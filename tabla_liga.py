# -*- coding: utf-8 -*-
"""
v316 — LA TABLA DE CADA COMPETICIÓN, CON LO QUE PIDIÓ EL USUARIO.

«Que la aplicación pueda checar las clasificaciones y sus goles a favor y en
contra, para saber si le vamos mejor a un under o a un over», y «goles a
favor y en contra por partido, local y visita, con el % de partidos con 4 o
más goles».

Para cualquier competición con historial (el motor de ligas, la base de
FotMob o la de Flashscore) se reconstruye la tabla de la temporada en curso
con los partidos YA jugados: puntos, posición, distancia en puntos a la zona
de arriba (el 25 % de la tabla: liguilla, playoffs, copas) y a la de descenso
(el 15 % de abajo), goles a favor y en contra por partido en casa y fuera, y
el % de sus partidos con 4 o más goles. Una temporada nueva empieza cuando la
competición para más de 35 días.

Si el partido es «decisivo para ambos» (los dos a 3 puntos o menos de una de
esas zonas, pasada la mitad de la temporada) se dice. Lo que cada cosa pesa
en la probabilidad está medido en `_v316_contexto.py`; aquí sólo se cuenta.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PAUSA_TEMPORADA = 35


def temporada_actual(df: pd.DataFrame) -> pd.DataFrame:
    """Los partidos de la temporada en curso (columnas date, home, away, gh, ga)."""
    if df is None or df.empty:
        return df
    df = df.sort_values('date')
    corte = df['date'].diff().dt.days.gt(PAUSA_TEMPORADA)
    if corte.any():
        ultimo = df.index[corte][-1]
        df = df.loc[ultimo:]
    return df


def tabla(df: pd.DataFrame) -> Dict[str, Dict]:
    """{equipo: estadísticas} de la temporada en curso de `df`."""
    t = temporada_actual(df)
    est: Dict[str, Dict] = {}
    if t is None or t.empty:
        return est
    for r in t.itertuples(index=False):
        for eq, gf, gc, casa in ((r.home, r.gh, r.ga, True), (r.away, r.ga, r.gh, False)):
            e = est.setdefault(eq, {'pj': 0, 'pts': 0, 'gf': 0, 'gc': 0, 'n4': 0,
                                    'cpj': 0, 'cgf': 0, 'cgc': 0, 'fpj': 0, 'fgf': 0, 'fgc': 0})
            e['pj'] += 1
            e['gf'] += gf
            e['gc'] += gc
            e['n4'] += int(r.gh + r.ga >= 4)
            e['pts'] += 3 if gf > gc else (1 if gf == gc else 0)
            p = 'c' if casa else 'f'
            e[p + 'pj'] += 1
            e[p + 'gf'] += gf
            e[p + 'gc'] += gc
    orden = sorted(est, key=lambda k: (-est[k]['pts'], -(est[k]['gf'] - est[k]['gc'])))
    N = len(orden)
    k_top, k_bot = max(1, round(0.25 * N)), max(1, round(0.15 * N))
    b_top = est[orden[k_top - 1]]['pts']
    b_bot = est[orden[N - k_bot]]['pts']
    pj_medio = np.mean([e['pj'] for e in est.values()])
    for i, k in enumerate(orden):
        e = est[k]
        e['pos'], e['n_equipos'] = i + 1, N
        e['a_zona_arriba'] = e['pts'] - b_top
        e['a_descenso'] = e['pts'] - b_bot
        e['avance'] = round(pj_medio / max(1, 2 * (N - 1)), 2)
        e['pct_4mas'] = e['n4'] / e['pj'] if e['pj'] else None
        e['casa_gf'] = e['cgf'] / e['cpj'] if e['cpj'] else None
        e['casa_gc'] = e['cgc'] / e['cpj'] if e['cpj'] else None
        e['fuera_gf'] = e['fgf'] / e['fpj'] if e['fpj'] else None
        e['fuera_gc'] = e['fgc'] / e['fpj'] if e['fpj'] else None
    return est


def _de_motor(clave: str) -> Optional[pd.DataFrame]:
    try:
        import panel_equipos as pe
        h = pe._historico(clave)
        if h is None or h.empty:
            return None
        h = h.dropna(subset=['home_goals', 'away_goals'])
        return pd.DataFrame({'date': pd.to_datetime(h['date']), 'home': h['home_team'],
                             'away': h['away_team'], 'gh': h['home_goals'].astype(int),
                             'ga': h['away_goals'].astype(int)})
    except Exception:
        return None


def _de_flashscore(liga: str) -> Optional[pd.DataFrame]:
    try:
        import resultados_flashscore as rf
        b = rf.cargar()
        x = b[b['liga'] == liga]
        if x.empty:
            return None
        ruta = x['ruta'].iloc[0]
        x = b[b['ruta'] == ruta]
        return pd.DataFrame({'date': x['ini'], 'home': x['home'], 'away': x['away'],
                             'gh': x['gh'], 'ga': x['ga']})
    except Exception:
        return None


_MEM: Dict = {}


def de_partido(pick: Dict) -> Optional[Dict]:
    """La tabla de los dos equipos de este partido, o None. Nunca lanza."""
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
        if not (h and a):
            return None
        clave = str(pick.get('clave_liga') or '')
        k = ('fs:' + str(pick.get('liga_origen') or pick.get('liga'))) \
            if pick.get('solo_mercado') else clave
        if k not in _MEM:
            df = _de_flashscore(str(pick.get('liga_origen') or pick.get('liga'))) \
                if pick.get('solo_mercado') else _de_motor(clave)
            _MEM[k] = tabla(df) if df is not None else {}
        t = _MEM[k]
        eh, ea = t.get(h), t.get(a)
        if not (eh and ea):
            return None
        en_juego = lambda e: abs(e['a_zona_arriba']) <= 3 or abs(e['a_descenso']) <= 3
        return {'local': eh, 'visita': ea,
                'decisivo_ambos': bool(eh['avance'] >= 0.5 and en_juego(eh) and en_juego(ea))}
    except Exception as e:
        logger.debug('[tabla] %s: %s', pick.get('partido'), e)
        return None


def texto(pick: Dict) -> str:
    """Una línea por equipo, para la tarjeta y para Telegram."""
    t = de_partido(pick)
    if not t:
        return ''
    import modo_modelo as mm
    h, a = mm._equipos(pick)

    def _f(x):
        return '—' if x is None else ('%.1f' % x)

    def _l(nom, e, casa):
        gf, gc = (e['casa_gf'], e['casa_gc']) if casa else (e['fuera_gf'], e['fuera_gc'])
        return ('%s %dº/%d · %d pts (%+d a zona de arriba, %+d al descenso) · %s '
                'mete %s y recibe %s por partido · 4+ goles en %s de sus partidos'
                % (nom, e['pos'], e['n_equipos'], e['pts'], e['a_zona_arriba'],
                   e['a_descenso'], 'en casa' if casa else 'fuera', _f(gf), _f(gc),
                   ('%.0f %%' % (100 * e['pct_4mas'])) if e['pct_4mas'] is not None else '—'))
    s = 'TABLA: %s | %s' % (_l(h, t['local'], True), _l(a, t['visita'], False))
    if t['decisivo_ambos']:
        s += ' | ⚠️ partido decisivo para los dos'
    return s
