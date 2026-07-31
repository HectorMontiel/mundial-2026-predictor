#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Los tres filtros de precio, medidos POR SEPARADO.

Por qué se separan
------------------
Aplicados en bloque, los tres filtros bloqueaban un 5-6 % de los picks y bajaban
el ROI medido (WTA +4,57 % -> +2,91 %). Pero no son igual de defendibles:

  · ratio Odd_Max/Odd_PS > 1,5
    Un precio un 50 % por encima del sharp no es discrepancia de mercado: es un
    error. Aquí vive la apuesta de +126,0 que ella sola aporta el 75 % del
    beneficio del grupo "imposible" de la WTA.

  · overround de Odd_Max < 0,95
    Ésta es DUDOSA. Odd_Max es el máximo sobre muchas casas y a lo largo del
    día; que la suma de inversas baje de 1 es justo lo que el line shopping
    busca, no necesariamente un error de datos.

  · Odd_Max < Odd_PS
    Tampoco es imposible si el conjunto de casas de Odd_Max no incluye a
    Pinnacle. Y además esas filas dan PEOR precio, así que la estrategia casi
    nunca las elige.

Meter en el mismo saco un detector de corrupción y dos heurísticas discutibles
es como elegir el corte que más paga, pero al revés. Se miden uno a uno y se
despliega sólo lo que se sostiene.
"""
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

MARGEN, PMIN = 0.01, 0.30
N_BOOT = 5000


def cargar(circuito):
    from engines.tennis_engine import TennisEngine
    e = TennisEngine(circuito)
    df = e.cargar_datos_historicos()
    need = ['Odd_PS_1', 'Odd_PS_2', 'Odd_Max_1', 'Odd_Max_2']
    d = df.dropna(subset=need).copy()
    for c in need:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[need] > 1.0).all(axis=1)]
    gana1 = (d['Winner'].astype(str) == d['Player_1'].astype(str)).values
    col = 'Date' if 'Date' in d.columns else 'date'
    d['__f'] = pd.to_datetime(d[col], errors='coerce')
    o = np.argsort(d['__f'].values)
    return d.iloc[o].reset_index(drop=True), gana1[o]


def stats(g, semilla=7):
    if len(g) < 30:
        return None
    rng = np.random.default_rng(semilla)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5))}


def analizar(circuito):
    d, gana1 = cargar(circuito)
    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)
    inv = 1.0 / pin
    justa = inv / inv.sum(axis=1, keepdims=True)
    ev = mx * justa - 1.0
    sel = (ev > MARGEN) & (justa > PMIN)

    reg = []
    for i, j in np.argwhere(sel):
        ok = bool((j == 0) if gana1[i] else (j == 1))
        reg.append({'pnl': (mx[i, j] - 1.0) if ok else -1.0,
                    'ratio': mx[i, j] / pin[i, j],
                    'overround': float((1 / mx[i]).sum()),
                    'max_menor': bool((mx[i] < pin[i]).any())})
    t = pd.DataFrame(reg)

    print('=' * 78)
    print(f'{circuito.upper()} · {len(t)} picks')
    print('=' * 78)
    base = stats(t['pnl'].values)
    print(f'  SIN filtro          n={base["n"]:6d} ROI {base["roi"]:+7.2%} '
          f'p5 {base["p5"]:+7.2%}')

    filtros = {
        'ratio <= 1,5 (sólo éste)': t['ratio'] <= 1.5,
        'ratio <= 2,0': t['ratio'] <= 2.0,
        'ratio <= 3,0': t['ratio'] <= 3.0,
        'overround >= 0,95': t['overround'] >= 0.95,
        'Odd_Max >= Pinnacle': ~t['max_menor'],
        'los TRES juntos': (t['ratio'] <= 1.5) & (t['overround'] >= 0.95)
                           & (~t['max_menor']),
    }
    out = {'sin_filtro': base, 'filtros': {}}
    print()
    for nombre, m in filtros.items():
        s = stats(t[m]['pnl'].values, semilla=11)
        if not s:
            continue
        bloq = int((~m).sum())
        out['filtros'][nombre] = {**s, 'bloqueados': bloq}
        print(f'  {nombre:26s} n={s["n"]:6d} ROI {s["roi"]:+7.2%} '
              f'p5 {s["p5"]:+7.2%}   bloquea {bloq:4d} '
              f'({bloq / len(t):5.2%})  ROI {s["roi"] - base["roi"]:+.2%}')

    # ¿qué pasa con la mayor ganancia individual?
    peor = t.nlargest(3, 'pnl')
    print(f'\n  las 3 mayores ganancias individuales:')
    for _, r in peor.iterrows():
        print(f'    +{r["pnl"]:8.1f} unidades · ratio {r["ratio"]:6.2f}x '
              f'Pinnacle · overround {r["overround"]:.3f}')
    print(f'  (una sola apuesta de +126 aporta el 75 % del beneficio del grupo '
          f'imposible en WTA)')
    return out


def main():
    salida = {}
    for c in ('atp', 'wta'):
        try:
            salida[c] = analizar(c)
        except Exception as ex:
            print(f'{c}: {type(ex).__name__}: {ex}')
        print()

    print('=' * 78)
    print('LECTURA')
    print('=' * 78)
    print('  El filtro que hay que desplegar es el que quita la cola imposible')
    print('  SIN tocar los picks normales. Se mira cuál bloquea poco y cuesta')
    print('  poco ROI: eso es robustez barata. Los que bloquean mucho y cuestan')
    print('  ROI están tirando line shopping legítimo.')
    json.dump(salida, open('_v86_filtros_uno_a_uno.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
