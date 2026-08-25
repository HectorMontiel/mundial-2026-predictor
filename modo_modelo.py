#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v152 — MODO MODELO: la pantalla que ordena por probabilidad, no por precio.

Qué es, y en qué se diferencia del resto de la app
--------------------------------------------------
El usuario lo pidió con estas palabras: «no quiero ver EV alto en equipos
débiles; quiero que la app me diga que este equipo está jugando mejor y que el
modelo le da un 70 %». Eso es una pantalla distinta, no un orden distinto:

    Modo Valor   ordena por VENTAJA DE PRECIO contra el consenso. Es el criterio
                 con p5 positivo medido, y el que decide la Sección 1.
    Modo Modelo  ordena por PROBABILIDAD DEL MODELO y enseña el rendimiento
                 reciente observado de los dos equipos.

v153.1 — LA PANTALLA SE SIMPLIFICA: UNA TARJETA, UNA APUESTA
------------------------------------------------------------
El encargo fue «que se sienta como un producto, no como un laboratorio de
datos»: una línea que diga qué apostar, la racha en colores debajo, y ningún
tecnicismo. Eso es lo que hay.

    ✅ Menos de 2.5 goles — 72 %      (verde:   ≥ 60 % Y contrastado)
    🟡 Gana el Barcelona — 55 %       (ámbar:   ≥ 50 %, sólo para combinar)
    ⚠️ Sin apuesta clara              (nada llega al 50 %)

v165 — EL VERDE YA NO SE GANA SÓLO CON UN NÚMERO ALTO
------------------------------------------------------
El 2026-08-23 esta pantalla anunció «✅ Menos de 2.5 — 80 %» en Celta Vigo B –
Andorra. Acabó 4-2. El fallo no fue acertar o no acertar un partido: fue
publicar en verde una convicción que nada sostenía. Desde la v165 el ✅ exige
tres cosas a la vez, y `cordura_probabilidad` las comprueba:

    · llegar al 60 %, como siempre;
    · no separarse más de 15 puntos de lo que la casa paga por ESA misma
      apuesta, sin margen (`mercado_implicito`);
    · que HAYA precio de la casa con el que compararse. Sin él la cifra se
      enseña, pero en ámbar y diciendo por qué.

Y por encima de las tres, un techo: en una competición que mete 3,0 goles por
partido, «menos de 2,5» no puede anunciarse por encima del 50 % aunque el
modelo lo crea, porque la aritmética de la liga no lo sostiene.

Medido sobre el barrido del 2026-08-23: de 151 tarjetas, 103 iban en verde. De
las 11 que se pudieron contrastar contra la casa, 4 se separaban más de 15
puntos y 3 de esas 4 estaban en verde — 87 % contra 67 %, 81 % contra 63 % y
70 % contra 46 %.

La apuesta destacada NO es sólo el 1X2: gana el mercado con más probabilidad de
todo el partido, que es lo que se pidió.

EL UMBRAL DEL VERDE ES 60 % Y NO 50, Y ESO NO ES DECORATIVO
------------------------------------------------------------
El board trae SIEMPRE los dos lados de cada mercado («más de 2.5» y «menos de
2.5»), así que el máximo de la lista está garantizado por encima del 50 %. Con
el verde en 50 no habría un solo partido sin su apuesta destacada, y una
etiqueta que sale siempre no informa de nada — es la lección de la v150 sobre
los avisos: el umbral se elige para que CALLE en el caso corriente.

LO QUE ESTA PANTALLA SIGUE DICIENDO, AUNQUE YA NO EN CADA TARJETA
------------------------------------------------------------------
El porcentaje es la probabilidad del MODELO, y este proyecto tiene medido que
guiarse por ella pierde entre −4,66 % y −6,52 % sobre 37.158 apuestas (su EV es
anti-indicador del cierre, correlación −0,054). Los textos técnicos salieron de
las tarjetas, que era lo pedido; la advertencia no desapareció, se plegó: vive
en un desplegable al pie, cerrado, una sola vez.

Enseñar un porcentaje como recomendación sin que en NINGUNA parte de la pantalla
se pueda leer lo que rinde convertiría la aplicación en lo contrario de lo que
es. Donde hay ventaja medida es en comprar al mejor precio, y eso vive en la
pestaña de al lado.

