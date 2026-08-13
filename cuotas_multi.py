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
import re
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

# v130 — tope del caché de tableros de Playdoit. Un tablero de fútbol ocupa
# ~395 KB desde que se bajan los mercados de jugador, así que 60 MB son unos
# 150 partidos vivos a la vez: mucho más de lo que nadie mira en seis horas, y
# lejos del disco del contenedor. Ver `_purgar_detalles_playdoit`.
MAX_CACHE_PLAYDOIT = 60 * 1024 * 1024
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
    # v114 — variantes MEDIDAS sobre los fixtures que se quedaban sin precio.
    #
    # De 473 fixtures de las 50 competiciones activas, 169 no encontraban
    # cuota. Casi todos porque ninguna casa los cotiza todavía (partidos a más
    # de tres días, ligas menores), que es correcto — pero nueve SÍ estaban en
    # el tablón y se perdían por cómo escribe el nombre cada fuente. Cada
    # entrada de aquí abajo corresponde a uno de esos nueve casos reales, no a
    # una suposición:
    #
    #   Union St.-Gilloise   ↔ Union Saint-Gilloise      (champions)
    #   Red Bull New York    ↔ New York Red Bulls        (mls)
    #   Asteras Tripoli      ↔ Asteras Tripolis          (gre_super_league)
    #   Queen's Park         ↔ FC Queens Park            (sco_championship)
    #   Hamburg SV           ↔ Hamburger SV              (bundesliga)
    #   CSKA Moscow          ↔ CSKA Moscú                (rus_premier)
    #   Lokomotiv Moscow     ↔ FK Lokomotiv Moscú        (rus_premier)
    'st': 'saint', 'bulls': 'bull', 'tripolis': 'tripoli',
    'queens': 'queen', 'hamburger': 'hamburg',
    'moscu': 'moscow', 'moskva': 'moscow',
    'munchen': 'munich', 'muenchen': 'munich',
}

