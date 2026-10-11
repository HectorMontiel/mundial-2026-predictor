#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v361 — Lo que enseña la tabla del análisis, contra el histórico.

La tabla del «Método Contexto» (`modo_modelo.metodo_contexto`) pone, por
estadística, el total esperado del partido y la línea «más de X» más alta que
el método ve al 70 % o más. ¿Cuánto se cumple de verdad esa línea?

Con `_v361_metodo.preparar()` (59.120 filas equipo-partido, 26 ligas): el
método se entrena con el 70 % más antiguo y se juzga con el 30 % reciente,
partido a partido (los dos equipos), en dos mitades del tramo de juicio. Por
estadística: cuántas veces sale línea, cuánto promete y cuánto acierta, y el
acierto por banda de lo que promete (70-75, 75-80, 80-85, 85+).
Escribe `_v361_lineas_hist.json`."""
import json
import sys

import numpy as np
import pandas as pd

import _v361_metodo as V
import tiros_equipo as te

OBJ = V.OBJ


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import lightgbm as lgb
    e = V.preparar()
    corte = e.fecha.quantile(0.70)
    ent, jui = e[e.fecha < corte], e[e.fecha >= corte].copy()
    mitad = jui.fecha.quantile(0.5)
    out = {'corte': str(corte)[:10], 'mitad': str(mitad)[:10], 'objetivos': {}}
    for nombre, col in OBJ.items():
        a = ent.dropna(subset=[col])
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=700, learning_rate=0.03,
                              num_leaves=31, min_child_samples=80, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                              verbose=-1, random_state=361)
        m.fit(a[te.COLUMNAS], a[col])
        c2 = a.fecha.quantile(0.85)
        k = te.ajustar_k(a[a.fecha >= c2][col].values,
                         np.clip(m.predict(a[a.fecha >= c2][te.COLUMNAS]), 0.05, None))
        b = jui.dropna(subset=[col]).copy()
        b['mu'] = np.clip(m.predict(b[te.COLUMNAS]), 0.05, None)
        g = b.groupby('mid').agg(mu_t=('mu', 'sum'), mu2=('mu', lambda x: float((x ** 2).sum())),
                                 real=(col, 'sum'), n=('mu', 'size'), fecha=('fecha', 'first'))
        g = g[g.n == 2]
        filas = []
        for r in g.itertuples():
            k_t = (r.mu_t ** 2) / max(r.mu2 / k, 1e-9) if k < 400 else 1e6
            for n in range(int(r.mu_t) + 1, -1, -1):
                p = te.prob_mas(r.mu_t, n + 0.5, k_t)
                if p >= 0.70:
                    filas.append({'p': p, 'linea': n + 0.5, 'ok': int(r.real > n + 0.5),
                                  'tramo': 'A' if r.fecha < mitad else 'B'})
                    break
        f = pd.DataFrame(filas)
        res = {'partidos': int(len(g)), 'con_linea': int(len(f)), 'k': round(k, 1)}
        for tr in ('A', 'B'):
            x = f[f.tramo == tr]
            res[tr] = {'n': int(len(x)), 'promete': round(float(x.p.mean()), 4),
                       'acierta': round(float(x.ok.mean()), 4)}
        bb = pd.cut(f.p, [0.70, 0.75, 0.80, 0.85, 1.0])
        res['bandas'] = [{'banda': str(kk), 'n': int(len(x)), 'promete': round(float(x.p.mean()), 3),
                          'acierta': round(float(x.ok.mean()), 3)}
                         for kk, x in f.groupby(bb, observed=True)]
        out['objetivos'][nombre] = res
        print(nombre, json.dumps(res, ensure_ascii=False))
    json.dump(out, open('_v361_lineas_hist.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
