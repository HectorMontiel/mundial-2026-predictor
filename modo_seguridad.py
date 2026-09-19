#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v212 — Modo Seguridad: «Apuestas Seguras del Día».

QUÉ ES, Y EN QUÉ SE DIFERENCIA DE LA SECCIÓN 1
----------------------------------------------
La Sección 1 busca VALOR: sitios donde una casa paga por encima del precio
justo del mercado. Es el único canal del proyecto con percentil 5 positivo
(+1,73 %), y no se toca.

Esto busca otra cosa: picks donde el modelo y el mercado DICEN LO MISMO, con
probabilidad alta y cuota corta pero no ridícula. No es la misma apuesta ni el
mismo criterio, y por eso va en su propia sección en vez de mezclarse.

LA DIFERENCIA CON EL ANTI-INDICADOR, QUE ES LA PREGUNTA OBVIA
-------------------------------------------------------------
Este proyecto tiene medido que elegir por EV sobre la probabilidad del modelo
pierde (−4,66 % a −6,52 % sobre 37.158 apuestas). Conviene decir por qué esto
NO es lo mismo, porque se parece:

    EV del modelo    busca donde el modelo DISCREPA del mercado y la cuota
                     paga más de lo que el modelo cree. Premia la discrepancia.
    Modo Seguridad   exige que el modelo COINCIDA con el mercado (|Δ| <= 8 pp).
                     Penaliza la discrepancia.

Son criterios opuestos sobre el mismo eje. Que el primero pierda no implica que
el segundo gane: implica que hay que medirlo, y por eso este módulo no se
enciende solo. `ACTIVO` lo fija `backtest_v212.py` y arranca en False.

LO QUE ESTE MÓDULO NO PROMETE
-----------------------------
Ganar dinero. Un filtro que selecciona favoritos a cuota corta y alineados con
el mercado está, por construcción, comprando el consenso con el margen de la
casa encima. El resultado esperado a priori es negativo y la única pregunta
que importa es CUÁNTO, y si el p5 de bootstrap llega a cero. Eso lo contesta
el backtest, no este docstring.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger('modo_seguridad')

# ---------------------------------------------------------------------------
# Los criterios del encargo, literales
# ---------------------------------------------------------------------------
PROB_MINIMA = 0.60
CUOTA_MINIMA = 1.30
CUOTA_MAXIMA = 1.90
ALINEACION_MAXIMA = 0.08        # |prob_modelo − prob_mercado|

# Filtros duros
EV_MINIMO = -0.08
DIVERGENCIA_MAXIMA = 0.15
RATIO_INFLADA_MAXIMO = 1.30
FACTOR_RIESGO_ALTO = 1.5
CUOTA_MINIMA_RIESGO = 1.80
CUOTA_SUELO_ABSOLUTO = 1.20

TOP_SEGURAS = 5                 # «Apuestas Seguras del Día»
TOP_COMPLEMENTOS = 15           # hasta aquí, «Complementos»
MAX_POR_PARTIDO = 2

# Pesos del score de solidez, tal y como los fija el encargo.
W_PROB, W_ALINEACION, W_CUOTA, W_RIESGO = 0.45, 0.30, 0.15, 0.10

# ---------------------------------------------------------------------------
# LA PUERTA DE ACTIVACIÓN
# ---------------------------------------------------------------------------
# No se enciende a mano. `backtest_v212.py` escribe este fichero con el
# veredicto de los cuatro criterios (Brier, p5, hit rate, ROI) y este módulo
# lo lee. Sin fichero, apagado: un motor sin medición no sale a pantalla.
FICHERO_ACTIVACION = 'activacion_v212.json'
_ACTIVACION: Optional[Dict] = None


def _cargar_activacion(recargar: bool = False) -> Dict:
    global _ACTIVACION
    if _ACTIVACION is not None and not recargar:
        return _ACTIVACION
    _ACTIVACION = {}
    try:
        if os.path.exists(FICHERO_ACTIVACION):
            with open(FICHERO_ACTIVACION, encoding='utf-8') as f:
                _ACTIVACION = json.load(f) or {}
    except Exception as e:
        logger.warning('[seguridad] no se pudo leer la activación: %s', e)
        _ACTIVACION = {}
    return _ACTIVACION


def activo(regla: str = 'modo_seguridad') -> bool:
    """¿Pasó esta regla los cuatro criterios del backtest?

    Sin fichero de activación devuelve False. Es deliberado: el estado por
    defecto de una regla sin medir es APAGADA, no encendida.
    """
    e = (_cargar_activacion().get('reglas') or {}).get(regla) or {}
    return bool(e.get('activa'))


