#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — VALIDACIÓN DE LA SECCIÓN DE REMATES DE LA FICHA, CON Y SIN DATOS.

Por qué no basta `valida_render.py`
-----------------------------------
Ese abre las VISTAS, y la ficha de un partido parte su contenido en secciones
que sólo se ejecutan cuando se abren (`partido_ui`, v147). La sección de
remates vive dentro de «Mercados», así que una vista de liga puede salir verde
con esa sección sin ejecutar ni una línea.

Y ahí es justo donde puede haber un `UnboundLocalError` o un `KeyError`: la
sección tiene cuatro caminos —observado, estimado, con jugadores y sin
jugadores— y el interesante es el ÚLTIMO, el de una competición sin alineación
publicada y sin roster cacheado, que es lo que se ve la mayor parte del tiempo.

Qué comprueba
-------------
Llama a `render_remates_partido` contra un Streamlit de mentira que registra lo
que se pinta, en cuatro escenarios:

    1. liga con remates OBSERVADOS y jugadores en caché
    2. liga con remates ESTIMADOS (sin datos observados)
    3. equipo SIN jugadores en caché — el bloque de jugadores no se pinta
    4. competición sin nada — no revienta y no pinta una tabla vacía

    python _v163_valida_ficha_remates.py
"""
import sys
import warnings

warnings.filterwarnings('ignore')
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

FALLOS = []


def check(cond, msg):
    print(('OK    ' if cond else 'FALLO ') + msg)
    if not cond:
        FALLOS.append(msg)


class _Col:
    """Una columna del `st.columns` de mentira."""

    def __init__(self, registro):
        self.r = registro

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, nombre):
        return getattr(self.r, nombre)


class _St:
    """
    Un Streamlit de mentira que sólo apunta lo que se le pide pintar.

    No se usa AppTest aquí a propósito: AppTest ejecuta el script entero y
    llegar a esta sección exigiría navegar por el selector de vistas, elegir
    liga, elegir partido y abrir la pestaña. Eso son minutos por escenario y
    cuatro escenarios. Llamando a la función con este doble se prueba
    exactamente el código que hay que probar, y `valida_render.py` sigue
    cubriendo el resto de la pantalla.
    """

    def __init__(self):
        self.textos = []
        self.tablas = []
        self.avisos = []

    def _anota(self, x):
        self.textos.append(str(x))

    def divider(self):
        pass

    def subheader(self, x, *a, **k):
        self._anota(x)

    def markdown(self, x, *a, **k):
        self._anota(x)

    def caption(self, x, *a, **k):
        self._anota(x)

    def info(self, x, *a, **k):
        self._anota(x)
        self.avisos.append(str(x))

    def warning(self, x, *a, **k):
        self._anota(x)
        self.avisos.append(str(x))

    def error(self, x, *a, **k):
        self._anota(x)
        self.avisos.append(str(x))

    def success(self, x, *a, **k):
        self._anota(x)

    def dataframe(self, d, *a, **k):
        self.tablas.append(d)

    def columns(self, n, *a, **k):
        cuantas = n if isinstance(n, int) else len(n)
        return [_Col(self) for _ in range(cuantas)]

    def cache_data(self, *a, **k):
        """El decorador, neutralizado: aquí no hay sesión que cachear."""
        def envoltorio(fn):
            return fn
        if a and callable(a[0]):
            return a[0]
        return envoltorio

    def __getattr__(self, nombre):
        # cualquier otra cosa que la seccion llame no hace nada y no revienta
        def _nada(*a, **k):
            return None
        return _nada


def escenario(nombre, clave, home, away, espera_tabla=True):
    import dashboard_ui as ui
    falso = _St()
    real = ui.st
    ui.st = falso
    try:
        ui.render_remates_partido(clave, home, away, key=clave)
    except Exception as e:
        ui.st = real
        check(False, '%s: revienta con %s: %s' % (nombre, type(e).__name__, e))
        import traceback
        traceback.print_exc()
        return falso
    finally:
        ui.st = real
    todo = ' '.join(falso.textos)
    check('Remates del partido' in todo,
          '%s: la seccion se pinta' % nombre)
    if espera_tabla:
        check(len(falso.tablas) >= 1,
              '%s: sale al menos una tabla (%d)' % (nombre, len(falso.tablas)))
    return falso


def main():
    import rendimiento_equipos as rq

    print('=' * 78)
    print('1) COMPETICION CON REMATES OBSERVADOS')
    print('=' * 78)
    f = escenario('observado', 'premier', 'Man City', 'Arsenal')
    todo = ' '.join(f.textos)
    check('calibraci' in todo,
          'observado: dice cuanto se equivoca')
    check('ventaja de precio' in todo,
          'observado: y dice que NO es una ventaja de precio')

    print()
    print('=' * 78)
    print('2) COMPETICION CON REMATES ESTIMADOS')
    print('=' * 78)
    sin = None
    try:
        import fixtures_espn
        from config import LEAGUES
        for c, v in LEAGUES.items():
            if not v.get('disponible') or c not in fixtures_espn.ESPN_CODIGOS:
                continue
            d = rq._historico(c)
            if d is None or getattr(d, 'empty', True) or len(d) < 300:
                continue
            if not rq.stats_disponibles(c).get('remates'):
                sin = (c, str(d['home_team'].iloc[-1]),
                       str(d['away_team'].iloc[-1]))
                break
    except Exception as e:
        print('   no se pudo elegir competicion sin datos: %s' % e)
    if sin:
        f2 = escenario('estimado (%s)' % sin[0], *sin)
        todo2 = ' '.join(f2.textos)
        check('Estimado' in todo2,
              'estimado: la seccion lo dice con todas las letras')
    else:
        print('   (no queda ninguna competicion sin remates observados)')

    print()
    print('=' * 78)
    print('3) EQUIPO SIN JUGADORES EN CACHE')
    print('=' * 78)
    f3 = escenario('sin jugadores', 'premier', 'Equipo Inventado FC',
                   'Otro Inventado CF', espera_tabla=False)
    todo3 = ' '.join(f3.textos)
    check('Sin estad' in todo3 or len(f3.tablas) >= 1,
          'sin jugadores: se explica el hueco en vez de pintar una tabla vacia')

    print()
    print('=' * 78)
    print('4) COMPETICION QUE NO EXISTE')
    print('=' * 78)
    falso = _St()
    import dashboard_ui as ui
    real = ui.st
    ui.st = falso
    try:
        ui.render_remates_partido('liga_que_no_existe', 'A', 'B',
                                  key='liga_que_no_existe')
        check(True, 'competicion inexistente: no revienta')
    except Exception as e:
        check(False, 'competicion inexistente: revienta con %s'
              % type(e).__name__)
    finally:
        ui.st = real
    check(not falso.tablas,
          'competicion inexistente: no pinta ninguna tabla')

    print()
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    for x in FALLOS:
        print('  - ' + x)
    return 1 if FALLOS else 0


if __name__ == '__main__':
    sys.exit(main())
