#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v362.

El usuario, con un boleto de Draftea de córners ganado: «una sección nueva de
apuestas arriesgadas, con córners y tiros, que sí tengan una probabilidad
significativa; y evalúa la metodología de córners de mi amigo».

Lo que se vigila:
  1. LO MEDIDO (`_v362_corners.json`): la regla del amigo sube el acierto;
     el Método Contexto la supera; la combinada sale lo que promete.
  2. LAS PATAS (`arriesgadas`): la línea más alta al 75 %+ con cuota ≥ 1,15,
     sólo si la casa la ve parecido (no otro mercado con la misma clave).
  3. LOS BOLETOS: una pata por partido, probabilidad y momio = productos.
  4. EL SEGUIMIENTO y la sección en la pantalla.

Ejecutar:  python test_v362.py
"""
import json
import os
import shutil
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    d = json.load(open('_v362_corners.json', encoding='utf-8'))
    e = d['equipo']['3.5']
    am, todos, me = (e['A3 genera mucho y el rival concede mucho'], e['todos'], e['M método ≥ 80 %'])
    check(all(am[t]['acierta'] - todos[t]['acierta'] >= 0.07 for t in 'AB'),
          'la regla del amigo sube el acierto ~10 pts en las dos mitades (%s)' % am)
    check(all(me[t]['acierta'] > am[t]['acierta'] for t in 'AB'),
          'y el Método Contexto la supera (%s)' % me)
    # v362b — la escalera de Playdoit a cuota de riesgo: el método acierta lo
    # que promete (calibrado) y no se cuelan líneas de otro mercado
    b = json.load(open('_v362b_escaleras.json', encoding='utf-8'))
    cal = {x['banda']: x for x in b['calibracion']}
    check(all(abs(cal[k]['acierta'] - cal[k]['promete']) <= 0.05
              for k in ('(0.5, 0.55]', '(0.55, 0.6]', '(0.6, 0.65]', '(0.65, 0.7]')),
          'a cuota 1,45-3 el método acierta lo que promete (%s)'
          % [(k, cal[k]['promete'], cal[k]['acierta']) for k in sorted(cal)])
    check(b['regla']['todo']['acierto'] < 0.75,
          'sin las líneas de otro mercado no hay «90 %% a cuota 2» (%.0f %%)'
          % (100 * b['regla']['todo']['acierto']))


DOC = {'k': {'corners': 11.6, 'tiros': 20.0, 'a_puerta': 43.0},
       'partidos': {'A vs B|mls': {'local': {'corners': 7.5, 'tiros': 15.0, 'a_puerta': 6.0},
                                   'visitante': {'corners': 4.0, 'tiros': 11.0, 'a_puerta': 4.0}},
                    'C vs D|mls': {'local': {'corners': 7.0, 'tiros': 14.0, 'a_puerta': 5.0},
                                   'visitante': {'corners': 4.5, 'tiros': 12.0, 'a_puerta': 4.0}}}}
TAB = {'corners_home': {'3.5': {'p': 0.80, 'mas': 1.20}, '4.5': {'p': 0.70, 'mas': 1.35},
                        '5.5': {'p': 0.55, 'mas': 1.75}, '6.5': {'p': 0.42, 'mas': 2.30}},
       'corners': {'1.5': {'p': 0.40, 'mas': 2.33}, '7.5': {'p': 0.78, 'mas': 1.24},
                   '9.5': {'p': 0.55, 'mas': 1.75}, '10.5': {'p': 0.45, 'mas': 2.10}}}


def probar_patas():
    import arriesgadas as ar
    import mercado_implicito as mi
    import tiros_equipo as te
    v1, v2 = te._dia, mi.del_partido
    te._dia = lambda ruta=None: DOC
    mi.del_partido = lambda h, a, **k: TAB
    try:
        pats = ar.patas_del_partido({'partido': 'A vs B', 'clave_liga': 'mls',
                                     'inicio': '2099-01-01T12:00:00Z'})
        ap = {x['apuesta']: x for x in pats}
        tots = [x for x in pats if x['apuesta'].startswith('Córners: Más de')]
        check(len(tots) == 1 and 1.45 <= tots[0]['cuota'] <= 3 and tots[0]['prob'] >= 0.55
              and not any(x['apuesta'].startswith('Córners A:') for x in pats),
              'la pata: de la escalera, la línea a cuota 1,45-3 al 55 %%+; sin córners de equipo '
              '(v363) (%s)' % [(x['apuesta'], round(x['prob'], 2), x['cuota']) for x in pats])
        check('Córners: Más de 1.5' not in ap and 'Córners: Más de 7.5' not in ap,
              'ni la línea de otro mercado ni la de cuota baja entran (%s)' % sorted(ap))
        pick2 = {'partido': 'C vs D', 'clave_liga': 'mls', 'inicio': '2099-01-01T15:00:00Z'}
        todas = ar.del_dia([{'partido': 'A vs B', 'clave_liga': 'mls', 'deporte': 'Fútbol',
                             'inicio': '2099-01-01T12:00:00Z'}, dict(pick2, deporte='Fútbol')],
                           ahora=0)
        b = ar.boleto(todas, 2)
        check(b and len({x['partido'] for x in b['patas']}) == 2
              and abs(b['prob'] - b['patas'][0]['prob'] * b['patas'][1]['prob']) < 1e-9
              and abs(b['momio'] - b['patas'][0]['cuota'] * b['patas'][1]['cuota']) < 1e-9,
              'el boleto: una pata por partido, probabilidad y momio multiplicados')
        check(ar.boleto(todas, 5) is None, 'sin patas suficientes no hay boleto')
        tmp = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            ruta = os.path.join(tmp, 'a.csv')
            n = ar.registrar([{'partido': 'A vs B', 'clave_liga': 'mls', 'deporte': 'Fútbol',
                               'inicio': '2099-01-01T12:00:00Z', 'fecha': '2099-01-01'}], ruta=ruta)
            import pandas as pd
            d = pd.read_csv(ruta)
            os.chdir(tmp)
            json.dump({'dia': str(d.dia.iloc[0]), 'partidos': [{
                'partido': 'A vs B', 'goles_home': 1, 'goles_away': 0,
                'stats_partido': {'corners_home': 7, 'corners_away': 2}}]},
                open('jugados_dia.json', 'w', encoding='utf-8'))
            m = ar.liquidar(ruta)
            d = pd.read_csv(ruta)
            ok = d[d.apuesta.str.startswith('Córners: Más de')]
            check(n >= 1 and m >= 1 and float(ok.real.iloc[0]) == 9
                  and int(ok.cumple.iloc[0]) == int(9 > float(ok.linea.iloc[0])),
                  'apunta las patas y las liquida con la ficha (córners del partido: 9)')
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        te._dia, mi.del_partido = v1, v2
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    pc = open('precalculo_dia.py', encoding='utf-8').read()
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('🎲 Apuestas arriesgadas' in ui and 'arriesgadas.registrar(' in pc
          and 'arriesgadas_seguimiento.csv' in wf,
          'la sección está en la pantalla y el precálculo la sigue')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medicion()
    print('\n=== 2. patas, boletos y seguimiento ===')
    probar_patas()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
