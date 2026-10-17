#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v393: ninguna liga pierde sus estadísticas reales.

CAUSA RAÍZ (5 porqués, 17-oct). La Liga MX tenía córners de 9 partidos
cuando ESPN le había dado 1.837:
  1. ¿Por qué? `stats_espn/liga_mx.csv.gz` tenía 9 filas.
  2. ¿Por qué? El reentrenamiento del 13-oct (`stats_espn --dias 10`) lo
     reescribió con sólo los últimos 10 días.
  3. ¿Por qué? `leer()` no pudo abrirlo, devolvió vacío y `_guardar` escribió
     encima sin mirar lo que había.
  4. ¿Por qué no se podía abrir? El 12-oct `git_sin_conflictos.resolver` lo
     «resolvió» leyéndolo como TEXTO con errors='replace' (bytes EF BF BD) y
     lo guardó así: 34 ficheros `.csv.gz` dañados en el commit 9070d47c.
  5. ¿Por qué? El resolvedor sólo conocía `.csv` y trataba todo lo demás como
     texto; nadie comprobaba que un comprimido siguiera siéndolo.

ARREGLO: el resolvedor trabaja en bytes y une los `.csv.gz` fila a fila;
`_guardar` no pisa un fichero ilegible ni uno que perdería el 30 %; los datos
se recuperaron del historial de git; y FotMob (`stats_fotmob`) cubre las ligas
que ESPN no tiene. Esta prueba vigila las cuatro cosas.

