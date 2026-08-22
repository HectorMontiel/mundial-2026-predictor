#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v159 — FOTOS DIARIAS DE LAS LÍNEAS DE CÓRNERS.

Por qué existe
--------------
La probabilidad de córners de este proyecto ya está calibrada: 0,0043 de error
para el total y 0,0056 por equipo, contra la frecuencia real (§10.8 y §10.9 de
la bitácora). Con eso se puede calcular un EV frente a la cuota de la casa.

Lo que NO se puede es saber si ese EV gana dinero, y no por falta de modelo:
**no existe histórico de líneas de córners**. football-data no las publica y el
histórico de The Odds API es de pago. Sin líneas pasadas no hay apuestas que
liquidar, así que la regla de oro del proyecto —percentil 5 positivo en el tramo
de juicio— no se puede ni aplicar a este mercado. Por eso su EV sale marcado.

Este módulo empieza a construir ese histórico. Una foto al día por partido y
línea; en unos meses habrá con qué medir si el EV que calculamos gana, y
entonces —y sólo entonces— podrá dejar de estar marcado.

LO MISMO QUE `daily_snapshots`, Y POR QUÉ NO VA ALLÍ
----------------------------------------------------
Aquel guarda 1X2, over/under 2.5, ambos marcan y hándicap en una tabla con esas
columnas fijas. Los córners no caben ahí: son varias familias (total, por
equipo, hándicap, par/impar) con líneas que cambian de partido a partido. Meterlos
obligaría a ensanchar un esquema que hoy funciona, así que van a su propio CSV,
con una fila por (partido, mercado, línea, día).

NUNCA SE PISA UNA FOTO ANTERIOR
-------------------------------
Cada día es una fila nueva. Eso es lo que permite reconstruir el movimiento de
la línea, que es la mitad del valor de esto: no sólo qué pagaba la casa, sino
cómo se movió hasta el pitido inicial. Una segunda ejecución el mismo día no
duplica (la clave es partido+mercado+línea+día).

Uso:
    python snapshots_corners.py
    python snapshots_corners.py --liga premier
