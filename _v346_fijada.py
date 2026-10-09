#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v346 — EL PUNTO MEDIO: la apuesta fijada con margen.

El usuario: «quiero que las que yo meta en ese momento sean las mejores y no
cambien después; entiendo que cerca del partido es mejor, pero ¿no hay un
punto medio?». La v343 midió que la última versión antes del pitido acierta
algo más que la primera (79,0 % contra 76,2 %), pero que la tarjeta cambiaba
de apuesta en 57 % de los partidos, casi siempre porque una cuota se movía
una centésima y cruzaba un corte fijo.

Estrategias, simuladas con todas las fotos de las decisiones guardadas:

    PRIMERA   lo primero que se anunció, sin tocar
    ÚLTIMA    lo de la última foto antes del pitido (lo que hace hoy la app)
    FIJADA δ  se anuncia lo primero y SE QUEDA mientras su probabilidad no
              caiga más de δ puntos respecto a la de cuando se anunció (si
              ya no aparece entre las candidatas, se queda: no hay evidencia
              de que empeorara). Si cae más de δ, se cambia por la mejor
              «meter» de ese momento que no estuviera ya.

δ se elige con la primera mitad de fechas y se juzga con la segunda.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

import _v343_estabilidad as E

CACHE = '_v346_fotos.json'
rng = np.random.default_rng(3461)


def fotos():
    """{partido: [(ts, [recomendadas con veredicto y prob_meter])]}"""
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding='utf-8'))
    hs = subprocess.run(['git', 'log', '--reverse', '--format=%H %cI',
                         '--since=2026-10-03T12:00', 'origin/main', '--',
                         'pronostico_dia.json'], capture_output=True,
                        text=True).stdout.split('\n')
    out = {}
    for linea in [x for x in hs if x.strip()]:
        h, cuando = linea.split()
        try:
            d = E._git_json(h, 'pronostico_dia.json')
        except Exception:
            continue
        for x in ((d.get('decisiones') or {}).get('listas') or {}).get('pronosticos') or []:
            recos = x.get('recomendadas_tarjeta') or x.get('recomendadas') or []
            par = str((x.get('llave') or [''])[0])
            out.setdefault(par, []).append(
                [cuando, [{k: r.get(k) for k in ('apuesta', 'mercado', 'bloque',
                                                  'etiqueta', 'linea', 'cuota',
                                                  'prob', 'prob_meter',
                                                  'veredicto_vp')} for r in recos]])
    json.dump(out, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    return out


def _metidas(recos):
    return [r for r in recos if r.get('veredicto_vp') == 'meter'][:2]


def simular(fts, delta):
    """La apuesta (hasta 2) que queda al pitido con la estrategia FIJADA δ, y
    cuántas veces cambió."""
    actual, cambios = {}, 0
    for _, recos in fts:
        por_ap = {r['apuesta']: r for r in recos}
        if not actual:
            for r in _metidas(recos):
                actual[r['apuesta']] = (r, float(r.get('prob_meter') or r['prob']))
            continue
        for ap, (r0, p0) in list(actual.items()):
            cur = por_ap.get(ap)
            if cur is None:
                continue                       # sin evidencia de que empeorara
            p1 = float(cur.get('prob_meter') or cur['prob'])
            if p0 - p1 > delta or cur.get('veredicto_vp') != 'meter' and p0 - p1 > delta / 2:
                actual.pop(ap)
                cambios += 1
        if len(actual) < 2:
            for r in _metidas(recos):
                if r['apuesta'] not in actual and len(actual) < 2:
                    actual[r['apuesta']] = (r, float(r.get('prob_meter') or r['prob']))
    return [r for r, _ in actual.values()], cambios


def main():
    E.pg.de_partido = lambda *a, **k: None
    ft = fotos()
    filas = []
    for p in E.jugados():
        if p.get('goles_home') is None or p.get('aplazado'):
            continue
        if str(p.get('deporte') or 'Fútbol') != 'Fútbol':
            continue
        par, ini = str(p.get('partido')), p.get('inicio')
        if par not in ft or not ini:
            continue
        try:
            t0 = E._ts(ini)
        except Exception:
            continue
        f = sorted(x for x in ft[par] if E._ts(x[0]) < t0)
        f = [x for x in f if _metidas(x[1])]
        if not f:
            continue
        fila = {'partido': par, 'dia': str(t0.date())}
        ids = lambda rs: tuple(sorted(r['apuesta'] for r in rs))
        estr = {'primera': (_metidas(f[0][1]), 0),
                'ultima': (_metidas(f[-1][1]),
                           sum(1 for a, b in zip(f, f[1:]) if ids(_metidas(a[1])) != ids(_metidas(b[1]))))}
        for dlt in (0.02, 0.03, 0.05, 0.08, 0.12):
            estr['fijada_%.2f' % dlt] = simular(f, dlt)
        for nom, (rs, cam) in estr.items():
            liq = E.liquidar(p, rs)
            fila[nom + '_n'] = len(liq)
            fila[nom + '_v'] = sum(x[1] for x in liq)
            fila[nom + '_cambios'] = cam
        filas.append(fila)
    d = pd.DataFrame(filas)
    d.to_pickle('_v346_fijada.pkl')
    corte = d.dia.quantile(0.5, interpolation='nearest') if False else sorted(d.dia)[len(d) // 2]
    noms = [c[:-2] for c in d.columns if c.endswith('_n')]
    res = {'partidos': len(d), 'corte': corte}
    for tramo, g in (('elige', d[d.dia < corte]), ('juzga', d[d.dia >= corte]), ('todo', d)):
        r = {}
        for nom in noms:
            n, v = g[nom + '_n'].sum(), g[nom + '_v'].sum()
            r[nom] = {'apuestas': int(n), 'verdes': int(v),
                      'acierto': round(float(v / n), 4) if n else None,
                      'partidos_que_cambian': int((g[nom + '_cambios'] > 0).sum())}
        res[tramo] = r
    # δ elegido con la primera mitad: el de mayor acierto; y su mejora frente a
    # la PRIMERA en el juicio, con bootstrap por partido
    el = res['elige']
    fij = [k for k in el if k.startswith('fijada')]
    mejor = max(fij, key=lambda k: el[k]['acierto'])
    g = d[d.dia >= corte]
    out = []
    for ref in ('primera', 'ultima'):
        A, NA, B, NB = (g[ref + '_v'].values, g[ref + '_n'].values,
                        g[mejor + '_v'].values, g[mejor + '_n'].values)
        bs = [B[i].sum() / NB[i].sum() - A[i].sum() / NA[i].sum()
              for i in (rng.integers(0, len(g), len(g)) for _ in range(4000))]
        out.append((ref, round(float(np.mean(bs)), 4), round(float(np.percentile(bs, 5)), 4)))
    res['elegida'] = mejor
    res['juzga_vs'] = out
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    json.dump(res, open('_v346_fijada.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
