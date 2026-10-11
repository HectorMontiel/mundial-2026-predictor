#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v362 — La metodología de córners del amigo, para «🎲 Apuestas arriesgadas».

El usuario (boleto de Draftea ganado: córners de equipo +4,5/+5,5 y total
+9,5 en la Liga MX, ×78) pasa la metodología:
  · «los que tienen córners altos» (a favor Y en contra): el total sale alto
    (esperaban ~16 y puso +9,5 para asegurar);
  · un equipo que mete muchos y domina en córners (Chivas): su +4,5/+5,5;
  · el tipo de partido: quién juega, dónde, contra quién, la tabla (América
    arriba y Monterrey que no quiere perder: muchos córners de los dos).

Reglas fijadas ANTES de mirar el tramo de juicio (umbrales = tercio alto de
la liga en la temporada, con lo jugado antes de cada partido):
  A1  total: los dos equipos «de córners altos» (a favor + en contra en el
      tercio alto)                      → total más de L
  A2  A1 y partido «grande» (los dos en la mitad de arriba de la tabla)
  A3  equipo: genera mucho (a favor en el tercio alto) y el rival concede
      mucho (en contra en el tercio alto) → equipo más de 4,5 / 5,5
  A4  A3 jugando de local
  M   el Método Contexto (LightGBM de `tiros_equipo` con los rasgos de
      córners, la tabla y la presión): la pata con probabilidad ≥ 75 %.
