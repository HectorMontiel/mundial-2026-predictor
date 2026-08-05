#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — ¿Hace falta ingerir cuotas sudamericanas para calibrar las ligas de verano?

La propuesta que se valida
--------------------------
«La calibración de verano sigue sin poder medir un peso w propio para ligas
como Argentina o Liga MX, por falta de cuotas de cierre en el ledger. Retomar
la ingesta de BetExplorer para poder calcular ese peso.»

Lo primero es comprobar la premisa, no el remedio. Y la premisa es FALSA para
las ligas grandes: el ledger ya trae 1.534 filas de Argentina con cuota de
Pinnacle, 1.090 de Liga MX, 1.276 de Brasil y 1.562 de MLS. O sea que el peso
por liga se puede medir HOY, sin scrapear nada. Este script lo mide.

Método (el de las reglas de oro)
--------------------------------
El `w` se ELIGE en los pliegues 0-2 y se JUZGA en los pliegues 3-4, que no
participan en la elección. Se compara contra la política vigente (w global
0,25) sobre exactamente la misma población, y se reporta log-loss, ECE,
precisión y el ROI/p5 de la apuesta que saldría.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

W_GLOBAL = 0.25
REJILLA = [round(x, 2) for x in np.arange(0.0, 1.01, 0.05)]
MIN_FILAS = 200          # por debajo de esto, medir un w propio es leer ruido


def devig(ch, cd, ca):
    """Probabilidad justa del mercado (método de potencia, el de cuotas_multi)."""
    inv = np.stack([1.0 / ch, 1.0 / cd, 1.0 / ca], axis=1)
    s = inv.sum(axis=1, keepdims=True)
    return inv / s


def metricas(p, y):
    """log-loss, ECE (10 bandas sobre el argmax) y precisión."""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = float(-np.mean(np.log(p[np.arange(len(y)), y])))
    conf = p.max(axis=1)
    pred = p.argmax(axis=1)
    acierta = (pred == y).astype(float)
    ece, n = 0.0, len(y)
    for lo in np.arange(0.0, 1.0, 0.1):
        m = (conf >= lo) & (conf < lo + 0.1)
        if m.sum():
            ece += (m.sum() / n) * abs(acierta[m].mean() - conf[m].mean())
    return ll, float(ece), float(acierta.mean())


