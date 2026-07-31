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


def test_handicap_medido():
    """
    v87: el hándicap asiático deja de ser el mercado sin medición.

    No hizo falta histórico de líneas asiáticas: para calibrar hace falta la
    probabilidad del modelo y si se cubrió, y las dos se reconstruyen de la
    MISMA matriz de marcadores que usa `alpha_finder`, con los λ y las
    probabilidades 1X2 fuera de muestra que ya estaban en los ledgers.

    Resulta ser el mercado mejor calibrado: sesgos de −0,5 % a +0,7 %.
    """
    import calibracion_confianza as cc
    check(cc.hay_medicion('Hándicap'), "«Hándicap» tiene medición")
    check(cc.hay_medicion('Hándicap asiático'),
          "«Hándicap asiático» resuelve al mismo mercado")
    check(cc.hay_medicion('Handicap'), "sin tilde también resuelve")

    r = cc.probabilidad_real(0.72, 'Hándicap')
    check(r is not None, "devuelve un número medido")
    check(r <= 0.72 + 1e-9, f"y sigue sin inflar ({r:.3f} <= 0.72)")

    import json
    d = json.load(open('calibracion_confianza.json', encoding='utf-8'))
    b = (d.get('bandas_por_mercado') or {}).get('Hándicap') or []
    con_dato = [x for x in b if x.get('acierto') is not None]
    check(len(con_dato) >= 5,
          f"hay bandas con muestra suficiente ({len(con_dato)} de {len(b)})")
    peor = max(abs(x['sesgo']) for x in con_dato)
    check(peor < 0.05,
          f"el hándicap está bien calibrado (peor sesgo {peor:+.3f})")

    # y cada mercado sigue con SU tabla
    vals = {m: cc.probabilidad_real(0.80, m)
            for m in ('Goles', 'BTTS', 'Hándicap')}
    check(len(set(round(v, 4) for v in vals.values() if v is not None)) == 3,
          f"los tres mercados dan cifras distintas ({vals})")


def test_modelos_portables():
    """
    v87: los modelos entrenados en el runner de Linux se cargan en Windows.

    El workflow serializa con la rueda de Linux y esos `modelo.joblib` daban
    «input stream corrupted» en Windows con la MISMA versión de XGBoost: 43 de
    43 ligas reentrenadas. No era corrupción (v86 lo descartó midiendo).

    La causa: el pickle guarda el formato de SERIALIZACIÓN
    (`XGBoosterSerializeToBuffer`), que XGBoost documenta como dependiente del
    entorno. Dentro lleva la sección «Model», que sí es portable. La reparación
    la recorta y la carga con `Booster.load_model`.
    """
    import modelos_portables as mp
    check(hasattr(mp, 'cargar'), "existe el cargador con reparación")
    check(mp.MARCA_MODEL == b'L\x00\x00\x00\x00\x00\x00\x00\x05Model',
          "la marca busca la clave «Model», no «learner»")

    # el recorte tiene que fallar limpio con basura, no devolver algo raro
    check(mp.recortar_a_modelo(b'') is None, "sin datos devuelve None")
    check(mp.recortar_a_modelo(b'no soy un booster') is None,
          "con basura devuelve None (no adivina)")

    check(mp.es_error_de_plataforma(Exception('input stream corrupted')),
          "reconoce el error de plataforma")
    check(not mp.es_error_de_plataforma(Exception('otra cosa')),
          "y no confunde otros errores")

    # y el cargador no cambia nada donde el joblib ya funciona
    import glob
    import joblib
    import numpy as np
    for r in sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib'))):
        try:
            a = joblib.load(r)
        except Exception:
            continue
        b = mp.cargar(r)
        n = getattr(a, 'n_features_in_', None)
        if not n:
            continue
        X = np.random.RandomState(0).randn(12, n)
        d = float(np.abs(a.predict_proba(X) - b.predict_proba(X)).max())
        check(d < 1e-9,
              f"la reparación no altera un modelo que ya cargaba "
              f"(diferencia {d:.1e})")
        break

    # el motor de liga usa el cargador
    fuente = open('league_engine.py', encoding='utf-8').read()
    check('modelos_portables' in fuente,
          "ClubEngine carga por la ruta con reparación")


