#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — La regla que decide si una liga se calibra mide lo que no toca.

El hallazgo
-----------
La v79 concluyó que el fútbol de julio salía sin calibrar por «falta de
histórico de cuotas sudamericano». Medido eslabón por eslabón
(`_v80_diag_cadena.py`), eso solo explica una parte. Las cinco ligas con más
partidos hoy tienen datos de sobra:

    argentina    13 partidos   7.193 cuotas en el almacén   1.843 filas con cuota
    liga_mx       7 partidos   5.086 cuotas                 1.311 filas con cuota
    china         5 partidos   3.612 cuotas                   899 filas con cuota
    chi_primera   5 partidos     912 cuotas                   256 filas con cuota
    suecia        1 partido    3.733 cuotas                   932 filas con cuota

No les falta dato: se midieron y la regla de `recalibrate_from_history` las
rechazó. La regla es:

    adopta = mejora_logloss >= X  Y  mejora_acc >= 0
             O  mejora_acc >= Y   Y  mejora_logloss >= 0

Y lo que pasa en esas ligas es exactamente esto:

    liga         Δ log-loss   Δ precisión
    china          +0,0321      −0,0165
    suecia         +0,0245      −0,0267
    argentina      +0,0161      −0,0136
    liga_mx        +0,0116      −0,0076

Encoger MEJORA la calibración y BAJA el acierto del argmax. La regla exige las
dos cosas, así que las tira.

Por qué eso es un error de diseño
---------------------------------
El acierto del argmax no es el objetivo de este sistema. El EV se calcula como
`cuota × p − 1`: lo que importa es que `p` esté bien calibrada, no que el lado
más probable acierte más veces. Son cosas distintas y pueden ir en direcciones
opuestas — de hecho aquí van en direcciones opuestas.

Y hay una razón mecánica para que el acierto baje al encoger: acercarse al
mercado empuja las probabilidades hacia 0,5, así que muchos partidos cambian de
lado por márgenes minúsculos. Eso mueve el argmax sin cambiar apenas el EV.

Este script mide lo ÚNICO que decide en este proyecto: el ROI fuera de muestra
con los umbrales de producción, y su bootstrap p5. Es el mismo criterio que
dejó fuera el Over/Under en la v44 y a tenis/MLB de la Capa 1 en la v78.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('regla')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 3000
MIN_N = 40


def _cargar():
    d = pd.read_csv(LEDGER, low_memory=False)
    d = d[d['deporte'] == 'Fútbol']
    d = d[d['cuota_home'].notna() & d['cuota_away'].notna()]
    return d


def _p_mercado(fila):
    cs = [fila['cuota_home'], fila['cuota_draw'], fila['cuota_away']]
    inv = [1.0 / c if (c and c > 1) else np.nan for c in cs]
    s = np.nansum(inv)
    if not np.isfinite(s) or s <= 0:
        return None
    return [(x / s if np.isfinite(x) else np.nan) for x in inv]


def simular(g, w, umbral_prob=0.55, min_ev=0.03, min_cuota=1.50):
    """ROI de los picks que producción emitiría con ese peso."""
    cuotas = g[['cuota_home', 'cuota_draw', 'cuota_away']].values
    probs = g[['p_home', 'p_draw', 'p_away']].values
    res = g['resultado'].values

    inv = np.where((cuotas > 1) & np.isfinite(cuotas), 1.0 / cuotas, np.nan)
    suma = np.nansum(inv, axis=1, keepdims=True)
    pmkt = np.where(suma > 0, inv / suma, np.nan)

    # encogimiento solo donde hay las tres patas del mercado
    completo = np.isfinite(pmkt).all(axis=1)
    p = probs.copy()
    p[completo] = w * probs[completo] + (1 - w) * pmkt[completo]
    p = p / p.sum(axis=1, keepdims=True)

    ev = cuotas * p - 1.0
    apostable = (p > umbral_prob) & (ev > min_ev) & (cuotas > min_cuota) \
        & np.isfinite(cuotas)
    idx = np.argwhere(apostable)
    if len(idx) < MIN_N:
        return None
    ganancias = []
    for i, j in idx:
        ganancias.append(cuotas[i, j] - 1.0 if res[i] == j else -1.0)
    gan = np.array(ganancias, float)
    roi = float(gan.mean())
    rng = np.random.default_rng(7)
    bs = gan[rng.integers(0, len(gan), size=(N_BOOT, len(gan)))].mean(axis=1)
    return {'n': int(len(gan)), 'roi': round(roi, 4),
            'p5': round(float(np.percentile(bs, 5)), 4),
            'hit': round(float((gan > 0).mean()), 4)}


def main():
    import calibracion_mercado as cal
    d = _cargar()
    log.info(f'{len(d)} filas de fútbol con cuota en el ledger')

    objetivo = ['argentina', 'liga_mx', 'china', 'chi_primera', 'suecia']
    # controles: ligas que la regla SÍ adoptó, para ver que el método no rompe
    control = ['brasil', 'mls', 'noruega']

    filas = []
    for liga in objetivo + control:
        g = d[d['liga'] == liga]
        if len(g) < 200:
            log.warning(f'{liga}: solo {len(g)} filas; se omite')
            continue
        w_actual = cal.peso_modelo(liga)
        curva = {}
        for w in (1.0, 0.8, 0.6, 0.4, 0.3, 0.25):
            r = simular(g, w)
            if r:
                curva[w] = r
        if not curva:
            log.warning(f'{liga}: ninguna configuración llega a {MIN_N} picks')
            continue
        base = curva.get(1.0)
        mejor_w = max(curva, key=lambda k: curva[k]['roi'])
        filas.append({'liga': liga, 'w_actual': w_actual,
                      'adoptada_hoy': w_actual < 1.0,
                      'base': base, 'mejor_w': mejor_w,
                      'mejor': curva[mejor_w], 'curva': curva})

    print('\n' + '=' * 96)
    print(f"{'liga':16s} {'w hoy':>6} {'ROI w=1':>9} {'p5 w=1':>8} "
          f"{'mejor w':>8} {'ROI':>9} {'p5':>8} {'n':>6}   veredicto")
    print('=' * 96)
    for f in filas:
        b, m = f['base'], f['mejor']
        gana = m['roi'] > (b['roi'] if b else -9) and m['p5'] > 0
        ver = ('ENCOGER MEJORA (ROI y p5)' if gana else
               'encoger no mejora el ROI')
        print(f"{f['liga']:16s} {f['w_actual']:6.2f} "
              f"{(b['roi'] if b else float('nan')):9.2%} "
              f"{(b['p5'] if b else float('nan')):8.2%} "
              f"{f['mejor_w']:8.2f} {m['roi']:9.2%} {m['p5']:8.2%} "
              f"{m['n']:6d}   {ver}")
    print('=' * 96)

    print('\nDetalle de las ligas hoy RECHAZADAS por la regla de log-loss:')
    for f in filas:
        if f['liga'] not in objetivo:
            continue
        print(f"\n  {f['liga']}  (hoy w={f['w_actual']:.2f})")
        for w, r in sorted(f['curva'].items(), reverse=True):
            print(f"     w={w:.2f}  n={r['n']:4d}  ROI {r['roi']:+7.2%}  "
                  f"p5 {r['p5']:+7.2%}  acierto {r['hit']:.1%}")

    json.dump(filas, open('_v80_regla_adopcion.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
