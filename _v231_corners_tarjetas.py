#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v231 — ¿los córners y las tarjetas tienen el mismo sesgo que tenía el BTTS?

LA PREGUNTA
-----------
La v230 encontró que el «ambos marcan» estaba infravalorado en 44 de 55 ligas,
y la causa era asumir independencia entre los goles de los dos equipos. Los
córners y las tarjetas son conteos que se suman igual, así que la pregunta se
traslada sola: ¿les pasa lo mismo?

Hay un motivo para sospechar que NO. El estimador de córners ya usa binomial
negativa con la sobredispersión medida (1,58 por equipo) en vez de Poisson, y
su propia bitácora dice que eso es seis veces mejor que la referencia. O sea
que el racimo —lo que a los goles les faltaba— ahí ya está contemplado. Pero
«ya está contemplado» es una afirmación, y esto la comprueba.

CÓMO SE MIDE SIN FUGA
---------------------
`rendimiento_equipos.corners_equipo` mira TODO el histórico, así que llamarlo
sobre un partido pasado sería preguntarle por un partido que ya vio. Aquí se
replica el mismo estimador con una ventana EXPANSIVA: para cada partido, la
media de los `N` anteriores de cada equipo, y nada más. Los primeros partidos
de cada equipo se descartan porque no tienen con qué.

La dispersión se estima también sólo con lo anterior, por la misma razón.

LAS LÍNEAS
----------
Las que de verdad se cotizan: 8.5, 9.5 y 10.5 córners; 3.5 y 4.5 tarjetas. No
se evalúan líneas que nadie publica, que es la disciplina que el propio
`plantilla_nfl` sigue para los totales.

Esto no cambia nada: mide y escribe `_v231_corners_tarjetas.json`.
"""
import glob
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

SALIDA = '_v231_corners_tarjetas.json'
VENTANA = 10                 # los mismos 10 partidos que usa el estimador vivo
MIN_PREVIOS = 5              # por debajo, la media de un equipo no dice nada
MIN_PARTIDOS = 200           # por liga, para que el resultado signifique algo

MERCADOS = (
    ('corners', 'home_corners', 'away_corners', (8.5, 9.5, 10.5)),
    ('tarjetas', 'home_yellow', 'away_yellow', (3.5, 4.5)),
)


def prob_mas_de(media, linea, dispersion):
    """P(total > línea) con binomial negativa. Vectorizada sobre `media`."""
    from scipy import stats as _st
    media = np.asarray(media, dtype=float)
    k = int(np.floor(float(linea)))
    d = float(dispersion or 1.0)
    if d <= 1.0:
        return 1.0 - _st.poisson.cdf(k, np.maximum(media, 1e-9))
    # var = d * media  ->  p = 1/d,  n = media/(d-1)
    p = 1.0 / d
    n = np.maximum(media, 1e-9) / (d - 1.0)
    return 1.0 - _st.nbinom.cdf(k, n, p)


def _medias_expansivas(df, col_h, col_a, ventana=VENTANA):
    """Para cada fila, la media de los `ventana` partidos ANTERIORES de cada
    equipo en ese aspecto. NaN mientras no haya `MIN_PREVIOS`."""
    hist = {}
    fuera_h = np.full(len(df), np.nan)
    fuera_a = np.full(len(df), np.nan)
    for i, r in enumerate(df.itertuples(index=False)):
        h, a = getattr(r, 'home_team'), getattr(r, 'away_team')
        for eq, destino in ((h, fuera_h), (a, fuera_a)):
            prev = hist.get(eq)
            if prev and len(prev) >= MIN_PREVIOS:
                destino[i] = float(np.mean(prev[-ventana:]))
        # y AHORA se apunta lo de este partido, nunca antes
        vh, va = getattr(r, col_h), getattr(r, col_a)
        if pd.notna(vh):
            hist.setdefault(h, []).append(float(vh))
        if pd.notna(va):
            hist.setdefault(a, []).append(float(va))
    return fuera_h, fuera_a


def auditar_liga(ruta):
    liga = os.path.basename(ruta)[len('historico_'):-len('.csv')]
    try:
        df = pd.read_csv(ruta)
    except Exception:
        return None
    if 'date' not in df.columns or len(df) < MIN_PARTIDOS:
        return None
    df = df.sort_values('date').reset_index(drop=True)
    ficha = {'liga': liga, 'n': int(len(df)), 'mercados': {}}

    for clave, ch, ca, lineas in MERCADOS:
        if ch not in df.columns or ca not in df.columns:
            continue
        sub = df[df[ch].notna() & df[ca].notna()].reset_index(drop=True)
        if len(sub) < MIN_PARTIDOS:
            continue
        mh, ma = _medias_expansivas(sub, ch, ca)
        real = (pd.to_numeric(sub[ch], errors='coerce')
                + pd.to_numeric(sub[ca], errors='coerce')).to_numpy(float)
        ok = ~np.isnan(mh) & ~np.isnan(ma) & ~np.isnan(real)
        if int(ok.sum()) < MIN_PARTIDOS:
            continue
        media_total = (mh + ma)[ok]
        y_total = real[ok]
        # dispersión estimada con lo mismo que se predice, no con el futuro:
        # var/media del TOTAL observado en la ventana de entrenamiento
        corte = max(MIN_PARTIDOS // 2, int(0.5 * len(y_total)))
        ent = y_total[:corte]
        disp = float(np.var(ent) / np.mean(ent)) if np.mean(ent) > 0 else 1.0
        disp = max(1.0, min(disp, 3.0))

        filas = {}
        for L in lineas:
            p = prob_mas_de(media_total[corte:], L, disp)
            y = (y_total[corte:] > L).astype(float)
            if len(y) < 100:
                continue
            filas['%.1f' % L] = {
                'n': int(len(y)),
                'prometido': round(float(np.mean(p)), 4),
                'real': round(float(np.mean(y)), 4),
                'sesgo': round(float(np.mean(p) - np.mean(y)), 4),
            }
        if filas:
            ficha['mercados'][clave] = {'dispersion': round(disp, 3),
                                        'lineas': filas}
    return ficha if ficha['mercados'] else None


def main():
    fichas = {}
    for ruta in sorted(glob.glob('historico_*.csv')):
        liga = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        if liga in ('partidos', 'jugadores', 'agrupado'):
            continue
        f = auditar_liga(ruta)
        if f:
            fichas[liga] = f
    print('ligas auditadas: %d' % len(fichas))

    resumen = {}
    for clave, _, _, lineas in MERCADOS:
        for L in lineas:
            k = '%.1f' % L
            ses = [f['mercados'][clave]['lineas'][k]['sesgo']
                   for f in fichas.values()
                   if clave in f['mercados']
                   and k in f['mercados'][clave]['lineas']]
            if len(ses) < 5:
                continue
            neg = sum(1 for s in ses if s < 0)
            resumen['%s_%s' % (clave, k)] = {
                'ligas': len(ses), 'media': round(float(np.mean(ses)), 4),
                'mediana': round(float(np.median(ses)), 4),
                'infravalorado_en': neg}
            print('%-16s %2d ligas · sesgo medio %+.4f · mediana %+.4f · '
                  'infravalorado en %d de %d'
                  % ('%s %s' % (clave, k), len(ses), float(np.mean(ses)),
                     float(np.median(ses)), neg, len(ses)))

    doc = {'ligas': fichas, 'resumen': resumen, 'ventana': VENTANA}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
