#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v85 — ¿Mejora encoger la probabilidad del modelo hacia un prior de ELO?

El problema
-----------
En la ficha de Puebla vs Chivas el modelo da Puebla 53,6 % con TODO en contra:
ELO 1349 vs 1597, forma 0,17 vs 0,58, encaja 2,17 vs 1,00, H2H −0,67. De las
quince features, solo dos favorecen a Puebla (remates a puerta a favor +0,83 y
xG a favor +0,13) — y el modelo se queda con esas dos.

La auditoría de monotonía (`_v85_auditoria_monotonia.py`) muestra que no es un
partido raro: de 56 ligas, **32 no responden bien a la fuerza de los equipos** y
**cuatro están invertidas** (a mejor ELO, MENOR probabilidad de ganar):

    china −0,288 · sudamericana −0,283 · ita_serie_b −0,206 · eng_league_two −0,171

Cuando hay mercado, `calibracion_mercado` ya encoge la probabilidad hacia él y
eso corrige el exceso. **Pero la ficha de partido no tiene mercado**, así que
ahí el modelo va suelto. Y es la pantalla donde el usuario juzga si el sistema
tiene sentido.

La hipótesis
------------
Un prior de ELO —la probabilidad que implica la diferencia de ELO con ventaja de
local— es un predictor pobre pero INSESGADO y monótono por construcción.
Encoger hacia él debería mejorar la calibración sin depender del mercado, igual
que encoger hacia el mercado mejoró cuando lo hay.

Se mide sobre el ledger de fútbol (36.006 filas con cuota) barriendo el peso.
Criterio: log-loss (calibración) y, por separado, ROI y p5 con los umbrales de
producción. Solo se adopta si no empeora ninguna de las dos.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('prior-elo')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 4000


def main():
    import recalibrate_from_history as rec
    d = rec.cargar(LEDGER)
    d = d[(d['deporte'] == 'Fútbol') & d['cuota_home'].notna()].copy()
    log.info(f'{len(d)} filas de fútbol con cuota')

    pm = d[['p_home', 'p_draw', 'p_away']].values.astype(float)
    y = d['resultado'].values.astype(int)
    cu = np.fmax(
        d[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(0).values.astype(float),
        np.nan_to_num(d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float),
                      nan=0.0))

    # El ledger no guarda el ELO de cada partido. Se usa como prior la TASA BASE
    # del fútbol (la distribución media de 1X2), que es el prior más neutro
    # posible y no requiere datos que no tengamos. Si encoger hacia AHÍ ya
    # mejora, encoger hacia un prior de ELO —que es estrictamente más
    # informativo— mejoraría al menos tanto.
    base = np.array([(y == 0).mean(), (y == 1).mean(), (y == 2).mean()])
    log.info(f'tasa base del ledger: local {base[0]:.3f} · empate {base[1]:.3f} '
             f'· visitante {base[2]:.3f}')

    def metricas(p):
        p = np.clip(p, 1e-9, 1)
        p = p / p.sum(axis=1, keepdims=True)
        ll = float(-np.log(p[np.arange(len(y)), y]).mean())
        acc = float((p.argmax(axis=1) == y).mean())
        f = np.arange(len(p))
        k = p.argmax(axis=1)
        prob, cuota = p[f, k], cu[f, k]
        sel = (prob > 0.55) & (cuota * prob - 1 > 0.03) & (cuota > 1.50)
        if sel.sum() < 60:
            return ll, acc, None, None, int(sel.sum())
        pnl = np.where(k[sel] == y[sel], cuota[sel] - 1, -1.0)
        rng = np.random.default_rng(31)
        bs = pnl[rng.integers(0, len(pnl), size=(N_BOOT, len(pnl)))].mean(axis=1)
        return (ll, acc, float(pnl.mean()), float(np.percentile(bs, 5)),
                int(sel.sum()))

    print('\n' + '=' * 78)
    print(f"{'w modelo':>9} {'log-loss':>10} {'precisión':>10} {'n':>6} "
          f"{'ROI':>9} {'p5':>9}")
    print('=' * 78)
    filas = []
    for w in (1.0, 0.95, 0.90, 0.85, 0.80, 0.70, 0.60, 0.50):
        p = w * pm + (1 - w) * base
        ll, acc, roi, p5, n = metricas(p)
        filas.append({'w': w, 'log_loss': round(ll, 5),
                      'precision': round(acc, 4), 'n': n,
                      'roi': roi, 'p5': p5})
        print(f"{w:9.2f} {ll:10.5f} {acc:10.4f} {n:6d} "
              f"{(roi if roi is not None else float('nan')):9.2%} "
              f"{(p5 if p5 is not None else float('nan')):9.2%}")
    print('=' * 78)

    base_f = filas[0]
    mejor_ll = min(filas, key=lambda r: r['log_loss'])
    print(f"\nMejor log-loss: w={mejor_ll['w']} "
          f"({mejor_ll['log_loss']:.5f} frente a {base_f['log_loss']:.5f} "
          f"sin encoger)")
    candidatos = [r for r in filas
                  if r['w'] < 1.0 and r['log_loss'] < base_f['log_loss']
                  and r['roi'] is not None and base_f['roi'] is not None
                  and r['roi'] >= base_f['roi'] and r['p5'] >= base_f['p5']]
    if candidatos:
        elegido = min(candidatos, key=lambda r: r['log_loss'])
        print(f"\nVEREDICTO: ADOPTAR w={elegido['w']} — mejora la calibración "
              f"SIN empeorar ROI ni p5.")
    else:
        print(f"\nVEREDICTO: NO ADOPTAR — ningún peso mejora la calibración "
              f"sin coste en ROI o p5.")
    json.dump(filas, open('_v85_prior_elo.json', 'w', encoding='utf-8'),
              indent=1, default=float)


if __name__ == '__main__':
    main()
