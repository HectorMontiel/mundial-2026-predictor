#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v350.

El usuario: «quiero meter a la Capa 1 y a las que se meten el ganador y los
puntos de la NFL y de la NBA, y el ganador y las carreras de la MLB, con la
misma metodología del fútbol; que la mayoría sigan siendo verdes».

Lo que se vigila:
  1. LA MEDICIÓN: la regla adoptada de cada deporte se eligió con 2010-2020
     y en 2021-2025 acierta ~80 % y más que la de antes (p5 > 0); la Capa 1
     replicada acierta ≥ 83 %.
  2. EL VEREDICTO: NFL y NBA meten el ganador sólo con su regla; los puntos
     y el béisbol se enseñan pero no se meten.
  3. LA CAPA 1 🏆 de la NFL y la NBA, con su deporte y su acierto medido.
  4. LA SOÑADORA, con las mismas reglas.

Ejecutar:  python test_v350.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    import veredicto_pick as vp
    d = json.load(open('_v350_ganador.json', encoding='utf-8'))
    for dep in ('NFL', 'NBA'):
        a = d[dep]['adoptada']
        check(a['regla']['casa'] == vp.METER_GANADOR_CASA_MIN[dep]
              and a['regla']['app'] == vp.METER_GANADOR_APP_MIN,
              '%s: la regla de producción es la medida (casa ≥ %.0f %%)'
              % (dep, 100 * a['regla']['casa']))
        check(a['juzga']['acierto'] >= 0.79 and a['juzga_vs_hoy']['acierto_dif_p5'] > 0,
              '%s: al juzgar acierta %.1f %% (antes %.1f %%), p5 de la mejora %+.1f pts'
              % (dep, 100 * a['juzga']['acierto'], 100 * d[dep]['hoy_juzga']['acierto'],
                 100 * a['juzga_vs_hoy']['acierto_dif_p5']))
        check(d[dep]['capa1_futbol_juzga']['acierto'] >= 0.83
              and d[dep]['capa1_futbol_elige']['acierto'] >= 0.83,
              '%s: la Capa 1 del fútbol replicada acierta %.1f / %.1f %%'
              % (dep, 100 * d[dep]['capa1_futbol_elige']['acierto'],
                 100 * d[dep]['capa1_futbol_juzga']['acierto']))


def _v(dep, apuesta, mercado, prob, cuota, ch, ca, **extra):
    import veredicto_pick as vp
    p = {'deporte': dep, 'partido': 'Local vs Visita', 'apuesta': apuesta,
         'mercado': mercado, 'prob': prob, 'cuota': cuota,
         'implicitas': {'1x2_cuotas': {'home': ch, 'away': ca}}, **extra}
    return vp.evaluar(p)['veredicto'] == vp.METER


def probar_veredicto():
    # casa sin margen: 1,25 / 4,60 → 78,6 % para el local
    check(_v('NFL', 'Gana Local', '1X2', 0.80, 1.25, 1.25, 4.60),
          'NFL: el ganador con la casa en 79 % y la app en 70 %+ se mete')
    check(not _v('NFL', 'Gana Local', '1X2', 0.80, 1.40, 1.40, 3.0),
          'NFL: con la casa en 68 % ya no (antes bastaba el 65 %)')
    check(_v('NBA', 'Gana Local', '1X2', 0.80, 1.25, 1.25, 4.60)
          and not _v('NBA', 'Gana Local', '1X2', 0.80, 1.28, 1.28, 4.0),
          'NBA: con la casa en 79 % sí; en 76 % no (pide 78 %)')
    check(not _v('NFL', 'Gana Local', '1X2', 0.95, 1.04, 1.04, 15.0),
          'cuota por debajo de 1,10: no')
    imp = {'1x2_cuotas': {'home': 1.5, 'away': 2.6},
           'totales_cuotas': {'49.5': {'mas': 3.0, 'menos': 1.36}}}
    import veredicto_pick as vp
    v = vp.evaluar({'deporte': 'NFL', 'partido': 'Local vs Visita',
                    'apuesta': 'Puntos: Menos de 49.5', 'mercado': 'Puntos',
                    'prob': 0.75, 'cuota': 1.36, 'implicitas': imp})
    check(v['veredicto'] == vp.NO_METER and 'puntos' in ' '.join(v['razones']),
          'NFL: los puntos no se meten (%s)' % v['razones'][:1])
    v = vp.evaluar({'deporte': 'MLB', 'partido': 'Visita @ Local',
                    'apuesta': 'Carreras: Menos de 10.5', 'mercado': 'Carreras',
                    'prob': 0.72, 'cuota': 1.40})
    check(v['veredicto'] == vp.NO_METER and v['correccion'] == 0.0,
          'MLB: las carreras no se meten y ya no llevan la curva del fútbol')
    check(not _v('KBO', 'Gana Local', '1X2', 0.75, 1.30, 1.30, 3.4),
          'KBO: el béisbol tampoco')


