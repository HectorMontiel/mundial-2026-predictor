#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalización para Análisis Topológico de Datos (TDA)."""

import pandas as pd
from sklearn.preprocessing import MinMaxScaler
import logging

logger = logging.getLogger(__name__)


def normalize_datasets(equipos_df: pd.DataFrame, jugadores_df: pd.DataFrame):
    """Escala todas las columnas numéricas a [0,1] con MinMaxScaler."""
    equipos_scaled = equipos_df.copy()
    jugadores_scaled = jugadores_df.copy()

    num_eq = equipos_df.select_dtypes(include='number').columns
    num_pl = jugadores_df.select_dtypes(include='number').columns

    scaler_eq = MinMaxScaler()
    scaler_pl = MinMaxScaler()

    if len(equipos_df) > 0:
        equipos_scaled[num_eq] = scaler_eq.fit_transform(equipos_df[num_eq])
    if len(jugadores_df) > 0:
        jugadores_scaled[num_pl] = scaler_pl.fit_transform(jugadores_df[num_pl])

    logger.info("Normalización TDA completada (todas las variables en [0,1]).")
    return equipos_scaled, jugadores_scaled
