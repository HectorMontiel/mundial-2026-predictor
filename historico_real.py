# -*- coding: utf-8 -*-
"""
v319 — EL HISTÓRICO REAL DE CADA EQUIPO, O NADA.

El usuario, después de perder dos apuestas de córners (Gales–Noruega y
Grecia–Países Bajos):

  «El modelo usa una media genérica de la competición para córners cuando la
   liga no publica estadísticas por equipo, marcándolo como [estimado]. Ese
   dato es ruido disfrazado de información… Prefiero tener cero picks de
   córners en un día donde no hay datos reales». Y: «quiero que valides igual
   tarjetas, goles por equipo… todas las estadísticas: no quiero nada con
   estimado».

LA REGLA (la del usuario)
Un equipo tiene HISTÓRICO REAL de una estadística en una competición si jugó
ahí al menos 5 partidos con esa estadística OBSERVADA (no sintética) en la
temporada en curso. Si cualquiera de los dos equipos no llega, ese mercado no
existe para ese partido: ni número, ni apuesta, ni estimado; sólo
«🚫 SIN HISTÓRICO REAL».

Los promedios que se enseñan van con el papel correcto: el local, lo que saca
EN CASA; el visitante, lo que saca FUERA (cada uno con su número de partidos).

QUÉ ES «TEMPORADA EN CURSO»
  · ligas: desde la última pausa de más de 35 días del calendario de esa
    competición (la misma regla que `patrones_liga`);
  · copas continentales: los últimos 365 días (la fase de grupos de una
    temporada no llega a 5 partidos en casa y sus equipos no tienen «pausa»);
  · selecciones: los últimos 730 días (no tienen temporada).

QUÉ ES «OBSERVADA»: la columna no es reproducible con el generador sintético
(`rendimiento_equipos.stats_disponibles`) y la fila lleva su marca de origen
cuando la competición mezcla (`rendimiento_equipos._solo_reales`).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MIN_PARTIDOS = 5
PAUSA_TEMPORADA = 35
COPAS = {'champions', 'europa_league', 'conference_league', 'libertadores',
         'sudamericana', 'leagues_cup', 'afc_champions', 'bra_copa',
         'eng_fa_cup', 'eng_carabao', 'esp_copa_rey'}
SELECCIONES = {'selecciones'}
# estadística → (sufijo de columna, nombre en `stats_disponibles`)
STATS = {'corners': ('corners', 'corners'), 'tarjetas': ('yellow', 'tarjetas'),
         'remates': ('shots_on', 'remates')}
_MEMO: Dict = {}
# las simulaciones de días pasados fijan aquí su fecha (ver
# `_v310_replay_semana.Recorte.fijar`); en vivo es «ahora»
FECHA = None


def _ventana(clave: str, d, fecha):
    """Las filas de la temporada en curso de esa competición, antes de `fecha`."""
    import pandas as pd
    d = d[d['date'] < fecha]
    if d.empty:
        return d
    if clave in SELECCIONES:
        return d[d['date'] >= fecha - pd.Timedelta(days=730)]
    if clave in COPAS:
        return d[d['date'] >= fecha - pd.Timedelta(days=365)]
    fechas = d['date'].sort_values()
    saltos = fechas.diff() > pd.Timedelta(days=PAUSA_TEMPORADA)
    if saltos.any():
        inicio = fechas[saltos].iloc[-1]
        d = d[d['date'] >= inicio]
    # y si la última fecha ya queda muy atrás, la temporada terminó
    if (fecha - fechas.iloc[-1]).days > PAUSA_TEMPORADA:
        return d.iloc[0:0]
    return d


def _filas(clave: str, stat: str, fecha):
    import pandas as pd
    import rendimiento_equipos as rq
    suf, nombre = STATS[stat]
    if not (rq.stats_disponibles(clave) or {}).get(nombre):
        return None
    d = rq._solo_reales(rq._historico(clave), suf)
    if d is None or getattr(d, 'empty', True) or 'home_' + suf not in d.columns:
        return None
    d = d[d['home_' + suf].notna() & d['away_' + suf].notna()].copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    return _ventana(clave, d.dropna(subset=['date']), fecha)


def evaluar(clave: str, home: str, away: str, stat: str = 'corners',
            fecha=None) -> Dict:
    """{'ok', 'n_local', 'n_visita', 'n_local_casa', 'n_visita_fuera',
    'prom_local_casa', 'prom_visita_fuera', 'motivo'}. Nunca lanza."""
    import pandas as pd
    if fecha is None:
        fecha = FECHA
    fecha = pd.Timestamp(fecha) if fecha is not None else pd.Timestamp.now()
    clave_memo = (clave, home, away, stat, str(fecha.date()))
    if clave_memo in _MEMO:
        return _MEMO[clave_memo]
    out = {'ok': False, 'n_local': 0, 'n_visita': 0, 'n_local_casa': 0,
           'n_visita_fuera': 0, 'prom_local_casa': None,
           'prom_visita_fuera': None, 'motivo': ''}
    try:
        d = _filas(clave, stat, fecha)
        if d is None:
            out['motivo'] = 'la competición no publica %s reales' % stat
        else:
            suf = STATS[stat][0]
            jh = d[(d['home_team'] == home) | (d['away_team'] == home)]
            ja = d[(d['home_team'] == away) | (d['away_team'] == away)]
            casa = d[d['home_team'] == home]
            fuera = d[d['away_team'] == away]
            out.update(n_local=int(len(jh)), n_visita=int(len(ja)),
                       n_local_casa=int(len(casa)), n_visita_fuera=int(len(fuera)))
            if len(casa):
                out['prom_local_casa'] = round(float(casa['home_' + suf].mean()), 2)
            if len(fuera):
                out['prom_visita_fuera'] = round(float(fuera['away_' + suf].mean()), 2)
            out['ok'] = len(jh) >= MIN_PARTIDOS and len(ja) >= MIN_PARTIDOS
            if not out['ok']:
                out['motivo'] = ('%s lleva %d y %s %d partidos con %s reales esta '
                                 'temporada (mínimo %d)'
                                 % (home, len(jh), away, len(ja), stat, MIN_PARTIDOS))
    except Exception as e:
        logger.debug('[historico_real] %s %s-%s %s: %s', clave, home, away, stat, e)
        out['motivo'] = 'no se pudo leer el histórico'
    if len(_MEMO) > 5000:
        _MEMO.clear()
    _MEMO[clave_memo] = out
    return out


def aviso(clave: str, home: str, away: str, stat: str = 'corners') -> str:
    """La línea que se enseña cuando no hay histórico real."""
    nombre = {'corners': 'córners', 'tarjetas': 'tarjetas',
              'remates': 'remates'}.get(stat, stat)
    e = evaluar(clave, home, away, stat)
    return '🚫 SIN HISTÓRICO REAL — %s no apostables%s' % (
        nombre, (' (%s)' % e['motivo']) if e.get('motivo') else '')
