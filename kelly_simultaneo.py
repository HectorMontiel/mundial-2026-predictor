#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kelly Fraccional SIMULTÁNEO con cap de exposición global (v27 §5).

El Kelly secuencial supone que el bankroll se actualiza entre apuestas; en
una jornada con muchos partidos simultáneos eso sobreexpone. Aquí:

  1. stake individual = ⅛ Kelly (más conservador que el ¼ clásico del
     proyecto), con tope del 5 % por apuesta (convención v19).
  2. si Σ stakes > 20 % del bankroll, TODOS se escalan proporcionalmente
     hasta que la exposición total sea exactamente el 20 %.

Validación (§5): simulación Montecarlo por jornadas comparando contra el
¼ Kelly secuencial — ver `comparar_estrategias()` (usa el motor de
montecarlo_sim con apuestas agrupadas).
"""

from typing import Dict, List

import numpy as np

FRACCION = 0.125          # ⅛ Kelly
TOPE_APUESTA = 0.05       # 5 % por apuesta (convención del proyecto)
CAP_GLOBAL = 0.20         # exposición máxima de la jornada


def stakes_jornada(apuestas: List[Dict], bankroll: float) -> List[Dict]:
    """apuestas: [{'prob':…, 'cuota':…, …}] → añade stake/stake_pct
    (escalados si la exposición supera el cap global)."""
    out = []
    for a in apuestas:
        b = max(a['cuota'] - 1.0, 1e-6)
        kelly = (b * a['prob'] - (1 - a['prob'])) / b
        # v28 (§2.5): las apuestas EVC Platino ponderan ×1.5 ANTES del cap
        peso = 1.5 if a.get('platino') else 1.0
        frac = float(np.clip(kelly * FRACCION * peso, 0.0, TOPE_APUESTA))
        out.append({**a, 'stake_pct': frac})
    total = sum(a['stake_pct'] for a in out)
    factor = CAP_GLOBAL / total if total > CAP_GLOBAL else 1.0
    for a in out:
        a['stake_pct'] = round(a['stake_pct'] * factor, 5)
        a['stake'] = round(a['stake_pct'] * bankroll, 2)
    return out


def comparar_estrategias(win_rate: float, odds_mean: float, odds_std: float,
                         n_jornadas: int = 60, bets_por_jornada: int = 5,
                         bankroll: float = 1000.0, n_sim: int = 1000,
                         seed: int = 42) -> Dict:
    """Montecarlo por JORNADAS: ¼ Kelly secuencial vs ⅛ simultáneo+cap 20 %.
    Reporta bankroll mediano, drawdown máximo mediano y prob. de ruina."""
    rng = np.random.default_rng(seed)

    def _sim(frac, cap):
        tray = np.full(n_sim, bankroll)
        peak = tray.copy()
        maxdd = np.zeros(n_sim)
        ruina = np.zeros(n_sim, dtype=bool)
        for _ in range(n_jornadas):
            cuotas = np.clip(rng.normal(odds_mean, odds_std,
                                        (n_sim, bets_por_jornada)), 1.10, 15.0)
            gana = rng.random((n_sim, bets_por_jornada)) < win_rate
            b = cuotas - 1.0
            kelly = np.clip((b * win_rate - (1 - win_rate)) / b * frac,
                            0.0, TOPE_APUESTA)
            if cap:
                tot = kelly.sum(axis=1, keepdims=True)
                kelly = np.where(tot > CAP_GLOBAL, kelly * CAP_GLOBAL / tot, kelly)
            stakes = tray[:, None] * kelly          # simultáneas: mismo bankroll
            delta = np.where(gana, stakes * b, -stakes).sum(axis=1)
            tray = np.maximum(tray + delta, 0.0)
            peak = np.maximum(peak, tray)
            maxdd = np.maximum(maxdd, 1 - tray / np.maximum(peak, 1e-9))
            ruina |= tray < bankroll * 0.10
        return {'final_mediano': round(float(np.median(tray)), 2),
                'drawdown_max_mediano': round(float(np.median(maxdd)), 4),
                'prob_ruina': round(float(ruina.mean()), 4)}

    return {'kelly_1_4_secuencial': _sim(0.25, cap=False),
            'kelly_1_8_simultaneo_cap20': _sim(FRACCION, cap=True)}


if __name__ == '__main__':
    import json
    import montecarlo_sim as mc
    par = mc.parametros_de_liga('liga_mx')
    print(json.dumps({'parametros': par,
                      **comparar_estrategias(par['win_rate'], par['odds_mean'],
                                             par['odds_std'])}, indent=2))
