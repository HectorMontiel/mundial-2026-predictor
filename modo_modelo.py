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

LO QUE ESTA PANTALLA TIENE QUE DECIR, Y DICE
--------------------------------------------
Ordenar por probabilidad del modelo NO es un criterio de apuesta rentable en
este proyecto, y está medido: apostar la probabilidad del modelo pierde entre
−4,66 % y −6,52 % sobre 37.158 apuestas, y su EV es anti-indicador del cierre
(correlación −0,054). Ocultar eso para que la pantalla se vea mejor sería
exactamente lo que la aplicación lleva veinte versiones desmontando.

Así que la pantalla se entrega con la advertencia dentro, no debajo: es una
LECTURA del rendimiento, y la decisión de jugar sigue viviendo en la Sección 1.
El usuario pidió ver el rendimiento y lo ve; lo que no se hace es dejar de decir
lo que ese orden rinde.

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


def _prob(pick: Dict) -> float:
    """La probabilidad del pick como número, o 0 si no lo es."""
    try:
        v = float(pick.get('prob'))
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v != v else v          # NaN ordena como el que menos


def _equipos(pick: Dict):
    """Los dos nombres del partido, o (None, None) si el rótulo no se parte."""
    nom = str(pick.get('partido') or '')
    for sep in (' vs ', ' vs. ', ' @ ', ' - '):
        if sep in nom:
            h, a = nom.split(sep, 1)
            return h.strip(), a.strip()
    return None, None


def _recomendado(pick: Dict) -> Optional[str]:
    """
    A quién señala el modelo, deducido de la etiqueta de la apuesta.

    Se compara por NOMBRE contra los dos equipos del partido, no por precio: la
    v151 ya corrigió un test que deducía los bandos comparando cuotas y daba
    falsos positivos. Si la apuesta no es un 1X2 de ganador, devuelve None y la
    tarjeta lo dice en vez de inventarse un favorito.
    """
    ap = str(pick.get('apuesta') or '')
    h, a = _equipos(pick)
    if not h or not a:
        return None
    # La coincidencia MÁS LARGA, no la primera. Con `Boca` y `Boca Juniors` en
    # el mismo partido, «Gana Boca Juniors» contiene a los dos y el primero que
    # se pruebe gana: eso es el mismo tipo de atajo que en la v148 hizo que
    # «Independiente Rivadavia» mapeara a «Independiente».
    candidatos = [eq for eq in (h, a) if eq and eq in ap]
    if candidatos:
        return max(candidatos, key=len)
    if 'mpate' in ap:
        return 'Empate'
    return None


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


def _linea_forma(st, f: Dict, disp: Dict, etiqueta: str) -> None:
    """
    Una línea por equipo: racha, goles, córners y remates de sus últimos 5.

    Cada estadística sale SÓLO si la competición la publica de verdad (`disp`
    viene de `rendimiento_equipos.stats_disponibles`, que lo comprueba
    reproduciendo el generador sintético). Una liga sin córners observados no
    enseña una fila de córners con un número inventado dentro.
    """
    if not f or not f.get('n'):
        st.caption('%s · sin partidos suficientes en el histórico' % etiqueta)
        return
    trozos = ['**%s** `%s`' % (f.get('equipo', etiqueta), f.get('racha', ''))]
    trozos.append('%.2f pts/partido' % f['pts_por_partido'])
    if disp.get('goles') and f.get('gf_media') is not None:
        trozos.append('goles %.1f–%.1f' % (f['gf_media'], f['gc_media']))
    if disp.get('corners') and f.get('ck_favor') is not None:
        trozos.append('córners %.1f–%.1f' % (f['ck_favor'], f['ck_contra']))
    if disp.get('remates') and f.get('remates_favor') is not None:
        trozos.append('remates %.1f–%.1f' % (f['remates_favor'],
                                             f['remates_contra']))
    st.markdown(' · '.join(trozos))


def _texto_momentum(m: Optional[Dict]) -> str:
    if not m:
        return ''
    flecha = {'sube': '📈', 'baja': '📉', 'igual': '➡️'}.get(m['tendencia'], '')
    return ('%s %.2f → %.2f pts/partido' % (flecha, m['anterior'], m['reciente']))


