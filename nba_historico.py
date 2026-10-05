# -*- coding: utf-8 -*-
"""
v330 — EL HISTÓRICO LARGO DE LA NBA (2007-08 → hoy), CON EL CIERRE DE LA CASA.

El usuario: «las pretemporadas de la NBA van a empezar; trae muchos datos de
NBA y haz un modelo muy avanzado y preciso… la validación con simulaciones
de partidos finalizados de las últimas temporadas».

Hasta aquí el motor de la NBA (`engines/nba_engine.py`) aprendía de
`historico_nba.csv`: 6.140 partidos de nba_api (2021-22 → 2025-26) y SIN
cuotas, así que no se podía saber si el modelo le ganaba o no a la casa ni
medir qué se puede «meter».

`OddsData.sqlite` del proyecto abierto kyleskom/NBA-Machine-Learning-Sports-
Betting trae, partido a partido, el marcador y el CIERRE (moneyline,
hándicap y total) de 2007-08 a 2025-26 (ésta hasta el 7 de enero de 2026):
unas 23.000 partidas. Se junta con `historico_nba.csv`, que el cron diario
(`retrain_leagues.yml`) mantiene al día con nba_api, para que el estado de
los equipos llegue hasta el último partido jugado aunque no tenga cuota.

Una fila por partido en `historico_nba_largo.csv`, con los códigos de tres
letras que usa el resto del proyecto.

Uso: python nba_historico.py
"""
from __future__ import annotations

import io
import logging
import os
import sqlite3
import sys
import tempfile
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SALIDA = 'historico_nba_largo.csv'
URL_CUOTAS = ('https://raw.githubusercontent.com/kyleskom/'
              'NBA-Machine-Learning-Sports-Betting/master/Data/OddsData.sqlite')

# Nombre largo → código (franquicia de hoy: los Nets de New Jersey son BKN,
# los SuperSonics OKC, los Bobcats CHA).
EQUIPOS = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
    'New Jersey Nets': 'BKN', 'Charlotte Bobcats': 'CHA',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI',
    'Cleveland Cavaliers': 'CLE', 'Dallas Mavericks': 'DAL',
    'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU',
    'Indiana Pacers': 'IND', 'LA Clippers': 'LAC',
    'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL',
    'Memphis Grizzlies': 'MEM', 'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL',
    'Minnesota Timberwolves': 'MIN', 'New Orleans Pelicans': 'NOP',
    'New Orleans Hornets': 'NOP', 'New York Knicks': 'NYK',
    'Oklahoma City Thunder': 'OKC', 'Seattle SuperSonics': 'OKC',
    'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
    'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC',
    'San Antonio Spurs': 'SAS', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA',
    'Washington Wizards': 'WAS',
}
CODIGOS = sorted(set(EQUIPOS.values()))


# Apodo → código, para los nombres cortos de las casas («Lakers», «LA
# Clippers», «Portland Trail Blazers»). «Hornets» es Charlotte (los de Nueva
# Orleans lo fueron hasta 2013 y ya no juegan con ese nombre).
APODOS = {}
for _largo, _c in EQUIPOS.items():
    if _largo != 'New Orleans Hornets':
        APODOS.setdefault(_largo.split()[-1].lower(), _c)


# abreviaturas de ciudad que usan las casas
_CIUDAD = {'la': 'los', 'ny': 'new', 'okc': 'oklahoma', 'gs': 'golden',
           'sa': 'san', 'no': 'new', 'nueva': 'new'}


# el nombre de HOY de cada franquicia, para enseñar
_LARGO = {c: l for l, c in EQUIPOS.items()
          if l not in ('New Jersey Nets', 'Charlotte Bobcats', 'Seattle SuperSonics',
                       'New Orleans Hornets', 'Los Angeles Clippers')}


def nombre_largo(c: str) -> str:
    return _LARGO.get(str(c or '').upper(), str(c or ''))


# abreviaturas de equipo que no son el código de tres letras del proyecto
_ABREV = {'NY': 'NYK', 'GS': 'GSW', 'SA': 'SAS', 'NO': 'NOP', 'NOR': 'NOP',
          'UTAH': 'UTA', 'WSH': 'WAS', 'PHO': 'PHX', 'BRK': 'BKN', 'BKL': 'BKN',
          'CHO': 'CHA', 'NJ': 'BKN', 'LA': None}


