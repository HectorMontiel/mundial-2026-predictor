# -*- coding: utf-8 -*-
"""
v331 — DIEZ HIPÓTESIS SOBRE POR QUÉ SALE ROJA UNA «METER», PROBADAS IGUAL.

El usuario: «tenemos una historia grande… no sólo verifiques mi teoría: haz
tú también hipótesis, método científico, simulaciones; no quiero que bajes
las cuotas a 1,20, que sería muy fácil; tiene que haber algo mejor».

LOS DATOS. Los dos históricos FUERA DE MUESTRA cruzados por partido:
`pick_ledger_totales.csv` (λ, probabilidades de goles, marcador) y
`pick_ledger.csv` (1X2 del modelo, cuotas de la casa, de Pinnacle y de
goles 2,5). Cada candidata «meter» se arma como en la app: modelo 70-80 % y,
si hay cuota, < 1,35. Mercados: ganador, doble oportunidad, más/menos de
1,5/2,5/3,5 y ambos marcan.

LAS VARIABLES, todas con lo que se sabía ANTES del partido:
  H1 vol      dispersión de los goles del equipo (a favor + en contra), 10 últimos
  H2 sesgo    goles reales − λ del modelo del equipo, 6 últimos, con el signo
              que perjudica a ESTA apuesta (positivo = el modelo se ha quedado
              corto justo en la dirección que la tumba)
  H3 n_temp   partidos del equipo en la temporada (corte: 50 días sin jugar)
  H4 descanso días desde su último partido (el menor de los dos)
  H5 pin      modelo − Pinnacle sin margen (sólo resultado)
  H6 casas    casa − Pinnacle sin margen, en la selección (sólo resultado)
  H7 corrector |λ total corregida − λ cruda|
  H8 liga     acierto − prometido de las 200 «meter» anteriores de su liga
  H9 partido  fuerza del favorito (max 1X2) y probabilidad de empate
  H10         todo junto: LightGBM entrenado en el tramo de mirar

EL EXAMEN (fijado antes de ver resultados):
  · 70 % más antiguo para mirar, 30 % reciente para juzgar.
  · Para cada variable se elige EN EL TRAMO DE MIRAR qué extremo (quintil
    peor) quitar. En el de juzgar se compara con el CONTROL: quitar el mismo
    número de apuestas de menor probabilidad (= subir el mínimo, lo «fácil»).
  · Pasa si gana al control en el juicio con p5 > 0 (bootstrap por día),
    gana también en las dos mitades del periodo y en ≥ 70 % de las temporadas.

Uso: python _v331_hipotesis.py   (escribe _v331_hipotesis.json y la tabla
     _v331_candidatas_hist.pkl para reutilizar; los .pkl no se suben)

RESULTADOS (2026-10-06), quitando el 20 % peor de cada variable; acierto en
el tramo de juzgar, regla / control «menor probabilidad»:

    resultado (81.259 «meter»)          goles (92.411 «meter»)
    H1 volatilidad    74,8 / 75,3        72,4 / 73,4
    H2 sesgo equipo   —                  73,0 / 73,4
    H3 inicio temp.   74,9 / 75,4        72,8 / 73,3
    H4 descanso       74,7 / 76,6        72,5 / 74,7
    H5 mod − Pinnacle 75,1 / 75,1        —
    H6 casa − Pinn.   75,0 / 75,1        —
    H7 corrector λ    74,8 / 75,4        74,0 / 73,5 (p5 +0,25 pero 4/9 temporadas)
    H8 liga reciente  75,0 / 75,5        72,9 / 73,5
    H9 favorito       75,6 / 75,4        72,7 / 73,5
    H9 empate         75,2 / 75,5        72,5 / 73,5
    NINGUNA pasa: subir el mínimo les gana a todas.

    H10 (LightGBM con todo): resultado +0,3-0,4 pts (p5 +0,1); goles +1,5
    (p5 +1,3), PERO `_v331_meta_ablacion.py` lo desmonta: +1,2 era arreglar
    «ambos marcan», cuya probabilidad en el histórico está rota (70-80 %
    prometido, 52 % real; la app la calcula distinto desde la v326). Sin
    ambos marcan, lo que aportan los equipos es 0,0-0,5 pts según el año
    (2022: −0,4) y el Brier pasa de 0,1909 a 0,1907. No compensa llevarlo a
    la app.

    H15, salida de mirar la calibración por tipo de apuesta: la línea 2,5
    del total de goles promete 72-73 % y da 66-69 % en todos los años. Es lo
    único que pasa las tres pruebas → `veredicto_pick.franja_futbol` (v331).
    Ver `_v331_linea_25.py`.
"""
from __future__ import annotations

