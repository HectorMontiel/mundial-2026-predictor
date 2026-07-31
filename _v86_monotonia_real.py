#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — La auditoría de monotonía, repetida sobre PARTIDOS REALES.

Por qué se repite
-----------------
`_v85_auditoria_monotonia.py` midió la correlación ELO↔P(local) sobre TODOS los
emparejamientos posibles de los 14 mejores equipos de cada liga, usando el
estado ACTUAL de cada equipo. Eso son partidos que nunca se jugaron, con el
modelo extrapolando fuera de la nube de datos que vio al entrenar.

Sobre el ledger real (47.948 partidos de fútbol, predicciones fuera de muestra
con walk-forward) la correlación agregada sale **+0,7378**, muy lejos del
desastre que sugería la auditoría sintética. Antes de "arreglar" 32 modelos hay
que saber cuál de las dos mediciones describe lo que ve el usuario.

Esto compara las dos, liga por liga:
  · rho sintético  = el de v85 (emparejamientos inventados, estado de hoy)
  · rho real       = sobre las predicciones del ledger (partidos que existieron)

Y comprueba la propiedad que de verdad importa para la ficha: dentro de cada
liga, ¿los partidos con más ELO a favor del local reciben más P(local)?
"""
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

MIN_FILAS = 100


def main():
    from scipy.stats import spearmanr

    led = pd.read_csv('pick_ledger_total.csv')
    elo = pd.read_csv('elo_por_partido.csv')
    d = (led[led['deporte'] == 'Fútbol']
         .merge(elo, on=['liga', 'match_id'], how='inner'))
    print(f'{len(d)} partidos de fútbol con ELO y predicción fuera de muestra\n')

    filas = []
    for liga, g in d.groupby('liga'):
        if len(g) < MIN_FILAS:
            continue
        rho, p = spearmanr(g['diff_elo'], g['p_home'])
        # ¿y el ELO predice el resultado real en esa liga?
        rho_y, _ = spearmanr(g['diff_elo'], (g['resultado'] == 0).astype(int))
        # rango de P(local) que produce el modelo
        rango = float(g['p_home'].max() - g['p_home'].min())
        filas.append({'liga': liga, 'n': len(g),
                      'rho_modelo_elo': float(rho), 'p_valor': float(p),
                      'rho_elo_resultado': float(rho_y),
                      'rango_p_home': rango,
                      'p_home_medio': float(g['p_home'].mean())})

    r = pd.DataFrame(filas).sort_values('rho_modelo_elo')
    print('=' * 92)
    print(f'{"liga":24s} {"n":>6} {"rho(modelo,ELO)":>16} '
          f'{"rho(ELO,resultado)":>19} {"rango P":>9}')
    print('=' * 92)
    for _, x in r.iterrows():
        marca = '  <-- INVERTIDA' if x['rho_modelo_elo'] < 0 else (
            '  <-- floja' if x['rho_modelo_elo'] < 0.30 else '')
        print(f'{x["liga"]:24s} {int(x["n"]):6d} {x["rho_modelo_elo"]:+16.4f} '
              f'{x["rho_elo_resultado"]:+19.4f} {x["rango_p_home"]:9.3f}'
              f'{marca}')
    print('=' * 92)

    neg = r[r['rho_modelo_elo'] < 0]
    flojas = r[(r['rho_modelo_elo'] >= 0) & (r['rho_modelo_elo'] < 0.30)]
    sanas = r[r['rho_modelo_elo'] >= 0.30]
    print(f'\n{len(r)} ligas con muestra suficiente (>= {MIN_FILAS} partidos)')
    print(f'  invertidas (rho < 0)      : {len(neg)}')
    print(f'  flojas (0 <= rho < 0,30)  : {len(flojas)}')
    print(f'  sanas (rho >= 0,30)       : {len(sanas)}')
    print(f'  mediana de rho            : {r["rho_modelo_elo"].median():+.4f}')

    # comparación con la auditoría sintética de v85
    print('\n' + '-' * 92)
    print('COMPARACIÓN CON LA AUDITORÍA SINTÉTICA DE v85')
    print('-' * 92)
    sinteticas = {'china': -0.288, 'sudamericana': -0.283, 'ita_serie_b': -0.206,
                  'eng_league_two': -0.171, 'eng_national': -0.011,
                  'mls': -0.030, 'laliga': 0.070, 'argentina': 0.076,
                  'liga_mx': 0.344}
    print(f'{"liga":24s} {"rho sintético (v85)":>20} {"rho real (v86)":>16} '
          f'{"n real":>8}')
    for liga, rs in sorted(sinteticas.items(), key=lambda kv: kv[1]):
        fila = r[r['liga'] == liga]
        if fila.empty:
            print(f'{liga:24s} {rs:+20.3f} {"(sin muestra)":>16}')
            continue
        rr = float(fila['rho_modelo_elo'].iloc[0])
        nn = int(fila['n'].iloc[0])
        print(f'{liga:24s} {rs:+20.3f} {rr:+16.4f} {nn:8d}')

    r.to_csv('_v86_monotonia_real.csv', index=False)
    json.dump({'n_ligas': len(r), 'invertidas': len(neg), 'flojas': len(flojas),
               'sanas': len(sanas),
               'mediana_rho': float(r['rho_modelo_elo'].median())},
              open('_v86_monotonia_real.json', 'w', encoding='utf-8'),
              indent=1, default=float)

    print('\nGuardado en _v86_monotonia_real.csv')


if __name__ == '__main__':
    main()