def test_ficha_anclada_al_mercado():
    """
    v87: la ficha se ancla al mercado, igual que los picks desde la v75.

    El caso: Puebla vs Chivas mostraba Puebla 53,6 % cuando Pinnacle, quitado
    el margen, daba Puebla 18,8 % y Chivas 59,4 %. Las cuotas estaban en la
    app; la ficha no las miraba porque `_cuotas_partido` sólo lee
    `odds_actuales.json` (4 partidos) y el ancla sólo alimentaba al MESM y al
    `blend_mercado` (configurado en 2 ligas).

    Medido sobre 28.555 filas del ledger con cuota, donde el modelo se aleja
    del mercado más de 0,25: precisión 33,6 % -> 55,5 % y ECE 0,2795 -> 0,0644.
    """
    fuente = open('league_engine.py', encoding='utf-8').read()
    check('_mercado_ficha' in fuente, "existe la búsqueda de mercado de la ficha")
    check('_tablon_con_presupuesto' in fuente,
          "el tablón de cuotas tiene presupuesto de tiempo (no bloquea la ficha)")
    check('PRESUPUESTO_MERCADO_S' in fuente,
          "el presupuesto es configurable por variable de entorno")
    check('calibracion_mercado' in fuente,
          "la ficha usa el encogimiento al mercado ya validado")

    # el orden de preferencia tiene que ser mercado ANTES que ELO
    i_mkt = fuente.find('mercado_info = ')
    i_elo = fuente.find("import calibracion_elo as _celo")
    check(0 < i_mkt < i_elo,
          "el ancla de mercado va ANTES del prior de ELO (es mejor referencia)")

    # los picks siguen sin pasar por aquí
    af = open('alpha_finder.py', encoding='utf-8').read()
    check(af.count('prior_elo=False') >= 2,
          "alpha_finder sigue desactivando la corrección de la ficha")

    # el interruptor viejo sigue funcionando
    import inspect
    import league_engine as le
    sig = inspect.signature(le.ClubEngine.predecir)
    check('anclar' in sig.parameters and 'prior_elo' in sig.parameters,
          f"predecir acepta `anclar` y el `prior_elo` antiguo ({list(sig.parameters)})")

    # y la corrección hacia el mercado hace lo que dice
    import calibracion_mercado as cm
    p0 = {'home': 0.536, 'draw': 0.248, 'away': 0.216}
    mk = {'home': 0.188, 'draw': 0.218, 'away': 0.594}
    q, info = cm.corregir(p0, mk, 'liga_mx')
    check(info.get('aplicado'), "el encogimiento al mercado se aplica en liga_mx")
    check(q['away'] > q['home'],
          f"con el mercado dando 59,4 % al visitante, la ficha ya no hace "
          f"favorito al local ({q['home']:.1%} vs {q['away']:.1%})")
    check(abs(sum(q.values()) - 1) < 1e-9, "las probabilidades siguen sumando 1")


def test_calibracion_de_totales_y_btts():
    """
    v86: Goles y BTTS dejan de decir «no medido» y llevan su acierto real.

    Medido sobre 47.794 partidos fuera de muestra (`build_ledger_totales.py`,
    walk-forward de los regresores de Poisson):

        Goles, banda >=0,75 : el modelo dice 83,1 % y acierta 74,5 %
        BTTS,  banda >=0,75 : el modelo dice 80,6 % y acierta 53,2 %

    El BTTS está PLANO (51-55 % en todas las bandas): es una moneda al aire
    vendida como confianza, y ahora se ve.
    """
    import calibracion_confianza as cc
    check(cc.hay_medicion('Goles'), "Goles ya tiene medición propia")
    check(cc.hay_medicion('BTTS'), "BTTS ya tiene medición propia")
    check(cc.hay_medicion('1X2'), "1X2 la sigue teniendo")
    # v87: el hándicap ya tiene la suya (ver test_handicap_medido). Lo que
    # sigue sin medición es cualquier mercado del que no haya ledger.
    check(not cc.hay_medicion('Córners'),
          "un mercado sin ledger sigue diciendo que no tiene medición")

    # cada mercado usa SU tabla, no la prestada de otro
    g = cc.probabilidad_real(0.80, 'Goles')
    b = cc.probabilidad_real(0.80, 'BTTS')
    check(g is not None and b is not None, "los dos devuelven número")
    check(abs(g - b) > 0.10,
          f"Goles y BTTS dan cifras DISTINTAS ({g:.3f} vs {b:.3f}); "
          f"si coincidieran estarían compartiendo tabla")
    check(b < 0.60,
          f"el BTTS al 80 % del modelo se muestra como {b:.1%}, no como 80 %")

    # v86: la corrección nunca infla
    for merc in ('1X2', 'Goles', 'BTTS'):
        for p in (0.52, 0.57, 0.62, 0.67, 0.72, 0.80):
            r = cc.probabilidad_real(p, merc)
            if r is not None:
                check(r <= p + 1e-9,
                      f"{merc} al {p:.0%}: el histórico no infla "
                      f"({r:.1%} <= {p:.0%})")
    # y el caso concreto que lo motivó
    check(abs(cc.probabilidad_real(0.72, '1X2') - 0.72) < 1e-9,
          "la banda 1X2 0,70-0,75 (n=33, IC [69,7 %, 90,9 %]) ya no sube "
          "el 71,3 % a 81,8 %")

    # las bandas llevan intervalo, no sólo el punto
    import json
    d = json.load(open('calibracion_confianza.json', encoding='utf-8'))
    con_ic = [x for x in d['bandas']
              if x.get('acierto') is not None and 'acierto_p5' in x]
    check(len(con_ic) >= 4,
          f"las bandas de 1X2 llevan intervalo del acierto ({len(con_ic)})")
    check('bandas_por_mercado' in d and
          {'Goles', 'BTTS'} <= set(d['bandas_por_mercado']),
          "el JSON guarda las bandas por mercado")


