#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entrenamiento v4: ensemble calibrado + topología por equipo + regresores de goles.

Modelos entrenados (todos con validación temporal estricta):
  1. Clasificador 1X2: ensemble de XGBoost + Random Forest + LightGBM
     (promediado suave de probabilidades) con calibración ISOTÓNICA.
  2. Regresores de goles esperados (λ local y λ visitante):
     HistGradientBoostingRegressor con pérdida de Poisson. Alimentan la
     simulación Monte Carlo de marcadores, hándicaps, over/under y BTTS.

Features:
  - 15 features tácticas pre-partido normalizadas MinMax (sin fuga).
  - 6 entropías de persistencia (Vietoris-Rips H0/H1):
      * nube combinada del par (6 puntos)
      * nube del local: sus últimos 10 partidos (10 puntos x 6 dims)
      * nube del visitante: ídem
  - Si la dimensionalidad de una nube supera 50, se reduce con PCA a 8.

Aumento de datos: +1000 partidos del generador sintético correlacionado se
añaden SOLO al conjunto de entrenamiento (nunca a la validación real).

Objetivos exigidos (metadata.json):
  - Regla de oro de despliegue: precisión ≥ 55 %.
  - Objetivo estricto:         precisión ≥ 62 % y log-loss ≤ 0.85.

Uso:
    python train_tda_model.py [--corte 2024-01-01] [--sin-aumento]
