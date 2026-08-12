#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v126 — ¿Son rentables el tenis y la MLB, como se da por hecho?

Por qué esta medición
---------------------
El plan de mejora parte de que «tenis y MLB ya sabemos que son rentables» y de
que por eso no hace falta medirles el p5. Es justo la clase de afirmación que
este proyecto ha tenido que desmontar varias veces, y aquí hay con qué
comprobarla: `pick_ledger_deportes.csv` guarda 64.591 partidos de tenis y 7.541
de MLB con la probabilidad del modelo, el resultado real y la cuota.

Lo que se mide es exactamente lo que haría el usuario: apostar el lado que el
modelo considera más probable, a la cuota registrada, con stake plano.

Se reporta el p5 del bootstrap además del ROI, porque es la regla del proyecto:
una estimación puntual positiva sobre muestra corta no distingue una estrategia
buena de una racha.

Uso:  python _v126_roi_tenis_mlb.py
"""
import os
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ARCHIVO = 'pick_ledger_deportes.csv'
N_BOOTSTRAP = 4000


def p5(retornos, semilla: int = 7):
    if len(retornos) < 30:
        return None
    rng = np.random.default_rng(semilla)
    b = [rng.choice(retornos, len(retornos), replace=True).mean()
         for _ in range(N_BOOTSTRAP)]
    return float(np.percentile(b, 5))


def medir(d: pd.DataFrame, etiqueta: str) -> None:
    """ROI de apostar SIEMPRE el lado más probable según el modelo."""
    if d.empty:
        print(f'{etiqueta}: sin filas')
        return
    # el lado más probable y su cuota
    lados = ['home', 'away'] + (['draw'] if 'p_draw' in d.columns else [])
    probs = d[[f'p_{l}' for l in lados]].apply(pd.to_numeric, errors='coerce')
    cuotas = d[[f'cuota_{l}' for l in lados]].apply(pd.to_numeric,
                                                    errors='coerce')
    elegido = probs.values.argmax(axis=1)
    p_sel = probs.values[np.arange(len(d)), elegido]
    c_sel = cuotas.values[np.arange(len(d)), elegido]
    lado_sel = np.array(lados)[elegido]
    # `resultado` viene codificado 0 = gana local · 1 = empate · 2 = gana
    # visitante, que es el convenio del ledger. Compararlo como texto contra
    # 'home'/'away' daba 0 % de acierto en las 72.132 filas, o sea un
    # resultado imposible que delataba el fallo.
    _COD = {0: 'home', 1: 'draw', 2: 'away'}
    res = np.array([_COD.get(int(x), '?') if pd.notna(x) else '?'
                    for x in d['resultado'].values])

    val = (~np.isnan(c_sel)) & (c_sel > 1) & (~np.isnan(p_sel))
    if not val.any():
        print(f'{etiqueta}: ninguna fila con cuota utilizable')
        return
    acierta = (lado_sel[val] == res[val])
    ret = np.where(acierta, c_sel[val] - 1.0, -1.0)
    n = int(val.sum())
    q = p5(ret)
    print(f'{etiqueta:26} n={n:6,}  acierto {acierta.mean()*100:5.2f} %  '
          f'cuota media {c_sel[val].mean():5.2f}  '
          f'ROI {ret.mean()*100:+6.2f} %  p5 {q*100:+6.2f} %'
          .replace(',', '.'))

    # por bandas de probabilidad, que es como decide el usuario
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        m = (p_sel[val] >= lo) & (p_sel[val] < hi)
        if m.sum() < 100:
            continue
        r = ret[m]
        qq = p5(r)
        print(f'    banda {lo:.0%}-{hi:.0%}  n={m.sum():6,}  '
              f'acierto {acierta[m].mean()*100:5.2f} %  '
              f'ROI {r.mean()*100:+6.2f} %  p5 {qq*100:+6.2f} %'
              .replace(',', '.'))


def main() -> int:
    if not os.path.exists(ARCHIVO):
        print(f'No existe {ARCHIVO}')
        return 1
    d = pd.read_csv(ARCHIVO, low_memory=False)
    print(f'{len(d):,} filas en el ledger de deportes\n'.replace(',', '.'))
    for dep in sorted(d['deporte'].dropna().unique()):
        sub = d[d['deporte'] == dep]
        medir(sub, dep)
        print()
    print('Recordatorio: el fútbol da −4,66 % a −6,52 % en las mismas '
          'condiciones, sobre 37.158 apuestas.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
