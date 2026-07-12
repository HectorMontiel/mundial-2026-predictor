#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ratings de jugadores para ligas de clubes (M5.2, v13) — SofaScore/WhoScored.

Objetivo: `avg_rating_titulares` y `sd_rating` por equipo (media de los 11 con
más minutos en los últimos 5 partidos) como features candidatas de LaLiga y
Liga MX, con adopción SOLO si el walk-forward mejora ≥0.5 pp.

ESTADO (verificado 2026-07-12): WhoScored (Incapsula) y la API interna de
SofaScore bloquean el acceso automatizado desde esta red; el módulo degrada
limpiamente y la feature queda NO ADOPTADA por imposibilidad de validación,
tal como exige la especificación ("si no, se descarta y se documenta").
Salida cuando haya datos: player_ratings_{liga}.csv
"""

import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SOFASCORE_TORNEOS = {'liga_mx': 11621, 'laliga': 8, 'premier': 17}


def obtener_ratings(clave_liga: str) -> pd.DataFrame:
    """
    Ratings medios recientes por jugador (best-effort). DataFrame vacío si la
    fuente bloquea el acceso — en ese caso la feature no se entrena.
    """
    torneo = SOFASCORE_TORNEOS.get(clave_liga)
    if torneo is None:
        return pd.DataFrame()
    try:
        url = (f"https://api.sofascore.com/api/v1/unique-tournament/{torneo}"
               f"/season/latest/top-players/overall")
        r = requests.get(url, timeout=20, headers={
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 Chrome/125.0 Safari/537.36')})
        r.raise_for_status()
        filas = []
        for bloque in r.json().get('topPlayers', {}).get('rating', []):
            filas.append({'jugador': bloque['player']['name'],
                          'equipo': bloque['player'].get('team', {}).get('name', ''),
                          'rating': float(bloque['statistics']['rating'])})
        df = pd.DataFrame(filas)
        if not df.empty:
            df.to_csv(f'player_ratings_{clave_liga}.csv', index=False)
            logger.info(f"Ratings [{clave_liga}]: {len(df)} jugadores.")
        return df
    except Exception as e:
        logger.warning(f"Ratings [{clave_liga}] no disponibles "
                       f"({type(e).__name__}): feature de ratings NO adoptada "
                       f"(sin datos no hay validación posible).")
        return pd.DataFrame()


def agregados_por_equipo(clave_liga: str) -> pd.DataFrame:
    """avg_rating_titulares y sd_rating por equipo (si hay ratings)."""
    try:
        df = pd.read_csv(f'player_ratings_{clave_liga}.csv')
    except FileNotFoundError:
        return pd.DataFrame()
    agg = df.groupby('equipo')['rating'].agg(['mean', 'std', 'count'])
    agg.columns = ['avg_rating_titulares', 'sd_rating', 'n_jugadores']
    return agg.reset_index()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    for liga in SOFASCORE_TORNEOS:
        obtener_ratings(liga)
