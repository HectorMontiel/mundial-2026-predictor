#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test del filtro de día (v298).

Esto decide QUE APUESTAS VE EL USUARIO, así que lo que se vigila es que no
esconda nada por accidente:

  · LAS DOS FORMAS DE LA FECHA. Los picks llegan con `fecha` normalizada o
    con `inicio`, que es una marca de tiempo Unix. Leer sólo una deja fuera
    media lista sin avisar — y es exactamente el motivo de que el usuario
    dijera «capa uno sólo me da apuestas de hoy».
  · UN MODO DESCONOCIDO DEVUELVE TODO, nunca lista vacía. Esconder picks es
    el fallo que esto viene a arreglar; no puede ser también su modo de
    fallar.
  · Y QUE NO LANCE, porque va dentro de un render.

Ejecutar:  python test_dia_picks.py
"""
import datetime as dt

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


HOY = dt.date(2026, 9, 21)


def probar_las_dos_formas_de_la_fecha():
    import dia_picks as dp

    # `fecha` ya normalizada
    check(dp.dia_de({'fecha': '2026-09-22'}) == '2026-09-22',
          'lee la fecha normalizada')
    check(dp.dia_de({'fecha': '2026-09-22T18:30:00Z'}) == '2026-09-22',
          'y con hora detrás se queda con el día')

    # `inicio` como marca de tiempo Unix — el camino del precálculo
    ts = dt.datetime(2026, 9, 22, 18, 30).timestamp()
    check(dp.dia_de({'inicio': ts}) == '2026-09-22',
          'lee `inicio` cuando es una marca de tiempo Unix')
    check(dp.dia_de({'inicio': str(int(ts))}) == '2026-09-22',
          'y también cuando viene como texto, que es como llega del tablero')

    # `fecha` basura pero `inicio` bueno: tiene que caer al segundo
    check(dp.dia_de({'fecha': 'no es una fecha', 'inicio': ts}) == '2026-09-22',
          'con la fecha rota usa `inicio` en vez de rendirse')


def probar_no_esconde_nada_por_accidente():
    import dia_picks as dp

    picks = [{'fecha': '2026-09-21'}, {'fecha': '2026-09-22'},
             {'fecha': '2026-09-23'}, {'sin': 'fecha'}]
    check(len(dp.solo_del_dia(picks, 'todo', HOY)) == 4,
          '«todo» devuelve los cuatro')
    check(len(dp.solo_del_dia(picks, 'cualquier cosa', HOY)) == 4,
          'un modo desconocido devuelve TODO, no una lista vacía')
    check(len(dp.solo_del_dia(picks, None, HOY)) == 4,
          'y None también')
    check(len(dp.solo_del_dia(picks, dp.HOY, HOY)) == 1, 'hoy es uno')
    check(len(dp.solo_del_dia(picks, dp.MANANA, HOY)) == 1, 'mañana es uno')
    check(not dp.solo_del_dia([], dp.HOY, HOY), 'sin picks, lista vacía')
    check(dp.solo_del_dia(None, dp.HOY, HOY) == [], 'None no rompe')


def probar_el_cambio_de_mes():
    """El 30 y el 31 son donde fallan estas cosas."""
    import dia_picks as dp

    fin = dt.date(2026, 9, 30)
    check(dp.fecha_del_modo(dp.MANANA, fin) == '2026-10-01',
          'el día siguiente al 30 de septiembre es el 1 de octubre')
    nochevieja = dt.date(2026, 12, 31)
    check(dp.fecha_del_modo(dp.MANANA, nochevieja) == '2027-01-01',
          'y el siguiente al 31 de diciembre cambia de año')


def probar_la_cuenta():
    import dia_picks as dp

    picks = [{'fecha': '2026-09-21'}, {'fecha': '2026-09-21'},
             {'fecha': '2026-09-22'}, {'fecha': '2026-10-05'}, 7, None]
    c = dp.cuenta(picks, HOY)
    check(c['todo'] == 4, 'la cuenta ignora lo que no es un pick (%s)' % c)
    check(c['hoy'] == 2 and c['mañana'] == 1, 'y cuenta bien cada día (%s)' % c)
    check(c['hoy'] + c['mañana'] <= c['todo'],
          'los días nunca suman más que el total')


def probar_no_lanza():
    import dia_picks as dp

    for malo in (None, 7, 'x', [], {}, {'fecha': None}, {'inicio': 'x'},
                 {'inicio': float('nan')}, {'inicio': 10 ** 20}):
        try:
            dp.dia_de(malo)
            dp.solo_del_dia([malo], dp.HOY, HOY)
            dp.cuenta([malo], HOY)
        except Exception as e:
            check(False, 'lanzó con %r: %r' % (malo, e))
    check(True, 'dia_de, solo_del_dia y cuenta aguantan basura')


def probar_la_pantalla_lo_usa():
    """Que `dashboard_ui` no se haya quedado con una copia paralela."""
    import re
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check('dia_picks' in src, 'la pantalla importa el módulo')
    # v299 — LA CAPA 1 ES OTRA LISTA, Y ERA LA QUE EL USUARIO MIRABA.
    #
    # La v298 puso el filtro sobre `_s1`/`_s2`, las secciones del
    # clasificador. El bloque titulado «🟢 Capa 1 — lo único con ventaja
    # medida» usa `_c1`, que no tocaba nadie, y por eso el usuario dijo
    # «cuando aplico el filtro a mañana no se aplica en capa 1».
    check("solo_del_dia(_c1, _modo_dia)" in src,
          'el bloque de Capa 1 se filtra por día')
    check("modo_de_dia(_c1, 'dia_del_dia')" in src,
          'y el mando se pinta ahí, que es lo primero que se ve')
    # Lo que importa no es cuántas veces se nombra la función —hay una
    # definición y un ayudante— sino que UNA SOLA la llame con esta clave.
    # Dos radios de Streamlit compartiendo `key` se pisan: el de abajo
    # reescribe la elección del de arriba en cada pasada.
    check(src.count("'dia_del_dia'") == 1,
          'un solo selector con la clave `dia_del_dia` (hay %d)'
          % src.count("'dia_del_dia'"))
    check("solo_del_dia(_s1, _modo_dia)" in src
          and "solo_del_dia(_s2, _modo_dia)" in src,
          'y las secciones del clasificador obedecen a ESE mando')
    # v300 — LA ESCALERA YA NO FILTRA, ENSEÑA EL DIA COMO COLUMNA.
    #
    # La v298 le puso un selector y el usuario seguía sin ver las de mañana:
    # un mando puede quedarse en la posición equivocada y esconderle media
    # lista sin que se note. Con la columna se ven los dos días a la vez y no
    # hay nada que ajustar. Además pidió expresamente no tener que
    # seleccionar nada en esa sección.
    check("'escalera_dia'" not in src,
          'la Escalera ya no tiene selector de día: el día es una columna')
    check('def _cuando(' in src,
          'y hay una columna «Cuándo» que dice Hoy o Mañana por fila')
    # ninguna de las dos pantallas puede tener su propia idea de qué es «hoy»
    propias = re.findall(r'date\.today\(\)', src)
    check(len(propias) <= 2,
          'la pantalla no reimplementa el cálculo del día (%d sitios)'
          % len(propias))


if __name__ == '__main__':
    print('=== 1. las dos formas de la fecha ===')
    probar_las_dos_formas_de_la_fecha()
    print('\n=== 2. no esconde nada por accidente ===')
    probar_no_esconde_nada_por_accidente()
    print('\n=== 3. el cambio de mes ===')
    probar_el_cambio_de_mes()
    print('\n=== 4. la cuenta del selector ===')
    probar_la_cuenta()
    print('\n=== 5. nunca lanza ===')
    probar_no_lanza()
    print('\n=== 6. la pantalla lo usa ===')
    probar_la_pantalla_lo_usa()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
