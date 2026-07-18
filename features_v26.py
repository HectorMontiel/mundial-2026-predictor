#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Features ortogonales v26 (spec §1.2-§1.4) — pase cronológico SIN fuga.

Tres grupos independientes (cada uno se valida por separado en walk-forward):

  * 'ent'   — Entropía táctica y varianza de rendimiento (§1.2):
      VOLAT_XGF_DIFF  — diff de la desv. estándar del xG a favor (últimos 6)
      VOLAT_GC_DIFF   — diff de la desv. estándar de goles en contra (últ. 6)
      ENTROPIA_DIFF   — diff de la entropía de Shannon de V/E/D (últimos 6)
  * 'elo_d' — Derivadas del ELO (§1.3):
      ELO_VEL_DIFF    — diff de (ELO_t − ELO_{t−3})
      ELO_ACC_DIFF    — diff de ((ELO_t−ELO_{t−1}) − (ELO_{t−1}−ELO_{t−2}))
  * 'urg'   — Índice de urgencia asimétrica (§1.4):
      URGENCIA_DIFF   — urgencia local − visitante, con tabla dinámica por
      temporada. Aproximación honesta y multi-liga: zona de descenso = 3
      últimos, objetivo = 4 primeros (Liga MX/MLS no descienden — se usa
      igualmente la cola de la tabla como proxy de "urgencia por fondos";
      documentado). urgencia = frac_temporada² · [1/(1+dist_desc) +
      1/(1+dist_obj)] — crece al final de la temporada y con la cercanía a
      un objetivo, como pide la spec (jornada>30 y ≤5 pts ⇒ urgencia alta).

Todas emiten el valor ANTES de actualizar el estado con el partido (sin
fuga; mismo patrón que features_extra_liga v17 y el IMT v24). El estado
final por equipo se persiste para reproducirlas en inferencia.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COLS_ENT = ['VOLAT_XGF_DIFF', 'VOLAT_GC_DIFF', 'ENTROPIA_DIFF']
COLS_ELO_D = ['ELO_VEL_DIFF', 'ELO_ACC_DIFF']
COLS_URG = ['URGENCIA_DIFF']
COLS_V26 = COLS_ENT + COLS_ELO_D + COLS_URG

N_VENTANA = 6           # partidos de las ventanas de volatilidad/entropía
N_ELO_VEL = 3           # ELO_t − ELO_{t−3}
DESCENSO_N = 3          # cola de la tabla considerada "zona roja"
OBJETIVO_N = 4          # cabeza de la tabla considerada "objetivo"


def _entropia(resultados: List[float]) -> float:
    """Shannon (base 2) de la distribución V/E/D en la ventana."""
    if not resultados:
        return 0.0
    arr = np.array(resultados)
    ps = [(arr == v).mean() for v in (1.0, 0.5, 0.0)]
    return float(-sum(p * np.log2(p) for p in ps if p > 0))


def _urgencia(frac: float, pts: Dict[str, float], pj: Dict[str, int],
              equipo: str) -> float:
    if not pts or equipo not in pts:
        return 0.0
    tabla = sorted(pts, key=lambda e: -pts[e])
    n = len(tabla)
    if n < 6:
        return 0.0
    pts_eq = pts[equipo]
    linea_desc = pts[tabla[max(n - DESCENSO_N, 0)]]     # 1º de la zona roja
    linea_obj = pts[tabla[min(OBJETIVO_N - 1, n - 1)]]  # último del objetivo
    dist_desc = abs(pts_eq - linea_desc)
    dist_obj = abs(linea_obj - pts_eq)
    return float(frac ** 2 * (1.0 / (1 + dist_desc) + 1.0 / (1 + dist_obj)))