SIN MODELO NO ES CON MERCADO
----------------------------
La v149 rellenó los partidos sin pronóstico con la probabilidad implícita del
mercado, etiquetada. Aquí NO: esta pantalla existe para leer al modelo, y un
número del mercado disfrazado de fila del modelo rompería justo eso. Los
partidos sin pronóstico salen agrupados aparte, con `Sin datos de modelo`.
"""
import logging

import numpy as np
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ligas que el plan llama «principales»: las que concentran volumen y donde el
# mercado está más trabajado. La lista es corta a propósito — todo lo que no
# esté aquí cuenta como secundaria, y así una competición nueva entra por
# defecto en el grupo que el usuario quiere mirar en vez de desaparecer.
PRINCIPALES = {
    'premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'champions',
    'europa_league', 'conference_league', 'eredivisie', 'primeira',
    'liga_mx', 'brasil', 'argentina', 'mls',
}

PROB_DESTACADA = 0.60      # a partir de aquí el modelo está diciendo algo


def es_secundaria(pick: Dict) -> Optional[bool]:
    """
    Si la competición del pick no está en la lista corta de principales.

    Devuelve `None` cuando el eje NO APLICA, y eso pasa siempre que el pick no
    es de fútbol. «Principal» y «secundaria» describen el volumen de una liga de
    fútbol frente a otra; la MLB no es una liga de fútbol secundaria, es otro
    deporte. La primera versión la etiquetaba como secundaria por no estar en la
    lista, y en pantalla salía «MLB · MLB · secundaria», que es una afirmación
    que nadie hizo.

    Los tres valores son distintos y el filtro los trata distinto: `True` y
    `False` se pueden pedir; `None` sólo aparece en «Todas».
    """
    if str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
        return None
    return str(pick.get('clave_liga') or '') not in PRINCIPALES


def _equipos(pick: Dict):
    """Los dos nombres del partido, o (None, None) si el rótulo no se parte."""
    nom = str(pick.get('partido') or '')
    for sep in (' vs ', ' vs. ', ' @ ', ' - '):
        if sep in nom:
            h, a = nom.split(sep, 1)
            return h.strip(), a.strip()
    return None, None


def _rendimiento(pick: Dict) -> Optional[Dict]:
    """El rendimiento reciente de los dos equipos, o None si no hay histórico."""
    clave = pick.get('clave_liga')
    h, a = _equipos(pick)
    if not clave or not h or not a:
        return None
    try:
        import rendimiento_equipos as rq
        r = rq.resumen_partido(str(clave), h, a)
        if not (r['forma_home'].get('n') or r['forma_away'].get('n')):
            return None
        return r
    except Exception as e:
        logger.debug('[modo_modelo] rendimiento %s: %s', clave, e)
        return None


def _bloque_tenis(st, pick: Dict) -> None:
    """
    El rendimiento de los dos jugadores: superficie, racha y sets.

    La SUPERFICIE viaja ya en el pick del barrido, así que no hay que ir a
    buscarla. Es además la variable que el plan pedía, y el modelo de tenis la
    usa desde hace versiones: tiene ELO por superficie con la pista cubierta
    como superficie propia (`hard_indoor` ≠ `hard`), porcentaje de victorias en
    esa superficie a 12 meses, y fatiga (partidos en 14 días, horas en pista en
    7). Aquí no se recalcula nada de eso: se enseña la forma reciente, que es lo
    que la pantalla no tenía.

    La cobertura del histórico de tenis es parcial —349 de 784 jugadores llegan
    a cinco partidos— y quien no llega no enseña racha.
    """
    sup = pick.get('superficie')
    if sup:
        st.markdown('**🎾 Superficie:** %s' % sup)
    h, a = _equipos(pick)
    if not h or not a:
        return
    try:
        import rendimiento_equipos as rq
    except Exception:
        return
    hubo = False
    for quien in (h, a):
        f = rq.forma_tenis(quien)
        if not f.get('n'):
            continue
        hubo = True
        trozos = ['**%s** `%s`' % (quien, f['racha'])]
        if f.get('pct_sets') is not None:
            trozos.append('%.0f %% de sets ganados (%d-%d)'
                          % (f['pct_sets'] * 100, f['sets_favor'],
                             f['sets_contra']))
        st.markdown(' · '.join(trozos))
    if not hubo:
        st.caption('Sin partidos recientes de estos jugadores en el '
                   'histórico: no hay racha que leer.')
    elif sup:
        st.caption('La racha son sus últimos partidos en cualquier '
                   'superficie: partirla por superficie dejaría muestras de '
                   'uno o dos partidos. El modelo sí separa por superficie '
                   'internamente, y la pista cubierta cuenta como una propia.')


# ---------------------------------------------------------------------------
# v153.1 — LA APUESTA DEL PARTIDO, Y EL SEMÁFORO POR PROBABILIDAD
# ---------------------------------------------------------------------------
UMBRAL_ALTA = 0.60          # verde: el modelo se moja
UMBRAL_PATA = 0.50          # amarillo: sólo para combinar

# Mercados que NO compiten por ser «la apuesta del partido».
#
# El board trae los dos lados de cada mercado, así que el máximo de la lista
# está garantizado por encima del 50 % — coger el mayor sin pensar hace que casi
# todo partido tenga su apuesta destacada. Por eso el verde exige 60 % y no 50:
# el umbral se elige para que la etiqueta CALLE en el caso corriente. No se
# excluye ningún mercado hoy, pero el sitio está hecho.
_MERCADOS_FUERA: set = set()


def apuesta_destacada(pick: Dict) -> Optional[Dict]:
    """
    El mercado con más probabilidad de este partido, sea cual sea.

    No se limita al 1X2: se pidió ver «Menos de 2.5 goles (72 %)» si eso es lo
    que el modelo cree con más fuerza. Se miran todos los mercados que el
    barrido dejó en el pick y gana el de mayor probabilidad.

    Devuelve `None` cuando ninguno llega al umbral, y ese None se PINTA: un
    partido sin nada claro tiene que decirlo, porque si no el usuario lee la
    ausencia de aviso como una recomendación.
    """
    filas = []
    for m in (pick.get('mercados') or []):
        if not isinstance(m, dict):
            continue
        if str(m.get('mercado') or '') in _MERCADOS_FUERA:
            continue
        # v164 — UN MERCADO ESTIMADO NO PUEDE SER EL TITULAR.
        #
        # Hoy no puede llegar ninguno: `alpha_finder` sólo mete aquí 1X2,
        # Goles, BTTS y hándicap, todos derivados de la matriz de marcador, que
        # se entrena con goles REALES en las 62 competiciones. Auditado sobre
        # el barrido del 2026-08-23: los 151 titulares salen de Goles (96),
        # BTTS (45) y 1X2 (10), ninguno de córners, tarjetas ni remates.
        #
        # La guarda se pone igualmente porque el día que alguien meta un
        # mercado físico en `mercados` —que es lo natural cuando se quiera
        # ofrecer córners como pick— el titular se llenaría de estimaciones sin
        # que nada lo denunciara. Es el modo de fallo de la v106 otra vez: un
        # argumento que deja de ser cierto y nadie se entera.
        if str(m.get('origen') or 'observado') == 'estimado':
            continue
        try:
            p = float(m.get('prob'))
        except (TypeError, ValueError):
            continue
        # v166 — SI `alpha_finder` YA ENCOGIO ESTE MERCADO HACIA EL PRECIO DE
        # LA CASA, NO SE ENCOGE DOS VECES. El 1X2 lo lleva hecho desde la v71 y
        # trae su `calibracion` dentro; goles y BTTS nunca lo tuvieron, y ahi
        # es justo donde la medicion encontro brechas de hasta 22 puntos.
        _ya = bool((m.get('calibracion') or {}).get('aplicado'))
        filas.append((p, str(m.get('apuesta') or ''),
                      str(m.get('mercado') or ''), _ya))
    if not filas:
        # Sin `mercados` (deportes que sólo publican el ganador) queda el board.
        for etiqueta, p in (pick.get('board') or {}).items():
            try:
                filas.append((float(p), str(etiqueta), '', False))
            except (TypeError, ValueError):
                continue
    if not filas:
        # Y en último recurso, la propia apuesta del pick. Este camino existe
        # porque sin él la tarjeta decía «Sin apuesta clara» en todo partido
        # que llegara sólo con `apuesta` y `prob` —que son la mayoría fuera del
        # fútbol— y eso no es «no hay nada claro»: es «no miré donde había».
        try:
            p = float(pick.get('prob'))
        except (TypeError, ValueError):
            p = None
        if p is not None and pick.get('apuesta'):
            filas.append((p, str(pick['apuesta']),
                          str(pick.get('mercado') or ''), False))
    if not filas:
        return None
    # v165 — EL CONTROL DE CORDURA, ANTES DE ELEGIR Y NO DESPUÉS.
    #
    # Si se eligiera el máximo crudo y luego se recortara, la tarjeta podría
    # anunciar un 60 % recortado desde el 87 % teniendo al lado otro mercado
    # con un 64 % que nadie ha tenido que tocar. Se revisa cada fila y gana la
    # que más vale DESPUÉS del recorte, que es lo que se está enseñando.
    revisadas = []
    for p, apuesta, mercado, ya in filas:
        info = _revisar(pick, apuesta, p, mercado=mercado, ya_encogido=ya)
        revisadas.append((info.get('prob', p), apuesta, mercado, info))
    p, apuesta, mercado, info = max(revisadas, key=lambda f: f[0])
    if p < UMBRAL_PATA:
        return None
    # El verde exige las tres cosas: llegar al 60 %, no separarse de la casa
    # más de 15 puntos y que HAYA casa con la que compararse. Sin precio no hay
    # verde, y eso no es un tecnicismo: el ✅ es la única marca de esta pantalla
    # que se lee como «juega esto».
    return {'prob': p, 'apuesta': apuesta, 'mercado': mercado,
            'alta': p >= UMBRAL_ALTA and bool(info.get('puede_verde')),
            'original': info.get('original', p),
            'fiable': bool(info.get('fiable', True)),
            'contrastada': bool(info.get('contrastada')),
            'implicita': info.get('implicita'),
            'techo': info.get('techo'),
            'aviso': _aviso_cordura(info)}


def _revisar(pick: Dict, apuesta: str, prob: float,
             mercado: Optional[str] = None, ya_encogido: bool = False) -> Dict:
    """
    La probabilidad que se puede enseñar de esa apuesta en ESTE partido.

    Junta las dos piezas: el precio de la casa que `alpha_finder` dejó en el
    pick (`implicitas`, sin margen y sin una sola petición de red) y las reglas
    de `cordura_probabilidad`. Si cualquiera de los dos módulos falla, devuelve
    la cifra intacta y sin verde: degradar a «no se puede contrastar» es el
    fallo seguro; degradar a «adelante, es verde» sería el peligroso.
    """
    try:
        import cordura_probabilidad as cp
    except Exception as e:
        logger.debug('[modo_modelo] cordura no disponible: %s', e)
        return {'prob': prob, 'original': prob, 'fiable': True,
                'contrastada': False, 'puede_verde': False,
                'implicita': None, 'techo': None, 'motivo': ''}
    imp = None
    try:
        import mercado_implicito as mi
        h, a = _equipos(pick)
        imp = mi.implicita(pick.get('implicitas') or {}, apuesta,
                           h or '', a or '')
    except Exception as e:
        logger.debug('[modo_modelo] implícita de %s: %s', apuesta, e)
    return cp.revisar(prob, apuesta, pick.get('clave_liga'), implicita=imp,
                      mercado=mercado, ya_encogido=ya_encogido)


def _aviso_cordura(info: Dict) -> str:
    try:
        import cordura_probabilidad as cp
        return cp.aviso(info)
    except Exception:
        return ''


_COLOR = {'G': '#1a7f37', 'E': '#9a6700', 'P': '#cf222e'}


def racha_html(racha: str) -> str:
    """
    La racha en colores, que es como se lee de un vistazo.

    Verde ganado, ámbar empatado, rojo perdido. Es la misma letra que ya había;
    el color hace el trabajo que antes había que hacer leyendo letra a letra.
    """
    if not racha:
        return ''
    return ''.join(
        '<span style="display:inline-block;width:1.15rem;height:1.15rem;'
        'line-height:1.15rem;text-align:center;border-radius:3px;'
        'margin-right:2px;font-size:.72rem;font-weight:700;color:#fff;'
        'background:%s">%s</span>' % (_COLOR.get(c, '#57606a'), c)
        for c in str(racha))


def _mini_forma(f: Dict, disp: Dict) -> str:
    """
    Una línea compacta: racha en color y las dos cifras que caben.

    Los córners salen aquí como dato (⛳ sacados–recibidos de los últimos 5) y
    NO como línea recomendada, y eso está medido: el total que el modelo predice
    para un partido es la media de su competición —la misma para todos sus
    partidos— porque la parte que variaba tiene correlación −0,0012 con el
    resultado real sobre 11.856 partidos. Recomendar «más de 9,5» a partir de un
    número idéntico en los diez partidos de la jornada sería vender la media de
    la liga como lectura del partido. Las medias de cada equipo sí son suyas.

    Y sólo se pintan donde la competición los publica de verdad: `disp` viene de
    `rendimiento_equipos.stats_disponibles`, que lo comprueba reproduciendo el
    generador sintético.
    """
    if not f or not f.get('n'):
        return ''
    partes = ['<b>%s</b> %s' % (f.get('equipo', ''), racha_html(f.get('racha')))]
    if disp.get('goles') and f.get('gf_media') is not None:
        partes.append('⚽ %.1f–%.1f' % (f['gf_media'], f['gc_media']))
    if disp.get('corners') and f.get('ck_favor') is not None:
        partes.append('⛳ %.1f–%.1f' % (f['ck_favor'], f['ck_contra']))
    return ' &nbsp;·&nbsp; '.join(partes)


# ---------------------------------------------------------------------------
# v155 — LA MISMA TARJETA PARA HOY Y PARA MAÑANA
# ---------------------------------------------------------------------------
# Las dos vistas enseñaban cosas distintas del mismo partido: hoy traía la
# apuesta destacada y las rachas, y mañana una barra de 1X2 con la etiqueta
# «· informativo». Ahora las dos pintan `tarjeta()`.
#
# Lo que cambia entre una y otra NO es el diseño: es que los partidos de mañana
# no producen picks («mañana se analiza, no se apuesta», v143), así que su
# tarjeta sale sin la línea de apuesta y con el aviso de por qué.

# Claves con las que el barrido nombra cada mercado en `board` y en `mercados`.
# Se buscan por prefijo porque el 1X2 lleva el nombre del equipo dentro
# («Gana Man City») y el resto no.
_ETQ_OVER = 'Más de 2.5'
_ETQ_UNDER = 'Menos de 2.5'
_ETQ_BTTS_SI = 'Ambos marcan: Sí'
_ETQ_BTTS_NO = 'Ambos marcan: No'


def _board(pick: Dict) -> Dict[str, float]:
    """Todas las probabilidades del partido, vengan de donde vengan."""
    salida = {}
    for m in (pick.get('mercados') or []):
        if isinstance(m, dict) and m.get('apuesta') is not None:
            try:
                salida[str(m['apuesta'])] = float(m['prob'])
            except (TypeError, ValueError):
                continue
    for k, v in (pick.get('board') or {}).items():
        try:
            salida.setdefault(str(k), float(v))
        except (TypeError, ValueError):
            continue
    # El relleno de mercado de la v149 va aparte y NO se mezcla: viene de la
    # casa, no del modelo, y confundirlos es justo lo que esa versión evitó.
    return salida


def probabilidades_1x2(pick: Dict):
    """
    (local, empate, visitante) del board, o `None` si no está el trío completo.

    Se localizan por los nombres de los equipos y no por posición: el board es
    un diccionario y su orden no es de fiar.
    """
    b = _board(pick)
    h, a = _equipos(pick)
    if not h or not a:
        return None
    pl = b.get('Gana %s' % h)
    pv = b.get('Gana %s' % a)
    px = b.get('Empate')
    if pl is None or pv is None or px is None:
        return None
    return (pl, px, pv)


def _bloque_goles_html(pick: Dict, board: Dict) -> str:
    """
    v163.1 — LOS GOLES EN SUS TRES LÍNEAS: 1,5 · 2,5 · 3,5.

    Se pidió porque una sola línea no dice lo mismo en todos los partidos: un
    64 % de «más de 2,5» puede venir de un partido que casi seguro pasa de 1,5
    o de uno que se va a 4, y con una sola barra los dos se leen igual.

    Salen de `goles_lineas`, que `alpha_finder` calcula sobre la misma matriz
    de marcador. Si no está —picks viejos en caché, deportes sin matriz— se
    cae a la línea de 2,5 de siempre, que es lo que había antes de esto.

    La de 2,5 sigue en NEGRITA y con barra: es la que cotiza toda casa y la que
    manda en el resto de la aplicación. Las otras dos van debajo, en una línea
    compacta, para que añadir información no cueste el doble de tarjeta.
    """
    lineas = pick.get('goles_lineas') or {}
    fila25 = _fila_mercado('⚽', 'Goles', board.get(_ETQ_OVER),
                           board.get(_ETQ_UNDER), 'Más 2.5', 'Menos 2.5')
    casa = _fila_casa(pick, '2.5')
    if not lineas:
        return fila25 + casa
    otras = []
    for etq in ('1.5', '3.5'):
        try:
            p = float(lineas[etq])
        except (KeyError, TypeError, ValueError):
            continue
        otras.append('Más %s <b>%.0f %%</b> · Menos %s %.0f %%'
                     % (etq, p * 100, etq, (1.0 - p) * 100))
    if not otras:
        return fila25 + casa
    if not fila25:
        # sin la de 2,5 no hay barra, pero las otras dos siguen valiendo
        fila25 = '<div class="mm-merc"><div class="mm-merc-tit">⚽ Goles</div></div>'
    return fila25 + ('<div class="mm-ck-fila mm-goles-otras">%s</div>'
                     % ' &nbsp;·&nbsp; '.join(otras)) + casa


def _fila_casa(pick: Dict, linea: str = '2.5') -> str:
    """
    v165 — LO QUE LA CASA CREE DE LA MISMA LÍNEA, DEBAJO DE LO QUE CREE EL MODELO.

    Es la comparación que faltaba y la que el usuario no podía hacer: la
    tarjeta anunciaba «Menos de 2.5 — 80 %» sin nada al lado, y la casa pagaba
    ese mismo lado al 63 %. Las dos cifras juntas dicen más que cualquiera de
    las dos sola, y ninguna de las dos se disfraza de la otra.

    Sale del precio que `alpha_finder` adjuntó al pronóstico, ya sin margen. Si
    no hay, no se pinta nada — un hueco se ve y un relleno no.
    """
    p = (((pick.get('implicitas') or {}).get('goles')) or {}).get(linea)
    try:
        p = float(p)
    except (TypeError, ValueError):
        return ''
    casa = (pick.get('implicitas') or {}).get('casa') or 'la casa'
    return ('<div class="mm-ck-fila mm-casa">🏠 %s · Más %s <b>%.0f %%</b> · '
            'Menos %s %.0f %% <span class="mm-ck-est">precio de la casa, sin '
            'su margen</span></div>'
            % (casa, linea, p * 100, linea, (1.0 - p) * 100))


def _fila_mercado(icono: str, titulo: str, izq, der, etq_izq: str,
                  etq_der: str) -> str:
    """
    Un mercado de dos lados, con su barra y sus dos porcentajes.

    Devuelve cadena vacía si falta cualquiera de los dos lados: media barra
    dibujada es peor que ninguna, porque el hueco se lee como «no lo sé» y la
    media barra como «esto vale 40 %».
    """
    if izq is None or der is None:
        return ''
    i, d = float(izq), float(der)
    tot = i + d
    if tot <= 0:
        return ''
    wi = i / tot * 100.0
    return (
        '<div class="mm-merc">'
        '<div class="mm-merc-tit">%s %s</div>'
        '<div class="mm-barra">'
        '<span style="width:%.1f%%;background:var(--ok)"></span>'
        '<span style="width:%.1f%%;background:var(--info)"></span>'
        '</div>'
        '<div class="mm-merc-val"><b>%s %.0f %%</b> · %s %.0f %%</div>'
        '</div>' % (icono, titulo, wi, 100.0 - wi, etq_izq, i * 100,
                    etq_der, d * 100))


# ---------------------------------------------------------------------------
# v159 — LOS CÓRNERS, CON SU PROBABILIDAD, EN LA TARJETA
# ---------------------------------------------------------------------------
# Hasta aquí la tarjeta enseñaba las medias observadas de cada equipo y ninguna
# probabilidad, porque el modelo del TOTAL predecía la media de la competición y
# publicar «Más de 9.5: 52 %» habría dicho más de la liga que del partido.
#
# Eso cambió al medirlo bien (v157-v158). Ahora hay dos estimadores calibrados
# contra la frecuencia REAL, cada uno el mejor para su mercado:
#
#     total del partido ....  media de la competición + binomial negativa
#                             error de calibración 0,0043
#     por equipo ...........  ataque + defensa del rival + binomial negativa
#                             error de calibración 0,0056
#
# Así que la probabilidad ya se puede enseñar. Lo que NO se puede es marcarla en
# verde: verde en esta aplicación significa «canal con percentil 5 positivo
# medido», y el EV de córners sigue sin histórico de líneas con el que
# comprobarlo. Va en ámbar, que es lo que el usuario pidió y lo que corresponde.

# La línea que se usa en la tarjeta es la más cercana a la media, no la de la
# casa. Pedirle el tablero a Playdoit cuesta 0,64 s por partido, y con cuarenta
# tarjetas serían 25 s de red en la vista más usada de la aplicación — la misma
# que se acaba de bajar de 119 s a 52. La línea de la casa sí se cruza en la
# FICHA del partido, que se abre de una en una.
def _linea_cercana(media: float) -> float:
    """La línea de medio punto más cercana a la media."""
    return float(np.floor(float(media))) + 0.5


def _mejor_lado(media: float, linea: float, disp) -> Optional[Dict]:
    """
    El lado más probable de una línea, con su probabilidad.

    Devuelve siempre el que supera el 50 %: es el que se enseña, y enseñar el
    otro obligaría al usuario a restar de cabeza.
    """
    try:
        import rendimiento_equipos as rq
        p_mas = rq.prob_mas_de(media, linea, disp)
    except Exception as e:
        logger.debug('[modo_modelo] prob de córners: %s', e)
        return None
    if p_mas is None:
        return None
    if p_mas >= 0.5:
        return {'texto': 'Más de %.1f' % linea, 'prob': float(p_mas),
                'linea': linea}
    return {'texto': 'Menos de %.1f' % linea, 'prob': float(1.0 - p_mas),
            'linea': linea}


def corners_tarjeta(pick: Dict) -> Optional[Dict]:
    """
    Total y por equipo, cada uno con su media y su apuesta mas probable.

    v162 — SALE EN TODAS LAS COMPETICIONES. Hasta aqui devolvia `None` en las
    55 que no publican corners observados. Ahora `rendimiento_equipos` cae al
    estimador de respaldo y esto lo pinta con su etiqueta: se pidio que ninguna
    liga se quede sin la seccion, y un numero marcado como estimado es mas util
    que un hueco — siempre que se diga que lo es, que es lo que hace
    `_bloque_corners_html`.

    Sigue devolviendo `None` cuando no es futbol o cuando no hay ni goles con
    los que situar el nivel de la competicion.
    """
    clave = str(pick.get('clave_liga') or '')
    if not clave or str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
        return None
    h, a = _equipos(pick)
    if not h or not a:
        return None
    try:
        import rendimiento_equipos as rq
        eq = rq.corners_equipo(clave, h, a)
    except Exception as e:
        logger.debug('[modo_modelo] córners de %s: %s', clave, e)
        return None
    if not eq:
        return None
    # v166 — con la línea REAL de la casa cuando el precálculo del día la trae.
    return _filas_de(eq, '⛳', 'corners',
                     lineas_casa=(pick.get('implicitas') or {}).get('corners'))


def _linea_de_la_casa(lineas: Optional[Dict], media: float) -> Optional[float]:
    """
    v166 — LA LINEA QUE COTIZA LA CASA, NO LA MEDIA REDONDEADA.

    La tarjeta situaba la apuesta en «la linea de medio punto mas cercana a la
    media», que es una linea INVENTADA: podia anunciar «Mas de 9.5 57 %»
    mientras la casa cotizaba 8,5, y entonces el porcentaje no correspondia a
    ninguna apuesta que se pudiera hacer.

    Se elige la linea REAL mas cercana a la media, para que la probabilidad que
    se enseña sea la de algo que existe. Devuelve None cuando la casa no cotiza
    corners de este partido, y entonces se cae a la de siempre — un hueco se
    ve, y aqui ni siquiera hay hueco: hay la linea de antes.
    """
    if not lineas:
        return None
    candidatas = []
    for k in lineas:
        try:
            candidatas.append(float(k))
        except (TypeError, ValueError):
            continue
    if not candidatas:
        return None
    return min(candidatas, key=lambda x: (abs(x - float(media)), x))


def _filas_de(eq: Dict, icono: str, mercado: str = '',
              lineas_casa: Optional[Dict] = None) -> Optional[Dict]:
    """
    Las tres filas de una seccion —total, local y visita— con su apuesta.

    Es comun a cornrs y tarjetas porque las dos secciones tienen exactamente la
    misma forma: la unica diferencia es de donde sale el total, y eso ya viene
    resuelto en `lambda_total` (media de la competicion en corners, suma de las
    dos lambdas en tarjetas — cada uno el mejor medido para su mercado).
    """
    filas = []
    tot, disp_tot = eq.get('lambda_total'), eq.get('dispersion_total')
    if tot:
        _lc = _linea_de_la_casa(lineas_casa, tot)
        lado = _mejor_lado(tot, _lc if _lc is not None else _linea_cercana(tot),
                           disp_tot)
        if lado:
            filas.append({'etiqueta': 'Total', 'media': float(tot),
                          'de_la_casa': _lc is not None, **lado})
    for nombre, media in (('Local', eq.get('lambda_home')),
                          ('Visita', eq.get('lambda_away'))):
        if not media:
            continue
        lado = _mejor_lado(media, _linea_cercana(media), eq.get('dispersion'))
        if lado:
            filas.append({'etiqueta': nombre, 'media': float(media), **lado})
    if not filas:
        return None
    origen = eq.get('origen') or 'observado'
    # v164 — QUIEN PUEDE LLEVAR INSIGNIA Y QUIEN NO.
    #
    # Medido sobre el barrido del 2026-08-23: de 624 bloques fisicos pintados,
    # 232 eran ESTIMADOS y todos anunciaban su «destacado», hasta un 68 %. En
    # 58 partidos lo eran TODOS. Un bloque estimado es el nivel de la
    # competicion repartido por bando, IDENTICO en todos sus partidos: no sabe
    # nada de ESE partido y no puede parecer una recomendacion.
    #
    # `confianza_mercado` decide, y el bloque sigue llevando sus filas y su
    # etiqueta: lo que desaparece es la insignia, no la informacion.
    conf = {'nivel': 2, 'insignia': True, 'error': None, 'motivo': ''}
    try:
        import confianza_mercado
        conf = confianza_mercado.nivel(eq.get('clave_liga') or '',
                                       mercado or '', origen)
    except Exception as e:
        logger.debug('[modo_modelo] confianza de %s: %s', mercado, e)
    return {'filas': filas, 'mejor': max(filas, key=lambda f: f['prob']),
            'origen': origen,
            'aceptable': eq.get('aceptable', True),
            'error_calibracion': eq.get('error_calibracion'),
            'confianza': conf,
            'base': eq.get('base'), 'icono': icono, 'mercado': mercado}


def _etiqueta_origen(bloque: Dict) -> str:
    """
    El aviso de que un numero es estimado y no observado.

    NO ES DECORACION. La regla de este proyecto desde la v149 es que un hueco
    se ve y un relleno no; enseñar una estimacion sin decirlo la convierte en
    un dato observado a ojos de quien la lee. Hay dos niveles porque los
    errores medidos son distintos: los corners estimados calibran a 0,0247 y
    las tarjetas a 0,0539, y el umbral que se fijo como aceptable era 0,05.
    """
    if (bloque.get('origen') or 'observado') != 'estimado':
        return ''
    if bloque.get('aceptable'):
        return ('<div class="mm-ck-fila mm-est">📐 <b>Estimado</b> · esta '
                'competición no publica esta estadística: el nivel sale de sus '
                'goles, no de sus partidos. Es igual para todos sus partidos.'
                '</div>')
    return ('<div class="mm-ck-fila mm-est mm-est-flojo">📐 <b>Estimado, con '
            'poca precisión</b> · esta competición no publica esta '
            'estadística. Su error de calibración medido (%.3f) está por '
            'encima del umbral aceptable (0,050): sirve para hacerse una idea '
            'del nivel, no para apostar.</div>'
            % float(bloque.get('error_calibracion') or 0.0))


def _bloque_corners_html(ck: Dict) -> str:
    """La seccion compacta, con la mas probable resaltada en ambar."""
    return _bloque_seccion_html(ck, '⛳', 'Córners')


def _bloque_seccion_html(bloque: Optional[Dict], icono: str,
                         titulo: str) -> str:
    """
    v164 — LA INSIGNIA SOLO SI EL MERCADO SE LA HA GANADO.

    Antes salia siempre, tambien sobre un bloque estimado. Un bloque estimado
    es el nivel de la competicion repartido por bando, identico en todos los
    partidos de esa liga —lo dice su propia etiqueta—, asi que anunciarlo como
    «destacado» le da forma de recomendacion a un numero que no distingue un
    partido de otro. Medido: 232 de 624 bloques del dia, y 58 partidos donde lo
    eran todos.

    Ahora la insignia depende de `confianza_mercado`:

        nivel 1  observado, error < 0,02          insignia limpia
        nivel 2  observado, 0,02-0,05 o sin medir  insignia con el error al lado
        nivel 3  estimado                          SIN insignia

    Las filas y la etiqueta de origen NO se tocan: lo que desaparece es la
    insignia, no la informacion. El bloque sigue enseñando sus tres medias y su
    «📐 Estimado», que es lo que se pidio.

    Y sigue siendo AMBAR en los tres niveles. El verde de esta aplicacion
    significa «canal con percentil 5 de bootstrap positivo medido» (§0), y
    cornrs, tarjetas y remates no lo tienen — estar bien calibrado y estar bien
    pagado son dos cosas distintas.
    """
    if not bloque:
        return ''
    mejor = bloque['mejor']
    estimado = (bloque.get('origen') or 'observado') == 'estimado'
    conf = bloque.get('confianza') or {}
    con_insignia = bool(conf.get('insignia', not estimado))
    if con_insignia:
        try:
            import confianza_mercado
            matiz = confianza_mercado.etiqueta(conf)
        except Exception:
            matiz = ''
        badge = ('<span class="mm-ck-badge">🟡 destacado: %s %s &nbsp;%.0f %%%s'
                 '</span>'
                 % (mejor['etiqueta'], mejor['texto'], mejor['prob'] * 100,
                    (' <span class="mm-ck-est">%s</span>' % matiz)
                    if matiz else ''))
    else:
        badge = ''
    # v165 — Y ADEMAS SE APAGA EL BLOQUE ENTERO.
    #
    # Quitar la insignia dejaba el bloque con el mismo peso visual que uno
    # medido: tres filas en negro con sus porcentajes, que es lo que el usuario
    # leyo como recomendacion en el parlay del 2026-08-23. Sin insignia el
    # bloque va en gris — se ve, se puede consultar, y no compite con lo que si
    # esta medido. Es la misma disciplina que la barra de mercado de la v149:
    # otro origen, otro tono.
    apagado = '' if con_insignia else ' mm-sinsena'
    trozos = ['<div class="mm-ck-tit%s">%s <b>%s</b>%s %s</div>'
              % (apagado, icono, titulo,
                 ' <span class="mm-ck-est">estimado</span>' if estimado else '',
                 badge)]
    for f in bloque['filas']:
        # sin insignia no se resalta ninguna fila: destacar una en negrita es
        # la misma afirmacion con otra tipografia
        resalta = ' mm-ck-mejor' if (con_insignia and f is mejor) else ''
        # v166 — cuando la línea es la que cotiza la casa se dice, porque hasta
        # ahora era una línea inventada («la media redondeada») y el usuario no
        # tenía forma de distinguir una de otra.
        sello = (' <span class="mm-ck-est">línea de la casa</span>'
                 if f.get('de_la_casa') else '')
        trozos.append(
            '<div class="mm-ck-fila%s%s">%s <b>%.1f</b> · %s '
            '<span class="mm-ck-pct">%.0f %%</span>%s</div>'
            % (resalta, apagado, f['etiqueta'], f['media'], f['texto'],
               f['prob'] * 100, sello))
    trozos.append(_etiqueta_origen(bloque))
    return ''.join(trozos)


# ---------------------------------------------------------------------------
# v160 — LAS TARJETAS, CON SU PROBABILIDAD Y CON EL ÁRBITRO
# ---------------------------------------------------------------------------
# Hasta aquí la tarjeta enseñaba «Rangers 1.6 · St Mirren 2.2 (amarillas por
# partido)»: dos medias de los últimos cinco partidos, sin línea y sin
# probabilidad. Ahora enseña lo mismo que los córners —total, local y visitante,
# cada uno con su apuesta más probable y su probabilidad calibrada— más el
# árbitro designado, que en tarjetas es la tercera pata del asunto.
#
# UNA DIFERENCIA CON LOS CÓRNERS QUE SE VE EN PANTALLA
# ----------------------------------------------------
# El total NO es la media de la competición, como sí lo es en córners. Aquí el
# estimador del partido gana por cuatro veces (calibración 0,0119 contra 0,0488)
# porque la indisciplina es un rasgo del equipo y sacar córners no lo es tanto.
# Así que el «Total» de esta sección es la suma de las dos lambdas, y cambia de
# partido en partido — que es justo lo que en córners no se podía prometer.
#
# LO QUE SE CUENTA ES AMARILLAS **MÁS ROJAS**, Y ESO SE MIDIÓ CONTRA LA CASA
# --------------------------------------------------------------------------
# La primera versión contaba sólo amarillas y quedaba 0,27 tarjetas por debajo
# del centro de la línea real de la casa, con la diferencia creciendo según
# subía la línea. Sumando las rojas —0,25 por partido de media— el centro pasó
# de 4,16 a 4,36 contra los 4,43 de la casa, y la calibración contra el
# resultado REAL mejoró de 0,0141 a 0,0117 por equipo. O sea que no es un
# apaño para parecerse al mercado: acierta más contra lo que de verdad pasó.
# El detalle está en `rendimiento_equipos`, sección v160.
#
# EL ÁRBITRO SE PINTA SIEMPRE QUE SE SEPA, Y CUANDO NO, SE DICE
# -------------------------------------------------------------
# El factor sale de `arbitro_partido`, que lo precalcula el bot en
# `arbitros_dia.json`. Si el fichero no está —el bot no ha corrido— o FotMob no
# ha publicado todavía la designación —pasa con los partidos a dos días vista,
# 13 de 48 en la primera medición— el factor es 1,0 y la línea del árbitro dice
# que no se sabe. No se rellena con la media: un hueco se ve, un relleno no.
#
# SIGUE EN ÁMBAR, Y NO ES UN DESCUIDO
# -----------------------------------
# Verde en esta aplicación significa «canal con percentil 5 positivo medido».
# Para tarjetas todavía no hay histórico de líneas con el que medirlo:
# `snapshots_tarjetas.py` lo empieza a acumular hoy, igual que
# `snapshots_corners.py` hizo con los córners en la v159. Hasta que ese
# histórico dé para liquidar, esto es una probabilidad mejor calibrada, no una
# ventaja de precio demostrada.
def tarjetas_tarjeta(pick: Dict) -> Optional[Dict]:
    """
    Total y por equipo de tarjetas —amarillas mas rojas—, cada uno con su
    apuesta mas probable, y el arbitro designado.

    v162 — SALE EN TODAS LAS COMPETICIONES, igual que corners: donde no hay
    datos observados cae al estimador de respaldo y se marca. Ojo con la
    diferencia entre las dos secciones: la estimacion de tarjetas calibra a
    0,0539, por encima del umbral de 0,05 que se fijo como aceptable, asi que
    ahi el aviso es el fuerte.
    """
    clave = str(pick.get('clave_liga') or '')
    if not clave or str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
        return None
    h, a = _equipos(pick)
    if not h or not a:
        return None

    perfil, f_arb = None, 1.0
    try:
        import arbitro_partido
        fecha = str(pick.get('fecha') or '')[:10]
        if fecha:
            perfil = arbitro_partido.buscar(fecha, h, a)
            f_arb = arbitro_partido.factor_de(fecha, h, a)
    except Exception as e:
        logger.debug('[modo_modelo] árbitro de %s: %s', clave, e)

    try:
        import rendimiento_equipos as rq
        tj = rq.tarjetas_equipo(clave, h, a, factor_arbitro=f_arb)
    except Exception as e:
        logger.debug('[modo_modelo] tarjetas de %s: %s', clave, e)
        return None
    if not tj:
        return None
    bloque = _filas_de(tj, '🟨', 'tarjetas')
    if not bloque:
        return None
    bloque['arbitro'] = perfil
    bloque['factor_arbitro'] = tj.get('factor_arbitro', 1.0)
    return bloque


def _bloque_tarjetas_html(tj: Optional[Dict]) -> str:
    """La seccion compacta, con la mas probable resaltada en ambar."""
    if not tj:
        return ''
    trozos = [_bloque_seccion_html(tj, '🟨', 'Tarjetas')]
    arb = tj.get('arbitro') or {}
    if arb.get('nombre'):
        factor = float(tj.get('factor_arbitro') or 1.0)
        # El signo se dice en palabras ademas de en numero: «x1,04» obliga a
        # recordar que es 1 y en una lista de cuarenta tarjetas nadie lo hace.
        if factor >= 1.015:
            sentido = 'tira a más'
        elif factor <= 0.985:
            sentido = 'tira a menos'
        else:
            sentido = 'en la media'
        # Las cifras del arbitro son AMARILLAS —es lo que publica FotMob— y las
        # de arriba son amarillas mas rojas. No se mezclan nunca porque lo que
        # se usa del arbitro es una RAZON contra la media de su propia
        # competicion, que es adimensional. Se rotula «amarillas» para que
        # nadie sume esta cifra con las de arriba.
        trozos.append(
            '<div class="mm-ck-fila mm-arb">👤 %s · %.2f amarillas por partido '
            'contra %.2f de la competición en %s partidos · %s (×%.3f)</div>'
            % (arb.get('nombre'), arb.get('amarillas_por_partido') or 0.0,
               arb.get('media_competicion') or 0.0, arb.get('partidos'),
               sentido, factor))
    else:
        trozos.append('<div class="mm-ck-fila mm-nd">👤 Árbitro sin designar '
                      'todavía · las tarjetas salen sin ajuste arbitral</div>')
    return ''.join(trozos)


# ---------------------------------------------------------------------------
# v163 — LOS REMATES, EN SUS DOS MERCADOS, Y QUIÉN LOS TIRA
# ---------------------------------------------------------------------------
# Tercera sección física, con la misma forma que córners y tarjetas para que se
# lea igual: total, local y visita, cada uno con su línea y su probabilidad.
#
# DOS BLOQUES Y NO UNO, PORQUE SON DOS MERCADOS
# ----------------------------------------------
# «Más de 12,5 remates» y «más de 4,5 a puerta» se cotizan por separado y se
# calibraron por separado (§13 de la bitácora). Juntarlos en una fila obligaría
# a elegir uno, y el que se dejara fuera sería el que el usuario está mirando.
#
# LO QUE NO SE PUEDE PROMETER AQUÍ, Y ESTÁ MEDIDO
# ------------------------------------------------
# Esto es una probabilidad mejor calibrada, no una ventaja de precio. No hay
# histórico de líneas de remates con el que medir un percentil 5, igual que
# pasaba con las tarjetas en la v160. Sale en ámbar y ahí se queda hasta que
# `snapshots_remates.py` acumule bastante para liquidar.
def remates_tarjeta(pick: Dict) -> Optional[Dict]:
    """
    Los dos mercados de remates del partido, cada uno con su apuesta más
    probable.

    Devuelve `{'totales': bloque, 'a_puerta': bloque}` con la forma que pinta
    `_bloque_seccion_html`, o `None` si no es fútbol o no hay ni goles con los
    que situar el nivel de la competición.
    """
    clave = str(pick.get('clave_liga') or '')
    if not clave or str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
        return None
    h, a = _equipos(pick)
    if not h or not a:
        return None
    try:
        import rendimiento_equipos as rq
        eq = rq.remates_equipo(clave, h, a)
    except Exception as e:
        logger.debug('[modo_modelo] remates de %s: %s', clave, e)
        return None
    if not eq:
        return None
    salida = {}
    for nombre, icono in (('totales', '🎯'), ('a_puerta', '🥅')):
        if eq.get(nombre):
            bloque = _filas_de(eq[nombre], icono, nombre)
            if bloque:
                salida[nombre] = bloque
    return salida or None


def _bloque_remates_html(rem: Optional[Dict]) -> str:
    """Las dos secciones, con la más probable de cada una resaltada."""
    if not rem:
        return ''
    trozos = []
    if rem.get('totales'):
        trozos.append(_bloque_seccion_html(rem['totales'], '🎯', 'Remates'))
    if rem.get('a_puerta'):
        trozos.append(_bloque_seccion_html(rem['a_puerta'], '🥅',
                                           'Remates a puerta'))
    return ''.join(trozos)


# ---------------------------------------------------------------------------
# v163 — QUIÉN REMATA, EN LA TARJETA
# ---------------------------------------------------------------------------
# El top 3 de cada equipo. Se sirve del roster de temporada que YA está
# precalculado en `goleadores_cache.json`, así que no cuesta ni una petición:
# la tarjeta se pinta sesenta veces por pantalla y pedir once `summary` por
# equipo (mil trescientas peticiones) no cabe. La tabla completa y con forma
# reciente está en la ficha, que se abre de una en una.
#
# EL AVISO NO ES DECORACIÓN, ES EL RESULTADO DE UNA MEDICIÓN
# -----------------------------------------------------------
# Saber CUÁNTO remata un jugador calibra (ECE 0,029). Saber SI VA A JUGAR no:
# la frecuencia de titularidad da ECE de 0,057 a 0,073, por encima del umbral
# de 0,05 del proyecto. Así que cuando FotMob publica el once probable se dice
# de dónde sale, y cuando no, se dice que no se sabe quién juega. Las dos
# frases son distintas y la diferencia es justo lo que separa un dato de una
# suposición.
def quien_remata_tarjeta(pick: Dict, tope: int = 3) -> Optional[Dict]:
    """El top `tope` de cada equipo, sin pedir nada a la red."""
    clave = str(pick.get('clave_liga') or '')
    if not clave or str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
        return None
    h, a = _equipos(pick)
    if not h or not a:
        return None
    try:
        import remates_jugador as rjg
        return rjg.partido(clave, h, a, str(pick.get('fecha') or '')[:10],
                           en_vivo=False, tope=tope)
    except Exception as e:
        logger.debug('[modo_modelo] quién remata en %s: %s', clave, e)
        return None


def _bloque_quien_remata_html(qr: Optional[Dict]) -> str:
    if not qr:
        return ''
    filas = (qr.get('home_jugadores') or []) + (qr.get('away_jugadores') or [])
    if not filas:
        return ''
    al = qr.get('alineacion') or {}
    if al.get('etiqueta') == 'probable':
        cabecera = ('once probable'
                    if al.get('tipo') == 'predicted' else 'alineación')
    elif al.get('etiqueta') == 'último once':
        cabecera = 'once del último partido'
    elif al.get('etiqueta') == 'confirmada':
        cabecera = 'once confirmado'
    else:
        cabecera = 'sin alineación'
    trozos = ['<div class="mm-ck-tit">🎯 <b>Quién remata</b> '
              '<span class="mm-ck-est">%s</span></div>' % cabecera]
    for lado, equipo in (('home', qr.get('home')), ('away', qr.get('away'))):
        js = qr.get(lado + '_jugadores') or []
        if not js:
            continue
        partes = []
        for j in js:
            corto = '*' if j.get('muestra_corta') else ''
            # v164 — LA LÍNEA DE LA CASA MANDA SOBRE LA NUESTRA.
            #
            # Si Playdoit cotiza a este jugador se enseña SU línea y la
            # probabilidad de ESA línea, que es la que el usuario va a ver en
            # el boleto. Sin línea se cae a «al menos uno», que es lo que había
            # y sigue siendo información honesta — pero no se inventa un
            # porcentaje sobre una línea que la casa no ofrece.
            trozo = None
            if j.get('p_linea_tot') is not None:
                trozo = ('%s <b>%.0f %%</b> de +%.1f'
                         % (j.get('jugador'), j['p_linea_tot'] * 100,
                            j['linea_tot']))
                if j.get('p_linea_on') is not None:
                    trozo += (' · %.0f %% de +%.1f a puerta'
                              % (j['p_linea_on'] * 100, j['linea_on']))
            elif j.get('p_remata') is not None:
                trozo = ('%s <b>%.0f %%</b> de rematar'
                         % (j.get('jugador'), j['p_remata'] * 100))
                if j.get('p_al_arco') is not None:
                    trozo += ' · %.0f %% a puerta' % (j['p_al_arco'] * 100)
            if trozo:
                partes.append(trozo + corto)
        if partes:
            trozos.append('<div class="mm-ck-fila">%s · %s</div>'
                          % (equipo, ' &nbsp;·&nbsp; '.join(partes)))
    if len(trozos) == 1:
        return ''
    # el pie: qué son esas probabilidades y qué NO son
    con_linea = sum(1 for j in filas if j.get('p_linea_tot') is not None)
    if con_linea:
        pie = ('«+1.5» es la línea que cotiza la casa y el porcentaje es la '
               'probabilidad del modelo para ESA línea. Es informativa: el '
               'mercado de jugador no tiene aquí ventaja de precio medida.')
        if con_linea < len(filas):
            pie += (' A %d de estos %d jugadores la casa no les cotiza línea, '
                    'y para ésos se enseña la probabilidad de rematar al menos '
                    'una vez — no un cero.'
                    % (len(filas) - con_linea, len(filas)))
    else:
        pie = ('probabilidad de tirar al menos un remate, y de que al menos '
               'uno vaya a puerta. La casa no cotiza líneas de jugador en este '
               'partido. Son informativas: el mercado de jugador no tiene aquí '
               'ventaja de precio medida.')
    if not al:
        pie = ('todavía no hay alineación publicada, así que no se sabe quién '
               'sale de inicio — ' + pie)
    else:
        # Si el once no se ha podido casar entero, se dice. Una lista de seis
        # nombres rotulada «once probable» afirma que el once son esos seis.
        faltan = [qr.get(l + '_casados_de') for l in ('home', 'away')]
        faltan = [c for c in faltan if c and c[0] < c[1]]
        if faltan:
            pie = ('de la alineación se han encontrado %s con estadística — '
                   % ' y '.join('%d de %d' % c for c in faltan)) + pie
    if any(j.get('muestra_corta') for j in filas):
        pie += ' El asterisco marca a quien lleva menos de 4 partidos.'
    if any(j.get('on_del_previo') for j in filas):
        pie += (' El «a puerta» de esta lista sale de la media de cada puesto, '
                'no de la puntería propia del jugador: el roster que hay '
                'guardado todavía no trae ese dato y se refresca solo.')
    trozos.append('<div class="mm-ck-fila mm-est">📐 %s</div>' % pie)
    return ''.join(trozos)


def _bloque_fisico(rend: Dict, disp: Dict, con_corners: bool = True,
                   con_tarjetas: bool = True) -> str:
    """
    Córners y tarjetas: lo que los dos equipos hacen DE VERDAD.

    Aquí no hay probabilidades, y es una decisión medida. El modelo de córners
    de este proyecto predice la media de la competición —la misma cifra para
    todos sus partidos—, porque su parte variable tiene correlación −0,0012 con
    el total real sobre 11.856 partidos. Publicar «Más de 9.5: 52 %» sería
    vender esa media como si fuera lectura de ESTE partido.

    Lo que sí es de cada equipo son sus medias observadas, y eso es lo que sale.
    Donde la competición no publica la estadística —55 de 75— se dice, en vez de
    dejar el hueco: `stats_disponibles` lo comprueba reproduciendo el generador
    sintético, así que «no disponible» aquí significa «la fuente no lo trae»,
    no «no lo hemos mirado».
    """
    fh = rend.get('forma_home') or {}
    fa = rend.get('forma_away') or {}
    filas = []

    if not con_corners:
        # La sección de arriba ya los pintó CON su probabilidad. Repetir aquí
        # las mismas medias sin probabilidad alarga la tarjeta y no añade nada.
        pass
    elif disp.get('corners') and fh.get('ck_favor') is not None \
            and fa.get('ck_favor') is not None:
        filas.append(
            '<div class="mm-fis">⛳ <b>Córners</b> · %s saca %.1f y recibe '
            '%.1f · %s saca %.1f y recibe %.1f</div>'
            % (fh.get('equipo', 'local'), fh['ck_favor'], fh['ck_contra'],
               fa.get('equipo', 'visitante'), fa['ck_favor'], fa['ck_contra']))
    else:
        filas.append('<div class="mm-fis mm-nd">⛳ Córners · '
                     'datos no disponibles en esta competición</div>')

    if not con_tarjetas:
        # v160: la sección de arriba ya las pintó con su probabilidad y con el
        # árbitro. Repetir aquí las medias de los últimos cinco no añade nada.
        pass
    elif disp.get('tarjetas') and fh.get('amarillas') is not None \
            and fa.get('amarillas') is not None:
        filas.append(
            '<div class="mm-fis">🟨 <b>Tarjetas</b> · %s %.1f · %s %.1f '
            '(amarillas por partido)</div>'
            % (fh.get('equipo', 'local'), fh['amarillas'],
               fa.get('equipo', 'visitante'), fa['amarillas']))
    else:
        filas.append('<div class="mm-fis mm-nd">🟨 Tarjetas · '
                     'datos no disponibles en esta competición</div>')
    return ''.join(filas)


CSS = """
<style>
.mm-merc { margin:.28rem 0; }
.mm-merc-tit { font-size:.76rem; opacity:.85; }
.mm-merc-val { font-size:.78rem; margin-top:.1rem; }
.mm-barra { display:flex; height:.55rem; border-radius:4px; overflow:hidden;
            margin:.12rem 0; }
