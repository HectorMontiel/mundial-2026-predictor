#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Distribuciones probabilísticas de mercados cuantitativos (M2, v13).

Centraliza las líneas over/under y las colas de probabilidad que consumen
la plantilla, el endpoint /distribuciones y el constructor de parlays.
Goles: matriz Monte Carlo bivariada calibrada. Córners/tarjetas/remates:
colas Poisson exactas sobre las λ del partido.
"""

from typing import Dict

import numpy as np
from scipy.stats import poisson

# Líneas estándar por mercado (especificación v13)
LINEAS = {
    'goles_totales': (0.5, 1.5, 2.5, 3.5, 4.5),
    'goles_equipo': (0.5, 1.5, 2.5),
    'corners_totales': (6.5, 7.5, 8.5, 9.5, 10.5),
    'corners_equipo': (3.5, 4.5, 5.5),
    'tarjetas_totales': (2.5, 3.5, 4.5, 5.5),
    'tarjetas_equipo': (1.5, 2.5),
    'remates_totales': (18.5, 20.5, 22.5, 24.5),
    'remates_puerta': (4.5, 5.5, 6.5, 7.5),
}


def prob_over(lam: float, linea: float) -> float:
    """P(Poisson(λ) > línea) para líneas x.5 (cola superior exacta)."""
    return float(1 - poisson.cdf(int(np.floor(linea)), max(lam, 1e-9)))


def lineas_poisson(lam: float, lineas) -> Dict[str, float]:
    """{'over_6.5': pct, ...} monótonas decrecientes por construcción."""
    return {f'over_{l}': round(prob_over(lam, l) * 100, 1) for l in lineas}


def lineas_desde_matriz(M: np.ndarray) -> Dict[str, Dict[str, float]]:
    """Líneas de goles (totales y por equipo) desde la matriz Monte Carlo."""
    idx = np.arange(M.shape[0])
    total = idx[:, None] + idx[None, :]
    g_h, g_a = M.sum(axis=1), M.sum(axis=0)

    def marginal(g, l):
        return round(float(g[int(np.floor(l)) + 1:].sum()) * 100, 1)

    return {
        'goles_totales': {f'over_{l}': round(float(M[total > l].sum()) * 100, 1)
                          for l in LINEAS['goles_totales']},
        'goles_local': {f'over_{l}': marginal(g_h, l) for l in LINEAS['goles_equipo']},
        'goles_visitante': {f'over_{l}': marginal(g_a, l) for l in LINEAS['goles_equipo']},
    }
