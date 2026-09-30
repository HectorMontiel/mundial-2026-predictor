# -*- coding: utf-8 -*-
"""
v316 — LA BASE PROPIA DE RESULTADOS DE TODAS LAS COMPETICIONES DEL TABLERO,
DESDE FLASHSCORE.

El usuario: «te dije que le hagas el modelo a esos partidos, o si no se
puede, dime por qué: no hay histórico, qué falta. Yo quiero que todos los
partidos, todos los equipos, tengan su modelo».

POR QUÉ LA BASE DE FOTMOB NO BASTABA (medido el 2026-09-29)
De 119 partidos del tablero que se quedaban sin modelo propio:
    nombre no encontrado ... 53   (la liga NO está en la base)
    femenil ................ 23
    juveniles .............. 20
    poca historia .......... 13
    reservas ............... 10
La causa de fondo: la consulta por día de FotMob (`matches?date=`) sólo
devuelve 84 competiciones al día (287 partidos el 27-sep), no todas; y su
catálogo entero son 570 competiciones: la liga belga amateur, las reservas
argentinas o la femenil argentina ni siquiera existen en FotMob.

POR QUÉ FLASHSCORE SÍ
El tablero de casas (`cuotas_mx.py`) YA sale de Flashscore, así que:
  · cubre exactamente las competiciones que el usuario ve (75 de 75 con su
    ruta, 562 competiciones en quince días de su feed);
  · escribe a los equipos EXACTAMENTE igual que el tablero: no hay que
    emparejar nombres («Platense 2», «Durham W», «Czech Republic U21»);
  · su página de resultados da la temporada en curso (51-133 partidos
    terminados por liga) y su archivo las anteriores (El Salvador desde
    2020-21, 128 por temporada).

CUÁNTO CUBRE (medido el 2026-09-29, `_v316_modelo_flashscore.py`)
De 2.259 partidos del tablero fuera del motor de ligas (19-28 sep):
    FotMob ........................  40,8 % con modelo propio
    Flashscore, sólo página ....... 82,1 %
    Flashscore, temporada entera .. 84,7 %  (226 mil partidos, 437 competiciones)
Los 345 que faltan: 249 con un equipo de menos de 6 partidos (recién
ascendido de una categoría que el tablero no tiene, o un torneo sub-20 que
empieza: Taghit lleva 2 partidos en la Ligue 2 de Argelia) y 96 que no
aparecen en la página de resultados de su competición (aplazados o de otra
fase). Los primeros tendrán modelo en cuanto jueguen seis.

QUÉ GUARDA
`resultados_flashscore.csv.gz`: cada partido terminado de cada competición
del tablero, la temporada en curso y las dos anteriores. El precálculo lo
pone al día (una petición por competición con partidos próximos) y también
sirve para liquidar lo que FotMob no publica (`marcadores_del_dia`).

Uso: python resultados_flashscore.py     (añade las competiciones del tablero)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FICHERO = 'resultados_flashscore.csv.gz'
# LA BASE SE PARTE EN DOS para que el repositorio no crezca 7 MB en cada
# pasada del cron: `FICHERO` es el histórico (226 mil partidos, fijo) y el
# cron sólo reescribe `FICHERO_RECIENTE`, con lo que no está en el histórico.
FICHERO_RECIENTE = 'resultados_flashscore_reciente.csv.gz'
RUTAS = 'rutas_flashscore.json'
# las competiciones a las que ya se les pidieron las temporadas anteriores
# (tengan o no): así no se repite en cada pasada del cron
HISTORIA = 'historia_flashscore.json'
WEB = 'https://www.flashscore.com'
FEED_DIA = 'https://global.flashscore.ninja/2/x/feed/f_1_%d_3_es-mx_1'
CAB = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
       'x-fsign': 'SW9D1eZo', 'Referer': 'https://www.flashscore.com/'}
TEMPORADAS_ATRAS = 2
# hh/ha: el marcador al descanso. El feed NO lo da directo: BC/BD son los
# goles de la SEGUNDA mitad (comprobado con Liverpool 3-1 Southampton del
# 8-mar-2025, 0-1 al descanso: BC/BD = 3-0), así que descanso = final − BC/BD
COLUMNAS = ['match_id', 'ini', 'liga', 'ruta', 'home', 'away', 'gh', 'ga',
            'hh', 'ha']
INTERNACIONAL = {'africa', 'asia', 'europe', 'world', 'south-america',
                 'north-central-america', 'oceania'}


def _get(url: str, intentos: int = 3) -> Optional[str]:
    for i in range(intentos):
        try:
            r = requests.get(url, headers=CAB, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return r.text
        except Exception as e:
            logger.debug('[flashscore] %s: %s', url, e)
        time.sleep(1 + 2 * i)
    return None


def _registros(texto: str):
    """Los registros «~CLAVE÷valor¬…» del formato de Flashscore."""
    for reg in texto.split('~'):
        d = {}
        for c in reg.split('¬'):
            if '÷' in c:
                k, v = c.split('÷', 1)
                d.setdefault(k, v)
        if d:
            yield d


def _partidos(texto: str, liga: str, ruta: str) -> List[dict]:
    fuera, liga_actual = [], liga
    for d in _registros(texto):
        if 'ZA' in d:
            liga_actual = d['ZA'] if not liga else liga
            continue
        if 'AA' not in d or d.get('AB') != '3':          # 3 = terminado
            continue
        try:
            ini = dt.datetime.fromtimestamp(int(d['AD']), dt.timezone.utc)
            gh, ga = int(d['AG']), int(d['AH'])
        except Exception:
            continue
        try:
            hh, ha = gh - int(d['BC']), ga - int(d['BD'])
            if hh < 0 or ha < 0:
                hh = ha = None
        except Exception:
            hh = ha = None
        fuera.append({'match_id': d['AA'], 'ini': ini.strftime('%Y-%m-%d %H:%M:%S'),
                      'liga': liga_actual, 'ruta': ruta,
                      'home': d.get('AE'), 'away': d.get('AF'), 'gh': gh, 'ga': ga,
                      'hh': hh, 'ha': ha})
    return fuera


# ------------------------------------------------------------------- rutas
def rutas(dias: int = 7) -> Dict[str, str]:
    """{«PAÍS: Liga»: «/football/pais/liga/»} de los feeds diarios (±dias),
    unido con lo ya conocido."""
    try:
        conocidas = json.load(open(RUTAS, encoding='utf-8'))
    except Exception:
        conocidas = {}
    for off in range(-dias, dias + 1):
        t = _get(FEED_DIA % off)
        if not t:
            continue
        for d in _registros(t):
            if 'ZA' in d and d.get('ZL'):
                conocidas[d['ZA']] = d['ZL']
    try:
        json.dump(conocidas, open(RUTAS, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=0, sort_keys=True)
    except Exception:
        pass
    return conocidas


FEED_TEMPORADA = ('https://global.flashscore.ninja/2/x/feed/'
                  'tr_1_%s_%s_%s_%d_3_es-mx_1')


def paginas_siguientes(texto: str, maximo: int = 12) -> List[str]:
    """v316 — LA PÁGINA DE RESULTADOS SÓLO TRAE LOS ~100 MÁS RECIENTES de
    la temporada (Premier 2024-25: 127 de 380), y eso dejaba a 308 de los
    partidos del tablero sin modelo por «poca historia». El resto está en el
    feed paginado de la temporada (lo que pide el botón «mostrar más»), con
    los identificadores que vienen en la misma página: país, torneo y
    temporada. Medido en la Premier 2024-25: páginas 1-3 = los 380."""
    try:
        pais = re.search(r'country_id\s*[=:]\s*"?(\d+)', texto).group(1)
        torneo = re.search(r'tournament_id\s*[=:]\s*"([A-Za-z0-9]+)"', texto).group(1)
        temp = re.search(r'seasonId\s*:\s*(\d+)', texto).group(1)
        total = int(re.search(r'allEventsCount\s*:\s*(\d+)', texto).group(1))
    except Exception:
        return []
    if total <= 120:
        return []
    fuera = []
    for pg in range(1, maximo + 1):
        t = _get(FEED_TEMPORADA % (pais, torneo, temp, pg), intentos=2)
        if not t or 'AA÷' not in t:
            break
        fuera.append(t)
    return fuera


def _slug(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')


# las fases que el tablero añade al nombre y que no están en la dirección
_FASES = re.compile(r'\s+-\s+(apertura|clausura|play offs?|playoffs|'
                    r'championship group|relegation group|placement group|'
                    r'winners stage|losers stage|first stage|second stage|'
                    r'main|regular season|group [a-z0-9]+).*$', re.I)


def adivinar_ruta(liga: str) -> Optional[str]:
    """v316 — el feed del día sólo trae ~84 competiciones (medido: 65-84),
    así que muchas del tablero (la Premier, Dinamarca, Armenia…) se quedaban
    sin ruta. Se arma desde el nombre («ENGLAND: Premier League» →
    /football/england/premier-league/) y se acepta sólo si esa página tiene
    partidos terminados."""
    if ':' not in str(liga):
        return None
    pais, nombre = liga.split(':', 1)
    nombre = _FASES.sub('', nombre.strip())
    ruta = '/football/%s/%s/' % (_slug(pais), _slug(nombre))
    t = _get(WEB + ruta + 'results/', intentos=2)
    if t and any('AA' in d and d.get('AB') == '3' for d in _registros(t)):
        return ruta
    return None


def _temporadas_previas(ruta: str) -> List[str]:
    t = _get(WEB + ruta + 'archive/')
    if not t:
        return []
    slug = ruta.strip('/').split('/')[-1]
    base = '/'.join(ruta.strip('/').split('/')[:-1])
    # los enlaces vienen dentro de un JSON, con las barras escapadas
    # («\/football\/el-salvador\/primera-division-2024-2025\/»): se busca
    # sólo el nombre de la temporada
    halladas = sorted(set(re.findall(r'(?<![\w-])(%s-20\d\d(?:-20\d\d)?)(?![\w-])'
                                     % re.escape(slug), t)))
    return ['/%s/%s/' % (base, s) for s in halladas[-TEMPORADAS_ATRAS:]]


# -------------------------------------------------------------------- base
_MEM: Dict = {}


def cargar(recargar: bool = False) -> pd.DataFrame:
    if 'df' in _MEM and not recargar:
        return _MEM['df']
    partes = [pd.read_csv(f, parse_dates=['ini'])
              for f in (FICHERO, FICHERO_RECIENTE) if os.path.exists(f)]
    if partes:
        _MEM['ids_base'] = set(partes[0]['match_id']) if os.path.exists(FICHERO) else set()
        df = pd.concat(partes, ignore_index=True).drop_duplicates('match_id', keep='last')
    else:
        _MEM['ids_base'] = set()
        df = pd.DataFrame(columns=COLUMNAS)
        df['ini'] = pd.to_datetime(df['ini'])
    df = df.sort_values('ini').reset_index(drop=True)
    _MEM['df'] = df
    return df


def actualizar(ligas: Optional[List[str]] = None, historia: bool = True) -> int:
    """Pone al día la base con las competiciones `ligas` (por defecto, las del
    tablero de casas). Las que no estaban se traen con sus dos temporadas
    anteriores. Devuelve cuántos partidos nuevos. Nunca lanza."""
    try:
        df = cargar(recargar=True)
        if ligas is None:
            tab = json.load(open('cuotas_mx.json', encoding='utf-8')).get('partidos') or {}
            ligas = sorted({v.get('liga') for v in tab.values()
                            if v.get('deporte') == 'futbol' and v.get('liga')})
        rt = rutas()
        # a las que no se les pidieron todavía las temporadas anteriores,
        # se les piden una vez
        try:
            ya = set(json.load(open(HISTORIA, encoding='utf-8')))
        except Exception:
            ya = set()
        nuevas = []
        adivinadas = {}
        for liga in ligas:
            ruta = rt.get(liga)
            if not ruta:
                ruta = adivinar_ruta(liga)
                if ruta:
                    adivinadas[liga] = ruta
            if not ruta:
                logger.info('[flashscore] %s: sin ruta', liga)
                continue
            paginas = [ruta]
            completa = historia and ruta not in ya
            if completa:
                paginas += _temporadas_previas(ruta)
                ya.add(ruta)
            for p in paginas:
                t = _get(WEB + p + 'results/')
                if t:
                    nuevas += _partidos(t, liga if p == ruta else '', ruta)
                    # la primera vez, la temporada entera (no sólo lo reciente)
                    if completa:
                        for t2 in paginas_siguientes(t):
                            nuevas += _partidos(t2, liga if p == ruta else '', ruta)
        try:
            json.dump(sorted(ya), open(HISTORIA, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=0)
            if adivinadas:
                rt.update(adivinadas)
                json.dump(rt, open(RUTAS, 'w', encoding='utf-8'),
                          ensure_ascii=False, indent=0, sort_keys=True)
        except Exception:
            pass
        if not nuevas:
            return 0
        nd = pd.DataFrame(nuevas)
        # las temporadas anteriores llevan su nombre en el feed; se unifica
        # con el de la competición para que el modelo vea una sola liga
        nd.loc[nd['liga'] == '', 'liga'] = nd['ruta']
        nd['ini'] = pd.to_datetime(nd['ini'])
        antes = len(df)
        todo = pd.concat([df, nd], ignore_index=True) \
            .drop_duplicates('match_id', keep='last').sort_values('ini') \
            .reset_index(drop=True)
        for c in COLUMNAS:
            if c not in todo.columns:
                todo[c] = None
        ids_base = _MEM.get('ids_base') or set()
        destino, filas = ((FICHERO_RECIENTE, todo[~todo['match_id'].isin(ids_base)])
                          if ids_base else (FICHERO, todo))
        filas[COLUMNAS].to_csv(destino, index=False, compression='gzip',
                               date_format='%Y-%m-%d %H:%M:%S')
        _MEM['df'] = todo
        logger.info('[flashscore] base: %d partidos (+%d) de %d competiciones',
                    len(todo), len(todo) - antes, todo['ruta'].nunique())
        return len(todo) - antes
    except Exception as e:
        logger.warning('[flashscore] no se pudo actualizar: %s', e)
        return 0


def marcadores_del_dia(offset: int = -1) -> List[Dict]:
    """Los terminados de un día del feed (offset relativo a hoy), en la forma
    de `partidos_jugados.marcadores_fotmob`: sirve para liquidar lo que FotMob
    no publica. Nunca lanza."""
    try:
        import horario as hz
        t = _get(FEED_DIA % offset)
        if not t:
            return []
        return [{'ini': hz._a_utc(p['ini']), 'home': p['home'], 'away': p['away'],
                 'gh': float(p['gh']), 'ga': float(p['ga']), 'liga': p['liga'],
                 'id': 'fs:' + p['match_id']}
                for p in _partidos(t, '', '')]
    except Exception:
        return []


def clave_equipo(ruta: str, nombre: str) -> str:
    """Un equipo es su nombre dentro de su país («argentina|Platense 2»);
    en competiciones internacionales, su nombre a secas («Belgium U21»)."""
    partes = str(ruta or '').strip('/').split('/')
    pais = partes[1] if len(partes) > 1 else ''
    return str(nombre) if pais in INTERNACIONAL else '%s|%s' % (pais, nombre)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    print(actualizar())
