# -*- coding: utf-8 -*-
"""v346 — ¿aciertan más las apuestas que llevan rato sin cambiar?

Para cada partido de fútbol jugado, las «meter» de la ÚLTIMA foto antes del
pitido, cada una con cuántas fotos seguidas (hasta esa) llevaba siendo
«meter» —su antigüedad— y cuántas horas antes del partido apareció. Si las
estables aciertan más, la tarjeta puede marcarlas para quien apuesta con
tiempo. Se mira por mitades de fecha y con bootstrap por partido."""
import json
import numpy as np
import pandas as pd
import _v343_estabilidad as E
import _v346_fijada as F

E.pg.de_partido = lambda *a, **k: None
ft = F.fotos()
rng = np.random.default_rng(3462)
filas = []
for p in E.jugados():
    if p.get('goles_home') is None or str(p.get('deporte') or 'Fútbol') != 'Fútbol':
        continue
    par, ini = str(p.get('partido')), p.get('inicio')
    if par not in ft or not ini:
        continue
    t0 = E._ts(ini)
    f = sorted(x for x in ft[par] if E._ts(x[0]) < t0)
    if not f or not F._metidas(f[-1][1]):
        continue
    for r in F._metidas(f[-1][1]):
        ant, desde = 0, None
        for ts, recos in reversed(f):
            if r['apuesta'] in [x['apuesta'] for x in F._metidas(recos)]:
                ant += 1
                desde = ts
            else:
                break
        liq = E.liquidar(p, [r])
        if not liq:
            continue
        filas.append({'partido': par, 'dia': str(t0.date()), 'apuesta': r['apuesta'],
                      'fotos': ant, 'horas': (t0 - E._ts(desde)).total_seconds() / 3600,
                      'verde': liq[0][1], 'p': float(r.get('prob_meter') or r['prob'])})
d = pd.DataFrame(filas)
d['estable'] = np.where(d.fotos >= 4, '4+ fotos (≥6 h)', np.where(d.fotos >= 2, '2-3 fotos', '1 foto (recién)'))
print(d.groupby('estable').agg(n=('verde', 'size'), acierto=('verde', 'mean'), promete=('p', 'mean'),
                               horas=('horas', 'median')).round(3))
corte = sorted(d.dia)[len(d) // 2]
for tr, g in (('elige', d[d.dia < corte]), ('juzga', d[d.dia >= corte])):
    print(tr, g.groupby('estable').agg(n=('verde', 'size'), acierto=('verde', 'mean')).round(3).to_dict())
a, b = d[d.fotos >= 4], d[d.fotos < 4]
def boot():
    pa, pb = a.partido.unique(), b.partido.unique()
    ga, gb = a.groupby('partido').verde.agg(['sum', 'size']), b.groupby('partido').verde.agg(['sum', 'size'])
    out = []
    for _ in range(4000):
        ia, ib = rng.choice(pa, len(pa)), rng.choice(pb, len(pb))
        out.append(ga.loc[ia, 'sum'].sum() / ga.loc[ia, 'size'].sum() - gb.loc[ib, 'sum'].sum() / gb.loc[ib, 'size'].sum())
    return round(float(np.mean(out)), 4), round(float(np.percentile(out, 5)), 4)
print('estables − resto:', boot())
d.to_pickle('_v346_estable.pkl')
