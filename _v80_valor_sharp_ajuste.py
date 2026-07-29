#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — Parámetros de `valor_vs_sharp`, elegidos FUERA DE MUESTRA.

El barrido de `_v80_valor_sharp.py` mostró edge validado en las 13
configuraciones probadas, con el mejor punto en margen 10 % (ROI +16,11 %,
p5 +6,65 %). Quedarse con ese número sería repetir el error que este proyecto
ya cometió y corrigió dos veces: es el máximo de un barrido, y el máximo de un
barrido siempre parece bueno.

Aquí los parámetros se eligen en la PRIMERA parte del histórico y se miden en
la última, que no participa en la elección. Es el mismo protocolo que usa
`recalibrate_from_history` para el peso `w`.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('ajuste')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 5000
MIN_N = 60
CORTE = 0.70          # 70 % para elegir, 30 % para validar


def devig_potencia(cuotas):
    inv = 1.0 / np.clip(cuotas, 1.0001, None)
    k = np.ones(len(cuotas))
    for _ in range(60):
        s = (inv ** k[:, None]).sum(axis=1)
        err = s - 1.0
        if np.all(np.abs(err) < 1e-10):
            break
        k = np.clip(k + err * 0.5, 0.2, 5.0)
    p = inv ** k[:, None]
    return p / p.sum(axis=1, keepdims=True)


def evaluar(cu, justa, res, ev, margen, pmin):
    sel = (ev > margen) & (justa > pmin)
    if sel.sum() < MIN_N:
        return None
    idx = np.argwhere(sel)
    gan = np.array([cu[i, j] - 1.0 if res[i] == j else -1.0 for i, j in idx],
                   float)
    rng = np.random.default_rng(5)
    bs = gan[rng.integers(0, len(gan), size=(N_BOOT, len(gan)))].mean(axis=1)
    return {'n': int(len(gan)), 'roi': float(gan.mean()),
            'p5': float(np.percentile(bs, 5)),
            'hit': float((gan > 0).mean())}


def main():
    d = pd.read_csv(LEDGER, low_memory=False)
    d = d[d['deporte'] == 'Fútbol']
    ok = (d[['cuota_home', 'cuota_draw', 'cuota_away']].notna().all(axis=1) &
          d[['pin_home', 'pin_draw', 'pin_away']].notna().all(axis=1))
    d = d[ok].copy()
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['fecha']).sort_values('fecha').reset_index(drop=True)
    n = len(d)
    corte = int(n * CORTE)
    f_corte = d['fecha'].iloc[corte]
    log.info(f'{n} partidos · elección hasta {f_corte.date()} '
             f'({corte}) · validación después ({n - corte})')

    cu = d[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    pin = d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float)
    res = d['resultado'].values.astype(int)
    justa = devig_potencia(pin)
    ev = cu * justa - 1.0

    tr = slice(0, corte)
    te = slice(corte, n)

    mejor, tabla = None, []
    for margen in (0.01, 0.02, 0.03, 0.05, 0.08, 0.10):
        for pmin in (0.0, 0.20, 0.30, 0.40):
            r = evaluar(cu[tr], justa[tr], res[tr], ev[tr], margen, pmin)
            if not r:
                continue
            tabla.append({'margen': margen, 'pmin': pmin, **r})
            # criterio: p5 positivo y el mayor; el ROI solo desempata
            if r['p5'] > 0 and (mejor is None or r['p5'] > mejor['p5']):
                mejor = {'margen': margen, 'pmin': pmin, **r}

    print('\nELECCIÓN (primer 70 %)')
    print(f"{'margen':>7} {'prob min':>9} {'n':>6} {'ROI':>9} {'p5':>9}")
    print('-' * 46)
    for t in sorted(tabla, key=lambda x: -x['p5'])[:10]:
        print(f"{t['margen']:7.0%} {t['pmin']:9.0%} {t['n']:6d} "
              f"{t['roi']:9.2%} {t['p5']:9.2%}")

    if not mejor:
        print('\nninguna configuración con p5 positivo en la elección')
        return
    print(f"\nElegido: margen {mejor['margen']:.0%} · prob mínima "
          f"{mejor['pmin']:.0%}  (p5 {mejor['p5']:+.2%} en la elección)")

    val = evaluar(cu[te], justa[te], res[te], ev[te],
                  mejor['margen'], mejor['pmin'])
    print('\nVALIDACIÓN (último 30 %, no participó en la elección)')
    if not val:
        print('  muestra insuficiente en validación')
        return
    print(f"  n={val['n']}  ROI {val['roi']:+.2%}  p5 {val['p5']:+.2%}  "
          f"acierto {val['hit']:.1%}")
    edge = val['roi'] > 0 and val['p5'] > 0
    print(f"\nVEREDICTO: {'EDGE CONFIRMADO fuera de muestra' if edge else 'NO se confirma'}")

    # referencia: la configuración que produccion aplica hoy (sin filtros)
    act = evaluar(cu[te], justa[te], res[te], ev[te], 0.0, 0.0)
    if act:
        print(f"\nReferencia — lo que produccion emite HOY (sin margen ni "
              f"probabilidad mínima), en el mismo periodo:")
        print(f"  n={act['n']}  ROI {act['roi']:+.2%}  p5 {act['p5']:+.2%}")

    json.dump({'eleccion': mejor, 'validacion': val, 'actual': act,
               'tabla': tabla},
              open('_v80_valor_sharp_ajuste.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
