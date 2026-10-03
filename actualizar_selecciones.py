#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v323 — EL MOTOR DE SELECCIONES, AL DÍA.

QUÉ PASABA
El motor de selecciones (`prediction_api.PredictionEngine`, el que pronostica
Nations League, amistosos y eliminatorias en «Apuestas del Día» y en
«Partidos Internacionales») lee el estado de cada equipo de `team_stats.json`,
y ese estado sale de `historico_partidos.csv`. Los dos llevaban congelados en
el **2026-07-15**: la base pública de la que salen (Kaggle / martj42) va con
semanas de retraso y ningún workflow los regeneraba. Mientras tanto
`historico_selecciones.csv` (ESPN, lo actualiza `precalculo_dia.yml`) ya tenía
los resultados hasta hoy, pero el motor no los veía.

LO QUE SE MIDIÓ ANTES DE CAMBIAR NADA (2026-10-03, `_v323_selecciones.py` y
`_v323_selecciones_analisis.py`)
Replay partido a partido desde 2024-01-01 —el clasificador se entrenó con lo
anterior, así que todo es fuera de muestra— con la misma maquinaria que
`predecir` y el estado del equipo justo antes de cada partido:

    146 partidos del 2026-07-16 al 2026-10-03     acierto   log-loss
      estado congelado (lo de producción)          55,5 %    1,0171
      estado al día (esto)                          55,5 %    0,9884
      mejora de log-loss 0,0288 (p5 0,0153, p95 0,0440)

Y la recalibración que parecía hacer falta («dice 73 %, acierta 66 %») NO se
adopta: en 931 partidos de 2025-07 a 2026-07, con el estado al día, el motor
no se pasa de confiado (dice 65 → acierta 70; dice 82 → 85) y una temperatura
ajustada con lo anterior EMPEORA el log-loss (−0,0023, p95 −0,0008). La brecha
de octubre salía de 11 partidos; por trimestre oscila entre −8 y +7 puntos.

QUÉ HACE
1. Toma de `historico_selecciones.csv` los partidos POSTERIORES al último de
   `historico_partidos.csv`, sólo absolutas masculinas (la misma regla que
   `selecciones_dia`), con los nombres pasados al código del motor.
2. Les pone `elo_diff` y las métricas del generador correlacionado igual que
   `data_fetcher.build_unified_history` (las mismas con las que se entrenó),
   y los añade al histórico.
3. Regenera `team_stats.json` con `update_team_stats.build_team_stats`.

Nunca quita filas: sólo añade las que faltan, y nunca toca lo anterior.

Uso:
    python actualizar_selecciones.py            # añade y regenera el estado
    python actualizar_selecciones.py --ver      # sólo dice qué añadiría
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger('actualizar_selecciones')

ESPN = 'historico_selecciones.csv'


def _catalogo() -> Dict[str, str]:
    """{nombre (inglés, alias, español): código}. El de `selecciones_dia`,
    construido desde `config` para no cargar el modelo (436 MB) en el cron."""
    from config import TEAMS, TEAM_NAMES_EN, TEAM_ALIAS, NAME_EN_TO_FIFA
    from prediction_api import NOMBRES_PAIS
    cat: Dict[str, str] = {}
    for c in TEAMS:
        cat[TEAM_NAMES_EN.get(c, c)] = c
        for al in TEAM_ALIAS.get(c, []):
            cat.setdefault(al, c)
        cat.setdefault(NOMBRES_PAIS.get(c, c), c)
    for nombre, c in NAME_EN_TO_FIFA.items():
        cat.setdefault(nombre, c)
    return cat


def _elo_diff(df: pd.DataFrame) -> np.ndarray:
    """`data_fetcher.compute_elo_series` sin escribir `elo_actual.csv`."""
    elo: Dict[str, float] = {}
    diffs = np.zeros(len(df))
    for i, f in enumerate(df.itertuples(index=False)):
        h, a = f.home_team, f.away_team
        rh, ra = elo.get(h, 1500.0), elo.get(a, 1500.0)
        diffs[i] = rh - ra
        eh = 1 / (1 + 10 ** ((ra - rh) / 400))
        sh = (1.0 if f.home_goals > f.away_goals
              else (0.5 if f.home_goals == f.away_goals else 0.0))
        k = (48 if 'World Cup' in str(f.tournament)
             else (20 if 'Friendly' in str(f.tournament) else 32))
        elo[h] = rh + k * (sh - eh)
        elo[a] = ra + k * ((1 - sh) - (1 - eh))
    return diffs


