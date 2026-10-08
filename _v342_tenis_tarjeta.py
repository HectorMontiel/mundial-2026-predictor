# -*- coding: utf-8 -*-
"""v342 — la tarjeta de tenis REHECHA con el código, antes y después.

Para cada partido de tenis ya jugado de las fotos de `jugados_dia.json` (la
foto archivada antes del partido, con sus precios de ese momento), se vuelve
a calcular lo que la tarjeta diría «meter» (`recomendadas` + `metidas`) y se
liquida con el marcador. «Antes» se corre con `veredicto_pick.py` y
`concordancia.py` de HEAD delante en el PYTHONPATH:

    python _v342_tenis_tarjeta.py antes   (con V342_HEAD=<carpeta con HEAD>)
    python _v342_tenis_tarjeta.py despues
"""
import json
import os
import sys

etiqueta = sys.argv[1]
if etiqueta == 'antes':
    # la carpeta del script va primero en sys.path: PYTHONPATH no basta
    sys.path.insert(0, os.environ['V342_HEAD'])
import pandas as pd
import _v342_fotos as f342
import modo_modelo as mm
import partidos_jugados as pj
import pronosticos_guardados as pg

import veredicto_pick as _vp
print(etiqueta, 'veredicto_pick de', _vp.__file__)
pg.de_partido = lambda *a, **k: None          # que no lea lo guardado
filas = []
for dia, foto in sorted(f342.fotos().items()):
    for p in pj._para_la_vista(foto.get('partidos') or []):
        if p.get('deporte') != 'Tenis' or p.get('aplazado'):
            continue
        q = dict(p)
        q.pop('recomendadas_previas', None)
        # la misma cuenta con la que se archivó (`_recomendadas_previas`
        # quita `jugado`, que hace que la tarjeta no recomiende nada)
        q['recomendadas_previas'] = pj._recomendadas_previas(q)
        for fl in pg.validar(q):
            if fl.get('estado') in (pg.CUMPLIDO, pg.FALLADO):
                filas.append({'dia': dia, 'partido': p.get('partido'),
                              'apuesta': fl.get('apuesta'), 'cuota': fl.get('cuota'),
                              'prob': fl.get('prob'),
                              'verde': int(fl['estado'] == pg.CUMPLIDO)})
d = pd.DataFrame(filas)
d.to_csv('_v342_tarjeta_%s.csv' % etiqueta, index=False)
r = {'n': len(d), 'verdes': int(d.verde.sum()), 'rojas': int(len(d) - d.verde.sum()),
     'acierto': round(float(d.verde.mean()), 4), 'cuota': round(float(d.cuota.mean()), 3),
     'roi': round(float((d.verde * d.cuota - 1).mean()), 4)}
print(etiqueta, r)
print(d.groupby('dia').verde.agg(['size', 'mean']).round(3))
json.dump(r, open('_v342_tarjeta_%s.json' % etiqueta, 'w'), indent=1)
