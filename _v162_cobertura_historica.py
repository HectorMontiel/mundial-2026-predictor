# -*- coding: utf-8 -*-
"""
v162 - HASTA DONDE LLEGA EL BOXSCORE DE ESPN, Y CUANTO CUESTA TRAERLO.

Dos preguntas que deciden el alcance de todo lo demas:
  1. ¿desde que temporada hay estadisticas? (si solo hay 2026, el backfill no
     da para calibrar nada)
  2. ¿cuanto tarda un partido? (decide si esto cabe en un workflow)

Se muestrea una temporada por año en varias competiciones de las que HOY no
tienen corners ni tarjetas observados.
"""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def tiene_stats(code, eid):
    try:
        su = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                 'summary?event=%s' % (code, eid))
    except Exception:
        return None
    eq = ((su.get('boxscore') or {}).get('teams') or [])
    if len(eq) < 2:
        return False
    nombres = {s.get('name') for t in eq for s in (t.get('statistics') or [])}
    return ('wonCorners' in nombres) and ('yellowCards' in nombres)


LIGAS = [('liga_mx', 'mex.1'), ('argentina', 'arg.1'), ('brasil', 'bra.1'),
         ('mls', 'usa.1'), ('col_primera_a', 'col.1'), ('jpn_j1', 'jpn.1'),
         ('suecia', 'swe.1'), ('per_liga1', 'per.1')]
# una ventana de 10 dias en plena temporada de cada año
VENTANAS = [('2018', '20180401-20180410'), ('2019', '20190401-20190410'),
            ('2020', '20201001-20201010'), ('2021', '20210401-20210410'),
            ('2022', '20220401-20220410'), ('2023', '20230401-20230410'),
            ('2024', '20240401-20240410'), ('2025', '20250401-20250410'),
            ('2026', '20260401-20260410')]

print('%-16s %s' % ('liga', ' '.join('%6s' % a for a, _ in VENTANAS)))
resumen = {}
for clave, code in LIGAS:
    fila = []
    for anio, ventana in VENTANAS:
        try:
            sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                     'scoreboard?dates=%s&limit=500' % (code, ventana))
            evs = [e for e in (sb.get('events') or [])
                   if (((e.get('status') or {}).get('type') or {})
                       .get('state') == 'post')]
        except Exception:
            fila.append('  err')
            continue
        if not evs:
            fila.append('    -')
            continue
        muestra = evs[:3]
        with ThreadPoolExecutor(max_workers=3) as ex:
            res = [r for r in ex.map(lambda e: tiene_stats(code, e.get('id')),
                                     muestra) if r is not None]
        if not res:
            fila.append('    ?')
        else:
            fila.append('%3d/%d' % (sum(res), len(res)))
    resumen[clave] = fila
    print('%-16s %s' % (clave, ' '.join('%6s' % x for x in fila)))

print()
print('leyenda: n/m = n de m partidos muestreados traen wonCorners y yellowCards')
print('         -   = ESPN no tiene partidos jugados en esa ventana')

# coste por partido
print()
print('COSTE MEDIDO')
sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/'
         'scoreboard?dates=20260401-20260430&limit=500')
evs = [e for e in (sb.get('events') or [])
       if (((e.get('status') or {}).get('type') or {}).get('state') == 'post')]
print('  partidos en un mes de Liga MX: %d' % len(evs))
for hilos in (1, 8, 16):
    lote = evs[:16]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        list(ex.map(lambda e: tiene_stats('mex.1', e.get('id')), lote))
    dt = time.time() - t0
    print('  %2d hilos: %d partidos en %.1f s  (%.2f s/partido)'
          % (hilos, len(lote), dt, dt / max(len(lote), 1)))

json.dump(resumen, open('_v162_cobertura_historica.json', 'w',
                        encoding='utf-8'), ensure_ascii=False, indent=1)
