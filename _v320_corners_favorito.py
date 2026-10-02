# -*- coding: utf-8 -*-
"""
v320 — ¿LOS CÓRNERS ACIERTAN MÁS CUANDO HAY UN FAVORITO CLARO?

Hipótesis del usuario: «córners sólo apostables cuando el favorito tiene 65 %+
de probabilidad de ganar; eso elimina los partidos donde el marcador puede
sorprender y tumbar la lógica de córners». Y después: «verifica ese 78,5 %
separando selecciones de clubes».

Sobre las filas del backtest de la v319 (`_v319_conteos_reales.py` deja
`_v319_corners_filas.pkl`: 11.874 partidos con histórico real, el modelo de
córners entrenado sólo con lo anterior al 2025-07-01), franja 70-80 %:
probabilidad del favorito = la mayor de local y visitante en las cuotas del
histórico, sin margen. Se separa total / córners de un equipo, clubes /
selecciones y primera / segunda mitad del periodo, con bootstrap por partido.

Uso: python _v320_corners_favorito.py   (escribe _v320_corners_favorito.json)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd


def _banda(z, rng):
    if not len(z):
        return {'partidos': 0}
    g = z.groupby('mid').y.agg(['sum', 'size'])
    v = [(lambda x: x['sum'].sum() / x['size'].sum())(g.iloc[rng.integers(0, len(g), len(g))])
         for _ in range(1000)]
    med = z['fecha'].quantile(.5)
    return {'partidos': int(z.mid.nunique()), 'apuestas': int(len(z)),
            'acierto': round(float(z.y.mean()), 4),
            'p5': round(float(np.percentile(v, 5)), 4), 'p95': round(float(np.percentile(v, 95)), 4),
            'primera_mitad': round(float(z[z.fecha < med].y.mean()), 4),
            'segunda_mitad': round(float(z[z.fecha >= med].y.mean()), 4)}


def main():
    rng = np.random.default_rng(320)
    P = pd.read_pickle('_v319_corners_filas.pkl')
    P = P[P.real & P.tipo.isin(['total_suma', 'local', 'visita']) & P.p.between(.70, .80)].copy()
    P['fecha'] = pd.to_datetime(P['fecha'])
    P['t'] = np.where(P.tipo == 'total_suma', 'total', 'equipo')
    P['grupo'] = np.where(P.liga == 'selecciones', 'selecciones', 'clubes')
    P['fav'] = np.where(P.fav.isna(), 'sin cuota',
                        np.where(P.fav >= .65, '65 %+', np.where(P.fav >= .50, '50-65 %', 'menor al 50 %')))
    out = {'partidos': int(P.mid.nunique()), 'acierto_todo': round(float(P.y.mean()), 4), 'grupos': {}}
    for (gr, t, f), z in P.groupby(['grupo', 't', 'fav']):
        out['grupos']['%s | %s | %s' % (gr, t, f)] = _banda(z, rng)
    e = P[(P.t == 'equipo') & (P.fav != 'sin cuota')]
    g = e.assign(k=e.fav == '65 %+').groupby('mid').agg(s=('y', 'sum'), n=('y', 'size'), k=('k', 'first'))
    bs = []
    for _ in range(2000):
        x = g.iloc[rng.integers(0, len(g), len(g))]
        a, b = x[x.k], x[~x.k]
        bs.append(a.s.sum() / a.n.sum() - b.s.sum() / b.n.sum())
    out['equipo_65_contra_resto'] = {'puntos': round(float(np.mean(bs)), 4),
                                     'p5': round(float(np.percentile(bs, 5)), 4)}
    out['adopta_equipo'] = bool(out['equipo_65_contra_resto']['p5'] > 0)
    t = P[(P.t == 'total') & (P.fav != 'sin cuota')]
    out['total_65'] = round(float(t[t.fav == '65 %+'].y.mean()), 4)
    out['total_resto'] = round(float(t[t.fav != '65 %+'].y.mean()), 4)
    out['adopta_total'] = bool(out['total_65'] > out['total_resto'])
    out['selecciones_con_cuota'] = int(P[(P.grupo == 'selecciones') & (P.fav != 'sin cuota')].mid.nunique())
    json.dump(out, open('_v320_corners_favorito.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
