#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v323 — LA APLICACIÓN LEE LAS DECISIONES EN VEZ DE TOMARLAS EN CADA CLIC.

QUÉ RESUELVE
------------
`modo_modelo.render` calculaba, en CADA pasada de Streamlit y para CADA
partido de las tres vistas (hoy, mañana y pasado), la apuesta destacada y las
cuatro recomendadas. Son funciones puras de los datos del pronóstico y de unos
ficheros de calibración que sólo cambian cuando un bot los commitea. Medido en
esta máquina el 2026-10-03 sobre el `pronostico_dia.json` de las 09:19Z (355
partidos): **21,5 s** en un proceso nuevo para recalcular lo mismo que ya se
había calculado la pasada anterior.

Ahora lo calcula el cron (`precalculo_dia.yml`) una vez, lo guarda en el JSON
y la aplicación lo LEE.

LA GARANTÍA: LO PRECALCULADO SÓLO SE USA SI SIGUE SIENDO LO QUE LA APP DIRÍA
---------------------------------------------------------------------------
El resultado depende del código y de ~40 ficheros de datos (calibraciones,
históricos, ranking de estabilidad…). Un bot puede commitear una calibración
nueva DESPUÉS de que el cron cocinara el día; si la app siguiera usando lo
cocinado, enseñaría una apuesta que su propio código ya no daría. Eso no se
admite.

Por eso el cálculo se hace en un proceso NUEVO con un gancho de auditoría
(`sys.addaudithook`) que apunta cada fichero del repositorio que se abre, y
cada módulo del repositorio que se importa. Su contenido (sha1) viaja en el
JSON como «huella». La aplicación, al leer el JSON, recalcula esa huella con
SUS ficheros: si coincide, adjunta las decisiones a cada partido; si un solo
byte difiere, no adjunta nada y la pantalla calcula como siempre. O sea: en el
peor caso la app es tan lenta como antes, nunca distinta.

Y lo que cambia en vivo (`jugado`, los partidos ya acabados del día) NO se
precalcula: `render` sigue resolviéndolo en la app, igual que antes.

Uso (lo llama `precalculo_dia.py` al final; también suelto):
    python decisiones_dia.py [pronostico_dia.json]
