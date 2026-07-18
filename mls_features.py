#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Features específicas de la MLS (v25): geografía continental + clima extremo.

La MLS es la liga con mayores distancias de viaje del proyecto (~4,500 km
costa a costa, 3 husos horarios) y veranos brutales (Houston/Miami/Austin).

  * ALT_SEDE_MLS   — altitud de la sede (Denver 1,580 m, Salt Lake 1,330 m).
  * DIST_VIAJE_MLS — km haversine entre sedes habituales (normalizado /4000).
  * DIFF_HUSO      — husos horarios que cruza el visitante (±3 → /3).
  * CLIMA_EXTREMO  — 1 si tmax > 30 °C Y humedad media > 60 % el día del
    partido en la ciudad del local (spec v25 §1.3). Histórico: caché
    Open-Meteo (clima.backfill); futuro: forecast Open-Meteo con memo.
    Sin dato → 0 (neutro) — la cobertura del backfill es 2023+ y las
    ventanas walk-forward caen dentro; documentado.

Validación: run_wf_mls_v25.py (A/B de 3 variantes contra la config base).
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COLS_MLS_GEO = ['ALT_SEDE_MLS', 'DIST_VIAJE_MLS', 'DIFF_HUSO']
COLS_MLS_CLIMA = ['CLIMA_EXTREMO']
COLS_MLS = COLS_MLS_GEO + COLS_MLS_CLIMA

UMBRAL_TEMP = 30.0      # °C
UMBRAL_HUMEDAD = 60.0   # %

# club -> (ciudad para Open-Meteo, país, lat, lon, altitud m, huso vs ET)
GEO_MLS = {
    'Atlanta Utd': ('Atlanta', 'USA', 33.755, -84.400, 320, 0),
    'Austin FC': ('Austin', 'USA', 30.388, -97.719, 150, -1),
    'CF Montreal': ('Montreal', 'Canada', 45.563, -73.552, 30, 0),
    'Charlotte': ('Charlotte', 'USA', 35.226, -80.853, 230, 0),
    'Chicago Fire': ('Chicago', 'USA', 41.862, -87.617, 180, -1),
    'Colorado Rapids': ('Denver', 'USA', 39.806, -104.892, 1580, -2),
    'Columbus Crew': ('Columbus', 'USA', 39.968, -83.017, 240, 0),
    'DC United': ('Washington', 'USA', 38.868, -77.012, 10, 0),
    'FC Cincinnati': ('Cincinnati', 'USA', 39.111, -84.522, 150, 0),
    'FC Dallas': ('Dallas', 'USA', 33.154, -96.835, 210, -1),
    'Houston Dynamo': ('Houston', 'USA', 29.752, -95.352, 15, -1),
    'Inter Miami': ('Fort Lauderdale', 'USA', 26.193, -80.161, 3, 0),
    'Los Angeles FC': ('Los Angeles', 'USA', 34.012, -118.284, 70, -3),
    'Los Angeles Galaxy': ('Carson', 'USA', 33.864, -118.261, 15, -3),
    'Minnesota United': ('Saint Paul', 'USA', 44.953, -93.165, 260, -1),
    'Nashville SC': ('Nashville', 'USA', 36.130, -86.766, 120, -1),
    'New England Revolution': ('Foxborough', 'USA', 42.091, -71.264, 90, 0),
    'New York City': ('New York', 'USA', 40.830, -73.926, 10, 0),
    'New York Red Bulls': ('Newark', 'USA', 40.737, -74.150, 10, 0),
    'Orlando City': ('Orlando', 'USA', 28.541, -81.389, 30, 0),
    'Philadelphia Union': ('Chester', 'USA', 39.832, -75.379, 5, 0),
    'Portland Timbers': ('Portland', 'USA', 45.521, -122.692, 15, -3),
    'Real Salt Lake': ('Sandy', 'USA', 40.583, -111.893, 1330, -2),
    'San Diego FC': ('San Diego', 'USA', 32.783, -117.120, 150, -3),
    'San Jose Earthquakes': ('San Jose', 'USA', 37.351, -121.925, 25, -3),
    'Seattle Sounders': ('Seattle', 'USA', 47.595, -122.332, 10, -3),
    'Sporting Kansas City': ('Kansas City', 'USA', 39.122, -94.824, 260, -1),
    'St. Louis City': ('Saint Louis', 'USA', 38.631, -90.211, 140, -1),
    'Toronto FC': ('Toronto', 'Canada', 43.633, -79.419, 80, 0),
    'Vancouver Whitecaps': ('Vancouver', 'Canada', 49.277, -123.112, 5, -3),
}
_DEFECTO = ('Kansas City', 'USA', 39.0, -95.0, 200, -1)   # centro del país


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = np.radians(lat2 - lat1), np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * 6371.0 * np.arcsin(np.sqrt(a)))


