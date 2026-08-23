#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — QUÉ MERCADO PUEDE LLEVAR INSIGNIA Y CUÁL NO.

El problema, medido
-------------------
La tarjeta pinta una insignia «🟡 destacado: …» en cada bloque físico con la
fila de mayor probabilidad de ESE bloque. Medido sobre el barrido del
2026-08-23 (`_v164_auditar_destacada.py`), de 624 bloques pintados **232 eran
ESTIMADOS** y todos llevaban su insignia, anunciando hasta un 68 %. Y en **58
partidos TODOS** sus bloques eran estimados: Danubio-Racing de Montevideo,
Sonderjyske-Nordsjaelland, Monagas-Portuguesa…

Un bloque estimado no sabe nada de ESE partido. Es el nivel de la competición
derivado de sus goles, repartido por bando, **idéntico en todos los partidos de
esa liga** — su propia etiqueta lo dice. Anunciarlo como «destacado» le da la
forma de una recomendación a un número que no distingue un partido de otro.

Los tres niveles
----------------
    1. observado y error de calibración < 0,02   -> puede llevar insignia
    2. observado y error entre 0,02 y 0,05       -> insignia con matiz
    3. estimado, o sin datos                      -> NUNCA insignia

El error sale de `_v162_calibracion_por_liga.json`, que genera
`informe_calibracion.py` midiendo cada competición contra la frecuencia real en
las líneas que cotiza la casa. Reparto actual sobre 61 competiciones:

    córners     37 medidas · 32 por debajo de 0,02 ·  5 entre 0,02 y 0,05
    tarjetas    38 medidas · 26 por debajo de 0,02 · 12 entre 0,02 y 0,05
    remates     37 medidas · 26 por debajo de 0,02 · 11 entre 0,02 y 0,05
    a puerta    37 medidas · 28 por debajo de 0,02 ·  9 entre 0,02 y 0,05

**Ninguna competición OBSERVADA pasa de 0,05**, así que el nivel 3 es
exactamente «lo estimado». Los dos umbrales no se solapan con la realidad por
casualidad: son los que se fijaron al cerrar córners y tarjetas.

LO QUE ESTE MÓDULO NO HACE: PONER NADA EN VERDE
-----------------------------------------------
El nivel 1 permite insignia, y la insignia sigue siendo ÁMBAR. En esta
aplicación el verde significa una cosa concreta y medida —«canal con percentil
5 de bootstrap positivo en tramo de juicio» (§0 de la bitácora)— y córners,
tarjetas y remates no lo tienen: no hay histórico de líneas con el que
calcularlo, que es justo lo que `snapshots_*.py` está acumulando.

Calibración y ventaja de precio son dos ejes distintos. Que una probabilidad
valga lo que dice no implica que la casa la esté pagando mal. Subir estos
bloques a verde por estar bien calibrados diría lo segundo enseñando lo
primero, así que el nivel 1 se queda en ámbar y lo que cambia es que el nivel 3
deja de tener insignia.

