#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Auditoría del hallazgo del empate, que era demasiado bueno.

El A/B dio para el empate una mejora de log-loss de +0,028 con p5 +0,025 y
P(mejora>0)=100 %. Es un orden de magnitud más que cualquier feature adoptada en
el proyecto (el IDF en tenis mejoró +0,0006). La regla de la casa dice que un
resultado así es fuga, overfitting o bug hasta que se demuestre lo contrario.

Tres controles, cada uno mata una explicación distinta:

  1. CONTEXTO PERMUTADO — se barajan las filas de las features de contexto,
     rompiendo su vínculo con el partido pero conservando su distribución. Si la
     mejora sobrevive, no venía del contexto.
  2. LIGA COMO CONTROL — se añade la tasa base de empate de la liga a AMBOS
     modelos. Si la mejora de B se evapora, lo que el contexto aportaba era
     identidad de liga (un efecto fijo), no circunstancia del partido anterior.
  3. FEATURE A FEATURE — cuál de las cinco columnas carga con la mejora. Si es
     DIFF_CARGA o DIFF_DESCANSO —las dos que más varían por calendario de liga—
     refuerza la sospecha del punto 2.
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contexto_previo as cp
from _v101_ab_contexto_futbol import (BOOT, JUICIO_DESDE, N_PLIEGUES, SEMILLA,
                                      _logit, _wf, cargar_contexto)


def medir(p_modelo, y, extras_a, extras_b, fecha, etiqueta):
    orden = np.argsort(fecha.to_numpy(), kind='stable')
    p_modelo, y = p_modelo[orden], y[orden]
    n = len(y)
    base = _logit(p_modelo).reshape(-1, 1)
    Xa = np.column_stack([base] + ([extras_a[orden]] if extras_a is not None else []))
    Xb = np.column_stack([base] + ([extras_a[orden]] if extras_a is not None else [])
                         + [extras_b[orden]])
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    pa, pb = _wf(Xa, y, bordes), _wf(Xb, y, bordes)
    msk = ~np.isnan(pa) & ~np.isnan(pb) & (np.arange(n) >= bordes[JUICIO_DESDE])
    yy = y[msk]

    def ll(p):
        p = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(p) + (1 - yy) * np.log(1 - p))

    d = ll(pa) - ll(pb)
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    print(f'  {etiqueta:<42} mejora {d.mean():+.5f} · p5 {p5:+.5f} · '
          f'{"ADOPTAR" if p5 > 0 else "RECHAZAR"}')
    return {'mejora': float(d.mean()), 'p5': p5, 'n': int(len(d))}


def main():
    ctx = cargar_contexto()
    led = pd.read_csv('pick_ledger.csv')
    led = led.join(ctx, on='match_id', how='inner').dropna(subset=cp.COLUMNAS)
    led = led.dropna(subset=['p_draw', 'resultado'])
    fecha = pd.to_datetime(led['fecha'])
    y = (led['resultado'].to_numpy() == 1).astype(float)
    p = led['p_draw'].to_numpy(dtype=float)
    X = led[cp.COLUMNAS].to_numpy(dtype=float)
    rng = np.random.default_rng(SEMILLA)
    out = {}

    print('\n1) Control de permutación — contexto barajado')
    out['real'] = medir(p, y, None, X, fecha, 'contexto REAL')
    Xp = X[rng.permutation(len(X))]
    out['permutado'] = medir(p, y, None, Xp, fecha, 'contexto PERMUTADO')

    print('\n2) Control de liga — tasa base de empate de cada liga')
    # tasa base histórica de la liga, calculada SÓLO con lo anterior a cada
    # partido (si se calcula con todo el histórico es fuga por sí misma)
    led = led.sort_values('fecha', kind='stable')
    base_liga = np.zeros(len(led))
    acc = {}
    for i, (lg, emp) in enumerate(zip(led['liga'].to_numpy(),
                                      (led['resultado'].to_numpy() == 1))):
        s, c = acc.get(lg, (0.0, 0))
        base_liga[i] = (s / c) if c >= 30 else 0.25
        acc[lg] = (s + float(emp), c + 1)
    y2 = (led['resultado'].to_numpy() == 1).astype(float)
    p2 = led['p_draw'].to_numpy(dtype=float)
    X2 = led[cp.COLUMNAS].to_numpy(dtype=float)
    f2 = pd.to_datetime(led['fecha'])
    out['con_liga'] = medir(p2, y2, base_liga.reshape(-1, 1), X2, f2,
                            'contexto sobre base+liga')

    print('\n3) Feature a feature (sobre la base desnuda)')
    out['por_feature'] = {}
    for j, c in enumerate(cp.COLUMNAS):
        out['por_feature'][c] = medir(p, y, None, X[:, [j]], fecha, c)

    json.dump(out, open('_v101_auditoria_empate.json', 'w'), indent=1)
    print('\n-> _v101_auditoria_empate.json')


if __name__ == '__main__':
    main()
