#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Que avisos de error saca la vista de la Bundesliga (y con que comparar).

El usuario dice «la Bundesliga me marca algunos errores» sin recordar cuales.
Esto abre la vista con AppTest y recoge TODO lo que suena a fallo: `st.error`,
`st.warning`, las excepciones, y los `caption` que contienen las formulas que la
aplicacion usa para decir «esto no se pudo». Se abre tambien LaLiga como
control: un aviso que sale en las dos no es de la Bundesliga.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
os.environ['PREFERENCIAS_USUARIO'] = os.path.join(
    tempfile.mkdtemp(prefix='prefs_bund_'), 'preferencias_usuario.json')

from streamlit.testing.v1 import AppTest

APP = 'dashboard_ui.py'
SOSPECHOSAS = ('no disponible', 'no se pudo', 'error', 'falta', 'sin datos',
               'no existe', 'vacío', 'vacio', 'fallo', 'falló', 'n/d',
               'no hay', 'aún no', 'aun no')


def avisos(at):
    out = []
    for col in ('error', 'warning'):
        for e in getattr(at, col, []):
            out.append(('%s' % col.upper(), str(e.value)))
    for col in ('caption', 'info', 'markdown'):
        for e in getattr(at, col, []):
            t = str(e.value)
            if any(s in t.lower() for s in SOSPECHOSAS):
                out.append((col, t))
    return out


def mira(vista):
    at = AppTest.from_file(APP, default_timeout=1200).run()
    at.selectbox(key='competencia').select(vista).run()
    print('=' * 70)
    print(vista)
    print('=' * 70)
    if at.exception:
        print('EXCEPCION: %s' % at.exception[0].message)
    vistos = set()
    for tipo, t in avisos(at):
        t = ' '.join(t.split())
        if t in vistos:
            continue
        vistos.add(t)
        print('  [%s] %s' % (tipo, t[:250]))
    return at


def main():
    for vista in ('\U0001f1e9\U0001f1ea Bundesliga', '\U0001f1ea\U0001f1f8 LaLiga'):
        try:
            mira(vista)
        except Exception as e:
            print('%s: no se pudo abrir (%s: %s)' % (vista, type(e).__name__, e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
