#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v310: todo lo que se ofrece, medido contra lo que pasó.

El usuario: «¿no quedamos que podías medir con el histórico?», «analiza
UEFA, CONCACAF y Liga MX; tiene que estar bien calibrado: goles, córners,
todo», «de las apuestas que me diste, cuáles se cumplieron», «probabilidad
alta, pero no abras tanto los rangos; la cosa es tener buenas cuotas».

Lo que se vigila:

  1. LAS MEDICIONES QUE SOSTIENEN CADA DECISIÓN siguen diciendo lo mismo:
     remates por jugador pierden con las cuotas reales (en los dos tramos);
     la mezcla 50/50 con la media gana en tarjetas, remates y a puerta y no
     en córners; con cuotas previas, el 50/50 modelo-casa no se mejora.
  2. TARJETAS Y REMATES, a medio camino de la media de su competición (y en
     selecciones, del tipo de torneo: un amistoso se pita menos).
  3. «METER»: los conteos (córners, tarjetas, remates) ya no se corrigen por
     banda de cuota —la subían sin medirse ahí—, y la cuota mínima de 1,40
     se midió con las apuestas reales de Playdoit y se rechazó.
  4. «💎 REMATE CON VALOR» ya no se pinta.
  5. LO QUE SE GUARDA de un partido es lo que la tarjeta enseñó, con su
     veredicto, y la tarjeta del finalizado cuenta los «meter».

Ejecutar:  python test_v310.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _j(ruta):
    return json.load(open(ruta, encoding='utf-8'))


# ---------------------------------------------------------------------------
def probar_las_mediciones():
    r = _j('_v310_remates_cuotas.json')['reglas']['ambos']
    app = r['app_v308 (5%<ev<40%)']
    check(app['eleccion']['roi'] < 0 and app['juicio']['roi'] < 0
          and app['eleccion']['p5'] < 0 and app['juicio']['p5'] < 0,
          'remates por jugador: la regla del «💎» pierde en los dos tramos '
          '(%s / %s)' % (app['eleccion']['roi'], app['juicio']['roi']))
    ning = [k for k, v in r.items()
            if v['eleccion'].get('p5', -1) > 0 and v['juicio'].get('p5', -1) > 0]
    check(not ning, 'y ninguna regla de remates por jugador pasa la puerta '
                    '(%s)' % ning)
    a = _j('_v310_ajuste_conteos.json')
    for m in ('tarjetas', 'remates', 'a_puerta'):
        w = a[m]['w=0.50']
        check(w['eleccion']['p5'] > 0 and w['juicio']['p5'] > 0,
              '%s: la mezcla 50/50 con la media pasa los dos tramos' % m)
    check(not any(a['corners'][k]['juicio'].get('p5', -1) > 0
                  and a['corners'][k]['eleccion'].get('p5', -1) > 0
                  for k in a['corners'] if k.startswith('w=')),
          'córners: ninguna mezcla pasa, y por eso no se tocan')
    pc = _j('_v310_peso_casa.json')['mercados']['todo']
    mejor = [k for k, v in pc['juicio'].items() if k.startswith('w=')
             and v['p5'] > 0 and pc['eleccion'][k]['p5'] > 0 and k != 'w=0.50']
    check(not mejor, 'con cuotas PREVIAS ningún peso mejora al 50/50 de '
                     '`concordancia` en los dos tramos (%s)' % mejor)
    import concordancia
    check(concordancia.PESO_MODELO == 0.5, 'y `concordancia` sigue en 0,5')


# ---------------------------------------------------------------------------
def probar_tarjetas_y_remates():
    import rendimiento_equipos as rq
    check(rq.MEZCLA_MEDIA == {'tarjetas': 0.5, 'remates': 0.5, 'a_puerta': 0.5},
          'la mezcla medida: 0,5 en tarjetas, remates y a puerta')
    check('corners' not in rq.MEZCLA_MEDIA, 'los córners no se mezclan')
    check(rq.es_amistoso('International - Friendlies')
          and rq.es_amistoso('Amistosos internacionales')
          and not rq.es_amistoso('Liga de Naciones UEFA'),
          'reconoce un amistoso en inglés y en español')
    b = {'lambda_home': 3.0, 'lambda_away': 2.0, 'lambda_total': 5.0,
         'origen': 'observado'}
    orig = rq.media_competicion
    rq.media_competicion = lambda c, m, t='': 3.0
    try:
        n = rq._a_la_media(b, 'x', 'tarjetas')
        e = rq._a_la_media(dict(b, origen='estimado'), 'x', 'tarjetas')
        c = rq._a_la_media(b, 'x', 'corners')
    finally:
        rq.media_competicion = orig
    check(abs(n['lambda_total'] - 4.0) < 1e-9
          and abs(n['lambda_home'] + n['lambda_away'] - 4.0) < 1e-6,
          'total a medio camino (5 y 3 → 4) y los equipos suman lo mismo')
    check(n['lambda_total_modelo'] == 5.0 and b['lambda_total'] == 5.0,
          'guarda el del modelo y no muta el bloque de entrada')
    check(e['lambda_total'] == 5.0 and c['lambda_total'] == 5.0,
          'lo estimado y los córners no se tocan')
    import inspect
    check('torneo' in inspect.signature(rq.tarjetas_equipo).parameters
          and 'torneo' in inspect.signature(rq.remates_equipo).parameters,
          'tarjetas y remates reciben el torneo')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check(src.count("pick.get('liga_origen')") >= 2,
          'la tarjeta les pasa el torneo del partido')


