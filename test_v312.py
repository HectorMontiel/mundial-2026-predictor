#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v312.

El usuario: «encuentra los patrones de las que no se cumplieron para darme
apuestas más certeras… valídalo con simulaciones de los partidos de hoy»;
«arregla ese workflow roto desde raíz»; «botones de pasado mañana y de
enviar todo, con todas las estadísticas para pasarlas a una IA»; «dame un
system prompt para un agente de IA».

Lo que se vigila:

  1. «METER» EN FÚTBOL: franja 70-80 %, cuota < 1,35 y sin los mercados que
     fallan (doble y goles, remates, hándicap); fuera del fútbol no cambia;
     y la medición que lo sostiene sigue diciendo lo mismo.
  2. EL WORKFLOW: ningún `--autostash … || true` suelto; los tres usan
     `git_sin_conflictos.py`; el paso final resuelve antes de commitear; y
     el script une filas de CSV y no toca código.
  3. TELEGRAM: botones de pasado mañana y de «todo», con el documento de
     `formato_ia` (guía, 🎯 meter, modelo, mercados).
  4. EL AGENTE: el documento con el prompt existe y dice lo esencial.

Ejecutar:  python test_v312.py
"""
import json
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_el_meter():
    import veredicto_pick as vp
    check((vp.METER_FUTBOL_MIN, vp.METER_FUTBOL_MAX,
           vp.CUOTA_METER_FUTBOL_MAX) == (0.70, 0.80, 1.35),
          'meter en fútbol: 70-80 % y cuota < 1,35')
    check(set(vp.MERCADOS_NO_METER_FUTBOL) == {'Doble y goles', 'Remates',
                                                 'Remates a puerta', 'Handicap'},
          'y sin los mercados que fallan más de lo que prometen')

    # v335 — donde la casa cotiza (goles, ganador, doble…) decide su precio:
    # casa sin margen ≥ 74 %, modelo ≥ 70 %, cuota 1,15-1,35. Por eso el
    # pick lleva `p_mercado`; sin él, esas apuestas no se meten.
    def ev(prob, cuota, mercado='Goles', dep='Fútbol', casa=0.78):
        v = vp.evaluar({'apuesta': 'x', 'mercado': mercado, 'prob': prob,
                        'cuota': cuota, 'deporte': dep})
        v['pick'] = {'deporte': dep, 'mercado': mercado, 'cuota': cuota,
                     'p_mercado': casa}
        if v['veredicto'] == vp.METER and vp.franja_futbol(v):
            return vp.NO_METER
        return v['veredicto']
    check(ev(.75, 1.25) == vp.METER, 'un 75 % a 1,25 en goles se mete')
    # v312 medía que el modelo al 80-85 % acertaba 67 %. Con la casa de
    # acuerdo deja de pasar (v335: 83,3 % en 395 apuestas de la simulación),
    # así que lo que se vigila ahora es que SIN la casa no entre.
    check(ev(.84, 1.20, casa=0.70) == vp.NO_METER,
          'un 84 % del modelo sin la casa de acuerdo no se mete')
    check(ev(.84, 1.20, casa=0.82) == vp.METER,
          'y con la casa de acuerdo sí (v335: 83,3 % medido)')
    check(ev(.75, 1.25, casa=None) == vp.NO_METER,
          'sin precio de la casa, una apuesta de goles no se mete')
    check(ev(.75, 1.40) == vp.NO_METER, 'a cuota 1,40 no')
    check(ev(.75, 1.25, 'Doble y goles') == vp.NO_METER,
          '«doble y goles» no se mete')
    check(ev(.75, 1.25, 'Remates a puerta') == vp.NO_METER,
          'remates a puerta no se mete')
    check(ev(.84, 1.20, 'Ganador', 'Tenis') == vp.METER,
          'fuera del fútbol no cambia (no está medido)')
    check(vp.evaluar({'apuesta': 'x', 'mercado': 'Goles', 'prob': .85,
                      'cuota': 1.3})['veredicto'] == vp.METER,
          'el veredicto general (Soñadora, combinadas) no cambia')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('_vp.franja_futbol(v)' in src,
          'la tarjeta aplica la franja al decidir qué enseña')
    r = json.load(open('_v312_patrones.json', encoding='utf-8'))
    for tramo in ('eleccion', 'prueba'):
        bt = r[tramo]['bootstrap']
        check(bt['p5_pts'] > 0 and r[tramo]['ahora']['acierto']
              > r[tramo]['antes']['acierto'],
              '%s: más verdes que antes (%.1f %% → %.1f %%, p5 %+.1f pts)'
              % (tramo, 100 * r[tramo]['antes']['acierto'],
                 100 * r[tramo]['ahora']['acierto'], bt['p5_pts']))
    h = r['hoy']
    check(h['ahora']['acierto'] >= h['antes']['acierto'],
          'hoy (%s): %.1f %% → %.1f %%' % (h['dia'], 100 * h['antes']['acierto'],
                                          100 * h['ahora']['acierto']))


def probar_el_workflow():
    import git_sin_conflictos as g
    import yaml
    for nombre in ('retrain_leagues', 'precalculo_dia', 'recalibrar'):
        t = open('.github/workflows/%s.yml' % nombre, encoding='utf-8').read()
        yaml.safe_load(t)
        sueltos = [l for l in t.splitlines()
                   if 'autostash' in l and '|| true' in l
                   and not l.strip().startswith('#')]
        check(not sueltos, '%s: ningún `--autostash … || true` suelto' % nombre)
        check('python git_sin_conflictos.py publicar' in t,
              '%s: publica con git_sin_conflictos.py' % nombre)
    t = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    i = t.index('- name: Commitear artefactos actualizados')
    j = t.index('git add -A team_stats_', i)
    check('python git_sin_conflictos.py resolver' in t[i:j],
          'el paso final resuelve lo que quede a medio fundir ANTES de commitear')
    u = g.unir_csv('h\n1\n2\n', 'h\n1\n3\n')
    check(u.splitlines() == ['h', '1', '2', '3'],
          'une las filas de los dos lados sin repetir (%r)' % u)
    check(g.unir_csv('h\n1\n', 'x\n9\n') == 'x\n9\n',
          'si las cabeceras no casan, gana lo recién generado')
    check(g.es_codigo('a.py') and g.es_codigo('.github/workflows/x.yml')
          and not g.es_codigo('lineas_jugador_hist/2026-09.csv'),
          'el código no se toca; los artefactos sí')


def probar_telegram():
    src = open('dashboard_ui.py', encoding='utf-8').read()
    for k in ('tg_send_hoy', 'tg_send_manana', 'tg_send_pasado', 'tg_send_todo'):
        check("key='%s'" % k in src, 'existe el botón %s' % k)
    check("_fia.texto(r, _dias)" in src and "_md_dia.dia_cdmx(i) for i in (0, 1, 2)"
          in src, '«todo» manda hoy, mañana y pasado en un solo documento')
    import formato_ia as fi
    check('GUÍA DE LECTURA' in fi.GUIA and 'casa sin margen' in fi.GUIA,
          'el documento empieza con la guía para la IA')
    r = {'pronosticos': [{
        'deporte': 'Fútbol', 'partido': 'Local vs Visita', 'liga': 'Liga X',
        'clave_liga': 'x', 'fecha': '2030-01-01', 'inicio': '2030-01-01 20:00:00',
        'board': {'Gana Local': .5, 'Empate': .3, 'Gana Visita': .2},
        'goles_lineas': {'1.5': .7, '2.5': .45, '3.5': .2},
        'goles_lambda': 2.3, 'mercados': []}]}
    import mercados_dia as md
    orig = md.partidos_del_dia
    md.partidos_del_dia = lambda r_, d, con_extras=True: [{
        'deporte': 'Fútbol', 'partido': 'Local vs Visita', 'liga': 'Liga X',
        'clave_liga': 'x', 'hora': '14:00', 'inicio': '2030-01-01 20:00:00',
        'mercados': [], 'notas': []}]
    try:
        t = fi.texto(r, ['2030-01-01'])
    finally:
        md.partidos_del_dia = orig
    check('Local vs Visita' in t and ('🎯 METER' in t or '🚫 Nada que meter' in t)
          and 'MODELO 1X2' in t and 'MODELO goles' in t,
          'cada partido lleva meter/nada, el 1X2 y los goles del modelo')


def probar_el_agente():
    t = open('AGENTE_IA_APUESTAS.md', encoding='utf-8').read()
    for pieza in ('Prompt de sistema', '🎯 METER', 'ESPERAR', 'NO METER',
                  'alineación', 'No inventes datos', 'Formato de salida'):
        check(pieza in t, 'el prompt del agente trata «%s»' % pieza)


if __name__ == '__main__':
    print('=== 1. el meter ===')
    probar_el_meter()
    print('\n=== 2. el workflow ===')
    probar_el_workflow()
    print('\n=== 3. telegram ===')
    probar_telegram()
    print('\n=== 4. el agente ===')
    probar_el_agente()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
