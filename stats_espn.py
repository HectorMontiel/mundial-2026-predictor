#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v162 — LAS ESTADÍSTICAS REALES DE ESPN, PARA TODAS LAS COMPETICIONES.

El problema que resuelve
------------------------
Hasta aquí, córners, tarjetas, remates y posesión eran OBSERVADOS en 20 de las
75 competiciones —las de formato 'main' de football-data— y en las otras 55 los
escribía `CorrelatedSyntheticGenerator`. La bitácora lo dice desde la v152: esas
columnas son una función afín de los goles con ruido encima, así que no se
entrena sobre ellas ni se enseñan.

Eso dejaba la Liga MX, Argentina, Brasil, la MLS, Colombia, Chile, Perú, Japón
y treinta y tantas más sin córners ni tarjetas. Y no por falta de datos: **el
`summary` de ESPN trae un `boxscore` que nadie de este proyecto había mirado**.

QUÉ TRAE, MEDIDO
----------------
28 estadísticas por equipo y partido, entre ellas las que hacían falta:

    wonCorners · yellowCards · redCards · foulsCommitted · possessionPct
    totalShots · shotsOnTarget · offsides · saves · totalPasses · passPct
    accurateCrosses · interceptions · totalTackles · effectiveClearance …

Sondeadas 34 competiciones el 2026-08-22: **23 las traen** (las 11 restantes no
tenían partidos jugados en la ventana de prueba o su boxscore venía vacío).
Entre las que sí: Liga MX, Argentina, Brasil, MLS, Colombia, Chile, Perú,
Japón, China, Suecia, Noruega, Dinamarca, Rusia, Sudáfrica, USL, Austria…

Y NO ES OTRO RELLENO: SE CRUZÓ CONTRA FOOTBALL-DATA
---------------------------------------------------
216 partidos de 6 competiciones grandes, los mismos en las dos fuentes:

    variable            n     idénticos   media ESPN   media FD    corr
    córners local     216       93,1 %       5,76        5,74     0,985
    córners visitante 216       96,3 %       4,34        4,33     0,981
    amarillas local   216       95,4 %       1,71        1,76     0,955
    amarillas visit.  216       94,4 %       1,72        1,78     0,957
    rojas local       216      100,0 %       0,07        0,07     1,000
    remates local     216       95,4 %      14,80       14,73     0,988

Los desacuerdos son de ±1 —criterio de conteo— y dos de ellos son un
emparejado mío mal hecho, no un dato malo. Con correlaciones de 0,98 y medias
que coinciden en la segunda cifra, ESPN es fuente observada, no estimación.

HASTA DÓNDE LLEGA
-----------------
Depende de la competición (muestreando tres partidos por año):

    Liga MX, Colombia .......  desde 2018
    MLS, Argentina, Brasil ..  desde 2018-2020 (con huecos de temporada)
    Japón, Suecia, Perú .....  desde 2025

O sea que unas tienen ocho temporadas y otras dos. Dos bastan para el
estimador que usa este proyecto (ventana de 10 partidos por equipo), pero no
para todo, y por eso el informe de calibración va por competición.

CUÁNTO CUESTA
-------------
Medido: **0,05 s por partido con 8 hilos** (0,18 s con uno). Una temporada de
380 partidos son ~20 s. Es dos órdenes de magnitud más barato que FotMob, que
tarda ~1,7 s por partido.

POR QUÉ UNA CACHÉ PROPIA Y NO UN PARCHE AL HISTÓRICO
-----------------------------------------------------
Porque el parche no sobreviviría a la noche. `descargar_liga` **reconstruye**
el histórico entero desde su fuente en cada reentrenamiento: football-data para
'main' y 'new', `uefa_scraper` para 'espn'. Escribir los córners reales en
`historico_liga_mx.csv` los borraría el siguiente `--build`.

Así que las estadísticas viven aquí, en `stats_espn/<liga>.csv.gz`, y se
INYECTAN en el marco durante la descarga, **antes** de que corra el generador
sintético. Eso encaja sin tocar nada más porque el generador ya promete que
«sólo rellena valores faltantes: si una columna ya trae datos reales, esos se
respetan» — y lo cumple.

