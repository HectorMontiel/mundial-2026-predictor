#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v231 — la correlacion EN LA MATRIZ, que es donde vive el problema de verdad.

QUE SE INTENTA ARREGLAR
-----------------------
Todo lo medido hasta ahora apunta a una sola causa. La matriz de marcador sale
de multiplicar dos Poisson independientes, y los goles de los dos equipos NO
son independientes: el marcador cambia como se juega. De ahi salen TRES
sintomas que se han ido parcheando por separado:

    ambos marcan   infravalorado en 44 de 55 ligas, mediana -4,3 pp
    empates        infravalorado -1,4 pp global, -3,5 en partidos abiertos
    Under          +15,7 pp en lambda baja, -8,2 pp en lambda alta

La v230 corrigio el BTTS con una isotonica por liga —medido y desplegado— pero
eso es un parche sobre el sintoma: pone bien el numero sin arreglar el modelo,
y no toca ni los empates ni el 1X2.

LA BIVARIADA DE POISSON
-----------------------
La forma limpia de meter correlacion sin inventarse nada:

    X = X1 + X3      goles del local
    Y = X2 + X3      goles del visitante

con X1, X2, X3 Poisson independientes. X3 es la componente COMUN —lo que hace
que un partido sea abierto o cerrado para los dos a la vez— y produce
Cov(X, Y) = lambda3 > 0, que es justo la correlacion que falta.

    P(x,y) = e^-(l1+l2+l3) * l1^x/x! * l2^y/y!
             * SUM_k C(x,k) C(y,k) k! (l3/(l1 l2))^k

Las marginales se conservan poniendo l1 = lh - l3 y l2 = la - l3, asi que la
lambda de cada equipo NO cambia: lo unico que se añade es como se reparten.
Eso importa porque el proyecto ya tiene la lambda medida y calibrada, y un
arreglo que la moviera obligaria a revalidar todo lo que cuelga de ella.

COMO SE PARAMETRIZA, Y POR QUE NO UNA CONSTANTE
-----------------------------------------------
`l3` constante seria raro: la misma covarianza en un partido de 1,8 goles y en
uno de 3,6. Se usa l3 = rho * min(lh, la), que escala con el partido y garantiza
l1, l2 >= 0 para cualquier rho en [0, 1).

CONTRA QUE SE JUZGA
-------------------
Log-loss del 1X2 y del BTTS, sesgo de las tres cosas, y bootstrap. `rho` se
ajusta SOLO en los pliegues de entrenamiento. Si no supera el p5, no se activa,
como paso con el inflado de la diagonal de la v230.

Esto no cambia nada: mide y escribe `_v231_bivariada.json`.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
from scipy.stats import poisson

SALIDA = '_v231_bivariada.json'
KMAX = 10                      # marcadores 0..9 por bando; cubre >99,99 %
REJILLA = np.round(np.arange(0.0, 0.31, 0.02), 3)


def matriz_bivariada(lh, la, rho):
    """(n, K, K) con P(x,y) bajo la bivariada de Poisson.

    Con rho = 0 es exactamente el producto de dos Poisson, o sea la matriz que
    el proyecto usa hoy. Eso es deliberado: la comparacion es contra el mismo
    codigo con un parametro a cero, no contra otra implementacion que podria
    diferir por su cuenta.
    """
    lh = np.asarray(lh, dtype=float)
    la = np.asarray(la, dtype=float)
    l3 = rho * np.minimum(lh, la)
    l1 = np.maximum(lh - l3, 1e-9)
    l2 = np.maximum(la - l3, 1e-9)

    k = np.arange(KMAX)
    # marginales de las componentes propias
    p1 = poisson.pmf(k[None, :], l1[:, None])          # (n, K)
    p2 = poisson.pmf(k[None, :], l2[:, None])
    base = p1[:, :, None] * p2[:, None, :]             # (n, K, K)
    if rho <= 0:
        return base

    # El sumatorio de la convolucion. Se acumula termino a termino en vez de
    # construir un tensor (n, K, K, K): con 38.000 partidos eso son gigabytes.
    import math as _m
    from scipy.special import comb
    x = k[:, None]
    y = k[None, :]
    total = np.zeros_like(base)
    ratio = l3 / (l1 * l2)                             # (n,)
    for j in range(KMAX):
        # C(x,j) · C(y,j) · j! · r^j. `comb` ya devuelve 0 donde j > x o j > y,
        # que es lo que corta el sumatorio en min(x, y) sin un `if` por casilla.
        coef = (comb(x, j, exact=False) * comb(y, j, exact=False)
                * float(_m.factorial(j)))
        if not np.any(coef):
            continue
        total += base * coef[None, :, :] * (ratio[:, None, None] ** j)
    # el factor e^-l3 que falta para que sume 1
    total *= np.exp(-l3)[:, None, None]
    s = total.sum(axis=(1, 2), keepdims=True)
    return total / np.where(s > 0, s, 1.0)


def _resumen(M):
    """(p_local, p_empate, p_visita, p_btts) de cada matriz."""
    idx = np.arange(KMAX)
    sup = idx[:, None] > idx[None, :]
    inf = idx[:, None] < idx[None, :]
    dia = idx[:, None] == idx[None, :]
    btts = (idx[:, None] >= 1) & (idx[None, :] >= 1)
    pl = (M * sup).sum(axis=(1, 2))
    pv = (M * inf).sum(axis=(1, 2))
    pe = (M * dia).sum(axis=(1, 2))
    pb = (M * btts).sum(axis=(1, 2))
    return pl, pe, pv, pb


