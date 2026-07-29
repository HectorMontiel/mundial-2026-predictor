#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v81 — «Máxima Confianza» incluye la banda que pierde dinero.

La pestaña selecciona por probabilidad ≥ 0,70 y NO pone techo. Pero la
calibración medida sobre 89.748 predicciones fuera de muestra dice esto:

    banda        n   dice    acierta   sesgo     ROI        p5
    0,70-0,75   72   71,7 %   69,4 %   +2,2 pp  +12,63 %   −2,21 %
    0,75+       45   79,6 %   57,8 %  +21,8 pp   −6,47 %  −27,09 %

Por encima de 0,75 el modelo promete casi 80 % y entrega 58 %. No es un matiz:
es el mayor sesgo de toda la tabla, y la banda pierde dinero.

En la pantalla de hoy, 5 de los 10 picks de «Máxima Confianza» estaban en esa
banda (80 %, 80 %, 78 %, 78 %, 75 %).

Este script comprueba si poner techo mejora, con bootstrap sobre la diferencia,
porque las muestras son pequeñas (72 y 45) y una diferencia grande en muestras
así puede ser ruido.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('techo')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 20000


def main():
    import recalibrate_from_history as rec
    d = rec.cargar(LEDGER)
    d = d.dropna(subset=['cuota_home'])

    pm = d[['p_home', 'p_draw', 'p_away']].values.astype(float)
    cu = np.fmax(
        d[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(0).values.astype(float),
        np.nan_to_num(d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float),
                      nan=0.0))
    y = d['resultado'].values.astype(int)
    f = np.arange(len(d))
    k = pm.argmax(axis=1)
    prob, cuota = pm[f, k], cu[f, k]
    acierto = (k == y)
    pnl = np.where(acierto, cuota - 1.0, -1.0)

    def bloque(sel, etiqueta):
        if sel.sum() < 20:
            print(f'  {etiqueta:28s} n={int(sel.sum()):4d}  muestra insuficiente')
            return None
        g = pnl[sel]
        rng = np.random.default_rng(19)
        bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
        r = {'n': int(len(g)), 'roi': float(g.mean()),
             'p5': float(np.percentile(bs, 5)),
             'acierto': float(acierto[sel].mean()),
             'promete': float(prob[sel].mean())}
        print(f"  {etiqueta:28s} n={r['n']:4d}  promete {r['promete']:.1%}  "
              f"acierta {r['acierto']:.1%}  ROI {r['roi']:+7.2%}  "
              f"p5 {r['p5']:+7.2%}")
        return r

    print('\nSelección actual y alternativas (cuota > 1,50, como la pestaña):')
    base_ok = cuota > 1.50
    sel_actual = (prob >= 0.70) & base_ok
    sel_techo = (prob >= 0.70) & (prob < 0.75) & base_ok
    sel_alta = (prob >= 0.75) & base_ok

    r_act = bloque(sel_actual, 'ACTUAL  prob >= 0,70')
    r_tec = bloque(sel_techo, 'CON TECHO  0,70 <= p < 0,75')
    r_alt = bloque(sel_alta, 'la banda excluida  p >= 0,75')

    if not (r_act and r_tec and r_alt):
        return

    # ¿es real la diferencia entre la banda buena y la excluida?
    ga, gb = pnl[sel_techo], pnl[sel_alta]
    rng = np.random.default_rng(23)
    da = ga[rng.integers(0, len(ga), size=(N_BOOT, len(ga)))].mean(axis=1)
    db = gb[rng.integers(0, len(gb), size=(N_BOOT, len(gb)))].mean(axis=1)
    dif = da - db
    p5d, p95d = np.percentile(dif, [5, 95])
    print(f"\nDiferencia de ROI (banda 0,70-0,75 menos banda 0,75+):")
    print(f"  media {dif.mean():+.2%}   IC 90 % [{p5d:+.2%}, {p95d:+.2%}]   "
          f"fracción a favor del techo {float((dif > 0).mean()):.1%}")

    # comparación directa de lo que importa: la selección con techo vs sin él
    rng2 = np.random.default_rng(29)
    gact = pnl[sel_actual]
    dact = gact[rng2.integers(0, len(gact), size=(N_BOOT, len(gact)))].mean(axis=1)
    dtec = ga[rng2.integers(0, len(ga), size=(N_BOOT, len(ga)))].mean(axis=1)
    mejora = dtec - dact
    print(f"\nMejora de poner techo frente a la selección actual:")
    print(f"  media {mejora.mean():+.2%}   "
          f"IC 90 % [{np.percentile(mejora,5):+.2%}, "
          f"{np.percentile(mejora,95):+.2%}]   "
          f"fracción positiva {float((mejora > 0).mean()):.1%}")

    veredicto = ('PONER TECHO' if float((mejora > 0).mean()) >= 0.90
                 else 'no concluyente al 90 %')
    print(f"\nVEREDICTO: {veredicto}")

    json.dump({'actual': r_act, 'con_techo': r_tec, 'banda_excluida': r_alt,
               'frac_mejora': float((mejora > 0).mean()),
               'veredicto': veredicto},
              open('_v81_confianza_techo.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
