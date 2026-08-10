#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v107 — EL PANEL DE EQUIPOS: H2H, clasificación y forma, en un solo sitio.

Qué pidió el usuario
--------------------
Poder abrir «América vs Cruz Azul» y ver, sin pulsar nada, el historial de
cruces con sus marcadores y fechas, la clasificación del torneo en curso y
cómo llega cada equipo — al estilo de SofaScore — para decidir la apuesta con
todo delante. Y lo razonó bien:

> «si los equipos en todos los partidos los ha ganado el equipo A pues obvio
>  hay más probabilidad, pero si en el torneo actual el equipo B tiene mejor
>  rendimiento baja su probabilidad»

Por qué esto NO necesita ninguna API
------------------------------------
La sección que había (`render_h2h_club`) dependía de API-Football: hacía falta
una clave, gastaba peticiones de un presupuesto diario, exigía pulsar un botón
y su plan gratuito **se queda en la temporada 2024-25**. Con eso, el usuario
que no configura la clave no ve nada.

Y mientras tanto el proyecto ya tiene, para las 50 competiciones activas, un
`historico_<clave>.csv` con fecha, equipos y goles — el mismo fichero con el
que se entrena el modelo. Cubre más años que el plan gratuito de la API, es
instantáneo, no gasta cuota y no puede fallar por red. Medido en Liga MX:
**26 cruces de América-Cruz Azul entre 2018 y 2026**, contra los que la API
daba sólo hasta 2024-25.

Las ligas de formato `main` (football-data) traen además remates, córners y
tarjetas, así que donde existen se muestran y donde no, se dice.

