#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optimizador de cartera de Markowitz — EXPERIMENTAL (v33 §3.2).

Trata los picks del día como activos: cada uno tiene un retorno esperado
(EV) y una varianza (la de una apuesta binaria). Se buscan los pesos que
maximizan el ratio de Sharpe con la frontera eficiente.

RESTRICCIÓN MATEMÁTICA OBLIGATORIA (§3.2): la matriz de covarianza es
DIAGONAL entre deportes/ligas distintos (independencia asumida y declarada);
solo se estima covarianza para picks que comparten liga Y día — ahí sí puede
haber correlación real (misma jornada, mismo clima, mismos árbitros), y se
aproxima con una correlación positiva conservadora ρ=0.15.

Para una apuesta binaria con probabilidad p y cuota c:
    retorno esperado  μ = c·p − 1
    varianza          σ² = p(1−p)·c²

NO sustituye al Kelly simultáneo salvo que el backtest lo justifique
(`comparar_con_kelly`).
"""

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)

RHO_MISMA_LIGA = 0.15
MAX_PESO = 0.25          # nada de concentrar más del 25 % en un solo pick


def _mu_sigma(picks: List[Dict]):
    mu = np.array([(p['cuota'] * p['prob'] - 1) for p in picks], dtype=float)
    var = np.array([p['prob'] * (1 - p['prob']) * p['cuota'] ** 2
                    for p in picks], dtype=float)
    n = len(picks)
    cov = np.diag(var)
    for i in range(n):
        for j in range(i + 1, n):
            misma = (picks[i].get('liga') == picks[j].get('liga')
                     and picks[i].get('fecha') == picks[j].get('fecha'))
            if misma:
                c = RHO_MISMA_LIGA * np.sqrt(var[i] * var[j])
                cov[i, j] = cov[j, i] = c
    return mu, cov


def optimizar(picks: List[Dict], exposicion_total: float = 0.20) -> Dict:
    """Pesos de máximo Sharpe (long-only, suma = exposición total)."""
    picks = [p for p in picks if p.get('cuota') and p.get('prob')]
    if not picks:
        return {'pesos': [], 'aviso': 'Sin picks con cuota real.'}
    mu, cov = _mu_sigma(picks)
    if (mu <= 0).all():
        return {'pesos': [], 'aviso': 'Ningún pick tiene EV positivo hoy.'}
    # solución analítica long-only aproximada: w ∝ Σ⁻¹μ, recortada a ≥0
    try:
        w = np.linalg.solve(cov + np.eye(len(mu)) * 1e-9, mu)
    except np.linalg.LinAlgError:
        w = mu / np.maximum(np.diag(cov), 1e-9)
    w = np.clip(w, 0, None)
    if w.sum() <= 0:
        return {'pesos': [], 'aviso': 'Sin solución long-only con EV positivo.'}
    w = w / w.sum()
    w = np.minimum(w, MAX_PESO)              # tope por pick
    w = w / w.sum() * exposicion_total       # escala a la exposición objetivo
    ret = float(w @ mu)
    vol = float(np.sqrt(max(w @ cov @ w, 1e-12)))
    return {
        'pesos': [{'partido': p.get('partido'), 'apuesta': p.get('apuesta'),
                   'peso_pct': round(float(x) * 100, 2),
                   'ev': round(float(m), 4)}
                  for p, x, m in zip(picks, w, mu)],
        'retorno_esperado_pct': round(ret * 100, 3),
        'volatilidad_pct': round(vol * 100, 3),
        'sharpe': round(ret / vol, 3) if vol > 0 else None,
        'exposicion_total_pct': round(float(w.sum()) * 100, 2),
        'nota': ('Covarianza DIAGONAL entre deportes/ligas distintos '
                 '(independencia declarada); ρ=0.15 solo dentro de la misma '
                 'liga y día.'),
    }


def comparar_con_kelly(picks: List[Dict], bankroll: float = 1000.0,
                       n_sim: int = 5000, seed: int = 33) -> Dict:
    """Monte Carlo de UNA jornada: Markowitz vs Kelly simultáneo (⅛, cap 20 %).
    Compara retorno medio, volatilidad y peor caso (percentil 5)."""
    import kelly_simultaneo as ks
    picks = [p for p in picks if p.get('cuota') and p.get('prob')]
    if len(picks) < 2:
        return {'aviso': 'Se necesitan ≥2 picks con cuota para comparar.'}
    rng = np.random.default_rng(seed)
    probs = np.array([p['prob'] for p in picks])
    cuotas = np.array([p['cuota'] for p in picks])
    ganan = rng.random((n_sim, len(picks))) < probs

    w_mk = np.array([x['peso_pct'] / 100 for x in optimizar(picks)['pesos']]) \
        if optimizar(picks).get('pesos') else np.zeros(len(picks))
    w_ke = np.array([s['stake_pct'] for s in ks.stakes_jornada(picks, bankroll)])

    def _res(w):
        pago = np.where(ganan, w * (cuotas - 1), -w)
        r = pago.sum(axis=1)
        return {'retorno_medio_pct': round(float(r.mean()) * 100, 3),
                'volatilidad_pct': round(float(r.std()) * 100, 3),
                'peor_5pct': round(float(np.percentile(r, 5)) * 100, 3),
                'exposicion_pct': round(float(w.sum()) * 100, 2)}
    return {'markowitz': _res(w_mk), 'kelly_simultaneo': _res(w_ke),
            'n_picks': len(picks), 'n_sim': n_sim}


if __name__ == '__main__':
    import json
    import warnings
    warnings.filterwarnings('ignore')
    logging.basicConfig(level=logging.INFO)
    import alpha_finder
    r = alpha_finder.apuestas_del_dia_universal()
    picks = (r.get('capa1') or []) + (r.get('ev_extremo') or [])
    print(json.dumps(optimizar(picks), indent=2, ensure_ascii=False))
    print(json.dumps(comparar_con_kelly(picks), indent=2, ensure_ascii=False))
