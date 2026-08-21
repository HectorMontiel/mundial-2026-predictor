#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v148 — Los pesos entrenados dejan de vivir en la historia de git.

EL PROBLEMA, MEDIDO
-------------------
    .git                       15 GB
    modelos/ (árbol de trabajo) 712 MB · 246 ficheros .joblib
    commits del bot                23
    15 GB / 23 ≈ 650 MB por commit

Cada madrugada el bot reentrena las 57 competiciones y commitea los 246
`.joblib`. Un `RandomForest` reentrenado con diez partidos nuevos sobre seis
mil predice prácticamente lo mismo, pero sus 20 MB de bytes cambian ENTEROS:
git no puede delta-comprimir un binario comprimido, así que guarda una copia
nueva completa. O sea, 650 MB diarios de historia para casi ninguna
información. A ese ritmo el repositorio crece ~19 GB al mes y el `fetch`
tarda más de diez minutos.

LO QUE **NO** ERA LA SOLUCIÓN, Y POR QUÉ (medido)
-------------------------------------------------
  · **Comprimir mejor.** Se midió sobre `modelos/liga_mx/modelo.joblib`:

        zlib-3 (actual)  7,07 MB · dump 0,7 s · load 0,35 s
        zlib-9           6,62 MB · dump 4,9 s
        lzma-3           5,62 MB · dump 7,6 s
        xz-6             5,16 MB · dump 9,7 s

    El mejor caso ahorra un 27 % a cambio de multiplicar por catorce el
    tiempo de guardado, y **no toca el problema**: 650 MB diarios pasarían a
    475 MB diarios. Se descarta.

  · **Adelgazar el modelo.** El 65 % del fichero es el `RandomForest` del
    ensemble (4,56 de 7,07 MB). Recortarlo cambia el modelo, y las ventanas y
    familias de este proyecto están MEDIDAS liga por liga. No se toca un
    modelo para ahorrar disco.

  · **Entrenar al arrancar** (Opción 1 del encargo). Medido en esta máquina:
    el reentrenamiento completo tarda del orden de veinte minutos. Streamlit
    Cloud duerme y despierta el contenedor constantemente, así que eso serían
    veinte minutos de pantalla en blanco en cada arranque — lo contrario de lo
    que pide la Parte 1. Se descarta.

LA SOLUCIÓN
-----------
El peso de un modelo no es historia: es un ARTEFACTO, y el sitio de un
artefacto no es el árbol de git. Los `.joblib` se publican como **assets de
un GitHub Release** de etiqueta fija (`modelos-latest`), que el bot reemplaza
cada día. Los assets de un Release **no viven en la historia del repositorio**:
sustituirlos no añade un solo byte al `.git`. Es gratis en el plan libre
(2 GB por asset, sin límite práctico de número) y no depende de ningún
servicio externo — el repositorio ya está en GitHub.

Y **un asset por competición**, no un único tarball de 712 MB. Ésa es la
diferencia entre un arranque de minutos y uno de segundos: la aplicación sólo
baja el modelo de la liga que de verdad va a usar, cuando lo va a usar. La
mediana es de 12 MB por competición y el máximo 22 MB.

