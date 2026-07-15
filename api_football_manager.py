#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gateway centralizado hacia API-Football (v21) — plan Free: 100 requests/día.

TODA petición a v3.football.api-sports.io debe pasar por `api_call()`:

  - Contador diario persistente (api_football_state.json), reinicio 00:00 UTC,
    sincronizado con las cabeceras x-ratelimit de cada respuesta.
  - Caché agresiva en api_football_cache/ con TTL por tipo de dato
    (alineaciones 1 h, estadísticas permanentes, cuotas 3 h, lesiones 6 h,
    H2H 24 h). Un dato en caché vigente NO consume request.
  - Prioridades con reserva de presupuesto: una petición de prioridad baja
    solo se ejecuta si quedan requests suficientes para las tareas críticas.
  - Degradación elegante: sin clave, sin crédito o con error de red devuelve
    None y registra un warning — nunca rompe al llamador.

La clave se resuelve SIN commitearse al repo (la app es pública):
  1. variable de entorno API_FOOTBALL_KEY
  2. st.secrets['API_FOOTBALL_KEY'] (Streamlit Cloud → Settings → Secrets)
  3. .streamlit/secrets.toml local (gitignorado)
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = 'https://v3.football.api-sports.io'
LIMITE_DIARIO = 100
# El plan Free TAMBIÉN limita por minuto (~10 req/min, verificado 2026-07-14:
# ráfagas seguidas devuelven {'rateLimit': 'Too many requests...'} y queman
# presupuesto). Se espacia cada petición y se reintenta con pausa.
INTERVALO_MIN_S = 6.5
REINTENTOS_RATE_LIMIT = 2
PAUSA_RATE_LIMIT_S = 15.0
ARCHIVO_ESTADO = 'api_football_state.json'
DIRECTORIO_CACHE = 'api_football_cache'

_ultima_peticion = [0.0]     # timestamp del último request real (por proceso)

# TTL de caché en segundos por endpoint (None = permanente: datos históricos
# que no cambian). El llamador puede sobreescribirlo con ttl=...
TTL_POR_ENDPOINT = {
    'status': 600,
    'fixtures/lineups': 3600,          # alineaciones: 1 h
    'fixtures/statistics': None,       # stats de partidos jugados: permanente
    'fixtures/headtohead': 24 * 3600,  # H2H: 24 h
    'odds': 3 * 3600,                  # cuotas pre-partido: 3 h
    'sidelined': 6 * 3600,             # lesiones/sanciones: 6 h
    'injuries': 6 * 3600,
    'fixtures': 6 * 3600,              # fixtures del día: 6 h (histórico:
                                       # pasar ttl=None desde el llamador)
    'players': 24 * 3600,
    'teams': None,
    'leagues': 7 * 24 * 3600,
}

# Reserva de presupuesto por prioridad (jerarquía de la spec v21 §2): una
# petición de prioridad p solo procede si tras ejecutarla quedarían al menos
# RESERVAS[p] requests para las tareas más críticas del día.
RESERVAS = {1: 0, 2: 5, 3: 10, 4: 20, 5: 35, 6: 45, 7: 60}


# ---------------------------------------------------------------------------
# Clave
# ---------------------------------------------------------------------------
def api_key() -> Optional[str]:
    key = os.getenv('API_FOOTBALL_KEY')
    if key:
        return key.strip()
    try:                                   # Streamlit Cloud (Settings→Secrets)
        import streamlit as st
        if hasattr(st, 'secrets') and 'API_FOOTBALL_KEY' in st.secrets:
            return str(st.secrets['API_FOOTBALL_KEY']).strip()
    except Exception:
        pass
    ruta = os.path.join('.streamlit', 'secrets.toml')   # local, gitignorado
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8') as f:
                for linea in f:
                    if linea.split('=')[0].strip() == 'API_FOOTBALL_KEY':
                        return linea.split('=', 1)[1].strip().strip('"\'')
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Contador diario (UTC)
# ---------------------------------------------------------------------------
def _hoy_utc() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _leer_estado() -> Dict:
    try:
        with open(ARCHIVO_ESTADO, encoding='utf-8') as f:
            estado = json.load(f)
    except Exception:
        estado = {}
    if estado.get('fecha') != _hoy_utc():
        estado = {'fecha': _hoy_utc(), 'usados': 0}
    return estado


def _guardar_estado(estado: Dict):
    try:
        with open(ARCHIVO_ESTADO, 'w', encoding='utf-8') as f:
            json.dump(estado, f)
    except Exception:
        pass


def requests_restantes() -> int:
    return max(0, LIMITE_DIARIO - _leer_estado()['usados'])


