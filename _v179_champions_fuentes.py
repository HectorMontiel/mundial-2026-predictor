#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuanto aporta cada fuente al historico de la Champions, y cuanto se solapan.

EL PROBLEMA MEDIDO: `historico_champions.csv` no se toca desde el 2026-07-14.
Es la unica competicion UEFA con `formato: api_football` —sus hermanas Europa
League y Conference League usan `espn`— y es la unica de las tres SIN
`stats_origen`, o sea sin una sola estadistica real: sus corners, tarjetas y
remates son los que inventa el generador sintetico.

    champions          api_football   hasta 2026-07-14   stats_origen NO
    europa_league      espn           hasta 2026-05-20   stats_origen SI
    conference_league  espn           hasta 2026-05-27   stats_origen SI

ESPN si esta al dia (llega a ayer, con la temporada nueva dentro) pero trae
menos historico. Antes de cambiar la fuente hay que saber cuanto se perderia,
y si los nombres de equipo de las dos fuentes son emparejables.
"""
import io
import sys
import unicodedata

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import pandas as pd


def norm(s):
    """Nombre comparable entre fuentes: sin acentos, sin puntuacion, minusculas."""
    s = str(s or '')
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    for basura in ('.', '-', "'", '  '):
        s = s.replace(basura, ' ' if basura == '-' else '')
    return ' '.join(s.lower().split())


def clave(d):
    return set(zip(d['date'].dt.strftime('%Y-%m-%d'),
                   d['home_team'].map(norm), d['away_team'].map(norm)))


def main():
    viejo = pd.read_csv('historico_champions.csv')
    viejo['date'] = pd.to_datetime(viejo['date'], errors='coerce')
    espn = pd.read_csv('_v179_champions_espn.csv')
    espn['date'] = pd.to_datetime(espn['date'], errors='coerce')

    print('api_football (en el repo) : %4d partidos  %s -> %s'
          % (len(viejo), str(viejo['date'].min())[:10], str(viejo['date'].max())[:10]))
    print('ESPN (descargado ahora)   : %4d partidos  %s -> %s'
          % (len(espn), str(espn['date'].min())[:10], str(espn['date'].max())[:10]))

    kv, ke = clave(viejo), clave(espn)
    print()
    print('solo en api_football : %4d' % len(kv - ke))
    print('solo en ESPN         : %4d' % len(ke - kv))
    print('en las dos           : %4d' % len(kv & ke))
    print('union                : %4d' % len(kv | ke))

    # Lo que ESPN aporta y el repo no tiene: la temporada nueva.
    nuevos = espn[[k not in kv for k in zip(
        espn['date'].dt.strftime('%Y-%m-%d'),
        espn['home_team'].map(norm), espn['away_team'].map(norm))]]
    recientes = nuevos[nuevos['date'] >= '2026-08-01']
    print()
    print('partidos de ESPN posteriores al 2026-08-01 que faltan en el repo: %d'
          % len(recientes))
    for _, f in recientes.sort_values('date').tail(12).iterrows():
        print('   %s  %-24s %-24s %s-%s'
              % (str(f['date'])[:10], f['home_team'], f['away_team'],
                 f['home_goals'], f['away_goals']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
