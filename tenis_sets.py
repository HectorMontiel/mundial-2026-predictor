#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v194 — EL PRIMER SET Y EL TOTAL DE SETS, MEDIDOS SOBRE 544.692 PARTIDOS.

DE DÓNDE SALEN LOS DATOS, PORQUE LA PRIMERA RESPUESTA FUE QUE NO EXISTÍAN
-------------------------------------------------------------------------
Al pedirse estos mercados se dijo que el histórico guardaba el resultado del
partido y no el marcador por sets. **Era falso**, y conviene dejarlo escrito:
`historico_itf.csv.gz` trae una columna `Score` con el marcador completo
—«6-2 6-1»— en 566.860 partidos, y de ahí sale todo.

Una trampa que casi cuesta el modelo: **el marcador está escrito siempre desde
la perspectiva del GANADOR**. Medido, el lado izquierdo gana el partido el
100,00 % de las veces. Leerlo como si fuera del jugador 1 daba «quien gana el
primer set gana el partido: 0,4993», una moneda al aire, cuando la cifra real
es 0,8467.

LO QUE SE MIDIÓ
---------------
Sobre 397.702 partidos al mejor de tres con ranking de los dos jugadores,
agrupados por diferencia de ranking (que es lo parejo que es el partido):

    gap (log)      n        P(fav gana)   P(fav 1er set)   P(3 sets)
    0,00-0,25   109.719        0,5395         0,5340         0,3448
    0,50-0,75    77.503        0,6896         0,6553         0,3127
    1,00-1,50    43.219        0,8057         0,7550         0,2611
    2,00-3,00     2.297        0,8890         0,8293         0,1937

Las dos relaciones son monótonas y casi rectas. **Ajustadas con el 70 % más
antiguo del calendario y validadas con el 30 % reciente (119.311 partidos):**

    1er set:  P = 0,8700 · p + 0,0586    error de -0,0072 a +0,0078
    3 sets :  P = -0,4157 · p + 0,5852   error de  ±0,015

El primer set calibra muy bien salvo en el tramo por encima de 0,88, donde la
muestra de validación son 687 partidos y el error sube a +0,027. Se dice y no
se esconde.

POR QUÉ NO VALE LA FÓRMULA OBVIA
---------------------------------
La tentación era: P(1er set) = p·K + (1-p)·(1-K) con K = 0,8467, la frecuencia
global de que el ganador se lleve el primer set. **Subestima al favorito de
forma sistemática y el error crece con la ventaja** (-0,007 con partidos
parejos, -0,060 con favoritos claros), porque K no es constante: un favorito
dominante que gana lo hace más veces en dos sets. La recta ajustada no tiene
ese sesgo.

QUÉ SE PUEDE JUGAR Y QUÉ NO
----------------------------
Playdoit publica **«Primer set - ganador»** con precio, así que ese mercado
lleva EV medible como cualquier otro. **El total de SETS no lo publica** —da
total de JUEGOS, que es otra cosa—, así que su probabilidad se calcula y se
enseña, pero sin EV: no hay precio contra el que medirla.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger('tenis_sets')

# Ajustadas con el 70 % antiguo de `historico_itf.csv.gz` y validadas con el
# 30 % reciente. Ver el encabezado.
A1, B1 = 0.8700, 0.0586        # P(gana el 1er set) desde P(gana el partido)
A3, B3 = -0.4157, 0.5852       # P(el partido va a 3 sets)

# Por encima de esto la validación sólo tenía 687 partidos y el error subía a
# +0,027. No se prohíbe, se marca.
P_MUESTRA_CORTA = 0.88


def prob_primer_set(p_partido: float) -> Optional[float]:
    """
    P(gana el PRIMER SET) de quien tiene `p_partido` de ganar el partido.

    Siempre está más cerca de 0,5 que la del partido, y tiene que ser así: un
    set es una muestra más pequeña que un partido al mejor de tres.
    """
    try:
        p = float(p_partido)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        return None
    return round(min(max(A1 * p + B1, 0.01), 0.99), 4)


def prob_tres_sets(p_partido: float) -> Optional[float]:
    """P(el partido llega al tercer set), al mejor de tres."""
    try:
        p = float(p_partido)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        return None
    # se mira desde el FAVORITO: el tercer set no distingue quién gana
    fav = max(p, 1.0 - p)
    return round(min(max(A3 * fav + B3, 0.01), 0.99), 4)


def muestra_corta(p_partido: float) -> bool:
    """Si el pronóstico cae donde la validación tenía poca muestra."""
    try:
        return max(float(p_partido), 1.0 - float(p_partido)) > P_MUESTRA_CORTA
    except (TypeError, ValueError):
        return False


def mercados(p_home: float, home: str, away: str) -> Dict:
    """
    Los dos mercados derivados, con su probabilidad.

    No lleva cuota: quien la tenga la añade. Esto sólo sabe de probabilidades.
    """
    ph = prob_primer_set(p_home)
    pa = prob_primer_set(1.0 - p_home) if p_home is not None else None
    p3 = prob_tres_sets(p_home)
    salida = {}
    if ph is not None and pa is not None:
        # LAS DOS SE NORMALIZAN. Cada una sale de su propia recta, y dos rectas
        # independientes no tienen por qué sumar 1: con p=0,5 dan 0,4936 cada
        # una y con p=0,9 dan 0,8416 y 0,1456, que suma 0,9872. Publicar dos
        # probabilidades de un mercado de dos salidas que no suman 1 es dar un
        # número que no es una probabilidad.
        s = ph + pa
        if s > 0:
            ph, pa = round(ph / s, 4), round(pa / s, 4)
        salida['primer_set'] = {'Gana el 1er set %s' % home: ph,
                                'Gana el 1er set %s' % away: pa}
    if p3 is not None:
        salida['sets'] = {'Más de 2.5 sets': p3, 'Menos de 2.5 sets':
                          round(1.0 - p3, 4)}
    if salida:
        salida['muestra_corta'] = muestra_corta(p_home)
    return salida
