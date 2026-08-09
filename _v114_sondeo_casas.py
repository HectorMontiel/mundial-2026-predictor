#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — Sondeo de casas y de MERCADOS DE PREDICCIÓN, tras el 403 de Betfair.

Por qué existe este sondeo
--------------------------
La v113 dejó la prioridad clara: el edge medido del proyecto está en el
PRECIO, no en el modelo, y con las cinco casas actuales el margen es 1,0574 y
hay CERO arbitrajes. Betfair Exchange era la pieza que faltaba (da el mejor
precio el 35,4 % de las veces sobre el histórico de football-data).

Betfair está **cerrado desde México**: bloquea por geolocalización de red, no
por scraping («Betfair does not accept bets from a country…», IP mexicana).
Eso no se arregla con cabeceras, y la API oficial exige cuenta, que exige
residencia admitida. Hay que buscar el mismo efecto —precio sin margen de
casa— por otra vía.

Este sondeo cubre tres familias:

  A) EXCHANGES Y MERCADOS DE PREDICCIÓN — el sustituto conceptual de Betfair.
     Polymarket y Kalshi cotizan deporte con libro de órdenes, sin margen de
     casa, y publican API de lectura sin clave. Si cubren los partidos que
     apostamos, son el mejor precio por construcción.

  B) AGREGADORES — una petición que devuelve N casas a la vez. Es line
     shopping sin integrar N casas.

  C) CASAS DIRECTAS accesibles desde México, y OTRAS INTEGRACIONES DE ALTENAR
     (la v76 probó unos nombres de integración y dieron 400; se prueban más,
     porque el nombre no es adivinable y un 400 sólo dice «ese no es»).

Qué se comprueba, por candidata
-------------------------------
  · robots.txt no lo prohíbe,
  · el endpoint responde 200,
  · el cuerpo es JSON parseable,
  · y dentro hay algo con forma de cuota decimal o americana.

REGLA HEREDADA DE LA v111, NO NEGOCIABLE: una casa nueva sólo entra si sus
precios son SUYOS. Kambi demostró que varias marcas comparten motor (248/272
precios idénticos) y añadirlas fabricaría dispersión falsa. Este script sólo
descubre; la correlación de precios se mide aparte antes de integrar.

    python _v114_sondeo_casas.py
