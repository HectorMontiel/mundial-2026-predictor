#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — La fuga de las features de fatiga en el modelo WTA desplegado.

Qué se encontró
---------------
`DIFF_DIAS_DESCANSO`, `DIFF_PARTIDOS_14D` y `DIFF_HORAS_7D` entraron en la v35 y
siguen en el vector de producción de WTA (`FEATURES_V992_WTA` = FEATURES[:13] +
IDF). Se calculan a partir de las FECHAS de los partidos anteriores de cada
jugadora.

Desde la v96/v97 el histórico de tenis incorpora el archivo ITF, que hoy es el
82 % de las filas. Y ese archivo guarda **todos los partidos de un torneo con
una sola fecha** (mediana: 1,0 fechas distintas por torneo; el 35,9 % de los
pares jugadora-fecha tienen 2 o más partidos ese día).

Con fecha única, «partidos en los últimos 14 días» deja de medir calendario y
pasa a medir CUÁNTO AVANZÓ EN ESTE MISMO TORNEO. Es decir: el resultado de los
partidos que se están prediciendo. Medido, las tres features SOLAS:

    filas kaggle (fechas reales) → log-loss 0,6936 · acierto 53,7 %
    filas ITF   (fecha única)    → log-loss 0,5412 · acierto 73,6 %

Mismo código, misma feature. La diferencia es la granularidad de la fecha. Eso
es fuga, y está en producción.

Qué mide este script
--------------------
El coste real. Se compara el vector desplegado (14 features) contra el mismo sin
las tres de fatiga (11), y se evalúa POR SEPARADO en las filas contaminadas y en
las limpias. Lo que dice la realidad es la evaluación sobre filas limpias: ahí es
donde se ve si las features aportan algo cuando no pueden hacer trampa.
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import engines.tennis_engine as te

N_PLIEGUES = 6
JUICIO_DESDE = 3
BOOT = 4000
SEMILLA = 101
FATIGA = ('DIFF_DIAS_DESCANSO', 'DIFF_PARTIDOS_14D', 'DIFF_HORAS_7D')
SALIDA = '_v101_fuga_fatiga_wta.json'


def _wf(X, y, bordes):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    p = np.full(len(y), np.nan)
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
        p[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
    return p


def _juzgar(pa, pb, y, msk, etiqueta):
    yy = y[msk]

    def ll(p):
        q = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

    ea, eb = ll(pa), ll(pb)
    d = eb - ea            # positivo = QUITARLAS empeora; negativo = mejora
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    print(f'  {etiqueta:<34} n={int(msk.sum()):>6} · con fatiga {ea.mean():.5f} '
          f'· sin fatiga {eb.mean():.5f} · acierto {((pa[msk]>=.5)==yy).mean():.4f}'
          f' → {((pb[msk]>=.5)==yy).mean():.4f}')
    # Se guardan LAS DOS colas. `d = sin − con`, así que «quitarlas mejora» se
    # concluye cuando el intervalo entero es negativo: mirar sólo el p5 (la cola
    # baja) contestaría la pregunta contraria y daría por bueno cualquier signo.
    return {'n': int(msk.sum()), 'll_con': float(ea.mean()),
            'll_sin': float(eb.mean()),
            'acc_con': float(((pa[msk] >= .5) == yy).mean()),
            'acc_sin': float(((pb[msk] >= .5) == yy).mean()),
            'p5_diferencia': float(np.percentile(bt, 5)),
            'p95_diferencia': float(np.percentile(bt, 95)),
            'quitarlas_mejora': bool(np.percentile(bt, 95) < 0)}


def main():
    salida = {}
    for circuito in ('wta', 'atp'):
        eng = te.TennisEngine(circuito)
        desplegado = list(eng.features)
        sin_fatiga = [f for f in desplegado if f not in FATIGA]
        print(f'\n=== {circuito.upper()} · desplegado {len(desplegado)} → '
              f'sin fatiga {len(sin_fatiga)}')
        if len(desplegado) == len(sin_fatiga):
            print('  este circuito NO lleva features de fatiga: nada que medir')
            salida[circuito] = {'afectado': False, 'features': desplegado}
            continue

        df = eng.cargar_datos_historicos()
        Xa, y, _f, _o, est = te.TennisEngine._dataset(df, desplegado)
        Xb, y2, _f2, _o2, _e2 = te.TennisEngine._dataset(df, sin_fatiga)
        assert len(Xa) == len(Xb) and (y == y2).all()
        Xa, Xb = np.asarray(Xa, float), np.asarray(Xb, float)
        n = len(y)
        fuente = np.array([m[0] for m in est['filas_meta']])
        bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
        pa, pb = _wf(Xa, y, bordes), _wf(Xb, y, bordes)
        tarde = (~np.isnan(pa)) & (np.arange(n) >= bordes[JUICIO_DESDE])

        res = {'features': desplegado, 'afectado': True}
        res['todo'] = _juzgar(pa, pb, y, tarde, 'todas las filas')
        res['itf_contaminado'] = _juzgar(
            pa, pb, y, tarde & (fuente == 'archivo_itf'),
            'sólo ITF (fecha única · sucio)')
        limpio = tarde & np.isin(fuente, ['kaggle', 'espn'])
        res['limpio'] = _juzgar(pa, pb, y, limpio,
                                'sólo fechas reales (LIMPIO)')
        salida[circuito] = res

    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')
    print('\nLectura: la fila «LIMPIO» es la que se parece a producción. Si ahí '
          'quitar las features no empeora, sobran — y en las filas ITF sólo '
          'estaban inflando el backtest.')


if __name__ == '__main__':
    main()
