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
_MEM: Dict[str, tuple] = {}    # deporte -> (timestamp, indice)


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

    partidos = _get(f'{PIN_BASE}/sports/{sid}/matchups',
                    {'withSpecials': 'false', 'brandId': 0})
    mercados = _get(f'{PIN_BASE}/sports/{sid}/markets/straight',
                    {'primaryOnly': 'false', 'withSpecials': 'false'})
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

    indice: Dict[str, dict] = {}
    for m in partidos:
        if m.get('parentId') is not None:      # mercados derivados
            continue
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
# 2/3. ESPN — scoreboard (gratis con los fixtures) y core API por evento
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
    """Carga (y cachea) el tablón de Pinnacle de ese deporte."""
    with _LOCK:
        idx = _indice_pinnacle(deporte)
        _MEM[deporte] = (time.time(), idx)
    return len(idx)


def _indice(deporte: str) -> Dict[str, dict]:
    ts, idx = _MEM.get(deporte, (0, None))
    if idx is None or time.time() - ts > TTL:
        with _LOCK:
            idx = _indice_pinnacle(deporte)
            _MEM[deporte] = (time.time(), idx)
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
        fuentes.append('pinnacle')

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


def diagnostico() -> Dict[str, int]:
    """Cuántos partidos hay hoy en cada deporte (para el aviso de la UI)."""
    return {d: len(_indice(d)) for d in DEPORTES}


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