def test_guardia_precio_imposible():
    """
    v86: un precio corrupto no puede entrar en la Capa 1.

    `valor_vs_sharp` ordena por EV descendente y no comprobaba que la cuota
    fuese un precio POSIBLE, así que un feed con una coma decimal desplazada se
    colocaba el primero. Medido en el histórico de tenis: una única apuesta a
    100x el precio de Pinnacle aporta 1,21 puntos del ROI de +4,57 % de la WTA.
    """
    import cuotas_multi as cm
    check(hasattr(cm, 'RATIO_MAX_SOBRE_SHARP'),
          "existe el techo de precio frente al sharp")
    r = getattr(cm, 'RATIO_MAX_SOBRE_SHARP', None)
    check(r and 1.2 <= r <= 3.0,
          f"el techo es plausible ({r}x el precio de Pinnacle)")

    # el filtro se aplica de verdad: se simula un feed corrupto
    fuente = open('cuotas_multi.py', encoding='utf-8').read()
    check('descartes_imposibles' in fuente,
          "los descartes se reportan en vez de desaparecer en silencio")
    check('RATIO_MAX_SOBRE_SHARP * pin_lado' in fuente,
          "el techo se compara contra la cuota de Pinnacle del MISMO lado")
    # y NO se filtra por overround, que bloqueaba line shopping legítimo.
    # Se miran sólo líneas de CÓDIGO: el comentario de v86 explica justamente
    # por qué ese filtro se descartó, así que contiene la palabra.
    cuerpo = fuente.split('def valor_vs_sharp')[1][:6000]
    codigo = [l for l in cuerpo.splitlines()
              if l.strip() and not l.strip().startswith('#')]
    check(not any('overround' in l for l in codigo),
          "no se filtra por overround (bloqueaba 3,6-4,8 % de picks legítimos)")


def test_prior_elo_solo_en_la_ficha():
    """
    v86: el encogimiento hacia el ELO es de la FICHA, no de los picks.

    Se midió que el modelo apenas responde a la fuerza de los equipos: subir
    600 puntos de ELO mueve P(local) +0,075 de mediana, y en Liga MX +0,017
    (el caso Puebla). La corrección se aplica donde el modelo va suelto —sin
    ancla de mercado— y `alpha_finder` la desactiva para que Capa 1 y Capa 2
    salgan idénticas.
    """
    import calibracion_elo as ce
    check(ce.hay_prior(), "la tabla del prior de ELO está generada")
    check(0.5 <= ce.W_FICHA < 1.0, f"w de la ficha en rango ({ce.W_FICHA})")

    # el prior tiene que ser MONÓTONO: más ELO -> más P(local)
    ps = [ce.prior(d)['home'] for d in (-0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75)]
    check(all(b > a for a, b in zip(ps, ps[1:])),
          f"el prior de ELO es monótono creciente ({[round(p, 3) for p in ps]})")
    pa = [ce.prior(d)['away'] for d in (-0.75, 0.0, 0.75)]
    check(all(b < a for a, b in zip(pa, pa[1:])),
          f"y decreciente para el visitante ({[round(p, 3) for p in pa]})")

    # corregir no debe romperse sin datos
    p0 = {'home': 0.5, 'draw': 0.3, 'away': 0.2}
    q, info = ce.corregir(p0, None)
    check(q == p0 and not info['aplicado'],
          "sin ELO devuelve las probabilidades intactas")
    q, info = ce.corregir(p0, 0.0, w=1.0)
    check(q == p0 and not info['aplicado'], "w=1 desactiva la corrección")
    q, info = ce.corregir(p0, -0.62)
    check(info['aplicado'] and abs(sum(q.values()) - 1) < 1e-9,
          "con ELO se aplica y las probabilidades suman 1")
    check(q['home'] < p0['home'],
          f"con el ELO en contra baja P(local) ({q['home']:.3f} < 0.5)")

    # y los picks NO pasan por aquí
    af = open('alpha_finder.py', encoding='utf-8').read()
    check(af.count('prior_elo=False') >= 2,
          "alpha_finder desactiva el prior en los dos barridos de fútbol")


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


