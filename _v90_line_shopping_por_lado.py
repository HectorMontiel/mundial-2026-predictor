#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — ¿El edge del line shopping es igual en los tres lados del 1X2?

La hipótesis
------------
El canal de valor exige `prob_justa ≥ 0,30` (v80). El empate ronda el 26 % de
probabilidad, así que ese piso **excluye casi todos los empates** — y el
empate es justo donde cabría esperar que las casas blandas estén peor: el
dinero recreativo va a equipos, no a la X, así que las casas ajustan la X con
menos presión y con menos información.

Nadie lo ha mirado por separado: el piso de 0,30 se eligió sobre el agregado.
Si el empate tuviera edge, el piso lo estaría tirando a la basura; y si lo que
tiene es un agujero, conviene saberlo antes de bajarlo.

Método
------
Se parte el canal por LADO y se mide en las dos mitades del ledger (pliegues
0-2 y 3-4). Sólo cuenta lo que es positivo en LAS DOS, y con una vecindad
contigua: la lección de la v83 es que un edge real se ve como una superficie
estable (16 de 20 configuraciones), no como un pico suelto.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
MARGEN_EV = 0.01
LADOS = ('local', 'empate', 'visitante')


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


def boot_p5(g, n_boot=4000, semilla=23):
    rng = np.random.default_rng(semilla)
    return float(np.percentile(
        [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)], 5) * 100)


def canal(mk, cu, y, prob_min):
    """Apuestas del canal de line shopping con ese piso de probabilidad."""
    idx = np.arange(len(mk))
    ev = np.where(np.isfinite(cu) & (cu > 1), cu * mk - 1.0, -9.9)
    k = ev.argmax(axis=1)
    ok = (ev[idx, k] > MARGEN_EV) & (mk[idx, k] >= prob_min) & (cu[idx, k] > 1)
    return k[ok], cu[idx, k][ok], y[ok], mk[idx, k][ok]


def resumen(k, precio, y, sel):
    if sel.sum() < 30:
        return None
    g = np.where(k[sel] == y[sel], precio[sel] - 1.0, -1.0)
    return {'n': int(sel.sum()), 'roi': float(g.mean() * 100), 'p5': boot_p5(g),
            'acierto': float((k[sel] == y[sel]).mean() * 100)}


def fmt(r):
    return ('        —        ' if r is None else
            f'{r["n"]:5d} {r["roi"]:+7.2f}% {r["p5"]:+7.2f}%')


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away', 'resultado'])
    for c in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[c] > 1.0]
    mk = devig_potencia(df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float))
    y = df['resultado'].to_numpy(int)
    cu = df[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(float)
    pl = df['pliegue'].to_numpy(int)
    e, j = pl <= 2, pl >= 3

    # --- 1. el canal VIGENTE (piso 0,30), partido por lado -----------------
    print('=== 1. El canal desplegado (piso 0,30), desglosado por lado ===')
    print(f'{"lado":12s} {"pliegues 0-2 (n/ROI/p5)":>26s}   {"pliegues 3-4 (n/ROI/p5)":>26s}')
    print('-' * 70)
    ke, pe, ye, _ = canal(mk[e], cu[e], y[e], 0.30)
    kj, pj, yj, _ = canal(mk[j], cu[j], y[j], 0.30)
    for c, nom in enumerate(LADOS):
        print(f'{nom:12s} {fmt(resumen(ke, pe, ye, ke == c)):>26s}   '
              f'{fmt(resumen(kj, pj, yj, kj == c)):>26s}')
    print(f'{"TODOS":12s} {fmt(resumen(ke, pe, ye, np.ones(len(ke), bool))):>26s}   '
          f'{fmt(resumen(kj, pj, yj, np.ones(len(kj), bool))):>26s}')

    # --- 2. bajar el piso: ¿qué aparece? -----------------------------------
    print('\n=== 2. Bajando el piso de probabilidad (aparecen los empates) ===')
    print(f'{"piso":>6s} {"lado":10s} {"pliegues 0-2":>26s}   {"pliegues 3-4":>26s} {"robusto":>8s}')
    print('-' * 82)
    filas = []
    for piso in (0.30, 0.27, 0.24, 0.20, 0.15):
        ke, pe, ye, _ = canal(mk[e], cu[e], y[e], piso)
        kj, pj, yj, _ = canal(mk[j], cu[j], y[j], piso)
        for c, nom in enumerate(LADOS):
            re_, rj_ = resumen(ke, pe, ye, ke == c), resumen(kj, pj, yj, kj == c)
            if re_ is None or rj_ is None:
                continue
            rob = re_['p5'] > 0 and rj_['p5'] > 0
            filas.append({'piso': piso, 'lado': nom, 'elige': re_, 'juzga': rj_,
                          'robusto': rob})
            print(f'{piso:6.2f} {nom:10s} {fmt(re_):>26s}   {fmt(rj_):>26s} '
                  f'{"SÍ" if rob else "no":>8s}')

    # --- 3. veredicto por lado ---------------------------------------------
    print('\n=== 3. Veredicto ===')
    for nom in LADOS:
        sub = [f for f in filas if f['lado'] == nom]
        rob = [f for f in sub if f['robusto']]
        print(f'  {nom:11s} configuraciones robustas (p5>0 en las DOS mitades): '
              f'{len(rob)}/{len(sub)}'
              + (f'  → pisos {[f["piso"] for f in rob]}' if rob else ''))

    with open('_v90_line_shopping_por_lado.json', 'w', encoding='utf-8') as f:
        json.dump(filas, f, ensure_ascii=False, indent=1, default=float)
    print('\n→ _v90_line_shopping_por_lado.json')


if __name__ == '__main__':
    main()
