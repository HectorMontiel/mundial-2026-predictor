#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v175 — ¿SOBREDISPERSAN LOS GOLES? MEDIDO, NO SUPUESTO.

EL ENCARGO
----------
«Cambiar de Poisson simple a Binomial Negativa si la liga muestra
sobredispersión (ya se hace para córners/tarjetas). Ajustar el parámetro `r`
por liga.»

Es una hipótesis contrastable y este proyecto tiene con qué contrastarla sin
pedir un solo dato nuevo: `pick_ledger_totales.csv` guarda, de 47.794 partidos
walk-forward, la lambda que el modelo dio de cada bando (`lam_h`, `lam_a`), los
goles que se marcaron de verdad y la probabilidad que la aplicación publicó en
tres líneas (1,5 · 2,5 · 3,5).

QUÉ SE MIDE, Y CONTRA QUÉ
--------------------------
Tres formas de repartir la probabilidad sobre el MISMO nivel esperado:

    matriz   la de producción hoy: suma sobre la matriz de marcador
    poisson  Poisson con lambda = lam_h + lam_a
    nbinom   binomial negativa con la misma media y la dispersión de la liga

La dispersión NO se estima con var/media a secas, que es lo que valdría si
todos los partidos tuvieran la misma lambda. Con lambda variable, un Poisson
puro ya produce varianza `E[λ] + Var(λ)`, así que medir var/media contaría como
sobredispersión lo que sólo es que unos partidos son más abiertos que otros.
Lo que se usa es el estadístico de Pearson:

    φ = (1/n) · Σ (y_i − λ_i)² / λ_i

que vale 1 exactamente cuando el Poisson con ESAS lambdas explica la varianza,
y sube por encima de 1 cuando queda racimo sin explicar.

Y SE ESTIMA HACIA ATRÁS, NO SOBRE EL FUTURO
--------------------------------------------
φ de cada partido se calcula con los partidos ANTERIORES de su liga (ventana
expansiva, mínimo `MIN_PREVIOS`). Estimarla sobre el fichero entero sería
mirar el resultado antes de predecirlo, que es justo lo que el ledger
walk-forward existe para evitar.

