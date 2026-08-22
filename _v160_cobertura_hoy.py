# -*- coding: utf-8 -*-
"""
v160 - QUE PARTIDOS HAY HOY DE VERDAD, Y CUALES ESTA VIENDO EL BARRIDO.

HMREY reporta 55 partidos hoy y echa en falta Real Madrid-Bayern y otros.
Esto no opina: pregunta a ESPN por las 64 competiciones que el proyecto tiene
codificadas MAS un puñado de codigos que el proyecto no conoce (amistosos de
club, supercopas, ligas grandes que faltan), cuenta los partidos de hoy y dice
por que cae fuera cada uno: sin codigo, no 'disponible', o ya empezado.
"""
import datetime as dt
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}
HOY = dt.date(2026, 8, 22)
FECHA = HOY.strftime('%Y%m%d')


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


import fixtures_espn
from config import LEAGUES

CODIGOS = dict(fixtures_espn.ESPN_CODIGOS)
# codigos que el proyecto NO tiene y que en agosto mueven partidos grandes
EXTRA = {
    '(amistosos de club)': 'fifa.friendly.club',
    '(amistosos de seleccion)': 'fifa.friendly',
    '(Supercopa de Europa)': 'uefa.super_cup',
    '(Supercopa de Espana)': 'esp.super_cup',
    '(Community Shield)': 'eng.charity',
    '(Supercopa de Italia)': 'ita.super_cup',
    '(Supercopa de Alemania)': 'ger.super_cup',
    '(Trophee des Champions)': 'fra.super_cup',
    '(Copa de Alemania)': 'ger.dfb_pokal',
    '(Copa de Francia)': 'fra.coupe_de_france',
    '(Copa de Italia)': 'ita.coppa_italia',
    '(Copa de Portugal)': 'por.taca.de.portugal',
    '(Copa de Holanda)': 'ned.knvb_beker',
    '(Club World Cup)': 'fifa.cwc',
    '(Suiza)': 'sui.1',
    '(Polonia)': 'pol.1',
    '(Chequia)': 'cze.1',
    '(Croacia)': 'cro.1',
    '(Serbia)': 'srb.1',
    '(Ucrania)': 'ukr.1',
    '(Israel)': 'isr.1',
    '(Corea)': 'kor.1',
    '(Arabia)': 'ksa.1',
    '(Catar)': 'qat.1',
    '(EAU)': 'uae.1',
    '(Egipto)': 'egy.1',
    '(Escocia League One)': 'sco.3',
    '(Islandia)': 'isl.1',
    '(Bulgaria)': 'bul.1',
    '(Hungria)': 'hun.1',
    '(Eslovaquia)': 'svk.1',
    '(Eslovenia)': 'slo.1',
    '(Chipre)': 'cyp.1',
    '(Marruecos)': 'mar.1',
    '(Canada)': 'can.1',
    '(USL League One)': 'usa.usl.l1',
    '(NWSL)': 'usa.nwsl',
    '(WSL)': 'eng.w.1',
    '(Concacaf CL)': 'concacaf.champions',
}

todos = [(k, v, True) for k, v in CODIGOS.items()] + \
        [(k, v, False) for k, v in EXTRA.items()]


def mira(t):
    clave, slug, conocida = t
    try:
        d = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                'scoreboard?dates=%s' % (slug, FECHA))
    except Exception as e:
        return {'clave': clave, 'slug': slug, 'conocida': conocida,
                'n': 0, 'error': '%s' % e, 'eventos': []}
    evs = d.get('events') or []
    return {'clave': clave, 'slug': slug, 'conocida': conocida, 'n': len(evs),
            'error': None,
            'eventos': [{'nombre': e.get('name'), 'fecha': e.get('date'),
                         'estado': ((e.get('status') or {}).get('type') or {}).get('state')}
                        for e in evs]}


with ThreadPoolExecutor(max_workers=12) as ex:
    res = list(ex.map(mira, todos))

con = [r for r in res if r['n']]
con.sort(key=lambda r: (-r['conocida'], -r['n']))

tot = sum(r['n'] for r in con)
conocidos = sum(r['n'] for r in con if r['conocida'])
disp = 0
print('PARTIDOS DE FUTBOL HOY %s' % HOY)
print('  total encontrados en ESPN .............. %d' % tot)
print('  en competiciones que el proyecto codifica %d' % conocidos)
print('  en competiciones SIN codigo en el proyecto %d' % (tot - conocidos))
print()
print('%-24s %-26s %4s %5s %s' % ('clave', 'slug', 'n', 'disp', 'estados'))
for r in con:
    cfg = LEAGUES.get(r['clave']) or {}
    d = cfg.get('disponible')
    if r['conocida'] and d:
        disp += r['n']
    estados = {}
    for e in r['eventos']:
        estados[e['estado']] = estados.get(e['estado'], 0) + 1
    marca = '' if (r['conocida'] and d) else '   <-- FUERA'
    print('%-24s %-26s %4d %5s %s%s' % (r['clave'], r['slug'], r['n'],
                                        d if r['conocida'] else 'n/a',
                                        estados, marca))

print()
print('  en competiciones DISPONIBLES del barrido . %d' % disp)
print()
print('BUSCANDO Real Madrid / Bayern / Barcelona hoy:')
hallado = False
for r in con:
    for e in r['eventos']:
        if any(k in (e['nombre'] or '') for k in
               ('Real Madrid', 'Bayern', 'Barcelona', 'Atletico Madrid')):
            cfg = LEAGUES.get(r['clave']) or {}
            print('   %-24s %-46s [%s] disponible=%s'
                  % (r['slug'], e['nombre'], e['estado'],
                     cfg.get('disponible') if r['conocida'] else 'SIN CODIGO'))
            hallado = True
if not hallado:
    print('   no aparece en ninguna de las %d competiciones sondeadas' % len(todos))

json.dump(res, open('_v160_cobertura_hoy.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
