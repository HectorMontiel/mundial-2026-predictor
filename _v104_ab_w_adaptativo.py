#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v104 — Encogimiento al mercado PROPORCIONAL A LO QUE EL MODELO SABE.

La idea
-------
El proyecto ya mezcla modelo y mercado con un peso fijo por deporte (`w=0,25`
en tenis, v75/v78). Fijo significa que el modelo pesa lo mismo cuando conoce a
los dos equipos de sobra que cuando no los ha visto nunca. Y ahí está el fallo
que produjo el pick del Vikingur: 8 partidos de historial, ELO 1501 contra 1511
—o sea el valor de arranque—, el modelo decía 46 % y el mercado 10,5 %. Con un
peso fijo, esa opinión sin fundamento entra en la mezcla con la misma fuerza que
una sobre el Real Madrid.

Lo que se propone es que el peso del modelo sea función de su CONOCIMIENTO:

    w(n) = w_max · n / (n + K)

donde `n` es el número de partidos previos del equipo con MENOS historial de los
dos. Con n=0 el sistema repite el precio de la casa (no inventa); con n grande
recupera el `w` de siempre. Es el mismo encogimiento bayesiano que el proyecto
ya usa en `aprendizaje_continuo` y en el factor de parque, aplicado al eje que
faltaba.

No es una idea exótica: es la forma estándar de decir «no opines de lo que no
sabes». Lo que no estaba era medirlo aquí.

Qué se compara
--------------
  A · la probabilidad del modelo tal cual (lo que hay hoy en el ledger).
  B · mezcla con peso FIJO hacia el mercado.
  C · mezcla con peso ADAPTATIVO por conocimiento.

Sobre `pick_ledger.csv`, 36.006 predicciones con cuota de cierre real. Se mide
log-loss, Brier, acierto y ROI, y se barren `w_max` y `K` en pliegues tempranos
para elegir; el juicio se emite en los tardíos. Bootstrap pareado y veredicto
por p5, como todo lo demás.
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

from _v103_ab_conocimiento import conocimiento_por_partido

BOOT = 4000
SEMILLA = 104
SALIDA = '_v104_ab_w_adaptativo.json'
# barrido; la elección se hace en la mitad temprana y el juicio en la tardía
W_MAX = (0.15, 0.25, 0.40, 0.60)
KS = (5, 15, 40, 100)


def _devigar(p_h, p_d, p_a):
    """Probabilidades del mercado sin margen (normalización simple)."""
    s = p_h + p_d + p_a
    return p_h / s, p_d / s, p_a / s


def cargar() -> pd.DataFrame:
    tabla = conocimiento_por_partido()
    d = pd.read_csv('pick_ledger.csv').join(tabla, on='match_id', how='inner')
    d = d.dropna(subset=['p_home', 'p_draw', 'p_away', 'resultado',
                         'cuota_home', 'cuota_draw', 'cuota_away',
                         'conocimiento'])
    ih = 1 / d['cuota_home'].to_numpy(dtype=float)
    idr = 1 / d['cuota_draw'].to_numpy(dtype=float)
    ia = 1 / d['cuota_away'].to_numpy(dtype=float)
    mh, md, ma = _devigar(ih, idr, ia)
    d['m_home'], d['m_draw'], d['m_away'] = mh, md, ma
    return d.sort_values('fecha', kind='stable').reset_index(drop=True)


