#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — REVISIÓN ESCÉPTICA de `_v373_contexto.py` (H3, contexto de equipo).

Regla bajo examen («ganador 1,60 con respaldo del aprendiz»):
  patas gana local / gana visita con cuota en [1,60; 2,10]; p_cal = casa
  calibrada (HGB sobre logit(p_c) + tipo); p_log = logística walk-forward con
  contexto; se apuesta la de mayor p_c entre las que cumplen p_log − p_cal ≥ u
  (u = 0,02 en la recomendada).

Qué hace este script (sólo lee; escribe `_v373_contexto_revision.json`):
  0. Reconstruye las patas con las MISMAS funciones del original (importa el
     módulo) y comprueba de dónde salen las cuotas (formato main = Bet365
     ANTES del cierre / Pinnacle de CIERRE; formato new = media de CIERRE /
     Pinnacle de CIERRE).
  1. Fugas en los rasgos: perturba resultados/cuotas (a) del propio partido y
     (b) de todo lo posterior a 2019-07-01, recalcula los rasgos y mira si los
     rasgos de los partidos afectados (a) o anteriores (b) cambian.
  2. Reproduce p_log / p_cal (walk-forward por julio) y las cifras de la regla.
  3. Controles que el original no hizo:
       · aprendiz NULO (misma logística SIN contexto: logit(p_c), tipo, faltantes);
       · NULO + liga; casa calibrada POR LIGA; contexto + liga;
       · contexto sin los rasgos que miran el calendario/temporada futura
         (próximo partido, copa después, avance).
  4. Otros cortes temporales: walk-forward por enero, 70/30 congelado, y la
     regla temporada por temporada; también por formato de cuota.
  5. Umbrales y pisos vecinos; ganancia por $100 con p5/p95.
  6. e_v361: «avance» y la regla «domina a puerta (ew +3)».
