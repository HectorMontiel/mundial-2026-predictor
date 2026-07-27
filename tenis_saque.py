#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v69 — Estadísticas de SAQUE y RESTO por partido (lo que v67 dio por imposible).

Qué se buscaba
--------------
Aces, dobles faltas, puntos de saque, primeros dentro/ganados y puntos de break.
Sin eso no hay ELO de saque/resto, que es la señal más fuerte del tenis después
del ranking. En v67 el veredicto fue "no existe fuente gratuita" porque los
repos `JeffSackmann/tennis_atp` y `tennis_wta` habían desaparecido de GitHub.

Qué se probó en v69 (peticiones reales, 2026-07-27)
--------------------------------------------------
  · ATP Tour (`atptour.com/en/scores/stats-centre/...`)  → **403**
  · SofaScore (`api.sofascore.com/.../statistics`)        → **403**
  · UltimateTennisStatistics (`/matchStats`)              → 200 pero sin datos
  · Flashscore                                            → HTML renderizado por JS
  · Kaggle Challengers (`dissfya/atp-challenger-...`)     → 403 (como en v35)
  · **TennisAbstract** (`/cgi-bin/player-classic.cgi`)    → **200 y SÍ los tiene**

El hallazgo
-----------
Las páginas de jugador de TennisAbstract embeben un array JS `matchmx` con el
log completo de partidos y, a partir del índice 20, **exactamente el esquema de
Sackmann**:

    [20] minutos  [21] aces  [22] dobles faltas  [23] puntos al saque
    [24] 1os dentro  [25] 1os ganados  [26] 2os ganados  [27] juegos al saque
    [28] break points salvados  [29] break points enfrentados
    [30..38] los mismos nueve del RIVAL

Verificado sobre 2.300 partidos de tres jugadores: **99.9 % de coherencia**
(1osDentro ≤ puntos, 1osGanados ≤ 1osDentro, 2osGanados ≤ puntos−1osDentro,
bpSalvados ≤ bpEnfrentados, aces ≤ 1osDentro). Los 3 fallos son filas del US
Open 2019 con `juegos al saque = 0`, un hueco de la fuente, no del esquema.

