#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fixtures ESPN (v49) — PRÓXIMOS partidos por liga, SIN clave y SIN coste de API.

El barrido de Apuestas del Día (alpha_finder) se alimentaba EXCLUSIVAMENTE de
odds_actuales.json: si la captura de The Odds API fallaba o se quedaba corta,
el barrido colapsaba a "partidos evaluados: 0". Este módulo aporta una fuente
de FIXTURES independiente de las cuotas: el scoreboard JSON público de ESPN
(site.api.espn.com), el mismo que ya usa el proyecto para el Mundial y la UEFA.

Así, cada partido con jornada se evalúa SIEMPRE:
  · si hay cuota real  → Capa 1 (con EV).
  · si no hay cuota    → Capa 2 (cuota justa del modelo).

Degradación honesta: si ESPN no responde para una liga (receso, cambio de
endpoint), se devuelve [] y el barrido sigue con las demás fuentes.
"""

import logging
import re
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard'

# clave interna del proyecto -> código de liga en ESPN (soccer).
# Verificado 2026-07-24: mex.1/usa.1/bra.1/arg.1 devuelven fixtures futuros.
ESPN_CODIGOS: Dict[str, str] = {
    'liga_mx': 'mex.1',
    'mls': 'usa.1',
    'brasil': 'bra.1',
    'argentina': 'arg.1',
    'premier': 'eng.1',
    'laliga': 'esp.1',
    'serie_a': 'ita.1',
    'bundesliga': 'ger.1',
    'ligue_1': 'fra.1',
    'eredivisie': 'ned.1',
    'primeira': 'por.1',
    'noruega': 'nor.1',
    'suecia': 'swe.1',
    'finlandia': 'fin.1',
    'rumania': 'rou.1',
    'irlanda': 'irl.1',
    'turquia': 'tur.1',
    'dinamarca': 'den.1',
    'china': 'chn.1',
    # (Polonia: ESPN devuelve 400 para pol.1 y está en receso hasta agosto; su
    #  cobertura llega por la vía de cuotas cuando reanuda.)
    # v68: las 40 competiciones nuevas se inyectan más abajo desde
    # config_ligas_espn.ESPN_CODIGOS_V68 (generado).
    'champions': 'uefa.champions',
    'europa_league': 'uefa.europa',
    'conference_league': 'uefa.europa.conf',
    'mundial': 'fifa.world',
    # v97 — Leagues Cup. Sin esta entrada la competición se entrena y no llega
    # nunca a Apuestas del Día: `alpha_finder.barrido_*` sólo recorre las
    # claves que estén en este mapa (ver la nota de v68 justo debajo).
    'leagues_cup': 'concacaf.leagues.cup',
}

# v68 — Competiciones nuevas. Sin esta línea, `alpha_finder.barrido_*` NO las
# recorre: filtra por `clave in fixtures_espn.ESPN_CODIGOS`, así que una liga
# entrenada y disponible pero ausente de este mapa nunca llegaría a Apuestas
# del Día. Las que se entrenan con football-data también van aquí, porque su
# histórico viene del CSV pero sus PRÓXIMOS partidos y cuotas salen de ESPN.
try:
    from config_ligas_espn import ESPN_CODIGOS_V68 as _CODIGOS_V68
    for _k, _v in _CODIGOS_V68.items():
        ESPN_CODIGOS.setdefault(_k, _v)
except Exception:                       # degradación limpia al catálogo previo
    pass

# ---------------------------------------------------------------------------
# v102 — CÓDIGOS COMPAÑEROS: las fases previas son otra competición para ESPN.
#
# El usuario reportó que la Champions «no trae los próximos partidos». No era un
# fallo de la app: en agosto la Champions está en fase previa, y ESPN la publica
# bajo un código DISTINTO del de la liguilla. Medido el 2026-08-06 pidiendo
# agosto-noviembre:
#
#     uefa.champions        →  0 eventos      uefa.champions_qual   → 10
#     uefa.europa           →  0 eventos      uefa.europa_qual      → 23
#     uefa.europa.conf      →  0 eventos      uefa.europa.conf_qual → 57
#     afc.champions         →  0 eventos      afc.champions_qual    →  4
#
# Es decir: 94 partidos reales que la app no veía porque preguntaba por el
# código de una fase que todavía no ha empezado. Se consultan los dos y se
# fusionan — un equipo eliminado en la previa no aparece luego en la liguilla,
# así que no hay riesgo de duplicar el mismo partido.
ESPN_COMPANEROS: Dict[str, List[str]] = {
    'champions': ['uefa.champions_qual'],
    'europa_league': ['uefa.europa_qual'],
    'conference_league': ['uefa.europa.conf_qual'],
    'afc_champions': ['afc.champions_qual'],
}

# v102 — HORIZONTE PROGRESIVO.
#
# La ventana era de 7 días fijos, y eso deja en blanco a toda competición que
# no juegue esta semana. Medido el 2026-08-06, con las ligas europeas a dos
# semanas de arrancar:
#
#     liga         7 d    30 d
#     premier        0      28
#     bundesliga     0      16
#     serie_a        0      24
#
# «Próximos partidos» significa los siguientes, no los de esta semana. Si la
# ventana corta viene vacía se amplía por escalones hasta encontrar algo. No se
# empieza por la ventana larga: cuando la liga SÍ juega esta semana, pedir 90
# días traería la temporada entera y la interfaz enseñaría partidos de octubre
# mezclados con los de mañana.
HORIZONTES = (7, 30, 90)

# memoización en proceso (clave, dias) -> (timestamp, fixtures). El barrido de
# la UI ya está cacheado a nivel de Streamlit; esto evita repetir la llamada a
# ESPN dentro de una misma corrida del bot/pipeline.
_CACHE: Dict[str, tuple] = {}

# v110 — un fallo que se repite sesenta veces deja de ser información.
#
# ESPN responde 403 a las IPs de centro de datos, así que en Streamlit Cloud
# hay rutas que fallan SIEMPRE (las competiciones de selecciones, los rosters).
# Con el aviso a nivel WARNING en cada intento, el log de producción se llenaba
# de líneas idénticas que tapaban los errores de verdad — el usuario mandó una
# captura con el mismo 403 repetido dieciséis veces seguidas.
#
# Se avisa la PRIMERA vez con todo el detalle y las siguientes van a debug.
_AVISADOS: set = set()


def _avisar_una_vez(clave: str, mensaje: str) -> None:
    if clave in _AVISADOS:
        logger.debug(mensaje + ' (repetido)')
    else:
        _AVISADOS.add(clave)
        logger.warning(mensaje)


_TTL = 1800  # 30 min


# timeout corto: un scoreboard responde en <2 s cuando está sano. Un timeout
# largo × muchas ligas secuenciales colgaba el barrido en Streamlit Cloud (v50.1).
TIMEOUT = 8


def _am2dec(ml):
    """Cuota americana (moneyline) → decimal. v52."""
    try:
        ml = float(str(ml).replace('+', ''))
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return round(1 + ml / 100, 3) if ml > 0 else round(1 + 100 / abs(ml), 3)


def _odds_de_evento(comp: dict) -> dict:
    """v52: extrae las cuotas 1X2 y O/U 2.5 que ESPN incluye en el MISMO JSON
    del scoreboard (proveedor DraftKings/consenso). Cero coste, sin clave. Es la
    fuente que rellena la mayoría de los partidos que The Odds API/Betexplorer
    no cubren. Devuelve {} si el evento no trae cuotas usables."""
    odds_list = comp.get('odds') or []
    if not odds_list:
        return {}
    o = odds_list[0] or {}

    def _lado(d):
        d = d or {}
        for k in ('close', 'open'):
            sub = d.get(k) or {}
            if sub.get('odds') is not None:
                return _am2dec(sub['odds'])
        return None

    ml = o.get('moneyline') or {}
    oh, oa = _lado(ml.get('home')), _lado(ml.get('away'))
    dv = (o.get('drawOdds') or {}).get('moneyLine')
    od = _am2dec(dv) if dv is not None else None
    salida = {}
    if oh and od and oa:
        salida.update({'odd_home': oh, 'odd_draw': od, 'odd_away': oa,
                       'casa': o.get('provider', {}).get('name') or 'ESPN'})
    # over/under 2.5 (solo si la línea es 2.5)
    total = o.get('total') or {}
    if (o.get('overUnder') == 2.5) or (str(total.get('over', {}).get('close', {})
                                           .get('line', '')).lstrip('o') == '2.5'):
        over = ((total.get('over') or {}).get('close') or
                (total.get('over') or {}).get('open') or {})
        under = ((total.get('under') or {}).get('close') or
                 (total.get('under') or {}).get('open') or {})
        oo, ou = _am2dec(over.get('odds')), _am2dec(under.get('odds'))
        if oo:
            salida['odd_over25'] = oo
        if ou:
            salida['odd_under25'] = ou

    # -----------------------------------------------------------------------
    # v106 — EL HÁNDICAP, QUE ESTABA EN EL MISMO JSON Y NO SE LEÍA.
    #
    # El scoreboard trae `pointSpread` con la línea y el precio de cada lado.
    # Sólo se leía el hándicap del CORE API (`odds_evento`), que es una
    # petición POR PARTIDO y que el barrido diario no hace para todas las
    # ligas. Resultado medido: de las 57 competiciones activas, sólo 20 tenían
    # backtest de hándicap — las 20 cuyo CSV de football-data trae columnas
    # asiáticas. Aquí sale gratis y para TODAS: 33 de 33 partidos con cuotas
    # en Liga MX, MLS, Brasileirão, Argentina y Premier lo traían (comprobado
    # el 2026-08-08).
    #
    # La línea que se guarda es la del LOCAL —negativa si es favorito—, que es
    # el convenio del resto del proyecto.
    ps = o.get('pointSpread') or {}

    def _linea(d):
        d = d or {}
        for k in ('close', 'open'):
            sub = d.get(k) or {}
            if sub.get('line') is not None:
                try:
                    return float(str(sub['line']).replace('+', ''))
                except ValueError:
                    return None
        return None

    linea_h = _linea(ps.get('home'))
    if linea_h is not None:
        salida['ah_linea'] = linea_h
        oah, oaa = _lado(ps.get('home')), _lado(ps.get('away'))
        if oah:
            salida['odd_ah_home'] = oah
        if oaa:
            salida['odd_ah_away'] = oaa
    return salida


# v71 — ventana por defecto: la SEMANA EN CURSO, no 3 días.
#
# Con `dias=3` la app enseñaba 2 partidos de Liga MX cuando la jornada tenía 9,
# y lo mismo en el resto de ligas: los fixtures del fin de semana no entraban
# hasta el jueves. Siete días cubren la jornada completa de cualquier liga.
#
# Cuesta lo mismo: es el mismo scoreboard con otro rango de fechas.
DIAS_SEMANA = 7


def fixtures_liga(clave: str, dias: int = DIAS_SEMANA,
                  ampliar: Optional[bool] = None) -> List[Dict]:
    """
    Próximos partidos (no finalizados) de una competición.

    v102 — busca en TODOS los códigos ESPN de la competición (el de la fase
    actual y el de la previa, ver `ESPN_COMPANEROS`) y, si `ampliar`, extiende
    el horizonte por escalones cuando la ventana viene vacía (`HORIZONTES`).
    Así «próximos partidos» quiere decir los siguientes que haya, no sólo los
    de esta semana.

    `ampliar=None` (por defecto) significa: ampliar SÓLO en la vista de próximos
    partidos, es decir cuando nadie ha pedido una ventana concreta. Importa,
    porque `alpha_finder._barrido_fixtures` pide `dias=2` justamente para
    quedarse con los de hoy: ampliarle el horizonte le haría pedir 90 días a
    cada liga fuera de temporada en cada barrido, para tirar después todo lo
    que no fuera de hoy.

    Devuelve [{'fecha': 'YYYY-MM-DD', 'home': str, 'away': str, ...}].
    """
    codigos = [c for c in ([ESPN_CODIGOS.get(clave)] +
                           ESPN_COMPANEROS.get(clave, [])) if c]
    if not codigos:
        return []
    if ampliar is None:
        ampliar = (dias == DIAS_SEMANA)
    ck = f'{clave}:{dias}:{int(ampliar)}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]

    # escalones: el pedido primero y luego los más largos. Si `dias` ya es
    # generoso no se amplía por debajo de él.
    escalones = [dias] + ([h for h in HORIZONTES if h > dias] if ampliar else [])
    fixtures: List[Dict] = []
    for horizonte in escalones:
        fixtures = []
        vistos = set()
        for code in codigos:
            for fx in _fixtures_de_codigo(clave, code, horizonte):
                # dos códigos de la misma competición no publican el mismo
                # partido, pero se deduplica por si acaso: repetir un partido
                # en la interfaz es peor que perderlo, porque se apostaría dos
                # veces sobre lo mismo creyendo que son eventos distintos.
                k = (fx.get('fecha'), fx.get('home'), fx.get('away'))
                if k in vistos:
                    continue
                vistos.add(k)
                fixtures.append(fx)
        if fixtures:
            if horizonte != dias:
                logger.info(f'[fixtures/{clave}] sin partidos en {dias} d; '
                            f'ampliado a {horizonte} d → {len(fixtures)}')
            break

    fixtures.sort(key=lambda f: (f.get('inicio') or f.get('fecha') or ''))
    for code in codigos:
        # v129: `clave` es la del proyecto («liga_mx»); `code` es la de ESPN
        # («mex.1»). La lista blanca del consenso usa la primera.
        _completar_cuotas(fixtures, 'futbol', 'soccer', code,
                          clave_proyecto=clave)
    logger.info(f"[fixtures/{clave}] {len(fixtures)} próximos partidos "
                f"(ESPN {'+'.join(codigos)}), "
                f"{sum(1 for f in fixtures if f.get('odd_home'))} con cuota.")
    _CACHE[ck] = (ahora, fixtures)
    return fixtures


# ---------------------------------------------------------------------------
# v162 — LOS PARTIDOS ACABADOS SE GUARDAN AL PASAR, EN VEZ DE PEDIRLOS OTRA VEZ
# ---------------------------------------------------------------------------
# `_fixtures_de_codigo` descarga el scoreboard de cada competición y TIRA los
# eventos `completed`, porque no son apostables. Desde la v162 la lista de hoy
# los enseña con su marcador, así que hacían falta — y la primera versión los
# pedía con 61 llamadas nuevas a `resultados_liga`.
#
# Medido: con esas 61 peticiones encima, la vista «Apuestas del Día» dejó de
# terminar. Son exactamente los mismos partidos que el scoreboard ya trajo y
# que se estaban descartando dos líneas más abajo.
#
# Así que se apuntan al pasar. La caché es por (competición, día) y vive lo
# mismo que la de fixtures. `jugados_del_dia` la mira primero y sólo pide por
# red lo que no esté — que en la práctica es nada, porque el barrido corre
# antes que la interfaz.
_JUGADOS: Dict[str, tuple] = {}


def _apuntar_jugado(clave: str, ev: dict, comp: dict) -> None:
    """Guarda un evento ya jugado del scoreboard que se está recorriendo."""
    try:
        loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
        vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
        gl, gv = int(loc.get('score')), int(vis.get('score'))
        fecha = pd.to_datetime(ev['date'])
        if fecha.tzinfo:
            fecha = fecha.tz_convert(None)
    except (KeyError, StopIteration, TypeError, ValueError):
        return
    dia = fecha.strftime('%Y-%m-%d')
    ck = f'{clave}:{dia}'
    ahora = time.time()
    previo = _JUGADOS.get(ck)
    lista = list(previo[1]) if (previo and ahora - previo[0] < _TTL) else []
    fila = {'fecha': dia, 'inicio': fecha.strftime('%Y-%m-%d %H:%M:%S'),
            'home': loc['team']['displayName'],
            'away': vis['team']['displayName'],
            'goles_home': gl, 'goles_away': gv}
    if not any(f['home'] == fila['home'] and f['away'] == fila['away']
               for f in lista):
        lista.append(fila)
    _JUGADOS[ck] = (ahora, lista)


def _fixtures_de_codigo(clave: str, code: str, dias: int) -> List[Dict]:
    """Los fixtures de UN código de ESPN. Sin caché: la pone `fixtures_liga`."""
    # v91 — EL RANGO SE ANCLA EN UTC, que es el reloj de ESPN.
    #
    # Estaba en hora local, y las fechas que ESPN devuelve (`ev['date']`) son
    # UTC: en cuanto la máquina va por detrás de UTC —cualquier huso de
    # América— el rango empezaba un día tarde respecto a lo que se filtraba
    # después. Medido en esta máquina (local 2026-08-02, UTC 2026-08-03): el
    # barrido del día pedía fixtures y luego descartaba los 12 que había,
    # dejando «partidos evaluados: 0». En Streamlit Cloud el servidor va en
    # UTC y por eso allí nunca se vio.
    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    # v162 — EL RANGO EMPIEZA UN DÍA ANTES, Y NO CUESTA UNA PETICIÓN MÁS.
    #
    # El scoreboard sirve el rango entero en una sola llamada, así que pedir
    # desde ayer es el mismo coste de red con un JSON algo mayor. Lo que se
    # gana: los partidos que ya se jugaron HOY EN CDMX caen en el día UTC
    # anterior —México va seis horas por detrás— y sin este día de más no
    # entraban en el barrido, así que `jugados_del_dia` tenía que volver a
    # pedirlos con 61 llamadas propias. Medido: con esas 61 encima, la vista
    # «Apuestas del Día» dejaba de terminar.
    #
    # NO añade ni un fixture apostable: todo lo de ayer está `completed` y el
    # bucle de abajo lo descarta igual — sólo que ahora, antes de descartarlo,
    # lo apunta en `_JUGADOS`.
    ini = (hoy - pd.Timedelta(days=1)).strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    fixtures: List[Dict] = []
    try:
        r = requests.get(ESPN_BASE.format(liga=code),
                         params={'dates': f'{ini}-{fin}', 'limit': 500},
                         timeout=TIMEOUT)
        r.raise_for_status()
        eventos = r.json().get('events', []) or []
    except Exception as e:
        logger.warning(f"[fixtures/{clave}] ESPN {code} falló: "
                       f"{type(e).__name__}: {e}")
        return []
    for ev in eventos:
        try:
            comp = ev['competitions'][0]
            estado = comp.get('status', ev.get('status', {})).get('type', {})
            if estado.get('completed'):
                # v162: se apunta antes de descartarlo. La lista de hoy los
                # enseña con su marcador y así no cuestan una petición aparte.
                _apuntar_jugado(clave, ev, comp)
                continue                       # ya jugado → no es fixture
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            fecha = pd.to_datetime(ev['date'])
            if fecha.tzinfo:
                fecha = fecha.tz_convert(None)
            # v162 — EL DÍA DE MÁS ES SÓLO PARA APUNTAR ACABADOS.
            #
            # El rango empieza ayer para capturar los partidos ya jugados sin
            # gastar una petición, pero lo que SALE de aquí tiene que ser
            # exactamente lo de antes: partidos de hoy en adelante. Un partido
            # de ayer que no esté `completed` —suspendido, en curso, aplazado—
            # pasaría el filtro de arriba y entraría en la lista como
            # apostable, que es justo lo que no puede ocurrir.
            if fecha.normalize() < hoy:
                continue
            fx = {
                'fecha': fecha.strftime('%Y-%m-%d'),
                # v88 — HORA DE INICIO (UTC). ESPN la publica y aquí se estaba
                # tirando al formatear a '%Y-%m-%d'. Sin ella no se puede
                # acotar «las próximas 24 horas»: con la fecha a secas, un
                # partido de mañana a las 23:00 y otro de dentro de una hora
                # son indistinguibles. `fecha` se mantiene para no romper a
                # nadie que ya la use.
                'inicio': fecha.strftime('%Y-%m-%d %H:%M:%S'),
                'home': loc['team']['displayName'],
                'away': vis['team']['displayName'],
                'event_id': ev.get('id'),      # v64: para las cuotas por evento
            }
            fx.update(_odds_de_evento(comp))   # v52: cuotas ESPN si las hay
            fx['_comp_id'] = comp.get('id')
            fixtures.append(fx)
        except Exception:
            continue
    return fixtures


def resultados_liga(clave: str, desde: str, hasta: str) -> List[Dict]:
    """
    v92 — partidos YA JUGADOS con su marcador, en [desde, hasta] (YYYY-MM-DD).

    Es el reverso exacto de `fixtures_liga`, que descarta los eventos
    `completed`. Hace falta para cerrar el circuito de retroalimentación: el
    proyecto registra los picks de cada día desde la v32 y NUNCA los liquidaba
    —`rendimiento_real.liquidar()` no tenía un solo llamador—, así que el
    panel de rendimiento real llevaba versiones vacío y no había forma de
    saber si el edge validado en backtest se estaba cobrando de verdad.

    Mismo endpoint, misma caché, coste cero: el scoreboard ya trae el marcador.
    """
    code = ESPN_CODIGOS.get(clave)
    if not code:
        return []
    ck = f'res:{clave}:{desde}:{hasta}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    ini = str(desde).replace('-', '')
    fin = str(hasta).replace('-', '')
    salida: List[Dict] = []
    try:
        r = requests.get(ESPN_BASE.format(liga=code),
                         params={'dates': f'{ini}-{fin}', 'limit': 500},
                         timeout=TIMEOUT)
        r.raise_for_status()
        eventos = r.json().get('events', []) or []
    except Exception as e:
        logger.warning(f"[resultados/{clave}] ESPN falló: {type(e).__name__}: {e}")
        _CACHE[ck] = (ahora, [])
        return []
    for ev in eventos:
        try:
            comp = ev['competitions'][0]
            estado = comp.get('status', ev.get('status', {})).get('type', {})
            if not estado.get('completed'):
                continue                       # aún no ha terminado
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            gl, gv = int(loc.get('score')), int(vis.get('score'))
            fecha = pd.to_datetime(ev['date'])
            if fecha.tzinfo:
                fecha = fecha.tz_convert(None)
            salida.append({'fecha': fecha.strftime('%Y-%m-%d'),
                           # v162 — la HORA, que antes se tiraba al formatear.
                           # Sin ella los partidos jugados no se pueden ordenar
                           # junto a los demás en la lista de hoy, que es donde
                           # el usuario los pidió: `_k_hora` ordena por
                           # `inicio` y sin el campo caían todos al final.
                           'inicio': fecha.strftime('%Y-%m-%d %H:%M:%S'),
                           'home': loc['team']['displayName'],
                           'away': vis['team']['displayName'],
                           'goles_home': gl, 'goles_away': gv})
        except (KeyError, StopIteration, TypeError, ValueError):
            continue
    logger.info(f"[resultados/{clave}] {len(salida)} partidos jugados "
                f"entre {desde} y {hasta}.")
    _CACHE[ck] = (ahora, salida)
    return salida


def jugados_del_dia(claves: List[str], dia: str,
                    max_hilos: int = 8) -> List[Dict]:
    """
    v161 — los partidos de `dia` que YA SE JUGARON, con su marcador.

    Por qué existe, y por qué NO va dentro del barrido
    --------------------------------------------------
    `fixtures_liga` descarta todo evento `completed`, y eso es correcto: no se
    puede apostar un partido acabado, y dejarlos entrar convertiría en «pick»
    algo que ya tiene resultado. Pero tiene un efecto que el usuario nota y que
    parece un fallo: **un sábado por la tarde la lista se queda casi vacía**.
    Medido el 2026-08-22, ESPN tenía 224 partidos de fútbol ese día y la
    aplicación enseñaba 55 — la mayor parte de la diferencia eran partidos ya
    jugados.

    Esto los recupera, pero por una puerta aparte y **bajo demanda**: el
    barrido tardó versiones en bajar de 119 s a 52 y no puede pagar 61
    peticiones más en cada carga. La interfaz los pide sólo cuando el usuario
    pulsa, y nunca entran en `pronosticos`, así que no pueden acabar en un pick
    ni en Telegram.

    Devuelve [{'clave_liga', 'liga', 'fecha', 'home', 'away', 'goles_home',
    'goles_away'}] ordenado por competición.
    """
    from concurrent.futures import ThreadPoolExecutor
    try:
        from config import LEAGUES as _LG
    except Exception:
        _LG = {}

    dia = str(dia)[:10]

    def _uno(clave):
        # LO QUE EL BARRIDO YA TRAJO NO SE VUELVE A PEDIR. `_fixtures_de_codigo`
        # apunta cada evento acabado al recorrer el scoreboard, así que cuando
        # la interfaz llega aquí lo normal es que no haga falta la red.
        guardado = _JUGADOS.get(f'{clave}:{dia}')
        if guardado and time.time() - guardado[0] < _TTL:
            return [dict(r, clave_liga=clave,
                         liga=(_LG.get(clave) or {}).get('nombre') or clave)
                    for r in guardado[1]]
        try:
            # La ventana se abre un día por cada lado porque la fecha que pide
            # la interfaz es de CDMX y ESPN publica en UTC: un partido de las
            # 19:00 en México es del día siguiente en UTC. Se recorta después.
            desde = (pd.Timestamp(dia) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            hasta = (pd.Timestamp(dia) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            return [dict(r, clave_liga=clave,
                         liga=(_LG.get(clave) or {}).get('nombre') or clave)
                    for r in resultados_liga(clave, desde, hasta)]
        except Exception as e:
            logger.debug('[jugados/%s] %s: %s', clave, type(e).__name__, e)
            return []

    salida: List[Dict] = []
    with ThreadPoolExecutor(max_workers=max_hilos) as ex:
        for lote in ex.map(_uno, list(claves)):
            salida.extend(lote or [])
    # el recorte fino, con la fecha que se pidió
    salida = [r for r in salida if str(r.get('fecha') or '')[:10] == dia]
    salida.sort(key=lambda r: (str(r.get('liga') or ''), str(r.get('home') or '')))
    logger.info('[jugados] %d partidos jugados el %s en %d competiciones',
                len(salida), dia, len(list(claves)))
    return salida


def claves_de_futbol() -> List[str]:
    """Las competiciones de fútbol que el barrido conoce y puede consultar."""
    try:
        from config import LEAGUES as _LG
    except Exception:
        return []
    return [c for c, cfg in _LG.items()
            if cfg.get('disponible') and c in ESPN_CODIGOS]


def resultados_tenis(desde: str, hasta: str) -> List[Dict]:
    """
    v93 — partidos de tenis YA JUGADOS con su GANADOR, de ATP y WTA.

    La estructura del scoreboard de tenis no es la de los deportes de equipo:
    cada `event` es un TORNEO y los partidos cuelgan de
    `groupings[*].competitions[*]`, cada uno con su `status.completed` y sus
    dos `competitors` con la bandera `winner`. Por eso el parser genérico no
    servía y el tenis se quedaba sin liquidar.

    Medido el 2026-08-03 sobre un solo día: 564 competiciones, **294
    finalizadas** con ganador — suficiente para cerrar el circuito del deporte
    que más picks emite después del fútbol.
    """
    ck = f'restenis:{desde}:{hasta}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    ini, fin = str(desde).replace('-', ''), str(hasta).replace('-', '')
    salida: List[Dict] = []
    for circuito in ('atp', 'wta'):
        try:
            r = requests.get(
                ESPN_BASE_DEP.format(path=f'tennis/{circuito}'),
                params={'dates': f'{ini}-{fin}'}, timeout=TIMEOUT)
            r.raise_for_status()
            eventos = r.json().get('events', []) or []
        except Exception as e:
            logger.warning(f'[tenis/{circuito}] ESPN falló: '
                           f'{type(e).__name__}: {e}')
            continue
        for ev in eventos:
            torneo = ev.get('name')
            for g in ev.get('groupings', []) or []:
                for c in g.get('competitions', []) or []:
                    try:
                        if not c.get('status', {}).get('type', {}).get('completed'):
                            continue
                        cs = c.get('competitors') or []
                        if len(cs) != 2:
                            continue      # dobles con formato raro, o walkover
                        nombres, ganador, juegos = [], None, []
                        for x in cs:
                            nom = (x.get('athlete') or {}).get('displayName')
                            if not nom:
                                nombres = []
                                break
                            nombres.append(nom)
                            if x.get('winner'):
                                ganador = nom
                            # v94 — MARCADOR POR SETS. ESPN lo publica en
                            # `linescores` (un valor por set) y no se estaba
                            # leyendo, así que los mercados derivados de tenis
                            # —juegos totales, hándicap de juegos, sets— no se
                            # podían liquidar. Se propuso buscar una fuente
                            # complementaria; no hace falta, ya estaba aquí.
                            juegos.append([float(l.get('value'))
                                           for l in (x.get('linescores') or [])
                                           if l.get('value') is not None])
                        if len(nombres) != 2 or not ganador:
                            continue
                        fecha = pd.to_datetime(c.get('date') or ev.get('date'))
                        if fecha.tzinfo:
                            fecha = fecha.tz_convert(None)
                        fila = {'fecha': fecha.strftime('%Y-%m-%d'),
                                'circuito': circuito.upper(),
                                'torneo': torneo,
                                'jugadores': nombres,
                                'ganador': ganador}
                        # sólo si los dos tienen el mismo número de sets: un
                        # abandono deja las listas descuadradas y liquidar con
                        # eso daría un total de juegos falso
                        if (len(juegos) == 2 and juegos[0] and
                                len(juegos[0]) == len(juegos[1])):
                            fila['juegos'] = juegos
                            fila['juegos_totales'] = int(sum(juegos[0])
                                                         + sum(juegos[1]))
                            fila['sets'] = [
                                sum(1 for a, b in zip(*juegos) if a > b),
                                sum(1 for a, b in zip(*juegos) if b > a)]
                        salida.append(fila)
                    except (KeyError, TypeError, ValueError):
                        continue
    logger.info(f'[tenis] {len(salida)} partidos con ganador entre '
                f'{desde} y {hasta}.')
    _CACHE[ck] = (ahora, salida)
    return salida


def con_cuota(fixtures: List[Dict]) -> Dict:
    """
    v72 — separa los fixtures APOSTABLES (los que ya tienen cuota) del resto, y
    dice cuándo merece la pena volver si no hay ninguno.

    Por qué: enseñar los 8 partidos de la semana cuando solo 2 tienen precio
    invita a apostar a ciegas. Las casas abren línea 2-4 días antes, así que
    con la fecha del próximo partido se puede decir con precisión la fecha de
    vuelta en vez de un «no hay nada» sin más.

    Devuelve:
      {'apostables': [...], 'sin_cuota': [...], 'proximo': 'YYYY-MM-DD'|None,
       'volver_el': 'YYYY-MM-DD'|None, 'dias_para_volver': int|None}
    """
    apostables = [f for f in fixtures if f.get('odd_home') and f.get('odd_away')]
    sin_cuota = [f for f in fixtures if f not in apostables]
    info = {'apostables': apostables, 'sin_cuota': sin_cuota,
            'proximo': None, 'volver_el': None, 'dias_para_volver': None}
    if apostables or not sin_cuota:
        return info
    try:
        fechas = sorted(pd.Timestamp(f['fecha']) for f in sin_cuota if f.get('fecha'))
    except Exception:
        return info
    if not fechas:
        return info
    prox = fechas[0]
    # las casas suelen abrir 3 días antes; se recomienda volver ese día, y
    # nunca antes de mañana
    # v102 — UTC: `prox` sale de las fechas de los fixtures, que son UTC.
    # Restarle un `hoy` local mezcla dos relojes y desplaza la
    # recomendacion un dia en medio mundo.
    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    volver = max(prox - pd.Timedelta(days=3), hoy + pd.Timedelta(days=1))
    volver = min(volver, prox)
    info['proximo'] = prox.strftime('%Y-%m-%d')
    info['volver_el'] = volver.strftime('%Y-%m-%d')
    info['dias_para_volver'] = int((volver - hoy).days)
    return info


def _completar_cuotas(fixtures: List[Dict], deporte: str, dep_espn: str,
                      liga_espn: str, clave_proyecto: Optional[str] = None) -> int:
    """
    v71 — rellena las cuotas que ESPN no trajo, sin coste de cuota de API.

    v129 — `clave_proyecto` es la clave interna de la competición («liga_mx»,
    «laliga»…), que NO es lo mismo que `liga_espn` («mex.1», «esp.1»). Hace
    falta porque la lista blanca del consenso ampliado está indexada por la
    primera, y esta función pasaba la segunda: por eso el barrido del día
    nunca pedía el consenso y el contador de créditos se quedaba a cero.
    Ver `cuotas_multi.cuotas_partido`.

    El scoreboard de ESPN cubre ~32 % de los fixtures. El resto se completa con
    el tablón público de Pinnacle (sin clave ni límite) y, si aún falta, con el
    core API de ESPN por evento. Medido en la ventana apostable (0-2 días) la
    cobertura pasa de ~32 % a **74 %**, y para los partidos de HOY a **93 %**.

    Lo que queda sin cuota son partidos a 5-7 días —ninguna casa ha abierto
    línea todavía— y un puñado de ligas que ningún operador cubre (Bolivia,
    El Salvador). Eso se marca como tal en la UI en vez de fingir una cuota.
    """
    if not fixtures:
        return 0
    try:
        import cuotas_multi as cm
    except Exception as e:
        logger.debug(f"[fixtures] cuotas_multi no disponible: {e}")
        return 0
    # v149 — LAS 354 PETICIONES DEJAN DE IR EN FILA INDIA.
    #
    # Medido con `_v149_perfil_barrido.py` y afinado con un contador por
    # función sobre el barrido real de fútbol:
    #
    #     rama de fútbol                140,5 s
    #     cuotas_partido   354 llamadas 262,7 s  (0,74 s cada una)
    #       _buscar       1770 llamadas  17,2 s
    #       _indice × 5    354 c/u        1,5 s
    #       ────────────────────────────────────
    #       sin explicar                ~244 s   ← el 90 % de su coste
    #
    # Los 244 s son `cuotas_core_espn`: **una petición HTTP por partido** al
    # core API de ESPN, y este bucle las hacía una detrás de otra. No es
    # cálculo, es el proceso parado esperando la red — que es exactamente lo
    # que la v79 ya había aprendido con las ramas de deporte y lo que la v147
    # aprendió con la ficha («el coste era RED, no cálculo»). Aquí quedaba el
    # último sitio donde no se había aplicado.
    #
    # Dos fases a propósito:
    #   1. la RED en paralelo, que es donde está el tiempo;
    #   2. las escrituras sobre `fx` en el hilo principal, en el mismo orden de
    #      siempre. Cada fixture sólo toca su propio diccionario, así que
    #      hacerlo en las hebras también sería correcto, pero secuencial es
    #      DETERMINISTA y este bucle decide qué precio ve el usuario.
    #
    # CUATRO hebras, no ocho ni treinta. `fixtures_multi` ya abre una hebra por
    # liga, así que el multiplicador real es 49 × N: con ocho serían casi
    # cuatrocientas peticiones simultáneas contra ESPN, que ya bloquea por IP a
    # los centros de datos (v147). Medido, el salto de secuencial a paralelo
    # aquí vale poco —`fixtures_multi` pasa de 41,3 s a 29,8 s— porque estas
    # llamadas ya iban solapadas entre ligas; cuatro se queda con esa ganancia
    # sin parecer un raspador.
    from concurrent.futures import ThreadPoolExecutor

    # Los índices de las casas se calientan ANTES de abrir el pool: los cachea
    # el proceso, pero si ocho hebras llegan a la vez con el caché frío, las
    # ocho se bajan el mismo tablón.
    try:
        cm.precargar(deporte)
    except Exception as e:
        logger.debug(f"[fixtures] precarga de tablones: {e}")

    def _pedir(fx):
        if not fx.get('event_id'):
            return fx, None
        try:
            ref = (dep_espn, liga_espn, fx.get('event_id'), fx.get('_comp_id'))
            return fx, cm.cuotas_partido(
                deporte, fx['home'], fx['away'], espn_ref=ref,
                fecha=fx.get('inicio') or fx.get('fecha'),
                liga=liga_espn, clave_consenso=clave_proyecto)
        except Exception:
            return fx, None

    with ThreadPoolExecutor(max_workers=4,
                            thread_name_prefix='cuotas149') as _pool:
        _resultados = list(_pool.map(_pedir, fixtures))

    n = 0
    for fx, res in _resultados:
        if res is None:
            continue
        # v80 — AQUÍ ESTABA EL «0 PICKS CALIBRADOS».
        #
        # Esto era `if fx.get('odd_home'): continue`. Tenía sentido en la v71,
        # cuando esta función solo servía para RELLENAR el precio que ESPN no
        # traía: si ya había precio, no había nada que rellenar.
        #
        # Pero desde la v71 esta misma llamada es también la ÚNICA que trae el
        # ancla sharp (`odd_home_pin`), que es lo que activa el encogimiento
        # hacia el mercado. Con el `continue`, todo fixture que ESPN sí cubría
        # se saltaba la consulta y se quedaba sin ancla — y los que ESPN cubre
        # son justo los partidos populares, o sea los que acaban produciendo
        # picks. Medido el 2026-07-29: solo **23 de 160 fixtures** llevaban
        # `odd_home_pin`, y **0 de 40 picks** de fútbol salían calibrados,
        # pese a que Pinnacle publicaba precio para el **73 %** de los
        # partidos del día.
        #
        # Importa porque el edge del fútbol se validó CON encogimiento: sobre
        # las 36.006 filas del ledger, la política que producción aplicaba de
        # verdad da ROI +3,65 % con p5 **−1,11 %** (sin edge), y la validada
        # +6,72 % con p5 +1,02 %.
        #
        # Ahora se consulta SIEMPRE para obtener el ancla, y el precio de ESPN
        # se respeta: solo se escribe `odd_home` si no venía ya.
        # v114 — la FECHA del fixture viaja a la búsqueda (ver `_pedir`). Es lo
        # que impide que el emparejador tome las cuotas de otro partido del
        # mismo cruce jugado otro día (ida y vuelta, o la categoría femenina
        # del mismo club). Ver `cuotas_multi._buscar`.
        tenia_precio = bool(fx.get('odd_home'))
        # El ANCLA SHARP se toma siempre que exista, traiga o no precio ESPN:
        # es lo que activa el encogimiento hacia el mercado.
        pin = res.get('pinnacle')
        if pin and pin.get('home') and pin.get('away'):
            fx['odd_home_pin'] = pin.get('home')
            fx['odd_draw_pin'] = pin.get('draw')
            fx['odd_away_pin'] = pin.get('away')

        mejor = res.get('mejor') or {}
        if not mejor.get('home') or not mejor.get('away'):
            continue
        if tenia_precio:
            # ESPN ya había traído precio: no se pisa (es el que la UI viene
            # mostrando y con el que se calcularon los mercados derivados).
            # Solo se ha venido a por el ancla.
            n += 1
            continue
        fx['odd_home'] = mejor['home']['cuota']
        fx['odd_away'] = mejor['away']['cuota']
        if mejor.get('draw'):
            fx['odd_draw'] = mejor['draw']['cuota']
        fx['casa'] = mejor['home']['casa']
        fx['n_casas'] = res.get('n_casas')
        fx['casas'] = res.get('casas')
        tot = res.get('totales') or {}
        if tot.get('over25'):
            fx.setdefault('odd_over25', tot['over25'])
        if tot.get('under25'):
            fx.setdefault('odd_under25', tot['under25'])
        n += 1
    return n


# v59: otros deportes en el MISMO scoreboard de ESPN (mismo patrón, sin clave).
# Verificado 2026-07-24: MLB devuelve 57 partidos programados; la NBA 0 por
# estar fuera de temporada (correcto, no es un fallo).
ESPN_DEPORTES = {
    'mlb': 'baseball/mlb',
    'nba': 'basketball/nba',
    # v131 — NFL. Verificado 2026-08-15: la pretemporada devuelve 16 partidos
    # y el scoreboard trae la temporada y su tipo dentro de cada evento, así
    # que `nfl_datos` puede distinguir pretemporada de liga regular sin una
    # petición más. El calendario propio de la NFL vive en
    # `nfl_datos.fixtures_nfl`, que además traduce a abreviatura y degrada al
    # catálogo de Playdoit; esta entrada es la que hace funcionar el selector
    # genérico de próximos partidos de la interfaz.
    'nfl': 'football/nfl',
}
ESPN_BASE_DEP = 'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard'


def fixtures_deporte(deporte: str, dias: int = DIAS_SEMANA) -> List[Dict]:
    """Próximos partidos de un deporte NO futbolístico (mlb, nba) desde ESPN.
    Devuelve [{'fecha','home','away'}] con los nombres que publica ESPN."""
    path = ESPN_DEPORTES.get(deporte)
    if not path:
        return []
    ck = f'dep:{deporte}:{dias}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    # v98 — LA MLB YA NO DEPENDE DE ESPN.
    #
    # La vista decía «Sin partidos programados en las próximas 48 h» teniendo
    # picks de MLB en la misma pantalla. El log de producción lo explica:
    #
    #     [fixtures/mlb] ESPN falló: HTTPError: 403 Client Error: Forbidden
    #     for url: .../baseball/mlb/scoreboard?dates=20260805-20260812
    #
    # ESPN responde **403 desde Streamlit Cloud** (IP de centro de datos) a la
    # misma petición que aquí devuelve 200. No es la ventana de fechas ni el
    # User-Agent: es de dónde sale la petición, y eso no se arregla desde el
    # código. La MLB publica su propio calendario —gratis, sin clave, con el
    # abridor probable y con la hora de inicio—, y este proyecto ya lo usa
    # para entrenar. Se antepone: ESPN queda como respaldo.
    if deporte == 'mlb':
        try:
            import mlb_statsapi
            oficial = mlb_statsapi.proximos(dias)
            if oficial:
                _completar_cuotas(oficial, deporte, *path.split('/'))
                logger.info(f"[fixtures/mlb] {len(oficial)} próximos partidos "
                            f"(MLB StatsAPI), "
                            f"{sum(1 for f in oficial if f.get('odd_home'))} con cuota.")
                _CACHE[ck] = (ahora, oficial)
                return oficial
        except Exception as e:
            logger.warning(f"[fixtures/mlb] StatsAPI falló ({type(e).__name__}: "
                           f"{e}); se intenta con ESPN.")

    # v102 — UTC, igual que `_fixtures_de_codigo`. La v91 anclo el reloj en
    # `fixtures_liga` y dejo fuera esta ruta: seguia pidiendo el rango con la
    # hora local, asi que en cualquier huso por detras de UTC empezaba un dia
    # tarde y se descartaban partidos que si existian. En Streamlit Cloud el
    # servidor va en UTC y por eso nunca se vio alli.
    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    salida: List[Dict] = []
    try:
        r = requests.get(ESPN_BASE_DEP.format(path=path),
                         params={'dates': f'{ini}-{fin}', 'limit': 300},
                         timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        eventos = r.json().get('events', []) or []
    except Exception as e:
        logger.warning(f"[fixtures/{deporte}] ESPN falló: {type(e).__name__}: {e}")
        _CACHE[ck] = (ahora, [])
        return []
    for ev in eventos:
        try:
            comp = ev['competitions'][0]
            if comp.get('status', ev.get('status', {})).get('type', {}).get('completed'):
                continue
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            fecha = pd.to_datetime(ev['date'])
            if fecha.tzinfo:
                fecha = fecha.tz_convert(None)
            fx = {'fecha': fecha.strftime('%Y-%m-%d'),
                  # v88 — hora de inicio en UTC; ver `fixtures_liga`.
                  'inicio': fecha.strftime('%Y-%m-%d %H:%M:%S'),
                  'home': loc['team']['displayName'],
                  'away': vis['team']['displayName'],
                  'event_id': ev.get('id'), '_comp_id': comp.get('id')}
            fx.update(_odds_de_evento(comp))
            salida.append(fx)
        except Exception:
            continue
    # v71: mismas cuotas automáticas que en fútbol (Pinnacle + core de ESPN).
    # En MLB el scoreboard no trae cuotas casi nunca y esto las recupera.
    _completar_cuotas(salida, deporte, *path.split('/'))
    logger.info(f"[fixtures/{deporte}] {len(salida)} próximos partidos (ESPN), "
                f"{sum(1 for f in salida if f.get('odd_home'))} con cuota.")
    _CACHE[ck] = (ahora, salida)
    return salida


# v60: competiciones de SELECCIONES NACIONALES. Tras el Mundial 2026 la vista
# «Partidos Internacionales» debe mostrar lo que viene de verdad: amistosos,
# Nations League y clasificatorias. Verificado 2026-07-24: 165 partidos
# programados a 200 días (amistosos desde el 23-sep, Nations League 24-sep).
# v114 — TODAS las competiciones de selecciones, no sólo siete masculinas.
#
# El usuario lo pidió explícito: «quiero que se encuentren todos los partidos a
# nivel de selecciones nacionales, ya sea varonil, femenil, amistosos, etc».
# Esta lista tenía amistosos, la Nations League de UEFA y cinco clasificatorias
# — o sea, ningún torneo continental, ninguna competición femenina y ninguna
# olímpica.
#
# Las quince añadidas están COMPROBADAS una a una contra el endpoint el
# 2026-08-09 (`_v114_espn_selecciones.py`): las 22 de aquí abajo responden 200.
# Cuatro que se probaron NO existen con ese nombre y devuelven 400, así que no
# se incluyen y quedan anotadas para no volver a intentarlas a ciegas:
# `uefa.euro.u21`, `conmebol.america.fem`, `concacaf.gold.w` y `ofc.nations`.
#
# El nombre del torneo IMPORTA, no es decorativo: viaja al emparejador de
# cuotas como nombre de competición, y de ahí sale la marca de categoría que
# impide que un amistoso femenino tome el precio del masculino entre los
# mismos dos países (ver `cuotas_multi.categoria_partido`). Por eso los
# femeninos llevan «(femenino)» en el nombre.
LIGAS_SELECCIONES = [
    ('fifa.friendly', 'Amistoso'),
    ('uefa.nations', 'UEFA Nations League'),
    ('fifa.worldq.uefa', 'Clasif. UEFA'),
    ('fifa.worldq.concacaf', 'Clasif. CONCACAF'),
    ('fifa.worldq.conmebol', 'Clasif. CONMEBOL'),
    ('fifa.worldq.afc', 'Clasif. AFC'),
    ('fifa.worldq.caf', 'Clasif. CAF'),
    # --- v114: el resto del calendario internacional masculino -------------
    ('fifa.world', 'Copa del Mundo'),
    ('fifa.worldq.ofc', 'Clasif. OFC'),
    ('uefa.euro', 'Eurocopa'),
    ('uefa.euroq', 'Clasif. Eurocopa'),
    ('conmebol.america', 'Copa América'),
    ('concacaf.gold', 'Copa Oro'),
    ('concacaf.nations.league', 'CONCACAF Nations League'),
    ('caf.nations', 'Copa África'),
    ('afc.asian.cup', 'Copa Asia'),
    ('fifa.confederations', 'Copa Confederaciones'),
    ('fifa.olympics', 'Juegos Olímpicos'),
    # --- v114: competiciones FEMENINAS -------------------------------------
    ('fifa.friendly.w', 'Amistoso femenino'),
    ('fifa.wwc', 'Mundial femenino'),
    ('uefa.weuro', 'Eurocopa femenina'),
    ('fifa.w.olympics', 'Juegos Olímpicos femenino'),
]


# v114 — RECONOCER UNA COMPETICIÓN DE SELECCIONES POR EL NOMBRE DE SU LIGA.
#
# Hace falta porque ESPN devuelve **403 a las IPs de centro de datos**, o sea
# SIEMPRE en Streamlit Cloud (la v110 ya lo documentó para otras rutas). En
# producción las 22 competiciones fallaban las 22, y la vista de selecciones se
# quedaba sin calendario — que es justo lo que el usuario reportó.
#
# El tablón de cuotas no tiene ese problema: ya se descarga entero para el
# resto de la app, no lo bloquea nadie y, por construcción, todo lo que hay
# ahí TIENE precio. Así que se usa como fuente propia y ESPN pasa a refuerzo.
#
# Los negativos son tan importantes como los positivos: «Club Friendlies»,
# «International Club — …», la Libertadores y las previas de UEFA son torneos
# de CLUBES y llevan palabras que, sueltas, parecen de selecciones.
_SEL_POSITIVO = re.compile(
    r'world cup|nations league|friendl|amistoso|eurocopa|\beuro\b|'
    r'copa am[eé]rica|gold cup|copa oro|africa cup|women cup of nations|'
    r'asian cup|copa asia|olympic|ol[ií]mpic|confederations|'
    r'world cup qualif|clasificat|eliminat', re.I)
_SEL_NEGATIVO = re.compile(
    r'\bclub|clubes|libertadores|sudamericana|champions league|'
    r'europa league|conference league|premier|liga mx|serie a|bundesliga|'
    r'ligue 1|eredivisie|primeira', re.I)

# Las categorías inferiores son el caso difícil: «Campeonato Sub-20 CONCACAF»
# es de selecciones y «Paulista Sub-20» o «Myanmar — Championship U20» son
# ligas de filiales de club, con el mismo «Sub-20» en el nombre. Medido sobre
# el tablón del 2026-08-09, esas tres se colaban.
#
# Lo que las separa no es la edad: es que un torneo de selecciones inferiores
# SIEMPRE nombra a su confederación o se declara internacional.
_SEL_JUVENIL = re.compile(r'sub-?\s?\d\d|u-?\d\d', re.I)
_SEL_CONFEDERACION = re.compile(
    r'concacaf|conmebol|uefa|\bafc\b|\bcaf\b|\bofc\b|fifa|international|'
    r'internacional|selecc', re.I)


def es_competicion_de_selecciones(liga: str) -> bool:
    """¿El nombre de esta competición es de selecciones y no de clubes?"""
    t = str(liga or '')
    if not t or _SEL_NEGATIVO.search(t):
        return False
    if _SEL_POSITIVO.search(t):
        return True
    # categoría inferior: sólo si además nombra confederación o se declara
    # internacional (ver el comentario de arriba)
    return bool(_SEL_JUVENIL.search(t) and _SEL_CONFEDERACION.search(t))


# Marca de «ESPN nos tiene bloqueados». Caduca sola: si algún día deja de
# bloquear (otra IP, otra política), la fuente vuelve sin tocar nada.
_ESPN_BLOQUEADO_HASTA = [0.0]
TTL_BLOQUEO_ESPN = 3600 * 6


def _espn_bloqueado() -> bool:
    return time.time() < _ESPN_BLOQUEADO_HASTA[0]


def _marcar_espn_bloqueado() -> None:
    _ESPN_BLOQUEADO_HASTA[0] = time.time() + TTL_BLOQUEO_ESPN


def _con_tablon(salida: List[Dict], ck: str, ahora: float,
                limite: int) -> List[Dict]:
    """Completa (o sustituye) el calendario con lo que cotizan las casas."""
    try:
        del_tablon = selecciones_del_tablon()
    except Exception as e:
        logger.info(f'[selecciones] tablón no disponible: {type(e).__name__}: {e}')
        del_tablon = []
    try:
        import cuotas_multi as _cm_sel
        _norm = _cm_sel.normalizar
    except Exception:
        def _norm(x):
            return str(x or '').lower()
    vistos = {(_norm(f['home']), _norm(f['away']), str(f['fecha'])[:10])
              for f in salida}
    for f in del_tablon:
        k = (_norm(f['home']), _norm(f['away']), str(f['fecha'])[:10])
        if k not in vistos:
            vistos.add(k)
            salida.append(f)
    salida.sort(key=lambda x: str(x.get('fecha') or ''))
    salida = salida[:limite]
    logger.info(f"[selecciones] {len(salida)} próximos partidos de selecciones "
                f"({len(del_tablon)} del tablón de cuotas).")
    _CACHE[ck] = (ahora, salida)
    return salida


def selecciones_del_tablon() -> List[Dict]:
    """
    Partidos de selecciones que las casas ya están cotizando.

    Cero peticiones nuevas —el tablón se descarga igualmente para todo lo
    demás— y sin 403, que es lo que rompe la vía de ESPN en producción. A
    cambio sólo ve lo que hay abierto: fuera de las ventanas FIFA, poco o
    nada. Es un resultado correcto, no un fallo.
    """
    try:
        import cuotas_multi as cm
    except Exception as e:
        logger.debug(f'[selecciones/tablon] cuotas_multi no disponible: {e}')
        return []
    salida, vistos = [], set()
    for obtener in (cm._indice, cm._indice_pdt, cm._indice_bov, cm._indice_uni):
        try:
            idx = obtener('futbol')
        except Exception:
            continue
        for v in (idx or {}).values():
            liga = v.get('liga') or ''
            if not es_competicion_de_selecciones(liga):
                continue
            home, away = v.get('home'), v.get('away')
            fecha = str(v.get('fecha') or '')[:10]
            k = (cm.normalizar(home), cm.normalizar(away), fecha)
            if not home or not away or k in vistos:
                continue
            vistos.add(k)
            salida.append({'fecha': fecha, 'home': home, 'away': away,
                           'torneo': liga, 'inicio': v.get('fecha'),
                           'origen': 'tablon',
                           'casas': [v.get('casa')] if v.get('casa') else []})
    salida.sort(key=lambda x: str(x.get('fecha') or ''))
    logger.info(f'[selecciones/tablon] {len(salida)} partidos con cuota abierta')
    return salida


def fixtures_selecciones(dias: int = 210, limite: int = 200) -> List[Dict]:
    """Próximos partidos de SELECCIONES NACIONALES (amistosos, Nations League y
    clasificatorias) desde ESPN. Devuelve [{'fecha','home','away','torneo'}]
    ordenados por fecha. La ventana es amplia porque las fechas FIFA son
    ventanas concretas separadas por meses."""
    ck = f'selecciones:{dias}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    # v102 — UTC, igual que `_fixtures_de_codigo`. La v91 anclo el reloj en
    # `fixtures_liga` y dejo fuera esta ruta: seguia pidiendo el rango con la
    # hora local, asi que en cualquier huso por detras de UTC empezaba un dia
    # tarde y se descartaban partidos que si existian. En Streamlit Cloud el
    # servidor va en UTC y por eso nunca se vio alli.
    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    salida: List[Dict] = []
    # v115 — CORTACIRCUITOS: SI ESPN NOS TIENE BLOQUEADOS, NO SE INSISTE 22 VECES.
    #
    # ESPN devuelve 403 a las IPs de centro de datos, así que en Streamlit
    # Cloud fallan TODAS las competiciones, siempre. El aviso «una vez por
    # liga» seguía siendo 22 peticiones inútiles y 22 líneas de registro en
    # cada arranque de proceso — el usuario mandó ese muro de 403 dos veces.
    #
    # Un 403 no es un fallo de esa competición: es un veto a la fuente entera.
    # Con dos seguidos se da por bloqueada y se salta el resto, que además
    # ahorra 20 peticiones y su tiempo de espera. El estado se guarda para no
    # reintentar en cada refresco, pero caduca — si el bloqueo se levanta (otra
    # IP, otra política), la fuente vuelve sola en la siguiente ventana.
    _bloqueos = 0
    if _espn_bloqueado():
        logger.info('[selecciones] ESPN marcado como bloqueado (403); se usa '
                    'sólo el tablón de cuotas hasta que caduque la marca')
        return _con_tablon([], ck, ahora, limite)
    for liga, torneo in LIGAS_SELECCIONES:
        if _bloqueos >= 2:
            logger.info(f'[selecciones] ESPN responde 403; se dejan de pedir '
                        f'las competiciones restantes en esta corrida')
            _marcar_espn_bloqueado()
            break
        try:
            r = requests.get(ESPN_BASE.format(liga=liga),
                             params={'dates': f'{ini}-{fin}', 'limit': 400},
                             timeout=TIMEOUT,
                             headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code == 403:
                _bloqueos += 1
                _avisar_una_vez('selecciones:403',
                                '[selecciones] ESPN devuelve 403 (bloquea las '
                                'IPs de centro de datos). El calendario sale '
                                'del tablón de cuotas.')
                continue
            r.raise_for_status()
            eventos = r.json().get('events', []) or []
        except Exception as e:
            # v110 — SE AVISA UNA VEZ POR LIGA, NO EN CADA CARGA.
            #
            # ESPN devuelve 403 a las IPs de centro de datos (lo mismo que la
            # v98 documentó con el scoreboard de MLB), así que en Streamlit
            # Cloud estas ocho competiciones fallan SIEMPRE. El resultado vacío
            # sí se cachea, pero con el aviso a nivel WARNING el log de
            # producción se llenaba de dieciséis líneas idénticas cada vez que
            # el caché caducaba — y ese ruido tapaba los errores reales.
            #
            # El fallo se sigue registrando: la primera vez en WARNING y las
            # siguientes en debug. Perder la señal no es una opción; repetirla
            # sesenta veces tampoco.
            _avisar_una_vez(f'selecciones:{liga}',
                            f"[selecciones/{liga}] {type(e).__name__}: {e}")
            continue
        for ev in eventos:
            try:
                comp = ev['competitions'][0]
                if comp.get('status', ev.get('status', {})).get('type', {}).get('completed'):
                    continue
                loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
                fecha = pd.to_datetime(ev['date'])
                if fecha.tzinfo:
                    fecha = fecha.tz_convert(None)
                salida.append({'fecha': fecha.strftime('%Y-%m-%d'),
                               'home': loc['team']['displayName'],
                               'away': vis['team']['displayName'],
                               'torneo': torneo,
                               # v114: la hora exacta y el evento, para poder
                               # pedir cuotas del partido correcto y enseñar la
                               # hora de CDMX como en el resto de la app
                               'inicio': ev.get('date'),
                               'event_id': ev.get('id'),
                               'liga_espn': liga})
            except Exception:
                continue
    # v114/v115 — el tablón completa (o sustituye) lo que ESPN no ha dado.
    # En Streamlit Cloud ESPN da 403 siempre y `salida` llega vacía; el tablón
    # de cuotas no se bloquea y es lo que salva la vista allí.
    return _con_tablon(salida, ck, ahora, limite)



def fixtures_multi(claves: List[str], dias: int = 3) -> Dict[str, List[Dict]]:
    """v50.1: descarga los fixtures de MUCHAS ligas EN PARALELO. Convierte
    ~14 llamadas secuenciales (que colgaban el barrido en Streamlit Cloud) en
    un único lote concurrente. Cada liga sigue cacheada individualmente."""
    from concurrent.futures import ThreadPoolExecutor
    claves = [c for c in claves if c in ESPN_CODIGOS]
    if not claves:
        return {}
    salida: Dict[str, List[Dict]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(claves))) as ex:
        futuros = {ex.submit(fixtures_liga, c, dias): c for c in claves}
        for fut in futuros:
            c = futuros[fut]
            try:
                salida[c] = fut.result()
            except Exception as e:
                logger.warning(f"[fixtures/{c}] {type(e).__name__}: {e}")
                salida[c] = []
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import sys
    claves = sys.argv[1:] or ['liga_mx', 'mls', 'brasil', 'argentina']
    for c in claves:
        fs = fixtures_liga(c)
        print(f"\n{c}: {len(fs)} partidos")
        for f in fs[:6]:
            print(f"  {f['fecha']}  {f['home']} vs {f['away']}")


# ---------------------------------------------------------------------------
# v64 — CUOTAS AUTOMÁTICAS POR EVENTO (hándicap + props de jugador).
#
# El scoreboard ya daba 1X2 y O/U (v52). El endpoint `core` POR EVENTO añade,
# también gratis y sin clave:
#   · spread + spreadOdds  → el HÁNDICAP con su cuota real
#   · propBets             → ~229 mercados por partido, incluido «First
#                            Goalscorer» / «Anytime Goalscorer», con cuota
#                            DECIMAL real y el atleta al que pertenecen.
# Verificado 2026-07-24 en Liga MX (proveedor DraftKings).
# ---------------------------------------------------------------------------
ESPN_CORE_ODDS = ('https://sports.core.api.espn.com/v2/sports/soccer/leagues/'
                  '{liga}/events/{eid}/competitions/{eid}/odds')
TTL_ODDS = 900          # 15 min: las cuotas se mueven


def _num(x):
    try:
        v = float(x)
        return v if v == v else None       # descarta NaN
    except (TypeError, ValueError):
        return None


def _am2dec_seguro(ml):
    v = _am2dec(ml)
    return v if v and v > 1.0 else None


def odds_evento(clave: str, event_id: str) -> Dict:
    """Cuotas del EVENTO: 1X2, over/under y HÁNDICAP con su cuota. {} si no hay."""
    code = ESPN_CODIGOS.get(clave)
    if not code or not event_id:
        return {}
    ck = f'oddsev:{clave}:{event_id}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < TTL_ODDS:
        return _CACHE[ck][1]
    try:
        r = requests.get(ESPN_CORE_ODDS.format(liga=code, eid=event_id),
                         timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        items = r.json().get('items') or []
    except Exception as e:
        logger.warning(f"[odds/{clave}/{event_id}] {type(e).__name__}: {e}")
        _CACHE[ck] = (ahora, {})
        return {}
    if not items:
        _CACHE[ck] = (ahora, {})
        return {}
    it = items[0]
    ho, ao = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
    salida = {
        'casa': (it.get('provider') or {}).get('name') or 'ESPN',
        'odd_home': _am2dec_seguro(ho.get('moneyLine')),
        'odd_away': _am2dec_seguro(ao.get('moneyLine')),
        'odd_draw': _am2dec_seguro((it.get('drawOdds') or {}).get('moneyLine')),
        'ou_linea': _num(it.get('overUnder')),
        'odd_over': _am2dec_seguro(it.get('overOdds')),
        'odd_under': _am2dec_seguro(it.get('underOdds')),
        # HÁNDICAP: la línea es del LOCAL (negativa = favorito)
        'ah_linea': _num(it.get('spread')),
        'odd_ah_home': _am2dec_seguro(ho.get('spreadOdds')),
        'odd_ah_away': _am2dec_seguro(ao.get('spreadOdds')),
        'event_id': event_id,
    }
    _CACHE[ck] = (ahora, salida)
    return salida


def props_evento(clave: str, event_id: str, max_paginas: int = 4,
                 nombres: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Props del evento con CUOTA DECIMAL real. `nombres` mapea id de atleta →
    nombre (se obtiene del roster cacheado de goleadores.py) para no gastar una
    petición por jugador. Devuelve [{'tipo','atleta','cuota'}]."""
    code = ESPN_CODIGOS.get(clave)
    if not code or not event_id:
        return []
    ck = f'props:{clave}:{event_id}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < TTL_ODDS:
        return _CACHE[ck][1]
    base = (ESPN_CORE_ODDS.format(liga=code, eid=event_id)
            + '/100/propBets?limit=25')
    salida: List[Dict] = []
    try:
        for pagina in range(1, max_paginas + 1):
            r = requests.get(f'{base}&page={pagina}', timeout=TIMEOUT,
                             headers={'User-Agent': 'Mozilla/5.0'})
            r.raise_for_status()
            j = r.json()
            for it in (j.get('items') or []):
                cuota = ((it.get('current') or {}).get('over') or {}).get('decimal')
                cuota = _num(cuota)
                if not cuota or cuota <= 1.0:
                    continue
                ref = (it.get('athlete') or {}).get('$ref') or ''
                aid = ref.rstrip('/').split('/')[-1].split('?')[0] if ref else ''
                salida.append({
                    'tipo': (it.get('type') or {}).get('name') or 'Prop',
                    'atleta_id': aid,
                    'atleta': (nombres or {}).get(aid, ''),
                    'cuota': round(cuota, 2),
                })
            if pagina >= (j.get('pageCount') or 1):
                break
    except Exception as e:
        logger.warning(f"[props/{clave}/{event_id}] {type(e).__name__}: {e}")
    logger.info(f"[props/{clave}] {len(salida)} props con cuota real.")
    _CACHE[ck] = (ahora, salida)
    return salida


def odds_multi(clave: str, event_ids: List[str]) -> Dict[str, Dict]:
    """v65: cuotas por evento de MUCHOS partidos EN PARALELO. El barrido diario
    necesita ~1 petición por partido; secuencial serían minutos, concurrente
    son segundos. Cada evento conserva su caché individual (15 min)."""
    from concurrent.futures import ThreadPoolExecutor
    ids = [e for e in event_ids if e]
    if not ids:
        return {}
    salida: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=min(10, len(ids))) as ex:
        futuros = {ex.submit(odds_evento, clave, eid): eid for eid in ids}
        for fut in futuros:
            eid = futuros[fut]
            try:
                salida[eid] = fut.result() or {}
            except Exception as e:
                logger.warning(f"[odds_multi/{clave}/{eid}] {type(e).__name__}: {e}")
                salida[eid] = {}
    return salida
