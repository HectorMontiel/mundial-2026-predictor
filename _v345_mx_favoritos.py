# -*- coding: utf-8 -*-
"""v345 — ¿apostar a los grandes de la Liga MX cuando son favoritos?

Medido en la v344 contra Pinnacle (2021-2026): ganan 64,7 % cuando Pinnacle
les da 60,3 %; por mitades +2,9 / +5,3 % de rendimiento, p5 negativo. Aquí:
  1. el histórico entero con bootstrap, y por temporada;
  2. a la cuota REAL de Playdoit (fotos de `mercado_dia.json` desde el
     24-ago) y cuánto paga Playdoit frente a Pinnacle en esos partidos;
  3. el umbral de favorito (60 %, 65 %, 70 %) elegido con la primera mitad.
"""
import json
import numpy as np
import pandas as pd
import _v344_patrones as V
import _v344_precio as P

rng = np.random.default_rng(3450)


def boot(g):
    v = g.values
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return round(float(np.percentile(bs, 5)), 4)


d = V.historico('liga_mx')
filas = []
for lado, otro in (('home', 'away'), ('away', 'home')):
    pin = d[['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']]
    inv = 1 / pin
    p = (1 / d['odd_%s_pin' % lado]) / inv.sum(axis=1)
    filas.append(pd.DataFrame({
        'fecha': d.fecha, 'eq': d['%s_team' % lado], 'rival': d['%s_team' % otro],
        'local': lado == 'home', 'p': p, 'cuota_pin': d['odd_%s_pin' % lado],
        'cuota_casa': d['odd_%s' % lado],
        'gana': (d['%s_goals' % lado] > d['%s_goals' % otro]).astype(int)}))
f = pd.concat(filas).dropna(subset=['p']).sort_values('fecha')
f['grande'] = [any(g in P._norm(t) for g in V.GRANDES_MX) for t in f['eq']]
f = f[f.grande & (f.p >= 0.5)].copy()
f['roi_pin'] = f.gana * f.cuota_pin - 1
f['roi_casa'] = f.gana * f.cuota_casa - 1
out = {'historico': {'n': len(f), 'promete': round(f.p.mean(), 3),
                     'gana': round(f.gana.mean(), 3),
                     'roi_pinnacle': round(f.roi_pin.mean(), 4), 'p5': boot(f.roi_pin),
                     'roi_cuota_media_mercado': round(f.roi_casa.dropna().mean(), 4),
                     'p5_cuota_media': boot(f.roi_casa.dropna())}}
f['año'] = f.fecha.dt.year
out['por_año'] = {int(a): {'n': len(g), 'roi_pin': round(g.roi_pin.mean(), 4)}
                  for a, g in f.groupby('año')}
corte = f.fecha.quantile(0.5)
el, ju = f[f.fecha < corte], f[f.fecha >= corte]
umb = {u: (round(el[el.p >= u].roi_pin.mean(), 4), int((el.p >= u).sum()))
       for u in (0.5, 0.55, 0.6, 0.65, 0.7)}
mejor = max(umb, key=lambda u: umb[u][0] if umb[u][1] >= 60 else -9)
g = ju[ju.p >= mejor]
out['umbral'] = {'elige': umb, 'elegido': mejor,
                 'juzga': {'n': len(g), 'roi_pin': round(g.roi_pin.mean(), 4), 'p5': boot(g.roi_pin)}}
# a la cuota de Playdoit: las fotos desde el 24-ago
tab = V.tableros_todo()
tab = tab[tab.liga == 'liga_mx']
rec = d[d.fecha >= P.DESDE].copy()
rec['mid'] = np.arange(len(rec))
prox = pd.DataFrame({'mid': rec.mid, 'liga': 'liga_mx', 'fecha': rec.fecha,
                     'equipo': rec.home_team, 'rival': rec.away_team})
casa = P.emparejar(prox, tab)
pd_ = []
for r in rec.itertuples():
    b = casa.get(r.mid)
    if b is None:
        continue
    x = V._d(b.get('1x2_cuotas'))
    for lado, eq, gf, gc, cp in (('home', r.home_team, r.home_goals, r.away_goals, r.odd_home_pin),
                                 ('away', r.away_team, r.away_goals, r.home_goals, r.odd_away_pin)):
        if not x.get(lado) or not any(gm in P._norm(eq) for gm in V.GRANDES_MX):
            continue
        s = sum(1 / x[k] for k in ('home', 'draw', 'away') if x.get(k))
        p = (1 / x[lado]) / s
        if p < 0.5:
            continue
        pd_.append({'eq': eq, 'p_casa': p, 'cuota': x[lado], 'cuota_pin': cp,
                    'gana': int(gf > gc)})
pdf = pd.DataFrame(pd_)
if len(pdf):
    pdf['roi'] = pdf.gana * pdf.cuota - 1
    out['playdoit_desde_24ago'] = {'n': len(pdf), 'casa_promete': round(pdf.p_casa.mean(), 3),
                                   'gana': round(pdf.gana.mean(), 3),
                                   'cuota': round(pdf.cuota.mean(), 3),
                                   'roi': round(pdf.roi.mean(), 4),
                                   'paga_vs_pinnacle': round((pdf.cuota / pdf.cuota_pin).dropna().mean(), 4)}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
json.dump(out, open('_v345_mx_favoritos.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
