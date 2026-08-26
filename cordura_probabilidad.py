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
import json
import logging
import os
import re
from typing import Dict, Optional

logger = logging.getLogger('cordura_probabilidad')

# ---------------------------------------------------------------------------
# v166 — LOS UMBRALES YA NO SON UNA CORAZONADA
# ---------------------------------------------------------------------------
# La v165 recortaba a partir de 15 puntos de separación. Ese 15 estaba escrito
# como lo que era: una intuición. Y no hacía falta esperar a acumular nada — el
# proyecto ya tenía dos ledgers WALK-FORWARD con la probabilidad que el modelo
# dio de verdad, el resultado real y la cuota de cierre:
#
#     pick_ledger_totales.csv   17.532 partidos con cuota O/U 2,5
#     pick_ledger.csv           36.025 partidos con cierre 1X2
#
# Medido (`_v166_umbral_cordura.py`), con el modelo POR ENCIMA de la casa, que
# es la única dirección peligrosa:
#
#     desvío     n      brecha de calibración
#     0-3 pp    1661        0,002
#     3-5 pp    1295        0,044
#     5-7 pp    1317        0,065      ← cruza el 0,05 del proyecto
#     11-13 pp  1254        0,124
#     15-20 pp  2227        0,169      ← donde recortaba la v165
#     > 20 pp   2745        0,281      dice 73 %, pasa el 45 %
#
# O sea que el 15 dejaba pasar una banda entera en la que el número ya mentía
# por diez puntos. El corte medido está en 5.
#
# EL UMBRAL SE LEE DE UN FICHERO, no se escribe aquí. Si alguien vuelve a correr
# la medición con más partidos y el corte se mueve, se mueve solo. Un número
# copiado a mano en el código es exactamente el que hubo que arreglar hoy.
FICHERO_UMBRALES = 'cordura_umbrales.json'

# Respaldo si el fichero no está. Es el valor MEDIDO, no una intuición nueva:
# si el fichero desaparece, el comportamiento no cambia.
DESVIO_MAX = 0.05
TECHO_DESVIADO = 0.60    # a lo que se recorta cuando se pasa de ahí

# Mercados a los que se les encoge la probabilidad hacia el mercado antes de
# juzgarla. Ver `_encoger`.
MERCADOS_ENCOGIBLES = ('Goles', 'BTTS', '1X2')

_UMBRALES: Optional[Dict] = None


def umbral(mercado: Optional[str] = None) -> float:
    """
    El desvío tolerado para ese mercado, del fichero medido.

    Hoy los tres salen en 5 pp, pero se guardan por separado a propósito: son
    tres mediciones distintas y no hay razón para que converjan siempre.
    """
    global _UMBRALES
    if _UMBRALES is None:
        datos = {}
        try:
            if os.path.exists(FICHERO_UMBRALES):
                with open(FICHERO_UMBRALES, encoding='utf-8') as f:
                    datos = (json.load(f) or {}).get('umbrales') or {}
        except Exception as e:
            logger.debug('[cordura] no se pudo leer %s: %s',
                         FICHERO_UMBRALES, e)
        _UMBRALES = datos
    try:
        return float(_UMBRALES.get(str(mercado), DESVIO_MAX))
    except (TypeError, ValueError):
        return DESVIO_MAX
TECHO_LIGA_SUAVE = 0.65  # línea por debajo de la media de la competición
TECHO_LIGA_DURO = 0.50   # línea 0,5 goles o más por debajo de la media
MARGEN_DURO = 0.50

