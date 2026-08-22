# -*- coding: utf-8 -*-
"""
v160 - DONDE SE CAEN LOS PARTIDOS QUE NO SALEN EN LA LISTA.

Se ejecuta la MISMA recogida que hace el barrido (claves disponibles ->
fixtures_multi -> filtro de ventana) y se compara, competicion a competicion,
contra lo que ESPN dice que hay hoy. Cada partido perdido queda con su motivo.
"""
import json
import pandas as pd

import fixtures_espn
import alpha_finder as af
from config import LEAGUES

claves_disp = [c for c, cfg in LEAGUES.items()
               if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
print('competiciones en config.LEAGUES ............ %d' % len(LEAGUES))
print('  con disponible=True ...................... %d'
      % sum(1 for c in LEAGUES.values() if c.get('disponible')))
print('  ademas con codigo ESPN (las que se barren)  %d' % len(claves_disp))
sin_codigo = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c not in fixtures_espn.ESPN_CODIGOS]
print('  disponibles SIN codigo ESPN (se pierden) . %d  %s'
      % (len(sin_codigo), sin_codigo[:12]))
no_disp = [c for c, cfg in LEAGUES.items()
           if not cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
print('  con codigo ESPN pero disponible=False .... %d  %s'
      % (len(no_disp), no_disp[:12]))

print()
print('pidiendo fixtures a ESPN (dias=3), igual que el barrido...')
fx = fixtures_espn.fixtures_multi(claves_disp, dias=3)
bruto = {k: len(v or []) for k, v in fx.items()}
en_ventana = {k: [f for f in (v or []) if af._en_ventana(f)] for k, v in fx.items()}

hoy = af.hoy_utc()
print('hoy_utc =', hoy)

filas = []
for c in claves_disp:
    v = en_ventana.get(c) or []
    hoy_n = sum(1 for f in v if af._es_del_dia(f))
    filas.append({'clave': c, 'bruto': bruto.get(c, 0),
                  'en_ventana': len(v), 'del_dia': hoy_n})
t = pd.DataFrame(filas).sort_values('bruto', ascending=False)
print()
print(t[t['bruto'] > 0].to_string(index=False))
print()
print('TOTALES: bruto %d · en ventana %d · del dia %d'
      % (t['bruto'].sum(), t['en_ventana'].sum(), t['del_dia'].sum()))

# competiciones que ESPN tiene con partidos hoy y aqui devuelven 0
try:
    espn = json.load(open('_v160_cobertura_hoy.json', encoding='utf-8'))
    print()
    print('COMPETICIONES CON PARTIDOS HOY EN ESPN Y CERO AQUI:')
    for r in espn:
        if not r['n'] or not r['conocida']:
            continue
        c = r['clave']
        if c in claves_disp and (bruto.get(c, 0) == 0):
            print('   %-22s ESPN=%d  barrido=0   <-- se pierde entera' % (c, r['n']))
        elif c not in claves_disp:
            cfg = LEAGUES.get(c) or {}
            print('   %-22s ESPN=%d  NO se barre (disponible=%s, codigo=%s)'
                  % (c, r['n'], cfg.get('disponible'), c in fixtures_espn.ESPN_CODIGOS))
except FileNotFoundError:
    pass

json.dump({'claves_disp': claves_disp, 'bruto': bruto,
           'del_dia': {r['clave']: r['del_dia'] for r in filas}},
          open('_v160_donde_se_caen.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
