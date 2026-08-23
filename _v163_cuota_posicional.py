#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — EL PREVIO POSICIONAL, EN CUOTA DEL EQUIPO Y NO EN REMATES.

De dónde viene la pregunta
--------------------------
El modelo por jugador que ganó la medición (`_v163_remates_jugador.py`) encoge
la media del jugador hacia la media de su posición:

    λ = (n · media_propia + K · media_posición) / (n + K)

con K=6 en remates totales y K=12 a puerta. El problema práctico es de dónde
sale «media_posición» en producción: medirla por competición exige tener
descargada la estadística por jugador de esa competición entera, que son cientos
de peticiones y no se tienen en 62 ligas.

La salida es medirla en CUOTA del equipo en vez de en remates absolutos:

    cuota_posición = remates del jugador / remates totales de su equipo

Eso es adimensional: no depende de si la liga tira 25 o 21 veces por partido,
así que una tabla sirve para todas. Y se reconvierte a remates multiplicando
por lo que se espera que tire el equipo en ESE partido, que es exactamente lo
que calcula la Parte 1 —o sea que el previo posicional queda enganchado al
modelo por equipo en vez de ser un número suelto.

Lo que hay que comprobar, y es el motivo de este script:

  1. que la cuota por posición sea estable ENTRE competiciones (si no, la tabla
     no es transportable y hay que medirla liga a liga);
  2. que encoger hacia `cuota_posición · λ_equipo` calibre igual de bien que
     encoger hacia la media posicional cruda de la propia liga, que es el techo
     de esta idea.

    python _v163_cuota_posicional.py
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

SALIDA = 'calibracion_remates_jugador.json'
INFORME = '_v163_cuota_posicional.json'
CODIGOS = ['eng.1', 'esp.1', 'mex.1']
VENTANA = 10
MIN_PREV = 4
# el encogimiento que ganó la medición, por objetivo
K = {'tot': 6, 'on': 12}
MIN_OBS_POSICION = 150


def _cargar(code):
    import os
    ruta = os.path.join('_v163_cache_jugadores', '%s.json' % code)
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding='utf-8') as f:
        return pd.DataFrame(json.load(f))


# El `summary` de ESPN da la posición fina («AM-L», «CD-R») y el ROSTER de
# temporada —que es el que tiene precalculado el proyecto en
# `goleadores_cache.json`, gratis y sin peticiones— sólo da la gruesa. Hacen
# falta las dos tablas: la fina para la ficha, que se sirve del summary, y la
# gruesa para la tarjeta, que se sirve del roster.
GRUESA = {
    'G': 'G',
    'CD': 'D', 'CD-L': 'D', 'CD-R': 'D', 'LB': 'D', 'RB': 'D', 'SW': 'D',
    'LWB': 'D', 'RWB': 'D',
    'DM': 'M', 'CM': 'M', 'CM-L': 'M', 'CM-R': 'M', 'LM': 'M', 'RM': 'M',
    'M': 'M', 'AM': 'M', 'AM-L': 'M', 'AM-R': 'M',
    'F': 'F', 'CF': 'F', 'CF-L': 'F', 'CF-R': 'F', 'LF': 'F', 'RF': 'F',
    'RCF': 'F', 'LCF': 'F', 'SS': 'F',
}


def cuotas(d, obj, gruesa=False):
    """Cuota media del total del equipo por posición, entre titulares."""
    col = 'remates' if obj == 'tot' else 'al_arco'
    filas = []
    for ev, g in d.groupby('evento', sort=False):
        for equipo, ge in g.groupby('equipo', sort=False):
            tot = float(ge[col].sum())
            if tot <= 0:
                continue
            for r in ge.itertuples(index=False):
                if not r.titular or not r.posicion or r.posicion == 'SUB':
                    continue
                pos = GRUESA.get(r.posicion) if gruesa else r.posicion
                if not pos:
                    continue
                filas.append({'pos': pos,
                              'cuota': float(getattr(r, col)) / tot})
    x = pd.DataFrame(filas)
    if not len(x):
        return {}
    g = x.groupby('pos')['cuota'].agg(['count', 'mean'])
    return {p: float(r['mean']) for p, r in g.iterrows()
            if r['count'] >= MIN_OBS_POSICION}


