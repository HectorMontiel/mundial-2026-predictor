#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v177 — ¿SUBESTIMA EL MODELO LOS GOLES EN LAS LIGAS DE MUCHOS GOLES?

EL ENCARGO
----------
«Si la liga tiene una media de goles alta (λ_liga > 2,8), el modelo debe
AUMENTAR la λ esperada en un 5-10 % antes de calcular las probabilidades
Over/Under.» Y: «si el ECE de goles sigue > 0,08, aplicar el encogimiento hacia
la casa de forma más agresiva (w=0,30 en lugar de 0,25)».

Son dos hipótesis contrastables y este proyecto tiene con qué contrastarlas:
`pick_ledger_totales.csv`, 47.794 partidos walk-forward con la λ que el modelo
dio de cada bando, los goles reales y la cuota de cierre del 2,5.

QUÉ SE MIDE, Y EN ESTE ORDEN
-----------------------------
  1. **¿Hay sesgo?** `media(y − λ)` por competición y por tramo de nivel. Si el
     modelo subestimara los goles en las ligas altas, esa diferencia sería
     POSITIVA y crecería con la media de la liga. Si sale en cero, multiplicar
     la λ por 1,05 no corrige un sesgo: lo crea.
  2. **¿Y después de la corrección de la v175?** La λ de producción ya no es
     `lam_h + lam_a`: desde la v175 se corrige con el H2H y la forma reciente
     (β 0,186 y 0,255, medidos). El sesgo hay que mirarlo sobre la λ QUE SE
     USA, no sobre la de antes.
  3. **El multiplicador que pide el encargo**, con su efecto en el ECE: 1,05 y
     1,10 sobre las ligas de media > 2,8.
  4. **El encogimiento w=0,30 contra w=0,25**, sobre la cifra publicada.

LO QUE ESTE FICHERO NO HACE
---------------------------
Decidir por simpatía. Si el sesgo sale en cero, el multiplicador no entra por
mucho que se haya pedido, y queda escrito por qué — igual que la binomial
negativa de la v175, que tenía buen diagnóstico y mal remedio.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

LINEAS = (1.5, 2.5, 3.5)
MIN_H2H = 4
N_H2H = 10
N_FORMA = 5
BETA_H2H = 0.186
BETA_FORMA = 0.255
W_BASE = 0.25


def ece(p, y, n_bins: int = 10):
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if len(p) < 50:
        return None
    bordes = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for i in range(n_bins):
        m = (p >= bordes[i]) & (p < bordes[i + 1] if i < n_bins - 1
                                else p <= bordes[i + 1])
        if m.sum() == 0:
            continue
        total += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
    return float(total)


def p_over(lam, linea):
    from scipy import stats
    return 1.0 - stats.poisson.cdf(int(np.floor(linea)), lam)


def devig2(c1, c2):
    try:
        c1, c2 = float(c1), float(c2)
    except (TypeError, ValueError):
        return np.nan
    if not (c1 > 1 and c2 > 1):
        return np.nan
    return (1.0 / c1) / (1.0 / c1 + 1.0 / c2)


def _fichero_de(liga):
    for cand in ('historico_%s.csv' % liga, 'historico_fotmob_%s.csv' % liga):
        if os.path.exists(cand):
            return cand
    return None


def señales(liga, ids):
    """H2H previo y forma previa de cada partido. Todo ANTERIOR a su fecha."""
    ruta = _fichero_de(liga)
    if not ruta:
        return {}
    try:
        d = pd.read_csv(ruta, low_memory=False)
    except Exception:
        return {}
    if not {'MATCH_ID', 'home_team', 'away_team', 'home_goals', 'away_goals',
            'date'}.issubset(d.columns):
        return {}
    d = d.dropna(subset=['home_goals', 'away_goals', 'home_team', 'away_team'])
    d = d.sort_values('date').reset_index(drop=True)
    tot = (d['home_goals'].astype(float) + d['away_goals'].astype(float))
    cruces, equipos, salida = defaultdict(list), defaultdict(list), {}
    for mid, h, a, t in zip(d['MATCH_ID'], d['home_team'], d['away_team'], tot):
        par = tuple(sorted((str(h), str(a))))
        if mid in ids:
            prev = cruces[par][-N_H2H:]
            sh, sa = equipos[str(h)][-N_FORMA:], equipos[str(a)][-N_FORMA:]
            salida[mid] = {
                'h2h': float(np.mean(prev)) if len(cruces[par]) >= MIN_H2H
                else None,
                'forma': ((float(np.mean(sh)) + float(np.mean(sa))) / 2.0
                          if len(sh) >= 3 and len(sa) >= 3 else None)}
        cruces[par].append(float(t))
        equipos[str(h)].append(float(t))
        equipos[str(a)].append(float(t))
    return salida


