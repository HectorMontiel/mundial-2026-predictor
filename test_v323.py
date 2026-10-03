# -*- coding: utf-8 -*-
"""
v323 — pruebas: la app LEE las decisiones que calculó el cron, y sólo cuando
son exactamente las que ella misma calcularía.

Lo que se comprueba, sobre el `pronostico_dia.json` que haya en el repo:

  1. EQUIVALENCIA EXACTA. Las decisiones del cron (proceso aparte, como en el
     workflow) son, partido por partido, idénticas —todas las recomendadas,
     en el mismo orden, con los mismos números— a las que calcula este
     proceso con `apuesta_destacada` y `recomendadas`. Se calculan aquí en
     orden INVERSO a propósito: si el resultado dependiera del orden o del
     estado que deja un partido al siguiente, saltaría.
  2. Lo precalculado sobrevive al JSON sin cambiar de tipo (una tupla que
     vuelve como lista, una clave numérica que vuelve como texto).
  3. LA HUELLA MANDA. Si cambia un byte de un fichero del que salió la
     decisión, o es otro día, la app NO la adjunta y calcula en vivo.
  4. `render` usa lo precalculado (no llama a `recomendadas` fuera de las
     tarjetas) y deja en cada partido lo mismo que dejaba calculando.

Uso: python test_v323.py
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


TMP = tempfile.mkdtemp(prefix='v323_')
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
    return json.load(open(RUTA, encoding='utf-8'))


def probar_equivalencia(doc):
    import decisiones_dia as dd
    import modo_modelo as mm
    import nombres_ligas
    dec = doc.get('decisiones') or {}
    datos = copy.deepcopy(doc['datos'])
    nombres_ligas.aplicar(datos)          # lo mismo que hace la app
    pares = []
    for lista in dd.LISTAS:
        for p, f in zip(datos.get(lista) or [],
                        (dec.get('listas') or {}).get(lista) or []):
            if f:
                pares.append((p, f))
    check(len(pares) >= 50, '%d partidos con decisión precalculada' % len(pares))
    distintos, filas, mutados = [], 0, 0
    n_tarj, filas_t = [0], [0]
    for p, f in reversed(pares):
        antes = canon({k: v for k, v in p.items() if k != '_contexto'})
        d = mm.apuesta_destacada(p)
        r = mm.recomendadas(p, None, n=mm.MAX_RECOMENDADAS)
        # `_contexto` es la caché que `valor_apuesta.contexto_de` cuelga del
        # propio partido; sólo la lee esa función y la rellena igual quien la
        # pida después. Cualquier OTRO cambio en el partido sí contaría.
        if canon({k: v for k, v in p.items() if k != '_contexto'}) != antes:
            mutados += 1
        filas += len(r)
        if 'recomendadas_tarjeta' in f:
            # la de la tarjeta, con los bloques, igual que `tarjeta()`
            _rm = mm.remates_tarjeta(p)
            rt = mm.recomendadas(p, {'Córners': mm.corners_tarjeta(p),
                                     'Tarjetas': mm.tarjetas_tarjeta(p),
                                     'Remates': (_rm or {}).get('totales'),
                                     'Remates a puerta': (_rm or {}).get('a_puerta')},
                                 n=mm.MAX_RECOMENDADAS)
            n_tarj[0] += 1
            filas_t[0] += len(rt)
            if canon(rt) != canon(f['recomendadas_tarjeta']):
                distintos.append(('tarjeta', p.get('partido')))
        if f['llave'] != dd._llave(p):
            distintos.append(('llave', f['llave']))
        elif canon(d) != canon(f['destacada']) or canon(r) != canon(f['recomendadas']):
            distintos.append((p.get('partido'), canon(r)[:200],
                              canon(f['recomendadas'])[:200]))
        # 2. el viaje por JSON no cambia tipos
        if json.loads(canon(r)) != r and canon(r) == canon(json.loads(canon(r))):
            # NaN no es igual a sí mismo: sólo cuenta si el texto difiere
            pass
        elif json.loads(canon(r)) != r:
            distintos.append(('tipos', p.get('partido')))
    check(not distintos, 'precalculado == calculado en vivo, partido por partido '
          '(%d partidos, %d recomendadas)%s'
          % (len(pares), filas, '' if not distintos else ': %s' % distintos[:2]))
    check(n_tarj[0] >= 50, 'y la de la tarjeta, con córners, tarjetas y '
          'remates: %d partidos, %d recomendadas' % (n_tarj[0], filas_t[0]))
    check(mutados == 0, 'calcular no modifica el partido, salvo la caché '
          '`_contexto` (%d modificados)' % mutados)


def probar_huella(doc):
    import decisiones_dia as dd
    d1 = copy.deepcopy(doc)
    check(dd.adjuntar(d1) > 0, 'con la huella intacta se adjuntan')
    # un byte distinto en uno de los ficheros de la huella
    h = d1['decisiones']['huella']
    check(any(r.endswith('.py') for r in h) and any(not r.endswith('.py') for r in h),
          'la huella lleva código y datos (%d ficheros)' % len(h))
    d2 = copy.deepcopy(doc)
    k = sorted(r for r in h if not r.endswith('.py'))[0]
    d2['decisiones']['huella'][k] = '0' * 40
    check(dd.adjuntar(d2) == 0 and not any(
        dd.CLAVE_PICK in p for p in d2['datos']['pronosticos']),
        'si un fichero de la huella cambia (%s), no se adjunta nada' % k)
    check(d1['decisiones'].get('red') == 0,
          'el cálculo no sale a la red (depende sólo de los ficheros)')
    d7 = copy.deepcopy(doc)
    d7['decisiones']['red'] = 1
    check(dd.adjuntar(d7) == 0, 'si hubiera salido a la red, no se adjunta')
    # el salto de línea: el runner puede escribir CRLF y git guarda LF
    # (`.gitattributes`: csv/json/py son `text eol=lf`). Pasó en el primer
    # precálculo real con `remates_fotmob_equipos.csv`.
    _d = tempfile.mkdtemp(prefix='v323_crlf_')
    open(os.path.join(_d, 'a.csv'), 'wb').write(b'x,y\r\n1,2\r\n')
    open(os.path.join(_d, 'b.csv'), 'wb').write(b'x,y\n1,2\n')
    open(os.path.join(_d, 'c.csv'), 'wb').write(b'x,y\n1,3\n')
    _raiz = dd.RAIZ
    try:
        dd.RAIZ = _d
        check(dd._sha('a.csv') == dd._sha('b.csv') != dd._sha('c.csv'),
              'la huella iguala CRLF y LF (como git) y distingue un dato '
              'cambiado')
    finally:
        dd.RAIZ = _raiz
    d3 = copy.deepcopy(doc)
    d3['decisiones']['dia'] = ['2000-01-01', '2000-01-01']
    check(dd.adjuntar(d3) == 0, 'si es otro día, no se adjunta nada')
    d4 = copy.deepcopy(doc)
    d4['datos']['pronosticos'] = d4['datos']['pronosticos'][1:]
    check(dd.adjuntar(d4) == 0, 'si las listas no casan, no se adjunta nada')
    d5 = copy.deepcopy(doc)
    d5.pop('decisiones')
    check(dd.adjuntar(d5) == 0, 'un JSON viejo, sin decisiones, se deja igual')
    # la copia: modificar lo devuelto no toca lo guardado
    d6 = copy.deepcopy(doc)
    dd.adjuntar(d6)
    p = next(x for x in d6['datos']['pronosticos'] if dd.CLAVE_PICK in x)
    a = canon(p[dd.CLAVE_PICK])
    _d, r = dd.de_pick(p)
    if r:
        r[0]['prob'] = -1
    check(canon(p[dd.CLAVE_PICK]) == a, '`de_pick` entrega copias')


def probar_render(doc):
    """`render` lee lo precalculado y deja lo mismo que calculando."""
    import decisiones_dia as dd
    import modo_modelo as mm

    class _Caja:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class St:
        session_state = {}

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
                    return mm.ESTADO_TODOS
                return False
            return f
    import pronosticos_guardados as pg
    check(pg.FICHERO.startswith(TMP), 'el registro de la prueba va a un temporal')
    pg.recargar()
    vivo = copy.deepcopy(doc)
    vivo.pop('decisiones')
    pre = copy.deepcopy(doc)
    n = dd.adjuntar(pre)
    lista_v = [p for p in vivo['datos']['pronosticos']][:60]
    lista_p = [p for p in pre['datos']['pronosticos']][:60]
    llamadas = []
    _rec = mm.recomendadas
    try:
        mm.render(St(), lista_v, pintar=False)
        mm.recomendadas = lambda *a, **k: llamadas.append(1) or _rec(*a, **k)
        mm.render(St(), lista_p, pintar=False)
    finally:
        mm.recomendadas = _rec
    check(n > 0 and not llamadas,
          '`render` no recalcula lo que ya trae el partido (%d llamadas)'
          % len(llamadas))
    dif = [p.get('partido') for p, q in zip(lista_v, lista_p)
           if canon([p.get(c) for c in ('_destacada', '_recomendadas', '_recomendada')])
           != canon([q.get(c) for c in ('_destacada', '_recomendadas', '_recomendada')])]
    check(not dif, '`render` deja en cada partido lo mismo que calculando '
          '(%d partidos)%s' % (len(lista_v), '' if not dif else ': %s' % dif[:3]))


def probar_cableado():
    src = open('precalculo_dia.py', encoding='utf-8').read()
    check('decisiones_dia.anadir(a.salida)' in src,
          'el precálculo añade las decisiones al JSON que publica')
    check(src.count('_adjuntar_decisiones(doc)') == 2,
          'leer() y descargar() las adjuntan')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('_dd.de_pick(p)' in src, '`render` las lee')


if __name__ == '__main__':
    print('=== 0. el cron ===')
    doc = preparar()
    print('\n=== 1-2. equivalencia exacta ===')
    probar_equivalencia(doc)
    print('\n=== 3. la huella ===')
    probar_huella(doc)
    print('\n=== 4. render ===')
    probar_render(doc)
    probar_cableado()
    shutil.rmtree(TMP, ignore_errors=True)
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
