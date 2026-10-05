# -*- coding: utf-8 -*-
"""
v330 — EL ESTADO DE CADA EQUIPO DE LA NBA ANTES DE CADA PARTIDO (sin fuga).

Igual que `nfl_estado`: se recorre `historico_nba_largo.csv` en orden y, ANTES
de mirar el resultado de un partido, se anotan sus variables con lo que se
sabía hasta ese momento; después se actualiza el estado.

Lo que se lleva de cada equipo:

  · ELO con margen de victoria (el de FiveThirtyEight para la NBA): ventaja
    de campo, multiplicador por margen corregido por la diferencia de nivel
    (para no premiar la paliza del favorito) y regresión a la media entre
    temporadas.
  · RATING DE MARGEN AJUSTADO POR RIVAL (como el SRS): el margen de cada
    partido más el nivel del rival, en media exponencial. Ganar de 10 a un
    colista no vale lo mismo que a un aspirante.
  · Puntos a favor y en contra (ataque y defensa) y el ritmo del total.
  · El CALENDARIO, que en la NBA pesa: días de descanso, partido en noches
    seguidas (back-to-back) y tres partidos en cuatro noches.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np
import pandas as pd

ELO_K = 20.0
ELO_HFA = 100.0
ELO_REGRESION = 0.25
DECAY = 0.95
ARRASTRE = 0.60
DECAY_CASA = 0.90
ARRASTRE_CASA = 0.70
HCA_CASA = 2.5
LIGA_PTS = 105.0


class _Media:
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
    def __init__(self):
        self.elo: Dict[str, float] = {}
        self.m: Dict[str, Dict[str, _Media]] = {}
        self.temporada: Dict[str, int] = {}
        self.fechas: Dict[str, list] = {}
        self.jugados: Dict[str, int] = {}
        self.jugados_temp: Dict[str, int] = {}
        self.liga = _Media(LIGA_PTS)

    def _equipo(self, e: str, t: int) -> Dict[str, _Media]:
        if e not in self.m:
            self.m[e] = {'margen_aj': _Media(0.0), 'pts_f': _Media(self.liga.v),
                         'pts_c': _Media(self.liga.v), 'casa_aj': _Media(0.0),
                         'tot_casa': _Media(2 * self.liga.v)}
            self.elo[e] = 1500.0
            self.temporada[e] = t
            self.fechas[e] = []
            self.jugados[e] = 0
            self.jugados_temp[e] = 0
        elif self.temporada[e] != t:
            mm = self.m[e]
            mm['margen_aj'].nueva_temporada(0.0, ARRASTRE)
            mm['pts_f'].nueva_temporada(self.liga.v, ARRASTRE)
            mm['pts_c'].nueva_temporada(self.liga.v, ARRASTRE)
            mm['casa_aj'].nueva_temporada(0.0, ARRASTRE_CASA)
            mm['tot_casa'].nueva_temporada(2 * self.liga.v, ARRASTRE)
            self.elo[e] = 1505.0 * ELO_REGRESION + self.elo[e] * (1 - ELO_REGRESION)
            self.temporada[e] = t
            self.jugados_temp[e] = 0
        return self.m[e]

    def _calendario(self, e: str, fecha: pd.Timestamp) -> Dict[str, float]:
        fs = self.fechas.get(e) or []
        if not fs:
            return {'descanso': 3.0, 'b2b': 0.0, 'tres_en_cuatro': 0.0}
        dias = (fecha - fs[-1]).days
        recientes = sum(1 for f in fs[-3:] if (fecha - f).days <= 3)
        return {'descanso': float(min(max(dias - 1, 0), 4)),
                'b2b': float(dias == 1),
                'tres_en_cuatro': float(recientes >= 2)}

    def variables(self, g) -> Dict[str, float]:
        t = int(g['temporada'])
        h, a = g['home'], g['away']
        mh, ma = self._equipo(h, t), self._equipo(a, t)
        f = pd.Timestamp(g['fecha'])
        ch, ca = self._calendario(h, f), self._calendario(a, f)
        v = {'elo_dif': (self.elo[h] - self.elo[a] + ELO_HFA) / 25.0,
             'margen_dif': mh['margen_aj'].v - ma['margen_aj'].v,
             'ataque_dif': (mh['pts_f'].v - mh['pts_c'].v) - (ma['pts_f'].v - ma['pts_c'].v),
             'descanso_dif': ch['descanso'] - ca['descanso'],
             'b2b_h': ch['b2b'], 'b2b_a': ca['b2b'],
             'tres_h': ch['tres_en_cuatro'], 'tres_a': ca['tres_en_cuatro'],
             's_pts': mh['pts_f'].v + mh['pts_c'].v + ma['pts_f'].v + ma['pts_c'].v,
             'liga': self.liga.v,
             'casa_dif': mh['casa_aj'].v - ma['casa_aj'].v,
             'tot_casa': (mh['tot_casa'].v + ma['tot_casa'].v) / 2.0,
             'n_h': self.jugados_temp[h], 'n_a': self.jugados_temp[a],
             'temprano': float(min(self.jugados_temp[h], self.jugados_temp[a]) < 10)}
        return v

    def registrar(self, g) -> None:
        hp, ap = g.get('home_pts'), g.get('away_pts')
        if hp is None or ap is None or hp != hp or ap != ap:
            return
        t = int(g['temporada'])
        h, a = g['home'], g['away']
        mh, ma = self._equipo(h, t), self._equipo(a, t)
        hp, ap = float(hp), float(ap)
        mov = hp - ap
        dif = self.elo[h] - self.elo[a] + ELO_HFA
        esperado = 1.0 / (1.0 + 10 ** (-dif / 400.0))
        real = 1.0 if mov > 0 else 0.0
        gan = dif if mov > 0 else -dif
        mult = ((abs(mov) + 3) ** 0.8) / (7.5 + 0.006 * gan)
        cambio = ELO_K * mult * (real - esperado)
        self.elo[h] += cambio
        self.elo[a] -= cambio
        # margen ajustado por el nivel del rival (antes de este partido),
        # sin la ventaja de campo (~2,5 puntos)
        rh, ra = mh['margen_aj'].v, ma['margen_aj'].v
        mh['margen_aj'].poner(mov - 2.5 + ra, DECAY)
        ma['margen_aj'].poner(-mov + 2.5 + rh, DECAY)
        mh['pts_f'].poner(hp, DECAY)
        mh['pts_c'].poner(ap, DECAY)
        ma['pts_f'].poner(ap, DECAY)
        ma['pts_c'].poner(hp, DECAY)
        # el nivel que la CASA le daba a cada equipo: su hándicap de cierre
        # quitada la ventaja de campo y el nivel (de la casa) del rival
        sp, tl = g.get('spread'), g.get('total_linea')
        if sp is not None and sp == sp:
            ch, ca = mh['casa_aj'].v, ma['casa_aj'].v
            mh['casa_aj'].poner(float(sp) - HCA_CASA + ca, DECAY_CASA)
            ma['casa_aj'].poner(-float(sp) + HCA_CASA + ch, DECAY_CASA)
        if tl is not None and tl == tl:
            mh['tot_casa'].poner(float(tl), DECAY_CASA)
            ma['tot_casa'].poner(float(tl), DECAY_CASA)
        f = pd.Timestamp(g['fecha'])
        for e in (h, a):
            self.fechas[e] = (self.fechas[e] + [f])[-4:]
            self.jugados[e] += 1
            self.jugados_temp[e] += 1
        self.liga.poner((hp + ap) / 2.0, 0.998)

    def nota_fecha(self, e: str, fecha) -> None:
        """Para predecir con el calendario de verdad cuando el partido de ayer
        aún no tiene marcador (no pasa en el histórico)."""
        self.fechas.setdefault(e, [])


def dataset(d: pd.DataFrame):
    """`(filas, estado)`: una fila por partido con sus variables previas y su
    resultado, y el estado tras el último partido jugado."""
    est = Estado()
    filas = []
    for g in d.to_dict('records'):
        v = est.variables(g)
        v.update({k: g.get(k) for k in ('fecha', 'temporada', 'home', 'away',
                                         'home_pts', 'away_pts', 'ml_home',
                                         'ml_away', 'spread', 'total_linea')})
        filas.append(v)
        est.registrar(g)
    out = pd.DataFrame(filas)
    out['margen'] = out['home_pts'] - out['away_pts']
    out['total'] = out['home_pts'] + out['away_pts']
    return out, est


COLS_MARGEN = ['elo_dif', 'margen_dif', 'ataque_dif', 'casa_dif', 'descanso_dif',
               'b2b_h', 'b2b_a', 'tres_h', 'tres_a']
COLS_TOTAL = ['s_pts', 'liga', 'tot_casa', 'b2b_h', 'b2b_a', 'tres_h', 'tres_a',
              'temprano']
