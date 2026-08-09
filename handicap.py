#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v106 — HÁNDICAP ASIÁTICO: el mercado que fallaba, y por qué.

El usuario reportó que el hándicap le falla «constantemente». No era una
impresión: la evaluación del hándicap en `alpha_finder._mercados_del_partido`
tenía tres agujeros, y los tres empujan en la MISMA dirección (inflar el lado
que se recomienda).

1. EL PUSH SE CONTABA COMO ACIERTO DEL LADO CONTRARIO
   ---------------------------------------------------
   El código aceptaba cualquier línea múltiplo de 0,5 —incluidas las ENTERAS
   (0, ±1, ±2)— y calculaba:

       p_local_cubre = P(margen > -L)
       p_visitante   = 1 - p_local_cubre        # <-- aquí

   Con L = −1 (local −1), `P(margen > 1)` es correcto para el local, pero el
   complemento `P(margen <= 1)` incluye `margen == 1`, que **no es una victoria
   del visitante: es un PUSH** (la casa devuelve la apuesta). En fútbol
   P(el local gana justo por 1) ronda el 20-25 %, así que el lado visitante
   salía con la probabilidad inflada en esos 20-25 puntos. Un pick de
   «Visitante +1» al 62 % real se publicaba al 85 %, y con esa cifra el EV
   salía positivo casi siempre. Eso es exactamente «me falla constantemente».

   El comentario del código decía «líneas .5 -> sin push», y era verdad de la
   intención pero no de la condición escrita, que dejaba pasar las enteras.
   El ledger de validación (`build_ledger_handicap.py`) sólo mide líneas .5,
   así que el caso roto nunca entró en la medición: por eso el hándicap
   figuraba como «el mercado mejor calibrado» mientras en producción fallaba.

2. LAS LÍNEAS DE CUARTO SE TIRABAN A LA BASURA
   -------------------------------------------
   `−0,25`, `−0,75`, `−1,25`... se descartaban enteras. Son las líneas más
   frecuentes en Pinnacle, que es justo la casa que se usa de ancla. Aquí se
   tratan como lo que son: media apuesta en cada línea de 0,5 adyacente.

3. EL HÁNDICAP NO SE ANCLABA AL MERCADO, EL 1X2 SÍ
   ------------------------------------------------
   Desde la v71 la probabilidad 1X2 se encoge hacia el mercado para corregir
   la maldición del ganador (el modelo infla entre +4 y +13 pp la selección
   que elige). Pero el hándicap se calculaba sobre la matriz de marcadores
   CRUDA, que no ve esa corrección: seguía cargando el sesgo completo.

   La matriz de marcadores ya nace re-ponderada a las marginales 1X2
   (`prediction_api._monte_carlo`), así que la corrección es la misma
   operación aplicada a las probabilidades ya encogidas — no un método nuevo:
   es el que valida `build_ledger_handicap.matriz_marcadores`.

Cómo se calcula ahora
---------------------
Toda apuesta asiática se descompone en (gana, pierde, push) por unidad
apostada, y de ahí salen las tres cifras que importan:

    prob. de ganar la apuesta = gana / (gana + pierde)     (condicional: el
                                push no es ni victoria ni derrota)
    cuota justa               = 1 / esa probabilidad
    EV                        = gana·(cuota − 1) − pierde

La fórmula del EV es la única correcta con push: `cuota·prob − 1` supone que
siempre se resuelve, y con línea entera eso sobreestima el EV en un factor
1/(gana+pierde).

Este módulo es PURO (sólo depende de numpy) para que se pueda medir y probar
sin arrancar la app.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Tolerancia con la que se decide si una línea cae en la rejilla de 0,25.
_EPS = 1e-6


# ---------------------------------------------------------------------------
# Distribución del margen
# ---------------------------------------------------------------------------
def distribucion_margen(matriz) -> Dict[int, float]:
    """
    Convierte la matriz de marcadores exactos en P(margen = goles_local −
    goles_visitante). El hándicap sólo depende del margen, así que trabajar
    aquí es más barato y más claro que arrastrar la matriz entera.
    """
    M = np.asarray(matriz, dtype=float)
    if M.ndim != 2 or M.size == 0:
        return {}
    n = M.shape[0]
    idx = np.arange(n)
    diff = idx[:, None] - idx[None, :]
    out: Dict[int, float] = {}
    for d in range(-(n - 1), n):
        masa = float(M[diff == d].sum())
        if masa > 0:
            out[d] = masa
    total = sum(out.values())
    if total > 0:
        out = {d: p / total for d, p in out.items()}
    return out


