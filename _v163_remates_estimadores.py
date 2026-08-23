#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — REMATES POR EQUIPO: qué media usar y qué distribución.

La misma pregunta que cerró la v158 en córners y la v160 en tarjetas, hecha
ahora sobre los remates: totales y a puerta. No se trata de acertar el número
—el techo de correlación de este mercado está medido en 0,357 (§10.7)— sino de
convertir la mejor media disponible en una probabilidad bien calibrada para la
línea EXACTA que cotiza la casa.

Hay una razón concreta para no dar por hecho el resultado de córners: la razón
varianza/media de los remates POR EQUIPO sale alrededor de 2,0-2,5, contra el
1,58 de los córners. Con esa sobredispersión, Poisson debería quedar mucho peor
—y la binomial negativa mucho mejor— de lo que quedaba allí. Se comprueba.

QUÉ SE COMPARA
--------------
Cuatro estimadores de la media de un equipo en un partido, todos calculados con
información PREVIA en un pase cronológico:

    A) media de la competición para ese bando  (la referencia tonta)
    B) media del equipo en lo que va de histórico
    C) media móvil de sus últimos 5
    D) combinado ataque/defensa: (lo que TIRA él + lo que CONCEDE el rival) / 2
       con ventana 10, que es el que ganó en córners y en tarjetas

Y para cada uno, dos distribuciones: Poisson y binomial negativa con la
dispersión medida de la competición.

Dos objetivos: remates TOTALES (a puerta + fuera) y remates A PUERTA.

    python _v163_remates_estimadores.py [liga ...]
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
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_remates_estimadores.json'

# Mezcla deliberada: seis de football-data (donde los remates vienen de la
# fuente histórica) y seis cubiertas por el boxscore de ESPN, para que el
# resultado no dependa de una sola procedencia.
LIGAS = ['premier', 'laliga', 'serie_a', 'ita_serie_b', 'fra_ligue2',
         'eng_league_one', 'liga_mx', 'mls', 'argentina', 'brasil',
         'jpn_j1', 'eredivisie']

# Las líneas que de verdad cotiza la casa para el equipo.
LINEAS = {'tot': (9.5, 11.5, 13.5, 15.5), 'on': (2.5, 3.5, 4.5, 5.5)}
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


def marco(clave):
    """
    El histórico con las estadísticas de ESPN ya inyectadas y recortado a las
    filas OBSERVADAS, que es exactamente lo que verá producción tras el
    siguiente `--build`. Sin la inyección, las competiciones que no son de
    football-data saldrían con los remates del generador sintético, y medir
    sobre una fórmula no mide nada.
    """
    import rendimiento_equipos as re_
    import stats_espn
    d = re_._historico(clave)
    if d is None or getattr(d, 'empty', True):
        return None
    # LA PUERTA QUE HAY QUE PASAR, Y NO ES OPCIONAL.
    #
    # `stats_espn.inyectar` SÓLO RELLENA HUECOS, así que en un histórico ya
    # guardado con los remates del generador sintético no pisa nada: marca la
    # fila con `stats_origen='espn'` porque aporta faltas y posesión, y los
    # remates siguen siendo la fórmula. `_solo_reales` deja pasar esas filas
    # y la medición sale sobre datos inventados.
    #
    # Se vio en la primera pasada: MLS, Argentina y Brasil daban dispersión
    # 3,25-3,47 y correlación 0,05 con el resultado real, contra el 2,0-2,4 y
    # 0,35-0,56 de las competiciones con remates de verdad. Ése es el retrato
    # del generador, no el de un mercado difícil.
    #
    # `stats_disponibles` no se fía de que la columna exista: le pide la
    # columna al generador y compara valor a valor (`_columnas_sinteticas`).
    # Es la misma puerta que usará producción, así que medir detrás de ella es
    # medir lo que se va a servir.
    if not re_.stats_disponibles(clave).get('remates'):
        return None
    try:
        d = stats_espn.inyectar(d.copy(), clave)
    except Exception:
        pass
    d = re_._solo_reales(d, 'shots_on')
    if d is None or getattr(d, 'empty', True):
        return None
    for b in ('home', 'away'):
        on = pd.to_numeric(d[b + '_shots_on'], errors='coerce')
        off = pd.to_numeric(d[b + '_shots_off'], errors='coerce')
        d[b + '_rem_on'] = on
        d[b + '_rem_tot'] = on + off
    return d.dropna(subset=['home_rem_tot', 'away_rem_tot',
                            'home_rem_on', 'away_rem_on'])