def evaluar(d, w_vec, etiqueta, msk):
    """Log-loss multiclase, acierto y ROI del pick elegido tras mezclar."""
    P = d[['p_home', 'p_draw', 'p_away']].to_numpy(dtype=float)
    M = d[['m_home', 'm_draw', 'm_away']].to_numpy(dtype=float)
    w = w_vec.reshape(-1, 1)
    Q = w * P + (1 - w) * M
    Q = Q / Q.sum(axis=1, keepdims=True)
    y = d['resultado'].to_numpy(dtype=int)
    idx = np.arange(len(d))
    ll = -np.log(np.clip(Q[idx, y], 1e-9, 1))
    lado = Q.argmax(axis=1)
    acierto = (lado == y).astype(float)
    cuotas = d[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(dtype=float)
    cu = cuotas[idx, lado]
    g = acierto * (cu - 1) - (1 - acierto)
    return {'etiqueta': etiqueta, 'll': float(ll[msk].mean()),
            'acierto': float(acierto[msk].mean()),
            'roi_pct': float(g[msk].mean() * 100),
            'brier': float(np.mean((Q[msk] - np.eye(3)[y[msk]]) ** 2) * 3),
            '_ll_vec': ll}


def main():
    d = cargar()
    n = len(d)
    corte = int(n * 0.5)
    temprano = np.arange(n) < corte
    tarde = ~temprano
    conoc = d['conocimiento'].to_numpy(dtype=float)
    print(f'{n} predicciones con cuota y conocimiento · '
          f'elección en las primeras {corte}, juicio en las {n - corte} últimas\n')

    salida = {}
    # --- elección de hiperparámetros SOLO con la mitad temprana ------------
    mejor = None
    print('barrido (mitad temprana):')
    for wm in W_MAX:
        for k in KS:
            w = wm * conoc / (conoc + k)
            r = evaluar(d, w, f'w_max={wm} K={k}', temprano)
            if mejor is None or r['ll'] < mejor['ll']:
                mejor = {**r, 'w_max': wm, 'K': k}
    print(f"  elegido: {mejor['etiqueta']} · log-loss {mejor['ll']:.5f}")
    salida['elegido'] = {'w_max': mejor['w_max'], 'K': mejor['K']}

    # w fijo de referencia: el mejor w constante en la mitad temprana
    mejor_fijo = None
    for wf in (0.0, 0.15, 0.25, 0.40, 0.60, 1.0):
        r = evaluar(d, np.full(n, wf), f'w fijo={wf}', temprano)
        if mejor_fijo is None or r['ll'] < mejor_fijo['ll']:
            mejor_fijo = {**r, 'w': wf}
    print(f"  mejor w fijo: {mejor_fijo['w']} · log-loss {mejor_fijo['ll']:.5f}")
    salida['mejor_w_fijo'] = mejor_fijo['w']

    # --- juicio en la mitad tardía ----------------------------------------
    print('\njuicio (mitad tardía):')
    print(f'{"variante":<26} {"log-loss":>9} {"Brier":>8} {"acierto":>8} {"ROI":>9}')
    A = evaluar(d, np.ones(n), 'A · modelo solo', tarde)
    B = evaluar(d, np.full(n, mejor_fijo['w']),
                f"B · w fijo {mejor_fijo['w']}", tarde)
    w_ad = mejor['w_max'] * conoc / (conoc + mejor['K'])
    C = evaluar(d, w_ad, 'C · w adaptativo', tarde)
    MKT = evaluar(d, np.zeros(n), 'mercado solo', tarde)
    for r in (A, B, C, MKT):
        print(f"{r['etiqueta']:<26} {r['ll']:>9.5f} {r['brier']:>8.4f} "
              f"{r['acierto']:>8.4f} {r['roi_pct']:>+8.2f}%")
        salida[r['etiqueta']] = {k: v for k, v in r.items()
                                 if not k.startswith('_')}

    # bootstrap pareado C contra B (¿aporta el adaptativo sobre el fijo?)
    rng = np.random.default_rng(SEMILLA)
    for ref, nombre in ((B, 'B · w fijo'), (A, 'A · modelo solo')):
        dif = (ref['_ll_vec'][tarde] - C['_ll_vec'][tarde])
        bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                       for _ in range(BOOT)])
        p5 = float(np.percentile(bt, 5))
        ver = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
        print(f'  C frente a {nombre:<18} mejora {dif.mean():+.5f} · '
              f'p5 {p5:+.5f} · {ver}')
        salida[f'C_vs_{nombre}'] = {'mejora': float(dif.mean()), 'p5': p5,
                                    'veredicto': ver}

    # --- y el caso que motivó todo: partidos de poco conocimiento ---------
    print('\nsólo partidos con conocimiento < 10 (el caso Vikingur):')
    poco = tarde & (conoc < 10)
    if poco.sum() >= 100:
        for r, etq in ((evaluar(d, np.ones(n), '', poco), 'A · modelo solo'),
                       (evaluar(d, np.full(n, mejor_fijo['w']), '', poco),
                        f"B · w fijo {mejor_fijo['w']}"),
                       (evaluar(d, w_ad, '', poco), 'C · w adaptativo')):
            print(f'  {etq:<24} n={int(poco.sum())} · log-loss {r["ll"]:.5f} '
                  f'· acierto {r["acierto"]:.4f} · ROI {r["roi_pct"]:+.2f}%')
            salida[f'poco_conocimiento|{etq}'] = {
                'n': int(poco.sum()), 'll': r['ll'], 'acierto': r['acierto'],
                'roi_pct': r['roi_pct']}

    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
