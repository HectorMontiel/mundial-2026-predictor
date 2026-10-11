#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v366c — el LADO (local / visita) de cada línea de equipo de `_v362b_lineas.pkl`.

Los `mid` de `_v361_metodo.preparar()` cambian cuando entra histórico nuevo, así
que el partido se empata por liga, fecha y los TOTALES reales de cada
estadística (córners, tiros, a puerta, tarjetas, goles). Luego el lado de cada
línea de equipo es el del equipo con ese valor real; si los dos sacaron lo
mismo, queda «igual». Escribe `_v366_lado.pkl` (índice de `_v362b_lineas.pkl`)."""
import os
import sys
import numpy as np
import pandas as pd

COL = {'corners': 'corners', 'tiros': 'tiros', 'a_puerta': 'a_puerta', 'tarjetas': 'amarillas', 'goles': 'gf'}
CACHE = os.environ.get('V366_E', '')
sys.stdout.reconfigure(encoding='utf-8')
d = pd.read_pickle('_v362b_lineas.pkl')
if CACHE and os.path.exists(CACHE):
    e = pd.read_pickle(CACHE)
else:
    import _v361_metodo as V
    e = V.preparar()
# los partidos del histórico: por liga y fecha, local y visita de cada estadística
e = e[e.fecha >= d.fecha.min() - pd.Timedelta(days=1)]
loc = e[e.local == 1].drop_duplicates('mid').set_index('mid')
vis = e[e.local == 0].drop_duplicates('mid').set_index('mid')
comunes = loc.index.intersection(vis.index)
part = {}
for m in comunes:
    a, b = loc.loc[m], vis.loc[m]
    part.setdefault((a.liga, pd.Timestamp(a.fecha).normalize()), []).append(
        {o: (a[c], b[c]) for o, c in COL.items()})
# los totales de cada partido del fichero de líneas
tot = d.groupby(['mid', 'obj']).agg(liga=('liga', 'first'), fecha=('fecha', 'first'),
                                     reales=('real', lambda x: sorted(set(x))))
lado = pd.Series('total', index=d.index, dtype=object)
emp = {}
for mid, g in d.groupby('mid'):
    liga, fecha = g.liga.iloc[0], pd.Timestamp(g.fecha.iloc[0]).normalize()
    cands = []
    for dd in (0, -1, 1):
        cands += part.get((liga, fecha + pd.Timedelta(days=dd)), [])
    ok = []
    for c in cands:
        bien = True
        for r in g[g.tipo == 'total'].drop_duplicates('obj').itertuples():
            h, a = c[r.obj]
            if not (h == h and a == a and abs(h + a - r.real) < 1e-6):
                bien = False
                break
        for r in g[g.tipo == 'equipo'].drop_duplicates(['obj', 'real']).itertuples():
            if bien and r.real not in c[r.obj]:
                bien = False
        if bien:
            ok.append(c)
    emp[mid] = ok[0] if len(ok) == 1 else None
for idx, r in d[d.tipo == 'equipo'].iterrows():
    c = emp.get(r.mid)
    if c is None:
        lado[idx] = 'sin'
        continue
    h, a = c[r.obj]
    lado[idx] = 'igual' if h == a else ('local' if r.real == h else 'visita')
pd.DataFrame({'lado_real': lado}).to_pickle('_v366_lado.pkl')
print(pd.crosstab(d.obj, lado))
