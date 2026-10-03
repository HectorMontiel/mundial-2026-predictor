# -*- coding: utf-8 -*-
"""v323 — qué arregla de verdad la sobreconfianza, medido fuera de muestra.

Dos pruebas, las dos con el ajuste hecho SÓLO con partidos anteriores:
  1. Tramo largo: se ajusta con 2024-01 → 2025-06 y se juzga 2025-07 → 2026-07-15.
  2. Tramo reciente: se ajusta con 2024-01 → 2026-07-15 y se juzga 2026-07-16 → hoy
     (el tramo que importa: es lo que vería el usuario).
Calibradores probados (todos de pocos parámetros, para no sobreajustar):
  · temperatura: p_i ∝ p_i^(1/T)
  · temperatura + empate: además, un factor sobre el empate
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

SCR = os.getcwd()
R = pd.read_csv(os.path.join(SCR, '_v323_replay_selecciones.csv'), parse_dates=['date'])
F = R[['f0', 'f1', 'f2']].to_numpy()
C = R[['c0', 'c1', 'c2']].to_numpy()
y = R['y'].to_numpy()


def temp(P, T, d=1.0):
    L = np.log(np.clip(P, 1e-9, 1)) / T
    L[:, 1] += np.log(d)
    E = np.exp(L - L.max(1, keepdims=True))
    return E / E.sum(1, keepdims=True)


def ll(P, y):
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-9, 1))))


def ajusta(P, y, con_empate):
    if con_empate:
        f = lambda x: ll(temp(P, np.exp(x[0]), np.exp(x[1])), y)
        r = minimize(f, [0.0, 0.0], method='Nelder-Mead')
        return np.exp(r.x[0]), np.exp(r.x[1])
    f = lambda x: ll(temp(P, np.exp(x[0])), y)
    r = minimize(f, [0.0], method='Nelder-Mead')
    return np.exp(r.x[0]), 1.0


def informe(nombre, P, y):
    acc = np.mean(P.argmax(1) == y)
    br = np.mean(((P - np.eye(3)[y]) ** 2).sum(1))
    fav = P.max(1)
    hit = P.argmax(1) == y
    tramos = []
    for lo, hi in ((.5, .6), (.6, .7), (.7, 1.01)):
        s = (fav >= lo) & (fav < hi)
        if s.sum():
            tramos.append('%d-%d%%: n=%d dice %.0f real %.0f' % (
                100 * lo, min(100, 100 * hi), s.sum(), 100 * fav[s].mean(), 100 * hit[s].mean()))
    s = fav >= .6
    gap = (fav[s].mean() - hit[s].mean()) * 100 if s.sum() else float('nan')
    print('  %-26s acierto %5.1f%%  log-loss %.4f  Brier %.4f  ≥60%%: brecha %+.1f pt (n=%d) | %s'
          % (nombre, 100 * acc, ll(P, y), br, gap, s.sum(), ' · '.join(tramos)))


def boot(Pa, Pb, y, n=2000):
    rng = np.random.default_rng(7)
    la = -np.log(np.clip(Pa[np.arange(len(y)), y], 1e-9, 1))
    lb = -np.log(np.clip(Pb[np.arange(len(y)), y], 1e-9, 1))
    d = la - lb
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return d.mean(), np.percentile(bs, 5), np.percentile(bs, 95)


for titulo, a0, a1, b0, b1 in (
        ('1) tramo largo', '2024-01-01', '2025-07-01', '2025-07-01', '2026-07-16'),
        ('2) tramo reciente', '2024-01-01', '2026-07-16', '2026-07-16', '2100-01-01')):
    A = (R.date >= a0) & (R.date < a1)
    B = (R.date >= b0) & (R.date < b1)
    print('\n%s · ajuste %s→%s (n=%d) · juicio %s→ (n=%d)' % (titulo, a0, a1, A.sum(), b0, B.sum()))
    t1, _ = ajusta(F[A], y[A], False)
    t2, d2 = ajusta(F[A], y[A], True)
    print('  temperatura T=%.3f · temperatura+empate T=%.3f d=%.3f' % (t1, t2, d2))
    yb = y[B]
    if titulo.startswith('2'):
        ok = ~np.isnan(C[B]).any(1)
        print('  (comparación con producción: %d partidos con equipos en team_stats)' % ok.sum())
        informe('ACTUAL (estado 15-jul)', C[B][ok], yb[ok])
        informe('estado al día', F[B][ok], yb[ok])
        informe('al día + temperatura', temp(F[B][ok], t1), yb[ok])
        informe('al día + temp + empate', temp(F[B][ok], t2, d2), yb[ok])
        m, p5, p95 = boot(C[B][ok], temp(F[B][ok], t1), yb[ok])
        print('  mejora log-loss (al día+temperatura vs ACTUAL): %.4f (p5 %.4f, p95 %.4f)' % (m, p5, p95))
        m, p5, p95 = boot(C[B][ok], F[B][ok], yb[ok])
        print('  mejora log-loss (sólo estado al día vs ACTUAL): %.4f (p5 %.4f, p95 %.4f)' % (m, p5, p95))
    else:
        informe('estado al día (sin calibrar)', F[B], yb)
        informe('al día + temperatura', temp(F[B], t1), yb)
        informe('al día + temp + empate', temp(F[B], t2, d2), yb)
        m, p5, p95 = boot(F[B], temp(F[B], t1), yb)
        print('  mejora log-loss por la temperatura: %.4f (p5 %.4f, p95 %.4f)' % (m, p5, p95))
