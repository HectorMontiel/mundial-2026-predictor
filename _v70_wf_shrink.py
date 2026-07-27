#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora G (hallazgo no previsto en el spec) — encogimiento de λ.

De dónde sale
-------------
El control del diagnóstico de alineaciones (`_v70_diag_lineup.py`) medía la
correlación entre (λ_local − λ_visitante) y el residuo de Pearson del margen,
esperando ~0. Salió **−0,193 en MLS (p<0,001) y −0,238 en Liga MX (p<0,001)**:
un efecto diez veces mayor que el de las alineaciones y con el mismo signo en
las dos ligas. Traducido: cuando el modelo predice un margen grande, el margen
real tiende a quedarse corto. Los regresores Poisson **separan demasiado** las
dos λ.

Es la regresión a la media de toda la vida, y tiene arreglo directo: encoger la
diferencia de λ hacia su media conservando el total.

    m     = (λ_h + λ_a) / 2
    d     = (λ_h − λ_a) / 2
    λ_h'  = m + s·d
    λ_a'  = m − s·d

con s ∈ (0, 1] calibrado por liga en walk-forward minimizando la desvianza de
Poisson **sólo con datos de train**. s = 1 es no tocar nada, así que la
parametrización contiene al modelo actual y no puede empeorarlo en train.

Esto no toca el 1X2 del clasificador: mejora las λ, que son las que gobiernan la
matriz de marcadores, el marcador exacto y los mercados de goles.

