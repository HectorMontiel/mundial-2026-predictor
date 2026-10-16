# -*- coding: utf-8 -*-
"""
v359 — NHL: GANADOR, HÁNDICAP Y GOLES CON LAS LÍNEAS QUE PUBLICA PLAYDOIT.

El usuario: «agrega la NHL con todo lo de contra la casa, nuestro método».

QUÉ PUBLICA PLAYDOIT (tableros del 10-oct, 18 partidos): «Ganador (incl.
prórroga y penaltis)», «Hándicap (incl. prórroga y penaltis)» de ±1,5 a ±4,5 y
«Totales (incl. prórroga y penaltis)» de 2,5 a 11,5 goles, más goles por
equipo y por periodo. La línea principal del hándicap es siempre ±1,5 (puck
line), así que —como en la MLB— lo que acierta una línea depende de la
probabilidad del equipo en la casa; la de los goles, de la distancia k a la
línea principal.

LO MEDIDO (`_v359_nhl_medir.py`, `nhl_lineas.json`; 16.300 partidos con el
cierre de la casa: sportsbookreviewsonline 2014-2022 y ESPN 2022-2026). La
casa acierta lo que promete en el ganador, banda a banda. Por lado, la línea
de mejor cuota que llega a la meta:

    meta     elegir 2014-18   juzgar 2019-25      2026     pretemporada
    75 %         80,9 %       80,2 % (p5 79,9)   81,1 %      80,7 %
    78 %         84,0 %       81,8 % (p5 81,5)   82,1 %      82,5 %
    80 %         85,0 %       82,7 % (p5 82,4)   82,9 %      83,5 %
    85 %         90,0 %       88,9 % (p5 88,6)   88,9 %      90,1 %

Se mete con 78 % (cuota ≥ 1,15); Capa 1 con 85 % (cuota ≥ 1,10). Los cuatro
lados (favorito, no favorito, más, menos) quedan en 80-84 % al juzgar.

EL GANADOR: con la casa en 75 % o más acertó 78,4 % (75-80, 283) y 81,8 %
(80+, 110) en 2019-25 → `META_GANADOR` = 75 %, como la NFL (74 %).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger('nhl_lineas')

FICHERO = 'nhl_lineas.json'
META_METER = 0.78
CUOTA_MIN = 1.15
META_CAPA1 = 0.85
CUOTA_MIN_CAPA1 = 1.10
# v375 — el usuario: «más flexibles en NHL, baja a 70 %». Medido con los
# cierres 2014-2026 (15.565 partidos): con la casa al 70-75 % el favorito ganó
# 73,7 % (+5,4 por $100 al cierre) y al 75 %+ 79,3 %. Por debajo de la meta
# de 78 % de las líneas: se sigue con el seguimiento.
META_GANADOR = 0.70
CLAVE = 'nhl_playdoit'
# LA PRETEMPORADA (ESPN 2022-2026, 408 partidos con cuota): con la regla del
# 78 % los cuatro lados aguantan en las dos mitades (2022-23 / 2024-26):
# favorito 84,5 / 78,8 %, no favorito 80,4 / 86,3 %, más 78,8 / 80,9 %,
# menos 87,7 / 82,5 %. El GANADOR no: el favorito de la casa al 75 % o más
# ganó 17 de 25 (68 %).
PRETEMPORADA_TIPOS: tuple = ('favorito', 'no_favorito', 'mas', 'menos')
_CACHE: Dict = {}
_RE_HCP = re.compile(r'^(.*?)\s*\(([+\-−]?\d+(?:[.,]\d+)?)\)\s*$')

# Los 32 equipos: el apodo (como lo escribe Playdoit, «EDM Oilers») → nombre.
EQUIPOS = {
    'ducks': 'Anaheim Ducks', 'bruins': 'Boston Bruins', 'sabres': 'Buffalo Sabres',
    'flames': 'Calgary Flames', 'hurricanes': 'Carolina Hurricanes',
    'blackhawks': 'Chicago Blackhawks', 'avalanche': 'Colorado Avalanche',
    'blue jackets': 'Columbus Blue Jackets', 'stars': 'Dallas Stars',
    'red wings': 'Detroit Red Wings', 'oilers': 'Edmonton Oilers',
    'panthers': 'Florida Panthers', 'kings': 'Los Angeles Kings', 'wild': 'Minnesota Wild',
    'canadiens': 'Montreal Canadiens', 'predators': 'Nashville Predators',
    'devils': 'New Jersey Devils', 'islanders': 'New York Islanders',
    'rangers': 'New York Rangers', 'senators': 'Ottawa Senators',
    'flyers': 'Philadelphia Flyers', 'penguins': 'Pittsburgh Penguins',
    'sharks': 'San Jose Sharks', 'kraken': 'Seattle Kraken', 'blues': 'St. Louis Blues',
    'lightning': 'Tampa Bay Lightning', 'maple leafs': 'Toronto Maple Leafs',
    'mammoth': 'Utah Mammoth', 'canucks': 'Vancouver Canucks',
    'golden knights': 'Vegas Golden Knights', 'capitals': 'Washington Capitals',
    'jets': 'Winnipeg Jets'}
_DOS = {'leafs': 'maple leafs', 'wings': 'red wings', 'jackets': 'blue jackets',
        'knights': 'golden knights'}


def apodo(nombre) -> Optional[str]:
    """«oilers» de «Edmonton Oilers» y de «EDM Oilers»; «maple leafs»…"""
    pal = str(nombre or '').strip().lower().replace('.', ' ').split()
    if not pal:
        return None
    return _DOS.get(pal[-1], pal[-1])


def nombre(n) -> Optional[str]:
    """El nombre completo de un equipo de la NHL; None si no lo es."""
    return EQUIPOS.get(apodo(n) or '')


def _doc() -> Dict:
    try:
        mt = os.path.getmtime(FICHERO)
    except OSError:
        return {}
    if _CACHE.get('mt') != mt:
        try:
            _CACHE.update(mt=mt, doc=json.load(open(FICHERO, encoding='utf-8')))
        except Exception as e:
            logger.debug('[nhl_lineas] %s', e)
            return {}
    return _CACHE.get('doc') or {}


def _interp(pts, x):
    pts = sorted(pts)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def prob_handicap(p_equipo: float, linea: float) -> Optional[float]:
    """Acierto del equipo con la línea `linea` según su probabilidad (sin
    margen) en la casa; interpolado entre bandas, sólo líneas medidas."""
    tab = _doc().get('handicap') or []
    clave = '%+g' % linea
    pts = [(b['p'], b[clave]) for b in tab if b.get(clave) is not None]
    return _interp(pts, p_equipo) if pts else None


def prob_total(lado: str, k: float) -> Optional[float]:
    t = (_doc().get('totales') or {}).get(lado) or {}
    pts = [(float(a), float(b)) for a, b in t.items() if b is not None]
    if not pts or k > max(a for a, _ in pts) + 1e-9:
        return None
    return _interp(pts, k)


def del_tablero(det: Dict, home: str, away: str) -> Optional[Dict]:
    """Ganador (sin margen), hándicap y goles totales de Playdoit, con NUESTROS
    nombres. None si no hay nada."""
    if not det:
        return None
    ah, aa = apodo(home), apodo(away)
    hcp: Dict[str, Dict[float, float]] = {home: {}, away: {}}
    tot: Dict[str, Dict[float, float]] = {'mas': {}, 'menos': {}}
    ml: Dict[str, float] = {}
    for m in det.get('mercados') or []:
        nom = str(m.get('nombre') or '')
        sels = m.get('selecciones') or []
        if nom.startswith('Ganador (incl'):
            for s in sels:
                eq = apodo(s.get('nombre'))
                if s.get('cuota'):
                    if eq == ah:
                        ml[home] = float(s['cuota'])
                    elif eq == aa:
                        ml[away] = float(s['cuota'])
        elif nom.startswith('Hándicap (incl'):
            for s in sels:
                mm = _RE_HCP.match(str(s.get('nombre') or ''))
                if not mm or not s.get('cuota'):
                    continue
                eq = apodo(mm.group(1))
                lin = float(mm.group(2).replace(',', '.').replace('−', '-'))
                if eq == ah:
                    hcp[home][lin] = float(s['cuota'])
                elif eq == aa:
                    hcp[away][lin] = float(s['cuota'])
        elif nom.startswith('Totales (incl'):
            for s in sels:
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
    if home in ml and away in ml:
        s = 1 / ml[home] + 1 / ml[away]
        out['p_local'] = round((1 / ml[home]) / s, 4)
        out['ml'] = {'local': ml[home], 'visita': ml[away]}
    if hcp[home] or hcp[away]:
        out['handicap'] = {'local': {'%g' % k: v for k, v in hcp[home].items()},
                           'visita': {'%g' % k: v for k, v in hcp[away].items()}}
    mejor = None
    for lin, c1 in tot['mas'].items():
        c2 = tot['menos'].get(lin)
        if c2 and (mejor is None or abs(c1 - c2) < mejor[0]):
            mejor = (abs(c1 - c2), lin)
    if mejor is not None and mejor[0] <= 0.6:
        out['totales'] = {'principal': mejor[1],
                          'mas': {'%g' % k: v for k, v in tot['mas'].items()},
                          'menos': {'%g' % k: v for k, v in tot['menos'].items()}}
    return out or None


def _equipos(partido: str):
    if ' vs ' in partido:
        h, a = (x.strip() for x in partido.split(' vs ', 1))
        return h, a
    return None, None


def candidatas(pick: Dict) -> List[Dict]:
    out: List[Dict] = []
    try:
        tab = ((pick or {}).get('implicitas') or {}).get(CLAVE) or {}
        home, away = _equipos(str(pick.get('partido') or ''))
        if not tab or not home:
            return []
        pl = tab.get('p_local')
        h = tab.get('handicap') or {}
        if pl is not None and h:
            for lado, equipo, pe in (('local', home, pl), ('visita', away, 1 - pl)):
                for clave, cuota in (h.get(lado) or {}).items():
                    lin = float(clave)
                    p = prob_handicap(pe, lin)
                    if p is None:
                        continue
                    out.append({'apuesta': 'Handicap: %s %+g' % (equipo, lin),
                                'mercado': 'Handicap', 'bloque': 'handicap',
                                'etiqueta': 'Hándicap', 'linea': lin, 'prob': round(p, 4),
                                'cuota': float(cuota), 'k': lin,
                                'tipo': 'favorito' if pe >= 0.5 else 'no_favorito'})
        t = tab.get('totales') or {}
        if t:
            t0 = float(t['principal'])
            for lado, rot in (('mas', 'Más de'), ('menos', 'Menos de')):
                for clave, cuota in (t.get(lado) or {}).items():
                    lin = float(clave)
                    if lin != int(lin) + 0.5:
                        continue
                    k = (t0 - lin) if lado == 'mas' else (lin - t0)
                    if k <= 0:
                        continue
                    p = prob_total(lado, k)
                    if p is None:
                        continue
                    out.append({'apuesta': 'Goles: %s %g' % (rot, lin),
                                'mercado': 'Goles', 'bloque': 'goles',
                                'etiqueta': 'Goles', 'linea': lin, 'prob': round(p, 4),
                                'cuota': float(cuota), 'k': round(k, 1), 'tipo': lado})
    except Exception as e:
        logger.debug('[nhl_lineas] candidatas de %s: %s', (pick or {}).get('partido'), e)
    return out


def elegidas(pick: Dict, meta: float = META_METER, cuota_min: float = CUOTA_MIN) -> List[Dict]:
    """Por lado, la de mejor cuota que llega a la meta; si ningún lado de un
    mercado llega, su más probable como informativa."""
    cands = candidatas(pick)
    out = []
    for mercado in ('Handicap', 'Goles'):
        grupo = [c for c in cands if c['mercado'] == mercado]
        if not grupo:
            continue
        lados: Dict[str, List[Dict]] = {}
        for c in grupo:
            lados.setdefault(c['apuesta'].rsplit(' ', 1)[0], []).append(c)
        buenas = []
        for cs in lados.values():
            ok = [c for c in cs if c['prob'] >= meta and c['cuota'] >= cuota_min]
            if ok:
                buenas.append(max(ok, key=lambda c: c['cuota']))
        out += buenas or [dict(max(grupo, key=lambda c: c['prob']), informativa=True)]
    return out
