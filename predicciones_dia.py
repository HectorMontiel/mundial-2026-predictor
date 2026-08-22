#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v153 — LAS PREDICCIONES DEL DÍA, CALCULADAS UNA VEZ AL DÍA Y NO EN CADA ARRANQUE.

El problema, medido
-------------------
El arranque en frío de la aplicación son ~119 s, con este desglose:

    fixtures y cuotas ......  29,8 s
    cargar los modelos .....  50,0 s     ← esto
    predicciones ...........  51,0 s     ← y esto

Los 101 s de abajo son trabajo que produce SIEMPRE EL MISMO RESULTADO durante
todo el día: el 1X2 de un partido sólo cambia cuando el bot reentrena. Pagarlo
en cada arranque de cada usuario es repetir de balde el mismo cálculo.

Este módulo lo hace una vez, en el bot, y deja el resultado en
`predicciones_dia.json`. La aplicación lo lee y se salta las dos fases.

LA CONDICIÓN QUE HABÍA QUE VERIFICAR ANTES, Y SE VERIFICÓ
---------------------------------------------------------
El proyecto tenía esto anotado como pendiente con una advertencia: `predecir`
consulta `odds_actuales.json` para el MESM y para el blend de mercado, así que
si ese fichero existiera en producción, precalcular **congelaría una predicción
viva**. Comprobado:

  · `odds_actuales.json` está en `.gitignore` y el camino que lo escribía se
    retiró en la v91. No existe ni en un clon nuevo ni en el despliegue.
  · La otra vía de red de `predecir` es `_mercado_ficha`, y sólo se llama con
    `anclar=True`. El barrido llama con `prior_elo=False`, o sea `anclar=False`.
  · Comprobado empíricamente cortando el socket: `predecir(prior_elo=False)`
    completa sin tocar la red y devuelve exactamente lo mismo dos veces.

O sea que en el barrido `predecir` ya es una función pura de los pesos y del
histórico. Precalcularla no congela nada que estuviera vivo.

POR QUÉ LA CLAVE LLEVA EL NOMBRE CRUDO DE ESPN
-----------------------------------------------
El objetivo no es ahorrarse la predicción: es ahorrarse **cargar el motor**, que
son 50 de los 101 s. Y el motor es justamente quien sabe traducir «Manchester
City» (como lo escribe ESPN) a «Man City» (como está en el catálogo).

Si la clave usara el nombre mapeado, habría que cargar el motor para poder
buscar en el JSON, y no se ahorraría nada. Por eso se indexa por el nombre TAL
COMO LLEGA DEL FIXTURE, y el registro lleva dentro el nombre ya mapeado para que
la interfaz pueda etiquetar.

LO QUE ESTE FICHERO NO ES
-------------------------
No es una fuente de precios. Sólo lleva probabilidades del modelo. Las cuotas
siguen pidiéndose en vivo en cada arranque, porque ésas SÍ cambian durante el
día y congelarlas sería exactamente el error que este módulo tuvo que descartar
antes de escribirse.

Uso:
    python predicciones_dia.py            # genera predicciones_dia.json
    python predicciones_dia.py --dias 3
