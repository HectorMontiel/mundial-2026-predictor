#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99.2 — El A/B que de verdad decide: IDF sobre el VECTOR DE PRODUCCIÓN.

La v99.1 midió el IDF contra una base de dos features (ELO global y de
superficie) y salió claramente positivo. Pero el motor desplegado no usa esa
base: usa 9 features en ATP y 13 en WTA, **y una de ellas ya es
`DIFF_FORMA10`**. La pregunta correcta —y más dura— es si el IDF aporta algo
ENCIMA de eso, o si la forma en bruto ya lo contenía.

Se usa el `_dataset` del propio motor, así que lo que se mide es exactamente lo
que se desplegaría. Elección en pliegues tempranos, juicio en los tardíos.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import engines.tennis_engine as te

N_PLIEGUES = 6
JUICIO_DESDE = 3
BOOT = 4000
SEMILLA = 992


def main():
    from sklearn.metrics import log_loss

    salida = {}
    for circuito in ('atp', 'wta'):
        eng = te.TennisEngine(circuito)
        df = eng.cargar_datos_historicos()
        base_cols = list(eng.features)
        con_idf = base_cols + te.FEATURES_IDF
        print(f'=== {circuito.upper()}: vector desplegado {len(base_cols)} '
              f'features · candidato {len(con_idf)}')

        Xa, y, fechas, odds, _est = te._dataset_publico(df, base_cols) \
            if hasattr(te, '_dataset_publico') else te.TennisEngine._dataset(df, base_cols)
        Xb, y2, _f2, _o2, _e2 = te.TennisEngine._dataset(df, con_idf)
        assert len(Xa) == len(Xb) and (y == y2).all(), 'los dos datasets deben ser el mismo'
        n = len(Xa)
        print(f'    {n} partidos utilizables')

        bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]

        def oos(X):
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
            p = np.full(n, np.nan)
            for i in range(N_PLIEGUES):
                ini, fin = bordes[i], bordes[i + 1]
                sc = StandardScaler().fit(X[:ini])
                m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
                p[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
            return p

        pa, pb = oos(np.asarray(Xa)), oos(np.asarray(Xb))
        msk = ~np.isnan(pa) & (np.arange(n) >= bordes[JUICIO_DESDE])
        yy = y[msk]
        res = {}
        for nombre, p in (('A · desplegado', pa[msk]), ('B · + IDF', pb[msk])):
            ll = float(log_loss(yy, np.column_stack([1 - p, p]), labels=[0, 1]))
            acc = float(((p >= 0.5) == yy).mean())
            br = float(np.mean((p - yy) ** 2))
            print(f'    {nombre:<16} log-loss {ll:.5f}  acc {acc:.4f}  Brier {br:.4f}')
            res[nombre] = {'ll': ll, 'acc': acc, 'brier': br}

        # bootstrap PAREADO de la diferencia de log-loss por partido
        ea = -(yy * np.log(np.clip(pa[msk], 1e-9, 1)) +
               (1 - yy) * np.log(np.clip(1 - pa[msk], 1e-9, 1)))
        eb = -(yy * np.log(np.clip(pb[msk], 1e-9, 1)) +
               (1 - yy) * np.log(np.clip(1 - pb[msk], 1e-9, 1)))
        d = ea - eb
        rng = np.random.default_rng(SEMILLA)
        bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
        p5 = float(np.percentile(bt, 5))
        prob = float((bt > 0).mean())
        print(f'    n={len(d)} · mejora {d.mean():+.5f} · p5 {p5:+.5f} · '
              f'P(mejora>0) {prob:.1%}')
        veredicto = ('ADOPTAR' if p5 > 0 and
                     res['B · + IDF']['acc'] >= res['A · desplegado']['acc'] - 0.002
                     else 'RECHAZAR')
        print(f'    VEREDICTO: {veredicto}')
        salida[circuito] = {'features_base': base_cols, 'n': int(len(d)),
                            'mejora_ll': float(d.mean()), 'p5': p5,
                            'prob_positiva': prob, 'metricas': res,
                            'veredicto': veredicto}
        print()

    json.dump(salida, open('_v992_ab_idf_motor_tenis.json', 'w'), indent=1)
    print('-> _v992_ab_idf_motor_tenis.json')


if __name__ == '__main__':
    main()
