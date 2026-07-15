#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward automatizado para TODAS las ligas (v22, spec §3.3).

Para cada liga reproduce la configuración ADOPTADA (features extra, beta
calibration) sobre su historico_{clave}.csv local, y valida en ventanas de
6 meses que ruedan sobre el último 40 % del dataset con entrenamiento
expansivo (escalador e imputaciones reajustados POR VENTANA — sin fuga).

Por ventana: precisión y log-loss del modelo, precisión del FAVORITO del
mercado con cuotas de cierre (donde existen) y nº de partidos. Resultado en
`wf_panel_v22.json` (lo consume el panel «📈 Rendimiento» de la UI) y
resumen en modelos/{clave}/metadata.json['walk_forward'].

Uso:  python run_wf_panel_v22.py [liga ...]     # sin args: todas
"""

import json
import logging
import os
import sys
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
import league_engine
from config import LEAGUES
from train_tda_model import construir_ensemble, calcular_features_topologicas

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO_PANEL = 'wf_panel_v22.json'
MIN_PARTIDOS_VENTANA = 60


def _dataset_liga(clave: str):
    """Dataset con la MISMA configuración adoptada que entrenar_liga."""
    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        raise FileNotFoundError(ruta)
    df = pd.read_csv(ruta, parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()

    cols_extra = league_engine.columnas_extra(clave)
    if cols_extra:
        extras_df, _ = league_engine.features_extra_liga(df)
        if 'mx' in LEAGUES[clave].get('features_extra', []):
            extras_df = extras_df.join(league_engine.features_mx(df))
        ids = [m[3] for m in ds['meta']]
        ext = extras_df.reindex(ids).reset_index(drop=True)
        for c in cols_extra:
            X_df[c] = ext[c].values

    topo = calcular_features_topologicas(ds)
    odds = df.set_index('MATCH_ID')[['odd_home', 'odd_draw', 'odd_away']]
    ids = [m[3] for m in ds['meta']]
    return X_df, ds['y'], ds['fechas'], topo, odds.reindex(ids), cols_extra


def _modelo_liga(clave: str):
    if LEAGUES[clave].get('calibracion') == 'beta':
        return league_engine.ModeloBetaCalibrado()
    return construir_ensemble()


def walk_forward_liga(clave: str) -> dict:
    X_df, y, fechas, topo, odds, cols_extra = _dataset_liga(clave)
    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')
    filas = []
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values
        if m_va.sum() < MIN_PARTIDOS_VENTANA or m_tr.sum() < 250:
            continue
        X = X_df.copy()
        # imputación por ventana con medias SOLO del train (sin fuga)
        for c in cols_extra:
            if c in league_engine.COLS_CUOTAS:
                X[c] = X[c].fillna(float(pd.to_numeric(
                    X.loc[m_tr, c], errors='coerce').mean()))
            else:
                X[c] = X[c].fillna(0.0)
        X_tr_n, X_va_n, _ = fe.normalizar_features(X[m_tr], X[m_va])
        modelo = _modelo_liga(clave)
        modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
        acc = float(accuracy_score(y[m_va], proba.argmax(axis=1)))
        ll = float(log_loss(y[m_va], proba, labels=[0, 1, 2]))

        # favorito del mercado en la MISMA ventana (cuotas de cierre)
        o_va = odds[m_va].dropna()
        acc_mercado = None
        if len(o_va) >= 30:
            y_va = pd.Series(y[m_va], index=odds.index[m_va])
            pick = o_va.values.argmin(axis=1)
            acc_mercado = float((pick == y_va.loc[o_va.index].values).mean())

        filas.append({'ventana': f"{inicio.date()} → {fin.date()}",
                      'n': int(m_va.sum()),
                      'precision': round(acc, 4), 'log_loss': round(ll, 4),
                      'precision_mercado': round(acc_mercado, 4) if acc_mercado else None})
        logger.info(f"  [{clave}] {inicio.date()}: n={m_va.sum()} acc={acc:.3f} "
                    f"ll={ll:.3f} mercado={acc_mercado if acc_mercado else 'N/D'}")

    if not filas:
        return {}
    resumen = {
        'ventanas': filas,
        'precision_media': round(float(np.mean([f['precision'] for f in filas])), 4),
        'log_loss_medio': round(float(np.mean([f['log_loss'] for f in filas])), 4),
        'precision_mercado_media': (round(float(np.mean(
            [f['precision_mercado'] for f in filas if f['precision_mercado']])), 4)
            if any(f['precision_mercado'] for f in filas) else None),
    }
    # persistir también en el metadata de la liga
    ruta_meta = os.path.join('modelos', clave, 'metadata.json')
    try:
        with open(ruta_meta, encoding='utf-8') as f:
            meta = json.load(f)
        meta['walk_forward'] = resumen
        with open(ruta_meta, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[{clave}] no se pudo actualizar metadata: {e}")
    return resumen


if __name__ == '__main__':
    objetivos = sys.argv[1:] or [c for c, cfg in LEAGUES.items() if cfg.get('disponible')]
    panel = {}
    if os.path.exists(ARCHIVO_PANEL):
        with open(ARCHIVO_PANEL, encoding='utf-8') as f:
            panel = json.load(f)
    for clave in objetivos:
        logger.info(f"=== walk-forward {clave} ===")
        try:
            r = walk_forward_liga(clave)
            if r:
                panel[clave] = r
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
        with open(ARCHIVO_PANEL, 'w', encoding='utf-8') as f:
            json.dump(panel, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: {'acc': v['precision_media'], 'll': v['log_loss_medio'],
                          'mercado': v.get('precision_mercado_media'),
                          'ventanas': len(v['ventanas'])}
                      for k, v in panel.items()}, indent=2))
