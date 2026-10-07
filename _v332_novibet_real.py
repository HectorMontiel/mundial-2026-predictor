# -*- coding: utf-8 -*-
"""
v332 — LA COMPROBACIÓN CON PRECIOS DE VERDAD: NOVIBET CONTRA PINNACLE.

El histórico (`_v332_combinadas.py`) dice que la única pata que gana a la
larga es el ERROR DE PRECIO —la casa paga más de lo que vale según Pinnacle
sin margen—, también a cuotas bajas (1,30-2,00: 65 % de acierto, +5 a +8 %).
Pero sus cuotas no son las de las casas del usuario. Aquí se repite con
NOVIBET, que es suya y es la casa de 7 de los 9 boletos que mandó:

  · la última cuota de Novibet ANTES del inicio, sacada de las 263 fotos de
    `cuotas_mx.json` que hay en git (desde el 10-sep), con su apertura;
  · Pinnacle de `radar_capturas.csv` (mismo partido, misma hora de inicio);
  · el resultado de `resultados_flashscore*.csv.gz` (mismo id de partido).

Se mide: acierto y rendimiento de cada pata por franja de cuota, el error
de precio (Pinnacle sin margen × cuota ≥ 1,02), el movimiento de la cuota
desde la apertura, y combinadas de 2-4 patas sorteadas por día.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from itertools import combinations

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3322)
CASA = 'Novibet'


def fotos():
    log = subprocess.run(['git', 'log', '--format=%H %ct', '--reverse', '--',
                          'cuotas_mx.json'], capture_output=True,
                         check=True).stdout.decode().split('\n')
    ultimo = {}
    for ln in log:
        if not ln.strip():
            continue
        h, ts = ln.split()
        ts = int(ts)
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':cuotas_mx.json'],
                                          capture_output=True, check=True).stdout)
        except Exception:
            continue
        for eid, p in (d.get('partidos') or {}).items():
            try:
                ini = int(p.get('inicio'))
            except Exception:
                continue
            nv = (p.get('casas') or {}).get(CASA)
            if not nv or p.get('deporte') != 'futbol' or ts >= ini:
                continue
            ultimo[eid] = {'ts': ts, 'ini': ini, 'home': p.get('home'),
                           'away': p.get('away'), 'liga': p.get('liga'), 'nv': nv}
    return ultimo


def patas(ult) -> pd.DataFrame:
    res = pd.concat([pd.read_csv('resultados_flashscore_reciente.csv.gz'),
                     pd.read_csv('resultados_flashscore.csv.gz')]).drop_duplicates('match_id')
    res = res.set_index('match_id')
    rad = pd.read_csv('radar_capturas.csv')
    rad = rad[rad.deporte == 'futbol'].drop_duplicates(['home', 'away', 'inicio'], keep='last')
    pin = {(h, a, int(i)): (ph, px, pa) for h, a, i, ph, px, pa in
           zip(rad.home, rad.away, rad.inicio, rad.pin_home, rad.pin_draw, rad.pin_away)}
    filas = []
    for eid, u in ult.items():
        if eid not in res.index:
            continue
        r = res.loc[eid]
        gh, ga = int(r.gh), int(r.ga)
        nv = u['nv']
        p3 = pin.get((u['home'], u['away'], u['ini']))
        pp = None
        if p3 and all(pd.notna(x) and x > 1 for x in p3):
            inv = [1 / x for x in p3]
            s = sum(inv)
            pp = [x / s for x in inv]
        fecha = pd.to_datetime(u['ini'], unit='s').normalize()
        base = {'fecha': fecha, 'eid': eid, 'liga': u['liga'],
                'partido': '%s vs %s' % (u['home'], u['away'])}
        hda = nv.get('HOME_DRAW_AWAY') or {}
        ap = hda.get('apertura') or {}
        for k, nom, ok, i in (('home', 'Gana local', gh > ga, 0),
                              ('draw', 'Empate', gh == ga, 1),
                              ('away', 'Gana visita', ga > gh, 2)):
            if hda.get(k):
                filas.append(dict(base, mercado='1X2', apuesta=nom, cuota=hda[k],
                                  apertura=ap.get(k), verde=int(ok),
                                  p_pin=pp[i] if pp else np.nan))
        dc = nv.get('DOUBLE_CHANCE') or {}
        ap = dc.get('apertura') or {}
        for k, nom, ok, ii in (('homeOrDraw', 'Local o empate', gh >= ga, (0, 1)),
                               ('awayOrDraw', 'Visita o empate', ga >= gh, (2, 1)),
                               ('noDraw', 'Local o visita', gh != ga, (0, 2))):
            if dc.get(k):
                filas.append(dict(base, mercado='Doble oportunidad', apuesta=nom,
                                  cuota=dc[k], apertura=ap.get(k), verde=int(ok),
                                  p_pin=(pp[ii[0]] + pp[ii[1]]) if pp else np.nan))
        ou = nv.get('OVER_UNDER') or {}
        for ln in (ou.get('lineas') or []):
            L = ln.get('linea')
            if L is None:
                continue
            for k, nom, ok in (('over', 'Más de %s' % L, gh + ga > L),
                               ('under', 'Menos de %s' % L, gh + ga < L)):
                if ln.get(k) and (gh + ga) != L:
                    filas.append(dict(base, mercado='Goles', apuesta=nom, cuota=ln[k],
                                      apertura=None, verde=int(ok), p_pin=np.nan))
        bt = nv.get('BOTH_TEAMS_TO_SCORE') or {}
        for k, nom, ok in (('yes', 'Ambos marcan sí', gh > 0 and ga > 0),
                           ('no', 'Ambos marcan no', not (gh > 0 and ga > 0))):
            if bt.get(k):
                filas.append(dict(base, mercado='Ambos marcan', apuesta=nom, cuota=bt[k],
                                  apertura=None, verde=int(ok), p_pin=np.nan))
    x = pd.DataFrame(filas)
    x['cuota'] = pd.to_numeric(x.cuota, errors='coerce')
    x['apertura'] = pd.to_numeric(x.apertura, errors='coerce')
    return x[x.cuota > 1.01]


def rinde(s):
    return 100 * ((s.verde * s.cuota).mean() - 1) if len(s) else np.nan


def boot_rinde(s, n=3000):
    g = s.assign(dev=s.verde * s.cuota).groupby('fecha').agg(dev=('dev', 'sum'),
                                                             n=('dev', 'size'))
    A = g.values
    b = [A[i].sum(axis=0) for i in [rng.integers(0, len(A), len(A)) for _ in range(n)]]
    b = [x[0] / x[1] - 1 for x in b]
    return 100 * np.percentile(b, 5), 100 * np.mean(b)


def combinadas(e, k, maxc=200):
    dev, n, hits = 0.0, 0, 0
    por_dia = []
    for f, g in e.groupby('fecha'):
        if len(g) < k:
            continue
        c, v = g.cuota.values, g.verde.values
        from math import comb
        idx = (np.array(list(combinations(range(len(g)), k))) if comb(len(g), k) <= maxc
               else np.array([rng.choice(len(g), k, replace=False) for _ in range(maxc)]))
        pago = np.prod(c[idx], axis=1) * np.prod(v[idx], axis=1)
        por_dia.append((len(idx), pago.sum(), (pago > 0).sum()))
    if not por_dia:
        return None
    A = np.array(por_dia, dtype=float)
    b = []
    for _ in range(2000):
        s = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        b.append(s[1] / s[0] - 1)
    return {'dias': len(A), 'n': int(A[:, 0].sum()), 'acierto': A[:, 2].sum() / A[:, 0].sum(),
            'rinde': A[:, 1].sum() / A[:, 0].sum() - 1, 'p5': np.percentile(b, 5)}


def main():
    ult = fotos()
    x = patas(ult)
    print('Novibet antes del inicio: %d partidos con resultado · %d patas · %s a %s'
          % (x.eid.nunique(), len(x), x.fecha.min().date(), x.fecha.max().date()))
    print('con Pinnacle: %d partidos' % x[x.p_pin.notna()].eid.nunique())
    out = {}
    print('\n1. CADA PATA DE NOVIBET, por franja de cuota (todas las selecciones)')
    x['cb'] = pd.cut(x.cuota, [1, 1.2, 1.35, 1.5, 1.8, 2.2, 3, 50])
    for b, s in x.groupby('cb', observed=True):
        print('   cuota %-11s n %5d · acierto %5.1f %% · rinde %+6.1f %%'
              % (b, len(s), 100 * s.verde.mean(), rinde(s)))
        out['franja %s' % b] = [len(s), s.verde.mean(), rinde(s)]
    print('\n2. ERROR DE PRECIO (Pinnacle sin margen × cuota de Novibet)')
    y = x[x.p_pin.notna()].copy()
    y['ev'] = y.p_pin * y.cuota
    for lo, hi in ((0, .95), (.95, 1.0), (1.0, 1.02), (1.02, 1.05), (1.05, 9)):
        s = y[(y.ev >= lo) & (y.ev < hi)]
        print('   Pinnacle×cuota %.2f-%.2f: n %4d · acierto %5.1f %% · prometía %5.1f %% · rinde %+6.1f %%'
              % (lo, hi, len(s), 100 * s.verde.mean(), 100 * s.p_pin.mean(), rinde(s)))
    err = y[(y.ev >= 1.02)]
    p5, med = boot_rinde(err)
    print('   errores (≥ 1,02): %d · acierto %.1f %% · rinde %+.1f %% (bootstrap p5 %+.1f)'
          % (len(err), 100 * err.verde.mean(), rinde(err), p5))
    err2 = err[err.cuota <= 2.0]
    if len(err2):
        p5b, _ = boot_rinde(err2)
        print('   errores con cuota ≤ 2,00: %d · acierto %.1f %% · rinde %+.1f %% (p5 %+.1f)'
              % (len(err2), 100 * err2.verde.mean(), rinde(err2), p5b))
    out['errores'] = [len(err), err.verde.mean(), rinde(err), p5]
    print('\n3. MOVIMIENTO DESDE LA APERTURA (1X2 y doble oportunidad)')
    z = x[x.apertura.notna() & (x.apertura > 1)].copy()
    z['mov'] = z.cuota / z.apertura - 1
    for nom, m in (('bajó ≥ 5 %', z.mov <= -0.05), ('bajó 0-5 %', (z.mov > -0.05) & (z.mov < 0)),
                   ('igual', z.mov == 0), ('subió 0-5 %', (z.mov > 0) & (z.mov < 0.05)),
                   ('subió ≥ 5 %', z.mov >= 0.05)):
        s = z[m]
        print('   cuota %-11s n %5d · acierto %5.1f %% · cuota media %.2f · rinde %+6.1f %%'
              % (nom, len(s), 100 * s.verde.mean(), s.cuota.mean(), rinde(s)))
        out['mov %s' % nom] = [len(s), s.verde.mean(), rinde(s)]
    print('\n4. COMBINADAS con patas de Novibet, sorteadas por día (una por partido)')
    reglas = {
        'favoritas ≤ 1,35 (estilo «meter»)': x[x.cuota <= 1.35],
        'cuota 1,40-1,80 (estilo de los boletos)': x[x.cuota.between(1.40, 1.80)],
        'errores de precio (≥ 1,02)': err,
        'errores de precio con cuota ≤ 2,00': err2,
    }
    for nom, e in reglas.items():
        e = e.sort_values('cuota').drop_duplicates('eid')
        print('   %s — %d patas, acierto %.1f %%, rinde suelta %+.1f %%'
              % (nom, len(e), 100 * e.verde.mean(), rinde(e)))
        out['comb ' + nom] = {}
        for k in (2, 3, 4, 6):
            r = combinadas(e, k)
            if r and r['dias'] >= 5:
                print('      %d patas: %6d combinadas en %2d días · acierto %5.1f %% · rinde %+6.1f %% (p5 %+.1f)'
                      % (k, r['n'], r['dias'], 100 * r['acierto'], 100 * r['rinde'], 100 * r['p5']))
                out['comb ' + nom][k] = r
    x.to_pickle('_v332_novibet_patas.pkl')
    json.dump(out, open('_v332_novibet_real.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
