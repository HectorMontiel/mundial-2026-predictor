#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v176 — PATRONES RECIENTES: LO QUE HA PASADO, NO LO QUE VA A PASAR.

Qué es esto
-----------
El encargo lo pide así: «crear una función que analice los últimos 10 partidos
de cada equipo y detecte patrones... ¿el equipo marca mucho o poco? ¿está en
racha de under/over? ¿saca muchos córners en casa? ¿es un equipo físico?».

Y esto es exactamente eso y NADA MÁS: un recuento de partidos observados. No
entra en la probabilidad, no toca la λ, no cambia una recomendación. La λ ya
escucha al histórico desde la v175 y con un peso MEDIDO (β 0,186 para el H2H y
0,255 para la forma, `_v175_h2h_en_la_lambda.py`); meter encima un segundo
canal sin medir sería contar la misma información dos veces, que es el error
que la v172 dejó escrito.

POR QUÉ 4 DE 5 Y NO 3 DE 5
---------------------------
El ejemplo del encargo decía «Under 2.5 en 3 de 5 últimos». Tres de cinco no es
un patrón: si el mercado fuera una moneda, **sacar 3 o más de 5 pasa el 50 % de
las veces**. Enseñarlo como hallazgo sería llenar la tarjeta de ruido con
aspecto de señal, que es justo lo que las últimas cinco versiones han ido
quitando. Con 4 de 5 la probabilidad por azar baja al 18,75 %, y con 5 de 5 al
3,1 %.

Es un umbral, no una ley: `MIN_RACHA` está en una constante y subirlo o bajarlo
es una línea. Lo que no se puede es llamar «patrón» a una moneda.

DE DÓNDE SALEN LOS NÚMEROS
--------------------------
Del histórico local de la competición (`rendimiento_equipos._historico`), que es
el mismo del que se entrenan los modelos y el que el pipeline nocturno
actualiza con cada jornada. Cero red. Se indexa una vez por competición —el
mismo patrón que `contexto_partido._indice_goles`, y por el mismo motivo: sin
índice, filtrar el histórico entero por equipo costaba 19 ms por partido.

LO QUE UN PATRÓN NO DICE
------------------------
Que se vaya a repetir. Un equipo con «+9,5 córners en 4 de 5» ha jugado cuatro
partidos abiertos, y eso es un hecho; que el quinto también lo sea es una
apuesta, y para eso está el resto de la aplicación. La tarjeta lo enseña en el
bloque de CONTEXTO, junto al H2H y la forma, que es donde vive lo observado.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger('patrones_equipo')

N_ULTIMOS = 5              # la ventana, la misma que la forma reciente
MIN_RACHA = 4              # 4 de 5: por azar, 18,75 %. Con 3 sería el 50 %.
MAX_POR_PARTIDO = 3        # tres líneas en la tarjeta, no un informe

# Las líneas contra las que se cuenta. Son las que la casa cotiza de verdad y
# las que el resto de la aplicación ya usa: 2,5 en goles es la línea de
# referencia de todo el proyecto, y 9,5 y 3,5 son las medianas de lo que
# Playdoit publica en córners y tarjetas.
LINEAS = (
    ('goles', 2.5, '⚽', 'goles'),
    ('corners', 9.5, '⛳', 'córners'),
    ('tarjetas', 3.5, '\U0001f7e8', 'tarjetas'),
)

_COLS = {'goles': ('home_goals', 'away_goals'),
         'corners': ('home_corners', 'away_corners'),
         'tarjetas': ('home_yellow', 'away_yellow')}

_INDICE: Dict[str, Dict] = {}


