# -*- coding: utf-8 -*-
"""
v328 — pruebas: el «🔍 Análisis» de la tarjeta es corto y sólo lleva lo medido.

  1. Ni «sin medir», ni «destacado», ni remates, ni «quién remata».
  2. Una línea por cosa: goles (con el mismo total que la razón de la
     apuesta), córners y tarjetas sólo si no son estimados.
  3. La tarjeta ya no calcula «quién remata».

Uso: python test_v328.py
"""
from __future__ import annotations

import json
import re
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


class _Caja:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class St:
    def __init__(self):
        self.session_state = {}
        self.textos = []
        self.en_analisis = False
        self.analisis = []

    def __getattr__(self, n):
        def f(*a, **k):
            t = str(a[0]) if a else ''
            if n == 'expander':
                self.en_analisis = 'Análisis' in t
                return _Caja()
            if n in ('markdown', 'caption', 'info'):
                self.textos.append(t)
                if self.en_analisis:
                    self.analisis.append(t)
            if n == 'columns':
                k_ = a[0] if a else 2
                return [_Caja() for _ in range(k_ if isinstance(k_, int) else len(k_))]
            if n == 'container':
                return _Caja()
            return False
        return f


def main():
    import modo_modelo as mm
    d = json.load(open('pronostico_dia.json', encoding='utf-8'))
    ps = [p for p in d['datos']['pronosticos']
          if not p.get('jugado') and p.get('deporte') == 'Fútbol'
          and p.get('prob') is not None and not p.get('sin_modelo')][:6]
    llamadas = []
    _qr = mm.quien_remata_tarjeta
    mm.quien_remata_tarjeta = lambda *a, **k: llamadas.append(1) or _qr(*a, **k)
    try:
        for p in ps:
            st = St()
            mm.tarjeta(st, p)
            txt = ' '.join(st.analisis)
            limpio = re.sub(r'<[^>]+>', ' ', txt)
            check('sin medir' not in limpio and 'destacado' not in limpio
                  and 'Remates' not in limpio and 'Quién remata' not in limpio,
                  '%s: el análisis no trae «sin medir», insignias ni remates' % p['partido'])
            todo = ' '.join(st.textos)
            check('Quién remata' not in todo, '%s: «quién remata» no sale en la tarjeta'
                  % p['partido'])
            filas = re.findall(r'<div class="mm-ck-fila">', txt)
            # v353 — más los tiros y los tiros a puerta (informativos): hasta 5
            check(1 <= len(filas) <= 5, '%s: de 1 a 5 líneas (%d)' % (p['partido'], len(filas)))
            lam = p.get('goles_lambda')
            if lam:
                check(('%.1f' % lam).replace('.', ',') in limpio,
                      '%s: los goles esperados son los de la razón (%.1f)' % (p['partido'], lam))
    finally:
        mm.quien_remata_tarjeta = _qr
    check(not llamadas, 'la tarjeta ya no calcula «quién remata» (%d llamadas)' % len(llamadas))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
