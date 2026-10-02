# -*- coding: utf-8 -*-
"""
v321 — pruebas: los córners sólo se meten con la línea lejos de lo esperado
(2,5 en el total, 2 en los de un equipo), medido.

Uso: python test_v321.py
"""
from __future__ import annotations

import json
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medido():
    m = json.load(open('_v321_corners_margen.json', encoding='utf-8'))
    b = m['backtest']
    for t in ('total', 'equipo'):
        x = b[t]
        check(x['acierto_con_margen'] > x['acierto_todas'] and x['p5_mejora'] > 0
              and x['primera_mitad'] > x['acierto_todas'] and x['segunda_mitad'] > x['acierto_todas'],
              '%s con margen ≥ %.1f: %.1f %% contra %.1f %% (p5 %+.1f; mitades %.1f / %.1f)'
              % (t, x['margen_minimo'], 100 * x['acierto_con_margen'], 100 * x['acierto_todas'],
                 100 * x['p5_mejora'], 100 * x['primera_mitad'], 100 * x['segunda_mitad']))
    check(b['conjunto']['despues'] - b['conjunto']['antes'] > 0.03,
          'córners en conjunto: %.1f %% → %.1f %%'
          % (100 * b['conjunto']['antes'], 100 * b['conjunto']['despues']))
    check(b['margen_1_5_total'] > 0.95, 'el 1,5 propuesto no filtra nada en el total (por eso 2,5)')
    s = m['tarjeta_simulada']
    check(s['todo_despues']['acierto'] > s['todo_antes']['acierto']
          and s['todo_despues']['rojos'] < s['todo_antes']['rojos'],
          'en la tarjeta simulada: %.1f %% → %.1f %%, %d → %d rojos'
          % (100 * s['todo_antes']['acierto'], 100 * s['todo_despues']['acierto'],
             s['todo_antes']['rojos'], s['todo_despues']['rojos']))


def probar_regla():
    import modo_modelo as mm
    lam = {'Total': 9.45, 'Local': 5.0, 'Visita': 4.4}

    def v(ap, et, L):
        return {'veredicto': 'meter', 'mercado': 'Córners',
                'pick': {'mercado': 'Córners', 'etiqueta': et, 'apuesta': ap, 'linea': L}}
    check(mm.corners_margen_corto(v('Córners: Menos de 10.5', 'Total', 10.5), lam) is not None,
          'Grecia–Países Bajos «menos de 10,5» con λ 9,45 (margen 1,05): ya no se mete')
    check(mm.corners_margen_corto(v('Córners: Menos de 12.5', 'Total', 12.5), lam) is None,
          '«menos de 12,5» con λ 9,45 (margen 3,05): sí')
    check(mm.corners_margen_corto(v('Córners Local: Más de 2.5', 'Local', 2.5), lam) is None,
          'equipo «más de 2,5» con λ 5,0 (margen 2,5): sí')
    check(mm.corners_margen_corto(v('Córners Visita: Menos de 5.5', 'Visita', 5.5), lam) is not None,
          'equipo «menos de 5,5» con λ 4,4 (margen 1,1): no')
    check(mm.corners_margen_corto(v('Córners: Más de 8.5', 'Total', 8.5), {}) is not None,
          'sin λ no se puede medir el margen: no se mete')
    g = {'veredicto': 'meter', 'mercado': 'Goles', 'pick': {'mercado': 'Goles', 'apuesta': 'Goles: Menos de 3.5'}}
    check(mm.corners_margen_corto(g, lam) is None, 'a los goles no se les aplica (medido: no ayuda)')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('corners_margen_corto(v, _lam_ck)' in src, 'la regla está en la decisión de «meter»')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medido()
    print('\n=== 2. la regla ===')
    probar_regla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