import io
import json
import sys
from collections import defaultdict, deque

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
LO, HI, CUOTA_MAX = 0.70, 0.80, 1.35
rng = np.random.default_rng(331)


# ---------------------------------------------------------------- datos
def partidos() -> pd.DataFrame:
    t = pd.read_csv('pick_ledger_totales.csv')
    r = pd.read_csv('pick_ledger.csv')
    r = r.drop(columns=['goles_local', 'goles_visit', 'fecha', 'pliegue'])
    d = t.merge(r, on=['liga', 'match_id'], how='inner')
    for k in ('cuota_over25', 'cuota_under25'):
        d[k] = d[k + '_y'].fillna(d[k + '_x'])
    d['fecha'] = pd.to_datetime(d.fecha)
    p = d.match_id.str.split('_', n=2, expand=True)
    d['home'] = d.liga + '|' + p[1]
    d['away'] = d.liga + '|' + p[2]
    d = d[d.goles_local.notna() & d.goles_visit.notna()]
    return d.sort_values(['fecha', 'match_id']).reset_index(drop=True)


def rasgos_equipo(d: pd.DataFrame) -> pd.DataFrame:
    """Lo que se sabía de cada equipo antes de cada partido."""
    hist = defaultdict(lambda: deque(maxlen=10))   # (gf, gc, lam_f, lam_c, pts-xpts)
    ultimo = {}
    n_temp = defaultdict(int)
    cols = defaultdict(list)
    for fecha, g in d.groupby('fecha', sort=True):
        for _, r in g.iterrows():
            for lado, eq in (('h', r.home), ('a', r.away)):
                h = hist[eq]
                if eq in ultimo and (fecha - ultimo[eq]).days > 50:
                    n_temp[eq] = 0
                gf = [x[0] for x in h]
                gc = [x[1] for x in h]
                cols['vol_' + lado].append(np.std(np.add(gf, gc)) if len(h) >= 5 else np.nan)
                u6 = list(h)[-6:]
                cols['resf_' + lado].append(np.mean([x[0] - x[2] for x in u6]) if len(u6) >= 4 else np.nan)
                cols['resc_' + lado].append(np.mean([x[1] - x[3] for x in u6]) if len(u6) >= 4 else np.nan)
                cols['xpts_' + lado].append(np.mean([x[4] for x in u6]) if len(u6) >= 4 else np.nan)
                cols['ntemp_' + lado].append(n_temp[eq])
                cols['desc_' + lado].append((fecha - ultimo[eq]).days if eq in ultimo else np.nan)
        for _, r in g.iterrows():
            ph, px, pa = r.p_home, r.p_draw, r.p_away
            gh, ga = r.goles_local, r.goles_visit
            pts_h = 3 * (gh > ga) + (gh == ga)
            pts_a = 3 * (ga > gh) + (gh == ga)
            hist[r.home].append((gh, ga, r.lam_h, r.lam_a, pts_h - (3 * ph + px)))
            hist[r.away].append((ga, gh, r.lam_a, r.lam_h, pts_a - (3 * pa + px)))
            for eq in (r.home, r.away):
                ultimo[eq] = fecha
                n_temp[eq] += 1
    for k, v in cols.items():
        d[k] = v
    return d


