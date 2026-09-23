#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la fila compacta y del día de la Escalera y la Capa 1 (v302).

El usuario, con sus palabras:

    «El filtro de día en reto escalera y capa 1 sigue sin funcionar, me estás
     adelantando un día las cosas... quiero que también tengan la hora de cada
     partido. Las tarjetas están bien grandes... quiero un diseño sencillo: el
     partido, la cuota, la probabilidad, el semáforo y la hora del partido.»

    «Capa 1 quiero que se pueda minimizar... y que sólo cuando yo lo abra se
     despliegue.»

Lo que se vigila:

  · CADA FILA DICE EL DÍA, no sólo la hora. Un partido de mañana a las 10:00
    sin la palabra «Mañana» se lee como de hoy a las 10:00: ése era el
    «me estás adelantando un día».
  · EL DÍA ES EL DE CDMX. A las 22:43 de CDMX del 22 ya son las 04:43 UTC del
    23; un partido a las 23:00 CDMX es de HOY.
  · LA ESCALERA ARRANCA EN HOY, con el mando siempre visible —antes arrancaba
    en «todo» y desaparecía si hoy estaba vacío, que es como se mezclaban.
  · LA CAPA 1 OBEDECE A LA PESTAÑA de Apuestas del Día (Hoy / Mañana /
    Pasado) en vez de tener un mando propio que arrancaba en «todo».
  · LA CAPA 1 VA PLEGADA, y la Escalera ya no pinta tres `st.metric` por
    apuesta.

