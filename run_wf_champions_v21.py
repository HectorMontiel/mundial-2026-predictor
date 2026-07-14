#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-forward por temporadas de la Champions (v21, spec §4.3).

Ventanas naturales: train 2022-23 → val 2023-24; train 22-24 → val 2024-25.
Se compara contra la línea base ELO ('siempre el favorito').
"""
import warnings
warnings.filterwarnings('ignore')
import json
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
from train_tda_model import construir_ensemble, calcular_features_topologicas

df = pd.read_csv('historico_champions.csv', parse_dates=['date'])
ds = fe.construir_dataset_supervisado(df)
X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
topo = calcular_features_topologicas(ds)
print(f"partidos utilizables: {len(X_df)}")

# temporadas: julio a junio
def temporada(f):
    return f.year if f.month >= 7 else f.year - 1

temps = fechas.map(temporada)
filas = []
for val_t in (2023, 2024):
    m_tr = (temps < val_t).values
    m_va = (temps == val_t).values
    if m_va.sum() < 40 or m_tr.sum() < 150:
        print(f"ventana {val_t}: insuficiente (tr={m_tr.sum()}, va={m_va.sum()})")
        continue
    X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
    modelo = construir_ensemble()
    modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
    proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
    acc = accuracy_score(y[m_va], proba.argmax(axis=1))
    ll = log_loss(y[m_va], proba, labels=[0, 1, 2])
    base = accuracy_score(y[m_va], np.where(X_df[m_va]['DIFF_ELO'].values > 0, 0, 2))
    filas.append({'temporada_val': f"{val_t}-{val_t+1-2000}", 'n': int(m_va.sum()),
                  'acc': round(float(acc), 4), 'log_loss': round(float(ll), 4),
                  'base_elo': round(float(base), 4)})
    print(filas[-1])

res = {'ventanas': filas,
       'acc_media': round(float(np.mean([f['acc'] for f in filas])), 4),
       'll_medio': round(float(np.mean([f['log_loss'] for f in filas])), 4),
       'base_media': round(float(np.mean([f['base_elo'] for f in filas])), 4)}
print(json.dumps(res, indent=2))
with open('resultados_wf_champions_v21.json', 'w', encoding='utf-8') as f:
    json.dump(res, f, indent=2)
