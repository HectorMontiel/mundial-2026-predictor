#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v105 — Cuánto edge hay REALMENTE en el line shopping, y cuánto se está cogiendo.

Por qué esta medición
---------------------
La v104 dejó claro que el modelo no bate al mercado en 1X2: su probabilidad es
peor que el precio (log-loss 1,024 contra 0,9997). El proyecto ya sabía que su
edge validado está en otro sitio —comprar el mejor precio disponible— pero eso
se midió una vez, en la v90, y nunca se cuantificó el TECHO: cuánto edge existe
y qué fracción se recoge.

Sin ese techo no se puede decidir si merece la pena añadir casas, que es la
única palanca de esta vía.

Cómo se mide
------------
`odds_snapshots.csv` guarda, por partido y por casa, el precio de cada lado.
Para cada partido con dos o más casas se compara:

  A · apostar al precio de UNA casa fija (la más frecuente).
  B · apostar al MEJOR precio disponible entre las casas de ese momento.

La diferencia entre A y B es el line shopping puro: mismo pick, distinto
precio. Se mide sobre los partidos que además tienen resultado en el histórico.

Se reporta también la DISPERSIÓN (cuánto separa el mejor precio del peor), que
es el techo teórico: sin dispersión no hay nada que recoger por mucho que se
añadan casas.
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

BOOT = 4000
SEMILLA = 105
SALIDA = '_v105_edge_line_shopping.json'
CASAS_REALES = ('Pinnacle', 'Bovada', 'DraftKings', 'Playdoit')


def resultados_por_match_id() -> pd.DataFrame:
    """Marcador de cada partido, desde todos los históricos de fútbol."""
    filas = []
    for f in sorted(os.listdir('.')):
        if not (f.startswith('historico_') and f.endswith('.csv')):
            continue
        try:
            d = pd.read_csv(f, low_memory=False,
                            usecols=['MATCH_ID', 'home_goals', 'away_goals'])
        except Exception:
            continue
        filas.append(d)
    r = pd.concat(filas, ignore_index=True).dropna()
    r = r.drop_duplicates('MATCH_ID')
    r['res'] = np.where(r.home_goals > r.away_goals, 0,
                        np.where(r.home_goals == r.away_goals, 1, 2))
    return r[['MATCH_ID', 'res']].set_index('MATCH_ID')


def main():
    d = pd.read_csv('odds_snapshots.csv', low_memory=False)
    d = d[d['bookmaker'].isin(CASAS_REALES)]
    d = d.dropna(subset=['odds_home', 'odds_away'])
    print(f'{len(d)} filas de casas reales · '
          f'{d.bookmaker.value_counts().to_dict()}')

    res = resultados_por_match_id()
    d = d.join(res, on='match_id', how='inner')
    print(f'{len(d)} filas con resultado conocido · '
          f'{d.match_id.nunique()} partidos')

    # una fila por (partido, casa): el precio de cada lado
    piv = d.groupby(['match_id', 'bookmaker']).agg(
        oh=('odds_home', 'max'), od=('odds_draw', 'max'),
        oa=('odds_away', 'max'), res=('res', 'first')).reset_index()
    n_casas = piv.groupby('match_id')['bookmaker'].nunique()
    multi = n_casas[n_casas >= 2].index
    print(f'{len(multi)} partidos con 2+ casas '
          f'({len(multi)/max(piv.match_id.nunique(),1):.0%} de los que tienen precio)')
    print(f'reparto de casas por partido: '
          f'{n_casas.value_counts().sort_index().to_dict()}')

    p = piv[piv.match_id.isin(multi)].copy()
    salida = {'n_partidos_multi': int(len(multi))}

    # --- DISPERSIÓN: el techo teórico -------------------------------------
    disp = p.groupby('match_id').agg(
        mejor_h=('oh', 'max'), peor_h=('oh', 'min'),
        mejor_a=('oa', 'max'), peor_a=('oa', 'min'))
    disp['spread_h'] = disp.mejor_h / disp.peor_h - 1
    disp['spread_a'] = disp.mejor_a / disp.peor_a - 1
    med = float(np.nanmean([disp.spread_h.mean(), disp.spread_a.mean()]))
    print(f'\ndispersión media entre la mejor y la peor casa: {med:.2%}')
    print(f'  percentiles del spread (local): '
          f'p50 {disp.spread_h.median():.2%} · p90 {disp.spread_h.quantile(.9):.2%}')
    salida['dispersion_media'] = med
    salida['spread_p50'] = float(disp.spread_h.median())
    salida['spread_p90'] = float(disp.spread_h.quantile(.9))

    # --- A contra B: misma apuesta, precio fijo o mejor precio ------------
    print('\nmismo pick, distinto precio (se apuesta SIEMPRE al favorito '
          'del mercado, para aislar el efecto del precio):')
    print(f'{"estrategia":<30} {"n":>7} {"acierto":>8} {"ROI":>9} {"p5":>9}')
    rng = np.random.default_rng(SEMILLA)
    resultados = {}

    def _roi(cuotas, aciertos, etiqueta):
        g = aciertos * (cuotas - 1) - (1 - aciertos)
        bt = np.array([g[rng.integers(0, len(g), len(g))].mean()
                       for _ in range(BOOT)]) * 100
        roi, p5 = float(g.mean() * 100), float(np.percentile(bt, 5))
        print(f'{etiqueta:<30} {len(g):>7} {aciertos.mean():>8.3f} '
              f'{roi:>+8.2f}% {p5:>+8.2f}%')
        resultados[etiqueta] = {'n': int(len(g)), 'acierto': float(aciertos.mean()),
                                'roi_pct': roi, 'p5': p5}
        return roi

    # el lado elegido: el favorito según la MEJOR cuota disponible (consenso)
    agg = p.groupby('match_id').agg(
        best_h=('oh', 'max'), best_d=('od', 'max'), best_a=('oa', 'max'),
        res=('res', 'first'))
    lado = agg[['best_h', 'best_d', 'best_a']].to_numpy(dtype=float).argmin(axis=1)
    y = agg['res'].to_numpy(dtype=int)
    aciertos = (lado == y).astype(float)

    # B · mejor precio disponible
    mejores = agg[['best_h', 'best_d', 'best_a']].to_numpy(dtype=float)
    cu_b = mejores[np.arange(len(agg)), lado]
    roi_b = _roi(cu_b, aciertos, 'B · mejor precio disponible')

    # A · cada casa por separado, en los MISMOS partidos
    for casa in CASAS_REALES:
        sub = p[p.bookmaker == casa].set_index('match_id')
        comun = agg.index.intersection(sub.index)
        if len(comun) < 200:
            continue
        m = agg.loc[comun]
        l2 = m[['best_h', 'best_d', 'best_a']].to_numpy(dtype=float).argmin(axis=1)
        cu = sub.loc[comun, ['oh', 'od', 'oa']].to_numpy(dtype=float)[
            np.arange(len(comun)), l2]
        ok = ~np.isnan(cu) & (cu > 1)
        ac = (l2 == m['res'].to_numpy(dtype=int)).astype(float)
        _roi(cu[ok], ac[ok], f'A · siempre {casa}')

    salida['detalle'] = resultados
    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
