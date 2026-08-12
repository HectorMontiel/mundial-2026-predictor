#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v126 — Barrido de casas de apuestas: cuáles se pueden integrar de verdad.

Por qué
-------
El consenso es la palanca. Medido el 2026-08-11: de 50 mercados de un partido,
sólo 13 tienen una segunda casa con la que compararse, y por eso la Sección 1
sale vacía. No es falta de valor: es falta de testigos.

Qué hace este script
--------------------
Prueba, una por una, decenas de fuentes de cuotas —APIs públicas de casas,
agregadores, exchanges y feeds de terceros— y para cada una registra:

    responde        si el endpoint devuelve algo
    con_datos       si eso que devuelve contiene cuotas de verdad
    n_eventos       cuántos partidos trae
    formato         json / html / otro
    motivo          por qué falla, cuando falla

No decide nada: deja `sondeo_casas.json` con el resultado para que la
integración se haga con datos y no con intuición.

LO QUE ESTE BARRIDO NO PUEDE HACER
----------------------------------
«Todas las casas del mundo» no es un objetivo alcanzable ni verificable: hay
miles de operadores, la mayoría sin feed público, y muchos sirven sus cuotas
por WebSocket autenticado desde su propio front. Lo que sí es alcanzable, y es
lo que hace esto, es barrer **todas las vías de acceso conocidas**: las APIs de
widget que usan sus propias webs (Altenar, Kambi, Betradar/Sportradar,
Digitain), los agregadores públicos, los exchanges y las APIs de terceros.

Sobre la LEGALIDAD y los términos de uso, que forma parte de lo que se pidió
validar: llamar al mismo endpoint JSON que usa la web pública de un operador es
lo que ya hace el proyecto con Playdoit y no requiere burlar autenticación ni
protección alguna. Rascar HTML detrás de un login, o saltarse un Cloudflare, sí
entra en terreno de términos de uso restrictivos, y por eso esas vías se
registran como tales y NO se integran sin decidirlo expresamente.

Uso:  python sondeo_casas.py            # barrido completo
      python sondeo_casas.py --json     # además escribe sondeo_casas.json
