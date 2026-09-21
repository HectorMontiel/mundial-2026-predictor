#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test del semáforo de la Capa 1 (v274).

Lo que se vigila es lo contrario de lo intuitivo, que es justo donde el código
se puede torcer sin que nadie lo note:

  · una ventaja ENORME tiene que salir en ROJO, no en verde. Es la firma de un
    precio rancio: la banda de EV 20-50 % da p5 -25,38 %.
  · una cuota BAJA no puede ser verde por mucho que acierte: ese grupo apenas
    empata (p5 -5,57 %).
  · el orden es por calidad medida, no por probabilidad de acertar.
  · y nada de esto puede lanzar, porque va dentro del render.

Ejecutar:  .venv\\Scripts\\python test_semaforo.py
"""

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_clasificacion():
    import semaforo_capa1 as sm

    v = sm.clasificar({'ev': 0.045, 'cuota': 2.85, 'cuota_justa': 2.61,
                       'validado': True})
    check(v['nivel'] == sm.VERDE, 'EV 4,5 % con cuota 2,85 es VERDE')
    check('Métela' in v['titulo'], 'y el título lo dice sin rodeos')

    r = sm.clasificar({'ev': 0.39, 'cuota': 2.90, 'validado': True})
    check(r['nivel'] == sm.ROJO,
          'EV del 39 % es ROJO aunque la cuota sea buena')
    check('viejo' in r['porque'] or 'error' in r['porque'],
          'y explica que es un precio malo, no una ganga')

    b = sm.clasificar({'ev': 0.05, 'cuota': 1.60, 'validado': True})
    check(b['nivel'] == sm.AMBAR,
          'cuota baja NO es verde aunque el EV este en banda')

    nv = sm.clasificar({'ev': 0.045, 'cuota': 2.85, 'validado': False})
    check(nv['nivel'] == sm.AMBAR,
          'un deporte sin validar no puede ser verde')

    # los bordes exactos de la banda medida
    check(sm.clasificar({'ev': 0.019, 'cuota': 2.85,
                         'validado': True})['nivel'] == sm.AMBAR,
          'por debajo del 2 % de EV ya no es verde')
    check(sm.clasificar({'ev': 0.101, 'cuota': 2.85,
                         'validado': True})['nivel'] == sm.AMBAR,
          'por encima del 10 % de EV tampoco')
    check(sm.clasificar({'ev': 0.05, 'cuota': 4.5,
                         'validado': True})['nivel'] == sm.AMBAR,
          'una cuota de 4,5 se sale de la banda medida')


def probar_orden():
    import semaforo_capa1 as sm

    picks = [
        {'partido': 'roja', 'ev': 0.35, 'cuota': 3.0, 'validado': True},
        {'partido': 'ambar', 'ev': 0.012, 'cuota': 1.7, 'validado': True},
        {'partido': 'verde', 'ev': 0.05, 'cuota': 2.6, 'validado': True},
    ]
    o = sm.ordenar(picks)
    check([p['partido'] for p in o] == ['verde', 'ambar', 'roja'],
          'verde primero, roja al final (salio %s)'
          % [p['partido'] for p in o])
    check(all('semaforo' in p for p in o), 'todas salen con su semaforo')
    check(len(o) == 3, 'no se pierde ninguna por el camino')

    # LA COMPROBACION QUE IMPORTA: la que mas acierta NO va primera
    picks2 = [
        {'partido': 'acierta mucho', 'ev': 0.03, 'cuota': 1.40,
         'prob': 0.70, 'validado': True},
        {'partido': 'paga mucho', 'ev': 0.04, 'cuota': 3.00,
         'prob': 0.34, 'validado': True},
    ]
    o2 = sm.ordenar(picks2)
    check(o2[0]['partido'] == 'paga mucho',
          'delante va la que PAGA, no la que mas acierta: es lo medido')

    check(sm.ordenar([]) == [], 'una lista vacia no rompe nada')
    check(sm.ordenar(None) == [], 'None tampoco')


def probar_resumen():
    import semaforo_capa1 as sm

    o = sm.ordenar([
        {'partido': 'v1', 'ev': 0.04, 'cuota': 2.5, 'validado': True},
        {'partido': 'v2', 'ev': 0.06, 'cuota': 3.0, 'validado': True},
        {'partido': 'a1', 'ev': 0.01, 'cuota': 1.5, 'validado': True},
        {'partido': 'r1', 'ev': 0.30, 'cuota': 3.0, 'validado': True},
    ])
    t = sm.resumen(o)
    check('mete las 2 primeras' in t, 'dice cuantas meter: %s' % t)
    check('déjalas' in t, 'y cuales dejar')

    t2 = sm.resumen(sm.ordenar([
        {'partido': 'a', 'ev': 0.01, 'cuota': 1.5, 'validado': True}]))
    check('no hay ninguna de las buenas' in t2,
          'sin verdes lo dice y explica que es normal: %s' % t2)
    check(sm.resumen([]) == '', 'sin picks no dice nada')


def probar_no_lanza():
    import semaforo_capa1 as sm

    for malo in ({}, {'ev': None, 'cuota': None}, {'ev': 'x', 'cuota': 'y'},
                 {'ev': float('nan'), 'cuota': 2.0}):
        try:
            c = sm.clasificar(malo)
            check(c.get('nivel') in (sm.VERDE, sm.AMBAR, sm.ROJO),
                  'con %r devuelve un nivel valido' % malo)
        except Exception as e:
            check(False, 'clasificar lanzo con %r: %r' % (malo, e))
    try:
        sm.ordenar([{'ev': 'x'}, None, 7])
        check(True, 'ordenar aguanta una lista con basura dentro')
    except Exception as e:
        check(False, 'ordenar lanzo con basura: %r' % e)


def probar_cortes():
    """Los cortes son los medidos. Si alguien los cambia, que se vea."""
    import semaforo_capa1 as sm
    check(sm.EV_MIN_VERDE == 0.02 and sm.EV_MAX_VERDE == 0.10,
          'la banda de EV verde es 2-10 %, que es la medida')
    check(sm.CUOTA_MIN_VERDE == 2.20 and sm.CUOTA_MAX_VERDE == 4.00,
          'la banda de cuota verde es 2,20-4,00, que es la medida')
    check(sm.EV_ROJO == 0.20, 'el rojo empieza en el 20 % de EV')


if __name__ == '__main__':
    print('=== 1. clasificacion ===')
    probar_clasificacion()
    print('\n=== 2. el orden ===')
    probar_orden()
    print('\n=== 3. el resumen ===')
    probar_resumen()
    print('\n=== 4. nunca lanza ===')
    probar_no_lanza()
    print('\n=== 5. los cortes medidos ===')
    probar_cortes()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
