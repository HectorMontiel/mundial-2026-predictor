# -*- coding: utf-8 -*-
"""
v358 — NFL: HÁNDICAP Y PUNTOS (MÁS/MENOS) CON LAS LÍNEAS QUE PUBLICA PLAYDOIT.

El usuario: «quiero meter en la NFL hándicap, puntos más/menos y ganador, con
la misma metodología, para la pretemporada y la temporada oficial».

QUÉ PUBLICA PLAYDOIT (tableros del 10-oct, 15 de 15 partidos de la semana):
«Hándicap (incl. prórroga)» con escalera de ±11 puntos alrededor de la
principal y «Totales (incl. prórroga)» con ±11, todas en ,5 (nunca empate).
A ~75 % paga 1,20-1,30; a ~80 %, 1,15-1,20.

LO MEDIDO (`_v358_nfl_lineas.py`, nflverse 1999-2025 con el cierre de la
casa; `nfl_lineas.json`). Como en la NBA, lo que acierta una línea alternativa
depende de lo lejos que esté de la principal (k puntos). Se probaron dos
formas: por distancia k y por «vecinos» (partidos de hándicap parecido, que
respeta los números clave 3 y 7); con 1999-2006 → 2007-14 gana la distancia k
(Brier 0,182 contra 0,185), y vuelve a ganar al juzgar (0,176 contra 0,179).

LA REGLA. Por lado (favorito, no favorito, más, menos), la línea más lejana
—la de mejor cuota— que llegue a la meta (`_v358_nfl_variantes.py`):

    meta     elegir 2010-14     juzgar 2015-25        2026 (5 semanas)
    75 %     77,1 % (4/part.)   77,7 % (p5 77,0)      75,4 % (260)
    78 %     79,7 % (2,9)       80,5 % (p5 79,8)      78,0 % (195)
    80 %     80,3 % (1,1)       82,0 % (p5 81,1)      80,8 % (130)

Se mete con META_METER = 78 % (el ~80 % de la casa, como el resto de «se
mete»). Ninguna línea de la escalera llega al nivel de Capa 1 (~85 %), así que
la Capa 1 de la NFL sigue siendo el ganador (v350).

EL MODELO DE LA NFL NO SUMA: pedir que vea el partido del lado de la apuesta
da +1,6 pts al elegir y ±0 al juzgar (77,6 contra 77,7 %). Manda la casa, como
en la NBA y la MLB.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

import nba_lineas as _nb

logger = logging.getLogger('nfl_lineas')

FICHERO = 'nfl_lineas.json'
META_METER = 0.78
CUOTA_MIN = 1.15
CLAVE = 'nfl_playdoit'
# LA PRETEMPORADA (ESPN, `_v358_nfl_espn.py`: 2021-2026, 291 partidos con su
# línea; `nfl_lineas.json` → 'pretemporada'). Los titulares juegan poco: la
# casa se pasa con el favorito y se queda corta con los puntos. Con la regla
# del 78 %, en dos mitades:
#
#                       2021-23     2024-26
#     no favorito        82,1 %      82,2 %     (aguanta)
#     más de             85,5 %      87,0 %     (aguanta)
#     favorito           84,8 %      69,9 %     (no aguanta: fuera)
#
# («menos de» no llega al 78 % con la escalera.) Y el GANADOR en pretemporada
# no se mete: el favorito de la casa al 74 % o más ganó 5 de 11.
PRETEMPORADA_TIPOS: tuple = ('no_favorito', 'mas')
_CACHE: Dict = {}


def tablas() -> Dict:
    try:
        mt = os.path.getmtime(FICHERO)
    except OSError:
        return {}
    if _CACHE.get('mt') != mt:
        try:
            _CACHE.update(mt=mt, doc=json.load(open(FICHERO, encoding='utf-8')))
        except Exception as e:
            logger.debug('[nfl_lineas] %s', e)
            return {}
    return (_CACHE.get('doc') or {}).get('tablas') or {}


def prob(tipo: str, k: float) -> Optional[float]:
    """Lo que acierta la línea a k puntos de la principal (interpolado; por
    encima de la tabla no se extrapola)."""
    t = tablas().get(tipo) or {}
    if not t:
        return None
    pts = sorted((float(a), float(b)) for a, b in t.items())
    if k < pts[0][0]:
        return None
    if k >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= k <= x1:
            return y0 + (y1 - y0) * (k - x0) / (x1 - x0)
    return None


def apodo(nombre) -> Optional[str]:
    """El apodo, único en la NFL: «jaguars» de «Jacksonville Jaguars» y de
    «JAX Jaguars» (así escribe Playdoit)."""
    pal = str(nombre or '').strip().lower().split()
    return pal[-1] if pal else None


def del_tablero(det: Dict, home: str, away: str) -> Optional[Dict]:
    return _nb.del_tablero(det, home, away, apodo=apodo)


def candidatas(pick: Dict) -> List[Dict]:
    return _nb.candidatas(pick, CLAVE, prob)


def elegidas(pick: Dict, meta: float = META_METER,
             cuota_min: float = CUOTA_MIN) -> List[Dict]:
    return _nb.elegidas(pick, meta, cuota_min, CLAVE, prob)
