#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora F — NBA: fatiga, viajes y estadística avanzada.

Qué añade sobre lo que ya tenía `NBAEngine`
-------------------------------------------
El motor de v29 ya llevaba `DIFF_REST`, `DIFF_B2B`, `DIFF_STREAK`, los ratings
ofensivo/defensivo y el `pace`. Este módulo aporta lo que faltaba del spec §7.6,
todo rolling y sin fuga:

FATIGA (de las fechas, sin fuente nueva)
  · `juegos_5d` / `juegos_7d` — densidad de calendario real, que es lo que
    distingue un back-to-back aislado de la cuarta noche en seis días.
  · `tres_en_cuatro` — el patrón clásico que la NBA vigila en su calendario.
  · `dias_de_viaje` — noches consecutivas fuera de casa (road trip).

VIAJES
  · `millas_viaje` — haversine entre el pabellón anterior y el actual, con el
    diccionario de coordenadas de los 30 pabellones (`ARENAS`).
  · `cruces_huso` — husos horarios cruzados desde el partido anterior.

AVANZADAS (de `leaguegamelog`, medias móviles de 5 y 10)
  · `efg` (tiro efectivo), `tov_pct`, `oreb_pct`, `ast_ratio`, `ft_rate`.

Sobre las LESIONES (transparencia, regla §2.9)
----------------------------------------------
El spec pide `missing_starters` y `missing_win_shares`. Medido en la Fase 1 de
v70: `nba_api` y ESPN publican el parte de lesiones **del día**, y ninguno de los
dos lo ARCHIVA. Un backtest necesita saber quién estaba lesionado el 14 de
noviembre de 2023, y ese dato no es recuperable de una fuente gratuita: los
partes históricos están en servicios de pago. Reconstruirlo por ausencia en el
boxscore confunde tres cosas distintas —lesión, descanso y decisión técnica— y
además introduce fuga, porque quién jugó se sabe DESPUÉS del partido.