Con `_v361_metodo.preparar()` (59.120 filas equipo-partido, 26 ligas), el
método se entrena con el 70 % más antiguo; todo se juzga con el 30 % reciente
en dos mitades. Y la COMBINADA: cada día, las k patas más probables (k = 3-6)
del método o de las reglas: cuánto sale entera y qué momio justo tendría.
Escribe `_v362_corners.json`."""
import json
import sys

import numpy as np
import pandas as pd

import _v361_metodo as V
import tiros_equipo as te

rng = np.random.default_rng(362)


def nb_mas(mu, L, k):
    from scipy import stats
    mu = np.clip(np.asarray(mu, float), 0.05, None)
    return stats.nbinom.sf(np.floor(L), k, k / (k + mu))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import lightgbm as lgb
    e = V.preparar().dropna(subset=['corners', 'corners_c'])
    corte = e.fecha.quantile(0.70)
    ent, jui = e[e.fecha < corte], e[e.fecha >= corte].copy()
    m = lgb.LGBMRegressor(objective='poisson', n_estimators=700, learning_rate=0.03,
                          num_leaves=31, min_child_samples=80, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=362)
    m.fit(ent[te.COLUMNAS], ent.corners)
    c2 = ent.fecha.quantile(0.85)
    k = te.ajustar_k(ent[ent.fecha >= c2].corners.values,
                     np.clip(m.predict(ent[ent.fecha >= c2][te.COLUMNAS]), 0.05, None))
    jui['mu'] = np.clip(m.predict(jui[te.COLUMNAS]), 0.05, None)
    # «córners altos»: tercio alto de la liga y temporada, con lo de antes
    for c in ('t_corners', 't_corners_c'):
        jui['q_' + c] = jui.groupby(['liga', 'temporada'])[c].transform(lambda x: x.rank(pct=True))
    jui['alto_favor'] = jui.q_t_corners >= 2 / 3
    jui['alto_contra'] = jui.q_t_corners_c >= 2 / 3
    jui['alto'] = jui.alto_favor & jui.alto_contra
    jui['arriba'] = jui.pos_rel <= 0.5
    r = jui[['mid', 'equipo', 'alto', 'alto_favor', 'alto_contra', 'arriba', 'mu']].rename(
        columns={'equipo': 'rival', 'alto': 'r_alto', 'alto_favor': 'r_alto_favor',
                 'alto_contra': 'r_alto_contra', 'arriba': 'r_arriba', 'mu': 'r_mu'})
    j = jui.merge(r, on=['mid', 'rival'], how='left')
    mitad = j.fecha.quantile(0.5)
    j['tramo'] = np.where(j.fecha < mitad, 'A', 'B')
    out = {'k': round(k, 1), 'corte': str(corte)[:10], 'mitad': str(mitad)[:10]}

    def res(x, col):
        return {tr: {'n': int((x.tramo == tr).sum()),
                     'acierta': round(float(x[x.tramo == tr][col].mean()), 4) if (x.tramo == tr).any() else None}
                for tr in ('A', 'B')}
    # --- equipo más de L
    eq = {}
    for L in (3.5, 4.5, 5.5):
        j['ok'] = (j.corners > L).astype(float)
        j['p_m'] = nb_mas(j.mu, L, k)
        g = {'todos': j, 'A3 genera mucho y el rival concede mucho': j[j.alto_favor & j.r_alto_contra],
             'A4 A3 y de local': j[j.alto_favor & j.r_alto_contra & (j.local == 1)],
             'M método ≥ 75 %': j[j.p_m >= 0.75], 'M método ≥ 80 %': j[j.p_m >= 0.80],
             'A3 y método ≥ 75 %': j[j.alto_favor & j.r_alto_contra & (j.p_m >= 0.75)]}
        eq['%g' % L] = {nm: res(x, 'ok') for nm, x in g.items()}
        print('equipo más de', L, json.dumps(eq['%g' % L], ensure_ascii=False))
    out['equipo'] = eq
    # --- total del partido más de L (una fila por partido: la del local)
    p = j[j.local == 1].copy()
    p['tot'] = p.corners + p.corners_c
    p['mu_t'] = p.mu + p.r_mu
    k_t = (p.mu_t ** 2) / ((p.mu ** 2 + p.r_mu ** 2) / k)
    tot = {}
    for L in (7.5, 8.5, 9.5, 10.5):
        p['ok'] = (p.tot > L).astype(float)
        p['p_m'] = [float(nb_mas(a, L, b)) for a, b in zip(p.mu_t, k_t)]
        g = {'todos': p, 'A1 los dos de córners altos': p[p.alto & p.r_alto],
             'A2 A1 y partido grande': p[p.alto & p.r_alto & p.arriba & p.r_arriba],
             'M método ≥ 75 %': p[p.p_m >= 0.75], 'M método ≥ 80 %': p[p.p_m >= 0.80],
             'A1 y método ≥ 75 %': p[p.alto & p.r_alto & (p.p_m >= 0.75)]}
        tot['%g' % L] = {nm: res(x, 'ok') for nm, x in g.items()}
        print('total más de', L, json.dumps(tot['%g' % L], ensure_ascii=False))
    out['total'] = tot
    # --- la combinada: cada día, las k patas más probables del método
    patas = []
    for L in (3.5, 4.5, 5.5):
        x = j.assign(p=nb_mas(j.mu, L, k), ok=(j.corners > L).astype(int), L=L, tipo='equipo')
        patas.append(x[['fecha', 'mid', 'tramo', 'p', 'ok', 'L', 'tipo']])
    for L in (7.5, 8.5, 9.5, 10.5):
        x = p.assign(p=[float(nb_mas(a, L, b)) for a, b in zip(p.mu_t, k_t)],
                     ok=(p.tot > L).astype(int), L=L, tipo='total')
        patas.append(x[['fecha', 'mid', 'tramo', 'p', 'ok', 'L', 'tipo']])
    pt = pd.concat(patas)
    # una pata por partido y tipo: la más alta línea con p ≥ 0,75 (la que paga más)
    pt = pt[pt.p >= 0.75].sort_values('L', ascending=False).groupby(['mid', 'tipo', 'fecha']).head(1)
    comb = {}
    for kk in (3, 4, 5, 6):
        filas = []
        for (f, tr), g in pt.groupby(['fecha', 'tramo']):
            g = g.sort_values('p', ascending=False).drop_duplicates('mid').head(kk)
            if len(g) < kk:
                continue
            filas.append({'tramo': tr, 'ok': int(g.ok.all()), 'p': float(g.p.prod()),
                          'patas_ok': float(g.ok.mean())})
        c = pd.DataFrame(filas)
        comb[kk] = {tr: {'dias': int((c.tramo == tr).sum()),
                         'entera': round(float(c[c.tramo == tr].ok.mean()), 4),
                         'promete': round(float(c[c.tramo == tr].p.mean()), 4),
                         'patas': round(float(c[c.tramo == tr].patas_ok.mean()), 4),
                         'momio_justo': round(float(1 / c[c.tramo == tr].p.mean()), 2)}
                    for tr in ('A', 'B') if (c.tramo == tr).any()}
        print('combinada de', kk, json.dumps(comb[kk], ensure_ascii=False))
    out['combinada'] = comb
    json.dump(out, open('_v362_corners.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
