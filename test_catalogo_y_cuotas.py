#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de no regresión de la v75 (catálogo de ligas + histórico de cuotas).

Cada comprobación existe porque en la v75 se encontró el fallo correspondiente
con datos reales. El objetivo es que ninguno pueda volver sin que este test se
ponga en rojo.

  1. **Catálogo sin gemelos.** `suiza`/`suiza_v48`, `austria`/`aut_bundesliga` y
     `grecia`/`gre_super_league` eran la misma competición con dos claves. Peor:
     en Austria y Grecia una variante estaba RECHAZADA por su backtest y la otra
     ACTIVA en la Capa 1, precisamente porque venía de una fuente sin cuotas y
     no había con qué medirla.
  2. **Verificación de fuente por contenido.** football-data.co.uk responde
     HTTP 200 sirviendo OTRA liga cuando el código de país no existe
     (/new/COL.csv es la Ekstraklasa polaca). Dar de alta una liga mirando el
     código de estado habría metido partidos polacos en la liga colombiana.
  3. **Esquema e idempotencia de `historical_odds`.** Reimportar no puede
     duplicar cierres, y una segunda foto del mismo día no puede pisar la
     primera (rompería el CLV).
  4. **El ledger no puede tener fuga temporal** ni picks pre-filtrados.
  5. **Los umbrales publicados tienen que ser los validados.**

