#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v375 — Las rojas de las «se mete» de los últimos días (lo archivado al
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
def tab(clave):
    g = collections.defaultdict(lambda: [0, 0, 0, 0])
    for f in F:
        k = clave(f); i = 0 if f['dia'] < mitad else 2
        g[k][i] += f['ok']; g[k][i+1] += 1
    return {str(k): '%d/%d (%s) | %d/%d (%s)' % (v[0], v[1], '%.0f%%' % (100*v[0]/v[1]) if v[1] else '-', v[2], v[3], '%.0f%%' % (100*v[2]/v[3]) if v[3] else '-')
            for k, v in sorted(g.items(), key=lambda x: -(x[1][1]+x[1][3])) if v[1]+v[3] >= 25}
R = {'dias': dd, 'n': len(F), 'acierto': round(sum(f['ok'] for f in F)/len(F), 4)}
for nom, cl in (('deporte', lambda f: f['dep']), ('elige', lambda f: f['elige']), ('bloque_lado', lambda f: '%s %s' % (f['bloque'], f['lado'])),
                ('cuota', lambda f: '<=1.12' if f['cuota'] <= 1.12 else ('1.13-1.18' if f['cuota'] <= 1.18 else ('1.19-1.25' if f['cuota'] <= 1.25 else '>1.25'))),
                ('linea_goles', lambda f: '%s %s' % (f['lado'], f['linea']) if f['bloque'] in ('goles', 'goles_equipo') else 'otro'),
                ('dia', lambda f: f['dia'])):
    R[nom] = tab(cl)
# rojas del mismo partido: ¿caen juntas?
pp = collections.defaultdict(list)
for f in F: pp[(f['dia'], f['partido'])].append(f['ok'])
dos = [v for v in pp.values() if len(v) >= 2]
R['mismo_partido'] = {'partidos_con_2+': len(dos), 'ambas_rojas': sum(1 for v in dos if v.count(False) >= 2),
                      'una_roja': sum(1 for v in dos if v.count(False) == 1), 'p_roja_pata': round(1 - R['acierto'], 3)}
json.dump(R, open('_v375_rojas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))

# --- la regla candidata: tope de cuota 1,25 para la «se mete» ---
import numpy as np
rng = np.random.default_rng(375)
def p5_dif(sub_a, sub_b):
    """p5 de acierto(a) − acierto(b), bootstrap por partido."""
    def agg(s):
        g = collections.defaultdict(lambda: [0, 0])
        for f in s: g[(f['dia'], f['partido'])][0] += f['ok']; g[(f['dia'], f['partido'])][1] += 1
        return np.array(list(g.values()), float)
    A, B = agg(sub_a), agg(sub_b); out = []
    for _ in range(2000):
        a = A[rng.integers(0, len(A), len(A))].sum(0); b = B[rng.integers(0, len(B), len(B))].sum(0)
        out.append(a[0]/a[1] - b[0]/b[1])
    return round(float(np.percentile(out, 5)), 4)
T = {}
for tope in (1.22, 1.25, 1.28):
    for t, m in (('A', lambda f: f['dia'] < mitad), ('B', lambda f: f['dia'] >= mitad)):
        s = [f for f in F if m(f)]; k = [f for f in s if f['cuota'] <= tope]
        T['%.2f %s' % (tope, t)] = {'antes': '%d/%d %.1f%%' % (sum(f['ok'] for f in s), len(s), 100*np.mean([f['ok'] for f in s])),
                                   'despues': '%d/%d %.1f%%' % (sum(f['ok'] for f in k), len(k), 100*np.mean([f['ok'] for f in k])),
                                   'rojas_quitadas': sum(1 for f in s if f['cuota'] > tope and not f['ok']),
                                   'verdes_quitadas': sum(1 for f in s if f['cuota'] > tope and f['ok']),
                                   'p5_dif_vs_quitadas': p5_dif(k, [f for f in s if f['cuota'] > tope])}
for dep in ('Fútbol', 'Tenis'):
    for t, m in (('A', lambda f: f['dia'] < mitad), ('B', lambda f: f['dia'] >= mitad)):
        s = [f for f in F if m(f) and f['dep'] == dep]
        hi = [f for f in s if f['cuota'] > 1.25]; lo = [f for f in s if f['cuota'] <= 1.25]
        T['%s %s' % (dep, t)] = '≤1,25 %.1f%% (%d) · >1,25 %.1f%% (%d)' % (100*np.mean([f['ok'] for f in lo]), len(lo), 100*np.mean([f['ok'] for f in hi]) if hi else 0, len(hi))
json.dump(T, open('_v375_tope.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(T, ensure_ascii=False, indent=1))
