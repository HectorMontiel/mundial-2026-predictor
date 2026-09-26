# -*- coding: utf-8 -*-
"""
v310 — ¿CUÁNTO PESO DARLE AL MODELO FRENTE A LA CASA? CON CUOTAS PREVIAS.

`concordancia.PESO_MODELO = 0,5` se fijó a propósito POR DEBAJO de lo que
decían los datos (óptimo w = 0, sólo la casa), porque aquellos datos eran
cuotas de CIERRE: «si algún día hay ledger con cuotas pre-partido, se vuelve a
medir y PESO_MODELO se mueve con evidencia limpia, no antes».

Ya la hay. `odds_historico.db` guarda fotos PREVIAS al partido (fase
`snapshot`: Pinnacle, Playdoit, Bovada, DraftKings, del 2026-07-28 al 09-06)
de partidos que están en los ledgers fuera de muestra. Y el registro de
apuestas de la app (1.238 liquidadas) dijo lo mismo por otro lado: cuando el
modelo dice más que la casa, acierta menos de lo que promete.

Para cada partido y mercado: p del modelo (ledger fuera de muestra; ambos
marcan pasado por `calibrador_btts`, como en producción), p de la casa sin
margen (mediana de las fotos previas), y la mezcla w·modelo + (1−w)·casa.
Log-loss por partido, tramos por fecha (elección 70 % / juicio 30 %) y
bootstrap de la mejora de cada w contra el 0,5 de hoy.

Uso: python _v310_peso_casa.py     (escribe _v310_peso_casa.json)
"""
from __future__ import annotations

import json
import sqlite3
import sys

import numpy as np
import pandas as pd

PESOS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
B = 2000


def _ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def casa() -> pd.DataFrame:
    c = sqlite3.connect('odds_historico.db')
    d = pd.read_sql("select * from historical_odds where fase='snapshot'", c)
    fil = []
    for r in d.itertuples(index=False):
        f = {'match_id': r.match_id}
        o = [r.odds_home, r.odds_draw, r.odds_away]
        if all(x and x > 1 for x in o):
            inv = [1 / x for x in o]
            s = sum(inv)
            if 1.0 <= s <= 1.6:
                f.update(c_home=inv[0] / s, c_draw=inv[1] / s, c_away=inv[2] / s)
        for a, b, k in ((r.odds_over25, r.odds_under25, 'c_over25'),
                        (r.odds_btts_yes, r.odds_btts_no, 'c_btts')):
            if a and b and a > 1 and b > 1:
                s = 1 / a + 1 / b
                if 1.0 <= s <= 1.6:
                    f[k] = (1 / a) / s
        fil.append(f)
    return pd.DataFrame(fil).groupby('match_id').median().reset_index()


def filas() -> pd.DataFrame:
    import calibrador_btts as cb
    k = casa()
    l = pd.read_csv('pick_ledger.csv', low_memory=False)
    t = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    out = []
    m = l.merge(k, on='match_id')
    for lado, pm, pc, res in (('local', 'p_home', 'c_home', 0),
                              ('empate', 'p_draw', 'c_draw', 1),
                              ('visita', 'p_away', 'c_away', 2)):
        x = m.dropna(subset=[pm, pc])
        out.append(pd.DataFrame({'mercado': '1X2 ' + lado, 'mid': x['match_id'],
                                 'fecha': x['fecha'], 'liga': x['liga'],
                                 'p_mod': x[pm], 'p_casa': x[pc],
                                 'y': (x['resultado'] == res).astype(int)}))
    m = t.merge(k, on='match_id')
    x = m.dropna(subset=['p_over_2.5', 'c_over25'])
    out.append(pd.DataFrame({'mercado': 'Más de 2.5', 'mid': x['match_id'],
                             'fecha': x['fecha'], 'liga': x['liga'],
                             'p_mod': x['p_over_2.5'], 'p_casa': x['c_over25'],
                             'y': x['over_2.5_real']}))
    x = m.dropna(subset=['p_btts', 'c_btts'])
    pb = [cb.calibrar_si_activo(p, lg) for p, lg in zip(x['p_btts'], x['liga'])]
    out.append(pd.DataFrame({'mercado': 'Ambos marcan', 'mid': x['match_id'],
                             'fecha': x['fecha'], 'liga': x['liga'],
                             'p_mod': pb, 'p_casa': x['c_btts'],
                             'y': x['btts_real']}))
    d = pd.concat(out, ignore_index=True).dropna()
    d['fecha'] = pd.to_datetime(d['fecha'])
    return d


def boot(delta: np.ndarray, rng) -> dict:
    bs = [delta[rng.integers(0, len(delta), len(delta))].mean() for _ in range(B)]
    return {'mejora_vs_0.5': round(float(delta.mean()), 5),
            'p5': round(float(np.percentile(bs, 5)), 5)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = filas()
    rng = np.random.default_rng(310)
    doc = {'n': int(len(d)), 'partidos': int(d['mid'].nunique()),
           'desde': str(d['fecha'].min().date()),
           'hasta': str(d['fecha'].max().date()), 'mercados': {}}
    fam = {'1X2 local': '1X2', '1X2 empate': '1X2', '1X2 visita': '1X2',
           'Más de 2.5': 'Goles', 'Ambos marcan': 'Goles'}
    d['familia'] = d['mercado'].map(fam)
    for grupo, x in list(d.groupby('familia')) + [('todo', d)]:
        x = x.sort_values('fecha')
        q70 = x['fecha'].quantile(0.7)
        res = {'n': int(len(x))}
        for tramo, g in (('eleccion', x[x['fecha'] <= q70]),
                         ('juicio', x[x['fecha'] > q70])):
            base = _ll(0.5 * g['p_mod'] + 0.5 * g['p_casa'], g['y'])
            r = {'n': int(len(g))}
            for w in PESOS:
                llw = _ll(w * g['p_mod'] + (1 - w) * g['p_casa'], g['y'])
                r['w=%.2f' % w] = dict(logloss=round(float(llw.mean()), 5),
                                       **boot((base - llw).values, rng))
            res[tramo] = r
        doc['mercados'][grupo] = res
        print(grupo, json.dumps(res, ensure_ascii=False))
    json.dump(doc, open('_v310_peso_casa.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print({k: doc[k] for k in ('n', 'partidos', 'desde', 'hasta')})


if __name__ == '__main__':
    main()
