#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v102 — El IDF en fútbol y en la NBA: el A/B que faltaba.

El Índice de Dispersión de Forma (v99.1) mide la forma DESCONTANDO la dificultad
del calendario: la media de (resultado observado − lo que el ELO esperaba). Está
validado y desplegado en tenis (p5 +0,00072 ATP, +0,00015 WTA) y rechazado en
MLB. El módulo es genérico desde el primer día, pero nunca se corrió en los dos
deportes que quedaban.

Cómo puntúa el empate
---------------------
En tenis y béisbol no hay empate y el IDF es inmediato. En fútbol hay que
decidirlo, y la decisión no es neutra. Se miden las TRES opciones en vez de
elegir a ojo:

  · `3-1-0 normalizado` — victoria 1, empate 1/3, derrota 0. Premia ganar como
    lo hace la clasificación.
  · `1-0,5-0` — el criterio del ELO, y el que usa `contexto_previo.elo_rodante`.
    Es el coherente con el «esperado» contra el que se resta.
  · `sólo victorias` — victoria 1, lo demás 0. Ignora el empate.

La segunda es la que tiene sentido teórico —el esperado del ELO es una
probabilidad de victoria con empate a medias, así que restar cualquier otra cosa
mezcla escalas—, pero se mide igual: el proyecto no adopta por elegancia.

Protocolo
---------
Igual que en tenis: la base es la probabilidad FUERA DE MUESTRA del modelo
desplegado, en log-odds, y se pregunta si el IDF aporta ENCIMA de ella. Nada de
medir contra una base de juguete. Walk-forward, juicio en pliegues tardíos,
bootstrap pareado y veredicto por p5.
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contexto_previo as cp
import indice_forma as idf_mod
from _v101_ab_contexto_futbol import _logit, _wf, N_PLIEGUES, JUICIO_DESDE

BOOT = 4000
SEMILLA = 102
VENTANAS = (5, 10, 15)
SALIDA = '_v102_ab_idf_futbol_nba.json'

PUNTUACIONES = {
    '3-1-0 normalizado': lambda gl, gv: np.where(gl > gv, 1.0,
                                                 np.where(gl == gv, 1 / 3, 0.0)),
    '1-0,5-0 (ELO)': lambda gl, gv: np.where(gl > gv, 1.0,
                                             np.where(gl == gv, 0.5, 0.0)),
    'sólo victorias': lambda gl, gv: (gl > gv).astype(float),
}


def _juzgar(pa, pb, y, msk, etiqueta):
    yy = y[msk]

    def ll(p):
        q = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

    ea, eb = ll(pa), ll(pb)
    d = ea - eb
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    ver = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
    print(f'    {etiqueta:<34} n={len(d):>6} · {ea.mean():.5f} → {eb.mean():.5f} '
          f'· mejora {d.mean():+.6f} · p5 {p5:+.6f} · {ver}')
    return {'n': int(len(d)), 'll_a': float(ea.mean()), 'll_b': float(eb.mean()),
            'mejora': float(d.mean()), 'p5': p5, 'veredicto': ver}


def idf_futbol(puntuar, ventana: int) -> pd.DataFrame:
    """IDF por partido y por lado, cronológico, para todas las ligas."""
    trozos = []
    for f in sorted(os.listdir('.')):
        if not (f.startswith('historico_') and f.endswith('.csv')):
            continue
        try:
            d = pd.read_csv(f, low_memory=False)
        except Exception:
            continue
        if not {'date', 'home_team', 'away_team', 'home_goals', 'away_goals',
                'MATCH_ID'}.issubset(d.columns):
            continue
        d = d.copy()
        d['_f'] = pd.to_datetime(d['date'], errors='coerce')
        d = d.sort_values('_f', kind='stable')
        gl = pd.to_numeric(d['home_goals'], errors='coerce')
        gv = pd.to_numeric(d['away_goals'], errors='coerce')
        ok = gl.notna() & gv.notna()
        d, gl, gv = d[ok], gl[ok], gv[ok]
        if len(d) < 50:
            continue
        # OJO con los nombres: `itertuples` (que usa `idf_por_participante`)
        # renombra toda columna que empiece por guion bajo a un nombre
        # posicional, así que aquí NO pueden llevarlo.
        d['res_idf'] = puntuar(gl.to_numpy(dtype=float), gv.to_numpy(dtype=float))
        # el ELO rodante da el «esperado»; el IDF es la media de la desviación
        ea, eb, _ = cp.elo_rodante(d, 'home_team', 'away_team', 'res_idf',
                                   ventaja_a=cp.ELO_VENTAJA_LOCAL)
        d['elo_a_idf'], d['elo_b_idf'] = ea, eb
        t = idf_mod.idf_por_participante(d, 'home_team', 'away_team',
                                         'elo_a_idf', 'elo_b_idf', 'res_idf',
                                         ventana=ventana)
        t['MATCH_ID'] = d['MATCH_ID'].to_numpy()
        trozos.append(t[['MATCH_ID', 'DIFF_IDF']])
    todo = pd.concat(trozos, ignore_index=True).drop_duplicates('MATCH_ID')
    return todo.set_index('MATCH_ID')


