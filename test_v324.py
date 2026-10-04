# -*- coding: utf-8 -*-
"""
v324 — pruebas: «Nada que meter».

Sobre el `pronostico_dia.json` que haya en el repo, con las decisiones
calculadas como las calcula el cron:

  1. LA LÍNEA QUE SE METE. Con la búsqueda de otra línea del mismo mercado
     apagada, `recomendadas` es la de antes; encendida, todo lo que se metía
     se sigue metiendo en el mismo partido, todo lo nuevo pasa la regla, y
     no aparece ningún «Nada que meter» que antes no estuviera.
  2. `nada_que_meter` dice lo mismo que la tarjeta (sus `metidas` vacías), y
     sin precálculo no esconde nada que no sepa.
  3. `render` saca esos partidos de la lista principal a un desplegable con
     su porqué, no pinta sus tarjetas si no se piden, y el registro de
     pronósticos queda idéntico al de antes.

Uso: python test_v324.py
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


TMP = tempfile.mkdtemp(prefix='v324_')
RUTA = os.path.join(TMP, 'pronostico_dia.json')
# Nada de esta prueba escribe en los ficheros del repositorio.
os.environ['PRONOSTICOS_EMITIDOS'] = os.path.join(TMP, 'emitidos.json')
os.environ['PREFERENCIAS_USUARIO'] = os.path.join(TMP, 'prefs.json')


def preparar():
    doc = json.load(open('pronostico_dia.json', encoding='utf-8'))
    doc.pop('decisiones', None)
    json.dump(doc, open(RUTA, 'w', encoding='utf-8'), ensure_ascii=False)
    import decisiones_dia as dd
    check(dd.anadir(RUTA), 'el cron calcula y escribe las decisiones')
    doc = json.load(open(RUTA, encoding='utf-8'))
    check(dd.adjuntar(doc) > 0, 'y la app las adjunta')
    return doc


def _bloques(mm, p):
    _rm = mm.remates_tarjeta(p)
    return {'Córners': mm.corners_tarjeta(p),
            'Tarjetas': mm.tarjetas_tarjeta(p),
            'Remates': (_rm or {}).get('totales'),
            'Remates a puerta': (_rm or {}).get('a_puerta')}


def probar_linea(doc):
    """1. La línea que se mete: sólo añade, y lo que añade pasa la regla."""
    import modo_modelo as mm
    import veredicto_pick as vp
    picks = [p for p in doc['datos']['pronosticos']
             if not p.get('jugado') and not p.get('solo_mercado')
             and not p.get('sin_modelo') and p.get('prob') is not None
             and str(p.get('deporte') or 'Fútbol') == 'Fútbol']
    _ld = mm._lineas_dignas
    antes, ahora = {}, {}
    for p in picks:
        b = _bloques(mm, p)
        k = (p.get('partido'), str(p.get('inicio')))
        try:
            mm._lineas_dignas = lambda *a, **kw: []
            antes[k] = mm.metidas(mm.recomendadas(copy.deepcopy(p), b,
                                                  n=mm.MAX_RECOMENDADAS))
        finally:
            mm._lineas_dignas = _ld
        ahora[k] = mm.metidas(mm.recomendadas(copy.deepcopy(p), b,
                                              n=mm.MAX_RECOMENDADAS))
    perdidos = [k for k in antes if antes[k] and not ahora[k]]
    check(len(picks) > 20 and not perdidos,
          'ningún partido que tenía algo que meter se queda sin nada '
          '(%d partidos)%s' % (len(picks), '' if not perdidos else ': %s' % perdidos[:3]))
    sin_antes = sum(1 for k in antes if not antes[k])
    sin_ahora = sum(1 for k in ahora if not ahora[k])
    print('      «Nada que meter»: %d antes, %d ahora, de %d partidos'
          % (sin_antes, sin_ahora, len(picks)))
    check(sin_ahora <= sin_antes, 'no aparece ningún «Nada que meter» nuevo')
    viejas = {(k, r.get('apuesta')) for k in antes for r in antes[k]}
    nuevas = [(k, r) for k in ahora for r in ahora[k]
              if (k, r.get('apuesta')) not in viejas]
    malas = []
    for k, r in nuevas:
        pm, c = r.get('prob_meter'), r.get('cuota')
        ok = (r.get('elite') or (
            str(r.get('mercado')) not in vp.MERCADOS_NO_METER_FUTBOL
            and pm is not None
            and vp.METER_FUTBOL_MIN <= pm <= vp.METER_FUTBOL_MAX
            and (c is None or c < vp.CUOTA_METER_FUTBOL_MAX)))
        if not ok:
            malas.append((k[0], r.get('apuesta'), pm, c))
    check(not malas, 'todo lo nuevo pasa la regla de «meter» (%d apuestas '
          'nuevas)%s' % (len(nuevas), '' if not malas else ': %s' % malas[:3]))
    # la regla de siempre sigue mandando: nada de lo nuevo viene de otro
    # mercado (sólo de otra línea del mismo)
    for k in ahora:
        merc = [str(r.get('mercado')) for r in ahora[k]]
        if len(merc) != len(set(merc)):
            check(False, 'dos apuestas del mismo mercado en %s' % k[0])
            break
    else:
        check(True, 'nunca dos líneas del mismo mercado en un partido')


def probar_nada(doc):
    """2. `nada_que_meter` dice lo que dice la tarjeta."""
    import decisiones_dia as dd
    import modo_modelo as mm
    ps = [p for p in doc['datos']['pronosticos'] if not p.get('jugado')]
    distintos, n_nada = [], 0
    for p in ps:
        if p.get('sin_modelo') or p.get('prob') is None or p.get('solo_mercado'):
            continue
        r = dd.tarjeta_de_pick(p)
        if r is None:
            continue
        n_nada += not mm.metidas(r)
        if mm.nada_que_meter(p) != (not mm.metidas(r)):
            distintos.append(p.get('partido'))
    check(n_nada > 0 and not distintos,
          '`nada_que_meter` coincide con la tarjeta (%d sin nada)%s'
          % (n_nada, '' if not distintos else ': %s' % distintos[:3]))
    # v327 — sin la decisión del cron (pasada la medianoche UTC) ya no se
    # deja el partido en la lista: se calcula aquí, y tiene que decir lo mismo
    # que el cron
    con_modelo = [p for p in ps if not (p.get('sin_modelo') or p.get('prob') is None
                                        or p.get('solo_mercado'))
                  and dd.tarjeta_de_pick(p) is not None][:25]
    distintos_vivo = []
    for p in con_modelo:
        q = copy.deepcopy(p)
        q.pop(dd.CLAVE_PICK, None)
        q['_recomendadas'] = mm.recomendadas(q, None, n=mm.MAX_RECOMENDADAS)
        if mm.nada_que_meter(q) != (not mm.metidas(dd.tarjeta_de_pick(p))):
            distintos_vivo.append(p.get('partido'))
    check(con_modelo and not distintos_vivo,
          'sin precálculo se calcula aquí y dice lo mismo que el cron (%d)%s'
          % (len(con_modelo), '' if not distintos_vivo else ': %s' % distintos_vivo[:3]))
    textos = [mm.por_que_no(p) for p in ps if mm.nada_que_meter(p)]
    check(textos and all(isinstance(t, str) and t for t in textos),
          'cada partido sin nada trae su porqué (%d)' % len(textos))
    print('      ej.: %s' % (textos[:2],))


class _Caja:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class St:
    """Un Streamlit de mentira que apunta los desplegables que abre."""

    def __init__(self, ver=False):
        self.session_state = {}
        self.desplegables = []
        self.textos = []
        self.ver = ver

    def __getattr__(self, n):
        def f(*a, **k):
            if n == 'columns':
                k_ = a[0] if a else 2
                return [_Caja() for _ in range(k_ if isinstance(k_, int) else len(k_))]
            if n == 'expander':
                self.desplegables.append(a[0] if a else '')
                return _Caja()
            if n == 'container':
                return _Caja()
            if n == 'selectbox':
                return 'Hora'
            if n == 'radio':
                import modo_modelo as mm
                return mm.ESTADO_SIN_JUGAR
            if n == 'toggle':
                return self.ver
            if n in ('markdown', 'caption', 'info'):
                self.textos.append(str(a[0]) if a else '')
            return False
        return f


def _registro(pg, nombre):
    pg.FICHERO = os.path.join(TMP, nombre)
    if os.path.exists(pg.FICHERO):
        os.remove(pg.FICHERO)
    pg.recargar()


def _leido(pg):
    pg.volcar()
    d = json.load(open(pg.FICHERO, encoding='utf-8')) if os.path.exists(pg.FICHERO) else {}
    return canon({k: {c: v for c, v in e.items() if c != 'anotado'}
                  for k, e in d.items()})


def probar_render(doc):
    """3. La lista principal sin ellos, el desplegable con ellos, y el
    registro igual."""
    import modo_modelo as mm
    import pronosticos_guardados as pg
    import time as _time
    import horario as _hz
    lista = [p for p in doc['datos']['pronosticos'] if not p.get('jugado')][:60]
    # v327 — los que ya empezaron salen de «sin jugar» antes de llegar aquí
    _empezo = lambda p: (_hz._a_utc(p.get('inicio')) is not None
                         and _hz._a_utc(p.get('inicio')).timestamp() <= _time.time())
    sin_nada = {p.get('partido') for p in lista
                if mm.nada_que_meter(p) and not _empezo(p)}
    pintadas = []
    _t, _nq = mm.tarjeta, mm.nada_que_meter
    mm.tarjeta = lambda st, p, **k: pintadas.append(p.get('partido')) or _t(st, p, **k)
    try:
        # antes: sin separar, todas las tarjetas
        _registro(pg, 'antes.json')
        mm.nada_que_meter = lambda p: False
        pagina = mm.TARJETAS_POR_PAGINA
        mm.TARJETAS_POR_PAGINA = 200
        with pg.lote():
            mm.render(St(), copy.deepcopy(lista), pintar=True)
        antes = _leido(pg)
        mm.nada_que_meter = _nq
        # ahora
        del pintadas[:]
        _registro(pg, 'ahora.json')
        st = St()
        with pg.lote():
            mm.render(st, copy.deepcopy(lista), pintar=True)
        ahora = _leido(pg)
    finally:
        mm.tarjeta, mm.nada_que_meter = _t, _nq
        mm.TARJETAS_POR_PAGINA = pagina
    check(sin_nada and not (set(pintadas) & sin_nada),
          'ningún partido sin nada que meter se pinta en la lista (%d de %d)'
          % (len(sin_nada), len(lista)))
    rot = [d for d in st.desplegables if str(d).startswith('🚫 Sin nada que meter')]
    check(rot == ['🚫 Sin nada que meter (%d)' % len(sin_nada)],
          'y van a su desplegable: %s' % rot)
    lineas = [t for t in st.textos if t.startswith('- **')]
    check(lineas and sum(t.count('\n- **') + 1 for t in lineas) == len(sin_nada),
          'con una línea por partido')
    check(antes == ahora and len(json.loads(antes)) > 0,
          'el registro de pronósticos es idéntico al de antes (%d partidos)'
          % len(json.loads(antes)))
    # y si se piden, sus tarjetas se pintan
    del pintadas[:]
    mm.tarjeta = lambda st, p, **k: pintadas.append(p.get('partido')) or _t(st, p, **k)
    try:
        _registro(pg, 'ver.json')
        with pg.lote():
            mm.render(St(ver=True), copy.deepcopy(lista), pintar=True)
    finally:
        mm.tarjeta = _t
    check(len(set(pintadas) & sin_nada) == min(len(sin_nada), mm.TARJETAS_POR_PAGINA),
          'con «Ver sus tarjetas» se pintan (las %d primeras)' % mm.TARJETAS_POR_PAGINA)


if __name__ == '__main__':
    print('=== 0. el cron ===')
    doc = preparar()
    print('\n=== 1. la línea que se mete ===')
    probar_linea(doc)
    print('\n=== 2. nada que meter ===')
    probar_nada(doc)
    print('\n=== 3. render ===')
    probar_render(doc)
    shutil.rmtree(TMP, ignore_errors=True)
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
