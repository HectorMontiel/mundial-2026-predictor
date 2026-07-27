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


# ---------------------------------------------------------------------------
# v68 — Matriz conjunta de marcadores: independencia vs dependencia
#
# Estado antes de v68:
#   · El modelo INTERNACIONAL ya usaba una matriz de CHOQUE COMÚN
#     (λ₀ = 0.12·min(λh,λa)) en `prediction_api._monte_carlo`.
#   · Las ligas de CLUBES seguían con `np.outer(ph, pa)`: independencia pura.
#     Es ahí donde está el hueco, no en el internacional.
#
# Lo que NO se repite: Dixon-Coles se probó en v27 sobre 13k+ partidos y se
# descartó con evidencia (el ρ óptimo salía con signo OPUESTO a la teoría y el
# log-loss del marcador exacto no mejoraba). Por eso aquí no se reimplementa τ:
# se comparan las dos formas de dependencia que SÍ quedaban por medir.
# ---------------------------------------------------------------------------
FRACCION_CHOQUE_COMUN = 0.12      # la de producción en el modelo internacional
MAX_GOLES_MATRIZ = 8


# ---------------------------------------------------------------------------
# v70 (Mejora G) — encogimiento de la diferencia de λ
#
# Hallazgo no previsto en el spec, encontrado al validar el ajuste por
# alineaciones. El control de ese diagnóstico medía la correlación entre
# (λ_local − λ_visitante) y el residuo de Pearson del margen, que debería ser
# ~0 si las λ estuviesen bien calibradas. Salió −0,193 en MLS y −0,238 en Liga
# MX (ambas p<0,001): cuando el modelo predice un margen grande, el margen real
# se queda corto de forma sistemática. Los regresores Poisson SEPARAN DEMASIADO
# las dos λ.
#
# Corrección: encoger la diferencia hacia la media conservando el total.
#
#     m = (λ_h + λ_a)/2 ;  d = (λ_h − λ_a)/2
#     λ_h' = m + s·d    ;  λ_a' = m − s·d
#
# s se calibra por liga en walk-forward (`_v70_wf_shrink.py`) minimizando la
# desvianza de Poisson sólo con datos de train. Medido en 15 competiciones,
# s cae entre 0,50 y 0,70 y la desvianza mejora en TODAS (−0,05 a −0,11), con
# el log-loss del 1X2 derivado mejorando en 14 de 15.
#
# s = 1 es no tocar nada, así que una liga sin coeficiente adoptado se queda
# exactamente como estaba.
# ---------------------------------------------------------------------------
ARCHIVO_SHRINK = 'lambda_shrink.json'
_CACHE_SHRINK = {}


def factor_shrink(clave_liga: str) -> float:
    """Factor de encogimiento adoptado para esa liga (1.0 = sin ajuste)."""
    import json
    import os
    if 'ligas' not in _CACHE_SHRINK:
        datos = {}
        try:
            if os.path.exists(ARCHIVO_SHRINK):
                with open(ARCHIVO_SHRINK, encoding='utf-8') as f:
                    datos = json.load(f).get('ligas') or {}
        except Exception:
            datos = {}
        _CACHE_SHRINK['ligas'] = datos
    try:
        s = float(_CACHE_SHRINK['ligas'].get(clave_liga, 1.0))
    except (TypeError, ValueError):
        return 1.0
    return s if 0.2 <= s <= 1.0 else 1.0


def encoger_lambdas(lam_h: float, lam_a: float, clave_liga: str = None,
                    s: float = None):
    """
    Aplica el encogimiento de v70. Conserva λ_h + λ_a (el total esperado de
    goles no cambia; sólo se reparte de forma menos extrema).
    """
    if s is None:
        s = factor_shrink(clave_liga) if clave_liga else 1.0
    if s >= 1.0:
        return float(lam_h), float(lam_a)
    m = (lam_h + lam_a) / 2.0
    d = (lam_h - lam_a) / 2.0
    return (float(np.clip(m + s * d, 0.15, 5.0)),
            float(np.clip(m - s * d, 0.15, 5.0)))


def _pmf_poisson(lam: float, n: int) -> np.ndarray:
    k = np.arange(n + 1)
    p = poisson.pmf(k, max(lam, 1e-9))
    s = p.sum()
    return p / s if s > 0 else p


