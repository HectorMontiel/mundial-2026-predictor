# -*- coding: utf-8 -*-
"""
v307 — REMATES Y REMATES A PUERTA, POR JUGADOR Y POR EQUIPO, DESDE FOTMOB.

LO QUE PIDIÓ EL USUARIO
    «Quiero poder obtener los remates a puerta y remates por jugador de
     equipos de ligas principales y selecciones.»

QUÉ FALTABA, MEDIDO
Sobre el precálculo del 2026-09-23: «quién remata» salía en 91 de 97 partidos
de clubes y en **0 de 92** de selecciones (y 0 de 11 de la femenil). La fuente
de los clubes es el roster de ESPN; para selecciones `remates_seleccion`
devolvía vacío (probado con Japón: 0 filas en 8,4 s).

LA FUENTE
La ficha de cada partido en FotMob (`/match/<id>`, la página que responde; la
API está blindada). Lo que trae depende de la competición, comprobado a mano:
    · ligas, copas y partidos OFICIALES de selecciones (Nations League,
      eliminatorias, Eurocopa...): `playerStats` con los remates, los remates
      a puerta, los minutos, los goles y el xG de CADA jugador que jugó
      (Portugal–España, final de la Nations League: 34 jugadores con datos);
    · el mapa de disparos `shotmap`, disparo a disparo;
    · los AMISTOSOS de selecciones: sólo los totales del equipo
      (Inglaterra–Costa Rica: 29 remates a 1), ni mapa ni jugadores.
Con eso sale, por jugador y partido: si jugó, cuántos minutos, si fue
titular, remates, a puerta, goles y xG — también los que NO dispararon, que
es lo que hace que una media no esté inflada. Y por equipo y partido: remates,
a puerta, xG, goles y córners a favor.

QUÉ ESCRIBE (incremental: un partido ya guardado no se vuelve a pedir)
    remates_fotmob_jugadores.csv   una fila por jugador que jugó y partido
                                   (se conservan los últimos 10 de cada equipo)
    remates_fotmob_equipos.csv     una fila por equipo y partido (entero)

Y `filas_equipo(clave, equipo)` devuelve las filas con la forma que usa
`remates_jugador` (media por titularidad, posición gruesa), así que el modelo
calibrado de «quién remata» —lambda por jugador encogida hacia su posición y
escalada con lo que se espera que remate su equipo, la línea de la casa— sirve
igual para una selección. `lambdas_partido` da ese «lo que se espera que
remate su equipo» cuando nuestro histórico no trae remates (selecciones,
femenil): lo que tira cada uno promediado con lo que concede el otro, el mismo
estimador que ganó en `rendimiento_equipos`.

Uso:
    python remates_fotmob.py                      # lo nuevo (70 días clubes)
    python remates_fotmob.py --dias 420           # el fondo, una vez
    python remates_fotmob.py --solo-selecciones   # sólo selecciones
    python remates_fotmob.py --ligas mex_femenil,premier
"""
from __future__ import annotations

import csv
import logging
import os
import sys
import threading
import time
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

JUGADORES = 'remates_fotmob_jugadores.csv'
EQUIPOS = 'remates_fotmob_equipos.csv'
VACIOS = 'remates_fotmob_vacios.txt'
PAUSA = 1.0
HILOS = 4
# v308 — 10, la ventana con la que se midió y entrenó `remates_ml` (antes 8)
VENTANA = 10                      # partidos por equipo para las medias
MAX_PAGINAS = 1500                # por pasada, para no pasarse de cortesía
# Partidos por equipo que se conservan en el fichero de jugadores: los de la
# ventana y ni uno más. Con 67 ligas, guardarlos todos crecería ~50 MB al año
# en un fichero que el precálculo commitea varias veces al día (el repo ya
# pesa 16 GB). El de equipos es pequeño y se guarda entero: es el que sirve
# para medir.
CONSERVAR = VENTANA
# Cuánto hacia atrás hace falta para tener VENTANA partidos de cada equipo:
# un club juega 8 partidos en unos 2 meses; una selección, en un año largo.
DIAS_CLUBES = 70
DIAS_SELECCIONES = 420