Ejecutar:  .venv\\Scripts\\python test_catalogo_y_cuotas.py
"""

import json
import os
import sqlite3
import sys

FALLOS = []


def check(cond, msg):
    print(('OK    ' if cond else 'FALLO ') + msg)
    if not cond:
        FALLOS.append(msg)


# ---------------------------------------------------------------------------
def test_catalogo_sin_duplicados():
    import config
    conflictos = config.validar_catalogo()
    check(not conflictos,
          f"catálogo sin ligas duplicadas ({len(config.LEAGUES)} competiciones)"
          + (f" — conflictos: {conflictos}" if conflictos else ""))

    # las claves fusionadas en la v75 no deben reaparecer
    for muerta in ('suiza_v48', 'austria', 'grecia'):
        check(muerta not in config.LEAGUES,
              f"la clave duplicada '{muerta}' sigue fuera del catálogo")

    # ninguna liga disponible puede quedarse sin fuente
    sin_fuente = [k for k, v in config.LEAGUES.items()
                  if v.get('disponible') and not v.get('urls')
                  and v.get('formato') not in ('espn', 'api_football')]
    check(not sin_fuente, f"toda liga disponible tiene fuente ({sin_fuente})")


def test_ligas_migradas():
    """Las tres migradas en la v75 tienen que estar como las dejó la regla de oro."""
    import config
    esperado = {
        # clave: (formato, disponible)  — veredicto medido en la v75
        'rus_premier': ('new', True),        # acc 0.530 > ELO 0.512
        'gre_super_league': ('main', True),  # acc 0.536 > ELO 0.506
        'aut_bundesliga': ('new', False),    # acc 0.373 < ELO 0.425
    }
    for clave, (formato, disp) in esperado.items():
        cfg = config.LEAGUES.get(clave, {})
        check(cfg.get('formato') == formato,
              f"{clave} usa football-data (formato '{formato}')")
        check(bool(cfg.get('disponible')) == disp,
              f"{clave} disponible={disp} (regla de oro de la v75)")


def test_verificacion_de_fuente():
    """El verificador tiene que rechazar los ficheros señuelo de football-data."""
    import odds_store
    # COL no existe: football-data devuelve la Ekstraklasa con HTTP 200
    r = odds_store.fuente_football_data_valida('COL', pais_esperado='Colombia')
    check(not r['valida'],
          f"/new/COL.csv rechazado por contenido ({r.get('motivo', '')[:60]})")
    # AUT sí existe y es Austria
    r2 = odds_store.fuente_football_data_valida('AUT')
    check(r2['valida'], "/new/AUT.csv aceptado (es Austria de verdad)")


def test_esquema_e_idempotencia():
    import odds_store
    ruta = '_test_odds_tmp.db'
    if os.path.exists(ruta):
        os.remove(ruta)
    con = odds_store.conectar(ruta)
    base = {'match_id': '20260101_A_B', 'league_key': 'x',
            'match_date': '2026-01-01', 'home_team': 'A', 'away_team': 'B',
            'bookmaker': 'mercado', 'odds_home': 2.0, 'odds_draw': 3.3,
            'odds_away': 3.5, 'ingested_at': 'now'}

    cierre = dict(base, fase='cierre', snapshot_key='cierre')
    odds_store.guardar(con, [cierre], reemplazar=True)
    odds_store.guardar(con, [cierre], reemplazar=True)        # reimportación
    n = con.execute("SELECT COUNT(*) FROM historical_odds "
                    "WHERE fase='cierre'").fetchone()[0]
    check(n == 1, f"reimportar un cierre no duplica (filas={n})")

    foto = dict(base, fase='snapshot', snapshot_key='2026-01-01|Pinnacle',
                bookmaker='Pinnacle', odds_home=2.10)
    odds_store.guardar(con, [foto], reemplazar=False)
    odds_store.guardar(con, [dict(foto, odds_home=9.99)], reemplazar=False)
    v = con.execute("SELECT odds_home FROM historical_odds "
                    "WHERE fase='snapshot'").fetchone()[0]
    check(abs(v - 2.10) < 1e-9,
          f"una segunda foto del mismo día NO pisa la primera (odds={v})")

    foto2 = dict(foto, snapshot_key='2026-01-02|Pinnacle', odds_home=2.30)
    odds_store.guardar(con, [foto2], reemplazar=False)
    n = con.execute("SELECT COUNT(*) FROM historical_odds "
                    "WHERE fase='snapshot'").fetchone()[0]
    check(n == 2, f"un día nuevo añade una foto nueva (filas={n}) — base del CLV")

    # una fila sin ninguna cuota no debe entrar
    vacia = dict(base, fase='cierre', snapshot_key='vacia', match_id='20260101_C_D',
                 odds_home=None, odds_draw=None, odds_away=None)
    odds_store.guardar(con, [vacia], reemplazar=True)
    n = con.execute("SELECT COUNT(*) FROM historical_odds "
                    "WHERE match_id='20260101_C_D'").fetchone()[0]
    check(n == 0, "una fila sin ninguna cuota no se almacena")
    con.close()
    os.remove(ruta)


def test_db_poblada():
    if not os.path.exists('odds_historico.db'):
        check(False, 'odds_historico.db existe')
        return
    con = sqlite3.connect('odds_historico.db')
    try:
        n = con.execute("SELECT COUNT(*) FROM historical_odds "
                        "WHERE fase='cierre'").fetchone()[0]
        ligas = con.execute("SELECT COUNT(DISTINCT league_key) FROM historical_odds "
                            "WHERE fase='cierre'").fetchone()[0]
        check(n > 50000, f"histórico de cierres poblado ({n} filas)")
        check(ligas >= 30, f"cierres en {ligas} ligas")
        # ninguna clave muerta puede tener filas
        muertas = con.execute(
            "SELECT DISTINCT league_key FROM historical_odds WHERE league_key "
            "IN ('suiza_v48','austria','grecia')").fetchall()
        check(not muertas, f"sin filas de ligas fusionadas ({muertas})")
    except sqlite3.OperationalError as e:
        check(False, f"tabla historical_odds legible ({e})")
    finally:
        con.close()


def test_snapshots_persisten_en_el_repo():
    """
    `odds_historico.db` está en .gitignore, así que si las fotos vivieran solo
    ahí el workflow las perdería en cada clon: capturaría 500 filas al día,
    no commitearía nada, y meses después el "histórico acumulado" seguiría
    teniendo un día. Lo irrepetible tiene que estar en el repositorio.
    """
    import csv
    import odds_store
    check(os.path.exists(odds_store.CSV_SNAPSHOTS),
          f"{odds_store.CSV_SNAPSHOTS} existe (es lo que se commitea)")
    if not os.path.exists(odds_store.CSV_SNAPSHOTS):
        return
    with open(odds_store.CSV_SNAPSHOTS, encoding='utf-8', newline='') as f:
        filas = list(csv.DictReader(f))
    check(len(filas) > 0, f"el CSV de fotos tiene datos ({len(filas)} filas)")
    # v76: el CSV ya no lleva SOLO fotos. También guarda el backfill de
    # BetExplorer, que tampoco se puede reconstruir desde el repositorio (se
    # podría volver a raspar, pero eso depende de que un sitio de terceros siga
    # en pie). Lo que NO debe entrar son los cierres de football-data, que sí
    # salen de los `historico_*.csv` versionados: duplicarlos engordaría el
    # repositorio sin aportar nada.
    fases = {r.get('fase') for r in filas}
    fuentes = {r.get('source_file') for r in filas}
    check(fases <= {'snapshot', 'cierre'}, f"fases esperadas en el CSV ({fases})")
    regenerables = [r for r in filas
                    if r.get('fase') == 'cierre' and r.get('source_file') != 'betexplorer']
    check(not regenerables,
          f"el CSV no duplica los cierres regenerables de football-data "
          f"({len(regenerables)} colados)")
    check('betexplorer' in fuentes,
          "el backfill de BetExplorer viaja en el repositorio (no es regenerable)")
    check(any(r.get('odds_btts_yes') for r in filas),
          "hay precios de BTTS acumulándose (única fuente: Pinnacle)")

    # y tienen que poder recargarse sin duplicar
    ruta = '_test_rehidratar.db'
    if os.path.exists(ruta):
        os.remove(ruta)
    con = odds_store.conectar(ruta)
    n1 = odds_store.importar_snapshots(con, odds_store.CSV_SNAPSHOTS)
    odds_store.importar_snapshots(con, odds_store.CSV_SNAPSHOTS)
    total = con.execute("SELECT COUNT(*) FROM historical_odds").fetchone()[0]
    con.close()
    os.remove(ruta)
    check(total == n1,
          f"recargar dos veces no duplica ({n1} insertadas, {total} en tabla)")


def test_backfill_betexplorer():
    """
    v76: el backfill histórico tiene que existir y ser CORRECTO.

    El riesgo real de un backfill no es que falten datos, es que asigne la
    cuota del partido equivocado: contamina el backtest sin dejar rastro. Por
    eso `backfill_betexplorer.enlazar` empareja por fecha + marcador exacto y
    solo usa el nombre para desempatar; aquí se comprueba que las cuotas
    importadas son plausibles y que no hay partidos duplicados por fuente.
    """
    import sqlite3
    if not os.path.exists('odds_historico.db'):
        check(False, 'odds_historico.db existe')
        return
    con = sqlite3.connect('odds_historico.db')
    try:
        n = con.execute("SELECT COUNT(*) FROM historical_odds "
                        "WHERE source_file='betexplorer'").fetchone()[0]
        ligas = con.execute("SELECT COUNT(DISTINCT league_key) FROM historical_odds "
                            "WHERE source_file='betexplorer'").fetchone()[0]
        check(n > 3000, f"backfill de BetExplorer con volumen ({n} cuotas)")
        check(ligas >= 10, f"backfill en {ligas} competiciones que antes no tenían nada")

        # margen plausible: ninguna terna puede implicar arbitraje
        malas = con.execute(
            "SELECT COUNT(*) FROM historical_odds WHERE source_file='betexplorer' "
            "AND odds_home IS NOT NULL AND odds_draw IS NOT NULL "
            "AND odds_away IS NOT NULL "
            "AND (1.0/odds_home + 1.0/odds_draw + 1.0/odds_away) < 1.0").fetchone()[0]
        check(malas == 0,
              f"ninguna cuota importada implica arbitraje (margen<1) — {malas} malas")

        # un partido no puede tener dos cierres de la misma casa
        dup = con.execute(
            "SELECT COUNT(*) FROM (SELECT match_id, bookmaker, COUNT(*) c "
            "FROM historical_odds WHERE fase='cierre' "
            "GROUP BY match_id, bookmaker HAVING c > 1)").fetchone()[0]
        check(dup == 0, f"sin cierres duplicados por partido y casa ({dup})")
    except sqlite3.OperationalError as e:
        check(False, f"consulta de backfill ({e})")
    finally:
        con.close()


def test_playdoit_integrada():
    """v76: Playdoit es la casa donde apuesta el usuario — si se cae, la Capa 1
    pierde el precio que de verdad puede tomar, así que tiene que estar
    cableada y dar márgenes plausibles."""
    import cuotas_multi as cm
    check(hasattr(cm, '_indice_playdoit'), "cuotas_multi expone _indice_playdoit")
    check(hasattr(cm, 'diagnostico_casas'), "cuotas_multi expone diagnostico_casas")
    try:
        idx = cm._indice_pdt('futbol')
    except Exception as e:
        check(False, f"el índice de Playdoit carga ({type(e).__name__}: {e})")
        return
    check(len(idx) > 100, f"Playdoit devuelve partidos ({len(idx)})")
    malos = 0
    for v in idx.values():
        c = v.get('cuotas') or {}
        if c.get('home') and c.get('draw') and c.get('away'):
            if 1 / c['home'] + 1 / c['draw'] + 1 / c['away'] < 1.0:
                malos += 1
    check(malos == 0,
          f"ninguna terna de Playdoit implica arbitraje ({malos}) — "
          f"si las hubiera, el parseo estaría mal")


def test_ledger_sin_fuga():
    if not os.path.exists('pick_ledger.csv'):
        print('AVISO pick_ledger.csv no existe todavía; se omiten sus comprobaciones')
        return
    import pandas as pd
    d = pd.read_csv('pick_ledger.csv')
    check(len(d) > 1000, f"ledger con volumen suficiente ({len(d)} filas)")
    check({'p_home', 'p_draw', 'p_away', 'resultado', 'match_id', 'pliegue'}
          <= set(d.columns), "el ledger lleva el VECTOR completo y el match_id")

    # sin filtrar: tiene que haber picks de baja probabilidad y de EV negativo
    p = d[['p_home', 'p_draw', 'p_away']].max(axis=1)
    check(float(p.min()) < 0.50,
          f"el ledger NO está pre-filtrado por probabilidad (mín {p.min():.3f})")

    # probabilidades normalizadas
    s = d[['p_home', 'p_draw', 'p_away']].sum(axis=1)
    check(bool(((s - 1).abs() < 1e-3).all()),
          "todas las probabilidades suman 1")

    # los pliegues tienen que ser CRONOLÓGICOS dentro de cada liga: si un
    # pliegue posterior contuviera fechas anteriores habría fuga temporal
    malos = []
    for liga, g in d.groupby('liga'):
        top = g.groupby('pliegue')['fecha'].max().sort_index()
        bot = g.groupby('pliegue')['fecha'].min().sort_index()
        for i in range(len(top) - 1):
            if bot.iloc[i + 1] < top.iloc[i]:
                malos.append(liga)
                break
    check(not malos, f"pliegues cronológicos en todas las ligas ({malos[:5]})")

    check(int(d['match_id'].duplicated().sum()) == 0,
          "sin partidos repetidos en el ledger")


def test_umbrales_publicados():
    if not os.path.exists('umbrales_capa1.json'):
        print('AVISO umbrales_capa1.json no existe todavía; se omite')
        return
    with open('umbrales_capa1.json', encoding='utf-8') as f:
        u = json.load(f)
    check('global' in u and 'ligas' in u,
          "umbrales_capa1.json tiene la forma esperada")
    met = u.get('global_metricas') or {}
    if u.get('global'):
        opt = met.get('optimizado') or {}
        check((opt.get('p5') or -1) > 0,
              f"los umbrales globales publicados tienen bootstrap p5 > 0 ({opt.get('p5')})")
    else:
        check(True, "sin umbrales globales adoptados (no superaron la regla) — "
                    "se mantienen los de edge_engine")


def test_alpha_finder_lee_umbrales():
    import importlib
    import alpha_finder
    importlib.reload(alpha_finder)
    check(hasattr(alpha_finder, 'umbrales_liga'),
          "alpha_finder expone umbrales_liga()")
    if hasattr(alpha_finder, 'umbrales_liga'):
        u = alpha_finder.umbrales_liga('_liga_inexistente_')
        check({'prob_min', 'ev_min', 'cuota_min'} <= set(u),
              f"umbrales_liga devuelve el contrato completo ({sorted(u)})")
        check(u['prob_min'] > 0 and u['cuota_min'] >= 1.0,
              "los valores por defecto son sensatos")


if __name__ == '__main__':
    print('=== v75: catálogo de ligas ===')
    test_catalogo_sin_duplicados()
    test_ligas_migradas()
    print('\n=== v75: verificación de fuente ===')
    test_verificacion_de_fuente()
    print('\n=== v75: almacén de cuotas ===')
    test_esquema_e_idempotencia()
    test_db_poblada()
    test_snapshots_persisten_en_el_repo()
    test_backfill_betexplorer()
    print('\n=== v76: casas de apuestas ===')
    test_playdoit_integrada()
    print('\n=== v75: ledger de predicciones ===')
    test_ledger_sin_fuga()
    print('\n=== v75: umbrales en producción ===')
    test_umbrales_publicados()
    test_alpha_finder_lee_umbrales()
    print(f"\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    for f in FALLOS:
        print('  - ' + f)
    sys.exit(1 if FALLOS else 0)
