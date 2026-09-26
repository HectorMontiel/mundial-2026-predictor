#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v176 — LO QUE LA APLICACIÓN DIJO ANTES DEL PITIDO, GUARDADO Y LIQUIDADO.

Qué resuelve
------------
La tarjeta de un partido acabado enseñaba el 1X2 y los goles reconstruidos de
la matriz de marcador, y nada más. No se podía ver **la apuesta que la
aplicación había recomendado** ni si acertó. El usuario lo pidió con estas
palabras: «mostrar el pronóstico previo en partidos finalizados, con colores de
validación».

POR QUÉ NO VA EN `predicciones_dia.json`, QUE ES DONDE SE PIDIÓ
----------------------------------------------------------------
Ese fichero **lo regenera el bot entero cada noche** (`predicciones_dia.generar`
escribe el JSON completo, no lo actualiza). Guardar ahí una copia que se
describe como *inmutable* sería garantizar que se borra en la primera pasada
del bot — exactamente lo contrario de lo que el encargo quiere. Y hay una
segunda razón, de fondo: `predicciones_dia.json` sólo lleva probabilidades del
modelo, a propósito («no es una fuente de precios», dice su cabecera), y una
recomendación lleva la CUOTA a la que se habría jugado. Mezclarlas convertiría
un fichero determinista en uno que depende de a qué hora se miró el tablero.

Así que esto es un fichero aparte, con dos propiedades que lo definen:

  · **SE AÑADE, NO SE REESCRIBE.** Un partido que ya tiene pronóstico guardado
    no se vuelve a tocar. Es lo que hace que sea un pronóstico y no una
    reconstrucción posterior: si se sobrescribiera con la recomendación de esta
    tarde, lo que se enseñaría después del partido sería lo que la aplicación
    pensaba al final, no lo que dijo al principio.
  · **NO CADUCA CON EL DÍA.** Se conservan `DIAS_MEMORIA` días para poder mirar
    hacia atrás sin que el fichero crezca sin límite.

DE DÓNDE SALE EL RESULTADO REAL, Y POR QUÉ NO SE PIDE A LA RED
---------------------------------------------------------------
Los goles vienen del propio partido jugado. Córners, tarjetas y remates salen
de `stats_espn.leer(liga)`, que es la **caché en disco** que el backfill
nocturno ya mantiene — el mismo fichero del que se alimentan los modelos de
conteo. Pedirlos en vivo desde la tarjeta sería repetir el error que este
proyecto tiene anotado tres veces («no pedir red desde la tarjeta»).

