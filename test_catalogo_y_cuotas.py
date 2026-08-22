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

    # ninguna liga disponible puede quedarse sin fuente.
    # v97: `leagues_cup` tampoco lleva `urls` — su histórico lo arma
    # `leagues_cup.historico()` juntando MLS, Liga MX y ESPN, así que su fuente
    # es el módulo, no una lista de CSV.
    FORMATOS_SIN_URLS = ('espn', 'api_football', 'leagues_cup')
    sin_fuente = [k for k, v in config.LEAGUES.items()
                  if v.get('disponible') and not v.get('urls')
                  and v.get('formato') not in FORMATOS_SIN_URLS]
    check(not sin_fuente, f"toda liga disponible tiene fuente ({sin_fuente})")

    # …y todo formato declarado tiene que saber descargarse. Sin esto, añadir
    # un formato nuevo y olvidar la rama de `descargar_liga` no da error hasta
    # el reentrenamiento nocturno, que es donde peor se ve.
    import inspect
    import league_engine
    fuente_descarga = inspect.getsource(league_engine.descargar_liga)
    formatos = {v.get('formato') for v in config.LEAGUES.values()
                if v.get('disponible')}
    sin_rama = [f for f in formatos
                if f and f not in ('main', 'new') and f"'{f}'" not in fuente_descarga]
    check(not sin_rama,
          f"todo formato del catálogo tiene rama en descargar_liga ({sin_rama})")


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


def test_tablero_playdoit():
    """
    v122: la casa del usuario tiene que publicar bastante más que el 1X2, o no
    hay con qué armar una combinada que se pueda poner en un solo boleto.

    El catálogo (`GetEvents`) trae CINCO mercados por partido y tres de ellos
    son el mismo suceso (1X2, doble oportunidad y empate-no-acción), así que
    con eso no se puede construir nada. El detalle (`GetEventDetails`) trae el
    tablero entero. Si esta llamada se cae o cambia de forma, la sección «En TU
    casa» se queda vacía sin dar un solo error — que es el modo de fallo que
    este proyecto ya ha pagado dos veces.
    """
    import cuotas_multi as cm
    check(hasattr(cm, 'mercados_playdoit'),
          "cuotas_multi expone mercados_playdoit")
    try:
        idx = cm._indice_pdt('futbol')
    except Exception as e:
        check(False, f"el índice de Playdoit carga ({type(e).__name__}: {e})")
        return
    con_id = sum(1 for v in idx.values() if v.get('event_id'))
    check(con_id > 0,
          f"el índice de Playdoit guarda el event_id ({con_id}/{len(idx)}) — "
          f"sin él no se puede pedir el detalle del partido")
    if not con_id:
        return
    # QUÉ SE AFIRMA AQUÍ, Y POR QUÉ NO SE AFIRMA UN NÚMERO GRANDE.
    #
    # Dos versiones anteriores de este test fallaron sin que nada estuviera
    # roto. La primera cogía «el primer partido del catálogo, el que sea» y le
    # tocó Alcorcón vs Rayo Majadahonda; la segunda probaba cinco y le
    # tocaron cinco partidos de división menor seguidos. En segunda B la casa
    # publica media docena de mercados, y eso no es un fallo del código: es el
    # partido.
    #
    # Lo que de verdad hay que comprobar es la afirmación que sostiene toda la
    # función: **el detalle trae MÁS que el catálogo**. El catálogo devuelve
    # como mucho cinco mercados por partido (1X2, doble oportunidad, empate no
    # acción, Total de 2.5 y ambos marcan), así que con que UN partido de la
    # muestra pase de cinco, el endpoint del detalle está funcionando. Si
    # estuviera roto daría 0 o None en todos, que es lo que este test caza.
    MERCADOS_DEL_CATALOGO = 5
    candidatos = [v for v in idx.values() if v.get('event_id')][:10]
    tableros = []
    for ent in candidatos:
        try:
            det = cm.mercados_playdoit('futbol', ent['home'], ent['away'])
        except Exception as e:
            check(False, f"mercados_playdoit lanza con {ent['home']} vs "
                         f"{ent['away']} ({type(e).__name__}: {e})")
            return
        if det:
            tableros.append((len(det.get('mercados') or []), ent, det))
    check(tableros,
          f"mercados_playdoit devuelve tablero de alguno de los "
          f"{len(candidatos)} partidos probados")
    if not tableros:
        return
    n, ent, det = max(tableros, key=lambda t: t[0])
    check(n > MERCADOS_DEL_CATALOGO,
          f"el detalle trae más mercados que el catálogo (el mejor de "
          f"{len(tableros)} partidos da {n} con precio, frente a los "
          f"{MERCADOS_DEL_CATALOGO} del catálogo: {ent['home']} vs "
          f"{ent['away']})")
    check(det.get('casa') == cm.CASA_PRIORITARIA,
          f"el tablero viene marcado con la casa del usuario ({det.get('casa')})")


def test_playdoit_no_inventa_mercados():
    """
    v122: el veto de la seña, que es lo que impide que un mercado sin
    equivalente en la plantilla cobre la probabilidad del más parecido.

    Caso REAL medido el 2026-08-10 en Monterrey vs Juárez: «Monterrey 3-4
    Juarez» @ 251,00 se cruzaba con «Monterrey o Juarez» (p 0,785) por
    similitud de cadena 0,89, y la app declaraba un EV de **+19.603 %**. No da
    excepción: da una apuesta. Es el mismo modo de fallo que la v114 corrigió
    en el emparejador, por otra puerta.
    """
    import cuotas_tablon as ct
    # un tablero de mentira con un marcador que la plantilla NO tiene
    det = {'casa': 'Playdoit', 'casa_home': 'Monterrey', 'casa_away': 'Juarez',
           'mercados': [
               {'tipo': 45, 'nombre': 'Marcador exacto', 'sv': None,
                'selecciones': [{'nombre': '3:4', 'cuota': 251.0,
                                 'tipo': 1, 'competidor': None}]},
               {'tipo': 18, 'nombre': 'Total', 'sv': '2.5',
                'selecciones': [{'nombre': 'Más de 2.5', 'cuota': 1.9,
                                 'tipo': 12, 'competidor': None},
                                # línea asiática de cuarto: NO existe en la
                                # plantilla y se parece demasiado a la de 2.5
                                {'nombre': 'Más de 2.25', 'cuota': 1.7,
                                 'tipo': 12, 'competidor': None}]},
           ]}
    filas = ct.filas_playdoit(det, 'Monterrey', 'Juarez')
    etqs = {f['etiqueta'] for f in filas}
    check('Más de 2.5 goles' in etqs,
          "la línea de 2.5 sí se traduce")
    check(not any('2.25' in e for e in etqs),
          f"las líneas asiáticas de cuarto se descartan ({etqs})")

    plantilla = {'secciones': [
        {'titulo': '2. Doble oportunidad', 'campos': [
            {'id': 'dc_12', 'etiqueta': 'Monterrey o Juarez',
             'tipo': 'pct', 'valor': 78.5}]},
        {'titulo': '3. Total de goles', 'campos': [
            {'id': 'over25', 'etiqueta': 'Más de 2.5 goles',
             'tipo': 'pct', 'valor': 53.6}]},
    ]}
    mk = ct.mercados_de_filas(filas, plantilla)
    ids = {r['id'] for r in mk}
    check('over25' in ids, "el mercado que SÍ existe se cruza")
    check('dc_12' not in ids,
          f"«Monterrey 3-4 Juarez» NO se cruza con «Monterrey o Juarez» "
          f"({[(r['apuesta'], r['ev']) for r in mk]})")
    check(all(r['ev'] < 1.0 for r in mk),
          f"ningún EV descabellado sobrevive ({[r['ev'] for r in mk]})")


def test_patas_llevan_su_id():
    """
    v122: cada pata de una combinada tiene que llevar el `id` de su mercado.

    Sin él, todo lo que la v114 construyó para razonar sobre las patas fallaba
    EN SILENCIO: tanto la interfaz (`m.get('id') == s.get('id')`) como
    `cuotas_tablon.recomendar_combinada` buscan el mercado por ahí, así que
    ninguna pata encontraba nunca el suyo. El síntoma visible era una
    recomendación que SIEMPRE decía «ninguna pata tiene un segundo precio con
    el que compararse», tuviera seis casas cotizándola o ninguna.
    """
    import inspect

    import match_parlay as mp
    fuente = inspect.getsource(mp)
    # los tres constructores que devuelven patas al exterior
    n = fuente.count("'id': s.id")
    check(n >= 3,
          f"los constructores de combinadas emiten el id del mercado ({n}/3)")


def test_combinada_de_una_sola_casa():
    """
    v122: la combinada de UNA casa se juzga por lo que paga esa casa frente al
    mercado, no por cuántas casas se han comparado (que es cero por
    construcción). Si se puntuara con el criterio normal, la recomendación se
    decidiría sola por probabilidad — justo el criterio que este proyecto tiene
    medido en NEGATIVO (−4,66 % a −6,52 % en 37.158 apuestas).
    """
    import cuotas_tablon as ct
    check(hasattr(ct, 'motor_solo_playdoit'),
          "cuotas_tablon expone motor_solo_playdoit")
    check(hasattr(ct, 'comparar_con_el_mercado'),
          "cuotas_tablon expone comparar_con_el_mercado")

    # dos opciones: la barata paga PEOR que el mercado, la otra lo iguala
    mercados = [
        {'id': 'a', 'apuesta': 'A', 'cuota_casa': 1.50, 'casa': 'Playdoit',
         'dif_vs_mercado': -0.20, 'casa_mercado': 'Pinnacle', 'ev': 0.0},
        {'id': 'b', 'apuesta': 'B', 'cuota_casa': 2.00, 'casa': 'Playdoit',
         'dif_vs_mercado': 0.01, 'casa_mercado': 'Pinnacle', 'ev': 0.0},
    ]
    peor = {'etiqueta_opcion': 'mal comprada', 'prob_conjunta': 0.55,
            'cuota_combinada': 1.9,
            'selecciones': [{'id': 'a', 'apuesta': 'A', 'cuota': 1.5,
                             'prob': 0.55, 'cuota_fuente': 'real'}]}
    mejor = {'etiqueta_opcion': 'bien comprada', 'prob_conjunta': 0.50,
             'cuota_combinada': 2.0,
             'selecciones': [{'id': 'b', 'apuesta': 'B', 'cuota': 2.0,
                              'prob': 0.50, 'cuota_fuente': 'real'}]}
    r = ct.recomendar_combinada([peor, mejor], mercados, criterio='casa_unica')
    check(r is not None and r['etiqueta_opcion'] == 'bien comprada',
          f"con una sola casa gana la que mejor se compra, no la más probable "
          f"({(r or {}).get('etiqueta_opcion')})")
    txt = ' '.join((r or {}).get('motivo_recomendacion', []))
    check('misma casa' in txt,
          f"la explicación dice que es un solo ticket ({txt[:120]})")
    # y el criterio de siempre no se toca
    r2 = ct.recomendar_combinada([peor, mejor], mercados)
    check(r2 is not None, "el criterio de mercado sigue funcionando")


def test_capa_visual_no_rompe():
    """
    v122: `estilo_ui` es SÓLO presentación y no puede lanzar nunca.

    Si un componente revienta con un dato raro, se lleva por delante la
    pantalla entera de Streamlit — y esta capa se llama desde catorce vistas.
    Todos tienen que devolver cadena (vacía si no entienden el dato), jamás
    una excepción.
    """
    import estilo_ui as e
    basura = [None, '', 'x', float('nan'), -1, 99, {}, []]
    fallos = []
    for v in basura:
        for f, args in ((e.barra, (v,)), (e.anillo, (v,)),
                        (e.chip_cuota, (v,)), (e.pildora, (v,)),
                        (e.medidor_precio, (v,)), (e.kpis, ([(v, 'x')],)),
                        (e.ticket, (v, v)), (e.pata, ('A', v, v)),
                        (e.barra_1x2, (v, v, v)), (e.nota, (v,)),
                        (e.vacio, ('t', v)), (e.cabecera, ('t', v)),
                        (e.seccion, ('t', v)), (e.tabla, (['a'], [[v]]))):
            try:
                out = f(*args)
                if not isinstance(out, str):
                    fallos.append(f'{f.__name__}({v!r}) no devuelve str')
            except Exception as ex:
                fallos.append(f'{f.__name__}({v!r}) lanza {type(ex).__name__}')
    check(not fallos, f"ningún componente visual lanza con datos raros "
                      f"({fallos[:4]})")
    # y el HTML que produce va escapado: un nombre con `<` no puede inyectar
    check('&lt;b&gt;' in e.pildora('<b>x</b>'),
          "los componentes escapan el texto que reciben")


def test_empate_recibe_su_precio():
    """
    v123: el precio del EMPATE tiene que llegar a `draw_prob`, no a `mv_x`.

    Fallo de producción desde la v114, y en el mercado más jugado que existe.
    `cruzar_con_plantilla` comparaba «Empate» contra los ~85 campos del modelo
    a la vez y ganaba el que más se le pareciera:

        «Empate» @ 4,63  →  «Empate» (mv_x, margen de victoria)  similitud 1,00
                     y NO →  «Empate (+365)» (draw_prob, 1X2)    similitud 0,75

    Los dos campos describen el mismo suceso, así que la probabilidad y el EV
    salían bien y nada fallaba a la vista. Pero `draw_prob` se quedaba SIN
    precio real, y el constructor de combinadas armaba cualquier pata con
    empate a cuota justa —un precio inventado— teniendo el real delante.

    Dos arreglos, y este test cubre los dos: la cuota americana que la
    plantilla pega a la etiqueta ya no cuenta para el cotejo, y cada familia de
    mercado sólo puede casar con su sección.
    """
    import cuotas_manual
    import cuotas_tablon as ct

    # 1) la decoración «(+365)» no puede impedir el cruce
    check(cuotas_manual._normalizar('Empate (+365)') == 'empate',
          f"la cuota americana sale de la etiqueta al normalizar "
          f"({cuotas_manual._normalizar('Empate (+365)')!r})")
    check(cuotas_manual._normalizar('Juarez +0.5 (no pierde)')
          == 'juarez +0 5 no pierde',
          "pero un paréntesis con texto SÍ se conserva "
          f"({cuotas_manual._normalizar('Juarez +0.5 (no pierde)')!r})")

    # 2) una fila de familia 1X2 sólo puede casar con la sección del 1X2
    plantilla = {'secciones': [
        {'titulo': '1. Resultado (1X2) con cuota justa', 'campos': [
            {'id': 'home_win_prob', 'etiqueta': 'Gana Monterrey (-163)',
             'tipo': 'pct', 'valor': 62.0},
            {'id': 'draw_prob', 'etiqueta': 'Empate (+365)',
             'tipo': 'pct', 'valor': 21.5},
            {'id': 'away_win_prob', 'etiqueta': 'Gana Juarez (+508)',
             'tipo': 'pct', 'valor': 16.5}]},
        {'titulo': '8. Margen de victoria', 'campos': [
            {'id': 'mv_x', 'etiqueta': 'Empate', 'tipo': 'pct',
             'valor': 21.5}]},
    ]}
    filas = [{'etiqueta': 'Empate', 'cuota': 4.25, 'casa': 'Playdoit',
              'familia': '1X2', 'sena': 'empate'}]
    ids = {r['id'] for r in ct.mercados_de_filas(filas, plantilla)}
    check('draw_prob' in ids,
          f"el precio del empate llega al 1X2 y no al margen de victoria "
          f"({ids})")


def test_tiempos_con_precio_pero_sin_ev():
    """
    v123: los mercados de mitad entran con precio REAL y con el EV marcado
    como no fiable.

    El usuario pidió «combinadas de córners, tarjetas, tiempos». Medido sobre
    Monterrey vs Juárez el 2026-08-10, de los 148 mercados con precio que
    publica Playdoit hay **cero** de córners o tarjetas y doce de mitades, así
    que de los tres sólo los tiempos se pueden jugar con cuota real.

    Pero el modelo reparte los goles a partes iguales entre las dos mitades
    —da la MISMA probabilidad a la 1ª y a la 2ª, medido en 4 de 4 partidos de
    Liga MX— y en el fútbol real se marca alrededor del 55 % en la segunda. El
    EV que sale de esa simetría mide lo que al modelo le falta, no valor, y por
    eso las filas van marcadas.
    """
    import cuotas_tablon as ct
    det = {'casa': 'Playdoit', 'casa_home': 'Monterrey',
           'casa_away': 'Juarez', 'mercados': [
               {'tipo': 68, 'nombre': '1ª Mitad - total', 'sv': '1.5',
                'selecciones': [{'nombre': 'Más de 0.5', 'cuota': 1.25,
                                 'tipo': 12, 'competidor': None},
                                {'nombre': 'Menos de 1.5', 'cuota': 1.6451,
                                 'tipo': 13, 'competidor': None}]},
               # total por equipo de una mitad: la plantilla NO lo tiene
               {'tipo': 69, 'nombre': '1ª Mitad - Monterrey total', 'sv': '0.5',
                'selecciones': [{'nombre': 'Más de 0.5', 'cuota': 1.52,
                                 'tipo': 12, 'competidor': None}]},
           ]}
    filas = ct.filas_playdoit(det, 'Monterrey', 'Juarez')
    etqs = {f['etiqueta'] for f in filas}
    check('1ª mitad: más de 0.5 goles' in etqs,
          f"el total de la 1ª mitad se traduce ({etqs})")
    check(not any('Monterrey' in e and 'mitad' in e for e in etqs),
          f"el total POR EQUIPO de una mitad se descarta ({etqs})")

    plantilla = {'secciones': [
        {'titulo': '13. 1ª y 2ª mitad', 'campos': [
            {'id': '1h_over05', 'etiqueta': '1ª mitad: más de 0.5 goles',
             'tipo': 'pct', 'valor': 77.1},
            {'id': '1h_under15', 'etiqueta': '1ª mitad: menos de 1.5 goles',
             'tipo': 'pct', 'valor': 56.6},
            {'id': '2h_over05', 'etiqueta': '2ª mitad: más de 0.5 goles',
             'tipo': 'pct', 'valor': 77.1},
            {'id': '2h_under15', 'etiqueta': '2ª mitad: menos de 1.5 goles',
             'tipo': 'pct', 'valor': 56.6}]},
    ]}
    check(ct._mitades_degeneradas(plantilla),
          "se detecta que el modelo da la misma probabilidad a las dos mitades")
    mk = ct.mercados_de_filas(filas, plantilla)
    check(mk, "los mercados de mitad se cruzan con el modelo")
    check(all(r.get('ev_no_fiable') for r in mk),
          f"y todos van marcados como EV no fiable "
          f"({[(r['apuesta'], r.get('ev_no_fiable')) for r in mk]})")


def test_h2h_trae_corners_y_tarjetas():
    """
    v123: el cara a cara tiene que enseñar córners, tarjetas y remates.

    Los históricos los traen desde siempre —67 de los 74 ficheros tienen
    `home_corners` y donde la columna existe la cobertura es del 100 % sobre
    147.811 partidos— y el panel no los leía. Fue exactamente lo que reportó el
    usuario mirando la pantalla.
    """
    import panel_equipos as pe
    r = pe.h2h('liga_mx', 'UNAM Pumas', 'Queretaro')
    if not r.get('n'):
        check(False, 'hay cruces de Pumas-Querétaro en el histórico')
        return
    ex = r.get('extra') or {}
    check('corners' in ex and ex['corners'].get('media_total'),
          f"el cara a cara trae córners ({ex.get('corners')})")
    check('tarjetas' in ex and ex['tarjetas'].get('lineas'),
          f"y tarjetas con su porcentaje por línea ({ex.get('tarjetas')})")
    # la posesión no puede dar un «total» de 100, que no informa de nada
    check('media_total' not in (ex.get('posesion') or {}),
          f"la posesión no publica un total (siempre sería 100) "
          f"({ex.get('posesion')})")
    p0 = r['partidos'][0]
    check(p0.get('corners_local') is not None,
          f"y cada partido lleva sus cifras ({p0})")


def test_juegos_de_tenis():
    """
    v123: los juegos totales del tenis, que el usuario pidió para apostar la
    línea.

    Salen del histórico unificado, que trae `Score` con cobertura del 100 %
    sobre 354.250 partidos del ATP. Lo que este test protege sobre todo es la
    separación por FORMATO: mezclar partidos al mejor de 3 con finales de Grand
    Slam al mejor de 5 daba un número que no corresponde a ningún partido
    —Alcaraz–Sinner salía a 32,8 juegos de media de cruce frente a 22,5 de
    media individual— y puesto al lado de una línea de casa habría hecho
    parecer baratísimo cualquier «más de 22.5».
    """
    import tenis_juegos as tj
    casos = [('6-3 6-7 4-6', 32), ('6-4 7-5', 22), ('6-0 6-0', 12),
             ('6-3 2-1 RET', None), ('', None), (None, None)]
    malos = [(s, tj.juegos_del_marcador(s), e) for s, e in casos
             if tj.juegos_del_marcador(s) != e]
    check(not malos, f"el marcador se lee bien y el retiro se descarta ({malos})")

    import os
    if not os.path.exists('tenis_juegos_atp.json'):
        print('AVISO tenis_juegos_atp.json no existe todavía; se omite el resto')
        return
    p = tj.perfil_jugador('atp', 'Djokovic N.', 3)
    check(p and p.get('n', 0) > 100,
          f"hay perfil de juegos de un jugador del circuito ({p})")
    r3 = tj.linea_sugerida('atp', 'Djokovic N.', 'Nadal R.', 3)
    r5 = tj.linea_sugerida('atp', 'Djokovic N.', 'Nadal R.', 5)
    check(r3 and r5, "hay línea sugerida en los dos formatos")
    if r3 and r5:
        check(r5['media_estimada'] > r3['media_estimada'] + 5,
              f"el mejor de 5 dura bastante más que el mejor de 3 "
              f"({r3['media_estimada']} vs {r5['media_estimada']})")
        if r3.get('h2h') and r5.get('h2h'):
            check(r3['h2h']['media'] < r5['h2h']['media'],
                  f"y el cara a cara también va separado por formato "
                  f"({r3['h2h']} vs {r5['h2h']})")


def test_partido_parejo():
    """
    v123: comparar «Gana X» con «X o Empate» y, sobre todo, medir el MARGEN.

    Lo que se puede comprobar sin depender de que el modelo acierte es cuánto
    cobra la casa en cada uno de los dos mercados. El margen de la doble
    oportunidad NO se calcula como el del 1X2: cada opción cubre dos de los
    tres resultados, así que las probabilidades implícitas de un libro sin
    margen suman 2 y hay que dividir entre 2. Sin esa corrección parecería que
    la doble oportunidad cobra el doble de lo que cobra, y la pantalla estaría
    empujando al usuario al mercado equivocado.
    """
    import partido_parejo as pp
    # libro sin margen: 1X2 con probabilidades 0,5 / 0,25 / 0,25
    m = pp.margen_1x2({'home': 2.0, 'draw': 4.0, 'away': 4.0})
    check(abs(m) < 1e-9, f"un 1X2 sin margen da 0 ({m})")
    # el mismo libro en doble oportunidad: 1X=0,75 12=0,75 X2=0,50
    d = pp.margen_doble({'1x': 1 / 0.75, '12': 1 / 0.75, 'x2': 1 / 0.50})
    check(abs(d) < 1e-9,
          f"y la doble oportunidad del mismo libro también da 0, no 100 % ({d})")
    # Playdoit en Monterrey vs Juárez, medido el 2026-08-10
    m_real = pp.margen_1x2({'home': 1.5455, 'draw': 4.25, 'away': 5.3334})
    d_real = pp.margen_doble({'1x': 1.1667, '12': 1.2, 'x2': 2.2223})
    check(0.02 < m_real < 0.15 and 0.02 < d_real < 0.15,
          f"los dos márgenes reales son plausibles ({m_real:.4f}, {d_real:.4f})")

    par = pp.es_parejo(0.34, 0.30, 0.36)
    check(par['parejo'], f"un 34/30/36 se detecta como parejo ({par['motivo']})")
    claro = pp.es_parejo(0.62, 0.22, 0.16)
    check(not claro['parejo'],
          f"y un 62/22/16 NO ({claro['motivo']})")


def test_selectores_de_partido_con_clave_estable():
    """
    v123: la etiqueta de un selector de partidos no puede ser su CLAVE.

    Los dos selectores de próximos partidos —el de deportes y el de ligas de
    fútbol— añadían «· sin cuota aún» al texto de la opción, y ese texto era
    además la clave. Como depende de si las casas han abierto línea, cambia
    entre una recarga y la siguiente: al pulsar «🔄 Actualizar» el valor
    guardado en la sesión dejaba de existir en la lista nueva y Streamlit
    tumbaba la vista entera.

        ValueError: '2026-08-12 11:40 · Baltimore Orioles @ Minnesota Twins'
        is not in list

    Lo cazó `smoke_botones.py` en la vista de MLB. La corrección es separar la
    clave (estable) del texto (`format_func`), más una guardia que olvida una
    selección que ya no exista — porque un partido que termina desaparece del
    calendario y eso las claves estables no lo pueden evitar.
    """
    import re
    src = open('dashboard_ui.py', encoding='utf-8').read()

    # ningún diccionario de opciones puede indexarse por la etiqueta volátil
    malos = [l.strip() for l in src.splitlines()
             if re.search(r'_?ops?\[_etq\]|_ops\[_etq\]', l)]
    check(not malos,
          f"las opciones no se indexan por la etiqueta con “sin cuota aún” "
          f"({malos[:2]})")

    # los dos selectores usan format_func y la guardia
    for clave_sel in ('fxd_sel_', 'fx_sel_'):
        i = src.find(f'key=f"{clave_sel}')
        check(i > 0, f"se encuentra el selector {clave_sel}")
        if i <= 0:
            continue
        ventana = src[max(0, i - 400):i + 300]
        check('format_func' in ventana,
              f"el selector {clave_sel} pinta la etiqueta con format_func")
        check('_olvidar_seleccion_muerta' in ventana,
              f"y olvida una selección que ya no exista ({clave_sel})")

    check('def _olvidar_seleccion_muerta' in src,
          "existe la guardia contra la selección muerta")


def test_telegram_envia_picks_y_ponches():
    """
    v124 (mejoras 7 y 8): el EV+ de cada deporte y la sección de ponches se
    pueden mandar al teléfono.

    Y con el aviso DENTRO del mensaje, no sólo en la pantalla. Un mensaje de
    Telegram se lee fuera de contexto: si dice «EV +23 %» sin decir que este
    proyecto tiene medido que apostar por la probabilidad del modelo pierde
    entre 4,7 % y 6,5 %, está engañando a quien lo lee en el autobús.
    """
    import bot_telegram as bt
    check(hasattr(bt, 'formatear_picks') and hasattr(bt, 'enviar_picks'),
          "bot_telegram sabe formatear y enviar picks")
    check(hasattr(bt, 'formatear_ponches') and hasattr(bt, 'enviar_ponches'),
          "y la sección de ponches")

    msg = bt.formatear_picks('EV+ MLB', [
        {'partido': 'BAL @ MIN', 'apuesta': 'Gana Minnesota', 'cuota': 1.85,
         'casa': 'Playdoit', 'prob': 0.58, 'ev': 0.073}])
    for trozo in ('BAL @ MIN', 'Gana Minnesota', '1.85', 'Playdoit', '58%'):
        check(trozo in msg, f"el mensaje de picks lleva «{trozo}»")
    check('pierde entre' in msg,
          "y el aviso medido viaja DENTRO del mensaje")

    pon = bt.formatear_ponches([
        {'lanzador': 'Cristian Javier', 'partido': 'HOU @ SDN', 'linea': 3.5,
         'cuota': 1.87, 'prob': 0.66, 'recomendacion': '✅ Más de 3.5'}])
    for trozo in ('Cristian Javier', 'HOU @ SDN', '3.5', '1.87', '66%'):
        check(trozo in pon, f"el mensaje de ponches lleva «{trozo}»")

    # ninguno puede pasarse del límite de Telegram, ni con la sección entera
    largo = bt.formatear_ponches([
        {'lanzador': f'Lanzador {i}', 'partido': f'Equipo A{i} @ Equipo B{i}',
         'linea': 4.5, 'cuota': 1.9, 'prob': 0.6, 'ev': 0.14,
         'recomendacion': '✅ Más de 4.5 ponches'} for i in range(200)])
    check(len(largo) <= bt.MAX_LEN,
          f"la sección entera se recorta al límite de Telegram ({len(largo)})")
    check('recortado' in largo,
          "y cuando se recorta, lo dice en vez de callarlo")

    # con la lista vacía tienen que decir por qué, no salir en blanco
    for f, etq in ((bt.formatear_picks('X', []), 'picks'),
                   (bt.formatear_ponches([]), 'ponches')):
        check(len(f) > 60 and 'no' in f.lower(),
              f"sin datos, el mensaje de {etq} explica por qué está vacío")

    # y el botón existe en las dos pantallas
    dash = open('dashboard_ui.py', encoding='utf-8').read()
    check('tg_ev_' in dash, "la vista de EV+ tiene su botón de Telegram")
    check("key='tg_ponches'" in dash,
          "y la de ponches el suyo")


