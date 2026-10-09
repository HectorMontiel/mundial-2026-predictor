# -*- coding: utf-8 -*-
"""v343 — los cambios de apuesta, separados por su causa: un despliegue de
código (regla nueva) o sólo datos (cuotas, modelo). Lee `_v343_estabilidad`
y repite la comparación primera/última sólo en partidos cuya ventana de
fotos no cruza ningún despliegue que toque el «meter» del fútbol."""
import json
import numpy as np
import pandas as pd
import _v343_estabilidad as e

DESPLIEGUES = ['2026-10-04T01:21Z', '2026-10-07T01:10Z', '2026-10-07T05:29Z',
               '2026-10-07T06:52Z', '2026-10-08T12:43Z']
dec = e.decisiones()
d = pd.read_pickle('_v343_estabilidad.pkl')
d = d[d.deporte == 'Fútbol'].copy()


def ventana(par):
    fs = sorted(f[0] for k in dec if k.split('|')[0] == par for f in dec[k] if f[1])
    return (e._ts(fs[0]), e._ts(fs[-1])) if fs else (None, None)


cruza = []
for par in d.partido:
    a, b = ventana(par)
    cruza.append(any(a < e._ts(t) <= b for t in DESPLIEGUES) if a is not None else True)
d['cruza'] = cruza
rng = np.random.default_rng(3431)
res = {}
for nom, g in (('sin_despliegue', d[~d.cruza]), ('con_despliegue', d[d.cruza])):
    P, PN, U, UN = g.prim_v.values, g.prim_n.values, g.ult_v.values, g.ult_n.values
    b = [U[i].sum() / UN[i].sum() - P[i].sum() / PN[i].sum()
         for i in (rng.integers(0, len(g), len(g)) for _ in range(5000))]
    q = [x for l in g.quitadas for x in l]
    n = [x for l in g.nuevas for x in l]
    res[nom] = {'partidos': len(g), 'con_cambio': int(g.cambio.sum()),
                'primera': [int(P.sum()), int(PN.sum()), round(P.sum() / PN.sum(), 4)],
                'ultima': [int(U.sum()), int(UN.sum()), round(U.sum() / UN.sum(), 4)],
                'quitadas': [len(q), round(np.mean([x[1] for x in q]), 3) if q else None],
                'nuevas': [len(n), round(np.mean([x[1] for x in n]), 3) if n else None],
                'dif_media': round(float(np.mean(b)), 4),
                'p5': round(float(np.percentile(b, 5)), 4)}
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open('_v343_separa.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
