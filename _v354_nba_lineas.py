#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v354 — NBA: hándicap y totales alternativos, contra la línea de la casa.

El usuario: «quiero ganador y más/menos puntos en NBA; quizá no al 80 %,
empecemos con 75 % y lo vamos subiendo; con la lógica del fútbol: contra la
casa, ver cómo está nuestro modelo».

Lo que publica Playdoit (tableros del 9-oct, `cuotas_multi.mercados_playdoit`):
ganador, hándicap con escalera hasta ±13 puntos de la principal (cuota mínima
~1,17-1,25) y totales con escalera hasta ±9-10 (cuota mínima ~1,37-1,59).

Aquí, con la réplica sin fuga de `_v330_nba` (2010-2025, cierre de la casa):
  1. TABLAS: lo que acierta la línea alternativa según su distancia k a la
     principal (hándicap del favorito / del no favorito; más / menos), elegida
     con 2010-16 y juzgada con 2017-25.
  2. EL MODELO: ¿acierta más la alternativa cuando el modelo ve el partido
     del mismo lado que la apuesta?
  3. LA PRETEMPORADA (ESPN, `_v354_nba_pretemporada.csv`): ¿la casa acierta
     lo que promete?, ¿la tabla vale?
Guarda las tablas que usa la app en `nba_lineas.json`.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(354)
KS = [x + 0.5 for x in range(0, 25)]


def regular():
    import _v330_nba as B
    d = B.nh.cargar()
    x, _ = B.ne.dataset(d)
    x['p_mkt'] = B.mercado(x)
    r = B.walk_forward(x, range(2010, 2026))
    r = r[r.spread.notna() & r.total_linea.notna() & r.margen.notna()].copy()
    return r


def tablas(r):
    """{'favorito', 'no_favorito', 'mas', 'menos'}: {k: acierto}."""
    s = r.spread.abs()
    mfav = np.where(r.spread >= 0, r.margen, -r.margen)
    out = {'favorito': {}, 'no_favorito': {}, 'mas': {}, 'menos': {}}
    for k in KS:
        out['favorito'][k] = float(((mfav - s + k) > 0).mean())
        out['no_favorito'][k] = float(((-mfav + s + k) > 0).mean())
        out['mas'][k] = float((r.total > r.total_linea - k).mean())
        out['menos'][k] = float((r.total < r.total_linea + k).mean())
    return out


def modelo(r):
    """El no favorito +k (y el favorito) con el modelo de acuerdo o no."""
    s = r.spread.abs()
    fav_local = r.spread >= 0
    mfav = np.where(fav_local, r.margen, -r.margen)
    mod_fav = np.where(fav_local, r.m_pred, -r.m_pred)     # margen del favorito según el modelo
    dif = mod_fav - s          # >0: el modelo ve al favorito más fuerte que la casa
    out = {}
    for tramo, f in (('elige', r.temporada <= 2016), ('juzga', r.temporada > 2016)):
        for k in (8.5, 10.5, 12.5):
            dog = ((-mfav + s + k) > 0)
            fav = ((mfav - s + k) > 0)
            out['%s_k%s' % (tramo, k)] = {
                'no_fav_modelo_con_el': round(float(dog[f & (dif <= -2)].mean()), 4),
                'no_fav_resto': round(float(dog[f & (dif > -2)].mean()), 4),
                'n_con_el': int((f & (dif <= -2)).sum()),
                'fav_modelo_con_el': round(float(fav[f & (dif >= 2)].mean()), 4),
                'fav_resto': round(float(fav[f & (dif < 2)].mean()), 4),
                'n_fav_con_el': int((f & (dif >= 2)).sum())}
    return out


def pretemporada():
    if not os.path.exists('_v354_nba_pretemporada.csv'):
        return None
    p = pd.read_csv('_v354_nba_pretemporada.csv')
    p = p[p.ml_home.notna() & p.ml_away.notna() & p.spread.notna()]
    p = p[p.nba_vs_nba == True]
    p['margen'] = p.pts_home - p.pts_away
    p['tot'] = p.pts_home + p.pts_away
    ph = (1 / p.ml_home) / (1 / p.ml_home + 1 / p.ml_away)
    p['p_fav'] = np.maximum(ph, 1 - ph)
    p['gana_fav'] = np.where(ph >= 0.5, p.margen > 0, p.margen < 0).astype(int)
    out = {'partidos': int(len(p)), 'temporadas': sorted(p.temporada.unique().tolist())}
    b = p.assign(banda=pd.cut(p.p_fav, [0.5, 0.6, 0.7, 0.78, 0.85, 1.0]))
    out['ganador_por_banda'] = [
        {'banda': str(k), 'n': int(len(g)), 'promete': round(float(g.p_fav.mean()), 3),
         'acierta': round(float(g.gana_fav.mean()), 3)}
        for k, g in b.groupby('banda', observed=True)]
    g = p[p.p_fav >= 0.78]
    out['regla_ganador_casa78'] = {'n': int(len(g)), 'acierta': round(float(g.gana_fav.mean()), 3)
                                   if len(g) else None}
    # ESPN da el spread con signo del favorito (negativo); el margen esperado
    # del local sale del moneyline: si el local es favorito, +|spread|
    esp = np.where(ph >= 0.5, p.spread.abs(), -p.spread.abs())
    r = pd.DataFrame({'spread': esp, 'margen': p.margen, 'total_linea': p.total,
                      'total': p.tot})
    out['tablas'] = {k: {kk: round(v, 4) for kk, v in t.items() if kk in (8.5, 10.5, 12.5, 14.5)}
                     for k, t in tablas(r.dropna()).items()}
    out['sd_margen_vs_linea'] = round(float((r.margen - r.spread).std()), 2)
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    r = regular()
    el, ju = r[r.temporada <= 2016], r[r.temporada > 2016]
    te, tj = tablas(el), tablas(ju)
    print('k   | favorito e/j | no_fav e/j | más e/j | menos e/j')
    for k in (6.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5):
        print(k, ['%.3f/%.3f' % (te[c][k], tj[c][k]) for c in ('favorito', 'no_favorito', 'mas', 'menos')])
    print('sd margen-línea regular: %.2f' % (r.margen - r.spread).std())
    m = modelo(r)
    print(json.dumps(m, indent=1))
    pre = pretemporada()
    print(json.dumps(pre, ensure_ascii=False, indent=1, default=str))
    doc = {'generado': pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
           'fuente': 'réplica _v330_nba 2017-2025 (juicio), cierre de la casa',
           'tablas': {c: {'%.1f' % k: round(v, 4) for k, v in t.items()} for c, t in tj.items()},
           'tablas_elige_2010_2016': {c: {'%.1f' % k: round(v, 4) for k, v in t.items()}
                                      for c, t in te.items()},
           'modelo': m, 'pretemporada': pre}
    json.dump(doc, open('nba_lineas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
