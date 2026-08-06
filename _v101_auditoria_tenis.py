#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Auditoría del contexto en tenis, que salió imposiblemente bueno.

El A/B dio en ATP +0,0916 de log-loss sólo con descanso y carga, y +0,1048 con
todo el contexto (0,602 → 0,497). Para comparar: el IDF, la última feature
adoptada, mejoró +0,00064. Esto es **160 veces más**. Nada que se calcule a
partir de fechas de partidos anteriores mejora tanto un modelo que ya tiene ELO,
ranking y forma. Es fuga o es un bug.

Cuatro controles:

  1. ¿Está `y` equilibrado? Si el dataset viene ordenado ganador-primero, la
     etiqueta sería casi constante y cualquier cosa que la correlacione parecería
     oro.
  2. PERMUTACIÓN: contexto barajado. Si la mejora sobrevive, no es el contexto.
  3. Poder predictivo DESNUDO: ¿cuánto acierta el contexto SOLO, sin el modelo?
     Si una diferencia de días de descanso predice el 70 % de los partidos de
     tenis, no es que sepa de tenis: es que lleva dentro el resultado.
  4. ¿De dónde sale? Correlación de cada columna con la etiqueta.
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
import engines.tennis_engine as te
from _v101_ab_contexto_tenis import contexto_alineado, evaluar

CIRCUITO = 'atp'


def main():
    eng = te.TennisEngine(CIRCUITO)
    df = eng.cargar_datos_historicos()
    Xa, y, _f, _o, _e = te.TennisEngine._dataset(df, eng.features)
    ctx, mask = contexto_alineado(df)
    c = ctx.loc[mask].reset_index(drop=True)
    Xa = np.asarray(Xa, dtype=float)
    out = {}

    print(f'\n1) Equilibrio de la etiqueta')
    print(f'   y media = {y.mean():.4f}  (0,5 = simétrico; ~1 = ganador '
          f'siempre en Player_1)')
    out['y_media'] = float(y.mean())
    # ¿y el ganador va de primero en el df crudo?
    gp1 = (df['Winner'].astype(str) == df['Player_1'].astype(str)).mean()
    print(f'   Winner == Player_1 en el df crudo: {gp1:.4f}')
    out['winner_es_player1'] = float(gp1)

    dc = c[['DIFF_DESCANSO', 'DIFF_CARGA']].to_numpy(dtype=float)

    print('\n2) Control de permutación (descanso+carga)')
    out['real'] = evaluar(Xa, np.column_stack([Xa, dc]), y, 'descanso+carga REAL')
    rng = np.random.default_rng(101)
    out['permutado'] = evaluar(Xa, np.column_stack([Xa, dc[rng.permutation(len(dc))]]),
                               y, 'descanso+carga PERMUTADO')

    print('\n3) Poder predictivo DESNUDO (sin el modelo)')
    unos = np.ones((len(y), 1))
    out['desnudo'] = evaluar(unos, np.column_stack([unos, dc]), y,
                             'sólo descanso+carga')

    print('\n4) Correlación de cada columna con la etiqueta')
    out['correlaciones'] = {}
    for col in cp.COLUMNAS:
        r = float(np.corrcoef(c[col].to_numpy(dtype=float), y)[0, 1])
        out['correlaciones'][col] = round(r, 4)
        print(f'   corr({col:<20}, y) = {r:+.4f}')
    # y las de cada lado por separado, que es donde se vería una asimetría
    for col in ('DESCANSO_A', 'DESCANSO_B', 'CARGA_A', 'CARGA_B'):
        r = float(np.corrcoef(c[col].to_numpy(dtype=float), y)[0, 1])
        out['correlaciones'][col] = round(r, 4)
        print(f'   corr({col:<20}, y) = {r:+.4f}')

    json.dump(out, open('_v101_auditoria_tenis.json', 'w'), indent=1,
              ensure_ascii=False)
    print('\n-> _v101_auditoria_tenis.json')


if __name__ == '__main__':
    main()
