#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reto Escalera — interés compuesto con picks de máxima probabilidad (v32 §2).

Toma de las Apuestas del Día los picks con prob ≥ 85 % y cuota ≥ 1.05
(suelo del §1.1: por debajo el retorno no compensa el riesgo de ruina),
protege contra correlación (un solo pick por partido, y haircut empírico
SGP si dos picks comparten familia de mercado) y simula la escalera con
Monte Carlo (reinversión diaria).

Aviso honesto que la UI debe mostrar: con stake del 100 % un solo fallo
liquida la banca. La simulación cuantifica exactamente eso.
"""

import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

PROB_MIN = 0.85
CUOTA_MIN = 1.05          # §1.1 suelo de cuota
MAX_PICKS = 3


def seleccionar(picks: List[Dict], prob_min: float = PROB_MIN,
                cuota_min: float = CUOTA_MIN,
                max_picks: int = MAX_PICKS) -> List[Dict]:
    """Picks aptos para la escalera, sin dos del mismo partido (§2.2)."""
    aptos = [p for p in picks
             if (p.get('prob') or 0) >= prob_min
             and (p.get('cuota') or 0) >= cuota_min]
    mejor_por_partido: Dict[str, Dict] = {}
    for p in aptos:
        clave = p.get('partido', '?')
        if clave not in mejor_por_partido or \
                p['prob'] > mejor_por_partido[clave]['prob']:
            mejor_por_partido[clave] = p
    return sorted(mejor_por_partido.values(),
                  key=lambda p: -p['prob'])[:max_picks]


def probabilidad_conjunta(picks: List[Dict]) -> float:
    """Producto de probabilidades con haircut de correlación empírico
    (sgp_correlation) cuando dos picks comparten familia de mercado."""
    if not picks:
        return 0.0
    p = 1.0
    for x in picks:
        p *= x['prob']
    try:
        import sgp_correlation as sgp
        for i, a in enumerate(picks):
            for b in picks[i + 1:]:
                misma = a.get('mercado') == b.get('mercado')
                p *= sgp.factor_par(a.get('id', a.get('mercado', '')), a['prob'],
                                    b.get('id', b.get('mercado', '')), b['prob'],
                                    misma_familia=misma)
    except Exception:
        pass
    return float(p)


def simular(prob_conjunta: float, cuota_combinada: float,
            capital: float = 100.0, dias: int = 30, fraccion: float = 1.0,
            n_sim: int = 10000, seed: int = 32) -> Dict:
    """Monte Carlo de la escalera con reinversión diaria (§2.2)."""
    rng = np.random.default_rng(seed)
    cap = np.full(n_sim, float(capital))
    vivo = np.ones(n_sim, dtype=bool)
    dias_racha = np.zeros(n_sim)
    ruina_10 = ruina_20 = None
    for d in range(1, dias + 1):
        gana = rng.random(n_sim) < prob_conjunta
        apostado = cap * fraccion
        cap = np.where(vivo & gana, cap - apostado + apostado * cuota_combinada,
                       np.where(vivo, cap - apostado, cap))
        dias_racha += (vivo & gana)
        vivo &= gana | (fraccion < 1.0)
        vivo &= cap > capital * 0.10
        if d == 10:
            ruina_10 = float(1 - vivo.mean())
        if d == 20:
            ruina_20 = float(1 - vivo.mean())
    return {
        'prob_completar_hoy': round(float(prob_conjunta), 4),
        'dias_racha_medios': round(float(dias_racha.mean()), 2),
        'prob_ruina_10d': round(ruina_10 if ruina_10 is not None else 0.0, 4),
        'prob_ruina_20d': round(ruina_20 if ruina_20 is not None else 0.0, 4),
        'prob_ruina_30d': round(float(1 - vivo.mean()), 4),
        'capital_mediano_30d': round(float(np.median(cap)), 2),
        'capital_p90_30d': round(float(np.percentile(cap, 90)), 2),
    }


def construir(picks: List[Dict], capital: float = 100.0,
              fraccion: float = 1.0) -> Dict:
    """Escalera completa lista para la UI."""
    sel = seleccionar(picks)
    if len(sel) < 1:
        return {'picks': [], 'aviso': 'Hoy no hay picks con probabilidad ≥85 % '
                                      'y cuota ≥1.05 — la escalera no arranca '
                                      '(mejor no forzarla).'}
    pc = probabilidad_conjunta(sel)
    cuota = float(np.prod([p['cuota'] for p in sel]))
    sim = simular(pc, cuota, capital=capital, fraccion=fraccion)
    riesgo_alto = sim['prob_ruina_10d'] > 0.05
    return {
        'picks': sel, 'n_picks': len(sel),
        'prob_conjunta': round(pc, 4), 'cuota_combinada': round(cuota, 3),
        'retorno_por_dia_pct': round((cuota - 1) * 100, 2),
        'simulacion': sim,
        'riesgo_alto': riesgo_alto,
        'aviso': ('⚠️ Con stake del 100 %, UN solo fallo liquida la banca. '
                  f"La simulación da {sim['prob_ruina_10d']*100:.0f} % de ruina "
                  'en 10 días' + (' — usa stake fraccional.' if riesgo_alto
                                  else '.')),
    }
