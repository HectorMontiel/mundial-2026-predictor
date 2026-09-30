# -*- coding: utf-8 -*-
"""
v316 — ¿CON LAS CORRECCIONES NUEVAS SE METEN MÁS VERDES EN GOLES?

Lo que el usuario pide al final: «después de las simulaciones y las
validaciones del modelo, tener todavía un porcentaje más alto de acierto».
La mejora de log-loss de `_v316_patrones_extra.py` es pequeña; lo que decide
es si las apuestas que se dicen «meter» en goles aciertan más.

SIMULACIÓN, en el tramo de juicio (30 % más reciente del histórico, 24.310
partidos que los correctores NO vieron al entrenarse):
  · HOY: la línea de 1,5 se mueve con el corrector de 2,5; la de 3,5 con su
    corrector de siempre (tabla y medias).
  · v316: la de 1,5 con su propio corrector; la de 3,5 con los rasgos de la
    temporada (zonas y 4+ goles).
Se «mete» (como la regla de fútbol) cuando la probabilidad de un lado —más
o menos— está entre 70 % y 80 %. Se cuentan verdes y rojos por línea y en
total, con bootstrap de la diferencia de acierto.

Uso: python _v316_meter_goles.py   (escribe _v316_meter_goles.json)
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd


def main():
    import lightgbm as lgb
    import patrones_liga as pl
    df = pl.conjunto()
    ligas = sorted(df['liga'].unique())
    cod = {l: i for i, l in enumerate(ligas)}
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    ele, jui = df[df['fecha'] < corte], df[df['fecha'] >= corte].copy()

    def entrena(y_col, p_col, rasgos):
        e = ele.dropna(subset=[y_col, p_col])
        return lgb.train(pl.PARAMS, lgb.Dataset(pl._X(e, p_col, cod, rasgos),
                                                label=e[y_col].astype(int),
                                                categorical_feature=['liga_cod']),
                         num_boost_round=pl.RONDAS)
    lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
    sg = lambda z: 1 / (1 + np.exp(-z))
    m25 = entrena('over_2.5_real', 'p_over_2.5', pl.RASGOS_V1)
    m35 = entrena('over_3.5_real', 'p_over_3.5', pl.RASGOS_V1)
    m35n = entrena('over_3.5_real', 'p_over_3.5', pl.RASGOS_V3)
    m15 = entrena('over_1.5_real', 'p_over_1.5', pl.RASGOS_V1)
    j = jui.dropna(subset=['p_over_1.5', 'p_over_2.5', 'p_over_3.5'])
    p25 = m25.predict(pl._X(j, 'p_over_2.5', cod, pl.RASGOS_V1))
    d25 = np.clip(lg(p25) - lg(j['p_over_2.5'].values), -1, 1)
    hoy = {'1.5': sg(lg(j['p_over_1.5'].values) + d25),
           '3.5': m35.predict(pl._X(j, 'p_over_3.5', cod, pl.RASGOS_V1))}
    nuevo = {'1.5': m15.predict(pl._X(j, 'p_over_1.5', cod, pl.RASGOS_V1)),
             '3.5': m35n.predict(pl._X(j, 'p_over_3.5', cod, pl.RASGOS_V3))}
    real = {'1.5': j['over_1.5_real'].values, '3.5': j['over_3.5_real'].values}
    rng = np.random.default_rng(316)
    out = {'partidos_juicio': int(len(j)), 'corte': str(corte.date())}

    def elegir(p, y):
        mas = (p >= 0.70) & (p <= 0.80)
        menos = ((1 - p) >= 0.70) & ((1 - p) <= 0.80)
        return np.concatenate([y[mas], 1 - y[menos]]), \
            {'mas': int(mas.sum()), 'menos': int(menos.sum())}
    tot_h, tot_n = [], []
    for L in ('1.5', '3.5'):
        yh, nh = elegir(hoy[L], real[L])
        yn, nn = elegir(nuevo[L], real[L])
        tot_h.append(yh)
        tot_n.append(yn)
        out['linea_%s' % L] = {
            'hoy': {'apuestas': int(len(yh)), 'verdes': int(yh.sum()),
                    'acierto': round(float(yh.mean()), 4), **nh},
            'v316': {'apuestas': int(len(yn)), 'verdes': int(yn.sum()),
                     'acierto': round(float(yn.mean()), 4), **nn}}
    yh, yn = np.concatenate(tot_h), np.concatenate(tot_n)
    bs = [rng.choice(yn, len(yn)).mean() - rng.choice(yh, len(yh)).mean()
          for _ in range(2000)]
    out['total'] = {'hoy': {'apuestas': int(len(yh)), 'verdes': int(yh.sum()),
                            'rojos': int(len(yh) - yh.sum()),
                            'acierto': round(float(yh.mean()), 4)},
                    'v316': {'apuestas': int(len(yn)), 'verdes': int(yn.sum()),
                             'rojos': int(len(yn) - yn.sum()),
                             'acierto': round(float(yn.mean()), 4)},
                    'diferencia_acierto_p5': round(float(np.percentile(bs, 5)), 4),
                    'diferencia_acierto_media': round(float(np.mean(bs)), 4)}
    json.dump(out, open('_v316_meter_goles.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
