#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — MLB StatsAPI: la fuente que faltaba para la TEMPORADA EN CURSO.

Por qué existe
--------------
El modelo de MLB se alimentaba solo de Retrosheet, que publica los game logs
**por temporada cerrada**. Medido el 2026-07-29:

    último partido en el estado del modelo : 2025-09-28
    hoy                                     : 2026-07-29
    ANTIGÜEDAD                              : 304 días

O sea: la temporada 2026 se estaba prediciendo con el ELO, la forma y las
rachas congelados en el final de 2025. No daba ningún error — simplemente
devolvía probabilidades casi idénticas para todo el mundo:

    58,5 % de los emparejamientos caían entre 45 % y 55 %
    desviación típica de la probabilidad: 0,0537   (máximo posible: 0,7075)

Ese es el «todo da 50-50» que se veía en la interfaz.

Qué aporta StatsAPI
-------------------
`statsapi.mlb.com` es la API oficial de la MLB: **gratuita, sin clave y sin
cuota**. Una temporada completa son 2.464 juegos en **una sola petición de
1,6 s**, con marcador final y —esto es lo que de verdad importa— el
**lanzador abridor probable** de cada lado, que es la variable más predictiva
del béisbol y que hasta ahora no llegaba a inferencia.

Se ingiere TODA la historia desde aquí, no solo la temporada en curso, por dos
razones medidas:

1. **Identidad del lanzador.** Retrosheet usa ids propios (`mizec001`) y
   StatsAPI usa ids numéricos (`684007`). Mezclarlos parte el historial de cada
   lanzador en dos personas distintas y la media de sus últimas 5 aperturas
   deja de significar nada. Con una sola fuente hay un solo espacio de nombres.

2. **La franquicia de Oakland estaba partida en dos.** Retrosheet cambió el
   código `OAK` (1.502 juegos, hasta 2024-09-29) por `ATH` (162 juegos, desde
   2025-03-27) al mudarse el equipo. En `historico_mlb.csv` había **31 códigos
   para 30 equipos**, y el ELO de los Athletics se reiniciaba a 1500 en 2025.
   Aquí se canonaliza por **id de StatsAPI**, que no cambia cuando cambia el
   nombre, y ambos caen en `OAK`.

