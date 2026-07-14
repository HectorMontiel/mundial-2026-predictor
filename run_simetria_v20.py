#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experimento v20 — Mejora 7: simetría local/visitante en el Mundial.

Mide, sobre el conjunto de validación oficial (corte 2024-01-01, mismos
2,640 partidos del metadata), dos cosas:

1. ASIMETRÍA ACTUAL: cuánto difiere P(gana A | A vs B) de P(gana A | B vs A)
   con el modelo en producción. Las features espejadas se derivan de las
   originales sin reconstruir el estado (todas son antisimétricas o
   constantes; las nubes topológicas se recomponen intercambiando filas).

2. EFECTO DE LA SIMETRIZACIÓN: precisión/log-loss si en partidos NEUTRALES
   la predicción final es el promedio de la vista (A,B) y la vista espejada
   (B,A). En partidos con localía real (neutral=False) se mantiene la vista
   original — exactamente la regla que aplicará el motor.

Regla de adopción (spec 8.3): mantener o mejorar 60.4 % / 0.871.
"""

import json
import logging

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
from config import HISTORICO_FILE
from train_tda_model import entropias_de_nubes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CORTE = pd.Timestamp('2024-01-01')

# Índices de FEATURES_MODELO que cambian de signo al invertir local/visitante
# (diferencias + choque de estilos + H2H); 11-13 (altura/localía/clima) son
# constantes de la sede y no cambian.
IDX_ANTISIMETRICAS = list(range(10)) + [10, 14]


def espejar_vectores(X: np.ndarray) -> np.ndarray:
    Xm = X.copy()
    Xm[:, IDX_ANTISIMETRICAS] *= -1.0
    return Xm


def espejar_nubes_par(nubes: np.ndarray) -> np.ndarray:
    """
    Filas de cada nube (6x10): [v_local, v_visit, medio, |diff|, cruce, ctx].
    Espejo: local<->visit, cruce = ataque del nuevo local (antes visitante)
    vs defensa del nuevo visitante; en ctx se reflejan choque y H2H
    (elementos 3 y 4, almacenados como (x+1)/2).
    """
    m = nubes.copy()
    m[:, [0, 1]] = nubes[:, [1, 0]]
    m[:, 4, :5] = nubes[:, 1, :5]
    m[:, 4, 5:] = nubes[:, 0, 5:]
    m[:, 5, 3] = 1.0 - nubes[:, 5, 3]
    m[:, 5, 4] = 1.0 - nubes[:, 5, 4]
    return m


def main():
    historico = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
    neutral_por_id = dict(zip(historico['MATCH_ID'], historico['neutral'].astype(bool)))
    ds = fe.construir_dataset_supervisado(historico)
    X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
    m_val = (fechas >= CORTE).values
    logger.info(f"Validación: {m_val.sum()} partidos (>= {CORTE.date()}).")

    modelo = joblib.load('modelos/modelo_tda.joblib')
    escalador = joblib.load('modelos/escalador.joblib')
    reg_l = joblib.load('modelos/reg_goles_local.joblib')
    reg_v = joblib.load('modelos/reg_goles_visit.joblib')

    # ---------- vista original (reproduce la validación oficial) ----------
    X_val = X_df[m_val]
    topo_val = np.hstack([
        entropias_de_nubes(ds['nubes_par'][m_val], 'par'),
        entropias_de_nubes(ds['nubes_local'][m_val], 'local-10'),
        entropias_de_nubes(ds['nubes_visit'][m_val], 'visit-10'),
    ])
    Xv = np.hstack([escalador.transform(X_val), topo_val])
    p1 = modelo.predict_proba(Xv)
    y_val = y[m_val]
    acc0 = accuracy_score(y_val, p1.argmax(axis=1))
    ll0 = log_loss(y_val, p1, labels=[0, 1, 2])
    logger.info(f"Baseline reproducido: acc={acc0:.4f} ll={ll0:.4f} "
                f"(metadata: 0.6038 / 0.8712)")

    # ---------- vista espejada ----------
    Xm_df = pd.DataFrame(espejar_vectores(X_val.values), columns=fe.FEATURES_MODELO)
    topo_m = np.hstack([
        entropias_de_nubes(espejar_nubes_par(ds['nubes_par'][m_val]), 'par-esp'),
        entropias_de_nubes(ds['nubes_visit'][m_val], 'local-esp'),
        entropias_de_nubes(ds['nubes_local'][m_val], 'visit-esp'),
    ])
    Xm = np.hstack([escalador.transform(Xm_df), topo_m])
    p2 = modelo.predict_proba(Xm)
    p2_esp = p2[:, ::-1]        # (gana B, empate, gana A) -> óptica de A local

    # ---------- 1. asimetría actual ----------
    dif = np.abs(p1 - p2_esp).max(axis=1)
    logger.info(f"ASIMETRÍA |p(A,B) - espejo(B,A)| por partido: "
                f"media {dif.mean()*100:.1f} pp · p90 {np.percentile(dif, 90)*100:.1f} pp · "
                f"máx {dif.max()*100:.1f} pp")

    # ---------- 2. simetrización solo en sede neutral ----------
    ids_val = [m[3] for m, keep in zip(ds['meta'], m_val) if keep]
    es_neutral = np.array([bool(neutral_por_id.get(i, False)) for i in ids_val])
    logger.info(f"Partidos neutrales en validación: {es_neutral.sum()} de {len(ids_val)}.")

    p_fix = p1.copy()
    p_fix[es_neutral] = (p1[es_neutral] + p2_esp[es_neutral]) / 2.0
    p_fix /= p_fix.sum(axis=1, keepdims=True)
    acc1 = accuracy_score(y_val, p_fix.argmax(axis=1))
    ll1 = log_loss(y_val, p_fix, labels=[0, 1, 2])

    # métricas por subconjunto neutral (donde de verdad cambia algo)
    accN0 = accuracy_score(y_val[es_neutral], p1[es_neutral].argmax(axis=1))
    accN1 = accuracy_score(y_val[es_neutral], p_fix[es_neutral].argmax(axis=1))
    llN0 = log_loss(y_val[es_neutral], p1[es_neutral], labels=[0, 1, 2])
    llN1 = log_loss(y_val[es_neutral], p_fix[es_neutral], labels=[0, 1, 2])

    # ---------- goles: MAE con lambdas simetrizadas en neutral ----------
    goles_val = ds['goles'][m_val]
    lh1, la1 = reg_l.predict(Xv), reg_v.predict(Xv)
    lh2, la2 = reg_l.predict(Xm), reg_v.predict(Xm)
    lh_fix, la_fix = lh1.copy(), la1.copy()
    lh_fix[es_neutral] = (lh1[es_neutral] + la2[es_neutral]) / 2.0
    la_fix[es_neutral] = (la1[es_neutral] + lh2[es_neutral]) / 2.0
    mae0 = np.mean(np.abs(lh1 - goles_val[:, 0])) + np.mean(np.abs(la1 - goles_val[:, 1]))
    mae1 = np.mean(np.abs(lh_fix - goles_val[:, 0])) + np.mean(np.abs(la_fix - goles_val[:, 1]))

    resumen = {
        'asimetria_actual': {'media_pp': round(float(dif.mean() * 100), 2),
                             'p90_pp': round(float(np.percentile(dif, 90) * 100), 2),
                             'max_pp': round(float(dif.max() * 100), 2)},
        'n_validacion': int(m_val.sum()),
        'n_neutrales': int(es_neutral.sum()),
        'global': {'acc_antes': round(float(acc0), 4), 'acc_despues': round(float(acc1), 4),
                   'll_antes': round(float(ll0), 4), 'll_despues': round(float(ll1), 4)},
        'solo_neutrales': {'acc_antes': round(float(accN0), 4), 'acc_despues': round(float(accN1), 4),
                           'll_antes': round(float(llN0), 4), 'll_despues': round(float(llN1), 4)},
        'mae_goles_suma': {'antes': round(float(mae0), 4), 'despues': round(float(mae1), 4)},
    }
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    with open('resultados_simetria_v20.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    main()
