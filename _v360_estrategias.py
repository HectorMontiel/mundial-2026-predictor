#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v360 — ¿Qué conjunto de «se mete» conviene apostar? (con `_v360_retiradas.pkl`)

  A  al pitido (lo que queda en la última foto antes del inicio)
  B  la primera anunciada (lo de la primera foto en que el partido tuvo «meter»)
  C  todo lo que alguna vez se anunció
  D  al pitido + las retiradas que se anunciaron con prob ≥ 80 %
  E  al pitido + las retiradas que NO siguen «meter» desplazadas por otra
  F  al pitido + las retiradas que desaparecieron del tablero
Verdes, rojas y acierto en las dos mitades de días, y el p5 de la diferencia
de acierto contra A. Escribe `_v360_estrategias.json`."""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(3601)


def boot(a, b, n=2000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ds = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean()
          for _ in range(n)]
    return round(float(np.percentile(ds, 5)), 4)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = pd.read_pickle('_v360_retiradas.pkl')
    dias = sorted(d.dia.unique())
    corte = dias[len(dias) // 2]
    d['tramo'] = np.where(d.dia < corte, 'elige', 'juzga')
    primera = d.groupby('partido').horas_anuncio.transform('max')
    ret = d.retirada == 1
    S = {
        'A al pitido': ~ret,
        'B primera anunciada': (d.horas_anuncio >= primera - 1e-6),
        'C todo lo anunciado': d.retirada >= 0,
        'D pitido + retiradas ≥ 80 %': ~ret | (ret & (d.p0 >= 0.80)),
        'E pitido + retiradas no desplazadas': ~ret | (ret & (d.estado != 'desplazada')),
        'F pitido + retiradas desaparecidas': ~ret | (ret & (d.estado == 'desaparecida')),
    }
    out = {'corte': corte, 'estrategias': {}}
    base = {tr: d[S['A al pitido'] & (d.tramo == tr)].verde for tr in ('elige', 'juzga')}
    print('%-38s %-28s %-28s' % ('estrategia', 'elige (✅/❌/%, p5 vs A)', 'juzga (✅/❌/%, p5 vs A)'))
    for nom, m in S.items():
        r = {}
        for tr in ('elige', 'juzga'):
            x = d[m & (d.tramo == tr)]
            r[tr] = {'verdes': int(x.verde.sum()), 'rojas': int((1 - x.verde).sum()),
                     'acierto': round(float(x.verde.mean()), 4),
                     'p5_vs_A': None if nom.startswith('A') else boot(x.verde, base[tr])}
        out['estrategias'][nom] = r
        print('%-38s %-28s %-28s' % (nom, '%d/%d/%.1f %s' % (r['elige']['verdes'], r['elige']['rojas'],
                                                              100 * r['elige']['acierto'], r['elige']['p5_vs_A']),
                                      '%d/%d/%.1f %s' % (r['juzga']['verdes'], r['juzga']['rojas'],
                                                         100 * r['juzga']['acierto'], r['juzga']['p5_vs_A'])))
    json.dump(out, open('_v360_estrategias.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