"""
import json
import os
import sys
import time
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import requests

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0 Safari/537.36'),
      'Accept': 'application/json, text/plain, */*'}
TIMEOUT = 20
ARCHIVO = 'sondeo_casas.json'

# ---------------------------------------------------------------------------
# LAS CANDIDATAS
#
# Agrupadas por PLATAFORMA, que es lo que de verdad decide si se puede
# integrar: dos casas sobre el mismo motor (Altenar, Kambi…) comparten formato,
# así que integrar la segunda cuesta casi nada — pero también significa que sus
# cuotas están CORRELACIONADAS y valen menos como testigo independiente. Es la
# razón por la que el proyecto tiene prohibido añadir dos marcas de Kambi.
# ---------------------------------------------------------------------------
CANDIDATAS: List[Dict] = [
    # --- plataforma Altenar (la que ya usa Playdoit) -----------------------
    {'casa': 'Playdoit', 'plataforma': 'Altenar', 'estado': 'integrada',
     'url': 'https://sb2frontend-altenar2.biahosted.com/api/widget/GetEvents',
     'params': {'culture': 'es-ES', 'timezoneOffset': '360',
                'integration': 'playdoit2', 'deviceType': '1',
                'numFormat': 'en-GB', 'countryCode': 'MX', 'sportid': 66,
                'categoryids': '', 'champids': '', 'group': 'AllEvents',
                'period': 'periodall'}},
    {'casa': 'Betano (Altenar)', 'plataforma': 'Altenar', 'estado': 'candidata',
     'url': 'https://sb2frontend-altenar2.biahosted.com/api/widget/GetEvents',
     'params': {'culture': 'es-ES', 'timezoneOffset': '0',
                'integration': 'betano', 'deviceType': '1',
                'numFormat': 'en-GB', 'countryCode': 'MX', 'sportid': 66,
                'categoryids': '', 'champids': '', 'group': 'AllEvents',
                'period': 'periodall'}},
    {'casa': 'Strendus (Altenar)', 'plataforma': 'Altenar',
     'estado': 'candidata',
     'url': 'https://sb2frontend-altenar2.biahosted.com/api/widget/GetEvents',
     'params': {'culture': 'es-ES', 'timezoneOffset': '360',
                'integration': 'strendus', 'deviceType': '1',
                'numFormat': 'en-GB', 'countryCode': 'MX', 'sportid': 66,
                'categoryids': '', 'champids': '', 'group': 'AllEvents',
                'period': 'periodall'}},
    {'casa': 'Codere (Altenar)', 'plataforma': 'Altenar', 'estado': 'candidata',
     'url': 'https://sb2frontend-altenar2.biahosted.com/api/widget/GetEvents',
     'params': {'culture': 'es-ES', 'timezoneOffset': '360',
                'integration': 'codere', 'deviceType': '1',
                'numFormat': 'en-GB', 'countryCode': 'MX', 'sportid': 66,
                'categoryids': '', 'champids': '', 'group': 'AllEvents',
                'period': 'periodall'}},

    # --- exchanges ---------------------------------------------------------
    {'casa': 'Matchbook', 'plataforma': 'exchange', 'estado': 'integrada',
     'url': 'https://www.matchbook.com/edge/rest/events',
     'params': {'sport-ids': 15, 'states': 'open', 'include-prices': 'true',
                'price-depth': 3, 'odds-type': 'DECIMAL',
                'exchange-type': 'back-lay', 'currency': 'EUR', 'per-page': 20}},
    {'casa': 'Smarkets', 'plataforma': 'exchange', 'estado': 'candidata',
     'url': 'https://api.smarkets.com/v3/events/',
     'params': {'type': 'ODDS', 'state': 'new,upcoming', 'limit': 20}},
    {'casa': 'Betfair (público)', 'plataforma': 'exchange',
     'estado': 'candidata',
     'url': 'https://ero.betfair.com/www/sports/exchange/readonly/v1/bymarket',
     'params': {'marketIds': '1.1', 'currencyCode': 'EUR', 'locale': 'es',
                'alt': 'json'}},
    {'casa': 'Polymarket', 'plataforma': 'prediction market',
     'estado': 'descartada v114',
     'url': 'https://gamma-api.polymarket.com/events',
     'params': {'limit': 20, 'closed': 'false', 'tag': 'sports'}},
    {'casa': 'Kalshi', 'plataforma': 'prediction market',
     'estado': 'descartada v114',
     'url': 'https://api.elections.kalshi.com/trade-api/v2/markets',
     'params': {'limit': 20, 'status': 'open'}},

    # --- casas con API propia ---------------------------------------------
    {'casa': 'Pinnacle', 'plataforma': 'propia', 'estado': 'integrada',
     'url': 'https://guest.api.arcadia.pinnacle.com/0.1/sports/29/matchups',
     'params': {}, 'headers': {'X-API-Key': 'CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R'}},
    {'casa': 'Bovada', 'plataforma': 'propia', 'estado': 'integrada',
     'url': ('https://www.bovada.lv/services/sports/event/coupon/events/A/'
             'description/soccer'),
     'params': {'marketFilterId': 'def', 'preMatchOnly': 'true', 'lang': 'en'}},
    {'casa': 'Unibet (Kambi)', 'plataforma': 'Kambi', 'estado': 'integrada',
     'url': ('https://eu-offering-api.kambicdn.com/offering/v2018/ub/'
             'listView/football.json'),
     'params': {'lang': 'en_GB', 'market': 'GB', 'useCombined': 'true'}},
    {'casa': '888sport (Kambi)', 'plataforma': 'Kambi',
     'estado': 'prohibida (2 marcas Kambi)',
     'url': ('https://eu-offering-api.kambicdn.com/offering/v2018/888/'
             'listView/football.json'),
     'params': {'lang': 'en_GB', 'market': 'GB', 'useCombined': 'true'}},
    {'casa': 'Betsson (Kambi)', 'plataforma': 'Kambi',
     'estado': 'prohibida (2 marcas Kambi)',
     'url': ('https://eu-offering-api.kambicdn.com/offering/v2018/betsson/'
             'listView/football.json'),
     'params': {'lang': 'en_GB', 'market': 'GB', 'useCombined': 'true'}},
    {'casa': 'DraftKings (ESPN core)', 'plataforma': 'ESPN',
     'estado': 'integrada v126',
     'url': ('https://sports.core.api.espn.com/v2/sports/soccer/leagues/'
             'mex.1/events'),
     'params': {'limit': 5}},
    {'casa': 'DraftKings (directa)', 'plataforma': 'propia',
     'estado': 'candidata',
     'url': ('https://sportsbook-nash.draftkings.com/api/sportscontent/'
             'dkusoh/v1/leagues/40253'),
     'params': {}},
    {'casa': 'FanDuel', 'plataforma': 'propia', 'estado': 'candidata',
     'url': ('https://sbapi.nj.sportsbook.fanduel.com/api/content-managed-page'),
     'params': {'page': 'CUSTOM', 'customPageId': 'soccer', '_ak': 'FhMFpcPWXMeyZxOx'}},
    {'casa': 'Betway', 'plataforma': 'propia', 'estado': 'candidata',
     'url': 'https://sports.betway.com/api/Events/v2/GetEvents',
     'params': {}},
    {'casa': 'Betsson MX (Digitain)', 'plataforma': 'Digitain',
     'estado': 'candidata',
     'url': 'https://sb1client-api.digitain.com/api/v2/PreMatch/GetSports',
     'params': {'languageId': 2, 'partnerId': 1}},
    {'casa': 'Caliente MX', 'plataforma': 'propia', 'estado': 'candidata',
     'url': 'https://sportsbook-api.caliente.mx/api/v1/events',
     'params': {'sport': 'soccer'}},
    {'casa': 'Rushbet (Kambi)', 'plataforma': 'Kambi',
     'estado': 'descartada v76 (429)',
     'url': ('https://eu-offering-api.kambicdn.com/offering/v2018/rushbetco/'
             'listView/football.json'),
     'params': {'lang': 'es_CO', 'market': 'CO'}},
    {'casa': '1xBet', 'plataforma': 'propia', 'estado': 'candidata',
     'url': 'https://1xbet.com/LineFeed/Get1x2_VZip',
     'params': {'sports': 1, 'count': 20, 'lng': 'es', 'mode': 4}},
    {'casa': 'Betcris MX', 'plataforma': 'propia', 'estado': 'candidata',
     'url': 'https://www.betcris.mx/api/sportsbook/events',
     'params': {'sport': 'soccer'}},

    # --- agregadores y feeds de terceros -----------------------------------
    {'casa': 'The Odds API (demo)', 'plataforma': 'agregador de pago',
     'estado': 'candidata',
     'url': 'https://api.the-odds-api.com/v4/sports',
     'params': {'apiKey': 'DEMO'}},
    {'casa': 'OddsPortal', 'plataforma': 'agregador HTML',
     'estado': 'candidata',
     'url': 'https://www.oddsportal.com/matches/soccer/', 'params': {}},
    {'casa': 'football-data.co.uk', 'plataforma': 'histórico CSV',
     'estado': 'integrada (histórico)',
     'url': 'https://www.football-data.co.uk/mmz4281/2526/E0.csv',
     'params': {}},
    {'casa': 'FlashScore / LiveScore', 'plataforma': 'agregador HTML',
     'estado': 'candidata',
     'url': 'https://www.flashscore.com/football/', 'params': {}},
]


def probar(c: Dict) -> Dict:
    """Un intento contra una fuente, con el resultado en claro."""
    r = {'casa': c['casa'], 'plataforma': c['plataforma'],
         'estado_previo': c['estado'], 'url': c['url'],
         'responde': False, 'con_datos': False, 'n_eventos': 0,
         'formato': None, 'http': None, 'motivo': ''}
    cab = dict(UA)
    cab.update(c.get('headers') or {})
    try:
        resp = requests.get(c['url'], params=c.get('params') or {},
                            headers=cab, timeout=TIMEOUT)
        r['http'] = resp.status_code
        if resp.status_code != 200:
            r['motivo'] = f'HTTP {resp.status_code}'
            return r
        r['responde'] = True
        texto = resp.text or ''
        ct = (resp.headers.get('Content-Type') or '').lower()
        if 'json' in ct or texto.strip()[:1] in '[{':
            r['formato'] = 'json'
            try:
                j = resp.json()
            except Exception:
                r['motivo'] = 'responde 200 pero el JSON no se puede leer'
                return r
            # cuántos eventos, buscando las claves habituales
            n = 0
            if isinstance(j, list):
                n = len(j)
            elif isinstance(j, dict):
                for k in ('events', 'Events', 'matchups', 'data', 'items',
                          'markets', 'sports', 'Value', 'results'):
                    v = j.get(k)
                    if isinstance(v, list):
                        n = max(n, len(v))
            r['n_eventos'] = n
            # ¿hay algo que parezca una cuota?
            crudo = texto[:400000].lower()
            señales = ('price', 'odds', 'cuota', 'oddsdecimal', 'decimal',
                       'homeodds', 'back', '"c":')
            r['con_datos'] = n > 0 and any(s in crudo for s in señales)
            if not r['con_datos']:
                r['motivo'] = ('responde pero sin cuotas reconocibles'
                               if n else 'responde pero sin eventos')
        elif 'html' in ct or texto.lstrip()[:1] == '<':
            r['formato'] = 'html'
            r['motivo'] = ('devuelve HTML: haría falta scraping del front, '
                           'con el riesgo de términos de uso y de romperse '
                           'en cada rediseño')
        elif 'csv' in ct or ',' in texto[:200]:
            r['formato'] = 'csv'
            r['n_eventos'] = max(texto.count('\n') - 1, 0)
            r['con_datos'] = 'B365' in texto or 'PSH' in texto or 'AvgH' in texto
            if not r['con_datos']:
                r['motivo'] = 'CSV sin columnas de cuota reconocibles'
        else:
            r['formato'] = ct or 'desconocido'
            r['motivo'] = 'formato no reconocido'
    except requests.exceptions.SSLError:
        r['motivo'] = 'error de certificado TLS'
    except requests.exceptions.ConnectionError:
        r['motivo'] = 'no resuelve o rechaza la conexión'
    except requests.exceptions.Timeout:
        r['motivo'] = f'sin respuesta en {TIMEOUT} s'
    except Exception as e:
        r['motivo'] = f'{type(e).__name__}: {e}'
    return r


def main() -> int:
    print(f'Sondeando {len(CANDIDATAS)} fuentes de cuotas…\n')
    res = []
    for c in CANDIDATAS:
        r = probar(c)
        res.append(r)
        marca = ('✅' if r['con_datos'] else
                 '🟡' if r['responde'] else '❌')
        print(f"{marca} {r['casa']:26} {str(r['plataforma'])[:16]:16} "
              f"http={str(r['http']):4} ev={r['n_eventos']:5} "
              f"{r['motivo'][:52]}")
        time.sleep(0.4)          # sin prisa: no se trata de castigar a nadie

    viables = [r for r in res if r['con_datos']]
    print()
    print('=' * 96)
    print(f'CON CUOTAS UTILIZABLES: {len(viables)} de {len(res)}')
    for r in viables:
        print(f"   {r['casa']:26} {r['plataforma']:18} "
              f"{r['n_eventos']:5} eventos · {r['estado_previo']}")

    nuevas = [r for r in viables
              if 'integrada' not in r['estado_previo']
              and 'prohibida' not in r['estado_previo']]
    print()
    print(f'NUEVAS CANDIDATAS A INTEGRAR: {len(nuevas)}')
    for r in nuevas:
        print(f"   {r['casa']:26} {r['plataforma']:18} "
              f"{r['n_eventos']:5} eventos")
    if not nuevas:
        print('   Ninguna fuente nueva devuelve cuotas utilizables hoy.')

    if '--json' in sys.argv:
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump({'sondeadas': len(res), 'viables': len(viables),
                       'nuevas': len(nuevas), 'resultados': res},
                      f, ensure_ascii=False, indent=1)
        print(f'\n{ARCHIVO} escrito.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
