#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v118 — ¿La probabilidad que publica el motor de MLB se cumple?

El usuario lo pidió tal cual: «¿estás seguro de que está bien calibrada esta
herramienta? Valídala con simulaciones de partidos pasados para validar su
eficacia y eficiencia. Si no, mejórala.»

Es la pregunta correcta y no estaba contestada. El metadata dice «precisión
54,7 %», pero acertar el 54,7 % NO significa que un «62 %» sea un 62 %. Son dos
cosas distintas:

  · **acierto** — cuántas veces gana el lado que el modelo señala;
  · **calibración** — cuando dice 62 %, ¿gana el 62 % de las veces?

Un modelo puede acertar mucho y estar mal calibrado (dice 80 % y acierta 60 %),
y entonces todas las apuestas que salgan de esa probabilidad tendrán un EV
inventado. Para apostar importa MÁS la calibración que el acierto, porque el EV
se calcula multiplicando por esa probabilidad.

Protocolo
---------
Simulación honesta hacia adelante, sin mirar el futuro en ningún punto:

  1. se recorre el histórico en orden cronológico;
  2. en cada corte se entrena SÓLO con lo anterior y se predice el tramo
     siguiente, que el modelo no ha visto;
  3. se agrupan las predicciones por banda de probabilidad y se compara lo
     prometido con lo ocurrido.

Se mide, además del acierto y la calibración:
  · **Brier** — error cuadrático medio de la probabilidad (más bajo, mejor);
  · **log-loss** — castiga la confianza equivocada;
  · **ECE** — error de calibración esperado: la distancia media entre lo que
    promete y lo que cumple, ponderada por cuántas apuestas caen en cada banda.
    Es el número que resume si se puede confiar en el porcentaje publicado.

Y se compara contra dos líneas base que hay que batir para que el modelo valga
algo: predecir siempre al local, y el ELO a secas.

    python _v118_calibrar_mlb.py [n_cortes]