def candidatas(d: pd.DataFrame) -> pd.DataFrame:
    gh, ga = d.goles_local, d.goles_visit
    loc, emp, vis = (gh > ga).astype(int), (gh == ga).astype(int), (gh < ga).astype(int)
    tot = gh + ga
    ih, ix, ia = 1 / d.cuota_home, 1 / d.cuota_draw, 1 / d.cuota_away
    s = ih + ix + ia
    ph_, px_, pa_ = 1 / d.pin_home, 1 / d.pin_draw, 1 / d.pin_away
    sp = ph_ + px_ + pa_
    pin = {'h': ph_ / sp, 'x': px_ / sp, 'a': pa_ / sp}
    cas = {'h': ih / s, 'x': ix / s, 'a': ia / s}
    filas = []

    def add(nombre, grupo, prob, verde, cuota, p_pin, p_cas, sesgo):
        filas.append(pd.DataFrame({
            'i': d.index, 'apuesta': nombre, 'grupo': grupo, 'prob': prob,
            'verde': verde, 'cuota': cuota, 'p_pin': p_pin, 'p_cas': p_cas,
            'sesgo': sesgo}))
    # resultado: «sesgo» = cuánto se ha quedado corto el modelo con el RIVAL
    # (sus puntos − esperados) menos con el equipo apostado: positivo = malo
    xh, xa = d.xpts_h, d.xpts_a
    add('Gana local', 'resultado', d.p_home, loc, d.cuota_home, pin['h'], cas['h'], xa - xh)
    add('Gana visita', 'resultado', d.p_away, vis, d.cuota_away, pin['a'], cas['a'], xh - xa)
    add('Local o empate', 'resultado', d.p_home + d.p_draw, loc | emp,
        1 / (ih + ix), pin['h'] + pin['x'], cas['h'] + cas['x'], xa - xh)
    add('Visita o empate', 'resultado', d.p_away + d.p_draw, vis | emp,
        1 / (ia + ix), pin['a'] + pin['x'], cas['a'] + cas['x'], xh - xa)
    add('Local o visita', 'resultado', d.p_home + d.p_away, loc | vis,
        1 / (ih + ia), pin['h'] + pin['a'], cas['h'] + cas['a'], np.nan)
    # goles: «sesgo» = goles reales − λ de los dos equipos (a favor y en
    # contra), con signo + cuando el modelo se queda CORTO y la apuesta es
    # «menos», o se pasa y la apuesta es «más»
    exc = (d.resf_h + d.resc_h + d.resf_a + d.resc_a) / 2
    io_, iu = 1 / d.cuota_over25, 1 / d.cuota_under25
    for ln in (1.5, 2.5, 3.5):
        p = d['p_over_%s' % ln]
        co = d.cuota_over25 if ln == 2.5 else np.nan
        cu = d.cuota_under25 if ln == 2.5 else np.nan
        pc = io_ / (io_ + iu) if ln == 2.5 else np.nan
        add('Más de %s' % ln, 'goles', p, (tot > ln).astype(int), co, np.nan, pc, -exc)
        add('Menos de %s' % ln, 'goles', 1 - p, (tot < ln).astype(int), cu, np.nan,
            1 - pc if ln == 2.5 else np.nan, exc)
    btts = ((gh > 0) & (ga > 0)).astype(int)
    add('Ambos marcan sí', 'goles', d.p_btts, btts, np.nan, np.nan, np.nan, -exc)
    add('Ambos marcan no', 'goles', 1 - d.p_btts, 1 - btts, np.nan, np.nan, np.nan, exc)
    c = pd.concat(filas, ignore_index=True)
    c = c[(c.prob >= LO) & (c.prob <= HI) & c.verde.notna()]
    c = c[c.cuota.isna() | (c.cuota < CUOTA_MAX)]
    base = d[['fecha', 'liga', 'match_id', 'vol_h', 'vol_a', 'ntemp_h', 'ntemp_a',
              'desc_h', 'desc_a', 'lam_total_prod', 'lam_total_crudo',
              'p_home', 'p_draw', 'p_away']]
    c = c.join(base, on='i')
    c['vol'] = c[['vol_h', 'vol_a']].mean(axis=1)
    c['n_temp'] = c[['ntemp_h', 'ntemp_a']].min(axis=1)
    c['descanso'] = c[['desc_h', 'desc_a']].min(axis=1)
    c['pin'] = c.prob - c.p_pin
    c['casas'] = c.p_cas - c.p_pin
    c['corrector'] = (c.lam_total_prod - c.lam_total_crudo).abs()
    c['favorito'] = c[['p_home', 'p_away']].max(axis=1)
    c['empate'] = c.p_draw
    return c.sort_values(['fecha', 'match_id']).reset_index(drop=True)


