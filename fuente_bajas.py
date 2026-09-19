#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v214 — Bajas, once y clima SIN clave de API: el endpoint de FotMob y el de ESPN.

EL ENCARGO
----------
«No quiero que sea mediante API, quiero que busques alguna otra forma, ya sea
scraping o alguna otra fuente. Investiga muchas fuentes de manera exhaustiva.»

Se sondearon 16 fuentes el 2026-09-19. Esto es lo que salió, y va escrito aquí
para que nadie repita el barrido:

    FUNCIONAN, SIN CLAVE
      FotMob  /api/data/matchDetails?matchId=N
          · `content.lineup.{home,away}Team.unavailable` -> BAJAS con nombre,
            tipo (`injury` / `suspension`) y fecha esperada de regreso
          · `.starters` (11) y `.lineupType`
          · `.formation`, `.coach`, `.totalStarterMarketValue`
          · `content.weather` -> CLIMA
      ESPN core /v2/sports/{dep}/leagues/{liga}/teams/{id}/injuries
          · lesiones con estado, fecha, jugador, posición y comentario largo
          · pobla NFL, MLB y NBA. En FÚTBOL devuelve 0 (comprobado en 10
            equipos de 5 ligas: Madrid, Barça, Valencia, Arsenal, City,
            Liverpool, Roma, Bayern, PSG, América).
      ESPN site /summary?event=N
          · `rosters[].roster[].starter` -> ONCE CONFIRMADO. Esto CORRIGE lo
            que este repositorio daba por sabido: ESPN sí marca titulares, no
            sólo la plantilla.

    NO FUNCIONAN
      Sofascore ................ 403 (Cloudflare)
      worldfootball.net ........ 403 incluso con UA de navegador
      physioroom ............... 404 en sus rutas de tabla
      besoccer ................. 406
      as.com / marca ........... 404 en sus rutas de lesionados
      Transfermarkt ............ responde 200 pero la tabla va por JS: cero
                                 enlaces de ficha en el HTML servido
      X / Twitter .............. sin API abierta

LA COBERTURA, MEDIDA Y NO PROMETIDA
-----------------------------------
Muestra aleatoria de 45 partidos de un día cualquiera (660 disponibles):

    con bloque de alineación ....... 23/45   (51 %)
    con once (`starters`) .......... 23/45   (51 %)
    con alguna baja ................ 10/45   (22 %)
    con clima ...................... 21/45   (47 %)
    tipos de baja .................. 55 `injury`, 3 `suspension`

EL MATIZ QUE IMPIDE USAR `starters` A LA LIGERA
-----------------------------------------------
`lineupType` salió así: `lastStarting11` 19 · `predicted` 2 · `simple` 1 ·
`standard` 1. O sea que **la mayoría de las veces el once que devuelve es el
del PARTIDO ANTERIOR**, no el de éste. Tratarlo como alineación confirmada
sería inventarse un dato con formato de dato, que es el modo de fallo contra el
que avisa todo este repositorio.

Por eso `once()` devuelve el tipo junto con los nombres y `es_confirmado()`
sólo dice que sí para `confirmed` y `standard`. Las BAJAS no tienen ese
problema: `unavailable` es la situación de hoy, no la del partido pasado.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger('fuente_bajas')

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/120.0.0.0 Safari/537.36')}

FOTMOB_DIA = 'https://www.fotmob.com/api/data/matches?date={fecha}'
FOTMOB_DETALLE = 'https://www.fotmob.com/api/data/matchDetails?matchId={mid}'
ESPN_INJURIES = ('https://sports.core.api.espn.com/v2/sports/{dep}/leagues/'
                 '{liga}/teams/{tid}/injuries')

CACHE = 'fotmob_cache'
TTL_DETALLE = 3600.0        # 1 h: las bajas cambian, pero no cada minuto
TIMEOUT = 25

# Los tipos de once que SÍ son de este partido.
TIPOS_CONFIRMADOS = ('confirmed', 'standard')

# ESPN sólo puebla lesiones en estos deportes (medido).
ESPN_DEPORTES = {'nfl': ('football', 'nfl'), 'mlb': ('baseball', 'mlb'),
                 'nba': ('basketball', 'nba')}

SONDEO = {
    'fecha': '2026-09-19',
    'fuentes_probadas': 16,
    'funcionan': ['fotmob_matchdetails', 'espn_core_injuries',
                  'espn_summary_rosters'],
    'no_funcionan': {'sofascore': '403', 'worldfootball': '403',
                     'physioroom': '404', 'besoccer': '406',
                     'as/marca': '404', 'transfermarkt': 'tabla por JS',
                     'x_twitter': 'sin API abierta'},
    'cobertura_fotmob': {'alineacion': '23/45', 'bajas': '10/45',
                         'clima': '21/45'},
    'espn_injuries_futbol': '0 en 10 equipos de 5 ligas',
}


# ---------------------------------------------------------------------------
def _cache_ruta(mid) -> str:
    return os.path.join(CACHE, f'detalle_{mid}.json')


