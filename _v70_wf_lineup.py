#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejoras A y B — validación del ajuste de λ por alineación y por portero.

Protocolo
---------
Walk-forward expandente de 5 pliegues. En cada pliegue:

  1. Se entrenan los DOS regresores Poisson de producción (λ local, λ visitante)
     con los partidos anteriores al corte, sobre exactamente las mismas features
     que usa `entrenar_liga`.
  2. Con esos mismos datos de train se calibra β (y γ) minimizando la
     **desvianza de Poisson** entre las λ ajustadas y los goles reales. Nunca se
     mira el test.
  3. Se aplica el ajuste a las λ del test y se comparan cuatro ramas.

Qué se mide
-----------
· `deviance` — desvianza de Poisson de los goles. Es el objetivo directo del
  ajuste y lo que dice si las alineaciones informan sobre los goles.
· `acc` / `ll` del 1X2 **derivado de la matriz de marcadores** (dos Poisson
  independientes). Es el efecto real del ajuste sobre el 1X2, porque en
  producción λ gobierna la matriz, el marcador exacto y los mercados de goles;
  el 1X2 del clasificador no se toca.

Ramas: `base` (sin ajuste) · `lineup` (sólo β) · `gk` (sólo γ) · `ambos`.

Salida: `_v70_wf_lineup.json`
"""
import argparse
import json
import logging
import os
import warnings
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_wf_lineup.json'
N_PLIEGUES = 5
FRAC_TEST = 0.40
N_MAX = 11                       # goles máximos para la matriz de marcadores

# liga del proyecto -> liga de ESPN
LIGAS = {'mls': 'usa.1', 'liga_mx': 'mex.1'}

# Alias que `name_mapper` no resuelve solo. «Los Angeles FC» se le parece más a
# «MLS All-Stars» (0.50) que a «LAFC» por puro solapamiento de caracteres, y
# «Los Angeles Galaxy» se queda en 0.67 con «LA Galaxy», por debajo del umbral.
# Sin esto se pierden los dos equipos de Los Ángeles del histórico.
ALIAS = {
    'usa.1': {'Los Angeles FC': 'LAFC', 'Los Angeles Galaxy': 'LA Galaxy'},
}

MALLA_BETA = np.round(np.arange(-0.30, 0.3001, 0.02), 4)
MALLA_GAMMA = np.round(np.arange(-0.20, 0.2001, 0.02), 4)
MALLA_DELTA = np.round(np.arange(-0.30, 0.3001, 0.02), 4)
CERO = [0.0]


def deviance_poisson(y, lam):
    lam = np.clip(lam, 1e-6, None)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(y > 0, y * np.log(y / lam), 0.0)
    return float(2.0 * np.sum(t - (y - lam)))


def probs_1x2(lam_h, lam_a):
    """
    1X2 por convolución de dos Poisson independientes.

    OJO con la orientación de la matriz: `M[i, j] = P(local=i, visitante=j)`,
    así que el LOCAL gana cuando i > j, es decir en el triángulo INFERIOR
    (`tril`, k=-1), y el visitante en el superior. Tenerlo al revés da una
    precisión del 29 % —por debajo del azar— que es como se detectó.
    """
    from scipy.stats import poisson
    kk = np.arange(N_MAX)
    out = np.zeros((len(lam_h), 3))
    for i in range(len(lam_h)):
        M = np.outer(poisson.pmf(kk, lam_h[i]), poisson.pmf(kk, lam_a[i]))
        M = M / M.sum()
        out[i] = [np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()]
    return np.clip(out, 1e-6, 1)


def emparejar(clave: str, liga_espn: str):
    """
    Cruza el histórico de la liga con las alineaciones de ESPN.

    Los nombres NO coinciden entre fuentes (trampa §4.2.4 del proyecto), así que
    se pasa por `name_mapper` con el catálogo de ESPN y se empareja por
    (fecha ±1 día, local, visitante). El desfase de un día cubre los partidos
    nocturnos, que ESPN fecha en UTC.
    """
    import lineup_impact as li
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    fz = li.fuerza_alineaciones(liga_espn)
    if fz.empty:
        raise RuntimeError(f'{liga_espn}: sin alineaciones recolectadas')
    fz['fecha'] = pd.to_datetime(fz['fecha'])

    catalogo = sorted(set(fz['home']) | set(fz['away']))
    equipos = sorted(set(df['home_team']) | set(df['away_team']))
    mapa = {e: v for e, v in ALIAS.get(liga_espn, {}).items() if v in catalogo}
    try:
        import name_mapper
        for e in equipos:
            if e in mapa:
                continue
            if e in catalogo:
                mapa[e] = e
                continue
            m = name_mapper.mapear(e, catalogo, contexto=f'lineup/{liga_espn}')
            if m:
                mapa[e] = m
    except Exception as e:
        logger.warning(f"name_mapper no disponible: {e}")
    for e in equipos:
        mapa.setdefault(e, e)
    logger.info(f"[{clave}] {sum(1 for e in equipos if mapa[e] in catalogo)}"
                f"/{len(equipos)} equipos mapeados a ESPN")

    idx = {}
    for r in fz.itertuples(index=False):
        for off in (0, 1, -1):
            idx.setdefault((r.fecha.normalize() + pd.Timedelta(days=off),
                            r.home, r.away), r)
    ld, gd, dl = [], [], []
    for r in df.itertuples(index=False):
        k = (pd.Timestamp(r.date).normalize(),
             mapa.get(r.home_team, r.home_team), mapa.get(r.away_team, r.away_team))
        m = idx.get(k)
        ld.append(m.lineup_diff if m is not None else np.nan)
        gd.append(m.gk_diff if m is not None else np.nan)
        dl.append(getattr(m, 'lineup_delta', np.nan) if m is not None else np.nan)
    df['lineup_diff'] = ld
    df['gk_diff'] = gd
    df['lineup_delta'] = dl
    cob_l = float(df['lineup_diff'].notna().mean())
    cob_g = float(df['gk_diff'].notna().mean())
    logger.info(f"[{clave}] cobertura: alineación {100*cob_l:.1f} % · "
                f"portero {100*cob_g:.1f} % de {len(df)} partidos")
    return df, cob_l, cob_g


def calibrar(lam_h, lam_a, gh, ga, señales, mallas):
    """
    Coeficientes que minimizan la desvianza de Poisson conjunta en el TRAIN.

    `señales` es una lista de vectores (lineup_diff, gk_diff, lineup_delta…) y
    `mallas` la rejilla de cada uno. El ajuste es siempre antisimétrico: lo que
    suma al local resta al visitante.
    """
    señales = [np.nan_to_num(s, nan=0.0) for s in señales]
    coef = [0.0] * len(señales)

    def _dev(c):
        eta = np.clip(sum(x * s for x, s in zip(c, señales)), -0.30, 0.30)
        return (deviance_poisson(gh, lam_h * np.exp(eta))
                + deviance_poisson(ga, lam_a * np.exp(-eta)))

    # Descenso por coordenadas: la desvianza es suave y convexa en cada
    # coordenada, así que tres pasadas bastan y evitan el producto cartesiano
    # (31×21×31 = 20.181 evaluaciones por pliegue, que no terminaba).
    mejor_d = _dev(coef)
    for _ in range(3):
        for i, malla in enumerate(mallas):
            if len(malla) == 1:
                continue
            for v in malla:
                cand = list(coef)
                cand[i] = float(v)
                d = _dev(cand)
                if d < mejor_d - 1e-9:
                    mejor_d, coef = d, cand
    return coef


def evaluar(clave: str, liga_espn: str) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import accuracy_score, log_loss
    import feature_engineering as fe
    from _v70_wf_modelos import construir_ds

    df, cob_l, cob_g = emparejar(clave, liga_espn)
    pk = construir_ds(clave)
    X_df, topo = pk['X_df'], pk['topo']

    # alinear las columnas de alineación con las filas del dataset supervisado
    ds = fe.construir_dataset_supervisado(df)
    ids = [m[3] for m in ds['meta']]
    mid = df.set_index('MATCH_ID')
    ld = mid['lineup_diff'].reindex(ids).values.astype(float)
    gd = mid['gk_diff'].reindex(ids).values.astype(float)
    dl = mid['lineup_delta'].reindex(ids).values.astype(float)
    goles = ds['goles']
    if len(ld) != len(X_df):
        return {'clave': clave, 'estado': 'desalineado',
                'n_ds': len(X_df), 'n_ld': len(ld)}

    n = len(X_df)
    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, N_PLIEGUES + 1).astype(int)
    ramas = ['base', 'lineup', 'gk', 'delta', 'todo']
    lam_acum = {k: [] for k in ramas}
    g_oos, coefs = [], []

    for f in range(N_PLIEGUES):
        a, b = cortes[f], cortes[f + 1]
        tr, te = slice(0, a), slice(a, b)
        Xtr_n, Xte_n, _ = fe.normalizar_features(X_df.iloc[tr], X_df.iloc[te])
        Xtr = np.hstack([Xtr_n, topo[tr]])
        Xte = np.hstack([Xte_n, topo[te]])

        def _reg(obj):
            return HistGradientBoostingRegressor(
                loss='poisson', max_iter=300, learning_rate=0.06, max_depth=6,
                random_state=42).fit(Xtr, obj)
        rl = _reg(goles[tr][:, 0])
        rv = _reg(goles[tr][:, 1])
        lh_tr = np.clip(rl.predict(Xtr), 0.2, 3.8)
        la_tr = np.clip(rv.predict(Xtr), 0.2, 3.8)
        lh = np.clip(rl.predict(Xte), 0.2, 3.8)
        la = np.clip(rv.predict(Xte), 0.2, 3.8)

        # calibración SOLO con train
        gh_tr, ga_tr = goles[tr][:, 0], goles[tr][:, 1]
        sen_tr = [ld[tr], gd[tr], dl[tr]]
        c_lin = calibrar(lh_tr, la_tr, gh_tr, ga_tr, sen_tr,
                         [MALLA_BETA, CERO, CERO])
        c_gk = calibrar(lh_tr, la_tr, gh_tr, ga_tr, sen_tr,
                        [CERO, MALLA_GAMMA, CERO])
        c_del = calibrar(lh_tr, la_tr, gh_tr, ga_tr, sen_tr,
                         [CERO, CERO, MALLA_DELTA])
        c_all = calibrar(lh_tr, la_tr, gh_tr, ga_tr, sen_tr,
                         [MALLA_BETA, MALLA_GAMMA, MALLA_DELTA])
        coefs.append({'pliegue': f + 1, 'beta': c_lin[0], 'gamma': c_gk[1],
                      'delta': c_del[2], 'todo': c_all})

        sen_te = [np.nan_to_num(ld[te], nan=0.0),
                  np.nan_to_num(gd[te], nan=0.0),
                  np.nan_to_num(dl[te], nan=0.0)]

        def _aj(coef):
            eta = np.clip(sum(c * s for c, s in zip(coef, sen_te)), -0.30, 0.30)
            return lh * np.exp(eta), la * np.exp(-eta)

        lam_acum['base'].append((lh, la))
        lam_acum['lineup'].append(_aj(c_lin))
        lam_acum['gk'].append(_aj(c_gk))
        lam_acum['delta'].append(_aj(c_del))
        lam_acum['todo'].append(_aj(c_all))
        g_oos.append(goles[te])
        logger.info(f"  pliegue {f+1}: train {a} test {b-a} · "
                    f"β={c_lin[0]:+.3f} γ={c_gk[1]:+.3f} δ={c_del[2]:+.3f} "
                    f"· todo={c_all}")

    G = np.vstack(g_oos)
    yv = np.where(G[:, 0] > G[:, 1], 0, np.where(G[:, 0] == G[:, 1], 1, 2))
    res = {'clave': clave, 'liga_espn': liga_espn, 'estado': 'ok', 'n': int(n),
           'n_oos': int(len(yv)), 'cobertura_alineacion': round(cob_l, 4),
           'cobertura_portero': round(cob_g, 4), 'coeficientes': coefs,
           'ramas': {}}
    for k in ramas:
        lh = np.concatenate([x[0] for x in lam_acum[k]])
        la = np.concatenate([x[1] for x in lam_acum[k]])
        p = probs_1x2(lh, la)
        p = p / p.sum(axis=1, keepdims=True)
        res['ramas'][k] = {
            'deviance': round((deviance_poisson(G[:, 0], lh)
                               + deviance_poisson(G[:, 1], la)) / len(G), 5),
            'acc': round(float(accuracy_score(yv, p.argmax(axis=1))), 4),
            'll': round(float(log_loss(yv, p, labels=[0, 1, 2])), 4)}
    ref = res['ramas']['base']
    for k, v in res['ramas'].items():
        v['d_dev'] = round(v['deviance'] - ref['deviance'], 5)
        v['d_acc'] = round(v['acc'] - ref['acc'], 4)
        v['d_ll'] = round(v['ll'] - ref['ll'], 4)
        v['regla_oro'] = bool((v['d_acc'] >= 0.003 and v['d_ll'] <= 0.01)
                              or (v['d_acc'] > 0 and v['d_ll'] < 0))
    return res


def main(solo: Optional[str] = None):
    previos = {}
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding='utf-8') as f:
            previos = {r['clave']: r for r in json.load(f)}
    for clave, espn in LIGAS.items():
        if solo and clave != solo:
            continue
        logger.info(f"== {clave} ({espn})")
        try:
            r = evaluar(clave, espn)
        except Exception as e:
            logger.error(f"  {clave}: {type(e).__name__}: {e}")
            r = {'clave': clave, 'estado': 'error',
                 'detalle': f'{type(e).__name__}: {e}'}
        previos[clave] = r
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(list(previos.values()), f, ensure_ascii=False, indent=1)
        if r.get('estado') == 'ok':
            for k, v in r['ramas'].items():
                logger.info(f"  {k:8s} dev={v['deviance']:.4f} ({v['d_dev']:+.4f}) "
                            f"acc={v['acc']:.4f} ({v['d_acc']:+.4f}) "
                            f"ll={v['ll']:.4f} ({v['d_ll']:+.4f}) "
                            f"{'ADOPTA' if v['regla_oro'] else ''}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo', default=None)
    main(ap.parse_args().solo)
