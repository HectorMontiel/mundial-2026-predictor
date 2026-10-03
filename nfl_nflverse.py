# -*- coding: utf-8 -*-
"""
v325 — EL HISTÓRICO LARGO DE LA NFL (nflverse, 1999 → hoy).

El usuario: «quiero que empieces a mejorar el modelo de la NFL; métele recio
al histórico, quiero que ese modelo quede bastante bien».

Hasta aquí el modelo (`modelo_nfl`) aprendía de `historico_nfl.csv`: 1.143
partidos de ESPN, de la semana 17 de 2022 a hoy. Tres temporadas y media dan
para poco, y además ESPN no dice quién fue el quarterback titular, que en la
NFL es la variable que más mueve un partido. Medido el 2026-10-03: el modelo
acertaba el 63,0 % de los ganadores de 2025 y el favorito de la casa el 66,5 %.

nflverse (https://github.com/nflverse) publica, abiertos y mantenidos al día:

  · `games.csv` — todos los partidos desde 1999 (7.548 hasta la semana 4 de
    2026) con el CIERRE de la casa (hándicap y total siempre; momio desde
    2006), el quarterback titular de cada lado —también el PREVISTO para los
    partidos que faltan—, los días de descanso, el estadio (techo, césped),
    viento, temperatura, entrenador y si es partido de división.
  · `stats_team_week_<temporada>.csv` — la ficha de cada equipo en cada
    partido, con el EPA (puntos esperados añadidos) de pase y de carrera, que
    describe la calidad de un ataque mucho mejor que las yardas.

Este módulo los junta en UNA fila por partido, `historico_nfl_largo.csv`, que
sí va al repositorio: el modelo lo lee sin red y el cron lo refresca.

Uso:
    python nfl_nflverse.py            # refresca la temporada en curso (el cron)
    python nfl_nflverse.py --todo     # descarga las 28 temporadas y reescribe
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

SALIDA = 'historico_nfl_largo.csv'
URL_PARTIDOS = ('https://raw.githubusercontent.com/nflverse/nfldata/master/'
                'data/games.csv')
URL_EQUIPOS = ('https://github.com/nflverse/nflverse-data/releases/download/'
               'stats_team/stats_team_week_{temporada}.csv')
PRIMERA = 1999

# nflverse usa los códigos HISTÓRICOS (OAK, SD, STL) y los de hoy (LV, LAC,
# LA). La franquicia es la misma: el estado de un equipo no se reinicia por
# mudarse. Y `LA` es la abreviatura de nflverse para los Rams, que ESPN y el
# resto del proyecto llaman `LAR`; Washington es `WAS` aquí y `WSH` allí.
FRANQUICIA = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LAR', 'LA': 'LAR',
              'WAS': 'WSH'}

# Lo que se guarda de cada lado, sacado de la ficha de equipo.
_COLS_LADO = ['jugadas', 'dropbacks', 'acarreos', 'epa_pase', 'epa_carrera',
              'perdidas', 'yardas']


def franquicia(codigo) -> str:
    c = str(codigo or '').upper()
    return FRANQUICIA.get(c, c)


def _get(url: str, timeout: int = 120) -> bytes:
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def _ficha(st: pd.DataFrame) -> pd.DataFrame:
    """Una fila por (partido, equipo) con lo que usa el modelo."""
    n = lambda c: pd.to_numeric(st.get(c), errors='coerce').fillna(0.0)
    out = pd.DataFrame({
        'game_id': st['game_id'],
        'team': st['team'].map(franquicia),
        'dropbacks': n('attempts') + n('sacks_suffered'),
        'acarreos': n('carries'),
        'epa_pase': n('passing_epa'),
        'epa_carrera': n('rushing_epa'),
        'perdidas': (n('passing_interceptions') + n('sack_fumbles_lost')
                     + n('rushing_fumbles_lost') + n('receiving_fumbles_lost')),
        'yardas': n('passing_yards') + n('rushing_yards') - n('sack_yards_lost'),
    })
    out['jugadas'] = out['dropbacks'] + out['acarreos']
    return out


def construir(partidos: pd.DataFrame, fichas: pd.DataFrame) -> pd.DataFrame:
    """Une el calendario con las fichas de los dos equipos."""
    g = partidos.copy()
    g['home'] = g['home_team'].map(franquicia)
    g['away'] = g['away_team'].map(franquicia)
    g['tipo'] = g['game_type'].map(lambda t: 'regular' if t == 'REG' else 'playoffs')
    g['neutral'] = g['location'].astype(str).eq('Neutral')
    fi = fichas.drop_duplicates(['game_id', 'team'])
    for lado in ('home', 'away'):
        f = fi.rename(columns={c: '%s_%s' % (lado, c) for c in _COLS_LADO})
        g = g.merge(f.rename(columns={'team': lado}), on=['game_id', lado],
                    how='left')
    cols = (['game_id', 'season', 'tipo', 'week', 'gameday', 'gametime',
             'home', 'away', 'home_score', 'away_score', 'overtime', 'neutral',
             'div_game', 'roof', 'surface', 'temp', 'wind',
             'home_rest', 'away_rest', 'home_qb_id', 'away_qb_id',
             'home_qb_name', 'away_qb_name', 'home_coach', 'away_coach',
             'spread_line', 'total_line', 'home_moneyline', 'away_moneyline',
             'home_spread_odds', 'away_spread_odds', 'over_odds', 'under_odds']
            + ['%s_%s' % (l, c) for l in ('home', 'away') for c in _COLS_LADO])
    g = g[[c for c in cols if c in g.columns]]
    return g.sort_values(['gameday', 'gametime', 'game_id']).reset_index(drop=True)


def descargar(temporadas: Optional[List[int]] = None) -> pd.DataFrame:
    partidos = pd.read_csv(io.BytesIO(_get(URL_PARTIDOS)), low_memory=False)
    ult = int(partidos['season'].max())
    temporadas = temporadas or list(range(PRIMERA, ult + 1))
    fichas = []
    for t in temporadas:
        try:
            st = pd.read_csv(io.BytesIO(_get(URL_EQUIPOS.format(temporada=t))),
                             low_memory=False)
            fichas.append(_ficha(st))
        except Exception as e:
            # la temporada en curso puede no tener fichas aún (pretemporada)
            logger.warning('[nflverse] fichas de %s: %s', t, e)
    fichas = pd.concat(fichas, ignore_index=True) if fichas else pd.DataFrame(
        columns=['game_id', 'team'] + _COLS_LADO)
    return construir(partidos, fichas)


def actualizar(temporada: Optional[int] = None, ruta: str = SALIDA) -> int:
    """Reescribe el histórico; con `temporada`, sólo baja las fichas de esa y
    conserva las de las anteriores. Devuelve el número de partidos."""
    if temporada is not None and os.path.exists(ruta):
        viejo = pd.read_csv(ruta, low_memory=False)
        nuevo = descargar([temporada])
        # el calendario entero viene siempre nuevo; las fichas de las
        # temporadas que no se bajaron se toman del fichero anterior
        lados = [c for c in viejo.columns
                 if c.startswith(('home_', 'away_')) and c.split('_', 1)[1] in _COLS_LADO]
        prev = viejo[viejo['season'] != temporada][['game_id'] + lados]
        nuevo = nuevo.set_index('game_id')
        prev = prev.set_index('game_id')
        nuevo.update(prev, overwrite=False)
        d = nuevo.reset_index()
    else:
        d = descargar()
    tmp = ruta + '.tmp'
    d.to_csv(tmp, index=False)
    os.replace(tmp, ruta)
    return len(d)


def cargar(ruta: str = SALIDA) -> Optional[pd.DataFrame]:
    if not os.path.exists(ruta):
        return None
    d = pd.read_csv(ruta, low_memory=False)
    d['gameday'] = pd.to_datetime(d['gameday'], errors='coerce')
    return d


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--temporada', type=int)
    ap.add_argument('--todo', action='store_true')
    a = ap.parse_args()
    t = a.temporada
    if t is None and not a.todo and os.path.exists(SALIDA):
        # lo normal en el cron: sólo cambian la temporada en curso (marcadores,
        # fichas y el QB previsto de los que faltan) y el calendario
        t = int(pd.read_csv(SALIDA, usecols=['season'])['season'].max())
    n = actualizar(None if a.todo else t)
    print('historico_nfl_largo.csv: %d partidos' % n)
