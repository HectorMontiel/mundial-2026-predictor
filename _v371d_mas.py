#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v371d — La regla candidata: la casa elige, SÓLO «más de» (goles, córners,
tiros y a puerta; total y por equipo), cuota 1,25-1,30 → 1,70. Dos mitades,
p5 de la diferencia contra «casa» con los dos lados, boletos de 2-5 patas, por
mercado y por banda de la casa. Escribe `_v371d_mas.json`."""
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
for cmin in (1.25, 1.30, 1.35):
    base = C.elegir(x, 'casa', cmin)
    xm = x[x.lado_ap == 'más']
    for nombre, regla in (('mas_casa', 'casa'), ('mas_veto3', 'casa_veto3')):
        z = C.elegir(xm, regla, cmin)
        f = {'todo': V.resumen(z), 'promete_casa': round(float(z.p_c.mean()), 4),
             'promete_metodo': round(float(z.p_m.mean()), 4)}
        for t, m in (('A', z.fecha < corte), ('B', z.fecha >= corte)):
            q, b = z[m], base[(base.fecha < corte) if t == 'A' else (base.fecha >= corte)]
            d = V._boot(q, 'ok') - V._boot(b, 'ok')
            f[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4), 'cuota': round(float(q.cuota.mean()), 3),
                    'dif_vs_casa': round(float(q.ok.mean() - b.ok.mean()), 4), 'dif_p5': round(float(np.percentile(d, 5)), 4),
                    'gan_100': round(100 * float(q.gan.mean()), 1)}
        f['boletos'] = {n: C.boletos(z, n, corte) for n in (2, 3, 4, 5)}
        f['por_mercado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3), round(float(g.cuota.mean()), 3)]
                            for m, g in z.groupby('mercado') if len(g) >= 10}
        import pandas as pd
        f['bandas'] = {str(k): [int(len(g)), round(float(g.ok.mean()), 3)]
                       for k, g in z.groupby(pd.cut(z.p_c, [0, .6, .65, .7, .75, 1]), observed=True)}
        R['%.2f %s' % (cmin, nombre)] = f
json.dump(R, open('_v371d_mas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
for k, f in R.items():
    print('%-16s %s | A %s | B %s' % (k, {a: f['todo'][a] for a in ('n', 'acierto', 'cuota', 'gan_100', 'gan_p5')}, f['A'], f['B']))
    print('   promete casa %s metodo %s' % (f['promete_casa'], f['promete_metodo']))
    print('   boletos', {n: {t: (v['enteros'], v['dias'], v['tres_rojas'], v['momio']) for t, v in b.items()} for n, b in f['boletos'].items()})
    print('   ', f['por_mercado'], f['bandas'])