# posición habitual de FotMob -> la gruesa del modelo calibrado
POSICION = {0: 'G', 1: 'D', 2: 'M', 3: 'F'}

# Las competiciones de SELECCIONES en FotMob (absolutas masculinas),
# comprobadas contra su página el 2026-09-23.
SELECCIONES = [
    (114, 'friendlies'),                       # amistosos: sólo totales
    (77, 'world-cup'), (50, 'euro'), (10607, 'euro-qualification'),
    (44, 'copa-america'), (289, 'africa-cup-of-nations'),
    (290, 'asian-cup'), (298, 'gold-cup'),
    (9806, 'nations-league-a'), (9807, 'nations-league-b'),
    (9808, 'nations-league-c'), (9809, 'nations-league-d'),
    (9821, 'concacaf-nations-league'),
    (10195, 'wc-qualification-uefa'), (10196, 'wc-qualification-caf'),
    (10197, 'wc-qualification-afc'), (10198, 'wc-qualification-concacaf'),
    (10199, 'wc-qualification-conmebol'), (10200, 'wc-qualification-ofc'),
    (10201, 'wc-qualification-inter-confederation'),
]

# FotMob -> el nombre de `historico_selecciones.csv`, que es el que llevan
# los pronósticos. Sacado comparando los 128 equipos capturados con nuestro
# histórico el 2026-09-23: sin esto Estados Unidos salía sin «quién remata».
NOMBRES_SELECCION = {
    'USA': 'United States', 'Bosnia and Herzegovina': 'Bosnia-Herzegovina',
    'Curacao': 'Curaçao', 'DR Congo': 'Congo DR',
    'Ireland': 'Republic of Ireland', 'Saint Martin': 'St. Martin',
    'Turkiye': 'Türkiye', 'UAE': 'United Arab Emirates',
}

# v308 — `pos` (el puesto de ESE partido: línea y carril, 105 es el nueve),
# `up` (su puesto habitual) y `mv` (valor de mercado): son tres de los rasgos
# que más pesan en el modelo de remates por jugador (`remates_ml`), medido
# sobre 165.620 titulares.
COL_J = ['match_id', 'fecha', 'liga', 'equipo', 'jugador', 'jugador_id',
         'posicion', 'titular', 'minutos', 'tiros', 'a_puerta', 'goles', 'xg',
         'pos', 'up', 'mv']
COL_E = ['match_id', 'fecha', 'liga', 'equipo', 'rival', 'local', 'tiros',
         'a_puerta', 'xg', 'goles', 'corners', 'por_jugador']


def competiciones(solo_selecciones: bool = False,
                  solo: Optional[List[str]] = None) -> List[tuple]:
    """[(clave, id, slug)] de todas las ligas verificadas y las selecciones
    (o sólo las claves de `solo`)."""
    if solo:
        return [c for c in competiciones() if c[0] in solo]
    fuera = []
    if not solo_selecciones:
        try:
            import fotmob_ligas as fl
            for k, (lid, slug) in fl.ids().items():
                fuera.append((k, lid, slug))
        except Exception as e:
            logger.debug('[remates_fotmob] ligas: %s', e)
        try:
            import historico_fotmob as hf
            vistos = {x[1] for x in fuera}
            for k, (paginas, _) in hf.LIGAS.items():
                for lid, slug in paginas:
                    if lid not in vistos:
                        fuera.append((k, lid, slug))
        except Exception:
            pass
    for lid, slug in SELECCIONES:
        fuera.append(('selecciones', lid, slug))
    return fuera


