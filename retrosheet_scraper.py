#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrosheet MLB game logs (v29 §4.1) — histórico gratuito y legal.

Descarga gl{año}.zip de retrosheet.org (un CSV por temporada, 161 campos) y
lo reduce a lo útil pre-partido: fecha, equipos, marcador y LANZADOR ABRIDOR
de cada lado (la variable más crítica del béisbol, §4.2). Caché commiteable
en historico_mlb.csv (incremental por temporada).

Campos del game log usados (posición 0-indexada, spec Retrosheet):
  0 fecha · 3 visitante · 6 local · 9 carreras_vis · 10 carreras_local
  101 id_pitcher_vis · 103 id_pitcher_local
"""

import io
import logging
import os
import zipfile
from typing import List

import pandas as pd
import requests

logger = logging.getLogger(__name__)

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
BASE = 'https://www.retrosheet.org/gamelogs'
SALIDA = 'historico_mlb.csv'
# posiciones en el game log
F_FECHA, F_VIS, F_HOME, F_VSC, F_HSC = 0, 3, 6, 9, 10
F_PIT_VIS, F_PIT_HOME = 101, 103


def descargar_temporada(anio: int) -> pd.DataFrame:
    r = requests.get(f'{BASE}/gl{anio}.zip', headers=UA, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    txt = z.read(z.namelist()[0]).decode('latin-1').splitlines()
    filas = []
    for linea in txt:
        c = [x.strip('"') for x in linea.split(',')]
        if len(c) <= F_PIT_HOME:
            continue
        try:
            filas.append({
                'date': pd.to_datetime(c[F_FECHA], format='%Y%m%d'),
                'home_team': c[F_HOME], 'away_team': c[F_VIS],
                'home_runs': int(c[F_HSC]), 'away_runs': int(c[F_VSC]),
                'home_pitcher': c[F_PIT_HOME], 'away_pitcher': c[F_PIT_VIS],
            })
        except (ValueError, IndexError):
            continue
    df = pd.DataFrame(filas)
    logger.info(f"[mlb] {anio}: {len(df)} juegos")
    return df


def actualizar(anios: List[int]) -> pd.DataFrame:
    """Consolida las temporadas pedidas (las ya presentes no se re-descargan
    salvo la más reciente, que puede estar en curso)."""
    existente = pd.read_csv(SALIDA, parse_dates=['date']) \
        if os.path.exists(SALIDA) else pd.DataFrame()
    presentes = set(existente['date'].dt.year.unique()) if not existente.empty else set()
    frames = [existente] if not existente.empty else []
    reciente = max(anios)
    for a in anios:
        if a in presentes and a != reciente:
            continue
        if not existente.empty:      # evita duplicar la temporada reciente
            frames[0] = frames[0][frames[0]['date'].dt.year != a]
        try:
            frames.append(descargar_temporada(a))
        except Exception as e:
            logger.warning(f"[mlb] {a} no disponible: {e}")
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df = df.sort_values('date').drop_duplicates(
            subset=['date', 'home_team', 'away_team'], keep='last')
        df.to_csv(SALIDA, index=False)
        logger.info(f"[mlb] {SALIDA}: {len(df)} juegos "
                    f"({df['date'].min().date()} → {df['date'].max().date()})")
    return df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import datetime
    hoy = datetime.date.today().year
    actualizar(list(range(hoy - 5, hoy + 1)))
