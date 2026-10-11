#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v366f — La regla candidata: patas arriesgadas SIN las de equipo visitante
(totales, local y ambos-marcan se quedan). Contra la regla nueva entera
(`elegir(criterio='p')`), dos mitades, bootstrap por partido; y la diferencia
local − visita con las dos mitades juntas. Escribe `_v366f_sin_visita.json`."""
import json
import importlib.util as iu
import numpy as np
import pandas as pd
s = iu.spec_from_file_location('r', '_v366_rojas_arriesgadas.py'); r = iu.module_from_spec(s); s.loader.exec_module(r)
rng = np.random.default_rng(3666)
d = r.cargar().join(pd.read_pickle('_v366_lado.pkl'))
R = {}
for crit in ('p', 'pxc'):
    b = r.elegir(d, criterio=crit)
    f = b[b.lado_real != 'visita']
    R[crit] = {'contra_toda': r.contra_base(b, f), 'todo_base': r.resumen(b), 'todo_sin_visita': r.resumen(f)}
    q = b[b.tipo == 'equipo']
    L, V = q[q.lado_real == 'local'], q[q.lado_real == 'visita']
    lm = L.groupby('mid').y.agg(['sum', 'count']).values
    vm = V.groupby('mid').y.agg(['sum', 'count']).values
    bs = []
    for _ in range(4000):
        a = lm[rng.integers(0, len(lm), len(lm))].sum(0)
        c = vm[rng.integers(0, len(vm), len(vm))].sum(0)
        bs.append(a[0] / a[1] - c[0] / c[1])
    R[crit]['local_menos_visita'] = {'dif': round(float(L.y.mean() - V.y.mean()), 3),
                                     'p5': round(float(np.percentile(bs, 5)), 3),
                                     'p2_5': round(float(np.percentile(bs, 2.5)), 3)}
    # ¿y en los boletos? una pata por partido, por prob, sin visita
    R[crit]['boletos_sin_visita'] = r.boletos(f, 'p_mod')
    R[crit]['boletos_todas'] = r.boletos(b, 'p_mod')
json.dump(R, open('_v366f_sin_visita.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
