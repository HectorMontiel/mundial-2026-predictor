#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v156 — ¿SE PUEDE PREDECIR EL TOTAL DE CÓRNERS DE UN PARTIDO?

El encargo: dejar de predecir la media de la liga (correlación −0,0012) y bajar
el MAE de ~2,70 a menos de 2,00, usando remates y remates a puerta en vez del
xG, y probando XGBoost o un Poisson compuesto.

QUÉ SE PRUEBA, Y CON QUÉ
------------------------
Datos REALES de football-data en las 20 competiciones de formato 'main':
remates (HS/AS), remates a puerta (HST/AST), córners (HC/AC), faltas y
tarjetas. El xG y la posesión de estos ficheros son sintéticos y no entran (lo
comprobó `rendimiento_equipos._columnas_sinteticas` reproduciendo el generador).

Features, todas en un pase cronológico sin fuga:

  · córners a favor y en contra, ventanas de 5 y de 10;
  · córners del BANDO que toca jugar (local en casa, visitante fuera);
  · remates totales y remates A PUERTA por separado, a favor y en contra —que
    es el cambio que se pidió: los remates son la variable física de la que
    salen los córners (un remate bloqueado o desviado ES un córner en buena
    parte de los casos);
  · precisión de remate (a puerta / totales), como proxy de presión;
  · faltas, como proxy de juego trabado;
  · córners del H2H entre esos dos equipos;
  · elo_diff.

Modelos: constante de liga, ridge, Poisson, XGBoost y LightGBM.

EL SUELO IRREDUCIBLE, Y POR QUÉ SE MIDE ANTES QUE NADA
-------------------------------------------------------
Antes de perseguir un MAE de 2,0 hay que saber si existe. El total de córners es
un conteo, y si se distribuye como un Poisson, entonces **incluso un oráculo que
conociera la media exacta de cada partido** cometería un error medio de
aproximadamente `sqrt(2·λ/π)`. Con λ ≈ 10 eso son ~2,5 córners.

