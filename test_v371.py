#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v371.

El usuario (11-oct), con un boleto de 4 patas que salió 1 ✅ 3 ❌: «tener 3/4
malas es inaceptable; da apuestas sencillas de cuota mínima 1,30; inclínate a
lo que diga la casa, también quién gana»; y «quiero poder seguir ese boleto y
eliminar los que ya no quiera; en carrusel».

Lo que se vigila:
  1. EL MÉTODO CASA 70/130 (`sencillas`): sólo patas a cuota 1,30-1,70 con la
     casa al 70 %+, una por partido, de la casa más alta a la más baja; sin
     tarjetas, córners de equipo, combinadas ni hándicap; el ganador entra.
  2. Cada pata se LIQUIDA sola (goles, córners, ganador) en «Mis boletos».
  3. «Mis boletos»: quitar uno, el resumen de cómo va, y el carrusel.
  4. El armador viejo queda plegado y avisado; lo medido queda guardado.

Ejecutar:  python test_v371.py
"""
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


TAB = {'1x2': {'home': 0.72, 'draw': 0.17, 'away': 0.11},
       '1x2_cuotas': {'home': 1.32, 'draw': 5.5, 'away': 8.0},
       'goles': {'1.5': {'p': 0.75, 'mas': 1.30, 'menos': 3.4},
                 '2.5': {'p': 0.55, 'mas': 1.75, 'menos': 2.0},
                 '1.75': {'p': 0.72, 'mas': 1.33, 'menos': 3.0}},
       'goles_home': {'0.5': {'p': 0.85, 'mas': 1.12, 'menos': 5.0}},
       'corners': {'7.5': {'p': 0.71, 'mas': 1.31, 'menos': 3.1},
                   '12.5': {'p': 0.27, 'mas': 3.2, 'menos': 1.29}},
       'corners_home': {'3.5': {'p': 0.74, 'mas': 1.31, 'menos': 3.0}},
       'tarjetas': {'2.5': {'p': 0.80, 'mas': 1.32, 'menos': 3.0}}}


def probar_regla():
    import mercado_implicito as mi
    import sencillas as se
    v = mi.del_partido
    mi.del_partido = lambda h, a, **k: TAB
    try:
        p = {'partido': 'Local FC vs Visita FC', 'deporte': 'Fútbol', 'clave_liga': 'x',
             'inicio': '2099-01-01T12:00:00Z', 'fecha': '2099-01-01'}
        pats = se.patas_del_partido(p)
        ap = [x['apuesta'] for x in pats]
        check(ap[0] == 'Goles: Más de 1.5' and 'Gana Local FC' in ap and 'Córners: Más de 7.5' in ap,
              'entran las de 1,30+ con la casa al 70 %%+, de la más alta a la más baja (%s)' % ap)
        check(not any('1.75' in a or 'Tarjetas' in a or 'Córners Local' in a
                      or 'Goles Local FC' in a or '12.5' in a for a in ap),
              'fuera líneas de cuarto, tarjetas, córners de equipo, cuota < 1,30 y casa < 70 %')
        check(all(se.CUOTA_MIN <= x['cuota'] <= se.CUOTA_MAX and x['p_casa'] >= se.CASA_MIN
                  and x['bloque'] and x['origen'] == 'casa70' for x in pats),
              'cada pata con su cuota, su casa y lo que necesita para liquidarse')
        dd = se.del_dia([p, dict(p, partido='Otro FC vs Rival FC')], ahora=0)
        check(len(dd) == 2 and len({x['partido'] for x in dd}) == 2, 'una por partido')
        b = se.boleto(dd, 2)
        check(b and abs(b['prob'] - 0.78 ** 2) < 1e-9 and b['momio'] > 1.6, 'el boleto multiplica')
        check('salió entero' in se.medido(4) and '10 de 19' in se.medido(4), 'con lo medido')
    finally:
        mi.del_partido = v


def probar_liquidar():
    import pronosticos_guardados as pg
    p = {'partido': 'Local FC vs Visita FC', 'goles_home': 2, 'goles_away': 0,
         'stats_partido': {'corners_home': 6, 'corners_away': 3}}
    filas = [{'apuesta': 'Goles: Más de 1.5', 'bloque': 'goles', 'etiqueta': 'Total', 'veredicto': 'meter'},
             {'apuesta': 'Córners: Más de 7.5', 'bloque': 'corners', 'etiqueta': 'Total', 'veredicto': 'meter'},
             {'apuesta': 'Gana Local FC', 'bloque': 'resultado', 'etiqueta': 'Ganador', 'veredicto': 'meter'},
             {'apuesta': 'Goles Visita FC: Más de 0.5', 'bloque': 'goles_equipo', 'etiqueta': 'Visitante',
              'veredicto': 'meter'}]
    est = [f['estado'] for f in pg.validar(p, filas=filas)]
    check(est == [pg.CUMPLIDO, pg.CUMPLIDO, pg.CUMPLIDO, pg.FALLADO],
          'las patas se liquidan solas: goles ✅, córners 9 ✅, gana local ✅, visita 0 ❌ (%s)' % est)


def probar_boletos():
    import sonadora_motor as sm
    import sonadora_ui as su
    tmp = tempfile.mkdtemp()
    ruta = os.path.join(tmp, 'p.json')
    sm.olvidar_parlays(ruta)
    sm.registrar_parlay({'n_patas': 1, 'patas': [{'id': 'a', 'partido': 'A vs B'}]}, '2099-01-01',
                        ruta=ruta, detalle=[{'partido': 'A vs B', 'apuesta': 'x', 'origen': 'casa70'}])
    reg = sm.parlays_activos(ruta)[0]
    check(reg['detalle'][0].get('origen') == 'casa70', 'el boleto recuerda de qué método salió')
    check(sm.quitar_parlay(reg['registrado'], ruta) and sm.parlays_activos(ruta) == [],
          'quitar un boleto lo deja de seguir')
    check(not sm.quitar_parlay('no-existe', ruta), 'quitar uno que no existe no rompe nada')
    v = su.estado_patas
    su.estado_patas = lambda b, r, ahora=None: b['filas']
    try:
        rs = su.resumen_boletos([{'filas': [{'estado': 'verde'}, {'estado': 'verde'}]},
                                 {'filas': [{'estado': 'verde'}, {'estado': 'roja'}]},
                                 {'filas': [{'estado': 'verde'}, {'estado': '?'}]}], {})
    finally:
        su.estado_patas = v
    check(rs == {'boletos': 3, 'enteros': 1, 'perdidos': 1, 'vivos': 1, 'verdes': 4, 'rojas': 1},
          'el resumen: enteros, con rojas y en juego (%s)' % rs)
    check(su._vigencia_pata({'origen': 'casa70'}, None)['texto'].startswith('⏳ por jugar'),
          'una pata del método por jugar no se juzga con la tarjeta')
    src = open('sonadora_ui.py', encoding='utf-8').read()
    check("key='son_mb_ant'" in src and "key='son_mb_sig'" in src and 'Boleto <b>%d</b> de %d' in src
          and '🗑️ Dejar de seguir este boleto' in src, 'Mis boletos en carrusel, con quitar')
    check("_seguir(st, b['patas'], dia, 'son_se_seguir', se.ORIGEN)" in src
          and "_seguir(st, b['patas'], None, 'son_bl_seguir', 'largo')" in src,
          '«📌 Seguir este boleto» en las sencillas y en el boleto largo')
    check("'⚡ Armar con los picks de «Apuestas del Día»',\n                     expanded=False" in src
          and 'Criterio viejo' in src, 'el armador viejo, plegado y avisado')


def probar_medicion():
    r = json.load(open('_v371e_umbral.json', encoding='utf-8'))
    f = r['casa >= 0.70']
    check(f['A']['acierto'] >= 0.77 and f['B']['acierto'] >= 0.76 and f['todo']['gan_100'] > 0,
          'lo medido queda guardado: 80 / 77 % y ganancia en el total')


if __name__ == '__main__':
    print('=== 1. la regla ===')
    probar_regla()
    print('\n=== 2. liquidar ===')
    probar_liquidar()
    print('\n=== 3. mis boletos ===')
    probar_boletos()
    print('\n=== 4. lo medido ===')
    probar_medicion()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
