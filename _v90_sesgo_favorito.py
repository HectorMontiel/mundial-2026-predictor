#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — El sesgo favorito-perdedor SOBREVIVE al devigado. ¿Se puede explotar?

El hallazgo (`_v90_auditoria_ledger.py`, 26.666 partidos con Pinnacle)
---------------------------------------------------------------------
Después de quitarle el margen a Pinnacle por el método de potencia, la
probabilidad resultante NO está calibrada de forma uniforme: sobrestima a los
tapados y subestima a los favoritos claros, de forma monótona.

    banda del favorito   dice      pasa      sesgo
    0,33–0,40           37,44 %   35,79 %   +1,65 pp
    0,40–0,50           44,61 %   44,35 %   +0,26 pp
    0,50–0,60           54,56 %   53,92 %   +0,64 pp
    0,60–0,70           64,43 %   65,25 %   −0,82 pp
    0,70–0,80           74,24 %   76,80 %   −2,56 pp
    0,80–1,00           85,03 %   85,90 %   −0,87 pp

Es el sesgo favorito-perdedor de manual, y es el ÚNICO sitio donde algo bate
al mercado en todo lo medido hasta ahora: el modelo pierde contra él en 33 de
34 ligas, pero el propio mercado se desvía de sí mismo de forma sistemática.

