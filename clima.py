#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clima histórico y futuro con Open-Meteo (v23) — gratuito, sin clave.

Dos APIs públicas:
  - Geocoding:  geocoding-api.open-meteo.com/v1/search  (ciudad+país → lat/lon)
  - Archivo:    archive-api.open-meteo.com/v1/archive    (ERA5 diario)

Estrategia de backfill EFICIENTE: una sola petición de archivo por CIUDAD
cubriendo el rango completo de sus partidos (la API devuelve series diarias),
guardando solo las fechas con partido. ~2 llamadas por ciudad en total.

Caché persistente en clima_cache.json:
  {'geo': {'ciudad|pais': {'lat':..,'lon':..} | null},
   'dias': {'ciudad|pais': {'YYYY-MM-DD': {'tmax','tmin','precip','viento','humedad'}}}}

Variables: temperatura máx/mín (°C), precipitación (mm), viento máx (km/h),
humedad relativa media (%). Ausencias → None (el modelo las imputa).
"""

import json
import logging
import os
import time
from typing import Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ARCHIVO_CACHE = 'clima_cache.json'
GEO_URL = 'https://geocoding-api.open-meteo.com/v1/search'
ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
PAUSA_S = 0.15                    # cortesía con la API gratuita
VARIABLES = ('temperature_2m_max', 'temperature_2m_min', 'precipitation_sum',
             'wind_speed_10m_max', 'relative_humidity_2m_mean')

# La API de geocoding usa nombres en inglés; el histórico de Kaggle también.
_PAIS_ALIAS = {'USA': 'United States', 'DR Congo': 'Democratic Republic of the Congo'}

_cache = None


def _cargar() -> Dict:
    global _cache
    if _cache is None:
        try:
            with open(ARCHIVO_CACHE, encoding='utf-8') as f:
                _cache = json.load(f)
        except Exception:
            _cache = {'geo': {}, 'dias': {}}
    return _cache


def _guardar():
    if _cache is not None:
        with open(ARCHIVO_CACHE, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, ensure_ascii=False)


def _clave(ciudad: str, pais: str) -> str:
    return f'{ciudad}|{pais}'


def geocodificar(ciudad: str, pais: str) -> Optional[Dict]:
    """lat/lon de la ciudad (cacheado; None persistente si no se encuentra)."""
    cache = _cargar()
    k = _clave(ciudad, pais)
    if k in cache['geo']:
        return cache['geo'][k]
    time.sleep(PAUSA_S)
    resultado = None
    try:
        r = requests.get(GEO_URL, params={'name': ciudad, 'count': 10,
                                          'language': 'en'}, timeout=20)
        candidatos = r.json().get('results') or []
        pais_busca = _PAIS_ALIAS.get(pais, pais)
        for c in candidatos:
            if str(c.get('country', '')).lower() == str(pais_busca).lower():
                resultado = {'lat': c['latitude'], 'lon': c['longitude']}
                break
        if resultado is None and candidatos:      # mejor esfuerzo: el primero
            c = candidatos[0]
            resultado = {'lat': c['latitude'], 'lon': c['longitude']}
    except Exception as e:
        logger.warning(f"Geocoding falló para {ciudad}, {pais}: {e}")
        return None                                # transitorio: no se cachea
    cache['geo'][k] = resultado
    return resultado


def _descargar_rango(lat: float, lon: float, desde: str, hasta: str) -> Dict[str, Dict]:
    time.sleep(PAUSA_S)
    r = requests.get(ARCHIVE_URL, params={
        'latitude': lat, 'longitude': lon,
        'start_date': desde, 'end_date': hasta,
        'daily': ','.join(VARIABLES), 'timezone': 'auto'}, timeout=40)
    d = r.json().get('daily') or {}
    fechas = d.get('time') or []
    out = {}
    for i, f in enumerate(fechas):
        def v(nombre):
            serie = d.get(nombre) or []
            return serie[i] if i < len(serie) else None
        tmax = v('temperature_2m_max')
        out[f] = {'tmax': tmax, 'tmin': v('temperature_2m_min'),
                  'precip': v('precipitation_sum'),
                  'viento': v('wind_speed_10m_max'),
                  'humedad': v('relative_humidity_2m_mean')}
    return out


def obtener_clima(ciudad: str, pais: str, fecha: str) -> Optional[Dict]:
    """Clima del día del partido desde la caché (tras el backfill)."""
    if not ciudad or pd.isna(ciudad):
        return None
    dias = _cargar()['dias'].get(_clave(str(ciudad), str(pais)))
    return dias.get(str(fecha)[:10]) if dias else None


def obtener_clima_futuro(ciudad: str, pais: str,
                         fecha: Optional[str] = None) -> Optional[Dict]:
    """Pronóstico (hasta 16 días) para partidos FUTUROS — API forecast.
    Sin fecha usa el día siguiente. Devuelve el mismo formato que la caché."""
    geo = geocodificar(ciudad, pais)
    if not geo:
        return None
    objetivo = (pd.Timestamp(fecha) if fecha
                else pd.Timestamp.today() + pd.Timedelta(days=1))
    dias = min(max((objetivo - pd.Timestamp.today()).days + 1, 1), 16)
    try:
        time.sleep(PAUSA_S)
        r = requests.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': geo['lat'], 'longitude': geo['lon'],
            'daily': ','.join(VARIABLES), 'forecast_days': dias,
            'timezone': 'auto'}, timeout=20)
        d = r.json().get('daily') or {}
        fechas = d.get('time') or []
        idx = min(dias - 1, len(fechas) - 1)
        if idx < 0:
            return None
        def v(nombre):
            serie = d.get(nombre) or []
            return serie[idx] if idx < len(serie) else None
        return {'tmax': v('temperature_2m_max'), 'tmin': v('temperature_2m_min'),
                'precip': v('precipitation_sum'), 'viento': v('wind_speed_10m_max'),
                'humedad': v('relative_humidity_2m_mean')}
    except Exception as e:
        logger.warning(f"Pronóstico falló para {ciudad}: {e}")
        return None


# Lección v23: la API pondera el costo por (ubicaciones × días del rango) —
# lotes multi-ciudad con rango UNIFICADO de 11 años agotan la cuota horaria
# ~10× más rápido que pedir el rango propio de cada ciudad. Lote = 1.
TAMANO_LOTE = 1
ABORTAR_TRAS_FALLOS = 5   # cuota horaria agotada: parar y reanudar después


def _descargar_lote(coords: list, desde: str, hasta: str) -> list:
    """Un solo request para varios puntos: latitude=a,b,c&longitude=... —
    devuelve una lista de bloques 'daily' (o un dict si es un único punto)."""
    time.sleep(PAUSA_S)
    r = requests.get(ARCHIVE_URL, params={
        'latitude': ','.join(f"{c['lat']:.4f}" for c in coords),
        'longitude': ','.join(f"{c['lon']:.4f}" for c in coords),
        'start_date': desde, 'end_date': hasta,
        'daily': ','.join(VARIABLES), 'timezone': 'auto'}, timeout=120)
    data = r.json()
    if isinstance(data, dict) and data.get('error'):
        raise RuntimeError(data.get('reason', 'error de la API'))
    bloques = data if isinstance(data, list) else [data]
    out = []
    for b in bloques:
        d = b.get('daily') or {}
        fechas = d.get('time') or []
        serie = {}
        for i, f in enumerate(fechas):
            def v(nombre):
                s = d.get(nombre) or []
                return s[i] if i < len(s) else None
            serie[f] = {'tmax': v('temperature_2m_max'),
                        'tmin': v('temperature_2m_min'),
                        'precip': v('precipitation_sum'),
                        'viento': v('wind_speed_10m_max'),
                        'humedad': v('relative_humidity_2m_mean')}
        out.append(serie)
    return out


def backfill(df: pd.DataFrame) -> Dict:
    """Descarga el clima de todos los (ciudad, país, fecha) del dataframe en
    LOTES de ciudades (una llamada de archivo por lote — ~50 llamadas en vez
    de ~1,100). Reanudable: lo cacheado no se repite. df: date/city/country."""
    cache = _cargar()
    df = df.dropna(subset=['city']).copy()
    df['date'] = pd.to_datetime(df['date'])
    hoy = pd.Timestamp.today().strftime('%Y-%m-%d')

    # 1) qué ciudades tienen fechas pendientes (y geocodificarlas)
    pendientes_por_ciudad = {}
    for (ciudad, pais), fechas in df.groupby(['city', 'country'])['date']:
        k = _clave(ciudad, pais)
        pend = {f.strftime('%Y-%m-%d') for f in fechas}
        pend -= set((cache['dias'].get(k) or {}).keys())
        pend = {f for f in pend if f <= hoy}
        if pend:
            pendientes_por_ciudad[(ciudad, pais)] = pend
    logger.info(f"clima: {len(pendientes_por_ciudad)} ciudades con fechas pendientes")

    listas, fallo_geo = [], 0
    for i, ((ciudad, pais), pend) in enumerate(sorted(pendientes_por_ciudad.items())):
        geo = geocodificar(ciudad, pais)
        if geo:
            listas.append(((ciudad, pais), geo, pend))
        else:
            fallo_geo += 1
        if (i + 1) % 100 == 0:
            _guardar()
            logger.info(f"clima: geocodificadas {i+1}/{len(pendientes_por_ciudad)}")
    _guardar()

    # 2) lotes con rango unificado (se recorta por ciudad al guardar)
    nuevas, fallo_lote, fallos_seguidos = 0, 0, 0
    for i in range(0, len(listas), TAMANO_LOTE):
        lote = listas[i:i + TAMANO_LOTE]
        desde = min(min(p) for _, _, p in lote)
        hasta = min(max(max(p) for _, _, p in lote), hoy)
        try:
            series = _descargar_lote([g for _, g, _ in lote], desde, hasta)
            fallos_seguidos = 0
        except Exception as e:
            logger.warning(f"Lote de archivo falló ({e}); ciudades omitidas.")
            fallo_lote += len(lote)
            fallos_seguidos += 1
            if fallos_seguidos >= ABORTAR_TRAS_FALLOS:
                logger.warning("clima: cuota agotada — se reanudará en la "
                               "próxima corrida (la caché conserva el avance).")
                break
            continue
        for ((ciudad, pais), _, pend), serie in zip(lote, series):
            propios = {f: v for f, v in serie.items() if f in pend}
            cache['dias'].setdefault(_clave(ciudad, pais), {}).update(propios)
            nuevas += len(propios)
        _guardar()
        logger.info(f"clima: lote {i//TAMANO_LOTE + 1}/"
                    f"{(len(listas)+TAMANO_LOTE-1)//TAMANO_LOTE} · {nuevas} días")
    resumen = {'ciudades_pendientes': len(pendientes_por_ciudad),
               'fallo_geocoding': fallo_geo, 'fallo_lotes': fallo_lote,
               'dias_nuevos': nuevas}
    logger.info(f"Backfill de clima: {resumen}")
    return resumen


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    desde = sys.argv[1] if len(sys.argv) > 1 else '2015-01-01'
    h = pd.read_csv('historico_partidos.csv', usecols=['date', 'city', 'country'])
    h = h[pd.to_datetime(h['date']) >= desde]
    print(json.dumps(backfill(h), indent=2))