def calibracion_liga(c: pd.DataFrame, n=200) -> pd.DataFrame:
    """H8: acierto − prometido de las n «meter» anteriores de su liga (días previos)."""
    q = defaultdict(lambda: deque(maxlen=n))
    out = np.full(len(c), np.nan)
    for fecha, g in c.groupby('fecha', sort=True):
        for i, r in g.iterrows():
            h = q[r.liga]
            if len(h) >= 50:
                out[i] = np.mean(h)
        for i, r in g.iterrows():
            q[r.liga].append(r.verde - r.prob)
    c['liga_cal'] = out
    return c


# --------------------------------------------------------------- examen
VARIABLES = {
    'H1 volatilidad': 'vol', 'H2 sesgo del modelo con el equipo': 'sesgo',
    'H3 inicio de temporada': 'n_temp', 'H4 descanso': 'descanso',
    'H5 modelo − Pinnacle': 'pin', 'H6 casa − Pinnacle': 'casas',
    'H7 corrector de λ': 'corrector', 'H8 calibración reciente de la liga': 'liga_cal',
    'H9a fuerza del favorito': 'favorito', 'H9b probabilidad de empate': 'empate',
}


def control_por_prob(s: pd.DataFrame, n_quitar: int) -> pd.Series:
    """Quita las n de menor probabilidad: el «subir el mínimo»."""
    orden = s.prob.sort_values(kind='mergesort').index[:n_quitar]
    m = pd.Series(False, index=s.index)
    m[orden] = True
    return m


def compara(s: pd.DataFrame, quita: pd.Series):
    """acierto con la regla − acierto del control con el MISMO número quitado."""
    n = int(quita.sum())
    if n == 0 or n == len(s):
        return np.nan, np.nan, n
    ctrl = control_por_prob(s, n)
    return (100 * s[~quita].verde.mean(), 100 * s[~ctrl].verde.mean(), n)


def boot_vs_control(s: pd.DataFrame, quita: pd.Series, n_iter=1500):
    ctrl = control_por_prob(s, int(quita.sum()))
    g = pd.DataFrame({'f': s.fecha, 'v': s.verde, 'r': ~quita, 'c': ~ctrl})
    a = g.groupby('f').apply(lambda x: pd.Series({
        'vr': (x.v * x.r).sum(), 'nr': x.r.sum(),
        'vc': (x.v * x.c).sum(), 'nc': x.c.sum()}), include_groups=False)
    A = a.values
    difs = []
    for _ in range(n_iter):
        b = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        if b[1] and b[3]:
            difs.append(b[0] / b[1] - b[2] / b[3])
    return 100 * np.percentile(difs, 5), 100 * np.mean(difs)


