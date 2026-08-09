"""
Sondeo de casas de apuestas nuevas para el tablón.

El line shopping es la ÚNICA vía con ROI positivo y robusto del proyecto
(+11,49 % en el tramo de juicio, p5 +1,73 %), y vive de la dispersión entre
casas. Hoy el tablón mira cuatro precios. Cada casa nueva multiplica las
oportunidades sin tocar el modelo.

Se comprueba, por cada candidata:
  · que `robots.txt` no lo prohíba (el proyecto ya descartó Statiz por eso),
  · que el endpoint responda,
  · que devuelva JSON parseable,
  · y que dentro haya algo que parezca una cuota.

Las que ya se probaron y fallaron en la v71 (Smarkets, Betfair, Betano, 1xBet,
Betsson, Marathonbet, Kambi/Unibet) NO se repiten: están documentadas.
"""
import json
import re
import sys
from urllib.parse import urlparse

import requests

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0 Safari/537.36'),
      'Accept': 'application/json, text/plain, */*'}

# candidatas: (nombre, url, nota)
CANDIDATAS = [
    # --- familia Digital Gaming Corp (mismo motor que Bovada) --------------
    ('BetOnline', 'https://www.betonline.ag/sportsbook/soccer', 'web'),
    ('Bodog', 'https://www.bodog.eu/services/sports/event/coupon/events/A/'
              'description/soccer?marketFilterId=def&preMatchOnly=true&lang=en',
     'mismo motor que Bovada'),
    ('Bovada-MX', 'https://www.bovada.lv/services/sports/event/coupon/events/A/'
                  'description/soccer/mexico?marketFilterId=def&preMatchOnly=true&lang=en',
     'ya la tenemos, control'),
    # --- crypto / internacionales con API pública --------------------------
    ('Cloudbet', 'https://sports-api.cloudbet.com/pub/v2/odds/sports', 'API pública documentada'),
    ('Coolbet', 'https://www.coolbet.com/api/sb/v2/configurations/sports', 'API interna'),
    ('Stake', 'https://stake.com/_api/casino/games', 'GraphQL, poco probable'),
    # --- Europa con JSON accesible ----------------------------------------
    ('Winamax', 'https://www.winamax.fr/paris-sportifs/sports/1', 'JSON embebido'),
    ('Betclic', 'https://offer.cdn.begmedia.com/api/pub/v4/sports/1'
                '?application=2048&countrycode=fr&language=fr&sitecode=frfr',
     'CDN público'),
    ('Unibet-feed', 'https://eu-offering-api.kambicdn.com/offering/v2018/ub/'
                    'listView/football.json?lang=en_GB&market=GB', 'Kambi CDN'),
    ('888sport', 'https://eu-offering-api.kambicdn.com/offering/v2018/888/'
                 'listView/football.json?lang=en_GB&market=GB', 'Kambi CDN'),
    # --- México (la casa del usuario está aquí) ----------------------------
    ('Caliente', 'https://www.caliente.mx/es/deportes', 'web MX'),
    ('Codere-MX', 'https://www.codere.mx/deportes', 'web MX'),
    ('Betano-MX', 'https://www.betano.mx/api/sport/futbol/', 'web MX'),
    # --- agregadores -------------------------------------------------------
    ('OddsPortal', 'https://www.oddsportal.com/matches/soccer/', 'agregador, JS'),
    ('Flashscore', 'https://www.flashscore.com/football/', 'agregador, JS'),
]


def robots_permite(url: str) -> str:
    """¿El robots.txt del sitio permite esta ruta? Devuelve un veredicto."""
    p = urlparse(url)
    base = f'{p.scheme}://{p.netloc}'
    try:
        r = requests.get(base + '/robots.txt', headers=UA, timeout=12)
        if r.status_code != 200:
            return f'sin robots.txt ({r.status_code})'
        txt = r.text.lower()
    except Exception as e:
        return f'robots no accesible ({type(e).__name__})'
    # bloque genérico
    bloques, actual = {}, None
    for linea in txt.splitlines():
        linea = linea.split('#')[0].strip()
        if linea.startswith('user-agent:'):
            actual = linea.split(':', 1)[1].strip()
            bloques.setdefault(actual, [])
        elif linea.startswith('disallow:') and actual is not None:
            bloques.setdefault(actual, []).append(linea.split(':', 1)[1].strip())
    # ¿nos nombra explícitamente?
    for agente in ('anthropic-ai', 'claudebot', 'claude-web'):
        if agente in bloques:
            if any(d == '/' for d in bloques[agente]):
                return f'PROHIBIDO explícitamente a {agente}'
    reglas = bloques.get('*', [])
    ruta = p.path or '/'
    for d in reglas:
        if d and d != '/' and ruta.startswith(d):
            return f'prohibido por «Disallow: {d}»'
        if d == '/':
            return 'prohibido TODO a User-agent: *'
    return 'permitido'


def parece_cuota(obj, prof=0) -> bool:
    """¿Hay algo con pinta de cuota decimal o americana ahí dentro?"""
    if prof > 6:
        return False
    if isinstance(obj, dict):
        claves = ' '.join(str(k).lower() for k in obj)
        if any(p in claves for p in ('odds', 'price', 'cuota', 'outcome',
                                     'moneyline', 'selection')):
            return True
        return any(parece_cuota(v, prof + 1) for v in list(obj.values())[:25])
    if isinstance(obj, list):
        return any(parece_cuota(v, prof + 1) for v in obj[:25])
    return False


print(f'{"casa":16s} {"robots":34s} {"HTTP":6s} {"tipo":12s} {"cuotas?":8s} nota')
print('-' * 110)
usables = []
for nombre, url, nota in CANDIDATAS:
    rb = robots_permite(url)
    if not rb.startswith('permitido') and 'sin robots' not in rb:
        print(f'{nombre:16s} {rb:34s} {"-":6s} {"-":12s} {"-":8s} {nota}')
        continue
    try:
        r = requests.get(url, headers=UA, timeout=20)
        code = str(r.status_code)
        ctype = (r.headers.get('content-type') or '')[:12]
        tiene = '-'
        if r.status_code == 200:
            try:
                j = r.json()
                tiene = 'SÍ' if parece_cuota(j) else 'no'
                if tiene == 'SÍ':
                    usables.append((nombre, url, nota))
            except Exception:
                # ¿JSON embebido en HTML?
                m = re.search(r'application/json[^>]*>(\{.*?\})</script>',
                              r.text, re.S)
                tiene = 'html' if not m else 'embebido'
    except Exception as e:
        code, ctype, tiene = type(e).__name__[:6], '-', '-'
    print(f'{nombre:16s} {rb:34s} {code:6s} {ctype:12s} {tiene:8s} {nota}')

print(f'\n=== candidatas con JSON de cuotas: {len(usables)} ===')
for n, u, _ in usables:
    print(f'  {n}: {u}')
json.dump([{'casa': n, 'url': u, 'nota': x} for n, u, x in usables],
          open('_v111_casas_candidatas.json', 'w', encoding='utf-8'),
          indent=1, ensure_ascii=False)
