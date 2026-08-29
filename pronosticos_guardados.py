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
ICONO = {CUMPLIDO: '\U0001f7e2', CERCA: '\U0001f7e1', FALLADO: '\U0001f534',
         PENDIENTE: '⏳'}
ROTULO = {CUMPLIDO: 'Cumplido', CERCA: 'Cerca', FALLADO: 'No cumplido',
          PENDIENTE: 'Pendiente'}
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
        return bool(io_atomico.escribir_json(FICHERO, doc, indent=1))
    except Exception as e:
        logger.debug('[pronosticos] no se pudo escribir %s: %s', FICHERO, e)
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
    return {k: v for k, v in doc.items() if _dia(v) >= corte}


def _fila(f: Dict) -> Dict:
    """La copia que se guarda de una recomendación. Sólo lo que hay que liquidar."""
    return {'mercado': f.get('mercado'), 'bloque': f.get('bloque'),
            'etiqueta': f.get('etiqueta'), 'apuesta': f.get('apuesta'),
            'linea': f.get('linea'),
            'prob': (None if f.get('prob') is None
                     else round(float(f['prob']), 4)),
            'cuota': f.get('cuota'), 'score': f.get('score'),
            'semaforo': f.get('semaforo'),
            'incierto': bool(f.get('incierto'))}


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
    doc = dict(doc)
    doc[k] = {'clave_liga': pick.get('clave_liga'), 'home': h, 'away': a,
              'partido': pick.get('partido'), 'liga': pick.get('liga'),
              'fecha': str(pick.get('fecha') or '')[:10],
              'inicio': pick.get('inicio'),
              'anotado': _hoy(),
              'recomendadas': filas}
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
            return None
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
            return None
        h, a = str(home or '').strip(), str(away or '').strip()
        fila = m[(m['home'].astype(str) == h) & (m['away'].astype(str) == a)]
        if fila.empty:
            return None
        r = fila.iloc[-1]

        def _n(col):
            try:
                v = float(r.get(col))
                return None if v != v else v
            except (TypeError, ValueError):
                return None
        return {
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


def _estado(acierto, distancia, prob) -> str:
    """El color, con las dos puertas del 🟡 que pidió el encargo."""
    if acierto is None:
        return PENDIENTE
    try:
        p = float(prob)
    except (TypeError, ValueError):
        p = None
    if acierto:
        # acertar con menos del 50 % es acertar, pero no es haberlo sabido
        if p is not None and p < PROB_FLOJA:
            return CERCA
        return CUMPLIDO
    if distancia is not None and distancia <= MARGEN_CERCA:
        return CERCA
    return FALLADO


def validar(pick: Dict) -> List[Dict]:
    """
    El pronóstico guardado de este partido, liquidado contra el marcador.

    Devuelve una fila por recomendación:

        {'apuesta', 'prob', 'cuota', 'score', 'mercado', 'bloque',
         'estado', 'icono', 'rotulo', 'real'}

    Lista vacía si no había pronóstico guardado. Es una distinción que la
    tarjeta enseña: «sin pronóstico previo» no es lo mismo que «falló».
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
    if not g:
        return []
    gh, ga = pick.get('goles_home'), pick.get('goles_away')
    stats = None
    if any(str(f.get('bloque')) in _CAMPO for f in (g.get('recomendadas') or [])):
        stats = _stats_del_partido(pick.get('clave_liga'), h, a,
                                   pick.get('fecha'))
    salida = []
    for f in (g.get('recomendadas') or []):
        real = _valor_real(f, gh, ga, stats)
        acierto, dist = _acierto(f, real, h, a)
        est = _estado(acierto, dist, f.get('prob'))
        salida.append({**f, 'estado': est, 'icono': ICONO[est],
                       'rotulo': ROTULO[est], 'real': real,
                       'acierto': acierto})
    return salida


def resumen(filas: List[Dict]) -> Dict:
    """Cuántas cumplieron, cuántas quedaron cerca y cuántas no. Para el estado."""
    c = {CUMPLIDO: 0, CERCA: 0, FALLADO: 0, PENDIENTE: 0}
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
