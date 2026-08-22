#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v152 — VALIDACIÓN DE RENDER DIRIGIDA: las vistas que tocó el cambio, y nada más.

Por qué existe
--------------
`smoke_botones.py` abre las ocho vistas y pulsa los botones caros de cada una.
Es la red más completa que tiene el proyecto y sigue siendo la que manda para
los cambios de motor. Lo que no puede ser es la puerta de CADA push: medido en
esta máquina el 2026-08-22, no terminó en 55 minutos en dos intentos seguidos
(EXIT 124 las dos veces), y sólo la vista de «Apuestas del Día» tarda 254 s.

Una puerta que cuesta media jornada deja de usarse, y una puerta que no se usa
no protege nada. Así que el reparto es:

    test_catalogo_y_cuotas.py   siempre, sin excepción
    valida_render.py <vistas>   cuando cambia la interfaz  ← esto
    smoke_botones.py            cuando cambia el motor, y una vez por semana

LO QUE NO SE RELAJA
-------------------
Que el render se valide. `py_compile` y el AST no ven un `UnboundLocalError`
dentro de un `if st.button(...)`: eso sólo lo ve AppTest, y ésa es la lección
que hizo nacer el smoke. Lo que cambia es el ALCANCE —las vistas que el cambio
toca en vez de las ocho— no el método.

Y no basta con «no lanzó excepción»: una vista puede renderizar vacía sin
lanzar nada. Por eso cada vista puede pedir textos que TIENEN que aparecer.

Uso
---
    python valida_render.py                      # las vistas de siempre
    python valida_render.py "Apuestas del Día"   # una vista suelta (subcadena)
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
from streamlit.testing.v1 import AppTest

APP = 'dashboard_ui.py'

# vista -> textos que TIENEN que salir en pantalla tras cargarla.
#
# Se comprueban por CONTENIDO y no por la etiqueta de la pestaña: que una
# pestaña exista en el árbol no demuestra que su contenido se haya pintado, y
# es justo el contenido lo que puede reventar.
VISTAS = {
    '💎 Apuestas del Día': [
        # el Modo Modelo, por la advertencia que sólo pinta él
        'probabilidad del modelo',
        '4,66',
    ],
    '🏴 Premier League': [],      # rama de córners OBSERVADOS
    '🇲🇽 Liga MX': [],            # rama de córners SIN observar
}

FALLOS = []


def check(cond, msg):
    print(('OK    ' if cond else 'FALLO ') + msg, flush=True)
    if not cond:
        FALLOS.append(msg)


def textos(at):
    """Todo lo que quedó escrito en pantalla, en una sola cadena."""
    trozos = []
    for coleccion in ('markdown', 'caption', 'subheader', 'header', 'info',
                      'warning', 'error', 'text'):
        try:
            trozos += [str(e.value) for e in getattr(at, coleccion)]
        except Exception:
            pass
    return ' \n '.join(trozos)


def valida(vista, exigidos, timeout=900):
    t0 = time.time()
    at = AppTest.from_file(APP, default_timeout=timeout).run()
    if at.exception:
        check(False, f'{vista}: la app no arranca ({at.exception[0].message})')
        return
    try:
        at.selectbox(key='competencia').select(vista).run()
    except Exception as e:
        check(False, f'{vista}: no se pudo seleccionar ({e})')
        return
    print(f'   [{vista}] {time.time() - t0:.1f} s', flush=True)
    if at.exception:
        check(False, f'{vista}: excepción al cargar '
                     f'({at.exception[0].message})')
        return
    check(True, f'{vista} carga sin excepciones')
    t = textos(at)
    for exigido in exigidos:
        check(exigido in t,
              f'{vista}: «{exigido}» aparece en pantalla')


def main():
    pedidas = sys.argv[1:]
    if pedidas:
        objetivo = {v: e for v, e in VISTAS.items()
                    if any(p.lower() in v.lower() for p in pedidas)}
        if not objetivo:
            print(f'Ninguna vista conocida casa con {pedidas}. '
                  f'Conocidas: {list(VISTAS)}')
            return 2
    else:
        objetivo = VISTAS
    for vista, exigidos in objetivo.items():
        valida(vista, exigidos)
    print()
    print(f'{len(FALLOS)} FALLOS' if FALLOS else 'TODO OK')
    for f in FALLOS:
        print('  - ' + f)
    return 1 if FALLOS else 0


if __name__ == '__main__':
    sys.exit(main())