"""
import copy
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

logger = logging.getLogger('decisiones_dia')

RAIZ = os.path.dirname(os.path.abspath(__file__))
VERSION = 1
CLAVE_DOC = 'decisiones'        # en el documento, junto a `datos`
CLAVE_PICK = '_decision'        # en cada partido, sólo en memoria de la app
LISTAS = ('pronosticos', 'solo_mercado')

# Ficheros que el cálculo LEE pero que no son una entrada: cachés que la
# propia app reescribe mientras pinta, con una respuesta que sólo depende de
# otros ficheros que sí van en la huella. Si entraran, la huella dejaría de
# valer en cuanto la app los tocara, que es lo que pasó en la primera prueba
# dentro de la app real (2026-10-03): la app los reescribe al pintar y desde
# ahí calculaba todo en vivo.
#
#   cache_columnas_sinteticas.json — `rendimiento_equipos._columnas_sinteticas`
#       guarda qué columnas de cada `historico_*.csv` escribió el generador
#       sintético; es una REPRODUCCIÓN determinista del histórico, que sí va
#       en la huella. Está en `.gitignore`: en la app ni siquiera viene del
#       repositorio.
NO_SON_ENTRADA = frozenset({'cache_columnas_sinteticas.json'})


# ---------------------------------------------------------------------------
# la decisión de UN partido: exactamente lo que hace `modo_modelo.render`
# ---------------------------------------------------------------------------
def decidir(p: Dict) -> Dict:
    """`{'destacada', 'recomendadas'}` de un partido sin jugar.

    Son las dos líneas de `modo_modelo.render` copiadas tal cual, con las
    mismas llamadas y los mismos argumentos. Si `render` cambia la forma de
    calcularlas, la prueba de equivalencia (`test_v323.py`) falla.
    """
    import modo_modelo as mm
    out = {'destacada': mm.apuesta_destacada(p),
           'recomendadas': mm.recomendadas(p, None, n=mm.MAX_RECOMENDADAS)}
    # Y la de la TARJETA, que es otra cuenta: lleva los bloques de córners,
    # tarjetas y remates (`modo_modelo.tarjeta`, rama con modelo). Sólo en
    # los partidos que pasan por esa rama; en los demás la tarjeta no la pide.
    if not (p.get('solo_mercado') or p.get('sin_modelo')
            or p.get('prob') is None):
        _rm = mm.remates_tarjeta(p)
        bloques = {'Córners': mm.corners_tarjeta(p),
                   'Tarjetas': mm.tarjetas_tarjeta(p),
                   'Remates': (_rm or {}).get('totales'),
                   'Remates a puerta': (_rm or {}).get('a_puerta')}
        out['recomendadas_tarjeta'] = mm.recomendadas(
            p, bloques, n=mm.MAX_RECOMENDADAS)
        # v347 — las demás que también se meten (el desplegable)
        out['otras_tarjeta'] = mm.otras_que_se_meten(
            p, bloques, mm.metidas(out['recomendadas_tarjeta']))
    return out


def _llave(p: Dict) -> List:
    """Con qué se comprueba que la decisión i es la del partido i."""
    return [str(p.get('partido') or ''), str(p.get('inicio') or ''),
            str(p.get('clave_liga') or '')]


# ---------------------------------------------------------------------------
# la huella
# ---------------------------------------------------------------------------
_CACHE_SHA: Dict[str, tuple] = {}
# Las extensiones que `.gitattributes` declara `text eol=lf`.
TEXTO_LF = ('.csv', '.json', '.py', '.md', '.yml')


def _sha(ruta_rel: str) -> Optional[str]:
    """sha1 del fichero, memorizado por (mtime, tamaño). `None` si no existe."""
    ruta = os.path.join(RAIZ, ruta_rel)
    try:
        st = os.stat(ruta)
    except OSError:
        return None
    firma = (st.st_mtime_ns, st.st_size)
    c = _CACHE_SHA.get(ruta)
    if c and c[0] == firma:
        return c[1]
    h = hashlib.sha1()
    if os.path.splitext(ruta)[1].lower() in TEXTO_LF:
        # Lo que se compara es lo que git GUARDA. En `.gitattributes` estos
        # ficheros son `text eol=lf`: git convierte CRLF en LF al commitear.
        # Medido en el primer precálculo real (2026-10-03 12:48Z): el runner
        # escribió `remates_fotmob_equipos.csv` con CRLF, el commit lo guardó
        # con LF y la huella no casaba con lo que la app recibe — habría
        # calculado siempre en vivo. Para leerlos (pandas, json, Python) los
        # dos saltos de línea son lo mismo.
        with open(ruta, 'rb') as f:
            h.update(f.read().replace(b'\r\n', b'\n'))
    else:
        with open(ruta, 'rb') as f:
            for trozo in iter(lambda: f.read(1 << 20), b''):
                h.update(trozo)
    _CACHE_SHA[ruta] = (firma, h.hexdigest())
    return _CACHE_SHA[ruta][1]


def _dia() -> List[str]:
    """El día del reloj, en hora local del proceso y en UTC.

    Hay ventanas que cuentan desde AHORA (`historico_real._ventana`, los
    últimos 730 días de una selección; `patrones_liga.Tabla.rasgos`, equipos
    activos en los últimos N días). Los históricos van por día —sin hora—, así
    que esas ventanas sólo cambian al pasar la medianoche: dentro del mismo
    día la respuesta es la misma, y al cambiar de día lo precalculado deja de
    valer y la app calcula en vivo hasta el siguiente precálculo. La hora
    local es la que usa `pd.Timestamp.now()`; la UTC va por si el contenedor
    tuviera otra zona.
    """
    import datetime as _dt
    return [_dt.datetime.now().date().isoformat(),
            _dt.datetime.now(_dt.timezone.utc).date().isoformat()]


def huella_vigente(huella: Optional[Dict]) -> bool:
    """¿Los ficheros de los que salió la decisión siguen siendo los mismos?"""
    if not isinstance(huella, dict) or not huella:
        return False
    try:
        return all(_sha(r) == s for r, s in huella.items())
    except Exception as e:
        logger.debug('[decisiones] huella: %s', e)
        return False


# ---------------------------------------------------------------------------
# el cálculo, en un proceso nuevo y vigilado
# ---------------------------------------------------------------------------
def _calcular_aqui(ruta: str, salida: str) -> int:
    """Corre en el subproceso: calcula y apunta qué ficheros tocó."""
    abiertos, escritos = set(), set()
    red = []

    def gancho(ev, args):
        # Si el cálculo saliera a la red, su respuesta dependería de cuándo se
        # hizo y no sólo de los ficheros: entonces no se puede reutilizar.
        if ev in ('socket.connect', 'socket.getaddrinfo'):
            red.append(ev)
            return
        if ev == 'open' and args and isinstance(args[0], (str, bytes)):
            try:
                a = os.fsdecode(args[0])
                p = os.path.abspath(a)
            except Exception:
                return
            if p.startswith(RAIZ + os.sep):
                r = os.path.relpath(p, RAIZ)
                abiertos.add(r)
                modo = args[1] if len(args) > 1 else None
                banderas = args[2] if len(args) > 2 else 0
                if ((isinstance(modo, str) and any(c in modo for c in 'wax+'))
                        or (isinstance(banderas, int) and banderas
                            & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))):
                    escritos.add(r)

    antes = set(sys.modules)
    with open(ruta, encoding='utf-8') as f:
        doc = json.load(f)
    datos = doc.get('datos') or {}
    sys.addaudithook(gancho)
    # La app pasa los datos por `nombres_ligas.aplicar` antes de pintar
    # (`dashboard_ui.barrido_universal`): se calcula sobre lo MISMO.
    try:
        import nombres_ligas
        nombres_ligas.aplicar(datos)
    except Exception as e:
        logger.debug('[decisiones] nombres de liga: %s', e)
    import modo_modelo  # noqa: F401  (para que su cierre entre en la huella)
    t0 = time.time()
    res = {}
    for lista in LISTAS:
        filas = []
        for p in (datos.get(lista) or []):
            if not isinstance(p, dict) or p.get('jugado'):
                filas.append(None)
                continue
            filas.append({'llave': _llave(p), **decidir(p)})
        res[lista] = filas
    ficheros = set()
    for m in set(sys.modules) - antes:
        f = getattr(sys.modules.get(m), '__file__', None)
        if f and os.path.abspath(f).startswith(RAIZ + os.sep):
            ficheros.add(os.path.relpath(os.path.abspath(f), RAIZ))
    for a in abiertos:
        if '__pycache__' in a or a.endswith('.pyc'):
            continue
        # Lo que el propio cálculo ESCRIBE es una caché suya (p. ej.
        # `cache_columnas_sinteticas.json`, que guarda una prueba determinista
        # de los históricos): no es una entrada, y su copia del contenedor de
        # la app nunca coincidirá byte a byte con la del runner.
        if a in escritos or a in NO_SON_ENTRADA:
            continue
        if os.path.abspath(os.path.join(RAIZ, a)) == os.path.abspath(ruta):
            continue
        if os.path.isfile(os.path.join(RAIZ, a)):
            ficheros.add(a)
    huella = {r: _sha(r) for r in sorted(ficheros)}
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump({'version': VERSION, 'huella': huella, 'dia': _dia(),
                   'red': len(red),
                   'escritos': sorted(escritos), 'listas': res,
                   'segundos': round(time.time() - t0, 1)}, f,
                  ensure_ascii=False)
    return 0


def calcular(ruta: str) -> Optional[Dict]:
    """Lanza el cálculo en un proceso nuevo y devuelve lo que dejó."""
    import tempfile
    fd, salida = tempfile.mkstemp(prefix='decisiones_', suffix='.json')
    os.close(fd)
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__),
                            '--interno', os.path.abspath(ruta), salida],
                           cwd=RAIZ, timeout=1800)
        if r.returncode != 0:
            logger.warning('[decisiones] el cálculo terminó con %s',
                           r.returncode)
            return None
        with open(salida, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning('[decisiones] no se pudieron calcular: %s', e)
        return None
    finally:
        try:
            os.remove(salida)
        except OSError:
            pass


def anadir(ruta: str) -> bool:
    """Calcula las decisiones del JSON `ruta` y las escribe dentro.

    Falla en blando: sin decisiones, el JSON sigue siendo el de siempre y la
    app calcula como hasta ahora.
    """
    res = calcular(ruta)
    if not res:
        return False
    try:
        with open(ruta, encoding='utf-8') as f:
            doc = json.load(f)
        doc[CLAVE_DOC] = res
        import io_atomico
        ok = bool(io_atomico.escribir_json(ruta, doc))
        logger.info('decisiones precalculadas: %s partidos en %.1f s, huella '
                    'de %d ficheros', sum(len([x for x in v if x]) for v in
                                          res['listas'].values()),
                    res.get('segundos') or 0, len(res['huella']))
        return ok
    except Exception as e:
        logger.warning('[decisiones] no se pudieron escribir: %s', e)
        return False


# ---------------------------------------------------------------------------
# el lado de la aplicación
# ---------------------------------------------------------------------------
def adjuntar(doc: Dict) -> int:
    """Pone en cada partido de `doc['datos']` su decisión precalculada.

    Sólo si la huella sigue vigente y si cada fila casa con su partido. Si no,
    no toca nada. Devuelve cuántos partidos la llevan.
    """
    try:
        dec = doc.get(CLAVE_DOC)
        if not isinstance(dec, dict) or dec.get('version') != VERSION:
            return 0
        if dec.get('red'):
            logger.info('[decisiones] el cálculo salió a la red: no se '
                        'reutiliza')
            return 0
        if dec.get('dia') != _dia():
            logger.info('[decisiones] precalculadas otro día: se calculan '
                        'en vivo')
            return 0
        if not huella_vigente(dec.get('huella')):
            logger.info('[decisiones] la huella no coincide con los ficheros '
                        'de esta app: se calculan en vivo')
            return 0
        datos = doc.get('datos') or {}
        n = 0
        for lista in LISTAS:
            picks = datos.get(lista) or []
            filas = (dec.get('listas') or {}).get(lista) or []
            if len(filas) != len(picks):
                return 0
            for p, f in zip(picks, filas):
                if not isinstance(p, dict) or not f:
                    continue
                if f.get('llave') != _llave(p):
                    continue
                p[CLAVE_PICK] = f
                n += 1
        return n
    except Exception as e:
        logger.debug('[decisiones] adjuntar: %s', e)
        return 0


def tarjeta_de_pick(p: Dict):
    """Las recomendadas de la tarjeta (con bloques), en copia, o `None`."""
    f = p.get(CLAVE_PICK) if isinstance(p, dict) else None
    if not isinstance(f, dict) or 'recomendadas_tarjeta' not in f:
        return None
    return copy.deepcopy(f['recomendadas_tarjeta'])


def otras_de_pick(p: Dict):
    """v347 — las «también se meten» precalculadas, en copia, o `None`."""
    f = p.get(CLAVE_PICK) if isinstance(p, dict) else None
    if not isinstance(f, dict) or 'otras_tarjeta' not in f:
        return None
    return copy.deepcopy(f['otras_tarjeta'])


def de_pick(p: Dict):
    """`(destacada, recomendadas)` precalculadas, o `None` si no las hay.

    Devuelve COPIAS: `render` y `tarjeta` cuelgan cosas de estas filas, y el
    cálculo de siempre entregaba objetos nuevos en cada pasada.
    """
    f = p.get(CLAVE_PICK) if isinstance(p, dict) else None
    if not isinstance(f, dict) or 'recomendadas' not in f:
        return None
    return (copy.deepcopy(f.get('destacada')),
            copy.deepcopy(f.get('recomendadas') or []))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if len(sys.argv) >= 4 and sys.argv[1] == '--interno':
        sys.exit(_calcular_aqui(sys.argv[2], sys.argv[3]))
    _ruta = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        'PRECALCULO_DIA', 'pronostico_dia.json')
    sys.exit(0 if anadir(_ruta) else 1)
