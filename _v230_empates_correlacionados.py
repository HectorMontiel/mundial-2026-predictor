#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v230 — el modelo se come los empates, y hay que ver si eso se arregla.

LO MEDIDO, QUE ES DE DONDE SALE ESTO
------------------------------------
Sobre los 47.794 partidos del ledger, P(empate) bajo Poisson independiente
contra los empates que de verdad ocurrieron:

    tramo lambda      n      modelo       real      sesgo
    0.0 - 2.2     13.021     0,3128     0,2852    +0,0276
    2.2 - 2.6     11.029     0,2579     0,2743    -0,0164
    2.6 - 3.0     10.205     0,2322     0,2680    -0,0359
    3.0 - inf     13.539     0,1952     0,2305    -0,0353

En tres de los cuatro tramos el modelo promete MENOS empates de los que pasan, y
en los partidos abiertos se queda corto por tres puntos y medio. El efecto en
pantalla es directo: de 169 picks de futbol del dia, solo 11 son empate.

POR QUE PASA, Y POR QUE NO ES UN FALLO DE CALIBRACION
-----------------------------------------------------
La matriz de marcador sale de multiplicar dos Poisson independientes. Los goles
de los dos equipos NO son independientes: el marcador influye en como se juega
—el que va perdiendo arriesga, el que gana se repliega— y eso correlaciona los
dos numeros y produce mas marcadores IGUALES de los que predice la
independencia. Es el efecto que Dixon-Coles corrigio en 1997 para el 0-0, 1-0,
0-1 y 1-1, y el mismo que aqui aparece extendido a toda la diagonal.

Una isotonica no lo arregla: es monotona sobre UNA probabilidad y aqui hay que
mover masa de probabilidad ENTRE casillas de la matriz conservando la suma.

QUE SE PRUEBA
-------------
Una correccion de un solo parametro sobre la diagonal:

    P'(k,k) = P(k,k) * (1 + d)      y el resto se reescala para sumar 1

`d` se ajusta en los pliegues de entrenamiento y se juzga en el ultimo, que es
la disciplina de siempre. Se compara log-loss del 1X2 —no accuracy— porque lo
que se quiere arreglar es la PROBABILIDAD, no cual de las tres gana.

Esto no cambia nada: mide y escribe `_v230_empates.json`.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
from scipy.stats import poisson

SALIDA = '_v230_empates.json'
K = np.arange(0, 12)
# El grid de `d`. Va hasta 0,40 porque el sesgo medido en la lambda alta es de
# 3,5 puntos sobre una base de 19,5: recuperarlo pide subir la diagonal cerca
# de un 18 %, y conviene que el grid tenga sitio por encima para que el optimo
# no caiga en el borde sin que se note.
REJILLA = np.round(np.arange(0.0, 0.41, 0.02), 3)


def _matriz(lh, la):
    """P(marcador) para cada partido: (n, K, K)."""
    ph = poisson.pmf(K[None, :], lh[:, None])
    pa = poisson.pmf(K[None, :], la[:, None])
    return ph[:, :, None] * pa[:, None, :]


def _tri(M, d):
    """(P_local, P_empate, P_visita) tras inflar la diagonal un `d`."""
    if d:
        diag = np.einsum('ikk->ik', M)
        M = M.copy()
        np.einsum('ikk->ik', M)[...] = diag * (1.0 + d)
    tot = M.sum(axis=(1, 2))
    tot = np.where(tot > 0, tot, 1.0)
    idx = np.arange(len(K))
    sup = idx[:, None] > idx[None, :]
    inf = idx[:, None] < idx[None, :]
    pl = (M * sup).sum(axis=(1, 2)) / tot
    pv = (M * inf).sum(axis=(1, 2)) / tot
    pe = 1.0 - pl - pv
    return pl, np.clip(pe, 1e-9, 1.0), pv


def _logloss(pl, pe, pv, y):
    """y: 0 local, 1 empate, 2 visita."""
    p = np.where(y == 0, pl, np.where(y == 1, pe, pv))
    return float(-np.mean(np.log(np.clip(p, 1e-9, 1.0))))


