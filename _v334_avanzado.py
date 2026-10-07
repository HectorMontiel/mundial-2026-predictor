# -*- coding: utf-8 -*-
"""
v334 — TÉCNICAS DE FINANZAS CUANTITATIVAS PARA DAR MÁS VERDES.

El usuario: «no entiendo cómo es que mejora pero no nos da más verdes…
investiga técnicas mucho más avanzadas de machine learning o algoritmos
estadísticos; quizá algo de los modelos de bolsa que no hemos probado en
apuestas… método científico y simulaciones».

LA VARA, QUE ANTES ESTABA MAL PUESTA. Comparar lo que acierta cada modelo
cuando dice «70-80 %» no sirve: si los dos están calibrados, los dos aciertan
~75 % ahí por definición. Un modelo mejor no hace que su 75 % acierte más:
ELIGE mejores partidos. La prueba justa es dejar que cada uno escoja el MISMO
número de apuestas —sus N más seguras de entre las mismas candidatas— y
contar los verdes. Candidatas por partido: más de 1,5, menos de 3,5, local o
empate, visita o empate (lo que la app «mete»).

LOS CONTENDIENTES, todos fuera de muestra:
  modelo   — el del proyecto (pick_ledger*.csv)
  mercado  — `motor_mercado` con las cuotas del mercado (v333)
  GAS      — NUEVO: modelo «score-driven» (Creal, Koopman y Lucas 2013, de
             la econometría de volatilidad financiera; Koopman y Lit lo
             llevaron al fútbol). Ataque y defensa de cada equipo son estados
             que se mueven con la SORPRESA de cada partido (goles − λ), como
             un precio que se ajusta con cada noticia, con persistencia φ y
             ganancia κ elegidas por verosimilitud en el tramo de mirar. Cada
             predicción se hace ANTES de ver el partido.
  apilado  — NUEVO: regresión logística por mercado sobre los logits de los
             tres (como combinar señales alfa en un fondo), entrenada al mirar.
  consenso — NUEVO: sólo cuando los tres pasan del umbral a la vez (riesgo de
             modelo: apostar donde fuentes independientes coinciden).

70 % antiguo para ajustar, 30 % reciente para juzgar; bootstrap por día de la
diferencia de verdes a igual número de apuestas.

RESULTADOS (2026-10-06, 80.855 partidos, juicio desde 2024-09-26)
  log-loss: modelo 0,5881 · GAS 0,5902 · mercado 0,5788 · apilado 0,5786
  A IGUAL número de apuestas, verdes:
      N 2.314   modelo 91,6 · GAS 89,6 · mercado 93,1 (p5 +0,51) · apilado 93,0
      N 4.628   modelo 88,0 · GAS 86,9 · mercado 90,2 (p5 +1,35) · apilado 90,2
      N 6.942   modelo 86,0 · GAS 84,9 · mercado 88,4 (p5 +1,71) · apilado 88,3
  El apilado pone peso ≈ 1 al mercado y ≈ 0 al modelo y al GAS: NINGUNO de los
  dos sabe algo que el precio no sepa ya. El GAS (κ 0,02, φ 1,0) sale peor
  que el modelo. El consenso no ayuda.

  DENTRO DE LA FRANJA DE CUOTA DE LA APP (mismas N, histórico con cuota real):
      1,15-1,35  regla de hoy 76,0 % a 1,247 (−5,3 %) · casa 79,1 % a 1,207 (−4,6 %)
      1,20-1,35  regla de hoy 74,7 % a 1,269 (−5,2 %) · casa 76,5 % a 1,243 (−4,9 %)
      1,25-1,35  regla de hoy 73,5 % a 1,295 (−4,8 %) · casa 74,7 % a 1,278 (−4,5 %)
  Los verdes de más vienen de cuotas más bajas: la casa calibra al punto, así
  que verdes y cuota van atados. Salir de esa frontera exige información que
  el precio no tenga, y ni el modelo ni el GAS la tienen. No se activa nada.
"""
from __future__ import annotations

import io
import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

import motor_mercado as mm

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(334)


# ------------------------------------------------------------------ datos
def datos() -> pd.DataFrame:
    t = pd.read_csv('pick_ledger_totales.csv')
    r = pd.read_csv('pick_ledger.csv').drop(columns=['goles_local', 'goles_visit',
                                                      'fecha', 'pliegue'])
    d = t.merge(r, on=['liga', 'match_id'], how='left')
    for k in ('cuota_over25', 'cuota_under25'):
        if k + '_y' in d:
            d[k] = d[k + '_y'].fillna(d[k + '_x'])
    d = d[d.goles_local.notna()].copy()
    d['fecha'] = pd.to_datetime(d.fecha)
    p = d.match_id.str.split('_', n=2, expand=True)
    d['home'], d['away'] = d.liga + '|' + p[1], d.liga + '|' + p[2]
    return d.sort_values(['fecha', 'match_id']).reset_index(drop=True)


