#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v192 — CINCO CASAS MEXICANAS POR UNA PUERTA ABIERTA.

DE DÓNDE SALE ESTO
------------------
El encargo era meter **Novibet**. Su propia API no se puede usar: devuelve 403
desde cualquier IP —hasta `robots.txt`— porque está detrás del desafío de
Cloudflare, y resolver una protección anti-bot no es algo que este proyecto
vaya a hacer. La v114 ya lo había sondeado y medido lo mismo.

Pero las cuotas de Novibet **sí están publicadas** en el comparador de
Flashscore, que responde 200 a una petición normal, sin navegador y sin
resolver nada. Es la misma categoría que el scraping de BetExplorer que el
proyecto ya hacía.

Y por esa puerta no entra una casa: entran **cinco, todas mexicanas**, que es
lo que de verdad importa —de nada sirve detectar valor en un precio que el
usuario no puede tomar—:

    Calientemx 631 · 1xBet 417 · Winpot 1113 · Novibet 632 · Sportium.mx 1041

El proyecto tenía tres casas (Pinnacle, Bovada, Playdoit). La dispersión entre
casas es la única señal que este proyecto mide como positiva, y con tres apenas
se ve.

COBERTURA MEDIDA (12 partidos por deporte, 1.040 peticiones, 2026-09-10)
-----------------------------------------------------------------------
                  Caliente  1xBet  Winpot  Novibet  Sportium
    futbol          10/12   10/12   10/12   10/12     9/12
    tenis           11/12   12/12   12/12   12/12    11/12
    baloncesto       4/12    9/12    4/12   10/12     0/12
    americano        3/4     0/4     0/4     0/4      3/4
    beisbol          1/12   11/12    0/12    0/12    11/12

Novibet es fuerte en fútbol, tenis y baloncesto —ahí es la mejor de las cinco—
y **no cotiza NFL ni MLB**. Esos los cubren Caliente, 1xBet y Sportium. Juntas
llegan a los cinco deportes.

POR QUÉ ESTO NO VA EN EL CAMINO CALIENTE
-----------------------------------------
Cada consulta cuesta 0,19 s y no hay límite de ritmo, pero un barrido completo
son ~4.500 peticiones: **catorce minutos**. Meterlo en el barrido que corre al
abrir la pantalla desharía la v178, que bajó la carga de 213 s a 39 s quitando
exactamente este tipo de petición de ahí.

Y no es una hipótesis: en esta misma tanda metí el tablero de Playdoit para los
16 partidos de la NFL, midió **+14,2 s por barrido** y dejó el smoke colgado 33
minutos. Se aprendió por las malas dos veces; no hace falta una tercera.

