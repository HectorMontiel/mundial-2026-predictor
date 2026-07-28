#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v71 — Capa de cuotas UNIVERSAL, sin cuota de peticiones.

El problema que resuelve
------------------------
La app mostraba «🎯 Sin cuota en vivo» en casi todos los picks y la Capa 1 se
quedaba vacía. La causa, medida el 2026-07-28: **The Odds API tenía la cuota
mensual agotada** (`x-requests-remaining: 0` de 500). La arquitectura gastaba
una petición POR LIGA y hasta 3 capturas al día, así que con ~20 ligas el saldo
se fundía en días y el resto del mes se apostaba a ciegas.

No era, como parecía, que esas ligas no estuviesen cubiertas: Liga MX, Brasil,
Rusia y Argentina están todas activas en The Odds API. Era el saldo.

La solución no es racionar mejor, es no depender de una fuente con cuota.

Fuentes (por orden de preferencia)
----------------------------------
1. **Pinnacle** (`guest.api.arcadia.pinnacle.com`) — el endpoint público que
   usa su propia web. **Sin clave propia, sin límite de peticiones.** Dos
   llamadas por deporte lo traen TODO:
       /0.1/sports/{id}/matchups          → partidos, liga, participantes
       /0.1/sports/{id}/markets/straight  → todos los precios de una vez
   Medido: 624 partidos de fútbol, **301 de tenis**, 24 de béisbol y 26 de
   baloncesto, con 1X2, totales y hándicaps. Y es la casa más eficiente del
   mercado, que es justo la referencia que el proyecto ya usa para el CLV y el
   `sharp_gap`.

2. **ESPN scoreboard** — las cuotas vienen en el MISMO JSON que los fixtures,
   así que son gratis en el sentido literal: cero peticiones extra. Cobertura
   medida: 32 % de los fixtures (106/330), muy buena en Liga MX (9/9), USL
   (14/14) y MLS (15/16), nula en tenis y en varias sudamericanas.

3. **ESPN core API** por evento — recupera casos donde el scoreboard trae
   `odds: [null]`. Medido: **12/12 en MLB**, que en el scoreboard daba 0.

4. **The Odds API** — se conserva, pero deja de ser la columna vertebral y pasa
   a refuerzo: solo se usa si quedan créditos, y para lo que aporta de verdad
   (más casas para el line shopping).

Con 1+2+3 no hace falta ninguna clave y no hay límite: **ningún partido debería
quedarse sin cuota**.

Line shopping
-------------
`cuotas_partido()` devuelve TODAS las casas que dieron precio, la mejor cuota
por selección con su casa, y Pinnacle aparte como ancla sharp. Es lo que la
Capa 1 necesita para decidir con EV real en vez de con cuota justa.

Uso:
    from cuotas_multi import cuotas_partido, precargar
    precargar('futbol')
    c = cuotas_partido('futbol', 'Guadalajara', 'Puebla')