def probar_capa1():
    import lo_mejor as lm
    p = {'deporte': 'NBA', 'partido': 'Celtics vs Bulls', 'fecha': '2026-10-30',
         'board': {'Gana Celtics': 0.77, 'Gana Bulls': 0.23},
         'implicitas': {'1x2_cuotas': {'home': 1.16, 'away': 5.2}}}
    e = lm.del_pick(p)
    check(e is not None and e['apuesta'] == 'Gana Celtics' and e['elite'],
          'NBA: modelo 77 %% y casa %.0f %% → Capa 1 🏆' % (100 * (e or {}).get('p_mercado', 0)))
    f = lm._entrada(p, e, False)
    check(f['deporte'] == 'NBA' and f['prob_escalera'] == 0.84,
          'la fila lleva su deporte y el acierto medido de la NBA (84 %)')
    check(lm.del_pick(dict(p, pretemporada=True)) is None,
          'la pretemporada no entra')
    check(lm.del_pick(dict(p, board={'Gana Celtics': 0.65, 'Gana Bulls': 0.35})) is None,
          'con el modelo por debajo del 70 % no entra')
    check(lm.resultado('Gana Celtics', 'Celtics vs Bulls', 112, 99) == 'verde',
          'y se liquida con el marcador (puntos) como en el fútbol')
    import veredicto_pick as vp
    v = vp.evaluar(dict(e, deporte='NBA', partido=p['partido']))
    check(v['veredicto'] == vp.METER, 'en la tarjeta va como «meter»')


def probar_sonadora():
    import sonadora_motor as sm
    partido = {'deporte': 'NFL', 'partido': 'Local vs Visita',
               'implicitas': {'1x2_cuotas': {'home': 1.25, 'away': 4.6}}}
    patas = [{'partido': 'Local vs Visita', 'casa': 'Playdoit', 'categoria': 'Ganador',
              'etiqueta': 'Gana Local', 'cuota': 1.25, 'prob_modelo': 0.80},
             {'partido': 'Local vs Visita', 'casa': 'Playdoit', 'categoria': 'Ganador',
              'etiqueta': 'Gana Visita', 'cuota': 4.6, 'prob_modelo': 0.20},
             {'partido': 'Local vs Visita', 'casa': 'Playdoit', 'categoria': 'Total',
              'etiqueta': 'Menos de 49.5', 'cuota': 1.36, 'prob_modelo': 0.75}]
    r = sm.deportes_con_la_casa(patas, partido)
    check(r[0]['color'] != sm.ROJO and r[1]['color'] == sm.ROJO and r[2]['color'] == sm.ROJO,
          'Soñadora NFL: el ganador que pasa la regla queda; el otro lado y los puntos, en rojo')
    m = sm.deportes_con_la_casa([dict(patas[0])], dict(partido, deporte='MLB'))
    check(m[0]['color'] == sm.ROJO, 'Soñadora MLB: en rojo')
    src = open('sonadora_motor.py', encoding='utf-8').read()
    check(src.count('deportes_con_la_casa(') >= 3, 'y se aplica en los dos caminos de patas')


if __name__ == '__main__':
    print('=== 1. la medición ===')
    probar_medicion()
    print('\n=== 2. el veredicto ===')
    probar_veredicto()
    print('\n=== 3. la Capa 1 ===')
    probar_capa1()
    print('\n=== 4. la Soñadora ===')
    probar_sonadora()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