def test_calibracion_multideporte():
    """
    v78: la corrección hacia el mercado tiene que llegar a los tres deportes,
    no solo al fútbol. Antes `cargar()` exigía las tres cuotas (1X2) y
    descartaba EN SILENCIO todo mercado a dos vías.
    """
    import calibracion_mercado as cm
    for clave in ('atp', 'wta', 'mlb'):
        w = cm.peso_modelo(clave)
        check(w < 1.0, f"{clave} tiene peso de calibración propio (w={w})")
    check(hasattr(cm, 'corregir_dos_vias'),
          "calibracion_mercado expone corregir_dos_vias (deportes sin empate)")
    # el encogimiento tiene que MOVER la probabilidad hacia el mercado
    p, info = cm.corregir_dos_vias(0.80, 2.50, 1.55, 'atp')
    check(info['aplicado'] and p < 0.80,
          f"la probabilidad se encoge hacia el mercado (0.80 -> {p:.3f})")
    # sin cuotas no hay hacia dónde encoger: degradación limpia
    p2, info2 = cm.corregir_dos_vias(0.80, None, None, 'atp')
    check(p2 == 0.80 and not info2['aplicado'],
          "sin cuota no se toca la probabilidad")


def test_ledger_multideporte_alineado():
    """
    v78: la guardia que destapó el fallo más grave de esta versión.

    Si las cuotas se pegan al partido equivocado, el log-loss del MERCADO sale
    peor que el azar — imposible en cuotas reales. Aquel desalineado no daba
    error: fabricaba un ROI de +37,68 % con p5 +31,7 %, justo lo que uno
    querría ver.
    """
    import numpy as np
    import pandas as pd
    if not os.path.exists('pick_ledger_total.csv'):
        print('AVISO pick_ledger_total.csv no existe; se omite')
        return
    d = pd.read_csv('pick_ledger_total.csv')
    check(d['deporte'].nunique() >= 3,
          f"el ledger cubre varios deportes ({sorted(d['deporte'].unique())})")
    import build_ledger_deportes as bl
    for dep, g in d.groupby('deporte'):
        v = bl.verificar_alineacion(g, dep)
        check(v['ok'],
              f"{dep}: cuotas alineadas con las predicciones "
              f"(log-loss del mercado {v.get('logloss_mercado')} < "
              f"azar {v.get('techo_azar')})")


def test_deportes_con_edge():
    """v78: solo entran en la Capa 1 los deportes cuyo ROI fuera de muestra
    es positivo Y su bootstrap p5 también. Misma regla que dejó fuera el
    Over/Under 2.5 en la v44."""
    import validacion_deportes as vd
    if not os.path.exists(vd.ARCHIVO):
        check(False, f"{vd.ARCHIVO} existe")
        return
    with open(vd.ARCHIVO, encoding='utf-8') as f:
        doc = json.load(f)
    deportes = doc.get('deportes') or {}
    check(len(deportes) >= 3, f"{len(deportes)} deportes evaluados")
    for dep, v in deportes.items():
        if 'mejor_roi' not in v:
            continue
        esperado = bool(v['mejor_roi'] > 0 and v['p5_mejor'] > 0)
        check(v['edge_validado'] == esperado,
              f"{dep}: el veredicto coincide con la regla "
              f"(ROI {v['mejor_roi']:+.2%}, p5 {v['p5_mejor']:+.2%})")
    # un deporte sin medición NO se castiga
    check(vd.tiene_edge('_deporte_inexistente_'),
          "un deporte sin medición se permite (no se castiga la falta de datos)")
    # y el motivo se puede mostrar
    fuera = [k for k, v in deportes.items() if not v.get('edge_validado', True)]
    for k in fuera:
        check(bool(vd.motivo(k)), f"{k} tiene motivo legible para la UI")


def test_monitor_playdoit():
    """v78: la cobertura de Playdoit decide qué picks son TOMABLES."""
    import monitor_playdoit as mp
    if not os.path.exists(mp.ARCHIVO):
        print('AVISO playdoit_cobertura.json no existe todavía; se omite')
        return
    with open(mp.ARCHIVO, encoding='utf-8') as f:
        d = json.load(f)
    check(d.get('competiciones', {}).get('futbol', 0) > 50,
          f"Playdoit cubre muchas competiciones de fútbol "
          f"({d.get('competiciones', {}).get('futbol')})")
    check(isinstance(mp.incidencias(), list),
          "el monitor produce incidencias para la UI")


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


