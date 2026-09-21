# -*- coding: utf-8 -*-
"""
v271 — El cuaderno del radar: lo que se ve HOY, guardado para mañana.

LO QUE PIDIÓ EL USUARIO, Y POR QUÉ ES LO CORRECTO
«Para el entrenamiento ocupamos el pasado, y para fechas posteriores las
capturas que día con día van a estar aumentando.»

Las dos fuentes, no una:

  · EL PASADO — `pick_ledger.csv`, 26.647 partidos desde 2021 con Pinnacle y
    casa blanda a la vez. Es mucho y es gratis, pero está congelado: son las
    casas de football-data, no las que el usuario juega, y termina donde
    termina.

  · EL PRESENTE — cada barrido de la Capa 1 ya empareja Pinnacle con Novibet,
    Winpot, Caliente, 1xBet y Sportium. Ese emparejamiento existía sólo
    durante un instante en memoria y se tiraba. Aquí se guarda. Son las casas
    REALES, con los precios REALES, y crece solo: ~277 partidos por pasada,
    doce pasadas al día.

Con el tiempo la segunda fuente supera a la primera en tamaño y la gana en
pertinencia. Mientras tanto, la primera sostiene el modelo. Por eso van juntas
y no una detrás de otra.

POR QUÉ ESTO NO CUESTA NI UNA PETICIÓN
No se pide nada nuevo. El barrido ya ha pagado la consulta; lo único que se
añade es escribir una línea con lo que ya tenía delante.

Y LA ETIQUETA NO ESPERA AL RESULTADO
«¿Había error de cuota?» es una comparación de precios, no un pronóstico: se
sabe en el acto. Por eso una captura de hoy ya sirve para entrenar mañana, sin
esperar a que el partido se juegue. Ésa es la diferencia con el ledger de
picks, que sí tiene que esperar el marcador.

UNA FILA POR PARTIDO Y DÍA
Doce pasadas diarias del mismo partido darían doce filas casi idénticas que
inflarían el fichero y engañarían al modelo con repeticiones. Se guarda la
primera del día y, si una pasada posterior SÍ encuentra error donde antes no
lo había, se añade esa —porque la pregunta operativa es «si barro este partido
hoy, ¿encontraré algo?», y la respuesta correcta es que sí.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

FICHERO = 'radar_capturas.csv'

CAMPOS = ['fecha', 'deporte', 'liga', 'home', 'away', 'inicio',
          'pin_home', 'pin_draw', 'pin_away', 'q_home', 'q_away',
          'margen_pin', 'hay_error', 'ev_max', 'casa']

# El mismo listón que la Capa 1 usa desde la v269. Si allí cambia, aquí
# también: el radar tiene que aprender a encontrar lo que de verdad se juega.
EV_MINIMO = 0.005
PROB_MINIMA = 0.30

_VISTOS: Optional[Set[Tuple[str, str]]] = None
_CON_ERROR: Set[Tuple[str, str]] = set()


def _clave(fecha: str, home: str, away: str) -> Tuple[str, str]:
    return (fecha, '%s|%s' % (str(home).strip().lower(),
                              str(away).strip().lower()))


def _cargar_vistos() -> Set[Tuple[str, str]]:
    """Qué hay ya anotado, para no repetirlo. Nunca lanza."""
    global _VISTOS, _CON_ERROR
    if _VISTOS is not None:
        return _VISTOS
    vistos: Set[Tuple[str, str]] = set()
    con_error: Set[Tuple[str, str]] = set()
    try:
        if os.path.exists(FICHERO):
            with io.open(FICHERO, encoding='utf-8', newline='') as f:
                for fila in csv.DictReader(f):
                    k = _clave(fila.get('fecha') or '', fila.get('home') or '',
                               fila.get('away') or '')
                    vistos.add(k)
                    if str(fila.get('hay_error') or '') == '1':
                        con_error.add(k)
    except Exception as e:
        logger.warning('[capturas] no se pudo leer %s: %s', FICHERO, e)
    _VISTOS, _CON_ERROR = vistos, con_error
    return _VISTOS


def olvidar() -> None:
    global _VISTOS, _CON_ERROR
    _VISTOS, _CON_ERROR = None, set()


def probabilidades(pin: Dict) -> Optional[Dict]:
    """El precio de Pinnacle sin su margen. None si no se puede.

    Sirve igual para fútbol (con empate) que para tenis o MLB (sin él): lo
    que hay se normaliza, lo que no hay no estorba.
    """
    try:
        h = float(pin.get('home'))
        a = float(pin.get('away'))
    except (TypeError, ValueError, AttributeError):
        return None
    if not (h > 1 and a > 1):
        return None
    d = pin.get('draw')
    try:
        d = float(d) if d else None
    except (TypeError, ValueError):
        d = None
    if d is not None and d <= 1:
        d = None
    s = 1.0 / h + 1.0 / a + (1.0 / d if d else 0.0)
    if s <= 0:
        return None
    return {'pin_home': h, 'pin_draw': d, 'pin_away': a,
            'q_home': (1.0 / h) / s, 'q_away': (1.0 / a) / s,
            'margen_pin': s - 1.0}


def hubo_error(valores, ev_min: float = EV_MINIMO,
               prob_min: float = PROB_MINIMA) -> Dict:
    """¿Alguna casa pagaba por encima del precio justo? Y cuánto.

    `valores` es la lista `valor` que devuelve `cuotas_multi.valor_vs_sharp`.
    """
    mejor, casa = None, None
    for v in (valores or []):
        if not isinstance(v, dict):
            continue
        try:
            ev = float(v.get('ev'))
            pr = float(v.get('prob_justa'))
        except (TypeError, ValueError):
            continue
        if ev < ev_min or pr < prob_min:
            continue
        if mejor is None or ev > mejor:
            mejor, casa = ev, v.get('casa')
    return {'hay_error': 1 if mejor is not None else 0,
            'ev_max': round(mejor, 4) if mejor is not None else 0.0,
            'casa': casa or ''}


def anotar(partido: Dict, pin: Dict, valores, cuando=None) -> bool:
    """Guarda una captura. Devuelve si escribió. NUNCA lanza.

    Se llama desde el barrido, con lo que el barrido ya tiene en la mano.
    """
    try:
        q = probabilidades(pin or {})
        if not q:
            return False
        hoy = (cuando or dt.date.today()).isoformat()[:10]
        home = str(partido.get('home') or '')
        away = str(partido.get('away') or '')
        if not (home and away):
            return False
        k = _clave(hoy, home, away)
        vistos = _cargar_vistos()
        err = hubo_error(valores)
        if k in vistos and not (err['hay_error'] and k not in _CON_ERROR):
            return False
        fila = {'fecha': hoy,
                'deporte': str(partido.get('deporte') or ''),
                'liga': str(partido.get('liga') or ''),
                'home': home, 'away': away,
                'inicio': partido.get('inicio') or '',
                'pin_draw': '' if q['pin_draw'] is None else q['pin_draw']}
        for c in ('pin_home', 'pin_away'):
            fila[c] = q[c]
        for c in ('q_home', 'q_away', 'margen_pin'):
            fila[c] = round(q[c], 6)
        fila.update(err)
        nuevo = not os.path.exists(FICHERO)
        with io.open(FICHERO, 'a', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction='ignore')
            if nuevo:
                w.writeheader()
            w.writerow(fila)
        vistos.add(k)
        if err['hay_error']:
            _CON_ERROR.add(k)
        return True
    except Exception as e:
        logger.debug('[capturas] no se pudo anotar: %s', e)
        return False


def resumen() -> Dict:
    """Cuánto llevamos acumulado, para poder mirarlo sin abrir el fichero."""
    fuera = {'filas': 0, 'con_error': 0, 'dias': 0, 'desde': None,
             'hasta': None}
    try:
        if not os.path.exists(FICHERO):
            return fuera
        dias = set()
        with io.open(FICHERO, encoding='utf-8', newline='') as f:
            for fila in csv.DictReader(f):
                fuera['filas'] += 1
                if str(fila.get('hay_error') or '') == '1':
                    fuera['con_error'] += 1
                d = fila.get('fecha') or ''
                if d:
                    dias.add(d)
        fuera['dias'] = len(dias)
        if dias:
            fuera['desde'], fuera['hasta'] = min(dias), max(dias)
    except Exception as e:
        logger.warning('[capturas] no se pudo resumir: %s', e)
    return fuera


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    r = resumen()
    print('capturas: %s filas · %s con error (%.1f %%) · %s días'
          % (format(r['filas'], ',d'), format(r['con_error'], ',d'),
             100.0 * r['con_error'] / r['filas'] if r['filas'] else 0.0,
             r['dias']))
    if r['desde']:
        print('   de %s a %s' % (r['desde'], r['hasta']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