def _ya_guardados() -> set:
    ya = set()
    if os.path.exists(EQUIPOS):
        try:
            ya |= set(pd.read_csv(EQUIPOS, usecols=['match_id'])['match_id']
                      .astype(str))
        except Exception:
            pass
    if os.path.exists(VACIOS):
        with open(VACIOS, encoding='utf-8') as f:
            ya |= {x.strip() for x in f if x.strip()}
    return ya


def _minutos(jug: Dict, titular: bool) -> Optional[int]:
    ev = ((jug.get('performance') or {}).get('substitutionEvents') or [])
    salida = next((e.get('time') for e in ev if e.get('type') == 'subOut'),
                  None)
    entrada = next((e.get('time') for e in ev if e.get('type') == 'subIn'),
                   None)
    if titular:
        return int(salida) if salida is not None else 90
    if entrada is None:
        return None                     # no jugó
    fin = int(salida) if salida is not None else 90
    return max(1, fin - int(entrada))


def _valor(v) -> Optional[float]:
    """El número de una estadística de FotMob ({'value': 3}, 7, '1.00' o
    '441 (87%)')."""
    if isinstance(v, dict):
        v = v.get('value')
    if v is None:
        return None
    try:
        return float(str(v).split(' ')[0])
    except Exception:
        return None


def _entero(v) -> Optional[int]:
    return None if v is None else int(v)


def _stats_equipo(cont: Dict) -> Dict:
    """{clave: (local, visitante)} de las estadísticas del partido."""
    fuera = {}
    per = ((cont.get('stats') or {}).get('Periods') or {}).get('All') or {}
    for grupo in per.get('stats') or []:
        for s in grupo.get('stats') or []:
            par = s.get('stats') or []
            k = s.get('key')
            if k and len(par) == 2 and k not in fuera \
                    and (par[0] is not None or par[1] is not None):
                fuera[k] = (_valor(par[0]), _valor(par[1]))
    return fuera


def _stats_jugador(p: Dict) -> Dict:
    """{clave: número} de un jugador en `playerStats` (todas sus secciones)."""
    fuera = {}
    for grupo in p.get('stats') or []:
        for v in (grupo.get('stats') or {}).values():
            k = (v or {}).get('key')
            if k and k not in fuera:
                fuera[k] = _valor(v.get('stat'))
    return fuera


def _marcador(pp: Dict) -> Optional[tuple]:
    s = str(((pp.get('header') or {}).get('status') or {}).get('scoreStr')
            or '').replace(' ', '')
    trozos = s.split('-')
    if len(trozos) == 2 and all(t.isdigit() for t in trozos):
        return int(trozos[0]), int(trozos[1])
    return None