# ---------------------------------------------------------------------------
# v79 — las causas raíz de esta versión, fijadas para que no vuelvan
# ---------------------------------------------------------------------------
def test_mlb_estado_fresco():
    """El estado del modelo de MLB no puede envejecer sin que nadie lo vea.

    En producción llevaba 304 días congelado (2025-09-28 mientras corría la
    temporada 2026) y no daba ningún error: solo devolvía probabilidades
    planas. Un test es la única forma de que eso vuelva a doler antes que al
    usuario.
    """
    import json as _j
    import pandas as _pd
    ruta = os.path.join('modelos', 'mlb', 'estado.json')
    if not os.path.exists(ruta):
        print('AVISO no hay estado de MLB; se omite')
        return
    with open(ruta, encoding='utf-8') as f:
        est = _j.load(f)
    fechas = [v.get('ult_fecha') for v in est.get('equipos', {}).values()
              if v.get('ult_fecha')]
    check(bool(fechas), 'el estado de MLB registra la última fecha por equipo')
    if not fechas:
        return
    dias = (_pd.Timestamp.today().normalize()
            - _pd.Timestamp(max(fechas)).normalize()).days
    # 200 días cubre el parón entre temporadas (octubre a marzo) sin dejar
    # pasar el caso real, que fueron 304 en plena temporada.
    check(dias <= 200,
          f'el estado de MLB no está obsoleto ({dias} días desde {max(fechas)})')
    check(len(est.get('equipos', {})) == 30,
          f"MLB tiene 30 equipos, no 31 ({len(est.get('equipos', {}))}) — "
          f"OAK y ATH son la misma franquicia")


def test_mlb_features_vivas():
    """Las features de abridor no pueden ser constantes en inferencia.

    `apuestas_dia` predecía sin abridores, así que DIFF_PIT_RA y MEDIA_PIT_RA
    salían con desviación típica 0,0000 en todos los partidos: un tercio del
    vector era ruido fijo, y justo el que más pesa en béisbol.
    """
    import numpy as _np
    try:
        from engines.mlb_engine import MLBEngine, FEATURES
        import mlb_statsapi
    except Exception as e:
        print(f'AVISO motor de MLB no disponible ({e}); se omite')
        return
    eng = MLBEngine().cargar_modelo()
    if not eng.listo:
        print('AVISO modelo de MLB no cargado; se omite')
        return
    eq = sorted((eng.estado.get('equipos') or {}).keys())
    pit = list((eng.estado.get('pitchers') or {}).keys())
    if len(eq) < 4 or len(pit) < 4:
        print('AVISO estado de MLB insuficiente; se omite')
        return
    # Se fabrican enfrentamientos con abridores REALES del estado, que es lo
    # que hace producción desde la v79.
    filas = []
    for i in range(0, min(len(eq) - 1, 12), 2):
        x = eng.construir_features(eq[i], eq[i + 1],
                                   home_pitcher=pit[i % len(pit)],
                                   away_pitcher=pit[(i + 1) % len(pit)])
        if x:
            filas.append(x)
    if len(filas) < 3:
        print('AVISO no se pudieron construir features; se omite')
        return
    M = _np.array(filas)
    for nombre in ('DIFF_PIT_RA', 'MEDIA_PIT_RA'):
        j = FEATURES.index(nombre)
        check(float(M[:, j].std()) > 1e-9,
              f'{nombre} varía en inferencia (no es una constante muerta)')


def test_mlb_entrenamiento_serializable():
    """`entrenar()` estaba roto desde la v78: `filas` guarda `Timestamp` y
    `json.dump` no sabe serializarlo. El modelo no se podía reentrenar y nadie
    lo notó porque el ledger usa `_dataset` en memoria."""
    import json as _j
    import pandas as _pd
    try:
        from engines.mlb_engine import _json_seguro
    except Exception as e:
        check(False, f'engines.mlb_engine expone _json_seguro ({e})')
        return
    muestra = {'filas': [(_pd.Timestamp('2026-07-28'), 'DET', 'KCA')]}
    try:
        texto = _j.dumps(muestra, default=_json_seguro)
        check('2026-07-28' in texto,
              'el estado de MLB con Timestamp se serializa a JSON')
    except Exception as e:
        check(False, f'el estado de MLB sigue sin serializarse: {e}')


def test_calibracion_segura_degrada():
    """Un fallo de calibración no puede tumbar un deporte entero.

    El AttributeError de `corregir_dos_vias` borró los 319 partidos de tenis
    del día. La corrección es calidad; el barrido es el producto.
    """
    try:
        import calibracion_segura as cs
    except Exception as e:
        check(False, f'calibracion_segura importable ({e})')
        return
    p, info = cs.encoger_dos_vias(0.80, 2.50, 1.55, 'atp')
    check(0.0 < p < 1.0, f'encoge y devuelve probabilidad válida ({p:.4f})')
    check(p < 0.80, 'la probabilidad se mueve HACIA el mercado')
    # sin cuota no hay hacia dónde encoger: degradación limpia, sin excepción
    p2, info2 = cs.encoger_dos_vias(0.80, None, None, 'atp')
    check(abs(p2 - 0.80) < 1e-9 and not info2.get('aplicado'),
          'sin cuota devuelve la probabilidad intacta y no lanza')
    # liga inexistente: tampoco puede reventar
    p3, _ = cs.encoger_dos_vias(0.60, 2.0, 2.0, 'liga_que_no_existe_v79')
    check(0.0 < p3 < 1.0, 'una liga desconocida no rompe el encogimiento')


