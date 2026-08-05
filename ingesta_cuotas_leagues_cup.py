#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v100 — Cuotas de cierre históricas de la Leagues Cup (BetExplorer).

Por qué hacía falta
-------------------
La Leagues Cup se validaba por PRECISIÓN contra el ELO sobre las ediciones
pasadas, y el pliegue de juicio son **62 partidos**. Con esa muestra el
intervalo del bootstrap es de ±10 pp: ninguna mejora, por buena que sea, puede
demostrarse. Pero el criterio de Capa 1 nunca fue la precisión — es el **ROI
contra la cuota de cierre**, y para eso sirven los 1X2 de las tres ediciones
enteras, no sólo los 62 de la última.

BetExplorer publica la competición por temporadas en rutas planas que su
`robots.txt` permite (sólo prohíbe cadenas de consulta), con las tres cuotas
(1, X, 2) en `data-odd`, el marcador y la fecha.
"""

import logging
import os
import re
import time
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

BASE = 'https://www.betexplorer.com'
SALIDA = 'cuotas_leagues_cup_cierre.csv'
UA = {'User-Agent': 'Mozilla/5.0'}
RUTAS = [
    '/football/north-central-america/leagues-cup-{a}/results/',
    '/football/usa/leagues-cup-{a}/results/',
]
TEMPORADAS = (2019, 2021, 2023, 2024, 2025, 2026)

RE_FILA = re.compile(
    r'<tr>\s*<td class="h-text-left">\s*<a[^>]*href="(/football/[^"]*?/'
    r'[A-Za-z0-9]{8}/)"[^>]*>(.*?)</a>\s*</td>\s*'
    r'<td class="h-text-center">(.*?)</td>(.*?)</tr>', re.S)
RE_MARCADOR = re.compile(r'>\s*(\d+):(\d+)\s*<')
RE_ODD = re.compile(r'data-odd="([\d.]+)"')
RE_FECHA = re.compile(r'>(\d{2}\.\d{2}\.\d{4})<')
RE_RELATIVA = re.compile(r'>(Today|Yesterday)<')
RE_TAG = re.compile(r'<[^>]+>')


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
        time.sleep(1.2 * (i + 1))
    raise RuntimeError(f'betexplorer no respondió: {ultimo}')


def _traducir(nombre: str):
    """Nombre de BetExplorer -> nombre canónico del proyecto."""
    import leagues_cup as lc
    n = re.sub(r'\s+', ' ', nombre).strip()
    if n in lc.ALIAS:
        return lc.ALIAS[n]
    # BetExplorer usa grafías propias; se resuelve contra los dos catálogos
    import name_mapper
    destino = sorted(set(lc.ALIAS.values()))
    return name_mapper.mapear(n, destino, contexto='betexplorer→leagues_cup')


def temporada(anio: int) -> List[dict]:
    filas = []
    for plantilla in RUTAS:
        try:
            html = _get(BASE + plantilla.format(a=anio))
        except Exception:
            continue
        for m in RE_FILA.finditer(html):
            equipos_html, marc_html, cola = m.group(2), m.group(3), m.group(4)
            marc = RE_MARCADOR.search(marc_html)
            if not marc:
                continue
            gh, ga = int(marc.group(1)), int(marc.group(2))
            nombres = [RE_TAG.sub('', x).strip()
                       for x in re.findall(r'<span>.*?</span>', equipos_html, re.S)]
            if len(nombres) < 2:
                continue
            h, a = _traducir(nombres[0]), _traducir(nombres[1])
            if not h or not a or h == a:
                continue
            odds = RE_ODD.findall(cola)
            if len(odds) < 3:                    # 1, X, 2
                continue
            f = RE_FECHA.search(cola)
            if f:
                d, mes, y = f.group(1).split('.')
                fecha = f'{y}-{mes}-{d}'
            else:
                rel = RE_RELATIVA.search(cola)
                if not rel:
                    continue
                delta = 0 if rel.group(1) == 'Today' else 1
                fecha = (pd.Timestamp.today().normalize()
                         - pd.Timedelta(days=delta)).strftime('%Y-%m-%d')
            filas.append({
                'fecha': fecha, 'temporada': anio, 'home': h, 'away': a,
                'goles_home': gh, 'goles_away': ga,
                'res': 0 if gh > ga else (1 if gh == ga else 2),
                'odd_home': float(odds[0]), 'odd_draw': float(odds[1]),
                'odd_away': float(odds[2])})
        if filas:
            break                                # la primera ruta que sirva
    logger.info(f'[lc/cuotas] {anio}: {len(filas)} partidos con cierre')
    return filas


def ingerir(salida: str = SALIDA) -> pd.DataFrame:
    todo = []
    for a in TEMPORADAS:
        try:
            todo += temporada(a)
        except Exception as e:
            logger.warning(f'[lc/cuotas] {a}: {e}')
        time.sleep(0.6)
    if not todo:
        return pd.DataFrame()
    df = pd.DataFrame(todo)
    if os.path.exists(salida):
        try:
            df = pd.concat([pd.read_csv(salida), df], ignore_index=True)
        except Exception:
            pass
    df = df.drop_duplicates(subset=['fecha', 'home', 'away'],
                            keep='last').sort_values('fecha')
    df.to_csv(salida, index=False)
    logger.info(f'[lc/cuotas] {salida}: {len(df)} partidos '
                f'({df.fecha.min()} → {df.fecha.max()})')
    return df


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    d = ingerir()
    print(json.dumps({'partidos': len(d),
                      'por_temporada': d.temporada.value_counts().sort_index().to_dict()
                      if len(d) else {}}, ensure_ascii=False, indent=1))
