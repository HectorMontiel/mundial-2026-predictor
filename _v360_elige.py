#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v360 — «⭐ ELIGE»: entre las «se mete», ¿cuáles de verdad se cumplen más?

El usuario: «quiero saber cuál es la que tiene más probabilidad de cumplirse
de verdad —no la probabilidad que dice la tarjeta— y que me la señales de
forma visual».

Réplica de la tarjeta (`_v356_candidatas.csv.gz`, 889 partidos de fútbol
19-sep → 9-oct, 1.086 «se mete» con su resultado). Reglas candidatas (una
«se mete» es ⭐ si…), medidas en las dos mitades de días con bootstrap de la
diferencia contra el resto de «se mete»:

  R1 probabilidad de la app ≥ 82 %
  R2 cuota ≤ 1,16
  R3 R1 o R2
  R4 R1 y R2
  R5 Capa 1 🏆
  R6 probabilidad de la app ≥ 80 %
Y la calibración que se pinta en cada apuesta: «acierta de verdad» por banda
de probabilidad de la app (lo medido, no lo prometido).
Escribe `_v360_elige.json`."""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(3602)


def boot(a, b, n=3000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ds = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean()
          for _ in range(n)]
    return [round(float(np.mean(ds)), 4), round(float(np.percentile(ds, 5)), 4)]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = pd.read_csv('_v356_candidatas.csv.gz')
    m = d[d.metida & d.acierto.notna()].copy()
    m['tramo'] = np.where(m.dia < '2026-09-30', 'elige', 'juzga')
    pa = m.ajustada.fillna(m.prob)
    reglas = {'R1 app ≥ 82 %': pa >= 0.82, 'R2 cuota ≤ 1,16': m.cuota <= 1.16,
              'R3 app ≥ 82 % o cuota ≤ 1,16': (pa >= 0.82) | (m.cuota <= 1.16),
              'R4 app ≥ 82 % y cuota ≤ 1,16': (pa >= 0.82) & (m.cuota <= 1.16),
              'R5 Capa 1': m.elite == True, 'R6 app ≥ 80 %': pa >= 0.80}
    out = {'n': int(len(m)), 'reglas': {}}
    print('%-30s %-26s %-26s' % ('regla', 'elige ⭐ n/acierto · resto', 'juzga ⭐ n/acierto · resto (dif, p5)'))
    for nom, f in reglas.items():
        r = {}
        for tr in ('elige', 'juzga'):
            a, b = m[f & (m.tramo == tr)], m[~f & (m.tramo == tr)]
            r[tr] = {'n': int(len(a)), 'acierto': round(float(a.acierto.mean()), 4),
                     'resto': round(float(b.acierto.mean()), 4), 'dif_p5': boot(a.acierto, b.acierto),
                     'por_partido': round(len(a) / max(m[m.tramo == tr].partido.nunique(), 1), 2)}
        out['reglas'][nom] = r
        print('%-30s %-26s %-26s' % (nom, '%d/%.1f · %.1f' % (r['elige']['n'], 100 * r['elige']['acierto'],
                                                              100 * r['elige']['resto']),
                                      '%d/%.1f · %.1f %s' % (r['juzga']['n'], 100 * r['juzga']['acierto'],
                                                             100 * r['juzga']['resto'], r['juzga']['dif_p5'])))
    # la calibración: lo que acierta de verdad cada banda de probabilidad de la app
    b = pd.cut(pa, [0, 0.76, 0.78, 0.80, 0.82, 0.84, 0.86, 1.0])
    cal = m.groupby(b, observed=True).acierto.agg(['size', 'mean'])
    out['calibracion'] = [{'banda': str(k), 'n': int(v['size']), 'acierta': round(float(v['mean']), 4)}
                          for k, v in cal.iterrows()]
    print('calibración (todo):', out['calibracion'])
    json.dump(out, open('_v360_elige.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
