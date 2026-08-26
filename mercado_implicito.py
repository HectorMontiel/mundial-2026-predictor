#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v165 — LO QUE LA CASA CREE, AL LADO DE LO QUE CREE EL MODELO.

Por qué hace falta
------------------
La tarjeta anunciaba «✅ Menos de 2.5 — 80 %» sin nada con qué contrastarlo. Un
80 % de «menos de 2,5» sale de una λ de partido de 1,35 goles, que en fútbol de
clubes casi no existe: la casa rara vez baja del 55-60 % en ese lado. La
diferencia entre las dos cifras no se veía porque **el pronóstico no lleva el
precio de la casa encima**.

Medido sobre el barrido cacheado del 2026-08-23: de los 156 pronósticos de
fútbol, **cero** traen `cuota` en ningún mercado. No es un fallo del barrido —
es que `pronosticos` se construye por el camino del MODELO
(`_mercados_modelo`), que emite cuota justa y `cuota: None` a propósito. Los
precios reales existen, pero viven en `candidatos`/`capa1`, que son otra lista y
sólo cubren los partidos que pasaron los filtros.

Qué hace este módulo
--------------------
Saca del tablero de la casa las probabilidades IMPLÍCITAS y SIN MARGEN de los
tres mercados que la tarjeta enseña —1X2, goles y ambos marcan— y las deja en
`mercado_dia.json` para que la tarjeta las lea sin pedir red.

    {'generado': '...', 'partidos': {'brighton|aston villa': {
        'casa': 'Playdoit',
        '1x2': {'home': 0.436, 'draw': 0.262, 'away': 0.302},
        'goles': {'2.5': 0.532, '1.5': 0.774, '3.5': 0.323},
        'btts': 0.558}}}

NO PIDE RED DESDE LA TARJETA, Y ESO NO ES NEGOCIABLE
-----------------------------------------------------
Es la misma regla —y el mismo contrato— que `lineas_jugador.del_partido` y
`remates_jugador.alineacion`: el precálculo lo hace el bot una vez al día y la
pantalla lee un fichero. Pedir el tablero desde la tarjeta ya costó tres
regresiones al proyecto (383 s y 388 s de barrido); sesenta partidos por una
descarga de 300 KB cada uno no caben en una pantalla.

De dónde salen las tres cifras
------------------------------
Del MISMO tablero por evento que ya baja `lineas_jugador.precalcular` para las
líneas de jugador (`cuotas_multi.mercados_playdoit`, cacheado en disco 30 min),
así que ejecutar los dos precálculos seguidos no dobla las descargas: el segundo
encuentra el tablero en disco.

El margen se quita con `cuotas_multi.devig(metodo='potencia')`, que es el que
este proyecto midió mejor por log-loss en las tres familias (v80). Sin quitarlo,
los dos lados de un total suman 1,05-1,08 y el contraste heredaría ese sesgo:
compararíamos una probabilidad contra algo que ni siquiera es una probabilidad.

