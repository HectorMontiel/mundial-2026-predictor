#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v180 — EL DICCIONARIO EQUIPO -> LIGA LOCAL. Construido con dato, no adivinado.

QUÉ RESUELVE, con el caso que lo motivó
---------------------------------------
Para estimar los córners de un Como o un Viking FK en Champions hace falta su
histórico de LIGA LOCAL, porque en Champions tienen cero partidos. Y para eso
hay que saber en qué liga juegan.

Buscarlo con emparejamiento difuso contra las 46 ligas produce esto, medido:

    Internazionale -> brasil  Internacional      Juventus -> brasil  Juventude
    Atalanta       -> liga_mx Atlante            Arsenal  -> rus     Arsenal Tula
    Lille          -> noruega Lillestrom         Braga    -> suecia  Brage

Y lo peor no es fallar: es que **no se nota**. Sale un número con aspecto de
córner normal y nadie vuelve a mirarlo. Es el mismo modo de fallo que el
proyecto ya tiene anotado con `Botafogo ↔ Botafogo SP`.

LA IDEA, QUE ES DEL USUARIO Y ES LA CORRECTA
--------------------------------------------
Un equipo **pertenece** a una liga, y eso es un hecho que se puede mirar en vez
de adivinar. Con la pertenencia fijada, el emparejamiento de nombres deja de
buscar entre 1.069 equipos de 47 países y busca entre los 18 o 20 de UNA liga —
que es exactamente para lo que `name_mapper` está hecho y donde acierta.

DE DÓNDE SALE, Y POR QUÉ NO CUESTA NI UNA PETICIÓN
--------------------------------------------------
Dos fuentes locales que ya están en el repositorio:

  1. `goleadores_cache.json` guarda `teams:<liga>` con los equipos que ESPN
     publica de cada competición: 47 ligas, 1.069 equipos. Los descarga el
     workflow de rosters, porque ESPN bloquea `/teams` desde IPs de centro de
     datos (v147).
  2. Los propios `historico_<liga>.csv`. Cubren las ligas que faltan en esa
     caché —la Bundesliga entre ellas, y por eso el Bayern y el Dortmund no
     casaban— y, sobre todo, dan **el nombre tal y como está escrito en el
     histórico**, que es el que hace falta para leer sus córners.

DESAMBIGUACIÓN: EL LIVERPOOL URUGUAYO
-------------------------------------
91 equipos aparecen en más de una competición, y no todos son el mismo club:

    Liverpool  ->  premier, uru_primera, libertadores

Tres reglas, en este orden:

  · las COPAS no otorgan pertenencia. Un equipo no «es» de la Libertadores ni
    de la Champions: juega ahí. Sólo las ligas domésticas asignan.
  · si aun así quedan varias, gana la liga donde el equipo tiene MÁS PARTIDOS
    en su histórico. El Liverpool inglés tiene cientos en la Premier; el
    uruguayo, los suyos en `uru_primera`, y cada uno se queda con el que es.
  · si hay empate o no hay histórico, se deja SIN asignar. Un mapa que se
    calla es mucho mejor que uno que se inventa.