def motivo_estado(regla: str = 'modo_seguridad') -> str:
    """Por qué está encendida o apagada, en texto llano."""
    doc = _cargar_activacion()
    if not doc:
        return ('sin backtest todavía: se enciende sola cuando '
                '`backtest_v212.py` la valide')
    e = (doc.get('reglas') or {}).get(regla) or {}
    if not e:
        return f'la regla `{regla}` no aparece en el backtest'
    return str(e.get('motivo') or '')


# ---------------------------------------------------------------------------
# El núcleo, PURO: mismas cuentas en producción y en el backtest
# ---------------------------------------------------------------------------
def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def normalizar_cuota(cuota: Optional[float], lo: float = CUOTA_MINIMA,
                     hi: float = CUOTA_MAXIMA) -> float:
    """La cuota dentro de la banda, llevada a 0-1. Fuera de banda, recortada."""
    c = _f(cuota)
    if c is None or hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (c - lo) / (hi - lo)))


def solidez(prob_modelo: Optional[float], prob_mercado: Optional[float],
            cuota: Optional[float], factor_riesgo: float = 1.3) -> float:
    """El score del encargo. 0 si falta cualquiera de las tres entradas.

    El factor de riesgo se normaliza sobre la escala real que usa el proyecto
    (1,0 a 1,8), no sobre 0-1: con la escala cruda, una liga de factor 1,0
    aportaba 0,10 y una de 1,8 aportaba −0,08, que es un premio negativo y
    desordenaba el ranking.
    """
    p, pm, c = _f(prob_modelo), _f(prob_mercado), _f(cuota)
    if p is None or pm is None or c is None:
        return 0.0
    riesgo_norm = max(0.0, min(1.0, (float(factor_riesgo) - 1.0) / 0.8))
    return round(
        W_PROB * p
        + W_ALINEACION * (1.0 - abs(p - pm))
        + W_CUOTA * normalizar_cuota(c)
        + W_RIESGO * (1.0 - riesgo_norm), 4)


def evaluar(prob_modelo: Optional[float], prob_mercado: Optional[float],
            cuota: Optional[float], factor_riesgo: float = 1.3,
            alta_incertidumbre: bool = False,
            ev: Optional[float] = None) -> Dict:
    """¿Entra este pick en Modo Seguridad? Con el motivo si no.

    ES LA FUNCIÓN QUE MIDE EL BACKTEST. La ruta de producción y la de
    validación llaman a ésta, no a dos copias: si divergen, el backtest deja
    de decir nada sobre lo que el usuario ve.
    """
    p, pm, c = _f(prob_modelo), _f(prob_mercado), _f(cuota)
    fuera = {'entra': False, 'solidez': 0.0}

    if p is None or c is None:
        return {**fuera, 'motivo': 'sin probabilidad o sin cuota'}
    if pm is None:
        return {**fuera, 'motivo': 'sin precio de mercado con el que alinear'}

    # --- criterios de entrada (los tres) -----------------------------------
    if p < PROB_MINIMA:
        return {**fuera, 'motivo': f'probabilidad {p:.0%} por debajo del '
                                   f'{PROB_MINIMA:.0%}'}
    if not (CUOTA_MINIMA <= c <= CUOTA_MAXIMA):
        return {**fuera, 'motivo': f'cuota {c:.2f} fuera de la banda '
                                   f'{CUOTA_MINIMA:.2f}-{CUOTA_MAXIMA:.2f}'}
    alineacion = abs(p - pm)
    if alineacion > ALINEACION_MAXIMA:
        return {**fuera, 'motivo': f'el modelo se separa {alineacion*100:.0f} '
                                   f'puntos del mercado (máximo '
                                   f'{ALINEACION_MAXIMA*100:.0f})'}

    # --- filtros duros ------------------------------------------------------
    if alta_incertidumbre:
        return {**fuera, 'motivo': '🔴 Alta incertidumbre (Brier ≥ 0,22)'}
    if c < CUOTA_SUELO_ABSOLUTO:
        return {**fuera, 'motivo': f'cuota por debajo de {CUOTA_SUELO_ABSOLUTO}'}
    e = _f(ev)
    if e is None:
        e = p * c - 1.0
    if e < EV_MINIMO:
        return {**fuera, 'motivo': f'EV {e*100:+.1f} % por debajo del '
                                   f'{EV_MINIMO*100:+.0f} %'}
    if alineacion > DIVERGENCIA_MAXIMA:
        return {**fuera, 'motivo': 'divergencia extrema con el mercado'}
    justa = 1.0 / p if p > 0 else None
    if justa and c / justa > RATIO_INFLADA_MAXIMO:
        return {**fuera, 'motivo': f'cuota inflada ({c/justa:.2f}× la justa)'}
    if factor_riesgo > FACTOR_RIESGO_ALTO and c < CUOTA_MINIMA_RIESGO:
        return {**fuera, 'motivo': f'competición de alto riesgo y cuota '
                                   f'{c:.2f} < {CUOTA_MINIMA_RIESGO}'}

    return {'entra': True, 'motivo': '',
            'solidez': solidez(p, pm, c, factor_riesgo),
            'alineacion': round(alineacion, 4),
            'ev': round(e, 4)}