def _bloque_corners(st, pick: Dict, rend: Dict, disp: Dict) -> None:
    """
    Los córners del partido, con el número y de dónde sale.

    El plan los pedía «destacados, con su total esperado y la línea
    recomendada». Salen el total y los córners observados de cada equipo. **La
    línea recomendada no sale, y ésa es la parte medida**: el total que el
    modelo predice para un partido es la media de su competición —la misma para
    todos sus partidos— porque la parte del modelo que variaba entre partidos
    tiene correlación −0,0012 con el resultado real sobre 11.856 partidos.

    Recomendar «más de 9,5» a partir de un número que es igual en los diez
    partidos de la jornada sería recomendar la media de la liga disfrazada de
    lectura del partido. Lo que sí se puede enseñar, y se enseña, es lo que cada
    equipo hace de verdad: eso son datos.
    """
    if not disp.get('corners'):
        return
    clave = str(pick.get('clave_liga') or '')
    media = None
    try:
        import rendimiento_equipos as rq
        media = rq.media_corners_liga(clave)
    except Exception as e:
        logger.debug('[modo_modelo] media de córners: %s', e)
    fh, fa = rend.get('forma_home') or {}, rend.get('forma_away') or {}
    partes = []
    if media is not None:
        partes.append('media de la competición **%.1f**' % media)
    if fh.get('ck_favor') is not None:
        partes.append('%s saca %.1f y recibe %.1f'
                      % (fh.get('equipo', 'local'), fh['ck_favor'],
                         fh['ck_contra']))
    if fa.get('ck_favor') is not None:
        partes.append('%s saca %.1f y recibe %.1f'
                      % (fa.get('equipo', 'visitante'), fa['ck_favor'],
                         fa['ck_contra']))
    if not partes:
        return
    st.markdown('**⛳ Córners** — ' + ' · '.join(partes))
    st.caption(
        'Los córners de esta competición son datos de la fuente, no '
        'estimaciones. **No hay línea recomendada**: el total que el modelo '
        'predice es la media de la competición, igual para todos sus partidos, '
        'porque su parte variable no distingue un partido de otro (correlación '
        '−0,001 con el resultado real sobre 11.856 partidos). Las medias de '
        'cada equipo sí son suyas.')


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


def tarjeta(st, pick: Dict, *, navegar: Optional[Callable] = None,
            n_boton: int = 0) -> None:
    """Una tarjeta del Modo Modelo: probabilidad del modelo y rendimiento."""
    prob = pick.get('prob')
    eq = _recomendado(pick)
    with st.container(border=True):
        cab = '**%s**' % pick.get('partido', '?')
        meta = [str(pick.get('deporte') or 'Fútbol'), str(pick.get('liga') or '')]
        if pick.get('hora_txt'):
            meta.append(str(pick['hora_txt']))
        sec = es_secundaria(pick)
        if sec is not None:
            meta.append('secundaria' if sec else 'principal')
        st.markdown(cab + '  \n' + ' · '.join([m for m in meta if m]))

        if prob is None:
            st.markdown('**Sin datos de modelo.**')
            st.caption(str(pick.get('motivo_sin_modelo') or
                           'el modelo no tiene pronóstico para este partido'))
        else:
            # LA ETIQUETA PRINCIPAL, tal y como se pidió. Dice «probabilidad»
            # y no dice EV: son cosas distintas y confundirlas es el motivo de
            # que esta pantalla exista.
            quien = eq or str(pick.get('apuesta') or 'la selección del modelo')
            st.markdown('### 📊 Modelo: %s con %.0f %% de probabilidad'
                        % (quien, float(prob) * 100))
            if pick.get('cuota'):
                st.caption('Cuota justa según el modelo: %.2f. La casa paga '
                           '%.2f. Esta pantalla NO ordena por esa diferencia '
                           '— para eso está el Modo Valor.'
                           % (1.0 / float(prob), float(pick['cuota'])))

        if str(pick.get('deporte') or '') == 'Tenis':
            _bloque_tenis(st, pick)
            if navegar is not None:
                if st.button('📊 Abrir %s' % pick.get('partido', 'el partido'),
                             key='mm_ir_%d' % n_boton, width='stretch'):
                    navegar(pick)
            return

        rend = _rendimiento(pick)
        if rend:
            disp = rend.get('disponible') or {}
            st.markdown('**Cómo llegan (últimos 5)**')
            _linea_forma(st, rend['forma_home'], disp, 'Local')
            _linea_forma(st, rend['forma_away'], disp, 'Visitante')
            mh = _texto_momentum(rend.get('momentum_home'))
            ma = _texto_momentum(rend.get('momentum_away'))
            if mh or ma:
                st.caption('Momentum (5 últimos vs 5 anteriores) — '
                           + ' | '.join([x for x in (mh, ma) if x])
                           + '. Son dos medias de cinco partidos: sirve para '
                             'leer, no para decidir.')
            # El bando que toca jugar, que es la lectura que más cambia y la
            # que menos se mira.
            ch, fa = rend.get('casa_home') or {}, rend.get('fuera_away') or {}
            if ch.get('n') and fa.get('n'):
                st.caption('En su bando: local `%s` (%.2f pts) · visitante '
                           '`%s` (%.2f pts)'
                           % (ch.get('racha', ''), ch['pts_por_partido'],
                              fa.get('racha', ''), fa['pts_por_partido']))
            _bloque_corners(st, pick, rend, disp)
            if disp and not disp.get('corners'):
                st.caption('Esta competición no publica córners ni remates: '
                           'lo único observado son los goles.')
        else:
            st.caption('Sin histórico de rendimiento para esta competición.')

        if navegar is not None:
            if st.button('📊 Abrir %s' % pick.get('partido', 'el partido'),
                         key='mm_ir_%d' % n_boton, width='stretch'):
                navegar(pick)


