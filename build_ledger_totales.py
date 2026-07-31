#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Ledger fuera de muestra para TOTALES y BTTS.

Por qué hace falta
------------------
`calibracion_confianza` mide el acierto real por banda de probabilidad, pero
sólo sobre 1X2 y ganador, porque es lo único que hay en `pick_ledger_total.csv`.
Por eso la pestaña «Máxima Confianza» dice «no medido» en los mercados de
hándicap y totales — que es honesto (v84 quitó el número prestado de otro
mercado) pero deja al usuario sin la corrección justo donde más picks hay.

Este script construye el sustrato que falta: **P(over) y P(BTTS) fuera de
muestra**, partido a partido, para poder medir esas bandas de verdad.

Qué NO se reentrena
-------------------
No se tocan los clasificadores 1X2 (XGB/RF/LGBM calibrados). Los mercados de
goles no salen de ahí: salen de los dos regresores de Poisson (λ local y λ
visitante). Reentrenar sólo esos por pliegue es órdenes de magnitud más barato
y produce exactamente la cantidad que hay que calibrar.

Paridad con producción
----------------------
Se replica la cadena de `ClubEngine.predecir` para los goles:

    λ = regresor.predict(X)  ->  clip(0.2, 3.8)
    λ_h, λ_a = distributions.encoger_lambdas(λ_h, λ_a, s=factor_shrink(liga))
    P(over L)   = 1 - Poisson.cdf(floor(L), λ_h + λ_a)
    P(BTTS)     = (1 - e^-λ_h)(1 - e^-λ_a)

Sin fuga: mismo esquema de pliegues cronológicos que `build_pick_ledger`; el
escalado se ajusta con el train de cada pliegue.

Salida: `pick_ledger_totales.csv`
"""
import logging
import sys
import warnings

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
logger = logging.getLogger('ledger-totales')

SALIDA = 'pick_ledger_totales.csv'
INICIO_TRAIN = 0.50
N_FOLDS = 5
MIN_PARTIDOS = 400
MIN_TEST_POR_FOLD = 40
LINEAS = (1.5, 2.5, 3.5)


def _regresor():
    """El mismo tipo de regresor que usa producción para los goles."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.06,
                                         max_depth=6, random_state=42)


def ledger_de_liga(clave: str) -> pd.DataFrame:
    import os

    import distributions as dist
    import feature_engineering as fe
    import league_engine as le
    from scipy.stats import poisson
    from train_tda_model import calcular_features_topologicas

    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        return pd.DataFrame()
    df = pd.read_csv(ruta, low_memory=False)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = (df.dropna(subset=['date'])
            .sort_values(['date', 'MATCH_ID'], kind='mergesort')
            .reset_index(drop=True))

    ds = fe.construir_dataset_supervisado(df)
    X_df, fechas = ds['X_df'], ds['fechas']
    if len(X_df) < MIN_PARTIDOS:
        return pd.DataFrame()

    topo = calcular_features_topologicas(ds)
    fechas = pd.Series(pd.to_datetime(fechas)).reset_index(drop=True)
    corte_imt = fechas.quantile(INICIO_TRAIN)
    X_df, cols_extra, _ = le.preparar_features_extra(clave, df, ds, X_df, corte_imt)
    X_df = X_df.reset_index(drop=True)
    ids = np.array([m[3] for m in ds['meta']])
    goles = ds['goles']

    n = len(X_df)
    orden = np.argsort(fechas.values, kind='mergesort')
    bordes = np.linspace(int(n * INICIO_TRAIN), n, N_FOLDS + 1).astype(int)
    s_shrink = dist.factor_shrink(clave)

    filas = []
    for k in range(N_FOLDS):
        ini, fin = bordes[k], bordes[k + 1]
        if fin - ini < MIN_TEST_POR_FOLD:
            continue
        idx_tr, idx_te = orden[:ini], orden[ini:fin]
        f_corte = fechas.iloc[idx_te].min()
        idx_tr = idx_tr[fechas.iloc[idx_tr].values < f_corte]
        if len(idx_tr) < 200:
            continue

        Xk = X_df.copy()
        for c in (cols_extra or []):
            if c in le.COLS_CUOTAS:
                m = float(pd.to_numeric(Xk.iloc[idx_tr][c], errors='coerce').mean())
                Xk[c] = Xk[c].fillna(m if np.isfinite(m) else 0.0)
            else:
                Xk[c] = Xk[c].fillna(0.0)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            X_tr_n, X_te_n, _ = fe.normalizar_features(Xk.iloc[idx_tr],
                                                       Xk.iloc[idx_te])
            X_tr = np.hstack([X_tr_n, topo[idx_tr]])
            X_te = np.hstack([X_te_n, topo[idx_te]])
            rl, rv = _regresor(), _regresor()
            rl.fit(X_tr, goles[idx_tr, 0])
            rv.fit(X_tr, goles[idx_tr, 1])
            lam_h = np.clip(rl.predict(X_te), 0.2, 3.8)
            lam_a = np.clip(rv.predict(X_te), 0.2, 3.8)

        for j, ig in enumerate(idx_te):
            lh, la = dist.encoger_lambdas(float(lam_h[j]), float(lam_a[j]),
                                          s=s_shrink)
            tot = lh + la
            fila = {'liga': clave, 'match_id': ids[ig],
                    'fecha': fechas.iloc[ig].strftime('%Y-%m-%d'),
                    'pliegue': k,
                    'lam_h': round(lh, 4), 'lam_a': round(la, 4),
                    'goles_local': int(goles[ig, 0]),
                    'goles_visit': int(goles[ig, 1]),
                    'goles_total': int(goles[ig, 0] + goles[ig, 1]),
                    'btts_real': int(goles[ig, 0] > 0 and goles[ig, 1] > 0),
                    'p_btts': round(float((1 - np.exp(-lh)) * (1 - np.exp(-la))), 5)}
            for L in LINEAS:
                fila[f'p_over_{L}'] = round(
                    float(1 - poisson.cdf(int(np.floor(L)), max(tot, 1e-9))), 5)
                fila[f'over_{L}_real'] = int(
                    (goles[ig, 0] + goles[ig, 1]) > L)
            filas.append(fila)

    return pd.DataFrame(filas)