def construir(df, obj):
    """Pase cronológico con los cuatro estimadores por equipo y bando."""
    col_h, col_a = 'home_rem_' + obj, 'away_rem_' + obj
    df = df.sort_values('date').reset_index(drop=True)
    hist, lig = {}, {'casa': [], 'fuera': []}

    def H(eq):
        return hist.setdefault(eq, {'tira_casa': [], 'tira_fuera': [],
                                    'conc_casa': [], 'conc_fuera': []})

    filas = []
    for f in df.itertuples(index=False):
        vh = float(getattr(f, col_h))
        va = float(getattr(f, col_a))
        hh, ha = H(f.home_team), H(f.away_team)
        for bando, propio, rival, tira, conc_rival, real in (
                ('casa', hh, ha, 'tira_casa', 'conc_fuera', vh),
                ('fuera', ha, hh, 'tira_fuera', 'conc_casa', va)):
            s = propio[tira]
            r = rival[conc_rival]
            if len(s) < MIN_PREV or len(r) < MIN_PREV or len(lig[bando]) < 60:
                continue
            filas.append({
                'bando': bando, 'real': real,
                'A_liga': float(np.mean(lig[bando])),
                'B_equipo': float(np.mean(s)),
                'C_movil5': float(np.mean(s[-5:])),
                'D_ataque_defensa': (float(np.mean(s[-10:]))
                                     + float(np.mean(r[-10:]))) / 2.0,
            })
        hh['tira_casa'].append(vh)
        hh['conc_casa'].append(va)
        ha['tira_fuera'].append(va)
        ha['conc_fuera'].append(vh)
        lig['casa'].append(vh)
        lig['fuera'].append(va)
    return pd.DataFrame(filas)


def dispersion(serie):
    m, v = float(np.mean(serie)), float(np.var(serie))
    return max(v / m, 1.0) if m > 0 else 1.0


def metricas(p, real):
    """
    Las tres cosas que hay que mirar a la vez, y por qué no basta la primera.

    · `marginal`  = |media de la probabilidad dicha − frecuencia real|. Es la
      métrica con la que se cerraron córners y tarjetas, y mide una cosa muy
      concreta: que el nivel no esté sesgado. Su punto ciego es que **no mide
      resolución**. La media de la competición dice la misma probabilidad en
      todos los partidos y aun así puntúa 0,021 aquí, porque de media acierta.
      Un estimador que no distingue un partido de otro es inútil para apostar
      por bueno que salga este número.

    · `brier`     = error cuadrático medio de la probabilidad. Baja sólo si la
      probabilidad se mueve en la dirección correcta partido a partido, así
      que es la que separa señal de nivel.

    · `ece`       = calibración por deciles de probabilidad dicha. Es la que
      caza el caso peligroso: dos sesgos que se cancelan en la media y dejan
      el `marginal` bajo mientras el modelo está mal en las dos colas.
    """
    p = np.asarray(p, dtype=float)
    y = np.asarray(real, dtype=float)
    m = ~np.isnan(p)
    p, y = p[m], y[m]
    if len(p) < 50:
        return None
    marginal = abs(float(p.mean()) - float(y.mean()))
    brier = float(np.mean((p - y) ** 2))
    # deciles por probabilidad dicha; los bordes salen de los propios datos
    # para que no haya cajones vacíos cuando el estimador es casi constante.
    bordes = np.unique(np.quantile(p, np.linspace(0, 1, 11)))
    ece, total = 0.0, 0
    if len(bordes) >= 3:
        idx = np.clip(np.digitize(p, bordes[1:-1]), 0, len(bordes) - 2)
        for b in range(len(bordes) - 1):
            sel = idx == b
            n = int(sel.sum())
            if n < 30:
                continue
            ece += n * abs(float(p[sel].mean()) - float(y[sel].mean()))
            total += n
    ece = ece / total if total else float('nan')
    return {'marginal': marginal, 'brier': brier, 'ece': ece}