# -------------------------------------------------------------------- GAS
def gas(d: pd.DataFrame, kappa: float, phi: float, corte) -> np.ndarray:
    """λ local y visita de cada partido, ANTES de verlo. Nivel y ventaja de
    local por liga con los partidos de mirar."""
    M = d[d.fecha < corte]
    base = M.groupby('liga').agg(gh=('goles_local', 'mean'), ga=('goles_visit', 'mean'))
    c = np.log(base.ga.clip(0.3)).to_dict()
    h = np.log((base.gh / base.ga).clip(0.7, 1.8)).to_dict()
    cg, hg = np.log(M.goles_visit.mean()), np.log(M.goles_local.mean() / M.goles_visit.mean())
    at, de = defaultdict(float), defaultdict(float)
    ult = {}
    out = np.zeros((len(d), 2))
    for k, (f, lg, H, A, gh, ga) in enumerate(zip(d.fecha.values, d.liga.values, d.home.values,
                                                  d.away.values, d.goles_local.values,
                                                  d.goles_visit.values)):
        for eq in (H, A):
            if eq in ult:
                dias = (f - ult[eq]) / np.timedelta64(1, 'D')
                dec = phi ** dias
                if dias > 50:                       # parón de temporada
                    dec *= 0.7
                at[eq] *= dec
                de[eq] *= dec
            ult[eq] = f
        cc, hh = c.get(lg, cg), h.get(lg, hg)
        lh = np.exp(cc + hh + at[H] - de[A])
        la = np.exp(cc + at[A] - de[H])
        out[k] = (lh, la)
        sh, sa = gh - lh, ga - la                   # la «sorpresa» (score de Poisson)
        at[H] += kappa * sh
        de[A] -= kappa * sh
        at[A] += kappa * sa
        de[H] -= kappa * sa
    return out


def loglik(lam, y):
    from scipy.special import gammaln
    lam = np.clip(lam, 1e-3, None)
    return float(np.sum(y * np.log(lam) - lam - gammaln(y + 1)))


def ajusta_gas(d, corte):
    M = d.fecha < corte
    y = np.c_[d.goles_local.values, d.goles_visit.values][M.values]
    mejor = None
    print('   ajuste del GAS (verosimilitud en mirar):')
    for kappa in (0.02, 0.04, 0.06, 0.09):
        for phi in (0.999, 0.9995, 1.0):
            L = gas(d, kappa, phi, corte)[M.values]
            v = loglik(L, y)
            print('      κ %.2f φ %.4f → %.1f' % (kappa, phi, v))
            if mejor is None or v > mejor[0]:
                mejor = (v, kappa, phi)
    print('   elegido κ %.2f, φ %.4f' % (mejor[1], mejor[2]))
    return mejor[1], mejor[2]


def probs_de_lambdas(L: np.ndarray) -> dict:
    """Probabilidades de las candidatas a partir de λ (Dixon-Coles, ρ v333)."""
    T = mm.tabla()
    lh = np.clip(L[:, 0], 0.05, 4.55)
    la = np.clip(L[:, 1], 0.05, 4.55)
    paso = 0.02
    n = int(round((4.6 - 0.05) / paso))
    i = np.clip(np.round((lh - 0.05) / paso).astype(int), 0, n - 1)
    j = np.clip(np.round((la - 0.05) / paso).astype(int), 0, n - 1)
    idx = i * n + j
    return {k: T['P'][k][idx] for k in ('Más de 1.5', 'Menos de 3.5', 'Local o empate',
                                        'Visita o empate', 'Más de 2.5')}


# --------------------------------------------------------------- candidatas
CANDIDATAS = ('Más de 1.5', 'Menos de 3.5', 'Local o empate', 'Visita o empate')


