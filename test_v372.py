#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v372.

El usuario (12-oct): «también debe haber ganador, que es lo que más cuota da
normalmente, pero sólo cuando la casa también esté a favor».

Lo que se vigila (`sencillas`):
  1. 🔷 primero si el modelo está de acuerdo (`lo_mejor.del_pick_riesgo`).
  2. Si no, 🏠 el favorito de la casa: sin margen al 62-70 % y cuota
     1,35-1,60; el que no es favorito, o fuera de esas bandas, no entra.
  3. Una por partido; «más seguras» pone primero las 🎯 y «más cuota» los
     ganadores; el boleto multiplica lo medido de cada pata (78 / 72 / 68 %).
  4. Lo medido queda guardado y la pantalla tiene el selector.

Ejecutar:  python test_v372.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _tab(ph, ch, pa, ca):
    return {'1x2': {'home': ph, 'draw': round(1 - ph - pa, 3), 'away': pa},
            '1x2_cuotas': {'home': ch, 'draw': 4.0, 'away': ca},
            'goles': {'1.5': {'p': 0.74, 'mas': 1.30, 'menos': 3.5}}}


def probar():
    import lo_mejor as lm
    import mercado_implicito as mi
    import sencillas as se
    tabs = {'Fav FC': _tab(0.64, 1.50, 0.15, 6.0),       # 🏠 sí
            'Flojo FC': _tab(0.55, 1.75, 0.20, 4.0),     # fuera: casa < 62 %
            'Caro FC': _tab(0.66, 1.30, 0.12, 7.0),      # fuera: cuota < 1,35
            'Model FC': _tab(0.60, 1.55, 0.18, 5.0)}     # 🔷 (modelo de acuerdo)
    v1, v2 = mi.del_partido, lm.del_pick_riesgo
    mi.del_partido = lambda h, a, **k: tabs.get(h, {})
    lm.del_pick_riesgo = lambda p: ({'apuesta': 'Gana Model FC', 'prob': 0.74, 'p_mercado': 0.60,
                                     'cuota': 1.55, 'casa': 'Playdoit'}
                                    if p['partido'].startswith('Model') else None)
    try:
        ps = [{'partido': '%s vs Rival %d' % (h, i), 'deporte': 'Fútbol', 'clave_liga': 'x',
               'inicio': '2099-01-01T1%d:00:00Z' % i, 'fecha': '2099-01-01'}
              for i, h in enumerate(tabs)]
        g = {p['partido'].split(' vs ')[0]: se.ganador_del_partido(p) for p in ps}
        check(g['Fav FC'] and g['Fav FC']['icono'] == '🏠' and g['Fav FC']['prob'] == 0.68
              and g['Fav FC']['apuesta'] == 'Gana Fav FC' and g['Fav FC']['bloque'] == 'resultado',
              '🏠 el favorito de la casa al 62-70 % y cuota 1,35-1,60 entra (68 % medido)')
        check(g['Flojo FC'] is None and g['Caro FC'] is None,
              'fuera la casa por debajo del 62 % y la cuota por debajo de 1,35')
        check(g['Model FC'] and g['Model FC']['icono'] == '🔷' and g['Model FC']['prob'] == 0.72,
              '🔷 primero cuando el modelo está de acuerdo (72 %)')
        seg = se.con_ganador(ps, 'seguras', ahora=0)
        cuo = se.con_ganador(ps, 'cuota', ahora=0)
        check(len(seg) == 4 and len({x['partido'] for x in seg}) == 4
              and seg[0]['origen'] == 'casa70' and cuo[0]['origen'] == 'riesgo',
              'una por partido; «seguras» empieza por 🎯 y «cuota» por ganador')
        b = se.boleto([x for x in cuo if x['origen'] == 'riesgo'], 2)
        check(b and b['n_ganador'] == 2 and abs(b['prob'] - 0.72 * 0.68) < 1e-9,
              'el boleto multiplica lo medido de cada pata (%s)' % (b and round(b['prob'], 4)))
    finally:
        mi.del_partido, lm.del_pick_riesgo = v1, v2
    r = json.load(open('_v372_ganador_casa.json', encoding='utf-8'))
    f = r['casa 0.62-0.70 · cuota 1.35-1.60']
    check(f['A']['acierto'] > 0.66 and f['B']['acierto'] > 0.66 and f['2023']['acierto'] > 0.66,
          'lo medido queda guardado (67-69 % en las dos mitades y desde 2023)')
    src = open('sonadora_ui.py', encoding='utf-8').read()
    # v373 — la Soñadora por cuota mínima incluye el ganador con su casilla
    check("'Incluir ganador'" in src and 'sp.del_dia(' in src,
          'la pantalla deja incluir el ganador')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
