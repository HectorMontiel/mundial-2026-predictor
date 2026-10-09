#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v350 — las escaleras de totales que de verdad ofrece la casa (NFL, NBA, MLB).

Lee el historial de git de `pronostico_dia.json` (una foto de cada ~6
precálculos) y guarda, por partido y línea, la cuota «más»/«menos» y su
probabilidad sin margen, la línea principal (la más pareja) y la distancia
de cada línea a la principal. Sirve para saber hasta qué probabilidad llegan
las líneas alternativas que la casa publica: sin esa línea en la casa, no hay
apuesta que meter.
"""
import json
import subprocess
import sys

import pandas as pd

DEPORTES = ('NFL', 'NBA', 'MLB', 'KBO')


def fotos(paso=4):
    hs = subprocess.run(['git', 'log', '--format=%H %cI', 'origin/main', '--',
                         'pronostico_dia.json'], capture_output=True, text=True).stdout.split('\n')
    hs = [h for h in hs if h.strip()][::paso]
    filas = []
    for linea in hs:
        h, cuando = linea.split()
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':pronostico_dia.json'],
                                          capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        datos = d.get('datos') or d
        for p in (datos.get('pronosticos') or []):
            dep = str(p.get('deporte') or '')
            if dep not in DEPORTES:
                continue
            imp = p.get('implicitas') or {}
            tc = imp.get('totales_cuotas') or {}
            ml = imp.get('1x2_cuotas') or {}
            base = {'ts': cuando, 'deporte': dep, 'partido': p.get('partido'),
                    'fecha': p.get('fecha'), 'inicio': p.get('inicio'),
                    'total_esperado': p.get('total_esperado'),
                    'ml_home': ml.get('home'), 'ml_away': ml.get('away'),
                    'lineas_modelo': json.dumps((p.get('totales') or {}).get('lineas') or {})}
            if not tc:
                filas.append({**base, 'linea': None})
            for k, v in tc.items():
                try:
                    cm, cn = float(v.get('mas')), float(v.get('menos'))
                except (TypeError, ValueError):
                    continue
                if cm <= 1 or cn <= 1:
                    continue
                s = 1 / cm + 1 / cn
                filas.append({**base, 'linea': float(k), 'c_mas': cm, 'c_menos': cn,
                              'p_mas': (1 / cm) / s, 'margen': s - 1})
    t = pd.DataFrame(filas)
    con = t[t.linea.notna()].copy()
    # la principal: la línea más pareja de cada foto
    con['dist_par'] = (con.p_mas - 0.5).abs()
    prin = con.sort_values('dist_par').drop_duplicates(['ts', 'partido'])[['ts', 'partido', 'linea']]
    con = con.merge(prin.rename(columns={'linea': 'principal'}), on=['ts', 'partido'])
    con['offset'] = con.linea - con.principal
    return t, con


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    t, con = fotos()
    con.to_csv('_v350_escaleras.csv.gz', index=False)
    print('fotos con algún deporte:', t.ts.nunique(), 'filas', len(t))
    print(t.groupby('deporte').agg(partidos=('partido', 'nunique'),
                                    con_total=('linea', lambda s: s.notna().sum()),
                                    desde=('fecha', 'min'), hasta=('fecha', 'max')))
    for dep, g in con.groupby('deporte'):
        print('\n==', dep, 'partidos', g.partido.nunique(), 'margen medio %.3f' % g.margen.mean())
        r = g.groupby('offset').agg(n=('p_mas', 'size'), p_mas=('p_mas', 'mean'),
                                    c_mas=('c_mas', 'mean'), c_menos=('c_menos', 'mean'))
        print(r.to_string())
        print('p más alta ofrecida (más o menos): mediana por partido %.3f, máx %.3f' % (
            g.assign(pm=g[['p_mas']].max(axis=1).combine(1 - g.p_mas, max)).groupby('partido').pm.max().median(),
            max(g.p_mas.max(), (1 - g.p_mas).max())))
