# -*- coding: utf-8 -*-
"""
v326 — pruebas: «ambos marcan» derivado de «marca el local» y «marca el
visitante» (`patrones_liga.btts_derivada`).

  1. Está medido en el fichero: activo sólo con mejora y p5 > 0.
  2. Apagado o sin datos, no toca nada (devuelve None).
  3. Encendido, `ajustar` lo escribe en el tablero y en los mercados del
     partido, con Sí + No = 1, y deja constancia de antes y después.
  4. Sube con la probabilidad de que marquen los dos equipos.

Uso: python test_v326.py
"""
from __future__ import annotations

import copy
import json
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def main():
    import patrones_liga as pl
    doc = pl.cargar()
    b = doc.get('btts_derivada') or {}
    check(bool(b), 'el fichero trae la medición de ambos marcan derivado')
    check(b.get('activo') == bool((b.get('mejora') or 0) > 0 and (b.get('p5') or 0) > 0),
          'activo sólo con mejora y p5 > 0 (mejora %s, p5 %s)' % (b.get('mejora'), b.get('p5')))
    # apagado → None
    viejo = copy.deepcopy(b)
    try:
        doc['btts_derivada'] = dict(b, activo=False)
        check(pl.btts_derivada(0.8, 0.7, 0.55) is None, 'apagado, no toca nada')
    finally:
        doc['btts_derivada'] = viejo
    if not b.get('activo'):
        print('(no está activo: el resto no aplica)')
        return
    lo = pl.btts_derivada(0.55, 0.50, 0.45)
    hi = pl.btts_derivada(0.85, 0.80, 0.45)
    check(lo is not None and hi is not None and hi > lo,
          'sube cuando los dos equipos marcan más (%.3f → %.3f)' % (lo, hi))
    # ajustar sobre un partido real del día
    d = json.load(open('pronostico_dia.json', encoding='utf-8'))
    hechos = 0
    for p in d['datos']['pronosticos']:
        if p.get('deporte') != 'Fútbol' or p.get('jugado'):
            continue
        q = copy.deepcopy(p)
        if not pl.ajustar(q):
            continue
        info = (q.get('patron_liga') or {}).get('btts')
        if not info:
            continue
        bo = q['board']
        si, no = bo.get('Ambos marcan: Sí'), bo.get('Ambos marcan: No')
        ok = abs(si + no - 1) < 0.0015 and si == info['despues']
        merc = {m['apuesta']: m['prob'] for m in q.get('mercados') or []
                if m.get('mercado') == 'BTTS'}
        ok = ok and (not merc or (merc.get('Ambos marcan: Sí') == si))
        check(ok, '%s: ambos marcan %.3f → %.3f en tablero y mercados'
              % (q['partido'], info['antes'], info['despues']))
        hechos += 1
        if hechos >= 3:
            break
    check(hechos > 0, 'se aplica a los partidos del día (%d revisados)' % hechos)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
