#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
El puente Champions <-> liga local, medido: cuanto cambia cada estadistica.

POR QUE HACE FALTA. Con el historico de la Champions ya con estadisticas
observadas (774 partidos), la muestra POR EQUIPO sigue siendo corta:

    mediana 16 partidos · 37 % de los equipos por debajo de 10
    Viking FK 0 · Sabah FK 0 · Como 0 · Stuttgart 8 · Slovan Bratislava 8
    Barcelona 48 · PSG 66 · Bayern 63

O sea que para media parrilla no hay con que estimar nada, y para la otra media
hay poco. Lo que si hay es su liga local: el Barcelona tiene cientos de partidos
de LaLiga con corners reales.

LO QUE ESTE SCRIPT MIDE, y es lo unico que permite usar ese dato sin mentir:
**el factor de competicion**. Un equipo no hace los mismos corners en Champions
que en su liga, y la diferencia no es la misma para todos: depende del nivel de
la liga de la que viene. Se mide sobre los equipos que tienen las dos cosas.

    factor_equipo = media_en_champions / media_en_su_liga

Se agrega por nivel de liga y se comprueba si la dispersion justifica tratar a
las ligas por separado o basta un factor unico.

No cambia nada del producto: sirve para decidir con numeros como se mezcla.
"""
import io
import os
import sys
import unicodedata

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

import config

CHAMPIONS = 'historico_champions.csv'
# Estadisticas que interesan y su columna local/visitante.
STATS = ('corners', 'yellow', 'shots_on', 'shots_off')
MIN_CHAMPIONS = 6          # partidos minimos en Champions para medir el factor
MIN_LIGA = 20              # y en su liga


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().replace('.', '').replace('-', ' ').split())


def perfil(df, stats):
    """Media por equipo y estadistica, juntando local y visitante."""
    filas = []
    for lado, otro in (('home', 'away'), ('away', 'home')):
        cols = {'equipo': df['%s_team' % lado]}
        for s in stats:
            c = '%s_%s' % (lado, s)
            if c in df.columns:
                cols[s] = df[c]
        filas.append(pd.DataFrame(cols))
    todo = pd.concat(filas, ignore_index=True)
    todo['equipo'] = todo['equipo'].map(norm)   # se remapea fuera con name_mapper
    g = todo.groupby('equipo')
    out = g.mean(numeric_only=True)
    out['n'] = g.size()
    return out


def ligas_locales():
    """{clave: DataFrame} de las ligas con estadisticas observadas."""
    import rendimiento_equipos as rq
    fuera = {'champions', 'europa_league', 'conference_league', 'leagues_cup'}
    salida = {}
    for clave in config.LEAGUES:
        if clave in fuera:
            continue
        ruta = 'historico_%s.csv' % clave
        if not os.path.exists(ruta):
            continue
        try:
            d = rq.stats_disponibles(clave)
        except Exception:
            continue
        if not (d.get('corners') and d.get('tarjetas')):
            continue
        try:
            df = pd.read_csv(ruta)
        except Exception:
            continue
        if 'stats_origen' in df.columns:      # solo filas observadas
            df = df[df['stats_origen'].notna()]
        if len(df) < 100:
            continue
        salida[clave] = df
    return salida


def main():
    ch = pd.read_csv(CHAMPIONS)
    ch = ch[ch['stats_origen'] == 'espn'] if 'stats_origen' in ch.columns else ch
    pch = perfil(ch, STATS)
    print('Champions: %d partidos observados · %d equipos'
          % (len(ch), len(pch)))

    ligas = ligas_locales()
    print('ligas locales con corners y tarjetas observados: %d' % len(ligas))

    filas = []
    for clave, df in ligas.items():
        pl = perfil(df, STATS)
        comunes = pch.index.intersection(pl.index)
        for eq in comunes:
            if pch.loc[eq, 'n'] < MIN_CHAMPIONS or pl.loc[eq, 'n'] < MIN_LIGA:
                continue
            fila = {'equipo': eq, 'liga': clave,
                    'n_ch': int(pch.loc[eq, 'n']), 'n_liga': int(pl.loc[eq, 'n'])}
            for s in STATS:
                if s in pch.columns and s in pl.columns:
                    a, b = pch.loc[eq, s], pl.loc[eq, s]
                    fila['ch_' + s] = a
                    fila['lg_' + s] = b
                    fila['f_' + s] = (a / b) if b and b == b and b > 0 else np.nan
            filas.append(fila)

    d = pd.DataFrame(filas)
    if d.empty:
        print('sin equipos emparejados: revisar los nombres')
        return 1
    print('equipos emparejados Champions <-> liga local: %d en %d ligas'
          % (len(d), d['liga'].nunique()))
    print()
    print('FACTOR DE COMPETICION (Champions / liga local), por estadistica')
    print('%-12s %8s %8s %8s %8s' % ('', 'mediana', 'media', 'p25', 'p75'))
    for s in STATS:
        c = 'f_' + s
        if c not in d.columns:
            continue
        v = d[c].dropna()
        if v.empty:
            continue
        print('%-12s %8.3f %8.3f %8.3f %8.3f'
              % (s, v.median(), v.mean(), v.quantile(.25), v.quantile(.75)))

    print()
    print('POR LIGA DE ORIGEN (mediana del factor; n = equipos)')
    print('%-20s %4s %8s %8s %8s %8s'
          % ('liga', 'n', 'corners', 'yellow', 'shots_on', 'shots_off'))
    orden = d.groupby('liga').size().sort_values(ascending=False)
    for clave in orden.index:
        sub = d[d['liga'] == clave]
        if len(sub) < 3:
            continue
        vals = []
        for s in STATS:
            c = 'f_' + s
            vals.append(sub[c].median() if c in sub.columns else np.nan)
        print('%-20s %4d %8.3f %8.3f %8.3f %8.3f'
              % (config.LEAGUES.get(clave, {}).get('nombre', clave)[:20],
                 len(sub), *vals))

    print()
    print('LO QUE DECIDE SI HACE FALTA SEPARAR POR LIGA:')
    for s in STATS:
        c = 'f_' + s
        if c not in d.columns:
            continue
        por_liga = d.groupby('liga')[c].median().dropna()
        por_liga = por_liga[d.groupby('liga').size() >= 3]
        if len(por_liga) < 3:
            continue
        print('  %-10s dispersion entre ligas: sd %.3f  (rango %.3f - %.3f)  '
              'dispersion entre equipos: sd %.3f'
              % (s, por_liga.std(), por_liga.min(), por_liga.max(),
                 d[c].std()))
    d.to_csv('_v179_champions_vs_liga.csv', index=False)
    print()
    print('detalle en _v179_champions_vs_liga.csv')
    return 0


if __name__ == '__main__':
    sys.exit(main())