TAMBIÉN SE MIDE LA VERSIÓN QUE SE PUBLICA
------------------------------------------
La aplicación no enseña la probabilidad cruda: la encoge hacia el precio de la
casa con w=0,25 (v166). En la línea de 2,5 hay cuota en el ledger, así que la
comparación se repite ya encogida, que es la cifra que el usuario ve.
"""
import json
import sys

import numpy as np
import pandas as pd
from scipy import stats

LINEAS = (1.5, 2.5, 3.5)
MIN_PREVIOS = 200        # por debajo de esto no se estima phi: se usa Poisson
PHI_MIN = 1.02           # por debajo de esto la binomial negativa es Poisson
W_MODELO = 0.25          # el encogimiento medido de la v166


def ece(p, y, n_bins: int = 10):
    """Error de calibración esperado, en 10 tramos de probabilidad."""
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


def brier(p, y):
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    return float(np.mean((p[ok] - y[ok]) ** 2))


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9)
    y = np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def p_poisson(lam, linea):
    return 1.0 - stats.poisson.cdf(int(np.floor(linea)), lam)


def p_nbinom(lam, linea, phi):
    """
    P(total > linea) con media `lam` y razón varianza/media `phi`.

    Misma parametrización que `rendimiento_equipos.prob_mas_de`, que es la que
    ya usan córners, tarjetas y remates: var = phi·m -> r = m/(phi−1).
    """
    lam = np.asarray(lam, float)
    phi = np.asarray(phi, float)
    salida = np.empty_like(lam)
    flojo = phi <= PHI_MIN
    if flojo.any():
        salida[flojo] = p_poisson(lam[flojo], linea)
    fuerte = ~flojo
    if fuerte.any():
        m = lam[fuerte]
        f = phi[fuerte]
        r = m / (f - 1.0)
        pp = r / (r + m)
        salida[fuerte] = 1.0 - stats.nbinom.cdf(int(np.floor(linea)), r, pp)
    return salida


def phi_walk_forward(d):
    """
    φ de cada partido, estimada SOLO con los anteriores de su misma liga.

    Devuelve una serie alineada con `d`. Los primeros `MIN_PREVIOS` partidos de
    cada liga salen a 1,0 —Poisson— porque no hay con qué estimar nada.
    """
    phi = pd.Series(1.0, index=d.index, dtype=float)
    for liga, sub in d.groupby('liga', sort=False):
        sub = sub.sort_values(['fecha', 'match_id'])
        lam = sub['lam_total'].to_numpy(float)
        y = sub['goles_total'].to_numpy(float)
        # (y − λ)² / λ acumulado hacia atrás
        pear = np.where(lam > 0, (y - lam) ** 2 / np.maximum(lam, 1e-9), np.nan)
        acum = np.nancumsum(pear)
        n = np.arange(1, len(pear) + 1)
        # el valor para el partido i usa los i−1 anteriores
        previos = np.concatenate(([0.0], acum[:-1]))
        cuantos = np.concatenate(([0], n[:-1]))
        with np.errstate(invalid='ignore', divide='ignore'):
            est = np.where(cuantos >= MIN_PREVIOS, previos / np.maximum(cuantos, 1), 1.0)
        phi.loc[sub.index] = np.clip(est, 1.0, 3.0)
    return phi


def devig2(c1, c2):
    """Probabilidad sin margen del primer lado de un mercado de dos vías."""
    try:
        c1, c2 = float(c1), float(c2)
    except (TypeError, ValueError):
        return np.nan
    if not (c1 > 1 and c2 > 1):
        return np.nan
    i1, i2 = 1.0 / c1, 1.0 / c2
    return i1 / (i1 + i2)


def main():
    d = pd.read_csv('pick_ledger_totales.csv')
    d['lam_total'] = d['lam_h'].astype(float) + d['lam_a'].astype(float)
    d = d[np.isfinite(d['lam_total']) & (d['lam_total'] > 0)].copy()
    d = d.sort_values(['liga', 'fecha', 'match_id']).reset_index(drop=True)
    print('=' * 78)
    print('v175 — ¿SOBREDISPERSAN LOS GOLES? %d partidos walk-forward' % len(d))
    print('=' * 78)

    d['phi'] = phi_walk_forward(d)

    # ---- 1) ¿hay sobredispersión, y cuánta? ---------------------------
    lam = d['lam_total'].to_numpy(float)
    y = d['goles_total'].to_numpy(float)
    phi_global = float(np.mean((y - lam) ** 2 / lam))
    print('\n1) DISPERSIÓN DE PEARSON SOBRE EL LEDGER ENTERO')
    print('   φ global = %.4f   (1,00 = el Poisson explica la varianza)'
          % phi_global)
    print('   media de goles observada %.3f · lambda media del modelo %.3f'
          % (y.mean(), lam.mean()))

    por_liga = []
    for liga, sub in d.groupby('liga'):
        if len(sub) < MIN_PREVIOS:
            continue
        l_, y_ = sub['lam_total'].to_numpy(float), sub['goles_total'].to_numpy(float)
        por_liga.append((liga, len(sub), float(np.mean((y_ - l_) ** 2 / l_))))
    por_liga.sort(key=lambda t: -t[2])
    print('\n   φ por competición (las 8 más y las 5 menos dispersas)')
    for liga, n, f in por_liga[:8]:
        print('     %-24s n=%-6d φ=%.4f' % (liga, n, f))
    print('     ...')
    for liga, n, f in por_liga[-5:]:
        print('     %-24s n=%-6d φ=%.4f' % (liga, n, f))
    n_sobre = sum(1 for _, _, f in por_liga if f > PHI_MIN)
    print('\n   %d de %d competiciones por encima de φ=%.2f'
          % (n_sobre, len(por_liga), PHI_MIN))

    # ---- 2) las tres formas, línea a línea ----------------------------
    print('\n\n2) CALIBRACIÓN LÍNEA A LÍNEA (probabilidad CRUDA)')
    print('%-8s %-10s %8s %9s %9s %9s' %
          ('línea', 'forma', 'n', 'ECE', 'Brier', 'logloss'))
    print('-' * 78)
    resumen = {}
    for linea in LINEAS:
        col_p = 'p_over_%.1f' % linea
        col_y = 'over_%.1f_real' % linea
        if col_p not in d.columns or col_y not in d.columns:
            continue
        yy = d[col_y].to_numpy(float)
        formas = {
            'matriz': d[col_p].to_numpy(float),
            'poisson': p_poisson(lam, linea),
            'nbinom': p_nbinom(lam, linea, d['phi'].to_numpy(float)),
        }
        for nombre, pp in formas.items():
            e, b, l = ece(pp, yy), brier(pp, yy), logloss(pp, yy)
            resumen['%.1f/%s' % (linea, nombre)] = {
                'n': int(np.isfinite(pp).sum()), 'ece': e, 'brier': b,
                'logloss': l}
            print('%-8.1f %-10s %8d %9.4f %9.4f %9.4f'
                  % (linea, nombre, np.isfinite(pp).sum(), e, b, l))
        print('-' * 78)

    # ---- 3) y como se PUBLICA: encogida hacia la casa ------------------
    print('\n\n3) LA CIFRA QUE SE PUBLICA (encogida al precio, w=%.2f)'
          % W_MODELO)
    print('   Sólo la línea de 2,5: es la única con cuota en el ledger.')
    mkt = np.array([devig2(a_, b_) for a_, b_ in
                    zip(d['cuota_over25'], d['cuota_under25'])], float)
    con = np.isfinite(mkt)
    print('   %d partidos con precio de la casa (%.1f %%)'
          % (con.sum(), con.sum() / len(d) * 100))
    yy = d['over_2.5_real'].to_numpy(float)[con]
    print('\n%-12s %8s %9s %9s %9s' % ('forma', 'n', 'ECE', 'Brier', 'logloss'))
    print('-' * 78)
    formas = {
        'matriz': d['p_over_2.5'].to_numpy(float)[con],
        'poisson': p_poisson(lam, 2.5)[con],
        'nbinom': p_nbinom(lam, 2.5, d['phi'].to_numpy(float))[con],
    }
    formas['mercado'] = mkt[con]
    for nombre, pp in formas.items():
        if nombre != 'mercado':
            pp = W_MODELO * pp + (1.0 - W_MODELO) * mkt[con]
        e, b, l = ece(pp, yy), brier(pp, yy), logloss(pp, yy)
        resumen['2.5/publicada/%s' % nombre] = {'n': int(len(pp)), 'ece': e,
                                                'brier': b, 'logloss': l}
        print('%-12s %8d %9.4f %9.4f %9.4f' % (nombre, len(pp), e, b, l))

    # ---- 4) el veredicto ----------------------------------------------
    print('\n\n4) VEREDICTO')
    mejoras = []
    for linea in LINEAS:
        a = resumen.get('%.1f/matriz' % linea)
        c = resumen.get('%.1f/nbinom' % linea)
        if a and c and a['ece'] and c['ece']:
            mejoras.append((linea, a['ece'], c['ece'],
                            (a['ece'] - c['ece']) / a['ece'] * 100))
    for linea, e_a, e_c, pct in mejoras:
        signo = 'MEJORA' if pct > 0 else 'EMPEORA'
        print('   línea %.1f: matriz ECE %.4f -> nbinom %.4f  (%s %+.1f %%)'
              % (linea, e_a, e_c, signo, pct))
    gana = sum(1 for _, _, _, p in mejoras if p > 0)
    print('\n   la binomial negativa gana en %d de %d líneas'
          % (gana, len(mejoras)))
    if gana < len(mejoras):
        print('   -> NO se adopta como sustituto de la matriz de marcador.')
    else:
        print('   -> se adopta.')

    with open('_v175_goles_binomial_negativa.json', 'w', encoding='utf-8') as f:
        json.dump({'phi_global': phi_global,
                   'phi_por_liga': {l: {'n': n, 'phi': p}
                                    for l, n, p in por_liga},
                   'resumen': resumen}, f, ensure_ascii=False, indent=2)
    print('\nEscrito _v175_goles_binomial_negativa.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())


# ---------------------------------------------------------------------------
# 5) LA REGLA CONDICIONAL DEL ENCARGO: binomial negativa SOLO donde dispersa
# ---------------------------------------------------------------------------
def condicional():
    d = pd.read_csv('pick_ledger_totales.csv')
    d['lam_total'] = d['lam_h'].astype(float) + d['lam_a'].astype(float)
    d = d[np.isfinite(d['lam_total']) & (d['lam_total'] > 0)].copy()
    d = d.sort_values(['liga', 'fecha', 'match_id']).reset_index(drop=True)
    d['phi'] = phi_walk_forward(d)
    lam = d['lam_total'].to_numpy(float)
    phi = d['phi'].to_numpy(float)

    print('\n\n' + '=' * 78)
    print('5) LA REGLA DEL ENCARGO: nbinom SOLO donde la liga sobredispersa')
    print('=' * 78)
    mkt = np.array([devig2(a_, b_) for a_, b_ in
                    zip(d['cuota_over25'], d['cuota_under25'])], float)
    con = np.isfinite(mkt)

    print('\n%-6s %-7s %8s %9s %9s %9s' %
          ('corte', 'linea', 'n_nb', 'ECE cruda', 'ECE matriz', 'delta %'))
    print('-' * 78)
    filas = []
    for corte in (1.02, 1.10, 1.20, 1.30):
        usa_nb = phi > corte
        for linea in LINEAS:
            col_p = 'p_over_%.1f' % linea
            col_y = 'over_%.1f_real' % linea
            yy = d[col_y].to_numpy(float)
            base = d[col_p].to_numpy(float)
            mezcla = base.copy()
            if usa_nb.any():
                mezcla[usa_nb] = p_nbinom(lam[usa_nb], linea, phi[usa_nb])
            e_mix, e_base = ece(mezcla, yy), ece(base, yy)
            filas.append((corte, linea, int(usa_nb.sum()), e_mix, e_base))
            print('%-6.2f %-7.1f %8d %9.4f %9.4f %+9.1f'
                  % (corte, linea, usa_nb.sum(), e_mix, e_base,
                     (e_base - e_mix) / e_base * 100))
        print('-' * 78)

    print('\n   y sobre la cifra PUBLICADA (2,5 encogida al precio, w=0,25)')
    print('   %-6s %8s %9s %9s' % ('corte', 'n', 'ECE', 'delta vs matriz %'))
    yy = d['over_2.5_real'].to_numpy(float)[con]
    base_pub = W_MODELO * d['p_over_2.5'].to_numpy(float)[con] \
        + (1.0 - W_MODELO) * mkt[con]
    e_base = ece(base_pub, yy)
    print('   %-6s %8d %9.4f %9s' % ('matriz', len(yy), e_base, '—'))
    for corte in (1.02, 1.10, 1.20, 1.30):
        usa_nb = (phi > corte)[con]
        cruda = d['p_over_2.5'].to_numpy(float)[con].copy()
        if usa_nb.any():
            cruda[usa_nb] = p_nbinom(lam[con][usa_nb], 2.5, phi[con][usa_nb])
        pub = W_MODELO * cruda + (1.0 - W_MODELO) * mkt[con]
        e = ece(pub, yy)
        print('   %-6.2f %8d %9.4f %+9.1f'
              % (corte, usa_nb.sum(), e, (e_base - e) / e_base * 100))

    print('\n   NOTA: en el ledger solo la linea de 2,5 tiene precio. Las')
    print('   lineas de la cola (3,5 · 4,5 · 5,5), que es donde la binomial')
    print('   negativa cambia mas, no se pueden medir ya encogidas porque')
    print('   nadie guardo su cuota. Se dice en vez de suponerlo.')


if __name__ == '__main__' and '--condicional' in sys.argv:
    condicional()