Lo que sí es honesto y es lo que se implementa: `titulares_ausentes_en_vivo()`
consulta el parte del día para el uso EN PRODUCCIÓN (donde sí está disponible a
tiempo), y las features de lesión quedan fuera del entrenamiento. Se documenta
como pendiente en vez de fabricar un backtest que no significaría nada.
"""
import json
import logging
import math
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MA_CORTA, MA_LARGA = 5, 10

# Coordenadas de los 30 pabellones (lat, lon) + huso horario (offset UTC
# estándar). Usadas para las millas de viaje y el cruce de husos.
ARENAS: Dict[str, tuple] = {
    'ATL': (33.7573, -84.3963, -5), 'BOS': (42.3662, -71.0621, -5),
    'BKN': (40.6826, -73.9754, -5), 'CHA': (35.2251, -80.8392, -5),
    'CHI': (41.8807, -87.6742, -6), 'CLE': (41.4965, -81.6882, -5),
    'DAL': (32.7905, -96.8103, -6), 'DEN': (39.7487, -105.0077, -7),
    'DET': (42.3410, -83.0550, -5), 'GSW': (37.7680, -122.3877, -8),
    'HOU': (29.7508, -95.3621, -6), 'IND': (39.7640, -86.1555, -5),
    'LAC': (33.9451, -118.2671, -8), 'LAL': (34.0430, -118.2673, -8),
    'MEM': (35.1382, -90.0505, -6), 'MIA': (25.7814, -80.1870, -5),
    'MIL': (43.0451, -87.9172, -6), 'MIN': (44.9795, -93.2760, -6),
    'NOP': (29.9490, -90.0821, -6), 'NYK': (40.7505, -73.9934, -5),
    'OKC': (35.4634, -97.5151, -6), 'ORL': (28.5392, -81.3839, -5),
    'PHI': (39.9012, -75.1720, -5), 'PHX': (33.4457, -112.0712, -7),
    'POR': (45.5316, -122.6668, -8), 'SAC': (38.5802, -121.4997, -8),
    'SAS': (29.4270, -98.4375, -6), 'TOR': (43.6435, -79.3791, -5),
    'UTA': (40.7683, -111.9011, -7), 'WAS': (38.8981, -77.0209, -5),
}


def haversine_millas(a: str, b: str) -> float:
    """Distancia en millas entre dos pabellones (0 si alguno no está)."""
    if a == b or a not in ARENAS or b not in ARENAS:
        return 0.0
    lat1, lon1, _ = ARENAS[a]
    lat2, lon2, _ = ARENAS[b]
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _huso(equipo: str) -> int:
    return ARENAS.get(equipo, (0, 0, -5))[2]


def _clave_partido(gid) -> str:
    """
    Normaliza el GAME_ID entre las dos fuentes.

    `historico_nba.csv` lo guarda como entero (22100002) y `leaguegamelog` como
    cadena con ceros a la izquierda ('0022100002'). Sin normalizar, el cruce
    daba 0 % de cobertura en las avanzadas — medido en v70, no supuesto.
    """
    return str(gid).strip().lstrip('0') or '0'


# ---------------------------------------------------------------------------
# Estadística avanzada por equipo-partido (nba_api)
# ---------------------------------------------------------------------------
CACHE_AVANZADAS = 'nba_avanzadas.csv.gz'


def descargar_avanzadas(seasons: List[str], forzar: bool = False) -> pd.DataFrame:
    """
    Una fila por equipo-partido con las avanzadas derivadas del boxscore
    tradicional de `leaguegamelog` (que sí trae FGM/FGA/FG3M/AST/TOV/OREB).

        efg      = (FGM + 0.5·FG3M) / FGA
        tov_pct  = TOV / (FGA + 0.44·FTA + TOV)
        ast_ratio= AST / (FGA + 0.44·FTA + AST + TOV)
        ft_rate  = FTA / FGA
        oreb     = OREB por partido (el % exige los rebotes del rival, que se
                   reconstruyen abajo al emparejar por GAME_ID)
    """
    if os.path.exists(CACHE_AVANZADAS) and not forzar:
        return pd.read_csv(CACHE_AVANZADAS, parse_dates=['date'])
    from nba_api.stats.endpoints import leaguegamelog
    marcos = []
    for s in seasons:
        try:
            d = leaguegamelog.LeagueGameLog(season=s, timeout=60).get_data_frames()[0]
            marcos.append(d)
            logger.info(f"[nba-adv] {s}: {len(d)} filas")
        except Exception as e:
            logger.warning(f"[nba-adv] {s} falló: {type(e).__name__}: {e}")
    if not marcos:
        return pd.DataFrame()
    d = pd.concat(marcos, ignore_index=True)
    d = d.rename(columns={'TEAM_ABBREVIATION': 'equipo', 'GAME_DATE': 'date'})
    d['date'] = pd.to_datetime(d['date'])
    for c in ('FGM', 'FGA', 'FG3M', 'FTA', 'AST', 'TOV', 'OREB', 'DREB', 'PTS'):
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0)
    pos = d['FGA'] + 0.44 * d['FTA'] + d['TOV']
    d['efg'] = np.where(d['FGA'] > 0, (d['FGM'] + 0.5 * d['FG3M']) / d['FGA'], 0.5)
    d['tov_pct'] = np.where(pos > 0, d['TOV'] / pos, 0.13)
    d['ast_ratio'] = np.where((pos + d['AST']) > 0,
                              d['AST'] / (d['FGA'] + 0.44 * d['FTA'] + d['AST'] + d['TOV']),
                              0.17)
    d['ft_rate'] = np.where(d['FGA'] > 0, d['FTA'] / d['FGA'], 0.22)
    # OREB% real: rebotes ofensivos propios / (propios + defensivos del rival)
    reb = d[['GAME_ID', 'equipo', 'OREB', 'DREB']].copy()
    riv = reb.merge(reb, on='GAME_ID', suffixes=('', '_riv'))
    riv = riv[riv['equipo'] != riv['equipo_riv']]
    riv['oreb_pct'] = np.where((riv['OREB'] + riv['DREB_riv']) > 0,
                               riv['OREB'] / (riv['OREB'] + riv['DREB_riv']), 0.27)
    d = d.merge(riv[['GAME_ID', 'equipo', 'oreb_pct']], on=['GAME_ID', 'equipo'],
                how='left')
    salida = d[['GAME_ID', 'date', 'equipo', 'efg', 'tov_pct', 'ast_ratio',
                'ft_rate', 'oreb_pct']].copy()
    salida.to_csv(CACHE_AVANZADAS, index=False, compression='gzip')
    logger.info(f"[nba-adv] guardado {CACHE_AVANZADAS}: {len(salida)} filas")
    return salida


# ---------------------------------------------------------------------------
# Features de fatiga y viaje, sin fuga
# ---------------------------------------------------------------------------
COLS_FATIGA = ['DIFF_J5D', 'DIFF_J7D', 'DIFF_3EN4', 'DIFF_VIAJE_MI',
               'DIFF_HUSOS', 'DIFF_ROADTRIP']
COLS_AVANZADAS = ['DIFF_EFG', 'DIFF_TOV', 'DIFF_AST_RATIO', 'DIFF_OREB',
                  'DIFF_FT_RATE']
COLS_V70 = COLS_FATIGA + COLS_AVANZADAS


def construir_features(df: pd.DataFrame,
                       avanzadas: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Devuelve un dataframe indexado por GAME_ID con las columnas `COLS_V70`.

    Todas se calculan con partidos ESTRICTAMENTE anteriores: el estado se
    actualiza después de emitir la fila, igual que en `NBAEngine._dataset`.
    """
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])

    avz: Dict[str, Dict[str, list]] = {}
    if avanzadas is not None and len(avanzadas):
        avanzadas = avanzadas.copy()
        avanzadas['GAME_ID'] = avanzadas['GAME_ID'].map(_clave_partido)
        idx_avz = {(r.GAME_ID, r.equipo): r for r in avanzadas.itertuples(index=False)}
    else:
        idx_avz = {}

    fechas_eq: Dict[str, List[pd.Timestamp]] = {}
    ult_sede: Dict[str, str] = {}
    noches_fuera: Dict[str, int] = {}
    filas = []

    def _n_ultimos(eq, fecha, dias):
        v = fechas_eq.get(eq, [])
        lim = fecha - pd.Timedelta(days=dias)
        return sum(1 for f in v if lim <= f < fecha)

    def _ma(eq, campo, n):
        v = avz.get(eq, {}).get(campo, [])
        return float(np.mean(v[-n:])) if v else np.nan

    for r in df.itertuples(index=False):
        h, a = r.home_team, r.away_team
        gid = _clave_partido(r.GAME_ID)
        f = r.date
        vals = {}
        for lado, eq, sede in (('h', h, h), ('a', a, h)):
            j5 = _n_ultimos(eq, f, 5)
            j7 = _n_ultimos(eq, f, 7)
            # 3 partidos en 4 noches: 2 previos en los últimos 3 días + este
            tres4 = 1.0 if _n_ultimos(eq, f, 3) >= 2 else 0.0
            prev = ult_sede.get(eq)
            millas = haversine_millas(prev, sede) if prev else 0.0
            husos = abs(_huso(prev) - _huso(sede)) if prev else 0
            vals[lado] = {'j5': j5, 'j7': j7, 'tres4': tres4, 'millas': millas,
                          'husos': husos, 'road': noches_fuera.get(eq, 0)}

        fila = {'GAME_ID': gid,
                'DIFF_J5D': (vals['h']['j5'] - vals['a']['j5']) / 3.0,
                'DIFF_J7D': (vals['h']['j7'] - vals['a']['j7']) / 4.0,
                'DIFF_3EN4': vals['h']['tres4'] - vals['a']['tres4'],
                'DIFF_VIAJE_MI': (vals['h']['millas'] - vals['a']['millas']) / 1500.0,
                'DIFF_HUSOS': (vals['h']['husos'] - vals['a']['husos']) / 3.0,
                'DIFF_ROADTRIP': (vals['h']['road'] - vals['a']['road']) / 5.0}
        for col, campo in (('DIFF_EFG', 'efg'), ('DIFF_TOV', 'tov_pct'),
                           ('DIFF_AST_RATIO', 'ast_ratio'),
                           ('DIFF_OREB', 'oreb_pct'), ('DIFF_FT_RATE', 'ft_rate')):
            vh, va = _ma(h, campo, MA_LARGA), _ma(a, campo, MA_LARGA)
            fila[col] = (vh - va) * 10.0 if np.isfinite(vh) and np.isfinite(va) else np.nan
        filas.append(fila)

        # --- actualizar estado DESPUÉS de emitir
        for eq in (h, a):
            fechas_eq.setdefault(eq, []).append(f)
            fechas_eq[eq] = fechas_eq[eq][-15:]
            reg = idx_avz.get((gid, eq))
            if reg is not None:
                for campo in ('efg', 'tov_pct', 'ast_ratio', 'oreb_pct', 'ft_rate'):
                    v = getattr(reg, campo, np.nan)
                    if pd.notna(v):
                        avz.setdefault(eq, {}).setdefault(campo, []).append(float(v))
                        avz[eq][campo] = avz[eq][campo][-MA_LARGA:]
        noches_fuera[h] = 0
        noches_fuera[a] = noches_fuera.get(a, 0) + 1
        ult_sede[h] = ult_sede[a] = h

    return pd.DataFrame(filas).set_index('GAME_ID')


def titulares_ausentes_en_vivo(equipo: str) -> Optional[dict]:
    """
    Parte de lesiones DEL DÍA para producción (no sirve para backtesting: ver
    la nota de transparencia de la cabecera del módulo).
    """
    import requests
    try:
        r = requests.get(
            'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries',
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        r.raise_for_status()
        for eq in r.json().get('injuries', []):
            abbr = (eq.get('team') or {}).get('abbreviation')
            if abbr != equipo:
                continue
            fuera = [i for i in eq.get('injuries', [])
                     if (i.get('status') or '').lower() in ('out', 'doubtful')]
            return {'equipo': equipo, 'bajas': len(fuera),
                    'jugadores': [(i.get('athlete') or {}).get('displayName')
                                  for i in fuera]}
    except Exception as e:
        logger.debug(f"[nba-lesiones] {type(e).__name__}: {e}")
    return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    d = pd.read_csv('historico_nba.csv', parse_dates=['date'])
    adv = descargar_avanzadas(['2021-22', '2022-23', '2023-24', '2024-25', '2025-26'])
    f = construir_features(d, adv)
    print(f.describe().T.to_string())
    print(f"\ncobertura de avanzadas: "
          f"{f['DIFF_EFG'].notna().mean()*100:.1f} %")
