#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v227 — el histórico agrupado, medido donde de verdad se le pedía algo.

QUÉ PREGUNTA CONTESTA ÉSTA QUE NO CONTESTABA LA DE LA v184
----------------------------------------------------------
`_v184_mide_agrupado_bien.py` ya arregló un error real —comparar márgenes
calculados sobre conjuntos distintos— y dio un veredicto honesto:

    solo copa      acc 0,5556   logloss 0,9517
    agrupado       acc 0,5611   logloss 0,9869

Cruzado: la precisión sube en UN partido de 180 (ruido puro) y el logloss, que
es la regla de puntuación propia y mira la probabilidad entera en vez del
argmax, empeora. Como decisión global, eso es un NO.

Pero esa medición tiene un punto ciego, y es justo el que hizo nacer el módulo.
Evalúa sobre partidos que el modelo de la copa YA SABE predecir, porque el
conjunto de evaluación se construye desde su propio histórico. Los partidos que
motivaron la v184 —Stuttgart-Viking, Fenerbahce-Roma, Como-Leipzig, que salen
con `prob: None`— no están ahí. No pueden estarlo: salen None precisamente
porque el equipo no tiene filas.

Así que la pregunta global era la equivocada. La buena es más estrecha:

    donde el modelo de la copa NO TIENE MUESTRA de un equipo,
    ¿el agrupado acierta más que la alternativa real, que es no predecir?

CÓMO SE MIDE
------------
Mismo corte temporal y mismos dos modelos que la v184, pero el conjunto de
evaluación se parte en dos usando `meta`, que trae (local, visitante) por fila:

  · CONOCIDOS  los dos equipos llegan al corte con >= MIN_FILAS partidos en el
               histórico de la copa. Aquí manda la v184: si el agrupado
               empeora, empeora, y no se toca.
  · HUECOS     alguno no llega. Aquí el modelo de la copa está adivinando con
               una muestra que no sostiene nada, o directamente no existe en el
               catálogo y el partido sale sin pick.

El listón para los huecos no es «que el agrupado gane al modelo de la copa».
Es más bajo y más honesto: que le gane a NO APOSTAR, que es lo que hay hoy. Se
compara contra dos líneas base tontas —siempre local, y la clase mayoritaria—
porque un modelo que no supera eso no aporta nada aunque su accuracy suene bien.

QUÉ SE HACE CON EL RESULTADO
----------------------------
Nada automático. Esto escribe `_v227_agrupado_huecos.json` y ya. Si los huecos
salen a favor, el enganche que toca es quirúrgico —agrupado SÓLO como respaldo
donde falta muestra, jamás sustituyendo una predicción que ya funciona—, que es
el mismo patrón que `perfil_liga_local` usa para las estadísticas y que el
propio docstring de `historico_agrupado` cita.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

CLAVE = sys.argv[1] if len(sys.argv) > 1 else 'champions'
CORTE = 0.80
# Por debajo de esto, la «historia» de un equipo en la copa es anécdota. Ocho
# partidos es lo que el propio proyecto usó en la v105 para llamar a un equipo
# de la Conference no convergido.
MIN_FILAS = 8
SALIDA = '_v227_agrupado_huecos.json'


def dataset(df):
    import feature_engineering as fe
    return fe.construir_dataset_supervisado(df)


def entrena(df_train, X_eval):
    """Entrena el ensemble y devuelve (pred, proba) sobre el conjunto dado."""
    from train_tda_model import construir_ensemble
    ds = dataset(df_train)
    X, y = ds['X_df'], ds['y']
    cols = [c for c in X.columns if c in X_eval.columns]
    modelo = construir_ensemble()
    modelo.fit(X[cols].values, y)
    return (modelo.predict(X_eval[cols].values),
            modelo.predict_proba(X_eval[cols].values),
            sorted(set(y)))


def marca(pred, proba, y, clases):
    from sklearn.metrics import accuracy_score, log_loss
    if len(y) == 0:
        return {'n': 0, 'acc': None, 'logloss': None}
    try:
        ll = float(log_loss(y, proba, labels=clases))
    except ValueError:
        ll = None
    return {'n': int(len(y)), 'acc': float(accuracy_score(y, pred)),
            'logloss': ll}


