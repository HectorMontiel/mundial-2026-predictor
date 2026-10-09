#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v344 — la metodología de tiros CONTRA LA LÍNEA DE PLAYDOIT.

`_v344_tiros.py` midió que la metodología predice los tiros mucho mejor que
«los últimos 5». Para apostar eso no basta: hay que ganarle al precio. Aquí:

  1. el modelo se entrena SÓLO con partidos anteriores al 24-ago-2026;
  2. para cada partido posterior con estadística real (ESPN), se busca la
     última foto del tablero de Playdoit (`mercado_dia.json` en git) anterior
     al día del partido, y sus líneas de tiros del equipo (`remates_home/away`)
     y a puerta (`remates_on_home/away`);
  3. se compara la probabilidad del modelo con la de la casa sin margen
     (log-loss) y se simula apostar: el lado que el modelo ve ≥ X puntos por
     encima de la casa, a la cuota de la casa.

Uso: python _v344_precio.py
"""
import json
import subprocess
import unicodedata

import numpy as np
import pandas as pd

import _v344_tiros as T

DESDE = pd.Timestamp('2026-08-24')
CACHE = '_v344_tableros.pkl'
rng = np.random.default_rng(3441)


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return ''.join(ch for ch in s.lower() if ch.isalnum())


def tableros():
    """[(ts_utc, clave_liga, home, away, board)] de todas las fotos."""
    try:
        return pd.read_pickle(CACHE)
    except Exception:
        pass
    hs = subprocess.run(['git', 'log', '--format=%H %cI', 'origin/main', '--',
                         'mercado_dia.json'], capture_output=True, text=True).stdout
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
            if not isinstance(v, dict):
                continue
            b = {k: v.get(k) for k in ('remates_home', 'remates_away',
                                       'remates_on_home', 'remates_on_away',
                                       '1x2_cuotas', 'casa')}
            if not (b['remates_home'] or b['remates_on_home']):
                continue
            filas.append((ts, v.get('clave_liga'), v.get('home'), v.get('away'), b))
    t = pd.DataFrame(filas, columns=['ts', 'liga', 'home', 'away', 'board'])
    t['h'] = t.home.map(_norm)
    t['a'] = t.away.map(_norm)
    t.to_pickle(CACHE)
    return t


def _parece(x, y):
    try:
        import cuotas_multi as cm
        return cm._sim_club(x, y)
    except Exception:
        return 1.0 if _norm(x) == _norm(y) else 0.0


def emparejar(partidos, tab):
    """Para cada partido (fila home), la última foto anterior a su día."""
    out = {}
    por_liga = {k: g for k, g in tab.groupby('liga')}
    for r in partidos.itertuples():
        g = por_liga.get(r.liga)
        if g is None:
            continue
        g = g[g.ts < r.fecha]                      # antes del día del partido
        g = g[g.ts >= r.fecha - pd.Timedelta(days=3)]
        if g.empty:
            continue
        nh, na = _norm(r.equipo), _norm(r.rival)
        cand = g[(g.h == nh) & (g.a == na)]
        if cand.empty:
            pares = g[['home', 'away']].drop_duplicates()
            ok = [(hh, aa) for hh, aa in pares.itertuples(index=False)
                  if _parece(r.equipo, hh) >= 0.8 and _parece(r.rival, aa) >= 0.8]
            if not ok:
                continue
            cand = g[(g.home == ok[0][0]) & (g.away == ok[0][1])]
        out[r.mid] = cand.sort_values('ts').iloc[-1].board
    return out


def _lineas(txt):
    if not txt:
        return {}
    if isinstance(txt, str):
        import ast
        try:
            txt = ast.literal_eval(txt)
        except Exception:
            return {}
    return txt if isinstance(txt, dict) else {}


def main():
    import lightgbm as lgb
    e = T.preparar()
    e = e[~e.liga.isin(T.COPAS)].copy()
    e['liga_tiros'] = T.media_liga(e, 'tiros')
    e['liga_a_puerta'] = T.media_liga(e, 'a_puerta')
    e = e[(e.n_prev >= 3) & (e.r_n_prev >= 3)].dropna(subset=['p_gana']).copy()
    el, ju = e[e.fecha < DESDE], e[e.fecha >= DESDE]
    print('entrena', len(el), 'prueba', len(ju))
    tab = tableros()
    print('fotos de tablero con tiros:', tab.ts.nunique(), 'filas', len(tab))
    casa_de = emparejar(ju[ju.local == 1], tab)
    print('partidos con tablero:', len(casa_de))
    filas = []
    for obj, clave in (('tiros', 'remates'), ('a_puerta', 'remates_on')):
        cols = T.columnas(e)
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=600,
                              learning_rate=0.03, num_leaves=31,
                              min_child_samples=80, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8,
                              verbose=-1, random_state=344)
        c2 = el.fecha.quantile(0.85)
        a, b = el[el.fecha < c2], el[el.fecha >= c2]
        m.fit(a[cols], a[obj])
        k = T.ajustar_k(b[obj].values, np.clip(m.predict(b[cols]), 0.3, None))
        m.fit(el[cols], el[obj])
        lam = np.clip(m.predict(ju[cols]), 0.3, None)
        for (r, l) in zip(ju.itertuples(), lam):
            mid = r.mid
            bd = casa_de.get(mid)
            if bd is None:
                continue
            lado = 'home' if r.local == 1 else 'away'
            for lin, v in _lineas(bd.get('%s_%s' % (clave, lado))).items():
                try:
                    L, cm_, cn = float(lin), float(v['mas']), float(v['menos'])
                except Exception:
                    continue
                pm = (1 / cm_) / (1 / cm_ + 1 / cn)
                pmod = float(T.nb_sf(l, L, k))
                filas.append({'obj': obj, 'mid': mid, 'liga': r.liga,
                              'fecha': r.fecha, 'equipo': r.equipo, 'linea': L,
                              'lam': l, 'real': getattr(r, obj),
                              'y': int(getattr(r, obj) > L), 'p_mod': pmod,
                              'p_casa': pm, 'c_mas': cm_, 'c_menos': cn})
    d = pd.DataFrame(filas)
    d.to_pickle('_v344_precio.pkl')
    res = {}
    for obj, g in d.groupby('obj'):
        y = g.y.values
        r = {'apuestas_posibles': len(g), 'partidos': int(g.mid.nunique()),
             'media_real': round(float(g.real.mean()), 2),
             'media_linea': round(float(g.linea.mean()), 2),
             'casa_promete_mas': round(float(g.p_casa.mean()), 3),
             'real_mas': round(float(y.mean()), 3)}
        for nom, p in (('casa', g.p_casa.values), ('modelo', g.p_mod.values),
                       ('mitad', 0.5 * g.p_casa.values + 0.5 * g.p_mod.values)):
            p = np.clip(p, 1e-4, 1 - 1e-4)
            r['ll_' + nom] = round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)
        # apostar donde el modelo se separa de la casa
        for umbral in (0.05, 0.08, 0.12):
            mas = g.p_mod - g.p_casa >= umbral
            menos = g.p_casa - g.p_mod >= umbral
            gan = np.r_[(g.y[mas] * g.c_mas[mas] - 1).values,
                        ((1 - g.y[menos]) * g.c_menos[menos] - 1).values]
            ac = np.r_[g.y[mas].values, 1 - g.y[menos].values]
            mids = np.r_[g.mid[mas].values, g.mid[menos].values]
            if len(gan) == 0:
                continue
            um, inv = np.unique(mids, return_inverse=True)
            s, n = np.bincount(inv, weights=gan), np.bincount(inv)
            bs = [s[i].sum() / n[i].sum() for i in
                  (rng.integers(0, len(um), len(um)) for _ in range(3000))]
            r['valor_%.2f' % umbral] = {'n': int(len(gan)), 'acierto': round(float(ac.mean()), 3),
                                        'roi': round(float(gan.mean()), 4),
                                        'p5': round(float(np.percentile(bs, 5)), 4)}
        res[obj] = r
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open('_v344_precio.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
