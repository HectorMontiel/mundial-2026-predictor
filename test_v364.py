#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v364.

El usuario: «el análisis no me lo das por equipo, sólo el global»; «un filtro
más: ordenar por las que tengan la estrellita de elige»; «en las arriesgadas
no quiero mucho texto, que entren ambos marcan, y en verde cuando se cumplen,
en rojo cuando no, con su semáforo de conversión»; «la Capa 1 con ⭐ por
forma reciente: evalúalo».

Lo que se vigila:
  1. LA TABLA: la línea al 70 %+ también de cada equipo.
  2. EL ORDEN «⭐ ELIGE primero».
  3. LAS ARRIESGADAS: ambos marcan con su regla; las jugadas en verde/rojo;
     la tasa de los últimos días; poco texto.
  4. LO MEDIDO: ambos marcan calibrado; la forma NO separa la Capa 1 (no se
     marca).

Ejecutar:  python test_v364.py
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


DOC = {'k': {'corners': 11.6, 'tiros': 20.0, 'a_puerta': 43.0}, 'partidos': {'A vs B|mls': {
    'local': {'tiros': 15.0, 'a_puerta': 6.0, 'goles': 1.9, 'corners': 5.8, 'tarjetas': 2.0},
    'visitante': {'tiros': 11.0, 'a_puerta': 4.0, 'goles': 1.3, 'corners': 4.3, 'tarjetas': 2.4}}}}


def probar_tabla_y_orden():
    import decisiones_dia as dd
    import modo_modelo as mm
    import tiros_equipo as te
    viejo = te._dia
    te._dia = lambda ruta=None: DOC
    try:
        mc = mm.metodo_contexto({'partido': 'A vs B', 'clave_liga': 'mls'})
        h = mm._tabla_metodo_html({'partido': 'A vs B', 'clave_liga': 'mls', 'deporte': 'Fútbol'})
    finally:
        te._dia = viejo
    check(mc['corners']['linea_l'] is not None and mc['corners']['p_l'] >= 0.70
          and mc['tiros']['linea_v'] is not None,
          'la línea al 70 %%+ también por equipo (córners A +%s al %.0f %%)'
          % (mc['corners']['linea_l'], 100 * mc['corners']['p_l']))
    check('A +' in h and 'B +' in h, 'y la tabla la enseña bajo la del total')
    con = {'partido': 'X vs Y', 'inicio': '2099-01-01T10:00:00Z', dd.CLAVE_PICK: {
        'recomendadas_tarjeta': [{'apuesta': 'a', 'veredicto_vp': 'meter', 'prob': 0.84, 'cuota': 1.3}]}}
    sin = {'partido': 'Z vs W', 'inicio': '2099-01-01T08:00:00Z', dd.CLAVE_PICK: {
        'recomendadas_tarjeta': [{'apuesta': 'b', 'veredicto_vp': 'meter', 'prob': 0.76, 'cuota': 1.3}]}}
    nada = {'partido': 'Q vs R', 'inicio': '2099-01-01T07:00:00Z'}
    orden = [p['partido'] for p in sorted([nada, sin, con], key=mm._k_elige)]
    check(orden == ['X vs Y', 'Z vs W', 'Q vs R'] and '⭐ ELIGE primero' in mm.ORDENES,
          'el orden «⭐ ELIGE primero»: ⭐, luego «se mete», luego el resto (%s)' % orden)


def probar_arriesgadas():
    import arriesgadas as ar
    import mercado_implicito as mi
    import tiros_equipo as te
    v1, v2 = te._dia, mi.del_partido
    te._dia = lambda ruta=None: DOC
    mi.del_partido = lambda h, a, **k: {'btts': 0.60, 'btts_cuotas': {'si': 1.60, 'no': 2.30}}
    try:
        pats = ar.patas_del_partido({'partido': 'A vs B', 'clave_liga': 'mls',
                                     'inicio': '2099-01-01T12:00:00Z'})
    finally:
        te._dia, mi.del_partido = v1, v2
    ap = [x['apuesta'] for x in pats]
    check('Ambos marcan: Sí' in ap and 'Ambos marcan: No' not in ap,
          'ambos marcan entra con su regla (sí al %.0f %%)' % (100 * [x for x in pats if x['obj'] == 'btts'][0]['prob']))
    tmp = tempfile.mkdtemp()
    try:
        ruta = os.path.join(tmp, 'a.csv')
        import pandas as pd
        pd.DataFrame([
            {'dia': '2026-10-11', 'partido': 'A vs B', 'inicio': 'x', 'apuesta': 'Ambos marcan: Sí',
             'obj': 'btts', 'tipo': 'btts', 'lado': 'total', 'linea': 1.0, 'prob': 0.6, 'cuota': 1.6,
             'real': 1.0, 'cumple': 1},
            {'dia': '2026-10-11', 'partido': 'C vs D', 'inicio': 'y', 'apuesta': 'Tiros: Más de 24.5',
             'obj': 'tiros', 'tipo': 'total', 'lado': 'total', 'linea': 24.5, 'prob': 0.6,
             'cuota': 1.7, 'real': 20.0, 'cumple': 0}]).to_csv(ruta, index=False)
        f = ar.finalizadas('2026-10-11', ruta=ruta)
        check([x['resultado_c1'] for x in f] == ['verde', 'rojo'],
              'las jugadas salen en verde o en rojo, con lo que pasó')
        import datetime as _dt
        hoy = _dt.date.today().isoformat()
        pd.read_csv(ruta).assign(dia=hoy).to_csv(ruta, index=False)
        check(ar.tasa(7, ruta=ruta).startswith('📈 7 días 50 %'),
              'y la tasa de conversión de los últimos días (%s)' % ar.tasa(7, ruta=ruta))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check("_ar.finalizadas(" in ui and "_ar.tasa()" in ui and 'La escalera de Playdoit desde donde' not in ui,
          'la sección: jugadas en verde/rojo, tasa en el título y poco texto')


def probar_medido():
    b = json.load(open('_v364_btts.json', encoding='utf-8'))
    cal = [x for x in b['calibracion'] if x['n'] >= 100]
    check(all(abs(x['acierta'] - x['promete']) <= 0.06 for x in cal),
          'ambos marcan con el método promete lo que acierta (%s)' % [(x['promete'], x['acierta']) for x in cal])
    f = json.load(open('_v364_capa1_forma.json', encoding='utf-8'))
    check(not any(v['pasa'] for v in f['hipotesis'].values()),
          'la forma reciente no separa las 🏆 en las dos mitades: no se marca la Capa 1')


if __name__ == '__main__':
    print('=== 1-2. tabla por equipo y orden ⭐ ===')
    probar_tabla_y_orden()
    print('\n=== 3. arriesgadas ===')
    probar_arriesgadas()
    print('\n=== 4. lo medido ===')
    probar_medido()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
