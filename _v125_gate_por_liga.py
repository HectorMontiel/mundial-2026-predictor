#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v125 — ¿Mejora el edge de precio si se filtra por el backtest de la liga?

La pregunta
-----------
La propuesta de la Sección 1 es:

    Playdoit > consenso del mercado   AND   backtest de la liga > 53,5 %

La primera condición está medida y es la única con ROI positivo del proyecto.
La segunda **no está medida**, y hay un motivo para dudar de ella: la ventaja de
precio es MODEL-INDEPENDIENTE. Que una casa pague por encima del consenso no
tiene nada que ver con lo bien que nuestro modelo prediga esa liga. Filtrar por
el backtest sólo ayudaría si las dos cosas correlacionaran, y no hay ninguna
razón para pensarlo.

Peor: el proyecto ya tiene medido que la precisión del modelo NO predice el ROI
(la banda de mayor acierto, 0,65-0,70 con 61,5 %, es la de peor ROI, −6,52 %).
Aplicar el mismo tipo de filtro a nivel de liga puede repetir ese error.

Cómo se mide
------------
`odds_snapshots.csv` guarda el precio de cada casa por partido y lado. Para cada
selección con dos o más casas se toma el MEJOR precio y se compara contra el
consenso sin margen (devig del resto). Se liquida contra el resultado real del
histórico de la liga y se calcula el ROI:

  · de TODAS las selecciones con ventaja de precio,
  · y separadas por el backtest de la liga (por encima / por debajo de 53,5 %).

Si el grupo de backtest alto no bate al de backtest bajo, el filtro no aporta y
no debe entrar: estaría tirando picks buenos sin ganar nada.

Uso:  python _v125_gate_por_liga.py
"""
import glob
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

UMBRAL_PROPUESTO = 0.535
LADOS = (('home', 'odds_home'), ('draw', 'odds_draw'), ('away', 'odds_away'))


def backtests_por_liga() -> dict:
    """Precisión de validación de cada liga, del metadata de su modelo."""
    fuera = {}
    for f in glob.glob(os.path.join('modelos', '*', 'metadata.json')):
        liga = os.path.basename(os.path.dirname(f))
        try:
            m = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        if m.get('precision_validacion'):
            fuera[liga] = float(m['precision_validacion'])
    return fuera


def resultados_reales() -> pd.DataFrame:
    """El resultado de cada partido, de los históricos del proyecto."""
    marcos = []
    for f in glob.glob('historico_*.csv'):
        try:
            d = pd.read_csv(f, usecols=lambda c: c in (
                'date', 'home_team', 'away_team', 'home_goals', 'away_goals'))
        except Exception:
            continue
        if not {'date', 'home_team', 'away_team',
                'home_goals', 'away_goals'} <= set(d.columns):
            continue
        d = d.dropna(subset=['home_goals', 'away_goals'])
        if d.empty:
            continue
        d['ganador'] = np.where(d['home_goals'] > d['away_goals'], 'home',
                                np.where(d['home_goals'] < d['away_goals'],
                                         'away', 'draw'))
        d['clave'] = (pd.to_datetime(d['date'], errors='coerce', format='mixed')
                      .dt.strftime('%Y%m%d') + '_'
                      + d['home_team'].astype(str) + '_'
                      + d['away_team'].astype(str))
        marcos.append(d[['clave', 'ganador']])
    return (pd.concat(marcos, ignore_index=True).drop_duplicates('clave')
            if marcos else pd.DataFrame(columns=['clave', 'ganador']))


def main() -> int:
    if not os.path.exists('odds_snapshots.csv'):
        print('No existe odds_snapshots.csv: no hay con qué medir.')
        return 1
    d = pd.read_csv('odds_snapshots.csv', low_memory=False)
    print(f'snapshots: {len(d):,} filas · {d["bookmaker"].nunique()} casas'
          .replace(',', '.'))

    # Sólo fotos previas al partido con precio de 1X2
    d = d[d['odds_home'].notna() & d['odds_away'].notna()]
    res = resultados_reales()
    print(f'partidos con resultado en el histórico: {len(res):,}'
          .replace(',', '.'))

    d['clave'] = (pd.to_datetime(d['match_date'], errors='coerce')
                  .dt.strftime('%Y%m%d') + '_'
                  + d['home_team'].astype(str) + '_'
                  + d['away_team'].astype(str))
    d = d.merge(res, on='clave', how='inner')
    print(f'filas con resultado: {len(d):,}'.replace(',', '.'))
    if d.empty:
        print('Sin solape entre las fotos de cuotas y los resultados.')
        return 1

    bt = backtests_por_liga()
    filas = []
    # una selección = (partido, lado). Se necesita 2+ casas para que exista
    # «mejor precio» y «consenso».
    for (clave, liga), g in d.groupby(['clave', 'league_key']):
        if g['bookmaker'].nunique() < 2:
            continue
        ganador = g['ganador'].iloc[0]
        for lado, col in LADOS:
            precios = pd.to_numeric(g[col], errors='coerce').dropna()
            precios = precios[precios > 1]
            if len(precios) < 2:
                continue
            mejor = float(precios.max())
            # consenso = media de las demás casas (sin la que da el mejor)
            resto = precios[precios < mejor]
            if resto.empty:
                continue
            consenso = float(resto.mean())
            ventaja = mejor / consenso - 1
            if ventaja <= 0:
                continue
            filas.append({
                'liga': liga, 'lado': lado, 'ventaja': ventaja,
                'cuota': mejor, 'acierta': int(lado == ganador),
                'backtest': bt.get(liga),
            })
    if not filas:
        print('Ninguna selección con dos o más casas y ventaja de precio.')
        return 1
    f = pd.DataFrame(filas)
    f['retorno'] = np.where(f['acierta'] == 1, f['cuota'] - 1, -1.0)
    print(f'\nselecciones con ventaja de precio: {len(f):,}'.replace(',', '.'))

    def _roi(sub, etq):
        if sub.empty:
            print(f'  {etq:38} sin datos')
            return
        roi = sub['retorno'].mean()
        # bootstrap del percentil 5, que es como este proyecto juzga un ROI
        rng = np.random.default_rng(7)
        b = [rng.choice(sub['retorno'].values, len(sub), replace=True).mean()
             for _ in range(2000)]
        print(f'  {etq:38} n={len(sub):6,}  ROI {roi*100:+6.2f} %  '
              f'p5 {np.percentile(b, 5)*100:+6.2f} %'.replace(',', '.'))

    print('\n=== ¿aporta el filtro por backtest de liga? ===')
    _roi(f, 'TODAS las que tienen ventaja')
    con_bt = f[f['backtest'].notna()]
    _roi(con_bt[con_bt['backtest'] > UMBRAL_PROPUESTO],
         f'liga con backtest > {UMBRAL_PROPUESTO:.1%}')
    _roi(con_bt[con_bt['backtest'] <= UMBRAL_PROPUESTO],
         f'liga con backtest <= {UMBRAL_PROPUESTO:.1%}')

    print('\n=== por tamaño de la ventaja de precio ===')
    for lo, hi in ((0.0, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 1.0)):
        _roi(f[(f['ventaja'] > lo) & (f['ventaja'] <= hi)],
             f'ventaja {lo:.0%}-{hi:.0%}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
