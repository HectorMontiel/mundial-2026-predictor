#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v103 — ¿Cuánto tiene que conocer el modelo a dos equipos para poder opinar?

El caso que lo destapa
----------------------
Apuestas del Día publicó «Gana Vikingur Reykjavik» a cuota 9,50 con un EV de
+74 % y una probabilidad del 18 %. El usuario lo señaló: de qué sirve un pick
que se pierde 4 de cada 5 veces.

Mirando los datos, el pick no salió de un modelo optimista: salió de un modelo
CIEGO. En el histórico de la Conference League, Vikingur Reykjavik tiene 8
partidos y el Nordsjælland 6, así que sus ELO son 1501,4 y 1510,7 — el valor de
arranque, 1500, prácticamente sin mover. El modelo veía dos equipos idénticos y
repartía 46 %/54 %; el mercado, que sabe que uno es islandés y el otro danés de
primera, pagaba 9,50 (10,5 % implícito). El EV enorme no era valor: era
ignorancia enfrentada a un precio informado.

Y no es un caso aislado: **68 de los 135 equipos de la Conference tienen 8
partidos o menos**. La mediana son 8. En una competición eliminatoria, el ELO
por competición nunca converge.

Qué se mide
-----------
Si la profundidad de historial predice el fallo, hay un umbral por debajo del
cual el modelo no debería opinar. Para cada partido del ledger se calcula
`conocimiento` = número de partidos previos del equipo con MENOS historial de
los dos, y se mide por tramos:

  · acierto real contra probabilidad prometida (brecha de calibración),
  · ROI con la cuota registrada,
  · y el desacuerdo con el mercado, que es la señal de alarma.

Si los tramos bajos salen mal calibrados y con ROI negativo, el gate está
justificado por datos y no por intuición.
"""
import json
import os
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
SALIDA = '_v103_ab_conocimiento.json'
TRAMOS = [(0, 5), (5, 10), (10, 20), (20, 40), (40, 10_000)]


def conocimiento_por_partido() -> pd.DataFrame:
    """Partidos previos del lado con MENOS historial, cronológicamente."""
    filas = []
    for f in sorted(os.listdir('.')):
        if not (f.startswith('historico_') and f.endswith('.csv')):
            continue
        try:
            d = pd.read_csv(f, low_memory=False)
        except Exception:
            continue
        if not {'date', 'home_team', 'away_team', 'MATCH_ID'}.issubset(d.columns):
            continue
        d = d.copy()
        d['_f'] = pd.to_datetime(d['date'], errors='coerce')
        d = d.sort_values('_f', kind='stable')
        vistos = {}
        mid = d['MATCH_ID'].to_numpy()
        h = d['home_team'].astype(str).to_numpy()
        a = d['away_team'].astype(str).to_numpy()
        for i in range(len(d)):
            nh, na = vistos.get(h[i], 0), vistos.get(a[i], 0)
            filas.append((mid[i], min(nh, na), max(nh, na)))
            vistos[h[i]] = nh + 1
            vistos[a[i]] = na + 1
    t = pd.DataFrame(filas, columns=['MATCH_ID', 'conocimiento', 'conoc_max'])
    return t.drop_duplicates('MATCH_ID').set_index('MATCH_ID')


def main():
    tabla = conocimiento_por_partido()
    print(f'conocimiento calculado para {len(tabla)} partidos')
    led = pd.read_csv('pick_ledger.csv').join(tabla, on='match_id', how='inner')
    led = led.dropna(subset=['p_home', 'p_away', 'resultado', 'conocimiento'])
    p = led[['p_home', 'p_draw', 'p_away']].fillna(0.0).to_numpy(dtype=float)
    lado = p.argmax(axis=1)
    led['prob'] = p[np.arange(len(p)), lado]
    led['acierto'] = (led['resultado'].to_numpy() == lado).astype(float)
    led['cuota'] = np.select(
        [lado == 0, lado == 1, lado == 2],
        [led['cuota_home'].to_numpy(dtype=float),
         led['cuota_draw'].to_numpy(dtype=float),
         led['cuota_away'].to_numpy(dtype=float)], np.nan)
    # probabilidad implícita del mercado en ESE lado (sin quitar margen: sirve
    # para medir el DESACUERDO, no para valorar)
    led['p_mercado'] = 1.0 / led['cuota']

    print(f'{len(led)} predicciones con cuota y conocimiento\n')
    print(f'{"conocimiento":<22} {"n":>7} {"acierto":>8} {"prometido":>10} '
          f'{"brecha":>8} {"ROI":>9} {"desacuerdo":>11}')
    rng = np.random.default_rng(SEMILLA)
    salida = {}
    for lo, hi in TRAMOS:
        m = (led['conocimiento'] >= lo) & (led['conocimiento'] < hi)
        s = led[m]
        if len(s) < 100:
            continue
        ac = s['acierto'].to_numpy(dtype=float)
        pr = s['prob'].to_numpy(dtype=float)
        cu = s['cuota'].to_numpy(dtype=float)
        ok = ~np.isnan(cu) & (cu > 1)
        roi = (float(np.mean(ac[ok] * (cu[ok] - 1) - (1 - ac[ok]))) * 100
               if ok.sum() >= 50 else None)
        des = float(np.nanmean(np.abs(pr - s['p_mercado'].to_numpy(dtype=float))))
        brecha = float(ac.mean() - pr.mean())
        bt = np.array([(lambda i: ac[i].mean() - pr[i].mean())(
            rng.integers(0, len(ac), len(ac))) for _ in range(BOOT)])
        etq = f'{lo}-{hi if hi < 10000 else "+"} partidos'
        print(f'{etq:<22} {len(s):>7} {ac.mean():>8.3f} {pr.mean():>10.3f} '
              f'{brecha:>+8.3f} '
              + (f'{roi:>+8.2f}%' if roi is not None else f'{"—":>9}')
              + f' {des:>11.3f}')
        salida[etq] = {'n': int(len(s)), 'acierto': float(ac.mean()),
                       'prometido': float(pr.mean()), 'brecha': brecha,
                       'ic': [float(np.percentile(bt, 5)),
                              float(np.percentile(bt, 95))],
                       'roi_pct': roi, 'desacuerdo_medio': des}

    # y el caso concreto: picks de EV alto con poco conocimiento
    print('\n=== picks de EV alto (el patrón del Vikingur) ===')
    led['ev'] = led['cuota'] * led['prob'] - 1
    for lo, hi in ((0, 10), (10, 10_000)):
        for ev_min in (0.20, 0.50):
            m = ((led['conocimiento'] >= lo) & (led['conocimiento'] < hi)
                 & (led['ev'] >= ev_min) & led['cuota'].notna())
            s = led[m]
            if len(s) < 30:
                continue
            ac = s['acierto'].to_numpy(dtype=float)
            cu = s['cuota'].to_numpy(dtype=float)
            roi = float(np.mean(ac * (cu - 1) - (1 - ac))) * 100
            etq = (f'conocimiento {"<10" if hi <= 10 else "≥10"} · EV≥{ev_min:.0%}')
            print(f'  {etq:<32} n={len(s):>5} · acierto {ac.mean():.3f} '
                  f'· prometido {s["prob"].mean():.3f} · ROI {roi:+.2f} %')
            salida[etq] = {'n': int(len(s)), 'acierto': float(ac.mean()),
                           'prometido': float(s['prob'].mean()), 'roi_pct': roi}

    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
