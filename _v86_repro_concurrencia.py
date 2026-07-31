#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Por qué se cae la app cuando entra un segundo usuario?

Hipótesis
---------
dashboard_ui.py, al abrir una sesión NUEVA, ejecuta dos cosas globales:

    st.cache_data.clear()                      # borra el caché de TODOS
    for _mod in (...13 módulos...): reload()   # recarga módulos en caliente

Streamlit Cloud corre un solo proceso y una hebra por sesión. `cache_resource`
guarda objetos (ClubEngine, PredictionEngine) que son instancias de clases que
viven en esos módulos. Recargar un módulo mientras otra hebra ejecuta código de
ese módulo reescribe su __dict__ en caliente: durante la ventana de recarga los
globales quedan a medio construir, y las instancias cacheadas apuntan a una
clase que ya no es la del módulo.

Esta prueba no razona: lo ejecuta.

    Hebra A = usuario 1 prediciendo en bucle (motor ya cacheado).
    Hebra B = usuario 2 entrando -> el bloque de recarga del dashboard.

Si la hipótesis es cierta, A revienta o devuelve resultados corruptos.
"""
import importlib
import sys
import threading
import time
import traceback

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

MODULOS = ('config', 'name_mapper', 'fixtures_espn', 'odds_api',
           'source_resilience', 'betexplorer_scraper', 'edge_engine',
           'traductor_quant', 'league_engine', 'reto_escalera',
           'data_health', 'alpha_finder', 'bot_telegram')

LIGA = 'liga_mx'

errores_A = []
resultados_A = []
parar = threading.Event()


def usuario_1(motor, a, b):
    """Usuario que ya tenía la app abierta y sigue pulsando botones."""
    while not parar.is_set():
        try:
            r = motor.predecir(a, b)
            if 'error' in r:
                errores_A.append(('error-dict', r['error']))
            else:
                resultados_A.append(
                    r['prediction']['probabilities']['home'])
        except Exception as ex:
            errores_A.append((type(ex).__name__, str(ex)[:200]))
            errores_A.append(('TRACEBACK', traceback.format_exc()[-800:]))
        time.sleep(0.01)


def usuario_2_entra():
    """El bloque exacto que dashboard_ui.py ejecuta en cada sesión nueva."""
    recargados = 0
    for m in MODULOS:
        if m in sys.modules:
            try:
                importlib.reload(sys.modules[m])
                recargados += 1
            except Exception as ex:
                print(f'   reload({m}) fallo: {type(ex).__name__}: {ex}')
    return recargados


def main():
    print('=' * 78)
    print('v86 · REPRODUCCIÓN DE LA CAÍDA CON DOS USUARIOS')
    print('=' * 78)

    import league_engine
    clase_original = league_engine.ClubEngine

    print(f'\n[setup] usuario 1 carga el motor de {LIGA} (simula cache_resource)')
    t0 = time.time()
    motor = league_engine.ClubEngine(LIGA)
    print(f'        motor listo={getattr(motor, "listo", None)} '
          f'en {time.time() - t0:.1f}s')
    equipos = [t for t in motor.stats
               if isinstance(motor.stats[t], dict) and motor.stats[t].get('ELO')]
    equipos = sorted(equipos, key=lambda t: -motor.stats[t]['ELO'])
    a, b = equipos[0], equipos[-1]
    print(f'        partido de prueba: {a} vs {b}')

    base = motor.predecir(a, b)['prediction']['probabilities']['home']
    print(f'        P(local) antes de nada = {base:.4f}')

    print('\n[run] usuario 1 predice en bucle...')
    hilo = threading.Thread(target=usuario_1, args=(motor, a, b), daemon=True)
    hilo.start()
    time.sleep(1.5)
    n_antes = len(resultados_A)
    err_antes = len(errores_A)
    print(f'      {n_antes} predicciones OK, {err_antes} errores (línea base)')

    print('\n[run] >>> ENTRA EL USUARIO 2 (recarga de módulos) <<<')
    t1 = time.time()
    n_rec = usuario_2_entra()
    dt = time.time() - t1
    print(f'      {n_rec} módulos recargados en {dt:.2f}s')

    time.sleep(2.0)
    parar.set()
    hilo.join(timeout=5)

    err_despues = len(errores_A) - err_antes
    print('\n' + '=' * 78)
    print('RESULTADO')
    print('=' * 78)
    print(f'predicciones totales del usuario 1 : {len(resultados_A)}')
    print(f'errores ANTES de que entre usuario 2: {err_antes}')
    print(f'errores DESPUÉS                     : {err_despues}')

    clase_nueva = league_engine.ClubEngine
    print(f'\n¿la clase ClubEngine sigue siendo la misma objeto en memoria? '
          f'{clase_original is clase_nueva}')
    print(f'¿el motor cacheado es instancia de la clase NUEVA? '
          f'{isinstance(motor, clase_nueva)}')
    print(f'   (id clase vieja {id(clase_original)} · '
          f'nueva {id(clase_nueva)})')

    if errores_A[err_antes:]:
        print('\nErrores tras la entrada del usuario 2:')
        vistos = set()
        for tipo, msg in errores_A[err_antes:]:
            k = (tipo, msg[:120])
            if k in vistos:
                continue
            vistos.add(k)
            print(f'  · {tipo}: {msg[:400]}')

    print(f'\ntiempo de bloqueo por la recarga: {dt:.2f}s '
          f'(el usuario 2 espera esto ANTES de ver nada, y durante ese '
          f'tiempo el proceso está ocupado)')

    veredicto = 'CONFIRMADA' if (err_despues > 0 or clase_original is not clase_nueva) \
        else 'NO reproducida'
    print(f'\nHIPÓTESIS: {veredicto}')


if __name__ == '__main__':
    main()
