# -*- coding: utf-8 -*-
"""
v331 — ¿FALLA MÁS LA «METER» CUANDO EL MODELO VA POR ENCIMA DE LA CASA?

Visto en las 867 «meter» reales de la app (26-sep a 6-oct): con el modelo por
encima de la probabilidad de la cuota acertaron 64,9 % (89); con la casa de
acuerdo o más segura, 75,5 % (772). Aquí se prueba en grande con cuotas
REALES y sin margen:

  · goles: más/menos de 2,5 (cuota_over25/under25 del histórico de goles)
  · resultado: ganador local/visita y doble oportunidad (1X2 de la casa;
    la doble se saca sumando las dos sin margen, que es lo que cotiza)

Siempre con la franja de la app SIN TOCAR (modelo 70-80 %). Las reglas sólo
QUITAN apuestas: «saltar si el modelo supera a la casa sin margen en > x».
Mismo examen: 70 % de los días para mirar, 30 % para juzgar, bootstrap por
día del acierto (con regla − sin regla) en el tramo de juzgar, p5 > 0 y
mejora también en el de mirar. Además, las dos mitades del periodo.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
LO, HI = 0.70, 0.80
rng = np.random.default_rng(3231)


def goles():
    d = pd.read_csv('pick_ledger_totales.csv')
    d = d[d.cuota_over25.notna() & d.cuota_under25.notna()]
    io_, iu = 1 / d.cuota_over25, 1 / d.cuota_under25
    c_over = io_ / (io_ + iu)
    a = pd.DataFrame({'fecha': d.fecha, 'apuesta': 'Más de 2.5',
                      'prob': d['p_over_2.5'], 'casa': c_over,
                      'cuota': d.cuota_over25, 'verde': d['over_2.5_real']})
    b = pd.DataFrame({'fecha': d.fecha, 'apuesta': 'Menos de 2.5',
                      'prob': 1 - d['p_over_2.5'], 'casa': 1 - c_over,
                      'cuota': d.cuota_under25,
                      'verde': 1 - d['over_2.5_real']})
    c = pd.concat([a, b])
    return c[(c.prob >= LO) & (c.prob <= HI) & c.verde.notna()]


def resultado():
    d = pd.read_csv('pick_ledger.csv')
    d = d[d.cuota_home.notna() & d.cuota_draw.notna() & d.cuota_away.notna()
          & d.goles_local.notna()]
    ih, ix, ia = 1 / d.cuota_home, 1 / d.cuota_draw, 1 / d.cuota_away
    s = ih + ix + ia
    ch, cx, ca = ih / s, ix / s, ia / s
    gh, ga = d.goles_local, d.goles_visit
    loc, emp, vis = (gh > ga).astype(int), (gh == ga).astype(int), (gh < ga).astype(int)
    filas = [('Gana local', d.p_home, ch, d.cuota_home, loc),
             ('Gana visita', d.p_away, ca, d.cuota_away, vis),
             ('Local o empate', d.p_home + d.p_draw, ch + cx, None, loc | emp),
             ('Visita o empate', d.p_away + d.p_draw, ca + cx, None, vis | emp)]
    c = pd.concat([pd.DataFrame({'fecha': d.fecha, 'apuesta': n, 'prob': p,
                                 'casa': k, 'cuota': (q if q is not None
                                                      else np.nan),
                                 'verde': v, 'mid': d.match_id})
                   for n, p, k, q, v in filas])
    c = c[(c.prob >= LO) & (c.prob <= HI)]
    # una por partido, la más probable (como la tarjeta)
    c = c.sort_values('prob', ascending=False).drop_duplicates('mid')
    return c


def examen(c, nombre, umbrales=(0.0, 0.03, 0.05)):
    c = c.copy()
    c['fecha'] = pd.to_datetime(c.fecha)
    c['dif'] = c.prob - c.casa
    dias = np.sort(c.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    mitad = dias[len(dias) // 2]
    print('\n=== %s — %d apuestas, base %.1f %%' % (nombre, len(c),
                                                  100 * c.verde.mean()))
    for lo, hi in ((-1, -0.05), (-0.05, 0), (0, 0.03), (0.03, 0.06),
                   (0.06, 1)):
        s = c[(c.dif > lo) & (c.dif <= hi)]
        if len(s):
            print('   modelo − casa en (%+.2f, %+.2f]: %.1f %% (n %d) · '
                  'exceso sobre el modelo %+.1f' % (lo, hi,
                                                    100 * s.verde.mean(),
                                                    len(s),
                                                    100 * (s.verde - s.prob).mean()))
    out = {}
    for u in umbrales:
        quita = c.dif > u
        r = {}
        for t, s in (('mirar', c.fecha < corte), ('juzgar', c.fecha >= corte),
                     ('mitad1', c.fecha < mitad), ('mitad2', c.fecha >= mitad)):
            a = c[s]
            q = c[s & ~quita]
            r[t] = (100 * a.verde.mean(), 100 * q.verde.mean(), len(a), len(q))
        j = c[c.fecha >= corte].assign(q=~quita[c.fecha >= corte])
        tot = j.groupby('fecha').verde.agg(['sum', 'size'])
        kep = j[j.q].groupby('fecha').verde.agg(['sum', 'size']).reindex(
            tot.index, fill_value=0)
        difs = []
        for _ in range(2000):
            b = rng.integers(0, len(tot), len(tot))
            A, K = tot.iloc[b].sum(), kep.iloc[b].sum()
            difs.append(K['sum'] / K['size'] - A['sum'] / A['size'])
        p5 = 100 * np.percentile(difs, 5)
        pasa = (r['mirar'][1] > r['mirar'][0] and p5 > 0
                and r['mitad1'][1] > r['mitad1'][0]
                and r['mitad2'][1] > r['mitad2'][0])
        print('   saltar si modelo − casa > %.2f: mirar %.1f→%.1f · juzgar '
              '%.1f→%.1f (%d→%d) · mitades %.1f→%.1f / %.1f→%.1f · p5 %+.2f'
              ' → %s' % (u, r['mirar'][0], r['mirar'][1], r['juzgar'][0],
                         r['juzgar'][1], r['juzgar'][2], r['juzgar'][3],
                         r['mitad1'][0], r['mitad1'][1], r['mitad2'][0],
                         r['mitad2'][1], p5, 'PASA' if pasa else 'no pasa'))
        out['%.2f' % u] = {'r': r, 'p5': p5, 'pasa': bool(pasa)}
    return out


if __name__ == '__main__':
    res = {'goles': examen(goles(), 'GOLES 2,5 con cuota real'),
           'resultado': examen(resultado(), 'RESULTADO con 1X2 real')}
    json.dump(res, open('_v331_desacuerdo_casa.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
