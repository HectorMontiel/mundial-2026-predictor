#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Experimento de features para MLB. Se adopta SOLO si mide mejor.

Punto de partida (medido sobre 7.541 predicciones fuera de muestra con cuota
de cierre real, 2018-2021):

    log-loss modelo  0,6823      log-loss mercado  0,6688
    precisión modelo 0,5645      precisión mercado 0,5934
    desviación típica del modelo 0,0587  vs mercado 0,1051  →  RATIO 0,558

El ratio es el diagnóstico: el modelo comprime el abanico a la MITAD del
mercado. No es que el béisbol sea plano — el mercado sharp reparte el doble de
recorrido con los mismos partidos. Al modelo le falta señal.

Qué se prueba, y por qué cada cosa
----------------------------------
Todo sale del propio game log (sin peticiones nuevas) y todo es causal: cada
fila se calcula con lo ocurrido ANTES de ese partido.

A. **Encogimiento del abridor + ventana larga.** La feature actual es «carreras
   que concedió el equipo en las últimas 5 aperturas de este lanzador». Cinco
   partidos es una muestra minúscula y la media cruda trata igual a un
   lanzador con 30 aperturas que a uno con 1. Se pasa a 10 aperturas con
   encogimiento empírico-bayesiano hacia la media de la liga.

B. **Dos horizontes de forma del equipo.** MA10 sola es ruidosa. Se añade la
   temporada en curso, encogida, que capta el nivel real del equipo mientras
   MA10 capta la racha.

C. **Factor de parque.** Un partido en Coors Field no es uno en Oracle Park.
   Se estima con el promedio histórico de carreras totales en el estadio del
   local, relativo a la liga.

D. **ELO con margen de victoria.** El ELO actual suma 20 puntos gane por 1 o
   por 10. Se pondera por el margen, que es más informativo.

E. **Descanso del abridor.** Días desde su última apertura.

