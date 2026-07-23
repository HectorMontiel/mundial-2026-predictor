#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CDI — Índice de Desincronización Circadiana aplicado al FÚTBOL (v35 §3).

En la NBA el CDI mejoró el log-loss (v30); en MLB se descartó. En fútbol
faltaba el histórico de SEDES para poder calcularlo: v35 lo resuelve con
`sedes_futbol.csv`, que el scraper de ESPN (uefa_scraper) rellena sin
peticiones adicionales, y con las tablas geográficas ya existentes de MLS y
Liga MX.

Dos formulaciones, ambas sin fuga (pase cronológico):

  CDI_SEDE  = husoLocal − husoVisitante   (definición literal del spec §3.2:
              el desfase entre el huso de la sede y el huso "de casa" del
              visitante; positivo = el visitante viaja hacia el este).
  CDI_VIAJE = husoSede − husoDeLaSedeAnterior del visitante (formulación v30
              adoptada en la NBA: lo que cuenta es el salto REAL desde donde
              jugó su último partido, si fue hace ≤ 10 días).

Ambas se normalizan a [-1, 1] dividiendo por 6 husos (máximo realista en
competición europea: Lisboa 0 → Almaty +6).
"""

import json
import logging
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COLS_CDI = ['CDI_SEDE', 'CDI_VIAJE']
MAPA_FILE = 'timezones_futbol.json'
SEDES_FILE = 'sedes_futbol.csv'
MAX_DIAS_VIAJE = 10          # más de 10 días ⇒ el visitante ya se readaptó
ESCALA = 6.0                 # husos máximos realistas en las competiciones UEFA

# Huso estándar (sin DST: la señal es la DIFERENCIA, robusta al horario de
# verano porque en Europa cambia a la vez en casi todos los países).
TZ_PAIS: Dict[str, int] = {
    'Portugal': 0, 'England': 0, 'Scotland': 0, 'Wales': 0,
    'Northern Ireland': 0, 'Ireland': 0, 'Iceland': 0, 'Faroe Islands': 0,
    'Spain': 1, 'France': 1, 'Germany': 1, 'Italy': 1, 'Netherlands': 1,
    'Belgium': 1, 'Switzerland': 1, 'Austria': 1, 'Denmark': 1, 'Norway': 1,
    'Sweden': 1, 'Poland': 1, 'Czech Republic': 1, 'Czechia': 1,
    'Slovakia': 1, 'Hungary': 1, 'Slovenia': 1, 'Croatia': 1,
    'Bosnia and Herzegovina': 1, 'Serbia': 1, 'Montenegro': 1,
    'North Macedonia': 1, 'Macedonia': 1, 'Albania': 1, 'Kosovo': 1,
    'Luxembourg': 1, 'Malta': 1, 'Andorra': 1, 'Gibraltar': 1,
    'San Marino': 1, 'Monaco': 1, 'Liechtenstein': 1,
    'Finland': 2, 'Estonia': 2, 'Latvia': 2, 'Lithuania': 2, 'Ukraine': 2,
    'Romania': 2, 'Bulgaria': 2, 'Greece': 2, 'Moldova': 2, 'Cyprus': 2,
    'Israel': 2, 'Egypt': 2, 'South Africa': 2,
    'Turkey': 3, 'Türkiye': 3, 'Russia': 3, 'Belarus': 3, 'Qatar': 3, 'Saudi Arabia': 3,
    'Georgia': 4, 'Armenia': 4, 'Azerbaijan': 4, 'United Arab Emirates': 4,
    'Kazakhstan': 6, 'Uzbekistan': 5,
    'United States': -5, 'USA': -5, 'Canada': -5, 'Mexico': -6,
    'Brazil': -3, 'Argentina': -3,
}

# Ciudades que NO siguen el huso "por defecto" de su país (países anchos).
TZ_CIUDAD: Dict[str, int] = {
    # España insular / Portugal atlántico
    'Las Palmas': 0, 'Santa Cruz de Tenerife': 0, 'Funchal': 0,
    'Ponta Delgada': -1,
    # Rusia y Kazajistán
    'Yekaterinburg': 5, 'Kazan': 3, 'Samara': 4, 'Rostov-on-Don': 3,
    'Krasnodar': 3, 'Almaty': 6, 'Astana': 6, 'Nur-Sultan': 6,
}


def tz_de_sede(ciudad: Optional[str], pais: Optional[str]) -> Optional[int]:
    if ciudad and str(ciudad) in TZ_CIUDAD:
        return TZ_CIUDAD[str(ciudad)]
    if pais and str(pais) in TZ_PAIS:
        return TZ_PAIS[str(pais)]
    return None


def _tz_por_longitud(lon: float) -> int:
    return int(round(float(lon) / 15.0))


def mapa_tz_liga(clave: str, df: pd.DataFrame) -> Dict[str, int]:
    """Club → huso de SU sede. Tres vías, por orden de fiabilidad:
      1. sedes_futbol.csv (sede real observada, competiciones UEFA);
      2. tablas geográficas del proyecto (MLS con su delta horario, Liga MX
         por longitud — su único club fuera del centro es Tijuana);
      3. país de la liga (huso constante ⇒ CDI ≡ 0, que es la verdad).
    """
    mapa: Dict[str, int] = {}
    if os.path.exists(SEDES_FILE):
        sedes = pd.read_csv(SEDES_FILE)
        sedes['tz'] = [tz_de_sede(c, p) for c, p in
                       zip(sedes['sede_ciudad'], sedes['sede_pais'])]
        sedes = sedes.dropna(subset=['tz'])
        for equipo, grupo in sedes.groupby('home_team'):
            moda = grupo['tz'].mode()
            if len(moda):
                mapa[str(equipo)] = int(moda.iloc[0])
    if clave == 'mls':
        import mls_features
        # el 6º campo es el delta respecto al Este (0/-1/-2) → huso absoluto
        for equipo, geo in mls_features.GEO_MLS.items():
            mapa[equipo] = -5 + int(geo[5])
    elif clave == 'liga_mx':
        import league_engine
        for equipo, geo in league_engine.GEO_MX.items():
            mapa[equipo] = _tz_por_longitud(geo[2])
    equipos = set(df['home_team']) | set(df['away_team'])
    # Champions se entrena con los nombres canónicos de API-Football
    # ('Bayern München') y las sedes vienen con los de ESPN ('Bayern
    # Munich'): se reconcilian con el mapeador central (v34).
    if mapa and any(e not in mapa for e in equipos):
        import name_mapper
        catalogo = list(mapa.keys())
        for e in equipos:
            if e in mapa:
                continue
            hit = name_mapper.mapear(e, catalogo, contexto=f'cdi/{clave}')
            if hit:
                mapa[e] = mapa[hit]
    faltan = [e for e in equipos if e not in mapa]
    if faltan:
        logger.info(f"[cdi/{clave}] {len(faltan)} equipos sin sede conocida "
                    f"(CDI neutro para ellos): {faltan[:5]}")
    return mapa


def features_cdi(df: pd.DataFrame, mapa_tz: Dict[str, int]) -> pd.DataFrame:
    """CDI por MATCH_ID en un pase cronológico (sin fuga)."""
    sede_por_partido = {}
    if os.path.exists(SEDES_FILE):
        s = pd.read_csv(SEDES_FILE, parse_dates=['date'])
        for f in s.itertuples(index=False):
            tz = tz_de_sede(f.sede_ciudad, f.sede_pais)
            if tz is not None:
                sede_por_partido[(pd.Timestamp(f.date).date(),
                                  f.home_team, f.away_team)] = tz

    ultimo: Dict[str, tuple] = {}          # equipo → (fecha, huso donde jugó)
    filas = []
    for f in df.itertuples(index=False):
        tz_local = sede_por_partido.get((pd.Timestamp(f.date).date(),
                                         f.home_team, f.away_team))
        if tz_local is None:
            tz_local = mapa_tz.get(f.home_team)
        tz_visit = mapa_tz.get(f.away_team)

        cdi_sede = 0.0
        if tz_local is not None and tz_visit is not None:
            cdi_sede = float(np.clip(tz_local - tz_visit, -ESCALA, ESCALA)) / ESCALA

        cdi_viaje = 0.0
        prev = ultimo.get(f.away_team)
        if prev and tz_local is not None:
            dias = (pd.Timestamp(f.date) - prev[0]).days
            if 0 <= dias <= MAX_DIAS_VIAJE:
                cdi_viaje = float(np.clip(tz_local - prev[1],
                                          -ESCALA, ESCALA)) / ESCALA
        filas.append({'MATCH_ID': f.MATCH_ID,
                      'CDI_SEDE': cdi_sede, 'CDI_VIAJE': cdi_viaje})

        if tz_local is not None:
            ultimo[f.home_team] = (pd.Timestamp(f.date), tz_local)
            ultimo[f.away_team] = (pd.Timestamp(f.date), tz_local)
    return pd.DataFrame(filas).set_index('MATCH_ID')


def guardar_mapa(mapas: Dict[str, Dict[str, int]], ruta: str = MAPA_FILE) -> None:
    previo = {}
    if os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as fh:
            previo = json.load(fh)
    previo.update({k: {e: int(t) for e, t in v.items()} for k, v in mapas.items()})
    with open(ruta, 'w', encoding='utf-8') as fh:
        json.dump(previo, fh, ensure_ascii=False, indent=1, sort_keys=True)


def vector_cdi(mapa_tz: Optional[Dict[str, int]], home: str, away: str) -> Dict[str, float]:
    """Inferencia: solo CDI_SEDE es computable sin conocer el partido previo
    del visitante (CDI_VIAJE queda neutro, como en el entrenamiento cuando no
    hay antecedente reciente)."""
    mapa_tz = mapa_tz or {}
    th, ta = mapa_tz.get(home), mapa_tz.get(away)
    cdi = 0.0
    if th is not None and ta is not None:
        cdi = float(np.clip(th - ta, -ESCALA, ESCALA)) / ESCALA
    return {'CDI_SEDE': cdi, 'CDI_VIAJE': 0.0}
