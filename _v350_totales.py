#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v350 — los totales (puntos) de la NFL y la NBA con las líneas que la casa
SÍ publica (`_v350_escaleras.py`): la principal ± lo que ofrece Playdoit
(NFL hasta ±7,5; NBA hasta ±3).

Réplica sin fuga (`_v325_nfl` / `_v330_nba`): la línea de cierre T, el total
esperado del modelo y el resultado. Para cada distancia k:
  · lo que la casa dice de «Más de T−k» / «Menos de T+k» (la media de sus
    escaleras de 2026, sin margen) contra lo que de verdad pasó;
  · y lo mismo sólo cuando el modelo está de acuerdo (su total esperado
    del mismo lado que la apuesta por ≥ d puntos).
Elige 2010-2020, juzga 2021-2025.
"""
import json
import sys

import numpy as np
import pandas as pd

ESC = pd.read_csv('_v350_escaleras.csv.gz')


def casa_p(dep, off):
    g = ESC[(ESC.deporte == dep)].groupby('offset').p_mas.mean()
    return float(g.get(off, np.nan))


def datos():
    import _v325_nfl as F
    import _v330_nba as B
    d = F.nv.cargar()
    ds, _ = F.ne.dataset(d)
    x = F.variables(ds)
    x['p_mkt'] = F.mercado(x)
    r = F.walk_forward(x, range(2010, 2026))
    nfl = pd.DataFrame({'temporada': r.season, 'T': r.total_line, 't_pred': r.t_pred,
                        'total': r.total}).dropna()
    d = B.nh.cargar()
    x, _ = B.ne.dataset(d)
    x['p_mkt'] = B.mercado(x)
    r = B.walk_forward(x, range(2010, 2026))
    nba = pd.DataFrame({'temporada': r.temporada, 'T': r.total_linea, 't_pred': r.t_pred,
                        'total': r.total}).dropna()
    return {'NFL': (nfl, (6.0, 6.5, 7.0, 7.5), (0, 2, 4, 6)),
            'NBA': (nba, (2.0, 2.5, 3.0), (0, 3, 6, 9))}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    out = {}
    for dep, (t, ks, ds) in datos().items():
        t = t.copy()
        t['lin'] = np.floor(t['T']) + 0.5          # la principal a .5 (sin empate)
        t['dif'] = t.t_pred - t['T']
        res = []
        for k in ks:
            for lado in ('mas', 'menos'):
                L = t.lin - k if lado == 'mas' else t.lin + k
                y = (t.total > L) if lado == 'mas' else (t.total < L)
                pc = casa_p(dep, -k) if lado == 'mas' else 1 - casa_p(dep, k)
                acuerdo = t.dif if lado == 'mas' else -t.dif
                for dmin in ds:
                    m = acuerdo >= dmin
                    for tramo, f in (('elige', t.temporada <= 2020), ('juzga', t.temporada > 2020)):
                        g = y[m & f]
                        if len(g) < 30:
                            continue
                        res.append({'k': k, 'lado': lado, 'modelo_de_acuerdo_por': dmin,
                                    'tramo': tramo, 'n': int(len(g)),
                                    'acierto': round(float(g.mean()), 4),
                                    'casa_dice': round(pc, 4)})
        out[dep] = res
        df = pd.DataFrame(res)
        print('\n=====', dep)
        pv = df.pivot_table(index=['k', 'lado', 'modelo_de_acuerdo_por'], columns='tramo',
                            values=['acierto', 'n'])
        pv.columns = ['%s_%s' % c for c in pv.columns]
        pv['casa_dice'] = df.groupby(['k', 'lado', 'modelo_de_acuerdo_por']).casa_dice.first()
        print(pv.to_string())
    json.dump(out, open('_v350_totales.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
