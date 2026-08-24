#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v165 — CONTROL DE CORDURA: NINGÚN PORCENTAJE SIN ALGO CONTRA LO QUE MEDIRLO.

El caso que lo provoca, con nombre y resultado
----------------------------------------------
Tarjeta del 2026-08-23, Celta Vigo B – Andorra: `✅ Menos de 2.5 — 80 %`.
El partido acabó **4-2**. Un 80 % en ese lado sale de una λ de partido de 1,35
goles; la media de la competición está por encima de 2,5. No es que el modelo
fallara un partido —eso pasa y no se arregla—: es que **publicó una convicción
que su propio nivel de liga no puede sostener**, y la publicó en verde.

Dos frenos, y son distintos
---------------------------
    1. CONTRA EL PRECIO DE LA CASA (`mercado_implicito`).
       Si el modelo se separa más de 15 puntos de la implícita sin margen, la
       cifra se recorta a 60 % y se rotula «🔴 Probabilidad poco fiable». No es
       que la casa tenga razón: es que una discrepancia de 15 puntos en un
       mercado líquido casi siempre es un defecto del modelo, y este proyecto
       lo tiene MEDIDO —guiarse por su probabilidad rinde −4,66 % a −6,52 %
       sobre 37.158 apuestas, y su EV correlaciona −0,054 con el cierre.

    2. CONTRA EL NIVEL DE LA COMPETICIÓN (`rendimiento_equipos`).
       En una liga que mete 3,0 goles por partido, «menos de 2,5» al 80 % es
       aritméticamente imposible salvo en un partido excepcional, y el modelo
       no tiene con qué distinguir uno excepcional. El techo es 65 % cuando la
       línea cae por debajo de la media de la liga y 50 % cuando cae 0,5 goles
       o más por debajo.

Y UN TERCER FRENO QUE NO RECORTA NADA: SIN PRECIO NO HAY VERDE
---------------------------------------------------------------
Cuando la casa no cotiza el partido —o no cotiza ESE mercado— no hay con qué
contrastar. La cifra se enseña igual, pero **no puede ir en verde**: el verde
es la única marca de esta pantalla que se lee como «juega esto», y sostenerla
sobre un número que nadie ha podido contradecir es justo lo que falló.

No es un caso raro. Medido sobre el barrido cacheado del 2026-08-23:
`pronosticos` trae 156 partidos de fútbol y **ninguno** lleva `cuota` en sus
mercados —los construye el camino del modelo, que emite cuota justa a
propósito—, así que el precio hay que ir a buscarlo al precálculo del día. Los
partidos que la casa no cotiza se quedan en ámbar, que es lo que corresponde.

LO QUE ESTE MÓDULO NO TOCA
--------------------------
La Sección 1 y el EV. La ventaja de precio es el ÚNICO canal con percentil 5
positivo medido de este proyecto (+11,49 %, p5 +1,73 % comprando al mejor
precio), y se calcula sobre la probabilidad cruda en `alpha_finder`. Meter un
techo ahí cambiaría el canal validado por uno sin validar. Esto vive en la capa
de PRESENTACIÓN y sólo cambia lo que se ve.

