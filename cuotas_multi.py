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

# v77: casa de referencia del usuario. Es donde apuesta de verdad, así que su
# precio es el que convierte un EV teórico en un EV cobrable. Ver
# `precio_accionable` para por qué esto NO sustituye al line shopping.
CASA_PRIORITARIA = 'Playdoit'

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


# -----------------------------------------------------------------------
# v79 — MEMOIZACIÓN DEL EMPAREJAMIENTO DE NOMBRES.
#
# El perfilado del barrido (`_v79_perfil.py`) señaló aquí, no a la red ni a
# los modelos:
#
#     cuotas_multi.normalizar      2.845.780 llamadas    77,8 s
#     cuotas_multi._tokens_club    2.844.616 llamadas   128,3 s
#     cuotas_multi._sim_club       1.422.308 llamadas   106,9 s
#     difflib.ratio                1.417.516 llamadas    56,0 s
#
# El motivo es estructural: `_buscar` recorre el tablón entero (unos 976
# partidos de fútbol) y por cada candidato llama cuatro veces a `_sim_club`,
# que normaliza dos nombres cada vez. Con ~580 búsquedas salen millones de
# llamadas... sobre un puñado de nombres DISTINTOS. Se estaba recalculando
# «Palmeiras» miles de veces.
#
# Las tres son funciones puras de sus argumentos, así que se memoizan. No
# cambia ni un resultado: cambia cuántas veces se calcula el mismo.
# -----------------------------------------------------------------------
from functools import lru_cache


def fecha_normalizada(cruda) -> Optional[str]:
    """
    v95 — LA FECHA SE NORMALIZA AQUÍ, en el único sitio donde entra al sistema.

    Cada casa la publica en un formato distinto y hasta ahora cada consumidor
    la parseaba por su cuenta:

        Pinnacle  '2026-08-03T21:30:00Z'   ISO con zona
        Bovada     1785781800000            milisegundos epoch
        Playdoit  '2026-08-03T21:30:00'    ISO sin zona

    `pd.to_datetime` interpreta un entero como NANOsegundos, así que el epoch
    de Bovada se leía como 1970-01-01. El bug apareció en la vista de tenis
    (v94) y se corrigió allí… y volvió a salir en las tarjetas de MLB, porque
    el arreglo estaba en el consumidor y no en el origen. Con tres casas y
    media docena de consumidores, parchear caso por caso es garantizar que
    reaparezca en el siguiente.

    Devuelve ISO 'YYYY-MM-DDTHH:MM:SS' o None. Una fecha implausible (fuera de
    [2000, 2100]) se trata como ausente: es preferible no mostrar fecha a
    mostrar 1970.
    """
    if cruda is None or cruda == '':
        return None
    try:
        if isinstance(cruda, bool):
            return None
        if isinstance(cruda, (int, float)):
            # milisegundos si es del orden de 1e12; segundos si de 1e9
            unidad = 'ms' if abs(cruda) > 1e11 else 's'
            f = pd.to_datetime(int(cruda), unit=unidad, utc=True)
        else:
            f = pd.to_datetime(str(cruda), utc=True, errors='coerce')
        if f is None or pd.isna(f):
            return None
        f = f.tz_convert(None) if f.tzinfo else f
        if not (2000 <= f.year <= 2100):
            return None
        return f.strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:
        return None


@lru_cache(maxsize=100_000)
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


@lru_cache(maxsize=100_000)
def _tokens_club(nombre: str) -> frozenset:
    """
    Palabras significativas de un nombre de club (sin las de relleno).

    Devuelve `frozenset` y no `set` porque el resultado se cachea y se comparte
    entre llamadas: un `set` mutable dejaría que un consumidor descuidado
    corrompiera la entrada de la caché para todos los demás. `frozenset`
    soporta `&`, `|` y `==` igual que antes, así que ningún llamador cambia.
    """
    return frozenset(t for t in normalizar(nombre).split()
                     if t and t not in RUIDO_CLUB and len(t) > 1)


