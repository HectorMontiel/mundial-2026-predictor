# -*- coding: utf-8 -*-
"""
v315 — LA BASE PROPIA DE RESULTADOS DE TODAS LAS COMPETICIONES (FOTMOB).

El usuario, después de ver en la aplicación partidos sub-19 y sub-20
«Finalizado · marcador pendiente» y una alerta de datos: «no es que
agreguemos esas estadísticas, sino que tenemos que tener un modelo propio
para cada una de esas ligas y competiciones, porque si no van a pasar este
tipo de errores».

Tiene razón en el fondo: sin una base propia de cada competición no hay con
qué predecir, ni con qué liquidar, ni con qué medir. Este módulo es esa base:
todos los partidos TERMINADOS que FotMob publica, día a día, de todas sus
competiciones (primera división, ascenso, copas, selecciones absolutas y
juveniles, femenil), con el id de FotMob de la liga y de cada equipo.

  · Se guarda en `resultados_fotmob.csv.gz` (en git, comprimido).
  · El precálculo lo pone al día cada pasada: sólo pide los días que faltan
    (1-3 peticiones), así que no cuesta nada.
  · De aquí salen el modelo propio de estas competiciones
    (`modelo_competiciones.py`) y la lista de competiciones que FotMob NO
    cubre: en ésas no hay ni resultado con qué liquidar, así que no se
    recomiendan.

Uso: python resultados_fotmob.py [desde AAAA-MM-DD]   (pone al día la base)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import time
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

FICHERO = 'resultados_fotmob.csv.gz'
DESDE_POR_DEFECTO = dt.date(2025, 7, 1)
COLUMNAS = ['match_id', 'ini', 'liga_id', 'liga', 'pais', 'home_id', 'home',
            'away_id', 'away', 'gh', 'ga']


def _dia(d: dt.date) -> List[dict]:
    """Los partidos terminados de un día UTC de FotMob."""
    import fuente_bajas as fb
    import horario as hz
    doc = None
    for intento in range(3):
        doc = fb._get(fb.FOTMOB_DIA.format(fecha=d.strftime('%Y%m%d')))
        if doc:
            break
        time.sleep(2 + 3 * intento)
    if not doc:
        return None
    filas = []
    for L in doc.get('leagues') or []:
        for m in L.get('matches') or []:
            est = m.get('status') or {}
            h, a = m.get('home') or {}, m.get('away') or {}
            if not est.get('finished') or est.get('cancelled') \
                    or h.get('score') is None or a.get('score') is None:
                continue
            ini = hz._a_utc(est.get('utcTime'))
            if ini is None:
                continue
            filas.append({'match_id': m.get('id'),
                          'ini': ini.strftime('%Y-%m-%d %H:%M:%S'),
                          'liga_id': L.get('primaryId') or L.get('id'),
                          'liga': L.get('name'), 'pais': L.get('ccode'),
                          'home_id': h.get('id'), 'home': h.get('name'),
                          'away_id': a.get('id'), 'away': a.get('name'),
                          'gh': int(h['score']), 'ga': int(a['score'])})
    return filas


_MEM = {}


def cargar(recargar: bool = False) -> pd.DataFrame:
    """La base entera, ordenada por hora. Vacía si no existe."""
    if 'df' in _MEM and not recargar:
        return _MEM['df']
    if os.path.exists(FICHERO):
        df = pd.read_csv(FICHERO, parse_dates=['ini'])
    else:
        df = pd.DataFrame(columns=COLUMNAS)
        df['ini'] = pd.to_datetime(df['ini'])
    df = df.sort_values('ini').reset_index(drop=True)
    _MEM['df'] = df
    return df


def actualizar(desde: Optional[dt.date] = None,
               hasta: Optional[dt.date] = None) -> int:
    """Pide a FotMob los días que faltan y los añade. Devuelve cuántos
    partidos nuevos. Nunca lanza."""
    try:
        df = cargar(recargar=True)
        hoy = dt.datetime.utcnow().date()
        hasta = hasta or hoy
        if desde is None:
            # se repiten los dos últimos días: un partido que acabó de
            # madrugada no estaba en la foto anterior
            desde = (df['ini'].max().date() - dt.timedelta(days=2)
                     if len(df) else DESDE_POR_DEFECTO)
        nuevas, d = [], desde
        while d <= hasta:
            filas = _dia(d)
            if filas is None:
                logger.warning('[resultados] %s sin respuesta de FotMob', d)
            else:
                nuevas += filas
            if (d - desde).days % 20 == 0:
                logger.info('[resultados] %s · %d nuevos', d, len(nuevas))
            d += dt.timedelta(days=1)
        if not nuevas:
            return 0
        nd = pd.DataFrame(nuevas)
        nd['ini'] = pd.to_datetime(nd['ini'])
        antes = len(df)
        todo = pd.concat([df, nd], ignore_index=True)
        todo = todo.drop_duplicates('match_id', keep='last') \
            .sort_values('ini').reset_index(drop=True)
        todo[COLUMNAS].to_csv(FICHERO, index=False, compression='gzip',
                              date_format='%Y-%m-%d %H:%M:%S')
        _MEM['df'] = todo
        logger.info('[resultados] base: %d partidos (+%d)', len(todo),
                    len(todo) - antes)
        return len(todo) - antes
    except Exception as e:
        logger.warning('[resultados] no se pudo actualizar: %s', e)
        return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    d0 = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    print(actualizar(desde=d0))