def extraer_de(raw: Dict, mid: str, liga: str) -> tuple:
    """(filas de jugadores, filas de equipos) de la ficha ya descargada.

    Tres fuentes, de mejor a peor, porque FotMob no da lo mismo en todos:
      1. `playerStats`: remates, a puerta, minutos, goles y xG de cada
         jugador.
      2. `shotmap`: los disparos uno a uno, si falta lo anterior.
      3. `stats` del partido: los totales del equipo. De un amistoso sale la
         fila del equipo pero NINGUNA de jugadores: ponerles ceros a todos
         hundiría la media de cada jugador sin que nadie hubiera dejado de
         rematar.
    """
    import historico_fotmob as hf
    pp = ((raw or {}).get('props') or {}).get('pageProps') or {}
    gen = pp.get('general') or {}
    cont = pp.get('content') or {}
    fecha = str(gen.get('matchTimeUTCDate') or '')[:10]
    def _nombre(x):
        x = hf._limpia(x)
        return NOMBRES_SELECCION.get(x, x) if liga == 'selecciones' else x
    equipos = {}
    for lado in ('homeTeam', 'awayTeam'):
        t = gen.get(lado) or {}
        equipos[t.get('id')] = (_nombre(t.get('name')), lado == 'homeTeam')
    if len(equipos) != 2 or None in equipos:
        return [], []
    # 1) por jugador desde playerStats
    pst = {}
    for k, p in (cont.get('playerStats') or {}).items():
        st = _stats_jugador(p or {})
        if st.get('total_shots') is not None:
            pst[str((p or {}).get('id') or k)] = st
    # 2) por jugador desde el mapa de disparos
    tiros = {}
    for s in ((cont.get('shotmap') or {}).get('shots') or []):
        if s.get('isOwnGoal'):
            continue
        d = tiros.setdefault(str(s.get('playerId')), {
            'tiros': 0, 'a_puerta': 0, 'goles': 0, 'xg': 0.0,
            'equipo': s.get('teamId')})
        d['tiros'] += 1
        d['a_puerta'] += 1 if s.get('isOnTarget') else 0
        d['goles'] += 1 if s.get('eventType') == 'Goal' else 0
        d['xg'] += float(s.get('expectedGoals') or 0.0)
    por_jugador = bool(pst) or bool(tiros)
    fj = []
    if por_jugador:
        lu = cont.get('lineup') or {}
        for lado in ('homeTeam', 'awayTeam'):
            t = lu.get(lado) or {}
            nombre = (_nombre(t.get('name'))
                      or equipos.get(t.get('id'), ('', 0))[0])
            for grupo, tit in (('starters', True), ('subs', False)):
                for j in t.get(grupo) or []:
                    jid = str(j.get('id'))
                    st = pst.get(jid)
                    mins = (st or {}).get('minutes_played') or _minutos(j, tit)
                    if not mins:
                        continue                    # no jugó
                    if pst:
                        st = st or {}
                        d = {'tiros': st.get('total_shots') or 0,
                             'a_puerta': st.get('ShotsOnTarget') or 0,
                             'goles': st.get('goals') or 0,
                             'xg': st.get('expected_goals') or 0.0}
                    else:
                        d = tiros.get(jid) or {}
                    fj.append({'match_id': mid, 'fecha': fecha, 'liga': liga,
                               'equipo': nombre, 'jugador': j.get('name'),
                               'jugador_id': j.get('id'),
                               'posicion': POSICION.get(
                                   j.get('usualPlayingPositionId'), ''),
                               'titular': int(tit), 'minutos': int(mins),
                               'tiros': int(d.get('tiros', 0)),
                               'a_puerta': int(d.get('a_puerta', 0)),
                               'goles': int(d.get('goles', 0)),
                               'xg': round(float(d.get('xg', 0.0)), 3),
                               'pos': j.get('positionId'),
                               'up': j.get('usualPlayingPositionId'),
                               'mv': j.get('marketValue')})
    # 3) totales del equipo: las estadísticas del partido mandan; si faltan,
    #    la suma del mapa de disparos
    ste = _stats_equipo(cont)
    suma = {}
    for d in tiros.values():
        e = suma.setdefault(d['equipo'], {'tiros': 0, 'a_puerta': 0,
                                          'xg': 0.0, 'goles': 0})
        for k in ('tiros', 'a_puerta', 'goles'):
            e[k] += d[k]
        e['xg'] += d['xg']
    marcador = _marcador(pp)
    ids = list(equipos)
    fe = []
    for tid in ids:
        nombre, local = equipos[tid]
        i = 0 if local else 1
        rival = equipos[[x for x in ids if x != tid][0]][0]
        e = suma.get(tid) or {}

        def de(clave, alt=None):
            v = (ste.get(clave) or (None, None))[i]
            return v if v is not None else alt
        t = de('total_shots', e.get('tiros'))
        if t is None:
            continue
        xg = de('expected_goals', e.get('xg'))
        fe.append({'match_id': mid, 'fecha': fecha, 'liga': liga,
                   'equipo': nombre, 'rival': rival, 'local': int(local),
                   'tiros': int(t),
                   'a_puerta': _entero(de('ShotsOnTarget', e.get('a_puerta'))),
                   'xg': None if xg is None else round(float(xg), 3),
                   'goles': marcador[i] if marcador else e.get('goles'),
                   'corners': _entero(de('corners')),
                   'por_jugador': int(por_jugador)})
    if len(fe) != 2:
        return [], []
    return fj, fe


