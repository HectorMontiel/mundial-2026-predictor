# -*- coding: utf-8 -*-
"""
v333 — VALIDACIÓN 1: ¿EL MOTOR DE MERCADO ACIERTA MEJOR QUE NUESTRO MODELO?

`motor_mercado.py` saca las λ de las cuotas principales de la casa (1X2 sin
margen y, si lo hay, más/menos 2,5) y con ellas da la probabilidad de todo
lo demás. Antes de usarlo para buscar patas mal puestas tiene que demostrar
que esas probabilidades son BUENAS en partidos que no ha visto.

  · histórico: pick_ledger*.csv (60 mil partidos con 1X2 del mercado y
    40 mil con más/menos 2,5; el modelo propio fuera de muestra al lado)
  · ρ de Dixon-Coles: se elige con el 70 % antiguo (log-loss de empate,
    más de 1,5 y más de 3,5); se juzga con el 30 % reciente
  · se comparan log-loss y Brier del motor, del modelo y de la mezcla de
    los dos, en mercados que el motor NO usó para despejar (más de 1,5,
    más de 3,5 y, sin cuota de goles, más de 2,5)
  · y lo que importa para los verdes: en la franja 70-80 %, ¿qué acierta lo
    que dice el motor frente a lo que dice el modelo?
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

import motor_mercado as mm

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(333)


def datos() -> pd.DataFrame:
    t = pd.read_csv('pick_ledger_totales.csv')
    r = pd.read_csv('pick_ledger.csv').drop(columns=['goles_local', 'goles_visit',
                                                      'fecha', 'pliegue'])
    d = t.merge(r, on=['liga', 'match_id'], how='inner')
    for k in ('cuota_over25', 'cuota_under25'):
        d[k] = d[k + '_y'].fillna(d[k + '_x'])
    d = d[d.goles_local.notna() & d.cuota_home.notna() & d.cuota_draw.notna()
          & d.cuota_away.notna()].copy()
    d['fecha'] = pd.to_datetime(d.fecha)
    ih, ix, ia = 1 / d.cuota_home, 1 / d.cuota_draw, 1 / d.cuota_away
    s = ih + ix + ia
    d['m1'], d['mx'], d['m2'] = ih / s, ix / s, ia / s
    io_, iu = 1 / d.cuota_over25, 1 / d.cuota_under25
    d['mo'] = io_ / (io_ + iu)
    tot = d.goles_local + d.goles_visit
    d['y_15'], d['y_25'], d['y_35'] = (tot > 1.5).astype(int), (tot > 2.5).astype(int), (tot > 3.5).astype(int)
    d['y_x'] = (d.goles_local == d.goles_visit).astype(int)
    d['y_btts'] = ((d.goles_local > 0) & (d.goles_visit > 0)).astype(int)
    return d.sort_values('fecha').reset_index(drop=True)


def ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def motor(d, rho):
    T = mm.tabla(rho)
    i = mm.lote(d.m1.values, d.m2.values, d.mo.values, rho=rho)
    return {k: T['P'][k][i] for k in ('Empate', 'Más de 1.5', 'Más de 2.5',
                                       'Más de 3.5', 'Ambos marcan sí')}


def main():
    d = datos()
    dias = np.sort(d.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    M, J = d[d.fecha < corte], d[d.fecha >= corte]
    print('partidos con 1X2 del mercado: %d (con más/menos 2,5: %d) · corte %s'
          % (len(d), d.mo.notna().sum(), str(corte)[:10]))
    # 1. ρ con el tramo de mirar
    print('\n1. ρ de Dixon-Coles elegido con el tramo de mirar (log-loss medio):')
    mejor, ll_m = None, 9
    for rho in (0.0, -0.03, -0.06, -0.09, -0.12):
        P = motor(M, rho)
        v = np.mean([ll(M.y_x, P['Empate']), ll(M.y_15, P['Más de 1.5']),
                     ll(M.y_35, P['Más de 3.5'])])
        print('   ρ %+.2f → %.5f' % (rho, v))
        if v < ll_m:
            mejor, ll_m = rho, v
    print('   elegido ρ = %+.2f' % mejor)
    P = motor(J, mejor)
    out = {'rho': mejor, 'corte': str(corte)[:10]}
    # 2. log-loss en el juicio
    print('\n2. JUICIO (%d partidos): log-loss y Brier, menor es mejor' % len(J))
    print('   mercado        motor             modelo            mezcla 50/50')
    comps = [('Más de 1.5', 'y_15', 'p_over_1.5', J.index),
             ('Más de 3.5', 'y_35', 'p_over_3.5', J.index),
             ('Más de 2.5 *', 'y_25', 'p_over_2.5', J[J.mo.isna()].index)]
    out['juicio'] = {}
    for nom, y, pm, idx in comps:
        Jx = J.loc[idx]
        pe = pd.Series(P[nom.replace(' *', '')], index=J.index).loc[idx]
        pmod = Jx[pm]
        mez = (pe + pmod) / 2
        r = [(ll(Jx[y], q), float(np.mean((Jx[y] - q) ** 2))) for q in (pe, pmod, mez)]
        print('   %-13s %.4f / %.4f   %.4f / %.4f   %.4f / %.4f   (n %d)'
              % (nom, r[0][0], r[0][1], r[1][0], r[1][1], r[2][0], r[2][1], len(Jx)))
        out['juicio'][nom] = {'motor': r[0], 'modelo': r[1], 'mezcla': r[2], 'n': len(Jx)}
    print('   (* sólo partidos SIN cuota de goles: el motor lo saca del 1X2)')
    pe = pd.Series(P['Ambos marcan sí'], index=J.index)
    print('   Ambos marcan  motor %.4f · (la probabilidad del modelo en el '
          'histórico está rota)' % ll(J.y_btts, pe))
    # 3. la franja 70-80 % de las «meter» de goles
    print('\n3. FRANJA 70-80 % (lo que se «mete»), JUICIO: lo que dice cada uno → lo que pasó')
    out['franja'] = {}
    for nom, y, pm, signo in (('Más de 1.5', 'y_15', 'p_over_1.5', 1),
                              ('Menos de 3.5', 'y_35', 'p_over_3.5', -1)):
        base = nom.replace('Menos', 'Más')
        pe = pd.Series(P[base], index=J.index)
        pmod = J[pm]
        if signo < 0:
            pe, pmod = 1 - pe, 1 - pmod
            yy = 1 - J[y]
        else:
            yy = J[y]
        for quien, q in (('motor', pe), ('modelo', pmod), ('mezcla', (pe + pmod) / 2)):
            m = q.between(0.70, 0.80)
            print('   %-13s %-7s n %5d · dice %.1f %% · pasó %.1f %%'
                  % (nom, quien, m.sum(), 100 * q[m].mean(), 100 * yy[m].mean()))
            out['franja']['%s|%s' % (nom, quien)] = [int(m.sum()), float(q[m].mean()),
                                                     float(yy[m].mean())]
        # donde los dos están de acuerdo
        m = pe.between(0.70, 0.80) & pmod.between(0.70, 0.80)
        print('   %-13s ambos   n %5d · pasó %.1f %%' % (nom, m.sum(), 100 * yy[m].mean()))
    json.dump(out, open('_v333_motor.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
