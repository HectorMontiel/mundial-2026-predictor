# -*- coding: utf-8 -*-
"""
v327 — pruebas: lo que ya empezó no sale en «Sin jugar», y lo que no se mete
no sale en la lista principal aunque no valga la decisión del cron.

  1. `sacar_empezados`: un partido cuyo inicio ya pasó se archiva como el
     cron (jugado, «en juego» mientras dura, con lo que se recomendaba antes),
     no se duplica si el archivo del día ya lo trae, y se anota en el registro
     igual que lo anotaba su tarjeta.
  2. `render` con «Sin jugar»: no pinta ningún empezado.
  3. El cron vuelve a cocinar al cambiar el día UTC.

Uso: python test_v327.py
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import time

FALLOS = []
TMP = tempfile.mkdtemp(prefix='v327_')
os.environ['PRONOSTICOS_EMITIDOS'] = os.path.join(TMP, 'emitidos.json')
os.environ['PREFERENCIAS_USUARIO'] = os.path.join(TMP, 'prefs.json')


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _picks():
    """Partidos de fútbol con modelo del precálculo, con la decisión del cron
    calculada aquí (en un temporal) para no depender de la hora."""
    import decisiones_dia as dd
    doc = json.load(open('pronostico_dia.json', encoding='utf-8'))
    doc.pop('decisiones', None)
    ruta = os.path.join(TMP, 'pronostico_dia.json')
    json.dump(doc, open(ruta, 'w', encoding='utf-8'), ensure_ascii=False)
    dd.anadir(ruta)
    doc = json.load(open(ruta, encoding='utf-8'))
    dd.adjuntar(doc)
    return [p for p in doc['datos']['pronosticos']
            if p.get('deporte') == 'Fútbol' and not p.get('jugado')
            and p.get('prob') is not None and not p.get('sin_modelo')]


def _hace(minutos):
    import pandas as pd
    return (pd.Timestamp.now('UTC') - pd.Timedelta(minutes=minutos)).strftime(
        '%Y-%m-%d %H:%M:%S')


def probar_sacar(ps):
    import modo_modelo as mm
    import pronosticos_guardados as pg
    pg.recargar()
    base = copy.deepcopy(ps[:8])
    for p in base[:3]:
        p['inicio'] = _hace(60)         # empezó hace una hora: en juego
    base[3]['inicio'] = _hace(300)      # hace cinco horas: terminado
    for p in base[4:]:
        p['inicio'] = _hace(-180)       # dentro de tres horas: sin jugar
    jugados = [dict(copy.deepcopy(base[2]), jugado=True, goles_home=1, goles_away=0)]
    out = mm.sacar_empezados(copy.deepcopy(base), jugados)
    sin_jugar = [p for p in out if not p.get('jugado')]
    arch = [p for p in out if p.get('jugado')]
    check(len(sin_jugar) == 4, 'quedan sin jugar sólo los que no han empezado (%d)'
          % len(sin_jugar))
    check(len(arch) == 3, 'se archivan los empezados, sin repetir el que ya estaba '
          'en el archivo del día (%d)' % len(arch))
    en_juego = [p['partido'] for p in arch if p.get('en_juego')]
    check(len(en_juego) == 2 and base[3]['partido'] not in en_juego,
          '«en juego» los de hace una hora; el de hace cinco ya no')
    ok_prev = all(p.get('recomendadas_previas') is not None
                  and [r['apuesta'] for r in p['recomendadas_previas']]
                  == [r['apuesta'] for r in mm.metidas(mm.recos_tarjeta(
                      next(b for b in base if b['partido'] == p['partido'])))]
                  for p in arch)
    check(ok_prev, 'con la apuesta que se recomendaba antes de empezar')
    anotados = [p['partido'] for p in base[:4] if pg.ya_anotado(p)
                or not mm.metidas(mm.recos_tarjeta(p))]
    check(len(anotados) == 4, 'y anotados en el registro como los anotaba su tarjeta')


class _Caja:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class St:
    def __init__(self):
        self.session_state = {}

    def __getattr__(self, n):
        def f(*a, **k):
            if n == 'columns':
                k_ = a[0] if a else 2
                return [_Caja() for _ in range(k_ if isinstance(k_, int) else len(k_))]
            if n in ('expander', 'container'):
                return _Caja()
            if n == 'selectbox':
                return 'Hora'
            if n == 'radio':
                import modo_modelo as mm
                return mm.ESTADO_SIN_JUGAR
            return False
        return f


def probar_render(ps):
    import modo_modelo as mm
    import pronosticos_guardados as pg
    lista = copy.deepcopy(ps[:30])
    empezados = {p['partido'] for p in lista[:6]}
    for p in lista[:6]:
        p['inicio'] = _hace(45)
    for p in lista[6:]:
        p['inicio'] = _hace(-180)
    pintadas = []
    _t = mm.tarjeta
    mm.tarjeta = lambda st, p, **k: pintadas.append(p.get('partido')) or _t(st, p, **k)
    try:
        with pg.lote():
            mm.render(St(), lista, pintar=True)
    finally:
        mm.tarjeta = _t
    check(not (set(pintadas) & empezados),
          '«Sin jugar» no pinta ningún partido empezado (%d pintados)' % len(pintadas))


def probar_cron():
    y = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('Cocinado otro día (UTC): se cocina.' in y and '+%F' in y,
          'el cron cocina al cambiar el día UTC aunque el precálculo sea reciente')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ps = _picks()
    print('=== 1. sacar los empezados ===')
    probar_sacar(ps)
    print('\n=== 2. render ===')
    probar_render(ps)
    print('\n=== 3. el cron ===')
    probar_cron()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
