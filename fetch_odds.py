#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Features de cuotas para el ENTRENAMIENTO, leídas de `odds_historicas.csv`.

v88 — QUÉ SE FUE DE AQUÍ Y POR QUÉ
----------------------------------
Este módulo descargaba cuotas de The Odds API (`descargar_cuotas_historicas`,
`descargar_cuotas_fixtures`, `actualizar_odds`) y las acumulaba en
`odds_historicas.csv`. La clave lleva devolviendo **401 en todas las ligas**,
así que esas tres funciones no traían nada: sólo llenaban los logs.

Se retiran junto con `odds_api.py`. Las cuotas EN VIVO del proyecto vienen
desde la v71/v72 de `cuotas_multi` (Pinnacle + Bovada + Playdoit) y de los
fixtures de ESPN, que son gratuitas, sin cuota mensual y cubren más partidos.

Lo que SÍ se conserva es `cargar_features_cuotas`, que **no toca la red**: lee
el CSV que ya está en el repositorio y construye las probabilidades implícitas
que usa `train_tda_model`. Borrarla habría cambiado el modelo entrenado, que no
es lo que se pedía.
"""

import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ODDS_FILE = 'odds_historicas.csv'

__all__ = ['cargar_features_cuotas', 'ODDS_FILE']


def cargar_features_cuotas(match_ids) -> pd.DataFrame:
    """
    Features de cuotas para el ENTRENAMIENTO: probabilidades implícitas
    normalizadas (sin margen) y overround de la casa. NaN donde no hay cuota.
        PROB_IMP_HOME, PROB_IMP_DRAW, PROB_IMP_AWAY, OVERROUND

    Sólo lee `odds_historicas.csv`. Si el archivo no está, devuelve todo NaN y
    el entrenamiento sigue sin esas features (degradación limpia prevista en la
    especificación).
    """
    columnas = ['PROB_IMP_HOME', 'PROB_IMP_DRAW', 'PROB_IMP_AWAY', 'OVERROUND']
    base = pd.DataFrame(index=range(len(match_ids)), columns=columnas, dtype=float)
    if not os.path.exists(ODDS_FILE):
        return base
    odds = pd.read_csv(ODDS_FILE).set_index('MATCH_ID')
    for i, mid in enumerate(match_ids):
        if mid in odds.index:
            fila = odds.loc[mid]
            inv = np.array([1 / fila['odd_home'], 1 / fila['odd_draw'],
                            1 / fila['odd_away']])
            base.iloc[i] = list(inv / inv.sum()) + [float(inv.sum() - 1)]
    return base
