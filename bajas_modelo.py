# -*- coding: utf-8 -*-
"""
v308 — LAS BAJAS ENTRAN EN EL MODELO DE GOLES, PORQUE SE MIDIÓ QUE MEJORAN.

El usuario: «estoy casi seguro de que sí se puede con el histórico; haz
pruebas, varias hipótesis, método científico». Tenía razón.

CÓMO SE MIDIÓ (`_v308_bajas.py`, `_v308_bajas.json`)
FotMob borra la lista de lesionados cuando el partido termina, pero deja la
convocatoria. En 30.834 equipo-partido de 15.450 partidos se reconstruyó la
baja como «habitual (titular en ≥ la mitad de sus 10 anteriores) que no está
convocado», con el peso de lo que aportaba. Se cruzó con la λ de goles que
nuestro modelo de producción había dado a cada equipo (`pick_ledger_totales`,
walk-forward): 9.772 partidos. Ajuste en el 70 % antiguo, juicio en el 30 %
final, bootstrap por partido de la mejora contra el modelo sin bajas:

    hipótesis                                  goles     más/menos 2,5   1X2
    H1  remates perdidos del ataque            no           no           sí
    H2  zaga que le falta al rival             SÍ           no           no
    H3  valor de mercado perdido               no           no           no
    H4  número de habituales ausentes          SÍ           no           no
    H5  remates perdidos + zaga del rival      SÍ           no           no
    H6  xG perdido + zaga del rival            SÍ           SÍ           no   <-

H6 es la única que pasa en goles Y en el más/menos 2,5 en los DOS tramos
(p5 de la mejora de log-verosimilitud +0,00088 / +0,00132 por partido; del
2,5: +0,00003 / +0,00037). Coeficientes ajustados en el tramo de elección:

    λ' = λ · exp(−0,2013 · xG_perdido_propio + 0,2535 · zaga_perdida_rival)

    un equipo sin los titulares que generan el 20 % de su xG: −4 % de goles
    un rival sin la mitad de sus minutos de zaga habitual:    +13,5 % de goles

El 1X2 NO se toca: con H6 falla en el tramo de elección.

EN PRODUCCIÓN
Las bajas de antes del partido las da FotMob (`bajas_fotmob`, lesión y
sanción). Se cruzan con los habituales de los 10 últimos partidos de cada
equipo en `remates_fotmob` y se calculan los mismos dos rasgos. Luego se
mueven la λ de goles y, con ella, las líneas de goles del partido y de cada
equipo, por diferencia de Poisson (la misma distribución con la que se
midió): p' = p + P(λ') − P(λ).

Diferencia honesta con lo medido: en el histórico «baja» incluye también al
habitual que no fue convocado por rotación; antes del partido sólo se conoce
la lesión y la sanción. Es un subconjunto de lo medido, no otra cosa.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BETA_ATAQUE_XG = -0.2013
BETA_ZAGA_RIVAL = 0.2535
VENT = 10
# un ajuste mayor que esto sería extrapolar: en la medición, el 95 % de los
# equipo-partido quedaba dentro de ±12 %
TOPE = 0.15


def _es_zaga(pos, posicion) -> bool:
    try:
        return float(pos) // 10 <= 4
    except (TypeError, ValueError):
        return str(posicion or '') in ('G', 'D')


def rasgos(clave_liga: str, equipo: str, nombres_baja: List[str]) -> Dict:
    """xG perdido (parte del xG del equipo que aportaban los habituales que
    faltan) y zaga perdida (parte de los minutos de portero y defensas)."""
    import remates_fotmob as rf
    import lineas_jugador as lj
    fuera = {'ataque_xg': 0.0, 'zaga': 0.0, 'ausentes': []}
    if not nombres_baja:
        return fuera
    dj = rf._jugadores()
    if dj is None or dj.empty:
        return fuera
    eq = rf._resolver_equipo(equipo, rf._candidatos(dj, clave_liga))
    if not eq:
        return fuera
    s = dj[dj['equipo'] == eq]
    partidos = list(dict.fromkeys(s.sort_values('fecha')['match_id']
                                  .astype(str)))[-VENT:]
    if len(partidos) < 4:
        return fuera
    s = s[s['match_id'].astype(str).isin(partidos)].copy()
    xg_tot = float(s['xg'].sum()) or 1.0
    s['zaga'] = [_es_zaga(p, q) for p, q in zip(s.get('pos'),
                                                 s.get('posicion'))]
    min_zaga = float(s.loc[s['zaga'], 'minutos'].sum()) or 1.0
    habituales = {}
    for jug, g in s.groupby('jugador'):
        if float(g['titular'].sum()) >= len(partidos) / 2:
            habituales[jug] = g
    for nombre in nombres_baja:
        j = nombre if nombre in habituales else lj.por_apellidos(
            nombre, list(habituales))
        if not j or j in fuera['ausentes']:
            continue
        g = habituales[j]
        fuera['ausentes'].append(j)
        fuera['ataque_xg'] += float(g['xg'].sum()) / xg_tot
        fuera['zaga'] += float(g.loc[g['zaga'], 'minutos'].sum()) / min_zaga
    fuera['ataque_xg'] = round(min(fuera['ataque_xg'], 1.0), 4)
    fuera['zaga'] = round(min(fuera['zaga'], 1.0), 4)
    return fuera


def factores(r_local: Dict, r_visita: Dict) -> tuple:
    """(f_local, f_visitante): lo que se multiplica cada λ de goles."""
    def tope(x):
        return max(1 - TOPE, min(1 + TOPE, x))
    f_l = math.exp(BETA_ATAQUE_XG * r_local['ataque_xg']
                   + BETA_ZAGA_RIVAL * r_visita['zaga'])
    f_v = math.exp(BETA_ATAQUE_XG * r_visita['ataque_xg']
                   + BETA_ZAGA_RIVAL * r_local['zaga'])
    return tope(f_l), tope(f_v)


def _p_mas(linea: float, lam: float) -> float:
    """P(goles > línea) con Poisson; líneas enteras: P(> L) sin el empate."""
    k = int(math.floor(float(linea))) + 1
    acc, term = 0.0, math.exp(-lam)
    for i in range(k):
        acc += term
        term *= lam / (i + 1)
    return 1.0 - acc


def _mover(lineas: Dict, lam0: float, lam1: float) -> Dict:
    fuera = {}
    for L, p in (lineas or {}).items():
        try:
            p = float(p)
            d = _p_mas(float(L), lam1) - _p_mas(float(L), lam0)
            fuera[L] = round(min(0.99, max(0.01, p + d)), 4)
        except (TypeError, ValueError):
            fuera[L] = p
    return fuera


def ajustar_pick(pick: Dict) -> Optional[Dict]:
    """Mueve la λ de goles y las líneas de goles del pronóstico según sus
    bajas. Devuelve lo que hizo (o None si no había bajas o datos)."""
    if not isinstance(pick, dict) or pick.get('ajuste_bajas'):
        return None
    gx = pick.get('goles_xg') or {}
    try:
        lh0, la0 = float(gx['local']), float(gx['visitante'])
    except (KeyError, TypeError, ValueError):
        return None
    par = str(pick.get('partido') or '')
    if ' vs ' not in par:
        return None
    try:
        import bajas_fotmob as bf
        b = bf.de_partido(pick)
    except Exception as e:
        logger.debug('[bajas_modelo] %s: %s', par, e)
        return None
    if not b:
        return None
    h, a = (x.strip() for x in par.split(' vs ', 1))
    clave = str(pick.get('clave_liga') or '')
    nb = {lado: [str(x.get('jugador')) for x in
                 ((b.get(lado) or {}).get('bajas') or []) if x.get('jugador')]
          for lado in ('home', 'away')}
    if not nb['home'] and not nb['away']:
        return None
    r_l = rasgos(clave, h, nb['home'])
    r_v = rasgos(clave, a, nb['away'])
    if not (r_l['ausentes'] or r_v['ausentes']):
        return None
    f_l, f_v = factores(r_l, r_v)
    lh1, la1 = lh0 * f_l, la0 * f_v
    pick['goles_xg'] = dict(gx, local=round(lh1, 3), visitante=round(la1, 3))
    if pick.get('goles_lineas'):
        pick['goles_lineas'] = _mover(pick['goles_lineas'], lh0 + la0,
                                      lh1 + la1)
    ge = pick.get('goles_equipo') or {}
    if ge:
        pick['goles_equipo'] = dict(
            ge, local=_mover(ge.get('local') or {}, lh0, lh1),
            visitante=_mover(ge.get('visitante') or {}, la0, la1))
    info = {'local': {'ausentes': r_l['ausentes'], 'factor': round(f_l, 4),
                      'xg_perdido': r_l['ataque_xg'], 'zaga': r_l['zaga']},
            'visitante': {'ausentes': r_v['ausentes'],
                          'factor': round(f_v, 4),
                          'xg_perdido': r_v['ataque_xg'], 'zaga': r_v['zaga']}}
    pick['ajuste_bajas'] = info
    return info


def ajustar_lista(picks: List[Dict]) -> int:
    """Ajusta los pronósticos de fútbol de una lista. Devuelve cuántos."""
    n = 0
    for p in picks or []:
        try:
            if str(p.get('deporte') or 'Fútbol') == 'Fútbol' and ajustar_pick(p):
                n += 1
        except Exception as e:
            logger.debug('[bajas_modelo] %s: %s', p.get('partido'), e)
    return n


def texto(pick: Dict) -> str:
    """«🚑 Bajas: Arsenal −4 % goles (Saka) · Leeds +3 %» — o vacío."""
    info = pick.get('ajuste_bajas') or {}
    trozos = []
    par = str(pick.get('partido') or '')
    nombres = par.split(' vs ', 1) if ' vs ' in par else ['Local', 'Visitante']
    for lado, eq in zip(('local', 'visitante'), nombres):
        x = info.get(lado) or {}
        f = x.get('factor')
        if f is None or abs(f - 1) < 0.01:
            continue
        trozos.append('%s %+.0f %% goles' % (eq.strip(), 100 * (f - 1)))
    if not trozos:
        return ''
    return '🚑 Bajas: ' + ' · '.join(trozos)
