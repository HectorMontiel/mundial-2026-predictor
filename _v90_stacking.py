#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — ¿Se puede APRENDER la combinación modelo+mercado en vez de fijarla?

De dónde sale
-------------
`_v90_edge_mezcla.py` deja tres hechos medidos sobre 26.666 partidos con ancla
de Pinnacle (elección en pliegues 0-2, juicio en 3-4):

    modelo solo    log-loss 1,02811 · precisión 48,96 %
    mercado solo   log-loss 1,00120 · precisión 50,04 %
    producción     log-loss 1,00204 · precisión 50,05 %   (lineal w=0,25)

O sea: el modelo por su cuenta es PEOR que el mercado, y la mezcla de
producción apenas empata con el mercado desnudo. El peso fijo sólo puede
moverse por una recta entre los dos; si el modelo aporta señal, la aporta en
sitios concretos (un lado, un rango de probabilidad), no de forma uniforme.

Qué se prueba aquí
------------------
Una regresión logística multinomial que recibe las dos opiniones en log-odds
y aprende cómo pesarlas. Es la generalización del blend: con los coeficientes
adecuados puede reproducir exactamente `w·pm + (1−w)·pmkt`, así que sólo puede
igualar o mejorar dentro de muestra — la pregunta es si eso sobrevive FUERA.

Se prueban tres cestas de features, de menos a más libertad:

  S1  log p_mercado                       (recalibrar el mercado a secas)
  S2  log p_mercado + log p_modelo        (el stacking clásico)
  S3  S2 + la discrepancia |pm − pmkt|    (deja que el peso dependa de cuánto
                                           discrepan, que es donde la v87 midió
                                           que el modelo se rompe)

Método: se ajusta en los pliegues 0-2 y se juzga en los 3-4, que no participan
ni en el ajuste ni en la elección de la cesta.
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.stdout.reconfigure(encoding='utf-8')
EPS = 1e-9


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


def metricas(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    ll = float(-np.mean(np.log(p[np.arange(len(y)), y])))
    conf, pred = p.max(axis=1), p.argmax(axis=1)
    acierta = (pred == y).astype(float)
    ece, n = 0.0, len(y)
    for lo in np.arange(0.0, 1.0, 0.05):
        m = (conf >= lo) & (conf < lo + 0.05)
        if m.sum():
            ece += (m.sum() / n) * abs(acierta[m].mean() - conf[m].mean())
    oh = np.zeros_like(p)
    oh[np.arange(len(y)), y] = 1.0
    return {'logloss': ll, 'ece': float(ece), 'acc': float(acierta.mean()),
            'brier': float(((p - oh) ** 2).sum(axis=1).mean())}


def boot_p5(g, n_boot=3000, semilla=11):
    rng = np.random.default_rng(semilla)
    b = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)]
    return float(np.percentile(b, 5) * 100)


def roi_sel(p, y, cu, prob_min=0.55, ev_min=0.03, ev_max=0.14,
            conv=0.025, cuota_min=1.50):
    """El filtro real de Capa 1 sobre el argmax."""
    pred = p.argmax(axis=1)
    idx = np.arange(len(pred))
    prob, precio = p[idx, pred], cu[idx, pred]
    ev = precio * prob - 1.0
    ok = (np.isfinite(precio) & (precio > cuota_min) & (prob > prob_min)
          & (ev > ev_min) & (ev <= ev_max) & (prob * ev >= conv))
    if ok.sum() < 25:
        return int(ok.sum()), None, None
    g = np.where(pred[ok] == y[ok], precio[ok] - 1.0, -1.0)
    return int(ok.sum()), float(g.mean() * 100), boot_p5(g)


