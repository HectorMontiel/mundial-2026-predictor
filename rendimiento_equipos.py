#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v152 — CÓMO LLEGA CADA EQUIPO, CON DATOS OBSERVADOS Y NADA MÁS.

Para qué
--------
El «Modo Modelo» ordena por probabilidad del modelo y enseña, al lado, el
rendimiento reciente del equipo recomendado. Este módulo es la fuente de ese
rendimiento: una llamada por equipo que devuelve racha, goles, córners y
remates de sus últimos partidos.

LA REGLA DE ESTE MÓDULO: SÓLO SALE LO QUE LA COMPETICIÓN PUBLICA
----------------------------------------------------------------
Un campo que la fuente no trae vuelve como `None` y la interfaz no lo pinta. No
hay medias de relleno, ni ceros por defecto, ni estimaciones «razonables». Es la
lección de la v149-v150 escrita como código: *un hueco se ve, un relleno no*, y
en cuanto se rellena un dato con una estimación plausible nadie vuelve a saber
cuál es cuál.

POR QUÉ AQUÍ NO HAY xG
----------------------
El plan pedía enseñar «xG a favor y en contra de los últimos 5». No se puede, y
no por falta de código: **el xG de este proyecto es sintético**. Lo rellena
`CorrelatedSyntheticGenerator.generate_advanced_metrics` como

    xG = xg_intercept + xg_slope_goles · goles_reales + ruido(xg_residual_std)

Medido el 2026-08-21 sobre los históricos guardados, ajustando xG contra goles:

    liga             n        intercepto   pendiente   sd residual
    Bundesliga       9.792    0,785        0,201       0,519
    Argentina        7.610    0,785        0,200       0,498
    Liga MX          5.302    0,776        0,203       0,509
    Brasileirão      6.174    0,775        0,208       0,505

    calibración del generador:  0,776       0,200       0,529

Los cuatro reproducen la calibración con tres decimales. O sea que el «xG» de
estos ficheros **es una función afín de los goles con ruido encima**: no lleva
ni un gramo de información que los goles no tengan ya, y lleva ruido que los
goles no tienen. Enseñarlo etiquetado como xG le diría al usuario que está
viendo calidad de ocasiones cuando está viendo el marcador multiplicado por 0,2.

Lo que sí es observado, y por eso es lo que sale aquí: **goles, córners, remates
y tarjetas**, que football-data publica partido a partido en sus 20 ligas de
formato 'main' (cobertura de córners medida: 100 %).

