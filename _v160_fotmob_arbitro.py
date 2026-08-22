# -*- coding: utf-8 -*-
import json, requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://www.fotmob.com/'}
def busca(o, palabra, camino='', out=None, prof=0):
    if out is None: out = []
    if prof > 14: return out
    if isinstance(o, dict):
        for k, v in o.items():
            p = camino + '.' + str(k)
            if palabra.lower() in str(k).lower(): out.append((p, v))
            busca(v, palabra, p, out, prof+1)
    elif isinstance(o, list):
        for i, v in enumerate(o[:10]): busca(v, palabra, camino+'[%d]'%i, out, prof+1)
    return out
for etiqueta, mid in (('FUTURO Brighton-Villa 23/8', '5795369'),
                      ('FUTURO City-Bournemouth 23/8', '5795370'),
                      ('JUGADO Arsenal-Coventry 21/8', '5795363')):
    r = requests.get('https://www.fotmob.com/api/data/matchDetails?matchId=%s' % mid, headers=UA, timeout=25)
    d = r.json()
    print('=' * 66); print(etiqueta, '| bytes', len(r.text), '| started', (d.get('general') or {}).get('started'))
    for pal in ('referee', 'Referee'):
        for p, v in busca(d, pal):
            if 'translation' in p: continue
            print('  ', p, '=', json.dumps(v, ensure_ascii=False)[:250])
    ib = busca(d, 'infoBox')
    for p, v in ib[:1]:
        print('   infoBox claves:', list(v.keys()) if isinstance(v, dict) else type(v))
        if isinstance(v, dict) and 'Referee' in v:
            print('   >> Referee =', json.dumps(v['Referee'], ensure_ascii=False)[:200])
