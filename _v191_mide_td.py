#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v191 - ¿SE PUEDEN PREDECIR LOS TOUCHDOWNS DESDE EL TOTAL DEL MODELO?

La correlacion entre touchdowns y puntos es 0,934, asi que la tentacion es
derivar los TD del total y darlo por bueno. Ajustar TD sobre los puntos REALES
da una calibracion casi perfecta —error por debajo de 1,5 puntos de
probabilidad en todas las lineas— y **esa medicion no vale**: en produccion no
se conocen los puntos, se conoce `total_esperado`, que trae su propio error de
mas o menos 13 puntos.

Es el mismo error que produjo aquel ROI del +76 % en tarjetas: comparar contra
algo que no se sabra a la hora de apostar.

Aqui se mide como toca: se entrena el modelo con la primera parte del
calendario, se predice la segunda SIN haberla visto, y los TD se derivan de esa
prediccion. La sigma tiene que recoger las dos fuentes de error.
"""
import io
import sys
from math import erf, sqrt

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

LINEAS = (3.5, 4.5, 5.5, 6.5, 7.5)


def p_mas(mu, linea, s):
    return 1.0 - 0.5 * (1 + erf((linea - mu) / (s * sqrt(2))))


def main():
    import numpy as np
    import pandas as pd
    import modelo_nfl as mn

    d = pd.read_csv('historico_nfl.csv', low_memory=False)
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['fecha']).sort_values('fecha').reset_index(drop=True)

    ds = mn.construir_dataset(d)
    ds = ds[ds['tipo'] == 'regular'].reset_index(drop=True)
    ds = ds[ds['home_td'].notna()] if 'home_td' in ds.columns else ds
    print('dataset de temporada regular:', len(ds))

    # los TD reales, casados por event_id
    tds = d.set_index('event_id')[['home_td', 'away_td']]
    ds = ds.join(tds, on='event_id') if 'event_id' in ds.columns else ds
    if 'home_td' not in ds.columns:
        print('NO SE PUDO CASAR: el dataset no trae event_id')
        return 1
    ds = ds[ds['home_td'].notna()].reset_index(drop=True)
    ds['td'] = ds['home_td'] + ds['away_td']
    print('con touchdowns:', len(ds))

    corte = int(len(ds) * 0.70)
    tr, te = ds.iloc[:corte], ds.iloc[corte:]
    print('entrena %d / valida %d' % (len(tr), len(te)))

    m = mn.NFLModelo().entrenar(tr)
    Xt = te[mn.COLS_TOTAL].values
    total_pred = m.m_total.predecir(Xt)

    # la recta TD<-puntos se ajusta SOLO con el tramo de entrenamiento
    A = np.polyfit(tr['total'].values, tr['td'].values, 1)
    res_lin = tr['td'].values - np.polyval(A, tr['total'].values)
    s_lin = float(np.std(res_lin))

    td_pred = np.polyval(A, total_pred)
    real = te['td'].values

    # la sigma buena junta los dos errores: el de la recta y el del modelo
    s_total = float(m.sigma_total)
    s_prop = sqrt((A[0] * s_total) ** 2 + s_lin ** 2)
    # y la empirica, que es la que manda si discrepan
    s_emp = float(np.std(real - td_pred))

    print()
    print('recta:  TD = %.4f * puntos %+.3f' % (A[0], A[1]))
    print('sigma de la recta sola      : %.3f' % s_lin)
    print('sigma del total del modelo  : %.2f puntos -> %.3f TD'
          % (s_total, abs(A[0]) * s_total))
    print('sigma propagada (teorica)   : %.3f' % s_prop)
    print('sigma EMPIRICA fuera de mues: %.3f' % s_emp)
    print()
    print('MAE fuera de muestra: %.3f  (media constante: %.3f)'
          % (np.abs(real - td_pred).mean(),
             np.abs(real - tr['td'].mean()).mean()))
    print()
    for etq, s in (('propagada', s_prop), ('empirica', s_emp)):
        print('CALIBRACION con sigma %s (%.3f):' % (etq, s))
        peor = 0.0
        for L in LINEAS:
            p = np.array([p_mas(m_, L, s) for m_ in td_pred])
            r = float((real > L).mean())
            dif = float(p.mean()) - r
            peor = max(peor, abs(dif))
            print('   mas de %.1f  predicha %.3f   real %.3f   dif %+0.3f'
                  % (L, float(p.mean()), r, dif))
        print('   peor desvio: %.3f' % peor)
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