"""

import argparse
import datetime
import json
import logging
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier, VotingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import accuracy_score, log_loss

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

from gtda.homology import VietorisRipsPersistence
from gtda.diagrams import PersistenceEntropy

import feature_engineering as fe
from config import HISTORICO_FILE

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DIRECTORIO_MODELOS = 'modelos'
UMBRAL_DESPLIEGUE = 0.55       # Regla de oro mínima
OBJETIVO_PRECISION = 0.62      # Objetivo estricto de la especificación
OBJETIVO_LOGLOSS = 0.85
MAX_DIMENSIONES_NUBE = 50
COMPONENTES_PCA = 8
N_PARTIDOS_AUMENTO = 1000


def entropias_de_nubes(nubes: np.ndarray, etiqueta: str) -> np.ndarray:
    """Diagramas Vietoris-Rips H0/H1 por lote -> entropías (n, 2)."""
    n, n_puntos, n_dims = nubes.shape
    if n_dims > MAX_DIMENSIONES_NUBE:
        logger.info(f"[{etiqueta}] dimensionalidad {n_dims} > {MAX_DIMENSIONES_NUBE}: PCA -> {COMPONENTES_PCA}.")
        planos = nubes.reshape(-1, n_dims)
        pca = PCA(n_components=COMPONENTES_PCA, random_state=42)
        nubes = pca.fit_transform(planos).reshape(n, n_puntos, COMPONENTES_PCA)
    vr = VietorisRipsPersistence(homology_dimensions=[0, 1], n_jobs=-1)
    diagramas = vr.fit_transform(nubes)
    return PersistenceEntropy(nan_fill_value=0.0).fit_transform(diagramas)


def calcular_features_topologicas(ds: dict) -> np.ndarray:
    """Las 6 entropías por partido: par combinado + local(10) + visitante(10)."""
    ent_par = entropias_de_nubes(ds['nubes_par'], 'par')
    ent_loc = entropias_de_nubes(ds['nubes_local'], 'local-10')
    ent_vis = entropias_de_nubes(ds['nubes_visit'], 'visitante-10')
    return np.hstack([ent_par, ent_loc, ent_vis])


def generar_aumento_sintetico(n_partidos: int) -> dict:
    """
    +N partidos del generador correlacionado (preserva distribuciones reales)
    procesados con el MISMO pipeline de features. Solo para entrenamiento.
    """
    from correlated_synthetic_generator import CorrelatedSyntheticGenerator
    gen = CorrelatedSyntheticGenerator(seed=7)
    # ~1 partido/día por cada 2 equipos muestreados cada 3 días (6 equipos/día)
    dias = int(n_partidos)  # generate_initial_history produce ~1 partido/día
    matches, _ = gen.generate_initial_history(days_back=dias)
    matches = matches.tail(n_partidos + 200)
    ds = fe.construir_dataset_supervisado(matches)
    logger.info(f"Aumento sintético: {len(ds['X_df'])} partidos correlacionados para entrenamiento.")
    return ds


def fuente_de_datos() -> str:
    try:
        with open('fuente_datos.json', 'r', encoding='utf-8') as f:
            return json.load(f).get('source', 'synthetic')
    except Exception:
        return 'synthetic'


def construir_ensemble() -> CalibratedClassifierCV:
    """
    XGBoost + Random Forest + LightGBM (soft voting) + calibración isotónica.
    Hiperparámetros de XGB/LGBM optimizados con Optuna (12 trials, TPE,
    minimizando log-loss en validación temporal 2024-2026): 0.8988 -> 0.8981.
    """
    xgb = XGBClassifier(
        n_estimators=200, max_depth=5, learning_rate=0.0315,
        subsample=0.85, colsample_bytree=0.8, reg_lambda=6.22,
        objective='multi:softprob', eval_metric='mlogloss',
        tree_method='hist', random_state=42, n_jobs=-1, verbosity=0,
    )
    rf = RandomForestClassifier(
        n_estimators=450, max_depth=12, min_samples_leaf=4,
        max_features='sqrt', class_weight='balanced_subsample',
        random_state=42, n_jobs=-1,
    )
    lgbm = LGBMClassifier(
        n_estimators=300, num_leaves=47, learning_rate=0.0462,
        subsample=0.85, colsample_bytree=0.8, reg_lambda=2.11,
        objective='multiclass', random_state=42, n_jobs=-1, verbose=-1,
    )
    ensemble = VotingClassifier(
        estimators=[('xgb', xgb), ('rf', rf), ('lgbm', lgbm)],
        voting='soft', n_jobs=1,
    )
    return CalibratedClassifierCV(ensemble, method='isotonic', cv=3)


def validacion_walk_forward(ds: dict, topo: np.ndarray) -> dict:
    """
    Backtesting walk-forward: entrenamiento expansivo (todo el pasado) y
    ventanas de validación de 6 meses rodando sobre 2024-2026. El escalador
    y el ensemble se reajustan en cada ventana (sin fuga temporal).
    """
    X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
    ventanas = pd.date_range('2024-01-01', fechas.max(), freq='6MS')
    filas = []
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values
        if m_va.sum() < 50:
            continue
        X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
        modelo = construir_ensemble()
        modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
        acc = accuracy_score(y[m_va], proba.argmax(axis=1))
        ll = log_loss(y[m_va], proba, labels=[0, 1, 2])
        filas.append({'ventana': f"{inicio.date()} → {fin.date()}",
                      'n': int(m_va.sum()), 'precision': round(float(acc), 4),
                      'log_loss': round(float(ll), 4)})
        logger.info(f"  walk-forward {inicio.date()}: n={m_va.sum()} acc={acc:.3f} ll={ll:.3f}")
    resumen = {
        'ventanas': filas,
        'precision_media': round(float(np.mean([f['precision'] for f in filas])), 4),
        'log_loss_medio': round(float(np.mean([f['log_loss'] for f in filas])), 4),
    }
    logger.info(f"Walk-forward: precisión media {resumen['precision_media']:.3f} · "
                f"log-loss medio {resumen['log_loss_medio']:.3f} sobre {len(filas)} ventanas.")
    return resumen


def entrenar(corte: str = None, con_aumento: bool = True,
             walkforward: bool = False) -> dict:
    # ------------------------------------------------------------------ 1
    if not os.path.exists(HISTORICO_FILE):
        logger.error(f"No existe {HISTORICO_FILE}. Ejecuta primero pipeline_mundial.py")
        sys.exit(1)
    historico = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
    logger.info(f"Histórico cargado: {len(historico)} partidos "
                f"({historico['date'].min().date()} → {historico['date'].max().date()}).")

    ds = fe.construir_dataset_supervisado(historico)
    X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
    logger.info(f"Dataset supervisado: {len(X_df)} partidos con features pre-partido válidas.")
    if len(X_df) < 100:
        logger.error("Menos de 100 partidos utilizables: histórico insuficiente.")
        sys.exit(1)

    # ------------------------------------------------------------------ 2
    logger.info("Calculando homología persistente (par + últimos 10 por equipo)...")
    topo = calcular_features_topologicas(ds)

    # ------------------------------------------------------------------ 3
    fecha_corte = pd.Timestamp(corte) if corte else fechas.quantile(0.80)
    m_train = (fechas < fecha_corte).values
    m_val = ~m_train
    if m_val.sum() < 30 or m_train.sum() < 70:
        logger.error(f"Split temporal degenerado (train={m_train.sum()}, val={m_val.sum()}).")
        sys.exit(1)
    logger.info(f"Validación temporal: train={m_train.sum()} (< {fecha_corte.date()}), "
                f"validación={m_val.sum()} partidos reales posteriores.")

    # Normalización ajustada SOLO con el train real
    X_tr_norm, X_va_norm, escalador = fe.normalizar_features(X_df[m_train], X_df[m_val])
    X_tr = np.hstack([X_tr_norm, topo[m_train]])
    X_va = np.hstack([X_va_norm, topo[m_val]])
    y_tr, y_va = y[m_train], y[m_val]
    goles_tr = ds['goles'][m_train]

    # ------------------------------------------------------------------ 4
    if con_aumento:
        try:
            ds_aug = generar_aumento_sintetico(N_PARTIDOS_AUMENTO)
            if len(ds_aug['X_df']) > 0:
                topo_aug = calcular_features_topologicas(ds_aug)
                X_aug = np.hstack([escalador.transform(ds_aug['X_df']), topo_aug])
                X_tr = np.vstack([X_tr, X_aug])
                y_tr = np.concatenate([y_tr, ds_aug['y']])
                goles_tr = np.vstack([goles_tr, ds_aug['goles']])
        except Exception as e:
            logger.warning(f"Aumento sintético omitido ({type(e).__name__}: {e}).")

    # ---- Cuotas de apertura (opcional, solo entrenamiento/backtesting) ------
    # Probabilidades implícitas del mercado + overround si fetch_odds.py las
    # acumuló en odds_historicas.csv. Sin cobertura suficiente se omiten y el
    # modelo queda idéntico (degradación limpia prevista en la especificación).
    import fetch_odds
    match_ids = [m[3] for m in ds['meta']]
    cuotas = fetch_odds.cargar_features_cuotas(match_ids)
    cobertura = float(cuotas['PROB_IMP_HOME'].notna().mean())
    odds_activas = bool(cobertura >= 0.05)
    odds_medias = None
    if odds_activas:
        medias_train = cuotas[m_train].mean()
        odds_medias = [round(float(v), 4) for v in medias_train]
        c_real = cuotas[m_train].fillna(medias_train).values
        n_aug = len(X_tr) - int(m_train.sum())
        c_aug = np.tile(medias_train.values, (n_aug, 1)) if n_aug > 0 else np.empty((0, 4))
        X_tr = np.hstack([X_tr, np.vstack([c_real, c_aug])])
        X_va = np.hstack([X_va, cuotas[m_val].fillna(medias_train).values])
        logger.info(f"Cuotas de apertura ACTIVAS como feature "
                    f"(cobertura {cobertura*100:.1f} % de los partidos).")
    else:
        logger.info(f"Cuotas de apertura no disponibles (cobertura {cobertura*100:.1f} %): "
                    f"el modelo se entrena sin ellas.")

    # ------------------------------------------------------------------ 5
    logger.info(f"Entrenando ensemble XGB+RF+LGBM (isotónico) con {len(X_tr)} partidos...")
    modelo = construir_ensemble()
    modelo.fit(X_tr, y_tr)

    proba_va = modelo.predict_proba(X_va)
    pred_va = np.argmax(proba_va, axis=1)
    precision = accuracy_score(y_va, pred_va)
    perdida = log_loss(y_va, proba_va, labels=[0, 1, 2])
    pred_base = np.where(X_df[m_val]['DIFF_ELO'].values > 0, 0, 2)
    precision_base = accuracy_score(y_va, pred_base)

    logger.info(f"Precisión validación temporal: {precision:.3f} "
                f"(línea base 'siempre el favorito': {precision_base:.3f})")
    logger.info(f"Log-loss validación: {perdida:.4f}")

    # ------------------------------------------------------------------ 6
    logger.info("Entrenando regresores de goles esperados (Poisson)...")
    reg_local = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                              learning_rate=0.06, max_depth=6,
                                              random_state=42)
    reg_visit = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                              learning_rate=0.06, max_depth=6,
                                              random_state=42)
    reg_local.fit(X_tr, goles_tr[:, 0])
    reg_visit.fit(X_tr, goles_tr[:, 1])
    goles_va = ds['goles'][m_val]
    mae_l = float(np.mean(np.abs(reg_local.predict(X_va) - goles_va[:, 0])))
    mae_v = float(np.mean(np.abs(reg_visit.predict(X_va) - goles_va[:, 1])))
    logger.info(f"MAE goles esperados (validación): local {mae_l:.3f} · visitante {mae_v:.3f}")

    # ------------------------------------------------------------------ 7
    origen = fuente_de_datos()
    deploy_ready = bool(precision >= UMBRAL_DESPLIEGUE)
    objetivo_estricto = bool(precision >= OBJETIVO_PRECISION and perdida <= OBJETIVO_LOGLOSS)
    if objetivo_estricto:
        logger.info(f"🏆 OBJETIVO ESTRICTO CUMPLIDO: {precision:.1%} ≥ {OBJETIVO_PRECISION:.0%} "
                    f"y log-loss {perdida:.3f} ≤ {OBJETIVO_LOGLOSS}.")
    elif deploy_ready:
        logger.info(f"✅ Regla de oro superada ({precision:.1%} ≥ {UMBRAL_DESPLIEGUE:.0%}). "
                    f"Objetivo estricto (62 % / 0.85) NO alcanzado — se reporta con transparencia.")
    else:
        logger.error(f"❌ Precisión {precision:.1%} < {UMBRAL_DESPLIEGUE:.0%}: NO desplegar.")

    os.makedirs(DIRECTORIO_MODELOS, exist_ok=True)
    # compress=3: mantiene el ensemble bajo el límite de 100 MB de GitHub
    joblib.dump(modelo, os.path.join(DIRECTORIO_MODELOS, 'modelo_tda.joblib'), compress=3)
    joblib.dump(escalador, os.path.join(DIRECTORIO_MODELOS, 'escalador.joblib'), compress=3)
    joblib.dump(reg_local, os.path.join(DIRECTORIO_MODELOS, 'reg_goles_local.joblib'), compress=3)
    joblib.dump(reg_visit, os.path.join(DIRECTORIO_MODELOS, 'reg_goles_visit.joblib'), compress=3)

    # Insumos del notebook de backtesting (curvas de calibración, etc.)
    np.savez_compressed(os.path.join(DIRECTORIO_MODELOS, 'validacion.npz'),
                        proba=proba_va, y=y_va,
                        fechas=fechas[m_val].astype('int64').values)

    # ------------------------------------------------------------------ 8
    walk = validacion_walk_forward(ds, topo) if walkforward else None

    metadata = {
        'version': 11,
        'walk_forward': walk,
        'odds_features': {'activas': odds_activas,
                          'cobertura': round(cobertura, 4),
                          'medias_train': odds_medias},
        'entrenado_en': datetime.datetime.now().isoformat(timespec='seconds'),
        'fuente_datos': origen,
        'arquitectura': 'VotingClassifier(XGBoost+RandomForest+LightGBM) + CalibratedClassifierCV(isotonic)',
        'n_partidos_train_real': int(m_train.sum()),
        'n_partidos_train_aumento': int(len(X_tr) - m_train.sum()),
        'n_partidos_validacion': int(m_val.sum()),
        'fecha_corte_validacion': str(fecha_corte.date()),
        'precision_validacion': round(float(precision), 4),
        'precision_linea_base': round(float(precision_base), 4),
        'log_loss_validacion': round(float(perdida), 4),
        'mae_goles_local': round(mae_l, 4),
        'mae_goles_visitante': round(mae_v, 4),
        'deploy_ready': deploy_ready,
        'umbral_despliegue': UMBRAL_DESPLIEGUE,
        'objetivo_estricto': {'precision': OBJETIVO_PRECISION, 'log_loss': OBJETIVO_LOGLOSS,
                              'cumplido': objetivo_estricto},
        'features': fe.FEATURES_MODELO + fe.FEATURES_TOPO,
    }
    with open(os.path.join(DIRECTORIO_MODELOS, 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    logger.info(f"Artefactos guardados en ./{DIRECTORIO_MODELOS}/")
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Entrena el ensemble TDA con validación temporal.')
    parser.add_argument('--corte', type=str, default=None,
                        help='Fecha de corte del backtesting (YYYY-MM-DD).')
    parser.add_argument('--sin-aumento', action='store_true',
                        help='Desactiva el aumento de datos sintéticos.')
    parser.add_argument('--walkforward', action='store_true',
                        help='Añade backtesting walk-forward (ventanas de 6 meses, 2024-2026).')
    args = parser.parse_args()
    entrenar(args.corte, con_aumento=not args.sin_aumento, walkforward=args.walkforward)
