# -*- coding: utf-8 -*-
"""
v303 — LA RAMA DEL BARRIDO PARA LAS LIGAS QUE SÓLO TIENEN RESULTADOS.

Hoy: Liga MX Femenil (FotMob, ver `historico_fotmob`). Mañana, cualquier liga
que se añada a `historico_fotmob.LIGAS` y cuyo `motor_goles` pase su
validación: la rama la toma sola.

Cada partido próximo de la liga sale como pronóstico CON LA MISMA FORMA que
los del fútbol de clubes (1X2, escalera de goles, goles de cada equipo,
lambdas), así que la tarjeta, el filtro de día, la razón corta y la Escalera
lo tratan igual. El precio sale del tablero de la casa con la misma función
que usan los clubes.

Sólo publica ligas cuyo motor le ganó a la línea base fuera de muestra
(`motor_goles.json`). Una liga que no pase no sale, y se dice como
incidencia en vez de enseñar un número sin respaldo.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

DIAS = 3
# Peso del modelo al mezclar con el mercado cuando hay precio: el mismo w=0,25
# con el que se midió la ventaja del fútbol de clubes (ver `alpha_finder`).
MODELO_W = 0.25


# Cómo se llama cada liga en el tablero de las casas mexicanas (Flashscore).
# La CATEGORÍA va en el nombre de la liga, y es lo que impide emparejar con el
# partido varonil de los mismos dos clubes: medido el 2026-09-23, buscar
# «Pachuca vs Santos Laguna» sin ella devolvía el precio del varonil
# (Pinnacle 2,20) para un partido en el que el motor femenil da 81 %.
LIGA_TABLERO = {'mex_femenil': ('mexico', 'women'),
                'champions_femenil': ('champions league women',),
                'fem_inglaterra': ('england', 'women'),
                'fem_espana': ('spain', 'women'),
                'fem_alemania': ('germany', 'women'),
                'fem_francia': ('france', 'women'),
                'fem_italia': ('italy', 'women')}


def _sin_sufijo(n: str) -> str:
    import re
    return re.sub(r'\s+(W|F|\(W\)|\(F\))$', '', str(n or '')).strip()


def implicitas_del_tablero(clave: str, home: str, away: str,
                           inicio=None) -> Dict:
    """Mejor precio de cada selección en el tablero de las casas mexicanas,
    con el formato de `mercado_implicito`. `{}` si no está."""
    import barrido_capa1 as bc
    import mercado_implicito as mi
    import name_mapper as nm
    claves = LIGA_TABLERO.get(clave)
    if not claves:
        return {}
    cand = [v for v in bc._tablero()
            if str(v.get('deporte')) == 'futbol'
            and all(c in str(v.get('liga') or '').lower() for c in claves)]
    if not cand:
        return {}
    por_nombre = {}
    for v in cand:
        por_nombre.setdefault(_sin_sufijo(v.get('home')), []).append(v)
    ch = nm.mapear(home, list(por_nombre), contexto='sin_motor')
    if not ch:
        return {}
    # y la MISMA FECHA: dos clubes pueden cruzarse en liga y en copa en la
    # misma semana, y el tablero no distingue más que por la competición
    t0 = None
    try:
        import horario as _h
        _d = _h._a_utc(inicio)
        t0 = _d.timestamp() if _d else None
    except Exception:
        t0 = None

    def _misma_fecha(x):
        if t0 is None:
            return True
        try:
            return abs(float(x.get('inicio') or 0) - t0) < 36 * 3600
        except (TypeError, ValueError):
            return False
    v = next((x for x in por_nombre[ch]
              if _misma_fecha(x)
              and nm.mapear(away, [_sin_sufijo(x.get('away'))],
                            contexto='sin_motor')), None)
    if not v:
        return {}
    mejor = {}
    goles = {}
    doble = {}
    for casa, mks in (v.get('casas') or {}).items():
        x = (mks or {}).get('HOME_DRAW_AWAY') or {}
        for k in ('home', 'draw', 'away'):
            c = x.get(k)
            if c and c > (mejor.get(k) or (0, ''))[0]:
                mejor[k] = (float(c), casa)
        dc = (mks or {}).get('DOUBLE_CHANCE') or {}
        for k, dst in (('homeOrDraw', '1X'), ('awayOrDraw', 'X2'),
                       ('noDraw', '12')):
            c = dc.get(k)
            if c and c > doble.get(dst, 0):
                doble[dst] = float(c)
        for ln in ((mks or {}).get('OVER_UNDER') or {}).get('lineas') or []:
            L = ln.get('linea')
            if L is None or float(L) % 1 != 0.5:
                continue          # sólo medias líneas: las demás tienen push
            k = mi.clave_linea(L)
            g = goles.setdefault(k, {'mas': 0.0, 'menos': 0.0})
            g['mas'] = max(g['mas'], float(ln.get('over') or 0))
            g['menos'] = max(g['menos'], float(ln.get('under') or 0))
    fuera = {}
    if len(mejor) == 3:
        cu = {k: c for k, (c, _) in mejor.items()}
        fuera['1x2_cuotas'] = {k: round(c, 3) for k, c in cu.items()}
        just = mi._devig(cu)
        if len(just) == 3:
            fuera['1x2'] = {k: round(p, 4) for k, p in just.items()}
        fuera['casa'] = mejor[max(just, key=just.get)][1] if just else ''
    if doble:
        fuera['doble_cuotas'] = doble
    gl = {}
    for k, g in goles.items():
        if g['mas'] > 1 and g['menos'] > 1:
            j = mi._devig({'mas': g['mas'], 'menos': g['menos']})
            if len(j) == 2:
                gl[k] = {'p': round(j['mas'], 4), 'mas': g['mas'],
                         'menos': g['menos']}
    if gl:
        fuera['goles'] = gl
    return fuera


def _pronostico(clave: str, nombre: str, fx: Dict, m: Dict) -> Dict:
    import motor_goles as mg
    lam = mg.lambdas(m, fx['home'], fx['away'])
    if not lam:
        return {}
    p = mg.probabilidades(*lam)
    h, a = fx['home'], fx['away']
    board = {'Gana %s' % h: round(p['home'], 3), 'Empate': round(p['draw'], 3),
             'Gana %s' % a: round(p['away'], 3),
             'Más de 2.5': round(p['lineas']['2.5'], 3),
             'Menos de 2.5': round(1 - p['lineas']['2.5'], 3),
             'Ambos marcan: Sí': round(p['btts'], 3),
             'Ambos marcan: No': round(1 - p['btts'], 3)}
    lado, prob = max((('home', p['home']), ('draw', p['draw']),
                      ('away', p['away'])), key=lambda x: x[1])
    apuesta = ('Empate' if lado == 'draw' else
               'Gana %s' % (h if lado == 'home' else a))
    mercados = [{'mercado': ('1X2' if k.startswith(('Gana', 'Empate')) else
                             'Goles' if k.startswith(('Más', 'Menos'))
                             else 'BTTS'),
                 'apuesta': k, 'prob': v, 'cuota': None, 'ev': None,
                 'cuota_justa': round(1 / v, 2) if v > 0 else None,
                 'valor': '🎯'} for k, v in board.items()]
    pron = {'deporte': 'Fútbol', 'liga': nombre, 'clave_liga': clave,
            'partido': '%s vs %s' % (h, a), 'fecha': fx['fecha'],
            'inicio': fx['inicio'], 'mercado': '1X2', 'apuesta': apuesta,
            'prob': round(prob, 3), 'cuota': None, 'ev': None,
            'cuota_justa': round(1 / prob, 2), 'valor': '🎯',
            'mercados': mercados, 'board': board,
            'goles_lineas': p['lineas'],
            'goles_lambda': round(lam[0] + lam[1], 3),
            'goles_equipo': {'local': p['local'], 'visitante': p['visitante']},
            'goles_xg': {'local': round(lam[0], 3),
                         'visitante': round(lam[1], 3)},
            'sin_cuota': True, 'motor': 'motor_goles'}
    # Si en esta liga el motor NO le gana a su base en goles (medido: la
    # Champions femenina), la escalera de goles es la frecuencia histórica de
    # la liga, y los goles por equipo no se publican: no hay nada validado
    # con qué calcularlos.
    v = (mg.estado().get('ligas') or {}).get(clave) or {}
    if not v.get('ok_goles', True):
        base = mg.lineas_base(clave)
        if base:
            pron['goles_lineas'] = base
            board['Más de 2.5'] = round(base['2.5'], 3)
            board['Menos de 2.5'] = round(1 - base['2.5'], 3)
            for mm_ in mercados:
                if mm_['apuesta'] == 'Más de 2.5':
                    mm_['prob'] = board['Más de 2.5']
                elif mm_['apuesta'] == 'Menos de 2.5':
                    mm_['prob'] = board['Menos de 2.5']
        for k in ('goles_equipo', 'goles_xg', 'goles_lambda'):
            pron.pop(k, None)
        pron['goles_de_la_liga'] = True
    try:
        # el tablero de las casas mexicanas, con la categoría exigida por la
        # liga; NO el emparejador general, que cruzaba con el varonil
        imp = implicitas_del_tablero(clave, h, a, fx.get('inicio'))
        if imp:
            pron['implicitas'] = imp
            # EL MISMO ENCOGIMIENTO QUE EL FÚTBOL DE CLUBES (v71/v79): con
            # precio, lo publicado es 0,25 modelo + 0,75 mercado, que es con
            # lo que se midió la ventaja del fútbol (+6,72 %, p5 +0,92 %). Sin
            # esto, la primera prueba daba «Gana Leuven» al 43 % contra la
            # Roma, cuando el mercado dice 20 %, y la tarjeta lo habría
            # vendido como una apuesta de cuota 4,49 con EV +95 %: un error
            # del modelo con disfraz de oportunidad.
            x2 = imp.get('1x2') or {}
            if len(x2) == 3:
                w = MODELO_W
                nuevo = {'home': w * p['home'] + (1 - w) * x2['home'],
                         'draw': w * p['draw'] + (1 - w) * x2['draw'],
                         'away': w * p['away'] + (1 - w) * x2['away']}
                for k, nom in (('home', 'Gana %s' % h), ('draw', 'Empate'),
                               ('away', 'Gana %s' % a)):
                    board[nom] = round(nuevo[k], 3)
                for mm_ in mercados:
                    if mm_['apuesta'] in board and mm_['mercado'] == '1X2':
                        mm_['prob'] = board[mm_['apuesta']]
                        mm_['calibracion'] = {'aplicado': True, 'w': w}
                lado, prob = max(nuevo.items(), key=lambda x: x[1])
                pron['apuesta'] = ('Empate' if lado == 'draw' else
                                   'Gana %s' % (h if lado == 'home' else a))
                pron['prob'] = round(prob, 3)
                pron['cuota_justa'] = round(1 / prob, 2)
                pron['encogido_al_mercado'] = w
            cu = (imp.get('1x2_cuotas') or {}).get(lado)
            if cu:
                pron['cuota'] = cu
                pron['sin_cuota'] = False
                pron['ev'] = round(float(cu) * prob - 1, 4)
    except Exception as e:
        logger.debug('[sin_motor] precio %s: %s', pron['partido'], e)
    try:
        import horario as _h
        _h.anotar(pron)
    except Exception:
        pass
    return pron


def barrer(dias: int = DIAS) -> Dict:
    """La rama. Misma salida que las demás. NUNCA lanza."""
    t0 = time.time()
    salida = {'pronosticos': [], 'no_enlazados': [], 'evaluados': 0,
              'cobertura': {}, 'capa1': [], 'capa2': [], 'incidencias': []}
    try:
        import historico_fotmob as hf
        import motor_goles as mg
        import pandas as pd
    except Exception as e:
        salida['incidencias'].append('⚠️ Ligas sin motor: %s' % e)
        return salida
    ligas = (mg.estado().get('ligas') or {})
    limite = pd.Timestamp.now('UTC').tz_localize(None) + pd.Timedelta(days=dias)
    for clave, (_, nombre) in hf.LIGAS.items():
        v = ligas.get(clave) or {}
        if not v.get('ok'):
            salida['incidencias'].append(
                'ℹ️ %s no sale en Apuestas del Día: su motor no le ganó a la '
                'línea base fuera de muestra.' % nombre)
            continue
        m = mg.modelo(clave)
        if not m:
            continue
        try:
            prox = hf.proximos(clave)
        except Exception as e:
            salida['incidencias'].append('⚠️ %s: calendario no disponible (%s)'
                                         % (nombre, type(e).__name__))
            continue
        n = 0
        for fx in prox:
            try:
                if pd.Timestamp(fx['inicio']) > limite:
                    continue
                p = _pronostico(clave, nombre, fx, m)
                if p:
                    salida['pronosticos'].append(p)
                    n += 1
                else:
                    salida['no_enlazados'].append('%s vs %s'
                                                  % (fx['home'], fx['away']))
            except Exception as e:
                logger.debug('[sin_motor] %s: %s', fx.get('home'), e)
        if n:
            salida['cobertura'][clave] = n
    salida['evaluados'] = len(salida['pronosticos'])
    logger.info('[sin_motor] %d pronósticos en %.1f s',
                len(salida['pronosticos']), time.time() - t0)
    return salida