def _geo(equipo: str):
    return GEO_MLS.get(equipo, _DEFECTO)


def _clima_extremo(ciudad: str, pais: str, fecha) -> Optional[float]:
    """1/0 desde la caché histórica; None si no hay dato (→ imputa 0)."""
    import clima
    d = clima.obtener_clima(ciudad, pais, str(pd.Timestamp(fecha).date()))
    if not d or d.get('tmax') is None or d.get('humedad') is None:
        return None
    return 1.0 if (d['tmax'] > UMBRAL_TEMP and d['humedad'] > UMBRAL_HUMEDAD) else 0.0


def fila_geo(home: str, away: str) -> Dict[str, float]:
    gh, ga = _geo(home), _geo(away)
    return {
        'ALT_SEDE_MLS': gh[4] / 1600.0,
        'DIST_VIAJE_MLS': _haversine_km(gh[2], gh[3], ga[2], ga[3]) / 4000.0,
        'DIFF_HUSO': (gh[5] - ga[5]) / 3.0,
    }


def features_mls(df: pd.DataFrame) -> pd.DataFrame:
    """Features por MATCH_ID para entrenamiento (clima desde la caché)."""
    filas = []
    con_clima = 0
    for f in df.itertuples(index=False):
        gh = _geo(f.home_team)
        fila = {'MATCH_ID': f.MATCH_ID, **fila_geo(f.home_team, f.away_team)}
        ce = _clima_extremo(gh[0], gh[1], f.date)
        fila['CLIMA_EXTREMO'] = 0.0 if ce is None else ce
        con_clima += ce is not None
        filas.append(fila)
    logger.info(f"[mls] features geo+clima: {len(filas)} partidos, "
                f"clima con dato en {con_clima} ({con_clima/max(len(filas),1)*100:.0f} %)")
    return pd.DataFrame(filas).set_index('MATCH_ID')


_memo_forecast: Dict = {}


def fila_inferencia(home: str, away: str, fecha=None) -> Dict[str, float]:
    """Mismas features en vivo: clima por forecast Open-Meteo (memoizado)."""
    import clima
    fecha = pd.Timestamp(fecha) if fecha is not None else \
        pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    valores = fila_geo(home, away)
    gh = _geo(home)
    k = (gh[0], str(fecha.date()))
    if k not in _memo_forecast:
        try:
            _memo_forecast[k] = clima.obtener_clima_futuro(gh[0], gh[1],
                                                           str(fecha.date()))
        except Exception:
            _memo_forecast[k] = None
    d = _memo_forecast[k]
    if d and d.get('tmax') is not None and d.get('humedad') is not None:
        valores['CLIMA_EXTREMO'] = 1.0 if (d['tmax'] > UMBRAL_TEMP
                                           and d['humedad'] > UMBRAL_HUMEDAD) else 0.0
    else:
        valores['CLIMA_EXTREMO'] = 0.0
    return valores


def backfill_clima_mls(desde: str = '2023-01-01') -> Dict:
    """Backfill histórico Open-Meteo para las ciudades MLS (spec §1.3):
    3 temporadas, una llamada de archivo por ciudad (patrón v23)."""
    import clima
    df = pd.read_csv('historico_mls.csv', parse_dates=['date'])
    df = df[df['date'] >= desde]
    geo = df['home_team'].map(lambda t: _geo(t))
    plan = pd.DataFrame({'date': df['date'],
                         'city': geo.map(lambda g: g[0]),
                         'country': geo.map(lambda g: g[1])})
    return clima.backfill(plan)


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    desde = sys.argv[1] if len(sys.argv) > 1 else '2023-01-01'
    print(json.dumps(backfill_clima_mls(desde), indent=2))
