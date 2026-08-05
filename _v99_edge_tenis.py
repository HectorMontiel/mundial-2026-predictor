#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99 — ¿Existe un edge de apuesta validable en tenis? Con TODO el histórico.

Por qué esto
------------
La interfaz venía diciendo «Tenis: sin edge validado. El mejor ROI fuera de
muestra fue +1,85 % sobre **112 apuestas** (bootstrap p5 −9,55 %)». 112
apuestas no deciden nada: con esa muestra el intervalo es enorme y da igual el
signo del ROI. Pero el proyecto **tiene** cuota de cierre de tenis desde hace
años y no se estaba usando para esto: el histórico unificado trae
**68.408 partidos de ATP y 45.179 de WTA con `Odd_1`/`Odd_2`** (Kaggle /
tennis-data), de 2000 a hoy.

Con eso sí se puede contestar la pregunta.

Protocolo (regla de oro 3)
--------------------------
Pase cronológico, ELO específico de tenis calculado sobre la marcha (sin fuga),
probabilidad calibrada con una logística ajustada SÓLO con el pasado de cada
pliegue, y barrido de reglas de apuesta:

  · se ELIGE la regla mirando los pliegues tempranos,
  · se JUZGA en los tardíos, que no se han mirado,
  · y el veredicto es el **bootstrap p5 del ROI**, no el ROI a secas.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BOOT = 3000
SEMILLA = 99
N_PLIEGUES = 6
ELECCION = (0, 1, 2)          # pliegues tempranos
JUICIO = (3, 4, 5)            # pliegues tardíos, no mirados para elegir


def preparar(circuito: str) -> pd.DataFrame:
    import tenis_fuentes as tf
    df = tf.historico_unificado(circuito)
    df = df.dropna(subset=['Date', 'Player_1', 'Player_2', 'Winner']).copy()
    for c in ('Odd_1', 'Odd_2'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['Odd_1', 'Odd_2'])
    df = df[(df.Odd_1 > 1.01) & (df.Odd_2 > 1.01)]
    df = df.sort_values('Date').reset_index(drop=True)

    # ELO cronológico y ELO por superficie, ambos sin mirar el futuro
    elo, elo_sup = {}, {}
    n_par = {}
    d_elo, d_sup, exp = np.zeros(len(df)), np.zeros(len(df)), np.zeros(len(df))
    y = np.zeros(len(df), dtype=int)
    for i, f in enumerate(df.itertuples(index=False)):
        p1, p2 = f.Player_1, f.Player_2
        sup = str(getattr(f, 'Surface', '') or 'Hard')
        r1, r2 = elo.get(p1, 1500.0), elo.get(p2, 1500.0)
        s1 = elo_sup.get((p1, sup), 1500.0)
        s2 = elo_sup.get((p2, sup), 1500.0)
        d_elo[i], d_sup[i] = r1 - r2, s1 - s2
        exp[i] = min(n_par.get(p1, 0), n_par.get(p2, 0))
        gana1 = 1 if f.Winner == p1 else 0
        y[i] = gana1
        # K decreciente con la experiencia: un debutante se mueve más
        for (a, b, ra, rb, res) in ((p1, p2, r1, r2, gana1), (p2, p1, r2, r1, 1 - gana1)):
            k = 32.0 if n_par.get(a, 0) < 30 else 20.0
            e = 1 / (1 + 10 ** ((rb - ra) / 400))
            elo[a] = ra + k * (res - e)
        for (a, b, ra, rb, res) in ((p1, p2, s1, s2, gana1), (p2, p1, s2, s1, 1 - gana1)):
            k = 32.0 if n_par.get(a, 0) < 30 else 20.0
            e = 1 / (1 + 10 ** ((rb - ra) / 400))
            elo_sup[(a, sup)] = ra + k * (res - e)
        n_par[p1] = n_par.get(p1, 0) + 1
        n_par[p2] = n_par.get(p2, 0) + 1

    df['DIFF_ELO'], df['DIFF_ELO_SUP'], df['EXP'] = d_elo, d_sup, exp
    df['y'] = y
    # probabilidad implícita del mercado, sin margen
    inv1, inv2 = 1 / df.Odd_1, 1 / df.Odd_2
    df['p_mkt'] = inv1 / (inv1 + inv2)
    df['overround'] = inv1 + inv2
    return df


def boot_p5(pnl, rng):
    if len(pnl) < 20:
        return float('nan'), float('nan')
    m = np.array([pnl[rng.integers(0, len(pnl), len(pnl))].mean() for _ in range(BOOT)])
    return float(np.percentile(m, 5)), float(m.mean())


