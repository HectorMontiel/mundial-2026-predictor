#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v347.

El usuario: «las dos más probables en la tarjeta principal; las demás que
también se meten (tiros, tarjetas, córners…) en el desplegable de cada
partido con su probabilidad, sin bajar el 80 % de verdes».

Lo que se vigila:
  1. `otras_que_se_meten`: sólo lo que pasa la MISMA regla que arriba, una por
     mercado y lado, sin repetir las de arriba ni su mercado.
  2. El desplegable «➕ También se meten (N)», con lo medido.
  3. El precálculo lo deja hecho y la tarjeta lo lee.
  4. Lo medido: las extras aciertan cerca del 80 % y no entran en el marcador.

Ejecutar:  python test_v347.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


class _St:
    def __init__(self):
        self.txt, self.plegados = [], []

    def markdown(self, t, **k):
        self.txt.append(str(t))

    def caption(self, t, **k):
        self.txt.append(str(t))

    def expander(self, rot, **k):
        self.plegados.append(rot)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def probar_funcion():
    import modo_modelo as mm
    import valor_apuesta as va
    import veredicto_pick as vp
    cand = [{'mercado': 'Goles', 'etiqueta': 'Total', 'apuesta': 'Goles: Más de 1.5',
             'prob': 0.76, 'cuota': 1.25, 'bloque': 'goles', 'linea': 1.5},
            {'mercado': 'Córners', 'etiqueta': 'Total', 'apuesta': 'Córners: Más de 7.5',
             'prob': 0.78, 'cuota': 1.22, 'bloque': 'corners', 'linea': 7.5},
            {'mercado': 'Córners', 'etiqueta': 'Total', 'apuesta': 'Córners: Más de 6.5',
             'prob': 0.84, 'cuota': 1.12, 'bloque': 'corners', 'linea': 6.5},
            {'mercado': 'Tarjetas', 'etiqueta': 'Total', 'apuesta': 'Tarjetas: Más de 2.5',
             'prob': 0.55, 'cuota': 1.5, 'bloque': 'tarjetas', 'linea': 2.5}]
    o_c, o_e, o_m, o_f = va.candidatos, vp.evaluar, mm._motivo_fuera, mm._enriquece
    try:
        va.candidatos = lambda p, b: cand
        mm._enriquece = lambda p, f, i: dict(f)
        vp.evaluar = lambda c, con_contexto=False: {
            'veredicto': vp.METER if c['prob'] >= 0.65 else vp.NO_METER,
            'prob_ajustada': c['prob']}
        mm._motivo_fuera = lambda v, f, l: ('fuera de franja'
                                            if v['pick']['prob'] > 0.80 else None)
        ya = [{'apuesta': 'Goles: Más de 1.5', 'mercado': 'Goles', 'etiqueta': 'Total'}]
        o = mm.otras_que_se_meten({'partido': 'A vs B'}, {}, ya)
        ap = [x['apuesta'] for x in o]
        check(ap == ['Córners: Más de 7.5'],
              'sólo la que pasa la regla, una por mercado, sin repetir las de '
              'arriba (%s)' % ap)
    finally:
        va.candidatos, vp.evaluar, mm._motivo_fuera, mm._enriquece = o_c, o_e, o_m, o_f
    st = _St()
    mm._bloque_otras(st, [{'apuesta': 'Córners: Más de 7.5', 'prob': 0.78, 'cuota': 1.22}])
    t = ''.join(st.txt)
    check(st.plegados == ['➕ También se meten (1)'] and '78 %' in t and '@1.22' in t,
          'el desplegable con su probabilidad y su cuota')
    check('79 %' in t and 'No cuentan en el marcador' in t, 'y lo medido')
    st = _St()
    mm._bloque_otras(st, [])
    check(not st.plegados, 'sin nada, no se pinta')


def probar_conexion():
    src = open('modo_modelo.py', encoding='utf-8').read()
    dd = open('decisiones_dia.py', encoding='utf-8').read()
    check('_bloque_otras(st, _otras)' in src and '_dd_o.otras_de_pick(pick)' in src,
          'la tarjeta pinta las otras (precalculadas o en vivo)')
    check("out['otras_tarjeta'] = mm.otras_que_se_meten(" in dd,
          'el precálculo las deja hechas')


def probar_medicion():
    r = json.load(open('_v347_extras.json', encoding='utf-8'))
    check(r['extras']['acierto'] >= 0.77 and r['juzga']['extras']['acierto'] >= 0.77,
          'las extras aciertan cerca del 80 %% (%s; juzga %s)'
          % (r['extras']['acierto'], r['juzga']['extras']['acierto']))
    check(r['extras']['acierto'] >= r['extras']['promete'],
          'y cumplen lo que prometen')


if __name__ == '__main__':
    print('=== 1. la función ===')
    probar_funcion()
    print('\n=== 2. la conexión ===')
    probar_conexion()
    print('\n=== 3. lo medido ===')
    probar_medicion()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
