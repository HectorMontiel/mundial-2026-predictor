#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibración con StatsBomb Open Data.

Aprende, a partir de partidos de Mundial con xG real de alta calidad, las
relaciones causales que el generador correlacionado usa para rellenar las
métricas avanzadas que faltan en el histórico de resultados:

    goles reales  ->  xG esperado        (E[xG | goles] + dispersión)
    xG            ->  remates al arco    (remates por unidad de xG)
    remates arco  ->  remates totales

Descarga una muestra de eventos del Mundial 2022 (open-data de StatsBomb en
GitHub) UNA sola vez y cachea el resultado en `calibracion_statsbomb.json`.
Si no hay red o falla la descarga, usa priors documentados de la literatura
futbolística (valores medios de torneos FIFA), que son suficientes para
mantener la coherencia causal.
"""

import json
import logging
import os

import numpy as np
import requests

logger = logging.getLogger(__name__)

CALIBRACION_FILE = 'calibracion_statsbomb.json'
BASE_URL = 'https://raw.githubusercontent.com/statsbomb/open-data/master/data'
COMPETENCIA_MUNDIAL, TEMPORADA_2022 = 43, 106   # FIFA World Cup 2022

# Priors documentados (medias de torneos FIFA) usados como fallback
PRIORS = {
    'xg_intercept': 0.45,        # xG base de un equipo que no anota
    'xg_slope_goles': 0.65,      # xG adicional por gol real anotado
    'xg_residual_std': 0.45,     # dispersión del xG alrededor de la relación
    'shots_on_por_xg': 3.1,      # remates al arco por unidad de xG
    'shots_total_por_on': 2.6,   # remates totales por remate al arco
    'fuente': 'priors_literatura',
    'n_partidos_calibrados': 0,
}


def _xg_y_remates_de_partido(match_id: int, timeout: int = 30):
    """Agrega los eventos de tiro de un partido: (equipo -> xG, remates, al arco, goles)."""
    url = f"{BASE_URL}/events/{match_id}.json"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    eventos = r.json()
    agregados = {}
    for e in eventos:
        if e.get('type', {}).get('name') != 'Shot':
            continue
        equipo = e['team']['name']
        shot = e.get('shot', {})
        a = agregados.setdefault(equipo, {'xg': 0.0, 'remates': 0, 'al_arco': 0, 'goles': 0})
        a['xg'] += float(shot.get('statsbomb_xg', 0.0))
        a['remates'] += 1
        resultado = shot.get('outcome', {}).get('name', '')
        if resultado in ('Goal', 'Saved', 'Saved To Post'):
            a['al_arco'] += 1
        if resultado == 'Goal':
            a['goles'] += 1
    return agregados


def calibrar(n_partidos: int = 10, forzar: bool = False) -> dict:
    """
    Devuelve el diccionario de calibración. Orden de preferencia:
      1. Caché en disco (calibracion_statsbomb.json).
      2. Descarga de una muestra de n_partidos del Mundial 2022.
      3. Priors documentados.
    """
    if not forzar and os.path.exists(CALIBRACION_FILE):
        try:
            with open(CALIBRACION_FILE, 'r', encoding='utf-8') as f:
                cal = json.load(f)
            logger.info(f"Calibración cargada de caché (fuente: {cal.get('fuente')}).")
            return cal
        except Exception:
            pass

    try:
        url = f"{BASE_URL}/matches/{COMPETENCIA_MUNDIAL}/{TEMPORADA_2022}.json"
        partidos = requests.get(url, timeout=30).json()
        muestra = partidos[:n_partidos]
        logger.info(f"Calibrando con {len(muestra)} partidos del Mundial 2022 (StatsBomb)...")

        filas = []  # (goles, xg, remates, al_arco) por equipo-partido
        for p in muestra:
            agg = _xg_y_remates_de_partido(p['match_id'])
            for equipo, a in agg.items():
                filas.append((a['goles'], a['xg'], a['remates'], a['al_arco']))

        if len(filas) < 10:
            raise RuntimeError("Muestra insuficiente para calibrar.")

        goles = np.array([f[0] for f in filas], dtype=float)
        xg = np.array([f[1] for f in filas], dtype=float)
        remates = np.array([f[2] for f in filas], dtype=float)
        al_arco = np.array([f[3] for f in filas], dtype=float)

        # Regresión lineal simple xG ~ goles (con np.polyfit, sin dependencias extra)
        slope, intercept = np.polyfit(goles, xg, 1)
        residuos = xg - (slope * goles + intercept)

        cal = {
            'xg_intercept': round(float(max(0.1, intercept)), 3),
            'xg_slope_goles': round(float(np.clip(slope, 0.2, 1.2)), 3),
            'xg_residual_std': round(float(np.clip(residuos.std(), 0.2, 0.8)), 3),
            'shots_on_por_xg': round(float(np.clip((al_arco.sum() / max(xg.sum(), 1e-6)), 1.5, 5.0)), 3),
            'shots_total_por_on': round(float(np.clip((remates.sum() / max(al_arco.sum(), 1e-6)), 1.5, 4.0)), 3),
            'fuente': 'statsbomb_wc2022',
            'n_partidos_calibrados': len(muestra),
        }
        with open(CALIBRACION_FILE, 'w', encoding='utf-8') as f:
            json.dump(cal, f, indent=2)
        logger.info(f"Calibración StatsBomb completada: {cal}")
        return cal

    except Exception as e:
        logger.warning(f"Calibración StatsBomb no disponible ({e}). Usando priors documentados.")
        with open(CALIBRACION_FILE, 'w', encoding='utf-8') as f:
            json.dump(PRIORS, f, indent=2)
        return dict(PRIORS)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(calibrar(forzar=True), indent=2))