def corpus(d, obj, tabla_pos):
    """
    Pase cronológico con las dos formas del previo posicional.

    `ref_liga`  media cruda de la posición en ESTA competición (el techo)
    `ref_cuota` cuota de la posición (tabla común) × lo que tira su equipo
    """
    col = 'remates' if obj == 'tot' else 'al_arco'
    d = d.sort_values(['fecha', 'evento']).copy()
    hist, pos_de, eq_hist, pos_hist = {}, {}, {}, {}
    filas = []
    for ev, g in d.groupby('evento', sort=False):
        for r in g.itertuples(index=False):
            if not r.titular:
                continue
            h = hist.get(r.jugador_id) or []
            eq = eq_hist.get(r.equipo) or []
            pos = pos_de.get(r.jugador_id)
            ph = pos_hist.get(pos) or [] if pos else []
            if len(h) < MIN_PREV or len(eq) < 6 or len(ph) < 200:
                continue
            if pos not in tabla_pos:
                continue
            n = float(min(len(h), VENTANA))
            plano = float(np.mean(h[-VENTANA:]))
            lam_eq = float(np.mean(eq[-VENTANA:]))
            filas.append({
                'real': float(getattr(r, col)),
                'plano': plano, 'n': n,
                'ref_liga': float(np.mean(ph)),
                'ref_cuota': float(tabla_pos[pos]) * lam_eq,
                'pos': pos,
            })
        tot_eq = {}
        for r in g.itertuples(index=False):
            tot_eq[r.equipo] = tot_eq.get(r.equipo, 0.0) + float(getattr(r, col))
            if r.titular:
                hist.setdefault(r.jugador_id, []).append(float(getattr(r, col)))
                if r.posicion and r.posicion != 'SUB':
                    c = pos_de.setdefault('_c_' + r.jugador_id, {})
                    c[r.posicion] = c.get(r.posicion, 0) + 1
                    pos_de[r.jugador_id] = max(c, key=c.get)
                    pos_hist.setdefault(r.posicion, []).append(
                        float(getattr(r, col)))
        for e, v in tot_eq.items():
            eq_hist.setdefault(e, []).append(v)
    return pd.DataFrame(filas)


