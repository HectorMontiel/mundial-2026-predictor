#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v67 — Remates y remates a puerta REALES por jugador.

Problema que resuelve
---------------------
Hasta v66 la sección «¿Quién remata?» mostraba, por jugador, un remates/partido
*estimado*: se partía de sus GOLES de los últimos 24 meses y se multiplicaba por
la calibración de StatsBomb (`shots_on_por_xg`, `shots_total_por_on`). Dos
consecuencias:

  · el número no era un remate observado, era un gol reescalado;
  · solo aparecían jugadores que habían MARCADO, así que el delantero que
    remata ocho veces por partido sin acertar simplemente no existía en la
    tabla — justo el dato que sirve para el mercado de remates.

Solución
--------
ESPN publica, en el `summary` de cada partido de fútbol, un bloque `rosters`
con las estadísticas POR JUGADOR, y entre ellas están `totalShots` (SHOT) y
`shotsOnTarget` (SOG). Verificado con cobertura en Premier, LaLiga, Serie A,
Liga MX, MLS, Brasileirão, Nations League y amistosos de selecciones.

Este módulo agrega esas estadísticas de los últimos partidos de un equipo y
devuelve, por jugador: partidos, remates, remates a puerta, goles, sus medias
por partido y la puntería (a puerta / totales). Todo dato observado.

Uso:
    remates_equipo('eng.1', 'Aston Villa')          # club
    remates_seleccion('MEX')                         # selección nacional
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}'
UA = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 25
CACHE_DIR = 'remates_cache'
TTL = 6 * 3600
MAX_PARTIDOS = 10
VENTANA_DIAS = 420          # cubre una temporada completa

# Ligas donde juegan las SELECCIONES (para la vista internacional)
LIGAS_SELECCIONES = ['fifa.friendly', 'uefa.nations', 'fifa.worldq.uefa',
                     'fifa.worldq.conmebol', 'fifa.worldq.concacaf',
                     'fifa.worldq.afc', 'fifa.worldq.caf', 'fifa.worldq.ofc',
                     'fifa.world']

# abreviatura de ESPN -> nombre de columna
CAMPOS = {'SHOT': 'remates', 'SOG': 'al_arco', 'G': 'goles',
          'A': 'asistencias', 'APP': 'apariciones'}


def _cache(nombre: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, nombre)


def _leer_cache(clave: str) -> Optional[dict]:
    ruta = _cache(clave)
    if os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < TTL:
        try:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _escribir_cache(clave: str, datos) -> None:
    try:
        with open(_cache(clave), 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False)
    except Exception:
        pass


def _get(url: str, params: dict) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug(f"[remates] {url}: {type(e).__name__}: {e}")
        return None


TRAMO_DIAS = 55        # ESPN devuelve 400 con rangos largos en fútbol


def _partidos_del_equipo(liga: str, equipo: str, dias: int,
                         objetivo_n: int = MAX_PARTIDOS) -> List[dict]:
    """
    Últimos partidos TERMINADOS del equipo en esa liga.

    El scoreboard de fútbol de ESPN rechaza rangos largos (400 Bad Request con
    un año entero), así que se recorre hacia atrás en tramos de ~2 meses y se
    para en cuanto hay partidos suficientes: en la práctica bastan 1-2 tramos.
    """
    objetivo = str(equipo).strip().lower()
    hoy = pd.Timestamp.today().normalize()
    salida: List[dict] = []
    vistos = set()
    for salto in range(0, max(dias, 1), TRAMO_DIAS):
        fin = hoy - pd.Timedelta(days=salto)
        ini = fin - pd.Timedelta(days=TRAMO_DIAS)
        j = _get(BASE.format(liga=liga) + '/scoreboard',
                 {'dates': f'{ini:%Y%m%d}-{fin:%Y%m%d}', 'limit': 400})
        if not j:
            continue
        for ev in j.get('events', []):
            if not ev.get('status', {}).get('type', {}).get('completed'):
                continue
            if ev['id'] in vistos:
                continue
            comp = (ev.get('competitions') or [{}])[0]
            nombres = []
            for c in comp.get('competitors', []):
                t = c.get('team', {})
                nombres += [str(t.get(k, '')).strip().lower()
                            for k in ('displayName', 'shortDisplayName',
                                      'name', 'abbreviation')]
            if objetivo in nombres:
                vistos.add(ev['id'])
                salida.append({'id': ev['id'], 'fecha': ev.get('date', '')})
        if len(salida) >= objetivo_n:
            break
    salida.sort(key=lambda x: x['fecha'], reverse=True)
    return salida


