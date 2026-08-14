#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v136 — La calculadora de combinadas: dice el EV real, no uno inventado.

LA ARITMÉTICA, PRIMERO
----------------------
    EV_combinada = Π(1 + EVᵢ) − 1

De ahí sale todo lo demás, y lo que sale es incómodo:

    3 patas al −4,76 %  →  −13,62 %
    3 patas al +4,50 %  →  +14,12 %

Combinar NO arregla una pata mala: multiplica su margen. Por eso el encargo
original —«que la app sugiera un parlay con EV positivo combinando picks de la
Sección 2»— no se puede cumplir: todos los picks de la Sección 2 tienen EV
negativo o sin medir, que es precisamente lo que los puso ahí. Cualquier
producto de números menores que 1 sigue siendo menor que 1.

Lo que sí se puede hacer, y es lo que hace este módulo, es **calcular el EV de
verdad y decirlo**, sea positivo o negativo, antes de que nadie confirme nada.

LA REGLA DE LA PATA DE RELLENO
------------------------------
Se parte SIEMPRE de una pata de la Sección 1 —la única con ventaja de precio
medida— y se admite como mucho UNA de la Sección 2, y sólo por encima de
`PROB_MINIMA_RELLENO`. El caso que justifica esa excepción es inflar la cuota
sin hundir la probabilidad conjunta; cada pata de relleno EMPEORA el EV del
boleto, así que va contada y avisada, no mezclada sin más.

