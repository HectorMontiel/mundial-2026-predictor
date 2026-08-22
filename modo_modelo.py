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


def tarjeta(st, pick: Dict, *, navegar: Optional[Callable] = None,
            n_boton: int = 0) -> None:
    """
    Una tarjeta: qué apostar, con cuánta probabilidad, y cómo llegan los dos.

    Sin explicaciones dentro. Lo que hay que leer es una línea —la apuesta y su
    porcentaje— y debajo dos rachas de colores. Todo lo demás (de dónde salen
    los datos, qué rinde este orden, la cuota justa) vive en el desplegable del
    pie, una vez, y no repetido en cada partido.
    """
    dest = pick.get('_destacada') if '_destacada' in pick \
        else apuesta_destacada(pick)
    with st.container(border=True):
        meta = [str(pick.get('deporte') or 'Fútbol'), str(pick.get('liga') or '')]
        if pick.get('hora_txt'):
            meta.append('🕐 %s' % pick['hora_txt'])
        st.markdown('**%s**  \n%s' % (pick.get('partido', '?'),
                                      ' · '.join([m for m in meta if m])))

        if pick.get('sin_modelo') or pick.get('prob') is None:
            st.markdown('**· Sin datos de modelo**')
        elif dest is None:
            st.markdown('⚠️ **Sin apuesta clara**')
        elif dest['alta']:
            st.markdown('### ✅ %s — %.0f %%'
                        % (dest['apuesta'], dest['prob'] * 100))
        else:
            st.markdown('🟡 **%s — %.0f %%** · sólo para combinar'
                        % (dest['apuesta'], dest['prob'] * 100))

        if str(pick.get('deporte') or '') == 'Tenis':
            _bloque_tenis(st, pick)
        else:
            rend = _rendimiento(pick)
            if rend:
                disp = rend.get('disponible') or {}
                lineas = [x for x in (_mini_forma(rend.get('forma_home'), disp),
                                      _mini_forma(rend.get('forma_away'), disp))
                          if x]
                if lineas:
                    st.markdown(
                        '<div style="font-size:.86rem;line-height:1.8">'
                        + '<br>'.join(lineas) + '</div>',
                        unsafe_allow_html=True)

        if navegar is not None:
            if st.button('Ver partido', key='mm_ir_%d' % n_boton,
                         width='stretch'):
                navegar(pick)


def render(st, pronosticos: List[Dict], *, navegar: Optional[Callable] = None,
           clave: str = 'mm', maximo: int = 40) -> None:
    """
    La pantalla entera: los partidos del día, cada uno con su apuesta.

    `pronosticos` llega YA filtrada por día, deporte y grupo de competición:
    esos tres ejes viven en la barra de arriba y afectan a todas las pestañas a
    la vez, para que no haya dos reglas de reparto que puedan divergir.
    """
    con, sin = [], []
    for p in (pronosticos or []):
        if not isinstance(p, dict):
            continue
        (sin if (p.get('sin_modelo') or p.get('prob') is None)
         else con).append(p)

    # La apuesta se calcula UNA vez por partido y se guarda al lado: el filtro,
    # el orden y la tarjeta necesitan lo mismo, y recalcularlo en cada sitio es
    # como acaban divergiendo tres criterios que deberían ser uno.
    for p in con:
        p['_destacada'] = apuesta_destacada(p)
    n_altas = sum(1 for p in con
                  if p.get('_destacada') and p['_destacada']['alta'])

    c1, c2 = st.columns([2, 1])
    with c1:
        orden = st.radio('Orden', ['Por hora', 'Por probabilidad'],
                         horizontal=True, key='%s_orden' % clave,
                         label_visibility='collapsed')
    with c2:
        solo_altas = st.checkbox('Sólo alta probabilidad (%d %%)'
                                 % (UMBRAL_ALTA * 100),
                                 key='%s_solo_altas' % clave)

    if solo_altas:
        con = [p for p in con
               if p.get('_destacada') and p['_destacada']['alta']]

    if orden == 'Por probabilidad':
        con.sort(key=lambda p: -((p.get('_destacada') or {}).get('prob') or 0))
    else:
        # Sin hora, al final: `~` ordena después de cualquier dígito, así que un
        # partido sin `inicio` no se cuela arriba por comparar contra el vacío.
        con.sort(key=lambda p: (str(p.get('inicio') or '~'),
                                str(p.get('partido') or '')))

    st.subheader('⚽ Partidos de hoy (%d)' % len(con))
    if n_altas:
        st.caption('%d con una apuesta por encima del %d %%.'
                   % (n_altas, UMBRAL_ALTA * 100))

    if not con:
        st.info('No hay partidos que cumplan el filtro.')
    else:
        for i, p in enumerate(con[:maximo]):
            tarjeta(st, p, navegar=navegar, n_boton=i)
        if len(con) > maximo:
            st.caption('Se muestran %d de %d.' % (maximo, len(con)))

    if sin:
        with st.expander('Sin datos de modelo (%d)' % len(sin)):
            for p in sin[:maximo]:
                st.markdown('· **%s** — %s' % (p.get('partido', '?'),
                                               p.get('liga', '')))

    # LA ADVERTENCIA NO DESAPARECE: SE PLIEGA.
    #
    # El encargo era quitar los textos técnicos de las tarjetas, y de las
    # tarjetas están quitados. Pero este porcentaje es la probabilidad del
    # MODELO, y este proyecto tiene medido que apostar guiándose por ella pierde
    # entre −4,66 % y −6,52 % sobre 37.158 apuestas. Enseñarla como recomendación
    # sin que en NINGUNA parte de la pantalla se pueda leer lo que rinde
    # convertiría la aplicación en lo contrario de lo que es. Va una vez, al pie
    # y cerrada, en vez de encima de cada partido.
    with st.expander('¿Qué significa este porcentaje?'):
        st.markdown(
            'Es lo que cree **el modelo**, no lo que paga la casa.\n\n'
            '- Una probabilidad alta **no** significa que la apuesta sea '
            'rentable: si la casa ya la tiene bien puesta, no hay nada que '
            'ganar. Medido aquí, guiarse sólo por la probabilidad del modelo '
            'pierde alrededor de un 5 %.\n'
            '- Donde sí hay ventaja medida es en **comprar al mejor precio**, '
            'y eso está en la pestaña de al lado.\n'
            '- Las rachas de colores y los goles son datos observados de los '
            'últimos 5 partidos.')