.mm-barra span { display:block; height:100%; }
.mm-1x2 { display:flex; height:.8rem; border-radius:4px; overflow:hidden;
          margin:.2rem 0 .1rem; font-size:.66rem; color:#fff;
          font-weight:700; text-align:center; line-height:.8rem; }
.mm-1x2 span { display:block; height:100%; }
.mm-fis { font-size:.78rem; margin:.15rem 0; }
.mm-nd { opacity:.55; font-style:italic; }
.mm-forma { font-size:.86rem; line-height:1.8; margin-top:.25rem; }
.mm-ck-tit { font-size:.8rem; margin:.35rem 0 .1rem; }
.mm-ck-badge { background:#9a6700; color:#fff; border-radius:4px;
               padding:.05rem .35rem; font-size:.7rem; font-weight:700;
               margin-left:.25rem; }
.mm-ck-fila { font-size:.79rem; line-height:1.65; padding-left:.5rem; }
/* v163.1 — las lineas de 1,5 y 3,5 van pegadas a la barra de 2,5 y algo
   mas apagadas: son contexto de la principal, no tres mercados iguales. */
.mm-goles-otras { margin-top:-.15rem; opacity:.82; }
.mm-ck-mejor { font-weight:700; }
.mm-ck-pct { opacity:.85; }
.mm-arb { opacity:.85; font-style:italic; }
.mm-ck-est { background:#4a5568; color:#fff; border-radius:3px; padding:0 .3rem;
             font-size:.68rem; font-weight:600; vertical-align:middle; }