Ejecutar:  python test_vistas_compactas.py
"""
import datetime as dt
import re

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


HOY = dt.date(2026, 9, 22)


def _ts(y, m, d, hh, mm):
    """Marca de tiempo UTC en TEXTO, que es como llega del tablero."""
    return str(int(dt.datetime(y, m, d, hh, mm,
                               tzinfo=dt.timezone.utc).timestamp()))


def probar_el_dia_de_cada_fila():
    import vista_compacta as vc
    # 05:00 UTC del 23 son las 23:00 CDMX del 22: es de HOY para el usuario
    p = {'inicio': _ts(2026, 9, 23, 5, 0), 'cuota': 2.1, 'prob': 0.5,
         'partido': 'Fukuoka vs Seibu', 'apuesta': 'Gana Seibu'}
    check(vc.dia_relativo(p, HOY) == 'Hoy',
          'las 05:00 UTC del 23 son HOY en CDMX (%s)' % vc.dia_relativo(p, HOY))
    check(vc.hora(p) == '23:00', 'y la hora es la de CDMX (%s)' % vc.hora(p))
    q = {'inicio': _ts(2026, 9, 23, 16, 0), 'cuota': 2.0}
    check(vc.dia_relativo(q, HOY) == 'Mañana', 'las 16:00 UTC del 23 son mañana')
    r = {'inicio': _ts(2026, 9, 24, 18, 45), 'cuota': 2.0}
    check(vc.dia_relativo(r, HOY) == 'Pasado', 'y las del 24, pasado')
    s = {'inicio': _ts(2026, 9, 28, 18, 45), 'cuota': 2.0}
    check(vc.dia_relativo(s, HOY) == '28 sep', 'más lejos, la fecha corta')
    check(vc.dia_relativo({'cuota': 2.0}, HOY) == '',
          'sin fecha no inventa un día')


def probar_la_fila():
    import vista_compacta as vc
    p = {'inicio': _ts(2026, 9, 23, 1, 0), 'cuota': 2.05, 'prob': 0.52,
         'partido': 'Grorud vs Moss', 'apuesta': 'Gana Grorud',
         'casa': 'Calientemx', 'semaforo': {'nivel': 'verde',
                                             'etiqueta': 'Métela'}}
    f = vc.fila(p, HOY)
    check(f and f['icono'] == '🟢', 'el semáforo verde sale verde')
    check(f and f['dia'] == 'Hoy' and f['hora'] == '19:00',
          'la fila lleva día y hora (%s %s)' % (f and f['dia'], f and f['hora']))
    check(vc.fila({'cuota': None, 'partido': 'x'}, HOY) is None,
          'sin cuota no hay fila: no se apuesta a lo que no tiene precio')
    h = vc.html_lista([p], HOY)
    for trozo in ('Hoy', '19:00', 'Grorud vs Moss', 'Gana Grorud', '2.05',
                  '52 %', '🟢', 'Calientemx'):
        check(trozo in h, 'el HTML enseña «%s»' % trozo)
    check(vc.html_lista([], HOY) == '', 'lista vacía, HTML vacío')
    # la combinada se lee como sus dos patas
    c = dict(p, patas=[{'texto': 'Gana Grorud', 'cuota': 1.4},
                       {'texto': 'Más de 2.5', 'cuota': 1.5}])
    check('Gana Grorud + Más de 2.5' in vc.html_lista([c], HOY),
          'la combinada enseña sus dos patas')
    # un nombre con HTML no rompe la página
    m = dict(p, partido='<b>X</b> vs Y')
    check('<b>X</b>' not in vc.html_lista([m], HOY), 'escapa el HTML')
    # la forma y la media de goles siguen enseñándose (en el aviso de la
    # fila): `forma_equipos` se quedó sin importadores en la v300 y el
    # auditor lo marcó como bandera roja
    src_vc = open('vista_compacta.py', encoding='utf-8').read()
    check('import forma_equipos' in src_vc,
          'la fila enseña la forma del equipo (forma_equipos enganchado)')
    # la probable lleva su propio icono
    pr = dict(p, semaforo=None, probable='ambos')
    check(vc.fila(pr, HOY)['icono'] == '🎯', 'la probable sale con 🎯')


def probar_el_mando_de_dia():
    import dia_picks as dp
    check(dp.fecha_del_modo(dp.PASADO, HOY) == '2026-09-24',
          'pasado mañana existe como modo')
    check(dp.modo_de_vista('manana') == dp.MANANA
          and dp.modo_de_vista('pasado') == dp.PASADO
          and dp.modo_de_vista('hoy') == dp.HOY,
          'la pestaña de Apuestas del Día se traduce a modo de día')
    check(dp.modo_de_vista('combi') == dp.HOY
          and dp.modo_de_vista(None) == dp.HOY,
          'y cualquier otra pestaña cae en HOY, nunca en «todo»')
    c = dp.cuenta([{'fecha': '2026-09-22'}, {'fecha': '2026-09-24'}], HOY)
    check(c.get(dp.PASADO) == 1, 'la cuenta incluye pasado')


def probar_la_pantalla():
    src = open('dashboard_ui.py', encoding='utf-8').read()
    i = src.find('def render_escalera')
    j = src.find('\ndef ', i + 10)
    esc = src[i:j]
    check('vista_compacta' in esc, 'la Escalera pinta con la fila compacta')
    check('st.metric' not in esc,
          'y ya no pinta tres métricas por apuesta')
    check('st.container(border=True)' not in esc,
          'ni una tarjeta con borde por opción')
    check("dia_de_vista" in src or "modo_de_vista" in src,
          'la Capa 1 sigue a la pestaña Hoy/Mañana/Pasado')
    m = re.search(r"(_rot_c1) = \(?'🟢 Capa 1", src)
    check(m is not None and 'st.expander(_rot_c1, expanded=False)' in src,
          'la Capa 1 va en un desplegable CERRADO, con la cuenta en el rótulo')
    k = src.find('def modo_de_dia')
    md = src[k:src.find('\ndef ', k + 10)]
    check("'todo (%d)'" not in md and '_dp.HOY' in md,
          'el mando de día arranca en HOY y no ofrece «todo»')
    check('if not (c[' not in md,
          'y no se esconde cuando un día está vacío')


if __name__ == '__main__':
    print('=== 1. el día de cada fila, en CDMX ===')
    probar_el_dia_de_cada_fila()
    print('\n=== 2. la fila ===')
    probar_la_fila()
    print('\n=== 3. el mando de día ===')
    probar_el_mando_de_dia()
    print('\n=== 4. la pantalla lo usa ===')
    probar_la_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
