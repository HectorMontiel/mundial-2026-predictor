#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v366e — ¿Las patas de equipo fallan más de local o de visita? ¿Y si el equipo
es el que más genera del partido? Patas de la regla nueva (la línea más
probable, `_v366_rojas_arriesgadas.elegir(criterio='p')`), lado de
`_v366c_lado.py`. Dos mitades y bootstrap por partido contra el resto de patas
de equipo. Escribe `_v366e_localia.json`."""
import json
import importlib.util as iu
import numpy as np
import pandas as pd
s = iu.spec_from_file_location('r', '_v366_rojas_arriesgadas.py'); r = iu.module_from_spec(s); s.loader.exec_module(r)
rng = np.random.default_rng(3665)
d = r.cargar().join(pd.read_pickle('_v366_lado.pkl'))
# la media del rival en la misma estadística
eq = d[d.tipo == 'equipo'][['mid', 'obj', 'mu']].drop_duplicates()
otro = eq.merge(eq, on=['mid', 'obj'], suffixes=('', '_rival'))
otro = otro[otro.mu != otro.mu_rival].drop_duplicates(['mid', 'obj', 'mu'])
d = d.merge(otro, on=['mid', 'obj', 'mu'], how='left').set_axis(d.index)
R = {}
for nombre, crit in (('hoy (prob × cuota)', 'pxc'), ('nueva (la más probable)', 'p')):
    b = r.elegir(d, criterio=crit)
    q = b[b.tipo == 'equipo'].copy()
    q['manda'] = q.mu > q.mu_rival
    fila = {}
    for etq, m in (('local', q.lado_real == 'local'), ('visita', q.lado_real == 'visita'),
                   ('genera más', q.manda), ('genera menos', ~q.manda & q.mu_rival.notna()),
                   ('local que genera más', (q.lado_real == 'local') & q.manda),
                   ('visita que genera más', (q.lado_real == 'visita') & q.manda)):
        x = q[m]
        por_obj = {o: [int(len(g)), round(float(g.y.mean()), 3)] for o, g in x.groupby('obj')}
        f = {'todo': r.resumen(x), 'por_obj': por_obj}
        for t in 'AB':
            xt, rest = x[x.tramo == t], q[(q.tramo == t) & ~m]
            if len(xt) >= 20 and len(rest) >= 20:
                xm = xt.groupby('mid').y.agg(['sum', 'count']).values
                rm = rest.groupby('mid').y.agg(['sum', 'count']).values
                bs = []
                for _ in range(2000):
                    a = xm[rng.integers(0, len(xm), len(xm))].sum(0)
                    c = rm[rng.integers(0, len(rm), len(rm))].sum(0)
                    bs.append(a[0] / a[1] - c[0] / c[1])
                f[t] = {'n': int(len(xt)), 'acierto': round(float(xt.y.mean()), 3),
                        'resto': round(float(rest.y.mean()), 3), 'cuota': round(float(xt.c_mas.mean()), 3),
                        'dif_p5': round(float(np.percentile(bs, 5)), 3)}
        fila[etq] = f
    R[nombre] = fila
json.dump(R, open('_v366e_localia.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
for n, v in R.items():
    print('==', n)
    for k, f in v.items():
        t = f['todo']
        print('%-24s n%4s ac %s cuota %s gan %s (p5 %s) | A %s | B %s | %s' % (
            k, t.get('n'), t.get('acierto'), t.get('cuota'), t.get('gan_100'), t.get('gan_p5'),
            f.get('A'), f.get('B'), f['por_obj']))
