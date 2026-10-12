#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v371f — Sensibilidad del Método Casa 70/130: umbral de la casa (68/70/72 %)
y cuota máxima (1,50/1,70). Escribe `_v371f_sensibilidad.json`."""
import importlib.util as iu
import json
import sys
import numpy as np
s = iu.spec_from_file_location('c', '_v371c_refinar.py'); C = iu.module_from_spec(s); s.loader.exec_module(C)
V = C.V
sys.stdout.reconfigure(encoding='utf-8')
x = V.playdoit()
corte = x.fecha.quantile(0.5)
R = {}
for umbral in (0.68, 0.70, 0.72):
    for cmax in (1.50, 1.70):
        q0 = x[(x.p_c >= umbral) & (x.cuota <= cmax)]
        z = C.elegir(q0, 'casa', 1.30)
        f = {'todo': V.resumen(z), 'por_dia': round(float(z.groupby(z.fecha.dt.date).size().mean()), 1)}
        for t, m in (('A', z.fecha < corte), ('B', z.fecha >= corte)):
            q = z[m]
            f[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4), 'gan_100': round(100 * float(q.gan.mean()), 1)}
        f['boletos'] = {n: C.boletos(z, n, corte) for n in (2, 3, 4)}
        R['casa>=%.2f cuota<=%.2f' % (umbral, cmax)] = f
json.dump(R, open('_v371f_sensibilidad.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
for k, f in R.items():
    print('%-24s %s %s/día | A %s | B %s' % (k, {a: f['todo'][a] for a in ('n', 'acierto', 'cuota', 'gan_100')}, f['por_dia'], f['A'], f['B']))
    print('     boletos', {n: {t: (v['enteros'], v['dias'], v['tres_rojas']) for t, v in b.items()} for n, b in f['boletos'].items()})
