#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v162 — CÓRNERS, TARJETAS Y REMATES DONDE NO HAY NI UN DATO, Y CUÁNTO VALEN.

Para qué
--------
`stats_espn` cubre casi todas las competiciones con datos REALES. Este módulo
es el respaldo para el resto: las que ESPN no publica, las que no tienen
partidos jugados suficientes, y los partidos sueltos que no casaron. Se pidió
que **ninguna liga se quede sin la sección**, aunque sea con una estimación
marcada — y eso es lo que hace.

Lo que devuelve va SIEMPRE con `origen: 'estimado'`. La interfaz lo pinta con
su etiqueta y no lo mezcla con lo observado.

CÓMO SE ESTIMA, Y QUÉ SE PROBÓ ANTES
-------------------------------------
La pregunta se contestó con **validación dejando una liga fuera**: se ajusta
con las 19 competiciones que sí tienen datos y se predice la vigésima como si
no tuviera ninguno, que es exactamente la situación de producción. Medirlo
dentro de la misma liga habría sido trampa.

Sobre 52.648 equipos-partido del tramo de juicio, error de calibración contra
la frecuencia real y correlación con el resultado:

    CÓRNERS por equipo                        error      corr
      con datos reales (el techo) .........  0,0076     0,257
      media de liga predicha de sus goles .  0,0247     0,160   ← lo adoptado
      media global de las otras ligas .....  0,0264     0,160
      predicha × ataque, normalizada ......  0,0326     0,234
      predicha × ataque, sin normalizar ...  0,0410     0,250

    TARJETAS por equipo                       error      corr
      con datos reales (el techo) .........  0,0123     0,150
      media de liga predicha de sus goles .  0,0539     0,100   ← lo adoptado
      media global de las otras ligas .....  0,0549     0,100
      predicha × ataque, sin normalizar ...  0,0556    −0,080
      predicha × ataque, normalizada ......  0,0578    −0,032

DOS DECISIONES QUE SALEN DE AHÍ, Y NO DE UNA PREFERENCIA
---------------------------------------------------------
**1. No se modula por el ataque del equipo, aunque suba la correlación.**
En córners, modular por los goles móviles del equipo lleva la correlación de
0,160 a 0,234 —casi el techo de 0,257— pero empeora la calibración de 0,0247 a
0,0326. En esta aplicación manda la calibración: la probabilidad que se enseña
tiene que valer lo que dice, y el precedente está en la §10.7-10.8 de la
bitácora. Se deja escrito para no volver a probarlo sin motivo, y para que
quien decida cambiarlo sepa exactamente qué está comprando y qué está pagando.

**2. En tarjetas, modular es peor que no hacer nada, y con signo negativo.**
La modulación por ataque da correlación **−0,080**: un equipo que ataca más se
lleva MENOS tarjetas, así que el modulador empuja justo al revés. Invertirlo
tampoco arregla nada (0,0563 y corr 0,086). O sea que los goles no sirven para
repartir tarjetas entre equipos, sólo para situar el nivel de la competición.

QUÉ SÍ APORTAN LOS GOLES
------------------------
El nivel de la liga. Medido entre las 20 competiciones con datos:

    media de córners  ~ media de goles :  correlación +0,428
    media de tarjetas ~ media de goles :  correlación −0,412

y el rango entre ligas es grande —córners de 8,70 a 10,59; tarjetas de 3,17 a
5,44— así que acertar el nivel importa. La regresión sobre los goles mejora
sobre la media global en las dos (0,0247 contra 0,0264 y 0,0539 contra 0,0549):
poco, pero en la dirección correcta y en las 20 ligas.

