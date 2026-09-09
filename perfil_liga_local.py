#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v182 — CUANDO NO HAY MUESTRA EN LA COMPETICIÓN, SE MIRA SU LIGA.

QUÉ RESUELVE
------------
En una COPA los equipos vienen de ligas distintas y juegan pocos partidos, así
que la muestra por equipo es corta. En Champions: mediana 16 partidos, el 37 %
por debajo de 10, y **Viking FK, Sabah FK y Como con cero**. En la Libertadores,
la Sudamericana, la Leagues Cup o las dos UEFA restantes pasa lo mismo. Con menos de
`MIN_PARTIDOS`, `lambda_corners_equipo` y sus hermanas devuelven `None` y el
partido cae al estimador de la competición, que reparte el nivel medio entre los
dos bandos: dos equipos distintos acaban con el mismo número.

Y sí hay con qué: el Viking juega en Noruega y allí tiene cientos de partidos
con córners contados.

LO QUE SE MIDIÓ ANTES DE ENCHUFARLO
-----------------------------------
`_v182_mide_mezcla.py`, walk-forward sobre los 774 partidos de Champions con
estadísticas observadas (1.548 equipos-partido), comparando el error absoluto
medio:

                          córners   tarjetas   remates
    sólo Champions         2,4429    1,1362    2,2973
    mezcla con su liga     2,3618    1,1027    2,2187

Y donde de verdad importa, los equipos con menos de 5 partidos previos en la
competición (362 casos):

    córners  −6,20 %   ·   tarjetas  −5,11 %   ·   remates  −7,79 %

POR ESO SÓLO ACTÚA CUANDO FALTA MUESTRA, y no siempre. Con el equipo ya visto en
la competición, lo suyo manda: la mejora medida está en la cola, no en el centro,
y tocar lo que ya funciona sería cambiar un estimador validado por una corazonada.

EL FACTOR DE COMPETICIÓN
------------------------
Un equipo no hace lo mismo en una copa que en su liga. Medido copa por copa en
`factor_competicion.json` (`_v182_factor_competicion.py`):

    competición          córners  tarjetas  sh_on  sh_off   n equipos
    champions             0,8195   0,9990  0,8434  0,8836      56
    europa_league         0,8798   1,0781  0,9056  0,9080      77
    conference_league     0,8907   1,0349  1,0113  0,9663      54
    libertadores          0,8889   1,0615  0,9428  0,9753      67
    sudamericana          0,9368   1,0515  1,0125  1,0003      98
    leagues_cup           0,9297   0,9047  1,0474  0,9368      48
    bra_copa              1,0237   1,0321  1,0617  1,0623      23
    eng_fa_cup            1,1489   0,7153  1,1414  1,0616      14  <- no se usa
    afc_champions         0,8994   1,1311  0,7591  0,8368      17  <- no se usa

El patrón se repite en las copas continentales: **menos córners (0,88-0,94) y
más tarjetas (1,03-1,08)** que en la liga de origen. Partidos más cerrados y más
tensos, que es lo que uno esperaría, medido.

Las dos últimas quedan en 1,0 —no corregir— por `MIN_EQUIPOS_FACTOR`: con 14 y
17 equipos el factor es ruido. La FA Cup da justo el patrón invertido del resto,
que es lo que produce una muestra corta llena de cruces entre categorías
distintas.

**Un factor único por copa, no uno por liga de origen**, y sigue medido: la
dispersión entre ligas (sd 0,08-0,18) es menor que entre equipos (sd 0,14-0,34)
en todas. El nivel de la liga explica menos que el propio equipo.

Y el de Champions **corrige a la v179**, que con 30 equipos midió 1,076 en
tarjetas: con 56 el efecto desaparece (0,9990).

