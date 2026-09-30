# -*- coding: utf-8 -*-
"""
v316 — LOS CÓRNERS CON LA TABLA CONTRA LOS DE PRODUCCIÓN.

`_v316_tabla_mercados.py` midió que la tabla le añade mucho a los córners de
cada equipo, pero contra un modelo sencillo de forma de córners. Lo que
decide si entra es ganarle a PRODUCCIÓN: el estimador ataque/defensa del
rival (ventana 10) con su binomial negativa, que es lo que ve la tarjeta.

CÓMO
`_v310_conteos.csv` guarda las λ de córners que dio producción para 2.812
partidos (Liga MX, Champions, Europa, Conference, selecciones), cada una
calculada con el histórico recortado a lo anterior al partido. Aquí:
  · los modelos de `corners_tabla` se entrenan SÓLO con partidos anteriores
    al 2024-07-01 (de todas las ligas);
  · en los partidos de `_v310` desde esa fecha, se compara la λ de
    producción con la de la forma de córners sola y con la de «+ tabla»,
    todas con la MISMA dispersión de producción, en las líneas de equipo
    2,5 a 6,5 (más y menos).
Log-loss con bootstrap 2.000 por partido; y el acierto de lo que se
ofrecería (lado con 70 % o más, y la franja 70-80 % que es la de «meter»).
Se adopta si «+ tabla» le gana a producción con p5 > 0 y no acierta menos.

Uso: python _v316_corners_tabla.py   (escribe _v316_corners_tabla.json)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

CORTE = pd.Timestamp('2024-07-01')
LINEAS = (2.5, 3.5, 4.5, 5.5, 6.5)


def main():
    import corners_tabla as ct
    import patrones_liga as pl
    import rendimiento_equipos as rq
    df = ct.conjunto()
    lg = sorted(df['liga'].unique())
    cod = {l: i for i, l in enumerate(lg)}
    ent = df[df['fecha'] < CORTE]
    r_forma = ct.CORNERS + ['liga_cod']
    r_tabla = ct.rasgos_modelo()
    mods = {'forma': ct.ajustar_modelos(ent, cod, r_forma),
            'tabla': ct.ajustar_modelos(ent, cod, r_tabla)}
    v = pd.read_csv('_v310_conteos.csv', parse_dates=['fecha'])
    v = v[(v['mercado'] == 'corners') & (v['origen'] == 'observado')
          & (v['fecha'] >= CORTE)].copy()
    df['dia'] = df['fecha'].dt.normalize()
    v['dia'] = v['fecha'].dt.normalize()
    x = v.merge(df, left_on=['clave', 'dia', 'home', 'away'],
                right_on=['liga', 'dia', 'home', 'away'], how='inner',
                suffixes=('', '_f'))
    x = x.drop_duplicates(['clave', 'dia', 'home', 'away'])
    for nombre, rs in (('forma', r_forma), ('tabla', r_tabla)):
        X = ct._X(x, cod, rs)
        x['lh_' + nombre] = mods[nombre]['local'].predict(X)
        x['la_' + nombre] = mods[nombre]['visita'].predict(X)
    x['lh_prod'], x['la_prod'] = x['lam_h'], x['lam_a']
    filas = []
    for i, r in enumerate(x.itertuples(index=False)):
        for lado, real, col in (('local', r.real_h, 'lh'), ('visita', r.real_a, 'la')):
            for L in LINEAS:
                y = int(real > L)
                f = {'partido': i, 'clave': r.clave, 'lado': lado, 'linea': L, 'y': y}
                for m in ('prod', 'forma', 'tabla'):
                    f[m] = rq.prob_mas_de(getattr(r, '%s_%s' % (col, m)), L, r.disp)
                filas.append(f)
    P = pd.DataFrame(filas).dropna()
    # más y menos
    P = pd.concat([P, P.assign(y=1 - P['y'], prod=1 - P['prod'], forma=1 - P['forma'],
                               tabla=1 - P['tabla'])], ignore_index=True)
    rng = np.random.default_rng(316)
    out = {'partidos': int(len(x)), 'de_v310': int(len(v)), 'corte': str(CORTE.date()),
           'por_competicion': {k: int(n) for k, n in x['clave'].value_counts().items()}}
    ll = {m: pl._ll(P['y'].to_numpy(), P[m].to_numpy()) for m in ('prod', 'forma', 'tabla')}
    g = P.assign(**{'ll_' + m: ll[m] for m in ll}).groupby('partido')
    sumas = g[['ll_prod', 'll_forma', 'll_tabla']].sum()
    cuenta = g.size()
    ids = sumas.index.to_numpy()
    for m in ('prod', 'forma', 'tabla'):
        sel = P[m] >= .70
        ban = (P[m] >= .70) & (P[m] < .80)
        out[m] = {'log-loss': round(float(ll[m].mean()), 5),
                  'ofrecidas_70': int(sel.sum()),
                  'acierto_70': round(float(P.loc[sel, 'y'].mean()), 4) if sel.any() else None,
                  'franja_70_80': int(ban.sum()),
                  'acierto_70_80': round(float(P.loc[ban, 'y'].mean()), 4) if ban.any() else None}
    for m in ('forma', 'tabla'):
        d = (sumas['ll_prod'] - sumas['ll_' + m])
        bs = []
        for _ in range(2000):
            s = rng.choice(ids, len(ids))
            bs.append(d.loc[s].sum() / cuenta.loc[s].sum())
        out[m]['mejora_vs_prod'] = round(float(d.sum() / cuenta.sum()), 5)
        out[m]['p5_vs_prod'] = round(float(np.percentile(bs, 5)), 5)
    out['adopta'] = bool(out['tabla']['mejora_vs_prod'] > 0 and out['tabla']['p5_vs_prod'] > 0
                         and (out['tabla']['acierto_70'] or 0) >= (out['prod']['acierto_70'] or 0))
    # por lado, para el informe
    out['por_lado'] = {}
    for lado, z in P.groupby('lado'):
        out['por_lado'][lado] = {m: round(float(pl._ll(z['y'].to_numpy(), z[m].to_numpy()).mean()), 5)
                                 for m in ('prod', 'forma', 'tabla')}
    json.dump(out, open('_v316_corners_tabla.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
