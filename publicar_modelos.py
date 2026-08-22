#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v148 — Publica los pesos entrenados como assets de un GitHub Release.

Es la otra mitad de `modelos_remotos.py`: aquel BAJA, éste SUBE. Lo ejecuta el
workflow de reentrenamiento justo después de entrenar y de verificar que los
modelos cargan, y antes del commit.

POR QUÉ UN RELEASE Y NO UNA RAMA
--------------------------------
Los assets de un Release no viven en la historia del repositorio: reemplazar
uno no añade nada al `.git`. Una rama huérfana forzada haría lo mismo con la
historia, pero obligaría a la aplicación a hablar git en tiempo de ejecución;
un asset se baja con una petición HTTPS normal contra una URL pública y
estable.

POR QUÉ UNO POR COMPETICIÓN
---------------------------
712 MB en un solo tarball serían minutos de arranque. Uno por competición
(mediana 12 MB) deja que la aplicación baje sólo lo que va a usar: en un
barrido típico hay fixtures en unas 16 de las 57, así que se mueven ~200 MB
en vez de 712, y en paralelo.

ETIQUETA FIJA, NO UNA POR DÍA
-----------------------------
`modelos-latest` se reutiliza y los assets se reemplazan con `--clobber`. Un
Release por día llenaría la pestaña de Releases de ruido y habría que ir
borrando los viejos para no acumular; con etiqueta fija no hay nada que
limpiar y la URL que usa la aplicación no cambia nunca.

    python publicar_modelos.py            # empaqueta y sube todo
    python publicar_modelos.py --verificar # además, se lo baja y lo carga
