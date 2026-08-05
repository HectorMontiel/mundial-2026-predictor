#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v98 — Cuotas de cierre históricas de la KBO desde BetExplorer.

Qué se buscó y qué hay
----------------------
La v97 dejó la KBO en Capa 2 porque no había cuota de cierre con la que medir
ROI. Buscadas (2026-08-05, con peticiones reales):

  · **sportsbookreviewsonline** — el que dio la MLB. Ni KBO ni Corea: 0
    ficheros en sus archivos.
  · **OddsPortal** — las tres rutas devuelven la MISMA página de 93.657 bytes
    (incluida `/robots.txt`), o sea un SPA que no sirve nada sin JavaScript.
  · **Flashscore / Scoreboard / Covers** — 404 en las rutas de KBO.
  · **statiz.sporki.com** — no resuelve.
  · **BetExplorer** — sí. Es esta.

Lo que BetExplorer permite, y lo que NO
---------------------------------------
Tiene la KBO por temporadas, **2012-2025**, en rutas planas
(`/baseball/south-korea/kbo-2024/results/`) que su `robots.txt` permite — sólo
prohíbe cadenas de consulta (`/*?stage=`, `/*?page=`, `/*?year=`…). Y cada fila
trae lo que hace falta: ganador en `<strong>`, marcador, fecha y **las dos
cuotas de cierre** en `data-odd`.

**PERO esa página sólo sirve los PLAYOFFS.** La temporada regular está detrás
de `?stage=`, que es justo lo que el `robots.txt` prohíbe. Es el mismo límite
que la v92 documentó al intentar traer las cuotas sudamericanas: superficie
permitida, no bug. Así que lo que se puede reunir legalmente son ~16 partidos
por temporada, no ~720.

