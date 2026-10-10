#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v356 — ¿Se pueden anticipar las rojas de goles y cambiarlas por verdes?

El usuario, con las rojas del 8 y 9-oct delante (todas de goles: «Más de 1.5»
que acabaron 0-0 / 1-0 y «Menos de 3.5» que acabaron 2-2 / 1-3): «haz un
modelo de anticipación: no se cumplió el +1.5 pero sí se habría cumplido el
−3.5; quiero evitar rojas y que entren más verdes, sin bajar el estándar».

Pista (FotMob de esas 9 rojas): en 3 de las 5 «Más de 1.5» perdidas, nuestro
modelo de goles (antes de mezclarse con la casa) esperaba bastantes menos
goles que la casa (Nacional–Tolima: modelo 52 %, app 76 %).

Datos: la réplica de la tarjeta (`_v356_candidatas.csv.gz`, 889 partidos
19-sep → 9-oct, precios de Playdoit) y lo que esperaba el modelo
(`_v356_lambdas.csv`, `goles_xg` antes de cada partido).

  H1  ACUERDO: en las «se mete» de goles totales, el acierto según la
      diferencia entre el modelo de goles (Poisson con su xG) y la casa.
  H2  CAMBIO: si la apuesta de goles está en desacuerdo (el modelo la ve T
      puntos por debajo de la casa), se cambia por la siguiente del partido que
      también pasa la regla; si no hay, se quita. T se elige con la primera
      mitad de días y se juzga con la segunda. Verdes, rojas y acierto.
  H3  LA OTRA COLA: cuando falla «Más de 1.5», ¿qué tal la «Menos de 3.5»
      del mismo partido? (es la idea del usuario).
