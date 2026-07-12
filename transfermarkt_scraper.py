#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Valores de mercado de plantillas desde Transfermarkt (v14/M9) — gratuito.

En lugar de scrapear jugador por jugador (miles de peticiones), usa la página
de RESUMEN de cada liga, que lista el valor total de plantilla de todos los
clubes en UNA sola petición. El valor de plantilla es un proxy de la calidad
individual agregada del equipo.

Ética: 1 petición por liga por día (caché en disco), User-Agent real,
pausa de 8 s si se piden varias ligas seguidas.

SOLO ligas de clubes (los valores de selecciones son engañosos — regla del
usuario). La feature derivada (VAL_LOG_RATIO) se activa con el flag
--ratings de league_engine y solo se adopta si supera el backtest (≥0.5 pp).

ADVERTENCIA metodológica (documentada en VALIDACION_v14.md): los valores son
los ACTUALES; aplicarlos a partidos de temporadas pasadas introduce sesgo de
anticipación (un club que mejoró mucho "sabe" en 2022 lo que vale en 2026).
El backtest con esta feature es por tanto OPTIMISTA y no debe compararse
1:1 con el resto.
"""

import json
import logging
import os
import re
import time
import unicodedata
from typing import Dict

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = 'transfermarkt_cache'
PAUSA_SEGUNDOS = 8
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

LIGAS_TM = {
    'premier': 'premier-league/startseite/wettbewerb/GB1',
    'laliga': 'laliga/startseite/wettbewerb/ES1',
    'serie_a': 'serie-a/startseite/wettbewerb/IT1',
    'bundesliga': 'bundesliga/startseite/wettbewerb/L1',
    'ligue_1': 'ligue-1/startseite/wettbewerb/FR1',
    'eredivisie': 'eredivisie/startseite/wettbewerb/NL1',
    'primeira': 'liga-portugal/startseite/wettbewerb/PO1',
}

# Transfermarkt -> football-data.co.uk (solo donde el matching difuso falla)
ALIAS_TM = {
    'atletico de madrid': 'ath madrid',
    'athletic bilbao': 'ath bilbao',
    'real betis balompie': 'betis',
    'celta de vigo': 'celta',
    'rayo vallecano': 'vallecano',
    'deportivo alaves': 'alaves',
    'manchester united': 'man united',
    'manchester city': 'man city',
    'newcastle united': 'newcastle',
    'wolverhampton wanderers': 'wolves',
    'nottingham forest': "nott'm forest",
    'tottenham hotspur': 'tottenham',
    'west ham united': 'west ham',
    'brighton amp hove albion': 'brighton',
    'borussia monchengladbach': "m'gladbach",
    'bayer 04 leverkusen': 'leverkusen',
    'rb leipzig': 'rb leipzig',
    'eintracht frankfurt': 'ein frankfurt',
    '1 fc koln': 'fc koln',
    '1 fc union berlin': 'union berlin',
    '1 fsv mainz 05': 'mainz',
    'borussia dortmund': 'dortmund',
    'paris saint-germain': 'paris sg',
    'as saint-etienne': 'st etienne',
    'psv eindhoven': 'psv eindhoven',
    'inter milan': 'inter',
    'ac milan': 'milan',
    'juventus fc': 'juventus',
    'as roma': 'roma',
    'ss lazio': 'lazio',
    'ssc napoli': 'napoli',
    'hellas verona': 'verona',
    'sporting cp': 'sp lisbon',
    'fc porto': 'porto',
    'sl benfica': 'benfica',
}


def _normalizar(nombre: str) -> str:
    s = unicodedata.normalize('NFKD', str(nombre))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()
    s = re.sub(r'[^\w\s\']', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _valor_a_millones(texto: str) -> float:
    """'€1.34bn' -> 1340.0 ; '€245.30m' -> 245.3 ; '€900k' -> 0.9"""
    m = re.search(r'€([\d.]+)\s*(bn|m|k)', texto)
    if not m:
        return float('nan')
    v = float(m.group(1))
    return v * {'bn': 1000.0, 'm': 1.0, 'k': 0.001}[m.group(2)]


def valores_liga(clave: str, forzar: bool = False) -> Dict[str, float]:
    """{nombre_equipo_transfermarkt: valor_plantilla_en_millones_EUR}.

    Cachea 24 h por liga. Devuelve {} si la liga no está soportada o falla.
    """
    if clave not in LIGAS_TM:
        return {}
    os.makedirs(CACHE_DIR, exist_ok=True)
    ruta = os.path.join(CACHE_DIR, f'{clave}.json')
    if os.path.exists(ruta) and not forzar:
        if (time.time() - os.path.getmtime(ruta)) / 3600 < 24:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
    try:
        from bs4 import BeautifulSoup
        r = requests.get(f'https://www.transfermarkt.com/{LIGAS_TM[clave]}',
                         headers={'User-Agent': UA}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        valores: Dict[str, float] = {}
        tabla = soup.select_one('table.items')
        if tabla is None:
            raise RuntimeError('tabla de clubes no encontrada')
        for tr in tabla.select('tbody > tr'):
            club_el = tr.select_one('td.hauptlink a')
            celdas = tr.select('td.rechts')
            if club_el is None or not celdas:
                continue
            valor = _valor_a_millones(celdas[-1].get_text(strip=True))
            if valor == valor:  # not NaN
                valores[club_el.get_text(strip=True)] = valor
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(valores, f, ensure_ascii=False)
        logger.info(f"[transfermarkt] {clave}: {len(valores)} clubes con valor de plantilla.")
        time.sleep(PAUSA_SEGUNDOS)
        return valores
    except Exception as e:
        logger.warning(f"[transfermarkt] {clave} no disponible ({e}).")
        return {}


def mapear_a_football_data(valores: Dict[str, float],
                           equipos_fd: list) -> Dict[str, float]:
    """Convierte las claves Transfermarkt a los nombres de football-data."""
    import difflib
    indice_fd = {_normalizar(e): e for e in equipos_fd}
    resultado: Dict[str, float] = {}
    for nombre_tm, valor in valores.items():
        norm = _normalizar(nombre_tm)
        candidato = ALIAS_TM.get(norm, norm)
        if candidato in indice_fd:
            resultado[indice_fd[candidato]] = valor
            continue
        cerca = difflib.get_close_matches(candidato, indice_fd.keys(), n=1, cutoff=0.6)
        if cerca:
            resultado[indice_fd[cerca[0]]] = valor
        else:
            logger.debug(f"[transfermarkt] sin mapeo: {nombre_tm}")
    return resultado


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--liga', required=True, choices=list(LIGAS_TM))
    args = parser.parse_args()
    vals = valores_liga(args.liga, forzar=True)
    for club, v in sorted(vals.items(), key=lambda kv: -kv[1]):
        print(f"{club:35s} €{v:8.1f}M")
