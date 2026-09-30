# -*- coding: utf-8 -*-
"""
v316 — ¿LO QUE PROPUSO EL USUARIO AÑADE ALGO A `patrones_liga`?

`patrones_liga` (v302/v306) ya corrige los goles con la tabla y la forma de
cada equipo: goles a favor y en contra (10 y 5 últimos), lo de casa del local
y lo de fuera del visitante, puntos por partido… y está ACTIVO en «más de
2,5» y «más de 3,5» (que es la cola de 4+ goles). Lo que el usuario propone y
aún no tiene:

  · el % de partidos con 4 o más goles de cada equipo en la temporada;
  · los puntos a la zona de arriba y al descenso, el avance de la temporada,
    y si el partido es decisivo para los dos (o si ya no se juegan nada);
  · la línea de 1,5 goles, que la aplicación mete mucho y no se corregía.

Misma prueba que `patrones_liga.entrenar`: LightGBM en el 70 % antiguo,
juicio en el 30 % reciente, bootstrap 2.000 del log-loss. Se adopta sólo si
el conjunto con los rasgos nuevos le gana al de siempre con p5 > 0.

Uso: python _v316_patrones_extra.py   (escribe _v316_patrones_extra.json)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

EXTRA = ['p4_h', 'p4_a', 'gap_top_h', 'gap_bot_h', 'gap_top_a', 'gap_bot_a',
         'prog', 'decisivo_ambos', 'nada_en_juego']
OBJ = {'mas15': ('over_1.5_real', 'p_over_1.5'),
       'mas25': ('over_2.5_real', 'p_over_2.5'),
       'mas35': ('over_3.5_real', 'p_over_3.5')}


def main():
    import lightgbm as lgb
    import patrones_liga as pl
    import _v316_contexto as ctx
    df = pl.conjunto()
    c = ctx.variables(pd.read_csv('_v316_contexto.csv'))
    c = c[['match_id'] + [x for x in EXTRA if x in c.columns]].drop_duplicates('match_id')
    df = df.merge(c, on='match_id', how='left')
    ligas = sorted(df['liga'].unique())
    codigos = {l: i for i, l in enumerate(ligas)}
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    ele, jui = df[df['fecha'] < corte], df[df['fecha'] >= corte]
    rng = np.random.default_rng(302)
    out = {'n': int(len(df)), 'n_juicio': int(len(jui)), 'corte': str(corte.date())}

    def X(d, p_col, rasgos):
        x = pl._X(d, p_col, codigos, rasgos=[r for r in rasgos if r not in EXTRA])
        for r in rasgos:
            if r in EXTRA:
                x[r] = d[r].astype(float).values
        return x
    base_r = list(pl.RASGOS_V1)
    for nombre, (y_col, p_col) in OBJ.items():
        e = ele.dropna(subset=[y_col, p_col])
        j = jui.dropna(subset=[y_col, p_col])
        y = j[y_col].astype(int).to_numpy()
        res = {}
        preds = {}
        for etq, rasgos in (('siempre', base_r),
                            ('+ 4 o más goles', base_r + ['p4_h', 'p4_a']),
                            ('+ zonas de la tabla', base_r + ['gap_top_h', 'gap_bot_h', 'gap_top_a',
                                                             'gap_bot_a', 'prog', 'decisivo_ambos',
                                                             'nada_en_juego']),
                            ('+ todo', base_r + EXTRA)):
            bst = lgb.train(pl.PARAMS, lgb.Dataset(X(e, p_col, rasgos), label=e[y_col].astype(int),
                                                   categorical_feature=['liga_cod']),
                            num_boost_round=pl.RONDAS)
            preds[etq] = bst.predict(X(j, p_col, rasgos))
        p_cal = pl._base_calibrada(e, j, y_col, p_col)
        idx = rng.integers(0, len(y), size=(2000, len(y)))
        ll_cal = pl._ll(y, p_cal)
        res['log-loss base calibrada'] = round(float(ll_cal.mean()), 5)
        for etq, p in preds.items():
            ll = pl._ll(y, p)
            d0 = ll_cal - ll
            r = {'log-loss': round(float(ll.mean()), 5),
                 'mejora_vs_base': round(float(d0.mean()), 5),
                 'p5_vs_base': round(float(np.percentile(d0[idx].mean(axis=1), 5)), 5)}
            if etq != 'siempre':
                d1 = pl._ll(y, preds['siempre']) - ll
                r['mejora_vs_siempre'] = round(float(d1.mean()), 5)
                r['p5_vs_siempre'] = round(float(np.percentile(d1[idx].mean(axis=1), 5)), 5)
                r['adopta'] = bool(d1.mean() > 0 and r['p5_vs_siempre'] > 0)
            res[etq] = r
        out[nombre] = res
        print(nombre, json.dumps(res, ensure_ascii=False), flush=True)
    json.dump(out, open('_v316_patrones_extra.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
