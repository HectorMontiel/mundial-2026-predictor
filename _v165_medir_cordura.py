#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v165 — ¿CUÁNTO SE SEPARA EL TITULAR DE LA TARJETA DEL PRECIO DE LA CASA?

Antes de poner un techo hay que saber sobre qué se pone. Este script recorre el
barrido CACHEADO del día (`.cache_barrido.pkl`, sin red) y, para cada
pronóstico de fútbol, compara la probabilidad del titular
(`modo_modelo.apuesta_destacada`) con la implícita SIN MARGEN de la casa
(`mercado_implicito`), sacada del tablero por evento que ya está en
`cuotas_cache/`.

    python _v165_medir_cordura.py

Contesta tres preguntas:

  1. ¿de cuántos titulares se puede saber el precio de la casa?
  2. ¿cuántos se separan más de 15 puntos, que es el umbral que se pidió?
  3. ¿a cuántos les cambiaría el semáforo el techo por media de goles de liga?
"""
import json
import logging
import os
import pickle
import sys
import warnings
from collections import Counter

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v165_medir_cordura.json'
CACHE = '.cache_barrido.pkl'


def _precio_de_disco(home, away):
    """El tablero cacheado de este partido, SIN pedir red."""
    import cuotas_multi as cm
    import mercado_implicito as mi
    try:
        ent = cm._buscar(cm._indice_pdt('futbol'), home, away, 'futbol',
                         None, None)
    except Exception:
        return {}
    if not ent or not ent.get('event_id'):
        return {}
    ruta = os.path.join('cuotas_cache', 'playdoit_ev_%s.json' % ent['event_id'])
    if not os.path.exists(ruta):
        return {}
    try:
        with open(ruta, encoding='utf-8') as f:
            crudos = json.load(f) or []
    except Exception:
        return {}
    invertido = bool(ent.get('invertido'))
    tablero = {'casa': 'Playdoit', 'mercados': crudos,
               'home': ent.get('away') if invertido else ent.get('home'),
               'away': ent.get('home') if invertido else ent.get('away')}
    return mi.del_tablero(tablero)


def main():
    import modo_modelo as mm
    import mercado_implicito as mi
    import render_todos_partidos as rt

    if not os.path.exists(CACHE):
        print('no hay %s: hace falta un barrido cacheado' % CACHE)
        return 1
    datos = pickle.load(open(CACHE, 'rb'))['datos']
    pron = [p for p in (datos.get('pronosticos') or [])
            if p.get('deporte') == 'Fútbol' and not p.get('sin_modelo')]
    print('%d pronósticos de fútbol con modelo\n' % len(pron))

    cuenta = Counter()
    desvios = []
    detalle = []
    for p in pron:
        d = mm.apuesta_destacada(p)
        if not d:
            cuenta['sin titular'] += 1
            continue
        cuenta['con titular'] += 1
        if d['alta']:
            cuenta['titular VERDE (>=60 %)'] += 1
        home, away = rt.lados(p.get('partido'))
        precio = _precio_de_disco(home, away)
        if not precio:
            cuenta['sin precio de la casa'] += 1
            continue
        imp = mi.implicita(precio, d['apuesta'], home, away)
        if imp is None:
            cuenta['la casa no cotiza ESE mercado'] += 1
            continue
        cuenta['contrastables'] += 1
        dif = d['prob'] - imp
        desvios.append(dif)
        if abs(dif) > 0.15:
            cuenta['desvío > 15 pp'] += 1
            if d['alta']:
                cuenta['VERDE con desvío > 15 pp'] += 1
        detalle.append({'partido': p.get('partido'),
                        'liga': p.get('clave_liga'),
                        'apuesta': d['apuesta'],
                        'modelo': round(d['prob'], 3),
                        'casa': round(imp, 3),
                        'dif': round(dif, 3), 'verde': d['alta']})

    print('=' * 78)
    print('1) CONTRASTE CONTRA LA CASA')
    print('=' * 78)
    for k, v in cuenta.most_common():
        print('  %-32s %4d' % (k, v))
    if desvios:
        ab = sorted(abs(x) for x in desvios)
        print('\n  desvío |modelo − casa|: mediana %.3f · p90 %.3f · máx %.3f'
              % (ab[len(ab) // 2], ab[int(len(ab) * 0.9)], ab[-1]))

    print('\n' + '=' * 78)
    print('2) LOS DIEZ MAYORES DESVÍOS')
    print('=' * 78)
    for d in sorted(detalle, key=lambda x: -abs(x['dif']))[:10]:
        print('  %-42s %-18s modelo %.0f %% · casa %.0f %%  (%+.0f pp)%s'
              % (d['partido'][:42], d['apuesta'][:18], d['modelo'] * 100,
                 d['casa'] * 100, d['dif'] * 100,
                 '  ← VERDE' if d['verde'] else ''))

    # ---- 3) el techo por media de goles de la liga -----------------------
    print('\n' + '=' * 78)
    print('3) EL TECHO POR MEDIA DE GOLES DE LA COMPETICIÓN')
    print('=' * 78)
    import rendimiento_equipos as rq
    import cordura_probabilidad as cp
    tocados = Counter()
    for p in pron:
        d = mm.apuesta_destacada(p)
        if not d:
            continue
        techo = cp.techo_por_liga(p.get('clave_liga'), d['apuesta'])
        if techo is None:
            tocados['sin techo aplicable'] += 1
            continue
        tocados['con techo aplicable'] += 1
        if d['prob'] > techo:
            tocados['recortados por el techo'] += 1
            if d['alta'] and techo < mm.UMBRAL_ALTA:
                tocados['pierden el VERDE'] += 1
    for k, v in tocados.most_common():
        print('  %-32s %4d' % (k, v))

    medias = {}
    for c in sorted(set(p.get('clave_liga') for p in pron if p.get('clave_liga'))):
        m = rq.media_goles_liga(c)
        if m is not None:
            medias[c] = m
    altas = {k: v for k, v in medias.items() if v > 2.5}
    print('\n  %d competiciones con media medida · %d por encima de 2,5 · '
          '%d por encima de 3,0'
          % (len(medias), len(altas),
             sum(1 for v in medias.values() if v > 3.0)))

    json.dump({'cuenta': dict(cuenta), 'techo': dict(tocados),
               'detalle': detalle, 'medias_goles': medias},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