def reponderar_a_1x2(dist: Dict[int, float],
                     probs: Dict[str, float]) -> Dict[int, float]:
    """
    Re-escala la distribución de margen para que sus tres regiones (local gana
    / empate / visitante gana) sumen exactamente las probabilidades 1X2 que se
    le pasan — típicamente las YA encogidas hacia el mercado.

    Es la misma operación con la que se construye la matriz de marcadores
    (`prediction_api._monte_carlo`) y con la que se validó el hándicap
    (`build_ledger_handicap.matriz_marcadores`): se conserva la FORMA de la
    distribución dentro de cada región y se corrige su MASA. Sin esto el
    hándicap arrastra el sesgo de selección que el 1X2 ya tiene corregido.

    Si `probs` no trae las tres claves o no suman algo positivo, se devuelve la
    distribución intacta (degradación limpia: mejor sin corregir que roto).
    """
    if not dist:
        return dist
    try:
        ph = float(probs['home'])
        pd_ = float(probs['draw'])
        pa = float(probs['away'])
    except (KeyError, TypeError, ValueError):
        return dist
    s = ph + pd_ + pa
    if not np.isfinite(s) or s <= 0:
        return dist
    ph, pd_, pa = ph / s, pd_ / s, pa / s

    masa = {'home': sum(p for d, p in dist.items() if d > 0),
            'draw': sum(p for d, p in dist.items() if d == 0),
            'away': sum(p for d, p in dist.items() if d < 0)}
    objetivo = {'home': ph, 'draw': pd_, 'away': pa}

    out: Dict[int, float] = {}
    for d, p in dist.items():
        region = 'home' if d > 0 else ('draw' if d == 0 else 'away')
        m = masa[region]
        if m <= 1e-12:
            continue           # región vacía: no hay forma que preservar
        out[d] = p * objetivo[region] / m
    total = sum(out.values())
    return {d: p / total for d, p in out.items()} if total > 0 else dist


# ---------------------------------------------------------------------------
# Descomposición de una línea asiática
# ---------------------------------------------------------------------------
def partes_de_linea(linea: float) -> Optional[List[Tuple[float, float]]]:
    """
    Descompone una línea asiática en las mitades sobre las que realmente se
    juega, como [(línea, fracción del importe), ...].

      · 0,0 / ±0,5 / ±1,0 / ±1,5 ...  -> una sola parte
      · ±0,25 / ±0,75 / ±1,25 ...     -> media apuesta en cada línea de 0,5
                                          adyacente (−0,75 = mitad en −0,5 y
                                          mitad en −1,0)

    Devuelve None si la línea no cae en la rejilla de 0,25 (no es una línea
    asiática válida y no se debe inventar nada con ella).
    """
    try:
        L = float(linea)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(L):
        return None
    cuartos = round(L * 4)
    if abs(L * 4 - cuartos) > _EPS:
        return None
    if cuartos % 2 == 0:                     # múltiplo de 0,5
        return [(cuartos / 4.0, 1.0)]
    return [((cuartos - 1) / 4.0, 0.5), ((cuartos + 1) / 4.0, 0.5)]


def desglose(dist: Dict[int, float], linea: float) -> Optional[Dict[str, float]]:
    """
    Reparto del importe apostado para una línea asiática, visto desde el lado
    al que se le aplica esa línea (margen = goles de ESE lado − los del otro).

    Devuelve {'gana', 'pierde', 'push'}, que suman 1: la fracción del importe
    que se cobra, la que se pierde y la que se devuelve. None si la línea no
    es válida o no hay distribución.
    """
    if not dist:
        return None
    partes = partes_de_linea(linea)
    if partes is None:
        return None
    gana = pierde = push = 0.0
    for L, peso in partes:
        for d, p in dist.items():
            v = d + L
            if v > _EPS:
                gana += peso * p
            elif v < -_EPS:
                pierde += peso * p
            else:
                push += peso * p
    total = gana + pierde + push
    if total <= 0:
        return None
    return {'gana': gana / total, 'pierde': pierde / total,
            'push': push / total}


