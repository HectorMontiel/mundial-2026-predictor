#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v343 — ¿Es bueno que la tarjeta cambie de apuesta durante el día?

El usuario armó un parley la madrugada del 8-oct con lo que daba la app y a
mediodía, en los mismos partidos, la app enseñaba otras apuestas. Visto en
`_v343_historia.py`: el modelo NO había cambiado; una cuota de Playdoit se
movió una centésima y cruzó un corte fijo (cuota ≥ 1,15 de la v335; casa
≤ 88 % de la Capa 1).

Aquí se mide si esos cambios aportan algo. Para cada partido ya jugado con
decisiones guardadas (`pronostico_dia.json` desde el 4-oct, una foto cada
~1,5 h), se toman:

    PRIMERA  las «meter» de la primera foto en que el partido tuvo alguna
    ÚLTIMA   las «meter» de la última foto anterior al inicio
    FIJADA   la primera, y se le suma lo nuevo sólo si la primera ya no
             tenía nada (o sea: lo primero que se dijo no se cambia)

y se liquidan con el marcador (`pronosticos_guardados.validar`). Si la
última no acierta más que la primera, los cambios son ruido y lo correcto
es no cambiar lo ya anunciado.
"""
import datetime as dt
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, '.')
import partidos_jugados as pj            # noqa: E402
import pronosticos_guardados as pg       # noqa: E402

DESDE = '2026-10-03T12:00'
CACHE = '_v343_fotos_decisiones.json'
rng = np.random.default_rng(343)


def _git_json(h, ruta):
    raw = subprocess.run(['git', 'show', '%s:%s' % (h, ruta)],
                         capture_output=True).stdout
    return json.loads(raw.decode('utf-8'))


def decisiones():
    """{llave: [(ts_foto, [filas meter])...]} con todas las fotos."""
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding='utf-8'))
    hs = subprocess.run(['git', 'log', '--reverse', '--format=%H %cI',
                         '--since=' + DESDE, 'origin/main', '--',
                         'pronostico_dia.json'],
                        capture_output=True, text=True).stdout.split('\n')
    out = {}
    for linea in [x for x in hs if x.strip()]:
        h, cuando = linea.split()
        try:
            d = _git_json(h, 'pronostico_dia.json')
        except Exception:
            continue
        for x in ((d.get('decisiones') or {}).get('listas') or {}).get(
                'pronosticos') or []:
            k = '|'.join(str(v) for v in (x.get('llave') or []))
            met = [r for r in (x.get('recomendadas_tarjeta') or x.get('recomendadas') or [])
                   if r.get('veredicto_vp') == 'meter'][:2]
            out.setdefault(k, []).append([cuando, met])
    json.dump(out, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    return out


def jugados():
    """Partidos acabados con marcador: las fotos de `jugados_dia.json` y
    `jugados_ayer.json` en origin/main, con los marcadores de otros deportes
    rellenados (la v342 arregló el tenis)."""
    por = {}
    for ruta in ('jugados_dia.json', 'jugados_ayer.json'):
        hs = subprocess.run(['git', 'log', '--format=%H', '--since=' + DESDE,
                             'origin/main', '--', ruta],
                            capture_output=True, text=True).stdout.split()
        for h in hs:                      # del más nuevo al más viejo
            try:
                d = _git_json(h, ruta)
            except Exception:
                continue
            for p in d.get('partidos') or []:
                k = (str(p.get('partido')), str(d.get('dia')))
                if k not in por or (por[k].get('goles_home') is None
                                    and p.get('goles_home') is not None):
                    por[k] = p
    return list(por.values())


def _ts(s):
    t = pd.Timestamp(s)
    return t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')


def liquidar(p, filas):
    if not filas:
        return []
    q = dict(p)
    q['recomendadas_previas'] = [dict(f, veredicto='meter') for f in filas]
    out = []
    for fl in pg.validar(q):
        if fl.get('estado') in (pg.CUMPLIDO, pg.FALLADO):
            out.append((fl.get('apuesta'), int(fl['estado'] == pg.CUMPLIDO),
                        float(fl.get('cuota') or 0)))
    return out


def main():
    pg.de_partido = lambda *a, **k: None
    dec = decisiones()
    print('partidos con decisiones:', len(dec))
    filas = []
    for p in jugados():
        if p.get('goles_home') is None or p.get('aplazado'):
            continue
        par, ini = str(p.get('partido')), p.get('inicio')
        cand = [k for k in dec if k.split('|')[0] == par]
        if not cand or not ini:
            continue
        try:
            t0 = _ts(ini)
        except Exception:
            continue
        fotos = sorted(f for k in cand for f in dec[k])
        fotos = [f for f in fotos if _ts(f[0]) < t0 and f[1]]
        if not fotos:
            continue
        prim, ult = fotos[0], fotos[-1]
        ids = lambda fs: tuple(sorted(r['apuesta'] for r in fs))
        cambios = len({ids(f[1]) for f in fotos})
        rp, ru = liquidar(p, prim[1]), liquidar(p, ult[1])
        if not rp or not ru:
            continue
        filas.append({'partido': par, 'deporte': p.get('deporte') or 'Fútbol',
                      'dia': str(t0.date()), 'fotos': len(fotos),
                      'versiones': cambios,
                      'cambio': ids(prim[1]) != ids(ult[1]),
                      'prim_n': len(rp), 'prim_v': sum(x[1] for x in rp),
                      'prim_roi': sum(x[1] * x[2] - 1 for x in rp),
                      'ult_n': len(ru), 'ult_v': sum(x[1] for x in ru),
                      'ult_roi': sum(x[1] * x[2] - 1 for x in ru),
                      'quitadas': [x for x in rp if x[0] not in {y[0] for y in ru}],
                      'nuevas': [x for x in ru if x[0] not in {y[0] for y in rp}]})
    d = pd.DataFrame(filas)
    d.to_pickle('_v343_estabilidad.pkl')
    res = {'partidos': len(d), 'con_cambio': int(d.cambio.sum())}
    for nom in ('prim', 'ult'):
        res[nom] = {'apuestas': int(d[nom + '_n'].sum()),
                    'verdes': int(d[nom + '_v'].sum()),
                    'acierto': round(d[nom + '_v'].sum() / d[nom + '_n'].sum(), 4),
                    'roi': round(d[nom + '_roi'].sum() / d[nom + '_n'].sum(), 4)}
    q = [x for l in d.quitadas for x in l]
    n = [x for l in d.nuevas for x in l]
    res['quitadas'] = {'n': len(q), 'acierto': round(np.mean([x[1] for x in q]), 4) if q else None,
                       'cuota': round(np.mean([x[2] for x in q]), 3) if q else None}
    res['nuevas'] = {'n': len(n), 'acierto': round(np.mean([x[1] for x in n]), 4) if n else None,
                     'cuota': round(np.mean([x[2] for x in n]), 3) if n else None}
    # bootstrap por partido: acierto(última) − acierto(primera)
    P, PN, U, UN = (d.prim_v.values, d.prim_n.values, d.ult_v.values, d.ult_n.values)
    b = []
    for _ in range(5000):
        i = rng.integers(0, len(d), len(d))
        b.append(U[i].sum() / UN[i].sum() - P[i].sum() / PN[i].sum())
    res['ultima_menos_primera'] = {'media': round(float(np.mean(b)), 4),
                                   'p5': round(float(np.percentile(b, 5)), 4),
                                   'p95': round(float(np.percentile(b, 95)), 4)}
    for dep, g in d.groupby('deporte'):
        res['dep_' + dep] = {'partidos': len(g), 'cambio': int(g.cambio.sum()),
                             'prim': round(g.prim_v.sum() / g.prim_n.sum(), 4),
                             'ult': round(g.ult_v.sum() / g.ult_n.sum(), 4)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open('_v343_estabilidad.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