# ---------------------------------------------------------------------------
# Caché
# ---------------------------------------------------------------------------
def _ruta_cache(endpoint: str, params: Dict) -> str:
    firma = endpoint + '|' + json.dumps(params, sort_keys=True)
    nombre = hashlib.md5(firma.encode()).hexdigest()[:20]
    return os.path.join(DIRECTORIO_CACHE, f"{endpoint.replace('/', '_')}_{nombre}.json")


def _leer_cache(ruta: str, ttl: Optional[float]) -> Optional[Dict]:
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding='utf-8') as f:
            entrada = json.load(f)
        if ttl is not None and time.time() - entrada['guardado'] > ttl:
            return None
        return entrada['data']
    except Exception:
        return None


def _guardar_cache(ruta: str, data: Dict):
    try:
        os.makedirs(DIRECTORIO_CACHE, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump({'guardado': time.time(), 'data': data}, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Llamada principal
# ---------------------------------------------------------------------------
def api_call(endpoint: str, params: Optional[Dict] = None, *,
             prioridad: int = 7, ttl: Optional[float] = 'auto',
             forzar: bool = False) -> Optional[Dict]:
    """
    JSON completo de API-Football (claves: response, results, errors, paging)
    o None si no hay clave/crédito/red. `ttl='auto'` usa TTL_POR_ENDPOINT;
    `ttl=None` = caché permanente; `forzar=True` ignora la caché (no el límite).
    """
    params = params or {}
    endpoint = endpoint.strip('/')
    if ttl == 'auto':
        ttl = TTL_POR_ENDPOINT.get(endpoint, 6 * 3600)

    ruta = _ruta_cache(endpoint, params)
    if not forzar:
        data = _leer_cache(ruta, ttl)
        if data is not None:
            return data

    key = api_key()
    if not key:
        logger.warning("API-Football: sin clave (API_FOOTBALL_KEY) — se omite la petición.")
        return None

    estado = _leer_estado()
    reserva = RESERVAS.get(int(prioridad), RESERVAS[7])
    if estado['usados'] + 1 > LIMITE_DIARIO - reserva:
        logger.warning(f"API-Football: presupuesto agotado para prioridad {prioridad} "
                       f"({estado['usados']}/{LIMITE_DIARIO} usados, reserva {reserva}).")
        return None

    data = None
    for intento in range(1 + REINTENTOS_RATE_LIMIT):
        # respeto del límite POR MINUTO: espaciado mínimo entre peticiones
        espera = INTERVALO_MIN_S - (time.time() - _ultima_peticion[0])
        if espera > 0:
            time.sleep(espera)
        try:
            _ultima_peticion[0] = time.time()
            r = requests.get(f"{BASE_URL}/{endpoint}", params=params,
                             headers={'x-apisports-key': key}, timeout=25)
            estado['usados'] += 1
            _guardar_estado(estado)
            data = r.json()
            # el contador del SERVIDOR es la verdad (las peticiones rechazadas
            # por límite de minuto no gastan cuota diaria — verificado):
            # cabecera x-ratelimit o, en /status, el propio cuerpo
            restante_srv = r.headers.get('x-ratelimit-requests-remaining')
            if restante_srv is not None:
                try:
                    estado['usados'] = LIMITE_DIARIO - int(restante_srv)
                except ValueError:
                    pass
            if endpoint == 'status':
                try:
                    estado['usados'] = int(data['response']['requests']['current'])
                except (KeyError, TypeError, ValueError):
                    pass
            _guardar_estado(estado)
        except Exception as e:
            _guardar_estado(estado)
            logger.warning(f"API-Football: fallo de red en /{endpoint}: "
                           f"{type(e).__name__}: {e}")
            return None
        errores = data.get('errors')
        if isinstance(errores, dict) and 'rateLimit' in errores \
                and intento < REINTENTOS_RATE_LIMIT:
            logger.info(f"API-Football: límite por minuto — pausa de "
                        f"{PAUSA_RATE_LIMIT_S:.0f}s y reintento ({intento + 1}).")
            time.sleep(PAUSA_RATE_LIMIT_S)
            continue
        break

    errores = data.get('errors')
    if errores and (not isinstance(errores, list) or len(errores)):
        # se devuelve igualmente (el llamador decide), pero NO se cachea para
        # no fosilizar errores transitorios; queda registrado
        logger.warning(f"API-Football /{endpoint} {params}: errores {errores}")
        return data

    _guardar_cache(ruta, data)
    return data


def resumen_estado() -> Dict:
    """Para la UI/pipeline: uso del día y disponibilidad de la clave."""
    estado = _leer_estado()
    return {'fecha_utc': estado['fecha'], 'usados': estado['usados'],
            'limite': LIMITE_DIARIO, 'restantes': requests_restantes(),
            'clave_configurada': api_key() is not None}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print(json.dumps(resumen_estado(), indent=2))
