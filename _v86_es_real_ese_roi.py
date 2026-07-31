#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿El +15 %/+29 % de ROI de los picks "imposibles" es dinero o es el error?

El resultado sospechoso
-----------------------
_v86_guardia_precio.py encontró que las filas estructuralmente imposibles
rinden MÁS que las sanas:

    ATP  sanas +2,51 %   imposibles +15,31 %
    WTA  sanas +2,91 %   imposibles +29,62 %

Leído ingenuamente: "el filtro tira dinero". Pero es justo la firma que este
proyecto ya ha diagnosticado tres veces (ROI +31,75 % en MLB, features de
abridor, margen 10 % de valor_vs_sharp): media mucho mayor que mediana, colas
enormes, y un resultado demasiado bueno.

La hipótesis alternativa
------------------------
El backtest **paga al precio registrado**. Si Odd_Max está mal y dice 127,00
cuando la cuota real era 2,10, una apuesta ganadora se apunta +126 unidades que
nadie cobró jamás. Entonces el ROI alto no es evidencia contra el filtro: es el
efecto del error que el filtro detecta.

Cómo se distingue
-----------------
Si el edge fuera REAL, vendría de acertar más veces. Si es el precio corrupto,
vendría del tamaño del pago. Tres pruebas que lo separan:

  1. Tasa de acierto contra la probabilidad justa de Pinnacle. Un edge real
     hace ganar MÁS veces de lo que Pinnacle implica. El precio corrupto no
     cambia quién gana el partido.

  2. ROI pagando al precio de PINNACLE (que sabemos que es real) en vez de al
     Odd_Max sospechoso. Si el edge sobrevive, es de selección; si desaparece,
     era el pago inventado.

  3. ROI mediano y ROI recortado (winsorizado). La media es rehén de una cola;
     la mediana no.
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
    col_f = 'Date' if 'Date' in d.columns else 'date'
    d['__f'] = pd.to_datetime(d[col_f], errors='coerce')
    o = np.argsort(d['__f'].values)
    return d.iloc[o].reset_index(drop=True), gana1[o]


def analizar(circuito):
    d, gana1 = cargar(circuito)
    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)
    inv = 1.0 / pin
    justa = inv / inv.sum(axis=1, keepdims=True)

    sano_fila = ((mx >= pin).all(axis=1)
                 & ((1 / mx).sum(axis=1) >= OVERROUND_MIN)
                 & (mx <= RATIO_MAX * pin).all(axis=1))

    ev = mx * justa - 1.0
    sel = (ev > MARGEN) & (justa > PMIN)

    reg = []
    for i, j in np.argwhere(sel):
        acierto = bool((j == 0) if gana1[i] else (j == 1))
        reg.append({
            'sano': bool(sano_fila[i]), 'acierto': acierto,
            'cuota_max': mx[i, j], 'cuota_pin': pin[i, j],
            'p_justa': justa[i, j],
            'pnl_max': (mx[i, j] - 1.0) if acierto else -1.0,
            'pnl_pin': (pin[i, j] - 1.0) if acierto else -1.0,
            'pnl_cap': (min(mx[i, j], RATIO_MAX * pin[i, j]) - 1.0)
                       if acierto else -1.0,
        })
    t = pd.DataFrame(reg)

    print('=' * 84)
    print(f'{circuito.upper()}  ·  {len(t)} picks seleccionados')
    print('=' * 84)

    for etiqueta, sub in (('SANOS', t[t['sano']]),
                          ('IMPOSIBLES', t[~t['sano']])):
        if len(sub) < 30:
            continue
        acierto = sub['acierto'].mean()
        esperado = sub['p_justa'].mean()
        print(f'\n--- {etiqueta} (n={len(sub)}) ---')
        print(f'  PRUEBA 1 · ¿gana más veces de lo que Pinnacle implica?')
        print(f'    acierto real          : {acierto:.2%}')
        print(f'    acierto que implica Pinnacle: {esperado:.2%}')
        exceso = acierto - esperado
        # error estándar del exceso
        se = np.sqrt(esperado * (1 - esperado) / len(sub))
        z = exceso / se if se > 0 else 0
        print(f'    exceso                : {exceso:+.2%}  (z = {z:+.2f})')
        print(f'    -> {"hay señal de selección" if z > 2 else "NO hay señal de selección"}')

        print(f'  PRUEBA 2 · ROI según a qué precio se pague')
        for nom, col in (('al Odd_Max registrado', 'pnl_max'),
                         ('al precio de Pinnacle', 'pnl_pin'),
                         ('capado a 1,5x Pinnacle', 'pnl_cap')):
            g = sub[col].values
            rng = np.random.default_rng(3)
            bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
            print(f'    {nom:24s} ROI {g.mean():+8.2%}  '
                  f'p5 {np.percentile(bs, 5):+8.2%}')

        print(f'  PRUEBA 3 · media frente a mediana')
        g = sub['pnl_max'].values
        w = np.clip(g, np.percentile(g, 1), np.percentile(g, 99))
        print(f'    ROI medio             : {g.mean():+.2%}')
        print(f'    ROI mediano           : {np.median(g):+.2%}')
        print(f'    ROI winsorizado 1-99  : {w.mean():+.2%}')
        top = np.sort(g)[-5:]
        print(f'    5 mayores ganancias   : '
              f'{", ".join(f"{x:+.1f}" for x in top)}')
        print(f'    aportan el {top.sum() / (g.sum() if g.sum() != 0 else 1):.0%} '
              f'del beneficio total de {len(g)} apuestas')

    return t


def main():
    salida = {}
    for c in ('atp', 'wta'):
        try:
            t = analizar(c)
            sub = t[~t['sano']]
            salida[c] = {
                'n_imposibles': int(len(sub)),
                'roi_al_max': float(sub['pnl_max'].mean()),
                'roi_a_pinnacle': float(sub['pnl_pin'].mean()),
                'roi_capado': float(sub['pnl_cap'].mean()),
                'roi_mediano': float(np.median(sub['pnl_max'])),
                'acierto': float(sub['acierto'].mean()),
                'acierto_implicito': float(sub['p_justa'].mean()),
            }
        except Exception as ex:
            print(f'{c}: {type(ex).__name__}: {ex}')
        print()

    print('=' * 84)
    print('VEREDICTO')
    print('=' * 84)
    for c, r in salida.items():
        print(f'\n{c.upper()} · picks imposibles (n={r["n_imposibles"]}):')
        print(f'  ROI pagando al Odd_Max registrado : {r["roi_al_max"]:+.2%}')
        print(f'  ROI pagando al precio de Pinnacle : {r["roi_a_pinnacle"]:+.2%}')
        print(f'  ROI capado a 1,5x Pinnacle        : {r["roi_capado"]:+.2%}')
        print(f'  ROI mediano                       : {r["roi_mediano"]:+.2%}')
        print(f'  acierto {r["acierto"]:.2%} frente al '
              f'{r["acierto_implicito"]:.2%} que implica Pinnacle')

    json.dump(salida, open('_v86_es_real_ese_roi.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
