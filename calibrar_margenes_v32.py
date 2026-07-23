#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibra σ del margen (v32 §8.2/§8.3) y el modelo de juegos de tenis (§8.1).

- NBA/MLB: σ = desviación estándar histórica del margen (local − visitante).
  Alimenta el spread y los totales por equipo de la plantilla (margen ~ N(μ,σ)
  con μ deducido de la probabilidad calibrada). Se escribe en metadata.json
  SIN reentrenar los modelos.
- Tenis: regresión de JUEGOS TOTALES sobre |ΔELO| a partir de la columna
  Score del dataset ("6-4 6-3" → 19 juegos). Da el total de juegos esperado
  y su σ, con lo que la plantilla deriva O/U de juegos y hándicap. Los
  marcadores exactos de sets quedan EXCLUIDOS (exigen cadenas de Markov).
"""
import json
import logging
import os
import re

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _actualizar_meta(carpeta: str, extra: dict):
    ruta = os.path.join('modelos', carpeta, 'metadata.json')
    with open(ruta, encoding='utf-8') as f:
        meta = json.load(f)
    meta.update(extra)
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    logger.info(f"[{carpeta}] metadata actualizada: {list(extra)}")


def sigma_nba() -> float:
    df = pd.read_csv('historico_nba.csv')
    s = float((df['home_pts'] - df['away_pts']).std())
    _actualizar_meta('nba', {
        'sigma_margen': round(s, 3),
        'mercados_excluidos': ['Ganador por cuartos (requiere play-by-play)']})
    return s


def sigma_mlb() -> float:
    df = pd.read_csv('historico_mlb.csv')
    s = float((df['home_runs'] - df['away_runs']).std())
    _actualizar_meta('mlb', {
        'sigma_margen': round(s, 3),
        'mercados_excluidos': ['Primeras 5 entradas (requiere event files)']})
    return s


def modelo_juegos_tenis() -> dict:
    """Total de juegos ~ a + b·|ΔELO| (mínimos cuadrados) + σ residual."""
    import kagglehub
    from engines.tennis_engine import DATASET, SUP
    p = kagglehub.dataset_download(DATASET)
    df = pd.read_csv(os.path.join(p, 'atp_tennis.csv'), parse_dates=['Date'])

    def _juegos(score):
        if not isinstance(score, str):
            return None
        tot = 0
        sets = 0
        for a, b in re.findall(r'(\d+)-(\d+)', score):
            ja, jb = int(a), int(b)
            if ja > 20 or jb > 20:      # tie-breaks anotados raro
                continue
            tot += ja + jb
            sets += 1
        return tot if 12 <= tot <= 60 and sets >= 2 else None

    def _margen_juegos(score):
        """Diferencia de juegos (ganador − perdedor) del marcador."""
        if not isinstance(score, str):
            return None
        a_tot = b_tot = 0
        for a, b in re.findall(r'(\d+)-(\d+)', score):
            ja, jb = int(a), int(b)
            if ja > 20 or jb > 20:
                continue
            a_tot += ja
            b_tot += jb
        return abs(a_tot - b_tot) if (a_tot + b_tot) >= 12 else None

    df['margen_juegos'] = df['Score'].map(_margen_juegos)
    df['juegos'] = df['Score'].map(_juegos)
    df = df.dropna(subset=['juegos', 'Rank_1', 'Rank_2'])
    # proxy de fuerza relativa disponible en el propio dataset: log-ranking
    df['gap'] = np.abs(np.log(df['Rank_1'].clip(lower=1))
                       - np.log(df['Rank_2'].clip(lower=1)))
    df['bo5'] = (df['Best of'] == 5).astype(float)
    X = np.column_stack([np.ones(len(df)), df['gap'].values, df['bo5'].values])
    coef, *_ = np.linalg.lstsq(X, df['juegos'].values, rcond=None)
    resid = df['juegos'].values - X @ coef
    mj = df['margen_juegos'].dropna()
    art = {'coef_juegos': [round(float(c), 4) for c in coef],
           'sigma_juegos': round(float(resid.std()), 3),
           'margen_juegos_medio': round(float(mj.mean()), 3),
           'sigma_margen_juegos': round(float(mj.std()), 3),
           'n_partidos_juegos': int(len(df)),
           'mercados_excluidos': [
               'Marcador exacto de sets (requiere cadenas de Markov)',
               'Cualquier set a cero (ídem)',
               'Ganador del primer set (sin datos de saque/resto)']}
    _actualizar_meta('tennis', art)
    logger.info(f"[tenis] juegos = {coef[0]:.2f} + {coef[1]:.2f}·gap + "
                f"{coef[2]:.2f}·bo5 (σ={resid.std():.2f}, n={len(df)})")
    return art


if __name__ == '__main__':
    logger.info(f"σ margen NBA: {sigma_nba():.2f}")
    logger.info(f"σ margen MLB: {sigma_mlb():.2f}")
    print(json.dumps(modelo_juegos_tenis(), indent=2, ensure_ascii=False))