# ---------------------------------------------------------------------------
# v175 — EL TECHO DE LAS COMPETICIONES DE ALTA VARIANZA
# ---------------------------------------------------------------------------
# EL ENCARGO, literal: «si la liga tiene una media de goles alta (λ>3,0), usar
# un techo de probabilidad de 60 % para el lado "Menos" y de 75 % para el lado
# "Más" (si es la media). Esto fuerza a que el Score no se infle con
# probabilidades irreales.»
#
# Y LA MEDICIÓN LE DA LA RAZÓN EN EL DIAGNÓSTICO. `_v175_goles_binomial_
# negativa.py` mide la dispersión de Pearson de los goles sobre los 47.794
# partidos del ledger: **φ = 1,179 global, y 53 de 55 competiciones por encima
# de 1,02**. Las más dispersas son justo las de media alta —bol_division 1,570,
# mex_expansion 1,541, champions 1,533—. O sea que en esas ligas la varianza
# que el modelo no explica es un 50 % mayor de lo que su Poisson supone, y una
# probabilidad publicada ahí está más segura de lo que puede estar.
#
# QUÉ ES ESTO Y QUÉ NO ES. Es un techo de PRESENTACIÓN, como los otros dos de
# este módulo: sólo baja, nunca sube, y no toca la Sección 1 ni el EV. No es
# una recalibración del modelo — eso se probó (binomial negativa) y sobre la
# cifra publicada EMPEORA, así que no entró.
#
# EL «(si es la media)» DEL ENCARGO SE RESPETA, Y NO ES UN DETALLE. Aplicar un
# techo del 75 % a «Más de 0,5» en una liga de 3,2 goles —donde esa línea vale
# el 96 % de verdad— sería destrozar la calibración con la excusa de
# protegerla. El techo actúa sólo sobre las líneas CENTRALES, las que caen a
# menos de `BANDA_CENTRAL` goles de la media de la competición, que son las que
# el encargo llama «la media» y las que mueven el Score.
MEDIA_ALTA = 3.0         # a partir de aquí la competición es de alta varianza
TECHO_ALTA_MENOS = 0.60  # el lado «Menos» no puede anunciarse por encima
TECHO_ALTA_MAS = 0.75    # y el lado «Más», tampoco
BANDA_CENTRAL = 0.5      # sólo las líneas a menos de medio gol de la media

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
    techos = []
    # distancia hacia el lado incorrecto de la apuesta
    d = (media - linea) if es_menos else (linea - media)
    if d > 0:
        techos.append(TECHO_LIGA_DURO if d >= MARGEN_DURO
                      else TECHO_LIGA_SUAVE)
    # v175 — y el techo de alta varianza, sobre las líneas centrales
    if media > MEDIA_ALTA and abs(linea - media) <= BANDA_CENTRAL:
        techos.append(TECHO_ALTA_MENOS if es_menos else TECHO_ALTA_MAS)
    if not techos:
        return None
    return min(techos)


def _encoger(p: float, imp: float, clave_liga) -> tuple:
    """
    La probabilidad encogida hacia el mercado, y el peso con el que se encogió.

    POR QUÉ ESTO ES LA CAUSA RAÍZ Y EL RECORTE ERA EL SÍNTOMA
    ---------------------------------------------------------
    El 1X2 se encoge hacia el mercado desde la v71 (`calibracion_mercado`,
    w por liga con suelo 0,25). Los goles NUNCA recibieron ese tratamiento. En
    el ledger —mismo modelo, mismos partidos, mismo día— eso se ve entero:

        goles sin encoger  (w=1,00)   ECE 0,0948 · brecha en >15 pp: 0,2215
        goles encogidos    (w=0,25)   ECE 0,0139 · brecha en >15 pp: 0,0211
        óptimo por ECE     (w=0,15)   ECE 0,0110 · brecha en >15 pp: 0,0066

    Un orden de magnitud, con la maquinaria que ya existe y está validada. Se
    usa el suelo de 0,25 y no el óptimo de 0,15 porque bajar `W_MIN` sería
    re-litigar para goles una decisión que se midió para otro mercado (v75), y
    con 0,25 la mejora ya está hecha.

    HONESTIDAD SOBRE LO QUE ESTO SIGNIFICA: por Brier y por log-loss el mejor
    peso es w=0,00 — o sea, el mercado solo. El modelo no aporta nada medible a
    los goles por encima del precio de la casa. Se queda en 0,25 porque por ECE
    sí gana algo y porque publicar el mercado puro con la cara del modelo sería
    la mentira contraria.

    Devuelve `(p_encogida, w)`. Con `w = 1.0` no se tocó nada.
    """
    try:
        import calibracion_mercado as cm
        # `peso_modelo('')` devuelve 1,0 —«sin liga no hay peso»— y aquí eso
        # sería elegir la opción que la medición descarta. La curva de arriba
        # está AGRUPADA sobre 20 competiciones y da 0,25, que es justo el suelo
        # del módulo. Una liga sin clave hereda ese agregado, igual que una
        # liga sin medición propia hereda el global desde la v80.
        w = float(cm.peso_modelo(str(clave_liga or '')) if clave_liga
                  else cm.W_MIN)
    except Exception as e:
        logger.debug('[cordura] peso de %s: %s', clave_liga, e)
        return p, 1.0
    if not (0.0 < w < 1.0):
        return p, 1.0
    return w * float(p) + (1.0 - w) * float(imp), w