def test_bitacora_de_arquitectura():
    """
    v124: la bitácora existe y conserva las cifras que gobiernan el sistema.

    No es un test de estilo. Este documento es la regla de oro del proyecto y
    su valor está en los números medidos: si alguien los borra o los cambia sin
    medir de nuevo, las decisiones que se apoyan en ellos dejan de tener
    respaldo y nadie se entera.
    """
    import os
    if not os.path.exists('BITACORA_ARQUITECTURA.md'):
        check(False, 'existe BITACORA_ARQUITECTURA.md')
        return
    doc = open('BITACORA_ARQUITECTURA.md', encoding='utf-8').read()
    for cifra, que in (
            ('89.748', 'el tamaño de la muestra de calibración'),
            ('37.158', 'las apuestas que miden el ROI negativo'),
            ('−0,054', 'la correlación del EV con el CLV'),
            ('54,9', 'la mejor precisión por liga, que no llega a 58 %'),
            ('−13,62', 'el EV de una combinada de tres patas negativas'),
    ):
        check(cifra in doc, f"la bitácora conserva {que} ({cifra})")
    for seccion in ('2 niveles', '3 secciones', 'Semáforo',
                    'generador de parlays', 'Playdoit', 'stack'):
        check(seccion.lower() in doc.lower(),
              f"la bitácora cubre «{seccion}»")


def test_clasificador_tres_secciones():
    """
    v125: el semáforo que reparte los mercados en las tres secciones.

    El criterio NO es el EV del modelo —medido en −4,66 % a −6,52 %— sino la
    ventaja de precio contra el consenso del mercado. Y el umbral no es cero:
    medido sobre 1.414 selecciones de `odds_snapshots.csv`, entre 0 % y 5 % el
    ROI es −11,48 % y por encima de 5 % es +8,22 %.
    """
    import clasificador as cla

    # el devig tiene que devolver un libro cuyas probabilidades sumen 1
    j = cla.consenso_sin_margen({'home': 1.9048, 'draw': 3.8095,
                                 'away': 3.8095})
    check(j is not None and abs(sum(1 / v for v in j.values()) - 1.0) < 1e-4,
          f"el devig deja las probabilidades sumando 1 ({j})")
    check(abs(j['home'] - 2.0) < 0.01,
          f"y devuelve la cuota justa correcta ({j['home']:.3f}, esperado 2,00)")

    # el semáforo, caso a caso
    casos = [
        (0.08, 3, 'verde',    'ventaja clara con consenso de varias casas'),
        (0.02, 3, 'amarillo', 'ventaja por debajo del 5 % medido'),
        (0.08, 1, 'amarillo', 'una sola casa de referencia no es consenso'),
        (-0.05, 3, 'rojo',    'la casa paga peor que el mercado'),
        (None, 3, 'amarillo', 'sin nada con lo que comparar'),
        (3.92, 3, 'rojo',     'ventaja imposible: son partidos distintos'),
    ]
    for v, n, esperada, que in casos:
        r = cla.semaforo(v, n)
        check(r['luz'] == esperada,
              f"{que}: {r['luz']} (esperado {esperada})")

    # la ventaja imposible se marca como error de datos, no como oportunidad
    check(cla.semaforo(3.92, 3).get('error_datos'),
          "una ventaja de +392 % se marca como error de datos")

    # el reparto y el material de parlay
    mercados = [
        {'id': 'a', 'apuesta': 'A', 'cuota_casa': 2.2, 'prob': 0.5,
         'dif_vs_consenso': 0.09, 'n_casas_mercado': 4},
        {'id': 'b', 'apuesta': 'B', 'cuota_casa': 1.1, 'prob': 0.90,
         'dif_vs_consenso': -0.01, 'n_casas_mercado': 4},
        {'id': 'c', 'apuesta': 'C', 'cuota_casa': 1.5, 'prob': 0.6,
         'dif_vs_consenso': -0.09, 'n_casas_mercado': 4},
    ]
    c = cla.clasificar(mercados, 0.52, 0.538)
    check([m['id'] for m in c['seccion1']] == ['a'],
          f"a la Sección 1 sólo va la que tiene ventaja ({c['seccion1']})")
    check([m['id'] for m in c['seccion2']] == ['b'],
          f"a la Sección 2 la de alta probabilidad sin ventaja")
    check([m['id'] for m in c['descartados']] == ['c'],
          "y la que paga peor se descarta")

    # LA REGLA QUE MÁS IMPORTA: el parlay parte de la Sección 1
    ids = cla.ids_para_parlay(c)
    check(ids and ids[0] == 'a',
          f"el parlay empieza por la Sección 1 ({ids})")
    check('c' not in ids, "y nunca incluye un descartado")
    check(len([i for i in ids if i == 'b']) <= 1,
          "el relleno de la Sección 2 está limitado a una pata")
    solo_s2 = cla.clasificar([mercados[1]], 0.52, 0.538)
    check(len(cla.ids_para_parlay(solo_s2)) <= 1,
          "sin patas verdes no se puede armar una combinada de la Sección 2 "
          "sola: multiplicaría la pérdida")


def test_regla_tenis_90():
    """
    v126: el tenis con probabilidad ≥ 90 % va a la Sección 1.

    Es la ÚNICA regla del proyecto que entra en la Sección 1 sin ventaja de
    precio, y entra porque está medida sobre 46.151 partidos del ledger:

        prob >= 90 %   n=1.793   acierto 91,69 %   ROI +5,76 %   p5 +0,18 %
        tenis global   n=46.151  acierto 65,88 %   ROI −4,92 %   p5 −5,53 %

    Lo que este test protege, además de la regla: que NO se extienda sola. El
    tenis global pierde casi lo mismo que el fútbol, así que la banda de 80-90 %
    (ROI −1,96 %) no puede colarse, y ningún otro deporte hereda la excepción.
    """
    import clasificador as cla
    check(abs(cla.REGLA_TENIS_PROB - 0.90) < 1e-9,
          f"el umbral de la regla es el 90 % medido ({cla.REGLA_TENIS_PROB})")
    check(cla.REGLA_TENIS_MEDICION.get('p5', -1) > 0,
          "la regla sólo existe porque su p5 es positivo")

    r = cla.semaforo(None, 1, None, deporte='tenis', prob=0.93)
    check(r['luz'] == 'verde' and r['seccion'] == 1,
          f"tenis al 93 % va a la Sección 1 ({r['luz']})")
    check('p5' in r['motivo'] and '1.793' in r['motivo'],
          f"y el motivo lleva la medición que lo respalda ({r['motivo'][:70]})")

    # sin precio no hay apuesta, por muy alta que sea la probabilidad
    r = cla.semaforo(None, 1, None, deporte='tenis', prob=0.93,
                     hay_precio=False)
    check(r['seccion'] == 2,
          f"sin cuota publicada no puede ir a la Sección 1 ({r['seccion']})")

    # la banda de 80-90 % NO hereda la regla: su ROI medido es −1,96 %
    r = cla.semaforo(None, 1, None, deporte='tenis', prob=0.85)
    check(r['seccion'] == 2,
          f"el 85 % NO entra en la Sección 1 ({r['seccion']})")

    # ningún otro deporte hereda la excepción
    for dep in ('futbol', 'mlb', 'nba'):
        r = cla.semaforo(None, 1, None, deporte=dep, prob=0.95)
        check(r['seccion'] != 1,
              f"{dep} al 95 % no entra en la Sección 1 por probabilidad")

    # y el guardia de datos manda sobre la regla
    r = cla.semaforo(3.92, 3, None, deporte='tenis', prob=0.95)
    check(r['luz'] == 'rojo',
          f"una ventaja imposible descarta incluso un pick de tenis al 95 % "
          f"({r['luz']})")


def test_consenso_api_respeta_el_presupuesto():
    """
    v127: el consenso ampliado no puede comerse los 500 créditos del mes.

    NOTA SOBRE EL NOMBRE. La v88 retiró un módulo llamado `odds_api` porque
    «la clave devolvía 401 en TODAS las ligas y sólo llenaba el arranque de
    errores, uno por competición», y dejó `test_sin_the_odds_api` para que no
    volviera. Ese guardián sigue vigente y se respeta: este módulo se llama
    `consenso_api` y hace otra cosa —ensanchar el consenso, no ser la fuente
    de cuotas—, con clave gratuita, tope de gasto y degradación en silencio.
    El modo de fallo de la v88 está cubierto por
    `test_consenso_api_degrada_en_silencio`.

    El plan gratuito da 500 créditos mensuales y el coste es
    `mercados × regiones` por LIGA (el histórico, ×10, está prohibido aquí).
    Las cuentas que fijan el diseño:

        5 ligas × 2 mercados × 4 veces/día = 1.200/mes  ✗
        5 ligas × 1 mercado  × 3 veces/día =   450/mes  ✓ justo
        bajo demanda, 10 partidos/día      =   300/mes  ✓

    Lo que este test protege es el corte duro: si alguien sube los mercados por
    defecto o mete las 24 huérfanas en la lista blanca, el presupuesto se
    dispara y la app se queda sin cuotas a mitad de mes. Aquí se detecta.
    """
    import consenso_api as oa

    check(oa.LIMITE_DURO < oa.CUOTA_MENSUAL,
          f"el corte ({oa.LIMITE_DURO}) deja margen bajo la cuota "
          f"({oa.CUOTA_MENSUAL})")
    check(len(oa.MERCADOS_POR_DEFECTO) == 1,
          f"por defecto se pide UN mercado: cada uno más duplica el gasto "
          f"({oa.MERCADOS_POR_DEFECTO})")
    check(',' not in oa.REGION_POR_DEFECTO,
          f"y UNA región, por lo mismo ({oa.REGION_POR_DEFECTO})")

    # el coste mensual del peor caso razonable tiene que caber
    n = len(oa.LIGAS_BLANCAS)
    coste_mes = n * len(oa.MERCADOS_POR_DEFECTO) * 1 * 30
    check(coste_mes <= oa.LIMITE_DURO,
          f"refrescar la lista blanca entera una vez al día cabe en el mes "
          f"({n} ligas → {coste_mes} créditos de {oa.LIMITE_DURO})")

    # las huérfanas NO pueden estar en la lista blanca: su histórico es lo que
    # necesitarían y está fuera del plan gratuito
    for huerfana in ('bol_division', 'col_primera_a', 'per_liga1',
                     'uru_primera', 'arg_primera_nacional'):
        check(huerfana not in oa.LIGAS_BLANCAS,
              f"«{huerfana}» se queda congelada, como se acordó")

    # y una liga fuera de la lista no gasta NADA, ni siquiera con clave
    check(oa.cuotas_liga('no_existe_esta_liga') is None,
          "una liga fuera de la lista blanca no llega a llamar")

    # el presupuesto se lee sin lanzar aunque no haya fichero ni clave
    p = oa.presupuesto()
    for k in ('mes', 'usados', 'limite', 'queda', 'agotado'):
        check(k in p, f"el presupuesto informa de «{k}»")
    check(not oa.hay_presupuesto(10 ** 6),
          "una llamada absurdamente cara se rechaza siempre")


def test_consenso_api_degrada_en_silencio():
    """
    v127: sin clave, el consenso ampliado NO puede hacer ruido.

    Éste es el modo de fallo exacto por el que la v88 retiró su predecesor:
    «la clave devolvía 401 en TODAS las ligas y sólo llenaba el arranque de
    errores, uno por competición». Un módulo opcional que grita cuando no está
    configurado es peor que no tenerlo.

    Medido con la clave quitada: el tablón sigue dando sus casas de siempre y
    se emiten CERO avisos.
    """
    import logging
    import os

    guardada = os.environ.pop('ODDS_API_KEY', None)
    registrados = []

    class _Cazador(logging.Handler):
        def emit(self, r):
            if r.levelno >= logging.WARNING:
                registrados.append(r.getMessage())

    h = _Cazador()
    raiz = logging.getLogger()
    raiz.addHandler(h)
    try:
        import consenso_api as ca
        check(not ca.disponible(),
              "sin variable de entorno, el módulo se declara no disponible")
        check(ca.cuotas_liga('liga_mx') is None,
              "y no devuelve datos en vez de lanzar")
        check(ca.casas_del_partido('liga_mx', 'A', 'B') == {},
              "las casas salen vacías, no None ni excepción")
        p = ca.presupuesto()
        check(isinstance(p, dict) and 'usados' in p,
              "el presupuesto se lee igualmente")
    finally:
        raiz.removeHandler(h)
        if guardada is not None:
            os.environ['ODDS_API_KEY'] = guardada

    ruidosos = [m for m in registrados
                if 'consenso' in m.lower() or 'odds' in m.lower()]
    check(not ruidosos,
          f"sin clave no se emite ni un aviso ({ruidosos[:2]})")


def test_la_ficha_pide_las_cuotas_con_liga():
    """
    v127: la vista de cuotas tiene que pasar `liga` a `cuotas_partido`.

    `liga` decide dos cosas: la guardia de categoría del emparejador
    (femenino/filial) y si la competición está en la lista blanca de The Odds
    API. Sin ella el consenso se queda en las cinco casas de siempre.

    Medido el día que se añadió el indicador de consenso, que es quien lo
    delató: `Monterrey vs Juarez` daba **4 casas** sin `liga` y **20** con
    ella. La ficha anunciaba «Consenso: 4 casas · modo de respaldo» teniendo
    veinte disponibles, y sin el indicador nadie se habría enterado.

    Es un test de código y no de red: lo que se comprueba es que la llamada
    lleve el argumento, porque el síntoma es silencioso.
    """
    src = open('dashboard_ui.py', encoding='utf-8').read()
    import re
    llamadas = re.findall(r'cuotas_partido\((.{0,220}?)\)', src, re.S)
    check(llamadas, 'la interfaz llama a cuotas_partido')
    sin_liga = [c.replace('\n', ' ')[:80] for c in llamadas
                if 'liga=' not in c]
    check(not sin_liga,
          f"todas las llamadas pasan la liga ({len(sin_liga)} sin ella: "
          f"{sin_liga[:2]})")

    # y el indicador de consenso tiene que estar en la ficha
    check('Consenso:' in src,
          'la ficha del partido enseña cuántas casas respaldan el consenso')
    check('modo de respaldo' in src,
          'y avisa cuando ha caído al tablón básico')


def test_sondeo_de_casas():
    """
    v126: el barrido de casas existe, es reproducible y no se cierra en tres.

    El usuario pidió explícitamente que no me quedara en las alternativas ya
    sondeadas. Este test no comprueba el RESULTADO del barrido —que depende de
    lo que respondan hoy los servidores— sino que la herramienta cubre las vías
    de acceso conocidas y sigue estando.
    """
    import sondeo_casas as sc
    check(len(sc.CANDIDATAS) >= 25,
          f"el barrido cubre un número serio de fuentes "
          f"({len(sc.CANDIDATAS)})")
    plataformas = {c['plataforma'] for c in sc.CANDIDATAS}
    for p in ('Altenar', 'Kambi', 'exchange', 'propia'):
        check(p in plataformas, f"se prueba la vía «{p}»")
    # las cinco integradas tienen que seguir en la lista, o el barrido dejaría
    # de detectar si una se cae
    casas = ' '.join(c['casa'] for c in sc.CANDIDATAS)
    for c in ('Playdoit', 'Pinnacle', 'Bovada', 'Unibet', 'Matchbook'):
        check(c in casas, f"«{c}» sigue vigilada por el barrido")


def test_sufijo_de_estado_no_confunde_clubes():
    """
    v125: «Athletico-PR» y «Atlético-MG» son clubes distintos.

    El normalizador machaca guiones y paréntesis, así que los dos acababan
    compartiendo su único token significativo («atletico») y el emparejador los
    daba por el MISMO equipo con similitud **1,0** — no un empate que la
    guardia de ambigüedad pudiera cazar, sino una coincidencia perfecta con el
    club equivocado.

    Medido el 2026-08-11: pidiendo «Athletico-PR vs Bragantino» devolvía el
    tablero de «Atlético-MG vs Bragantino», de otra competición y otra fecha, y
    con él la Sección 1 anunciaba «Empate @ 16,00 · +392 % sobre el mercado».
    Un precio de otro partido que alguien podría haber apostado.
    """
    import cuotas_multi as cm
    check(cm.marca_estado('Athletico-PR') == 'pr'
          and cm.marca_estado('Atlético-MG') == 'mg',
          "se detecta el sufijo de estado brasileño")
    check(cm.marca_estado('Bragantino') == ''
          and cm.marca_estado('Vasco da Gama') == '',
          "y no se inventa donde no lo hay")

    # el emparejador no puede cruzar dos clubes con sufijo distinto
    idx = {
        'atletico mg|bragantino': {'home': 'Atlético-MG',
                                   'away': 'Bragantino',
                                   'cuotas': {'home': 2.0, 'away': 3.0}},
        'athletico pr|bragantino': {'home': 'Athletico-PR',
                                    'away': 'Bragantino',
                                    'cuotas': {'home': 2.5, 'away': 2.6}},
    }
    r = cm._buscar(idx, 'Athletico-PR', 'Bragantino', 'futbol')
    check(r is not None and r['home'] == 'Athletico-PR',
          f"«Athletico-PR» empareja con su club, no con el otro Atlético "
          f"({(r or {}).get('home')})")
    r2 = cm._buscar(idx, 'Atletico-MG', 'Bragantino', 'futbol')
    check(r2 is not None and r2['home'] == 'Atlético-MG',
          f"y «Atlético-MG» con el suyo ({(r2 or {}).get('home')})")


def test_consenso_de_varias_casas():
    """
    v125: la ventaja se mide contra el CONSENSO, no contra el mejor precio.

    El umbral del 5 % se calibró comparando contra la media del resto de casas.
    Compararlo contra el MEJOR del resto sería aplicar ese umbral a una
    magnitud distinta y mucho más exigente, y la Sección 1 quedaría vacía por
    construcción sin que nadie se diera cuenta.
    """
    import cuotas_tablon as ct
    plantilla = {'secciones': [
        {'titulo': '1. Resultado (1X2) con cuota justa', 'campos': [
            {'id': 'home_win_prob', 'etiqueta': 'Gana A', 'tipo': 'pct',
             'valor': 50.0}]}]}
    filas = [
        {'etiqueta': 'Gana A', 'cuota': 2.00, 'casa': 'Pinnacle',
         'familia': '1X2'},
        {'etiqueta': 'Gana A', 'cuota': 2.10, 'casa': 'Bovada',
         'familia': '1X2'},
        {'etiqueta': 'Gana A', 'cuota': 2.20, 'casa': 'Unibet',
         'familia': '1X2'},
    ]
    mk = ct.mercados_de_filas(filas, plantilla)
    check(mk, "se cruzan las filas")
    if not mk:
        return
    r = mk[0]
    check(r.get('n_casas') == 3, f"cuenta las tres casas ({r.get('n_casas')})")
    check(abs((r.get('cuota_media') or 0) - 2.10) < 0.001,
          f"y publica la media del tablón ({r.get('cuota_media')}, "
          f"esperado 2,10)")