def cargar():
    d = pd.read_csv('pick_ledger_totales.csv')
    d['lam0'] = d['lam_h'].astype(float) + d['lam_a'].astype(float)
    d = d[np.isfinite(d['lam0']) & (d['lam0'] > 0)].copy()
    h2h, forma = [], []
    for liga, sub in d.groupby('liga'):
        s = señales(liga, set(sub['match_id']))
        for mid in sub['match_id']:
            r = s.get(mid) or {}
            h2h.append(r.get('h2h'))
            forma.append(r.get('forma'))
    d['h2h'] = [np.nan if x is None else x for x in h2h]
    d['forma'] = [np.nan if x is None else x for x in forma]
    lam0 = d['lam0'].to_numpy(float)
    # la λ de PRODUCCIÓN: la corregida por la v175
    ajuste = np.zeros_like(lam0)
    ok_h = np.isfinite(d['h2h'].to_numpy(float))
    ok_f = np.isfinite(d['forma'].to_numpy(float))
    ajuste[ok_h] += BETA_H2H * (d['h2h'].to_numpy(float)[ok_h] - lam0[ok_h])
    ajuste[ok_f] += BETA_FORMA * (d['forma'].to_numpy(float)[ok_f]
                                  - lam0[ok_f])
    d['lam'] = np.maximum(lam0 + ajuste, 0.05)
    # el nivel de cada competición, con los mismos partidos del ledger
    nivel = d.groupby('liga')['goles_total'].mean()
    d['nivel'] = d['liga'].map(nivel)
    d['mkt'] = [devig2(a, b) for a, b in zip(d['cuota_over25'],
                                             d['cuota_under25'])]
    return d