Qué se prueba
-------------
Dos correcciones sobre la probabilidad devigada, ninguna con datos nuevos:

  · PLATT en log-odds:  logit(p') = a + b·logit(p).  Si b>1 el mercado está
    poco afilado y hay que estirarlo hacia los extremos. Dos parámetros para
    20.000 partidos: imposible sobreajustar.
  · ISOTÓNICA: monótona pero libre de forma. Más flexible y por tanto más
    capaz de perseguir ruido; sirve de control — si la isotónica no bate a
    Platt, la forma simple es la correcta.

Se ajusta en los pliegues 0-2 y se juzga en los 3-4. Y no basta con mejorar la
calibración: hay que ver si **se cobra**, así que se mide también el ROI de
apostar donde la probabilidad corregida ve valor que el mercado no ve.
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

sys.stdout.reconfigure(encoding='utf-8')
EPS = 1e-6


def devig_potencia(cuotas):
    inv = 1.0 / cuotas
    out = np.empty_like(inv)
    for i in range(len(inv)):
        p = inv[i]
        lo, hi = 0.5, 1.5
        for _ in range(40):
            mid = (lo + hi) / 2
            if (p ** mid).sum() > 1:
                lo = mid
            else:
                hi = mid
        q = p ** ((lo + hi) / 2)
        out[i] = q / q.sum()
    return out


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def metricas(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    ll = float(-np.mean(np.log(p[np.arange(len(y)), y])))
    conf, pred = p.max(axis=1), p.argmax(axis=1)
    ac = (pred == y).astype(float)
    ece, n = 0.0, len(y)
    for lo in np.arange(0.0, 1.0, 0.05):
        m = (conf >= lo) & (conf < lo + 0.05)
        if m.sum():
            ece += (m.sum() / n) * abs(ac[m].mean() - conf[m].mean())
    oh = np.zeros_like(p)
    oh[np.arange(len(y)), y] = 1.0
    return {'logloss': ll, 'ece': float(ece), 'acc': float(ac.mean()),
            'brier': float(((p - oh) ** 2).sum(axis=1).mean())}


def boot_p5(g, n_boot=4000, semilla=13):
    rng = np.random.default_rng(semilla)
    return float(np.percentile(
        [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)], 5) * 100)


def roi_valor(p, y, cu, margen=0.01, prob_min=0.30):
    """
    Apuesta donde la probabilidad CORREGIDA ve valor: cuota·p−1 > margen.
    Es la misma forma que `valor_vs_sharp` (el canal con edge validado del
    proyecto), pero con la probabilidad corregida en vez de la devigada cruda.
    """
    n_f, idx = p.shape[1], np.arange(len(p))
    mejor_ev, mejor_k = None, None
    ev_all = cu * p - 1.0
    ev_all = np.where(np.isfinite(cu) & (cu > 1), ev_all, -9.9)
    mejor_k = ev_all.argmax(axis=1)
    mejor_ev = ev_all[idx, mejor_k]
    prob = p[idx, mejor_k]
    precio = cu[idx, mejor_k]
    ok = (mejor_ev > margen) & (prob >= prob_min) & np.isfinite(precio) & (precio > 1)
    if ok.sum() < 40:
        return int(ok.sum()), None, None
    g = np.where(mejor_k[ok] == y[ok], precio[ok] - 1.0, -1.0)
    return int(ok.sum()), float(g.mean() * 100), boot_p5(g)


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away', 'resultado'])
    for c in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[c] > 1.0]
    mk = devig_potencia(df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float))
    y = df['resultado'].to_numpy(int)
    cu = df[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(float)
    pin = df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float)
    cu = np.where(np.isfinite(cu) & (cu > 1), cu, pin)
    pl = df['pliegue'].to_numpy(int)
    e, j = pl <= 2, pl >= 3
    print(f'{len(df)} partidos · ajusta {e.sum()} · juzga {j.sum()}\n')

    # los tres lados de cada partido son puntos independientes de calibración
    def desplegar(mask):
        P = mk[mask].reshape(-1)
        Y = np.zeros((mask.sum(), 3), dtype=int)
        Y[np.arange(mask.sum()), y[mask]] = 1
        return P, Y.reshape(-1)

    Pe, Ye = desplegar(e)
    print(f'puntos de calibración para el ajuste: {len(Pe)}')

    # --- PLATT en log-odds --------------------------------------------------
    lr = LogisticRegression(max_iter=2000, C=1e6)   # sin regularización real
    lr.fit(logit(Pe).reshape(-1, 1), Ye)
    a, b = float(lr.intercept_[0]), float(lr.coef_[0][0])
    print(f'\nPLATT ajustado en pliegues 0-2:  logit(p\') = {a:+.4f} + {b:.4f}·logit(p)')
    print(f'  b = {b:.4f} → el mercado está '
          f'{"POCO AFILADO (hay que estirarlo)" if b > 1 else "SOBREAFILADO"}; '
          f'a {a:+.4f}')

    def aplica_platt(P):
        q = 1.0 / (1.0 + np.exp(-(a + b * logit(P))))
        return q / q.sum(axis=1, keepdims=True)

    # --- ISOTÓNICA ----------------------------------------------------------
    iso = IsotonicRegression(out_of_bounds='clip', y_min=0.001, y_max=0.999)
    iso.fit(Pe, Ye)

    def aplica_iso(P):
        q = iso.predict(P.reshape(-1)).reshape(P.shape)
        q = np.clip(q, 0.001, 0.999)
        return q / q.sum(axis=1, keepdims=True)

    # --- juicio -------------------------------------------------------------
    print('\n=== JUICIO en los pliegues 3-4 (no participaron en el ajuste) ===')
    print(f'{"variante":22s} {"logloss":>9s} {"ECE":>8s} {"precisión":>10s} '
          f'{"Brier":>9s} {"n valor":>8s} {"ROI":>8s} {"p5":>8s}')
    print('-' * 88)
    out = {}
    for nombre, P in (('mercado devigado', mk[j]),
                      ('+ Platt', aplica_platt(mk[j])),
                      ('+ isotónica', aplica_iso(mk[j]))):
        m = metricas(P, y[j])
        n, roi, p5 = roi_valor(P, y[j], cu[j])
        out[nombre] = {**m, 'n_valor': n, 'roi': roi, 'p5': p5}
        print(f'{nombre:22s} {m["logloss"]:9.5f} {m["ece"]:8.4f} '
              f'{m["acc"]*100:9.2f} % {m["brier"]:9.5f} {n:8d} '
              f'{"—" if roi is None else f"{roi:+7.2f}%"} '
              f'{"—" if p5 is None else f"{p5:+7.2f}%"}')

    # --- ¿el sesgo por banda desaparece? ------------------------------------
    print('\n=== El sesgo por banda, ANTES y DESPUÉS de Platt (pliegues 3-4) ===')
    print(f'{"banda":14s} {"n":>6s} {"sesgo crudo":>13s} {"sesgo Platt":>13s}')
    print('-' * 50)
    pp = aplica_platt(mk[j])
    for lo, hi in ((0.33, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70),
                   (0.70, 0.80), (0.80, 1.01)):
        c0, pr0 = mk[j].max(axis=1), mk[j].argmax(axis=1)
        m = (c0 >= lo) & (c0 < hi)
        if m.sum() < 25:
            continue
        acc = (pr0[m] == y[j][m]).mean()
        c1 = pp.max(axis=1)[m]
        print(f'{lo:.2f}–{hi:.2f}   {m.sum():6d} {(c0[m].mean()-acc)*100:+12.2f} pp '
              f'{(c1.mean()-acc)*100:+12.2f} pp')

    out['platt'] = {'a': a, 'b': b}
    with open('_v90_sesgo_favorito.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)
    print('\n→ _v90_sesgo_favorito.json')


if __name__ == '__main__':
    main()