def extraer(mid: str, liga: str) -> Optional[tuple]:
    """(filas de jugadores, filas de equipos) de un partido; ([], []) si la
    ficha no trae nada y None si FotMob no respondió. La diferencia importa:
    lo primero se apunta para no volver a pedirlo y lo segundo NO, o un
    corte de red de un día dejaría esos partidos fuera para siempre."""
    import fotmob_scraper as fm
    raw = fm._next_data('https://www.fotmob.com/match/%s' % mid)
    if not raw or not ((raw.get('props') or {}).get('pageProps') or {}).get(
            'general'):
        return None
    return extraer_de(raw, mid, liga)


def _anexar(ruta: str, filas: List[Dict], cols: List[str]) -> None:
    if not filas:
        return
    # un fichero escrito antes de añadir columnas: se reescribe una vez con
    # la cabecera nueva (las columnas que le faltan quedan vacías)
    if os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as f:
            cab = f.readline().strip().split(',')
        if cab != cols:
            viejo = pd.read_csv(ruta, low_memory=False)
            for c in cols:
                if c not in viejo.columns:
                    viejo[c] = None
            viejo[cols].to_csv(ruta, index=False)
    nuevo = not os.path.exists(ruta)
    with open(ruta, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def podar(ruta: str = JUGADORES, conservar: int = CONSERVAR) -> int:
    """Deja en el fichero de jugadores sólo los últimos `conservar` partidos
    de cada equipo. Devuelve las filas quitadas."""
    if not os.path.exists(ruta):
        return 0
    d = pd.read_csv(ruta, low_memory=False)
    # el equipo por su nombre sin acentos, como al leer: «Almeria» y
    # «Almería» son el mismo y comparten los `conservar` partidos
    d['_eq'] = d['liga'].astype(str) + '|' + d['equipo'].map(_sin_acentos)
    part = (d[['_eq', 'match_id', 'fecha']].drop_duplicates()
            .sort_values('fecha'))
    vivos = part.groupby('_eq').tail(conservar)
    llave = set(zip(vivos['_eq'], vivos['match_id'].astype(str)))
    ok = [(e, str(m)) in llave for e, m in zip(d['_eq'], d['match_id'])]
    d = d.drop(columns=['_eq'])
    quitadas = int(len(d) - sum(ok))
    if quitadas:
        tmp = ruta + '.nuevo'
        d[ok].to_csv(tmp, index=False)
        os.replace(tmp, ruta)
    return quitadas


def _partidos_de(liga: str, lid: int, slug: str, desde) -> List[tuple]:
    """Los partidos terminados desde `desde` de una competición, mirando la
    temporada anterior si la actual no llega tan atrás."""
    import historico_fotmob as hf
    fuera = []
    temporadas = ['']
    if (pd.Timestamp.now('UTC').tz_localize(None) - desde).days > 60:
        try:
            ts = hf.temporadas(lid, slug)
            temporadas += ts[1:3]
        except Exception:
            pass
    for t in temporadas:
        try:
            ms = hf._temporada(lid, slug, t)
        except Exception as e:
            logger.debug('[remates_fotmob] %s %s: %s', liga, t, e)
            continue
        viejo = True
        for m in ms:
            st = m.get('status') or {}
            f = pd.to_datetime(st.get('utcTime'), errors='coerce', utc=True)
            if pd.isna(f):
                continue
            f = f.tz_convert(None)
            if f >= desde:
                viejo = False
            if not st.get('finished') or st.get('cancelled') or f < desde:
                continue
            fuera.append((f, str(m.get('id')), liga))
        if viejo and ms:
            break                        # esta temporada ya es anterior
    return fuera


def capturar(dias: Optional[int] = None, max_paginas: int = MAX_PAGINAS,
             solo_selecciones: bool = False,
             solo: Optional[List[str]] = None) -> Dict:
    """Guarda los partidos terminados que falten. Sin `dias`, la ventana de
    cada tipo (70 días clubes, 420 selecciones)."""
    from concurrent.futures import ThreadPoolExecutor
    ya = _ya_guardados()
    ahora = pd.Timestamp.now('UTC').tz_localize(None)
    comps = competiciones(solo_selecciones, solo)

    def _lista(c):
        liga, lid, slug = c
        d = dias if dias is not None else (
            DIAS_SELECCIONES if liga == 'selecciones' else DIAS_CLUBES)
        return _partidos_de(liga, lid, slug, ahora - pd.Timedelta(days=d))

    pendientes = []
    with ThreadPoolExecutor(HILOS) as ex:
        for lista in ex.map(_lista, comps):
            pendientes += [x for x in lista if x[1] not in ya]
    # sin repetidos (una selección sale en dos listas si el partido cuenta
    # para dos torneos) y lo más reciente primero: si el tope corta, corta lo
    # viejo
    pendientes = sorted({p[1]: p for p in pendientes}.values(), reverse=True)
    cerrojo = threading.Lock()
    cuenta = {'guardados': 0, 'sin_datos': 0, 'jugadores': 0,
              'sin_respuesta': 0}

    def _uno(p):
        _, mid, liga = p
        try:
            r = extraer(mid, liga)
        except Exception as e:
            logger.debug('[remates_fotmob] %s: %s', mid, e)
            r = None
        time.sleep(PAUSA)
        with cerrojo:
            if r is None:
                cuenta['sin_respuesta'] += 1
                return
            fj, fe = r
            if not fe:
                cuenta['sin_datos'] += 1
                with open(VACIOS, 'a', encoding='utf-8') as f:
                    f.write(mid + '\n')
                return
            _anexar(JUGADORES, fj, COL_J)
            _anexar(EQUIPOS, fe, COL_E)
            cuenta['guardados'] += 1
            cuenta['jugadores'] += 1 if fj else 0

    with ThreadPoolExecutor(HILOS) as ex:
        list(ex.map(_uno, pendientes[:max_paginas]))
    r = {'competiciones': len(comps), 'pendientes': len(pendientes),
         'guardados': cuenta['guardados'],
         'con_jugadores': cuenta['jugadores'],
         'sin_datos': cuenta['sin_datos'],
         'sin_respuesta': cuenta['sin_respuesta'], 'podadas': podar()}
    olvidar()
    logger.info('[remates_fotmob] %s', r)
    return r


# ---------------------------------------------------------------------------
# lectura
# ---------------------------------------------------------------------------
_CACHE: Dict = {}


# Nombres de nuestros pronósticos que FotMob escribe de otra forma y que el
# emparejador no casa solo.
ALIAS_EQUIPO = {'Celta B': 'Celta Fortuna'}


def _sin_acentos(t) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t or ''))
    return t.encode('ascii', 'ignore').decode().lower().strip()


