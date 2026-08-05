#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v94 — ¿Es 0,25 el peso correcto para el tenis, o hay uno mejor medido?

La premisa que se valida
------------------------
Se propuso «calcular un peso de calibración w para tenis y MLB, similar al
fútbol», dando por hecho que no se aplica ninguno. Comprobado primero: **sí se
aplica**. `alpha_finder` encoge el tenis con `calibracion_segura.
encoger_dos_vias` (línea 1136) y `mlb_engine` hace lo propio (línea 580), los
dos con w=0,25. Y la MLB además tiene su peso MEDIDO en
`calibracion_mercado.json` (n=7.541, Δlog-loss +0,0136, Δprecisión +0,0152).

Lo que sí falta es un w medido para ATP y WTA: caen al global. Y hay motivo
para mirarlo, porque la medición de producción de la v93 dice que el tenis
sigue sobreconfiando incluso encogido:

    mercado «Ganador»  n=58  promete 77,2 %  acierta 70,7 %   (−6,5 pp)

Eso apunta a que 0,25 podría ser demasiado peso para el modelo. Este script lo
mide sobre el ledger (ATP 36.457 filas, WTA 28.131), eligiendo en los pliegues
0-2 y juzgando en los 3-4, que no participan en la elección.

Advertencia previa: la v90 midió que el w POR LIGA en fútbol es una moneda al
aire y empeora ECE y ROI. El tenis es otra estructura (dos vías, sin empate) y
merece su propia medición — pero el listón es el mismo: sólo se adopta si gana
fuera de muestra y por un margen que no sea ruido.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

REJILLA = [round(x, 2) for x in np.arange(0.0, 1.001, 0.05)]
W_ACTUAL = 0.25
EPS = 1e-9


def devig_2via(c1, c2):
    """Probabilidad justa a dos vías (proporcional = potencia con 2 salidas)."""
    i1, i2 = 1.0 / c1, 1.0 / c2
    s = i1 + i2
    return i1 / s


def metricas(p, y):
    """p = P(gana el primero); y = 1 si ganó el primero."""
    p = np.clip(p, EPS, 1 - EPS)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    pred = (p >= 0.5).astype(int)
    acc = float((pred == y).mean())
    conf = np.maximum(p, 1 - p)
    acierta = (pred == y).astype(float)
    ece, n = 0.0, len(y)
    for lo in np.arange(0.5, 1.0, 0.05):
        m = (conf >= lo) & (conf < lo + 0.05)
        if m.sum():
            ece += (m.sum() / n) * abs(acierta[m].mean() - conf[m].mean())
    brier = float(np.mean((p - y) ** 2))
    return {'logloss': ll, 'acc': acc, 'ece': float(ece), 'brier': brier}


def boot_p5(g, n_boot=3000, semilla=29):
    rng = np.random.default_rng(semilla)
    return float(np.percentile(
        [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)], 5) * 100)


def roi_pick(p, y, c1, c2, prob_min=0.55):
    """ROI de apostar al lado que el modelo prefiere, con su cuota real."""
    lado1 = p >= 0.5
    prob = np.where(lado1, p, 1 - p)
    cuota = np.where(lado1, c1, c2)
    gano = np.where(lado1, y == 1, y == 0)
    ok = (prob >= prob_min) & np.isfinite(cuota) & (cuota > 1)
    if ok.sum() < 50:
        return int(ok.sum()), None, None
    g = np.where(gano[ok], cuota[ok] - 1.0, -1.0)
    return int(ok.sum()), float(g.mean() * 100), boot_p5(g)


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    salida = {}
    for circ in ('ATP', 'WTA'):
        sub = df[df['liga'] == circ].dropna(
            subset=['p_home', 'cuota_home', 'cuota_away', 'resultado']).copy()
        sub = sub[(sub['cuota_home'] > 1) & (sub['cuota_away'] > 1)]
        if len(sub) < 500:
            print(f'{circ}: muestra insuficiente ({len(sub)})')
            continue
        pm = sub['p_home'].to_numpy(float)
        mk = devig_2via(sub['cuota_home'].to_numpy(float),
                        sub['cuota_away'].to_numpy(float))
        y = (sub['resultado'].to_numpy(int) == 0).astype(int)   # 0 = gana p1
        c1 = sub['cuota_home'].to_numpy(float)
        c2 = sub['cuota_away'].to_numpy(float)
        pl = sub['pliegue'].to_numpy(int)
        e, j = pl <= 2, pl >= 3
        print(f'\n=== {circ} · {len(sub)} partidos · elige {e.sum()} · juzga {j.sum()} ===')

        # ELECCIÓN en los pliegues tempranos, por log-loss
        mejor_w, mejor_ll = None, np.inf
        curva = []
        for w in REJILLA:
            p = w * pm[e] + (1 - w) * mk[e]
            ll = metricas(p, y[e])['logloss']
            curva.append((w, round(ll, 5)))
            if ll < mejor_ll:
                mejor_ll, mejor_w = ll, w
        print(f'  w* elegido en 0-2: {mejor_w:.2f} (log-loss {mejor_ll:.5f})')
        print('  curva:', ' '.join(f'{w:.2f}:{l:.4f}' for w, l in curva[::4]))

        # JUICIO en los tardíos
        print(f'\n  {"variante":22s} {"logloss":>9s} {"precisión":>10s} '
              f'{"ECE":>8s} {"Brier":>8s} {"n":>6s} {"ROI":>8s} {"p5":>8s}')
        print('  ' + '-' * 82)
        fila_circ = {}
        for nombre, w in ((f'PRODUCCIÓN w={W_ACTUAL}', W_ACTUAL),
                          (f'medido w={mejor_w:.2f}', mejor_w),
                          ('mercado solo w=0', 0.0),
                          ('modelo solo w=1', 1.0)):
            p = w * pm[j] + (1 - w) * mk[j]
            m = metricas(p, y[j])
            n, roi, p5 = roi_pick(p, y[j], c1[j], c2[j])
            fila_circ[nombre] = {**m, 'w': w, 'n': n, 'roi': roi, 'p5': p5}
            print(f'  {nombre:22s} {m["logloss"]:9.5f} {m["acc"]*100:9.2f} % '
                  f'{m["ece"]:8.4f} {m["brier"]:8.5f} {n:6d} '
                  f'{"—" if roi is None else f"{roi:+7.2f}%"} '
                  f'{"—" if p5 is None else f"{p5:+7.2f}%"}')
        salida[circ] = {'w_elegido': mejor_w, 'juicio': fila_circ}

        base = fila_circ[f'PRODUCCIÓN w={W_ACTUAL}']
        nuevo = fila_circ[f'medido w={mejor_w:.2f}']
        d_ll = base['logloss'] - nuevo['logloss']
        print(f'\n  → el w medido {"MEJORA" if d_ll > 0 else "EMPEORA"} la '
              f'log-loss en {d_ll:+.5f} y la precisión en '
              f'{(nuevo["acc"]-base["acc"])*100:+.2f} pp fuera de muestra')

    with open('_v94_w_tenis.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1, default=float)
    print('\n→ _v94_w_tenis.json')


if __name__ == '__main__':
    main()
