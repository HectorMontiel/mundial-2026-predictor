"""
¿Se puede saber ANTES de apostar si vamos a batir el cierre?

El CLV discrimina el ROI brutalmente (+0,79 % contra -4,19 %), pero sólo sirve
si es predecible en el momento de apostar. Esto prueba los candidatos que el
proyecto ya puede calcular sin fuentes nuevas.
"""
import glob
import json
import os

import numpy as np
import pandas as pd

filas = []
for ruta in sorted(glob.glob('roi_bets_*.json')):
    liga = os.path.basename(ruta)[len('roi_bets_'):-len('.json')]
    if liga.startswith(('ah_', 'ou_')):
        continue
    try:
        bets = json.load(open(ruta, encoding='utf-8'))
    except Exception:
        continue
    for b in bets:
        if not isinstance(b, dict):
            continue
        filas.append({**b, 'liga': liga})

d = pd.DataFrame(filas)
print('apuestas registradas:', len(d))
print('columnas:', list(d.columns))
if d.empty:
    raise SystemExit

for c in ('cuota', 'cuota_pin', 'prob', 'ev'):
    if c in d.columns:
        d[c] = pd.to_numeric(d[c], errors='coerce')

d = d.dropna(subset=['cuota', 'cuota_pin', 'gano'])
d = d[(d['cuota'] > 1) & (d['cuota_pin'] > 1)]
print('con cuota apostada y cierre de Pinnacle:', len(d))

d['clv'] = d['cuota'] / d['cuota_pin'] - 1.0
d['batimos'] = d['clv'] > 0
d['pnl'] = np.where(d['gano'].astype(bool), d['cuota'] - 1.0, -1.0)

print(f"\nCLV medio {d['clv'].mean():+.2%} · batimos el cierre "
      f"{d['batimos'].mean():.1%} de las veces")
print(f"  ROI cuando batimos: {d.loc[d['batimos'],'pnl'].mean():+.2%} "
      f"(n={int(d['batimos'].sum())})")
print(f"  ROI cuando no:      {d.loc[~d['batimos'],'pnl'].mean():+.2%} "
      f"(n={int((~d['batimos']).sum())})")


def bootstrap_p5(x, n=2000, semilla=20260808):
    rng = np.random.default_rng(semilla)
    if len(x) < 30:
        return float('nan')
    idx = rng.integers(0, len(x), size=(n, len(x)))
    return float(np.percentile(np.asarray(x)[idx].mean(axis=1), 5))


print('\n=== ¿QUÉ SEÑALES, CONOCIDAS AL APOSTAR, PREDICEN BATIR EL CIERRE? ===')

candidatos = {}
if 'ev' in d.columns:
    candidatos['EV declarado'] = d['ev']
if 'prob' in d.columns:
    candidatos['probabilidad'] = d['prob']
candidatos['cuota'] = d['cuota']

for nombre, serie in candidatos.items():
    s = pd.to_numeric(serie, errors='coerce')
    ok = s.notna()
    if ok.sum() < 200:
        continue
    corr = float(np.corrcoef(s[ok], d.loc[ok, 'clv'])[0, 1])
    print(f'\n  {nombre}: correlación con el CLV = {corr:+.4f}')
    q = pd.qcut(s[ok], 4, labels=['Q1', 'Q2', 'Q3', 'Q4'], duplicates='drop')
    for etq, sub in d.loc[ok].groupby(q, observed=True):
        print(f"    {etq}: n={len(sub):5d}  CLV {sub['clv'].mean():+.2%}  "
              f"batimos {sub['batimos'].mean():5.1%}  "
              f"ROI {sub['pnl'].mean():+.2%}  p5 {bootstrap_p5(sub['pnl'].values):+.2%}")

print('\n=== SIMULACIÓN: sólo apostar cuando batimos el cierre ===')
sub = d[d['batimos']]
print(f"  n={len(sub)}  ROI {sub['pnl'].mean():+.2%}  "
      f"p5 {bootstrap_p5(sub['pnl'].values):+.2%}")
for umbral in (0.01, 0.02, 0.03, 0.05):
    s2 = d[d['clv'] >= umbral]
    if len(s2) < 50:
        continue
    print(f"  CLV >= {umbral:.0%}: n={len(s2):5d}  ROI {s2['pnl'].mean():+.2%}  "
          f"p5 {bootstrap_p5(s2['pnl'].values):+.2%}  "
          f"acierto {s2['gano'].astype(bool).mean():.1%}")

print('\n=== por liga (¿dónde batimos el cierre?) ===')
g = d.groupby('liga').agg(n=('clv', 'size'), clv=('clv', 'mean'),
                          batimos=('batimos', 'mean'), roi=('pnl', 'mean'))
g = g[g['n'] >= 100].sort_values('clv', ascending=False)
print(f"  {'liga':22s} {'n':>6s} {'CLV':>8s} {'bate%':>7s} {'ROI':>8s}")
for k, r in g.iterrows():
    print(f"  {k:22s} {int(r['n']):6d} {r['clv']:+7.2%} {r['batimos']:6.1%} "
          f"{r['roi']:+7.2%}")
