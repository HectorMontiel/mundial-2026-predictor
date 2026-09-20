# -*- coding: utf-8 -*-
"""v251 — La lambda de goles no va corta: va demasiado extrema.

EL DIAGNOSTICO, Y ES EL CONTRARIO DEL QUE PARECIA
Medido sobre `pick_ledger_totales.csv` (47.794 partidos con la lambda del
MODELO ENTRENADO, no una estimacion casera), el sesgo por banda:

    lambda 0,0-2,0   n= 8.388   dice 1,68   pasan 2,35   +0,67
    lambda 2,0-2,5   n=12.879        2,26        2,50    +0,23
    lambda 2,5-3,0   n=12.988        2,74        2,68    -0,06
    lambda 3,0-3,5   n= 8.253        3,22        2,82    -0,40
    lambda 3,5+      n= 5.286        3,90        3,07    -0,83

Global: +0,002 goles. El NIVEL esta perfecto; lo que falla es la DISPERSION.
El modelo se va demasiado lejos en las dos direcciones — y en los partidos de
equipos goleadores predice MAS goles de los que pasan, no menos.

ESTO CORRIGE UNA LECTURA EQUIVOCADA MIA. Antes se comparo la lambda contra la
MEDIA RECIENTE de los dos equipos y parecia que el modelo iba corto (+0,43 en
los goleadores). Pero la media reciente no es lo que va a pasar: los equipos
que vienen de marcar mucho regresan a su media. Contra lo que PASO DE VERDAD,
el modelo va largo ahi. La comparacion correcta es contra el resultado, no
contra la forma.

EL ARREGLO Y SU MEDICION
Encoger hacia la media de goles de SU LIGA, que es el ancla que corresponde —
no la global: hay ligas de 3,1 goles y ligas de 2,2, y encogerlas al mismo
sitio destrozaria las dos.

    lambda' = ancla + k * (lambda - ancla)

Medido sin fuga (el ancla sale de los partidos ANTERIORES de esa liga) y
evaluado ENCIMA de la mezcla con la pata historica, que ya esta en produccion
y ya corrige parte de lo mismo:

    k     solo encogido   encogido + mezcla
    1,0        0,64209             0,61726     <- lo que habia
    0,4        0,61325             0,61141
    0,3        0,61188             0,61122     <- optimo
    0,2        0,61142             0,61126
    0,0        0,61328             0,61209

La curva toca fondo y VUELVE A SUBIR, que es el dato importante: con k=0 la
lambda del modelo no se usaria y sale peor, asi que la lambda si lleva senal
— mucha menos de la que dice, pero la lleva.

POR QUE k=0,4 Y NO EL OPTIMO 0,3. La meseta entre 0,2 y 0,4 es plana (cuatro
diezmilesimas), y 0,4 es el extremo que MENOS encoge: el mas parecido a lo que
habia y el que menos depende de que la medicion siga valiendo cuando el modelo
se reentrene. Captura el 97 % de la mejora disponible.

    k=0,4 sobre lo que ya hay:  +0,00604 ·  p5 +0,00558 · 100 % de 2.000
    remuestreos positivos

Y el sesgo por banda queda asi:

    banda          antes   despues
    0,0-2,0        +0,67     +0,11
    2,0-2,5        +0,23     +0,02
    2,5-3,0        -0,07     +0,00
    3,0-3,5        -0,40     -0,04
    3,5+           -0,83     -0,04

QUE NO HACE
No toca la lambda por equipo ni el marcador exacto: solo el TOTAL, que es lo
unico medido. Y si no hay media de liga con la que anclar, devuelve la lambda
tal cual — encoger hacia un ancla inventada seria peor que no encoger.
"""
from typing import Optional

import logging

logger = logging.getLogger(__name__)

# El factor medido. Ver la nota de arriba para por que 0,4 y no 0,3.
K_ENCOGIMIENTO = 0.4

# Interruptor, como el resto de calibradores del proyecto.
USAR_ENCOGIMIENTO_LAMBDA = True

# Fuera de esto no se encoge: una media de liga absurda es un ancla absurda.
ANCLA_MINIMA = 1.2
ANCLA_MAXIMA = 5.0


def ancla_de(clave_liga) -> Optional[float]:
    """La media de goles de esa competicion, o `None`.

    Se usa `rendimiento_equipos.media_goles_liga`, que es la MISMA que ya
    consulta `cordura_probabilidad.techo_por_liga`. Dos definiciones de «el
    nivel de goles de esta liga» en el mismo proyecto acabarian divergiendo.
    """
    if not clave_liga:
        return None
    try:
        import rendimiento_equipos as rq
        m = rq.media_goles_liga(str(clave_liga))
    except Exception as e:
        logger.debug('[lambda] media de %s: %s', clave_liga, e)
        return None
    try:
        m = float(m)
    except (TypeError, ValueError):
        return None
    if not (ANCLA_MINIMA <= m <= ANCLA_MAXIMA):
        return None
    return m


def encoger(lam, clave_liga, k: Optional[float] = None) -> Optional[float]:
    """La lambda corregida de sobredispersion. La devuelve intacta si no puede.

    Devolver el numero sin tocar cuando falta el ancla es deliberado: encoger
    hacia un valor inventado mueve TODA la escalera de goles de ese partido, y
    hacerlo mal es peor que no hacerlo.
    """
    if not USAR_ENCOGIMIENTO_LAMBDA:
        return lam
    try:
        v = float(lam)
    except (TypeError, ValueError):
        return lam
    if v <= 0 or v != v:
        return lam
    a = ancla_de(clave_liga)
    if a is None:
        return lam
    kk = K_ENCOGIMIENTO if k is None else float(k)
    return max(0.05, a + kk * (v - a))
