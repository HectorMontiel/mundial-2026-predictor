#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora E — MLB: ¿carreras esperadas en vez de clasificador de moneyline?

Qué hace hoy el motor
---------------------
`MLBEngine` entrena un clasificador binario (gana local sí/no) y, por separado,
un regresor Poisson del TOTAL de carreras. Para poder ofrecer run line, totales
por equipo y F5, `plantilla_mlb` tiene que RECONSTRUIR las λ de cada equipo
invirtiendo una normal:

    mu = sigma · Φ⁻¹(p_home);  λ_local = (total+mu)/2;  λ_visit = (total−mu)/2

Eso mezcla tres modelos distintos (clasificador, regresor del total y una σ
constante de metadata) y no garantiza que la matriz de carreras resultante
reproduzca la probabilidad de moneyline de la que partió.

Qué se prueba aquí
------------------
Dos regresores Poisson directos —carreras del local y del visitante— de los que
sale TODO por convolución. El moneyline pasa a ser P(H>A) más el reparto de los
empates en la regulación, que en béisbol se resuelven en entradas extra.

Variantes medidas:
  · `clasificador`  — el actual. Referencia.
  · `carreras`      — dos Poisson + P(H>A) crudo.
  · `carreras_cal`  — idem con calibración isotónica de la probabilidad final
                      ajustada SÓLO con datos de train (la independencia entre
                      las carreras de ambos equipos es falsa: hay sobredispersión
                      y contexto común —parque, clima, árbitro— así que la prob
                      cruda queda descalibrada aunque ordene bien).
  · `mixto`         — media de clasificador y carreras_cal.

Métricas: precisión, log-loss y ECE (error de calibración esperado, 10 bins),
que es la que el spec permite usar para adoptar por sí sola.

