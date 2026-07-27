#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA game logs vía nba_api (v30 §4) — gratuito, JSON oficial, sin bloqueos.

leaguegamelog da una fila por equipo-partido; se emparejan por GAME_ID en
local/visitante (MATCHUP "DEN vs. LAL" = local; "LAL @ DEN" = visitante).
Se calculan posesiones para OFF/DEF rating. Caché en historico_nba.csv.
"""

import logging
import os
import time
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)

SALIDA = 'historico_nba.csv'


def _clave_gid(gid) -> str:
    """
    Clave canónica del partido, igual venga de la API (cadena con ceros a la
    izquierda) o del CSV (entero). Sin esto la deduplicación no funciona.
    """
    return str(gid).strip().lstrip('0') or '0'


def descargar_temporada(season: str) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog
    lg = leaguegamelog.LeagueGameLog(season=season, timeout=45)
    df = lg.get_data_frames()[0]
    filas = {}
    for r in df.itertuples(index=False):
        gid = r.GAME_ID
        poss = (r.FGA + 0.44 * r.FTA - r.OREB + r.TOV)
        d = filas.setdefault(gid, {'GAME_ID': gid, 'date': r.GAME_DATE})
        es_local = 'vs.' in r.MATCHUP
        lado = 'home' if es_local else 'away'
        d[f'{lado}_team'] = r.TEAM_ABBREVIATION
        d[f'{lado}_pts'] = r.PTS
        d[f'{lado}_poss'] = poss
    filas = [f for f in filas.values() if 'home_team' in f and 'away_team' in f]
    out = pd.DataFrame(filas)
    logger.info(f"[nba] {season}: {len(out)} juegos")
    return out


def actualizar(seasons: List[str]) -> pd.DataFrame:
    existente = pd.read_csv(SALIDA, parse_dates=['date']) if os.path.exists(SALIDA) else pd.DataFrame()
    presentes = set(existente['date'].dt.year.astype(str)) if not existente.empty else set()
    frames = [existente] if not existente.empty else []
    reciente = seasons[-1]
    for s in seasons:
        anio = s[:4]
        if anio in presentes and s != reciente:
            continue
        try:
            frames.append(descargar_temporada(s))
            time.sleep(1.0)
        except Exception as e:
            logger.warning(f"[nba] {s} falló: {e}")
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        # v70: la deduplicación fallaba silenciosamente. `leaguegamelog` devuelve
        # el GAME_ID como cadena con ceros a la izquierda ('0022500001') y al
        # releerlo del CSV vuelve como entero (22500001); al concatenar quedaban
        # los dos tipos en la misma columna y `drop_duplicates` no los veía
        # iguales, así que CADA actualización volvía a duplicar la temporada en
        # curso. Encontrado con 1.225 juegos repetidos de 2025-26 sobre 7.365
        # filas. Normalizar la clave antes de deduplicar lo arregla y además
        # limpia de una vez el fichero ya existente.
        df['GAME_ID'] = df['GAME_ID'].map(_clave_gid)
        df = df.sort_values('date').drop_duplicates(subset='GAME_ID', keep='last')
        df.to_csv(SALIDA, index=False)
        logger.info(f"[nba] {SALIDA}: {len(df)} juegos "
                    f"({df['date'].min().date()} → {df['date'].max().date()})")
    return df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    actualizar(['2021-22', '2022-23', '2023-24', '2024-25', '2025-26'])
