#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — Fotos diarias de la línea (`historical_odds`, fase='snapshot').

Por qué hace falta
------------------
28 de las 64 competiciones del catálogo NO tienen ninguna cuota histórica, y no
es un descuido: son las que sirve ESPN, y **ESPN retira el bloque `odds` en
cuanto el partido termina**. Medido el 2026-07-28 sobre col.1, bra.2, chi.1,
mex.1, eng.1 y conmebol.libertadores: 25/25 partidos FUTUROS traen cuota y
0/40+ partidos PASADOS la conservan, a 7, 30 o 120 días vista. No hay backfill
posible; la única forma de tener histórico ahí es capturarlo antes del pitido
inicial. Eso es lo que hace este módulo.

Y es también la materia prima del CLV: guardando una foto al día se reconstruye
el movimiento de la línea (`dias_al_partido`), que es lo que permite entrenar
un predictor de cierre. Por eso NUNCA se pisa una foto anterior — cada día es
una fila nueva, y una segunda ejecución el mismo día no altera el histórico
(`INSERT OR IGNORE` sobre la clave `snapshot_key`).

Identidad del partido
---------------------
El `match_id` se construye con `league_engine._match_id` sobre los nombres del
CATÁLOGO DEL MODELO (no los de ESPN o Pinnacle), resolviéndolos con
`name_mapper`. Así la foto de hoy y la cuota de cierre que football-data
publique mañana caen sobre el mismo identificador y el CLV se puede calcular.
`reconciliar()` arregla además el desfase de un día entre la fecha UTC de ESPN
y la fecha local de football-data, que si no dejaría huérfana una de cada
varias fotos.

Uso:
    python daily_snapshots.py                # captura de hoy
    python daily_snapshots.py --reconciliar  # solo reconciliar ids