Consecuencia honesta: un partido que acaba de terminar todavía no tiene su
boxscore en la caché, así que sus mercados de conteo salen **⏳ Pendiente** en
vez de con un veredicto inventado. Un hueco se ve; un veredicto falso, no.
"""
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger('pronosticos_guardados')

FICHERO = os.environ.get('PRONOSTICOS_EMITIDOS', 'pronosticos_emitidos.json')
DIAS_MEMORIA = 21          # lo que se conserva hacia atrás
MAX_RECOMENDADAS = 3       # la principal y sus dos alternativas

# Los tres estados de la validación, con el criterio que los separa.
#
# El «cerca» tiene DOS puertas y las dos vienen del encargo literal: «si el lado
# fue correcto pero la probabilidad era baja (<50 %), o si estuvo a 1 unidad de
# la línea». La segunda es la que importa de verdad — un «Menos de 2,5
# tarjetas» que termina en 3 falló, sí, pero falló por medio punto y leerlo en
# el mismo rojo que un 9 sería perder la única información que distingue un
# modelo que va afinado de uno que va perdido.
CUMPLIDO = 'cumplido'
CERCA = 'cerca'
FALLADO = 'fallado'
PENDIENTE = 'pendiente'
# v309 — un hándicap asiático que acaba JUSTO en la línea no se gana ni se
# pierde: la casa devuelve. Pintarlo ⏳ diría «todavía no se sabe», y sí se
# sabe.
NULA = 'nula'
ICONO = {CUMPLIDO: '\U0001f7e2', CERCA: '\U0001f7e1', FALLADO: '\U0001f534',
         PENDIENTE: '⏳', NULA: '⚪'}
ROTULO = {CUMPLIDO: 'Cumplido', CERCA: 'Cerca', FALLADO: 'No cumplido',
          PENDIENTE: 'Pendiente', NULA: 'Nula (se devuelve)'}
MARGEN_CERCA = 1.0         # «a una unidad de la línea»
PROB_FLOJA = 0.50          # acertar por debajo de aquí es acertar de suerte

_RE_LINEA = re.compile(r'(m[aá]s|menos)\s+de\s+([0-9]+(?:[.,][0-9]+)?)', re.I)

_CACHE: Optional[Dict] = None


# ---------------------------------------------------------------------------
# el fichero
# ---------------------------------------------------------------------------
def clave(clave_liga, home: str, away: str, fecha: str) -> str:
    """La clave de un partido. Los nombres van tal cual llegan, como en el resto."""
    return '%s|%s|%s|%s' % (str(clave_liga or ''), str(fecha or '')[:10],
                            str(home or '').strip(), str(away or '').strip())


def _leer() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    doc = {}
    try:
        import io_atomico
        doc = io_atomico.leer_json(FICHERO, {}) or {}
    except Exception as e:
        logger.debug('[pronosticos] no se pudo leer %s: %s', FICHERO, e)
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    _CACHE = doc
    return doc


def _escribir(doc: Dict) -> bool:
    global _CACHE
    _CACHE = doc
    try:
        import io_atomico
        # SIN indentar, como sus hermanos `mercado_dia.json` y
        # `predicciones_dia.json`: es un fichero de datos que se
        # regenera a diario y viaja en el repositorio. Con `indent=1`
        # un solo dia ocupaba 12.000 lineas y la poda de 21 dias lo
        # habria dejado en un cuarto de millon.
        return bool(io_atomico.escribir_json(FICHERO, doc))
    except Exception as e:
        logger.debug('[pronosticos] no se pudo escribir %s: %s', FICHERO, e)
        return False


# v216 — ESCRIBIR UNA VEZ, NO UNA POR PRONÓSTICO.
#
# `_leer` está cacheado; `_escribir` no. Así que `guardar` volcaba el
# diccionario ENTERO a disco en cada llamada: con 1.737 registros y 157
# pronósticos nuevos en una pasada, eso son 157 escrituras completas del mismo
# fichero. Medido en el perfil de «Apuestas del Día»: **94,8 s de los 206**,
# más que pintar las doscientas tarjetas.
#
# El modo diferido acumula en la caché y escribe una sola vez al salir. Se usa
# con el gestor de contexto `lote()`, que garantiza el volcado aunque el cuerpo
# lance — si se dejara al llamador, el primer `except` del camino se llevaría
# los pronósticos del día sin que nadie se enterara.
_DIFERIDO = False
_PENDIENTE = False


class lote:
    """Agrupa varios `guardar` en una sola escritura.

        with pronosticos_guardados.lote():
            for p in partidos:
                guardar(p, recomendadas(p))

    Reentrante: si ya hay un lote abierto, el interior no cierra el de fuera.
    """

    def __init__(self):
        self._era = False

    def __enter__(self):
        global _DIFERIDO
        self._era = _DIFERIDO
        _DIFERIDO = True
        return self

    def __exit__(self, *exc):
        global _DIFERIDO
        _DIFERIDO = self._era
        if not _DIFERIDO:
            volcar()
        return False            # no se traga la excepción


def volcar() -> bool:
    """Escribe lo acumulado en modo diferido. Idempotente."""
    global _PENDIENTE
    if not _PENDIENTE:
        return False
    _PENDIENTE = False
    doc = _leer()
    try:
        import io_atomico
        return bool(io_atomico.escribir_json(FICHERO, _poda(dict(doc))))
    except Exception as e:
        logger.debug('[pronosticos] no se pudo volcar %s: %s', FICHERO, e)
        return False


def _hoy() -> str:
    """El día de hoy en UTC, o cadena vacía si pandas no está."""
    try:
        import pandas as pd
        return pd.Timestamp.now('UTC').strftime('%Y-%m-%d')
    except Exception:
        return ''


def _poda(doc: Dict) -> Dict:
    """
    Quita lo más viejo de `DIAS_MEMORIA` días. El fichero no crece sin fin.

    Se poda por `anotado` —el día en que se escribió la entrada— y no por
    `fecha`, y la diferencia importa: los registros que deja el bot vienen de
    `predicciones_dia.json`, **que no guarda la fecha del partido**. Podando
    por `fecha` esas entradas tendrían fecha vacía, se ordenarían como futuras
    y no se borrarían nunca; el fichero crecería sin tope hasta que alguien lo
    notara.
    """
    try:
        import pandas as pd
        corte = (pd.Timestamp.now('UTC').tz_localize(None)
                 - pd.Timedelta(days=DIAS_MEMORIA)).strftime('%Y-%m-%d')
    except Exception:
        return doc

    def _dia(v):
        v = v or {}
        return max(str(v.get('fecha') or '')[:10],
                   str(v.get('anotado') or '')[:10]) or '9999'
    # v249 — LO QUE YA SE RESOLVIO NO SE BORRA.
    #
    # «Si ya finalizaron no deberia borrar lo que ya habia marcado la app,
    # simplemente es para mantener el historico y validar, y que tu en segundo
    # plano puedas entrenarte y seguir patrones.»
    #
    # Tenia razon y el coste era grande: habia 1.591 partidos guardados, TODOS
    # sin resolver, y a los 21 dias se iban. Entre ellos 498 picks de corners
    # y 70 de tarjetas — que es exactamente por que no existe calibracion de
    # esos mercados y hubo que medirlos contra el historico de las ligas.
    #
    # Un registro RESUELTO ya no crece sin fin por si solo: es una fila con su
    # acierto, y es el unico material con el que el modelo puede aprender de
    # sus propios aciertos. Se conserva.
    def _resuelto(v):
        return any((r or {}).get('acierto') is not None
                   for r in ((v or {}).get('recomendadas') or []))

    return {k: v for k, v in doc.items()
            if _dia(v) >= corte or _resuelto(v)}


def _fila(f: Dict) -> Dict:
    """La copia que se guarda de una recomendación. Sólo lo que hay que liquidar."""
    return {'mercado': f.get('mercado'), 'bloque': f.get('bloque'),
            'etiqueta': f.get('etiqueta'), 'apuesta': f.get('apuesta'),
            'linea': f.get('linea'),
            'prob': (None if f.get('prob') is None
                     else round(float(f['prob']), 4)),
            'cuota': f.get('cuota'), 'score': f.get('score'),
            'semaforo': f.get('semaforo'),
            'incierto': bool(f.get('incierto')),
            # v310 — si la tarjeta dijo «meter» y con qué probabilidad
            'veredicto': f.get('veredicto_vp'),
            'prob_meter': (None if f.get('prob_meter') is None
                           else round(float(f['prob_meter']), 4))}


def ya_anotado(pick: Dict) -> bool:
    """¿Este partido ya tiene pronóstico guardado (o no puede tenerlo)?

    POR QUÉ EXISTE, Y ES UNA CUESTIÓN DE VELOCIDAD, NO DE LÓGICA.
    `guardar()` es de sólo-inserción: si la clave ya está, no toca nada y
    devuelve `False`. Pero para llegar a esa comprobación hay que haberle
    pasado ya las `recomendadas`, y calcularlas es lo caro — sale a predecir el
    partido entero. Resultado medido en el perfil de «Apuestas del Día»: en
    cada pasada se recalculaban las recomendaciones de TODOS los partidos ya
    anotados para tirarlas a la basura dentro de `guardar`.

    Esto es la misma pregunta hecha ANTES de pagar: mismas condiciones
    —partido jugado o clave ya presente— y ninguna más, para que no pueda
    decir que sí donde `guardar` diría que no.
    """
    if not pick:
        return True
    if pick.get('jugado'):
        return True               # de un partido acabado ya no se pronostica
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
    except Exception:
        return False              # ante la duda, que siga el camino de siempre
    if not (h and a):
        return True               # sin equipos, `guardar` tampoco escribiría
    k = clave(pick.get('clave_liga'), h, a, pick.get('fecha'))
    return k in _leer()


def guardar(pick: Dict, recomendadas: List[Dict]) -> bool:
    """
    Deja constancia de lo que se recomendó en este partido. UNA sola vez.

    Devuelve `True` si escribió algo. Si el partido ya tenía pronóstico, no
    toca nada y devuelve `False` — esa es la propiedad que hace del fichero un
    registro y no un espejo del estado actual.
    """
    if not (pick and recomendadas):
        return False
    if pick.get('jugado'):
        return False               # de un partido acabado ya no se pronostica
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
    except Exception:
        h = a = None
    if not (h and a):
        return False
    k = clave(pick.get('clave_liga'), h, a, pick.get('fecha'))
    doc = _leer()
    if k in doc:
        return False
    filas = [_fila(f) for f in recomendadas[:MAX_RECOMENDADAS] if f]
    if not filas:
        return False
    entrada = {'clave_liga': pick.get('clave_liga'), 'home': h, 'away': a,
               'partido': pick.get('partido'), 'liga': pick.get('liga'),
               'fecha': str(pick.get('fecha') or '')[:10],
               'inicio': pick.get('inicio'),
               'anotado': _hoy(),
               'recomendadas': filas}
    if _DIFERIDO:
        # En lote: se anota en la caché y el disco espera al `volcar()` del
        # gestor de contexto. La poda también se aplica allí, una sola vez.
        global _PENDIENTE
        doc[k] = entrada
        _PENDIENTE = True
        return True
    doc = dict(doc)
    doc[k] = entrada
    return _escribir(_poda(doc))


def de_partido(clave_liga, home: str, away: str,
               fecha: str = '') -> Optional[Dict]:
    """
    El pronóstico que se guardó de este partido, o `None`.

    POR QUÉ NO BASTA CON LA CLAVE EXACTA. Los dos que escriben aquí no
    saben lo mismo. La aplicación tiene la fecha del partido y la mete en
    la clave; el bot lo anota desde `predicciones_dia.json`, **cuyos
    registros no llevan fecha** —se indexan por liga y nombres crudos y
    nada más—. Exigir coincidencia exacta dejaría al bot escribiendo
    entradas que la tarjeta no encontraría nunca.

    Así que se busca primero la clave exacta y, si no está, el mismo par
    en la misma competición sin mirar la fecha. El riesgo de esa segunda
    pasada es confundir dos cruces del mismo par dentro de los
    `DIAS_MEMORIA` días —liga y copa en la misma quincena—, y se acota
    quedándose con el de fecha MÁS CERCANA a la que se pregunta.
    """
    doc = _leer()
    exacto = doc.get(clave(clave_liga, home, away, fecha))
    if exacto:
        return exacto
    liga = str(clave_liga or '')
    h, a = str(home or '').strip(), str(away or '').strip()
    f = str(fecha or '')[:10]
    candidatas = [v for v in doc.values()
                  if isinstance(v, dict)
                  and str(v.get('clave_liga') or '') == liga
                  and str(v.get('home') or '').strip() == h
                  and str(v.get('away') or '').strip() == a]
    if not candidatas:
        return None
    if not f:
        return candidatas[0]

    def _lejania(v):
        g = str(v.get('fecha') or '')[:10]
        if not g:
            return 10 ** 6          # sin fecha, la última opción
        try:
            import pandas as pd
            return abs((pd.Timestamp(g) - pd.Timestamp(f)).days)
        except Exception:
            return 10 ** 6
    return min(candidatas, key=_lejania)


def cuantos() -> int:
    """Cuántos partidos tienen pronóstico guardado. Para los tests y el estado."""
    return len(_leer())


def recargar() -> None:
    """Olvida la caché en memoria. Sólo lo usan los tests."""
    global _CACHE
    _CACHE = None


# ---------------------------------------------------------------------------
# el resultado real
# ---------------------------------------------------------------------------
def _linea_de(apuesta: str):
    """`(linea, es_mas)` de una apuesta con línea, o `None`."""
    m = _RE_LINEA.search(str(apuesta or ''))
    if not m:
        return None
    try:
        return (float(m.group(2).replace(',', '.')),
                m.group(1).lower().startswith('m') and
                not m.group(1).lower().startswith('men'))
    except ValueError:
        return None


def _stats_del_partido(clave_liga, home: str, away: str,
                       fecha: str) -> Optional[Dict]:
    """
    Córners, tarjetas y remates REALES de ese partido, de la caché en disco.

    `stats_espn.leer` es el fichero que el backfill nocturno mantiene y del que
    ya se alimentan los modelos de conteo. No se pide nada a la red: si la fila
    todavía no está, se devuelve `None` y el mercado sale ⏳ Pendiente.
    """
    try:
        import pandas as pd
        import stats_espn as se
        d = se.leer(str(clave_liga or ''))
        if d is None or getattr(d, 'empty', True):
            return _stats_fotmob(home, away, fecha)
        f = str(fecha or '')[:10]
        # el día se mira con un día de margen: ESPN publica en UTC y la lista
        # reparte en hora de CDMX, así que un partido de la tarde mexicana cae
        # en el día siguiente del fichero.
        try:
            dia = pd.Timestamp(f)
            dias = {f, (dia - pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                    (dia + pd.Timedelta(days=1)).strftime('%Y-%m-%d')}
        except Exception:
            dias = {f}
        m = d[d['fecha'].astype(str).str[:10].isin(dias)]
        if m.empty:
            return _stats_fotmob(home, away, fecha)
        h, a = str(home or '').strip(), str(away or '').strip()
        fila = m[(m['home'].astype(str) == h) & (m['away'].astype(str) == a)]
        if fila.empty:
            # v249 — LA CACHÉ DE ESPN ESCRIBE «Heart of Midlothian» Y EL PICK
            # «Hearts».
            #
            # La comparación era exacta, así que cualquier diferencia de
            # grafía dejaba el mercado en ⏳ Pendiente para siempre — y con él
            # los 498 picks de córners guardados, que son justo los que no
            # tienen calibración por falta de histórico resuelto.
            #
            # Se usa `cuotas_multi._sim_club`, el mismo emparejador de clubes
            # del resto del proyecto, con el mismo listón de 0,80 y exigiendo
            # que casen LOS DOS equipos. Desde la v247 ese emparejador ya no
            # cruza dos clubes de la misma ciudad.
            try:
                import cuotas_multi as _cm
                mejor, mejor_s = None, 0.0
                for _, r2 in m.iterrows():
                    s = min(_cm._sim_club(h, str(r2.get('home'))),
                            _cm._sim_club(a, str(r2.get('away'))))
                    if s > mejor_s:
                        mejor, mejor_s = r2, s
                if mejor is None or mejor_s < 0.80:
                    return _stats_fotmob(home, away, fecha)
                fila = None
                r = mejor
            except Exception as e:
                logger.debug('[pronosticos] parecido de %s-%s: %s', h, a, e)
                return None
        if fila is not None:
            r = fila.iloc[-1]

        def _n(col):
            try:
                v = float(r.get(col))
                return None if v != v else v
            except (TypeError, ValueError):
                return None
        return {
            'fuente': 'espn',
            'corners_home': _n('home_corners'), 'corners_away': _n('away_corners'),
            'tarjetas_home': _n('home_yellow'), 'tarjetas_away': _n('away_yellow'),
            'remates_on_home': _n('home_shots_on'),
            'remates_on_away': _n('away_shots_on'),
            'remates_home': (None if _n('home_shots_on') is None
                             or _n('home_shots_off') is None
                             else _n('home_shots_on') + _n('home_shots_off')),
            'remates_away': (None if _n('away_shots_on') is None
                             or _n('away_shots_off') is None
                             else _n('away_shots_on') + _n('away_shots_off')),
        }
    except Exception as e:
        logger.debug('[pronosticos] stats de %s-%s: %s', home, away, e)
        return None


def _stats_fotmob(home: str, away: str, fecha: str) -> Optional[Dict]:
    """
    v309 — CÓRNERS Y REMATES DE FOTMOB CUANDO ESPN NO LOS TIENE.

    Las selecciones y la femenil no están en la caché de `stats_espn`, así
    que una apuesta de córners o de remates de Italia-Bélgica se quedaba en
    ⏳ Pendiente para siempre. `remates_fotmob_equipos.csv` —lo escribe el
    precálculo desde la v307, una fila por equipo y partido— trae remates, a
    puerta y córners de esos partidos. Tarjetas no: siguen pendientes, que
    es la verdad.

    Mismo emparejador que arriba (`cuotas_multi._sim_club`, listón 0,80 y
    los DOS equipos), con la fila del LOCAL. Nunca lanza.
    """
    try:
        import pandas as pd
        import cuotas_multi as _cm
        ruta = 'remates_fotmob_equipos.csv'
        import os
        if not os.path.exists(ruta):
            return None
        d = pd.read_csv(ruta)
        f = str(fecha or '')[:10]
        dia = pd.Timestamp(f)
        dias = {f, (dia - pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                (dia + pd.Timedelta(days=1)).strftime('%Y-%m-%d')}
        m = d[d['fecha'].astype(str).str[:10].isin(dias)
              & (d['local'].astype(str).isin(('1', 'True', '1.0')))]
        mejor, mejor_s = None, 0.0
        for _, r in m.iterrows():
            s = min(_cm._sim_club(str(home), str(r.get('equipo'))),
                    _cm._sim_club(str(away), str(r.get('rival'))))
            if s > mejor_s:
                mejor, mejor_s = r, s
        if mejor is None or mejor_s < 0.80:
            return None
        otro = d[(d['match_id'] == mejor['match_id'])
                 & (d['equipo'] == mejor['rival'])]
        if otro.empty:
            return None
        v = otro.iloc[0]

        def _x(x):
            try:
                y = float(x)
                return None if y != y else y
            except (TypeError, ValueError):
                return None
        return {'fuente': 'fotmob',
                'corners_home': _x(mejor.get('corners')),
                'corners_away': _x(v.get('corners')),
                'tarjetas_home': None, 'tarjetas_away': None,
                'remates_on_home': _x(mejor.get('a_puerta')),
                'remates_on_away': _x(v.get('a_puerta')),
                'remates_home': _x(mejor.get('tiros')),
                'remates_away': _x(v.get('tiros'))}
    except Exception as e:
        logger.debug('[pronosticos] stats FotMob de %s-%s: %s', home, away, e)
        return None


_CAMPO = {'corners': 'corners', 'tarjetas': 'tarjetas',
          'remates': 'remates', 'remates_on': 'remates_on'}


def _valor_real(guardada: Dict, gh, ga, stats: Optional[Dict]):
    """
    El número (o el lado) que de verdad ocurrió en el mercado de esa apuesta.

    Devuelve `None` cuando no se puede saber todavía — que NO es lo mismo que
    cero y por eso no se colapsan: un mercado sin dato sale ⏳ Pendiente.
    """
    bloque = str(guardada.get('bloque') or '')
    etq = str(guardada.get('etiqueta') or '')
    if bloque == 'goles':
        return None if gh is None or ga is None else float(gh) + float(ga)
    # v309 — los mercados que el marcador resuelve y se quedaban ⏳: goles de
    # un equipo, doble oportunidad con goles y hándicap asiático. Medido el
    # 2026-09-25: 72 de 131 apuestas archivadas del día seguían «pendientes»
    # con el marcador delante, y 41 eran de estos tres mercados.
    if bloque == 'goles_equipo':
        if gh is None or ga is None:
            return None
        if etq.lower().startswith('local'):
            return float(gh)
        if etq.lower().startswith('visit'):
            return float(ga)
        return None
    if bloque in ('dc_goles', 'handicap'):
        if gh is None or ga is None:
            return None
        return (float(gh), float(ga))
    if bloque == 'btts':
        if gh is None or ga is None:
            return None
        return 'si' if (gh > 0 and ga > 0) else 'no'
    if bloque == 'resultado':
        if gh is None or ga is None:
            return None
        return 'home' if gh > ga else ('away' if ga > gh else 'draw')
    campo = _CAMPO.get(bloque)
    if campo and stats:
        h, a = stats.get('%s_home' % campo), stats.get('%s_away' % campo)
        if etq == 'Local':
            return h
        if etq == 'Visita':
            return a
        return None if h is None or a is None else h + a
    return None


def _acierto(guardada: Dict, real, home: str, away: str):
    """
    ¿Acertó esa apuesta? `(acierto, distancia_a_la_linea)`.

    `acierto` es `None` cuando no se puede juzgar. La distancia sólo existe en
    los mercados con línea y es lo que separa el 🟡 del 🔴.
    """
    if real is None:
        return None, None
    apuesta = str(guardada.get('apuesta') or '')
    bloque = str(guardada.get('bloque') or '')
    if bloque == 'dc_goles' and isinstance(real, tuple):
        return _acierto_dc_goles(guardada, real)
    if bloque == 'handicap' and isinstance(real, tuple):
        ok, dist = _acierto_handicap(apuesta, guardada.get('linea'), real,
                                     home, away)
        # la devolución sale como (None, 0.0): quien cuenta aciertos
        # (`fiabilidad_picks`, `resolver_pendientes`) la salta, y `validar`
        # la pinta ⚪ Nula
        return (None, 0.0) if ok == 'nula' else (ok, dist)
    par = _linea_de(apuesta)
    if par is not None and not isinstance(real, str):
        linea, es_mas = par
        gano = (real > linea) if es_mas else (real < linea)
        return bool(gano), abs(float(real) - linea)
    if bloque == 'btts':
        # la etiqueta es «Ambos marcan: Sí» o «Ambos marcan: No», y las dos
        # las construye `valor_apuesta._de_resultado`: no hay tercera forma
        quiere = 'no' if apuesta.strip().lower().endswith('no') else 'si'
        return bool(quiere == real), None
    if bloque == 'resultado':
        etq = str(guardada.get('etiqueta') or '')
        nombra_h = bool(home and home in apuesta)
        nombra_a = bool(away and away in apuesta)
        if etq == 'Doble':
            lados = set()
            if nombra_h:
                lados.add('home')
            if nombra_a:
                lados.add('away')
            if 'empate' in apuesta.lower():
                lados.add('draw')
            if not lados:
                return None, None
            return bool(real in lados), None
        if apuesta.strip().lower() == 'empate':
            return bool(real == 'draw'), None
        if nombra_h and not nombra_a:
            return bool(real == 'home'), None
        if nombra_a and not nombra_h:
            return bool(real == 'away'), None
    return None, None


_LADOS_DC = {'1X': ('home', 'draw'), 'X2': ('draw', 'away'),
             '12': ('home', 'away')}


def _acierto_dc_goles(guardada: Dict, real: tuple):
    """«Senegal o empate y más de 1.5»: las DOS patas tienen que cumplirse.
    La doble va en la etiqueta (1X, X2, 12) y la línea en el texto."""
    gh, ga = real
    lados = _LADOS_DC.get(str(guardada.get('etiqueta') or '').upper())
    par = _linea_de(guardada.get('apuesta'))
    if not lados or par is None:
        return None, None
    linea, es_mas = par
    res = 'home' if gh > ga else ('away' if ga > gh else 'draw')
    total = gh + ga
    ok_goles = (total > linea) if es_mas else (total < linea)
    return bool(res in lados and ok_goles), abs(total - linea)


_RE_HANDICAP = re.compile(r'handicap:\s*(.+?)\s*([+-]\d+(?:[.,]\d+)?)\s*$',
                          re.I)


def _acierto_handicap(apuesta: str, linea, real: tuple, home: str, away: str):
    """Hándicap asiático: margen del equipo + línea. Las líneas de cuarto
    (±0.25, ±0.75) son media apuesta a cada línea vecina: si una mitad gana y
    la otra se devuelve, se cobra (verde); si una pierde y la otra se
    devuelve, se pierde (rojo). Justo en la línea entera: `'nula'`."""
    m = _RE_HANDICAP.search(str(apuesta or ''))
    if not m:
        return None, None
    equipo = m.group(1).strip()
    try:
        h = float(m.group(2).replace(',', '.'))
    except ValueError:
        return None, None
    gh, ga = real
    if home and equipo == str(home).strip():
        margen = gh - ga
    elif away and equipo == str(away).strip():
        margen = ga - gh
    else:
        return None, None
    frac = round(abs(h) % 1, 2)
    mitades = ([h - 0.25, h + 0.25] if frac in (0.25, 0.75) else [h])
    res = []
    for x in mitades:
        v = margen + x
        res.append(1 if v > 1e-9 else (-1 if v < -1e-9 else 0))
    if all(r == 0 for r in res):
        return 'nula', 0.0
    if any(r > 0 for r in res) and not any(r < 0 for r in res):
        return True, abs(margen + h)
    return False, abs(margen + h)


def _estado(acierto, distancia, prob) -> str:
    """El color: verde si la predicción se cumplió, rojo si no. Y ya.

    v217 — SE QUITA EL 🟡, POR PETICIÓN EXPLÍCITA: «de nada me sirve amarillo,
    es sí o no, en cuanto a si atinó su predicción».

    El amarillo tenía DOS puertas y las dos confundían la misma pregunta:

      · acertar con probabilidad < 50 % se pintaba 🟡 («acertó, pero no lo
        sabía»). Eso es un juicio sobre la CONFIANZA, no sobre el acierto, y
        tiene su sitio: ahora vive en `fiabilidad_picks`, que mide cuánto
        acierta de verdad cada banda de probabilidad. Mezclarlo con el
        resultado hacía que un acierto pareciera medio fallo.
      · fallar por menos de una unidad se pintaba 🟡 («casi»). En una apuesta
        no hay casi: un Under 3.5 con cuatro goles se pierde igual que con
        ocho.

    `distancia` sigue en la firma y se sigue guardando en la fila, porque es
    información real para el análisis —saber si se falló por poco o por mucho
    dice mucho de un mercado—; lo que ya no hace es cambiar el color.

    ⏳ PENDIENTE se queda: no es un «casi», es «todavía no se sabe».
    """
    if acierto is None:
        return PENDIENTE
    return CUMPLIDO if acierto else FALLADO


def reconstruir(pick: Dict) -> List[Dict]:
    """
    v177 — LO QUE LA APLICACIÓN RECOMENDABA, RECONSTRUIDO DEL PRECÁLCULO.

    EL DEFECTO QUE CIERRA. El registro de `guardar` sólo existe si alguien
    —la aplicación o el bot— vio el partido ANTES de que se jugara. Un
    partido que terminó mientras nadie miraba salía con «sin pronóstico
    previo», y el usuario lo leyó como lo que parecía: que la aplicación no
    había dicho nada. Había dicho, y se puede recuperar.

    POR QUÉ ESTO **NO** ES MIRAR EL FUTURO, que es la objeción obvia y hay
    que contestarla. No se vuelve a predecir el partido: se leen los dos
    ficheros que el bot dejó ESA MAÑANA y que son estado anterior al
    pitido inicial —`predicciones_dia.json` con la matriz de marcador y
    `mercado_dia.json` con el tablero de Playdoit—. Es exactamente el mismo
    razonamiento por el que `partidos_jugados` ya reconstruye el 1X2 y los
    goles de un partido acabado, y su cabecera lo explica: recalcularlo con
    el ELO ya movido por el resultado sería otra cosa, y sería mentir.

    LO QUE SÍ CAMBIA respecto a un pronóstico guardado, y por eso las filas
    salen marcadas con `origen='precalculo'`: los dos ficheros se
    regeneran cada noche. Reconstruir el partido de esta tarde funciona;
    reconstruir el del martes pasado ya no, porque el tablero de aquel día
    no existe. Por eso `guardar` sigue siendo la vía principal y esto es la
    red debajo.
    """
    try:
        import modo_modelo as mm
        import predicciones_dia as pdia
    except Exception as e:
        logger.debug('[pronosticos] sin precalculo: %s', e)
        return []
    h_crudo = pick.get('_home_crudo')
    a_crudo = pick.get('_away_crudo')
    if not (h_crudo and a_crudo):
        # sin el nombre crudo no hay llave: los dos ficheros se indexan
        # por el del fixture, no por el del catálogo del modelo (v165).
        return []
    try:
        reg = pdia.prediccion(pick.get('clave_liga'), h_crudo, a_crudo)
    except Exception as e:
        logger.debug('[pronosticos] prediccion de %s: %s', h_crudo, e)
        return []
    if not reg:
        return []
    clave_p = '%s|%s|%s' % (pick.get('clave_liga') or '', h_crudo, a_crudo)
    previo = _pick_de_registro(clave_p, dict(reg,
                                             fecha=pick.get('fecha')))
    if not previo:
        return []
    try:
        _rm = mm.remates_tarjeta(previo) or {}
        bloques = {'Córners': mm.corners_tarjeta(previo),
                   'Tarjetas': mm.tarjetas_tarjeta(previo),
                   'Remates': _rm.get('totales'),
                   'Remates a puerta': _rm.get('a_puerta')}
        recos = mm.recomendadas(previo, bloques, n=MAX_RECOMENDADAS)
    except Exception as e:
        logger.debug('[pronosticos] reconstruir %s: %s', clave_p, e)
        return []
    if recos:
        return [dict(_fila(r), origen='precalculo') for r in recos]
    # v177 — Y SI PLAYDOIT NO COTIZA EL PARTIDO, LOS MERCADOS DEL MODELO.
    #
    # Es el caso que el usuario nombró: Dalian Yingbo - Beijing Guoan.
    # Sin precio no hay APUESTA que recomendar —regla de la v174, y no se
    # toca— pero sí hubo PROBABILIDADES, y son las que la tarjeta enseñaba
    # en su sección de mercados antes del partido. Validarlas es
    # exactamente lo que se pidió: ver si lo que decía la app se cumplió.
    #
    # Van sin cuota y sin Score a propósito, y la tarjeta lo dice: no eran
    # apuestas, eran lecturas. Confundirlas sería inventar un precio que
    # nadie ofreció.
    return _del_board(previo)


def _del_board(pick: Dict) -> List[Dict]:
    """
    Los tres mercados que el modelo calcula sin precio: goles, BTTS y 1X2.

    Se elige el lado que el modelo prefería —el de probabilidad más alta—,
    que es el que la tarjeta enseñaba en negrita. Validar el otro lado
    sería puntuar al modelo por algo que no dijo.
    """
    try:
        import modo_modelo as mm
        b = mm._board(pick) or {}
        h, a = mm._equipos(pick)
    except Exception as e:
        logger.debug('[pronosticos] board de %s: %s', pick, e)
        return []
    if not b:
        return []
    filas = []

    def _dos(mercado, bloque, etiqueta, etq_a, etq_b):
        pa, pb = b.get(etq_a), b.get(etq_b)
        if pa is None or pb is None:
            return
        gana, p = (etq_a, pa) if float(pa) >= float(pb) else (etq_b, pb)
        filas.append({'mercado': mercado, 'bloque': bloque,
                      'etiqueta': etiqueta, 'apuesta': gana,
                      'linea': 2.5 if bloque == 'goles' else None,
                      'prob': round(float(p), 4), 'cuota': None,
                      'score': None, 'semaforo': None,
                      'incierto': False, 'origen': 'modelo'})

    _dos('Goles', 'goles', 'Total', 'Más de 2.5', 'Menos de 2.5')
    _dos('BTTS', 'btts', 'Ambos marcan', 'Ambos marcan: Sí',
         'Ambos marcan: No')
    if h and a:
        tri = {'Gana %s' % h: b.get('Gana %s' % h),
               'Empate': b.get('Empate'),
               'Gana %s' % a: b.get('Gana %s' % a)}
        tri = {k: v for k, v in tri.items() if v is not None}
        if tri:
            mejor_lado = max(tri, key=lambda k: float(tri[k]))
            filas.append({'mercado': '1X2', 'bloque': 'resultado',
                          'etiqueta': 'Resultado', 'apuesta': mejor_lado,
                          'linea': None,
                          'prob': round(float(tri[mejor_lado]), 4),
                          'cuota': None, 'score': None, 'semaforo': None,
                          'incierto': False, 'origen': 'modelo'})
    return filas[:MAX_RECOMENDADAS]


def validar(pick: Dict) -> List[Dict]:
    """
    El pronóstico guardado de este partido, liquidado contra el marcador.

    Devuelve una fila por recomendación:

        {'apuesta', 'prob', 'cuota', 'score', 'mercado', 'bloque',
         'estado', 'icono', 'rotulo', 'real'}

    Se busca primero el pronóstico GUARDADO y, si no lo hay, se
    reconstruye del precálculo de esa mañana (`reconstruir`). Las
    filas reconstruidas van marcadas con `origen='precalculo'`.

    Lista vacía sólo cuando fallan las dos vías, o sea cuando el
    partido no lo evaluó nadie. La tarjeta lo enseña distinto: «sin
    pronóstico previo» no es lo mismo que «falló».
    """
    if not pick:
        return []
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
    except Exception:
        h = a = None
    if not (h and a):
        return []
    g = de_partido(pick.get('clave_liga'), h, a, pick.get('fecha'))
    filas_previas = list((g or {}).get('recomendadas') or [])
    if not filas_previas:
        # v309 — la apuesta que `partidos_jugados` archivó al empezar el
        # partido, calculada sobre el pick de antes del pitido. Es la vía de
        # las selecciones y la femenil, que no están en `predicciones_dia` y
        # por eso no se podían reconstruir: salían «sin evaluar» aunque la
        # tarjeta hubiera recomendado algo toda la mañana.
        filas_previas = [dict(f) for f in (pick.get('recomendadas_previas')
                                           or []) if isinstance(f, dict)]
    if not filas_previas:
        # v177 — la red debajo: se reconstruye del precálculo de esa
        # mañana. Ver `reconstruir`.
        filas_previas = reconstruir(pick)
    if not filas_previas:
        return []
    gh, ga = pick.get('goles_home'), pick.get('goles_away')
    stats = None
    if any(str(f.get('bloque')) in _CAMPO for f in filas_previas):
        stats = _stats_del_partido(pick.get('clave_liga'), h, a,
                                   pick.get('fecha'))
        # v309 — lo que falte, de la ficha de FotMob que `partidos_jugados`
        # guardó con el partido (selecciones y femenil no están en ESPN, y
        # las tarjetas no están en `remates_fotmob_equipos.csv`)
        extra = pick.get('stats_partido') or {}
        if extra:
            stats = dict(stats or {})
            for k, v in extra.items():
                if stats.get(k) is None and v is not None:
                    stats[k] = v
    salida = []
    for f in filas_previas:
        real = _valor_real(f, gh, ga, stats)
        acierto, dist = _acierto(f, real, h, a)
        est = _estado(acierto, dist, f.get('prob'))
        if (acierto is None and dist == 0.0 and real is not None
                and str(f.get('bloque')) == 'handicap'):
            est = NULA                   # v309: justo en la línea, se devuelve
        # v217 — LA DISTANCIA SE DEVUELVE, aunque ya no decida el color.
        #
        # Se calculaba y se tiraba. Desde que el estado es binario, la
        # distancia deja de pintar nada — pero es justo entonces cuando vale
        # como DATO: fallar un Under 3.5 por medio gol y fallarlo por cuatro
        # son dos cosas muy distintas sobre un mercado, y sin este campo el
        # análisis no puede distinguirlas.
        salida.append({**f, 'estado': est, 'icono': ICONO[est],
                       'rotulo': ROTULO[est], 'real': real,
                       'acierto': acierto, 'distancia': dist})
    return salida


def resumen(filas: List[Dict]) -> Dict:
    """Cuántas cumplieron, cuántas quedaron cerca y cuántas no. Para el estado."""
    c = {CUMPLIDO: 0, CERCA: 0, FALLADO: 0, PENDIENTE: 0, NULA: 0}
    for f in (filas or []):
        c[f.get('estado', PENDIENTE)] = c.get(f.get('estado', PENDIENTE), 0) + 1
    return c

# ---------------------------------------------------------------------------
# el bot: anotar el día entero, para que el registro sobreviva al reinicio
# ---------------------------------------------------------------------------
def _pick_de_registro(clave_partido: str, reg: Dict) -> Optional[Dict]:
    """
    Un pick con la forma que espera `valor_apuesta`, desde el precálculo.

    Las dos piezas son ficheros que el bot ya deja en el repositorio:
    `predicciones_dia.json` (la matriz de marcador, indexada por el nombre
    CRUDO del fixture) y `mercado_dia.json` (el tablero de Playdoit, con
    la misma indexación). Que compartan indexación es lo que hace esto
    posible sin cargar un solo motor de liga.
    """
    try:
        import alpha_finder as af
        import mercado_implicito as mi
        import partidos_jugados as pj
        import predicciones_dia as pdia
        trozos = str(clave_partido).split('|')
        if len(trozos) < 3:
            return None
        liga, h_crudo, a_crudo = trozos[0], trozos[1], trozos[2]
        pred = pdia.como_prediccion(reg)
        if not pred:
            return None
        hm = reg.get('home') or h_crudo
        am = reg.get('away') or a_crudo
        pick = {
            'partido': '%s vs %s' % (hm, am), 'clave_liga': liga,
            'deporte': 'Fútbol', 'liga': reg.get('liga') or liga,
            'fecha': str(reg.get('fecha') or '')[:10],
            'inicio': reg.get('inicio'),
            'board': pj._board_de_matriz(pred.get('score_matrix'), hm, am,
                                         pred.get('probabilities')),
            'goles_lineas': af.lineas_de_goles(pred, clave_liga=liga,
                                              home=hm, away=am),
        }
        # el tablero se busca con el nombre CRUDO, que es como se indexa.
        # Buscarlo con el mapeado encontraba 22 de 151 (v165).
        imp = mi.del_partido(h_crudo, a_crudo) or {}
        if imp:
            pick['implicitas'] = imp
        return pick
    except Exception as e:
        logger.debug('[pronosticos] pick de %s: %s', clave_partido, e)
        return None


def _resultado_historico(clave_liga, home: str, away: str, fecha: str):
    """Los goles reales de ese partido, del historico de la competicion.

    Se usa `panel_equipos._historico`, que es el MISMO cargador del que comen
    `rendimiento_equipos` y los modelos de conteo. Una segunda via para leer
    resultados acabaria discrepando de la primera, y entonces un pick saldria
    acertado en una pantalla y fallado en otra.
    """
    try:
        import pandas as pd
        import panel_equipos as pe
        import cuotas_multi as cm
    except Exception as e:
        logger.debug('[resolver] sin dependencias: %s', e)
        return None
    try:
        d = pe._historico(str(clave_liga or ''))
    except Exception as e:
        logger.debug('[resolver] historico de %s: %s', clave_liga, e)
        return None
    if d is None or getattr(d, 'empty', True):
        return None
    if 'home_goals' not in d.columns or 'date' not in d.columns:
        return None
    f = str(fecha or '')[:10]
    if not f:
        return None
    try:
        dias = pd.to_datetime(d['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    except Exception:
        return None
    # +-1 dia: el historico guarda la fecha local de la competicion y el
    # registro la del fixture en UTC, y en los partidos de madrugada no
    # coinciden. Mas de un dia ya no es el mismo partido.
    objetivo = pd.to_datetime(f, errors='coerce')
    if objetivo is None or objetivo is pd.NaT:
        return None
    cerca = d[(pd.to_datetime(dias, errors='coerce')
               - objetivo).abs() <= pd.Timedelta(days=1)]
    if not len(cerca):
        return None
    mejor, mejor_s = None, 0.0
    for _, r in cerca.iterrows():
        s = min(cm._sim_club(str(home), str(r.get('home_team'))),
                cm._sim_club(str(away), str(r.get('away_team'))))
        if s > mejor_s:
            mejor, mejor_s = r, s
    if mejor is None or mejor_s < 0.80:
        return None
    gh, ga = mejor.get('home_goals'), mejor.get('away_goals')
    try:
        return int(gh), int(ga)
    except (TypeError, ValueError):
        return None


def resolver_pendientes(maximo: int = 0) -> Dict:
    """v249 — Liquida los picks de los partidos que ya terminaron.

    EL HUECO QUE CIERRA. `anotar_el_dia` dejaba escrito lo que la aplicacion
    iba a recomendar, y `validar()` sabia juzgarlo contra el resultado — pero
    nadie juntaba las dos cosas: `validar` solo se llamaba al abrir la ficha de
    un partido, y su veredicto no se guardaba en ninguna parte. Resultado
    medido: 1.591 partidos anotados y CERO resueltos.

    Sin esto no hay material para calibrar corners, tarjetas ni remates —hay
    498 picks de corners guardados sin resolver— y el modelo no puede aprender
    de lo que recomendo.

    De solo-escritura sobre lo que falta: un pick ya resuelto no se vuelve a
    tocar, asi que correr esto dos veces no cambia nada.
    """
    doc = _leer()
    if not doc:
        return {'partidos': 0, 'resueltos': 0, 'picks': 0, 'pendientes': 0}
    import datetime as _dt
    hoy = _dt.date.today().isoformat()
    res = {'partidos': 0, 'resueltos': 0, 'picks': 0, 'pendientes': 0}
    cambios = False
    for k, reg in doc.items():
        filas = (reg or {}).get('recomendadas') or []
        if not filas:
            continue
        if all(f.get('acierto') is not None for f in filas):
            continue
        # v249 — SIN `fecha`, VALE `anotado`, Y SON 947 DE 1.591.
        #
        # Lo avisa el propio `_poda`: los registros que deja el bot salen de
        # `predicciones_dia.json`, que NO guarda la fecha del partido. Sin
        # fecha no hay contra que resolver, y esos eran la mayoria del fichero.
        #
        # `anotado` es el dia en que el bot escribio la entrada, y el bot anota
        # los partidos DEL DIA, asi que es la fecha del partido con un margen
        # de horas. `_resultado_historico` ya busca con +-1 dia y exige que los
        # dos equipos casen al 0,80, de modo que el margen no puede emparejar
        # un partido distinto.
        f_partido = (str((reg or {}).get('fecha') or '')[:10]
                     or str((reg or {}).get('anotado') or '')[:10])
        if not f_partido or f_partido >= hoy:
            res['pendientes'] += 1          # todavia no se ha jugado
            continue
        res['partidos'] += 1
        pick = _pick_de_registro(k, reg)
        if not pick:
            pick = {'partido': '%s vs %s' % (reg.get('home'), reg.get('away')),
                    'clave_liga': str(k).split('|')[0],
                    'fecha': f_partido, 'deporte': 'Fútbol'}
        pick['fecha'] = pick.get('fecha') or f_partido
        marcador = _resultado_historico(pick.get('clave_liga'),
                                        reg.get('home') or '',
                                        reg.get('away') or '', f_partido)
        if not marcador:
            res['pendientes'] += 1
            continue
        pick['goles_home'], pick['goles_away'] = marcador
        try:
            juzgadas = validar(pick)
        except Exception as e:
            logger.debug('[resolver] %s: %s', k, e)
            continue
        if not juzgadas:
            continue
        # se casan por la etiqueta de la apuesta, que es lo unico estable
        por_apuesta = {str(j.get('apuesta')): j for j in juzgadas}
        n = 0
        for f in filas:
            j = por_apuesta.get(str(f.get('apuesta')))
            if not j or j.get('acierto') is None:
                continue
            f['acierto'] = bool(j['acierto'])
            f['real'] = j.get('real')
            f['estado'] = j.get('estado')
            n += 1
        if n:
            reg['resuelto'] = hoy
            reg['goles_home'], reg['goles_away'] = marcador
            res['resueltos'] += 1
            res['picks'] += n
            cambios = True
        if maximo and res['resueltos'] >= int(maximo):
            break
    if cambios:
        _escribir(doc)
    logger.info('[resolver] %d partidos resueltos, %d picks liquidados '
                '(%d siguen pendientes)',
                res['resueltos'], res['picks'], res['pendientes'])
    return res


def anotar_el_dia(maximo: int = 0) -> Dict:
    """
    v176 — EL BOT DEJA ANOTADO LO QUE LA APLICACIÓN VA A RECOMENDAR.

    POR QUÉ ESTO NO PUEDE VIVIR SÓLO EN LA APLICACIÓN. Streamlit Cloud
    reinicia el contenedor cuando le parece y lo que la aplicación escribió
    en disco se va con él. Un registro que se pierde en el reinicio no
    sirve para validar nada al día siguiente, que es justo para lo que se
    pidió. Así que se genera aquí, en el mismo workflow nocturno que ya
    produce `predicciones_dia.json` y `mercado_dia.json`, y viaja en el
    repositorio como ellos.

    Y ADEMÁS CIERRA EL PUNTO 1.3 DEL ENCARGO. La aplicación sólo puede
    anotar los partidos que alguien mira; esto anota **todos los que el
    precálculo evaluó**, los mire alguien o no. Era el caso de Dalian
    Yingbo - Beijing Guoan.

    El registro sigue siendo de sólo-inserción: si el partido ya estaba
    anotado —porque alguien abrió la aplicación antes— no se toca.
    """
    resumen_ = {
        'evaluados': 0, 'anotados': 0, 'ya_estaban': 0, 'sin_apuesta': 0}
    try:
        import modo_modelo as mm
        import predicciones_dia as pdia
        doc = pdia._leer() or {}
        registros = doc.get('predicciones') or doc.get('partidos') or {}
    except Exception as e:
        logger.warning('[pronosticos] sin precalculo: %s', e)
        return resumen_
    if not isinstance(registros, dict):
        return resumen_
    for i, (k, reg) in enumerate(registros.items()):
        if maximo and i >= int(maximo):
            break
        if not isinstance(reg, dict):
            continue
        resumen_['evaluados'] += 1
        pick = _pick_de_registro(k, reg)
        if not pick:
            continue
        _h, _a = mm._equipos(pick)
        if _h and _a and de_partido(pick.get('clave_liga'), _h, _a,
                                    pick.get('fecha')):
            resumen_['ya_estaban'] += 1
            continue
        try:
            # los bloques físicos entran: son los mismos que la tarjeta
            # calcula y NO piden red (esa regla ya costó tres regresiones).
            # Sin ellos, córners, tarjetas y remates no podrían validarse
            # nunca, que es la mitad del ejemplo del encargo.
            _rm = mm.remates_tarjeta(pick) or {}
            bloques = {'Córners': mm.corners_tarjeta(pick),
                       'Tarjetas': mm.tarjetas_tarjeta(pick),
                       'Remates': _rm.get('totales'),
                       'Remates a puerta': _rm.get('a_puerta')}
            recos = mm.recomendadas(pick, bloques, n=MAX_RECOMENDADAS)
        except Exception as e:
            logger.debug('[pronosticos] recomendadas de %s: %s', k, e)
            recos = []
        if not recos:
            resumen_['sin_apuesta'] += 1
            continue
        if guardar(pick, recos):
            resumen_['anotados'] += 1
    return resumen_


def main() -> int:
    """Uso: `python pronosticos_guardados.py [--max N]`."""
    import argparse
    ap = argparse.ArgumentParser(description='Anota los pronosticos del dia')
    ap.add_argument('--max', type=int, default=0,
                    help='tope de partidos (0 = todos)')
    args = ap.parse_args()
    r = anotar_el_dia(args.max)
    print('evaluados %d · anotados %d · ya estaban %d · sin apuesta %d'
          % (r['evaluados'], r['anotados'], r['ya_estaban'],
             r['sin_apuesta']))
    print('%d partidos con pronostico guardado en %s' % (cuantos(),
                                                        FICHERO))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
