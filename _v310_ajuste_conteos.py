# -*- coding: utf-8 -*-
"""
v310 — TARJETAS Y REMATES: QUÉ ARREGLO GANA, MEDIDO FUERA DE MUESTRA.

`_v310_conteos.py` dejó dos defectos, sobre ~2.800 partidos de Liga MX,
selecciones y copas UEFA predichos sólo con lo anterior a su fecha:

  · TARJETAS: el modelo (ataque/defensa del rival, ventana 10) pierde contra
    la tasa histórica de la competición en Liga MX, selecciones UEFA,
    amistosos y «otras selecciones». En amistosos se pasa +1,2 tarjetas: en
    un amistoso se pita menos que en una eliminatoria, y el modelo mezcla los
    dos porque para él todo es `selecciones`.
  · REMATES TOTALES: se queda corto ~1,2 en copas UEFA y selecciones.

CANDIDATOS (todos con información previa a la fecha):
    M0  el de producción: λ del modelo, dispersión del modelo
    B   la media de la competición (del TIPO de torneo en selecciones)
    Mw  mezcla λ = w·λ_modelo + (1−w)·λ_base, con w ∈ {0,.25,.5,.75}
    Mk  el modelo reescalado por el sesgo medido en elección (λ·k)
Se elige con el 50 % más antiguo y se juzga en el 30 % final; log-loss de
todas las líneas habituales, bootstrap por partido de la mejora contra M0.
Adoptar: p5 > 0 en los DOS tramos.

Uso: python _v310_ajuste_conteos.py   (lee _v310_conteos.csv)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import rendimiento_equipos as rq
from _v310_conteos import LINEAS, grupo

B = 1000


def _p(lam, L, disp):
    return rq.prob_mas_de(lam, L, disp)


def tipo_torneo(r) -> str:
    """El tipo de torneo que decide cuánto se pita: amistoso u oficial."""
    if r['clave'] != 'selecciones':
        return r['clave']
    return 'sel_amistoso' if 'Amistoso' in str(r['torneo']) else 'sel_oficial'


def logloss_filas(d: pd.DataFrame, lam_col: str) -> pd.Series:
    """Log-loss media por partido sobre las líneas habituales del mercado."""
    out = []
    for r in d.itertuples(index=False):
        lam = getattr(r, lam_col)
        s, n = 0.0, 0
        for L in LINEAS[r.mercado]:
            p = _p(lam, L, r.disp_t)
            if p is None:
                continue
            p = min(max(p, 1e-4), 1 - 1e-4)
            y = int(r.real_t > L)
            s += -(y * np.log(p) + (1 - y) * np.log(1 - p))
            n += 1
        out.append(s / n if n else np.nan)
    return pd.Series(out, index=d.index)


def boot(delta: pd.Series, rng) -> dict:
    v = delta.dropna().values
    if len(v) < 30:
        return {'n': int(len(v))}
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return {'n': int(len(v)), 'mejora': round(float(v.mean()), 5),
            'p5': round(float(np.percentile(bs, 5)), 5)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = pd.read_csv('_v310_conteos.csv', parse_dates=['fecha'])
    d['grupo'] = d.apply(grupo, axis=1)
    d['tipo'] = d.apply(tipo_torneo, axis=1)
    d['real_t'] = d['real_h'] + d['real_a']
    d = d.dropna(subset=['lam_t', 'real_t']).sort_values('fecha')
    # la media del tipo de torneo con lo PREVIO (expanding, desplazada)
    d['base'] = (d.groupby(['mercado', 'tipo'])['real_t']
                 .transform(lambda s: s.shift(1).expanding(20).mean()))
    d = d.dropna(subset=['base'])
    rng = np.random.default_rng(310)
    doc = {}
    for mercado in ('tarjetas', 'remates', 'a_puerta', 'corners'):
        x = d[d['mercado'] == mercado].copy()
        q50, q70 = x['fecha'].quantile(.5), x['fecha'].quantile(.7)
        ent1, jue1 = x[x['fecha'] < q50], x[(x['fecha'] >= q50) & (x['fecha'] < q70)]
        ent2, jue2 = x[x['fecha'] < q70], x[x['fecha'] >= q70]
        x['ll_M0'] = logloss_filas(x, 'lam_t')
        res = {}
        for w in (0.0, 0.25, 0.5, 0.75):
            x['lw'] = w * x['lam_t'] + (1 - w) * x['base']
            x['ll'] = logloss_filas(x, 'lw')
            res['w=%.2f' % w] = {
                'eleccion': boot(x.loc[jue1.index, 'll_M0'] - x.loc[jue1.index, 'll'], rng),
                'juicio': boot(x.loc[jue2.index, 'll_M0'] - x.loc[jue2.index, 'll'], rng)}
        # reescalado por el sesgo, medido con lo previo a cada tramo
        for nom, ent, jue in (('eleccion', ent1, jue1), ('juicio', ent2, jue2)):
            k = float(ent['real_t'].sum() / ent['lam_t'].sum())
            x.loc[jue.index, 'lk'] = x.loc[jue.index, 'lam_t'] * k
            res.setdefault('k', {})[nom] = dict(
                boot(x.loc[jue.index, 'll_M0']
                     - logloss_filas(x.loc[jue.index], 'lk'), rng), k=round(k, 3))
        # y por tipo de torneo, la mezcla elegida por grupo
        doc[mercado] = res
        print(mercado, json.dumps(res, ensure_ascii=False))
    json.dump(doc, open('_v310_ajuste_conteos.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
