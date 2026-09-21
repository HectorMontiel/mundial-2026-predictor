# -*- coding: utf-8 -*-
"""
v297 — LA COMBINADA DEL MISMO PARTIDO. Dos patas, una sola apuesta.

DE DONDE SALE
El usuario enseñó su boleto de Draftea y pidió que la Escalera hiciera eso:

    Gana local      1,21
    Más de 2,5      1,27
    COMBINADA       1,44

    «Si armas una combinada segura eso ayuda bastante a llegar al banco...
     tiene que ser una combinada probablemente del mismo partido.»
    «Sólo se va a poner en la escalera una sola de ésas y puede haber varias
     en el mismo día. Lo importante es multiplicar el banco, que sólo sea una
     apuesta, que sea lo más probable y que tenga buena cuota.»

POR QUE ESTO SI FUNCIONA CUANDO CASI NADA MAS FUNCIONA
Porque la casa arma la combinada MULTIPLICANDO las dos cuotas, y eso supone
que las dos patas son independientes. No lo son: si el local gana, es porque
ha metido goles, así que «gana el local» y «más de 2,5» van de la mano.
Medido sobre 17.420 partidos con las dos cuotas reales:

    gana el local                0,4320
    más de 2,5                   0,5142
    multiplicando las dos        0,2221   <- lo que supone el precio
    LAS DOS DE VERDAD            0,2631   <- lo que pasa
                                 +18,4 % relativo

Ese 18,4 % es la ventaja, y es estructural: no depende de acertar nada, sólo
de que la casa cobre la combinada como si fueran independientes.

MEDIDO, CON LA PATA DEL 1X2 SALIENDO DE CAPA 1 (n = 1.710)

                        entra     ROI        p5
    elección (70 %)    28,6 %  +11,11 %   +2,35 %
    juicio   (30 %)    34,1 %  +22,74 %   +8,61 %

Las dos puertas, las dos con p5 positivo. Y aguanta lo que suele tumbar a
estas cosas:

    por año        2024 +5,89 % · 2025 +23,34 % (p5 +11,52)
    sin la mejor liga (esp_hypermotion)   +10,96 %  p5 +3,05 %
    quitando las 20 combinadas más gordas +7,29 %
    sólo combinadas hasta 6,00            +13,22 %  p5 +5,68 %

Y SOBRE TODO: LE GANA A JUGAR LA PATA SOLA

    la combinada   ROI +14,60 %  p5 +7,26 %  entra 30,2 %
    sólo el 1X2    ROI  +7,46 %  p5 +3,08 %  entra 51,1 %
    mejora +7,14 pp (p5 +1,34) — gana en el 97,8 % de los remuestreos

EL PRECIO, QUE HAY QUE DECIRLO
Entra el 30,2 % de las veces contra el 51,1 % de la pata sola. Paga más y
entra menos, así que las rachas malas son más largas. Para una escalera eso
importa: se dobla más rápido cuando entra y se tarda más en que entre.

LO QUE NO SE PUEDE HACER
Córners y tarjetas NO, y no es por pereza: Pinnacle no los publica —se
revisaron sus 506 tipos de mercado especial— así que no hay precio de
referencia con el que saber si la casa se equivoca. Sin ancla sharp no hay
canal, sólo una corazonada con dos patas. Ambos-marcan tampoco: el feed
sólo trae ancla en 9 de cada 521 partidos.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# El regalo de la correlacion: cuanto sube la probabilidad conjunta REAL por
# encima de multiplicar las dos patas. Medido POR LADO, porque no son lo mismo.
#
# NO se tocan sin volver a medir: es literalmente de donde sale la ventaja. Si
# alguna vez bajan de 1,0 la combinada pasa a ser una trampa y hay que apagarla.
#
#   local + mas de 2,5      n=17.420   0,2631 contra 0,2221   +18,4 %
#   visitante + mas de 2,5  n=13.012   0,1831 contra 0,1576   +16,2 %
CORRELACION = 1.184            # local
CORRELACION_VISITANTE = 1.162

# v297.3 — EL VISITANTE TAMBIEN, Y NO ES UN AÑADIDO DE CORTESIA.
#
# El usuario enseño un boleto ganador con el Dila Gori y el CSKA Sofia II, los
# dos VISITANTES, en los dos partidos donde la Capa 1 recomendaba al local
# (Spaeri perdio 1-4, Dobrudzha perdio 1-3). Al medirlo, su lado rinde MAS:
#
#   canal              eleccion              juicio
#   local           +6,81 % (p5 +1,58)   +10,67 % (p5 +2,79)
#   visitante       +7,55 % (p5 +1,03)   +13,14 % (p5 +2,50)   n=1.326
#
# y la combinada por ese lado, con la pata de Capa 1:
#
#   eleccion  n=884  entra 28,1 %  ROI +21,62 %  p5 +10,27 %
#   juicio    n=379  entra 26,6 %  ROI +21,11 %  p5  +3,39 %

# Cuota minima de la COMBINADA. El usuario la puso: «puede ser una cuota
# arriba de 1,5». Aqui si vale, al reves que en el 1X2 suelto —donde la banda
# 1,50-1,80 es la unica que pierde— porque una combinada a 1,50 son dos patas
# de ~1,22 cada una, que es otra cosa completamente distinta.
CUOTA_MINIMA = 1.50

# Y un techo, porque a partir de ahi ya no es «lo mas probable» sino una
# soñadora con dos patas, y para eso esta la seccion de Soñadoras.
CUOTA_MAXIMA = 6.00

# Probabilidad conjunta minima. Entra el 30 % de las veces de media; por
# debajo de esto ya no sirve para ir doblando un banco.
PROB_MINIMA = 0.22


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def conjunta(p1: float, p2: float, lado: str = 'home') -> float:
    """La probabilidad REAL de que entren las dos, con la correlacion dentro.

    No es `p1 * p2`: eso es lo que supone la casa y es justo su error. Se
    limita a `min(p1, p2)` porque ninguna conjunta puede pasar de la pata mas
    floja, y la correccion podria empujarla por encima en casos extremos.
    """
    a, b = _num(p1), _num(p2)
    if a is None or b is None or not (0 < a <= 1 and 0 < b <= 1):
        return 0.0
    k = CORRELACION_VISITANTE if str(lado) == 'away' else CORRELACION
    return min(a * b * k, a, b)


def de_pick(pick: Dict) -> Optional[Dict]:
    """La combinada de ese pick de Capa 1, si su partido la admite.

    El pick tiene que traer `over25` puesto por el barrido: la cuota del más
    de 2,5 del MISMO partido y en la MISMA casa. Sin eso no hay combinada que
    armar, y no se inventa una con el precio de otra casa: el usuario tiene
    que poder meter las dos patas en un solo boleto.

    NUNCA lanza; devuelve None cuando no sale.
    """
    try:
        if not isinstance(pick, dict):
            return None
        # v297.1 — `combi` trae las dos patas de UNA MISMA casa, que es lo
        # unico con lo que se puede llenar un boleto. `over25` a secas es el
        # caso facil: la casa que gana el line shopping ya tenia el 2,5.
        combi = pick.get('combi') or {}
        if combi:
            ou = combi.get('over25') or {}
            cu_1x2 = _num(combi.get('cuota_1x2'))
            p_1x2 = _num(combi.get('prob_1x2'))
            casa = combi.get('casa')
        else:
            ou = pick.get('over25') or {}
            cu_1x2 = _num(pick.get('cuota'))
            p_1x2 = _num(pick.get('prob'))
            casa = pick.get('casa')
            if p_1x2 is None:
                ev = _num(pick.get('ev'))
                if ev is not None and cu_1x2:
                    p_1x2 = (1.0 + ev) / cu_1x2
        cu_ov = _num(ou.get('cuota'))
        p_ov = _num(ou.get('prob'))
        if None in (cu_ov, p_ov, cu_1x2, p_1x2):
            return None

        cuota = round(cu_1x2 * cu_ov, 2)
        if not (CUOTA_MINIMA <= cuota <= CUOTA_MAXIMA):
            return None
        prob = conjunta(p_1x2, p_ov, pick.get('lado'))
        if prob < PROB_MINIMA:
            return None
        ev = prob * cuota - 1.0
        if ev <= 0:
            return None

        q = dict(pick)
        q.update({
            'mercado': 'Combinada',
            'apuesta': '%s  +  Más de 2.5 goles' % pick.get('apuesta', '?'),
            'cuota': cuota,
            'prob': round(prob, 4),
            'ev': round(ev, 4),
            'cuota_justa': round(1.0 / prob, 3) if prob else None,
            'casa': casa,
            'patas': [
                {'texto': pick.get('apuesta', '?'), 'cuota': cu_1x2,
                 'prob': round(p_1x2, 4)},
                {'texto': 'Más de 2.5 goles', 'cuota': cu_ov,
                 'prob': round(p_ov, 4)},
            ],
            'origen': 'combinada del mismo partido (correlación medida)',
            'nota_canal': (
                'Dos patas del mismo partido en un solo boleto. La casa la '
                'cobra multiplicando las dos cuotas, como si fueran '
                'independientes, y no lo son: si el local gana suele haber '
                'goles. Medido en 17.420 partidos, las dos entran juntas un '
                '18,4 % más de lo que supone ese precio.'),
        })
        return q
    except Exception as e:
        logger.debug('[combinada] %s', e)
        return None


def todas(picks: List[Dict], tope: int = 6) -> List[Dict]:
    """Las combinadas que salen hoy, de más a menos probable. NUNCA lanza.

    Una por partido, que es lo que el usuario pidió («sólo sea una apuesta»).
    """
    fuera, vistos = [], set()
    try:
        for p in (picks or []):
            c = de_pick(p)
            if not c:
                continue
            k = str(c.get('partido'))
            if k in vistos:
                continue
            vistos.add(k)
            fuera.append(c)
        fuera.sort(key=lambda x: (-(x.get('prob') or 0), -(x.get('ev') or 0)))
    except Exception as e:
        logger.debug('[combinada] todas: %s', e)
    return fuera[:tope]


def resumen(c: Optional[Dict], banco: float = 100.0) -> str:
    """Una línea para la tarjeta."""
    if not isinstance(c, dict):
        return 'Hoy no sale ninguna combinada con las dos patas en la misma casa.'
    try:
        cu = float(c.get('cuota') or 0)
        pr = float(c.get('prob') or 0)
        return ('Pones %.0f y si entran las dos cobras %.0f. Entra %.0f de '
                'cada 100 veces.' % (banco, banco * cu, 100 * pr))
    except (TypeError, ValueError):
        return ''
