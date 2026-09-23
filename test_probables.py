#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de las probables con buena cuota (v302).

Lo que se vigila:

  · LA REGLA ES LA MEDIDA, con sus números: visitante favorito, justa de
    Pinnacle >= 55 %, cuota >= 1,50. Atado a los NÚMEROS y no a las
    constantes: un check `x >= probables.PROB_MINIMA` se mide contra sí mismo
    y no puede fallar (lección de los mutantes).
  · EL LOCAL NO ENTRA: medido, el local favorito con buena cuota pierde
    (-1,49 % y -1,74 %). Es el hallazgo, no un detalle.
  · SI EL MODELO OPINA EN CONTRA, NO ENTRA. La versión de «sólo mercado» es
    para cuando el modelo no cubre la liga, no para cuando dice que no.
  · NUNCA SE OFRECE PINNACLE: ahí no se puede apostar.
  · LA ESCALERA LAS RECIBE, con su nivel y su número, y no las confunde con
    los niveles medidos de la Capa 1.
  · NO LANZA sin tablero.

Ejecutar:  python test_probables.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _tablero_falso():
    base = 4102444800          # 2100-01-01: nunca «ya empezó»
    return [
        # visitante favorito, bien pagado: ENTRA
        {'deporte': 'futbol', 'home': 'Local A', 'away': 'Visita A',
         'liga': 'Liga X', 'inicio': str(base)},
        # visitante favorito pero cuota corta (1,40): FUERA
        {'deporte': 'futbol', 'home': 'Local B', 'away': 'Visita B',
         'liga': 'Liga X', 'inicio': str(base)},
        # LOCAL favorito bien pagado: FUERA (el local no entra)
        {'deporte': 'futbol', 'home': 'Local C', 'away': 'Visita C',
         'liga': 'Liga X', 'inicio': str(base)},
        # visitante al 50 %: FUERA
        {'deporte': 'futbol', 'home': 'Local D', 'away': 'Visita D',
         'liga': 'Liga X', 'inicio': str(base)},
        # visitante favorito pero sólo Pinnacle lo paga: FUERA
        {'deporte': 'futbol', 'home': 'Local E', 'away': 'Visita E',
         'liga': 'Liga X', 'inicio': str(base)},
        # tenis: FUERA (sólo fútbol)
        {'deporte': 'tenis', 'home': 'J1', 'away': 'J2',
         'liga': 'ATP', 'inicio': str(base)},
        # visitante favorito, bien pagado, pero el MODELO dice que no
        {'deporte': 'futbol', 'home': 'Local F', 'away': 'Visita F',
         'liga': 'Liga X', 'inicio': str(base)},
    ]


PIN = {  # home, draw, away de Pinnacle
    'Local A': (4.6, 3.9, 1.72),   # justa visitante ~0,56
    'Local B': (4.6, 3.9, 1.72),
    'Local C': (1.60, 4.2, 5.8),
    'Local D': (2.9, 3.5, 2.05),
    'Local E': (4.6, 3.9, 1.72),
    'Local F': (4.6, 3.9, 1.72),
}
MEJOR = {'Local A': ('Calientemx', 1.62), 'Local B': ('Winpot', 1.40),
         'Local C': ('Novibet', 1.62), 'Local D': ('1xBet', 2.05),
         'Local E': ('Pinnacle', 1.72), 'Local F': ('Winpot', 1.62)}


def _parchear():
    import barrido_capa1 as bc
    import cuotas_multi as cm
    orig = (bc._tablero, cm.cuotas_partido, cm.precio_accionable)
    bc._tablero = lambda ruta=None: _tablero_falso()

    def cuotas_partido(dep, h, a, **kw):
        ph, pd_, pa = PIN.get(h, (None, None, None))
        return {'pinnacle': {'home': ph, 'draw': pd_, 'away': pa}, '_h': h}

    def precio_accionable(res, lado):
        casa, cuota = MEJOR.get(res.get('_h'), (None, None))
        if lado == 'away':
            return {'casa': casa, 'cuota': cuota}
        if lado == 'home' and res.get('_h') == 'Local C':
            return {'casa': casa, 'cuota': 1.70}
        return {}
    cm.cuotas_partido = cuotas_partido
    cm.precio_accionable = precio_accionable
    return orig


def _restaurar(orig):
    import barrido_capa1 as bc
    import cuotas_multi as cm
    bc._tablero, cm.cuotas_partido, cm.precio_accionable = orig


