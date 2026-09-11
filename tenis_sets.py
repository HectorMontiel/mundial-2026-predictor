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

# v194.1 — HAY QUE SEPARAR POR NIVEL, Y SE COMPROBO MIDIENDO.
#
# La primera version ajusto una sola recta sobre TODO el archivo, que es en su
# mayoria ITF, y la aplico a los partidos de ATP y WTA que enseña la app. Al
# contrastarla por nivel de torneo salio esto:
#
#                 1er set (dif)        3 sets (dif)
#     ITF          -0,003 .. +0,003    +0,017 .. -0,006
#     Challenger   -0,006 .. +0,012    -0,010 .. -0,033
#     Grand Slam   +0,003 .. +0,015    -0,034 .. -0,055
#
# **La del primer set transfiere; la del tercer set NO.** En torneos de nivel
# alto se llega al tercer set bastante mas a menudo —hasta 5,5 puntos mas— de
# lo que predice la recta de ITF. Tiene sentido: arriba los partidos son mas
# competitivos aunque el ranking diga otra cosa.
#
# Y los partidos que enseña la app son ATP y WTA, o sea el nivel donde peor
# iba. Asi que hay dos juegos de coeficientes, cada uno ajustado con el 70 %
# antiguo de SU nivel y validado con el 30 % reciente:
#
#     ALTO (challenger + Grand Slam, n=99.431)
#         3 sets  peor desvio 0,0287   ·   1er set  peor desvio 0,0075
#     ITF (n=298.271)
#         3 sets  peor desvio 0,0200   ·   1er set  peor desvio 0,0068
#
# El tercer set calibra peor que el primero en los dos niveles, y eso se dice:
# casi 3 puntos de desvio en el peor tramo del nivel alto.
NIVELES = {
    'alto': {'A1': 0.8505, 'B1': 0.0675, 'A3': -0.3790, 'B3': 0.5848},
    'itf': {'A1': 0.8595, 'B1': 0.0663, 'A3': -0.3863, 'B3': 0.5598},
}
# Por defecto el nivel alto: es lo que la app enseña (ATP y WTA). Elegir mal
# por defecto cuesta hasta 2,5 puntos en el total de sets.
NIVEL_POR_DEFECTO = 'alto'


def _coef(nivel=None):
    return NIVELES.get(str(nivel or NIVEL_POR_DEFECTO).lower(),
                       NIVELES[NIVEL_POR_DEFECTO])


def nivel_de(liga=None, torneo=None) -> str:
    """`itf` si el partido es de circuito ITF; `alto` en lo demas."""
    texto = ('%s %s' % (liga or '', torneo or '')).lower()
    if 'itf' in texto or texto.strip().startswith(('m15', 'w15', 'm25', 'w25')):
        return 'itf'
    return 'alto'


# Se conservan por compatibilidad: son los del nivel por defecto.
A1, B1 = NIVELES['alto']['A1'], NIVELES['alto']['B1']
A3, B3 = NIVELES['alto']['A3'], NIVELES['alto']['B3']

# Por encima de esto la validación sólo tenía 687 partidos y el error subía a
# +0,027. No se prohíbe, se marca.
P_MUESTRA_CORTA = 0.88


def prob_primer_set(p_partido: float, nivel=None) -> Optional[float]:
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
    c = _coef(nivel)
    return round(min(max(c['A1'] * p + c['B1'], 0.01), 0.99), 4)


def prob_tres_sets(p_partido: float, nivel=None) -> Optional[float]:
    """P(el partido llega al tercer set), al mejor de tres."""
    try:
        p = float(p_partido)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        return None
    # se mira desde el FAVORITO: el tercer set no distingue quién gana
    fav = max(p, 1.0 - p)
    c = _coef(nivel)
    return round(min(max(c['A3'] * fav + c['B3'], 0.01), 0.99), 4)


def muestra_corta(p_partido: float) -> bool:
    """Si el pronóstico cae donde la validación tenía poca muestra."""
    try:
        return max(float(p_partido), 1.0 - float(p_partido)) > P_MUESTRA_CORTA
    except (TypeError, ValueError):
        return False


def mercados(p_home: float, home: str, away: str, nivel=None) -> Dict:
    """
    Los dos mercados derivados, con su probabilidad.

    No lleva cuota: quien la tenga la añade. Esto sólo sabe de probabilidades.
    """
    ph = prob_primer_set(p_home, nivel)
    pa = (prob_primer_set(1.0 - p_home, nivel)
          if p_home is not None else None)
    p3 = prob_tres_sets(p_home, nivel)
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