def main():
    d = cargar()
    y = d['goles_total'].to_numpy(float)
    lam0 = d['lam0'].to_numpy(float)
    lam = d['lam'].to_numpy(float)
    print('=' * 78)
    print('v177 — ¿SUBESTIMA EL MODELO LOS GOLES? %d partidos' % len(d))
    print('=' * 78)

    # ---- 1) el sesgo, que es la pregunta ------------------------------
    print('\n1) SESGO MEDIO  (goles reales − lambda).  0 = sin sesgo')
    print('   sobre la lambda CRUDA ....... %+.4f' % float(np.mean(y - lam0)))
    print('   sobre la lambda de la v175 .. %+.4f' % float(np.mean(y - lam)))

    print('\n   por tramo de nivel de competición:')
    print('   %-16s %8s %9s %9s %9s' %
          ('tramo', 'n', 'media real', 'sesgo v174', 'sesgo v175'))
    print('   ' + '-' * 60)
    tramos = [('< 2,4', -9, 2.4), ('2,4 - 2,8', 2.4, 2.8),
              ('2,8 - 3,0', 2.8, 3.0), ('> 3,0', 3.0, 99)]
    filas_tramo = {}
    for etq, lo, hi in tramos:
        m = (d['nivel'] > lo) & (d['nivel'] <= hi)
        if m.sum() < 100:
            continue
        s0 = float(np.mean(y[m] - lam0[m]))
        s1 = float(np.mean(y[m] - lam[m]))
        filas_tramo[etq] = {'n': int(m.sum()), 'sesgo_v174': s0,
                            'sesgo_v175': s1}
        print('   %-16s %8d %9.3f %+9.4f %+9.4f'
              % (etq, m.sum(), float(y[m].mean()), s0, s1))

    print('\n   las 6 competiciones con MÁS sesgo positivo (v175):')
    por_liga = []
    for liga, sub in d.groupby('liga'):
        if len(sub) < 200:
            continue
        por_liga.append((liga, len(sub), float(sub['nivel'].iloc[0]),
                         float(np.mean(sub['goles_total'] - sub['lam']))))
    por_liga.sort(key=lambda t: -t[3])
    for liga, n, niv, s in por_liga[:6]:
        print('     %-22s n=%-6d nivel=%.2f sesgo=%+.4f' % (liga, n, niv, s))
    print('   y las 3 con más sesgo NEGATIVO:')
    for liga, n, niv, s in por_liga[-3:]:
        print('     %-22s n=%-6d nivel=%.2f sesgo=%+.4f' % (liga, n, niv, s))

    # ---- 2) el multiplicador que pide el encargo ----------------------
    print('\n\n2) EL MULTIPLICADOR DEL ENCARGO: lambda x k donde nivel > 2,8')
    alta = (d['nivel'] > 2.8).to_numpy()
    print('   %d partidos en ligas de nivel > 2,8 (%.1f %%)'
          % (alta.sum(), alta.sum() / len(d) * 100))
    print('\n   %-8s %9s %9s %9s %9s' %
          ('k', 'ECE 1,5', 'ECE 2,5', 'ECE 3,5', 'media'))
    print('   ' + '-' * 52)
    tabla_k = {}
    for k in (1.00, 1.05, 1.10):
        lam2 = lam.copy()
        lam2[alta] = lam2[alta] * k
        es = []
        for linea in LINEAS:
            yy = d['over_%.1f_real' % linea].to_numpy(float)
            es.append(ece(p_over(lam2, linea)[alta], yy[alta]))
        tabla_k['%.2f' % k] = es
        print('   %-8.2f %9.4f %9.4f %9.4f %9.4f'
              % (k, es[0], es[1], es[2], float(np.mean(es))))

    # ---- 3) el encogimiento: 0,25 contra 0,30 -------------------------
    print('\n\n3) EL ENCOGIMIENTO HACIA LA CASA: w=0,25 contra w=0,30')
    con = np.isfinite(d['mkt'].to_numpy(float))
    mkt = d['mkt'].to_numpy(float)
    yy = d['over_2.5_real'].to_numpy(float)
    print('   %d partidos con precio de la casa' % con.sum())
    print('\n   %-8s %10s %12s' % ('w', 'ECE todas', 'ECE nivel>2,8'))
    print('   ' + '-' * 36)
    tabla_w = {}
    alta_con = alta & con
    for w in (0.15, 0.20, 0.25, 0.30, 0.40):
        pub = w * p_over(lam, 2.5) + (1.0 - w) * mkt
        e_todas = ece(pub[con], yy[con])
        e_alta = ece(pub[alta_con], yy[alta_con]) if alta_con.sum() > 50 else None
        tabla_w['%.2f' % w] = {'todas': e_todas, 'alta': e_alta}
        print('   %-8.2f %10.4f %12s'
              % (w, e_todas, '%.4f' % e_alta if e_alta else '—'))

    # ---- 4) el ECE actual, que es lo que dispara la regla 3 -----------
    print('\n\n4) EL ECE QUE PIDE MIRAR EL ENCARGO ( > 0,08 dispara w=0,30 )')
    pub25 = W_BASE * p_over(lam, 2.5) + (1.0 - W_BASE) * mkt
    e_pub = ece(pub25[con], yy[con])
    e_crudo = ece(p_over(lam, 2.5), yy)
    print('   ECE de goles 2,5 PUBLICADA (con precio) .. %.4f' % e_pub)
    print('   ECE de goles 2,5 CRUDA (todas) ........... %.4f' % e_crudo)
    print('   -> la regla de w=0,30 %s'
          % ('SE DISPARA' if e_pub > 0.08 else 'NO se dispara'))

    with open('_v177_sesgo_goles_por_liga.json', 'w', encoding='utf-8') as f:
        json.dump({'sesgo_global_v174': float(np.mean(y - lam0)),
                   'sesgo_global_v175': float(np.mean(y - lam)),
                   'por_tramo': filas_tramo,
                   'por_liga': [{'liga': l, 'n': n, 'nivel': niv, 'sesgo': s}
                                for l, n, niv, s in por_liga],
                   'multiplicador': tabla_k, 'encogimiento': tabla_w,
                   'ece_publicada_25': e_pub, 'ece_cruda_25': e_crudo},
                  f, ensure_ascii=False, indent=2)
    print('\nEscrito _v177_sesgo_goles_por_liga.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())


# ---------------------------------------------------------------------------
# 5) LA CORRECCIÓN SIMÉTRICA, Y CON EL NIVEL ESTIMADO HACIA ATRÁS
# ---------------------------------------------------------------------------
# El sesgo del apartado 1 no es «el modelo se queda corto»: es que **encoge
# hacia la media global**. Sobreestima donde se marca poco y subestima donde se
# marca mucho, y con la misma magnitud. Un multiplicador que sólo toca el
# extremo alto arregla media curva y deja la otra media igual de torcida.
#
# Y el nivel de liga se estima con los partidos ANTERIORES de esa competición,
# no con el fichero entero: usar la media de todo el ledger sería mirar el
# resultado antes de predecirlo. Es la misma disciplina que la phi de la v175.
MIN_PREVIOS_NIVEL = 200


def nivel_walk_forward(d):
    """Media de goles de la liga con los partidos anteriores. NaN al principio."""
    nivel = pd.Series(np.nan, index=d.index, dtype=float)
    for liga, sub in d.groupby('liga', sort=False):
        sub = sub.sort_values(['fecha', 'match_id'])
        y = sub['goles_total'].to_numpy(float)
        acum = np.cumsum(y)
        n = np.arange(1, len(y) + 1)
        previos = np.concatenate(([0.0], acum[:-1]))
        cuantos = np.concatenate(([0], n[:-1]))
        with np.errstate(invalid='ignore', divide='ignore'):
            est = np.where(cuantos >= MIN_PREVIOS_NIVEL,
                           previos / np.maximum(cuantos, 1), np.nan)
        nivel.loc[sub.index] = est
    return nivel


def simetrica():
    d = cargar()
    d = d.sort_values(['liga', 'fecha', 'match_id']).reset_index(drop=True)
    d['nivel_wf'] = nivel_walk_forward(d)
    lam = d['lam'].to_numpy(float)
    niv = d['nivel_wf'].to_numpy(float)
    mkt = d['mkt'].to_numpy(float)
    hay = np.isfinite(niv)
    print('\n\n' + '=' * 78)
    print('5) LA CORRECCIÓN SIMÉTRICA: lambda + g * (nivel_liga - lambda)')
    print('=' * 78)
    print('   %d partidos con nivel estimado hacia atrás (%.1f %%)'
          % (hay.sum(), hay.sum() / len(d) * 100))

    print('\n   %-8s %9s %9s %9s %9s %11s' %
          ('g', 'ECE 1,5', 'ECE 2,5', 'ECE 3,5', 'media', 'sesgo >3,0'))
    print('   ' + '-' * 64)
    alta = hay & (niv > 3.0)
    mejor = None
    for g in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
        lam2 = lam.copy()
        lam2[hay] = lam[hay] + g * (niv[hay] - lam[hay])
        lam2 = np.maximum(lam2, 0.05)
        es = []
        for linea in LINEAS:
            yy = d['over_%.1f_real' % linea].to_numpy(float)
            es.append(ece(p_over(lam2, linea)[hay], yy[hay]))
        s_alta = float(np.mean(d['goles_total'].to_numpy(float)[alta]
                               - lam2[alta])) if alta.sum() else float('nan')
        m = float(np.mean(es))
        if mejor is None or m < mejor[1]:
            mejor = (g, m)
        print('   %-8.2f %9.4f %9.4f %9.4f %9.4f %+11.4f'
              % (g, es[0], es[1], es[2], m, s_alta))
    print('\n   mejor g por ECE medio: %.2f (%.4f)' % mejor)

    print('\n   y sobre la cifra PUBLICADA (2,5 encogida al precio, w=0,25):')
    con = np.isfinite(mkt) & hay
    yy = d['over_2.5_real'].to_numpy(float)
    print('   %-8s %10s %12s' % ('g', 'ECE todas', 'ECE nivel>3,0'))
    print('   ' + '-' * 36)
    alta_con = con & (niv > 3.0)
    for g in (0.0, 0.05, 0.10, 0.15, 0.20):
        lam2 = lam.copy()
        lam2[hay] = np.maximum(lam[hay] + g * (niv[hay] - lam[hay]), 0.05)
        pub = W_BASE * p_over(lam2, 2.5) + (1.0 - W_BASE) * mkt
        e_t = ece(pub[con], yy[con])
        e_a = ece(pub[alta_con], yy[alta_con]) if alta_con.sum() > 50 else None
        print('   %-8.2f %10.4f %12s'
              % (g, e_t, '%.4f' % e_a if e_a else '—'))

    print('\n   COMPARADO con el multiplicador asimétrico del encargo')
    print('   (x1,05 sólo donde nivel > 2,8), sobre los MISMOS partidos:')
    alta28 = hay & (niv > 2.8)
    for etq, lam2 in (('sin tocar', lam.copy()),
                      ('x1,05 asimétrico', None),
                      ('g=0,10 simétrico', None)):
        if etq == 'x1,05 asimétrico':
            lam2 = lam.copy()
            lam2[alta28] = lam2[alta28] * 1.05
        elif etq == 'g=0,10 simétrico':
            lam2 = lam.copy()
            lam2[hay] = np.maximum(lam[hay] + 0.10 * (niv[hay] - lam[hay]),
                                   0.05)
        es = [ece(p_over(lam2, L)[hay],
                  d['over_%.1f_real' % L].to_numpy(float)[hay])
              for L in LINEAS]
        print('     %-20s ECE medio %.4f' % (etq, float(np.mean(es))))


# ---------------------------------------------------------------------------
# 6) LA TRAMPA DEL ECE: ¿corrige, o sólo aplana?
# ---------------------------------------------------------------------------
# Encoger la probabilidad hacia la tasa base SIEMPRE mejora el ECE y SIEMPRE
# destruye resolución. El Brier lo descompone —calibración menos resolución— y
# el log-loss castiga igual, así que si la corrección es real los tres mejoran
# a la vez; si sólo mejora el ECE, lo que se está haciendo es aplanar el modelo
# y llamarlo calibrar.
def brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    return float(np.mean((p[ok] - y[ok]) ** 2))


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9)
    y = np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    return float(-np.mean(y[ok] * np.log(p[ok])
                          + (1 - y[ok]) * np.log(1 - p[ok])))