# ---------------------------------------------------------------------------
def probar_el_meter():
    import veredicto_pick as vp
    check(vp.CUOTA_METER_FUTBOL is None and vp.UMBRAL_METER == 0.65,
          'la cuota mínima de 1,40 se midió con Playdoit y se RECHAZÓ: '
          'meter sigue siendo probabilidad ≥ 65 %')
    base = {'apuesta': 'Goles: Más de 1.5', 'mercado': 'Goles', 'prob': 0.86,
            'deporte': 'Fútbol'}
    check(vp.evaluar(dict(base, cuota=1.18))['veredicto'] == vp.METER,
          'un 86 % a 1,18 se sigue metiendo')
    check('Córners' not in vp.MERCADOS_SIN_CORRECCION,
          'los córners conservan la corrección (ahí baja la cifra y acierta)')
    for m in ('Tarjetas', 'Remates', 'Remates a puerta'):
        c = vp.correccion(0.62, m, 1.30)
        check(c['delta'] == 0.0 and c['fuente'] == 'conteo_calibrado',
              '%s: sin corrección por banda (el modelo ya sale calibrado)' % m)
    t = vp.evaluar({'apuesta': 'Tarjetas: Más de 3.5', 'mercado': 'Tarjetas',
                    'prob': 0.58, 'cuota': 1.30, 'deporte': 'Fútbol'})
    check(t['veredicto'] == vp.NO_METER and t['prob_ajustada'] == 0.58,
          'un 58 % en tarjetas ya no sube a 68 % para meterse')
    r = _j('_v310_replay_semana.json')['reglas']
    v, nu = r['vieja'], r['nueva']
    check(abs(nu['prometido'] - nu['real']) < abs(v['prometido'] - v['real'])
          and nu['roi'] >= v['roi'],
          'con las cuotas de Playdoit de la semana, la regla nueva cumple mejor '
          'lo que promete (%.3f→%.3f contra %.3f→%.3f) y no rinde peor'
          % (nu['prometido'], nu['real'], v['prometido'], v['real']))


# ---------------------------------------------------------------------------
def probar_la_tarjeta_y_el_archivo():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('filas.append(_fila_remates_con_valor(_qr))' not in src,
          '«💎 Remate con valor» ya no se pinta')
    check('apostar remates de jugador pierde dinero' in src,
          'y la escalera de remates dice por qué es sólo información')
    check("v['pick']['prob_meter'] = v.get('prob_ajustada')" in src,
          'la recomendación lleva la probabilidad con la que se decidió')
    check('🎯 meter: %d de %d' in src,
          'la tarjeta del finalizado cuenta los «meter» acertados')
    import pronosticos_guardados as pg
    f = pg._fila({'apuesta': 'x', 'prob': 0.7, 'veredicto_vp': 'meter',
                  'prob_meter': 0.68123})
    check(f['veredicto'] == 'meter' and f['prob_meter'] == 0.6812,
          'lo que se guarda lleva el veredicto y la probabilidad de «meter»')
    import modo_modelo as mm
    import partidos_jugados as pj
    orig = (mm.recomendadas, mm.remates_tarjeta, mm.corners_tarjeta,
            mm.tarjetas_tarjeta)
    mm.recomendadas = lambda q, b, n=4: [
        {'apuesta': 'A', 'mercado': 'Goles', 'bloque': 'goles',
         'veredicto_vp': 'no_meter', 'prob': .6},
        {'apuesta': 'B', 'mercado': 'BTTS', 'bloque': 'btts',
         'veredicto_vp': 'no_meter', 'prob': .55},
        {'apuesta': 'C', 'mercado': '1X2', 'bloque': 'resultado',
         'veredicto_vp': 'meter', 'prob': .7}]
    mm.remates_tarjeta = mm.corners_tarjeta = mm.tarjetas_tarjeta = \
        lambda q: None
    try:
        filas = pj._recomendadas_previas({'partido': 'X vs Y'})
    finally:
        (mm.recomendadas, mm.remates_tarjeta, mm.corners_tarjeta,
         mm.tarjetas_tarjeta) = orig
    check([f['apuesta'] for f in filas] == ['A', 'C'],
          'se archiva lo que la tarjeta enseñó: la principal y las «meter» '
          '(%s)' % [f['apuesta'] for f in filas])


if __name__ == '__main__':
    print('=== 1. las mediciones ===')
    probar_las_mediciones()
    print('\n=== 2. tarjetas y remates ===')
    probar_tarjetas_y_remates()
    print('\n=== 3. el meter ===')
    probar_el_meter()
    print('\n=== 4-5. la tarjeta y el archivo ===')
    probar_la_tarjeta_y_el_archivo()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