def _leer(ruta: str, cols: List[str]) -> pd.DataFrame:
    try:
        d = pd.read_csv(ruta, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=cols)
    sel = d['liga'].astype(str) == 'selecciones'
    for c in ('equipo', 'rival'):
        if c in d.columns and sel.any():
            d.loc[sel, c] = d.loc[sel, c].replace(NOMBRES_SELECCION)
    # FotMob escribe el mismo equipo unas veces con acento y otras sin él
    # («Almeria» y «Almería» en la misma Segunda): sin unificar, la historia
    # del equipo se parte en dos y cada mitad tiene la mitad de partidos. Se
    # queda la grafía más frecuente de cada equipo en su competición.
    for c in ('equipo', 'rival'):
        if c not in d.columns or d.empty:
            continue
        llave = d['liga'].astype(str) + '|' + d[c].map(_sin_acentos)
        cuenta = d.groupby([llave, d[c]]).size().reset_index()
        cuenta.columns = ['llave', 'nombre', 'n']
        mejor = (cuenta.sort_values('n', ascending=False)
                 .drop_duplicates('llave').set_index('llave')['nombre'])
        d[c] = llave.map(mejor).fillna(d[c])
    return d


def _jugadores() -> pd.DataFrame:
    if 'j' not in _CACHE:
        _CACHE['j'] = _leer(JUGADORES, COL_J)
    return _CACHE['j']


