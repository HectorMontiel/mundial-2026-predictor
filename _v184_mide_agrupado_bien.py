#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
La medicion del historico agrupado, hecha BIEN.

POR QUE HAY UNA SEGUNDA VERSION. La primera comparo el margen sobre el ELO de
los dos modelos y dijo que el agrupado mejoraba (+0,0679). No vale:

    actual     n_train    566 · acc 0,5274 · ELO 0,5822 · margen -0,0548
    agrupado   n_train 41.725 · acc 0,5213 · ELO 0,5082 · margen +0,0131

La precision BAJA (0,5274 -> 0,5213) y lo que sube es el margen, porque la
linea base ELO cae de 0,5822 a 0,5082. Y cae por un motivo que no tiene que ver
con el modelo: **cada uno se valida sobre un conjunto distinto**. El agrupado
valida sobre partidos de liga, donde el ELO acierta menos que en Champions —ahi
los desequilibrios son enormes y el ELO se luce—. Comparar margenes calculados
sobre conjuntos distintos no dice nada.

QUE HACE ESTA VERSION. Un corte temporal, los dos modelos entrenados con lo
anterior, y los dos evaluados sobre EL MISMO conjunto: los partidos de CHAMPIONS
posteriores al corte. Ahi si se pueden comparar, y contra el mismo ELO.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

CLAVE = sys.argv[1] if len(sys.argv) > 1 else 'champions'
CORTE = 0.80          # 80 % para entrenar, el resto para evaluar


def dataset(df):
    import feature_engineering as fe
    return fe.construir_dataset_supervisado(df)


def entrena_y_evalua(df_train, meta_eval, X_eval, y_eval):
    """Entrena un ensemble y devuelve (acc, logloss) sobre el conjunto dado."""
    from sklearn.metrics import accuracy_score, log_loss
    from train_tda_model import construir_ensemble
    ds = dataset(df_train)
    X, y = ds['X_df'], ds['y']
    cols = [c for c in X.columns if c in X_eval.columns]
    modelo = construir_ensemble()
    modelo.fit(X[cols].values, y)
    proba = modelo.predict_proba(X_eval[cols].values)
    pred = modelo.predict(X_eval[cols].values)
    return (float(accuracy_score(y_eval, pred)),
            float(log_loss(y_eval, proba, labels=sorted(set(y)))))


def main():
    import historico_agrupado as ha
    import league_engine as le

    solo = le.descargar_liga(CLAVE)
    solo['date'] = pd.to_datetime(solo['date'], errors='coerce')
    solo = solo.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    corte = solo['date'].quantile(CORTE)
    print('%s: %d partidos · corte en %s' % (CLAVE, len(solo), str(corte)[:10]))

    eval_df = solo[solo['date'] > corte].copy()
    print('  evaluacion: %d partidos de %s posteriores al corte'
          % (len(eval_df), CLAVE))
    if len(eval_df) < 60:
        print('  muy pocos partidos para evaluar')
        return 1

    # El conjunto de evaluacion se construye UNA vez y es el mismo para los dos.
    ds_eval = dataset(pd.concat([solo[solo['date'] <= corte].tail(200),
                                 eval_df], ignore_index=True))
    n_eval = len(eval_df)
    X_eval = ds_eval['X_df'].tail(n_eval)
    y_eval = ds_eval['y'][-n_eval:]

    # LINEA BASE ELO sobre ESE conjunto
    fechas = ds_eval['fechas'][-n_eval:] if 'fechas' in ds_eval else None
    elo_col = [c for c in X_eval.columns if 'elo' in c.lower()]
    acc_elo = None
    if elo_col:
        d = X_eval[elo_col[0]].values
        pred_elo = np.where(d > 0.15, 0, np.where(d < -0.15, 2, 1))
        # el orden de clases lo fija el dataset; se prueba el mapeo directo
        from sklearn.metrics import accuracy_score
        acc_elo = float(accuracy_score(y_eval, pred_elo))

    print()
    print('%-12s %8s %10s' % ('modelo', 'acc', 'logloss'))
    a1, l1 = entrena_y_evalua(solo[solo['date'] <= corte], None, X_eval, y_eval)
    print('%-12s %8.4f %10.4f' % ('solo copa', a1, l1))

    agr = ha.construir(CLAVE)
    agr['date'] = pd.to_datetime(agr['date'], errors='coerce')
    agr = agr.dropna(subset=['date'])
    a2, l2 = entrena_y_evalua(agr[agr['date'] <= corte], None, X_eval, y_eval)
    print('%-12s %8.4f %10.4f' % ('agrupado', a2, l2))
    if acc_elo is not None:
        print('%-12s %8.4f %10s' % ('ELO (base)', acc_elo, '-'))

    print()
    print('  acc     %+.4f' % (a2 - a1))
    print('  logloss %+.4f  (menos es mejor)' % (l2 - l1))
    print()
    mejora = (a2 > a1) and (l2 < l1)
    print('VEREDICTO: el agrupado %s sobre el MISMO conjunto de %s'
          % ('MEJORA' if mejora else ('EMPEORA' if (a2 < a1 and l2 > l1)
                                      else 'NO decide (senales cruzadas)'),
             CLAVE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