def tabla_candidatas(d, P_gas, P_mer):
    tot = d.goles_local + d.goles_visit
    real = {'Más de 1.5': (tot > 1.5), 'Menos de 3.5': (tot < 3.5),
            'Local o empate': d.goles_local >= d.goles_visit,
            'Visita o empate': d.goles_visit >= d.goles_local}
    mod = {'Más de 1.5': d['p_over_1.5'], 'Menos de 3.5': 1 - d['p_over_3.5'],
           'Local o empate': d.p_home + d.p_draw, 'Visita o empate': d.p_away + d.p_draw}
    filas = []
    for ap in CANDIDATAS:
        filas.append(pd.DataFrame({'fecha': d.fecha, 'mid': d.match_id, 'liga': d.liga,
                                   'apuesta': ap, 'verde': real[ap].astype(int),
                                   'modelo': mod[ap], 'gas': P_gas[ap], 'mercado': P_mer[ap]}))
    c = pd.concat(filas, ignore_index=True)
    return c[c.modelo.notna() & c.mercado.notna()].reset_index(drop=True)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def apila(c, corte):
    from sklearn.linear_model import LogisticRegression
    c = c.copy()
    c['apilado'] = np.nan
    for ap, s in c.groupby('apuesta'):
        X = np.c_[logit(s.modelo), logit(s.gas), logit(s.mercado)]
        m = (s.fecha < corte).values
        lr = LogisticRegression(C=1.0).fit(X[m], s.verde.values[m])
        c.loc[s.index, 'apilado'] = lr.predict_proba(X)[:, 1]
        print('   apilado %-16s pesos modelo %.2f · GAS %.2f · mercado %.2f'
              % (ap, *lr.coef_[0]))
    return c


def top_n(J, col, n):
    """Las n candidatas más seguras según `col`, una por partido."""
    s = J.sort_values(col, ascending=False).drop_duplicates('mid')
    return s.head(n)


def ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main():
    d = datos()
    dias = np.sort(d.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    print('%d partidos · corte %s' % (len(d), str(corte)[:10]))
    kappa, phi = ajusta_gas(d, corte)
    L = gas(d, kappa, phi, corte)
    P_gas = probs_de_lambdas(L)
    # mercado (motor v333) con 1X2 y más/menos 2,5 del mercado
    ih, ix, ia = 1 / d.cuota_home, 1 / d.cuota_draw, 1 / d.cuota_away
    s = ih + ix + ia
    io_, iu = 1 / d.cuota_over25, 1 / d.cuota_under25
    T = mm.tabla()
    idx = mm.lote((ih / s).values, (ia / s).values, (io_ / (io_ + iu)).values)
    P_mer = {k: np.where(idx >= 0, T['P'][k][np.clip(idx, 0, None)], np.nan)
             for k in CANDIDATAS}
    c = tabla_candidatas(d, P_gas, P_mer)
    c = apila(c, corte)
    c['consenso'] = c[['modelo', 'gas', 'mercado']].min(axis=1)
    J = c[c.fecha >= corte]
    out = {'kappa': kappa, 'phi': phi, 'corte': str(corte)[:10]}
    print('\n1. CALIDAD (juicio, %d candidatas): log-loss, menor es mejor' % len(J))
    for col in ('modelo', 'gas', 'mercado', 'apilado'):
        print('   %-9s %.4f' % (col, ll(J.verde, J[col])))
        out['ll_' + col] = ll(J.verde, J[col])
    print('\n2. A IGUAL NÚMERO DE APUESTAS (las N más seguras de cada uno, una por partido)')
    print('   N        modelo    GAS       mercado   apilado   consenso')
    nj = J.mid.nunique()
    out['igual_n'] = {}
    for frac in (0.05, 0.10, 0.20, 0.30):
        n = int(nj * frac)
        fila = {}
        for col in ('modelo', 'gas', 'mercado', 'apilado', 'consenso'):
            t = top_n(J, col, n)
            fila[col] = (t.verde.mean(), t)
        print('   %-7d  %5.1f %%   %5.1f %%   %5.1f %%   %5.1f %%   %5.1f %%'
              % (n, *[100 * fila[k][0] for k in ('modelo', 'gas', 'mercado', 'apilado', 'consenso')]))
        out['igual_n'][n] = {k: v[0] for k, v in fila.items()}
        # bootstrap por día: apilado − modelo y mercado − modelo
        for otro in ('apilado', 'mercado', 'consenso'):
            a = fila[otro][1].groupby('fecha').verde.agg(['sum', 'size'])
            b = fila['modelo'][1].groupby('fecha').verde.agg(['sum', 'size'])
            dd = sorted(set(a.index) | set(b.index))
            A = a.reindex(dd, fill_value=0).values
            B = b.reindex(dd, fill_value=0).values
            bs = []
            for _ in range(2000):
                q = rng.integers(0, len(dd), len(dd))
                x, y = A[q].sum(axis=0), B[q].sum(axis=0)
                bs.append(x[0] / x[1] - y[0] / y[1])
            print('      %-8s − modelo: %+.2f pts (p5 %+.2f)' % (otro, 100 * np.mean(bs),
                                                               100 * np.percentile(bs, 5)))
            out['igual_n'][n]['%s_p5' % otro] = 100 * np.percentile(bs, 5)
    c[['fecha', 'mid', 'liga', 'apuesta', 'verde', 'modelo', 'gas', 'mercado', 'apilado']] \
        .to_pickle('_v334_candidatas.pkl')
    json.dump(out, open('_v334_avanzado.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