def _indice(clave_liga: str) -> Dict:
    """
    Los totales de cada partido de cada equipo, indexados UNA vez por liga.

    `{equipo: {'goles': [...], 'corners': [...], 'tarjetas': [...]}}`, en orden
    cronológico. Los `None` se conservan: una competición que no publica
    córners tiene que poder decir «no lo sé», no un cero.
    """
    ck = str(clave_liga or '')
    if ck in _INDICE:
        return _INDICE[ck]
    salida: Dict[str, Dict[str, List]] = {}
    try:
        import pandas as pd
        import rendimiento_equipos as rq
        d = rq._historico(ck)
        if d is None or getattr(d, 'empty', True):
            _INDICE[ck] = salida
            return salida
        d = d.sort_values('date')
        casa = d['home_team'].astype(str).to_numpy()
        fuera = d['away_team'].astype(str).to_numpy()
        series = {}
        for obj, (col_h, col_a) in _COLS.items():
            if col_h in d.columns and col_a in d.columns:
                series[obj] = (pd.to_numeric(d[col_h], errors='coerce')
                               + pd.to_numeric(d[col_a],
                                               errors='coerce')).to_numpy()
        for i, (h, a) in enumerate(zip(casa, fuera)):
            for equipo in (h, a):
                fila = salida.setdefault(equipo,
                                         {k: [] for k in _COLS})
                for obj in _COLS:
                    v = series.get(obj)
                    x = None if v is None else float(v[i])
                    fila[obj].append(None if x is None or x != x else x)
    except Exception as e:
        logger.debug('[patrones] índice de %s: %s', clave_liga, e)
    _INDICE[ck] = salida
    return salida


def olvidar() -> None:
    """Vacía el índice. Sólo lo usan los tests y el pipeline al reentrenar."""
    _INDICE.clear()


def _cuenta(valores: List, linea: float):
    """`(sobre, bajo, n)` de los valores válidos contra esa línea."""
    vistos = [v for v in valores if v is not None]
    if not vistos:
        return 0, 0, 0
    sobre = sum(1 for v in vistos if v > linea)
    return sobre, len(vistos) - sobre, len(vistos)


def de_equipo(clave_liga: str, equipo: str,
              n: int = N_ULTIMOS) -> List[Dict]:
    """
    Los patrones del equipo en sus últimos `n` partidos.

    Cada uno:

        {'objeto': 'goles', 'icono': '⚽', 'rotulo': 'goles',
         'lado': 'Under'|'Over', 'linea': 2.5, 'aciertos': 4, 'n': 5,
         'texto': 'Under 2.5 en 4 de 5'}

    Lista vacía cuando no hay racha que contar, y eso es lo normal: la mayoría
    de los equipos no tienen ningún patrón la mayoría de las semanas.
    """
    idx = _indice(clave_liga).get(str(equipo or ''))
    if not idx:
        return []
    salida = []
    for obj, linea, icono, rotulo in LINEAS:
        serie = (idx.get(obj) or [])[-int(n):]
        sobre, bajo, total = _cuenta(serie, linea)
        if total < MIN_RACHA:
            continue
        if sobre >= MIN_RACHA:
            lado, aciertos = 'Over', sobre
        elif bajo >= MIN_RACHA:
            lado, aciertos = 'Under', bajo
        else:
            continue
        salida.append({
            'objeto': obj, 'icono': icono, 'rotulo': rotulo, 'lado': lado,
            'linea': linea, 'aciertos': aciertos, 'n': total,
            'texto': '%s %s %s en %d de %d'
                     % (lado, ('%.1f' % linea).rstrip('0').rstrip('.'),
                        rotulo, aciertos, total)})
    # el patrón más marcado primero: 5 de 5 dice más que 4 de 5
    salida.sort(key=lambda p: (-p['aciertos'] / max(p['n'], 1), -p['aciertos']))
    return salida


def de_partido(clave_liga: str, home: str, away: str,
               tope: int = MAX_POR_PARTIDO) -> List[Dict]:
    """
    Los patrones de los dos equipos, mezclados y recortados a `tope`.

    Cada fila lleva su `equipo` para que la tarjeta pueda decir de quién es.
    Se alternan los dos bandos a propósito: si el local tiene tres patrones y
    el visitante uno, enseñar sólo los del local diría del partido menos que
    enseñar dos de cada.
    """
    por_bando = []
    for equipo in (home, away):
        if not equipo:
            continue
        por_bando.append([dict(p, equipo=equipo)
                          for p in de_equipo(clave_liga, equipo)])
    salida = []
    i = 0
    while len(salida) < int(tope) and any(len(b) > i for b in por_bando):
        for b in por_bando:
            if len(b) > i and len(salida) < int(tope):
                salida.append(b[i])
        i += 1
    return salida


def texto(clave_liga: str, home: str, away: str) -> List[str]:
    """Los patrones como líneas de texto ya montadas. Para los tests y el log."""
    return ['%s %s: %s' % (p['icono'], p['equipo'], p['texto'])
            for p in de_partido(clave_liga, home, away)]
