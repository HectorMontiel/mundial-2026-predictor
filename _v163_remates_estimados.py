#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — CUÁNTO VALE ESTIMAR LOS REMATES DE UNA LIGA QUE NO PUBLICA NINGUNO.

Mismo método con el que se cerraron córners y tarjetas en la v162: **validación
dejando una liga fuera**. Se ajusta la relación nivel-de-remates ~ nivel-de-goles
con las N−1 competiciones que sí tienen datos y se predice la que queda como si
no tuviera ninguno, que es exactamente la situación de producción. Medirlo
dentro de la misma liga sería trampa.

Se comparan cuatro cosas por objetivo (remates totales y a puerta):

    techo        el estimador real (ataque/defensa, ventana 10, binneg)
    predicha     el nivel de la liga predicho de sus goles      ← candidato
    global       la media de las otras ligas, sin mirar los goles
    modulada     la predicha multiplicada por el ataque del equipo

La última se prueba porque en córners subía la correlación y empeoraba la
calibración, y en tarjetas salía con el signo cambiado. No se hereda: se mide.

    python _v163_remates_estimados.py
"""
import json
import logging
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_remates_estimados.json'
LINEAS = {'tot': (9.5, 11.5, 13.5, 15.5), 'on': (2.5, 3.5, 4.5, 5.5)}
MIN_PREV = 5


def perfil(clave, obj):
    """Nivel de goles, nivel de remates, reparto por bando y dispersión."""
    from _v163_remates_estimadores import marco, dispersion
    d = marco(clave)
    if d is None or len(d) < 400:
        return None, None
    gh = pd.to_numeric(d.get('home_goals'), errors='coerce')
    ga = pd.to_numeric(d.get('away_goals'), errors='coerce')
    rh = d['home_rem_' + obj].astype(float)
    ra = d['away_rem_' + obj].astype(float)
    s = pd.concat([rh, ra]).dropna()
    return d, {'n': int(len(d)), 'goles': float((gh + ga).mean()),
               'nivel': float((rh + ra).mean()),
               'prop_h': float(rh.mean() / (rh.mean() + ra.mean())),
               'disp': float(dispersion(s))}


def corpus(d, obj):
    """
    Pase cronológico: por cada equipo-partido, lo real, el estimador con datos
    y el ataque móvil del equipo (para la variante modulada).
    """
    col_h, col_a = 'home_rem_' + obj, 'away_rem_' + obj
    d = d.sort_values('date').reset_index(drop=True)
    hist, lig = {}, {'casa': [], 'fuera': []}

    def H(eq):
        return hist.setdefault(eq, {'tira_casa': [], 'tira_fuera': [],
                                    'conc_casa': [], 'conc_fuera': [],
                                    'goles': []})

    filas = []
    for f in d.itertuples(index=False):
        vh, va = float(getattr(f, col_h)), float(getattr(f, col_a))
        gh = float(getattr(f, 'home_goals', 0) or 0)
        ga = float(getattr(f, 'away_goals', 0) or 0)
        hh, ha = H(f.home_team), H(f.away_team)
        for bando, propio, rival, tira, conc, real in (
                ('casa', hh, ha, 'tira_casa', 'conc_fuera', vh),
                ('fuera', ha, hh, 'tira_fuera', 'conc_casa', va)):
            s, r, g = propio[tira], rival[conc], propio['goles']
            if (len(s) < MIN_PREV or len(r) < MIN_PREV or len(g) < MIN_PREV
                    or len(lig[bando]) < 60):
                continue
            filas.append({
                'bando': bando, 'real': real,
                'con_datos': (float(np.mean(s[-10:]))
                              + float(np.mean(r[-10:]))) / 2.0,
                'ataque': float(np.mean(g[-10:])),
            })
        hh['tira_casa'].append(vh)
        hh['conc_casa'].append(va)
        hh['goles'].append(gh)
        ha['tira_fuera'].append(va)
        ha['conc_fuera'].append(vh)
        ha['goles'].append(ga)
        lig['casa'].append(vh)
        lig['fuera'].append(va)
    x = pd.DataFrame(filas)
    if len(x):
        # ataque normalizado por el ataque medio de la competición, que es la
        # variante que en córners salió mejor que la sin normalizar
        x['ataque_rel'] = x['ataque'] / max(float(x['ataque'].mean()), 1e-6)
    return x


def main():
    from _v163_remates_estimadores import _p_mas, metricas

    ligas = json.load(open('_v163_cobertura_remates.json',
                           encoding='utf-8'))['con_remates']
    salida = {}
    for obj in ('tot', 'on'):
        print('=' * 78)
        print('ESTIMACIÓN SIN DATOS — remates %s'
              % ('TOTALES' if obj == 'tot' else 'A PUERTA'))
        print('=' * 78)
        perfiles, corpora = {}, {}
        for clave in ligas:
            d, p = perfil(clave, obj)
            if p is None:
                continue
            c = corpus(d, obj)
            if len(c) < 600:
                continue
            perfiles[clave], corpora[clave] = p, c
            print('%-16s goles %.2f  nivel %.2f  prop_h %.3f  disp %.3f  n=%d'
                  % (clave, p['goles'], p['nivel'], p['prop_h'], p['disp'],
                     len(c)), flush=True)
        if len(perfiles) < 6:
            print('muy pocas competiciones con datos; no se puede validar')
            continue

        nivel = np.array([p['nivel'] for p in perfiles.values()])
        goles = np.array([p['goles'] for p in perfiles.values()])
        corr_nivel = float(np.corrcoef(goles, nivel)[0, 1])
        print('\ncorrelación nivel de remates ~ nivel de goles entre ligas: '
              '%+.3f   (rango %.2f a %.2f)'
              % (corr_nivel, nivel.min(), nivel.max()))

        acc = {}
        for fuera, p_f in perfiles.items():
            otras = {k: v for k, v in perfiles.items() if k != fuera}
            x = np.array([[1.0, v['goles']] for v in otras.values()])
            y = np.array([v['nivel'] for v in otras.values()])
            coef, *_ = np.linalg.lstsq(x, y, rcond=None)
            pred = float(coef[0] + coef[1] * p_f['goles'])
            lo, hi = y.mean() - 2 * y.std(), y.mean() + 2 * y.std()
            pred = float(np.clip(pred, lo, hi))
            glob = float(y.mean())
            prop = float(np.median([v['prop_h'] for v in otras.values()]))
            disp = float(np.median([v['disp'] for v in otras.values()]))
            disp_real = p_f['disp']

            c = corpora[fuera]
            es_casa = c['bando'] == 'casa'
            lam_pred = np.where(es_casa, pred * prop, pred * (1 - prop))
            lam_glob = np.where(es_casa, glob * prop, glob * (1 - prop))
            variantes = {
                'techo': (c['con_datos'].to_numpy(float), disp_real),
                'predicha': (lam_pred, disp),
                'global': (lam_glob, disp),
                'modulada': (lam_pred * c['ataque_rel'].to_numpy(float), disp),
            }
            for nombre, (lam, dv) in variantes.items():
                ms = {'marginal': [], 'brier': [], 'ece': []}
                for L in LINEAS[obj]:
                    p = np.array([_p_mas(m, L, dv) or np.nan for m in lam])
                    real = (c['real'] > L).astype(float).to_numpy()
                    mt = metricas(p, real)
                    if mt is None:
                        continue
                    for k in ms:
                        ms[k].append(mt[k])
                if not ms['marginal']:
                    continue
                res = {k: float(np.nanmean(v)) for k, v in ms.items()}
                res['corr'] = float(np.corrcoef(lam, c['real'])[0, 1]) \
                    if np.std(lam) > 1e-9 else 0.0
                acc.setdefault(nombre, []).append((len(c), res))

        print()
        print('%-12s %10s %10s %10s %8s' % ('variante', 'marginal', 'brier',
                                            'ECE', 'corr'))
        print('-' * 54)
        tabla = {}
        for nombre, vals in acc.items():
            n = sum(v[0] for v in vals)
            tabla[nombre] = {k: sum(v[0] * v[1][k] for v in vals) / n
                             for k in ('marginal', 'brier', 'ece', 'corr')}
            tabla[nombre]['n'] = n
        for nombre in ('techo', 'predicha', 'global', 'modulada'):
            if nombre not in tabla:
                continue
            t = tabla[nombre]
            print('%-12s %10.5f %10.5f %10.5f %8.3f'
                  % (nombre, t['marginal'], t['brier'], t['ece'], t['corr']))
        print()
        salida[obj] = {
            'corr_nivel_goles': round(corr_nivel, 4),
            'ligas': len(perfiles),
            'tabla': {k: {kk: round(vv, 5) if isinstance(vv, float) else vv
                          for kk, vv in v.items()} for k, v in tabla.items()},
            'perfiles': {k: {kk: round(vv, 4) if isinstance(vv, float) else vv
                             for kk, vv in v.items()}
                         for k, v in perfiles.items()},
        }
    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
