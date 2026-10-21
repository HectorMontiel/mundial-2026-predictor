#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v390: la identidad (logo, colores) y «Mi cuenta» que ya no se traba."""
import os
FALLOS = []


def check(c, m):
    print(('OK   ' if c else 'FALLO') + ' ' + m)
    if not c:
        FALLOS.append(m)


def probar():
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check('lock: async (_n, _t, fn) => await fn()' in cu, 'sin el candado de sesión que se trababa en el celular')
    check('const aTiempo = ' in cu and "aTiempo(sb.rpc('enlace_vip'), 5000" in cu, 'ninguna consulta espera más de 5 s')
    check('Cargando…</p><button class="salir" data-salir>Cerrar sesión</button>' in cu,
          'Mi cuenta se abre al instante con Cerrar sesión')
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check('marca/logo-96.png' in html and 'marca/favicon.png' in html and 'og:image' in html, 'el logo, el favicon y la portada')
    check(all(os.path.exists(os.path.join('web', 'marca', f)) for f in ('logo-96.png', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png')),
          'los íconos de la marca están')
    css = open(os.path.join('web', 'estilo.css'), encoding='utf-8').read()
    check('--marca: #3ddc84' in css, 'los colores de la marca')


def probar_filtros():
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('estado.deportes = new Set(' in app and 'alterna(estado.niveles' in app and 'listaBase().filter(pasaDep)' in app,
          'deportes y niveles de selección múltiple; los destacados respetan el deporte')
    check('estado.deporte ' not in app and 'estado.nivel ' not in app, 'no queda el filtro viejo de uno solo')
    check('estado.vivoCorriendo' in app and 'gs.map(seguro(filaPartido))' in app and 'fila.outerHTML = filaPartido(g)' in app,
          'lo en vivo no se pisa, un partido raro no rompe la lista y abrir uno sólo redibuja ese')
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    # v421 — la estrella sigue cambiando al instante (en todas las copias del botón)
    check("b.textContent = !sigo ? '★ Siguiendo' : '☆ Seguir'" in cu, 'Seguir responde al instante')


if __name__ == '__main__':
    probar()
    probar_filtros()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