@lru_cache(maxsize=200_000)
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
    if not inter:
        # v79 — atajo DEMOSTRABLEMENTE inocuo, no una heurística.
        #
        # Sin ningún token compartido, jac = 0 y el valor de retorno sería
        # `max(0, 0.5·cad)` = 0,5·cad. Como `cad` nunca pasa de 1, ese valor
        # nunca llega a 0,5 — muy por debajo del umbral 0,80 que exige
        # `_buscar` para aceptar un emparejamiento. Es decir: calcular aquí el
        # SequenceMatcher no puede cambiar ninguna decisión, solo consume
        # tiempo. Y este es el caso mayoritario, porque casi todos los pares
        # del tablón son partidos que no tienen nada que ver.
        return 0.0
    cad = SequenceMatcher(None, ' '.join(sorted(ta)), ' '.join(sorted(tb))).ratio()
    return max(jac, 0.5 * jac + 0.5 * cad)


# Sufijos que no forman parte del apellido y que unas casas ponen y otras no.
_SUFIJOS_TENIS = {'jr', 'sr', 'ii', 'iii', 'iv'}
# Partículas que van pegadas al apellido, no sueltas.
_PARTICULAS_APELLIDO = {'de', 'del', 'della', 'di', 'da', 'dos', 'das', 'van',
                        'von', 'der', 'den', 'la', 'le', 'el', 'al', 'bin',
                        'mc', 'mac', "o"}


@lru_cache(maxsize=100_000)
def _clave_tenista(nombre: str) -> tuple:
    """
    (apellido, inicial) de un tenista, escriba quien lo escriba.

    Las fuentes del proyecto usan «Mensik J.» y Pinnacle «Jakub Mensik»: sin
    esto no empareja ni uno. Se detecta el formato por la posición del punto.

    v77 — TRES FALLOS CORREGIDOS, todos ellos causa de partidos duplicados en
    la Capa 2 (cada variante del nombre entraba como un partido distinto):

      1. **Texto entre paréntesis.** «Andrés Andrade (PAN)» daba `('pan','a')`:
         el código de país se colaba como apellido. Se elimina antes de nada.
      2. **Sufijos de linaje.** «Martin Damm Jr» daba `('jr','m')`. Una casa
         escribe el Jr y otra no, así que se descartan.
      3. **Apellidos compuestos.** «Félix Auger-Aliassime» daba
         `('aliassime','f')` y «Auger-Aliassime F.» daba `('auger','f')` —
         el mismo jugador con dos claves. `normalizar` convierte el guion en
         espacio, y como cada rama del formato elige una parte distinta, no
         coincidían nunca. Ahora el guion se une ANTES de normalizar, de modo
         que el apellido compuesto es un solo token en los dos formatos.

    Las tildes ya las quitaba `normalizar`; el problema nunca fue ese.
    """
    import re
    crudo = str(nombre or '').strip()
    # 1) fuera lo que va entre paréntesis (país, categoría, etc.)
    crudo = re.sub(r'\([^)]*\)', ' ', crudo)
    # 3) el apellido compuesto se vuelve un token: «Auger-Aliassime» ->
    #    «augeraliassime», igual se escriba en un formato o en el otro
    crudo_unido = re.sub(r'(\w)[-‐‑’\']\s*(\w)', r'\1\2', crudo)

    s = normalizar(crudo_unido)
    partes = [p for p in s.split() if p and p not in _SUFIJOS_TENIS]   # 2)
    # 4) partículas de apellido: «del Potro» y «de Minaur» se parten distinto
    #    según el formato (la rama con punto se quedaba con «del» y la otra con
    #    «potro»), así que se pegan al token siguiente: «delpotro». Se unen en
    #    vez de descartarse para no fundir jugadores realmente distintos.
    unidas, i = [], 0
    while i < len(partes):
        if partes[i] in _PARTICULAS_APELLIDO and i + 1 < len(partes):
            # codicioso: «van de Zandschulp» son DOS partículas seguidas, y
            # unir solo la primera dejaba «vande» frente a «zandschulp»
            j = i
            while j < len(partes) and partes[j] in _PARTICULAS_APELLIDO:
                j += 1
            if j < len(partes):
                unidas.append(''.join(partes[i:j + 1]))
                i = j + 1
                continue
        unidas.append(partes[i])
        i += 1
    partes = unidas
    if not partes:
        return ('', '')
    if '.' in crudo:
        # formato «Apellido X.» (puede llevar apellido compuesto)
        sin_inicial = [p for p in partes if len(p) > 1]
        inicial = next((p for p in partes if len(p) == 1), '')
        if sin_inicial:
            return (sin_inicial[-1] if len(sin_inicial) == 1 else sin_inicial[0],
                    inicial)
    # formato «Nombre Apellido»
    return (partes[-1], partes[0][:1])


