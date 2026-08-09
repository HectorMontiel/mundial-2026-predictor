"""
La pregunta limpia: ¿comprar SIEMPRE al mejor precio basta para vencer la
comisión?

Sin modelo, sin señal. Sólo: ¿cuánto margen le queda a la casa cuando tomas el
mejor precio del mercado en cada lado? Si la suma de probabilidades implícitas
baja de 1, hay arbitraje puro. Si se queda cerca, el line shopping deja el
listón lo bastante bajo como para que una señal modesta lo cruce.

Es la medición que decide si la vía tiene techo o no, y hoy se puede hacer con
19.425 partidos en vez de los 219 que había.
"""
import io

import numpy as np
import pandas as pd
import requests

UA = {'User-Agent': 'Mozilla/5.0'}
LIGAS = ['E0', 'E1', 'SP1', 'I1', 'D1', 'F1', 'N1', 'P1', 'T1', 'B1', 'SC0', 'G1']
TEMPS = ['2122', '2223', '2324', '2425', '2526']

partes = []
for t in TEMPS:
    for lg in LIGAS:
        try:
            r = requests.get(
                f'https://www.football-data.co.uk/mmz4281/{t}/{lg}.csv',
                headers=UA, timeout=40)
            if r.status_code != 200 or len(r.text) < 500:
                continue
            d = pd.read_csv(io.StringIO(r.text))
        except Exception:
            continue
        if 'MaxCH' not in d.columns:
            continue
        d['liga'] = lg
        partes.append(d)

D = pd.concat(partes, ignore_index=True).copy()
COLS = ['MaxCH', 'MaxCD', 'MaxCA', 'AvgCH', 'AvgCD', 'AvgCA',
        'PSCH', 'PSCD', 'PSCA', 'B365CH', 'B365CD', 'B365CA',
        'FTHG', 'FTAG']
for c in COLS:
    if c in D.columns:
        D[c] = pd.to_numeric(D[c], errors='coerce')
D = D.dropna(subset=['MaxCH', 'MaxCD', 'MaxCA', 'AvgCH', 'AvgCD', 'AvgCA',
                     'FTHG', 'FTAG'])
print(f'{len(D)} partidos con precio de cierre completo\n')


def margen(dh, dd, da):
    return 1 / dh + 1 / dd + 1 / da


D['m_avg'] = margen(D['AvgCH'], D['AvgCD'], D['AvgCA'])
D['m_max'] = margen(D['MaxCH'], D['MaxCD'], D['MaxCA'])
if 'PSCH' in D.columns:
    D['m_pin'] = margen(D['PSCH'], D['PSCD'], D['PSCA'])

print('=== MARGEN DE LA CASA (suma de probabilidades implícitas) ===')
print('    1,00 = juego justo · 1,05 = la casa se queda el 5 %\n')
for etq, col in (('media del mercado (AvgC)', 'm_avg'),
                 ('Pinnacle (la más eficiente)', 'm_pin'),
                 ('MEJOR PRECIO de las 18 casas (MaxC)', 'm_max')):
    if col not in D.columns:
        continue
    s = D[col].dropna()
    print(f'  {etq:38s} media {s.mean():.4f} · mediana {s.median():.4f} · '
          f'p10 {s.quantile(.10):.4f}')

sub = D['m_max'].dropna()
arb = (sub < 1.0).mean()
print(f'\n  partidos donde el mejor precio da ARBITRAJE puro (margen<1): '
      f'{arb:.2%} ({int((sub < 1).sum())} de {len(sub)})')

print('\n=== ¿cuánto sube el ROI comprar al mejor precio? ===')
# apostar al favorito del mercado, con cada precio
fav = D[['AvgCH', 'AvgCD', 'AvgCA']].to_numpy(float).argmin(axis=1)
res = np.where(D['FTHG'] > D['FTAG'], 0,
               np.where(D['FTHG'] == D['FTAG'], 1, 2))
gano = (fav == res)
for etq, cols in (('media del mercado', ['AvgCH', 'AvgCD', 'AvgCA']),
                  ('Pinnacle', ['PSCH', 'PSCD', 'PSCA']),
                  ('mejor precio', ['MaxCH', 'MaxCD', 'MaxCA'])):
    if not all(c in D.columns for c in cols):
        continue
    precios = D[cols].to_numpy(float)[np.arange(len(D)), fav]
    ok = ~np.isnan(precios)
    pnl = np.where(gano[ok], precios[ok] - 1, -1.0)
    print(f'  apostar al favorito a {etq:20s} ROI {pnl.mean():+.2%} '
          f'(n={ok.sum()})')

print('\n=== conclusión ===')
d_avg = D['m_avg'].mean()
d_max = D['m_max'].mean()
print(f'  El mejor precio baja el margen de {d_avg:.4f} a {d_max:.4f}, '
      f'o sea {(d_avg - d_max)*100:.2f} puntos.')
if d_max > 1.0:
    print(f'  Sigue por ENCIMA de 1: aun comprando al mejor precio del mercado,')
    print(f'  la casa se queda el {(d_max - 1)*100:.2f} % de media. Una señal')
    print(f'  necesita superar ESO para ganar dinero, no sólo batir al mercado.')
