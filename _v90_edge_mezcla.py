#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — ¿Se puede mejorar la PRECISIÓN cambiando cómo se mezclan modelo y mercado?

Qué se prueba
-------------
Producción mezcla en el espacio de PROBABILIDAD y con un peso fijo:

    p = w·p_modelo + (1−w)·p_mercado,   w = 0,25

Dos supuestos ahí dentro que nunca se han comparado contra alternativas:

  1. Que 0,25 sigue siendo el peso correcto. Se eligió en la v75 sobre 75.131
     partidos, pero el modelo se ha reentrenado varias veces desde entonces.
  2. Que la mezcla LINEAL es la forma correcta. Mezclar probabilidades en línea
     recta arrastra hacia el centro; en logit (log-odds) la mezcla conserva la
     forma de las colas, que es donde vive el favorito claro. Es lo estándar
     para combinar predictores calibrados y aquí nunca se probó.

Método
------
Todo se ELIGE en los pliegues 0-2 y se JUZGA en los 3-4, que no participan en
la elección. Nada de quedarse con el máximo de un barrido.

Se reportan las cuatro métricas que importan y no siempre coinciden:
log-loss (calidad probabilística), ECE (calibración), PRECISIÓN (lo que el
usuario ve como «acertar») y ROI/p5 de la apuesta (lo que se cobra).
"""
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

REJILLA = [round(x, 2) for x in np.arange(0.0, 1.001, 0.05)]
EPS = 1e-9


def devig_potencia(cuotas):
    """El devigado de producción (potencia), vectorizado."""
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


def mezcla_lineal(pm, mk, w):
    p = w * pm + (1 - w) * mk
    return p / p.sum(axis=1, keepdims=True)


def mezcla_logit(pm, mk, w):
    """Media geométrica ponderada = mezcla lineal en log-odds, renormalizada."""
    a = np.clip(pm, EPS, 1)
    b = np.clip(mk, EPS, 1)
    p = np.exp(w * np.log(a) + (1 - w) * np.log(b))
    return p / p.sum(axis=1, keepdims=True)


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
    # Brier multiclase
    oh = np.zeros_like(p)
    oh[np.arange(len(y)), y] = 1.0
    brier = float(((p - oh) ** 2).sum(axis=1).mean())
    return {'logloss': ll, 'ece': float(ece), 'acc': float(acierta.mean()),
            'brier': brier}


def roi_seleccion(p, y, cuotas, prob_min=0.55, ev_min=0.03, ev_max=0.14,
                  conviccion=0.025, cuota_min=1.50, n_boot=3000, semilla=11):
    """
    ROI de lo que producción APOSTARÍA de verdad: el filtro de Capa 1
    (piso de probabilidad, banda de EV, convicción y cuota mínima) sobre el
    argmax. Devuelve (n, ROI %, p5 %).
    """
    pred = p.argmax(axis=1)
    idx = np.arange(len(pred))
    prob = p[idx, pred]
    precio = cuotas[idx, pred]
    ev = precio * prob - 1.0
    ok = (np.isfinite(precio) & (precio > cuota_min) & (prob > prob_min)
          & (ev > ev_min) & (ev <= ev_max) & (prob * ev >= conviccion))
    if ok.sum() < 25:
        return int(ok.sum()), None, None
    g = np.where(pred[ok] == y[ok], precio[ok] - 1.0, -1.0)
    rng = np.random.default_rng(semilla)
    boots = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)]
    return int(ok.sum()), float(g.mean() * 100), float(np.percentile(boots, 5) * 100)


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
    pliegue = df['pliegue'].to_numpy(int)

    e = pliegue <= 2      # ELIGE
    j = pliegue >= 3      # JUZGA
    print(f'fútbol con ancla de Pinnacle: {len(df)} filas · '
          f'elige {e.sum()} · juzga {j.sum()}\n')

    # --- referencias puras -------------------------------------------------
    print('=== REFERENCIAS en los pliegues 3-4 ===')
    for nombre, p in (('modelo solo', pm[j]), ('mercado solo', mk[j])):
        m = metricas(p, y[j])
        n, roi, p5 = roi_seleccion(p, y[j], cu[j])
        print(f'  {nombre:14s} logloss {m["logloss"]:.5f} · ECE {m["ece"]:.4f} · '
              f'precisión {m["acc"]*100:5.2f} % · Brier {m["brier"]:.5f} · '
              f'sel n={n} ROI {roi if roi is None else round(roi,2)} p5 '
              f'{p5 if p5 is None else round(p5,2)}')

    # --- elección del w en los pliegues tempranos --------------------------
    print('\n=== ELECCIÓN del w en los pliegues 0-2 (por log-loss) ===')
    elegidos = {}
    for nombre, fn in (('lineal', mezcla_lineal), ('logit', mezcla_logit)):
        mejor_w, mejor_ll = None, np.inf
        curva = []
        for w in REJILLA:
            ll = metricas(fn(pm[e], mk[e], w), y[e])['logloss']
            curva.append((w, round(ll, 5)))
            if ll < mejor_ll:
                mejor_ll, mejor_w = ll, w
        elegidos[nombre] = mejor_w
        print(f'  {nombre:7s} w* = {mejor_w:.2f} (logloss {mejor_ll:.5f})')
        print('          curva:', ' '.join(f'{w:.2f}:{l:.4f}' for w, l in curva[::4]))

    # --- juicio en los pliegues tardíos ------------------------------------
    print('\n=== JUICIO en los pliegues 3-4 (no participaron en la elección) ===')
    print(f'{"variante":28s} {"logloss":>9s} {"ECE":>8s} {"precisión":>10s} '
          f'{"Brier":>9s} {"n sel":>6s} {"ROI":>8s} {"p5":>8s}')
    print('-' * 95)
    salida = {}
    variantes = [
        ('PRODUCCIÓN lineal w=0.25', mezcla_lineal, 0.25),
        (f'lineal w*={elegidos["lineal"]:.2f}', mezcla_lineal, elegidos['lineal']),
        (f'LOGIT w*={elegidos["logit"]:.2f}', mezcla_logit, elegidos['logit']),
        ('logit w=0.25', mezcla_logit, 0.25),
    ]
    for nombre, fn, w in variantes:
        p = fn(pm[j], mk[j], w)
        m = metricas(p, y[j])
        n, roi, p5 = roi_seleccion(p, y[j], cu[j])
        salida[nombre] = {**m, 'w': w, 'n_sel': n, 'roi': roi, 'p5': p5}
        print(f'{nombre:28s} {m["logloss"]:9.5f} {m["ece"]:8.4f} '
              f'{m["acc"]*100:9.2f} % {m["brier"]:9.5f} {n:6d} '
              f'{"—" if roi is None else f"{roi:+7.2f}%"} '
              f'{"—" if p5 is None else f"{p5:+7.2f}%"}')

    with open('_v90_edge_mezcla.json', 'w', encoding='utf-8') as f:
        json.dump({'elegidos': elegidos, 'juicio': salida}, f,
                  ensure_ascii=False, indent=1)
    print('\n→ _v90_edge_mezcla.json')


if __name__ == '__main__':
    main()
