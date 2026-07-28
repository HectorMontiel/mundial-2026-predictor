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


def test_claves_de_tenista():
    """
    v77: los nombres de tenista tienen que colapsar a la misma clave se
    escriban como se escriban, o el mismo partido entra dos veces.
    Cada caso viene de un duplicado real observado en producción.
    """
    import cuotas_multi as cm
    iguales = [
        ('Andrés Andrade (PAN)', 'Andres Andrade'),     # el (PAN) hacía de apellido
        ('Martin Damm', 'Martin Damm Jr'),              # el sufijo hacía de apellido
        ('Mensik J.', 'Jakub Mensik'),
        ('Félix Auger-Aliassime', 'Auger-Aliassime F.'),  # apellido compuesto
        ('Juan Martín del Potro', 'Del Potro J.'),        # partícula
        ('Botic van de Zandschulp', 'Van De Zandschulp B.'),  # doble partícula
        ('Carlos Alcaraz (ESP)', 'Alcaraz C.'),
    ]
    for a, b in iguales:
        check(cm._clave_tenista(a) == cm._clave_tenista(b),
              f"«{a}» y «{b}» dan la misma clave "
              f"({cm._clave_tenista(a)} vs {cm._clave_tenista(b)})")
    # y jugadores distintos NO pueden colapsar
    distintos = [('Zverev A.', 'Zverev M.'),
                 ('Alex de Minaur', 'Juan Martin del Potro'),
                 ('Carlos Alcaraz', 'Jaume Munar')]
    for a, b in distintos:
        check(cm._clave_tenista(a) != cm._clave_tenista(b),
              f"«{a}» y «{b}» siguen siendo jugadores distintos")


def test_orientacion_local_visitante():
    """
    v77: en MLB/NBA el evento se llama «VISITANTE @ LOCAL», al revés que en
    fútbol. Fiarse del orden de `competitorIds` invertía todos los partidos de
    béisbol y generaba picks del equipo equivocado con un EV inventado (+49 %).
    Se comprueba contra Pinnacle, que sí declara los bandos.
    """
    import cuotas_multi as cm
    try:
        pin = cm._indice('mlb')
        pdt = cm._indice_pdt('mlb')
    except Exception as e:
        check(False, f"los índices de MLB cargan ({type(e).__name__}: {e})")
        return
    if not pin or not pdt:
        print('AVISO sin partidos de MLB ahora mismo; se omite la comprobación')
        return
    coincidencias, invertidos = 0, 0
    for k, v in pdt.items():
        p = pin.get(k)
        if not p:
            continue
        coincidencias += 1
        cp, cv = p.get('cuotas') or {}, v.get('cuotas') or {}
        if not (cp.get('home') and cv.get('home')):
            continue
        # si estuviera invertido, el 'home' de uno se parecería al 'away' del otro
        d_ok = abs(cp['home'] - cv['home'])
        d_inv = abs(cp['home'] - (cv.get('away') or 0))
        if d_inv < d_ok - 0.15:
            invertidos += 1
    if coincidencias:
        check(invertidos == 0,
              f"Playdoit y Pinnacle coinciden en el bando local en MLB "
              f"({invertidos} invertidos de {coincidencias} comparables)")
    else:
        print('AVISO ningún partido de MLB en común entre casas; se omite')


def test_playdoit_multideporte():
    """v77: Playdoit tiene que cubrir los cuatro deportes. El mercado ganador
    lleva un `typeId` distinto en cada uno (1 fútbol, 186 tenis, 223 NBA,
    251 MLB), y fijarlo a 1 dejaba tres deportes a cero EN SILENCIO."""
    import cuotas_multi as cm
    vivos = 0
    for dep in ('futbol', 'tenis', 'mlb', 'nba'):
        try:
            n = len(cm._indice_pdt(dep))
        except Exception as e:
            check(False, f"Playdoit {dep} carga ({type(e).__name__})")
            continue
        if n:
            vivos += 1
        print(f"      · Playdoit {dep}: {n} partidos")
    check(vivos >= 2,
          f"Playdoit devuelve partidos en al menos 2 deportes ({vivos}/4 con "
          f"partidos ahora mismo)")