def main():
    from sklearn.linear_model import LogisticRegression

    resumen = {}
    for circuito in ('atp', 'wta'):
        df = preparar(circuito)
        print(f'=== {circuito.upper()}: {len(df)} partidos con cuota '
              f'({df.Date.min().date()} → {df.Date.max().date()}) · '
              f'overround medio {df.overround.mean():.4f}')
        n = len(df)
        bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]

        # probabilidad del modelo fuera de muestra, pliegue a pliegue
        p_mod = np.full(n, np.nan)
        for i in range(N_PLIEGUES):
            ini, fin = bordes[i], bordes[i + 1]
            X = df[['DIFF_ELO', 'DIFF_ELO_SUP']].to_numpy() / 100.0
            m = LogisticRegression(max_iter=2000).fit(X[:ini], df.y.to_numpy()[:ini])
            p_mod[ini:fin] = m.predict_proba(X[ini:fin])[:, 1]
        df['p_mod'] = p_mod
        val = df.dropna(subset=['p_mod']).copy()

        # calidad pura: ¿el modelo sabe algo que el precio no sepa?
        br_mod = float(np.mean((val.p_mod - val.y) ** 2))
        br_mkt = float(np.mean((val.p_mkt - val.y) ** 2))
        print(f'    Brier modelo {br_mod:.4f} · mercado {br_mkt:.4f} '
              f'({"MERCADO" if br_mkt < br_mod else "MODELO"} gana)')

        # --- barrido de reglas -------------------------------------------
        rng = np.random.default_rng(SEMILLA)
        reglas = []
        for ev_min in (0.02, 0.05, 0.10):
            for p_min in (0.30, 0.45, 0.55, 0.65):
                for solo_fav in (False, True):
                    reglas.append((ev_min, p_min, solo_fav))

        def pnl_de(sub, ev_min, p_min, solo_fav):
            out = []
            for lado in (1, 2):
                p = sub.p_mod if lado == 1 else 1 - sub.p_mod
                cu = sub.Odd_1 if lado == 1 else sub.Odd_2
                acierta = (sub.y == 1) if lado == 1 else (sub.y == 0)
                ev = p * cu - 1
                msk = (ev > ev_min) & (p >= p_min)
                if solo_fav:
                    msk &= (p >= 0.5)
                out.append(np.where(acierta[msk], cu[msk] - 1, -1.0))
            return np.concatenate(out) if out else np.array([])

        pliegue_de = np.searchsorted(np.array(bordes[1:]), val.index.to_numpy(), 'right')
        val = val.assign(_pl=pliegue_de)
        elec = val[val._pl.isin(ELECCION)]
        juic = val[val._pl.isin(JUICIO)]

        marcador = []
        for r in reglas:
            pnl = pnl_de(elec, *r)
            if len(pnl) < 200:
                continue
            p5, med = boot_p5(pnl, rng)
            marcador.append((p5, med, len(pnl), r))
        marcador.sort(reverse=True)
        if not marcador:
            print('    ninguna regla con muestra suficiente en la elección')
            continue
        print(f"    {'regla (EVmin, pmin, solo_fav)':<34}{'n':>7}{'ROI':>9}{'p5':>9}   (ELECCIÓN)")
        for p5, med, nn, r in marcador[:4]:
            print(f'    {str(r):<34}{nn:>7}{med:>8.2%}{p5:>9.2%}')
        mejor = marcador[0][3]

        pnl_j = pnl_de(juic, *mejor)
        p5j, medj = boot_p5(pnl_j, rng)
        print(f'    -> elegida {mejor}')
        print(f'    JUICIO (pliegues {JUICIO}, no mirados): n={len(pnl_j)} '
              f'ROI={medj:.2%} p5={p5j:.2%}')
        veredicto = 'EDGE VALIDADO' if (p5j == p5j and p5j > 0) else 'sin edge'
        print(f'    VEREDICTO: {veredicto}')
        resumen[circuito] = {
            'n_con_cuota': int(len(df)), 'brier_modelo': br_mod,
            'brier_mercado': br_mkt, 'regla': list(mejor),
            'n_juicio': int(len(pnl_j)), 'roi_juicio': medj, 'p5_juicio': p5j,
            'veredicto': veredicto}
        print()

    json.dump(resumen, open('_v99_edge_tenis.json', 'w'), indent=1)
    print('-> _v99_edge_tenis.json')


if __name__ == '__main__':
    main()
