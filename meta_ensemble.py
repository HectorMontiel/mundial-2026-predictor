#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meta-Ensemble de Superación de Mercado — MESM (v23).

## Formalización

Nivel 1 (existente): ensemble calibrado del proyecto → p_base ∈ Δ².
Nivel 2 (nuevo): meta-modelo logístico multinomial sobre

    z = [ln p_base, ln p_mercado, overround]  ∈ ℝ⁷

entrenado con la **pérdida asimétrica** de la spec v23 §2.2 implementada
como pesos de muestra (equivalente exacto para pérdidas separables):

    w_i = 2.0  si el mercado acertó el partido i y el modelo base falló
    w_i = 0.5  si el modelo base acertó e el mercado falló
    w_i = 1.0  en el resto

Minimizar  Σ w_i · CE(y_i, softmax(W·z_i))  concentra la capacidad del
meta-modelo en la región donde el mercado nos gana, y evita que "desaprenda"
justo donde tenemos ventaja — la asimetría del objetivo de negocio (batir al
mercado) llevada a la función objetivo.

## Protocolo de stacking sin fuga

Dentro de cada ventana walk-forward: el modelo base se entrena con el primer
75 % cronológico del train; el meta se ajusta con el último 25 % (probs
out-of-sample del base). La comparación en validación es SIEMPRE contra el
mismo base — manzanas con manzanas.

Adopción por liga solo si supera la regla de oro en walk-forward; el ROI
simulado con cuotas de cierre se reporta junto a precisión/log-loss.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EPS = 1e-6
PESO_MERCADO_GANA = 2.0
PESO_MODELO_GANA = 0.5


def probs_mercado(df: pd.DataFrame) -> np.ndarray:
    """Cuotas de cierre → probabilidades implícitas normalizadas + overround.
    Devuelve (n, 4): [pH, pD, pA, overround]; NaN si faltan cuotas."""
    inv = np.column_stack([1.0 / df['odd_home'], 1.0 / df['odd_draw'],
                           1.0 / df['odd_away']])
    over = inv.sum(axis=1)
    return np.column_stack([inv / over[:, None], over - 1.0])


def pesos_asimetricos(y: np.ndarray, p_base: np.ndarray,
                      p_mkt: np.ndarray) -> np.ndarray:
    """La pérdida asimétrica de la spec como sample_weight."""
    acierta_base = p_base.argmax(axis=1) == y
    acierta_mkt = p_mkt.argmax(axis=1) == y
    w = np.ones(len(y))
    w[acierta_mkt & ~acierta_base] = PESO_MERCADO_GANA
    w[acierta_base & ~acierta_mkt] = PESO_MODELO_GANA
    return w


class MetaEnsemble:
    """Nivel 2 del MESM: combina p_base y p_mercado con objetivo asimétrico."""

    def __init__(self):
        from sklearn.linear_model import LogisticRegression
        self.lr = LogisticRegression(max_iter=2000, C=1.0)

    @staticmethod
    def _z(p_base: np.ndarray, mkt: np.ndarray) -> np.ndarray:
        return np.column_stack([
            np.log(np.clip(p_base, EPS, 1.0)),
            np.log(np.clip(mkt[:, :3], EPS, 1.0)),
            mkt[:, 3:4],
        ])

    def fit(self, y: np.ndarray, p_base: np.ndarray, mkt: np.ndarray,
            asimetrico: bool = True):
        """asimetrico=False → stacking clásico (ablación científica: aísla
        cuánto aporta la pérdida asimétrica frente a la mera combinación)."""
        w = pesos_asimetricos(y, p_base, mkt[:, :3]) if asimetrico else None
        self.lr.fit(self._z(p_base, mkt), y, sample_weight=w)
        return self

    def predict_proba(self, p_base: np.ndarray, mkt: np.ndarray) -> np.ndarray:
        p = np.zeros((len(p_base), 3))
        proba = self.lr.predict_proba(self._z(p_base, mkt))
        for k_idx, k in enumerate(self.lr.classes_):
            p[:, int(k)] = proba[:, k_idx]
        return p / p.sum(axis=1, keepdims=True)


def roi_simulado(y: np.ndarray, p: np.ndarray, df_cuotas: pd.DataFrame,
                 umbral_prob: float = 0.50) -> Optional[Dict]:
    """1 unidad al pick si p>umbral y EV>0 con la cuota de cierre real."""
    cuotas = df_cuotas[['odd_home', 'odd_draw', 'odd_away']].values
    pick = p.argmax(axis=1)
    cuota_pick = cuotas[np.arange(len(pick)), pick]
    p_pick = p[np.arange(len(pick)), pick]
    ev = cuota_pick * p_pick - 1.0
    juega = (p_pick > umbral_prob) & (ev > 0) & np.isfinite(cuota_pick)
    if juega.sum() == 0:
        return None
    gana = pick[juega] == y[juega]
    ganancia = float(np.where(gana, cuota_pick[juega] - 1.0, -1.0).sum())
    return {'n_apuestas': int(juega.sum()),
            'aciertos': int(gana.sum()),
            'roi_pct': round(100 * ganancia / juega.sum(), 2)}