def _ll_1x2(pl, pe, pv, y):
    p = np.where(y == 0, pl, np.where(y == 1, pe, pv))
    return float(-np.mean(np.log(np.clip(p, 1e-9, 1.0))))


def _ll_bin(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main():
    import calibrador_goles as cg

    t = cg._datos()
    t = t[t.goles_local.notna() & t.goles_visit.notna()].copy()
    gl = t.goles_local.to_numpy(float)
    gv = t.goles_visit.to_numpy(float)
    y1x2 = np.where(gl > gv, 0, np.where(gl == gv, 1, 2))
    ybtts = ((gl >= 1) & (gv >= 1)).astype(float)
    lh = t.lam_h.to_numpy(float)
    la = t.lam_a.to_numpy(float)
    pl_ = t.pliegue.to_numpy(int)
    ultimo = int(pl_.max())
    tr, ju = pl_ < ultimo, pl_ == ultimo
    print('ledger %d · entrena %d · juzga %d' % (len(t), tr.sum(), ju.sum()))

    print()
    print('%6s %12s %12s' % ('rho', 'll_1x2_tr', 'll_btts_tr'))
    mejor, mejor_ll = 0.0, None
    for rho in REJILLA:
        M = matriz_bivariada(lh[tr], la[tr], float(rho))
        a, b, c, d = _resumen(M)
        ll = _ll_1x2(a, b, c, y1x2[tr]) + _ll_bin(d, ybtts[tr])
        if mejor_ll is None or ll < mejor_ll:
            mejor, mejor_ll = float(rho), ll
        if abs(rho * 100 % 6) < 1e-6:
            print('%6.2f %12.5f %12.5f'
                  % (rho, _ll_1x2(a, b, c, y1x2[tr]), _ll_bin(d, ybtts[tr])))
    print()
    print('rho elegido: %.2f (suma de log-loss %.5f)' % (mejor, mejor_ll))
    if mejor >= REJILLA[-1] - 1e-9:
        print('AVISO: el optimo cae en el borde; ampliar la rejilla')

    M0 = matriz_bivariada(lh[ju], la[ju], 0.0)
    M1 = matriz_bivariada(lh[ju], la[ju], mejor)
    a0, b0, c0, d0 = _resumen(M0)
    a1, b1, c1, d1 = _resumen(M1)
    yj, bj = y1x2[ju], ybtts[ju]
    emp_real = float((yj == 1).mean())
    btts_real = float(bj.mean())

    filas = [
        ('log-loss 1X2', _ll_1x2(a0, b0, c0, yj), _ll_1x2(a1, b1, c1, yj)),
        ('log-loss BTTS', _ll_bin(d0, bj), _ll_bin(d1, bj)),
        ('P(empate) media', float(b0.mean()), float(b1.mean())),
        ('P(BTTS) media', float(d0.mean()), float(d1.mean())),
        ('sesgo empate', float(b0.mean() - emp_real),
         float(b1.mean() - emp_real)),
        ('sesgo BTTS', float(d0.mean() - btts_real),
         float(d1.mean() - btts_real)),
    ]
    print()
    print('%-22s %12s %12s' % ('', 'rho=0', 'rho=%.2f' % mejor))
    for etq, v0, v1 in filas:
        print('%-22s %12.5f %12.5f' % (etq, v0, v1))
    print('%-22s %12.4f' % ('empates reales', emp_real))
    print('%-22s %12.4f' % ('BTTS real', btts_real))
    print('%-22s %12d %12d' % ('empate es el modal',
                               int((b0 > np.maximum(a0, c0)).sum()),
                               int((b1 > np.maximum(a1, c1)).sum())))

    rng = np.random.default_rng(31)
    n = int(ju.sum())
    d1x2, dbtts = [], []
    for _ in range(600):
        s = rng.integers(0, n, n)
        d1x2.append(_ll_1x2(a0[s], b0[s], c0[s], yj[s])
                    - _ll_1x2(a1[s], b1[s], c1[s], yj[s]))
        dbtts.append(_ll_bin(d0[s], bj[s]) - _ll_bin(d1[s], bj[s]))
    d1x2, dbtts = np.array(d1x2), np.array(dbtts)
    p5_1x2, p5_btts = float(np.percentile(d1x2, 5)), float(np.percentile(dbtts, 5))
    print()
    print('bootstrap 1X2 : media %+.5f · p5 %+.5f · mejora %.1f %%'
          % (d1x2.mean(), p5_1x2, 100 * float((d1x2 > 0).mean())))
    print('bootstrap BTTS: media %+.5f · p5 %+.5f · mejora %.1f %%'
          % (dbtts.mean(), p5_btts, 100 * float((dbtts > 0).mean())))

    activa = mejor > 0 and p5_1x2 > 0 and p5_btts > 0
    print()
    print('VEREDICTO: %s' % (
        'SE ACTIVA — mejora 1X2 y BTTS, y los dos p5 aguantan' if activa else
        'NO se activa — algun p5 no aguanta'))

    doc = {'rho': mejor, 'n_train': int(tr.sum()), 'n_juicio': n,
           'metricas': {e: {'rho0': v0, 'rho': v1} for e, v0, v1 in filas},
           'empates_reales': emp_real, 'btts_real': btts_real,
           'bootstrap_1x2_p5': p5_1x2, 'bootstrap_btts_p5': p5_btts,
           'modal_empate_rho0': int((b0 > np.maximum(a0, c0)).sum()),
           'modal_empate_rho': int((b1 > np.maximum(a1, c1)).sum()),
           'activa': bool(activa)}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
