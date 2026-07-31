#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Cuántos picks REALES bloquearía un guardia estructural de precio?

El agujero
----------
`cuotas_multi.valor_vs_sharp` calcula

    ev = cuota_accionable * prob_justa_de_pinnacle - 1
    if ev >= min_edge:  -> entra en la Capa 1

y no comprueba en ningún momento que `cuota_accionable` sea un precio POSIBLE.
Si un feed devuelve una cuota corrupta —y en el histórico de tennis-data hay
una de 42.586— el EV sale gigantesco y el pick entra directo.

Esto no es hipotético: sobre el histórico, el 4 % de las filas del ATP son
estructuralmente imposibles. Y como la estrategia ordena por EV descendente,
esas filas son justo las que se llevan la parte alta de la lista.

Lo que mide este script
-----------------------
De los picks que la estrategia SELECCIONARÍA con la configuración de
producción, ¿qué fracción es estructuralmente imposible, y qué ROI tienen esos
picks frente a los sanos? Si los corruptos pierden dinero, el guardia no es
higiene: es rentabilidad.
"""
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RATIO_MAX = 1.50
OVERROUND_MIN = 0.95
N_BOOT = 5000

# configuración de producción de valor_vs_sharp en tenis (v82)
MARGEN = 0.01
PMIN = 0.30


def cargar(circuito):
    from engines.tennis_engine import TennisEngine
    e = TennisEngine(circuito)
    df = e.cargar_datos_historicos()
    need = ['Odd_PS_1', 'Odd_PS_2', 'Odd_Max_1', 'Odd_Max_2']
    if any(c not in df.columns for c in need):
        return None, None
    d = df.dropna(subset=need).copy()
    for c in need:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[need] > 1.0).all(axis=1)]
    gana1 = (d['Winner'].astype(str) == d['Player_1'].astype(str)).values
    col_f = 'Date' if 'Date' in d.columns else 'date'
    d['__f'] = pd.to_datetime(d[col_f], errors='coerce')
    orden = np.argsort(d['__f'].values)
    return d.iloc[orden].reset_index(drop=True), gana1[orden]


def stats(g, semilla=7):
    if len(g) < 30:
        return None
    rng = np.random.default_rng(semilla)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5)),
            'hit': float((g > 0).mean())}


def analizar(circuito):
    d, gana1 = cargar(circuito)
    if d is None:
        return None
    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)
    inv = 1.0 / pin
    justa = inv / inv.sum(axis=1, keepdims=True)

    # ¿es la fila estructuralmente posible?
    sano_fila = ((mx >= pin).all(axis=1)
                 & ((1 / mx).sum(axis=1) >= OVERROUND_MIN)
                 & (mx <= RATIO_MAX * pin).all(axis=1))

    # picks que la estrategia seleccionaría
    ev = mx * justa - 1.0
    sel = (ev > MARGEN) & (justa > PMIN)

    filas = []
    for i, j in np.argwhere(sel):
        acierto = (j == 0) if gana1[i] else (j == 1)
        filas.append({'pnl': mx[i, j] - 1.0 if acierto else -1.0,
                      'sano': bool(sano_fila[i]),
                      'ev': ev[i, j], 'cuota': mx[i, j],
                      'ratio': mx[i, j] / pin[i, j]})
    t = pd.DataFrame(filas)
    if t.empty:
        return None

    print('=' * 80)
    print(f'{circuito.upper()} · picks seleccionados con margen {MARGEN:.0%} '
          f'y prob mínima {PMIN:.0%}')
    print('=' * 80)
    print(f'  total de picks            : {len(t)}')
    print(f'  estructuralmente sanos    : {int(t["sano"].sum())} '
          f'({t["sano"].mean():.2%})')
    print(f'  IMPOSIBLES (los bloquearía): {int((~t["sano"]).sum())} '
          f'({(~t["sano"]).mean():.2%})')

    todos = stats(t['pnl'].values)
    sanos = stats(t[t['sano']]['pnl'].values)
    malos = stats(t[~t['sano']]['pnl'].values, semilla=13)

    print(f'\n  {"grupo":>16} {"n":>7} {"ROI":>9} {"p5":>9} {"acierto":>9}')
    for nombre, s in (('todos (hoy)', todos), ('sólo sanos', sanos),
                      ('sólo imposibles', malos)):
        if s is None:
            print(f'  {nombre:>16} {"(muestra corta)":>36}')
            continue
        print(f'  {nombre:>16} {s["n"]:7d} {s["roi"]:9.2%} {s["p5"]:9.2%} '
              f'{s["hit"]:9.2%}')

    if malos:
        m = t[~t['sano']]
        print(f'\n  perfil de los imposibles:')
        print(f'    EV medio declarado : {m["ev"].mean():+.2%} '
              f'(mediana {m["ev"].median():+.2%}, máx {m["ev"].max():+.2%})')
        print(f'    cuota mediana      : {m["cuota"].median():.2f} '
              f'(máx {m["cuota"].max():.2f})')
        print(f'    ratio sobre Pinnacle: mediana {m["ratio"].median():.2f}x '
              f'(máx {m["ratio"].max():.1f}x)')
        s = t[t['sano']]
        print(f'    para comparar, EV medio de los sanos: {s["ev"].mean():+.2%}')

    if sanos and todos:
        d_roi = sanos['roi'] - todos['roi']
        d_p5 = sanos['p5'] - todos['p5']
        print(f'\n  efecto del guardia: ROI {d_roi:+.2%} · p5 {d_p5:+.2%}')

    return {'circuito': circuito, 'todos': todos, 'sanos': sanos,
            'imposibles': malos,
            'pct_bloqueado': float((~t['sano']).mean())}


def main():
    out = []
    for c in ('atp', 'wta'):
        try:
            r = analizar(c)
            if r:
                out.append(r)
        except Exception as ex:
            print(f'{c}: {type(ex).__name__}: {ex}')
        print()

    print('=' * 80)
    print('CONCLUSIÓN')
    print('=' * 80)
    for r in out:
        t, s = r['todos'], r['sanos']
        if not t or not s:
            continue
        print(f"  {r['circuito'].upper()}: el guardia bloquea "
              f"{r['pct_bloqueado']:.2%} de los picks y mueve el ROI de "
              f"{t['roi']:+.2%} a {s['roi']:+.2%} "
              f"(p5 {t['p5']:+.2%} -> {s['p5']:+.2%})")

    json.dump(out, open('_v86_guardia_precio.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
