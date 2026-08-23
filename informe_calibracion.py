#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v162 — INFORME DE CALIBRACIÓN, COMPETICIÓN A COMPETICIÓN.

v163 — y con REMATES, en sus dos mercados (totales y a puerta), medidos igual.

Para qué
--------
Se pidió que TODAS las competiciones enseñen córners y tarjetas. Con `stats_espn`
la mayoría pasan a tener datos REALES y unas pocas se quedan con la estimación
de `stats_estimadas`. Eso obliga a poder decir, de cada una, cuánto vale su
número — y no de oído: con el mismo error de calibración contra la frecuencia
real que se usó para cerrar córners en la v159 y tarjetas en la v160.

Qué mide
--------
Para cada competición con datos observados, y sobre su tramo de juicio (el
último 30 % por fecha, con medias móviles desplazadas un partido para que nada
vea su propio resultado):

  · error de calibración: |P(más de L) calculada − frecuencia real|, promediado
    sobre las líneas que cotiza la casa
  · correlación entre la lambda estimada y el resultado real
  · el número de observaciones, para saber de qué muestra sale cada cifra

Y para las que NO tienen datos, se anota el error medido en la validación
dejando una liga fuera (0,0247 en córners, 0,0539 en tarjetas, 0,0281 en
remates totales y 0,0168 a puerta), que es lo que la interfaz enseña marcado
como estimación.

Uso:
    python informe_calibracion.py                  # todas
    python informe_calibracion.py --liga liga_mx
    python informe_calibracion.py --md INFORME.md  # además, en markdown