def main():
    import calibrador_goles as cg

    t = cg._datos()
    t = t[t.goles_local.notna() & t.goles_visit.notna()].copy()
    gl = t.goles_local.to_numpy(float)
    gv = t.goles_visit.to_numpy(float)
    y = np.where(gl > gv, 0, np.where(gl == gv, 1, 2))
    lh = t.lam_h.to_numpy(float)
    la = t.lam_a.to_numpy(float)
    pliegue = t.pliegue.to_numpy(int)
    ultimo = int(pliegue.max())
    tr, ju = pliegue < ultimo, pliegue == ultimo
    print('ledger %d · entrena con %d · juzga con %d'
          % (len(t), tr.sum(), ju.sum()))

    M_tr = _matriz(lh[tr], la[tr])
    M_ju = _matriz(lh[ju], la[ju])

    print()
    print('%6s %12s' % ('d', 'logloss_tr'))
    mejor, mejor_ll = 0.0, None
    for d in REJILLA:
        ll = _logloss(*_tri(M_tr, float(d)), y[tr])
        if mejor_ll is None or ll < mejor_ll:
            mejor, mejor_ll = float(d), ll
        if abs(d * 100 % 6) < 1e-6:
            print('%6.2f %12.5f' % (d, ll))
    print()
    print('d elegido en entrenamiento: %.2f (log-loss %.5f)' % (mejor, mejor_ll))
    if mejor >= REJILLA[-1] - 1e-9:
        print('AVISO: el optimo cae en el borde de la rejilla; ampliarla')

    # JUICIO, fuera de muestra
    pl0, pe0, pv0 = _tri(M_ju, 0.0)
    pl1, pe1, pv1 = _tri(M_ju, mejor)
    ll0 = _logloss(pl0, pe0, pv0, y[ju])
    ll1 = _logloss(pl1, pe1, pv1, y[ju])
    real = float((y[ju] == 1).mean())

    print()
    print('%-22s %10s %10s' % ('', 'sin', 'con d=%.2f' % mejor))
    print('%-22s %10.5f %10.5f' % ('log-loss 1X2', ll0, ll1))
    print('%-22s %10.4f %10.4f' % ('P(empate) media', pe0.mean(), pe1.mean()))
    print('%-22s %10.4f %10.4f' % ('empates reales', real, real))
    print('%-22s %+10.4f %+10.4f'
          % ('sesgo', pe0.mean() - real, pe1.mean() - real))
    print('%-22s %10d %10d' % ('empate es el modal',
                               int((pe0 > np.maximum(pl0, pv0)).sum()),
                               int((pe1 > np.maximum(pl1, pv1)).sum())))

    # BOOTSTRAP: que la mejora no sea el azar de un pliegue.
    rng = np.random.default_rng(7)
    n = int(ju.sum())
    yj = y[ju]
    dif = []
    for _ in range(600):
        s = rng.integers(0, n, n)
        dif.append(_logloss(pl0[s], pe0[s], pv0[s], yj[s])
                   - _logloss(pl1[s], pe1[s], pv1[s], yj[s]))
    dif = np.array(dif)
    p5 = float(np.percentile(dif, 5))

    # Y EL BOOTSTRAP DEL SESGO, QUE ES OTRA PREGUNTA.
    #
    # El log-loss mide la calidad predictiva ENTERA, y mover masa a la diagonal
    # apenas la cambia: se corrige el nivel del empate sin mejorar la capacidad
    # de separar un partido de otro. Pero quien apuesta no compra log-loss:
    # compra EV = p x cuota - 1, que es LINEAL en p. Un empate infravalorado en
    # 1,4 puntos sobre una base de 25 es un 5,6 % de EV que no se ve.
    #
    # Asi que se mide tambien si la REDUCCION DEL SESGO aguanta el remuestreo.
    # Las dos respuestas pueden discrepar, y si discrepan hay que decirlo en vez
    # de esconderse detras de la que convenga.
    s_dif = []
    for _ in range(600):
        s = rng.integers(0, n, n)
        r = float((yj[s] == 1).mean())
        s_dif.append(abs(pe0[s].mean() - r) - abs(pe1[s].mean() - r))
    s_dif = np.array(s_dif)
    s_p5 = float(np.percentile(s_dif, 5))
    print()
    print('bootstrap de la mejora de log-loss: media %+.5f · p5 %+.5f · '
          'veces que mejora %.1f %%'
          % (dif.mean(), p5, 100.0 * float((dif > 0).mean())))

    print('bootstrap de la reducción del SESGO:   media %+.5f · p5 %+.5f · '
          'veces que mejora %.1f %%'
          % (s_dif.mean(), s_p5, 100.0 * float((s_dif > 0).mean())))

    activa = (ll1 < ll0) and p5 > 0
    print()
    print('Criterio del proyecto (p5 del log-loss): %s'
          % ('SE ACTIVA' if activa else 'NO se activa'))
    print('Calibración del empate  (p5 del sesgo):  %s'
          % ('mejora y aguanta el remuestreo' if s_p5 > 0
             else 'no es concluyente'))
    if not activa and s_p5 > 0:
        print()
        print('LAS DOS RESPUESTAS DISCREPAN, y hay que decirlo en vez de')
        print('elegir la que convenga. El log-loss mide la calidad predictiva')
        print('entera y mover masa a la diagonal apenas la cambia. El sesgo')
        print('mide si el nivel del empate es el correcto, y ese SÍ mejora.')
        print('Quien apuesta no compra log-loss: compra EV = p x cuota - 1,')
        print('que es lineal en p. Manda el criterio del proyecto —queda')
        print('APAGADO— pero la decisión es del usuario y ahora tiene el dato.')

    doc = {'d': mejor, 'n_train': int(tr.sum()), 'n_juicio': n,
           'logloss_sin': ll0, 'logloss_con': ll1,
           'p_empate_sin': float(pe0.mean()), 'p_empate_con': float(pe1.mean()),
           'empates_reales': real,
           'sesgo_sin': float(pe0.mean() - real),
           'sesgo_con': float(pe1.mean() - real),
           'modal_sin': int((pe0 > np.maximum(pl0, pv0)).sum()),
           'modal_con': int((pe1 > np.maximum(pl1, pv1)).sum()),
           'bootstrap_p5': p5, 'bootstrap_media': float(dif.mean()),
           'sesgo_bootstrap_p5': s_p5,
           'sesgo_bootstrap_media': float(s_dif.mean()),
           'activa': bool(activa)}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
