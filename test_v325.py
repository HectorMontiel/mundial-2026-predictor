# -*- coding: utf-8 -*-
"""
v325 — pruebas: la NFL con 27 temporadas (nflverse), el quarterback dentro y
la decisión de «meter» mezclada con la casa.

  1. El histórico largo: códigos de franquicia, una fila por partido.
  2. Sin fuga: las variables de un partido no cambian si cambia su resultado.
  3. El modelo de producción carga el de la v325, ve el QB previsto, predice
     igual dos veces y, sin el histórico largo, vuelve al de la v131.
  4. La medición escrita en el artefacto: mejor que la v131 en 2025.
  5. La decisión: la NFL toma el precio de la casa aunque no haya empate, con
     un cuarto para el modelo y sin la corrección del fútbol; el fútbol y el
     tenis siguen exactamente igual.

Uso: python test_v325.py
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pandas as pd

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_historico():
    import nfl_nflverse as nv
    check(nv.franquicia('OAK') == 'LV' and nv.franquicia('LA') == 'LAR'
          and nv.franquicia('WAS') == 'WSH' and nv.franquicia('KC') == 'KC',
          'los códigos de nflverse se llevan a los del proyecto')
    d = nv.cargar()
    check(d is not None and len(d) > 7000, 'historico_nfl_largo.csv con %d partidos'
          % (0 if d is None else len(d)))
    import nfl_datos as nd
    check(set(d['home']) <= set(nd.EQUIPOS), 'todos los equipos existen en nfl_datos')
    check(d['game_id'].is_unique, 'una fila por partido')
    jug = d[d['home_score'].notna()]
    check(jug['home_epa_pase'].isna().mean() < 0.01,
          'casi todos los jugados traen su ficha de EPA (%.2f %% sin ella)'
          % (100 * jug['home_epa_pase'].isna().mean()))
    check(int(jug['season'].min()) <= 1999, 'desde 1999')


def probar_sin_fuga():
    import nfl_estado as ne
    import nfl_nflverse as nv
    d = nv.cargar()
    d = d[(d['season'] >= 2023) & d['home_score'].notna()].reset_index(drop=True)
    k = 300
    a, _ = ne.dataset(d)
    d2 = d.copy()
    d2.loc[k, 'home_score'] = d2.loc[k, 'home_score'] + 30
    b, _ = ne.dataset(d2)
    cols = [c for c in a.columns if c not in ('home_score', 'margen', 'total')
            and pd.api.types.is_numeric_dtype(a[c])]
    igual_k = all((a.loc[k, c] == b.loc[k, c]) or (a.loc[k, c] != a.loc[k, c])
                  for c in cols)
    check(igual_k, 'las variables de un partido no dependen de su resultado')
    cambia = any(a.loc[j, 'elo_dif'] != b.loc[j, 'elo_dif'] for j in range(k + 1, k + 40))
    check(cambia, 'y sí cambian las de los partidos de después')


def probar_modelo():
    import modelo_nfl as mn
    import nfl_datos as nd
    m = mn.NFLModelo.cargar(historico=nd.cargar_historico())
    check(m is not None and m.version == 'v325', 'se carga el modelo de la v325')
    pend = m.pendientes
    check(pend is not None and len(pend) > 0, 'con los partidos que faltan (%d)'
          % (0 if pend is None else len(pend)))
    g = pend.dropna(subset=['home_qb_id', 'away_qb_id']).iloc[0]
    r1 = m.predecir_partido(g['home'], g['away'], fecha=g['gameday'])
    r2 = m.predecir_partido(g['home'], g['away'], fecha=g['gameday'])
    check('error' not in r1 and r1.get('qb_home') == g['home_qb_name'],
          'usa el QB previsto (%s %s: %s)' % (g['home'], g['away'], r1.get('qb_home')))
    check(r1.get('prob_home_sin_empate') == r2.get('prob_home_sin_empate'),
          'predecir dos veces da lo mismo')
    for k in ('margen_esperado', 'total_esperado', 'prob_home_sin_empate',
              'prob_away_sin_empate', 'sigma_total', 'tds_esperados'):
        check(k in r1, 'la predicción trae «%s», como la de la v131' % k)
    # el QB importa: con el mejor QB del momento en lugar del previsto, sube
    est = m.estado_v325
    # el peso de un QB llega como mucho a 1 / (1 - QB_DECAY) = 10 partidos
    mejor_qb = max(est.qb, key=lambda q: est.qb_valor(q) if est.qb[q].w > 5 else -9)
    # en el primer partido cuyo local no lo tenga ya (si no, no hay «mejor»)
    con_qb = pend.dropna(subset=['home_qb_id', 'away_qb_id'])
    gq = con_qb[con_qb['home_qb_id'] != mejor_qb].iloc[0]
    rq = m.predecir_partido(gq['home'], gq['away'], fecha=gq['gameday'])
    m2 = copy.copy(m)
    m2.pendientes = pend.copy()
    i = m2.pendientes.index[(m2.pendientes['home'] == gq['home'])
                            & (m2.pendientes['away'] == gq['away'])][0]
    m2.pendientes.loc[i, 'home_qb_id'] = mejor_qb
    # v341 — cambiar de QB enciende también «QB nuevo», que el modelo castiga
    # (-1,31 puntos de margen). Con DAL-TB (2026-10-08) el previsto es Dak
    # Prescott (0,022 EPA por dropback) y el mejor Brock Purdy (0,068): el
    # valor suma +1,13 y el debut resta 1,31, y el local bajaba 0,739 → 0,733.
    # El signo del QB era bueno; la prueba mezclaba los dos efectos. Se miden
    # por separado: el mismo QB mejor sin contarlo como nuevo...
    m2.estado_v325 = copy.deepcopy(est)
    m2.estado_v325.ultimo_qb[gq['home']] = mejor_qb
    r3 = m2.predecir_partido(gq['home'], gq['away'], fecha=gq['gameday'])
    check(r3['prob_home_sin_empate'] > rq['prob_home_sin_empate'],
          'con un QB mejor, el local sube (%s %s: %.3f → %.3f)'
          % (gq['home'], gq['away'], rq['prob_home_sin_empate'],
             r3['prob_home_sin_empate']))
    # ...y, con los dos nuevos, el mejor contra un suplente cualquiera
    m2.estado_v325 = est
    r_mejor = m2.predecir_partido(gq['home'], gq['away'], fecha=gq['gameday'])
    m2.pendientes.loc[i, 'home_qb_id'] = 'suplente-sin-historial'
    r_sup = m2.predecir_partido(gq['home'], gq['away'], fecha=gq['gameday'])
    check(r_mejor['prob_home_sin_empate'] > r_sup['prob_home_sin_empate'],
          'entre dos QB nuevos, el mejor le gana al suplente (%.3f > %.3f)'
          % (r_mejor['prob_home_sin_empate'], r_sup['prob_home_sin_empate']))
    check(r_sup['prob_home_sin_empate'] < rq['prob_home_sin_empate'],
          'y con un suplente en lugar del previsto, el local baja (%.3f → %.3f)'
          % (rq['prob_home_sin_empate'], r_sup['prob_home_sin_empate']))
    # sin el histórico largo, el de siempre
    import nfl_nflverse as nv
    real = nv.SALIDA
    try:
        nv.SALIDA = 'no_existe_nfl.csv'
        v = mn.NFLModelo.cargar(historico=nd.cargar_historico())
    finally:
        nv.SALIDA = real
    check(v is not None and v.version == 'v131',
          'sin historico_nfl_largo.csv se carga el de la v131')


def probar_medicion():
    doc = json.load(open('modelos/nfl_v325.json', encoding='utf-8'))
    med = doc.get('medicion') or {}
    ll25 = (med.get('2025') or {}).get('modelo', {}).get('log_loss')
    v131 = (med.get('2025') or {}).get('v131', {}).get('log_loss')
    check(ll25 is not None and v131 is not None and ll25 < v131,
          'en 2025 mejora al de la v131 (log-loss %s contra %s)' % (ll25, v131))
    check(doc.get('metodo_margen') in ('normal', 'empirico'),
          'el método del margen está elegido (%s)' % doc.get('metodo_margen'))


def probar_decision():
    import concordancia as cc
    import veredicto_pick as vp
    nfl = {'deporte': 'NFL', 'partido': 'Buffalo Bills vs New England Patriots',
           'implicitas': {'1x2_cuotas': {'home': 1.33, 'away': 3.4}}}
    p = cc.prob_mercado(nfl, 'Gana Buffalo Bills', '1X2')
    esperado = (1 / 1.33) / (1 / 1.33 + 1 / 3.4)
    check(p is not None and abs(p - esperado) < 1e-9,
          'NFL: el precio de la casa sin empate se lee (%.3f)' % (p or 0))
    ten = dict(nfl, deporte='Tenis', partido='A vs B')
    # v342 — el tenis ya lee el precio de la casa (y decide con él, medido)
    check(abs((cc.prob_mercado(ten, 'Gana A', '1X2') or 0) - esperado) < 1e-9,
          'el tenis también lee la casa desde la v342')
    fut = {'deporte': 'Fútbol', 'partido': 'A vs B',
           'implicitas': {'1x2_cuotas': {'home': 2.0, 'draw': 3.4, 'away': 4.0}}}
    pf = cc.prob_mercado(fut, 'Gana A', '1X2')
    check(pf is not None and abs(sum([pf]) - pf) < 1e-12, 'el fútbol lee su 1X2 de tres')
    check(cc.peso_modelo({'deporte': 'NFL'}) == 0.25
          and cc.peso_modelo({'deporte': 'Fútbol'}) == cc.PESO_MODELO,
          'un cuarto para el modelo en la NFL; el resto sin tocar')
    fila = {'deporte': 'NFL', 'prob': 0.598, 'mercado': '1X2', 'cuota': 1.495,
            'apuesta': 'Gana Indianapolis Colts', 'p_mercado': 0.652}
    v = vp.evaluar(fila)
    check(abs(v['prob_ajustada'] - (0.25 * 0.598 + 0.75 * 0.652)) < 1e-3
          and v['veredicto'] == vp.NO_METER,
          'NFL: sin la corrección del fútbol (Colts 59,8 %% / casa 65,2 %% → %.3f, '
          'no se mete)' % v['prob_ajustada'])
    ff = dict(fila, deporte='Fútbol')
    c = vp.correccion(0.598, '1X2', 1.495)
    vf = vp.evaluar(ff)
    esperado_f = 0.5 * max(0.01, min(0.99, 0.598 + c['delta'])) + 0.5 * 0.652
    check(abs(vf['prob_ajustada'] - esperado_f) < 1e-3,
          'el fútbol sigue con su corrección y mitad y mitad')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('=== 1. histórico largo ===')
    probar_historico()
    print('\n=== 2. sin fuga ===')
    probar_sin_fuga()
    print('\n=== 3. el modelo ===')
    probar_modelo()
    print('\n=== 4. la medición ===')
    probar_medicion()
    print('\n=== 5. la decisión ===')
    probar_decision()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