"""
import importlib.util as iu
import json
import os
import sys
import time

import numpy as np
import pandas as pd

T0 = time.time()
RAIZ = os.path.dirname(os.path.abspath(__file__))
os.chdir(RAIZ)
sys.path.insert(0, RAIZ)
_s = iu.spec_from_file_location('ctx373', os.path.join(RAIZ, '_v373_contexto.py'))
C = iu.module_from_spec(_s)
_s.loader.exec_module(C)

NB = 400
D2023 = np.datetime64('2023-07-01')
lg = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))


def log(*a):
    print('[%5.0fs]' % (time.time() - T0), *a, flush=True)


def r4(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 4)


# ============================================================ medición propia
def medir(z, sel, pcal='p_cal', periodos_extra=None, semilla=0, min_n=60):
    """La casa elige en z (una pata por partido, la de mayor p_c) contra la
    misma elección restringida a `sel`. Bootstrap Poisson por partido."""
    rng = np.random.default_rng(semilla)
    b = z.sort_values('p_c', ascending=False, kind='mergesort').drop_duplicates('mid').sort_values('mid')
    q = z[np.asarray(sel, dtype=bool)]
    q = q.sort_values('p_c', ascending=False, kind='mergesort').drop_duplicates('mid')
    if len(q) < min_n:
        return {'n': int(len(q))}
    idx = pd.Index(b.mid.values)
    pos = idx.get_indexer(q.mid.values)
    n = len(b)
    has, ok, gan, exk, pc, cu = (np.zeros(n, np.float64) for _ in range(6))
    has[pos] = 1
    ok[pos], gan[pos] = q.ok.values, q.gan.values
    exk[pos] = (q.ok - q[pcal]).values
    pc[pos], cu[pos] = q.p_c.values, q.cuota.values
    bok, bgan, bexk = b.ok.values, b.gan.values, (b.ok - b[pcal]).values
    bpc, bcu = b.p_c.values, b.cuota.values
    fb = b.fecha.values.astype('datetime64[D]')
    f = np.sort(q.fecha.values.astype('datetime64[D]'))
    fmin, corte = f[0], f[len(f) // 2]
    per = {'A': (fb >= fmin) & (fb < corte), 'B': fb >= corte, '2023': fb >= D2023, 'todo': fb >= fmin}
    for k, (ini, fin) in (periodos_extra or {}).items():
        per[k] = (fb >= np.datetime64(ini)) & (fb < np.datetime64(fin))
    W = rng.poisson(1.0, size=(NB, n)).astype(np.float64)
    out = {'corte_AB': str(corte), 'desde': str(fmin)}
    for k, mm in per.items():
        mf = mm.astype(np.float64)
        V = np.column_stack([has * mf, ok * mf, gan * mf, exk * mf, mf, bok * mf, bgan * mf, bexk * mf])
        S = V.sum(0)
        if S[0] < 30:
            out[k] = {'n': int(S[0])}
            continue
        Rb = W @ V
        with np.errstate(invalid='ignore', divide='ignore'):
            acc, bacc = Rb[:, 1] / Rb[:, 0], Rb[:, 5] / Rb[:, 4]
            ek, bek = Rb[:, 3] / Rb[:, 0], Rb[:, 7] / Rb[:, 4]
            ga = Rb[:, 2] / Rb[:, 0]
        sel_ = has.astype(bool) & mm
        dias = len(np.unique(fb[mm]))
        out[k] = {'n': int(S[0]), 'patas_dia': round(float(S[0] / max(dias, 1)), 2),
                  'acierto': r4(S[1] / S[0]), 'base': r4(S[5] / S[4]), 'dif': r4(S[1] / S[0] - S[5] / S[4]),
                  'dif_p5': r4(np.nanpercentile(acc - bacc, 5)),
                  'p_c_regla': r4(pc[sel_].mean()), 'p_c_base': r4(bpc[mm].mean()),
                  'exc_cal': r4(S[3] / S[0]), 'exc_cal_base': r4(S[7] / S[4]),
                  'dif_exc_cal': r4(S[3] / S[0] - S[7] / S[4]),
                  'dif_exc_cal_p5': r4(np.nanpercentile(ek - bek, 5)),
                  'cuota': round(float(cu[sel_].mean()), 3), 'cuota_base': round(float(bcu[mm].mean()), 3),
                  'gan_100': round(100 * float(S[2] / S[0]), 2),
                  'gan_p5': round(100 * float(np.nanpercentile(ga, 5)), 2),
                  'gan_p95': round(100 * float(np.nanpercentile(ga, 95)), 2),
                  'gan_base_100': round(100 * float(S[6] / S[4]), 2)}
    A, B = out.get('A', {}), out.get('B', {})
    if 'dif_p5' in A and 'dif_p5' in B:
        out['pasa_acierto'] = bool(A['dif_p5'] > 0 and B['dif_p5'] > 0)
        out['pasa_cal'] = bool(A['dif_exc_cal_p5'] > 0 and B['dif_exc_cal_p5'] > 0)
        out['pasa'] = out['pasa_acierto'] and out['pasa_cal']
    return out


def corto(r, k='todo'):
    x = r.get(k, {})
    if 'acierto' not in x:
        return 'n %s' % x.get('n', r.get('n'))
    return ('n %5d %.2f/d acierto %.3f base %.3f dif %+.3f(p5 %+.3f) exc_cal %+.3f(p5 %+.3f) '
            'p_c %.3f/%.3f cuota %.2f/%.2f gan %+.2f [%+.2f,%+.2f] base %+.2f' % (
                x['n'], x['patas_dia'], x['acierto'], x['base'], x['dif'], x['dif_p5'], x['dif_exc_cal'],
                x['dif_exc_cal_p5'], x['p_c_regla'], x['p_c_base'], x['cuota'], x['cuota_base'], x['gan_100'],
                x['gan_p5'], x['gan_p95'], x['gan_base_100']))


# ============================================================ aprendices
def cortes(f, esquema):
    if esquema == 'julio':
        for Y in range(2012, 2027):
            ini, fin = np.datetime64('%d-07-01' % Y), np.datetime64('%d-07-01' % (Y + 1))
            tr, te = f < ini, (f >= ini) & (f < fin)
            if te.sum() == 0 or tr.sum() < 20000:
                continue
            yield tr, te
    elif esquema == 'enero':
        for Y in range(2013, 2027):
            ini, fin = np.datetime64('%d-01-01' % Y), np.datetime64('%d-01-01' % (Y + 1))
            tr, te = f < ini, (f >= ini) & (f < fin)
            if te.sum() == 0 or tr.sum() < 20000:
                continue
            yield tr, te
    elif esquema == '70/30':
        corte = np.sort(f)[int(0.7 * len(f))]
        yield f < corte, f >= corte


def wf_log(X, y, f, esquema):
    from sklearn.linear_model import LogisticRegression
    out = np.full(len(y), np.nan)
    for tr, te in cortes(f, esquema):
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
        lr = LogisticRegression(C=0.5, max_iter=400)
        lr.fit((X[tr] - mu) / sd, y[tr])
        out[te] = lr.predict_proba((X[te] - mu) / sd)[:, 1]
    return out


def wf_cal(X, y, f, esquema, cat, mono):
    from sklearn.ensemble import HistGradientBoostingClassifier
    out = np.full(len(y), np.nan)
    for tr, te in cortes(f, esquema):
        ctl = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=8,
                                             min_samples_leaf=1000, max_bins=64, categorical_features=cat,
                                             monotonic_cst=mono, early_stopping=False, random_state=0)
        ctl.fit(X[tr], y[tr])
        out[te] = ctl.predict_proba(X[te])[:, 1]
    return out


def matrices(P, quitar=()):
    """Las mismas matrices que `C.aprendiz` (Xa para la casa calibrada, Xl para
    la logística). `quitar`: rasgos de FEAT que se dejan fuera (ablación)."""
    tipos = sorted(P.tipo.unique())
    feat = [f for f in C.FEAT if f not in quitar]
    num = ['T_' + f for f in feat] + ['R_' + f for f in feat]
    Xa = np.column_stack([lg(P.p_c.values), P.tipo.map({t: i for i, t in enumerate(tipos)}).values]
                         + [P[c].values for c in num]).astype(np.float32)
    lado = np.where(P.familia == 'goles', 0.0, 1.0)
    signo = np.where(P.tipo == 'menos 2,5', -1.0, 1.0)
    D = np.column_stack([(P.tipo == t).values.astype(float) for t in tipos])
    Xn = np.nan_to_num(Xa[:, 2:].astype(float))
    gsum = np.column_stack([(P.T_l5_gt + P.R_l5_gt).fillna(5.4).values,
                            (P.T_l5_sott + P.R_l5_sott).fillna(17).values,
                            ((P.T_desc <= 3) & (P.R_desc <= 3)).values.astype(float),
                            ((P.T_pj <= 5) & (P.R_pj <= 5)).values.astype(float)])
    falta = np.column_stack([P[c].isna().values for c in ('T_desc', 'R_desc', 'T_l5_pts', 'R_l5_pts',
                                                          'T_l5_sotd', 'T_pos', 'R_pos')]).astype(float)
    Xl = np.column_stack([lg(P.p_c.values), D, Xn * lado[:, None], gsum * signo[:, None] * (1 - lado)[:, None],
                          falta])
    return Xa, Xl, D, falta


# ============================================================ fugas en rasgos
COLF = ['h_' + f for f in C.FEAT] + ['a_' + f for f in C.FEAT]


def comparar(m1, m2, mids):
    a = m1.set_index('mid').loc[mids, COLF].astype(float)
    b = m2.set_index('mid').loc[mids, COLF].astype(float)
    dif = {}
    for c in COLF:
        x, y = a[c].values, b[c].values
        distinto = ~((x == y) | (np.isnan(x) & np.isnan(y)))
        if distinto.any():
            dif[c] = int(distinto.sum())
    return dif


def prueba_fugas(d, citas, m):
    rng = np.random.default_rng(7)
    R = {}
    # (a) el propio partido: se cambian goles, tiros y cuotas de TODOS los
    # partidos de UNA fecha al azar por liga y temporada (así ningún partido
    # perturbado tiene otro perturbado antes en su temporada)
    d2 = d.copy()
    elegidas = {}
    for (lgq, tq), gg in d2.groupby(['liga', 'temporada']):
        fu = gg.fecha.unique()
        elegidas[(lgq, tq)] = fu[rng.integers(len(fu))]
    sel = np.array([fe == elegidas[(lgq, tq)] for lgq, tq, fe in zip(d2.liga, d2.temporada, d2.fecha)])
    ix = d2.index.values[sel]
    for c in ('home_goals', 'away_goals'):
        d2.loc[ix, c] = rng.integers(0, 6, size=len(ix))
    for c in ('home_shots_on', 'away_shots_on'):
        d2.loc[ix, c] = rng.integers(0, 12, size=len(ix))
    for c in ('odd_home', 'odd_draw', 'odd_away'):
        d2.loc[ix, c] = d2.loc[ix, c] * rng.uniform(0.7, 1.4, size=len(ix))
    m2 = C.rasgos(d2, citas)
    dif = comparar(m, m2, d.loc[ix, 'mid'].values)
    R['mismo_partido'] = {'partidos_perturbados': int(len(ix)), 'rasgos_que_cambian': dif,
                          'veredicto': 'sin fuga' if not dif else 'FUGA'}
    log('fugas (a) mismo partido:', R['mismo_partido']['veredicto'], dif)
    # (b) todo lo posterior a 2019-07-01: resultados, tiros y cuotas al azar
    d3 = d.copy()
    fut = d3.fecha >= pd.Timestamp('2019-07-01')
    k = int(fut.sum())
    for c in ('home_goals', 'away_goals'):
        d3.loc[fut, c] = rng.integers(0, 6, size=k)
    for c in ('home_shots_on', 'away_shots_on'):
        d3.loc[fut, c] = rng.integers(0, 12, size=k)
    for c in ('odd_home', 'odd_draw', 'odd_away'):
        d3.loc[fut, c] = d3.loc[fut, c] * rng.uniform(0.7, 1.4, size=k)
    m3 = C.rasgos(d3, citas)
    dif = comparar(m, m3, d.loc[~fut, 'mid'].values)
    R['futuro'] = {'partidos_perturbados': k, 'partidos_comparados': int((~fut).sum()),
                   'rasgos_que_cambian': dif, 'veredicto': 'sin fuga' if not dif else 'FUGA'}
    log('fugas (b) futuro:', R['futuro']['veredicto'], dif)
    R['nota'] = ('Los rasgos no dependen de resultados ni cuotas del propio partido ni del futuro. Sí usan '
                 'el CALENDARIO futuro (días al próximo partido, copa en ≤5 días después), el corte de '
                 'temporada por parones (fechas futuras), n.º de equipos de la temporada y jornadas del '
                 'formato (mediana de todas las temporadas): se miden aparte quitándolos.')
    return R


# ============================================================ e_v361
def revisar_e():
    e = pd.read_pickle(C.RUTA_E)
    R = {}
    # «avance»: ¿con el máximo de la temporada (incluido lo que aún no se ha jugado)?
    g = e.groupby(['liga', 'temporada'])
    mx = g.n_prev.transform('max')
    ratio = (e.avance / ((e.n_prev) / mx.replace(0, np.nan))).replace([np.inf, -np.inf], np.nan)
    R['avance'] = {
        'corr_avance_vs_nprev_sobre_max_temporada': r4(np.corrcoef(e.avance.fillna(0), (e.n_prev / mx).fillna(0))[0, 1]),
        'mediana_avance_sobre_(n_prev/max_temporada)': r4(ratio.median()),
        'temporada_en_curso_avance_max_ultimo_dia': {}}
    ult = e.fecha.max()
    cur = e[e.fecha >= ult - pd.Timedelta(days=10)]
    for lgq, gg in cur.groupby('liga'):
        R['avance']['temporada_en_curso_avance_max_ultimo_dia'][lgq] = r4(gg.avance.max())
    # ¿ew sólo con lo anterior? ew[i+1] ≈ (1−α)ew[i] + α·a_puerta[i]  vs  ew[i] ≈ (1−α)ew[i−1] + α·a_puerta[i]
    s = e.sort_values(['liga', 'equipo', 'fecha'])
    gq = s.groupby(['liga', 'equipo'])
    ew, ap = s.ew_a_puerta.values, s.a_puerta.values
    ew_sig = gq.ew_a_puerta.shift(-1).values
    ew_ant = gq.ew_a_puerta.shift(1).values
    ok1 = np.isfinite(ew) & np.isfinite(ap) & np.isfinite(ew_sig)
    ok2 = np.isfinite(ew) & np.isfinite(ap) & np.isfinite(ew_ant)

    def ajuste(yv, x1, x2):
        X = np.column_stack([x1, x2])
        coef, res, *_ = np.linalg.lstsq(X, yv, rcond=None)
        r = yv - X @ coef
        return [round(float(c), 4) for c in coef], round(float(1 - r.var() / yv.var()), 4)

    R['ew_solo_pasado'] = {
        'ew_siguiente ~ ew + a_puerta_del_partido (coef, R2)': ajuste(ew_sig[ok1], ew[ok1], ap[ok1]),
        'ew ~ ew_anterior + a_puerta_del_partido (coef, R2)': ajuste(ew[ok2], ew_ant[ok2], ap[ok2]),
        'nota': 'si ew incluyera el propio partido, el 2.º ajuste daría R2≈1 con coef. de a_puerta > 0'}
    # regla «domina a puerta (ew +3)», doble 1,45-1,95, por temporada
    e = e[(e.odd_w > 1) & (e.odd_d > 1) & (e.odd_l > 1)].copy()
    sm = 1 / e.odd_w + 1 / e.odd_d + 1 / e.odd_l
    e['mid'] = e.liga + '|' + e.mid.astype(str)
    pw, pe = (1 / e.odd_w) / sm, (1 / e.odd_d) / sm
    filas = []
    for tipo, fam, c, p, okk in (('gana', 'ganador', e.odd_w, pw, e.gf > e.gc),
                                 ('no pierde', 'doble', 1 / (1 / e.odd_w + 1 / e.odd_d), pw + pe, e.gf >= e.gc)):
        filas.append(e.assign(tipo=tipo, familia=fam, cuota=c.values, p_c=p.values, ok=okk.astype(float).values))
    P = pd.concat(filas, ignore_index=True)
    P['gan'] = np.where(P.ok == 1, P.cuota - 1, -1.0)
    P['p_cal'] = P.p_c          # sin casa calibrada aquí: exc_cal = exceso sobre la proporcional
    dom_p = (P.ew_a_puerta - P.ew_a_puerta_c) - (P.r_ew_a_puerta - P.r_ew_a_puerta_c)
    temporadas = {'%d-%02d' % (y, (y + 1) % 100): ('%d-07-01' % y, '%d-07-01' % (y + 1)) for y in range(2020, 2027)}
    R['domina_a_puerta'] = {}
    for fam, piso in (('doble', 1.45), ('doble', 1.60), ('ganador', 1.60)):
        z = P[(P.familia == fam) & (P.cuota >= piso) & (P.cuota <= piso + 0.5)]
        msk = (dom_p.loc[z.index] >= 3).values
        r = medir(z, msk, pcal='p_cal', periodos_extra=temporadas, semilla=11)
        R['domina_a_puerta']['%s %.2f' % (fam, piso)] = r
        log('e_v361 domina a puerta %s %.2f:' % (fam, piso), corto(r))
        for k in temporadas:
            log('     %s %s' % (k, corto(r, k)))
    return R


# ============================================ 8. football-data crudo (main)
def seccion_fd(P, config):
    """Con los CSV crudos de football-data (_v308_fd, 2019-20→, 22 ligas main):
    · confirma que la casa es B365 ANTES del cierre y Pinnacle el CIERRE;
    · REF Pinnacle con PSH (simultáneo a B365) contra PSCH (cierre);
    · la regla del aprendiz cobrada al precio de CIERRE de Bet365 (B365C)
      y cuánto se mueve la cuota de sus patas entre el pre-cierre y el cierre."""
    import glob as _g
    import re as _re
    cod2liga = {}
    for k, v in config.LEAGUES.items():
        if v.get('formato') != 'main':
            continue
        for u in v.get('urls', []):
            mm = _re.search(r'/([A-Z]+\d?)\.csv', u)
            if mm:
                cod2liga[mm.group(1)] = k
    filas = []
    for fpath in sorted(_g.glob(os.path.join('_v308_fd', '*.csv'))):
        cod = os.path.basename(fpath).split('_')[0]
        if cod not in cod2liga:
            continue
        try:
            x = pd.read_csv(fpath, encoding='latin-1', low_memory=False)
        except Exception:          # noqa: BLE001
            continue
        need = ['Date', 'HomeTeam', 'AwayTeam', 'B365H', 'B365D', 'B365A', 'PSH', 'PSD', 'PSA', 'PSCH', 'PSCD',
                'PSCA', 'B365CH', 'B365CD', 'B365CA']
        for c in need:
            if c not in x:
                x[c] = np.nan
        x = x[need].copy()
        x['liga'] = cod2liga[cod]
        x['fecha'] = pd.to_datetime(x.Date, dayfirst=True, errors='coerce').dt.normalize()
        filas.append(x)
    if not filas:
        return {'error': 'sin _v308_fd'}
    X = pd.concat(filas, ignore_index=True).dropna(subset=['fecha'])
    X = X.drop_duplicates(['liga', 'fecha', 'HomeTeam', 'AwayTeam'])
    for c in X.columns:
        if c.startswith(('B365', 'PS')):
            X[c] = pd.to_numeric(X[c], errors='coerce')
    out = {'ligas': sorted(set(cod2liga.values()) & set(X.liga)), 'partidos_crudos': int(len(X))}
    return out, X


def seccion_fd_medir(z, X):
    """z: patas ganador main 1,60-2,10 con home_team/away_team; X: crudo."""
    out = {}
    k = z.merge(X.rename(columns={'HomeTeam': 'home_team', 'AwayTeam': 'away_team'}),
                on=['liga', 'fecha', 'home_team', 'away_team'], how='inner')
    k = k[k.lado != 'ninguno'].copy()
    loc = (k.lado == 'local').values
    pick = lambda h, a: np.where(loc, k[h].values, k[a].values)
    k['c_b365'] = pick('B365H', 'B365A')
    k['c_b365c'] = pick('B365CH', 'B365CA')

    def prop(h, d_, a):
        s = 1 / k[h] + 1 / k[d_] + 1 / k[a]
        return np.where(loc, (1 / k[h] / s).values, (1 / k[a] / s).values)

    k['p_psh'] = prop('PSH', 'PSD', 'PSA')
    k['p_psc'] = prop('PSCH', 'PSCD', 'PSCA')
    k['p_b365c'] = prop('B365CH', 'B365CD', 'B365CA')
    k['c_psc'] = pick('PSCH', 'PSCA')
    out['patas_unidas'] = int(len(k))
    out['desde'] = str(k.fecha.min().date()) if len(k) else None
    out['casa_es_B365_precierre (|cuota−B365|<0,005)'] = r4((np.abs(k.cuota - k.c_b365) < 0.005).mean())
    out['pinnacle_es_PSCH_cierre (|p_pin−p_PSC|<0,001)'] = r4((np.abs(k.p_pin - k.p_psc) < 0.001).mean())
    out['pinnacle_es_PSH_precierre (|p_pin−p_PSH|<0,001)'] = r4((np.abs(k.p_pin - k.p_psh) < 0.001).mean())
    k = k[np.isfinite(k.c_b365c) & np.isfinite(k.p_psh) & np.isfinite(k.p_psc)].copy()
    # gan al precio de CIERRE de Bet365
    kc = k.copy()
    kc['gan'] = np.where(kc.ok == 1, kc.c_b365c - 1, -1.0)
    reglas = {
        'base (casa elige)': np.ones(len(k), bool),
        'aprendiz: logística ≥ casa calibrada+2': (k.p_log - k.p_cal >= 0.02).values,
        'aprendiz: logística ≥ casa calibrada+0': (k.p_log - k.p_cal >= 0.0).values,
        'NULO ≥ casa calibrada+2': (k.p_nulo - k.p_cal >= 0.02).values,
        'REF Pinnacle CIERRE (PSCH) ≥ casa+2': (k.p_psc - k.p_c >= 0.02).values,
        'REF Pinnacle PRE-CIERRE (PSH, simultáneo) ≥ casa+2': (k.p_psh - k.p_c >= 0.02).values,
    }
    for nom, sel in reglas.items():
        r1 = medir(k, sel, semilla=21)
        r2 = medir(kc, sel, semilla=21)
        q = k[sel].sort_values('p_c', ascending=False, kind='mergesort').drop_duplicates('mid')
        b = k.sort_values('p_c', ascending=False, kind='mergesort').drop_duplicates('mid')
        mov = lambda t: r4((t.p_b365c - t.p_c).mean())
        out[nom] = {'precio_precierre_B365': r1.get('todo'), 'precio_cierre_B365': r2.get('todo'),
                    'mitades_precierre': {kk: r1.get(kk) for kk in ('A', 'B')},
                    'mov_prob_B365_precierre→cierre_regla': mov(q), 'mov_base': mov(b),
                    'cuota_cierre_media_regla': r4(q.c_b365c.mean())}
        log('[fd] %-50s pre: %s' % (nom[:50], corto(r1)))
        log('[fd] %-50s cie: %s | mov regla %s base %s' % ('', corto(r2), mov(q), mov(b)))
    return out


# ===================================================================== main
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import config
    FORMATO = {k: v.get('formato') for k, v in config.LEAGUES.items()}
    OUT = {'regla': 'ganador 1,60-2,10: la casa elige, sólo si p_log − p_cal ≥ u (u = 0,02 recomendada)'}

    d = C.cargar_ligas()
    d['temporada'] = C.temporadas(d)
    citas, _ = C.mapear_copas(d)
    m = C.rasgos(d.copy(), citas)
    P = C.patas(m)
    P['formato'] = P.liga.map(FORMATO).fillna('?')
    log('patas', len(P), 'partidos', P.mid.nunique())

    if '--solo-fd' in sys.argv:          # sólo la sección 8, añadida al json ya escrito
        f = P.fecha.values.astype('datetime64[D]')
        y = P.ok.values.astype(int)
        Xa, Xl, D, falta = matrices(P)
        P['p_cal'] = wf_cal(Xa[:, :2], y, f, 'julio', [1], [1, 0])
        P['p_cal'] = np.where(np.isnan(P.p_cal.values), P.p_c.values, P.p_cal.values)
        log('p_cal')
        P['p_log'] = wf_log(Xl, y, f, 'julio')
        log('p_log')
        P['p_nulo'] = wf_log(np.column_stack([Xl[:, 0], D, falta]), y, f, 'julio')
        log('p_nulo')
        nombres = m.set_index('mid')[['home_team', 'away_team']]
        zfd = P[(P.familia == 'ganador') & (P.cuota >= 1.60) & (P.cuota <= 2.10) &
                (P.formato == 'main')].join(nombres, on='mid')
        info, Xfd = seccion_fd(P, config)
        info.update(seccion_fd_medir(zfd, Xfd))
        J = json.load(open('_v373_contexto_revision.json', encoding='utf-8'))
        J['football_data_crudo'] = info
        json.dump(J, open('_v373_contexto_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
                  default=str)
        log('añadido football_data_crudo al json')
        return

    # ---- 0. de dónde salen las cuotas
    g = P[P.familia == 'ganador'].drop_duplicates('mid')
    OUT['cuotas'] = {
        'fuente': {'main': 'casa = Bet365 B365H/D/A (ANTES del cierre); Pinnacle = PSCH (CIERRE, respaldo PSH)',
                   'new': 'casa = AvgCH (media de CIERRE; respaldo PSCH, B365CH); Pinnacle = PSCH (CIERRE)'},
        'ligas_por_formato': {k: sorted(P[P.formato == k].liga.unique().tolist()) for k in P.formato.unique()},
        'partidos_por_formato': g.formato.value_counts().to_dict(),
        'pinnacle_disponible_por_formato': g.groupby('formato').p_pin.apply(lambda s: r4(s.notna().mean())).to_dict(),
        'casa_igual_a_pinnacle_por_formato': g.assign(
            ig=(np.abs(m.set_index('mid').loc[g.mid, 'odd_home'].values -
                       m.set_index('mid').loc[g.mid, 'odd_home_pin'].values) < 1e-9)).groupby(
            'formato').ig.mean().round(3).to_dict(),
        'tiros_sinteticos': ('en las ligas de formato new los tiros a puerta del histórico los rellena '
                             'CorrelatedSyntheticGenerator a partir de los GOLES del propio partido (no hay fuga: '
                             'los rasgos sólo usan partidos anteriores, pero «a puerta» ahí es goles + ruido)'),
        'uso_en_el_aprendiz': ('p_pin (Pinnacle) NO entra en el aprendiz ni en p_cal: sólo en la regla «REF». '
                               'Las cuotas de cierre sí entran como p_c en las ligas new (es el precio de la casa)')}

    # ---- 1. fugas en los rasgos
    OUT['fugas_rasgos'] = prueba_fugas(d, citas, m)
    del citas

    # ---- 2. aprendices
    f = P.fecha.values.astype('datetime64[D]')
    y = P.ok.values.astype(int)
    Xa, Xl, D, falta = matrices(P)
    ligas = sorted(P.liga.unique())
    Lh = np.column_stack([(P.liga == x).values.astype(float) for x in ligas])
    liga_cod = P.liga.map({x: i for i, x in enumerate(ligas)}).values.astype(np.float32)
    Xcal = Xa[:, :2]
    Xcal_l = np.column_stack([Xa[:, :2], liga_cod]).astype(np.float32)
    pred = {}
    pred['p_cal'] = wf_cal(Xcal, y, f, 'julio', [1], [1, 0])
    log('p_cal')
    pred['p_log'] = wf_log(Xl, y, f, 'julio')
    log('p_log (reproducción)')
    pred['p_nulo'] = wf_log(np.column_stack([Xl[:, 0], D, falta]), y, f, 'julio')
    log('p_nulo')
    pred['p_nulo_liga'] = wf_log(np.column_stack([Xl[:, 0], D, falta, Lh]), y, f, 'julio')
    log('p_nulo_liga')
    pred['p_cal_liga'] = wf_cal(Xcal_l, y, f, 'julio', [1, 2], [1, 0, 0])
    log('p_cal_liga')
    pred['p_log_liga'] = wf_log(np.column_stack([Xl, Lh]), y, f, 'julio')
    log('p_log_liga')
    _, Xl_sc, _, _ = matrices(P, quitar=('prox', 'copa_d', 'avance'))
    pred['p_log_sin_cal'] = wf_log(Xl_sc, y, f, 'julio')
    del Xl_sc
    log('p_log sin calendario futuro')
    pred['p_cal_enero'] = wf_cal(Xcal, y, f, 'enero', [1], [1, 0])
    pred['p_log_enero'] = wf_log(Xl, y, f, 'enero')
    log('enero')
    pred['p_cal_7030'] = wf_cal(Xcal, y, f, '70/30', [1], [1, 0])
    pred['p_log_7030'] = wf_log(Xl, y, f, '70/30')
    pred['p_nulo_7030'] = wf_log(np.column_stack([Xl[:, 0], D, falta]), y, f, '70/30')
    log('70/30')
    for k, v in pred.items():
        P[k] = v
    # como en el original: antes de 2012-07 la casa calibrada es la proporcional
    for k in ('p_cal', 'p_cal_liga', 'p_cal_enero'):
        P[k] = np.where(np.isnan(P[k].values), P.p_c.values, P[k].values)
    corte7030 = str(np.sort(f)[int(0.7 * len(f))])
    P['p_cal_7030'] = np.where(np.isnan(P.p_cal_7030.values), P.p_c.values, P.p_cal_7030.values)
    del Xa, Xl, D, falta, Lh

    temporadas = {'%d-%02d' % (y_, (y_ + 1) % 100): ('%d-07-01' % y_, '%d-07-01' % (y_ + 1))
                  for y_ in range(2012, 2027)}
    gan_win = lambda piso: P[(P.familia == 'ganador') & (P.lado != 'ninguno') & (P.cuota >= piso) &
                             (P.cuota <= piso + 0.5)]
    z = gan_win(1.60)
    R = {}

    def ev(nombre, sel, pcal='p_cal', extra=None, zz=None, semilla=1):
        r = medir(z if zz is None else zz, sel, pcal=pcal, periodos_extra=extra, semilla=semilla)
        R[nombre] = r
        log('%-62s %s' % (nombre[:62], corto(r)))
        for k in ('A', 'B', '2023'):
            if k in r:
                log('      %-5s %s' % (k, corto(r, k)))
        return r

    # nota: la base del original incluye el empate en [1,60;2,10]; se reproduce igual
    z_or = P[(P.familia == 'ganador') & (P.cuota >= 1.60) & (P.cuota <= 2.10)]
    lado_ok = (z_or.lado != 'ninguno').values
    log('== 2. reproducción (base con empate como en el original)')
    r = medir(z_or, ((z_or.p_log - z_or.p_cal >= 0.02).values), semilla=1)
    R['REPRO original: logística ≥ casa calibrada+2'] = r
    log('REPRO', corto(r))
    for k in ('A', 'B', '2023'):
        log('      %-5s %s' % (k, corto(r, k)))
    r = medir(z_or, np.ones(len(z_or), bool), semilla=1)
    R['REPRO base (casa elige)'] = r
    log('REPRO base', corto(r))
    z = z_or          # todo lo demás se mide sobre el mismo universo que el original

    log('== 3. controles')
    for u in (0.0, 0.01, 0.02, 0.03, 0.04):
        ev('logística ≥ casa calibrada+%d' % round(100 * u), (z.p_log - z.p_cal >= u).values)
    for u in (0.0, 0.02):
        ev('NULO (sin contexto) ≥ casa calibrada+%d' % round(100 * u), (z.p_nulo - z.p_cal >= u).values)
        ev('NULO+liga (sin contexto) ≥ casa calibrada+%d' % round(100 * u), (z.p_nulo_liga - z.p_cal >= u).values)
        ev('NULO+liga ≥ casa calibrada POR LIGA+%d [exc. sobre cal. por liga]' % round(100 * u),
           (z.p_nulo_liga - z.p_cal_liga >= u).values, pcal='p_cal_liga')
        ev('original medida contra casa calibrada POR LIGA (+%d)' % round(100 * u),
           (z.p_log - z.p_cal >= u).values, pcal='p_cal_liga')
        ev('logística ≥ casa calibrada POR LIGA+%d' % round(100 * u), (z.p_log - z.p_cal_liga >= u).values,
           pcal='p_cal_liga')
        ev('logística+liga ≥ casa calibrada POR LIGA+%d' % round(100 * u),
           (z.p_log_liga - z.p_cal_liga >= u).values, pcal='p_cal_liga')
        ev('logística SIN calendario futuro ≥ casa calibrada+%d' % round(100 * u),
           (z.p_log_sin_cal - z.p_cal >= u).values)
    # cuánto del filtro es puro precio: la regla elige cuotas más cortas dentro de la ventana
    log('== 4. otros cortes')
    for nom, msk in (('original +2', (z.p_log - z.p_cal >= 0.02).values),
                     ('NULO +2', (z.p_nulo - z.p_cal >= 0.02).values),
                     ('original +0', (z.p_log - z.p_cal >= 0.0).values)):
        rr = ev('POR TEMPORADA: ' + nom, msk, extra=temporadas)
        for k in temporadas:
            log('      %s %s' % (k, corto(rr, k)))
    for u in (0.0, 0.02):
        ev('WF ENERO: logística ≥ casa calibrada+%d' % round(100 * u),
           (z.p_log_enero - z.p_cal_enero >= u).values, pcal='p_cal_enero')
    zt = z[z.fecha.values.astype('datetime64[D]') >= np.datetime64(corte7030[:10])]
    for u in (0.0, 0.02):
        ev('70/30 congelado (prueba %s→): logística ≥ casa calibrada+%d' % (corte7030[:10], round(100 * u)),
           (zt.p_log_7030 - zt.p_cal_7030 >= u).values, pcal='p_cal_7030', zz=zt)
        ev('70/30 congelado: NULO ≥ casa calibrada+%d' % round(100 * u),
           (zt.p_nulo_7030 - zt.p_cal_7030 >= u).values, pcal='p_cal_7030', zz=zt)
    log('== 5. por formato de cuota')
    for fmt in ('main', 'new'):
        zf = z[z.formato == fmt]
        ev('[%s] original +2' % fmt, (zf.p_log - zf.p_cal >= 0.02).values, zz=zf)
        ev('[%s] NULO +2' % fmt, (zf.p_nulo - zf.p_cal >= 0.02).values, zz=zf)
        ev('[%s] REF Pinnacle ≥ casa+2' % fmt, ((zf.p_pin - zf.p_c >= 0.02).values & (zf.lado != 'ninguno').values),
           zz=zf)
    ev('REF Pinnacle ≥ casa+2 (todas)', (z.p_pin - z.p_c >= 0.02).values & lado_ok)
    log('== 6. pisos vecinos y ventanas')
    for piso in (1.45, 1.55, 1.65, 1.70, 1.80):
        zp = P[(P.familia == 'ganador') & (P.cuota >= piso) & (P.cuota <= piso + 0.5)]
        ev('piso %.2f: original +2' % piso, (zp.p_log - zp.p_cal >= 0.02).values, zz=zp)
        ev('piso %.2f: NULO +2' % piso, (zp.p_nulo - zp.p_cal >= 0.02).values, zz=zp)
    log('== 8. football-data crudo (B365 pre-cierre / cierre, PSH / PSCH)')
    try:
        nombres = m.set_index('mid')[['home_team', 'away_team']]
        zfd = P[(P.familia == 'ganador') & (P.cuota >= 1.60) & (P.cuota <= 2.10) &
                (P.formato == 'main')].join(nombres, on='mid')
        info, Xfd = seccion_fd(P, config)
        info.update(seccion_fd_medir(zfd, Xfd))
        OUT['football_data_crudo'] = info
    except Exception as ex:          # noqa: BLE001
        import traceback
        traceback.print_exc()
        OUT['football_data_crudo'] = {'error': repr(ex)}
    OUT['resultados'] = R

    # ---- ganancia positiva en algún caso
    pos = []
    for nom, r in R.items():
        if not isinstance(r, dict):
            continue
        for k, x in r.items():
            if isinstance(x, dict) and x.get('gan_100') is not None and x['gan_100'] > 0 and x.get('n', 0) >= 100:
                pos.append({'regla': nom, 'periodo': k, 'n': x['n'], 'gan_100': x['gan_100'], 'gan_p5': x['gan_p5'],
                            'gan_p95': x['gan_p95']})
    OUT['ganancia_positiva_n100'] = sorted(pos, key=lambda v: -v['gan_100'])

    # ---- conteo de celdas que «pasan» en el json original (aprendiz vs control)
    try:
        J = json.load(open('_v373_contexto.json', encoding='utf-8'))
        cnt = {}
        for fam, pp in J['reglas'].items():
            for kp, rr in pp.items():
                for nom, r in rr.items():
                    if 'calibrada+' in nom:
                        t = 'aprendiz ≥ casa calibrada'
                    elif nom.startswith('CONTROL'):
                        t = 'CONTROL casa calibrada ≥ casa'
                    elif nom.startswith(('casa elige, árbol ≥ casa+', 'casa elige, logística ≥ casa+')):
                        t = 'aprendiz ≥ casa proporcional'
                    else:
                        continue
                    c = cnt.setdefault(t, {'celdas': 0, 'pasa': 0, 'gan_positiva': 0})
                    c['celdas'] += 1
                    c['pasa'] += int(r.get('veredicto') == 'pasa')
                    c['gan_positiva'] += int(r.get('todo', {}).get('gan_100', -1) > 0)
        OUT['celdas_original'] = cnt
    except Exception as ex:          # noqa: BLE001
        OUT['celdas_original'] = str(ex)

    # ---- e_v361
    log('== 7. e_v361')
    OUT['e_v361'] = revisar_e()
    OUT['segundos'] = round(time.time() - T0)
    json.dump(OUT, open('_v373_contexto_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    log('escrito _v373_contexto_revision.json')


if __name__ == '__main__':
    main()