def test_inferencia_rapida_no_cambia_nada():
    """`n_jobs=1` es una optimización, no un cambio de modelo.

    Matiz medido, porque importa: prediciendo **fila a fila** —que es lo que
    hace producción— el resultado es bit a bit idéntico (diferencia 0,0).
    Prediciendo un LOTE aparece una diferencia de ~1e-16, y no es del modelo:
    es que sumar los votos de los árboles en distinto orden da distinto último
    bit (la suma en coma flotante no es asociativa). Además no es determinista
    entre ejecuciones, así que exigir igualdad exacta haría el test
    intermitente. Se comprueba lo que de verdad se afirma: que la diferencia
    es del orden del epsilon de máquina y no puede mover ninguna decisión.
    """
    import glob
    import numpy as _np
    try:
        import joblib
        import inferencia_rapida as ir
    except Exception as e:
        print(f'AVISO inferencia_rapida no disponible ({e}); se omite')
        return
    rutas = sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib')))
    if not rutas:
        print('AVISO no hay modelos de liga; se omite')
        return
    # v86 — Los `modelo.joblib` que publica el workflow de reentrenamiento se
    # serializan en el runner de GitHub (Linux, rueda
    # `xgboost-3.3.0-manylinux_2_28_x86_64`) y NO se pueden deserializar con la
    # rueda de Windows de la MISMA versión: XGBoost lanza «input stream
    # corrupted».
    #
    # No es corrupción del fichero ni conversión de saltos de línea: el blob del
    # repo coincide byte a byte con el disco, `.gitattributes` ya declara
    # `*.joblib binary`, la proporción de CRLF es idéntica a la de un modelo
    # sano (0,4 %, ruido), y los artefactos de sklearn del MISMO commit
    # (escalador, reg_local, reg_visit) cargan sin problema.
    #
    # Producción NO está afectada: el paso «Verificar que todos los modelos se
    # pueden cargar» del workflow recorre `modelos/*/*.joblib` en Linux y el run
    # del 2026-07-31 reportó «Ilegibles restaurados: 0». Streamlit Cloud también
    # es Linux.
    #
    # Se detecta y se avisa en vez de reventar con un traceback de XGBoost, que
    # hacía parecer que el fallo era del cambio que se estaba probando.
    rutas_ok = []
    for r in rutas:
        try:
            joblib.load(r)
            rutas_ok.append(r)
        except Exception:
            pass
    if not rutas_ok:
        print(f'AVISO ninguno de los {len(rutas)} modelos de liga se puede '
              f'cargar en {sys.platform}. Son artefactos serializados por el '
              f'workflow en Linux; no son deserializables con la rueda de '
              f'Windows de XGBoost. Producción (Linux) no está afectada. '
              f'Se omite este test.')
        return
    if len(rutas_ok) < len(rutas):
        print(f'AVISO {len(rutas) - len(rutas_ok)} de {len(rutas)} modelos no '
              f'cargan en {sys.platform} (serializados en Linux por el '
              f'workflow); se usa uno de los {len(rutas_ok)} que sí.')
    m1, m2 = joblib.load(rutas_ok[0]), joblib.load(rutas_ok[0])
    n = ir.secuencial(m2)
    check(n > 0, f'inferencia_rapida secuencializa estimadores ({n})')
    X = _np.random.RandomState(0).randn(8, m1.n_features_in_)
    # fila a fila: el camino real de producción
    d_fila = max(float(_np.abs(m1.predict_proba(X[i:i + 1])
                               - m2.predict_proba(X[i:i + 1])).max())
                 for i in range(len(X)))
    # v82 — la v79 exigía igualdad EXACTA aquí, y era una afirmación demasiado
    # fuerte sacada de una sola observación que dio 0,0. El test resultó
    # intermitente: fila a fila también aparece de vez en cuando una diferencia
    # de ~1e-16. Es el mismo efecto que en lote —la suma en coma flotante no es
    # asociativa— solo que más raro. Lo que se puede afirmar, y se afirma, es
    # que la diferencia es del orden del epsilon de máquina y no puede mover
    # ninguna decisión.
    check(d_fila < 1e-12,
          f'fila a fila la diferencia es epsilon de máquina (dif = {d_fila:.1e})')
    d_lote = float(_np.abs(m1.predict_proba(X) - m2.predict_proba(X)).max())
    check(d_lote < 1e-12,
          f'en lote la diferencia es epsilon de máquina, no del modelo '
          f'(max|dif| = {d_lote:.1e})')