def _equipos_df() -> pd.DataFrame:
    if 'e' not in _CACHE:
        _CACHE['e'] = _leer(EQUIPOS, COL_E)
    return _CACHE['e']


def olvidar() -> None:
    _CACHE.clear()


def _resolver_equipo(nombre: str, candidatos: List[str]) -> Optional[str]:
    if not nombre:
        return None
    nombre = ALIAS_EQUIPO.get(nombre, nombre)
    if nombre in candidatos:
        return nombre
    # las selecciones llegan en español desde las casas («Japón») y FotMob
    # las nombra en inglés («Japan»)
    try:
        en = _espanol_a_ingles().get(nombre)
        if en and en in candidatos:
            return en
    except Exception:
        pass
    try:
        import name_mapper as nm
        return nm.mapear(nombre, candidatos, contexto='remates_fotmob')
    except Exception:
        return None


def _espanol_a_ingles() -> Dict[str, str]:
    """{«Japón»: «Japan»} vía el código FIFA (`NOMBRES_PAIS` da el español,
    `TEAM_NAMES_EN` el inglés)."""
    if 'es_en' not in _CACHE:
        m = {}
        try:
            from config import TEAM_NAMES_EN
            from prediction_api import NOMBRES_PAIS
            for cod, es in NOMBRES_PAIS.items():
                if cod in TEAM_NAMES_EN:
                    m[es] = TEAM_NAMES_EN[cod]
        except Exception as e:
            logger.debug('[remates_fotmob] nombres: %s', e)
        _CACHE['es_en'] = m
    return _CACHE['es_en']


def _candidatos(d: pd.DataFrame, clave_liga: str) -> List[str]:
    """Los equipos entre los que buscar: los de la misma competición primero
    (un «Arsenal» femenino no es el masculino), todos si no hay."""
    if 'liga' in d.columns and clave_liga:
        s = d[d['liga'].astype(str) == str(clave_liga)]
        if len(s):
            return sorted(set(s['equipo'].astype(str)))
    return sorted(set(d['equipo'].astype(str)))


def filas_equipo(clave_liga: str, equipo: str,
                 ventana: int = VENTANA) -> List[Dict]:
    """Los jugadores del equipo en sus últimos `ventana` partidos CON datos
    por jugador, con la forma que usa `remates_jugador`."""
    d = _jugadores()
    if d.empty:
        return []
    eq = _resolver_equipo(equipo, _candidatos(d, clave_liga))
    if not eq:
        return []
    s = d[d['equipo'] == eq].sort_values('fecha')
    partidos = list(dict.fromkeys(s['match_id'].astype(str)))[-ventana:]
    s = s[s['match_id'].astype(str).isin(partidos)]
    import remates_jugador as rjg
    fuera = []
    for jug, g in s.groupby('jugador'):
        apar = float(len(g))
        tit = float(g['titular'].sum())
        pos = g['posicion'].dropna().astype(str)
        pos = pos[pos != '']
        tot, on = float(g['tiros'].sum()), float(g['a_puerta'].sum())
        # la media por TITULARIDAD, la misma función que el modelo calibrado:
        # un suplente que entra diez minutos no cuenta como un partido entero
        fuera.append({'jugador': jug,
                      'posicion': pos.mode().iat[0] if len(pos) else '',
                      'apariciones': apar, 'titularidades': tit,
                      'p_titular': round(tit / max(1.0, float(len(partidos))),
                                         3),
                      'partidos_equipo': len(partidos),
                      'base': 'últimos partidos (FotMob)',
                      'remates': int(tot), 'al_arco': int(on),
                      'media_tot': rjg.media_por_titularidad(tot, apar, tit,
                                                             'tot'),
                      'media_on': rjg.media_por_titularidad(on, apar, tit,
                                                            'on'),
                      'goles': int(g['goles'].sum()),
                      'xg': round(float(g['xg'].sum()), 2)})
    fuera.sort(key=lambda x: x['media_tot'] or 0.0, reverse=True)
    return fuera


