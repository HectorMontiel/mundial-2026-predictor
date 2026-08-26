#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v175 — ¿CUÁNTO DEBE PESAR EL H2H EN LA LAMBDA? EL PESO SALE DE LOS DATOS.

EL ENCARGO
----------
«Aumentar el peso del H2H en la lambda, especialmente en ligas donde el
historial es determinista. Pesos a calibrar con el histórico (regresión o
gradiente).»

Hoy `contexto_partido.factor_lambda` mete el H2H con un peso de **0,5** frente
a la forma reciente. Ese 0,5 se escribió a mano en la v174 y es el pendiente
número 2 del traspaso: nunca se midió contra el ECE.

CÓMO SE MIDE, Y POR QUÉ ASÍ
----------------------------
La pregunta no es «¿los cruces dicen algo?» —claro que dicen algo— sino «¿dicen
algo que la lambda del modelo NO sepa ya?». Esa es exactamente la pregunta que
responde una regresión sobre el RESIDUO:

    y − λ  =  β · (goles_del_H2H − λ)  +  ruido

Si β sale 0, el modelo ya se sabía el H2H y añadirlo es contar dos veces. Si β
sale 0,30, entonces la lambda debería moverse un 30 % de la distancia hacia lo
que dicen los cruces — ni más ni menos, y ese número ES el peso que se busca.

SIN MIRAR EL FUTURO
-------------------
El H2H de cada partido se calcula SÓLO con los cruces anteriores a su fecha.
Un H2H que incluya el partido que se está prediciendo daría un β precioso y
completamente falso.

Y SE COMPARA CONTRA EL ECE, QUE ES LO QUE IMPORTA
-------------------------------------------------
Un β distinto de cero no basta: hay que ver si mover la lambda con él MEJORA la
calibración de las líneas que la aplicación publica (1,5 · 2,5 · 3,5). Se prueba
el β medido, el 0,5 que hay hoy escrito, y varios intermedios.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

MIN_H2H = 4          # el mismo mínimo que usa `contexto_partido`
N_H2H = 10           # la ventana de cruces de `contexto_partido`
N_FORMA = 5
LINEAS = (1.5, 2.5, 3.5)


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


def _fichero_de(liga):
    for cand in ('historico_%s.csv' % liga, 'historico_fotmob_%s.csv' % liga):
        if os.path.exists(cand):
            return cand
    return None


def señales_de_liga(liga, ids_necesarios):
    """
    Para cada `match_id` pedido: goles del H2H previo y de la forma previa.

    Devuelve `{match_id: {'h2h': media_goles_cruces, 'n_h2h': n,
                          'forma': media_goles_de_los_dos_en_sus_ultimos 5}}`
    con `None` donde no hay muestra. Todo estrictamente ANTERIOR a la fecha.
    """
    ruta = _fichero_de(liga)
    if not ruta:
        return {}
    try:
        d = pd.read_csv(ruta, low_memory=False)
    except Exception:
        return {}
    if not {'MATCH_ID', 'home_team', 'away_team',
            'home_goals', 'away_goals', 'date'}.issubset(d.columns):
        return {}
    d = d.dropna(subset=['home_goals', 'away_goals', 'home_team', 'away_team'])
    d = d.sort_values('date').reset_index(drop=True)
    d['total'] = d['home_goals'].astype(float) + d['away_goals'].astype(float)

    cruces = defaultdict(list)      # par ordenado alfabéticamente -> [totales]
    equipos = defaultdict(list)     # equipo -> [totales de sus partidos]
    salida = {}
    for mid, h, a, tot in zip(d['MATCH_ID'], d['home_team'], d['away_team'],
                              d['total']):
        par = tuple(sorted((str(h), str(a))))
        if mid in ids_necesarios:
            prev = cruces[par]
            sh, sa = equipos[str(h)][-N_FORMA:], equipos[str(a)][-N_FORMA:]
            # v175 — LA MISMA VENTANA QUE PRODUCCION: los ultimos 10.
            # `contexto_partido._goles_del_h2h` mira `N_H2H` cruces,
            # que son los que la tarjeta enseña. Medir sobre TODOS
            # los cruces daria un beta que luego nadie aplica.
            salida[mid] = {
                'h2h': (float(np.mean(prev[-N_H2H:]))
                        if len(prev) >= MIN_H2H else None),
                'n_h2h': len(prev),
                'forma': (float(np.mean(sh + sa))
                          if len(sh) >= 3 and len(sa) >= 3 else None)}
        cruces[par].append(float(tot))
        equipos[str(h)].append(float(tot))
        equipos[str(a)].append(float(tot))
    return salida


