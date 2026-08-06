#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v105 — ¿Mejora el ELO cross-competición las predicciones de copa?

`elo_global.py` construye un ELO único por equipo sobre las 66 competiciones,
con los nombres unificados y encogido hacia la media de su país. La pregunta es
la de siempre: ¿aporta ENCIMA de la probabilidad que el modelo desplegado ya
produce?

Se mide sobre `pick_ledger.csv` (predicciones fuera de muestra), separando:

  · TODO el ledger — para no elegir el subconjunto que mejor salga.
  · sólo COMPETICIONES DE COPA — donde está el problema que motivó el módulo.
  · sólo partidos de POCO CONOCIMIENTO — el caso Vikingur en estado puro.

Base: log-odds de la probabilidad del modelo. Candidato: base + DIFF_ELO_G.
Walk-forward, juicio en pliegues tardíos, bootstrap pareado, veredicto por p5.
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

import elo_global as eg
from _v101_ab_contexto_futbol import _logit, _wf, N_PLIEGUES, JUICIO_DESDE

BOOT = 4000
SEMILLA = 105
SALIDA = '_v105_ab_elo_global.json'


def _juzgar(pa, pb, y, msk, etiqueta, salida):
    if msk.sum() < 300:
        print(f'  {etiqueta:<34} muestra insuficiente ({int(msk.sum())})')
        return
    yy = y[msk]

    def ll(p):
        q = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

    a, b = ll(pa), ll(pb)
    d = a - b
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    acc_a = float(((pa[msk] >= .5) == yy).mean())
    acc_b = float(((pb[msk] >= .5) == yy).mean())
    ver = 'ADOPTAR' if p5 > 0 and acc_b >= acc_a - 0.002 else 'RECHAZAR'
    print(f'  {etiqueta:<34} n={int(msk.sum()):>6} · {a.mean():.5f} → '
          f'{b.mean():.5f} · mejora {d.mean():+.6f} · p5 {p5:+.6f} · '
          f'acierto {acc_a:.4f}→{acc_b:.4f} · {ver}')
    salida[etiqueta] = {'n': int(msk.sum()), 'll_a': float(a.mean()),
                        'll_b': float(b.mean()), 'mejora': float(d.mean()),
                        'p5': p5, 'acc_a': acc_a, 'acc_b': acc_b,
                        'veredicto': ver}


def main():
    t = eg.cargar_partidos()
    g = eg.elo_global(t)
    if 'MATCH_ID' not in g.columns:
        print('el ELO global no trae MATCH_ID; no se puede cruzar')
        return
    tabla = g.dropna(subset=['MATCH_ID']).drop_duplicates('MATCH_ID')
    tabla = tabla.set_index('MATCH_ID')[['DIFF_ELO_G', 'N_HOME', 'N_AWAY']]

    led = pd.read_csv('pick_ledger.csv').join(tabla, on='match_id', how='inner')
    led = led.dropna(subset=['DIFF_ELO_G', 'resultado'])
    led = led.sort_values('fecha', kind='stable').reset_index(drop=True)
    n = len(led)
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    extra = led[['DIFF_ELO_G']].to_numpy(dtype=float)
    conoc = np.minimum(led['N_HOME'].to_numpy(dtype=float),
                       led['N_AWAY'].to_numpy(dtype=float))
    es_copa = led['liga'].isin(eg.COPAS).to_numpy()
    print(f'{n} predicciones cruzadas · {int(es_copa.sum())} de copa · '
          f'{int((conoc < 20).sum())} con poco conocimiento (<20 partidos)\n')

    salida = {}
    for etq, col_p, valor in (('gana local', 'p_home', 0),
                              ('empate', 'p_draw', 1),
                              ('gana visita', 'p_away', 2)):
        print(f'{etq}:')
        y = (led['resultado'].to_numpy() == valor).astype(float)
        base = _logit(led[col_p].to_numpy(dtype=float)).reshape(-1, 1)
        pa = _wf(base, y, bordes)
        pb = _wf(np.column_stack([base, extra]), y, bordes)
        tarde = ~np.isnan(pa) & ~np.isnan(pb) & \
            (np.arange(n) >= bordes[JUICIO_DESDE])
        _juzgar(pa, pb, y, tarde, f'{etq} · todo', salida)
        _juzgar(pa, pb, y, tarde & es_copa, f'{etq} · sólo copas', salida)
        _juzgar(pa, pb, y, tarde & (conoc < 20),
                f'{etq} · poco conocimiento', salida)
        print()

    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'-> {SALIDA}')


if __name__ == '__main__':
    main()