def equipo_resumen(clave_liga: str, equipo: str,
                   ventana: int = VENTANA) -> Optional[Dict]:
    """Remates y a puerta del equipo (a favor y en contra) en sus últimos
    partidos. None si no hay."""
    d = _equipos_df()
    if d.empty:
        return None
    eq = _resolver_equipo(equipo, _candidatos(d, clave_liga))
    if not eq:
        return None
    s = d[d['equipo'] == eq].sort_values('fecha').tail(ventana)
    if s.empty:
        return None
    contra = d[d['match_id'].isin(s['match_id']) & (d['equipo'] != eq)]

    def media(serie):
        serie = pd.to_numeric(serie, errors='coerce').dropna()
        return round(float(serie.mean()), 2) if len(serie) else None
    return {'equipo': eq, 'partidos': int(len(s)),
            'tiros': media(s['tiros']), 'a_puerta': media(s['a_puerta']),
            'tiros_contra': media(contra['tiros']),
            'a_puerta_contra': media(contra['a_puerta'])}


MIN_PARTIDOS_LAMBDA = 3


def lambdas_partido(clave_liga: str, home: str,
                    away: str) -> Optional[Dict]:
    """Remates esperados de cada equipo en este partido, desde FotMob, con la
    forma de `rendimiento_equipos.remates_equipo`. None si falta alguno.

    λ = (lo que el equipo tira + lo que el rival concede) / 2, el estimador
    que ganó en `rendimiento_equipos` por Brier y ECE; aquí sin separar por
    bando porque una selección juega pocas veces en casa.
    """
    rh = equipo_resumen(clave_liga, home)
    ra = equipo_resumen(clave_liga, away)
    if not rh or not ra or min(rh['partidos'], ra['partidos']) \
            < MIN_PARTIDOS_LAMBDA:
        return None
    fuera = {}
    for nombre, a_favor, en_contra in (('totales', 'tiros', 'tiros_contra'),
                                       ('a_puerta', 'a_puerta',
                                        'a_puerta_contra')):
        vals = []
        for yo, otro in ((rh, ra), (ra, rh)):
            x = [v for v in (yo.get(a_favor), otro.get(en_contra))
                 if v is not None]
            vals.append(round(sum(x) / len(x), 3) if x else None)
        if None in vals:
            continue
        fuera[nombre] = {'lambda_home': vals[0], 'lambda_away': vals[1],
                         'lambda_total': round(vals[0] + vals[1], 3),
                         'origen': 'observado (FotMob)',
                         'clave_liga': clave_liga,
                         'partidos': (rh['partidos'], ra['partidos'])}
    return fuera or None


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    dias = None
    if '--dias' in sys.argv:
        dias = int(sys.argv[sys.argv.index('--dias') + 1])
    tope = MAX_PAGINAS
    if '--max' in sys.argv:
        tope = int(sys.argv[sys.argv.index('--max') + 1])
    global HILOS
    if '--hilos' in sys.argv:
        HILOS = int(sys.argv[sys.argv.index('--hilos') + 1])
    solo = None
    if '--ligas' in sys.argv:
        solo = sys.argv[sys.argv.index('--ligas') + 1].split(',')
    print(capturar(dias=dias, max_paginas=tope,
                   solo_selecciones='--solo-selecciones' in sys.argv,
                   solo=solo))
    return 0


if __name__ == '__main__':
    sys.exit(main())
