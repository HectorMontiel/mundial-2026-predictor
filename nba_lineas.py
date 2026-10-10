# -*- coding: utf-8 -*-
"""
v354 — NBA: HÁNDICAP Y PUNTOS CON LAS LÍNEAS QUE PUBLICA PLAYDOIT.

El usuario: «quiero ganador y más/menos puntos de la NBA; quizá no al 80 %,
empecemos con 75 % y lo vamos subiendo, con la lógica del fútbol: contra la
casa, evaluando el mercado».

QUÉ PUBLICA PLAYDOIT (tableros del 9-oct; antes no se leían: la v354 arregla
el emparejador, que no casaba «Detroit Pistons» con «DET Pistons»): ganador;
hándicap con escalera hasta ±13 puntos de la principal (cuota mínima
~1,17-1,25); totales con escalera hasta ±9-10 (cuota mínima ~1,37-1,59);
puntos por equipo, sólo la línea principal.

LO MEDIDO (`_v354_nba_lineas.py`, réplica 2010-2025 con el cierre de la
casa; `nba_lineas.json`). Lo que acierta una línea alternativa depende de lo
lejos que esté de la principal (k puntos), y casi nada de lo demás:

    k (puntos)          8,5    10,5    12,5     elegir 2010-16 / juzgar 2017-25
    no favorito + k     78/76   83/80   86/84
    favorito  − s + k   76/74   80/78   85/82
    más / menos (total) 69/67   73/72   77/75

El modelo de la NBA casi no suma (de acuerdo con la apuesta: +0 pts en 2010-
16, +1-2 en 2017-25), lo mismo que la v330 midió para el ganador
(`concordancia.PESO_MODELO_NBA` = 0,10): el número es el de la casa, como en
el tenis.

LA REGLA (lo que pidió el usuario: empezar en 75 %). Se mete la línea con la
MEJOR cuota cuya probabilidad medida sea ≥ 75 % y la cuota ≥ 1,15: en el
hándicap la escalera de Playdoit llega; en los totales no (se quedan en
~70 %: se enseñan, no se meten). La Capa 1 lleva la de ≥ 84 % (~85 % como la
del fútbol).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger('nba_lineas')

FICHERO = 'nba_lineas.json'
META_METER = 0.75
CUOTA_MIN = 1.15
META_CAPA1 = 0.84
# LA PRETEMPORADA (ESPN, `_v354_nba_espn.py`: 2021-2026, ~520 partidos con
# su cuota; `nba_lineas.json` → 'pretemporada'). La casa sobrevalora al
# favorito (juegan poco los titulares): lo que promete 78-85 % acierta 67 %, y
# el ganador con la regla de la temporada (casa ≥ 78 %) da 73,7 % (38). Pero el
# hándicap del NO FAVORITO se porta igual que en la temporada regular:
#
#                     pretemporada   temporada 2017-25
#     no favorito +8,5    76,9 %          75,8 %
#     no favorito +10,5   80,5 %          80,2 %
#     favorito a 8,5      71,3 %          73,5 %       (por eso éste no)
#
# Así que en pretemporada sólo se mete el hándicap del no favorito.
PRETEMPORADA_TIPOS = ('no_favorito',)
CUOTA_MIN_CAPA1 = 1.10
_CACHE: Dict = {}
_RE_HCP = re.compile(r'^(.*?)\s*\(([+\-−]?\d+(?:[.,]\d+)?)\)\s*$')


def tablas() -> Dict:
    try:
        mt = os.path.getmtime(FICHERO)
    except OSError:
        return {}
    if _CACHE.get('mt') != mt:
        try:
            _CACHE.update(mt=mt, doc=json.load(open(FICHERO, encoding='utf-8')))
        except Exception as e:
            logger.debug('[nba_lineas] %s', e)
            return {}
    return (_CACHE.get('doc') or {}).get('tablas') or {}


def prob(tipo: str, k: float) -> Optional[float]:
    """Lo que acierta la línea a k puntos de la principal (interpolado)."""
    t = tablas().get(tipo) or {}
    if not t:
        return None
    pts = sorted((float(a), float(b)) for a, b in t.items())
    if k <= pts[0][0]:
        # por debajo de 0,5 se va hacia el 50 % (la principal)
        x0, y0 = pts[0]
        return max(0.0, y0 - (x0 - k) * 0.035)
    if k >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= k <= x1:
            return y0 + (y1 - y0) * (k - x0) / (x1 - x0)
    return None


def _apodo(nombre) -> Optional[str]:
    try:
        import cuotas_multi as cm
        return cm.apodo_nba(nombre)
    except Exception:
        return None


def del_tablero(det: Dict, home: str, away: str, apodo=None) -> Optional[Dict]:
    """El tablero de Playdoit (`cuotas_multi.mercados_playdoit`) en la forma
    que usa la app: las escaleras de hándicap y totales con la línea principal
    de cada una. Con NUESTROS nombres de equipo. None si no hay nada."""
    if not det:
        return None
    _apodo_ = apodo or _apodo
    ah, aa = _apodo_(home), _apodo_(away)
    hcp: Dict[str, Dict[float, float]] = {home: {}, away: {}}
    tot: Dict[str, Dict[float, float]] = {'mas': {}, 'menos': {}}
    for m in det.get('mercados') or []:
        nombre = str(m.get('nombre') or '')
        if nombre.startswith('Hándicap'):
            for s in m.get('selecciones') or []:
                mm = _RE_HCP.match(str(s.get('nombre') or ''))
                if not mm or not s.get('cuota'):
                    continue
                eq = _apodo_(mm.group(1))
                lin = float(mm.group(2).replace(',', '.').replace('−', '-'))
                if eq == ah:
                    hcp[home][lin] = float(s['cuota'])
                elif eq == aa:
                    hcp[away][lin] = float(s['cuota'])
        elif nombre.startswith('Totales'):
            for s in m.get('selecciones') or []:
                t = str(s.get('nombre') or '')
                mm = re.search(r'(\d+(?:[.,]\d+)?)', t)
                if not mm or not s.get('cuota'):
                    continue
                lin = float(mm.group(1).replace(',', '.'))
                if t.startswith('Más'):
                    tot['mas'][lin] = float(s['cuota'])
                elif t.startswith('Menos'):
                    tot['menos'][lin] = float(s['cuota'])
    out = {}
    # la principal: la pareja más pareja (local h, visitante −h)
    mejor = None
    for h, c1 in hcp[home].items():
        c2 = hcp[away].get(-h)
        if c2 and (mejor is None or abs(c1 - c2) < mejor[0]):
            mejor = (abs(c1 - c2), h)
    if mejor is not None:
        out['handicap'] = {'principal_local': mejor[1],
                           'local': {'%g' % k: v for k, v in hcp[home].items()},
                           'visita': {'%g' % k: v for k, v in hcp[away].items()}}
    mejor = None
    for lin, c1 in tot['mas'].items():
        c2 = tot['menos'].get(lin)
        if c2 and (mejor is None or abs(c1 - c2) < mejor[0]):
            mejor = (abs(c1 - c2), lin)
    if mejor is not None:
        out['totales'] = {'principal': mejor[1],
                          'mas': {'%g' % k: v for k, v in tot['mas'].items()},
                          'menos': {'%g' % k: v for k, v in tot['menos'].items()}}
    return out or None


def candidatas(pick: Dict, clave: str = 'nba_playdoit', fprob=None) -> List[Dict]:
    """Las líneas del tablero de Playdoit con su probabilidad medida:
    [{'apuesta', 'mercado', 'bloque', 'linea', 'prob', 'cuota', 'k', 'tipo'}].
    Nunca lanza."""
    out: List[Dict] = []
    try:
        fprob = fprob or prob
        tab = ((pick or {}).get('implicitas') or {}).get(clave) or {}
        par = str(pick.get('partido') or '')
        if ' vs ' not in par or not tab:
            return []
        home, away = (x.strip() for x in par.split(' vs ', 1))
        h = tab.get('handicap') or {}
        if h:
            h0_local = float(h['principal_local'])
            for lado, equipo, h0 in (('local', home, h0_local),
                                     ('visita', away, -h0_local)):
                tipo = 'favorito' if h0 < 0 else 'no_favorito'
                for clave, cuota in (h.get(lado) or {}).items():
                    lin = float(clave)
                    k = lin - h0
                    if k <= 0:
                        continue
                    p = fprob(tipo, k)
                    if p is None:
                        continue
                    out.append({'apuesta': 'Handicap: %s %+g' % (equipo, lin),
                                'mercado': 'Handicap', 'bloque': 'handicap',
                                'etiqueta': 'Hándicap', 'linea': lin,
                                'prob': round(p, 4), 'cuota': float(cuota),
                                'k': round(k, 1), 'tipo': tipo})
        t = tab.get('totales') or {}
        if t:
            t0 = float(t['principal'])
            for lado, rot in (('mas', 'Más de'), ('menos', 'Menos de')):
                for clave, cuota in (t.get(lado) or {}).items():
                    lin = float(clave)
                    k = (t0 - lin) if lado == 'mas' else (lin - t0)
                    if k <= 0:
                        continue
                    p = fprob(lado, k)
                    if p is None:
                        continue
                    out.append({'apuesta': 'Puntos: %s %g' % (rot, lin),
                                'mercado': 'Puntos', 'bloque': 'totales',
                                'etiqueta': 'Puntos', 'linea': lin,
                                'prob': round(p, 4), 'cuota': float(cuota),
                                'k': round(k, 1), 'tipo': lado})
    except Exception as e:
        logger.debug('[nba_lineas] candidatas de %s: %s', (pick or {}).get('partido'), e)
    return out


def elegidas(pick: Dict, meta: float = META_METER,
             cuota_min: float = CUOTA_MIN, clave: str = 'nba_playdoit',
             fprob=None) -> List[Dict]:
    """Por cada lado (local, visita, más, menos), la línea de MEJOR cuota que
    llega a la meta; y si ningún lado llega en un mercado, su mejor línea como
    informativa (`informativa=True`). Una por mercado y lado."""
    cands = candidatas(pick, clave, fprob)
    out = []
    for mercado in ('Handicap', 'Puntos'):
        grupo = [c for c in cands if c['mercado'] == mercado]
        if not grupo:
            continue
        lados = {}
        for c in grupo:
            lado = c['apuesta'].rsplit(' ', 1)[0]      # «Handicap: Equipo» / «Puntos: Más de»
            lados.setdefault(lado, []).append(c)
        buenas = []
        for lado, cs in lados.items():
            ok = [c for c in cs if c['prob'] >= meta and c['cuota'] >= cuota_min]
            if ok:
                buenas.append(max(ok, key=lambda c: c['cuota']))
        if buenas:
            out += buenas
        else:
            out.append(dict(max(grupo, key=lambda c: c['prob']), informativa=True))
    return out