"""

import argparse
import glob
import hashlib
import json
import logging
import os
import subprocess
import sys
import tarfile
import tempfile

logger = logging.getLogger('publicar_modelos')

REPO = os.environ.get('REPO_MODELOS', 'HectorMontiel/mundial-2026-predictor')
ETIQUETA = os.environ.get('RELEASE_MODELOS', 'modelos-latest')
RAIZ = 'modelos'


def competiciones() -> list:
    """Subcarpetas de `modelos/` con artefactos dentro."""
    salida = []
    for d in sorted(glob.glob(os.path.join(RAIZ, '*'))):
        if not os.path.isdir(d):
            continue
        if any(f.endswith(('.joblib', '.json'))
               for f in os.listdir(d)):
            salida.append(os.path.basename(d))
    return salida


def empaquetar(clave: str, destino: str) -> str:
    """Un `.tar.gz` con el CONTENIDO de la carpeta, sin el nivel del nombre.

    Plano a propósito: `modelos_remotos` extrae sobre un directorio temporal y
    lo renombra a `modelos/<clave>`, así que el tar no debe repetir el nivel.
    """
    ruta = os.path.join(destino, f'modelos-{clave}.tar.gz')
    origen = os.path.join(RAIZ, clave)
    with tarfile.open(ruta, 'w:gz') as tar:
        for nombre in sorted(os.listdir(origen)):
            tar.add(os.path.join(origen, nombre), arcname=nombre)
    return ruta


def _gh(*args, comprobar=True):
    r = subprocess.run(['gh', *args], capture_output=True, text=True)
    if comprobar and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} -> {r.returncode}: "
                           f"{(r.stderr or r.stdout).strip()[:300]}")
    return r


def asegurar_release() -> None:
    r = _gh('release', 'view', ETIQUETA, '--repo', REPO, comprobar=False)
    if r.returncode == 0:
        return
    logger.info(f'creando el Release «{ETIQUETA}»')
    _gh('release', 'create', ETIQUETA, '--repo', REPO,
        '--title', 'Modelos entrenados (última versión)',
        '--notes', 'Pesos entrenados por el bot de reentrenamiento. '
                   'Se reemplazan en cada ejecución; esta etiqueta siempre '
                   'apunta a los últimos. La aplicación los descarga bajo '
                   'demanda (ver modelos_remotos.py).',
        '--latest=false')


# v153 — SÓLO SE SUBE LO QUE CAMBIÓ, Y ESTO NO ES UNA OPTIMIZACIÓN: ES LO QUE
# IMPEDÍA QUE LOS DATOS LLEGARAN A LA APLICACIÓN.
#
# Medido sobre la ejecución del 2026-08-22 (run 32555539614): el job arrancó a
# las 05:54, terminó de reentrenar hacia las 06:20 y se pasó **34 minutos**
# subiendo assets. Lo cancelaron por tiempo en el asset 40 de 54, y como el paso
# que commitea los CSV va DESPUÉS, el día entero se perdió — el runner ya tenía
# la J1 con sus partidos del 21 a las 06:11 y nunca llegaron a `main`. El día
# anterior el mismo workflow terminó en failure.
#
# Reentrenar una competición con diez partidos nuevos sobre seis mil produce un
# modelo casi idéntico, pero sus bytes cambian enteros. Lo que no cambia nada es
# una competición EN RECESO: sus ficheros son idénticos y se re-subían igual.
#
# EL HASH ES DEL CONTENIDO, NO DEL .tar.gz. gzip escribe la marca de tiempo en
# la cabecera, así que dos tar del mismo contenido nunca son iguales byte a
# byte y comparar el paquete no serviría de nada.
MANIFIESTO = 'modelos_publicados.json'


def _hash_carpeta(clave: str) -> str:
    """sha256 del CONTENIDO de `modelos/<clave>`, estable entre ejecuciones."""
    h = hashlib.sha256()
    origen = os.path.join(RAIZ, clave)
    for nombre in sorted(os.listdir(origen)):
        ruta = os.path.join(origen, nombre)
        if not os.path.isfile(ruta):
            continue
        h.update(nombre.encode('utf-8'))
        with open(ruta, 'rb') as f:
            for bloque in iter(lambda: f.read(1 << 20), b''):
                h.update(bloque)
    return h.hexdigest()


def _assets_publicados() -> set:
    """
    Qué assets existen HOY en el Release.

    Se consulta de verdad y no se confía sólo en el manifiesto: si alguien borra
    un asset a mano, su hash seguiría en el manifiesto y esa competición se
    quedaría sin pesos para siempre. Con las dos comprobaciones, para saltarse
    una subida tienen que coincidir las dos cosas.
    """
    r = _gh('release', 'view', ETIQUETA, '--repo', REPO,
            '--json', 'assets', comprobar=False)
    if r.returncode != 0:
        return set()
    try:
        datos = json.loads(r.stdout or '{}')
        return {a.get('name') for a in (datos.get('assets') or [])}
    except Exception:
        return set()


def _manifiesto_previo(tmp: str) -> dict:
    """El manifiesto de la última publicación, bajado del propio Release."""
    destino = os.path.join(tmp, MANIFIESTO)
    r = _gh('release', 'download', ETIQUETA, '--repo', REPO,
            '--pattern', MANIFIESTO, '--dir', tmp, comprobar=False)
    if r.returncode != 0 or not os.path.exists(destino):
        return {}
    try:
        with open(destino, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def publicar(claves=None, verificar=False, forzar=False) -> int:
    claves = claves or competiciones()
    if not claves:
        logger.error('no hay nada en modelos/ que publicar')
        return 1
    asegurar_release()
    fallos, subidas, saltadas = [], [], []
    with tempfile.TemporaryDirectory(prefix='pub_modelos_') as tmp:
        previo = {} if forzar else _manifiesto_previo(tmp)
        existentes = set() if forzar else _assets_publicados()
        nuevo = dict(previo)
        for i, clave in enumerate(claves, 1):
            try:
                firma = _hash_carpeta(clave)
                nombre_asset = f'modelos-{clave}.tar.gz'
                if (not forzar and previo.get(clave) == firma
                        and nombre_asset in existentes):
                    saltadas.append(clave)
                    logger.info(f'[{i}/{len(claves)}] {clave}: sin cambios, '
                                f'no se re-sube')
                    continue
                paquete = empaquetar(clave, tmp)
                mb = os.path.getsize(paquete) / 1e6
                _gh('release', 'upload', ETIQUETA, paquete,
                    '--repo', REPO, '--clobber')
                logger.info(f'[{i}/{len(claves)}] {clave}: {mb:.1f} MB subidos')
                os.remove(paquete)
                nuevo[clave] = firma
                subidas.append(clave)
            except Exception as e:
                logger.error(f'{clave}: {type(e).__name__}: {e}')
                fallos.append(clave)
                nuevo.pop(clave, None)   # que el próximo intento lo reintente
        # El manifiesto se sube SIEMPRE que algo haya cambiado, y al final: si
        # el job muere a mitad, el manifiesto viejo sigue describiendo lo que de
        # verdad hay publicado, y la próxima ejecución vuelve a subir lo que
        # falte. Nunca deja constancia de una subida que no ocurrió.
        if subidas or fallos:
            try:
                ruta_m = os.path.join(tmp, MANIFIESTO)
                with open(ruta_m, 'w', encoding='utf-8') as f:
                    json.dump(nuevo, f, indent=1, sort_keys=True)
                _gh('release', 'upload', ETIQUETA, ruta_m,
                    '--repo', REPO, '--clobber')
            except Exception as e:
                logger.warning(f'no se pudo actualizar el manifiesto: {e}')
    if fallos:
        logger.error(f'{len(fallos)} competiciones sin publicar: {fallos}')
        return 1
    logger.info(f'{len(subidas)} subidas, {len(saltadas)} sin cambios, '
                f'de {len(claves)} competiciones en «{ETIQUETA}»')
    if verificar:
        # Se verifica lo que se SUBIÓ. Verificar las saltadas sería bajarse 50
        # tar.gz para comprobar que siguen igual que ayer, y ese viaje de ida y
        # vuelta es justo el tiempo que este cambio venía a recuperar.
        return verificacion_ida_y_vuelta(subidas) if subidas else 0
    return 0


def verificacion_ida_y_vuelta(claves) -> int:
    """
    Se baja lo que se acaba de subir y comprueba que carga.

    Es el paso que hace seguro dejar de versionar `modelos/`: mientras esto no
    pase, los pesos siguen viajando en el repositorio y nada depende del
    Release. Es la misma disciplina que la v68 aplicó al commit de modelos —
    nunca se publica un artefacto que no se haya vuelto a abrir.
    """
    import modelos_remotos as mr
    muestra = list(claves)[:3]
    malos = []
    # La verificación baja a un directorio APARTE, nunca sobre `modelos/`.
    #
    # La primera versión de esto apartaba la carpeta real con `os.rename` y la
    # devolvía en un `finally`. Funciona… salvo si el proceso muere en medio
    # (el workflow tiene tope de 60 minutos): la carpeta se quedaría fuera de
    # sitio y el `git add -A` del final del job la habría borrado del
    # repositorio. Comprobar que la publicación va bien no puede poner en
    # riesgo lo que se está publicando.
    with tempfile.TemporaryDirectory(prefix='verifica_modelos_') as tmp:
        raiz_real = mr.RAIZ
        mr.RAIZ = tmp
        try:
            for clave in muestra:
                try:
                    mr.olvidar(clave)
                    if not mr.asegurar(clave):
                        malos.append((clave, 'no se pudo descargar'))
                        continue
                    import modelos_portables as mp
                    ruta = os.path.join(tmp, clave, 'modelo.joblib')
                    if not os.path.exists(ruta):
                        # Los motores de deporte no se llaman `modelo.joblib`;
                        # basta con que el asset traiga artefactos.
                        if not os.listdir(os.path.join(tmp, clave)):
                            raise RuntimeError('el asset venía vacío')
                    else:
                        mp.cargar(ruta)
                    logger.info(f'verificado: {clave} baja del Release y carga')
                except Exception as e:
                    malos.append((clave, f'{type(e).__name__}: {e}'))
                finally:
                    mr.olvidar(clave)
        finally:
            mr.RAIZ = raiz_real
    if malos:
        for c, m in malos:
            logger.error(f'VERIFICACIÓN FALLIDA {c}: {m}')
        return 1
    logger.info(f'verificación de ida y vuelta OK sobre {len(muestra)} '
                f'competiciones')
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('claves', nargs='*', help='competiciones (por defecto, todas)')
    ap.add_argument('--verificar', action='store_true',
                    help='baja del Release una muestra y comprueba que carga')
    ap.add_argument('--forzar', action='store_true',
                    help='re-sube TODO, ignorando el manifiesto de la última '
                         'publicación. Para cuando se sospeche que el Release '
                         'quedó descuadrado.')
    a = ap.parse_args()
    sys.exit(publicar(a.claves or None, verificar=a.verificar,
                      forzar=a.forzar))
