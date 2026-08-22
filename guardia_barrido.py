#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Un solo barrido de alpha_finder a la vez en todo el proceso.
v148 — Y además: el que llega no espera al barrido si ya hay uno servible.

EL PROBLEMA ORIGINAL (v86), QUE SIGUE VIGENTE
---------------------------------------------
_v86_barrido_concurrente.py, sobre el barrido real:

    1 barrido  -> pico de 1297,7 MB  (95,8 s)
    2 barridos -> pico de 2172,2 MB

Streamlit Cloud es UN proceso con UNA hebra por sesión, así que dos barridos
simultáneos suman en el mismo contenedor. Ése es el "se cae cuando se conectan
dos personas".

Por qué no bastaba el caché de Streamlit: `@st.cache_data` ya serializa por
clave con un cerrojo (`compute_value_lock`), pero `cache_data.clear()` borra
ese diccionario de cerrojos (cache_utils.py:162-164), y hasta la v85 el
dashboard llamaba a `clear()` en cada visitante nuevo. La protección se
desactivaba justo cuando hacía falta. Este guardia vive en un módulo normal,
así que sobrevive a cualquier `clear()` y a que app.py re-ejecute
dashboard_ui.py con runpy en cada rerun.

LO QUE AÑADE LA v148
--------------------
El guardia resolvía la concurrencia pero no la ESPERA. Su estado vivía sólo en
memoria del proceso, así que el primer visitante después de cada arranque de
contenedor —que en Streamlit Cloud es constante: la app se duerme y se
despierta— pagaba el barrido entero. Medido por el usuario: ~122 s mirando un
spinner.

Ahora hay dos niveles y una regla:

    memoria  ->  disco  ->  calcular

  · FRESCURA_S (5 min): por debajo, lo que hay vale y no se toca nada.
  · CADUCIDAD_S (1 h): entre una y otra, se DEVUELVE lo que hay al instante y
    se lanza la revalidación en segundo plano. Por encima, se calcula.

POR QUÉ SE PUEDE SERVIR ALGO DE HACE MEDIA HORA, Y QUÉ NO
---------------------------------------------------------
No todo el barrido envejece igual, y meterlo todo en el mismo saco sería
deshonesto en la dirección peligrosa:

  · el PRONÓSTICO del modelo (el 1X2 de cada partido, la lista de lo que se
    juega hoy) no cambia en media hora: sale de un modelo entrenado de
    madrugada. Servirlo de caché es correcto.
  · el PRECIO sí cambia, y enseñar una cuota de hace media hora como si fuera
    la de ahora es exactamente el error que este proyecto no comete.

Por eso el resultado servido de caché viaja SIEMPRE con `_frescura`, y la
interfaz avisa de la edad antes de que nadie mire una cuota. El guardia no
decide qué se enseña: da el dato y su edad, y quien pinta decide.

