#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v366d — ¿Hay ligas donde las patas arriesgadas fallan (o aciertan) más de lo
prometido? Sin hacer trampa: las ligas se ELIGEN en una mitad (acierto −
prometido, con 15+ patas) y se JUZGAN en la otra, en los dos sentidos; bootstrap
por partido de la diferencia contra el resto. Escribe `_v366d_ligas.json`."""
import json
import importlib.util as iu
import numpy as np
s = iu.spec_from_file_location('r', '_v366_rojas_arriesgadas.py'); r = iu.module_from_spec(s); s.loader.exec_module(r)
rng = np.random.default_rng(3664)
d = r.cargar(); b = r.elegir(d)


def p5_dif(x, y):
    """p5 de acierto(x) − acierto(y), bootstrap por partido dentro de cada grupo."""
    xm = x.groupby('mid').y.agg(['sum', 'count']).values
    ym = y.groupby('mid').y.agg(['sum', 'count']).values
    out = []
    for _ in range(2000):
        a = xm[rng.integers(0, len(xm), len(xm))].sum(0)
        c = ym[rng.integers(0, len(ym), len(ym))].sum(0)
        out.append(a[0] / a[1] - c[0] / c[1])
    return float(np.percentile(out, 5)), float(np.percentile(out, 95))


R = {}
for elige, juzga in (('A', 'B'), ('B', 'A')):
    e, j = b[b.tramo == elige], b[b.tramo == juzga]
    g = e.groupby('liga').agg(n=('y', 'size'), ac=('y', 'mean'), pr=('p_mod', 'mean'))
    g = g[g.n >= 15]
    buenas = list(g[g.ac - g.pr >= 0.05].index)
    malas = list(g[g.ac - g.pr <= -0.05].index)
    jb, jm = j[j.liga.isin(buenas)], j[j.liga.isin(malas)]
    jr = j[~j.liga.isin(malas)]
    fila = {'buenas': buenas, 'malas': malas}
    if len(jb) >= 30:
        lo, hi = p5_dif(jb, j[~j.liga.isin(buenas)])
        fila['buenas_juzgadas'] = {'n': len(jb), 'acierto': round(jb.y.mean(), 3), 'cuota': round(jb.c_mas.mean(), 3),
                                   'resto': round(j[~j.liga.isin(buenas)].y.mean(), 3), 'dif_p5': round(lo, 3)}
    if len(jm) >= 30:
        lo, hi = p5_dif(j[~j.liga.isin(malas)], jm)
        fila['sin_malas'] = {'n_malas': len(jm), 'acierto_malas': round(jm.y.mean(), 3),
                             'acierto_sin_malas': round(jr.y.mean(), 3), 'todas': round(j.y.mean(), 3),
                             'cuota_sin_malas': round(jr.c_mas.mean(), 3), 'dif_p5': round(lo, 3)}
    R['elige %s, juzga %s' % (elige, juzga)] = fila
json.dump(R, open('_v366d_ligas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
