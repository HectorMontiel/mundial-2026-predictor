#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v342.

El usuario: cinco «Ganador» de tenis perdidos a 1,38-1,45 («calibra mejor el
tenis, no está dando buenos resultados»); «en el marcador muestra el total de
apuestas, cuántas se han jugado, verdes, rojas y porcentaje, partido a la
mitad: a la izquierda el día anterior y a la derecha el actual»; y «lo de
Capa 1, cuando termina el partido, desaparece: que se ilumine de verde si se
dio y de rojo si no».

Lo que se vigila:
  1. EL TENIS: sin la curva del fútbol; «meter» sólo con la casa y el modelo
     en el 70 % o más; sin precio de la casa no se mete; el número que se
     enseña es el de la casa. El fútbol no cambia.
  2. LA SOÑADORA: las patas de tenis que no pasan van en rojo.
  3. EL MARCADOR: ayer | hoy, cada uno con su total; ayer sale de
     `jugados_ayer.json`, que el precálculo rota al cambiar de día.
  4. LA CAPA 1 FINALIZADA: con su resultado, en verde o en rojo.

Ejecutar:  python test_v342.py
"""
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _tenis(prob, cuota, p_casa=None):
    d = {'prob': prob, 'cuota': cuota, 'mercado': '1X2', 'deporte': 'Tenis',
         'apuesta': 'Gana Karolina Muchova'}
    if p_casa is not None:
        d['p_mercado'] = p_casa
    return d


def probar_tenis():
    import concordancia as cc
    import veredicto_pick as vp
    # Muchova a 1,40: el modelo 66 %, la casa 68 % → antes «meter» (72 %)
    v = vp.evaluar(_tenis(0.658, 1.40, 0.6818))
    check(v['veredicto'] == vp.NO_METER, 'el 66 %% a 1,40 ya no se mete (%s)'
          % v['razones'][:1])
    check(v['correccion'] == 0.0, 'sin la curva del fútbol')
    check(abs(v['prob_ajustada'] - 0.6818) < 1e-6,
          'el número que se enseña es el de la casa (%.4f)' % v['prob_ajustada'])
    v = vp.evaluar(_tenis(0.82, 1.15, 0.84))
    check(v['veredicto'] == vp.METER, 'casa y modelo en el 70 % o más: se mete')
    check(vp.evaluar(_tenis(0.69, 1.30, 0.75))['veredicto'] == vp.NO_METER,
          'con el modelo por debajo del 70 % no')
    check(vp.evaluar(_tenis(0.85, 1.30))['veredicto'] == vp.NO_METER,
          'sin el precio de la casa no se mete')
    check(vp.evaluar(dict(_tenis(0.6, 1.5), elite=True))['veredicto'] == vp.METER,
          'Capa 1 sigue mandando')
    # el fútbol, igual que antes: la curva sigue entrando
    f = vp.evaluar({'prob': 0.6498, 'cuota': 1.493, 'mercado': '1X2',
                    'deporte': 'Fútbol', 'apuesta': 'Gana X'})
    check(f['correccion'] > 0, 'el fútbol conserva su corrección')
    # la casa del tenis: libro de dos vías, sin margen, y peso 0 del modelo
    pick = {'deporte': 'Tenis', 'partido': 'Emma Van Poppel vs Sevil Yuldasheva',
            'implicitas': {'1x2_cuotas': {'home': 8.51, 'away': 1.0818}}}
    pm = cc.prob_mercado(pick, 'Gana Sevil Yuldasheva', '1X2')
    check(pm is not None and abs(pm - (1 / 1.0818) / (1 / 1.0818 + 1 / 8.51)) < 1e-9,
          'el tenis tiene precio de la casa (%.4f)' % (pm or 0))
    check(cc.peso_modelo({'deporte': 'Tenis'}) == 0.0, 'y decide la casa sola')
    check(vp.tenis_mete(0.70, 0.70) and not vp.tenis_mete(None, 0.9),
          'la regla, en su función')


def probar_sonadora():
    import sonadora_motor as sm
    partido = {'deporte': 'Tenis', 'partido': 'Karolina Muchova vs Rival X'}

    def pata(etq, prob, cuota):
        return sm._pata(partido, 'Ganador', etq, prob, cuota, casa='Novibet')
    patas = [pata('Gana Karolina Muchova', 0.658, 1.40),
             pata('Gana Rival X', 0.342, 2.90)]
    sm.tenis_con_la_casa(patas, partido)
    check(patas[0]['color'] == sm.ROJO and patas[0].get('regla_tenis'),
          'la pata de 1,40 que la casa ve al 68 %% va en rojo (%s)'
          % patas[0].get('regla_tenis'))
    buenas = [pata('Gana A', 0.80, 1.15), pata('Gana B', 0.20, 5.0)]
    partido2 = {'deporte': 'Tenis', 'partido': 'A vs B'}
    for q in buenas:
        q['partido'] = 'A vs B'
    sm.tenis_con_la_casa(buenas, partido2)
    pc = (1 / 1.15) / (1 / 1.15 + 1 / 5.0)
    check(buenas[0]['color'] != sm.ROJO and abs(buenas[0]['prob'] - round(pc, 4)) < 1e-9,
          'la que pasa se puntúa con la casa (%.4f)' % buenas[0]['prob'])
    sola = [pata('Gana Karolina Muchova', 0.80, 1.20)]
    sm.tenis_con_la_casa(sola, partido)
    check(sola[0]['color'] == sm.ROJO, 'sin el otro lado ni el barrido: rojo')
    futbol = {'deporte': 'Fútbol', 'partido': 'A vs B'}
    f = [sm._pata(futbol, 'Ganador', 'Gana A', 0.66, 1.40)]
    c0 = f[0]['color']
    sm.tenis_con_la_casa(f, futbol)
    check(f[0]['color'] == c0, 'el fútbol no se toca')
    src = open('sonadora_motor.py', encoding='utf-8').read()
    check(src.count('tenis_con_la_casa(') >= 3,
          'se aplica en Novibet y en el tablero de Playdoit')


def probar_marcador():
    import estilo_ui as eu
    h = eu.marcador_doble({'titulo': 'Ayer · 07/10', 'verdes': 80, 'rojas': 20},
                          {'titulo': 'Hoy · 08/10', 'verdes': 40, 'rojas': 10,
                           'en_juego': 5, 'por_jugar': 145})
    check(h.index('Ayer') < h.index('Hoy'), 'ayer a la izquierda, hoy a la derecha')
    check('<b>100</b> apuestas' in h and '<b>200</b> apuestas' in h,
          'cada mitad con su total')
    check('jugadas 50 de 200 · 5 en juego · 145 por jugar' in h,
          'cuántas se han jugado de cuántas')
    check(h.count('<b>80 %</b><i>acierto</i>') == 2, 'y el porcentaje sobre las jugadas')
    check('.marcador.doble' in eu.CSS_VIDRIO, 'con su estilo de cristal')
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check('_estilo.marcador_doble(_ma, _mc)' in d and 'solo_precalculo=True' in d,
          'en la pantalla del día, ayer sin tocar la red')
    check('_marcador_del_dia(_hoy_kpi, _dep_mc)' in d
          and "_dep_mc, solo_precalculo=True" in d and '_dep_mc)' in
          d[d.index("_mc['por_jugar'] = _por_jugar_hoy("):][:200],
          'las tres cuentas siguen el filtro de deportes (también en la caché)')
    # la rotación de ayer
    import partidos_jugados as pj
    t = tempfile.mkdtemp()
    os.environ['JUGADOS_DIA_FICHERO'] = os.path.join(t, 'dia.json')
    os.environ['JUGADOS_AYER_FICHERO'] = os.path.join(t, 'ayer.json')
    try:
        doc = {'dia': '2026-10-07', 'ts': 0, 'partidos': [{'partido': 'A vs B'}]}
        check(pj._rotar_a_ayer(doc, '2026-10-08'), 'el día que acaba pasa a ayer')
        check(not pj._rotar_a_ayer(dict(doc, dia='2026-10-05'), '2026-10-08'),
              'uno de hace tres días no es ayer')
        json.dump({'dia': '2026-10-08', 'ts': 0, 'partidos': []},
                  open(os.environ['JUGADOS_DIA_FICHERO'], 'w'))
        check(pj._leer_precalculo('2026-10-07') == [{'partido': 'A vs B'}],
              'y se lee de su fichero')
    finally:
        os.environ.pop('JUGADOS_DIA_FICHERO', None)
        os.environ.pop('JUGADOS_AYER_FICHERO', None)
    w = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('jugados_ayer.json' in w, 'el workflow lo publica')
    check('repasar_ayer(' in open('precalculo_dia.py', encoding='utf-8').read(),
          'y cada pasada le rellena los marcadores')


def probar_capa1():
    import lo_mejor as lm
    import vista_compacta as vc
    check(lm.resultado('Gana A', 'A vs B', 2, 1) == 'verde'
          and lm.resultado('A o empate', 'A vs B', 1, 1) == 'verde'
          and lm.resultado('Gana B', 'A vs B', 2, 1) == 'rojo'
          and lm.resultado('Gana A', 'A vs B', None, None) is None,
          'el resultado de ganador y doble oportunidad')
    p = {'deporte': 'Fútbol', 'partido': 'Cruzeiro vs Sao Paulo', 'jugado': True,
         'board': {'Gana Cruzeiro': 0.62, 'Empate': 0.24, 'Gana Sao Paulo': 0.14},
         'implicitas': {'casa': 'Playdoit',
                        '1x2': {'home': 0.58, 'draw': 0.26, 'away': 0.16},
                        '1x2_cuotas': {'home': 1.62, 'draw': 3.6, 'away': 5.8},
                        'doble_cuotas': {'1X': 1.18, 'X2': 2.4}},
         'goles_home': 0, 'goles_away': 1}
    fin = lm.finalizados([p])
    check(len(fin) == 1 and fin[0]['resultado_c1'] == 'rojo'
          and fin[0]['marcador'] == '0-1',
          'la Capa 1 de un partido acabado se queda, con su resultado (%s)'
          % [(x['apuesta'], x.get('resultado_c1')) for x in fin])
    check(lm.del_pick(p) is None, 'el barrido de antes sigue sin darla por jugar')
    vivo = lm.finalizados([dict(p, goles_home=None, goles_away=None)])
    check(vivo and vivo[0]['resultado_c1'] == 'vivo', 'sin marcador: en juego')
    h = vc.html_lista(fin)
    check('vc-fila fin-no' in h and '❌ NO' in h and '0-1' in h,
          'y se pinta en rojo con el marcador')
    h = vc.html_lista([dict(fin[0], resultado_c1='verde', marcador='2-0')])
    check('vc-fila fin-ok' in h and '✅ SÍ' in h, 'o en verde si se dio')
    check('.vc-fila.fin-ok' in vc.CSS and '.vc-fila.fin-no' in vc.CSS,
          'con su brillo')
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check('_capa1_finalizadas(_dia_hoy_cdmx())' in d,
          'en la Capa 1 de la pantalla del día')


def probar_resultados_tenis():
    import datetime as dt
    import fixtures_espn as fe
    import liquidador as lq
    import partidos_jugados as pj
    import resultados_flashscore as rf
    d0, d1 = dt.date(2026, 10, 6), dt.date(2026, 10, 8)
    torneo = {'date': '2026-09-27T04:00Z', 'endDate': '2026-10-12T03:59Z'}
    check(fe._dentro_del_rango(torneo, d0, d1),
          'un torneo de ESPN empezado antes cuenta si se solapa')
    check(not fe._dentro_del_rango({'date': '2026-09-27T04:00Z'}, d0, d1)
          and fe._dentro_del_rango({'date': '2026-10-07T20:00Z'}, d0, d1),
          'un partido suelto, como antes')
    ts = int(dt.datetime(2026, 10, 7, 9, tzinfo=dt.timezone.utc).timestamp())
    feed = ('~ZA÷ITF MEN - SINGLES: M15 Heraklion¬'
            '~AA÷x1¬AB÷3¬AC÷3¬AD÷%d¬AE÷Bar Biryukov P.¬AF÷Shin M.¬AG÷0¬'
            'AH÷2¬AS÷2¬BA÷4¬BB÷6¬BC÷3¬BD÷6¬'
            '~AA÷x2¬AB÷3¬AC÷3¬AD÷%d¬AE÷Wang A.¬AF÷Wang B.¬AG÷1¬AH÷1¬AS÷1¬' % (ts, ts))
    orig = rf._get
    rf._get = lambda url, intentos=3: feed if '_-1_' in url else None
    try:
        out = {}
        n = lq._sumar_flashscore_tenis(out, '2026-10-07', '2026-10-07',
                                       hoy='2026-10-08')
    finally:
        rf._get = orig
    par = tuple(sorted(('biryukov', 'shin')))
    check(n == 1 and par in out and out[par][0][1]['_ganador'] == 'shin'
          and out[par][0][1]['juegos_totales'] == 19.0,
          'Flashscore aporta el ITF con ganador, sets y juegos (%s)' % out.get(par))
    p = {'deporte': 'Tenis', 'partido': 'Petr Bar Biryukov vs Maxim Shin',
         'inicio': '2026-10-07T09:00:00Z'}
    check(pj._marcador_tenis(p, out) == (0.0, 2.0),
          'y el finalizado de la app se liquida con él')
    doble = {par: out[par] + [('2026-10-07', dict(out[par][0][1],
                                                  _ganador='biryukov'))]}
    check(pj._marcador_tenis(p, doble) is None,
          'con dos ganadores distintos para la pareja no se liquida')


if __name__ == '__main__':
    print('=== 0. los resultados del tenis ===')
    probar_resultados_tenis()
    print('\n=== 1. el tenis ===')
    probar_tenis()
    print('\n=== 2. la Soñadora ===')
    probar_sonadora()
    print('\n=== 3. el marcador ===')
    probar_marcador()
    print('\n=== 4. la Capa 1 finalizada ===')
    probar_capa1()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