def bloque_futbol(salida: dict) -> None:
    led = pd.read_csv('pick_ledger.csv')
    print(f'\n{"#" * 72}\n# FÚTBOL — {len(led)} predicciones fuera de muestra')
    for nombre, puntuar in PUNTUACIONES.items():
        for ventana in VENTANAS:
            tabla = idf_futbol(puntuar, ventana)
            d = led.join(tabla, on='match_id', how='inner').dropna(
                subset=['DIFF_IDF'])
            fecha = pd.to_datetime(d['fecha'])
            orden = np.argsort(fecha.to_numpy(), kind='stable')
            d = d.iloc[orden]
            n = len(d)
            bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
            extra = d[['DIFF_IDF']].to_numpy(dtype=float)
            print(f'  {nombre} · ventana {ventana}')
            for etq, col_p, valor in (('gana local', 'p_home', 0),
                                      ('empate', 'p_draw', 1),
                                      ('gana visita', 'p_away', 2)):
                y = (d['resultado'].to_numpy() == valor).astype(float)
                base = _logit(d[col_p].to_numpy(dtype=float)).reshape(-1, 1)
                pa = _wf(base, y, bordes)
                pb = _wf(np.column_stack([base, extra]), y, bordes)
                msk = ~np.isnan(pa) & ~np.isnan(pb) & \
                    (np.arange(n) >= bordes[JUICIO_DESDE])
                salida[f'futbol|{nombre}|v{ventana}|{etq}'] = _juzgar(
                    pa, pb, y, msk, f'  {etq}')


def bloque_nba(salida: dict) -> None:
    ruta = 'historico_nba.csv'
    if not os.path.exists(ruta):
        print('\nNBA: sin historico_nba.csv')
        return
    d = pd.read_csv(ruta)
    print(f'\n{"#" * 72}\n# NBA — {len(d)} partidos · columnas: {list(d.columns)[:10]}')
    cols = {c.lower(): c for c in d.columns}
    ch = cols.get('home_team') or cols.get('home')
    ca = cols.get('away_team') or cols.get('away')
    ph = cols.get('home_points') or cols.get('home_score') or cols.get('home_pts')
    pa_ = cols.get('away_points') or cols.get('away_score') or cols.get('away_pts')
    cf = cols.get('date') or cols.get('fecha')
    if not all([ch, ca, ph, pa_, cf]):
        print('  columnas no reconocidas; no se mide (mejor eso que adivinar)')
        salida['nba'] = {'veredicto': 'NO MEDIDO', 'columnas': list(d.columns)}
        return
    d = d.copy()
    d['_f'] = pd.to_datetime(d[cf], errors='coerce')
    d = d.sort_values('_f', kind='stable').dropna(subset=['_f'])
    gl = pd.to_numeric(d[ph], errors='coerce')
    gv = pd.to_numeric(d[pa_], errors='coerce')
    ok = gl.notna() & gv.notna()
    d, gl, gv = d[ok], gl[ok], gv[ok]
    d['res_idf'] = (gl.to_numpy() > gv.to_numpy()).astype(float)  # sin empates
    y = d['res_idf'].to_numpy(dtype=float)
    n = len(d)
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    ea, eb, _ = cp.elo_rodante(d, ch, ca, 'res_idf',
                               ventaja_a=cp.ELO_VENTAJA_LOCAL)
    d['elo_a_idf'], d['elo_b_idf'] = ea, eb
    # base: el ELO rodante (la NBA no tiene ledger fuera de muestra propio, así
    # que la referencia honesta es el ELO, no una probabilidad de modelo que no
    # existe). Se dice, para que nadie lo lea como si fuera el motor desplegado.
    base = ((ea - eb) / cp.ESCALA_ELO).reshape(-1, 1)
    for ventana in VENTANAS:
        t = idf_mod.idf_por_participante(d, ch, ca, 'elo_a_idf', 'elo_b_idf',
                                         'res_idf', ventana=ventana)
        extra = t[['DIFF_IDF']].to_numpy(dtype=float)
        pa2 = _wf(base, y, bordes)
        pb2 = _wf(np.column_stack([base, extra]), y, bordes)
        msk = ~np.isnan(pa2) & ~np.isnan(pb2) & \
            (np.arange(n) >= bordes[JUICIO_DESDE])
        salida[f'nba|v{ventana}'] = _juzgar(pa2, pb2, y, msk,
                                            f'  ventana {ventana}')


def main():
    salida: dict = {}
    bloque_futbol(salida)
    bloque_nba(salida)
    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
