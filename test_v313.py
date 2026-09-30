#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v313.

El usuario, con la Capa 1 y el documento de Telegram delante:
  · «en Capa 1 me mandas Sub 21, Sub 19, Japón… y en las apuestas del día no
    aparecen, ni en Telegram. Quiero que esté todo, pero el porcentaje de
    acierto no tiene que bajar»;
  · «Egipto: el documento lo pone contra Sudán, pero es Sudán del Sur»;
  · «λ de córners 9,1 repetido en toda la Liga de Naciones: arregla eso»;
  · «el agente no buscó en la web solo, y no me quiso armar una promoción».

Lo que se vigila:
  1. SUDÁN DEL SUR: «South Sudan» no casa con «Sudan» (ni Irlanda del Norte
     con Irlanda…), y los emparejados de siempre siguen igual.
  2. PARTIDOS SIN MODELO: la regla medida de «meter» (Pinnacle 80-90 %, cuota
     1,10-1,35, local o local/empate), una por partido; lo que el modelo
     cubre no se duplica; la medición sostiene que el acierto NO baja.
  3. LLEGAN A TODAS PARTES: tarjeta de la app, finalizados, Telegram (con
     hora, sin duplicados «USA / United States»).
  4. CÓRNERS: el total sigue siendo la media (medido: la mezcla no pasa) y
     el documento lo dice.
  5. EL AGENTE: busca en la web por partido sin pedírselo y nunca se niega a
     una promoción.