def roi_ev_positivo(p, y, cu):
    """Muestra ANCHA: todo EV>0. Menos parecido a producción pero con
    poder estadístico suficiente para distinguir variantes."""
    pred = p.argmax(axis=1)
    idx = np.arange(len(pred))
    prob, precio = p[idx, pred], cu[idx, pred]
    ev = precio * prob - 1.0
    ok = np.isfinite(precio) & (precio > 1.0) & (ev > 0)
    if ok.sum() < 50:
        return int(ok.sum()), None, None
    g = np.where(pred[ok] == y[ok], precio[ok] - 1.0, -1.0)
    return int(ok.sum()), float(g.mean() * 100), boot_p5(g)


def features(pm, mk, cesta):
    lm = np.log(np.clip(mk, EPS, 1))
    lp = np.log(np.clip(pm, EPS, 1))
    if cesta == 'S1':
        return lm
    if cesta == 'S2':
        return np.hstack([lm, lp])
    disc = np.abs(pm - mk).max(axis=1, keepdims=True)
    return np.hstack([lm, lp, disc, disc * lp])


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away',
                           'p_home', 'p_draw', 'p_away', 'resultado'])
    for c in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[c] > 1.0]

    pm = df[['p_home', 'p_draw', 'p_away']].to_numpy(float)
    pm = pm / pm.sum(axis=1, keepdims=True)
    mk = devig_potencia(df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float))
    y = df['resultado'].to_numpy(int)
    cu = df[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(float)
    pin = df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float)
    cu = np.where(np.isfinite(cu) & (cu > 1), cu, pin)
    pl = df['pliegue'].to_numpy(int)
    e, j = pl <= 2, pl >= 3
    print(f'{len(df)} partidos · ajusta {e.sum()} · juzga {j.sum()}\n')

    def linea(nombre, p, yy, cc):
        m = metricas(p, yy)
        n1, r1, q1 = roi_sel(p, yy, cc)
        n2, r2, q2 = roi_ev_positivo(p, yy, cc)
        print(f'{nombre:26s} {m["logloss"]:8.5f} {m["ece"]:7.4f} '
              f'{m["acc"]*100:8.2f} % {n1:5d} '
              f'{"—":>8s}' if r1 is None else
              f'{nombre:26s} {m["logloss"]:8.5f} {m["ece"]:7.4f} '
              f'{m["acc"]*100:8.2f} % {n1:5d} {r1:+7.2f}% {q1:+7.2f}% '
              f'{n2:6d} {r2:+7.2f}% {q2:+7.2f}%')
        return {**m, 'n_sel': n1, 'roi_sel': r1, 'p5_sel': q1,
                'n_ev': n2, 'roi_ev': r2, 'p5_ev': q2}

    print(f'{"variante":26s} {"logloss":>8s} {"ECE":>7s} {"precisión":>10s} '
          f'{"nSel":>5s} {"ROIsel":>8s} {"p5sel":>8s} {"nEV+":>6s} '
          f'{"ROIev":>8s} {"p5ev":>8s}')
    print('-' * 104)
    out = {}
    base_lin = 0.25 * pm + 0.75 * mk
    base_lin = base_lin / base_lin.sum(axis=1, keepdims=True)
    out['produccion_w025'] = linea('PRODUCCIÓN lineal .25', base_lin[j], y[j], cu[j])
    out['mercado'] = linea('mercado solo', mk[j], y[j], cu[j])
    out['modelo'] = linea('modelo solo', pm[j], y[j], cu[j])

    for cesta in ('S1', 'S2', 'S3'):
        Xe, Xj = features(pm[e], mk[e], cesta), features(pm[j], mk[j], cesta)
        clf = LogisticRegression(max_iter=3000, C=1.0, multi_class='multinomial')
        clf.fit(Xe, y[e])
        out[cesta] = linea(f'stacking {cesta}', clf.predict_proba(Xj), y[j], cu[j])
        out[cesta]['coef'] = clf.coef_.tolist()

    with open('_v90_stacking.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)
    print('\n→ _v90_stacking.json')


if __name__ == '__main__':
    main()
