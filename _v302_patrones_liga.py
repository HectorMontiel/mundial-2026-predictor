# -*- coding: utf-8 -*-
"""
v302 — PATRONES POR LIGA: ¿el nivel en la tabla de cada equipo le dice al
modelo algo que todavía no sabe?

El usuario:

    «Sigo sin ver que haya análisis de patrones de ligas, como entender que en
     el fútbol femenil Liga MX los equipos top de tabla normalmente golean y
     los de media y baja tabla por lo regular no anotan muchos goles. Cosas así
     pero en todas las ligas... Si es posible crea un modelo de IA que aprenda
     de cada una de las ligas.»

QUÉ SE MIDE
1. EL PATRÓN, liga por liga: goles a favor por partido según el TERCIO de la
   tabla (arriba / medio / abajo) de cada equipo, calculado SÓLO con partidos
   anteriores (puntos por partido en sus 15 últimos de liga, ordenado contra
   los equipos activos de esa liga en los 120 días previos).
2. SI EL MODELO YA LO SABE: el residuo (goles reales - goles esperados del
   modelo, `lam_h`/`lam_a` de `pick_ledger_totales.csv`, fuera de muestra)
   por tercio. Si el modelo ya lo recoge, el residuo es ~0 en todas las
   casillas y el patrón es real pero no aporta.
3. EL MODELO QUE APRENDE DE CADA LIGA: un LightGBM supervisado que recibe la
   predicción del modelo actual más los rasgos de la liga y de la tabla, y
   predice más de 2,5 / ambos marcan / marca el local / marca el visitante.
   Se entrena en el 70 % antiguo y se JUZGA en el 30 % reciente, contra el
   modelo actual, con log-loss y Brier y un bootstrap de la diferencia.

Salida: `_v302_patrones_liga.json`.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict, deque

import numpy as np
import pandas as pd

RNG = np.random.default_rng(3021)
VENTANA_PPG = 15
VENTANA_GOLES = 10
ACTIVO_DIAS = 120
MIN_PARTIDOS = 5


def _historico(liga: str) -> pd.DataFrame:
    ruta = 'historico_%s.csv' % liga
    if not os.path.exists(ruta):
        return pd.DataFrame()
    df = pd.read_csv(ruta, low_memory=False,
                     usecols=lambda c: c in ('date', 'home_team', 'away_team',
                                             'home_goals', 'away_goals',
                                             'MATCH_ID'))
    df = df.dropna(subset=['date', 'home_team', 'away_team', 'home_goals',
                           'away_goals'])
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    return df


def rasgos_de_tabla(df: pd.DataFrame) -> pd.DataFrame:
    """Rasgos PREVIOS al partido de cada equipo. Sin fuga: todo se lee antes
    de sumar el partido actual."""
    pts = defaultdict(lambda: deque(maxlen=VENTANA_PPG))
    gf = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))
    gc = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))
    ultimo = {}
    filas = []
    liga_goles = deque(maxlen=400)
    for r in df.itertuples(index=False):
        h, a, d = r.home_team, r.away_team, r.date
        activos = [t for t, f in ultimo.items()
                   if (d - f).days <= ACTIVO_DIAS and len(pts[t]) >= MIN_PARTIDOS]
        ppg = {t: np.mean(pts[t]) for t in activos}
        orden = sorted(ppg.values())

        def pct(t):
            if t not in ppg or len(orden) < 6:
                return np.nan
            return float(np.searchsorted(orden, ppg[t], side='right')) / len(orden)

        def m(dq):
            return float(np.mean(dq)) if len(dq) >= 3 else np.nan

        filas.append({
            'MATCH_ID': r.MATCH_ID,
            'pct_h': pct(h), 'pct_a': pct(a),
            'ppg_h': ppg.get(h, np.nan), 'ppg_a': ppg.get(a, np.nan),
            'gf_h': m(gf[h]), 'gc_h': m(gc[h]), 'gf_a': m(gf[a]),
            'gc_a': m(gc[a]),
            'liga_goles': float(np.mean(liga_goles)) if len(liga_goles) >= 50
            else np.nan,
        })
        hg, ag = float(r.home_goals), float(r.away_goals)
        pts[h].append(3 if hg > ag else (1 if hg == ag else 0))
        pts[a].append(3 if ag > hg else (1 if hg == ag else 0))
        gf[h].append(hg); gc[h].append(ag)
        gf[a].append(ag); gc[a].append(hg)
        ultimo[h] = ultimo[a] = d
        liga_goles.append(hg + ag)
    return pd.DataFrame(filas)


def tercio(p):
    if p != p:
        return None
    return 'arriba' if p > 2 / 3 else ('abajo' if p <= 1 / 3 else 'medio')


def construir() -> pd.DataFrame:
    led = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    led = led[led['liga'] != 'liga']
    partes = []
    for liga in sorted(led['liga'].unique()):
        h = _historico(liga)
        if h.empty or 'MATCH_ID' not in h.columns:
            continue
        r = rasgos_de_tabla(h)
        r['liga'] = liga
        partes.append(r)
    ras = pd.concat(partes, ignore_index=True)
    df = led.merge(ras, left_on=['liga', 'match_id'],
                   right_on=['liga', 'MATCH_ID'], how='inner')
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    df = df.dropna(subset=['fecha', 'lam_h', 'lam_a']).sort_values('fecha')
    df['t_h'] = df['pct_h'].map(tercio)
    df['t_a'] = df['pct_a'].map(tercio)
    df['marca_h'] = (df['goles_local'] >= 1).astype(int)
    df['marca_v'] = (df['goles_visit'] >= 1).astype(int)
    # la probabilidad de marcar que implica el propio modelo (Poisson)
    df['p_marca_h'] = 1 - np.exp(-df['lam_h'])
    df['p_marca_v'] = 1 - np.exp(-df['lam_a'])
    return df.reset_index(drop=True)


def patrones(df: pd.DataFrame) -> dict:
    """Por liga y tercio: goles reales, esperados por el modelo, y residuo."""
    out = {}
    for liga, g in df.groupby('liga'):
        filas = {}
        for lado, t, gl, lam in (('local', 't_h', 'goles_local', 'lam_h'),
                                 ('visitante', 't_a', 'goles_visit', 'lam_a')):
            for ter in ('arriba', 'medio', 'abajo'):
                s = g[g[t] == ter]
                if len(s) < 40:
                    continue
                filas['%s_%s' % (lado, ter)] = {
                    'n': int(len(s)),
                    'goles': round(float(s[gl].mean()), 3),
                    'modelo': round(float(s[lam].mean()), 3),
                    'residuo': round(float((s[gl] - s[lam]).mean()), 3),
                    'se': round(float((s[gl] - s[lam]).std() / np.sqrt(len(s))), 3),
                    'no_marca': round(float((s[gl] == 0).mean()), 3),
                }
        # el cruce que el usuario describió: arriba contra abajo
        s = g[(g['t_h'] == 'arriba') & (g['t_a'] == 'abajo')]
        if len(s) >= 30:
            filas['arriba_vs_abajo'] = {
                'n': int(len(s)),
                'mas25': round(float(s['over_2.5_real'].mean()), 3),
                'modelo_mas25': round(float(s['p_over_2.5'].mean()), 3)}
        s = g[(g['t_h'] != 'arriba') & (g['t_a'] != 'arriba')]
        if len(s) >= 30:
            filas['sin_ninguno_arriba'] = {
                'n': int(len(s)),
                'mas25': round(float(s['over_2.5_real'].mean()), 3),
                'modelo_mas25': round(float(s['p_over_2.5'].mean()), 3)}
        if filas:
            out[liga] = filas
    return out


def _ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


RASGOS = ['lam_h', 'lam_a', 'pct_h', 'pct_a', 'ppg_h', 'ppg_a', 'gf_h',
          'gc_h', 'gf_a', 'gc_a', 'liga_goles', 'liga_cod']
OBJETIVOS = {'mas25': ('over_2.5_real', 'p_over_2.5'),
             'btts': ('btts_real', 'p_btts'),
             'marca_local': ('marca_h', 'p_marca_h'),
             'marca_visitante': ('marca_v', 'p_marca_v')}
PARAMS = dict(objective='binary', learning_rate=0.03, num_leaves=15,
              min_data_in_leaf=200, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=302)
RONDAS = 400


def aprender(df: pd.DataFrame) -> dict:
    import lightgbm as lgb
    ligas = sorted(df['liga'].unique())
    df = df.copy()
    df['liga_cod'] = df['liga'].map({l: i for i, l in enumerate(ligas)})
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    ele = df[df['fecha'] < corte]
    jui = df[df['fecha'] >= corte]
    res = {'corte': str(corte.date()), 'n_eleccion': int(len(ele)),
           'n_juicio': int(len(jui)), 'objetivos': {}}
    for nombre, (y_col, p_col) in OBJETIVOS.items():
        e = ele.dropna(subset=[y_col, p_col])
        j = jui.dropna(subset=[y_col, p_col])
        # la prediccion del modelo actual entra como rasgo, en logit: el
        # arbol aprende la CORRECCION, no a predecir de cero
        def X(d):
            x = d[RASGOS].copy()
            pp = np.clip(d[p_col].astype(float), 1e-3, 1 - 1e-3)
            x['logit_modelo'] = np.log(pp / (1 - pp))
            return x
        ds = lgb.Dataset(X(e), label=e[y_col].astype(int),
                         categorical_feature=['liga_cod'])
        bst = lgb.train(PARAMS, ds, num_boost_round=RONDAS)
        p_new = bst.predict(X(j))
        y = j[y_col].astype(int).to_numpy()
        p_old = j[p_col].astype(float).to_numpy()
        ll_old, ll_new = _ll(y, p_old), _ll(y, p_new)
        dif = ll_old - ll_new                       # > 0 = mejora
        idx = RNG.integers(0, len(dif), size=(2000, len(dif)))
        bs = dif[idx].mean(axis=1)
        # y liga por liga, en el juicio
        por_liga = {}
        for liga, g in j.assign(_d=dif).groupby('liga'):
            if len(g) >= 80:
                por_liga[liga] = {'n': int(len(g)),
                                  'mejora_ll': round(float(g['_d'].mean()), 4)}
        # LA LINEA BASE JUSTA: calibrar el modelo actual liga por liga (una
        # logistica sobre su logit, ajustada en la eleccion). Es lo que ya
        # hacen los calibradores de produccion; ganarle al modelo CRUDO no
        # demostraria nada que no supieramos.
        from sklearn.linear_model import LogisticRegression
        p_cal = np.array(p_old, dtype=float)
        lg_e = np.log(np.clip(e[p_col].astype(float), 1e-3, 1 - 1e-3) /
                      (1 - np.clip(e[p_col].astype(float), 1e-3, 1 - 1e-3)))
        lg_j = np.log(np.clip(p_old, 1e-3, 1 - 1e-3) /
                      (1 - np.clip(p_old, 1e-3, 1 - 1e-3)))
        glob_lr = LogisticRegression(C=1.0).fit(lg_e.to_numpy().reshape(-1, 1),
                                                e[y_col].astype(int))
        p_cal = glob_lr.predict_proba(lg_j.reshape(-1, 1))[:, 1]
        for liga in j['liga'].unique():
            me = (e['liga'] == liga).to_numpy()
            mj = (j['liga'] == liga).to_numpy()
            ye = e[y_col].astype(int).to_numpy()[me]
            if me.sum() >= 150 and 0 < ye.mean() < 1:
                lr = LogisticRegression(C=1.0).fit(
                    lg_e.to_numpy()[me].reshape(-1, 1), ye)
                p_cal[mj] = lr.predict_proba(lg_j[mj].reshape(-1, 1))[:, 1]
        ll_cal = _ll(y, p_cal)
        dif_c = ll_cal - ll_new
        bs_c = dif_c[idx].mean(axis=1)
        res.setdefault('contra_calibrado', {})[nombre] = {
            'll_calibrado_por_liga': round(float(ll_cal.mean()), 5),
            'll_aprendido': round(float(ll_new.mean()), 5),
            'mejora': round(float(dif_c.mean()), 5),
            'p5': round(float(np.percentile(bs_c, 5)), 5)}
        if nombre == 'mas25' and 'cuota_over25' in j.columns:
            mk = j['cuota_over25'].notna().to_numpy() & j['cuota_under25'].notna().to_numpy()
            if mk.sum() > 500:
                io_ = 1 / j['cuota_over25'].to_numpy()[mk]
                iu_ = 1 / j['cuota_under25'].to_numpy()[mk]
                p_mer = io_ / (io_ + iu_)
                res['contra_mercado'] = {
                    'n': int(mk.sum()),
                    'll_mercado': round(float(_ll(y[mk], p_mer).mean()), 5),
                    'll_aprendido': round(float(ll_new[mk].mean()), 5),
                    'll_modelo': round(float(ll_old[mk].mean()), 5)}
        imp = dict(zip(bst.feature_name(),
                       [int(v) for v in bst.feature_importance('gain')]))
        res['objetivos'][nombre] = {
            'll_modelo': round(float(ll_old.mean()), 5),
            'll_aprendido': round(float(ll_new.mean()), 5),
            'brier_modelo': round(float(((p_old - y) ** 2).mean()), 5),
            'brier_aprendido': round(float(((p_new - y) ** 2).mean()), 5),
            'mejora_ll': round(float(dif.mean()), 5),
            'mejora_p5': round(float(np.percentile(bs, 5)), 5),
            'ligas_mejor': sum(1 for v in por_liga.values()
                               if v['mejora_ll'] > 0),
            'ligas_total': len(por_liga),
            'importancia': dict(sorted(imp.items(), key=lambda kv: -kv[1])),
            'por_liga': por_liga,
        }
    return res


def main() -> int:
    df = construir()
    print('partidos con rasgos: %d en %d ligas' % (len(df), df['liga'].nunique()))
    pat = patrones(df)
    apr = aprender(df)
    with open('_v302_patrones_liga.json', 'w', encoding='utf-8') as f:
        json.dump({'patrones': pat, 'aprendizaje': apr}, f,
                  ensure_ascii=False, indent=1)
    # resumen legible: donde el modelo se equivoca por tercio
    print('\nRESIDUO POR TERCIO (goles reales - esperados), ligas con |r|>2 se:')
    for liga, fl in pat.items():
        for k, v in fl.items():
            if 'residuo' in v and abs(v['residuo']) > 2 * max(v['se'], 1e-6):
                print('  %-22s %-18s n=%4d goles %.2f modelo %.2f residuo %+.3f'
                      % (liga, k, v['n'], v['goles'], v['modelo'], v['residuo']))
    print('\nAPRENDIZAJE POR LIGA (juicio desde %s, n=%d):'
          % (apr['corte'], apr['n_juicio']))
    for k, v in apr['objetivos'].items():
        print('  %-16s ll %.5f -> %.5f  mejora %+.5f (p5 %+.5f)  brier %.5f -> '
              '%.5f  ligas que mejoran %d/%d'
              % (k, v['ll_modelo'], v['ll_aprendido'], v['mejora_ll'],
                 v['mejora_p5'], v['brier_modelo'], v['brier_aprendido'],
                 v['ligas_mejor'], v['ligas_total']))
        print('     rasgos:', list(v['importancia'].items())[:6])
    print('\nCONTRA EL MODELO CALIBRADO POR LIGA (la linea base justa):')
    for k, v in apr.get('contra_calibrado', {}).items():
        print('  %-16s ll calibrado %.5f -> aprendido %.5f  mejora %+.5f (p5 %+.5f)'
              % (k, v['ll_calibrado_por_liga'], v['ll_aprendido'], v['mejora'], v['p5']))
    print('CONTRA EL MERCADO (mas de 2,5):', apr.get('contra_mercado'))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
