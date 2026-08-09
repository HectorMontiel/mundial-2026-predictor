"""
Las tres señales con significancia, ¿dan DINERO?

Una correlación de +0,03 con el residuo del mercado es significativa con
72.000 partidos y aun así puede no pagar la comisión de la casa (5-7 %). Esto
lo mide donde importa: ROI apostando de verdad, con el protocolo del proyecto
—elegir en una mitad, juzgar en la otra— y bootstrap para el percentil 5.

Si el p5 no es positivo, no se despliega. Es la regla de oro.
"""
import glob
import os

import numpy as np
import pandas as pd

filas = []
for f in glob.glob('historico_*.csv'):
    liga = os.path.basename(f)[len('historico_'):-4]
    try:
        d = pd.read_csv(f)
    except Exception:
        continue
    if not {'date', 'home_team', 'away_team', 'home_goals', 'away_goals',
            'odd_home', 'odd_draw', 'odd_away'} <= set(d.columns):
        continue
    d['date'] = pd.to_datetime(d['date'], errors='coerce', format='mixed')
    d = d.dropna(subset=['date', 'home_goals', 'away_goals',
                         'odd_home', 'odd_draw', 'odd_away'])
    d['liga'] = liga
    filas.append(d)

D = pd.concat(filas, ignore_index=True).sort_values('date').reset_index(drop=True)
D = D[(D['odd_home'] > 1) & (D['odd_draw'] > 1) & (D['odd_away'] > 1)]
print(f'{len(D)} partidos con cuota de cierre, {D["liga"].nunique()} ligas')

racha, gf_rec, gc_rec = {}, {}, {}
reg = []
for r in D.itertuples(index=False):
    h, a = r.home_team, r.away_team
    f = {'fecha': r.date, 'liga': r.liga,
         'oh': float(r.odd_home), 'od': float(r.odd_draw), 'oa': float(r.odd_away),
         'gl': int(r.home_goals), 'gv': int(r.away_goals)}
    for lado, eq in (('h', h), ('a', a)):
        rr = racha.get(eq, [])
        f[f'pts5_{lado}'] = sum(rr[-5:]) / min(len(rr), 5) if len(rr) >= 5 else np.nan
        f[f'gf5_{lado}'] = np.mean(gf_rec.get(eq, [])[-5:]) if len(gf_rec.get(eq, [])) >= 5 else np.nan
        f[f'gc5_{lado}'] = np.mean(gc_rec.get(eq, [])[-5:]) if len(gc_rec.get(eq, [])) >= 5 else np.nan
    reg.append(f)
    gl, gv = int(r.home_goals), int(r.away_goals)
    for eq, pf, pc, p in ((h, gl, gv, 3 if gl > gv else (1 if gl == gv else 0)),
                          (a, gv, gl, 3 if gv > gl else (1 if gl == gv else 0))):
        racha.setdefault(eq, []).append(p)
        gf_rec.setdefault(eq, []).append(pf)
        gc_rec.setdefault(eq, []).append(pc)

X = pd.DataFrame(reg).dropna(subset=['pts5_h', 'pts5_a', 'gf5_h', 'gc5_h'])
X['gana_local'] = (X['gl'] > X['gv']).astype(int)
X['dif_forma'] = X['pts5_h'] - X['pts5_a']
X['dif_ataque'] = X['gf5_h'] - X['gf5_a']
X['dif_defensa'] = X['gc5_a'] - X['gc5_h']
X['senal'] = (X['dif_forma'] / 3.0 + X['dif_ataque'] / 2.0 + X['dif_defensa'] / 2.0)

inv = 1 / X[['oh', 'od', 'oa']].to_numpy(float)
X['p_mkt'] = (inv / inv.sum(axis=1, keepdims=True))[:, 0]
print(f'con las tres señales calculables: {len(X)}')

# protocolo del proyecto: ELEGIR en la primera mitad, JUZGAR en la segunda
corte = X['fecha'].quantile(0.5)
elige, juzga = X[X['fecha'] <= corte], X[X['fecha'] > corte]
print(f'elegir: {len(elige)} (hasta {corte.date()}) · juzgar: {len(juzga)}')


def p5(pnl, n=2000, semilla=20260809):
    if len(pnl) < 50:
        return float('nan')
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    return float(np.percentile(np.asarray(pnl)[idx].mean(axis=1), 5))


def simular(sub, umbral):
    """Apostar al LOCAL cuando la señal lo favorece por encima del umbral."""
    sel = sub[sub['senal'] >= umbral]
    if len(sel) < 50:
        return None
    pnl = np.where(sel['gana_local'] == 1, sel['oh'] - 1.0, -1.0)
    return {'n': len(sel), 'roi': float(pnl.mean()), 'p5': p5(pnl),
            'acierto': float(sel['gana_local'].mean()),
            'mercado': float(sel['p_mkt'].mean())}


print(f'\n=== ELECCIÓN: apostar al local cuando la señal lo favorece ===')
print(f'  {"umbral":>7s} {"n":>7s} {"acierto":>8s} {"mercado":>8s} {"ROI":>9s} {"p5":>9s}')
mejor, mejor_roi = None, -9
for u in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
    r = simular(elige, u)
    if not r:
        continue
    print(f'  {u:7.1f} {r["n"]:7d} {r["acierto"]:7.1%} {r["mercado"]:7.1%} '
          f'{r["roi"]:+8.2%} {r["p5"]:+8.2%}')
    if r['roi'] > mejor_roi:
        mejor, mejor_roi = u, r['roi']

print(f'\n=== JUICIO: el umbral elegido ({mejor}) en la mitad NO usada ===')
r = simular(juzga, mejor)
if r:
    print(f'  n={r["n"]}  acierto {r["acierto"]:.1%} (mercado decía '
          f'{r["mercado"]:.1%})  ROI {r["roi"]:+.2%}  p5 {r["p5"]:+.2%}')
    print()
    if r['p5'] > 0:
        print('  VEREDICTO: ADOPTAR — el p5 es positivo en el tramo de juicio.')
    else:
        print('  VEREDICTO: RECHAZAR — el ROI no sobrevive al bootstrap.')
        print('  La señal predice (z=8,6) pero no paga la comisión de la casa.')

# control: ¿y si apostamos AL AZAR el mismo número de veces?
print('\n=== control: apostar al local sin mirar nada ===')
pnl = np.where(juzga['gana_local'] == 1, juzga['oh'] - 1.0, -1.0)
print(f'  n={len(juzga)}  ROI {pnl.mean():+.2%}  p5 {p5(pnl):+.2%}')