v163 — REMATES, MEDIDOS IGUAL Y CON EL MISMO VEREDICTO
-------------------------------------------------------
El tercer mercado entró por la misma puerta, con validación dejando una liga
fuera sobre 18 competiciones (`_v163_remates_estimados.py`):

    REMATES TOTALES por equipo             marginal     ECE     corr
      con datos reales (el techo) .......   0,0131   0,0321    0,431
      media de liga predicha de sus goles   0,0281   0,0302    0,235  ← adoptado
      media global de las otras ligas ...   0,0401   0,0405    0,235
      predicha × ataque, normalizada ....   0,0481   0,1516    0,258

    REMATES A PUERTA por equipo
      con datos reales (el techo) .......   0,0128   0,0279    0,334
      media de liga predicha de sus goles   0,0168   0,0211    0,171  ← adoptado
      media global de las otras ligas ...   0,0376   0,0390    0,171
      predicha × ataque, normalizada ....   0,0376   0,1101    0,239

Los dos quedan por debajo del umbral de 0,05, así que la estimación de remates
se enseña con el aviso suave —a diferencia de la de tarjetas, que va a 0,0539
y lleva el fuerte. Y la modulación por ataque vuelve a perder, aquí por más
distancia que en ningún otro mercado: multiplica el ECE por cinco.

Los goles predicen el nivel de remates de una liga MEJOR que el de córners o
tarjetas: correlación +0,666 en remates totales y **+0,878** a puerta, contra
+0,428 y −0,412. Tiene sentido — los remates son el paso inmediatamente
anterior al gol, y córners y tarjetas están dos pasos más lejos.

