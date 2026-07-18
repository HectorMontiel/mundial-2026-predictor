#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward A/B de las features MLS (v25, spec §1.3).

Variantes con ventanas idénticas de 6 meses (arnés v24):
  * base      — config adoptada de la MLS (cuotas de cierre).
  * geo       — base + ALT_SEDE_MLS + DIST_VIAJE_MLS + DIFF_HUSO.
  * geo_clima — geo + CLIMA_EXTREMO (tmax>30 °C y humedad>60 %, backfill
                Open-Meteo 2023+; sin dato → 0 neutro).

Regla de oro v16: ≥ +0.3 pp de precisión media sin empeorar el log-loss
medio > 0.01 (o mejora en ambos). Resultado → resultados_mls_v25.json.

Uso: python run_wf_mls_v25.py
"""

import json
import logging
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
import league_engine
import mls_features
from train_tda_model import construir_ensemble, calcular_features_topologicas

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_mls_v25.json'
MIN_PARTIDOS_VENTANA = 60
MIN_TRAIN = 250


def main() -> dict:
    df = pd.read_csv('historico_mls.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    y, fechas = ds['y'], ds['fechas']
    ids = [m[3] for m in ds['meta']]

    extras_df, _ = league_engine.features_extra_liga(df)
    extras_df = extras_df.join(mls_features.features_mls(df))
    ext = extras_df.reindex(ids).reset_index(drop=True)
    cols_todas = league_engine.COLS_CUOTAS + mls_features.COLS_MLS
    for c in cols_todas:
        X_df[c] = ext[c].values

    topo = calcular_features_topologicas(ds)
    cols_modelo = list(fe.FEATURES_MODELO)
    variantes = {
        'base': cols_modelo + league_engine.COLS_CUOTAS,
        'geo': cols_modelo + league_engine.COLS_CUOTAS + mls_features.COLS_MLS_GEO,
        'geo_clima': cols_modelo + league_engine.COLS_CUOTAS + mls_features.COLS_MLS,
    }

    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')
    res = {v: [] for v in variantes}
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values
        if m_va.sum() < MIN_PARTIDOS_VENTANA or m_tr.sum() < MIN_TRAIN:
            continue
        fila = {}
        for nombre, cols in variantes.items():
            Xv = X_df[cols].copy()
            for c in cols:
                if c in league_engine.COLS_CUOTAS:
                    Xv[c] = Xv[c].fillna(float(pd.to_numeric(
                        Xv.loc[m_tr, c], errors='coerce').mean()))
                else:
                    Xv[c] = Xv[c].fillna(0.0)
            X_tr_n, X_va_n, _ = fe.normalizar_features(Xv[m_tr], Xv[m_va])
            modelo = construir_ensemble()
            modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
            proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
            acc = float(accuracy_score(y[m_va], proba.argmax(axis=1)))
            ll = float(log_loss(y[m_va], proba, labels=[0, 1, 2]))
            res[nombre].append({'ventana': str(inicio.date()), 'n': int(m_va.sum()),
                                'acc': round(acc, 4), 'll': round(ll, 4)})
            fila[nombre] = f"{acc:.3f}/{ll:.3f}"
        logger.info(f"  [mls] {inicio.date()} n={m_va.sum()} :: "
                    + ' · '.join(f'{k} {v}' for k, v in fila.items()))

    def _media(v):
        return (round(float(np.mean([f['acc'] for f in res[v]])), 4),
                round(float(np.mean([f['ll'] for f in res[v]])), 4))

    acc_b, ll_b = _media('base')
    salida = {'ventanas': res,
              'media': {v: {'acc': _media(v)[0], 'll': _media(v)[1]} for v in res}}
    adoptar = None
    for v in ('geo', 'geo_clima'):
        acc_v, ll_v = _media(v)
        pasa = ((acc_v - acc_b >= 0.003 and ll_v - ll_b <= 0.01)
                or (acc_v > acc_b and ll_v < ll_b))
        salida['media'][v]['pasa_regla_de_oro'] = bool(pasa)
        if pasa and (adoptar is None or ll_v < salida['media'][adoptar]['ll']):
            adoptar = v
    salida['adoptar'] = adoptar
    logger.info(f"[mls] base {acc_b}/{ll_b} · geo {_media('geo')} · "
                f"geo_clima {_media('geo_clima')} → ADOPTAR: {adoptar or 'ninguna'}")
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    return salida


if __name__ == '__main__':
    r = main()
    print(json.dumps(r['media'], indent=2))
