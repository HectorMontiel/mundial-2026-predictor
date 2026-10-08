# -*- coding: utf-8 -*-
"""v342 — la regla del tenis contra las apuestas reales de la app.

Toma la última foto de `jugados_dia.json` de cada día (la de `_v331_rojos_app`),
y para cada «Gana X» de tenis que se dijo «meter» y ya se liquidó saca el
precio de la casa sin margen de los dos lados que guarda el partido.
"""
import json
import pandas as pd
import _v342_fotos as f342
import partidos_jugados as pj
import pronosticos_guardados as pg

filas = []
for dia, foto in sorted(f342.fotos().items()):
    for p in pj._para_la_vista(foto.get('partidos') or []):
        if p.get('deporte') != 'Tenis' or p.get('aplazado'):
            continue
        c = ((p.get('implicitas') or {}).get('1x2_cuotas') or {})
        h, a = p.get('partido', ' vs ').split(' vs ')[0], p.get('partido', ' vs ').split(' vs ')[-1]
        try:
            vs = pg.validar(p)
        except Exception:
            continue
        for fl in vs:
            if fl.get('estado') not in (pg.CUMPLIDO, pg.FALLADO):
                continue
            ap = str(fl.get('apuesta') or '')
            ch, ca = c.get('home'), c.get('away')
            pm = None
            if ch and ca and ch > 1 and ca > 1:
                ih, ia = 1 / ch, 1 / ca
                pm = ih / (ih + ia) if ap == 'Gana ' + h else ia / (ih + ia) if ap == 'Gana ' + a else None
            filas.append({'dia': dia, 'partido': p.get('partido'), 'apuesta': ap,
                          'veredicto': fl.get('veredicto'),
                          'p_modelo': fl.get('prob'), 'p_meter': fl.get('prob_meter'),
                          'cuota': fl.get('cuota'), 'pm': pm,
                          'verde': int(fl['estado'] == pg.CUMPLIDO)})
d = pd.DataFrame(filas)
d.to_csv('_v342_tenis_app.csv', index=False)
m = d[d.veredicto == 'meter'].copy()
m['roi'] = m.verde * m.cuota - 1
nueva = m[(m.pm >= 0.70) & (m.p_modelo >= 0.70)]
fuera = m[~m.index.isin(nueva.index)]
res = {}
for k, s in (('hoy', m), ('regla nueva', nueva), ('las que quita', fuera)):
    res[k] = {'n': len(s), 'verdes': int(s.verde.sum()), 'rojas': int((1 - s.verde).sum()),
              'acierto': round(s.verde.mean(), 4), 'cuota': round(s.cuota.mean(), 3),
              'roi': round(s.roi.mean(), 4)}
    print(k, res[k])
print('sin precio de la casa:', int(m.pm.isna().sum()))
print(fuera[['dia', 'apuesta', 'p_modelo', 'pm', 'cuota', 'verde']].to_string())
json.dump(res, open('_v342_tenis_app.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