Ejecutar:  python test_v393.py
"""
import gzip
import os
import shutil
import subprocess
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_resolvedor():
    import git_sin_conflictos as g
    a = gzip.compress(b'event_id,fecha\n1,2026-01-01\n2,2026-01-02\n')
    b = gzip.compress(b'event_id,fecha\n2,2026-01-02\n3,2026-01-03\n')
    c, como = g.fundir('stats_espn/x.csv.gz', a, b)
    filas = gzip.decompress(c).decode().splitlines()
    check(filas == ['event_id,fecha', '1,2026-01-01', '2,2026-01-02', '3,2026-01-03'],
          'un .csv.gz en conflicto se une fila a fila y sigue comprimido (%s)' % como)
    roto = 'basura�'.encode('utf-8')
    c, _ = g.fundir('stats_espn/x.csv.gz', roto, b)
    check(gzip.decompress(c) == gzip.decompress(b), 'un lado dañado no envenena al otro')
    png = bytes(range(256))
    c, _ = g.fundir('web/marca/logo.png', b'viejo', png)
    check(c == png, 'cualquier otro binario pasa intacto, byte a byte')
    c, _ = g.fundir('lineas.csv', 'h\nñ1\n'.encode(), 'h\nñ2\n'.encode())
    check(c.decode('utf-8') == 'h\nñ1\nñ2\n', 'los .csv se siguen uniendo (con acentos)')


def probar_candado():
    import pandas as pd
    import stats_espn as se
    tmp = tempfile.mkdtemp()
    try:
        d = pd.DataFrame({c: [] for c in se.COLUMNAS})
        filas = [{'fecha': '2026-01-%02d' % (i % 28 + 1), 'home': 'A', 'away': 'B',
                  'event_id': str(i)} for i in range(100)]
        d = pd.DataFrame(filas).reindex(columns=se.COLUMNAS)
        se._guardar('x', d, directorio=tmp)
        try:
            se._guardar('x', d.head(10), directorio=tmp)
            check(False, 'no se escribe una versión con 90 % menos filas')
        except se.EscrituraPeligrosa:
            check(True, 'no se escribe una versión con 90 % menos filas')
        check(len(se.leer('x', tmp)) == 100, 'el fichero bueno sigue entero')
        se._guardar('x', d.head(10), permitir_perder=True, directorio=tmp)
        check(len(se.leer('x', tmp)) == 10, '`limpiar` sí puede quitar filas a propósito')
        with open(se.ruta('y', tmp), 'wb') as f:
            f.write('roto�'.encode())
        try:
            se._guardar('y', d.head(5), directorio=tmp)
            check(False, 'un fichero ilegible no se sobrescribe')
        except se.EscrituraPeligrosa:
            check(True, 'un fichero ilegible no se sobrescribe')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def probar_ficheros():
    """Todos los comprimidos se leen y ninguno tiene menos del 70 % de las
    filas que tiene en el último commit (pérdida silenciosa)."""
    import io
    import pandas as pd
    for carpeta in ('stats_espn', 'stats_fotmob', 'stats_flashscore'):
        if not os.path.isdir(carpeta):
            continue
        malos, perdidas = [], []
        for f in sorted(os.listdir(carpeta)):
            if not f.endswith('.csv.gz'):
                continue
            p = '%s/%s' % (carpeta, f)
            try:
                n = len(pd.read_csv(p, compression='gzip', usecols=['event_id']))
            except Exception:
                malos.append(f)
                continue
            r = subprocess.run(['git', 'show', 'HEAD:' + p], capture_output=True)
            if r.returncode == 0 and r.stdout:
                try:
                    n0 = len(pd.read_csv(io.BytesIO(gzip.decompress(r.stdout)), usecols=['event_id']))
                except Exception:
                    n0 = 0
                if n0 >= 20 and n < 0.7 * n0:
                    perdidas.append('%s %d→%d' % (f, n0, n))
        check(not malos, '%s: todos los comprimidos se leen (%s)' % (carpeta, malos[:5]))
        check(not perdidas, '%s: ninguno perdió filas frente al último commit (%s)' % (carpeta, perdidas[:5]))


def probar_ligas():
    import rendimiento_equipos as rq
    for liga, minimo in (('liga_mx', 1500), ('mls', 2000), ('argentina', 2000), ('premier', 1500),
                         ('serie_a', 1500), ('brasil', 1500)):
        h = rq._historico(liga)
        if h is None or getattr(h, 'empty', True) or 'stats_origen' not in h:
            continue
        n = int(h['stats_origen'].notna().sum())
        check(n >= minimo, '%s: %d partidos con estadísticas reales (mínimo %d)' % (liga, n, minimo))
    # TODAS las ligas de fútbol con histórico tienen su media de córners
    # observada (el usuario: «No podemos dejar ninguna liga sin las
    # estadísticas»). Fuera, con su porqué:
    #   isr_premier — apagada (v184), su fuente se quedó en mayo de 2025 y ESPN
    #                 ya no la publica: sólo cruza una temporada.
    #   partidos / estadisticas_avanzadas — no son ligas (selecciones, tabla).
    import glob
    import pandas as pd
    fuera = {'isr_premier', 'partidos', 'estadisticas_avanzadas'}
    sin = []
    for r in sorted(glob.glob('historico_*.csv')):
        c = r[len('historico_'):-len('.csv')]
        if c in fuera:
            continue
        try:
            cols = pd.read_csv(r, nrows=0).columns
        except Exception:
            continue
        if 'home_goals' not in cols or 'home_corners' not in cols and 'stats_origen' not in cols:
            continue
        if rq.media_corners_liga(c) is None:
            sin.append(c)
    check(not sin, 'todas las ligas tienen su media de córners medida (sin: %s)' % sin)
    m = rq.media_corners_liga('liga_mx')
    check(m is not None and 8 <= m <= 12, 'la Liga MX tiene su media de córners medida (%s)' % m)
    d = rq.dispersion_corners_liga('liga_mx')
    check(d is not None and 1.0 <= d <= 1.6, 'y su dispersión (%s)' % d)
    le = open('league_engine.py', encoding='utf-8').read()
    check("directorio='stats_fotmob', origen='fotmob'" in le, 'el histórico se completa con FotMob donde ESPN no llega')
    wf = open(os.path.join('.github', 'workflows', 'retrain_leagues.yml'), encoding='utf-8').read()
    check('python stats_fotmob.py --dias 10' in wf and 'stats_fotmob/' in wf, 'el bot baja FotMob cada día y lo guarda')
    check('python stats_flashscore.py --dias 10' in wf and 'stats_flashscore/' in wf
          and "directorio='stats_flashscore', origen='flashscore'" in le,
          'y Flashscore para las ocho que ni ESPN ni FotMob publican')


def probar_fechas_espn():
    """ESPN rechaza `dates=ini-fin` (HTTP 400 o cero eventos). Ningún módulo
    de producción puede volver a pedirlo: se usa `espn_fechas`."""
    import re
    import espn_fechas as ef
    check(ef.consultas('2026-10-17', '2026-10-19') == ['20261017', '20261018', '20261019']
          and ef.consultas('2026-01-15', '2026-03-10') == ['202601', '202602', '202603'],
          'un rango se pide por días (≤ 7) o por meses, nunca con guion')
    check(ef.dentro({'date': '2026-10-17T02:00Z'}, '2026-10-17', '2026-10-17')
          and not ef.dentro({'date': '2026-09-30T23:00Z'}, '2026-10-01', '2026-10-31'),
          'y se queda sólo con los eventos del rango')
    patron = re.compile(r"""['"]dates['"]\s*:\s*f['"][^'"]*\}-\{""")
    malos = []
    for f in sorted(os.listdir('.')):
        # el tenis SÍ acepta rangos (medido el 17-oct) y sus eventos son
        # torneos, que empiezan antes del rango: filtrarlos por fecha sería peor
        if f.endswith('.py') and not f.startswith(('_', 'test_')) and f != 'tenis_fuentes.py':
            if patron.search(open(f, encoding='utf-8', errors='replace').read()):
                malos.append(f)
    check(not malos, 'ningún módulo pide a ESPN un rango con guion (%s)' % malos)


if __name__ == '__main__':
    probar_fechas_espn()
    probar_resolvedor()
    probar_candado()
    probar_ficheros()
    probar_ligas()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
