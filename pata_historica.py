# -*- coding: utf-8 -*-
"""v245 — La pata histórica: cuántos de sus últimos partidos pasaron esa línea.

EL ENCARGO, CON SU EJEMPLO
«Me estás dando la apuesta de Menos de 11.5 córners pero en el texto me dices
que la media en la Premier es más alta que en cualquier liga. ¿Por qué
escogiste −11.5 en lugar del +7.5? Tienes que ver cuándo conviene más y cuándo
conviene menos, cuando las probabilidades son similares.»

Leeds-Crystal Palace, con los veinte partidos recientes de los dos equipos:

    opción             modelo   histórico   mezcla
    Menos de 11.5        66 %       60 %      63 %   <- lo que se recomendó
    Más de 7.5           79 %       80 %      80 %   <- lo que había que ver

EL PROBLEMA QUE ESTO ARREGLA
`valor_apuesta` recorre la escalera entera de la casa, pero después se queda
con UNA por mercado: la de mejor `Score = probabilidad × cuota`. Y ese criterio
apenas discrimina —en cualquier apuesta bien tarifada ronda 1— así que la
elección entre dos peldaños acaba decidiéndose por milésimas. En Leeds ganó el
Under por 1,019 contra 1,000.

La pata histórica es una estimación INDEPENDIENTE de la misma línea: qué
fracción de los últimos partidos de esos dos equipos la pasó. No mira el
modelo ni el precio, y por eso aporta.

LO MEDIDO
Sobre 180.103 partidos de 67 ligas con córners reales (2010-2026), evaluando
SIETE líneas por partido —de media−3,5 a media+2,5— para no medir solo la de
al lado: 1.260.350 pares (partido, línea).

    solo modelo      log-loss 0,61062   sesgo +0,26 pp
    solo histórico            0,60560          −0,06 pp
    mezcla 0,5                0,59187          +0,10 pp

    mezcla 0,5 sobre solo-modelo: +0,01875 · p5 +0,01855 · 100 % de 2.000
    remuestreos positivos

El óptimo está plano entre 0,2 y 0,5 (0,59009 en w=0,3). Se usa **0,5**: coge
el 90 % de la mejora, no está afinado al último decimal y es el mismo peso que
`concordancia` usa con el mercado, así que el sistema tiene UNA regla y no dos.

Y de paso quedó comprobado que el modelo está bien calibrado en TODAS las
líneas, no solo en la de al lado —lo que quitaba la excusa para mirar una sola:

    desvío  −3,5   dice 78,8 %   acierta 77,5 %
    desvío  −1,5   dice 57,6 %   acierta 57,7 %
    desvío  +2,5   dice 19,1 %   acierta 20,2 %

DÓNDE **NO** SE APLICA
Solo en las líneas de TOTAL del partido, que es lo único que se midió. Las de
«Local» y «Visita» hablan de los córners de UN equipo y necesitan su propia
medición; hasta entonces siguen exactamente como estaban. Prometer que están
respaldadas cuando no lo están sería peor que no tocarlas.
"""
from typing import Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

# Mitad y mitad. Ver la nota de arriba.
PESO_MODELO = 0.5

# Por debajo de esto la fracción es ruido: con seis partidos, un 4/6 y un 3/6
# se separan 17 puntos por un solo resultado.
MIN_PARTIDOS = 10

# CUÁNTOS PARTIDOS POR EQUIPO, Y POR QUÉ ESTE NÚMERO Y NO OTRO.
#
# `rendimiento_equipos.forma` usa 5 por defecto, que es lo que la tarjeta pinta
# en la racha. La medición de arriba se hizo con DIEZ por equipo —veinte entre
# los dos—, así que pedir la ventana corta aquí sería correr con un número
# distinto del que se validó. Se pide explícitamente para que las dos cosas
# no puedan separarse sin que alguien lo note.
VENTANA = 10

