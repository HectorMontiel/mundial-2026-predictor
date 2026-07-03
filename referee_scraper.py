#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper de árbitros (WorldReferee.com) con respaldo a la lista oficial.

Intenta actualizar las estadísticas por-90 de los árbitros designados desde
WorldReferee; si el sitio no responde o cambia su estructura, usa la lista
oficial FIFA pregrabada en `arbitros.py` (fuente WorldReferee 2022-2025).

Salida: `referees.json` — el módulo `arbitros.py` lo carga al importar, de
modo que el motor y la UI siempre usan la versión más reciente disponible.

Ejecución: semanal (incluida en pipeline_mundial.py).
"""

import datetime
import json
import logging
import re
import unicodedata

import requests
from bs4 import BeautifulSoup

from arbitros import ARBITROS

logger = logging.getLogger(__name__)

REFEREES_FILE = 'referees.json'
BASE_URL = 'https://worldreferee.com'
CABECERAS = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36')}


def _slug(nombre: str) -> str:
    s = ''.join(c for c in unicodedata.normalize('NFD', nombre)
                if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z]+', '-', s.lower()).strip('-')


def _scrapear_arbitro(nombre: str, timeout: int = 15) -> dict:
    """
    Best-effort: perfil del árbitro en WorldReferee. Devuelve las claves que
    consiga extraer (ama_p90, roj_p90, pen_p90); vacío si falla.
    """
    url = f"{BASE_URL}/referee/{_slug(nombre)}/bio"
    r = requests.get(url, headers=CABECERAS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, 'lxml')
    texto = soup.get_text(' ', strip=True).lower()
    datos = {}
    m = re.search(r'yellow cards?\D{0,20}([\d.]+)\s*(?:per (?:game|match|90))', texto)
    if m:
        datos['ama_p90'] = float(m.group(1))
    m = re.search(r'red cards?\D{0,20}([\d.]+)\s*(?:per (?:game|match|90))', texto)
    if m:
        datos['roj_p90'] = float(m.group(1))
    m = re.search(r'penalt(?:y|ies)\D{0,20}([\d.]+)\s*(?:per (?:game|match|90))', texto)
    if m:
        datos['pen_p90'] = float(m.group(1))
    return datos


def actualizar_arbitros(intentar_scraping: bool = True) -> dict:
    """
    Genera referees.json: lista oficial pregrabada + actualizaciones que el
    scraping consiga (los valores scrapeados PISAN a los pregrabados).
    """
    resultado = {nombre: dict(perfil) for nombre, perfil in ARBITROS.items()}
    actualizados = 0

    if intentar_scraping:
        for nombre in list(resultado.keys()):
            try:
                datos = _scrapear_arbitro(nombre)
                if datos:
                    resultado[nombre].update(datos)
                    actualizados += 1
            except Exception:
                continue  # el respaldo pregrabado cubre a este árbitro
        if actualizados:
            logger.info(f"WorldReferee: {actualizados} árbitros actualizados por scraping.")
        else:
            logger.info("WorldReferee no accesible: se usa la lista oficial pregrabada.")

    salida = {
        'actualizado': datetime.date.today().isoformat(),
        'fuente': 'worldreferee+fifa' if actualizados else 'lista_oficial_pregrabada',
        'n_scrapeados': actualizados,
        'arbitros': resultado,
    }
    with open(REFEREES_FILE, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    logger.info(f"referees.json escrito: {len(resultado)} árbitros.")
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    actualizar_arbitros()