Protocolo: mismo walk-forward de origen móvil que `build_ledger_deportes`,
mismos pliegues, mismo estimador. Lo único que cambia son las features.
"""
import json
import logging
import warnings

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('mlb-feat')

MA = 10
RUTA = 'historico_mlb.csv'
N_FOLDS, INICIO, MIN_TEST = 5, 0.45, 300


# ---------------------------------------------------------------- features
def dataset_base(df):
    """Réplica exacta de `MLBEngine._dataset` (las 9 features actuales)."""
    from engines.mlb_engine import MLBEngine
    X, y, tot, fechas, estado = MLBEngine._dataset(df)
    return np.asarray(X, float), np.asarray(y, int), \
        pd.Series(pd.to_datetime(fechas)).reset_index(drop=True), estado


def dataset_rico(df):
    """Features enriquecidas (A-E). Causal: se emite antes de actualizar."""
    df = df.sort_values('date').reset_index(drop=True)
    elo, rs, ra, streak, ult, pit_ra, pit_ult = {}, {}, {}, {}, {}, {}, {}
    temp_rs, temp_ra, temp_g = {}, {}, {}      # acumulado de temporada
    parque_runs, parque_n = {}, {}
    anio_actual = None
    # medias de liga móviles (para el encogimiento)
    liga_runs, liga_pit = [], []
    X, y, fechas, filas_id = [], [], [], []

    for r in df.itertuples(index=False):
        h, a, fecha = r.home_team, r.away_team, r.date
        anio = fecha.year
        if anio != anio_actual:                # reinicio de acumulados anuales
            temp_rs, temp_ra, temp_g = {}, {}, {}
            anio_actual = anio

        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
        mu_liga = float(np.mean(liga_runs[-2000:])) if liga_runs else 4.5
        mu_pit = float(np.mean(liga_pit[-2000:])) if liga_pit else 4.5

        def _ma(d, k, dv):
            v = d.get(k, [])
            return float(np.mean(v[-MA:])) if v else dv

        rs_h, rs_a = _ma(rs, h, mu_liga), _ma(rs, a, mu_liga)
        ra_h, ra_a = _ma(ra, h, mu_liga), _ma(ra, a, mu_liga)

        # (B) temporada encogida: (suma + k*mu) / (n + k), k=30 partidos
        def _temp(d, k_eq, dv):
            n = temp_g.get(k_eq, 0)
            s = d.get(k_eq, 0.0)
            return (s + 30.0 * dv) / (n + 30.0)
        trs_h, trs_a = _temp(temp_rs, h, mu_liga), _temp(temp_rs, a, mu_liga)
        tra_h, tra_a = _temp(temp_ra, h, mu_liga), _temp(temp_ra, a, mu_liga)

        # (A) abridor encogido, ventana 10, k=6 aperturas
        def _pit(pid):
            v = pit_ra.get(pid) if isinstance(pid, str) and pid else None
            if not v:
                return mu_pit, 0
            w = v[-10:]
            n = len(w)
            return (float(np.sum(w)) + 6.0 * mu_pit) / (n + 6.0), n
        pr_h, nh = _pit(r.home_pitcher)
        pr_a, na = _pit(r.away_pitcher)

        # (E) descanso del abridor
        def _rest_pit(pid):
            u = pit_ult.get(pid) if isinstance(pid, str) and pid else None
            return float(min((fecha - u).days, 10)) if u is not None else 5.0
        rp_h, rp_a = _rest_pit(r.home_pitcher), _rest_pit(r.away_pitcher)

        rest_h = min((fecha - ult[h]).days, 7) if h in ult else 3
        rest_a = min((fecha - ult[a]).days, 7) if a in ult else 3

        # (C) factor de parque
        pn = parque_n.get(h, 0)
        pf = ((parque_runs.get(h, 0.0) + 20.0 * 2 * mu_liga) /
              (pn + 20.0)) / max(2 * mu_liga, 1e-6)

        if all(len(rs.get(t, [])) >= 5 for t in (h, a)):
            X.append([
                (eh - ea) / 100.0,
                (rs_h - rs_a) / 3.0, (ra_h - ra_a) / 3.0,
                (streak.get(h, 0) - streak.get(a, 0)) / 5.0,
                (rest_h - rest_a) / 5.0,
                (pr_h - pr_a) / 3.0,
                (rs_h + rs_a) / 9.0, (ra_h + ra_a) / 9.0, (pr_h + pr_a) / 9.0,
                # nuevas
                (trs_h - trs_a) / 3.0, (tra_h - tra_a) / 3.0,
                (trs_h + trs_a) / 9.0, (tra_h + tra_a) / 9.0,
                (rp_h - rp_a) / 5.0,
                (pf - 1.0) * 5.0,
                min(nh, 15) / 15.0, min(na, 15) / 15.0,
            ])
            y.append(int(r.home_runs > r.away_runs))
            fechas.append(fecha)
            filas_id.append((fecha, str(h), str(a)))

        # ---- actualizar estado (después de emitir: sin fuga) ----
        gh, ga = float(r.home_runs), float(r.away_runs)
        rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
        rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
        temp_rs[h] = temp_rs.get(h, 0.0) + gh; temp_ra[h] = temp_ra.get(h, 0.0) + ga
        temp_rs[a] = temp_rs.get(a, 0.0) + ga; temp_ra[a] = temp_ra.get(a, 0.0) + gh
        temp_g[h] = temp_g.get(h, 0) + 1; temp_g[a] = temp_g.get(a, 0) + 1
        liga_runs.append(gh); liga_runs.append(ga)
        parque_runs[h] = parque_runs.get(h, 0.0) + gh + ga
        parque_n[h] = parque_n.get(h, 0) + 1
        for pid, conc in ((r.home_pitcher, ga), (r.away_pitcher, gh)):
            if isinstance(pid, str) and pid:
                pit_ra.setdefault(pid, []).append(conc)
                pit_ult[pid] = fecha
                liga_pit.append(conc)
        for eq, gano in ((h, gh > ga), (a, ga > gh)):
            streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else \
                min(streak.get(eq, 0), 0) - 1
        # (D) ELO ponderado por margen
        e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
        s_h = 1.0 if gh > ga else 0.0
        k = 20.0 * (1.0 + np.log1p(abs(gh - ga)) / 2.0)
        elo[h] = eh + k * (s_h - e_h)
        elo[a] = ea + k * ((1 - s_h) - (1 - e_h))
        ult[h] = ult[a] = fecha

    return (np.asarray(X, float), np.asarray(y, int),
            pd.Series(fechas).reset_index(drop=True), filas_id)


# ---------------------------------------------------------------- protocolo
def _modelo():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                              learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                      random_state=42))], voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def walk_forward(X, y, fechas, ids, cuotas, etiqueta):
    from sklearn.preprocessing import StandardScaler
    mid = [f"{f.strftime('%Y%m%d')}_{h}_{a}" for f, h, a in ids]
    con = np.array([i for i, m in enumerate(mid)
                    if cuotas.get(m) and cuotas[m][0] and cuotas[m][1]])
    if len(con) < N_FOLDS * MIN_TEST:
        log.warning(f'{etiqueta}: solo {len(con)} con cuota')
        return None
    bordes = np.linspace(int(len(con) * INICIO), len(con), N_FOLDS + 1).astype(int)
    P, Y, M = [], [], []
    for k in range(N_FOLDS):
        sel = con[bordes[k]:bordes[k + 1]]
        if len(sel) < MIN_TEST:
            continue
        ini, fin = int(sel[0]), int(sel[-1]) + 1
        corte = fechas.iloc[ini:fin].min()
        tr = np.arange(ini)[fechas.iloc[:ini].values < corte]
        if len(tr) < 2000:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            sc = StandardScaler().fit(X[tr])
            m = _modelo().fit(sc.transform(X[tr]), y[tr])
            i1 = list(m.classes_).index(1)
            pr = m.predict_proba(sc.transform(X[ini:fin]))[:, i1]
        for j, i in enumerate(range(ini, fin)):
            c = cuotas.get(mid[i])
            if not c or not (c[0] and c[1]):
                continue
            P.append(pr[j]); Y.append(y[i])
            ih, ia = 1 / c[0], 1 / c[1]
            M.append(ih / (ih + ia))
    P, Y, M = np.array(P), np.array(Y), np.array(M)
    ll = lambda p: float(-(Y * np.log(p.clip(1e-6, 1 - 1e-6)) +
                           (1 - Y) * np.log((1 - p).clip(1e-6, 1 - 1e-6))).mean())
    res = {'etiqueta': etiqueta, 'n': int(len(P)),
           'log_loss': round(ll(P), 4), 'log_loss_mercado': round(ll(M), 4),
           'precision': round(float(((P >= .5).astype(int) == Y).mean()), 4),
           'precision_mercado': round(float(((M >= .5).astype(int) == Y).mean()), 4),
           'std': round(float(P.std()), 4), 'std_mercado': round(float(M.std()), 4),
           'ratio_dispersion': round(float(P.std() / max(M.std(), 1e-9)), 3),
           'corr_mercado': round(float(np.corrcoef(P, M)[0, 1]), 4)}
    log.info(f"{etiqueta}: n={res['n']} ll={res['log_loss']} "
             f"(mercado {res['log_loss_mercado']}) acc={res['precision']} "
             f"ratio={res['ratio_dispersion']}")
    return res


def main():
    import odds_store
    df = pd.read_csv(RUTA, low_memory=False)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    con = odds_store.conectar()
    cur = con.execute("SELECT match_id, odds_home, odds_away FROM historical_odds "
                      "WHERE league_key='mlb' AND fase='cierre'")
    cuotas = {m: (h, a) for m, h, a in cur.fetchall()}
    con.close()
    log.info(f'{len(cuotas)} cuotas de cierre en el almacén')

    Xb, yb, fb, estado = dataset_base(df)
    idsb = estado.get('filas') or []
    base = walk_forward(Xb, yb, fb, idsb, cuotas, 'BASE (9 features)')

    Xr, yr, fr, idsr = dataset_rico(df)
    rico = walk_forward(Xr, yr, fr, idsr, cuotas, 'RICO (17 features)')

    print('\n' + '=' * 74)
    print(f"{'variante':22s} {'n':>6} {'log-loss':>9} {'precisión':>10} "
          f"{'ratio disp':>11} {'corr mkt':>9}")
    print('=' * 74)
    for r in (base, rico):
        if r:
            print(f"{r['etiqueta']:22s} {r['n']:6d} {r['log_loss']:9.4f} "
                  f"{r['precision']:10.4f} {r['ratio_dispersion']:11.3f} "
                  f"{r['corr_mercado']:9.4f}")
    if base and rico:
        print(f"{'MERCADO':22s} {base['n']:6d} {base['log_loss_mercado']:9.4f} "
              f"{base['precision_mercado']:10.4f} {1.0:11.3f} {1.0:9.4f}")
        d_ll = base['log_loss'] - rico['log_loss']
        d_ac = rico['precision'] - base['precision']
        print('=' * 74)
        print(f"\nΔ log-loss (positivo = mejora): {d_ll:+.4f}")
        print(f"Δ precisión (positivo = mejora): {d_ac:+.4f}")
        print(f"Δ ratio de dispersión          : "
              f"{rico['ratio_dispersion'] - base['ratio_dispersion']:+.3f}")
        veredicto = 'ADOPTAR' if (d_ll > 0 and d_ac > 0) else \
                    ('ADOPTAR (log-loss)' if d_ll > 0.002 else 'RECHAZAR')
        print(f"\nVEREDICTO: {veredicto}")
        json.dump({'base': base, 'rico': rico, 'veredicto': veredicto},
                  open('_v79_mlb_features.json', 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