Y SI NO HAY PRECIO, NO SE INVENTA
---------------------------------
`implicita()` devuelve `None` cuando la casa no cotiza ese partido o ese
mercado. `None` no es 0,5 y no se trata como tal: quien llama —
`cordura_probabilidad`— sabe distinguir «la casa dice otra cosa» de «no hay con
qué contrastar», y las dos consecuencias son distintas.
"""
import json
import logging
import os
import re
import time
import unicodedata
from typing import Dict, Optional

logger = logging.getLogger('mercado_implicito')

FICHERO = 'mercado_dia.json'

# Los nombres con los que Playdoit rotula los tres mercados. Se comparan
# normalizados (sin tildes, en minúsculas) porque la casa alterna «Ambos equipos
# marcan» y «Ambos Equipos Anotan» según la liga.
_N_1X2 = ('resultado final', '1x2')
_N_TOTAL = ('total',)
_N_BTTS = ('ambos equipos marcan', 'ambos equipos anotan')

_LINEA = re.compile(r'^(m[aá]s|menos)\s+de\s+([0-9]+(?:[.,][0-9]+)?)$')

_DISCO: Optional[Dict] = None
_MEM: Dict[str, Optional[Dict]] = {}


def _norm(s) -> str:
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())


def llave(home: str, away: str) -> str:
    """La misma llave que usa `lineas_jugador`: normalizada y por bandos."""
    return '%s|%s' % (_norm(home), _norm(away))


def clave_linea(v) -> Optional[str]:
    """
    La etiqueta con la que se guarda una línea de goles.

    Dos decimales sin ceros de relleno: `2.5`, `1.25`, `3`. Redondear a uno
    solo —que es lo primero que se escribió— convertía «Más de 1.25» en la
    clave `1.2` y «Más de 1.75» en `1.8`: emparejaban bien entre sí, pero el
    rótulo mentía y a la primera línea de cuartos que alguien consultara por su
    nombre le habría contestado otra. Playdoit publica los cuartos, así que
    esto no es hipotético.

    Quien escribe y quien lee pasan los dos por aquí, que es lo único que
    garantiza que no diverjan.
    """
    try:
        f = float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return ('%.2f' % f).rstrip('0').rstrip('.')


def _devig(cuotas: Dict[str, float]) -> Dict[str, float]:
    try:
        import cuotas_multi as cm
        return cm.devig(cuotas, metodo='potencia') or {}
    except Exception as e:
        logger.debug('[mercado] devig: %s', e)
        # Respaldo proporcional: peor que `potencia` (v80) pero infinitamente
        # mejor que devolver la implícita con margen.
        inv = {k: 1.0 / v for k, v in cuotas.items() if v and v > 1}
        s = sum(inv.values())
        return {k: v / s for k, v in inv.items()} if s > 0 else {}


def _es_corner(texto: str) -> bool:
    """La misma prueba que `snapshots_corners`, y por el mismo motivo: la casa
    renombra familias cada temporada y una lista fija deja de capturar en
    silencio."""
    t = str(texto or '')
    return 'corner' in t or 'esquina' in t


def prob_de(entrada) -> Optional[float]:
    """
    La probabilidad SIN MARGEN de una linea, sea cual sea el formato guardado.

    Hasta la v170 cada linea era un `float`; desde la v171 es un dict con la
    probabilidad y las dos cuotas. El fichero del dia se regenera cada noche,
    asi que durante unas horas conviven los dos — y un lector que solo
    entienda el nuevo dejaria la tarjeta sin lineas hasta que corriera el bot.
    """
    if isinstance(entrada, dict):
        v = entrada.get('p')
    else:
        v = entrada
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cuota_de(entrada, lado: str = 'mas') -> Optional[float]:
    """La cuota de ese lado, o `None` si lo guardado es del formato viejo."""
    if not isinstance(entrada, dict):
        return None
    try:
        v = float(entrada.get(lado))
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _menciona(nombre: str, equipo: str) -> bool:
    """
    ¿El rótulo de esta familia nombra a ese equipo?

    Por PALABRAS ENTERAS, no por subcadena. Con `equipo in nombre` bastaba un
    club de nombre corto —«Ajax», «Roma», o una «A» en una prueba— para casar
    dentro de otra palabra y tirar el mercado del partido entero creyéndolo el
    de un equipo. Es la misma lección que la v163.1 con `name_mapper`: la
    contención engaña.
    """
    eq = _norm(equipo)
    if not eq:
        return False
    return re.search(r'(?<!\w)%s(?!\w)' % re.escape(eq), _norm(nombre)) \
        is not None


def _lineas_dos_lados(sels) -> Dict[str, float]:
    """
    `{linea: P(más de)}` de una familia con los dos lados, ya sin margen.

    Una línea con un solo lado publicado se descarta: sin el contrario no se
    puede quitar el margen, y una implícita CON margen no es una probabilidad
    — compararla contra el modelo heredaría ese sesgo. Es la misma razón por
    la que la v164 no persiguió la lambda de remates por jugador.
    """
    mas: Dict[str, float] = {}
    menos: Dict[str, float] = {}
    for s in sels:
        if not isinstance(s, dict):
            continue
        c = _cuota(s)
        if c is None:
            continue
        mm = _LINEA.match(_norm(s.get('nombre')))
        if not mm:
            continue
        linea = clave_linea(mm.group(2))
        if linea is None:
            continue
        (menos if mm.group(1) == 'menos' else mas)[linea] = c
    salida = {}
    for linea, c_mas in mas.items():
        c_menos = menos.get(linea)
        if not c_menos:
            continue
        justa = _devig({'mas': c_mas, 'menos': c_menos})
        if len(justa) == 2:
            # v171 — SE GUARDA TAMBIEN LA CUOTA, NO SOLO LA IMPLICITA.
            #
            # Hasta aqui bastaba la probabilidad sin margen para contrastar el
            # numero del modelo. Desde la v171 la recomendacion se elige por
            # `Score = probabilidad x cuota`, y para eso hace falta el PRECIO
            # que el usuario va a cobrar — que no es 1/implicita, porque la
            # implicita ya no lleva el margen y la cuota si.
            salida[linea] = {'p': round(justa['mas'], 4),
                             'mas': round(float(c_mas), 3),
                             'menos': round(float(c_menos), 3)}
    return salida


# ---------------------------------------------------------------------------
# v169 — LO QUE LA CASA PUBLICA DE VERDAD, FAMILIA A FAMILIA
# ---------------------------------------------------------------------------
# La v166 sacaba sólo el TOTAL de córners y descartaba a propósito las familias
# por equipo. Con la recomendación moviéndose a córners, tarjetas y remates
# (v168), eso dejaba a los mercados más estables sin su línea real.
#
# LO QUE SE ENCONTRÓ AL MIRAR EL TABLERO, Y NO ERA LO QUE SE SUPONÍA
# -------------------------------------------------------------------
# El encargo decía que Playdoit publica sólo el total de tarjetas y no las de
# equipo. Medido sobre ocho partidos del día, es al revés de lo que se creía y
# además es MUY desigual:
#
#     Botafogo-Athletico-PR   16 familias de tarjetas · «Total de tarjetas»
#                             (4,5/5,5/6,5) Y «Total de tarjetas Atlético» (2,5)
#     Valencia-Betis          22 familias
#     Real Madrid-Real Soc.    0 familias de tarjetas
#
# O sea que no se puede codificar «la casa publica esto»: hay que LEER cada
# tablero y enseñar lo que traiga. Es la misma disciplina que `snapshots_corners`
# ya seguía —filtrar por el nombre de la familia y no por una lista fija— porque
# la casa renombra y añade familias cada temporada.
#
# LO QUE SE DESCARTA, Y POR QUÉ CADA COSA
# ----------------------------------------
#   · media parte: es otro partido;
#   · exacto / escala / impar-par / 1x2 / hándicap / carrera / ambos / primer /
#     último: no son Más-Menos sobre una línea, así que no se pueden comparar
#     con una binomial negativa;
#   · tarjetas ROJAS: nuestro modelo cuenta amarillas MÁS rojas (v160), y la
#     familia de rojas sola es otro mercado. Mezclarlos sería comparar dos cosas
#     distintas y no se vería.
_RE_MITAD = re.compile(r'mitad|1er tiempo|primer tiempo|1a mitad')
_RE_NO_LINEA = re.compile(
    r'exact|escala|impar|par/|/par|1x2|handicap|hándicap|carrera|ambos'
    r'|primer|ultimo|último|anota|marca')

_FAMILIAS = (
    ('corners', re.compile(r'esquina|corner')),
    ('tarjetas', re.compile(r'tarjeta|amarilla')),
    ('remates_on', re.compile(r'a puerta|al arco')),
    ('remates', re.compile(r'remate|tiro(?!s de esquina)')),
)


def _familia_de(nom: str) -> Optional[str]:
    """A qué mercado de conteo pertenece esta familia, o `None`."""
    if _RE_MITAD.search(nom) or _RE_NO_LINEA.search(nom):
        return None
    if 'roja' in nom:
        return None                      # otro mercado, ver arriba
    for clave, rx in _FAMILIAS:
        if rx.search(nom):
            return clave
    return None


def _lado_de(nom: str, casa_home: str, casa_away: str,
             invertido: bool) -> str:
    """
    `''` si la familia es del partido, `'_home'`/`'_away'` si es de un equipo.

    Por PALABRAS ENTERAS, con la misma regla que `_menciona`: con subcadena, un
    club corto casa dentro de otra palabra y una familia del partido se
    archivaría como la de un equipo.

    `casa_home` ya viene orientado por `mercados_playdoit` —es el nombre con el
    que la casa llama a NUESTRO local, invertido incluido—, así que aquí no hay
    que volver a darle la vuelta.
    """
    if _menciona(nom, casa_home):
        return '_home'
    if _menciona(nom, casa_away):
        return '_away'
    return ''


def _conteos_del_tablero(tablero: Dict, casa_home: str, casa_away: str,
                         invertido: bool) -> Dict[str, Dict[str, float]]:
    """
    Todas las líneas Más/Menos de conteo que trae el tablero, devigadas.

    Devuelve `{'corners': {...}, 'corners_home': {...}, 'tarjetas': {...}}` y
    sólo con lo que exista. Una familia con un solo lado publicado se descarta
    entera: sin el contrario no se puede quitar el margen, y una implícita CON
    margen no es una probabilidad.
    """
    salida: Dict[str, Dict[str, float]] = {}
    for m in (tablero.get('mercados') or []):
        if not isinstance(m, dict):
            continue
        nom = _norm(m.get('nombre'))
        fam = _familia_de(nom)
        if not fam:
            continue
        lineas = _lineas_dos_lados(m.get('selecciones') or [])
        if not lineas:
            continue
        lado = _lado_de(nom, casa_home, casa_away, invertido)
        # NINGÚN MERCADO DE JUGADOR PUEDE COLARSE AQUÍ.
        #
        # Playdoit rotula los de jugador «Remates a Puerta - Vinicius Jr.
        # (RMA)» y «Remates del jugador - dentro del área (…)»: llevan un
        # paréntesis con el código del equipo o la palabra «jugador». Sin esta
        # guarda, la línea de 1,5 remates de un extremo se archivaría junto a
        # la de 24,5 del partido y se compararía contra la lambda del equipo.
        #
        # La excepción es un equipo que lleve paréntesis en su propio nombre
        # —«Racing (Montevideo)»—: si el rótulo casa con uno de los dos
        # equipos, es suyo y entra. Preferir el hueco al número equivocado.
        if not lado and ('(' in nom or 'jugador' in nom):
            continue
        salida.setdefault(fam + lado, {}).update(lineas)
    return salida


def _cuota(sel) -> Optional[float]:
    try:
        v = float(sel.get('cuota'))
    except (TypeError, ValueError, AttributeError):
        return None
    return v if v > 1.0 else None


def del_tablero(tablero: Optional[Dict]) -> Dict:
    """
    1X2, goles y BTTS de un tablero de la casa, ya sin margen.

    Devuelve `{}` si el tablero no trae ninguno de los tres. Las claves que
    faltan simplemente no están: un mercado ausente no se rellena con la media
    de nada.
    """
    if not tablero:
        return {}
    salida: Dict = {}
    # Los nombres con los que la CASA rotula a los dos equipos. `home`/`away`
    # de `mercados_playdoit` son los del LLAMADOR —lo dice su docstring— y
    # comparar las selecciones contra ésos fallaba en la mayoría: «Athletico-PR»
    # contra «Athletico Paranaense». Medido antes de arreglarlo: sólo 22 de 54
    # partidos sacaban su 1X2.
    casa_home = _norm(tablero.get('casa_home') or tablero.get('home'))
    casa_away = _norm(tablero.get('casa_away') or tablero.get('away'))
    invertido = bool(tablero.get('invertido'))
    for m in (tablero.get('mercados') or []):
        if not isinstance(m, dict):
            continue
        nom = _norm(m.get('nombre'))
        sels = m.get('selecciones') or []
        if not sels:
            continue
        # --- 1X2 --------------------------------------------------------
        if '1x2' not in salida and any(nom.startswith(x) for x in _N_1X2) \
                and 'mitad' not in nom and len(sels) == 3:
            cu = {}
            for s in sels:
                c = _cuota(s)
                if c is None:
                    continue
                # El `tipo` de la selección (1 local, 2 empate, 3 visitante) es
                # más fiable que el nombre y no depende de cómo escriba la casa
                # al equipo. El nombre queda de respaldo por si algún día no
                # viene, pero manda el tipo.
                #
                # Y EL TIPO ES EL DE LA CASA, NO EL NUESTRO. Cuando el
                # emparejador detectó que la casa publica el partido con los
                # bandos al revés (`invertido`), su «tipo 1» es nuestro
                # visitante. Sin este cambio de lado, esos partidos saldrían
                # con el 1X2 espejado y nadie lo vería: las tres cifras siguen
                # sumando 1. Es la misma disciplina que sigue `cuotas_partido`
                # con el 1X2 desde la v77.
                por_tipo = ({1: 'away', 2: 'draw', 3: 'home'} if invertido
                            else {1: 'home', 2: 'draw', 3: 'away'}
                            ).get(s.get('tipo'))
                n = _norm(s.get('nombre'))
                if por_tipo:
                    cu[por_tipo] = c
                elif n == 'empate':
                    cu['draw'] = c
                elif n == casa_home:
                    cu['home'] = c
                elif n == casa_away:
                    cu['away'] = c
            if len(cu) == 3:
                justa = _devig(cu)
                if len(justa) == 3:
                    salida['1x2'] = {k: round(v, 4) for k, v in justa.items()}
                    # v171 — y las tres cuotas, para poder calcular el Score
                    salida['1x2_cuotas'] = {k: round(float(v), 3)
                                            for k, v in cu.items()}
        # --- goles: TODAS las líneas de medio punto, cada una devigada ---
        elif 'goles' not in salida and nom in _N_TOTAL:
            goles = _lineas_dos_lados(sels)
            if goles:
                salida['goles'] = goles
        # --- doble oportunidad -------------------------------------------
        #
        # v171 — entra al catálogo con SU cuota. La probabilidad no hace falta
        # guardarla: sale de sumar dos lados del 1X2 que ya está aquí. Lo que
        # no se puede deducir es el precio, y sin precio no hay Score.
        elif 'doble_cuotas' not in salida and 'doble oportunidad' in nom \
                and 'mitad' not in nom and len(sels) == 3:
            cu = {}
            for s_ in sels:
                c = _cuota(s_)
                if c is None:
                    continue
                n = _norm(s_.get('nombre'))
                # la casa las rotula «Local o Empate», «Local o Visitante»…
                # y también «1X»/«12»/«X2» según la liga. Se aceptan las dos.
                if n in ('1x', '12', 'x2'):
                    cu[n.upper()] = c
                elif casa_home and casa_home in n and 'empate' in n:
                    cu['1X'] = c
                elif casa_away and casa_away in n and 'empate' in n:
                    cu['X2'] = c
                elif casa_home and casa_away and casa_home in n \
                        and casa_away in n:
                    cu['12'] = c
            if cu:
                salida['doble_cuotas'] = {k: round(float(v), 3)
                                          for k, v in cu.items()}
        # --- ambos marcan -----------------------------------------------
        elif 'btts' not in salida and nom in _N_BTTS and len(sels) == 2:
            cu = {}
            for s in sels:
                c = _cuota(s)
                if c is None:
                    continue
                n = _norm(s.get('nombre'))
                if n in ('si', 'sí'):
                    cu['si'] = c
                elif n == 'no':
                    cu['no'] = c
            if len(cu) == 2:
                justa = _devig(cu)
                if len(justa) == 2:
                    salida['btts'] = round(justa['si'], 4)
                    salida['btts_cuotas'] = {k: round(float(v), 3)
                                             for k, v in cu.items()}
    # v169 — y TODAS las familias de conteo que la casa traiga: córners y
    # tarjetas, del partido y de cada equipo, y remates si las publica. No se
    # codifica qué publica: se lee.
    salida.update(_conteos_del_tablero(tablero, casa_home, casa_away,
                                       invertido))
    if salida:
        salida['casa'] = tablero.get('casa') or 'Playdoit'
    return salida


# ---------------------------------------------------------------------------
# lectura: lo que dejó el bot
# ---------------------------------------------------------------------------
def cargar(ruta: str = FICHERO, recargar: bool = False) -> Dict:
    """Lo precalculado del día. `{}` si no está, sin protestar."""
    global _DISCO
    if _DISCO is not None and not recargar:
        return _DISCO
    datos: Dict = {}
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.debug('[mercado] no se pudo leer %s: %s', ruta, e)
    _DISCO = datos
    return datos


def del_partido(home: str, away: str,
                permitir_red: bool = False) -> Dict:
    """
    El precio de la casa de este partido. `{}` cuando no lo cotiza.

    `permitir_red=False` —la tarjeta— NO hace ni una petición. La ficha del
    partido, que se abre de una en una, sí puede pasar `True`.
    """
    ck = '%s|%s' % (llave(home, away), permitir_red)
    if ck in _MEM:
        return _MEM[ck] or {}
    salida = dict((cargar().get('partidos') or {}).get(llave(home, away)) or {})
    if not salida and permitir_red:
        try:
            import cuotas_multi as cm
            salida = del_tablero(cm.mercados_playdoit('futbol', home, away))
        except Exception as e:
            logger.debug('[mercado] %s-%s: %s', home, away, e)
            salida = {}
    _MEM[ck] = salida
    return salida


# Cómo se llama cada apuesta en el board del proyecto -> dónde mirarla aquí.
_RE_MAS = re.compile(r'^m[aá]s de ([0-9]+(?:[.,][0-9]+)?)$', re.I)
_RE_MENOS = re.compile(r'^menos de ([0-9]+(?:[.,][0-9]+)?)$', re.I)


def implicita(precio: Dict, apuesta: str,
              home: str = '', away: str = '') -> Optional[float]:
    """
    La probabilidad SIN MARGEN que la casa le da a ESA apuesta, o `None`.

    `apuesta` es la etiqueta tal cual la escribe el barrido: «Gana Brighton»,
    «Empate», «Más de 2.5», «Menos de 2.5», «Ambos marcan: Sí»…

    `None` NO es 0,5: significa «la casa no cotiza esto» y quien llama tiene que
    distinguirlo de un desacuerdo. El hándicap devuelve `None` a propósito: su
    línea viaja en el propio pick y compararla exigiría emparejar líneas, que es
    una medición aparte y no está hecha.
    """
    if not precio or not apuesta:
        return None
    etq = str(apuesta).strip()
    n = _norm(etq)
    # goles
    for rx, es_mas in ((_RE_MAS, True), (_RE_MENOS, False)):
        mm = rx.match(etq)
        if mm:
            linea = clave_linea(mm.group(1))
            p = prob_de((precio.get('goles') or {}).get(linea)) \
                if linea else None
            if p is None:
                return None
            return p if es_mas else 1.0 - p
    # ambos marcan
    if n.startswith('ambos marcan'):
        p = precio.get('btts')
        if p is None:
            return None
        return float(p) if n.endswith('si') or n.endswith('sí') \
            else 1.0 - float(p)
    # 1X2
    x2 = precio.get('1x2') or {}
    if not x2:
        return None
    if n == 'empate':
        return float(x2['draw']) if 'draw' in x2 else None
    if n.startswith('gana '):
        equipo = _norm(etq[5:])
        if home and equipo == _norm(home):
            return float(x2['home']) if 'home' in x2 else None
        if away and equipo == _norm(away):
            return float(x2['away']) if 'away' in x2 else None
    return None


# ---------------------------------------------------------------------------
# el precálculo diario
# ---------------------------------------------------------------------------
def precalcular(dias: int = 2, max_hilos: int = 4) -> Dict:
    """
    El precio de los tres mercados de los fixtures próximos, listo para guardar.

    Una petición de tablero por partido, la MISMA que hace
    `lineas_jugador.precalcular`. Ejecutados seguidos, el segundo la encuentra
    en la caché de disco de `cuotas_multi` (TTL 30 min) y no vuelve a bajarla.
    """
    from concurrent.futures import ThreadPoolExecutor
    import cuotas_multi as cm
    import fixtures_espn as fx
    from config import LEAGUES

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fx.ESPN_CODIGOS]
    por_liga = fx.fixtures_multi(claves, dias=dias)
    pendientes = []
    for clave, lista in (por_liga or {}).items():
        nombre = (LEAGUES.get(clave) or {}).get('nombre') or clave
        for f in (lista or []):
            h, a = f.get('home'), f.get('away')
            if h and a:
                pendientes.append((clave, h, a, f.get('fecha'), nombre))

    def _uno(par):
        # LA FECHA Y LA LIGA VAN SIEMPRE, Y NO ES OPCIONAL AQUI.
        #
        # `cuotas_multi._buscar` empareja por nombre y sin fecha caso «Botafogo
        # vs Athletico-PR» (Brasileirão) con el «Botafogo SP vs Atlético» que
        # la casa cotizaba ese mismo día: el precio salía con el favorito al
        # revés que el de ESPN (3,80 contra 2,40 al local). Es el modo de fallo
        # de la v114, y aquí duele el doble — un precio de OTRO partido no da un
        # hueco, da un contraste falso, y este módulo existe justo para
        # contrastar.
        clave, h, a, fecha, nombre_liga = par
        try:
            precio = del_tablero(cm.mercados_playdoit(
                'futbol', h, a, fecha=fecha, liga=nombre_liga))
        except Exception as e:
            logger.debug('[mercado] %s-%s: %s', h, a, e)
            return None
        if not precio:
            return None
        return (llave(h, a), {'clave_liga': clave, 'home': h, 'away': a,
                              **precio})

    salida: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=max_hilos) as ex:
        for r in ex.map(_uno, pendientes):
            if r:
                salida[r[0]] = r[1]
    logger.info('[mercado] %d fixtures · %d con precio de la casa',
                len(pendientes), len(salida))
    return {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'partidos': salida}


def guardar(doc: Dict, ruta: str = FICHERO) -> None:
    """Sin sangrado: son cifras y se commitea todos los días."""
    try:
        import io_atomico
        io_atomico.escribir_json(ruta, doc)
    except Exception:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dias', type=int, default=2)
    ap.add_argument('--salida', default=FICHERO)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    doc = precalcular(dias=a.dias)
    guardar(doc, a.salida)
    print('%d partidos con precio de la casa -> %s'
          % (len(doc.get('partidos') or {}), a.salida))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
