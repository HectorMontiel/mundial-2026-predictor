#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v368 — ¿Un modelo que APRENDA de los resultados cuándo meter «más» y cuándo
«menos» mejora al Método Contexto?

El usuario (11-oct): «debemos tener un algoritmo de ML que aprenda de todo
esto, aprendizaje supervisado o no supervisado, para que aprenda cuándo meter
menos o más estadística».

Datos: `_v362b_lineas.pkl` — 13.359 líneas de las escaleras de Playdoit (goles,
córners, tiros, a puerta, tarjetas; total y por equipo) desde el 28-ago, con la
probabilidad del Método Contexto entrenado SÓLO con lo anterior (`p_mod`), la
de la casa sin margen (`p_casa`), la cuota y lo que pasó (`y` = se cumplió el
«más»). Más el lado (`_v366_lado.pkl`).

El APRENDIZ (supervisado): LightGBM y una logística sobre lo que se sabe antes
del partido — p_mod, p_casa, la distancia línea−λ (en unidades y en
desviaciones), la estadística, total/equipo, local/visita, la línea, la liga —
y aprende si el «más» se cumple. Siempre entrenado con lo ANTERIOR y juzgado
con lo POSTERIOR (ventanas que avanzan por semana), nunca al revés.

Se compara con el método solo y con la casa sola:
  1. ¿Calibra mejor? (log-loss y Brier en lo posterior).
  2. LA DECISIÓN: «más» si p ≥ 70 %, «menos» si p ≤ 30 %. Acierto, cuántas
     apuestas da y ganancia con la cuota de la casa (el «menos» se reconstruye
     de p_casa y la cuota del «más»). Bootstrap por partido, dos mitades.
  3. NO SUPERVISADO: grupos de partidos (k-medias sobre λ de las cinco
     estadísticas) — ¿algún grupo falla o acierta distinto a lo prometido?
