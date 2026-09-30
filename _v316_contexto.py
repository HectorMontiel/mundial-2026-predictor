# -*- coding: utf-8 -*-
"""
v316 — TRES IDEAS DEL USUARIO PARA LOS GOLES, MEDIDAS EN EL HISTÓRICO.

El usuario, después de un Millonarios–Medellín en el que el modelo marcaba
«menos de 3,5» y a media parte ya iban cuatro goles:

  1. «Puntos a la zona de playoffs o descenso, y si el partido es decisivo
     para ambos. Probar en historial con Brier o log-loss y adoptarlo sólo si
     mejora. Aunque no mueva la probabilidad, como advertencia bajaría la
     confianza a media en los unders.»
  2. «Goles a favor y en contra por partido, local y visita, con el % de
     partidos con 4 o más goles.» (y la «g» de la forma es ambigua)
  3. «Cola de la distribución: revisar cómo calibra P(4 o más goles), por
     ejemplo con una binomial negativa.»

LOS DATOS
`pick_ledger_totales.csv`: 80.829 predicciones de goles FUERA DE MUESTRA del
motor de ligas (61 competiciones, 2018-2026), cada una con su resultado. La
tabla de cada liga se reconstruye con su histórico
(`panel_equipos._historico`), partido a partido y SÓLO con lo anterior: una
temporada nueva empieza cuando la liga para más de 35 días.

LA PRUEBA
Recalibración logística de la probabilidad del modelo con y sin cada grupo
de variables, ajustada en el 70 % más antiguo (elección) y juzgada en el 30 %
más reciente (prueba) con log-loss, Brier y bootstrap por partido. Se adopta
sólo si mejora en los dos tramos con p5 > 0 en prueba.

Uso: python _v316_contexto.py   (escribe _v316_contexto.json)
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

SALIDA = '_v316_contexto.json'
COPAS = {'champions', 'europa_league', 'conference_league', 'libertadores',
         'sudamericana', 'leagues_cup', 'afc_champions'}


def _tablas(clave: str) -> pd.DataFrame:
    """Para cada partido del histórico de `clave`, la tabla ANTES de jugarlo."""
    import panel_equipos as pe
    h = pe._historico(clave)
    if h is None or h.empty:
        return pd.DataFrame()
    h = h.dropna(subset=['home_goals', 'away_goals']).sort_values('date')
    filas = []
    est, ult_fecha, n_prev = {}, None, None
    for r in h.itertuples(index=False):
        if ult_fecha is not None and (r.date - ult_fecha).days > 35:
            n_prev = len(est) or n_prev
            est = {}
        ult_fecha = r.date
        H, A = r.home_team, r.away_team
        for t in (H, A):
            est.setdefault(t, {'pts': 0, 'pj': 0, 'gf': 0, 'gc': 0, 'n4': 0,
                               'hgf': 0, 'hgc': 0, 'hn': 0, 'agf': 0, 'agc': 0, 'an': 0})
        N = max(len(est), n_prev or 0)
        orden = sorted(est.items(), key=lambda kv: (-kv[1]['pts'],
                                                    -(kv[1]['gf'] - kv[1]['gc'])))
        pts_rank = [v['pts'] for _, v in orden]
        k_top = max(1, round(0.25 * N))
        k_bot = max(1, round(0.15 * N))
        b_top = pts_rank[min(k_top, len(pts_rank)) - 1]
        b_bot = pts_rank[max(0, len(pts_rank) - k_bot)] if len(pts_rank) >= N - k_bot + 1 \
            else pts_rank[-1]
        eh, ea = est[H], est[A]
        prog = ((eh['pj'] + ea['pj']) / 2) / max(1, 2 * (N - 1))

        def _pm(x, n):
            return x / n if n >= 3 else np.nan
        filas.append({
            'MATCH_ID': r.MATCH_ID, 'prog': prog,
            'gap_top_h': eh['pts'] - b_top, 'gap_bot_h': eh['pts'] - b_bot,
            'gap_top_a': ea['pts'] - b_top, 'gap_bot_a': ea['pts'] - b_bot,
            'gf_h_casa': _pm(eh['hgf'], eh['hn']), 'gc_h_casa': _pm(eh['hgc'], eh['hn']),
            'gf_a_fuera': _pm(ea['agf'], ea['an']), 'gc_a_fuera': _pm(ea['agc'], ea['an']),
            'p4_h': _pm(eh['n4'], eh['pj']), 'p4_a': _pm(ea['n4'], ea['pj'])})
        gh, ga = int(r.home_goals), int(r.away_goals)
        for t, gf, gc, casa in ((H, gh, ga, True), (A, ga, gh, False)):
            e = est[t]
            e['pj'] += 1
            e['gf'] += gf
            e['gc'] += gc
            e['n4'] += int(gh + ga >= 4)
            e['pts'] += 3 if gf > gc else (1 if gf == gc else 0)
            if casa:
                e['hgf'] += gf; e['hgc'] += gc; e['hn'] += 1
            else:
                e['agf'] += gf; e['agc'] += gc; e['an'] += 1
    return pd.DataFrame(filas)


def construir() -> pd.DataFrame:
    L = pd.read_csv('pick_ledger_totales.csv')
    partes = []
    for clave, x in L.groupby('liga'):
        t = _tablas(clave)
        if t.empty:
            continue
        m = x.merge(t, left_on='match_id', right_on='MATCH_ID', how='left')
        if clave in COPAS:
            for c in ('gap_top_h', 'gap_bot_h', 'gap_top_a', 'gap_bot_a'):
                m[c] = np.nan
        partes.append(m)
        print(clave, len(x), 'tabla', int(m['prog'].notna().sum()), flush=True)
    d = pd.concat(partes, ignore_index=True)
    d.to_csv('_v316_contexto.csv', index=False)
    return d


def variables(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()

    def en_juego(top, bot):
        return (top.abs() <= 3) | (bot.abs() <= 3)
    tarde = d['prog'] >= 0.5
    jh = en_juego(d['gap_top_h'], d['gap_bot_h'])
    ja = en_juego(d['gap_top_a'], d['gap_bot_a'])
    d['decisivo_ambos'] = (tarde & jh & ja).astype(float)
    lejos_h = (d['gap_top_h'].abs() > 6) & (d['gap_bot_h'].abs() > 6)
    lejos_a = (d['gap_top_a'].abs() > 6) & (d['gap_bot_a'].abs() > 6)
    d['nada_en_juego'] = ((d['prog'] >= 0.6) & lejos_h & lejos_a).astype(float)
    # total que dicen las tablas: lo que mete el local en casa con lo que
    # recibe el visitante fuera, y al revés
    tot = ((d['gf_h_casa'] + d['gc_a_fuera']) / 2 + (d['gf_a_fuera'] + d['gc_h_casa']) / 2)
    d['tabla_menos_modelo'] = (tot - d['lam_total_prod']).fillna(0).clip(-3, 3)
    p4 = (d['p4_h'] + d['p4_a']) / 2
    d['p4_equipos'] = (p4 - d.groupby('liga')['over_3.5_real'].transform('mean')).fillna(0)
    return d


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def ajustar(X, y):
    """Regresión logística por Newton, sin librerías extra."""
    X = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X.shape[1])
    for _ in range(30):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (y - p)
        Hm = (X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(len(w))
        w += np.linalg.solve(Hm, g)
    return w


def predecir(w, X):
    X = np.column_stack([np.ones(len(X)), X])
    return 1 / (1 + np.exp(-X @ w))


def medir(d, objetivo, pcol, extras, rng):
    E = d[d['fecha'] < d['_corte']]
    P = d[d['fecha'] >= d['_corte']]
    out = {}
    for nombre, cols in (('solo recalibrar', []), ('+ contexto de tabla', ['decisivo_ambos', 'nada_en_juego']),
                         ('+ goles de la tabla', ['tabla_menos_modelo', 'p4_equipos']),
                         ('+ todo', ['decisivo_ambos', 'nada_en_juego', 'tabla_menos_modelo', 'p4_equipos'])):
        XE = np.column_stack([_logit(E[pcol].values)] + [E[c].values for c in cols])
        XP = np.column_stack([_logit(P[pcol].values)] + [P[c].values for c in cols])
        w = ajustar(XE, E[objetivo].values.astype(float))
        pe_, pp_ = predecir(w, XE), predecir(w, XP)
        yE, yP = E[objetivo].values, P[objetivo].values
        ll = lambda p, y: float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p))))
        out[nombre] = {'coef': [round(float(x), 4) for x in w],
                       'logloss_eleccion': round(ll(pe_, yE), 5),
                       'logloss_prueba': round(ll(pp_, yP), 5),
                       'brier_prueba': round(float(np.mean((pp_ - yP) ** 2)), 5),
                       '_pp': pp_}
    base = out['solo recalibrar']['_pp']
    yP = P[objetivo].values
    for k, v in out.items():
        if k == 'solo recalibrar':
            continue
        dif = (base - yP) ** 2 - (v['_pp'] - yP) ** 2
        bs = [dif[rng.integers(0, len(dif), len(dif))].mean() for _ in range(1000)]
        v['mejora_brier_prueba'] = round(float(np.mean(dif)), 6)
        v['p5'] = round(float(np.percentile(bs, 5)), 6)
        v['adopta'] = bool(v['logloss_eleccion'] < out['solo recalibrar']['logloss_eleccion']
                           and v['logloss_prueba'] < out['solo recalibrar']['logloss_prueba']
                           and v['p5'] > 0)
    for v in out.values():
        v.pop('_pp')
    return out


def cola(d, rng):
    """P(4+ goles): lo de producción, Poisson y binomial negativa con la media
    del modelo. La dispersión se elige en elección."""
    from scipy import stats
    E = d[d['fecha'] < d['_corte']]
    P = d[d['fecha'] >= d['_corte']]
    lam = lambda x: x['lam_total_prod'].values

    def p4_nb(m, k):
        if k is None:
            return 1 - stats.poisson.cdf(3, m)
        n = k
        p = n / (n + m)
        return 1 - stats.nbinom.cdf(3, n, p)
    ll = lambda p, y: float(np.mean(-(y * np.log(np.clip(p, 1e-4, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-4, 1)))))
    res = {}
    grid = {}
    for k in (None, 5, 10, 20, 40, 80):
        grid[str(k)] = ll(p4_nb(lam(E), k), E['over_3.5_real'].values)
    kbest = min(grid, key=grid.get)
    kb = None if kbest == 'None' else float(kbest)
    for nombre, pe_, pp_ in (('producción', E['p_over_3.5'].values, P['p_over_3.5'].values),
                             ('Poisson(λ modelo)', p4_nb(lam(E), None), p4_nb(lam(P), None)),
                             ('binomial negativa k=%s' % kbest, p4_nb(lam(E), kb), p4_nb(lam(P), kb))):
        yP = P['over_3.5_real'].values
        b = pd.cut(pp_, [0, .2, .25, .3, .35, .4, .5, 1])
        res[nombre] = {'logloss_eleccion': round(ll(pe_, E['over_3.5_real'].values), 5),
                       'logloss_prueba': round(ll(pp_, yP), 5),
                       'brier_prueba': round(float(np.mean((pp_ - yP) ** 2)), 5),
                       'bandas_prueba': {str(k): {'n': int(len(v)), 'p': round(float(np.mean(pp_[v.index])), 3),
                                                  'real': round(float(yP[v.index].mean()), 3)}
                                         for k, v in pd.Series(range(len(pp_))).groupby(b, observed=True)}}
    res['grid_eleccion'] = grid
    return res


def main():
    import os
    rng = np.random.default_rng(0)
    d = pd.read_csv('_v316_contexto.csv') if os.path.exists('_v316_contexto.csv') \
        and '--rehacer' not in sys.argv else construir()
    d = variables(d)
    d = d[d['prog'].notna()].copy()
    d['_corte'] = d['fecha'].quantile(0.7) if False else sorted(d['fecha'])[int(len(d) * 0.7)]
    out = {'predicciones': int(len(d)), 'ligas': int(d['liga'].nunique()),
           'corte': str(d['_corte'].iloc[0])}
    out['over_2.5'] = medir(d, 'over_2.5_real', 'p_over_2.5', None, rng)
    out['over_3.5'] = medir(d, 'over_3.5_real', 'p_over_3.5', None, rng)
    # 1-bis) la advertencia: ¿los unders fallan más cuando es decisivo?
    u = d.assign(p_under=1 - d['p_over_3.5'], y_under=1 - d['over_3.5_real'])
    u = u[(u['p_under'] >= 0.70) & (u['p_under'] <= 0.80)]
    out['under_3.5_franja_70_80'] = {
        str(k): {'n': int(len(v)), 'acierto': round(float(v['y_under'].mean()), 4)}
        for k, v in u.groupby('decisivo_ambos')}
    u2 = d.assign(p_under=1 - d['p_over_2.5'], y_under=1 - d['over_2.5_real'])
    u2 = u2[(u2['p_under'] >= 0.55)]
    out['under_2.5_mayor_55'] = {
        str(k): {'n': int(len(v)), 'acierto': round(float(v['y_under'].mean()), 4)}
        for k, v in u2.groupby('decisivo_ambos')}
    out['cola_4_goles'] = cola(d, rng)
    json.dump(out, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
