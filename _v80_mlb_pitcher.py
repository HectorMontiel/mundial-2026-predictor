#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — Calidad REAL del abridor en MLB. Se adopta solo si mide mejor.

De dónde viene
--------------
La v79 dejó el diagnóstico cerrado y la puerta abierta: el modelo de MLB
comprime el abanico a la mitad del mercado (ratio de dispersión 0,527 con dos
vectores distintos de features de EQUIPO), y las ocho features enriquecidas que
se probaron —abridor encogido, factor de parque, ELO por margen— no movieron
ese ratio ni una milésima. La conclusión fue que el techo no está en cómo se
combinan las estadísticas de equipo, sino en que las estadísticas de equipo no
dan para más. Lo que faltaba era la línea real del abridor.

Se dio por inviable porque parecía exigir un game log por lanzador (~900 por
temporada). **Era falso**: `/api/v1/stats?stats=season&group=pitching` devuelve
los 873 lanzadores de una temporada en 1,2 s. Trece temporadas ya están
descargadas en `mlb_pitchers_temporada.csv.gz` (10.421 filas, 2.850 lanzadores).

Cómo se usa sin fuga
--------------------
La línea de una temporada solo se conoce cuando termina. Para un partido de la
temporada Y se usa el ACUMULADO DE TODAS LAS TEMPORADAS ANTERIORES a Y, que es
información disponible antes del primer lanzamiento de Y. Cero fuga.

Se agrega por entradas lanzadas y se encoge hacia la media de la liga, porque
un lanzador con 12 entradas en su carrera no merece el mismo crédito que uno
con 900:

    tasa = (sucesos_carrera + k · tasa_liga) / (entradas_carrera + k)