Siete competiciones tienen datos observados pero muestra corta y no llegan a
tener error medido. Ésas van al nivel 2, no al 3: sus datos son reales, sólo
que todavía no se sabe cuánto valen. Decir «no hay datos» de una liga que los
tiene sería el error contrario al que este módulo arregla.
"""
import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger('confianza_mercado')

INFORME = '_v162_calibracion_por_liga.json'

# Los dos umbrales del proyecto. El de 0,05 es el que fijó la v162 como
# «aceptable» para una estimación; el de 0,02 es el que pidió el usuario para
# separar lo bien calibrado de lo que sólo está calibrado.
UMBRAL_FINO = 0.02
UMBRAL_ACEPTABLE = 0.05

# nombre del bloque en la tarjeta -> clave del informe
MERCADOS = {'corners': 'corners', 'tarjetas': 'tarjetas',
            'remates': 'remates', 'remates_on': 'remates_on',
            'a_puerta': 'remates_on', 'totales': 'remates'}

NIVEL_FINO = 1
NIVEL_GRUESO = 2
NIVEL_SIN_INSIGNIA = 3

_CACHE: Optional[Dict] = None


def _informe() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    datos: Dict = {}
    try:
        if os.path.exists(INFORME):
            with open(INFORME, encoding='utf-8') as f:
                doc = json.load(f) or {}
            for lg in (doc.get('ligas') or []):
                clave = lg.get('clave')
                if clave:
                    datos[clave] = lg
    except Exception as e:
        logger.debug('[confianza] no se pudo leer %s: %s', INFORME, e)
    _CACHE = datos
    return _CACHE


def error_medido(clave_liga: str, mercado: str) -> Optional[float]:
    """
    El error de calibración medido de ese mercado en esa competición.

    `None` cuando la competición no está en el informe o su muestra no dio para
    medirlo. `None` NO es cero y no se trata como tal: quien llama lo manda al
    nivel 2, no al 1.
    """
    campo = MERCADOS.get(mercado, mercado)
    lg = _informe().get(str(clave_liga)) or {}
    bloque = lg.get(campo) or {}
    if (bloque.get('origen') or '') != 'observado':
        return None
    v = (bloque.get('por_equipo') or {}).get('error_calib')
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v >= 0.0 else None


def nivel(clave_liga: str, mercado: str,
          origen: Optional[str] = None) -> Dict:
    """
    En qué nivel de confianza cae este mercado para esta competición.

    `origen` es lo que dice el propio bloque (`'observado'` / `'estimado'`), y
    MANDA sobre el informe: el bloque sabe de dónde salieron SUS números hoy,
    mientras que el informe es una foto de cuando se generó. Si el bloque dice
    que es estimado, es estimado, aunque el informe tenga a esa liga medida.

    Devuelve `{'nivel', 'insignia', 'error', 'motivo'}`.
    """
    if (origen or 'observado') == 'estimado':
        return {'nivel': NIVEL_SIN_INSIGNIA, 'insignia': False, 'error': None,
                'motivo': 'estimado'}
    err = error_medido(clave_liga, mercado)
    if err is None:
        return {'nivel': NIVEL_GRUESO, 'insignia': True, 'error': None,
                'motivo': 'observado sin error medido'}
    if err < UMBRAL_FINO:
        return {'nivel': NIVEL_FINO, 'insignia': True, 'error': err,
                'motivo': 'observado y bien calibrado'}
    if err <= UMBRAL_ACEPTABLE:
        return {'nivel': NIVEL_GRUESO, 'insignia': True, 'error': err,
                'motivo': 'observado, calibración aceptable'}
    return {'nivel': NIVEL_SIN_INSIGNIA, 'insignia': False, 'error': err,
            'motivo': 'observado pero mal calibrado'}


def puede_destacar(clave_liga: str, mercado: str,
                   origen: Optional[str] = None) -> bool:
    """Atajo: ¿este mercado puede llevar insignia de destacado?"""
    return bool(nivel(clave_liga, mercado, origen).get('insignia'))


def etiqueta(info: Dict) -> str:
    """
    El texto que acompaña a la insignia, o cadena vacía si no la lleva.

    El nivel 1 no dice nada: es el caso corriente y una etiqueta que sale
    siempre no informa (misma lección que el umbral del verde en la v153.1).
    El nivel 2 sí, porque ahí el número vale menos y hay que poder saberlo.
    """
    if info.get('nivel') != NIVEL_GRUESO:
        return ''
    err = info.get('error')
    if err is None:
        return 'calibración sin medir'
    return 'calibración %.3f' % err


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    claves = sys.argv[1:] or sorted(_informe())
    print('%-22s %-12s %-6s %-9s %s'
          % ('competición', 'mercado', 'nivel', 'error', 'motivo'))
    print('-' * 74)
    for c in claves:
        for m in ('corners', 'tarjetas', 'remates', 'remates_on'):
            n = nivel(c, m)
            print('%-22s %-12s %-6d %-9s %s'
                  % (c, m, n['nivel'],
                     ('%.4f' % n['error']) if n['error'] is not None else '-',
                     n['motivo']))