def main():
    d = pd.read_csv('pick_ledger_totales.csv')
    d['lam'] = d['lam_h'].astype(float) + d['lam_a'].astype(float)
    d = d[np.isfinite(d['lam']) & (d['lam'] > 0)].copy()
    print('=' * 78)
    print('v175 — EL PESO DEL H2H EN LA LAMBDA, MEDIDO SOBRE %d PARTIDOS'
          % len(d))
    print('=' * 78)

    h2h, n_h2h, forma = [], [], []
    for liga, sub in d.groupby('liga'):
        s = señales_de_liga(liga, set(sub['match_id']))
        for mid in sub['match_id']:
            r = s.get(mid) or {}
            h2h.append(r.get('h2h'))
            n_h2h.append(r.get('n_h2h') or 0)
            forma.append(r.get('forma'))
    d['h2h'] = [np.nan if x is None else x for x in h2h]
    d['n_h2h'] = n_h2h
    d['forma'] = [np.nan if x is None else x for x in forma]

    lam = d['lam'].to_numpy(float)
    y = d['goles_total'].to_numpy(float)
    resid = y - lam

    print('\n1) COBERTURA DE LAS SEÑALES')
    print('   partidos con H2H de >= %d cruces previos: %d (%.1f %%)'
          % (MIN_H2H, np.isfinite(d['h2h']).sum(),
             np.isfinite(d['h2h']).sum() / len(d) * 100))
    print('   partidos con forma previa de los dos:     %d (%.1f %%)'
          % (np.isfinite(d['forma']).sum(),
             np.isfinite(d['forma']).sum() / len(d) * 100))

    print('\n\n2) LA REGRESIÓN SOBRE EL RESIDUO:  y − λ = β · (señal − λ)')
    print('   β = 0 significa «el modelo ya lo sabía».')
    print('\n%-10s %8s %10s %10s %10s' %
          ('señal', 'n', 'beta', 'error est.', 't'))
    print('-' * 78)
    betas = {}
    for nombre in ('h2h', 'forma'):
        x = d[nombre].to_numpy(float) - lam
        ok = np.isfinite(x) & np.isfinite(resid)
        if ok.sum() < 500:
            print('%-10s %8d  (muestra insuficiente)' % (nombre, ok.sum()))
            continue
        xx, rr = x[ok], resid[ok]
        beta = float(np.sum(xx * rr) / np.sum(xx * xx))
        # error estándar de una regresión por el origen
        s2 = float(np.sum((rr - beta * xx) ** 2) / (len(xx) - 1))
        se = float(np.sqrt(s2 / np.sum(xx * xx)))
        betas[nombre] = beta
        print('%-10s %8d %10.4f %10.4f %10.2f'
              % (nombre, ok.sum(), beta, se, beta / se if se else 0.0))

    # las dos juntas: ¿aporta el H2H algo que la forma no tenga?
    x1 = d['h2h'].to_numpy(float) - lam
    x2 = d['forma'].to_numpy(float) - lam
    ok = np.isfinite(x1) & np.isfinite(x2) & np.isfinite(resid)
    if ok.sum() > 500:
        X = np.column_stack([x1[ok], x2[ok]])
        coef, *_ = np.linalg.lstsq(X, resid[ok], rcond=None)
        print('\n   las dos a la vez (n=%d):  beta_h2h=%.4f  beta_forma=%.4f'
              % (ok.sum(), coef[0], coef[1]))
        print('   -> si beta_h2h cae mucho aquí, el H2H no añade nada')
        print('      que la forma reciente no tuviera ya.')
        betas['h2h_conjunta'] = float(coef[0])

    print('\n\n3) ¿MEJORA EL ECE MOVER LA LAMBDA CON ESE PESO?')
    print('   λ\' = λ + w · (goles_del_H2H − λ), sólo donde hay H2H.')
    con = np.isfinite(d['h2h'].to_numpy(float))
    print('   se evalúa sobre los %d partidos con H2H.\n' % con.sum())
    señal = np.where(con, d['h2h'].to_numpy(float) - lam, 0.0)
    print('%-8s %9s %9s %9s %9s' %
          ('w', 'ECE 1,5', 'ECE 2,5', 'ECE 3,5', 'media'))
    print('-' * 78)
    tabla = {}
    pesos = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.00]
    if 'h2h' in betas:
        pesos.append(round(betas['h2h'], 3))
    for w in sorted(set(pesos)):
        lam2 = np.maximum(lam + w * señal, 0.05)
        es = []
        for linea in LINEAS:
            yy = d['over_%.1f_real' % linea].to_numpy(float)
            es.append(ece(p_over(lam2, linea)[con], yy[con]))
        tabla['%.3f' % w] = es
        print('%-8.3f %9.4f %9.4f %9.4f %9.4f'
              % (w, es[0], es[1], es[2], float(np.mean(es))))

    mejor = min(tabla.items(), key=lambda kv: float(np.mean(kv[1])))
    print('\n   mejor peso por ECE medio: w = %s (%.4f)'
          % (mejor[0], float(np.mean(mejor[1]))))
    print('   el peso escrito hoy en `contexto_partido` es 0,5 relativo a la')
    print('   forma, que sobre la lambda equivale a mover la mitad del camino.')

    with open('_v175_h2h_en_la_lambda.json', 'w', encoding='utf-8') as f:
        json.dump({'betas': betas, 'ece_por_peso': tabla,
                   'n': int(con.sum()), 'mejor_peso': mejor[0]}, f,
                  ensure_ascii=False, indent=2)
    print('\nEscrito _v175_h2h_en_la_lambda.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())


# ---------------------------------------------------------------------------
# 4) LA PRUEBA DECISIVA: ¿sobrevive al encogimiento hacia el precio de la casa?
# ---------------------------------------------------------------------------
# Es la misma prueba que tumbo a la binomial negativa (_v175_goles_binomial_
# negativa.py): la aplicacion NO publica la probabilidad cruda, la publica
# encogida con w=0,25 hacia el precio. Una mejora que solo existe en la cruda
# se diluye cuatro veces y puede desaparecer entera.
W_MODELO = 0.25


def devig2(c1, c2):
    try:
        c1, c2 = float(c1), float(c2)
    except (TypeError, ValueError):
        return np.nan
    if not (c1 > 1 and c2 > 1):
        return np.nan
    return (1.0 / c1) / (1.0 / c1 + 1.0 / c2)


def publicada():
    d = pd.read_csv('pick_ledger_totales.csv')
    d['lam'] = d['lam_h'].astype(float) + d['lam_a'].astype(float)
    d = d[np.isfinite(d['lam']) & (d['lam'] > 0)].copy()
    h2h, forma = [], []
    for liga, sub in d.groupby('liga'):
        s = señales_de_liga(liga, set(sub['match_id']))
        for mid in sub['match_id']:
            r = s.get(mid) or {}
            h2h.append(r.get('h2h'))
            forma.append(r.get('forma'))
    d['h2h'] = [np.nan if x is None else x for x in h2h]
    d['forma'] = [np.nan if x is None else x for x in forma]

    lam = d['lam'].to_numpy(float)
    mkt = np.array([devig2(a_, b_) for a_, b_ in
                    zip(d['cuota_over25'], d['cuota_under25'])], float)
    tiene_h2h = np.isfinite(d['h2h'].to_numpy(float))
    con = np.isfinite(mkt) & tiene_h2h
    yy = d['over_2.5_real'].to_numpy(float)[con]

    print('\n\n' + '=' * 78)
    print('4) LA CIFRA QUE SE PUBLICA: 2,5 encogida al precio (w=%.2f)'
          % W_MODELO)
    print('=' * 78)
    print('   %d partidos con precio de la casa Y con H2H previo.\n' % con.sum())
    señal = d['h2h'].to_numpy(float) - lam
    señal_f = d['forma'].to_numpy(float) - lam

    print('%-26s %9s %9s' % ('lambda', 'ECE cruda', 'ECE publicada'))
    print('-' * 78)
    filas = [('sin tocar (produccion hoy)', np.zeros_like(lam), 0.0)]
    for w in (0.15, 0.20, 0.30, 0.356, 0.50):
        filas.append(('con H2H, w=%.3f' % w, señal, w))
    for etq, s_, w in filas:
        lam2 = np.maximum(lam + w * s_, 0.05)
        cruda = p_over(lam2, 2.5)
        pub = W_MODELO * cruda + (1.0 - W_MODELO) * mkt
        print('%-26s %9.4f %9.4f'
              % (etq, ece(cruda[con], yy), ece(pub[con], yy)))
    # y la version conjunta (H2H + forma con los coeficientes de la regresion
    # multiple, que es la que no cuenta dos veces lo mismo)
    ok = np.isfinite(señal) & np.isfinite(señal_f)
    s_join = np.where(ok, 0.204 * np.nan_to_num(señal)
                      + 0.244 * np.nan_to_num(señal_f), 0.0)
    lam2 = np.maximum(lam + s_join, 0.05)
    cruda = p_over(lam2, 2.5)
    pub = W_MODELO * cruda + (1.0 - W_MODELO) * mkt
    print('%-26s %9.4f %9.4f' % ('H2H+forma (0,204/0,244)',
                                 ece(cruda[con], yy), ece(pub[con], yy)))
    print('\n   Y SIN PRECIO DE LA CASA — los partidos que Playdoit no cotiza,')
    print('   donde la cruda ES la que se publica:')
    sin = (~np.isfinite(mkt)) & tiene_h2h
    yy2 = d['over_2.5_real'].to_numpy(float)[sin]
    for etq, s_, w in filas:
        lam2 = np.maximum(lam + w * s_, 0.05)
        print('     %-24s n=%-6d ECE %.4f'
              % (etq, sin.sum(), ece(p_over(lam2, 2.5)[sin], yy2)))