Escribe `_v368_aprendiz.json`.
"""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(368)
OBJS = ['goles', 'corners', 'tiros', 'a_puerta', 'tarjetas']


def cargar():
    d = pd.read_pickle('_v362b_lineas.pkl')
    try:
        d = d.join(pd.read_pickle('_v366_lado.pkl'))
    except Exception:
        d['lado_real'] = np.where(d.tipo == 'total', 'total', 'sin')
    # las líneas de otro mercado fuera (como en la app: |método − casa| ≤ 20)
    d = d[(d.p_mod - d.p_casa).abs() <= 0.20].copy()
    d['dist'] = d.linea - d.mu
    d['dist_sd'] = d.dist / np.sqrt(d.mu.clip(lower=0.2))
    # la cuota del «menos», de la casa sin margen y la del «más»
    im_mas = 1.0 / d.c_mas
    im_menos = im_mas * (1 - d.p_casa) / d.p_casa
    d['c_menos'] = 1.0 / im_menos
    for o in OBJS:
        d['o_' + o] = (d.obj == o).astype(int)
    d['es_total'] = (d.tipo == 'total').astype(int)
    d['es_local'] = (d.lado_real == 'local').astype(int)
    d['es_visita'] = (d.lado_real == 'visita').astype(int)
    d['semana'] = d.fecha.dt.to_period('W').astype(str)
    d['liga_c'] = d.liga.astype('category').cat.codes
    return d.sort_values('fecha').reset_index(drop=True)


RASGOS = ['p_mod', 'p_casa', 'dist', 'dist_sd', 'linea', 'mu', 'es_total', 'es_local',
          'es_visita'] + ['o_' + o for o in OBJS]


def _ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def predicciones(d):
    """Por cada semana desde la 3.ª: entrenado con todas las anteriores."""
    import lightgbm as lgb
    from sklearn.linear_model import LogisticRegression
    semanas = sorted(d.semana.unique())
    d['p_lgb'] = np.nan
    d['p_log'] = np.nan
    for i, s in enumerate(semanas):
        if i < 2:
            continue
        tr, te = d[d.semana < s], d[d.semana == s]
        X, Xt = tr[RASGOS + ['liga_c']], te[RASGOS + ['liga_c']]
        m = lgb.LGBMClassifier(n_estimators=250, learning_rate=0.03, num_leaves=15,
                               min_child_samples=40, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, verbose=-1)
        m.fit(X, tr.y)
        d.loc[te.index, 'p_lgb'] = m.predict_proba(Xt)[:, 1]
        # logística sobre logit(p_mod), logit(p_casa) y la estadística
        def _f(q):
            lm = np.log(q.p_mod.clip(.01, .99) / (1 - q.p_mod.clip(.01, .99)))
            lc = np.log(q.p_casa.clip(.01, .99) / (1 - q.p_casa.clip(.01, .99)))
            return np.column_stack([lm, lc, q.dist_sd, q.es_total, q.es_local, q.es_visita]
                                   + [q['o_' + o] for o in OBJS])
        lr = LogisticRegression(C=1.0, max_iter=2000).fit(_f(tr), tr.y)
        d.loc[te.index, 'p_log'] = lr.predict_proba(_f(te))[:, 1]
    return d[d.p_lgb.notna()].copy()


def decision(q, col, umbral=0.70):
    """«más» si p ≥ umbral, «menos» si p ≤ 1 − umbral; una por partido,
    estadística y lado (la más segura)."""
    x = q.copy()
    x['seg'] = np.maximum(x[col], 1 - x[col])
    x = x[x.seg >= umbral]
    x['grupo'] = x.mid.astype(str) + x.obj + x.lado_real.astype(str) + x.tipo
    x = x.sort_values('seg', ascending=False).drop_duplicates('grupo')
    mas = x[col] >= umbral
    x['acierta'] = np.where(mas, x.y, 1 - x.y)
    x['cuota'] = np.where(mas, x.c_mas, x.c_menos)
    x['gan'] = np.where(x.acierta == 1, x.cuota - 1, -1.0)
    x['lado_ap'] = np.where(mas, 'más', 'menos')
    return x


def _res(x):
    if not len(x):
        return {'n': 0}
    um, inv = np.unique(x.mid.values, return_inverse=True)
    s_a, s_g, n = (np.bincount(inv, weights=x.acierta.values), np.bincount(inv, weights=x.gan.values),
                   np.bincount(inv))
    ba, bg = [], []
    for _ in range(2000):
        i = rng.integers(0, len(um), len(um))
        ba.append(s_a[i].sum() / n[i].sum())
        bg.append(s_g[i].sum() / n[i].sum())
    return {'n': int(len(x)), 'acierto': round(float(x.acierta.mean()), 4),
            'acierto_p5': round(float(np.percentile(ba, 5)), 4),
            'cuota': round(float(x.cuota.mean()), 3), 'gan_100': round(100 * float(x.gan.mean()), 1),
            'gan_p5': round(100 * float(np.percentile(bg, 5)), 1),
            'menos_pct': round(float((x.lado_ap == 'menos').mean()), 3)}


def no_supervisado(q):
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    t = q[q.tipo == 'total'].pivot_table(index='mid', columns='obj', values='mu', aggfunc='first')
    t = t.dropna()
    if len(t) < 50:
        return {}
    km = KMeans(n_clusters=5, n_init=10, random_state=368).fit(StandardScaler().fit_transform(t))
    lab = pd.Series(km.labels_, index=t.index)
    x = q[q.mid.isin(t.index)].copy()
    x['grupo_nm'] = x.mid.map(lab)
    out = {}
    for g, z in x.groupby('grupo_nm'):
        out[int(g)] = {'partidos': int(z.mid.nunique()), 'lineas': int(len(z)),
                       'acierto_mas': round(float(z.y.mean()), 4), 'promete': round(float(z.p_mod.mean()), 4),
                       'dif': round(float(z.y.mean() - z.p_mod.mean()), 4),
                       'medias': {o: round(float(t.loc[lab == g, o].mean()), 2) for o in t.columns}}
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar()
    q = predicciones(d)
    corte = q.fecha.quantile(0.5)
    R = {'lineas_juzgadas': int(len(q)), 'desde': str(q.fecha.min().date()), 'hasta': str(q.fecha.max().date())}
    R['calibracion'] = {}
    for col in ('p_mod', 'p_casa', 'p_lgb', 'p_log'):
        R['calibracion'][col] = {t: {'logloss': round(_ll(z.y.values, z[col].values), 4),
                                     'brier': round(float(np.mean((z[col] - z.y) ** 2)), 4)}
                                 for t, z in (('A', q[q.fecha < corte]), ('B', q[q.fecha >= corte]))}
    R['decision'] = {}
    for col in ('p_mod', 'p_casa', 'p_lgb', 'p_log'):
        for u in (0.70, 0.75):
            x = decision(q, col, u)
            R['decision']['%s ≥ %.0f %%' % (col, 100 * u)] = {
                'A': _res(x[x.fecha < corte]), 'B': _res(x[x.fecha >= corte]),
                'por_obj': {o: _res(x[x.obj == o]) for o in OBJS}}
    R['no_supervisado'] = no_supervisado(q)
    json.dump(R, open('_v368_aprendiz.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: R[k] for k in ('lineas_juzgadas', 'desde', 'hasta', 'calibracion')},
                     ensure_ascii=False, indent=1))
    for k, v in R['decision'].items():
        print(k, '| A', v['A'], '| B', v['B'])
    for g, v in R['no_supervisado'].items():
        print('grupo', g, v)


if __name__ == '__main__':
    main()
