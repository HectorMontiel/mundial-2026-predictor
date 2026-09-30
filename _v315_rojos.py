# -*- coding: utf-8 -*-
"""
v315 — LOS ROJOS DE LO QUE SE DIJO «METER», UNO POR UNO, Y SU PATRÓN.

El usuario: «de los rojos que hemos tenido, analízalos para saber qué fue y
poder corregir y mejorar el modelo».

Los datos son los partidos terminados TAL COMO LOS VIO LA APLICACIÓN: cada
día, la última versión de `jugados_dia.json` en git (cada partido con la
apuesta archivada al empezar y su marcador). Se liquida con
`pronosticos_guardados.validar`, lo mismo que pinta la tarjeta. Sólo cuenta
lo que se dijo «meter».

Uso: python _v315_rojos.py   (escribe _v315_rojos.json y _v315_rojos.csv)
"""
from __future__ import annotations

import json
import subprocess

import pandas as pd

DESDE = '2026-09-20'


def dias():
    ult = {}
    for l in subprocess.check_output(
            ['git', 'log', '--reverse', '--format=%h', '--since=' + DESDE,
             '--', 'jugados_dia.json'], text=True).splitlines():
        try:
            d = json.loads(subprocess.check_output(['git', 'show', l + ':jugados_dia.json']))
        except Exception:
            continue
        ult[d.get('dia')] = d
    try:
        d = json.load(open('jugados_dia.json', encoding='utf-8'))
        ult[d.get('dia')] = d
    except Exception:
        pass
    return ult


def main():
    import pronosticos_guardados as pg
    filas = []
    for dia, doc in sorted(dias().items()):
        for p in doc.get('partidos') or []:
            if not isinstance(p, dict) or p.get('goles_home') is None:
                continue
            try:
                vs = pg.validar(p)
            except Exception:
                continue
            for v in vs:
                if v.get('veredicto') not in (None, 'meter') and v.get('origen') != 'archivo':
                    continue
                est = v.get('estado')
                # «cerca» en una apuesta de «meter» (prob ≥ 70 %) es un rojo
                # que falló por una unidad
                if est not in ('cumplido', 'fallado', 'cerca'):
                    continue
                filas.append({'dia': dia, 'partido': p.get('partido'),
                              'liga': p.get('liga'), 'sin_modelo': bool(p.get('solo_mercado')),
                              'mercado': v.get('mercado'), 'apuesta': v.get('apuesta'),
                              'prob': v.get('prob'), 'cuota': v.get('cuota'),
                              'marcador': '%d-%d' % (p['goles_home'], p['goles_away']),
                              'real': v.get('real'), 'cerca': est == 'cerca',
                              'y': int(est == 'cumplido')})
    d = pd.DataFrame(filas).drop_duplicates(['dia', 'partido', 'apuesta'])
    d.to_csv('_v315_rojos.csv', index=False)
    out = {'apuestas': int(len(d)), 'verdes': int(d.y.sum()),
           'acierto': round(float(d.y.mean()), 4)}
    for col in ('dia', 'mercado', 'sin_modelo'):
        out['por_' + col] = {str(k): {'n': int(len(v)), 'acierto': round(float(v.y.mean()), 3)}
                             for k, v in d.groupby(col)}
    d['banda'] = pd.cut(d.prob.astype(float), [0, .7, .75, .8, .85, .9, 1])
    out['por_banda'] = {str(k): {'n': int(len(v)), 'acierto': round(float(v.y.mean()), 3)}
                        for k, v in d.groupby('banda', observed=True)}
    lg = d.groupby('liga').y.agg(['size', 'mean'])
    out['ligas_con_mas_rojos'] = {k: {'n': int(r['size']), 'acierto': round(float(r['mean']), 3)}
                                  for k, r in lg[lg['size'] >= 5].sort_values('mean').head(12).iterrows()}
    out['rojos'] = d[d.y == 0][['dia', 'partido', 'liga', 'apuesta', 'prob', 'cuota',
                                'marcador', 'sin_modelo']].to_dict('records')
    json.dump(out, open('_v315_rojos.json', 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != 'rojos'}, ensure_ascii=False,
                     indent=1, default=str))


if __name__ == '__main__':
    main()