Detalle que arruina el cálculo si se pasa por alto: `inningsPitched` viene en
notación de béisbol, «198.1» son 198 entradas Y UN OUT, no 198,1. Leerlo como
decimal deforma todas las tasas.
"""
import json
import logging
import warnings

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('mlb-pit')

RUTA = 'historico_mlb.csv'
PIT = 'mlb_pitchers_temporada.csv.gz'
N_FOLDS, INICIO, MIN_TEST = 5, 0.45, 300
MA = 10
K_SHRINK = 120.0          # entradas de encogimiento hacia la media de la liga


def ip_real(x):
    """«198.1» -> 198 + 1/3. La parte decimal son OUTS, no décimas."""
    v = pd.to_numeric(x, errors='coerce')
    ent = np.floor(v)
    outs = np.round((v - ent) * 10)
    return ent + outs / 3.0


def tabla_lanzadores():
    """pitcher -> {anio: acumulado de TODAS las temporadas anteriores}."""
    d = pd.read_csv(PIT)
    d['ip'] = ip_real(d['ip'])
    d = d[d['ip'] > 0]
    # sucesos absolutos (no tasas) para poder acumular
    d['er'] = d['era'] * d['ip'] / 9.0        # carreras limpias implícitas
    d = d.sort_values(['pitcher', 'anio'])

    # acumulado ESTRICTAMENTE anterior a cada año
    g = d.groupby('pitcher', sort=False)
    for c in ('ip', 'er', 'so', 'bb', 'hr'):
        d[f'cum_{c}'] = g[c].cumsum() - d[c]
    d['cum_gs'] = g['gs'].cumsum() - d['gs']

    # media de liga por año (con lo anterior a ese año)
    liga = {}
    for a in sorted(d['anio'].unique()):
        prev = d[d['anio'] < a]
        if prev['ip'].sum() > 0:
            liga[a] = {
                'era': float(prev['er'].sum() / prev['ip'].sum() * 9.0),
                'k9': float(prev['so'].sum() / prev['ip'].sum() * 9.0),
                'bb9': float(prev['bb'].sum() / prev['ip'].sum() * 9.0),
                'hr9': float(prev['hr'].sum() / prev['ip'].sum() * 9.0)}
        else:
            liga[a] = {'era': 4.10, 'k9': 8.0, 'bb9': 3.1, 'hr9': 1.2}

    tabla = {}
    for r in d.itertuples(index=False):
        L = liga.get(r.anio, {'era': 4.10, 'k9': 8.0, 'bb9': 3.1, 'hr9': 1.2})
        ip_c = float(r.cum_ip)
        def _t(suceso, base):
            return (float(suceso) + K_SHRINK * base / 9.0) / (ip_c + K_SHRINK) * 9.0
        tabla[(str(r.pitcher), int(r.anio))] = {
            'era': _t(r.cum_er, L['era']), 'k9': _t(r.cum_so, L['k9']),
            'bb9': _t(r.cum_bb, L['bb9']), 'hr9': _t(r.cum_hr, L['hr9']),
            'ip': ip_c, 'gs': float(r.cum_gs), 'liga': L}
    log.info(f'[pitchers] {len(tabla)} pares (lanzador, año) con historia previa')
    return tabla, liga


def dataset(df, tabla, liga, con_pitcher: bool):
    """Las 9 features de producción, opcionalmente + 6 de calidad de abridor."""
    df = df.sort_values('date').reset_index(drop=True)
    elo, rs, ra, streak, ult, pit_ra = {}, {}, {}, {}, {}, {}
    X, y, fechas, ids = [], [], [], []

    for r in df.itertuples(index=False):
        h, a, fecha = r.home_team, r.away_team, r.date
        anio = fecha.year
        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)

        def _m(d, k, dv):
            v = d.get(k, [])
            return float(np.mean(v[-MA:])) if v else dv
        rs_h, rs_a = _m(rs, h, 4.5), _m(rs, a, 4.5)
        ra_h, ra_a = _m(ra, h, 4.5), _m(ra, a, 4.5)
        rest_h = min((fecha - ult[h]).days, 7) if h in ult else 3
        rest_a = min((fecha - ult[a]).days, 7) if a in ult else 3
        pr_h = (float(np.mean(pit_ra.get(r.home_pitcher, [])[-5:]))
                if pit_ra.get(r.home_pitcher) else 4.5)
        pr_a = (float(np.mean(pit_ra.get(r.away_pitcher, [])[-5:]))
                if pit_ra.get(r.away_pitcher) else 4.5)

        if all(len(rs.get(t, [])) >= 5 for t in (h, a)):
            fila = [(eh - ea) / 100.0, (rs_h - rs_a) / 3.0, (ra_h - ra_a) / 3.0,
                    (streak.get(h, 0) - streak.get(a, 0)) / 5.0,
                    (rest_h - rest_a) / 5.0, (pr_h - pr_a) / 3.0,
                    (rs_h + rs_a) / 9.0, (ra_h + ra_a) / 9.0, (pr_h + pr_a) / 9.0]
            if con_pitcher:
                L = liga.get(anio, {'era': 4.10, 'k9': 8.0, 'bb9': 3.1, 'hr9': 1.2})
                neutro = {'era': L['era'], 'k9': L['k9'], 'bb9': L['bb9'],
                          'hr9': L['hr9'], 'ip': 0.0, 'gs': 0.0}
                ph = tabla.get((str(r.home_pitcher), anio), neutro)
                pa = tabla.get((str(r.away_pitcher), anio), neutro)
                fila += [
                    (ph['era'] - pa['era']) / 2.0,
                    (ph['k9'] - pa['k9']) / 3.0,
                    (ph['bb9'] - pa['bb9']) / 1.5,
                    (ph['hr9'] - pa['hr9']) / 0.8,
                    (ph['era'] + pa['era']) / 9.0,
                    (min(ph['ip'], 900) + min(pa['ip'], 900)) / 1800.0,
                ]
            X.append(fila)
            y.append(int(r.home_runs > r.away_runs))
            fechas.append(fecha)
            ids.append((fecha, str(h), str(a)))

        gh, ga = float(r.home_runs), float(r.away_runs)
        rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
        rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
        for pid, conc in ((r.home_pitcher, ga), (r.away_pitcher, gh)):
            if isinstance(pid, str) and pid:
                pit_ra.setdefault(pid, []).append(conc)
        for eq, gano in ((h, gh > ga), (a, ga > gh)):
            streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else \
                min(streak.get(eq, 0), 0) - 1
        e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
        s_h = 1.0 if gh > ga else 0.0
        elo[h] = eh + 20 * (s_h - e_h)
        elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
        ult[h] = ult[a] = fecha

    return (np.asarray(X, float), np.asarray(y, int),
            pd.Series(fechas).reset_index(drop=True), ids)


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
        return None
    bordes = np.linspace(int(len(con) * INICIO), len(con), N_FOLDS + 1).astype(int)
    # v80 — LAS CUOTAS SE RECOGEN EN EL MISMO BUCLE QUE EMITE LA PREDICCIÓN.
    #
    # La primera versión de la prueba de rentabilidad las reconstruía después,
    # filtrando la lista completa de cuotas y emparejándola por posición con P.
    # Eso está mal: `walk_forward` solo emite desde `bordes[k]`, no desde el
    # índice 0, así que P[i] quedaba pegado a la cuota de otro partido.
    # Resultado: ROI +31,75 % con p5 +26,43 %, imposible en un mercado como el
    # de MLB. Es EXACTAMENTE la desalineación que fabricó el +37,68 % en la
    # v78, cometida otra vez y por el mismo motivo: adivinar el orden en vez de
    # arrastrarlo.
    #
    # Recogiendo `ch`/`ca` aquí dentro, junto a `P` y `Y`, no hay orden que
    # adivinar: los tres salen de la misma iteración.
    P, Y, M, CH, CA = [], [], [], [], []
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
            CH.append(float(c[0])); CA.append(float(c[1]))
            ih, ia = 1 / c[0], 1 / c[1]
            M.append(ih / (ih + ia))
    P, Y, M = np.array(P), np.array(Y), np.array(M)
    CH, CA = np.array(CH), np.array(CA)
    ll = lambda p: float(-(Y * np.log(p.clip(1e-6, 1 - 1e-6)) +
                           (1 - Y) * np.log((1 - p).clip(1e-6, 1 - 1e-6))).mean())
    res = {'etiqueta': etiqueta, 'n': int(len(P)), 'log_loss': round(ll(P), 4),
           'log_loss_mercado': round(ll(M), 4),
           'precision': round(float(((P >= .5).astype(int) == Y).mean()), 4),
           'precision_mercado': round(float(((M >= .5).astype(int) == Y).mean()), 4),
           'std': round(float(P.std()), 4),
           'ratio_dispersion': round(float(P.std() / max(M.std(), 1e-9)), 3),
           'corr_mercado': round(float(np.corrcoef(P, M)[0, 1]), 4)}
    # GUARDIA DE ALINEACIÓN (obligatoria desde la v78): unas cuotas de cierre
    # reales, por malas que sean, siempre baten al azar. Si el log-loss del
    # mercado supera ln(2), están pegadas al partido equivocado.
    res['alineado'] = bool(res['log_loss_mercado'] < float(np.log(2)))
    if not res['alineado']:
        log.error(f"{etiqueta}: CUOTAS DESALINEADAS "
                  f"(log-loss del mercado {res['log_loss_mercado']} > "
                  f"{np.log(2):.4f}) — cualquier ROI de aquí es ficticio")
    log.info(f"{etiqueta}: n={res['n']} ll={res['log_loss']} "
             f"acc={res['precision']} ratio={res['ratio_dispersion']}")
    return res, P, Y, CH, CA


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

    tabla, liga = tabla_lanzadores()

    Xb, yb, fb, idb = dataset(df, tabla, liga, con_pitcher=False)
    base = walk_forward(Xb, yb, fb, idb, cuotas, 'BASE (9, equipo)')
    Xp, yp, fp, idp = dataset(df, tabla, liga, con_pitcher=True)
    pit = walk_forward(Xp, yp, fp, idp, cuotas, 'CON ABRIDOR (15)')

    if not base or not pit:
        print('sin datos suficientes')
        return
    (rb, Pb, Yb, CHb, CAb), (rp, Pp, Yp, CHp, CAp) = base, pit

    print('\n' + '=' * 78)
    print(f"{'variante':22s} {'n':>6} {'log-loss':>9} {'precision':>10} "
          f"{'ratio disp':>11} {'corr mkt':>9}")
    print('=' * 78)
    for r in (rb, rp):
        print(f"{r['etiqueta']:22s} {r['n']:6d} {r['log_loss']:9.4f} "
              f"{r['precision']:10.4f} {r['ratio_dispersion']:11.3f} "
              f"{r['corr_mercado']:9.4f}")
    print(f"{'MERCADO':22s} {rb['n']:6d} {rb['log_loss_mercado']:9.4f} "
          f"{rb['precision_mercado']:10.4f} {1.0:11.3f} {1.0:9.4f}")
    print('=' * 78)

    # bootstrap PAREADO (misma lección que el tenis en la v79)
    n = min(len(Pb), len(Pp))
    Y = Yb[:n]
    llf = lambda p: -(Y * np.log(p[:n].clip(1e-6, 1 - 1e-6)) +
                      (1 - Y) * np.log((1 - p[:n]).clip(1e-6, 1 - 1e-6)))
    d = llf(Pb) - llf(Pp)
    rng = np.random.default_rng(42)
    idx = rng.integers(0, n, size=(5000, n))
    mu = d[idx].mean(axis=1)
    p5, p95 = np.percentile(mu, [5, 95])
    print(f"\nDiferencia de log-loss a favor del abridor: {d.mean():+.5f}")
    print(f"IC 90 % bootstrap pareado                 : [{p5:+.5f}, {p95:+.5f}]")
    print(f"fraccion de remuestreos con mejora        : {(mu > 0).mean():.1%}")
    veredicto = 'ADOPTAR' if p5 > 0 else 'NO ADOPTAR (el IC toca el cero)'
    print(f"\nVEREDICTO por log-loss: {veredicto}")

    # ---- lo que de verdad decide en este proyecto: ROI y p5 --------------
    # El log-loss mide el vector entero; la rentabilidad depende solo de los
    # picks que superan los filtros. Son preguntas distintas y aquí importa la
    # segunda: es el criterio que dejó fuera el Over/Under en la v44 y a
    # tenis/MLB de la Capa 1 en la v78.
    print('\n' + '=' * 78)
    print('RENTABILIDAD con los umbrales de producción (prob>0,58 · EV>3 % · cuota>1,50)')
    print('=' * 78)
    print(f"{'variante':22s} {'n':>6} {'ROI':>9} {'p5':>9} {'acierto':>9}")
    print('-' * 78)
    roi_res = {}
    for etiqueta, P, Yv, CH, CA, r_ in (
            ('BASE (9, equipo)', Pb, Yb, CHb, CAb, rb),
            ('CON ABRIDOR (15)', Pp, Yp, CHp, CAp, rp)):
        if not r_.get('alineado'):
            print(f'{etiqueta:22s}   OMITIDO: cuotas desalineadas')
            continue
        gan = []
        for i in range(len(P)):
            for prob, cuota, acierto in ((P[i], CH[i], Yv[i] == 1),
                                         (1 - P[i], CA[i], Yv[i] == 0)):
                if prob > 0.58 and cuota * prob - 1 > 0.03 and cuota > 1.50:
                    gan.append(cuota - 1.0 if acierto else -1.0)
        if len(gan) < 60:
            print(f'{etiqueta:22s} {len(gan):6d}   muestra insuficiente')
            continue
        g = np.array(gan, float)
        rng2 = np.random.default_rng(3)
        bs = g[rng2.integers(0, len(g), size=(5000, len(g)))].mean(axis=1)
        p5r = float(np.percentile(bs, 5))
        roi_res[etiqueta] = {'n': len(g), 'roi': float(g.mean()), 'p5': p5r,
                             'hit': float((g > 0).mean())}
        print(f'{etiqueta:22s} {len(g):6d} {g.mean():9.2%} {p5r:9.2%} '
              f'{float((g>0).mean()):9.1%}')
    print('=' * 78)

    # Cordura: el MERCADO apostado contra sí mismo debe rondar el −margen.
    # Si el ROI del modelo se dispara muy por encima de lo plausible, es que
    # algo sigue mal pegado.
    if roi_res:
        peor = max(r['roi'] for r in roi_res.values())
        if peor > 0.15:
            print(f'\n⚠️  ROI de {peor:.1%}: implausible en MLB. Revisar '
                  f'alineación ANTES de creérselo (lección v78).')

    json.dump({'base': rb, 'con_pitcher': rp,
               'delta_medio': round(float(d.mean()), 5),
               'ic90': [round(float(p5), 5), round(float(p95), 5)],
               'frac_positiva': round(float((mu > 0).mean()), 4),
               'veredicto': veredicto},
              open('_v80_mlb_pitcher.json', 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)


if __name__ == '__main__':
    main()
