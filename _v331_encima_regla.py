# -*- coding: utf-8 -*-
"""
v331 — «EL MODELO NO PUEDE IR POR ENCIMA DE LA CASA», ENCIMA DE LA REGLA DE HOY.

La regla de «meter» en fútbol ya exige 70-80 % y cuota < 1,35 (v312). La
pregunta es si, DENTRO de lo que hoy se mete, saltar las apuestas en que la
probabilidad corregida supera a la de la cuota (1/cuota, con el margen de la
casa, que es lo único que la tarjeta tiene a mano) quita rojos.

Tres pruebas, con la regla de hoy ya aplicada:
  A. histórico de resultado (29 mil con 1X2 real): ganador con su cuota y
     doble oportunidad con su cuota aproximada (1/(1/c1+1/cX)).
  B. las «meter» REALES de la app (_v331_meter_app.csv), días 26-sep a
     2-oct para mirar, 3 a 6-oct para juzgar.
  C. la simulación de la tarjeta (_v319_candidatas.csv, veredicto «meter»).
Las tres con bootstrap por día de (con regla − sin regla).
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3232)
NO_METER = ('Doble y goles', 'Remates', 'Remates a puerta', 'Handicap')


def boot(s, quita, n=3000):
    tot = s.groupby('fecha').verde.agg(['sum', 'size'])
    kep = s[~quita].groupby('fecha').verde.agg(['sum', 'size']).reindex(
        tot.index, fill_value=0)
    difs = []
    for _ in range(n):
        b = rng.integers(0, len(tot), len(tot))
        A, K = tot.iloc[b].sum(), kep.iloc[b].sum()
        if K['size']:
            difs.append(K['sum'] / K['size'] - A['sum'] / A['size'])
    return 100 * np.percentile(difs, 5), 100 * np.mean(difs)


def informe(nombre, c, corte, margenes=(0.0, 0.02)):
    c = c.copy()
    c['dif'] = c.prob - 1 / c.cuota
    print('\n=== %s — %d apuestas, %.1f %% de verdes' % (
        nombre, len(c), 100 * c.verde.mean()))
    for lo, hi in ((-1, -0.05), (-0.05, 0), (0, 0.03), (0.03, 1)):
        s = c[(c.dif > lo) & (c.dif <= hi)]
        if len(s):
            print('   prob − 1/cuota en (%+.2f, %+.2f]: %.1f %% (n %d)'
                  % (lo, hi, 100 * s.verde.mean(), len(s)))
    out = {}
    for m in margenes:
        quita = c.dif > m
        r = {}
        for t, s in (('mirar', c.fecha < corte), ('juzgar', c.fecha >= corte)):
            a, q = c[s], c[s & ~quita]
            r[t] = (round(100 * a.verde.mean(), 1), round(100 * q.verde.mean(), 1),
                    int(len(a)), int(len(q)), int((1 - a.verde).sum()),
                    int((1 - q.verde).sum()))
        sj = c[c.fecha >= corte]
        p5, med = boot(sj, quita[c.fecha >= corte])
        pasa = r['mirar'][1] > r['mirar'][0] and p5 > 0
        print('   saltar si prob − 1/cuota > %.2f:' % m)
        for t in ('mirar', 'juzgar'):
            a = r[t]
            print('      %-6s %.1f %% → %.1f %%  apuestas %d → %d  rojos %d → %d'
                  % (t, a[0], a[1], a[2], a[3], a[4], a[5]))
        print('      bootstrap (juzgar): media %+.2f pts · p5 %+.2f → %s'
              % (med, p5, 'PASA' if pasa else 'no pasa'))
        out['%.2f' % m] = {'r': r, 'p5': p5, 'media': med, 'pasa': bool(pasa)}
    return out


def historico():
    d = pd.read_csv('pick_ledger.csv')
    d = d[d.cuota_home.notna() & d.cuota_draw.notna() & d.cuota_away.notna()
          & d.goles_local.notna()]
    gh, ga = d.goles_local, d.goles_visit
    loc, emp, vis = (gh > ga).astype(int), (gh == ga).astype(int), (gh < ga).astype(int)
    c1x = 1 / (1 / d.cuota_home + 1 / d.cuota_draw)
    cx2 = 1 / (1 / d.cuota_away + 1 / d.cuota_draw)
    filas = [('Gana local', d.p_home, d.cuota_home, loc),
             ('Gana visita', d.p_away, d.cuota_away, vis),
             ('Local o empate', d.p_home + d.p_draw, c1x, loc | emp),
             ('Visita o empate', d.p_away + d.p_draw, cx2, vis | emp)]
    c = pd.concat([pd.DataFrame({'fecha': pd.to_datetime(d.fecha), 'mid': d.match_id,
                                 'apuesta': n, 'prob': p, 'cuota': q, 'verde': v})
                   for n, p, q, v in filas])
    c = c[(c.prob >= 0.70) & (c.prob <= 0.80) & (c.cuota < 1.35)]
    c = c.sort_values('prob', ascending=False).drop_duplicates('mid')
    dias = np.sort(c.fecha.unique())
    return c, dias[int(len(dias) * 0.7)]


def reales():
    c = pd.read_csv('_v331_meter_app.csv')
    c = c[(c.deporte == 'Fútbol') & ~c.mercado.isin(NO_METER)
          & c.prob.between(0.70, 0.80) & (c.cuota < 1.35) & c.cuota.notna()]
    c['fecha'] = pd.to_datetime(c.dia)
    return c, pd.Timestamp('2026-10-03')


def simulacion():
    c = pd.read_csv('_v319_candidatas.csv')
    c = c[c.veredicto == 'meter'].rename(columns={'prob_meter': 'pm'})
    c['prob'] = c.pm
    c['verde'] = c.acierto
    c['fecha'] = pd.to_datetime(c.dia)
    c = c[c.cuota.notna()]
    dias = np.sort(c.fecha.unique())
    return c, dias[int(len(dias) * 0.7)]


if __name__ == '__main__':
    res = {}
    for nombre, f in (('A. HISTÓRICO resultado (regla de hoy aplicada)', historico),
                      ('B. REALES de la app (regla de hoy aplicada)', reales),
                      ('C. SIMULACIÓN de la tarjeta (v319, «meter»)', simulacion)):
        c, corte = f()
        res[nombre] = informe(nombre, c, corte)
    json.dump(res, open('_v331_encima_regla.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
