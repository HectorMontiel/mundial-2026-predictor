#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-forward Champions v22: ¿cuánta historia FBref conviene añadir?

Variantes sobre el histórico fusionado (API-Football 2022-24 + FBref):
  B) solo_futuro : API 2022-24 + FBref 2025-26/actual (descongela la forma)
  C) completo    : + FBref 2017-2022 (¿ayuda el pasado remoto?)

Baseline v21 (solo API, ventana 2024-25): 53.5 % / 1.007 (ELO 51.6 %).
Regla de oro: adoptar la variante que mantenga/mejore la ventana comparable.
"""
import warnings
warnings.filterwarnings('ignore')
import json
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
from train_tda_model import construir_ensemble, calcular_features_topologicas

df_full = pd.read_csv('historico_champions.csv', parse_dates=['date'])


def temporada(f):
    return f.year if f.month >= 7 else f.year - 1


def evaluar(df, ventanas, etiqueta):
    ds = fe.construir_dataset_supervisado(df)
    X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
    topo = calcular_features_topologicas(ds)
    temps = fechas.map(temporada)
    filas = []
    for val_t in ventanas:
        m_tr = (temps < val_t).values
        m_va = (temps == val_t).values
        if m_va.sum() < 40 or m_tr.sum() < 150:
            continue
        X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
        modelo = construir_ensemble()
        modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
        filas.append({
            'variante': etiqueta, 'temporada_val': f'{val_t}-{val_t+1-2000}',
            'n_train': int(m_tr.sum()), 'n_val': int(m_va.sum()),
            'acc': round(float(accuracy_score(y[m_va], proba.argmax(axis=1))), 4),
            'log_loss': round(float(log_loss(y[m_va], proba, labels=[0, 1, 2])), 4),
            'base_elo': round(float(accuracy_score(
                y[m_va], np.where(X_df[m_va]['DIFF_ELO'].values > 0, 0, 2))), 4),
        })
        print(filas[-1])
    return filas


import sys
resultados = []
if '--solo-d' in sys.argv:
    df_D = df_full[df_full['date'] >= '2020-06-01']
    resultados += evaluar(df_D, [2024, 2025], 'D_desde_2020')
else:
    df_B = df_full[df_full['date'] >= '2022-06-01']
    resultados += evaluar(df_B, [2024, 2025], 'B_solo_futuro')
    resultados += evaluar(df_full, [2023, 2024, 2025], 'C_completo')

import os
previos = []
if os.path.exists('resultados_wf_champions_v22.json'):
    with open('resultados_wf_champions_v22.json', encoding='utf-8') as f:
        previos = [r for r in json.load(f)
                   if r['variante'] not in {x['variante'] for x in resultados}]
print(json.dumps(resultados, indent=2))
with open('resultados_wf_champions_v22.json', 'w', encoding='utf-8') as f:
    json.dump(previos + resultados, f, indent=2)
