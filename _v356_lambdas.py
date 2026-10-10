#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v356 — lo que el modelo de goles esperaba de cada partido de fútbol antes
de jugarse, sacado de las fotos de `pronostico_dia.json` en git (la última
antes del inicio): `goles_xg` (local, visitante), `goles_lambda` y la
escalera de goles del modelo. Escribe `_v356_lambdas.csv`."""
import json
import subprocess
import sys

import pandas as pd

DESDE = '2026-08-24'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    hs = subprocess.run(['git', 'log', '--format=%H %cI', '--since=' + DESDE, 'origin/main',
                         '--', 'pronostico_dia.json'], capture_output=True, text=True).stdout.split('\n')
    hs = [h for h in hs if h.strip()][::2]
    ult = {}
    for i, linea in enumerate(hs):
        h, cuando = linea.split()
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':pronostico_dia.json'],
                                          capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        ts = pd.Timestamp(cuando).tz_convert('UTC').tz_localize(None)
        for p in ((d.get('datos') or d).get('pronosticos') or []):
            if not isinstance(p, dict) or (p.get('deporte') or 'Fútbol') != 'Fútbol':
                continue
            try:
                ini = pd.Timestamp(p.get('inicio'))
                ini = ini.tz_convert('UTC').tz_localize(None) if ini.tzinfo else ini
            except Exception:
                continue
            if ts >= ini:
                continue
            k = (p.get('partido'), str(p.get('clave_liga')))
            if k in ult and ult[k]['ts'] >= ts:
                continue
            xg = p.get('goles_xg') or {}
            gl = p.get('goles_lineas') or {}
            ult[k] = {'ts': ts, 'partido': p.get('partido'), 'clave_liga': p.get('clave_liga'),
                      'inicio': p.get('inicio'), 'xg_h': xg.get('local'), 'xg_a': xg.get('visitante'),
                      'lam': p.get('goles_lambda'),
                      'm_mas15': (gl.get('1.5') or {}).get('mas') if isinstance(gl.get('1.5'), dict) else gl.get('1.5'),
                      'm_mas25': (gl.get('2.5') or {}).get('mas') if isinstance(gl.get('2.5'), dict) else gl.get('2.5'),
                      'm_mas35': (gl.get('3.5') or {}).get('mas') if isinstance(gl.get('3.5'), dict) else gl.get('3.5')}
        if i % 20 == 0:
            print(i, len(hs), len(ult), flush=True)
    t = pd.DataFrame(ult.values())
    t.to_csv('_v356_lambdas.csv', index=False)
    print('guardado', len(t))


if __name__ == '__main__':
    main()