"""
import json
import sys

import numpy as np
import pandas as pd

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

HISTORICO = 'historico_mlb.csv'
N_CORTES = 6
MIN_ENTRENO = 3000          # juegos mínimos antes de la primera predicción
SALIDA = '_v118_calibracion_mlb.json'


def _bandas(p, y, n=10):
    """Agrupa por decil de probabilidad: prometido contra cumplido."""
    filas = []
    for i in range(n):
        lo, hi = i / n, (i + 1) / n
        m = (p >= lo) & (p < hi) if i < n - 1 else (p >= lo) & (p <= hi)
        if m.sum() < 20:
            continue
        filas.append({'banda': f'{int(lo*100)}-{int(hi*100)}%',
                      'n': int(m.sum()),
                      'promete': float(p[m].mean()),
                      'cumple': float(y[m].mean())})
    return filas


def _ece(filas, total):
    """Error de calibración esperado: |prometido − cumplido| ponderado."""
    if not total:
        return None
    return sum(f['n'] * abs(f['promete'] - f['cumple']) for f in filas) / total


def main() -> int:
    cortes = int(sys.argv[1]) if len(sys.argv) > 1 else N_CORTES
    print('=' * 78)
    print('v118 — CALIBRACIÓN DEL MOTOR DE MLB, SIMULANDO HACIA ADELANTE')
    print('=' * 78)

    from engines.mlb_engine import MLBEngine
    d = pd.read_csv(HISTORICO)
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date', 'home_runs', 'away_runs'])
    d = d.sort_values('date', kind='stable').reset_index(drop=True)
    # el béisbol no tiene empates, pero por si acaso
    d = d[d['home_runs'] != d['away_runs']].reset_index(drop=True)
    print(f'{len(d)} juegos entre {d["date"].min().date()} y '
          f'{d["date"].max().date()}')

    X, y, _t, _f, estado = MLBEngine._dataset(d)
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < MIN_ENTRENO + 500:
        print('histórico insuficiente')
        return 1
    print(f'vector de features: {X.shape[1]} columnas · {n} filas etiquetadas')

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    bordes = np.linspace(MIN_ENTRENO, n, cortes + 1).astype(int)
    p_mod = np.full(n, np.nan)
    p_elo = np.full(n, np.nan)
    print(f'\nsimulación: {cortes} cortes, cada uno entrena con TODO lo '
          f'anterior\ny predice el siguiente tramo, que no ha visto.')
    for i in range(cortes):
        ini, fin = bordes[i], bordes[i + 1]
        if fin <= ini:
            continue
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
        p_mod[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
        # línea base: sólo el ELO (columna 0), misma familia y mismo protocolo
        sc0 = StandardScaler().fit(X[:ini, :1])
        m0 = LogisticRegression(max_iter=3000).fit(sc0.transform(X[:ini, :1]),
                                                   y[:ini])
        p_elo[ini:fin] = m0.predict_proba(sc0.transform(X[ini:fin, :1]))[:, 1]
        print(f'  corte {i+1}: entrena {ini} · predice {fin-ini}')

    m = ~np.isnan(p_mod)
    pm, pe, yy = p_mod[m], p_elo[m], y[m]
    print(f'\npredicciones fuera de muestra: {m.sum()}')

    def _resumen(p, nombre):
        acc = float(((p >= 0.5) == (yy == 1)).mean())
        brier = float(np.mean((p - yy) ** 2))
        eps = 1e-12
        ll = float(-np.mean(yy * np.log(np.clip(p, eps, 1))
                            + (1 - yy) * np.log(np.clip(1 - p, eps, 1))))
        filas = _bandas(p, yy)
        ece = _ece(filas, int(m.sum()))
        print(f'\n  {nombre}')
        print(f'    acierto  {acc*100:.2f} %')
        print(f'    Brier    {brier:.5f}   (más bajo, mejor)')
        print(f'    log-loss {ll:.5f}')
        print(f'    ECE      {ece*100:.2f} puntos'
              if ece is not None else '    ECE      n/d')
        return {'acierto': acc, 'brier': brier, 'log_loss': ll, 'ece': ece,
                'bandas': filas}

    r_mod = _resumen(pm, 'MODELO (vector completo)')
    r_elo = _resumen(pe, 'LÍNEA BASE (sólo ELO)')
    acc_local = float((yy == 1).mean())
    print(f'\n  SIEMPRE EL LOCAL')
    print(f'    acierto  {acc_local*100:.2f} %')

    print('\n' + '-' * 78)
    print('CALIBRACIÓN DEL MODELO: lo que promete contra lo que cumple')
    print('-' * 78)
    print(f"  {'banda':<12}{'promete':>10}{'cumple':>10}{'n':>8}   desvío")
    for f in r_mod['bandas']:
        print(f"  {f['banda']:<12}{f['promete']*100:>9.1f}%"
              f"{f['cumple']*100:>9.1f}%{f['n']:>8}   "
              f"{(f['cumple']-f['promete'])*100:+.1f} pts")

    print('\n' + '=' * 78)
    print('VEREDICTO')
    print('=' * 78)
    ece = r_mod['ece'] or 0
    if ece <= 0.02:
        print(f'  ✅ ECE {ece*100:.2f} puntos: la probabilidad publicada es')
        print('     fiable. Un «62 %» es un 62 % dentro de dos puntos.')
    elif ece <= 0.04:
        print(f'  🟡 ECE {ece*100:.2f} puntos: aceptable pero mejorable.')
    else:
        print(f'  ❌ ECE {ece*100:.2f} puntos: la probabilidad NO es fiable y')
        print('     el EV que salga de ella está inventado. Hay que calibrar.')
    if r_mod['brier'] < r_elo['brier']:
        print(f"  ✅ Bate al ELO en Brier ({r_mod['brier']:.5f} contra "
              f"{r_elo['brier']:.5f}).")
    else:
        print(f"  ❌ NO bate al ELO en Brier ({r_mod['brier']:.5f} contra "
              f"{r_elo['brier']:.5f}): el vector completo no aporta.")
    if r_mod['acierto'] > acc_local:
        print(f"  ✅ Bate a «siempre el local» ({r_mod['acierto']*100:.2f} % "
              f"contra {acc_local*100:.2f} %).")
    else:
        print(f"  ❌ NO bate a «siempre el local».")

    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump({'n_fuera_muestra': int(m.sum()), 'modelo': r_mod,
                   'elo': r_elo, 'siempre_local': acc_local,
                   'cortes': cortes}, f, ensure_ascii=False, indent=2)
    print(f'\nDetalle en {SALIDA}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
