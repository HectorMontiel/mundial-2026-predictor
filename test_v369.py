#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v369.

El usuario (11-oct): «¿lo de Telegram lo estás mandando de tal manera que un
agente de IA pueda decirme qué meter y qué no, de manera sencilla?» y «quiero
poder decirle de qué deporte quiero mandar: sólo fútbol, sólo básquetbol, o
combinados».

Lo que se vigila:
  1. EL DOCUMENTO EMPIEZA POR «✅ QUÉ METER»: una línea por apuesta, las ⭐
     primero y por hora, con cuota, «acierta de verdad» y fijada/provisional;
     y dice que lo demás no se mete.
  2. La guía ya no trae reglas viejas («cuota menor de 1,35») y explica ⭐ y
     la fijada.
  3. LOS DEPORTES: el texto («futbol,nba») se entiende, y el documento, el
     resumen y los cinco envíos sólo llevan esos.
  4. El documento usa la misma tarjeta que la app (`recos_tarjeta`).

Ejecutar:  python test_v369.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _r():
    p1 = {'partido': 'A vs B', 'deporte': 'Fútbol', 'clave_liga': 'mls', 'fecha': '2030-01-01',
          'inicio': '2030-01-01 20:00:00', 'prob': 0.5}
    p2 = {'partido': 'C vs D', 'deporte': 'Fútbol', 'clave_liga': 'mls', 'fecha': '2030-01-01',
          'inicio': '2030-01-01 18:00:00', 'prob': 0.5}
    p3 = {'partido': 'Lakers vs Celtics', 'deporte': 'NBA', 'fecha': '2030-01-01',
          'inicio': '2030-01-01 19:00:00', 'prob': 0.5}
    return {'pronosticos': [p1, p2, p3], 'capa1': [], 'deportes_cubiertos': ['Fútbol', 'NBA']}


def probar_que_meter():
    import formato_ia as fi
    import mercados_dia as md
    import modo_modelo as mm
    v_m, v_p = fi._meter, md.partidos_del_dia
    fi._meter = lambda p: {
        'A vs B': [{'apuesta': 'Goles: Menos de 4.5', 'veredicto_vp': 'meter', 'prob': 0.85,
                    'cuota': 1.15, 'fijada': True, 'fijada_hora': '12:00'}],
        'C vs D': [{'apuesta': 'C o empate', 'veredicto_vp': 'meter', 'prob': 0.76,
                    'cuota': 1.25, 'provisional_hasta': '14:00'}],
        'Lakers vs Celtics': [{'apuesta': 'Gana Lakers', 'veredicto_vp': 'meter',
                               'prob': 0.80, 'p_mercado': 0.80, 'cuota': 1.20}]}[p['partido']]
    md.partidos_del_dia = lambda r, dia, con_extras=True: [
        {'deporte': p['deporte'], 'partido': p['partido'], 'hora': p['inicio'][11:16]}
        for p in r.get('pronosticos') or []]
    try:
        L = fi.que_meter(_r(), ['2030-01-01'])
        filas = [x for x in L if x[:1] in ('⭐', '•', '🏆')]
        check(len(filas) == 3 and filas[0].startswith('⭐') and 'A vs B' in filas[0],
              'la ⭐ primero aunque sea más tarde (%s)' % [x[:40] for x in filas])
        check('C vs D' in filas[1] and 'Lakers' in filas[2],
              'luego las demás por hora (18:00 antes que 19:00)')
        check('🔒 FIJADA 12:00' in filas[0] and '⏳ PROVISIONAL, se fija a las 14:00' in filas[1]
              and 'acierta de verdad 86%' in filas[0],
              'con fijada/provisional y lo que acierta de verdad')
        check(any('NO se mete' in x for x in L), 'y dice que lo demás no se mete')
        solo = fi.que_meter(fi.filtrar_deportes(_r(), ['🏀 Básquetbol']), ['2030-01-01'],
                            ['🏀 Básquetbol'])
        check(sum(1 for x in solo if x[:1] in ('⭐', '•')) == 1
              and any('Lakers' in x for x in solo),
              'sólo básquetbol: sólo la NBA')
    finally:
        fi._meter, md.partidos_del_dia = v_m, v_p
    del mm


def probar_deportes():
    import formato_ia as fi
    check(fi.deportes_de_texto('Fútbol, NBA') == ['⚽ Fútbol', '🏀 Básquetbol']
          and fi.deportes_de_texto('basquet+tenis') == ['🏀 Básquetbol', '🎾 Tenis']
          and fi.deportes_de_texto('') == [] and fi.deportes_de_texto('todos') == [],
          'el texto de los deportes se entiende (con o sin acentos; vacío = todos)')
    r = _r()
    f = fi.filtrar_deportes(r, ['⚽ Fútbol'])
    check([p['partido'] for p in f['pronosticos']] == ['A vs B', 'C vs D']
          and len(r['pronosticos']) == 3,
          'filtrar deja sólo fútbol y no toca el barrido original')
    check(fi.filtrar_deportes(r, []) is r, 'sin deportes, todo')


def probar_fuentes():
    import formato_ia as fi
    check('cuota\n  menor de 1,35' not in fi.GUIA and '⭐ ELIGE' in fi.GUIA
          and 'FIJADA' in fi.GUIA and 'QUÉ METER' in fi.GUIA,
          'la guía explica ⭐ y fijada y ya no trae la regla vieja')
    src = open('formato_ia.py', encoding='utf-8').read()
    check('mm.metidas(mm.recos_tarjeta(pick))' in src,
          'el documento usa la misma tarjeta que la app')
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check("key='tg_deportes'" in ui and "_fia.texto(r, _dias, _deps_tg)" in ui
          and 'filtrar_deportes(r, st.session_state.get' in ui,
          'la app deja elegir los deportes para los cinco envíos')
    bd = open('bot_dia_completo.py', encoding='utf-8').read()
    bt = open('bot_telegram.py', encoding='utf-8').read()
    w1 = open('.github/workflows/telegram_dia_completo.yml', encoding='utf-8').read()
    w2 = open('.github/workflows/telegram_bot.yml', encoding='utf-8').read()
    check("'--deportes'" in bd and 'DEPORTES_ENVIO' in bt
          and 'deportes:' in w1 and '--deportes "$DEPORTES_ENVIO"' in w1
          and 'DEPORTES_ENVIO: ${{ inputs.deportes }}' in w2,
          'y los envíos automáticos también (al lanzarlos a mano)')


if __name__ == '__main__':
    print('=== 1. qué meter ===')
    probar_que_meter()
    print('\n=== 3. los deportes ===')
    probar_deportes()
    print('\n=== 2 y 4. guía y fuentes ===')
    probar_fuentes()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
