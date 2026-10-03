# -*- coding: utf-8 -*-
"""
v325 — EL ESTADO DE CADA EQUIPO ANTES DE CADA PARTIDO (NFL, sin fuga).

Se recorre `historico_nfl_largo.csv` en orden y, ANTES de mirar el resultado
de un partido, se anotan sus variables con lo que se sabía hasta ese momento;
después se actualiza el estado con el resultado. Así cada fila del dataset es
exactamente lo que el modelo habría tenido delante al apostar.

Lo que se lleva de cada equipo (franquicia):

  · ELO con margen de victoria (el de FiveThirtyEight): un número que resume
    todo el historial, con ventaja de campo y regresión a la media entre
    temporadas.
  · EPA por jugada, de ataque y de defensa (y por separado pase y carrera),
    en media exponencial: describe CÓMO juega un equipo, no sólo cuánto
    anota, y el marcador es mucho más ruidoso.
  · Puntos a favor y en contra, y el ritmo (jugadas por partido).

Y de cada QUARTERBACK, por su identificador: el EPA por dropback del equipo
en los partidos que él fue titular, en media exponencial y encogido hacia el
nivel de un suplente cuando ha jugado poco. Es lo que explica, por ejemplo,
Washington–Colts del 2026-10-04: con Marcus Mariota de titular la casa paga a
Washington a 2,80; un modelo que no mira al quarterback lo daba favorito.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Parámetros del estado. Se fijan con las temporadas 2002-2014 (ver
# `_v325_nfl.py`) y se juzgan en 2015-2025, que no participan en la elección.
ELO_K = 40.0
ELO_HFA = 48.0              # ventaja de campo en puntos Elo (~1,7 de margen)
ELO_REGRESION = 1.0 / 3.0   # cuánto vuelve a la media entre temporadas
MEDIA_DECAY = 0.98          # peso de lo anterior en las medias exponenciales
ARRASTRE = 0.80             # cuánto de la media sobrevive al cambio de temporada
QB_DECAY = 0.90
QB_PREVIO = 8.0             # «partidos» de suplente con que arranca un QB
QB_SUPLENTE = -0.20         # EPA por dropback de un suplente cualquiera

LIGA = {'epa_of': 0.0, 'epa_pase': 0.05, 'epa_carrera': -0.08,
        'pts': 22.0, 'jugadas': 63.0, 'perdidas': 1.5}


class _Media:
    """Media exponencial con peso acumulado (para encoger hacia la liga)."""
    __slots__ = ('v', 'w')

    def __init__(self, v: float):
        self.v, self.w = v, 0.0

    def poner(self, x: float, decay: float) -> None:
        if x is None or x != x:
            return
        w = self.w * decay
        self.v = (self.v * w + x) / (w + 1.0)
        self.w = w + 1.0

    def nueva_temporada(self, base: float, arrastre: float) -> None:
        self.v = base + (self.v - base) * arrastre
        self.w *= arrastre


class Estado:
    CAMPOS = ('of', 'de', 'of_pase', 'de_pase', 'of_carrera', 'de_carrera',
              'pts_f', 'pts_c', 'jugadas', 'perdidas_f', 'perdidas_c')

    def __init__(self):
        self.elo: Dict[str, float] = {}
        self.m: Dict[str, Dict[str, _Media]] = {}
        self.qb: Dict[str, _Media] = {}
        self.qb_n: Dict[str, int] = {}
        self.ultimo_qb: Dict[str, str] = {}
        self.temporada: Dict[str, int] = {}
        self.jugados: Dict[str, int] = {}
        self.liga_pts = _Media(LIGA['pts'])

    def _base(self, campo: str) -> float:
        if campo in ('of', 'de'):
            return LIGA['epa_of']
        if campo in ('of_pase', 'de_pase'):
            return LIGA['epa_pase']
        if campo in ('of_carrera', 'de_carrera'):
            return LIGA['epa_carrera']
        if campo in ('pts_f', 'pts_c'):
            return self.liga_pts.v
        if campo == 'jugadas':
            return LIGA['jugadas']
        return LIGA['perdidas']

    def _equipo(self, e: str, temporada: int) -> Dict[str, _Media]:
        if e not in self.m:
            self.m[e] = {c: _Media(self._base(c)) for c in self.CAMPOS}
            self.elo[e] = 1500.0
            self.temporada[e] = temporada
            self.jugados[e] = 0
        elif self.temporada[e] != temporada:
            for c, mm in self.m[e].items():
                mm.nueva_temporada(self._base(c), ARRASTRE)
            self.elo[e] = 1505.0 * ELO_REGRESION + self.elo[e] * (1 - ELO_REGRESION)
            self.temporada[e] = temporada
        return self.m[e]

    def qb_valor(self, qb_id) -> float:
        if not isinstance(qb_id, str) or not qb_id:
            return QB_SUPLENTE
        m = self.qb.get(qb_id)
        if m is None:
            return QB_SUPLENTE
        # encogido hacia el suplente con QB_PREVIO partidos de peso
        return (m.v * m.w + QB_SUPLENTE * QB_PREVIO) / (m.w + QB_PREVIO)

    # -- las variables de un partido, ANTES de jugarlo ---------------------
    def variables(self, g) -> Dict[str, float]:
        t = int(g['season'])
        h, a = g['home'], g['away']
        mh, ma = self._equipo(h, t), self._equipo(a, t)
        neutral = bool(g.get('neutral'))
        v = {}
        v['elo_dif'] = (self.elo[h] - self.elo[a] + (0 if neutral else ELO_HFA)) / 25.0
        for lado, mm in (('h', mh), ('a', ma)):
            for c in self.CAMPOS:
                v['%s_%s' % (lado, c)] = mm[c].v
        qh = self.qb_valor(g.get('home_qb_id'))
        qa = self.qb_valor(g.get('away_qb_id'))
        v['h_qb'], v['a_qb'] = qh, qa
        # el QB de hoy contra el pase que el equipo venía teniendo: lo que
        # cambia cuando entra un suplente (o vuelve el titular)
        v['h_qb_delta'] = qh - mh['of_pase'].v
        v['a_qb_delta'] = qa - ma['of_pase'].v
        v['h_qb_nuevo'] = float(self.ultimo_qb.get(h) not in (None, g.get('home_qb_id')))
        v['a_qb_nuevo'] = float(self.ultimo_qb.get(a) not in (None, g.get('away_qb_id')))
        hr = pd.to_numeric(g.get('home_rest'), errors='coerce')
        ar = pd.to_numeric(g.get('away_rest'), errors='coerce')
        v['descanso_dif'] = float(np.clip((hr if hr == hr else 7) - (ar if ar == ar else 7), -7, 7))
        v['neutral'] = float(neutral)
        v['div'] = float(g.get('div_game') or 0)
        roof = str(g.get('roof') or '')
        v['techo'] = float(roof in ('dome', 'closed'))
        w = pd.to_numeric(g.get('wind'), errors='coerce')
        v['viento'] = 0.0 if roof in ('dome', 'closed') or w != w else float(w)
        tp = pd.to_numeric(g.get('temp'), errors='coerce')
        v['frio'] = 0.0 if roof in ('dome', 'closed') or tp != tp else float(max(0.0, 40.0 - tp))
        v['liga_pts'] = self.liga_pts.v
        v['playoffs'] = float(g.get('tipo') == 'playoffs')
        v['n_h'] = self.jugados[h]
        v['n_a'] = self.jugados[a]
        return v

    # -- el resultado, DESPUÉS ---------------------------------------------
    def registrar(self, g) -> None:
        hs, as_ = g.get('home_score'), g.get('away_score')
        if hs is None or as_ is None or hs != hs or as_ != as_:
            return
        t = int(g['season'])
        h, a = g['home'], g['away']
        mh, ma = self._equipo(h, t), self._equipo(a, t)
        neutral = bool(g.get('neutral'))
        # Elo con margen de victoria
        dif = self.elo[h] - self.elo[a] + (0 if neutral else ELO_HFA)
        esperado = 1.0 / (1.0 + 10 ** (-dif / 400.0))
        mov = float(hs) - float(as_)
        real = 1.0 if mov > 0 else (0.5 if mov == 0 else 0.0)
        gan = dif if mov > 0 else -dif
        mult = math.log(abs(mov) + 1.0) * 2.2 / (gan * 0.001 + 2.2) if mov != 0 else 1.0
        cambio = ELO_K * mult * (real - esperado)
        self.elo[h] += cambio
        self.elo[a] -= cambio

        def por(x, n):
            x, n = float(x if x == x else 0), float(n if n == n else 0)
            return x / n if n > 0 else None

        lados = {}
        for lado in ('home', 'away'):
            j = g.get('%s_jugadas' % lado)
            lados[lado] = {
                'of': por((g.get('%s_epa_pase' % lado) or 0) + (g.get('%s_epa_carrera' % lado) or 0), j),
                'pase': por(g.get('%s_epa_pase' % lado), g.get('%s_dropbacks' % lado)),
                'carrera': por(g.get('%s_epa_carrera' % lado), g.get('%s_acarreos' % lado)),
                'jugadas': j if j == j and j else None,
                'perdidas': g.get('%s_perdidas' % lado)}
        for e, mm, yo, el, pf, pc in ((h, mh, 'home', 'away', hs, as_),
                                      (a, ma, 'away', 'home', as_, hs)):
            p, q = lados[yo], lados[el]
            mm['of'].poner(p['of'], MEDIA_DECAY)
            mm['de'].poner(q['of'], MEDIA_DECAY)
            mm['of_pase'].poner(p['pase'], MEDIA_DECAY)
            mm['de_pase'].poner(q['pase'], MEDIA_DECAY)
            mm['of_carrera'].poner(p['carrera'], MEDIA_DECAY)
            mm['de_carrera'].poner(q['carrera'], MEDIA_DECAY)
            mm['pts_f'].poner(float(pf), MEDIA_DECAY)
            mm['pts_c'].poner(float(pc), MEDIA_DECAY)
            mm['jugadas'].poner(p['jugadas'], MEDIA_DECAY)
            mm['perdidas_f'].poner(p['perdidas'], MEDIA_DECAY)
            mm['perdidas_c'].poner(q['perdidas'], MEDIA_DECAY)
            self.jugados[e] += 1
            qb = g.get('%s_qb_id' % yo)
            if isinstance(qb, str) and qb and p['pase'] is not None:
                self.qb.setdefault(qb, _Media(QB_SUPLENTE)).poner(p['pase'], QB_DECAY)
                self.qb_n[qb] = self.qb_n.get(qb, 0) + 1
            if isinstance(qb, str) and qb:
                self.ultimo_qb[e] = qb
        self.liga_pts.poner((float(hs) + float(as_)) / 2.0, 0.995)


def dataset(d: pd.DataFrame):
    """`(filas, estado)`: una fila por partido con sus variables previas y su
    resultado, y el estado tras el último partido jugado. Los partidos sin
    marcador (los que faltan) también salen, con el resultado vacío, y no
    tocan el estado."""
    est = Estado()
    filas = []
    for g in d.to_dict('records'):
        v = est.variables(g)
        v.update({k: g.get(k) for k in (
            'game_id', 'season', 'week', 'tipo', 'gameday', 'home', 'away',
            'home_score', 'away_score', 'spread_line', 'total_line',
            'home_moneyline', 'away_moneyline', 'over_odds', 'under_odds',
            'home_spread_odds', 'away_spread_odds', 'home_qb_name',
            'away_qb_name')})
        filas.append(v)
        est.registrar(g)
    out = pd.DataFrame(filas)
    out['margen'] = out['home_score'] - out['away_score']
    out['total'] = out['home_score'] + out['away_score']
    return out, est


# ---------------------------------------------------------------------------
# Las variables que entran al modelo (las mismas en la réplica y en producción)
# ---------------------------------------------------------------------------
COLS_MARGEN = ['elo_dif', 'd_of', 'd_de', 'd_pase', 'd_carrera', 'd_qb',
               'd_qb_delta', 'd_qb_nuevo', 'd_pts', 'd_perdidas',
               'descanso_dif', 'local', 'div']
COLS_TOTAL = ['s_of', 's_de', 's_pts', 's_jugadas', 's_qb', 'liga_pts',
              'techo', 'viento', 'frio', 'playoffs', 'div']


def derivar(x: pd.DataFrame) -> pd.DataFrame:
    """De las variables de cada lado a las del partido (diferencias y sumas)."""
    x = x.copy()
    x['d_of'] = x.h_of - x.a_of
    x['d_de'] = x.h_de - x.a_de
    x['d_pase'] = (x.h_of_pase - x.h_de_pase) - (x.a_of_pase - x.a_de_pase)
    x['d_carrera'] = (x.h_of_carrera - x.h_de_carrera) - (x.a_of_carrera - x.a_de_carrera)
    x['d_qb'] = x.h_qb - x.a_qb
    x['d_qb_delta'] = x.h_qb_delta - x.a_qb_delta
    x['d_qb_nuevo'] = x.h_qb_nuevo - x.a_qb_nuevo
    x['d_pts'] = (x.h_pts_f - x.h_pts_c) - (x.a_pts_f - x.a_pts_c)
    x['d_perdidas'] = (x.h_perdidas_f - x.h_perdidas_c) - (x.a_perdidas_f - x.a_perdidas_c)
    x['local'] = 1.0 - x.neutral
    x['s_of'] = x.h_of + x.a_of
    x['s_de'] = x.h_de + x.a_de
    x['s_pts'] = x.h_pts_f + x.h_pts_c + x.a_pts_f + x.a_pts_c
    x['s_jugadas'] = x.h_jugadas + x.a_jugadas
    x['s_qb'] = x.h_qb + x.a_qb
    return x
