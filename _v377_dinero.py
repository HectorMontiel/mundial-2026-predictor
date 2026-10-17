#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v377 — ¿Las «se mete» ganan DINERO? (para decidir qué se puede vender).
pitido en git), por mercado, lado, cuota, ⭐, liga y hora: ¿qué tienen en
común? Dos mitades por fecha. Escribe `_v375_rojas.json`."""
import json, subprocess, sys, collections
sys.path.insert(0, '.')
import modo_modelo as mm, pronosticos_guardados as pg
sys.stdout.reconfigure(encoding='utf-8')
cs = subprocess.run(['git', 'log', '--format=%h', '--since=2026-10-03', '--', 'jugados_ayer.json', 'jugados_dia.json'],
                    capture_output=True, text=True).stdout.split()
dias = {}
for c in cs:
    for f in ('jugados_ayer.json', 'jugados_dia.json'):
        r = subprocess.run(['git', 'show', '%s:%s' % (c, f)], capture_output=True)
        if r.returncode: continue
        try: d = json.loads(r.stdout.decode('utf-8'))
        except Exception: continue
        if d.get('dia') and d['dia'] not in dias and d.get('partidos'): dias[d['dia']] = d['partidos']
F = []
for dia, ps in dias.items():
    for p in ps:
        if p.get('solo_mercado') or p.get('sin_modelo') or p.get('aplazado'): continue
        dep = str(p.get('deporte') or 'Fútbol')
        for fl in pg.validar(p) or []:
            if fl.get('veredicto') != 'meter' or fl.get('estado') not in (pg.CUMPLIDO, pg.FALLADO): continue
            ap = str(fl.get('apuesta'))
            F.append({'dia': dia, 'dep': dep, 'liga': p.get('clave_liga'), 'ok': fl['estado'] == pg.CUMPLIDO,
                      'elige': mm.elige(dict(fl, veredicto_vp='meter'), dep), 'cuota': float(fl.get('cuota') or 0),
                      'bloque': fl.get('bloque'), 'lado': 'menos' if 'Menos' in ap else ('más' if 'Más' in ap else 'otro'),
                      'linea': fl.get('linea'), 'ap': ap, 'partido': p.get('partido'),
                      'hora': str(p.get('inicio') or '')[11:13]})
dd = sorted({f['dia'] for f in F}); mitad = dd[len(dd)//2]
import numpy as np
rng = np.random.default_rng(377)
dd = sorted({f['dia'] for f in F}); mitad = dd[len(dd)//2]
def roi(s):
    if not s: return None
    g = np.array([f['cuota'] - 1 if f['ok'] else -1 for f in s])
    b = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(2000)]
    return {'n': len(s), 'acierto': round(float(np.mean([f['ok'] for f in s])), 3),
            'cuota_media': round(float(np.mean([f['cuota'] for f in s])), 3),
            'gana_por_100': round(100 * float(g.mean()), 1), 'p5': round(100 * float(np.percentile(b, 5)), 1)}
R = {}
grupos = {'todas': lambda f: True, 'cuota<=1.25': lambda f: f['cuota'] <= 1.25,
          '⭐ ELIGE': lambda f: bool(f['elige']), '⭐ y <=1.25': lambda f: bool(f['elige']) and f['cuota'] <= 1.25,
          'Fútbol': lambda f: f['dep'] == 'Fútbol', 'Tenis': lambda f: f['dep'] == 'Tenis',
          'otros deportes': lambda f: f['dep'] not in ('Fútbol', 'Tenis')}
for k, fn in grupos.items():
    for m, sel in (('A', lambda f: f['dia'] < mitad), ('B', lambda f: f['dia'] >= mitad)):
        R['%s %s' % (k, m)] = roi([f for f in F if fn(f) and sel(f) and f['cuota'] > 1])
json.dump(R, open('_v377_dinero.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for k, v in R.items(): print(k, v)
