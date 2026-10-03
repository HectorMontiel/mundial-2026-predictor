# -*- coding: utf-8 -*-
"""
v325 — EL MODELO DE LA NFL CON 27 TEMPORADAS, MEDIDO TEMPORADA A TEMPORADA.

Réplica sin fuga sobre `historico_nfl_largo.csv` (nflverse, 1999 → hoy):
cada temporada S de 2010 a 2025 se predice con un modelo ENTRENADO SÓLO con
las temporadas anteriores, y cada partido con el estado de los equipos y de
los quarterbacks justo antes de jugarse (`nfl_estado`).

Se compara contra:
  · el CIERRE de la casa (momio sin margen) — la referencia dura;
  · el modelo de antes (`nfl_calibracion.json`, temporada 2025).

Los ajustes del estado (`nfl_estado`) y la regularización se eligen con
2010-2016 y se juzgan en 2017-2025.

Uso: python _v325_nfl.py
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

import nfl_estado as ne
import nfl_nflverse as nv

COLS_MARGEN, COLS_TOTAL = ne.COLS_MARGEN, ne.COLS_TOTAL
variables = ne.derivar


class Ridge:
    def __init__(self, alpha):
        self.alpha = alpha

    def ajustar(self, X, y):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        A = Z.T @ Z + self.alpha * np.eye(Z.shape[1])
        self.b0 = y.mean()
        self.b = np.linalg.solve(A, Z.T @ (y - self.b0))
        return self

    def predecir(self, X):
        return self.b0 + ((X - self.mu) / self.sd) @ self.b


def americano(ml):
    ml = pd.to_numeric(ml, errors='coerce')
    return np.where(ml > 0, 1 + ml / 100.0, 1 + 100.0 / ml.abs())


def mercado(x: pd.DataFrame) -> pd.Series:
    oh, oa = americano(x.home_moneyline), americano(x.away_moneyline)
    ph, pa = 1 / oh, 1 / oa
    return pd.Series(ph / (ph + pa), index=x.index)


def walk_forward(x: pd.DataFrame, temporadas, alpha_m=20.0, alpha_t=20.0,
                 desde=2002) -> pd.DataFrame:
    jug = x[x.margen.notna()]
    out = []
    for s in temporadas:
        ent = jug[(jug.season >= desde) & (jug.season < s)]
        jui = jug[jug.season == s].copy()
        mm = Ridge(alpha_m).ajustar(ent[COLS_MARGEN].values, ent.margen.values)
        mt = Ridge(alpha_t).ajustar(ent[COLS_TOTAL].values, ent.total.values)
        res = ent.margen.values - mm.predecir(ent[COLS_MARGEN].values)
        sig = res.std()
        jui['m_pred'] = mm.predecir(jui[COLS_MARGEN].values)
        jui['t_pred'] = mt.predecir(jui[COLS_TOTAL].values)
        jui['sigma'] = sig
        jui['p_home'] = norm.cdf(jui.m_pred / sig)
        # la otra forma: los residuos reales (los números clave 3 y 7)
        rs = np.sort(res)
        jui['p_home_emp'] = 1.0 - np.searchsorted(rs, -jui.m_pred.values, side='right') / len(rs)
        out.append(jui)
    return pd.concat(out)


def metricas(r: pd.DataFrame, col='p_home') -> dict:
    r = r[r.margen != 0]
    y = (r.margen > 0).astype(float)
    p = r[col].clip(1e-4, 1 - 1e-4)
    return {'n': int(len(r)),
            'log_loss': round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 5),
            'brier': round(float(((p - y) ** 2).mean()), 5),
            'acierto': round(float(((p > 0.5) == (y == 1)).mean()), 4)}


def entrenar(x: pd.DataFrame, metodo: str, medicion: dict):
    """El modelo de producción: todas las temporadas jugadas desde 2002."""
    import modelo_nfl as mn
    jug = x[x.margen.notna() & (x.season >= 2002)].copy()
    m = mn.NFLModelo.v325().entrenar(jug, alpha=mn.ALPHA_V325)
    m.metodo_margen = metodo
    ruta = m.guardar(mn.ARTEFACTO_V325)
    doc = json.load(open(ruta, encoding='utf-8'))
    doc['medicion'] = medicion
    json.dump(doc, open(ruta, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return ruta


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = nv.cargar()
    ds, _ = ne.dataset(d)
    x = variables(ds)
    x['p_mkt'] = mercado(x)
    r = walk_forward(x, range(2010, 2026))
    rm = r[r.p_mkt.notna()]
    print('=== ganador (moneyline), por tramo ===')
    for nom, f in (('elige 2010-16', rm.season <= 2016), ('juzga 2017-25', rm.season >= 2017),
                   ('2025', rm.season == 2025)):
        print(nom, 'modelo', metricas(rm[f]), '\n   ', ' ' * len(nom), 'casa  ', metricas(rm[f], 'p_mkt'))
        mix = rm[f].assign(p_mix=0.5 * rm[f].p_home + 0.5 * rm[f].p_mkt)
        print('   ', ' ' * len(nom), 'mitad y mitad', metricas(mix, 'p_mix'))
    j = r[r.season >= 2017]
    print('\n=== margen y total (2017-2025) ===')
    print('MAE margen modelo %.2f · hándicap de la casa %.2f' % (
        (j.margen - j.m_pred).abs().mean(), (j.margen - j.spread_line).abs().mean()))
    print('MAE total  modelo %.2f · total de la casa %.2f' % (
        (j.total - j.t_pred).abs().mean(), (j.total - j.total_line).abs().mean()))
    print('correlación margen modelo↔hándicap %.3f' % np.corrcoef(j.m_pred, j.spread_line.fillna(0))[0, 1])
    viejo = json.load(open('nfl_calibracion.json', encoding='utf-8'))
    print('\nmodelo de antes (2025):', viejo['metodo']['empirico'],
          'acierto', viejo['contra_mercado']['acierto_modelo'])
    e = r[r.season <= 2016]
    ll = {k: metricas(e, c)['log_loss'] for k, c in (('normal', 'p_home'), ('empirico', 'p_home_emp'))}
    metodo = min(ll, key=ll.get)
    print('\nmargen → probabilidad (elige 2010-16):', ll, '→', metodo)
    col = 'p_home' if metodo == 'normal' else 'p_home_emp'
    medicion = {
        'metodo_por_tramo': ll,
        'juicio_2017_2025': {'modelo': metricas(rm[rm.season >= 2017], col),
                             'casa': metricas(rm[rm.season >= 2017], 'p_mkt')},
        '2025': {'modelo': metricas(rm[rm.season == 2025], col),
                 'casa': metricas(rm[rm.season == 2025], 'p_mkt'),
                 'v131': viejo['metodo']['empirico']},
    }
    if '--entrenar' in sys.argv:
        print('guardado en', entrenar(x, metodo, medicion))


if __name__ == '__main__':
    main()