@lru_cache(maxsize=200_000)
def _sim_tenista(a: str, b: str) -> float:
    # v79 — memoizada por el mismo motivo que `_sim_club`: `_buscar` la llama
    # cuatro veces por candidato del tablón (unos 421 partidos de tenis) y
    # siempre sobre los mismos nombres.
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
            'fecha': fecha_normalizada(m.get('startTime')
                                       or m.get('cutoffAt')),
            'casa': 'Pinnacle', 'cuotas': cuotas,
            'totales': {k: {kk: american_a_decimal(vv) for kk, vv in (v or {}).items()}
                        for k, v in tot.items()},
            # v106 — LOS HÁNDICAPS TAMBIÉN SALEN DEL ÍNDICE.
            #
            # `por_id` ya los recogía (`spreads`, con su línea y el precio por
            # lado) desde la v75, pero se quedaban dentro de la función: aquí
            # sólo salían el moneyline y los totales. Hacen falta fuera para la
            # run line del béisbol (±1.5, el mercado al que apunta la regla de
            # «mejor pitcher») y para el hándicap asiático de fútbol, que hasta
            # ahora dependía sólo de la línea que publicase ESPN.
            'spreads': {k: {kk: american_a_decimal(vv)
                            for kk, vv in (v or {}).items()}
                        for k, v in (por_id.get(m.get('id'), {})
                                     .get('spreads') or {}).items()},
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
                'fecha': fecha_normalizada(ev.get('startTime')),
                'casa': 'Bovada',
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


def _ganador_altenar(ev: dict, ids: list, mercados: dict,
                     precios: dict) -> Dict[str, float]:
    """
    Cuotas del mercado GANADOR de un evento de Altenar, sea el deporte que sea.

    v77 — por qué no se busca por `typeId`. La v76 lo fijaba a 1, que es el
    Resultado Final del FÚTBOL, y por eso Playdoit devolvía 0 partidos en MLB,
    NBA y tenis sin dar el menor error: cada deporte usa el suyo (1 fútbol,
    186 tenis, 223 NBA, 251 MLB) y seguirá inventando más. Codificar cuatro
    números habría arreglado hoy y roto en cuanto añadan un deporte.
    Peor aún: fallaba EN SILENCIO — no había excepción, simplemente no
    encontraba mercado y el deporte desaparecía del barrido.
    Se identifica por ESTRUCTURA, que es lo que no cambia:
      · cada selección apunta a un competidor del evento (o es el empate);
      · y su nombre es EXACTAMENTE el del competidor. Esto último es lo que
        distingue al ganador del hándicap, que comparte competidores pero
        escribe «Orioles (+1.5)».
    """
    equipos_ev = {i for i in ids if i is not None}
    for mid in (ev.get('marketIds') or []):
        m = mercados.get(mid)
        if not m:
            continue
        sel = [precios.get(o) for o in (m.get('oddIds') or [])]
        sel = [s for s in sel if s]
        if len(sel) not in (2, 3):
            continue
        cuotas: Dict[str, float] = {}
        valido = True
        for s in sel:
            try:
                p = float(s.get('price'))
            except (TypeError, ValueError):
                valido = False
                break
            if p <= 1:
                valido = False
                break
            cid = s.get('competitorId')
            nombre = ' '.join(str(s.get('name') or '').split())
            if cid in equipos_ev:
                # el nombre tiene que ser el del competidor tal cual: si lleva
                # una línea entre paréntesis es hándicap, no ganador
                esperado = ' '.join(str(_NOMBRE_COMP.get(cid) or '').split())
                if esperado and nombre != esperado:
                    valido = False
                    break
                lado = 'home' if cid == ids[0] else 'away'
                cuotas[lado] = round(p, 4)
            elif cid is None and len(sel) == 3:
                cuotas['draw'] = round(p, 4)      # el empate no tiene competidor
            else:
                valido = False
                break
        if valido and cuotas.get('home') and cuotas.get('away'):
            if len(sel) == 3 and not cuotas.get('draw'):
                continue
            return cuotas
    return {}


