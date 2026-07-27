#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora C — ¿aporta P(BTTS) como columna del clasificador 1X2?

Protocolo
---------
Mismo walk-forward expandente de 5 pliegues que la Mejora D, comparando el
vector actual contra el vector + `P_BTTS`, con la probabilidad calculada por
`supervivencia_btts.serie_btts_sin_fuga` (cloglog reajustado sólo con partidos
anteriores). El resto —normalización, topológicas, modelo— es idéntico, así que
la única diferencia entre las dos ramas es la columna.

La P(BTTS) que falta (los primeros partidos de cada liga, antes de que haya
modelo) se imputa con la media del TRAIN, exactamente como hace `entrenar_liga`
con las cuotas ausentes.

Salida: `_v70_wf_btts.json`
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

SALIDA = '_v70_wf_btts.json'
N_PLIEGUES = 5
FRAC_TEST = 0.40
LIGAS = ['premier', 'laliga', 'serie_a', 'liga_mx', 'mls', 'bundesliga', 'ligue_1']


def evaluar(clave: str) -> dict:
    from sklearn.metrics import accuracy_score, log_loss
    import feature_engineering as fe
    import supervivencia_btts as sb
    from _v70_wf_modelos import construir_ds, _probs3, _fit_ensemble

    pk = construir_ds(clave)
    X_df, y, topo = pk['X_df'].copy(), pk['y'], pk['topo']

    # P(BTTS) alineada por MATCH_ID con las filas del dataset supervisado
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    p_btts = sb.serie_btts_sin_fuga(df)
    d = df.sort_values(['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)
    mapa = dict(zip(d['MATCH_ID'], p_btts))

    import feature_engineering as _fe
    ds = _fe.construir_dataset_supervisado(df)
    ids = [m[3] for m in ds['meta']]
    serie = np.array([mapa.get(i, np.nan) for i in ids], dtype=float)
    if len(serie) != len(X_df):
        return {'clave': clave, 'estado': 'desalineado',
                'n_ds': len(X_df), 'n_serie': len(serie)}
    cobertura = float(np.isfinite(serie).mean())
    logger.info(f"[{clave}] P_BTTS disponible en {100*cobertura:.1f} % de las filas")

    n = len(X_df)
    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, N_PLIEGUES + 1).astype(int)
    acum = {'sin_btts': [], 'con_btts': []}
    y_oos = []

    for f in range(N_PLIEGUES):
        a, b = cortes[f], cortes[f + 1]
        if b - a < 10:
            continue
        tr, te = slice(0, a), slice(a, b)
        ytr = y[tr]

        Xtr_n, Xte_n, _ = fe.normalizar_features(X_df.iloc[tr], X_df.iloc[te])
        Xtr = np.hstack([Xtr_n, topo[tr]])
        Xte = np.hstack([Xte_n, topo[te]])
        acum['sin_btts'].append(_probs3(_fit_ensemble(Xtr, ytr), Xte))

        # rama CON la columna: imputación con la media del TRAIN
        col = serie.copy()
        media = float(np.nanmean(col[tr])) if np.isfinite(col[tr]).any() else 0.5
        col = np.where(np.isfinite(col), col, media)
        X2 = X_df.copy()
        X2['P_BTTS'] = col
        X2tr_n, X2te_n, _ = fe.normalizar_features(X2.iloc[tr], X2.iloc[te])
        X2tr = np.hstack([X2tr_n, topo[tr]])
        X2te = np.hstack([X2te_n, topo[te]])
        acum['con_btts'].append(_probs3(_fit_ensemble(X2tr, ytr), X2te))
        y_oos.append(y[te])

    yv = np.concatenate(y_oos)
    res = {'clave': clave, 'estado': 'ok', 'n': int(n), 'n_oos': int(len(yv)),
           'cobertura_btts': round(cobertura, 4), 'modelos': {}}
    for k in ('sin_btts', 'con_btts'):
        p = np.concatenate(acum[k])
        res['modelos'][k] = {
            'acc': round(float(accuracy_score(yv, p.argmax(axis=1))), 4),
            'll': round(float(log_loss(yv, p, labels=[0, 1, 2])), 4)}
    s, c = res['modelos']['sin_btts'], res['modelos']['con_btts']
    res['d_acc'] = round(c['acc'] - s['acc'], 4)
    res['d_ll'] = round(c['ll'] - s['ll'], 4)
    # regla de oro del proyecto (§2.1)
    res['regla_oro'] = bool((res['d_acc'] >= 0.003 and res['d_ll'] <= 0.01)
                            or (res['d_acc'] > 0 and res['d_ll'] < 0))
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
            logger.info(f"  sin {r['modelos']['sin_btts']['acc']:.4f}/"
                        f"{r['modelos']['sin_btts']['ll']:.4f} → "
                        f"con {r['modelos']['con_btts']['acc']:.4f}/"
                        f"{r['modelos']['con_btts']['ll']:.4f} · "
                        f"Δacc {r['d_acc']:+.4f} Δll {r['d_ll']:+.4f} · "
                        f"{'ADOPTA' if r['regla_oro'] else 'no adopta'}")


if __name__ == '__main__':
    main()
