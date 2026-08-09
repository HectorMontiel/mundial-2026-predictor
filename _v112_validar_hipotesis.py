"""
LA PRUEBA DECISIVA: señal de forma + line shopping, sobre 20.325 partidos.

La v111 dejó la hipótesis planteada y sin validar por falta de precios de
varias casas a la vez. Resulta que ese histórico YA EXISTE y el proyecto lo
descarga a diario sin usarlo: football-data publica, por partido, 18 casas más
`MaxC` (el mejor precio de cierre del mercado) y `AvgC` (la media).

Se mide con el protocolo del proyecto: elegir umbral en la primera mitad
cronológica, juzgar en la segunda, y bootstrap para el p5. Si el p5 no es
positivo, no se despliega.

Se reportan DOS precios:
  · MaxC  — el mejor de las 18 casas que sigue football-data. Es un TECHO:
            incluye casas a las que no tenemos acceso.
  · el mejor de las que SÍ podemos tomar (Pinnacle, Bet365, 1xBet, Betfair
            Exchange), que es lo realista.
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
        if 'MaxCH' not in d.columns or 'Date' not in d.columns:
            continue
        d['liga'] = lg
        partes.append(d)

D = pd.concat(partes, ignore_index=True)
D['fecha'] = pd.to_datetime(D['Date'], dayfirst=True, errors='coerce')
D = D.dropna(subset=['fecha', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG',
                     'MaxCH', 'AvgCH'])
D = D.sort_values('fecha').reset_index(drop=True)
print(f'{len(D)} partidos · {D["liga"].nunique()} ligas · '
      f'{D["fecha"].min().date()} .. {D["fecha"].max().date()}')

# --- la señal, construida SIN mirar el futuro -------------------------------
racha, gf_rec, gc_rec = {}, {}, {}
reg = []
for r in D.itertuples(index=False):
    h, a = r.HomeTeam, r.AwayTeam
    f = {}
    for lado, eq in (('h', h), ('a', a)):
        rr = racha.get(eq, [])
        f[f'pts5_{lado}'] = sum(rr[-5:]) / 5 if len(rr) >= 5 else np.nan
        f[f'gf5_{lado}'] = np.mean(gf_rec.get(eq, [])[-5:]) if len(gf_rec.get(eq, [])) >= 5 else np.nan
        f[f'gc5_{lado}'] = np.mean(gc_rec.get(eq, [])[-5:]) if len(gc_rec.get(eq, [])) >= 5 else np.nan
    reg.append(f)
    gl, gv = int(r.FTHG), int(r.FTAG)
    for eq, pf, pc, p in ((h, gl, gv, 3 if gl > gv else (1 if gl == gv else 0)),
                          (a, gv, gl, 3 if gv > gl else (1 if gl == gv else 0))):
        racha.setdefault(eq, []).append(p)
        gf_rec.setdefault(eq, []).append(pf)
        gc_rec.setdefault(eq, []).append(pc)

S = pd.concat([D.reset_index(drop=True), pd.DataFrame(reg)], axis=1)
S = S.dropna(subset=['pts5_h', 'pts5_a', 'gf5_h', 'gc5_h', 'gf5_a', 'gc5_a'])
S['senal'] = ((S['pts5_h'] - S['pts5_a']) / 3.0
              + (S['gf5_h'] - S['gf5_a']) / 2.0
              + (S['gc5_a'] - S['gc5_h']) / 2.0)
S['gana_local'] = (S['FTHG'] > S['FTAG']).astype(int)

# precio realista: el mejor de las casas que SÍ podemos tomar
# (algunas columnas vienen con tipos mezclados en los CSV antiguos)
tomables = [c for c in ('PSCH', 'B365CH', '1XBCH', 'BFECH') if c in S.columns]
for c in tomables + ['MaxCH', 'AvgCH']:
    S[c] = pd.to_numeric(S[c], errors='coerce')
S['tomable_h'] = S[tomables].max(axis=1)
S = S.dropna(subset=['MaxCH', 'AvgCH'])
print(f'casas tomables en el histórico: {tomables}')
print(f'con señal calculable: {len(S)}')
print(f'\ndispersión MaxC sobre AvgC (local): '
      f'{(S["MaxCH"]/S["AvgCH"]-1).mean()*100:+.2f} %')
print(f'dispersión tomable sobre AvgC:      '
      f'{(S["tomable_h"]/S["AvgCH"]-1).mean()*100:+.2f} %')


def p5(pnl, n=3000, semilla=20260809):
    if len(pnl) < 50:
        return float('nan')
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    return float(np.percentile(np.asarray(pnl)[idx].mean(axis=1), 5))


corte = S['fecha'].quantile(0.5)
elige, juzga = S[S['fecha'] <= corte], S[S['fecha'] > corte]
print(f'\nelegir: {len(elige)} (hasta {corte.date()}) · juzgar: {len(juzga)}')


def sim(sub, umbral, col):
    sel = sub[sub['senal'] >= umbral]
    sel = sel[sel[col].notna() & (sel[col] > 1)]
    if len(sel) < 50:
        return None
    pnl = np.where(sel['gana_local'] == 1, sel[col] - 1.0, -1.0)
    return {'n': len(sel), 'roi': float(pnl.mean()), 'p5': p5(pnl),
            'acierto': float(sel['gana_local'].mean())}


for etiqueta, col in (('AvgC (media del mercado)', 'AvgCH'),
                      ('tomable (Pinnacle/B365/1xBet/Betfair)', 'tomable_h'),
                      ('MaxC (techo: las 18 casas)', 'MaxCH')):
    print(f'\n{"="*66}\n=== precio: {etiqueta}\n{"="*66}')
    print(f'  {"umbral":>7s} {"n":>6s} {"acierto":>8s} {"ROI":>9s} {"p5":>9s}')
    # Se elige por p5 y exigiendo muestra: escoger por ROI bruto se queda
    # siempre con el umbral más extremo (n=51), que luego no tiene partidos
    # que juzgar. Es el mismo error que ordenar picks por EV.
    mejor, mejor_p5 = None, -9
    for u in (0.5, 1.0, 1.5, 2.0, 2.5):
        r = sim(elige, u, col)
        if not r:
            continue
        print(f'  {u:7.1f} {r["n"]:6d} {r["acierto"]:7.1%} '
              f'{r["roi"]:+8.2%} {r["p5"]:+8.2%}')
        if r['n'] >= 300 and r['p5'] > mejor_p5:
            mejor, mejor_p5 = u, r['p5']
    if mejor is None:
        print('  (ningún umbral con muestra suficiente)')
        continue
    r = sim(juzga, mejor, col)
    if r:
        ver = 'ADOPTAR' if r['p5'] > 0 else 'RECHAZAR'
        print(f'\n  JUICIO (umbral {mejor}, elegido por p5 con n>=300):')
        print(f'    n={r["n"]}  acierto {r["acierto"]:.1%}  '
              f'ROI {r["roi"]:+.2%}  p5 {r["p5"]:+.2%}  -> {ver}')