def nuevos(historico: pd.DataFrame, espn: pd.DataFrame) -> pd.DataFrame:
    """Las filas que faltan, ya con el formato de `historico_partidos.csv`."""
    import selecciones_dia as sd
    hist = historico.copy()
    hist['date'] = pd.to_datetime(hist['date'])
    e = espn.copy()
    e['date'] = pd.to_datetime(e['date'])
    e = e[e['date'] > hist['date'].max()].dropna(
        subset=['home_goals', 'away_goals'])
    cat = _catalogo()
    filas = []
    for _, r in e.iterrows():
        if not sd._es_absoluta({'home': r.home_team, 'away': r.away_team,
                                'torneo': r.tournament}):
            continue
        h = cat.get(r.home_team) or r.home_team
        a = cat.get(r.away_team) or r.away_team
        filas.append({
            'MATCH_ID': '%s_%s_%s' % (r.date.strftime('%Y%m%d'),
                                      str(h).replace(' ', '-'),
                                      str(a).replace(' ', '-')),
            'date': r.date, 'home_team': h, 'away_team': a,
            'home_goals': float(r.home_goals), 'away_goals': float(r.away_goals),
            'tournament': r.tournament, 'city': None, 'country': None,
            'neutral': str(r.neutral).strip().lower() == 'true',
            'stadium': None})
    if not filas:
        return pd.DataFrame(columns=historico.columns)
    n = pd.DataFrame(filas).drop_duplicates('MATCH_ID')
    n = n[~n['MATCH_ID'].isin(set(hist['MATCH_ID']))]
    if n.empty:
        return pd.DataFrame(columns=historico.columns)
    todo = pd.concat([hist, n], ignore_index=True).sort_values(
        ['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)
    todo['elo_diff'] = _elo_diff(todo)
    marca = todo['MATCH_ID'].isin(set(n['MATCH_ID']))
    import statsbomb_calibration
    from correlated_synthetic_generator import CorrelatedSyntheticGenerator
    nuevas = CorrelatedSyntheticGenerator().generate_advanced_metrics(
        todo[marca].reset_index(drop=True), statsbomb_calibration.calibrar())
    for c in historico.columns:
        if c not in nuevas.columns:
            nuevas[c] = np.nan
    nuevas = nuevas[list(historico.columns)]
    nuevas['date'] = pd.to_datetime(nuevas['date']).dt.strftime('%Y-%m-%d')
    return nuevas


def actualizar(ruta_hist: str = None, ver: bool = False) -> int:
    """Añade lo que falta y regenera `team_stats.json`. Devuelve cuántos."""
    from config import HISTORICO_FILE
    ruta_hist = ruta_hist or HISTORICO_FILE
    historico = pd.read_csv(ruta_hist)
    if not os.path.exists(ESPN):
        logger.warning('no hay %s: nada que añadir', ESPN)
        return 0
    n = nuevos(historico, pd.read_csv(ESPN))
    logger.info('%d partidos de selecciones nuevos para el motor (último del '
                'histórico: %s)', len(n), historico['date'].max())
    if ver or n.empty:
        return len(n)
    # Se AÑADEN líneas al final y no se reescribe el fichero: reescribirlo
    # entero con pandas cambiaba el formato de las 32.400 filas viejas
    # (`5` pasaba a `5.0`) aunque sus valores fueran los mismos. Se copia
    # aparte, se añade y se mueve encima: o está el de antes o el nuevo.
    import shutil
    tmp = ruta_hist + '.nuevo'
    shutil.copyfile(ruta_hist, tmp)
    with open(tmp, 'rb+') as f:
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b'\n':
                f.write(b'\n')
    with open(tmp, 'a', encoding='utf-8', newline='') as f:
        n.to_csv(f, header=False, index=False, lineterminator='\n')
    os.replace(tmp, ruta_hist)
    import update_team_stats
    update_team_stats.build_team_stats()
    return len(n)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--ver', action='store_true')
    a = ap.parse_args()
    print('añadidos: %d' % actualizar(ver=a.ver))
    return 0


if __name__ == '__main__':
    sys.exit(main())
