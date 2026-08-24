#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v165 — ¿EL PRECIO QUE TRAEMOS ES DEL PARTIDO QUE CREEMOS?

`cuotas_multi._buscar` empareja por nombre, y sin este control se descubrió que
casaba «Botafogo vs Athletico-PR» (Brasileirão) con el «Botafogo SP vs
Atlético» que la casa cotizaba el mismo día. Pasar `fecha` y `liga` NO lo
arregla: los dos partidos son del mismo día y de la misma categoría.

Un precio de otro partido no produce un hueco —que sería honesto— sino un
CONTRASTE FALSO, y este módulo existe justo para contrastar. Así que hace falta
una segunda opinión independiente, y la hay: ESPN publica su propio 1X2 del
mismo fixture. Si los dos devigados discrepan mucho sobre quién es favorito, el
emparejamiento es sospechoso y el precio se tira.

Este script mide cuántos partidos del día caen de cada lado, para elegir el
umbral con un número delante en vez de a ojo.

    python _v165_emparejado_casa.py
"""
import json
import logging
import sys
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v165_emparejado_casa.json'


def main():
    import cuotas_multi as cm
    import fixtures_espn as fx
    import mercado_implicito as mi
    from config import LEAGUES

    doc = mi.cargar(recargar=True)
    precios = doc.get('partidos') or {}
    if not precios:
        print('no hay mercado_dia.json: ejecuta antes mercado_implicito.py')
        return 1

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fx.ESPN_CODIGOS]
    por_liga = fx.fixtures_multi(claves, dias=2)

    filas = []
    for lista in (por_liga or {}).values():
        for f in (lista or []):
            h, a = f.get('home'), f.get('away')
            if not (h and a):
                continue
            precio = precios.get(mi.llave(h, a))
            x2 = (precio or {}).get('1x2')
            if not x2:
                continue
            if not (f.get('odd_home') and f.get('odd_draw')
                    and f.get('odd_away')):
                continue
            espn = cm.devig({'home': f['odd_home'], 'draw': f['odd_draw'],
                             'away': f['odd_away']}, metodo='potencia')
            if len(espn) != 3:
                continue
            filas.append({
                'partido': '%s vs %s' % (h, a),
                'casa_home': round(x2['home'], 3),
                'espn_home': round(espn['home'], 3),
                'dif': round(x2['home'] - espn['home'], 3),
                'favorito_cambia': (x2['home'] > x2['away']) !=
                                   (espn['home'] > espn['away'])})

    filas.sort(key=lambda r: -abs(r['dif']))
    print('%d partidos con 1X2 de las DOS fuentes\n' % len(filas))
    for umbral in (0.10, 0.15, 0.20, 0.25, 0.30):
        n = sum(1 for r in filas if abs(r['dif']) > umbral)
        print('  |dif| > %.2f  ->  %3d partidos (%.0f %%)'
              % (umbral, n, 100.0 * n / max(len(filas), 1)))
    print('\n  el favorito cambia de bando en %d'
          % sum(1 for r in filas if r['favorito_cambia']))

    print('\nLOS DIEZ MAYORES:')
    for r in filas[:10]:
        print('  %-46s casa %.2f · ESPN %.2f  (%+.2f)%s'
              % (r['partido'][:46], r['casa_home'], r['espn_home'], r['dif'],
                 '  ← el favorito CAMBIA' if r['favorito_cambia'] else ''))

    json.dump(filas, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
