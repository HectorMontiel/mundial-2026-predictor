#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v229 — el total de cada deporte, en la misma forma que la escalera de goles.

EL HUECO QUE ESTO TAPA
----------------------
El usuario lo dijo en una frase: «no sólo el del gane». Medido sobre el
precálculo del 2026-09-19, con 340 picks:

    Fútbol   1X2 (con empate), goles 0.5-6.5, BTTS
    NFL      sólo «Gana X»
    MLB      sólo «Gana X»
    Tenis    sólo «Gana X»

Y no es que faltara el modelo. Los tres lo tienen, medido y desplegado:

  · MLB     `plantilla_mlb` arma la matriz de carreras y saca over/under de
            7.5 a 10.5, totales por equipo, run line y F5.
  · Tenis   `TennisEngine.plantilla` tiene una regresión de juegos calibrada
            sobre 68.000 partidos, con su sigma.
  · NFL     `nfl_mercados.plantilla_nfl` cubre el total del partido y el de
            cada equipo.

Lo que faltaba es que ese trabajo llegara al PICK DIARIO. Sólo alimentaba la
ficha de detalle, que hay que abrir partido a partido. Esto es el puente.

POR QUÉ UNA FORMA ÚNICA Y NO TRES
---------------------------------
Porque la tarjeta es una. El fútbol ya publica `goles_lineas` —{línea: P(over)}
y una λ— y la pantalla sabe pintarlo. Devolver lo mismo para carreras, puntos y
juegos hace que los tres deportes hereden esa pantalla sin tocarla, en vez de
tres bloques que divergen a la tercera versión.

