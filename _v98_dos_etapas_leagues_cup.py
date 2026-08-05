#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v98 — Leagues Cup: modelo de DOS ETAPAS.

Etapa 1: el modelo ya entrenado sobre el conjunto MLS + Liga MX (6.609
partidos), que es lo desplegado.
Etapa 2: un factor de corrección estimado con los CRUCES entre ligas, en
espacio de PROBABILIDAD (no de ELO, que es lo que la v97 probó y rechazó):
para cada edición se mide cuánto se desvía la probabilidad predicha del
resultado real según de qué liga sea el local, y se corrige.

Protocolo: se ajusta con 2023+2024 (154 partidos) y se juzga en 2025 (62), que
no se mira para ajustar. La corrección se aplica en log-odds, que es donde una
traslación conserva las probabilidades dentro de [0,1].
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import leagues_cup as lc

BOOT = 4000
SEMILLA = 98
AJUSTE = (2023, 2024)
JUICIO = (2025,)


def elo_y_forma(df):
    elo, d, eh, ea = {}, np.zeros(len(df)), [], []
    ppg, fh, fa = {}, [], []
    for i, f in enumerate(df.itertuples(index=False)):
        h, a = f.home_team, f.away_team
        rh, ra = elo.get(h, 1500.0), elo.get(a, 1500.0)
        d[i] = rh - ra
        eh.append(rh); ea.append(ra)
        fh.append(np.mean(ppg.get(h, [])[-5:]) if ppg.get(h) else 1.3)
        fa.append(np.mean(ppg.get(a, [])[-5:]) if ppg.get(a) else 1.3)
        e = 1 / (1 + 10 ** ((ra - rh) / 400))
        s = 1.0 if f.home_goals > f.away_goals else (0.5 if f.home_goals == f.away_goals else 0.0)
        elo[h] = rh + 24 * (s - e)
        elo[a] = ra + 24 * ((1 - s) - (1 - e))
        r = 3 if f.home_goals > f.away_goals else (1 if f.home_goals == f.away_goals else 0)
        ppg.setdefault(h, []).append(r)
        ppg.setdefault(a, []).append(3 - r if r != 1 else 1)
    out = df.reset_index(drop=True).copy()
    out['DIFF_ELO'], out['PPG_H'], out['PPG_A'] = d, fh, fa
    return out


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    df = elo_y_forma(lc.historico(con_ligas=True))
    origen = {}
    for cl in ('mls', 'liga_mx'):
        sub = df[df.competicion == cl]
        for e in set(sub.home_team) | set(sub.away_team):
            origen.setdefault(e, cl)
    df['liga_h'] = df.home_team.map(origen)
    df['liga_a'] = df.away_team.map(origen)
    df['anio'] = df.date.dt.year
    df['y'] = np.where(df.home_goals > df.away_goals, 0,
                       np.where(df.home_goals == df.away_goals, 1, 2))

    X = lambda d: np.column_stack([d.DIFF_ELO / 100, d.PPG_H - d.PPG_A, d.PPG_H + d.PPG_A])

    def etapa1(tr, te):
        sc = StandardScaler().fit(X(tr))
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X(tr)), tr.y)
        return m.predict_proba(sc.transform(X(te)))

    def logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    # --- ETAPA 2: se ajusta el desplazamiento con 2023+2024 -----------------
    aj = df[(df.competicion == 'leagues_cup') & (df.anio.isin(AJUSTE))]
    tr_aj = df[df.date < aj.date.min()]
    p_aj = etapa1(tr_aj, aj)
    cruce_aj = (aj.liga_h != aj.liga_a).to_numpy()
    mls_local = (aj.liga_h == 'mls').to_numpy()
    y_aj = aj.y.to_numpy()

    print(f'ajuste: {len(aj)} partidos ({AJUSTE}), cruces entre ligas '
          f'{int(cruce_aj.sum())}')
    real_h = float((y_aj == 0).mean())
    pred_h = float(p_aj[:, 0].mean())
    print(f'  P(local) predicha {pred_h:.4f} · observada {real_h:.4f} '
          f'· sesgo {real_h - pred_h:+.4f}')
    for etq, msk in (('local de MLS', mls_local & cruce_aj),
                     ('local de Liga MX', (~mls_local) & cruce_aj)):
        if msk.sum() < 5:
            continue
        print(f'  {etq:<18} n={int(msk.sum()):>3} predicha '
              f'{p_aj[msk, 0].mean():.4f} · observada {(y_aj[msk] == 0).mean():.4f} '
              f'· sesgo {(y_aj[msk] == 0).mean() - p_aj[msk, 0].mean():+.4f}')

    # desplazamiento en log-odds que iguala la P(local) media en cada grupo
    def desplazamiento(p, y, msk):
        if msk.sum() < 5:
            return 0.0
        obj = float((y[msk] == 0).mean())
        lo = logit(p[msk, 0])
        mejor, err = 0.0, np.inf
        for c in np.arange(-1.5, 1.51, 0.01):
            q = 1 / (1 + np.exp(-(lo + c)))
            e = abs(q.mean() - obj)
            if e < err:
                mejor, err = float(c), e
        return mejor

    c_mls = desplazamiento(p_aj, y_aj, mls_local & cruce_aj)
    c_mx = desplazamiento(p_aj, y_aj, (~mls_local) & cruce_aj)
    print(f'  desplazamiento en log-odds: local MLS {c_mls:+.3f} · '
          f'local Liga MX {c_mx:+.3f}')

    # --- JUICIO: 2025, que no se ha mirado ---------------------------------
    ju = df[(df.competicion == 'leagues_cup') & (df.anio.isin(JUICIO))]
    tr_ju = df[df.date < ju.date.min()]
    p_ju = etapa1(tr_ju, ju)
    y_ju = ju.y.to_numpy()
    cruce_ju = (ju.liga_h != ju.liga_a).to_numpy()
    mls_ju = (ju.liga_h == 'mls').to_numpy()

    p_cor = p_ju.copy()
    lo = logit(p_ju[:, 0])
    c = np.where(mls_ju, c_mls, c_mx) * cruce_ju
    p_home_cor = 1 / (1 + np.exp(-(lo + c)))
    # se reparte el resto entre empate y visitante conservando su proporción
    resto = p_ju[:, 1] + p_ju[:, 2]
    with np.errstate(divide='ignore', invalid='ignore'):
        prop_x = np.where(resto > 0, p_ju[:, 1] / resto, 0.5)
    p_cor[:, 0] = p_home_cor
    p_cor[:, 1] = (1 - p_home_cor) * prop_x
    p_cor[:, 2] = (1 - p_home_cor) * (1 - prop_x)

    elo_pred = np.where(ju.DIFF_ELO.to_numpy() > 0, 0, 2)
    ok_base = (p_ju.argmax(1) == y_ju)
    ok_cor = (p_cor.argmax(1) == y_ju)
    ok_elo = (elo_pred == y_ju)

    print()
    print(f'JUICIO {JUICIO[0]} (n={len(ju)}):')
    print(f'  etapa 1 (sin corregir) {ok_base.mean():.4f} · '
          f'log-loss {log_loss(y_ju, p_ju, labels=[0,1,2]):.4f}')
    print(f'  dos etapas (corregido) {ok_cor.mean():.4f} · '
          f'log-loss {log_loss(y_ju, p_cor, labels=[0,1,2]):.4f}')
    print(f'  ELO (línea base)       {ok_elo.mean():.4f}')

    rng = np.random.default_rng(SEMILLA)
    d = ok_cor.astype(float) - ok_elo.astype(float)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5, p50, p95 = np.percentile(bt, [5, 50, 95])
    print(f'  ventaja dos-etapas − ELO: {d.mean():+.4f} '
          f'(p5 {p5:+.4f} · mediana {p50:+.4f} · p95 {p95:+.4f}) '
          f'P(>0)={(bt > 0).mean():.1%}')

    salida = {'c_mls': c_mls, 'c_liga_mx': c_mx, 'n_ajuste': int(len(aj)),
              'n_juicio': int(len(ju)),
              'acc_etapa1': float(ok_base.mean()),
              'acc_dos_etapas': float(ok_cor.mean()),
              'acc_elo': float(ok_elo.mean()),
              'll_etapa1': float(log_loss(y_ju, p_ju, labels=[0, 1, 2])),
              'll_dos_etapas': float(log_loss(y_ju, p_cor, labels=[0, 1, 2])),
              'ventaja': float(d.mean()), 'p5': float(p5), 'p95': float(p95),
              'prob_positiva': float((bt > 0).mean())}
    json.dump(salida, open('_v98_dos_etapas_leagues_cup.json', 'w'), indent=1)
    print('\n-> _v98_dos_etapas_leagues_cup.json')


if __name__ == '__main__':
    main()
