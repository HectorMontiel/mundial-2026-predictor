#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v95 — El catálogo de tenis crece solo con los partidos que se van jugando.

El problema
-----------
La app mostraba 182 partidos de tenis como «con cuota, sin modelo propio»: hay
precio de las casas pero los jugadores no están en el catálogo. Medido, el
reparto es muy desigual:

    ATP · histórico unificado   75.004 partidos
        atp_tour                 58.941
        Grand Slams              14.838
        challenger_atp            1.225   ← apenas cubierto
        ITF                           0   ← nada

Y el catálogo del modelo tiene 2.138 jugadores, que son básicamente el circuito
principal. Por eso los challengers e ITF caen fuera.

Qué se puede arreglar y qué no
------------------------------
  · **Challengers: SÍ.** El scoreboard de ESPN los cubre — medido sobre 15
    días: 785 partidos, 13 torneos, entre ellos Iasi, Praga, Memphis y
    VanOpen, con 488 jugadores distintos. Ese material existe y es gratis; lo
    único que faltaba era GUARDARLO. ESPN sólo sirve una ventana reciente, así
    que si no se acumula día a día, se pierde.
  · **ITF: NO.** Ese mismo scoreboard devuelve **0 partidos de ITF**. Sin
    resultados no hay entrenamiento posible, y sin modelo lo único que se podía
    enseñar era la probabilidad implícita del precio — repetirle al usuario lo
    que ya dice la casa. Por eso el ITF se excluye del barrido (ver
    `alpha_finder._cuotas_tenis_multi`) en vez de fingir cobertura.

Este módulo es la mitad que faltaba: guarda cada día los resultados que ESPN
publica, con la misma disciplina que `daily_snapshots` usa para las cuotas —
CSV commiteado, idempotente, sin pisar lo ya guardado. Con eso el histórico de
challengers crece solo y el próximo reentrenamiento amplía el catálogo.

Uso:
    python acumular_tenis.py            # últimos 7 días
    python acumular_tenis.py --dias 15
"""
import argparse
import csv
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

ARCHIVO = 'historico_tenis_espn.csv'
CAMPOS = ('fecha', 'circuito', 'torneo', 'jugador_1', 'jugador_2', 'ganador',
          'sets_1', 'sets_2', 'juegos_totales', 'ingerido')


def _clave(f: dict) -> tuple:
    """Identidad de un partido: dos jugadores y día. Un mismo cruce no se
    repite el mismo día, así que basta para no duplicar."""
    return (f['fecha'], *sorted((f['jugador_1'], f['jugador_2'])))


def _leer(ruta: str = ARCHIVO) -> List[dict]:
    if not os.path.exists(ruta):
        return []
    try:
        with open(ruta, encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))
    except Exception as e:
        logger.warning(f'[tenis/acumular] {ruta} ilegible: {e}')
        return []


def acumular(dias: int = 7, ruta: str = ARCHIVO) -> Dict:
    """Guarda los resultados de ESPN de los últimos `dias`. Idempotente."""
    import pandas as pd

    import fixtures_espn

    hasta = pd.Timestamp.utcnow().tz_localize(None).normalize()
    desde = hasta - pd.Timedelta(days=dias)
    try:
        crudos = fixtures_espn.resultados_tenis(desde.strftime('%Y-%m-%d'),
                                                hasta.strftime('%Y-%m-%d'))
    except Exception as e:
        logger.warning(f'[tenis/acumular] ESPN falló: {type(e).__name__}: {e}')
        return {'nuevos': 0, 'error': f'{type(e).__name__}: {e}'}

    previos = _leer(ruta)
    vistos = {_clave(f) for f in previos if f.get('jugador_1')}
    ahora = pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    nuevos: List[dict] = []
    for r in crudos:
        j1, j2 = r['jugadores']
        sets = r.get('sets') or [None, None]
        fila = {'fecha': r['fecha'], 'circuito': r['circuito'],
                'torneo': r['torneo'], 'jugador_1': j1, 'jugador_2': j2,
                'ganador': r['ganador'],
                'sets_1': sets[0], 'sets_2': sets[1],
                'juegos_totales': r.get('juegos_totales'),
                'ingerido': ahora}
        k = _clave(fila)
        if k in vistos:
            continue
        vistos.add(k)
        nuevos.append(fila)

    if nuevos:
        filas = previos + nuevos
        filas.sort(key=lambda f: (str(f.get('fecha')), str(f.get('torneo'))))
        buf = [','.join(CAMPOS)]
        for f in filas:
            buf.append(','.join(
                '' if f.get(c) is None else
                str(f.get(c)).replace(',', ';').replace('\n', ' ')
                for c in CAMPOS))
        try:
            from io_atomico import escribir_texto
            escribir_texto(ruta, '\n'.join(buf) + '\n')
        except Exception:
            with open(ruta, 'w', encoding='utf-8', newline='') as f:
                f.write('\n'.join(buf) + '\n')

    jugadores = {f['jugador_1'] for f in (previos + nuevos)} | \
                {f['jugador_2'] for f in (previos + nuevos)}
    torneos = {f['torneo'] for f in (previos + nuevos)}
    salida = {'nuevos': len(nuevos), 'total': len(previos) + len(nuevos),
              'jugadores': len(jugadores), 'torneos': len(torneos),
              'ventana': f"{desde:%Y-%m-%d}..{hasta:%Y-%m-%d}"}
    logger.info(f"[tenis/acumular] +{len(nuevos)} partidos "
                f"(total {salida['total']}, {salida['jugadores']} jugadores, "
                f"{salida['torneos']} torneos)")
    return salida


def jugadores_conocidos(ruta: str = ARCHIVO) -> set:
    """Jugadores vistos en el histórico acumulado (para ampliar el catálogo)."""
    filas = _leer(ruta)
    return ({f['jugador_1'] for f in filas if f.get('jugador_1')} |
            {f['jugador_2'] for f in filas if f.get('jugador_2')})


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--dias', type=int, default=7)
    a = ap.parse_args()
    print(json.dumps(acumular(a.dias), ensure_ascii=False, indent=1))