"""
import json
import logging
import os
import threading
import time
import unicodedata
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Clave pública que la propia web de Pinnacle envía desde el navegador. No es
# una credencial de usuario ni da acceso a cuenta: solo lee el tablón público.
PIN_BASE = 'https://guest.api.arcadia.pinnacle.com/0.1'
PIN_KEY = 'CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R'
PIN_HEADERS = {'User-Agent': 'Mozilla/5.0', 'X-API-Key': PIN_KEY,
               'Accept': 'application/json'}

# deporte del proyecto -> id de Pinnacle
DEPORTES = {'futbol': 29, 'tenis': 33, 'mlb': 3, 'nba': 4}

CACHE_DIR = 'cuotas_cache'
TTL = 1800                     # 30 min: las líneas se mueven, pero no tanto
_LOCK = threading.Lock()
_MEM: Dict[str, tuple] = {}      # deporte -> (timestamp, índice Pinnacle)
_MEM_BOV: Dict[str, tuple] = {}  # deporte -> (timestamp, índice Bovada)
_MEM_PDT: Dict[str, tuple] = {}  # v76: deporte -> (timestamp, índice Playdoit)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def american_a_decimal(precio) -> Optional[float]:
    """Cuota americana → decimal."""
    try:
        p = float(precio)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return round(1 + p / 100.0, 4) if p > 0 else round(1 + 100.0 / abs(p), 4)


# Equivalencias de transliteración y de nombre corto que ninguna medida de
# similitud resuelve sola. Medidas contra el tablón real de Pinnacle.
EQUIVALENCIAS = {
    'dynamo': 'dinamo', 'zenith': 'zenit', 'spartak': 'spartak',
    'lokomotiv': 'locomotiv', 'krylia': 'krylya', 'cska': 'cska',
    'atletico': 'atl', 'athletico': 'atl', 'atlético': 'atl',
    'gremio': 'gremio', 'gremio fbpa': 'gremio',
    'sao': 'sao', 'saopaulo': 'sao paulo',
    'wanderers': 'wanderers', 'nacional': 'nacional',
}

# Palabras que no distinguen a un club y solo meten ruido en la comparación
RUIDO_CLUB = {
    'fc', 'cf', 'sc', 'ac', 'afc', 'cd', 'ud', 'sd', 'ec', 'fk', 'sk', 'nk',
    'club', 'clube', 'deportivo', 'atletico', 'atlético', 'athletic', 'real',
    'sporting', 'united', 'city', 'de', 'do', 'da', 'del', 'the', 'if', 'ff',
    'bk', 'ik', 'cr', 'ca', 'aa', 'se', 'esporte', 'futebol', 'futbol', 'rj',
    'sp', 'mg', 'rs', 'pr', 'sc2', 'u20', 'ii', 'b',
}


def normalizar(nombre: str) -> str:
    """Clave de comparación: sin acentos, sin puntuación, sin sufijos de club."""
    if not nombre:
        return ''
    s = unicodedata.normalize('NFKD', str(nombre))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    for ch in ".,-'()/&":
        s = s.replace(ch, ' ')
    partes = [EQUIVALENCIAS.get(p, p) for p in s.split()]
    return ' '.join(partes)


def _tokens_club(nombre: str) -> set:
    """Palabras significativas de un nombre de club (sin las de relleno)."""
    return {t for t in normalizar(nombre).split()
            if t and t not in RUIDO_CLUB and len(t) > 1}


def _sim_club(a: str, b: str) -> float:
    """
    Similitud entre dos nombres de club: Jaccard de palabras significativas,
    reforzado con similitud de cadena. Un solo token compartido y fuerte
    ('palmeiras', 'zenit') ya identifica al equipo, que es como escriben las
    casas: «Gremio» y «Gremio FBPA» son el mismo club.
    """
    from difflib import SequenceMatcher
    ta, tb = _tokens_club(a), _tokens_club(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if inter and (inter == ta or inter == tb):
        return 1.0                      # uno contiene al otro: mismo club
    jac = len(inter) / len(ta | tb)
    cad = SequenceMatcher(None, ' '.join(sorted(ta)), ' '.join(sorted(tb))).ratio()
    return max(jac, 0.5 * jac + 0.5 * cad)


def _clave_tenista(nombre: str) -> tuple:
    """
    (apellido, inicial) de un tenista, escriba quien lo escriba.

    Las fuentes del proyecto usan «Mensik J.» y Pinnacle «Jakub Mensik»: sin
    esto no empareja ni uno. Se detecta el formato por la posición del punto.
    """
    s = normalizar(nombre)
    partes = [p for p in s.split() if p]
    if not partes:
        return ('', '')
    crudo = str(nombre).strip()
    if '.' in crudo:
        # formato «Apellido X.» (puede llevar apellido compuesto)
        sin_inicial = [p for p in partes if len(p) > 1]
        inicial = next((p for p in partes if len(p) == 1), '')
        if sin_inicial:
            return (sin_inicial[-1] if len(sin_inicial) == 1 else sin_inicial[0],
                    inicial)
    # formato «Nombre Apellido»
    return (partes[-1], partes[0][:1])


def _sim_tenista(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    ap_a, in_a = _clave_tenista(a)
    ap_b, in_b = _clave_tenista(b)
    if not ap_a or not ap_b:
        return 0.0
    sim_ap = SequenceMatcher(None, ap_a, ap_b).ratio()
    if sim_ap < 0.85:
        # apellido compuesto: puede estar en la otra posición
        ta, tb = set(normalizar(a).split()), set(normalizar(b).split())
        comunes = {t for t in ta & tb if len(t) > 2}
        if comunes:
            sim_ap = 0.9
        else:
            return 0.0
    if in_a and in_b and in_a != in_b:
        return 0.0                       # mismo apellido, jugador distinto
    return sim_ap


def _cache_path(nombre: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, nombre)


def _leer_cache(clave: str, ttl: int = TTL):
    p = _cache_path(clave)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        try:
            with open(p, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _escribir_cache(clave: str, datos) -> None:
    try:
        with open(_cache_path(clave), 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False)
    except Exception:
        pass


def _get(url, params=None, headers=None, timeout=40, intentos=3):
    for i in range(intentos):
        try:
            r = requests.get(url, params=params, headers=headers or PIN_HEADERS,
                             timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == intentos - 1:
                logger.debug(f"[cuotas] {url}: {type(e).__name__}: {e}")
            time.sleep(1.0 * (i + 1))
    return None


# ---------------------------------------------------------------------------
# 1. Pinnacle — dos llamadas por deporte lo traen todo
# ---------------------------------------------------------------------------
def _indice_pinnacle(deporte: str) -> Dict[str, dict]:
    """
    {clave_partido: {'home','away','liga','fecha','cuotas':{...}}}

    La clave es `normalizar(home)|normalizar(away)`, que es con lo que después
    se cruza contra los nombres del proyecto.
    """
    sid = DEPORTES.get(deporte)
    if not sid:
        return {}
    cacheado = _leer_cache(f'pinnacle_{deporte}.json')
    if cacheado is not None:
        return cacheado

    # v75: `withSpecials=true`. Con `false` se perdía el mercado **Both Teams
    # To Score?**, que Pinnacle SÍ publica en este mismo endpoint (medido el
    # 2026-07-28: 102 partidos con precio Sí y No, gratis y sin límite). Es la
    # única fuente sharp de BTTS que existe para el proyecto: football-data no
    # publica ninguna columna BTTS en NINGÚN formato — verificado sobre los 132
    # campos de /mmz4281/ (E0, SC0) y los 25 de /new/ (MEX, JPN) —, así que sin
    # esto el mercado BTTS no tenía forma de acumular histórico jamás.
    # Los specials llegan como matchups aparte, con `parent` apuntando al
    # partido y participantes 'Yes'/'No'; el bucle de abajo los aparta antes de
    # construir el índice 1X2 para no confundirlos con partidos.
    partidos = _get(f'{PIN_BASE}/sports/{sid}/matchups',
                    {'withSpecials': 'true', 'brandId': 0})
    mercados = _get(f'{PIN_BASE}/sports/{sid}/markets/straight',
                    {'primaryOnly': 'false', 'withSpecials': 'true'})
    if not partidos or not mercados:
        logger.warning(f"[pinnacle] {deporte}: sin respuesta")
        return {}

    # precios por matchupId (solo periodo 0 = partido completo)
    por_id: Dict[int, dict] = {}
    for mk in mercados:
        if mk.get('period') != 0 or mk.get('isAlternate'):
            continue
        mid = mk.get('matchupId')
        tipo = mk.get('type')
        precios = {p.get('designation'): p.get('price')
                   for p in (mk.get('prices') or [])}
        d = por_id.setdefault(mid, {})
        # v75: precios en crudo (con su participantId) — los specials como BTTS
        # no usan `designation` sino participantes nombrados 'Yes'/'No'.
        d.setdefault('_precios', []).extend(mk.get('prices') or [])
        if tipo == 'moneyline':
            d['moneyline'] = precios
        elif tipo == 'total':
            linea = None
            for p in (mk.get('prices') or []):
                if p.get('points') is not None:
                    linea = p['points']
                    break
            if linea is not None:
                d.setdefault('totales', {})[str(linea)] = precios
        elif tipo == 'spread':
            for p in (mk.get('prices') or []):
                if p.get('points') is not None:
                    d.setdefault('spreads', {}).setdefault(
                        str(p['points']), {})[p.get('designation')] = p.get('price')

    # v75: BTTS de partido completo, indexado por el id del partido PADRE.
    # `Both Teams To Score?` a secas es el mercado del partido entero; hay una
    # variante `... 1st Half` que se descarta comparando la descripción exacta.
    btts_por_padre: Dict[int, dict] = {}
    for m in partidos:
        desc = ((m.get('special') or {}).get('description') or '').strip()
        if desc != 'Both Teams To Score?':
            continue
        padre = (m.get('parent') or {}).get('id')
        if padre is None:
            continue
        nombres = {p.get('id'): str(p.get('name') or '').lower()
                   for p in (m.get('participants') or [])}
        precios = {}
        for pr in (por_id.get(m.get('id'), {}).get('_precios') or []):
            n = nombres.get(pr.get('participantId'))
            d = american_a_decimal(pr.get('price'))
            if n in ('yes', 'no') and d:
                precios[f'btts_{"yes" if n == "yes" else "no"}'] = d
        if len(precios) == 2:
            btts_por_padre[padre] = precios

    indice: Dict[str, dict] = {}
    for m in partidos:
        if m.get('parentId') is not None:      # mercados derivados
            continue
        if (m.get('special') or {}).get('description'):
            continue                           # v75: special, no es un partido
        parts = m.get('participants') or []
        if len(parts) < 2:
            continue
        loc = next((p for p in parts if p.get('alignment') == 'home'), parts[0])
        vis = next((p for p in parts if p.get('alignment') == 'away'), parts[-1])
        home, away = loc.get('name'), vis.get('name')
        if not home or not away:
            continue
        precios = por_id.get(m.get('id')) or {}
        ml = precios.get('moneyline') or {}
        cuotas = {}
        for lado, dest in (('home', 'home'), ('draw', 'draw'), ('away', 'away')):
            d = american_a_decimal(ml.get(dest))
            if d:
                cuotas[lado] = d
        if not cuotas:
            continue
        # over/under 2.5 (fútbol) o la línea principal del deporte
        tot = precios.get('totales') or {}
        if '2.5' in tot:
            o = american_a_decimal((tot['2.5'] or {}).get('over'))
            u = american_a_decimal((tot['2.5'] or {}).get('under'))
            if o:
                cuotas['over25'] = o
            if u:
                cuotas['under25'] = u
        cuotas.update(btts_por_padre.get(m.get('id')) or {})   # v75: BTTS sharp
        clave = f"{normalizar(home)}|{normalizar(away)}"
        indice[clave] = {
            'home': home, 'away': away,
            'liga': (m.get('league') or {}).get('name'),
            'fecha': m.get('startTime') or m.get('cutoffAt'),
            'casa': 'Pinnacle', 'cuotas': cuotas,
            'totales': {k: {kk: american_a_decimal(vv) for kk, vv in (v or {}).items()}
                        for k, v in tot.items()},
        }
    _escribir_cache(f'pinnacle_{deporte}.json', indice)
    logger.info(f"[pinnacle] {deporte}: {len(indice)} partidos con cuotas")
    return indice


# ---------------------------------------------------------------------------
# 2. Bovada — la tercera casa, y la que tapa los huecos de Pinnacle
#
# Investigadas y descartadas (v71, medido): Smarkets (403), Betfair (403),
# Betano (403), 1xBet (404), Betsson y Marathonbet (devuelven HTML, no JSON),
# Kambi/Unibet (200 pero solo 185 eventos, mayoría esports y amistosos, con el
# catálogo filtrado al mercado británico) y BetExplorer (HTML puramente JS,
# cero filas de cuotas en 738 KB).
#
# Bovada sirve el mismo JSON que consume su web: **904 partidos de fútbol en
# 126 competiciones y 312 de tenis**, con cuota DECIMAL directa. Y sobre todo,
# cubre justo lo que a Pinnacle le faltaba:
#
#     El Salvador  → Pinnacle NO tenía nada     Perú     ✓
#     Costa Rica   ✓                            Chile    ✓
#     Paraguay     ✓                            Ecuador  ✓
#     Rusia        15 eventos (Pinnacle: 6)
#
# Siguen sin cubrir Bolivia y Venezuela: ninguna de las casas probadas les pone
# precio. Es una limitación real del mercado, no del código.
#
# Aporta además la segunda pata para el LINE SHOPPING: con solo Pinnacle y
# DraftKings no había ninguna oportunidad porque DraftKings es retail y nunca
# paga por encima del justo de Pinnacle.
# ---------------------------------------------------------------------------
BOVADA = ('https://www.bovada.lv/services/sports/event/coupon/events/A/'
          'description/{path}?marketFilterId=def&preMatchOnly=true&lang=en')
BOVADA_PATH = {'futbol': 'soccer', 'tenis': 'tennis',
               'mlb': 'baseball/mlb', 'nba': 'basketball/nba'}
UA_WEB = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/126.0 Safari/537.36'),
          'Accept': 'application/json'}


def _indice_bovada(deporte: str) -> Dict[str, dict]:
    """{clave_partido: {...,'cuotas':{home,draw,away}}} desde Bovada."""
    path = BOVADA_PATH.get(deporte)
    if not path:
        return {}
    cacheado = _leer_cache(f'bovada_{deporte}.json')
    if cacheado is not None:
        return cacheado
    j = _get(BOVADA.format(path=path), headers=UA_WEB, timeout=45)
    if not j:
        logger.warning(f"[bovada] {deporte}: sin respuesta")
        return {}
    indice: Dict[str, dict] = {}
    for blk in (j if isinstance(j, list) else []):
        p = blk.get('path') or []
        liga = p[0].get('description') if p else None
        pais = p[1].get('description') if len(p) > 1 else None
        for ev in blk.get('events', []):
            comps = ev.get('competitors') or []
            if len(comps) < 2:
                continue
            loc = next((c for c in comps if c.get('home')), comps[0])
            vis = next((c for c in comps if not c.get('home')), comps[-1])
            home, away = loc.get('name'), vis.get('name')
            if not home or not away:
                continue
            cuotas = {}
            for dg in (ev.get('displayGroups') or []):
                for mk in (dg.get('markets') or []):
                    desc = (mk.get('description') or '').lower()
                    if 'moneyline' not in desc:
                        continue
                    for o in (mk.get('outcomes') or []):
                        nom = (o.get('description') or '').strip()
                        try:
                            dec = float((o.get('price') or {}).get('decimal'))
                        except (TypeError, ValueError):
                            continue
                        if dec <= 1:
                            continue
                        if nom.lower() == 'draw':
                            cuotas['draw'] = round(dec, 4)
                        elif normalizar(nom) == normalizar(home):
                            cuotas['home'] = round(dec, 4)
                        elif normalizar(nom) == normalizar(away):
                            cuotas['away'] = round(dec, 4)
                    break
            if not cuotas.get('home') or not cuotas.get('away'):
                continue
            indice[f'{normalizar(home)}|{normalizar(away)}'] = {
                'home': home, 'away': away,
                'liga': f'{pais} — {liga}' if pais else liga,
                'fecha': ev.get('startTime'), 'casa': 'Bovada',
                'cuotas': cuotas}
    _escribir_cache(f'bovada_{deporte}.json', indice)
    logger.info(f"[bovada] {deporte}: {len(indice)} partidos con cuotas")
    return indice


# ---------------------------------------------------------------------------
# 3/4. ESPN — scoreboard (gratis con los fixtures) y core API por evento
# ---------------------------------------------------------------------------
CORE = ('https://sports.core.api.espn.com/v2/sports/{dep}/leagues/{liga}'
        '/events/{ev}/competitions/{comp}/odds')
UA = {'User-Agent': 'Mozilla/5.0'}


def cuotas_core_espn(deporte_espn: str, liga: str, event_id: str,
                     comp_id: str = None) -> Dict[str, dict]:
    """
    Cuotas por evento del CORE API de ESPN, que a veces las tiene cuando el
    scoreboard devuelve `odds: [null]`. Medido: recupera 12/12 en MLB.
    Devuelve {casa: {'home','draw','away'}}.
    """
    j = _get(CORE.format(dep=deporte_espn, liga=liga, ev=event_id,
                         comp=comp_id or event_id), headers=UA, timeout=25,
             intentos=2)
    salida = {}
    for it in (j or {}).get('items', []):
        casa = (it.get('provider') or {}).get('name') or 'ESPN'
        c = {}
        for lado, k in (('home', 'homeTeamOdds'), ('away', 'awayTeamOdds')):
            d = american_a_decimal((it.get(k) or {}).get('moneyLine'))
            if d:
                c[lado] = d
        dr = it.get('drawOdds')
        if isinstance(dr, dict):
            d = american_a_decimal(dr.get('moneyLine'))
            if d:
                c['draw'] = d
        if c:
            salida[casa] = c
    return salida


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def precargar(deporte: str) -> int:
    """Carga (y cachea) los tablones de ese deporte. Devuelve el total."""
    with _LOCK:
        idx = _indice_pinnacle(deporte)
        _MEM[deporte] = (time.time(), idx)
        bov = _indice_bovada(deporte)
        _MEM_BOV[deporte] = (time.time(), bov)
        pdt = _indice_playdoit(deporte)          # v76
        _MEM_PDT[deporte] = (time.time(), pdt)
    return len(idx) + len(bov) + len(pdt)


def _indice(deporte: str) -> Dict[str, dict]:
    ts, idx = _MEM.get(deporte, (0, None))
    if idx is None or time.time() - ts > TTL:
        with _LOCK:
            idx = _indice_pinnacle(deporte)
            _MEM[deporte] = (time.time(), idx)
    return idx


def _indice_bov(deporte: str) -> Dict[str, dict]:
    ts, idx = _MEM_BOV.get(deporte, (0, None))
    if idx is None or time.time() - ts > TTL:
        with _LOCK:
            idx = _indice_bovada(deporte)
            _MEM_BOV[deporte] = (time.time(), idx)
    return idx


# ---------------------------------------------------------------------------
# 4. PLAYDOIT — la casa del usuario (v76)
#
# Es la cuarta casa y la más importante en la práctica: de nada sirve detectar
# valor en un precio que el usuario no puede tomar. Playdoit es donde apuesta
# de verdad, así que su cuota es la que convierte un EV teórico en un EV
# cobrable.
#
# Corre sobre **Altenar**, cuya API de widget es pública y sin clave. La
# integración se llama `playdoit2` y se descubrió inspeccionando las peticiones
# que hace su propia web (el SDK `sb2wsdk-altenar2.biahosted.com` la lleva en
# cada llamada). Una sola petición trae todo el catálogo.
#
# Medido el 2026-07-28: **953 eventos de fútbol, 948 con 1X2 completo, en 70
# países** — más cobertura que Pinnacle (619) y en el mismo orden que Bovada.
#
# Casas investigadas y DESCARTADAS en la v76, con el motivo medido:
#   · Kambi (Rushbet MX/CO, Unibet, 888sport) → 429 persistente, incluso con
#     cabeceras de navegador y espaciado. Nos limita por IP.
#   · Matchbook, Smarkets, Betfair (los tres exchanges) → 403 de Cloudflare.
#   · Bodog (.eu/.net/.ca) → DNS/522, el dominio ya no responde.
#   · Betcris MX → 404 en su propia ruta de deportes.
#   · 1xBet LineFeed → 404 (la API cambió).
#   · BetOnline → sin API JSON localizable.
#   · Otras integraciones de Altenar (betano, winpot, strendus, codere,
#     betsson, sportium…) → 400: `playdoit2` es la única válida, así que
#     Altenar no da una quinta casa por esta vía.
#   · ESPN core API → expone un único proveedor (DraftKings), no varios.
# ---------------------------------------------------------------------------
ALTENAR = 'https://sb2frontend-altenar2.biahosted.com/api/widget/GetEvents'
ALTENAR_SPORT = {'futbol': 66, 'tenis': 68, 'mlb': 76, 'nba': 67}
ALTENAR_BASE = {'culture': 'es-ES', 'timezoneOffset': '360',
                'integration': 'playdoit2', 'deviceType': '1',
                'numFormat': 'en-GB', 'countryCode': 'MX'}
UA_PDT = {'User-Agent': UA_WEB['User-Agent'], 'Accept': 'application/json',
          'Origin': 'https://www.playdoit.mx',
          'Referer': 'https://www.playdoit.mx/'}
# typeId de la selección dentro del mercado 1X2 de Altenar
_ALT_LADO = {1: 'home', 2: 'draw', 3: 'away'}


def _indice_playdoit(deporte: str) -> Dict[str, dict]:
    """{clave_partido: {...,'cuotas':{home,draw,away}}} desde Playdoit."""
    sid = ALTENAR_SPORT.get(deporte)
    if not sid:
        return {}
    cacheado = _leer_cache(f'playdoit_{deporte}.json')
    if cacheado is not None:
        return cacheado
    params = {**ALTENAR_BASE, 'sportid': sid, 'categoryids': '', 'champids': '',
              'group': 'AllEvents', 'period': 'periodall'}
    j = _get(ALTENAR, params=params, headers=UA_PDT, timeout=60)
    if not isinstance(j, dict) or not j.get('events'):
        logger.warning(f"[playdoit] {deporte}: sin respuesta")
        return {}

    mercados = {m['id']: m for m in (j.get('markets') or [])}
    precios = {o['id']: o for o in (j.get('odds') or [])}
    equipos = {c['id']: c.get('name') for c in (j.get('competitors') or [])}
    cats = {c['id']: c.get('name') for c in (j.get('categories') or [])}
    champs = {c['id']: c.get('name') for c in (j.get('champs') or [])}

    indice: Dict[str, dict] = {}
    for ev in j['events']:
        ids = ev.get('competitorIds') or []
        if len(ids) < 2:
            continue
        # Altenar mete tabulaciones y dobles espacios en algunos nombres
        # («RC Celta\t\t»); sin limpiarlos, `normalizar` genera una clave
        # distinta y el partido no empareja nunca.
        home = ' '.join(str(equipos.get(ids[0]) or '').split())
        away = ' '.join(str(equipos.get(ids[1]) or '').split())
        if not home or not away:
            continue
        cuotas = {}
        for mid in (ev.get('marketIds') or []):
            m = mercados.get(mid)
            # typeId 1 = Resultado Final (1X2) con sus tres selecciones
            if not m or m.get('typeId') != 1 or len(m.get('oddIds') or []) != 3:
                continue
            for oid in m['oddIds']:
                o = precios.get(oid)
                if not o:
                    continue
                lado = _ALT_LADO.get(o.get('typeId'))
                try:
                    p = float(o.get('price'))
                except (TypeError, ValueError):
                    continue
                if lado and p > 1:
                    cuotas[lado] = round(p, 4)
            break
        if not (cuotas.get('home') and cuotas.get('away')):
            continue
        clave = f"{normalizar(home)}|{normalizar(away)}"
        indice[clave] = {
            'home': home, 'away': away,
            'liga': champs.get(ev.get('champId')),
            'pais': cats.get(ev.get('catId')),
            'fecha': ev.get('startDate'),
            'casa': 'Playdoit', 'cuotas': cuotas,
        }
    _escribir_cache(f'playdoit_{deporte}.json', indice)
    logger.info(f"[playdoit] {deporte}: {len(indice)} partidos con cuotas")
    return indice


def _indice_pdt(deporte: str) -> Dict[str, dict]:
    ts, idx = _MEM_PDT.get(deporte, (0, None))
    if idx is None or time.time() - ts > TTL:
        with _LOCK:
            idx = _indice_playdoit(deporte)
            _MEM_PDT[deporte] = (time.time(), idx)
    return idx


def _buscar(indice: Dict[str, dict], home: str, away: str,
            deporte: str = 'futbol') -> Optional[dict]:
    """
    Empareja el partido contra el tablón, tolerando cómo escribe cada fuente.

    Se prueba primero la clave exacta y luego una búsqueda por similitud
    ESPECÍFICA DEL DEPORTE: clubes por palabras significativas (para que
    «Gremio» case con «Gremio FBPA» y «Dinamo Moscow» con «Dynamo Moscow»),
    tenistas por apellido + inicial (para que «Mensik J.» case con «Jakub
    Mensik»). Se exige que AMBOS participantes casen, así que un apellido
    común no basta para colar un partido equivocado.
    """
    h, a = normalizar(home), normalizar(away)
    for clave in (f'{h}|{a}', f'{a}|{h}'):
        if clave in indice:
            r = dict(indice[clave])
            r['invertido'] = clave == f'{a}|{h}' and h != a
            return r

    sim = _sim_tenista if deporte == 'tenis' else _sim_club
    umbral = 0.86 if deporte == 'tenis' else 0.80
    mejor, score = None, 0.0
    for v in indice.values():
        ph, pa = v['home'], v['away']
        s1 = min(sim(home, ph), sim(away, pa))       # el peor de los dos manda
        s2 = min(sim(home, pa), sim(away, ph))
        s, inv = (s1, False) if s1 >= s2 else (s2, True)
        if s > score:
            mejor, score = (v, inv), s
    if mejor and score >= umbral:
        r = dict(mejor[0])
        r['invertido'] = mejor[1]
        r['emparejado_difuso'] = round(score, 3)
        return r
    return None


def cuotas_partido(deporte: str, home: str, away: str,
                   odds_espn: Optional[dict] = None,
                   espn_ref: Optional[tuple] = None) -> Dict:
    """
    Todas las cuotas disponibles de un partido, de todas las fuentes.

    `odds_espn` son las que ya vinieron con el fixture (dict de
    `fixtures_espn._odds_de_evento`), que no cuestan ninguna petición.
    `espn_ref` es `(deporte_espn, liga, event_id, comp_id)` para consultar el
    core API solo si hace falta.

    Devuelve:
      {'casas': {casa: {'home','draw','away'}},
       'mejor': {'home': {'cuota','casa'}, ...},      ← line shopping
       'pinnacle': {...} | None,                       ← ancla sharp
       'n_casas': int, 'fuentes': [...]}
    """
    casas: Dict[str, dict] = {}
    fuentes = []

    if odds_espn and odds_espn.get('odd_home'):
        casas[odds_espn.get('casa') or 'ESPN'] = {
            'home': odds_espn['odd_home'],
            'draw': odds_espn.get('odd_draw'),
            'away': odds_espn['odd_away']}
        fuentes.append('espn_scoreboard')
        for k_src, k_dst in (('odd_over25', 'over25'), ('odd_under25', 'under25')):
            if odds_espn.get(k_src):
                casas.setdefault('_totales', {})[k_dst] = odds_espn[k_src]

    pin = _buscar(_indice(deporte), home, away, deporte)
    if pin and pin.get('cuotas'):
        c = dict(pin['cuotas'])
        if pin.get('invertido'):          # Pinnacle listó al revés: se voltea
            c['home'], c['away'] = c.get('away'), c.get('home')
        casas['Pinnacle'] = {k: v for k, v in c.items()
                             if k in ('home', 'draw', 'away')}
        if c.get('over25'):
            casas.setdefault('_totales', {})['over25'] = c['over25']
        if c.get('under25'):
            casas.setdefault('_totales', {})['under25'] = c['under25']
        # v75: BTTS sharp de Pinnacle (única fuente que lo publica gratis)
        for k in ('btts_yes', 'btts_no'):
            if c.get(k):
                casas.setdefault('_totales', {})[k] = c[k]
        fuentes.append('pinnacle')

    # Bovada: tercera casa. Aporta las ligas que Pinnacle no cubre y la
    # segunda pata del line shopping.
    bov = _buscar(_indice_bov(deporte), home, away, deporte)
    if bov and bov.get('cuotas'):
        c = dict(bov['cuotas'])
        if bov.get('invertido'):
            c['home'], c['away'] = c.get('away'), c.get('home')
        if c.get('home') and c.get('away'):
            casas['Bovada'] = {k: v for k, v in c.items()
                               if k in ('home', 'draw', 'away')}
            fuentes.append('bovada')

    # v76: Playdoit — la casa donde el usuario apuesta de verdad. Va la última
    # a propósito: si algo falla en su API, las tres anteriores ya han dado
    # precio y el barrido no se resiente.
    pdt = _buscar(_indice_pdt(deporte), home, away, deporte)
    if pdt and pdt.get('cuotas'):
        c = dict(pdt['cuotas'])
        if pdt.get('invertido'):
            c['home'], c['away'] = c.get('away'), c.get('home')
        if c.get('home') and c.get('away'):
            casas['Playdoit'] = {k: v for k, v in c.items()
                                 if k in ('home', 'draw', 'away')}
            fuentes.append('playdoit')

    if not casas and espn_ref:
        extra = cuotas_core_espn(*espn_ref)
        if extra:
            casas.update(extra)
            fuentes.append('espn_core')

    totales = casas.pop('_totales', None)
    reales = {k: v for k, v in casas.items() if v.get('home')}
    mejor = {}
    for lado in ('home', 'draw', 'away'):
        cands = [(v[lado], k) for k, v in reales.items()
                 if v.get(lado) and v[lado] > 1]
        if cands:
            cuota, casa = max(cands)
            mejor[lado] = {'cuota': cuota, 'casa': casa}
    return {'casas': reales, 'mejor': mejor, 'totales': totales,
            'pinnacle': reales.get('Pinnacle'), 'n_casas': len(reales),
            'fuentes': fuentes,
            'emparejado_difuso': (pin or {}).get('emparejado_difuso')}


def devig(cuotas: Dict[str, float], metodo: str = 'proporcional') -> Dict[str, float]:
    """
    Probabilidades JUSTAS a partir de las cuotas de una casa, quitándole el
    margen (overround).

    `proporcional` reparte el margen en proporción a la probabilidad implícita;
    `potencia` (Shin/logarítmico simplificado) castiga más al favorito, que es
    lo que mejor reproduce el sesgo favorito-perdedor en mercados de 3 vías.
    """
    imp = {k: 1.0 / v for k, v in cuotas.items() if v and v > 1}
    s = sum(imp.values())
    if not imp or s <= 0:
        return {}
    if metodo == 'potencia' and len(imp) >= 2:
        # busca k tal que sum(p^k) = 1
        lo, hi = 0.5, 1.5
        for _ in range(40):
            mid = (lo + hi) / 2
            tot = sum(p ** mid for p in imp.values())
            if tot > 1:
                lo = mid
            else:
                hi = mid
        k = (lo + hi) / 2
        out = {kk: v ** k for kk, v in imp.items()}
        t = sum(out.values())
        return {kk: v / t for kk, v in out.items()}
    return {k: v / s for k, v in imp.items()}


def valor_vs_sharp(deporte: str, home: str, away: str,
                   odds_espn: Optional[dict] = None,
                   min_edge: float = 0.02) -> Dict:
    """
    v71 — VALOR DE MERCADO: dónde una casa blanda paga más que el precio justo
    de Pinnacle.

    Por qué esto y no el EV contra el modelo
    ----------------------------------------
    La Capa 1 exigía «EV > +3 % contra la cuota real». Con Pinnacle en el
    tablón eso casi nunca se cumple, porque Pinnacle es eficiente: si el modelo
    le gana por 3 puntos suele ser que el modelo se equivoca, no que haya
    valor. Los pocos que pasaban el filtro traían EV de +130 % o +170 %, que es
    la firma clásica de una probabilidad mal calibrada, no de una oportunidad.

    El edge que sí es real y de baja varianza es el **line shopping**: tomar la
    probabilidad justa que implica Pinnacle (quitándole el margen) y buscar la
    casa que paga por encima de ella. Eso no depende de que el modelo acierte
    más que el mercado; depende de que dos casas discrepen, que es un hecho
    observable.

    Devuelve, por selección: mejor cuota, casa, probabilidad justa de Pinnacle,
    EV contra esa probabilidad y el margen que se está capturando.
    """
    res = cuotas_partido(deporte, home, away, odds_espn=odds_espn)
    pin = res.get('pinnacle') or {}
    salida = {'valor': [], 'n_casas': res.get('n_casas', 0),
              'casas': res.get('casas'), 'pinnacle': pin}
    just = devig({k: v for k, v in pin.items() if v}, metodo='potencia')
    if not just:
        return salida
    salida['prob_justa'] = {k: round(v, 4) for k, v in just.items()}
    for lado, p_just in just.items():
        mejor = (res.get('mejor') or {}).get(lado)
        if not mejor or p_just <= 0:
            continue
        cuota = mejor['cuota']
        if mejor['casa'] == 'Pinnacle':
            continue                     # el valor está en superar a Pinnacle
        ev = cuota * p_just - 1.0
        if ev >= min_edge:
            salida['valor'].append({
                'lado': lado, 'cuota': cuota, 'casa': mejor['casa'],
                'prob_justa': round(p_just, 4),
                'cuota_justa': round(1.0 / p_just, 3),
                'ev': round(ev, 4),
                'pinnacle': pin.get(lado)})
    salida['valor'].sort(key=lambda x: -x['ev'])
    return salida


def diagnostico() -> Dict[str, int]:
    """Cuántos partidos hay hoy en cada deporte (para el aviso de la UI)."""
    return {d: len(_indice(d)) for d in DEPORTES}


def diagnostico_casas(deporte: str = 'futbol') -> Dict[str, int]:
    """v76: partidos con cuota POR CASA — para ver de un vistazo si una fuente
    se ha caído en vez de descubrirlo cuando la Capa 1 aparezca medio vacía."""
    return {'Pinnacle': len(_indice(deporte)),
            'Bovada': len(_indice_bov(deporte)),
            'Playdoit': len(_indice_pdt(deporte))}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    import sys
    if len(sys.argv) >= 4:
        print(json.dumps(cuotas_partido(sys.argv[1], sys.argv[2], sys.argv[3]),
                         ensure_ascii=False, indent=1))
    else:
        for d in DEPORTES:
            n = precargar(d)
            print(f'{d:8s} {n:4d} partidos con cuota en Pinnacle')
