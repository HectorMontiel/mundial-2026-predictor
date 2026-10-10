#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v359 — NHL contra la casa: ganador, hándicap y goles (más/menos).

El usuario: «agrega la NHL con todo lo de contra la casa, nuestro método».
Con `_v359_nhl_cierres.csv` (sbro 2007-22 + ESPN 2022-hoy, cierre de la casa):

  1. GANADOR: ¿la casa acierta lo que promete?, ¿hay favorito al ~80 %?
  2. HÁNDICAP: P(margen del equipo + línea > 0) según la probabilidad del
     equipo en la casa (bandas de 5 pts), para las líneas que publica
     Playdoit (±1,5 a ±4,5). Tabla elegida con 2014-2018, juzgada 2019-2025.
  3. GOLES: P(total > principal − k) y P(total < principal + k), sólo con
     líneas en ,5 (sin devolución).
  4. LA REGLA: por lado, la línea de mejor cuota (la menos probable) que
     llega a la meta (75 / 78 / 80 %); las 2 mejores del partido; dos tramos,
     bootstrap; 2026 y la pretemporada aparte.
Guarda lo que usa la app en `nhl_lineas.json`.
"""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(359)
LINEAS = [-3.5, -2.5, -1.5, 1.5, 2.5, 3.5, 4.5]
BANDAS = np.arange(0.20, 0.851, 0.05)
KS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]


def cargar():
    d = pd.read_csv('_v359_nhl_cierres.csv')
    d = d[d.gh.notna() & d.ga.notna() & d.ml_home.notna() & d.ml_away.notna()].copy()
    d = d[(d.ml_home > 1) & (d.ml_away > 1)]
    s = 1 / d.ml_home + 1 / d.ml_away
    d['p_local'] = (1 / d.ml_home) / s
    d['margen'] = d.gh - d.ga
    d['tot'] = d.gh + d.ga
    d['tramo'] = np.select([d.tipo == 'pretemporada', d.temporada <= 2018, d.temporada <= 2025],
                           ['pre', 'elige', 'juzga'], 'nuevo')
    return d


def lados(d):
    """Una fila por equipo y partido: su probabilidad y su margen."""
    a = pd.DataFrame({'idx': d.index, 'p': d.p_local, 'm': d.margen, 'tramo': d.tramo,
                      'temporada': d.temporada})
    b = pd.DataFrame({'idx': d.index, 'p': 1 - d.p_local, 'm': -d.margen, 'tramo': d.tramo,
                      'temporada': d.temporada})
    return pd.concat([a, b], ignore_index=True)


def tabla_hcp(L):
    out = []
    for lo in BANDAS:
        g = L[(L.p >= lo) & (L.p < lo + 0.05)]
        if len(g) < 60:
            continue
        fila = {'p': round(float(g.p.mean()), 4), 'n': int(len(g))}
        for lin in LINEAS:
            fila['%+g' % lin] = round(float(((g.m + lin) > 0).mean()), 4)
        out.append(fila)
    return out


def interp(tab, p, lin):
    clave = '%+g' % lin
    pts = sorted((b['p'], b[clave]) for b in tab)
    xs, ys = zip(*pts)
    return float(np.interp(p, xs, ys))


def tabla_tot(d):
    t = d[d.total.notna()]
    out = {'mas': {}, 'menos': {}}
    for k in KS:
        Lm, Ln = t.total - k, t.total + k
        okm, okn = (Lm % 1) == 0.5, (Ln % 1) == 0.5
        if okm.sum() > 100:
            out['mas']['%.1f' % k] = round(float((t.tot[okm] > Lm[okm]).mean()), 4)
        if okn.sum() > 100:
            out['menos']['%.1f' % k] = round(float((t.tot[okn] < Ln[okn]).mean()), 4)
    return out


def interp_tot(tt, lado, k):
    pts = sorted((float(a), b) for a, b in tt[lado].items())
    if not pts or k > pts[-1][0] or k < pts[0][0]:
        return None
    xs, ys = zip(*pts)
    return float(np.interp(k, xs, ys))


def predicciones(d, th, tt):
    """Todas las líneas que publicaría Playdoit, con su probabilidad y si ganó."""
    filas = []
    for r in d.itertuples():
        for lado, pe, m in (('local', r.p_local, r.margen), ('visita', 1 - r.p_local, -r.margen)):
            for lin in LINEAS:
                filas.append({'idx': r.Index, 'tramo': r.tramo, 'temporada': r.temporada,
                              'mercado': 'Handicap', 'lado': lado,
                              'tipo': 'favorito' if pe >= 0.5 else 'no_favorito',
                              'p': interp(th, pe, lin), 'gana': (m + lin) > 0, 'k': lin})
        if r.total == r.total:
            for lado, sg in (('mas', -1), ('menos', 1)):
                for k in KS:
                    L = r.total + sg * k
                    if L % 1 != 0.5:
                        continue
                    p = interp_tot(tt, lado, k)
                    if p is None:
                        continue
                    filas.append({'idx': r.Index, 'tramo': r.tramo, 'temporada': r.temporada,
                                  'mercado': 'Goles', 'lado': lado, 'tipo': lado,
                                  'p': p, 'gana': (r.tot > L) if lado == 'mas' else (r.tot < L), 'k': k})
    return pd.DataFrame(filas)


def boot(a, n=2000):
    a = np.asarray(a, float)
    if len(a) < 10:
        return None
    return round(float(np.percentile([a[rng.integers(0, len(a), len(a))].mean() for _ in range(n)], 5)), 4)


def regla(f, meta, top2=False):
    x = f[f.p >= meta].sort_values('p').groupby(['idx', 'mercado', 'lado']).head(1)
    if top2:
        x = x.sort_values('p', ascending=False).groupby('idx').head(2)
    return x


def resumen(x):
    if not len(x):
        return {'n': 0}
    out = {'n': int(len(x)), 'acierta': round(float(x.gana.mean()), 4), 'p5': boot(x.gana),
           'promete': round(float(x.p.mean()), 4)}
    out['por_tipo'] = {k: [int(len(g)), round(float(g.gana.mean()), 3)]
                       for k, g in x.groupby(['mercado', 'tipo'])}
    out['por_tipo'] = {'%s/%s' % k: v for k, v in out['por_tipo'].items()}
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar()
    print('partidos con cuota y marcador:', d.groupby('tramo').size().to_dict())
    doc = {}
    # 1. ganador
    d['pf'] = np.maximum(d.p_local, 1 - d.p_local)
    d['gana_fav'] = np.where(d.p_local >= 0.5, d.margen > 0, d.margen < 0)
    gan = {}
    for tr in ('elige', 'juzga', 'nuevo', 'pre'):
        g = d[d.tramo == tr]
        b = pd.cut(g.pf, [0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 1.0])
        gan[tr] = [{'banda': str(k), 'n': int(len(x)), 'promete': round(float(x.pf.mean()), 3),
                    'acierta': round(float(x.gana_fav.mean()), 3)} for k, x in g.groupby(b, observed=True)]
        print('ganador', tr, gan[tr])
    doc['ganador'] = gan
    # 2-3. tablas con el tramo de elegir; luego con todo (para la app)
    el = d[d.tramo == 'elige']
    th, tt = tabla_hcp(lados(el)), tabla_tot(el)
    print('tabla hcp (elige):')
    for b in th:
        print('  ', b)
    print('tabla goles (elige):', tt)
    f = predicciones(d, th, tt)
    res = {}
    for meta in (0.75, 0.78, 0.80, 0.85):
        for top2 in (False, True):
            clave = 'meta%d%s' % (int(meta * 100), '_top2' if top2 else '')
            res[clave] = {tr: resumen(regla(f[f.tramo == tr], meta, top2))
                          for tr in ('elige', 'juzga', 'nuevo', 'pre')}
            print(clave, json.dumps({tr: {k: v for k, v in r.items() if k != 'por_tipo'}
                                     for tr, r in res[clave].items()}, ensure_ascii=False))
    print('por tipo meta78 juzga:', res['meta78']['juzga'].get('por_tipo'))
    print('por tipo meta78 pre:', res['meta78']['pre'].get('por_tipo'))
    # la pretemporada en dos mitades
    pre = f[f.tramo == 'pre']
    pre_m = {nm: resumen(regla(pre[c], 0.78)) for nm, c in
             (('2022_2023', pre.temporada <= 2023), ('2024_2026', pre.temporada >= 2024))}
    print('pretemporada mitades:', json.dumps({k: v.get('por_tipo') for k, v in pre_m.items()}, ensure_ascii=False))
    doc.update({'reglas': res, 'pretemporada_mitades': pre_m,
                'tabla_elige': {'handicap': th, 'totales': tt}})
    # la tabla de la app: temporada regular y playoffs 2007-2025
    todo = d[d.tramo.isin(['elige', 'juzga'])]
    doc['handicap'] = tabla_hcp(lados(todo))
    doc['totales'] = tabla_tot(todo)
    doc['generado'] = pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    doc['fuente'] = 'sportsbookreviewsonline 2007-2022 + ESPN 2022-hoy (cierre de la casa)'
    json.dump(doc, open('nhl_lineas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    print('guardado nhl_lineas.json')


if __name__ == '__main__':
    main()
