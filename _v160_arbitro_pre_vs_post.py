# -*- coding: utf-8 -*-
"""v160 — ¿ESPN da el arbitro ANTES del partido?

Se recorre el scoreboard de las 20 competiciones con tarjetas OBSERVADAS,
en una ventana de dias pasados y futuros, y por cada evento se pide el summary
y se mira si trae gameInfo.officials. El corte que importa es el estado:
'pre' (aun por jugar, que es cuando hace falta) contra 'post' (ya jugado).
"""
import json, urllib.request, datetime as dt, collections
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

from config_ligas_espn import ESPN_CODIGOS_V68 as MAPA
CLAVES = ['premier','eng_championship','eng_league_one','eng_league_two','eng_national',
          'sco_premiership','sco_championship','laliga','serie_a','ligue_1','bundesliga',
          'esp_hypermotion','ita_serie_b','fra_ligue2','turquia','primeira',
          'ger_bundesliga2','eredivisie','gre_super_league','bel_pro_league']

hoy = dt.date(2026, 8, 22)
rango = '%s-%s' % ((hoy - dt.timedelta(days=6)).strftime('%Y%m%d'),
                   (hoy + dt.timedelta(days=6)).strftime('%Y%m%d'))

eventos = []
def sb(clave):
    code = MAPA.get(clave)
    if not code:
        return []
    try:
        d = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/scoreboard?dates=%s'
                % (code, rango))
    except Exception as e:
        print('  scoreboard %s: %s' % (clave, e)); return []
    out = []
    for ev in (d.get('events') or []):
        st = ((ev.get('status') or {}).get('type') or {}).get('state')
        out.append((clave, code, ev.get('id'), st, ev.get('date'), ev.get('name')))
    return out

with ThreadPoolExecutor(max_workers=8) as ex:
    for r in ex.map(sb, CLAVES):
        eventos += r
print('eventos recogidos:', len(eventos), 'ventana', rango)
print('por estado:', collections.Counter(e[3] for e in eventos))

def arbitro(e):
    clave, code, eid, st, fecha, nombre = e
    try:
        su = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/summary?event=%s'
                 % (code, eid))
    except Exception:
        return (clave, st, None, 'ERROR', fecha, nombre)
    offs = ((su.get('gameInfo') or {}).get('officials')) or []
    ref = None
    for o in offs:
        if str(((o.get('position') or {}).get('name') or '')).lower() == 'referee':
            ref = o.get('displayName') or o.get('fullName')
    return (clave, st, ref, 'ok', fecha, nombre)

with ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(arbitro, eventos))

cnt = collections.defaultdict(lambda: [0, 0])
for clave, st, ref, ok, fecha, nombre in res:
    cnt[st][0] += 1
    if ref:
        cnt[st][1] += 1
print()
print('%-8s %8s %10s %8s' % ('estado', 'eventos', 'con árbitro', '%'))
for st, (n, c) in sorted(cnt.items()):
    print('%-8s %8d %10d %7.1f%%' % (st, n, c, 100.0*c/n if n else 0))

print()
print('EJEMPLOS pre CON arbitro:')
for clave, st, ref, ok, fecha, nombre in res:
    if st == 'pre' and ref:
        print('  ', clave, fecha, nombre, '->', ref)
print('EJEMPLOS pre SIN arbitro (primeros 8):')
k = 0
for clave, st, ref, ok, fecha, nombre in res:
    if st == 'pre' and not ref:
        print('  ', clave, fecha, nombre); k += 1
        if k >= 8: break

json.dump([{'clave': c, 'estado': s, 'arbitro': r, 'fecha': f, 'partido': n}
           for c, s, r, ok, f, n in res],
          open('_v160_arbitro_pre_vs_post.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
