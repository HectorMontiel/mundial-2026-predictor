#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v192 — CINCO CASAS MEXICANAS POR UNA PUERTA ABIERTA.

DE DÓNDE SALE ESTO
------------------
El encargo era meter **Novibet**. Su propia API no se puede usar: devuelve 403
desde cualquier IP —hasta `robots.txt`— porque está detrás del desafío de
Cloudflare, y resolver una protección anti-bot no es algo que este proyecto
vaya a hacer. La v114 ya lo había sondeado y medido lo mismo.

Pero las cuotas de Novibet **sí están publicadas** en el comparador de
Flashscore, que responde 200 a una petición normal, sin navegador y sin
resolver nada. Es la misma categoría que el scraping de BetExplorer que el
proyecto ya hacía.

Y por esa puerta no entra una casa: entran **cinco, todas mexicanas**, que es
lo que de verdad importa —de nada sirve detectar valor en un precio que el
usuario no puede tomar—:

    Calientemx 631 · 1xBet 417 · Winpot 1113 · Novibet 632 · Sportium.mx 1041

El proyecto tenía tres casas (Pinnacle, Bovada, Playdoit). La dispersión entre
casas es la única señal que este proyecto mide como positiva, y con tres apenas
se ve.

COBERTURA MEDIDA (12 partidos por deporte, 1.040 peticiones, 2026-09-10)
-----------------------------------------------------------------------
                  Caliente  1xBet  Winpot  Novibet  Sportium
    futbol          10/12   10/12   10/12   10/12     9/12
    tenis           11/12   12/12   12/12   12/12    11/12
    baloncesto       4/12    9/12    4/12   10/12     0/12
    americano        3/4     0/4     0/4     0/4      3/4
    beisbol          1/12   11/12    0/12    0/12    11/12

Novibet es fuerte en fútbol, tenis y baloncesto —ahí es la mejor de las cinco—
y **no cotiza NFL ni MLB**. Esos los cubren Caliente, 1xBet y Sportium. Juntas
llegan a los cinco deportes.

POR QUÉ ESTO NO VA EN EL CAMINO CALIENTE
-----------------------------------------
Cada consulta cuesta 0,19 s y no hay límite de ritmo, pero un barrido completo
son ~4.500 peticiones: **catorce minutos**. Meterlo en el barrido que corre al
abrir la pantalla desharía la v178, que bajó la carga de 213 s a 39 s quitando
exactamente este tipo de petición de ahí.

Y no es una hipótesis: en esta misma tanda metí el tablero de Playdoit para los
16 partidos de la NFL, midió **+14,2 s por barrido** y dejó el smoke colgado 33
minutos. Se aprendió por las malas dos veces; no hace falta una tercera.