"""

import argparse
import datetime as dt
import json
import logging
import sys
from typing import Dict, List, Optional

import pandas as pd

import odds_store

# La consola de Windows es cp1252: sin esto, imprimir una flecha o un
# visto aborta el script DESPUÉS de haber hecho todo el trabajo.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

SALIDA = '_v75_snapshots.json'
DIAS_VISTA = 7


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _clave_dia() -> str:
    """
    Cubo horario, no diario.

    Se intentó primero con clave diaria y se vio el problema en la primera
    prueba: al añadir el mercado BTTS a mitad de la mañana, la captura del día
    ya estaba escrita y `INSERT OR IGNORE` bloqueaba cualquier reintento — el
    día entero se quedaba sin BTTS y no había forma de recuperarlo. Con cubo
    horario, el workflow diario sigue produciendo exactamente una foto por casa
    (corre una vez), pero una ejecución posterior aporta una foto NUEVA en vez
    de chocar, y nunca se pisa la anterior. Para el CLV, más granularidad es
    mejor: el movimiento intradía es señal, no ruido.
    """
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H')


def _fila_base(clave, mid, fecha, home, away, dias):
    return {'match_id': mid, 'league_key': clave, 'match_date': fecha,
            'home_team': home, 'away_team': away,
            'fase': 'snapshot', 'snapshot_key': _clave_dia(),
            'dias_al_partido': dias, 'source_file': 'daily_snapshots',
            'ingested_at': _ahora()}


def capturar(dias: int = DIAS_VISTA, solo: Optional[str] = None) -> dict:
    """Recorre los fixtures de los próximos `dias` y guarda una fila por casa."""
    import cuotas_multi
    import fixtures_espn
    import name_mapper
    from config import LEAGUES
    from league_engine import ClubEngine, _match_id

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS
              and (not solo or c == solo)]
    try:
        cuotas_multi.precargar('futbol')
    except Exception as e:
        logger.warning(f"precarga de cuotas falló ({e}); se sigue con ESPN.")

    fixtures_por_liga = fixtures_espn.fixtures_multi(claves, dias=dias)
    hoy = pd.Timestamp.today().normalize()
    filas: List[dict] = []
    por_liga: Dict[str, int] = {}
    sin_nombre = 0

    for clave in claves:
        fixtures = fixtures_por_liga.get(clave) or []
        if not fixtures:
            continue
        try:
            eng = ClubEngine(clave)
            catalogo = list(eng.stats.keys()) if getattr(eng, 'listo', False) else []
        except Exception:
            catalogo = []
        for fx in fixtures:
            try:
                fecha = pd.Timestamp(fx['fecha'])
            except (ValueError, TypeError):
                continue
            if fecha < hoy:
                continue
            home = name_mapper.mapear(fx['home'], catalogo,
                                      contexto=f'snapshot→{clave}') if catalogo else fx['home']
            away = name_mapper.mapear(fx['away'], catalogo,
                                      contexto=f'snapshot→{clave}') if catalogo else fx['away']
            if not (home and away) or home == away:
                sin_nombre += 1
                continue
            mid = _match_id(fecha, home, away)
            dias_al = float((fecha - hoy).days)
            base = _fila_base(clave, mid, fecha.strftime('%Y-%m-%d'),
                              str(home), str(away), dias_al)

            # 1) lo que ya vino con el fixture (coste cero)
            if fx.get('odd_home') and fx.get('odd_away'):
                filas.append({**base, 'bookmaker': (fx.get('casa') or 'ESPN'),
                              'snapshot_key': f"{_clave_dia()}|{fx.get('casa') or 'ESPN'}",
                              'odds_home': fx.get('odd_home'),
                              'odds_draw': fx.get('odd_draw'),
                              'odds_away': fx.get('odd_away'),
                              'odds_over25': fx.get('odd_over25'),
                              'odds_under25': fx.get('odd_under25')})

            # 2) Pinnacle / Bovada / resto vía la capa multi-casa
            try:
                c = cuotas_multi.cuotas_partido('futbol', str(home), str(away),
                                                odds_espn=None)
            except Exception as e:
                logger.debug(f"[{clave}] cuotas_partido {home}-{away}: {e}")
                c = None
            if c:
                totales = c.get('totales') or {}
                # v90 — CADA CASA GUARDA SUS PROPIOS TOTALES.
                #
                # Hasta ahora los de Goles y BTTS se escribían SÓLO en la fila
                # de Pinnacle, porque `cuotas_partido` devolvía un único dict
                # `totales` con las casas ya fusionadas. Consecuencia medida al
                # intentar validar el canal de valor sobre Goles: de 35.606
                # filas con over25 en `historical_odds`, **cero** tienen dos
                # casas para el mismo partido. Sin dos precios no hay line
                # shopping que medir, y el mercado quedaba condenado a no poder
                # validarse nunca — no por falta de tiempo, sino porque el dato
                # se fusionaba antes de guardarse.
                #
                # `totales_por_casa` (v90) conserva la atribución. Se cae al
                # dict fusionado para Pinnacle si la fuente no lo trae, así que
                # el histórico que ya existe no cambia de forma.
                por_casa = c.get('totales_por_casa') or {}
                for casa, precios in (c.get('casas') or {}).items():
                    if not precios.get('home'):
                        continue
                    fila = {**base, 'bookmaker': casa,
                            'snapshot_key': f"{_clave_dia()}|{casa}",
                            'odds_home': precios.get('home'),
                            'odds_draw': precios.get('draw'),
                            'odds_away': precios.get('away')}
                    tot = por_casa.get(casa) or (totales if casa == 'Pinnacle'
                                                 else {})
                    if tot:
                        fila['odds_over25'] = tot.get('over25')
                        fila['odds_under25'] = tot.get('under25')
                        # v75: BTTS. Es la ÚNICA vía por la que este mercado
                        # puede acumular histórico: football-data no publica
                        # ninguna columna BTTS en ningún formato (verificado
                        # sobre los 132 campos de /mmz4281/ y los 25 de /new/),
                        # así que sin estas fotos el modelo Weibull nunca
                        # podría validarse contra precios reales.
                        fila['odds_btts_yes'] = tot.get('btts_yes')
                        fila['odds_btts_no'] = tot.get('btts_no')
                    filas.append(fila)
            por_liga[clave] = por_liga.get(clave, 0) + 1

    con = odds_store.conectar()
    # Recargar primero lo que ya hubiera en el repositorio: en un clon limpio
    # (el runner de Actions) la base viene vacía porque está en .gitignore, y
    # sin este paso cada ejecución empezaría de cero y el histórico nunca
    # crecería. Ver `odds_store.exportar_snapshots`.
    odds_store.importar_snapshots(con)
    # reemplazar=False: una segunda pasada en la misma hora NO reescribe la foto.
    n = odds_store.guardar(con, filas, reemplazar=False)
    total_snap = con.execute(
        "SELECT COUNT(*) FROM historical_odds WHERE fase='snapshot'").fetchone()[0]
    # …y volcarlo de vuelta, que es lo que el workflow commitea.
    odds_store.exportar_snapshots(con)
    con.close()

    resumen = {'generado': _ahora(), 'dia': _clave_dia(),
               'filas_nuevas': n, 'filas_generadas': len(filas),
               'partidos': sum(por_liga.values()), 'ligas': len(por_liga),
               'sin_nombre_resuelto': sin_nombre,
               'snapshots_acumulados': total_snap, 'por_liga': por_liga}
    logger.info(f"Snapshot {_clave_dia()}: {n} filas nuevas de "
                f"{resumen['partidos']} partidos en {resumen['ligas']} ligas "
                f"(acumulado histórico: {total_snap}).")
    return resumen


# ---------------------------------------------------------------------------
# v97 — Fotos de la KBO
# ---------------------------------------------------------------------------
def capturar_kbo() -> dict:
    """
    Fotografía la línea de la KBO. Es la ÚNICA vía a un edge validado.

    `capturar()` recorre el catálogo de fútbol, así que la KBO se quedaba
    fuera: sin fotos no hay cuota de cierre, sin cierre no hay ROI, y sin ROI
    la competición no puede salir nunca de Capa 2 — daría igual lo bueno que
    fuese su modelo. Como de la KBO no existe histórico gratuito de cierre que
    comprar ni descargar, la única forma de tenerlo algún día es **empezar a
    guardarlo hoy**. Es exactamente lo que la v90 dejó en marcha para las 11
    ligas sin cuotas (n≈300 por liga en ~4 meses).

    Reutiliza el mismo almacén y la misma clave de foto que el fútbol, así que
    `clv_tracker`, `monitor_canales` y el exportador a CSV la ven sin cambios.
    """
    import cuotas_multi
    from engines.kbo_engine import KBOEngine, equipo_kbo, es_partido_kbo

    filas: List[dict] = []
    try:
        cuotas_multi.precargar('mlb')
    except Exception as e:
        logger.warning(f"[kbo] precarga de cuotas falló ({e}).")

    vistos = set()
    hoy = pd.Timestamp.today().normalize()
    for idx in (cuotas_multi._indice('mlb'), cuotas_multi._indice_bov('mlb'),
                cuotas_multi._indice_pdt('mlb')):
        for v in (idx or {}).values():
            h, a = v.get('home'), v.get('away')
            if not (h and a) or not es_partido_kbo(h, a):
                continue
            hc, ac = equipo_kbo(h), equipo_kbo(a)
            iso = cuotas_multi.fecha_normalizada(v.get('fecha'))
            fecha = (iso or str(hoy.date()))[:10]
            if (hc, ac, fecha) in vistos:
                continue
            vistos.add((hc, ac, fecha))
            try:
                dias = (pd.Timestamp(fecha) - hoy).days
            except Exception:
                dias = 0
            try:
                c = cuotas_multi.cuotas_partido('mlb', h, a)
            except Exception as e:
                logger.debug(f'[kbo] cuotas_partido {h}-{a}: {e}')
                continue
            mid = f"{fecha.replace('-', '')}_{hc}_{ac}".replace(' ', '-')
            base = _fila_base('kbo', mid, fecha, hc, ac, dias)
            for casa, precios in (c.get('casas') or {}).items():
                if not isinstance(precios, dict) or not precios.get('home'):
                    continue
                # `snapshot_key` lleva la casa, igual que en el fútbol: la
                # tabla es UNIQUE(match_id, bookmaker, snapshot_key) y sin ella
                # dos casas del mismo día colisionarían.
                filas.append({**base, 'bookmaker': casa,
                              'snapshot_key': f"{_clave_dia()}|{casa}",
                              'odds_home': precios.get('home'),
                              'odds_away': precios.get('away'),
                              'source_file': 'daily_snapshots/kbo'})

    if not filas:
        logger.info('[kbo] sin partidos con cuota que fotografiar.')
        return {'filas_nuevas': 0, 'partidos': 0}
    con = odds_store.conectar()
    odds_store.importar_snapshots(con)
    n = odds_store.guardar(con, filas, reemplazar=False)
    odds_store.exportar_snapshots(con)
    con.close()
    logger.info(f"[kbo] {n} filas nuevas de {len(vistos)} partidos.")
    return {'filas_nuevas': n, 'partidos': len(vistos),
            'filas_generadas': len(filas)}


# ---------------------------------------------------------------------------
# Reconciliación snapshot -> cierre
# ---------------------------------------------------------------------------
def reconciliar(tolerancia_dias: int = 1) -> dict:
    """
    Reasigna el `match_id` de las fotos que no cuadran con ninguna cuota de
    cierre por un desfase de fecha.

    ESPN fecha el partido en UTC y football-data en hora local, así que un
    Boca–River de las 21:00 en Argentina es día D para football-data y D+1 para
    ESPN. Sin esta reconciliación esas fotos quedarían huérfanas y el CLV se
    calcularía sobre una muestra sesgada (solo los partidos de horario
    europeo). Se empareja por (liga, equipos, fecha ±`tolerancia_dias`).
    """
    con = odds_store.conectar()
    cierres = {}
    for mid, liga, fecha, h, a in con.execute(
            "SELECT DISTINCT match_id, league_key, match_date, home_team, away_team "
            "FROM historical_odds WHERE fase='cierre'"):
        cierres.setdefault((liga, str(h).lower(), str(a).lower()), []).append((fecha, mid))

    huerfanas = con.execute(
        "SELECT DISTINCT s.match_id, s.league_key, s.match_date, s.home_team, s.away_team "
        "FROM historical_odds s WHERE s.fase='snapshot' AND NOT EXISTS ("
        "  SELECT 1 FROM historical_odds c WHERE c.fase='cierre' "
        "        AND c.match_id = s.match_id)").fetchall()

    arreglos = 0
    for mid, liga, fecha, h, a in huerfanas:
        cands = cierres.get((liga, str(h).lower(), str(a).lower())) or []
        try:
            f0 = dt.date.fromisoformat(fecha)
        except ValueError:
            continue
        for fecha_c, mid_c in cands:
            try:
                d = abs((dt.date.fromisoformat(fecha_c) - f0).days)
            except ValueError:
                continue
            if d <= tolerancia_dias and mid_c != mid:
                con.execute("UPDATE OR IGNORE historical_odds SET match_id=? "
                            "WHERE match_id=? AND fase='snapshot'", (mid_c, mid))
                arreglos += 1
                break
    con.commit()
    pendientes = con.execute(
        "SELECT COUNT(DISTINCT match_id) FROM historical_odds s WHERE s.fase='snapshot' "
        "AND NOT EXISTS (SELECT 1 FROM historical_odds c WHERE c.fase='cierre' "
        "AND c.match_id = s.match_id)").fetchone()[0]
    con.close()
    logger.info(f"Reconciliación: {arreglos} fotos reasignadas a su cierre; "
                f"{pendientes} partidos aún sin cierre publicado (normal si "
                f"todavía no se han jugado).")
    return {'reasignadas': arreglos, 'sin_cierre': pendientes}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--liga')
    ap.add_argument('--dias', type=int, default=DIAS_VISTA)
    ap.add_argument('--reconciliar', action='store_true')
    args = ap.parse_args()
    if args.reconciliar:
        salida = reconciliar()
    else:
        salida = capturar(dias=args.dias, solo=args.liga)
        # v97 — la KBO va aparte porque `capturar` recorre el catálogo de
        # fútbol. Un fallo suyo no puede llevarse las fotos del fútbol.
        try:
            salida['kbo'] = capturar_kbo()
        except Exception as e:
            logger.warning(f'[kbo] fotos omitidas: {type(e).__name__}: {e}')
            salida['kbo'] = {'error': f'{type(e).__name__}: {e}'}
        salida['reconciliacion'] = reconciliar()
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print(json.dumps(salida, ensure_ascii=False, indent=1)[:900])