.mm-est { opacity:.85; font-size:.74rem; line-height:1.5; }
.mm-est-flojo { color:#b45309; }
.mm-jug { font-size:.79rem; line-height:1.6; padding-left:.6rem; opacity:.9; }
/* v165 — el precio de la casa y los bloques sin insignia.
   `mm-casa` es una cifra de OTRO origen que la del modelo, asi que se
   distingue como la barra de mercado de la v149: misma forma, tono aparte.
   `mm-sinsena` apaga el bloque entero de un mercado que no ha ganado su
   insignia — el usuario lo ve, la aplicacion no lo recomienda. */
.mm-casa { font-size:.75rem; opacity:.85; margin-top:-.1rem;
           border-left:2px solid var(--tenue); }
.mm-sinsena { opacity:.62; }
/* v167 — LA TARJETA ACCIONABLE.
   `mm-rec` es el bloque de arriba: una apuesta, su precio y nada mas.
   `mm-fc` es una fila de mercado en rejilla — nombre, linea, dos lados y una
   insignia CORTA. Lo que antes era un parrafo aqui es una etiqueta de dos
   palabras, y el parrafo vive en el desplegable. */
.mm-rec { display:flex; flex-direction:column; gap:.15rem; margin:.5rem 0 .35rem;
          padding:.55rem .7rem; border-radius:10px; border:1px solid var(--borde); }
.mm-rec-tit { font-size:.64rem; font-weight:800; letter-spacing:.06em;
              opacity:.75; }
.mm-rec-ap { font-size:1.05rem; font-weight:800; line-height:1.25; }
.mm-rec-cu { font-size:.76rem; opacity:.85; }
.mm-rec-si { background:rgba(26,127,55,.14); border-color:var(--ok); }
.mm-rec-ambar { background:rgba(154,103,0,.14); border-color:var(--mira); }
.mm-rec-no { background:var(--panel2); opacity:.8; }
.mm-rec-no span { font-size:.76rem; opacity:.8; }
.mm-otros { font-size:.64rem; font-weight:800; letter-spacing:.06em;
            opacity:.7; margin:.5rem 0 .2rem; }
.mm-fc { display:grid; grid-template-columns:7.5rem 2.4rem 1fr 1fr auto;
         gap:.4rem; align-items:center; font-size:.78rem; line-height:1.9;
         border-top:1px solid var(--borde); }
.mm-fc-n { font-weight:600; }
.mm-fc-l { opacity:.75; text-align:right; }
.mm-fc-e { text-align:right; }
.mm-fc-barra { grid-column:2 / -1; }
.mm-fc-jug { grid-column:2 / -1; font-size:.75rem; }
/* v168 — la tira de estabilidad: seis iconos y sus rotulos, nada mas. */
.mm-tira { display:grid; grid-template-columns:repeat(6,1fr); gap:.2rem;
           text-align:center; font-size:.62rem; line-height:1.5;
           margin:.1rem 0 .25rem; opacity:.95; }
.mm-est-c { display:block; }
@media (max-width:768px) {
  .mm-fc { grid-template-columns:6.2rem 2.2rem 1fr 1fr; row-gap:.1rem; }
  .mm-fc-e { grid-column:3 / -1; text-align:left; }
}
</style>
"""



# ---------------------------------------------------------------------------
# v167 — LA APUESTA RECOMENDADA: UNA, Y LA QUE HAY QUE METER
# ---------------------------------------------------------------------------
# El encargo, con sus palabras: «no quiero leer, quiero apostar». La tarjeta
# enseñaba seis bloques, cuatro párrafos técnicos y ninguna instrucción. Esto
# elige UNA apuesta de todo el partido y la pone arriba, con su cuota y con el
# botón para jugarla; el resto de la tarjeta pasa a ser contexto compacto y el
# texto técnico se pliega en un desplegable.
#
# EL ORDEN DE PRIORIDAD, Y LA PARTE QUE NO SE PUDO SEGUIR AL PIE DE LA LETRA
# --------------------------------------------------------------------------
# Lo pedido fue: (1) mejor EV, (2) si ninguno es positivo, la de mayor
# probabilidad calibrada por encima del 60 % que esté en verde o ámbar, (3) si
# no hay nada, decirlo.
#
# El paso (1) tal cual estaba escrito —EV sobre la probabilidad CRUDA del
# modelo— es exactamente el canal que este proyecto tiene medido como
# ANTI-INDICADOR: guiarse por el EV del modelo rinde −4,66 % a −6,52 % sobre
# 37.158 apuestas, y su EV correlaciona −0,054 con el cierre (§2 del traspaso).
# Peor todavía: el EV es máximo justo donde el modelo más se separa de la casa,
# y la v166 midió que ahí es donde su número más miente — brecha de calibración
# 0,28 por encima de los 20 puntos de desvío.
#
# Así que el orden se respeta, pero el EV se calcula sobre la probabilidad YA
# AJUSTADA por `cordura_probabilidad` (encogida hacia el mercado y recortada si
# hace falta). Con esa probabilidad, un EV positivo ya no significa «el modelo
# discrepa mucho» sino «esta casa paga por encima de lo que vale», que es la
# ventaja de PRECIO — el único canal con percentil 5 positivo medido del
# proyecto (+11,49 %, p5 +1,73 %). Es la misma apuesta que pedía el encargo,
# calculada sobre el número que la v166 dejó honesto.
#
# QUÉ PUEDE SER RECOMENDADO Y QUÉ NO
# ----------------------------------
#   · un mercado ESTIMADO, nunca (v164): es el nivel de la competición
#     repartido por bando, idéntico en todos sus partidos;
#   · un mercado físico observado, sí, pero SIEMPRE en ámbar: verde en esta
#     aplicación significa «canal con p5 de bootstrap positivo medido» y
#     córners, tarjetas y remates no lo tienen;
#   · el verde exige además precio de la casa con el que contrastar (v165).

# ---------------------------------------------------------------------------
# v168 — EL MERCADO REY MANDA, Y LOS INESTABLES QUEDAN EN CUARENTENA
# ---------------------------------------------------------------------------
# Hasta la v167 la recomendación salía del mercado con más probabilidad, y eso
# daba por hecho que todos los mercados de todas las ligas son igual de
# fiables. Medido sobre los tres ledgers walk-forward (`mercado_estabilidad`),
# no lo son ni de lejos: en el Brasileirão B «Menos de 2,5» calibra a 0,118 —
# más del doble del umbral que este proyecto llama aceptable— mientras los
# remates a puerta calibran a 0,0057. Recomendar goles ahí era recomendar desde
# el peor sitio de esa liga.
#
# Ahora la selección va por el RANKING DE ESTABILIDAD de esa competición, que
# es lo que se pidió: primero el Mercado Rey, y si no llega al 55 % o no pasa
# el control de cordura, el siguiente.
#
# LO QUE SE BLOQUEA, Y NO ES LO MISMO QUE LO QUE NO SE ENSEÑA
# ------------------------------------------------------------
# Un bloque en cuarentena SIGUE VIÉNDOSE con sus probabilidades. Lo que no
# puede es ser la recomendación. Es la misma línea que la v165 trazó con el
# gris: mirar sí, proponer no.
PROB_MINIMA_REY = 0.55        # el suelo que pidió el encargo para el rey
DESVIO_BLOQUEO = 0.10         # por encima de esto NO es jugable (encargo 2.2)

# Cómo se llama cada mercado del pick en el ranking de estabilidad. El nombre
# del board lleva la línea dentro («Menos de 2.5») y el del ranking la lleva
# fuera («Goles 2.5»), así que hace falta traducir.
_BLOQUE_DE = {'1X2': 'resultado', 'Goles': 'goles', 'BTTS': 'btts',
              'Hándicap': 'handicap', 'Córners': 'corners',
              'Tarjetas': 'tarjetas', 'Remates': 'remates',
              'Remates a puerta': 'remates_on'}


def _nombre_en_ranking(mercado: str, apuesta: str) -> str:
    """El nombre con el que ese mercado aparece en `mercado_estabilidad`."""
    m = str(mercado or '')
    if m == 'Goles':
        import re as _re
        g = _re.search(r'([0-9]+(?:[.,][0-9]+)?)', str(apuesta or ''))
        return 'Goles %s' % g.group(1).replace(',', '.') if g else 'Goles 2.5'
    return m


def _estabilidad_de(clave_liga, mercado: str, apuesta: str) -> Dict:
    """Puesto, estado y cuarentena de ese mercado en esa competición."""
    bloque = _BLOQUE_DE.get(str(mercado or ''), 'otros')
    try:
        import mercado_estabilidad as me
        estado = me.estado_bloque(clave_liga, bloque)
        return {'bloque': bloque, 'estado': estado,
                'icono': me.SEMAFORO.get(estado, '⚪'),
                'cuarentena': me.en_cuarentena(clave_liga, bloque),
                'puesto': me.puesto(clave_liga,
                                    _nombre_en_ranking(mercado, apuesta)),
                'rey': me.rey(clave_liga)}
    except Exception as e:
        logger.debug('[modo_modelo] estabilidad de %s: %s', mercado, e)
        # Sin fichero de estabilidad la aplicación sigue: nada en cuarentena y
        # sin puesto, que es como se comportaba antes de la v168.
        return {'bloque': bloque, 'estado': 'sin medir', 'icono': '⚪',
                'cuarentena': False, 'puesto': None, 'rey': None}


MIN_EV_RECOMENDADA = 0.03      # el mismo suelo que `alpha_finder.MIN_EV`
URL_PLAYDOIT = 'https://www.playdoit.mx/deportes'


def _candidata(apuesta, mercado, prob, info, cuota=None, fisico=False,
               clave_liga=None):
    """Una fila candidata a ser la apuesta del partido, ya juzgada."""
    p = float(prob)
    ev = None
    if cuota:
        try:
            ev = float(cuota) * p - 1.0
        except (TypeError, ValueError):
            ev = None
    # El verde sólo para lo que no es físico y ha pasado el contraste.
    verde = (not fisico and p >= UMBRAL_ALTA
             and bool(info.get('puede_verde', False)))
    est = _estabilidad_de(clave_liga, mercado, apuesta)
    # v168 — EL BLOQUEO DURO DEL ENCARGO: mas de 10 puntos de separacion
    # contra la casa y la apuesta NO es jugable. Es mas estricto que el
    # recorte de la v166 (5 pp, que marca y recorta pero deja mirar) y se
    # aplica encima, no en su lugar: uno decide como se ENSEÑA la cifra y el
    # otro si se puede PROPONER.
    imp = info.get('implicita')
    bloqueada = bool(imp is not None and (p - float(imp)) > DESVIO_BLOQUEO)
    return {'apuesta': apuesta, 'mercado': mercado, 'prob': p,
            'cuota': float(cuota) if cuota else None,
            'cuota_justa': round(1.0 / max(p, 1e-6), 2), 'ev': ev,
            'verde': verde, 'fisico': fisico,
            'original': info.get('original', p),
            'fiable': bool(info.get('fiable', True)),
            'contrastada': bool(info.get('contrastada', False)),
            'implicita': imp, 'bloqueada': bloqueada,
            'estabilidad': est, 'bloque': est['bloque'],
            'puesto': est.get('puesto'), 'es_rey': bool(
                est.get('rey') and est['rey'] == _nombre_en_ranking(
                    mercado, apuesta)),
            'aviso': _aviso_cordura(info)}


def _candidatas_fisicas(pick: Dict, bloques: Dict) -> List[Dict]:
    """
    Córners, tarjetas y remates como candidatos — sólo los que se lo han ganado.

    `confianza_mercado` ya decide quién puede llevar insignia: un bloque
    estimado cae al nivel 3 y no la lleva. Aquí se usa exactamente esa misma
    puerta, para que no puedan decir cosas distintas la insignia del bloque y
    la apuesta recomendada de arriba.
    """
    salida = []
    for titulo, bloque in bloques.items():
        if not bloque:
            continue
        conf = bloque.get('confianza') or {}
        if not conf.get('insignia'):
            continue                      # estimado o mal calibrado: no opina
        mejor = bloque.get('mejor')
        if not mejor:
            continue
        etq = '%s %s' % (titulo, mejor['texto'])
        if mejor.get('etiqueta') in ('Local', 'Visita'):
            h, a = _equipos(pick)
            quien = h if mejor['etiqueta'] == 'Local' else a
            etq = '%s de %s: %s' % (titulo, quien or mejor['etiqueta'],
                                    mejor['texto'])
        salida.append(_candidata(
            etq, titulo, mejor['prob'],
            {'puede_verde': False, 'original': mejor['prob'],
             'fiable': True, 'contrastada': False},
            fisico=True, clave_liga=pick.get('clave_liga')))
    return salida


def apuesta_recomendada(pick: Dict, bloques: Optional[Dict] = None
                        ) -> Optional[Dict]:
    """
    La apuesta que hay que meter en este partido, o `None` si no hay ninguna.

    `None` NO es un fallo y se PINTA: un partido sin nada jugable tiene que
    decirlo, porque si no la ausencia de aviso se lee como permiso.
    """
    if pick.get('jugado') or pick.get('sin_modelo'):
        return None
    candidatas = []
    for m in (pick.get('mercados') or []):
        if not isinstance(m, dict) or m.get('apuesta') is None:
            continue
        if str(m.get('origen') or 'observado') == 'estimado':
            continue
        try:
            p0 = float(m.get('prob'))
        except (TypeError, ValueError):
            continue
        mercado = str(m.get('mercado') or '')
        info = _revisar(pick, str(m['apuesta']), p0, mercado=mercado,
                        ya_encogido=bool((m.get('calibracion') or {})
                                         .get('aplicado')))
        candidatas.append(_candidata(str(m['apuesta']), mercado,
                                     info.get('prob', p0), info,
                                     cuota=m.get('cuota'),
                                     clave_liga=pick.get('clave_liga')))
    if not candidatas:
        # Deportes que sólo publican el ganador: queda el board y, tras él, la
        # propia apuesta del pick. Es el mismo camino de `apuesta_destacada` y
        # existe por lo mismo — sin él la tarjeta decía «sin apuesta» en todo
        # partido que no fuera de fútbol.
        d = apuesta_destacada(pick)
        if d:
            candidatas.append(_candidata(
                d['apuesta'], d.get('mercado') or '', d['prob'],
                {'puede_verde': d.get('alta', False),
                 'original': d.get('original', d['prob']),
                 'fiable': d.get('fiable', True),
                 'contrastada': d.get('contrastada', False)},
                cuota=pick.get('cuota'),
                clave_liga=pick.get('clave_liga')))
    candidatas += _candidatas_fisicas(pick, bloques or {})

    # Sólo lo jugable. Una cifra marcada como poco fiable no se recomienda
    # aunque llegue alta — eso es lo que la v165 vino a arreglar.
    #
    # EL SUELO DEL 50 % ES DE LA VÍA DE PROBABILIDAD, NO DE LA DE PRECIO. Una
    # apuesta con ventaja de precio real casi nunca es favorita: el canal
    # medido con p5 positivo del proyecto (+11,49 %) vive precisamente en
    # comprar barato, no en comprar seguro. Filtrarlas por debajo del 50 %
    # habría tirado justo las que sí tienen respaldo medido.
    #
    # v168 — Y ADEMAS DOS PUERTAS NUEVAS, LAS DEL MODO SEGURIDAD:
    #   · CUARENTENA: un bloque cuyo mejor mercado calibra por encima de 0,05
    #     —o cuya varianza dobla a su media— no se propone. Se sigue VIENDO con
    #     sus probabilidades; lo que no puede es ser la recomendacion.
    #   · BLOQUEO A 10 pp: mas de diez puntos por encima de la casa y no es
    #     jugable, por alta que sea la cifra.
    jugables = [c for c in candidatas
                if c['fiable'] and not c['bloqueada']
                and not c['estabilidad']['cuarentena']
                and (c['prob'] >= UMBRAL_PATA
                     or (c['ev'] is not None
                         and c['ev'] >= MIN_EV_RECOMENDADA))]
    if not jugables:
        return None

    # 0) VENTAJA DE PRECIO, ANTES QUE NADA Y TAMBIEN ANTES QUE EL RANKING.
    #
    # El ranking de estabilidad dice DONDE es fiable el modelo. La ventaja de
    # precio dice donde la CASA se ha equivocado, que es otra cosa y es la
    # unica con percentil 5 positivo medido en este proyecto (+11,49 %, p5
    # +1,73 %). Si aparece, manda: una apuesta a la que la casa paga de mas
    # vale mas que una bien calibrada a precio justo.
    con_ev = [c for c in jugables
              if c['ev'] is not None and c['ev'] >= MIN_EV_RECOMENDADA]
    if con_ev:
        elegida = max(con_ev, key=lambda c: c['ev'])
        elegida['motivo'] = 'precio'
        return elegida

    # 1) EL MERCADO REY DE ESTA COMPETICION, Y LUEGO EL SIGUIENTE.
    #
    # Medido sobre los tres ledgers walk-forward: el mercado mas fiable cambia
    # por completo de una liga a otra —handicap en 14 competiciones, cornrs por
    # equipo en 12, remates a puerta en 7, tarjetas en 8— y los goles, que eran
    # de donde salia el 64 % de los titulares, calibran PEOR que casi todo lo
    # demas en todas partes. Asi que se elige por el ranking de esa liga y no
    # por quien tenga el porcentaje mas alto.
    #
    # El suelo del 55 % es el que pidio el encargo. Dentro del mismo puesto
    # manda el precio y despues la probabilidad, que es el orden de la v167.
    por_ranking = [c for c in jugables
                   if c['puesto'] is not None and c['prob'] >= PROB_MINIMA_REY]
    if por_ranking:
        elegida = min(por_ranking,
                      key=lambda c: (c['puesto'],
                                     -(c['ev'] if c['ev'] is not None else -1),
                                     -c['prob']))
        elegida['motivo'] = 'rey' if elegida['es_rey'] else 'estabilidad'
        return elegida

    # 2) si no hay precio que aproveche, la de mayor probabilidad ajustada que
    #    llegue al umbral del verde y pueda llevar color.
    altas = [c for c in jugables if c['prob'] >= UMBRAL_ALTA]
    if altas:
        # EL VERDE GANA AL PORCENTAJE, y no es un detalle de orden. «Jugable en
        # solitario» es una afirmación más fuerte que «un número más alto»: un
        # bloque de córners al 78 % es ámbar porque su ventaja de precio no
        # está medida, y proponerlo por delante de un 64 % que sí ha pasado el
        # contraste sería premiar la cifra grande sobre la comprobada. Además
        # así la tarjeta y el filtro de la lista no pueden divergir.
        elegida = max(altas, key=lambda c: (c['verde'], c['prob']))
        elegida['motivo'] = 'probabilidad'
        return elegida

    # 3) y si nada llega al 60 %, lo mejor que hay para COMBINAR, en ámbar.
    #    Aquí sí manda el suelo del 50 %: sin precio que aproveche, proponer
    #    algo que ni siquiera es más probable que su contrario no es una
    #    recomendación, es rellenar el hueco.
    jugables = [c for c in jugables if c['prob'] >= UMBRAL_PATA]
    if not jugables:
        return None
    elegida = max(jugables, key=lambda c: c['prob'])
    elegida['motivo'] = 'combinar'
    elegida['verde'] = False
    return elegida


def _barra_1x2(pl, px, pv, home: str, away: str) -> str:
    """La barra de tres tramos, con el número dentro cuando cabe."""
    vals = [float(pl), float(px), float(pv)]
    tot = sum(vals)
    if tot <= 0:
        return ''
    colores = ('var(--ok)', 'var(--tenue)', 'var(--info)')
    etqs = ('%s %.0f %%' % (home, vals[0] * 100), 'Empate %.0f %%'
            % (vals[1] * 100), '%s %.0f %%' % (away, vals[2] * 100))
    trozos = []
    for v, col, etq in zip(vals, colores, etqs):
        ancho = v / tot * 100.0
        # El número sólo se escribe si el tramo da de sí: por debajo del 12 %
        # el texto se sale y se lee peor que sin él. El título lo conserva.
        dentro = '%.0f' % (v * 100) if v / tot >= 0.12 else ''
        trozos.append('<span style="width:%.2f%%;background:%s" title="%s">%s'
                      '</span>' % (ancho, col, etq, dentro))
    return '<div class="mm-1x2">%s</div>' % ''.join(trozos)


# Los seis bloques de la tira de estabilidad, con su icono y su rótulo corto.
# Rótulo corto de verdad: la tira se lee de un vistazo o no sirve de nada.
_TIRA = (('resultado', '1X2'), ('goles', 'Goles'), ('btts', 'BTTS'),
         ('corners', 'Córners'), ('tarjetas', 'Tarj.'), ('remates', 'Rem.'))


def _tira_estabilidad(clave_liga) -> str:
    """
    v168 — SEIS ICONOS Y NINGUNA FRASE.

    Dice, de un vistazo, en qué mercados de ESTA competición se puede confiar.
    Sale del ranking medido sobre los ledgers walk-forward, así que no es una
    opinión de diseño: 🟢 es ECE < 0,02, 🟡 hasta 0,05, 🔴 por encima o con la
    varianza doblando a la media, ⚪ sin medir.

    No lleva leyenda debajo a propósito. Una leyenda de tres líneas explicando
    tres colores es justo el párrafo que este rediseño vino a quitar; la
    explicación vive en el desplegable.
    """
    if not clave_liga:
        return ''
    try:
        import mercado_estabilidad as me
    except Exception:
        return ''
    celdas = []
    for bloque, rotulo in _TIRA:
        estado = me.estado_bloque(clave_liga, bloque)
        celdas.append('<span class="mm-est-c" title="%s: %s">%s<br>%s</span>'
                      % (rotulo, estado, me.SEMAFORO.get(estado, '⚪'),
                         rotulo))
    return ('<div class="mm-otros">📊 ESTABILIDAD DEL MERCADO</div>'
            '<div class="mm-tira">%s</div>' % ''.join(celdas))


def _candado(clave_liga, bloque: str) -> str:
    """`🔒` si ese bloque está en cuarentena. Tres palabras, no un párrafo."""
    try:
        import mercado_estabilidad as me
        if me.en_cuarentena(clave_liga, bloque):
            return '<span class="mm-ck-est">🔒 No recomendado</span>'
    except Exception:
        pass
    return ''


def _fila_compacta(icono: str, nombre: str, linea: str, izq: str, der: str,
                   etiqueta: str = '', apagado: bool = False) -> str:
    """
    Una fila de mercado: nombre, línea, los dos lados y una etiqueta CORTA.

    v167 — sin párrafos. Lo que antes eran tres filas y un párrafo de aviso
    («Estimado · esta competición no publica esta estadística: el nivel sale de
    sus goles…») es ahora una línea y una insignia de dos palabras. El párrafo
    no se ha borrado: vive en «📊 Análisis completo», que es donde lo lee quien
    lo quiere leer.
    """
    return (
        '<div class="mm-fc%s">'
        '<span class="mm-fc-n">%s %s</span>'
        '<span class="mm-fc-l">%s</span>'
        '<span class="mm-fc-v">%s</span>'
        '<span class="mm-fc-v">%s</span>'
        '<span class="mm-fc-e">%s</span>'
        '</div>' % (' mm-sinsena' if apagado else '', icono, nombre,
                    linea, izq, der, etiqueta))


def _etiqueta_corta(bloque: Optional[Dict]) -> str:
    """`📐 Estimado`, `🟡 Ámbar` o vacío. Nunca un párrafo."""
    if not bloque:
        return ''
    if (bloque.get('origen') or 'observado') == 'estimado':
        return '<span class="mm-ck-est">📐 Estimado</span>'
    if (bloque.get('confianza') or {}).get('insignia'):
        return '<span class="mm-ck-est">🟡 Ámbar</span>'
    return ''


def _fila_de_bloque(bloque: Optional[Dict], icono: str, nombre: str,
                    clave_liga=None, bloque_nombre: str = '') -> str:
    """La fila compacta de un bloque físico: su TOTAL y nada más."""
    if not bloque:
        return ''
    total = None
    for f in bloque.get('filas') or []:
        if f.get('etiqueta') == 'Total':
            total = f
            break
    if total is None:
        return ''
    otro = 1.0 - float(total['prob'])
    contrario = ('Menos de %.1f' % total['linea']
                 if total['texto'].startswith('Más')
                 else 'Más de %.1f' % total['linea'])
    apagado = not (bloque.get('confianza') or {}).get('insignia')
    # v168 — el candado manda sobre la etiqueta de origen: si el mercado esta
    # en cuarentena, lo que el usuario necesita saber es que no se recomienda,
    # no de donde salen sus cifras.
    cand = _candado(bloque.get('clave_liga') or clave_liga, bloque_nombre)
    return _fila_compacta(
        icono, nombre, '%.1f' % total['linea'],
        '<b>%s: %.0f %%</b>' % (total['texto'].split(' de ')[0], total['prob'] * 100),
        '%s: %.0f %%' % (contrario.split(' de ')[0], otro * 100),
        cand or _etiqueta_corta(bloque), apagado=apagado or bool(cand))


def _fila_dos_lados(icono: str, nombre: str, linea: str, izq, der,
                    etq_izq: str, etq_der: str, etiqueta: str = '') -> str:
    """La fila compacta de un mercado de dos vías del board."""
    if izq is None or der is None:
        return ''
    return _fila_compacta(
        icono, nombre, linea,
        '<b>%s: %.0f %%</b>' % (etq_izq, float(izq) * 100),
        '%s: %.0f %%' % (etq_der, float(der) * 100),
        etiqueta, apagado=bool(etiqueta))


def _quien_remata_compacto(qr: Optional[Dict]) -> str:
    """
    v167 — una fila, no seis líneas de texto.

    Antes: «Sergio Rodelas 32 % de +1.5 · 42 % de +0.5 a puerta» por jugador,
    más el aviso de alineación. Ahora los nombres con su probabilidad y ya; el
    detalle —de qué línea es cada cifra, de dónde sale el once— está en el
    desplegable.
    """
    if not qr:
        return ''
    nombres = []
    for j in ((qr.get('home_jugadores') or [])
              + (qr.get('away_jugadores') or []))[:6]:
        # La línea de la casa manda sobre la nuestra (v164): si Playdoit cotiza
        # a este jugador, su cifra es la de ESA línea. Sin ella, la de rematar.
        p = j.get('p_linea_tot')
        if p is None:
            p = j.get('p_remata')
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        color = ('var(--ok)' if p >= 0.60
                 else 'var(--mira)' if p >= 0.45 else 'var(--tenue)')
        nombres.append('<span style="color:%s">%s <b>%.0f %%</b></span>'
                       % (color, _esc_mm(j.get('jugador') or ''), p * 100))
    if not nombres:
        return ''
    return ('<div class="mm-fc"><span class="mm-fc-n">🎯 Remata</span>'
            '<span class="mm-fc-jug">%s</span></div>'
            % ' &nbsp;·&nbsp; '.join(nombres))


def _esc_mm(t) -> str:
    import html as _html
    return _html.escape(str(t if t is not None else ''), quote=True)


def _bloque_recomendada(st, rec: Optional[Dict], clave: str,
                        n: int = 0) -> None:
    """
    El corazón de la tarjeta: qué meter, a qué precio, y el botón para jugarlo.

    Cuando no hay nada jugable se DICE. Un partido sin recomendación tiene que
    verse tan claro como uno con ella: si el bloque simplemente desapareciera,
    la ausencia se leería como que la app no ha mirado.
    """
    if rec is None:
        st.markdown('<div class="mm-rec mm-rec-no">🚫 <b>Sin apuestas '
                    'jugables</b></div>', unsafe_allow_html=True)
        return
    icono = '✅' if rec['verde'] else '🟡'
    tono = 'mm-rec-si' if rec['verde'] else 'mm-rec-ambar'
    # La coletilla dice POR QUÉ está propuesta, y no siempre es lo mismo. Una
    # apuesta elegida por PRECIO casi nunca es favorita —el canal medido vive
    # en comprar barato, no en comprar seguro— y llamarla «sólo para combinar»
    # la describiría mal.
    # v168 — la coletilla va en SU PROPIA LINEA y en cuatro palabras.
    # Pegada a la apuesta hacia una frase de 53 caracteres, que es justo
    # el parrafo que este rediseño vino a quitar.
    if rec.get('motivo') == 'precio':
        coleta = 'La casa paga de más'
    elif rec['verde']:
        coleta = ''
    else:
        coleta = 'Sólo para combinar'
    precio = ('Cuota %.2f · justa %.2f' % (rec['cuota'], rec['cuota_justa'])
              if rec.get('cuota') else 'Cuota justa: %.2f' % rec['cuota_justa'])
    if rec.get('ev') is not None:
        precio += ' · EV %+.1f %%' % (rec['ev'] * 100)
    st.markdown(
        '<div class="mm-rec %s">'
        '<span class="mm-rec-tit">🏆 APUESTA RECOMENDADA</span>'
        '<span class="mm-rec-ap">%s %s — %.0f %%</span>'
        '<span class="mm-rec-cu">%s %s</span>%s'
        '</div>' % (tono, icono, _esc_mm(rec['apuesta']).upper(),
                    rec['prob'] * 100,
                    (rec.get('estabilidad') or {}).get('icono', ''),
                    precio,
                    ('<span class="mm-rec-cu">%s</span>' % coleta)
                    if coleta else ''),
        unsafe_allow_html=True)
    st.link_button('🎲 Jugar en Playdoit', URL_PLAYDOIT, width='stretch')


def tarjeta(st, pick: Dict, *, navegar: Optional[Callable] = None,
            n_boton: int = 0, con_apuesta: bool = True) -> None:
    """
    v167 — LA TARJETA DEJA DE INFORMAR Y PASA A RECOMENDAR.

    El encargo, con sus palabras: «no quiero leer, quiero apostar». La tarjeta
    enseñaba seis bloques, cuatro párrafos técnicos y ninguna instrucción. Lo
    que hay ahora, de arriba abajo:

        partido · liga · hora
        🏆 APUESTA RECOMENDADA        una, con su cuota y su botón
        📊 OTROS MERCADOS             una fila por mercado, sin párrafos
        📊 Análisis completo          desplegable, cerrado

    NADA SE HA BORRADO. Todo el texto técnico —el párrafo de «Estimado», el
    perfil del árbitro, las rachas, el detalle de quién remata, el aviso de
    cordura— vive dentro del desplegable. Esa es la diferencia entre esconder y
    ordenar: quien quiera el detalle lo tiene a un clic, y quien quiera la
    apuesta la ve sin leer nada.

    `con_apuesta=False` en la vista de mañana: esos partidos no producen picks
    todavía —las líneas se mueven durante la noche y ese movimiento es
    precisamente el canal que este proyecto mide—, así que se enseña el
    análisis y se dice por qué no hay apuesta.
    """
    b = _board(pick)
    h, a = _equipos(pick)
    clave_vista = str(pick.get('_clave_vista', 'x'))
    with st.container(border=True):
        meta = [str(pick.get('deporte') or 'Fútbol'),
                str(pick.get('liga') or '')]
        if pick.get('hora_txt'):
            meta.append('🕐 %s' % pick['hora_txt'])
        st.markdown('**%s**  \n%s' % (pick.get('partido', '?'),
                                      ' · '.join([m for m in meta if m])))

        sin_modelo = bool(pick.get('sin_modelo') or pick.get('prob') is None)
        _ck = corners_tarjeta(pick)
        _tj = tarjetas_tarjeta(pick)
        _rm = remates_tarjeta(pick)
        _qr = quien_remata_tarjeta(pick)

        # ---- 1) la apuesta recomendada, o por qué no la hay --------------
        if pick.get('jugado'):
            gh, ga = pick.get('goles_home'), pick.get('goles_away')
            if gh is not None and ga is not None:
                st.markdown('### ✅ Finalizado — %d &nbsp;–&nbsp; %d'
                            % (int(gh), int(ga)))
            else:
                st.markdown('### ✅ Finalizado')
            st.caption('Sin pronóstico.' if sin_modelo
                       else 'Pronóstico previo. No jugable.')
            rec = None
        elif sin_modelo:
            st.markdown('**· Sin datos de modelo**')
            rec = None
        elif not con_apuesta:
            st.caption('Mañana: sólo análisis.')
            rec = None
        else:
            rec = apuesta_recomendada(
                pick, {'Córners': _ck, 'Tarjetas': _tj,
                       'Remates': (_rm or {}).get('totales')})
            _bloque_recomendada(st, rec, clave_vista, n_boton)

        # ---- 2) otros mercados, en filas compactas ----------------------
        filas = []
        tri = probabilidades_1x2(pick)
        if tri and h and a:
            filas.append(
                '<div class="mm-fc"><span class="mm-fc-n">📊 Resultado</span>'
                '<span class="mm-fc-barra">%s</span></div>'
                % _barra_1x2(tri[0], tri[1], tri[2], h, a))
        filas.append(_fila_dos_lados('⚽', 'Goles', '2.5', b.get(_ETQ_OVER),
                                     b.get(_ETQ_UNDER), 'Más', 'Menos',
                                     _candado(pick.get('clave_liga'), 'goles')))
        filas.append(_fila_dos_lados('🤝', 'Ambos marcan', '',
                                     b.get(_ETQ_BTTS_SI), b.get(_ETQ_BTTS_NO),
                                     'Sí', 'No',
                                     _candado(pick.get('clave_liga'), 'btts')))
        _cl = pick.get('clave_liga')
        filas.append(_fila_de_bloque(_ck, '⛳', 'Córners', _cl, 'corners'))
        filas.append(_fila_de_bloque(_tj, '🟨', 'Tarjetas', _cl, 'tarjetas'))
        filas.append(_fila_de_bloque((_rm or {}).get('totales'), '🎯',
                                     'Remates', _cl, 'remates'))
        filas.append(_quien_remata_compacto(_qr))
        filas = [f for f in filas if f]
        if filas:
            st.markdown(_tira_estabilidad(pick.get('clave_liga'))
                        + '<div class="mm-otros">📊 OTROS MERCADOS</div>'
                        + ''.join(filas), unsafe_allow_html=True)

        if str(pick.get('deporte') or '') == 'Tenis':
            _bloque_tenis(st, pick)

        # ---- 3) y todo el detalle, plegado ------------------------------
        with st.expander('🔍 Análisis'):
            _analisis_completo(st, pick, b, rec, _ck, _tj, _rm, _qr)
            if navegar is not None:
                if st.button('Ver ficha del partido',
                             key='mm_ir_%s_%d' % (clave_vista, n_boton),
                             width='stretch'):
                    navegar(pick)


def _analisis_completo(st, pick: Dict, b: Dict, rec, _ck, _tj, _rm, _qr
                       ) -> None:
    """
    Lo que antes ocupaba la tarjeta entera, ahora a un clic.

    Se conserva ENTERO y sin resumir: los bloques con sus tres filas, el
    párrafo de «Estimado», el árbitro, las rachas y el aviso de cordura. La
    v167 no borró nada de esto — lo movió, que es distinto.
    """
    if rec is not None and rec.get('aviso'):
        st.caption(rec['aviso'])
    piezas = [
        _bloque_goles_html(pick, b),
        _bloque_corners_html(_ck),
        _bloque_tarjetas_html(_tj),
        _bloque_remates_html(_rm),
        _bloque_quien_remata_html(_qr),
    ]
    rend = None
    if str(pick.get('deporte') or '') != 'Tenis':
        rend = _rendimiento(pick)
    if rend:
        disp = rend.get('disponible') or {}
        piezas.append(_bloque_fisico(rend, disp, con_corners=not _ck,
                                     con_tarjetas=not _tj))
        lineas = [x for x in (_mini_forma(rend.get('forma_home'), disp),
                              _mini_forma(rend.get('forma_away'), disp))
                  if x]
        if lineas:
            piezas.append('<div class="mm-forma">%s</div>'
                          % '<br>'.join(lineas))
    piezas = [p for p in piezas if p]
    if piezas:
        st.markdown(''.join(piezas), unsafe_allow_html=True)
    else:
        st.caption('No hay más detalle de este partido.')


# Criterios de orden. El valor es la función que da la CLAVE de ordenación;
# todas devuelven un número que se ordena de mayor a menor salvo la hora.
def _k_hora(p):
    return (str(p.get('inicio') or '~'), str(p.get('partido') or ''))


def _k_local(p):
    tri = probabilidades_1x2(p)
    return -(tri[0] if tri else -1)


def _k_over(p):
    return -(_board(p).get(_ETQ_OVER) or -1)


def _k_btts(p):
    return -(_board(p).get(_ETQ_BTTS_SI) or -1)


def _k_destacada(p):
    return -((p.get('_destacada') or {}).get('prob') or -1)


ORDENES = {
    'Hora': _k_hora,
    'Probabilidad del local': _k_local,
    'Probabilidad de más de 2.5': _k_over,
    'Probabilidad de ambos marcan': _k_btts,
    'Apuesta destacada': _k_destacada,
}


def _tiene_fisicos(p: Dict) -> bool:
    """
    Si esta competición publica córners y tarjetas OBSERVADOS.

    v162 — el filtro sigue existiendo y ahora quiere decir otra cosa. Antes
    separaba «tiene sección» de «no la tiene»; desde que todas las
    competiciones la tienen —con estimación donde no hay datos— lo que separa
    es **observado de estimado**, que es la distinción que de verdad importa
    para decidir si un número se puede usar.
    """
    try:
        import rendimiento_equipos as rq
        d = rq.stats_disponibles(str(p.get('clave_liga') or ''))
        return bool(d.get('corners') and d.get('tarjetas'))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# v161 → v162 — LOS PARTIDOS QUE YA SE JUGARON
# ---------------------------------------------------------------------------
# La v161 los puso detrás de un BOTÓN, en una lista escueta con el marcador.
# Duró una versión: lo que se quería era verlos EN la lista, con su tarjeta
# entera y el pronóstico previo, y un desplegable aparte no es eso. El botón y
# su función se han retirado — los construye `partidos_jugados.de_dia` y los
# mezcla `render`. Lo único que sobrevive de aquel bloque es `_dia_de`, que
# sigue diciendo qué día está enseñando la lista.
#
# Lo que NO cambió, y es lo importante: siguen fuera de `alpha_finder`. No
# tienen EV, no se comparan con la cuota y no pueden llegar a Telegram.
# La lista enseña los partidos que se pueden apostar, o sea los que no han
# empezado. Es lo correcto —un partido acabado no es un pick— pero tiene un
# efecto que parece un fallo: un sábado por la tarde la lista se queda casi
# vacía. Medido el 2026-08-22, ESPN tenía 224 partidos de fútbol ese día y la
# aplicación enseñaba 55. La mayor parte de la diferencia eran partidos ya
# jugados, y desde fuera eso se lee como «faltan partidos».
#
# Aquí salen, con su marcador, separados de los apostables y SIN apuesta. Tres
# decisiones que van juntas:
#
#   · **bajo demanda, con un botón.** Son 61 peticiones a ESPN. El barrido
#     tardó de la v148 a la v154 en bajar de 119 s a 52 y no puede pagarlas en
#     cada carga. Pulsando, cuestan ~5 s y quedan en la caché de 5 minutos.
#   · **fuera de `pronosticos`.** No pasan por `tarjeta()` ni por la Sección 1:
#     un partido con resultado no puede convertirse en un pick ni salir por
#     Telegram por accidente.
#   · **sin probabilidad.** Enseñar lo que el modelo «habría dicho» de un
#     partido ya jugado es la clase de cifra que sólo sirve para engañarse.
def _dia_de(pronosticos: List[Dict]) -> str:
    """
    El día que está enseñando esta lista, EN HORA DE CDMX.

    v163.1 — ANTES DEVOLVÍA EL DÍA UTC Y ESO METÍA PARTIDOS DE AYER. Leía
    `p['fecha']`, que es el día en UTC, y con él pedía los jugados. Como México
    va seis horas por detrás, el día UTC de un partido de la tarde mexicana es
    el SIGUIENTE, así que la lista de hoy se llenaba con los partidos de ayer
    por la tarde — el usuario lo vio el 2026-08-23 a la 01:21, con un
    Barcelona SC-Orense del día 22 rotulado como de hoy.

    Ahora se calcula desde `inicio`, que es la marca completa, igual que hace
    la pantalla para pintar la hora. Lo normal es que quien llama pase el día
    explícito (`render(..., dia=...)`); esto es el respaldo.
    """
    for p in (pronosticos or []):
        if not isinstance(p, dict):
            continue
        try:
            import fixtures_espn
            f = fixtures_espn.fecha_local(p.get('inicio'), p.get('fecha'))
        except Exception:
            f = str(p.get('fecha') or '')[:10]
        if len(f) == 10:
            return f
    try:
        import horario
        import pandas as _pd
        return horario.fecha(_pd.Timestamp.now('UTC')) or ''
    except Exception:
        return ''


def render(st, pronosticos: List[Dict], *, navegar: Optional[Callable] = None,
           clave: str = 'mm', maximo: int = 200, con_apuesta: bool = True,
           titulo: str = '⚽ Partidos de hoy',
           dia: Optional[str] = None) -> None:
    """
    La lista de partidos, con sus filtros y su orden.

    `clave` separa el estado de sesión de cada vista, así que hoy y mañana
    pueden tener criterios distintos. Streamlit conserva la elección mientras
    dure la sesión; entre sesiones distintas no se guarda —eso necesitaría
    almacenamiento propio y no lo hay.

    v162 — `maximo` sube de 40 a 200, y no es por gusto. Desde que los partidos
    ya jugados entran en la misma lista ordenados por hora, son los PRIMEROS
    (se jugaron antes), así que un tope de 40 los habría dejado ocupando la
    lista entera y habría empujado fuera los partidos que todavía se pueden
    apostar — exactamente lo contrario de lo que se pidió. El tope sigue
    existiendo para que la página no se vaya de las manos un sábado, y cuando
    corta lo dice.
    """
    # v162 — LOS YA JUGADOS ENTRAN EN LA MISMA LISTA.
    #
    # La v161 los puso detrás de un botón, en una lista escueta con el
    # marcador. Lo que se pidió después es verlos aquí, con su tarjeta entera y
    # el pronóstico que había ANTES del pitido inicial, para poder analizar.
    #
    # Vienen de `partidos_jugados.de_dia`, que NO pasa por `alpha_finder`: no
    # tienen EV, no se comparan con la cuota y no pueden llegar a Telegram. La
    # única forma de que un partido acabado se convirtiera en un pick sería
    # meterlo en el barrido, y eso sigue sin ocurrir.
    #
    # Sólo en la vista con apuesta —la de HOY—: mañana no hay nada jugado, y
    # pedirlo igualmente serían 61 peticiones a ESPN para una lista vacía.
    jugados: List[Dict] = []
    if con_apuesta:
        try:
            import partidos_jugados
            # v163.1 — EL DÍA LO DICE QUIEN LLAMA, y no se adivina de la lista.
            # `dashboard_ui` ya sabe qué día está enseñando (lo usa para
            # repartir hoy/mañana en hora de CDMX), así que pasarlo es exacto.
            # Deducirlo del primer partido funcionaba sólo mientras la lista no
            # estuviera vacía y mientras su `fecha` fuera del mismo día que el
            # rótulo, y ninguna de las dos cosas está garantizada.
            jugados = partidos_jugados.de_dia(dia or _dia_de(pronosticos))
        except Exception as e:
            logger.debug('[modo_modelo] partidos jugados: %s', e)

    con, sin = [], []
    for p in (list(pronosticos or []) + jugados):
        if not isinstance(p, dict):
            continue
        p['_clave_vista'] = clave
        # Un partido JUGADO va siempre a la lista principal, tenga pronóstico o
        # no: se pidió verlos todos, y esconder en un desplegable el que no
        # tiene modelo volvería a dejar la lista corta sin decir por qué.
        if p.get('jugado'):
            con.append(p)
        elif p.get('sin_modelo') or p.get('prob') is None:
            sin.append(p)
        else:
            con.append(p)

    for p in con:
        p['_destacada'] = None if p.get('jugado') else apuesta_destacada(p)
        # v167 — EL FILTRO Y LA TARJETA TIENEN QUE DECIR LO MISMO.
        #
        # El recuento y la casilla de «solo alta probabilidad» miraban
        # `_destacada`, y la tarjeta enseña ahora la recomendada. Dos
        # criterios para la misma pregunta acaban divergiendo — la lista diria
        # que hay veinte oportunidades y las tarjetas enseñarian otra cosa.
        #
        # Se calcula SIN los bloques fisicos a proposito: cornrs, tarjetas y
        # remates nunca pueden ir en verde (no tienen p5 medido), asi que no
        # cambian la respuesta a «cuantas hay jugables en solitario» y pedirlos
        # aqui costaria tres consultas por partido en una pantalla que ya tarda.
        p['_recomendada'] = (None if p.get('jugado')
                             else apuesta_recomendada(p))
    # Los jugados no cuentan para «N con una apuesta por encima del 60 %»: esa
    # frase es un recuento de oportunidades, y una oportunidad que ya pasó no
    # lo es.
    n_altas = sum(1 for p in con
                  if not p.get('jugado')
                  and (p.get('_recomendada') or {}).get('verde'))
    n_jugados = sum(1 for p in con if p.get('jugado'))

    c1, c2 = st.columns([3, 2])
    with c1:
        etq_orden = st.selectbox('Ordenar por', list(ORDENES),
                                 key='%s_orden' % clave)
    with c2:
        if con_apuesta:
            solo_altas = st.checkbox('Sólo alta probabilidad (%d %%)'
                                     % (UMBRAL_ALTA * 100),
                                     key='%s_solo_altas' % clave,
                                     help='Deja sólo las apuestas que llegan '
                                          'al %d %% Y se pueden contrastar con '
                                          'el precio de la casa sin separarse '
                                          'más de %d puntos. Una cifra alta que '
                                          'nadie ha podido contradecir no entra '
                                          'aquí.'
                                          % (UMBRAL_ALTA * 100, 15))
        else:
            solo_altas = False
        solo_fisicos = st.checkbox('Sólo con córners y tarjetas',
                                   key='%s_solo_fisicos' % clave,
                                   help='Deja sólo las competiciones que '
                                        'publican esas estadísticas de verdad. '
                                        'El resto también las enseña, pero '
                                        'estimadas a partir de sus goles.')

    if solo_altas:
        # Los jugados salen también de aquí: ese filtro sirve para buscar
        # apuestas, y en un partido acabado no queda ninguna que hacer.
        con = [p for p in con
               if (p.get('_recomendada') or {}).get('verde')]
    if solo_fisicos:
        con = [p for p in con if _tiene_fisicos(p)]

    con.sort(key=ORDENES.get(etq_orden, _k_hora))

    st.subheader('%s (%d)' % (titulo, len(con)))
    if n_altas and con_apuesta:
        st.caption('%d con una apuesta por encima del %d %%.'
                   % (n_altas, UMBRAL_ALTA * 100))
    if n_jugados:
        st.caption('Los partidos marcados como **✅ Finalizado** (%d) muestran '
                   'el pronóstico previo para análisis, pero ya no son '
                   'jugables.' % n_jugados)

    st.markdown(CSS, unsafe_allow_html=True)
    if not con:
        st.info('No hay partidos que cumplan el filtro.')
    else:
        for i, p in enumerate(con[:maximo]):
            tarjeta(st, p, navegar=navegar, n_boton=i, con_apuesta=con_apuesta)
        if len(con) > maximo:
            st.caption('Se muestran %d de %d.' % (maximo, len(con)))

    if sin:
        with st.expander('Sin datos de modelo (%d)' % len(sin)):
            for p in sin[:maximo]:
                st.markdown('· **%s** — %s' % (p.get('partido', '?'),
                                               p.get('liga', '')))

    # LA ADVERTENCIA NO DESAPARECE: SE PLIEGA.
    #
    # Los textos técnicos salieron de las tarjetas, que era lo pedido. Pero el
    # porcentaje es la probabilidad del MODELO, y este proyecto tiene medido que
    # guiarse por ella pierde entre −4,66 % y −6,52 % sobre 37.158 apuestas.
    # Enseñarla como recomendación sin que en NINGUNA parte de la pantalla se
    # pueda leer lo que rinde convertiría la aplicación en lo contrario de lo
    # que es. Va una vez, al pie y cerrada.
    with st.expander('¿Qué significa este porcentaje?'):
        st.markdown(
            'Es lo que cree **el modelo**, no lo que paga la casa.\n\n'
            '- Una probabilidad alta **no** significa que la apuesta sea '
            'rentable: si la casa ya la tiene bien puesta, no hay nada que '
            'ganar. Medido aquí, guiarse sólo por la probabilidad del modelo '
            'pierde alrededor de un 5 %.\n'
            '- Donde sí hay ventaja medida es en **comprar al mejor precio**, '
            'y eso está en «Ventaja de precio», más abajo.\n'
            '- Las rachas, los córners y las tarjetas son datos **observados** '
            'de los últimos 5 partidos, no predicciones.\n'
            '- Los córners no llevan porcentaje a propósito: el modelo predice '
            'para ellos la media de la competición, igual en todos sus '
            'partidos, así que un «Más de 9.5: 52 %» diría más de la liga que '
            'de este partido.')