def features_v26(df: pd.DataFrame):
    """(DataFrame por MATCH_ID con COLS_V26, estado final serializable)."""
    xgf: Dict[str, List[float]] = {}
    gc: Dict[str, List[float]] = {}
    res: Dict[str, List[float]] = {}
    elos: Dict[str, List[float]] = {}       # historial de ELO por equipo
    pts: Dict[str, float] = {}
    pj: Dict[str, int] = {}
    temporada_actual = None
    partidos_temporada = 0

    def _st(d, eq):
        return d.setdefault(eq, [])

    filas = []
    for f in df.itertuples(index=False):
        h, a, fecha = f.home_team, f.away_team, f.date
        temp = fecha.year if fecha.month >= 7 else fecha.year - 1
        if temp != temporada_actual:
            temporada_actual = temp
            pts, pj = {}, {}
            partidos_temporada = 0
        n_eq = max(len(pts), 2)
        # fracción de temporada transcurrida (jornadas ≈ 2·(n−1) por equipo)
        jornadas_tot = max(2 * (n_eq - 1), 10)
        frac = min(np.mean([pj.get(h, 0), pj.get(a, 0)]) / jornadas_tot, 1.0)

        def _lado(eq):
            r6 = _st(res, eq)[-N_VENTANA:]
            x6 = _st(xgf, eq)[-N_VENTANA:]
            g6 = _st(gc, eq)[-N_VENTANA:]
            e = _st(elos, eq)
            vel = (e[-1] - e[-1 - N_ELO_VEL]) if len(e) > N_ELO_VEL else 0.0
            acc = ((e[-1] - e[-2]) - (e[-2] - e[-3])) if len(e) >= 3 else 0.0
            return {
                'volat_xgf': float(np.std(x6)) if len(x6) >= 4 else 0.0,
                'volat_gc': float(np.std(g6)) if len(g6) >= 4 else 0.0,
                'entropia': _entropia(r6) if len(r6) >= 4 else 0.0,
                'vel': vel, 'acc': acc,
                'urg': _urgencia(frac, pts, pj, eq),
            }

        lh, la = _lado(h), _lado(a)
        filas.append({
            'MATCH_ID': f.MATCH_ID,
            'VOLAT_XGF_DIFF': float(np.clip((lh['volat_xgf'] - la['volat_xgf']) / 1.5, -1, 1)),
            'VOLAT_GC_DIFF': float(np.clip((lh['volat_gc'] - la['volat_gc']) / 1.5, -1, 1)),
            'ENTROPIA_DIFF': (lh['entropia'] - la['entropia']) / np.log2(3),
            'ELO_VEL_DIFF': float(np.clip((lh['vel'] - la['vel']) / 100.0, -1, 1)),
            'ELO_ACC_DIFF': float(np.clip((lh['acc'] - la['acc']) / 60.0, -1, 1)),
            'URGENCIA_DIFF': float(np.clip(lh['urg'] - la['urg'], -2, 2)) / 2.0,
        })

        # --- actualizar estado DESPUÉS de emitir (sin fuga) ---
        gh, ga = float(f.home_goals), float(f.away_goals)
        xh = float(getattr(f, 'home_xg', np.nan))
        xa = float(getattr(f, 'away_xg', np.nan))
        # ELO local a la función (mismas constantes que _elo_diff_liga)
        r_h = _st(elos, h)[-1] if _st(elos, h) else 1500.0
        r_a = _st(elos, a)[-1] if _st(elos, a) else 1500.0
        e_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        s_h = 1.0 if gh > ga else (0.5 if gh == ga else 0.0)
        _st(elos, h).append(r_h + 24 * (s_h - e_h))
        _st(elos, a).append(r_a + 24 * ((1 - s_h) - (1 - e_h)))
        for eq, propios, rival, xg_p in ((h, gh, ga, xh), (a, ga, gh, xa)):
            _st(res, eq).append(1.0 if propios > rival else
                                (0.5 if propios == rival else 0.0))
            _st(xgf, eq).append(xg_p if np.isfinite(xg_p) else propios)
            _st(gc, eq).append(rival)
            pj[eq] = pj.get(eq, 0) + 1
            pts[eq] = pts.get(eq, 0) + (3 if propios > rival else
                                        (1 if propios == rival else 0))
            # memoria acotada
            res[eq] = res[eq][-N_VENTANA:]
            xgf[eq] = xgf[eq][-N_VENTANA:]
            gc[eq] = gc[eq][-N_VENTANA:]
            elos[eq] = elos[eq][-8:]
        partidos_temporada += 1

    estado = {}
    equipos = sorted(set(df['home_team']) | set(df['away_team']))
    n_eq = max(len(pts), 2)
    jornadas_tot = max(2 * (n_eq - 1), 10)
    for eq in equipos:
        frac = min(pj.get(eq, 0) / jornadas_tot, 1.0)
        estado[eq] = {
            'res': res.get(eq, []), 'xgf': [round(x, 3) for x in xgf.get(eq, [])],
            'gc': gc.get(eq, []), 'elos': [round(e, 1) for e in elos.get(eq, [])],
            'urg': round(_urgencia(frac, pts, pj, eq), 4),
        }
    return pd.DataFrame(filas).set_index('MATCH_ID'), estado


def vector_v26(estado: Dict, home: str, away: str) -> Dict[str, float]:
    """Reproduce las features en inferencia desde el estado guardado."""
    def _lado(eq):
        e = (estado or {}).get(eq) or {}
        elos_ = e.get('elos') or []
        vel = (elos_[-1] - elos_[-1 - N_ELO_VEL]) if len(elos_) > N_ELO_VEL else 0.0
        acc = ((elos_[-1] - elos_[-2]) - (elos_[-2] - elos_[-3])) \
            if len(elos_) >= 3 else 0.0
        x6, g6, r6 = e.get('xgf') or [], e.get('gc') or [], e.get('res') or []
        return {
            'volat_xgf': float(np.std(x6)) if len(x6) >= 4 else 0.0,
            'volat_gc': float(np.std(g6)) if len(g6) >= 4 else 0.0,
            'entropia': _entropia(r6) if len(r6) >= 4 else 0.0,
            'vel': vel, 'acc': acc, 'urg': float(e.get('urg') or 0.0),
        }
    lh, la = _lado(home), _lado(away)
    return {
        'VOLAT_XGF_DIFF': float(np.clip((lh['volat_xgf'] - la['volat_xgf']) / 1.5, -1, 1)),
        'VOLAT_GC_DIFF': float(np.clip((lh['volat_gc'] - la['volat_gc']) / 1.5, -1, 1)),
        'ENTROPIA_DIFF': (lh['entropia'] - la['entropia']) / np.log2(3),
        'ELO_VEL_DIFF': float(np.clip((lh['vel'] - la['vel']) / 100.0, -1, 1)),
        'ELO_ACC_DIFF': float(np.clip((lh['acc'] - la['acc']) / 60.0, -1, 1)),
        'URGENCIA_DIFF': float(np.clip(lh['urg'] - la['urg'], -2, 2)) / 2.0,
    }
