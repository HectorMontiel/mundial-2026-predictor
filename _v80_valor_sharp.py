#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — ¿Tiene edge la estrategia que HOY ocupa toda la Capa 1?

El hallazgo
-----------
Persiguiendo por qué ningún pick de élite salía calibrado se llegó a algo más
gordo: **la Capa 1 de hoy no contiene ni un solo pick del modelo**. Los diez
picks vienen de `cuotas_multi.valor_vs_sharp` (el «valor de mercado» de la
v71), que se añaden DIRECTAMENTE a `elite_fix`:

  · no pasan por `_mercados_del_partido`, así que nunca se calibran;
  · **no pasan por `pasa_capa1`**, así que se saltan el umbral de
    probabilidad, la banda de EV y el filtro de convicción;
  · su `prob` no es la del modelo, es la probabilidad justa de PINNACLE.

De ahí lo que ve el usuario: «Empate · EV +9,5 % · prob 29 %». Un pick de
élite con 29 % de probabilidad.

La idea de la v71 es razonable —una casa blanda pagando por encima del precio
justo de la casa más eficiente es edge que no depende de que el modelo acierte—
pero **nunca se midió**. Y el +6,72 % de ROI que el sistema exhibe NO la
incluye: esa cifra sale de los picks del modelo con sus filtros.

Qué se mide aquí
----------------
El ledger tiene, por partido, la cuota de cierre genérica (`cuota_*`) y la de
Pinnacle (`pin_*`). Eso permite reconstruir la estrategia tal cual: apostar la
selección donde el precio disponible supera al precio justo de Pinnacle por
encima de un margen, y liquidar con el resultado real.

Se barre el margen mínimo para ver si existe algún punto rentable, con el
criterio de siempre: ROI positivo Y bootstrap p5 positivo.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('valor-sharp')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 5000
MIN_N = 60


def devig_potencia(cuotas):
    """Probabilidad justa por el método de potencia (el que usa el proyecto)."""
    inv = 1.0 / np.clip(cuotas, 1.0001, None)
    k = np.ones(len(cuotas))
    for _ in range(60):
        s = (inv ** k[:, None]).sum(axis=1)
        err = s - 1.0
        if np.all(np.abs(err) < 1e-10):
            break
        k += err * 0.5
        k = np.clip(k, 0.2, 5.0)
    p = inv ** k[:, None]
    return p / p.sum(axis=1, keepdims=True)


def main():
    d = pd.read_csv(LEDGER, low_memory=False)
    d = d[d['deporte'] == 'Fútbol']
    # hace falta AMBOS: precio tomable y ancla sharp
    ok = (d[['cuota_home', 'cuota_draw', 'cuota_away']].notna().all(axis=1) &
          d[['pin_home', 'pin_draw', 'pin_away']].notna().all(axis=1))
    d = d[ok].copy()
    log.info(f'{len(d)} partidos con cuota tomable Y cuota de Pinnacle')
    if len(d) < 500:
        print('muestra insuficiente para medir la estrategia')
        return

    cu = d[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    pin = d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float)
    res = d['resultado'].values.astype(int)
    justa = devig_potencia(pin)

    # EV de apostar cada selección al precio disponible usando la prob de Pinnacle
    ev = cu * justa - 1.0

    print('\n' + '=' * 84)
    print(f"{'margen EV':>10} {'n':>7} {'ROI':>9} {'p5':>9} {'p95':>9} "
          f"{'acierto':>9}   veredicto")
    print('=' * 84)
    filas = []
    for margen in (0.00, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10):
        sel = ev > margen
        if sel.sum() < MIN_N:
            print(f'{margen:10.0%} {int(sel.sum()):7d}   muestra insuficiente')
            continue
        idx = np.argwhere(sel)
        gan = np.array([cu[i, j] - 1.0 if res[i] == j else -1.0
                        for i, j in idx], float)
        rng = np.random.default_rng(5)
        bs = gan[rng.integers(0, len(gan), size=(N_BOOT, len(gan)))].mean(axis=1)
        p5 = float(np.percentile(bs, 5))
        p95 = float(np.percentile(bs, 95))
        roi = float(gan.mean())
        ver = 'EDGE VALIDADO' if (roi > 0 and p5 > 0) else 'sin edge'
        print(f'{margen:10.0%} {len(gan):7d} {roi:9.2%} {p5:9.2%} {p95:9.2%} '
              f'{float((gan>0).mean()):9.1%}   {ver}')
        filas.append({'margen': margen, 'n': int(len(gan)),
                      'roi': round(roi, 4), 'p5': round(p5, 4),
                      'p95': round(p95, 4),
                      'hit': round(float((gan > 0).mean()), 4),
                      'edge': bool(roi > 0 and p5 > 0)})
    print('=' * 84)

    # ¿y si además se exige una probabilidad mínima? (los picks de hoy tienen
    # 20-40 %, que es justo lo que `pasa_capa1` filtraría)
    print('\nMismo barrido EXIGIENDO ADEMÁS probabilidad mínima (margen 3 %):')
    print(f"{'prob min':>9} {'n':>7} {'ROI':>9} {'p5':>9}   veredicto")
    print('-' * 60)
    for pmin in (0.0, 0.20, 0.30, 0.40, 0.50, 0.55):
        sel = (ev > 0.03) & (justa > pmin)
        if sel.sum() < MIN_N:
            print(f'{pmin:9.0%} {int(sel.sum()):7d}   muestra insuficiente')
            continue
        idx = np.argwhere(sel)
        gan = np.array([cu[i, j] - 1.0 if res[i] == j else -1.0
                        for i, j in idx], float)
        rng = np.random.default_rng(5)
        bs = gan[rng.integers(0, len(gan), size=(N_BOOT, len(gan)))].mean(axis=1)
        p5 = float(np.percentile(bs, 5))
        roi = float(gan.mean())
        ver = 'EDGE VALIDADO' if (roi > 0 and p5 > 0) else 'sin edge'
        print(f'{pmin:9.0%} {len(gan):7d} {roi:9.2%} {p5:9.2%}   {ver}')
        filas.append({'margen': 0.03, 'prob_min': pmin, 'n': int(len(gan)),
                      'roi': round(roi, 4), 'p5': round(p5, 4),
                      'edge': bool(roi > 0 and p5 > 0)})

    json.dump(filas, open('_v80_valor_sharp.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