Es la misma regla que ya implementa `clasificador.ids_para_parlay`; aquí se
añade lo que faltaba: enseñar el número.
"""
import math
from typing import Dict, List, Optional

# Probabilidad mínima para que una pata de la Sección 2 pueda entrar de
# relleno. Por debajo, lo que se hace es cambiar una cuota mayor por una
# probabilidad conjunta que se desploma.
PROB_MINIMA_RELLENO = 0.85

# Cuántas patas de relleno se admiten. Uno. Ver el encabezado.
MAX_RELLENO = 1


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def ev_combinada(patas: List[Dict]) -> Optional[float]:
    """
    `Π(1 + EVᵢ) − 1` sobre las patas que traigan EV.

    Devuelve None si alguna pata no tiene EV: con un hueco, el producto no
    significa nada y publicar un número incompleto sería peor que no publicarlo.
    """
    if not patas:
        return None
    prod = 1.0
    for p in patas:
        ev = _f(p.get('ev'))
        if ev is None:
            return None
        prod *= (1.0 + ev)
    return round(prod - 1.0, 4)


def cuota_combinada(patas: List[Dict]) -> Optional[float]:
    """El producto de las cuotas. None si a alguna le falta el precio."""
    if not patas:
        return None
    prod = 1.0
    for p in patas:
        c = _f(p.get('cuota'))
        if not c or c <= 1:
            return None
        prod *= c
    return round(prod, 4)


def prob_conjunta(patas: List[Dict]) -> Optional[float]:
    """
    Producto de las probabilidades — **suponiendo independencia**.

    Ese supuesto NO es gratis y hay que decirlo donde se enseñe: dos patas del
    mismo partido están correlacionadas y el producto se queda corto o largo
    según el signo de la correlación. Para patas de partidos distintos es una
    aproximación razonable; para el mismo partido, no.
    """
    if not patas:
        return None
    prod = 1.0
    for p in patas:
        pr = _f(p.get('prob'))
        if pr is None or not (0 < pr <= 1):
            return None
        prod *= pr
    return round(prod, 4)


def mismo_partido(patas: List[Dict]) -> bool:
    """¿Hay dos patas del mismo encuentro? Entonces no son independientes."""
    vistos = set()
    for p in patas:
        k = (str(p.get('deporte') or ''), str(p.get('partido') or ''))
        if k in vistos:
            return True
        vistos.add(k)
    return False


def evaluar(base: Optional[Dict], relleno: Optional[List[Dict]] = None) -> Dict:
    """
    El veredicto de un boleto, con su número y su motivo en texto llano.

    `base` tiene que salir de la Sección 1. `relleno` son patas de la Sección 2,
    y sólo se admite `MAX_RELLENO`.
    """
    relleno = [x for x in (relleno or []) if x]
    if not base:
        return {'ok': False, 'ev': None,
                'motivo': 'Una combinada empieza por una pata con ventaja de '
                          'precio medida. Elige primero algo de la Sección 1: '
                          'sin eso, el boleto sólo multiplica el margen de la '
                          'casa.'}
    avisos: List[str] = []
    if len(relleno) > MAX_RELLENO:
        avisos.append(
            f'Se han elegido {len(relleno)} patas de relleno y sólo se admite '
            f'{MAX_RELLENO}. Cada una empeora el valor del boleto: '
            f'EV = Π(1+EVᵢ)−1, así que multiplican el margen en vez de '
            f'repartirlo.')
        relleno = relleno[:MAX_RELLENO]
    flojas = [x for x in relleno
              if (_f(x.get('prob')) or 0) < PROB_MINIMA_RELLENO]
    for x in flojas:
        avisos.append(
            f"«{x.get('apuesta', '?')}» va al "
            f"{(_f(x.get('prob')) or 0)*100:.0f} % y el mínimo para rellenar "
            f"es {PROB_MINIMA_RELLENO*100:.0f} %: por debajo, la cuota sube "
            f"menos de lo que baja la probabilidad conjunta.")

    patas = [base] + relleno
    ev = ev_combinada(patas)
    cuota = cuota_combinada(patas)
    prob = prob_conjunta(patas)
    correlacionadas = mismo_partido(patas)
    if correlacionadas:
        avisos.append(
            'Hay dos patas del MISMO partido: no son sucesos independientes, '
            'así que la probabilidad conjunta que sale del producto no es de '
            'fiar. Tómala como orientación, no como cifra.')

    ev_base = _f(base.get('ev'))
    salida = {'ok': ev is not None and ev > 0, 'ev': ev, 'cuota': cuota,
              'prob': prob, 'n_patas': len(patas), 'avisos': avisos,
              'correlacionadas': correlacionadas, 'ev_base': ev_base}
    if ev is None:
        salida['motivo'] = ('Alguna pata no tiene EV calculable —le falta el '
                            'precio o la probabilidad—, así que el valor del '
                            'boleto no se puede calcular. No se enseña un '
                            'número a medias.')
        salida['ok'] = False
        return salida
    if ev > 0:
        salida['motivo'] = (
            f'El boleto tiene un EV de {ev*100:+.2f} %'
            + (f' a cuota {cuota:.2f}' if cuota else '')
            + '. Es positivo, que con combinadas es lo raro.')
        if ev_base is not None and relleno and ev < ev_base:
            salida['motivo'] += (
                f' Aun así, la pata sola daba {ev_base*100:+.2f} %: el relleno '
                f'te ha costado {(ev_base - ev)*100:.2f} puntos.')
    else:
        salida['motivo'] = (
            f'El boleto tiene un EV de {ev*100:+.2f} %'
            + (f' a cuota {cuota:.2f}' if cuota else '')
            + '. **No lo juegues**: a la larga pierde.')
        if ev_base is not None and ev_base > 0 and relleno:
            salida['motivo'] += (
                f' La pata de la Sección 1 sola daba {ev_base*100:+.2f} %; '
                f'añadir el relleno la ha convertido en negativa. Eso es lo '
                f'que hace combinar una pata sin valor.')
    return salida


def texto_formula(patas: List[Dict]) -> str:
    """La cuenta escrita, para que el número no haya que creérselo."""
    trozos = []
    for p in patas or []:
        ev = _f(p.get('ev'))
        trozos.append('(1 ' + (f'{ev:+.4f}' if ev is not None else '+ ?') + ')')
    return ' × '.join(trozos) + ' − 1' if trozos else ''