Ejecutar:  python test_v313.py
"""
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_sudan():
    import name_mapper as nm
    check(nm.mapear('South Sudan', ['Sudan', 'Egypt']) is None,
          '«South Sudan» ya no se convierte en «Sudan»')
    check(nm.mapear('Northern Ireland', ['Ireland']) is None
          and nm.mapear('Equatorial Guinea', ['Guinea']) is None
          and nm.mapear('DR Congo', ['Congo']) is None,
          'ni Irlanda del Norte, Guinea Ecuatorial o RD Congo')
    check(nm.mapear('North Macedonia', ['Macedonia']) == 'Macedonia',
          'Macedonia del Norte sí es Macedonia (nombre viejo)')
    check(nm.mapear('Ajax', ['Ajax Amsterdam']) == 'Ajax Amsterdam'
          and nm.mapear('Roma', ['AS Roma']) == 'AS Roma'
          and nm.mapear('Man City', ['Manchester City']) == 'Manchester City',
          'los emparejados de siempre no cambian')


def _tablero(ruta, partidos):
    json.dump({'partidos': partidos}, open(ruta, 'w', encoding='utf-8'))


def _v(home, away, inicio, q):
    casas = {'Novibet': {'HOME_DRAW_AWAY': {'home': q['home'], 'draw': q['draw'],
                                            'away': q['away']},
                         'DOUBLE_CHANCE': {'homeOrDraw': q['1X'],
                                           'awayOrDraw': q['X2']}}}
    return {'deporte': 'futbol', 'home': home, 'away': away,
            'liga': 'EUROPE: Euro U21', 'inicio': str(inicio), 'casas': casas}


def _pred(lh=2.4, la=0.45):
    """v315 — desde la v315 un partido fuera del motor sólo se ofrece con
    modelo propio; en los tests se le da uno fijo."""
    import modelo_competiciones as mc
    return {'p': mc.probabilidades(lh, la), 'lambdas': (lh, la), 'n': (20, 20)}


def probar_sin_modelo():
    import time
    import mercado_sin_modelo as msm
    check((msm.P_MIN, msm.P_MAX, msm.CUOTA_MIN, msm.CUOTA_MAX)
          == (0.80, 0.90, 1.10, 1.35)
          and msm.LADOS_METER == ('home', 'homeOrDraw'),
          'regla: Pinnacle 80-90 %, cuota 1,10-1,35, local o local/empate')
    check(msm.mismo_partido('USA vs Chile', 'United States vs Chile')
          and msm.mismo_partido('Botafogo SP vs Ponte Preta',
                                'Botafogo-SP vs Ponte Preta'),
          'el mismo partido escrito de otra forma se reconoce')
    check(not msm.mismo_partido('USA U19 vs Wales U19', 'United States vs Wales')
          and not msm.mismo_partido('South Sudan vs Egypt', 'Sudan vs Egypt'),
          'un sub-19 no es la absoluta, y Sudán del Sur no es Sudán')
    ini = int(time.time()) + 86400
    fav = _v('Belgium U21', 'Wales U21', ini,
             {'home': 1.23, 'draw': 7.5, 'away': 13.0, '1X': 1.05, 'X2': 4.5})
    pin = {'home': 1.18, 'draw': 7.8, 'away': 15.0}
    p = msm.pick_de(fav, pin, pred=_pred(), t_pd={})
    check(p['solo_mercado'] and p['partido'] == 'Belgium U21 vs Wales U21'
          and abs(sum(p['board'].values()) - 1) < 0.01 and p.get('hora_cdmx'),
          'el pick de mercado lleva 1X2 de Pinnacle sin margen y la hora')
    r = msm.recomendadas(p)
    check(len(r) == 1 and r[0]['apuesta'] == 'Gana Belgium U21'
          and r[0]['veredicto_vp'] == 'meter' and 0.80 <= r[0]['prob'] <= 0.90,
          'Pinnacle 80-90 %% a 1,23: se mete (%s)' % [x['apuesta'] for x in r])
    p2 = msm.pick_de(fav, {'home': 1.40, 'draw': 4.5, 'away': 8.0}, pred=_pred(), t_pd={})
    check(msm.recomendadas(p2) == [], 'con Pinnacle ~70 % no se mete')
    vis = _v('A', 'B', ini, {'home': 13.0, 'draw': 7.5, 'away': 1.23,
                             '1X': 4.5, 'X2': 1.05})
    check(msm.recomendadas(msm.pick_de(vis, {'home': 15.0, 'draw': 7.8,
                                             'away': 1.18}, pred=_pred(), t_pd={})) == [],
          'el visitante no entra (no medido)')
    barato = _v('C', 'D', ini, {'home': 1.06, 'draw': 12, 'away': 30,
                                '1X': 1.01, 'X2': 9})
    check(msm.recomendadas(msm.pick_de(barato, {'home': 1.12, 'draw': 9,
                                                'away': 25}, pred=_pred(), t_pd={})) == [],
          'a cuota menor de 1,10 no se mete')
    # construir: lo que el modelo cubre no se duplica
    tmp = os.path.join(tempfile.mkdtemp(), 'cuotas_mx.json')
    _tablero(tmp, {'1': fav, '2': _v('United States', 'Chile', ini,
                                     {'home': 1.2, 'draw': 7, 'away': 14,
                                      '1X': 1.04, 'X2': 5})})
    orig = msm._pinnacle
    msm._pinnacle = lambda h, a: {'home': 1.18, 'draw': 7.8, 'away': 15.0}
    import modelo_competiciones as mc
    orig_p, orig_t = mc.predecir, msm._tablero_playdoit
    mc.predecir = lambda h, a, i, liga=None: _pred()
    msm._tablero_playdoit = lambda v, fecha=None: {}
    try:
        import horario as hz
        datos = {'pronosticos': [{'deporte': 'Fútbol',
                                  'partido': 'USA vs Chile',
                                  'fecha': hz.fecha(str(ini))}]}
        L = msm.construir(datos, ruta=tmp)
    finally:
        msm._pinnacle = orig
        mc.predecir, msm._tablero_playdoit = orig_p, orig_t
    check([x['partido'] for x in L] == ['Belgium U21 vs Wales U21'],
          'construir: entra el sub-21 y NO el partido que ya cubre el modelo '
          '(%s)' % [x['partido'] for x in L])
    # la medición que lo sostiene
    m = json.load(open('_v313_sin_modelo.json', encoding='utf-8'))
    for tramo in ('eleccion', 'prueba', 'hoy'):
        s = m['sumado_a_v312'][tramo]
        antes = float(s['solo_modelo'].split('=')[1].strip(' %'))
        despues = float(s['juntos'].split('=')[1].strip(' %'))
        check(despues >= antes, '%s: el acierto de «meter» no baja (%.1f %% → '
              '%.1f %%)' % (tramo, antes, despues))
    lg = m['ledger']
    check(lg['eleccion']['acierto'] > 0.76 and lg['prueba']['acierto'] > 0.76,
          'y en la muestra grande (2018-2026) acierta más del 76 %% (%.1f / %.1f)'
          % (100 * lg['eleccion']['acierto'], 100 * lg['prueba']['acierto']))


def probar_que_llega():
    import modo_modelo as mm
    import mercado_sin_modelo as msm
    import time
    ini = int(time.time()) + 86400
    p = msm.pick_de(_v('Belgium U21', 'Wales U21', ini,
                       {'home': 1.23, 'draw': 7.5, 'away': 13.0, '1X': 1.05,
                        'X2': 4.5}), {'home': 1.18, 'draw': 7.8, 'away': 15.0},
                    pred=_pred(), t_pd={})
    r = mm.metidas(mm.recomendadas(p))
    check(r and r[0]['apuesta'] == 'Gana Belgium U21',
          'la tarjeta de la app usa la regla de mercado en estos partidos')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("elif pick.get('solo_mercado'):" in src
          and 'Sin modelo propio para esta competición' in src,
          'la tarjeta los pinta con su «🎯 Se mete» y dice de dónde sale')
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check("(r.get('solo_mercado') or [])" in d,
          'las listas de hoy / mañana / pasado los incluyen')
    pc = open('precalculo_dia.py', encoding='utf-8').read()
    check("datos['solo_mercado'] = _msm.construir(datos)" in pc,
          'el precálculo los construye en su propia lista')
    pj = open('partidos_jugados.py', encoding='utf-8').read()
    check("_dd.get('solo_mercado')" in pj,
          'y se archivan al empezar, para verlos en finalizados')
    # Telegram: mismo partido con dos nombres → un solo bloque, con hora
    import mercados_dia as md
    import formato_ia as fi
    r_ = {'pronosticos': [{'deporte': 'Fútbol', 'partido': 'United States vs Chile',
                           'liga': 'Amistosos', 'clave_liga': 'selecciones',
                           'inicio': '2030-01-01 20:00:00', 'hora_cdmx': '14:00',
                           'fecha': '2030-01-01', 'board': {'Gana United States': .6},
                           'mercados': []}],
          'capa1': [{'deporte': 'Fútbol', 'partido': 'USA vs Chile',
                     'liga': 'WORLD: Friendly', 'clave_liga': 'x',
                     'inicio': '1893528000', 'fecha': '2030-01-01',
                     'apuesta': 'Gana USA', 'prob': .69, 'cuota': 1.49,
                     'casa': 'Novibet'}],
          'solo_mercado': [p]}
    dia = p['fecha']
    r_['pronosticos'][0]['inicio'] = r_['capa1'][0]['inicio'] = str(ini)
    r_['pronosticos'][0]['fecha'] = r_['capa1'][0]['fecha'] = dia
    regs = md.partidos_del_dia(r_, dia, con_extras=False)
    nombres = [x['partido'] for x in regs]
    check(nombres.count('United States vs Chile') == 1
          and 'USA vs Chile' not in nombres,
          '«USA vs Chile» de la Capa 1 se junta con «United States vs Chile» '
          '(%s)' % nombres)
    check(all(x['hora'] for x in regs), 'ningún partido sale sin hora (--:--)')
    t = fi.texto(r_, [dia])
    check('Belgium U21 vs Wales U21' in t and 'FUERA DEL MOTOR DE LIGAS' in t
          and '• Gana Belgium U21' in t,
          'Telegram: el sub-21 sale con su 🎯 METER y dice que es sin modelo')


def probar_corners():
    m = json.load(open('_v313_corners_total.json', encoding='utf-8'))
    check(m['pasa'] is False and m['prueba']['p5'] < 0,
          'mezclar la suma de equipos en el total NO pasa (p5 prueba %+.5f): '
          'el total sigue siendo la media' % m['prueba']['p5'])
    import formato_ia as fi
    src = open('formato_ia.py', encoding='utf-8').read()
    check('MEDIA DE LA COMPETICIÓN' in fi.GUIA
          and "' = media de la competición'" in src,
          'el documento dice que el 9,1 es la media de la competición, a '
          'propósito')


def probar_agente():
    t = open('AGENTE_IA_APUESTAS.md', encoding='utf-8').read()
    for pieza in ('REGLA 1', 'SIN QUE TE LO PIDA', 'búsqueda web',
                  'No tengo búsqueda web', 'REGLA 2', 'NUNCA TE NIEGAS',
                  'cuota mínima', 'Probabilidad conjunta', 'fuera del meter',
                  'South Sudan', 'sigue', 'FUERA DEL MOTOR DE LIGAS',
                  'Prompt de sistema', 'No inventes datos', 'Formato de salida'):
        check(pieza in t, 'el prompt del agente trata «%s»' % pieza)
    check('máximo\n  3 patas' not in t and 'máximo 3 patas' not in t,
          'ya no limita las combinadas a 3 patas')


if __name__ == '__main__':
    print('=== 1. Sudán del Sur ===')
    probar_sudan()
    print('\n=== 2. partidos sin modelo ===')
    probar_sin_modelo()
    print('\n=== 3. llegan a todas partes ===')
    probar_que_llega()
    print('\n=== 4. córners ===')
    probar_corners()
    print('\n=== 5. el agente ===')
    probar_agente()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