CÓMO DEGRADA
------------
Este módulo NO es obligatorio. `asegurar()` mira primero el disco: si la
carpeta está (clon de desarrollo, o ya descargada en este contenedor), no
toca la red. Si no hay Release publicado todavía, devuelve False sin ruido y
`ClubEngine` informa de su error de siempre. Nada de lo que había deja de
funcionar por que esto falle.
"""

import logging
import os
import shutil
import tarfile
import tempfile
import threading

logger = logging.getLogger(__name__)

# El repositorio real del proyecto. `HMREY/...` es un fork viejo.
REPO = os.environ.get('REPO_MODELOS', 'HectorMontiel/mundial-2026-predictor')
ETIQUETA = os.environ.get('RELEASE_MODELOS', 'modelos-latest')
RAIZ = 'modelos'
TIMEOUT_S = float(os.environ.get('TIMEOUT_MODELOS', '120'))

# Un cerrojo por competición. El barrido predice en varias hebras y sin esto
# dos de ellas descargarían y extraerían el mismo tar a la vez, sobre el mismo
# directorio destino.
_cerrojos: dict = {}
_cerrojo_maestro = threading.Lock()
# Competiciones ya resueltas en este proceso (con éxito o sin él). Sin esto,
# una liga sin asset publicado pediría la red en cada predicción.
_resueltas: dict = {}


def url_asset(clave: str) -> str:
    return (f'https://github.com/{REPO}/releases/download/{ETIQUETA}/'
            f'modelos-{clave}.tar.gz')


def _cerrojo_de(clave: str) -> threading.Lock:
    with _cerrojo_maestro:
        return _cerrojos.setdefault(clave, threading.Lock())


def local_completo(clave: str) -> bool:
    """¿Está la carpeta de la competición con algo dentro?"""
    d = os.path.join(RAIZ, clave)
    try:
        return os.path.isdir(d) and any(
            f.endswith(('.joblib', '.json')) for f in os.listdir(d))
    except OSError:
        return False


def _descargar(clave: str) -> bool:
    import requests
    url = url_asset(clave)
    try:
        r = requests.get(url, timeout=TIMEOUT_S, stream=True)
    except Exception as e:
        logger.warning(f"[modelos] {clave}: no se pudo pedir el asset "
                       f"({type(e).__name__}: {e})")
        return False
    if r.status_code == 404:
        logger.info(f"[modelos] {clave}: aún no hay asset publicado en "
                    f"«{ETIQUETA}»")
        return False
    if r.status_code != 200:
        logger.warning(f"[modelos] {clave}: HTTP {r.status_code} al bajar "
                       f"el asset")
        return False

    os.makedirs(RAIZ, exist_ok=True)
    tmp_tar = None
    tmp_dir = tempfile.mkdtemp(prefix=f'mdl_{clave}_', dir=RAIZ)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz',
                                         dir=RAIZ) as f:
            tmp_tar = f.name
            for trozo in r.iter_content(chunk_size=1 << 20):
                if trozo:
                    f.write(trozo)
        with tarfile.open(tmp_tar, 'r:gz') as tar:
            # El tar lo produce `publicar_modelos.py` con rutas relativas y
            # planas, pero se comprueba igual: un tar con `..` o rutas
            # absolutas escribiría fuera del destino.
            for m in tar.getmembers():
                if m.name.startswith(('/', '\\')) or '..' in m.name.split('/'):
                    raise ValueError(f'ruta insegura en el tar: {m.name}')
            tar.extractall(tmp_dir)
        destino = os.path.join(RAIZ, clave)
        # `os.replace` sobre un directorio falla si el destino existe y no
        # está vacío, así que se aparta primero lo que hubiera.
        if os.path.isdir(destino):
            shutil.rmtree(destino, ignore_errors=True)
        os.replace(tmp_dir, destino)
        tmp_dir = None
        n = len(os.listdir(destino))
        logger.info(f"[modelos] {clave}: descargado del Release ({n} ficheros)")
        return True
    except Exception as e:
        logger.warning(f"[modelos] {clave}: el asset no se pudo extraer "
                       f"({type(e).__name__}: {e})")
        return False
    finally:
        for ruta, borrar in ((tmp_tar, os.remove),
                             (tmp_dir, lambda d: shutil.rmtree(d, ignore_errors=True))):
            if ruta:
                try:
                    borrar(ruta)
                except OSError:
                    pass


def asegurar(clave: str) -> bool:
    """
    Garantiza que `modelos/<clave>/` existe en disco. True si está utilizable.

    Barata y reentrante: si la carpeta ya está, no toca la red ni el cerrojo.
    """
    if local_completo(clave):
        return True
    if clave in _resueltas:
        return _resueltas[clave]
    with _cerrojo_de(clave):
        if local_completo(clave):          # otra hebra la trajo mientras
            return True
        if clave in _resueltas:
            return _resueltas[clave]
        ok = _descargar(clave)
        _resueltas[clave] = ok
        return ok


def olvidar(clave: str = None) -> None:
    """Sólo para pruebas: vuelve a permitir el intento de descarga."""
    if clave is None:
        _resueltas.clear()
    else:
        _resueltas.pop(clave, None)
