#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99 — KBO: alternativas concretas, medidas sobre la cuota de cierre REAL.

El modelo no bate al mercado (v98: ROI −9,1 %, Brier 0,2492 contra 0,2411).
Antes de darlo por cerrado hay cosas que probar que NO son «entrenar otra vez»,
y todas se pueden medir con los 204 cierres que ya tenemos:

  A. **Mezcla con el mercado.** Si el precio sabe más, la pregunta no es si el
     modelo gana, sino cuánto peso merece. Se busca el `w` que minimiza el
     Brier de `w·modelo + (1−w)·mercado`. Si el óptimo es w>0, el modelo aporta
     información aunque solo no gane; si es w=0, no aporta nada.
  B. **Sólo donde discrepa poco.** La v87 midió que cuando el modelo se aleja
     del mercado suele equivocarse él. Se comprueba si hay una banda de
     discrepancia donde sí acierte.
  C. **Sólo favoritos claros del mercado.** Es donde el béisbol es más
     predecible y donde la MLB tiene su piso de 0,58.
  D. **Contra el cierre, apostando al lado que el MERCADO no favorece** (test
     de contraste: si el modelo fuese sistemáticamente contrario, invertirlo
     daría edge — es la comprobación de que no hay señal, ni siquiera al revés).
"""
import io
import json
import sys

import numpy as np
import pandas as pd

from _v98_backtest_kbo import predicciones_oos

BOOT = 4000
SEMILLA = 99


def boot(pnl, rng):
    if len(pnl) < 20:
        return float('nan'), float('nan')
    m = np.array([pnl[rng.integers(0, len(pnl), len(pnl))].mean() for _ in range(BOOT)])
    return float(np.percentile(m, 5)), float(m.mean())


def main():
    oos = predicciones_oos()
    cu = pd.read_csv('cuotas_kbo_cierre.csv')
    j = cu.merge(oos, on=['fecha', 'home', 'away'], how='inner')
    print(f'cruzados: {len(j)}')
    p = j.p_home.to_numpy()
    gh = j.gana_home_y.to_numpy().astype(float)
    oh, oa = j.odd_home.to_numpy(), j.odd_away.to_numpy()
    imp = (1 / oh) / (1 / oh + 1 / oa)
    rng = np.random.default_rng(SEMILLA)
    out = {}

    print()
    print('--- A. ¿Cuánto peso merece el modelo en una mezcla con el mercado? ---')
    mejor_w, mejor_b = None, np.inf
    for w in np.arange(0, 1.01, 0.05):
        q = w * p + (1 - w) * imp
        b = float(np.mean((q - gh) ** 2))
        if b < mejor_b:
            mejor_w, mejor_b = float(w), b
    b_mkt = float(np.mean((imp - gh) ** 2))
    b_mod = float(np.mean((p - gh) ** 2))
    print(f'   Brier: mercado {b_mkt:.4f} · modelo {b_mod:.4f} · '
          f'mejor mezcla {mejor_b:.4f} con w={mejor_w:.2f}')
    print(f"   -> {'el modelo APORTA información' if mejor_w > 0.001 else 'el modelo NO aporta nada sobre el precio'}")
    out['mezcla'] = {'w_optimo': mejor_w, 'brier_mezcla': mejor_b,
                     'brier_mercado': b_mkt, 'brier_modelo': b_mod}

    print()
    print('--- B. ¿Hay una banda de discrepancia donde el modelo acierte? ---')
    dif = np.abs(p - imp)
    for lo, hi in ((0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.0)):
        m = (dif >= lo) & (dif < hi)
        if m.sum() < 15:
            print(f'   |modelo−mercado| en [{lo:.2f},{hi:.2f}): n={int(m.sum())} (muestra corta)')
            continue
        acc_mod = float(((p[m] >= 0.5) == gh[m].astype(bool)).mean())
        acc_mkt = float(((imp[m] >= 0.5) == gh[m].astype(bool)).mean())
        print(f'   |modelo−mercado| en [{lo:.2f},{hi:.2f}): n={int(m.sum()):>3} '
              f'· acierta modelo {acc_mod:.3f} · mercado {acc_mkt:.3f}')

    print()
    print('--- C. Sólo favoritos claros del mercado (imp >= 0,58, piso de MLB) ---')
    for piso in (0.55, 0.58, 0.65):
        m = imp >= piso
        if m.sum() < 20:
            continue
        pnl = np.where(gh[m].astype(bool), oh[m] - 1, -1.0)
        p5, med = boot(pnl, rng)
        print(f'   imp>={piso:.2f}: n={int(m.sum()):>3} ROI={med:+.2%} p5={p5:+.2%}')
        out[f'fav_{piso}'] = {'n': int(m.sum()), 'roi': med, 'p5': p5}

    print()
    print('--- D. Contraste: ¿y si se apuesta AL REVÉS que el modelo? ---')
    lado_mod = p >= 0.5
    pnl_inv = np.where(np.where(~lado_mod, gh.astype(bool), ~gh.astype(bool)),
                       np.where(~lado_mod, oh - 1, oa - 1), -1.0)
    p5i, medi = boot(pnl_inv, rng)
    print(f'   invertido: n={len(pnl_inv)} ROI={medi:+.2%} p5={p5i:+.2%}')
    print('   (si esto tampoco es positivo, no hay señal explotable en ningún sentido)')
    out['invertido'] = {'n': int(len(pnl_inv)), 'roi': medi, 'p5': p5i}

    json.dump(out, open('_v99_alternativas_kbo.json', 'w'), indent=1)
    print('\n-> _v99_alternativas_kbo.json')


if __name__ == '__main__':
    main()
