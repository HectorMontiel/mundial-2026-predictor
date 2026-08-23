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

    ✅ Menos de 2.5 goles — 72 %      (verde:   ≥ 60 %)
    🟡 Gana el Barcelona — 55 %       (ámbar:   ≥ 50 %, sólo para combinar)
    ⚠️ Sin apuesta clara              (nada llega al 50 %)

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
        try:
            p = float(m.get('prob'))
        except (TypeError, ValueError):
            continue
        filas.append((p, str(m.get('apuesta') or ''),
                      str(m.get('mercado') or '')))
    if not filas:
        # Sin `mercados` (deportes que sólo publican el ganador) queda el board.
        for etiqueta, p in (pick.get('board') or {}).items():
            try:
                filas.append((float(p), str(etiqueta), ''))
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
            filas.append((p, str(pick['apuesta']), str(pick.get('mercado') or '')))
    if not filas:
        return None
    p, apuesta, mercado = max(filas, key=lambda f: f[0])
    if p < UMBRAL_PATA:
        return None
    return {'prob': p, 'apuesta': apuesta, 'mercado': mercado,
            'alta': p >= UMBRAL_ALTA}


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
    if not lineas:
        return fila25
    otras = []
    for etq in ('1.5', '3.5'):
        try:
            p = float(lineas[etq])
        except (KeyError, TypeError, ValueError):
            continue
        otras.append('Más %s <b>%.0f %%</b> · Menos %s %.0f %%'
                     % (etq, p * 100, etq, (1.0 - p) * 100))
    if not otras:
        return fila25
    if not fila25:
        # sin la de 2,5 no hay barra, pero las otras dos siguen valiendo
        fila25 = '<div class="mm-merc"><div class="mm-merc-tit">⚽ Goles</div></div>'
    return fila25 + ('<div class="mm-ck-fila mm-goles-otras">%s</div>'
                     % ' &nbsp;·&nbsp; '.join(otras))


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
    return _filas_de(eq, '⛳')