# Palabras que no distinguen a un club y solo meten ruido en la comparación
RUIDO_CLUB = {
    'fc', 'cf', 'sc', 'ac', 'afc', 'cd', 'ud', 'sd', 'ec', 'fk', 'sk', 'nk',
    'club', 'clube', 'deportivo', 'atletico', 'atlético', 'athletic', 'real',
    'sporting', 'united', 'city', 'de', 'do', 'da', 'del', 'the', 'if', 'ff',
    'bk', 'ik', 'cr', 'ca', 'aa', 'se', 'esporte', 'futebol', 'futbol', 'rj',
    'sp', 'mg', 'rs', 'pr', 'sc2', 'u20', 'ii', 'b',
    # v114: siglas de sociedad que unas fuentes ponen y otras no. «Volos NFC»
    # y «Volos NPS» son el mismo club griego escrito con dos abreviaturas.
    'nfc', 'nps', 'npc',
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


# v132 — LAS ABREVIATURAS DE MLB, QUE ROMPÍAN EL CRUCE ENTERO.
#
# Playdoit publica «DET Tigers» y Pinnacle «Detroit Tigers». Normalizados dan
# `det tigers` y `detroit tigers`, con similitud 0,583: por debajo del listón
# del emparejador, así que NO casaban. Efecto medido: la escalera de ponches de
# Playdoit no se encontraba nunca partiendo del prop de Pinnacle, y con ella se
# caía la Tarea 3 completa aunque todo lo demás estuviera bien.
#
# No se arregla bajando el listón —eso emparejaría cosas que no son— sino
# expandiendo la abreviatura, que es un conjunto CERRADO de 30 y estable. Sale
# de `/api/v1/teams` de MLB StatsAPI, la misma fuente que usa el resto del
# módulo de béisbol.
ABREV_MLB = {
    'ATH': 'Athletics', 'ATL': 'Atlanta Braves', 'AZ': 'Arizona Diamondbacks',
    'BAL': 'Baltimore Orioles', 'BOS': 'Boston Red Sox', 'CHC': 'Chicago Cubs',
    'CIN': 'Cincinnati Reds', 'CLE': 'Cleveland Guardians',
    'COL': 'Colorado Rockies', 'CWS': 'Chicago White Sox',
    'DET': 'Detroit Tigers', 'HOU': 'Houston Astros', 'KC': 'Kansas City Royals',
    'LAA': 'Los Angeles Angels', 'LAD': 'Los Angeles Dodgers',
    'MIA': 'Miami Marlins', 'MIL': 'Milwaukee Brewers', 'MIN': 'Minnesota Twins',
    'NYM': 'New York Mets', 'NYY': 'New York Yankees',
    'PHI': 'Philadelphia Phillies', 'PIT': 'Pittsburgh Pirates',
    'SD': 'San Diego Padres', 'SEA': 'Seattle Mariners',
    'SF': 'San Francisco Giants', 'STL': 'St. Louis Cardinals',
    'TB': 'Tampa Bay Rays', 'TEX': 'Texas Rangers', 'TOR': 'Toronto Blue Jays',
    'WSH': 'Washington Nationals',
}
# `{'det': 'detroit tigers', …}` para expandir sobre el texto ya normalizado.
_ABREV_MLB_NORM = {k.lower(): v.lower().replace('.', '') for k, v in ABREV_MLB.items()}


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
    # La abreviatura sólo se expande cuando ENCABEZA el nombre y hay algo
    # detrás («det tigers»), que es como la escriben las casas. Suelta no se
    # toca: «sd» puede ser muchas cosas fuera del béisbol, y este normalizador
    # lo usan también el fútbol y el tenis.
    if len(partes) >= 2 and partes[0] in _ABREV_MLB_NORM:
        resto = ' '.join(partes[1:])
        completo = _ABREV_MLB_NORM[partes[0]]
        if resto and resto in completo:
            return completo
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
        # v114 — CONTENCIÓN NO ES IGUALDAD, Y CONFUNDIRLAS COSTÓ UN PICK FALSO.
        #
        # Esto devolvía 1.0 en los dos casos, y por eso «Independiente» casaba
        # perfecto con «Independiente Rivadavia»: dos clubes DISTINTOS de la
        # misma liga argentina. Medido el 2026-08-09 sobre el tablón real: el
        # sistema emparejó «Independiente vs Belgrano» (Primera División
        # FEMENINA, 10-ago) con «Belgrano vs Independiente Rivadavia» (Liga
        # Profesional masculina, 15-ago) y encima con los bandos al revés, lo
        # que fabricaba un arbitraje del 0,7737 y un EV enorme sobre un partido
        # que no existe. No daba excepción: daba una apuesta.
        #
        # La contención SIGUE valiendo —«Gremio» y «Gremio FBPA» son el mismo
        # club, que es para lo que se escribió— pero ahora puntúa por debajo de
        # la igualdad exacta. 0,93 está muy por encima del umbral 0,80 que
        # exige `_buscar`, así que ningún emparejamiento que hoy funciona deja
        # de funcionar; lo único que cambia es que si en el mismo tablón están
        # el club exacto Y uno que lo contiene, gana el exacto.
        return 1.0 if ta == tb else 0.93
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


# ---------------------------------------------------------------------------
# v114 — CATEGORÍA DEL PARTIDO (femenino, juvenil, reservas).
#
# `normalizar` convierte «(W)» y «(F)» en espacios y luego `_tokens_club` tira
# las palabras de una letra, así que el marcador de categoría DESAPARECE antes
# de comparar: «CA Independiente (W)» y «Independiente» quedan idénticos. Con
# eso, un partido femenino y uno masculino del mismo club son indistinguibles
# para el emparejador — y sus cuotas no tienen nada que ver.
#
# Se extrae del texto ORIGINAL, antes de normalizar. La marca puede venir en
# el nombre del equipo («Belgrano de Córdoba (W)») o en el de la competición
# («Argentina - Primera Division Women»), así que se acepta cualquiera de los
# dos como fuente.
#
# Sólo se reconocen marcas INEQUÍVOCAS. Las letras sueltas «w» y «f» se
# aceptan únicamente entre paréntesis, que es como las escriben las casas; una
# «B» o un «II» de equipo filial no se tratan aquí porque «B» aparece en
# nombres legítimos y el falso positivo sería peor que el problema.
# ---------------------------------------------------------------------------
_MARCAS_CATEGORIA = (
    # el género se escribe con la terminación del idioma («femenino» pero
    # «Eurocopa femenina»), así que la marca acepta las dos y el plural
    ('fem', re.compile(
        r'\((?:w|f)\)|\b(?:women|womens|woman|femenin[ao]s?|femenil(?:es)?|'
        r'feminin[ao]s?|femminile|frauen|dames|ladies|kvinner|damen)\b',
        re.I)),
    # v114 — FILIAL, JUVENIL Y RESERVAS SON LA MISMA MARCA A PROPÓSITO.
    #
    # «Benfica II», «Benfica B» y «Benfica Sub-21» son el MISMO equipo escrito
    # de tres formas: el filial. Si cada variante fuese una marca distinta, el
    # emparejador dejaría de casarlas entre sí y perdería cobertura real —
    # medido: el arreglo costaba «Benfica II vs Leixoes» de Playdoit.
    #
    # Lo que sí tienen que separar es el filial del PRIMER equipo, y eso lo
    # hacen todas por igual. `RUIDO_CLUB` ya tira «ii», «b» y «u20» de los
    # tokens para que el nombre base identifique al club; la marca es lo que
    # distingue después qué equipo de ese club juega.
    #
    # También cubre las selecciones inferiores («Brasil U20 vs Chile U20»),
    # que casan entre sí y nunca con la absoluta.
    ('filial', re.compile(
        r'\bu-?(?:15|16|17|18|19|20|21|23)\b|'
        r'\bsub-?\s?(?:15|16|17|18|19|20|21|23)\b|'
        r'\((?:r|b|ii)\)|'
        r'\b(?:youth|juvenil|junioren|jugend|reserves?|reservas?|filial)\b',
        re.I)),
)

# Marca DÉBIL de filial: «Benfica II», «Real Madrid B». Significa lo mismo que
# «Reserves», pero con dos caracteres que también aparecen donde no significan
# nada: «Primera B Metropolitana», «Liga II», «Juan Pablo II». Medido sobre el
# tablón real, usarla para FILTRAR costaba seis emparejamientos correctos y no
# arreglaba ninguno que las marcas fuertes no cubrieran ya.
#
# Así que no filtra: DESEMPATA. Cuando dos candidatos encajan igual de bien,
# gana el que coincida con el buscado en llevarla o no. Una preferencia no
# puede perder cobertura; un filtro sí.
_MARCA_FILIAL_DEBIL = re.compile(r'\b(?:ii|b)\s*$', re.I)

# v125 — EL SUFIJO DE ESTADO BRASILEÑO ES LA IDENTIDAD DEL CLUB, NO ADORNO.
#
# `normalizar` machaca los guiones y los paréntesis, así que «Athletico-PR» y
# «Atlético-MG» acaban compartiendo el único token significativo («atletico») y
# `_sim_club` los da por el MISMO equipo con similitud **1,0**. No es un
# empate que la guardia de ambigüedad pueda cazar: es una coincidencia
# perfecta con el club equivocado.
#
# Medido el 2026-08-11 pidiendo «Athletico-PR vs Bragantino»:
#
#     devuelve  «Bragantino vs Atlético-MG»  ·  score 1,0
#     y encima de otra competición (Copa Sudamericana) y otra fecha
#
# El daño no es cosmético. Con el tablero de esa ficha, la Sección 1 declaraba
# «Empate @ 16,00 · +392 % sobre el mercado», que es un precio de otro partido.
# Un usuario podría apostarlo.
#
# En Brasil el sufijo de dos letras ES el club: PR = Paranaense, MG = Mineiro,
# GO = Goianiense, RJ, SP, RS, SC, CE, BA, MT, MS, PE, PB, AL, RN. Se trata
# como el sufijo de filial: si dos candidatos llevan sufijos DISTINTOS, son
# equipos distintos y no se pueden emparejar.
_ESTADOS_BR = ('pr', 'mg', 'go', 'rj', 'sp', 'rs', 'sc', 'ce', 'ba', 'mt',
               'ms', 'pe', 'pb', 'al', 'rn', 'pa', 'ma', 'pi', 'to', 'ro',
               'ac', 'am', 'ap', 'rr', 'se', 'df', 'es')
_MARCA_ESTADO = re.compile(
    r'[-(\s](' + '|'.join(_ESTADOS_BR) + r')\s*\)?\s*$', re.I)


def marca_estado(nombre: str) -> str:
    """
    El sufijo de estado brasileño de un nombre de club, o '' si no lo lleva.

    «Athletico-PR» → 'pr' · «Atlético-MG» → 'mg' · «Bragantino» → ''.
    """
    m = _MARCA_ESTADO.search(str(nombre or '').strip())
    return m.group(1).lower() if m else ''


@lru_cache(maxsize=50_000)
def categoria_partido(home: str, away: str, liga: str = '') -> frozenset:
    """
    Marcas de categoría de un partido: `{'fem'}`, `{'filial'}`, las dos o
    ninguna. Sin marcas es el caso por defecto: el absoluto masculino.

    Sólo marcas INEQUÍVOCAS, porque esto sí filtra. Valen vengan del equipo o
    de la competición: «Argentina - Primera Division Women» es la única pista
    de que ese partido es femenino, ya que sus equipos no la llevan.
    """
    marcas = set()
    for t in (home, away, liga):
        t = str(t or '').strip()
        if not t:
            continue
        for nombre, patron in _MARCAS_CATEGORIA:
            if patron.search(t):
                marcas.add(nombre)
    return frozenset(marcas)


@lru_cache(maxsize=50_000)
def _filial_debil(home: str, away: str) -> bool:
    """¿Algún equipo lleva el sufijo «II»/«B»?"""
    return any(_MARCA_FILIAL_DEBIL.search(str(t or '').strip())
               for t in (home, away))


@lru_cache(maxsize=50_000)
def categoria_efectiva(home: str, away: str, liga: str = '') -> frozenset:
    """
    La categoría con la que se compara: las marcas inequívocas MÁS el sufijo
    «II»/«B» de los nombres de equipo.

    Existe porque cada fuente escribe el filial a su manera y todas quieren
    decir lo mismo. Medido en el tablón del 2026-08-09:

        Pinnacle «Benfica II»                Playdoit «Benfica Sub-21»
        Pinnacle «Monagas II»                Playdoit «Monagas SC Reserves»
        Pinnacle «New England Revolution II» Bovada   «New England Revolution (R)»

    Sin esto, la marca fuerte de un lado y la débil del otro daban categorías
    distintas y siete partidos correctos se quedaban sin precio. Con esto, «X
    II» y «X Reserves» son el mismo equipo, y ninguno de los dos casa con «X»
    a secas — que es justo lo que se busca.
    """
    marcas = set(categoria_partido(home, away, liga))
    if _filial_debil(home, away):
        marcas.add('filial')
    return frozenset(marcas)


def _dias_entre(f1, f2) -> Optional[float]:
    """Días entre dos fechas ISO, o None si alguna falta o no se entiende."""
    if not f1 or not f2:
        return None
    try:
        a, b = pd.Timestamp(f1), pd.Timestamp(f2)
        if pd.isna(a) or pd.isna(b):
            return None
        a = a.tz_convert(None) if a.tzinfo else a
        b = b.tz_convert(None) if b.tzinfo else b
        return abs((a - b).total_seconds()) / 86400.0
    except Exception:
        return None


# Tolerancia de fecha al emparejar. Dos días cubre de sobra las diferencias de
# huso y los aplazamientos de unas horas que publican distinto cada casa, y
# corta en seco el caso que motivó la guardia: dos partidos del mismo cruce
# separados cinco días (ida y vuelta, o dos categorías distintas).
TOLERANCIA_DIAS = 2.0


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
        if mk.get('period') != 0:
            continue
        # v114 — LAS LÍNEAS ALTERNATIVAS SE GUARDAN, YA NO SE TIRAN.
        #
        # Esto descartaba todo lo marcado `isAlternate`, así que de cada
        # partido quedaba UNA sola línea de goles y el hándicap principal:
        # medido, 1,0 líneas de totales y 2,0 de spread por partido. Pinnacle
        # las manda todas en la misma respuesta (`primaryOnly: false` ya
        # estaba puesto); simplemente se estaban ignorando.
        #
        # Importa porque es lo que deja sin material a las combinadas con
        # precio real: con cinco mercados cotizados no hay de dónde sacar
        # varias opciones distintas, y la casilla «solo mercados con cuota
        # REAL» respondía «no hay suficientes mercados vigentes» aun teniendo
        # el tablón entero descargado.
        #
        # Las alternativas van a un cajón APARTE (`totales_alt`,
        # `spreads_alt`): `cuotas`, `totales` y `spreads` siguen conteniendo
        # exactamente lo de siempre —la línea principal— para no cambiarle el
        # significado a ningún consumidor que ya los lea.
        _alt = bool(mk.get('isAlternate'))
        mid = mk.get('matchupId')
        tipo = mk.get('type')
        precios = {p.get('designation'): p.get('price')
                   for p in (mk.get('prices') or [])}
        d = por_id.setdefault(mid, {})
        # v75: precios en crudo (con su participantId) — los specials como BTTS
        # no usan `designation` sino participantes nombrados 'Yes'/'No'.
        if not _alt:
            d.setdefault('_precios', []).extend(mk.get('prices') or [])
        if tipo == 'moneyline':
            if not _alt:
                d['moneyline'] = precios
        elif tipo == 'total':
            linea = None
            for p in (mk.get('prices') or []):
                if p.get('points') is not None:
                    linea = p['points']
                    break
            if linea is not None:
                # la principal en `totales` (comportamiento de siempre) y
                # TODAS —principal incluida— en `totales_alt`
                if not _alt:
                    d.setdefault('totales', {})[str(linea)] = precios
                d.setdefault('totales_alt', {})[str(linea)] = precios
        elif tipo == 'spread':
            for p in (mk.get('prices') or []):
                if p.get('points') is None:
                    continue
                if not _alt:
                    d.setdefault('spreads', {}).setdefault(
                        str(p['points']), {})[p.get('designation')] = p.get('price')
                d.setdefault('spreads_alt', {}).setdefault(
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
            # v114 — TODAS las líneas, principal y alternativas. `totales` y
            # `spreads` de arriba siguen siendo sólo la principal; estas dos
            # son las que dan material a las combinadas con precio real.
            'totales_alt': {k: {kk: american_a_decimal(vv)
                                for kk, vv in (v or {}).items()}
                            for k, v in (precios.get('totales_alt') or {}).items()},
            'spreads_alt': {k: {kk: american_a_decimal(vv)
                                for kk, vv in (v or {}).items()}
                            for k, v in (precios.get('spreads_alt') or {}).items()},
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
# 3-bis. UNIBET (Kambi) — la quinta casa (v111)
#
# Por qué esta y no otra
# ----------------------
# El line shopping es la única vía del proyecto con ROI positivo Y robusto
# (+11,49 % en el tramo de juicio, p5 +1,73 %), y vive de la dispersión entre
# casas: cada precio nuevo multiplica las oportunidades sin tocar el modelo.
#
# Se sondearon quince candidatas (`_v111_casas_candidatas.json`). Casi todas
# están cerradas a peticiones automáticas: FanDuel, BetMGM y Betfair devuelven
# 403; DraftKings no resuelve; Caliente, Codere, OddsPortal y Flashscore sirven
# HTML montado por JavaScript; Cloudbet exige clave. Las que la v71 ya descartó
# (Smarkets, Betano, 1xBet, Betsson, Marathonbet) no se volvieron a probar.
#
# Kambi es la única con JSON abierto y catálogo real: 380 partidos de fútbol
# con cuota en 126 competiciones, más tenis (90), béisbol (15) y baloncesto
# (16). La v71 la había descartado mirando otro endpoint que devolvía 185
# eventos casi todos de esports; `listView/{deporte}.json` es el bueno.
#
# UNA SOLA MARCA, Y ESTO NO ES NEGOCIABLE
# ---------------------------------------
# Kambi es una plataforma compartida: Unibet, 888sport, LeoVegas, Rizk, Casumo,
# ATG y una docena más cuelgan del MISMO motor de precios. Comprobado sobre los
# 272 partidos que `ub` y `atg` publican a la vez: **248 idénticos, 24
# distintos (9 %)**, y esos 24 difieren en céntimos (2,90 contra 2,95) — ruido
# de captura entre dos peticiones separadas por segundos, no dos opiniones.
#
# Añadir varias marcas fabricaría dispersión FALSA: el sistema vería «una casa
# paga más que otra» donde hay un único precio, y emitiría picks de line
# shopping inexistentes. Es exactamente la trampa del EV+ ilusorio que la v25
# documentó. Si alguien quiere «añadir más casas», que no sean marcas de Kambi.
# ---------------------------------------------------------------------------
KAMBI = ('https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/'
         '{path}.json?lang=en_GB&market=GB')
KAMBI_PATH = {'futbol': 'football', 'tenis': 'tennis',
              'mlb': 'baseball', 'nba': 'basketball'}
_MEM_UNI: Dict[str, tuple] = {}


def _indice_unibet(deporte: str) -> Dict[str, dict]:
    """{clave_partido: {...,'cuotas':{home,draw,away}}} desde Unibet (Kambi)."""
    path = KAMBI_PATH.get(deporte)
    if not path:
        return {}
    cacheado = _leer_cache(f'unibet_{deporte}.json')
    if cacheado is not None:
        return cacheado
    j = _get(KAMBI.format(path=path), headers=UA_WEB, timeout=30)
    if not j:
        logger.warning(f"[unibet] {deporte}: sin respuesta")
        return {}
    indice: Dict[str, dict] = {}
    for bloque in (j.get('events') or []):
        ev = bloque.get('event') or {}
        # sólo PREPARTIDO: una cuota en vivo no es comparable con el resto del
        # tablón, que es de línea previa.
        if ev.get('state') not in (None, 'NOT_STARTED'):
            continue
        home, away = ev.get('homeName'), ev.get('awayName')
        if not home or not away:
            continue
        # v111 — FUERA LOS ESPORTS, QUE AQUÍ VIENEN MEZCLADOS CON EL FÚTBOL.
        #
        # El feed de «football» incluye «Esports Battle (2x4min)» y «Cyber Live
        # Arena»: partidas de FIFA entre jugadores, no partidos. Llegan con
        # nombres como «Barcelona (dm1trena)» y son 22+19+18 de los 380
        # eventos. Si entran al tablón, el emparejado difuso los casa con el
        # Barcelona de verdad y el line shopping compara el precio de un
        # partido real contra el de una partida de consola de cuatro minutos.
        # Ese es el tipo de error que no da excepción y envenena una apuesta.
        _ruta = ' '.join(str(p.get('name') or '') for p in (ev.get('path') or []))
        _texto = f'{_ruta} {ev.get("group") or ""}'.lower()
        if any(t in _texto for t in ('esport', 'e-sport', 'cyber',
                                     'live arena', 'simulated')):
            continue
        cuotas: Dict[str, float] = {}
        for oferta in (bloque.get('betOffers') or []):
            crit = ((oferta.get('criterion') or {}).get('label') or '').lower()
            # el mercado del ganador se llama distinto en cada deporte
            if not any(k in crit for k in ('match odds', 'moneyline', '1x2',
                                           'full time')):
                continue
            for oc in (oferta.get('outcomes') or []):
                try:
                    # Kambi publica la cuota en MILÉSIMAS (2700 = 2.70)
                    dec = float(oc.get('odds') or 0) / 1000.0
                except (TypeError, ValueError):
                    continue
                if dec <= 1:
                    continue
                lado = {'OT_ONE': 'home', 'OT_CROSS': 'draw',
                        'OT_TWO': 'away'}.get(oc.get('type'))
                if lado:
                    cuotas[lado] = round(dec, 4)
            if cuotas.get('home') and cuotas.get('away'):
                break
        if not (cuotas.get('home') and cuotas.get('away')):
            continue
        ruta = [p.get('name') for p in (ev.get('path') or [])]
        indice[f'{normalizar(home)}|{normalizar(away)}'] = {
            'home': home, 'away': away,
            'liga': ' — '.join(x for x in ruta[1:] if x) or ev.get('group'),
            'fecha': fecha_normalizada(ev.get('start')),
            'casa': 'Unibet',
            'cuotas': cuotas}
    _escribir_cache(f'unibet_{deporte}.json', indice)
    logger.info(f"[unibet] {deporte}: {len(indice)} partidos con cuotas")
    return indice


def _indice_uni(deporte: str) -> Dict[str, dict]:
    ts, idx = _MEM_UNI.get(deporte, (0, None))
    if idx is None or time.time() - ts > TTL:
        with _LOCK:
            idx = _indice_unibet(deporte)
            _MEM_UNI[deporte] = (time.time(), idx)
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
            # v122: el identificador del evento en Altenar. El listado sólo
            # trae cinco mercados por partido; el detalle trae ciento y pico
            # (ver `mercados_playdoit`), y sin este número no hay forma de
            # pedirlo. Guardarlo aquí cuesta cero peticiones porque el listado
            # ya se estaba descargando entero.
            'event_id': ev.get('id'),
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


# ---------------------------------------------------------------------------
# 4b. PLAYDOIT, EL TABLERO ENTERO DE UN PARTIDO (v122)
#
# Por qué hacía falta
# -------------------
# El usuario lo dijo sin rodeos: «en el mundo real no es posible hacer cuotas
# con diferentes casas. Quiero que me des cuotas también pero solo con la casa
# de Playdoit que es la mía». Y tenía razón: una combinada cuyas patas están
# cada una en una casa distinta NO se puede colocar en ningún sitio. La cuota
# combinada que la app enseñaba era la suma de tres tickets, no un ticket.
#
# El obstáculo era de datos, no de criterio: `GetEvents` —la llamada del
# catálogo, una sola para los 800 partidos— devuelve CINCO mercados por
# evento (1X2, doble oportunidad, empate no acción, Total de 2.5 y ambos
# marcan). Con dos de esos cinco no comparables entre sí (el 1X2 y sus
# derivados son el mismo suceso), no hay material para armar una combinada de
# tres patas en una sola casa.
#
# `GetEventDetails` sí lo tiene. Medido sobre Monterrey vs Juárez el
# 2026-08-10: **182 mercados y 1.239 precios en una sola petición**, con el
# abanico entero de líneas —Total de 1.5 a 3.5 incluidas las asiáticas de
# cuarto, hándicap de +0 a -1.25, totales por equipo, par/impar, marcador
# exacto, mitades y goleador—. Ahí sí hay con qué.
#
# El coste y por qué se paga
# --------------------------
# Es UNA petición POR PARTIDO, frente a una por catálogo entero. Por eso no
# entra en el barrido de `alpha_finder` (que mira cientos de partidos) sino
# sólo en la vista de UN partido, que es donde el usuario decide la combinada.
# Se cachea con el mismo TTL que el resto (30 min).
#
# Lo que este módulo NO decide
# ----------------------------
# Aquí sólo se leen y se normalizan precios. Traducirlos al vocabulario del
# modelo («Más de 2.5 goles», «Monterrey -1.5») es trabajo de `cuotas_tablon`,
# igual que con el resto del tablón: mezclar las dos cosas es lo que hacía
# imposible añadir una casa sin tocar la interfaz.
# ---------------------------------------------------------------------------
ALTENAR_DETALLE = ('https://sb2frontend-altenar2.biahosted.com/api/widget/'
                   'GetEventDetails')


def _selecciones_altenar(m: dict, precios: Dict[int, dict]) -> List[dict]:
    """
    Las selecciones de un mercado del detalle, con su precio.

    El detalle no usa `oddIds` como el listado: usa `desktopOddIds`, que es una
    **matriz** (filas × columnas de la rejilla que pinta su web). Se aplana
    conservando el orden de lectura, que es el que empareja «Más de 2.5» con su
    precio.
    """
    filas = m.get('desktopOddIds') or m.get('mobileOddIds') or m.get('oddIds') or []
    ids: List[int] = []
    for f in filas:
        if isinstance(f, list):
            ids.extend(f)
        else:
            ids.append(f)
    out = []
    for i in ids:
        o = precios.get(i)
        if not o:
            continue
        try:
            p = float(o.get('price'))
        except (TypeError, ValueError):
            continue
        if p <= 1.0:
            continue
        out.append({'nombre': ' '.join(str(o.get('name') or '').split()),
                    'cuota': round(p, 4), 'tipo': o.get('typeId'),
                    'competidor': o.get('competitorId')})
    return out


def mercados_playdoit(deporte: str, home: str, away: str, fecha=None,
                      liga: Optional[str] = None) -> Optional[Dict]:
    """
    TODOS los mercados que Playdoit publica de un partido, normalizados.

    Devuelve `None` cuando el partido no está en su catálogo, que es un
    resultado legítimo y frecuente: Playdoit no cotiza todas las ligas que
    cotiza Pinnacle. Nunca lanza — sin red, la vista sigue entera y la sección
    de la casa del usuario dice que hoy no hay precio.

        {'casa': 'Playdoit', 'event_id': 17147596,
         'home': 'Monterrey', 'away': 'Juarez', 'liga': 'Liga MX', ...
         'mercados': [{'tipo': 18, 'nombre': 'Total', 'sv': '3.5',
                       'selecciones': [{'nombre': 'Más de 2.5', 'cuota': 1.5264,
                                        'tipo': 12, 'competidor': None}, ...]}]}

    `home`/`away` son los del LLAMADOR, no los de Altenar: si el emparejador
    detecta que la casa publica el partido con los bandos al revés, aquí ya
    sale enderezado (`invertido`), que es la misma disciplina que sigue
    `cuotas_partido` con el 1X2 desde la v77.
    """
    try:
        ent = _buscar(_indice_pdt(deporte), home, away, deporte, fecha, liga)
    except Exception as e:
        logger.info(f'[playdoit] sin catálogo para el detalle: '
                    f'{type(e).__name__}: {e}')
        return None
    if not ent or not ent.get('event_id'):
        return None
    eid = ent['event_id']
    # Los nombres de equipo que usa la casa, para que quien traduzca sepa a
    # cuál de los dos se refiere «Monterrey (-0.5)». El orden de `competitors`
    # NO es fiable (misma lección que la v77 con « @ »): se toma el del
    # emparejador, que ya resolvió la orientación.
    invertido = bool(ent.get('invertido'))
    casa_home = ent.get('away') if invertido else ent.get('home')
    casa_away = ent.get('home') if invertido else ent.get('away')

    # SE CACHEA LO NORMALIZADO, NO LA RESPUESTA CRUDA.
    #
    # El detalle en bruto pesa 250-320 KB por partido (1.239 precios y 182
    # mercados, la mayoría de goleador). Guardarlo tal cual sería dejar 30 MB
    # en disco por cada cien partidos que alguien mire, y el contenedor de
    # Streamlit Cloud es efímero y pequeño. Normalizado se queda en una décima
    # parte y no se pierde nada: lo que se tira son los identificadores de
    # rejilla y los mercados sin precio.
    #
    # Y se cachea sólo la parte que NO depende de quién pregunta: `home` y
    # `away` los pone el llamador y pueden venir escritos de otra forma en la
    # siguiente llamada, así que meterlos en el fichero sería servirle a uno
    # los nombres de otro.
    mercados = _leer_cache(f'playdoit_ev_{eid}.json')
    if mercados is None:
        try:
            j = _get(ALTENAR_DETALLE,
                     params={**ALTENAR_BASE, 'eventId': eid},
                     headers=UA_PDT, timeout=40)
        except Exception as e:
            logger.info(f'[playdoit] detalle {eid} falló: '
                        f'{type(e).__name__}: {e}')
            return None
        if not isinstance(j, dict) or not j.get('markets'):
            return None
        precios = {o['id']: o for o in (j.get('odds') or []) if o.get('id')}
        mercados = []
        vistos = set()
        # v130 — LOS MERCADOS DE JUGADOR VIVEN EN `childMarkets`, Y SE CAÍAN.
        #
        # `markets` trae el mercado PADRE de cada familia de jugador, sin
        # precios propios: sus selecciones cuelgan de `childMarketIds` y el
        # detalle las sirve aparte, en `childMarkets`. Como `_selecciones_altenar`
        # sólo mira los ids del propio mercado, esos padres salían vacíos y se
        # descartaban — con ellos, TODA la oferta por jugador.
        #
        # Medido en DET vs CLE (evento 16238906): 149 mercados en `markets`, de
        # los que 32 son padres sin precio; en el crudo hay 262 apariciones de
        # `sa:player`. Entre lo que se estaba tirando estaba esto:
        #
        #     Strikeouts del jugador al menos (Keider Montero (DET))
        #         2+ 1,18 · 3+ 1,57 · 4+ 2,15 · 5+ 3,20 · 6+ 5,00 · 7+ 9,00
        #
        # o sea la ESCALERA COMPLETA de ponches del abridor, que es justo lo que
        # hacía falta para proponer una línea alternativa cuando la principal no
        # da valor. El diagnóstico anterior —«Playdoit no cotiza ponches por
        # jugador»— era un error de lectura de este bucle, no un hecho de la
        # casa; lo corrigió el usuario, que sí los veía en su pantalla.
        for m in list(j.get('markets') or []) + list(j.get('childMarkets') or []):
            sels = _selecciones_altenar(m, precios)
            if not sels:
                continue
            nombre = ' '.join(str(m.get('name') or '').split())
            clave = (m.get('typeId'), str(m.get('sv')), nombre)
            if clave in vistos:
                # el detalle repite los mercados destacados en su cabecera; el
                # segundo ejemplar trae los mismos precios y sólo duplicaría
                # filas
                continue
            vistos.add(clave)
            mercados.append({'tipo': m.get('typeId'), 'nombre': nombre,
                             'sv': m.get('sv'), 'selecciones': sels})
        if not mercados:
            return None
        _escribir_cache(f'playdoit_ev_{eid}.json', mercados)
        _purgar_detalles_playdoit()
    if not mercados:
        return None
    return {'casa': CASA_PRIORITARIA, 'event_id': eid,
            'home': home, 'away': away,
            'casa_home': casa_home, 'casa_away': casa_away,
            'liga': ent.get('liga'),
            # La fecha del índice ya viene normalizada, pero se vuelve a pasar
            # por el normalizador y no se copia tal cual: el índice puede
            # llegar de un fichero de caché escrito por una versión anterior, y
            # entonces lo que hay dentro es lo que hubiera entonces. La función
            # es idempotente sobre un ISO, así que esto no cuesta nada y cierra
            # la única vía por la que un 1970-01-01 podría volver a colarse.
            'fecha': fecha_normalizada(ent.get('fecha')),
            'invertido': invertido, 'mercados': mercados}


def _purgar_detalles_playdoit(max_edad: int = 6 * 3600) -> int:
    """
    Borra los tableros de partido ya caducados.

    A diferencia del resto del caché, que son unos pocos ficheros con nombre
    fijo (uno por casa y deporte) y se sobrescriben, éstos son UNO POR PARTIDO:
    sin limpieza se acumulan para siempre, porque `_leer_cache` los ignora
    cuando caducan pero no los borra. En el contenedor de Streamlit Cloud eso
    acaba llenando el disco, y un disco lleno no da un aviso: mata el proceso.

    Se conservan seis horas, muy por encima del TTL de 30 min, para que un
    despliegue o un reinicio no obligue a redescargar lo que ya estaba.

    v130 — Y ADEMÁS UN TOPE DE TAMAÑO, PORQUE LOS TABLEROS HAN CRECIDO.
    ------------------------------------------------------------------
    Al bajar a `childMarkets` un tablero pasa de 170 a 794 mercados en fútbol
    (395 KB por partido en vez de 40), porque aparecen los ~480 mercados de
    goleador que antes se caían. La edad sola ya no basta: seis horas de
    navegación por fichas caben de sobra en el disco de Streamlit Cloud, y ahí
    un disco lleno no avisa, mata el proceso.
    """
    n = 0
    try:
        d = _cache_path('')
        ficheros = []
        for nombre in os.listdir(d):
            if not nombre.startswith('playdoit_ev_'):
                continue
            p = os.path.join(d, nombre)
            try:
                ficheros.append((os.path.getmtime(p), os.path.getsize(p), p))
            except OSError:
                pass
        # 1) por edad
        vivos = []
        for mt, tam, p in ficheros:
            if time.time() - mt > max_edad:
                try:
                    os.remove(p)
                    n += 1
                except OSError:
                    pass
            else:
                vivos.append((mt, tam, p))
        # 2) por tamaño total: se borran los más antiguos hasta bajar del tope.
        #    Se conserva SIEMPRE el más reciente, que es el que se acaba de
        #    escribir y el que la pantalla está usando ahora mismo.
        vivos.sort(key=lambda x: x[0])          # el más viejo primero
        total = sum(t for _, t, _ in vivos)
        while total > MAX_CACHE_PLAYDOIT and len(vivos) > 1:
            mt, tam, p = vivos.pop(0)
            try:
                os.remove(p)
                total -= tam
                n += 1
            except OSError:
                total -= tam
    except Exception as e:
        logger.debug(f'[playdoit] purga del caché: {type(e).__name__}: {e}')
    return n


# ---------------------------------------------------------------------------
# 6. MATCHBOOK — el EXCHANGE (v114)
#
# Por qué se buscaba una casa como ésta
# --------------------------------------
# La v113 dejó la prioridad medida: el edge del proyecto está en el PRECIO, y
# con las cinco casas anteriores el margen conjunto es 1,0574 y hay CERO
# arbitrajes. Betfair Exchange era la pieza que faltaba —da el mejor precio el
# 35,4 % de las veces en el histórico de football-data— pero está CERRADO desde
# México: bloquea por geolocalización de red, no por scraping. Eso no se
# arregla con cabeceras y la API oficial exige una cuenta que exige residencia
# admitida.
#
# Se sondearon 41 alternativas (`_v114_sondeo_casas.py`). Sólo tres respondían
# con datos: Matchbook, Polymarket y Kalshi. Y al medirlas contra el tablón
# real (`_v114_medir_exchanges.py`, 2026-08-09):
#
#   Matchbook   152 partidos de fútbol · margen medio 1,0337
#               cubre 125 de los 642 partidos de Pinnacle (19 %)
#               da el MEJOR precio el 14,2 % de las veces
#               y donde está, mejora al mejor de las casas en 244 de 373
#               selecciones (65,4 %), con +1,80 % de media
#               baja el margen del mejor precio de 1,0546 a 1,0495
#   Polymarket  margen 1,0000 (no cobra), pero 21 partidos y CERO coincidencias
#               con nuestro tablón: sus nombres son de otro registro
#               («Cruzeiro EC», «AFC Ajax») y su catálogo de fútbol es mínimo.
#               No se integra: un precio que nunca casa no aporta nada.
#   Kalshi      su primera página no trae deporte y operar exige residencia en
#               EE. UU. Descartada por cobertura.
#
# LA COMISIÓN NO ES UN DETALLE
# ----------------------------
# Un exchange no cobra margen en la cuota: cobra COMISIÓN sobre la ganancia
# neta. Comparar su back «a pelo» contra el precio de una casa sería inflarlo,
# y con una mejora media de +1,80 % la comisión se come casi todo. Así que aquí
# la cuota se guarda YA NETA: una back de 3,00 con 2 % de comisión paga
# 1 + 2,00 × 0,98 = 2,96. Es el precio que el usuario cobraría de verdad.
#
# PARA QUÉ SIRVE AUNQUE NO SE APUESTE ALLÍ
# ----------------------------------------
# Aunque nunca se abra cuenta, un libro de órdenes sin margen es la MEJOR
# estimación disponible de la probabilidad real, mejor que Pinnacle. Eso lo
# convierte en el ancla de `devig` — y un ancla mejor mueve el EV de todo el
# tablón, no sólo el de este operador.
# ---------------------------------------------------------------------------
MATCHBOOK = 'https://www.matchbook.com/edge/rest/events'
MATCHBOOK_SPORT = {'futbol': 15, 'tenis': 9, 'mlb': 3, 'nba': 4}
# Comisión sobre la ganancia neta. 2 % es la tarifa estándar del operador; se
# deja configurable porque baja con el volumen y quien apueste allí de verdad
# querrá poner la suya.
COMISION_EXCHANGE = float(os.environ.get('COMISION_EXCHANGE', '0.02'))

# UN PRECIO SIN DINERO DETRÁS NO ES UN PRECIO.
#
# Ésta es la diferencia esencial entre un exchange y una casa: la casa cotiza
# lo que está dispuesta a aceptar, el exchange enseña lo que alguien ha dejado
# puesto. En un libro poco líquido, «el mejor back disponible» puede ser una
# orden residual de dos euros a una cuota absurda. Medido en el primer volcado
# real (2026-08-09):
#
#     Los Andes vs Ferro Carril Oeste   home 98,02   away 1,1274
#     Maringá vs Amazonas               home  2,6464 (Pinnacle 1,3891,
#                                                     Bovada 1,5181)
#
# Si eso entra al tablón, el line shopping elige 98,02 como «mejor precio» y
# fabrica un EV gigantesco sobre una apuesta que no se puede colocar más que
# por dos euros. Es el mismo tipo de fallo silencioso que el emparejador de
# esta misma versión: no da excepción, da una apuesta.
#
# Dos guardias, las dos objetivas:
#   · IMPORTE — se exige que haya al menos este dinero disponible a ese precio.
#   · LIBRO COMPLETO — si la suma de probabilidades implícitas de los backs
#     baja de este umbral, el libro no está cotizado entero (falta dinero en
#     algún lado) y el partido no entra. Un exchange sano ronda 1,00-1,04; por
#     debajo de 0,95 lo que hay es un hueco, no una oportunidad.
IMPORTE_MINIMO_EXCHANGE = float(os.environ.get('IMPORTE_MINIMO_EXCHANGE', '25'))
MARGEN_MINIMO_EXCHANGE = 0.95

_MEM_MB: Dict[str, tuple] = {}


def cuota_neta_exchange(cuota: float,
                        comision: Optional[float] = None) -> Optional[float]:
    """Cuota de back descontada la comisión sobre la ganancia neta."""
    try:
        c = float(cuota)
    except (TypeError, ValueError):
        return None
    if c <= 1:
        return None
    com = COMISION_EXCHANGE if comision is None else comision
    return round(1.0 + (c - 1.0) * (1.0 - com), 4)


def _indice_matchbook(deporte: str) -> Dict[str, dict]:
    """{clave_partido: {...,'cuotas':{home,draw,away}}} desde Matchbook."""
    sid = MATCHBOOK_SPORT.get(deporte)
    if not sid:
        return {}
    cacheado = _leer_cache(f'matchbook_{deporte}.json')
    if cacheado is not None:
        return cacheado
    indice: Dict[str, dict] = {}
    # el catálogo se pagina de 50 en 50; se recorre hasta que deje de haber
    # eventos o se llegue al tope, que evita un bucle infinito si la API
    # devolviera siempre la misma página
    for offset in range(0, 500, 50):
        j = _get(MATCHBOOK, params={
            'sport-ids': sid, 'states': 'open', 'include-prices': 'true',
            'price-depth': 3, 'odds-type': 'DECIMAL',
            'exchange-type': 'back-lay', 'currency': 'EUR',
            'per-page': 50, 'offset': offset}, headers=UA_WEB, timeout=30)
        eventos = (j or {}).get('events') or []
        if not eventos:
            break
        for e in eventos:
            nombre = str(e.get('name') or '')
            if ' vs ' not in nombre:
                continue
            home, away = [x.strip() for x in nombre.split(' vs ', 1)]
            if not home or not away:
                continue
            for m in (e.get('markets') or []):
                if str(m.get('market-type')) not in ('one_x_two', 'two_way'):
                    continue
                cuotas: Dict[str, float] = {}
                for run in (m.get('runners') or []):
                    nom = str(run.get('name') or '').strip()
                    if nom.lower() in ('draw', 'the draw', 'empate'):
                        lado = 'draw'
                    elif normalizar(nom) == normalizar(home):
                        lado = 'home'
                    elif normalizar(nom) == normalizar(away):
                        lado = 'away'
                    else:
                        continue
                    # sólo precios CON DINERO DETRÁS (ver el comentario de
                    # `IMPORTE_MINIMO_EXCHANGE`)
                    backs = [p.get('odds') for p in (run.get('prices') or [])
                             if p.get('side') == 'back' and p.get('odds')
                             and float(p.get('available-amount') or 0)
                             >= IMPORTE_MINIMO_EXCHANGE]
                    if not backs:
                        continue
                    # el mejor precio DISPONIBLE para respaldar esa selección,
                    # ya neto de comisión (ver el comentario de arriba)
                    neta = cuota_neta_exchange(max(backs))
                    if neta:
                        cuotas[lado] = neta
                # el libro tiene que estar cotizado ENTERO: si falta dinero en
                # una de las salidas, las otras no son precios comparables
                _suma = sum(1.0 / v for v in cuotas.values() if v)
                if _suma < MARGEN_MINIMO_EXCHANGE:
                    logger.debug(
                        f'[matchbook] {home} vs {away}: libro incompleto '
                        f'(suma {_suma:.4f} < {MARGEN_MINIMO_EXCHANGE}), fuera')
                    continue
                if cuotas.get('home') and cuotas.get('away'):
                    indice[f'{normalizar(home)}|{normalizar(away)}'] = {
                        'home': home, 'away': away,
                        'liga': ((e.get('meta-tags') or [{}])[0] or {}).get('name'),
                        'fecha': fecha_normalizada(e.get('start')),
                        'casa': 'Matchbook', 'exchange': True,
                        'cuotas': cuotas}
                    break
    _escribir_cache(f'matchbook_{deporte}.json', indice)
    logger.info(f"[matchbook] {deporte}: {len(indice)} partidos con cuotas "
                f"(netas de {COMISION_EXCHANGE*100:.1f} % de comisión)")
    return indice


def _indice_mb(deporte: str) -> Dict[str, dict]:
    ts, idx = _MEM_MB.get(deporte, (0, None))
    if idx is None or time.time() - ts > TTL:
        with _LOCK:
            idx = _indice_matchbook(deporte)
            _MEM_MB[deporte] = (time.time(), idx)
    return idx


def _buscar(indice: Dict[str, dict], home: str, away: str,
            deporte: str = 'futbol', fecha=None,
            liga: Optional[str] = None) -> Optional[dict]:
    """
    Empareja el partido contra el tablón, tolerando cómo escribe cada fuente.

    Se prueba primero la clave exacta y luego una búsqueda por similitud
    ESPECÍFICA DEL DEPORTE: clubes por palabras significativas (para que
    «Gremio» case con «Gremio FBPA» y «Dinamo Moscow» con «Dynamo Moscow»),
    tenistas por apellido + inicial (para que «Mensik J.» case con «Jakub
    Mensik»). Se exige que AMBOS participantes casen, así que un apellido
    común no basta para colar un partido equivocado.

    v114 — DOS GUARDIAS Y UNA DESAMBIGUACIÓN, porque el nombre no basta.

    El emparejador miraba SÓLO los nombres, y con eso casó un partido de la
    Primera División femenina argentina con uno de la Liga Profesional
    masculina jugado cinco días después, bandos invertidos incluidos. Las
    cuotas resultantes eran de otro partido, así que el EV era ficción.

      · CATEGORÍA — un partido femenino y uno masculino del mismo club no son
        el mismo partido. `fecha` y `liga` son opcionales para no obligar a
        tocar a los siete llamadores; sin ellos la guardia sigue funcionando
        con los nombres, que es donde la marca suele venir.
      · FECHA — si el llamador sabe cuándo se juega y el candidato trae fecha,
        más de `TOLERANCIA_DIAS` de diferencia descarta el candidato.
      · AMBIGÜEDAD — si al final quedan dos candidatos DISTINTOS empatados en
        el mejor score, no se elige uno a dedo: se devuelve None y se registra.
        Antes ganaba el primero del diccionario, que es un orden arbitrario.

    Devolver None es un resultado correcto: el partido aparecerá «sin cuota»,
    que es honesto. Devolver la cuota de otro partido, no.
    """
    cat_ref = categoria_efectiva(home, away, liga or '')
    sim = _sim_tenista if deporte == 'tenis' else _sim_club
    umbral = 0.86 if deporte == 'tenis' else 0.80

    def _compatible(v: dict) -> bool:
        """¿Este candidato puede ser el mismo partido que el buscado?"""
        if categoria_efectiva(v.get('home') or '', v.get('away') or '',
                              v.get('liga') or '') != cat_ref:
            return False
        d = _dias_entre(fecha, v.get('fecha'))
        return d is None or d <= TOLERANCIA_DIAS

    h, a = normalizar(home), normalizar(away)
    for clave in (f'{h}|{a}', f'{a}|{h}'):
        v = indice.get(clave)
        # la clave exacta también se comprueba: dos partidos del mismo cruce
        # (ida y vuelta) comparten clave, y la categoría puede venir en la liga
        if v is not None and _compatible(v):
            r = dict(v)
            r['invertido'] = clave == f'{a}|{h}' and h != a
            return r

    # v125 — el sufijo de estado brasileño manda sobre la similitud. Ver
    # `marca_estado`: «Athletico-PR» y «Atlético-MG» puntúan 1,0 entre sí
    # porque el normalizador se come el sufijo, y ése es justo el único trozo
    # del nombre que los distingue.
    def _mismo_estado(pedido: str, candidato: str) -> bool:
        a_, b_ = marca_estado(pedido), marca_estado(candidato)
        return not (a_ and b_ and a_ != b_)

    candidatos: List[tuple] = []          # (score, invertido, clave, valor)
    for clave, v in indice.items():
        if not _compatible(v):
            continue
        ph, pa = v['home'], v['away']
        s1 = min(sim(home, ph), sim(away, pa))       # el peor de los dos manda
        s2 = min(sim(home, pa), sim(away, ph))
        if not (_mismo_estado(home, ph) and _mismo_estado(away, pa)):
            s1 = 0.0
        if not (_mismo_estado(home, pa) and _mismo_estado(away, ph)):
            s2 = 0.0
        s, inv = (s1, False) if s1 >= s2 else (s2, True)
        if s >= umbral:
            candidatos.append((s, inv, clave, v))
    if not candidatos:
        return None

    mejor_score = max(c[0] for c in candidatos)
    finalistas = [c for c in candidatos if c[0] >= mejor_score - 1e-9]
    # desempate por el sufijo «II»/«B» (ver `_MARCA_FILIAL_DEBIL`): entre dos
    # candidatos igual de buenos, el filial va con el filial y el primer
    # equipo con el primer equipo. Si ninguno coincide, se dejan los dos y
    # decide la guardia de ambigüedad de abajo.
    if len(finalistas) > 1:
        _ref = _filial_debil(home, away)
        _iguales = [c for c in finalistas
                    if _filial_debil(c[3]['home'], c[3]['away']) == _ref]
        if _iguales:
            finalistas = _iguales
    if len({c[2] for c in finalistas}) > 1:
        _cuales = ', '.join('{} vs {}'.format(c[3]['home'], c[3]['away'])
                            for c in finalistas[:4])
        logger.warning(
            f"[emparejado] «{home} vs {away}» empata a {mejor_score:.3f} con "
            f"{len(finalistas)} partidos distintos ({_cuales}) — se descarta "
            f"por ambiguo en vez de elegir uno al azar")
        return None

    s, inv, _clave, v = finalistas[0]
    r = dict(v)
    r['invertido'] = inv
    r['emparejado_difuso'] = round(s, 3)
    return r


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


# v115 — MEMORIA DE PARTIDO YA RESUELTO.
#
# `cuotas_partido` no toca la red (los índices de cada casa ya están cacheados
# 30 min), pero sí recorre el tablón entero UNA VEZ POR CASA para emparejar:
# seis casas × ~800 partidos. Y la interfaz lo llama varias veces por pantalla
# —la tabla de cuotas, el motor de combinadas, la lista de mercados con EV—,
# así que ese trabajo se repetía tal cual tres o cuatro veces por render.
#
# Se memoiza el resultado por (deporte, home, away, fecha, liga) con el mismo
# TTL que los índices: si el tablón no se ha refrescado, la respuesta no puede
# haber cambiado. Sólo se cachean las llamadas SIN `odds_espn` ni `espn_ref`,
# que son las que dependen únicamente de esos cinco argumentos.
_MEM_PARTIDO: Dict[tuple, tuple] = {}
_MAX_MEM_PARTIDO = 4000


def limpiar_memoria_partidos() -> None:
    """Olvida los partidos resueltos (para tests y para forzar recálculo)."""
    _MEM_PARTIDO.clear()


def cuotas_partido(deporte: str, home: str, away: str,
                   odds_espn: Optional[dict] = None,
                   espn_ref: Optional[tuple] = None,
                   fecha=None, liga: Optional[str] = None,
                   clave_consenso: Optional[str] = None) -> Dict:
    """
    Todas las cuotas disponibles de un partido, de todas las fuentes.

    v114 — `fecha` y `liga` son OPCIONALES y sirven para desambiguar (ver
    `_buscar`). Quien las sepa —el barrido las tiene en el fixture— evita que
    el emparejador confunda este partido con otro del mismo cruce en otra
    fecha o en otra categoría. Quien no las pase se comporta como siempre.

    v129 — `clave_consenso` SEPARA DOS COSAS QUE ESTABAN PEGADAS.
    ------------------------------------------------------------
    `liga` se usa como TEXTO para detectar categoría (femenino, filial): ver
    `categoria_efectiva`. La v127 la reutilizó además como clave de la lista
    blanca del consenso ampliado, y ahí se rompió, porque quien más llama a
    esta función pasa el CÓDIGO DE ESPN, no la clave del proyecto:

        fixtures_espn._completar_cuotas → liga='mex.1', 'esp.1', 'ita.1'…
        lista blanca de consenso_api    → 'liga_mx', 'laliga', 'serie_a'…

    Intersección: NINGUNA. O sea que el barrido del día —que es el que ve casi
    todos los partidos— nunca llegaba a pedir el consenso ampliado, y el
    contador de créditos se quedaba en cero con la clave puesta y funcionando.
    Sólo la vista de partido, que sí pasa la clave del proyecto, lo activaba.

    No se puede arreglar cambiando lo que se pasa en `liga`: ese texto es lo
    que ve el guardia de categoría, y sustituirlo por la clave del proyecto
    cambiaría a quién empareja. Así que la clave del consenso viaja aparte y
    cae a `liga` cuando no se pasa, que es como se comportaba la vista de
    partido y por eso allí seguía funcionando.

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
    # v115 — lectura del caché (ver `_MEM_PARTIDO`). Sólo cuando la respuesta
    # depende exclusivamente de estos cinco argumentos.
    _cacheable = odds_espn is None and espn_ref is None
    # v129: `clave_consenso` entra en la clave del caché. Si no entrara, la
    # primera llamada sin consenso dejaría cacheada una respuesta de 6 casas y
    # la siguiente —ya con la clave de la lista blanca— se la comería.
    _clave_mem = (deporte, normalizar(home), normalizar(away),
                  str(fecha or '')[:10], str(liga or ''),
                  str(clave_consenso or ''))
    if _cacheable:
        _hit = _MEM_PARTIDO.get(_clave_mem)
        if _hit and (time.time() - _hit[0]) < TTL:
            return _hit[1]

    casas: Dict[str, dict] = {}
    fuentes = []
    # v114: todas las líneas de goles y hándicap de Pinnacle (ver más abajo)
    lineas_totales: Dict[str, dict] = {}
    lineas_spread: Dict[str, dict] = {}
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

    pin = _buscar(_indice(deporte), home, away, deporte, fecha, liga)
    if pin and pin.get('cuotas'):
        c = dict(pin['cuotas'])
        if pin.get('invertido'):          # Pinnacle listó al revés: se voltea
            c['home'], c['away'] = c.get('away'), c.get('home')
        _ah = _spread_principal(pin.get('spreads'), pin.get('invertido'))
        if _ah:
            ah_casa['Pinnacle'] = _ah
        # v114 — todas las líneas de goles y de hándicap, no sólo la principal.
        # Es lo que convierte «cinco mercados con precio» en «veinte», y con
        # ello hace posible armar VARIAS combinadas con cuota real en vez de
        # una. Se entregan en crudo (línea -> precios) y ya orientadas al
        # local si la casa listó los equipos al revés.
        lineas_totales = dict(pin.get('totales_alt') or {})
        lineas_spread = {}
        for _k, _v in (pin.get('spreads_alt') or {}).items():
            try:
                _L = float(_k)
            except (TypeError, ValueError):
                continue
            if pin.get('invertido'):
                lineas_spread[str(-_L)] = {'home': (_v or {}).get('away'),
                                           'away': (_v or {}).get('home')}
            else:
                lineas_spread[str(_L)] = dict(_v or {})
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
    bov = _buscar(_indice_bov(deporte), home, away, deporte, fecha, liga)
    if bov and bov.get('cuotas'):
        c = dict(bov['cuotas'])
        if bov.get('invertido'):
            c['home'], c['away'] = c.get('away'), c.get('home')
        if c.get('home') and c.get('away'):
            casas['Bovada'] = {k: v for k, v in c.items()
                               if k in ('home', 'draw', 'away')}
            fuentes.append('bovada')

    # v111: Unibet (Kambi) — la quinta casa. Ver `_indice_unibet` para por qué
    # es ésta y por qué SOLO ésta de todas las marcas de Kambi.
    uni = _buscar(_indice_uni(deporte), home, away, deporte, fecha, liga)
    if uni and uni.get('cuotas'):
        c = dict(uni['cuotas'])
        if uni.get('invertido'):
            c['home'], c['away'] = c.get('away'), c.get('home')
        if c.get('home') and c.get('away'):
            casas['Unibet'] = {k: v for k, v in c.items()
                               if k in ('home', 'draw', 'away')}
            fuentes.append('unibet')

    # v114: Matchbook — el EXCHANGE. Su precio va NETO de comisión (ver
    # `_indice_matchbook`), así que es comparable con el de una casa sin
    # inflarlo. Aporta el mejor precio el 14,2 % de las veces y baja el margen
    # del mejor precio de 1,0546 a 1,0495 sobre el tablón medido.
    mb = _buscar(_indice_mb(deporte), home, away, deporte, fecha, liga)
    if mb and mb.get('cuotas'):
        c = dict(mb['cuotas'])
        if mb.get('invertido'):
            c['home'], c['away'] = c.get('away'), c.get('home')
        if c.get('home') and c.get('away'):
            casas['Matchbook'] = {k: v for k, v in c.items()
                                  if k in ('home', 'draw', 'away')}
            fuentes.append('matchbook')

    # v76: Playdoit — la casa donde el usuario apuesta de verdad. Va la última
    # a propósito: si algo falla en su API, las tres anteriores ya han dado
    # precio y el barrido no se resiente.
    pdt = _buscar(_indice_pdt(deporte), home, away, deporte, fecha, liga)
    if pdt and pdt.get('cuotas'):
        c = dict(pdt['cuotas'])
        if pdt.get('invertido'):
            c['home'], c['away'] = c.get('away'), c.get('home')
        if c.get('home') and c.get('away'):
            casas['Playdoit'] = {k: v for k, v in c.items()
                                 if k in ('home', 'draw', 'away')}
            fuentes.append('playdoit')

    # v126 — EL CORE DE ESPN ENTRA SIEMPRE, NO SÓLO CUANDO NO HAY NADIE.
    #
    # Estaba puesto como último recurso (`if not casas`), o sea que en cuanto
    # una sola casa cotizaba el partido, la casa que sirve ESPN —DraftKings—
    # se descartaba. Era un miembro del consenso tirado a la basura, y el
    # consenso es justo lo que le falta a este sistema: medido el 2026-08-11,
    # de 50 mercados de un partido sólo 13 tenían una segunda casa con la que
    # compararse, y por eso la Sección 1 salía vacía.
    #
    # Añadir una casa al consenso no mejora el modelo, pero sí mejora la
    # ÚNICA señal con ROI positivo del proyecto: saber si el precio de la casa
    # del usuario está por encima o por debajo del resto del mercado.
    #
    # No pisa a nadie: `setdefault` deja intacto lo que ya haya, así que si
    # DraftKings ya vino por otra vía se conserva la primera lectura.
    if espn_ref:
        extra = cuotas_core_espn(*espn_ref)
        if extra:
            nuevas = [k for k in extra if k not in casas]
            for k, v in extra.items():
                casas.setdefault(k, v)
            if nuevas:
                fuentes.append('espn_core')

    # v127 — EL CONSENSO AMPLIADO, DENTRO DEL PLAN GRATUITO.
    #
    # Medido: este proveedor devuelve 18-23 casas en el mismo partido donde
    # nosotros teníamos cinco, con una dispersión real de hasta el 14,6 % en el
    # mismo resultado. Esa dispersión es la única señal con ROI positivo del
    # proyecto, y con cinco casas no se ve.
    #
    # El coste está acotado por `consenso_api`: lista blanca de ligas, una llamada
    # por LIGA (no por partido) cacheada 30 min, y un corte duro a los 450
    # créditos del mes. Si no hay clave, si la liga no está en la lista o si el
    # presupuesto se agotó, esto devuelve {} y el tablón sigue con sus cinco
    # casas de siempre — que es el comportamiento anterior, intacto.
    _clave_oa = clave_consenso or liga
    if _clave_oa:
        try:
            import consenso_api as _oa
            if _oa.disponible():
                extra2 = _oa.casas_del_partido(_clave_oa, home, away)
                nuevas2 = [k for k in extra2 if k not in casas]
                for k, v in extra2.items():
                    casas.setdefault(k, v)
                if nuevas2:
                    fuentes.append('consenso_api')
        except Exception as e:
            logger.info(f'[consenso] no aportó al consenso: '
                        f'{type(e).__name__}: {e}')

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
    salida = {'casas': reales, 'mejor': mejor, 'preferida': preferida,
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
            # v114 — TODAS las líneas de goles y de hándicap que publica el
            # ancla sharp, no sólo la principal. Es lo que da material para
            # armar varias combinadas con precio real; `cuotas_tablon` las
            # traduce al vocabulario de la plantilla.
            'lineas_totales': lineas_totales or None,
            'lineas_handicap': lineas_spread or None,
            'pinnacle': reales.get('Pinnacle'), 'n_casas': len(reales),
            'fuentes': fuentes,
            'emparejado_difuso': (pin or {}).get('emparejado_difuso')}
    if _cacheable:
        if len(_MEM_PARTIDO) > _MAX_MEM_PARTIDO:
            _MEM_PARTIDO.clear()      # tope simple: el TTL hace el resto
        _MEM_PARTIDO[_clave_mem] = (time.time(), salida)
    return salida


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