La dirección del recorte también importa: el techo sólo BAJA. Un modelo tímido
no se sube nunca hacia la casa, porque eso sería publicar la opinión de la casa
con la cara del modelo — el error que la v149 ya evitó con las barras de
mercado.
"""
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger('cordura_probabilidad')

# Los tres números de la regla, en un solo sitio.
DESVIO_MAX = 0.15        # separación tolerada contra la implícita de la casa
TECHO_DESVIADO = 0.60    # a lo que se recorta cuando se pasa de ahí
TECHO_LIGA_SUAVE = 0.65  # línea por debajo de la media de la competición
TECHO_LIGA_DURO = 0.50   # línea 0,5 goles o más por debajo de la media
MARGEN_DURO = 0.50

_RE_MAS = re.compile(r'^m[aá]s de ([0-9]+(?:[.,][0-9]+)?)$', re.I)
_RE_MENOS = re.compile(r'^menos de ([0-9]+(?:[.,][0-9]+)?)$', re.I)


def _linea_de(apuesta: str):
    """`(linea, es_menos)` de una apuesta de goles, o `None` si no lo es."""
    etq = str(apuesta or '').strip()
    for rx, es_menos in ((_RE_MENOS, True), (_RE_MAS, False)):
        m = rx.match(etq)
        if m:
            try:
                return float(m.group(1).replace(',', '.')), es_menos
            except ValueError:
                return None
    return None


def techo_por_liga(clave_liga, apuesta: str) -> Optional[float]:
    """
    El techo que impone el nivel de goles de la competición, o `None`.

    Sólo se aplica a las apuestas de GOLES y sólo cuando la línea está en el
    lado equivocado de la media de la competición:

        «Menos de L» con L por debajo de la media  -> se está apostando a que
        el partido baje de lo que esa liga hace normalmente;
        «Más de L» con L por encima de la media    -> el caso espejo.

    Fuera de eso devuelve `None`, y `None` no es un techo de 1,0: significa que
    esta regla no tiene nada que decir. «Menos de 3,5» en una liga de 2,7 goles
    es un favorito legítimo al 75 % y recortarlo sería el error contrario.

    Los dos escalones son los que se fijaron: media por encima de la línea ->
    65 %; media 0,5 goles o más por encima -> 50 %. Con la línea de 2,5 —la que
    cotiza toda casa y la que manda en la aplicación— eso es exactamente
    «λ > 2,5 -> 65 %» y «λ > 3,0 -> 50 %».
    """
    par = _linea_de(apuesta)
    if not par or not clave_liga:
        return None
    linea, es_menos = par
    try:
        import rendimiento_equipos as rq
        media = rq.media_goles_liga(str(clave_liga))
    except Exception as e:
        logger.debug('[cordura] media de goles de %s: %s', clave_liga, e)
        return None
    if media is None:
        return None
    # distancia hacia el lado incorrecto de la apuesta
    d = (media - linea) if es_menos else (linea - media)
    if d <= 0:
        return None
    return TECHO_LIGA_DURO if d >= MARGEN_DURO else TECHO_LIGA_SUAVE


def revisar(prob, apuesta: str, clave_liga=None,
            implicita: Optional[float] = None) -> Dict:
    """
    La probabilidad que se puede enseñar de esta apuesta, y por qué.

    Devuelve:

        {'prob':        la que se pinta (nunca por encima de la original),
         'original':    la que dio el modelo,
         'fiable':      False si se separa de la casa más de `DESVIO_MAX`,
         'contrastada': True si había precio de la casa con el que comparar,
         'puede_verde': si esta cifra puede llevar el ✅,
         'implicita':   la de la casa, sin margen, o None,
         'techo':       el techo que se aplicó, o None,
         'motivo':      texto corto para la pantalla, o ''}

    `puede_verde` es False en tres casos y conviene no confundirlos: sin precio
    de la casa (no hay con qué contrastar), con desvío grande (hay con qué y no
    cuadra) y con techo por debajo del umbral del verde (el nivel de la liga no
    lo sostiene). Los tres se cuentan por separado en `_v165_medir_cordura.py`.
    """
    try:
        p0 = float(prob)
    except (TypeError, ValueError):
        return {'prob': None, 'original': None, 'fiable': True,
                'contrastada': False, 'puede_verde': False,
                'implicita': None, 'techo': None, 'motivo': ''}

    imp = None
    if implicita is not None:
        try:
            imp = float(implicita)
        except (TypeError, ValueError):
            imp = None

    p = p0
    motivos = []
    fiable = True
    if imp is not None and abs(p0 - imp) > DESVIO_MAX:
        fiable = False
        p = min(p, TECHO_DESVIADO)
        motivos.append('la casa le da %.0f %% a esta misma apuesta' % (imp * 100))

    techo = techo_por_liga(clave_liga, apuesta)
    if techo is not None and p > techo:
        p = techo
        motivos.append('la competición no sostiene más en esta línea')

    puede_verde = fiable and imp is not None and (techo is None
                                                  or techo >= 0.60)
    return {'prob': round(p, 4), 'original': round(p0, 4), 'fiable': fiable,
            'contrastada': imp is not None, 'puede_verde': puede_verde,
            'implicita': imp, 'techo': techo,
            'motivo': ' · '.join(motivos)}


def aviso(info: Dict) -> str:
    """
    La línea que explica el recorte, o cadena vacía si no hubo ninguno.

    Cuando la cifra baja, el usuario tiene que poder saber que bajó y por qué:
    enseñar 60 % donde el modelo dijo 80 % sin decirlo es cambiar una mentira
    grande por una pequeña.
    """
    if not info:
        return ''
    if not info.get('fiable'):
        return ('🔴 **Probabilidad poco fiable** · el modelo decía %.0f %% y %s. '
                'Se enseña recortada.'
                % ((info.get('original') or 0.0) * 100,
                   info.get('motivo') or 'no cuadra con el precio de la casa'))
    if info.get('techo') is not None and \
            (info.get('original') or 0) > info['techo'] + 1e-9:
        return ('📉 **Recortada al nivel de la competición** · el modelo decía '
                '%.0f %%, y en esta liga esa línea no sostiene más de %.0f %%.'
                % ((info.get('original') or 0.0) * 100, info['techo'] * 100))
    if not info.get('contrastada'):
        return ('🔎 Sin precio de la casa con el que contrastar esta cifra: se '
                'enseña, pero no se recomienda.')
    return ''
