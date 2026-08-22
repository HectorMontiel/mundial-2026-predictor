# -*- coding: utf-8 -*-
"""v160 — el feed de ESPN, a ver si trae arbitro. Se prueban las dos vias:
el scoreboard (lo que ya consume el barrido) y el summary por evento."""
import json, urllib.request

UA = {'User-Agent': 'Mozilla/5.0'}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

def busca(obj, clave, camino=''):
    """Todas las apariciones de una clave, a cualquier profundidad."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = camino + '.' + str(k)
            if clave.lower() in str(k).lower():
                out.append((p, v))
            out += busca(v, clave, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:6]):
            out += busca(v, clave, camino + '[%d]' % i)
    return out

LIGAS = ['eng.1', 'esp.1', 'ita.1', 'ger.1', 'mex.1']
for lg in LIGAS:
    print('=' * 70)
    print('LIGA', lg)
    try:
        sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/scoreboard' % lg)
    except Exception as e:
        print('  scoreboard ERROR', e); continue
    evs = sb.get('events') or []
    print('  eventos en scoreboard:', len(evs))
    hits = busca(sb, 'official')
    print('  "official*" en scoreboard:', len(hits), hits[:3])
    if not evs:
        # sin partidos hoy: se pide un dia con partidos seguro
        try:
            sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/scoreboard?dates=20260510' % lg)
            evs = sb.get('events') or []
            print('  (con dates=20260510) eventos:', len(evs))
        except Exception as e:
            print('  retry ERROR', e)
    if not evs:
        continue
    eid = evs[0].get('id')
    print('  evento de prueba:', eid, evs[0].get('name'), evs[0].get('status', {}).get('type', {}).get('state'))
    try:
        su = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/summary?event=%s' % (lg, eid))
    except Exception as e:
        print('  summary ERROR', e); continue
    print('  claves del summary:', sorted(su.keys()))
    for palabra in ('official', 'referee', 'arbit'):
        h = busca(su, palabra)
        if h:
            print('  >> "%s" en summary: %d' % (palabra, len(h)))
            for p, v in h[:4]:
                print('     ', p, '=', json.dumps(v, ensure_ascii=False)[:300])
