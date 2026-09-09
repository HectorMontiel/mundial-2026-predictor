#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostico de la queja: la vista de MANANA no cambia al aplicar el filtro.

Reproduce con AppTest la secuencia exacta del usuario:
  1. abrir Apuestas del Dia
  2. pulsar la vista MANANA
  3. tocar el filtro de deporte / el orden
  4. mirar en que vista se queda y que se pinta

No cambia nada del repositorio: es solo medicion.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
os.environ['PREFERENCIAS_USUARIO'] = os.path.join(
    tempfile.mkdtemp(prefix='prefs_diag_'), 'preferencias_usuario.json')

from streamlit.testing.v1 import AppTest

APP = 'dashboard_ui.py'
T = 1800


def subheaders(at):
    out = []
    for col in ('subheader', 'header'):
        try:
            out += [str(e.value) for e in getattr(at, col)]
        except Exception:
            pass
    return out


def sc(at):
    for w in at.segmented_control:
        if str(getattr(w, 'key', '')) == '_vista_principal':
            return w
    return None


def estado(at, etiqueta):
    try:
        v = str(at.session_state['_vista_principal'])
    except Exception:
        v = '???'
    print('  [%s] _vista_principal=%r' % (etiqueta, v), flush=True)
    for s in subheaders(at):
        if ('Partidos de' in s or 'MANANA' in s or 'manana' in s.lower()
                or 'hoy' in s.lower()):
            print('      subheader: %s' % s, flush=True)
    if at.exception:
        print('      EXCEPCION: %s' % at.exception[0].message, flush=True)
    return v


def main():
    at = AppTest.from_file(APP, default_timeout=T).run()
    print('arrancada', flush=True)
    at.selectbox(key='competencia').select('\U0001f48e Apuestas del Día').run()
    print('vista de apuestas cargada', flush=True)
    w = sc(at)
    if w is None:
        print('NO HAY selector de vista'); return 2
    print('  rotulos: %s' % list(w.options), flush=True)
    estado(at, 'inicio')

    # 2. pulsar MANANA
    w.set_value('manana').run()
    v = estado(at, 'tras pulsar manana')

    # cuantos partidos pinta la vista de manana
    for s in subheaders(at):
        if 'mañana' in s.lower():
            print('      -> %s' % s, flush=True)

    # 3. tocar el filtro de DEPORTE
    try:
        r = at.radio(key='_filtro_deporte')
        opciones = list(r.options)
        print('  deportes: %s' % opciones, flush=True)
        nuevo = [o for o in opciones if o != r.value][0]
        r.set_value(nuevo).run()
        estado(at, 'tras filtro deporte -> %s' % nuevo)
    except Exception as e:
        print('  sin filtro de deporte (%s)' % e, flush=True)

    # 4. tocar el ORDEN de la vista de manana
    try:
        s = at.selectbox(key='man_orden')
        ops = list(s.options)
        nuevo = [o for o in ops if o != s.value][0]
        s.set_value(nuevo).run()
        estado(at, 'tras orden manana -> %s' % nuevo)
    except Exception as e:
        print('  sin selector man_orden (%s)' % e, flush=True)

    # 5. filtro de alta probabilidad en manana
    try:
        c = at.checkbox(key='man_solo_altas')
        c.set_value(True).run()
        estado(at, 'tras solo alta probabilidad en manana')
        for s2 in subheaders(at):
            if 'mañana' in s2.lower():
                print('      -> %s' % s2, flush=True)
    except Exception as e:
        print('  sin casilla man_solo_altas (%s)' % e, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