def matriz_independiente(lam_h: float, lam_a: float,
                         n: int = MAX_GOLES_MATRIZ) -> np.ndarray:
    """Producto de marginales: P(i,j) = P(i)·P(j). El comportamiento previo."""
    return np.outer(_pmf_poisson(lam_h, n), _pmf_poisson(lam_a, n))


def matriz_choque_comun(lam_h: float, lam_a: float, n: int = MAX_GOLES_MATRIZ,
                        fraccion: float = FRACCION_CHOQUE_COMUN) -> np.ndarray:
    """
    Poisson bivariante clásico: X = U + W, Y = V + W, con W el "choque común"
    del partido (ritmo, arbitraje, estado del campo). Induce correlación
    POSITIVA, que es la que se observa en fútbol.

    Es exactamente el modelo que ya usa el motor internacional en producción,
    aquí en forma analítica (sin Monte Carlo, así que es determinista y rápido).
    """
    l0 = fraccion * min(lam_h, lam_a)
    lu, lv = max(lam_h - l0, 1e-9), max(lam_a - l0, 1e-9)
    pu, pv, pw = _pmf_poisson(lu, n), _pmf_poisson(lv, n), _pmf_poisson(l0, n)
    M = np.zeros((n + 1, n + 1))
    for w in range(n + 1):
        if pw[w] < 1e-12:
            continue
        # goles = w + u  ->  desplazar las marginales w casillas
        M[w:, w:] += pw[w] * np.outer(pu[:n + 1 - w], pv[:n + 1 - w])
    s = M.sum()
    return M / s if s > 0 else M


def matriz_copula_gauss(lam_h: float, lam_a: float, rho: float = 0.10,
                        n: int = MAX_GOLES_MATRIZ) -> np.ndarray:
    """
    Cópula gaussiana sobre marginales Poisson (lo que pedía el spec v68).

    Ventaja sobre el choque común: admite ρ NEGATIVO (un equipo que se
    adelanta y se encierra reduce los goles del rival), cosa que el choque
    común no puede representar. Se construye por diferencias de la CDF
    binormal sobre los cuantiles de cada marginal.
    """
    from scipy.stats import norm, multivariate_normal
    if abs(rho) < 1e-6:
        return matriz_independiente(lam_h, lam_a, n)
    ch = np.clip(poisson.cdf(np.arange(-1, n + 1), max(lam_h, 1e-9)), 1e-9, 1 - 1e-9)
    ca = np.clip(poisson.cdf(np.arange(-1, n + 1), max(lam_a, 1e-9)), 1e-9, 1 - 1e-9)
    zh, za = norm.ppf(ch), norm.ppf(ca)
    cov = [[1.0, rho], [rho, 1.0]]
    # C(u,v) evaluada en la rejilla de cortes; la probabilidad de la celda
    # (i,j) es la diferencia de segundo orden de la cópula.
    Z = np.empty((n + 2, n + 2))
    for i in range(n + 2):
        Z[i, :] = multivariate_normal.cdf(
            np.column_stack([np.full(n + 2, zh[i]), za]), mean=[0, 0], cov=cov)
    M = Z[1:, 1:] - Z[:-1, 1:] - Z[1:, :-1] + Z[:-1, :-1]
    M = np.clip(M, 0, None)
    s = M.sum()
    return M / s if s > 0 else M


def matriz_goles(lam_h: float, lam_a: float, metodo: str = 'choque_comun',
                 rho: float = 0.10, n: int = MAX_GOLES_MATRIZ) -> np.ndarray:
    """Punto de entrada único. `metodo` ∈ independiente | choque_comun | copula."""
    if metodo == 'independiente':
        return matriz_independiente(lam_h, lam_a, n)
    if metodo == 'copula':
        return matriz_copula_gauss(lam_h, lam_a, rho, n)
    return matriz_choque_comun(lam_h, lam_a, n)


def probabilidades_1x2(M: np.ndarray) -> tuple:
    """(local, empate, visitante) desde la matriz conjunta."""
    idx = np.arange(M.shape[0])
    local = float(M[idx[:, None] > idx[None, :]].sum())
    empate = float(np.trace(M))
    visit = float(M[idx[:, None] < idx[None, :]].sum())
    total = local + empate + visit
    return (local / total, empate / total, visit / total) if total > 0 else (0.0, 0.0, 0.0)


def prob_btts(M: np.ndarray) -> float:
    """P(ambos marcan) desde la matriz conjunta."""
    return float(M[1:, 1:].sum())


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
