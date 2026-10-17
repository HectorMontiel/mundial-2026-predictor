#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v312 — PUBLICAR DESDE LOS WORKFLOWS SIN DEJAR NUNCA UN FICHERO A MEDIO FUNDIR.

EL FALLO, CON SU CAUSA (el usuario: «ya van varias veces que sale»)
`Reentrenar modelos de ligas` falló el 24, 25, 27 y 28 de septiembre, siempre
igual, al final de ~1 h de trabajo:

    error: Committing is not possible because you have unmerged files.
    U	lineas_jugador_hist/2026-09.csv

El fichero lo escriben DOS bots (el precálculo, cada ~1,6 h, y el
reentrenamiento, con `lineas_jugador.py --dias 2`). A mitad del job, el paso
«Guardar históricos» hace push; si otro bot empujó antes, reintenta con
`git pull --rebase --autostash || true`. El autostash aparta el CSV sin
guardar, rebasa y al devolverlo CHOCA con la versión del otro bot: queda en
estado «U», y el `|| true` se lo traga. Media hora después el paso final
intenta commitear y muere con exit 128. Sólo pasa los días en que coincide
con otro bot: por eso «a veces».

`precalculo_dia.yml` y `recalibrar.yml` tenían el mismo `|| true` esperando
su turno.

EL ARREGLO
Un solo sitio que sabe resolver, usado por los tres workflows:

  · CSV de histórico (sólo crecen): se UNEN las filas de las dos versiones,
    sin duplicados y con la cabecera una vez. Ninguna fila se pierde, que es
    lo que importa en `lineas_jugador_hist/` (no se puede volver a bajar).
  · cualquier otro artefacto: gana la versión RECIÉN GENERADA (la del job).
  · código (`*.py`, `.github/`): no se toca nunca; se aborta y se avisa.

Y NUNCA queda un fichero en estado «U»: si algo no se puede resolver, se
restaura el lado limpio y se avisa, en vez de envenenar el paso siguiente.

Uso (desde los workflows):
    python git_sin_conflictos.py resolver       # deja el árbol sin «U»
    python git_sin_conflictos.py sincronizar    # fetch + rebase + resolver
    python git_sin_conflictos.py publicar       # push con reintentos
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional

INTENTOS = 5


def _git(*args, check=False, capturar=True) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], text=True, check=check,
                          capture_output=capturar, encoding='utf-8',
                          errors='replace')


def _aviso(msg: str) -> None:
    print('::warning::' + msg, flush=True)


def sin_fundir() -> List[str]:
    r = _git('diff', '--name-only', '--diff-filter=U')
    return [l.strip() for l in (r.stdout or '').splitlines() if l.strip()]


def es_codigo(ruta: str) -> bool:
    return ruta.endswith('.py') or ruta.startswith('.github/')


