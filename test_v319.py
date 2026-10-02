# -*- coding: utf-8 -*-
"""
v319 — pruebas: nada estimado en córners, tarjetas ni remates; histórico real
(5+ partidos de cada equipo esta temporada) o «🚫 SIN HISTÓRICO REAL»; el total
de córners es la suma de los dos equipos; córners reales de FotMob donde el
histórico no los trae, con su backtest.

Uso: python test_v319.py
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
    m = json.load(open('_v319_conteos_reales.json', encoding='utf-8'))
    c = m['corners']
    f = c['franja_70_80']
    check(c['con_historico_real'] >= 200 and f['datos_reales']['acierto'] >= 0.72,
          'córners con datos reales: %d partidos, %.1f %% en la franja 70-80 %% (umbral 72 %%)'
          % (c['con_historico_real'], 100 * f['datos_reales']['acierto']))
    check(f['reales_liga_completa']['partidos'] > 0 and f['reales_liga_parcial']['partidos'] > 0,
          'separado por liga completa (%.1f %%) y parcial (%.1f %%)'
          % (100 * f['reales_liga_completa']['acierto'], 100 * f['reales_liga_parcial']['acierto']))
    check(c['total']['adopta_suma'] and c['total']['p5'] > 0,
          'el total como suma de los dos equipos le gana a la media de la competición (p5 %+.5f)'
          % c['total']['p5'])
    t = m['produccion_tarjetas']['franja_70_80']['observado_con_historico_real']
    check(t['acierto'] >= 0.72, 'tarjetas con histórico real: %.1f %%' % (100 * t['acierto']))
    cf = json.load(open('corners_fotmob.json', encoding='utf-8'))
    o = cf['franja_70_80_ligas_sin_historico']
    check(cf['activo'] and o['partidos'] >= 200 and o['acierto'] >= 0.72,
          'córners reales de FotMob en las ligas sin histórico: %d partidos, %.1f %%'
          % (o['partidos'], 100 * o['acierto']))


def probar_puerta():
    import pandas as pd
    import historico_real as hr
    import rendimiento_equipos as rq
    d = pd.DataFrame({'date': pd.date_range('2026-08-01', periods=12, freq='7D'),
                      'home_team': ['A', 'B', 'C'] * 4, 'away_team': ['B', 'C', 'A'] * 4,
                      'home_goals': 1, 'away_goals': 0,
                      'home_corners': 5.0, 'away_corners': 3.0})
    o1, o2 = rq._historico, rq.stats_disponibles
    try:
        rq._historico = lambda clave: d
        rq.stats_disponibles = lambda clave: {'corners': True, 'tarjetas': False}
        hr._MEMO.clear()
        e = hr.evaluar('x', 'A', 'B', 'corners', '2026-10-30')
        e4 = hr.evaluar('x', 'A', 'B', 'corners', '2026-08-20')
        sin = hr.evaluar('x', 'A', 'B', 'tarjetas', '2026-10-30')
    finally:
        rq._historico, rq.stats_disponibles = o1, o2
        hr._MEMO.clear()
    check(e['ok'] and e['n_local'] == 8 and e['prom_local_casa'] == 5.0
          and e['prom_visita_fuera'] == 3.0,
          'con 5+ partidos de cada uno hay histórico real, con promedios en su papel')
    check(not e4['ok'] and 'mínimo 5' in e4['motivo'], 'con menos de 5, no (y dice por qué)')
    check(not sin['ok'] and 'no publica' in sin['motivo'],
          'si la competición no publica la estadística, no hay nada')

    orig = rq._corners_equipo_crudo
    try:
        rq._corners_equipo_crudo = lambda c, h, a, n=10: {'origen': 'estimado',
                                                          'lambda_home': 5, 'lambda_away': 4}
        check(rq.corners_equipo('premier', 'A', 'B') is None or
              rq.corners_equipo('premier', 'A', 'B').get('origen') != 'estimado',
              'un bloque estimado nunca sale')
    finally:
        rq._corners_equipo_crudo = orig
    r = rq.corners_equipo('selecciones', 'Greece', 'Netherlands')
    check(r and r['historico_real'] and abs(r['lambda_total'] - r['lambda_home'] - r['lambda_away']) < 1e-6,
          'con histórico real: total = suma de los dos equipos (%.1f)' % (r or {}).get('lambda_total', 0))


def probar_salida():
    import formato_ia as fi
    pick = {'deporte': 'Fútbol', 'partido': 'Greece vs Netherlands', 'clave_liga': 'selecciones'}
    L = fi._bloque_conteo(pick, 'corners', 'Córners')
    t = '\n'.join(L)
    check('datos reales' in t and 'λ total esperado' in t and 'promedio histórico en casa' in t
          and 'Más de 8.5' in t and 'Menos de 10.5' in t,
          'Telegram: córners con el formato pedido (datos reales, λ total, promedios, líneas)')
    L2 = fi._bloque_conteo({'deporte': 'Fútbol', 'partido': 'Zz vs Yy', 'clave_liga': 'premier'},
                           'corners', 'Córners')
    check(L2 and '🚫 SIN HISTÓRICO REAL' in L2[0], 'sin histórico real: «🚫 SIN HISTÓRICO REAL»')
    check('[estimado]' not in open('formato_ia.py', encoding='utf-8').read().split('GUIA = ')[1].split('"""')[2],
          'el documento ya no escribe «[estimado]»')
    import modo_modelo as mm
    h = mm._sin_historico_html({'deporte': 'Fútbol', 'partido': 'Zz vs Yy', 'clave_liga': 'premier'},
                               'corners', '⛳')
    check('SIN HISTÓRICO REAL' in h, 'la tarjeta dice «SIN HISTÓRICO REAL» en vez del estimado')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medido()
    print('\n=== 2. la puerta del histórico real ===')
    probar_puerta()
    print('\n=== 3. la salida ===')
    probar_salida()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