"""
import argparse
import logging
import os
import time
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger('snapshots_corners')

FICHERO = os.environ.get('CORNERS_SNAPSHOTS', 'corners_snapshots.csv')
COLUMNAS = ['snapshot_key', 'capturado_en', 'clave_liga', 'fecha_partido',
            'home', 'away', 'casa', 'familia', 'mercado', 'linea', 'cuota',
            'dias_al_partido']


def _hoy() -> str:
    return pd.Timestamp.now('UTC').strftime('%Y-%m-%d')


def _es_corner(texto: str) -> bool:
    t = str(texto or '').lower()
    return 'córner' in t or 'corner' in t or 'esquina' in t


def _linea_de(etiqueta: str) -> Optional[float]:
    """El número de la línea que aparece en la etiqueta del mercado."""
    import re
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(etiqueta or ''))
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', '.'))
    except ValueError:
        return None


def lineas_de_corners(deporte: str, home: str, away: str) -> List[Dict]:
    """
    Todas las líneas de córners que cotiza la casa para este partido.

    Se filtra por el NOMBRE de la familia y no por una lista de mercados
    conocidos: la casa renombra y añade familias cada temporada, y una lista
    fija dejaría de capturar en silencio justo lo que se quiere acumular.
    """
    try:
        import cuotas_multi as cm
        tablero = cm.mercados_playdoit(deporte, home, away) or {}
    except Exception as e:
        logger.debug('[corners/snap] tablero %s-%s: %s', home, away, e)
        return []
    # `mercados` es una LISTA de familias, cada una con sus `selecciones`:
    #   [{'tipo': 18, 'nombre': 'Total de tiros de esquina', 'sv': '9.5',
    #     'selecciones': [{'nombre': 'Más de 9.5', 'cuota': 1.85}, ...]}]
    filas = []
    for fam in (tablero.get('mercados') or []):
        if not isinstance(fam, dict):
            continue
        nombre_fam = str(fam.get('nombre') or '')
        if not _es_corner(nombre_fam):
            continue
        # LA LÍNEA SALE DE LA ETIQUETA, NO DE `sv`. Medido sobre el tablero
        # real: la familia «Total Tiros De Esquina» llega con sv=9.5 y su
        # selección dice «Más de 8.5». Lo que define la apuesta —y lo que hay
        # que liquidar después— es la etiqueta que ve el usuario; guardar 9,5
        # cuando se apuesta 8,5 haría inservible todo el histórico que esto
        # existe para acumular. `sv` queda de respaldo para cuando la etiqueta
        # no lleve número.
        linea_fam = _linea_de(fam.get('sv'))
        for sel in (fam.get('selecciones') or []):
            if not isinstance(sel, dict):
                continue
            etq = str(sel.get('nombre') or '')
            try:
                cuota = float(sel.get('cuota'))
            except (TypeError, ValueError):
                continue
            if cuota <= 1.0:
                continue
            linea_etq = _linea_de(etq)
            filas.append({
                'familia': nombre_fam, 'mercado': etq,
                'linea': linea_etq if linea_etq is not None else linea_fam,
                'cuota': round(cuota, 3)})
    return filas


def _existentes() -> set:
    if not os.path.exists(FICHERO):
        return set()
    try:
        d = pd.read_csv(FICHERO, usecols=['snapshot_key'])
        return set(d['snapshot_key'].astype(str))
    except Exception:
        return set()


def capturar(dias: int = 2, solo: Optional[str] = None) -> Dict:
    """
    Recorre los partidos próximos de las competiciones CON córners observados y
    guarda lo que cotice la casa.

    Sólo esas 20: en las demás no hay con qué comparar después, así que guardar
    su línea sería acumular un dato que nunca se podrá liquidar contra un
    resultado observado.
    """
    import fixtures_espn
    from config import LEAGUES

    try:
        import rendimiento_equipos as rq
    except Exception as e:
        logger.error('sin rendimiento_equipos: %s', e)
        return {'filas': 0}

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    if solo:
        claves = [c for c in claves if c == solo]
    claves = [c for c in claves
              if (rq.stats_disponibles(c) or {}).get('corners')]
    logger.info('competiciones con córners observados: %d', len(claves))

    fixtures = fixtures_espn.fixtures_multi(claves, dias=dias)
    vistos = _existentes()
    hoy, ahora = _hoy(), pd.Timestamp.now('UTC').isoformat()
    nuevas, partidos, t0 = [], 0, time.time()

    for clave in claves:
        for fx in (fixtures.get(clave) or []):
            h, a = fx.get('home'), fx.get('away')
            if not h or not a:
                continue
            partidos += 1
            for fila in lineas_de_corners('futbol', h, a):
                # Las familias de RANGO («0-5», «6-8») no tienen línea de
                # medio punto y se guardan igual: la etiqueta identifica la
                # apuesta, que es lo que hace falta para liquidarla. Descartar
                # lo que no encaja en un molde de Más/Menos tiraría la mitad
                # del tablero de córners.
                clave_snap = '%s|%s|%s|%s|%s|%s' % (
                    clave, h, a, fila['familia'], fila['mercado'], hoy)
                if clave_snap in vistos:
                    continue
                vistos.add(clave_snap)
                try:
                    d_al = int((pd.Timestamp(fx.get('fecha')).normalize()
                                - pd.Timestamp(hoy)).days)
                except Exception:
                    d_al = None
                nuevas.append({
                    'snapshot_key': clave_snap, 'capturado_en': ahora,
                    'clave_liga': clave,
                    'fecha_partido': str(fx.get('fecha') or '')[:10],
                    'home': h, 'away': a, 'casa': 'playdoit',
                    'familia': fila['familia'], 'mercado': fila['mercado'],
                    'linea': fila['linea'], 'cuota': fila['cuota'],
                    'dias_al_partido': d_al})

    if nuevas:
        df = pd.DataFrame(nuevas, columns=COLUMNAS)
        cabecera = not os.path.exists(FICHERO)
        df.to_csv(FICHERO, mode='a', header=cabecera, index=False,
                  encoding='utf-8')
    logger.info('%d filas nuevas de %d partidos en %.0f s',
                len(nuevas), partidos, time.time() - t0)
    return {'filas': len(nuevas), 'partidos': partidos,
            'competiciones': len(claves),
            'segundos': round(time.time() - t0, 1)}


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--liga', default=None)
    ap.add_argument('--dias', type=int, default=2)
    args = ap.parse_args()
    r = capturar(dias=args.dias, solo=args.liga)
    print('%d filas nuevas · %d partidos · %d competiciones · %.0f s'
          % (r.get('filas', 0), r.get('partidos', 0),
             r.get('competiciones', 0), r.get('segundos', 0)))
    if os.path.exists(FICHERO):
        try:
            total = len(pd.read_csv(FICHERO, usecols=['snapshot_key']))
            print('acumulado en %s: %d filas' % (FICHERO, total))
        except Exception:
            pass


if __name__ == '__main__':
    main()
