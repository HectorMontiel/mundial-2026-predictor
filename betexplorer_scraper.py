#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuotas 1X2 del Mundial desde Betexplorer (v14/M10) — gratuito, sin clave.

Betexplorer solo sirve en HTML estático la lista de PARTIDOS DEL DÍA (el
detalle por torneo carga vía JS), así que este scraper:
  1. Baja esa lista (una sola petición, robots.txt lo permite).
  2. Se queda con los partidos donde AMBOS equipos son selecciones del
     Mundial (mapeo nombre inglés -> código FIFA).
  3. En días de partido del Mundial eso captura exactamente las cuotas que
     el parlay necesita; el resto de días devuelve vacío sin coste.

Ética: 1 petición por corrida, User-Agent real, sin paralelismo.
"""

import logging
from typing import Dict, List

import pandas as pd
import requests

from config import TEAMS, NAME_EN_TO_FIFA

logger = logging.getLogger(__name__)

URL = 'https://www.betexplorer.com/football/world/world-cup/fixtures/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
# UAs alternativos para rotar ante un 429 (v41 §resiliencia)
UAS = [UA,
       ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
        '(KHTML, like Gecko) Version/17.0 Safari/605.1.15'),
       ('Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0')]


def _get(url: str, intentos: int = 3, timeout: int = 25):
    """GET con reintento y backoff ante 429/5xx (v41). Rota User-Agent. Ético:
    espera creciente, no martillea. Devuelve el Response o lanza la última
    excepción para que el llamador la registre y degrade a la siguiente
    fuente de la cadena de resiliencia."""
    import time
    ultima = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers={'User-Agent': UAS[i % len(UAS)],
                                           'Accept-Language': 'en-US,en;q=0.9'},
                             timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                ultima = requests.HTTPError(f"{r.status_code} en {url}")
                time.sleep(2 * (i + 1))          # 2 s, 4 s, 6 s
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            ultima = e
            time.sleep(1.5 * (i + 1))
    raise ultima if ultima else RuntimeError(f"GET falló: {url}")

# nombres Betexplorer -> inglés estándar (solo donde difieren)
BETEXPLORER_ALIAS = {
    'South Korea': 'South Korea', 'Korea Republic': 'South Korea',
    'USA': 'United States', 'Ivory Coast': 'Ivory Coast',
    'Cape Verde': 'Cabo Verde',
}


def _a_fifa(nombre: str):
    n = BETEXPLORER_ALIAS.get(nombre.strip(), nombre.strip())
    return NAME_EN_TO_FIFA.get(n)


# ---------------------------------------------------------------------------
# v31 (§4): tenis y baloncesto. VERIFICADO 2026-07-22: las URLs del spec
# (/tennis/matches-today/) devuelven la página de FÚTBOL; la ruta real es
# /next/{deporte}/ (tabla con spans --home/--away y botones data-odd).
# ---------------------------------------------------------------------------
URL_NEXT = 'https://www.betexplorer.com/next/{}/'


def _partidos_next(deporte: str, filtro_href: str = '') -> List[Dict]:
    """Partidos próximos de Betexplorer con cuotas medias (2 vías)."""
    from bs4 import BeautifulSoup
    try:
        r = _get(URL_NEXT.format(deporte))
    except Exception as e:
        logger.warning(f"[betexplorer/{deporte}] no disponible: {e}")
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    out = []
    for tr in soup.select('tr'):
        odds = [b.get('data-odd') for b in tr.select('button[data-odd]')]
        a = tr.select_one('a.table-main__teamsLink')
        if not a or len(odds) < 2:
            continue
        href = a.get('href') or ''
        if filtro_href and filtro_href not in href:
            continue
        h = a.select_one('.table-main__teamLine--home')
        v = a.select_one('.table-main__teamLine--away')
        if not h or not v:
            continue
        try:
            o1, o2 = float(odds[0]), float(odds[1])
        except (TypeError, ValueError):
            continue
        out.append({'home': h.get_text(strip=True), 'away': v.get_text(strip=True),
                    'odd_home': o1, 'odd_away': o2, 'href': href})
    logger.info(f"[betexplorer/{deporte}] {len(out)} partidos"
                + (f" (filtro '{filtro_href}')" if filtro_href else ''))
    return out


def cuotas_tenis_hoy(solo_atp: bool = True) -> List[Dict]:
    """Partidos de tenis próximos con cuotas. Por defecto solo ATP (el modelo
    está entrenado con ATP; los ITF/Challenger tienen otro nivel)."""
    return _partidos_next('tennis', 'atp-single' if solo_atp else '')


def cuotas_baloncesto_hoy(solo_nba: bool = True) -> List[Dict]:
    """Partidos de baloncesto próximos con cuotas (por defecto solo NBA)."""
    return _partidos_next('basketball', '/nba/' if solo_nba else '')


def normalizar_nombre(nombre: str) -> str:
    """Normaliza a 'apellido i.' (minúsculas, sin tildes) para el fuzzy."""
    import unicodedata
    n = unicodedata.normalize('NFKD', str(nombre))
    n = ''.join(c for c in n if not unicodedata.combining(c))
    return ' '.join(n.lower().replace('.', ' ').split())


# v195 — LA CLAVE DEL CACHÉ LLEVA EL CATÁLOGO, Y ANTES NO.
#
# Era `{nombre: resultado}` a secas, y a esta función la llaman con DOS
# catálogos distintos: el de ATP y el de WTA. `_picks_tenis` lo hace a
# propósito —«el circuito puede venir mal etiquetado por la fuente: se intenta
# con el otro motor antes de darlo por no enlazado»—, y ese reintento no podía
# funcionar: la primera llamada guardaba `None` bajo el nombre y la segunda lo
# leía sin volver a mirar. El reintento llevaba desde la v72 sin reintentar
# nada.
_CACHE_FUZZY: Dict[tuple, str] = {}

# Índices por catálogo, para no recorrer 14.000 nombres en cada consulta.
_IDX_CATALOGO: Dict[tuple, dict] = {}


def _huella(catalogo: List[str]) -> tuple:
    """Identifica un catálogo sin recorrerlo entero."""
    if not catalogo:
        return (0, '', '')
    return (len(catalogo), catalogo[0], catalogo[-1])


def _indice_jugadores(catalogo: List[str], huella: tuple) -> dict:
    """
    Índice del catálogo: apellido, prefijo de apellido, palabras y nombres ya
    normalizados. Se construye UNA vez por catálogo.

    v195 — EL MISMO BARRIDO DIFUSO QUE YA COSTÓ 22,7 s EN LA v178.
    ---------------------------------------------------------------
    `emparejar_jugador` comparaba el nombre contra los 13.561 del catálogo de
    ATP (14.746 en WTA), dos veces: una con `_sim_tenista` y otra con
    `SequenceMatcher`. Medido el 2026-09-12 perfilando la rama de tenis:

        emparejar_jugador   46,0 s de los 61,6 s del barrido de tenis
                            218 llamadas a 211 ms cada una

    Es, letra por letra, la segunda de las tres regresiones de la v178
    —«emparejado difuso contra 1.900 nombres, +22,7 s, índice por palabra,
    0,0003 s por consulta»— repetida aquí con un catálogo siete veces mayor.
    La solución es la misma: no comparar contra todo, sino contra lo que puede
    ganar.

    Lo que NO cambia es el criterio. `_sim_tenista` devuelve 0 salvo que los
    apellidos se parezcan (≥0,85) o compartan una palabra de más de dos letras,
    así que la lista corta se construye con exactamente esas puertas: apellido
    igual, una palabra en común, o el apellido compartiendo su arranque, su
    final o su interior. Y se recorre en el ORDEN DEL CATÁLOGO para que los
    empates se resuelvan como siempre.

    LOS TROZOS DEL APELLIDO NO SON ADORNO, y costaron dos mediciones. Con sólo
    el arranque de cuatro letras, el índice cambiaba 16 resultados de 1.434:
    «Anastasia Gasanova» no alcanzaba a «Andrin Casanova» (difieren en la
    primera letra) ni «Maeda Rio» a «Rios M.» (el apellido cambia de longitud,
    y ahí la ventana de cuatro tampoco vale). Con arranque, final e interior de
    TRES letras: **cero diferencias en 1.418 consultas** —709 nombres reales
    contra los dos catálogos— frente al barrido exhaustivo.

    Que en alguno de esos 16 el índice acertara MÁS que el original da igual:
    acelerar cambiando a quién se empareja es cambiar las predicciones, y eso
    no es una optimización, es otro modelo.
    """
    idx = _IDX_CATALOGO.get(huella)
    if idx is not None:
        return idx
    from cuotas_multi import _clave_tenista, normalizar
    por_clave: Dict[str, list] = {}
    por_prefijo: Dict[str, list] = {}
    por_palabra: Dict[str, list] = {}
    normalizados = []
    for i, c in enumerate(catalogo):
        try:
            ap = _clave_tenista(c)[0]
        except Exception:
            ap = ''
        if ap:
            por_clave.setdefault(ap, []).append(i)
            # tres trozos del apellido: arranque, final y el interior. Un
            # apellido que se parece a otro por encima de 0,85 se diferencia
            # en una letra o dos, así que al menos uno de los tres sobrevive
            # esté donde esté la diferencia. Tres letras y no cuatro porque la
            # diferencia puede ser de LONGITUD: «rio» y «rios» puntúan 0,857 y
            # con ventana de cuatro no se encontraban. Ver la nota de arriba.
            por_prefijo.setdefault(('i', ap[:3]), []).append(i)
            por_prefijo.setdefault(('f', ap[-3:]), []).append(i)
            por_prefijo.setdefault(('m', ap[1:4]), []).append(i)
        try:
            for t in normalizar(c).split():
                if len(t) > 2:
                    por_palabra.setdefault(t, []).append(i)
        except Exception:
            pass
        normalizados.append(normalizar_nombre(c))
    # Y agrupados por LONGITUD del nombre normalizado, en orden de catálogo.
    # Lo usa el segundo pase para ir de la longitud más parecida hacia fuera
    # sin ordenar 13.561 nombres en cada consulta, que era la mitad del coste
    # que quedaba después de meter el índice.
    por_longitud: Dict[int, list] = {}
    for i, nc in enumerate(normalizados):
        por_longitud.setdefault(len(nc), []).append(i)
    idx = {'clave': por_clave, 'prefijo': por_prefijo, 'palabra': por_palabra,
           'norm': normalizados, 'longitud': por_longitud}
    _IDX_CATALOGO[huella] = idx
    return idx


def emparejar_jugador(nombre: str, catalogo: List[str],
                      umbral: float = 0.75):
    """Cruza un nombre de Betexplorer con el catálogo del dataset ATP.
    Devuelve el nombre del catálogo o None (el llamador lo manda a la
    Capa 2 con aviso, nunca lo descarta en silencio — §4.2)."""
    from difflib import SequenceMatcher
    huella = _huella(catalogo)
    ck = (huella, nombre)
    if ck in _CACHE_FUZZY:
        return _CACHE_FUZZY[ck]
    if not catalogo:
        return None
    idx = _indice_jugadores(catalogo, huella)

    # v72 — primero, comparación por APELLIDO + INICIAL.
    #
    # La similitud de cadena sola no sirve cuando las fuentes usan formatos
    # distintos: el catálogo del modelo guarda «Mensik J.» y Pinnacle o Bovada
    # publican «Jakub Mensik». SequenceMatcher entre esas dos cadenas da ~0,55,
    # por debajo del umbral, así que el partido se daba por no enlazado. Con
    # las cuotas de tenis conectadas en v72 eso dejaba 249 de 250 partidos
    # fuera de la Capa 1.
    try:
        from cuotas_multi import _clave_tenista, normalizar, _sim_tenista
        ap = _clave_tenista(nombre)[0]
        posibles = set(idx['clave'].get(ap, ()))
        if ap:
            posibles.update(idx['prefijo'].get(('i', ap[:3]), ()))
            posibles.update(idx['prefijo'].get(('f', ap[-3:]), ()))
            posibles.update(idx['prefijo'].get(('m', ap[1:4]), ()))
        for t in normalizar(nombre).split():
            if len(t) > 2:
                posibles.update(idx['palabra'].get(t, ()))
        mejor_t, score_t = None, 0.0
        for i in sorted(posibles):
            s = _sim_tenista(nombre, catalogo[i])
            if s > score_t:
                mejor_t, score_t = catalogo[i], s
                if score_t >= 1.0:
                    break            # no hay nada por encima de 1,0
        if mejor_t and score_t >= 0.85:
            _CACHE_FUZZY[ck] = mejor_t
            return mejor_t
    except Exception:
        pass

    # Segundo pase, el de similitud de cadena. Es el último recurso y no tiene
    # puerta de entrada por nombre, así que aquí la poda es por LONGITUD, y es
    # exacta: el parecido de dos cadenas no puede pasar de
    #
    #     2·min(la, lb) / (la + lb)
    #
    # De ahí salen dos descartes que no cambian ni un resultado:
    #
    #   · el que no puede llegar al UMBRAL no puede ser la respuesta, porque
    #     por debajo del umbral la función devuelve None de todas formas;
    #   · el que no puede superar al mejor de momento no hace falta ni
    #     compararlo.
    #
    # Y se recorre de la longitud más parecida hacia fuera, para que el mejor
    # suba pronto y la segunda poda muerda desde el principio. Cambiar el orden
    # NO cambia a quién se elige: los empates se resuelven por la posición en
    # el catálogo, igual que hacía el `s > ratio` del recorrido en orden.
    objetivo = normalizar_nombre(nombre)
    largo = len(objetivo)
    normalizados = idx['norm']

    def _tope(lb):
        return 2.0 * min(largo, lb) / max(largo + lb, 1)

    por_longitud = idx['longitud']
    # las longitudes que pueden llegar al umbral, de la más parecida hacia
    # fuera, para que el mejor suba pronto y la poda muerda desde el principio
    longitudes = []
    for d in range(0, max([largo] + list(por_longitud or [0])) + 1):
        for lb in ((largo,) if d == 0 else (largo + d, largo - d)):
            if lb in por_longitud and _tope(lb) >= umbral:
                longitudes.append(lb)
    mejor_i, ratio = None, 0.0
    for lb in longitudes:
        tope = _tope(lb)
        if tope < ratio:
            continue
        for i in por_longitud[lb]:
            if tope == ratio and mejor_i is not None and i > mejor_i:
                continue
            s = SequenceMatcher(None, objetivo, normalizados[i]).ratio()
            if s > ratio or (s == ratio and mejor_i is not None
                             and i < mejor_i):
                mejor_i, ratio = i, s
    resultado = (catalogo[mejor_i]
                 if mejor_i is not None and ratio >= umbral else None)
    _CACHE_FUZZY[ck] = resultado
    return resultado


def cuotas_mundial_hoy() -> pd.DataFrame:
    """Partidos del Mundial de HOY con cuotas 1X2 medias de Betexplorer.

    Devuelve DataFrame [MATCH_ID, odd_home, odd_draw, odd_away] (vacío si
    hoy no juega ninguna selección o si la web no responde).
    """
    try:
        from bs4 import BeautifulSoup
        r = _get(URL)
        soup = BeautifulSoup(r.text, 'lxml')
        filas: List[Dict] = []
        hoy = pd.Timestamp.today().normalize()
        for cont in soup.select('li.table-main__tournamentLiContent'):
            equipos_el = cont.select_one('.table-main__participants')
            odds = [b.get('data-odd') for b in cont.select('button[data-odd]')]
            if equipos_el is None or len(odds) < 3:
                continue
            texto = equipos_el.get_text(' ', strip=True)
            if ' - ' not in texto:
                continue
            nombre_h, nombre_a = [p.strip() for p in texto.split(' - ', 1)]
            home, away = _a_fifa(nombre_h), _a_fifa(nombre_a)
            if home not in TEAMS or away not in TEAMS:
                continue           # no es un partido del Mundial
            filas.append({
                'MATCH_ID': f"{hoy.strftime('%Y%m%d')}_{home}_{away}",
                'odd_home': float(odds[0]), 'odd_draw': float(odds[1]),
                'odd_away': float(odds[2]),
            })
        logger.info(f"Betexplorer: {len(filas)} partidos del Mundial hoy con cuotas.")
        return pd.DataFrame(filas)
    except Exception as e:
        logger.warning(f"Betexplorer no disponible ({e}): sin cuotas del Mundial hoy.")
        return pd.DataFrame()


def _normalizar_club(nombre: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', str(nombre))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _claves_disponibles():
    """v50: TODAS las ligas de clubes con modelo disponible (no solo las 8
    europeas). Así las ligas EN TEMPORADA de verano (Brasil, Argentina, MLS,
    China, nórdicas) también obtienen cuotas 1X2 reales de Betexplorer y sus
    picks pasan de Capa 2 (sin cuota) a Capa 1 (con EV validado)."""
    try:
        from config import LEAGUES
        return tuple(c for c, cfg in LEAGUES.items()
                     if cfg.get('disponible') and cfg.get('formato') != 'espn'
                     and cfg.get('formato') != 'api_football')
    except Exception:
        return ('liga_mx', 'premier', 'laliga', 'serie_a', 'bundesliga',
                'ligue_1', 'eredivisie', 'primeira')


def cuotas_clubes_hoy(claves=None) -> pd.DataFrame:
    """Cuotas 1X2 de HOY para partidos de nuestras ligas de clubes (v18/M2,
    ampliado en v50 a todas las ligas disponibles).

    La página diaria de Betexplorer lista todos los partidos del día con
    cuotas; se emparejan los equipos contra team_stats_{liga}.json (fuzzy,
    cutoff alto para evitar falsos positivos). Es la única fuente gratuita de
    cuotas EN VIVO para Liga MX (fixtures.csv no la cubre). 1 petición.
    """
    if claves is None:
        claves = _claves_disponibles()
    import difflib
    import json as _json
    import os as _os

    indices = {}
    for clave in claves:
        ruta = f'team_stats_{clave}.json'
        if not _os.path.exists(ruta):
            continue
        with open(ruta, encoding='utf-8') as f:
            equipos = list(_json.load(f).get('equipos', {}).keys())
        indices[clave] = {_normalizar_club(e): e for e in equipos}

    def emparejar(nombre):
        norm = _normalizar_club(nombre)
        for indice in indices.values():
            if norm in indice:
                return indice[norm]
            cerca = difflib.get_close_matches(norm, indice.keys(), n=1, cutoff=0.85)
            if cerca:
                return indice[cerca[0]]
        return None

    try:
        from bs4 import BeautifulSoup
        r = _get(URL)
        soup = BeautifulSoup(r.text, 'lxml')
        filas: List[Dict] = []
        hoy = pd.Timestamp.today().normalize()
        for cont in soup.select('li.table-main__tournamentLiContent'):
            equipos_el = cont.select_one('.table-main__participants')
            odds = [b.get('data-odd') for b in cont.select('button[data-odd]')]
            if equipos_el is None or len(odds) < 3:
                continue
            texto = equipos_el.get_text(' ', strip=True)
            if ' - ' not in texto:
                continue
            nombre_h, nombre_a = [p.strip() for p in texto.split(' - ', 1)]
            home, away = emparejar(nombre_h), emparejar(nombre_a)
            if not home or not away:
                continue
            filas.append({
                'MATCH_ID': f"{hoy.strftime('%Y%m%d')}_{home.replace(' ', '-')}_{away.replace(' ', '-')}",
                'odd_home': float(odds[0]), 'odd_draw': float(odds[1]),
                'odd_away': float(odds[2]),
            })
        logger.info(f"Betexplorer: {len(filas)} partidos de clubes hoy con cuotas.")
        return pd.DataFrame(filas)
    except Exception as e:
        logger.warning(f"Betexplorer clubes no disponible ({e}).")
        return pd.DataFrame()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    df = cuotas_mundial_hoy()
    if not df.empty:
        print(df.to_string())
    df2 = cuotas_clubes_hoy()
    if not df2.empty:
        print(df2.to_string())
