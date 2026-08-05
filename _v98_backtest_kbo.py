#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v98 — ¿Tiene la KBO edge de APUESTA contra la cuota de cierre?

Predicciones FUERA DE MUESTRA (walk-forward, el mismo esquema de pliegues que
la v97) cruzadas con las 201 cuotas de cierre reales que BetExplorer permite
descargar. Se mide ROI y bootstrap p5, que es lo que el proyecto exige desde la
v13 para poner algo en Capa 1.

AVISO QUE MANDA SOBRE EL RESULTADO: esas 201 son **playoffs**. Es una población
sesgada — sólo equipos fuertes, rotación de lanzadores distinta y ningún
partido intrascendente. Un ROI medido aquí NO se extrapola sin más a la
temporada regular, que es donde la app va a operar.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from engines.kbo_engine import KBOEngine, COLS_MODELO

N_PLIEGUES = 5
BOOT = 4000
SEMILLA = 98


def predicciones_oos():
    """Probabilidad fuera de muestra para cada juego, con su identidad."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    df = pd.read_csv('historico_kbo.csv', parse_dates=['date'])
    dfd = df[df.home_runs != df.away_runs].sort_values('date').reset_index(drop=True)
    X, y, tot, fechas, estado = KBOEngine._dataset(dfd)
    ident = estado['filas']                       # (fecha, home, away) por fila
    n = len(X)
    bordes = [int(n * (0.5 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    filas = []
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=2000).fit(
            sc.transform(X[:ini])[:, COLS_MODELO], y[:ini])
        p = m.predict_proba(sc.transform(X[ini:fin])[:, COLS_MODELO])[:, 1]
        for k in range(ini, fin):
            f, h, a = ident[k]
            filas.append({'fecha': pd.Timestamp(f).strftime('%Y-%m-%d'),
                          'home': h, 'away': a,
                          'p_home': float(p[k - ini]), 'gana_home': int(y[k])})
    return pd.DataFrame(filas)


def bootstrap(pnl, rng, n=BOOT):
    if len(pnl) == 0:
        return (float('nan'),) * 3
    m = np.array([pnl[rng.integers(0, len(pnl), len(pnl))].mean() for _ in range(n)])
    return tuple(np.percentile(m, [5, 50, 95]))


def main():
    oos = predicciones_oos()
    cu = pd.read_csv('cuotas_kbo_cierre.csv')
    j = cu.merge(oos, on=['fecha', 'home', 'away'], how='inner')
    print(f'cuotas: {len(cu)} · predicciones OOS: {len(oos)} · cruzados: {len(j)}')
    if j.empty:
        print('sin solape: nada que medir'); return
    # coherencia (regla de oro 7): las dos fuentes deben decir lo mismo
    ok = int((j.gana_home_x.astype(bool) == j.gana_home_y.astype(bool)).sum())
    print(f'el ganador coincide en {ok}/{len(j)} '
          f'({ok / len(j):.1%}) entre BetExplorer y el histórico de Naver')
    if ok / len(j) < 0.95:
        print('!! las dos fuentes no concuerdan; no se sigue'); return

    rng = np.random.default_rng(SEMILLA)
    p = j.p_home.to_numpy()
    gh = j.gana_home_y.to_numpy().astype(bool)
    oh, oa = j.odd_home.to_numpy(), j.odd_away.to_numpy()

    # sobrerredondeo del mercado y probabilidad implícita sin margen
    imp_h = (1 / oh) / (1 / oh + 1 / oa)
    print(f'overround medio: {(1/oh + 1/oa).mean():.4f}')

    resultados = {}
    print()
    print(f"{'estrategia':<44}{'n':>5}{'ROI':>9}{'p5':>9}{'p95':>9}")
    for etq, umbral in (('modelo: apostar SIEMPRE al lado favorito', 0.0),
                        ('modelo: EV > 0', 0.0),
                        ('modelo: EV > +2 %', 0.02),
                        ('modelo: EV > +5 %', 0.05)):
        pnl = []
        for k in range(len(j)):
            for lado, prob, cuota, acierta in (
                    ('h', p[k], oh[k], gh[k]), ('a', 1 - p[k], oa[k], not gh[k])):
                ev = prob * cuota - 1
                if etq.endswith('favorito'):
                    if (lado == 'h') != (p[k] >= 0.5):
                        continue
                elif ev <= umbral:
                    continue
                pnl.append((cuota - 1) if acierta else -1.0)
        pnl = np.array(pnl)
        p5, p50, p95 = bootstrap(pnl, rng)
        roi = pnl.mean() if len(pnl) else float('nan')
        print(f'{etq:<44}{len(pnl):>5}{roi:>8.2%}{p5:>9.2%}{p95:>9.2%}')
        resultados[etq] = {'n': int(len(pnl)), 'roi': float(roi) if len(pnl) else None,
                           'p5': float(p5), 'p95': float(p95)}

    # línea base: seguir al mercado (apostar al favorito de la casa)
    pnl_m = np.array([(oh[k] - 1) if gh[k] else -1.0 if imp_h[k] >= 0.5
                      else ((oa[k] - 1) if not gh[k] else -1.0)
                      for k in range(len(j))])
    p5m, _, p95m = bootstrap(pnl_m, rng)
    print(f"{'mercado: apostar al favorito de la casa':<44}{len(pnl_m):>5}"
          f'{pnl_m.mean():>8.2%}{p5m:>9.2%}{p95m:>9.2%}')
    resultados['mercado_favorito'] = {'n': int(len(pnl_m)),
                                      'roi': float(pnl_m.mean()),
                                      'p5': float(p5m), 'p95': float(p95m)}

    # calibración: ¿el modelo sabe algo que el precio no sepa?
    print()
    brier_mod = float(np.mean((p - gh) ** 2))
    brier_mkt = float(np.mean((imp_h - gh) ** 2))
    print(f'Brier modelo {brier_mod:.4f} · Brier mercado {brier_mkt:.4f} '
          f'({"el mercado gana" if brier_mkt < brier_mod else "el modelo gana"})')
    acc_mod = float(((p >= 0.5) == gh).mean())
    acc_mkt = float(((imp_h >= 0.5) == gh).mean())
    print(f'precisión modelo {acc_mod:.4f} · mercado {acc_mkt:.4f}')
    resultados['calibracion'] = {'brier_modelo': brier_mod, 'brier_mercado': brier_mkt,
                                 'acc_modelo': acc_mod, 'acc_mercado': acc_mkt,
                                 'n': int(len(j))}
    json.dump(resultados, open('_v98_backtest_kbo.json', 'w'), indent=1)
    print('\n-> _v98_backtest_kbo.json')


if __name__ == '__main__':
    main()
