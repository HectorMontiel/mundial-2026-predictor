#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v162 — INFORME DE CALIBRACIÓN DE CÓRNERS Y TARJETAS, COMPETICIÓN A COMPETICIÓN.

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
dejando una liga fuera (0,0247 en córners y 0,0539 en tarjetas), que es lo que
la interfaz enseña marcado como estimación.

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
    for etq in ('corners', 'tarjetas'):
        if etq == 'corners':
            ch = pd.to_numeric(d['home_corners'], errors='coerce')
            ca = pd.to_numeric(d['away_corners'], errors='coerce')
            lineas_eq, lineas_tot = LINEAS_CK_EQ, LINEAS_CK_TOT
        else:
            ch = (pd.to_numeric(d['home_yellow'], errors='coerce')
                  + pd.to_numeric(d['home_red'], errors='coerce'))
            ca = (pd.to_numeric(d['away_yellow'], errors='coerce')
                  + pd.to_numeric(d['away_red'], errors='coerce'))
            lineas_eq, lineas_tot = LINEAS_TJ_EQ, LINEAS_TJ_TOT
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

    for etq, cols_par, disponible in (
            ('corners', ('home_corners', 'away_corners'), disp.get('corners')),
            ('tarjetas', None, disp.get('tarjetas'))):
        if not disponible:
            salida[etq] = {'origen': 'estimado'}
            continue
        dd = rq._solo_reales(d, 'corners' if etq == 'corners' else 'yellow')
        if dd is None or getattr(dd, 'empty', True) or len(dd) < 400:
            salida[etq] = {'origen': 'estimado', 'motivo': 'muestra corta'}
            continue
        dd = dd.sort_values('date').reset_index(drop=True)
        if etq == 'corners':
            ch = pd.to_numeric(dd[cols_par[0]], errors='coerce')
            ca = pd.to_numeric(dd[cols_par[1]], errors='coerce')
            lineas_eq, lineas_tot = LINEAS_CK_EQ, LINEAS_CK_TOT
        else:
            ch = (pd.to_numeric(dd['home_yellow'], errors='coerce')
                  + pd.to_numeric(dd['home_red'], errors='coerce'))
            ca = (pd.to_numeric(dd['away_yellow'], errors='coerce')
                  + pd.to_numeric(dd['away_red'], errors='coerce'))
            lineas_eq, lineas_tot = LINEAS_TJ_EQ, LINEAS_TJ_TOT
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


def _tabla(doc: Dict) -> str:
    lineas = []
    cab = ('%-24s %-10s %8s %8s %8s %8s %8s'
           % ('competición', 'origen', 'partidos', 'ck err', 'ck corr',
              'tj err', 'tj corr'))
    lineas.append(cab)
    lineas.append('-' * len(cab))
    obs_ck, obs_tj, est = 0, 0, 0
    for f in doc['ligas']:
        ck = f.get('corners') or {}
        tj = f.get('tarjetas') or {}
        o_ck = ck.get('origen', '-')
        o_tj = tj.get('origen', '-')
        origen = ('observado' if o_ck == 'observado' and o_tj == 'observado'
                  else ('mixto' if 'observado' in (o_ck, o_tj) else 'estimado'))
        obs_ck += int(o_ck == 'observado')
        obs_tj += int(o_tj == 'observado')
        est += int(origen == 'estimado')

        def _c(bloque, campo):
            m = (bloque or {}).get('por_equipo') or {}
            v = m.get(campo)
            return ('%8.4f' % v) if isinstance(v, (int, float)) else '       -'

        lineas.append('%-24s %-10s %8s %s %s %s %s'
                      % (f['clave'], origen,
                         f.get('partidos_espn', 0),
                         _c(ck, 'error_calib'), _c(ck, 'corr'),
                         _c(tj, 'error_calib'), _c(tj, 'corr')))
    lineas.append('')
    lineas.append('competiciones con córners OBSERVADOS ..... %d de %d'
                  % (obs_ck, len(doc['ligas'])))
    lineas.append('competiciones con tarjetas OBSERVADAS .... %d de %d'
                  % (obs_tj, len(doc['ligas'])))
    lineas.append('competiciones sólo con estimación ........ %d' % est)
    # medias sobre las observadas
    for etq in ('corners', 'tarjetas'):
        errs = [((f.get(etq) or {}).get('por_equipo') or {}).get('error_calib')
                for f in doc['ligas']
                if (f.get(etq) or {}).get('origen') == 'observado']
        errs = [e for e in errs if isinstance(e, (int, float))]
        if errs:
            lineas.append('error de calibración medio en %s observados: %.4f '
                          '(%d competiciones)' % (etq, float(np.mean(errs)),
                                                  len(errs)))
    lineas.append('estimación (validación dejando una liga fuera): '
                  'córners 0,0247 · tarjetas 0,0539')
    return '\n'.join(lineas)


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
            f.write('# Informe de calibración — córners y tarjetas\n\n')
            f.write('Generado %s\n\n```\n%s\n```\n'
                    % (doc['generado'], _tabla(doc)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
