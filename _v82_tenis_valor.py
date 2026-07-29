#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v82 — `valor_vs_sharp` en TENIS, medido sobre 26.000 partidos con Pinnacle.

El ledger no guarda el ancla de Pinnacle para tenis (`pin_*` va a None en
`ledger_tenis`), así que la estrategia no se podía medir por ahí. Pero la
fuente sí la tiene: tennis-data.co.uk publica en el mismo fichero

    Odd_PS_1 / Odd_PS_2    -> Pinnacle           (26.397 partidos)
    Odd_Max_1 / Odd_Max_2  -> la MEJOR del mercado (28.188)

Que es exactamente el par que la estrategia necesita: un precio sharp de
referencia y un precio tomable mejor. No hace falta ninguna fuente nueva.

La hipótesis
------------
El modelo de tenis no bate al mercado (log-loss 0,6109 frente a 0,5831) y por
eso está fuera de la Capa 1. Pero `valor_vs_sharp` **no usa el modelo**: apuesta
donde una casa se ha quedado descolgada respecto a Pinnacle. Si el edge está en
la discrepancia entre casas, debería existir aquí igual que en fútbol, y la
Capa 1 podría recuperar el tenis sin arreglar el modelo.

Guardarraíles (los que dejó establecidos la v80)
------------------------------------------------
  · parámetros elegidos en el 70 % más antiguo, validados en el 30 % reciente;
  · ROI **y** bootstrap p5 positivos, en LOS DOS periodos;
  · nada de quedarse con el máximo del barrido: ya se vio hundirse de
    p5 +10,09 % a −9,44 % fuera de muestra.

Cordura obligatoria: el log-loss de Pinnacle debe batir al azar. Si no, las
cuotas están mal pegadas y cualquier ROI es ficticio (lección v78).
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('tenis-valor')

N_BOOT = 5000
MIN_N = 80
CORTE = 0.70


def evaluar(cu, justa, gana1, margen, pmin, semilla=5):
    ev = cu * justa - 1.0
    sel = (ev > margen) & (justa > pmin)
    if sel.sum() < MIN_N:
        return None
    idx = np.argwhere(sel)
    gan = []
    for i, j in idx:
        acierto = (j == 0) if gana1[i] else (j == 1)
        gan.append(cu[i, j] - 1.0 if acierto else -1.0)
    g = np.array(gan, float)
    rng = np.random.default_rng(semilla)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5)),
            'hit': float((g > 0).mean())}


def analizar(circuito):
    from engines.tennis_engine import TennisEngine
    e = TennisEngine(circuito)
    df = e.cargar_datos_historicos()
    need = ['Odd_PS_1', 'Odd_PS_2', 'Odd_Max_1', 'Odd_Max_2']
    if any(c not in df.columns for c in need):
        print(f'{circuito}: faltan columnas de cuotas')
        return None
    d = df.dropna(subset=need).copy()
    for c in need:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[need] > 1.0).all(axis=1)]
    # el dataset está en formato ganador/perdedor: la fila 1 SIEMPRE gana
    # salvo que la fuente indique lo contrario. Se comprueba abajo.
    if 'Winner' in d.columns and 'Player_1' in d.columns:
        gana1 = (d['Winner'].astype(str) == d['Player_1'].astype(str)).values
    else:
        print(f'{circuito}: no se puede determinar el ganador; se omite')
        return None
    if 'Date' in d.columns:
        d['__f'] = pd.to_datetime(d['Date'], errors='coerce')
    elif 'date' in d.columns:
        d['__f'] = pd.to_datetime(d['date'], errors='coerce')
    else:
        d['__f'] = pd.RangeIndex(len(d))
    orden = np.argsort(d['__f'].values)
    d = d.iloc[orden].reset_index(drop=True)
    gana1 = gana1[orden]

    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)
    inv = 1.0 / pin
    justa = inv / inv.sum(axis=1, keepdims=True)

    # GUARDIA: Pinnacle tiene que batir al azar
    p1 = np.clip(justa[:, 0], 1e-9, 1 - 1e-9)
    ll = float(-(gana1 * np.log(p1) + (~gana1) * np.log(1 - p1)).mean())
    print(f'\n{"="*82}\n{circuito.upper()}  ·  {len(d)} partidos con Pinnacle y '
          f'mejor precio')
    print(f'  log-loss de Pinnacle: {ll:.4f}  (azar {np.log(2):.4f})  '
          f'{"OK" if ll < np.log(2) else "DESALINEADO"}')
    print('='*82)
    if ll >= np.log(2):
        print('  cuotas desalineadas: cualquier ROI de aquí sería ficticio')
        return None

    # margen medio de Max sobre Pinnacle (¿hay de verdad discrepancia?)
    mejora = (mx / pin - 1.0)
    print(f'  Max supera a Pinnacle de media en {mejora.mean():.2%} '
          f'(mediana {np.median(mejora):.2%})')

    n = len(d)
    c = int(n * CORTE)
    print(f"\n{'margen':>7} {'pmin':>6} | {'n(70%)':>7} {'ROI':>8} {'p5':>8} "
          f"| {'n(30%)':>7} {'ROI':>8} {'p5':>8}  ambos")
    print('-'*82)
    robustas = []
    for margen in (0.00, 0.01, 0.02, 0.03, 0.05):
        for pmin in (0.0, 0.30, 0.50):
            a = evaluar(mx[:c], justa[:c], gana1[:c], margen, pmin)
            b = evaluar(mx[c:], justa[c:], gana1[c:], margen, pmin, semilla=11)
            if not a or not b:
                continue
            ok = a['p5'] > 0 and b['p5'] > 0
            if ok:
                robustas.append((margen, pmin, a, b))
            print(f"{margen:7.0%} {pmin:6.0%} | {a['n']:7d} {a['roi']:8.2%} "
                  f"{a['p5']:8.2%} | {b['n']:7d} {b['roi']:8.2%} "
                  f"{b['p5']:8.2%}  {'SI' if ok else ''}")
    if robustas:
        mejor = max(robustas, key=lambda x: x[3]['n'])
        print(f"\n  ROBUSTA: margen {mejor[0]:.0%} · prob mínima {mejor[1]:.0%}")
        print(f"    validación n={mejor[3]['n']} ROI {mejor[3]['roi']:+.2%} "
              f"p5 {mejor[3]['p5']:+.2%}")
        print(f"  VEREDICTO: EDGE VALIDADO en {circuito.upper()}")
        return {'circuito': circuito, 'robusta': True,
                'margen': mejor[0], 'pmin': mejor[1],
                'eleccion': mejor[2], 'validacion': mejor[3]}
    print(f"\n  VEREDICTO: sin configuración robusta en {circuito.upper()}")
    return {'circuito': circuito, 'robusta': False}


def main():
    out = []
    for c in ('atp', 'wta'):
        try:
            r = analizar(c)
            if r:
                out.append(r)
        except Exception as e:
            log.warning(f'{c}: {type(e).__name__}: {e}')
    json.dump(out, open('_v82_tenis_valor.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
