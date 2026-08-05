#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v100 — Leagues Cup contra la CUOTA DE CIERRE (no contra el ELO).

Hasta ahora se validaba por precisión frente al ELO sobre 62 partidos de la
última edición. El criterio de Capa 1 no es ése: es batir al MERCADO. Con las
90 cuotas de cierre reunidas de BetExplorer se puede preguntar lo que importa.

Se comparan la variante desplegada y la que corrige la localía ficticia.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

from _v100_localia_leagues_cup import COLS, matriz, preparar

BOOT = 4000
SEMILLA = 100


def boot(x, rng):
    if len(x) < 15:
        return float('nan'), float('nan')
    m = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(BOOT)])
    return float(np.percentile(m, 5)), float(m.mean())


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    df = preparar()
    cu = pd.read_csv('cuotas_leagues_cup_cierre.csv')
    cu['fecha'] = pd.to_datetime(cu['fecha'])
    lc_df = df[df.competicion == 'leagues_cup'].copy()
    lc_df['fecha'] = lc_df.date.dt.normalize()

    # se cruza con tolerancia de un día (ESPN fecha en UTC, BetExplorer local)
    filas = []
    for delta in (0, 1, -1):
        tmp = cu.copy()
        tmp['fecha'] = tmp['fecha'] + pd.Timedelta(days=delta)
        filas.append(tmp)
    cu2 = pd.concat(filas, ignore_index=True)
    j = lc_df.merge(cu2, on=['fecha', 'home_team', 'away_team'], how='inner',
                    suffixes=('', '_c')) if 'home_team' in cu2.columns else None
    if j is None:
        cu2 = cu2.rename(columns={'home': 'home_team', 'away': 'away_team'})
        j = lc_df.merge(cu2, on=['fecha', 'home_team', 'away_team'], how='inner')
    j = j.drop_duplicates(subset=['fecha', 'home_team', 'away_team'])
    print(f'partidos de Leagues Cup con cierre cruzado: {len(j)}')
    if len(j) < 30:
        print('muestra insuficiente para concluir'); return

    # COHERENCIA (regla de oro 7) — y aquí saltó de verdad.
    #
    # Primera versión: exigir que ESPN y BetExplorer dieran el mismo resultado.
    # Coincidían en 60 de 86 (69,8 %) y el guardia paró el backtest. Bien
    # parado, porque el motivo importa: **BetExplorer registra 0 % de empates y
    # ESPN el 29,5 %**. La Leagues Cup decide TODOS sus partidos por penaltis,
    # así que BetExplorer guarda el ganador del desempate y ESPN el marcador
    # reglamentario.
    #
    # ¿Y para qué se pagan las cuotas? Para los 90 minutos: la columna X tiene
    # una probabilidad implícita media del **25,3 %**, coherente con el 29,5 %
    # de empates observados. Si no existiera el empate en ese mercado, esa
    # columna no valdría 1/4.
    #
    # Conclusión: el precio es de BetExplorer y el RESULTADO es el de ESPN. Usar
    # el `res` de BetExplorer habría liquidado apuestas de 90 minutos con el
    # ganador tras penaltis — un ROI inventado, sin ningún error por pantalla.
    p_x = (1 / j.odd_draw) / (1 / j.odd_home + 1 / j.odd_draw + 1 / j.odd_away)
    tasa_x = float((j.y == 1).mean())
    print(f'empate: implícito {p_x.mean():.3f} · observado {tasa_x:.3f} '
          f'(las cuotas son de 90 min; el resultado se toma de ESPN)')
    if abs(p_x.mean() - tasa_x) > 0.15:
        print('!! el mercado no parece de 90 minutos; no se sigue'); return

    rng = np.random.default_rng(SEMILLA)
    inv = np.column_stack([1 / j.odd_home, 1 / j.odd_draw, 1 / j.odd_away])
    imp = inv / inv.sum(1, keepdims=True)
    print(f'overround medio: {inv.sum(1).mean():.4f}')
    y = j.y.to_numpy()
    cuotas = np.column_stack([j.odd_home, j.odd_draw, j.odd_away])

    salida = {'n': int(len(j)), 'overround': float(inv.sum(1).mean())}
    print()
    print(f"{'variante':<12}{'Brier':>9}{'logloss':>9}{'acc':>8}   apuestas EV>2 %  ROI      p5")
    for nombre, cols in list(COLS.items()) + [('sin_local', COLS['completo'])]:
        # predicción fuera de muestra: se entrena con lo anterior a cada partido
        p_out = np.zeros((len(j), 3))
        for i, fila in enumerate(j.itertuples(index=False)):
            tr = df[df.date < fila.date]
            if len(tr) < 500:
                p_out[i] = [1 / 3, 1 / 3, 1 / 3]
                continue
            sc = StandardScaler().fit(matriz(tr, cols))
            m = LogisticRegression(max_iter=3000).fit(sc.transform(matriz(tr, cols)), tr.y)
            uno = j.iloc[[i]]
            p = m.predict_proba(sc.transform(matriz(uno, cols)))[0]
            if nombre == 'sin_local':
                esp = uno.copy()
                esp['DIFF_ELO'] = -esp['DIFF_ELO']
                esp[['PPG_H', 'PPG_A']] = esp[['PPG_A', 'PPG_H']].values
                esp['host_mls'] = -esp['host_mls']
                pe = m.predict_proba(sc.transform(matriz(esp, cols)))[0]
                p = (p + np.array([pe[2], pe[1], pe[0]])) / 2.0
            p_out[i] = p

        br = float(np.mean((p_out[np.arange(len(y)), y] - 1) ** 2))
        ll = float(log_loss(y, p_out, labels=[0, 1, 2]))
        acc = float((p_out.argmax(1) == y).mean())
        ev = p_out * cuotas - 1
        msk = ev > 0.02
        pnl = np.where(msk, np.where(np.arange(3)[None, :] == y[:, None],
                                     cuotas - 1, -1.0), 0.0)[msk]
        p5, med = boot(pnl, rng)
        print(f'{nombre:<12}{br:>9.4f}{ll:>9.4f}{acc:>8.4f}   n={len(pnl):<6} '
              f'{med:>7.2%} {p5:>8.2%}')
        salida[nombre] = {'brier': br, 'logloss': ll, 'acc': acc,
                          'n_apuestas': int(len(pnl)), 'roi': med, 'p5': p5}

    br_m = float(np.mean((imp[np.arange(len(y)), y] - 1) ** 2))
    ll_m = float(log_loss(y, imp, labels=[0, 1, 2]))
    acc_m = float((imp.argmax(1) == y).mean())
    print(f'{"MERCADO":<12}{br_m:>9.4f}{ll_m:>9.4f}{acc_m:>8.4f}')
    salida['mercado'] = {'brier': br_m, 'logloss': ll_m, 'acc': acc_m}

    json.dump(salida, open('_v100_backtest_leagues_cup.json', 'w'), indent=1)
    print('\n-> _v100_backtest_leagues_cup.json')


if __name__ == '__main__':
    main()
