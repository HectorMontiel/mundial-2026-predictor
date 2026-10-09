#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v346.

El usuario: «quiero que los tiros también se puedan meter, validado con todo
el historial»; «del cambio de apuestas de una hora a otra, ¿no hay un punto
medio?»; «el marcador, ¿cuenta las apuestas anteriores o las nuevas? es medio
engañoso»; y la pata de Capa 1 que al pitido ya no estaba.

Lo que se vigila:
  1. TIROS CON «SE METE»: la regla de alta probabilidad (modelo ≥ 72 %,
     cuota ≤ 2), activa porque su registro desde el 10-sep tiene p5 > 0, y
     que se apaga sola si deja de tenerlo.
  2. EL PUNTO MEDIO QUE SÍ AYUDA: cada «se mete» dice si está ESTABLE (≥ 6 h
     anunciada) o es NUEVA; no se congela (medido: congelar acierta menos).
  3. EL MARCADOR: lo de la tarjeta al pitido, y aparte lo anunciado antes.
  4. LA CAPA 1 ANUNCIADA: lo que estuvo en 🏆/🔷 antes y ya no al pitido, con
     su resultado y 📌.

Ejecutar:  python test_v346.py
"""
import datetime as dt
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_tiros():
    import tiros_seguimiento as ts
    import veredicto_pick as vp
    check(ts.alta_de(0.75, 'tiros', 1.5, 2.5) == 'más'
          and ts.alta_de(0.20, 'a_puerta', 3.0, 1.3) == ''          # v348
          and ts.alta_de(0.70, 'tiros', 1.5, 2.5) == ''
          and ts.alta_de(0.80, 'tiros', 2.2, 1.6) == '',
          'la regla: el modelo ≥ 72 % en el lado, cuota ≤ 2')
    r = ts.medir(ts.FICHERO, os.path.join(tempfile.mkdtemp(), 'r.json'))
    a = r.get('alta') or {}
    # v348 — con sólo «más de», la regla vuelve a seguimiento: se activa sola
    # con 100 apuestas y p5 > 0
    check(a.get('activo') == (a.get('n', 0) >= 100 and a.get('p5', 0) > 0),
          'activa sólo si su registro lo gana: %s apuestas, %s, p5 %s'
          % (a.get('n'), a.get('acierto'), a.get('p5')))
    fila = {'apuesta': 'Remates Visita: Más de 11.5', 'mercado': 'Remates',
            'prob': 0.78, 'cuota': 1.5, 'deporte': 'Fútbol',
            'tiros_alta': 'más', 'p_mod_tiros': 0.78}
    orig = ts.activo
    try:
        ts.activo = lambda *x, **k: k.get('regla') == 'alta'
        v = dict(vp.evaluar(fila), pick=fila)
        check(v['veredicto'] == vp.METER and vp.franja_futbol(v) is None,
              'con la regla activa, el tiro de alta probabilidad se mete (%s)'
              % v['razones'][:1])
        ts.activo = lambda *x, **k: False
        v = dict(vp.evaluar(fila), pick=fila)
        check(v['veredicto'] == vp.NO_METER or bool(vp.franja_futbol(v)),
              'y si la regla se apaga, deja de meterse')
    finally:
        ts.activo = orig


def probar_tarjeta_tiros():
    import tiros_equipo as te
    import valor_apuesta as va
    bloque = {'lambda_home': 9.0, 'lambda_away': 17.0, 'lambda_total': 26.0,
              'dispersion': 1.6, 'dispersion_total': 1.7, 'k': 20.0,
              'modelo_tiros': 'v345', 'peso_modelo': 1.0,
              'confianza': {'insignia': True}}
    pick = {'partido': 'A vs B', 'clave_liga': 'brasil',
            'implicitas': {'remates_away': {'11.5': {'p': 0.6, 'mas': 1.45, 'menos': 2.6}}}}
    filas = va._de_conteo(pick, {'Remates': bloque})
    mas = [f for f in filas if f['apuesta'] == 'Remates Visita: Más de 11.5']
    check(te.prob_mas(17.0, 11.5, 20.0) >= 0.72 and mas and mas[0].get('tiros_alta') == 'más',
          'la línea de alta probabilidad lleva su marca (%s)' % (mas and mas[0].get('prob')))
    menos = [f for f in filas if f['apuesta'] == 'Remates Visita: Menos de 11.5']
    check(not menos, 'el «menos» de remates no se ofrece (v348)')


class _St:
    def __init__(self):
        self.txt = []

    def markdown(self, t, **k):
        self.txt.append(str(t))


def probar_estable():
    import anunciadas as an
    import modo_modelo as mm
    ruta = os.path.join(tempfile.mkdtemp(), 'an.json')
    t0 = dt.datetime(2026, 10, 8, 2, 0, tzinfo=dt.timezone.utc)
    doc = {'decisiones': {'listas': {'pronosticos': [
        {'llave': ['A vs B', '2026-10-09 22:00:00', 'brasil'],
         'recomendadas_tarjeta': [{'apuesta': 'Goles: Más de 1.5', 'cuota': 1.2,
                                   'prob': 0.8, 'veredicto_vp': 'meter'}]}]}}}
    an.acumular(doc, ruta, t0)
    an._CACHE.clear()
    h = an.horas_anunciada({'partido': 'A vs B', 'clave_liga': 'brasil'},
                           'Goles: Más de 1.5', ruta, t0 + dt.timedelta(hours=10))
    check(h is not None and abs(h - 10) < 1e-6, 'cuenta las horas desde que se anunció')
    base = {'apuesta': 'Goles: Más de 1.5', 'prob': 0.8, 'cuota': 1.2,
            'score': 0.96, 'cuota_justa': 1.25, 'verde': False,
            'veredicto_vp': 'meter', 'puesto_valor': 1}
    st = _St()
    mm._bloque_recomendada(st, dict(base, horas_anunciada=10.0), 'x', 0)
    check('🔒 ESTABLE 10 H' in ''.join(st.txt), 'la que lleva rato: 🔒 ESTABLE')
    st = _St()
    mm._bloque_recomendada(st, dict(base, horas_anunciada=1.0), 'x', 0)
    check('🆕 NUEVA' in ''.join(st.txt), 'la recién aparecida: 🆕 NUEVA')
    st = _St()
    mm._bloque_recomendada(st, dict(base), 'x', 0)
    check('ESTABLE' not in ''.join(st.txt) and 'NUEVA' not in ''.join(st.txt),
          'sin dato, no inventa la marca')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("r1['horas_anunciada'] = _an_h.horas_anunciada(" in src,
          'la tarjeta le pone a cada apuesta sus horas anunciada')


def probar_marcador():
    import estilo_ui as eu
    h = eu.marcador_doble({'titulo': 'Ayer', 'verdes': 8, 'rojas': 2, 'ant_v': 3, 'ant_r': 1},
                          {'titulo': 'Hoy', 'verdes': 1, 'rojas': 0})
    # v352 — lo anunciado antes son provisionales y se dice que no cuentan
    check('⏳ provisionales (no cuentan): 3 ✅ 1 ❌' in h
          and '<b>80 %</b><i>acierto</i>' in h,
          'el marcador cuenta lo de la tarjeta y, aparte, lo anunciado antes')
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check("'ant_v': ant_v, 'ant_r': ant_r" in d, 'y el cálculo del día lo lleva')


def probar_capa1():
    import anunciadas as an
    import lo_mejor as lm
    ruta = os.path.join(tempfile.mkdtemp(), 'an.json')
    pick = {'deporte': 'Fútbol', 'partido': 'Cruzeiro vs Sao Paulo',
            'clave_liga': 'brasil', 'inicio': '2026-10-09T22:00:00Z',
            'board': {'Gana Cruzeiro': 0.62, 'Empate': 0.24, 'Gana Sao Paulo': 0.14},
            'implicitas': {'casa': 'Playdoit',
                           '1x2': {'home': 0.58, 'draw': 0.26, 'away': 0.16},
                           '1x2_cuotas': {'home': 1.62, 'draw': 3.6, 'away': 5.8},
                           'doble_cuotas': {'1X': 1.18, 'X2': 2.4}}}
    an.acumular({'datos': {'pronosticos': [pick]}}, ruta,
                dt.datetime(2026, 10, 9, 6, 0, tzinfo=dt.timezone.utc))
    an._CACHE.clear()
    os.environ['ANUNCIADAS_FICHERO'] = ruta
    try:
        c1 = an.capa1_del_partido(pick)
        check(c1 and c1[0]['nivel'] == '🏆', 'la Capa 1 de cada pasada se apunta (%s)'
              % [x['apuesta'] for x in c1])
        # al pitido ya no era Capa 1 (otro precio): sale igual, con 📌
        jug = dict(pick, jugado=True, goles_home=2, goles_away=0,
                   implicitas=dict(pick['implicitas'], **{'1x2': {'home': 0.72, 'draw': 0.18, 'away': 0.10}}))
        fin = lm.finalizados([jug])
        an_ = [f for f in fin if f.get('anunciada')]
        check(an_ and an_[0]['resultado_c1'] == 'verde' and an_[0]['marcador'] == '2-0',
              'lo anunciado en Capa 1 y retirado sale con su resultado (%s)'
              % [(f['apuesta'], f.get('resultado_c1')) for f in fin])
        import vista_compacta as vc
        check('📌 ' in vc.html_lista(an_), 'marcado 📌')
    finally:
        os.environ.pop('ANUNCIADAS_FICHERO', None)
        an._CACHE.clear()


if __name__ == '__main__':
    print('=== 1. tiros con «se mete» ===')
    probar_tiros()
    probar_tarjeta_tiros()
    print('\n=== 2. estable o nueva ===')
    probar_estable()
    print('\n=== 3. el marcador ===')
    probar_marcador()
    print('\n=== 4. la Capa 1 anunciada ===')
    probar_capa1()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