Salida: `_v70_wf_shrink.json`
"""
import json
import logging
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_wf_shrink.json'
ARCHIVO_COEF = 'lambda_shrink.json'
N_PLIEGUES = 5
FRAC_TEST = 0.40
MALLA_S = np.round(np.arange(0.40, 1.0001, 0.02), 4)

LIGAS = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'liga_mx',
         'mls', 'eredivisie', 'brasil', 'argentina', 'eng_championship',
         'ned_eerste', 'bra_serie_b', 'gre_super_league', 'crc_fpd']


def deviance_poisson(y, lam):
    lam = np.clip(lam, 1e-6, None)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(y > 0, y * np.log(y / lam), 0.0)
    return float(2.0 * np.sum(t - (y - lam)))


def encoger(lh, la, s):
    m = (lh + la) / 2.0
    d = (lh - la) / 2.0
    return np.clip(m + s * d, 0.15, 5.0), np.clip(m - s * d, 0.15, 5.0)


def probs_1x2(lam_h, lam_a, n_max=11):
    from scipy.stats import poisson
    kk = np.arange(n_max)
    out = np.zeros((len(lam_h), 3))
    for i in range(len(lam_h)):
        M = np.outer(poisson.pmf(kk, lam_h[i]), poisson.pmf(kk, lam_a[i]))
        M /= M.sum()
        # M[i,j]=P(local=i, visitante=j): el local gana en el triángulo inferior
        out[i] = [np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()]
    return np.clip(out, 1e-6, 1)


def evaluar(clave: str) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import accuracy_score, log_loss
    import feature_engineering as fe
    from _v70_wf_modelos import construir_ds

    pk = construir_ds(clave)
    X_df, topo = pk['X_df'].copy(), pk['topo']
    X_df = X_df.fillna(0.0)
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    goles = ds['goles']
    n = len(X_df)
    if n != len(goles) or n < 300:
        return {'clave': clave, 'estado': 'desalineado', 'n': n,
                'n_goles': len(goles)}

    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, N_PLIEGUES + 1).astype(int)
    base_l, base_a, enc_l, enc_a, g_oos, eses = [], [], [], [], [], []

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
        rl, rv = _reg(goles[tr][:, 0]), _reg(goles[tr][:, 1])

        # s calibrado con las predicciones sobre el ÚLTIMO 25 % del train,
        # ajustadas por un modelo entrenado sólo con el 75 % anterior (si se
        # calibrara con las predicciones in-sample, s saldría 1 por construcción)
        c75 = int(a * 0.75)
        Xa_n, Xb_n, _ = fe.normalizar_features(X_df.iloc[:c75], X_df.iloc[c75:a])
        Xa = np.hstack([Xa_n, topo[:c75]])
        Xb = np.hstack([Xb_n, topo[c75:a]])

        def _reg2(obj):
            return HistGradientBoostingRegressor(
                loss='poisson', max_iter=300, learning_rate=0.06, max_depth=6,
                random_state=42).fit(Xa, obj)
        lh_i = np.clip(_reg2(goles[:c75, 0]).predict(Xb), 0.2, 3.8)
        la_i = np.clip(_reg2(goles[:c75, 1]).predict(Xb), 0.2, 3.8)
        gh_i, ga_i = goles[c75:a, 0], goles[c75:a, 1]
        mejor_s, mejor_d = 1.0, np.inf
        for s in MALLA_S:
            eh, ea = encoger(lh_i, la_i, s)
            d = deviance_poisson(gh_i, eh) + deviance_poisson(ga_i, ea)
            if d < mejor_d:
                mejor_d, mejor_s = d, float(s)
        eses.append(mejor_s)

        lh = np.clip(rl.predict(Xte), 0.2, 3.8)
        la = np.clip(rv.predict(Xte), 0.2, 3.8)
        eh, ea = encoger(lh, la, mejor_s)
        base_l.append(lh); base_a.append(la)
        enc_l.append(eh); enc_a.append(ea)
        g_oos.append(goles[te])

    G = np.vstack(g_oos)
    yv = np.where(G[:, 0] > G[:, 1], 0, np.where(G[:, 0] == G[:, 1], 1, 2))
    res = {'clave': clave, 'estado': 'ok', 'n': int(n), 'n_oos': int(len(yv)),
           's_por_pliegue': eses, 's_mediano': float(np.median(eses)),
           'ramas': {}}
    for nombre, (L, A) in (('base', (base_l, base_a)), ('encogido', (enc_l, enc_a))):
        lh, la = np.concatenate(L), np.concatenate(A)
        p = probs_1x2(lh, la)
        p = p / p.sum(axis=1, keepdims=True)
        res['ramas'][nombre] = {
            'deviance': round((deviance_poisson(G[:, 0], lh)
                               + deviance_poisson(G[:, 1], la)) / len(G), 5),
            'acc': round(float(accuracy_score(yv, p.argmax(axis=1))), 4),
            'll': round(float(log_loss(yv, p, labels=[0, 1, 2])), 4)}
    b, e = res['ramas']['base'], res['ramas']['encogido']
    res['d_dev'] = round(e['deviance'] - b['deviance'], 5)
    res['d_acc'] = round(e['acc'] - b['acc'], 4)
    res['d_ll'] = round(e['ll'] - b['ll'], 4)
    # Criterio de adopción para λ.
    #
    # La regla de oro del proyecto (§2.1) está escrita para la PRECISIÓN del
    # 1X2, y el 1X2 de producción no sale de λ sino del clasificador: λ gobierna
    # la matriz de marcadores, el marcador exacto y los mercados de goles. Lo
    # que hay que exigirle a λ, por tanto, es que describa mejor los goles. Eso
    # son dos cosas y se piden las dos: menos desvianza de Poisson (el ajuste
    # directo) y no empeorar el log-loss del 1X2 derivado (que no se degrade
    # nada aguas abajo). La precisión se reporta pero no decide.
    res['regla_oro'] = bool(res['d_dev'] < 0 and res['d_ll'] <= 0.0)
    return res


def main():
    previos = {}
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding='utf-8') as f:
            previos = {r['clave']: r for r in json.load(f)}
    for i, c in enumerate(LIGAS, 1):
        logger.info(f"[{i}/{len(LIGAS)}] {c}")
        try:
            r = evaluar(c)
        except Exception as e:
            logger.error(f"  {c}: {type(e).__name__}: {e}")
            r = {'clave': c, 'estado': 'error', 'detalle': f'{type(e).__name__}: {e}'}
        previos[c] = r
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(list(previos.values()), f, ensure_ascii=False, indent=1)
        if r.get('estado') == 'ok':
            logger.info(f"  s={r['s_mediano']:.2f} · dev {r['d_dev']:+.5f} · "
                        f"acc {r['d_acc']:+.4f} · ll {r['d_ll']:+.4f} "
                        f"{'ADOPTA' if r['regla_oro'] else ''}")

    # artefacto para producción: sólo las ligas que superan la regla de oro
    ok = {r['clave']: round(r['s_mediano'], 3)
          for r in previos.values()
          if r.get('estado') == 'ok' and r.get('regla_oro')}
    with open(ARCHIVO_COEF, 'w', encoding='utf-8') as f:
        json.dump({'generado': str(pd.Timestamp.today().date()),
                   'nota': 'factor de encogimiento de la diferencia de lambdas; '
                           'una liga ausente no recibe ajuste (s=1)',
                   'ligas': ok}, f, ensure_ascii=False, indent=1)
    logger.info(f"== {len(ok)} ligas adoptan encogimiento → {ARCHIVO_COEF}")


if __name__ == '__main__':
    main()
