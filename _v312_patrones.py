# -*- coding: utf-8 -*-
"""
v312 — ¿QUÉ TIENEN EN COMÚN LAS APUESTAS «METER» QUE SALEN ROJAS?

El usuario: «analiza todos los partidos finalizados de hoy y los acumulados;
en las apuestas que me diste y no se cumplieron encuentra los patrones, para
que la siguiente versión me dé apuestas más certeras y sólo me muestre las
que sí debo meter… en todas las estadísticas, incluyendo córners y goles por
equipo. Lo que quiero evitar es tener muchos rojos. Las validaciones las
harás con simulaciones de los partidos de hoy: cuando consigas más verdes
que los de hoy, el modelo mejoró. Quiero ver esos resultados con el
porcentaje de acierto».

LOS DATOS: todos los partidos de fútbol que la aplicación pronosticó desde
el 2026-09-19 (cada foto del pronóstico está en git), cada uno con la ÚLTIMA
foto anterior a su inicio y los precios de Playdoit de ese momento. Se pasan
por la tarjeta de hoy (`modo_modelo.recomendadas`, con los históricos
RECORTADOS a lo anterior a la fecha de cada partido: ver
`_v310_replay_semana.Recorte`) y se guardan TODAS las candidatas —no sólo las
que se enseñan— con su veredicto, para poder probar reglas distintas sobre
exactamente las mismas apuestas. Se liquidan con el marcador y la ficha de
FotMob.

LA PRUEBA: las reglas se eligen con los días ANTERIORES y se juzgan en los
días más recientes (y, aparte, en el día de hoy), que no se usaron para
elegir. «Más verdes» = mayor porcentaje de acierto de lo que se dice
«meter», sin que el número de apuestas se desplome.

Uso: python _v312_patrones.py [--rehacer]   (caché: _v312_candidatas.csv)
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

CACHE = os.environ.get('V312_CACHE', '_v312_candidatas.csv')
SALIDA = '_v312_patrones.json'


def construir() -> pd.DataFrame:
    import dia_picks as dp
    import horario as hz
    import modo_modelo as mm
    import partidos_jugados as pj
    import pronosticos_guardados as pg
    import _v310_replay_semana as rp
    t0 = time.time()
    picks = rp.fotos()
    print('partidos con foto previa y precio:', len(picks), flush=True)
    rec = rp.Recorte()
    por_fecha = {}
    for p in picks:
        por_fecha.setdefault(pd.Timestamp(hz._a_utc(p['inicio']).date()),
                             []).append(p)
    partidos = []
    for fecha in sorted(por_fecha):
        grupo = por_fecha[fecha]
        rec.fijar(fecha, {p.get('clave_liga') for p in grupo})
        for p in grupo:
            q = dict(p)
            try:
                _rm = mm.remates_tarjeta(q) or {}
                bloques = {'Córners': mm.corners_tarjeta(q),
                           'Tarjetas': mm.tarjetas_tarjeta(q),
                           'Remates': _rm.get('totales'),
                           'Remates a puerta': _rm.get('a_puerta')}
                cands = mm.recomendadas(q, bloques, n=mm.ANCHO_CANDIDATAS) or []
            except Exception as e:
                print('  fallo', p.get('partido'), e)
                cands = []
            q['_cands'] = cands
            q['jugado'] = True
            q['recomendadas_previas'] = [pg._fila(c) for c in cands]
            partidos.append(q)
        print(fecha.date(), len(grupo), '· %.0f s' % (time.time() - t0),
              flush=True)
    rec.corte = None
    por_dia = {}
    for q in partidos:
        por_dia.setdefault(dp.dia_de(q), []).append(q)
    for dia, lista in sorted(por_dia.items()):
        pj.poner_marcadores(lista, dia, fotmob=pj.marcadores_fotmob(dia))
    filas = []
    for q in partidos:
        gh, ga = q.get('goles_home'), q.get('goles_away')
        if gh is None or q.get('aplazado'):
            continue
        h, a = mm._equipos(q)
        stats = q.get('stats_partido')
        if stats is None:
            stats = pg._stats_del_partido(q.get('clave_liga'), h, a, q.get('fecha'))
        mostradas = [c.get('apuesta') for c in mm.metidas(
            q['_cands'][:mm.MAX_RECOMENDADAS])]
        for i, c in enumerate(q['_cands']):
            f = pg._fila(c)
            real = pg._valor_real(f, gh, ga, stats)
            ok, dist = pg._acierto(f, real, h, a)
            filas.append({
                'dia': dp.dia_de(q), 'liga': q.get('clave_liga'),
                'torneo': q.get('liga'), 'partido': q.get('partido'),
                'puesto': i + 1, 'mostrada': c.get('apuesta') in mostradas,
                'mercado': c.get('mercado'), 'bloque': c.get('bloque'),
                'etiqueta': c.get('etiqueta'), 'apuesta': c.get('apuesta'),
                'linea': c.get('linea'), 'prob': c.get('prob'),
                'prob_meter': c.get('prob_meter'),
                'veredicto': c.get('veredicto_vp'), 'cuota': c.get('cuota'),
                'p_mercado': c.get('p_mercado'),
                'goles': (gh or 0) + (ga or 0),
                'acierto': None if ok is None else int(bool(ok)),
                'distancia': dist})
    d = pd.DataFrame(filas)
    d.to_csv(CACHE, index=False)
    return d


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if '--rehacer' in sys.argv or not os.path.exists(CACHE):
        d = construir()
    else:
        d = pd.read_csv(CACHE)
    print('candidatas liquidadas:', int(d['acierto'].notna().sum()),
          'de', len(d), '· partidos', d['partido'].nunique(),
          '· días', sorted(d['dia'].unique()))


if __name__ == '__main__':
    main()