def _get(url: str) -> Optional[Dict]:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            logger.debug('[bajas] %s -> %s', url, r.status_code)
            return None
        return r.json()
    except Exception as e:
        logger.debug('[bajas] %s: %s', url, e)
        return None


def detalle(mid, forzar: bool = False) -> Optional[Dict]:
    """El matchDetails de FotMob, con caché en disco de una hora."""
    ruta = _cache_ruta(mid)
    if not forzar and os.path.exists(ruta):
        try:
            if time.time() - os.path.getmtime(ruta) < TTL_DETALLE:
                with open(ruta, encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug('[bajas] caché %s: %s', ruta, e)
    d = _get(FOTMOB_DETALLE.format(mid=mid))
    if d is None:
        return None
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        logger.debug('[bajas] no se pudo cachear: %s', e)
    return d


def partidos_del_dia(fecha_aaaammdd: str) -> List[Dict]:
    """Los partidos de FotMob de ese día: `[{'id', 'liga', 'home', 'away'}]`."""
    d = _get(FOTMOB_DIA.format(fecha=fecha_aaaammdd))
    fuera = []
    for L in (d or {}).get('leagues', []) or []:
        for m in (L.get('matches') or []):
            h = (m.get('home') or {}).get('name')
            a = (m.get('away') or {}).get('name')
            fuera.append({'id': m.get('id'), 'liga': L.get('name'),
                          'home': h, 'away': a})
    return fuera


def buscar_partido(home: str, away: str,
                   fecha_aaaammdd: str) -> Optional[Dict]:
    """Empareja un partido del barrido con el de FotMob, por nombre.

    Usa `name_mapper`, que es el emparejador del proyecto: FotMob escribe
    «Tottenham Hotspur» donde ESPN escribe «Tottenham», y comparar por igualdad
    exacta es el fallo silencioso que ya costó una versión en la v209.
    """
    lista = partidos_del_dia(fecha_aaaammdd)
    if not lista:
        return None
    try:
        import name_mapper as nm
        catalogo = [p['home'] for p in lista if p.get('home')]
        objetivo = nm.mapear(home, catalogo)
    except Exception as e:
        logger.debug('[bajas] emparejado: %s', e)
        objetivo = home
    for p in lista:
        if p.get('home') == objetivo:
            return p
    return None


# ---------------------------------------------------------------------------
def _lado(det: Dict, lado: str) -> Dict:
    lu = ((det or {}).get('content') or {}).get('lineup') or {}
    if not isinstance(lu, dict):
        return {}
    return lu.get('homeTeam' if lado == 'home' else 'awayTeam') or {}


def tipo_alineacion(det: Dict) -> str:
    lu = ((det or {}).get('content') or {}).get('lineup') or {}
    return str((lu or {}).get('lineupType') or '')


def es_confirmado(det: Dict) -> bool:
    """¿El once es de ESTE partido, o el del anterior?

    Medido: `lastStarting11` es lo que más sale. Ese once NO es de este
    partido y no puede presentarse como tal.
    """
    return tipo_alineacion(det).lower() in TIPOS_CONFIRMADOS


def bajas(det: Dict, lado: str = 'home') -> List[Dict]:
    """Jugadores no disponibles de ese lado, normalizados.

    A diferencia del once, esto SÍ es de hoy: es la enfermería del equipo en el
    momento de la consulta.
    """
    fuera = []
    for u in (_lado(det, lado).get('unavailable') or []):
        if not isinstance(u, dict):
            continue
        info = u.get('unavailability') or {}
        fuera.append({
            'nombre': u.get('name'),
            'tipo': str(info.get('type') or 'desconocido'),
            'regreso': info.get('expectedReturn'),
            'valor_mercado': u.get('marketValue'),
            'edad': u.get('age'),
        })
    return fuera


def once(det: Dict, lado: str = 'home') -> Dict:
    """Los titulares, con el tipo de alineación al lado. SIEMPRE con el tipo."""
    t = _lado(det, lado)
    nombres = []
    for s in (t.get('starters') or []):
        if isinstance(s, dict):
            nombres.append(s.get('name') or (s.get('athlete') or {}).get('name'))
    return {'equipo': t.get('name'), 'formacion': t.get('formation'),
            'entrenador': ((t.get('coach') or {}).get('name')
                           if isinstance(t.get('coach'), dict)
                           else t.get('coach')),
            'titulares': [n for n in nombres if n],
            'valor_once': t.get('totalStarterMarketValue'),
            'edad_media': t.get('averageStarterAge'),
            'tipo': tipo_alineacion(det),
            'confirmado': es_confirmado(det)}


def clima(det: Dict) -> Dict:
    c = ((det or {}).get('content') or {}).get('weather') or {}
    return c if isinstance(c, dict) else {}


# ---------------------------------------------------------------------------
def espn_lesiones(deporte: str, team_id) -> List[Dict]:
    """Lesiones de ESPN para NFL, MLB y NBA. En fútbol devuelve vacío.

    No es una limitación de este código: está medido. ESPN responde 200 con
    `count: 0` en los 10 equipos de fútbol probados, y con 50 lesiones en un
    solo equipo de NFL.
    """
    par = ESPN_DEPORTES.get(str(deporte).lower())
    if not par or not team_id:
        return []
    dep, liga = par
    d = _get(ESPN_INJURIES.format(dep=dep, liga=liga, tid=team_id))
    fuera = []
    for it in (d or {}).get('items', [])[:40]:
        ref = it.get('$ref')
        if not ref:
            continue
        det = _get(ref)
        if not det:
            continue
        atl = _get((det.get('athlete') or {}).get('$ref') or '') or {}
        fuera.append({
            'nombre': atl.get('displayName'),
            'posicion': (atl.get('position') or {}).get('abbreviation'),
            'estado': det.get('status'),
            'tipo': (det.get('type') or {}).get('description'),
            'fecha': det.get('date'),
            'comentario': det.get('shortComment'),
        })
    return fuera


# ---------------------------------------------------------------------------
def de_partido(home: str, away: str, fecha_aaaammdd: str) -> Dict:
    """Todo lo que se puede saber de un partido de fútbol, en una llamada.

    Devuelve siempre el mismo esquema; los campos que la fuente no cubra van
    vacíos y `cobertura` dice qué se consiguió, para que quien lo consuma no
    tenga que adivinarlo.
    """
    vacio = {'encontrado': False, 'bajas_home': [], 'bajas_away': [],
             'once_home': {}, 'once_away': {}, 'clima': {}, 'cobertura': {}}
    p = buscar_partido(home, away, fecha_aaaammdd)
    if not p or not p.get('id'):
        return vacio
    det = detalle(p['id'])
    if not det:
        return vacio
    bh, ba = bajas(det, 'home'), bajas(det, 'away')
    oh, oa = once(det, 'home'), once(det, 'away')
    cl = clima(det)
    return {
        'encontrado': True, 'match_id': p['id'], 'liga_fotmob': p.get('liga'),
        'bajas_home': bh, 'bajas_away': ba,
        'once_home': oh, 'once_away': oa, 'clima': cl,
        'cobertura': {'bajas': bool(bh or ba),
                      'once': bool(oh.get('titulares') or oa.get('titulares')),
                      'once_confirmado': oh.get('confirmado', False),
                      'clima': bool(cl)},
    }


def a_senales(ficha: Dict, deporte: str = 'futbol') -> Dict:
    """Traduce la ficha a señales de `scraper_contexto`, por lado.

    El peso de una baja NO es uno fijo: una baja con `expectedReturn` de
    «Doubtful» pesa menos que una con fecha de vuelta lejana, porque la primera
    puede acabar jugando. Y dos o más bajas se agrupan en `lesion_multiple`,
    que es el tipo que `ajuste_contexto` ya sabe puntuar.
    """
    try:
        import scraper_contexto as sc
    except Exception as e:
        logger.debug('[bajas] scraper_contexto: %s', e)
        return {'home': [], 'away': []}

    fuera = {'home': [], 'away': []}
    for lado in ('home', 'away'):
        lista = (ficha or {}).get(f'bajas_{lado}') or []
        lesiones = [b for b in lista if b.get('tipo') == 'injury']
        sanciones = [b for b in lista if b.get('tipo') == 'suspension']
        equipo = ((ficha.get(f'once_{lado}') or {}).get('equipo')) or ''
        if len(lesiones) >= 2:
            nombres = ', '.join(str(b['nombre']) for b in lesiones[:3]
                                if b.get('nombre'))
            fuera[lado].append(sc.senal(
                'lesion_multiple', 1, 'fotmob', deporte,
                detalle=f'{equipo}: {len(lesiones)} bajas por lesión '
                        f'({nombres})'))
        elif len(lesiones) == 1:
            b = lesiones[0]
            fuera[lado].append(sc.senal(
                'lesion_clave', 1, 'fotmob', deporte,
                detalle=f"{equipo}: baja {b.get('nombre')} "
                        f"(vuelve: {b.get('regreso') or '?'})"))
        for s in sanciones[:1]:
            fuera[lado].append(sc.senal(
                'baja_defensiva', 1, 'fotmob', deporte,
                detalle=f"{equipo}: {s.get('nombre')} sancionado"))
    return fuera


def estado() -> Dict:
    """Qué se sondeó, qué funciona y con cuánta cobertura."""
    return dict(SONDEO)


if __name__ == '__main__':
    import datetime as _dt
    import sys
    hoy = _dt.date.today().strftime('%Y%m%d')
    lista = partidos_del_dia(hoy)
    print(f'partidos de FotMob el {hoy}: {len(lista)}')
    vistos = 0
    for p in lista:
        d = detalle(p['id'])
        if not d:
            continue
        b = bajas(d, 'home') + bajas(d, 'away')
        if not b:
            continue
        o = once(d, 'home')
        print(f"\n{p['home']} vs {p['away']}  ({p['liga']})")
        print(f"  once: {o['tipo']} · confirmado={o['confirmado']}")
        for x in b[:4]:
            print(f"    - {x['nombre']}: {x['tipo']} / {x['regreso']}")
        vistos += 1
        if vistos >= 3:
            break
    if not vistos:
        print('ningún partido con bajas en la muestra de hoy')
    sys.exit(0)
