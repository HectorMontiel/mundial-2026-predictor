# -*- coding: utf-8 -*-
"""
v330 — EL MODELO DE LA NBA CON 19 TEMPORADAS, MEDIDO TEMPORADA A TEMPORADA.

Réplica sin fuga sobre `historico_nba_largo.csv`: cada temporada S de 2010-11
a 2025-26 se predice con un modelo ENTRENADO SÓLO con las anteriores, y cada
partido con el estado de los equipos justo antes de jugarse (`nba_estado`).
Los ajustes se eligen con 2010-11 → 2016-17 y se juzgan en 2017-18 → 2025-26.

Se compara contra el CIERRE de la casa (moneyline sin margen) y contra el
motor de antes (`engines/nba_engine`), y se mide lo que decide la app: la
mezcla con la casa y su acierto por bandas de probabilidad.

Uso: python _v330_nba.py [--entrenar]
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

import nba_estado as ne
import nba_historico as nh

CORTE = 2016          # elige hasta esta temporada incluida; juzga después
ARTEFACTO = 'modelos/nba_v330.json'
ALPHA = 20.0
PESO_MODELO = 0.10    # elegido con 2010-16 (ver `main`), juzgado en 2017-25


class Ridge:
    def __init__(self, alpha):
        self.alpha = alpha

    def ajustar(self, X, y):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        self.b0 = y.mean()
        self.b = np.linalg.solve(Z.T @ Z + self.alpha * np.eye(Z.shape[1]),
                                 Z.T @ (y - self.b0))
        return self

    def predecir(self, X):
        return self.b0 + ((X - self.mu) / self.sd) @ self.b


def americano(ml):
    ml = pd.to_numeric(ml, errors='coerce')
    return np.where(ml > 0, 1 + ml / 100.0, 1 + 100.0 / ml.abs())


def mercado(x: pd.DataFrame) -> pd.Series:
    oh, oa = americano(x.ml_home), americano(x.ml_away)
    ph, pa = 1 / oh, 1 / oa
    return pd.Series(ph / (ph + pa), index=x.index)


def walk_forward(x, temporadas, alpha=20.0, desde=2008):
    jug = x[x.margen.notna()]
    out = []
    for s in temporadas:
        ent = jug[(jug.temporada >= desde) & (jug.temporada < s)]
        jui = jug[jug.temporada == s].copy()
        if jui.empty:
            continue
        mm = Ridge(alpha).ajustar(ent[ne.COLS_MARGEN].values, ent.margen.values)
        mt = Ridge(alpha).ajustar(ent[ne.COLS_TOTAL].values, ent.total.values)
        res = ent.margen.values - mm.predecir(ent[ne.COLS_MARGEN].values)
        rt = ent.total.values - mt.predecir(ent[ne.COLS_TOTAL].values)
        jui['m_pred'] = mm.predecir(jui[ne.COLS_MARGEN].values)
        jui['t_pred'] = mt.predecir(jui[ne.COLS_TOTAL].values)
        jui['sig_m'], jui['sig_t'] = res.std(), rt.std()
        jui['p_home'] = norm.cdf(jui.m_pred / res.std())
        out.append(jui)
    return pd.concat(out)


def metricas(r, col='p_home') -> dict:
    y = (r.margen > 0).astype(float)
    p = r[col].clip(1e-4, 1 - 1e-4)
    return {'n': int(len(r)),
            'log_loss': round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 5),
            'brier': round(float(((p - y) ** 2).mean()), 5),
            'acierto': round(float(((p > .5) == (y == 1)).mean()), 4)}


def bandas(r, col):
    t = r.assign(p=np.maximum(r[col], 1 - r[col]),
                 gana=np.where(r[col] >= .5, r.margen > 0, r.margen < 0),
                 cuota=np.where(r[col] >= .5, americano(r.ml_home), americano(r.ml_away)))
    t = t[t.p >= .65]
    t['tramo'] = np.where(t.temporada <= CORTE, 'elige', 'juzga')
    t['banda'] = pd.cut(t.p, [.65, .7, .75, .8, .85, .9, 1])
    t['pnl'] = np.where(t.gana, t.cuota - 1, -1)
    return t


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = nh.cargar()
    x, _ = ne.dataset(d)
    x['p_mkt'] = mercado(x)
    r = walk_forward(x, range(2010, 2026))
    rm = r[r.p_mkt.notna()].copy()
    print('=== ganador, por tramo ===')
    for nom, f in (('elige 2010-16', rm.temporada <= CORTE),
                   ('juzga 2017-25', rm.temporada > CORTE),
                   ('2024-25', rm.temporada == 2024)):
        print('%-14s modelo %s' % (nom, metricas(rm[f])))
        print('%-14s casa   %s' % ('', metricas(rm[f], 'p_mkt')))
    for w in (0.5, 0.25, 0.1):
        rm['pw'] = w * rm.p_home + (1 - w) * rm.p_mkt
        print('mezcla %.2f  elige %s · juzga %s' % (
            w, metricas(rm[rm.temporada <= CORTE], 'pw')['log_loss'],
            metricas(rm[rm.temporada > CORTE], 'pw')['log_loss']))
    j = r[r.temporada > CORTE]
    print('\nMAE margen modelo %.2f · hándicap casa %.2f' % (
        (j.margen - j.m_pred).abs().mean(), (j.margen - j.spread).abs().mean()))
    print('MAE total  modelo %.2f · total casa %.2f' % (
        (j.total - j.t_pred).abs().mean(), (j.total - j.total_linea).abs().mean()))
    return x, r, rm


def medicion(r, rm) -> dict:
    """Lo que se guarda en el artefacto: la medición, por tramo."""
    rm = rm.copy()
    rm['pw'] = PESO_MODELO * rm.p_home + (1 - PESO_MODELO) * rm.p_mkt
    out = {'peso_modelo': PESO_MODELO, 'corte_elige': CORTE}
    for nom, f in (('elige', rm.temporada <= CORTE), ('juzga', rm.temporada > CORTE)):
        out[nom] = {'modelo': metricas(rm[f]), 'casa': metricas(rm[f], 'p_mkt'),
                    'mezcla': metricas(rm[f], 'pw')}
    t = bandas(rm, 'pw')
    j = t[t.tramo == 'juzga']
    out['meter_juzga'] = {'n': int(len(j)), 'promete': round(float(j.p.mean()), 4),
                          'real': round(float(j.gana.mean()), 4),
                          'roi_cierre': round(float(j.pnl.mean()), 4)}
    return out


def entrenar(x, r, rm) -> dict:
    """El modelo final: todas las temporadas completas, mismos ajustes."""
    jug = x[x.margen.notna() & (x.temporada >= 2008)]
    mm = Ridge(ALPHA).ajustar(jug[ne.COLS_MARGEN].values, jug.margen.values)
    mt = Ridge(ALPHA).ajustar(jug[ne.COLS_TOTAL].values, jug.total.values)
    rmar = jug.margen.values - mm.predecir(jug[ne.COLS_MARGEN].values)
    rtot = jug.total.values - mt.predecir(jug[ne.COLS_TOTAL].values)

    def _c(m, cols):
        return {'cols': cols, 'mu': [float(v) for v in m.mu],
                'sd': [float(v) for v in m.sd], 'b0': float(m.b0),
                'b': [float(v) for v in m.b]}
    art = {'version': 'v330', 'alpha': ALPHA,
           'margen': _c(mm, ne.COLS_MARGEN), 'total': _c(mt, ne.COLS_TOTAL),
           'sigma_margen': float(rmar.std()), 'sigma_total': float(rtot.std()),
           'partidos': int(len(jug)),
           'temporadas': [int(jug.temporada.min()), int(jug.temporada.max())],
           'medicion': medicion(r, rm)}
    with open(ARTEFACTO, 'w', encoding='utf-8') as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    return art


if __name__ == '__main__':
    _x, _r, _rm = main()
    if '--entrenar' in sys.argv:
        a = entrenar(_x, _r, _rm)
        print('\n%s: %d partidos, sigma margen %.2f, total %.2f' % (
            ARTEFACTO, a['partidos'], a['sigma_margen'], a['sigma_total']))
        print(json.dumps(a['medicion'], ensure_ascii=False, indent=1))
