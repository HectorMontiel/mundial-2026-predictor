#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulador de bankroll Montecarlo (v26, spec §4.1).

1,000 trayectorias de apuestas con el win-rate REAL del modelo (precisión de
backtesting de la liga elegida, o la tasa de acierto de los picks de alta
confianza) y cuotas muestreadas de una normal truncada (media/desviación de
las cuotas observadas en roi_bets_{liga}.json cuando existen).

Estrategias: kelly ¼ (tope 5 % del bankroll — convención del proyecto),
kelly ½, kelly completo (educativo: mostrar su varianza brutal) y stake
fijo 2 %. Devuelve percentiles 5/50/95, probabilidad de ruina (<10 % del
bankroll inicial) y bankroll final mediano.
"""

from typing import Dict, Optional

import numpy as np

ESTRATEGIAS = {
    'kelly_1_4': ('¼ Kelly (tope 5 %)', 0.25),
    'kelly_1_2': ('½ Kelly (tope 5 %)', 0.50),
    'kelly_full': ('Kelly completo (⚠️ varianza brutal)', 1.00),
    'fijo_2': ('Stake fijo 2 %', None),
}
TOPE_STAKE = 0.05
RUINA_FRAC = 0.10


def simular_bankroll(bankroll: float, win_rate: float, odds_mean: float,
                     odds_std: float, n_bets: int, estrategia: str = 'kelly_1_4',
                     n_sim: int = 1000, seed: int = 42) -> Dict:
    """Matriz de trayectorias (n_sim × n_bets+1) y métricas resumen."""
    rng = np.random.default_rng(seed)
    frac_kelly = ESTRATEGIAS.get(estrategia, ESTRATEGIAS['kelly_1_4'])[1]

    # cuotas por apuesta: normal truncada en [1.10, 15]
    cuotas = rng.normal(odds_mean, max(odds_std, 1e-6), size=(n_sim, n_bets))
    cuotas = np.clip(cuotas, 1.10, 15.0)
    gana = rng.random((n_sim, n_bets)) < win_rate

    tray = np.empty((n_sim, n_bets + 1))
    tray[:, 0] = bankroll
    quebrado = np.zeros(n_sim, dtype=bool)
    for t in range(n_bets):
        b = cuotas[:, t] - 1.0
        if frac_kelly is None:
            frac = np.full(n_sim, 0.02)
        else:
            kelly = (b * win_rate - (1 - win_rate)) / np.maximum(b, 1e-6)
            frac = np.clip(kelly * frac_kelly, 0.0, TOPE_STAKE)
        stake = tray[:, t] * frac
        stake[quebrado] = 0.0
        delta = np.where(gana[:, t], stake * b, -stake)
        tray[:, t + 1] = tray[:, t] + delta
        quebrado |= tray[:, t + 1] < bankroll * RUINA_FRAC

    return {
        'trayectorias': tray,
        'p5': np.percentile(tray, 5, axis=0),
        'p50': np.percentile(tray, 50, axis=0),
        'p95': np.percentile(tray, 95, axis=0),
        'prob_ruina': round(float(quebrado.mean()), 4),
        'final_mediano': round(float(np.median(tray[:, -1])), 2),
        'final_p5': round(float(np.percentile(tray[:, -1], 5)), 2),
        'final_p95': round(float(np.percentile(tray[:, -1], 95)), 2),
    }


def parametros_de_liga(clave: Optional[str]) -> Dict:
    """win-rate y distribución de cuotas desde los artefactos reales de la
    liga (roi_bets = picks de alta confianza/EV+ con cuota de cierre)."""
    import json
    import os
    out = {'win_rate': 0.52, 'odds_mean': 2.1, 'odds_std': 0.6,
           'fuente': 'valores por defecto'}
    if not clave:
        return out
    ruta = f'roi_bets_{clave}.json'
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8') as f:
                bets = json.load(f)
            if len(bets) >= 30:
                cuotas = np.array([b['cuota'] for b in bets])
                out = {'win_rate': round(float(np.mean([b['gano'] for b in bets])), 4),
                       'odds_mean': round(float(cuotas.mean()), 3),
                       'odds_std': round(float(cuotas.std()), 3),
                       'fuente': f'{len(bets)} apuestas simuladas de la validación '
                                 f'de {clave} (cuotas de cierre reales)'}
        except Exception:
            pass
    return out
