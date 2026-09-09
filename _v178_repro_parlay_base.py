#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reproduce en minutos lo que al smoke le cuesta una hora:

    abrir «Apuestas del Dia» -> recorrer las cuatro vistas -> pulsar
    «🔄 Actualizar ahora» estando en la ultima  ->  KeyError: parlay_base

DOS DETALLES SIN LOS CUALES NO SALE, y los dos costaron una pasada del smoke:

  1. `parlay_base` es el selectbox de «Arma tu combinada» y **solo se crea si la
     Seccion 1 trae algo**. La mayoria de los dias esta vacia, el widget ni
     existe y no hay nada que perder — por eso la v177.2 no pudo reproducirlo a
     mano. Aqui se fuerza envolviendo el barrido.
  2. El smoke pulsa el objeto boton que capturo en la carga INICIAL, no uno
     recien buscado en la pasada actual.

Se corre igual en un `git worktree` con el codigo viejo, que es como se sabe si
un fallo del smoke es nuevo o venia de antes.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
os.environ['PREFERENCIAS_USUARIO'] = os.path.join(
    tempfile.mkdtemp(prefix='prefs_repro_'), 'preferencias_usuario.json')

import guardia_barrido

PICK = {
    'deporte': 'Fútbol', 'partido': 'Equipo A vs Equipo B',
    'apuesta': 'Gana Equipo A', 'cuota': 1.85, 'prob': 0.62, 'ev': 0.147,
    'liga': 'Premier League', 'clave_liga': 'premier', 'casa': 'Pinnacle',
    'canal': 'precio_local', 'motivo': 'fila de prueba', 'n_casas': 3,
    'fecha': '2026-09-09', 'es_hoy': True,
}

_original = guardia_barrido.barrido


def _con_seccion1(*a, **k):
    r = _original(*a, **k) or {}
    if isinstance(r, dict):
        r = dict(r)
        r['seccion1'] = list(r.get('seccion1') or []) + [dict(PICK)]
    return r


guardia_barrido.barrido = _con_seccion1

from streamlit.testing.v1 import AppTest

APP = 'dashboard_ui.py'


def main():
    at = AppTest.from_file(APP, default_timeout=1800).run()
    at.selectbox(key='competencia').select('\U0001f48e Apuestas del Día').run()
    if at.exception:
        print('la pantalla no carga: %s' % at.exception[0].message)
        return 2
    try:
        print('parlay_base al cargar: %r' % (at.session_state['parlay_base'],))
    except Exception as e:
        print('parlay_base NO existe al cargar (%s) — la Seccion 1 sigue '
              'vacia y esta prueba no sirve' % type(e).__name__)
        return 2
    # EL BOTON SE CAPTURA AHORA, como hace el smoke, y se pulsa al final.
    boton = [x for x in at.button
             if str(getattr(x, 'key', '')) == 'refresh_alpha']
    if not boton:
        print('no hay boton refresh_alpha')
        return 2
    boton = boton[0]
    # EL RECORRIDO DEL SMOKE: las cuatro vistas en orden antes de pulsar.
    for _clave in ('hoy', 'manana', 'combi', 'estado'):
        sc = [w for w in at.segmented_control
              if str(getattr(w, 'key', '')) == '_vista_principal'][0]
        sc.set_value(_clave).run()
        if at.exception:
            print('FALLO al abrir la vista %r: %s'
                  % (_clave, at.exception[0].message))
            return 1
        try:
            _hay = repr(at.session_state['parlay_base'])
        except Exception as e:
            _hay = 'PERDIDO (%s)' % type(e).__name__
        print('  vista %-7s -> estado %r · parlay_base %s'
              % (_clave, at.session_state['_vista_principal'], _hay))
    try:
        boton.click().run()
    except Exception as e:
        print('FALLO al pulsar: %s: %s' % (type(e).__name__, e))
        return 1
    if at.exception:
        print('FALLO tras pulsar: %s' % at.exception[0].message)
        return 1
    print('OK: se pudo pulsar «Actualizar ahora» estando en «estado»')
    return 0


if __name__ == '__main__':
    sys.exit(main())