def test_precio_accionable():
    """v77: el EV se calcula con el precio que el usuario PUEDE tomar."""
    import cuotas_multi as cm
    check(cm.CASA_PRIORITARIA == 'Playdoit', "la casa prioritaria es Playdoit")
    c = {'casas': {'Pinnacle': {'home': 2.0, 'away': 2.0},
                   'Playdoit': {'home': 1.9, 'away': 2.3}},
         'mejor': {'home': {'cuota': 2.0, 'casa': 'Pinnacle'},
                   'away': {'cuota': 2.3, 'casa': 'Playdoit'}},
         'preferida': {'home': {'cuota': 1.9, 'casa': 'Playdoit',
                                'mejor_alternativa': 'Pinnacle',
                                'ventaja_alternativa': 0.0526},
                       'away': {'cuota': 2.3, 'casa': 'Playdoit',
                                'mejor_alternativa': 'Playdoit',
                                'ventaja_alternativa': 0.0}}}
    a = cm.precio_accionable(c, 'home')
    check(a and a['casa'] == 'Playdoit' and a['cuota'] == 1.9,
          f"se toma el precio de Playdoit aunque otro sea mejor ({a})")
    check(a and a['ventaja_alternativa'] > 0,
          "y se informa de cuánto se deja en la otra casa")
    # sin Playdoit, cae al mejor del mercado
    c2 = dict(c, preferida={})
    b = cm.precio_accionable(c2, 'home')
    check(b and b['casa'] == 'Pinnacle',
          f"sin Playdoit se usa el mejor del mercado ({b})")


def test_calibracion_confianza():
    """
    v77: la pestaña «Máxima Confianza» no puede prometer lo que no cumple.
    Medido: el modelo dice 79,6 % en la banda ≥0,75 y acierta el 57,8 %.
    """
    if not os.path.exists('calibracion_confianza.json'):
        check(False, 'calibracion_confianza.json existe')
        return
    with open('calibracion_confianza.json', encoding='utf-8') as f:
        cal = json.load(f)
    check(cal.get('n_total', 0) > 10000,
          f"calibrado sobre muestra grande ({cal.get('n_total')} predicciones)")
    bandas = [b for b in cal.get('bandas', []) if b.get('acierto') is not None]
    check(len(bandas) >= 4, f"{len(bandas)} bandas con muestra suficiente")
    u = cal.get('umbral_recomendado')
    check(u and 0.55 <= u <= 0.80,
          f"umbral recomendado en rango sensato ({u})")

    import calibracion_confianza as cc
    # la banda alta tiene que estar marcada como sobreconfiada
    alta = [b for b in bandas if b['desde'] >= 0.75]
    if alta:
        check(alta[0]['sesgo'] > 0.10,
              f"la banda ≥0,75 está sobreconfiada y queda registrado "
              f"(sesgo {alta[0]['sesgo']:+.1%})")
        aviso = cc.aviso_calibracion(0.79)
        check(bool(aviso), f"y se genera aviso para el usuario ({aviso})")


def test_combinadas_multideporte():
    """v77: una combinada no puede tener dos patas del mismo partido ni
    quedarse en un solo deporte (correlación)."""
    import cross_sport_parlay as csp
    picks = [
        {'deporte': 'Fútbol', 'liga': 'L1', 'partido': 'A vs B',
         'apuesta': 'Gana A', 'prob': 0.70, 'cuota': 1.60},
        {'deporte': 'Fútbol', 'liga': 'L1', 'partido': 'A vs B',
         'apuesta': 'Más de 1.5', 'prob': 0.75, 'cuota': 1.55},
        {'deporte': 'Tenis', 'liga': 'ATP', 'partido': 'C vs D',
         'apuesta': 'Gana C', 'prob': 0.68, 'cuota': 1.70},
        {'deporte': 'MLB', 'liga': 'MLB', 'partido': 'E @ F',
         'apuesta': 'Gana F', 'prob': 0.66, 'cuota': 1.75},
    ]
    combis = csp.generar(picks, [])
    check(bool(combis), f"se generan combinadas ({len(combis)})")
    for c in combis:
        partidos = [p['partido'] for p in c['patas']]
        check(len(partidos) == len(set(partidos)),
              f"la combinada {c['perfil']} no repite partido")
        check(len(c['deportes']) >= 2,
              f"la combinada {c['perfil']} cruza deportes ({c['deportes']})")
        check(c['stake_sugerido_pct'] >= 0, "stake sugerido no negativo")
    # un solo deporte no debe producir nada
    solo_uno = [p for p in picks if p['deporte'] == 'Fútbol']
    check(csp.generar(solo_uno, []) == [],
          "con un solo deporte NO se generan combinadas")


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
    print('\n=== v77: casas, deportes y orientación ===')
    test_playdoit_multideporte()
    test_orientacion_local_visitante()
    test_precio_accionable()
    print('\n=== v77: tenis y pestañas nuevas ===')
    test_claves_de_tenista()
    test_calibracion_confianza()
    test_combinadas_multideporte()
    print('\n=== v75: ledger de predicciones ===')
    test_ledger_sin_fuga()
    print('\n=== v75: umbrales en producción ===')
    test_umbrales_publicados()
    test_alpha_finder_lee_umbrales()
    print(f"\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    for f in FALLOS:
        print('  - ' + f)
    sys.exit(1 if FALLOS else 0)