O sea que un MAE de 2,0 no sería un modelo mejor: sería un modelo imposible,
salvo que los córners estén MUCHO menos dispersos que un Poisson. El script lo
mide en vez de suponerlo — compara la varianza real con la media real y simula
el error de ese oráculo.
"""
import json
import logging
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import league_engine as le

PRINCIPALES = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1',
               'eredivisie', 'primeira', 'turquia', 'sco_premiership',
               'bel_pro_league']
SECUNDARIAS = ['eng_championship', 'eng_league_one', 'eng_league_two',
               'eng_national', 'esp_hypermotion', 'ita_serie_b', 'fra_ligue2',
               'ger_bundesliga2', 'sco_championship', 'gre_super_league']
LIGAS = PRINCIPALES + SECUNDARIAS

MIN_HIST = 3


def _ma(serie, n):
    if len(serie) < MIN_HIST:
        return None
    return float(np.mean(serie[-n:]))


def construir(df: pd.DataFrame) -> pd.DataFrame:
    """Pase cronológico. Cada fila ve SÓLO lo anterior a su fecha."""
    df = df.sort_values('date').reset_index(drop=True)
    hist, h2h = {}, {}

    def H(eq):
        return hist.setdefault(eq, {
            'ck_f': [], 'ck_c': [], 'ck_casa': [], 'ck_fuera': [],
            'st_f': [], 'st_c': [], 'sh_f': [], 'sh_c': [], 'fal': []})

    filas = []
    for f in df.itertuples(index=False):
        hh, ha = H(f.home_team), H(f.away_team)
        par = tuple(sorted((f.home_team, f.away_team)))
        prev = h2h.get(par, [])

        fila = {'date': f.date,
                'ck_total': float(f.home_corners) + float(f.away_corners),
                'elo_diff': float(getattr(f, 'elo_diff', 0) or 0)}
        for pref, d, bando in (('h', hh, 'ck_casa'), ('a', ha, 'ck_fuera')):
            for n in (5, 10):
                fila['ck_f_%s%d' % (pref, n)] = _ma(d['ck_f'], n)
                fila['ck_c_%s%d' % (pref, n)] = _ma(d['ck_c'], n)
                fila['st_f_%s%d' % (pref, n)] = _ma(d['st_f'], n)
                fila['st_c_%s%d' % (pref, n)] = _ma(d['st_c'], n)
                fila['sh_f_%s%d' % (pref, n)] = _ma(d['sh_f'], n)
                fila['sh_c_%s%d' % (pref, n)] = _ma(d['sh_c'], n)
            fila['ck_bando_%s' % pref] = _ma(d[bando], 5)
            fila['fal_%s' % pref] = _ma(d['fal'], 5)
            # precisión de remate: proxy de presión sostenida
            sf, st = _ma(d['sh_f'], 5), _ma(d['st_f'], 5)
            fila['prec_%s' % pref] = (st / sf) if (sf and st) else None
        fila['h2h_ck'] = float(np.mean(prev[-3:])) if len(prev) >= 2 else None
        filas.append(fila)

        ckh, cka = float(f.home_corners), float(f.away_corners)
        sth = float(getattr(f, 'home_shots_on', 0) or 0)
        sta = float(getattr(f, 'away_shots_on', 0) or 0)
        shh = sth + float(getattr(f, 'home_shots_off', 0) or 0)
        sha = sta + float(getattr(f, 'away_shots_off', 0) or 0)
        fh = float(getattr(f, 'home_yellow', 0) or 0)
        fa = float(getattr(f, 'away_yellow', 0) or 0)
        for d, cf, cc, sf, sc, hf, hc, bando, fl in (
                (hh, ckh, cka, shh, sha, sth, sta, 'ck_casa', fh),
                (ha, cka, ckh, sha, shh, sta, sth, 'ck_fuera', fa)):
            d['ck_f'].append(cf); d['ck_c'].append(cc)
            d['sh_f'].append(sf); d['sh_c'].append(sc)
            d['st_f'].append(hf); d['st_c'].append(hc)
            d[bando].append(cf); d['fal'].append(fl)
        h2h.setdefault(par, []).append(ckh + cka)
    return pd.DataFrame(filas)


def suelo_poisson(y, semilla=7):
    """
    Qué MAE cometería un ORÁCULO que conociera la media exacta de cada partido.

    Si el total de córners fuese Poisson, ese error es irreducible: no lo baja
    ningún modelo, porque es la dispersión del propio fenómeno y no ignorancia
    sobre él. Se simula en vez de usar la fórmula para no depender de la
    aproximación asintótica.

    Se devuelve además la razón varianza/media: por encima de 1 el conteo está
    MÁS disperso que un Poisson (y el suelo es aún más alto), por debajo, menos.
    """
    rng = np.random.default_rng(semilla)
    lam = float(np.mean(y))
    sim = rng.poisson(lam, size=(20, len(y)))
    mae = float(np.mean(np.abs(sim - lam)))
    return {'lambda': round(lam, 3),
            'mae_oraculo_poisson': round(mae, 4),
            'var_media_real': round(float(np.var(y)) / lam, 3),
            'sd_real': round(float(np.std(y)), 3)}


def boot_p5(dif, n_iter=2000, semilla=7):
    rng = np.random.default_rng(semilla)
    d = np.asarray(dif, float)
    m = rng.choice(d, size=(n_iter, len(d)), replace=True).mean(axis=1)
    return round(float(np.percentile(m, 5)), 4)


def mide(clave, temporadas=8):
    t0 = time.time()
    df = le.descargar_liga(clave, temporadas=temporadas)
    df = df.dropna(subset=['home_corners', 'away_corners'])
    if len(df) < 600:
        return {'liga': clave, 'excluida': True, 'motivo': 'n=%d' % len(df)}
    d = construir(df)
    cols = [c for c in d.columns if c not in ('date', 'ck_total')]
    d = d.dropna(subset=cols + ['ck_total'])
    if len(d) < 500:
        return {'liga': clave, 'excluida': True,
                'motivo': 'con features n=%d' % len(d)}

    corte = d['date'].quantile(0.75)
    tr, te = d[d['date'] <= corte], d[d['date'] > corte]
    if len(te) < 120:
        return {'liga': clave, 'excluida': True, 'motivo': 'juicio n=%d' % len(te)}
    Xtr, ytr = tr[cols].to_numpy(float), tr['ck_total'].to_numpy(float)
    Xte, yte = te[cols].to_numpy(float), te['ck_total'].to_numpy(float)

    const = float(ytr.mean())
    e_const = np.abs(yte - const)
    res = {'liga': clave, 'excluida': False,
           'tipo': 'secundaria' if clave in SECUNDARIAS else 'principal',
           'n_train': len(tr), 'n_juicio': len(te), 'n_features': len(cols),
           'mae_constante': round(float(e_const.mean()), 4),
           'suelo': suelo_poisson(yte)}

    from sklearn.linear_model import PoissonRegressor, RidgeCV
    from sklearn.preprocessing import StandardScaler
    esc = StandardScaler().fit(Xtr)
    Str, Ste = esc.transform(Xtr), esc.transform(Xte)

    modelos = {
        'ridge': lambda: RidgeCV(alphas=np.logspace(-2, 3, 20)).fit(Str, ytr),
        'poisson': lambda: PoissonRegressor(alpha=1.0, max_iter=800).fit(Str, ytr),
    }
    preds = {}
    for nombre, fab in modelos.items():
        try:
            m = fab()
            preds[nombre] = m.predict(Ste)
        except Exception as e:
            res[nombre] = {'error': str(e)[:80]}

    try:
        import xgboost as xgb
        m = xgb.XGBRegressor(n_estimators=400, max_depth=3, learning_rate=0.03,
                             subsample=0.8, colsample_bytree=0.8,
                             reg_lambda=2.0, objective='count:poisson',
                             random_state=7, n_jobs=2)
        m.fit(Xtr, ytr)
        preds['xgboost'] = m.predict(Xte)
        res['importancia'] = dict(sorted(
            zip(cols, [round(float(v), 4) for v in m.feature_importances_]),
            key=lambda kv: -kv[1])[:6])
    except Exception as e:
        res['xgboost'] = {'error': str(e)[:80]}

    try:
        import lightgbm as lgb
        m = lgb.LGBMRegressor(n_estimators=400, max_depth=3, learning_rate=0.03,
                              objective='poisson', verbose=-1, random_state=7,
                              n_jobs=2)
        m.fit(Xtr, ytr)
        preds['lightgbm'] = m.predict(Xte)
    except Exception as e:
        res['lightgbm'] = {'error': str(e)[:80]}

    for nombre, p in preds.items():
        err = np.abs(yte - p)
        res[nombre] = {
            'mae': round(float(err.mean()), 4),
            'mejora': round(float((e_const - err).mean()), 4),
            'p5': boot_p5(e_const - err),
            'corr': (round(float(np.corrcoef(p, yte)[0, 1]), 4)
                     if np.std(p) > 1e-9 else 0.0),
        }
    res['segundos'] = round(time.time() - t0, 1)
    return res


def main():
    ligas = sys.argv[1:] or LIGAS
    res = []
    for c in ligas:
        try:
            r = mide(c)
        except Exception as e:
            r = {'liga': c, 'excluida': True,
                 'motivo': '%s: %s' % (type(e).__name__, e)}
        res.append(r)
        if r.get('excluida'):
            print('%-20s EXCL %s' % (r['liga'], r.get('motivo')), flush=True)
        else:
            print('%-20s cte %.3f | ridge %.3f | pois %.3f | xgb %.3f | '
                  'lgbm %.3f | suelo %.3f'
                  % (r['liga'], r['mae_constante'],
                     r.get('ridge', {}).get('mae', float('nan')),
                     r.get('poisson', {}).get('mae', float('nan')),
                     r.get('xgboost', {}).get('mae', float('nan')),
                     r.get('lightgbm', {}).get('mae', float('nan')),
                     r['suelo']['mae_oraculo_poisson']), flush=True)

    ok = [r for r in res if not r.get('excluida')]
    if not ok:
        return
    n = sum(r['n_juicio'] for r in ok)

    def pond(*camino):
        tot = 0.0
        for r in ok:
            v = r
            for k in camino:
                v = v.get(k) if isinstance(v, dict) else None
            if v is None:
                return None
            tot += v * r['n_juicio']
        return round(tot / n, 4)

    resumen = {
        'ligas': len(ok), 'n_juicio': n,
        'mae_constante': pond('mae_constante'),
        'suelo_poisson': pond('suelo', 'mae_oraculo_poisson'),
        'var_media': pond('suelo', 'var_media_real'),
    }
    for m in ('ridge', 'poisson', 'xgboost', 'lightgbm'):
        resumen['mae_' + m] = pond(m, 'mae')
        resumen['corr_' + m] = pond(m, 'corr')
        resumen['ligas_p5_pos_' + m] = sum(
            1 for r in ok if (r.get(m) or {}).get('p5', -1) > 0)
    print('\nRESUMEN ' + json.dumps(resumen, ensure_ascii=False, indent=1),
          flush=True)
    json.dump({'ligas': res, 'resumen': resumen},
              open('_v156_corners_avanzado.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
