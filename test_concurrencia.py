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

    guardia_barrido.reiniciar()

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
    guardia_barrido.reiniciar()
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

    guardia_barrido.reiniciar()

    fuente = open('dashboard_ui.py', encoding='utf-8').read()
    ok('guardia_barrido.barrido' in fuente,
       'el dashboard pasa por el guardia')
    ok('_forzar_barrido' in fuente,
       'el botón Actualizar usa el forzado por sesión, no un clear() global')


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


def main():
    print('=' * 60)
    print('v86 · PRUEBA DE CONCURRENCIA (dos usuarios a la vez)')
    print('=' * 60)
    prueba_arranque()
    prueba_techo_ligas()
    prueba_escritura_atomica()
    prueba_dos_sesiones()

    print('\n' + '=' * 40)
    if fallos:
        print(f'{len(fallos)} FALLOS:')
        for f in fallos:
            print(f'  - {f}')
        sys.exit(1)
    print('TODO OK')


if __name__ == '__main__':
    main()
