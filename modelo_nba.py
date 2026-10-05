# -*- coding: utf-8 -*-
"""
v330 — EL MODELO DE LA NBA QUE DECIDE EN «APUESTAS DEL DÍA».

El usuario: «las pretemporadas de la NBA van a empezar… haz un modelo para la
NBA muy avanzado y preciso… la validación con simulaciones de partidos
finalizados de las últimas temporadas… y las apuestas de la NBA tienen que
estar ya apareciendo en Apuestas del Día».

QUÉ ES
------
Dos regresiones (margen y total de puntos) sobre el estado de cada equipo
antes de cada partido (`nba_estado`: Elo con margen, rating de margen
ajustado por rival, ataque y defensa, el nivel que le daba la casa en sus
cierres y el calendario: descanso, noches seguidas, tres en cuatro), con el
error de cada una como su campana. Entrenado en `_v330_nba.py --entrenar`
con 19 temporadas (2007-08 → 2025-26, 24.280 partidos, 23.590 con cierre).

LO QUE SE MIDIÓ, SIN MAQUILLAR (`modelos/nba_v330.json` → `medicion`)
--------------------------------------------------------------------
Cada temporada con un modelo que no la vio. Ajustes elegidos con 2010-16 y
juzgados en 2017-18 → 2025-26 (10.707 partidos):

                         log-loss   acierto
    modelo solo           0,6187    65,8 %
    cierre de la casa     0,6027    67,4 %
    90 % casa + 10 % mod  0,6027    67,4 %

La casa de la NBA es MUY fina: sabe las bajas del día y el modelo no. Se
probó de todo para pasarla —afinar el Elo y las medias (curva plana), árboles
LightGBM (0,6236, peor), corregir sesgos de la casa con calendario y modelo
(mejora ≤ 0 con p5 negativo) y buscar ventaja en el más/menos y el hándicap
cuando el modelo discrepa de la línea (50,4 % y 51,3 %: nada)— y no se pudo.
Lo honesto es lo que hace la app: decidir con 90 % casa y 10 % modelo
(`concordancia.PESO_MODELO_NBA`), que es lo que mejor promete lo que cumple:

    «meter» (≥ 65 %) en 2017-26: promete 76,0 %, acierta 75,6 % (5.792)
    más/menos con líneas alternativas, por banda: dentro de ±1,5 puntos

LA PRETEMPORADA NO SE MIDE. No hay un solo partido de pretemporada en el
histórico de cierres y los titulares juegan poco: sus tarjetas salen con la
nota y nunca «para meter».
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

ARTEFACTO = 'modelos/nba_v330.json'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
TIPO_TEMPORADA = {1: 'pretemporada', 2: 'regular', 3: 'playoffs', 5: 'play-in'}
NOTA_PRETEMPORADA = ('⚠️ Pretemporada: los titulares juegan poco y el '
                     'resultado no describe al equipo. No se mide ni se '
                     'recomienda: sólo informa.')

_MEM: Dict[str, tuple] = {}


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class NBAModelo:
    def __init__(self, art: Dict, estado):
        self.art = art
        self.estado = estado
        self.sigma_margen = float(art['sigma_margen'])
        self.sigma_total = float(art['sigma_total'])
        self.medicion = art.get('medicion') or {}

    # ------------------------------------------------------------------
    @classmethod
    def cargar(cls, ruta: str = ARTEFACTO) -> Optional['NBAModelo']:
        """El modelo con el estado de los equipos tras el último partido
        jugado. `None` si falta el artefacto o el histórico. Se memoriza por
        fecha de modificación de los ficheros (recorrer 24.000 partidos cuesta
        ~2 s y el barrido lo pide una vez)."""
        import nba_estado as ne
        import nba_historico as nh
        if not os.path.exists(ruta) or not os.path.exists(nh.SALIDA):
            return None
        firma = tuple(os.path.getmtime(f) if os.path.exists(f) else 0
                      for f in (ruta, nh.SALIDA, 'historico_nba.csv'))
        hit = _MEM.get('modelo')
        if hit and hit[0] == firma:
            return hit[1]
        with open(ruta, encoding='utf-8') as f:
            art = json.load(f)
        d = nh.cargar()
        if d is None or d.empty:
            return None
        _, est = ne.dataset(d)
        m = cls(art, est)
        _MEM['modelo'] = (firma, m)
        return m

    # ------------------------------------------------------------------
    def _lineal(self, nombre: str, v: Dict) -> float:
        c = self.art[nombre]
        x = np.array([float(v[k]) for k in c['cols']])
        z = (x - np.array(c['mu'])) / np.array(c['sd'])
        return float(c['b0'] + z @ np.array(c['b']))

    def predecir_partido(self, home, away, fecha=None,
                         tipo: str = 'regular') -> Dict:
        import pandas as pd
        import nba_historico as nh
        h, a = nh.codigo(home), nh.codigo(away)
        if not h or not a or h == a:
            return {'error': 'equipo de la NBA no reconocido: %s / %s' % (home, away)}
        f = pd.Timestamp(str(fecha)[:10]) if fecha else pd.Timestamp.now('UTC').tz_localize(None).normalize()
        # copia: `variables` pasa a los equipos de temporada y no debe tocar
        # el estado compartido entre partidos del mismo barrido
        est = copy.deepcopy(self.estado)
        v = est.variables({'temporada': nh._temporada(f), 'home': h,
                           'away': a, 'fecha': f})
        margen = self._lineal('margen', v)
        total = self._lineal('total', v)
        ph = _phi(margen / self.sigma_margen)
        return {'home': h, 'away': a, 'tipo': tipo,
                'margen_esperado': round(margen, 1),
                'total_esperado': round(total, 1),
                'pts_home_esperado': int(round((total + margen) / 2.0)),
                'pts_away_esperado': int(round((total - margen) / 2.0)),
                'prob_home_sin_empate': round(ph, 4),
                'prob_away_sin_empate': round(1.0 - ph, 4),
                'sigma_margen': self.sigma_margen,
                'sigma_total': self.sigma_total,
                'pretemporada': tipo == 'pretemporada'}

    def prob_mas(self, total_esperado: float, linea: float) -> float:
        return 1.0 - _phi((float(linea) - float(total_esperado)) / self.sigma_total)

    def totales(self, pred: Dict, lineas=None) -> Dict:
        """El bloque `totales` de la tarjeta (forma de `totales_deporte`):
        las líneas de la casa si las hay; si no, tres alrededor del total
        esperado."""
        import totales_deporte as td
        t = pred.get('total_esperado')
        if t is None:
            return {}
        ls = sorted({float(x) for x in (lineas or [])}) or \
            td.lineas_alrededor(t, 4.0, 3)
        campos = [{'id': 'total_over_%g' % L,
                   'etiqueta': 'Más de %g puntos' % L,
                   'valor': round(self.prob_mas(t, L) * 100, 2), 'tipo': 'pct'}
                  for L in ls]
        return td.de_plantilla({'campos': campos}, 'NBA')


# ---------------------------------------------------------------------------
# El calendario: ESPN (con el tipo de partido: pretemporada, regular…)
# ---------------------------------------------------------------------------
def fixtures_nba(dias: int = 2) -> List[Dict]:
    """Los partidos de hoy a `dias` vista, sin los terminados. Cada uno con
    `home`/`away` (nombre largo), `abrev_*` (código de tres letras), `inicio`
    UTC y `tipo`. Los rivales que no son de la NBA (los clubes de fuera que
    juegan la pretemporada) se quedan fuera: el modelo no los conoce."""
    import pandas as pd
    import requests
    import nba_historico as nh
    ck = 'fx:%d' % dias
    hit = _MEM.get(ck)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    rango = '%s-%s' % (hoy.strftime('%Y%m%d'),
                       (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d'))
    salida: List[Dict] = []
    try:
        r = requests.get(ESPN, params={'dates': rango, 'limit': 300},
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        j = r.json() if r.status_code == 200 else {}
    except Exception as e:
        logger.info('[nba] ESPN sin respuesta: %s', e)
        j = {}
    for ev in (j.get('events') or []):
        try:
            comp = (ev.get('competitions') or [{}])[0]
            estado = ((comp.get('status') or ev.get('status') or {}).get('type') or {})
            if estado.get('completed'):
                continue
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            nh_, na_ = loc['team']['displayName'], vis['team']['displayName']
            ch, ca = nh.codigo(nh_), nh.codigo(na_)
            if not ch or not ca:
                continue
            f = pd.to_datetime(ev['date'])
            if f.tzinfo:
                f = f.tz_convert(None)
            tipo = TIPO_TEMPORADA.get(int((ev.get('season') or {}).get('type') or 2),
                                      'regular')
            salida.append({'fecha': f.strftime('%Y-%m-%d'),
                           'inicio': f.strftime('%Y-%m-%d %H:%M:%S'),
                           'home': nh_, 'away': na_,
                           'abrev_home': ch, 'abrev_away': ca,
                           'tipo': tipo, 'neutral': bool(comp.get('neutralSite'))})
        except Exception:
            continue
    _MEM[ck] = (time.time(), salida)
    logger.info('[nba] %d próximos partidos (ESPN, %d días)', len(salida), dias)
    return salida


def tipo_por_fecha(fecha) -> str:
    """Para las fuentes que no dicen el tipo (las casas): la temporada
    regular de la NBA nunca ha empezado antes del 16 de octubre, y lo de
    octubre antes de esa fecha es pretemporada."""
    s = str(fecha or '')[:10]
    try:
        m, d = int(s[5:7]), int(s[8:10])
    except ValueError:
        return 'regular'
    return 'pretemporada' if (m == 10 and d < 16) else 'regular'
