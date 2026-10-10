#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v355 — Los cierres de la MLB 2010-2021, enteros (sportsbookreviewsonline).

El usuario: «lo mismo que la NBA para la MLB y la KBO: ganador, más/menos,
hándicap, abridores, bateadores, ponches… analiza patrones en el histórico,
cancha, geografía, local/visita, tabla».

La v78 (`backfill_mlb_odds.py`) sólo guardaba el moneyline y se perdió del
CSV de fotos. Aquí se lee TODO lo que trae cada fichero, una fila por partido:
abridores (con su mano), carreras por entrada, moneyline, run line y total de
cierre con sus cuotas. Formato: dos filas por partido, visitante (V) y local
(H); en los neutrales, N y N (la segunda hace de local).
"""
import sys

import numpy as np
import pandas as pd

import backfill_mlb_odds as b

SALIDA = '_v355_mlb_cierres.csv'


def _dec(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return np.nan
    if x == 0 or np.isnan(x):
        return np.nan
    return 1 + x / 100.0 if x > 0 else 1 + 100.0 / abs(x)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def temporada(anio, url):
    d = b._descargar(anio, url)
    if d is None:
        return []
    d = d.reset_index(drop=True)
    filas = []
    entradas = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th']
    cols = list(d.columns)
    ic = cols.index('Close')
    tiene_rl = len(cols) - ic - 1 >= 6          # 2010 no trae run line
    c_rl, c_rlo = (cols[ic + 1], cols[ic + 2]) if tiene_rl else (None, None)
    c_oo = cols[ic + 3] if tiene_rl else cols[ic + 1]
    c_co, c_coo = (cols[ic + 5], cols[ic + 6]) if tiene_rl else (cols[ic + 3], cols[ic + 4])
    for i in range(0, len(d) - 1, 2):
        v, h = d.iloc[i], d.iloc[i + 1]
        try:
            mmdd = int(v['Date'])
        except (TypeError, ValueError):
            continue
        mes, dia = mmdd // 100, mmdd % 100
        try:
            fecha = pd.Timestamp(anio, mes, dia).strftime('%Y-%m-%d')
        except Exception:
            continue

        def _inn(r):
            return [_num(r[c]) for c in entradas]
        iv, ih = _inn(v), _inn(h)
        # total: el visitante lleva la cuota del «más» y el local la del «menos»
        tot = _num(v[c_co])
        filas.append({
            'temporada': anio, 'fecha': fecha, 'neutral': v['VH'] == 'N',
            'away': str(v['Team']).strip(), 'home': str(h['Team']).strip(),
            'away_sp': str(v['Pitcher']).strip(), 'home_sp': str(h['Pitcher']).strip(),
            'runs_away': _num(v['Final']), 'runs_home': _num(h['Final']),
            'r5_away': np.nansum(iv[:5]), 'r5_home': np.nansum(ih[:5]),
            'r1_away': iv[0], 'r1_home': ih[0],
            'ml_away': _dec(v['Close']), 'ml_home': _dec(h['Close']),
            'ml_away_open': _dec(v['Open']), 'ml_home_open': _dec(h['Open']),
            'rl_away': _num(v[c_rl]) if c_rl else np.nan,
            'rl_away_odd': _dec(v[c_rlo]) if c_rlo else np.nan,
            'rl_home': _num(h[c_rl]) if c_rl else np.nan,
            'rl_home_odd': _dec(h[c_rlo]) if c_rlo else np.nan,
            'total': tot if not np.isnan(tot) else _num(h[c_co]),
            'over_odd': _dec(v[c_coo]), 'under_odd': _dec(h[c_coo]),
            'total_open': _num(v[c_oo]),
        })
    return filas


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    todas = []
    for anio, url in sorted(b.ficheros_disponibles().items()):
        f = temporada(anio, url)
        print(anio, len(f), flush=True)
        todas += f
    t = pd.DataFrame(todas)
    t.to_csv(SALIDA, index=False)
    print('guardado', SALIDA, len(t))
    print(t.describe().T[['count', 'mean']].round(2).to_string())
