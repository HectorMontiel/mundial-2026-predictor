# -*- coding: utf-8 -*-
"""
v333 — EL MOTOR DE MERCADO: LOS GOLES QUE «CREE» LA CASA, Y CON ELLOS EL
PRECIO JUSTO DE TODO LO DEMÁS.

LA IDEA, NUEVA EN EL PROYECTO
Hasta aquí el precio justo salía de NUESTRO modelo. Aquí sale de la propia
casa: sus mercados PRINCIPALES (1X2 y más/menos 2,5) son los más trabajados
—ahí apuesta todo el mundo y ahí la corrigen los profesionales—; los
secundarios (otras líneas de goles, ambos marcan, doble oportunidad,
hándicap) los deriva de esos con fórmulas más toscas.

Se invierte el camino: de las probabilidades SIN MARGEN de los principales
se despejan las dos λ (goles esperados de local y de visita) de un Poisson
bivariado con la corrección de Dixon-Coles para los marcadores bajos
(0-0, 1-0, 0-1, 1-1). Con esas λ se calcula la probabilidad justa de
cualquier otro mercado. Si la casa paga un secundario por encima de lo que
sus PROPIOS principales dicen que vale, esa pata está mal puesta — y eso no
depende de una foto de Pinnacle de otra hora, porque sale de la misma foto.

Funciones puras, sin red. `lambdas(...)` despeja; `probabilidades(...)` da
el reparto de marcadores; `tabla` + `lote` lo hacen en lote.

LO MEDIDO (2026-10-06) — LA HERRAMIENTA ES BUENA, EL DINERO NO ESTÁ AHÍ
  · Pronostica mejor que el modelo propio en todo lo que deriva
    (`_v333_motor.py`, juicio de 24.724 partidos, log-loss):
        más de 1,5   0,5454 vs 0,5542 · más de 3,5   0,5815 vs 0,5925
        más de 2,5 sin cuota de goles   0,6692 vs 0,6807
    y en la franja 70-80 % cumple (menos de 3,5: dice 74,7 %, pasa 75,4 %).
  · Sus conjuntas calibran (`_v333_constructor.py`): gana favorito + más
    de 2,5 dice 30,6 %, pasa 30,8 %. Y mide la correlación del constructor:
    ×1,58 gana favorito + favorito 2+ goles, ×1,32 más de 1,5 + ambos
    marcan, ×1,20 gana favorito + más de 2,5, ×0,95 gana favorito + menos
    de 4,5.
  · PERO no encuentra patas sólidas mal puestas: en Novibet, lo que sus
    secundarios pagan «de más» frente a sus principales pierde (−2 a −20 %;
    sólidas ≥ 60 % +1,2 % con p5 −9,2; `_v333_novibet_interno.py`); y
    Playdoit frente a Pinnacle EN LA MISMA FOTO casi nunca se equivoca
    (50 errores en dos meses, todos a cuota 5-6; `_v333_playdoit_pinnacle.py`).
    Pinnacle sin margen calibra al punto (33,9 → 34,2 %; 36,6 → 36,6 %).
No lo usa la app todavía: es la base de una calculadora del constructor y
de promociones, que sólo tendría sentido con precios reales del constructor.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

MAXG = 11
RHO = -0.06          # v333 — se fija con el tramo de mirar (ver _v333_motor.py)
_G = np.arange(MAXG)


def _poisson(lam: float) -> np.ndarray:
    from math import exp, factorial
    return np.array([exp(-lam) * lam ** k / factorial(k) for k in range(MAXG)])


def matriz(lh: float, la: float, rho: float = RHO) -> np.ndarray:
    """P(goles local = i, goles visita = j) con Dixon-Coles."""
    m = np.outer(_poisson(lh), _poisson(la))
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def sin_margen(*cuotas) -> Optional[list]:
    try:
        inv = [1.0 / float(c) for c in cuotas]
    except Exception:
        return None
    if any(not np.isfinite(x) or x <= 0 for x in inv):
        return None
    s = sum(inv)
    return [x / s for x in inv]


def _resumen(m: np.ndarray) -> Tuple[float, float, float, float]:
    i, j = np.meshgrid(_G, _G, indexing='ij')
    return (m[i > j].sum(), m[i == j].sum(), m[i < j].sum(), m[(i + j) > 2.5].sum())


def lambdas(p1: float, px: float, p2: float, p_mas25: Optional[float] = None,
            rho: float = RHO) -> Optional[Tuple[float, float]]:
    """Las λ que mejor reproducen el 1X2 (y el más/menos 2,5 si lo hay)."""
    from scipy.optimize import least_squares
    if not all(np.isfinite([p1, px, p2])):
        return None

    def err(x):
        lh, la = np.exp(x)
        h, d, a, o = _resumen(matriz(lh, la, rho))
        e = [h - p1, d - px, a - p2]
        if p_mas25 is not None and np.isfinite(p_mas25):
            e.append(o - p_mas25)
        return e
    try:
        r = least_squares(err, x0=np.log([1.4, 1.1]), bounds=([-3, -3], [1.8, 1.8]))
    except Exception:
        return None
    lh, la = np.exp(r.x)
    return float(lh), float(la)


def probabilidades(lh: float, la: float, rho: float = RHO) -> Dict[str, float]:
    """Probabilidad justa de los mercados que derivan las casas."""
    m = matriz(lh, la, rho)
    i, j = np.meshgrid(_G, _G, indexing='ij')
    t = i + j
    out = {'Gana local': m[i > j].sum(), 'Empate': m[i == j].sum(),
           'Gana visita': m[i < j].sum()}
    out['Local o empate'] = out['Gana local'] + out['Empate']
    out['Visita o empate'] = out['Gana visita'] + out['Empate']
    out['Local o visita'] = out['Gana local'] + out['Gana visita']
    for L in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        out['Más de %s' % L] = m[t > L].sum()
        out['Menos de %s' % L] = m[t < L].sum()
    out['Ambos marcan sí'] = m[(i > 0) & (j > 0)].sum()
    out['Ambos marcan no'] = 1 - out['Ambos marcan sí']
    out['Local marca'] = m[i > 0].sum()
    out['Visita marca'] = m[j > 0].sum()
    for L in (0.5, 1.5, 2.5):
        out['Local más de %s' % L] = m[i > L].sum()
        out['Visita más de %s' % L] = m[j > L].sum()
    out['Local gana por 2+'] = m[(i - j) >= 2].sum()
    out['Visita gana por 2+'] = m[(j - i) >= 2].sum()
    return {k: float(v) for k, v in out.items()}


def handicap_ev(lh: float, la: float, linea: float, cuota_local: float,
                cuota_visita: float, rho: float = RHO) -> Tuple[float, float]:
    """Valor esperado por peso de cada lado de un hándicap asiático `linea`
    (para el local), con las devoluciones de las líneas enteras y las dos
    mitades de las de cuarto (−0,25, −0,75…)."""
    m = matriz(lh, la, rho)
    i, j = np.meshgrid(_G, _G, indexing='ij')
    cuarto = abs((linea * 4) % 2 - 1) < 1e-9
    partes = [linea - 0.25, linea + 0.25] if cuarto else [linea]
    ev_h = ev_a = 0.0
    for L in partes:
        d = (i - j) + L
        g, e, p = m[d > 0].sum(), m[np.abs(d) < 1e-9].sum(), m[d < 0].sum()
        ev_h += (g * cuota_local + e) / len(partes)
        ev_a += (p * cuota_visita + e) / len(partes)
    return float(ev_h - 1), float(ev_a - 1)


# ---------------------------------------------------------------------------
# v333 — EN LOTE: una tabla de λ cada 0,02 y búsqueda del vecino más cercano.
#
# `lambdas` resuelve un partido con mínimos cuadrados (lento: milisegundos que
# en 60 mil partidos son minutos). Para medir y para el precálculo se usa esta
# tabla: cada pareja de λ con su 1X2 y su más de 2,5 ya calculados, y un
# KD-tree en el espacio de probabilidades. El error de la rejilla es < 0,5 pts.
# ---------------------------------------------------------------------------
_TABLAS: Dict[float, dict] = {}
MERCADOS_LOTE = ('Gana local', 'Empate', 'Gana visita', 'Local o empate',
                 'Visita o empate', 'Local o visita', 'Más de 0.5', 'Menos de 0.5',
                 'Más de 1.5', 'Menos de 1.5', 'Más de 2.5', 'Menos de 2.5',
                 'Más de 3.5', 'Menos de 3.5', 'Más de 4.5', 'Menos de 4.5',
                 'Más de 5.5', 'Menos de 5.5', 'Ambos marcan sí', 'Ambos marcan no',
                 'Local marca', 'Visita marca', 'Local más de 1.5', 'Visita más de 1.5',
                 'Local gana por 2+', 'Visita gana por 2+')


def tabla(rho: float = RHO, paso: float = 0.02, maximo: float = 4.6) -> dict:
    if rho in _TABLAS:
        return _TABLAS[rho]
    from scipy.spatial import cKDTree
    from scipy.stats import poisson
    grid = np.arange(0.05, maximo, paso)
    LH, LA = np.meshgrid(grid, grid, indexing='ij')
    lh, la = LH.ravel(), LA.ravel()
    ph = poisson.pmf(_G[None, :], lh[:, None])          # (n, G)
    pa = poisson.pmf(_G[None, :], la[:, None])
    M = ph[:, :, None] * pa[:, None, :]                 # (n, G, G)
    M[:, 0, 0] *= 1 - lh * la * rho
    M[:, 0, 1] *= 1 + lh * rho
    M[:, 1, 0] *= 1 + la * rho
    M[:, 1, 1] *= 1 - rho
    M = np.clip(M, 0, None)
    M /= M.sum(axis=(1, 2), keepdims=True)
    i, j = np.meshgrid(_G, _G, indexing='ij')
    t = i + j

    def s(mask):
        return (M * mask[None]).sum(axis=(1, 2))
    P = {'Gana local': s(i > j), 'Empate': s(i == j), 'Gana visita': s(i < j)}
    P['Local o empate'] = P['Gana local'] + P['Empate']
    P['Visita o empate'] = P['Gana visita'] + P['Empate']
    P['Local o visita'] = P['Gana local'] + P['Gana visita']
    for L in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        P['Más de %s' % L] = s(t > L)
        P['Menos de %s' % L] = 1 - P['Más de %s' % L]
    P['Ambos marcan sí'] = s((i > 0) & (j > 0))
    P['Ambos marcan no'] = 1 - P['Ambos marcan sí']
    P['Local marca'], P['Visita marca'] = s(i > 0), s(j > 0)
    P['Local más de 1.5'], P['Visita más de 1.5'] = s(i > 1.5), s(j > 1.5)
    P['Local gana por 2+'], P['Visita gana por 2+'] = s((i - j) >= 2), s((j - i) >= 2)
    T = {'lh': lh, 'la': la, 'P': P, 'M': M,
         'kd3': cKDTree(np.c_[P['Gana local'], P['Gana visita'], P['Más de 2.5']]),
         'kd2': cKDTree(np.c_[P['Gana local'], P['Gana visita']])}
    _TABLAS[rho] = T
    return T


def lote(p1, p2, p_mas25=None, rho: float = RHO) -> np.ndarray:
    """Índice de la tabla para cada partido (con más de 2,5 si lo hay)."""
    T = tabla(rho)
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    idx = np.full(len(p1), -1)
    ok = np.isfinite(p1) & np.isfinite(p2)
    if p_mas25 is not None:
        po = np.asarray(p_mas25, float)
        con = ok & np.isfinite(po)
        if con.any():
            idx[con] = T['kd3'].query(np.c_[p1[con], p2[con], po[con]])[1]
        ok = ok & ~con
    if ok.any():
        idx[ok] = T['kd2'].query(np.c_[p1[ok], p2[ok]])[1]
    return idx
