# -*- coding: utf-8 -*-
"""
v333 — VALIDACIÓN 3: EL ERROR DE PRECIO DE PLAYDOIT CONTRA PINNACLE, EN LA
MISMA FOTO.

La v332 vio que el «error de precio» contra el Pinnacle de radar_capturas
perdía −37 % en Novibet porque las dos fotos no eran del mismo momento.
`odds_snapshots.csv` guarda barridos HORARIOS con Playdoit (la casa
principal del usuario) y Pinnacle a la vez: la clave del barrido es la hora.
Se toma, por partido, el último barrido ANTES del inicio en que estén las dos,
y se mide con el resultado real (pick_ledger.csv):

  · valor = Pinnacle sin margen × cuota de Playdoit, por tramos
  · los «errores» (≥ 1,02), también sólo los sólidos (Pinnacle ≥ 55 %)
  · dos mitades, bootstrap por día, combinadas de 2-3 errores
  · y con el pago anticipado por 2 goles sumado (+1,3 pts, v332) cuando la
    pata es «Gana X», por si el usuario la juega en una casa que lo da
"""
from __future__ import annotations

import io
import json
import sys
from itertools import combinations

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3332)


def datos() -> pd.DataFrame:
    o = pd.read_csv('odds_snapshots.csv', low_memory=False)
    o = o[o.fase == 'snapshot'].copy()
    o['hora'] = o.snapshot_key.str.split('|').str[0]
    P = o[o.bookmaker == 'Playdoit']
    Pi = o[o.bookmaker == 'Pinnacle']
    j = P.merge(Pi[['match_id', 'hora', 'odds_home', 'odds_draw', 'odds_away']],
                on=['match_id', 'hora'], suffixes=('', '_pin'))
    j = j[j.dias_al_partido >= 0]
    # el último barrido antes del partido
    j = j.sort_values(['match_id', 'dias_al_partido', 'hora']).groupby('match_id').agg('first').reset_index()
    l = pd.read_csv('pick_ledger.csv', usecols=['match_id', 'goles_local', 'goles_visit',
                                                'p_home', 'p_draw', 'p_away'])
    j = j.merge(l, on='match_id', how='inner')
    j = j[j.goles_local.notna()]
    filas = []
    for _, r in j.iterrows():
        pin = [r.odds_home_pin, r.odds_draw_pin, r.odds_away_pin]
        if not all(np.isfinite(pin)) or min(pin) <= 1:
            continue
        inv = [1 / x for x in pin]
        s = sum(inv)
        pp = [x / s for x in inv]
        gh, ga = r.goles_local, r.goles_visit
        for nom, c, p, g, pm in (('Gana local', r.odds_home, pp[0], gh > ga, r.p_home),
                                 ('Empate', r.odds_draw, pp[1], gh == ga, r.p_draw),
                                 ('Gana visita', r.odds_away, pp[2], ga > gh, r.p_away)):
            if np.isfinite(c) and c > 1:
                filas.append({'fecha': pd.to_datetime(r.match_date), 'mid': r.match_id,
                              'liga': r.league_key, 'apuesta': nom, 'cuota': c,
                              'p_pin': p, 'p_mod': pm, 'verde': int(g),
                              'dias': r.dias_al_partido})
    x = pd.DataFrame(filas)
    x['valor'] = x.p_pin * x.cuota
    return x


def rinde(s, extra=0.0):
    return 100 * (((s.verde + extra) * s.cuota).mean() - 1)


def boot(s, n=3000):
    g = s.assign(d=s.verde * s.cuota).groupby('fecha').d.agg(['sum', 'size']).values
    b = []
    for _ in range(n):
        q = g[rng.integers(0, len(g), len(g))].sum(axis=0)
        b.append(q[0] / q[1] - 1)
    return 100 * np.percentile(b, 5)


def main():
    x = datos()
    mitad = x.fecha.sort_values().iloc[len(x) // 2]
    print('Playdoit + Pinnacle en el mismo barrido, con resultado: %d partidos, %d patas, %s a %s'
          % (x.mid.nunique(), len(x), x.fecha.min().date(), x.fecha.max().date()))
    print('días del barrido al partido: mediana %.1f' % x.dias.median())
    out = {}
    print('\n   valor          n     acierto  Pinnacle  cuota  rinde    mitades')
    for lo, hi in ((0, .90), (.90, .95), (.95, 1.0), (1.0, 1.02), (1.02, 1.05), (1.05, 9)):
        s = x[(x.valor >= lo) & (x.valor < hi)]
        if len(s) < 20:
            continue
        a, b = s[s.fecha < mitad], s[s.fecha >= mitad]
        print('   %.2f-%.2f  %6d   %5.1f %%   %5.1f %%  %5.2f  %+6.1f %%  %+.1f / %+.1f'
              % (lo, hi, len(s), 100 * s.verde.mean(), 100 * s.p_pin.mean(), s.cuota.mean(),
                 rinde(s), rinde(a), rinde(b)))
        out['%.2f-%.2f' % (lo, hi)] = [len(s), s.verde.mean(), s.p_pin.mean(), rinde(s), rinde(a), rinde(b)]
    for nom, m in (('errores ≥ 1,02', x.valor >= 1.02),
                   ('errores ≥ 1,02 y sólidos (Pinnacle ≥ 55 %)', (x.valor >= 1.02) & (x.p_pin >= .55)),
                   ('errores ≥ 1,02 con cuota ≤ 2,00', (x.valor >= 1.02) & (x.cuota <= 2.0))):
        s = x[m]
        if len(s) < 10:
            print('   %s: sólo %d' % (nom, len(s)))
            continue
        a, b = s[s.fecha < mitad], s[s.fecha >= mitad]
        g = s[s.apuesta != 'Empate']
        print('   %s: n %d · acierto %.1f %% · rinde %+.1f %% (p5 %+.1f) · mitades %+.1f / %+.1f'
              ' · «Gana X» con pago anticipado %+.1f %%'
              % (nom, len(s), 100 * s.verde.mean(), rinde(s), boot(s), rinde(a), rinde(b),
                 rinde(g, 0.013)))
        out[nom] = [len(s), s.verde.mean(), rinde(s), boot(s), rinde(a), rinde(b)]
    print('\n   y SIN Pinnacle, por franja de cuota (lo que rinde Playdoit a secas):')
    x['cb'] = pd.cut(x.cuota, [1, 1.3, 1.6, 2.0, 3.0, 50])
    for b, s in x.groupby('cb', observed=True):
        print('   cuota %-11s n %5d · acierto %5.1f %% · rinde %+6.1f %%' % (b, len(s), 100 * s.verde.mean(), rinde(s)))
    json.dump(out, open('_v333_playdoit_pinnacle.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
