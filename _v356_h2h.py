#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v356 — ¿El H2H y la tendencia de goles dicen qué lado de los goles meter?

El usuario, con Lexington–Tulsa 0-0 delante (le dimos «Más de 1.5»; en sus
cuatro enfrentamientos previos nunca hubo más de 3 goles: 0-0, 0-0, 3-0,
0-2): «¿por qué preferiste +1.5 en lugar de −3.5? Verifica ese patrón en las
rojas».

Para cada partido de la réplica de la tarjeta (`_v356_candidatas.csv.gz`,
889 partidos 19-sep → 9-oct), con los históricos de su liga y SÓLO lo jugado
antes de ese día:
  · H2H: partidos previos entre los dos, media de goles, % con 2+ goles y %
    con 4+ goles;
  · forma: media de goles de los últimos 5 partidos de cada equipo.

Reglas (se cambia la «se mete» de goles por la otra cola si también pasa la
regla del «meter»; si no, por la siguiente que la pase):
  R1  «Más de 1.5» con H2H de pocos goles (≥ 3 previos y % con 2+ ≤ U)
      → «Menos de 3.5».
  R2  «Menos de 3.5» con H2H de muchos (≥ 3 previos y % con 4+ ≥ V)
      → «Más de 1.5».
  R3  igual que R1 con la forma de los dos equipos (media ≤ F goles).
U, V, F se eligen con la primera mitad de días y se juzgan con la segunda.
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

import _v344_precio as P
import _v356_anticipar as A

rng = np.random.default_rng(3562)


def historicos():
    out = {}
    for ruta in glob.glob('historico_*.csv'):
        liga = ruta[len('historico_'):-4]
        try:
            d = pd.read_csv(ruta, usecols=['date', 'home_team', 'away_team', 'home_goals',
                                           'away_goals'], low_memory=False)
        except Exception:
            continue
        d = d.dropna(subset=['home_goals', 'away_goals'])
        d['h'] = d.home_team.map(P._norm)
        d['a'] = d.away_team.map(P._norm)
        d['t'] = d.home_goals + d.away_goals
        d['date'] = d.date.astype(str).str[:10]
        out[liga] = d
    return out


def rasgos(d, hist):
    filas = []
    for (par, liga, dia), _ in d.groupby(['partido', 'liga', 'dia']):
        if ' vs ' not in str(par) or liga not in hist:
            continue
        h, a = (P._norm(x.strip()) for x in par.split(' vs ', 1))
        H = hist[liga]
        H = H[H.date < dia]
        m = H[((H.h == h) & (H.a == a)) | ((H.h == a) & (H.a == h))].tail(10)
        fh = H[(H.h == h) | (H.a == h)].tail(5)
        fa = H[(H.h == a) | (H.a == a)].tail(5)
        filas.append({'partido': par, 'h2h_n': len(m),
                      'h2h_media': m.t.mean() if len(m) else np.nan,
                      'h2h_2mas': (m.t >= 2).mean() if len(m) else np.nan,
                      'h2h_4mas': (m.t >= 4).mean() if len(m) else np.nan,
                      'forma_h': fh.t.mean() if len(fh) >= 3 else np.nan,
                      'forma_a': fa.t.mean() if len(fa) >= 3 else np.nan})
    return pd.DataFrame(filas)