def _stats_partido(liga: str, evento_id: str, equipo: str) -> List[dict]:
    """Estadísticas por jugador del equipo en ese partido."""
    j = _get(BASE.format(liga=liga) + '/summary', {'event': evento_id})
    if not j:
        return []
    objetivo = str(equipo).strip().lower()
    filas = []
    for ro in j.get('rosters', []):
        t = ro.get('team', {})
        nombres = [str(t.get(k, '')).strip().lower()
                   for k in ('displayName', 'shortDisplayName', 'name', 'abbreviation')]
        if objetivo not in nombres:
            continue
        for a in ro.get('roster', []):
            atleta = a.get('athlete') or {}
            st = {x.get('abbreviation'): x.get('displayValue')
                  for x in (a.get('stats') or [])}
            if 'SHOT' not in st:            # el partido no trae estadística
                continue
            fila = {'jugador': atleta.get('displayName'),
                    'posicion': (a.get('position') or {}).get('abbreviation'),
                    'titular': bool(a.get('starter'))}
            for abbr, col in CAMPOS.items():
                try:
                    fila[col] = int(float(st.get(abbr) or 0))
                except (TypeError, ValueError):
                    fila[col] = 0
            filas.append(fila)
    return filas


def equipos_de_liga(liga: str, dias: int = 120) -> List[str]:
    """Nombres de equipo tal y como los escribe ESPN en esa liga."""
    clave = f'equipos_{liga}.json'
    cacheado = _leer_cache(clave)
    if cacheado is not None:
        return cacheado
    hoy = pd.Timestamp.today().normalize()
    nombres = set()
    for salto in range(0, max(dias, 1), TRAMO_DIAS):
        fin = hoy - pd.Timedelta(days=salto)
        ini = fin - pd.Timedelta(days=TRAMO_DIAS)
        j = _get(BASE.format(liga=liga) + '/scoreboard',
                 {'dates': f'{ini:%Y%m%d}-{fin:%Y%m%d}', 'limit': 400})
        for ev in (j or {}).get('events', []):
            for c in (ev.get('competitions') or [{}])[0].get('competitors', []):
                n = (c.get('team') or {}).get('displayName')
                if n:
                    nombres.add(n)
        if len(nombres) >= 16:
            break
    salida = sorted(nombres)
    _escribir_cache(clave, salida)
    return salida


def resolver_equipo(liga: str, nombre: str) -> Optional[str]:
    """
    Traduce el nombre que usa el proyecto (football-data: «Nott'm Forest») al
    que usa ESPN («Nottingham Forest»), con el `name_mapper` del proyecto.
    Devuelve None si no hay equivalente razonable.
    """
    catalogo = equipos_de_liga(liga)
    if not catalogo:
        return None
    if nombre in catalogo:
        return nombre
    try:
        import name_mapper
        return name_mapper.mapear(nombre, catalogo, contexto=f'remates/{liga}')
    except Exception:
        objetivo = str(nombre).strip().lower()
        for c in catalogo:
            if c.strip().lower() == objetivo:
                return c
        return None