Así que `barrer()` corre en un trabajo de fondo y deja un fichero; la pantalla
sólo lo lee.
"""
import io
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

logger = logging.getLogger('cuotas_mx')

FEED = 'https://global.flashscore.ninja/2/x/feed/f_%d_%d_3_es-mx_1'
ODDS = 'https://global.ds.lsapp.eu/odds/pq_graphql'
CABEZ = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
         'Referer': 'https://www.flashscore.com.mx/',
         'x-fsign': 'SW9D1eZo'}

CASAS = {'Calientemx': 631, '1xBet': 417, 'Winpot': 1113,
         'Novibet': 632, 'Sportium.mx': 1041}

# el `sportId` de Flashscore -> la clave de deporte de este proyecto
DEPORTES = {1: 'futbol', 2: 'tenis', 3: 'nba', 5: 'nfl', 6: 'mlb'}

# Qué mercado pedir a cada deporte, y CON QUÉ ALCANCE. Pedir los cuatro
# mercados a todos los deportes multiplicaría por dos las peticiones para traer
# vacíos: el fútbol no tiene HOME_AWAY y el tenis no tiene empate.
#
# v195 — EL BÉISBOL PEDÍA UN MERCADO QUE NO EXISTE, Y POR ESO NO TRAÍA NADA.
#
# El alcance iba fijo a `FULL_TIME` para los cinco deportes. En los deportes
# que pueden ir a tiempo extra, Flashscore llama `FULL_TIME` al resultado de la
# parte reglamentaria y `FULL_TIME_OVER_TIME` al del partido completo — que es
# el que cotizan las casas. El servicio no da error: responde 200 con `null`.
#
# Medido el 2026-09-12 sobre 25 partidos programados por deporte, las cinco
# casas y los cuatro mercados; partidos con precio de GANADOR:
#
#     deporte   FULL_TIME   FULL_TIME_OVER_TIME
#     mlb            0/25            10/25
#     nba            6/25             8/25
#     nfl           11/25            13/25
#     futbol        14/25             0/25
#     tenis         25/25             0/25
#
# O sea: la MLB entera de las cinco casas mexicanas llevaba desde la v192 sin
# entrar en el consenso. Cero partidos, no pocos. El barrido lo decía en el log
# —«[mx] mlb 139 partidos, 0 con cuota»— junto a los otros cuatro deportes, que
# sí traían, y ahí se quedó.
#
# Y LOS SEIS QUE SÍ TRAÍA LA NBA NO ERAN EL GANADOR. Eran el 1X2 de la parte
# reglamentaria, con su empate, y el lector de `cuotas_multi` prefiere
# `HOME_DRAW_AWAY` cuando está — así que la NFL y la NBA comparaban un precio
# de tres vías contra el de dos vías de Pinnacle. Y el de tres vías es MÁS
# LARGO, porque el empate se lleva probabilidad. Medido en la misma pasada:
#
#     Toronto   3 vías 1.24 / 26.0 / 4.00      ganador 1.15 / 5.50
#     Michigan  3 vías 2.85 / 18.0 / 1.45      ganador 2.75 / 1.41
#
# Leído como ganador, ese 1.24 finge pagar un 8 % más de lo que paga. No era
# que faltaran picks: era que los de NFL y NBA salían con EV inflado.
#
# Por eso el alcance se decide por (deporte, mercado) y no por deporte, y cada
# combinación que aquí aparece está medida arriba. Las que dieron cero no
# están: pedirlas es gastar una petición para recibir `null`.
MERCADOS = {
    'futbol': (('HOME_DRAW_AWAY', 'FULL_TIME'),
               ('OVER_UNDER', 'FULL_TIME'),
               ('ASIAN_HANDICAP', 'FULL_TIME')),
    'tenis': (('HOME_AWAY', 'FULL_TIME'),
              ('OVER_UNDER', 'FULL_TIME'),
              ('ASIAN_HANDICAP', 'FULL_TIME')),
    'nba': (('HOME_AWAY', 'FULL_TIME_OVER_TIME'),
            ('OVER_UNDER', 'FULL_TIME_OVER_TIME'),
            ('ASIAN_HANDICAP', 'FULL_TIME_OVER_TIME')),
    'nfl': (('HOME_AWAY', 'FULL_TIME_OVER_TIME'),
            ('OVER_UNDER', 'FULL_TIME_OVER_TIME'),
            ('ASIAN_HANDICAP', 'FULL_TIME_OVER_TIME')),
    'mlb': (('HOME_AWAY', 'FULL_TIME_OVER_TIME'),
            ('OVER_UNDER', 'FULL_TIME_OVER_TIME'),
            ('ASIAN_HANDICAP', 'FULL_TIME_OVER_TIME')),
}

# El alcance por defecto, para un deporte que no esté en la tabla.
ALCANCE_POR_DEFECTO = 'FULL_TIME'

FICHERO = 'cuotas_mx.json'
TIMEOUT = 20
PAUSA = 0.02
# Un fichero de más de este tiempo no se usa: son precios, y un precio de
# ayer no es un precio.
TTL_HORAS = 8


# ---------------------------------------------------------------------------
# el calendario
# ---------------------------------------------------------------------------
# Estado del partido en el feed de Flashscore (campo `AC`). El 1 es
# «programado»; el resto son en juego, terminado, aplazado o cancelado.
PROGRAMADO = '1'


def eventos(sport_id: int, dias: int = 3, sesion=None,
            solo_programados: bool = True) -> List[Dict]:
    """Los partidos que Flashscore publica para un deporte, con su id.

    v195 — SOLO LOS QUE NO HAN EMPEZADO.

    El feed del día de hoy trae también los de ayer por la noche, ya jugados
    (17 de 69 en béisbol el 2026-09-12). Un partido terminado no tiene precio
    de prepartido, así que pedir sus cuotas es gastar peticiones para recibir
    `null` — y, peor, deja en el fichero un cruce repetido que `buscar` puede
    confundir con el de hoy. Ver el porqué en `buscar`.
    """
    import requests
    ses = sesion or requests.Session()
    ses.headers.update(CABEZ)
    salida, vistos = [], set()
    descartados = 0
    for d in range(dias):
        try:
            t = ses.get(FEED % (sport_id, d), timeout=TIMEOUT).text
        except Exception as e:
            logger.debug('[mx] feed %s/%s: %s', sport_id, d, e)
            continue
        liga = ''
        for trozo in re.split(r'~ZA÷', t):
            cab = trozo.split('¬')[0]
            if cab and '÷' not in cab:
                liga = cab[:80]
            for x in trozo.split('~AA÷')[1:]:
                eid = x[:8]
                if eid in vistos:
                    continue
                campos = dict(re.findall(r'([A-Z]{2})÷([^¬]*)', '¬' + x))
                h, a = campos.get('AE'), campos.get('AF')
                if not h or not a:
                    continue
                if solo_programados and campos.get('AC') != PROGRAMADO:
                    descartados += 1
                    continue
                vistos.add(eid)
                salida.append({'id': eid, 'home': h, 'away': a, 'liga': liga,
                               'inicio': campos.get('AD')})
    # Si el filtro se lo lleva TODO es que el campo cambió de significado, y
    # entonces el filtro es el error. Se avisa y se devuelve sin filtrar: es
    # preferible un fichero con ruido a uno vacío.
    if solo_programados and descartados and not salida:
        logger.warning('[mx] deporte %s: el filtro de estado descartó los %d '
                       'partidos. Se devuelve sin filtrar.',
                       sport_id, descartados)
        return eventos(sport_id, dias=dias, sesion=ses,
                       solo_programados=False)
    if descartados:
        logger.debug('[mx] deporte %s: %d partidos no programados fuera',
                     sport_id, descartados)
    return salida


# ---------------------------------------------------------------------------
# las cuotas
# ---------------------------------------------------------------------------
def _valor(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if 1.001 <= v <= 1000.0 else None


def cuotas_evento(evento_id: str, casa_id: int, mercado: str,
                  sesion=None, alcance: str = ALCANCE_POR_DEFECTO
                  ) -> Optional[Dict]:
    """Las cuotas de UNA casa para UN partido en UN mercado, o None.

    `alcance` es el `betScope` de Flashscore y NO es un detalle: en los
    deportes con tiempo extra, `FULL_TIME` es la parte reglamentaria y
    `FULL_TIME_OVER_TIME` el partido entero. Ver la tabla `MERCADOS`.
    """
    import requests
    ses = sesion or requests.Session()
    ses.headers.update(CABEZ)
    try:
        r = ses.get(ODDS, params={'_hash': 'ope2', 'eventId': evento_id,
                                  'bookmakerId': casa_id, 'betType': mercado,
                                  'betScope': alcance},
                    timeout=TIMEOUT).json()
    except Exception as e:
        logger.debug('[mx] %s/%s/%s/%s: %s', evento_id, casa_id, mercado,
                     alcance, e)
        return None
    d = (r.get('data') or {}).get('findPrematchOddsForBookmaker')
    if not isinstance(d, dict):
        return None

    salida = {'mercado': mercado}
    # 1X2 y ganador: home / draw / away
    for lado in ('home', 'draw', 'away'):
        it = d.get(lado)
        if isinstance(it, dict):
            v = _valor(it.get('value'))
            if v is not None:
                salida[lado] = v
                # LA APERTURA TAMBIEN, y no es un adorno: la diferencia entre
                # el precio de apertura y el actual es movimiento de linea, que
                # es de lo que se alimenta el CLV — la metrica rey del
                # proyecto. Ninguna de las otras tres casas la publica.
                ap = _valor(it.get('opening'))
                if ap is not None:
                    salida.setdefault('apertura', {})[lado] = ap
    # totales y hándicap: over / under con su línea
    for lado, clave in (('over', 'over'), ('under', 'under')):
        it = d.get(clave)
        if isinstance(it, dict):
            v = _valor(it.get('value'))
            if v is not None:
                salida[lado] = v
    for k in ('total', 'handicap', 'value'):
        if isinstance(d.get(k), (int, float, str)):
            try:
                salida['linea'] = float(d[k])
                break
            except (TypeError, ValueError):
                pass
    return salida if len(salida) > 1 else None


# ---------------------------------------------------------------------------
# el barrido de fondo
# ---------------------------------------------------------------------------
def barrer(dias: int = 3, max_por_deporte: int = 120,
           deportes: Optional[List[int]] = None) -> Dict:
    """
    Recorre los deportes y deja las cuotas en `cuotas_mx.json`.

    NO se llama desde la pantalla. Va en el workflow, como el resto de lo que
    cuesta segundos.
    """
    import requests
    ses = requests.Session()
    ses.headers.update(CABEZ)

    doc = {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'casas': CASAS, 'partidos': {}}
    t0 = time.time()
    n_pet = 0
    for sid in (deportes or list(DEPORTES)):
        dep = DEPORTES.get(sid)
        if not dep:
            continue
        evs = eventos(sid, dias=dias, sesion=ses)[:max_por_deporte]
        con = 0

        # EN PARALELO, porque en serie no escala. Medido en serie: 1.830
        # peticiones en 381 s para 104 partidos, o sea 3,7 s por partido. Un
        # barrido de verdad son ~500 partidos: media hora. Con hilos baja a
        # minutos y sigue sin ser el camino caliente.
        #
        # Ocho hilos y no mas: esto es cortesia, no una carrera. La medicion
        # dio 0,19 s por peticion sin ningun limite de ritmo, y no hace falta
        # averiguar donde esta el limite para que nos lo pongan.
        def _de_un_partido(ev):
            fila = {}
            hilo = requests.Session()
            hilo.headers.update(CABEZ)
            pedidas = 0
            for casa, bid in CASAS.items():
                por_mercado = {}
                for mk, alc in MERCADOS.get(
                        dep, (('HOME_DRAW_AWAY', ALCANCE_POR_DEFECTO),)):
                    c = cuotas_evento(ev['id'], bid, mk, sesion=hilo,
                                      alcance=alc)
                    pedidas += 1
                    if c:
                        # La clave sigue siendo el mercado a secas: cada
                        # (deporte, mercado) tiene UN alcance, así que no
                        # chocan, y `cuotas_multi` sigue leyendo lo mismo.
                        por_mercado[mk] = c
                if por_mercado:
                    fila[casa] = por_mercado
            return ev, fila, pedidas

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            for ev, fila, pedidas in pool.map(_de_un_partido, evs):
                n_pet += pedidas
                if fila:
                    con += 1
                    doc['partidos'][ev['id']] = {
                        'deporte': dep, 'home': ev['home'], 'away': ev['away'],
                        'liga': ev['liga'], 'inicio': ev['inicio'],
                        'casas': fila}
        logger.info('[mx] %-10s %d partidos, %d con cuota', dep, len(evs), con)

    doc['segundos'] = round(time.time() - t0, 1)
    doc['peticiones'] = n_pet
    tmp = FICHERO + '.nuevo'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, FICHERO)
    return doc


# ---------------------------------------------------------------------------
# la lectura, que es lo que usa la pantalla
# ---------------------------------------------------------------------------
_MEM: Dict = {}


def cargar() -> Dict:
    """El fichero, o `{}` si no está o es viejo. Nunca lanza."""
    try:
        if not os.path.exists(FICHERO):
            return {}
        edad = (time.time() - os.path.getmtime(FICHERO)) / 3600.0
        if edad > TTL_HORAS:
            logger.info('[mx] %s tiene %.1f h: no se usa', FICHERO, edad)
            return {}
        marca = os.path.getmtime(FICHERO)
        if _MEM.get('marca') != marca:
            with io.open(FICHERO, encoding='utf-8') as f:
                _MEM['doc'] = json.load(f)
            _MEM['marca'] = marca
        return _MEM.get('doc') or {}
    except Exception as e:
        logger.debug('[mx] no se pudo leer %s: %s', FICHERO, e)
        return {}


def _momento(x) -> Optional[float]:
    """El `inicio` de Flashscore (epoch en segundos) o una fecha, en epoch."""
    if x is None or x == '':
        return None
    try:
        return float(int(str(x).strip()))
    except (TypeError, ValueError):
        pass
    try:
        import pandas as pd
        t = pd.Timestamp(x)
        if pd.isna(t):
            return None
        t = t.tz_convert(None) if t.tzinfo else t
        return float(t.timestamp())
    except Exception:
        return None


# Cuánto puede separarse el partido que pide quien llama del candidato del
# fichero. Doce horas: cubre husos y retrasos, y NO cubre el partido del día
# siguiente de la misma serie, que es justo lo que hay que separar.
TOLERANCIA_HORAS = 12.0


def buscar(deporte: str, home: str, away: str, fecha=None) -> Dict:
    """
    Las cuotas de las cinco casas para un partido, o `{}`.

    El emparejamiento va por nombre dentro del MISMO deporte, con
    `name_mapper`, que es para lo que está: Flashscore escribe «UNAM Pumas» y
    el catálogo puede decir otra cosa. Fuera del deporte no se busca — ésa es
    la lección de la v180: un catálogo de todo empareja cualquier cosa.

    v195 — Y DENTRO DEL DEPORTE, TAMPOCO BASTA EL NOMBRE.

    Esto emparejaba sólo por los dos nombres y devolvía el primer candidato.
    En fútbol pasa desapercibido porque dos equipos no se cruzan dos veces en
    dos días; **en béisbol es la norma**, que se juega en series diarias contra
    el mismo rival. Medido el 2026-09-12, con el fichero de dos días: los 14
    partidos de MLB del día tenían un gemelo —el juego de la víspera, ya
    terminado— y `buscar` devolvía SIEMPRE el de ayer.

    Lo que salía de ahí no era «sin cuota», que sería honesto: era el precio
    de cierre de otro partido comparado contra el de Pinnacle de éste. Los
    números que producía parecían oportunidades enormes:

        Mets @ Yankees   Pinnacle 1,55 / 2,63   las cinco casas 1,77 / 2,10
        Angels @ Nats    Pinnacle 1,90 / 2,01   las cinco casas 1,62 / 2,35

    Esa segunda columna es del juego del día anterior. Leída como si fuera de
    hoy daba picks de +19 % de EV en un moneyline de dos vías, que es la firma
    clásica de un emparejado equivocado y no de valor.

    Es EXACTAMENTE la lección de la v114 —«un partido del mismo cruce cinco
    días después, con las cuotas de otro partido»— que `_buscar` ya aprendió
    para las demás casas y que esta puerta, abierta en la v192, no heredó.

    Así que si quien llama sabe cuándo se juega, se exige que el candidato
    caiga dentro de `TOLERANCIA_HORAS` y gana el más cercano. Si no lo sabe, se
    toma el PRÓXIMO que aún no ha empezado: un precio de un partido terminado
    no es un precio.
    """
    doc = cargar()
    if not doc:
        return {}
    # EL INDICE SE CONSTRUYE UNA VEZ POR DEPORTE, NO EN CADA LLAMADA.
    #
    # Rehacerlo por partido costaba 0,034 s, que por los 260 partidos de
    # futbol de un barrido son **8,8 s** tirados en reconstruir la misma lista
    # de 1.900 nombres una y otra vez. Medido.
    #
    # Se ata a la marca de tiempo del fichero: cuando el barrido de fondo
    # escribe uno nuevo, el indice se rehace solo.
    # v195 — UNA RANURA PARA CINCO DEPORTES ES CERO RANURAS.
    #
    # El índice se guardaba en `_MEM['idx']`, una sola, con la clave del
    # deporte al lado para saber de quién era. Y las cinco ramas del barrido
    # corren EN PARALELO desde la v79: fútbol pedía lo suyo, tenis lo pisaba,
    # béisbol lo volvía a pisar. Medido el 2026-09-12 contando las
    # reconstrucciones en un barrido real: **69 para 742 consultas**, cuando
    # deberían ser cinco, una por deporte.
    #
    # Es el mismo gasto que este bloque se puso a evitar —el comentario de
    # abajo cuenta los 8,8 s que costaba rehacerlo por partido— sólo que
    # repartido en 69 veces en vez de 260. Se guarda uno por deporte y se
    # acabó.
    _cache = _MEM.setdefault('por_deporte', {})
    clave_idx = ('idx', deporte, _MEM.get('marca'))
    entrada = _cache.get(deporte)
    if not entrada or entrada.get('clave_idx') != clave_idx:
        _idx = {}
        for k, v in (doc.get('partidos') or {}).items():
            if v.get('deporte') != deporte:
                continue
            _idx.setdefault(v.get('home', ''), []).append((k, v))
            _idx.setdefault(v.get('away', ''), []).append((k, v))
        entrada = {'clave_idx': clave_idx, 'idx': _idx,
                   'catalogo': [x for x in _idx if x]}
        # Y un indice por nombre NORMALIZADO. El emparejado difuso contra
        # 1.900 nombres cuesta 0,034 s por busqueda —8,7 s en un barrido de
        # futbol— y casi todas se resuelven antes: «UNAM Pumas» y «Pumas UNAM»
        # normalizan igual. Lo difuso queda para lo que de verdad no casa.
        _norm = {}
        try:
            import name_mapper as _nm
            for x in entrada['catalogo']:
                _norm.setdefault(_nm.normalizar(x), x)
        except Exception:
            _norm = {}
        entrada['norm'] = _norm
        # Y un indice por PALABRA. El emparejado difuso contra los 1.900
        # nombres del catalogo costaba 22,7 s en un barrido completo (medido:
        # 114,8 s con las casas mexicanas contra 92,1 s sin ellas). Casi todo
        # ese tiempo se va comparando «Pumas» con equipos de Kazajistan.
        #
        # Con este indice, lo difuso solo se prueba contra los que comparten
        # al menos una palabra: de 1.900 candidatos a una veintena.
        _pal = {}
        try:
            import name_mapper as _nm2
            for x in entrada['catalogo']:
                for p in _nm2.normalizar(x).split():
                    if len(p) >= 3:
                        _pal.setdefault(p, []).append(x)
        except Exception:
            _pal = {}
        entrada['palabras'] = _pal
        # Y, en tenis, un indice por APELLIDO DE TENISTA.
        #
        # v195.2 — AQUI SE PERDIAN LAS CUOTAS DE NOVIBET.
        #
        # Todo lo de arriba empareja CLUBES: normaliza, quita sufijos
        # societarios y compara palabras. Con tenistas no funciona, porque las
        # fuentes usan formatos distintos del mismo nombre: Flashscore publica
        # «Kinoshita H.» y el tablon de Pinnacle «Hayu Kinoshita». Normalizados
        # son «kinoshita h» y «hayu kinoshita»: ni iguales, ni uno dentro del
        # otro, ni al 0,80 de similitud que se exige aqui.
        #
        # Resultado medido el 2026-09-12: de las 18 filas que se quedaban sin
        # precio, **16 eran de tenis, y el fichero tenia la cuota de Novibet
        # para ellas**. No faltaba la fuente: fallaba el cruce.
        #
        #     la app busca   «Hayu Kinoshita vs Victoria Rodriguez»
        #     el fichero dice «Kinoshita H. vs Rodriguez V.»  Novibet 1,57
        #
        # `cuotas_multi._clave_tenista` existe desde la v72 justo para esto y
        # `_buscar` ya la usa con las demas casas. Esta puerta, abierta en la
        # v192, volvio a emparejar por club.
        _ten = {}
        if deporte == 'tenis':
            try:
                from cuotas_multi import _clave_tenista as _ct
                for x in entrada['catalogo']:
                    ap = _ct(x)[0]
                    if ap:
                        _ten.setdefault(ap, []).append(x)
            except Exception:
                _ten = {}
        entrada['tenistas'] = _ten
        _cache[deporte] = entrada
    nombres = entrada.get('idx') or {}
    catalogo = entrada.get('catalogo') or []
    if not catalogo:
        return {}
    candidatos = [(k, v) for k, v in (doc.get('partidos') or {}).items()
                  if v.get('deporte') == deporte]
    try:
        import name_mapper
    except Exception:
        name_mapper = None

    def _mapea_tenista(n):
        """El nombre del fichero que corresponde a este tenista, o None.

        Mismo criterio que `cuotas_multi._buscar`: apellido + inicial, con
        `_sim_tenista`, que ya devuelve 0 cuando la inicial no coincide (mismo
        apellido, jugador distinto). Solo se compara contra los que comparten
        apellido, no contra el fichero entero.
        """
        try:
            from cuotas_multi import _clave_tenista as _ct, _sim_tenista as _st
        except Exception:
            return None
        ap = _ct(n)[0]
        if not ap:
            return None
        idx_t = entrada.get('tenistas') or {}
        corto = list(idx_t.get(ap, ()))
        if not corto:
            # apellido escrito distinto: se prueba con los que arrancan igual
            for k, xs in idx_t.items():
                if k[:3] == ap[:3] or k[-3:] == ap[-3:]:
                    corto.extend(xs)
        mejor, score = None, 0.0
        for x in corto:
            s = _st(n, x)
            if s > score:
                mejor, score = x, s
        return mejor if score >= 0.85 else None

    def _mapea(n):
        if not n:
            return None
        if n in nombres:
            return n
        if deporte == 'tenis':
            x = _mapea_tenista(n)
            if x:
                return x
        if name_mapper is not None:
            try:
                x = (entrada.get('norm') or {}).get(name_mapper.normalizar(n))
                if x:
                    return x
            except Exception:
                pass
        if name_mapper is None:
            return None
        try:
            corto = []
            vistos = set()
            for p in name_mapper.normalizar(n).split():
                if len(p) < 3:
                    continue
                for x in (entrada.get('palabras') or {}).get(p, ()):
                    if x not in vistos:
                        vistos.add(x)
                        corto.append(x)
            if not corto:
                return None
            return name_mapper.mapear(n, corto, umbral=0.80,
                                      contexto='cuotas_mx→%s' % deporte)
        except Exception:
            return None

    mh, ma = _mapea(home), _mapea(away)
    if not (mh and ma):
        return {}

    # TODOS los que casan por nombre, no el primero. Ver el docstring: en
    # béisbol el mismo cruce sale tres o cuatro días seguidos.
    posibles = []
    for k, v in candidatos:
        if v.get('home') == mh and v.get('away') == ma:
            posibles.append((v, False))
        elif v.get('home') == ma and v.get('away') == mh:
            # el partido está al revés; se marca para que quien llame no
            # confunda local con visitante
            posibles.append((v, True))
    if not posibles:
        return {}
    if len(posibles) == 1 and fecha is None:
        v, inv = posibles[0]
        return {**v, 'invertido': True} if inv else v

    pedido = _momento(fecha)
    ahora = time.time()
    mejor, mejor_coste = None, None
    for v, inv in posibles:
        ini = _momento(v.get('inicio'))
        if pedido is not None:
            if ini is None:
                # sin hora no se puede desempatar; sólo vale si es el único
                coste = TOLERANCIA_HORAS * 3600.0
            else:
                coste = abs(ini - pedido)
                if coste > TOLERANCIA_HORAS * 3600.0:
                    continue
        else:
            # sin fecha del llamador: el PRÓXIMO que no haya empezado.
            if ini is None or ini < ahora:
                continue
            coste = ini - ahora
        if mejor_coste is None or coste < mejor_coste:
            mejor, mejor_coste = (v, inv), coste
    if mejor is None:
        if len(posibles) > 1:
            logger.debug('[mx] %s %s vs %s: %d candidatos y ninguno encaja en '
                         'la fecha; se deja sin cuota',
                         deporte, home, away, len(posibles))
        return {}
    v, inv = mejor
    return {**v, 'invertido': True} if inv else v


def main() -> int:
    import argparse
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dias', type=int, default=3)
    ap.add_argument('--max', type=int, default=120)
    a = ap.parse_args()

    d = barrer(dias=a.dias, max_por_deporte=a.max)
    print()
    print('partidos con cuota: %d' % len(d.get('partidos') or {}))
    print('peticiones: %d en %.1f s' % (d.get('peticiones', 0),
                                        d.get('segundos', 0)))
    por_casa = {}
    for v in (d.get('partidos') or {}).values():
        for casa in (v.get('casas') or {}):
            por_casa[casa] = por_casa.get(casa, 0) + 1
    for casa, n in sorted(por_casa.items(), key=lambda x: -x[1]):
        print('   %-14s %d partidos' % (casa, n))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
