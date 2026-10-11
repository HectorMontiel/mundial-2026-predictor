#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v364 — «Ambos marcan» (sí / no) con el Método Contexto, contra los cierres de Playdoit.

El usuario: «en las apuestas arriesgadas también podrían entrar los ambos
marcan más probables o los ambos no marcan, para que los cheques con la
metodología de mi amigo».

Con `_v361_metodo.preparar()`: el modelo de goles por equipo del Método
Contexto, entrenado SÓLO con lo anterior al 24-ago, da la media de goles de
cada equipo; con Poisson, P(ambos marcan) = (1 − e^−λ_local)(1 − e^−λ_visita).
Se junta con las cuotas de Playdoit de «ambos marcan» (historial de git de
`mercado_dia.json`, la última foto antes del día) y con el resultado real.
Se mide: si promete lo que acierta, y la regla «arriesgada» (cuota 1,45-3,
método ≥ 55 %) del «sí» y del «no», en dos mitades.
Escribe `_v364_btts.json`.
"""
import json
import subprocess
import sys

import numpy as np
import pandas as pd

import _v344_precio as P
import _v361_metodo as V
import tiros_equipo as te

rng = np.random.default_rng(364)
DESDE = pd.Timestamp('2026-08-24')
CACHE = '_v364_btts_tab.pkl'


def tableros():
    try:
        return pd.read_pickle(CACHE)
    except Exception:
        pass
    hs = subprocess.run(['git', 'log', '--format=%H %cI', 'origin/main', '--', 'mercado_dia.json'],
                        capture_output=True, text=True).stdout
    filas = []
    for linea in [x for x in hs.split('\n') if x.strip()]:
        h, cuando = linea.split()
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':mercado_dia.json'],
                                          capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        ts = pd.Timestamp(cuando).tz_convert('UTC').tz_localize(None)
        for v in (d.get('partidos') or {}).values():
            if isinstance(v, dict) and v.get('btts_cuotas'):
                filas.append((ts, v.get('clave_liga'), v.get('home'), v.get('away'),
                              {'btts_cuotas': v.get('btts_cuotas'), 'casa': v.get('casa')}))
    t = pd.DataFrame(filas, columns=['ts', 'liga', 'home', 'away', 'board'])
    t['h'] = t.home.map(P._norm)
    t['a'] = t.away.map(P._norm)
    t.to_pickle(CACHE)
    return t


def resumen(x, lado):
    if not len(x):
        return {'n': 0}
    y = x.btts if lado == 'si' else 1 - x.btts
    p = x.p_si if lado == 'si' else 1 - x.p_si
    c = x.c_si if lado == 'si' else x.c_no
    gan = y * c - 1
    um, inv = np.unique(x.mid.values, return_inverse=True)
    s, n = np.bincount(inv, weights=gan.values), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in (rng.integers(0, len(um), len(um)) for _ in range(2000))]
    return {'n': int(len(x)), 'buenas': round(float(y.mean()), 3), 'promete': round(float(p.mean()), 3),
            'cuota': round(float(c.mean()), 3), 'ganancia_por_100': round(float(100 * gan.mean()), 1),
            'p5_por_100': round(float(100 * np.percentile(bs, 5)), 1)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import lightgbm as lgb
    e = V.preparar().dropna(subset=['gf'])
    el, ju = e[e.fecha < DESDE], e[e.fecha >= DESDE].copy()
    m = lgb.LGBMRegressor(objective='poisson', n_estimators=700, learning_rate=0.03, num_leaves=31,
                          min_child_samples=80, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                          reg_lambda=1.0, verbose=-1, random_state=364)
    m.fit(el[te.COLUMNAS], el.gf)
    ju['mu'] = np.clip(m.predict(ju[te.COLUMNAS]), 0.05, None)
    loc = ju[ju.local == 1][['mid', 'liga', 'fecha', 'equipo', 'rival', 'gf', 'gc', 'mu']]
    vis = ju[ju.local == 0][['mid', 'mu']].rename(columns={'mu': 'mu_v'})
    g = loc.merge(vis, on='mid')
    g['p_si'] = (1 - np.exp(-g.mu)) * (1 - np.exp(-g.mu_v))
    g['btts'] = ((g.gf > 0) & (g.gc > 0)).astype(int)
    casa = P.emparejar(ju[ju.local == 1], tableros())
    filas = []
    for r in g.itertuples():
        b = casa.get(r.mid)
        if not b:
            continue
        c = b.get('btts_cuotas') or {}
        try:
            cs, cn = float(c['si']), float(c['no'])
        except Exception:
            continue
        filas.append({'mid': r.mid, 'fecha': r.fecha, 'p_si': r.p_si, 'btts': r.btts, 'c_si': cs,
                      'c_no': cn, 'p_casa_si': (1 / cs) / (1 / cs + 1 / cn)})
    d = pd.DataFrame(filas)
    corte = d.fecha.quantile(0.5)
    d['tramo'] = np.where(d.fecha < corte, 'A', 'B')
    out = {'partidos': int(len(d)), 'corte': str(corte)[:10]}
    print('partidos con cuota de ambos marcan', len(d), 'corte', out['corte'])
    b = pd.cut(d.p_si, [0, 0.35, 0.45, 0.55, 0.65, 1.0])
    out['calibracion'] = [{'banda': str(k), 'n': int(len(x)), 'promete': round(float(x.p_si.mean()), 3),
                           'casa': round(float(x.p_casa_si.mean()), 3), 'acierta': round(float(x.btts.mean()), 3)}
                          for k, x in d.groupby(b, observed=True)]
    print('calibración (P de «sí»):', out['calibracion'])
    ll = lambda p, y: float(-(y * np.log(np.clip(p, 1e-4, 1 - 1e-4)) + (1 - y) * np.log(np.clip(1 - p, 1e-4, 1 - 1e-4))).mean())
    out['logloss'] = {'metodo': round(ll(d.p_si, d.btts), 4), 'casa': round(ll(d.p_casa_si, d.btts), 4)}
    print('log-loss método vs casa:', out['logloss'])
    for lado in ('si', 'no'):
        p = d.p_si if lado == 'si' else 1 - d.p_si
        c = d.c_si if lado == 'si' else d.c_no
        out[lado] = {}
        for pm in (0.55, 0.60):
            x = d[(p >= pm) & (c >= 1.45) & (c <= 3.0)]
            out[lado]['%d' % int(pm * 100)] = {tr: resumen(x[x.tramo == tr], lado) for tr in ('A', 'B')}
            print('ambos marcan «%s», método ≥ %d %%:' % (lado, int(pm * 100)),
                  json.dumps(out[lado]['%d' % int(pm * 100)], ensure_ascii=False))
    json.dump(out, open('_v364_btts.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
