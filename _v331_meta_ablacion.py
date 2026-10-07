# -*- coding: utf-8 -*-
"""
v331 — ¿LO QUE GANA EL META-MODELO EN GOLES ES DE VERDAD DE LOS EQUIPOS?

`_v331_hipotesis.py` dio que un LightGBM con todo (H10) gana en goles al
control «quitar los de menor probabilidad»: +1,5 pts, p5 +1,3. Puede ser
trampa: si sólo está recalibrando por tipo de apuesta («más de 1,5» frente a
«menos de 3,5»), eso la app ya lo hace con su corrección por mercado.

Así que el control se endurece: un meta con SÓLO probabilidad y tipo de
apuesta. Y se mide qué aporta cada variable (quitar una cada vez). Además:
dos mitades, temporada por temporada, y la curva de calibración del meta.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3311)
VARS = ['vol', 'sesgo', 'n_temp', 'descanso', 'corrector', 'liga_cal',
        'favorito', 'empate']
FRAC = 0.20


def modelo():
    return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03,
                              num_leaves=15, min_child_samples=200,
                              subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, reg_lambda=5.0,
                              verbose=-1, random_state=331)


def quita_peor(s, score, frac=FRAC):
    n = int(len(s) * frac)
    m = pd.Series(False, index=s.index)
    m[score.sort_values(kind='mergesort').index[:n]] = True
    return m


def boot(s, qa, qb, n_iter=1500):
    """p5 y media de (acierto con qa − acierto con qb), por día."""
    g = pd.DataFrame({'f': s.fecha.values, 'v': s.verde.values,
                      'a': (~qa).values, 'b': (~qb).values})
    g['va'], g['vb'] = g.v * g.a, g.v * g.b
    A = g.groupby('f')[['va', 'a', 'vb', 'b']].sum().values
    d = []
    for _ in range(n_iter):
        x = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        d.append(x[0] / x[1] - x[2] / x[3])
    return 100 * np.percentile(d, 5), 100 * np.mean(d)


def entrena_y_puntua(M, J, cols):
    m = modelo().fit(M[cols], M.verde)
    return pd.Series(m.predict_proba(J[cols])[:, 1], index=J.index), m


def main():
    c = pd.read_pickle('_v331_candidatas_hist.pkl')
    s0 = c[c.grupo == 'goles'].copy()
    # la probabilidad de «ambos marcan» del histórico está rota (70-80 %
    # prometido, 52 % real) y la app la calcula distinto desde la v326: fuera
    s0 = s0[~s0.apuesta.str.startswith('Ambos')]
    s0['ap'] = s0.apuesta.astype('category').cat.codes
    dias = np.sort(s0.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    M, J = s0[s0.fecha < corte], s0[s0.fecha >= corte]
    base_cols = ['prob', 'ap']
    full_cols = base_cols + VARS
    sb, _ = entrena_y_puntua(M, J, base_cols)
    sf, mf = entrena_y_puntua(M, J, full_cols)
    qb, qf = quita_peor(J, sb), quita_peor(J, sf)
    qp = quita_peor(J, J.prob)
    out = {}
    print('GOLES — juzgar %d apuestas; se quita el %d %% peor' % (len(J), 100 * FRAC))
    print('   sin quitar nada              %.1f %%' % (100 * J.verde.mean()))
    print('   control 1: menor probabilidad %.1f %%' % (100 * J[~qp].verde.mean()))
    print('   control 2: meta prob+tipo     %.1f %%' % (100 * J[~qb].verde.mean()))
    print('   meta con todo                 %.1f %%' % (100 * J[~qf].verde.mean()))
    p5, med = boot(J, qf, qb)
    print('   meta con todo − control 2: media %+.2f · p5 %+.2f' % (med, p5))
    out['vs_control2'] = {'p5': p5, 'media': med,
                          'todo': 100 * J[~qf].verde.mean(),
                          'control2': 100 * J[~qb].verde.mean(),
                          'control1': 100 * J[~qp].verde.mean()}
    print('   Brier: prob %.4f · meta prob+tipo %.4f · meta todo %.4f'
          % (np.mean((J.verde - J.prob) ** 2), np.mean((J.verde - sb) ** 2),
             np.mean((J.verde - sf) ** 2)))
    # una variable cada vez: cuánto se pierde al quitarla, y sola con prob+tipo
    print('\n   variable      sin ella (pts vs todo)   sola + prob+tipo (pts vs control 2)')
    out['variables'] = {}
    for v in VARS:
        s_sin, _ = entrena_y_puntua(M, J, [x for x in full_cols if x != v])
        s_sola, _ = entrena_y_puntua(M, J, base_cols + [v])
        a = 100 * (J[~quita_peor(J, s_sin)].verde.mean() - J[~qf].verde.mean())
        b = 100 * (J[~quita_peor(J, s_sola)].verde.mean() - J[~qb].verde.mean())
        print('   %-12s %+6.2f                    %+6.2f' % (v, a, b))
        out['variables'][v] = {'sin_ella': a, 'sola': b}
    # mitades y temporadas (el meta se entrena con lo ANTERIOR a cada tramo)
    print('\n   por año (entrenado con todos los años anteriores):')
    out['anios'] = {}
    for anio in range(2021, 2027):
        Mt = s0[s0.fecha.dt.year < anio]
        Jt = s0[s0.fecha.dt.year == anio]
        if len(Jt) < 1000 or len(Mt) < 5000:
            continue
        a_b, _ = entrena_y_puntua(Mt, Jt, base_cols)
        a_f, _ = entrena_y_puntua(Mt, Jt, full_cols)
        rb = 100 * Jt[~quita_peor(Jt, a_b)].verde.mean()
        rf = 100 * Jt[~quita_peor(Jt, a_f)].verde.mean()
        rp = 100 * Jt[~quita_peor(Jt, Jt.prob)].verde.mean()
        print('   %d  n %5d · prob %.1f · prob+tipo %.1f · todo %.1f  (%+.2f)'
              % (anio, len(Jt), rp, rb, rf, rf - rb))
        out['anios'][anio] = {'n': len(Jt), 'prob': rp, 'base': rb, 'todo': rf}
    # calibración del meta en el juicio
    print('\n   calibración del meta (juzgar):')
    for lo, hi in ((0, .65), (.65, .70), (.70, .75), (.75, .80), (.80, 1)):
        m = (sf >= lo) & (sf < hi)
        if m.sum() > 200:
            print('   meta %.2f-%.2f: n %5d · dice %.1f %% · real %.1f %%'
                  % (lo, hi, m.sum(), 100 * sf[m].mean(), 100 * J.verde[m].mean()))
    json.dump(out, open('_v331_meta_ablacion_sin_btts.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