def test_ledger_total_reproducible():
    """`pick_ledger_total.csv` decide qué deportes entran en la Capa 1 y no lo
    escribía ningún script: se había hecho a mano en la v78."""
    import pandas as _pd
    try:
        import build_ledger_total
    except Exception as e:
        check(False, f'build_ledger_total importable ({e})')
        return
    check(hasattr(build_ledger_total, 'construir'),
          'build_ledger_total expone construir()')
    if not os.path.exists('pick_ledger_total.csv'):
        print('AVISO no hay ledger total; se omite el resto')
        return
    d = _pd.read_csv('pick_ledger_total.csv', usecols=['deporte', 'match_id'])
    check(d.duplicated(subset=['deporte', 'match_id']).sum() == 0,
          'el ledger total no tiene partidos duplicados')
    check(d['deporte'].nunique() >= 2,
          f"el ledger total cubre varios deportes "
          f"({sorted(d['deporte'].unique())})")


def test_mlb_statsapi_mapea_la_liga():
    """La fuente nueva tiene que cubrir los 30 equipos y unir la franquicia de
    Oakland, que Retrosheet tenía partida en OAK + ATH."""
    try:
        import mlb_statsapi
    except Exception as e:
        check(False, f'mlb_statsapi importable ({e})')
        return
    codigos = set(mlb_statsapi.ID_A_CODIGO.values())
    check(len(mlb_statsapi.ID_A_CODIGO) == 30,
          f'StatsAPI mapea 30 equipos ({len(mlb_statsapi.ID_A_CODIGO)})')
    check(len(codigos) == 30,
          f'los 30 equipos dan 30 códigos distintos ({len(codigos)})')
    check('ATH' not in codigos and 'OAK' in codigos,
          'la franquicia de Oakland es OAK, no está duplicada como ATH')
    from engines.mlb_engine import codigo_mlb
    check(codigo_mlb('Athletics') == codigo_mlb('Oakland Athletics') == 'OAK',
          'los dos nombres de los Athletics caen en el mismo código')


def test_peso_modelo_insensible_a_mayusculas():
    """La caja de la clave no puede decidir si un deporte se calibra o no.

    `ledger_tenis` escribe `liga` como `circuito.upper()` y `ledger_mlb` en
    minúsculas, así que `calibracion_mercado.json` acabó con «ATP»/«WTA» en
    mayúsculas mientras producción pregunta por «atp»/«wta». Medido antes del
    arreglo: `peso_modelo('atp')` daba 1,00 y `peso_modelo('ATP')` 0,25 — el
    tenis se quedaba sin encoger EN SILENCIO, justo después de que la v78
    midiera que encoger le da +2,6 pp (ATP) y +2,4 pp (WTA) de precisión.
    """
    import json as _j
    try:
        import calibracion_mercado as cm_cal
    except Exception as e:
        check(False, f'calibracion_mercado importable ({e})')
        return
    if not os.path.exists('calibracion_mercado.json'):
        print('AVISO no hay tabla de calibración; se omite')
        return
    with open('calibracion_mercado.json', encoding='utf-8') as f:
        ligas = (_j.load(f).get('ligas') or {})
    if not ligas:
        print('AVISO tabla de calibración vacía; se omite')
        return
    clave = next(iter(ligas))
    w_bajo = cm_cal.peso_modelo(clave.lower())
    w_alto = cm_cal.peso_modelo(clave.upper())
    check(w_bajo == w_alto and w_bajo < 1.0,
          f"'{clave}' pesa igual en mayúsculas y minúsculas "
          f"({w_alto:.2f} / {w_bajo:.2f})")
    # los deportes que producción consulta en minúsculas deben resolver
    for dep in ('atp', 'wta', 'mlb'):
        if dep in {k.lower() for k in ligas}:
            check(cm_cal.peso_modelo(dep) < 1.0,
                  f"'{dep}' resuelve su peso tal como lo pide producción "
                  f"({cm_cal.peso_modelo(dep):.2f})")
    # v80 — CAMBIO DELIBERADO respecto a la v79: una liga sin peso medido ya
    # NO cae a w=1,0 («sin corregir») sino al w GLOBAL. Devolver 1,0 no era
    # abstenerse, era elegir la opción que la evidencia global descarta, y
    # estaba medido lo que costaba: con la caída a 1,0 el fútbol daba ROI
    # +3,65 % con p5 **−1,11 %** (sin edge validado); cayendo al global,
    # +5,92 % con p5 +0,34 %.
    g = cm_cal.w_global()
    check(g is not None and 0 < g < 1,
          f'la tabla publica un w global utilizable ({g})')
    if g is not None:
        check(abs(cm_cal.peso_modelo('liga_inventada_v80') - g) < 1e-9,
              f'una liga sin medición hereda el w global ({g}), no w=1,0')
    check(cm_cal.peso_modelo('') == 1.0,
          'una clave vacía sigue devolviendo w=1,0 (no hay liga que calibrar)')


