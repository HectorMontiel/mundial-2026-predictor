#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la recarga de módulos al desplegar (v303).

El 2026-09-23 producción servía `dia_picks`, `modo_modelo` y `escalera` de
la versión ANTERIOR tras el despliegue: Streamlit Cloud no reinicia el
proceso y `sys.modules` sobrevive. Lo que se vigila:

  · UN PROCESO VIEJO SE PONE AL DÍA la primera vez: todo lo del proyecto que
    ya estuviera importado se recarga.
  · DESPUÉS, SÓLO LO QUE CAMBIA: un fichero con fecha nueva se recarga y uno
    intacto no (recargar todo en cada pasada costaría segundos por clic).
  · NUNCA TOCA LO DE FUERA del proyecto.
  · `app.py` lo llama ANTES de ejecutar la pantalla.

Ejecutar:  python test_recarga.py
"""
import importlib
import os
import sys
import tempfile
import time

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def main():
    import recarga_modulos as rm
    d = tempfile.mkdtemp()
    ruta = os.path.join(d, 'modulo_de_prueba_v303.py')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('VALOR = 1\n')
    sys.path.insert(0, d)
    importlib.invalidate_caches()
    import modulo_de_prueba_v303 as m
    check(m.VALOR == 1, 'el módulo de prueba carga')

    # el fichero cambia «por un despliegue» ANTES de la primera pasada
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('VALOR = 2\n')
    # un `git pull` deja fecha nueva; sin ella Python reusaría el .pyc (se
    # valida por fecha y tamaño, y aquí el tamaño es el mismo)
    t = time.time() + 2
    os.utime(ruta, (t, t))
    rm._ESTRENADO.clear()
    rm._VISTOS.clear()
    hechos = rm.recargar_cambiados(raiz=d)
    m2 = sys.modules['modulo_de_prueba_v303']
    check('modulo_de_prueba_v303' in hechos and m2.VALOR == 2,
          'la primera pasada pone al día un proceso viejo (%s)' % hechos)
    check('pandas' not in hechos and 'streamlit' not in hechos,
          'y no toca nada de fuera del proyecto')

    hechos = rm.recargar_cambiados(raiz=d)
    check(hechos == [], 'sin cambios, no recarga nada (%s)' % hechos)

    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('VALOR = 3\n')
    t = time.time() + 5
    os.utime(ruta, (t, t))
    hechos = rm.recargar_cambiados(raiz=d)
    check(hechos == ['modulo_de_prueba_v303']
          and sys.modules['modulo_de_prueba_v303'].VALOR == 3,
          'un fichero con fecha nueva se recarga, y sólo él (%s)' % hechos)

    # un módulo que ya no compila no tumba la pasada
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('VALOR = (\n')
    t = time.time() + 10
    os.utime(ruta, (t, t))
    try:
        rm.recargar_cambiados(raiz=d)
        check(True, 'un módulo roto no hace lanzar la recarga')
    except Exception as e:
        check(False, 'lanzó con un módulo roto: %s' % e)

    src = open('app.py', encoding='utf-8').read()
    i = src.find('recargar_cambiados()')
    j = src.find('runpy.run_path')
    check(0 < i < j, 'app.py recarga ANTES de ejecutar la pantalla')


if __name__ == '__main__':
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