def codigo(nombre) -> Optional[str]:
    """Nombre (de la casa que sea) o código → código de tres letras."""
    n = str(nombre or '').strip()
    if n.upper() in CODIGOS:
        return n.upper()
    if n in EQUIPOS:
        return EQUIPOS[n]
    partes = n.lower().replace('.', '').split()
    if not partes:
        return None
    c = APODOS.get(partes[-1])
    if c is None or len(partes) == 1:
        return c
    # con ciudad, la ciudad tiene que ser la del equipo: «Sydney Kings» o
    # «Perth Wildcats» juegan la pretemporada y NO son los Kings de Sacramento
    # o la abreviatura del equipo delante: «PHI 76ers», «NY Knicks» (Playdoit)
    if _ABREV.get(partes[0].upper(), partes[0].upper()) == c:
        return c
    ciudad = _CIUDAD.get(partes[0], partes[0])
    for largo, cc in EQUIPOS.items():
        if cc == c and largo.lower().split()[0] == ciudad:
            return c
    return None


def _temporada(fecha: pd.Timestamp) -> int:
    """El año en que EMPIEZA la temporada (2024-25 → 2024). Empiezan en
    octubre (2011-12 y 2020-21, en diciembre); la «burbuja» de 2019-20 acabó
    en octubre de 2020 y es de 2019."""
    if fecha.year == 2020 and fecha.month == 10:
        return 2019
    return fecha.year if fecha.month >= 10 else fecha.year - 1


def _tablas(ruta: str) -> pd.DataFrame:
    con = sqlite3.connect(ruta)
    nombres = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table'")]
    usar = []
    for n in nombres:
        # las temporadas viejas en su versión «_new» (fechas ISO); 2023-24 en
        # la tabla SIN prefijo: la «odds_2023-24_new» trae marcadores rotos
        # (53 puntos en un partido de playoffs)
        if n.startswith('odds_') and n.endswith('_new') and '2023-24' not in n:
            usar.append(n)
        elif n in ('2023-24', '2024-25') or (n.startswith('odds_20') and
                                              not n.endswith('_new') and
                                              int(n[5:9]) >= 2025):
            usar.append(n)
    partes = []
    for n in usar:
        d = pd.read_sql('select * from "%s"' % n, con)
        d['tabla'] = n
        partes.append(d)
    con.close()
    return pd.concat(partes, ignore_index=True)


def de_cuotas(ruta: str) -> pd.DataFrame:
    d = _tablas(ruta)
    d['fecha'] = pd.to_datetime(d['Date'], errors='coerce')
    d = d.dropna(subset=['fecha'])
    d['home'] = d['Home'].map(codigo)
    d['away'] = d['Away'].map(codigo)
    d = d.dropna(subset=['home', 'away'])
    tot = pd.to_numeric(d['Points'], errors='coerce')
    mar = pd.to_numeric(d['Win_Margin'], errors='coerce')
    mlh = pd.to_numeric(d['ML_Home'], errors='coerce')
    mla = pd.to_numeric(d['ML_Away'], errors='coerce')
    out = pd.DataFrame({
        'fecha': d['fecha'].dt.strftime('%Y-%m-%d'),
        'temporada': d['fecha'].map(_temporada),
        'home': d['home'], 'away': d['away'],
        'home_pts': (tot + mar) / 2.0, 'away_pts': (tot - mar) / 2.0,
        'ml_home': mlh, 'ml_away': mla,
        # la base trae el hándicap SIN signo (el del favorito); el signo sale
        # de la moneyline: «spread» queda como el margen que la casa espera
        # para el LOCAL (+6 = el local favorito por 6)
        'spread': pd.to_numeric(d['Spread'], errors='coerce').abs() * np.where(
            mlh <= mla, 1.0, np.where(mlh > mla, -1.0, np.nan)),
        'total_linea': pd.to_numeric(d['OU'], errors='coerce'),
        'fuente': 'cuotas'})
    # marcadores imposibles fuera (una tabla con un partido a 53 puntos)
    ok = (out['home_pts'] + out['away_pts'] >= 120) & (out['home_pts'] >= 50) \
        & (out['away_pts'] >= 50)
    out = out[ok].copy()
    # y las LÍNEAS imposibles a vacío (el partido se queda): hay totales de
    # 1.955 puntos y hándicaps de 216 en la base. Un total de cierre fuera de
    # 150-280, un hándicap de más de 25 o una moneyline cuyo libro no suma
    # entre 1,00 y 1,15 no son el cierre de nadie.
    out.loc[~out['total_linea'].between(150, 280), 'total_linea'] = np.nan
    out.loc[out['spread'].abs() > 25, 'spread'] = np.nan
    oh = np.where(out['ml_home'] > 0, 1 + out['ml_home'] / 100, 1 + 100 / out['ml_home'].abs())
    oa = np.where(out['ml_away'] > 0, 1 + out['ml_away'] / 100, 1 + 100 / out['ml_away'].abs())
    libro = 1 / oh + 1 / oa
    malo = ~((libro >= 1.0) & (libro <= 1.15))
    out.loc[malo, ['ml_home', 'ml_away']] = np.nan
    return out.drop_duplicates(['fecha', 'home', 'away'])


