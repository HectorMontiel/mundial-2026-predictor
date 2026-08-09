"""
¿Existe YA histórico de precios de VARIAS casas a la vez?

Si lo hay, la hipótesis (señal de forma + line shopping) se puede validar hoy
en vez de esperar semanas a que las fotos diarias acumulen muestra.
"""
import io

import pandas as pd
import requests

UA = {'User-Agent': 'Mozilla/5.0'}

print('=== football-data.co.uk: ¿trae columnas POR CASA? ===')
u = 'https://www.football-data.co.uk/mmz4281/2425/E0.csv'
r = requests.get(u, headers=UA, timeout=60)
d = pd.read_csv(io.StringIO(r.text))
print(f'  {u}')
print(f'  {len(d)} partidos, {len(d.columns)} columnas\n')

casas = {}
for c in d.columns:
    if c.endswith('H') and c[:-1] + 'D' in d.columns and c[:-1] + 'A' in d.columns:
        pref = c[:-1]
        n = int(d[[pref + 'H', pref + 'D', pref + 'A']].notna().all(axis=1).sum())
        if n:
            casas[pref] = n

print(f'  casas/agregados con 1X2 completo: {len(casas)}')
for k, v in sorted(casas.items(), key=lambda x: -x[1]):
    print(f'    {k:8s} {v:5d} partidos')

print('\n=== ¿MaxC (mejor precio) contra AvgC (media)? ===')
for pref in ('MaxC', 'AvgC', 'Max', 'Avg'):
    cols = [pref + x for x in 'HDA']
    if all(c in d.columns for c in cols):
        sub = d[cols].dropna()
        print(f'  {pref}: {len(sub)} partidos')

if all(c in d.columns for c in ('MaxCH', 'AvgCH')):
    sub = d[['MaxCH', 'AvgCH', 'MaxCA', 'AvgCA', 'FTHG', 'FTAG']].dropna()
    disp_h = (sub['MaxCH'] / sub['AvgCH'] - 1)
    disp_a = (sub['MaxCA'] / sub['AvgCA'] - 1)
    print(f'\n  DISPERSIÓN (mejor precio sobre la media), n={len(sub)}:')
    print(f'    local:     media {disp_h.mean()*100:+.2f} % · '
          f'mediana {disp_h.median()*100:+.2f} % · p90 {disp_h.quantile(.9)*100:+.2f} %')
    print(f'    visitante: media {disp_a.mean()*100:+.2f} % · '
          f'mediana {disp_a.median()*100:+.2f} % · p90 {disp_a.quantile(.9)*100:+.2f} %')
    print('\n  -> Esto ES line shopping histórico: MaxC es lo que pagaba la')
    print('     mejor casa y AvgC la media del mercado, partido a partido.')

print('\n=== ¿cuántas temporadas y ligas hay así? ===')
LIGAS = ['E0', 'E1', 'SP1', 'I1', 'D1', 'F1', 'N1', 'P1', 'T1', 'B1', 'SC0', 'G1']
TEMPS = ['2122', '2223', '2324', '2425', '2526']
total = 0
for t in TEMPS:
    fila = []
    for lg in LIGAS:
        try:
            rr = requests.get(
                f'https://www.football-data.co.uk/mmz4281/{t}/{lg}.csv',
                headers=UA, timeout=30)
            if rr.status_code != 200 or len(rr.text) < 500:
                continue
            dd = pd.read_csv(io.StringIO(rr.text))
            if 'MaxCH' in dd.columns and 'AvgCH' in dd.columns:
                n = int(dd[['MaxCH', 'AvgCH']].notna().all(axis=1).sum())
                fila.append(f'{lg}:{n}')
                total += n
        except Exception:
            continue
    print(f'  {t}: ' + ' '.join(fila))
print(f'\n  TOTAL con Max y Avg de cierre: {total} partidos')