# De la familia de mercado a la serie que publica `rendimiento_equipos`.
#
# Los TRES que están aquí son los tres que se midieron, cada uno sobre 180.103
# partidos de 67 ligas y con el 100 % de los remuestreos a favor:
#
#     corners    modelo 0,61050 -> mezcla 0,59174   p5 +0,01855
#     remates    modelo 0,67030 -> mezcla 0,63838   p5 +0,03168
#     tarjetas   modelo 0,52449 -> mezcla 0,51845   p5 +0,00585
#     remates_on modelo 0,57814 -> mezcla 0,56033   p5 +0,01760
#     goles      modelo 0,50546 -> mezcla 0,48685   p5 +0,01832
#
# LOS GOLES ENTRARON POR UNA PREGUNTA CONCRETA DEL USUARIO: «en vez de Más de
# 1.5 pudiéramos irnos a Más de 2.5 o incluso Más de 3.5, porque el Barcelona
# anota mucho — pero que esté bien fundamentado, con la media de goles de cada
# equipo y el histórico de ambos, no nada más porque sí».
#
# Y la medición le da la razón y además dice DÓNDE hace falta. El sesgo del
# modelo por altura de línea, sobre 929.043 pares:
#
#     línea 1.5-2.6   n=178.418   +1,99 pp  ->  +1,12 pp con la mezcla
#     línea 2.6-3.6   n=179.813   -0,86 pp  ->  -0,35 pp
#     línea 3.6+      n=401.390   -3,11 pp  ->  -1,65 pp
#
# Justo en las líneas altas —donde estaría ese «Más de 3.5»— el modelo se pasa
# de optimista en tres puntos, y el histórico de los dos equipos lo corrige a
# la mitad. O sea que subir de línea es buena idea, pero el modelo solo la
# sobrevalora: esto es lo que la funda.
#
# «Remates a puerta» entró DESPUÉS, cuando el usuario pidió que se midiera
# también. Hasta entonces estuvo fuera a propósito, aunque su serie existiera
# y fuera la misma clase de cuenta: suponer que se comporta igual que los
# remates totales habría sido el atajo que este proyecto no da. Ahora está
# medido sobre los mismos 180.103 partidos y entra con el mismo derecho.
_SERIE = {'corners': 'serie_corners',
          'tarjetas': 'serie_tarjetas',
          'remates': 'serie_remates',
          'remates_on': 'serie_remates_on',
          'goles': 'serie_goles'}

_MEMO: Dict = {}


def olvidar() -> None:
    """Para los tests y para cuando cambia el histórico."""
    _MEMO.clear()


def serie(pick: Dict, familia: str) -> List[float]:
    """Los totales de los últimos partidos de los DOS equipos, juntos.

    Se juntan y no se promedian a propósito: lo que hace falta es la fracción
    que pasó la línea, y para eso hay que contar partidos, no medias.
    """
    clave_liga = str((pick or {}).get('clave_liga') or '')
    campo = _SERIE.get(str(familia or ''))
    if not clave_liga or not campo:
        return []
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
    except Exception as e:
        logger.debug('[pata] equipos: %s', e)
        return []
    if not (h and a):
        return []
    memo = (clave_liga, h, a, campo)
    if memo in _MEMO:
        return _MEMO[memo]
    fuera: List[float] = []
    try:
        import rendimiento_equipos as rq
        for equipo in (h, a):
            f = rq.forma(clave_liga, equipo, n=VENTANA) or {}
            fuera.extend(float(x) for x in (f.get(campo) or [])
                         if x is not None)
    except Exception as e:
        logger.debug('[pata] serie de %s: %s', familia, e)
        fuera = []
    _MEMO[memo] = fuera
    return fuera


def prob_mas_historica(pick: Dict, familia: str,
                       linea: float) -> Optional[float]:
    """Fracción de esos partidos que pasó de `linea`. `None` si no hay serie.

    Los empates exactos con la línea no existen: las líneas son de medio punto
    y los conteos son enteros, así que no hace falta decidir qué hacer con
    ellos.
    """
    s = serie(pick, familia)
    if len(s) < MIN_PARTIDOS:
        return None
    try:
        L = float(linea)
    except (TypeError, ValueError):
        return None
    return float(sum(1 for x in s if x > L)) / float(len(s))


def mezclar(p_modelo, p_historica) -> Optional[float]:
    """La probabilidad con la que hay que decidir. `None` si falta una."""
    try:
        a = float(p_modelo)
        b = float(p_historica)
    except (TypeError, ValueError):
        return None
    if a != a or b != b:
        return None
    return max(0.01, min(0.99, PESO_MODELO * a + (1.0 - PESO_MODELO) * b))


def aplicar(pick: Dict, familia: str, linea: float, p_mas: float,
            etiqueta: str = 'Total') -> Dict:
    """La P(más de línea) ya mezclada, con de dónde sale.

    `etiqueta` distinta de «Total» devuelve el número intacto: solo el total
    está medido. Ver la nota de cabecera.
    """
    fuera = {'p_mas': p_mas, 'hay': False, 'p_historica': None,
             'n': 0, 'razon': ''}
    if str(etiqueta or '') != 'Total':
        return fuera
    ph = prob_mas_historica(pick, familia, linea)
    if ph is None:
        return fuera
    mez = mezclar(p_mas, ph)
    if mez is None:
        return fuera
    n = len(serie(pick, familia))
    return {'p_mas': mez, 'hay': True, 'p_historica': round(ph, 4),
            'n': n,
            'razon': '%d de sus últimos %d partidos pasaron de %s'
                     % (round(ph * n), n,
                        ('%.1f' % float(linea)).rstrip('0').rstrip('.'))}