def de_nba_api(ruta: str = 'historico_nba.csv') -> pd.DataFrame:
    if not os.path.exists(ruta):
        return pd.DataFrame()
    h = pd.read_csv(ruta)
    f = pd.to_datetime(h['date'], errors='coerce')
    return pd.DataFrame({
        'fecha': f.dt.strftime('%Y-%m-%d'), 'temporada': f.map(_temporada),
        'home': h['home_team'].map(codigo), 'away': h['away_team'].map(codigo),
        'home_pts': h['home_pts'], 'away_pts': h['away_pts'],
        'home_poss': h.get('home_poss'), 'away_poss': h.get('away_poss'),
        'fuente': 'nba_api'}).dropna(subset=['home', 'away', 'fecha'])


def construir(ruta_cuotas: str) -> pd.DataFrame:
    c = de_cuotas(ruta_cuotas)
    a = de_nba_api()
    if len(a):
        # las posesiones de nba_api donde coinciden; y los partidos que la
        # base de cuotas aún no tiene (de enero de 2026 en adelante)
        llave = ['fecha', 'home', 'away']
        c = c.merge(a[llave + ['home_poss', 'away_poss']], on=llave, how='left')
        nuevos = a.merge(c[llave], on=llave, how='left', indicator=True)
        nuevos = nuevos[nuevos['_merge'] == 'left_only'].drop(columns='_merge')
        # sólo lo POSTERIOR a la base de cuotas: antes, un partido que no casa
        # es un nombre distinto, no un partido nuevo
        nuevos = nuevos[nuevos['fecha'] > c['fecha'].max()]
        c = pd.concat([c, nuevos], ignore_index=True)
    return c.sort_values(['fecha', 'home']).reset_index(drop=True)


def actualizar(ruta: str = SALIDA) -> int:
    import requests
    r = requests.get(URL_CUOTAS, timeout=120)
    r.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        f.write(r.content)
        tmp = f.name
    try:
        d = construir(tmp)
    finally:
        os.remove(tmp)
    d.to_csv(ruta + '.tmp', index=False)
    os.replace(ruta + '.tmp', ruta)
    return len(d)


def cargar(ruta: str = SALIDA) -> Optional[pd.DataFrame]:
    """El histórico largo, con lo que nba_api haya añadido después (el cron
    diario lo mantiene) sin necesidad de volver a bajar las cuotas."""
    if not os.path.exists(ruta):
        return None
    d = pd.read_csv(ruta, low_memory=False)
    a = de_nba_api()
    if len(a):
        llave = ['fecha', 'home', 'away']
        nuevos = a.merge(d[llave], on=llave, how='left', indicator=True)
        nuevos = nuevos[(nuevos['_merge'] == 'left_only')
                        & (nuevos['fecha'] > d['fecha'].max())].drop(columns='_merge')
        if len(nuevos):
            d = pd.concat([d, nuevos], ignore_index=True)
    return d.sort_values(['fecha', 'home']).reset_index(drop=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    print('historico_nba_largo.csv: %d partidos' % actualizar())
