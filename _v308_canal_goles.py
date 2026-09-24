# -*- coding: utf-8 -*-
"""
v308 — ¿EL CANAL DE GOLES DE LA CAPA 1 FUNCIONA? MEDIDO, NO SUPUESTO.

La Capa 1 enseñaba «Sin validar todavía» en las apuestas de goles por
diferencia de precio con Pinnacle: el método es el del ganador (validado),
pero el mercado de goles no tenía medición propia y «estaba acumulando». El
usuario: «todo debe estar bien calibrado, no quiero meter una apuesta que me
dé mal».

No hace falta esperar a acumular: football-data guarda, por partido, la cuota
de cierre de Pinnacle y la MEDIA de cierre del mercado para más/menos de 2.5.
Se mide exactamente como se validó el ganador (`league_engine`: media de
cierre `AvgC*` contra Pinnacle de cierre `PC*`):

    q   = probabilidad sin margen de Pinnacle (normalización multiplicativa)
    EV  = q · cuota_media − 1
    se apuesta si EV > 0,005, q ≥ 0,30 y cuota ≥ 1,15 (la regla del barrido)

Dos tramos por fecha (70 % elección / 30 % juicio) y bootstrap de 2.000
remuestreos del ROI; la puerta es p5 > 0 en los DOS. Se mide también la
calibración de q (lo que dice contra lo que pasa), por bandas.

Uso: python _v308_canal_goles.py
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np
import pandas as pd
import requests

DIVS = ['E0', 'E1', 'E2', 'E3', 'EC', 'SC0', 'SC1', 'SC2', 'SC3', 'D1', 'D2',
        'I1', 'I2', 'SP1', 'SP2', 'F1', 'F2', 'N1', 'B1', 'P1', 'T1', 'G1']
TEMPS = ['1920', '2021', '2122', '2223', '2324', '2425', '2526']
CACHE = '_v308_fd'
SALIDA = '_v308_canal_goles.json'
EV_MIN, Q_MIN, CUOTA_MIN = 0.005, 0.30, 1.15
B = 2000


def cargar() -> pd.DataFrame:
    os.makedirs(CACHE, exist_ok=True)
    trozos = []
    for t in TEMPS:
        for d in DIVS:
            ruta = os.path.join(CACHE, '%s_%s.csv' % (d, t))
            if not os.path.exists(ruta):
                r = requests.get('https://football-data.co.uk/mmz4281/%s/%s.csv'
                                 % (t, d), timeout=60,
                                 headers={'User-Agent': 'Mozilla/5.0'})
                if r.status_code != 200:
                    continue
                with open(ruta, 'wb') as f:
                    f.write(r.content)
            try:
                x = pd.read_csv(ruta, encoding='latin-1', on_bad_lines='skip')
            except Exception:
                continue
            x['div'] = d
            x['temp'] = t
            trozos.append(x)
    df = pd.concat(trozos, ignore_index=True)
    df['fecha'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    return df


def apuestas(df: pd.DataFrame, pin=('PC>2.5', 'PC<2.5'),
             blanda=('AvgC>2.5', 'AvgC<2.5')) -> pd.DataFrame:
    need = list(pin) + list(blanda) + ['FTHG', 'FTAG', 'fecha']
    d = df.dropna(subset=[c for c in need if c in df.columns]).copy()
    for c in list(pin) + list(blanda):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=list(pin) + list(blanda))
    inv_o, inv_u = 1 / d[pin[0]], 1 / d[pin[1]]
    s = inv_o + inv_u
    q_o, q_u = inv_o / s, inv_u / s
    goles = d['FTHG'] + d['FTAG']
    filas = []
    for lado, q, cu, gana in (('over', q_o, d[blanda[0]], goles > 2.5),
                              ('under', q_u, d[blanda[1]], goles < 2.5)):
        ev = q * cu - 1
        ok = (ev > EV_MIN) & (q >= Q_MIN) & (cu >= CUOTA_MIN)
        x = pd.DataFrame({'fecha': d['fecha'], 'div': d['div'], 'lado': lado,
                          'q': q, 'cuota': cu, 'ev': ev,
                          'gana': gana.astype(int)})[ok]
        filas.append(x)
    a = pd.concat(filas).sort_values('fecha').reset_index(drop=True)
    a['ganancia'] = np.where(a['gana'] == 1, a['cuota'] - 1, -1.0)
    return a


def roi_p5(g: np.ndarray, rng) -> tuple:
    if len(g) == 0:
        return None, None
    bs = rng.choice(g, size=(B, len(g)), replace=True).mean(axis=1)
    return float(g.mean()), float(np.percentile(bs, 5))


def tramos(a: pd.DataFrame) -> dict:
    rng = np.random.default_rng(308)
    corte = a['fecha'].quantile(0.70)
    fuera = {}
    for nombre, x in (('eleccion', a[a['fecha'] <= corte]),
                      ('juicio', a[a['fecha'] > corte])):
        roi, p5 = roi_p5(x['ganancia'].to_numpy(), rng)
        fuera[nombre] = {'n': int(len(x)), 'acierto': round(float(x['gana'].mean()), 4)
                         if len(x) else None,
                         'roi': None if roi is None else round(roi, 4),
                         'p5': None if p5 is None else round(p5, 4)}
    fuera['pasa'] = all((fuera[k]['p5'] or -1) > 0 for k in ('eleccion', 'juicio'))
    return fuera


def calibracion(a: pd.DataFrame) -> list:
    a = a.copy()
    a['banda'] = pd.cut(a['q'], [0.3, 0.4, 0.5, 0.6, 0.7, 1.0])
    g = a.groupby('banda', observed=True).agg(n=('gana', 'size'),
                                              q=('q', 'mean'),
                                              real=('gana', 'mean'))
    return [{'banda': str(i), 'n': int(r.n), 'dice': round(r.q, 4),
             'pasa': round(r.real, 4)} for i, r in g.iterrows()]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    df = cargar()
    print('partidos', len(df), 'con cierre de Pinnacle 2.5:',
          int(df['PC>2.5'].notna().sum()))
    doc = {}
    for nombre, pin, blanda in (
            ('cierre_media', ('PC>2.5', 'PC<2.5'), ('AvgC>2.5', 'AvgC<2.5')),
            ('apertura_media', ('P>2.5', 'P<2.5'), ('Avg>2.5', 'Avg<2.5')),
            ('cierre_maxima', ('PC>2.5', 'PC<2.5'), ('MaxC>2.5', 'MaxC<2.5'))):
        a = apuestas(df, pin, blanda)
        r = tramos(a)
        r['por_lado'] = {l: tramos(a[a['lado'] == l]) for l in ('over', 'under')}
        r['calibracion'] = calibracion(a)
        # por banda de cuota, que es la segmentación que ganó en el proyecto
        r['por_cuota'] = {}
        for lo, hi in ((1.15, 1.6), (1.6, 2.0), (2.0, 2.8), (2.8, 10)):
            x = a[(a['cuota'] >= lo) & (a['cuota'] < hi)]
            r['por_cuota']['%.2f-%.2f' % (lo, hi)] = tramos(x)
        doc[nombre] = r
        print(nombre, json.dumps({k: r[k] for k in ('eleccion', 'juicio', 'pasa')},
                                 ensure_ascii=False))
        for l in ('over', 'under'):
            print('   ', l, json.dumps(r['por_lado'][l], ensure_ascii=False))
        for k, v in r['por_cuota'].items():
            print('    cuota', k, json.dumps(v, ensure_ascii=False))
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