def revisar(prob, apuesta: str, clave_liga=None,
            implicita: Optional[float] = None, mercado: Optional[str] = None,
            ya_encogido: bool = False) -> Dict:
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
    w = 1.0

    # 1) ENCOGER hacia el mercado. Va PRIMERO porque es la causa raíz: con el
    #    encogimiento puesto, la brecha de calibración de goles baja de 0,2215
    #    a 0,0211 en el tramo que la v165 recortaba, y el recorte pasa de ser
    #    el mecanismo principal a ser un cortafuegos que casi nunca salta.
    if imp is not None and not ya_encogido and (
            mercado is None or str(mercado) in MERCADOS_ENCOGIBLES):
        p, w = _encoger(p, imp, clave_liga)
        if w < 1.0:
            motivos.append('ajustada al precio de la casa')

    # 2) RECORTAR si aun así se separa. Y SÓLO HACIA ARRIBA: medido, cuando el
    #    modelo va por DEBAJO de la casa no miente al alza — dice 55 % y pasa
    #    el 63-73 %. Recortar ahí no quita nada (ya está por debajo del techo)
    #    y marcarlo en rojo señalaría como sospechoso un número prudente. La
    #    v165 usaba el valor absoluto y trataba las dos direcciones igual; la
    #    medición dice que no lo son.
    lim = umbral(mercado)
    if imp is not None and (p - imp) > lim:
        fiable = False
        # el desvío se mide ANTES de recortar: contarlo después daría la
        # distancia que queda tras el recorte, que puede ser negativa y no es
        # lo que se quiere decir.
        motivos.append('aun así queda %.0f puntos por encima de la casa'
                       % ((p - imp) * 100))
        p = min(p, TECHO_DESVIADO)

    techo = techo_por_liga(clave_liga, apuesta)
    if techo is not None and p > techo:
        p = techo
        motivos.append('la competición no sostiene más en esta línea')

    puede_verde = fiable and imp is not None and (techo is None
                                                  or techo >= 0.60)
    return {'prob': round(p, 4), 'original': round(p0, 4), 'fiable': fiable,
            'contrastada': imp is not None, 'puede_verde': puede_verde,
            'implicita': imp, 'techo': techo, 'w': round(w, 3),
            'encogida': w < 1.0, 'umbral': lim,
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
    # v166 — el ajuste hacia el mercado también se dice, aunque no sea un
    # recorte por desconfianza. Medido sobre 17.532 partidos: sin él la cifra
    # que se enseñaba se separaba de la realidad hasta 22 puntos. Enseñar el
    # número ajustado sin decir que se ajustó sería cambiar de mentira.
    if info.get('encogida') and abs((info.get('original') or 0.0)
                                    - (info.get('prob') or 0.0)) >= 0.02:
        return ('📊 Ajustada al precio de la casa · el modelo decía %.0f %% y '
                'la casa paga %.0f %%. Medido sobre 17.532 partidos, mezclarlas '
                'acierta mucho mejor que el modelo solo.'
                % ((info.get('original') or 0.0) * 100,
                   (info.get('implicita') or 0.0) * 100))
    if info.get('techo') is not None and \
            (info.get('original') or 0) > info['techo'] + 1e-9:
        return ('📉 **Recortada al nivel de la competición** · el modelo decía '
                '%.0f %%, y en esta liga esa línea no sostiene más de %.0f %%.'
                % ((info.get('original') or 0.0) * 100, info['techo'] * 100))
    if not info.get('contrastada'):
        return ('🔎 Sin precio de la casa con el que contrastar esta cifra: se '
                'enseña, pero no se recomienda.')
    return ''