# ---------------------------------------------------------------------------
# La ruta de producción
# ---------------------------------------------------------------------------
def _prob_mercado(pick: Dict) -> Optional[float]:
    try:
        import auditoria_pick as ap
        return ap.probabilidad_mercado(pick)
    except Exception as e:
        logger.debug('[seguridad] prob de mercado: %s', e)
        return None


def evaluar_pick(pick: Dict) -> Dict:
    """Evalúa un pick del barrido reutilizando la capa de auditoría."""
    p = dict(pick or {})
    try:
        import auditoria_pick as ap
        ficha = ap.auditar(p, con_contexto=False)
        factor = float(ficha.get('factor_riesgo_liga') or 1.3)
        incierto = bool(ficha.get('alta_incertidumbre'))
    except Exception as e:
        logger.debug('[seguridad] auditoría: %s', e)
        ficha, factor, incierto = {}, 1.3, False

    r = evaluar(p.get('prob'), _prob_mercado(p), p.get('cuota'),
                factor_riesgo=factor, alta_incertidumbre=incierto,
                ev=p.get('ev'))
    return {**r, 'pick': p, 'auditoria': ficha}


def seleccionar(picks: Sequence[Dict]) -> Dict:
    """La sección entera: top 5 seguras, 6-15 complementos, y lo descartado.

    El tope de dos patas por partido se aplica DESPUÉS de ordenar por solidez,
    para que de un partido sobrevivan sus dos mejores y no las dos primeras que
    llegaron.
    """
    dentro, fuera = [], []
    for p in list(picks or []):
        if not isinstance(p, dict):
            continue
        try:
            r = evaluar_pick(p)
        except Exception as e:
            logger.warning('[seguridad] pick descartado por error: %s', e)
            continue
        (dentro if r['entra'] else fuera).append(r)

    dentro.sort(key=lambda r: -r['solidez'])
    try:
        import auditoria_pick as ap
        ordenados = ap.patas_compatibles([r['pick'] for r in dentro],
                                         max_por_partido=MAX_POR_PARTIDO)
        permitidos = {id(x) for x in ordenados}
        dentro = [r for r in dentro if id(r['pick']) in permitidos]
    except Exception as e:
        logger.debug('[seguridad] correlación: %s', e)

    return {'seguras': dentro[:TOP_SEGURAS],
            'complementos': dentro[TOP_SEGURAS:TOP_COMPLEMENTOS],
            'descartadas': fuera,
            'n_dentro': len(dentro),
            'activo': activo(),
            'motivo_estado': motivo_estado()}


def explicar(resultado: Dict) -> str:
    """Una línea por pick seguro, para el resumen de texto y el bot."""
    lineas = []
    for r in (resultado or {}).get('seguras', []):
        p = r['pick']
        lineas.append(
            f"{p.get('apuesta', '?')} · {p.get('partido', '?')} "
            f"@ {p.get('cuota', '?')} — solidez {r['solidez']:.3f}, "
            f"{(p.get('prob') or 0)*100:.0f} % del modelo contra el mercado "
            f"a {abs(r.get('alineacion', 0))*100:.0f} puntos")
    return '\n'.join(lineas)


if __name__ == '__main__':
    print('activo:', activo(), '·', motivo_estado())
    demo = [
        {'partido': 'A vs B', 'apuesta': 'Gana A', 'prob': 0.68,
         'cuota': 1.55, 'cuota_justa': 1.50, 'clave_liga': 'premier'},
        {'partido': 'C vs D', 'apuesta': 'Gana C', 'prob': 0.52,
         'cuota': 1.70, 'cuota_justa': 1.75, 'clave_liga': 'premier'},
    ]
    for r in seleccionar(demo)['seguras']:
        print(' ', r['pick']['apuesta'], r['solidez'])