Eso importa al interpretarlo, y por eso se anota `fase='playoff'` en cada
fila: **los playoffs son una población sesgada** (sólo los equipos fuertes, con
rotación de lanzadores distinta y sin partidos intrascendentes). Un ROI medido
aquí no se puede extrapolar sin más a la temporada regular. Se recoge igual
porque es cuota de cierre REAL y es lo único que existe.
"""

import io
import logging
import re
import time
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

BASE = 'https://www.betexplorer.com'
SALIDA = 'cuotas_kbo_cierre.csv'
UA = {'User-Agent': 'Mozilla/5.0'}
TEMPORADAS = list(range(2012, 2026))

# Nombre en BetExplorer -> nombre canónico de `kbo_naver`.
ALIAS_BE = {
    'doosan bears': 'Doosan Bears', 'hanwha eagles': 'Hanwha Eagles',
    'kia tigers': 'Kia Tigers', 'kt wiz': 'KT Wiz', 'kt wiz suwon': 'KT Wiz',
    'lg twins': 'LG Twins', 'lotte giants': 'Lotte Giants',
    'nc dinos': 'NC Dinos', 'samsung lions': 'Samsung Lions',
    'ssg landers': 'SSG Landers', 'sk wyverns': 'SSG Landers',
    'kiwoom heroes': 'Kiwoom Heroes', 'nexen heroes': 'Kiwoom Heroes',
    'woori heroes': 'Kiwoom Heroes', 'heroes': 'Kiwoom Heroes',
}

RE_FILA = re.compile(
    r'<tr>\s*<td class="h-text-left">\s*<a[^>]*href="(/baseball/south-korea/'
    r'[^"]*?/[A-Za-z0-9]{8}/)"[^>]*>(.*?)</a>\s*</td>\s*'
    r'<td class="h-text-center">\s*<a[^>]*>\s*([\d]+):([\d]+)\s*</a>\s*</td>'
    r'(.*?)</tr>', re.S)
RE_ODD = re.compile(r'data-odd="([\d.]+)"')
RE_FECHA = re.compile(r'>(\d{2}\.\d{2}\.\d{4})<')
RE_TAG = re.compile(r'<[^>]+>')


def _equipo(nombre: str):
    return ALIAS_BE.get(re.sub(r'\s+', ' ', nombre).strip().lower())


def _get(url: str, intentos: int = 3):
    import requests
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers=UA, timeout=35)
            if r.status_code == 200:
                return r.text
            ultimo = RuntimeError(f'HTTP {r.status_code}')
        except Exception as e:
            ultimo = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'betexplorer no respondió: {ultimo}')


def temporada(anio: int) -> List[dict]:
    """Partidos con cuota de cierre de esa temporada (sólo los que sirve la
    ruta plana: playoffs)."""
    slug = 'kbo' if anio >= 2026 else f'kbo-{anio}'
    html = _get(f'{BASE}/baseball/south-korea/{slug}/results/')
    filas = []
    for m in RE_FILA.finditer(html):
        equipos_html, s1, s2, cola = m.group(2), m.group(3), m.group(4), m.group(5)
        gana_1 = '<strong>' in equipos_html.split('</span>')[0]
        nombres = [RE_TAG.sub('', x).strip()
                   for x in re.findall(r'<span>.*?</span>', equipos_html, re.S)]
        if len(nombres) < 2:
            continue
        h, a = _equipo(nombres[0]), _equipo(nombres[1])
        if not h or not a or h == a:
            continue
        odds = RE_ODD.findall(cola)
        if len(odds) < 2:
            continue
        f = RE_FECHA.search(cola)
        if not f:
            continue
        d, mes, y = f.group(1).split('.')
        filas.append({
            'fecha': f'{y}-{mes}-{d}', 'temporada': anio,
            # En BetExplorer el PRIMERO es el local en béisbol coreano; se
            # comprueba después contra `historico_kbo.csv`, que es la verdad.
            'home': h, 'away': a,
            'runs_home': int(s1), 'runs_away': int(s2),
            'gana_home': int(s1) > int(s2),
            'odd_home': float(odds[0]), 'odd_away': float(odds[1]),
            'fase': 'playoff'})
    logger.info(f'[kbo/cuotas] {anio}: {len(filas)} partidos con cierre')
    return filas


def ingerir(salida: str = SALIDA) -> pd.DataFrame:
    todo = []
    for a in TEMPORADAS:
        try:
            todo += temporada(a)
        except Exception as e:
            logger.warning(f'[kbo/cuotas] {a}: {e}')
        time.sleep(0.6)                    # educado: ~1 petición cada 0,6 s
    if not todo:
        return pd.DataFrame()
    df = pd.DataFrame(todo).drop_duplicates(
        subset=['fecha', 'home', 'away']).sort_values('fecha')
    df.to_csv(salida, index=False)
    logger.info(f"[kbo/cuotas] {salida}: {len(df)} partidos "
                f"({df.fecha.min()} → {df.fecha.max()})")
    return df


def cotejar(ruta: str = SALIDA, historico: str = 'historico_kbo.csv') -> Dict:
    """
    Comprueba que estas cuotas casan con el histórico de Naver.

    No es un adorno: si BetExplorer listara al VISITANTE primero, las cuotas
    quedarían cambiadas de lado y el backtest daría un ROI inventado — sin
    error por ninguna parte. Se compara el ganador que dice cada fuente.
    """
    import os
    if not (os.path.exists(ruta) and os.path.exists(historico)):
        return {'error': 'faltan ficheros'}
    c = pd.read_csv(ruta)
    h = pd.read_csv(historico, parse_dates=['date'])
    h['fecha'] = h['date'].dt.strftime('%Y-%m-%d')
    j = c.merge(h[['fecha', 'home_team', 'away_team', 'home_runs', 'away_runs']],
                left_on=['fecha', 'home', 'away'],
                right_on=['fecha', 'home_team', 'away_team'], how='inner')
    # ¿y si están al revés?
    j_inv = c.merge(h[['fecha', 'home_team', 'away_team', 'home_runs', 'away_runs']],
                    left_on=['fecha', 'home', 'away'],
                    right_on=['fecha', 'away_team', 'home_team'], how='inner')
    coincide = int((j.runs_home == j.home_runs).sum()) if len(j) else 0
    return {'cruzados_mismo_orden': len(j), 'marcador_coincide': coincide,
            'cruzados_orden_inverso': len(j_inv), 'total_cuotas': len(c)}


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    df = ingerir()
    print(json.dumps({'partidos': len(df),
                      'temporadas': sorted(df.temporada.unique().tolist()) if len(df) else [],
                      'cotejo': cotejar()}, ensure_ascii=False, indent=1))