def main():
    from _v163_remates_estimadores import metricas
    from _v163_remates_jugador import _p_al_menos_uno

    marcos = {c: _cargar(c) for c in CODIGOS}
    marcos = {c: d for c, d in marcos.items() if d is not None and len(d)}
    if not marcos:
        print('no hay caché de jugadores; corre antes '
              '_v163_remates_jugador.py')
        return 1

    doc = {'generado': pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ'),
           'ligas_ajuste': sorted(marcos), 'K': K, 'cuotas': {},
           'calibracion': {}}
    informe = {}
    for obj in ('tot', 'on'):
        print('=' * 78)
        print('CUOTA POSICIONAL — remates %s'
              % ('TOTALES' if obj == 'tot' else 'A PUERTA'))
        print('=' * 78)
        por_liga = {c: cuotas(d, obj) for c, d in marcos.items()}
        posiciones = sorted(set().union(*[set(v) for v in por_liga.values()]))
        print('%-8s %s' % ('posición',
                           ' '.join('%9s' % c for c in sorted(marcos))
                           + '   %9s %7s' % ('media', 'disp.rel')))
        tabla, detalle = {}, {}
        for p in posiciones:
            vals = [por_liga[c][p] for c in sorted(marcos) if p in por_liga[c]]
            if len(vals) < 2:
                continue
            m = float(np.mean(vals))
            rel = float(np.std(vals) / m) if m > 0 else float('nan')
            tabla[p] = round(m, 5)
            detalle[p] = {'por_liga': {c: round(por_liga[c].get(p, float('nan')), 5)
                                       for c in sorted(marcos)
                                       if p in por_liga[c]},
                          'media': round(m, 5), 'dispersion_relativa': round(rel, 4)}
            print('%-8s %s   %9.4f %7.3f'
                  % (p, ' '.join('%9.4f' % por_liga[c][p] if p in por_liga[c]
                                 else '%9s' % '-' for c in sorted(marcos)),
                     m, rel))
        disp_media = float(np.mean([d['dispersion_relativa']
                                    for d in detalle.values()]))
        print('\ndispersión relativa media entre competiciones: %.3f' % disp_media)

        # ¿calibra igual encogiendo hacia la cuota que hacia la media de liga?
        print()
        print('%-24s %10s %10s %10s %8s'
              % ('previo', 'marginal', 'brier', 'ECE', 'corr'))
        print('-' * 66)
        acc = {}
        for code, d in marcos.items():
            c = corpus(d, obj, tabla)
            if len(c) < 800:
                continue
            for nombre, ref in (('media de la liga', 'ref_liga'),
                                ('cuota × λ equipo', 'ref_cuota')):
                lam = ((c['n'] * c['plano'] + K[obj] * c[ref])
                       / (c['n'] + K[obj]))
                p = lam.apply(lambda x: _p_al_menos_uno(x, 1.0))
                real = (c['real'] >= 1).astype(float)
                mt = metricas(p, real)
                if not mt:
                    continue
                mt['corr'] = float(np.corrcoef(lam, c['real'])[0, 1])
                acc.setdefault(nombre, []).append((len(c), mt))
            # el jugador solo, como referencia de cuánto aporta encoger
            p = c['plano'].apply(lambda x: _p_al_menos_uno(x, 1.0))
            real = (c['real'] >= 1).astype(float)
            mt = metricas(p, real)
            if mt:
                mt['corr'] = float(np.corrcoef(c['plano'], c['real'])[0, 1])
                acc.setdefault('sin encoger', []).append((len(c), mt))
        cal = {}
        for nombre, vals in acc.items():
            n = sum(v[0] for v in vals)
            cal[nombre] = {k: round(sum(v[0] * v[1][k] for v in vals) / n, 5)
                           for k in ('marginal', 'brier', 'ece', 'corr')}
            cal[nombre]['n'] = n
        for nombre in ('media de la liga', 'cuota × λ equipo', 'sin encoger'):
            if nombre not in cal:
                continue
            t = cal[nombre]
            print('%-24s %10.5f %10.5f %10.5f %8.3f'
                  % (nombre, t['marginal'], t['brier'], t['ece'], t['corr']))
        print()
        # y la misma tabla en posición gruesa, para el roster de temporada
        por_liga_g = {c: cuotas(d, obj, gruesa=True) for c, d in marcos.items()}
        tabla_g = {}
        print('cuota en posición gruesa (la del roster de temporada):')
        for p in sorted(set().union(*[set(v) for v in por_liga_g.values()])):
            vals = [por_liga_g[c][p] for c in sorted(marcos) if p in por_liga_g[c]]
            if len(vals) < 2:
                continue
            tabla_g[p] = round(float(np.mean(vals)), 5)
            print('   %-4s %s   media %.4f' % (
                p, ' '.join('%8.4f' % v for v in vals), np.mean(vals)))
        print()
        doc['cuotas'][obj] = tabla
        doc['cuotas_gruesas'] = doc.get('cuotas_gruesas') or {}
        doc['cuotas_gruesas'][obj] = tabla_g
        doc['calibracion'][obj] = cal
        informe[obj] = {'detalle': detalle,
                        'dispersion_relativa_media': round(disp_media, 4),
                        'calibracion': cal}

    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    with open(INFORME, 'w', encoding='utf-8') as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
    print('escritos %s y %s' % (SALIDA, INFORME))
    return 0


if __name__ == '__main__':
    sys.exit(main())