DE DÓNDE SALE LA LIGA DE CADA EQUIPO
------------------------------------
De `catalogo_equipos`, que la mira en vez de adivinarla. Sin él, esto le daría a
la Juventus los córners del Juventude brasileño y no se notaría.
"""
import io
import json
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger('perfil_liga_local')

FICHERO_FACTOR = os.environ.get('FACTOR_COMPETICION', 'factor_competicion.json')

# Con menos de esto en la competición, se mira la liga. Es el mismo umbral que
# usa `rendimiento_equipos.MIN_PARTIDOS` para dar una serie por buena.
MIN_PARTIDOS = 3

# v183 — DONDE APLICA SALE DEL PROPIO FICHERO DE FACTORES.
#
# Aplica a las COPAS: competiciones donde los equipos vienen de ligas distintas
# y juegan pocos partidos. Una liga doméstica no lo necesita —sus equipos juegan
# ahí toda la temporada— y mirarles otro histórico sería un error.
#
# La lista era fija y se quedaba corta sola. Ahora son las competiciones que
# tienen factor medido, y eso se cumple exactamente cuando la copa publica
# estadísticas observadas — que es también la condición para que el estimador
# por equipo pueda usarse. Medidas hoy: champions, europa_league,
# conference_league, libertadores, sudamericana, leagues_cup, bra_copa,
# eng_fa_cup y afc_champions.
COMPETICIONES_RESPALDO = ('champions', 'europa_league', 'conference_league',
                          'afc_champions', 'libertadores', 'sudamericana')

# Con menos equipos que esto, el factor es ruido y no se aplica: se deja 1,0.
# La FA Cup lo midió con 14 equipos y dio 0,7153 en tarjetas y 1,1489 en
# córners —el patrón invertido del resto de copas—, que es justo lo que hace
# una muestra corta llena de cruces entre equipos de categorías distintas.
MIN_EQUIPOS_FACTOR = 20

_FACTORES: Optional[dict] = None


def _factores() -> dict:
    global _FACTORES
    if _FACTORES is not None:
        return _FACTORES
    doc = {}
    try:
        with io.open(FICHERO_FACTOR, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        logger.debug('[perfil] sin %s (%s): factor 1,0', FICHERO_FACTOR, e)
    _FACTORES = doc if isinstance(doc, dict) else {}
    return _FACTORES


def factor(competicion: str, stat: str) -> float:
    """
    Cuánto de lo que hace un equipo en su liga se traslada a la competición.

    Devuelve 1,0 cuando no está medido, que es la hipótesis nula honesta: sin
    dato, no se corrige nada. Nunca inventa un ajuste.
    """
    d = ((_factores().get(str(competicion)) or {}).get(str(stat)) or {})
    try:
        v = float(d.get('factor'))
    except (TypeError, ValueError):
        return 1.0
    # Muestra corta: se prefiere no corregir a corregir mal.
    try:
        if int(d.get('n_equipos') or 0) < MIN_EQUIPOS_FACTOR:
            return 1.0
    except (TypeError, ValueError):
        return 1.0
    # Un factor absurdo es un error de medición, no un descubrimiento.
    return v if 0.3 <= v <= 3.0 else 1.0


def aplica(competicion: str) -> bool:
    """Si esta competición es una copa con factor medido."""
    medidas = _factores()
    if medidas:
        return str(competicion) in medidas
    return str(competicion) in COMPETICIONES_RESPALDO


def serie_de_su_liga(equipo: str, competicion: str, stat: str, en_casa: bool,
                     n: int = 10, papel: str = 'hace'):
    """
    La serie del equipo en SU liga, ya escalada al nivel de la competición.

    `papel` distingue las dos series que estos estimadores necesitan:

      'hace'    lo que el equipo produce en su bando (córners que saca,
                remates que tira, tarjetas que recibe)
      'concede' lo que el rival deja en el bando contrario

    Devuelve `None` —y no una serie vacía— cuando no hay liga, no hay fichero o
    no hay filas: quien llama distingue «no aplica» de «cero».
    """
    if not aplica(competicion):
        return None
    try:
        import catalogo_equipos as ce
        destino = ce.nombre_en_su_liga(equipo)
    except Exception as e:
        logger.debug('[perfil] catálogo no disponible: %s', e)
        return None
    if not destino:
        return None
    clave_liga, nombre = destino
    if clave_liga == competicion:
        return None
    try:
        import pandas as pd
        import rendimiento_equipos as rq
        d = rq._solo_reales(rq._historico(clave_liga), stat)
        if d is None or getattr(d, 'empty', True):
            return None
        # El bando se conserva: lo que un equipo hace en casa y fuera son dos
        # cosas distintas, y el partido que se predice tiene bandos asignados.
        lado = 'home' if en_casa else 'away'
        col_valor = '%s_%s' % (lado, stat)
        col_equipo = ('%s_team' % lado) if papel == 'hace' else (
            '%s_team' % ('away' if en_casa else 'home'))
        if col_valor not in d.columns or col_equipo not in d.columns:
            return None
        s = pd.to_numeric(d.loc[d[col_equipo] == nombre, col_valor],
                          errors='coerce').dropna()
        if s.empty:
            return None
        return s.tail(n) * factor(competicion, stat)
    except Exception as e:
        logger.debug('[perfil] serie de %s en %s: %s', equipo, clave_liga, e)
        return None


def completar(serie, equipo: str, competicion: str, stat: str, en_casa: bool,
              n: int = 10, papel: str = 'hace') -> Tuple[object, bool]:
    """
    `(serie, se_completó)`. Sólo mira la liga si la serie se queda corta.

    No mezcla las dos cuando la de la competición ya vale: la mejora medida
    está en los equipos con poca muestra, y en los demás el estimador actual
    está validado sobre 30.454 equipos-partido. Se completa por detrás, así que
    lo propio de la competición sigue siendo lo último que se mira.
    """
    try:
        n_actual = 0 if serie is None else len(serie)
    except TypeError:
        n_actual = 0
    if n_actual >= MIN_PARTIDOS:
        return serie, False
    extra = serie_de_su_liga(equipo, competicion, stat, en_casa, n, papel)
    if extra is None or len(extra) == 0:
        return serie, False
    try:
        import pandas as pd
        junta = pd.concat([extra, serie]) if n_actual else extra
        logger.info('[perfil] %s: %d partidos en %s, se completa con su liga '
                    '(%d filas de %s)', equipo, n_actual, competicion,
                    len(extra), stat)
        return junta, True
    except Exception as e:
        logger.debug('[perfil] no se pudo completar %s: %s', equipo, e)
        return serie, False


def olvidar() -> None:
    """Vacía la caché de factores. Lo usan los tests."""
    global _FACTORES
    _FACTORES = None
