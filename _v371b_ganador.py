#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v371b — Ganador, empate y más/menos 2,5 «inclinados a la casa», con AÑOS de
finalizados (los `historico_*.csv` de las 87 ligas: cuota de la casa y de
Pinnacle desde 2010).

El usuario: «en este tipo de soñadoras es donde podemos ver qué equipo gana,
inclinado a lo que diga la casa; incluso empates; empezar a tener mejores
cuotas» y «simulaciones con el histórico de finalizados para refinar la
metodología».

Para cada partido con cuotas, las patas: gana local, empate, gana visita, más y
menos de 2,5. La probabilidad de la casa sin margen se saca de su propio
mercado (reparto proporcional) y la de Pinnacle igual. Zona de cuota 1,30-1,70.
Se mide, por banda de la casa y por lado (favorito local / favorito visitante /
empate / más / menos):
  · acierto contra lo que la casa dice (si la casa se queda corta, ahí hay
    con qué inclinarse);
  · ganancia por $100 con la cuota de la casa;
  · por temporadas recientes (2023→) y en dos mitades por fecha, bootstrap.
Escribe `_v371b_ganador.json`.
"""
import glob
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(3712)
CMIN, CMAX = 1.30, 1.70


def cargar():
    filas = []
    for f in glob.glob('historico_*.csv'):
        try:
            d = pd.read_csv(f, usecols=lambda c: c in {
                'date', 'home_goals', 'away_goals', 'odd_home', 'odd_draw', 'odd_away',
                'odd_over25', 'odd_under25', 'odd_home_pin', 'odd_draw_pin', 'odd_away_pin',
                'MATCH_ID'}, low_memory=False)
        except Exception:
            continue
        d['liga'] = f[len('historico_'):-4]
        if 'date' not in d or 'odd_home' not in d:
            continue
        d['fecha'] = pd.to_datetime(d['date'], errors='coerce', format='mixed')
        filas.append(d)
    d = pd.concat(filas, ignore_index=True)
    d = d.dropna(subset=['fecha', 'home_goals', 'away_goals', 'odd_home', 'odd_draw', 'odd_away'])
    d = d[(d.odd_home > 1) & (d.odd_draw > 1) & (d.odd_away > 1)]
    d = d.drop_duplicates(subset=['liga', 'MATCH_ID'])
    return d


def patas(d):
    gh, ga = d.home_goals.astype(float), d.away_goals.astype(float)
    im = 1 / d[['odd_home', 'odd_draw', 'odd_away']]
    s = im.sum(axis=1)
    out = []
    for lado, col, ok in (('gana local', 'odd_home', gh > ga), ('empate', 'odd_draw', gh == ga),
                          ('gana visita', 'odd_away', gh < ga)):
        x = pd.DataFrame({'mid': d.liga + '|' + d.MATCH_ID.astype(str), 'fecha': d.fecha,
                          'liga': d.liga, 'lado': lado, 'cuota': d[col],
                          'p_c': (1 / d[col]) / s, 'margen': s - 1, 'ok': ok.astype(int)})
        pc = {'odd_home': 'odd_home_pin', 'odd_draw': 'odd_draw_pin', 'odd_away': 'odd_away_pin'}[col]
        if pc in d:
            sp = (1 / d[['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']]).sum(axis=1)
            x['p_pin'] = (1 / d[pc]) / sp
        out.append(x)
    ou = d.dropna(subset=['odd_over25', 'odd_under25'])
    ou = ou[(ou.odd_over25 > 1) & (ou.odd_under25 > 1)]
    so = 1 / ou.odd_over25 + 1 / ou.odd_under25
    tot = ou.home_goals.astype(float) + ou.away_goals.astype(float)
    for lado, col, ok in (('más de 2.5', 'odd_over25', tot > 2.5), ('menos de 2.5', 'odd_under25', tot < 2.5)):
        out.append(pd.DataFrame({'mid': ou.liga + '|' + ou.MATCH_ID.astype(str), 'fecha': ou.fecha,
                                 'liga': ou.liga, 'lado': lado, 'cuota': ou[col],
                                 'p_c': (1 / ou[col]) / so, 'margen': so - 1, 'ok': ok.astype(int)}))
    x = pd.concat(out, ignore_index=True)
    x['gan'] = np.where(x.ok == 1, x.cuota - 1, -1.0)
    return x


def _boot(z, col, n=1000):
    g = z.groupby('mid')[col].agg(['sum', 'count']).values
    return np.array([g[i].sum(0)[0] / g[i].sum(0)[1]
                     for i in (rng.integers(0, len(g), len(g)) for _ in range(n))])


def res(z):
    if len(z) < 30:
        return {'n': int(len(z))}
    return {'n': int(len(z)), 'acierto': round(float(z.ok.mean()), 4),
            'casa': round(float(z.p_c.mean()), 4),
            'pin': round(float(z.p_pin.mean()), 4) if 'p_pin' in z and z.p_pin.notna().any() else None,
            'cuota': round(float(z.cuota.mean()), 3), 'margen': round(float(z.margen.mean()), 4),
            'gan_100': round(100 * float(z.gan.mean()), 2),
            'gan_p5': round(100 * float(np.percentile(_boot(z, 'gan'), 5)), 2)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar()
    x = patas(d)
    z = x[(x.cuota >= CMIN) & (x.cuota <= CMAX)].copy()
    corte = z.fecha.quantile(0.5)
    rec = z[z.fecha >= '2023-07-01']
    R = {'partidos': int(d.shape[0]), 'desde': str(d.fecha.min().date()), 'hasta': str(d.fecha.max().date()),
         'zona': res(z)}
    z['banda'] = pd.cut(z.p_c, [0, .55, .60, .65, .70, .75, 1])
    for nombre, q in (('todo', z), ('reciente_2023', rec.assign(banda=pd.cut(rec.p_c, [0, .55, .60, .65, .70, .75, 1])))):
        R[nombre] = {}
        for lado, g in q.groupby('lado'):
            R[nombre][lado] = {'todo': res(g), 'A': res(g[g.fecha < corte]), 'B': res(g[g.fecha >= corte]),
                               'bandas': {str(b): res(h) for b, h in g.groupby('banda', observed=True)}}
    # el empate, a su cuota (fuera de la zona): ¿la casa lo paga de más o de menos?
    em = x[x.lado == 'empate'].copy()
    em['bc'] = pd.cut(em.cuota, [1, 2.8, 3.2, 3.6, 4.5, 99])
    R['empate_por_cuota'] = {str(b): res(g) for b, g in em.groupby('bc', observed=True)}
    # el favorito de la casa a cualquier cuota (¿hasta dónde vale inclinarse?)
    fav = x[x.lado.isin(['gana local', 'gana visita'])].copy()
    fav['bc'] = pd.cut(fav.cuota, [1, 1.2, 1.3, 1.45, 1.6, 1.8, 2.0, 2.5, 99])
    R['ganador_por_cuota'] = {str(b): res(g) for b, g in fav.groupby('bc', observed=True)}
    R['ganador_por_cuota_reciente'] = {str(b): res(g) for b, g in fav[fav.fecha >= '2023-07-01']
                                       .groupby('bc', observed=True)}
    json.dump(R, open('_v371b_ganador.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(R['partidos'], R['desde'], R['hasta'], R['zona'])
    for nombre in ('todo', 'reciente_2023'):
        print('==', nombre)
        for lado, v in R[nombre].items():
            print('  %-13s %s | A %s | B %s' % (lado, v['todo'], v['A'].get('gan_100'), v['B'].get('gan_100')))
    print('== ganador por cuota (todo)')
    for b, v in R['ganador_por_cuota'].items():
        print('  ', b, v)
    print('== ganador por cuota (2023→)')
    for b, v in R['ganador_por_cuota_reciente'].items():
        print('  ', b, v)
    print('== empate por cuota')
    for b, v in R['empate_por_cuota'].items():
        print('  ', b, v)


if __name__ == '__main__':
    main()
