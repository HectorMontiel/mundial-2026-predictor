#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v340.

El usuario (captura del móvil): «los insights que me da no le veo utilidad,
prefiero que no estén»; «veo partidos en los que me das apuesta pero no veo
si se mete o no se mete»; «lo de Capa 1 tómalo en cuenta en las apuestas que
me despliegas»; «en la Soñadora, con el filtro de hoy no me das partidos de
hoy y con el rango no respetas las fechas»; y «un contador de verdes y rojas
del día, con el porcentaje, que no ocupe mucho».

Lo que se vigila:
  1. SOÑADORA: con «hoy» sólo partidos de hoy en CDMX; con un rango, sólo
     los de ese rango; nunca uno ya empezado.
  2. LA TARJETA: la apuesta que se mete dice «🎯 SE METE», en verde, marca
     Capa 1 si viene de ahí y no lleva el renglón 💡; los insights se van al
     desplegable de Análisis.
  3. EL MARCADOR: verdes, rojas, porcentaje y por jugar, en una franja, en
     lugar de las cuatro cifras.

Ejecutar:  python test_v340.py
"""
import datetime as dt

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_sonadora():
    import sonadora_ui as s
    ahora = dt.datetime(2026, 10, 7, 18, 0, tzinfo=dt.timezone.utc)   # 12:00 CDMX
    r = {'pronosticos': [
        {'partido': 'A vs B', 'inicio': '2026-10-07T23:00:00Z'},   # hoy 17:00 CDMX
        {'partido': 'C vs D', 'inicio': '2026-10-08T01:30:00Z'},   # hoy 19:30 CDMX (UTC ya es 8)
        {'partido': 'E vs F', 'inicio': '2026-10-08T20:00:00Z'},   # mañana
        {'partido': 'G vs H', 'inicio': '2026-10-09T20:00:00Z'},   # pasado
        {'partido': 'I vs J', 'inicio': '2026-10-07T15:00:00Z'},   # hoy, ya empezado
        {'partido': 'K vs L', 'inicio': '2026-10-07T23:00:00Z', 'jugado': True},
    ], 'otra_cosa': 1}
    hoy = [p['partido'] for p in s.filtrar_por_dias(r, '2026-10-07', None, ahora)['pronosticos']]
    check(hoy == ['A vs B', 'C vs D'],
          'con «hoy» sólo los de hoy en CDMX y sin los empezados (%s)' % hoy)
    rg = [p['partido'] for p in s.filtrar_por_dias(
        r, '2026-10-08', ['2026-10-08', '2026-10-09'], ahora)['pronosticos']]
    check(rg == ['E vs F', 'G vs H'], 'el rango se respeta (%s)' % rg)
    check(s.filtrar_por_dias(r, None, None, ahora) is r, 'sin día elegido no toca nada')
    check(len(r['pronosticos']) == 6 and s.filtrar_por_dias(r, '2026-10-07', None, ahora)
          ['otra_cosa'] == 1, 'devuelve una copia y conserva el resto del barrido')
    src = open('sonadora_ui.py', encoding='utf-8').read()
    check('r = filtrar_por_dias(r, dia, dias)' in src, 'la pantalla filtra antes de armar')


class _St:
    def __init__(self):
        self.txt = []

    def markdown(self, t, **k):
        self.txt.append(str(t))


def probar_tarjeta():
    import modo_modelo as mm
    base = {'apuesta': 'Goles: Más de 1.5', 'prob': 0.78, 'cuota': 1.23,
            'score': 0.96, 'cuota_justa': 1.28, 'verde': False, 'motivo': 'valor',
            'incierto': True, 'razon': 'Santos mete 1,5', 'puesto_valor': 1}
    f = _St()
    mm._bloque_recomendada(f, dict(base, veredicto_vp='meter'), 'x', 0)
    t = ''.join(f.txt)
    check('🎯 SE METE' in t and 'mm-rec-si' in t, 'lo que se mete lo dice, en verde')
    check('Alta incertidumbre' not in t, 'sin la coletilla que lo contradecía')
    check('💡' not in t and 'Santos mete' not in t, 'sin el renglón 💡')
    f = _St()
    mm._bloque_recomendada(f, dict(base, veredicto_vp='meter', elite=True), 'x', 0)
    check('🏆 CAPA 1' in ''.join(f.txt), 'la apuesta de Capa 1 se marca')
    f = _St()
    mm._bloque_recomendada(f, dict(base, veredicto_vp='meter', puesto_valor=2), 'x', 0)
    check('🎯 SE METE · 2ª' in ''.join(f.txt), 'la segunda también dice que se mete')
    f = _St()
    mm._bloque_recomendada(f, dict(base), 'x', 0)
    check('APUESTA RECOMENDADA' in ''.join(f.txt), 'sin veredicto, el bloque de siempre')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('_porque_detalle.extend(_lineas_tarjeta)' in src
          and "st.caption('  ·  '.join(_lineas_tarjeta))" not in src,
          'los insights (patrón y rasgo de la liga) se van a Análisis')


def probar_marcador():
    import estilo_ui as eu
    h = eu.marcador(12, 3, 21)
    check('<b>12</b><i>verdes</i>' in h and '<b>3</b><i>rojas</i>' in h,
          'el marcador cuenta verdes y rojas')
    check('<b>80 %</b><i>acierto</i>' in h and '<b>21</b><i>por jugar</i>' in h,
          'con el porcentaje y lo que queda por jugar')
    check('width:80.0%' in h, 'y la barra reparte verde y rojo')
    check('<b>—</b><i>acierto</i>' in eu.marcador(0, 0, 5), 'sin liquidadas no inventa un %')
    check('.marcador' in eu.CSS_VIDRIO, 'con su estilo de cristal')
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check('_estilo.marcador(' in d and 'f1, f2, f3, f4 = st.columns(4)' not in d,
          'en la pantalla del día, en lugar de las cuatro cifras')
    check('def _marcador_del_dia(' in d and '_pg.validar(_p)' in d,
          'contado con lo mismo que los finalizados')


if __name__ == '__main__':
    print('=== 1. la Soñadora ===')
    probar_sonadora()
    print('\n=== 2. la tarjeta ===')
    probar_tarjeta()
    print('\n=== 3. el marcador ===')
    probar_marcador()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