def test_la_interfaz_usa_la_capa_visual():
    """
    v122: que `estilo_ui` no vuelva a ser un módulo que nadie llama.

    Éste es el fallo exacto de la v117, y no es una hipótesis: creó seis
    componentes y la aplicación usaba TRES, en CUATRO sitios, sobre 5.884
    líneas de interfaz. El resto seguía siendo `st.markdown` con asteriscos.
    Por eso el usuario pidió el rediseño cuatro veces seguidas — desde fuera no
    había cambiado nada, porque desde fuera efectivamente no había cambiado
    casi nada.

    Un módulo de presentación sin llamadores no da error, no rompe ningún test
    y no se nota en ninguna métrica. Sólo se nota mirando la pantalla, que es
    justo lo que un test no hace. De ahí esta guardia.
    """
    import ast
    src = open('dashboard_ui.py', encoding='utf-8').read()
    usos = src.count('_pinta(') + src.count('_seccion(') + src.count('_cabecera(')
    check(usos >= 40,
          f"la interfaz usa la capa visual de verdad ({usos} llamadas; la "
          f"v117 tenía 4 y por eso no se notaba)")

    # y que cada componente público de estilo_ui tenga al menos un llamador
    import estilo_ui
    arbol = ast.parse(open('estilo_ui.py', encoding='utf-8').read())
    publicos = [n.name for n in arbol.body
                if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')]
    huerfanos = [f for f in publicos
                 if f not in ('aplicar', 'pinta') and f'.{f}(' not in src]
    check(not huerfanos,
          f"ningún componente visual se queda sin usar ({huerfanos})")

    # el tema tiene que existir: sin él, el CSS afina bordes sobre la paleta de
    # fábrica de Streamlit, que es lo que hacía que el rediseño no se viera
    cfg = open('.streamlit/config.toml', encoding='utf-8').read()
    check('[theme]' in cfg and 'primaryColor' in cfg,
          "la app define su propio tema, no el de fábrica de Streamlit")
    # y el color primario del tema tiene que ser el mismo «puedes actuar» del
    # sistema de componentes, o el botón y la píldora de al lado dirían cosas
    # distintas con el mismo color
    import re
    m = re.search(r'primaryColor\s*=\s*"(#[0-9a-fA-F]{6})"', cfg)
    check(bool(m) and m.group(1).lower() in estilo_ui.CSS.lower(),
          f"el color primario del tema es el mismo --ok de estilo_ui "
          f"({m.group(1) if m else 'sin definir'})")


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
    # v151 — SE COMPARAN LOS BANDOS, NO LOS PRECIOS.
    #
    # Esto inferría la inversión del PRECIO: si el `home` de una casa se parecía
    # más al `away` de la otra, lo contaba como invertido. Y esa heurística no
    # sabe distinguir «los bandos están al revés» de «las dos casas discrepan
    # sobre quién es favorito», que en la MLB pasa constantemente porque el
    # moneyline se mueve fuerte con el abridor.
    #
    # Falló el 2026-08-21 con este caso, que NO estaba invertido:
    #
    #     baltimore orioles|tampa bay rays
    #     pinnacle  home 2,16  away 1,78   (favorito: Tampa Bay)
    #     playdoit  home 1,83  away 2,00   (favorito: Baltimore)
    #     nombres:  Baltimore Orioles / BAL Orioles  →  el MISMO bando local
    #
    # El nombre es la verdad; el precio es un indicio, y encima uno que las
    # casas tienen derecho a discrepar. Así que se comprueba lo que de verdad
    # importaba: que el equipo que cada casa declara como local sea el mismo.
    # Un fallo real —el de la v77, que invertía todo el béisbol— se vería aquí
    # igual de claro, porque entonces el local de una SÍ sería el visitante de
    # la otra por NOMBRE.
    coincidencias, invertidos = 0, 0
    for k, v in pdt.items():
        p = pin.get(k)
        if not p:
            continue
        h_pin, a_pin = cm.normalizar(p.get('home') or ''), cm.normalizar(p.get('away') or '')
        h_pdt, a_pdt = cm.normalizar(v.get('home') or ''), cm.normalizar(v.get('away') or '')
        if not (h_pin and a_pin and h_pdt and a_pdt):
            continue
        coincidencias += 1
        # invertido de verdad = el local de una es el visitante de la otra
        if cm._sim_club(h_pin, a_pdt) > cm._sim_club(h_pin, h_pdt):
            invertidos += 1
            print(f'AVISO bandos invertidos: pinnacle {p.get("home")}/{p.get("away")} '
                  f'vs playdoit {v.get("home")}/{v.get("away")}')
    if coincidencias:
        check(invertidos == 0,
              f"Playdoit y Pinnacle declaran el MISMO local en MLB "
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


def test_solo_mlb_en_el_tablon_de_mlb():
    """
    v88: el tablón de cuotas «mlb» trae LMB, NPB, KBO, CPBL y Triple-A.

    Medido el 2026-07-31: de 80 entradas en Pinnacle/Bovada/Playdoit, sólo 16
    eran MLB. Sin filtro llegaban a la Capa 1 partidos de la CPBL de Taiwán
    etiquetados «MLB» — y por duplicado, porque los nombres desconocidos no
    colapsan en la clave de deduplicación.

    Peor todavía: el fuzzy con umbral 0,60 daba por MLB a un 10 % de los
    equipos de otras ligas (Kia Tigers -> Detroit Tigers, Chiba Lotte Marines
    -> Seattle Mariners, Fubon Guardians -> Cleveland Guardians). Y `codigo_mlb`
    es la puerta al MOTOR, así que esos partidos se predecían con las
    estadísticas del equipo equivocado.
    """
    from engines.mlb_engine import (NOMBRES_MLB, codigo_mlb, es_equipo_mlb,
                                    es_partido_mlb, UMBRAL_FUZZY_MLB)

    check(UMBRAL_FUZZY_MLB >= 0.85,
          f"el umbral del fuzzy es estricto ({UMBRAL_FUZZY_MLB})")

    # los 30 equipos reales siguen resolviendo
    fallan = [n for n in NOMBRES_MLB if not es_equipo_mlb(n)]
    check(not fallan, f"los 30 equipos de MLB siguen reconociéndose ({fallan})")

    # y los de otras ligas ya no
    intrusos = {
        'Kia Tigers': 'KBO', 'Chiba Lotte Marines': 'NPB',
        'Fubon Guardians': 'CPBL', 'Sacramento River Cats': 'Triple-A',
        'Tacoma Rainiers': 'Triple-A', 'Rakuten Monkeys': 'CPBL',
        'Uni-President 7-Eleven Lions': 'CPBL', 'Hanshin Tigers': 'NPB',
        'Olmecas de Tabasco': 'LMB', 'Toros de Tijuana': 'LMB',
        'Lotte Giants': 'KBO', 'Samsung Lions': 'KBO',
    }
    colados = [f'{n} ({liga}) -> {codigo_mlb(n)}'
               for n, liga in intrusos.items() if es_equipo_mlb(n)]
    check(not colados, f"ningún equipo de otra liga pasa por MLB ({colados})")

    check(not es_partido_mlb('Rakuten Monkeys', 'Uni-President Lions'),
          "el partido de la CPBL que llegó a la Capa 1 ya no pasa")
    check(es_partido_mlb('New York Yankees', 'Boston Red Sox'),
          "un partido de MLB de verdad sí pasa")

    # alias habituales de las casas
    for alias, cod in (('LA Dodgers', 'LAN'), ('NY Yankees', 'NYA'),
                       ('St Louis Cardinals', 'SLN'), ('Athletics', 'OAK')):
        check(codigo_mlb(alias) == cod,
              f"alias de casa reconocido: {alias} -> {cod} "
              f"(dio {codigo_mlb(alias)})")

    # y el barrido aplica el filtro
    af = open('alpha_finder.py', encoding='utf-8').read()
    check('es_partido_mlb' in af,
          "el barrido de valor de mercado filtra a MLB de verdad")


def test_sin_the_odds_api():
    """
    v88: The Odds API se retira. La clave devolvía 401 en TODAS las ligas y
    sólo llenaba el arranque de errores, uno por competición.

    Las cuotas vienen de `cuotas_multi` (Pinnacle + Bovada + Playdoit) y de los
    fixtures de ESPN, que son gratuitas y cubren más partidos.
    """
    import importlib.util
    for mod in ('odds_api', 'cross_arbitrage', 'props_scraper'):
        check(importlib.util.find_spec(mod) is None,
              f"el módulo {mod} ya no existe")

    # la función pura que se usaba de allí sigue disponible
    import cuotas_multi as cm
    check(hasattr(cm, 'sharp_gap_2via'),
          "sharp_gap_2via se conserva en cuotas_multi")
    g = cm.sharp_gap_2via(0.60, 2.0, 2.0)
    check(g is not None and abs(g - 0.10) < 1e-9,
          f"y calcula igual que antes ({g})")
    check(cm.sharp_gap_2via(0.6, None, 2.0) is None,
          "sin cuota sharp devuelve None")

    # y la lectura de cuotas históricas para el entrenamiento se conserva
    import fetch_odds
    check(hasattr(fetch_odds, 'cargar_features_cuotas'),
          "fetch_odds conserva la lectura local para el entrenamiento")
    check(not hasattr(fetch_odds, 'actualizar_odds'),
          "y ya no tiene la descarga por API")

    # nadie llama al módulo retirado
    for f in ('alpha_finder.py', 'dashboard_ui.py', 'engines/mlb_engine.py',
              'pipeline_total.py', 'pipeline_mundial.py'):
        codigo = [l for l in open(f, encoding='utf-8').read().splitlines()
                  if l.strip() and not l.strip().startswith('#')]
        malos = [l.strip() for l in codigo
                 if 'import odds_api' in l or 'odds_api.' in l]
        check(not malos, f"{f} no llama a odds_api ({malos[:2]})")


def test_ventana_24h():
    """
    v91: «Apuestas del Día» es el DÍA CALENDARIO — si es 1 de agosto, solo
    partidos del 1 de agosto, sin importar la hora de la consulta.

    Sustituye el contrato de la v88 (rolling 24 h): a las 20:00 aquella
    ventana ya metía los partidos de mañana por la mañana, y la de la v89
    (semana entera etiquetada) mezclaba picks del sábado con los de hoy. El
    usuario rechazó ambas expresamente.
    """
    import pandas as pd
    import alpha_finder as af

    hoy = pd.Timestamp.utcnow().tz_localize(None).normalize()

    def fx(dias):
        return {'fecha': str((hoy + pd.Timedelta(days=dias)).date())}

    check(af._es_del_dia(fx(0)), "un partido de HOY entra, a cualquier hora")
    check(not af._es_del_dia(fx(1)), "uno de MAÑANA no entra")
    check(not af._es_del_dia(fx(-1)), "uno de AYER no entra")
    check(not af._es_del_dia(fx(3)), "uno del fin de semana no entra")
    check(not af._es_del_dia({'fecha': 'no-es-fecha'}),
          "una fecha ilegible no revienta: simplemente no entra")

    # el camino de The Odds API está retirado del barrido (v91)
    src = open('alpha_finder.py', encoding='utf-8').read()
    check("odds_actuales.json'" not in src.replace(
        "SE RETIRA EL CAMINO DE `odds_actuales.json`", ''),
          "alpha_finder ya no lee odds_actuales.json")
    # Se comprueba sobre las CADENAS QUE VE EL USUARIO, no sobre comentarios
    # ni docstrings — que sí nombran lo retirado, y deben hacerlo, para
    # explicar por qué ya no está. Se recorre el árbol y se ignoran los
    # literales que son documentación.
    import ast
    _arbol = ast.parse(src)
    _docs = set()
    for _n in ast.walk(_arbol):
        if isinstance(_n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef)):
            _d = ast.get_docstring(_n, clean=False)
            if _d:
                _docs.add(_d)
    _vivas = [_n.value for _n in ast.walk(_arbol)
              if isinstance(_n, ast.Constant) and isinstance(_n.value, str)
              and 'Odds API' in _n.value and _n.value not in _docs]
    check(not _vivas,
          f"ninguna cadena viva de alpha_finder menciona The Odds API "
          f"({[v[:60] for v in _vivas[:1]]})")


def test_telegram_no_rehace_el_barrido():
    """
    v88: pulsar «Enviar a Telegram» tumbaba la app.

    `construir_mensaje()` llamaba a `apuestas_del_dia_universal()` por su
    cuenta, saltándose el guardia de la v86. Como el dashboard ya tenía el
    barrido en memoria, el botón lanzaba un SEGUNDO barrido completo:
    1.297,7 MB uno, 2.172,2 MB dos.
    """
    import inspect
    import bot_telegram

    sig = inspect.signature(bot_telegram.construir_mensaje)
    check('resultado' in sig.parameters,
          f"construir_mensaje acepta un barrido ya hecho ({list(sig.parameters)})")

    src = inspect.getsource(bot_telegram.construir_mensaje)
    check('guardia_barrido' in src,
          "y sin argumento pasa por el guardia, no por alpha_finder a pelo")

    dash = open('dashboard_ui.py', encoding='utf-8').read()
    check('construir_mensaje(r)' in dash,
          "el dashboard le pasa el barrido que ya calculó")
    check('_enviar_telegram' in dash,
          "el botón marca la intención y el envío va después del barrido")


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
    # v91: un solo barrido de fútbol (el de `odds_actuales.json` se retiró),
    # así que la comprobación pasa de «>=2 sitios» a «el que hay».
    check(af.count('prior_elo=False') >= 1,
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
    # v91: ver arriba — queda un único barrido de fútbol.
    check(af.count('prior_elo=False') >= 1,
          "alpha_finder desactiva el prior en el barrido de fútbol")


def test_proximos_partidos_todas_las_competiciones():
    """
    v102: «la Champions no trae los próximos partidos». No era un fallo de red:
    en agosto la Champions está en fase previa, y ESPN publica esa fase bajo un
    código DISTINTO. Además la ventana era de 7 días fijos, así que toda liga
    entre temporadas salía vacía.
    """
    import fixtures_espn as fe

    # 1. las competiciones con fase previa tienen su código compañero
    for clave, esperado in (('champions', 'uefa.champions_qual'),
                            ('europa_league', 'uefa.europa_qual'),
                            ('conference_league', 'uefa.europa.conf_qual'),
                            ('afc_champions', 'afc.champions_qual')):
        check(esperado in fe.ESPN_COMPANEROS.get(clave, []),
              f'{clave} consulta también su fase previa ({esperado})')

    # 2. la ampliación es OPT-IN: el barrido pide `dias=2` para quedarse con
    #    hoy, y ampliarle el horizonte le haría pedir 90 días a cada liga fuera
    #    de temporada en cada pase, para tirarlo todo después.
    import inspect
    firma = inspect.signature(fe.fixtures_liga)
    check('ampliar' in firma.parameters,
          'fixtures_liga permite decidir si amplía el horizonte')
    check(firma.parameters['ampliar'].default is None,
          'por defecto amplía sólo en la vista de próximos partidos')
    check(len(fe.HORIZONTES) >= 2 and fe.HORIZONTES[0] == fe.DIAS_SEMANA,
          f'los escalones empiezan en la semana ({fe.HORIZONTES})')

    # 3. toda liga disponible tiene por dónde traer sus partidos
    from config import LEAGUES
    sin_via = [c for c, cfg in LEAGUES.items()
               if cfg.get('disponible') and c not in fe.ESPN_CODIGOS]
    # Polonia es la excepción CONOCIDA: ESPN devuelve 400 en pol.1, pol.2 y
    # pol.ekstraklasa (comprobado 2026-08-06). Se declara en vez de fingir.
    check(set(sin_via) <= {'polonia'},
          f'todas las ligas disponibles tienen código ESPN salvo Polonia '
          f'(sin vía: {sin_via})')


def test_aprendizaje_continuo():
    """
    v101: el lazo que aprende de sus propios resultados es autónomo, así que
    sus guardarraíles son lo único que impide que se sobreajuste solo. Se
    comprueban las cuatro propiedades de las que depende su seguridad.
    """
    import aprendizaje_continuo as ac

    # 1. sin mapa aprendido NO toca nada — degradar a la identidad, no a un
    #    número inventado, es lo que permite desplegarlo antes de tener datos
    check(ac.aplicar(0.72, {}) == 0.72,
          'sin mapa aprendido, la probabilidad sale intacta')
    check(ac.aplicar(None, {'global': {'a': 0.5, 'b': 0.0}}) is None,
          'una probabilidad ausente no se inventa')

    # 2. MONOTONÍA: la corrección no puede reordenar los picks. Es la propiedad
    #    que garantiza que recalibrar no convierta un buen pick en malo.
    nodo = {'global': {'a': 0.6, 'b': -0.3, 'n': 500}}
    ps = [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95]
    corregidas = [ac.aplicar(p, nodo) for p in ps]
    check(all(x < y for x, y in zip(corregidas, corregidas[1:])),
          f'la corrección es monótona (no reordena): '
          f'{[round(c, 3) for c in corregidas]}')

    # 3. TOPE DURO: nunca desplaza una probabilidad más de TOPE_AJUSTE, por
    #    extremo que sea el mapa. Sin esto, un nodo mal ajustado con poca
    #    muestra podría reescribir el pronóstico en vez de matizarlo.
    brutal = {'global': {'a': 1.5, 'b': -5.0, 'n': 60}}
    peor = max(abs(ac.aplicar(p, brutal) - p) for p in ps)
    check(peor <= ac.TOPE_AJUSTE + 1e-9,
          f'ningún ajuste supera el tope de ±{ac.TOPE_AJUSTE} '
          f'(máximo observado {peor:.4f})')

    # 4. ENCOGIMIENTO: con poca muestra el nodo se queda cerca de su prior. Es
    #    lo que impide que 30 picks de una racha manden sobre 47.794
    #    predicciones del ledger.
    prior = (0.30, 0.70)
    poco = ac._encoger((1.5, -5.0), prior, n=10)
    mucho = ac._encoger((1.5, -5.0), prior, n=20000)
    check(abs(poco[0] - prior[0]) < abs(mucho[0] - prior[0]),
          f'con n=10 se queda pegado al prior y con n=20.000 se separa '
          f'(a: {poco[0]:.3f} vs {mucho[0]:.3f})')

    # y el artefacto publicado, si existe, tiene que declarar su tope
    if os.path.exists('calibracion_adaptativa.json'):
        with open('calibracion_adaptativa.json', encoding='utf-8') as f:
            d = json.load(f)
        check(d.get('tope_ajuste') is not None and d.get('n0'),
              'el mapa publicado declara su tope y su fuerza de prior')
        g = (d.get('mapa') or {}).get('global') or {}
        check(ac.PENDIENTE_MIN <= g.get('a', 1.0) <= ac.PENDIENTE_MAX,
              f"la pendiente global está en rango ({g.get('a')})")


def test_features_del_modelo_coinciden():
    """
    v101: un modelo guardado con otro vector de features no puede usarse. La
    fuga de fatiga de WTA obligó a cambiar el vector, y sin esta guarda el
    desajuste salía como un error de forma de sklearn en mitad de una
    predicción — ilegible y fácil de confundir con un fallo de datos.
    """
    import inspect

    from engines.base_engine import BaseSportsEngine
    src = inspect.getsource(BaseSportsEngine.cargar_modelo)
    check('features' in src and 'reentrenar' in src,
          'cargar_modelo compara las features guardadas con las del motor')

    import engines.tennis_engine as te
    wta = te.TennisEngine('wta').features
    fuera = [f for f in te.FEATURES_FATIGA if f in wta]
    check(not fuera,
          f'el vector de WTA ya no lleva features de fatiga (sobran: {fuera})')
    check(len(wta) == 11, f'WTA usa 11 features tras la v101 ({len(wta)})')
    atp = te.TennisEngine('atp').features
    check(not [f for f in te.FEATURES_FATIGA if f in atp],
          'ATP nunca las llevó y sigue sin llevarlas')


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
    # v114 — la contención sigue casando, pero YA NO empata con la igualdad.
    #
    # Este check exigía >= 0,99, es decir, que «Gremio» y «Gremio FBPA»
    # puntuaran igual que dos nombres idénticos. Eso es lo que hacía que
    # «Independiente» casara perfecto con «Independiente Rivadavia» —dos clubes
    # distintos de la misma liga argentina— y el sistema tomara las cuotas del
    # partido equivocado. Lo que hay que exigir es que la contención SIGA
    # emparejando (para eso se escribió) y que pierda contra el exacto.
    check(cm._sim_club('Gremio', 'Gremio FBPA') >= 0.80,
          'un nombre contenido en otro sigue casando («Gremio» / «Gremio FBPA»)')
    check(cm._sim_club('Independiente', 'Independiente Rivadavia')
          < cm._sim_club('Belgrano', 'Belgrano'),
          'pero la contención puntúa por debajo de la igualdad exacta')
    check(cm._sim_club('Dinamo Moscow', 'Dynamo Moscow') > 0.5,
          'las variantes de transliteración siguen casando')
    check(cm._sim_club('Palmeiras', 'Boca Juniors') < 0.80,
          'dos equipos distintos no casan')
    check(isinstance(cm._tokens_club('Real Madrid'), frozenset),
          '_tokens_club devuelve frozenset (la caché no se puede corromper)')


def test_guardias_del_emparejador():
    """
    v114 — el emparejador no puede tomar las cuotas de OTRO partido.

    Caso real medido el 2026-08-09 en el tablón de producción: «Independiente
    vs Belgrano» de la Primera División FEMENINA argentina (10-ago) se emparejó
    con «Belgrano vs Independiente Rivadavia» de la Liga Profesional masculina
    (15-ago), y encima con los bandos invertidos. No dio ningún error: dio un
    arbitraje falso del 0,7737 y un EV inventado sobre un partido inexistente.
    """
    try:
        import cuotas_multi as cm
    except Exception as e:
        print(f'AVISO cuotas_multi no disponible ({e}); se omite')
        return

    # --- categoría --------------------------------------------------------
    check('fem' in cm.categoria_partido('CA Independiente (W)', 'Belgrano (W)'),
          'la marca «(W)» identifica un partido femenino')
    check('fem' in cm.categoria_partido('Independiente', 'Belgrano',
                                        'Argentina - Primera Division Women'),
          'y también se lee del nombre de la competición, no sólo del equipo')
    check(not cm.categoria_partido('Independiente', 'Belgrano'),
          'un partido sin marcas es el absoluto masculino')
    check(not cm.categoria_partido('Boca Juniors', 'River Plate'),
          'un club con «Juniors» en el nombre NO es una categoría inferior')
    check('filial' in cm.categoria_partido('Brasil U20', 'Chile U20'),
          'las selecciones sub-20 se marcan como categoría inferior')
    check(cm.categoria_efectiva('Benfica II', 'Leixoes')
          == cm.categoria_efectiva('Benfica Sub-21', 'Leixoes'),
          '«Benfica II» y «Benfica Sub-21» son el mismo filial')
    check(cm.categoria_efectiva('Benfica II', 'Leixoes')
          != cm.categoria_efectiva('Benfica', 'Leixoes'),
          'pero el filial no es el primer equipo')
    check(not cm.categoria_efectiva('Laferrere', 'Arsenal de Sarandi',
                                    'Argentina - Primera B Metropolitana'),
          'una liga llamada «Primera B» no convierte el partido en filial')

    # --- fecha ------------------------------------------------------------
    idx = {'belgrano|independiente rivadavia': {
        'home': 'Belgrano', 'away': 'Independiente Rivadavia',
        'fecha': '2026-08-15T22:00:00', 'cuotas': {'home': 1.95, 'away': 4.3}}}
    check(cm._buscar(idx, 'Independiente', 'Belgrano', 'futbol',
                     fecha='2026-08-10T18:00:00') is None,
          'cinco días de diferencia descartan el emparejamiento')
    check(cm._buscar(idx, 'Belgrano', 'Independiente Rivadavia', 'futbol',
                     fecha='2026-08-15T20:00:00') is not None,
          'el mismo partido en su fecha sí empareja')

    # --- ambigüedad -------------------------------------------------------
    idx2 = {'independiente|belgrano': {'home': 'Independiente',
                                       'away': 'Belgrano',
                                       'cuotas': {'home': 2.0, 'away': 3.0}},
            'independiente rivadavia|belgrano': {
                'home': 'Independiente Rivadavia', 'away': 'Belgrano',
                'cuotas': {'home': 2.5, 'away': 2.6}}}
    _r = cm._buscar(idx2, 'Independiente', 'Belgrano', 'futbol')
    check(_r is not None and _r['home'] == 'Independiente',
          'con el club exacto y uno que lo contiene en el tablón, gana el exacto')

    # --- el barrido pasa la fecha ----------------------------------------
    import inspect
    check('fecha' in inspect.signature(cm.cuotas_partido).parameters,
          'cuotas_partido acepta la fecha del fixture para desambiguar')
    _src = inspect.getsource(__import__('fixtures_espn')._completar_cuotas)
    check('fecha=' in _src,
          'y el barrido de fixtures se la pasa (si no, la guardia no actúa)')


def test_exchange_matchbook():
    """
    v114 — el exchange entra al tablón con dos condiciones innegociables.

    Matchbook sustituye a Betfair, que está cerrado desde México por
    geolocalización. Medido sobre el tablón del 2026-08-09: da el mejor precio
    el 36,5 % de las veces (más que Pinnacle) y baja el margen del mejor precio
    de 1,0395 a 1,0314. Pero un exchange no es una casa y hay dos cosas que no
    se pueden olvidar sin envenenar el line shopping.
    """
    try:
        import cuotas_multi as cm
    except Exception as e:
        print(f'AVISO cuotas_multi no disponible ({e}); se omite')
        return

    # --- 1. la comisión se descuenta SIEMPRE ------------------------------
    # Un exchange no cobra margen en la cuota: cobra sobre la ganancia neta.
    # Comparar su back bruto contra el precio de una casa lo inflaría, y la
    # mejora media que aporta es del orden de la propia comisión.
    check(cm.cuota_neta_exchange(3.0, 0.02) == 2.96,
          'una back de 3,00 con 2 % de comisión paga 2,96, no 3,00')
    check(cm.cuota_neta_exchange(2.0, 0.0) == 2.0,
          'sin comisión la cuota no cambia')
    check(cm.cuota_neta_exchange(1.0) is None,
          'una cuota de 1,00 no es una cuota')
    check(cm.cuota_neta_exchange('x') is None,
          'una cuota ilegible no se inventa')
    check(cm.cuota_neta_exchange(3.0) < 3.0,
          'la comisión por defecto es mayor que cero')

    # --- 2. un precio sin dinero detrás no es un precio -------------------
    # Medido en el primer volcado real: «Los Andes vs Ferro Carril Oeste» con
    # el local a 98,02 porque el libro estaba vacío. Sin estas guardias el
    # line shopping habría elegido 98,02 como mejor precio.
    check(cm.IMPORTE_MINIMO_EXCHANGE > 0,
          'se exige un importe mínimo disponible para aceptar un precio')
    check(0.5 < cm.MARGEN_MINIMO_EXCHANGE < 1.0,
          'y que el libro esté cotizado entero (margen mínimo)')
    import inspect
    _src = inspect.getsource(cm._indice_matchbook)
    check('available-amount' in _src,
          'la liquidez se lee del propio precio, no se supone')
    check('cuota_neta_exchange' in _src,
          'y la cuota se guarda ya neta de comisión, no bruta')

    # --- 3. está enchufado al tablón --------------------------------------
    _src2 = inspect.getsource(cm.cuotas_partido)
    check("casas['Matchbook']" in _src2,
          'Matchbook entra en cuotas_partido como una casa más')
    check('_indice_mb' in _src2,
          'y usa su propio índice cacheado')


def test_tablon_a_mercados():
    """
    v114 — todas las ligas enseñan los mismos mercados, no sólo las que ESPN
    identifica.

    La Champions, la Conference y la Eredivisie sólo veían el 1X2 porque
    `buscar_event_id` no localiza a sus equipos de fase previa. `cuotas_tablon`
    traduce lo que el tablón multi-casa ya devolvía —totales, ambos marcan,
    hándicap— al vocabulario de la plantilla y lo cruza con el modelo.
    """
    try:
        import cuotas_tablon as ct
    except Exception as e:
        print(f'AVISO cuotas_tablon no disponible ({e}); se omite')
        return

    res = {
        'casas': {'Pinnacle': {'home': 2.0, 'draw': 3.4, 'away': 3.8},
                  'Bovada': {'home': 2.1, 'draw': 3.3, 'away': 3.6},
                  '_totales': {'over25': 1.9}},
        'totales_por_casa': {'Pinnacle': {'over25': 1.9, 'under25': 1.95,
                                          'btts_yes': 1.8, 'btts_no': 2.0}},
        'handicap_por_casa': {'Pinnacle': {'linea': -0.5, 'home': 1.95,
                                           'away': 1.9}},
    }
    filas = ct.filas_del_tablon(res, 'Monterrey', 'Juarez')
    etiquetas = {f['etiqueta'] for f in filas}
    check('Gana Monterrey' in etiquetas, 'el 1X2 sale con el nombre del local')
    check('Más de 2.5 goles' in etiquetas,
          'los totales salen con el vocabulario de la plantilla')
    check('Ambos equipos marcan: Sí' in etiquetas, 'y el «ambos marcan»')
    check('Monterrey -0.5' in etiquetas and 'Juarez +0.5' in etiquetas,
          'el hándicap sale con la línea de CADA lado, no la del local en los dos')
    check(not any(f['casa'].startswith('_') for f in filas),
          'el cajón interno «_totales» no se cuela como si fuera una casa')

    # line shopping: entre dos casas manda el precio más alto
    pl = {'secciones': [{'titulo': '1X2', 'campos': [
        {'id': 'home_win_prob', 'etiqueta': 'Gana Monterrey', 'valor': 50.0,
         'tipo': 'pct'}]}]}
    mk = ct.mercados_con_ev(res, pl, 'Monterrey', 'Juarez')
    fila = next((r for r in mk if r['id'] == 'home_win_prob'), None)
    check(fila is not None, 'el mercado se cruza con la plantilla del modelo')
    if fila:
        check(fila['cuota_casa'] == 2.1 and fila['casa'] == 'Bovada',
              'y se queda con el MEJOR precio (2,1 de Bovada, no 2,0 de Pinnacle)')
        check(fila['n_casas'] == 2, 'diciendo cuántas casas se compararon')
        check(abs(fila['ev'] - 0.05) < 1e-6,
              'el EV usa la cuota real: 2,1 × 0,50 − 1 = +5 %')

    # el motor envuelto es transparente para todo lo demás
    class _Falso:
        clave = 'liga_mx'
        def plantilla_club(self, h, a):
            return {'secciones': []}
        def otra_cosa(self):
            return 'intacto'
    m = ct.MotorConTablon(_Falso(), {'over25': 1.95}, {'over25': 'Pinnacle'})
    check(m.otra_cosa() == 'intacto',
          'el motor envuelto delega todo lo que no sea la plantilla')
    check(m.clave == 'liga_mx', 'incluidos los atributos')
    check(m.plantilla_club('a', 'b').get('cuotas_tablon') == {'over25': 1.95},
          'y engancha las cuotas reales a la plantilla que devuelve')


def test_selecciones_completas():
    """
    v114 — «todos los partidos de selecciones, varonil, femenil, amistosos».

    La lista tenía siete competiciones, todas masculinas absolutas: ni un
    torneo continental, ni una femenina, ni una olímpica.
    """
    try:
        import fixtures_espn as fe
    except Exception as e:
        print(f'AVISO fixtures_espn no disponible ({e}); se omite')
        return
    ligas = dict(fe.LIGAS_SELECCIONES)
    check(len(ligas) >= 20,
          f'el catálogo de selecciones cubre {len(ligas)} competiciones (eran 7)')
    for clave in ('fifa.world', 'concacaf.gold', 'conmebol.america',
                  'caf.nations', 'afc.asian.cup', 'uefa.euro',
                  'concacaf.nations.league'):
        check(clave in ligas, f'incluye {clave}')
    femeninas = [t for t in ligas.values() if 'femenin' in t.lower()]
    check(len(femeninas) >= 3,
          f'y {len(femeninas)} competiciones femeninas (no había ninguna)')
    # el nombre del torneo es lo que le dice al emparejador que es femenino
    import cuotas_multi as cm
    for torneo in femeninas:
        check('fem' in cm.categoria_partido('Spain', 'England', torneo),
              f'«{torneo}» se reconoce como femenino en el emparejador')
    check('fem' not in cm.categoria_partido('Spain', 'England', 'Amistoso'),
          'y un amistoso masculino no')

    # v115 — el calendario también sale del TABLÓN, porque ESPN da 403 en
    # Streamlit Cloud y allí las 22 competiciones fallan las 22.
    check(fe.es_competicion_de_selecciones('FIFA World Cup Qualifying - UEFA'),
          'una clasificatoria se reconoce como competición de selecciones')
    check(fe.es_competicion_de_selecciones('UEFA Nations League'),
          'y la Nations League')
    check(not fe.es_competicion_de_selecciones('Club Friendlies'),
          'pero «Club Friendlies» es de clubes, no de selecciones')
    check(not fe.es_competicion_de_selecciones('CONMEBOL - Copa Libertadores'),
          'ni la Libertadores, que lleva «CONMEBOL» en el nombre')
    check(not fe.es_competicion_de_selecciones('UEFA - Champions League Qualifiers'),
          'ni una previa de Champions, que lleva «Qualifiers»')
    check(fe.es_competicion_de_selecciones('Campeonato Sub-20 CONCACAF'),
          'un sub-20 CON confederación sí es de selecciones')
    check(not fe.es_competicion_de_selecciones('Paulista Sub-20'),
          'pero un sub-20 de clubes no (fue un falso positivo real del tablón)')
    check(not fe.es_competicion_de_selecciones('Myanmar — Championship U20'),
          'ni una liga juvenil nacional de clubes')
    import inspect
    check('_con_tablon' in inspect.getsource(fe.fixtures_selecciones)
          and 'selecciones_del_tablon' in inspect.getsource(fe._con_tablon),
          'y el calendario de selecciones se fusiona con el del tablón')
    # v115 — cortacircuitos: un 403 es un veto a la fuente entera, no un fallo
    # de esa competición. Sin esto eran 22 peticiones y 22 líneas de registro
    # en cada arranque, que es el muro de errores que reportó el usuario.
    _src_sel = inspect.getsource(fe.fixtures_selecciones)
    check('403' in _src_sel and '_marcar_espn_bloqueado' in _src_sel,
          'con 403 se deja de pedir el resto de competiciones')
    fe._ESPN_BLOQUEADO_HASTA[0] = 0
    check(not fe._espn_bloqueado(), 'la marca de bloqueo arranca limpia')
    fe._marcar_espn_bloqueado()
    check(fe._espn_bloqueado(), 'y se puede marcar cuando ESPN veta')
    check(fe.TTL_BLOQUEO_ESPN > 0,
          'la marca CADUCA: si el bloqueo se levanta, la fuente vuelve sola')
    fe._ESPN_BLOQUEADO_HASTA[0] = 0


def test_metricas_con_procedencia():
    """
    v117 — una métrica de validación en el metadata tiene que decir de dónde sale.

    El caso que lo motivó: el bloque `walk_forward` de la KBO estaba escrito a
    mano desde la v97, el entrenamiento NO lo recalculaba, y el metadata lo
    presentaba como «lo que de verdad autoriza a desplegar». Se descubrió al
    integrar las features del abridor: salió idéntico cifra por cifra con las
    columnas del modelo ya cambiadas.

    Se revisaron todos los motores y era el único caso. `monitor_canales`
    también lleva cifras fijas, pero declara su `fuente` en cada una, que es
    justo lo que aquí se exige.
    """
    import json
    import os

    # 1. el bloque de la KBO ya no puede leerse como si fuera de hoy
    ruta = os.path.join('modelos', 'kbo', 'metadata.json')
    if os.path.exists(ruta):
        try:
            meta = json.load(open(ruta, encoding='utf-8'))
        except Exception as e:
            print(f'AVISO metadata de KBO ilegible ({e}); se omite')
            meta = {}
        wf = meta.get('walk_forward') or {}
        if wf:
            check('medido_en' in wf or 'aviso' in wf,
                  'el walk-forward de la KBO declara que es un valor histórico')
            check('corresponde_a' in wf,
                  'y a qué modelo corresponde (no al desplegado)')
        va = meta.get('validacion_abridor') or {}
        if va:
            check(va.get('bootstrap_p5', 0) > 0,
                  f"las features del abridor se integraron con p5 positivo "
                  f"({va.get('bootstrap_p5')})")
            check(va.get('juzgados', 0) >= 500,
                  f"y con muestra de juicio suficiente ({va.get('juzgados')})")
        check(list(meta.get('columnas_modelo') or []) ==
              [0, 5, 9, 10, 11, 12],
              'el clasificador de KBO mira ELO, abridor, IDF y las tres nuevas')

    # 2. las referencias fijas de monitor_canales declaran su procedencia
    try:
        import monitor_canales
        for clave, ref in (monitor_canales.REFERENCIAS or {}).items():
            check(bool(ref.get('fuente')),
                  f'la referencia «{clave}» dice de qué versión y muestra sale')
    except Exception as e:
        print(f'AVISO monitor_canales no disponible ({e}); se omite')


def test_bf_por_apertura():
    """
    v115 — el sesgo que inflaba las líneas de ponches.

    Medido contra los registros por juego de MLB StatsAPI: la Poisson estaba
    bien calibrada (promete 54,4 %, cumple 54,8 % en 5.118 evaluaciones), pero
    `bf_apertura` sobreestimaba +2,43 bateadores porque `bf/gs` mezcla los
    bateadores enfrentados como RELEVISTA con las aperturas. Con un k/BF de
    liga de 0,2213 eso son +0,54 ponches — justo el sesgo del λ observado.
    """
    try:
        import beisbol_pitchers as bp
    except Exception as e:
        print(f'AVISO beisbol_pitchers no disponible ({e}); se omite')
        return
    f = bp._bf_por_apertura
    check(f(0, 0) == bp.BF_APERTURA_LIGA,
          'sin datos se usa la media de la liga, no un número inventado')
    check(f(500, 0) == bp.BF_APERTURA_LIGA,
          'sin aperturas tampoco se divide por cero')
    # el caso real: Andrew Álvarez, 7 aperturas y 210 bateadores porque casi
    # todos fueron de relevo → 30,0 con el código viejo, 18,6 de verdad
    check(f(210, 7) == bp.BF_APERTURA_LIGA,
          'un bf/gs imposible (30) se descarta: son relevos contando de más')
    # un abridor puro no se toca apenas
    check(23.0 <= f(23.1 * 22, 22) <= 23.5,
          'un abridor con 22 aperturas conserva su media (23,1)')
    check(f(27.0 * 25, 25) > 25.0,
          'y un abridor largo de verdad (27,0 en 25 aperturas) no se aplana')
    # con muestra corta se encoge hacia la liga
    _corto = f(20.0 * 2, 2)
    check(20.0 < _corto < bp.BF_APERTURA_LIGA,
          f'con 2 aperturas el dato se encoge hacia la liga ({_corto:.1f})')
    check(bp.BF_APERTURA_MIN <= f(10 * 5, 5) <= bp.BF_APERTURA_MAX,
          'el resultado siempre cae dentro del rango posible')


def test_lineas_alternativas():
    """
    v115 — las líneas alternativas de Pinnacle ya no se tiran.

    Se descartaba todo lo marcado `isAlternate`, así que cada partido tenía
    UNA línea de goles y el hándicap principal: medido, 1,0 y 2,0 por partido.
    Sin material, la casilla «solo mercados con cuota REAL» no podía armar
    ninguna combinada y respondía que no había mercados.
    """
    try:
        import cuotas_multi as cm
        import cuotas_tablon as ct
    except Exception as e:
        print(f'AVISO módulos de cuotas no disponibles ({e}); se omite')
        return
    import inspect
    _src = inspect.getsource(cm._indice_pinnacle)
    check('totales_alt' in _src and 'spreads_alt' in _src,
          'el índice de Pinnacle guarda las líneas alternativas')
    check("d.setdefault('totales', {})" in _src,
          'y `totales` sigue siendo sólo la principal (nadie cambia de significado)')

    res = {'casas': {'Pinnacle': {'home': 2.0, 'draw': 3.4, 'away': 3.8}},
           'lineas_totales': {'1.5': {'over': 1.2, 'under': 4.5},
                              '2.5': {'over': 1.9, 'under': 1.95},
                              '3.5': {'over': 3.1, 'under': 1.35},
                              '2.25': {'over': 1.8, 'under': 2.0},
                              '3.0': {'over': 2.2, 'under': 1.7}},
           'lineas_handicap': {'-0.5': {'home': 1.95, 'away': 1.9},
                               '-1.5': {'home': 3.2, 'away': 1.35},
                               '-0.25': {'home': 1.8, 'away': 2.0}}}
    filas = ct.filas_del_tablon(res, 'Monterrey', 'Juarez')
    etiquetas = {f['etiqueta'] for f in filas}
    for e in ('Más de 1.5 goles', 'Menos de 3.5 goles', 'Monterrey -1.5',
              'Juarez +1.5'):
        check(e in etiquetas, f'se publica «{e}»')
    check(not any('2.25' in e or '0.25' in e for e in etiquetas),
          'las líneas asiáticas de cuarto NO se publican: la plantilla no las '
          'tiene y el cruce difuso las casaría con la de al lado')
    check(not any('Más de 3 goles' == e for e in etiquetas),
          'ni las líneas enteras, que se liquidan con devolución')
    check(len(filas) >= 10,
          f'un partido pasa de 5 mercados a {len(filas)} filas cotizadas')
    # la caché tiene que estar activa
    check(hasattr(cm.normalizar, 'cache_info'),
          'normalizar está memoizada')


def test_itf_tiene_datos_y_modelo():
    """
    v96 — el circuito ITF ya no es un agujero.

    La v95 lo excluyó del barrido con un motivo medido: no había fuente de
    resultados. La v96 la encontró — un espejo de archivo de los datos de Jeff
    Sackmann, cuyos repos originales están **borrados de verdad** (404 de la
    API de GitHub; de todo su perfil sólo sobrevive el MatchChartingProject).

    Ingerido: 566.130 partidos y 23.393 jugadores de ITF y challenger. El
    histórico de ATP pasa de 75.004 partidos a 365.017, y de 1.380 jugadores
    a 12.897.
    """
    import os

    import ingesta_itf

    check(os.path.exists(ingesta_itf.SALIDA),
          f"el histórico de ITF está ingerido ({ingesta_itf.SALIDA})")
    if not os.path.exists(ingesta_itf.SALIDA):
        return

    total = 0
    for circ in ('atp', 'wta'):
        d = ingesta_itf.cargar(circ)
        total += len(d)
        check(not d.empty, f"hay partidos de ITF/challenger para {circ.upper()}")
        if not d.empty:
            faltan = [c for c in ('Date', 'Player_1', 'Player_2', 'Winner',
                                  'Categoria') if c not in d.columns]
            check(not faltan,
                  f"{circ.upper()} respeta el esquema del proyecto "
                  f"(faltan {faltan})")
            check(d['Winner'].notna().all(),
                  f"{circ.upper()}: todos los partidos tienen ganador")
    check(total > 100_000,
          f"el volumen ingerido es el esperado ({total} partidos)")

    # el dato vive en NUESTRO repositorio: el original ya desapareció una vez
    check(os.path.getsize(ingesta_itf.SALIDA) > 1_000_000,
          "y pesa lo que debe (se guarda en el repo, no se re-descarga)")

    # ------------------------------------------------------------------
    # FUGA DE POSICIÓN — el fallo que casi se cuela en esta misma versión.
    #
    # Sackmann publica `winner_name`/`loser_name`. La traducción ingenua deja
    # al ganador siempre en `Player_1`, y entonces el modelo aprende a leer la
    # columna en vez de a predecir. Se probó y el síntoma parecía un triunfo:
    # el ATP saltó de 62,77 % a **93,54 %** de precisión de validación, que en
    # tenis es imposible. Con el 78 % del histórico viniendo de aquí, la fuga
    # habría contaminado también el circuito principal.
    # ------------------------------------------------------------------
    for circ in ('atp', 'wta'):
        d = ingesta_itf.cargar(circ)
        if d.empty:
            continue
        eq = float((d['Winner'] == d['Player_1']).mean())
        check(0.45 <= eq <= 0.55,
              f"{circ.upper()}: el ganador está repartido entre las dos "
              f"columnas ({eq:.1%}, se espera ~50 %) — sin fuga de posición")

    src = open('ingesta_itf.py', encoding='utf-8').read()
    check('fuga de posición' in src.lower() and 'raise ValueError' in src,
          "la ingesta se niega a escribir si el reparto se desequilibra")

    # y el filtro que excluía el circuito tiene que haberse retirado
    af = open('alpha_finder.py', encoding='utf-8').read()
    vivas = [l for l in af.splitlines()
             if "'ITF' in" in l and not l.lstrip().startswith('#')]
    check(not vivas,
          f"el barrido ya no excluye el ITF ({vivas[:1]})")


def test_fecha_normalizada_en_el_origen():
    """
    v95 — la fecha se normaliza EN EL ORIGEN, no en cada consumidor.

    Bovada publica milisegundos epoch y `pd.to_datetime` los interpreta como
    nanosegundos → 1970-01-01. El bug salió en la vista de tenis (v94), se
    corrigió AHÍ, y volvió a aparecer en las tarjetas de MLB. Con tres casas y
    media docena de consumidores, parchear caso por caso garantiza que
    reaparezca; por eso ahora la conversión vive en `cuotas_multi`, donde la
    fecha entra al sistema.
    """
    import cuotas_multi as cm

    f = cm.fecha_normalizada
    check(f(1785781800000) is not None and f(1785781800000).startswith('2026'),
          "el epoch en MILISEGUNDOS de Bovada se lee como 2026, no como 1970")
    check(f(1785781800) is not None and f(1785781800).startswith('2026'),
          "y también el epoch en segundos")
    check(f('2026-08-03T21:30:00Z') == '2026-08-03T21:30:00',
          "el ISO con zona de Pinnacle se conserva")
    check(f('2026-08-03T21:30:00') == '2026-08-03T21:30:00',
          "y el ISO sin zona de Playdoit")
    for basura in (None, '', 'no es fecha', 0, -1, True):
        check(f(basura) is None,
              f"lo que no es una fecha devuelve None ({basura!r})")

    # y ningún índice puede volver a guardar la fecha en crudo
    src = open('cuotas_multi.py', encoding='utf-8').read()
    crudas = [l for l in src.splitlines()
              if "'fecha':" in l and 'fecha_normalizada' not in l
              and not l.lstrip().startswith('#')]
    check(not crudas,
          f"los tres índices normalizan la fecha al construirse ({crudas[:1]})")

    # última guardia: la UI no puede imprimir un año imposible
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('Fecha no disponible' in ui,
          "la UI tiene una última guardia contra una fecha absurda")


def test_mensajes_sin_jerga_interna():
    """
    v95 — los mensajes que ve el usuario no citan versiones internas.

    El texto de la Capa 2 decía «el guardarraíl contra la sobreconfianza
    documentada en v71». Al usuario no le dice nada esa referencia —y encima
    quedó desactualizada—, así que los mensajes visibles se reescribieron para
    que los entienda alguien que nunca ha apostado.
    """
    import ast
    import re

    # v152 — la regla vale para TODO lo que pinta pantalla, no sólo para el
    # fichero grande. Las vistas viven cada vez más en módulos aparte
    # (`modo_modelo`, `render_todos_partidos`), y hasta aquí quedaban fuera del
    # guardia por el sitio donde estaban, no por lo que hacen.
    pat = re.compile(r'\bv\d{2,3}\b')
    for fichero in ('dashboard_ui.py', 'modo_modelo.py',
                    'render_todos_partidos.py', 'rendimiento_equipos.py'):
        if not os.path.exists(fichero):
            continue
        src = open(fichero, encoding='utf-8').read()
        arbol = ast.parse(src)
        docs = set()
        for n in ast.walk(arbol):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                d = ast.get_docstring(n, clean=False)
                if d:
                    docs.add(d)
        # cadenas vivas (ni comentarios ni docstrings) que citen «vNN».
        #
        # Un comentario CSS `/* ... */` dentro de una hoja de estilos NO es
        # texto visible: nadie lo lee en pantalla. Al ampliar el guardia a los
        # módulos de vista, la primera cosa que encontró fue exactamente eso, y
        # una alarma que salta en el caso normal deja de ser una alarma. Se
        # limpian antes de buscar.
        def _visible(t):
            return re.sub(r'/\*.*?\*/', ' ', t, flags=re.S)

        malas = [n.value[:70] for n in ast.walk(arbol)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and n.value not in docs and pat.search(_visible(n.value))]
        check(not malas,
              f"ningún texto visible de {fichero} cita una versión interna "
              f"({malas[:2]})")


def test_tenis_dos_fuentes_y_sets():
    """
    v94 — dos arreglos del tenis, ambos con la misma raíz: se estaba usando
    media fuente.

    1. El CALENDARIO sólo miraba ESPN, cuyo scoreboard sirve el cuadro
       principal y en su mayoría con emparejamientos **TBD vs TBD** (rondas sin
       definir). Medido: de 128 competiciones ATP no jugadas a 10 días vista,
       127 eran TBD y la vista enseñaba UN partido mientras el barrido operaba
       decenas. Ahora se completa con el tablón de cuotas, igual que el fútbol
       desde la v71.
    2. El MARCADOR POR SETS se creía no disponible («habría que buscar una
       fuente complementaria»), y ESPN ya lo publica en `linescores`. Medido:
       188 de 189 partidos (99 %) lo traen.
    """
    import fixtures_espn
    import tenis_fuentes

    src = open('tenis_fuentes.py', encoding='utf-8').read()
    check('_fixtures_desde_cuotas' in src,
          "el calendario de tenis se completa con el tablón de cuotas")
    check('unit=\'ms\'' in src or 'unit="ms"' in src,
          "y entiende el epoch en milisegundos de Bovada "
          "(si no, sus partidos caían en 1970-01-01)")

    # el marcador por sets se lee y se usa para liquidar
    fsrc = open('fixtures_espn.py', encoding='utf-8').read()
    check('linescores' in fsrc,
          "resultados_tenis lee el marcador set a set de ESPN")
    check('juegos_totales' in fsrc,
          "y calcula el total de juegos del partido")

    import liquidador
    partido = {'_ganador': 'vukic', 'sets': [0, 2], 'juegos_totales': 18}
    check(liquidador._gano_tenis('Gana Vukic A.', partido) is True,
          "se resuelve el ganador")
    check(liquidador._gano_tenis('Más de 17.5 juegos', partido) is True,
          "se resuelve el total de juegos (18 > 17,5)")
    check(liquidador._gano_tenis('Menos de 17.5 juegos', partido) is False,
          "y su contrario")
    check(liquidador._gano_tenis('Resultado 2-0 en sets', partido) is True,
          "se resuelve el marcador por sets")
    check(liquidador._gano_tenis('Algo que no existe', partido) is None,
          "y lo que no se sabe leer devuelve None, no se inventa")


def test_reentrenamiento_multideporte():
    """
    v94 — MLB, tenis y NBA se reentrenan solos.

    El workflow diario sólo hacía `league_engine --build`, que es fútbol. Los
    otros tres motores se reentrenaban a mano y sus modelos llevaban 5-7 días
    de retraso: el sistema predecía la MLB de agosto con el estado de julio.
    """
    wf = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    for mod in ('engines.mlb_engine', 'engines.tennis_engine',
                'engines.nba_engine'):
        check(mod in wf, f"el workflow reentrena {mod}")
    check('atp wta' in wf,
          "y el tenis reentrena LOS DOS circuitos")
    # mismo blindaje que el fútbol: no se commitea un modelo que no carga
    check('no carga tras reentrenar' in wf,
          "con verificación de que el modelo vuelve a abrir")
    check('git' in wf and 'checkout' in wf,
          "y restauración del anterior si no abre")


def test_pick_por_probabilidad_calibrada():
    """
    v93 — el Pick del Día es el MÁS PROBABLE DE ACERTAR, no el de más EV.

    Medido sobre los primeros 142 picks liquidados en producción, la brecha
    entre lo prometido y lo que pasa depende del mercado y es enorme:
    Goles promete 69,7 % y acierta 51,7 %; BTTS promete 69,7 % y acierta
    50,0 %; el Ganador de tenis promete 77,2 % y acierta 70,7 %. Ordenar por
    la probabilidad del modelo ponía arriba justo los mercados que peor
    cumplen.
    """
    import alpha_finder as af

    # un BTTS que promete más que un 1X2 pero acierta mucho menos
    picks = [
        {'partido': 'A vs B', 'mercado': 'BTTS',
         'apuesta': 'Ambos marcan: Sí', 'prob': 0.84, 'ev': 0.05, 'cuota': 1.9},
        {'partido': 'C vs D', 'mercado': '1X2',
         'apuesta': 'Gana C', 'prob': 0.82, 'ev': 0.04, 'cuota': 1.7},
    ]
    p_btts = af.prob_calibrada(picks[0])
    check(p_btts < 0.84,
          f"la probabilidad del BTTS se corrige a la baja ({p_btts:.3f} < 0,84)")
    elegido = af.pick_del_dia(picks)
    check(elegido is not None, "hay Pick del Día con estos dos candidatos")
    if elegido:
        check(elegido['mercado'] == '1X2',
              f"gana el mercado que MÁS ACIERTA, no el que más promete "
              f"(salió {elegido['mercado']})")
        check(elegido.get('prob_calibrada') is not None,
              "el pick viaja con su probabilidad calibrada")

    # sin medición para ese mercado, no se inventa una corrección
    p = af.prob_calibrada({'mercado': '__mercado_inexistente__', 'prob': 0.7})
    check(abs(p - 0.7) < 1e-9,
          "un mercado sin medición conserva la probabilidad del modelo")


def test_recalibracion_automatica():
    """
    v93 — las calibraciones se regeneran solas.

    El workflow diario reentrenaba los modelos de fútbol pero NINGUNA de sus
    calibraciones: `pick_ledger_total.csv` (5 días), `calibracion_confianza`
    (3), `umbrales_capa1` (6), `edge_map` (11) no los tocaba nadie. La
    inconsistencia era peor que la antigüedad: se corregía el modelo de hoy
    con la huella de un modelo que ya no existe.
    """
    import os
    check(os.path.exists('recalibrar_todo.py'),
          "existe la cadena de recalibración")
    import recalibrar_todo
    nombres = [n for n, _ in recalibrar_todo.PASOS]
    check(len(nombres) >= 6,
          f"la cadena cubre los {len(nombres)} artefactos que cuelgan del ledger")
    check('ledger' in nombres[0].lower(),
          "y empieza por el ledger, del que dependen todos los demás")

    wf = '.github/workflows/recalibrar.yml'
    check(os.path.exists(wf), "hay un workflow que la ejecuta")
    if os.path.exists(wf):
        src = open(wf, encoding='utf-8').read()
        check('recalibrar_todo.py' in src, "y llama a la cadena completa")
        check('schedule' in src and 'cron' in src,
              "de forma programada, no sólo a mano")


def test_circuito_de_liquidacion():
    """
    v92 — el circuito de retroalimentación está CONECTADO y el ROI no miente.

    Dos fallos que convivían desde la v32:

    1. `rendimiento_real.liquidar()` no tenía UN SOLO llamador. El sistema
       registraba los picks de cada día y nunca los resolvía — 315 registrados,
       0 liquidados —, así que el panel de rendimiento real llevaba versiones
       vacío y no había forma de saber si el edge se cobraba.
    2. `resumen()` hacía `df['cuota'].fillna(0)`, y los picks de Capa 2 no
       tienen cuota por definición: un acierto de Capa 2 puntuaba 1·(0−1) = −1,
       o sea un acierto contado como pérdida total. Al conectar la liquidación,
       el panel mostró −62,93 % de ROI con 47,4 % de acierto: imposible de
       conciliar, y la señal de que el roto era el cálculo.
    """
    import liquidador

    # el ROI no puede castigar a una apuesta sin precio
    import inspect
    src = inspect.getsource(__import__('rendimiento_real').resumen)
    # se mira el CÓDIGO, no los comentarios: el comentario cita `fillna(0)`
    # a propósito, para explicar qué se rompía
    codigo = [l for l in src.splitlines() if not l.lstrip().startswith('#')]
    check(not [l for l in codigo if 'fillna(0)' in l],
          "el ROI ya no rellena con 0 las cuotas ausentes")
    check(any('notna()' in l for l in codigo),
          "y calcula el ROI sólo sobre los picks con cuota real")

    # la resolución de mercados, contra marcadores conocidos
    r = liquidador.resolver
    check(r('1X2', 'Gana Boca', 'Boca', 'River', 2, 1) is True,
          "1X2: gana el local con 2-1")
    check(r('1X2', 'Gana River', 'Boca', 'River', 2, 1) is False,
          "1X2: el visitante pierde ese mismo partido")
    check(r('1X2', 'Empate', 'Boca', 'River', 1, 1) is True, "1X2: empate")
    check(r('Goles', 'Más de 2.5', 'A', 'B', 2, 1) is True, "Goles: 3 > 2.5")
    check(r('Goles', 'Menos de 2.5', 'A', 'B', 2, 1) is False, "Goles: 3 no es < 2.5")
    check(r('BTTS', 'Ambos marcan: Sí', 'A', 'B', 1, 2) is True, "BTTS sí")
    check(r('BTTS', 'Ambos marcan: No', 'A', 'B', 1, 0) is True, "BTTS no")
    check(r('Hándicap', 'B +1.5', 'A', 'B', 2, 1) is True,
          "hándicap: el visitante con +1.5 cubre perdiendo por 1")
    check(r('Hándicap', 'A −1.5', 'A', 'B', 2, 1) is False,
          "hándicap: el local con −1.5 NO cubre ganando por 1")
    check(r('Hándicap', 'A −1.5', 'A', 'B', 3, 1) is True,
          "y sí cubre ganando por 2")
    check(r('Mercado raro', 'lo que sea', 'A', 'B', 1, 0) is None,
          "un mercado que no se sabe resolver devuelve None, no se inventa")

    # y el workflow tiene que ejecutarlo, o el circuito seguiría abierto
    wf = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    check('liquidador.py' in wf,
          "el workflow diario ejecuta el liquidador")
    # el histórico tiene que persistir: la base está en .gitignore
    import rendimiento_real as rr
    check(hasattr(rr, 'exportar') and hasattr(rr, 'importar'),
          "los picks se persisten a CSV (la base es efímera en cloud)")


def test_un_solo_reloj():
    """
    v91 — TODO el barrido usa el MISMO reloj (UTC).

    Convivían `pd.Timestamp.today()` (local) y `utcnow()` según el punto del
    código, y las fechas de los fixtures vienen de ESPN en UTC. En Streamlit
    Cloud el servidor va en UTC y coincidían, así que la mezcla era invisible;
    en cualquier máquina de América el barrido pedía los fixtures del día y
    después los descartaba todos por un desfase de 24 h — «partidos evaluados:
    0» con 12 partidos disponibles. Este test fija el contrato.
    """
    import pandas as pd
    import alpha_finder as af

    hoy = af.hoy_utc()
    check(hoy == pd.Timestamp.utcnow().tz_localize(None).normalize(),
          "hoy_utc() es la medianoche UTC de hoy")
    check(hoy.hour == 0 and hoy.tzinfo is None,
          "normalizado y sin zona (comparable con las fechas de los fixtures)")

    # Ningún punto del barrido puede volver a LLAMAR al reloj local. Se busca
    # la llamada en el árbol, no la cadena en el texto: los comentarios y
    # docstrings nombran `Timestamp.today()` justamente para explicar por qué
    # ya no se usa.
    import ast
    src = open('alpha_finder.py', encoding='utf-8').read()
    llamadas = [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'today']
    check(not llamadas,
          f"alpha_finder no llama al reloj local en ningún sitio "
          f"({len(llamadas)} llamadas a .today())")

    # v102 — el rango lo construye ahora `_fixtures_de_codigo`, porque
    # `fixtures_liga` pasó a orquestar varios códigos de ESPN y varios
    # horizontes. El invariante es el mismo y aquí se comprueba donde vive,
    # en vez de fiarlo a que dos funciones sigan pegadas en el fichero.
    fsrc = open('fixtures_espn.py', encoding='utf-8').read()
    cuerpo = fsrc.split('def _fixtures_de_codigo')[1][:1500]
    # v110 — se aceptan las DOS formas de pedir la hora UTC.
    #
    # `Timestamp.utcnow()` quedó deprecado en pandas 4 («use Timestamp.now('UTC')
    # instead») y el aviso salía en el log de producción, así que se sustituyó.
    # Lo que este test vigila es el INVARIANTE —que el rango se ancle en UTC y
    # no en el reloj local—, no cómo se escribe la llamada; buscar sólo el
    # literal viejo convertía una limpieza de deprecación en un fallo rojo.
    check("utcnow" in cuerpo or "now('UTC')" in cuerpo,
          "el rango de fechas se ancla en UTC (el reloj de ESPN)")
    # y que nadie haya vuelto a colar el reloj local en el módulo
    import ast as _ast
    locales = [n for n in _ast.walk(_ast.parse(fsrc))
               if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
               and n.func.attr == 'today']
    check(not locales,
          f"fixtures_espn no usa el reloj local ({len(locales)} .today())")


def test_totales_conservan_su_casa():
    """
    v90 — los totales tienen que llegar con la casa que puso cada precio.

    `_totales` era un dict PLANO: el over25 de ESPN y el de Pinnacle iban a la
    misma clave y el segundo pisaba al primero, así que `daily_snapshots` sólo
    podía etiquetarlos como Pinnacle. Consecuencia medida: de 35.606 filas con
    over25 en `historical_odds`, CERO tenían dos casas para el mismo partido,
    y sin dos precios el line shopping sobre Goles no se puede validar nunca.

    Este test fija las dos mitades del contrato: que `totales_por_casa`
    distinga, y que `totales` siga siendo exactamente el dict fusionado de
    antes (nada de lo desplegado puede cambiar de comportamiento).
    """
    try:
        import cuotas_multi as cm
    except Exception as e:
        print(f'AVISO cuotas_multi no disponible ({e}); se omite')
        return
    espn = {'casa': 'DraftKings', 'odd_home': 2.10, 'odd_draw': 3.30,
            'odd_away': 3.50, 'odd_over25': 1.85, 'odd_under25': 1.95}
    c = cm.cuotas_partido('futbol', '__equipo_inexistente_a__',
                          '__equipo_inexistente_b__', odds_espn=espn)
    tpc = c.get('totales_por_casa') or {}
    check('DraftKings' in tpc,
          'el over/under de ESPN se atribuye a su casa, no se pierde')
    check((tpc.get('DraftKings') or {}).get('over25') == 1.85,
          'y conserva el precio exacto')
    check((c.get('totales') or {}).get('over25') == 1.85,
          '`totales` sigue existiendo con la misma forma de siempre')

    # y que daily_snapshots lo use: sin esto el histórico no acumularía nada
    import inspect
    import daily_snapshots
    src = inspect.getsource(daily_snapshots.capturar)
    check('totales_por_casa' in src,
          'daily_snapshots guarda los totales de CADA casa')
    check("if casa == 'Pinnacle':" not in src,
          'y ya no los reserva solo a Pinnacle')


def test_techo_por_liga_estable():
    """
    v90 — el techo de acierto por liga sólo vale si es ESTABLE.

    La v38 midió que el ROI por liga no es estacionario y por eso se rechazó
    elegir ligas por rentabilidad pasada. El acierto es otra cosa (refleja el
    equilibrio competitivo), pero eso hay que comprobarlo, no suponerlo: el
    fichero sólo se publica si la correlación entre las dos mitades del ledger
    supera el umbral. Este test verifica que lo publicado cumple su propia
    condición y que la consulta degrada limpia con una liga desconocida.
    """
    try:
        import precision_ligas as pl
    except Exception as e:
        print(f'AVISO precision_ligas no disponible ({e}); se omite')
        return
    t = pl._tabla()
    if not t:
        print('AVISO precision_ligas.json no generado todavía; se omite')
        return
    check(t.get('estable') is True,
          'el fichero publicado declara que el techo es estable')
    check(t.get('correlacion_mitades', 0) >= pl.MIN_CORRELACION,
          f'y su correlación entre mitades ({t.get("correlacion_mitades")}) '
          f'supera el umbral {pl.MIN_CORRELACION}')
    check(pl.techo('__liga_que_no_existe__') is None,
          'una liga sin medir devuelve None, no un número inventado')
    check(pl.etiqueta('__liga_que_no_existe__') == '',
          'y su etiqueta es vacía (la UI no enseña nada)')
    arg = pl.techo('argentina')
    if arg:
        check(0.30 < arg['mercado'] < 0.75,
              'el techo medido está en un rango plausible para un 1X2')


# ---------------------------------------------------------------------------
# v97 — ITF en vivo, KBO y Leagues Cup
# ---------------------------------------------------------------------------
def test_itf_fuente_viva():
    """
    La fuente viva de ITF existe, y no puede volver a colar una fuga de
    posición como la de la v96.
    """
    import acumular_itf

    # 1) La guardia anti-fuga corta ANTES de escribir.
    filas = [{'fecha': '2026-08-04', 'circuito': 'itf_masculino', 'nivel': 'M15',
              'torneo': 'T', 'superficie': 'Hard',
              'jugador_1': f'A{i}', 'jugador_2': f'B{i}', 'ganador': f'A{i}',
              'sets_1': 2, 'sets_2': 0, 'juegos_totales': 12,
              'cuota_1': None, 'cuota_2': None}
             for i in range(acumular_itf.MUESTRA_MINIMA + 20)]
    check(abs(acumular_itf.reparto_ganadores(filas) - 1.0) < 1e-9,
          "el medidor detecta el 100 % de ganadores en la primera columna")

    import tempfile
    import unittest.mock as _mock
    with _mock.patch.object(acumular_itf, 'descargar', lambda: filas):
        ruta = os.path.join(tempfile.gettempdir(), '_test_itf_fuga.csv')
        if os.path.exists(ruta):
            os.remove(ruta)
        try:
            acumular_itf.acumular(ruta=ruta)
            salto = False
        except ValueError:
            salto = True
        check(salto, "un reparto de ganadores imposible LANZA ValueError")
        check(not os.path.exists(ruta),
              "y no llega a escribir el fichero contaminado")

    # 2) Lo ya acumulado es coherente: el marcador viaja con la columna.
    if os.path.exists(acumular_itf.ARCHIVO):
        for circuito in ('atp', 'wta'):
            df = acumular_itf.cargar(circuito)
            if df.empty:
                continue
            sets = df['Score'].str.split('-', expand=True).astype(int)
            gana_p1 = (df['Winner'] == df['Player_1']).to_numpy()
            check(bool(((sets[0] > sets[1]).to_numpy() == gana_p1).all()),
                  f"ITF vivo {circuito}: el marcador concuerda con el ganador "
                  f"en los {len(df)} partidos")
            frac = float(gana_p1.mean())
            check(0.35 <= frac <= 0.65,
                  f"ITF vivo {circuito}: el ganador se reparte entre columnas "
                  f"({frac:.1%}), no siempre en la misma")

    # 3) TennisAbstract quedó descartado por robots.txt, no por falta de dato.
    #    Que no se cuele una petición a las rutas prohibidas — comprobado sobre
    #    el AST y NO sobre el texto, porque el docstring de `acumular_itf` cita
    #    esas rutas precisamente para explicar por qué no se usan. Es la misma
    #    técnica del test de jerga de la v95: las cadenas VIVAS son las que
    #    importan, los comentarios y docstrings pueden decir lo que haga falta.
    #
    # v98: `tenis_saque.py` VUELVE a la lista. En la v97 quedó fuera con el
    # hallazgo anotado (pedía `/jsplayers/curr_rank_*.js`, que está en el
    # Disallow); ahora su ranking sale del histórico unificado del propio
    # proyecto y la petición prohibida ya no existe. Las páginas de jugador
    # (`/cgi-bin/player-classic.cgi`) sí están permitidas y se siguen usando.
    import ast
    PROHIBIDAS = ('/jsmatches/', '/jsplayers/', '/jsfrags/')
    for mod in ('acumular_itf.py', 'tenis_fuentes.py', 'tenis_saque.py'):
        if not os.path.exists(mod):
            continue
        arbol = ast.parse(open(mod, encoding='utf-8').read())
        docstrings = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                d = ast.get_docstring(nodo, clean=False)
                if d:
                    docstrings.add(d)
        vivas = [n.value for n in ast.walk(arbol)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and n.value not in docstrings]
        malas = [s for s in vivas if any(p in s for p in PROHIBIDAS)]
        check(not malas,
              f"{mod} no pide las rutas que tennisabstract prohíbe en "
              f"robots.txt ({malas[:2]})")


def test_kbo_integrada():
    """La KBO tiene datos, modelo y no se mezcla con la MLB."""
    import config

    check('KBO' in config.UMBRALES_DEPORTE,
          "la KBO declara su umbral de confianza (no hereda uno escondido)")

    import kbo_naver
    check(len(kbo_naver.CODIGO_A_EQUIPO) == 10,
          f"la KBO mapea sus 10 equipos ({len(kbo_naver.CODIGO_A_EQUIPO)})")
    check(len(set(kbo_naver.CODIGO_A_EQUIPO.values())) == 10,
          "y ningún código apunta al mismo equipo que otro")

    if os.path.exists(kbo_naver.SALIDA):
        import pandas as _pd
        df = _pd.read_csv(kbo_naver.SALIDA, parse_dates=['date'])
        check(len(df) > 10000,
              f"histórico de KBO con volumen ({len(df)} juegos)")
        dec = df[df.home_runs != df.away_runs]
        pct = float((dec.home_runs > dec.away_runs).mean())
        check(kbo_naver.LOCAL_MIN <= pct <= kbo_naver.LOCAL_MAX,
              f"local y visitante NO están cruzados (el local gana {pct:.1%})")
        check(df['date'].max() >= _pd.Timestamp('2026-01-01'),
              f"la fuente llega a la temporada en curso "
              f"(último {df['date'].max().date()})")

    # El filtro anti-KBO de la v88 en la MLB sigue puesto: son ligas distintas
    # y el edge de la MLB se midió sólo con partidos de MLB.
    from engines.mlb_engine import es_partido_mlb
    from engines.kbo_engine import es_partido_kbo
    check(not es_partido_mlb('LG Twins', 'SSG Landers'),
          "un partido de KBO NO se cuela como MLB")
    check(es_partido_kbo('LG Twins', 'SSG Landers'),
          "y el motor de KBO sí lo reconoce")
    check(not es_partido_kbo('New York Yankees', 'Boston Red Sox'),
          "y un partido de MLB no se cuela como KBO")

    # El clasificador es binario: un empate no puede entrar como «no gana el
    # local», que es lo que pasaría si no se filtrasen.
    import pandas as _pd
    from engines.kbo_engine import KBOEngine
    demo = _pd.DataFrame({
        'date': _pd.to_datetime(['2025-04-0%d' % i for i in range(1, 9)] * 3),
        'home_team': ['LG Twins', 'KT Wiz'] * 12,
        'away_team': ['NC Dinos', 'Doosan Bears'] * 12,
        'home_runs': [3, 3] * 12, 'away_runs': [3, 1] * 12,
        'home_pitcher': ['x'] * 24, 'away_pitcher': ['y'] * 24})
    _X, _y, _t, _f, _e = KBOEngine._dataset(demo)
    check(len(_X) == 0 or set(_y.tolist()) <= {0, 1},
          "el dataset de KBO no etiqueta empates como derrota local")


def test_leagues_cup_integrada():
    """La Leagues Cup está en el catálogo, con nombres correctos."""
    import config
    check('leagues_cup' in config.LEAGUES,
          "la Leagues Cup está en el catálogo de competiciones")
    check(config.LEAGUES['leagues_cup'].get('capa') == 2,
          "y declarada en Capa 2 (informativa): ningún modelo batió al ELO")

    import fixtures_espn
    check(fixtures_espn.ESPN_CODIGOS.get('leagues_cup') == 'concacaf.leagues.cup',
          "tiene código ESPN (sin él nunca llegaría a Apuestas del Día)")

    import leagues_cup
    # EL fallo que el emparejamiento difuso cometió: dos clubes de Nueva York.
    check(leagues_cup.ALIAS.get('Red Bull New York') == 'New York Red Bulls',
          "«Red Bull New York» NO se confunde con «New York City»")
    check(leagues_cup.ALIAS.get('New York City FC') == 'New York City',
          "y «New York City FC» sigue siendo el suyo")
    check(len(set(leagues_cup.ALIAS.values())) == len(leagues_cup.ALIAS),
          "ningún par de equipos de la Leagues Cup cae en el mismo club")

    # Los alias tienen que estar TAMBIÉN en el fichero global, que es lo que
    # usa `alpha_finder` al resolver los fixtures de ESPN.
    import json as _json
    if os.path.exists('alias_manuales.json'):
        alias = _json.load(open('alias_manuales.json', encoding='utf-8'))
        faltan = [k for k, v in leagues_cup.ALIAS.items()
                  if alias.get(k) not in (v, None) or k not in alias]
        check(not faltan,
              f"los alias de Leagues Cup están en alias_manuales.json ({faltan[:4]})")

    if os.path.exists('historico_leagues_cup.csv'):
        import pandas as _pd
        df = _pd.read_csv('historico_leagues_cup.csv')
        check(len(df) > 5000,
              f"su histórico es el AGRUPADO con MLS y Liga MX ({len(df)} "
              f"partidos; la competición sola son 230)")

    # Los goleadores van por la MISMA tabla, sin respaldo difuso. ESPN sólo
    # publica los ~36 participantes de la edición en curso, y cuando el equipo
    # buscado no está el emparejamiento difuso no calla: elige el más parecido.
    # Medido: «New York Red Bulls» acababa en «New York City FC» y los
    # goleadores habrían salido de la plantilla equivocada, sin ningún error.
    try:
        import goleadores
        cat = {e['nombre']: e['id'] for e in goleadores.equipos_liga('leagues_cup')}
    except Exception:
        cat = {}
    if cat:
        nyc = cat.get('New York City FC')
        rb = goleadores._buscar_team_id('leagues_cup', 'New York Red Bulls')
        check(rb is None or rb != nyc,
              "los goleadores de «New York Red Bulls» NO salen del New York City")
        malos = []
        for espn, canon in leagues_cup.ALIAS.items():
            tid = goleadores._buscar_team_id('leagues_cup', canon)
            if tid is not None and tid != cat.get(espn):
                malos.append((canon, espn))
        check(not malos,
              f"ningún equipo de Leagues Cup resuelve a la plantilla de otro "
              f"({malos[:3]})")


# ===========================================================================
# v106
# ===========================================================================
def test_handicap_con_push():
    """
    v106 — el hándicap deja de regalarle el push al lado contrario.

    El fallo: `alpha_finder` aceptaba cualquier línea múltiplo de 0,5 (la
    condición dejaba pasar también las ENTERAS, pese al comentario «líneas .5
    → sin push») y calculaba el lado visitante como `1 − P(el local cubre)`.
    Con línea entera ese complemento incluye `margen == −L`, que es DEVOLUCIÓN,
    no victoria. Medido sobre la matriz de un favorito típico: el visitante
    salía al 71,2 % cuando su probabilidad real de cobrar es 61,7 %, porque el
    25 % de push se le contaba como acierto. Con esa cifra el EV salía positivo
    casi siempre — es «el hándicap me falla constantemente».

    No se veía en la medición porque `build_ledger_handicap.py` sólo medía
    líneas .5, que son justo las que no tienen push.
    """
    import numpy as np
    import handicap as h

    # distribución de margen sencilla y exacta, para que el test no dependa
    # de ningún modelo entrenado
    dist = {2: 0.20, 1: 0.25, 0: 0.25, -1: 0.20, -2: 0.10}

    # --- línea ENTERA: el push existe y no es de nadie ---------------------
    d = h.desglose(dist, -1.0)          # el local da 1
    check(abs(d['gana'] - 0.20) < 1e-9, "local −1 gana sólo si gana por 2+")
    check(abs(d['push'] - 0.25) < 1e-9, "gana por 1 exacto es PUSH, no derrota")
    check(abs(d['gana'] + d['pierde'] + d['push'] - 1) < 1e-9,
          "gana + pierde + push suma 1")
    p = h.probabilidad(dist, -1.0)
    check(abs(p - 0.20 / 0.75) < 1e-9,
          f"la probabilidad es CONDICIONAL a que se resuelva ({p:.4f})")

    # el lado contrario no puede llevarse el push
    lados = {f['lado']: f for f in
             _evaluar_desde_dist(h, dist, -1.0, 1.90, 1.95)}
    check(abs(lados['away']['prob'] - 0.55 / 0.75) < 1e-9,
          "el visitante +1 NO cobra el push")
    # así lo calculaba la v65: `1 − P(el local cubre)`, que se traga el push
    viejo = 1 - sum(p for m, p in dist.items() if m > 1)
    check(lados['away']['prob'] < viejo - 0.05,
          f"el método viejo daba {viejo:.4f} y el real es "
          f"{lados['away']['prob']:.4f}: {(viejo - lados['away']['prob'])*100:.1f} "
          f"puntos de inflación, justo la masa del push")
    check(abs(lados['home']['gana'] - lados['away']['pierde']) < 1e-9,
          "lo que gana un lado es exactamente lo que pierde el otro")
    check(abs(lados['home']['push'] - lados['away']['push']) < 1e-9,
          "el push es el mismo para los dos lados")

    # --- líneas de CUARTO: antes se descartaban enteras ---------------------
    check(set(h.partes_de_linea(-0.75)) == {(-0.5, 0.5), (-1.0, 0.5)},
          "−0,75 se juega mitad en −0,5 y mitad en −1,0")
    check(h.desglose(dist, -0.75) is not None,
          "una línea de cuarto ya produce mercado (Pinnacle publica muchas)")
    check(h.partes_de_linea(-0.3) is None,
          "una línea fuera de la rejilla de 0,25 no se inventa")

    # --- EV: con push, `cuota·prob − 1` exagera ----------------------------
    ev = h.ev(dist, -1.0, 2.0)
    check(abs(ev - (0.20 * 1.0 - 0.55)) < 1e-9,
          f"EV = gana·(cuota−1) − pierde ({ev:+.4f})")
    ingenuo = 2.0 * p - 1
    check(abs(ev - 0.75 * ingenuo) < 1e-9,
          "el EV ingenuo sobreestima exactamente en 1/(gana+pierde)")

    # --- anclaje al mercado: el hándicap hereda el encogimiento del 1X2 ----
    d2 = h.reponderar_a_1x2(dist, {'home': 0.30, 'draw': 0.25, 'away': 0.45})
    check(abs(sum(p_ for k, p_ in d2.items() if k > 0) - 0.30) < 1e-9,
          "la masa de «gana el local» queda en la probabilidad ya corregida")
    check(abs(sum(d2.values()) - 1) < 1e-9, "y la distribución sigue sumando 1")
    p_ancl = h.probabilidad(d2, -0.5)
    check(p_ancl < h.probabilidad(dist, -0.5),
          "anclar a un 1X2 menor baja el hándicap del local (era el sesgo "
          "de selección que el 1X2 sí corregía desde la v71)")

    # --- y producción usa este módulo, no su propia cuenta ------------------
    fuente = open('alpha_finder.py', encoding='utf-8').read()
    check('import handicap' in fuente,
          "alpha_finder evalúa el hándicap con el módulo medido")
    check('1 - p_home_cubre' not in fuente,
          "el complemento que regalaba el push ya no existe en el barrido")

    # --- el ledger mide lo que producción publica --------------------------
    import build_ledger_handicap as blh
    check(-1.0 in blh.LINEAS and -0.75 in blh.LINEAS,
          "el ledger mide también líneas enteras y de cuarto (antes sólo .5)")
    import pandas as _pd
    if os.path.exists('pick_ledger_handicap.csv'):
        led = _pd.read_csv('pick_ledger_handicap.csv', nrows=5)
        check(any(c.startswith('res_ah_') for c in led.columns),
              "el ledger guarda la fracción de importe resuelta (sin ella, "
              "una línea de cuarto no es comparable con su probabilidad)")

    # --- y el LIQUIDADOR resuelve lo que el barrido publica -----------------
    #
    # Con la v106 el barrido emite líneas enteras y de cuarto de verdad. Si el
    # liquidador no supiera resolverlas, sus picks se acumularían pendientes
    # para siempre y el ROI del hándicap no se mediría nunca — que es el mismo
    # agujero que la v92 encontró con los picks sin liquidar.
    from liquidador import resolver
    H, A = 'Toluca', 'Atlante'
    casos = [
        (f'{H} −1.5', 3, 1, True,  'la .5 de siempre no cambia'),
        (f'{H} −1',   3, 1, True,  'entera: gana por 2, cubre'),
        (f'{H} −1',   2, 1, None,  'entera: gana por 1 EXACTO es PUSH y NO se '
                                   'liquida (contarlo de cualquier lado '
                                   'contamina el ROI para siempre)'),
        (f'{A} +1',   2, 1, None,  'y el push tampoco se liquida por el otro '
                                   'lado'),
        (f'{H} 0',    2, 1, True,  'línea 0 («empate no cuenta»): se etiqueta '
                                   'SIN signo y aun así se parsea'),
        (f'{H} 0',    1, 1, None,  'y su empate es devolución'),
        (f'{H} −0.75', 2, 1, True, 'cuarto: media gana y media empata → cobra'),
        (f'{H} −1.25', 2, 1, False, 'cuarto: media empata y media pierde'),
    ]
    for apuesta, gl, gv, esperado, porque in casos:
        r = resolver('Hándicap', apuesta, H, A, gl, gv)
        check(r is esperado if esperado is None else r == esperado,
              f"liquidación de «{apuesta}» {gl}-{gv} = {r} — {porque}")

    # --- la calibración no puede volver a contar un push como acierto ------
    src_cal = open('calibracion_confianza.py', encoding='utf-8').read()
    i = src_cal.find('LEDGER_HANDICAP)')
    bloque = src_cal[i:i + 1400] if i > 0 else ''
    check('notna()' in bloque,
          "la calibración descarta los push (np.nan como bool es True: sin "
          "esto los 10.966 push de la línea −1 entrarían como aciertos)")


def _evaluar_desde_dist(h, dist, linea, ch, ca):
    """Aplica `handicap.evaluar` a una distribución de margen ya dada, sin
    pasar por una matriz de marcadores (el test no necesita un modelo)."""
    dist_v = {-d: p for d, p in dist.items()}
    fuera = []
    for lado, dl, L, c in (('home', dist, linea, ch),
                           ('away', dist_v, -linea, ca)):
        des = h.desglose(dl, L)
        fuera.append({'lado': lado, 'prob': h.probabilidad(dl, L),
                      'gana': des['gana'], 'pierde': des['pierde'],
                      'push': des['push'], 'ev': h.ev(dl, L, c)})
    return fuera


def test_hora_cdmx():
    """
    v106 — la hora del partido, en hora de Ciudad de México.

    El usuario la pidió para decidir «casi en vivo, antes de que empiece». El
    dato ya se guardaba (`inicio`, en UTC) y no llegaba a la pantalla.

    Lo que este test fija es sobre todo lo que NO puede pasar: que la
    conversión se cuele en la lógica. El proyecto razona en UTC de punta a
    punta (`test_un_solo_reloj`) porque mezclar relojes ya costó un día entero
    de partidos descartados en la v91.
    """
    import horario

    check(horario.partes('2026-08-08 23:30:00') == ('2026-08-08', '17:30'),
          "23:30 UTC son las 17:30 en CDMX")
    check(horario.partes('2026-08-09 01:00:00') == ('2026-08-08', '19:00'),
          "la FECHA local puede no ser la UTC: 01:00 del sábado en UTC es "
          "viernes por la noche en México")
    check(horario.partes('2026-08-08T19:00:00Z') == ('2026-08-08', '13:00'),
          "lee el ISO con zona")
    for malo in (None, '', 'basura', '1970-01-01 00:00:00'):
        check(horario.partes(malo) is None,
              f"no inventa hora con {malo!r} (mejor sin hora que una falsa)")
    check(horario.etiqueta(None) == '',
          "sin hora devuelve cadena vacía, para poder concatenar sin comprobar")

    # `anotar` NO puede tocar los campos con los que se compara internamente
    p = {'fecha': '2026-08-09', 'inicio': '2026-08-09 01:00:00'}
    horario.anotar(p)
    check(p['fecha'] == '2026-08-09',
          "anotar() deja intacta la fecha UTC que usa la lógica")
    check(p['fecha_cdmx'] == '2026-08-08' and p['hora_cdmx'] == '19:00',
          "y añade la fecha y hora locales aparte")

    # el reloj sigue siendo uno solo: nadie razona en hora local
    import ast
    src = open('alpha_finder.py', encoding='utf-8').read()
    llamadas = [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'today']
    check(not llamadas,
          "añadir la hora de CDMX no metió el reloj local en el barrido")
    check('horario.anotar' in src or 'horario' in src,
          "el barrido anota la hora local en el borde de salida")

    # y la zona sale de la base de datos de zonas, no de un −6 escrito a mano
    check('America/Mexico_City' in open('horario.py', encoding='utf-8').read(),
          "la zona es America/Mexico_City (no un desfase fijo)")
    req = open('requirements.txt', encoding='utf-8').read()
    check('tzdata' in req,
          "`tzdata` está declarada: en Windows `zoneinfo` no tiene base propia")

    # la interfaz y el mensaje de Telegram la enseñan
    dash = open('dashboard_ui.py', encoding='utf-8').read()
    check('_horario' in dash, "la interfaz usa el módulo de horario")
    tg = open('bot_telegram.py', encoding='utf-8').read()
    check('hora_cdmx' in tg, "el mensaje de Telegram lleva la hora")


def test_ev_automatico_en_todos_los_deportes():
    """
    v106 — el EV+ automático deja de ser exclusivo de la MLB.

    El usuario: «en deportes que no son fútbol no tienes la opción de EV+
    automático, y ese me ayuda mucho». Era cierto a medias y por eso costaba
    verlo: `alpha_finder` YA calculaba picks con cuota y EV de MLB, NBA, KBO y
    tenis, pero sólo la vista de MLB los enseñaba; para los otros tres había
    que salir a la pantalla general y buscar entre todos los deportes.
    """
    import alpha_finder as af

    for f in ('_picks_mlb', '_picks_nba', '_picks_kbo', '_picks_tenis'):
        check(hasattr(af, f), f"existe el barrido de {f}")

    dash = open('dashboard_ui.py', encoding='utf-8').read()
    check('def render_ev_automatico' in dash,
          "hay UN panel de EV+ común a todos los deportes")
    for dep, fn in (('NBA', '_picks_nba'), ('KBO', '_picks_kbo'),
                    ('Tenis', '_picks_tenis')):
        check(f"'{dep}', _af.{fn}" in dash,
              f"{dep} tiene su EV+ automático conectado a su barrido")
    check("'MLB', eng.apuestas_dia" in dash,
          "la MLB usa el mismo panel (y así gana la Capa 2 que antes tiraba)")

    # el panel tiene que enseñar la hora, que es para lo que sirve «casi en vivo»
    i = dash.find('def render_ev_automatico')
    cuerpo = dash[i:i + 6000]
    check('_horario' in cuerpo, "el panel enseña la hora del partido en CDMX")
    check('falta_para' in cuerpo, "y cuánto falta para que empiece")

    # -----------------------------------------------------------------------
    # LA CACHÉ TIENE QUE DISTINGUIR DEPORTES, Y ES UN FALLO SILENCIOSO.
    #
    # El panel es UNA función usada por los cuatro deportes, así que su función
    # cacheada tiene el mismo nombre en las cuatro llamadas y sólo el argumento
    # las separa. Streamlit **excluye del hash todo parámetro que empiece por
    # guion bajo** (su convención para colar objetos no hasheables), de modo
    # que llamarlo `_dep` haría que las cuatro compartieran una única entrada:
    # la vista de NBA enseñaría los picks de la MLB, sin error ni aviso.
    # -----------------------------------------------------------------------
    import ast
    fn = next(n for n in ast.walk(ast.parse(dash))
              if isinstance(n, ast.FunctionDef) and n.name == 'render_ev_automatico')
    interna = next((n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef)
                    and n.name != 'render_ev_automatico'
                    and any('cache_data' in ast.dump(d) for d in n.decorator_list)),
                   None)
    check(interna is not None, "el panel cachea el barrido de cada deporte")
    if interna is not None:
        args = [a.arg for a in interna.args.args]
        check(len(args) >= 1,
              f"la función cacheada recibe el deporte como argumento ({args})")
        check(all(not a.startswith('_') for a in args),
              f"y NINGÚN argumento empieza por guion bajo — Streamlit no los "
              f"hashea y los cuatro deportes compartirían caché ({args})")


def test_unibet_quinta_casa():
    """
    v111 — Unibet (Kambi) entra al tablón, y sólo Unibet.

    El line shopping es la única vía del proyecto con ROI positivo y robusto
    (+11,49 % en juicio, p5 +1,73 %) y vive de la dispersión entre casas. De
    quince candidatas sondeadas, Kambi fue la única con JSON abierto y catálogo
    real: 270 partidos de fútbol (ya sin esports), 73 de tenis, 15 de MLB y 16
    de NBA.

    Medido al integrarla: sobre 33 partidos con dos o más casas, **Unibet da el
    mejor precio en 17** con una ventaja media del **+3,64 %** sobre la segunda
    mejor (mediana +1,69 %, máximo +11,43 %).

    LO QUE ESTE TEST PROTEGE DE VERDAD
    ----------------------------------
    Kambi es una plataforma compartida: Unibet, 888sport, LeoVegas, Rizk,
    Casumo y ATG cuelgan del MISMO motor. Comprobado sobre los 272 partidos que
    `ub` y `atg` publican a la vez: **248 idénticos** y 24 con diferencias de
    céntimos (ruido de captura). Añadir una segunda marca de Kambi fabricaría
    dispersión falsa — picks de line shopping sobre un precio que es el mismo.
    Es la trampa del EV+ ilusorio de la v25, y sería invisible.
    """
    import cuotas_multi as cm

    check(hasattr(cm, '_indice_unibet'), "existe el índice de Unibet")
    check('Unibet' in open('cuotas_multi.py', encoding='utf-8').read(),
          "y se registra como casa en `cuotas_partido`")

    src = open('cuotas_multi.py', encoding='utf-8').read()
    # UNA sola marca de Kambi en la URL
    import re
    marcas = set(re.findall(r"offering/v2018/(\w+)/", src))
    check(marcas == {'ub'},
          f"se consulta UNA sola marca de Kambi ({marcas}) — varias fabricarían "
          f"dispersión falsa: 248 de 272 partidos tienen precio idéntico entre "
          f"marcas")
    check('mismo motor' in src.lower() or 'MISMO motor' in src,
          "y queda escrito por qué, para que nadie lo 'mejore' añadiendo marcas")

    # los esports NO pueden entrar al fútbol
    check('esport' in src.lower(),
          "el feed de fútbol de Kambi trae esports y se filtran")
    idx = cm._indice_unibet('futbol')
    if idx:
        sucios = [v for v in idx.values()
                  if any(t in str(v.get('liga', '')).lower()
                         for t in ('esport', 'cyber', 'live arena'))]
        check(not sucios,
              f"ningún esports se cuela como fútbol ({len(sucios)} de "
              f"{len(idx)}) — el emparejado difuso casaría «Barcelona "
              f"(dm1trena)» con el Barcelona de verdad")
        check(len(idx) >= 50,
              f"y el catálogo real es amplio ({len(idx)} partidos)")

    # las cuotas tienen que venir en decimal creíble (Kambi las da en milésimas)
    if idx:
        malas = []
        for v in list(idx.values())[:60]:
            for lado, c in (v.get('cuotas') or {}).items():
                if not (1.0 < float(c) < 200):
                    malas.append((v['home'], lado, c))
        check(not malas,
              f"las cuotas se convierten bien de milésimas a decimal ({malas[:3]})")


def test_sin_bom_en_el_codigo():
    """
    v110 — ningún .py puede empezar con BOM UTF-8.

    Se coló reescribiendo ficheros con `Set-Content -Encoding UTF8` de
    PowerShell 5.1, que añade BOM sin avisar. Lo traicionero es que
    `py_compile` lo acepta —Python trata el BOM como marca de codificación— así
    que la comprobación habitual pasaba en verde mientras seis ficheros
    quedaban con tres bytes de basura al principio.

    Dónde SÍ rompe: en cualquier herramienta que lea el fichero como texto y lo
    parsee por su cuenta. Aquí lo destapó el propio suite, que hace
    `ast.parse(open(...).read())` sobre varios módulos:

        SyntaxError: invalid non-printable character U+FEFF

    Y habría roto igual en producción a la primera que alguien leyera el
    fichero sin `encoding='utf-8-sig'`.
    """
    import glob
    malos = []
    for f in sorted(glob.glob('*.py') + glob.glob('engines/*.py')):
        with open(f, 'rb') as fh:
            if fh.read(3) == b'\xef\xbb\xbf':
                malos.append(f)
    check(not malos, f"ningún fichero .py empieza con BOM UTF-8 ({malos})")

    # y que de verdad se puedan parsear como texto plano, que es lo que
    # `py_compile` NO comprueba
    import ast
    rotos = []
    for f in sorted(glob.glob('*.py') + glob.glob('engines/*.py')):
        try:
            ast.parse(open(f, encoding='utf-8').read())
        except SyntaxError as e:
            rotos.append(f'{f}: {e.msg}')
    check(not rotos, f"todos se parsean leyéndolos como UTF-8 ({rotos[:3]})")


def test_ruido_de_produccion():
    """
    v110 — tres cosas que ensuciaban el log de producción, y una costaba tiempo.

    1. **`goleadores` reintentaba cada 403 en CADA rerun.** ESPN bloquea
       `/teams` y `/roster` desde IPs de centro de datos (mismo caso que la v98
       con el scoreboard de MLB), pero el `except` devolvía la caché vacía sin
       anotar el fallo, así que la siguiente llamada volvía a intentarlo. El log
       traía decenas de líneas idénticas por carga de página y cada una era una
       petición HTTP real esperando su timeout.

    2. **`use_container_width`** queda retirado el 2025-12-31.

    3. **El aviso de ripser** («more columns than rows») salía en cada
       predicción. Es esperado —la nube de un partido tiene más dimensiones que
       puntos— y un aviso que sale siempre y nunca significa nada acaba tapando
       los que sí importan. De hecho es lo que pasaba: los 403 se perdían entre
       ellos.
    """
    import goleadores as g

    check(hasattr(g, 'TTL_FALLO_S') and g.TTL_FALLO_S > 0,
          "goleadores recuerda los fallos durante un rato")
    check(hasattr(g, '_fallo_reciente') and hasattr(g, '_anotar_fallo'),
          "y tiene las dos piezas de la caché negativa")

    src = open('goleadores.py', encoding='utf-8').read()
    check(src.count('_fallo_reciente(cache') >= 2,
          "las DOS rutas que pegan a ESPN la consultan (equipos y roster)")
    check(src.count('_anotar_fallo(cache') >= 2, "y las dos la escriben")
    check('repetido' in src,
          "el aviso se emite una vez por clave; las repeticiones van a debug")

    # el TTL tiene que ser corto: un bloqueo puede ser temporal y no queremos
    # quedarnos sin goleadores un día entero por un 403 de hace un minuto.
    check(60 <= g.TTL_FALLO_S <= 6 * 3600,
          f"el fallo se reintenta en un plazo razonable ({g.TTL_FALLO_S} s)")

    # --- 2. la llamada obsoleta de Streamlit -------------------------------
    #
    # Se excluye ESTE fichero: contiene el literal por necesidad —es lo que
    # busca— y sin la exclusión el test se detecta a sí mismo y falla siempre.
    import glob
    _yo = os.path.basename(__file__)
    malos = [f for f in glob.glob('*.py') + glob.glob('engines/*.py')
             if os.path.basename(f) != _yo
             and 'use_container' + '_width' in open(f, encoding='utf-8').read()]
    check(not malos,
          f"nadie usa `use_container_width`, que Streamlit retira el "
          f"2025-12-31 ({malos})")

    # --- 3. el aviso de ripser ---------------------------------------------
    pa = open('prediction_api.py', encoding='utf-8').read()
    i = pa.find('def _entropias')
    cuerpo = pa[i:i + 1800]
    check('filterwarnings' in cuerpo, "el aviso de ripser se silencia")
    check('more columns than rows' in cuerpo,
          "y SÓLO ese aviso, por su mensaje — no se apaga la categoría entera")
    check('catch_warnings' in cuerpo,
          "y sólo dentro de esa llamada, no globalmente")


def test_panel_equipos():
    """
    v107 — H2H, clasificación y forma del cruce, sin API y sin pulsar nada.

    Lo pidió el usuario para decidir la apuesta con todo delante, al estilo de
    SofaScore. La sección que había (`render_h2h_club`) dependía de
    API-Football: clave obligatoria, presupuesto de peticiones, un botón, y su
    plan gratuito **se queda en 2024-25**. Quien no configuraba la clave no
    veía nada.

    Todo esto sale del `historico_<clave>.csv` con el que ya se entrena el
    modelo: cubre las 50 competiciones activas, llega más atrás que el plan
    gratuito y no puede fallar por red.
    """
    import config
    import panel_equipos as pe

    # --- cara a cara --------------------------------------------------------
    h = pe.h2h('liga_mx', 'Club America', 'Cruz Azul')
    check(h['n'] >= 20,
          f"el H2H sale del histórico local ({h['n']} cruces de "
          f"América-Cruz Azul, desde {h.get('desde')})")
    check(h['gana_a'] + h['empates'] + h['gana_b'] == h['n'],
          "el balance cuadra con el número de cruces")
    check(all(p['fecha'] and p['local'] and p['visitante']
              for p in h['partidos']),
          "cada cruce trae fecha y los dos equipos")
    check(h['partidos'] == sorted(h['partidos'], key=lambda p: p['fecha'],
                                  reverse=True),
          "y salen del más reciente al más antiguo")

    # --- clasificación en TODAS las competiciones activas --------------------
    activas = [k for k, v in config.LEAGUES.items() if v.get('disponible')]
    sin_tabla = []
    for k in activas:
        try:
            if not pe.clasificacion(k):
                sin_tabla.append(k)
        except Exception as e:
            sin_tabla.append(f'{k}({type(e).__name__})')
    check(not sin_tabla,
          f"las {len(activas)} competiciones activas tienen clasificación "
          f"calculable ({sin_tabla[:5]})")

    cl = pe.clasificacion('liga_mx')
    check(cl[0]['pos'] == 1 and cl[0]['pts'] >= cl[-1]['pts'],
          "la tabla va ordenada por puntos")
    for f in cl:
        check(f['g'] + f['e'] + f['p'] == f['pj'],
              f"{f['equipo']}: G+E+P cuadra con PJ") if f is cl[0] else None
        check(f['pts'] == f['g'] * 3 + f['e'],
              f"{f['equipo']}: los puntos cuadran (3 por victoria)") \
            if f is cl[0] else None

    # --- degradación limpia: nunca lanza, nunca inventa ---------------------
    check(pe.h2h('__no_existe__', 'A', 'B')['n'] == 0,
          "una competición inexistente devuelve 0 cruces, no una excepción")
    check(pe.forma('liga_mx', '__equipo_inventado__')['n'] == 0,
          "un equipo que no está devuelve forma vacía")
    check(pe.posicion('liga_mx', '__equipo_inventado__') is None,
          "y no aparece en la clasificación")
    check(pe.clasificacion('__no_existe__') == [],
          "y una liga sin histórico no tiene tabla")

    # --- LA LECTURA NO PUEDE CONTRADECIRSE ---------------------------------
    #
    # Primera versión: la frase de arriba exigía el doble de victorias para
    # decir «domina» y la de abajo se conformaba con `ga > gb`. Con un 9-10-7
    # el panel decía «historial parejo» y dos líneas después «América domina el
    # historial». Un panel que se contradice es peor que uno escueto: el
    # usuario no sabe cuál creerse.
    frases = pe.lectura('liga_mx', 'Club America', 'Cruz Azul')
    texto = ' '.join(frases)
    check(not ('parejo' in texto and 'domina el historial' in texto),
          f"la lectura no dice «parejo» y «domina» a la vez")
    check(len(frases) >= 2, f"la lectura dice algo útil ({len(frases)} frases)")

    src = open('panel_equipos.py', encoding='utf-8').read()
    check('HUECO_TEMPORADA_DIAS' in src,
          "la temporada en curso se detecta por el parón del calendario, no "
          "con una regla por país (hay ligas de año natural, de agosto a mayo "
          "y de dos torneos por año)")
    check("format='mixed'" in src,
          "las fechas se parsean con formato mixto: los históricos de ESPN "
          "traen hora y los de football-data no, y inferir uno solo convierte "
          "en NaT medio fichero (el fallo que la v105 encontró en el ELO)")

    # --- y la interfaz lo usa ----------------------------------------------
    dash = open('dashboard_ui.py', encoding='utf-8').read()
    check('def render_panel_equipos' in dash, "la interfaz tiene el panel")
    check('render_panel_equipos(clave, home, away' in dash,
          "y lo llama en la vista de liga, para todas las competiciones")
    i_panel = dash.find('render_panel_equipos(clave, home, away')
    i_parlay = dash.find('render_parlay_partido(motor, home, away, key=clave)')
    check(0 < i_panel < i_parlay,
          "el panel va ANTES del combinador: se usa para decidir la apuesta, "
          "no para repasarla después")


def test_roi_negativo_se_avisa_de_frente():
    """
    v108 — el ROI negativo va DELANTE, no escondido en un desplegable.

    El usuario dijo «no quiero perder dinero y quiero que sean seguras», y usa
    la pestaña de Máxima Confianza para decidir («los que tienen de 67 % si
    aciertan»). La medición dice justo lo contrario, y estaba dentro de un
    expander que había que abrir:

        banda        n        ROI       p5
        0,50-0,55  13.792   -5,03 %   -6,31 %
        0,55-0,60  13.106   -4,66 %   -5,94 %
        0,60-0,65   8.821   -4,88 %   -6,17 %
        0,65-0,70   1.439   -6,52 %   -9,77 %   <- justo la que él usa
        0,70-0,75      33  +27,76 %   +8,75 %   <- 33 apuestas: ruido

    Las CUATRO bandas con muestra real (37.158 apuestas en total) pierden
    dinero. Enseñar el acierto («61,5 %») sin el ROI («−6,52 %») al lado es la
    media verdad que hace perder dinero: se acierta seis de cada diez y aun
    así se pierde, porque la cuota de un favorito no paga lo que arriesga.

    Un aviso que hay que desplegar para verlo no es un aviso.
    """
    if not os.path.exists('calibracion_confianza.json'):
        check(False, 'calibracion_confianza.json existe')
        return
    with open('calibracion_confianza.json', encoding='utf-8') as f:
        cal = json.load(f)

    bandas = [b for b in cal.get('bandas', [])
              if b.get('roi') is not None and b.get('n', 0) >= 500]
    check(len(bandas) >= 3,
          f"hay bandas con muestra suficiente para juzgar ({len(bandas)})")
    perdedoras = [b for b in bandas if b['roi'] < 0]
    # Esto NO es un test de que el modelo sea malo: es un test de que, mientras
    # lo sea, la interfaz lo diga. Si algún día el ROI se vuelve positivo, el
    # aviso desaparece solo y este test sigue pasando.
    dash = open('dashboard_ui.py', encoding='utf-8').read()
    i_fn = dash.find('def _render_maxima_confianza')
    # v122 — la función ENTERA, no los primeros 6.000 caracteres.
    #
    # El corte fijo era un número mágico que ataba el test a la LONGITUD de la
    # función en vez de a su contenido: al añadirle unas líneas en esta
    # versión, «muestra corta» se salió de la ventana y el test falló sin que
    # nada hubiera dejado de mostrarse. Un test que se rompe al crecer la
    # función avisa de lo que no es. Se corta en el siguiente `def` a nivel de
    # módulo, que es el final de verdad.
    _resto = dash[i_fn:]
    _fin = _resto.find('\ndef ', 1)
    cuerpo = _resto[:_fin] if _fin > 0 else _resto

    check('st.error' in cuerpo,
          "el aviso de ROI negativo usa `st.error` (rojo), no un caption")
    check('PERDIDO dinero' in cuerpo or 'perdido dinero' in cuerpo.lower(),
          "y dice literalmente que se ha perdido dinero")
    i_error = cuerpo.find('st.error')
    i_expander = cuerpo.find('st.expander')
    check(0 < i_error < i_expander,
          "el aviso va ANTES del desplegable: uno que hay que abrir para verlo "
          "no es un aviso")
    check('no para apostar sueltas' in cuerpo or 'patas de combinada' in cuerpo,
          "se dice para qué SÍ sirven estos picks (patas de combinada)")
    check('line shopping' in cuerpo,
          "y se apunta al único canal con ROI positivo y robusto del histórico")

    # la tabla tiene que traer el p5 y el tamaño de muestra, o el ROI engaña
    check("'ROI en el peor 5 %'" in cuerpo or 'p5' in cuerpo,
          "la tabla enseña el p5 del bootstrap junto al ROI")
    check('muestra corta' in cuerpo,
          "y marca las bandas con muestra insuficiente (la de +27,8 % tiene 33 "
          "apuestas)")

    if perdedoras:
        peor = min(perdedoras, key=lambda b: b['roi'])
        print(f'      · dato actual: la peor banda es '
              f'{peor["desde"]:.2f}-{peor["hasta"]:.2f} con ROI '
              f'{peor["roi"]:+.2%} sobre {peor["n"]} apuestas')


def test_cobertura_remates_medida():
    """
    v107 — dónde hay remates por jugador y dónde no, medido en vez de supuesto.

    `remates_jugadores` funciona igual en todas las competiciones —pide el
    `summary` del partido y lee `rosters`— pero ESPN no lo publica para todas.
    Hasta aquí eso salía como una tabla vacía con un «no disponible» junto a
    cada equipo, indistinguible de un fallo de red o de un equipo mal mapeado.

    v118 — LA MEDICIÓN ANTERIOR ESTABA MAL, Y EL FALLO ERA EL MISMO QUE OCULTABA.

    `remates_jugadores` metía la CLAVE DEL PROYECTO en la URL de ESPN en vez de
    su CÓDIGO:

        .../soccer/liga_mx/scoreboard   →  400 Bad Request
        .../soccer/mex.1/scoreboard     →  200, 13 partidos

    Con la clave equivocada el catálogo de equipos salía vacío y la competición
    se anotaba como «sin remates» aunque ESPN los publicara. Liga MX devolvía
    CERO jugadores y la interfaz decía «ESPN no publica esto» — sobre una liga
    que devuelve 36.

    Rehecha en la v118 con el código correcto y probando TRES equipos por
    competición (con uno solo, Brasil salía «sin datos» porque el primero del
    catálogo no jugó en la ventana, mientras Palmeiras devuelve 38 jugadores):
    **44 con datos, 5 sin ellos** de las 49 activas.
    """
    import remates_jugadores as rj

    c = rj.cobertura()
    check(bool(c), "existe el fichero de cobertura de remates")
    con = c.get('con_remates') or []
    sin = c.get('sin_remates') or {}
    check(len(con) >= 40,
          f"la mayoría de competiciones tienen remates por jugador "
          f"({len(con)} con, {len(sin)} sin)")
    check(not (set(con) & set(sin)),
          "ninguna competición está a la vez con y sin datos")

    # la traducción de clave a código de ESPN es lo que arregló todo
    check(rj.codigo_espn('liga_mx') == 'mex.1',
          "la clave del proyecto se traduce al código de ESPN")
    check(rj.codigo_espn('premier') == 'eng.1', "y para el resto igual")
    check(rj.codigo_espn('__inventada__') == '__inventada__',
          "una clave desconocida se deja tal cual, no se rompe")

    check(rj.hay_remates('liga_mx') is True, "Liga MX sí tiene remates")
    check(rj.hay_remates('brasil') is True,
          "y el Brasileirão TAMBIÉN — la medición vieja se equivocaba")
    # `None` tiene que ser distinto de `False`: una liga sin medir puede tener
    # datos, y decir «no hay» sin comprobarlo sería inventar.
    check(rj.hay_remates('__no_medida__') is None,
          "una competición sin medir devuelve None, no False")

    dash = open('dashboard_ui.py', encoding='utf-8').read()
    check('hay_remates' in dash,
          "la interfaz consulta la cobertura antes de enseñar la sección")


_ASSETS_CACHE = {}


def _ASSETS_DEL_RELEASE():
    """Nombres de los assets de `modelos-latest`, o None si no hay red.

    v148 — se consulta la API pública de GitHub, que no pide credenciales para
    un repositorio público. Devolver None y no una lista vacía es deliberado:
    «no lo sé» y «no hay ninguno» llevan a conclusiones opuestas, y confundirlos
    haría que este test cantara un fallo inventado cada vez que se ejecuta sin
    conexión.
    """
    if 'assets' in _ASSETS_CACHE:
        return _ASSETS_CACHE['assets']
    salida = None
    try:
        import json as _json
        import urllib.request as _u
        import modelos_remotos as _mr
        url = (f'https://api.github.com/repos/{_mr.REPO}/releases/tags/'
               f'{_mr.ETIQUETA}')
        with _u.urlopen(url, timeout=20) as r:
            salida = {a['name'] for a in _json.load(r).get('assets', [])}
    except Exception:
        salida = None
    _ASSETS_CACHE['assets'] = salida
    return salida


def test_ningun_test_se_queda_sin_ejecutar():
    """
    v150 — un test que no se llama pasa siempre, y eso es peor que no tenerlo.

    Este fichero no descubre los tests: los llama a mano al final. Añadir una
    función `test_*` y olvidarse de la línea de llamada produce un test que
    parece existir, sale en el fichero, y **nunca se ejecuta**. La suite
    termina en «TODO OK» y nadie se entera.

    Lo destapó la v150: al enganchar el aviso del fallback de mercado apareció
    que `test_metricas_con_procedencia` llevaba DEFINIDO y sin llamar. Es la
    misma familia de trampa que ya está escrita en la bitácora —«un test que no
    encuentra su fichero devuelve exit 0, comprobar que CORRIÓ»— sólo que aquí
    el que no corre es el test mismo.

    Se comprueba con AST y no con `dir()` para no depender de importarse a sí
    mismo ni del orden de definición.
    """
    import ast as _ast

    src = open('test_catalogo_y_cuotas.py', encoding='utf-8').read()
    arbol = _ast.parse(src)
    definidos = {n.name for n in _ast.walk(arbol)
                 if isinstance(n, _ast.FunctionDef) and n.name.startswith('test_')}
    # el bloque de arranque es el único sitio donde se llaman
    principal = src[src.index("if __name__"):]
    llamados = {n for n in definidos if f'{n}()' in principal}
    huerfanos = sorted(definidos - llamados)
    check(not huerfanos,
          f"todos los tests definidos se ejecutan de verdad ({huerfanos})")


def test_el_fallback_de_mercado_se_delata():
    """
    v150 — un relleno que tapa una liga entera tiene que avisar.

    Desde la v149 un partido sin modelo sale con la probabilidad implícita del
    mercado en vez de con un hueco. Eso es correcto —el precio sabe más que el
    modelo— pero cambia el modo de fallo: **un hueco se ve, un relleno no.** Si
    una liga dejara de cargar su modelo, la pantalla se vería normal y el
    corazón de la aplicación estaría apagado, que es exactamente lo que pasó en
    la v106 con doce competiciones, sólo que con mejor disfraz.

    Se comprueban los dos lados, porque una alarma sólo sirve si además CALLA
    cuando debe: si saltara con los dos ascendidos de la Premier en agosto,
    saltaría todos los días de agosto y nadie volvería a leerla.
    """
    import alpha_finder

    def _fixtures(clave, total, sin_modelo):
        return [{'deporte': 'Fútbol', 'clave_liga': clave,
                 'sin_modelo': i < sin_modelo} for i in range(total)]

    # CALLA: dos ascendidos de diez es lo normal en agosto (Coventry y Hull,
    # medido el 2026-08-21). Avisar aquí sería ruido.
    check(not alpha_finder.avisos_sin_modelo(_fixtures('premier', 10, 2)),
          "el fallback de mercado NO avisa por un par de ascendidos")

    # CALLA: con dos partidos, uno sin modelo ya es el 50 % y no significa nada.
    check(not alpha_finder.avisos_sin_modelo(_fixtures('mini', 2, 1)),
          "y tampoco avisa con una muestra de dos partidos")

    # AVISA: un tercio o más ya no son ascensos.
    avisos = alpha_finder.avisos_sin_modelo(_fixtures('premier', 10, 4))
    check(len(avisos) == 1 and 'premier' in avisos[0],
          "pero SÍ avisa cuando el mercado tapa un tercio de la liga")

    # AVISA: la liga entera caída es el caso que motivó todo esto.
    caida = alpha_finder.avisos_sin_modelo(_fixtures('laliga', 9, 9))
    check(len(caida) == 1 and 'laliga' in caida[0],
          "y con la liga entera tapada, con su nombre y su cifra")

    check(not alpha_finder.avisos_sin_modelo([]),
          "sin partidos no inventa avisos")


def test_ninguna_liga_activa_sin_modelo():
    """
    v106 — una competición ACTIVA no puede tener su modelo fuera del repo.

    El fallo: `.gitignore` excluía 15 carpetas de `modelos/` con el argumento
    «la app nunca las carga porque el selector sólo muestra las `disponible`».
    Entre la v68 y hoy, **12 de esas 15 pasaron a `disponible: True`** y nadie
    tocó el .gitignore. Resultado: el runner las entrenaba cada día, el commit
    las descartaba, Streamlit Cloud clonaba sin ellas, `ClubEngine` moría con
    FileNotFoundError y `_barrido_fixtures` las saltaba **sin decir nada**.
    Doce competiciones desaparecidas de las apuestas del día, los pronósticos
    y la tabla de confianza, sin un solo aviso.

    Es un fallo de CONSISTENCIA entre dos ficheros, del tipo que no produce
    excepción y no se nota hasta que alguien va a buscar una liga y no está.
    Por eso se comprueba aquí y no se confía en recordarlo.
    """
    import config

    ignoradas = set()
    with open('.gitignore', encoding='utf-8') as f:
        for linea in f:
            linea = linea.strip()
            if linea.startswith('modelos/') and not linea.startswith('#'):
                ignoradas.add(linea.rstrip('/').split('/')[-1])

    activas = {k for k, v in config.LEAGUES.items() if v.get('disponible')}
    conflicto = sorted(activas & ignoradas)
    check(not conflicto,
          f"ninguna competición activa tiene su modelo excluido del repo "
          f"({conflicto})")

    # y las activas tienen que tener el artefacto DISPONIBLE de verdad
    #
    # v148 — «disponible» ya no significa «está en el repo».
    #
    # Los pesos por competición salieron de la historia de git y viven como
    # assets del Release `modelos-latest`, que la aplicación baja bajo demanda
    # (ver `modelos_remotos.py`). Un clon limpio NO trae `modelos/<liga>/`, así
    # que exigir el fichero en disco convertía este test en un falso negativo
    # permanente.
    #
    # Lo que se comprueba sigue siendo LO MISMO —que ninguna competición activa
    # se quede sin modelo y desaparezca en silencio, que es el fallo de la
    # v106— sólo que ahora hay dos sitios válidos donde puede estar: el disco o
    # el Release. Si no está en ninguno, es el mismo agujero de siempre.
    #
    # El Release se consulta UNA vez y con red opcional: sin conexión no se
    # puede afirmar nada, así que el test lo dice y no inventa un veredicto.
    _en_disco = {k for k in activas
                 if os.path.exists(os.path.join('modelos', k, 'modelo.joblib'))}
    _faltan_local = sorted(k for k in activas
                           if k in _CLAVES_CON_MODELO_PROPIO()
                           and k not in _en_disco)
    if not _faltan_local:
        check(True, "todas las activas con motor propio traen su modelo.joblib")
    else:
        _publicados = _ASSETS_DEL_RELEASE()
        if _publicados is None:
            print(f"AVISO {len(_faltan_local)} modelos no están en disco y no se "
                  f"pudo consultar el Release (sin red): no se afirma nada.")
        else:
            _sin_ningun_sitio = sorted(k for k in _faltan_local
                                       if f'modelos-{k}.tar.gz' not in _publicados)
            check(not _sin_ningun_sitio,
                  f"todas las activas con motor propio tienen su modelo, en "
                  f"disco o publicado en el Release ({_sin_ningun_sitio})")

    # las que se apartaron dicen POR QUÉ, con la cifra medida
    for k in ('eng_championship', 'eng_fa_cup', 'ned_eerste'):
        cfg = config.LEAGUES.get(k) or {}
        check(not cfg.get('disponible'), f"{k} está apartada")
        check('ELO' in str(cfg.get('nota', '')),
              f"y su nota dice contra qué se midió ({str(cfg.get('nota'))[:60]})")


def _CLAVES_CON_MODELO_PROPIO():
    """Competiciones que entrena `league_engine` (las de fútbol de club).

    Se excluyen las que tienen motor aparte o histórico compuesto, que no
    escriben `modelos/<clave>/modelo.joblib`.
    """
    import config
    return {k for k, v in config.LEAGUES.items()
            if v.get('formato') not in ('api_football',)}


def test_motores_de_deporte_cargan():
    """
    v106 — los CUATRO motores de deporte cargan, y dos fallos que lo impedían.

    Se descubrió al cablear el EV+ automático de cada deporte: los paneles
    decían «motor no disponible» y el motivo llevaba versiones escondido.

    1. **MLB, ATP y WTA: `XGBoostError: input stream corrupted`.** Es el fallo
       que la v87 diagnosticó y resolvió con `modelos_portables` — el pickle
       guarda el formato de SERIALIZACIÓN de XGBoost, que depende del entorno,
       así que un modelo entrenado en el runner de Linux no abre en Windows.
       La v87 cableó la reparación SÓLO en `ClubEngine` (fútbol);
       `BaseSportsEngine` se quedó con `joblib.load` a secas. En Streamlit
       Cloud (Linux, igual que el runner) no se nota, y por eso no se veía.

    2. **NBA: `AttributeError: Can't get attribute '_BlendEloNBA' on
       <module '__main__'>`.** Éste NO es de plataforma y rompía también en
       producción: el entrenamiento se lanza con `python -m
       engines.nba_engine`, donde ese fichero es `__main__`, así que pickle
       guardó la clase como `__main__._BlendEloNBA`. Al cargar desde la app,
       `__main__` es Streamlit y allí no existe. El modelo publicado no se
       podía abrir desde ningún sitio.
    """
    from engines.kbo_engine import KBOEngine
    from engines.mlb_engine import MLBEngine
    from engines.nba_engine import NBAEngine
    from engines.tennis_engine import TennisEngine

    for etq, motor in (('MLB', MLBEngine()), ('ATP', TennisEngine('atp')),
                       ('WTA', TennisEngine('wta')), ('KBO', KBOEngine()),
                       ('NBA', NBAEngine())):
        eng = motor.cargar_modelo()
        check(getattr(eng, 'listo', False),
              f"el motor de {etq} carga "
              f"({str(getattr(eng, 'error', '')) [:70] or 'sin error'})")

    # la reparación portable tiene que estar cableada donde falta, no sólo en
    # el fútbol
    base = open(os.path.join('engines', 'base_engine.py'), encoding='utf-8').read()
    check('modelos_portables' in base,
          "BaseSportsEngine carga por la ruta con reparación de plataforma")

    # y la NBA tiene que poder PREDECIR, no sólo abrir el fichero
    nba = NBAEngine().cargar_modelo()
    if getattr(nba, 'listo', False) and len(nba.equipos) > 1:
        p = nba.predecir(nba.equipos[0], nba.equipos[1])
        check('error' not in p and 0 < (p.get('prob_home') or 0) < 1,
              f"y predice de verdad (prob local {p.get('prob_home')})")

    # el entrenamiento no puede volver a serializar la clase como `__main__`
    src = open(os.path.join('engines', 'nba_engine.py'), encoding='utf-8').read()
    i = src.find("if __name__ == '__main__':")
    check(i > 0 and 'from engines.nba_engine import' in src[i:],
          "el entrenamiento de NBA reimporta la clase del paquete, para que el "
          "próximo modelo no vuelva a apuntar a `__main__`")


def test_beisbol_pitchers():
    """
    v106 — abridor, estadio y ponches, con la regla de parlay del usuario.

    Se comprueban las tres cosas que pueden estar mal sin que se note:
      · que el factor de parque salga de MEDIR y no de una tabla a mano,
      · que el SIGNO de la run line sea el correcto (aquí hubo un error real:
        Pinnacle indexa cada precio por SU línea, no por la del local, y darle
        la vuelta convertía un +1.5 en un −1.5),
      · que la cascada de decisión sea la que el usuario describió.
    """
    import beisbol_pitchers as bp

    # --- factores de parque: medidos, y con el resultado que se sabe --------
    f = bp.factores_parque()
    check(len(f) >= 25, f"hay factor de parque para {len(f)} equipos")
    if f:
        peor = max(f.items(), key=lambda x: x[1])
        check(peor[0] == 'COL',
              f"Coors Field sale como el parque más de bateadores ({peor})")
        check(f.get('COL', 0) > 1.10,
              f"y con un margen claro (×{f.get('COL'):.3f})")
        check(min(f.values()) < 0.95,
              "y hay parques de lanzadores en el otro extremo")
    check(bp.factor_parque('__equipo_que_no_existe__') == 1.0,
          "un equipo sin medición sale neutro, no inventado")

    # --- el signo de la run line -------------------------------------------
    # Pinnacle: {'-1.5': {'home': …}, '1.5': {'away': …}} → la clave YA es la
    # línea de ese lado.
    sp = {'-1.5': {'home': 2.51}, '1.5': {'away': 1.60}}
    check(bp._run_line(sp, 'home') == {'linea': -1.5, 'cuota': 2.51},
          "el local que da 1,5 sale como −1.5")
    check(bp._run_line(sp, 'away') == {'linea': 1.5, 'cuota': 1.6},
          "y el visitante que RECIBE 1,5 sale como +1.5, no como −1.5")
    check(bp._run_line(None, 'home') is None, "sin spreads no se inventa línea")

    # --- el favorito lo decide el CASINO, no el modelo ----------------------
    check(bp._lado_favorito(1.60, 2.40) == 'home', "cuota menor = favorito")
    check(bp._lado_favorito(2.40, 1.60) == 'away', "y por el otro lado igual")
    check(bp._lado_favorito(None, 1.60) is None, "sin las dos cuotas, no hay "
                                                 "favorito que declarar")

    # --- la cascada de decisión --------------------------------------------
    check(bp.K_LINEA_ALTA == 6.0,
          "el corte de «muchos ponches» es 6, como lo pidió el usuario")
    check(bp.CUOTA_GANADOR_MIN == 1.50,
          "y «cuota de ganador buena» es el mismo mínimo que el resto del "
          "proyecto")
    src = open('beisbol_pitchers.py', encoding='utf-8').read()
    i_ml = src.find('conviene meterlo de GANADOR')
    i_k = src.find('no conviene tomar esa cuota')
    check(0 < i_ml < i_k,
          "el caso del favorito con buen abridor se evalúa ANTES que la línea "
          "de ponches (el usuario lo puso como el «pero» que manda)")
    check('regla_del_usuario' in src,
          "cada veredicto se marca como regla del usuario, no como edge medido")

    # sin abridor no se opina: es la variable que más pesa en béisbol
    v = bp.veredicto('NYA', 'BOS', None, None, 1.80, 2.10)
    check(not v['entra'], "sin abridor anunciado el partido no entra")
    check(any('abridor' in m for m in v['motivos']),
          "y se dice que el motivo es la falta de abridor")

    # --- la fuente de los props es la que ya se usa, sin claves nuevas ------
    check('withSpecials' in src,
          "la línea de ponches sale del mismo endpoint de Pinnacle que ya se "
          "consulta para los moneyline: cero peticiones nuevas")
    check('total strikeouts' in src.lower(),
          "y se reconoce el mercado por su nombre en la fuente")


def test_handicap_en_todas_las_ligas():
    """
    v106 — el hándicap deja de existir sólo donde football-data lo publica.

    Medido antes del cambio: de las 57 competiciones activas, sólo **20**
    tenían backtest de hándicap (`roi_bets_ah_*.json`), y son exactamente las
    20 cuyo CSV de football-data trae columnas asiáticas (`AHCh`, `AvgCAHH`,
    `AvgCAHA`). Liga MX —la liga del usuario— no estaba entre ellas, ni las 21
    que sólo cubre ESPN, ni las 14 de formato `new`.

    No era falta de tiempo: el dato no se guardaba en ningún sitio.
    `daily_snapshots` fotografiaba 1X2, totales y BTTS pero nunca el hándicap,
    aunque `odds_store` tiene sus tres columnas desde la v75. Y el scoreboard
    de ESPN —que ya se descarga— lo traía en `pointSpread` sin que nadie lo
    leyera: 33 de 33 partidos con cuota lo publicaban.
    """
    import fixtures_espn as fe

    src = open('fixtures_espn.py', encoding='utf-8').read()
    check('pointSpread' in src,
          "el scoreboard de ESPN se lee también el hándicap (viene gratis en "
          "el mismo JSON que ya se descarga)")

    # el barrido cae al scoreboard cuando el core API no responde
    af = open('alpha_finder.py', encoding='utf-8').read()
    check("fx.get('ah_linea')" in af,
          "el barrido usa el hándicap del scoreboard si el core API no lo trajo")

    # la foto diaria acumula el hándicap: es la única vía para que las ligas
    # sin CSV asiático puedan medirlo algún día
    ds = open('daily_snapshots.py', encoding='utf-8').read()
    check("'ah_linea'" in ds,
          "la foto diaria guarda la línea de hándicap")
    check("odds_ah_home" in ds and "odds_ah_away" in ds,
          "y las dos cuotas")
    import odds_store
    esquema = odds_store.ESQUEMA if hasattr(odds_store, 'ESQUEMA') else \
        open('odds_store.py', encoding='utf-8').read()
    check('ah_linea' in str(esquema),
          "el almacén tiene dónde guardarlo (lo tenía desde la v75, vacío)")

    # y las cuotas multi-casa exponen el hándicap por casa, que es lo que
    # permite hacer line shopping también en este mercado
    cm_src = open('cuotas_multi.py', encoding='utf-8').read()
    check('handicap_por_casa' in cm_src,
          "cuotas_partido devuelve el hándicap por casa")
    check('_spread_principal' in cm_src,
          "con la línea normalizada al LOCAL (Pinnacle la indexa por lado)")

    # el normalizador tiene que respetar el signo y la inversión de equipos
    import cuotas_multi as cm
    sp = {'-0.5': {'home': 1.95}, '0.5': {'away': 1.90}}
    r = cm._spread_principal(sp)
    check(r and abs(r['linea'] + 0.5) < 1e-9,
          f"la línea del local es −0,5 ({r})")
    ri = cm._spread_principal(sp, invertido=True)
    check(ri and abs(ri['linea'] - 0.5) < 1e-9,
          "si la casa listó los equipos al revés, la línea cambia de signo")

    # -----------------------------------------------------------------------
    # LA CADENA VACÍA NO PUEDE COLARSE COMO LÍNEA.
    #
    # `importar_snapshots` recarga el CSV con `csv.DictReader`, que devuelve ''
    # para toda celda vacía. Las cuotas ya se saneaban; `ah_linea` no, y entraba
    # como '' en una columna REAL. Medido al empezar a guardar el hándicap:
    # **17.202 filas con `ah_linea = ''`**, que un `WHERE ah_linea IS NOT NULL`
    # cuenta como si tuvieran línea. Sin este saneo, el primer backtest de
    # hándicap sobre las fotos arrancaría con 17.000 filas fantasma.
    # -----------------------------------------------------------------------
    import odds_store as _os
    for crudo, esperado in (('', None), (None, None), ('x', None),
                            ('-0.5', -0.5), (-1.0, -1.0), (0, 0.0)):
        v = _os._limpiar({'ah_linea': crudo}).get('ah_linea')
        check(v is None if esperado is None else v == esperado,
              f"ah_linea {crudo!r} se normaliza a {v!r}")
    if os.path.exists('odds_historico.db'):
        import sqlite3
        _c = sqlite3.connect('odds_historico.db')
        try:
            vacias = _c.execute("SELECT COUNT(*) FROM historical_odds "
                                "WHERE ah_linea = ''").fetchone()[0]
            check(vacias == 0,
                  f"ninguna fila guarda '' como línea de hándicap ({vacias})")
        finally:
            _c.close()


# ---------------------------------------------------------------------------
# v131 - NFL. Cada comprobacion corresponde a un fallo REAL encontrado al
# integrarla, no a una hipotesis.
# ---------------------------------------------------------------------------
def test_nfl_mapeo_de_nombres():
    """
    Los 32 equipos, con las abreviaturas que usa Playdoit de verdad.

    El fallo que cubre: Playdoit escribe «ARZ Cardinals» (ESPN escribe ARI),
    «LA Rams» y «LA Chargers» (mismo prefijo de ciudad), «NY Jets» y
    «NY Giants» (idem) y mete tabulaciones dentro del nombre. Un emparejador
    por parecido los confunde entre si, y confundirlos no da un error: da una
    apuesta al equipo contrario.
    """
    import nfl_datos as nd
    check(len(nd.EQUIPOS) == 32,
          f"los 32 equipos de la NFL estan en la tabla ({len(nd.EQUIPOS)})")
    casos = {'NE  Patriots': 'NE', 'SF 49ers\t\t': 'SF', 'ARZ Cardinals': 'ARI',
             'LA Rams': 'LAR', 'LA Chargers': 'LAC', 'NY Jets': 'NYJ',
             'NY Giants': 'NYG', 'WAS Commanders\t\t': 'WSH',
             'Kansas City Chiefs': 'KC', 'GB Packers\t': 'GB'}
    for texto, esperado in casos.items():
        obtenido = nd.abreviatura(texto)
        check(obtenido == esperado,
              f"«{texto.strip()}» -> {esperado} (obtenido {obtenido})")
    check(nd.abreviatura('Wroclaw Panthers') is None,
          "un equipo que no es de la NFL devuelve None en vez de adivinar")
    check(nd.abreviatura('') is None, "el nombre vacio devuelve None")
    faltan = sorted(set(nd.EQUIPOS) - set(nd.ESTADIOS))
    check(not faltan, f"los 32 equipos tienen estadio con coordenadas ({faltan})")


def test_nfl_abreviaturas_no_chocan_con_mlb():
    """
    Catorce ciudades tienen equipo de MLB y de NFL: KC, SF, TB, SEA, PIT, PHI,
    MIN, MIA, DET, CLE, CIN, BAL, ATL, HOU y WSH.

    El fallo que cubre: `normalizar` expandia abreviaturas con un diccionario
    plano de MLB. Al anadir la NFL, «KC Chiefs» habria salido como «kansas city
    royals» - un equipo de otro deporte, sin dar el menor error.
    """
    import cuotas_multi as cm
    pares = [('KC Chiefs', 'kansas city chiefs'),
             ('KC Royals', 'kansas city royals'),
             ('SF 49ers', 'san francisco 49ers'),
             ('SF Giants', 'san francisco giants'),
             ('TB Buccaneers', 'tampa bay buccaneers'),
             ('TB Rays', 'tampa bay rays'),
             ('DET Lions', 'detroit lions'),
             ('DET Tigers', 'detroit tigers')]
    for texto, esperado in pares:
        obtenido = cm.normalizar(texto)
        check(obtenido == esperado,
              f"normalizar('{texto}') = '{esperado}' (obtenido '{obtenido}')")


def test_nfl_mercados_no_se_inventan():
    """
    El tablero de la NFL se traduce a PUNTOS, nunca a goles, y lo que el modelo
    no cubre sale con precio y sin EV.

    El fallo que cubre: aplicar el traductor de futbol a un partido de NFL
    haria que «Totales 35.5 puntos» casara por parecido con «Mas de 2.5 goles»
    y saliera un EV inventado - el mismo modo de fallo que la v122 midio en
    +19.603 %.
    """
    import nfl_mercados as nm
    det = {'casa': 'Playdoit', 'deporte': 'nfl',
           'casa_home': 'KC Chiefs', 'casa_away': 'LA Rams',
           'mercados': [
               {'nombre': 'Ganador (incl. prorroga)', 'sv': None, 'selecciones': [
                   {'nombre': 'KC Chiefs', 'cuota': 1.71},
                   {'nombre': 'LA Rams', 'cuota': 2.05}]},
               {'nombre': 'Handicap (incl. prorroga)', 'sv': '-2.5', 'selecciones': [
                   {'nombre': 'KC Chiefs (-2.5)', 'cuota': 1.91},
                   {'nombre': 'LA Rams (+2.5)', 'cuota': 1.83}]},
               {'nombre': 'Totales (incl. prorroga)', 'sv': '35.5', 'selecciones': [
                   {'nombre': 'Mas de 35.5', 'cuota': 1.80},
                   {'nombre': 'Menos de 35.5', 'cuota': 1.95}]},
               {'nombre': 'KC Chiefs total (incl. prorroga)', 'sv': '18.5',
                'selecciones': [{'nombre': 'Mas de 18.5', 'cuota': 1.80},
                                {'nombre': 'Menos de 18.5', 'cuota': 1.87}]},
               {'nombre': '1a Mitad - total', 'sv': '19.5', 'selecciones': [
                   {'nombre': 'Mas de 19.5', 'cuota': 1.80},
                   {'nombre': 'Menos de 19.5', 'cuota': 1.87}]},
               {'nombre': 'Primer equipo en marcar', 'sv': None, 'selecciones': [
                   {'nombre': 'KC Chiefs', 'cuota': 1.71},
                   {'nombre': 'LA Rams', 'cuota': 2.05}]},
           ]}
    filas = nm.filas_playdoit_nfl(det, 'Kansas City Chiefs', 'Los Angeles Rams')
    etiquetas = {f['etiqueta'] for f in filas}
    check(not any('gol' in e.lower() for e in etiquetas),
          "ninguna etiqueta de NFL habla de goles")
    check('Más de 35.5 puntos' in etiquetas,
          f"el total del partido se traduce a puntos ({sorted(etiquetas)[:3]})")
    check('Kansas City Chiefs: más de 18.5 puntos' in etiquetas,
          "el total por equipo lleva el nombre del equipo delante")
    check('Kansas City Chiefs -2.5' in etiquetas and
          'Los Angeles Rams +2.5' in etiquetas,
          "el handicap conserva el signo de cada lado")
    periodos = [f for f in filas if f['familia'] == nm.FAMILIA_TIEMPOS]
    check(bool(periodos) and all(f['ev_no_fiable'] for f in periodos),
          f"los {len(periodos)} mercados de mitad salen con el EV marcado")
    otros = [f for f in filas if f['familia'] == nm.FAMILIA_OTROS]
    check(bool(otros) and all(f['ev_no_fiable'] for f in otros),
          f"«primer equipo en marcar» sale con precio y sin EV ({len(otros)})")
    lin = nm.lineas_del_tablero(det, 'Kansas City Chiefs', 'Los Angeles Rams')
    check(lin['handicap'] == [-2.5],
          f"linea de handicap detectada ({lin['handicap']})")
    check(lin['total'] == [35.5], f"linea de total detectada ({lin['total']})")
    check(lin['total_home'] == [18.5],
          f"linea de total del local detectada ({lin['total_home']})")


def test_nfl_probabilidades_coherentes():
    """
    Las probabilidades del modelo suman lo que tienen que sumar y el empuje se
    reparte donde toca.

    El fallo que cubre: `sigma_equipo` se calculaba SOLO cuando se pedian
    lineas de equipo, asi que la plantilla recibia `None` y los cuatro mercados
    de total por equipo se caian del cruce - aparecian con precio y sin
    probabilidad sin que nada diera error.
    """
    import modelo_nfl as mn
    m = mn.NFLModelo()
    p = m.probabilidades(margen_esp=3.0, total_esp=44.0,
                         linea_hcp=-3.5, linea_total=44.5)
    check(abs(p['prob_home'] + p['prob_away'] + p['prob_empate'] - 1.0) < 1e-3,
          "1X2: local + visitante + empate suman 1")
    check(abs(p['prob_home_sin_empate'] + p['prob_away_sin_empate'] - 1.0) < 1e-6,
          "el mercado a dos vias suma 1 exactamente")
    check(abs(p['prob_hcp_home'] + p['prob_hcp_away'] - 1.0) < 1e-6,
          "handicap de media linea: sin empuje, las dos patas suman 1")
    check(abs(p['prob_over'] + p['prob_under'] - 1.0) < 1e-6,
          "total de media linea: over + under suman 1")
    check(p.get('sigma_equipo') is not None,
          "sigma del total de equipo se calcula SIEMPRE, no solo al pedir lineas")
    pe = m.probabilidades(3.0, 44.0, linea_hcp=-3.0)
    check(pe['prob_hcp_push'] > 0,
          f"handicap de linea entera declara el empuje ({pe['prob_hcp_push']})")
    check(abs(pe['prob_hcp_home'] + pe['prob_hcp_away']
              + pe['prob_hcp_push'] - 1.0) < 1e-3,
          "con empuje, las tres salidas suman 1")
    check(p['prob_home'] > p['prob_away'],
          "con margen esperado positivo, el local es el favorito")
    p2 = m.probabilidades(-7.0, 44.0)
    check(p2['prob_away'] > p2['prob_home'],
          "con margen esperado negativo, el visitante es el favorito")


def test_nfl_sin_fuga_temporal():
    """
    Las features de un partido no pueden contener informacion de ese partido.

    Es la comprobacion mas importante del modelo: un backtest con fuga da un
    numero bonito y una apuesta perdedora. Se verifica construyendo el dataset
    dos veces -con el historico entero y truncado justo tras ese partido- y
    exigiendo que las features de ese partido sean IDENTICAS.
    """
    import nfl_datos as nd
    import modelo_nfl as mn
    d = nd.cargar_historico()
    if not len(d):
        check(True, "sin historico de NFL descargado: comprobacion de fuga omitida")
        return
    d = d[d['tipo'].isin(mn.TIPOS_ENTRENAMIENTO)].sort_values(['fecha', 'event_id'])
    if len(d) < 200:
        check(True, f"historico de NFL corto ({len(d)}): fuga no comprobable")
        return
    corte = len(d) - 30
    completo = mn.construir_dataset(d)
    truncado = mn.construir_dataset(d.iloc[:corte + 1])
    eid = str(d.iloc[corte]['event_id'])
    fa = completo[completo['event_id'].astype(str) == eid]
    fb = truncado[truncado['event_id'].astype(str) == eid]
    if not len(fa) or not len(fb):
        check(False, "el partido de control no aparece en los dos datasets")
        return
    iguales = all(
        abs(float(fa.iloc[0][c]) - float(fb.iloc[0][c])) < 1e-9
        for c in mn.COLS_MARGEN + mn.COLS_TOTAL)
    check(iguales,
          "las features de un partido no cambian al anadir partidos "
          "posteriores (sin fuga temporal)")


def test_nfl_no_sube_a_seccion1_sin_medicion():
    """
    La NFL solo entra en la Seccion 1 con una medicion propia detras.

    Es la regla de oro del proyecto aplicada a un deporte nuevo y de moda, que
    es justo donde mas tienta saltarsela.
    """
    import os as _os

    import clasificador as cl
    pick = {'deporte': 'NFL', 'lado': 'home', 'valor_mercado': True,
            'prob': 0.55, 'cuota': 1.95, 'partido': 'A vs B'}
    c = cl.canal_del_pick(pick)
    if not _os.path.exists('nfl_canal_precio.json'):
        check(c['seccion'] == 2,
              "sin veredicto medido, un pick de NFL va a la Seccion 2")
        return
    import nfl_lineshop as ls
    med = ls.medicion_para_clasificador()
    if med and 'home' in (med.get('lados') or []):
        check(c['seccion'] == 1 and c['canal'] == 'precio_nfl',
              f"con el lado local validado, sube a Seccion 1 ({c['canal']})")
        check('p5' in c.get('motivo', ''),
              "el motivo de la Seccion 1 cita el p5 medido")
    else:
        check(c['seccion'] == 2,
              f"sin lado validado, la NFL se queda en Seccion 2 ({c['canal']})")


def test_nfl_en_el_barrido_y_la_interfaz():
    """La NFL esta enchufada donde tiene que estarlo, no solo escrita."""
    import alpha_finder as af
    import config
    import cuotas_multi as cm
    import fixtures_espn as fe
    check(hasattr(af, '_picks_nfl'), "alpha_finder expone la rama de NFL")
    check('NFL' in config.UMBRALES_DEPORTE,
          "la NFL tiene umbrales declarados en config")
    for mapa, nombre in ((cm.DEPORTES, 'Pinnacle'),
                         (cm.BOVADA_PATH, 'Bovada'),
                         (cm.ALTENAR_SPORT, 'Playdoit/Altenar'),
                         (cm.MATCHBOOK_SPORT, 'Matchbook')):
        check('nfl' in mapa, f"la NFL esta registrada en {nombre}")
    check('nfl' in fe.ESPN_DEPORTES,
          "la NFL esta registrada en el scoreboard de ESPN")
    check('nfl' in cm.ALTENAR_CAMPEONATOS,
          "el catalogo de Altenar filtra la NFL (si no, entrarian NCAAF y CFL)")
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check("('\U0001F3C8', 'NFL')" in src, "el filtro de deporte incluye NFL")
    check('nfl_deporte' in src, "la vista de NFL esta enrutada en la interfaz")
    check('def render_nfl' in src, "la vista de NFL existe")





# ===========================================================================
# v152 — MODO MODELO, RENDIMIENTO OBSERVADO Y LA PRUEBA DE SÍNTESIS
# ===========================================================================
def test_no_se_ensena_estadistica_sintetica():
    """
    v152 — la app no puede llamar «xG» a una función de los goles.

    El plan pedía enseñar xG y posesión en las tarjetas del Modo Modelo. No se
    puede: en este proyecto los dos los escribe `CorrelatedSyntheticGenerator`
    a partir de los goles y del ELO. Medido sobre los históricos guardados:

        xG        = 0,776 + 0,200·goles + ruido(0,529)   ← la calibración exacta
        posesión  = 50 + 12·tanh(elo_diff/300) + ruido(4)

    Enseñar eso etiquetado como xG le diría al usuario que ve calidad de
    ocasiones cuando ve el marcador multiplicado por 0,2, y el ruido lo haría
    parecer una medición independiente. Es el modo de fallo de la v150 —«un
    hueco se ve, un relleno no»— llevado a la pantalla principal.

    `rendimiento_equipos` lo comprueba REPRODUCIENDO el generador, que es
    determinista por MATCH_ID. Este test verifica que esa prueba funciona en
    los dos sentidos: dice «sintético» de lo que lo es y «observado» de lo que
    no, en la misma competición.
    """
    import rendimiento_equipos as rq

    disp = rq.stats_disponibles('premier')
    check(disp.get('goles') is True,
          "los goles de la Premier salen como observados")
    check(disp.get('corners') is True,
          "los córners de la Premier salen como observados (football-data "
          "publica HC/AC)")
    check(disp.get('xg') is False,
          "el xG de la Premier NO sale como observado: lo escribe el generador")
    check(disp.get('posesion') is False,
          "la posesion de la Premier NO sale como observada")

    # La otra mitad, y la que de verdad separa esta prueba de una lista escrita
    # a mano: una liga que NO es de football-data tiene la columna de córners al
    # 100 % y aun asi es relleno.
    disp_mx = rq.stats_disponibles('liga_mx')
    check(disp_mx.get('goles') is True,
          "los goles de la Liga MX salen como observados")
    check(disp_mx.get('corners') is False,
          "los córners de la Liga MX NO salen como observados aunque la columna "
          "este llena: los escribio el generador")


def test_rendimiento_no_rellena_lo_que_falta():
    """
    v152 — un campo sin dato vuelve `None`, nunca un cero ni una media.

    Es la regla del modulo escrita como test. Si un dia alguien pone un
    `fillna(0)` por comodidad, la tarjeta empezaria a decir «córners a favor:
    0,0» en las 55 competiciones que no los publican, que se lee como «este
    equipo no saca córners nunca» en vez de como «no lo sabemos».
    """
    import rendimiento_equipos as rq

    d = rq._historico('liga_mx')
    if d is None or d.empty:
        check(True, "sin historico de Liga MX: nada que comprobar")
        return
    equipo = str(d['home_team'].iloc[-1])
    f = rq.forma('liga_mx', equipo)
    check(f.get('n', 0) > 0, f"hay forma reciente de {equipo}")
    # goles sí; córners tampoco aqui, porque la competicion no los publica de
    # verdad — pero eso lo decide `stats_disponibles`, no `forma`: `forma` lee
    # lo que hay en el fichero. Lo que se comprueba es que no INVENTA.
    check(f.get('gf_media') is not None, "la media de goles existe")

    # Un equipo que no existe no devuelve ceros: devuelve n=0.
    vacio = rq.forma('liga_mx', 'Equipo Que No Existe FC')
    check(vacio.get('n') == 0,
          "un equipo desconocido devuelve n=0, no una fila de ceros")
    check(vacio.get('gf_media') is None,
          "y sus medias vienen vacias, no a cero")

    # v152 — LO MISMO EN TENIS, que no pasa por `panel_equipos` porque su
    # historico usa `jugador_1`/`jugador_2`. La cobertura es parcial (349 de
    # 784 jugadores llegan a cinco partidos) y quien no llega tiene que salir
    # con n=0, no con una racha inventada de los pocos que haya.
    d_t = rq._historico_tenis()
    if d_t is not None and not d_t.empty:
        import pandas as _pd
        frecuentes = _pd.concat([d_t['jugador_1'],
                                 d_t['jugador_2']]).value_counts()
        alguien = str(frecuentes.index[0])
        f_t = rq.forma_tenis(alguien)
        check(f_t.get('n', 0) >= 3, f"hay forma reciente de {alguien}")
        check(f_t.get('pct_sets') is None or 0.0 <= f_t['pct_sets'] <= 1.0,
              "el porcentaje de sets es una proporcion valida")
        check(rq.forma_tenis('Jugador Que No Existe')['n'] == 0,
              "un jugador desconocido devuelve n=0")


def test_modo_modelo_no_tapa_los_huecos_con_el_mercado():
    """
    v152 — en el Modo Modelo, «sin modelo» es «sin modelo».

    Desde la v149 un partido sin pronostico sale con la probabilidad implicita
    del mercado, etiquetada. Es correcto en la lista general —el precio sabe
    mas que el modelo— y es INCORRECTO en una pantalla cuyo unico proposito es
    leer al modelo: un numero del mercado en una fila del modelo hace imposible
    distinguir uno de otro, que es justo lo que la pantalla venia a arreglar.
    """
    import modo_modelo as mm

    src = open('modo_modelo.py', encoding='utf-8').read()
    check('board_mercado' not in src,
          "el Modo Modelo no lee el relleno de mercado de la v149")
    check('Sin datos de modelo' in src,
          "los partidos sin pronostico se etiquetan como tales")

    # y la advertencia medida tiene que estar EN la pantalla, no en un anexo
    check('4,66' in src and '6,52' in src,
          "la pantalla dice lo que rinde ordenar por probabilidad del modelo")


def test_modo_modelo_separa_ligas_secundarias():
    """
    v152 — el filtro de secundarias existe y reparte todo el catalogo.

    La lista corta es de PRINCIPALES: todo lo que no este en ella cuenta como
    secundaria. Se hace en ese sentido a proposito — asi una competicion nueva
    entra por defecto en el grupo que el usuario quiere mirar en vez de
    desaparecer de los dos.
    """
    import modo_modelo as mm

    check(mm.es_secundaria({'clave_liga': 'eng_league_one'}) is True,
          "la League One cuenta como secundaria")
    check(mm.es_secundaria({'clave_liga': 'premier'}) is False,
          "la Premier cuenta como principal")
    check(mm.es_secundaria({'clave_liga': 'liga_inventada_2030'}) is True,
          "una competicion desconocida cae del lado de las secundarias")

    # v152 — Y EL EJE NO APLICA FUERA DEL FÚTBOL.
    #
    # Lo cazo el render: la MLB salia en pantalla como «MLB · MLB ·
    # secundaria», porque no estaba en la lista corta. La MLB no es una liga de
    # futbol secundaria, es otro deporte, y esa etiqueta era una afirmacion que
    # nadie habia hecho. `None` es un tercer valor con significado propio:
    # «este pick no se reparte por este eje».
    for dep in ('MLB', 'NBA', 'Tenis', 'NFL', 'KBO'):
        check(mm.es_secundaria({'deporte': dep, 'clave_liga': dep.lower()})
              is None,
              f"el eje principal/secundaria no aplica a {dep}")

    # v153.1 — SE COMPRUEBA LA PROMESA, NO UNA FRASE.
    #
    # La version anterior buscaba literalmente «no tiene su propio p5» en
    # `modo_modelo.py`. Al simplificar la pantalla ese parrafo se fue —era
    # justamente uno de los textos tecnicos que habia que quitar— y el test
    # fallo, aunque la propiedad que protegia seguia intacta. Un test que exige
    # una redaccion concreta se rompe con cada reescritura y no protege nada.
    #
    # Lo que NO puede pasar es que alguna pantalla AFIRME que las secundarias
    # rinden mas, porque eso no esta medido en este proyecto.
    afirmaciones = ('secundarias son mas rentables', 'secundarias rinden mas',
                    'mejores cuotas en secundarias', 'mas valor en secundarias')
    for fichero in ('modo_modelo.py', 'dashboard_ui.py'):
        if not os.path.exists(fichero):
            continue
        txt = open(fichero, encoding='utf-8').read().lower()
        malas = [a for a in afirmaciones if a in txt]
        check(not malas,
              f"{fichero} no promete que las secundarias rindan mas ({malas})")

    # El selector vive ARRIBA, junto al de deporte, y afecta a todas las
    # pestañas. Un segundo selector del mismo eje dentro de una pestaña haria
    # que el mismo partido saliera en una pantalla y no en la otra.
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    mm_src = open('modo_modelo.py', encoding='utf-8').read()
    check('_filtro_grupo_liga' in ui,
          "el filtro de secundarias esta en la barra comun de la vista")
    check("key='%s_grupo'" % 'mm' not in mm_src
          and "_grupo' % clave" not in mm_src,
          "y NO esta duplicado dentro del Modo Modelo")


def test_el_bot_guarda_los_datos_antes_de_lo_lento():
    """
    v153 — el orden de los pasos del bot decide si los datos llegan o no.

    CAUSA RAIZ MEDIDA. El commit de artefactos era el ULTIMO paso del job,
    detras de la publicacion de assets al Release. En el run 32555539614
    (2026-08-22) el reentrenamiento acabo hacia las 06:20, la subida de assets
    se comio 34 minutos y el job murio cancelado por tiempo en el asset 40 de
    54. El runner tenia la J1 con sus partidos del 21 desde las 06:11 y **no
    llegaron nunca a main**. El dia anterior, failure.

    O sea: dos dias seguidos se tiro una hora de reentrenamiento porque lo
    barato y valioso (los CSV que lee la aplicacion) estaba detras de lo caro y
    prescindible (re-subir pesos que en su mayoria no cambiaron).

    Este test fija el orden. Si alguien vuelve a poner el guardado de
    historicos detras de la publicacion, el fallo vuelve entero y en silencio:
    la app simplemente se queda con los datos de ayer.
    """
    ruta = os.path.join('.github', 'workflows', 'retrain_leagues.yml')
    if not os.path.exists(ruta):
        check(False, 'existe el workflow de reentrenamiento')
        return
    src = open(ruta, encoding='utf-8').read()

    i_guardar = src.find('Guardar históricos y estado')
    i_publicar = src.find('Publicar los modelos como assets')
    check(i_guardar > 0, 'el bot guarda los historicos en su propio paso')
    check(i_publicar > 0, 'el bot publica los assets del Release')
    check(0 < i_guardar < i_publicar,
          'los historicos se guardan ANTES de subir los assets')

    # El tope de tiempo no puede volver a 60: es el que mataba el job.
    import re
    m = re.search(r'timeout-minutes:\s*(\d+)', src)
    check(m is not None and int(m.group(1)) >= 90,
          'el job tiene al menos 90 minutos de tope (%s)'
          % (m.group(1) if m else 'sin tope'))


def test_solo_se_republica_lo_que_cambio():
    """
    v153 — re-subir 54 assets intactos costaba 34 minutos y el dia entero.

    La firma que decide si algo cambio es del CONTENIDO de la carpeta y NO del
    `.tar.gz`, y eso no es un detalle de estilo: gzip escribe la marca de
    tiempo en su cabecera, asi que dos paquetes del mismo contenido nunca son
    iguales byte a byte. Comparando el paquete, el salto no se activaria nunca
    y el arreglo seria decorativo.

    Comprobado aqui empaquetando dos veces lo mismo.
    """
    import hashlib
    import tempfile
    import time

    import publicar_modelos as pm

    claves = pm.competiciones()
    if not claves:
        check(True, 'sin modelos en disco: nada que comprobar')
        return
    clave = min(claves, key=lambda c: sum(
        os.path.getsize(os.path.join('modelos', c, f))
        for f in os.listdir(os.path.join('modelos', c))
        if os.path.isfile(os.path.join('modelos', c, f))))

    h1 = pm._hash_carpeta(clave)
    check(h1 == pm._hash_carpeta(clave),
          'la firma del contenido es estable entre llamadas')
    otras = [c for c in claves if c != clave]
    if otras:
        check(h1 != pm._hash_carpeta(otras[0]),
              'y distingue una competicion de otra')

    def _sha(p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()

    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        a = pm.empaquetar(clave, t1)
        time.sleep(1.1)          # que cambie el segundo que gzip escribe
        b = pm.empaquetar(clave, t2)
        check(_sha(a) != _sha(b),
              'el .tar.gz del MISMO contenido cambia entre ejecuciones: por eso '
              'la firma no puede ser del paquete')

    src = open('publicar_modelos.py', encoding='utf-8').read()
    check('--forzar' in src,
          'queda una salida para re-subirlo todo si el Release se descuadra')


def test_no_se_reentrena_una_liga_sin_partidos_nuevos():
    """
    v153 — el arreglo de los assets era inerte sin esto, y se midio.

    Saltarse la subida de un asset sólo sirve si sus bytes NO cambian. Medido
    sobre `gre_super_league`: dos entrenamientos seguidos con el MISMO
    histórico producen `.joblib` con bytes distintos. O sea que mientras
    `--build` reentrenara las 54 competiciones cada madrugada, el salto de
    subida no se activaria nunca y el arreglo seria decorativo.

    Por eso se corta antes: si el histórico no ha cambiado, no se reentrena.
    Medido tras el cambio: 43,3 s → 0,2 s, y los bytes quedan identicos, con lo
    que el asset tampoco se re-sube. Las dos optimizaciones se encadenan.

    La firma es de fecha, equipos y marcador, NO del dataframe entero: las
    derivadas (`elo_diff`, el xG del generador) se recalculan en cada descarga
    y arrastran ruido propio, asi que incluirlas haria que la firma cambiara
    siempre — el mismo error que tendria comparar el `.tar.gz`.
    """
    import pandas as pd

    import league_engine as le

    check(hasattr(le, '_firma_datos'), 'existe la firma del histórico')
    check(getattr(le, 'VERSION_ENTRENAMIENTO', None) is not None,
          'existe la version de entrenamiento que invalida las firmas de golpe')

    base = pd.DataFrame({
        'date': pd.to_datetime(['2026-01-01', '2026-01-08']),
        'home_team': ['A', 'B'], 'away_team': ['B', 'A'],
        'home_goals': [1.0, 2.0], 'away_goals': [0.0, 2.0],
    })
    f1 = le._firma_datos(base)
    check(f1 == le._firma_datos(base.copy()),
          'la firma es estable con los mismos partidos')
    check(f1 == le._firma_datos(base.iloc[::-1].copy()),
          'y no depende del orden de las filas')

    # Una columna derivada NO puede cambiarla: es lo que impide que el salto se
    # desactive solo en cuanto el generador sintetico mueva un decimal.
    con_ruido = base.copy()
    con_ruido['elo_diff'] = [12.5, -3.25]
    con_ruido['home_xg'] = [1.11, 2.22]
    check(f1 == le._firma_datos(con_ruido),
          'las columnas derivadas no alteran la firma')

    # Un partido nuevo SI la cambia, que es la mitad que hace util al salto.
    nuevo = pd.concat([base, pd.DataFrame({
        'date': pd.to_datetime(['2026-01-15']), 'home_team': ['A'],
        'away_team': ['B'], 'home_goals': [3.0], 'away_goals': [1.0]})])
    check(f1 != le._firma_datos(nuevo),
          'un partido nuevo cambia la firma')
    # Y un marcador corregido tambien: football-data los rectifica a veces.
    corregido = base.copy()
    corregido.loc[corregido.index[0], 'home_goals'] = 5.0
    check(f1 != le._firma_datos(corregido),
          'un marcador corregido cambia la firma')

    src = open('league_engine.py', encoding='utf-8').read()
    check("'--forzar' in sys.argv" in src,
          'queda una salida para reentrenar a la fuerza')



def test_el_precalculo_no_cambia_ni_un_numero():
    """
    v153 — el camino rapido tiene que dar EXACTAMENTE lo mismo que el lento.

    El bot precalcula el 1X2 del dia en `predicciones_dia.json` y el barrido lo
    lee en vez de cargar los modelos (50 s) y predecir (51 s). Medido sobre el
    barrido completo: 119,4 s -> 74,3 s, con 319 pronosticos y 303 con modelo
    en los dos casos.

    Si el precalculo y la prediccion en vivo divergieran, la aplicacion
    enseñaria una cosa distinta segun hubiera fichero o no, que es peor que no
    tener fichero. Por eso el registro guarda la MATRIZ de marcadores y el
    barrido reconstruye con ella un objeto con la forma de `predecir`: asi las
    dos rutas llaman a las mismas funciones de mercados y la equivalencia es por
    construccion, no algo que haya que mantener a mano.

    La primera version guardaba solo un resumen (probabilidades y dos
    agregados). Se quedo corta en cuanto un partido tuvo cuotas:
    `_mercados_del_partido` necesita la matriz entera y el barrido reventaba con
    `NoneType is not subscriptable`.
    """
    import predicciones_dia as pdia

    e = pdia.estado()
    check(isinstance(e, dict) and 'usable' in e,
          'el estado del precalculo se puede consultar siempre')
    if not e.get('usable'):
        check(True, 'sin fichero de predicciones: el barrido predice en vivo '
                    '(%s)' % e.get('motivo'))
        return

    import json

    import alpha_finder as af

    with open(pdia.FICHERO, encoding='utf-8') as f:
        doc = json.load(f)
    registros = doc.get('predicciones') or {}
    check(bool(registros), 'el fichero trae predicciones')

    # Todo registro tiene que poder reconstruirse: si a uno le falta la matriz,
    # el barrido caeria al llegar a el y no al leerlo.
    sin_matriz = [k for k, v in registros.items() if 'score_matrix' not in v]
    check(not sin_matriz,
          'todos los registros llevan su matriz de marcadores (%d sin ella)'
          % len(sin_matriz))

    clave = next(iter(registros))
    reg = registros[clave]
    pred = pdia.como_prediccion(reg)
    check(pred is not None and 'score_matrix' in pred,
          'un registro se reconstruye con la forma de `predecir`')

    # Y los mercados que sale de ahi son los del modelo, no una copia aparte.
    mercados = af._mercados_modelo(pred, reg['home'], reg['away'])
    check(len(mercados) == 7,
          'del precalculo salen los 7 mercados del modelo (%d)' % len(mercados))
    suma_1x2 = sum(m['prob'] for m in mercados if m['mercado'] == '1X2')
    check(abs(suma_1x2 - 1.0) <= 0.01,
          'y su 1X2 suma 1 (%.3f)' % suma_1x2)

    # La clave se indexa por el nombre CRUDO del fixture: es lo que permite
    # consultarlo SIN cargar el motor, que es de donde sale todo el ahorro.
    liga, crudo_h, crudo_a = clave.split('|', 2)
    check(pdia.prediccion(liga, crudo_h, crudo_a) is not None,
          'se consulta con el nombre crudo del fixture, sin catalogo')
    check(reg.get('home') is not None and reg.get('away') is not None,
          'y el registro trae dentro el nombre ya mapeado')

def test_los_except_pueden_registrar_su_error():
    """
    v152 — un `except` que usa un nombre indefinido es peor que no tenerlo.

    `dashboard_ui.py` usaba `logger.` en SEIS sitios y no definia `logger` en
    ninguna parte. Los seis viven dentro de un `except` que intenta dejar
    constancia antes de degradar la pantalla, asi que lo que hacian era lanzar
    `NameError: name 'logger' is not defined` **encima** del error original: el
    manejador se llevaba por delante la vista entera y ademas borraba la pista
    de lo que habia pasado de verdad.

    Cinco llevaban versiones ahi, latentes, porque son caminos de excepcion que
    casi nunca se recorren. Lo destapo la validacion de render al cargar
    «Apuestas del Dia».

    `py_compile` no lo ve: un nombre indefinido dentro de un `except` compila
    igual de bien que uno definido. Este test lo mira con AST, en todos los
    modulos que pintan pantalla.
    """
    import ast

    for fichero in ('dashboard_ui.py', 'modo_modelo.py',
                    'render_todos_partidos.py', 'rendimiento_equipos.py'):
        if not os.path.exists(fichero):
            continue
        arbol = ast.parse(open(fichero, encoding='utf-8').read())
        usa = any(isinstance(n, ast.Attribute)
                  and isinstance(n.value, ast.Name) and n.value.id == 'logger'
                  for n in ast.walk(arbol))
        if not usa:
            continue
        # definido a nivel de MODULO: si estuviera dentro de una funcion, los
        # `except` de las demas seguirian sin verlo.
        definido = any(
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'logger'
                    for t in n.targets)
            for n in arbol.body)
        check(definido,
              f"{fichero} usa `logger` y lo define a nivel de modulo")



def test_la_apuesta_destacada_de_cada_partido():
    """
    v153.1 — la tarjeta dice una cosa: qué apostar y con cuánta probabilidad.

    Gana el mercado con MÁS probabilidad del partido, sea cual sea — no sólo el
    1X2. Se pidió ver «Menos de 2.5 goles (72 %)» cuando eso es lo que el modelo
    cree con más fuerza.

    EL UMBRAL DEL VERDE ES 60 % Y NO 50, Y NO ES DECORATIVO. El board trae
    SIEMPRE los dos lados de cada mercado («mas de 2.5» y «menos de 2.5»), asi
    que el maximo de la lista esta garantizado por encima del 50 %. Con el verde
    en 50 no habria un solo partido sin apuesta destacada, y una etiqueta que
    sale siempre no informa de nada: es la leccion de la v150 sobre los avisos
    —el umbral se elige para que CALLE en el caso corriente— aplicada aqui.
    """
    import modo_modelo as mm

    check(mm.UMBRAL_ALTA > 0.5,
          "el verde exige mas que el 50 %% que el board garantiza (%.2f)"
          % mm.UMBRAL_ALTA)

    # 1. gana el mercado mas probable, aunque no sea el 1X2
    p = {'mercados': [{'mercado': '1X2', 'apuesta': 'Gana A', 'prob': 0.40},
                      {'mercado': 'Goles', 'apuesta': 'Menos de 2.5',
                       'prob': 0.81}]}
    d = mm.apuesta_destacada(p)
    check(d and d['apuesta'] == 'Menos de 2.5' and d['alta'],
          "gana el mercado mas probable del partido, no el 1X2 por defecto")

    # 2. por debajo del verde, ambar; por debajo del ambar, nada
    medio = mm.apuesta_destacada(
        {'mercados': [{'mercado': 'Goles', 'apuesta': 'Mas de 2.5',
                       'prob': 0.52}]})
    check(medio is not None and not medio['alta'],
          "una probabilidad entre 50 y 60 sale como «solo para combinar»")
    check(mm.apuesta_destacada(
        {'mercados': [{'mercado': '1X2', 'apuesta': 'Empate',
                       'prob': 0.34}]}) is None,
          "por debajo del 50 % no hay apuesta destacada")

    # 3. LOS TRES ORIGENES. El tercero existe porque sin el la tarjeta decia
    #    «Sin apuesta clara» en todo partido que llegara solo con `apuesta` y
    #    `prob` —la mayoria fuera del futbol— y eso no es «no hay nada claro»,
    #    es «no mire donde habia».
    check(mm.apuesta_destacada({'board': {'Gana I': 0.66, 'Gana J': 0.34}}),
          "se lee del board cuando no hay lista de mercados")
    solo = mm.apuesta_destacada({'apuesta': 'Gana HOU', 'prob': 0.58,
                                 'mercado': 'Moneyline'})
    check(solo is not None and solo['apuesta'] == 'Gana HOU',
          "y de la propia apuesta del pick cuando no hay ni board")

    # 4. nada utilizable no se inventa
    check(mm.apuesta_destacada({'partido': 'A vs B'}) is None,
          "un pick sin nada que leer no produce una apuesta inventada")
    check(mm.apuesta_destacada({'apuesta': 'X', 'prob': None}) is None,
          "ni uno con la probabilidad vacia")

    # 5. la racha se pinta en color y no se traga letras
    html = mm.racha_html('GEP')
    check(html.count('<span') == 3, "la racha pinta un recuadro por partido")
    for letra in 'GEP':
        check(('>%s<' % letra) in html, "la racha conserva la letra %s" % letra)
    check(mm.racha_html('') == '', "sin racha no se pinta nada")

def test_modo_modelo_esta_enrutado_en_la_interfaz():
    """
    v152 — la pestaña existe, es la primera, y la de precio sigue estando.

    Cambiar el orden de las pestañas es una decision del usuario. Lo que no
    puede pasar es que el cambio se lleve por delante la pantalla que SI tiene
    percentil 5 positivo medido.
    """
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check('import modo_modelo' in src, "el Modo Modelo esta importado")
    check('Modo Modelo' in src, "la pestaña del Modo Modelo existe")
    check('Modo Valor' in src, "la pestaña de Modo Valor existe")
    i_modelo = src.index('\U0001F4CA Modo Modelo')
    i_valor = src.index('\U0001F48E Modo Valor')
    check(i_modelo < i_valor,
          "el Modo Modelo se declara antes que el Modo Valor (es la primera)")
    check('_tab_jugar' in src,
          "la pestaña de la Seccion 1 sigue enrutada")


def test_corners_no_suben_a_seccion1_sin_medicion():
    """
    v152 — el EV de corners no puede entrar en la Seccion 1 hoy, y por que.

    Medido con los lambdas de PRODUCCION (que es como habia que medirlo, y no
    como lo midio la v146) sobre 15 competiciones con corners reales: la
    formula `4,0 + 0,25·(lam_h+lam_a)·spx·tpo` tiene un sesgo de nivel pequeño
    —la base 4,0 estaba bien— pero una correlacion con el resultado real de
    ~0,00. Predice el mismo total siempre.

    Un modelo que siempre dice ~10,1 produce EV enormes en cuanto la casa mueve
    su linea a 8,5 u 11,5, y ese EV es integramente error del modelo: la firma
    exacta de `EV_SOSPECHOSO`. Ademas no existe historico de LINEAS de corners
    con el que calcular un p5, asi que la regla de oro del proyecto no se puede
    ni aplicar.

    Y la respuesta a «¿4,0 o 5,3?» resulto ser «ninguna de las dos importa»:
    recalibrar el nivel por liga recupera 0,014 de los 0,375 que la formula
    pierde contra decir siempre la media de la competicion. El 96 % del daño lo
    hace la parte variable, que es ruido. Por eso la formula se sustituyo por la
    media OBSERVADA de la competicion donde la hay.
    """
    import rendimiento_equipos as rq

    src = open('league_engine.py', encoding='utf-8').read()
    check('media_corners_liga' in src,
          "el total de córners sale de la media observada de la competicion")
    check('CK_MEDIA_COMPARABLES' in src,
          "y donde no hay córners observados, de la media de las que si los "
          "publican, no de la formula del xG")

    # La media tiene que existir donde los córners son reales y NO existir
    # donde los escribio el generador. Es la mitad que impide que esto acabe
    # siendo un `mean()` sobre el relleno del propio generador.
    m_premier = rq.media_corners_liga('premier')
    check(m_premier is not None and 7.0 < m_premier < 13.0,
          f"la Premier tiene media de córners observada y es plausible "
          f"({m_premier})")
    check(rq.media_corners_liga('liga_mx') is None,
          "la Liga MX no tiene media observada: sus córners son del generador")

    # El EV de córners sigue marcado como no fiable, y por el motivo medido.
    tab = open('cuotas_tablon.py', encoding='utf-8').read()
    check("ev_no_fiable'] = True" in tab and 'Córners' in tab,
          "el EV de los córners sigue marcado como no fiable")
    # QUE EL MOTIVO QUE VE EL USUARIO SEA EL MEDIDO, y se comprueba sobre el
    # texto EMITIDO, no sobre el fuente.
    #
    # La primera version de este check buscaba en el fichero la frase vieja
    # («la discriminacion si parece buena») y fallaba, porque el comentario
    # nuevo la CITA justo para explicar por que era falsa. Un test que busca
    # prosa no distingue una afirmacion de su desmentido; el que mira lo que
    # sale por la salida, si.
    # Se saca del AST, no del texto del fichero: el motivo esta escrito como
    # varios literales adyacentes en lineas distintas, asi que «media de la
    # competicion» NO aparece seguido en el fuente aunque si en la cadena. El
    # parser ya los concatena, de modo que el AST tiene el texto que ve el
    # usuario. Buscarlo en el fuente daba un falso negativo.
    import ast as _ast
    cadenas = [n.value for n in _ast.walk(_ast.parse(tab))
               if isinstance(n, _ast.Constant) and isinstance(n.value, str)]
    motivos = [c for c in cadenas if 'córners' in c and 'EV' in c]
    check(any('media de la competición' in c for c in motivos),
          "el motivo que se enseña dice que el modelo predice la media de la "
          "competicion")
    check(any('no valor' in c for c in motivos),
          "y deja claro que ese EV no mide valor")

    import clasificador
    canales_s1 = {'precio_local', 'precio_nfl', 'tenis_90'}
    # `canal_del_pick` es la puerta de la Seccion 1 del dia: ningun pick de
    # córners puede salir de ella con seccion 1.
    pick = {'deporte': 'Fútbol', 'mercado': 'Más de 9.5 córners',
            'apuesta': 'Más de 9.5 córners', 'prob': 0.62, 'cuota': 1.9,
            'valor_mercado': False}
    r = clasificador.canal_del_pick(pick)
    check(r.get('seccion') == 2,
          "un pick de córners por EV del modelo se queda en la Seccion 2")
    check(r.get('canal') not in canales_s1,
          "y no usa ninguno de los canales medidos con p5 positivo")


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
    print('\n=== v101: aprendizaje autónomo y fuga de features ===')
    test_proximos_partidos_todas_las_competiciones()
    test_aprendizaje_continuo()
    test_features_del_modelo_coinciden()
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
    test_guardias_del_emparejador()                      # v114
    test_exchange_matchbook()                            # v114
    test_tablon_a_mercados()                             # v114
    test_selecciones_completas()                         # v114
    test_bf_por_apertura()                               # v115
    test_lineas_alternativas()                           # v115
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
    print('\n=== v88: MLB limpio, sin Odds API, 24 h y Telegram ===')
    test_solo_mlb_en_el_tablon_de_mlb()
    test_sin_the_odds_api()
    test_ventana_24h()
    test_telegram_no_rehace_el_barrido()
    print('\n=== v97: ITF en vivo, KBO y Leagues Cup ===')
    test_itf_fuente_viva()
    test_kbo_integrada()
    test_leagues_cup_integrada()
    print('\n=== v96: el circuito ITF tiene datos y modelo ===')
    test_itf_tiene_datos_y_modelo()
    print('\n=== v95: fecha en el origen y mensajes sin jerga ===')
    test_fecha_normalizada_en_el_origen()
    test_mensajes_sin_jerga_interna()
    print('\n=== v94: tenis con dos fuentes y reentrenamiento multideporte ===')
    test_tenis_dos_fuentes_y_sets()
    test_reentrenamiento_multideporte()
    print('\n=== v93: probabilidad calibrada y recalibración automática ===')
    test_pick_por_probabilidad_calibrada()
    test_recalibracion_automatica()
    print('\n=== v92: circuito de liquidación ===')
    test_circuito_de_liquidacion()
    print('\n=== v91: un solo reloj ===')
    test_un_solo_reloj()
    print('\n=== v90: totales por casa y techo por liga ===')
    test_totales_conservan_su_casa()
    test_techo_por_liga_estable()
    print('\n=== v106: hándicap con push, hora de CDMX y EV+ multideporte ===')
    test_handicap_con_push()
    test_hora_cdmx()
    test_ev_automatico_en_todos_los_deportes()
    test_panel_equipos()
    test_roi_negativo_se_avisa_de_frente()
    test_cobertura_remates_medida()
    print('\n=== v110: ruido de producción y codificación ===')
    test_unibet_quinta_casa()
    test_sin_bom_en_el_codigo()
    test_ruido_de_produccion()
    test_ninguna_liga_activa_sin_modelo()
    test_motores_de_deporte_cargan()
    test_beisbol_pitchers()
    test_handicap_en_todas_las_ligas()
    print('\n=== v122: la casa del usuario y la capa visual ===')
    test_tablero_playdoit()
    test_playdoit_no_inventa_mercados()
    test_patas_llevan_su_id()
    test_combinada_de_una_sola_casa()
    test_capa_visual_no_rompe()
    test_la_interfaz_usa_la_capa_visual()
    print('\n=== v123: estadísticas del cruce, tiempos y juegos ===')
    test_empate_recibe_su_precio()
    test_tiempos_con_precio_pero_sin_ev()
    test_h2h_trae_corners_y_tarjetas()
    test_juegos_de_tenis()
    test_partido_parejo()
    test_selectores_de_partido_con_clave_estable()
    print('\n=== v124: Telegram y bitácora de arquitectura ===')
    test_telegram_envia_picks_y_ponches()
    test_bitacora_de_arquitectura()
    print('\n=== v125: clasificador de tres secciones ===')
    test_clasificador_tres_secciones()
    test_sufijo_de_estado_no_confunde_clubes()
    test_consenso_de_varias_casas()
    print('\n=== v126: regla del tenis y barrido de casas ===')
    test_regla_tenis_90()
    test_sondeo_de_casas()
    test_consenso_api_respeta_el_presupuesto()
    test_consenso_api_degrada_en_silencio()
    test_la_ficha_pide_las_cuotas_con_liga()
    print('\n=== v131: NFL ===')
    test_nfl_mapeo_de_nombres()
    test_nfl_abreviaturas_no_chocan_con_mlb()
    test_nfl_mercados_no_se_inventan()
    test_nfl_probabilidades_coherentes()
    test_nfl_sin_fuga_temporal()
    test_nfl_no_sube_a_seccion1_sin_medicion()
    test_nfl_en_el_barrido_y_la_interfaz()
    print('\n=== v150: el fallback de mercado se delata ===')
    test_el_fallback_de_mercado_se_delata()
    test_ningun_test_se_queda_sin_ejecutar()
    # v150 — estaba DEFINIDO y no se llamaba desde ninguna parte, así que
    # llevaba pasando sin ejecutarse. Lo destapó la auditoría de huérfanos que
    # se añade justo debajo.
    test_metricas_con_procedencia()
    print('\n=== v152: Modo Modelo, rendimiento observado y córners ===')
    test_no_se_ensena_estadistica_sintetica()
    test_rendimiento_no_rellena_lo_que_falta()
    test_modo_modelo_no_tapa_los_huecos_con_el_mercado()
    test_modo_modelo_separa_ligas_secundarias()
    test_el_bot_guarda_los_datos_antes_de_lo_lento()
    test_solo_se_republica_lo_que_cambio()
    test_no_se_reentrena_una_liga_sin_partidos_nuevos()
    test_el_precalculo_no_cambia_ni_un_numero()
    test_los_except_pueden_registrar_su_error()
    test_la_apuesta_destacada_de_cada_partido()
    test_modo_modelo_esta_enrutado_en_la_interfaz()
    test_corners_no_suben_a_seccion1_sin_medicion()
    print(f"\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    for f in FALLOS:
        print('  - ' + f)
    sys.exit(1 if FALLOS else 0)