"""
import json
import logging
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FICHERO = os.environ.get('PREDICCIONES_DIA', 'predicciones_dia.json')
VERSION = 1

# Cuántas horas puede tener el fichero antes de que se considere caducado.
#
# El bot lo regenera cada madrugada (05:30 UTC). 30 horas deja margen para una
# ejecución que falle sin que la aplicación se quede sin predicciones a media
# tarde, y es lo bastante corto como para que dos días seguidos de fallo se
# noten en vez de servir un fichero de la semana pasada.
HORAS_VALIDO = 30

_MEMO: Dict[str, object] = {'mtime': None, 'datos': None}


# ---------------------------------------------------------------------------
# LECTURA — lo que usa la aplicación
# ---------------------------------------------------------------------------
def clave_partido(clave_liga: str, home_crudo: str, away_crudo: str) -> str:
    """La clave del índice. Nombres crudos del fixture, sin mapear."""
    return '%s|%s|%s' % (clave_liga, str(home_crudo).strip(),
                         str(away_crudo).strip())


def _leer() -> Optional[Dict]:
    """El fichero, memorizado por fecha de modificación. None si no sirve."""
    try:
        mtime = os.path.getmtime(FICHERO)
    except OSError:
        _MEMO['mtime'], _MEMO['datos'] = None, None
        return None
    if _MEMO['mtime'] == mtime:
        return _MEMO['datos']
    try:
        with open(FICHERO, 'r', encoding='utf-8') as f:
            datos = json.load(f)
    except Exception as e:
        logger.warning('[predicciones] %s ilegible: %s', FICHERO, e)
        _MEMO['mtime'], _MEMO['datos'] = mtime, None
        return None
    if int(datos.get('version') or 0) != VERSION:
        logger.warning('[predicciones] versión %s, se esperaba %s: se ignora',
                       datos.get('version'), VERSION)
        datos = None
    _MEMO['mtime'], _MEMO['datos'] = mtime, datos
    return datos


def estado() -> Dict:
    """
    Qué hay en el fichero y si sirve. Para el panel de estado de la aplicación.

    Devuelve siempre las mismas claves, con `usable` como respuesta corta.
    """
    datos = _leer()
    if not datos:
        return {'usable': False, 'motivo': 'no hay fichero de predicciones',
                'n': 0}
    gen = str(datos.get('generado') or '')
    horas = None
    try:
        import pandas as pd
        horas = (pd.Timestamp.now('UTC')
                 - pd.Timestamp(gen)).total_seconds() / 3600.0
    except Exception:
        horas = None
    n = len(datos.get('predicciones') or {})
    if horas is not None and horas > HORAS_VALIDO:
        return {'usable': False, 'n': n, 'generado': gen, 'horas': round(horas, 1),
                'motivo': 'las predicciones tienen %.0f horas y el límite son '
                          '%d: se recalculan en vivo' % (horas, HORAS_VALIDO)}
    return {'usable': bool(n), 'n': n, 'generado': gen,
            'horas': round(horas, 1) if horas is not None else None,
            'ligas': len(datos.get('ligas') or []),
            'motivo': 'predicciones del bot, %d partidos' % n}


def prediccion(clave_liga: str, home_crudo: str, away_crudo: str) -> Optional[Dict]:
    """
    La predicción precalculada de un partido, o None si no está.

    `None` NO es un error: es la señal de que ese partido hay que predecirlo en
    vivo. Un fixture nuevo que apareció después de que el bot corriera cae por
    aquí, y tiene que seguir funcionando.
    """
    e = estado()
    if not e.get('usable'):
        return None
    datos = _leer() or {}
    return (datos.get('predicciones') or {}).get(
        clave_partido(clave_liga, home_crudo, away_crudo))


def ligas_cubiertas() -> set:
    """Competiciones cuyas predicciones están COMPLETAS en el fichero.

    Sólo para esas se puede saltar la carga del motor: si a una liga le falta
    un partido, hay que cargarlo igual y entonces no se ahorra nada."""
    datos = _leer() or {}
    return set(datos.get('ligas_completas') or [])


# ---------------------------------------------------------------------------
# GENERACIÓN — lo que ejecuta el bot
# ---------------------------------------------------------------------------
def _resumen_de(pred: Dict) -> Optional[Dict]:
    """
    Lo que hace falta para RECONSTRUIR el objeto de predicción, no un resumen.

    La primera versión guardaba sólo las tres probabilidades y dos agregados
    (`over25`, `btts`), que es lo que consume `_mercados_modelo`. Se quedó corta
    en cuanto un partido tuvo cuotas: `_mercados_del_partido` necesita la MATRIZ
    de marcadores entera para los hándicaps, las mitades y los totales por
    equipo, y el barrido reventó con un `NoneType is not subscriptable`.

    Así que se guarda la matriz. Son 7×7 —381 bytes por partido, unos 100 KB en
    todo el fichero— y a cambio el camino rápido puede llamar EXACTAMENTE a las
    mismas funciones que el lento en vez de a una copia suya. La equivalencia
    deja de ser algo que haya que mantener a mano y pasa a ser por construcción.
    """
    try:
        import numpy as np
        pr = pred['prediction']['probabilities']
        eg = pred['prediction']['expected_goals']
        M = np.round(np.array(pred['score_matrix'], dtype=float), 6)
        return {
            'probabilities': {k: round(float(pr[k]), 6)
                              for k in ('home', 'draw', 'away')},
            'expected_goals': {'home': round(float(eg['home']), 3),
                               'away': round(float(eg['away']), 3)},
            'score_matrix': M.tolist(),
        }
    except Exception as e:
        logger.debug('[predicciones] resumen: %s', e)
        return None


def como_prediccion(registro: Dict) -> Optional[Dict]:
    """
    Un registro del fichero, con la forma que devuelve `ClubEngine.predecir`.

    Es la pieza que permite que el barrido no tenga dos caminos: con esto, un
    partido precalculado y uno predicho en vivo entran por la misma función.
    """
    if not registro or 'score_matrix' not in registro:
        return None
    return {
        'prediction': {
            'probabilities': registro.get('probabilities') or {},
            'expected_goals': registro.get('expected_goals') or {},
        },
        'score_matrix': registro['score_matrix'],
        'precalculado': True,
    }


def generar(dias: int = 3, salida: str = None) -> Dict:
    """
    Recorre las competiciones disponibles y precalcula sus partidos.

    Usa EXACTAMENTE la misma llamada que el barrido —`predecir(prior_elo=False)`—
    para que la predicción precalculada y la que se calcularía en vivo sean el
    mismo número. Si divergieran, la aplicación enseñaría una cosa distinta
    según hubiera fichero o no, que es peor que no tener fichero.
    """
    import fixtures_espn
    import name_mapper
    from config import LEAGUES
    from league_engine import ClubEngine

    t0 = time.time()
    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    fixtures = fixtures_espn.fixtures_multi(claves, dias=int(dias))
    con_fixtures = [c for c in claves if fixtures.get(c)]
    logger.info('[predicciones] %d competiciones con partidos', len(con_fixtures))

    salida_dict: Dict[str, Dict] = {}
    completas: List[str] = []
    fallos: Dict[str, str] = {}
    for clave in con_fixtures:
        lista = fixtures.get(clave) or []
        try:
            eng = ClubEngine(clave)
        except Exception as e:
            fallos[clave] = '%s: %s' % (type(e).__name__, e)
            continue
        if not getattr(eng, 'listo', False):
            fallos[clave] = str(getattr(eng, 'error', 'motor no listo'))
            continue
        catalogo = list(eng.stats.keys())
        hechos, total = 0, 0
        for fx in lista:
            crudo_h, crudo_a = fx.get('home'), fx.get('away')
            if not crudo_h or not crudo_a:
                continue
            total += 1
            home = name_mapper.mapear(crudo_h, catalogo,
                                      contexto='precalculo→%s' % clave)
            away = name_mapper.mapear(crudo_a, catalogo,
                                      contexto='precalculo→%s' % clave)
            if not (home and away) or home == away:
                continue
            try:
                pred = eng.predecir(home, away, prior_elo=False)
            except Exception as e:
                logger.debug('[predicciones] %s %s-%s: %s', clave, home, away, e)
                continue
            if 'error' in pred:
                continue
            resumen = _resumen_de(pred)
            if not resumen:
                continue
            resumen.update({'home': home, 'away': away, 'clave_liga': clave})
            salida_dict[clave_partido(clave, crudo_h, crudo_a)] = resumen
            hechos += 1
        # «Completa» es lo que autoriza a NO cargar el motor. Si falta un solo
        # partido hay que cargarlo igual para ese, y entonces no se ahorra nada:
        # por eso el criterio es estricto y no «casi todos».
        if total and hechos == total:
            completas.append(clave)
        logger.info('[predicciones] %s: %d de %d', clave, hechos, total)

    import pandas as pd
    doc = {
        'version': VERSION,
        'generado': pd.Timestamp.now('UTC').isoformat(),
        'dias': int(dias),
        'ligas': sorted(con_fixtures),
        'ligas_completas': sorted(completas),
        'fallos': fallos,
        'segundos': round(time.time() - t0, 1),
        'predicciones': salida_dict,
    }
    destino = salida or FICHERO
    with open(destino, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
    logger.info('[predicciones] %d partidos en %s (%.1f s)',
                len(salida_dict), destino, doc['segundos'])
    return doc


def main():
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dias', type=int, default=3)
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()
    doc = generar(dias=args.dias, salida=args.salida)
    print('%d partidos · %d competiciones · %d completas · %.1f s'
          % (len(doc['predicciones']), len(doc['ligas']),
             len(doc['ligas_completas']), doc['segundos']))
    if doc['fallos']:
        print('competiciones sin motor: %s' % ', '.join(sorted(doc['fallos'])))


if __name__ == '__main__':
    main()