Así que `barrer()` corre en un trabajo de fondo y deja un fichero; la pantalla
sólo lo lee.
"""
import io
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

logger = logging.getLogger('cuotas_mx')

FEED = 'https://global.flashscore.ninja/2/x/feed/f_%d_%d_3_es-mx_1'
ODDS = 'https://global.ds.lsapp.eu/odds/pq_graphql'
CABEZ = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
         'Referer': 'https://www.flashscore.com.mx/',
         'x-fsign': 'SW9D1eZo'}

CASAS = {'Calientemx': 631, '1xBet': 417, 'Winpot': 1113,
         'Novibet': 632, 'Sportium.mx': 1041}

# el `sportId` de Flashscore -> la clave de deporte de este proyecto
DEPORTES = {1: 'futbol', 2: 'tenis', 3: 'nba', 5: 'nfl', 6: 'mlb'}

# Qué mercado pedir a cada deporte. Pedir los cuatro a todos multiplicaría por
# dos las peticiones para traer vacíos: el fútbol no tiene HOME_AWAY y el tenis
# no tiene empate.
MERCADOS = {
    'futbol': ('HOME_DRAW_AWAY', 'OVER_UNDER', 'ASIAN_HANDICAP'),
    'tenis': ('HOME_AWAY', 'OVER_UNDER', 'ASIAN_HANDICAP'),
    'nba': ('HOME_DRAW_AWAY', 'HOME_AWAY', 'OVER_UNDER', 'ASIAN_HANDICAP'),
    'nfl': ('HOME_AWAY', 'HOME_DRAW_AWAY', 'OVER_UNDER', 'ASIAN_HANDICAP'),
    'mlb': ('HOME_AWAY', 'HOME_DRAW_AWAY', 'OVER_UNDER', 'ASIAN_HANDICAP'),
}

FICHERO = 'cuotas_mx.json'
TIMEOUT = 20
PAUSA = 0.02
# Un fichero de más de este tiempo no se usa: son precios, y un precio de
# ayer no es un precio.
TTL_HORAS = 8


# ---------------------------------------------------------------------------
# el calendario
# ---------------------------------------------------------------------------
def eventos(sport_id: int, dias: int = 3, sesion=None) -> List[Dict]:
    """Los partidos que Flashscore publica para un deporte, con su id."""
    import requests
    ses = sesion or requests.Session()
    ses.headers.update(CABEZ)
    salida, vistos = [], set()
    for d in range(dias):
        try:
            t = ses.get(FEED % (sport_id, d), timeout=TIMEOUT).text
        except Exception as e:
            logger.debug('[mx] feed %s/%s: %s', sport_id, d, e)
            continue
        liga = ''
        for trozo in re.split(r'~ZA÷', t):
            cab = trozo.split('¬')[0]
            if cab and '÷' not in cab:
                liga = cab[:80]
            for x in trozo.split('~AA÷')[1:]:
                eid = x[:8]
                if eid in vistos:
                    continue
                campos = dict(re.findall(r'([A-Z]{2})÷([^¬]*)', '¬' + x))
                h, a = campos.get('AE'), campos.get('AF')
                if not h or not a:
                    continue
                vistos.add(eid)
                salida.append({'id': eid, 'home': h, 'away': a, 'liga': liga,
                               'inicio': campos.get('AD')})
    return salida


# ---------------------------------------------------------------------------
# las cuotas
# ---------------------------------------------------------------------------
def _valor(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if 1.001 <= v <= 1000.0 else None


def cuotas_evento(evento_id: str, casa_id: int, mercado: str,
                  sesion=None) -> Optional[Dict]:
    """Las cuotas de UNA casa para UN partido en UN mercado, o None."""
    import requests
    ses = sesion or requests.Session()
    ses.headers.update(CABEZ)
    try:
        r = ses.get(ODDS, params={'_hash': 'ope2', 'eventId': evento_id,
                                  'bookmakerId': casa_id, 'betType': mercado,
                                  'betScope': 'FULL_TIME'},
                    timeout=TIMEOUT).json()
    except Exception as e:
        logger.debug('[mx] %s/%s/%s: %s', evento_id, casa_id, mercado, e)
        return None
    d = (r.get('data') or {}).get('findPrematchOddsForBookmaker')
    if not isinstance(d, dict):
        return None

    salida = {'mercado': mercado}
    # 1X2 y ganador: home / draw / away
    for lado in ('home', 'draw', 'away'):
        it = d.get(lado)
        if isinstance(it, dict):
            v = _valor(it.get('value'))
            if v is not None:
                salida[lado] = v
                # LA APERTURA TAMBIEN, y no es un adorno: la diferencia entre
                # el precio de apertura y el actual es movimiento de linea, que
                # es de lo que se alimenta el CLV — la metrica rey del
                # proyecto. Ninguna de las otras tres casas la publica.
                ap = _valor(it.get('opening'))
                if ap is not None:
                    salida.setdefault('apertura', {})[lado] = ap
    # totales y hándicap: over / under con su línea
    for lado, clave in (('over', 'over'), ('under', 'under')):
        it = d.get(clave)
        if isinstance(it, dict):
            v = _valor(it.get('value'))
            if v is not None:
                salida[lado] = v
    for k in ('total', 'handicap', 'value'):
        if isinstance(d.get(k), (int, float, str)):
            try:
                salida['linea'] = float(d[k])
                break
            except (TypeError, ValueError):
                pass
    return salida if len(salida) > 1 else None


# ---------------------------------------------------------------------------
# el barrido de fondo
# ---------------------------------------------------------------------------
def barrer(dias: int = 3, max_por_deporte: int = 120,
           deportes: Optional[List[int]] = None) -> Dict:
    """
    Recorre los deportes y deja las cuotas en `cuotas_mx.json`.

    NO se llama desde la pantalla. Va en el workflow, como el resto de lo que
    cuesta segundos.
    """
    import requests
    ses = requests.Session()
    ses.headers.update(CABEZ)

    doc = {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'casas': CASAS, 'partidos': {}}
    t0 = time.time()
    n_pet = 0
    for sid in (deportes or list(DEPORTES)):
        dep = DEPORTES.get(sid)
        if not dep:
            continue
        evs = eventos(sid, dias=dias, sesion=ses)[:max_por_deporte]
        con = 0

        # EN PARALELO, porque en serie no escala. Medido en serie: 1.830
        # peticiones en 381 s para 104 partidos, o sea 3,7 s por partido. Un
        # barrido de verdad son ~500 partidos: media hora. Con hilos baja a
        # minutos y sigue sin ser el camino caliente.
        #
        # Ocho hilos y no mas: esto es cortesia, no una carrera. La medicion
        # dio 0,19 s por peticion sin ningun limite de ritmo, y no hace falta
        # averiguar donde esta el limite para que nos lo pongan.
        def _de_un_partido(ev):
            fila = {}
            hilo = requests.Session()
            hilo.headers.update(CABEZ)
            pedidas = 0
            for casa, bid in CASAS.items():
                por_mercado = {}
                for mk in MERCADOS.get(dep, ('HOME_DRAW_AWAY',)):
                    c = cuotas_evento(ev['id'], bid, mk, sesion=hilo)
                    pedidas += 1
                    if c:
                        por_mercado[mk] = c
                if por_mercado:
                    fila[casa] = por_mercado
            return ev, fila, pedidas

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            for ev, fila, pedidas in pool.map(_de_un_partido, evs):
                n_pet += pedidas
                if fila:
                    con += 1
                    doc['partidos'][ev['id']] = {
                        'deporte': dep, 'home': ev['home'], 'away': ev['away'],
                        'liga': ev['liga'], 'inicio': ev['inicio'],
                        'casas': fila}
        logger.info('[mx] %-10s %d partidos, %d con cuota', dep, len(evs), con)

    doc['segundos'] = round(time.time() - t0, 1)
    doc['peticiones'] = n_pet
    tmp = FICHERO + '.nuevo'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, FICHERO)
    return doc


# ---------------------------------------------------------------------------
# la lectura, que es lo que usa la pantalla
# ---------------------------------------------------------------------------
_MEM: Dict = {}


def cargar() -> Dict:
    """El fichero, o `{}` si no está o es viejo. Nunca lanza."""
    try:
        if not os.path.exists(FICHERO):
            return {}
        edad = (time.time() - os.path.getmtime(FICHERO)) / 3600.0
        if edad > TTL_HORAS:
            logger.info('[mx] %s tiene %.1f h: no se usa', FICHERO, edad)
            return {}
        marca = os.path.getmtime(FICHERO)
        if _MEM.get('marca') != marca:
            with io.open(FICHERO, encoding='utf-8') as f:
                _MEM['doc'] = json.load(f)
            _MEM['marca'] = marca
        return _MEM.get('doc') or {}
    except Exception as e:
        logger.debug('[mx] no se pudo leer %s: %s', FICHERO, e)
        return {}


def buscar(deporte: str, home: str, away: str) -> Dict:
    """
    Las cuotas de las cinco casas para un partido, o `{}`.

    El emparejamiento va por nombre dentro del MISMO deporte, con
    `name_mapper`, que es para lo que está: Flashscore escribe «UNAM Pumas» y
    el catálogo puede decir otra cosa. Fuera del deporte no se busca — ésa es
    la lección de la v180: un catálogo de todo empareja cualquier cosa.
    """
    doc = cargar()
    if not doc:
        return {}
    # EL INDICE SE CONSTRUYE UNA VEZ POR DEPORTE, NO EN CADA LLAMADA.
    #
    # Rehacerlo por partido costaba 0,034 s, que por los 260 partidos de
    # futbol de un barrido son **8,8 s** tirados en reconstruir la misma lista
    # de 1.900 nombres una y otra vez. Medido.
    #
    # Se ata a la marca de tiempo del fichero: cuando el barrido de fondo
    # escribe uno nuevo, el indice se rehace solo.
    clave_idx = ('idx', deporte, _MEM.get('marca'))
    if _MEM.get('clave_idx') != clave_idx:
        _idx = {}
        for k, v in (doc.get('partidos') or {}).items():
            if v.get('deporte') != deporte:
                continue
            _idx.setdefault(v.get('home', ''), []).append((k, v))
            _idx.setdefault(v.get('away', ''), []).append((k, v))
        _MEM['clave_idx'] = clave_idx
        _MEM['idx'] = _idx
        _MEM['catalogo'] = [x for x in _idx if x]
        # Y un indice por nombre NORMALIZADO. El emparejado difuso contra
        # 1.900 nombres cuesta 0,034 s por busqueda —8,7 s en un barrido de
        # futbol— y casi todas se resuelven antes: «UNAM Pumas» y «Pumas UNAM»
        # normalizan igual. Lo difuso queda para lo que de verdad no casa.
        _norm = {}
        try:
            import name_mapper as _nm
            for x in _MEM['catalogo']:
                _norm.setdefault(_nm.normalizar(x), x)
        except Exception:
            _norm = {}
        _MEM['norm'] = _norm
        # Y un indice por PALABRA. El emparejado difuso contra los 1.900
        # nombres del catalogo costaba 22,7 s en un barrido completo (medido:
        # 114,8 s con las casas mexicanas contra 92,1 s sin ellas). Casi todo
        # ese tiempo se va comparando «Pumas» con equipos de Kazajistan.
        #
        # Con este indice, lo difuso solo se prueba contra los que comparten
        # al menos una palabra: de 1.900 candidatos a una veintena.
        _pal = {}
        try:
            import name_mapper as _nm2
            for x in _MEM['catalogo']:
                for p in _nm2.normalizar(x).split():
                    if len(p) >= 3:
                        _pal.setdefault(p, []).append(x)
        except Exception:
            _pal = {}
        _MEM['palabras'] = _pal
    nombres = _MEM.get('idx') or {}
    catalogo = _MEM.get('catalogo') or []
    if not catalogo:
        return {}
    candidatos = [(k, v) for k, v in (doc.get('partidos') or {}).items()
                  if v.get('deporte') == deporte]
    try:
        import name_mapper
    except Exception:
        name_mapper = None

    def _mapea(n):
        if not n:
            return None
        if n in nombres:
            return n
        if name_mapper is not None:
            try:
                x = (_MEM.get('norm') or {}).get(name_mapper.normalizar(n))
                if x:
                    return x
            except Exception:
                pass
        if name_mapper is None:
            return None
        try:
            corto = []
            vistos = set()
            for p in name_mapper.normalizar(n).split():
                if len(p) < 3:
                    continue
                for x in (_MEM.get('palabras') or {}).get(p, ()):
                    if x not in vistos:
                        vistos.add(x)
                        corto.append(x)
            if not corto:
                return None
            return name_mapper.mapear(n, corto, umbral=0.80,
                                      contexto='cuotas_mx→%s' % deporte)
        except Exception:
            return None

    mh, ma = _mapea(home), _mapea(away)
    if not (mh and ma):
        return {}
    for k, v in candidatos:
        if v.get('home') == mh and v.get('away') == ma:
            return v
        if v.get('home') == ma and v.get('away') == mh:
            # el partido está al revés; se devuelve marcado para que quien
            # llame no confunda local con visitante
            return {**v, 'invertido': True}
    return {}


def main() -> int:
    import argparse
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dias', type=int, default=3)
    ap.add_argument('--max', type=int, default=120)
    a = ap.parse_args()

    d = barrer(dias=a.dias, max_por_deporte=a.max)
    print()
    print('partidos con cuota: %d' % len(d.get('partidos') or {}))
    print('peticiones: %d en %.1f s' % (d.get('peticiones', 0),
                                        d.get('segundos', 0)))
    por_casa = {}
    for v in (d.get('partidos') or {}).values():
        for casa in (v.get('casas') or {}):
            por_casa[casa] = por_casa.get(casa, 0) + 1
    for casa, n in sorted(por_casa.items(), key=lambda x: -x[1]):
        print('   %-14s %d partidos' % (casa, n))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