# nombres de competidor del volcado en curso (lo rellena `_indice_playdoit`);
# `_ganador_altenar` los necesita para distinguir ganador de hándicap.
_NOMBRE_COMP: Dict[int, str] = {}


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
    _NOMBRE_COMP.clear()
    _NOMBRE_COMP.update(equipos)
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
        a0 = ' '.join(str(equipos.get(ids[0]) or '').split())
        a1 = ' '.join(str(equipos.get(ids[1]) or '').split())
        if not a0 or not a1:
            continue
        # v77 — ORIENTACIÓN LOCAL/VISITANTE. El orden de `competitorIds` NO es
        # constante: en fútbol el evento se llama «A vs. B» y A es el local,
        # pero en los deportes de formato estadounidense (MLB, NBA) se llama
        # «A @ B» y ahí A es el VISITANTE. Fiarse de la posición invertía todos
        # los partidos de MLB — verificado contra Pinnacle: para
        # «BAL Orioles @ DET Tigers», Pinnacle da home=Detroit 1,7194 y
        # away=Baltimore 2,28, mientras nosotros etiquetábamos Baltimore como
        # local. Los precios eran correctos; el bando, no. Habría generado
        # picks del equipo equivocado con un EV inventado enorme (+49 %).
        if ' @ ' in str(ev.get('name') or ''):
            home, away = a1, a0
        else:
            home, away = a0, a1
        if home != a0:
            ids = [ids[1], ids[0]]        # que `_ganador_altenar` case bandos
        if not home or not away:
            continue
        cuotas = _ganador_altenar(ev, ids, mercados, precios)
        if not (cuotas.get('home') and cuotas.get('away')):
            continue
        clave = f"{normalizar(home)}|{normalizar(away)}"
        indice[clave] = {
            'home': home, 'away': away,
            'liga': champs.get(ev.get('champId')),
            'pais': cats.get(ev.get('catId')),
            'fecha': fecha_normalizada(ev.get('startDate')),
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


def _spread_principal(spreads: Optional[Dict],
                      invertido: bool = False) -> Optional[Dict]:
    """
    v106 — el hándicap principal de Pinnacle, normalizado a la LÍNEA DEL LOCAL.

    Pinnacle indexa cada precio por SU propia línea, así que un partido llega
    como {'-0.5': {'home': 1.95}, '0.5': {'away': 1.90}}: la clave ya es la
    línea de ese lado, no la del local. Aquí se pasa al convenio del proyecto
    —una sola línea, la del local, negativa si es favorito— que es el que usan
    `fixtures_espn.odds_evento`, `league_engine` y `odds_store`.

    `invertido` indica que Pinnacle listó los equipos al revés que el
    proyecto; en ese caso se intercambian los lados Y se cambia el signo de la
    línea, porque «local −1» visto del otro lado es «local +1».

    Se elige la línea principal como la de menor valor absoluto, que es la que
    la casa cotiza más cerca del 50/50 y la que publica por defecto.
    """
    if not spreads:
        return None
    por_linea: Dict[float, dict] = {}
    for k, precios in spreads.items():
        try:
            linea = float(k)
        except (TypeError, ValueError):
            continue
        for lado, cuota in (precios or {}).items():
            if lado not in ('home', 'away') or not cuota:
                continue
            # la línea del LOCAL: la propia si es el lado local, la opuesta si
            # es la del visitante
            linea_local = linea if lado == 'home' else -linea
            por_linea.setdefault(linea_local, {})[lado] = float(cuota)
    if not por_linea:
        return None
    # se prefiere la línea con los DOS precios; entre ellas, la más central
    def _orden(item):
        L, precios = item
        return (0 if len(precios) == 2 else 1, abs(L))
    linea, precios = sorted(por_linea.items(), key=_orden)[0]
    salida = {'linea': linea, 'home': precios.get('home'),
              'away': precios.get('away')}
    if invertido:
        salida = {'linea': -linea, 'home': precios.get('away'),
                  'away': precios.get('home')}
    return salida if (salida['home'] or salida['away']) else None


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
    # v90 — LOS TOTALES SE GUARDAN TAMBIÉN POR CASA.
    #
    # `_totales` es un dict PLANO: el over25 de ESPN y el de Pinnacle se
    # escriben en la misma clave y el segundo pisa al primero. O sea que la
    # casa que puso cada precio de Goles/BTTS se perdía por construcción, y con
    # ella la posibilidad de hacer line shopping en esos mercados: comparar dos
    # casas exige conservar las dos.
    #
    # Se vio al intentar validar el canal de valor sobre Goles: en
    # `historical_odds` hay 35.606 filas con over25 y **ni una** con dos casas
    # para el mismo partido, porque `daily_snapshots` sólo podía etiquetarlas
    # como Pinnacle. No es que faltara histórico — es que el dato nunca se
    # llegó a distinguir.
    #
    # `totales` se mantiene EXACTAMENTE igual (mismo dict fusionado, misma
    # precedencia), así que nada de lo que hay hoy cambia de comportamiento;
    # `totales_por_casa` es información nueva que antes se tiraba.
    tot_casa: Dict[str, dict] = {}

    if odds_espn and odds_espn.get('odd_home'):
        _casa_espn = odds_espn.get('casa') or 'ESPN'
        casas[_casa_espn] = {
            'home': odds_espn['odd_home'],
            'draw': odds_espn.get('odd_draw'),
            'away': odds_espn['odd_away']}
        fuentes.append('espn_scoreboard')
        for k_src, k_dst in (('odd_over25', 'over25'), ('odd_under25', 'under25')):
            if odds_espn.get(k_src):
                casas.setdefault('_totales', {})[k_dst] = odds_espn[k_src]
                tot_casa.setdefault(_casa_espn, {})[k_dst] = odds_espn[k_src]

    # v106 — hándicaps por casa, para que se puedan FOTOGRAFIAR.
    #
    # `daily_snapshots` guardaba 1X2, totales y BTTS pero nunca el hándicap
    # asiático, aunque `odds_store` tiene sus tres columnas desde la v75. El
    # efecto medido: sólo 20 de las 57 competiciones activas tienen backtest de
    # hándicap (`roi_bets_ah_*.json`), y son exactamente las 20 cuyo CSV de
    # football-data trae columnas asiáticas. Liga MX, las 21 ligas que sólo
    # cubre ESPN y todas las de formato `new` no podían medirlo NUNCA — no por
    # falta de tiempo, sino porque el dato no se guardaba.
    #
    # Con Pinnacle publicando `spreads` en su índice (misma versión) y ESPN el
    # `ah_linea` del fixture, la foto diaria ya puede acumularlo.
    ah_casa: Dict[str, dict] = {}
    if odds_espn and odds_espn.get('ah_linea') is not None:
        _c_espn = odds_espn.get('casa') or 'ESPN'
        ah_casa[_c_espn] = {'linea': odds_espn.get('ah_linea'),
                            'home': odds_espn.get('odd_ah_home'),
                            'away': odds_espn.get('odd_ah_away')}

    pin = _buscar(_indice(deporte), home, away, deporte)
    if pin and pin.get('cuotas'):
        c = dict(pin['cuotas'])
        if pin.get('invertido'):          # Pinnacle listó al revés: se voltea
            c['home'], c['away'] = c.get('away'), c.get('home')
        _ah = _spread_principal(pin.get('spreads'), pin.get('invertido'))
        if _ah:
            ah_casa['Pinnacle'] = _ah
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
        for k in ('over25', 'under25', 'btts_yes', 'btts_no'):
            if c.get(k):
                tot_casa.setdefault('Pinnacle', {})[k] = c[k]
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

    # -----------------------------------------------------------------------
    # v77 — CUOTA ACCIONABLE vs MEJOR CUOTA
    #
    # El usuario apuesta en Playdoit, así que un precio de Bovada que no puede
    # tomar no es una oportunidad: es un número bonito. Pero fijar la política
    # en "usa siempre Playdoit" tampoco sale gratis. Medido sobre 894
    # selecciones con dos o más casas: **Playdoit da el mejor precio el 41,1 %
    # de las veces** y, cuando no lo da, deja un 3,34 % de cuota de media
    # (mediana 2,55 %, peor caso 23,9 %). Ese 3 % en un pick de cuota 2,00 y
    # probabilidad 0,55 baja el EV de +13,3 % a +10,0 % — un tercio del margen.
    #
    # Así que no se elige: se devuelven las dos.
    #   · `preferida`  — el precio de la casa del usuario. Es con el que se
    #                    calcula el EV accionable, porque es el que puede
    #                    cobrar de verdad.
    #   · `mejor`      — el mejor del mercado, con su casa, y el diferencial.
    #                    Es información para que decida si le compensa abrir o
    #                    usar otra cuenta, no un EV que se apunte solo.
    # -----------------------------------------------------------------------
    preferida = {}
    p_casa = reales.get(CASA_PRIORITARIA)
    if p_casa:
        for lado in ('home', 'draw', 'away'):
            v = p_casa.get(lado)
            if v and v > 1:
                mj = (mejor.get(lado) or {}).get('cuota')
                preferida[lado] = {
                    'cuota': v, 'casa': CASA_PRIORITARIA,
                    'mejor_alternativa': (mejor.get(lado) or {}).get('casa'),
                    'ventaja_alternativa': (round((mj - v) / v, 4)
                                            if mj and mj > v else 0.0)}
    return {'casas': reales, 'mejor': mejor, 'preferida': preferida,
            'casa_prioritaria': CASA_PRIORITARIA,
            'totales': totales,
            # v90: los mismos totales SIN fusionar, con la casa que puso cada
            # precio. Nadie lo consume todavía para decidir picks; lo escribe
            # `daily_snapshots` para que dentro de unas semanas exista el
            # histórico de dos casas que hoy no existe (ver el comentario de
            # `tot_casa` arriba).
            'totales_por_casa': tot_casa or None,
            # v106: hándicap asiático por casa, con la línea REFERIDA AL LOCAL
            # (negativa = local favorito), que es el convenio del resto del
            # proyecto (`fixtures_espn.odds_evento`, `league_engine`).
            'handicap_por_casa': ah_casa or None,
            'pinnacle': reales.get('Pinnacle'), 'n_casas': len(reales),
            'fuentes': fuentes,
            'emparejado_difuso': (pin or {}).get('emparejado_difuso')}


def precio_accionable(c: Dict, lado: str) -> Optional[dict]:
    """
    Precio con el que se debe calcular el EV de una selección.

    Prioriza la casa del usuario (`CASA_PRIORITARIA`) y solo cae al mejor del
    mercado si esa casa no cotiza ese partido. Devuelve el mismo dict que
    `mejor[lado]`, con `mejor_alternativa` y `ventaja_alternativa` cuando otra
    casa paga más, para que la interfaz lo pueda avisar.
    """
    if not c:
        return None
    p = (c.get('preferida') or {}).get(lado)
    if p:
        return p
    m = (c.get('mejor') or {}).get(lado)
    return dict(m, mejor_alternativa=None, ventaja_alternativa=0.0) if m else None


def devig(cuotas: Dict[str, float], metodo: str = 'potencia') -> Dict[str, float]:
    """
    Probabilidades JUSTAS a partir de las cuotas de una casa, quitándole el
    margen (overround).

    `proporcional` reparte el margen en proporción a la probabilidad implícita;
    `potencia` (Shin/logarítmico simplificado) castiga más al favorito, que es
    lo que mejor reproduce el sesgo favorito-perdedor en mercados de 3 vías.

    v80 — EL DEFECTO PASA DE `proporcional` A `potencia`, y esta vez medido.
    ------------------------------------------------------------------------
    De este paso cuelga todo lo demás: el ancla del encogimiento, el
    `valor_vs_sharp` que hoy llena la Capa 1 y el `m_*` con el que se valida.
    Si el devigado sesga, sesga todo a la vez. La preferencia por `potencia`
    estaba escrita como argumento razonable pero **nunca se había comprobado**.

    Comparados cuatro métodos por log-loss contra el resultado real
    (`_v80_devig.py`), incluido el de Shin, que es el estándar académico:

        FÚTBOL, cierre genérico (n=36.006)     log-loss      ECE
          potencia (el que se usa)              0,99926    0,00414
          aditivo                               0,99930    0,00464
          Shin                                  0,99943    0,00523
          proporcional                          1,00011    0,00700

        FÚTBOL, Pinnacle (n=26.666)            0,99910 / 0,99912 / 0,99917 / 0,99946
        TENIS y MLB, 2 vías (n=53.685)         0,59430 / 0,59434 / 0,59434 / 0,59500

    `potencia` gana en los tres, y `proporcional` pierde en los tres — y era
    justo el valor por defecto. Hoy ningún llamador lo usa (todos pasan
    `metodo='potencia'` explícitamente), así que esto no cambia ningún número:
    quita una trampa para el siguiente que llame a `devig` sin pensarlo.
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


# v86 — Techo del precio accionable frente al sharp. Ver el comentario dentro de
# `valor_vs_sharp`: es un límite de plausibilidad económica, no un parámetro
# ajustado. Doblar el precio de Pinnacle implicaría un EV de más del 100 %.
RATIO_MAX_SOBRE_SHARP = 2.0


def sharp_gap_2via(prob_modelo: float, pin_a: Optional[float],
                   pin_b: Optional[float]) -> Optional[float]:
    """
    Gap del modelo sobre la devig de Pinnacle en un mercado a 2 vías (sin
    empate: MLB, tenis, NBA). Positivo = el modelo supera al sharp.

    v88 — venía de `odds_api`, que se retira. Es una función PURA (no toca la
    red ni la clave de API) y su sitio natural es aquí, junto a `devig`, que es
    lo mismo generalizado a tres vías.
    """
    if not pin_a or not pin_b or pin_a <= 1 or pin_b <= 1:
        return None
    ia, ib = 1.0 / pin_a, 1.0 / pin_b
    devig_a = ia / (ia + ib)             # prob implícita sin margen
    return prob_modelo - devig_a


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
    salida['descartes_imposibles'] = []
    for lado, p_just in just.items():
        # v77: se valora el precio ACCIONABLE (la casa del usuario) y no el
        # mejor del mercado. Un pick de line shopping que solo existe en una
        # casa donde no se puede apostar no es una oportunidad; y como el EV
        # aquí sale de superar el precio justo de Pinnacle, usar una cuota que
        # el usuario no puede tomar inflaría el EV de toda la Capa 1.
        precio = precio_accionable(res, lado)
        if not precio or p_just <= 0:
            continue
        cuota = precio['cuota']
        if precio['casa'] == 'Pinnacle':
            continue                     # el valor está en superar a Pinnacle
        # v86 — GUARDIA DE PRECIO IMPOSIBLE.
        #
        # Hasta v85 no había ninguna comprobación de que la cuota accionable
        # fuera un precio POSIBLE: se calculaba el EV y, si superaba el umbral,
        # el pick entraba en la Capa 1. Un feed corrupto (una coma decimal
        # desplazada, un valor rancio) produce un EV gigantesco y se cuela
        # directo arriba del todo, porque la lista va ordenada por EV.
        #
        # No es hipotético. En el histórico de tennis-data.co.uk hay una cuota
        # a 100x el precio de Pinnacle, y esa ÚNICA apuesta aporta 1,21 puntos
        # del ROI de +4,57 % de la WTA: el 26 % del titular sale de un dato que
        # nadie pudo cobrar jamás.
        #
        # El corte es de PRINCIPIO, no de barrido: doblar el precio del sharp
        # implicaría un EV de más del 100 %, y eso no existe en un mercado de
        # dos vías. Se midieron 1,5 · 2,0 · 2,5 · 3,0 y dan prácticamente lo
        # mismo (bloquean entre el 0,02 % y el 0,23 % de los picks), así que el
        # valor concreto no está ajustado a los datos.
        #
        # Lo que NO se filtra, aunque se probó: el sobre-redondeo (overround) de
        # las mejores cuotas por debajo de 0,95. Bloqueaba entre el 3,6 % y el
        # 4,8 % de los picks y costaba hasta 1,54 puntos de ROI, porque un
        # overround bajo es precisamente lo que el line shopping busca — dos
        # casas discrepando — y no una señal de dato corrupto.
        pin_lado = pin.get(lado)
        if pin_lado and pin_lado > 1 and cuota > RATIO_MAX_SOBRE_SHARP * pin_lado:
            salida['descartes_imposibles'].append({
                'lado': lado, 'cuota': cuota, 'casa': precio['casa'],
                'pinnacle': pin_lado,
                'ratio': round(cuota / pin_lado, 2),
                'motivo': f'precio {cuota / pin_lado:.1f}x el de Pinnacle'})
            continue
        ev = cuota * p_just - 1.0
        if ev >= min_edge:
            salida['valor'].append({
                'lado': lado, 'cuota': cuota, 'casa': precio['casa'],
                'prob_justa': round(p_just, 4),
                'cuota_justa': round(1.0 / p_just, 3),
                'ev': round(ev, 4),
                'pinnacle': pin.get(lado),
                # para que la UI pueda decir «en X pagan un Y % más»
                'mejor_alternativa': precio.get('mejor_alternativa'),
                'ventaja_alternativa': precio.get('ventaja_alternativa', 0.0)})
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
