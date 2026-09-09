#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
El diccionario equipo -> liga local, construido con DATO, no adivinado.

POR QUE. Para estimar los corners de un Viking FK o un Como en Champions hace
falta su historico de liga local, porque en Champions tienen CERO partidos. Y
para eso hay que saber en que liga juegan. Buscarlo con emparejamiento difuso
contra las 46 ligas es lo que produjo, medido:

    Internazionale -> brasil  Internacional      Juventus -> brasil  Juventude
    Atalanta       -> liga_mx Atlante            Arsenal  -> rus     Arsenal Tula

LA VIA LIMPIA, y no cuesta una sola peticion: `goleadores_cache.json` ya guarda
`teams:<liga>` con los equipos que ESPN publica de cada competicion —47 ligas,
1.069 equipos—. Un equipo pertenece a la liga que lo lista, y punto. No hay que
adivinar nada.

Y desde que la Champions se descarga de ESPN (v179), sus nombres de equipo
salen del MISMO catalogo que esas listas, asi que casan por igualdad y no por
parecido.

Este script mide cuanto cubre ese mapa antes de construir nada encima.
"""
import io
import json
import sys
import unicodedata
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import pandas as pd

CACHE = 'goleadores_cache.json'
CHAMPIONS = 'historico_champions.csv'
# Competiciones que NO son una liga local: un equipo no "pertenece" a ellas.
NO_SON_LIGA = {'champions', 'europa_league', 'conference_league', 'leagues_cup',
               'afc_champions', 'copa_libertadores', 'copa_sudamericana',
               'eng_fa_cup', 'esp_copa_rey', 'bra_copa', 'mundial'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace('.', '').replace('-', ' ')
    return ' '.join(s.split())


def mapa_desde_cache():
    """{nombre normalizado: [ligas que lo listan]} y el nombre tal cual."""
    with io.open(CACHE, encoding='utf-8') as f:
        d = json.load(f)
    por_equipo = defaultdict(list)
    crudo = {}
    for k, v in d.items():
        if not k.startswith('teams:'):
            continue
        liga = k.split(':', 1)[1]
        if liga in NO_SON_LIGA:
            continue
        for eq in ((v or {}).get('data') or []):
            n = norm(eq.get('nombre'))
            if not n:
                continue
            por_equipo[n].append(liga)
            crudo.setdefault(n, eq.get('nombre'))
    return por_equipo, crudo


def main():
    por_equipo, crudo = mapa_desde_cache()
    ligas = {l for ls in por_equipo.values() for l in ls}
    print('mapa desde la cache: %d equipos en %d ligas locales'
          % (len(por_equipo), len(ligas)))
    ambiguos = {e: ls for e, ls in por_equipo.items() if len(set(ls)) > 1}
    print('equipos listados por MAS de una liga: %d' % len(ambiguos))
    for e, ls in list(ambiguos.items())[:8]:
        print('   %-28s %s' % (crudo[e], sorted(set(ls))))

    ch = pd.read_csv(CHAMPIONS)
    equipos_ch = sorted(set(pd.concat([ch['home_team'], ch['away_team']]).dropna()))
    print()
    print('equipos que aparecen en el historico de Champions: %d' % len(equipos_ch))

    casan, faltan = [], []
    for e in equipos_ch:
        ls = sorted(set(por_equipo.get(norm(e), [])))
        (casan if ls else faltan).append((e, ls))
    print('  con liga local identificada: %d (%.0f %%)'
          % (len(casan), 100 * len(casan) / max(len(equipos_ch), 1)))
    print('  sin liga local:              %d' % len(faltan))
    print()
    print('EJEMPLOS DE LOS QUE CASAN (los que antes se inventaban):')
    interes = ('Juventus', 'Internazionale', 'Atalanta', 'Arsenal', 'Lille',
               'Como', 'Viking FK', 'VfB Stuttgart', 'Slovan Bratislava',
               'Bodo/Glimt', 'Barcelona', 'Manchester City', 'Paris Saint-Germain')
    for e, ls in casan:
        if e in interes:
            print('   %-26s -> %s' % (e, ls))
    print()
    print('LOS QUE NO CASAN (su liga no esta en el catalogo, o es de fuera):')
    for e, _ in faltan[:25]:
        print('   ', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