def test_nombre_de_liga_no_identifica_liga():
    """El nombre visible de una liga NO es su identidad.

    Tres competiciones se llaman «Primera División» (argentina, uru_primera,
    slv_primera) y dos «División Profesional» (bol_division, par_division). El
    código invertía el mapa nombre→clave, y al invertir gana el último: todo
    pick argentino se resolvía como **El Salvador**. Con la liga equivocada se
    leían la fiabilidad, la antigüedad del estado y los umbrales de otra
    competición, y la «Combinada segura del día» moría con un AttributeError
    al pedirle equipos argentinos al motor salvadoreño.
    """
    from collections import Counter
    try:
        from config import LEAGUES
    except Exception as e:
        check(False, f'config.LEAGUES importable ({e})')
        return
    nombres = Counter(cfg.get('nombre', c) for c, cfg in LEAGUES.items())
    duplicados = {n: v for n, v in nombres.items() if v > 1}
    # No se exige que no haya duplicados —son nombres reales— sino que el
    # sistema NO dependa de ellos para identificar la liga.
    check(bool(duplicados),
          f'hay nombres de liga repetidos, como se esperaba ({len(duplicados)})')

    import alpha_finder as af
    src = open(af.__file__, encoding='utf-8').read()
    check("p.get('clave_liga')" in src,
          'alpha_finder resuelve la liga por CLAVE, no por nombre visible')
    check("'clave_liga': clave" in src or "'clave_liga': liga" in src,
          'los picks de fútbol llevan su clave_liga')


def test_dashboard_usa_clave_de_liga():
    """La UI tampoco puede deducir la liga del nombre (mismo motivo)."""
    ruta = 'dashboard_ui.py'
    if not os.path.exists(ruta):
        print('AVISO dashboard_ui.py no encontrado; se omite')
        return
    src = open(ruta, encoding='utf-8').read()
    check("cand_combo.get('clave_liga')" in src,
          'la Combinada segura usa la clave del pick, no el nombre invertido')
    check('¼ Kelly simultáneo' in src or '¼ Kelly' in src,
          'el pie de exposición refleja la fracción de Kelly vigente (¼)')


def test_memoizacion_no_cambia_el_emparejamiento():
    """El atajo de `_sim_club` sin tokens comunes es demostrablemente inocuo:
    nunca puede alcanzar el umbral 0,80 que exige `_buscar`."""
    try:
        import cuotas_multi as cm
    except Exception as e:
        print(f'AVISO cuotas_multi no disponible ({e}); se omite')
        return
    check(cm._sim_club('Gremio', 'Gremio FBPA') >= 0.99,
          'un nombre contenido en otro sigue casando («Gremio» / «Gremio FBPA»)')
    check(cm._sim_club('Dinamo Moscow', 'Dynamo Moscow') > 0.5,
          'las variantes de transliteración siguen casando')
    check(cm._sim_club('Palmeiras', 'Boca Juniors') < 0.80,
          'dos equipos distintos no casan')
    check(isinstance(cm._tokens_club('Real Madrid'), frozenset),
          '_tokens_club devuelve frozenset (la caché no se puede corromper)')
    # la caché tiene que estar activa
    check(hasattr(cm.normalizar, 'cache_info'),
          'normalizar está memoizada')


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
    print('\n=== v78: multideporte ===')
    test_calibracion_multideporte()
    test_ledger_multideporte_alineado()
    test_deportes_con_edge()
    test_monitor_playdoit()
    print('\n=== v79: MLB al día y features vivas ===')
    test_mlb_estado_fresco()
    test_mlb_features_vivas()
    test_mlb_entrenamiento_serializable()
    test_mlb_statsapi_mapea_la_liga()
    print('\n=== v79: resiliencia y rendimiento ===')
    test_calibracion_segura_degrada()
    test_nombre_de_liga_no_identifica_liga()
    test_dashboard_usa_clave_de_liga()
    test_peso_modelo_insensible_a_mayusculas()
    test_inferencia_rapida_no_cambia_nada()
    test_memoizacion_no_cambia_el_emparejamiento()
    test_ledger_total_reproducible()
    print('\n=== v75: ledger de predicciones ===')
    test_ledger_sin_fuga()
    print('\n=== v75: umbrales en producción ===')
    test_umbrales_publicados()
    test_alpha_finder_lee_umbrales()
    print('\n=== v86: precio imposible, prior de ELO y totales ===')
    test_guardia_precio_imposible()
    test_prior_elo_solo_en_la_ficha()
    test_calibracion_de_totales_y_btts()
    print('\n=== v87: mercado en la ficha, hándicap y portabilidad ===')
    test_ficha_anclada_al_mercado()
    test_handicap_medido()
    test_modelos_portables()
    print(f"\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    for f in FALLOS:
        print('  - ' + f)
    sys.exit(1 if FALLOS else 0)