"""
import argparse
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('informe_calibracion')

VENTANA = 10
MINP = 3
LINEAS_CK_EQ = [3.5, 4.5, 5.5, 6.5]
LINEAS_CK_TOT = [8.5, 9.5, 10.5, 11.5]
LINEAS_TJ_EQ = [0.5, 1.5, 2.5, 3.5]
LINEAS_TJ_TOT = [2.5, 3.5, 4.5, 5.5]
# v163 — las líneas que de verdad cotiza la casa en remates. Son las mismas
# con las que se eligió el estimador en `_v163_remates_estimadores.py`, para
# que este informe y aquella medición hablen del mismo número.
LINEAS_RM_EQ = [9.5, 11.5, 13.5, 15.5]
LINEAS_RM_TOT = [20.5, 22.5, 24.5, 26.5]
LINEAS_RMON_EQ = [2.5, 3.5, 4.5, 5.5]
LINEAS_RMON_TOT = [6.5, 7.5, 8.5, 9.5]

# etiqueta -> (columna en `_solo_reales`, líneas por equipo, líneas del total,
#              clave de `stats_disponibles`)
MERCADOS = {
    'corners': ('corners', LINEAS_CK_EQ, LINEAS_CK_TOT, 'corners'),
    'tarjetas': ('yellow', LINEAS_TJ_EQ, LINEAS_TJ_TOT, 'tarjetas'),
    'remates': ('shots_on', LINEAS_RM_EQ, LINEAS_RM_TOT, 'remates'),
    'remates_on': ('shots_on', LINEAS_RMON_EQ, LINEAS_RMON_TOT, 'remates'),
}


def _par_columnas(d, etq):
    """
    Los dos bandos de un mercado, con sus líneas.

    Estaba escrito dos veces —una en `_de_cache` y otra en `_de_liga`— con un
    if/else por mercado. Con cuatro mercados en vez de dos eso son ocho ramas
    que hay que acordarse de tocar a la vez, así que se junta aquí: los dos
    caminos leen columnas con los mismos nombres (`_de_cache` renombra los
    suyos antes de llamar), que es lo que permite compartirlo.
    """
    if etq == 'corners':
        ch = pd.to_numeric(d['home_corners'], errors='coerce')
        ca = pd.to_numeric(d['away_corners'], errors='coerce')
    elif etq == 'tarjetas':
        ch = (pd.to_numeric(d['home_yellow'], errors='coerce')
              + pd.to_numeric(d['home_red'], errors='coerce'))
        ca = (pd.to_numeric(d['away_yellow'], errors='coerce')
              + pd.to_numeric(d['away_red'], errors='coerce'))
    elif etq == 'remates_on':
        ch = pd.to_numeric(d['home_shots_on'], errors='coerce')
        ca = pd.to_numeric(d['away_shots_on'], errors='coerce')
    else:                                   # remates totales
        ch = (pd.to_numeric(d['home_shots_on'], errors='coerce')
              + pd.to_numeric(d['home_shots_off'], errors='coerce'))
        ca = (pd.to_numeric(d['away_shots_on'], errors='coerce')
              + pd.to_numeric(d['away_shots_off'], errors='coerce'))
    _, lineas_eq, lineas_tot, _ = MERCADOS[etq]
    return ch, ca, lineas_eq, lineas_tot
MIN_JUICIO = 300


def _movil(g, v, n=VENTANA):
    return v.groupby(g).transform(
        lambda s: s.shift().rolling(n, min_periods=MINP).mean())


def _prob_mas(media, linea, disp):
    from scipy import stats as st
    m = np.asarray(media, float)
    k = int(np.floor(linea))
    if disp is None or disp <= 1.0001:
        return 1.0 - st.poisson.cdf(k, m)
    r = m / (disp - 1.0)
    return 1.0 - st.nbinom.cdf(k, r, r / (r + m))


def _metricas(pred, real, lineas, disp) -> Optional[Dict]:
    pred = np.asarray(pred, float)
    real = np.asarray(real, float)
    ok = np.isfinite(pred) & np.isfinite(real) & (pred > 0)
    if ok.sum() < MIN_JUICIO:
        return None
    p, x = pred[ok], real[ok]
    err = [abs(float(_prob_mas(p, L, disp).mean()) - float((x > L).mean()))
           for L in lineas]
    return {'error_calib': round(float(np.mean(err)), 4),
            'corr': round(float(np.corrcoef(p, x)[0, 1]), 4)
            if np.std(p) > 0 else None,
            'n': int(ok.sum()),
            'media_pred': round(float(p.mean()), 3),
            'media_real': round(float(x.mean()), 3)}


def _de_cache(clave: str) -> Optional[Dict]:
    """
    Las metricas de una competicion medidas SOBRE LA CACHE de `stats_espn`.

    Existe para no tener que reconstruir los 61 historicos antes de poder
    informar. La cache es la fuente de esas estadisticas —lo que
    `league_engine` inyecta cada noche es exactamente esto—, asi que medir aqui
    da el mismo numero sin esperar a un `--build` de una hora.

    Los nombres de equipo son los de ESPN y no los del catalogo, y da igual: lo
    que se mide es la calidad del estimador dentro de la propia competicion,
    donde los nombres solo sirven para agrupar.
    """
    import stats_espn
    c = stats_espn.leer(clave)
    if not len(c):
        return None
    d = c.copy()
    d['date'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    d = d.rename(columns={'home': 'home_team', 'away': 'away_team'})
    if len(d) < 400:
        return {'clave': clave, 'estado': 'muestra corta',
                'partidos_espn': int(len(d))}

    salida = {'clave': clave, 'estado': 'ok', 'partidos_espn': int(len(d)),
              'fuente': 'cache'}
    for etq in MERCADOS:
        try:
            ch, ca, lineas_eq, lineas_tot = _par_columnas(d, etq)
        except KeyError:
            salida[etq] = {'origen': 'estimado', 'motivo': 'sin columna'}
            continue
        dd = d.assign(_h=ch, _a=ca).dropna(subset=['_h', '_a'])
        if len(dd) < 400:
            salida[etq] = {'origen': 'estimado', 'motivo': 'muestra corta'}
            continue
        serie = pd.concat([dd['_h'], dd['_a']])
        disp_eq = max(float(serie.var() / serie.mean()), 1.0)
        tot = dd['_h'] + dd['_a']
        disp_tot = max(float(tot.var() / tot.mean()), 1.0)
        lh = (_movil(dd['home_team'], dd['_h'])
              + _movil(dd['away_team'], dd['_h'])) / 2.0
        la = (_movil(dd['away_team'], dd['_a'])
              + _movil(dd['home_team'], dd['_a'])) / 2.0
        corte = dd['date'].quantile(0.70)
        J = (dd['date'] > corte).to_numpy()
        m_eq = _metricas(np.concatenate([lh.to_numpy()[J], la.to_numpy()[J]]),
                         np.concatenate([dd['_h'].to_numpy()[J],
                                         dd['_a'].to_numpy()[J]]),
                         lineas_eq, disp_eq)
        # el total: media de la competición SÓLO en córners; en tarjetas y en
        # remates gana la suma de las dos lambdas, y está medido en cada uno
        # (§10.8, §11.3 y §13.3)
        base = (tot.expanding().mean().shift().to_numpy()[J] if etq == 'corners'
                else (lh + la).to_numpy()[J])
        m_tot = _metricas(base, tot.to_numpy()[J], lineas_tot, disp_tot)
        salida[etq] = {'origen': 'observado', 'n_filas': int(len(dd)),
                       'dispersion_equipo': round(disp_eq, 4),
                       'dispersion_total': round(disp_tot, 4),
                       'media_total': round(float(tot.mean()), 3),
                       'por_equipo': m_eq, 'total': m_tot}
    return salida


def _de_liga(clave: str) -> Dict:
    """Las métricas de una competición, o el motivo por el que no las hay."""
    import rendimiento_equipos as rq

    salida = {'clave': clave}
    try:
        disp = rq.stats_disponibles(clave)
    except Exception as e:
        return {**salida, 'estado': 'error', 'motivo': str(e)[:60]}
    d = rq._historico(clave)
    if d is None or getattr(d, 'empty', True):
        return {**salida, 'estado': 'sin histórico'}

    try:
        import stats_espn
        cache = stats_espn.leer(clave)
        salida['partidos_espn'] = int(len(cache))
    except Exception:
        salida['partidos_espn'] = 0

    for etq, (col_real, _le, _lt, clave_disp) in MERCADOS.items():
        if not disp.get(clave_disp):
            salida[etq] = {'origen': 'estimado'}
            continue
        dd = rq._solo_reales(d, col_real)
        if dd is None or getattr(dd, 'empty', True) or len(dd) < 400:
            salida[etq] = {'origen': 'estimado', 'motivo': 'muestra corta'}
            continue
        dd = dd.sort_values('date').reset_index(drop=True)
        try:
            ch, ca, lineas_eq, lineas_tot = _par_columnas(dd, etq)
        except KeyError:
            salida[etq] = {'origen': 'estimado', 'motivo': 'sin columna'}
            continue
        dd = dd.assign(_h=ch, _a=ca).dropna(subset=['_h', '_a'])
        if len(dd) < 400:
            salida[etq] = {'origen': 'estimado', 'motivo': 'muestra corta'}
            continue

        serie_eq = pd.concat([dd['_h'], dd['_a']])
        disp_eq = max(float(serie_eq.var() / serie_eq.mean()), 1.0)
        tot = dd['_h'] + dd['_a']
        disp_tot = max(float(tot.var() / tot.mean()), 1.0)

        lh = (_movil(dd['home_team'], dd['_h'])
              + _movil(dd['away_team'], dd['_h'])) / 2.0
        la = (_movil(dd['away_team'], dd['_a'])
              + _movil(dd['home_team'], dd['_a'])) / 2.0
        corte = dd['date'].quantile(0.70)
        J = (dd['date'] > corte).to_numpy()

        m_eq = _metricas(np.concatenate([lh.to_numpy()[J], la.to_numpy()[J]]),
                         np.concatenate([dd['_h'].to_numpy()[J],
                                         dd['_a'].to_numpy()[J]]),
                         lineas_eq, disp_eq)
        # el total: media de la competición en córners, suma de lambdas en
        # tarjetas — cada uno el mejor medido para su mercado (§10.8 y §11.3)
        if etq == 'corners':
            base = tot.expanding().mean().shift().to_numpy()[J]
        else:
            base = (lh + la).to_numpy()[J]
        m_tot = _metricas(base, tot.to_numpy()[J], lineas_tot, disp_tot)

        salida[etq] = {'origen': 'observado', 'n_filas': int(len(dd)),
                       'dispersion_equipo': round(disp_eq, 4),
                       'dispersion_total': round(disp_tot, 4),
                       'media_total': round(float(tot.mean()), 3),
                       'por_equipo': m_eq, 'total': m_tot}
    salida['estado'] = 'ok'
    return salida


def generar(claves: Optional[List[str]] = None) -> Dict:
    import fixtures_espn
    from config import LEAGUES
    claves = claves or [c for c, v in LEAGUES.items()
                        if v.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    filas = []
    for c in claves:
        try:
            # La cache es la fuente de estas estadisticas y no exige que el
            # historico se haya reconstruido; si una competicion no la tiene
            # —las 20 de football-data— se mide sobre su historico, que ahi si
            # es observado desde siempre.
            r = _de_cache(c)
            filas.append(r if (r and r.get('estado') == 'ok') else _de_liga(c))
        except Exception as e:
            logger.warning('[informe] %s: %s: %s', c, type(e).__name__, e)
            filas.append({'clave': c, 'estado': 'error', 'motivo': str(e)[:80]})
    return {'generado': pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ligas': filas}


ROTULOS = {'corners': 'córners', 'tarjetas': 'tarjetas',
           'remates': 'remates', 'remates_on': 'remates a puerta'}
CORTOS = {'corners': 'ck', 'tarjetas': 'tj', 'remates': 'rm',
          'remates_on': 'ra'}
# el error medido dejando una liga fuera, para las que no tienen datos propios
ESTIMADO = {'corners': 0.0247, 'tarjetas': 0.0539,
            'remates': 0.0281, 'remates_on': 0.0168}


def _tabla(doc: Dict) -> str:
    lineas = []
    cab = ('%-24s %-10s %8s' % ('competición', 'origen', 'partidos')
           + ''.join('%8s %8s' % (CORTOS[e] + ' err', CORTOS[e] + ' corr')
                     for e in MERCADOS))
    lineas.append(cab)
    lineas.append('-' * len(cab))
    obs = {e: 0 for e in MERCADOS}
    est = 0
    for f in doc['ligas']:
        origenes = [(f.get(e) or {}).get('origen', '-') for e in MERCADOS]
        for e, o in zip(MERCADOS, origenes):
            obs[e] += int(o == 'observado')
        if all(o == 'observado' for o in origenes):
            origen = 'observado'
        elif 'observado' in origenes:
            origen = 'mixto'
        else:
            origen = 'estimado'
            est += 1

        def _c(etq, campo):
            m = ((f.get(etq) or {}).get('por_equipo') or {})
            v = m.get(campo)
            return ('%8.4f' % v) if isinstance(v, (int, float)) else '       -'

        lineas.append('%-24s %-10s %8s' % (f['clave'], origen,
                                           f.get('partidos_espn', 0))
                      + ''.join(_c(e, 'error_calib') + _c(e, 'corr')
                                for e in MERCADOS))
    lineas.append('')
    for e in MERCADOS:
        lineas.append('competiciones con %-17s OBSERVADOS .. %d de %d'
                      % (ROTULOS[e], obs[e], len(doc['ligas'])))
    lineas.append('competiciones sin ningún dato observado ......... %d' % est)
    for etq in MERCADOS:
        errs = [((f.get(etq) or {}).get('por_equipo') or {}).get('error_calib')
                for f in doc['ligas']
                if (f.get(etq) or {}).get('origen') == 'observado']
        errs = [e for e in errs if isinstance(e, (int, float))]
        if errs:
            lineas.append('error de calibración medio en %s observados: %.4f '
                          '(%d competiciones)' % (ROTULOS[etq],
                                                  float(np.mean(errs)),
                                                  len(errs)))
    lineas.append('estimación (validación dejando una liga fuera): '
                  + ' · '.join('%s %.4f' % (ROTULOS[e], ESTIMADO[e])
                               for e in MERCADOS))
    return chr(10).join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--liga', default=None)
    ap.add_argument('--json', default='_v162_calibracion_por_liga.json')
    ap.add_argument('--md', default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    doc = generar([args.liga] if args.liga else None)
    print(_tabla(doc))
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, default=float)
    if args.md:
        with open(args.md, 'w', encoding='utf-8') as f:
            f.write('# Informe de calibración — córners, tarjetas y remates\n\n')
            f.write('Generado %s\n\n```\n%s\n```\n'
                    % (doc['generado'], _tabla(doc)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