def tarjeta(d, cond_mas, cond_menos):
    """Las metidas con el cambio de cola."""
    out = []
    for par, g in d.groupby('partido', sort=False):
        met = g[g.metida]
        if met.empty:
            continue
        r = g.iloc[0]
        quitar = met[(met.apuesta.eq('Goles: Más de 1.5') & cond_mas(r))
                     | (met.apuesta.eq('Goles: Menos de 3.5') & cond_menos(r))]
        if quitar.empty:
            out.append(met)
            continue
        q = met.drop(quitar.index)
        nuevas = []
        for x in quitar.itertuples():
            otra = 'Goles: Menos de 3.5' if x.apuesta.startswith('Goles: Más') else 'Goles: Más de 1.5'
            c = g[(g.apuesta == otra) & (g.motivo.fillna('') == '') & ~g.apuesta.isin(set(q.apuesta))]
            if c.empty:
                c = g[(g.motivo.fillna('') == '') & ~g.metida & ~g.apuesta.isin(set(q.apuesta))
                      & ~g.mercado.isin(set(q.mercado))].sort_values('p', ascending=False)
            if len(c):
                nuevas.append(c.head(1))
        out.append(pd.concat([q] + nuevas))
    return pd.concat(out)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = A.cargar()
    if os.path.exists('_v356_h2h_rasgos.csv'):
        ra = pd.read_csv('_v356_h2h_rasgos.csv')
    else:
        ra = rasgos(d, historicos())
        ra.to_csv('_v356_h2h_rasgos.csv', index=False)
    d = d.merge(ra, on='partido', how='left')
    out = {'partidos_con_h2h3': int(ra[ra.h2h_n >= 3].shape[0]), 'partidos': int(ra.shape[0])}
    met = d[d.metida]
    # 1) ¿acierta menos «Más de 1.5» con H2H de pocos goles? (descriptivo)
    m15 = met[met.apuesta.eq('Goles: Más de 1.5') & (met.h2h_n >= 3)].copy()
    m15['b'] = pd.cut(m15.h2h_2mas, [-0.01, 0.5, 0.7, 0.85, 1.0])
    print('«Más de 1.5» por % del H2H con 2+ goles:')
    print(m15.groupby(['b', 'tramo'], observed=True).acierto.agg(['size', 'mean']).unstack('tramo').round(3).to_string())
    m35 = met[met.apuesta.eq('Goles: Menos de 3.5') & (met.h2h_n >= 3)].copy()
    m35['b'] = pd.cut(m35.h2h_4mas, [-0.01, 0.1, 0.25, 0.4, 1.0])
    print('\n«Menos de 3.5» por % del H2H con 4+ goles:')
    print(m35.groupby(['b', 'tramo'], observed=True).acierto.agg(['size', 'mean']).unstack('tramo').round(3).to_string())
    m15f = met[met.apuesta.eq('Goles: Más de 1.5')].copy()
    m15f['forma'] = (m15f.forma_h + m15f.forma_a) / 2
    m15f['b'] = pd.cut(m15f.forma, [0, 2.0, 2.4, 2.8, 9])
    print('\n«Más de 1.5» por la media de goles de los últimos 5 (los dos equipos):')
    print(m15f.groupby(['b', 'tramo'], observed=True).acierto.agg(['size', 'mean']).unstack('tramo').round(3).to_string())
    base = met
    res = {}
    for nombre, cm, cn in (
            [('R1_U%.2f' % U, (lambda r, U=U: (r.h2h_n >= 3) & (r.h2h_2mas <= U)), (lambda r: False))
             for U in (0.4, 0.5, 0.6, 0.7)]
            + [('R2_V%.2f' % V, (lambda r: False), (lambda r, V=V: (r.h2h_n >= 3) & (r.h2h_4mas >= V)))
               for V in (0.3, 0.4, 0.5)]
            + [('R3_F%.1f' % F, (lambda r, F=F: ((r.forma_h + r.forma_a) / 2 <= F)), (lambda r: False))
               for F in (2.0, 2.2, 2.4)]):
        t = tarjeta(d, lambda r, f=cm: bool(f(r)) if f(r) == f(r) else False,
                    lambda r, f=cn: bool(f(r)) if f(r) == f(r) else False)
        res[nombre] = {tr: A.resumen(t[t.tramo == tr]) for tr in ('elige', 'juzga')}
        res[nombre]['dias'] = {dia: (int(t[t.dia == dia].acierto.sum()),
                                     int((1 - t[t.dia == dia].acierto).sum()))
                               for dia in ('2026-10-08', '2026-10-09')}
        res[nombre]['boot_juzga'] = A.boot_dif(base[base.tramo == 'juzga'], t[t.tramo == 'juzga'])
    res['base'] = {tr: A.resumen(base[base.tramo == tr]) for tr in ('elige', 'juzga')}
    res['base']['dias'] = {dia: (int(base[base.dia == dia].acierto.sum()),
                                 int((1 - base[base.dia == dia].acierto).sum()))
                           for dia in ('2026-10-08', '2026-10-09')}
    print()
    for k, v in res.items():
        print('%-10s elige %s✅ %s❌ %.1f%% | juzga %s✅ %s❌ %.1f%% | días %s %s' % (
            k, v['elige']['verdes'], v['elige']['rojas'], 100 * v['elige']['acierto'],
            v['juzga']['verdes'], v['juzga']['rojas'], 100 * v['juzga']['acierto'], v['dias'],
            v.get('boot_juzga', '')))
    out['reglas'] = res
    json.dump(out, open('_v356_h2h.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