def main():
    ligas = sys.argv[1:] or LIGAS
    resultado = {}
    for obj in ('tot', 'on'):
        print('=' * 78)
        print('OBJETIVO: remates %s'
              % ('TOTALES' if obj == 'tot' else 'A PUERTA'))
        print('=' * 78)
        acumulado, disp_global, por_liga = {}, [], {}
        for clave in ligas:
            df = marco(clave)
            if df is None or len(df) < 600:
                print('%-16s sin datos observados suficientes' % clave)
                continue
            d = construir(df, obj)
            if len(d) < 600:
                print('%-16s n=%d, insuficiente' % (clave, len(d)))
                continue
            por_eq = pd.concat([df['home_rem_' + obj],
                                df['away_rem_' + obj]]).astype(float)
            disp = dispersion(por_eq)
            disp_global.append(disp)
            corr = float(np.corrcoef(d['D_ataque_defensa'], d['real'])[0, 1])
            print('%-16s n=%5d  disp=%.3f  media=%5.2f  corr(D,real)=%.3f'
                  % (clave, len(d), disp, float(por_eq.mean()), corr),
                  flush=True)
            errs_liga = {}
            for est in ('A_liga', 'B_equipo', 'C_movil5', 'D_ataque_defensa'):
                for dist, dv in (('poisson', 1.0), ('binneg', disp)):
                    acc = {'marginal': [], 'brier': [], 'ece': []}
                    for L in LINEAS[obj]:
                        p = d[est].apply(lambda m: _p_mas(m, L, dv))
                        real = (d['real'] > L).astype(float)
                        mt = metricas(p, real)
                        if mt is None:
                            continue
                        for k in acc:
                            acc[k].append(mt[k])
                    if not acc['marginal']:
                        continue
                    res = {k: float(np.nanmean(v)) for k, v in acc.items()}
                    acumulado.setdefault((est, dist), []).append((len(d), res))
                    errs_liga['%s/%s' % (est, dist)] = {
                        k: round(v, 5) for k, v in res.items()}
            por_liga[clave] = {'n': int(len(d)), 'dispersion': round(disp, 4),
                               'media': round(float(por_eq.mean()), 3),
                               'corr': round(corr, 4), 'errores': errs_liga}
        if not acumulado:
            continue
        filas = []
        for (est, dist), vals in acumulado.items():
            n = sum(v[0] for v in vals)
            agg = {k: sum(v[0] * v[1][k] for v in vals) / n
                   for k in ('marginal', 'brier', 'ece')}
            filas.append({'estimador': est, 'dist': dist, 'n': n, **agg})
        print()
        print('%-20s %-9s %10s %10s %10s'
              % ('estimador', 'distrib.', 'marginal', 'brier', 'ECE'))
        print('-' * 63)
        for f in sorted(filas, key=lambda f: f['brier']):
            print('%-20s %-9s %10.5f %10.5f %10.5f'
                  % (f['estimador'], f['dist'], f['marginal'], f['brier'],
                     f['ece']))
        # Se elige por ECE —calibración de verdad, decil a decil— y no por el
        # marginal, que no distingue un modelo de una constante.
        mejor = min(filas, key=lambda f: f['ece'])
        print('\nMEJOR por ECE: %s con %s (ece %.5f · brier %.5f · marginal '
              '%.5f)' % (mejor['estimador'], mejor['dist'], mejor['ece'],
                         mejor['brier'], mejor['marginal']))
        print('dispersión media por equipo: %.3f\n'
              % float(np.mean(disp_global)))
        resultado[obj] = {
            'filas': sorted(filas, key=lambda f: f['brier']),
            'mejor': mejor,
            'dispersion_media': round(float(np.mean(disp_global)), 4),
            'por_liga': por_liga,
        }
    json.dump(resultado, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
