"""
¿QUÉ casas producen el mejor precio? Sin eso, «añade más casas» es un deseo.

Si el edge lo genera una sola casa a la que no llegamos, la conclusión no es
«integrar más» sino «conseguir acceso a ÉSA» — que es una acción concreta que
el usuario puede tomar.
"""
import io

import numpy as np
import pandas as pd
import requests

UA = {'User-Agent': 'Mozilla/5.0'}
LIGAS = ['E0', 'E1', 'SP1', 'I1', 'D1', 'F1', 'N1', 'P1', 'T1', 'B1', 'SC0', 'G1']
TEMPS = ['2223', '2324', '2425', '2526']

partes = []
for t in TEMPS:
    for lg in LIGAS:
        try:
            r = requests.get(
                f'https://www.football-data.co.uk/mmz4281/{t}/{lg}.csv',
                headers=UA, timeout=40)
            if r.status_code != 200 or len(r.text) < 500:
                continue
            partes.append(pd.read_csv(io.StringIO(r.text)))
        except Exception:
            continue
D = pd.concat(partes, ignore_index=True).copy()

# casas con cierre 1X2 completo
CASAS = {}
for c in D.columns:
    if c.endswith('CH') and c[:-1] + 'D' in D.columns and c[:-1] + 'A' in D.columns:
        CASAS[c[:-2]] = [c, c[:-1] + 'D', c[:-1] + 'A']
CASAS.pop('Max', None)
CASAS.pop('Avg', None)
for cols in list(CASAS.values()) + [['MaxCH', 'MaxCD', 'MaxCA'],
                                    ['AvgCH', 'AvgCD', 'AvgCA']]:
    for c in cols:
        if c in D.columns:
            D[c] = pd.to_numeric(D[c], errors='coerce')

print(f'{len(D)} partidos · casas con cierre 1X2: {sorted(CASAS)}\n')

# ¿quién da el mejor precio en cada lado?
gana = {k: 0 for k in CASAS}
total = 0
for lado, i in (('home', 0), ('draw', 1), ('away', 2)):
    sub = D[[cols[i] for cols in CASAS.values()]].copy()
    sub.columns = list(CASAS)
    ok = sub.notna().sum(axis=1) >= 4
    sub = sub[ok]
    total += len(sub)
    for casa in sub.idxmax(axis=1).dropna():
        gana[casa] = gana.get(casa, 0) + 1

print('=== ¿quién paga el mejor precio? (los tres lados juntos) ===')
for k, v in sorted(gana.items(), key=lambda x: -x[1]):
    acceso = {'PS': 'SÍ (Pinnacle, ya integrada)',
              'B365': 'no (Bet365 bloquea)',
              'BFE': 'no (Betfair 403)',
              '1XB': 'no (1xBet 404 en la v71)',
              'WH': 'no (William Hill)',
              'BW': 'no (Bwin)',
              'BF': 'no (Betfair Sportsbook)'}.get(k, '?')
    print(f'  {k:6s} {v:6d}  {v/max(total,1):6.1%}   acceso: {acceso}')

# el experimento decisivo: MaxC SIN la casa dominante
print('\n=== ¿qué pasa con el margen si quitamos casas? ===')


def margen_de(casas_incluidas):
    cols_h = [CASAS[c][0] for c in casas_incluidas if c in CASAS]
    cols_d = [CASAS[c][1] for c in casas_incluidas if c in CASAS]
    cols_a = [CASAS[c][2] for c in casas_incluidas if c in CASAS]
    if not cols_h:
        return None
    h = D[cols_h].max(axis=1)
    d = D[cols_d].max(axis=1)
    a = D[cols_a].max(axis=1)
    m = (1 / h + 1 / d + 1 / a).replace([np.inf, -np.inf], np.nan).dropna()
    return m


TODAS = sorted(CASAS)
esc = [('todas las casas', TODAS),
       ('sin Betfair Exchange (BFE)', [c for c in TODAS if c != 'BFE']),
       ('sin BFE ni 1xBet', [c for c in TODAS if c not in ('BFE', '1XB')]),
       ('sólo Pinnacle', ['PS']),
       ('sólo las que podríamos tomar (PS+B365)', ['PS', 'B365'])]
for etq, cs in esc:
    m = margen_de(cs)
    if m is None or m.empty:
        continue
    arb = (m < 1.0).mean()
    print(f'  {etq:42s} margen medio {m.mean():.4f} · '
          f'arbitraje {arb:6.2%}  (n={len(m)})')