def _lado(ruta: str, etapa: int) -> Optional[bytes]:
    """El contenido de `ruta` en la etapa 2 (lo de arriba: main) o 3 (lo
    recién generado por este job), EN BYTES. None si ese lado no existe.

    v393: antes se leía como texto con errors='replace'; un `.csv.gz` se
    convertía en basura (bytes EF BF BD) y se guardaba así. Pasó el 12-oct
    con 34 ficheros de `stats_espn/`, y al día siguiente el reentrenamiento,
    al no poder leerlos, los reescribió con sólo los últimos 10 días: la
    Liga MX se quedó con 9 partidos con córners de los 1.837 que tenía."""
    r = subprocess.run(['git', 'show', ':%d:%s' % (etapa, ruta)],
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _texto(b: Optional[bytes]) -> Optional[str]:
    return None if b is None else b.decode('utf-8', errors='replace')


def _gz_texto(b: Optional[bytes]) -> Optional[str]:
    """El CSV de dentro de un `.csv.gz`; None si no existe o está roto (un
    lado roto no cuenta: se queda el otro entero)."""
    if b is None:
        return None
    import gzip
    try:
        return gzip.decompress(b).decode('utf-8')
    except Exception:
        _aviso('un lado del .csv.gz no se puede leer: se ignora')
        return None


def fundir(ruta: str, arriba: Optional[bytes], nuevo: Optional[bytes]):
    """(contenido en bytes o None, cómo). Nunca pasa un binario por texto."""
    if ruta.endswith('.csv'):
        a, b = _texto(arriba), _texto(nuevo)
        if a is None and b is None:
            return None, 'borrado'
        return unir_csv(a, b).encode('utf-8'), 'filas unidas'
    if ruta.endswith('.csv.gz'):
        import gzip
        a, b = _gz_texto(arriba), _gz_texto(nuevo)
        if a is None and b is None:
            return (nuevo if nuevo is not None else arriba), 'versión recién generada'
        return gzip.compress(unir_csv(a, b).encode('utf-8'), mtime=0), 'filas unidas (gz)'
    return (nuevo if nuevo is not None else arriba), 'versión recién generada'


def unir_csv(a: Optional[str], b: Optional[str]) -> str:
    """Las filas de las dos versiones, en orden, sin repetir, cabecera una
    vez. Si las cabeceras no coinciden, gana la recién generada entera."""
    la = (a or '').splitlines()
    lb = (b or '').splitlines()
    if not la:
        return (b or '')
    if not lb:
        return (a or '')
    if la[0].strip() != lb[0].strip():
        return b or ''
    vistos, fuera = set(), [lb[0]]
    for linea in la[1:] + lb[1:]:
        k = linea.rstrip('\r')
        if not k or k in vistos:
            continue
        vistos.add(k)
        fuera.append(linea)
    return '\n'.join(fuera) + '\n'


def resolver() -> int:
    """Resuelve todo lo que esté en «U». Devuelve cuántos resolvió; -1 si
    había código en conflicto (no se toca y se restaura el lado de main)."""
    rutas = sin_fundir()
    if not rutas:
        return 0
    n, codigo = 0, False
    for ruta in rutas:
        if es_codigo(ruta):
            codigo = True
            _aviso('conflicto en CÓDIGO (%s): se deja la versión de main' % ruta)
            _git('checkout', '--ours', '--', ruta)
            _git('add', '--', ruta)
            continue
        contenido, como = fundir(ruta, _lado(ruta, 2), _lado(ruta, 3))
        if contenido is None:
            _git('rm', '-q', '-f', '--', ruta)
        else:
            os.makedirs(os.path.dirname(ruta) or '.', exist_ok=True)
            with open(ruta, 'wb') as f:
                f.write(contenido)
            _git('add', '--', ruta)
        print('resuelto %s: %s' % (ruta, como), flush=True)
        n += 1
    if _en_rebase():
        return -1 if codigo else n
    # Conflicto al DEVOLVER el autostash: el rebase terminó y lo que queda
    # son cambios sin commitear. Se sacan del índice (siguen en el árbol,
    # que es donde estaban) y se tira la copia del stash, que ya se aplicó.
    _git('reset', '-q')
    if _git('stash', 'list').stdout.strip():
        _git('stash', 'drop', '-q')
    return -1 if codigo else n


def _en_rebase() -> bool:
    g = _git('rev-parse', '--git-dir').stdout.strip() or '.git'
    return (os.path.isdir(os.path.join(g, 'rebase-merge'))
            or os.path.isdir(os.path.join(g, 'rebase-apply')))


def sincronizar() -> bool:
    """Trae main y pone encima lo de este job sin dejar nada a medio fundir.
    True si quedó rebasado; False si hubo que abortar (código en conflicto)."""
    _git('fetch', 'origin', 'main')
    r = _git('rebase', '--autostash', 'origin/main')
    for _ in range(20):                       # un rebase puede parar varias veces
        if not _en_rebase():
            break
        res = resolver()
        if res < 0:
            _git('rebase', '--abort')
            return False
        env = dict(os.environ, GIT_EDITOR='true')
        c = subprocess.run(['git', 'rebase', '--continue'], text=True,
                           capture_output=True, env=env)
        if c.returncode != 0 and not sin_fundir() and _en_rebase():
            # «nada que commitear» en este paso: se salta
            _git('rebase', '--skip')
    if _en_rebase():
        _git('rebase', '--abort')
        return False
    resolver()                                # el autostash devuelto
    if sin_fundir():                          # imposible, pero nunca «U»
        _git('reset', '-q', '--merge')
    return r.returncode == 0 or not sin_fundir()


def publicar() -> int:
    for intento in range(1, INTENTOS + 1):
        if _git('push', capturar=False).returncode == 0:
            print('publicado (intento %d)' % intento, flush=True)
            return 0
        print('push rechazado (intento %d): se sincroniza con main' % intento,
              flush=True)
        if not sincronizar():
            _aviso('conflicto de código con main: no se publica en esta '
                   'ejecución; lo hará la siguiente')
            return 0
    _aviso('no se pudo publicar tras %d intentos' % INTENTOS)
    return 1


def main(argv: List[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    orden = argv[1] if len(argv) > 1 else ''
    if orden == 'resolver':
        n = resolver()
        print('conflictos resueltos: %d' % max(n, 0), flush=True)
        return 0
    if orden == 'sincronizar':
        sincronizar()
        return 0
    if orden == 'publicar':
        return publicar()
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
