#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v468 — la IA sin repetir los promedios, «Cerrar» pegado abajo, cerrar la liga cierra sus
tarjetas, ligas de la A a la Z y «Por hora»."""
import os
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    css = open(os.path.join('web', 'estilo.css'), encoding='utf-8').read()
    ia = app[app.index('function iaHtml('):app.index('function iaHtml(') + 6000]
    check("filaStat(et, ctx.sl[k], ctx.sv[k], true)" not in ia, 'v468: la IA ya no repite los promedios de «Antes del partido»')
    check('class="pf-cerrar"' in app and 'data-cerrar-pf="1"' in app and '.pf-cerrar { position: sticky;' in css
          and '.liga-bloque, .partido-fila.deslizable { overflow: clip; }' in css,
          'v468: «Cerrar» se queda pegado abajo mientras se lee la tarjeta (overflow clip: hidden lo impedía)')
    check("if (ligaDe(g[0]) === l) estado.abiertos.delete(k)" in app, 'v468: al cerrar la liga se cierran todas sus tarjetas')
    check("localeCompare(b[0].replace(/^🎾 /, ''), 'es'" in app and 'return alfabetico(m);' in app, 'v468: las ligas de la A a la Z')
    check('data-ord="hora"' in app and "estado.porHora = t.dataset.ord === 'hora'" in app and 'class="liga-bloque por-hora"' in app
          and 'pf-lig' in app, 'v468: «Por hora» junta todos los partidos por hora, cada uno con su liga')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
