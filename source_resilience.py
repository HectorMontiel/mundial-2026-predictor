#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cadena de resiliencia de fuentes (v33, principio transversal).

Ejecuta una lista ORDENADA de fuentes hasta que una devuelva datos válidos.
Cada eslabón va en su propio try/except: un fallo se registra y se pasa al
siguiente SIN interrumpir el pipeline. Solo si TODAS fallan se devuelve el
fallo explícito para que el llamador degrade con elegancia (nunca romper la
generación de Apuestas del Día).

Uso:
    cadena = Cadena('resultados MLS', [
        ('football-data', _de_footballdata),
        ('ESPN', _de_espn),
        ('API-Football', _de_apifootball),
    ])
    datos = cadena.obtener(validador=lambda d: d is not None and len(d) > 0)
    if datos is None:
        ...  # todas fallaron: mantener estado anterior + avisar
"""

import logging
import time
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Cadena:
    def __init__(self, nombre: str,
                 fuentes: List[Tuple[str, Callable[[], Any]]],
                 timeout_total: Optional[float] = None):
        self.nombre = nombre
        self.fuentes = fuentes
        self.timeout_total = timeout_total
        self.traza: List[dict] = []

    def obtener(self, validador: Optional[Callable[[Any], bool]] = None) -> Optional[Any]:
        validador = validador or (lambda d: d is not None)
        t0 = time.time()
        for i, (etiqueta, fn) in enumerate(self.fuentes, 1):
            if self.timeout_total and (time.time() - t0) > self.timeout_total:
                self.traza.append({'fuente': etiqueta, 'estado': 'omitida',
                                   'motivo': 'presupuesto de tiempo agotado'})
                continue
            try:
                datos = fn()
                if validador(datos):
                    self.traza.append({'fuente': etiqueta, 'estado': 'ok',
                                       'orden': i})
                    logger.info(f"[resiliencia/{self.nombre}] eslabón {i} "
                                f"({etiqueta}) OK")
                    return datos
                self.traza.append({'fuente': etiqueta, 'estado': 'vacia',
                                   'orden': i})
                logger.warning(f"[resiliencia/{self.nombre}] eslabón {i} "
                               f"({etiqueta}) devolvió datos no válidos")
            except Exception as e:
                self.traza.append({'fuente': etiqueta, 'estado': 'error',
                                   'orden': i, 'detalle': f'{type(e).__name__}: {e}'})
                logger.warning(f"[resiliencia/{self.nombre}] eslabón {i} "
                               f"({etiqueta}) falló: {type(e).__name__}: {e}")
        logger.error(f"[resiliencia/{self.nombre}] TODAS las fuentes fallaron "
                     f"({len(self.fuentes)} eslabones) — se conserva el estado "
                     "anterior")
        return None

    @property
    def fuente_usada(self) -> Optional[str]:
        for t in self.traza:
            if t['estado'] == 'ok':
                return t['fuente']
        return None


# ---------------------------------------------------------------------------
# Cadena concreta: resultados recientes de la MLS (§1.2)
# Orden REAL (corregido tras verificación empírica 2026-07-23): football-data
# va PRIMERO porque es la fuente canónica de entrenamiento del proyecto y
# estaba fresca (4 días); ESPN es el respaldo vivo (verificado: 15 eventos
# con marcador); API-Football cierra la cadena.
# ---------------------------------------------------------------------------
def _mls_footballdata():
    import io

    import pandas as pd
    import requests
    r = requests.get('https://www.football-data.co.uk/new/USA.csv',
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), on_bad_lines='skip')
    df['fecha'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['fecha', 'HG', 'AG'])
    return df.rename(columns={'Home': 'home_team', 'Away': 'away_team',
                              'HG': 'home_goals', 'AG': 'away_goals',
                              'fecha': 'date'})[
        ['date', 'home_team', 'away_team', 'home_goals', 'away_goals']]


def _mls_espn(dias: int = 10):
    import pandas as pd
    import requests
    hoy = pd.Timestamp.today()
    rango = (f"{(hoy - pd.Timedelta(days=dias)).strftime('%Y%m%d')}-"
             f"{hoy.strftime('%Y%m%d')}")
    r = requests.get('https://site.api.espn.com/apis/site/v2/sports/soccer/'
                     'usa.1/scoreboard',
                     params={'dates': rango, 'limit': 200},
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
    r.raise_for_status()
    filas = []
    for ev in r.json().get('events', []):
        if 'FULL_TIME' not in ev['status']['type']['name']:
            continue
        comp = ev['competitions'][0]
        loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
        vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
        filas.append({'date': pd.Timestamp(ev['date'][:10]),
                      'home_team': loc['team']['displayName'],
                      'away_team': vis['team']['displayName'],
                      'home_goals': float(loc['score']),
                      'away_goals': float(vis['score'])})
    return pd.DataFrame(filas)


def _mls_apifootball():
    import pandas as pd
    import api_football_manager as afm
    data = afm.api_call('fixtures', {'league': 253, 'season': 2026},
                        prioridad=3, ttl=6 * 3600)
    filas = []
    for p in (data or {}).get('response', []):
        if p['fixture']['status']['short'] not in ('FT', 'AET', 'PEN'):
            continue
        ft = p['score']['fulltime']
        if ft['home'] is None:
            continue
        filas.append({'date': pd.to_datetime(p['fixture']['date']).tz_localize(None),
                      'home_team': p['teams']['home']['name'],
                      'away_team': p['teams']['away']['name'],
                      'home_goals': float(ft['home']),
                      'away_goals': float(ft['away'])})
    return pd.DataFrame(filas)


def resultados_mls_recientes():
    """Devuelve (DataFrame|None, fuente_usada, traza)."""
    cadena = Cadena('resultados MLS', [
        ('football-data', _mls_footballdata),
        ('ESPN', _mls_espn),
        ('API-Football', _mls_apifootball),
    ])
    datos = cadena.obtener(validador=lambda d: d is not None and len(d) > 0)
    return datos, cadena.fuente_usada, cadena.traza


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    df, fuente, traza = resultados_mls_recientes()
    if df is None:
        print("todas las fuentes fallaron")
    else:
        print(f"fuente usada: {fuente} · {len(df)} partidos · "
              f"último {df['date'].max().date()}")
    for t in traza:
        print(' ', t)
