# -*- coding: utf-8 -*-
"""
v273 — ¿Hay un ancla de reserva donde Pinnacle no llega?

EL PROBLEMA, EN UNA LÍNEA
Un pick de Capa 1 necesita DOS precios: el de referencia (cuánto vale de
verdad) y el de tu casa. Si falta cualquiera de los dos, no hay pick aunque el
valor esté ahí. Y el que falta casi siempre es el de referencia:

    partidos del tablero .................... 277
    con ancla de Pinnacle .................... 97   (35 %)
    picks de Capa 1 que salen .................  7   (7,2 % de los anclados)

Los otros 180 no se miran siquiera. No es que no tengan valor: es que no hay
con qué compararlos.

LO QUE SE DESCUBRIÓ, Y CÓMO
El endpoint de cuotas que el proyecto ya usa (`cuotas_mx`, el comparador de
Flashscore) acepta un `bookmakerId`. Usábamos cinco. Barriendo los ids del 1 al
1.300 sobre partidos reales contestaron **293 casas**, con el MISMO `eventId`
—o sea, sin emparejar por nombre, que es lo que hoy pierde la mayor parte del
tablero— y por la misma puerta, sin infraestructura nueva.

PINNACLE NO ESTÁ ENTRE ELLAS. Se comprobó por huella: se buscó un partido
presente a la vez en el comparador y en la API propia de Pinnacle, se pidieron
las tres cuotas a los 1.300 ids y NINGUNO coincide con sus precios. Queda
cerrado.

LO QUE SÍ HAY (medido sobre 137 partidos de fútbol, 3.014 peticiones)

    id     cobertura   margen   desviación   error vs Pinnacle
    1187      91 %      7,98 %     1,16 %        0,23 pp
    1207      46 %      9,99 %     2,24 %        0,21 pp
    575       87 %      7,09 %     4,10 %        0,82 pp
    925       99 %      8,01 %     2,30 %        1,10 pp
    44        60 %      2,77 %    15,21 %        1,37 pp   ← DESCARTADA

EL ID 44 ESTÁ DESCARTADO Y CONVIENE QUE SE SEPA POR QUÉ. Su margen mediano es
del 2,77 %, que parecería lo más sharp del tablón, pero su DESVIACIÓN es del
15,21 %. Ninguna casa real se comporta así: es un agregado o una columna
compuesta («mejor cuota del mercado» o similar). Usarla de ancla habría hecho
que todo saliera sin valor y la Capa 1 se habría quedado en cero para siempre.
Es exactamente el tipo de error que parece una mejora.

POR QUÉ ESTE MÓDULO NO DECIDE NADA TODAVÍA
Ese «error vs Pinnacle» está calculado sobre DOCE partidos, que es la muestra
que había. Con doce no se decide. Y hay una razón teórica para desconfiar: un
libro con 8 % de margen no lo reparte a partes iguales entre los tres
resultados, así que su probabilidad sin margen puede pegarse a la de Pinnacle
en partidos equilibrados y desviarse justo donde importa.

Así que esto ACUMULA, que es lo que funcionó con el radar. Cada barrido guarda
el precio de las candidatas junto al de Pinnacle cuando lo hay, y la medición
se hace sola cuando la muestra llega. Hasta entonces `activo` es `False` y
producción se comporta exactamente como hoy.

LAS DOS PUERTAS, Y NO SE ABRE CON UNA SOLA
  1. que la probabilidad sin margen se pegue a la de Pinnacle  (semanas)
  2. que los picks generados con esa ancla HAYAN GANADO         (meses)

La segunda es la que manda. La primera sola no enciende nada: parecerse a
Pinnacle no es lo mismo que ganar dinero.

DÓNDE NO SE METE ESTO, A PROPÓSITO
Las candidatas NO entran en `cuotas_mx.json`. Si entraran, aparecerían en el
cálculo de «mejor cuota» y podrían inflar el EV con precios que el usuario no
puede tomar. La regla del proyecto (v77) es que el EV se calcula sobre precio
ACCIONABLE, y eso no se relaja por conveniencia.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import os
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

FICHERO = 'anclas_capturas.csv'
META = 'anclas.json'
TABLERO = 'cuotas_mx.json'

# Las cuatro que sobrevivieron a la criba: buena cobertura, margen ESTABLE y
# el menor error contra Pinnacle en la muestra que había. El 44 no está, y el
# encabezado explica por qué.
CANDIDATAS = (1187, 1207, 575, 925)

CAMPOS = ['fecha', 'capturado', 'event_id', 'deporte', 'liga', 'home', 'away',
          'inicio', 'casa_id', 'c_home', 'c_draw', 'c_away',
          'pin_home', 'pin_draw', 'pin_away']

# Cuántos pares (candidata + Pinnacle en el mismo partido) hacen falta antes
# de que la medición signifique algo. Con 12 el error medido fue de 0,23 pp y
# no quiere decir nada. 400 son unas dos o tres semanas de barridos.
MIN_PARES = 400

# Cuánto puede alejarse la probabilidad sin margen de la de Pinnacle para que
# la candidata siga sirviendo de sustituta. Un punto porcentual sobre una
# probabilidad de 0,50 es un 2 % de error relativo: por encima de eso, el EV
# calculado con esa ancla deja de ser comparable al que ya está validado.
ERROR_MAXIMO_PP = 1.0

_VISTOS: Optional[Set[Tuple[str, str, int]]] = None


def _clave(fecha: str, event_id: str, casa_id: int) -> Tuple[str, str, int]:
    return (fecha, str(event_id), int(casa_id))


def _cargar_vistos() -> Set[Tuple[str, str, int]]:
    """Lo ya anotado, para no repetir. Nunca lanza."""
    global _VISTOS
    if _VISTOS is not None:
        return _VISTOS
    vistos: Set[Tuple[str, str, int]] = set()
    try:
        if os.path.exists(FICHERO):
            with io.open(FICHERO, encoding='utf-8', newline='') as f:
                for fila in csv.DictReader(f):
                    try:
                        vistos.add(_clave(fila.get('fecha') or '',
                                          fila.get('event_id') or '',
                                          int(fila.get('casa_id') or 0)))
                    except (TypeError, ValueError):
                        continue
    except Exception as e:
        logger.warning('[anclas] no se pudo leer %s: %s', FICHERO, e)
    _VISTOS = vistos
    return _VISTOS


def olvidar() -> None:
    global _VISTOS
    _VISTOS = None


def _probabilidades(h, d, a) -> Optional[Dict]:
    """Las tres cuotas sin el margen, o None si no se puede."""
    try:
        h, d, a = float(h), float(d), float(a)
    except (TypeError, ValueError):
        return None
    if not (h > 1 and d > 1 and a > 1):
        return None
    s = 1.0 / h + 1.0 / d + 1.0 / a
    return {'home': (1.0 / h) / s, 'draw': (1.0 / d) / s,
            'away': (1.0 / a) / s, 'margen': s - 1.0}


def _pedir(sesion, url, cabeceras, event_id: str, casa_id: int):
    """Las tres cuotas de una casa para un partido. Nunca lanza."""
    try:
        r = sesion.get(url, headers=cabeceras,
                       params={'_hash': 'ope2', 'eventId': event_id,
                               'bookmakerId': casa_id,
                               'betType': 'HOME_DRAW_AWAY',
                               'betScope': 'FULL_TIME'}, timeout=15)
        if r.status_code != 200:
            return None
        n = (((r.json().get('data') or {})
              .get('findPrematchOddsForBookmaker')) or {})
        h = (n.get('home') or {}).get('value')
        d = (n.get('draw') or {}).get('value')
        a = (n.get('away') or {}).get('value')
        if h and d and a:
            return (float(h), float(d), float(a))
    except Exception as e:
        logger.debug('[anclas] %s/%s: %s', event_id, casa_id, e)
    return None


def capturar(ruta: str = TABLERO, max_partidos: int = 400) -> Dict:
    """Anota el precio de las candidatas para el tablero de hoy. NUNCA lanza.

    Va DESPUÉS del barrido de cuotas, en el mismo workflow: el tablero ya está
    escrito y los identificadores de evento son los mismos, así que no hay que
    emparejar por nombre.
    """
    fuera = {'partidos': 0, 'filas': 0, 'con_pinnacle': 0}
    try:
        import requests
        from concurrent.futures import ThreadPoolExecutor

        import cuotas_mx as mx
        if not os.path.exists(ruta):
            logger.warning('[anclas] sin %s', ruta)
            return fuera
        with io.open(ruta, encoding='utf-8') as f:
            doc = json.load(f) or {}
        partidos = [(k, v) for k, v in (doc.get('partidos') or {}).items()
                    if isinstance(v, dict) and v.get('deporte') == 'futbol'
                    and v.get('home') and v.get('away')][:max_partidos]
        if not partidos:
            return fuera
        fuera['partidos'] = len(partidos)

        # Pinnacle, cuando lo haya: es la referencia contra la que se juzgará
        pin = {}
        try:
            import cuotas_multi as cm
            idx = cm._indice('futbol') or {}
            for eid, v in partidos:
                clave = '%s|%s' % (cm.normalizar(v.get('home') or ''),
                                   cm.normalizar(v.get('away') or ''))
                c = (idx.get(clave) or {}).get('cuotas') or {}
                if c.get('home') and c.get('draw') and c.get('away'):
                    pin[eid] = (c['home'], c['draw'], c['away'])
        except Exception as e:
            logger.warning('[anclas] sin ancla de Pinnacle: %s', e)
        fuera['con_pinnacle'] = len(pin)

        hoy = dt.date.today().isoformat()
        ahora = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        vistos = _cargar_vistos()
        tareas = [(eid, v, b) for eid, v in partidos for b in CANDIDATAS
                  if _clave(hoy, eid, b) not in vistos]
        if not tareas:
            logger.info('[anclas] todo anotado ya hoy')
            return fuera

        ses = requests.Session()
        # el pool por defecto es de 10 y aquí van 12 hilos: sin esto, requests
        # descarta conexiones y las rehace, que es latencia regalada
        _ad = requests.adapters.HTTPAdapter(pool_connections=16,
                                            pool_maxsize=16)
        ses.mount('https://', _ad)
        ses.mount('http://', _ad)

        def _una(t):
            eid, v, b = t
            return (eid, v, b, _pedir(ses, mx.ODDS, mx.CABEZ, eid, b))

        nuevas = []
        with ThreadPoolExecutor(max_workers=12) as pool:
            for eid, v, b, cu in pool.map(_una, tareas):
                if not cu:
                    continue
                p = pin.get(eid) or (None, None, None)
                nuevas.append({
                    'fecha': hoy, 'capturado': ahora, 'event_id': eid,
                    'deporte': v.get('deporte') or '',
                    'liga': v.get('liga') or '',
                    'home': v.get('home') or '', 'away': v.get('away') or '',
                    'inicio': v.get('inicio') or '', 'casa_id': b,
                    'c_home': cu[0], 'c_draw': cu[1], 'c_away': cu[2],
                    'pin_home': p[0] or '', 'pin_draw': p[1] or '',
                    'pin_away': p[2] or ''})
                vistos.add(_clave(hoy, eid, b))

        if nuevas:
            nuevo = not os.path.exists(FICHERO)
            with io.open(FICHERO, 'a', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=CAMPOS,
                                   extrasaction='ignore')
                if nuevo:
                    w.writeheader()
                w.writerows(nuevas)
        fuera['filas'] = len(nuevas)
    except Exception as e:
        logger.warning('[anclas] la captura fallo: %s: %s',
                       type(e).__name__, e)
    return fuera


def medir(ruta_meta: str = META) -> Dict:
    """¿Sirve alguna candidata de ancla? Se contesta sola cuando hay muestra.

    Mientras no haya `MIN_PARES` partidos con candidata Y Pinnacle a la vez,
    esto no decide nada y lo dice. Es la misma puerta que el radar: no se
    publica lo que no se ha podido medir.
    """
    doc = {'activo': False, 'generado': dt.datetime.now(
        dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'casas': {}}
    try:
        import statistics
        if not os.path.exists(FICHERO):
            doc['motivo'] = 'todavia no hay capturas'
            _guardar(doc, ruta_meta)
            return doc
        por_casa: Dict[int, List[float]] = {}
        margenes: Dict[int, List[float]] = {}
        cobertura: Dict[int, Set[str]] = {}
        with io.open(FICHERO, encoding='utf-8', newline='') as f:
            for fila in csv.DictReader(f):
                try:
                    b = int(fila.get('casa_id') or 0)
                except (TypeError, ValueError):
                    continue
                q = _probabilidades(fila.get('c_home'), fila.get('c_draw'),
                                    fila.get('c_away'))
                if not q:
                    continue
                cobertura.setdefault(b, set()).add(str(fila.get('event_id')))
                margenes.setdefault(b, []).append(q['margen'])
                qp = _probabilidades(fila.get('pin_home'),
                                     fila.get('pin_draw'),
                                     fila.get('pin_away'))
                if qp:
                    err = max(abs(q[k] - qp[k])
                              for k in ('home', 'draw', 'away'))
                    por_casa.setdefault(b, []).append(err)

        mejor, mejor_err = None, None
        for b in sorted(set(list(margenes) + list(por_casa))):
            errs = por_casa.get(b) or []
            mg = margenes.get(b) or []
            ficha = {
                'n_pares': len(errs),
                'n_partidos': len(cobertura.get(b) or ()),
                'margen_mediano': round(100 * statistics.median(mg), 3)
                if mg else None,
                'margen_desviacion': round(
                    100 * statistics.pstdev(mg), 3) if len(mg) > 1 else None,
                'error_mediano_pp': round(
                    100 * statistics.median(errs), 3) if errs else None,
                'suficiente': len(errs) >= MIN_PARES,
            }
            doc['casas'][str(b)] = ficha
            if (ficha['suficiente'] and ficha['error_mediano_pp'] is not None
                    and ficha['error_mediano_pp'] <= ERROR_MAXIMO_PP):
                if mejor_err is None or ficha['error_mediano_pp'] < mejor_err:
                    mejor, mejor_err = b, ficha['error_mediano_pp']

        if mejor is None:
            faltan = MIN_PARES - max(
                [f['n_pares'] for f in doc['casas'].values()] or [0])
            doc['motivo'] = (
                'ninguna candidata pasa todavia: faltan %d pares'
                % max(0, faltan)) if faltan > 0 else (
                'hay muestra pero ninguna se pega lo suficiente a Pinnacle')
        else:
            # PRIMERA puerta pasada. NO se enciende: falta la de los
            # resultados, que es la que manda. Ver el encabezado.
            doc['candidata'] = mejor
            doc['error_pp'] = mejor_err
            doc['motivo'] = (
                'la candidata %d se pega a Pinnacle (%.2f pp), pero falta la '
                'segunda puerta: que sus picks hayan ganado' % (mejor,
                                                                mejor_err))
        _guardar(doc, ruta_meta)
    except Exception as e:
        logger.warning('[anclas] la medicion fallo: %s: %s',
                       type(e).__name__, e)
    return doc


def _guardar(doc: Dict, ruta: str) -> None:
    try:
        tmp = ruta + '.nuevo'
        with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)
    except Exception as e:
        logger.warning('[anclas] no se pudo guardar %s: %s', ruta, e)


def disponible() -> bool:
    """¿Hay ancla de reserva validada? Hoy siempre False, y a proposito."""
    try:
        if not os.path.exists(META):
            return False
        with io.open(META, encoding='utf-8') as f:
            return bool((json.load(f) or {}).get('activo'))
    except Exception:
        return False


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--medir', action='store_true',
                    help='solo medir lo acumulado, sin capturar')
    args = ap.parse_args()

    if not args.medir:
        r = capturar()
        print('capturadas %s filas de %s partidos (%s con Pinnacle)'
              % (format(r['filas'], ',d'), format(r['partidos'], ',d'),
                 format(r['con_pinnacle'], ',d')))
    d = medir()
    print('medicion: %s' % d.get('motivo', ''))
    for b, f in sorted((d.get('casas') or {}).items()):
        print('   id %-6s %4s partidos · %4s pares · margen %s %% (±%s) '
              '· error %s pp'
              % (b, f.get('n_partidos'), f.get('n_pares'),
                 f.get('margen_mediano'), f.get('margen_desviacion'),
                 f.get('error_mediano_pp')))
    print('activo: %s' % d.get('activo'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
