# -*- coding: utf-8 -*-
"""
v306 — ¿HAY LIGAS «SEGURAS»? ¿Y SIGUEN SIÉNDOLO?

El usuario, con un boleto de la J1 japonesa en el que acertó todo menos un
sub-23: «detrás de todo esto hay ligas que son más seguras y otras que no».

Es medible, y la pregunta que decide si sirve no es «¿qué liga fue segura?»
sino «¿la que fue segura lo SIGUE siendo?». Se clasifica cada liga SÓLO con
el 70 % antiguo del ledger (elección) y se juzga en el 30 % reciente (juicio):

    seguridad de la liga = acierto real del favorito − lo que su precio
                           justo (Pinnacle sin margen) le daba

Una liga donde el favorito gana MÁS de lo que dice su precio es una liga
donde apostar al probable rinde. Se forman tres grupos por la elección y se
mira, en el juicio, el acierto contra lo esperado y el ROI al precio del
mercado del favorito con probabilidad justa >= 0,55.

Salida: `_v306_ligas_seguras.json`.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

RNG = np.random.default_rng(306)


def cargar():
    df = pd.read_csv('pick_ledger.csv', low_memory=False)
    df = df.dropna(subset=['goles_local', 'goles_visit', 'pin_home',
                           'pin_draw', 'pin_away', 'fecha'])
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    df = df.dropna(subset=['fecha']).sort_values('fecha')
    inv = 1 / df[['pin_home', 'pin_draw', 'pin_away']]
    s = inv.sum(axis=1)
    df['f_h'] = inv['pin_home'] / s
    df['f_a'] = inv['pin_away'] / s
    fav_home = df['f_h'] >= df['f_a']
    df['p_fav'] = np.where(fav_home, df['f_h'], df['f_a'])
    gl, gv = df['goles_local'], df['goles_visit']
    df['gana_fav'] = np.where(fav_home, gl > gv, gv > gl).astype(int)
    df['cuota_fav'] = np.where(fav_home, df['cuota_home'], df['cuota_away'])
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    df['tramo'] = np.where(df['fecha'] < corte, 'eleccion', 'juicio')
    return df, corte


def p5(g):
    if len(g) < 30:
        return None
    idx = RNG.integers(0, len(g), size=(2000, len(g)))
    return float(np.percentile(g[idx].mean(axis=1), 5))


def main() -> int:
    df, corte = cargar()
    fav = df[df['p_fav'] >= 0.55]
    ele = fav[fav['tramo'] == 'eleccion']
    jui = fav[fav['tramo'] == 'juicio']
    por = ele.groupby('liga').agg(n=('gana_fav', 'size'),
                                  real=('gana_fav', 'mean'),
                                  esperado=('p_fav', 'mean'))
    por = por[por['n'] >= 60]
    por['exceso'] = por['real'] - por['esperado']
    por = por.sort_values('exceso', ascending=False)
    k = len(por) // 3
    grupos = {'seguras': list(por.index[:k]),
              'medias': list(por.index[k:2 * k]),
              'inciertas': list(por.index[2 * k:])}
    res = {'corte': str(corte.date()), 'ligas_clasificadas': len(por),
           'grupos': grupos, 'eleccion': {}, 'juicio': {},
           'exceso_por_liga': por['exceso'].round(4).to_dict()}
    for tramo, d in (('eleccion', ele), ('juicio', jui)):
        for g, ligas in grupos.items():
            s = d[d['liga'].isin(ligas)]
            ok = s['gana_fav'].to_numpy()
            c = s['cuota_fav'].to_numpy(dtype=float)
            m = ~np.isnan(c)
            gan = np.where(ok[m] == 1, c[m] - 1, -1.0)
            res[tramo][g] = {
                'n': int(len(s)),
                'acierta': round(float(ok.mean()), 4) if len(s) else None,
                'esperado': round(float(s['p_fav'].mean()), 4) if len(s) else None,
                'exceso': round(float(ok.mean() - s['p_fav'].mean()), 4)
                if len(s) else None,
                'roi': round(float(gan.mean()), 4) if len(gan) else None,
                'p5': round(p5(gan), 4) if len(gan) >= 30 else None}
    # ¿la clasificación se sostiene? correlación del exceso entre tramos
    pj = jui.groupby('liga').agg(n=('gana_fav', 'size'),
                                 real=('gana_fav', 'mean'),
                                 esperado=('p_fav', 'mean'))
    pj = pj[pj['n'] >= 30]
    pj['exceso'] = pj['real'] - pj['esperado']
    comun = por.index.intersection(pj.index)
    res['correlacion_exceso'] = round(float(np.corrcoef(
        por.loc[comun, 'exceso'], pj.loc[comun, 'exceso'])[0, 1]), 3)
    res['ligas_en_comun'] = int(len(comun))
    with open('_v306_ligas_seguras.json', 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print('corte', res['corte'], '| ligas', len(por), '| correlación del exceso '
          'entre tramos %.3f (%d ligas)' % (res['correlacion_exceso'],
                                            res['ligas_en_comun']))
    for tramo in ('eleccion', 'juicio'):
        for g in ('seguras', 'medias', 'inciertas'):
            v = res[tramo][g]
            print('%-9s %-9s n=%5d acierta %.1f%% (esperado %.1f%%, exceso %+.1f pp) '
                  'ROI %+.2f%% p5 %s' % (tramo, g, v['n'], 100 * v['acierta'],
                                         100 * v['esperado'], 100 * v['exceso'],
                                         100 * v['roi'], v['p5']))
    print('seguras:', grupos['seguras'][:12])
    print('inciertas:', grupos['inciertas'][:12])
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