def trampa():
    d = cargar()
    d = d.sort_values(['liga', 'fecha', 'match_id']).reset_index(drop=True)
    d['nivel_wf'] = nivel_walk_forward(d)
    lam = d['lam'].to_numpy(float)
    niv = d['nivel_wf'].to_numpy(float)
    mkt = d['mkt'].to_numpy(float)
    hay = np.isfinite(niv)
    sin_precio = hay & (~np.isfinite(mkt))
    con_precio = hay & np.isfinite(mkt)

    print('\n\n' + '=' * 78)
    print('6) ¿CORRIGE O SÓLO APLANA? Brier y log-loss dicen la verdad')
    print('=' * 78)
    print('   n con nivel: %d · sin precio de la casa: %d · con precio: %d'
          % (hay.sum(), sin_precio.sum(), con_precio.sum()))
    print('\n   CRUDA, media de las tres lineas')
    print('   %-8s %9s %9s %9s' % ('g', 'ECE', 'Brier', 'logloss'))
    print('   ' + '-' * 40)
    for g in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
        lam2 = lam.copy()
        lam2[hay] = np.maximum(lam[hay] + g * (niv[hay] - lam[hay]), 0.05)
        es, bs, ls = [], [], []
        for L in LINEAS:
            yy = d['over_%.1f_real' % L].to_numpy(float)
            pp = p_over(lam2, L)
            es.append(ece(pp[hay], yy[hay]))
            bs.append(brier(pp[hay], yy[hay]))
            ls.append(logloss(pp[hay], yy[hay]))
        print('   %-8.2f %9.4f %9.4f %9.4f'
              % (g, np.mean(es), np.mean(bs), np.mean(ls)))

    print('\n   SIN PRECIO DE LA CASA (la cruda ES lo que se publica), 2,5')
    print('   %-8s %9s %9s %9s' % ('g', 'ECE', 'Brier', 'logloss'))
    print('   ' + '-' * 40)
    yy = d['over_2.5_real'].to_numpy(float)
    for g in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
        lam2 = lam.copy()
        lam2[hay] = np.maximum(lam[hay] + g * (niv[hay] - lam[hay]), 0.05)
        pp = p_over(lam2, 2.5)
        print('   %-8.2f %9.4f %9.4f %9.4f'
              % (g, ece(pp[sin_precio], yy[sin_precio]),
                 brier(pp[sin_precio], yy[sin_precio]),
                 logloss(pp[sin_precio], yy[sin_precio])))

    print('\n   CON PRECIO (publicada = 0,25*modelo + 0,75*mercado), 2,5')
    print('   %-8s %9s %9s %9s' % ('g', 'ECE', 'Brier', 'logloss'))
    print('   ' + '-' * 40)
    for g in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
        lam2 = lam.copy()
        lam2[hay] = np.maximum(lam[hay] + g * (niv[hay] - lam[hay]), 0.05)
        pub = W_BASE * p_over(lam2, 2.5) + (1.0 - W_BASE) * mkt
        print('   %-8.2f %9.4f %9.4f %9.4f'
              % (g, ece(pub[con_precio], yy[con_precio]),
                 brier(pub[con_precio], yy[con_precio]),
                 logloss(pub[con_precio], yy[con_precio])))
