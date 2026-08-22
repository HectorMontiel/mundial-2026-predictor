#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v158 — CÓRNERS POR EQUIPO: qué media usar y qué distribución.

La pregunta no es predecir el número exacto —eso está medido y descartado (§10.7
de la bitácora)— sino convertir la mejor media disponible en una probabilidad
bien calibrada para la línea EXACTA que cotiza la casa.

Para el TOTAL ya está resuelto: binomial negativa con la dispersión de la
competición baja el error de calibración de 0,0093 a 0,0043. Este script
contesta lo mismo para los córners DE CADA EQUIPO, que es otro mercado y no
tiene por qué comportarse igual:

  · un equipo saca ~4,9 córners de media, la mitad que el total, y en conteos
    pequeños la diferencia entre Poisson y binomial negativa se estrecha;
  · el agrupamiento (un córner genera otro) ocurre DENTRO del ataque de un
    mismo equipo, así que podría ser MÁS marcado por equipo que en el total.

Las dos cosas empujan en direcciones contrarias, así que se mide.

QUÉ SE COMPARA
--------------
Cuatro estimadores de la media de un equipo en un partido, todos calculados con
información PREVIA en un pase cronológico:

    A) media de la competición para ese bando  (la referencia tonta)
    B) media del equipo en lo que va de histórico
    C) media móvil de sus últimos 5
    D) combinado ataque/defensa: (lo que SACA él + lo que RECIBE el rival) / 2

Y para cada uno, dos distribuciones: Poisson y binomial negativa.

La métrica es el ERROR DE CALIBRACIÓN contra la frecuencia real en las líneas
que de verdad cotiza la casa (3,5 / 4,5 / 5,5 / 6,5), no el MAE: lo que se va a
enseñar es una probabilidad, y lo que importa es que sea la que ocurre.
"""
import json
import logging
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import league_engine as le

LIGAS = ['premier', 'laliga', 'serie_a', 'eng_league_one', 'ita_serie_b',
         'fra_ligue2']
LINEAS = (3.5, 4.5, 5.5, 6.5)
MIN_PREV = 5


def _p_mas(media, linea, disp):
    """P(X > linea) con Poisson (disp<=1) o binomial negativa."""
    m = float(media)
    if m <= 0:
        return None
    k = int(np.floor(linea))
    if disp is None or disp <= 1.0001:
        return float(1.0 - stats.poisson.cdf(k, m))
    r = m / (disp - 1.0)
    p = r / (r + m)
    return float(1.0 - stats.nbinom.cdf(k, r, p))


def construir(df):
    """
    Un pase cronológico con los cuatro estimadores por equipo y bando.

    Cada fila lleva los córners REALES de ese equipo en ese partido —que es lo
    que hay que acertar— y las cuatro medias calculadas sólo con lo anterior.
    """
    df = df.sort_values('date').reset_index(drop=True)
    hist, lig = {}, {'casa': [], 'fuera': []}

    def H(eq):
        return hist.setdefault(eq, {'saca_casa': [], 'saca_fuera': [],
                                    'rec_casa': [], 'rec_fuera': []})

    filas = []
    for f in df.itertuples(index=False):
        hh, ha = H(f.home_team), H(f.away_team)
        for bando, propio, rival, saca, rec_rival in (
                ('casa', hh, ha, 'saca_casa', 'rec_fuera'),
                ('fuera', ha, hh, 'saca_fuera', 'rec_casa')):
            s = propio[saca]
            r = rival[rec_rival]
            if len(s) < MIN_PREV or len(r) < MIN_PREV or len(lig[bando]) < 60:
                continue
            real = (float(f.home_corners) if bando == 'casa'
                    else float(f.away_corners))
            m_liga = float(np.mean(lig[bando]))
            filas.append({
                'bando': bando, 'real': real,
                'A_liga': m_liga,
                'B_equipo': float(np.mean(s)),
                'C_movil5': float(np.mean(s[-5:])),
                # (lo que saca él + lo que recibe el rival) / 2 — el estimador
                # estándar de ataque contra defensa, sin normalizar por liga
                # porque las dos partes ya son de este bando.
                'D_ataque_defensa': (float(np.mean(s[-10:]))
                                     + float(np.mean(r[-10:]))) / 2.0,
            })
        ckh, cka = float(f.home_corners), float(f.away_corners)
        hh['saca_casa'].append(ckh); hh['rec_casa'].append(cka)
        ha['saca_fuera'].append(cka); ha['rec_fuera'].append(ckh)
        lig['casa'].append(ckh); lig['fuera'].append(cka)
    return pd.DataFrame(filas)


def dispersion(serie):
    m, v = float(np.mean(serie)), float(np.var(serie))
    return max(v / m, 1.0) if m > 0 else 1.0


def main():
    ligas = sys.argv[1:] or LIGAS
    acumulado = {}
    disp_global = []
    for clave in ligas:
        try:
            df = le.descargar_liga(clave, temporadas=8)
            df = df.dropna(subset=['home_corners', 'away_corners'])
        except Exception as e:
            print('%-16s ERROR %s' % (clave, type(e).__name__))
            continue
        if len(df) < 800:
            continue
        d = construir(df)
        if len(d) < 800:
            continue
        # dispersión de los córners POR EQUIPO en esta competición
        por_equipo = pd.concat([df['home_corners'], df['away_corners']]).astype(float)
        disp = dispersion(por_equipo)
        disp_global.append(disp)
        print('%-16s n=%5d  dispersión por equipo=%.3f  media=%.2f'
              % (clave, len(d), disp, float(por_equipo.mean())), flush=True)

        for est in ('A_liga', 'B_equipo', 'C_movil5', 'D_ataque_defensa'):
            for dist, dv in (('poisson', 1.0), ('binneg', disp)):
                errs = []
                for L in LINEAS:
                    p = d[est].apply(lambda m: _p_mas(m, L, dv))
                    real = (d['real'] > L).astype(float)
                    # error de calibración: |media de la probabilidad dicha −
                    # frecuencia con la que de verdad ocurre|
                    errs.append(abs(float(p.mean()) - float(real.mean())))
                clave_acc = (est, dist)
                acumulado.setdefault(clave_acc, []).append(
                    (len(d), float(np.mean(errs))))

    if not acumulado:
        return
    print()
    print('%-20s %-9s %14s' % ('estimador', 'distrib.', 'error calibr.'))
    print('-' * 46)
    filas = []
    for (est, dist), vals in sorted(acumulado.items()):
        n = sum(v[0] for v in vals)
        err = sum(v[0] * v[1] for v in vals) / n
        filas.append((est, dist, err, n))
    for est, dist, err, n in sorted(filas, key=lambda f: f[2]):
        print('%-20s %-9s %14.5f' % (est, dist, err))

    mejor = min(filas, key=lambda f: f[2])
    print()
    print('MEJOR: %s con %s (error %.5f)' % (mejor[0], mejor[1], mejor[2]))
    print('dispersión media por equipo: %.3f' % float(np.mean(disp_global)))
    json.dump({'filas': [{'estimador': e, 'dist': d, 'error': err, 'n': n}
                         for e, d, err, n in filas],
               'dispersion_por_equipo': round(float(np.mean(disp_global)), 4)},
              open('_v158_corners_equipo.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
