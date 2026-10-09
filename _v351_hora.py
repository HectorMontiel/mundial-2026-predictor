#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v351 — ¿Cuál es la hora adecuada para apostar cada partido?

El usuario: «quiero que se muestre la hora adecuada para apostar; no quiero
que sea siempre una hora antes, porque con un parlay de varios equipos no se
puede hacer todo a la vez; dos horas antes o así; algo breve y visual».

Con todas las fotos del precálculo (git de `pronostico_dia.json`, una cada
~2 h desde el 3-oct) y el resultado de cada partido (`jugados_*.json`), cada
vez que una apuesta sale «se mete» se apunta:

  · cuántas horas faltan para el partido y cuántas lleva ya anunciada,
  · si sigue siendo la apuesta de la app al pitido (si «se queda»),
  · si se ganó, y su cuota frente a la última foto antes del pitido.

Tres preguntas:
  1. ¿Apostar antes cuesta acierto o cuota? (si no, la hora sólo decide si
     la app la va a cambiar después)
  2. ¿Desde cuántas horas antes la apuesta ya casi no cambia?
  3. ¿Una apuesta que ya lleva X horas sin cambiar se queda aunque falte
     mucho? (para poder decir «ya puedes» antes de la ventana)
Elige con la primera mitad de los días, juzga con la segunda; bootstrap por
partido.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import _v343_estabilidad as E
import _v346_fijada as F

rng = np.random.default_rng(351)


def construir():
    E.pg.de_partido = lambda *a, **k: None
    ft = F.fotos()
    filas = []
    for p in E.jugados():
        if p.get('goles_home') is None:
            continue
        par, ini = str(p.get('partido')), p.get('inicio')
        if par not in ft or not ini:
            continue
        try:
            t0 = E._ts(ini)
        except Exception:
            continue
        f = sorted(x for x in ft[par] if E._ts(x[0]) < t0)
        if len(f) < 2 or not F._metidas(f[-1][1]):
            continue
        final = {r['apuesta']: float(r.get('cuota') or 0) for r in F._metidas(f[-1][1])}
        primera: dict = {}
        resultado: dict = {}
        for ts, recos in f[:-1]:
            for r in F._metidas(recos):
                ap = r['apuesta']
                primera.setdefault(ap, E._ts(ts))
                if ap not in resultado:
                    liq = E.liquidar(p, [r])
                    resultado[ap] = liq[0][1] if liq else None
                if resultado[ap] is None:
                    continue
                filas.append({
                    'partido': par, 'deporte': str(p.get('deporte') or 'Fútbol'),
                    'dia': str(t0.date()), 'apuesta': ap,
                    'cuota': float(r.get('cuota') or 0),
                    'cuota_final': final.get(ap),
                    'horas': (t0 - E._ts(ts)).total_seconds() / 3600,
                    'lleva': (E._ts(ts) - primera[ap]).total_seconds() / 3600,
                    'se_queda': int(ap in final), 'verde': resultado[ap]})
    return pd.DataFrame(filas)


def boot(v, mids, n=2000):
    um, inv = np.unique(mids, return_inverse=True)
    s, k = np.bincount(inv, weights=v), np.bincount(inv)
    bs = [s[i].sum() / k[i].sum() for i in (rng.integers(0, len(um), len(um)) for _ in range(n))]
    return round(float(np.mean(bs)), 4), round(float(np.percentile(bs, 5)), 4)


BANDAS = [0, 2, 3, 4, 6, 9, 12, 18, 24, 48, 200]


def tabla(d):
    d = d.assign(b=pd.cut(d.horas, BANDAS))
    return d.groupby('b', observed=True).agg(
        n=('verde', 'size'), partidos=('partido', 'nunique'),
        se_queda=('se_queda', 'mean'), acierto=('verde', 'mean'),
        cuota=('cuota', 'mean'),
        cuota_vs_pitido=('dcuota', 'mean')).round(3)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if os.path.exists('_v351_filas.pkl'):
        d = pd.read_pickle('_v351_filas.pkl')
    else:
        d = construir()
        d.to_pickle('_v351_filas.pkl')
    d['dcuota'] = d.cuota - d.cuota_final.fillna(d.cuota)
    out = {'filas': int(len(d)), 'partidos': int(d.partido.nunique()),
           'dias': [d.dia.min(), d.dia.max()],
           'por_deporte': d.groupby('deporte').partido.nunique().to_dict()}
    print(json.dumps(out, ensure_ascii=False))
    corte = sorted(d.dia.unique())[len(d.dia.unique()) // 2]
    out['corte'] = corte
    for dep, g in [('todos', d)] + list(d.groupby('deporte')):
        if g.partido.nunique() < 20:
            continue
        print('\n=====', dep)
        t = tabla(g)
        print(t.to_string())
        out['tabla_%s' % dep] = t.reset_index().astype({'b': str}).to_dict('records')
    # 1. ¿apostar pronto cuesta acierto o cuota? (lo que se apuesta a esa hora)
    pronto, tarde = d[d.horas > 6], d[d.horas <= 3]
    out['acierto_pronto_vs_tarde'] = {
        'pronto_>6h': boot(pronto.verde.values, pronto.partido.values),
        'tarde_<=3h': boot(tarde.verde.values, tarde.partido.values),
        'cuota_pronto_vs_pitido': round(float(pronto.dcuota.mean()), 4),
        'cuota_tarde_vs_pitido': round(float(tarde.dcuota.mean()), 4)}
    # 2. y 3. se queda, por horas que faltan y horas que ya lleva, en las dos mitades
    d['falta'] = pd.cut(d.horas, [0, 2, 3, 4, 6, 9, 12, 24, 200])
    d['lleva_b'] = pd.cut(d.lleva, [-0.1, 2, 6, 12, 200], labels=['<2h', '2-6h', '6-12h', '12h+'])
    for tramo, g in (('elige', d[d.dia < corte]), ('juzga', d[d.dia >= corte])):
        pv = g.pivot_table(index='falta', columns='lleva_b', values='se_queda',
                           aggfunc='mean', observed=True).round(3)
        nv = g.pivot_table(index='falta', columns='lleva_b', values='se_queda',
                           aggfunc='size', observed=True)
        print('\n--- se queda (%s): filas = horas que faltan, columnas = horas que ya lleva' % tramo)
        print(pv.to_string())
        print(nv.to_string())
        out['se_queda_%s' % tramo] = {str(k): {str(c): (None if pd.isna(v) else v)
                                               for c, v in row.items()}
                                      for k, row in pv.iterrows()}
        out['n_%s' % tramo] = {str(k): {str(c): (None if pd.isna(v) else int(v))
                                        for c, v in row.items()}
                               for k, row in nv.iterrows()}
    print(json.dumps(out['acierto_pronto_vs_tarde'], ensure_ascii=False))
    json.dump(out, open('_v351_hora.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
