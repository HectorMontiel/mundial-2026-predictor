#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Prueba de regresión: la app no debe hundirse cuando entran DOS usuarios.

Reproduce el fallo que reportó el usuario ("cuando dos personas se conectan a
la app, se cae") con dos sesiones reales de Streamlit en el mismo proceso, que
es exactamente como funciona Streamlit Cloud: un proceso, una hebra por sesión.

Lo que se comprueba:

  1. Dos sesiones simultáneas NO lanzan dos barridos de alpha_finder.
     Medido en _v86_barrido_concurrente.py: un barrido pica a 1297,7 MB y dos
     a la vez a 2172,2 MB, que es lo que mataba al contenedor.

  2. Entrar en una sesión nueva NO borra el caché de quien ya estaba dentro.

  3. El caché de motores de liga tiene techo, para que navegar por muchas
     ligas no crezca sin freno (49,8 MB por liga, 56 ligas disponibles).

  4. El log de deriva se escribe de forma atómica (sin lecturas corruptas).
"""
import io
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fallos = []


def _sin_precalculo():
    """Aparta el precálculo del camino mientras se prueba el cerrojo.

    POR QUÉ HACE FALTA, Y POR QUÉ NO ES HACER TRAMPA
    Este fichero prueba UNA cosa: que N sesiones simultáneas no lancen N
    barridos. Cuando se escribió (v86) el guardia sólo tenía el cerrojo.

    La v220 le puso delante el día cocinado: si hay un `pronostico_dia.json`
    fresco, el guardia lo sirve y NO llama a `calcular` — que es justo lo que
    debe hacer en producción, porque un barrido pica a 1,3 GB y el servidor
    tiene 1 GB. Con eso, el test quedó a merced de si el fichero del día
    estaba fresco o no: con precálculo fresco contaba cero barridos y fallaba;
    sin él, pasaba. Nada que ver con la concurrencia.

    Así que aquí se aparta el precálculo a propósito, y lo que queda medido es
    el cerrojo, que es lo que este fichero dice que mide. El camino del
    precálculo tiene sus propias pruebas.
    """
    import precalculo_dia as pre
    previo = (pre.FICHERO, pre.SOLO_PRECALCULO, pre.mas_nuevo_publicado)
    pre.FICHERO = '_no_existe_a_proposito.json'
    pre.SOLO_PRECALCULO = False
    pre.mas_nuevo_publicado = lambda *a, **k: None
    return pre, previo


def _devolver_precalculo(pre, previo):
    pre.FICHERO, pre.SOLO_PRECALCULO, pre.mas_nuevo_publicado = previo


def ok(cond, msg, detalle=''):
    if cond:
        print(f'OK    {msg}')
    else:
        print(f'FALLO {msg} {detalle}')
        fallos.append(msg)


# --------------------------------------------------------------------------
# 1 y 2 — dos sesiones a la vez sobre el barrido caro
# --------------------------------------------------------------------------
def prueba_dos_sesiones():
    """
    Se prueba el guardia directamente y no con dos `AppTest` porque AppTest no
    admite dos instancias concurrentes en el mismo proceso (la segunda pierde el
    Runtime y expira). Lo que importa aquí es la política de concurrencia, y eso
    es exactamente lo que vive en guardia_barrido.
    """
    print('\n=== N sesiones simultáneas pidiendo el barrido ===')
    import guardia_barrido

    # el disco tambien: un .cache_barrido.pkl de una pasada anterior
    # haria que la primera llamada se sirviera de el sin barrer
    guardia_barrido.reiniciar(borrar_disco=True)

    solapes = []
    dentro = [0]
    lock = threading.Lock()

    def barrido_falso():
        # Un barrido real tarda ~90 s y pica a 1,3 GB; aquí basta con que dure
        # lo suficiente para que las demás hebras lleguen mientras corre.
        with lock:
            dentro[0] += 1
            if dentro[0] > 1:
                solapes.append(dentro[0])
        time.sleep(1.0)
        with lock:
            dentro[0] -= 1
        return {'capa1': [], 'capa2': [], 'candidatos': []}

    N = 5
    resultados = {}

    def sesion(i):
        try:
            resultados[i] = guardia_barrido.barrido(barrido_falso)
        except Exception as e:
            resultados[i] = f'ERROR {type(e).__name__}: {e}'

    hilos = [threading.Thread(target=sesion, args=(i,)) for i in range(N)]
    t0 = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    dt = time.time() - t0

    est = guardia_barrido.estadisticas()
    ok(not solapes, f'nunca hay dos barridos a la vez (solapes: {solapes})')
    ok(est['barridos'] == 1,
       f'{N} sesiones simultáneas provocan UN solo barrido '
       f'(hubo {est["barridos"]})')
    ok(all(isinstance(r, dict) for r in resultados.values()),
       f'las {N} sesiones reciben resultado sin excepciones',
       str([r for r in resultados.values() if not isinstance(r, dict)])[:200])
    ok(dt < 3.0,
       f'las sesiones que esperan no repiten el trabajo ({dt:.1f}s para {N})')

    # y una segunda tanda debe servirse del caché, sin recalcular
    guardia_barrido.barrido(barrido_falso)
    ok(guardia_barrido.estadisticas()['barridos'] == 1,
       'una petición posterior reutiliza el resultado fresco')

    # forzar sí debe recalcular (es el botón "Actualizar ahora")
    guardia_barrido.barrido(barrido_falso, forzar=True)
    ok(guardia_barrido.estadisticas()['barridos'] == 2,
       'forzar=True sí recalcula (botón Actualizar ahora)')

    # ...pero N usuarios pulsando "Actualizar" a la vez siguen dando UN barrido
    #
    # v271 — `borrar_disco=True`, y no es un detalle. `reiniciar()` a secas
    # vacía la memoria pero deja el `.cache_barrido.pkl` que los barridos de
    # arriba acaban de escribir, así que la llamada siguiente se servía DEL
    # DISCO sin llamar a `calcular` y el contador se quedaba en cero. Lo que
    # se quiere medir aquí es qué pasa al forzar, y para eso hay que empezar
    # sin nada en ningún sitio.
    guardia_barrido.reiniciar(borrar_disco=True)
    guardia_barrido.barrido(barrido_falso)          # deja algo fresco
    solapes.clear()

    def sesion_forzada(i):
        guardia_barrido.barrido(barrido_falso, forzar=True)

    hilos = [threading.Thread(target=sesion_forzada, args=(i,))
             for i in range(N)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    est2 = guardia_barrido.estadisticas()
    ok(not solapes,
       f'ni forzando hay dos barridos a la vez (solapes: {solapes})')
    ok(est2['barridos'] == 2,
       f'{N} usuarios pulsando Actualizar a la vez = 1 barrido nuevo '
       f'(total {est2["barridos"]})')

    guardia_barrido.reiniciar(borrar_disco=True)

    fuente = open('dashboard_ui.py', encoding='utf-8').read()
    ok('guardia_barrido.barrido' in fuente,
       'el dashboard pasa por el guardia')
    # v271 — ESTA COMPROBACIÓN SE ACTUALIZA PORQUE EL BOTÓN YA NO EXISTE.
    #
    # Hasta aquí se exigía `_forzar_barrido` en el código, que era el forzado
    # por sesión del botón «Actualizar ahora». Ese botón se retiró en la v236
    # —está anotado en `dashboard_ui.py`— y con él la variable, así que la
    # comprobación llevaba desde entonces fallando por buscar algo que ya no
    # tenía que estar.
    #
    # Lo que SÍ hay que seguir garantizando es lo de fondo: que ninguna
    # pantalla pueda disparar un barrido de 1,3 GB en un servidor de 1 GB. O
    # sea que nadie llame al barrido con `forzar=True`.
    import re
    ok(not re.search(r'barrido_universal\(\s*(forzar\s*=\s*True|True)',
                     fuente),
       'ninguna pantalla fuerza un barrido nuevo (el botón se retiró en v236)')


# --------------------------------------------------------------------------
# 3 — techo del caché de motores de liga
# --------------------------------------------------------------------------
def prueba_techo_ligas():
    print('\n=== techo de memoria del caché de ligas ===')
    fuente = open('dashboard_ui.py', encoding='utf-8').read()
    ok('max_entries=MAX_LIGAS_EN_MEMORIA' in fuente,
       'cargar_motor_liga tiene max_entries (si no, crece sin freno)')

    import re
    m = re.search(r"MAX_LIGAS_EN_MEMORIA = int\(os\.environ\.get\("
                  r"'MAX_LIGAS_EN_MEMORIA', '(\d+)'\)\)", fuente)
    ok(m is not None, 'el techo es configurable por variable de entorno')
    if m:
        n = int(m.group(1))
        ok(1 <= n <= 12, f'el techo por defecto es razonable ({n} ligas)')
        # 49,8 MB por liga medidos en _v86_huella_total.py, sobre 625 MB fijos
        proyeccion = 625 + n * 49.8
        ok(proyeccion < 1400,
           f'la proyección de RSS con el techo cabe holgadamente '
           f'({proyeccion:.0f} MB con {n} ligas)')


# --------------------------------------------------------------------------
# 4 — escritura atómica del log de deriva
# --------------------------------------------------------------------------
def prueba_escritura_atomica():
    print('\n=== escritura atómica bajo concurrencia ===')
    import json
    import os
    import io_atomico

    ruta = '_test_conc_atomica.json'
    rotas = []
    lock = threading.Lock()

    def faena(idx):
        datos = {f'k{i}': list(range(60)) for i in range(60)}
        for v in range(40):
            datos[f'k{idx}'] = [v] * 60
            io_atomico.escribir_json(ruta, datos)
            # Se lee con leer_json, que es la API real que usa el código de
            # producción. Lo que se vigila es que NUNCA se devuelva un JSON a
            # medias: o sale el contenido entero, o sale el valor por defecto.
            # (Antes, con `open(w)` directo, se leía truncado un 34,4 % de las
            # veces y eso pasaba por dato bueno.)
            leido = io_atomico.leer_json(ruta, None)
            if leido is None or not isinstance(leido, dict) or len(leido) != 60:
                with lock:
                    rotas.append(f'lectura incompleta: {type(leido).__name__} '
                                 f'{len(leido) if hasattr(leido, "__len__") else "?"}')

    io_atomico.escribir_json(ruta, {'inicial': 1})
    hilos = [threading.Thread(target=faena, args=(i,)) for i in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    ok(not rotas, f'ninguna lectura corrupta con 6 hebras ({len(rotas)} rotas)',
       rotas[0] if rotas else '')

    sobrantes = [f for f in os.listdir('.')
                 if f.startswith(ruta) and f.endswith('.tmp')]
    ok(not sobrantes, f'no quedan temporales sueltos ({sobrantes})')
    for f in [ruta] + sobrantes:
        try:
            os.remove(f)
        except Exception:
            pass

    fuente = open('prediction_api.py', encoding='utf-8').read()
    ok('io_atomico.escribir_json' in fuente,
       'el monitor de deriva usa escritura atómica')
    ok('MAX_CRUCES_LOG' in fuente,
       'el log de deriva tiene techo de tamaño')


# --------------------------------------------------------------------------
# 5 — el arranque no se repite por visitante
# --------------------------------------------------------------------------
def prueba_arranque():
    print('\n=== el refresco de arranque es por proceso, no por visitante ===')
    fuente = open('dashboard_ui.py', encoding='utf-8').read()
    ok('_refresco_de_arranque' in fuente and
       '@st.cache_resource\ndef _refresco_de_arranque' in fuente,
       'el refresco vive en cache_resource (una vez por proceso)')
    # Se miran sólo las líneas de CÓDIGO: los comentarios de v86 explican el
    # fallo antiguo y contienen la llamada como texto.
    cabecera = fuente[:fuente.index('COLORES = {')]
    codigo = [ln for ln in cabecera.splitlines()
              if ln.strip() and not ln.strip().startswith('#')]
    ok(not any('cache_data.clear()' in ln for ln in codigo),
       'entrar en la app ya NO borra el caché de los demás')
    ok("st.session_state['_refresco_inicial']" not in fuente,
       'ya no se usa session_state para el refresco (era por visitante)')


def prueba_reparacion_entre_hilos():
    """
    v88 — La reparación de modelos parchea `Booster.__setstate__`, que es GLOBAL
    al proceso, y el barrido corre sus cuatro ramas en un ThreadPoolExecutor.

    Mientras el hilo de fútbol tenía el parche puesto, el hilo de MLB cargaba
    SU modelo a través del parche ajeno. El resultado, varios pasos más tarde:

        OSError: exception: access violation reading 0x0000000000000000

    dentro de `XGBoosterPredict` — y en el barrido salía como «MLB omitido por
    error», dejando el deporte fuera de las Apuestas del Día.
    """
    print('\n=== reparar modelos desde varios hilos a la vez ===')
    import glob
    import os

    import joblib
    import numpy as np
    import modelos_portables as mp

    fuente = open('modelos_portables.py', encoding='utf-8').read()
    ok('_CERROJO' in fuente, 'la reparación va bajo cerrojo')
    ok('threading.get_ident() != hilo' in fuente,
       'el parche sólo actúa sobre el hilo que lo puso')

    rutas = sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib')))
    if len(rutas) < 4:
        print('  (menos de 4 modelos; se omite)')
        return

    errores, resultados = [], {}
    lock = threading.Lock()

    def cargar(i, ruta):
        try:
            m = mp.cargar(ruta)
            n = getattr(m, 'n_features_in_', None)
            if n:
                p = m.predict_proba(np.random.RandomState(i).randn(4, n))
                with lock:
                    resultados[i] = bool(np.all(np.isfinite(p)))
            else:
                with lock:
                    resultados[i] = True
        except Exception as e:
            with lock:
                errores.append(f'{os.path.basename(os.path.dirname(ruta))}: '
                               f'{type(e).__name__}: {str(e)[:60]}')

    hilos = [threading.Thread(target=cargar, args=(i, r))
             for i, r in enumerate(rutas[:8])]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    ok(not errores, f'8 modelos cargados en paralelo sin errores ({errores[:2]})')
    ok(all(resultados.values()) and len(resultados) >= 1,
       f'y todos predicen valores finitos ({len(resultados)} probados)')

    # y después de todo eso, un modelo distinto debe seguir prediciendo:
    # es lo que fallaba (MLB reventaba DESPUÉS, no durante)
    try:
        from engines.mlb_engine import MLBEngine
        eng = MLBEngine().cargar_modelo()
        # v98 — un modelo del CI que no abre en Windows NO es este fallo.
        #
        # `modelos/mlb/` lo publica el reentrenamiento nocturno, que corre en
        # Linux, y sus boosters de XGBoost no siempre se pueden leer en
        # Windows: da «input stream corrupted». Es una condición conocida y
        # documentada del entorno de desarrollo (v87, `modelos_portables`), no
        # una regresión de concurrencia, que es lo que este test mide. Se
        # distingue explícitamente en vez de dejar que tiña de rojo la suite:
        # cualquier OTRO motivo por el que MLB no prediga sigue siendo un fallo.
        import modelos_portables as _mp
        if not eng.listo and _mp.es_error_de_plataforma(Exception(eng.error or '')):
            print(f'  ·  MLB omitida: el modelo del CI no abre en esta '
                  f'plataforma ({eng.error}) — condición conocida, no es '
                  f'un fallo de concurrencia.')
        else:
            pred = eng.predecir('NYA', 'BOS') if eng.listo else {}
            ok('prob_home' in pred,
               f'MLB sigue prediciendo después de las reparaciones ({list(pred)[:3]})')
    except Exception as e:
        ok(False, f'MLB sigue vivo tras las reparaciones ({type(e).__name__}: '
                  f'{str(e)[:60]})')


def main():
    print('=' * 60)
    print('v86 · PRUEBA DE CONCURRENCIA (dos usuarios a la vez)')
    print('=' * 60)
    prueba_arranque()
    prueba_techo_ligas()
    prueba_escritura_atomica()
    prueba_reparacion_entre_hilos()
    # el cerrojo se prueba con el precálculo apartado: ver `_sin_precalculo`
    _pre, _previo = _sin_precalculo()
    try:
        prueba_dos_sesiones()
    finally:
        _devolver_precalculo(_pre, _previo)

    print('\n' + '=' * 40)
    if fallos:
        print(f'{len(fallos)} FALLOS:')
        for f in fallos:
            print(f'  - {f}')
        sys.exit(1)
    print('TODO OK')


if __name__ == '__main__':
    main()
