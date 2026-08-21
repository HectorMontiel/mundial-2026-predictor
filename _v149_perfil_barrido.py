#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v149 — DÓNDE SE VAN LOS SEGUNDOS DEL BARRIDO.

La v148 escondió el coste detrás de una caché, que es correcto pero no es lo
mismo que reducirlo: el primer visitante de cada contenedor sigue pagándolo
entero, y en Streamlit Cloud el contenedor se recicla en cada despliegue.

Esto no optimiza nada: sólo mide, para no volver a optimizar a ciegas.
"""
import logging
import time
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

TIEMPOS = {}


def _cronometrar(nombre, fn, *a, **k):
    t = time.perf_counter()
    try:
        return fn(*a, **k)
    finally:
        TIEMPOS[nombre] = TIEMPOS.get(nombre, 0.0) + (time.perf_counter() - t)


def main():
    import alpha_finder
    import fixtures_espn
    import league_engine
    from config import LEAGUES

    # --- 1. instrumentar los sospechosos, sin tocar su comportamiento
    _orig_engine = league_engine.ClubEngine.__init__
    n_motores = [0]

    def _engine(self, clave):
        n_motores[0] += 1
        return _cronometrar('carga de modelos (ClubEngine)',
                            _orig_engine, self, clave)
    league_engine.ClubEngine.__init__ = _engine

    _orig_pred = league_engine.ClubEngine.predecir
    n_pred = [0]

    def _pred(self, *a, **k):
        n_pred[0] += 1
        return _cronometrar('predicciones', _orig_pred, self, *a, **k)
    league_engine.ClubEngine.predecir = _pred

    _orig_fix = fixtures_espn.fixtures_multi

    def _fix(*a, **k):
        return _cronometrar('fixtures ESPN', _orig_fix, *a, **k)
    fixtures_espn.fixtures_multi = _fix

    _orig_odds = fixtures_espn.odds_multi
    n_odds = [0]

    def _odds(*a, **k):
        n_odds[0] += 1
        return _cronometrar('cuotas por evento (ESPN)', _orig_odds, *a, **k)
    fixtures_espn.odds_multi = _odds

    try:
        import cuotas_multi
        _orig_cm = cuotas_multi.cuotas_partido

        def _cm(*a, **k):
            return _cronometrar('cuotas_multi (casas)', _orig_cm, *a, **k)
        cuotas_multi.cuotas_partido = _cm
    except Exception:
        pass

    # --- 2. cada rama por separado, en serie, para que los tiempos no se pisen
    ramas = [('fútbol', lambda: alpha_finder.apuestas_del_dia()),
             ('tenis', alpha_finder._picks_tenis),
             ('mlb', alpha_finder._picks_mlb),
             ('nba', alpha_finder._picks_nba),
             ('kbo', alpha_finder._picks_kbo),
             ('nfl', alpha_finder._picks_nfl)]
    por_rama = {}
    for nombre, fn in ramas:
        t = time.perf_counter()
        try:
            fn()
        except Exception as e:
            print(f'   rama {nombre} falló: {type(e).__name__}: {e}')
        por_rama[nombre] = time.perf_counter() - t

    print('\n=== POR RAMA (en serie; en producción van en paralelo) ===')
    for k, v in sorted(por_rama.items(), key=lambda x: -x[1]):
        print(f'   {k:<10} {v:7.1f} s')
    print(f'   {"SUMA":<10} {sum(por_rama.values()):7.1f} s')
    print(f'   {"TECHO":<10} {max(por_rama.values()):7.1f} s  '
          f'(la rama más lenta = lo que tarda en paralelo)')

    print('\n=== POR ACTIVIDAD (acumulado, todas las hebras) ===')
    for k, v in sorted(TIEMPOS.items(), key=lambda x: -x[1]):
        print(f'   {k:<32} {v:7.1f} s')
    print(f'\n   motores construidos : {n_motores[0]}')
    print(f'   predicciones        : {n_pred[0]}')
    print(f'   llamadas odds_multi : {n_odds[0]}')


if __name__ == '__main__':
    t0 = time.perf_counter()
    main()
    print(f'\nTOTAL DEL PERFIL: {time.perf_counter() - t0:.1f} s')