Honestidad sobre lo que esto es y lo que no
-------------------------------------------
Esto es INFORMACIÓN para decidir, no un modelo nuevo ni un edge. El H2H y la
forma reciente ya están dentro del modelo (el ELO los absorbe partido a
partido), así que ver aquí que un equipo domina el historial **no significa que
haya valor**: lo más probable es que la cuota ya lo refleje. Lo que esta
pantalla añade es poder juzgar por qué el modelo dice lo que dice, y detectar
los casos en los que el contexto no está en los números (un derbi, una racha
contra un rival concreto, un equipo que cambió de entrenador).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Un hueco de este tamaño en el calendario separa temporadas (o Apertura de
# Clausura). Se detecta en vez de codificar el calendario de cada país: hay
# ligas de año natural (Brasil, MLS), de agosto a mayo (Europa) y de dos
# torneos por año (México, Argentina), y una regla por liga se queda obsoleta
# en cuanto una cambia de formato.
HUECO_TEMPORADA_DIAS = 45
_CACHE: Dict[str, pd.DataFrame] = {}


def _historico(clave: str) -> pd.DataFrame:
    """El histórico de la competición, con la fecha ya parseada. Vacío si no
    existe — nunca lanza, para que la pantalla degrade sola."""
    if clave in _CACHE:
        return _CACHE[clave]
    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        logger.info(f'[panel] {ruta} no existe')
        _CACHE[clave] = pd.DataFrame()
        return _CACHE[clave]
    try:
        d = pd.read_csv(ruta)
    except Exception as e:
        logger.warning(f'[panel] {ruta}: {type(e).__name__}: {e}')
        _CACHE[clave] = pd.DataFrame()
        return _CACHE[clave]
    # v118 — no todos los `historico_*.csv` son de equipos. El de tenis usa
    # `jugador_1`/`jugador_2` y no tiene `home_team`, así que al recorrerlos
    # todos (ver `forma_global`) reventaba con un KeyError. Se descarta aquí,
    # que es donde se sabe, en vez de en cada consumidor.
    if not {'date', 'home_team', 'away_team'} <= set(d.columns):
        _CACHE[clave] = pd.DataFrame()
        return _CACHE[clave]
    # `format='mixed'`: los históricos de ESPN traen '2024-03-06 19:00:00' y
    # los de football-data '2023-08-11'. Inferir un solo formato convertía a
    # NaT la mitad del fichero (el mismo fallo que la v105 encontró en el ELO
    # global, donde se perdían 37 de 66 competiciones enteras).
    d['date'] = pd.to_datetime(d['date'], errors='coerce', format='mixed')
    # v114 — EL BÉISBOL ANOTA CARRERAS, NO GOLES.
    #
    # `historico_mlb.csv` y `historico_kbo.csv` tienen exactamente la misma
    # forma que los de fútbol (date, home_team, away_team, marcador) pero
    # llaman `home_runs`/`away_runs` a las dos columnas del marcador. Con
    # renombrarlas aquí, todo el panel —cara a cara, forma, racha, local y
    # visitante— funciona en MLB y KBO sin duplicar una línea de lógica.
    #
    # Se hace en el ÚNICO sitio donde el fichero entra al módulo, que es lo
    # que evita tener que acordarse en cada función.
    if 'home_goals' not in d.columns:
        for origen, destino in (('home_runs', 'home_goals'),
                                ('away_runs', 'away_goals'),
                                ('home_score', 'home_goals'),
                                ('away_score', 'away_goals')):
            if origen in d.columns and destino not in d.columns:
                d[destino] = d[origen]
    for c in ('home_goals', 'away_goals'):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    if 'home_goals' not in d.columns or 'away_goals' not in d.columns:
        logger.info(f'[panel] {ruta} sin columnas de marcador reconocibles')
        _CACHE[clave] = pd.DataFrame()
        return _CACHE[clave]
    d = d.dropna(subset=['date', 'home_team', 'away_team',
                         'home_goals', 'away_goals'])
    d = d.sort_values('date').reset_index(drop=True)
    _CACHE[clave] = d
    return d


def limpiar_cache() -> None:
    _CACHE.clear()


def _resultado(gl: float, gv: float) -> str:
    return 'L' if gl > gv else ('E' if gl == gv else 'V')


# ---------------------------------------------------------------------------
# 1. Cara a cara
# ---------------------------------------------------------------------------
def h2h(clave: str, a: str, b: str, maximo: int = 10) -> Dict:
    """
    Historial de cruces entre dos equipos.

    Devuelve el balance ({a} ganados, empates, {b} ganados) y los últimos
    `maximo` partidos con su fecha y marcador — el formato que pidió el
    usuario, el mismo de SofaScore.
    """
    d = _historico(clave)
    if d.empty:
        return {'n': 0, 'partidos': [], 'motivo': 'sin histórico de esta '
                                                  'competición'}
    par = d[((d['home_team'] == a) & (d['away_team'] == b)) |
            ((d['home_team'] == b) & (d['away_team'] == a))]
    if par.empty:
        return {'n': 0, 'partidos': [],
                'motivo': f'{a} y {b} no se han cruzado en el histórico de '
                          f'esta competición ({len(d)} partidos desde '
                          f'{d["date"].min().date()})'}
    par = par.sort_values('date', ascending=False)

    gana_a = int((((par['home_team'] == a) & (par['home_goals'] > par['away_goals'])) |
                  ((par['away_team'] == a) & (par['away_goals'] > par['home_goals']))).sum())
    empates = int((par['home_goals'] == par['away_goals']).sum())
    gana_b = int(len(par) - gana_a - empates)

    partidos = [{
        'fecha': r['date'].date().isoformat(),
        'local': r['home_team'], 'visitante': r['away_team'],
        'goles_local': int(r['home_goals']), 'goles_visit': int(r['away_goals']),
        'ganador': (r['home_team'] if r['home_goals'] > r['away_goals']
                    else (r['away_team'] if r['away_goals'] > r['home_goals']
                          else None)),
    } for _, r in par.head(maximo).iterrows()]

    goles_a = int(par.loc[par['home_team'] == a, 'home_goals'].sum()
                  + par.loc[par['away_team'] == a, 'away_goals'].sum())
    goles_b = int(par.loc[par['home_team'] == b, 'home_goals'].sum()
                  + par.loc[par['away_team'] == b, 'away_goals'].sum())
    return {
        'n': int(len(par)), 'equipo_a': a, 'equipo_b': b,
        'gana_a': gana_a, 'empates': empates, 'gana_b': gana_b,
        'goles_a': goles_a, 'goles_b': goles_b,
        'desde': par['date'].min().date().isoformat(),
        'hasta': par['date'].max().date().isoformat(),
        'media_goles': round(float((par['home_goals'] + par['away_goals']).mean()), 2),
        'pct_ambos_marcan': round(float(((par['home_goals'] >= 1) &
                                         (par['away_goals'] >= 1)).mean()), 3),
        'partidos': partidos,
    }


# ---------------------------------------------------------------------------
# 2. Temporada en curso y clasificación
# ---------------------------------------------------------------------------
def temporada_actual(clave: str) -> Optional[pd.DataFrame]:
    """
    Los partidos del torneo EN CURSO.

    Se detecta por el último hueco largo del calendario en vez de codificar la
    temporada de cada país: hay ligas de año natural (Brasil, MLS), de agosto a
    mayo (Europa) y de dos torneos por año (México, Argentina). Una regla por
    liga se rompe en cuanto una cambia de formato; un hueco de mes y medio sin
    jugar es un corte de temporada en cualquiera de ellas.
    """
    d = _historico(clave)
    if d.empty:
        return None
    ultimo = d['date'].max()
    reciente = d[d['date'] >= ultimo - pd.Timedelta(days=400)]
    if reciente.empty:
        return None
    huecos = reciente['date'].diff().dt.days
    cortes = reciente.index[huecos > HUECO_TEMPORADA_DIAS]
    if len(cortes):
        reciente = reciente.loc[cortes[-1]:]
    return reciente


def clasificacion(clave: str) -> List[Dict]:
    """
    Tabla de posiciones del torneo en curso, calculada del histórico.

    Tres puntos por victoria, uno por empate. No se lee de ninguna fuente
    externa: sale de los mismos partidos con los que se entrena el modelo, así
    que nunca puede contradecirlo ni quedarse sin actualizar por su cuenta.
    """
    t = temporada_actual(clave)
    if t is None or t.empty:
        return []
    filas: Dict[str, Dict] = {}

    def _fila(eq):
        return filas.setdefault(eq, {'equipo': eq, 'pj': 0, 'g': 0, 'e': 0,
                                     'p': 0, 'gf': 0, 'gc': 0, 'pts': 0})

    for _, r in t.iterrows():
        gl, gv = int(r['home_goals']), int(r['away_goals'])
        loc, vis = _fila(r['home_team']), _fila(r['away_team'])
        for f, gfa, gco in ((loc, gl, gv), (vis, gv, gl)):
            f['pj'] += 1
            f['gf'] += gfa
            f['gc'] += gco
            if gfa > gco:
                f['g'] += 1
                f['pts'] += 3
            elif gfa == gco:
                f['e'] += 1
                f['pts'] += 1
            else:
                f['p'] += 1
    salida = sorted(filas.values(),
                    key=lambda f: (-f['pts'], -(f['gf'] - f['gc']), -f['gf']))
    for i, f in enumerate(salida, 1):
        f['pos'] = i
        f['dg'] = f['gf'] - f['gc']
        f['pts_por_partido'] = round(f['pts'] / f['pj'], 2) if f['pj'] else 0.0
    return salida


def competiciones_del_equipo(equipo: str, excluir: Optional[str] = None,
                             desde_dias: int = 400) -> List[str]:
    """
    En qué otras competiciones ha jugado este equipo recientemente.

    v118 — el usuario lo señaló con un ejemplo exacto: «la MLS y la Liga MX
    juegan el Mundial de Clubes, la Leagues Cup… deben aparecer los partidos de
    todas las competiciones, no sólo de la liga actual, para determinar
    desgaste». Y es verdad: Monterrey tiene 316 partidos en el histórico de
    Liga MX y **330 en el de la Leagues Cup**, y la forma sólo miraba el
    primero. Un equipo que viene de jugar entre semana llega distinto, y eso no
    se veía.

    Se recorren los `historico_*.csv` del proyecto. No es caro: cada uno se lee
    una vez y queda en la caché del módulo.
    """
    import glob
    fuera = []
    corte = pd.Timestamp.today() - pd.Timedelta(days=desde_dias)
    for ruta in sorted(glob.glob('historico_*.csv')):
        clave = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        if excluir and clave == excluir:
            continue
        d = _historico(clave)
        if d.empty:
            continue
        suyos = d[((d['home_team'] == equipo) | (d['away_team'] == equipo))
                  & (d['date'] >= corte)]
        if not suyos.empty:
            fuera.append(clave)
    return fuera


def forma_global(clave: str, equipo: str, n: int = 8) -> Dict:
    """
    La forma del equipo en TODAS sus competiciones, no sólo en ésta.

    Devuelve lo mismo que `forma` más `competicion` en cada partido, para que
    se vea de dónde viene cada resultado. Si el equipo sólo juega una
    competición, el resultado es idéntico al de `forma` — así que sustituirla
    no cambia nada donde no había nada que añadir.
    """
    import glob
    filas = []
    for ruta in sorted(glob.glob('historico_*.csv')):
        cl = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        d = _historico(cl)
        if d.empty:
            continue
        suyos = d[(d['home_team'] == equipo) | (d['away_team'] == equipo)]
        for _, r in suyos.iterrows():
            filas.append((r, cl))
    if not filas:
        return {'n': 0, 'partidos': [], 'competiciones': []}
    # v118 — EL MISMO PARTIDO NO PUEDE CONTAR DOS VECES.
    #
    # Los históricos se solapan: «Monterrey 2-0 Atlas» del 2 de agosto está en
    # `historico_liga_mx.csv` y en `historico_leagues_cup.csv`, porque el
    # ingestor de cada competición recoge lo que ESPN publica bajo su código y
    # algunos partidos aparecen en los dos. Sin deduplicar, la racha sale con
    # ocho entradas y sólo seis partidos, y el contador de desgaste —que es
    # justo para lo que se pidió esto— exagera la carga.
    #
    # La identidad de un partido es (fecha, local, visitante, marcador): si
    # coincide todo eso, es el mismo aunque venga de dos ficheros. Se conserva
    # la primera aparición y se anotan las competiciones donde salió.
    vistos, unicas = {}, []
    for r, cl in sorted(filas, key=lambda x: x[0]['date'], reverse=True):
        k = (str(r['date'])[:10], str(r['home_team']), str(r['away_team']),
             int(r['home_goals']), int(r['away_goals']))
        if k in vistos:
            vistos[k].add(cl)
            continue
        vistos[k] = {cl}
        unicas.append((r, cl, k))
    filas = [(r, cl) for r, cl, _k in unicas[:n]]

    partidos, racha, gf, gc = [], [], 0, 0
    comps = set()
    for r, cl in filas:
        en_casa = r['home_team'] == equipo
        propio = int(r['home_goals'] if en_casa else r['away_goals'])
        ajeno = int(r['away_goals'] if en_casa else r['home_goals'])
        res = 'G' if propio > ajeno else ('E' if propio == ajeno else 'P')
        racha.append(res)
        gf += propio
        gc += ajeno
        comps.add(cl)
        partidos.append({
            'fecha': r['date'].date().isoformat(),
            'rival': r['away_team'] if en_casa else r['home_team'],
            'casa': bool(en_casa), 'goles': propio, 'encajados': ajeno,
            'resultado': res, 'competicion': cl,
            'es_de_esta_liga': cl == clave,
            'stats': _stats_partido(r, en_casa),
        })
    pj = len(partidos)
    # v118 — DESGASTE: partidos en los últimos 14 y 30 días, contando TODAS
    # las competiciones. Es el dato que el usuario pedía y que con una sola
    # liga no se puede calcular: un equipo con cuatro partidos en dos semanas
    # llega fundido, juegue donde juegue.
    hoy = pd.Timestamp.today().normalize()
    def _en(dias):
        lim = hoy - pd.Timedelta(days=dias)
        return sum(1 for p in partidos if pd.Timestamp(p['fecha']) >= lim)
    return {
        'n': pj, 'racha': ''.join(racha),
        'ganados': racha.count('G'), 'empatados': racha.count('E'),
        'perdidos': racha.count('P'),
        'gf': gf, 'gc': gc,
        'gf_media': round(gf / pj, 2), 'gc_media': round(gc / pj, 2),
        'pts_por_partido': round((racha.count('G') * 3 + racha.count('E')) / pj, 2),
        'partidos': partidos,
        'competiciones': sorted(comps),
        'partidos_14d': _en(14), 'partidos_30d': _en(30),
    }


def posicion(clave: str, equipo: str) -> Optional[Dict]:
    """La fila de la clasificación de ese equipo, o None si no está."""
    for f in clasificacion(clave):
        if f['equipo'] == equipo:
            return f
    return None


# ---------------------------------------------------------------------------
# 3. Forma reciente
# ---------------------------------------------------------------------------
# Estadísticas que los históricos publican, con el nombre que se enseña. La
# clave es el sufijo: la columna real es `home_<sufijo>` o `away_<sufijo>`
# según de qué lado jugara el equipo.
STATS_PARTIDO = (
    ('shots_on', 'Tiros a puerta'),
    ('shots_off', 'Tiros fuera'),
    ('corners', 'Córners'),
    ('yellow', 'Amarillas'),
    ('red', 'Rojas'),
    ('possession', 'Posesión %'),
    ('xg', 'xG'),
)


def _stats_partido(fila, en_casa: bool) -> Dict:
    """
    Las estadísticas de ESE partido, ya orientadas al equipo que se consulta:
    `propio` es lo que hizo él y `rival` lo que le hicieron.

    Devuelve sólo las que la competición publica de verdad. Un histórico de
    formato «new» sólo tiene goles, y entonces esto viene vacío — que es la
    respuesta correcta, no un cero.
    """
    yo, otro = ('home', 'away') if en_casa else ('away', 'home')
    salida: Dict[str, Dict] = {}
    for sufijo, etiqueta in STATS_PARTIDO:
        c_yo, c_otro = f'{yo}_{sufijo}', f'{otro}_{sufijo}'
        try:
            v_yo = fila[c_yo] if c_yo in fila.index else None
            v_otro = fila[c_otro] if c_otro in fila.index else None
        except Exception:
            continue
        if v_yo is None or pd.isna(v_yo):
            continue
        try:
            salida[etiqueta] = {
                'propio': round(float(v_yo), 2),
                'rival': (round(float(v_otro), 2)
                          if v_otro is not None and not pd.isna(v_otro)
                          else None)}
        except (TypeError, ValueError):
            continue
    return salida


def forma(clave: str, equipo: str, n: int = 6) -> Dict:
    """
    Cómo llega el equipo: sus últimos `n` partidos, con marcador y rival.

    Se cuenta sobre TODO el histórico de la competición, no sólo la temporada
    en curso, porque al principio de temporada la muestra sería de dos o tres
    partidos y una racha de dos victorias parecería una tendencia.
    """
    d = _historico(clave)
    if d.empty:
        return {'n': 0, 'partidos': []}
    suyos = d[(d['home_team'] == equipo) | (d['away_team'] == equipo)]
    if suyos.empty:
        return {'n': 0, 'partidos': []}
    suyos = suyos.sort_values('date', ascending=False).head(n)

    partidos, racha, gf, gc = [], [], 0, 0
    for _, r in suyos.iterrows():
        en_casa = r['home_team'] == equipo
        propio = int(r['home_goals'] if en_casa else r['away_goals'])
        ajeno = int(r['away_goals'] if en_casa else r['home_goals'])
        res = 'G' if propio > ajeno else ('E' if propio == ajeno else 'P')
        racha.append(res)
        gf += propio
        gc += ajeno
        partidos.append({
            'fecha': r['date'].date().isoformat(),
            'rival': r['away_team'] if en_casa else r['home_team'],
            'casa': bool(en_casa), 'goles': propio, 'encajados': ajeno,
            'resultado': res,
            # v114 — las ESTADÍSTICAS de cada partido, no sólo el marcador.
            #
            # El usuario lo pidió: «que haya otra sección que me muestre los
            # partidos más recientes de América con sus estadísticas, marcador,
            # etc., para evaluar qué conviene elegir». El histórico ya las
            # traía (tiros, córners, tarjetas, posesión) y aquí se tiraban.
            #
            # Se devuelve lo que EXISTA en esa competición: los históricos de
            # football-data «main» traen tiros y tarjetas, los de formato
            # «new» sólo goles, y Liga MX añade xG y posesión. Un partido sin
            # una estadística no la inventa: sale ausente.
            'stats': _stats_partido(r, en_casa),
        })
    pj = len(partidos)
    return {
        'n': pj, 'racha': ''.join(racha),
        'ganados': racha.count('G'), 'empatados': racha.count('E'),
        'perdidos': racha.count('P'),
        'gf': gf, 'gc': gc,
        'gf_media': round(gf / pj, 2), 'gc_media': round(gc / pj, 2),
        'pts_por_partido': round((racha.count('G') * 3 + racha.count('E')) / pj, 2),
        'partidos': partidos,
    }


def rendimiento_casa_fuera(clave: str, equipo: str) -> Dict:
    """
    Rendimiento en casa y como visitante en el torneo en curso.

    Es la separación que más cambia un pronóstico y la que menos se mira: un
    equipo de media tabla puede ser el mejor local de la liga.
    """
    t = temporada_actual(clave)
    if t is None or t.empty:
        return {}
    salida = {}
    for lado, col_eq, col_gf, col_gc in (('casa', 'home_team', 'home_goals', 'away_goals'),
                                         ('fuera', 'away_team', 'away_goals', 'home_goals')):
        sub = t[t[col_eq] == equipo]
        if sub.empty:
            continue
        g = int((sub[col_gf] > sub[col_gc]).sum())
        e = int((sub[col_gf] == sub[col_gc]).sum())
        salida[lado] = {
            'pj': int(len(sub)), 'g': g, 'e': e, 'p': int(len(sub) - g - e),
            'gf': round(float(sub[col_gf].mean()), 2),
            'gc': round(float(sub[col_gc].mean()), 2),
            'pts_por_partido': round((g * 3 + e) / len(sub), 2),
        }
    return salida


# ---------------------------------------------------------------------------
# 4. La lectura: qué dice todo esto junto
# ---------------------------------------------------------------------------
def lectura(clave: str, local: str, visitante: str,
            prob_modelo: Optional[Dict] = None) -> List[str]:
    """
    Frases en lenguaje llano con lo que sale de los datos, y —cuando se pasa
    `prob_modelo`— si coincide o no con lo que dice el modelo.

    El razonamiento que pidió el usuario, explícito: el historial pesa, pero la
    forma del torneo en curso lo corrige. Cuando las dos señales apuntan al
    mismo lado se dice; cuando se contradicen, también — que es justo el caso
    en el que conviene no apostar.
    """
    frases: List[str] = []
    cruces = h2h(clave, local, visitante)
    # UN SOLO criterio de «domina», usado en todas las frases.
    #
    # Al principio había dos: la frase de arriba exigía el doble de victorias y
    # la de abajo se conformaba con `ga > gb`. Con 9-10-7 el panel decía
    # «historial parejo» y dos líneas después «América domina el historial».
    # Un panel que se contradice a sí mismo es peor que uno escueto: el usuario
    # no sabe cuál de las dos frases creerse.
    dom = None
    if cruces['n'] >= 3:
        ga, gb, e = cruces['gana_a'], cruces['gana_b'], cruces['empates']
        if ga >= gb * 2 and ga >= 3:
            dom = local
        elif gb >= ga * 2 and gb >= 3:
            dom = visitante
        if dom:
            frases.append(
                f"📜 **{dom} domina el historial**: {ga}-{e}-{gb} en "
                f"{cruces['n']} cruces desde {cruces['desde']}.")
        else:
            frases.append(
                f"📜 Historial parejo: {ga}-{e}-{gb} en {cruces['n']} cruces.")
        if cruces['media_goles'] >= 3.0:
            frases.append(
                f"⚽ Sus cruces son de goles: **{cruces['media_goles']} por "
                f"partido** y ambos marcan el "
                f"{cruces['pct_ambos_marcan']*100:.0f} % de las veces.")
        elif cruces['media_goles'] <= 2.0:
            frases.append(
                f"🔒 Sus cruces son cerrados: **{cruces['media_goles']} goles "
                f"por partido** de media.")
    elif cruces['n']:
        frases.append(f"📜 Sólo {cruces['n']} cruces en el histórico: muy poca "
                      f"muestra para leer nada de ahí.")

    pl, pv = posicion(clave, local), posicion(clave, visitante)
    if pl and pv:
        frases.append(
            f"🏆 En el torneo actual: **{local} {pl['pos']}º** "
            f"({pl['pts']} pts en {pl['pj']} PJ) · "
            f"**{visitante} {pv['pos']}º** ({pv['pts']} pts en {pv['pj']} PJ).")
        # Con pocas jornadas la tabla es ruido y decirlo importa: ser «1º» con
        # tres partidos no significa nada, y presentarlo con el mismo aire que
        # un liderato de jornada 20 induce justo al error que el usuario quiere
        # evitar.
        _pj_min = min(pl['pj'], pv['pj'])
        if _pj_min < 6:
            frases.append(
                f"🟡 Ojo con la tabla: el torneo lleva sólo {_pj_min} jornadas. "
                f"A estas alturas la clasificación es más azar que nivel — "
                f"pesa más el historial y la forma de abajo.")

        # El matiz que pidió el usuario: la forma del torneo corrige al
        # historial. Sólo se declara «mejor ahora» con una diferencia que
        # signifique algo (0,3 pts/partido ≈ una victoria cada 10 jornadas);
        # por debajo de eso los dos están igual y decir lo contrario sería
        # inventar una señal.
        _MARGEN = 0.30
        dif = pl['pts_por_partido'] - pv['pts_por_partido']
        mejor_ahora = (local if dif >= _MARGEN
                       else (visitante if dif <= -_MARGEN else None))
        if dom and mejor_ahora and _pj_min >= 6:
            if dom != mejor_ahora:
                frases.append(
                    f"⚠️ **Las dos señales se contradicen**: el historial va "
                    f"con {dom} pero {mejor_ahora} llega mejor esta temporada "
                    f"({max(pl, pv, key=lambda x: x['pts_por_partido'])['pts_por_partido']} "
                    f"pts/partido). Es el caso en el que menos claro está el "
                    f"favorito — y donde peor suele pagar forzar la apuesta.")
            else:
                frases.append(
                    f"✅ **Las dos señales coinciden**: {dom} domina el "
                    f"historial y además llega mejor esta temporada.")

    fl, fv = forma(clave, local), forma(clave, visitante)
    if fl['n'] and fv['n']:
        frases.append(
            f"📈 Forma (últimos {fl['n']}): **{local} {fl['racha']}** "
            f"({fl['pts_por_partido']} pts/p) · "
            f"**{visitante} {fv['racha']}** ({fv['pts_por_partido']} pts/p).")

    # ¿coincide con el modelo?
    if prob_modelo:
        try:
            ph, pa = float(prob_modelo.get('home', 0)), float(prob_modelo.get('away', 0))
            fav_modelo = local if ph > pa else visitante
            if pl and pv:
                fav_tabla = (local if pl['pts_por_partido'] > pv['pts_por_partido']
                             else visitante)
                if fav_modelo != fav_tabla:
                    frases.append(
                        f"🔍 El modelo favorece a **{fav_modelo}** aunque "
                        f"{fav_tabla} va mejor en la tabla. No es un error: el "
                        f"modelo pesa localía, descanso y calidad de rival, no "
                        f"sólo los puntos.")
        except (TypeError, ValueError):
            pass

    if not frases:
        frases.append('Sin histórico suficiente de esta competición para '
                      'sacar conclusiones.')
    return frases


def resumen(clave: str, local: str, visitante: str,
            prob_modelo: Optional[Dict] = None) -> Dict:
    """Todo el panel de un cruce, en una sola llamada."""
    return {
        'h2h': h2h(clave, local, visitante),
        'clasificacion': clasificacion(clave),
        'posicion_local': posicion(clave, local),
        'posicion_visitante': posicion(clave, visitante),
        'forma_local': forma(clave, local),
        'forma_visitante': forma(clave, visitante),
        'casa_fuera_local': rendimiento_casa_fuera(clave, local),
        'casa_fuera_visitante': rendimiento_casa_fuera(clave, visitante),
        'lectura': lectura(clave, local, visitante, prob_modelo),
    }
