#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v82 — La Capa 1 está vacía porque buscamos el edge donde no está.

El razonamiento
---------------
Llevamos varias versiones intentando que los MODELOS de tenis y MLB batan al
mercado, y las mediciones dicen que no lo hacen:

    tenis  log-loss modelo 0,6109  ·  mercado 0,5831
    MLB    log-loss modelo 0,6828  ·  mercado 0,6687

Y cada intento de mejorarlos ha fallado por el mismo sitio: features de nivel
y de saque (v69, v79), features de equipo (v79), features de abridor (v80).
Todas mejoran la precisión y ninguna mejora la rentabilidad.

Mientras tanto, **lo único con edge validado y estable en todo el proyecto no
usa el modelo para nada**: `valor_vs_sharp` — apostar donde una casa blanda
paga por encima del precio justo de Pinnacle. Medido en la v80 sobre 26.647
partidos de fútbol, eligiendo parámetros en el 70 % más antiguo y validando en
el 30 % más reciente: **p5 +3,92 % y +3,91 %**, casi idénticos.

La hipótesis de esta versión es sencilla y no requiere ningún modelo nuevo:

    Si el edge está en la DISCREPANCIA ENTRE CASAS y no en nuestro modelo,
    debería existir también en tenis y en MLB, donde tenemos las mismas casas
    (Pinnacle, Bovada, Playdoit).

Eso convertiría el problema «los modelos de tenis y MLB no baten al mercado»
en irrelevante para la Capa 1: no hace falta batir al mercado, hace falta
encontrar a la casa que se ha quedado descolgada.

Cómo se mide, sin trampas
-------------------------
El ledger guarda por partido la cuota de cierre genérica (`cuota_*`) y la de
Pinnacle (`pin_*`). Con las dos se reconstruye la estrategia exactamente:
apostar la selección cuyo precio disponible supera al precio justo de Pinnacle
por encima de un margen, y liquidar con el resultado real.

Se aplican los mismos guardarraíles que la v80 dejó establecidos:
  · elección de parámetros en el 70 % antiguo, validación en el 30 % reciente;
  · el criterio es ROI **y** bootstrap p5, los dos positivos;
  · se exige que la configuración funcione en LOS DOS periodos, porque el
    máximo del barrido ya demostró hundirse fuera de muestra (+10,09 % → −9,44 %).
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('vs-deportes')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 5000
MIN_N = 60
CORTE = 0.70


def devig_dos(cu):
    """Dos vías: proporcional y potencia coinciden en la práctica."""
    inv = 1.0 / cu
    return inv / inv.sum(axis=1, keepdims=True)


def evaluar(cu, justa, res_gana0, margen, pmin, semilla=5):
    ev = cu * justa - 1.0
    sel = (ev > margen) & (justa > pmin)
    if sel.sum() < MIN_N:
        return None
    idx = np.argwhere(sel)
    gan = []
    for i, j in idx:
        acierto = (j == 0) if res_gana0[i] else (j == 1)
        gan.append(cu[i, j] - 1.0 if acierto else -1.0)
    g = np.array(gan, float)
    rng = np.random.default_rng(semilla)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5)),
            'hit': float((g > 0).mean())}


def analizar(d, etiqueta):
    """d: filas de un deporte a dos vías con cuota tomable y Pinnacle."""
    cu = d[['cuota_home', 'cuota_away']].values.astype(float)
    pin = d[['pin_home', 'pin_away']].values.astype(float)
    justa = devig_dos(pin)
    gana0 = (d['resultado'].values.astype(int) == 0)

    n = len(d)
    c = int(n * CORTE)
    print(f'\n{"="*80}\n{etiqueta}  ·  {n} partidos con precio Y ancla de Pinnacle')
    print('='*80)
    print(f"{'margen':>7} {'pmin':>6} | {'n(70%)':>7} {'ROI':>8} {'p5':>8} "
          f"| {'n(30%)':>7} {'ROI':>8} {'p5':>8}  ambos")
    print('-'*80)
    filas, robustas = [], []
    for margen in (0.00, 0.01, 0.02, 0.03, 0.05):
        for pmin in (0.0, 0.30, 0.40, 0.50):
            a = evaluar(cu[:c], justa[:c], gana0[:c], margen, pmin)
            b = evaluar(cu[c:], justa[c:], gana0[c:], margen, pmin, semilla=11)
            if not a or not b:
                continue
            ok = a['p5'] > 0 and b['p5'] > 0
            if ok:
                robustas.append((margen, pmin, a, b))
            print(f"{margen:7.0%} {pmin:6.0%} | {a['n']:7d} {a['roi']:8.2%} "
                  f"{a['p5']:8.2%} | {b['n']:7d} {b['roi']:8.2%} {b['p5']:8.2%}"
                  f"  {'SI' if ok else ''}")
            filas.append({'margen': margen, 'pmin': pmin,
                          'eleccion': a, 'validacion': b, 'robusta': ok})
    if robustas:
        # entre las robustas, la de mayor muestra en validación (más fiable)
        mejor = max(robustas, key=lambda x: x[3]['n'])
        print(f"\n  ROBUSTA elegida: margen {mejor[0]:.0%} · prob mínima "
              f"{mejor[1]:.0%}")
        print(f"    elección  n={mejor[2]['n']:5d} ROI {mejor[2]['roi']:+.2%} "
              f"p5 {mejor[2]['p5']:+.2%}")
        print(f"    validación n={mejor[3]['n']:5d} ROI {mejor[3]['roi']:+.2%} "
              f"p5 {mejor[3]['p5']:+.2%}")
        print(f"\n  VEREDICTO: EDGE VALIDADO en {etiqueta}")
    else:
        print(f"\n  VEREDICTO: ninguna configuración con p5 positivo en LOS DOS "
              f"periodos → sin edge robusto en {etiqueta}")
    return filas, (robustas[0] if robustas else None)


def main():
    d = pd.read_csv(LEDGER, low_memory=False)
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['fecha']).sort_values('fecha')

    salida = {}
    for dep in ('Tenis', 'MLB'):
        g = d[d['deporte'] == dep]
        ok = (g[['cuota_home', 'cuota_away']].notna().all(axis=1) &
              g[['pin_home', 'pin_away']].notna().all(axis=1) &
              (g[['cuota_home', 'cuota_away']] > 1).all(axis=1) &
              (g[['pin_home', 'pin_away']] > 1).all(axis=1))
        g = g[ok].reset_index(drop=True)
        if len(g) < 500:
            print(f'\n{dep}: solo {len(g)} filas con ancla de Pinnacle en el '
                  f'ledger — la estrategia no se puede medir aquí.')
            salida[dep] = {'n': int(len(g)), 'medible': False}
            continue
        filas, mejor = analizar(g, dep)
        salida[dep] = {'n': int(len(g)), 'medible': True, 'filas': filas,
                       'robusta': bool(mejor)}

    json.dump(salida, open('_v82_valor_sharp_deportes.json', 'w',
                           encoding='utf-8'), indent=1, ensure_ascii=False,
              default=float)


if __name__ == '__main__':
    main()
