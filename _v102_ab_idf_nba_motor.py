#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v102 — El IDF en la NBA, contra el VECTOR DESPLEGADO (la medición que decide).

El primer pase midió el IDF de la NBA contra el ELO rodante a secas y salió
ADOPTAR en las tres ventanas (p5 +0,00038 / +0,00058 / +0,00014). No basta, y el
proyecto ya tropezó con esto una vez: la v99.1 midió el IDF de tenis contra una
base de dos features y salió muy positivo; la v99.2 lo repitió contra el vector
real —que ya llevaba `DIFF_FORMA10`— y la mejora se redujo a una décima parte.

El motor de la NBA usa NUEVE features, y tres de ellas ya son forma o descanso:
`DIFF_STREAK`, `DIFF_REST` y `DIFF_B2B`. La pregunta correcta es si el IDF
aporta ENCIMA de eso, no encima del ELO.

Se usa el `_dataset` del propio motor, así que lo que se mide es exactamente lo
que se desplegaría.
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
import indice_forma as idf_mod
import engines.nba_engine as ne
from _v101_ab_contexto_futbol import _wf, N_PLIEGUES, JUICIO_DESDE

BOOT = 4000
SEMILLA = 102
VENTANAS = (5, 10, 15)
SALIDA = '_v102_ab_idf_nba_motor.json'


def main():
    eng = ne.NBAEngine() if hasattr(ne, 'NBAEngine') else None
    df = (eng.cargar_datos_historicos() if eng is not None
          else pd.read_csv('historico_nba.csv'))
    X, y, _tot, fechas, _est = ne.NBAEngine._dataset(df)
    X = np.asarray(X, dtype=float)
    n = len(y)
    print(f'NBA · vector desplegado {len(ne.FEATURES)} features '
          f'({", ".join(ne.FEATURES)})')
    print(f'{n} partidos utilizables del dataset del motor')

    # el IDF se calcula sobre el MISMO df ordenado que usa `_dataset`, y se
    # recorta a las filas que el motor emitió (las primeras se descartan porque
    # los equipos aún no tienen historial)
    d = df.sort_values('date').reset_index(drop=True).copy()
    d['res_idf'] = (pd.to_numeric(d['home_pts'], errors='coerce')
                    > pd.to_numeric(d['away_pts'], errors='coerce')).astype(float)
    ea, eb, _ = cp.elo_rodante(d, 'home_team', 'away_team', 'res_idf',
                               ventaja_a=cp.ELO_VENTAJA_LOCAL)
    d['elo_a_idf'], d['elo_b_idf'] = ea, eb
    if len(d) < n:
        print('  ! el df es más corto que el dataset: se aborta')
        return
    # `_dataset` emite las ÚLTIMAS n filas del df ordenado (descarta el arranque)
    recorte = len(d) - n
    print(f'  {recorte} filas de arranque descartadas por el motor')

    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    salida = {'features': list(ne.FEATURES), 'n': int(n)}
    pa = _wf(X, y, bordes)
    for ventana in VENTANAS:
        t = idf_mod.idf_por_participante(d, 'home_team', 'away_team',
                                         'elo_a_idf', 'elo_b_idf', 'res_idf',
                                         ventana=ventana)
        extra = t[['DIFF_IDF']].to_numpy(dtype=float)[recorte:]
        pb = _wf(np.column_stack([X, extra]), y, bordes)
        msk = ~np.isnan(pa) & ~np.isnan(pb) & \
            (np.arange(n) >= bordes[JUICIO_DESDE])
        yy = y[msk]

        def ll(p):
            q = np.clip(p[msk], 1e-9, 1 - 1e-9)
            return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

        e_a, e_b = ll(pa), ll(pb)
        dif = e_a - e_b
        rng = np.random.default_rng(SEMILLA)
        bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                       for _ in range(BOOT)])
        p5 = float(np.percentile(bt, 5))
        acc_a = float(((pa[msk] >= .5) == yy).mean())
        acc_b = float(((pb[msk] >= .5) == yy).mean())
        ver = ('ADOPTAR' if p5 > 0 and acc_b >= acc_a - 0.002 else 'RECHAZAR')
        print(f'  ventana {ventana:>2} · n={len(dif):>5} · {e_a.mean():.5f} → '
              f'{e_b.mean():.5f} · mejora {dif.mean():+.6f} · p5 {p5:+.6f} · '
              f'acierto {acc_a:.4f} → {acc_b:.4f} · {ver}')
        salida[f'v{ventana}'] = {'n': int(len(dif)), 'll_a': float(e_a.mean()),
                                 'll_b': float(e_b.mean()),
                                 'mejora': float(dif.mean()), 'p5': p5,
                                 'acc_a': acc_a, 'acc_b': acc_b,
                                 'veredicto': ver}

    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
