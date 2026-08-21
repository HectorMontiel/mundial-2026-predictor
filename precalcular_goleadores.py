#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v147 — Precalcula la caché de goleadores en el runner, no en el navegador.

El problema, y por qué NO es un cambio de URL
---------------------------------------------
En producción el log repite:

    [goleadores/liga_mx] roster 232: HTTPError: 403 Client Error: Forbidden

Verificado el 2026-08-17 desde una máquina normal, sobre 14 ligas
(mex.1, eng.1, esp.1, ita.1, ger.1, fra.1, usa.1, arg.1, bra.1, por.1, ned.1,
sco.1, swe.1, rus.1):

    /teams  que fallan ....... 0 de 14
    /roster que fallan ....... 0 de 14

O sea que la URL está bien y el endpoint funciona. **El 403 depende de quién
pregunta**: ESPN bloquea `/teams` y `/roster` desde IPs de centro de datos, que
es donde corre Streamlit Cloud. Está documentado en `goleadores` desde la v110,
con caché negativa para no repetir la petición en cada rerun.

Por qué el runner de GitHub sí puede
------------------------------------
Podría pensarse que un runner de Actions es también un centro de datos y estaría
igual de bloqueado. **No lo está, y hay prueba en el propio repositorio**: el
commit diario del bot añade partidos a `historico_arg_primera_nacional.csv`,
`historico_bol_division.csv`, `historico_chi_primera.csv` y
`historico_per_liga1.csv` — cuatro ligas de formato `espn`, cuyos datos salen
EXCLUSIVAMENTE de ESPN. Si el runner estuviera bloqueado, esos ficheros no
crecerían.

Qué hace este script
--------------------
Rellena `goleadores_cache.json`, que es **la misma caché que la aplicación ya
lee**. No hay formato nuevo, ni consumidor nuevo, ni una segunda fuente que
mantener: sólo se adelanta el trabajo a un sitio donde la petición no la
rechazan. En Streamlit Cloud, `_fresco()` encuentra la entrada y no llama a la
red.

El TTL de la caché son 3 días (`goleadores.TTL_DIAS`), así que el workflow corre
a diario y siempre la deja fresca.

Uso:
    python precalcular_goleadores.py                 # todas las disponibles
    python precalcular_goleadores.py --ligas liga_mx premier
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

logger = logging.getLogger(__name__)


def ligas_objetivo(pedidas=None):
    """Las ligas disponibles que ESPN puede servir, en orden estable."""
    import config
    import fixtures_espn as fe
    todas = [k for k, v in sorted(config.LEAGUES.items())
             if v.get('disponible') and k in fe.ESPN_CODIGOS]
    if not pedidas:
        return todas
    faltan = [k for k in pedidas if k not in todas]
    if faltan:
        logger.warning(f'[precalc] ligas ignoradas (no disponibles o sin '
                       f'código ESPN): {faltan}')
    return [k for k in pedidas if k in todas]


def precalcular(claves, pausa: float = 0.4) -> dict:
    """
    Rellena la caché de goleadores para cada liga y devuelve el resumen.

    La pausa entre equipos no es paranoia: son ~20 peticiones por liga y ~50
    ligas, o sea unas mil. Sin ella se parece a una ráfaga, y una ráfaga es
    exactamente lo que hace que una fuente gratuita empiece a devolver 429.
    """
    import goleadores as g
    resumen = {'ligas': {}, 'equipos_ok': 0, 'equipos_fallo': 0}
    for clave in claves:
        t0 = time.time()
        try:
            equipos = g.equipos_liga(clave)
        except Exception as e:
            logger.warning(f'[precalc/{clave}] equipos: {type(e).__name__}: {e}')
            equipos = []
        ok = fallo = 0
        for eq in equipos:
            try:
                pl = g.plantilla_equipo(clave, eq['id'])
                if pl:
                    ok += 1
                else:
                    fallo += 1
            except Exception as e:
                fallo += 1
                logger.debug(f'[precalc/{clave}] {eq.get("nombre")}: '
                             f'{type(e).__name__}: {e}')
            time.sleep(pausa)
        resumen['ligas'][clave] = {'equipos': len(equipos), 'ok': ok,
                                   'fallo': fallo,
                                   'segundos': round(time.time() - t0, 1)}
        resumen['equipos_ok'] += ok
        resumen['equipos_fallo'] += fallo
        logger.info(f'[precalc/{clave}] {ok}/{len(equipos)} plantillas '
                    f'({time.time() - t0:.0f} s)')
    return resumen


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--ligas', nargs='*', default=None)
    ap.add_argument('--pausa', type=float, default=0.4)
    a = ap.parse_args()

    claves = ligas_objetivo(a.ligas)
    if not claves:
        logger.error('[precalc] ninguna liga objetivo; no se escribe nada.')
        return 1
    logger.info(f'[precalc] {len(claves)} ligas: {", ".join(claves[:8])}'
                f'{"…" if len(claves) > 8 else ""}')
    r = precalcular(claves, pausa=a.pausa)

    print(f'\n{"liga":24} {"equipos":>8} {"ok":>5} {"fallo":>6} {"seg":>6}')
    for k, v in r['ligas'].items():
        print(f'{k:24} {v["equipos"]:8} {v["ok"]:5} {v["fallo"]:6} '
              f'{v["segundos"]:6.0f}')
    print(f'\nplantillas cacheadas: {r["equipos_ok"]} · fallidas: '
          f'{r["equipos_fallo"]}')

    # SI NO SE CACHEÓ NADA, SE FALLA EN VOZ ALTA.
    #
    # Un script de precálculo que no precalcula nada y termina con éxito es la
    # peor variante posible: el workflow sale verde, nadie mira, y la caché
    # sigue vacía. Si ESPN empezara a bloquear también al runner, esto es lo
    # que lo diría.
    if r['equipos_ok'] == 0:
        logger.error('[precalc] no se cacheó NINGUNA plantilla. Si esto pasa '
                     'en el runner, ESPN ha empezado a bloquearlo también y '
                     'hay que buscar otra vía.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