`CADUCIDAD_S` es el límite de lo que tiene sentido enseñar aunque se avise:
pasada una hora, buena parte de los partidos de la ventana ya han empezado.
"""
import logging
import os
import pickle
import threading
import time

logger = logging.getLogger(__name__)

FRESCURA_S = 300          # v148: 5 min — por debajo, se sirve tal cual

# v154 — DE 1 HORA A 3, Y ES UNA DECISIÓN DE PRODUCTO, NO UN AJUSTE.
#
# Por encima de esto no se sirve ni con aviso: se recalcula, y quien llega paga
# los ~52 s completos. Con el tope en 1 h eso pasaba a menudo, porque Streamlit
# Cloud reinicia por inactividad y la caché se pierde: la queja era «la primera
# vez tarda mucho».
#
# Lo que se cambia y lo que no:
#
#   · Los PRONÓSTICOS del modelo no caducan dentro del día. El 1X2 de un partido
#     de esta tarde es el mismo a las 10:00 que a las 13:00 — sólo cambia cuando
#     el bot reentrena. Servirlos de hace tres horas no degrada nada.
#   · Las CUOTAS sí se mueven. Por eso el tope no es «infinito con aviso»: es
#     tres horas, y por encima de cinco minutos la interfaz ya dice la edad
#     exacta y pide confirmar el precio en la casa antes de apostar.
#
# Elegido por HMREY sobre la alternativa de 6 h. El equilibrio es: dentro de la
# ventana se sirve al instante y se revalida por detrás, así que la cuota vieja
# sólo la ve el primero que llega y sólo hasta que termina la revalidación.
CADUCIDAD_S = int(os.environ.get('CADUCIDAD_BARRIDO_S', 3 * 3600))
ARCHIVO = os.environ.get('CACHE_BARRIDO', '.cache_barrido.pkl')

_cerrojo = threading.Lock()
_cerrojo_disco = threading.Lock()
_cerrojo_revalida = threading.Lock()
_estado = {'ts': 0.0, 'datos': None, 'barridos': 0, 'esperas': 0,
           'servidos_de_disco': 0, 'revalidaciones': 0}
# Revalidación en vuelo. No es un contador: es la garantía de que cinco
# visitantes con caché rancia no lancen cinco barridos de 1,3 GB.
_revalidando = threading.Event()


def _fresco(ahora: float) -> bool:
    return _estado['datos'] is not None and ahora - _estado['ts'] < FRESCURA_S


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
# Pickle y no JSON a propósito: el barrido lleva `numpy.float64`, `Timestamp` y
# listas anidadas que `json.dump` no serializa sin un `default=str` que
# convertiría números en cadenas y rompería la aritmética río abajo. El fichero
# lo produce y lo consume este mismo proceso, así que no hay superficie de
# ataque: nunca se lee un pickle que no haya escrito la propia aplicación.
def _leer_disco():
    try:
        if not os.path.exists(ARCHIVO):
            return None, 0.0
        with open(ARCHIVO, 'rb') as f:
            sobre = pickle.load(f)
        return sobre.get('datos'), float(sobre.get('ts') or 0.0)
    except Exception as e:
        logger.debug(f"[guardia] cache de disco ilegible: {type(e).__name__}: {e}")
        return None, 0.0


def _escribir_disco(datos, ts: float) -> None:
    # Escritura atómica: un contenedor que muere a mitad de `pickle.dump` deja
    # un fichero truncado, y el siguiente arranque lo leería como caché válida.
    tmp = f'{ARCHIVO}.tmp'
    try:
        with _cerrojo_disco:
            with open(tmp, 'wb') as f:
                pickle.dump({'ts': ts, 'datos': datos}, f,
                            protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, ARCHIVO)
    except Exception as e:
        logger.debug(f"[guardia] no se pudo persistir el barrido: "
                     f"{type(e).__name__}: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass


def _sellar(datos, ts: float, ahora: float):
    """Adjunta la edad al resultado. La interfaz la necesita para avisar."""
    if isinstance(datos, dict):
        datos = dict(datos)
        edad = max(0.0, ahora - ts)
        datos['_frescura'] = {'edad_s': round(edad, 1),
                              'fresco': edad < FRESCURA_S,
                              'calculado_ts': ts}
    return datos


def _revalidar(calcular):
    """Recalcula en segundo plano y deja el resultado listo para el siguiente."""
    try:
        with _cerrojo:
            datos = calcular()
            ahora = time.time()
            _estado['datos'] = datos
            _estado['ts'] = ahora
            _estado['barridos'] += 1
        _escribir_disco(datos, ahora)
        logger.info('[guardia] revalidacion en segundo plano terminada')
    except Exception as e:
        logger.warning(f"[guardia] la revalidacion fallo: "
                       f"{type(e).__name__}: {e}")
    finally:
        _revalidando.clear()


def _lanzar_revalidacion(calcular) -> bool:
    """Arranca la revalidación si no hay ya una en vuelo. True si la arrancó."""
    # `is_set()` + `set()` no es atómico: dos visitantes que llegan a la vez
    # con la caché rancia pasarían los dos. El segundo se quedaría bloqueado en
    # `_cerrojo` dentro de `_revalidar` —así que la memoria nunca corre
    # peligro—, pero recalcularía el barrido entero justo después del primero.
    # El cerrojo convierte la comprobación en un test-and-set de verdad.
    with _cerrojo_revalida:
        if _revalidando.is_set():
            return False
        _revalidando.set()
        _estado['revalidaciones'] += 1
    threading.Thread(target=_revalidar, args=(calcular,),
                     name='revalida-barrido', daemon=True).start()
    return True


def barrido(calcular, forzar: bool = False):
    """
    Ejecuta `calcular()` garantizando que no se solape consigo mismo.

    `calcular` es una función sin argumentos (normalmente
    alpha_finder.apuestas_del_dia_universal). Se inyecta en vez de importarla
    aquí para poder probar este módulo sin pagar un barrido de 90 segundos.
    """
    entrada = time.time()
    if not forzar and _fresco(entrada):
        return _sellar(_estado['datos'], _estado['ts'], entrada)

    # v148 — el disco, ANTES del cerrojo.
    #
    # Va aquí y no dentro del `with` a propósito: si un barrido está corriendo,
    # el cerrojo está tomado y quien llega se quedaría esperando los 122 s
    # completos, que es justo lo que se quiere evitar. El disco se lee sin
    # cerrojo (es una lectura de unos milisegundos) y el que llega se va con
    # datos servibles mientras el otro termina.
    if not forzar and _estado['datos'] is None:
        datos_d, ts_d = _leer_disco()
        if datos_d is not None and entrada - ts_d < CADUCIDAD_S:
            _estado['datos'], _estado['ts'] = datos_d, ts_d
            _estado['servidos_de_disco'] += 1
            logger.info(f"[guardia] barrido servido de disco "
                        f"({entrada - ts_d:.0f} s de antiguedad)")

    if not forzar and _estado['datos'] is not None:
        edad = entrada - _estado['ts']
        if edad < FRESCURA_S:
            return _sellar(_estado['datos'], _estado['ts'], entrada)
        if edad < CADUCIDAD_S:
            # Rancio pero servible: se devuelve YA y se refresca por detrás.
            _lanzar_revalidacion(calcular)
            return _sellar(_estado['datos'], _estado['ts'], entrada)

    with _cerrojo:
        if time.time() - entrada > 0.01:
            _estado['esperas'] += 1
        # Otro hilo pudo calcularlo mientras esperábamos el cerrojo.
        #
        # El criterio no es sólo "¿hay algo fresco?", porque con forzar=True
        # (el botón "Actualizar ahora") siempre lo hay y nunca se recalcularía.
        # Es "¿alguien ha terminado un barrido DESPUÉS de que yo pidiera el
        # mío?": si sí, ese resultado ya satisface mi petición y me lo llevo;
        # si no, lo calculo yo. Así `forzar` recalcula de verdad, pero cinco
        # usuarios pulsando "Actualizar" a la vez siguen provocando un único
        # barrido en lugar de cinco de 1,3 GB cada uno.
        if _estado['datos'] is not None and _estado['ts'] > entrada:
            return _sellar(_estado['datos'], _estado['ts'], time.time())
        if not forzar and _fresco(time.time()):
            return _sellar(_estado['datos'], _estado['ts'], time.time())
        datos = calcular()
        ahora = time.time()
        _estado['datos'] = datos
        _estado['ts'] = ahora
        _estado['barridos'] += 1
    _escribir_disco(datos, ahora)
    return _sellar(datos, ahora, time.time())


def estadisticas() -> dict:
    """Para pruebas y diagnóstico: cuántos barridos reales y cuántas esperas."""
    return dict(_estado, datos=('si' if _estado['datos'] is not None else 'no'),
                revalidando=_revalidando.is_set())


def reiniciar(borrar_disco: bool = False) -> None:
    """Sólo para pruebas."""
    _estado.update(ts=0.0, datos=None, barridos=0, esperas=0,
                   servidos_de_disco=0, revalidaciones=0)
    _revalidando.clear()
    if borrar_disco:
        try:
            os.remove(ARCHIVO)
        except OSError:
            pass
