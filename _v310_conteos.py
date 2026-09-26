# -*- coding: utf-8 -*-
"""
v310 — CÓRNERS, TARJETAS Y REMATES: ¿CUMPLE LO QUE PROMETE? FUERA DE MUESTRA.

El usuario: «analiza mejor las estadísticas y la historia de los partidos de
UEFA, los de CONCACAF y los de Liga MX; siento que el modelo no está bien en
cada uno. Tiene que estar bien calibrado: los goles, los córners, todo».

CÓMO SE MIDE
Con el código de PRODUCCIÓN (`rendimiento_equipos.corners_equipo`,
`tarjetas_equipo`, `remates_equipo`) y el histórico RECORTADO a lo anterior a
cada fecha: `panel_equipos._CACHE[clave]` se sustituye por las filas previas
y se vacían las cachés del módulo. Así cada partido se predice sólo con lo
que se sabía antes de jugarlo, que es lo que vio la tarjeta.

Para cada partido: λ y dispersión de total y por equipo, y P(más de L) en las
líneas habituales de la casa. Se compara con lo que pasó: tasa real por
banda de probabilidad, ECE, sesgo de la media y, como referencia, la línea
base «tasa histórica de la competición» (si el modelo no le gana a eso, no
está sumando nada).

Competiciones: Liga MX; selecciones (UEFA Nations League, CONCACAF Nations
League, amistosos, eliminatorias); Champions, Europa y Conference League.

Uso: python _v310_conteos.py        (escribe _v310_conteos.csv y .json)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import panel_equipos as pe
import rendimiento_equipos as rq

DESDE = {'liga_mx': '2024-07-01', 'selecciones': '2023-01-01',
         'champions': '2024-07-01', 'europa_league': '2024-07-01',
         'conference_league': '2024-07-01'}
LINEAS = {'corners': (7.5, 8.5, 9.5, 10.5, 11.5, 12.5),
          'tarjetas': (2.5, 3.5, 4.5, 5.5),
          'a_puerta': (6.5, 7.5, 8.5, 9.5, 10.5),
          'remates': (20.5, 22.5, 24.5, 26.5, 28.5)}
LINEAS_EQ = {'corners': (2.5, 3.5, 4.5, 5.5, 6.5),
             'tarjetas': (0.5, 1.5, 2.5),
             'a_puerta': (2.5, 3.5, 4.5, 5.5),
             'remates': (8.5, 10.5, 12.5, 14.5)}
import os as _os
CSV = _os.environ.get('V310_CONTEOS_CSV', '_v310_conteos.csv')


def _vaciar_cachés():
    for nombre, v in vars(rq).items():
        if isinstance(v, dict) and (nombre.startswith('_CACHE')
                                    or nombre.startswith('_MEMO')) \
                and nombre != '_CACHE_TENIS':
            v.clear()


def _real(r, col):
    try:
        a, b = float(r['home_' + col]), float(r['away_' + col])
        if a != a or b != b:
            return None, None
        return a, b
    except (TypeError, ValueError, KeyError):
        return None, None


def medir(clave: str) -> pd.DataFrame:
    completo = pe._historico(clave).copy()
    completo = completo[completo['date'].notna()].sort_values('date')
    ev = completo[(completo['date'] >= DESDE[clave])
                  & completo['home_corners'].notna()]
    filas = []
    for dia, g in ev.groupby(completo['date'].dt.normalize()):
        pe._CACHE[clave] = completo[completo['date'] < dia].reset_index(drop=True)
        _vaciar_cachés()
        for _, r in g.iterrows():
            h, a = r['home_team'], r['away_team']
            base = {'clave': clave, 'fecha': dia, 'home': h, 'away': a,
                    'torneo': r.get('tournament') if clave == 'selecciones'
                    else clave}
            try:
                ck = rq.corners_equipo(clave, h, a)
                # el torneo del partido, como lo pasa la tarjeta desde v310
                tor = str(r.get('tournament') or '') if clave == 'selecciones' else ''
                tj = rq.tarjetas_equipo(clave, h, a, torneo=tor)
                rm = rq.remates_equipo(clave, h, a, torneo=tor) or {}
            except Exception as e:
                print('  fallo', clave, h, a, e)
                continue
            for mercado, pred, col in (
                    ('corners', ck, 'corners'), ('tarjetas', tj, 'yellow'),
                    ('a_puerta', rm.get('a_puerta'), 'shots_on'),
                    ('remates', rm.get('totales'), None)):
                if not pred:
                    continue
                if col:
                    rh, ra = _real(r, col)
                else:
                    oh, oa = _real(r, 'shots_on')
                    fh, fa = _real(r, 'shots_off')
                    rh = None if oh is None or fh is None else oh + fh
                    ra = None if oa is None or fa is None else oa + fa
                if rh is None:
                    continue
                filas.append(dict(base, mercado=mercado,
                                  origen=pred.get('origen'),
                                  lam_h=pred.get('lambda_home'),
                                  lam_a=pred.get('lambda_away'),
                                  lam_t=pred.get('lambda_total'),
                                  disp=pred.get('dispersion'),
                                  disp_t=pred.get('dispersion_total'),
                                  real_h=rh, real_a=ra))
    return pd.DataFrame(filas)


def _p(lam, linea, disp):
    return rq.prob_mas_de(lam, linea, disp)


def grupo(r) -> str:
    if r['clave'] != 'selecciones':
        return {'liga_mx': 'Liga MX'}.get(r['clave'], 'UEFA clubes')
    t = str(r['torneo'] or '')
    if 'UEFA' in t or 'Euro' in t:
        return 'UEFA selecciones'
    if 'CONCACAF' in t or 'Oro' in t:
        return 'CONCACAF selecciones'
    if 'Amistoso' in t:
        return 'Amistosos'
    return 'Otras selecciones'


def ece(p, y, bins=10):
    p, y = np.asarray(p), np.asarray(y)
    if len(p) == 0:
        return None
    cortes = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, cortes) - 1, 0, bins - 1)
    e = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return round(float(e), 4)


def analizar(d: pd.DataFrame) -> dict:
    d = d.copy()
    d['grupo'] = d.apply(grupo, axis=1)
    d['real_t'] = d['real_h'] + d['real_a']
    out = {}
    filas_p = []
    for r in d.itertuples(index=False):
        for L in LINEAS[r.mercado]:
            if r.lam_t:
                filas_p.append({'grupo': r.grupo, 'mercado': r.mercado,
                                'tipo': 'total', 'linea': L, 'fecha': r.fecha,
                                'p': _p(r.lam_t, L, r.disp_t),
                                'y': int(r.real_t > L)})
        for lado, lam, real in (('local', r.lam_h, r.real_h),
                                ('visita', r.lam_a, r.real_a)):
            if not lam:
                continue
            for L in LINEAS_EQ[r.mercado]:
                filas_p.append({'grupo': r.grupo, 'mercado': r.mercado,
                                'tipo': lado, 'linea': L, 'fecha': r.fecha,
                                'p': _p(lam, L, r.disp),
                                'y': int(real > L)})
    P = pd.DataFrame(filas_p).dropna(subset=['p'])
    # ambos lados de cada línea: «más» con p y «menos» con 1-p
    P2 = pd.concat([P.assign(lado='mas'),
                    P.assign(lado='menos', p=1 - P['p'], y=1 - P['y'])])
    # línea base: tasa histórica de la competición en esa línea (con lo previo)
    P2 = P2.sort_values('fecha')
    P2['base'] = (P2.groupby(['grupo', 'mercado', 'tipo', 'linea', 'lado'])['y']
                  .transform(lambda s: s.shift(1).expanding(30).mean()))
    for (g, m), x in P2.groupby(['grupo', 'mercado']):
        sel = x[x['p'] >= 0.5]                 # lo que se ofrecería
        bandas = pd.cut(sel['p'], [.5, .55, .6, .65, .7, .75, .8, .85, .9, 1])
        xb = sel.dropna(subset=['base'])
        out.setdefault(g, {})[m] = {
            'partidos': int(d[(d['grupo'] == g) & (d['mercado'] == m)].shape[0]),
            'sesgo_media_total': round(float(
                (d[(d['grupo'] == g) & (d['mercado'] == m)]['lam_t']
                 - d[(d['grupo'] == g) & (d['mercado'] == m)]['real_t']).mean()),
                3),
            'ece_p>=50': ece(sel['p'], sel['y']),
            'brier_modelo': round(float(((xb['p'] - xb['y']) ** 2).mean()), 4)
            if len(xb) else None,
            'brier_base': round(float(((xb['base'] - xb['y']) ** 2).mean()), 4)
            if len(xb) else None,
            'bandas': {str(k): {'n': int(len(v)),
                                'p': round(float(v['p'].mean()), 3),
                                'real': round(float(v['y'].mean()), 3)}
                       for k, v in sel.groupby(bandas, observed=True)},
        }
    return out, P2


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    partes = []
    for clave in DESDE:
        print('midiendo', clave, flush=True)
        partes.append(medir(clave))
    d = pd.concat(partes, ignore_index=True)
    d.to_csv(CSV, index=False)
    out, _ = analizar(d)
    json.dump(out, open('_v310_conteos.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)
    for g, ms in out.items():
        for m, r in ms.items():
            print('%-22s %-9s n=%4d sesgo=%+.2f ece=%s brier %s vs base %s'
                  % (g, m, r['partidos'], r['sesgo_media_total'],
                     r['ece_p>=50'], r['brier_modelo'], r['brier_base']))


if __name__ == '__main__':
    main()
