#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
¿Mejora mezclar el perfil de Champions con el de la liga local? Medido.

EL PROBLEMA. En Champions la muestra por equipo es corta —mediana 16 partidos,
37 % por debajo de 10, y algunos con cero—, asi que estimar sus corners solo con
lo que ha hecho en la competicion es estimar sobre ruido. Su liga local tiene
cientos de partidos.

LO QUE SE COMPARA, walk-forward y sin mirar el futuro. Para cada partido de
Champions con corners observados, en orden de fecha, y para cada uno de los dos
equipos:

    y         corners reales de ese equipo en ese partido
    A         media de sus ULTIMOS k partidos de Champions (lo que se hace hoy)
    B         media de sus ultimos k de su LIGA LOCAL x factor de competicion
    MEZCLA    A y B ponderados por cuanta muestra hay de cada uno
    LIGA      la media de la competicion (linea base tonta)

El factor de competicion se estima SOLO con los partidos anteriores a cada
fecha, para no meter informacion del futuro.

La pregunta que contesta: ¿baja el error absoluto medio? Y sobre todo, ¿baja en
los equipos con POCA muestra, que son los que motivan todo esto?
"""
import io
import sys
from collections import defaultdict, deque

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

import catalogo_equipos as ce

CHAMPIONS = 'historico_champions.csv'
VENTANA = 10          # la misma que usa `lambda_corners_equipo`
STATS = ('corners', 'yellow', 'shots_on')
# Peso de la liga local: cuanto menos se ha visto al equipo en la competicion,
# mas manda su liga. `k` es el punto en que las dos pesan lo mismo.
K_MEZCLA = 6


def cargar_ligas(claves):
    """{clave: DataFrame con filas observadas} de las ligas que hagan falta."""
    import rendimiento_equipos as rq
    salida = {}
    for clave in sorted(set(claves)):
        try:
            d = rq.stats_disponibles(clave)
            if not d.get('corners'):
                continue
            df = pd.read_csv('historico_%s.csv' % clave)
        except Exception:
            continue
        if 'stats_origen' in df.columns:
            df = df[df['stats_origen'].notna()]
        if df.empty:
            continue
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        salida[clave] = df.dropna(subset=['date']).sort_values('date')
    return salida


def series_por_equipo(df, stat):
    """[(fecha, equipo, valor)] juntando los dos bandos."""
    filas = []
    for lado in ('home', 'away'):
        col = '%s_%s' % (lado, stat)
        if col not in df.columns:
            continue
        sub = df[['date', '%s_team' % lado, col]].dropna()
        for f, e, v in sub.itertuples(index=False):
            filas.append((f, str(e), float(v)))
    filas.sort(key=lambda x: x[0])
    return filas


def main():
    ch = pd.read_csv(CHAMPIONS)
    if 'stats_origen' in ch.columns:
        ch = ch[ch['stats_origen'] == 'espn']
    ch['date'] = pd.to_datetime(ch['date'], errors='coerce')
    ch = ch.dropna(subset=['date']).sort_values('date')
    print('Champions con estadisticas observadas: %d partidos' % len(ch))

    equipos = sorted(set(ch['home_team']) | set(ch['away_team']))
    mapa = {}
    for e in equipos:
        r = ce.nombre_en_su_liga(e)
        if r:
            mapa[e] = r
    print('equipos con liga local resuelta: %d de %d' % (len(mapa), len(equipos)))

    ligas = cargar_ligas([l for l, _ in mapa.values()])
    print('ligas locales cargadas: %d' % len(ligas))

    for stat in STATS:
        print()
        print('=' * 68)
        print('  %s' % stat.upper())
        print('=' * 68)
        # historial por equipo en su liga local, indexado por fecha
        hist_liga = {}
        for clave, df in ligas.items():
            hist_liga[clave] = defaultdict(list)
            for f, e, v in series_por_equipo(df, stat):
                hist_liga[clave][e].append((f, v))

        ult_ch = defaultdict(lambda: deque(maxlen=VENTANA))
        errores = defaultdict(list)
        # para el factor: se acumulan pares (media_ch, media_liga) del pasado
        pares = []
        media_ch_global = []

        for fila in ch.itertuples(index=False):
            f = fila.date
            for lado, otro in (('home', 'away'), ('away', 'home')):
                eq = getattr(fila, '%s_team' % lado)
                col = '%s_%s' % (lado, stat)
                y = getattr(fila, col, None)
                if y is None or (isinstance(y, float) and np.isnan(y)):
                    continue
                y = float(y)
                prev = list(ult_ch[eq])
                n_ch = len(prev)
                base_liga = float(np.mean(media_ch_global)) if media_ch_global else y

                # A: solo Champions
                a = float(np.mean(prev)) if prev else base_liga
                # B: liga local ajustada por el factor estimado hasta ahora
                b = None
                r = mapa.get(eq)
                if r:
                    clave_l, nombre_l = r
                    serie = (hist_liga.get(clave_l) or {}).get(nombre_l) or []
                    antes = [v for ff, v in serie if ff < f][-VENTANA:]
                    if antes:
                        factor = (float(np.median([x / z for x, z in pares
                                                   if z > 0]))
                                  if len(pares) >= 20 else 1.0)
                        b = float(np.mean(antes)) * factor
                        if prev:
                            pares.append((float(np.mean(prev)),
                                          float(np.mean(antes))))
                # MEZCLA: peso por muestra
                if b is None:
                    mezcla = a
                else:
                    w = n_ch / (n_ch + K_MEZCLA)
                    mezcla = w * a + (1 - w) * b
                errores['A_solo_champions'].append(abs(y - a))
                errores['B_solo_liga'].append(abs(y - (b if b is not None else a)))
                errores['MEZCLA'].append(abs(y - mezcla))
                errores['LINEA_BASE_media'].append(abs(y - base_liga))
                # y el corte que importa: equipos con poca muestra
                if n_ch < 5:
                    errores['A_pocos'].append(abs(y - a))
                    errores['MEZCLA_pocos'].append(abs(y - mezcla))
                ult_ch[eq].append(y)
                media_ch_global.append(y)

        n = len(errores['A_solo_champions'])
        print('  equipos-partido evaluados: %d' % n)
        print('  %-26s %8s' % ('estimador', 'MAE'))
        for k in ('LINEA_BASE_media', 'A_solo_champions', 'B_solo_liga',
                  'MEZCLA'):
            if errores[k]:
                print('  %-26s %8.4f' % (k, float(np.mean(errores[k]))))
        if errores['A_pocos']:
            ma = float(np.mean(errores['A_pocos']))
            mm = float(np.mean(errores['MEZCLA_pocos']))
            print()
            print('  SOLO equipos con menos de 5 partidos previos (%d casos):'
                  % len(errores['A_pocos']))
            print('    solo Champions %.4f  ·  MEZCLA %.4f  ·  %+.2f %%'
                  % (ma, mm, 100.0 * (mm - ma) / ma))
    return 0


if __name__ == '__main__':
    sys.exit(main())
