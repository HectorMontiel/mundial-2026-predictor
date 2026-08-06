#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — ¿El contexto del partido anterior explica el error del modelo desplegado?

El test correcto
----------------
No se pregunta si el contexto predice partidos —eso lo hace hasta el ELO solo—,
sino si aporta algo ENCIMA de lo que el modelo ya sabe. Así que la base no es un
vector de features: es **la propia probabilidad fuera de muestra del modelo
desplegado**, en log-odds. Si añadir el contexto a esa base mejora el log-loss,
entonces el contexto contiene información que el modelo no tenía. Si no, no la
contiene, por muy razonable que suene la hipótesis.

Es el mismo planteamiento del stacking de la v90, y la razón de usarlo aquí es
que no exige reentrenar 55 ligas para contestar la pregunta.

Mercados medidos
----------------
`over_1.5` es el ejemplo literal que motivó la versión, y va primero. Se miden
también `over_2.5`, `btts` y el 1X2 completo para no elegir el mercado que
mejor salga después de mirar — el barrido se fija antes.

Protocolo: 6 pliegues walk-forward sobre el histórico ordenado por fecha, juicio
sólo en los tardíos (los tempranos eligen), bootstrap pareado de la diferencia
de log-loss por partido, y veredicto por p5 — no por la media.
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

N_PLIEGUES = 6
JUICIO_DESDE = 3
BOOT = 4000
SEMILLA = 101
SALIDA = '_v101_ab_contexto_futbol.json'


def cargar_contexto() -> pd.DataFrame:
    """Contexto de todas las ligas con histórico, indexado por MATCH_ID."""
    trozos = []
    for f in sorted(os.listdir('.')):
        if not (f.startswith('historico_') and f.endswith('.csv')):
            continue
        try:
            d = pd.read_csv(f, low_memory=False)
        except Exception:
            continue
        if not {'date', 'home_team', 'away_team', 'home_goals',
                'away_goals', 'MATCH_ID'}.issubset(d.columns):
            continue
        try:
            ctx = cp.contexto_futbol(d)
        except Exception as e:
            print(f'  ! {f}: {type(e).__name__} {e}')
            continue
        trozos.append(ctx[['MATCH_ID'] + cp.COLUMNAS])
    todo = pd.concat(trozos, ignore_index=True)
    todo = todo.drop_duplicates('MATCH_ID', keep='first')
    print(f'contexto disponible para {len(todo)} partidos '
          f'de {len(trozos)} ligas')
    return todo.set_index('MATCH_ID')


def _logit(p):
    return np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))


def _wf(X, y, bordes):
    """Probabilidades fuera de muestra por walk-forward."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    p = np.full(len(y), np.nan)
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        if ini < 200 or len(np.unique(y[:ini])) < 2:
            continue
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
        p[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
    return p


def evaluar(nombre, p_modelo, y, fecha, extras) -> dict:
    """A = recalibrar el modelo desplegado. B = A + contexto."""
    orden = np.argsort(fecha.to_numpy(), kind='stable')
    p_modelo, y = p_modelo[orden], y[orden]
    extras = extras[orden]
    n = len(y)
    base = _logit(p_modelo).reshape(-1, 1)
    Xa = base
    Xb = np.column_stack([base, extras])
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]

    pa, pb = _wf(Xa, y, bordes), _wf(Xb, y, bordes)
    msk = ~np.isnan(pa) & ~np.isnan(pb) & (np.arange(n) >= bordes[JUICIO_DESDE])
    yy = y[msk]
    if msk.sum() < 300 or len(np.unique(yy)) < 2:
        print(f'  {nombre}: muestra insuficiente ({int(msk.sum())})')
        return {'veredicto': 'SIN MUESTRA', 'n': int(msk.sum())}

    def ll_por_caso(p):
        p = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(p) + (1 - yy) * np.log(1 - p))

    ea, eb = ll_por_caso(pa), ll_por_caso(pb)
    d = ea - eb                       # positivo = B mejora
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    prob = float((bt > 0).mean())
    veredicto = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
    print(f'  {nombre:<12} n={len(d):>6} · log-loss A {ea.mean():.5f} → '
          f'B {eb.mean():.5f} · mejora {d.mean():+.5f} · p5 {p5:+.5f} · '
          f'P(>0) {prob:.1%} · {veredicto}')
    return {'n': int(len(d)), 'll_a': float(ea.mean()), 'll_b': float(eb.mean()),
            'mejora': float(d.mean()), 'p5': p5, 'prob_positiva': prob,
            'veredicto': veredicto}


def main():
    ctx = cargar_contexto()
    salida = {}

    # --- mercados de goles (el ejemplo que motivó la versión) ---
    tot = pd.read_csv('pick_ledger_totales.csv')
    tot = tot.join(ctx, on='match_id', how='inner')
    tot = tot.dropna(subset=cp.COLUMNAS)
    print(f'\ntotales: {len(tot)} filas con contexto')
    extras = tot[cp.COLUMNAS].to_numpy(dtype=float)
    for mercado, col_p, col_y in (('over_1.5', 'p_over_1.5', 'over_1.5_real'),
                                  ('over_2.5', 'p_over_2.5', 'over_2.5_real'),
                                  ('btts', 'p_btts', 'btts_real')):
        sub = tot.dropna(subset=[col_p, col_y])
        salida[mercado] = evaluar(
            mercado, sub[col_p].to_numpy(dtype=float),
            sub[col_y].to_numpy(dtype=float),
            pd.to_datetime(sub['fecha']),
            sub[cp.COLUMNAS].to_numpy(dtype=float))

    # --- 1X2, medido como tres binarios (local / empate / visitante) ---
    led = pd.read_csv('pick_ledger.csv')
    led = led.join(ctx, on='match_id', how='inner').dropna(subset=cp.COLUMNAS)
    print(f'\n1X2: {len(led)} filas con contexto')
    # CODIFICACIÓN DEL LEDGER: 0 = gana local, 1 = empate, 2 = gana visitante.
    # Verificado contra el marcador (`goles_local` vs `goles_visit`) en las
    # 47.948 filas, no supuesto: la primera versión de este A/B asumió
    # 1=local/0=empate y produjo un «hallazgo» de +0,028 en el empate que era
    # sólo la etiqueta cruzada. Se comprueba, no se deduce del nombre.
    for etiqueta, col_p, valor in (('gana local', 'p_home', 0),
                                   ('empate', 'p_draw', 1),
                                   ('gana visita', 'p_away', 2)):
        sub = led.dropna(subset=[col_p, 'resultado'])
        salida[f'1x2:{etiqueta}'] = evaluar(
            etiqueta, sub[col_p].to_numpy(dtype=float),
            (sub['resultado'].to_numpy() == valor).astype(float),
            pd.to_datetime(sub['fecha']),
            sub[cp.COLUMNAS].to_numpy(dtype=float))

    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
