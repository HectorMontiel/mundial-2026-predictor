# -*- coding: utf-8 -*-
"""
v351 — LA HORA ADECUADA PARA APOSTAR CADA PARTIDO.

El usuario: «¿cuándo sería la hora adecuada para apostar ese partido? Que se
muestre algo así. No quiero que en todo sea una hora antes, porque cuando hago
un parlay de varios equipos no voy a poder hacer todos; dos horas antes o así.
Algo rápido, breve, simple y visual».

LO MEDIDO (`_v351_hora.py`, `_v351_hora.json`). Con todas las fotos del
precálculo del 3 al 9-oct (una cada ~2 h, 494 partidos terminados: 132 de
fútbol y 361 de tenis), cada «se mete» que salió en cada foto, con cuántas
horas faltaban, si seguía siendo la apuesta de la app al pitido y si se ganó:

  1. APOSTAR PRONTO NO CUESTA NADA. Lo que se apostó con más de 6 h de
     antelación acertó 77,8 % (p5 74,3); lo de las últimas 3 h, 77,0 %
     (p5 73,4). La cuota de esa hora frente a la del pitido: −0,002 y
     +0,000. Ni el acierto ni el precio mejoran por esperar.
  2. LO ÚNICO QUE CAMBIA ES SI LA APP CAMBIA DE APUESTA DESPUÉS. En fútbol,
     la apuesta de esa hora sigue siendo la del pitido:

         faltan       0-2 h   2-3 h   3-4 h   4-6 h   6-9 h   9-12 h   12-24 h   +24 h
         se queda     95 %    92 %    89 %    85 %    79 %    77 %     64-72 %   40-54 %

     En tenis se queda el 100 %: allí decide el precio de la casa (v342) y la
     apuesta no cambia.
  3. LLEVAR VARIAS HORAS SIN CAMBIAR NO ADELANTA EL MOMENTO SEGURO (por horas
     ya anunciada, sin patrón estable): manda cuánto falta.

LA REGLA. Desde 4 h antes del partido la apuesta ya es la del pitido ~9 de
cada 10 veces (89-95 %), y deja margen para armar un parlay de varios
partidos sin ir uno por uno a última hora. En tenis, en cuanto sale. La NFL
y la NBA no tienen muestra todavía (un partido): llevan la misma ventana que
el fútbol, que es la prudente. Lo anunciado y retirado se sigue enseñando
(📌) y acierta igual (v347), así que apostar antes de la ventana no es un
error: sólo es más probable que la tarjeta cambie después.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional

VENTANA_H = {'Fútbol': 4.0, 'NFL': 4.0, 'NBA': 4.0, 'MLB': 4.0, 'KBO': 4.0}
# deportes donde la apuesta no cambia: se apuesta en cuanto sale
EN_CUANTO_SALE = ('Tenis',)


def desde(pick: Dict) -> Optional[_dt.datetime]:
    """La hora (UTC) desde la que conviene apostar, o None si es «ya» o no
    se sabe la hora del partido."""
    dep = str((pick or {}).get('deporte') or 'Fútbol')
    if dep in EN_CUANTO_SALE:
        return None
    try:
        import horario as _h
        ini = _h._a_utc(pick.get('inicio'))
    except Exception:
        ini = None
    if ini is None:
        return None
    return ini - _dt.timedelta(hours=VENTANA_H.get(dep, 4.0))


def texto(pick: Dict) -> str:
    """'⏰ apuesta desde 14:15' (CDMX), '⏰ apuesta en cuanto salga' en
    tenis, o cadena vacía si no hay hora. Es fijo (no depende de la hora de
    ahora) para que la tarjeta guardada en memoria no se quede vieja."""
    dep = str((pick or {}).get('deporte') or 'Fútbol')
    if dep in EN_CUANTO_SALE:
        return '⏰ apuesta en cuanto salga'
    d = desde(pick)
    if d is None:
        return ''
    try:
        import horario as _h
        hh = _h.hora(d.strftime('%Y-%m-%dT%H:%M:%SZ'))
    except Exception:
        hh = ''
    return ('⏰ apuesta desde %s' % hh) if hh else ''


def corto(pick: Dict) -> str:
    """Lo mismo para las listas: '⏰14:15', '⏰ya' en tenis, o ''."""
    t = texto(pick)
    if not t:
        return ''
    return '⏰ya' if 'cuanto' in t else '⏰' + t.rsplit(' ', 1)[-1]
