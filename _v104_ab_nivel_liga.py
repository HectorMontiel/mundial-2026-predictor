#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v104 — ¿Merece la pena que el lazo aprenda también POR COMPETICIÓN?

El lazo de calibración aprende hoy en dos niveles: global → deporte → mercado.
Los ledgers, sin embargo, traen la liga de cada una de sus 190.000 predicciones,
y esa columna se estaba tirando. La pregunta es si añadir un tercer nivel
—global → deporte → mercado → liga— mejora fuera de muestra o sólo trocea la
muestra hasta que cada nodo aprende ruido.

No es obvio que ayude. Con 60 competiciones, muchas aportan unos cientos de
casos, y el encogimiento hacia el padre las devolverá casi enteras a su
mercado. El coste de equivocarse aquí es real: una liga con 200 partidos y una
racha puede desviar su nodo y publicar probabilidades sesgadas durante semanas.

Se mide como todo lo demás: la calibración se aprende SÓLO con el pasado y se
juzga en el futuro, avanzando por pliegues; bootstrap pareado y veredicto por
p5 sobre el log-loss.
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

import aprendizaje_continuo as ac

N_PLIEGUES = 6
JUICIO_DESDE = 2
BOOT = 4000
SEMILLA = 104
SALIDA = '_v104_ab_nivel_liga.json'


def walk_forward(d: pd.DataFrame, niveles) -> np.ndarray:
    n = len(d)
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    p = d['prob'].to_numpy(dtype=float).copy()
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        if ini < 500:
            continue
        mapa = ac.aprender(d.iloc[:ini], 'prob', 'acierto', niveles)
        sub = d.iloc[ini:fin]
        p[ini:fin] = [
            ac.aplicar(float(r.prob), mapa,
                       {k: str(getattr(r, k)) for k in niveles})
            for r in sub.itertuples(index=False)]
    return p, bordes


def main():
    u = ac._universo()
    u = u.dropna(subset=['prob', 'acierto', 'liga']).reset_index(drop=True)
    print(f'{len(u)} predicciones · {u.liga.nunique()} competiciones · '
          f'{u.deporte.nunique()} deportes')
    print(f'mediana de casos por competición: '
          f'{int(u.liga.value_counts().median())}\n')

    y = u['acierto'].to_numpy(dtype=float)
    p_sin, bordes = walk_forward(u, ['deporte', 'mercado'])
    p_con, _ = walk_forward(u, ['deporte', 'mercado', 'liga'])
    msk = np.arange(len(u)) >= bordes[JUICIO_DESDE]
    yy = y[msk]

    def ll(p):
        q = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

    a, b = ll(p_sin), ll(p_con)
    dif = a - b
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                   for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    ver = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
    print(f'n juzgados = {int(msk.sum())}')
    print(f'  sin nivel de liga · log-loss {a.mean():.5f} · '
          f'brecha {abs(yy.mean() - p_sin[msk].mean()):.4f}')
    print(f'  con nivel de liga · log-loss {b.mean():.5f} · '
          f'brecha {abs(yy.mean() - p_con[msk].mean()):.4f}')
    print(f'  mejora {dif.mean():+.6f} · p5 {p5:+.6f} · {ver}')

    salida = {'n': int(msk.sum()), 'll_sin': float(a.mean()),
              'll_con': float(b.mean()), 'mejora': float(dif.mean()),
              'p5': p5, 'veredicto': ver,
              'competiciones': int(u.liga.nunique())}
    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
