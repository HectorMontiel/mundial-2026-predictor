# -*- coding: utf-8 -*-
"""
v326 — LOS PATRONES DE CADA LIGA (goles, ambos marcan, córners) Y SI SIRVEN
PARA APOSTAR MEJOR.

El usuario: «analiza los patrones de cada una de las ligas: en cuáles hay más
ambos marcan, más goles, más córners, y con eso recalibra el modelo. Si hay
ligas donde hay ambos marcan y los dos equipos en su histórico reciente
tienen buena cantidad de goles, podríamos poner ambos marcan: hay una gran
probabilidad de que pase. Y no sólo en ambos marcan: en todo, en fútbol».

LOS DATOS: `pick_ledger_totales.csv`, 80.830 partidos de 61 ligas
(2018-2026) con la probabilidad del modelo calculada FUERA DE MUESTRA y el
resultado; y los `historico_*.csv` para los córners.

LA PRUEBA, la de siempre (`patrones_liga`): se aprende con el 70 % más
antiguo y se juzga en el 30 % reciente. La línea base es lo que la app ya
hace —el modelo calibrado liga por liga—, no el modelo crudo: ganarle al
crudo es fácil y no dice nada. Se adopta un patrón sólo si en el juicio mejora
el log-loss con el percentil 5 del bootstrap por encima de cero.

Las variables del patrón son las que propuso el usuario, calculadas sólo con
partidos ANTERIORES: en cuántos de sus últimos 10 partidos marcó y recibió
cada equipo, su media de goles a favor y en contra, su tasa de «ambos marcan»
y de «más de 2,5», y las mismas tasas de su liga.

Uso: python _v326_patrones.py   (escribe _v326_patrones.json)
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict, deque

import numpy as np
import pandas as pd

SALIDA = '_v326_patrones.json'
N_EQUIPO = 10
N_LIGA = 300
MERCADOS = {'btts': ('btts_real', 'p_btts'),
            'mas15': ('over_1.5_real', 'p_over_1.5'),
            'mas25': ('over_2.5_real', 'p_over_2.5'),
            'mas35': ('over_3.5_real', 'p_over_3.5')}


def cargar() -> pd.DataFrame:
    d = pd.read_csv('pick_ledger_totales.csv')
    d['fecha'] = pd.to_datetime(d['fecha'])
    p = d['match_id'].str.split('_', n=2, expand=True)
    d['home'], d['away'] = d['liga'] + '|' + p[1], d['liga'] + '|' + p[2]
    return d.sort_values(['fecha', 'match_id']).reset_index(drop=True)


def rasgos(d: pd.DataFrame) -> pd.DataFrame:
    """Lo que se sabía de cada equipo y de su liga ANTES de cada partido."""
    eq = defaultdict(lambda: deque(maxlen=N_EQUIPO))
    lg = defaultdict(lambda: deque(maxlen=N_LIGA))
    filas = []
    for r in d[['liga', 'home', 'away', 'goles_local', 'goles_visit']].itertuples(index=False):
        f = {}
        for lado, e in (('h', r.home), ('a', r.away)):
            q = eq[e]
            n = len(q)
            f['%s_n' % lado] = n
            if n:
                gf = np.array([x[0] for x in q]); gc = np.array([x[1] for x in q])
                f['%s_marca' % lado] = (gf > 0).mean()
                f['%s_recibe' % lado] = (gc > 0).mean()
                f['%s_gf' % lado] = gf.mean()
                f['%s_gc' % lado] = gc.mean()
                f['%s_btts' % lado] = ((gf > 0) & (gc > 0)).mean()
                f['%s_o25' % lado] = (gf + gc > 2).mean()
            else:
                for k in ('marca', 'recibe', 'gf', 'gc', 'btts', 'o25'):
                    f['%s_%s' % (lado, k)] = np.nan
        L = lg[r.liga]
        if L:
            a = np.array(L)
            f['liga_btts'] = ((a[:, 0] > 0) & (a[:, 1] > 0)).mean()
            f['liga_o25'] = (a.sum(1) > 2).mean()
            f['liga_goles'] = a.sum(1).mean()
        else:
            f['liga_btts'] = f['liga_o25'] = f['liga_goles'] = np.nan
        filas.append(f)
        gh, ga = r.goles_local, r.goles_visit
        eq[r.home].append((gh, ga))
        eq[r.away].append((ga, gh))
        lg[r.liga].append((gh, ga))
    x = pd.concat([d, pd.DataFrame(filas)], axis=1)
    return x


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def tabla_ligas(x: pd.DataFrame) -> pd.DataFrame:
    """El carácter de cada liga en sus dos últimos años."""
    rec = x[x['fecha'] >= x['fecha'].max() - pd.Timedelta(days=730)]
    t = rec.groupby('liga').agg(partidos=('match_id', 'size'),
                                goles=('goles_total', 'mean'),
                                ambos_marcan=('btts_real', 'mean'),
                                mas_25=('over_2.5_real', 'mean'),
                                mas_15=('over_1.5_real', 'mean'),
                                mas_35=('over_3.5_real', 'mean'),
                                modelo_ambos=('p_btts', 'mean'))
    corners = {}
    for f in glob.glob('historico_*.csv'):
        clave = os.path.basename(f)[len('historico_'):-4]
        try:
            h = pd.read_csv(f, usecols=['date', 'home_corners', 'away_corners'])
        except Exception:
            continue
        h['date'] = pd.to_datetime(h['date'], errors='coerce')
        h = h[h['date'] >= h['date'].max() - pd.Timedelta(days=730)].dropna()
        if len(h) >= 50:
            c = h['home_corners'] + h['away_corners']
            corners[clave] = (round(float(c.mean()), 2), round(float((c > 9.5).mean()), 3))
    t['corners'] = [corners.get(l, (np.nan, np.nan))[0] for l in t.index]
    t['corners_mas_95'] = [corners.get(l, (np.nan, np.nan))[1] for l in t.index]
    return t[t['partidos'] >= 100].sort_values('ambos_marcan', ascending=False)


def medir(x: pd.DataFrame) -> dict:
    """Base calibrada liga por liga contra base + patrones, en el juicio."""
    import lightgbm as lgb
    from sklearn.linear_model import LogisticRegression
    x = x[(x['h_n'] >= 5) & (x['a_n'] >= 5) & x['liga_btts'].notna()].reset_index(drop=True)
    corte = x['fecha'].iloc[int(len(x) * 0.70)]
    ele, jui = x[x['fecha'] < corte], x[x['fecha'] >= corte]
    ligas = sorted(x['liga'].unique())
    dum = lambda s: pd.get_dummies(pd.Categorical(s['liga'], categories=ligas)).values.astype(float)
    pat = ['h_marca', 'h_recibe', 'h_gf', 'h_gc', 'h_btts', 'h_o25',
           'a_marca', 'a_recibe', 'a_gf', 'a_gc', 'a_btts', 'a_o25',
           'liga_btts', 'liga_o25', 'liga_goles']
    rng = np.random.default_rng(326)
    out = {'n': int(len(x)), 'n_juicio': int(len(jui)), 'corte': str(corte.date())}
    for m, (yc, pc) in MERCADOS.items():
        ye, yj = ele[yc].values, jui[yc].values
        # la base: el modelo calibrado liga por liga (logit + intercepto por liga)
        Xe = np.column_stack([logit(ele[pc].values), dum(ele)])
        Xj = np.column_stack([logit(jui[pc].values), dum(jui)])
        base = LogisticRegression(C=10.0, max_iter=2000).fit(Xe, ye)
        pb = base.predict_proba(Xj)[:, 1]
        # los patrones: lo mismo + las variables del usuario (LightGBM, como
        # `patrones_liga`)
        Fe = np.column_stack([logit(ele[pc].values), ele[pat].values])
        Fj = np.column_stack([logit(jui[pc].values), jui[pat].values])
        cod = {l: i for i, l in enumerate(ligas)}
        Fe = np.column_stack([Fe, ele['liga'].map(cod).values])
        Fj = np.column_stack([Fj, jui['liga'].map(cod).values])
        gbm = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15,
                                 min_child_samples=200, subsample=0.8, subsample_freq=1,
                                 colsample_bytree=0.8, reg_lambda=5.0, verbose=-1)
        gbm.fit(Fe, ye, categorical_feature=[Fe.shape[1] - 1])
        pp = gbm.predict_proba(Fj)[:, 1]
        lb, lp = ll(yj, pb), ll(yj, pp)
        dif = lb - lp
        boots = [dif[rng.integers(0, len(dif), len(dif))].mean() for _ in range(2000)]
        out[m] = {'ll_base_calibrada': round(float(lb.mean()), 5),
                  'll_patrones': round(float(lp.mean()), 5),
                  'mejora': round(float(dif.mean()), 5),
                  'p5': round(float(np.percentile(boots, 5)), 5)}
        # y lo que importa para apostar: donde cada uno dice 70 % o más
        for nom, p in (('base', pb), ('patrones', pp)):
            for lado, pl, y in (('si', p, yj), ('no', 1 - p, 1 - yj)):
                s = pl >= 0.70
                out[m]['%s_%s_70' % (nom, lado)] = {
                    'n': int(s.sum()),
                    'prometido': round(float(pl[s].mean()), 3) if s.any() else None,
                    'real': round(float(y[s].mean()), 3) if s.any() else None}
    return out


def regla_usuario(x: pd.DataFrame) -> dict:
    """La regla tal cual la dijo el usuario: liga de ambos marcan y los dos
    equipos con goles recientes. ¿Cuánto acierta ambos marcan ahí, y cuánto
    decía ya el modelo?"""
    x = x[(x['h_n'] >= 8) & (x['a_n'] >= 8) & x['liga_btts'].notna()]
    corte = x['fecha'].iloc[int(len(x) * 0.70)]
    out = {}
    for nom, f in (
            ('liga ≥55 % y los dos marcan en ≥8 de 10',
             (x.liga_btts >= .55) & (x.h_marca >= .8) & (x.a_marca >= .8)),
            ('... y además los dos reciben en ≥7 de 10',
             (x.liga_btts >= .55) & (x.h_marca >= .8) & (x.a_marca >= .8)
             & (x.h_recibe >= .7) & (x.a_recibe >= .7)),
            ('los dos marcan en ≥9 de 10',
             (x.h_marca >= .9) & (x.a_marca >= .9)),
            ('los dos con ≥1,8 goles a favor de media',
             (x.h_gf >= 1.8) & (x.a_gf >= 1.8))):
        s = x[f]
        out[nom] = {t: {'n': int(len(z)), 'ambos_marcan_real': round(float(z.btts_real.mean()), 3),
                        'modelo_decia': round(float(z.p_btts.mean()), 3)}
                    for t, z in (('elige', s[s.fecha < corte]), ('juzga', s[s.fecha >= corte]))}
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    x = rasgos(cargar())
    t = tabla_ligas(x)
    pd.set_option('display.width', 200)
    print(t.round(3).to_string())
    r = regla_usuario(x)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    m = medir(x)
    print(json.dumps(m, ensure_ascii=False, indent=1))
    json.dump({'ligas': t.round(4).reset_index().to_dict('records'),
               'regla_usuario': r, 'medicion': m},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=float)


if __name__ == '__main__':
    main()
