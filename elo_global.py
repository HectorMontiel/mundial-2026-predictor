#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v105 — ELO cross-competición: un equipo, un número, aunque juegue en cinco sitios.

El problema, con números
------------------------
El ELO se calcula POR COMPETICIÓN, y en una copa eliminatoria eso no converge
nunca. En el histórico de la Conference League, **68 de 135 equipos tienen 8
partidos o menos** y la mediana son 8. El Vikingur Reykjavik tenía ELO 1501,4 y
el Nordsjælland 1510,7 —el valor de arranque, 1500, prácticamente sin mover—,
así que el modelo los veía iguales y repartía 46 %/54 % mientras el mercado
pagaba 9,50 (10,5 % implícito).

Tres piezas, y por qué cada una
-------------------------------
**1. Un solo ELO por equipo, sobre TODAS las competiciones.** Un club no cambia
de fuerza al pasar de su liga a la copa. Medido: 113 de los 135 equipos de la
Conference aparecen en alguna otra competición del repositorio, y el Vikingur
pasa de 8 partidos a 14.

**2. Unificación de nombres CON comprobación de país.** El mapeo difuso sube la
cobertura del 30 % al 78 %, pero mete errores graves: «AEK Larnaca» (Chipre)
casaba con «AEK» (Atenas), y «Anorthosis» con «NOR». Aquí sólo se funden dos
nombres si además de parecerse comparten país inferido. El país sale de
`sede_pais` en sus partidos como LOCAL, que es la sede de su estadio.

**3. Encogimiento hacia la media del país, no hacia 1500.** Un club islandés con
tres partidos no es «media europea»: es «islandés desconocido». Arrancar en la
media de su país es un prior mucho mejor que el valor neutro, y es lo que
separa al Vikingur del Nordsjælland antes de que ninguno haya jugado.

    ELO_efectivo = w·ELO_propio + (1−w)·ELO_pais,   w = n/(n+K)

Todo con pase cronológico: la fila i sólo ve partidos anteriores a i, y la media
del país se calcula con lo que se sabía en ese momento.