"""
import json
import re
import sys

import numpy as np
import pandas as pd
from scipy.stats import poisson

rng = np.random.default_rng(356)


def cargar():
    d = pd.read_csv('_v356_candidatas.csv.gz', low_memory=False)
    d = d[d.acierto.notna()].copy()
    d['p'] = d.ajustada.fillna(d.prob)
    lam = pd.read_csv('_v356_lambdas.csv')
    lam['xg'] = lam.xg_h + lam.xg_a
    lam = lam.drop_duplicates('partido', keep='last')[['partido', 'xg', 'lam']]
    d = d.merge(lam, on='partido', how='left')

    def p_mod(r):
        m = re.match(r'^Goles: (Más|Menos) de (\d+(?:\.\d+)?)$', str(r.apuesta))
        if not m or not (r.xg == r.xg):
            return np.nan
        lin = float(m.group(2))
        pm = float(poisson.sf(np.floor(lin), r.xg))
        return pm if m.group(1) == 'Más' else 1 - pm
    d['p_xg'] = [p_mod(r) for r in d.itertuples()]
    d['goles_total'] = d.apuesta.str.match(r'^Goles: (Más|Menos) de ')
    d['delta'] = d.p_xg - d.p_mercado.fillna(d.p)
    dias = sorted(d.dia.unique())
    d['tramo'] = np.where(d.dia < dias[len(dias) // 2], 'elige', 'juzga')
    return d


def h1(d):
    m = d[d.metida & d.goles_total & d.delta.notna()].copy()
    m['banda'] = pd.cut(m.delta, [-1, -0.20, -0.10, -0.05, 0.0, 0.05, 1])
    t = m.groupby(['tramo', 'banda'], observed=True).acierto.agg(['size', 'mean']).round(3)
    return m, t


def elegir(d, T):
    """La tarjeta con el cambio: por partido, las «se mete» de siempre salvo
    las de goles en desacuerdo (delta < −T), que se cambian por la siguiente
    que pasa la regla (motivo vacío) y no está en desacuerdo."""
    out = []
    for par, g in d.groupby('partido', sort=False):
        met = g[g.metida]
        if met.empty:
            continue
        malas = met[met.goles_total & (met.delta < -T)]
        if malas.empty:
            out.append(met.assign(cambio=''))
            continue
        quedan = met.drop(malas.index)
        ya = set(quedan.apuesta)
        cand = g[(g.motivo.fillna('') == '') & ~g.metida & ~g.apuesta.isin(ya)]
        cand = cand[~(cand.goles_total & (cand.delta < -T))]
        cand = cand.sort_values('p', ascending=False)
        nuevas = cand.head(len(malas)).assign(cambio='entra')
        out.append(pd.concat([quedan.assign(cambio=''), nuevas]))
    return pd.concat(out) if out else d.iloc[:0]


def resumen(t):
    return {'apuestas': int(len(t)), 'verdes': int(t.acierto.sum()),
            'rojas': int((1 - t.acierto).sum()),
            'acierto': round(float(t.acierto.mean()), 4) if len(t) else None,
            'cuota': round(float(t.cuota.mean()), 3) if len(t) else None}


def boot_dif(base, nueva, n=2000):
    """Acierto nuevo − base, remuestreando partidos."""
    ps = sorted(set(base.partido) | set(nueva.partido))
    gb, gn = base.groupby('partido').acierto, nueva.groupby('partido').acierto
    sb, nb_ = gb.sum().reindex(ps).fillna(0).values, gb.size().reindex(ps).fillna(0).values
    sn, nn = gn.sum().reindex(ps).fillna(0).values, gn.size().reindex(ps).fillna(0).values
    difs, dv = [], []
    for _ in range(n):
        i = rng.integers(0, len(ps), len(ps))
        if nb_[i].sum() == 0 or nn[i].sum() == 0:
            continue
        difs.append(sn[i].sum() / nn[i].sum() - sb[i].sum() / nb_[i].sum())
        dv.append(sn[i].sum() - sb[i].sum())
    return {'acierto_dif': round(float(np.mean(difs)), 4), 'p5': round(float(np.percentile(difs, 5)), 4),
            'verdes_dif': round(float(np.mean(dv)), 1)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar()
    out = {'partidos': int(d.partido.nunique()), 'dias': [d.dia.min(), d.dia.max()],
           'con_xg': int(d[d.metida & d.goles_total].delta.notna().sum())}
    m, t = h1(d)
    print('H1 — acierto de las «se mete» de goles por delta (modelo − casa):')
    print(t.to_string())
    out['H1'] = t.reset_index().astype({'banda': str}).to_dict('records')
    base = d[d.metida]
    out['base'] = {tr: resumen(base[base.tramo == tr]) for tr in ('elige', 'juzga')}
    print('\nBASE', out['base'])
    rej = {}
    for T in (0.05, 0.10, 0.15, 0.20, 0.25):
        nueva = elegir(d, T)
        rej[T] = {tr: resumen(nueva[nueva.tramo == tr]) for tr in ('elige', 'juzga')}
        rej[T]['cambios'] = int((nueva.cambio == 'entra').sum())
        print('T=%.2f' % T, rej[T])
    out['H2_rejilla'] = {str(k): v for k, v in rej.items()}
    # T elegido con la primera mitad: el que más sube el acierto sin perder verdes
    def score(T):
        e = rej[T]['elige']
        return (e['verdes'] >= out['base']['elige']['verdes'] - 2, e['acierto'])
    T = max(rej, key=score)
    nueva = elegir(d, T)
    out['H2_elegido'] = T
    out['H2_juzga'] = {'base': out['base']['juzga'], 'nueva': rej[T]['juzga'],
                       'boot': boot_dif(base[base.tramo == 'juzga'], nueva[nueva.tramo == 'juzga'])}
    out['H2_todo'] = {'base': resumen(base), 'nueva': resumen(nueva), 'boot': boot_dif(base, nueva)}
    print('\nH2 elegido T=%.2f  juzga:' % T, out['H2_juzga'])
    print('H2 todo:', out['H2_todo'])
    # los dos últimos días
    for dia in ('2026-10-08', '2026-10-09'):
        out['H2_' + dia] = {'base': resumen(base[base.dia == dia]), 'nueva': resumen(nueva[nueva.dia == dia])}
        print(dia, out['H2_' + dia])
    # H3: la otra cola
    otra = []
    for par, g in d.groupby('partido'):
        f = g[g.metida & (g.apuesta == 'Goles: Más de 1.5') & (g.acierto == 0)]
        if f.empty:
            continue
        o = g[g.apuesta == 'Goles: Menos de 3.5']
        if len(o):
            otra.append(int(o.acierto.iloc[0]))
    out['H3_menos35_cuando_falla_mas15'] = {'n': len(otra), 'acierta': round(float(np.mean(otra)), 3) if otra else None}
    print('H3:', out['H3_menos35_cuando_falla_mas15'])
    json.dump(out, open('_v356_anticipar.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