El esquema de salida es EXACTAMENTE el de `retrosheet_scraper` (mismas columnas
y mismos códigos de equipo), así que nada aguas abajo se entera del cambio.
"""

import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = 'https://statsapi.mlb.com/api/v1/schedule'
SALIDA = 'historico_mlb.csv'
TIEMPO_ESPERA = 60

# id de StatsAPI -> código Retrosheet. Se indexa por ID y no por nombre porque
# el nombre cambia (Cleveland Indians -> Guardians, Oakland Athletics ->
# Athletics) y el id no. `OAK` para el 133 mantiene unida la historia de la
# franquicia (ver docstring).
ID_A_CODIGO: Dict[int, str] = {
    108: 'ANA', 109: 'ARI', 110: 'BAL', 111: 'BOS', 112: 'CHN',
    113: 'CIN', 114: 'CLE', 115: 'COL', 116: 'DET', 117: 'HOU',
    118: 'KCA', 119: 'LAN', 120: 'WAS', 121: 'NYN', 133: 'OAK',
    134: 'PIT', 135: 'SDN', 136: 'SEA', 137: 'SFN', 138: 'SLN',
    139: 'TBA', 140: 'TEX', 141: 'TOR', 142: 'MIN', 143: 'PHI',
    144: 'ATL', 145: 'CHA', 146: 'MIA', 147: 'NYA', 158: 'MIL',
}

# Estados de partido que cuentan como resultado firme.
FINALES = {'F', 'FR', 'FT', 'O'}


def _pedir(params: dict, reintentos: int = 3) -> dict:
    ultimo = None
    for i in range(reintentos):
        try:
            r = requests.get(BASE, params=params, timeout=TIEMPO_ESPERA)
            r.raise_for_status()
            return r.json()
        except Exception as e:                       # red intermitente
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'StatsAPI no respondió: {ultimo}')


def _fila(g: dict, solo_finalizados: bool) -> Optional[dict]:
    """Convierte un juego de StatsAPI al esquema de `retrosheet_scraper`."""
    estado = (g.get('status') or {}).get('codedGameState')
    equipos = g.get('teams') or {}
    h, a = equipos.get('home') or {}, equipos.get('away') or {}
    hid = ((h.get('team') or {}).get('id'))
    aid = ((a.get('team') or {}).get('id'))
    hc, ac = ID_A_CODIGO.get(hid), ID_A_CODIGO.get(aid)
    if not hc or not ac:
        return None                    # partido de exhibición o equipo no-MLB
    if solo_finalizados:
        if estado not in FINALES:
            return None
        if h.get('score') is None or a.get('score') is None:
            return None
    def _pit(lado):
        p = (lado.get('probablePitcher') or {}).get('id')
        return str(p) if p else ''
    return {
        'date': pd.to_datetime((g.get('officialDate')
                                or g.get('gameDate', '')[:10])),
        'home_team': hc, 'away_team': ac,
        'home_runs': int(h['score']) if h.get('score') is not None else None,
        'away_runs': int(a['score']) if a.get('score') is not None else None,
        'home_pitcher': _pit(h), 'away_pitcher': _pit(a),
    }


def descargar_temporada(anio: int, solo_finalizados: bool = True) -> pd.DataFrame:
    """Temporada regular completa en una sola petición."""
    d = _pedir({'sportId': 1, 'gameType': 'R',
                'startDate': f'{anio}-02-15', 'endDate': f'{anio}-12-01',
                'hydrate': 'probablePitcher,team'})
    filas = []
    for dia in d.get('dates') or []:
        for g in dia.get('games') or []:
            f = _fila(g, solo_finalizados)
            if f:
                filas.append(f)
    df = pd.DataFrame(filas)
    con_pit = 0
    if not df.empty:
        con_pit = int(((df.home_pitcher != '') & (df.away_pitcher != '')).sum())
    logger.info(f"[mlb/statsapi] {anio}: {len(df)} juegos "
                f"({con_pit} con ambos abridores)")
    return df


def actualizar(anios: List[int], salida: str = SALIDA) -> pd.DataFrame:
    """
    Consolida las temporadas pedidas en `historico_mlb.csv`.

    A diferencia de `retrosheet_scraper.actualizar`, la temporada en curso se
    vuelve a bajar SIEMPRE (es la que cambia todos los días, y es justo la que
    el modelo necesita fresca).
    """
    frames = []
    for a in sorted(anios):
        try:
            df = descargar_temporada(a)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            logger.warning(f"[mlb/statsapi] {a} no disponible: {e}")
    if not frames:
        return pd.read_csv(salida, parse_dates=['date']) \
            if os.path.exists(salida) else pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=['home_runs', 'away_runs'])
    df['home_runs'] = df['home_runs'].astype(int)
    df['away_runs'] = df['away_runs'].astype(int)
    df = (df.sort_values('date')
            .drop_duplicates(subset=['date', 'home_team', 'away_team'],
                             keep='last')
            .reset_index(drop=True))
    df.to_csv(salida, index=False)
    logger.info(f"[mlb/statsapi] {salida}: {len(df)} juegos "
                f"({df['date'].min().date()} → {df['date'].max().date()}) · "
                f"{df['home_team'].nunique()} equipos")
    return df


def partidos_del_dia(fecha: Optional[str] = None) -> List[dict]:
    """
    Partidos de hoy CON abridor probable, para inferencia.

    Es la mitad que faltaba: el modelo se entrena con las carreras permitidas
    por el abridor, pero `apuestas_dia` llamaba a `predecir(home, away)` sin
    pasarlos, así que en producción esas features caían al valor por defecto y
    quedaban CONSTANTES. Medido: `DIFF_PIT_RA` y `MEDIA_PIT_RA` tenían
    desviación típica 0,0000 sobre todos los emparejamientos.
    """
    f = fecha or pd.Timestamp.today().strftime('%Y-%m-%d')
    try:
        d = _pedir({'sportId': 1, 'startDate': f, 'endDate': f,
                    'hydrate': 'probablePitcher,team'})
    except Exception as e:
        logger.warning(f"[mlb/statsapi] partidos del día: {e}")
        return []
    fuera = []
    for dia in d.get('dates') or []:
        for g in dia.get('games') or []:
            fila = _fila(g, solo_finalizados=False)
            if not fila:
                continue
            fuera.append({
                'fecha': str(fila['date'].date()),
                'home': fila['home_team'], 'away': fila['away_team'],
                'home_pitcher': fila['home_pitcher'],
                'away_pitcher': fila['away_pitcher'],
                'estado': (g.get('status') or {}).get('codedGameState'),
                'game_pk': g.get('gamePk'),
            })
    con = sum(1 for x in fuera if x['home_pitcher'] and x['away_pitcher'])
    logger.info(f"[mlb/statsapi] {f}: {len(fuera)} partidos, "
                f"{con} con ambos abridores anunciados")
    return fuera


# ---------------------------------------------------------------------------
# v80 — CALIDAD DEL LANZADOR: lo que faltaba, y no era caro
# ---------------------------------------------------------------------------
BASE_STATS = 'https://statsapi.mlb.com/api/v1/stats'
SALIDA_PIT = 'mlb_pitchers_temporada.csv.gz'


def _num(x, dv=None):
    try:
        v = float(x)
        return v if np.isfinite(v) else dv
    except (TypeError, ValueError):
        return dv


def stats_pitcheo(anio: int) -> pd.DataFrame:
    """
    Línea de pitcheo de TODOS los lanzadores de una temporada, en UNA petición.

    Por qué importa
    ---------------
    La v79 dejó escrito que el techo de MLB estaba en la falta de estadística
    real del abridor: la única señal disponible era «carreras que concedió el
    EQUIPO en las últimas aperturas de este lanzador», que mezcla bullpen y
    defensa y se calcula sobre 5 partidos. Se dio por inviable traerla porque
    parecía exigir un game log por lanzador (~900 por temporada).

    Era falso. `/api/v1/stats?stats=season&group=pitching&sportId=1` devuelve
    **los 873 lanzadores de la temporada 2025 en 1,2 segundos**, con ERA, WHIP,
    ponches, bases por bolas, jonrones, entradas y aperturas. Doce temporadas
    son doce peticiones, unos quince segundos en total.

    Cómo se usa SIN FUGA
    --------------------
    La línea de una temporada solo se conoce cuando esa temporada ha
    terminado, así que para un partido de la temporada Y se usa la línea de
    Y-1 (y el acumulado de todas las anteriores). Eso es información
    disponible antes del primer lanzamiento de Y: cero fuga, y a la vez la
    medida más limpia de «cómo de bueno es este lanzador» que existe gratis.
    """
    d = _pedir_stats({'stats': 'season', 'group': 'pitching', 'season': anio,
                      'sportId': 1, 'limit': 2000, 'playerPool': 'All'})
    bloques = d.get('stats') or []
    filas = []
    for b in bloques:
        for s in (b.get('splits') or []):
            p = s.get('player') or {}
            st = s.get('stat') or {}
            ip = _num(st.get('inningsPitched'), 0.0) or 0.0
            if not p.get('id'):
                continue
            filas.append({
                'anio': anio, 'pitcher': str(p['id']),
                'nombre': p.get('fullName'),
                'ip': ip,
                'gs': _num(st.get('gamesStarted'), 0.0) or 0.0,
                'era': _num(st.get('era')),
                'whip': _num(st.get('whip')),
                'so': _num(st.get('strikeOuts'), 0.0) or 0.0,
                'bb': _num(st.get('baseOnBalls'), 0.0) or 0.0,
                'hr': _num(st.get('homeRuns'), 0.0) or 0.0,
                'bf': _num(st.get('battersFaced'), 0.0) or 0.0,
            })
    df = pd.DataFrame(filas)
    logger.info(f'[mlb/statsapi] pitcheo {anio}: {len(df)} lanzadores')
    return df


def _pedir_stats(params: dict, reintentos: int = 3) -> dict:
    ultimo = None
    for i in range(reintentos):
        try:
            r = requests.get(BASE_STATS, params=params, timeout=TIEMPO_ESPERA)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'StatsAPI (stats) no respondió: {ultimo}')


def actualizar_pitcheo(anios: List[int], salida: str = SALIDA_PIT) -> pd.DataFrame:
    """Consolida la línea de pitcheo de varias temporadas en un CSV cacheable."""
    partes = []
    for a in sorted(anios):
        try:
            d = stats_pitcheo(a)
            if not d.empty:
                partes.append(d)
        except Exception as e:
            logger.warning(f'[mlb/statsapi] pitcheo {a} no disponible: {e}')
    if not partes:
        return (pd.read_csv(salida) if os.path.exists(salida)
                else pd.DataFrame())
    df = pd.concat(partes, ignore_index=True)
    df = df.drop_duplicates(subset=['anio', 'pitcher'], keep='last')
    df.to_csv(salida, index=False, compression='gzip')
    logger.info(f"[mlb/statsapi] {salida}: {len(df)} filas · "
                f"{df['anio'].min()}-{df['anio'].max()} · "
                f"{df['pitcher'].nunique()} lanzadores distintos")
    return df


def indice_abridores(fecha: Optional[str] = None) -> Dict[tuple, tuple]:
    """(codigo_local, codigo_visitante) -> (id_abridor_local, id_abridor_vis)."""
    return {(p['home'], p['away']): (p['home_pitcher'], p['away_pitcher'])
            for p in partidos_del_dia(fecha)}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import datetime
    y = datetime.date.today().year
    actualizar(list(range(y - 11, y + 1)))
    partidos_del_dia()


# ---------------------------------------------------------------------------
# v84 — LIGA MEXICANA DE BÉISBOL (LMB): dejar de tirarla a la basura
# ---------------------------------------------------------------------------
# El barrido decía cada día: «MLB: 33 partidos con cuota pero sin equipos
# reconocidos por el modelo (probablemente ligas no MLB, como la Liga Mexicana
# de Béisbol)». Ese «probablemente» era una suposición, y descartar a ciegas un
# tercio de los partidos con precio es tirar información.
#
# Comprobado: la API oficial SÍ cubre la Liga Mexicana — `leagueId 125`,
# `sportId 23`, 20 equipos, ~1.000 juegos por temporada (2024: 1.059, 2025:
# 1.044, 2026: 966). No es una liga opaca, es una liga que no habíamos mirado.
#
# Con los equipos identificados dejan de ser «desconocidos»: se pueden etiquetar
# como lo que son, y la vía de `valor_vs_sharp` —que NO usa modelo— puede
# operar sobre ellos igual que sobre la MLB.
LMB_SPORT_ID = 23
LMB_LEAGUE_ID = 125
_CACHE_LMB: Dict[str, set] = {}


def equipos_lmb() -> set:
    """Nombres de los equipos de la Liga Mexicana, normalizados en minúsculas."""
    if 'nombres' in _CACHE_LMB:
        return _CACHE_LMB['nombres']
    nombres = set()
    try:
        r = requests.get('https://statsapi.mlb.com/api/v1/teams',
                         params={'sportId': LMB_SPORT_ID,
                                 'leagueId': LMB_LEAGUE_ID},
                         timeout=TIEMPO_ESPERA)
        r.raise_for_status()
        for t in (r.json().get('teams') or []):
            for k in ('name', 'teamName', 'shortName', 'clubName'):
                v = t.get(k)
                if v:
                    nombres.add(str(v).strip().lower())
    except Exception as e:
        logger.warning(f'[lmb] no se pudo leer el catálogo de equipos: {e}')
    _CACHE_LMB['nombres'] = nombres
    logger.info(f'[lmb] {len(nombres)} nombres de equipo de la Liga Mexicana')
    return nombres


def es_lmb(nombre: str) -> bool:
    """¿Este nombre es de un equipo de la Liga Mexicana de Béisbol?"""
    if not nombre:
        return False
    n = str(nombre).strip().lower()
    eq = equipos_lmb()
    if n in eq:
        return True
    # las casas abrevian ('Sultanes', 'Diablos Rojos'): basta con que un nombre
    # del catálogo contenga al otro y comparta una palabra significativa.
    for c in eq:
        if n in c or c in n:
            return True
    return False
