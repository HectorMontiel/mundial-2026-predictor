#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v371e — La casa elige y además tiene que verla al 68 / 70 % o más (cuota
1,30-1,70, sin tarjetas ni córners de equipo). Dos mitades, boletos de 2-5,
y cuántas patas da por día. Escribe `_v371e_umbral.json`."""
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
for umbral in (0.0, 0.66, 0.68, 0.70):
    z = C.elegir(x[x.p_c >= umbral], 'casa', 1.30)
    f = {'todo': V.resumen(z), 'promete_casa': round(float(z.p_c.mean()), 4),
         'patas_por_dia': round(float(z.groupby(z.fecha.dt.date).size().mean()), 1)}
    for t, m in (('A', z.fecha < corte), ('B', z.fecha >= corte)):
        q = z[m]
        f[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4), 'cuota': round(float(q.cuota.mean()), 3),
                'acierto_p5': round(float(np.percentile(V._boot(q, 'ok'), 5)), 4), 'gan_100': round(100 * float(q.gan.mean()), 1)}
    f['boletos'] = {n: C.boletos(z, n, corte) for n in (2, 3, 4, 5)}
    f['por_mercado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3), round(float(g.cuota.mean()), 3)]
                        for m, g in z.groupby('mercado') if len(g) >= 10}
    f['por_lado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3)] for m, g in z.groupby('lado_ap')}
    R['casa >= %.2f' % umbral] = f
json.dump(R, open('_v371e_umbral.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
for k, f in R.items():
    print('%-12s %s promete %s · %s/día | A %s | B %s' % (k, {a: f['todo'][a] for a in ('n', 'acierto', 'cuota', 'gan_100')},
                                                        f['promete_casa'], f['patas_por_dia'], f['A'], f['B']))
    print('   boletos', {n: {t: (v['enteros'], v['dias'], v['tres_rojas'], v['momio']) for t, v in b.items()} for n, b in f['boletos'].items()})
    print('   ', f['por_mercado'], f['por_lado'])