def roi_p5(p, y, cuotas, n_boot=2000, semilla=7):
    """ROI de apostar al argmax con la mejor cuota disponible, y su bootstrap p5."""
    pred = p.argmax(axis=1)
    precio = cuotas[np.arange(len(pred)), pred]
    ok = np.isfinite(precio) & (precio > 1)
    if ok.sum() < 30:
        return None, None, int(ok.sum())
    g = np.where(pred[ok] == y[ok], precio[ok] - 1.0, -1.0)
    rng = np.random.default_rng(semilla)
    boots = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)]
    return float(g.mean() * 100), float(np.percentile(boots, 5) * 100), int(ok.sum())


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    # sólo filas con ancla sharp: es contra lo que se encoge en producción
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away',
                           'p_home', 'p_draw', 'p_away', 'resultado'])
    for c in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[c] > 1.0]
    print(f'filas de fútbol con ancla de Pinnacle: {len(df)} · '
          f'ligas: {df["liga"].nunique()}\n')

    filas = []
    for liga, g in df.groupby('liga'):
        if len(g) < MIN_FILAS:
            continue
        elige = g[g['pliegue'] <= 2]
        juzga = g[g['pliegue'] >= 3]
        if len(elige) < 100 or len(juzga) < 60:
            continue

        def prep(sub):
            pm = sub[['p_home', 'p_draw', 'p_away']].to_numpy(float)
            pm = pm / pm.sum(axis=1, keepdims=True)
            mk = devig(sub['pin_home'].to_numpy(float),
                       sub['pin_draw'].to_numpy(float),
                       sub['pin_away'].to_numpy(float))
            y = sub['resultado'].to_numpy(int)
            cu = sub[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(float)
            # sin cuota apostable se usa la de Pinnacle (peor precio, más honesto)
            pin = sub[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float)
            cu = np.where(np.isfinite(cu) & (cu > 1), cu, pin)
            return pm, mk, y, cu

        pm_e, mk_e, y_e, _ = prep(elige)
        pm_j, mk_j, y_j, cu_j = prep(juzga)

        # ELECCIÓN del w en los pliegues tempranos, por log-loss
        mejor_w, mejor_ll = None, np.inf
        for w in REJILLA:
            ll, _, _ = metricas(w * pm_e + (1 - w) * mk_e, y_e)
            if ll < mejor_ll:
                mejor_ll, mejor_w = ll, w

        # JUICIO en los pliegues tardíos
        p_liga = mejor_w * pm_j + (1 - mejor_w) * mk_j
        p_glob = W_GLOBAL * pm_j + (1 - W_GLOBAL) * mk_j
        ll_l, ece_l, acc_l = metricas(p_liga, y_j)
        ll_g, ece_g, acc_g = metricas(p_glob, y_j)
        roi_l, p5_l, n_l = roi_p5(p_liga, y_j, cu_j)
        roi_g, p5_g, _ = roi_p5(p_glob, y_j, cu_j)
        filas.append({
            'liga': liga, 'n': len(g), 'n_juzga': len(juzga),
            'w_liga': mejor_w,
            'll_liga': ll_l, 'll_global': ll_g, 'd_ll': ll_g - ll_l,
            'ece_liga': ece_l, 'ece_global': ece_g,
            'acc_liga': acc_l, 'acc_global': acc_g,
            'roi_liga': roi_l, 'roi_global': roi_g,
            'p5_liga': p5_l, 'p5_global': p5_g, 'n_apuestas': n_l})

    res = pd.DataFrame(filas).sort_values('n', ascending=False)
    print(f'{"liga":22s} {"n":>5s} {"w":>5s} {"logloss w_liga":>14s} '
          f'{"logloss global":>14s} {"gana":>6s} {"ECE liga":>9s} {"ECE glob":>9s}')
    print('-' * 92)
    for _, r in res.iterrows():
        gana = 'liga' if r['d_ll'] > 0 else 'GLOBAL'
        print(f'{r["liga"]:22s} {r["n"]:5.0f} {r["w_liga"]:5.2f} '
              f'{r["ll_liga"]:14.5f} {r["ll_global"]:14.5f} {gana:>6s} '
              f'{r["ece_liga"]:9.4f} {r["ece_global"]:9.4f}')

    gana_liga = int((res['d_ll'] > 0).sum())
    print('-' * 92)
    print(f'\nVEREDICTO en los pliegues 3-4 (que no eligieron el w):')
    print(f'  el w por liga gana en {gana_liga} de {len(res)} ligas '
          f'({100*gana_liga/max(len(res),1):.0f} %)')
    print(f'  log-loss agregada  w por liga {res["ll_liga"].mean():.5f} · '
          f'w global {res["ll_global"].mean():.5f}')
    print(f'  ECE agregada       w por liga {res["ece_liga"].mean():.5f} · '
          f'w global {res["ece_global"].mean():.5f}')
    print(f'  precisión          w por liga {res["acc_liga"].mean():.4f} · '
          f'w global {res["acc_global"].mean():.4f}')
    sub = res.dropna(subset=['roi_liga', 'roi_global'])
    if len(sub):
        print(f'  ROI medio          w por liga {sub["roi_liga"].mean():+.2f} % · '
              f'w global {sub["roi_global"].mean():+.2f} %')
        print(f'  p5 medio           w por liga {sub["p5_liga"].mean():+.2f} % · '
              f'w global {sub["p5_global"].mean():+.2f} %')

    # ¿cuántas de las ligas que JUEGAN EN VERANO se pueden medir ya?
    verano = {'argentina', 'liga_mx', 'brasil', 'mls', 'suecia', 'noruega',
              'finlandia', 'irlanda', 'china', 'rus_premier', 'jpn_j1',
              'sco_premiership'}
    med = res[res['liga'].isin(verano)]
    print(f'\nligas de verano YA medibles con el ledger actual: {len(med)} '
          f'({", ".join(med["liga"])})')

    res.to_json('_v90_w_verano.json', orient='records', indent=1)
    print('\n→ _v90_w_verano.json')


if __name__ == '__main__':
    main()
