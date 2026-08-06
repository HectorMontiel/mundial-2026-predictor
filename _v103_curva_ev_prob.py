#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v103 — Dónde deja de ser rentable perseguir el EV, y qué pasa con la probabilidad.

El usuario lo dijo claro: «no me puedes estar dando apuestas con 18 % de
probabilidad; la cosa es meter y ganar». La v103 ya midió el patrón que lo
produce —los picks de EV alto aciertan MUY por debajo de lo que prometen— y
aquí se traza la curva completa para poder poner el corte donde lo digan los
datos y no a ojo.

Se mide sobre `pick_ledger.csv` (47.948 predicciones fuera de muestra con cuota
de cierre real), tomando el lado que el modelo prefiere en cada partido.
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

BOOT = 3000
SEMILLA = 103
SALIDA = '_v103_curva_ev_prob.json'


def _roi_ic(ac, cu):
    g = ac * (cu - 1) - (1 - ac)
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([g[rng.integers(0, len(g), len(g))].mean()
                   for _ in range(BOOT)]) * 100
    return float(g.mean() * 100), float(np.percentile(bt, 5))


def main():
    led = pd.read_csv('pick_ledger.csv').dropna(
        subset=['p_home', 'p_away', 'resultado'])
    p = led[['p_home', 'p_draw', 'p_away']].fillna(0.0).to_numpy(dtype=float)
    lado = p.argmax(axis=1)
    led['prob'] = p[np.arange(len(p)), lado]
    led['acierto'] = (led['resultado'].to_numpy() == lado).astype(float)
    led['cuota'] = np.select(
        [lado == 0, lado == 1, lado == 2],
        [led['cuota_home'].to_numpy(dtype=float),
         led['cuota_draw'].to_numpy(dtype=float),
         led['cuota_away'].to_numpy(dtype=float)], np.nan)
    d = led[led['cuota'].notna() & (led['cuota'] > 1)].copy()
    d['ev'] = d['cuota'] * d['prob'] - 1
    print(f'{len(d)} predicciones fuera de muestra con cuota real\n')
    salida = {}

    print('=== ROI por banda de EV declarado ===')
    print(f'{"banda de EV":<16} {"n":>7} {"acierto":>8} {"promete":>9} '
          f'{"brecha":>8} {"ROI":>9} {"p5 ROI":>9}')
    salida['por_ev'] = {}
    for lo, hi in [(-1, 0), (0, .05), (.05, .10), (.10, .20), (.20, .35),
                   (.35, .60), (.60, 99)]:
        s = d[(d['ev'] >= lo) & (d['ev'] < hi)]
        if len(s) < 100:
            continue
        ac = s['acierto'].to_numpy(dtype=float)
        cu = s['cuota'].to_numpy(dtype=float)
        roi, p5 = _roi_ic(ac, cu)
        etq = (f'{lo:+.0%} a {hi:+.0%}' if hi < 90 else f'{lo:+.0%} o más')
        print(f'{etq:<16} {len(s):>7} {ac.mean():>8.3f} '
              f'{s["prob"].mean():>9.3f} {ac.mean()-s["prob"].mean():>+8.3f} '
              f'{roi:>+8.2f}% {p5:>+8.2f}%')
        salida['por_ev'][etq] = {
            'n': int(len(s)), 'acierto': float(ac.mean()),
            'promete': float(s['prob'].mean()),
            'brecha': float(ac.mean() - s['prob'].mean()),
            'roi_pct': roi, 'p5_roi': p5}

    print('\n=== ROI por banda de PROBABILIDAD del pick ===')
    print(f'{"probabilidad":<16} {"n":>7} {"acierto":>8} {"promete":>9} '
          f'{"brecha":>8} {"ROI":>9} {"p5 ROI":>9}')
    salida['por_prob'] = {}
    for lo, hi in [(0, .35), (.35, .45), (.45, .55), (.55, .65), (.65, .75),
                   (.75, 1.01)]:
        s = d[(d['prob'] >= lo) & (d['prob'] < hi)]
        if len(s) < 100:
            continue
        ac = s['acierto'].to_numpy(dtype=float)
        cu = s['cuota'].to_numpy(dtype=float)
        roi, p5 = _roi_ic(ac, cu)
        etq = f'{lo:.0%}-{hi:.0%}'
        print(f'{etq:<16} {len(s):>7} {ac.mean():>8.3f} '
              f'{s["prob"].mean():>9.3f} {ac.mean()-s["prob"].mean():>+8.3f} '
              f'{roi:>+8.2f}% {p5:>+8.2f}%')
        salida['por_prob'][etq] = {
            'n': int(len(s)), 'acierto': float(ac.mean()),
            'promete': float(s['prob'].mean()),
            'brecha': float(ac.mean() - s['prob'].mean()),
            'roi_pct': roi, 'p5_roi': p5}

    print('\n=== la combinación: probabilidad alta Y EV contenido ===')
    print(f'{"regla":<34} {"n":>7} {"acierto":>8} {"ROI":>9} {"p5 ROI":>9}')
    salida['reglas'] = {}
    reglas = {
        'todo (lo que hay hoy)': d['prob'] > 0,
        'prob >= 50 %': d['prob'] >= .50,
        'prob >= 55 %': d['prob'] >= .55,
        'prob >= 60 %': d['prob'] >= .60,
        'prob >= 55 % y EV <= 20 %': (d['prob'] >= .55) & (d['ev'] <= .20),
        'prob >= 55 % y EV <= 10 %': (d['prob'] >= .55) & (d['ev'] <= .10),
        'prob >= 60 % y EV <= 20 %': (d['prob'] >= .60) & (d['ev'] <= .20),
        'prob >= 60 % y EV en [0, 15 %]': ((d['prob'] >= .60) & (d['ev'] >= 0)
                                           & (d['ev'] <= .15)),
        'EV >= 20 % (lo que se destaca hoy)': d['ev'] >= .20,
    }
    for nombre, m in reglas.items():
        s = d[m]
        if len(s) < 100:
            continue
        ac = s['acierto'].to_numpy(dtype=float)
        cu = s['cuota'].to_numpy(dtype=float)
        roi, p5 = _roi_ic(ac, cu)
        print(f'{nombre:<34} {len(s):>7} {ac.mean():>8.3f} {roi:>+8.2f}% '
              f'{p5:>+8.2f}%')
        salida['reglas'][nombre] = {'n': int(len(s)),
                                    'acierto': float(ac.mean()),
                                    'roi_pct': roi, 'p5_roi': p5}

    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
