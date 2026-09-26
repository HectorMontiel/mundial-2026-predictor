# -*- coding: utf-8 -*-
"""
v310 — GOLES, AMBOS MARCAN Y 1X2 EN LIGA MX Y COPAS UEFA: ¿CUMPLE LO QUE DICE?

Sobre los ledgers fuera de muestra del modelo de producción (cada partido lo
predijo un modelo entrenado sin él: columna `pliegue`):
    pick_ledger_totales.csv   más de 1,5/2,5/3,5 y ambos marcan
    pick_ledger.csv           1X2 con cuotas de cierre (football-data)
Se mira lo que la tarjeta ofrecería (el lado con p ≥ 50 %): tasa real por
banda, ECE, y el ROI a la cuota real donde la hay. Liga MX, Champions /
Europa / Conference y Leagues Cup contra el resto como referencia.

Uso: python _v310_goles.py   (escribe _v310_goles.json)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

GRUPOS = {'liga_mx': 'Liga MX', 'champions': 'UEFA clubes',
          'europa_league': 'UEFA clubes', 'conference_league': 'UEFA clubes',
          'leagues_cup': 'Leagues Cup'}


def ece(p, y, bins=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return None
    idx = np.clip(np.digitize(p, np.linspace(0, 1, bins + 1)) - 1, 0, bins - 1)
    return round(float(sum((idx == b).mean() * abs(p[idx == b].mean()
                                                   - y[idx == b].mean())
                           for b in range(bins) if (idx == b).any())), 4)


def tabla(x: pd.DataFrame) -> dict:
    b = pd.cut(x['p'], [.5, .55, .6, .65, .7, .75, .8, .85, .9, 1])
    r = {'n': int(len(x)), 'p_media': round(float(x['p'].mean()), 4),
         'real': round(float(x['y'].mean()), 4), 'ece': ece(x['p'], x['y']),
         'bandas': {str(k): {'n': int(len(v)), 'p': round(float(v['p'].mean()), 3),
                             'real': round(float(v['y'].mean()), 3)}
                    for k, v in x.groupby(b, observed=True) if len(v) >= 10}}
    if 'cuota' in x and x['cuota'].notna().any():
        c = x[x['cuota'].notna()]
        r['roi_cuota_real'] = round(float((c['y'] * c['cuota'] - 1).mean()), 4)
        r['n_cuota'] = int(len(c))
    return r


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    t = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    t['grupo'] = t['liga'].map(GRUPOS).fillna('Resto')
    t = t[t['fecha'] >= '2023-07-01']
    filas = []
    for L in ('1.5', '2.5', '3.5'):
        p, y = t['p_over_' + L], t['over_%s_real' % L]
        ok = p.notna() & y.notna()
        cm = t['cuota_over25'] if L == '2.5' else pd.Series(np.nan, index=t.index)
        cn = t['cuota_under25'] if L == '2.5' else pd.Series(np.nan, index=t.index)
        filas.append(pd.DataFrame({'grupo': t['grupo'], 'mercado': 'Más de ' + L,
                                   'p': p, 'y': y, 'cuota': cm})[ok])
        filas.append(pd.DataFrame({'grupo': t['grupo'], 'mercado': 'Menos de ' + L,
                                   'p': 1 - p, 'y': 1 - y, 'cuota': cn})[ok])
    ok = t['p_btts'].notna() & t['btts_real'].notna()
    filas.append(pd.DataFrame({'grupo': t['grupo'], 'mercado': 'Ambos: sí',
                               'p': t['p_btts'], 'y': t['btts_real'],
                               'cuota': np.nan})[ok])
    filas.append(pd.DataFrame({'grupo': t['grupo'], 'mercado': 'Ambos: no',
                               'p': 1 - t['p_btts'], 'y': 1 - t['btts_real'],
                               'cuota': np.nan})[ok])
    l = pd.read_csv('pick_ledger.csv', low_memory=False)
    l = l[l['fecha'] >= '2023-07-01']
    l['grupo'] = l['liga'].map(GRUPOS).fillna('Resto')
    for lado, col, res, cu in (('Gana local', 'p_home', 0, 'cuota_home'),
                               ('Empate', 'p_draw', 1, 'cuota_draw'),
                               ('Gana visita', 'p_away', 2, 'cuota_away')):
        filas.append(pd.DataFrame({'grupo': l['grupo'], 'mercado': lado,
                                   'p': l[col], 'y': (l['resultado'] == res)
                                   .astype(int), 'cuota': l[cu]}))
    for nom, a, b, ra, rb in (('Doble 1X', 'p_home', 'p_draw', 0, 1),
                              ('Doble X2', 'p_draw', 'p_away', 1, 2)):
        filas.append(pd.DataFrame({'grupo': l['grupo'], 'mercado': nom,
                                   'p': l[a] + l[b],
                                   'y': l['resultado'].isin([ra, rb]).astype(int),
                                   'cuota': np.nan}))
    P = pd.concat(filas, ignore_index=True)
    P = P[P['p'] >= 0.5]
    out = {}
    for (g, m), x in P.groupby(['grupo', 'mercado']):
        out.setdefault(g, {})[m] = tabla(x)
    json.dump(out, open('_v310_goles.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    for g in out:
        for m, r in out[g].items():
            print('%-12s %-14s n=%5d prometido=%.3f real=%.3f ece=%s roi=%s'
                  % (g, m, r['n'], r['p_media'], r['real'], r['ece'],
                     r.get('roi_cuota_real')))


if __name__ == '__main__':
    main()