def remates_equipo(liga: str, equipo: str, n_partidos: int = MAX_PARTIDOS,
                   dias: int = VENTANA_DIAS) -> pd.DataFrame:
    """
    Remates REALES por jugador en los últimos `n_partidos` del equipo.

    Devuelve columnas: jugador, posicion, partidos, remates, al_arco, goles,
    remates_pp, al_arco_pp, punteria, titularidades. Vacío si ESPN no publica
    estadística de esos partidos (degradación limpia: la UI cae al estimado).
    """
    clave = f'rem_{liga}_{str(equipo).lower().replace(" ", "_")}_{n_partidos}.json'
    cacheado = _leer_cache(clave)
    if cacheado is not None:
        return pd.DataFrame(cacheado)

    partidos = _partidos_del_equipo(liga, equipo, dias, n_partidos)[:n_partidos]
    if not partidos:
        return pd.DataFrame()
    filas: List[dict] = []
    with ThreadPoolExecutor(max_workers=min(6, len(partidos))) as ex:
        for res in ex.map(lambda p: _stats_partido(liga, p['id'], equipo), partidos):
            filas.extend(res)
    if not filas:
        return pd.DataFrame()

    df = pd.DataFrame(filas)
    agr = df.groupby('jugador', as_index=False).agg(
        posicion=('posicion', lambda s: s.mode().iat[0] if len(s.mode()) else ''),
        partidos=('apariciones', 'sum'),
        titularidades=('titular', 'sum'),
        remates=('remates', 'sum'),
        al_arco=('al_arco', 'sum'),
        goles=('goles', 'sum'),
        asistencias=('asistencias', 'sum'),
    )
    agr['partidos'] = agr['partidos'].clip(lower=1)
    agr['remates_pp'] = (agr['remates'] / agr['partidos']).round(2)
    agr['al_arco_pp'] = (agr['al_arco'] / agr['partidos']).round(2)
    agr['punteria'] = (agr['al_arco'] / agr['remates'].where(agr['remates'] > 0)).round(3)
    agr = agr.sort_values(['remates', 'al_arco'], ascending=False).reset_index(drop=True)
    agr['n_partidos_muestra'] = len(partidos)
    _escribir_cache(clave, agr.to_dict('records'))
    logger.info(f"[remates] {equipo} ({liga}): {len(agr)} jugadores en "
                f"{len(partidos)} partidos.")
    return agr


def remates_seleccion(codigo_fifa: str, n_partidos: int = 8) -> pd.DataFrame:
    """
    Igual que `remates_equipo` pero para una SELECCIÓN: barre las competiciones
    de selecciones (amistosos, Nations League, clasificatorias, Mundial) y
    junta lo que encuentre.
    """
    try:
        from config import TEAM_NAMES_EN
        nombre = TEAM_NAMES_EN.get(codigo_fifa, codigo_fifa)
    except Exception:
        nombre = codigo_fifa
    clave = f'rem_sel_{codigo_fifa}_{n_partidos}.json'
    cacheado = _leer_cache(clave)
    if cacheado is not None:
        return pd.DataFrame(cacheado)

    marcos = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for df in ex.map(lambda lg: remates_equipo(lg, nombre, n_partidos),
                         LIGAS_SELECCIONES):
            if df is not None and not df.empty:
                marcos.append(df)
    if not marcos:
        return pd.DataFrame()
    todo = pd.concat(marcos, ignore_index=True)
    agr = todo.groupby('jugador', as_index=False).agg(
        posicion=('posicion', lambda s: s.mode().iat[0] if len(s.mode()) else ''),
        partidos=('partidos', 'sum'), titularidades=('titularidades', 'sum'),
        remates=('remates', 'sum'), al_arco=('al_arco', 'sum'),
        goles=('goles', 'sum'), asistencias=('asistencias', 'sum'))
    agr['remates_pp'] = (agr['remates'] / agr['partidos'].clip(lower=1)).round(2)
    agr['al_arco_pp'] = (agr['al_arco'] / agr['partidos'].clip(lower=1)).round(2)
    agr['punteria'] = (agr['al_arco'] / agr['remates'].where(agr['remates'] > 0)).round(3)
    agr = agr.sort_values(['remates', 'al_arco'], ascending=False).reset_index(drop=True)
    _escribir_cache(clave, agr.to_dict('records'))
    return agr


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if len(sys.argv) >= 3:
        print(remates_equipo(sys.argv[1], sys.argv[2]).head(15).to_string(index=False))
    else:
        print(remates_seleccion(sys.argv[1] if len(sys.argv) > 1 else 'MEX')
              .head(15).to_string(index=False))