"""
import json
import sys
import time
from urllib.parse import urlparse

import requests

# La consola de Windows llega en cp1252 y los emojis del informe la revientan
# con UnicodeEncodeError antes de imprimir el primer resultado. Se fuerza UTF-8
# en la salida, que es lo que el resto de scripts del proyecto ya hace.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0 Safari/537.36'),
      'Accept': 'application/json, text/plain, */*'}

ALTENAR = 'https://sb2frontend-altenar2.biahosted.com/api/widget/GetEvents'

# (nombre, url, params, familia, nota)
CANDIDATAS = [
    # --- A) exchanges y mercados de predicción ----------------------------
    ('Polymarket-gamma', 'https://gamma-api.polymarket.com/markets',
     {'closed': 'false', 'limit': '20', 'order': 'volumeNum', 'ascending': 'false'},
     'exchange', 'libro de órdenes, sin margen de casa'),
    ('Polymarket-clob', 'https://clob.polymarket.com/sampling-markets', None,
     'exchange', 'precios del CLOB'),
    ('Kalshi', 'https://api.elections.kalshi.com/trade-api/v2/markets',
     {'limit': '20', 'status': 'open'}, 'exchange',
     'mercado regulado, lectura sin clave'),
    ('Matchbook', 'https://www.matchbook.com/edge/rest/events',
     {'sport-ids': '15', 'per-page': '20'}, 'exchange', 'v76: 403 de Cloudflare'),
    ('Smarkets', 'https://api.smarkets.com/v3/events/', {'type': 'ODDS'},
     'exchange', 'v71/v76: 403'),
    ('ProphetX', 'https://api.prophetx.co/partner/v2/sports', None,
     'exchange', 'exchange de EE. UU.'),

    # --- B) agregadores ----------------------------------------------------
    ('Oddspedia', 'https://oddspedia.com/api/v1/getMatchList',
     {'excludeSpecialStatus': '0', 'sortBy': 'default', 'sport': 'football',
      'popularLeaguesOnly': '0', 'inplay': '0', 'language': 'en',
      'geoCode': 'MX'}, 'agregador', 'agrega ~70 casas'),
    ('Oddspedia-odds', 'https://oddspedia.com/api/v1/getMatchOdds',
     {'geoCode': 'MX', 'bookmakerGeoCode': 'MX', 'language': 'en',
      'matchId': '1'}, 'agregador', 'precios por partido'),
    ('BetExplorer', 'https://www.betexplorer.com/next/soccer/', None,
     'agregador', 'ya usado en backfill; se comprueba estado'),
    ('OddsAPI-free', 'https://api.the-odds-api.com/v4/sports', {'apiKey': 'x'},
     'agregador', 'control: debe dar 401'),

    # --- C) casas directas accesibles desde México -------------------------
    ('1xBet-LineFeed', 'https://1xbet.mx/LineFeed/Get1x2_VZip',
     {'sports': '1', 'count': '20', 'lng': 'en', 'mode': '4', 'country': '113',
      'partner': '51', 'getEmpty': 'true'}, 'casa', 'v76: 404 (API cambió)'),
    ('1xBet-com', 'https://1xbet.com/LineFeed/Get1x2_VZip',
     {'sports': '1', 'count': '20', 'lng': 'en', 'mode': '4', 'country': '113',
      'partner': '51', 'getEmpty': 'true'}, 'casa', 'dominio internacional'),
    ('Betano-MX', 'https://www.betano.mx/api/sportsbook/v1/sport/soccer', None,
     'casa', 'Kaizen Gaming'),
    ('Betano-feed', 'https://www.betano.mx/api/feed/sport/soccer', None,
     'casa', 'Kaizen, otra ruta'),
    ('Caliente-sb', 'https://sportsapi.caliente.mx/api/sportsbook/events', None,
     'casa', 'la casa más grande de México'),
    ('Caliente-web', 'https://www.caliente.mx/api/sportsbook/v1/events', None,
     'casa', 'ruta alternativa'),
    ('Betcris-MX', 'https://www.betcris.mx/api/sportsbook/events', None,
     'casa', 'v76: 404 en su ruta'),
    ('Novibet-MX', 'https://www.novibet.mx/api/sportsbook/betting/events', None,
     'casa', 'motor propio'),
    ('Betsson-MX', 'https://www.betsson.mx/api/sb/v1/sports', None,
     'casa', 'v71: descartada, se reintenta'),
    ('Coolbet', 'https://www.coolbet.com/api/sb/v2/configurations/sports', None,
     'casa', 'v111: pendiente'),
    ('Betclic-CDN', 'https://offer.cdn.begmedia.com/api/pub/v4/sports/1',
     {'application': '2048', 'countrycode': 'fr', 'language': 'fr',
      'sitecode': 'frfr'}, 'casa', 'CDN público'),
    ('Marathonbet', 'https://www.marathonbet.com/en/betting/Football+-+26420',
     None, 'casa', 'v71: descartada, se reintenta'),
    ('Betway', 'https://sports.betway.com/api/Events/v2/GetEvents', None,
     'casa', 'motor propio'),
    ('Stake', 'https://stake.com/_api/sportsbook/v1/sports', None,
     'casa', 'GraphQL, poco probable'),
    ('Cloudbet', 'https://sports-api.cloudbet.com/pub/v2/odds/sports', None,
     'casa', 'API documentada, exige clave'),
    ('Pinnacle-control', 'https://guest.api.arcadia.pinnacle.com/0.1/sports/29/matchups',
     None, 'casa', 'CONTROL: ya integrada, debe funcionar'),
]

# --- C-bis) otras integraciones de Altenar --------------------------------
# La v76 probó betano, winpot, strendus, codere, betsson y sportium y todas
# dieron 400. El nombre de integración NO es el de la marca: `playdoit2` lleva
# sufijo. Se prueban variantes con sufijo y algunos operadores de Altenar en
# LatAm que no se habían mirado. Un 400 aquí significa «ese nombre no existe»,
# no «Altenar está cerrado».
ALTENAR_INTEGRACIONES = [
    'playdoit2',        # CONTROL: la nuestra
    'strendus2', 'winpot2', 'codere2', 'betsson2', 'sportium2',
    'novibet2', 'betcris2', 'jugabet2', 'rushbet2', 'ganabet2',
    'bet365mx2', 'megapari2', 'betwinner2', 'caliente2',
]


def robots_permite(url: str) -> str:
    p = urlparse(url)
    base = f'{p.scheme}://{p.netloc}'
    try:
        r = requests.get(base + '/robots.txt', headers=UA, timeout=12)
        if r.status_code != 200:
            return f'sin robots.txt ({r.status_code})'
        txt = r.text.lower()
    except Exception as e:
        return f'robots no accesible ({type(e).__name__})'
    bloques, actual = {}, None
    for linea in txt.splitlines():
        linea = linea.split('#')[0].strip()
        if linea.startswith('user-agent:'):
            actual = linea.split(':', 1)[1].strip()
            bloques.setdefault(actual, [])
        elif linea.startswith('disallow:') and actual is not None:
            bloques.setdefault(actual, []).append(linea.split(':', 1)[1].strip())
    for agente in ('anthropic-ai', 'claudebot', 'claude-web'):
        if agente in bloques and any(d == '/' for d in bloques[agente]):
            return f'PROHIBIDO explícitamente a {agente}'
    ruta = p.path or '/'
    for d in bloques.get('*', []):
        if d == '/':
            return 'prohibido TODO a User-agent: *'
        if d and ruta.startswith(d):
            return f'prohibido por «Disallow: {d}»'
    return 'permitido'


def parece_cuota(obj, prof=0) -> bool:
    """¿Hay algo con forma de cuota decimal o americana ahí dentro?"""
    if prof > 7:
        return False
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(t in kl for t in ('odds', 'price', 'cuota', 'momio',
                                     'decimal', 'american', 'bestbid',
                                     'bestask', 'lastprice', 'yes_ask')):
                if isinstance(v, (int, float, str)):
                    try:
                        f = float(v)
                    except (TypeError, ValueError):
                        continue
                    # decimal plausible, americana plausible, o probabilidad
                    # de mercado de predicción en céntimos (1-99)
                    if 1.01 <= f <= 1000 or abs(f) >= 100 or 1 <= f <= 99:
                        return True
                elif parece_cuota(v, prof + 1):
                    return True
            elif parece_cuota(v, prof + 1):
                return True
    elif isinstance(obj, list):
        for v in obj[:60]:
            if parece_cuota(v, prof + 1):
                return True
    return False


def sondear(nombre, url, params, familia, nota) -> dict:
    out = {'casa': nombre, 'familia': familia, 'url': url, 'nota': nota}
    out['robots'] = robots_permite(url)
    t0 = time.time()
    try:
        r = requests.get(url, params=params, headers=UA, timeout=25)
        out['status'] = r.status_code
        out['ms'] = int((time.time() - t0) * 1000)
        out['bytes'] = len(r.content)
        ct = r.headers.get('content-type', '')
        out['content_type'] = ct.split(';')[0]
        if r.status_code != 200:
            out['veredicto'] = f'HTTP {r.status_code}'
            return out
        try:
            j = r.json()
        except Exception:
            out['veredicto'] = ('HTML/JS (no JSON)' if 'html' in ct
                                else 'cuerpo no parseable')
            return out
        out['json'] = True
        if isinstance(j, dict):
            out['claves'] = list(j.keys())[:12]
            out['n'] = len(j)
        elif isinstance(j, list):
            out['claves'] = (list(j[0].keys())[:12]
                             if j and isinstance(j[0], dict) else [])
            out['n'] = len(j)
        out['cuotas'] = parece_cuota(j)
        out['veredicto'] = ('SIRVE — JSON con cuotas' if out['cuotas']
                            else 'JSON sin cuotas visibles')
    except Exception as e:
        out['veredicto'] = f'{type(e).__name__}: {str(e)[:120]}'
    return out


def sondear_altenar(integracion: str) -> dict:
    params = {'culture': 'es-ES', 'timezoneOffset': '360',
              'integration': integracion, 'deviceType': '1',
              'numFormat': 'en-GB', 'countryCode': 'MX', 'sportid': 66,
              'categoryids': '', 'champids': '', 'group': 'AllEvents',
              'period': 'periodall'}
    out = {'casa': f'Altenar:{integracion}', 'familia': 'altenar',
           'url': ALTENAR, 'nota': 'integración de widget'}
    try:
        r = requests.get(ALTENAR, params=params, headers=UA, timeout=45)
        out['status'] = r.status_code
        out['bytes'] = len(r.content)
        if r.status_code != 200:
            out['veredicto'] = f'HTTP {r.status_code}'
            return out
        j = r.json()
        evs = j.get('events') or []
        out['n_eventos'] = len(evs)
        out['n_precios'] = len(j.get('odds') or [])
        out['veredicto'] = (f'SIRVE — {len(evs)} eventos' if evs
                            else 'responde pero sin eventos')
    except Exception as e:
        out['veredicto'] = f'{type(e).__name__}: {str(e)[:120]}'
    return out


def main() -> int:
    res = []
    print('=' * 78)
    print('SONDEO v114 — casas, exchanges y agregadores')
    print('=' * 78)
    for nombre, url, params, familia, nota in CANDIDATAS:
        r = sondear(nombre, url, params, familia, nota)
        res.append(r)
        marca = '✅' if r.get('cuotas') else ('🟡' if r.get('json') else '❌')
        print(f"{marca} {r['casa']:<20} {str(r.get('status','—')):>5}  "
              f"{r['veredicto'][:52]:<52} robots={r['robots'][:28]}")
        sys.stdout.flush()
    print('-' * 78)
    print('Integraciones de Altenar (mismo endpoint que Playdoit)')
    print('-' * 78)
    for integ in ALTENAR_INTEGRACIONES:
        r = sondear_altenar(integ)
        res.append(r)
        marca = '✅' if r.get('n_eventos') else '❌'
        print(f"{marca} {r['casa']:<24} {str(r.get('status','—')):>5}  "
              f"{r['veredicto'][:50]}")
        sys.stdout.flush()

    with open('_v114_casas_candidatas.json', 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    sirven = [r for r in res if r.get('cuotas') or r.get('n_eventos')]
    print('=' * 78)
    print(f'{len(sirven)}/{len(res)} candidatas con datos utilizables:')
    for r in sirven:
        print(f"  · {r['casa']} ({r['familia']}) — {r['veredicto']}")
    print('Detalle en _v114_casas_candidatas.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