Ética de uso: es un sitio pequeño. Se cachea en disco de forma permanente por
jugador, se respeta una pausa entre peticiones y sólo se piden los jugadores
que el modelo necesita.
"""

import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = 'https://www.tennisabstract.com'
UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36')}
CACHE = 'tenis_saque_cache'
PAUSA = 1.2                 # segundos entre peticiones (sitio pequeño)
TIMEOUT = 40
TTL_JUGADOR = 7 * 86400     # el log de un jugador cambia como mucho semanalmente

# Índices del array `matchmx` (verificados, ver docstring)
I_FECHA, I_TORNEO, I_SUP, I_NIVEL, I_RES = 0, 1, 2, 3, 4
I_RONDA, I_SCORE, I_RIVAL = 8, 9, 11
I_STATS = 20                # minutos; a partir de aquí, 9 propias + 9 del rival

CAMPOS = ['minutos', 'aces', 'df', 'svpt', 'primeros_in', 'primeros_gan',
          'segundos_gan', 'juegos_saque', 'bp_salvados', 'bp_enfrentados']


def _ruta(nombre: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    seguro = re.sub(r'[^A-Za-z0-9_-]', '_', nombre)
    return os.path.join(CACHE, f'{seguro}.json')


def ranking_actual(circuito: str = 'atp') -> Dict[str, int]:
    """Nombre completo -> ranking. Es también la lista de jugadores disponibles."""
    clave = f'_ranking_{circuito}'
    ruta = _ruta(clave)
    if os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < TTL_JUGADOR:
        try:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    url = f'{BASE}/jsplayers/curr_rank_{circuito}.js'
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        m = re.search(r'var\s+currRank\s*=\s*(\{.*?\});', r.text, re.S)
        datos = {k: int(v) for k, v in json.loads(m.group(1)).items()} if m else {}
    except Exception as e:
        logger.warning(f"[saque/{circuito}] ranking no disponible: {type(e).__name__}: {e}")
        return {}
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False)
    logger.info(f"[saque/{circuito}] {len(datos)} jugadores en el ranking.")
    return datos


def _slug(nombre_completo: str) -> str:
    """'Carlos Alcaraz' -> 'CarlosAlcaraz' (así construye la URL el propio sitio)."""
    return re.sub(r'\s+', '', nombre_completo.strip())


def log_jugador(nombre_completo: str, forzar: bool = False) -> List[list]:
    """Array `matchmx` crudo de un jugador. Cachea en disco de forma permanente."""
    ruta = _ruta(nombre_completo)
    if not forzar and os.path.exists(ruta):
        if time.time() - os.path.getmtime(ruta) < TTL_JUGADOR:
            try:
                with open(ruta, encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    url = f'{BASE}/cgi-bin/player-classic.cgi?p={_slug(nombre_completo)}'
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        m = re.search(r'var matchmx\s*=\s*(\[.*?\]);', r.text, re.S)
        filas = json.loads(m.group(1)) if m else []
    except Exception as e:
        logger.debug(f"[saque] {nombre_completo}: {type(e).__name__}: {e}")
        filas = []
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(filas, f, ensure_ascii=False)
    time.sleep(PAUSA)
    return filas


def _entero(v) -> Optional[int]:
    try:
        n = int(str(v).strip())
        return n
    except (TypeError, ValueError):
        return None


def partidos_de(nombre_completo: str, circuito: str = 'atp') -> pd.DataFrame:
    """
    Partidos del jugador con sus estadísticas de saque, en formato tabular.
    Devuelve vacío si la fuente no tiene log para ese nombre.
    """
    import tenis_fuentes as tf
    filas = log_jugador(nombre_completo)
    salida = []
    yo = tf.canonico(nombre_completo)
    for r in filas:
        if len(r) < I_STATS + 19:
            continue
        propias = [_entero(x) for x in r[I_STATS:I_STATS + 10]]
        rival = [_entero(x) for x in r[I_STATS + 10:I_STATS + 19]]
        if propias[3] is None or propias[3] <= 0:      # sin puntos al saque
            continue
        fila = {'fecha': str(r[I_FECHA]), 'torneo': r[I_TORNEO],
                'superficie': r[I_SUP], 'nivel': r[I_NIVEL],
                'gano': 1 if str(r[I_RES]).upper() == 'W' else 0,
                'ronda': r[I_RONDA], 'score': r[I_SCORE],
                'jugador': yo, 'rival': tf.canonico(r[I_RIVAL])}
        for c, v in zip(CAMPOS, propias):
            fila[c] = v
        for c, v in zip(CAMPOS[1:], rival):            # el rival no trae minutos
            fila[f'riv_{c}'] = v
        salida.append(fila)
    if not salida:
        return pd.DataFrame()
    df = pd.DataFrame(salida)
    df['fecha'] = pd.to_datetime(df['fecha'], format='%Y%m%d', errors='coerce')
    return df.dropna(subset=['fecha'])


def coherente(df: pd.DataFrame) -> pd.Series:
    """
    Máscara de filas cuyas estadísticas son internamente consistentes. Se aplica
    SIEMPRE antes de usar los datos: la fuente tiene huecos puntuales (vi filas
    del US Open 2019 con `juegos_saque = 0`) y una fila incoherente envenena las
    medias rodantes sin avisar.
    """
    return ((df['primeros_in'] <= df['svpt'])
            & (df['primeros_gan'] <= df['primeros_in'])
            & (df['segundos_gan'] <= df['svpt'] - df['primeros_in'])
            & (df['bp_salvados'] <= df['bp_enfrentados'])
            & (df['aces'] <= df['primeros_in'])
            & (df['juegos_saque'].fillna(0) > 0)
            & (df['svpt'] > 0))


def descargar_circuito(circuito: str = 'atp', top_n: int = 250,
                       solo: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Descarga los logs de los `top_n` jugadores del ranking (o de la lista
    `solo`) y devuelve TODOS sus partidos con estadísticas de saque.

    Un partido aparece dos veces (una por jugador) si ambos están en la lista:
    se deduplica quedándose con la primera, que ya trae también las
    estadísticas del rival.
    """
    ranking = ranking_actual(circuito)
    if solo:
        nombres = [n for n in solo if n in ranking] or list(solo)
    else:
        nombres = [n for n, _ in sorted(ranking.items(), key=lambda kv: kv[1])[:top_n]]
    logger.info(f"[saque/{circuito}] descargando {len(nombres)} jugadores "
                f"(pausa {PAUSA}s, caché {CACHE}/)")
    marcos = []
    for i, n in enumerate(nombres, 1):
        df = partidos_de(n, circuito)
        if not df.empty:
            marcos.append(df)
        if i % 25 == 0:
            logger.info(f"   {i}/{len(nombres)} · {sum(len(m) for m in marcos)} partidos")
    if not marcos:
        return pd.DataFrame()
    todo = pd.concat(marcos, ignore_index=True)
    antes = len(todo)
    todo = todo[coherente(todo)].copy()
    # clave simétrica del partido para deduplicar
    todo['_k'] = [f"{f:%Y%m%d}|" + '|'.join(sorted((a, b)))
                  for f, a, b in zip(todo['fecha'], todo['jugador'], todo['rival'])]
    todo = todo.drop_duplicates('_k', keep='first').drop(columns='_k')
    logger.info(f"[saque/{circuito}] {len(todo)} partidos únicos con estadística de "
                f"saque ({antes - len(todo)} filas descartadas por duplicado o "
                f"incoherencia) · {todo['fecha'].min().date()} → {todo['fecha'].max().date()}")
    return todo.sort_values('fecha').reset_index(drop=True)


def guardar(circuito: str = 'atp', top_n: int = 250) -> str:
    df = descargar_circuito(circuito, top_n)
    # Comprimido: son datos de un sitio pequeño que no conviene volver a
    # raspar, y en gzip ocupan una fracción (27.3 MB -> 1.4 MB en la WTA).
    ruta = f'saque_{circuito}.csv.gz'
    df.to_csv(ruta, index=False, encoding='utf-8', compression='gzip')
    print(f"✅ {ruta}: {len(df)} partidos con estadística de saque.")
    return ruta


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('circuito', nargs='?', default='atp', choices=['atp', 'wta'])
    ap.add_argument('--top', type=int, default=250)
    a = ap.parse_args()
    guardar(a.circuito, a.top)
