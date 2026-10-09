# -*- coding: utf-8 -*-
"""v343 — lo que la tarjeta dijo «meter» de cada partido en CADA precálculo.

El usuario armó un parley la madrugada del 8-oct con lo que daba la app y a
mediodía vio otras apuestas en los mismos partidos. Esto recorre las fotos de
`pronostico_dia.json` en git (cada ~1,5 h) y saca, por partido, las «meter»
que enseñaba la tarjeta (las dos primeras, como `modo_modelo.metidas`) con su
probabilidad, cuota y precio de la casa.

Uso: python _v343_historia.py "Santos" "Fluminense" ...
"""
import json
import subprocess
import sys

BUSCA = [s.lower() for s in sys.argv[1:]]
hs = subprocess.run(['git', 'log', '--since=2026-10-07T12:00', '--format=%H %cI',
                     'origin/main', '--', 'pronostico_dia.json'],
                    capture_output=True, text=True).stdout.split('\n')
for linea in reversed([h for h in hs if h.strip()]):
    h, fecha = linea.split()
    try:
        d = json.loads(subprocess.run(['git', 'show', '%s:pronostico_dia.json' % h],
                                      capture_output=True).stdout.decode('utf-8'))
    except Exception:
        continue
    dec = (d.get('decisiones') or {}).get('listas', {}).get('pronosticos') or []
    for x in dec:
        par = str((x.get('llave') or [''])[0])
        if not any(b in par.lower() for b in BUSCA):
            continue
        met = [r for r in (x.get('recomendadas_tarjeta') or x.get('recomendadas') or [])
               if r.get('veredicto_vp') == 'meter'][:2]
        txt = ' | '.join('%s %.0f%% @%.2f casa %s' % (
            r['apuesta'], 100 * (r.get('prob_meter') or r['prob']), r.get('cuota') or 0,
            '%.0f%%' % (100 * r['p_mercado']) if r.get('p_mercado') else '—') for r in met)
        print('%s  %-40s %s' % (fecha[5:16], par[:40], txt or '(nada que meter)'))
