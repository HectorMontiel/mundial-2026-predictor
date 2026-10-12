#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v372 — El ganador «cuando la casa está a favor», sólo con la casa (sin el
modelo): favorito con la casa sin margen en una banda y cuota en otra, en los
125.721 partidos de `historico_*.csv` (2010-2026). Dos mitades por fecha,
2023→ aparte, bootstrap por partido. Escribe `_v372_ganador_casa.json`."""
import importlib.util as iu
import json
import sys
import numpy as np
s = iu.spec_from_file_location('g', '_v371b_ganador.py'); G = iu.module_from_spec(s); s.loader.exec_module(G)
sys.stdout.reconfigure(encoding='utf-8')
x = G.patas(G.cargar())
fav = x[x.lado.isin(['gana local', 'gana visita'])]
corte = fav.fecha.quantile(0.5)
R = {}
for (lo, hi) in ((0.55, 0.62), (0.58, 0.70), (0.60, 0.70), (0.62, 0.70), (0.65, 0.70), (0.70, 1.0)):
    for (cl, ch) in ((1.30, 1.45), (1.35, 1.60), (1.45, 1.70)):
        z = fav[(fav.p_c >= lo) & (fav.p_c < hi) & (fav.cuota >= cl) & (fav.cuota <= ch)]
        if len(z) < 200:
            continue
        f = {'todo': G.res(z)}
        for t, m in (('A', z.fecha < corte), ('B', z.fecha >= corte), ('2023', z.fecha >= '2023-07-01')):
            q = z[m]
            f[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4),
                    'gan_100': round(100 * float(q.gan.mean()), 2)}
        f['local'] = round(float(z[z.lado == 'gana local'].ok.mean()), 4)
        f['visita'] = round(float(z[z.lado == 'gana visita'].ok.mean()), 4) if (z.lado == 'gana visita').sum() > 30 else None
        R['casa %.2f-%.2f · cuota %.2f-%.2f' % (lo, hi, cl, ch)] = f
json.dump(R, open('_v372_ganador_casa.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
for k, f in R.items():
    t = f['todo']
    print('%-34s n %5d acierto %.3f promete %.3f cuota %.3f gan %+.2f (p5 %+.2f) | A %.3f B %.3f 2023 %.3f (%+.1f) | L %.3f V %s'
          % (k, t['n'], t['acierto'], t['casa'], t['cuota'], t['gan_100'], t['gan_p5'], f['A']['acierto'],
             f['B']['acierto'], f['2023']['acierto'], f['2023']['gan_100'], f['local'], f['visita']))
