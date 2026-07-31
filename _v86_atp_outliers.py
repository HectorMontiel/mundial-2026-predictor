#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Saneamiento de Odd_Max en tenis (tennis-data.co.uk).

El problema
-----------
v82 dejó el ATP fuera de la Capa 1: ninguna configuración de `valor_vs_sharp`
aguantaba fuera de muestra. La pista era que Odd_Max supera a Pinnacle en

    mediana +1,72 %   pero   media +26,45 %

Una media catorce veces mayor que la mediana significa cola pesada: unos pocos
partidos con una "mejor cuota" absurda. Y en esta estrategia esos partidos son
justo los que el filtro selecciona, porque son los de mayor EV aparente. O sea
que el barrido estaba escogiendo basura por construcción.

Antes de limpiar hay que caracterizar: cuántos son, de qué años, si están en un
lado concreto (favorito/perdedor), y si tienen pinta de error de tecleo
(coma decimal desplazada) o de cuota legítima de un tapado.

Este script NO decide el umbral por ROI: eso sería elegir el corte que más
paga, que es exactamente el sobreajuste que ya costó tres correcciones. El
umbral sale de la ESTRUCTURA de los datos (imposibilidad económica), y sólo
después se mide qué efecto tiene.
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


def cargar(circuito):
    from engines.tennis_engine import TennisEngine
    e = TennisEngine(circuito)
    df = e.cargar_datos_historicos()
    need = ['Odd_PS_1', 'Odd_PS_2', 'Odd_Max_1', 'Odd_Max_2']
    if any(c not in df.columns for c in need):
        return None
    d = df.dropna(subset=need).copy()
    for c in need:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[need] > 1.0).all(axis=1)]
    if 'Date' in d.columns:
        d['__f'] = pd.to_datetime(d['Date'], errors='coerce')
    else:
        d['__f'] = pd.NaT
    return d.reset_index(drop=True)


def analizar(circuito):
    d = cargar(circuito)
    if d is None or not len(d):
        print(f'{circuito}: sin datos')
        return None

    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)
    mejora = mx / pin - 1.0

    print('=' * 84)
    print(f'{circuito.upper()} · {len(d)} partidos con Pinnacle y mejor precio')
    print('=' * 84)
    print(f'  mejora de Odd_Max sobre Pinnacle:')
    print(f'    media    {mejora.mean():+9.2%}')
    print(f'    mediana  {np.median(mejora):+9.2%}')
    for q in (0.75, 0.90, 0.95, 0.99, 0.999):
        print(f'    p{q * 100:<5.1f}   {np.quantile(mejora, q):+9.2%}')
    print(f'    máximo   {mejora.max():+9.2%}')

    # --- el sobre-redondeo: suma de probabilidades implícitas de Odd_Max ---
    # Si tomas la MEJOR cuota de cada lado, la suma de las inversas baja. Por
    # debajo de 1 hay arbitraje. Un mercado real de tenis raramente deja más de
    # un 2-3 % de arbitraje; por debajo de ~0,90 el dato es imposible.
    sobre_max = (1 / mx).sum(axis=1)
    sobre_pin = (1 / pin).sum(axis=1)
    print(f'\n  suma de probabilidades implícitas (overround):')
    print(f'    Pinnacle : mediana {np.median(sobre_pin):.4f}  '
          f'(margen de la casa {np.median(sobre_pin) - 1:+.2%})')
    print(f'    Odd_Max  : mediana {np.median(sobre_max):.4f}  '
          f'mínimo {sobre_max.min():.4f}')
    for u in (1.00, 0.98, 0.95, 0.90, 0.80, 0.70, 0.50):
        n = int((sobre_max < u).sum())
        print(f'    con overround < {u:.2f}: {n:6d} partidos '
              f'({n / len(d):6.2%})  <- arbitraje de '
              f'{(1 - u) * 100:.0f}% o más')

    # --- ¿pinta de coma decimal desplazada? ---
    # Odd_Max debería estar cerca de Pinnacle. Un factor ~10 es tecleo.
    ratio = mx / pin
    factor10 = ((ratio > 5) & (ratio < 20)).sum()
    print(f'\n  cuotas con Odd_Max entre 5x y 20x la de Pinnacle: '
          f'{int(factor10)} (pinta de coma decimal desplazada)')
    print(f'  cuotas con Odd_Max > 2x Pinnacle: {int((ratio > 2).sum())}')
    print(f'  cuotas con Odd_Max < Pinnacle (imposible, "mejor" es peor): '
          f'{int((ratio < 1).sum())}  ({(ratio < 1).mean():.2%})')

    # --- ¿en qué lado están? ---
    lado_fav = pin.argmin(axis=1)
    peor = mejora.max(axis=1)
    extremos = peor > 0.20
    print(f'\n  partidos con alguna mejora > 20 %: {int(extremos.sum())} '
          f'({extremos.mean():.2%})')
    if extremos.sum():
        lado_ext = mejora.argmax(axis=1)[extremos]
        es_fav = (lado_ext == lado_fav[extremos])
        print(f'    de ellos, la mejora está en el FAVORITO: '
              f'{es_fav.mean():.1%}')
        cuota_ext = mx[extremos, lado_ext]
        print(f'    cuota de Odd_Max en esos casos: mediana '
              f'{np.median(cuota_ext):.2f}, máx {cuota_ext.max():.2f}')

    # --- ¿por año? ---
    if d['__f'].notna().any():
        d = d.assign(_mejora=peor, _sobre=sobre_max,
                     _anio=d['__f'].dt.year)
        print(f'\n  por año:')
        print(f'    {"año":>6} {"n":>6} {"mejora mediana":>15} '
              f'{"mejora media":>13} {"% con >20%":>11} {"% arb<0,95":>11}')
        for anio, g in d.groupby('_anio'):
            if pd.isna(anio):
                continue
            print(f'    {int(anio):6d} {len(g):6d} '
                  f'{np.median(g["_mejora"]):15.2%} {g["_mejora"].mean():13.2%} '
                  f'{(g["_mejora"] > 0.20).mean():11.2%} '
                  f'{(g["_sobre"] < 0.95).mean():11.2%}')

    return {'circuito': circuito, 'n': len(d),
            'mejora_media': float(mejora.mean()),
            'mejora_mediana': float(np.median(mejora)),
            'pct_arb_95': float((sobre_max < 0.95).mean()),
            'pct_arb_90': float((sobre_max < 0.90).mean()),
            'pct_mejora_20': float(extremos.mean()),
            'pct_max_menor_pin': float((ratio < 1).mean())}


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
    json.dump(out, open('_v86_atp_outliers.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
