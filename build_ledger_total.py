#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Constructor de `pick_ledger_total.csv`.

Por qué hacía falta
-------------------
`pick_ledger_total.csv` es el fichero del que dependen tres cosas críticas:

  · `recalibrate_from_history.py`  → el peso `w` de cada liga
  · `calibracion_confianza.py`     → las bandas de «Máxima Confianza»
  · `validacion_deportes.py`       → QUÉ DEPORTES ENTRAN EN LA CAPA 1

...y sin embargo **ningún script lo escribía**. Se había creado a mano en la
v78 juntando los dos ledgers parciales. Eso significa que el veredicto de la
Capa 1 —la decisión más importante que toma el sistema— colgaba de un fichero
que nadie sabía reproducir, y que se quedaba obsoleto en silencio en cuanto se
reconstruía uno de sus dos orígenes.

De hecho pasó: al reconstruir el ledger de MLB en esta versión,
`pick_ledger_deportes.csv` se quedó SOLO con MLB (el tenis se sobreescribió), y
el total siguió tan campante con los datos viejos, así que los tests seguían
dando por buenos los números de la v78.

Orígenes
--------
  `pick_ledger.csv`           fútbol   (build_pick_ledger.py)
  `pick_ledger_deportes.csv`  tenis y MLB (build_ledger_deportes.py)

El fútbol no trae columna `deporte` porque es el ledger original; se le pone
aquí. Las columnas propias del fútbol (goles, cuotas de over/under) no viajan
al total: los consumidores no las usan y mezclarlas obligaría a rellenar de
nulos los otros deportes.
"""
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

FUTBOL = 'pick_ledger.csv'
DEPORTES = 'pick_ledger_deportes.csv'
SALIDA = 'pick_ledger_total.csv'

COLUMNAS = ['deporte', 'liga', 'match_id', 'fecha', 'pliegue',
            'p_home', 'p_draw', 'p_away', 'resultado',
            'cuota_home', 'cuota_draw', 'cuota_away',
            'pin_home', 'pin_draw', 'pin_away']


def construir(salida: str = SALIDA) -> pd.DataFrame:
    partes = []

    if os.path.exists(FUTBOL):
        f = pd.read_csv(FUTBOL, low_memory=False)
        if 'deporte' not in f.columns:
            f['deporte'] = 'Fútbol'
        partes.append(f)
        logger.info(f'[total] {FUTBOL}: {len(f)} filas')
    else:
        logger.warning(f'[total] falta {FUTBOL}')

    if os.path.exists(DEPORTES):
        d = pd.read_csv(DEPORTES, low_memory=False)
        partes.append(d)
        logger.info(f"[total] {DEPORTES}: {len(d)} filas "
                    f"({d['deporte'].value_counts().to_dict()})")
    else:
        logger.warning(f'[total] falta {DEPORTES}')

    if not partes:
        raise SystemExit('no hay ningún ledger de origen')

    out = pd.concat(partes, ignore_index=True)
    for c in COLUMNAS:
        if c not in out.columns:
            out[c] = None
    out = out[COLUMNAS]

    # Un partido no puede estar dos veces: si estuviera, pesaría doble en la
    # calibración y en el ROI.
    antes = len(out)
    out = out.drop_duplicates(subset=['deporte', 'match_id'], keep='last')
    if len(out) != antes:
        logger.info(f'[total] {antes - len(out)} duplicados descartados')

    # Guardia mínima: un deporte presente en un origen tiene que llegar aquí.
    esperados = set()
    for p in partes:
        esperados |= set(p['deporte'].dropna().unique())
    faltan = esperados - set(out['deporte'].unique())
    if faltan:
        raise SystemExit(f'deportes perdidos al fundir: {faltan}')

    out.to_csv(salida, index=False)
    logger.info(f"[total] {salida}: {len(out)} filas · "
                f"{out['deporte'].value_counts().to_dict()}")
    return out


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    d = construir()
    con_cuota = d['cuota_home'].notna().sum()
    print(f"\n{len(d)} filas · {d['deporte'].value_counts().to_dict()}")
    print(f"con cuota: {con_cuota}")