def probar_la_regla():
    import probables as pr
    check(abs(pr.PROB_MINIMA - 0.55) < 1e-9 and abs(pr.CUOTA_MINIMA - 1.50) < 1e-9,
          'la regla es la medida: 55 % y cuota 1,50')
    check(abs(pr.MEDIDO['ambos']['acierta'] - 0.680) < 1e-9
          and pr.MEDIDO['ambos']['n'] == 325,
          'y viaja con su número: 68 % sobre 325')
    orig = _parchear()
    try:
        pron = [{'deporte': 'Fútbol', 'partido': 'Local F vs Visita F',
                 'board': {'Gana Visita F': 0.40}},
                {'deporte': 'Fútbol', 'partido': 'Local A vs Visita A',
                 'board': {'Gana Visita A': 0.61}}]
        out = pr.barrer(pron)
    finally:
        _restaurar(orig)
    partidos = [p['partido'] for p in out]
    check(partidos == ['Local A vs Visita A'],
          'sólo entra el visitante favorito bien pagado (%s)' % partidos)
    if out:
        p = out[0]
        check(p['probable'] == 'ambos',
              'con el modelo de acuerdo es «ambos» (%s)' % p['probable'])
        check(p['casa'] == 'Calientemx' and abs(p['cuota'] - 1.62) < 1e-9,
              'con la casa y la cuota accionables')
        check(p['validado'] is False,
              'y NO se marca como ventaja validada: no pasa el p5')
        check(p['apuesta'] == 'Gana Visita A' and p['lado'] == 'away',
              'la apuesta es al visitante')
        check(0.55 <= p['prob'] < 0.60, 'con la probabilidad justa de Pinnacle')


def probar_la_escalera_las_recibe():
    import escalera as esc
    p = {'deporte': 'Fútbol', 'partido': 'Local A vs Visita A',
         'mercado': 'Ganador', 'apuesta': 'Gana Visita A', 'lado': 'away',
         'prob': 0.57, 'cuota': 1.62, 'ev': -0.08, 'casa': 'Calientemx',
         'probable': 'ambos', 'validado': False,
         'acierta_medido': 0.68, 'etiqueta_probable': 'Probable'}
    ops = esc.todas([p])
    check(len(ops) == 1, 'la Escalera ofrece la probable (%d)' % len(ops))
    if ops:
        nv = ops[0].get('nivel_escalera') or {}
        check(nv.get('probable') == 'ambos',
              'en su propio nivel, el de las probables')
        check(abs((nv.get('acierta') or 0) - 0.68) < 1e-9,
              'que dice lo que acierta: 68 %')
        check((ops[0].get('semaforo') or {}).get('nivel') != 'rojo',
              'y no la tumba el semáforo de la Capa 1, que mide otra cosa')
    # una de Capa 1 de verdad sigue entrando por los niveles medidos, y
    # una probable NO se cuela en ellos
    capa1 = {'deporte': 'Fútbol', 'partido': 'P vs Q', 'mercado': 'Ganador',
             'apuesta': 'Gana P', 'lado': 'home', 'prob': 0.52,
             'cuota': 2.00, 'ev': 0.04, 'margen_pin': 0.03}
    ops = esc.todas([capa1, dict(p, cuota=2.05, prob=0.56)])
    niveles = [(o['partido'], (o.get('nivel_escalera') or {}).get('probable'))
               for o in ops]
    check(('P vs Q', None) in niveles,
          'la de Capa 1 sigue en su nivel medido (%s)' % niveles)
    check(all(pb for par, pb in niveles if par == 'Local A vs Visita A'),
          'y la probable sólo sale en el suyo, nunca con el sello de otro')


def probar_no_lanza():
    import probables as pr
    import barrido_capa1 as bc
    orig = bc._tablero
    bc._tablero = lambda ruta=None: (_ for _ in ()).throw(OSError('x'))
    try:
        out = pr.barrer(None)
        check(out == [], 'sin tablero devuelve lista vacía, sin lanzar')
    except Exception as e:
        check(False, 'lanzó %s' % e)
    finally:
        bc._tablero = orig


def probar_la_pantalla():
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check('probables' in src, 'la pantalla usa las probables')
    i = src.find('def render_escalera')
    esc = src[i:src.find('\ndef ', i + 10)]
    check('probables' in esc or '_probables_en_vivo' in esc,
          'y la Escalera las recibe')


if __name__ == '__main__':
    print('=== 1. la regla ===')
    probar_la_regla()
    print('\n=== 2. la Escalera las recibe ===')
    probar_la_escalera_las_recibe()
    print('\n=== 3. no lanza ===')
    probar_no_lanza()
    print('\n=== 4. la pantalla ===')
    probar_la_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
