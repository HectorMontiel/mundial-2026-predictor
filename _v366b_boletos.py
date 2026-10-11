#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v366b — ¿Qué patas poner en el boleto? Mismas patas que `_v366_rojas_arriesgadas`
(regla de hoy), una por partido; cambia sólo el ORDEN para elegir las n del día:
la prob del método (lo de hoy), la de la casa, la menor de las dos (que estén de
acuerdo) y la media. Dos mitades por fecha y bootstrap por día."""
import json
import numpy as np
import pandas as pd
import importlib.util as _iu
_s = _iu.spec_from_file_location('r', '_v366_rojas_arriesgadas.py'); r = _iu.module_from_spec(_s); _s.loader.exec_module(r)
rng = np.random.default_rng(3662)
d = r.cargar(); base = r.elegir(d)
base['p_min'] = np.minimum(base.p_mod, base.p_casa)
base['p_med'] = (base.p_mod + base.p_casa) / 2
base['dia'] = base.fecha.dt.strftime('%Y-%m-%d')
dias = sorted(base.dia.unique()); mitad = dias[len(dias) // 2]


def tickets(orden, n):
    out = []
    for dia, g in base.groupby('dia'):
        g = g.sort_values(orden, ascending=False).drop_duplicates('mid').head(n)
        if len(g) < n:
            continue
        m = float(np.prod(g.c_mas)); ok = bool(g.y.all())
        out.append((dia, ok, m, (m - 1) if ok else -1.0, int(g.y.sum())))
    return pd.DataFrame(out, columns=['dia', 'ok', 'momio', 'gan', 'patas_bien'])


R = {}
for n in (2, 3, 4, 6):
    R[n] = {}
    for orden in ('p_mod', 'p_casa', 'p_min', 'p_med'):
        t = tickets(orden, n)
        fila = {}
        for tramo, q in (('A', t[t.dia < mitad]), ('B', t[t.dia >= mitad]), ('todo', t)):
            if not len(q):
                continue
            bs = [q.gan.values[rng.integers(0, len(q), len(q))].mean() for _ in range(2000)]
            fila[tramo] = {'dias': len(q), 'salen': int(q.ok.sum()), 'pct': round(q.ok.mean(), 3),
                           'momio': round(q.momio.mean(), 2), 'gan_100': round(100 * q.gan.mean(), 1),
                           'gan_p5': round(100 * float(np.percentile(bs, 5)), 1),
                           'patas_bien': round(q.patas_bien.mean() / n, 3)}
        R[n][orden] = fila
json.dump(R, open('_v366b_boletos.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for n, v in R.items():
    for o, f in v.items():
        print(n, o.ljust(6), ' | '.join('%s %s/%s %.0f%% ×%.2f gan %s (p5 %s) patas %.0f%%' % (
            k, x['salen'], x['dias'], 100 * x['pct'], x['momio'], x['gan_100'], x['gan_p5'], 100 * x['patas_bien'])
            for k, x in f.items()))
