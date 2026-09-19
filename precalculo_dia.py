#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v220 — El día cocinado: separar el CÁLCULO del SERVICIO.

LA CAUSA RAÍZ QUE ESTO CIERRA
-----------------------------
La aplicación calculaba dentro del render. Todos los síntomas salían de ahí, y
el propio repositorio ya tenía el número escrito en `dashboard_ui`:

    «El barrido de alpha_finder pica a 1297,7 MB; dos a la vez, a 2172,2 MB»

Contra un techo de **1 GB** en Streamlit Community Cloud. No es un bug: es que
el pico no cabe. Con un usuario pasa a veces; con tres, siempre.

    ANTES                              AHORA
    -----                              -----
    usuario abre la app                cron (GitHub Actions)
      └─ importa xgboost                 └─ corre el barrido (pico 1,3 GB,
      └─ carga modelos                   │   pero en un runner de 7 GB)
      └─ CORRE EL BARRIDO  ← 1,3 GB      └─ escribe pronostico_dia.json
      └─ pinta                                   │
                                                 ▼
                                       usuario abre la app
                                         └─ LEE el JSON  ← ~10 MB
                                         └─ pinta

LO QUE HACE QUE ESTO SEA BARATO DE HACER
----------------------------------------
Que el resultado del barrido **ya es serializable a JSON tal cual**:
comprobado sobre el barrido real, 1,0 MB y cero tipos que no sean str, int,
float, bool, None, list o dict. No hace falta inventar un formato: se vuelca lo
mismo que ya viajaba en el pickle.

DÓNDE SE ENGANCHA, Y POR QUÉ AHÍ
--------------------------------
En `guardia_barrido.barrido()`, que es el único sitio por el que pasan TODOS
los consumidores —«Apuestas del Día», las combinadas, el bot de Telegram y la
exportación—. Engancharlo en la vista habría dejado a los otros tres
calculando.

EL INTERRUPTOR QUE DE VERDAD PONE EL TECHO
------------------------------------------
`SOLO_PRECALCULO=1` hace que la aplicación **no calcule nunca**: si no hay
precálculo, enseña el aviso en vez de levantar 1,3 GB. Es lo que se pone en
producción, y es la diferencia entre «normalmente no calcula» y «no puede
calcular». Sin ese pestillo, basta un día con el JSON viejo para que vuelva el
crash.

Uso:
    python precalculo_dia.py              # calcula y escribe el JSON
    python precalculo_dia.py --estado     # sólo dice qué hay