El xG REAL existe y es alcanzable —FotMob lo publica junto con posesión y
ocasiones claras, y `fotmob_scraper.py` ya lo sabe leer— pero hoy hay 28
partidos cacheados. Cuando la cobertura permita validarlo, entra por aquí sin
tocar la interfaz: basta con que `stats_disponibles` empiece a incluirlo.
"""
import logging

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

VENTANA = 5          # «los últimos 5», que es lo que se pidió y lo que se pinta
MIN_PARTIDOS = 3     # con menos, una racha no es una racha


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f      # NaN fuera


def _media(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _historico(clave: str):
    """El histórico de la competición. Se apoya en `panel_equipos`, que ya lo
    cachea, normaliza fechas y sabe de los históricos que no son de fútbol."""
    try:
        import panel_equipos
        return panel_equipos._historico(clave)
    except Exception as e:
        logger.debug('[rendimiento] %s: %s', clave, e)
        import pandas as pd
        return pd.DataFrame()


def forma(clave: str, equipo: str, n: int = VENTANA,
          solo_bando: Optional[str] = None) -> Dict:
    """
    Cómo llega `equipo` a su próximo partido, en `n` partidos.

    `solo_bando` ('casa' | 'fuera') restringe a los partidos de ese bando. Sirve
    para la lectura que más cambia un pronóstico y que menos se mira: un equipo
    puede sacar 7 córners en casa y 3 fuera, y el partido que se va a jugar
    tiene bandos asignados.

    Devuelve siempre las mismas claves. Las que la competición no publica valen
    `None`, y la interfaz las omite en vez de pintar un cero.
    """
    # v153.1 — EL ESQUEMA COMPLETO, SIEMPRE. Este diccionario existe porque el
    # docstring de arriba prometía «devuelve siempre las mismas claves» y no era
    # verdad: los dos caminos de «pocos partidos» devolvían `n` con un valor
    # mayor que cero y sin `pts_por_partido` detrás. La interfaz comprobaba `n`,
    # lo veía positivo, accedía al resto y reventaba con KeyError — en
    # producción, tumbando la pestaña entera del Modo Modelo.
    #
    # Un contrato a medias es peor que ninguno: el consumidor comprueba lo que
    # el contrato le dice que compruebe y aun así falla. Ahora todas las claves
    # existen desde el principio, con `None` donde no hay dato, que es
    # exactamente lo que el resto del módulo promete.
    vacio = {'equipo': equipo, 'clave_liga': clave, 'n': 0, 'bando': solo_bando,
             'racha': '', 'ganados': 0, 'empatados': 0, 'perdidos': 0,
             'pts_por_partido': None, 'gf_media': None, 'gc_media': None,
             'ck_favor': None, 'ck_contra': None, 'ck_total': None,
             'remates_favor': None, 'remates_contra': None, 'amarillas': None,
             'partidos': []}
    d = _historico(clave)
    if d is None or getattr(d, 'empty', True):
        return vacio
    en_casa_col = d['home_team'] == equipo
    de_fuera_col = d['away_team'] == equipo
    if solo_bando == 'casa':
        suyos = d[en_casa_col]
    elif solo_bando == 'fuera':
        suyos = d[de_fuera_col]
    else:
        suyos = d[en_casa_col | de_fuera_col]
    if suyos.empty:
        return vacio
    suyos = suyos.sort_values('date', ascending=False).head(int(n))
    if len(suyos) < MIN_PARTIDOS:
        return {**vacio, 'n': int(len(suyos)),
                'aviso': 'sólo %d partidos en el histórico: no hay racha que '
                         'leer' % len(suyos)}

    racha, gf, gc, ck_f, ck_c, rem_f, rem_c, amar = [], [], [], [], [], [], [], []
    partidos = []
    for _, r in suyos.iterrows():
        casa = (r['home_team'] == equipo)
        yo, otro = ('home', 'away') if casa else ('away', 'home')
        g_yo, g_otro = _num(r.get(yo + '_goals')), _num(r.get(otro + '_goals'))
        if g_yo is None or g_otro is None:
            continue
        res = 'G' if g_yo > g_otro else ('E' if g_yo == g_otro else 'P')
        racha.append(res)
        gf.append(g_yo)
        gc.append(g_otro)
        c_yo, c_otro = _num(r.get(yo + '_corners')), _num(r.get(otro + '_corners'))
        if c_yo is not None:
            ck_f.append(c_yo)
        if c_otro is not None:
            ck_c.append(c_otro)
        # remates totales = a puerta + fuera, que es como los publica
        # football-data (HST/HS − HST). Si falta cualquiera de los dos, no se
        # suma un total a medias.
        for destino, quien in ((rem_f, yo), (rem_c, otro)):
            on = _num(r.get(quien + '_shots_on'))
            off = _num(r.get(quien + '_shots_off'))
            if on is not None and off is not None:
                destino.append(on + off)
        a = _num(r.get(yo + '_yellow'))
        if a is not None:
            amar.append(a)
        partidos.append({
            'fecha': str(r['date'].date()) if hasattr(r['date'], 'date') else '',
            'rival': r['away_team'] if casa else r['home_team'],
            'casa': bool(casa), 'resultado': res,
            'goles': int(g_yo), 'encajados': int(g_otro),
            'corners': int(c_yo) if c_yo is not None else None,
        })

    pj = len(racha)
    if pj < MIN_PARTIDOS:
        return {**vacio, 'n': pj}
    g, e = racha.count('G'), racha.count('E')
    return {
        'equipo': equipo, 'clave_liga': clave, 'n': pj,
        'bando': solo_bando,
        # La racha se lee del más reciente al más antiguo en la lista, pero se
        # PINTA del más antiguo al más nuevo: «PGGEG» se lee mal si el último
        # partido está a la izquierda.
        'racha': ''.join(reversed(racha)),
        'ganados': g, 'empatados': e, 'perdidos': pj - g - e,
        'pts_por_partido': round((g * 3 + e) / pj, 2),
        'gf_media': _media(gf), 'gc_media': _media(gc),
        'ck_favor': _media(ck_f), 'ck_contra': _media(ck_c),
        'ck_total': (round(_media(ck_f) + _media(ck_c), 2)
                     if _media(ck_f) is not None and _media(ck_c) is not None
                     else None),
        'remates_favor': _media(rem_f), 'remates_contra': _media(rem_c),
        'amarillas': _media(amar),
        'partidos': partidos,
    }


def momentum(clave: str, equipo: str, n: int = VENTANA) -> Optional[Dict]:
    """
    Si el equipo va a más o a menos: los últimos `n` contra los `n` anteriores.

    Es una comparación de dos medias de cinco partidos, así que su margen de
    error es enorme y el texto lo dice. Vale para ordenar la lectura, no para
    decidir una apuesta.
    """
    d = _historico(clave)
    if d is None or getattr(d, 'empty', True):
        return None
    suyos = d[(d['home_team'] == equipo) | (d['away_team'] == equipo)]
    suyos = suyos.sort_values('date', ascending=False).head(int(n) * 2)
    if len(suyos) < int(n) * 2:
        return None

    def ppp(sub):
        pts = 0
        for _, r in sub.iterrows():
            casa = (r['home_team'] == equipo)
            g_yo = _num(r['home_goals'] if casa else r['away_goals'])
            g_ot = _num(r['away_goals'] if casa else r['home_goals'])
            if g_yo is None or g_ot is None:
                return None
            pts += 3 if g_yo > g_ot else (1 if g_yo == g_ot else 0)
        return pts / len(sub)

    rec, ant = ppp(suyos.head(int(n))), ppp(suyos.tail(int(n)))
    if rec is None or ant is None:
        return None
    dif = rec - ant
    return {
        'reciente': round(rec, 2), 'anterior': round(ant, 2),
        'delta': round(dif, 2),
        # El umbral es 0,4 puntos por partido —dos puntos en cinco jornadas—
        # porque por debajo de eso un solo resultado cambia el signo.
        'tendencia': 'sube' if dif >= 0.4 else ('baja' if dif <= -0.4 else 'igual'),
    }


_CACHE_SINT: Dict[str, Dict[str, bool]] = {}
_MUESTRA_SINT = 400
_FICHERO_SINT = 'cache_columnas_sinteticas.json'
_DISCO_SINT = None


def _firma(clave: str):
    """Tamaño y fecha del histórico. Si cambian, la respuesta guardada caduca."""
    import os
    ruta = 'historico_%s.csv' % clave
    try:
        s = os.stat(ruta)
        return '%d|%d' % (s.st_size, int(s.st_mtime))
    except OSError:
        return None


def _disco_sint() -> Dict:
    """
    El resultado de la prueba, guardado entre ejecuciones.

    La prueba cuesta ~0,3 s por competición (regenera 400 filas por cada
    columna) y su respuesta sólo cambia si cambia el fichero. Sin este caché,
    la pestaña nueva añadiría ~6 s al arranque en frío de una app que ya tarda
    119 s, y los añadiría **siempre**: `st.tabs` renderiza el contenido de
    todas las pestañas, se mire o no.
    """
    global _DISCO_SINT
    if _DISCO_SINT is None:
        import json
        import os
        _DISCO_SINT = {}
        if os.path.exists(_FICHERO_SINT):
            try:
                with open(_FICHERO_SINT, 'r', encoding='utf-8') as f:
                    _DISCO_SINT = json.load(f) or {}
            except Exception as e:
                logger.debug('[rendimiento] caché ilegible: %s', e)
                _DISCO_SINT = {}
    return _DISCO_SINT


def _guarda_sint(clave: str, firma: str, valor: Dict) -> None:
    import json
    d = _disco_sint()
    d[clave] = {'firma': firma, 'cols': valor}
    try:
        with open(_FICHERO_SINT, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:
        logger.debug('[rendimiento] no se pudo guardar la caché: %s', e)


def _columnas_sinteticas(clave: str, d) -> Dict[str, bool]:
    """
    Qué columnas de este histórico las escribió el generador sintético.

    NO es una inferencia estadística: es una REPRODUCCIÓN. El generador es
    determinista por `MATCH_ID` (`_uniformes_por_partido`: hash estable con una
    sal por variable), así que se le vuelve a pedir la columna sobre una muestra
    del propio fichero y se compara valor a valor. Si coincide, la columna no es
    un dato observado que casualmente se parece a la fórmula: **es la fórmula**.

    Se hace así, y no con una lista de columnas prohibidas escrita a mano,
    porque una lista se queda vieja en silencio: el día que una liga traiga xG
    de verdad, la lista seguiría diciendo que no y nadie se enteraría. Esto
    responde por el fichero que tiene delante.

    Cada columna se prueba SOLA —se borra esa y se dejan las demás— porque el
    generador encadena: los remates salen del xG y los córners de los remates.
    Borrando todas a la vez, una columna real se recalcularía a partir de
    entradas sintéticas y saldría distinta, o sea «real», que es el error
    peligroso.
    """
    if clave in _CACHE_SINT:
        return _CACHE_SINT[clave]
    firma = _firma(clave)
    guardado = _disco_sint().get(clave)
    if guardado and firma and guardado.get('firma') == firma:
        _CACHE_SINT[clave] = guardado.get('cols') or {}
        return _CACHE_SINT[clave]
    salida: Dict[str, bool] = {}
    try:
        import numpy as np
        import statsbomb_calibration
        from correlated_synthetic_generator import CorrelatedSyntheticGenerator
        cal = statsbomb_calibration.calibrar()
        gen = CorrelatedSyntheticGenerator()
        base = d.head(_MUESTRA_SINT).copy()
        if 'MATCH_ID' not in base.columns or len(base) < 50:
            _CACHE_SINT[clave] = {}
            return {}
        for col in ('home_xg', 'home_possession', 'home_corners',
                    'home_shots_on', 'home_shots_off', 'home_yellow'):
            if col not in base.columns or not base[col].notna().any():
                continue
            prueba = base.drop(columns=[col])
            try:
                rehecho = gen.generate_advanced_metrics(prueba, cal)
            except Exception:
                continue
            a = pd.to_numeric(base[col], errors='coerce').to_numpy(float)
            b = pd.to_numeric(rehecho[col], errors='coerce').to_numpy(float)
            m = ~(np.isnan(a) | np.isnan(b))
            if m.sum() < 50:
                continue
            # 0,01 de tolerancia: el fichero guarda el xG redondeado a 2
            # decimales, así que exigir igualdad binaria daría «real» a una
            # columna sintética que sólo pasó por un round().
            iguales = float(np.mean(np.abs(a[m] - b[m]) <= 0.011))
            salida[col] = bool(iguales >= 0.95)
    except Exception as e:
        logger.debug('[rendimiento] prueba de síntesis en %s: %s', clave, e)
    _CACHE_SINT[clave] = salida
    if firma and salida:
        _guarda_sint(clave, firma, salida)
    return salida


def stats_disponibles(clave: str) -> Dict[str, bool]:
    """
    Qué publica esta competición **de verdad**, mirando su fichero.

    La interfaz pregunta ANTES de pintar: así una liga sin córners no enseña una
    fila de córners vacía. Y ninguna estadística sale por tener columna: sale
    por no ser reproducible con el generador sintético (`_columnas_sinteticas`).
    """
    d = _historico(clave)
    if d is None or getattr(d, 'empty', True):
        return {}
    cols = set(d.columns)
    sint = _columnas_sinteticas(clave, d)

    def hay(sufijo):
        c = 'home_' + sufijo
        if c not in cols or not bool(d[c].notna().any()):
            return False
        return not sint.get(c, False)

    return {
        'goles': ('home_goals' in cols and bool(d['home_goals'].notna().any())),
        'corners': hay('corners'),
        'remates': hay('shots_on') and hay('shots_off'),
        'tarjetas': hay('yellow'), 'posesion': hay('possession'),
        'xg': hay('xg'),
    }


def resumen_partido(clave: str, home: str, away: str,
                    n: int = VENTANA) -> Dict:
    """
    Las dos formas de un partido, más el momentum de cada uno, en una llamada.

    Es lo que consume la tarjeta del Modo Modelo. Cada equipo se mide DOS veces:
    en todos sus partidos y sólo en el bando que le toca jugar.
    """
    return {
        'clave_liga': clave, 'home': home, 'away': away,
        'disponible': stats_disponibles(clave),
        'forma_home': forma(clave, home, n),
        'forma_away': forma(clave, away, n),
        'casa_home': forma(clave, home, n, solo_bando='casa'),
        'fuera_away': forma(clave, away, n, solo_bando='fuera'),
        'momentum_home': momentum(clave, home, n),
        'momentum_away': momentum(clave, away, n),
    }


_CACHE_CK: Dict[str, Optional[float]] = {}


def media_corners_liga(clave: str, temporadas_recientes: int = 3) -> Optional[float]:
    """
    Total medio de córners por partido en esta competición, OBSERVADO.

    Devuelve `None` si la competición no publica córners de verdad. Eso es lo
    que separa esta función de un `mean()`: en 55 de las 75 competiciones del
    proyecto la columna existe y la escribió el generador sintético, y promediar
    el relleno del generador daría un número con aspecto de medición.

    Por qué existe, y qué sustituye
    -------------------------------
    La fórmula de producción deriva los córners del xG:
    `ck = 4,0 + 0,25·(lam_h+lam_a)·spx·tpo`. Medida sobre 20 competiciones y
    8.889 partidos de juicio, con split temporal y sin fuga:

        media de la competición ..............  MAE 2,6996
        fórmula actual .......................  MAE 3,0749   (peor en 19 de 20)
        fórmula con el nivel recalibrado .....  MAE 3,0609
        córners y remates reales (ridge) .....  MAE 2,6942   (mejora 0,005)

    Las dos lecturas que decidieron el cambio:

      · **La constante 4,0 no era el problema.** Recalibrar el nivel por liga
        recupera 0,014 de los 0,375 que la fórmula pierde. El 96 % del daño lo
        hace la parte variable.
      · **La parte variable es ruido.** Su correlación con el total real es
        −0,0012 de media sobre 11.856 partidos, y 0 de 15 ligas pasan de 0,1 en
        valor absoluto. Sumarla a una media añade varianza sin añadir señal, y
        por eso la empeora.

    Así que el mejor estimador medido del total de córners de un partido es la
    media de su competición. No es un modelo brillante: es el que menos se
    equivoca de los que se han probado, y decir eso es más útil que enseñar un
    número que parece específico del partido y no lo es.

    La ventana son las últimas temporadas y no el histórico entero porque el
    número de córners de una liga se mueve con los años (cambios de reglamento,
    de estilo); 3 temporadas es la misma ventana con la que se entrenan los
    modelos de liga.
    """
    if clave in _CACHE_CK:
        return _CACHE_CK[clave]
    valor = None
    try:
        if stats_disponibles(clave).get('corners'):
            d = _historico(clave)
            tot = (pd.to_numeric(d['home_corners'], errors='coerce')
                   + pd.to_numeric(d['away_corners'], errors='coerce')).dropna()
            if len(tot) >= 200:
                # las últimas ~3 temporadas: se cuenta por fecha, no por número
                # de filas, porque las competiciones no tienen el mismo tamaño
                corte = d['date'].max() - pd.Timedelta(days=365 * int(temporadas_recientes))
                recientes = tot[d['date'] >= corte]
                usar = recientes if len(recientes) >= 200 else tot
                valor = round(float(usar.mean()), 3)
    except Exception as e:
        logger.debug('[rendimiento] media de córners de %s: %s', clave, e)
    _CACHE_CK[clave] = valor
    return valor


# ---------------------------------------------------------------------------
# TENIS
#
# No pasa por `panel_equipos`: su histórico usa `jugador_1`/`jugador_2` y ese
# módulo lo descarta a propósito (no es un histórico de equipos). Aquí se lee
# aparte, y con la misma regla que el resto del módulo — si no hay partidos
# suficientes, sale `n` y nada más.
#
# La cobertura es la que es: 784 jugadores en el fichero, 349 con 5 partidos o
# más. Los otros 435 no enseñan racha, que es la respuesta correcta.
# ---------------------------------------------------------------------------
_RUTA_TENIS = 'historico_tenis_espn.csv'
_CACHE_TENIS = {}


def _historico_tenis():
    if 'd' not in _CACHE_TENIS:
        try:
            d = pd.read_csv(_RUTA_TENIS)
            d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
            _CACHE_TENIS['d'] = d.dropna(
                subset=['fecha', 'jugador_1', 'jugador_2', 'ganador'])
        except Exception as e:
            logger.debug('[rendimiento] histórico de tenis: %s', e)
            _CACHE_TENIS['d'] = pd.DataFrame()
    return _CACHE_TENIS['d']


def forma_tenis(jugador: str, n: int = VENTANA) -> Dict:
    """
    Cómo llega un jugador: racha y porcentaje de SETS de sus últimos `n`.

    El porcentaje de sets se separa del de partidos a propósito: ganar 2-0 y
    ganar 2-1 cuentan igual en la racha y no cuentan igual en la pista, y es la
    lectura que el plan pedía para el tenis.

    La superficie NO se cruza aquí. El pick del barrido ya trae la del partido
    y el modelo de tenis tiene ELO por superficie desde hace versiones
    (`DIFF_ELO_SUP`, con la pista cubierta como superficie propia); partir estos
    cinco partidos por superficie dejaría muestras de uno o dos, que no dicen
    nada.
    """
    vacio = {'n': 0, 'jugador': jugador}
    d = _historico_tenis()
    if d is None or getattr(d, 'empty', True) or not jugador:
        return vacio
    suyos = d[(d['jugador_1'] == jugador) | (d['jugador_2'] == jugador)]
    if suyos.empty:
        return vacio
    suyos = suyos.sort_values('fecha', ascending=False).head(int(n))
    if len(suyos) < MIN_PARTIDOS:
        return {**vacio, 'n': int(len(suyos))}

    racha, sg, sp = [], 0.0, 0.0
    for _, r in suyos.iterrows():
        es_1 = (r['jugador_1'] == jugador)
        racha.append('G' if str(r['ganador']).strip() == str(jugador).strip()
                     else 'P')
        s1, s2 = _num(r.get('sets_1')), _num(r.get('sets_2'))
        if s1 is None or s2 is None:
            continue
        sg += s1 if es_1 else s2
        sp += s2 if es_1 else s1
    tot = sg + sp
    return {
        'jugador': jugador, 'n': len(racha),
        'racha': ''.join(reversed(racha)),
        'ganados': racha.count('G'), 'perdidos': racha.count('P'),
        'sets_favor': int(sg), 'sets_contra': int(sp),
        'pct_sets': round(sg / tot, 3) if tot else None,
    }


_CACHE_DISP: Dict[str, Optional[float]] = {}


def dispersion_corners_liga(clave: str) -> Optional[float]:
    """
    Razón varianza/media del total de córners de esta competición.

    Es el número que dice cuánto se aparta el fenómeno de un Poisson, y sirve
    para una cosa muy concreta: calcular bien las probabilidades de «más de N
    córners».

    POR QUÉ NO BASTA POISSON, MEDIDO
    --------------------------------
    Los córners no llegan sueltos: un ataque genera un racimo —el saque se
    desvía, rebota en la barrera, otro córner— y eso infla la varianza sin que
    la media cambie. Medido sobre 20 competiciones, la razón varianza/media es
    **1,16**, no 1.

    Ignorarlo sesga las colas, que es justo donde están las líneas que cotiza la
    casa. Comparando la probabilidad calculada contra la frecuencia REAL en 24
    líneas de 6 competiciones:

        Poisson ..............  error medio 0,0093
        binomial negativa ....  error medio 0,0043   ← la mitad

    Devuelve `None` cuando la competición no publica córners observados: sin
    datos no hay dispersión que medir, y suponer 1,0 sería volver a Poisson por
    la puerta de atrás sin decirlo.
    """
    if clave in _CACHE_DISP:
        return _CACHE_DISP[clave]
    valor = None
    try:
        if stats_disponibles(clave).get('corners'):
            d = _historico(clave)
            tot = (pd.to_numeric(d['home_corners'], errors='coerce')
                   + pd.to_numeric(d['away_corners'], errors='coerce')).dropna()
            if len(tot) >= 400:
                m, v = float(tot.mean()), float(tot.var())
                if m > 0:
                    # Por debajo de 1 el conteo está MENOS disperso que un
                    # Poisson y la binomial negativa no existe: se corta en 1,0,
                    # que devuelve el comportamiento de Poisson.
                    valor = round(max(v / m, 1.0), 4)
    except Exception as e:
        logger.debug('[rendimiento] dispersión de córners de %s: %s', clave, e)
    _CACHE_DISP[clave] = valor
    return valor


def prob_mas_de(media: float, linea: float,
                dispersion: Optional[float] = None) -> Optional[float]:
    """
    P(total > linea) para un conteo con sobredispersión conocida.

    Con `dispersion` a None o 1,0 es exactamente Poisson. Por encima usa la
    binomial negativa con la misma media y esa razón varianza/media, que es la
    parametrización que ajusta el racimo sin tocar el nivel.
    """
    try:
        from scipy import stats as _st
        m = float(media)
        if m <= 0:
            return None
        k = int(np.floor(float(linea)))
        d = float(dispersion or 1.0)
        if d <= 1.0001:
            return float(1.0 - _st.poisson.cdf(k, m))
        # var = d·m  ->  r = m² / (var − m) = m / (d − 1)
        r = m / (d - 1.0)
        p = r / (r + m)
        return float(1.0 - _st.nbinom.cdf(k, r, p))
    except Exception as e:
        logger.debug('[rendimiento] prob_mas_de: %s', e)
        return None


_CACHE_DISP_EQ: Dict[str, Optional[float]] = {}


def dispersion_corners_equipo(clave: str) -> Optional[float]:
    """
    Razón varianza/media de los córners DE UN EQUIPO en esta competición.

    No es la del total, y la diferencia importa: medido sobre 6 competiciones,
    el total va a 1,16 y un equipo suelto a **1,58**. Tiene sentido — el racimo
    (un córner que genera otro) ocurre dentro del ataque del MISMO equipo, así
    que se nota más cuando se mira equipo a equipo que cuando se suman los dos y
    las rachas de uno rellenan los huecos del otro.

    Usar la dispersión del total para las líneas por equipo sería quedarse corto
    justo en las colas, que es donde están las líneas que cotiza la casa.
    """
    if clave in _CACHE_DISP_EQ:
        return _CACHE_DISP_EQ[clave]
    valor = None
    try:
        if stats_disponibles(clave).get('corners'):
            d = _historico(clave)
            serie = pd.concat([
                pd.to_numeric(d['home_corners'], errors='coerce'),
                pd.to_numeric(d['away_corners'], errors='coerce')]).dropna()
            if len(serie) >= 800:
                m, v = float(serie.mean()), float(serie.var())
                if m > 0:
                    valor = round(max(v / m, 1.0), 4)
    except Exception as e:
        logger.debug('[rendimiento] dispersión por equipo de %s: %s', clave, e)
    _CACHE_DISP_EQ[clave] = valor
    return valor


def lambda_corners_equipo(clave: str, equipo: str, rival: str,
                          en_casa: bool, n: int = 10) -> Optional[float]:
    """
    Córners esperados de `equipo` contra `rival`, jugando en su bando.

    ES EL ESTIMADOR QUE GANÓ, y por bastante. Medido sobre 30.454
    equipos-partido en 6 competiciones, comparando el error de calibración
    contra la frecuencia real en las líneas 3,5 / 4,5 / 5,5 / 6,5:

        ataque + defensa del rival, binomial negativa ....  0,0056
        media móvil de 5, Poisson ........................  0,0093
        media de la competición, binomial negativa .......  0,0101
        media del equipo, Poisson ........................  0,0296
        media de la competición, Poisson .................  0,0369

    O sea: seis veces mejor que la referencia. Dos cosas lo explican, y las dos
    hacen falta —cambiar sólo una de ellas se queda a mitad de camino:

      · **quién enfrente también cuenta.** Los córners que saca un equipo
        dependen de a quién ataca tanto como de cómo ataca, y `B_equipo` y
        `C_movil5` sólo miran a uno de los dos.
      · **cada bando por separado.** Lo que un equipo saca en casa y lo que saca
        fuera son dos cosas distintas, y el partido que se predice tiene bandos
        asignados.

    La ventana es de 10 y no de 5 a propósito: la media móvil de 5 salió PEOR
    (0,0093 con Poisson, 0,0149 con binomial negativa). Cinco partidos de un
    equipo son una muestra de cinco, y su propio ruido de Poisson es mayor que
    la señal que se busca.
    """
    d = _historico(clave)
    if d is None or getattr(d, 'empty', True):
        return None
    try:
        # LAS DOS COLUMNAS SON LA MISMA, Y NO ES UNA ERRATA.
        #
        # «Lo que saca el equipo en su bando» y «lo que el rival recibe en el
        # bando contrario» son córners del MISMO lado del marcador: si el equipo
        # juega en casa, los suyos son `home_corners`, y los que el rival encaja
        # jugando fuera también son `home_corners` (los del local de aquel
        # partido). Lo que cambia entre los dos es por QUIÉN se filtra, no qué
        # columna se lee.
        #
        # La primera versión puso aquí la columna contraria y las dos lambdas
        # del partido salían IDÉNTICAS —6,10 y 6,10 en Man City-Arsenal, 5,50 y
        # 5,50 en Liverpool-Everton—, que es lo que delató el fallo antes de
        # integrarlo. Con las columnas bien, ese partido da 6,10 y 4,40.
        col_eq = 'home_team' if en_casa else 'away_team'
        col_riv = 'away_team' if en_casa else 'home_team'
        col_saca = 'home_corners' if en_casa else 'away_corners'
        col_rec = col_saca

        saca = pd.to_numeric(
            d.loc[d[col_eq] == equipo, col_saca], errors='coerce').dropna()
        recibe = pd.to_numeric(
            d.loc[d[col_riv] == rival, col_rec], errors='coerce').dropna()
        if len(saca) < MIN_PARTIDOS or len(recibe) < MIN_PARTIDOS:
            return None
        return round((float(saca.tail(n).mean())
                      + float(recibe.tail(n).mean())) / 2.0, 3)
    except Exception as e:
        logger.debug('[rendimiento] lambda de córners %s: %s', clave, e)
        return None


def corners_equipo(clave: str, home: str, away: str,
                   n: int = 10) -> Optional[Dict]:
    """
    Los córners esperados de los dos equipos y la dispersión con la que
    convertirlos en probabilidades. `None` si la competición no los publica.
    """
    disp = dispersion_corners_equipo(clave)
    if disp is None:
        return None
    lh = lambda_corners_equipo(clave, home, away, True, n)
    la = lambda_corners_equipo(clave, away, home, False, n)
    if lh is None or la is None:
        return None
    return {'lambda_home': lh, 'lambda_away': la, 'dispersion': disp,
            'clave_liga': clave}


# ---------------------------------------------------------------------------
# v160 — TARJETAS
#
# La misma metodología con la que se cerraron los córners, aplicada al mercado
# de tarjetas: estimador ataque/defensa del rival con ventana 10, y binomial
# negativa con la razón varianza/media medida de la propia competición.
#
# QUÉ CUENTA UNA «TARJETA» AQUÍ: AMARILLAS **MÁS ROJAS**
# ------------------------------------------------------
# Esto no es un detalle de nomenclatura, es lo que decide si el EV que se
# calcule después sirve para algo. La primera versión contaba sólo amarillas
# —que es lo que football-data publica con más limpieza— y al cruzarla contra
# las líneas reales de la casa apareció un sesgo sistemático:
#
#     línea de la casa   P(más) del modelo   P(más) del mercado   diferencia
#         3,5                 0,565                0,622            −0,056
#         4,5                 0,406                0,489            −0,083
#         5,5                 0,232                0,368            −0,136
#         6,5                 0,134                0,242            −0,108
#
#     centro de la casa 4,43 · lambda del modelo 4,16 · −0,27 tarjetas
#
# El modelo veía MENOS tarjetas que la casa, y cada vez más según subía la
# línea — la firma exacta de estar contando una magnitud más pequeña. Y las
# rojas valen 0,25 por partido de media (0,13 en la Premier, 0,27 en Portugal),
# o sea casi exactamente los 0,27 que faltaban.
#
# Contarlas mejora TODO lo medible, no sólo el nivel:
#
#                              sólo amarillas   amarillas + rojas
#     calibración por equipo       0,0141            0,0117
#     correlación por equipo       0,146             0,150
#     calibración del total        0,0121            0,0119
#     correlación del total        0,107             0,110
#
# Queda una pregunta que estos datos no cierran y que `snapshots_tarjetas.py`
# está acumulando para cerrarla: si la casa cuenta una segunda amarilla como
# UNA tarjeta o como DOS. football-data suma la roja de la doble amarilla en
# `home_red` y las dos amarillas en `home_yellow`, así que aquí cuenta como
# tres. Cuando haya líneas liquidadas se sabrá; hasta entonces, esto es lo más
# cerca del mercado que se puede estar con datos y no con supuestos.
#
# LO QUE SE MIDIÓ
# ---------------
# 20 competiciones con tarjetas OBSERVADAS (las de formato 'main' de
# football-data; en las otras 55 la columna la escribió el generador sintético
# y `stats_disponibles` ya lo distingue). Split temporal, último 30 % como
# tramo de juicio, medias móviles desplazadas un partido — nada ve su propio
# resultado. Error de calibración contra la frecuencia REAL en las líneas que
# cotiza la casa:
#
#     POR EQUIPO (líneas 0,5 / 1,5 / 2,5 / 3,5, n = 52.648)
#       ataque + defensa del rival, ventana 10 ....  0,0117   corr 0,150
#       sólo lo que comete el equipo, ventana 10 ..  0,0155   corr 0,112
#       media móvil de 5 del equipo ...............  0,0227   corr 0,098
#       media de la competición en ese bando ......  0,0312   corr 0,101
#
#     TOTAL DEL PARTIDO (líneas 2,5 / 3,5 / 4,5 / 5,5, n = 26.324)
#       ataque + defensa del rival, binneg ........  0,0119   corr 0,110
#       ataque + defensa del rival, Poisson .......  0,0134   corr 0,110
#       media de la competición ...................  0,0488   corr 0,003
#
# DOS DIFERENCIAS CON LOS CÓRNERS QUE HAY QUE TENER PRESENTES
# -----------------------------------------------------------
# 1) **En el TOTAL, aquí sí gana el estimador del partido.** En córners la
#    media de la competición era imbatible (su parte variable tenía correlación
#    −0,0012 con el total real) y por eso `corners_tarjeta` la usa para el
#    total. En tarjetas la media de la liga tiene correlación 0,003 —o sea,
#    ninguna— y el estimador ataque/defensa llega a 0,110 y cuadruplica su
#    calibración. La indisciplina SÍ es un rasgo estable del equipo; sacar
#    córners depende del rival tanto como de uno.
#
# 2) **La binomial negativa aporta, pero por las ROJAS.** Contando sólo
#    amarillas la razón varianza/media salía 1,0 o por debajo en 19 de las 20
#    competiciones —un conteo sin sobredispersión, donde la binomial negativa
#    degenera en Poisson y no cambia nada—. Sumando las rojas sube a 1,35 en
#    Turquía, 1,37 en Portugal, 1,28 en la Eredivisie: una roja es un suceso
#    raro que arrastra más tarjetas detrás, y eso engorda la cola justo donde
#    están las líneas altas. Con eso, binneg gana a Poisson en el total
#    (0,0119 contra 0,0134). Los córners llegaban a 1,58 por equipo, así que
#    esto sigue siendo un racimo más flojo que aquél, pero ya no es cero.
#
# El detalle está en `_v160_tarjetas_estimadores.py` (sólo amarillas),
# `_v160_tarjetas_con_rojas.py` (lo adoptado) y `_v160_contra_mercado.py`.
# ---------------------------------------------------------------------------

_CACHE_DISP_TJ: Dict[str, Optional[float]] = {}
_CACHE_DISP_TJ_EQ: Dict[str, Optional[float]] = {}


def _tarjetas_de(d, bando: str):
    """
    Las tarjetas de un bando: amarillas MÁS rojas.

    Una fila a la que le falte cualquiera de las dos columnas sale `NaN` y no
    se cuenta, en vez de tratar la roja ausente como un cero. Un cero
    inventado aquí bajaría la media de la competición sin que se notara.
    """
    return (pd.to_numeric(d[bando + '_yellow'], errors='coerce')
            + pd.to_numeric(d[bando + '_red'], errors='coerce'))


def _serie_tarjetas(clave: str):
    """Las tarjetas de los dos bandos, si la competición las publica."""
    if not stats_disponibles(clave).get('tarjetas'):
        return None, None
    d = _historico(clave)
    if d is None or getattr(d, 'empty', True):
        return None, None
    if 'home_red' not in d.columns or 'away_red' not in d.columns:
        return None, None
    return d, (_tarjetas_de(d, 'home'), _tarjetas_de(d, 'away'))


def dispersion_tarjetas_liga(clave: str) -> Optional[float]:
    """
    Razón varianza/media del TOTAL de tarjetas de la competición.

    Medida contando amarillas + rojas: entre 1,00 y 1,37 según la liga, contra
    el 1,16 de los córners. Se corta en 1,0 por abajo —por debajo la binomial
    negativa no existe— y ahí `prob_mas_de` se comporta como Poisson, que es lo
    correcto: el conteo no está sobredisperso y forzar una cola más gorda sería
    inventarla.

    `None` si la competición no publica tarjetas observadas.
    """
    if clave in _CACHE_DISP_TJ:
        return _CACHE_DISP_TJ[clave]
    valor = None
    try:
        d, cols = _serie_tarjetas(clave)
        if cols is not None:
            tot = (cols[0] + cols[1]).dropna()
            if len(tot) >= 400:
                m, v = float(tot.mean()), float(tot.var())
                if m > 0:
                    valor = round(max(v / m, 1.0), 4)
    except Exception as e:
        logger.debug('[rendimiento] dispersión de tarjetas de %s: %s', clave, e)
    _CACHE_DISP_TJ[clave] = valor
    return valor


def dispersion_tarjetas_equipo(clave: str) -> Optional[float]:
    """
    Razón varianza/media de las tarjetas DE UN EQUIPO en la competición.

    Más baja que la del total —1,12 en Turquía contra 1,35, por ejemplo—, que
    es lo contrario de lo que pasaba en córners (1,58 por equipo contra 1,16 en
    el total). Tiene una explicación y conviene tenerla presente al leer los
    dos módulos: el racimo de córners ocurre DENTRO del ataque de un equipo, y
    el de tarjetas ocurre ENTRE los dos —una entrada dura trae la represalia—,
    así que sumar los dos bandos concentra el efecto en vez de diluirlo.
    """
    if clave in _CACHE_DISP_TJ_EQ:
        return _CACHE_DISP_TJ_EQ[clave]
    valor = None
    try:
        d, cols = _serie_tarjetas(clave)
        if cols is not None:
            serie = pd.concat([cols[0], cols[1]]).dropna()
            if len(serie) >= 800:
                m, v = float(serie.mean()), float(serie.var())
                if m > 0:
                    valor = round(max(v / m, 1.0), 4)
    except Exception as e:
        logger.debug('[rendimiento] dispersión de tarjetas por equipo de %s: %s',
                     clave, e)
    _CACHE_DISP_TJ_EQ[clave] = valor
    return valor


def lambda_tarjetas_equipo(clave: str, equipo: str, rival: str,
                           en_casa: bool, n: int = 10) -> Optional[float]:
    """
    Tarjetas esperadas de `equipo` contra `rival`, jugando en su bando.

    Mismo estimador que ganó en córners y por la misma razón: lo que el equipo
    RECIBE en su bando promediado con lo que el rival PROVOCA en el bando
    contrario. Las dos partes hacen falta —quitar cualquiera empeora la
    calibración de 0,0117 a 0,0155, medido— porque una tarjeta la saca el
    árbitro por algo que hacen los dos: uno que va a destiempo y otro que
    provoca.

    LAS DOS LECTURAS USAN LA MISMA COLUMNA, Y NO ES UNA ERRATA. Es el mismo
    caso que en `lambda_corners_equipo`, escrito aquí otra vez porque la
    primera versión de aquélla se equivocó justo en esto: si el equipo juega en
    casa, las tarjetas que él ve son las del bando local, y las que el rival
    provoca cuando visita también son las del bando local —las del local de
    aquellos partidos—. Lo que cambia entre las dos no es la columna, es POR
    QUIÉN se filtra. Poner la columna contraria devuelve las dos lambdas del
    partido IGUALES, que es la señal que delató el fallo entonces y la que
    comprueba `test_tarjetas_lambdas_distintas` ahora.

    Ventana 10, como en córners: cinco partidos de un equipo son una muestra de
    cinco y su propio ruido tapa la señal (la móvil de 5 midió 0,0227 contra
    0,0117 de esto).
    """
    d, _ = _serie_tarjetas(clave)
    if d is None:
        return None
    try:
        col_eq = 'home_team' if en_casa else 'away_team'
        col_riv = 'away_team' if en_casa else 'home_team'
        bando = 'home' if en_casa else 'away'
        serie = _tarjetas_de(d, bando)
        recibe = serie[d[col_eq] == equipo].dropna()
        provoca = serie[d[col_riv] == rival].dropna()
        if len(recibe) < MIN_PARTIDOS or len(provoca) < MIN_PARTIDOS:
            return None
        return round((float(recibe.tail(n).mean())
                      + float(provoca.tail(n).mean())) / 2.0, 3)
    except Exception as e:
        logger.debug('[rendimiento] lambda de tarjetas %s: %s', clave, e)
        return None


def tarjetas_equipo(clave: str, home: str, away: str, n: int = 10,
                    factor_arbitro: Optional[float] = None) -> Optional[Dict]:
    """
    Las tarjetas esperadas de los dos equipos y del partido, con la dispersión
    con la que convertirlas en probabilidades.

    `factor_arbitro` es el ajuste por el árbitro designado, ya encogido, tal y
    como lo devuelve `arbitro_partido.factor()`. Multiplica a los dos equipos
    por igual: lo que el árbitro cambia es cuánto se pita en el partido, y
    repartirlo asimétricamente exigiría un sesgo local medido que aquí no está
    (el `sesgo_local` de `referees.json` es de la tabla mundialista, otra cosa).
    Con `None` no se toca nada y sale el estimador desnudo.

    `None` cuando la competición no publica tarjetas observadas — 55 de las 75.
    """
    disp_eq = dispersion_tarjetas_equipo(clave)
    disp_tot = dispersion_tarjetas_liga(clave)
    if disp_eq is None or disp_tot is None:
        return None
    lh = lambda_tarjetas_equipo(clave, home, away, True, n)
    la = lambda_tarjetas_equipo(clave, away, home, False, n)
    if lh is None or la is None:
        return None
    f = 1.0
    if factor_arbitro is not None:
        try:
            f = float(factor_arbitro)
        except (TypeError, ValueError):
            f = 1.0
        if not (0.5 <= f <= 1.6):    # fuera de rango no se aplica, se ignora
            f = 1.0
    return {'lambda_home': round(lh * f, 3), 'lambda_away': round(la * f, 3),
            'lambda_total': round((lh + la) * f, 3),
            'dispersion': disp_eq, 'dispersion_total': disp_tot,
            'factor_arbitro': round(f, 4), 'clave_liga': clave}