def examina(c: pd.DataFrame, grupo: str, frac=0.20) -> dict:
    s0 = c[c.grupo == grupo]
    dias = np.sort(s0.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    mitad = dias[len(dias) // 2]
    M, J = s0[s0.fecha < corte], s0[s0.fecha >= corte]
    print('\n' + '=' * 78)
    print('%s — %d apuestas «meter» (mirar %d · juzgar %d), acierto %.1f %%'
          % (grupo.upper(), len(s0), len(M), len(J), 100 * s0.verde.mean()))
    print('quitando el %d %% peor de cada variable, contra quitar el mismo número '
          'de menor probabilidad' % (100 * frac))
    print('%-38s %-8s %-15s %-15s %-14s %s' % ('hipótesis', 'quita', 'mirar regla/ctrl',
                                             'juzgar regla/ctrl', 'p5 (juzgar)', 'veredicto'))
    out = {}
    for nombre, col in VARIABLES.items():
        if s0[col].notna().mean() < 0.5:
            continue
        m_ok = M[M[col].notna()]
        # se elige en MIRAR qué cola quitar: la de peor exceso sobre el modelo
        lo_q, hi_q = m_ok[col].quantile(frac), m_ok[col].quantile(1 - frac)
        ex_lo = (m_ok[m_ok[col] <= lo_q].verde - m_ok[m_ok[col] <= lo_q].prob).mean()
        ex_hi = (m_ok[m_ok[col] >= hi_q].verde - m_ok[m_ok[col] >= hi_q].prob).mean()
        cola, umbral = ('alta', hi_q) if ex_hi < ex_lo else ('baja', lo_q)

        def regla(s):
            v = s[col]
            return (v >= umbral) if cola == 'alta' else (v <= umbral)
        res = {}
        for t, s in (('mirar', M), ('juzgar', J), ('mitad1', s0[s0.fecha < mitad]),
                     ('mitad2', s0[s0.fecha >= mitad])):
            q = regla(s).fillna(False)
            res[t] = compara(s, q)
        p5, med = boot_vs_control(J, regla(J).fillna(False))
        temporadas = []
        for a, s in s0.groupby(s0.fecha.dt.year):
            if len(s) >= 300:
                r_, c_, _ = compara(s, regla(s).fillna(False))
                temporadas.append(r_ > c_)
        frac_t = np.mean(temporadas) if temporadas else np.nan
        pasa = (p5 > 0 and res['mirar'][0] > res['mirar'][1]
                and res['mitad1'][0] > res['mitad1'][1]
                and res['mitad2'][0] > res['mitad2'][1] and frac_t >= 0.7)
        print('%-38s %-8s %5.1f/%5.1f     %5.1f/%5.1f     %+.2f (%+.2f)  %s · temporadas %d/%d'
              % (nombre, cola, res['mirar'][0], res['mirar'][1], res['juzgar'][0],
                 res['juzgar'][1], p5, med, 'PASA' if pasa else 'no pasa',
                 sum(temporadas), len(temporadas)))
        out[nombre] = {'col': col, 'cola': cola, 'umbral': float(umbral), 'res': res,
                       'p5': p5, 'media': med, 'temporadas': frac_t, 'pasa': bool(pasa)}
    return out


def meta_modelo(c: pd.DataFrame, grupo: str, fracs=(0.1, 0.2, 0.3)) -> dict:
    """H10: LightGBM con todo, entrenado en MIRAR; se juzga contra el control."""
    import lightgbm as lgb
    s0 = c[c.grupo == grupo].copy()
    dias = np.sort(s0.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    X_cols = ['prob'] + [v for v in VARIABLES.values() if s0[v].notna().mean() >= 0.5]
    s0['ap'] = s0.apuesta.astype('category').cat.codes
    X_cols.append('ap')
    M, J = s0[s0.fecha < corte], s0[s0.fecha >= corte]
    mdl = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15,
                             min_child_samples=200, subsample=0.8, subsample_freq=1,
                             colsample_bytree=0.8, reg_lambda=5.0, verbose=-1,
                             random_state=331)
    mdl.fit(M[X_cols], M.verde)
    J = J.assign(meta=mdl.predict_proba(J[X_cols])[:, 1])
    brier_p = np.mean((J.verde - J.prob) ** 2)
    brier_m = np.mean((J.verde - J.meta) ** 2)
    print('\n--- H10 %s: LightGBM con %s' % (grupo.upper(), ', '.join(X_cols)))
    print('   Brier en el juicio: probabilidad del modelo %.4f · meta %.4f'
          % (brier_p, brier_m))
    out = {'brier_prob': brier_p, 'brier_meta': brier_m, 'cortes': {}}
    imp = sorted(zip(mdl.feature_importances_, X_cols), reverse=True)
    print('   importancia:', ', '.join('%s %d' % (k, v) for v, k in imp))
    for f in fracs:
        n = int(len(J) * f)
        quita = pd.Series(False, index=J.index)
        quita[J.meta.sort_values(kind='mergesort').index[:n]] = True
        r_, c_, _ = compara(J, quita)
        p5, med = boot_vs_control(J, quita)
        print('   quitar el %d %% peor según el meta: %.1f %% · control %.1f %% · '
              'p5 %+.2f (media %+.2f) → %s' % (100 * f, r_, c_, p5, med,
                                              'PASA' if p5 > 0 else 'no pasa'))
        out['cortes'][f] = {'regla': r_, 'control': c_, 'p5': p5, 'media': med}
    return out


def main():
    import os
    if os.path.exists('_v331_rasgos.pkl'):
        d = pd.read_pickle('_v331_rasgos.pkl')
    else:
        d = rasgos_equipo(partidos())
        d.to_pickle('_v331_rasgos.pkl')
    c = calibracion_liga(candidatas(d))
    c.to_pickle('_v331_candidatas_hist.pkl')
    res = {}
    for g in ('resultado', 'goles'):
        res[g] = {'variables': examina(c, g), 'meta': meta_modelo(c, g)}
    json.dump(res, open('_v331_hipotesis.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
