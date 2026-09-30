#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v315.

El usuario, con dos capturas: «🚨 Alerta de datos: no están llegando cuotas»
y sub-19 «Finalizado · marcador pendiente». «Tenemos que tener un modelo
propio para cada una de esas ligas y competiciones… sólo ocupo Playdoit, la
comparamos con Pinnacle, y Draftea y Novibet… analiza los rojos».

Lo que se vigila:
  1. LA ALERTA: mide los precios que la aplicación usa (precálculo y
     tablero), no una petición en vivo desde el servidor de la aplicación.
  2. LIQUIDAR: «X o empate» con empate es verde; la hora de la casa puede
     estar mal (±3 h con los dos nombres); y los bandos al revés.
  3. LA BASE PROPIA Y EL MODELO PROPIO: existen, son secuenciales, separan
     U21 / femenil / reservas, y lo medido queda escrito (solo pierde contra
     Pinnacle; el veto no pasó).
  4. LAS CASAS: sólo Playdoit y Novibet ponen precio.
  5. SIN MODELO PROPIO NO SE OFRECE: así nada queda sin poder liquidarse.

Ejecutar:  python test_v315.py
"""
import json
import os
import tempfile
import time

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_alerta():
    import data_health as dh
    src = open('data_health.py', encoding='utf-8').read()
    check('_precios_publicados()' in src, 'la salud mira los precios publicados')
    d = tempfile.mkdtemp()
    cwd = os.getcwd()
    os.chdir(d)
    try:
        json.dump({'generado_ts': time.time() - 3600,
                   'datos': {'pronosticos': [{'cuota': 1.3}] * 40}},
                  open('pronostico_dia.json', 'w'))
        import cuotas_multi as cm
        orig = cm.diagnostico
        cm.diagnostico = lambda: {'futbol': 0}      # el servidor sin Pinnacle
        try:
            e = dh.estado_datos()
        finally:
            cm.diagnostico = orig
        check(e['nivel'] == 'ok' and not e['alarma'],
              'precálculo de hace 1 h y Pinnacle caído en el servidor: sin alarma '
              '(%s)' % e['detalles'])
        json.dump({'generado_ts': time.time() - 30 * 3600,
                   'datos': {'pronosticos': [{'cuota': 1.3}] * 40}},
                  open('pronostico_dia.json', 'w'))
        e = dh.estado_datos()
        check(e['nivel'] == 'critico' and e['alarma'],
              'precálculo de hace 30 h: ahí sí hay alarma')
    finally:
        os.chdir(cwd)


def probar_liquidar():
    import pronosticos_guardados as pg
    p = {'partido': 'Bromsgrove vs Leamington', 'clave_liga': 'x',
         'fecha': '2026-09-29', 'jugado': True, 'goles_home': 1.0,
         'goles_away': 1.0,
         'recomendadas_previas': [{'mercado': 'Doble oportunidad',
                                   'bloque': 'resultado',
                                   'etiqueta': 'Doble oportunidad',
                                   'apuesta': 'Bromsgrove o empate',
                                   'prob': .85, 'cuota': 1.14,
                                   'veredicto': 'meter', 'origen': 'archivo'}]}
    v = pg.validar(p)
    check(v and v[0]['estado'] == 'cumplido',
          '«Bromsgrove o empate» con 1-1 es verde (%s)' % (v and v[0]['estado']))
    import partidos_jugados as pj
    import horario as hz
    base = hz._a_utc('2026-09-29 09:00:00')
    lista = [{'ini': base, 'home': 'Brunei', 'away': 'Hong Kong', 'gh': 0.0, 'ga': 2.0}]
    m = pj._casar_fotmob({'partido': 'Hong Kong vs Brunei',
                          'inicio': '2026-09-29 08:00:00'}, lista)
    check(m and m['gh'] == 2.0 and m['ga'] == 0.0,
          'hora de la casa 1 h desplazada y bandos al revés: se liquida y se '
          'voltea el marcador (%s)' % m)


def probar_modelo():
    import modelo_competiciones as mc
    import resultados_fotmob as rf
    import pandas as pd
    check(os.path.exists(rf.FICHERO), 'la base propia de resultados existe')
    df = rf.cargar()
    check(len(df) > 50000 and df['liga_id'].nunique() > 300,
          'base: %d partidos de %d competiciones' % (len(df), df['liga_id'].nunique()))
    p = mc.probabilidades(1.8, 0.9)
    check(abs(p['home'] + p['draw'] + p['away'] - 1) < 1e-6
          and p['home'] > p['away'] and p['mas_1.5'] > p['mas_2.5'],
          'las probabilidades del modelo son coherentes')
    m = mc.Motor()
    for _ in range(10):
        m.actualizar(1, 'A', 'B', 3, 0)
    lh, la = m.lambdas(1, 'A', 'B')
    check(lh > la, 'un equipo que gana 3-0 diez veces sube su ataque (%.2f vs %.2f)'
          % (lh, la))
    check(mc.buscar_equipo('Platense 2') is None or
          'Platense FC' != mc.buscar_equipo('Platense 2')[3],
          '«Platense 2» (reservas) no es el primer equipo')
    e = mc.buscar_equipo('Ajax W')
    check(e is not None and '(W)' in e[3], 'el femenil busca el femenil (%s)' % (e,))
    r = json.load(open('_v315_modelo_competiciones.json', encoding='utf-8'))
    b = r['brier']['resultado']['eleccion']
    check(b['1'] > b['0'], 'medido y dicho: solo, el modelo acierta menos que '
          'el mercado (Brier %.4f contra %.4f)' % (b['1'], b['0']))
    check(r['veto_elegido'] == 'sin veto',
          'el veto del modelo no pasó y no se aplica')
    import mercado_sin_modelo as msm
    check(msm.MODELO_MIN == 0.0, 'el umbral del veto queda en 0')


def probar_casas():
    import mercado_sin_modelo as msm
    v = {'home': 'A', 'away': 'B', 'casas': {
        'Winpot': {'HOME_DRAW_AWAY': {'home': 1.30, 'draw': 5, 'away': 9}},
        'Novibet': {'HOME_DRAW_AWAY': {'home': 1.22, 'draw': 5, 'away': 9}}}}
    q = msm.precios_usuario(v, t_pd={'1x2_cuotas': {'home': 1.25}})
    check(q['home'] == (1.25, 'Playdoit'),
          'Winpot paga 1,30 pero no es tuya: sale 1,25 de Playdoit (%s)' % (q['home'],))
    check(msm.CASAS_USUARIO == ('Playdoit', 'Novibet', 'Draftea'),
          'las casas son Playdoit, Novibet y Draftea')


def probar_sin_base():
    import mercado_sin_modelo as msm
    import modelo_competiciones as mc
    tmp = os.path.join(tempfile.mkdtemp(), 'cuotas_mx.json')
    ini = int(time.time()) + 86400
    v = {'deporte': 'futbol', 'home': 'Serbia U19', 'away': 'Hungary U19',
         'liga': 'X', 'inicio': str(ini), 'casas': {'Novibet': {
             'HOME_DRAW_AWAY': {'home': 1.2, 'draw': 7, 'away': 14}}}}
    json.dump({'partidos': {'1': v}}, open(tmp, 'w'))
    orig = mc.predecir
    mc.predecir = lambda h, a, i, liga=None: None          # FotMob no los tiene
    try:
        L = msm.construir({'pronosticos': []}, ruta=tmp)
    finally:
        mc.predecir = orig
    check(L == [], 'sin modelo propio (no están en la base) no se ofrece: no '
          'quedará «marcador pendiente»')
    t = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('resultados_fotmob.csv.gz' in t, 'el cron guarda la base propia')
    pc = open('precalculo_dia.py', encoding='utf-8').read()
    check('_rf.actualizar()' in pc, 'el precálculo la pone al día')
    r = json.load(open('_v315_rojos.json', encoding='utf-8'))
    check(r['apuestas'] > 100 and r['rojos'], 'los rojos están analizados (%d)'
          % len(r['rojos']))
    import modo_modelo as mm
    recos = [{'apuesta': str(i), 'veredicto_vp': 'meter'} for i in range(4)]
    check(mm.MAX_METER_POR_PARTIDO == 2 and len(mm.metidas(recos)) == 2,
          'como mucho dos «meter» por partido (los rojos llegaban en racimo)')
    pj = open('partidos_jugados.py', encoding='utf-8').read()
    check('recos[:mm.MAX_METER_POR_PARTIDO]' in pj,
          'y se archivan las mismas dos que se enseñan')


if __name__ == '__main__':
    print('=== 1. la alerta ===')
    probar_alerta()
    print('\n=== 2. liquidar ===')
    probar_liquidar()
    print('\n=== 3. la base y el modelo propio ===')
    probar_modelo()
    print('\n=== 4. las casas ===')
    probar_casas()
    print('\n=== 5. sin base no se ofrece ===')
    probar_sin_base()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