def adjuntar_cuotas(led: pd.DataFrame) -> pd.DataFrame:
    """Trae cuota_over25/under25 de pick_ledger.csv, que ya las cruzó."""
    import os
    if not os.path.exists('pick_ledger.csv'):
        return led
    p = pd.read_csv('pick_ledger.csv',
                    usecols=['liga', 'match_id', 'cuota_over25', 'cuota_under25'])
    return led.merge(p, on=['liga', 'match_id'], how='left')


def construir() -> pd.DataFrame:
    import config
    claves = [c for c, cfg in config.LEAGUES.items() if cfg.get('disponible', True)]
    trozos = []
    for i, c in enumerate(claves, 1):
        try:
            t = ledger_de_liga(c)
        except Exception as ex:
            print(f'  {i:2d}/{len(claves)} {c:24s} ERROR '
                  f'{type(ex).__name__}: {str(ex)[:50]}')
            continue
        if len(t):
            trozos.append(t)
            print(f'  {i:2d}/{len(claves)} {c:24s} {len(t):6d} partidos')
        else:
            print(f'  {i:2d}/{len(claves)} {c:24s} sin muestra')
    if not trozos:
        return pd.DataFrame()
    out = pd.concat(trozos, ignore_index=True)
    out = adjuntar_cuotas(out)
    out.to_csv(SALIDA, index=False)
    return out


if __name__ == '__main__':
    print('construyendo ledger de totales y BTTS (walk-forward)...')
    d = construir()
    if d.empty:
        print('vacío')
        sys.exit(1)
    print(f'\n{len(d)} partidos -> {SALIDA}')
    print(f'con cuota over 2.5: {d["cuota_over25"].notna().sum()}')
    print('\ncordura (el modelo debe acertar más que la tasa base):')
    for L in LINEAS:
        real = d[f'over_{L}_real'].mean()
        pred = d[f'p_over_{L}'].mean()
        print(f'  over {L}: real {real:.3f} · predicho medio {pred:.3f} '
              f'· sesgo {pred - real:+.3f}')
    print(f'  BTTS   : real {d["btts_real"].mean():.3f} · '
          f'predicho medio {d["p_btts"].mean():.3f} · '
          f'sesgo {d["p_btts"].mean() - d["btts_real"].mean():+.3f}')