El efecto secundario es el que se quería: `rendimiento_equipos.stats_disponibles`
decide si una columna es sintética REPRODUCIÉNDOLA con el generador. En cuanto
llegan los valores de ESPN, la reproducción falla y la columna pasa a contar
como observada. No hay que tocar esa función ni mantener una lista.
"""
import argparse
import json
import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger('stats_espn')

DIRECTORIO = 'stats_espn'
BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{code}'
# «Mozilla/5.0» A SECAS, Y NO ES PEREZA. La cadena completa de Chrome
# —'Mozilla/5.0 (Windows NT 10.0…) Chrome/126…'— devuelve **Access Denied** en
# site.api.espn.com. Medido: con la cadena larga, HTTP 403 con página de error;
# con ésta, 200 y 485 KB de JSON. Es la misma que usa `fixtures_espn` en sus
# cinco llamadas desde hace versiones, así que aquí se repite en vez de
# «mejorarla».
UA = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 25
HILOS = 8

# El nombre de ESPN -> la columna del histórico. `totalShots` no está aquí
# porque el histórico guarda remates DENTRO y FUERA por separado, y el de fuera
# se deriva restando (ver `_fila_de_evento`).
MAPA = {
    'wonCorners': 'corners',
    'yellowCards': 'yellow',
    'redCards': 'red',
    'shotsOnTarget': 'shots_on',
    'foulsCommitted': 'fouls',
    'possessionPct': 'possession',
    'offsides': 'offsides',
}
# Las columnas que se escriben en la caché, por bando.
DERIVADAS = ('corners', 'yellow', 'red', 'shots_on', 'shots_off', 'fouls',
             'possession', 'offsides')
COLUMNAS = (['fecha', 'home', 'away', 'event_id']
            + ['%s_%s' % (b, c) for c in DERIVADAS for b in ('home', 'away')])


# ---------------------------------------------------------------------------
# red
# ---------------------------------------------------------------------------
def _get(url: str, intentos: int = 2) -> Optional[Dict]:
    for i in range(intentos):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception as e:
            logger.debug('[stats_espn] %s: %s: %s', url, type(e).__name__, e)
        if i + 1 < intentos:
            time.sleep(0.8)
    return None


def _eventos(code: str, desde: str, hasta: str) -> List[Dict]:
    """Los partidos JUGADOS de un rango. Una petición por rango."""
    d = _get(BASE.format(code=code) + '/scoreboard?dates=%s-%s&limit=500'
             % (str(desde).replace('-', ''), str(hasta).replace('-', '')))
    if not d:
        return []
    salida = []
    for ev in (d.get('events') or []):
        st = ((ev.get('status') or {}).get('type') or {})
        if not st.get('completed'):
            continue
        try:
            comp = ev['competitions'][0]
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
        except (KeyError, IndexError, StopIteration):
            continue
        fecha = pd.to_datetime(ev.get('date'), errors='coerce')
        if fecha is None or pd.isna(fecha):
            continue
        if getattr(fecha, 'tzinfo', None):
            fecha = fecha.tz_convert(None)
        salida.append({'event_id': str(ev.get('id')),
                       'fecha': fecha.strftime('%Y-%m-%d'),
                       'home': loc['team']['displayName'],
                       'away': vis['team']['displayName']})
    return salida


def _fila_de_evento(code: str, ev: Dict) -> Optional[Dict]:
    """El boxscore de un partido, ya en columnas del histórico."""
    d = _get(BASE.format(code=code) + '/summary?event=%s' % ev['event_id'])
    if not d:
        return None
    equipos = ((d.get('boxscore') or {}).get('teams') or [])
    if len(equipos) < 2:
        return None
    fila = dict(ev)
    visto = False
    for t in equipos:
        lado = str(t.get('homeAway') or '').lower()
        if lado not in ('home', 'away'):
            continue
        crudo = {}
        for st in (t.get('statistics') or []):
            n = st.get('name')
            if n not in MAPA and n != 'totalShots':
                continue
            try:
                crudo[n] = float(str(st.get('displayValue')).replace('%', ''))
            except (TypeError, ValueError):
                continue
        if not crudo:
            continue
        visto = True
        for n, col in MAPA.items():
            if n in crudo:
                fila['%s_%s' % (lado, col)] = crudo[n]
        # remates FUERA = totales − a puerta. Si falta cualquiera de los dos no
        # se escribe un total a medias: la columna se queda vacía y el
        # generador la rellenará, que es peor pero honesto.
        tot, den = crudo.get('totalShots'), crudo.get('shotsOnTarget')
        if tot is not None and den is not None:
            fila['%s_shots_off' % lado] = max(tot - den, 0.0)
    if not visto:
        return None
    # UN BOXSCORE A CEROS NO ES UN PARTIDO SIN CÓRNERS: ES UN PARTIDO SIN
    # DATOS, Y ESPN LO PUBLICA IGUAL.
    #
    # Medido en la Liga MX: el 7,0 % de los partidos volvían con posesión 0-0,
    # faltas 0, córners 0 y remates 0 — todo a cero a la vez, que es imposible.
    # Colados como datos buenos hundían la media y disparaban la dispersión
    # (var/media de los córners por equipo salía 2,04 con ellos dentro).
    #
    # La posesión es el detector limpio: la suma de las dos SIEMPRE ronda 100
    # en un partido de verdad —1.777 de 1.911 caen entre 95 y 105— y vale 0
    # exactamente cuando el boxscore viene vacío. Se descarta la fila entera,
    # no sólo la posesión, porque lo que falta es el boxscore completo.
    ph = fila.get('home_possession')
    pa = fila.get('away_possession')
    if (ph or 0) + (pa or 0) <= 1.0:
        return None
    return fila


# ---------------------------------------------------------------------------
# caché en disco
# ---------------------------------------------------------------------------
def ruta(clave: str) -> str:
    return os.path.join(DIRECTORIO, '%s.csv.gz' % clave)


def leer(clave: str) -> pd.DataFrame:
    """Lo que ya está descargado de esta competición. Vacío si no hay nada."""
    r = ruta(clave)
    if not os.path.exists(r):
        return pd.DataFrame(columns=COLUMNAS)
    try:
        d = pd.read_csv(r, compression='gzip', low_memory=False)
        for c in COLUMNAS:
            if c not in d.columns:
                d[c] = np.nan
        return d
    except Exception as e:
        logger.warning('[stats_espn] %s ilegible: %s', r, e)
        return pd.DataFrame(columns=COLUMNAS)


def _guardar(clave: str, d: pd.DataFrame) -> None:
    os.makedirs(DIRECTORIO, exist_ok=True)
    d = d.drop_duplicates(subset=['event_id'], keep='last')
    d = d.sort_values('fecha').reset_index(drop=True)
    d.to_csv(ruta(clave), index=False, compression='gzip')


def backfill(clave: str, desde: str, hasta: str, hilos: int = HILOS,
             forzar: bool = False) -> Dict:
    """
    Descarga las estadísticas de `clave` entre dos fechas y las acumula.

    Va mes a mes porque el scoreboard de ESPN corta los rangos largos, y salta
    los partidos que ya están en la caché: llamarlo a diario cuesta lo que
    cuesten los partidos nuevos, no la temporada entera.
    """
    from concurrent.futures import ThreadPoolExecutor
    import fixtures_espn

    code = fixtures_espn.ESPN_CODIGOS.get(clave)
    if not code:
        return {'clave': clave, 'error': 'sin código ESPN'}

    previo = leer(clave)
    ya = set(previo['event_id'].astype(str)) if len(previo) else set()

    # LOS RANGOS TAMBIÉN EN PARALELO, Y NO ES UN CAPRICHO. Un backfill de cinco
    # temporadas son ~60 rangos mensuales por competición; en serie, a ~0,3 s
    # cada uno, son 20 s de espera por liga ANTES de bajar un solo boxscore —
    # más de una hora sumando las 61. El cuello no es la CPU, es la latencia.
    meses = pd.date_range(pd.Timestamp(desde), pd.Timestamp(hasta), freq='MS')
    if len(meses) == 0:
        meses = pd.DatetimeIndex([pd.Timestamp(desde)])
    # LOS MESES QUE YA ESTÁN NO SE VUELVEN A PREGUNTAR.
    #
    # `backfill` saltaba los `event_id` conocidos, pero sólo DESPUÉS de pedir
    # el scoreboard de los ~60 rangos mensuales. En una segunda pasada eso son
    # 60 peticiones por competición para descubrir que no hay nada nuevo —
    # medido: 96 a 140 s por liga sin bajar una sola fila, o sea más de dos
    # horas para las 61. El paso semanal del bot habría costado eso cada lunes.
    #
    # Un mes con partidos ya guardados no puede traer más: las competiciones no
    # añaden jornadas al pasado. Los DOS ÚLTIMOS meses sí se vuelven a pedir
    # siempre, porque ahí es donde aparecen los partidos nuevos y donde ESPN
    # rellena el boxscore de uno que acabó sin él.
    ya_por_mes = set()
    if len(previo) and not forzar:
        _f = pd.to_datetime(previo['fecha'], errors='coerce')
        ya_por_mes = set(_f.dt.strftime('%Y-%m').dropna())
    frontera = (pd.Timestamp(hasta) - pd.offsets.MonthBegin(2)) \
        if hasta else pd.Timestamp.min
    rangos = []
    saltados = 0
    for ini in meses:
        if (ini.strftime('%Y-%m') in ya_por_mes and ini < frontera):
            saltados += 1
            continue
        rangos.append((ini.strftime('%Y-%m-%d'),
                       (ini + pd.offsets.MonthEnd(1)).strftime('%Y-%m-%d')))
    if saltados:
        logger.info('[stats_espn] %s: %d meses ya cubiertos, se piden %d',
                    clave, saltados, len(rangos))
    pendientes: List[Dict] = []
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for lote in ex.map(lambda r: _eventos(code, r[0], r[1]), rangos):
            for ev in (lote or []):
                if forzar or ev['event_id'] not in ya:
                    pendientes.append(ev)

    # un mismo partido puede salir en dos rangos si cae en el borde
    vistos, unicos = set(), []
    for ev in pendientes:
        if ev['event_id'] in vistos:
            continue
        vistos.add(ev['event_id'])
        unicos.append(ev)

    t0 = time.time()
    filas = []
    if unicos:
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            for f in ex.map(lambda e: _fila_de_evento(code, e), unicos):
                if f:
                    filas.append(f)

    nuevas = pd.DataFrame(filas)
    if len(nuevas):
        for c in COLUMNAS:
            if c not in nuevas.columns:
                nuevas[c] = np.nan
        nuevas = nuevas[COLUMNAS]
        total = pd.concat([previo[COLUMNAS], nuevas], ignore_index=True)
        _guardar(clave, total)
    else:
        total = previo

    return {'clave': clave, 'candidatos': len(unicos), 'nuevas': len(filas),
            'acumulado': len(total),
            'con_corners': int(total['home_corners'].notna().sum()) if len(total) else 0,
            'segundos': round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# inyección en el histórico
# ---------------------------------------------------------------------------
_CACHE_MAPEO: Dict[str, Dict] = {}


def _normaliza(nombre) -> str:
    try:
        import name_mapper
        return name_mapper.normalizar(str(nombre or ''))
    except Exception:
        return str(nombre or '').strip().lower()


def _traductor(nombres_espn, catalogo) -> Dict[str, str]:
    """
    De cada nombre de ESPN al nombre del histórico, con `name_mapper`.

    NO VALE NORMALIZAR Y COMPARAR, Y ESTÁ MEDIDO. La primera versión de esta
    función comparaba `normalizar(a) == normalizar(b)` y casó **62 de 207**
    partidos de la Liga MX: el histórico dice «Club Tijuana», «Club America»,
    «Guadalajara Chivas», «Mazatlan FC», «Club Leon», y ESPN dice «Tijuana»,
    «América», «Guadalajara», «Mazatlán FC», «León». Son los mismos clubes con
    otro rótulo, que es exactamente el problema para el que existe
    `name_mapper.mapear` —con sus alias, sus abreviaturas y su regla de
    contención— y que este módulo se estaba saltando.

    Lo peor de aquel fallo no era perder 145 partidos: era que **no se notaba**.
    Los que no casaban se rellenaban con el generador sintético y salían con
    aspecto de córners normales.
    """
    try:
        import name_mapper
    except Exception:
        return {}
    catalogo = list(catalogo)
    salida = {}
    for n in nombres_espn:
        if n in salida:
            continue
        m = name_mapper.mapear(str(n), catalogo, contexto='stats_espn')
        if m:
            salida[str(n)] = m
    return salida


def inyectar(df: pd.DataFrame, clave: str) -> pd.DataFrame:
    """
    Mete en `df` las estadísticas reales que haya para esos partidos.

    Se llama desde `league_engine.descargar_liga` ANTES del generador
    sintético, así que lo que entra aquí se queda: el generador sólo rellena
    huecos.

    El emparejado es por (día, local, visitante) traduciendo los nombres de
    ESPN al catálogo del histórico con `name_mapper` (ver `_traductor`), y con
    una ventana de un día por cada lado porque ESPN publica en UTC y algunos
    históricos guardan la fecha local. **Si un partido no casa, no se fuerza**:
    se queda sin estadísticas reales y el generador lo rellena. Meter los
    córners del partido equivocado sería mucho peor que no meter ninguno.
    """
    if df is None or getattr(df, 'empty', True):
        return df
    cache = leer(clave)
    if not len(cache):
        return df

    d = df.copy()
    fechas = pd.to_datetime(d['date'], errors='coerce')
    kh = d['home_team'].astype(str)
    ka = d['away_team'].astype(str)

    catalogo = sorted(set(kh) | set(ka))
    cache = cache.copy()
    trad = _traductor(
        set(cache['home'].astype(str)) | set(cache['away'].astype(str)),
        catalogo)
    cache['_f'] = pd.to_datetime(cache['fecha'], errors='coerce')
    cache['_h'] = cache['home'].astype(str).map(lambda x: trad.get(x))
    cache['_a'] = cache['away'].astype(str).map(lambda x: trad.get(x))
    cache = cache[cache['_h'].notna() & cache['_a'].notna()]
    if not len(cache):
        return df

    # índice por (equipos) -> lista de (fecha, fila); se resuelve por cercanía
    # de fecha, que es lo que absorbe el desfase de huso.
    indice: Dict[tuple, List] = {}
    for i, r in cache.iterrows():
        indice.setdefault((r['_h'], r['_a']), []).append((r['_f'], i))

    cols = ['%s_%s' % (b, c) for c in DERIVADAS for b in ('home', 'away')]
    for c in cols:
        if c not in d.columns:
            d[c] = np.nan
    # QUÉ FILAS SON REALES, ANOTADO EN EL PROPIO FICHERO.
    #
    # Sin esto, una competición con estadísticas de ESPN desde 2021 y relleno
    # sintético desde 2018 queda con la columna MEZCLADA, y cualquier media o
    # dispersión calculada sobre ella sale mal. Medido en la Liga MX: la razón
    # varianza/media de los córners por equipo daba 1,92 mezclando, cuando las
    # competiciones con datos limpios van a 1,5-1,7.
    #
    # Se marca la fila entera y no cada columna porque el boxscore de ESPN
    # llega completo o no llega: si hay `wonCorners` hay también tarjetas,
    # faltas y posesión del mismo partido.
    # `object` y no `np.nan`: pandas 3 crea la columna como float64 si se
    # inicializa con NaN y luego RECHAZA escribir 'espn' dentro
    # («Invalid value 'espn' for dtype 'float64'»). El `except` de
    # `league_engine` se tragaba esa excepción y la liga se quedaba sin
    # estadísticas sin más aviso que una línea de log.
    if 'stats_origen' not in d.columns:
        d['stats_origen'] = pd.Series([None] * len(d), dtype='object',
                                      index=d.index)
    else:
        d['stats_origen'] = d['stats_origen'].astype('object')

    puestos = 0
    for pos in range(len(d)):
        cand = indice.get((kh.iat[pos], ka.iat[pos]))
        if not cand:
            continue
        f = fechas.iat[pos]
        if pd.isna(f):
            continue
        mejor, dist = None, None
        for fc, i in cand:
            if pd.isna(fc):
                continue
            dd = abs((fc - f).days)
            if dd <= 1 and (dist is None or dd < dist):
                mejor, dist = i, dd
        if mejor is None:
            continue
        fila = cache.loc[mejor]
        algo = False
        for c in cols:
            v = fila.get(c)
            if v is None or pd.isna(v):
                continue
            # SÓLO SE RELLENAN HUECOS. La primera versión escribía siempre, y
            # eso PISABA los córners y las tarjetas de football-data en las 20
            # competiciones que ya los traían.
            #
            # No era inocuo aunque las dos fuentes coincidan en el 93-96 % de
            # los partidos: football-data es la fuente establecida de esas
            # ligas, con cobertura del 100 %, y cambiarle los números por
            # detrás movería medidas que ya están cerradas en la bitácora —el
            # error de calibración de la §10.9, la dispersión de 1,58, el techo
            # de correlación— sin que nadie se enterara de por qué.
            #
            # Con esta regla cada fuente hace lo suyo: football-data mantiene
            # sus 20 ligas, ESPN llena las otras 41, y en las 20 aporta lo que
            # football-data NO publica (faltas, posesión, fueras de juego).
            # Es además la misma promesa que cumple el generador sintético dos
            # pasos más abajo, así que las tres capas se ordenan solas.
            j = d.columns.get_loc(c)
            actual = d.iat[pos, j]
            if actual is not None and not pd.isna(actual):
                continue
            d.iat[pos, j] = float(v)
            algo = True
        if algo:
            d.iat[pos, d.columns.get_loc('stats_origen')] = 'espn'
        puestos += int(algo)

    if puestos:
        logger.info('[stats_espn] %s: estadísticas reales en %d de %d partidos',
                    clave, puestos, len(d))
    return d


def limpiar(clave: str) -> Dict:
    """
    Quita de la cache las filas cuyo boxscore vino vacio (todo a ceros).

    Existe porque el filtro de `_fila_de_evento` se anadio DESPUES de empezar
    a descargar, asi que las primeras competiciones se guardaron con esas
    filas dentro. Es idempotente: pasarlo dos veces no quita nada la segunda.
    """
    d = leer(clave)
    if not len(d):
        return {'clave': clave, 'antes': 0, 'quitadas': 0}
    ph = pd.to_numeric(d.get('home_possession'), errors='coerce').fillna(0.0)
    pa = pd.to_numeric(d.get('away_possession'), errors='coerce').fillna(0.0)
    vacias = (ph + pa) <= 1.0
    n = int(vacias.sum())
    if n:
        _guardar(clave, d[~vacias])
    return {'clave': clave, 'antes': int(len(d)), 'quitadas': n,
            'quedan': int(len(d) - n)}


def cobertura(clave: str) -> Dict:
    """Cuántos partidos de esta competición tienen ya estadísticas reales."""
    c = leer(clave)
    if not len(c):
        return {'clave': clave, 'partidos': 0}
    return {'clave': clave, 'partidos': int(len(c)),
            'desde': str(c['fecha'].min()), 'hasta': str(c['fecha'].max()),
            'corners': int(c['home_corners'].notna().sum()),
            'tarjetas': int(c['home_yellow'].notna().sum()),
            'faltas': int(c['home_fouls'].notna().sum()),
            'posesion': int(c['home_possession'].notna().sum())}


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--liga', default=None, help='sólo esta competición')
    ap.add_argument('--desde', default=None,
                    help='YYYY-MM-DD (por defecto, 5 temporadas atrás)')
    ap.add_argument('--hasta', default=None)
    ap.add_argument('--dias', type=int, default=None,
                    help='atajo: los últimos N días (para el bot diario)')
    ap.add_argument('--hilos', type=int, default=HILOS)
    ap.add_argument('--limpiar', action='store_true',
                    help='quita las filas con el boxscore vacío')
    ap.add_argument('--informe', action='store_true',
                    help='sólo informar de lo acumulado, sin descargar')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')

    import fixtures_espn
    from config import LEAGUES

    claves = ([args.liga] if args.liga else
              [c for c, v in LEAGUES.items()
               if v.get('disponible') and c in fixtures_espn.ESPN_CODIGOS])

    if args.limpiar:
        total = 0
        for c in claves:
            r = limpiar(c)
            if r['quitadas']:
                print('  %-24s -%d filas vacías (quedan %d)'
                      % (c, r['quitadas'], r['quedan']))
            total += r['quitadas']
        print('filas vacías retiradas: %d' % total)
        return 0

    if args.informe:
        print('%-24s %8s %8s %8s %8s %12s' % ('liga', 'partidos', 'córners',
                                              'tarjetas', 'faltas', 'rango'))
        for c in claves:
            i = cobertura(c)
            if not i.get('partidos'):
                print('%-24s %8d' % (c, 0))
                continue
            print('%-24s %8d %8d %8d %8d  %s→%s'
                  % (c, i['partidos'], i['corners'], i['tarjetas'],
                     i['faltas'], i['desde'][:7], i['hasta'][:7]))
        return 0

    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    if args.dias:
        desde = (hoy - pd.Timedelta(days=int(args.dias))).strftime('%Y-%m-%d')
        hasta = hoy.strftime('%Y-%m-%d')
    else:
        desde = args.desde or (hoy - pd.Timedelta(days=365 * 5)).strftime('%Y-%m-%d')
        hasta = args.hasta or hoy.strftime('%Y-%m-%d')

    print('ventana %s → %s · %d competiciones' % (desde, hasta, len(claves)))
    total_nuevas = 0
    for c in claves:
        r = backfill(c, desde, hasta, hilos=args.hilos)
        if r.get('error'):
            print('  %-24s %s' % (c, r['error']))
            continue
        total_nuevas += r['nuevas']
        print('  %-24s +%-5d nuevas · %5d acumuladas · %4d con córners · %.0f s'
              % (c, r['nuevas'], r['acumulado'], r['con_corners'],
                 r['segundos']))
    print('TOTAL de filas nuevas: %d' % total_nuevas)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
