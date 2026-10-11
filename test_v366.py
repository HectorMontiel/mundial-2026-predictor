#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v366.

El usuario (11-oct): «cuando ordeno por estrellas no me sale lo de las
estrellas primero; también quiero ver la tasa de conversión de las
estrellas» y «analiza las rojas de las apuestas arriesgadas: más verdes, sin
arriesgar la cuota».

Lo que se vigila:
  1. EL PRECÁLCULO VUELVE A VALER: `anunciadas_dia.json` no entra en la huella
     (el cron lo lee y lo reescribe en la misma corrida; desde el 9-oct la app
     lo calculaba todo en vivo), tampoco en las huellas viejas.
  2. LA FIJADA NO SE PIERDE: `recos_tarjeta` la aplica siempre.
  3. «⭐ ELIGE primero» ordena con la misma tarjeta que se pinta, también sin
     precálculo.
  4. EL MARCADOR cuenta las ⭐ aparte («⭐ ELIGE: 3 ✅ 1 ❌ · 75 %»).
  5. ARRIESGADAS: de la escalera, la línea MÁS PROBABLE a cuota de riesgo.

Ejecutar:  python test_v366.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_huella():
    import decisiones_dia as dd
    check('anunciadas_dia.json' in dd.NO_SON_ENTRADA,
          'el fichero de las fijadas no es una entrada del precálculo')
    viejo = dd._sha
    dd._sha = lambda r: 'otro' if r == 'anunciadas_dia.json' else 'igual'
    try:
        check(dd.huella_vigente({'anunciadas_dia.json': 'x', 'modo_modelo.py': 'igual'}),
              'una huella vieja que lo traía sigue valiendo')
        check(not dd.huella_vigente({'modo_modelo.py': 'cambiado'}),
              'pero un fichero de verdad cambiado la invalida')
    finally:
        dd._sha = viejo


def probar_fijada_y_orden():
    import decisiones_dia as dd
    import modo_modelo as mm
    v_t, v_f = dd.tarjeta_de_pick, mm.con_fijada
    fila = {'apuesta': 'Goles: Menos de 4.5', 'veredicto_vp': 'meter', 'prob': 0.80,
            'prob_meter': 0.80, 'cuota': 1.25}
    dd.tarjeta_de_pick = lambda p: [dict(fila)]
    mm.con_fijada = lambda p, r: [dict(x, fijada=True) for x in (r or [])]
    try:
        check(all(x.get('fijada') for x in mm.recos_tarjeta({'partido': 'A vs B'})),
              'recos_tarjeta aplica la fijada a lo precalculado')
        estrella = dict(fila, prob=0.85, prob_meter=0.85)
        # sin precálculo: la cuenta de la tarjeta (la recordada en la app)
        dd.tarjeta_de_pick = lambda p: None
        v_r = mm.recos_tarjeta
        mm.recos_tarjeta = lambda p: [dict(estrella if p['partido'].startswith('Con') else fila)]
        ps = [{'partido': 'Sin vs Estrella', 'clave_liga': 'l', 'inicio': '2099-01-01 10:00', 'prob': 0.5},
              {'partido': 'Con vs Estrella', 'clave_liga': 'l', 'inicio': '2099-01-01 20:00', 'prob': 0.5}]
        orden = [p['partido'] for p in sorted(ps, key=mm._k_elige)]
        check(orden == ['Con vs Estrella', 'Sin vs Estrella'],
              'sin precálculo, la ⭐ va primero aunque sea más tarde (%s)' % orden)
        mm.recos_tarjeta = v_r
    finally:
        dd.tarjeta_de_pick, mm.con_fijada = v_t, v_f


def probar_marcador():
    import estilo_ui as eu
    html = eu._mitad_marcador({'titulo': 'Hoy', 'verdes': 10, 'rojas': 3,
                               'eli_v': 3, 'eli_r': 1})
    check('⭐ ELIGE: 3 ✅ 1 ❌ · 75 %' in html, 'el marcador enseña la tasa de las ⭐')
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check("'eli_v': eli_v" in src and 'def _es_elige(' in src,
          'el marcador del día las cuenta con la regla de la tarjeta')


def probar_arriesgadas():
    import arriesgadas as ar
    import tiros_equipo as te
    v = te.prob_mas
    te.prob_mas = lambda mu, L, k: {8.5: 0.66, 9.5: 0.58}.get(L, 0.3)
    try:
        lin = {'8.5': {'p': 0.62, 'mas': 1.50, 'menos': 2.50},
               '9.5': {'p': 0.52, 'mas': 1.85, 'menos': 1.95},
               '7.5': {'p': 0.75, 'mas': 1.25, 'menos': 3.6}}
        m = ar._mejor_linea(lin, 10.0, 12.0)
        check(m is not None and m[0] == 8.5,
              'la línea más probable a cuota 1,45-3, no la de más prob × cuota (%s)' % (m,))
    finally:
        te.prob_mas = v
    check(open('_v366_rojas_arriesgadas.json', encoding='utf-8').read().count('H10') >= 1,
          'la medición queda guardada')


if __name__ == '__main__':
    print('=== 1. la huella ===')
    probar_huella()
    print('\n=== 2-3. la fijada y el orden ===')
    probar_fijada_y_orden()
    print('\n=== 4. el marcador ===')
    probar_marcador()
    print('\n=== 5. arriesgadas ===')
    probar_arriesgadas()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
