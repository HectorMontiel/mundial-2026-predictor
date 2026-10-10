# -*- coding: utf-8 -*-
"""
v355 — MLB (y KBO): HÁNDICAP Y TOTALES CON LAS ESCALERAS DE PLAYDOIT.

El usuario: «lo mismo que la NBA para la MLB y la KBO: ganador, más/menos,
hándicap… quiero ver Capa 1 y Apuestas del día de este deporte».

LO MEDIDO (`_v355_mlb_medir.py`, 28.005 partidos 2010-2021 con el cierre de la
casa; `mlb_lineas.json`; elige 2010-16, juzga 2017-21):

  · GANADOR: la casa acierta lo que promete, y en la MLB casi no hay favoritos
    fuertes (≥ 70 %: ~71 por temporada, aciertan 71-72 %). No hay ganador al
    75-80 %: se queda con su regla de siempre (no se mete).
  · HÁNDICAP (run line): lo que acierta el equipo X con su línea h depende de
    su probabilidad en la casa y casi de nada más (juzga 2017-21):

        X según la casa      +1,5    +2,5    +3,5    +4,5
        favorito 55-60 %      70 %    78 %    84 %    89 %
        favorito 60-65 %      72 %    80 %    87 %    91 %
        no favorito 40-45 %   57 %    66 %    74 %    81 %

    Playdoit publica hasta ±4,5: sí hay líneas al 75-85 %.
  · TOTALES a k carreras de la línea: «más» 70 % (k=2,5), 79 % (3,5), 86 %
    (4,5); «menos» 70 / 76 / 81 %.
  · PATRONES contra la casa (estadio y altura —Coors—, local/visita, tabla,
    abridor zurdo, mes, nivel del total, movimiento de la cuota): NINGUNO pasa
    en las dos mitades. La casa ya pone todo eso en su precio.

LA REGLA es la de la NBA (v354): por lado, la línea de mejor cuota con
probabilidad medida ≥ 75 % y cuota ≥ 1,15; la Capa 1, ≥ 84 % y cuota ≥ 1,10.
La KBO usa sus propias tablas cuando las tenga medidas (`KBO_MEDIDA`).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger('mlb_lineas')

FICHERO = 'mlb_lineas.json'
META_METER = 0.75
CUOTA_MIN = 1.15
META_CAPA1 = 0.84
CUOTA_MIN_CAPA1 = 1.10
DEPORTES = ('MLB',)
# v355 — LA KBO, CON LAS TABLAS DE LA MLB: en sus 395 cierres con resultado
# (`cuotas_kbo_cierre.csv`, 2012-2026, 790 lados) la tabla del hándicap predice
# +2,5 72,5 % y acertó 72,7; +3,5 79,7 / 79,1; +4,5 85,6 / 84,1. El hándicap
# sí; los totales no tienen historial de líneas en la KBO: sólo informativos.
KBO_MEDIDA = True
_CACHE: Dict = {}
_RE_HCP = re.compile(r'^(.*?)\s*\(([+\-−]?\d+(?:[.,]\d+)?)\)\s*$')


def _doc() -> Dict:
    try:
        mt = os.path.getmtime(FICHERO)
    except OSError:
        return {}
    if _CACHE.get('mt') != mt:
        try:
            _CACHE.update(mt=mt, doc=json.load(open(FICHERO, encoding='utf-8')))
        except Exception as e:
            logger.debug('[mlb_lineas] %s', e)
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
    """Acierto del equipo con la línea `linea`, según su probabilidad en la
    casa (interpolado entre bandas). Sólo las líneas medidas."""
    tab = _doc().get('handicap') or []
    clave = '%+g' % linea
    pts = [(b['p'], b[clave]) for b in tab if clave in b]
    return _interp(pts, p_equipo) if pts else None


def prob_total(lado: str, k: float) -> Optional[float]:
    t = (_doc().get('totales') or {}).get(lado) or {}
    pts = [(float(a), float(b)) for a, b in t.items()]
    return _interp(pts, k) if pts else None


def _apodo(nombre) -> str:
    """Lo que identifica al equipo en los nombres de Playdoit («CLE
    Guardians», «CHI White Sox») y en los nuestros («Chicago White Sox»)."""
    t = str(nombre or '').lower().replace('.', ' ').split()
    if len(t) >= 2 and t[-1] == 'sox':
        return ' '.join(t[-2:])
    if len(t) >= 2 and t[-1] in ('jays',):
        return ' '.join(t[-2:])
    return t[-1] if t else ''


def del_tablero(det: Dict, home: str, away: str) -> Optional[Dict]:
    """Ganador (sin margen), escalera de hándicap y de totales de Playdoit, con
    NUESTROS nombres. None si no hay nada."""
    if not det:
        return None
    ah, aa = _apodo(home), _apodo(away)
    hcp: Dict[str, Dict[float, float]] = {home: {}, away: {}}
    tot: Dict[str, Dict[float, float]] = {'mas': {}, 'menos': {}}
    ml: Dict[str, float] = {}
    for m in det.get('mercados') or []:
        nombre = str(m.get('nombre') or '')
        sels = m.get('selecciones') or []
        if nombre.startswith('Ganador (incl'):
            for s in sels:
                eq = _apodo(s.get('nombre'))
                if s.get('cuota'):
                    if eq == ah:
                        ml[home] = float(s['cuota'])
                    elif eq == aa:
                        ml[away] = float(s['cuota'])
        elif nombre.startswith('Hándicap (incl'):
            for s in sels:
                mm = _RE_HCP.match(str(s.get('nombre') or ''))
                if not mm or not s.get('cuota'):
                    continue
                eq = _apodo(mm.group(1))
                lin = float(mm.group(2).replace(',', '.').replace('−', '-'))
                if eq == ah:
                    hcp[home][lin] = float(s['cuota'])
                elif eq == aa:
                    hcp[away][lin] = float(s['cuota'])
        elif nombre.startswith('Totales (incl'):
            for s in sels:
                t = str(s.get('nombre') or '')
                mm = re.search(r'(\d+(?:[.,]\d+)?)', t)
                if not mm or not s.get('cuota'):
                    continue
                lin = float(mm.group(1).replace(',', '.'))
                # las enteras cuentan para hallar la principal (Dodgers–Brewers:
                # 6 a 1,91/1,91); se apuesta sólo en las de ,5 (`candidatas`)
                (tot['mas'] if t.startswith('Más') else tot['menos'] if t.startswith('Menos')
                 else {})[lin] = float(s['cuota'])
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
    # sin una pareja de verdad pareja no hay línea principal y no se mide nada
    # (Dodgers–Brewers del 12-oct: la «más pareja» era 5,5 a 1,30/3,30)
    if mejor is not None and mejor[0] <= 0.5:
        out['totales'] = {'principal': mejor[1],
                          'mas': {'%g' % k: v for k, v in tot['mas'].items()},
                          'menos': {'%g' % k: v for k, v in tot['menos'].items()}}
    return out or None


def _equipos(partido: str):
    if ' @ ' in partido:
        a, h = (x.strip() for x in partido.split(' @ ', 1))
        return h, a
    if ' vs ' in partido:
        h, a = (x.strip() for x in partido.split(' vs ', 1))
        return h, a
    return None, None


def candidatas(pick: Dict) -> List[Dict]:
    out: List[Dict] = []
    try:
        tab = ((pick or {}).get('implicitas') or {}).get('mlb_playdoit') or {}
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
                        continue             # sólo las de ,5: sin devolución
                    k = (t0 - lin) if lado == 'mas' else (lin - t0)
                    if k <= 0:
                        continue
                    p = prob_total(lado, k)
                    if p is None:
                        continue
                    if str(pick.get('deporte') or '') == 'KBO':
                        continue             # KBO: los totales no están medidos
                    out.append({'apuesta': 'Carreras: %s %g' % (rot, lin),
                                'mercado': 'Carreras', 'bloque': 'totales',
                                'etiqueta': 'Carreras', 'linea': lin, 'prob': round(p, 4),
                                'cuota': float(cuota), 'k': round(k, 1), 'tipo': lado})
    except Exception as e:
        logger.debug('[mlb_lineas] candidatas de %s: %s', (pick or {}).get('partido'), e)
    return out


def elegidas(pick: Dict, meta: float = META_METER, cuota_min: float = CUOTA_MIN) -> List[Dict]:
    """Por lado, la de mejor cuota que llega a la meta; si ningún lado de un
    mercado llega, su más probable como informativa."""
    cands = candidatas(pick)
    out = []
    for mercado in ('Handicap', 'Carreras'):
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


def aplica(pick: Dict) -> bool:
    dep = str((pick or {}).get('deporte') or '')
    return dep in DEPORTES or (dep == 'KBO' and KBO_MEDIDA)