def probabilidad(dist: Dict[int, float], linea: float) -> Optional[float]:
    """
    Probabilidad de GANAR la apuesta, condicionada a que se resuelva
    (el push no cuenta ni a favor ni en contra). Es la cifra que hay que
    comparar contra la cuota: la casa también devuelve el importe en el push.
    """
    d = desglose(dist, linea)
    if not d:
        return None
    resuelve = d['gana'] + d['pierde']
    if resuelve <= 1e-12:
        return None                    # push seguro: no hay apuesta que medir
    return d['gana'] / resuelve


def cuota_justa(dist: Dict[int, float], linea: float) -> Optional[float]:
    """Cuota a la que la apuesta es neutra (EV = 0), con el push ya tenido en
    cuenta."""
    p = probabilidad(dist, linea)
    if not p or p <= 0:
        return None
    return 1.0 / p


def ev(dist: Dict[int, float], linea: float, cuota: float) -> Optional[float]:
    """
    Valor esperado por unidad apostada:

        EV = gana·(cuota − 1) − pierde

    Con push (líneas enteras y de cuarto) esto NO equivale a `cuota·prob − 1`:
    esa fórmula supone que la apuesta siempre se resuelve y exagera el EV.
    """
    d = desglose(dist, linea)
    if not d:
        return None
    try:
        c = float(cuota)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(c) or c <= 1:
        return None
    return d['gana'] * (c - 1.0) - d['pierde']


def etiqueta(equipo: str, linea: float) -> str:
    """«Rayados −1.25» / «Toluca +0.5». El signo se escribe con el menos
    tipográfico que ya usa el resto de la interfaz."""
    try:
        L = float(linea)
    except (TypeError, ValueError):
        return equipo
    if abs(L) < _EPS:
        return f'{equipo} 0'
    signo = '−' if L < 0 else '+'
    v = abs(L)
    txt = f'{v:.2f}'.rstrip('0').rstrip('.')
    return f'{equipo} {signo}{txt}'


def evaluar(matriz, linea_local: float, cuota_local: Optional[float],
            cuota_visitante: Optional[float],
            probs_1x2: Optional[Dict[str, float]] = None) -> List[Dict]:
    """
    Punto de entrada único: dada la matriz de marcadores, la línea que publica
    la casa (referida SIEMPRE al local, negativa = local favorito) y las dos
    cuotas, devuelve una entrada por lado con probabilidad condicional, cuota
    justa, EV correcto y el desglose de push.

    `probs_1x2` son las probabilidades 1X2 ya corregidas al mercado; si se
    pasan, la distribución de margen se re-pondera a ellas (ver
    `reponderar_a_1x2`). Es lo que alinea el hándicap con el 1X2 que se
    publica en la misma tarjeta.

    Devuelve [] si la línea no es válida: no se emite un mercado a medias.
    """
    dist = distribucion_margen(matriz)
    if not dist:
        return []
    if probs_1x2:
        dist = reponderar_a_1x2(dist, probs_1x2)
    if partes_de_linea(linea_local) is None:
        return []
    # la línea del visitante es la del local con el signo cambiado, y su margen
    # es el margen espejo
    dist_visit = {-d: p for d, p in dist.items()}

    salida = []
    for lado, d_lado, L, cuota in (('home', dist, linea_local, cuota_local),
                                   ('away', dist_visit, -float(linea_local),
                                    cuota_visitante)):
        des = desglose(d_lado, L)
        if not des:
            continue
        p = probabilidad(d_lado, L)
        if p is None:
            continue
        fila = {'lado': lado, 'linea': L, 'prob': p,
                'cuota_justa': 1.0 / p if p > 0 else None,
                'gana': des['gana'], 'pierde': des['pierde'],
                'push': des['push']}
        if cuota:
            e = ev(d_lado, L, cuota)
            if e is not None:
                fila['cuota'] = float(cuota)
                fila['ev'] = e
        salida.append(fila)
    return salida
