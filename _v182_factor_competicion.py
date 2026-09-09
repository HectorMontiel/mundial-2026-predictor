#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
El factor de competicion, medido con el catalogo equipo -> liga.

La v179 lo midio con los 30 equipos que casaban por nombre exacto. Con
`catalogo_equipos` casan 58, asi que se rehace con casi el doble de muestra y
se deja en un JSON para que el codigo no lo lleve escrito a mano.

    factor = media del equipo en la competicion / media en su liga local

Se calcula por equipo y se agrega con la MEDIANA, que aguanta mejor los equipos
con dos partidos raros. Se exige un minimo de muestra a los dos lados.

Tambien contesta si hace falta un factor por liga de origen o basta uno solo:
la v179 midio que la dispersion entre ligas (sd 0,102) es menor que entre
equipos (sd 0,232), o sea que separar por liga añade ruido. Aqui se rehace con
mas datos.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

import catalogo_equipos as ce

SALIDA = 'factor_competicion.json'
# v183 — TODAS las copas con estadisticas observadas, no solo la Champions.
# Una copa es una competicion donde los equipos vienen de ligas distintas y
# juegan pocos partidos: exactamente el caso que el respaldo resuelve.
def _copas_con_datos():
    import os
    import catalogo_equipos as ce
    import rendimiento_equipos as rq
    import config
    salida = []
    for k in config.LEAGUES:
        if not ce._es_copa(k) or not os.path.exists('historico_%s.csv' % k):
            continue
        try:
            d = rq.stats_disponibles(k)
        except Exception:
            continue
        if d.get('corners') or d.get('tarjetas'):
            salida.append(k)
    return tuple(salida)


COMPETICIONES = _copas_con_datos()
STATS = ('corners', 'yellow', 'shots_on', 'shots_off')
MIN_COMP = 5
MIN_LIGA = 20


def perfil(df, stat):
    filas = []
    for lado in ('home', 'away'):
        col = '%s_%s' % (lado, stat)
        if col not in df.columns:
            continue
        sub = df[['%s_team' % lado, col]].dropna()
        filas.append(sub.rename(columns={'%s_team' % lado: 'equipo',
                                         col: 'v'}))
    if not filas:
        return {}
    todo = pd.concat(filas, ignore_index=True)
    g = todo.groupby('equipo')['v']
    return {e: (float(m), int(n)) for e, m, n
            in zip(g.mean().index, g.mean().values, g.size().values)}


def main():
    doc = {}
    for comp in COMPETICIONES:
        ch = pd.read_csv('historico_%s.csv' % comp)
        if 'stats_origen' in ch.columns:
            ch = ch[ch['stats_origen'].notna()]
        print('%s: %d partidos observados' % (comp, len(ch)))
        # las ligas locales que hacen falta
        equipos = sorted(set(ch['home_team']) | set(ch['away_team']))
        destino = {}
        for e in equipos:
            r = ce.nombre_en_su_liga(e)
            if r:
                destino[e] = r
        print('  equipos con liga local: %d de %d' % (len(destino), len(equipos)))
        cache = {}
        doc[comp] = {}
        for stat in STATS:
            pc = perfil(ch, stat)
            factores, por_liga = [], {}
            for e, (m_ch, n_ch) in pc.items():
                if n_ch < MIN_COMP or e not in destino:
                    continue
                clave_l, nombre_l = destino[e]
                if clave_l not in cache:
                    try:
                        d = pd.read_csv('historico_%s.csv' % clave_l)
                        if 'stats_origen' in d.columns:
                            d = d[d['stats_origen'].notna()]
                        cache[clave_l] = d
                    except Exception:
                        cache[clave_l] = None
                d = cache[clave_l]
                if d is None or d.empty:
                    continue
                pl = perfil(d, stat)
                if nombre_l not in pl:
                    continue
                m_l, n_l = pl[nombre_l]
                if n_l < MIN_LIGA or m_l <= 0:
                    continue
                f = m_ch / m_l
                factores.append(f)
                por_liga.setdefault(clave_l, []).append(f)
            if not factores:
                continue
            med = float(np.median(factores))
            sd_eq = float(np.std(factores))
            medianas_liga = [float(np.median(v)) for v in por_liga.values()
                             if len(v) >= 3]
            sd_liga = float(np.std(medianas_liga)) if len(medianas_liga) >= 3 else None
            doc[comp][stat] = {'factor': round(med, 4), 'n_equipos': len(factores),
                               'sd_entre_equipos': round(sd_eq, 4),
                               'sd_entre_ligas': (round(sd_liga, 4)
                                                  if sd_liga is not None else None)}
            print('  %-10s factor %.4f  (n=%d equipos · sd equipos %.3f · '
                  'sd ligas %s)'
                  % (stat, med, len(factores), sd_eq,
                     ('%.3f' % sd_liga) if sd_liga is not None else '-'))
    with io.open(SALIDA, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    print()
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