def render(st, pronosticos: List[Dict], *, navegar: Optional[Callable] = None,
           clave: str = 'mm', maximo: int = 40) -> None:
    """
    La pestaña entera.

    `pronosticos` es la lista del barrido YA filtrada por día y por deporte:
    esta función no vuelve a filtrar por esos ejes para que no haya dos reglas
    de reparto que puedan divergir (la lección de la v141).
    """
    st.caption(
        '⚠️ **Esta pantalla ordena por probabilidad del modelo, y eso no es un '
        'criterio de apuesta rentable en este proyecto.** Está medido: apostar '
        'la probabilidad del modelo pierde entre −4,66 % y −6,52 % sobre '
        '37.158 apuestas, y su EV es anti-indicador del cierre. Lo que sí '
        'tiene percentil 5 positivo es comprar al mejor precio, y eso vive en '
        '«✅ Para jugar». Aquí se lee el rendimiento; allí se decide.')

    con, sin = [], []
    for p in (pronosticos or []):
        if not isinstance(p, dict):
            continue
        (sin if (p.get('sin_modelo') or p.get('prob') is None) else con).append(p)

    # EL FILTRO DE LIGAS SECUNDARIAS NO VIVE AQUÍ.
    #
    # Está arriba, al lado del filtro de deporte, y afecta a todas las pestañas
    # a la vez. Tener un segundo selector del mismo eje dentro de esta pantalla
    # sería la receta para que el mismo partido salga aquí y no en «Para
    # jugar», que es exactamente el fallo que la separación por día tuvo que
    # arreglar en su momento. Esta función recibe la lista ya filtrada.
    _n_sec = sum(1 for p in con if es_secundaria(p) is True)
    if _n_sec:
        st.caption('%d de los partidos con pronóstico son de ligas '
                   'secundarias. **Que tengan menos volumen no es, por sí '
                   'solo, una ventaja medida en este proyecto**: es una '
                   'hipótesis razonable que todavía no tiene su propio p5.'
                   % _n_sec)

    # El orden usa `_prob`, no `p['prob']` a pelo. La lista llega de siete
    # ramas de deporte distintas y basta con que UNA traiga la probabilidad
    # como texto para que `-(p.get('prob') or 0)` lance un TypeError y se lleve
    # por delante la pestaña entera — y con `st.tabs`, la vista entera con ella.
    con.sort(key=lambda p: -_prob(p))
    if not con:
        st.info('No hay partidos con pronóstico del modelo en esta selección.')
    else:
        fuertes = [p for p in con if _prob(p) >= PROB_DESTACADA]
        st.subheader('📊 Por probabilidad del modelo (%d)' % len(con))
        if fuertes:
            st.caption('%d superan el %.0f %%.' % (len(fuertes),
                                                   PROB_DESTACADA * 100))
        for i, p in enumerate(con[:maximo]):
            tarjeta(st, p, navegar=navegar, n_boton=i)
        if len(con) > maximo:
            st.caption('Se muestran los %d más probables de %d. El resto está '
                       'en «📋 Partidos de hoy».' % (maximo, len(con)))

    if sin:
        with st.expander('Sin datos de modelo (%d)' % len(sin)):
            st.caption(
                'Estos partidos no llevan pronóstico. **Aquí no se enseña la '
                'probabilidad implícita del mercado** aunque exista: esta '
                'pantalla es para leer al modelo, y un número del mercado en '
                'una fila del modelo haría imposible distinguir uno de otro. '
                'El precio de estos partidos sí sale en «📋 Partidos de hoy».')
            for p in sin[:maximo]:
                st.markdown('· **%s** — %s · %s'
                            % (p.get('partido', '?'), p.get('liga', ''),
                               p.get('motivo_sin_modelo') or 'sin pronóstico'))
