#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v415 — en las copas, las estadísticas REALES de la liga de cada equipo.

  El usuario: «Como vs Manchester United no trae las estadísticas ni el H2H…
  quiero que todos tengan, no estimaciones». En la Champions Como tenía 2
  partidos (con menos de 3 no se calcula) y los del United eran de 2023. Ahora
  se juntan los partidos de la competición con los de la liga de cada equipo.

Ejecutar:  python test_v415.py
"""
import os

import pandas as pd

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def fila(fecha, h, a, gh, ga, ch, ca):
    return {'date': fecha, 'home_team': h, 'away_team': a, 'home_goals': gh, 'away_goals': ga,
            'home_corners': ch, 'away_corners': ca}


def probar():
    import catalogo_equipos as ce
    import errores_web as ew
    import name_mapper as nm
    import panel_equipos as pe
    copa = pd.DataFrame([fila('2023-10-03', 'Manchester United', 'Galatasaray', 2, 3, 4, 5),
                         fila('2026-10-13', 'Atlético Madrid', 'Manchester United', 1, 1, 6, 3),
                         fila('2026-10-14', 'Como', 'Feyenoord', 2, 0, 7, 2)])
    serie_a = pd.DataFrame([fila('2026-09-%02d' % d, 'Como', 'Rival%d' % d, 2, 1, 6, 4) for d in range(1, 9)])
    premier = pd.DataFrame([fila('2026-09-%02d' % d, 'Man United', 'Otro%d' % d, 1, 1, 5, 5) for d in range(1, 9)])
    viejos = (ce.nombre_en_su_liga, ce.liga_de, pe._historico, nm.mapear)
    ce.nombre_en_su_liga = lambda e: {'Como': ('serie_a', 'Como')}.get(e)
    ce.liga_de = lambda e: {'Como': 'serie_a', 'Manchester United': 'premier'}.get(e)
    pe._historico = lambda c: {'serie_a': serie_a, 'premier': premier}.get(c)
    nm.mapear = lambda n, cat, **k: 'Man United' if n == 'Manchester United' and 'Man United' in cat else None
    try:
        h = ew._con_sus_ligas(copa, 'champions', ('Como', 'Manchester United'))
        antes = pd.Timestamp('2026-10-21')
        pl, pv = ew._promedios(h, 'Como', antes), ew._promedios(h, 'Manchester United', antes)
        check(pl is not None and pl['n'] == 9, 'Como (1 de copa) se completa con sus 8 de liga: %s' % (pl or {}).get('n'))
        check(pv is not None and pv['n'] == 10 and pv['cor'] < 5.5,
              'el United toma sus partidos RECIENTES de la Premier («Man United»), no los de 2023')
        check((h['home_team'] == 'Man United').sum() == 0, 'el nombre de la liga se unifica con el de la copa')
        solo = ew._con_sus_ligas(serie_a, 'serie_a', ('Como', 'Rival1'))
        check(len(solo) == len(serie_a), 'en un partido de liga no cambia nada')
    finally:
        ce.nombre_en_su_liga, ce.liga_de, pe._historico, nm.mapear = viejos
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('No se han enfrentado en nuestros registros.' in app, 'sin H2H se dice, en vez de esconder la sección')
    js = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check("if (!yo.perfil) { c.innerHTML = '<span class=\"saldo\" title=\"Tus monedas\">🪙 …</span>" in js,
          'v416: sin perfil la cabecera no inventa el correo ni «0 monedas»')
    check("if (!data) { if (!yo.perfil) yo.perfil = perfilGuardado(yo.user.id); return; }" in js,
          'v416: una consulta vacía al volver a la app no borra la copia del perfil')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