def _filas_de(eq: Dict, icono: str) -> Optional[Dict]:
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
        lado = _mejor_lado(tot, _linea_cercana(tot), disp_tot)
        if lado:
            filas.append({'etiqueta': 'Total', 'media': float(tot), **lado})
    for nombre, media in (('Local', eq.get('lambda_home')),
                          ('Visita', eq.get('lambda_away'))):
        if not media:
            continue
        lado = _mejor_lado(media, _linea_cercana(media), eq.get('dispersion'))
        if lado:
            filas.append({'etiqueta': nombre, 'media': float(media), **lado})
    if not filas:
        return None
    return {'filas': filas, 'mejor': max(filas, key=lambda f: f['prob']),
            'origen': eq.get('origen') or 'observado',
            'aceptable': eq.get('aceptable', True),
            'error_calibracion': eq.get('error_calibracion'),
            'base': eq.get('base'), 'icono': icono}


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
    if not bloque:
        return ''
    mejor = bloque['mejor']
    estimado = (bloque.get('origen') or 'observado') == 'estimado'
    trozos = ['<div class="mm-ck-tit">%s <b>%s</b>%s '
              '<span class="mm-ck-badge">🟡 destacado: %s %s &nbsp;%.0f %%'
              '</span></div>'
              % (icono, titulo,
                 ' <span class="mm-ck-est">estimado</span>' if estimado else '',
                 mejor['etiqueta'], mejor['texto'], mejor['prob'] * 100)]
    for f in bloque['filas']:
        resalta = ' mm-ck-mejor' if f is mejor else ''
        trozos.append(
            '<div class="mm-ck-fila%s">%s <b>%.1f</b> · %s '
            '<span class="mm-ck-pct">%.0f %%</span></div>'
            % (resalta, f['etiqueta'], f['media'], f['texto'],
               f['prob'] * 100))
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
    bloque = _filas_de(tj, '🟨')
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
            bloque = _filas_de(eq[nombre], icono)
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
            if j.get('p_remata') is None:
                continue
            corto = '*' if j.get('muestra_corta') else ''
            # LAS DOS PROBABILIDADES, QUE ES LO QUE SE PIDIÓ: rematar y rematar
            # A PUERTA. Son dos mercados distintos y la casa los cotiza por
            # separado, así que enseñar sólo el primero obliga a adivinar el
            # segundo — y no se adivina: la puntería de un jugador es suya, no
            # una fracción fija.
            if j.get('p_al_arco') is not None:
                partes.append('%s <b>%.0f %%</b> / %.0f %% a puerta%s'
                              % (j.get('jugador'), j['p_remata'] * 100,
                                 j['p_al_arco'] * 100, corto))
            else:
                partes.append('%s <b>%.0f %%</b>%s'
                              % (j.get('jugador'), j['p_remata'] * 100, corto))
        if partes:
            trozos.append('<div class="mm-ck-fila">%s · %s</div>'
                          % (equipo, ' &nbsp;·&nbsp; '.join(partes)))
    if len(trozos) == 1:
        return ''
    # el pie: qué son esas probabilidades y qué NO son
    pie = ('probabilidad de tirar al menos un remate, y de que al menos uno '
           'vaya a puerta. Son informativas: el mercado de jugador no tiene '
           'aquí ventaja de precio medida.')
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
</style>
"""


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


def tarjeta(st, pick: Dict, *, navegar: Optional[Callable] = None,
            n_boton: int = 0, con_apuesta: bool = True) -> None:
    """
    La tarjeta de un partido. La MISMA para hoy y para mañana.

    `con_apuesta=False` en la vista de mañana: esos partidos no producen picks
    todavía —las líneas se mueven durante la noche y ese movimiento es
    precisamente el canal que este proyecto mide—, así que se enseña el análisis
    entero y se dice por qué no hay apuesta, en vez de proponer una que mañana
    no valdrá.
    """
    dest = pick.get('_destacada') if '_destacada' in pick \
        else apuesta_destacada(pick)
    b = _board(pick)
    with st.container(border=True):
        meta = [str(pick.get('deporte') or 'Fútbol'), str(pick.get('liga') or '')]
        if pick.get('hora_txt'):
            meta.append('🕐 %s' % pick['hora_txt'])
        st.markdown('**%s**  \n%s' % (pick.get('partido', '?'),
                                      ' · '.join([m for m in meta if m])))

        sin_modelo = bool(pick.get('sin_modelo') or pick.get('prob') is None)
        # v162 — UN PARTIDO ACABADO NO PROPONE NADA, Y LO DICE ARRIBA.
        #
        # La línea de apuesta destacada se sustituye por el marcador. No es
        # decoración: `apuesta_destacada` devolvería «Menos de 2.5 — 72 %» de
        # un partido que ya terminó 3-1, y eso leído deprisa parece una
        # recomendación. El resto de la tarjeta sí se pinta entera —barras,
        # córners, tarjetas, rachas— porque es lo que se pidió: poder mirar qué
        # decía el modelo ANTES, con el resultado al lado.
        if pick.get('jugado'):
            gh, ga = pick.get('goles_home'), pick.get('goles_away')
            if gh is not None and ga is not None:
                st.markdown('### ✅ Finalizado — %d &nbsp;–&nbsp; %d'
                            % (int(gh), int(ga)))
            else:
                st.markdown('### ✅ Finalizado')
            if sin_modelo:
                st.caption('No hay pronóstico guardado de este partido.')
            else:
                st.caption('Lo de abajo es el pronóstico PREVIO al partido, '
                           'para análisis. Ya no es jugable.')
        elif sin_modelo:
            st.markdown('**· Sin datos de modelo**')
        elif not con_apuesta:
            st.caption('Se analiza, no se apuesta todavía: las líneas se mueven '
                       'durante la noche.')
        elif dest is None:
            st.markdown('⚠️ **Sin apuesta clara**')
        elif dest['alta']:
            st.markdown('### ✅ %s — %.0f %%'
                        % (dest['apuesta'], dest['prob'] * 100))
        else:
            st.markdown('🟡 **%s — %.0f %%** · sólo para combinar'
                        % (dest['apuesta'], dest['prob'] * 100))

        h, a = _equipos(pick)
        piezas = []
        tri = probabilidades_1x2(pick)
        if tri and h and a:
            piezas.append('<div class="mm-merc-tit">📊 Resultado</div>')
            piezas.append(_barra_1x2(tri[0], tri[1], tri[2], h, a))
        piezas.append(_bloque_goles_html(pick, b))
        piezas.append(_fila_mercado('🤝', 'Ambos marcan', b.get(_ETQ_BTTS_SI),
                                    b.get(_ETQ_BTTS_NO), 'Sí', 'No'))
        # Los córners van DEBAJO de goles y ambos marcan, y sólo en las 20
        # competiciones que los publican: donde no hay datos, la sección
        # desaparece en vez de rellenarse con la estimación del xG sintético.
        _ck_tarjeta = corners_tarjeta(pick)
        piezas.append(_bloque_corners_html(_ck_tarjeta))
        # v160 — y las tarjetas justo debajo, con la misma forma. Sólo en las 20
        # competiciones que las publican observadas; en las otras 55 la sección
        # desaparece, igual que la de córners.
        _tj_tarjeta = tarjetas_tarjeta(pick)
        piezas.append(_bloque_tarjetas_html(_tj_tarjeta))
        # v163.1 - DE REMATES, EN LA TARJETA, SOLO QUIEN LOS TIRA.
        #
        # Los bloques por EQUIPO (total, local y visita) se retiraron de aqui a
        # peticion del usuario: «lo unico que me interesa saber es quien
        # remata». No se han borrado, siguen enteros en la ficha del partido
        # (`dashboard_ui.render_remates_partido`), que es donde se va a mirar
        # el detalle. `remates_tarjeta` y `_bloque_remates_html` se conservan
        # por lo mismo: volver a ponerlos aqui es una linea.
        #
        # Y habia un motivo tecnico que apunta en la misma direccion: en las 17
        # competiciones sin remates observados el bloque era IDENTICO en todos
        # sus partidos —lo dice su propia etiqueta, «es igual para todos sus
        # partidos»—, asi que ocupaba seis lineas de tarjeta sin distinguir un
        # partido de otro.
        piezas.append(_bloque_quien_remata_html(quien_remata_tarjeta(pick)))

        rend = None
        if str(pick.get('deporte') or '') != 'Tenis':
            rend = _rendimiento(pick)
        if rend:
            disp = rend.get('disponible') or {}
            piezas.append(_bloque_fisico(rend, disp,
                                        con_corners=not _ck_tarjeta,
                                        con_tarjetas=not _tj_tarjeta))
            lineas = [x for x in (_mini_forma(rend.get('forma_home'), disp),
                                  _mini_forma(rend.get('forma_away'), disp))
                      if x]
            if lineas:
                piezas.append('<div class="mm-forma">%s</div>'
                              % '<br>'.join(lineas))
        piezas = [p for p in piezas if p]
        if piezas:
            st.markdown(''.join(piezas), unsafe_allow_html=True)
        if str(pick.get('deporte') or '') == 'Tenis':
            _bloque_tenis(st, pick)

        if navegar is not None:
            if st.button('Ver partido', key='mm_ir_%s_%d'
                         % (pick.get('_clave_vista', 'x'), n_boton),
                         width='stretch'):
                navegar(pick)


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
    # Los jugados no cuentan para «N con una apuesta por encima del 60 %»: esa
    # frase es un recuento de oportunidades, y una oportunidad que ya pasó no
    # lo es.
    n_altas = sum(1 for p in con
                  if not p.get('jugado')
                  and p.get('_destacada') and p['_destacada']['alta'])
    n_jugados = sum(1 for p in con if p.get('jugado'))

    c1, c2 = st.columns([3, 2])
    with c1:
        etq_orden = st.selectbox('Ordenar por', list(ORDENES),
                                 key='%s_orden' % clave)
    with c2:
        if con_apuesta:
            solo_altas = st.checkbox('Sólo alta probabilidad (%d %%)'
                                     % (UMBRAL_ALTA * 100),
                                     key='%s_solo_altas' % clave)
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
               if p.get('_destacada') and p['_destacada']['alta']]
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