Salida: `_v70_wf_mlb.json`
"""
import json
import logging
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_wf_mlb.json'
N_PLIEGUES = 5
FRAC_TEST = 0.40
N_MAX = 30                    # tope de carreras para la convolución

# Ventaja del local en entradas extra. Se estima de los datos; este es el
# arranque si no hubiese muestra suficiente.
P_EXTRA_HOME = 0.5


def ece(y, p, bins=10):
    """Error de calibración esperado: |confianza − acierto| ponderado."""
    b = np.clip((p * bins).astype(int), 0, bins - 1)
    tot = 0.0
    for k in range(bins):
        m = b == k
        if m.sum() == 0:
            continue
        tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def dataset_carreras(df):
    """
    Mismo pase cronológico que `MLBEngine._dataset` pero devolviendo también las
    carreras de CADA equipo (el actual sólo devuelve el total) y añadiendo las
    features del spec que faltaban: efecto del bullpen y factor de parque.
    """
    MA = 10
    df = df.sort_values('date').reset_index(drop=True)
    elo, rs, ra, streak, ult, pit_ra = {}, {}, {}, {}, {}, {}
    bull = {}                       # carreras permitidas por el relevo
    parque_gf, parque_n = {}, {}    # park factor rodante
    X, y, runs, fechas = [], [], [], []

    def _m(d, k, dv, n=MA):
        v = d.get(k, [])
        return float(np.mean(v[-n:])) if v else dv

    for r in df.itertuples(index=False):
        h, a = r.home_team, r.away_team
        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
        rs_h, rs_a = _m(rs, h, 4.5), _m(rs, a, 4.5)
        ra_h, ra_a = _m(ra, h, 4.5), _m(ra, a, 4.5)
        rest_h = min((r.date - ult[h]).days, 7) if h in ult else 3
        rest_a = min((r.date - ult[a]).days, 7) if a in ult else 3
        pr_h = _m(pit_ra, r.home_pitcher, 4.5, 5)
        pr_a = _m(pit_ra, r.away_pitcher, 4.5, 5)
        bu_h, bu_a = _m(bull, h, 4.0, 8), _m(bull, a, 4.0, 8)
        pf = (parque_gf.get(h, 0.0) / parque_n[h]) if parque_n.get(h, 0) >= 20 else 8.8
        if all(len(rs.get(t, [])) >= 5 for t in (h, a)):
            X.append([(eh - ea) / 100.0, (rs_h - rs_a) / 3.0, (ra_h - ra_a) / 3.0,
                      (streak.get(h, 0) - streak.get(a, 0)) / 5.0,
                      (rest_h - rest_a) / 5.0, (pr_h - pr_a) / 3.0,
                      (rs_h + rs_a) / 9.0, (ra_h + ra_a) / 9.0,
                      (pr_h + pr_a) / 9.0,
                      # v70: nuevas
                      rs_h / 4.5, rs_a / 4.5, ra_h / 4.5, ra_a / 4.5,
                      pr_h / 4.5, pr_a / 4.5,
                      (bu_h - bu_a) / 3.0, (bu_h + bu_a) / 9.0, pf / 8.8])
            y.append(int(r.home_runs > r.away_runs))
            runs.append([float(r.home_runs), float(r.away_runs)])
            fechas.append(r.date)
        gh, ga = float(r.home_runs), float(r.away_runs)
        rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
        rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
        pit_ra.setdefault(r.home_pitcher, []).append(ga)
        pit_ra.setdefault(r.away_pitcher, []).append(gh)
        # bullpen: carreras del rival por encima de lo que "explica" el abridor
        bull.setdefault(h, []).append(max(ga - pr_h, 0.0))
        bull.setdefault(a, []).append(max(gh - pr_a, 0.0))
        parque_gf[h] = parque_gf.get(h, 0.0) + gh + ga
        parque_n[h] = parque_n.get(h, 0) + 1
        for eq, gano in ((h, gh > ga), (a, ga > gh)):
            streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else \
                min(streak.get(eq, 0), 0) - 1
        e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
        s_h = 1.0 if gh > ga else 0.0
        elo[h] = eh + 20 * (s_h - e_h)
        elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
        ult[h] = ult[a] = r.date
    return (np.array(X), np.array(y), np.array(runs), pd.Series(fechas))


def p_home_de_carreras(lam_h, lam_a, p_extra=P_EXTRA_HOME):
    """P(gana local) por convolución de dos Poisson, repartiendo el empate."""
    from scipy.stats import poisson
    kk = np.arange(N_MAX)
    out = np.empty(len(lam_h))
    for i in range(len(lam_h)):
        ph = poisson.pmf(kk, lam_h[i])
        pa = poisson.pmf(kk, lam_a[i])
        M = np.outer(ph, pa)
        # M[i, j] = P(local=i, visitante=j) → el LOCAL gana con i > j, que es el
        # triángulo INFERIOR. Con `triu` saldría la probabilidad del visitante.
        gana = np.tril(M, -1).sum()         # H > A
        empate = np.trace(M)
        out[i] = gana + empate * p_extra
    return np.clip(out, 1e-6, 1 - 1e-6)


def main():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import (HistGradientBoostingRegressor,
                                  RandomForestClassifier, VotingClassifier)
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import accuracy_score, log_loss
    from sklearn.preprocessing import StandardScaler
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    import retrosheet_scraper
    import datetime
    anio = datetime.date.today().year
    df = retrosheet_scraper.actualizar(list(range(anio - 5, anio + 1)))
    X, y, runs, fechas = dataset_carreras(df)
    logger.info(f"[mlb] {len(X)} juegos utilizables · "
                f"{fechas.min().date()} → {fechas.max().date()}")

    n = len(X)
    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, N_PLIEGUES + 1).astype(int)
    nombres = ['clasificador', 'carreras', 'carreras_cal', 'mixto']
    acum = {k: [] for k in nombres}
    y_oos, elo_oos = [], []

    for f in range(N_PLIEGUES):
        a, b = cortes[f], cortes[f + 1]
        tr, te = slice(0, a), slice(a, b)
        sc = StandardScaler().fit(X[tr])
        Xtr, Xte = sc.transform(X[tr]), sc.transform(X[te])

        # ventaja del local en entradas extra, medida SOLO en train
        emp = runs[tr][:, 0] == runs[tr][:, 1]
        p_extra = P_EXTRA_HOME
        if emp.sum() > 30:
            # los empates en 9 no existen en el histórico final: se usa como
            # aproximación la tasa de victoria local en juegos de 1 carrera
            cerr = np.abs(runs[tr][:, 0] - runs[tr][:, 1]) == 1
            if cerr.sum() > 50:
                p_extra = float((runs[tr][cerr, 0] > runs[tr][cerr, 1]).mean())

        # --- clasificador actual
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                  learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                    learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                          random_state=42))], voting='soft')
        clf = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(Xtr, y[tr])
        p_clf = clf.predict_proba(Xte)[:, list(clf.classes_).index(1)]

        # --- regresores de carreras
        def _reg():
            return HistGradientBoostingRegressor(
                loss='poisson', max_iter=300, learning_rate=0.05,
                max_depth=5, min_samples_leaf=40, l2_regularization=1.0,
                random_state=42)
        rh = _reg().fit(Xtr, runs[tr][:, 0])
        ra_ = _reg().fit(Xtr, runs[tr][:, 1])
        lam_h = np.clip(rh.predict(Xte), 0.5, 15)
        lam_a = np.clip(ra_.predict(Xte), 0.5, 15)
        p_run = p_home_de_carreras(lam_h, lam_a, p_extra)

        # --- calibración isotónica ajustada en el ÚLTIMO 25 % del train
        c75 = int(a * 0.75)
        lam_h_i = np.clip(_reg().fit(sc.transform(X[:c75]), runs[:c75, 0])
                          .predict(sc.transform(X[c75:a])), 0.5, 15)
        lam_a_i = np.clip(_reg().fit(sc.transform(X[:c75]), runs[:c75, 1])
                          .predict(sc.transform(X[c75:a])), 0.5, 15)
        p_in = p_home_de_carreras(lam_h_i, lam_a_i, p_extra)
        iso = IsotonicRegression(out_of_bounds='clip', y_min=0.01, y_max=0.99)
        iso.fit(p_in, y[c75:a])
        p_cal = np.clip(iso.predict(p_run), 1e-6, 1 - 1e-6)

        acum['clasificador'].append(p_clf)
        acum['carreras'].append(p_run)
        acum['carreras_cal'].append(p_cal)
        acum['mixto'].append(0.5 * p_clf + 0.5 * p_cal)
        y_oos.append(y[te])
        elo_oos.append((X[te][:, 0] > 0).astype(int))
        logger.info(f"  pliegue {f+1}/{N_PLIEGUES}: train {a} · test {b-a} · "
                    f"p_extra_home={p_extra:.3f}")

    yv = np.concatenate(y_oos)
    res = {'n': int(n), 'n_oos': int(len(yv)), 'pliegues': N_PLIEGUES,
           'elo_acc': round(float(accuracy_score(yv, np.concatenate(elo_oos))), 4),
           'modelos': {}}
    for k in nombres:
        p = np.concatenate(acum[k])
        res['modelos'][k] = {
            'acc': round(float(accuracy_score(yv, (p >= 0.5).astype(int))), 4),
            'll': round(float(log_loss(yv, np.column_stack([1 - p, p]))), 4),
            'ece': round(ece(yv, p), 4)}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    logger.info(f"ELO {res['elo_acc']}")
    for k, v in res['modelos'].items():
        logger.info(f"  {k:14s} acc={v['acc']:.4f} ll={v['ll']:.4f} ece={v['ece']:.4f}")


if __name__ == '__main__':
    main()