Este módulo NO decide nada: produce la columna. Si mejora o no es una pregunta
empírica que contesta `_v105_ab_elo_global.py`.
"""

import logging
import os
import unicodedata
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ELO_INICIAL = 1500.0
ELO_K = 20.0
VENTAJA_LOCAL = 60.0
ESCALA = 400.0
# Con K partidos propios el equipo pesa la mitad que la media de su país.
# 12 es del orden de una temporada de copa: por debajo de eso el país manda.
K_ENCOGIMIENTO = 12
# Umbral de similitud para fundir dos nombres. Más exigente que el 0,78 de
# `name_mapper` porque aquí un falso positivo fusiona dos clubes distintos en
# uno y contamina su historial entero, no sólo un partido.
UMBRAL_FUSION = 0.88

COPAS = {'champions', 'europa_league', 'conference_league', 'libertadores',
         'sudamericana', 'afc_champions', 'leagues_cup', 'eng_fa_cup',
         'eng_carabao', 'esp_copa_rey', 'bra_copa', 'mundial'}


def _norm(s: str) -> str:
    n = unicodedata.normalize('NFKD', str(s))
    n = ''.join(c for c in n if not unicodedata.combining(c)).lower()
    for ch in ".,'-/()":
        n = n.replace(ch, ' ')
    return ' '.join(n.split())


def cargar_partidos() -> pd.DataFrame:
    """Todos los partidos de fútbol del repositorio, en un solo flujo."""
    trozos = []
    for f in sorted(os.listdir('.')):
        if not (f.startswith('historico_') and f.endswith('.csv')):
            continue
        clave = f[len('historico_'):-4]
        try:
            d = pd.read_csv(f, low_memory=False)
        except Exception:
            continue
        if not {'date', 'home_team', 'away_team', 'home_goals',
                'away_goals'}.issubset(d.columns):
            continue
        cols = ['date', 'home_team', 'away_team', 'home_goals', 'away_goals']
        if 'MATCH_ID' in d.columns:
            cols.append('MATCH_ID')
        if 'sede_pais' in d.columns:
            cols.append('sede_pais')
        s = d[cols].copy()
        s['competicion'] = clave
        s['es_copa'] = clave in COPAS
        trozos.append(s)
    t = pd.concat(trozos, ignore_index=True)
    # `format='mixed'` NO es cosmético. Sin él, pandas infiere UN formato del
    # primer valor no nulo y convierte a NaT todo lo que no encaje: los
    # históricos de ESPN traen «2024-03-06 19:00:00» y los de football-data
    # «2023-08-11», así que al concatenar se perdían 37 de las 66 competiciones
    # enteras —Premier, LaLiga, Liga MX, MLS…— y el ELO se construía sólo con
    # las copas. Se detectó porque salían 29 competiciones donde debían salir 66.
    t['fecha'] = pd.to_datetime(t['date'], errors='coerce', format='mixed')
    t = t.dropna(subset=['fecha', 'home_team', 'away_team',
                         'home_goals', 'away_goals'])
    return t.sort_values('fecha', kind='stable').reset_index(drop=True)


def inferir_pais(t: pd.DataFrame) -> Dict[str, str]:
    """
    País de cada equipo, por la sede de sus partidos como LOCAL.

    Se exige MAYORÍA (más de la mitad de sus locales en el mismo país) porque
    hay clubes que juegan en campo neutral temporadas enteras: el Maccabi
    Tel-Aviv aparece con sede en Serbia, y darle ese país lo metería en el
    grupo equivocado. Sin mayoría clara se deja sin país, y entonces el
    encogimiento cae a la media global — que es peor prior, pero honesto.
    """
    if 'sede_pais' not in t.columns:
        return {}
    d = t.dropna(subset=['sede_pais'])
    if d.empty:
        return {}
    cuenta: Dict[str, Dict[str, int]] = {}
    for eq, pais in zip(d['home_team'].astype(str),
                        d['sede_pais'].astype(str)):
        cuenta.setdefault(eq, {})
        cuenta[eq][pais] = cuenta[eq].get(pais, 0) + 1
    out = {}
    for eq, c in cuenta.items():
        total = sum(c.values())
        mejor, n = max(c.items(), key=lambda kv: kv[1])
        if total >= 2 and n > total / 2:
            out[eq] = mejor
    return out


def unificar_nombres(equipos: List[str], pais: Dict[str, str]) -> Dict[str, str]:
    """
    Mapa nombre → nombre canónico, fundiendo variantes del MISMO club.

    Dos nombres se funden si se parecen por encima de `UMBRAL_FUSION` **y**
    comparten país inferido (o uno de los dos no lo tiene). Sin la condición de
    país, «AEK Larnaca» y «AEK» se fusionarían siendo clubes de Chipre y Grecia.
    """
    from difflib import SequenceMatcher
    canon: Dict[str, str] = {}
    # se procesa de más frecuente a menos para que el canónico sea el nombre
    # mayoritario, no el primero alfabético
    for eq in equipos:
        n = _norm(eq)
        mejor, mejor_r = None, 0.0
        for otro, c in canon.items():
            if _norm(otro) == n:
                mejor, mejor_r = c, 1.0
                break
            r = SequenceMatcher(None, n, _norm(otro)).ratio()
            if r > mejor_r:
                mejor, mejor_r = c, r
        if mejor is not None and mejor_r >= UMBRAL_FUSION:
            pa, pb = pais.get(eq), pais.get(mejor)
            if pa is None or pb is None or pa == pb:
                canon[eq] = mejor
                continue
        canon[eq] = eq
    return canon


def elo_global(t: pd.DataFrame, k_encogimiento: int = K_ENCOGIMIENTO
               ) -> pd.DataFrame:
    """
    ELO pre-partido de los dos lados, cronológico y compartido entre
    competiciones, encogido hacia la media del país cuando hay poco historial.
    """
    pais = inferir_pais(t)
    frec = pd.concat([t['home_team'], t['away_team']]).astype(str).value_counts()
    canon = unificar_nombres(list(frec.index), pais)
    n_fusiones = sum(1 for k, v in canon.items() if k != v)
    logger.info(f'[elo_global] {len(frec)} nombres · {n_fusiones} fusionados '
                f'· {len(pais)} con país inferido')

    home = t['home_team'].astype(str).map(canon).to_numpy()
    away = t['away_team'].astype(str).map(canon).to_numpy()
    pais_c = {canon.get(k, k): v for k, v in pais.items()}
    gl = pd.to_numeric(t['home_goals'], errors='coerce').to_numpy(dtype=float)
    gv = pd.to_numeric(t['away_goals'], errors='coerce').to_numpy(dtype=float)
    res = np.where(gl > gv, 1.0, np.where(gl == gv, 0.5, 0.0))

    elo: Dict[str, float] = {}
    partidos: Dict[str, int] = {}
    # media del país, acumulada cronológicamente
    suma_pais: Dict[str, float] = {}
    n_pais: Dict[str, int] = {}
    ea = np.full(len(t), ELO_INICIAL)
    eb = np.full(len(t), ELO_INICIAL)

    def _efectivo(eq: str) -> float:
        n = partidos.get(eq, 0)
        propio = elo.get(eq, ELO_INICIAL)
        p = pais_c.get(eq)
        if p and n_pais.get(p, 0) >= 5:
            ancla = suma_pais[p] / n_pais[p]
        else:
            ancla = ELO_INICIAL
        w = n / (n + k_encogimiento)
        return w * propio + (1 - w) * ancla

    for i in range(len(t)):
        h, a = home[i], away[i]
        ea[i], eb[i] = _efectivo(h), _efectivo(a)
        if np.isnan(res[i]):
            continue
        esp = 1.0 / (1.0 + 10 ** ((eb[i] - (ea[i] + VENTAJA_LOCAL)) / ESCALA))
        aj = ELO_K * (res[i] - esp)
        elo[h] = elo.get(h, ELO_INICIAL) + aj
        elo[a] = elo.get(a, ELO_INICIAL) - aj
        partidos[h] = partidos.get(h, 0) + 1
        partidos[a] = partidos.get(a, 0) + 1
        for eq in (h, a):
            p = pais_c.get(eq)
            if p:
                suma_pais[p] = suma_pais.get(p, 0.0) + elo[eq]
                n_pais[p] = n_pais.get(p, 0) + 1

    out = pd.DataFrame({
        'ELO_G_HOME': ea, 'ELO_G_AWAY': eb,
        'DIFF_ELO_G': (ea - eb) / ESCALA,
        'N_HOME': [partidos.get(h, 0) for h in home],
        'N_AWAY': [partidos.get(a, 0) for a in away],
    }, index=t.index)
    if 'MATCH_ID' in t.columns:
        out['MATCH_ID'] = t['MATCH_ID'].to_numpy()
    return out


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    t = cargar_partidos()
    print(f'{len(t)} partidos · {t.competicion.nunique()} competiciones')
    g = elo_global(t)
    j = t.join(g.drop(columns=['MATCH_ID'], errors='ignore'))
    for eq in ('Vikingur Reykjavik', 'FC Nordsjaelland', 'Nordsjaelland'):
        s = j[(j.home_team == eq) | (j.away_team == eq)].tail(1)
        if len(s):
            r = s.iloc[0]
            e = r.ELO_G_HOME if r.home_team == eq else r.ELO_G_AWAY
            n = r.N_HOME if r.home_team == eq else r.N_AWAY
            print(f'  {eq:24} ELO global {e:7.1f} · {int(n)} partidos')