"""

import argparse
import datetime as _dt
import json
import logging
import os
import sys
import time
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('precalculo_dia')

FICHERO = os.environ.get('PRECALCULO_DIA', 'pronostico_dia.json')

# Cuánto se admite un precálculo antes de considerarlo inservible. Por encima
# de esto la aplicación lo dice en pantalla en vez de enseñarlo como si fuera
# de hoy: un pronóstico de ayer con cuotas de ayer no es un pronóstico.
CADUCIDAD_S = int(os.environ.get('PRECALCULO_CADUCIDAD_S', 6 * 3600))

# v221 — NO CALCULAR ES EL COMPORTAMIENTO POR DEFECTO, NO UNA OPCIÓN.
#
# La v220 dejó esto como una variable de entorno que había que ir a poner a
# mano en el despliegue. Estaba mal, y el usuario lo dijo con razón: «no quiero
# hacer cosas manuales ni estarlo cambiando a cada rato».
#
# Un interruptor que hay que acordarse de encender no protege de nada: protege
# los días que alguien se acordó. Y lo que hay detrás no es una preferencia
# —es que el barrido pica a 1,3 GB y el servidor tiene 1 GB—, así que la
# respuesta correcta no depende de la opinión de nadie.
#
# Ahora viene ENCENDIDO de fábrica. La variable sigue existiendo, pero para lo
# contrario: ponerla a 0 en una máquina de desarrollo, donde sí interesa que la
# aplicación calcule si falta el fichero.
_CRUDO = str(os.environ.get('SOLO_PRECALCULO', '')).strip().lower()
SOLO_PRECALCULO = _CRUDO not in ('0', 'false', 'no')

# Cuánto se sigue sirviendo un precálculo viejo ANTES de rendirse. Ver
# `guardia_barrido`: entre `CADUCIDAD_S` y esto se enseña igual, avisando de
# su edad, porque un pronóstico de hace ocho horas es muchísimo mejor que una
# pantalla vacía. Sólo por encima de aquí se deja de enseñar.
RESERVA_S = int(os.environ.get('PRECALCULO_RESERVA_S', 36 * 3600))


def _jsonable(o, prof: int = 0):
    """Deja el árbol en tipos que JSON entiende, sin romperse por uno raro.

    El barrido de hoy ya sale limpio —comprobado— pero esto es la red por si
    alguien mete mañana un `numpy.float64` o una fecha en cualquiera de los
    veintisiete campos. Convertir de más no cuesta nada; fallar al volcar
    dejaría a la aplicación sin precálculo y calculando a 1,3 GB.
    """
    if prof > 12:
        return None
    if o is None or isinstance(o, (str, bool, int, float)):
        return o
    if isinstance(o, dict):
        return {str(k): _jsonable(v, prof + 1) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_jsonable(v, prof + 1) for v in o]
    for attr in ('item', 'isoformat'):
        fn = getattr(o, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn(), prof + 1)
            except Exception:
                pass
    return str(o)


# ---------------------------------------------------------------------------
def construir() -> Dict:
    """Corre el barrido entero. Es lo caro, y por eso vive en el cron."""
    import alpha_finder
    t0 = time.time()
    datos = alpha_finder.apuestas_del_dia_universal()
    logger.info('barrido en %.0f s · %d pronósticos', time.time() - t0,
                len(datos.get('pronosticos') or []))
    return datos


def escribir(datos: Dict, ruta: Optional[str] = None) -> bool:
    """Vuelca el día cocinado, con su sello de tiempo."""
    ruta = _ruta(ruta)
    doc = {
        'version': 1,
        'generado_ts': time.time(),
        'generado': _dt.datetime.now(_dt.timezone.utc)
                       .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'datos': _jsonable(datos),
    }
    try:
        import io_atomico
        ok = bool(io_atomico.escribir_json(ruta, doc))
    except Exception as e:
        logger.warning('[precalculo] io_atomico falló (%s); se escribe directo', e)
        try:
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False)
            ok = True
        except Exception as e2:
            logger.error('[precalculo] no se pudo escribir %s: %s', ruta, e2)
            return False
    if ok:
        try:
            mb = os.path.getsize(ruta) / 1024 / 1024
            logger.info('escrito %s (%.2f MB)', ruta, mb)
        except Exception:
            pass
    return ok


def _ruta(ruta: Optional[str] = None) -> str:
    """La ruta efectiva, resuelta EN CADA LLAMADA.

    Escribir `def leer(ruta=FICHERO)` parece equivalente y no lo es: Python
    evalúa el valor por defecto UNA vez, al definir la función, así que
    cambiar `precalculo_dia.FICHERO` después —un test, otra ruta, una variable
    de entorno leída más tarde— no tenía ningún efecto. Lo cazaron tres tests
    de la v220 que apuntaban a un fichero inexistente y seguían leyendo el
    real.
    """
    return ruta or FICHERO


def leer(ruta: Optional[str] = None) -> Optional[Dict]:
    """El día cocinado, o None. Devuelve `{'datos', 'ts', 'edad_s'}`.

    Nunca lanza: si el fichero no está, está a medias o es de otro formato,
    devuelve None y quien llama decide. Un precálculo ilegible tiene que
    comportarse igual que uno ausente.
    """
    ruta = _ruta(ruta)
    try:
        if not os.path.exists(ruta):
            return None
        with open(ruta, encoding='utf-8') as f:
            doc = json.load(f)
        if not isinstance(doc, dict) or not isinstance(doc.get('datos'), dict):
            logger.warning('[precalculo] %s no tiene la forma esperada', ruta)
            return None
        ts = float(doc.get('generado_ts') or 0.0)
        return {'datos': doc['datos'], 'ts': ts,
                'edad_s': max(0.0, time.time() - ts),
                'generado': doc.get('generado')}
    except Exception as e:
        logger.warning('[precalculo] no se pudo leer %s: %s', ruta, e)
        return None


def fresco(ruta: Optional[str] = None,
           caducidad_s: Optional[float] = None) -> bool:
    d = leer(ruta)
    if d is None:
        return False
    tope = CADUCIDAD_S if caducidad_s is None else caducidad_s
    return d['edad_s'] < tope


def estado(ruta: Optional[str] = None) -> Dict:
    """Qué hay, de cuándo y si sirve. Para la pantalla y para el cron."""
    d = leer(ruta)
    if d is None:
        return {'hay': False, 'solo_precalculo': SOLO_PRECALCULO,
                'motivo': 'no hay precálculo en disco'}
    dat = d['datos']
    return {
        'hay': True,
        'generado': d.get('generado'),
        'edad_min': round(d['edad_s'] / 60.0, 1),
        'fresco': d['edad_s'] < CADUCIDAD_S,
        'caducidad_h': round(CADUCIDAD_S / 3600.0, 1),
        'solo_precalculo': SOLO_PRECALCULO,
        'pronosticos': len(dat.get('pronosticos') or []),
        'seccion1': len(dat.get('seccion1') or []),
        'seccion2': len(dat.get('seccion2') or []),
        'actualizado': dat.get('actualizado'),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--estado', action='store_true')
    ap.add_argument('--salida', default=FICHERO)
    a = ap.parse_args()

    if a.estado:
        print(json.dumps(estado(a.salida), ensure_ascii=False, indent=1))
        return 0

    datos = construir()

    # v222 — SE ARCHIVA EL CONTEXTO AQUÍ, Y NO EN LA PANTALLA.
    #
    # `archivo_contexto` existía desde la v217 con CERO importadores: escrito,
    # probado y sin enchufar — el mismo patrón que este proyecto lleva
    # señalando en `filtro_contexto` y `ventaja_ponches`. Lo cazó la propia
    # auditoría en cuanto se le quitó el punto ciego del `__main__`.
    #
    # El sitio correcto es el cron y no la vista, por dos motivos: consultar
    # bajas sale a la red (justo lo que la v220 sacó del render) y esto tiene
    # que correr aunque nadie abra la aplicación — si sólo se archivara al
    # mirar, los días que no entras se pierden.
    #
    # Falla en blando a propósito: un archivo de contexto incompleto es un
    # problema de mañana; no escribir el precálculo es un problema de ahora.
    try:
        import archivo_contexto as _arc
        _res = _arc.archivar_del_barrido(
            (datos.get('pronosticos') or [])[:400], con_contexto=True)
        logger.info('contexto archivado: %d nuevos, %d ya estaban',
                    _res.get('archivados', 0), _res.get('saltados', 0))
    except Exception as e:
        logger.warning('[precalculo] no se pudo archivar el contexto: %s', e)

    if not datos or not datos.get('pronosticos'):
        logger.error('el barrido salió vacío: NO se escribe el precálculo')
        # Escribir un día vacío sería peor que no escribirlo: la aplicación
        # lo serviría como si fuera el día de hoy.
        return 1
    if not escribir(datos, a.salida):
        return 1
    print(json.dumps(estado(a.salida), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