"""
import io
import json
import logging
import os
import unicodedata
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('catalogo_equipos')

FICHERO = os.environ.get('CATALOGO_EQUIPOS', 'catalogo_equipos.json')
CACHE_ROSTERS = 'goleadores_cache.json'

# Competiciones que NO otorgan pertenencia: son torneos, no ligas domésticas.
# Un club juega la Libertadores; es de su liga.
#
# La lista fija se quedó corta y el fallo fue silencioso: `eng_carabao` no
# estaba y el Manchester City acabó asignado a la Carabao Cup en vez de a la
# Premier. Así que se completa mirando el NOMBRE de cada competición en
# `config`, que es donde está escrito qué es cada cosa.
COPAS = {
    'champions', 'europa_league', 'conference_league', 'afc_champions',
    'leagues_cup', 'libertadores', 'sudamericana', 'copa_libertadores',
    'copa_sudamericana', 'bra_copa', 'eng_fa_cup', 'esp_copa_rey',
    'eng_carabao', 'mundial', 'internacionales',
}
_PISTAS_COPA = ('cup', 'copa', 'coupe', 'pokal', 'trophy', 'supercopa',
                'libertadores', 'sudamericana')


def _es_copa(clave: str) -> bool:
    if clave in COPAS:
        return True
    try:
        import config
        nombre = str((config.LEAGUES.get(clave) or {}).get('nombre', '')).lower()
    except Exception:
        return False
    return any(p in nombre for p in _PISTAS_COPA)


# ALIAS EXPLÍCITOS: lo que el emparejador resuelve MAL y hay que fijar a mano.
#
# `name_mapper` manda «Paris Saint-Germain» a «Paris FC» y lo hace con
# confianza alta —comparten «Paris» y la regla de contención se dispara—, así
# que subir el umbral no lo arregla: con 0,95 sigue dando «Paris FC». Y son dos
# clubes distintos que juegan en la MISMA liga.
#
# Un alias a mano es la respuesta honesta a esto: son pocos, se revisan uno a
# uno y tienen test. Lo que no vale es dejar que el emparejador decida y
# enterarse el día que el PSG salga con los córners del Paris FC.
ALIAS = {
    'paris saint germain': ('ligue_1', 'Paris SG'),
}

# Un equipo «juega» en la liga donde ha aparecido en el último año. Con ese
# corte, un ascenso o un descenso se refleja en cuanto hay una jornada nueva.
try:
    import pandas as _pd_cat
    _HACE_UN_ANIO = _pd_cat.Timestamp.now().normalize() - _pd_cat.Timedelta(days=365)
    _VIEJO = _pd_cat.Timestamp('1900-01-01')
except Exception:                                    # pragma: no cover
    _HACE_UN_ANIO = None
    _VIEJO = None

_CACHE: Optional[Dict] = None


def normalizar(nombre) -> str:
    """Nombre comparable: sin acentos, sin puntuación, en minúsculas."""
    s = unicodedata.normalize('NFKD', str(nombre or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace('.', '').replace('-', ' ').replace("'", '')
    return ' '.join(s.split())


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------
def _de_la_cache_de_rosters() -> Dict[str, List[str]]:
    """{equipo normalizado: [ligas que lo listan]} según ESPN."""
    salida = defaultdict(list)
    if not os.path.exists(CACHE_ROSTERS):
        return salida
    try:
        with io.open(CACHE_ROSTERS, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        logger.warning('[catalogo] no se pudo leer %s: %s', CACHE_ROSTERS, e)
        return salida
    for k, v in doc.items():
        if not str(k).startswith('teams:'):
            continue
        liga = str(k).split(':', 1)[1]
        if _es_copa(liga):
            continue
        for eq in ((v or {}).get('data') or []):
            n = normalizar(eq.get('nombre'))
            if n:
                salida[n].append(liga)
    return salida


def _de_los_historicos() -> Tuple[Dict[str, List[str]], Dict[Tuple[str, str], str],
                                  Dict[Tuple[str, str], int]]:
    """
    Recorre `historico_<liga>.csv` y devuelve tres cosas:

      pertenencia  {equipo: [ligas]}
      nombre_real  {(equipo, liga): nombre tal cual en ese histórico}
      partidos     {(equipo, liga): cuántos partidos tiene ahí}

    El nombre real es lo que de verdad hace falta: para leer los córners del
    Bayern en la Bundesliga hay que pedirlos por «Bayern Munich», que es como
    los escribe su histórico, no por el nombre que usa ESPN en la Champions.
    """
    import pandas as pd
    import config

    pertenencia = defaultdict(list)
    nombre_real: Dict[Tuple[str, str], str] = {}
    partidos: Dict[Tuple[str, str], int] = defaultdict(int)
    ultimo: Dict[Tuple[str, str], object] = {}
    for clave in config.LEAGUES:
        if _es_copa(clave):
            continue
        ruta = 'historico_%s.csv' % clave
        if not os.path.exists(ruta):
            continue
        try:
            df = pd.read_csv(ruta, usecols=['date', 'home_team', 'away_team'])
        except Exception:
            continue
        largo = pd.concat([
            df[['date', 'home_team']].rename(columns={'home_team': 'e'}),
            df[['date', 'away_team']].rename(columns={'away_team': 'e'})])
        largo = largo.dropna(subset=['e'])
        for crudo, sub in largo.groupby('e'):
            e = normalizar(crudo)
            if not e:
                continue
            if clave not in pertenencia[e]:
                pertenencia[e].append(clave)
            partidos[(e, clave)] += int(len(sub))
            nombre_real.setdefault((e, clave), str(crudo))
            try:
                ultimo[(e, clave)] = max(ultimo.get((e, clave), _VIEJO),
                                         pd.to_datetime(sub['date'],
                                                        errors='coerce').max())
            except Exception:
                pass
    return pertenencia, nombre_real, partidos, ultimo


def construir() -> Dict[str, Dict]:
    """El diccionario completo. Es puro cálculo local: no toca la red."""
    por_espn = _de_la_cache_de_rosters()
    por_hist, nombre_real, partidos, ultimo = _de_los_historicos()
    # El catálogo de nombres de cada histórico, para emparejar dentro de él.
    catalogos: Dict[str, List[str]] = defaultdict(list)
    for (e_, liga_), crudo_ in nombre_real.items():
        catalogos[liga_].append(crudo_)

    equipos = set(por_espn) | set(por_hist)
    salida: Dict[str, Dict] = {}
    for e in sorted(equipos):
        if e in ALIAS:
            liga_a, nombre_a = ALIAS[e]
            salida[e] = {'liga': liga_a, 'en_historico': nombre_a,
                         'partidos': partidos.get((e, liga_a), 0),
                         'motivo': 'alias', 'candidatas': None}
            continue
        candidatas = sorted(set(por_espn.get(e, [])) | set(por_hist.get(e, [])))
        candidatas = [c for c in candidatas if not _es_copa(c)]
        if not candidatas:
            continue
        if len(candidatas) == 1:
            liga = candidatas[0]
            motivo = 'unica'
        else:
            # DÓNDE JUEGA AHORA MANDA SOBRE DÓNDE JUGÓ MÁS.
            #
            # El desempate por número de partidos mandó al Como a la Serie B:
            # 114 partidos allí con el último en mayo de 2024, contra 79 en la
            # Serie A con el último hace cinco días. Ascendió, y el catálogo
            # seguía mirando su pasado — y la Serie B ni siquiera tenía sus
            # córners observados, así que el partido se quedaba sin estadística.
            #
            # Primero se filtra por RECIENTE: las ligas donde el equipo ha
            # jugado en el último año. Sólo si ninguna lo es —o si hay varias—
            # se recurre al volumen.
            recientes = [c for c in candidatas
                         if ultimo.get((e, c)) is not None
                         and ultimo[(e, c)] >= _HACE_UN_ANIO]
            en_juego = recientes if recientes else candidatas
            marcador = {c: partidos.get((e, c), 0) for c in en_juego}
            mejor = max(marcador.values()) if marcador else 0
            ganadoras = [c for c, v in marcador.items() if v == mejor]
            if mejor == 0 or len(ganadoras) != 1:
                logger.debug('[catalogo] %s ambiguo entre %s: sin asignar',
                             e, candidatas)
                continue
            liga = ganadoras[0]
            motivo = 'reciente' if recientes else 'mas_partidos'
        en_hist = nombre_real.get((e, liga))
        if not en_hist:
            # EL PASO QUE CIERRA EL CÍRCULO, Y AQUÍ SÍ ES SEGURO EMPAREJAR.
            #
            # ESPN dice «Borussia Dortmund» y su histórico dice «Dortmund»;
            # «Internazionale» contra «Inter»; «Paris Saint-Germain» contra
            # «Paris SG». Son el mismo club con otro rótulo, que es justo el
            # problema para el que existe `name_mapper`.
            #
            # Y ahora se puede usar sin miedo porque el ÁMBITO ya está
            # decidido: se busca entre los 18 o 20 equipos de ESA liga, no
            # entre los 1.069 de 61 competiciones. Ésa es la diferencia entre
            # encontrar «Dortmund» y encontrar «Juventude».
            en_hist = _en_el_historico_de(e, liga, catalogos.get(liga) or [])
        salida[e] = {
            'liga': liga,
            'en_historico': en_hist,
            'partidos': partidos.get((e, liga), 0),
            'motivo': motivo,
            'candidatas': candidatas if len(candidatas) > 1 else None,
        }
    return salida


def _en_el_historico_de(equipo_norm: str, liga: str, catalogo: List[str]
                        ) -> Optional[str]:
    """El nombre de ese equipo en el histórico de esa liga, o None."""
    if not catalogo:
        return None
    try:
        import name_mapper
    except Exception:
        return None
    try:
        return name_mapper.mapear(equipo_norm, list(catalogo),
                                  contexto='catalogo_equipos') or None
    except Exception:
        return None


def guardar(mapa: Optional[Dict] = None, ruta: Optional[str] = None) -> int:
    """Deja el diccionario en disco. Devuelve cuántos equipos tiene."""
    mapa = construir() if mapa is None else mapa
    ruta = ruta or FICHERO
    try:
        import io_atomico
        io_atomico.escribir_json(ruta, mapa, indent=0)
    except Exception:
        with io.open(ruta, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(mapa, f, ensure_ascii=False, indent=0, sort_keys=True)
    return len(mapa)


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def _leer() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    doc = {}
    try:
        with io.open(FICHERO, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        logger.debug('[catalogo] sin fichero %s (%s): se construye al vuelo',
                     FICHERO, e)
        try:
            doc = construir()
        except Exception as e2:
            logger.warning('[catalogo] no se pudo construir: %s', e2)
            doc = {}
    _CACHE = doc if isinstance(doc, dict) else {}
    return _CACHE


def liga_de(equipo: str) -> Optional[str]:
    """La liga local del equipo, o None si no consta. Nunca adivina."""
    d = _leer().get(normalizar(equipo))
    return (d or {}).get('liga')


def nombre_en_su_liga(equipo: str) -> Optional[Tuple[str, str]]:
    """
    `(clave_liga, nombre en el histórico de esa liga)`, o None.

    Es lo que hace falta para ir a buscar sus córners: la liga dice en qué
    fichero mirar y el nombre dice por quién preguntar.
    """
    d = _leer().get(normalizar(equipo))
    if not d or not d.get('liga') or not d.get('en_historico'):
        return None
    return d['liga'], d['en_historico']


def olvidar() -> None:
    """Vacía la caché en memoria. Lo usan los tests."""
    global _CACHE
    _CACHE = None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    n = guardar()
    print('%s: %d equipos' % (FICHERO, n))