LO QUE ESTO **NO** HACE
-----------------------
No recomienda nada. Publica la probabilidad del modelo, igual que
`goles_lineas`. Convertir un total en pick exige comparar contra el precio de
ese mercado concreto, y eso es otra tubería —la de cuotas por mercado— que hoy
sólo está montada para el moneyline en estos tres deportes. Publicar un pick
sin ese lado sería inventarse el EV, que es justo lo que el proyecto prohíbe.
"""
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger('totales_deporte')

# Cómo se llama el total en cada deporte. Va aquí y no en la vista porque es
# dato del deporte, no de la pantalla, y la Soñadora y Telegram lo necesitan
# igual.
UNIDAD = {'MLB': 'carreras', 'KBO': 'carreras',
          'NFL': 'puntos', 'NBA': 'puntos',
          'Tenis': 'juegos'}

_RE_OVER = re.compile(r'(?:m[áa]s de|over)\s*([0-9]+(?:[.,][0-9]+)?)', re.I)


def _linea(texto: str) -> Optional[float]:
    """La línea que menciona una etiqueta («Más de 8.5 carreras» -> 8.5)."""
    g = _RE_OVER.search(str(texto or ''))
    if not g:
        return None
    try:
        return float(g.group(1).replace(',', '.'))
    except ValueError:
        return None


def _de_campos(campos,
               prefijo_bueno=('over_', 'juegos_over_', 'total_over_',
                              'nfl_ov_')):
    """
    {línea: P(over)} a partir de una lista de campos de plantilla.

    Se filtra por el PREFIJO del id y no por el texto de la etiqueta. Los tres
    motores publican también totales POR EQUIPO —`tt_home_over_4.5`,
    `Kansas City: más de 24.5`— y mezclarlos con el total del partido daría dos
    probabilidades distintas para la misma línea. El id es lo único que los
    distingue sin ambigüedad.
    """
    fuera: Dict[str, float] = {}
    for c in (campos or []):
        if not isinstance(c, dict):
            continue
        cid = str(c.get('id') or '')
        if not any(cid.startswith(p) for p in prefijo_bueno):
            continue
        lin = _linea(c.get('etiqueta'))
        if lin is None:
            lin = _linea(cid.replace('_', ' '))
        if lin is None:
            continue
        try:
            v = float(c.get('valor'))
        except (TypeError, ValueError):
            continue
        # las plantillas publican en PORCENTAJE y aquí se guarda en [0,1],
        # como `goles_lineas`, para que la vista no tenga que saber de cuál
        # viene cada número
        fuera['%.1f' % lin] = round(min(max(v / 100.0, 0.0), 1.0), 4)
    return fuera


def _campos_de(plantilla) -> list:
    """Todos los campos de una plantilla, venga en secciones o en plano."""
    if not isinstance(plantilla, dict) or 'error' in plantilla:
        return []
    if plantilla.get('campos'):
        return list(plantilla['campos'])
    fuera = []
    for s in (plantilla.get('secciones') or []):
        fuera.extend(s.get('campos') or [])
    return fuera


def de_plantilla(plantilla, deporte: str) -> Dict:
    """
    `{'lineas': {...}, 'unidad': 'carreras', 'centro': 8.5}` o `{}`.

    `centro` es la línea que el modelo considera el punto medio: aquella cuya
    P(over) está más cerca del 50 %. Es el equivalente de la λ del fútbol para
    un deporte donde no siempre hay una media explícita, y es lo que permite
    que la tarjeta diga «espera unas 8,5 carreras» en vez de sólo un
    porcentaje suelto — que es exactamente lo que el usuario echó en falta en
    los goles.
    """
    lineas = _de_campos(_campos_de(plantilla))
    if not lineas:
        return {}
    centro = min(lineas.items(), key=lambda kv: abs(kv[1] - 0.5))[0]
    return {'lineas': lineas, 'unidad': UNIDAD.get(deporte, 'puntos'),
            'centro': float(centro)}


def lineas_alrededor(centro, paso: float, n: int = 3):
    """`n` líneas de medio punto centradas en `centro`, separadas por `paso`.

    La NFL no publica un abanico fijo: `plantilla_nfl` sólo calcula las líneas
    que le pidas, a propósito, para no fabricar cien mercados que nadie cotiza.
    Cuando el barrido no trae las de la casa —que es lo normal fuera del día
    del partido— hay que darle unas, y las útiles son las de alrededor de su
    propio total esperado: ahí es donde la probabilidad dice algo. Una línea de
    38 en un partido que el modelo ve de 51 sólo informa de que sí, habrá más
    de 38.
    """
    try:
        c = float(centro)
    except (TypeError, ValueError):
        return []
    fuera = set()
    for i in range(-(n // 2), n // 2 + 1):
        x = round((c + i * paso) * 2) / 2
        # A .5 SIEMPRE. Una línea entera admite el empate —el «push», en el que
        # la casa devuelve la apuesta— y eso es un mercado distinto con otra
        # probabilidad. Publicar 8 cuando se quiere decir 8.5 sería publicar el
        # número de otro mercado.
        if x == int(x):
            x += 0.5
        if x > 0:
            fuera.add(x)
    return sorted(fuera)


def de_nfl(pred: Dict, home: str, away: str, lineas=None) -> Dict:
    """Los totales de la NFL, pidiéndole a su plantilla las líneas que faltan."""
    if not isinstance(pred, dict) or 'error' in pred:
        return {}
    lineas = dict(lineas or {})
    if not lineas.get('total'):
        centro = pred.get('total_esperado')
        if centro is None:
            return {}
        lineas['total'] = lineas_alrededor(centro, 3.0, 3)
    try:
        import nfl_mercados as _nm
        return de_plantilla(_nm.plantilla_nfl(pred, home, away, lineas), 'NFL')
    except Exception as e:
        logger.debug('[totales/NFL] %s-%s: %s: %s', home, away,
                     type(e).__name__, e)
        return {}


def para_pick(motor, deporte: str, home: str, away: str, **ctx) -> Dict:
    """
    El bloque de totales de un partido. `{}` si no se puede, y nunca lanza.

    Degradación silenciosa a propósito: un total que falta es una fila menos en
    la tarjeta; una excepción aquí tumbaría el barrido entero, que es el error
    que este proyecto ya cometió con el tablero de la NFL.
    """
    if motor is None:
        return {}
    try:
        for nombre in ('plantilla_mlb', 'plantilla_club', 'plantilla'):
            f = getattr(motor, nombre, None)
            if f is None:
                continue
            return de_plantilla(f(home, away, **ctx), deporte)
    except Exception as e:
        logger.debug('[totales/%s] %s-%s: %s: %s', deporte, home, away,
                     type(e).__name__, e)
    return {}