def main():
    import historico_agrupado as ha
    import league_engine as le

    solo = le.descargar_liga(CLAVE)
    solo['date'] = pd.to_datetime(solo['date'], errors='coerce')
    solo = (solo.dropna(subset=['date']).sort_values('date')
            .reset_index(drop=True))
    corte = solo['date'].quantile(CORTE)
    pre, eval_df = solo[solo['date'] <= corte], solo[solo['date'] > corte]
    print('%s: %d partidos · corte %s · evaluacion %d'
          % (CLAVE, len(solo), str(corte)[:10], len(eval_df)))
    if len(eval_df) < 60:
        print('muy pocos partidos para evaluar')
        return 1

    # Cuánta muestra tiene cada equipo ANTES del corte. Esto es lo que el
    # modelo de la copa sabe de él el día que le toca predecir.
    filas = pd.concat([pre['home_team'], pre['away_team']]).value_counts()

    ds = dataset(pd.concat([pre.tail(200), eval_df], ignore_index=True))
    n = len(eval_df)
    X_eval = ds['X_df'].tail(n).reset_index(drop=True)
    y_eval = np.asarray(ds['y'][-n:])
    meta = list(ds['meta'])[-n:]
    if len(meta) != n:
        print('AVISO: meta y evaluacion no cuadran (%d vs %d); el constructor '
              'de features ha tirado filas y la alineacion no es fiable'
              % (len(meta), n))
        return 1

    hueco = np.array([min(filas.get(m[0], 0), filas.get(m[1], 0)) < MIN_FILAS
                      for m in meta])
    print('  huecos: %d de %d partidos tienen un equipo con menos de %d filas'
          % (int(hueco.sum()), n, MIN_FILAS))

    p1, pr1, c1 = entrena(pre, X_eval)
    agr = ha.construir(CLAVE)
    agr['date'] = pd.to_datetime(agr['date'], errors='coerce')
    agr = agr.dropna(subset=['date'])
    p2, pr2, c2 = entrena(agr[agr['date'] <= corte], X_eval)

    # Las dos lineas base tontas, sobre los mismos huecos.
    mayoria = int(pd.Series(y_eval[~hueco] if (~hueco).any() else y_eval)
                  .value_counts().idxmax())

    out = {'clave': CLAVE, 'corte': str(corte)[:10], 'n_eval': n,
           'min_filas': MIN_FILAS, 'n_huecos': int(hueco.sum()),
           'grupos': {}}
    for etiqueta, m in (('conocidos', ~hueco), ('huecos', hueco)):
        if not m.any():
            continue
        g = {'solo_copa': marca(p1[m], pr1[m], y_eval[m], c1),
             'agrupado': marca(p2[m], pr2[m], y_eval[m], c2),
             'base_mayoria': marca(np.full(m.sum(), mayoria), None,
                                   y_eval[m], None)}
        out['grupos'][etiqueta] = g
        print()
        print('[%s]  n=%d' % (etiqueta.upper(), int(m.sum())))
        for k in ('solo_copa', 'agrupado', 'base_mayoria'):
            v = g[k]
            print('  %-13s acc %s   logloss %s'
                  % (k,
                     '  n/d' if v['acc'] is None else '%.4f' % v['acc'],
                     '     n/d' if v['logloss'] is None
                     else '%.4f' % v['logloss']))

    h = out['grupos'].get('huecos')
    if h and h['solo_copa']['n'] >= 25:
        d_acc = h['agrupado']['acc'] - h['solo_copa']['acc']
        gana_base = h['agrupado']['acc'] > h['base_mayoria']['acc']
        out['veredicto_huecos'] = (
            'a_favor' if (d_acc > 0 and gana_base) else
            'en_contra' if d_acc < 0 else 'no_decide')
        print()
        print('HUECOS: agrupado %+.4f de acc sobre el modelo de la copa, '
              'y %s a la base tonta -> %s'
              % (d_acc, 'GANA' if gana_base else 'NO gana',
                 out['veredicto_huecos']))
    else:
        out['veredicto_huecos'] = 'muestra_insuficiente'
        print()
        print('HUECOS: muestra insuficiente para decidir (%s partidos)'
              % (h['solo_copa']['n'] if h else 0))

    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
