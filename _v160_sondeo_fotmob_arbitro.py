# -*- coding: utf-8 -*-
"""v160 — ¿FotMob publica el arbitro DESIGNADO antes del partido?"""
import json, re, requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def next_data(url):
    r = requests.get(url, headers=UA, timeout=30)
    print('  HTTP', r.status_code, 'len', len(r.text))
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        return None
    return json.loads(m.group(1))

def busca(obj, palabra, camino='', out=None, prof=0):
    if out is None: out = []
    if prof > 12: return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = camino + '.' + str(k)
            if palabra.lower() in str(k).lower():
                out.append((p, v))
            busca(v, palabra, p, out, prof+1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:8]):
            busca(v, palabra, camino + '[%d]' % i, out, prof+1)
    return out

print('--- overview de la Premier para sacar ids de partidos futuros ---')
d = next_data('https://www.fotmob.com/leagues/47/overview/premier-league')
if not d:
    print('sin __NEXT_DATA__ (FotMob cambio de render o bloqueo)')
    raise SystemExit
ov = (d.get('props', {}).get('pageProps', {}) or {}).get('overview') or {}
ms = ov.get('leagueOverviewMatches') or []
print('partidos en overview:', len(ms))
futuros = [m for m in ms if not ((m.get('status') or {}).get('finished'))]
jugados = [m for m in ms if ((m.get('status') or {}).get('finished'))]
print('futuros:', len(futuros), 'jugados:', len(jugados))

for etiqueta, lote in (('FUTURO', futuros[:2]), ('JUGADO', jugados[:2])):
    for m in lote:
        mid = m.get('id')
        h = (m.get('home') or {}).get('name'); a = (m.get('away') or {}).get('name')
        print('=' * 60)
        print(etiqueta, mid, h, 'vs', a, (m.get('status') or {}).get('utcTime'))
        dd = next_data('https://www.fotmob.com/matches/x/%s' % mid)
        if not dd:
            print('  sin __NEXT_DATA__'); continue
        for palabra in ('referee', 'Referee', 'arbit', 'official'):
            hits = busca(dd, palabra)
            if hits:
                print('  >> %s: %d' % (palabra, len(hits)))
                for p, v in hits[:3]:
                    print('     ', p, '=', json.dumps(v, ensure_ascii=False)[:200])
                break
        else:
            ib = busca(dd, 'infoBox')
            print('  sin referee. infoBox:', json.dumps(ib[0][1], ensure_ascii=False)[:400] if ib else 'no hay')
