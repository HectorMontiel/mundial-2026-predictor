#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Que historicos ha encogido el bot nocturno, y cuanto.

`league_engine.entrenar_liga` escribe `historico_<clave>.csv` con lo que le
devuelva `descargar_liga`, SIN comparar contra lo que ya habia. Si la fuente
falla —football-data.co.uk lleva devolviendo 503— el fichero bueno se
sobrescribe con uno degradado y el commit nocturno lo sube.

Detectado en la Leagues Cup: 6.758 filas el 2026-09-03 y 291 el 2026-09-06.
Este script mira TODOS los historicos, no solo ese.

Uso:
    python _v178_historicos_encogidos.py [revision_de_referencia]
"""
import io
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

REF = sys.argv[1] if len(sys.argv) > 1 else '04e48e4'


def filas(rev, fichero):
    r = subprocess.run(['git', 'show', '%s:%s' % (rev, fichero)],
                       capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.count(b'\n')


def main():
    lst = subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'HEAD'],
                         capture_output=True, text=True).stdout.split('\n')
    hist = sorted(f for f in lst
                  if f.startswith('historico_') and f.endswith('.csv'))
    print('%d historicos · referencia %s' % (len(hist), REF))
    encogidos = []
    for f in hist:
        a, b = filas(REF, f), filas('HEAD', f)
        if a is None or b is None or a <= 1:
            continue
        if b < a:
            encogidos.append((f, a, b, 100.0 * (a - b) / a))
    encogidos.sort(key=lambda x: -x[3])
    if not encogidos:
        print('ninguno ha encogido')
        return 0
    print()
    print('%-45s %8s %8s %8s' % ('fichero', REF, 'HEAD', 'perdido'))
    for f, a, b, pct in encogidos:
        print('%-45s %8d %8d %7.1f %%' % (f, a, b, pct))
    print()
    print('%d historicos con menos filas que el %s' % (len(encogidos), REF))
    return 1


if __name__ == '__main__':
    sys.exit(main())
