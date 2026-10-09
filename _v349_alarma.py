# -*- coding: utf-8 -*-
"""v349 — ¿el movimiento de Playdoit sirve de ALARMA para nuestras «se mete»?

Para cada partido de la réplica de la tarjeta (`_v348_candidatas.csv.gz`:
lo que la tarjeta metía, liquidado), el movimiento de Playdoit en sus fotos
de días antes (`odds_snapshots.csv`, 1X2 / más de 2,5 / ambos marcan):

  · alarma de partido: algún lado del 1X2 se movió ≥ 5 pts
  · alarma de la apuesta: el lado que apostamos se abarató (≥ 3 pts) en el
    mismo mercado (sólo 1X2, más/menos 2,5 y ambos marcan)

¿Las «se mete» con alarma aciertan menos? Por mitades y con bootstrap."""
import json
import numpy as np
import pandas as pd
import _v344_precio as P

rng = np.random.default_rng(3491)
mov = pd.read_pickle('_v349_movimiento.pkl')
pl = mov[mov.casa == 'Playdoit']
# el movimiento máximo del 1X2 por partido (clave: liga, fecha, equipos)
s = pd.read_csv('odds_snapshots.csv', low_memory=False, usecols=['match_id', 'league_key', 'match_date', 'home_team', 'away_team'])
s = s.drop_duplicates('match_id')
s['k'] = [(l, str(f)[:10], P._norm(h), P._norm(a)) for l, f, h, a in zip(s.league_key, s.match_date, s.home_team, s.away_team)]
clave = dict(zip(s.match_id, s.k))
m1 = pl[pl.lado.isin(['1', 'X', '2'])].groupby('mid').mov.apply(lambda x: x.abs().max())
alarma = {clave[m]: v for m, v in m1.items() if m in clave}
lado_mov = {(clave[r.mid], r.lado): r.mov for r in pl.itertuples() if r.mid in clave}
c = pd.read_csv('_v348_candidatas.csv.gz', low_memory=False)
c = c[c.metida & c.acierto.notna()].copy()
def k_de(r):
    h, a = str(r.partido).split(' vs ', 1)
    return (r.liga, str(r.inicio)[:10], P._norm(h), P._norm(a))
c['k'] = [k_de(r) for r in c.itertuples()]
c['mov_1x2'] = c.k.map(alarma)
def lado_de(r):
    ap = str(r.apuesta)
    h, a = str(r.partido).split(' vs ', 1)
    if ap == 'Gana ' + h: return '1'
    if ap == 'Gana ' + a: return '2'
    if ap == 'Empate': return 'X'
    if ap.endswith('Más de 2.5') and r.mercado == 'Goles': return 'mas25'
    if ap.endswith('Menos de 2.5') and r.mercado == 'Goles': return 'menos25'
    if 'Ambos marcan: Sí' in ap: return 'btts_si'
    if 'Ambos marcan: No' in ap: return 'btts_no'
    return None
c['lado'] = [lado_de(r) for r in c.itertuples()]
c['mov_lado'] = [lado_mov.get((k, l)) if l else None for k, l in zip(c.k, c.lado)]
con = c[c.mov_1x2.notna()]
print('se mete con fotos de Playdoit:', len(con), 'de', len(c))
corte = sorted(con.dia.unique())[len(con.dia.unique()) // 2]
def res(g):
    return {'n': int(len(g)), 'acierto': round(float(g.acierto.mean()), 4) if len(g) else None}
out = {'n': int(len(con)), 'corte': corte}
for nom, f in (('movimiento_fuerte_1x2 (≥5 pts)', con.mov_1x2 >= 0.05),
               ('movimiento_medio (3-5)', con.mov_1x2.between(0.03, 0.05, inclusive='left')),
               ('tranquilo (<3)', con.mov_1x2 < 0.03)):
    g = con[f]
    out[nom] = {'todo': res(g), 'elige': res(g[g.dia < corte]), 'juzga': res(g[g.dia >= corte])}
l = c[c.mov_lado.notna()]
out['apuesta_abaratada (su lado bajó ≥3)'] = res(l[l.mov_lado <= -0.03])
out['apuesta_respaldada (su lado subió ≥3)'] = res(l[l.mov_lado >= 0.03])
out['apuesta_igual'] = res(l[l.mov_lado.abs() < 0.03])
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(out, open('_v349_alarma.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
