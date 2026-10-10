#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v357 — Patrones de la literatura y de los tipsters, contra nuestras «se mete».

El usuario: «analiza más patrones, investiga en internet, artículos
científicos, tipsters…: qué otro patrón podemos seguir para tener más verdes o
menos rojas». Lo que dice la investigación (búsqueda del 9-oct):

  · sesgo favorito-sorpresa: el favorito gana algo más de lo que dice el precio
  · «racha caliente»: el mercado sobrevalora a los equipos en racha
  · la casa infravalora la ventaja del local
  · los «menos» rinden más que los «más», sobre todo con línea alta
  · calendario apretado: menos ataque, mejor defensa en casa (menos goles)
  · liga principal / secundaria (en las chicas el precio es peor)

Para cada partido de la réplica de la tarjeta (`_v356_candidatas.csv.gz`, 889
partidos 19-sep → 9-oct) se calculan, sólo con lo jugado ANTES ese día:
racha del favorito (victorias seguidas), días de descanso de cada equipo,
favorito local o visitante. Y se mira el acierto de las «se mete» de cada
grupo en las dos mitades de días, con bootstrap de la diferencia contra el
resto. Un patrón vale si va en el mismo sentido en las dos mitades y el p5 de
la diferencia es > 0.
"""
import glob
import json
import sys

import numpy as np
import pandas as pd

import _v344_precio as P
import _v356_anticipar as A
import modo_modelo as mm

rng = np.random.default_rng(357)


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
        d['date'] = d.date.astype(str).str[:10]
        out[liga] = d.sort_values('date')
    return out


def _equipo(H, eq, dia):
    g = H[((H.h == eq) | (H.a == eq)) & (H.date < dia)].tail(6)
    if g.empty:
        return np.nan, np.nan
    descanso = (pd.Timestamp(dia) - pd.Timestamp(g.date.iloc[-1])).days
    racha = 0
    for r in g.iloc[::-1].itertuples():
        gano = (r.home_goals > r.away_goals) if r.h == eq else (r.away_goals > r.home_goals)
        if gano:
            racha += 1
        else:
            break
    return descanso, racha


def rasgos(d):
    hist = historicos()
    filas = []
    for (par, liga, dia), g in d.groupby(['partido', 'liga', 'dia']):
        if ' vs ' not in str(par) or liga not in hist:
            continue
        h, a = (P._norm(x.strip()) for x in par.split(' vs ', 1))
        dh, rh = _equipo(hist[liga], h, dia)
        da, ra = _equipo(hist[liga], a, dia)
        fav = g.fav.iloc[0] if 'fav' in g else np.nan
        filas.append({'partido': par, 'desc_h': dh, 'desc_a': da, 'racha_h': rh, 'racha_a': ra,
                      'principal': str(liga) in mm.PRINCIPALES})
    return pd.DataFrame(filas)


def boot(a, b, n=2000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 15 or len(b) < 15:
        return None
    ds = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean()
          for _ in range(n)]
    return round(float(np.mean(ds)), 4), round(float(np.percentile(ds, 5)), 4), round(float(np.percentile(ds, 95)), 4)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = A.cargar()
    try:
        ra = pd.read_csv('_v357_rasgos.csv')
    except Exception:
        ra = rasgos(d)
        ra.to_csv('_v357_rasgos.csv', index=False)
    m = d[d.metida].merge(ra, on='partido', how='left')
    # el lado favorito y su racha / descanso
    m['p_local'] = m.fav  # `fav` = prob del favorito (0-1); el lado se infiere abajo
    m['tipo'] = np.select([m.apuesta.str.startswith('Goles: Más'), m.apuesta.str.startswith('Goles: Menos'),
                           m.apuesta.str.contains(' o empate'), m.mercado.eq('1X2')],
                          ['mas', 'menos', 'dc', 'ganador'], 'otro')
    racha_max = np.fmax(m.racha_h, m.racha_a)
    descanso_min = np.fmin(m.desc_h, m.desc_a)
    grupos = {
        'favorito/equipo en racha de 3+ victorias': racha_max >= 3,
        'algún equipo con ≤ 3 días de descanso': descanso_min <= 3,
        'los dos con ≥ 7 días de descanso': (m.desc_h >= 7) & (m.desc_a >= 7),
        'liga principal': m.principal == True,
        '«menos» de goles': m.tipo == 'menos',
        '«más» de goles': m.tipo == 'mas',
        '«menos» con línea alta (≥ 3,5)': (m.tipo == 'menos') & m.apuesta.str.contains(r'[3-9]\.5'),
        'doble oportunidad': m.tipo == 'dc',
        'cuota ≤ 1,18': m.cuota <= 1.18,
        'cuota ≥ 1,28': m.cuota >= 1.28,
        'favorito muy claro (≥ 70 %)': m.fav >= 0.70,
        'partido parejo (favorito < 50 %)': m.fav < 0.50,
    }
    out = {'apuestas': int(len(m)), 'grupos': {}}
    print('%-42s %-22s %-22s %s' % ('grupo', 'elige (n, acierto)', 'juzga (n, acierto)', 'dif juzga (media, p5, p95)'))
    for nombre, f in grupos.items():
        f = f.fillna(False)
        r = {}
        for tr in ('elige', 'juzga'):
            x, y = m[f & (m.tramo == tr)], m[~f & (m.tramo == tr)]
            r[tr] = {'n': int(len(x)), 'acierto': round(float(x.acierto.mean()), 3) if len(x) else None,
                     'resto': round(float(y.acierto.mean()), 3) if len(y) else None,
                     'dif': boot(x.acierto, y.acierto)}
        out['grupos'][nombre] = r
        print('%-42s %-22s %-22s %s' % (nombre, (r['elige']['n'], r['elige']['acierto'], r['elige']['resto']),
                                         (r['juzga']['n'], r['juzga']['acierto'], r['juzga']['resto']),
                                         r['juzga']['dif']))
    pasan = [k for k, v in out['grupos'].items()
             if v['elige']['dif'] and v['juzga']['dif']
             and ((v['elige']['dif'][1] > 0 and v['juzga']['dif'][1] > 0)
                  or (v['elige']['dif'][2] < 0 and v['juzga']['dif'][2] < 0))]
    out['pasan'] = pasan
    print('\nPATRONES QUE PASAN (mismo sentido y p5/p95 fuera del 0 en las dos mitades):', pasan)
    json.dump(out, open('_v357_patrones.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