LO QUE ESTO NO PUEDE HACER, DICHO CLARO
----------------------------------------
Sin un solo córner observado de una competición, **no hay forma de saber qué
equipo saca más**. Lo que se enseña es el nivel de la liga repartido por bando,
igual para todos sus partidos. Eso no es un modelo del partido: es el mejor
número disponible, y por eso va marcado. Con 0,0539 de error, la estimación de
tarjetas está por encima del umbral de 0,05 que se fijó como aceptable, y la
interfaz lo dice en vez de disimularlo.
"""
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('stats_estimadas')

ARCHIVO = 'calibracion_stats_liga.json'
# Por encima de este error de calibración, la estimación se enseña con un aviso
# más fuerte. Es el umbral que se fijó al pedir esto.
UMBRAL_ACEPTABLE = 0.05
_CACHE: Optional[Dict] = None


# ---------------------------------------------------------------------------
# el ajuste (se regenera con `python stats_estimadas.py --ajustar`)
# ---------------------------------------------------------------------------
def ajustar(claves: Optional[List[str]] = None) -> Dict:
    """
    Ajusta, con las competiciones que SÍ tienen datos observados, la relación
    entre el nivel de goles de una liga y su nivel de córners y tarjetas.

    Se guarda el resultado en `calibracion_stats_liga.json`: dos rectas, las
    proporciones local/visitante y las dispersiones medianas. Todo lo que hace
    falta para estimar una liga de la que sólo se conocen los goles.
    """
    import rendimiento_equipos as rq
    from config import LEAGUES

    claves = claves or list(LEAGUES)
    perfiles = {}
    for c in claves:
        try:
            disp = rq.stats_disponibles(c)
        except Exception:
            continue
        if not (disp.get('corners') or disp.get('tarjetas')
                or disp.get('remates')):
            continue
        d = rq._historico(c)
        if d is None or getattr(d, 'empty', True) or len(d) < 400:
            continue
        p = {'n': int(len(d))}
        gh = pd.to_numeric(d.get('home_goals'), errors='coerce')
        ga = pd.to_numeric(d.get('away_goals'), errors='coerce')
        p['goles'] = float((gh + ga).mean())
        if disp.get('corners'):
            ch = pd.to_numeric(d['home_corners'], errors='coerce')
            ca = pd.to_numeric(d['away_corners'], errors='coerce')
            p['ck'] = float((ch + ca).mean())
            p['ck_prop_h'] = float(ch.mean() / (ch.mean() + ca.mean()))
            s = pd.concat([ch, ca]).dropna()
            p['ck_disp'] = float(max(s.var() / s.mean(), 1.0))
        # v163 — remates, en sus dos mercados. La columna de totales es a
        # puerta MÁS fuera, igual que la lee `rendimiento_equipos._remates_de`;
        # si falta cualquiera de las dos, la fila no suma un total a medias.
        #
        # ESTE BLOQUE FILTRA POR `_solo_reales` Y LOS DE ARRIBA NO.
        # No es un descuido: en una competición cubierta por ESPN desde 2021
        # con histórico desde 2018, la columna está MEZCLADA, y promediar las
        # dos mitades da un nivel que no es el de la liga. Medido: la razón
        # varianza/media de los remates por equipo sale 3,4 mezclando y 2,0
        # limpia. Los bloques de córners y tarjetas se dejan como estaban
        # porque su calibración ya está medida y cerrada con ese
        # comportamiento (§10-§11); cambiarlos aquí movería números validados
        # sin volver a medirlos, que es justo lo que este proyecto no hace.
        d_rem = rq._solo_reales(d, 'shots_on')
        if disp.get('remates') and d_rem is not None and len(d_rem) >= 400:
            for obj, cols in (('rem', ('shots_on', 'shots_off')),
                              ('rem_on', ('shots_on',))):
                if not all('home_%s' % c in d_rem.columns for c in cols):
                    continue
                rh = sum(pd.to_numeric(d_rem['home_%s' % c], errors='coerce')
                         for c in cols)
                ra = sum(pd.to_numeric(d_rem['away_%s' % c], errors='coerce')
                         for c in cols)
                if not rh.notna().any():
                    continue
                p[obj] = float((rh + ra).mean())
                p['%s_prop_h' % obj] = float(rh.mean()
                                             / (rh.mean() + ra.mean()))
                s = pd.concat([rh, ra]).dropna()
                p['%s_disp' % obj] = float(max(s.var() / s.mean(), 1.0))
        if disp.get('tarjetas') and 'home_red' in d.columns:
            th = (pd.to_numeric(d['home_yellow'], errors='coerce')
                  + pd.to_numeric(d['home_red'], errors='coerce'))
            ta = (pd.to_numeric(d['away_yellow'], errors='coerce')
                  + pd.to_numeric(d['away_red'], errors='coerce'))
            p['tj'] = float((th + ta).mean())
            p['tj_prop_h'] = float(th.mean() / (th.mean() + ta.mean()))
            s = pd.concat([th, ta]).dropna()
            p['tj_disp'] = float(max(s.var() / s.mean(), 1.0))
        perfiles[c] = p

    doc = {'generado': pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ'),
           'ligas_ajuste': sorted(perfiles), 'rectas': {}, 'medianas': {}}
    for obj in ('ck', 'tj', 'rem', 'rem_on'):
        con = {c: p for c, p in perfiles.items() if obj in p}
        if len(con) < 5:
            continue
        x = np.array([[1.0, p['goles']] for p in con.values()])
        y = np.array([p[obj] for p in con.values()])
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ coef
        doc['rectas'][obj] = {
            'intercepto': float(coef[0]), 'pendiente': float(coef[1]),
            'n_ligas': len(con),
            'corr_goles': float(np.corrcoef(x[:, 1], y)[0, 1]),
            'media_global': float(y.mean()),
            'sd_entre_ligas': float(y.std()),
            'error_ajuste': float(np.mean(np.abs(pred - y))),
        }
        doc['medianas'][obj] = {
            'prop_h': float(np.median([p['%s_prop_h' % obj] for p in con.values()])),
            'disp': float(np.median([p['%s_disp' % obj] for p in con.values()])),
        }
    # el error de calibración medido dejando una liga fuera (v162); no se
    # recalcula aquí, se anota para que la interfaz sepa qué está enseñando
    doc['calibracion_estimada'] = {'ck': 0.0247, 'tj': 0.0539,
                                   'rem': 0.0281, 'rem_on': 0.0168}
    doc['calibracion_observada'] = {'ck': 0.0076, 'tj': 0.0123,
                                    'rem': 0.0131, 'rem_on': 0.0128}
    doc['perfiles'] = perfiles
    return doc


def cargar() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(ARCHIVO, encoding='utf-8') as f:
            _CACHE = json.load(f) or {}
    except Exception as e:
        logger.debug('[stats_estimadas] sin %s: %s', ARCHIVO, e)
        _CACHE = {}
    return _CACHE


# ---------------------------------------------------------------------------
# la estimación
# ---------------------------------------------------------------------------
def _media_goles(clave: str) -> Optional[float]:
    try:
        import rendimiento_equipos as rq
        d = rq._historico(clave)
        if d is None or getattr(d, 'empty', True) or len(d) < 100:
            return None
        gh = pd.to_numeric(d.get('home_goals'), errors='coerce')
        ga = pd.to_numeric(d.get('away_goals'), errors='coerce')
        v = float((gh + ga).mean())
        return v if 0.5 < v < 7.0 else None
    except Exception as e:
        logger.debug('[stats_estimadas] goles de %s: %s', clave, e)
        return None


def estimar(clave: str, objetivo: str) -> Optional[Dict]:
    """
    Lo estimado para una competición sin datos observados.

    `objetivo` es 'ck' (córners), 'tj' (tarjetas), 'rem' (remates totales) o
    'rem_on' (remates a puerta).

    Devuelve las dos lambdas por bando, la dispersión y de dónde sale cada
    cosa. `None` si ni siquiera hay goles con los que situar el nivel — sin
    eso no queda nada honesto que enseñar.
    """
    if objetivo not in ('ck', 'tj', 'rem', 'rem_on'):
        return None
    doc = cargar()
    recta = (doc.get('rectas') or {}).get(objetivo)
    med = (doc.get('medianas') or {}).get(objetivo)
    if not recta or not med:
        return None
    goles = _media_goles(clave)
    if goles is None:
        return None
    total = float(recta['intercepto'] + recta['pendiente'] * goles)
    # El ajuste es una recta sobre 20 puntos: fuera del rango observado deja de
    # ser una interpolación y pasa a ser una extrapolación. Se acota a ±2
    # desviaciones del nivel medio entre ligas, que es donde hay evidencia.
    lo = recta['media_global'] - 2.0 * recta['sd_entre_ligas']
    hi = recta['media_global'] + 2.0 * recta['sd_entre_ligas']
    total = float(np.clip(total, lo, hi))
    prop = float(med['prop_h'])
    err = float((doc.get('calibracion_estimada') or {}).get(objetivo, 0.05))
    return {
        'lambda_home': round(total * prop, 3),
        'lambda_away': round(total * (1.0 - prop), 3),
        'lambda_total': round(total, 3),
        'dispersion': round(float(med['disp']), 4),
        'dispersion_total': round(float(med['disp']), 4),
        'origen': 'estimado',
        'clave_liga': clave,
        'error_calibracion': err,
        'aceptable': bool(err <= UMBRAL_ACEPTABLE),
        'base': 'nivel de la competición derivado de sus goles (%.2f)' % goles,
    }


# ---------------------------------------------------------------------------
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ajustar', action='store_true',
                    help='recalcula el ajuste y lo guarda')
    ap.add_argument('--probar', default=None, help='estima esta competición')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    if args.ajustar:
        doc = ajustar()
        try:
            import io_atomico
            io_atomico.escribir_json(ARCHIVO, doc, indent=1)
        except Exception:
            with open(ARCHIVO, 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
        print('ajustado con %d competiciones' % len(doc.get('ligas_ajuste') or []))
        for obj, r in (doc.get('rectas') or {}).items():
            print('  %s: nivel = %.3f + %.3f · goles   (corr %+.3f, %d ligas, '
                  'error de ajuste %.3f)'
                  % (obj, r['intercepto'], r['pendiente'], r['corr_goles'],
                     r['n_ligas'], r['error_ajuste']))
            m = doc['medianas'][obj]
            print('       reparto local %.3f · dispersión %.3f'
                  % (m['prop_h'], m['disp']))
        return 0

    if args.probar:
        for obj in ('ck', 'tj', 'rem', 'rem_on'):
            print(obj, '->', json.dumps(estimar(args.probar, obj),
                                        ensure_ascii=False))
        return 0

    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
