#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v192 - CUANTO CUBREN DE VERDAD LAS CINCO CASAS MEXICANAS DE FLASHSCORE.

El usuario pidio Novibet. Al buscarle una puerta legitima -la suya esta detras
de Cloudflare y no se toca- aparecio el feed publico de comparacion de cuotas
de Flashscore, y con el no una casa sino CINCO, todas mexicanas:

    Calientemx 631 · 1xBet 417 · Winpot 1113 · Novibet 632 · Sportium.mx 1041

El proyecto tiene hoy Pinnacle, Bovada y Playdoit. La dispersion entre casas es
lo unico que este proyecto mide como señal positiva, asi que cinco casas mas
-y mexicanas, o sea precios que el usuario puede tomar de verdad- no es un
adorno.

Esto NO integra nada. Mide: cuantos partidos de cada deporte traen cuota de
cada casa, y con que mercados. Sin ese numero no se sabe si vale la pena.
"""
import io
import sys
import time
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

FEED = 'https://global.flashscore.ninja/2/x/feed/f_%d_%d_3_es-mx_1'
ODDS = 'https://global.ds.lsapp.eu/odds/pq_graphql'
CAB = {'User-Agent': 'Mozilla/5.0 Chrome/120',
       'Referer': 'https://www.flashscore.com.mx/', 'x-fsign': 'SW9D1eZo'}
CASAS = {'Calientemx': 631, '1xBet': 417, 'Winpot': 1113,
         'Novibet': 632, 'Sportium.mx': 1041}
DEPORTES = {1: 'futbol', 2: 'tenis', 3: 'baloncesto',
            5: 'futbol americano', 6: 'beisbol'}
TIPOS = ('HOME_DRAW_AWAY', 'HOME_AWAY', 'OVER_UNDER', 'ASIAN_HANDICAP')
POR_DEPORTE = 12


def main():
    import requests
    ses = requests.Session()
    ses.headers.update(CAB)

    total_pet = 0
    t0 = time.time()
    for sid, nom in DEPORTES.items():
        ids = []
        for dia in (0, 1):
            try:
                t = ses.get(FEED % (sid, dia), timeout=25).text
                ids += [x[:8] for x in t.split('~AA÷')[1:]]
            except Exception as e:
                print('  [%s] feed dia %d: %s' % (nom, dia, str(e)[:40]))
        ids = list(dict.fromkeys(ids))[:POR_DEPORTE]
        if not ids:
            print('%-18s sin partidos' % nom)
            continue

        con = Counter()
        mercados = defaultdict(Counter)
        for mid in ids:
            for casa, bid in CASAS.items():
                visto = False
                for bt in TIPOS:
                    try:
                        r = ses.get(ODDS, params={
                            '_hash': 'ope2', 'eventId': mid,
                            'bookmakerId': bid, 'betType': bt,
                            'betScope': 'FULL_TIME'}, timeout=18).json()
                        total_pet += 1
                    except Exception:
                        continue
                    if (r.get('data') or {}).get('findPrematchOddsForBookmaker'):
                        mercados[casa][bt] += 1
                        visto = True
                if visto:
                    con[casa] += 1

        print('%-18s (%d partidos mirados)' % (nom, len(ids)))
        for casa in CASAS:
            m = mercados[casa]
            print('   %-13s %2d/%2d partidos   %s'
                  % (casa, con[casa], len(ids),
                     ', '.join('%s:%d' % (k[:12], v) for k, v in m.most_common())
                     or '-'))
    print()
    print('%d peticiones en %.1f s (%.2f s por peticion)'
          % (total_pet, time.time() - t0,
             (time.time() - t0) / max(total_pet, 1)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
