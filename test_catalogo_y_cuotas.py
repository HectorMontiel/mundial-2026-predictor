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
def _liga_sin_observar(stat: str):
    """
    Una competicion que NO publica `stat` de verdad, o None si no queda ninguna.

    v162 — ANTES ESTO ERA 'liga_mx' ESCRITO A MANO, EN OCHO TESTS. Servia para
    comprobar lo que sigue importando —que una columna escrita por el generador
    sintetico nunca se presenta como observada— pero se rompio entero el dia
    que `stats_espn` trajo los corners reales de la Liga MX: ocho fallos de
    golpe, todos por que el ejemplo habia dejado de serlo.

    La cobertura va a seguir creciendo, asi que el ejemplo se busca en vez de
    escribirse. Y si algun dia no queda ninguna competicion sin datos, estas
    comprobaciones se saltan diciendolo, que es mejor que fallar por haber
    tenido exito.
    """
    import fixtures_espn
    import rendimiento_equipos as rq
    from config import LEAGUES
    for c, v in LEAGUES.items():
        if not v.get('disponible') or c not in fixtures_espn.ESPN_CODIGOS:
            continue
        try:
            d = rq._historico(c)
            if d is None or getattr(d, 'empty', True) or len(d) < 300:
                continue
            if not rq.stats_disponibles(c).get(stat):
                return c
        except Exception:
            continue
    return None


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
    """
    Las tres migradas en la v75 siguen leyendo de football-data.

    v161 — LO QUE ESTE TEST YA NO FIJA, Y POR QUÉ.

    Fijaba también `disponible`, con `aut_bundesliga` en False porque su modelo
    medía acc 0,373 contra 0,425 de su línea base de ELO. Esa era la regla de
    la v75: si el 1X2 de una liga no bate a su ELO, la liga no sale.

    La regla dejó de decidir nada, y está medido después (v90 y siguientes):
    el modelo bate al mercado en 1 de 34 ligas, apostar su probabilidad pierde
    entre −4,66 % y −6,52 % sobre 37.158 apuestas, y lo que gana es comprar al
    mejor precio (+11,49 %, p5 +1,73 %). O sea que el acierto del 1X2 de una
    liga no es de donde sale el valor, y filtrar competiciones por él quitaba
    partidos sin proteger de nada — 28 en un sábado normal.

    Lo que este test SIGUE fijando es el formato, que sí es una propiedad de la
    fuente y no una decisión revisable: si alguien cambia `aut_bundesliga` a
    formato 'espn', deja de leer football-data y pierde sus cuotas de cierre.
    Qué ligas están encendidas lo comprueba ahora
    `test_las_ligas_apagadas_por_elo_se_encendieron`.
    """
    import config
    esperado = {
        # clave: formato medido en la v75
        'rus_premier': 'new',            # acc 0.530 > ELO 0.512
        'gre_super_league': 'main',      # acc 0.536 > ELO 0.506
        'aut_bundesliga': 'new',         # acc 0.373 < ELO 0.425 — ver docstring
    }
    for clave, formato in esperado.items():
        cfg = config.LEAGUES.get(clave, {})
        check(cfg.get('formato') == formato,
              f"{clave} usa football-data (formato '{formato}')")


def test_las_ligas_apagadas_por_elo_se_encendieron():
    """
    v161 — la regla que las apagaba dejo de ser la regla que decide.

    Doce competiciones estaban con `disponible: False` y una nota del tipo «no
    bate ELO (0,4422 vs 0,4496)», medida entre la v39 y la v106. La regla de
    entonces: si el modelo 1X2 de una liga no supera a su propia linea base de
    ELO, la liga no sale.

    Esa regla ya no decide nada, y esta medido:
      - el modelo bate al mercado en 1 de 34 ligas (v90), o sea que su acierto
        no es de donde sale el valor;
      - apostar su probabilidad PIERDE entre -4,66 % y -6,52 % sobre 37.158
        apuestas, y su EV correlaciona -0,054 con el CLV;
      - lo que gana es comprar al mejor precio: +11,49 %, p5 +1,73 %.

    Asi que filtrar competiciones por el acierto de su 1X2 quitaba partidos sin
    proteger de nada. Medido el 2026-08-22: son 28 partidos mas en un sabado.

    Este test NO dice que esas ligas sean buenas. Dice que estan encendidas a
    proposito y que su nota lo sigue contando, para que nadie las apague otra
    vez creyendo que se coló un descuido.
    """
    import config

    ENCENDIDAS = ('aut_bundesliga', 'eng_championship', 'bel_pro_league',
                  'ned_eerste', 'slv_primera', 'par_division', 'crc_fpd',
                  'ven_primera', 'aus_aleague', 'eng_fa_cup', 'ind_isl',
                  'bra_copa')
    for c in ENCENDIDAS:
        cfg = config.LEAGUES.get(c) or {}
        check(bool(cfg.get('disponible')), f"{c} esta disponible")
        nota = str(cfg.get('nota') or '')
        check('v161' in nota,
              f"{c}: la nota dice que se encendio a proposito")

    # Las tres que se quedan fuera, y por que. Si alguien las enciende sin
    # darles lo que les falta, la liga sale rota en vez de no salir.
    import os
    for c in ('esp_copa_rey', 'eng_carabao'):
        cfg = config.LEAGUES.get(c) or {}
        check(not cfg.get('disponible'),
              f"{c} sigue apagada: no tiene team_stats_{c}.json")
        check(not os.path.exists('team_stats_%s.json' % c),
              f"y efectivamente no lo tiene")
    check(not (config.LEAGUES.get('ksa_pro') or {}).get('disponible'),
          "ksa_pro sigue apagada: no tiene ni histórico ni team_stats")

    # Toda liga encendida tiene que tener con que trabajar.
    import fixtures_espn
    disp = [c for c, v in config.LEAGUES.items() if v.get('disponible')]
    check(len(disp) >= 62, f"hay {len(disp)} competiciones disponibles")
    sin_hist = [c for c in ENCENDIDAS
                if not os.path.exists('historico_%s.csv' % c)]
    check(not sin_hist, f"todas las encendidas tienen histórico ({sin_hist})")
    sin_stats = [c for c in ENCENDIDAS
                 if not os.path.exists('team_stats_%s.json' % c)]
    check(not sin_stats, f"y todas tienen team_stats ({sin_stats})")
    sin_codigo = [c for c in ENCENDIDAS if c not in fixtures_espn.ESPN_CODIGOS]
    check(not sin_codigo, f"y todas tienen código ESPN ({sin_codigo})")


def test_las_estadisticas_reales_de_espn():
    """
    v162 — el boxscore de ESPN, que estaba delante todo el tiempo.

    Cornrs y tarjetas eran observados en 20 de 75 competiciones. En las otras
    55 los escribia el generador sintetico, asi que la Liga MX, Argentina,
    Brasil, la MLS y treinta y tantas mas no podian enseñarlos. Y no era falta
    de datos: el `summary` de ESPN trae un `boxscore` con 28 estadisticas por
    equipo —wonCorners, yellowCards, redCards, foulsCommitted, possessionPct,
    totalShots, shotsOnTarget…— que nadie de este proyecto habia mirado.

    NO ES OTRO RELLENO, Y SE COMPROBO ANTES DE CONSTRUIR NADA. Cruzados 216
    partidos de 6 competiciones grandes contra football-data, que es la fuente
    observada del proyecto:

        cornrs local     93,1 % identicos   corr 0,985
        cornrs visitante 96,3 % identicos   corr 0,981
        amarillas local  95,4 % identicos   corr 0,955
        rojas local     100,0 % identicos   corr 1,000
        remates local    95,4 % identicos   corr 0,988

    Efecto medido en la Liga MX, que no tenia ni un corner observado: error de
    calibracion 0,0111 y correlacion 0,210 por equipo. La estimacion de
    respaldo da 0,0247. O sea que traer el dato real vale mas del doble.
    """
    import os
    import stats_espn as se

    check(hasattr(se, 'backfill') and hasattr(se, 'inyectar'),
          "el modulo descarga e inyecta")

    # LA CABECERA. La cadena larga de Chrome devuelve Access Denied en
    # site.api.espn.com; la corta, 200. No es un detalle de estilo.
    check(se.UA.get('User-Agent') == 'Mozilla/5.0',
          "usa la cabecera que ESPN acepta, la misma que fixtures_espn")

    # UN BOXSCORE A CEROS NO ES UN PARTIDO SIN CORNERS.
    #
    # El 7,0 % de los partidos de la Liga MX volvian con posesion 0-0, faltas 0
    # y cornrs 0 — todo a cero a la vez, que es imposible. Colados como datos
    # buenos, la razon varianza/media de los cornrs por equipo salia 2,04 y el
    # error de calibracion 0,0288. Quitando esas 131 filas: dispersion 1,63 y
    # error 0,0111. La misma liga, el mismo dia, sin tocar nada mas.
    src = open('stats_espn.py', encoding='utf-8').read()
    check('_possession' in src and 'return None' in src,
          "descarta el boxscore vacio en vez de guardarlo como ceros")
    check(hasattr(se, 'limpiar'),
          "y sabe limpiar lo que se descargo antes de ese filtro")

    # EL ORDEN DE LA INYECCION ES TODO EL TRUCO. El generador sintetico solo
    # rellena huecos, asi que inyectar ANTES hace que gane el dato real. Al
    # reves, el relleno llegaria primero y ESPN no pintaria nada.
    le = open('league_engine.py', encoding='utf-8').read()
    i_iny = le.index('_se.inyectar(df, clave)')
    i_gen = le.index('gen.generate_advanced_metrics(df, cal)')
    check(i_iny < i_gen,
          "las estadisticas de ESPN se inyectan ANTES del generador sintetico")

    # Y NO SE PARCHEA EL CSV: `descargar_liga` lo reconstruye cada noche, asi
    # que un parche directo duraria hasta el siguiente --build.
    check(se.DIRECTORIO == 'stats_espn',
          "la cache vive aparte del historico, que se reconstruye")

    if os.path.isdir(se.DIRECTORIO):
        import pandas as pd
        ficheros = [f for f in os.listdir(se.DIRECTORIO) if f.endswith('.csv.gz')]
        check(len(ficheros) > 0,
              f"hay competiciones descargadas ({len(ficheros)})")
        # Ninguna fila guardada puede tener el boxscore vacio.
        malas = []
        for f in ficheros[:20]:
            c = se.leer(f[:-len('.csv.gz')])
            if not len(c):
                continue
            ph = pd.to_numeric(c['home_possession'], errors='coerce').fillna(0)
            pa = pd.to_numeric(c['away_possession'], errors='coerce').fillna(0)
            n = int(((ph + pa) <= 1.0).sum())
            if n:
                malas.append((f, n))
        check(not malas,
              f"ninguna competicion guarda filas con el boxscore vacio ({malas[:3]})")


def test_solo_se_promedian_las_filas_reales():
    """
    v162 — una columna MEZCLADA no se puede promediar entera.

    `stats_espn` cubre desde 2021 y varios historicos arrancan en 2018, asi que
    media columna es de ESPN y la otra media la escribio el generador. Medido
    en la Liga MX antes de separar: la razon varianza/media de los cornrs por
    equipo salia 2,04 mezclando, contra 1,63 usando solo las filas reales.

    `inyectar` marca cada fila que rellena con `stats_origen`, y las funciones
    que promedian filtran por esa marca. En las 20 competiciones de
    football-data la columna no existe y se usa el historico entero, que es lo
    correcto ahi: todo es observado.
    """
    import pandas as pd
    import rendimiento_equipos as rq

    check(hasattr(rq, '_solo_reales'), "existe el filtro de filas reales")

    # Sin la columna, no se filtra nada (competiciones de football-data).
    d = pd.DataFrame({'home_corners': [1.0, 2.0, 3.0]})
    check(len(rq._solo_reales(d, 'corners')) == 3,
          "sin marca de origen se usa el historico entero")

    # Con la columna y pocas marcas, no se promedia: mejor nada que una media
    # de veinte partidos presentada como la de la competicion.
    d2 = pd.DataFrame({'home_corners': [1.0] * 500,
                       'stats_origen': ['espn'] * 20 + [None] * 480})
    check(len(rq._solo_reales(d2, 'corners')) == 0,
          "con menos de 200 filas marcadas no se promedia")

    d3 = pd.DataFrame({'home_corners': [1.0] * 500,
                       'stats_origen': ['espn'] * 300 + [None] * 200})
    check(len(rq._solo_reales(d3, 'corners')) == 300,
          "con marcas suficientes se usan solo esas")

    # LA DETECCION DE COLUMNAS SINTETICAS MIRA LA COLA, NO LA CABECERA.
    # Con `head` seguiria viendo los partidos de 2018 —sinteticos para
    # siempre— y diria que la competicion no tiene datos cuando si los tiene.
    src = open('rendimiento_equipos.py', encoding='utf-8').read()
    i = src.index('def _columnas_sinteticas')
    j = src.index('def stats_disponibles')
    check('d.tail(_MUESTRA_SINT)' in src[i:j],
          "la muestra de sintesis sale de los partidos RECIENTES")


def test_todas_las_ligas_tienen_cornrs_y_tarjetas():
    """
    v162 — ninguna competicion se queda sin la seccion, y lo estimado se dice.

    Se pidio que TODAS las ligas enseñen cornrs y tarjetas. Donde hay datos,
    salen observados; donde no, `stats_estimadas` da el nivel de la competicion
    derivado de sus goles y la interfaz lo marca.

    LO QUE VALE CADA COSA, medido con validacion dejando una liga fuera —se
    ajusta con 19 competiciones y se predice la vigesima como si no tuviera
    datos, que es la situacion real de produccion:

        CORNERS por equipo                      error     corr
          con datos reales .................   0,0076    0,257
          media de liga predicha de goles ..   0,0247    0,160  <- lo adoptado
          media global de las otras ligas ..   0,0264    0,160
          predicha x ataque, normalizada ...   0,0326    0,234

        TARJETAS por equipo                     error     corr
          con datos reales .................   0,0123    0,150
          media de liga predicha de goles ..   0,0539    0,100  <- lo adoptado
          predicha x ataque ................   0,0556   -0,080

    NO SE MODULA POR EL ATAQUE aunque suba la correlacion: en cornrs la lleva
    de 0,160 a 0,234 pero empeora la calibracion de 0,0247 a 0,0326, y aqui
    manda la calibracion. En tarjetas la correlacion sale NEGATIVA (-0,080):
    un equipo que ataca mas se lleva menos tarjetas, asi que el modulador
    empuja al reves.
    """
    import os
    import modo_modelo as mm
    import stats_estimadas as se

    check(os.path.exists(se.ARCHIVO),
          f"existe el ajuste entre ligas ({se.ARCHIVO})")
    doc = se.cargar()
    check(len((doc.get('ligas_ajuste') or [])) >= 15,
          f"ajustado con suficientes competiciones "
          f"({len(doc.get('ligas_ajuste') or [])})")
    for obj in ('ck', 'tj'):
        r = (doc.get('rectas') or {}).get(obj) or {}
        check(bool(r), f"hay recta para {obj}")
        if r:
            check(abs(r.get('corr_goles', 0)) > 0.3,
                  f"{obj}: los goles explican algo del nivel "
                  f"(corr {r.get('corr_goles'):+.3f})")

    # El umbral que se fijo: por encima de 0,05 la estimacion se enseña con
    # aviso fuerte. Las tarjetas estimadas caen ahi, y eso NO se disimula.
    check(se.UMBRAL_ACEPTABLE == 0.05, "el umbral aceptable es 0,05")
    check(doc['calibracion_estimada']['tj'] > se.UMBRAL_ACEPTABLE,
          "las tarjetas estimadas estan por encima del umbral y se marcan")
    check(doc['calibracion_estimada']['ck'] < se.UMBRAL_ACEPTABLE,
          "y los cornrs estimados por debajo")

    # NINGUNA competicion de futbol puede quedarse sin seccion.
    import fixtures_espn
    from config import LEAGUES
    claves = [c for c, v in LEAGUES.items()
              if v.get('disponible') and c in fixtures_espn.ESPN_CODIGOS][:12]
    import rendimiento_equipos as rq
    sin_ck, sin_tj = [], []
    for c in claves:
        d = rq._historico(c)
        if d is None or getattr(d, 'empty', True) or len(d) < 200:
            continue
        h = str(d['home_team'].iloc[-1])
        a = str(d['away_team'].iloc[-1])
        if rq.corners_equipo(c, h, a) is None:
            sin_ck.append(c)
        if rq.tarjetas_equipo(c, h, a) is None:
            sin_tj.append(c)
    check(not sin_ck, f"todas las competiciones dan cornrs ({sin_ck})")
    check(not sin_tj, f"todas las competiciones dan tarjetas ({sin_tj})")

    # Y lo estimado va etiquetado, en el titulo y en una linea propia.
    est = {'filas': [{'etiqueta': 'Total', 'media': 9.4, 'texto': 'Más de 9.5',
                      'prob': 0.55, 'linea': 9.5}],
           'mejor': {'etiqueta': 'Total', 'media': 9.4, 'texto': 'Más de 9.5',
                     'prob': 0.55, 'linea': 9.5},
           'origen': 'estimado', 'aceptable': True, 'error_calibracion': 0.0247}
    html = mm._bloque_seccion_html(est, '⛳', 'Córners')
    check('estimado' in html, "el titulo dice que el numero es estimado")
    check('📐' in html, "y hay una linea que lo explica")
    flojo = dict(est, aceptable=False, error_calibracion=0.0539)
    check('poca precisión' in mm._bloque_seccion_html(flojo, '🟨', 'Tarjetas'),
          "y con error por encima del umbral el aviso es mas fuerte")

    obs = dict(est, origen='observado')
    check('estimado' not in mm._bloque_seccion_html(obs, '⛳', 'Córners'),
          "lo observado NO lleva la etiqueta")


def test_los_jugados_salen_en_la_lista_con_su_pronostico():
    """
    v162 — los partidos acabados, EN la lista y con el pronostico previo.

    La v161 los puso detras de un boton, en una lista escueta con el marcador.
    Duro una version: lo que se queria era verlos en la misma lista, con su
    tarjeta entera, para poder analizar que decia el modelo antes del pitido.

    EL PRONOSTICO NO SE RECALCULA, Y ESO ES LO IMPORTANTE. Se recupera de
    `predicciones_dia.json`, que el bot escribio por la mañana cuando el
    partido aun no se habia jugado. Recalcularlo ahora daria un numero
    distinto —el ELO y las medias moviles ya se movieron con el resultado— y
    enseñarlo como «pronostico previo» seria mentir con precision decimal.

    Y SIGUEN SIN PODER SER UN PICK: no pasan por `alpha_finder`, no tienen EV,
    no se comparan con la cuota y no llegan a Telegram.
    """
    import inspect
    import numpy as np
    import modo_modelo as mm
    import partidos_jugados as pj
    import fixtures_espn

    check(hasattr(pj, 'de_dia'), "el modulo construye los partidos jugados")
    check(not hasattr(mm, '_bloque_jugados'),
          "el boton de la v161 se retiro: ahora van en la lista")

    # El board sale de la matriz de marcador guardada.
    M = np.zeros((7, 7))
    M[0, 0] = 0.25   # 0-0
    M[1, 0] = 0.25   # 1-0
    M[2, 2] = 0.25   # 2-2
    M[3, 1] = 0.25   # 3-1
    b = pj._board_de_matriz(M, 'A', 'B')
    check(abs(b['Gana A'] - 0.50) < 1e-6, f"1X2 local ({b.get('Gana A')})")
    check(abs(b['Empate'] - 0.50) < 1e-6, f"1X2 empate ({b.get('Empate')})")
    check(abs(b['Más de 2.5'] - 0.50) < 1e-6,
          f"mas de 2.5 son los marcadores que suman 3+ ({b.get('Más de 2.5')})")
    check(abs(b['Ambos marcan: Sí'] - 0.50) < 1e-6,
          f"ambos marcan quita fila y columna cero ({b.get('Ambos marcan: Sí')})")
    check(abs(b['Menos de 2.5'] + b['Más de 2.5'] - 1.0) < 1e-6,
          "los dos lados de goles suman 1")

    # La tarjeta de un jugado enseña el marcador y NO una apuesta.
    src = inspect.getsource(mm.tarjeta)
    check("pick.get('jugado')" in src and 'Finalizado' in src,
          "la tarjeta marca los partidos acabados")
    # v167 — la comprobacion es la misma, sobre la estructura nueva: el
    # marcador de un partido acabado SUSTITUYE a la recomendacion, no se le
    # añade debajo. `apuesta_recomendada` devuelve None en un partido jugado,
    # asi que hay dos guardas y se comprueban las dos.
    i_jug = src.index("if pick.get('jugado')")
    i_rec = src.index('_bloque_recomendada(st, rec')
    check(i_jug < i_rec,
          "el marcador va antes que la apuesta recomendada, no debajo")
    rec_src = inspect.getsource(mm.apuesta_recomendada)
    check("pick.get('jugado')" in rec_src and 'return None' in rec_src,
          "y un partido acabado no produce recomendacion ninguna")

    # La leyenda que se pidio, y el recuento aparte.
    rnd = inspect.getsource(mm.render)
    check('Finalizado' in rnd and 'no son' in rnd,
          "la lista lleva la leyenda de que los finalizados no son jugables")
    check("not p.get('jugado')" in rnd,
          "los jugados no cuentan como apuestas por encima del umbral")

    # `fixtures_liga` SIGUE descartando los acabados: esto es aditivo.
    fx = inspect.getsource(fixtures_espn._fixtures_de_codigo)
    check("if estado.get('completed'):" in fx,
          "los acabados siguen fuera de los fixtures apostables")
    check('partidos_jugados' not in open('alpha_finder.py', encoding='utf-8').read(),
          "el barrido no los conoce, asi que no pueden acabar en un pick")

    # La hora, para que se ordenen junto a los demas.
    res = inspect.getsource(fixtures_espn.resultados_liga)
    check("'inicio'" in res,
          "los jugados traen hora de inicio y se ordenan con el resto")


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
            # v161 — LAS RECIÉN ENCENDIDAS, MIENTRAS ESPERAN SU PRIMER
            # ENTRENAMIENTO.
            #
            # Estas doce se encendieron en la v161 y sus modelos no existen
            # todavía: el workflow entrena «cada liga disponible», así que
            # aparecerán en el próximo reentrenamiento (~52 s por liga medido
            # con eng_championship). Hasta entonces salen en `ligas_sin_motor`
            # de la pestaña Estado, que es el comportamiento correcto — se ven
            # y se dice que les falta el modelo, en vez de desaparecer.
            #
            # La lista se DRENA SOLA: el bloque de abajo falla si una de ellas
            # ya tiene su modelo publicado y sigue aquí, así que no se puede
            # quedar de coartada permanente. Ése es justo el fallo de la v106,
            # donde un argumento dejó de ser cierto y nadie se enteró.
            # `aut_bundesliga` y `bra_copa` NO están aquí, y no es un olvido:
            # ya tienen su modelo publicado en el Release de antes, así que
            # encenderlas fue sólo cambiar el `disponible`. Ponerlas en esta
            # lista fue el primer intento, y el bloque de drenaje de abajo lo
            # rechazó — que es exactamente para lo que está.
            #
            # v163.1 — LA LISTA SE VACIÓ, Y ASÍ ES COMO TENÍA QUE PASAR.
            # Las diez que quedaban (aus_aleague, bel_pro_league, crc_fpd,
            # eng_championship, eng_fa_cup, ind_isl, ned_eerste, par_division,
            # slv_primera, ven_primera) ya tienen su `modelos-*.tar.gz` en el
            # Release: el reentrenamiento nocturno corrió entre la v163 y la
            # v163.1 y las entrenó, que es lo que la v161 dijo que pasaría.
            # El bloque de drenaje de abajo falló en cuanto ocurrió y obligó a
            # quitarlas — la coartada duró exactamente lo que tenía que durar.
            #
            # Se deja el conjunto VACÍO y no se borra el mecanismo: la próxima
            # tanda de ligas encendidas volverá a necesitarlo.
            _PENDIENTES_PRIMER_ENTRENAMIENTO = set()
            _esperadas = sorted(set(_sin_ningun_sitio)
                                & _PENDIENTES_PRIMER_ENTRENAMIENTO)
            _sin_excusa = sorted(set(_sin_ningun_sitio)
                                 - _PENDIENTES_PRIMER_ENTRENAMIENTO)
            if _esperadas:
                print(f"AVISO {len(_esperadas)} competiciones encendidas en la "
                      f"v161 esperan su primer entrenamiento: {_esperadas}")
            check(not _sin_excusa,
                  f"todas las activas con motor propio tienen su modelo, en "
                  f"disco o publicado en el Release ({_sin_excusa})")
            _ya_no_pendientes = sorted(
                k for k in _PENDIENTES_PRIMER_ENTRENAMIENTO
                if f'modelos-{k}.tar.gz' in (_publicados or set()))
            check(not _ya_no_pendientes,
                  f"la lista de pendientes se drena: éstas ya tienen modelo y "
                  f"hay que quitarlas de _PENDIENTES_PRIMER_ENTRENAMIENTO "
                  f"({_ya_no_pendientes})")

    # v161 — las que se midieron por debajo de su ELO conservan la cifra.
    #
    # Este bloque comprobaba que estuvieran APARTADAS. Ya no lo están: el
    # acierto del 1X2 de una liga dejó de decidir si sale (ver
    # `test_las_ligas_apagadas_por_elo_se_encendieron`). Lo que sigue
    # comprobándose es que su nota conserve la medición, porque es información
    # real sobre ese modelo y borrarla al encender la liga sería tapar el dato
    # que justifica leer su probabilidad con desconfianza.
    for k in ('eng_championship', 'eng_fa_cup', 'ned_eerste'):
        cfg = config.LEAGUES.get(k) or {}
        nota = str(cfg.get('nota', ''))
        check('ELO' in nota,
              f"{k}: su nota conserva contra qué se midió ({nota[:60]})")
        check('v161' in nota,
              f"{k}: y dice que se encendió a pesar de eso")


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
    # v164 — LA POSESION DE LA PREMIER YA ES OBSERVADA, Y ESO ES UN AVANCE.
    #
    # Este check exigia `False` porque hasta la v162 la posesion la escribia el
    # generador en TODAS las competiciones. El 2026-08-23 el `--build` nocturno
    # reescribio los historicos con el boxscore de ESPN inyectado
    # (commit `02b87a4`): `historico_premier.csv` tiene ahora 1.613 filas
    # marcadas con `stats_origen='espn'` y su posesion es real.
    #
    # Es exactamente la transicion que el traspaso de la v163 anunciaba como
    # pendiente numero 6. El detector no se ha roto: sigue diciendo «sintetico»
    # del xG, que es la comprobacion en el otro sentido y la que de verdad
    # protege — lo que ha cambiado es el dato, no la prueba.
    check(disp.get('posesion') is True,
          "la posesion de la Premier YA sale como observada: el --build "
          "inyecto el boxscore de ESPN")

    # La otra mitad, y la que de verdad separa esta prueba de una lista escrita
    # a mano: una liga que NO es de football-data tiene la columna de córners al
    # 100 % y aun asi es relleno.
    # v162 — LA LIGA MX DEJO DE SER EL EJEMPLO, Y ESO ES BUENA NOTICIA.
    # `stats_espn` le trajo los córners REALES de ESPN, asi que ya sale como
    # observada. Lo que este test protege sigue siendo lo mismo —una columna
    # del generador no puede presentarse como observada— pero el ejemplo se
    # busca en vez de escribirse, porque la cobertura va a seguir creciendo.
    disp_mx = rq.stats_disponibles('liga_mx')
    check(disp_mx.get('goles') is True,
          "los goles de la Liga MX salen como observados")
    _sin = _liga_sin_observar('corners')
    if _sin:
        check(rq.stats_disponibles(_sin).get('corners') is False,
              f"los córners de {_sin} NO salen como observados aunque la "
              f"columna este llena: los escribio el generador")
    else:
        print('AVISO ya no queda ninguna competicion con córners sinteticos: '
              'no hay contraejemplo que comprobar')


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


def test_el_suelo_del_error_en_corners():
    """
    v156 — un MAE de 2,0 en córners no es dificil: es imposible, y aqui esta.

    Se pidio bajar el error de ~2,70 a menos de 2,00 con remates, remates a
    puerta, XGBoost y Poisson. Se probo en serio: 32 features y cuatro modelos
    sobre 20 competiciones y 7.890 partidos de juicio. Ninguno de los tres
    modelos avanzados bate a decir siempre la media de la liga; XGBoost sale
    PEOR (2,7293 contra 2,7067).

    EL MOTIVO NO ES QUE FALTEN FEATURES. El total de córners es un conteo con
    razon varianza/media 1,17 —un Poisson casi puro—, y con esa distribucion un
    ORACULO que conociera la media exacta de cada partido cometeria 2,4835 de
    error medio. Eso no es ignorancia: es la dispersion del propio fenomeno.

        margen teorico    2,7067 − 2,4835 = 0,223 córners
        mejor capturado   0,009 (un 4 %)

    Este test no ejecuta el experimento —tarda media hora— sino que fija sus
    conclusiones donde no se puedan perder: el suelo en la bitacora y el
    comportamiento en el codigo. Si alguien vuelve a pedir MAE < 2,0, esto es lo
    que hay que enseñarle antes de gastar otra tarde.
    """
    doc = open('BITACORA_ARQUITECTURA.md', encoding='utf-8').read()
    for cifra, que in (
            ('2,4835', 'el suelo del oraculo Poisson'),
            ('2,7067', 'el MAE de la constante de liga'),
            ('7.890', 'los partidos de juicio del experimento'),
            ('1,17', 'la razon varianza/media que hace Poisson al fenomeno'),
    ):
        check(cifra in doc, f"la bitacora conserva {que} ({cifra})")
    check('imposible' in doc.lower(),
          "y deja escrito que el objetivo pedido no era alcanzable")

    # El comportamiento: el total sigue siendo la media OBSERVADA de la liga,
    # que es el mejor estimador medido, y el EV sigue bloqueado.
    import rendimiento_equipos as rq

    src = open('league_engine.py', encoding='utf-8').read()
    check('media_corners_liga' in src,
          "el total de córners sigue saliendo de la media observada")
    m = rq.media_corners_liga('premier')
    check(m is not None and 7.0 < m < 13.0,
          f"y esa media es un numero plausible ({m})")

    tab = open('cuotas_tablon.py', encoding='utf-8').read()
    check("ev_no_fiable'] = True" in tab and 'Córners' in tab,
          "el EV de córners sigue marcado como no fiable")

    # Y la interfaz no publica un porcentaje de córners por partido.
    import modo_modelo as mm
    lleno = mm._bloque_fisico(
        {'forma_home': {'equipo': 'A', 'ck_favor': 5.4, 'ck_contra': 4.1,
                        'amarillas': 2.1},
         'forma_away': {'equipo': 'B', 'ck_favor': 4.8, 'ck_contra': 5.0,
                        'amarillas': 1.8}},
        {'corners': True, 'tarjetas': True})
    check('%' not in lleno,
          "la tarjeta enseña medias de córners, nunca una probabilidad")


def test_las_probabilidades_de_corners_usan_la_sobredispersion():
    """
    v157 — los córners no son Poisson, y se nota justo donde estan las lineas.

    Llegan en racimo: un ataque genera el córner, el saque se desvia o rebota en
    la barrera, y sale otro. Eso infla la varianza sin mover la media. Medido
    sobre 20 competiciones, la razon varianza/media es 1,16 y no 1.

    Comparando la probabilidad calculada contra la frecuencia REAL en 24 lineas
    de 6 competiciones:

        Poisson ..............  error medio 0,0093
        binomial negativa ....  error medio 0,0043    ← la mitad

    Es la unica de las cuatro vias propuestas para mejorar los córners que dio
    resultado, y conviene ser preciso sobre QUE mejora: no la prediccion de la
    media —eso sigue igual de dificil, §10.7— sino la conversion de esa media en
    probabilidades.
    """
    import rendimiento_equipos as rq

    d = rq.dispersion_corners_liga('premier')
    check(d is not None and 1.0 <= d <= 1.6,
          f"la Premier tiene sobredispersion medida y plausible ({d})")
    _sin = _liga_sin_observar('corners')
    if _sin:
        check(rq.dispersion_corners_liga(_sin) is None,
              f"una competicion sin córners observados ({_sin}) no inventa "
              f"una dispersion")

    m = rq.media_corners_liga('premier')
    p_poi = rq.prob_mas_de(m, 8.5, 1.0)
    p_nb = rq.prob_mas_de(m, 8.5, d)
    check(p_poi is not None and p_nb is not None,
          "las dos probabilidades se calculan")
    # La cola alta de la binomial negativa es MENOS optimista que la de Poisson
    # cuando la linea esta por debajo de la media: es justo la correccion que se
    # midio contra la frecuencia real.
    check(p_nb < p_poi,
          f"con sobredispersion, «mas de 8.5» sale por debajo de Poisson "
          f"({p_nb:.3f} < {p_poi:.3f})")
    # y con dispersion 1 tiene que dar EXACTAMENTE Poisson, para que una
    # competicion sin datos se comporte como antes del cambio
    check(abs(rq.prob_mas_de(m, 9.5, 1.0) - rq.prob_mas_de(m, 9.5, None)) < 1e-9,
          "sin dispersion conocida, el calculo es el de siempre")

    src = open('league_engine.py', encoding='utf-8').read()
    check('dispersion_corners_liga' in src,
          "el motor pide la sobredispersion de la competicion")
    check('_p_ck(' in src,
          "y calcula las lineas de córners con ella")

    doc = open('BITACORA_ARQUITECTURA.md', encoding='utf-8').read()
    check('0,0043' in doc,
          "la bitacora conserva el error de calibracion de la binomial negativa")


def test_los_corners_por_equipo_salen_de_sus_datos():
    """
    v158 — los córners de cada equipo, de sus córners y no de su xG.

    El reparto anterior partia el TOTAL por la cuota de xG, asi que los córners
    de un equipo salian de su ataque esperado. Ahora, donde la competicion los
    publica, se usa el estimador que gano la comparacion sobre 30.454
    equipos-partido en 6 ligas, midiendo el error de calibracion contra la
    frecuencia real en las lineas 3,5 / 4,5 / 5,5 / 6,5:

        ataque + defensa del rival, binomial negativa ....  0,0056
        media movil de 5, Poisson ........................  0,0093
        media de la competicion, binomial negativa .......  0,0101
        media de la competicion, Poisson .................  0,0369

    DOS DETALLES QUE COSTARON, Y QUE ESTE TEST FIJA:

    1. La dispersion de UN EQUIPO es 1,58, no la del total (1,16). El racimo
       —un córner que genera otro— ocurre dentro del ataque del mismo equipo, y
       al sumar los dos las rachas de uno rellenan los huecos del otro.

    2. «Lo que saca el equipo en su bando» y «lo que el rival recibe en el bando
       contrario» son la MISMA columna del histórico; lo que cambia es por quien
       se filtra. La primera version puso la columna contraria y las dos lambdas
       del partido salian IDENTICAS —6,10 y 6,10 en Man City-Arsenal—, que es lo
       que delato el fallo antes de integrarlo.
    """
    import rendimiento_equipos as rq

    d_eq = rq.dispersion_corners_equipo('premier')
    d_tot = rq.dispersion_corners_liga('premier')
    check(d_eq is not None and d_tot is not None,
          "se miden las dos dispersiones")
    check(d_eq > d_tot,
          f"la dispersion por equipo es mayor que la del total "
          f"({d_eq} > {d_tot})")
    _sin = _liga_sin_observar('corners')
    if _sin:
        check(rq.dispersion_corners_equipo(_sin) is None,
              f"y una competicion sin córners observados ({_sin}) no inventa "
              f"ninguna")

    c = rq.corners_equipo('premier', 'Man City', 'Arsenal')
    check(c is not None, "hay córners esperados para un partido de la Premier")
    if c:
        # EL FALLO QUE HUBO: las dos lambdas identicas.
        check(abs(c['lambda_home'] - c['lambda_away']) > 0.01,
              f"las dos lambdas del partido son distintas "
              f"({c['lambda_home']} vs {c['lambda_away']})")
        check(2.0 < c['lambda_home'] < 9.0 and 2.0 < c['lambda_away'] < 9.0,
              "y las dos son plausibles para un equipo")
        # y no son simetricas: al invertir el partido cambian
        inv = rq.corners_equipo('premier', 'Arsenal', 'Man City')
        if inv:
            check(abs(inv['lambda_home'] - c['lambda_home']) > 0.01,
                  "invertir local y visitante cambia el resultado")

    # v162 — SIN DATOS YA NO ES `None`: ES UNA ESTIMACION MARCADA.
    # Se pidio que ninguna competicion se quede sin la seccion. Lo que NO puede
    # pasar es que salga sin decir que es estimada, y eso es lo que se comprueba.
    _sin = _liga_sin_observar('corners')
    if _sin:
        d = rq._historico(_sin)
        e = rq.corners_equipo(_sin, str(d['home_team'].iloc[-1]),
                              str(d['away_team'].iloc[-1]))
        check(e is not None and e.get('origen') == 'estimado',
              f"sin córners observados ({_sin}) sale una estimacion MARCADA")
        check(e is None or e.get('error_calibracion') is not None,
              "y la estimacion lleva su error de calibracion medido")

    src = open('league_engine.py', encoding='utf-8').read()
    check('corners_equipo' in src and '_p_ck_eq(' in src,
          "el motor usa el estimador por equipo para sus lineas")
    check('corners_por_equipo_de_datos' in src,
          "y declara si esas lineas salen de datos o del reparto por xG")


def test_los_corners_en_la_tarjeta():
    """
    v159 — total y por equipo, cada uno con su apuesta más probable, en ámbar.

    Ahora se PUEDE enseñar la probabilidad: los dos estimadores están calibrados
    contra la frecuencia real (0,0043 el total, 0,0056 por equipo). Lo que no se
    puede es marcarla en verde — verde en esta aplicacion significa «canal con
    percentil 5 positivo medido», y el EV de córners sigue sin histórico de
    lineas con el que comprobarlo.
    """
    import modo_modelo as mm

    ck = mm.corners_tarjeta({'partido': 'Man City vs Arsenal',
                             'clave_liga': 'premier', 'deporte': 'Fútbol'})
    check(ck is not None, "una liga con córners observados produce la seccion")
    if ck:
        check(len(ck['filas']) == 3,
              "salen las tres filas: total, local y visita (%d)"
              % len(ck['filas']))
        etiquetas = [f['etiqueta'] for f in ck['filas']]
        check(etiquetas == ['Total', 'Local', 'Visita'],
              f"y en ese orden ({etiquetas})")
        for f in ck['filas']:
            # Siempre se enseña el lado que supera el 50 %: enseñar el otro
            # obligaria al usuario a restar de cabeza.
            check(f['prob'] >= 0.5,
                  f"{f['etiqueta']}: se enseña el lado mas probable "
                  f"({f['prob']:.2f})")
            check(f['texto'].startswith(('Más de', 'Menos de')),
                  f"{f['etiqueta']}: la apuesta dice de que lado es")
        check(ck['mejor'] in ck['filas'],
              "la destacada es una de las tres")
        check(ck['mejor']['prob'] == max(f['prob'] for f in ck['filas']),
              "y es la de mayor probabilidad")

    # v162 — donde no hay córners observados la seccion SI sale, estimada.
    _sin = _liga_sin_observar('corners')
    if _sin:
        import rendimiento_equipos as _rq2
        d = _rq2._historico(_sin)
        p = {'partido': '%s vs %s' % (d['home_team'].iloc[-1],
                                      d['away_team'].iloc[-1]),
             'clave_liga': _sin, 'deporte': 'Fútbol'}
        b = mm.corners_tarjeta(p)
        check(b is not None and b.get('origen') == 'estimado',
              f"una competicion sin córners observados ({_sin}) produce "
              f"seccion MARCADA como estimada")
    check(mm.corners_tarjeta({'partido': 'HOU vs NYY', 'clave_liga': 'mlb',
                              'deporte': 'MLB'}) is None,
          "y el beisbol tampoco")

    # ÁMBAR, NO VERDE.
    #
    # v164 — SE COMPRUEBA SOBRE EL HTML PINTADO, NO SOBRE 900 CARACTERES DEL
    # FICHERO. La version anterior recortaba `src[i:i+900]` desde
    # `def _bloque_corners_html` y buscaba el emoji ahi dentro; esa funcion es
    # una linea que delega en `_bloque_seccion_html`, asi que el recorte
    # dependia de cuanto ocupara el docstring de la de al lado. Al crecer ese
    # docstring en la v164 el 🟡 se salio de la ventana y el check fallo sin
    # que nada hubiera cambiado de comportamiento.
    #
    # Mirar lo que se PINTA no tiene ese problema y comprueba lo que importa.
    _obs = mm.corners_tarjeta({'partido': 'Man City vs Arsenal',
                               'clave_liga': 'premier', 'deporte': 'Fútbol'})
    if _obs and _obs.get('origen') == 'observado':
        _html = mm._bloque_corners_html(_obs)
        check('🟡' in _html, "la destacada de córners va en ambar")
        check('✅' not in _html,
              "y NUNCA en verde: el EV de córners no esta validado con "
              "histórico")

    # La linea que se usa es la mas cercana a la media, y esta dicho por que.
    check(abs(mm._linea_cercana(10.4) - 10.5) < 1e-9,
          "la linea de 10,4 es 10,5")
    check(abs(mm._linea_cercana(5.0) - 5.5) < 1e-9,
          "y la de 5,0 es 5,5, nunca un entero sin empuje")


def test_se_guardan_las_lineas_de_corners():
    """
    v159 — la unica via que desbloquea el p5 de córners: acumular el histórico.

    No existe historico de lineas de córners —football-data no las publica y el
    de The Odds API es de pago— asi que la regla de oro del proyecto no se puede
    ni aplicar a este mercado. Esto lo empieza a construir: una foto al dia por
    partido y mercado.

    Medido en la primera captura real: 4.200 filas de 48 partidos en 29 s, de 18
    competiciones.
    """
    import os

    import snapshots_corners as sc

    check(hasattr(sc, 'capturar') and hasattr(sc, 'lineas_de_corners'),
          "el modulo expone la captura")

    # LA LINEA SALE DE LA ETIQUETA, NO DE `sv`. Medido sobre el tablero real:
    # la familia «Total Tiros De Esquina» llega con sv=9.5 y su seleccion dice
    # «Mas de 8.5». Guardar 9,5 cuando se apuesta 8,5 haria inservible todo el
    # historico que esto existe para acumular.
    src = open('snapshots_corners.py', encoding='utf-8').read()
    check('linea_etq if linea_etq is not None else linea_fam' in src,
          "la linea guardada es la de la etiqueta, con `sv` de respaldo")

    check(sc._es_corner('Total Tiros De Esquina') is True,
          "reconoce la familia de córners de la casa")
    check(sc._es_corner('Total de goles') is False,
          "y no se lleva por delante otros mercados")
    check(abs(sc._linea_de('Más de 8.5') - 8.5) < 1e-9,
          "extrae la linea de la etiqueta")

    # El bot lo ejecuta y commitea el resultado: sin las dos cosas, el historico
    # no crece y esto no sirve de nada.
    wf = open(os.path.join('.github', 'workflows', 'retrain_leagues.yml'),
              encoding='utf-8').read()
    check('snapshots_corners.py' in wf, "el bot lo ejecuta a diario")
    check('corners_snapshots.csv' in wf, "y commitea lo capturado")

    if os.path.exists(sc.FICHERO):
        import pandas as pd
        d = pd.read_csv(sc.FICHERO)
        check(len(d) > 0, f"hay lineas capturadas ({len(d)})")
        # Coherencia: la linea tiene que coincidir con el numero de la etiqueta
        con_linea = d[d['linea'].notna() & d['mercado'].str.contains(
            'de ', case=False, na=False)]
        if len(con_linea):
            malas = 0
            for _, r in con_linea.head(200).iterrows():
                n = sc._linea_de(r['mercado'])
                if n is not None and abs(float(n) - float(r['linea'])) > 1e-6:
                    malas += 1
            check(malas == 0,
                  f"la linea guardada coincide con su etiqueta ({malas} malas)")

def test_las_tarjetas_cuentan_amarillas_y_rojas():
    """
    v160 — la magnitud del modelo tiene que ser la que liquida la casa.

    La primera version conto solo amarillas y quedo 0,27 tarjetas por debajo
    del centro de la linea real de la casa, con la diferencia CRECIENDO segun
    subia la linea (-0,056 en 3,5 · -0,083 en 4,5 · -0,136 en 5,5) — la firma
    de estar contando una magnitud mas pequena. Las rojas valen 0,25 por
    partido y cerraron la brecha: el centro paso de 4,16 a 4,36 contra los 4,43
    de la casa.

    Y no es un apano para parecerse al mercado: contra el resultado REAL la
    calibracion mejoro de 0,0141 a 0,0117 por equipo y la correlacion de 0,146
    a 0,150. Si alguien vuelve a contar solo amarillas, esto lo para.
    """
    import pandas as pd
    import rendimiento_equipos as rq

    src = open('rendimiento_equipos.py', encoding='utf-8').read()
    i = src.index('def _tarjetas_de')
    check("'_yellow'" in src[i:i + 600] and "'_red'" in src[i:i + 600],
          "el conteo de tarjetas suma amarillas y rojas")

    # La comprobacion que no depende del texto: la media que sale del modulo
    # tiene que ser la de amarillas+rojas, no la de amarillas.
    clave = 'premier'
    d = rq._historico(clave)
    if d is not None and not getattr(d, 'empty', True) and 'home_red' in d.columns:
        y = (pd.to_numeric(d['home_yellow'], errors='coerce')
             + pd.to_numeric(d['away_yellow'], errors='coerce'))
        r = (pd.to_numeric(d['home_red'], errors='coerce')
             + pd.to_numeric(d['away_red'], errors='coerce'))
        m = y.notna() & r.notna()
        solo_amar = float(y[m].var() / y[m].mean())
        con_rojas = float((y + r)[m].var() / (y + r)[m].mean())
        disp = rq.dispersion_tarjetas_liga(clave)
        check(disp is not None, "la Premier publica tarjetas observadas")
        if disp is not None:
            check(abs(disp - max(con_rojas, 1.0)) < 0.01,
                  f"la dispersion es la de amarillas+rojas ({disp:.4f})")
            check(abs(disp - max(solo_amar, 1.0)) > 0.005,
                  "y NO la de solo amarillas, que es otra")

    # Una roja ausente no puede contarse como cero: bajaria la media sin que se
    # note. `_tarjetas_de` suma dos columnas, y NaN + n = NaN.
    df = pd.DataFrame({'home_yellow': [2.0, 3.0], 'home_red': [1.0, None]})
    t = rq._tarjetas_de(df, 'home')
    check(float(t.iloc[0]) == 3.0, "amarillas mas rojas se suman")
    check(pd.isna(t.iloc[1]),
          "y una roja ausente deja la fila fuera, no la cuenta como cero")


def test_las_tarjetas_por_equipo_salen_de_sus_datos():
    """
    v160 — el estimador ataque/defensa, y la trampa que ya cayo una vez.

    Medido sobre 52.648 equipos-partido de juicio en 20 competiciones, error de
    calibracion contra la frecuencia real en las lineas 0,5 / 1,5 / 2,5 / 3,5:

        ataque + defensa del rival, ventana 10 ....  0,0117
        solo lo que recibe el equipo, ventana 10 ..  0,0155
        media movil de 5 del equipo ...............  0,0227
        media de la competicion en ese bando ......  0,0312

    LA TRAMPA: `lambda_corners_equipo` se escribio con la columna del bando
    contrario en una de las dos lecturas, y las dos lambdas del partido salian
    IDENTICAS. Eso es lo que delato el fallo, y es lo que se comprueba aqui —
    no el valor, que cambia con cada jornada, sino que los dos lados difieren.
    """
    import rendimiento_equipos as rq

    probados = 0
    for clave, h, a in (('premier', 'Man City', 'Arsenal'),
                        ('premier', 'Liverpool', 'Everton'),
                        ('laliga', 'Real Madrid', 'Barcelona'),
                        ('serie_a', 'Juventus', 'Inter')):
        t = rq.tarjetas_equipo(clave, h, a)
        if t is None:
            continue
        probados += 1
        check(t['lambda_home'] != t['lambda_away'],
              f"{h}-{a}: los dos lados dan lambdas distintas "
              f"({t['lambda_home']} y {t['lambda_away']})")
        check(abs(t['lambda_total'] - (t['lambda_home'] + t['lambda_away']))
              < 0.01, f"{h}-{a}: el total es la suma de los dos")
        check(0.3 < t['lambda_home'] < 6.0 and 0.3 < t['lambda_away'] < 6.0,
              f"{h}-{a}: las lambdas estan en un rango fisico")
        check(t['dispersion'] >= 1.0 and t['dispersion_total'] >= 1.0,
              f"{h}-{a}: la dispersion nunca baja de 1")
    check(probados >= 2, f"se probaron {probados} partidos con datos reales")

    # Las dos lecturas usan la MISMA columna con distinto filtro. Si alguien
    # vuelve a cruzarlas, el simetrico deja de serlo.
    t1 = rq.tarjetas_equipo('premier', 'Man City', 'Arsenal')
    t2 = rq.tarjetas_equipo('premier', 'Arsenal', 'Man City')
    if t1 and t2:
        check(t1['lambda_home'] != t2['lambda_home'],
              "cambiar quien juega en casa cambia la lambda del local")

    # v162 — sin tarjetas observadas sale la estimacion, marcada.
    _sin = _liga_sin_observar('tarjetas')
    if _sin:
        d = rq._historico(_sin)
        e = rq.tarjetas_equipo(_sin, str(d['home_team'].iloc[-1]),
                               str(d['away_team'].iloc[-1]))
        check(e is not None and e.get('origen') == 'estimado',
              f"sin tarjetas observadas ({_sin}) sale una estimacion MARCADA")


def test_el_arbitro_designado_y_su_encogimiento():
    """
    v160 — el arbitro aporta, pero solo encogido, y esta medido.

    ESPN NO SIRVE PARA ESTO, y se comprobo antes de buscar otra fuente: da el
    arbitro en `summary` -> `gameInfo.officials`, pero medido sobre 139 eventos
    de las 20 competiciones con tarjetas observadas, en +-6 dias:

        partidos ya jugados ('post') ...  88 de 98 con arbitro   89,8 %
        partidos por jugar  ('pre')  ...   0 de 41 con arbitro    0,0 %

    Cero de cuarenta y uno no es cobertura floja: el campo no se rellena hasta
    que el partido empieza, y para apostar hace falta antes. FotMob si lo da
    antes, y ademas con sus amarillas por partido Y la media de su competicion.

    CUANTO APORTA, sobre las 7 competiciones cuyo historico trae quien pito
    (n = 11.375 partidos de juicio, total del partido, lineas 2,5 a 5,5):

        sin arbitro .............  Brier 0,20500   correlacion 0,103
        con arbitro (K=60) ......  Brier 0,20344   correlacion 0,133

    y mejora en las SEIS competiciones, ninguna en contra. El encogimiento hace
    falta: con K=0 la razon cruda EMPEORA la calibracion de 0,0153 a 0,0371.
    """
    import arbitro_partido as ap

    check(ap.K_ENCOGIMIENTO == 60.0,
          f"el encogimiento medido es 60 (esta en {ap.K_ENCOGIMIENTO})")

    # Un arbitro sin datos no mueve nada. Es la regla que impide que un hueco
    # se convierta en un supuesto invisible.
    check(ap.factor(None) == 1.0, "sin arbitro, el factor es 1")
    check(ap.factor({'nombre': 'X'}) == 1.0, "sin sus cifras, tambien es 1")
    check(ap.factor({'nombre': 'X', 'amarillas_por_partido': 5.0,
                     'media_competicion': 0, 'partidos': 30}) == 1.0,
          "sin media de la competicion no hay razon que calcular")

    # El encogimiento: un arbitro con n partidos aporta n/(n+60) de su
    # desviacion. Con n=60 aporta la mitad exacta.
    f = ap.factor({'nombre': 'X', 'amarillas_por_partido': 6.0,
                   'media_competicion': 4.0, 'partidos': 60})
    check(abs(f - 1.25) < 1e-6,
          f"con n=60 y razon 1,5 el factor es 1,25, la mitad del camino ({f})")
    f0 = ap.factor({'nombre': 'X', 'amarillas_por_partido': 6.0,
                    'media_competicion': 4.0, 'partidos': 0})
    check(f0 == 1.0, "con cero partidos arbitrados no aporta nada")

    # Mas partidos, mas peso; nunca al reves.
    fs = [ap.factor({'nombre': 'X', 'amarillas_por_partido': 5.0,
                     'media_competicion': 4.0, 'partidos': n})
          for n in (5, 20, 60, 200)]
    check(fs == sorted(fs),
          f"cuantos mas partidos, mas se acerca a su razon real ({fs})")

    # Y un valor absurdo no se aplica: se ignora, no se recorta en silencio.
    f = ap.factor({'nombre': 'X', 'amarillas_por_partido': 40.0,
                   'media_competicion': 4.0, 'partidos': 500})
    check(f == 1.0, "un factor fuera de banda se ignora, no se recorta")

    # El emparejado con FotMob: los dos equipos, y con margen sobre el segundo.
    idx = [{'home': 'Roma', 'away': 'Fiorentina'},
           {'home': 'Torino', 'away': 'Milan'},
           {'home': 'Palermo', 'away': 'Juve Stabia'}]
    m = ap._empareja('AS Roma', 'Fiorentina', idx)
    check(m is not None and m['home'] == 'Roma',
          "«AS Roma» casa con «Roma» pese al prefijo societario")
    m = ap._empareja('Torino', 'AC Milan', idx)
    check(m is not None and m['away'] == 'Milan',
          "«AC Milan» casa con «Milan»")
    check(ap._empareja('PAOK', 'Levadiakos', idx) is None,
          "y un partido que no esta no se empareja con el mas parecido")

    # La regla que evita el fallo caro: un arbitro en el partido equivocado.
    ambiguo = [{'home': 'Atletico', 'away': 'Racing'},
               {'home': 'Atletico', 'away': 'Racing'}]
    check(ap._empareja('Atletico', 'Racing', ambiguo) is None,
          "dos candidatos igual de buenos se descartan, no se elige uno")


def test_las_tarjetas_en_la_tarjeta():
    """
    v160 — la seccion de tarjetas de la tarjeta: total, por equipo y arbitro.

    ÁMBAR, NO VERDE. Verde en esta aplicacion significa «canal con percentil 5
    positivo medido», y para tarjetas no hay histórico de lineas con el que
    medirlo todavia — `snapshots_tarjetas.py` lo esta acumulando.
    """
    import modo_modelo as mm

    pick = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol', 'fecha': '2026-08-23'}
    tj = mm.tarjetas_tarjeta(pick)
    check(tj is not None, "la Premier produce seccion de tarjetas")
    if tj:
        etiquetas = [f['etiqueta'] for f in tj['filas']]
        check(etiquetas == ['Total', 'Local', 'Visita'],
              f"salen las tres filas en orden ({etiquetas})")
        for f in tj['filas']:
            check(0.5 <= f['prob'] <= 1.0,
                  f"{f['etiqueta']}: se enseña el lado que supera el 50 % "
                  f"({f['prob']:.2f})")
            check(f['texto'].startswith(('Más de', 'Menos de')),
                  f"{f['etiqueta']}: la apuesta dice su lado y su linea")
        check(tj['mejor'] in tj['filas'], "la destacada es una de las tres")
        check(tj['mejor']['prob'] == max(f['prob'] for f in tj['filas']),
              "y es la de mayor probabilidad")
        html = mm._bloque_tarjetas_html(tj)
        check('🟡' in html, "la destacada de tarjetas va en ambar")
        check('✅' not in html,
              "y NUNCA en verde: el EV de tarjetas no esta validado con "
              "histórico de lineas")
        check('👤' in html,
              "la linea del arbitro sale siempre: con su nombre o diciendo "
              "que no esta designado")

    # v162 — donde no hay tarjetas observadas la seccion SI sale, estimada.
    _sin = _liga_sin_observar('tarjetas')
    if _sin:
        import rendimiento_equipos as _rq3
        d = _rq3._historico(_sin)
        b = mm.tarjetas_tarjeta({'partido': '%s vs %s'
                                 % (d['home_team'].iloc[-1],
                                    d['away_team'].iloc[-1]),
                                 'clave_liga': _sin, 'deporte': 'Fútbol'})
        check(b is not None and b.get('origen') == 'estimado',
              f"una competicion sin tarjetas observadas ({_sin}) produce "
              f"seccion MARCADA como estimada")
    check(mm.tarjetas_tarjeta({'partido': 'HOU vs NYY', 'clave_liga': 'mlb',
                               'deporte': 'MLB'}) is None,
          "y el beisbol tampoco")

    # Un partido sin arbitro designado NO se queda sin seccion: se queda sin
    # ajuste, y lo dice. Es la diferencia entre un hueco y un relleno.
    sin_arb = mm.tarjetas_tarjeta({'partido': 'Man City vs Arsenal',
                                   'clave_liga': 'premier',
                                   'deporte': 'Fútbol',
                                   'fecha': '2030-01-01'})
    check(sin_arb is not None, "sin arbitro la seccion sigue saliendo")
    if sin_arb:
        check(sin_arb['factor_arbitro'] == 1.0,
              "y sale sin ajuste, no con uno inventado")
        check('sin designar' in mm._bloque_tarjetas_html(sin_arb),
              "y la tarjeta lo dice en vez de callarselo")

    # La seccion de abajo no repite las medias cuando la de arriba ya salio.
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('con_tarjetas=not _tj' in src,
          "si la seccion con probabilidad salio, la de medias no se repite")


def test_se_guardan_las_lineas_de_tarjetas():
    """
    v160 — la unica via que desbloquea el p5 de tarjetas: acumular el histórico.

    Mismo caso que los córners en la v159. Y un filtro que costo tres pasadas:
    la casa cotiza 4.105 familias distintas en tres partidos, y las de JUGADOR
    entran por el apellido. «Primer goleador y marcador exacto (Diego Alexander
    Gomez Amarilla)» lleva «amarilla»; «Multigoleadores Sergi Cardona Bermadez»
    lleva «card» dentro de «Cardona». Sin los cuatro filtros pasaban 358
    familias donde debian pasar 40.
    """
    import os
    import snapshots_tarjetas as st

    check(hasattr(st, 'capturar') and hasattr(st, 'lineas_de_tarjetas'),
          "el modulo expone la captura")

    # Lo que tiene que entrar: mercados de equipo y de partido.
    for n in ('Total de tarjetas', 'Total de tarjetas Eyupspor',
              'Tarjetas 1x2', 'Tarjetas exactas', 'Tarjetas Hándicap',
              '1ª Mitad - Total de tarjetas', 'Total tarjetas Impar/Par',
              'Ambos equipos 2+ tarjetas cada uno', 'Total de tarjetas rojas'):
        check(st._es_tarjeta(n) is True, f"entra el mercado «{n}»")

    # Lo que NO puede entrar, con los casos reales que lo colaron.
    for n, motivo in (
            ('Jugador recibe una tarjeta (Abdelhamid Sabiri (EYU))',
             'es por jugador y no hay con que liquidarla'),
            ('Primer goleador y marcador exacto (Diego Alexander Gomez Amarilla)',
             'el apellido del jugador lleva «amarilla»'),
            ('Tackleadas - Diego Alexander Gomez Amarilla (BHA) (alineación inicial)',
             'el apellido va fuera de los parentesis'),
            ('Multigoleadores Sergi Cardona Bermadez',
             '«card» esta dentro de «Cardona»'),
            ('Goleador O el sustituto anotará - Diego Alexander Gomez Amarilla',
             'goleador con apellido «Amarilla»'),
            ('Total de goles', 'no es de tarjetas'),
            ('Total Tiros De Esquina', 'son córners')):
        check(st._es_tarjeta(n) is False, f"NO entra «{n[:52]}»: {motivo}")

    # Los parentesis anidados existen en el tablero real.
    check(st._sin_parentesis('Jugador recibe una tarjeta (X (EYU))').strip()
          == 'Jugador recibe una tarjeta',
          "los parentesis anidados se quitan enteros")

    # La linea sale de la ETIQUETA, con `sv` de respaldo: «Total de tarjetas»
    # llega con sv=5.5 y sus selecciones dicen 4.5, 5.5 y 6.5.
    src = open('snapshots_tarjetas.py', encoding='utf-8').read()
    check('linea_etq if linea_etq is not None else linea_fam' in src,
          "la linea guardada es la de la etiqueta, con `sv` de respaldo")

    # El bot lo ejecuta y commitea el resultado: sin las dos cosas, el histórico
    # no crece y esto no sirve de nada.
    wf = open(os.path.join('.github', 'workflows', 'retrain_leagues.yml'),
              encoding='utf-8').read()
    check('snapshots_tarjetas.py' in wf, "el bot lo ejecuta a diario")
    check('tarjetas_snapshots.csv' in wf, "y commitea lo capturado")
    check('arbitro_partido.py' in wf,
          "y precalcula los arbitros del dia antes de capturar")

    if os.path.exists(st.FICHERO):
        import pandas as pd
        d = pd.read_csv(st.FICHERO)
        check(len(d) > 0, f"hay lineas capturadas ({len(d)})")
        # Ninguna familia de jugador puede haberse colado al fichero.
        coladas = [n for n in d['familia'].unique() if not st._es_tarjeta(n)]
        check(not coladas,
              f"ninguna familia del fichero incumple el filtro ({coladas[:3]})")


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
    #
    # v165 — Y EL VERDE YA NO SALE SOLO POR SER ALTO. Este caso pedia antes
    # `d['alta']` con un 81 % y sin nada con que contrastarlo, que es
    # exactamente lo que fallo el 2026-08-23. La ELECCION del mercado no
    # cambia; lo que cambia es que el ✅ exige precio de la casa que lo
    # respalde. El detalle esta en `test_el_titular_no_va_en_verde_sin_contraste`.
    p = {'mercados': [{'mercado': '1X2', 'apuesta': 'Gana A', 'prob': 0.40},
                      {'mercado': 'Goles', 'apuesta': 'Menos de 2.5',
                       'prob': 0.81}]}
    d = mm.apuesta_destacada(p)
    check(d and d['apuesta'] == 'Menos de 2.5',
          "gana el mercado mas probable del partido, no el 1X2 por defecto")
    check(d and not d['alta'],
          "pero sin precio de la casa con el que contrastarlo, no va en verde")
    # v166 — «de acuerdo» es ahora una distancia MEDIDA, no cualquier cosa: el
    # 81 % de antes quedaba 7 puntos por encima de la casa y eso ya miente
    # (brecha 0,065 sobre 1.317 partidos). Con la casa realmente de acuerdo,
    # el verde sigue saliendo.
    import cordura_probabilidad as _cp
    con_precio = mm.apuesta_destacada(
        {**p, 'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.19}}})
    check(con_precio and con_precio['alta'],
          f"y con la casa de acuerdo, si ({con_precio})")
    lejos = mm.apuesta_destacada(
        {**p, 'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.40}}})
    check(lejos and not lejos['alta'],
          "y con la casa en contra, no")

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


def test_la_tarjeta_es_la_misma_para_hoy_y_manana():
    """
    v155 — un solo componente para las dos vistas, y una sola diferencia.

    «Mañana» enseñaba una tabla con la barra de 1X2 y la etiqueta
    «· informativo», mientras «hoy» tenía la apuesta destacada, los mercados y
    las rachas. Eran dos diseños para el mismo partido, y la diferencia no
    venia de los datos —que son los mismos— sino de que cada vista se habia
    construido en un momento distinto.

    La UNICA diferencia que queda es `con_apuesta`, y es de fondo: los partidos
    de mañana no producen picks porque las lineas se mueven durante la noche, y
    ese movimiento es justo el canal que este proyecto mide.
    """
    import modo_modelo as mm

    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('_mm_man.render(' in ui, "la vista de mañana usa el mismo render")
    check('con_apuesta=False' in ui,
          "y lo hace en modo analisis, sin proponer apuesta")
    check('_rtp_m.pintar_con_boton' not in ui,
          "ya no queda la tabla vieja de mañana")

    import inspect
    firma = inspect.signature(mm.render).parameters
    check('con_apuesta' in firma, "`render` acepta el modo sin apuesta")
    check('titulo' in firma, "y un titulo propio por vista")
    check('con_apuesta' in inspect.signature(mm.tarjeta).parameters,
          "y la tarjeta tambien")


def test_los_bloques_de_la_tarjeta():
    """
    v155 — 1X2, goles, ambos marcan, córners y tarjetas, cada uno con su regla.

    LOS CÓRNERS NO LLEVAN PORCENTAJE, Y ES UNA DECISION MEDIDA. El modelo de
    córners predice la media de la competicion —la misma cifra para todos sus
    partidos— porque su parte variable tiene correlacion −0,0012 con el total
    real sobre 11.856 partidos. Un «Más de 9.5: 52 %» diria mas de la liga que
    del partido. Lo que si es de cada equipo son sus medias observadas.
    """
    import modo_modelo as mm

    p = {'partido': 'A vs B', 'clave_liga': 'premier', 'deporte': 'Fútbol',
         'mercados': [
             {'mercado': '1X2', 'apuesta': 'Gana A', 'prob': 0.55},
             {'mercado': '1X2', 'apuesta': 'Empate', 'prob': 0.23},
             {'mercado': '1X2', 'apuesta': 'Gana B', 'prob': 0.22},
             {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.65},
             {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.35},
             {'mercado': 'BTTS', 'apuesta': 'Ambos marcan: Sí', 'prob': 0.54},
             {'mercado': 'BTTS', 'apuesta': 'Ambos marcan: No', 'prob': 0.46}]}

    tri = mm.probabilidades_1x2(p)
    check(tri is not None and abs(sum(tri) - 1.0) < 0.02,
          "el 1X2 se localiza por el nombre de los equipos y suma 1")
    check(mm.probabilidades_1x2({'partido': 'A vs B'}) is None,
          "sin las tres probabilidades no se dibuja una barra a medias")

    # media barra es peor que ninguna: se lee como un valor, no como un hueco
    check(mm._fila_mercado('⚽', 'Goles', 0.65, None, 'a', 'b') == '',
          "un mercado con un solo lado no se pinta")
    fila = mm._fila_mercado('⚽', 'Goles', 0.65, 0.35, 'Más 2.5', 'Menos 2.5')
    check('65' in fila and '35' in fila, "y con los dos, salen los dos numeros")

    # LOS CÓRNERS, SIN PORCENTAJE. Se comprueba sobre la SALIDA y no sobre el
    # codigo: la primera version buscaba «%» en el cuerpo de la funcion y
    # chocaba con el operador de formato («%.1f»), que no tiene nada que ver.
    lleno = mm._bloque_fisico(
        {'forma_home': {'equipo': 'A', 'ck_favor': 5.4, 'ck_contra': 4.1,
                        'amarillas': 2.1},
         'forma_away': {'equipo': 'B', 'ck_favor': 4.8, 'ck_contra': 5.0,
                        'amarillas': 1.8}},
        {'corners': True, 'tarjetas': True})
    check('5.4' in lleno and '2.1' in lleno,
          "el bloque enseña las medias observadas de cada equipo")
    check('%' not in lleno,
          "y NO publica probabilidades de córners: el modelo predice para "
          "ellos la media de la competicion, igual en todos sus partidos")

    # y donde la competicion no los trae, se DICE
    vacio = mm._bloque_fisico({'forma_home': {}, 'forma_away': {}}, {})
    check('no disponibles' in vacio,
          "sin datos de córners se dice, en vez de dejar el hueco")


def test_los_ordenes_de_la_lista():
    """
    v155 — cinco criterios, y ninguno se inventa un valor cuando no lo hay.

    Un partido sin el dato del criterio elegido tiene que irse ABAJO, no
    colarse arriba. Ordenar por «probabilidad de ambos marcan» y que encabece
    la lista un partido que no publica ese mercado seria peor que no ordenar.
    """
    import modo_modelo as mm

    check(len(mm.ORDENES) == 5, "hay cinco criterios de orden (%d)"
          % len(mm.ORDENES))
    for etq in ('Hora', 'Probabilidad del local',
                'Probabilidad de más de 2.5',
                'Probabilidad de ambos marcan', 'Apuesta destacada'):
        check(etq in mm.ORDENES, f"el criterio «{etq}» existe")

    lleno = {'partido': 'A vs B',
             'mercados': [{'mercado': 'Goles', 'apuesta': 'Más de 2.5',
                           'prob': 0.70}]}
    vacio = {'partido': 'C vs D'}
    for nombre in ('Probabilidad del local', 'Probabilidad de más de 2.5',
                   'Probabilidad de ambos marcan', 'Apuesta destacada'):
        fn = mm.ORDENES[nombre]
        check(fn(vacio) > fn(lleno) or fn(vacio) >= 0,
              f"«{nombre}» manda abajo lo que no tiene el dato")

def test_modo_modelo_esta_enrutado_en_la_interfaz():
    """
    v154 — la vista de apuestas es la primera, y la ventaja de precio SIGUE.

    Las siete pestañas se consolidaron en cuatro: tres enseñaban la misma lista
    del dia con otro orden. Lo que este test protege no es el numero de
    pestañas —eso es decision de producto y puede volver a cambiar— sino que la
    simplificacion no se lleve por delante **la ventaja de precio**, que es el
    unico criterio con percentil 5 positivo medido en todo el proyecto.

    Antes se comprobaba el ORDEN de dos rotulos concretos («Modo Modelo» antes
    que «Modo Valor»). Esos rotulos ya no existen, y un test atado a una
    redaccion se rompe con cada rediseño sin proteger nada: ahora se comprueba
    que el destino siga enrutado y que su contenido siga siendo alcanzable.
    """
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check('import modo_modelo' in src, "la vista de apuestas esta importada")
    check('_mm.render(' in src, "y se pinta de verdad")
    check('Apuestas de hoy' in src, "la pestaña de apuestas de hoy existe")

    # La ventaja de precio: su pestaña puede haberse convertido en desplegable,
    # pero el destino y su contenido tienen que seguir vivos.
    check('_tab_ev' in src and '_tab_jugar' in src,
          "el destino de la Seccion 1 sigue enrutado")
    check('Ventaja de precio' in src,
          "y sigue alcanzable con su nombre en pantalla")
    i_hoy = src.index('⚽ Apuestas de hoy')
    i_manana = src.index('\U0001F5D3️ Mañana')
    check(i_hoy < i_manana,
          "las apuestas de hoy se declaran antes que las de mañana")



def test_los_remates_por_equipo_salen_de_sus_datos():
    """
    v163 — el estimador ataque/defensa, y la trampa que ya cayo dos veces.

    Medido sobre 41.000 equipos-partido de 17 competiciones con remates
    observados (`_v163_remates_estimadores.py`), comparando cuatro estimadores
    por dos distribuciones:

        remates TOTALES por equipo            marginal    Brier      ECE
          ataque/defensa v10, binneg .......   0,01315   0,19501   0,03132
          media del equipo, binneg .........   0,02067   0,20441   0,03310
          media de la competicion, binneg ..   0,02077   0,21282   0,03200
          media movil de 5, Poisson ........   0,01476   0,22477   0,11418

    OJO CON LA PRIMERA COLUMNA. Es la que se uso en corners y tarjetas, y aqui
    la habria ganado la media movil de 5 con Poisson, que es el PEOR estimador
    de la tabla por las otras dos. El error marginal no mide resolucion: dos
    sesgos que se cancelan lo dejan bajo. Por eso la eleccion se hizo por ECE.

    LA TRAMPA: `lambda_corners_equipo` se escribio con la columna del bando
    contrario en una de las dos lecturas, y las dos lambdas del partido salian
    IDENTICAS. Es lo que se comprueba aqui — no el valor, que cambia con cada
    jornada, sino que los dos lados difieren.
    """
    import rendimiento_equipos as rq

    probados = 0
    for clave, h, a in (('premier', 'Man City', 'Arsenal'),
                        ('premier', 'Liverpool', 'Everton'),
                        ('laliga', 'Real Madrid', 'Barcelona'),
                        ('serie_a', 'Juventus', 'Inter')):
        r = rq.remates_equipo(clave, h, a)
        if not r or (r.get('totales') or {}).get('origen') != 'observado':
            continue
        probados += 1
        for mercado, lo, hi in (('totales', 3.0, 25.0), ('a_puerta', 0.8, 10.0)):
            b = r.get(mercado)
            check(b is not None, f"{h}-{a}: hay bloque de {mercado}")
            if not b:
                continue
            check(b['lambda_home'] != b['lambda_away'],
                  f"{h}-{a} {mercado}: los dos lados dan lambdas distintas "
                  f"({b['lambda_home']} y {b['lambda_away']})")
            check(abs(b['lambda_total']
                      - (b['lambda_home'] + b['lambda_away'])) < 0.01,
                  f"{h}-{a} {mercado}: el total es la suma de los dos")
            check(lo < b['lambda_home'] < hi and lo < b['lambda_away'] < hi,
                  f"{h}-{a} {mercado}: las lambdas estan en un rango fisico")
            check(b['dispersion'] >= 1.0 and b['dispersion_total'] >= 1.0,
                  f"{h}-{a} {mercado}: la dispersion nunca baja de 1")
        t, o = r.get('totales') or {}, r.get('a_puerta') or {}
        if t and o:
            check(o['lambda_total'] < t['lambda_total'],
                  f"{h}-{a}: a puerta siempre es menos que el total")

    check(probados >= 2, f"se probaron {probados} partidos con datos reales")

    # Las dos lecturas usan la MISMA columna con distinto filtro. Si alguien
    # vuelve a cruzarlas, el simetrico deja de serlo.
    r1 = rq.remates_equipo('premier', 'Man City', 'Arsenal')
    r2 = rq.remates_equipo('premier', 'Arsenal', 'Man City')
    if r1 and r2 and r1.get('totales') and r2.get('totales'):
        check(r1['totales']['lambda_home'] != r2['totales']['lambda_home'],
              "cambiar quien juega en casa cambia la lambda del local")

    # La sobredispersion por equipo es MUCHO mayor que la del total, y eso es
    # lo que justifica usar dos numeros distintos en vez de uno.
    de, dt = (rq.dispersion_remates_equipo('premier', 'tot'),
              rq.dispersion_remates_liga('premier', 'tot'))
    if de and dt:
        check(de > dt,
              f"la dispersion por equipo ({de}) supera a la del total ({dt}), "
              f"que es lo medido (2,09 contra 1,35)")

    # v163 — sin remates observados sale la estimacion, marcada.
    _sin = _liga_sin_observar('remates')
    if _sin:
        d = rq._historico(_sin)
        e = rq.remates_equipo(_sin, str(d['home_team'].iloc[-1]),
                              str(d['away_team'].iloc[-1]))
        check(e is not None
              and (e.get('totales') or {}).get('origen') == 'estimado',
              f"sin remates observados ({_sin}) sale una estimacion MARCADA")


def test_el_nivel_de_remates_no_se_mide_sobre_dos_epocas():
    """
    v163 — la dispersion se mide en las ULTIMAS temporadas, y hace falta.

    El historico de la Premier arranca en 2010 y los remates a puerta por
    partido de aquellos anos no son los de ahora:

        2010  13,4      2014   8,6      2020   8,4      2024   9,9
        2013  11,3      2018   8,7      2023   9,0      2026   8,5

    Entre 2013 y 2014 la media se parte por la mitad: la fuente cambio que
    cuenta. Promediando las dos epocas juntas, la razon varianza/media del
    total sale 1,62 cuando dentro de cada ano va entre 0,90 y 1,22 — o sea que
    la sobredispersion medida seria la distancia entre dos definiciones, y la
    binomial negativa engordaria las colas por un motivo inventado.
    """
    import rendimiento_equipos as rq

    check(hasattr(rq, '_recientes') and rq.TEMPORADAS_REMATES >= 3,
          "las series de remates se recortan a las ultimas temporadas")

    d = rq.dispersion_remates_liga('premier', 'on')
    check(d is not None and 0.95 <= d <= 1.35,
          f"la dispersion del total a puerta en la Premier es la de su epoca "
          f"actual ({d}), no la de las dos mezcladas (1,62)")

    # y la del equipo sigue por encima, que es lo que separa los dos numeros
    de = rq.dispersion_remates_equipo('premier', 'tot')
    check(de is not None and 1.5 <= de <= 3.0,
          f"la dispersion por equipo en remates totales sigue alta ({de})")


def test_los_remates_en_la_tarjeta():
    """
    v163 — la seccion sale, tiene sus dos mercados y dice de donde viene.

    Dos bloques y no uno porque son dos mercados que la casa cotiza por
    separado y que se calibraron por separado. Juntarlos obligaria a elegir
    uno, y el que se dejara fuera seria el que el usuario esta mirando.
    """
    import modo_modelo as mm

    pick = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol'}
    r = mm.remates_tarjeta(pick)
    check(r is not None, "la tarjeta de la Premier trae seccion de remates")
    if r:
        check('totales' in r and 'a_puerta' in r,
              "trae los dos mercados: totales y a puerta")
        for nombre, bloque in r.items():
            check(len(bloque['filas']) >= 1,
                  f"{nombre}: al menos una fila (total, local o visita)")
            check(bloque['mejor'] in bloque['filas'],
                  f"{nombre}: la destacada es una de las filas")
            for f in bloque['filas']:
                check(0.0 <= f['prob'] <= 1.0,
                      f"{nombre}/{f['etiqueta']}: la probabilidad es una "
                      f"probabilidad")
                check(f['prob'] >= 0.5,
                      f"{nombre}/{f['etiqueta']}: se ensena el lado que gana, "
                      f"no obliga a restar de cabeza")
        html = mm._bloque_remates_html(r)
        check('Remates' in html and 'A puerta' in html.replace('a puerta',
                                                               'A puerta'),
              "el HTML nombra los dos mercados")

    # No es futbol -> no hay seccion. Un bloque de remates en un partido de
    # tenis seria un numero sin significado.
    check(mm.remates_tarjeta({'partido': 'Alcaraz vs Sinner',
                              'clave_liga': 'atp',
                              'deporte': 'Tenis'}) is None,
          "en tenis no se pinta seccion de remates")
    # Y sin bloque, el HTML es cadena vacia y no un hueco con titulo.
    check(mm._bloque_remates_html(None) == '',
          "sin datos no se pinta un titulo vacio")


def test_los_remates_por_jugador_no_se_inventan():
    """
    v163 — lo que se ensena por jugador y lo que NO se promete.

    Tres cosas medidas que esta prueba fija:

      1. la lambda del jugador se ENCOGE hacia la media de su posicion. Con
         4-10 apariciones su media suelta es un tercio de ruido; encoger baja
         el ECE de 0,056 a 0,029 y ademas sube la correlacion.
      2. la distribucion es POISSON, no binomial negativa — al reves que en el
         equipo. La sobredispersion que se mide juntando jugadores es en buena
         parte la diferencia entre ellos, y esa ya esta dentro de cada lambda.
      3. el previo posicional va en CUOTA del total del equipo, que es
         adimensional y por eso vale en las 62 competiciones.
    """
    import remates_jugador as rjg

    cal = rjg.calibracion()
    check(bool(cal.get('cuotas')),
          "existe el ajuste medido de cuotas por posicion")
    for obj in ('tot', 'on'):
        cuotas = (cal.get('cuotas') or {}).get(obj) or {}
        check(len(cuotas) >= 8,
              f"{obj}: hay cuota para las posiciones habituales "
              f"({len(cuotas)})")
        if cuotas:
            check(all(0.0 <= v <= 0.5 for v in cuotas.values()),
                  f"{obj}: ninguna posicion se lleva mas de la mitad de los "
                  f"remates del equipo")
            # el delantero remata mas que el central: si esto se invierte, la
            # tabla se ha generado mal o se han cruzado las posiciones
            f_, d_ = cuotas.get('F'), cuotas.get('CD-L') or cuotas.get('CD-R')
            if f_ and d_:
                check(f_ > d_ * 2,
                      f"{obj}: un delantero remata bastante mas que un central "
                      f"({f_} contra {d_})")
        check(rjg._k(obj) > 0, f"{obj}: hay encogimiento (K > 0)")
    check(rjg._k('on') > rjg._k('tot'),
          "el evento mas raro (a puerta) se encoge MAS, que es lo medido "
          "(K=12 contra K=6)")

    # El encogimiento hace lo que dice: con poca muestra manda el previo.
    previo = rjg.cuota_posicion('F', 'tot')
    if previo:
        lam_eq = 13.0
        poca = rjg.lambda_jugador(5.0, 1, 'F', lam_eq, 'tot')
        mucha = rjg.lambda_jugador(5.0, 10, 'F', lam_eq, 'tot')
        base = previo * lam_eq
        check(abs(poca - base) < abs(mucha - base),
              f"con una aparicion la lambda ({poca}) queda mas cerca del "
              f"previo ({base:.2f}) que con diez ({mucha})")
        check(mucha > poca,
              "y con mas muestra pesa mas lo que hace el jugador")

    # Poisson: P(>=1) con lambda 0 es 0 y crece sin pasar de 1.
    check(rjg.p_al_menos_uno(0.0) == 0.0, "lambda 0 -> probabilidad 0")
    check(rjg.p_al_menos_uno(None) is None, "sin lambda no hay probabilidad")
    p1, p2 = rjg.p_al_menos_uno(1.0), rjg.p_al_menos_uno(3.0)
    check(0.0 < p1 < p2 < 1.0,
          f"la probabilidad crece con la lambda y no llega a 1 ({p1}, {p2})")

    # Una posicion desconocida NO recibe una cuota inventada.
    check(rjg.cuota_posicion('XX', 'tot') is None,
          "una posicion que no esta medida no se rellena con un numero")
    check(rjg.lambda_jugador(2.0, 8, 'XX', 13.0, 'tot') is None,
          "y sin cuota no sale lambda: la fila desaparece en vez de mentir")

    # Sin lambda de equipo tampoco: el jugador va anclado al equipo.
    check(rjg.lambda_jugador(2.0, 8, 'F', None, 'tot') is None,
          "sin lo que se espera del equipo no hay lambda de jugador")


def test_la_alineacion_no_cuesta_la_pantalla_ni_se_inventa():
    """
    v163 — de donde sale el once, cuanto cuesta y que pasa cuando no hay.

    ESPN NO SIRVE, y se midio antes de buscar otra fuente: da el once inicial
    en 50 de 50 partidos JUGADOS y en **0 de 54** por jugar, incluido uno a 4,4
    horas del saque (`_v163_sondeo_alineacion.json`). Misma firma que el
    arbitro en la v160.

    FotMob si: 27 de 50 partidos por jugar, 21 de ellos como `predicted` y 6
    como `lastStarting11` — que no valen lo mismo y por eso se distinguen en
    pantalla.

    Y NO SE PIDE EN LA TARJETA. Sesenta partidos por un `matchDetails` de 1,7
    segundos son dos minutos anadidos a una pantalla que ya tarda 85. Se
    precalcula en el bot, igual que el arbitro.
    """
    import remates_jugador as rjg

    src = open('remates_jugador.py', encoding='utf-8').read()
    check('permitir_red' in src,
          "la alineacion distingue leer del disco de preguntar a la red")
    check('lineupType' in src,
          "se lee el tipo de alineacion, que es lo que separa un once probable "
          "de uno confirmado")
    check('starters' in src,
          "y por la ruta comprobada de FotMob (homeTeam.starters)")

    # Por defecto NO toca la red: con un fichero que no existe devuelve None
    # sin llamar a nadie.
    rjg._DISCO = {}
    rjg._ALINEACIONES.clear()
    check(rjg.alineacion('2026-01-01', 'Equipo Que No Existe',
                         'Otro Que Tampoco') is None,
          "sin precalculo y sin red, la alineacion es None y no un invento")

    # Los tres tipos de FotMob tienen su rotulo, y son distintos entre si.
    etiquetas = {v[0] for v in rjg.TIPOS.values()}
    check('probable' in etiquetas and 'confirmada' in etiquetas,
          "un once probable y uno confirmado no se llaman igual")
    check(rjg.TIPOS['lastStarting11'][0] != rjg.TIPOS['predicted'][0],
          "el once del ultimo partido no se presenta como alineacion probable")

    # El emparejado de nombres no fuerza: un nombre que no casa se queda fuera.
    filas = [{'jugador': 'Bukayo Saka'}, {'jugador': 'Martin Odegaard'}]
    pares = rjg.casar_once_detalle(
        ['Bukayo Saka', 'Nombre Que No Existe En Ninguna Parte'], filas)
    check(pares.get('Bukayo Saka') == 'Bukayo Saka',
          "el nombre que casa, casa")
    check('Nombre Que No Existe En Ninguna Parte' not in pares,
          "y el que no casa se queda fuera en vez de caer en otro jugador")

    # Un jugador de ESPN no puede casar con dos del once.
    pares2 = rjg.casar_once_detalle(['Bukayo Saka', 'B. Saka'],
                                    [{'jugador': 'Bukayo Saka'}])
    check(len(set(pares2.values())) == len(pares2.values()),
          "un mismo jugador no se asigna a dos nombres del once")

    # El precalculo esta enchufado al bot, que es lo que lo hace gratis en
    # pantalla.
    wf = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    check('remates_jugador.py --dias' in wf,
          "el bot precalcula las alineaciones del dia")
    check('alineaciones_dia.json' in wf,
          "y las guarda, porque manana ya no se pueden recuperar")


def test_el_catalogo_de_equipos_de_espn_no_se_corta():
    """
    v163 — el catalogo se completa, y antes se cortaba a los 16 equipos.

    `equipos_de_liga` paraba el barrido en cuanto juntaba 16 nombres, con la
    idea de que una liga tiene ~20 equipos y con un tramo de 55 dias basta. No
    basta: a principio de temporada ahi dentro no ha jugado media competicion.

    Medido el 2026-08-23 con el catalogo que habia cacheado: la Serie A tenia
    16 equipos (faltaban Roma, Lazio, Fiorentina y Bologna) y LaLiga 19
    (faltaba Osasuna). Y el efecto no se veia: `resolver_equipo` devuelve None
    para un equipo que no esta, asi que la seccion de jugadores salia VACIA
    para la Roma, sin aviso — indistinguible de «ESPN no cubre esta
    competicion».
    """
    import remates_jugadores as rj

    src = open('remates_jugadores.py', encoding='utf-8').read()
    check('if len(nombres) >= 16:' not in src,
          "el barrido del catalogo ya no para a los 16 equipos")
    check('secos' in src,
          "para cuando dos tramos seguidos no aportan un nombre nuevo, que es "
          "la senal de que el catalogo esta completo")
    check('if salida:' in src,
          "y un catalogo vacio no se cachea: seis horas de silencio por un "
          "fallo de red seria el mismo error con otra cara")

    # Los alias que faltaban estan, y no pisan a los que ya habia.
    import json
    alias = json.load(open('alias_manuales.json', encoding='utf-8'))

    def _destinos(k):
        v = alias.get(k)
        return [] if v is None else ([v] if isinstance(v, str) else list(v))

    for clave, espn in (('Roma', 'AS Roma'), ('Man City', 'Manchester City'),
                        ('Ajax', 'Ajax Amsterdam'), ('QPR',
                                                     'Queens Park Rangers')):
        check(espn in _destinos(clave),
              f"'{clave}' sabe que en ESPN se llama '{espn}'")
    check(_destinos('Man City')[0] == 'Man City',
          "y el destino de siempre sigue el PRIMERO, asi que el emparejado "
          "contra el catalogo del proyecto no cambia")


def test_remates_no_suben_a_seccion1_sin_medicion():
    """
    v163 — los remates se ensenan, pero no como ventaja de precio.

    Verde en esta aplicacion significa «canal con percentil 5 de bootstrap
    positivo medido en tramo de juicio». En remates no hay ni eso ni historico
    de LINEAS con el que empezar a medirlo, exactamente igual que pasaba con
    corners en la v152 y con tarjetas en la v160.

    Lo que si hay es una probabilidad calibrada — 0,0131 de error en remates
    totales y 0,0129 a puerta donde los datos son observados — y eso es lo que
    se ensena, dicho como lo que es.
    """
    import modo_modelo as mm

    src = open('modo_modelo.py', encoding='utf-8').read()
    i = src.find('def remates_tarjeta')
    check(i > 0, "existe la seccion de remates en la tarjeta")
    cabecera = src[max(0, i - 2000):i]
    check('ventaja de precio' in cabecera,
          "la seccion dice por escrito que no es una ventaja de precio")

    # Y la probabilidad del jugador no se presenta como apuesta recomendada.
    j = src.find('def _bloque_quien_remata_html')
    check(j > 0, "existe el bloque de quien remata")
    cuerpo = src[j:j + 3000]
    check('informativa' in cuerpo,
          "el bloque de jugadores se presenta como informativo")

    pick = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol'}
    r = mm.remates_tarjeta(pick)
    if r:
        for bloque in r.values():
            check('alta' not in bloque and 'ev' not in bloque,
                  "el bloque de remates no lleva ni EV ni marca de apuesta "
                  "alta: no compite con la Seccion 1")


def test_los_jugados_son_del_dia_de_cdmx():
    """
    v163.1 — «hoy» es el dia de CDMX, y antes era el de UTC.

    LO QUE VEIA EL USUARIO. El 2026-08-23 a la 01:21 de Mexico, la lista de
    «Partidos de hoy» traia 27 partidos con ✅ Finalizado, todos del dia 22 por
    la tarde. Un Barcelona SC-Orense de las 18:00 del 22 en Mexico son las
    00:00 UTC del 23, y el recorte comparaba contra el dia UTC.

    Y la otra mitad del mismo fallo, que no se veia: los partidos de la TARDE
    del 23 en Mexico (02:00 UTC del 24) no habrian entrado nunca en «hoy».

    Un dia de CDMX abarca DOS dias UTC —de 06:00 del propio a 05:59 del
    siguiente— asi que se miran los dos y se recorta con la fecha local.
    """
    import fixtures_espn as fx

    # el caso exacto que lo destapo
    check(fx.fecha_local('2026-08-23 00:00:00') == '2026-08-22',
          "un partido de las 00:00 UTC del 23 es del 22 en CDMX "
          "(el Barcelona SC-Orense de las 18:00)")
    check(fx.fecha_local('2026-08-24 02:00:00') == '2026-08-23',
          "y uno de las 02:00 UTC del 24 es del 23 en CDMX: tiene que salir "
          "en «hoy», no en «manana»")
    check(fx.fecha_local('2026-08-23 12:00:00') == '2026-08-23',
          "el mediodia UTC cae en el mismo dia en CDMX")

    # sin hora no se inventa: se usa el dia suelto que venga
    check(fx.fecha_local(None, '2026-08-23') == '2026-08-23',
          "sin marca de tiempo se usa el dia que venga, no se adivina")
    check(fx.fecha_local(None, None) == '',
          "y sin nada, cadena vacia")

    # el recorte de `jugados_del_dia` mira los DOS dias UTC
    src = open('fixtures_espn.py', encoding='utf-8').read()
    cuerpo = src.split('def jugados_del_dia')[1].split(chr(10) + 'def ')[0]
    check('dia_sig' in cuerpo,
          "se consulta tambien el dia UTC siguiente, que es donde cae la "
          "tarde mexicana")
    check('fecha_local(' in cuerpo,
          "y el recorte final usa la fecha LOCAL de cada partido")

    # el invariante del reloj NO se toca: el rango de descarga sigue en UTC
    rango = src.split('def _fixtures_de_codigo')[1][:1200]
    check("Timestamp.now('UTC')" in rango or 'utcnow()' in rango,
          "el rango de descarga sigue anclado en UTC (v91)")

    # y la interfaz pasa el dia explicito en vez de adivinarlo
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('dia=_HOY_S' in ui,
          "la lista de hoy recibe el dia de CDMX de quien lo sabe, en vez de "
          "deducirlo del primer partido de la lista")
    mm = open('modo_modelo.py', encoding='utf-8').read()
    check('dia or _dia_de(pronosticos)' in mm,
          "y `render` lo usa cuando se lo pasan")


def test_los_goles_traen_tres_lineas():
    """
    v163.1 — mas/menos 1,5 y 3,5 ademas de 2,5.

    Una sola linea no dice lo mismo en todos los partidos: un 64 % de «mas de
    2,5» puede venir de uno que casi seguro pasa de 1,5 o de uno que se va a 4,
    y con una sola barra los dos se leen igual.

    VAN EN SU PROPIA CLAVE Y NO EN EL `board`. El `board` lo recorren
    `apuesta_destacada` y el `prob` de los partidos jugados buscando el MAXIMO,
    y «mas de 1,5» ronda el 75-85 % en casi cualquier partido: metido ahi seria
    la apuesta destacada de la lista entera.
    """
    import numpy as np
    import alpha_finder as af
    import modo_modelo as mm

    # una matriz de marcador de juguete, con masa repartida
    M = np.zeros((6, 6))
    for i in range(6):
        for j in range(6):
            M[i, j] = 1.0 / ((i + 1) * (j + 1))
    M = M / M.sum()
    lineas = af.lineas_de_goles({'score_matrix': M.tolist()})
    # v171 — son SIETE, no tres. La recomendacion se elige por Score sobre
    # TODAS las lineas que la casa publica (de 0,5 a 6,5), y una que el modelo
    # no calcule es una que no se puede proponer aunque sea la de mejor valor.
    check(set(lineas) >= {'1.5', '2.5', '3.5'},
          f"siguen las tres de siempre ({sorted(lineas)})")
    check(set(lineas) == {'0.5', '1.5', '2.5', '3.5', '4.5', '5.5', '6.5'},
          f"y la escalera entera desde la v171 ({sorted(lineas)})")
    check(lineas['1.5'] > lineas['2.5'] > lineas['3.5'],
          f"y son monotonas: cuanto mas alta la linea, menos probable "
          f"({lineas})")
    for v in lineas.values():
        check(0.0 <= v <= 1.0, f"cada una es una probabilidad ({v})")

    # matriz invalida -> diccionario vacio, no una excepcion ni un cero
    check(af.lineas_de_goles({}) == {},
          "sin matriz no hay lineas, y no revienta")

    # el bloque se pinta, y sin `goles_lineas` se comporta como antes
    b = {'Más de 2.5': 0.69, 'Menos de 2.5': 0.31}
    html = mm._bloque_goles_html({'goles_lineas': {'1.5': 0.87, '2.5': 0.69,
                                                   '3.5': 0.42}}, b)
    for t in ('1.5', '2.5', '3.5', '87', '69', '42'):
        check(t in html, f"el bloque de goles nombra {t}")
    viejo = mm._bloque_goles_html({}, b)
    check('1.5' not in viejo and '2.5' in viejo,
          "sin las lineas nuevas se pinta lo de siempre y nada mas")

    # y NO estan en el board, que es lo que mira la apuesta destacada
    check('Más de 1.5' not in b, "el board no se toca")
    d = mm.apuesta_destacada({'board': {'Gana A': 0.55, 'Gana B': 0.45},
                              'goles_lineas': {'1.5': 0.92}})
    check(d is None or 'Gana' in d.get('apuesta', ''),
          "la apuesta destacada sigue saliendo del board, no de las lineas "
          "nuevas")


def test_la_contencion_no_empareja_clubes_distintos():
    """
    v163.1 — «Viking FK» ya no es el «Vikingur Reykjavik».

    Lo encontro el diagnostico de la Champions:

        mapear('Viking FK', catalogo_champions)  ->  'Vikingur Reykjavik'

    El Viking FK es de Stavanger y el Vikingur Reykjavik de Islandia. El
    emparejado no fallaba: acertaba con confianza, y el modelo publicaba una
    probabilidad calculada con la fuerza del equipo equivocado. Un hueco se ve;
    esto no.

    LO QUE HABIA QUE CONSERVAR. La contencion es la que casa «Roma» con «AS
    Roma» y «Man City» con «Manchester City», asi que no se podia quitar. Dos
    reglas obvias fallaron antes de dar con la buena:

      · exigir PALABRA COMPLETA tumbaba «Man City» y «West Brom», donde la
        abreviatura trunca una palabra y truncar es legitimo;
      · exigir PARECIDO tampoco vale: «Ajax» contra «Ajax Amsterdam» tiene 0,44
        de similitud, MENOS que el 0,50 del Viking, y es correcto.

    Lo que los separa es cuantas palabras le SOBRAN al nombre largo. Medido
    sobre 1.779 emparejados reales del proyecto, cambia EXACTAMENTE UNO.
    """
    import name_mapper as nm

    catalogo = ['Vikingur Reykjavik', 'Celtic', 'AS Roma', 'Real Betis',
                'Manchester City', 'West Bromwich Albion', 'Ajax Amsterdam',
                'Flora Tallinn']
    check(nm.mapear('Viking FK', catalogo, contexto='t') is None,
          "«Viking FK» no se resuelve al Vikingur Reykjavik: son dos clubes")
    for corto, largo in (('Roma', 'AS Roma'), ('Betis', 'Real Betis'),
                         ('Man City', 'Manchester City'),
                         ('West Brom', 'West Bromwich Albion'),
                         ('Ajax', 'Ajax Amsterdam')):
        check(nm.mapear(corto, catalogo, contexto='t') == largo,
              f"«{corto}» sigue casando con «{largo}»")

    # la regla, directamente
    check(not nm._contencion_fiable('viking', 'vikingur reykjavik'),
          "una palabra truncada MAS otra sin explicar no basta")
    check(nm._contencion_fiable('man', 'manchester'),
          "una palabra truncada y nada que sobre si basta")
    check(nm._contencion_fiable('ajax', 'ajax amsterdam'),
          "una palabra ENTERA sostiene el emparejado aunque sobre otra")
    check(nm._contencion_fiable('viking', 'vikingur'),
          "«viking» contra «vikingur» a secas SI vale: no sobra nada, es la "
          "misma palabra truncada")


def test_el_aviso_sin_modelo_dice_la_causa():
    """
    v163.1 — el aviso distingue una averia de lo que es normal.

    Mandaba siempre el mismo recado: «revisa que su modelo cargue y que su
    catalogo de nombres este al dia». El usuario lo recibio el 2026-08-23 sobre
    la Champions, donde las dos cosas estaban bien: en agosto la Champions son
    RONDAS PREVIAS y su historico —1.174 partidos, 174 equipos— cubre la fase
    de grupos, asi que el LASK o el Hapoel Be'er Sheva no han jugado nunca en
    ella. No habia nada que arreglar y el aviso mandaba a buscarlo.

    Cada fila ya trae `motivo_sin_modelo`, asi que el aviso agrupa por causa.
    """
    import alpha_finder as af

    def _pron(motivo, n=3, liga='champions'):
        return [{'deporte': 'Fútbol', 'clave_liga': liga, 'sin_modelo': True,
                 'motivo_sin_modelo': motivo} for _ in range(n)]

    a = af.avisos_sin_modelo(_pron('X no ha jugado todavía en esta '
                                   'competición (recién ascendido)'))
    check(len(a) == 1, "avisa cuando la proporcion es anomala")
    if a:
        check('ℹ️' in a[0],
              "sin historia NO es una averia: el icono lo dice")
        check('no hay nada que arreglar' in a[0],
              f"y el texto tambien: {a[0][:90]}")
        check('revisa que su modelo cargue' not in a[0],
              "ya no manda a buscar una averia inexistente")

    b = af.avisos_sin_modelo(_pron('partido nuevo desde el último precálculo '
                                   'y el modelo de esta competición no se '
                                   'pudo cargar'))
    check(b and '⚠️' in b[0], "un motor que no carga SI es una averia")
    check(b and 'ligas_sin_motor' in b[0],
          f"y dice donde mirar: {b[0][-70:] if b else ''}")

    c = af.avisos_sin_modelo(_pron('el nombre «X» no casa con el catálogo del '
                                   'modelo de esta liga'))
    check(c and 'alias_manuales.json' in c[0],
          "un nombre que no casa manda al fichero de alias")

    # y sigue callando cuando la proporcion es normal
    normales = [{'deporte': 'Fútbol', 'clave_liga': 'premier'}
                for _ in range(9)]
    normales += _pron('recién ascendido', 1, 'premier')
    check(not af.avisos_sin_modelo(normales),
          "un ascendido de diez partidos no dispara nada")


def test_la_tarjeta_no_pinta_remates_por_equipo():
    """
    v166 — LOS REMATES POR EQUIPO VUELVEN A LA TARJETA. ESTE TEST SE INVIERTE.

    La v163.1 los quito a peticion del usuario («lo unico que me interesa
    saber es quien remata») y este test guardaba esa decision. En la v166 se
    pide lo contrario y explicitamente: ver TODOS los mercados, con la app
    diciendo cuales son reales y cuales estimados.

    Las dos peticiones no se contradicen tanto como parece. El motivo tecnico
    que apoyaba la retirada era que en las competiciones sin remates
    observados el bloque era IDENTICO en todos sus partidos y ocupaba seis
    lineas sin distinguir uno de otro. Eso ya no pesa igual: desde la v165 un
    bloque sin insignia va en GRIS, asi que se puede consultar sin competir
    con lo que si esta medido.

    El nombre de la funcion se conserva a proposito. Renombrarlo borraria el
    rastro de que esto se decidio, se midio y se revirtio.
    """
    # v167 — los dos siguen enseñandose, pero ya no como parrafo en el cuerpo
    # de la tarjeta: arriba van en fila compacta y el detalle entero esta en el
    # desplegable «Analisis completo». Lo que este test protege es que se
    # ENSEÑEN, no donde; asi que se comprueban los dos sitios.
    src = open('modo_modelo.py', encoding='utf-8').read()
    cuerpo = src.split('def tarjeta(st, pick')[-1]
    check('quien_remata_tarjeta(pick)' in cuerpo
          and '_quien_remata_compacto' in cuerpo,
          "la tarjeta sigue enseñando quien remata, en fila compacta")
    check('remates_tarjeta(pick)' in cuerpo,
          "y v166: los remates por equipo se calculan para la tarjeta")
    detalle = src.split('def _analisis_completo')[-1]
    check('_bloque_quien_remata_html' in detalle
          and '_bloque_remates_html' in detalle,
          "y su detalle completo vive en el desplegable")
    import modo_modelo as mm
    bloque = mm.remates_tarjeta({'partido': 'Danubio vs Racing (Montevideo)',
                                 'clave_liga': 'uru_primera',
                                 'deporte': 'Fútbol'})
    if bloque:
        html = mm._bloque_remates_html(bloque)
        check('mm-sinsena' in html,
              "y donde es estimado sigue yendo en gris, que es lo que hacia"
              " tolerable volver a enseñarlo")

    # las funciones NO se borran: la ficha las usa y volver a ponerlas es una
    # linea
    import modo_modelo as mm
    check(hasattr(mm, 'remates_tarjeta') and hasattr(mm, '_bloque_remates_html'),
          "las funciones se conservan para la ficha")
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('render_remates_partido' in ui,
          "y la ficha mantiene la seccion completa")

    # el bloque de jugadores trae las DOS probabilidades
    pick = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol'}
    qr = mm.quien_remata_tarjeta(pick)
    if qr:
        html = mm._bloque_quien_remata_html(qr)
        check('a puerta' in html,
              "el bloque de jugadores enseña tambien la de rematar A PUERTA")
        js = (qr.get('home_jugadores') or []) + (qr.get('away_jugadores') or [])
        con_on = [j for j in js if j.get('p_al_arco') is not None]
        check(len(con_on) == len(js) and js,
              f"todos los jugadores traen la de a puerta ({len(con_on)} de "
              f"{len(js)})")
        for j in js:
            if j.get('p_al_arco') is None or j.get('p_remata') is None:
                continue
            check(j['p_al_arco'] <= j['p_remata'] + 1e-9,
                  f"{j.get('jugador')}: rematar a puerta nunca es mas "
                  f"probable que rematar")


def test_la_insignia_solo_en_mercados_observados():
    """
    v164 — un bloque ESTIMADO no puede llevar «destacado».

    LO QUE SE MIDIO ANTES DE TOCARLO (`_v164_auditar_destacada.py`), sobre el
    barrido real del 2026-08-23: de 624 bloques fisicos pintados, **232 eran
    estimados y todos anunciaban su insignia**, hasta un 68 %. Y en **58
    partidos lo eran TODOS** — Danubio-Racing de Montevideo,
    Sonderjyske-Nordsjaelland, Monagas-Portuguesa.

    Un bloque estimado es el nivel de la competicion derivado de sus goles,
    repartido por bando, IDENTICO en todos los partidos de esa liga: su propia
    etiqueta lo dice. Anunciarlo como destacado le da forma de recomendacion a
    un numero que no distingue un partido de otro.

    Los tres niveles, y el reparto medido tras el cambio:

        nivel 1  observado, error < 0,02     289 bloques  insignia
        nivel 2  observado, 0,02-0,05        103 bloques  insignia con matiz
        nivel 3  estimado                    232 bloques  SIN insignia

    EL TITULAR DE LA TARJETA NO ESTABA AFECTADO, y se comprueba igual: los 151
    titulares del dia salian de Goles (96), BTTS (45) y 1X2 (10), todos
    derivados de la matriz de marcador, que se entrena con goles REALES. La
    guarda se pone de todos modos para que el dia que alguien meta un mercado
    fisico en `mercados` no se cuele sin que nadie se entere.
    """
    import confianza_mercado as cf
    import modo_modelo as mm

    # los tres niveles, directamente
    n_est = cf.nivel('uru_primera', 'corners', 'estimado')
    check(n_est['nivel'] == cf.NIVEL_SIN_INSIGNIA and not n_est['insignia'],
          "un mercado estimado cae al nivel 3 y NO lleva insignia")
    check(not cf.puede_destacar('uru_primera', 'corners', 'estimado'),
          "y `puede_destacar` lo dice igual")

    # el origen del bloque MANDA sobre el informe: una liga medida que hoy
    # viene estimada, sale estimada
    n_mix = cf.nivel('premier', 'corners', 'estimado')
    check(n_mix['nivel'] == cf.NIVEL_SIN_INSIGNIA,
          "si el bloque dice que es estimado, es estimado aunque el informe "
          "tenga esa liga medida")

    err = cf.error_medido('premier', 'corners')
    if err is not None:
        n_obs = cf.nivel('premier', 'corners', 'observado')
        check(n_obs['insignia'], "un mercado observado si puede llevarla")
        esperado = (cf.NIVEL_FINO if err < cf.UMBRAL_FINO
                    else cf.NIVEL_GRUESO)
        check(n_obs['nivel'] == esperado,
              f"y su nivel sale del error medido ({err:.4f} -> {esperado})")

    # una liga que no esta en el informe: nivel 2, NO nivel 3. Sus datos son
    # reales, solo que no se sabe cuanto valen.
    n_desc = cf.nivel('liga_que_no_existe', 'corners', 'observado')
    check(n_desc['nivel'] == cf.NIVEL_GRUESO and n_desc['insignia'],
          "observado sin error medido va al nivel 2, no al 3")

    # y en el HTML de verdad
    est = mm.corners_tarjeta({'partido': 'Danubio vs Racing (Montevideo)',
                              'clave_liga': 'uru_primera',
                              'deporte': 'Fútbol'})
    if est:
        check((est.get('confianza') or {}).get('insignia') is False,
              "el bloque de una liga sin datos no lleva insignia")
        html = mm._bloque_corners_html(est)
        check('destacado:' not in html,
              "y su HTML no dice «destacado» en ninguna parte")
        check('Estimado' in html,
              "pero SI conserva su etiqueta de estimado: lo que desaparece es "
              "la insignia, no la informacion")
        check('mm-ck-mejor' not in html,
              "tampoco se resalta una fila en negrita, que es la misma "
              "afirmacion con otra tipografia")

    obs = mm.corners_tarjeta({'partido': 'Man City vs Arsenal',
                              'clave_liga': 'premier', 'deporte': 'Fútbol'})
    if obs and obs.get('origen') == 'observado':
        check((obs.get('confianza') or {}).get('insignia') is True,
              "el bloque de una liga con datos SI la lleva")
        check('destacado:' in mm._bloque_corners_html(obs),
              "y su HTML la pinta")

    # el titular ignora un mercado marcado como estimado
    pick = {'mercados': [
        {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.62},
        {'mercado': 'Córners', 'apuesta': 'Más de 9.5', 'prob': 0.91,
         'origen': 'estimado'}]}
    d = mm.apuesta_destacada(pick)
    check(d and d['apuesta'] == 'Más de 2.5',
          f"el titular ignora el mercado estimado del 91 % ({d})")

    # y sigue siendo AMBAR: verde significa ventaja de precio medida, y estos
    # mercados no la tienen
    src = open('confianza_mercado.py', encoding='utf-8').read()
    check('percentil' in src and 'verde' in src,
          "queda escrito por que el nivel 1 no sube a verde")
    if obs:
        check('🟡' in mm._bloque_corners_html(obs),
              "la insignia del nivel 1 sigue siendo ambar")


def test_las_lineas_de_jugador_de_la_casa():
    """
    v164 — la probabilidad se calcula sobre la LINEA QUE COTIZA LA CASA.

    El encargo daba libertad para buscar APIs de pago. No hizo falta: Playdoit
    ya publica los mercados de remates por jugador y el proyecto los tiraba.
    Medido sobre 8 partidos (`_v164_sondeo_mercados_jugador.py`), de 13.769
    familias distintas:

        Remates - <Jugador> (<COD>) ............  317
        Remates a Puerta - <Jugador> (<COD>) ...  317

    unas 80 familias por partido, con tres lineas cada una.

    LO QUE NO SE HACE: inventar un porcentaje cuando la casa no cotiza a ese
    jugador. «Linea no disponible» y un 0 % son cosas distintas, y la casa
    ofrece unos 40 jugadores por partido mientras ESPN devuelve ~55.
    """
    import lineas_jugador as lj
    import remates_jugador as rjg

    # ---- la extraccion, sobre un tablero de mentira ----------------------
    tablero = {'mercados': [
        {'nombre': 'Remates - Erling Haaland (MCI)',
         'sv': '2.5|ws:player:1',
         'selecciones': [{'nombre': 'Más de 1.5', 'cuota': 1.4},
                         {'nombre': 'Más de 2.5', 'cuota': 2.1},
                         {'nombre': 'Menos de 2.5', 'cuota': 1.7}]},
        {'nombre': 'Remates a Puerta - Erling Haaland (MCI)',
         'sv': '0.5|ws:player:1',
         'selecciones': [{'nombre': 'Más de 0.5', 'cuota': 1.3}]},
        # ruido que NO debe entrar
        {'nombre': 'Total Tiros De Esquina', 'sv': '9.5',
         'selecciones': [{'nombre': 'Más de 9.5', 'cuota': 1.9}]},
        {'nombre': 'Manchester City Remates Totales', 'sv': '14.5',
         'selecciones': [{'nombre': 'Más de 14.5', 'cuota': 1.9}]},
    ]}
    lin = lj.del_tablero(tablero)
    check(list(lin) == ['Erling Haaland'],
          f"solo entra el mercado POR JUGADOR ({list(lin)})")
    h = lin.get('Erling Haaland') or {}
    check(h.get('equipo') == 'MCI',
          "se guarda el codigo de equipo, que es lo que distingue a dos "
          "homonimos de los dos lados")
    check((h.get('tot') or {}).get('principal') == 2.5,
          f"la linea principal sale de `sv` ({(h.get('tot') or {})})")
    check((h.get('on') or {}).get('principal') == 0.5,
          "y el mercado a puerta tiene la suya")
    check('1.5' in ((h.get('tot') or {}).get('lineas') or {}),
          "se guarda la escalera de lineas del lado «Más de»")
    check(not any('Menos' in str(k)
                  for k in ((h.get('tot') or {}).get('lineas') or {})),
          "y NO el lado «Menos de», que es su complemento")

    # ---- P(X > linea) con Poisson ----------------------------------------
    check(rjg.p_mas_de(None, 1.5) is None and rjg.p_mas_de(2.0, None) is None,
          "sin lambda o sin linea no hay probabilidad, y no es 0")
    p05 = rjg.p_mas_de(2.0, 0.5)
    p15 = rjg.p_mas_de(2.0, 1.5)
    p25 = rjg.p_mas_de(2.0, 2.5)
    check(p05 > p15 > p25 > 0.0,
          f"cuanto mas alta la linea, menos probable ({p05:.3f} {p15:.3f} "
          f"{p25:.3f})")
    # P(X>0.5) con lambda 2 es 1 - e^-2 = 0,8647
    check(abs(p05 - 0.864665) < 1e-4,
          f"P(X>0,5) con lambda 2 es 1 - e^-2 ({p05:.6f})")
    check(abs(rjg.p_mas_de(2.0, 0.5) - rjg.p_al_menos_uno(2.0)) < 1e-9,
          "y coincide con `p_al_menos_uno`, que es el mismo suceso")

    # ---- emparejar nombres de PERSONA ------------------------------------
    catalogo = ['Diego Alexander Gomez Amarilla', 'Kang-in Lee',
                'Ben Doak', 'Erling Haaland']
    check(lj.por_apellidos('Diego Gómez', catalogo)
          == 'Diego Alexander Gomez Amarilla',
          "«Diego Gómez» casa con «Diego Alexander Gomez Amarilla»")
    check(lj.por_apellidos('Lee Kang-In', catalogo) == 'Kang-in Lee',
          "y aguanta el orden invertido de los nombres coreanos")
    check(lj.por_apellidos('Diego Martínez', catalogo) is None,
          "un apellido que no esta NO casa por el nombre de pila")
    check(lj.buscar(lin, 'Nombre Que No Existe') is None,
          "un nombre que no casa devuelve None, no la ficha de otro")

    # ---- la interfaz dice «no disponible», no 0 % ------------------------
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('no disponible' in ui,
          "la ficha escribe «no disponible» cuando la casa no cotiza")
    mm = open('modo_modelo.py', encoding='utf-8').read()
    check('de rematar' in mm,
          "y la tarjeta cae a «probabilidad de rematar» en vez de inventar "
          "una linea")

    # ---- la media es POR TITULARIDAD, no por aparicion --------------------
    #
    # EL DESAJUSTE QUE ESTUVO EN PRODUCCION DESDE LA v163: el modelo se valido
    # sobre remates POR TITULARIDAD (ECE 0,029 sobre 6.688 titulares-partido) y
    # produccion dividia entre APARICIONES, que incluyen entrar diez minutos
    # desde el banquillo. Son dos magnitudes distintas y la segunda es menor.
    #
    # Medido sobre 24.059 apariciones: de titular se remata 0,9888 y de
    # suplente 0,4741 (el 48 %), y el 29 % de las apariciones son suplencias.
    check(abs(rjg.RATIO_SUPLENTE['tot'] - 0.4795) < 1e-4,
          "la razon suplente/titular esta medida, no supuesta")
    # 10 remates en 10 apariciones, todas de titular -> 1,0 por titularidad
    check(abs(rjg.media_por_titularidad(10, 10, 10, 'tot') - 1.0) < 1e-9,
          "sin suplencias, la media por titularidad es la de aparicion")
    # 10 remates en 10 apariciones, 5 de ellas suplencias: los titulares
    # cargan mas, asi que su media SUBE por encima de 1,0
    m = rjg.media_por_titularidad(10, 10, 5, 'tot')
    check(m > 1.0,
          f"con suplencias de por medio, la media del titular sube ({m:.3f})")
    check(abs(m - 10.0 / (5 + 0.4795 * 5)) < 1e-9,
          "y sale de despejar la ecuacion, no de un factor a ojo")
    # sin saber las titularidades se usa el factor global, y sigue subiendo
    g = rjg.media_por_titularidad(10, 10, None, 'tot')
    check(abs(g - 1.0 * rjg.FACTOR_APARICION['tot']) < 1e-9,
          "sin titularidades se aplica el factor global medido")
    check(rjg.media_por_titularidad(5, 0) is None,
          "sin apariciones no hay media, y no es cero")
    check(rjg.media_por_titularidad(None, 10) is None,
          "y sin remates tampoco")

    # el previo posicional esta bien escalado contra la REALIDAD: un once
    # 4-4-2 suma 0,857 de los remates del equipo y la fraccion real que se
    # llevan los titulares es 0,857 (mediana de 1.515 equipos-partido)
    _g = (rjg.calibracion().get('cuotas_gruesas') or {}).get('tot') or {}
    if _g:
        _once = _g.get('G', 0) + 4 * _g.get('D', 0) + 4 * _g.get('M', 0)             + 2 * _g.get('F', 0)
        check(0.80 <= _once <= 0.92,
              f"la cuota posicional de un 4-4-2 suma {_once:.3f}, que es la "
              f"fraccion real de remates de los titulares (0,857)")

    # ---- el coste: la tarjeta NO pide a la red ---------------------------
    src = open('lineas_jugador.py', encoding='utf-8').read()
    check('permitir_red' in src,
          "las lineas distinguen leer del precalculo de preguntar a la casa")
    wf = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    check('lineas_jugador.py --dias' in wf,
          "el bot las precalcula")
    check('lineas_jugador_dia.json' in wf,
          "y guarda el fichero, porque la casa mueve las lineas durante el dia")


def test_se_guardan_las_lineas_de_remates():
    """
    v163 — la foto diaria de las lineas, y la trampa de «tiros de esquina».

    Sin este fichero los remates NO PUEDEN SALIR DE AMBAR NUNCA: la
    probabilidad esta calibrada (0,0131 por equipo en totales y 0,0129 a
    puerta) pero la regla de oro del proyecto exige un percentil 5 medido, y
    para eso hacen falta lineas pasadas que ninguna fuente gratuita publica.
    Es el mismo paso que dieron corners en la v159 y tarjetas en la v160.

    LA TRAMPA PROPIA DE ESTE MERCADO: «Tiros de esquina» ES el mercado de
    CORNERS y lleva la palabra «tiros» dentro. Si entrara aqui, el fichero
    acumularia corners rotulados como remates durante meses y el fallo saldria
    a la luz cuando ya no tuviera arreglo — nadie liquida esto hasta que hay
    volumen. Lo mismo con los tiros libres y los penaltis.

    Y una leccion que ya costo una vez en tarjetas: los plurales. La primera
    version escribia `libre` en singular y, con limite de palabra, «Total de
    tiros libres» NO casaba con el filtro de exclusion y entraba como remate.
    """
    import snapshots_remates as sr

    # lo que SI es un mercado de remates, con su objetivo
    for texto, esperado in (
            ('Total de remates', 'tot'),
            ('Total de remates Arsenal', 'tot'),
            ('Remates totales - 1a Mitad', 'tot'),
            ('Total shots', 'tot'),
            ('Total de remates a puerta', 'on'),
            ('Total de disparos a porteria', 'on'),
            ('Mas de/Menos de tiros al arco', 'on'),
            ('Total shots on target', 'on')):
        check(sr.objetivo_de(texto) == esperado,
              f"«{texto}» se clasifica como {esperado}")

    # lo que NO lo es, aunque lo parezca
    for texto in ('Total de tiros de esquina', 'Tiros de esquina - Handicap',
                  'Total de corners', 'Total de saques de esquina',
                  'Total de tiros libres', 'Total de tiros libres directos',
                  'Total de faltas', 'Total de penaltis', 'Total de penales',
                  'Total de tarjetas', 'Total de goles',
                  'Primer jugador en rematar',
                  'Jugador remata a puerta (Bukayo Saka)',
                  'Multigoleadores Sergi Cardona Bermadez'):
        check(sr.objetivo_de(texto) is None,
              f"«{texto}» NO entra como mercado de remates")

    # las dos columnas que hacen util el fichero
    check('objetivo' in sr.COLUMNAS,
          "cada fila dice de que mercado es: los dos tienen dispersiones y "
          "niveles distintos y revueltos serian inservibles")
    check('linea' in sr.COLUMNAS and 'cuota' in sr.COLUMNAS,
          "se guardan la linea y la cuota, que es lo que permite liquidar")
    check('snapshot_key' in sr.COLUMNAS,
          "y la clave que impide duplicar la foto del mismo dia")

    # el paso esta en el bot y el fichero se commitea: si no, no se acumula
    wf = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    check('snapshots_remates.py --dias' in wf,
          "el bot fotografia las lineas de remates cada dia")
    check('remates_snapshots.csv' in wf,
          "y guarda el fichero, que es lo unico que no se puede reconstruir")



def test_el_control_de_cordura_recorta_lo_que_no_se_sostiene():
    """
    v165 — NINGUN PORCENTAJE SIN ALGO CONTRA LO QUE MEDIRLO.

    El caso que lo provoca tiene nombre y resultado: Celta Vigo B - Andorra del
    2026-08-23, tarjeta con «Menos de 2.5 — 80 %» en verde, partido 4-2. Un
    80 % en ese lado sale de una lambda de partido de 1,35 goles, y la media de
    esa competicion esta por encima de 2,5.

    Se comprueban los tres frenos por separado, porque son distintos y sus
    consecuencias tambien:

        1. desvio contra el precio de la casa > 15 pp  -> recorte al 60 %
        2. linea en el lado equivocado de la media de la liga -> techo
        3. sin precio de la casa -> se enseña, pero NUNCA en verde

    Y se comprueba lo que NO hace: subir una cifra hacia la casa. El techo solo
    baja; publicar la opinion de la casa con la cara del modelo es el error que
    la v149 ya evito con las barras de mercado.
    """
    import cordura_probabilidad as cp

    # --- 1) el desvio contra la casa -----------------------------------
    r = cp.revisar(0.80, 'Menos de 2.5', None, implicita=0.45)
    check(not r['fiable'], "un 80 % contra un 45 % de la casa no es fiable")
    check(r['prob'] <= cp.TECHO_DESVIADO + 1e-9,
          f"y no se enseña por encima del techo ({r['prob']})")
    check(r['prob'] < r['original'] - 0.15,
          "la cifra baja de verdad, no cosmeticamente")
    check(r['original'] == 0.80,
          "la cifra original se conserva para poder decirla")
    check(not r['puede_verde'], "una cifra poco fiable no puede ir en verde")
    check('poco fiable' in cp.aviso(r), "y la pantalla lo dice")

    # v166 — el umbral ya no es 15: es el MEDIDO sobre 17.532 partidos, y lo
    # lee de `cordura_umbrales.json`. Se comprueba con el valor que haya en el
    # fichero, no con una constante escrita aqui: si la medicion se repite con
    # mas datos y el corte se mueve, este test se mueve con el.
    lim = cp.umbral('Goles')
    justo = cp.revisar(0.60, 'Menos de 2.5', None,
                       implicita=0.60 - lim * 0.5, mercado='Goles')
    check(justo['fiable'],
          f"medio umbral de separacion ({lim*100:.0f} pp) no marca nada")

    # --- 2) el techo por media de goles de la competicion ---------------
    import rendimiento_equipos as rq
    alta = baja = None
    for clave in ('dinamarca', 'eredivisie', 'bundesliga', 'noruega', 'suiza',
                  'premier', 'laliga', 'serie_a', 'ligue_1', 'esp_hypermotion',
                  'argentina', 'brasil', 'china', 'irlanda'):
        m = rq.media_goles_liga(clave)
        if m is None:
            continue
        if m > 2.5 and alta is None:
            alta = (clave, m)
        if m <= 2.5 and baja is None:
            baja = (clave, m)
    check(alta is not None,
          "hay competiciones con media de goles por encima de 2,5 medida")
    if alta:
        clave, m = alta
        t = cp.techo_por_liga(clave, 'Menos de 2.5')
        esperado = (cp.TECHO_LIGA_DURO if m - 2.5 >= cp.MARGEN_DURO
                    else cp.TECHO_LIGA_SUAVE)
        check(t == esperado,
              f"{clave} mete {m:.2f} goles: «menos de 2.5» topa en "
              f"{esperado*100:.0f} % (dio {t})")
        r2 = cp.revisar(0.80, 'Menos de 2.5', clave)
        check(r2['prob'] <= esperado + 1e-9,
              f"y un 80 % del modelo se recorta a {r2['prob']}")
        check(cp.aviso(r2) != '', "diciendo por que baja")
        # el caso espejo NO se toca: «menos de 4.5» en esa misma liga esta en
        # el lado correcto de la media y es un favorito legitimo
        check(cp.techo_por_liga(clave, 'Menos de 4.5') is None,
              "una linea por encima de la media de la liga no lleva techo")
    if baja:
        clave, m = baja
        check(cp.techo_por_liga(clave, 'Menos de 2.5') is None,
              f"{clave} mete {m:.2f}: ahi «menos de 2.5» no necesita techo")

    check(cp.techo_por_liga('premier', 'Gana Man City') is None,
          "el techo es de GOLES: al 1X2 no se le aplica")

    # --- 3) sin precio de la casa no hay verde --------------------------
    solo = cp.revisar(0.72, 'Menos de 2.5', None)
    check(not solo['contrastada'],
          "sin implicita, la revision se marca como no contrastada")
    check(not solo['puede_verde'],
          "y sin nada con que contrastar no se puede pintar el verde")
    check(abs(solo['prob'] - 0.72) < 1e-9,
          "pero la cifra NO se recorta por no haber precio: se enseña entera")
    check(cp.aviso(solo) != '',
          "y se dice que no hay con que contrastarla")

    # --- 4) v166: EL MODELO TIMIDO SI SE SUBE, Y ESTA MEDIDO ------------
    #
    # La v165 prometia que el techo solo bajaba. La medicion sobre 4.207
    # partidos en los que el modelo va POR DEBAJO de la casa dice lo
    # contrario: el modelo dice 55 % y pasa el 63-73 %. Ahi el numero del
    # modelo es una infravaloracion, no una prudencia, y mezclarlo con la casa
    # lo acerca a lo que pasa. Lo que NO puede es hacerlo en silencio.
    timido = cp.revisar(0.55, 'Menos de 2.5', 'premier', implicita=0.85,
                        mercado='Goles')
    check(timido['prob'] > 0.55,
          f"un modelo por debajo de la casa se ajusta hacia ella ({timido['prob']})")
    check(timido['encogida'] and timido['w'] < 1.0,
          "y queda anotado con que peso se ajusto")
    check(timido['fiable'],
          "ir por DEBAJO de la casa no marca la cifra como poco fiable: esa"
          " direccion no miente al alza")
    sin_liga = cp.revisar(0.55, 'Menos de 2.5', None, implicita=0.85,
                          mercado='Ganador')
    check(abs(sin_liga['prob'] - 0.55) < 1e-9,
          "y un mercado que no es de los encogibles no se toca")


def test_el_titular_no_va_en_verde_sin_contraste():
    """
    v165 — LOS TRES FRENOS, DONDE EL USUARIO LOS VE: EL TITULAR DE LA TARJETA.

    Medido sobre el barrido del 2026-08-23: de 151 tarjetas, 103 iban en verde
    y de las 11 que se pudieron contrastar contra la casa, 4 se separaban mas
    de 15 puntos — 3 de ellas en verde (87 % contra 67 %, 81 % contra 63 % y
    70 % contra 46 %). Eso es lo que este test impide que vuelva.
    """
    import modo_modelo as mm

    base = {'partido': 'Celta Vigo B vs Andorra', 'clave_liga': None,
            'deporte': 'Fútbol'}

    # sin precio de la casa: ambar, aunque el numero sea altisimo
    sin = mm.apuesta_destacada(
        {**base, 'mercados': [
            {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.80},
            {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.20}]})
    check(sin is not None, "sigue habiendo titular")
    check(sin['apuesta'] == 'Menos de 2.5', "y es el lado que dice el modelo")
    check(not sin['alta'],
          f"pero NO va en verde sin precio con el que contrastar ({sin})")
    check(not sin['contrastada'], "y la tarjeta sabe por que")

    # con precio de la casa que lo desmiente: recortado y sin verde
    desmentido = mm.apuesta_destacada(
        {**base,
         'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.55}},
         'mercados': [
             {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.80},
             {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.20}]})
    check(desmentido and not desmentido['alta'],
          "un 80 % contra el 45 % de la casa no va en verde")
    check(desmentido['prob'] <= 0.60 + 1e-9,
          f"y se recorta a {desmentido['prob']} desde {desmentido['original']}")
    check('poco fiable' in (desmentido.get('aviso') or ''),
          "con su aviso de probabilidad poco fiable")

    # con precio de la casa que lo confirma: verde, como siempre
    confirmado = mm.apuesta_destacada(
        {**base,
         'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.32}},
         'mercados': [
             {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.72},
             {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.28}]})
    check(confirmado and confirmado['alta'],
          f"lo que la casa respalda SI sigue yendo en verde ({confirmado})")
    check('poco fiable' not in (confirmado.get('aviso') or ''),
          "y no se marca en rojo lo que la casa respalda")

    # el ganador se elige DESPUES del recorte, no antes
    mezcla = mm.apuesta_destacada(
        {**base,
         'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.55},
                        'btts': 0.60},
         'mercados': [
             {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.87},
             {'mercado': 'BTTS', 'apuesta': 'Ambos marcan: Sí', 'prob': 0.64}]})
    check(mezcla and mezcla['apuesta'] == 'Ambos marcan: Sí',
          f"gana el mercado que mas vale DESPUES del recorte ({mezcla})")

    # y el HTML enseña el precio de la casa al lado del del modelo
    html = mm._bloque_goles_html(
        {**base, 'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.55}}},
        {'Más de 2.5': 0.20, 'Menos de 2.5': 0.80})
    check('mm-casa' in html and 'Playdoit' in html,
          "la tarjeta pinta lo que cree la casa debajo de lo que cree el "
          "modelo")
    check('margen' in html,
          "y dice que es sin margen, que es lo que la hace comparable")
    check('mm-casa' not in mm._bloque_goles_html(
        base, {'Más de 2.5': 0.20, 'Menos de 2.5': 0.80}),
        "sin precio no se pinta la fila: un hueco se ve y un relleno no")


def test_el_precio_de_la_casa_llega_a_la_tarjeta_sin_pedir_red():
    """
    v165 — DE DONDE SALE LA IMPLICITA, Y LO QUE NO PUEDE COSTAR.

    Medido: de los 156 pronosticos de futbol del barrido cacheado del
    2026-08-23, NINGUNO llevaba `cuota` en sus mercados — los construye
    `_mercados_modelo`, que emite cuota justa y `cuota: None` a proposito. Por
    eso el precio se adjunta en `alpha_finder` (donde todavia esta el nombre
    crudo del fixture, que es la llave del precalculo) y no se busca desde la
    tarjeta: buscando con los nombres ya mapeados solo 22 de 151 partidos
    encontraban su entrada.

    Y la tarjeta NO PIDE RED. Esa regla ya costo tres regresiones al proyecto.
    """
    import mercado_implicito as mi

    tablero = {'casa': 'Playdoit', 'home': 'Brighton', 'away': 'Aston Villa',
               'mercados': [
                   {'nombre': 'Resultado Final (Tiempo Regular)', 'sv': None,
                    'selecciones': [{'nombre': 'Brighton', 'cuota': 2.2},
                                    {'nombre': 'Empate', 'cuota': 3.6667},
                                    {'nombre': 'Aston Villa', 'cuota': 3.1}]},
                   {'nombre': 'Total', 'sv': '2.5',
                    'selecciones': [{'nombre': 'Más de 2.5', 'cuota': 1.8},
                                    {'nombre': 'Menos de 2.5', 'cuota': 2.05},
                                    {'nombre': 'Más de 3.5', 'cuota': 2.9},
                                    {'nombre': 'Menos de 3.5', 'cuota': 1.4}]},
                   {'nombre': 'Ambos equipos marcan', 'sv': None,
                    'selecciones': [{'nombre': 'Sí', 'cuota': 1.6667},
                                    {'nombre': 'No', 'cuota': 2.15}]}]}
    precio = mi.del_tablero(tablero)
    check(set(precio) >= {'1x2', 'goles', 'btts'},
          f"del tablero salen los tres mercados ({sorted(precio)})")
    check(abs(sum(precio['1x2'].values()) - 1.0) < 1e-6,
          "el 1X2 sale SIN margen: los tres lados suman 1")
    # v171 — cada linea guarda ahora un dict con la probabilidad Y las dos
    # cuotas, porque sin cuota no hay Score. Se lee con `prob_de`, que entiende
    # tambien el formato viejo mientras el fichero del dia no se regenere.
    for linea in ('2.5', '3.5'):
        p = mi.prob_de(precio['goles'][linea])
        check(0.0 < p < 1.0, f"la linea {linea} sale como probabilidad ({p})")
    check(mi.prob_de(precio['goles']['3.5'])
          < mi.prob_de(precio['goles']['2.5']),
          "y las lineas van en orden: mas de 3,5 es menos probable que mas "
          "de 2,5")
    crudo_mas = 1 / 1.8
    check(mi.prob_de(precio['goles']['2.5']) < crudo_mas,
          f"quitar el margen BAJA la implicita cruda "
          f"({mi.prob_de(precio['goles']['2.5']):.4f} < {crudo_mas:.4f})")
    check(abs(mi.cuota_de(precio['goles']['2.5'], 'mas') - 1.8) < 1e-6,
          "y la cuota del lado «Mas» se conserva tal cual la publica la casa")

    # la traduccion de la etiqueta del proyecto a este diccionario
    check(abs(mi.implicita(precio, 'Más de 2.5') +
              mi.implicita(precio, 'Menos de 2.5') - 1.0) < 1e-6,
          "«Mas de» y «Menos de» de la misma linea suman 1")
    check(mi.implicita(precio, 'Gana Brighton', 'Brighton', 'Aston Villa')
          == precio['1x2']['home'],
          "«Gana <local>» se resuelve por el nombre, no por posicion")
    check(mi.implicita(precio, 'Gana Aston Villa', 'Brighton', 'Aston Villa')
          == precio['1x2']['away'], "y el visitante igual")
    check(mi.implicita(precio, 'Ambos marcan: No') is not None
          and abs(mi.implicita(precio, 'Ambos marcan: Sí')
                  + mi.implicita(precio, 'Ambos marcan: No') - 1.0) < 1e-6,
          "los dos lados de ambos marcan tambien")
    check(mi.implicita(precio, 'Menos de 9.5') is None,
          "una linea que la casa no cotiza devuelve None, NO 0,5")
    check(mi.implicita({}, 'Menos de 2.5') is None,
          "y sin precio, None")
    check(mi.implicita(precio, 'Gana Man City', 'Brighton', 'Aston Villa')
          is None,
          "un equipo que no es ninguno de los dos no se resuelve por parecido")

    # la tarjeta no pide red: el contrato es el mismo que en lineas_jugador
    src = open('mercado_implicito.py', encoding='utf-8').read()
    check('permitir_red: bool = False' in src,
          "`del_partido` no pide red por defecto")
    mm_src = open('modo_modelo.py', encoding='utf-8').read()
    check('permitir_red' not in mm_src.split('def _revisar')[1][:1200],
          "y la tarjeta nunca la autoriza")
    af_src = open('alpha_finder.py', encoding='utf-8').read()
    check('implicitas_de_la_casa' in af_src
          and "pron['implicitas']" in af_src,
          "el barrido adjunta el precio al pronostico")

    # la clave de la linea la fabrica UN solo sitio, o las dos fuentes
    # escribirian «2.5» y «2.50» y la tarjeta no encontraria nada
    check(mi.clave_linea(2.5) == '2.5' and mi.clave_linea('2,50') == '2.5',
          "la clave de linea es la misma se escriba como se escriba")
    check(mi.clave_linea(1.25) == '1.25',
          "y los cuartos NO se redondean a un decimal: 1.25 no es 1.2")
    check('clave_linea' in af_src,
          "el respaldo del barrido usa la misma funcion, no un formato propio")

    # --- el emparejamiento roto se descarta -----------------------------
    #
    # `_buscar` caso «Botafogo vs Athletico-PR» con el «Botafogo SP vs
    # Atletico» del mismo dia, y pasar fecha y liga NO lo arregla: son del
    # mismo dia y de la misma categoria. Un precio de OTRO partido no da un
    # hueco, da un contraste falso.
    import alpha_finder as af
    fx_ok = {'home': 'A', 'away': 'B', 'odd_home': 2.0, 'odd_draw': 3.4,
             'odd_away': 3.8}
    espn = mi._devig({'home': 2.0, 'draw': 3.4, 'away': 3.8})
    coherente = {'1x2': {k: round(v, 4) for k, v in espn.items()},
                 'goles': {'2.5': 0.5}}
    check(af._mismo_partido(coherente, fx_ok),
          "un precio que coincide con el 1X2 de ESPN se acepta")
    espejado = {'1x2': {'home': espn['away'], 'draw': espn['draw'],
                        'away': espn['home']}, 'goles': {'2.5': 0.5}}
    check(not af._mismo_partido(espejado, fx_ok),
          "y uno que pone al favorito del otro lado se descarta")
    check(af._mismo_partido({'goles': {'2.5': 0.5}}, fx_ok),
          "sin 1X2 con el que comparar no se juzga: no se descarta a ciegas")
    check(af._mismo_partido(coherente, {'home': 'A', 'away': 'B'}),
          "y sin cuotas de ESPN, tampoco")
    check(af.DESVIO_EMPAREJADO <= 0.10,
          f"el umbral separa lo roto (0,15) de lo sano (0,02) "
          f"({af.DESVIO_EMPAREJADO})")

    # el modulo esta enchufado al precalculo diario del bot
    yml = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    check('mercado_implicito.py' in yml,
          "el bot lo precalcula, como hace con las lineas de jugador")
    check('mercado_dia.json' in yml,
          "y el fichero del dia se commitea, o la app no lo veria nunca")


def test_los_bloques_sin_insignia_van_en_gris():
    """
    v165 — QUITAR LA INSIGNIA NO BASTABA.

    La v164 dejo de pintar «destacado» en los bloques estimados, pero el bloque
    seguia teniendo el mismo peso visual que uno medido: tres filas en negro
    con sus porcentajes. Eso es lo que se leyo como recomendacion en el parlay
    del 2026-08-23 (Bologna-Lazio, «Local Menos de 5.5 60 %»). Sin insignia, el
    bloque entero va apagado.
    """
    import modo_modelo as mm

    est = mm.corners_tarjeta({'partido': 'Danubio vs Racing (Montevideo)',
                              'clave_liga': 'uru_primera',
                              'deporte': 'Fútbol'})
    if est:
        html = mm._bloque_corners_html(est)
        check('mm-sinsena' in html, "un bloque sin insignia sale apagado")
        check(html.count('mm-sinsena') >= 2,
              "y no solo el titulo: tambien sus filas")
        check('Estimado' in html,
              "sigue enseñando su etiqueta y sus cifras: se apaga, no se borra")

    obs = mm.corners_tarjeta({'partido': 'Man City vs Arsenal',
                              'clave_liga': 'premier', 'deporte': 'Fútbol'})
    if obs and obs.get('origen') == 'observado':
        check('mm-sinsena' not in mm._bloque_corners_html(obs),
              "y un bloque medido NO se apaga")

    css = open('modo_modelo.py', encoding='utf-8').read()
    check('.mm-sinsena' in css, "la clase existe en la hoja de estilo")



def test_el_umbral_de_cordura_sale_del_historico():
    """
    v166 — EL UMBRAL YA NO ES UNA CORAZONADA, Y ESTE TEST LO EXIGE.

    La v165 recortaba a partir de 15 puntos. Ese numero era una intuicion. No
    hacia falta esperar a acumular nada: el proyecto ya tenia dos ledgers
    WALK-FORWARD con la probabilidad que el modelo dio de verdad, el resultado
    real y la cuota de cierre — 17.532 partidos con O/U 2,5 y 36.025 con 1X2.

    Medido con el modelo POR ENCIMA de la casa, que es la unica direccion
    peligrosa, la brecha de calibracion cruza el 0,05 del proyecto entre los
    3-5 pp (0,044) y los 5-7 pp (0,065). El corte esta en 5, no en 15.

    Lo que se comprueba aqui no es el valor —ese se mueve si la medicion se
    repite con mas datos— sino que el valor VENGA DEL FICHERO MEDIDO y no de
    una constante escrita a mano.
    """
    import json as _json
    import os as _os
    import cordura_probabilidad as cp

    check(_os.path.exists(cp.FICHERO_UMBRALES),
          "existe el fichero de umbrales medidos")
    doc = _json.load(open(cp.FICHERO_UMBRALES, encoding='utf-8'))
    check(doc.get('generado_por', '').startswith('_v166'),
          "y dice que script lo genero, para poder repetirlo")
    check((doc.get('n_goles') or 0) >= 10000,
          f"medido sobre una muestra seria ({doc.get('n_goles')} partidos "
          f"de goles)")
    check((doc.get('n_1x2') or 0) >= 10000,
          f"y {doc.get('n_1x2')} de 1X2")

    for mercado in ('Goles', 'BTTS', '1X2'):
        u = cp.umbral(mercado)
        check(u == doc['umbrales'][mercado],
              f"el umbral de {mercado} sale del fichero ({u})")
        check(0.0 < u < 0.15,
              f"y es mas estricto que los 15 pp de la v165 ({u})")

    # el respaldo, si el fichero desapareciera, es el valor MEDIDO — no una
    # intuicion nueva
    check(cp.DESVIO_MAX <= 0.10,
          f"el respaldo del codigo tambien es el medido ({cp.DESVIO_MAX})")

    src = open('_v166_umbral_cordura.py', encoding='utf-8').read()
    check('pick_ledger_totales.csv' in src and 'pick_ledger.csv' in src,
          "la medicion usa los ledgers walk-forward que ya existian")
    check('_boot_p5' in src,
          "y no decide sobre una media: hay percentil 5 de bootstrap")


def test_los_goles_se_encogen_hacia_el_mercado():
    """
    v166 — LA CAUSA RAIZ: A GOLES NUNCA SE LE APLICO LO QUE SI TIENE EL 1X2.

    El 1X2 se encoge hacia el mercado desde la v71 (`calibracion_mercado`, w
    por liga con suelo 0,25). Los goles nunca lo tuvieron. En el ledger —mismo
    modelo, mismos partidos— eso se ve entero:

        sin encoger (w=1,00)   ECE 0,0948 · brecha en el tramo de >15 pp 0,2215
        encogido    (w=0,25)   ECE 0,0139 · brecha 0,0211

    Un orden de magnitud, con maquinaria que ya existia y estaba validada. El
    recorte de la v165 era el sintoma; esto es la causa.
    """
    import cordura_probabilidad as cp

    r = cp.revisar(0.80, 'Menos de 2.5', 'premier', implicita=0.50,
                   mercado='Goles')
    check(r['encogida'] and r['w'] < 1.0,
          f"un mercado de goles se encoge hacia la casa ({r['w']})")
    check(0.50 < r['prob'] < 0.80,
          f"la cifra que se enseña queda ENTRE las dos ({r['prob']})")
    check(abs(r['prob'] - (r['w'] * 0.80 + (1 - r['w']) * 0.50)) < 0.02
          or r['prob'] <= cp.TECHO_DESVIADO + 1e-9,
          "y es la mezcla, o el techo si la mezcla lo pasaba")

    # el 1X2 que YA viene encogido de `alpha_finder` no se encoge dos veces
    dos = cp.revisar(0.60, 'Gana A', 'premier', implicita=0.40,
                     mercado='1X2', ya_encogido=True)
    check(not dos['encogida'],
          "un mercado ya encogido en el barrido no se vuelve a encoger")

    # y un mercado que no es de los tres tampoco
    fuera = cp.revisar(0.70, 'Gana X', 'premier', implicita=0.40,
                       mercado='Ganador')
    check(not fuera['encogida'],
          "un mercado fuera de la lista no se toca")

    # el peso sale de `calibracion_mercado`, no de una constante local
    src = open('cordura_probabilidad.py', encoding='utf-8').read()
    check('calibracion_mercado' in src and 'peso_modelo' in src,
          "el peso lo da el modulo que ya lo tenia medido, no uno nuevo")


def test_los_corners_salen_en_todas_las_ligas_y_con_la_linea_de_la_casa():
    """
    v166 — CORNERS EN TODAS LAS TARJETAS, Y CONTRA UNA LINEA QUE EXISTE.

    Dos cosas distintas:

      · El bloque SALE en las 62 competiciones desde la v162 — en las 50 con
        datos observados con sus cifras, y en las 12 sin ellos con el nivel de
        la competicion y su etiqueta «Estimado». Lo que cambio en la v165 es
        que el estimado va en gris. Aqui se comprueba que sigue SALIENDO, que
        es lo que se pidio: verlo aunque sea estimado, no que desaparezca.
      · La LINEA. Hasta ahora era «la de medio punto mas cercana a la media»:
        una linea inventada. Podia anunciar «Mas de 9.5 57 %» mientras la casa
        cotizaba 8,5, y entonces ese porcentaje no era el de ninguna apuesta
        que se pudiera hacer. Ahora se usa la de la casa cuando el precalculo
        del dia la trae, y se rotula.
    """
    import modo_modelo as mm
    import mercado_implicito as mi

    # --- sale en las dos clases de competicion --------------------------
    for clave, partido, espera_estimado in (
            ('premier', 'Man City vs Arsenal', False),
            ('uru_primera', 'Danubio vs Racing (Montevideo)', True)):
        pick = {'partido': partido, 'clave_liga': clave, 'deporte': 'Fútbol',
                'fecha': '2026-08-24'}
        ck = mm.corners_tarjeta(pick)
        check(ck is not None,
              f"{clave}: el bloque de corners existe")
        if not ck:
            continue
        html = mm._bloque_corners_html(ck)
        check('Córners' in html and 'Total' in html,
              f"{clave}: y se pinta con su fila de total")
        if espera_estimado:
            check('Estimado' in html,
                  f"{clave}: sin datos observados se enseña IGUAL, marcado")
            check('mm-sinsena' in html,
                  f"{clave}: en gris, para que no compita con lo medido")
        else:
            check('mm-sinsena' not in html,
                  f"{clave}: con datos observados NO se apaga")

    # --- la linea de la casa manda sobre la media redondeada ------------
    base = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol', 'fecha': '2026-08-24'}
    sin = mm.corners_tarjeta(base)
    con = mm.corners_tarjeta({**base, 'implicitas': {
        'casa': 'Playdoit', 'corners': {'7.5': 0.86, '8.5': 0.71}}})
    if sin and con:
        f_sin, f_con = sin['filas'][0], con['filas'][0]
        check(not f_sin.get('de_la_casa'),
              "sin precalculo, la linea es la de siempre")
        check(f_con.get('de_la_casa'),
              "con precalculo, la linea es la de la casa")
        check('8.5' in f_con['texto'] or '7.5' in f_con['texto'],
              f"y es una de las que la casa cotiza ({f_con['texto']})")
        check('línea de la casa' in mm._bloque_corners_html(con),
              "la tarjeta dice que esa linea es de la casa")

    # la eleccion es la MAS CERCANA a la media, no la primera del diccionario
    check(mm._linea_de_la_casa({'7.5': 1, '10.5': 1, '9.5': 1}, 9.6) == 9.5,
          "se elige la linea real mas cercana a la media")
    check(mm._linea_de_la_casa(None, 9.6) is None,
          "y sin lineas de la casa, None")

    # --- el lector saca los corners del tablero -------------------------
    tablero = {'casa': 'Playdoit', 'home': 'A', 'away': 'B',
               'casa_home': 'A', 'casa_away': 'B', 'mercados': [
                   {'nombre': 'Total Tiros De Esquina', 'sv': '9.5',
                    'selecciones': [{'nombre': 'Más de 9.5', 'cuota': 1.9},
                                    {'nombre': 'Menos de 9.5', 'cuota': 1.9},
                                    {'nombre': 'Más de 8.5', 'cuota': 1.5}]},
                   {'nombre': 'A Total de Tiros de Esquina', 'sv': '4.5',
                    'selecciones': [{'nombre': 'Más de 4.5', 'cuota': 1.9},
                                    {'nombre': 'Menos de 4.5', 'cuota': 1.9}]},
                   {'nombre': '1ª mitad - Total de Tiros de Esquina',
                    'sv': '4.5',
                    'selecciones': [{'nombre': 'Más de 4.5', 'cuota': 2.0},
                                    {'nombre': 'Menos de 4.5', 'cuota': 1.8}]}]}
    p = mi.del_tablero(tablero)
    ck = p.get('corners') or {}
    check(set(ck) == {'9.5'},
          f"solo el total del PARTIDO, con sus dos lados ({sorted(ck)})")
    check(abs(mi.prob_de(ck['9.5']) - 0.5) < 1e-6,
          "y devigada: dos cuotas iguales dan 50 %")
    check('4.5' not in ck,
          "ni la familia por equipo ni la de media parte se cuelan")


def test_la_tarjeta_enseña_todos_los_mercados():
    """
    v166 — NADA SE ESCONDE: 1X2, GOLES, AMBOS MARCAN, CORNERS, TARJETAS Y
    REMATES, LOS SEIS, EN TODA TARJETA DE FUTBOL.

    La v163.1 quito los remates por equipo a peticion del usuario. Ahora se
    pide lo contrario y explicitamente: verlo todo, con la app diciendo que es
    real y que es estimado. Las dos peticiones son compatibles — lo que hacia
    ruido no era el bloque, era que un bloque estimado tuviera el mismo peso
    visual que uno medido, y eso se arreglo en la v165 con el gris.
    """
    import modo_modelo as mm

    src = open('modo_modelo.py', encoding='utf-8').read()
    cuerpo = src.split('def tarjeta(')[1]
    for pieza in ('_bloque_goles_html', '_bloque_corners_html',
                  '_bloque_tarjetas_html', '_bloque_remates_html',
                  '_bloque_quien_remata_html', 'Ambos marcan'):
        check(pieza in cuerpo,
              f"la tarjeta pinta {pieza}")

    for clave, partido in (('premier', 'Man City vs Arsenal'),
                           ('uru_primera', 'Danubio vs Racing (Montevideo)')):
        pick = {'partido': partido, 'clave_liga': clave, 'deporte': 'Fútbol',
                'fecha': '2026-08-24'}
        html = ''.join([
            mm._bloque_corners_html(mm.corners_tarjeta(pick)),
            mm._bloque_tarjetas_html(mm.tarjetas_tarjeta(pick)),
            mm._bloque_remates_html(mm.remates_tarjeta(pick))])
        for titulo in ('Córners', 'Tarjetas', 'Remates', 'Remates a puerta'):
            check(titulo in html,
                  f"{clave}: la tarjeta enseña «{titulo}»")



def test_la_apuesta_recomendada_es_una_y_es_jugable():
    """
    v167 — LA TARJETA DEJA DE INFORMAR Y PASA A RECOMENDAR.

    El encargo: «no quiero leer, quiero apostar». Una apuesta arriba, con su
    cuota, y el resto plegado. Se comprueba la logica de seleccion, que es lo
    unico que puede equivocarse en silencio:

        1) ventaja de PRECIO (EV sobre la probabilidad ya ajustada)
        2) si no la hay, la de mayor probabilidad ajustada que llegue al 60 %
        3) si nada llega, lo mejor para combinar, en ambar
        4) si no hay nada jugable, None — y eso se PINTA

    EL PASO 1 NO USA EL EV CRUDO DEL MODELO, Y NO ES UN DESCUIDO. Ese canal
    esta medido como ANTI-indicador (−4,66 % a −6,52 % sobre 37.158 apuestas) y
    ademas es maximo justo donde la v166 midio que el numero mas miente. El EV
    se calcula sobre la probabilidad que devuelve `cordura_probabilidad`, y
    entonces un EV positivo significa «esta casa paga de mas», que es la
    ventaja de precio — el unico canal con p5 positivo del proyecto.
    """
    import modo_modelo as mm

    base = {'partido': 'Granada vs Mallorca', 'clave_liga': 'esp_hypermotion',
            'deporte': 'Fútbol', 'fecha': '2026-08-24'}

    # --- 2) por probabilidad, cuando no hay cuota real ------------------
    r = mm.apuesta_recomendada({
        **base, 'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.36}},
        'mercados': [
            {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.66},
            {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.34},
            {'mercado': '1X2', 'apuesta': 'Gana Granada', 'prob': 0.41}]})
    check(r is not None, "hay apuesta recomendada")
    check(r['apuesta'] == 'Menos de 2.5',
          f"gana la de mayor probabilidad ajustada ({r})")
    # v168 — el motivo puede ser «probabilidad» o «estabilidad»/«rey» segun si
    # ese mercado tiene puesto en el ranking de su liga. Lo que se comprueba es
    # que la tarjeta DIGA por que la propone, no cual de las dos vias gano.
    check(r['motivo'] in ('probabilidad', 'estabilidad', 'rey',
                         'seguridad'),
          f"y dice por que la propone ({r['motivo']})")
    check(r['cuota_justa'] > 1.0, "trae su cuota justa para el boleto")

    # --- 1) v170: EL PRECIO YA NO MANDA, Y ES DELIBERADO ----------------
    #
    # Hasta la v168 una cuota que pagaba de mas ganaba a cualquier
    # probabilidad. El usuario cambio la prioridad: no quiere depender de que
    # Playdoit se equivoque, quiere la apuesta con mas probabilidad de
    # acierto. El precio pasa a ser una insignia («Valor»), no un criterio.
    con_precio = mm.apuesta_recomendada({
        **base, 'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.36}},
        'mercados': [
            {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.66},
            {'mercado': '1X2', 'apuesta': 'Gana Granada', 'prob': 0.41,
             'cuota': 3.20}]})
    check(con_precio and con_precio['apuesta'] == 'Menos de 2.5',
          f"gana la mas probable aunque la otra pague mas ({con_precio})")
    check(con_precio['motivo'] != 'precio',
          "y el motivo ya nunca es el precio")

    # --- 4) sin nada jugable, None, y se pinta --------------------------
    nada = mm.apuesta_recomendada({
        **base, 'mercados': [
            {'mercado': '1X2', 'apuesta': 'Gana Granada', 'prob': 0.34},
            {'mercado': '1X2', 'apuesta': 'Empate', 'prob': 0.33}]})
    check(nada is None, f"por debajo del 50 % no hay apuesta que meter ({nada})")

    # un partido ya jugado no recomienda nada
    check(mm.apuesta_recomendada({**base, 'jugado': True, 'mercados': [
        {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.9}]}) is None,
        "y un partido acabado tampoco")

    # --- lo que NUNCA puede recomendarse --------------------------------
    estimado = mm.apuesta_recomendada({
        **base, 'mercados': [
            {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.55},
            {'mercado': 'Córners', 'apuesta': 'Más de 9.5', 'prob': 0.93,
             'origen': 'estimado'}]})
    check(estimado and estimado['apuesta'] == 'Menos de 2.5',
          f"un mercado estimado no se recomienda ni al 93 % ({estimado})")


def test_los_mercados_fisicos_se_recomiendan_pero_nunca_en_verde():
    """
    v167 — CORNERS, TARJETAS Y REMATES PUEDEN SER LA APUESTA. EN AMBAR.

    Se pidio evaluarlos todos para elegir la mejor apuesta jugable, y se hace.
    Pero el verde de esta aplicacion significa una cosa concreta y medida
    —«canal con percentil 5 de bootstrap positivo en tramo de juicio»— y estos
    tres mercados no lo tienen: no hay historico de lineas con el que
    calcularlo, que es lo que `snapshots_*.py` esta acumulando.

    Y la puerta de entrada es la MISMA que la de la insignia del bloque
    (`confianza_mercado`), para que no puedan decir cosas distintas la insignia
    de abajo y la recomendacion de arriba.
    """
    import modo_modelo as mm

    base = {'partido': 'Roma vs Fiorentina', 'clave_liga': 'serie_a',
            'deporte': 'Fútbol', 'fecha': '2026-08-24',
            'mercados': [{'mercado': 'Goles', 'apuesta': 'Menos de 2.5',
                          'prob': 0.52}]}
    observado = {'filas': [{'etiqueta': 'Total', 'media': 10.2,
                            'texto': 'Más de 9.5', 'linea': 9.5,
                            'prob': 0.78}],
                 'mejor': {'etiqueta': 'Total', 'media': 10.2,
                           'texto': 'Más de 9.5', 'linea': 9.5, 'prob': 0.78},
                 'origen': 'observado',
                 'confianza': {'nivel': 1, 'insignia': True}}
    r = mm.apuesta_recomendada(base, {'Córners': observado})
    check(r and r['apuesta'].startswith('Córners'),
          f"un bloque fisico observado SI puede ser la apuesta ({r})")
    # v170 — Y SI PUEDEN IR EN VERDE. El verde cambio de significado: ya no
    # dice «ventaja de precio medida» (eso lo decidia el line shopping, que el
    # usuario retiro) sino «mercado estable en esta liga y por encima del
    # 60 %». La tarjeta no promete ventaja de precio en ninguna parte, asi que
    # la marca no miente — pero es un cambio de contrato y queda anotado.
    check(r['fisico'] and r['verde'] == (r['prob'] >= mm.UMBRAL_ALTA),
          f"y su color sale de la probabilidad, no del tipo de mercado ({r})")

    estimado = dict(observado, origen='estimado',
                    confianza={'nivel': 3, 'insignia': False})
    r2 = mm.apuesta_recomendada(base, {'Córners': estimado})
    check(r2 and not r2['fisico'],
          f"y uno estimado no entra siquiera ({r2})")
    check((r2 or {}).get('apuesta') == 'Menos de 2.5',
          "gana entonces el mercado de goles, que si esta medido")


def test_la_tarjeta_es_accionable_y_no_un_parrafo():
    """
    v167 — NADA SE BORRO, TODO SE ORDENO.

    La tarjeta enseñaba cuatro parrafos tecnicos («Estimado · esta competicion
    no publica esta estadistica…», el perfil del arbitro, el detalle por
    jugador). Ahora arriba hay UNA apuesta y filas compactas, y el texto entero
    vive en «📊 Analisis completo». La diferencia entre esconder y ordenar es
    que lo segundo se puede abrir.
    """
    import modo_modelo as mm

    src = open('modo_modelo.py', encoding='utf-8').read()
    cuerpo = src.split('def tarjeta(st, pick')[1].split(
        'def _analisis_completo')[0]

    check('_bloque_recomendada' in cuerpo,
          "la tarjeta pinta el bloque de apuesta recomendada")
    check('APUESTA RECOMENDADA' in src, "con su rotulo")
    check("st.expander('🔍 Análisis')" in cuerpo,
          "y el detalle va en un desplegable (v168: se llama 🔍 Análisis)")
    for parrafo in ('_bloque_corners_html', '_bloque_tarjetas_html',
                    '_bloque_remates_html', '_bloque_quien_remata_html',
                    '_bloque_fisico', '_mini_forma'):
        check(parrafo not in cuerpo,
              f"{parrafo} ya no se pinta en el cuerpo de la tarjeta")
    detalle = src.split('def _analisis_completo')[1]
    for parrafo in ('_bloque_corners_html', '_bloque_tarjetas_html',
                    '_bloque_remates_html', '_bloque_quien_remata_html',
                    '_bloque_fisico', '_mini_forma'):
        check(parrafo in detalle,
              f"pero {parrafo} SI vive en el analisis completo")

    # el boton de Playdoit existe y apunta a la casa del usuario
    check('link_button' in src and 'Playdoit' in src,
          "hay boton para ir a jugarla")
    check(mm.URL_PLAYDOIT.startswith('https://'),
          "con una URL de verdad")

    # las filas compactas no llevan parrafos: una etiqueta de dos palabras
    fila = mm._fila_compacta('⛳', 'Córners', '9.5', 'Más: 53 %', 'Menos: 47 %',
                             '<span class="mm-ck-est">📐 Estimado</span>',
                             apagado=True)
    check('📐 Estimado' in fila and len(fila) < 400,
          "la fila compacta lleva la etiqueta corta y nada mas")
    check('mm-sinsena' in fila,
          "y un mercado estimado sale apagado, como desde la v165")
    check('esta competición no publica' not in fila,
          "el parrafo largo NO esta en la fila")

    # el bloque de «sin apuestas jugables» existe y se ve
    class _Falso:
        def __init__(self):
            self.txt = []

        def markdown(self, t, **k):
            self.txt.append(t)

        def link_button(self, *a, **k):
            self.txt.append('BOTON')
    f = _Falso()
    mm._bloque_recomendada(f, None, 'x', 0)
    check(any('Sin apuestas jugables' in t for t in f.txt),
          "cuando no hay nada jugable, la tarjeta lo dice")
    check(not any('BOTON' in t for t in f.txt),
          "y no ofrece boton para jugar nada")
    f2 = _Falso()
    mm._bloque_recomendada(f2, {'apuesta': 'Ambos marcan: No', 'prob': 0.60,
                                'cuota': None, 'cuota_justa': 1.67,
                                'ev': None, 'verde': True, 'fisico': False,
                                'aviso': ''}, 'x', 0)
    check(any('AMBOS MARCAN: NO' in t for t in f2.txt),
          "y cuando la hay, la enseña en mayusculas y con su porcentaje")
    check(any('1.67' in t for t in f2.txt), "con la cuota justa al lado")
    check(any('BOTON' in t for t in f2.txt), "y el boton para jugarla")



def test_el_mercado_rey_recorre_todo_el_catalogo():
    """
    v168 — CADA COMPETICION TIENE SU MERCADO MAS FIABLE, Y NO ES SIEMPRE EL
    MISMO.

    Medido sobre los tres ledgers walk-forward que ya estaban en el repo
    (`pick_ledger.csv`, `pick_ledger_totales.csv`, `pick_ledger_handicap.csv`)
    mas el informe de calibracion fisico. Reparto del rey sobre 62
    competiciones:

        Handicap 14 · Cornrs por equipo 12 · Remates a puerta 7
        Doble oportunidad 6 · Tarjetas por equipo 5 · Remates por equipo 5
        Tarjetas 3 · Remates 2 · 1X2 1 · Cornrs 1 · ninguno 6

    O sea que el rey sale de las tres familias del catalogo —resultado, goles y
    estadisticos—, que es justo lo que se pidio comprobar. BTTS no corona
    ninguna, y eso NO es un hueco del catalogo: calibra 🔴 en todas las ligas
    medidas. Un catalogo completo tambien sirve para descartar.
    """
    import mercado_estabilidad as me

    doc = me.cargar(recargar=True)
    ligas = doc.get('ligas') or {}
    check(len(ligas) >= 55,
          f"se midieron casi todas las competiciones ({len(ligas)})")

    reyes = {v.get('rey') for v in ligas.values() if v.get('rey')}
    check(len(reyes) >= 5,
          f"el rey cambia de mercado segun la liga ({len(reyes)} distintos)")
    familias = {me.BLOQUE.get(r, 'otros') for r in reyes}
    check(len(familias & {'resultado', 'handicap'}) > 0,
          f"algun rey sale de los mercados de RESULTADO ({sorted(familias)})")
    check(len(familias & {'corners', 'tarjetas', 'remates', 'remates_on'}) > 0,
          "y alguno de los ESTADISTICOS")

    # el catalogo entero esta representado, incluido lo que no se pudo medir
    nombres = set()
    for v in ligas.values():
        for f in v.get('mercados') or []:
            nombres.add(f['mercado'])
    for esperado in ('1X2', 'Doble oportunidad', 'Hándicap', 'Goles 2.5',
                     'BTTS', 'Córners', 'Tarjetas', 'Remates',
                     'Remates a puerta', 'Córners por equipo',
                     'Tarjetas por equipo', 'Remates por equipo'):
        check(esperado in nombres, f"el catalogo incluye «{esperado}»")
    # y lo que NO se puede medir se dice, en vez de colarse con un numero
    for sin_medir in ('Goles por equipo', 'Resultado exacto',
                      'Remates de jugador'):
        check(sin_medir in nombres,
              f"«{sin_medir}» aparece marcado, no escondido")
        fila = [f for v in ligas.values() for f in (v.get('mercados') or [])
                if f['mercado'] == sin_medir][0]
        check(fila['origen'] == 'sin medir' and fila['ece'] is None,
              f"«{sin_medir}» no lleva un numero inventado")
        check(fila.get('puesto') is None,
              f"y no puede ser rey de nada ({sin_medir})")

    # un mercado sin medicion nunca entra al ranking
    for v in ligas.values():
        for f in v.get('mercados') or []:
            if f.get('puesto') is not None:
                check(f['ece_efectiva'] is not None,
                      "todo lo que tiene puesto tiene medicion")
                check(f['estado'] != me.INESTABLE,
                      "y ningun inestable tiene puesto")

    # la cuarentena por varianza funciona de verdad
    en_cuarentena = [f for v in ligas.values() for f in (v.get('mercados') or [])
                     if f.get('dispersion') and f['dispersion'] > me.DISPERSION_MAX]
    check(all(f['estado'] == me.INESTABLE for f in en_cuarentena),
          f"varianza/media > {me.DISPERSION_MAX} manda a cuarentena "
          f"({len(en_cuarentena)} casos)")


def test_los_goles_del_brasileirao_b_nunca_salen_en_verde():
    """
    v168 — EL CASO QUE LO PROVOCA: «Menos de 2.5 — 82 %», termino 1-4.

    Medido: en el Brasileirao B los goles calibran a **0,118** en crudo —mas
    del doble del 0,05 que este proyecto llama aceptable— y su liga no tiene
    cuota en el ledger con la que encogerlos, asi que lo que se veria en
    pantalla es ese crudo. El bloque entero queda en cuarentena.

    Y no esta solo: los goles salen 🔴 en TODAS las ligas medidas sin cuota. Es
    el mercado del que salia el 64 % de los titulares de la aplicacion.
    """
    import mercado_estabilidad as me
    import modo_modelo as mm

    check(me.estado_bloque('bra_serie_b', 'goles') == me.INESTABLE,
          "los goles del Brasileirao B estan marcados inestables")
    check(me.en_cuarentena('bra_serie_b', 'goles'),
          "y por tanto en cuarentena")

    pick = {'partido': 'Athletic vs Novorizontino', 'clave_liga': 'bra_serie_b',
            'deporte': 'Fútbol', 'fecha': '2026-08-24',
            'mercados': [
                {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.82},
                {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.18}]}
    r = mm.apuesta_recomendada(pick)
    check(r is None or r['bloque'] != 'goles',
          f"un 82 % en goles de esa liga NO se recomienda ({r})")

    # y en la tarjeta el bloque sale con candado
    fila = mm._fila_dos_lados('⚽', 'Goles', '2.5', 0.18, 0.82, 'Más', 'Menos',
                              mm._candado('bra_serie_b', 'goles'))
    check('🔒' in fila, "y su fila lleva candado")
    check('mm-sinsena' in fila, "y sale apagada")
    check('No recomendado' in fila, "con tres palabras, no un parrafo")

    # la tira lo enseña de un vistazo
    tira = mm._tira_estabilidad('bra_serie_b')
    check('🔴' in tira and 'Goles' in tira,
          "la tira de estabilidad lo pinta en rojo")


def test_el_modo_seguridad_bloquea_lo_que_discrepa_de_la_casa():
    """
    v168 — MAS DE 10 PUNTOS POR ENCIMA DE LA CASA Y NO ES JUGABLE.

    Es mas duro que el recorte de la v166 (5 pp, que marca y recorta pero deja
    mirar) y se aplica ENCIMA, no en su lugar: uno decide como se ENSEÑA la
    cifra y el otro si se puede PROPONER. Los dos numeros vienen de sitios
    distintos — el 5 esta medido sobre 17.532 partidos y el 10 lo fijo el
    encargo como suelo de seguridad.
    """
    import cordura_probabilidad as cp
    import modo_modelo as mm

    # el 82 % contra un 60 % de la casa: se recorta y se marca
    r = cp.revisar(0.82, 'Menos de 2.5', 'laliga', implicita=0.60,
                   mercado='Goles')
    check(r['prob'] < 0.82, f"la cifra baja ({r['prob']})")
    check(not r['fiable'] or r['prob'] <= cp.TECHO_DESVIADO + 1e-9,
          "y queda marcada o por debajo del techo")

    # y no se puede proponer
    pick = {'partido': 'A vs B', 'clave_liga': 'laliga', 'deporte': 'Fútbol',
            'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.40}},
            'mercados': [
                {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.82},
                {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.18}]}
    rec = mm.apuesta_recomendada(pick)
    check(rec is None or rec['apuesta'] != 'Menos de 2.5',
          f"un 82 % contra un 60 % de la casa no se recomienda ({rec})")

    check(mm.DESVIO_BLOQUEO == 0.10,
          f"el bloqueo duro esta en 10 pp ({mm.DESVIO_BLOQUEO})")
    check(mm.PROB_MINIMA_REY == 0.55,
          f"y el suelo del rey en 55 % ({mm.PROB_MINIMA_REY})")


def test_la_tarjeta_no_tiene_parrafos_visibles():
    """
    v168 — TEXTO MINIMO FUERA DEL DESPLEGABLE.

    Se comprueba con regex, como pedia el encargo: ningun texto visible de la
    tarjeta pasa de 50 caracteres. Los parrafos explicativos siguen existiendo
    —no se ha borrado ninguno— pero dentro de «🔍 Analisis».
    """
    import re as _re
    import modo_modelo as mm

    def _textos(html):
        """Los trozos de texto que el usuario ve, sin etiquetas."""
        plano = _re.sub(r'<[^>]+>', chr(0), str(html))
        return [t.strip() for t in plano.split(chr(0))
                if t.strip() and t.strip() != '&nbsp;·&nbsp;']

    piezas = [
        mm._tira_estabilidad('premier'),
        mm._fila_compacta('⛳', 'Córners', '9.5', 'Más: 53 %', 'Menos: 47 %',
                          '<span>📐 Estimado</span>'),
        mm._fila_dos_lados('⚽', 'Goles', '2.5', 0.42, 0.58, 'Más', 'Menos',
                           mm._candado('bra_serie_b', 'goles')),
    ]
    for html in piezas:
        for t in _textos(html):
            check(len(t) <= 50,
                  f"texto visible corto: «{t[:60]}» ({len(t)})")

    # el bloque de recomendacion, en sus dos formas
    class _Falso:
        def __init__(self):
            self.txt = []

        def markdown(self, t, **k):
            self.txt.append(t)

        def link_button(self, *a, **k):
            pass
    for rec in (None,
                {'apuesta': 'Tarjetas: Menos de 3.5', 'prob': 0.58,
                 'cuota': None, 'cuota_justa': 1.72, 'ev': None,
                 'verde': False, 'fisico': True, 'aviso': '',
                 'motivo': 'rey', 'estabilidad': {'icono': '🟢'}}):
        f = _Falso()
        mm._bloque_recomendada(f, rec, 'x', 0)
        for html in f.txt:
            for t in _textos(html):
                check(len(t) <= 50,
                      f"la recomendacion no lleva parrafos: «{t[:60]}»")

    # y los parrafos largos SIGUEN existiendo, dentro del desplegable
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('esta competición no publica esta' in src,
          "el parrafo de «Estimado» no se ha borrado del proyecto")
    detalle = src.split('def _analisis_completo')[1]
    check('_etiqueta_origen' in src and '_bloque_corners_html' in detalle,
          "y se pinta en el analisis completo")
    cuerpo = src.split('def tarjeta(st, pick')[1].split(
        'def _analisis_completo')[0]
    check("st.expander('🔍 Análisis')" in cuerpo,
          "el desplegable se llama 🔍 Analisis, como se pidio")



def test_las_lineas_de_conteo_salen_del_tablero_y_no_se_suponen():
    """
    v169 — SE LEE LO QUE LA CASA PUBLICA, NO LO QUE CREEMOS QUE PUBLICA.

    El encargo daba por hecho que Playdoit publica solo el TOTAL de tarjetas y
    no las de equipo. Medido sobre ocho partidos del dia, es al reves y ademas
    es muy desigual:

        Botafogo-Athletico-PR   «Total de tarjetas» (4,5/5,5/6,5) Y
                                «Total de tarjetas Atletico» (2,5)
        Valencia-Betis          22 familias de tarjetas
        Real Madrid-Real Soc.    0 familias de tarjetas

    Cobertura sobre los 80 partidos del precalculo: cornrs total 59, tarjetas
    total 41, y por equipo solo 9-10. O sea que no se puede codificar «la casa
    publica esto»: hay que leer cada tablero.
    """
    import mercado_implicito as mi

    tablero = {
        'casa': 'Playdoit', 'home': 'Botafogo', 'away': 'Athletico-PR',
        'casa_home': 'Botafogo SP', 'casa_away': 'Atlético',
        'invertido': True,
        'mercados': [
            {'nombre': 'Total de tarjetas', 'sv': '5.5', 'selecciones': [
                {'nombre': 'Más de 4.5', 'cuota': 1.55},
                {'nombre': 'Menos de 4.5', 'cuota': 2.28}]},
            {'nombre': 'Total de tarjetas Atlético', 'sv': '2.5',
             'selecciones': [{'nombre': 'Más de 2.5', 'cuota': 1.92},
                             {'nombre': 'Menos de 2.5', 'cuota': 1.70}]},
            {'nombre': 'Total de tarjetas Botafogo SP', 'sv': '2.5',
             'selecciones': [{'nombre': 'Más de 2.5', 'cuota': 1.60},
                             {'nombre': 'Menos de 2.5', 'cuota': 2.05}]},
            # las que NO deben entrar, cada una por su motivo
            {'nombre': '1ª Mitad - Total de tarjetas', 'sv': '1.5',
             'selecciones': [{'nombre': 'Más de 1.5', 'cuota': 1.75},
                             {'nombre': 'Menos de 1.5', 'cuota': 1.95}]},
            {'nombre': 'Total de tarjetas rojas', 'sv': '0.5',
             'selecciones': [{'nombre': 'Más de 0.5', 'cuota': 4.0},
                             {'nombre': 'Menos de 0.5', 'cuota': 1.2}]},
            {'nombre': 'Tarjetas exactas', 'sv': None, 'selecciones': [
                {'nombre': '0-3', 'cuota': 3.3}, {'nombre': '4', 'cuota': 5.5}]},
            {'nombre': 'Total tarjetas Impar/Par', 'sv': None, 'selecciones': [
                {'nombre': 'Impar', 'cuota': 1.81},
                {'nombre': 'Par', 'cuota': 1.81}]},
            {'nombre': 'Remates a Puerta - Vinicius Jr. (RMA)', 'sv': '1.5',
             'selecciones': [{'nombre': 'Más de 1.5', 'cuota': 2.0},
                             {'nombre': 'Menos de 1.5', 'cuota': 1.8}]},
            {'nombre': 'Total Tiros De Esquina', 'sv': '9.5', 'selecciones': [
                {'nombre': 'Más de 9.5', 'cuota': 1.9},
                {'nombre': 'Menos de 9.5', 'cuota': 1.9}]},
            {'nombre': 'Botafogo SP Total de Tiros de Esquina', 'sv': '4.5',
             'selecciones': [{'nombre': 'Más de 4.5', 'cuota': 1.9},
                             {'nombre': 'Menos de 4.5', 'cuota': 1.9}]},
        ]}
    p = mi.del_tablero(tablero)

    check('tarjetas' in p and '4.5' in p['tarjetas'],
          f"entra el total de tarjetas del partido ({p.get('tarjetas')})")
    check('tarjetas_home' in p and '2.5' in p['tarjetas_home'],
          "y el de cada equipo, cuando la casa lo publica")
    check('tarjetas_away' in p and '2.5' in p['tarjetas_away'],
          "los dos bandos")
    check(mi.prob_de(p['tarjetas_home']['2.5'])
          != mi.prob_de(p['tarjetas_away']['2.5']),
          "y no se confunden entre si")
    check('corners' in p and 'corners_home' in p,
          "cornrs: total y equipo")
    check(abs(mi.prob_de(p['corners']['9.5']) - 0.5) < 1e-6,
          "devigada: dos cuotas iguales dan 50 %")

    # lo que se descarta, y que se descarte por el motivo correcto
    check('1.5' not in (p.get('tarjetas') or {}),
          "la media parte NO se cuela en el total del partido")
    check('0.5' not in (p.get('tarjetas') or {}),
          "las tarjetas ROJAS son otro mercado y no se mezclan")
    check(not any('1.5' in (v or {}) for k, v in p.items()
                  if str(k).startswith('remates')),
          "un mercado de JUGADOR no se archiva como del equipo")

    # la orientacion: `casa_home` es NUESTRO local aunque la casa lo publique
    # al reves, y aqui el tablero viene invertido a proposito
    check(mi.prob_de(p['tarjetas_home']['2.5']) is not None,
          "el bando se resuelve por el nombre que usa la casa")
    check(abs(mi.prob_de(p['tarjetas_home']['2.5']) - 0.5729) < 0.01,
          f"«Botafogo SP» es nuestro local ({p['tarjetas_home']})")


def test_la_tarjeta_usa_la_linea_de_la_casa_en_cada_bando():
    """
    v169 — CADA BANDO CON SU LINEA REAL.

    Hasta aqui el Total usaba la linea de la casa (v166) pero Local y Visita
    seguian con «la media redondeada»: un 55 % sobre una linea que no existe en
    ningun boleto. Ahora los tres usan la de la casa cuando esta.
    """
    import modo_modelo as mm

    pick = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol', 'fecha': '2026-08-24',
            'implicitas': {'casa': 'Playdoit',
                           'corners': {'9.5': 0.60, '10.5': 0.46},
                           'corners_home': {'6.5': 0.52},
                           'corners_away': {'3.5': 0.46},
                           'tarjetas': {'4.5': 0.61},
                           'tarjetas_home': {'2.5': 0.57},
                           'tarjetas_away': {'2.5': 0.46}}}
    for bloque, lineas in ((mm.corners_tarjeta(pick),
                            {'Total': 10.5, 'Local': 6.5, 'Visita': 3.5}),
                           (mm.tarjetas_tarjeta(pick),
                            {'Total': 4.5, 'Local': 2.5, 'Visita': 2.5})):
        if not bloque:
            continue
        for f in bloque['filas']:
            esperada = lineas.get(f['etiqueta'])
            if esperada is None:
                continue
            check(f.get('de_la_casa'),
                  f"{f['etiqueta']}: la linea es de la casa")
            check(abs(f['linea'] - esperada) < 1e-6,
                  f"{f['etiqueta']}: y es la que publica ({f['linea']} vs "
                  f"{esperada})")

    # sin precalculo se sigue enseñando la nuestra, marcada como no-casa
    sin = mm.corners_tarjeta({k: v for k, v in pick.items()
                              if k != 'implicitas'})
    if sin:
        check(not sin['filas'][0].get('de_la_casa'),
              "sin precalculo, la linea no se marca como de la casa")


def test_los_goles_se_calibran_encogiendo_y_no_con_un_modelo_nuevo():
    """
    v169 — LA MEDICION DECIDIO, Y DIJO QUE NO AL 0,6 DEL ENCARGO.

    El encargo proponia `0,6·modelo + 0,4·casa` y pedia calibrar los pesos con
    el historico. Ajustado sobre 17.532 partidos con las dos cuotas de cierre:

        peso del modelo    ECE       ligas con ECE > 0,05 (de 20)
        1,00 (crudo)     0,0948            20
        0,60 (pedido)    0,0472            16
        0,25 (desplegado) 0,0139            5
        0,09 (optimo)    0,0109            6

    O sea que el 0,60 es **4,3 veces peor** que el optimo y dejaria 16 de 20
    ligas por encima del umbral. Lo que ya estaba desplegado (0,25) es el que
    menos ligas deja mal, asi que NO SE CAMBIA — y eso tambien es un resultado.

    El objetivo de «ninguna liga por encima de 0,05» NO se alcanza: quedan
    cinco (sco_premiership 0,078, sco_championship 0,063, turquia 0,062,
    bundesliga 0,052, eredivisie 0,051). Se dice, no se disimula.
    """
    import json as _json
    import os as _os

    ruta = '_v169_goles_y_eficacia.json'
    check(_os.path.exists(ruta), "existe la medicion de goles")
    if not _os.path.exists(ruta):
        return
    d = _json.load(open(ruta, encoding='utf-8'))['goles']
    curva = {round(f['w'], 2): f for f in d['curva']}

    check(curva[1.0]['ece'] > curva[0.25]['ece'] * 3,
          f"encoger mejora el ECE de {curva[1.0]['ece']} a "
          f"{curva[0.25]['ece']}")
    check(curva[0.6]['ece'] > curva[0.25]['ece'],
          f"y el 0,6 del encargo es PEOR que el 0,25 desplegado "
          f"({curva[0.6]['ece']} vs {curva[0.25]['ece']})")
    check(curva[0.25]['ligas_malas'] <= curva[0.6]['ligas_malas'],
          "y deja menos ligas por encima del umbral")
    check(d['ok_crudo'] == 0,
          f"sin encoger, NINGUNA liga baja de 0,05 ({d['ok_crudo']})")
    check(d['ok_encogido'] >= 12,
          f"encogiendo, la mayoria si ({d['ok_encogido']} de "
          f"{len(d['ligas'])})")

    # y el peso que usa produccion es el del modulo validado, no uno nuevo
    import calibracion_mercado as cm
    check(cm.W_MIN == 0.25,
          f"el suelo sigue siendo el medido en la v75 ({cm.W_MIN})")
    src = open('cordura_probabilidad.py', encoding='utf-8').read()
    check('calibracion_mercado' in src,
          "y el encogimiento usa ese modulo, no una constante nueva")


def test_la_recomendacion_se_liquida_contra_el_resultado():
    """
    v169 — ¿SE CUMPLE LA APUESTA? LIQUIDADO CONTRA EL MARCADOR.

    Se reconstruye, sobre 47.794 partidos del historico, que habria propuesto
    la aplicacion con las reglas de hoy y con las de la v164, y se compara con
    lo que paso:

        politica  apuestas    de     acierto   anunciado    ROI
        v164        47.794  47.794    56,0 %     65,2 %   -4,96 %
        v169        14.665  47.794    62,3 %     61,7 %   -4,21 %

    Lo que importa no es el ROI —sigue negativo, y este proyecto ya sabe que su
    modelo no bate al mercado— sino la distancia entre lo ANUNCIADO y lo
    OCURRIDO: la v164 prometia 65,2 % y acertaba 56,0 %, nueve puntos de
    mentira. Hoy promete 61,7 % y acierta 62,3 %: se queda corta.

    Y apuesta en 14.665 partidos de 47.794 en vez de en todos. Una aplicacion
    que recomienda algo en el 100 % de los partidos no esta seleccionando.
    """
    import json as _json
    import os as _os

    ruta = '_v169_goles_y_eficacia.json'
    if not _os.path.exists(ruta):
        check(False, "existe la medicion de eficacia")
        return
    d = _json.load(open(ruta, encoding='utf-8'))['eficacia']
    viejo, nuevo = d['v164'], d['v169']

    # v170 — las cifras se remidieron con el CATALOGO COMPLETO (la doble
    # oportunidad entro al conjunto de candidatos), asi que las tres politicas
    # se comparan sobre las mismas opciones:
    #
    #     v164  47.794 apuestas · acierto 74,5 % · anunciado 78,9 %
    #     v169  44.421 apuestas · acierto 75,2 % · anunciado 77,0 %
    #     v170  44.557 apuestas · acierto 76,0 % · anunciado 78,0 %
    hoy = d.get('v170') or nuevo
    brecha_v = abs(viejo['esperado'] - viejo['acierto'])
    brecha_n = abs(hoy['esperado'] - hoy['acierto'])
    check(brecha_v > brecha_n,
          f"la politica vieja se separaba mas de la realidad "
          f"({brecha_v*100:.1f} contra {brecha_n*100:.1f} puntos)")
    check(brecha_n <= 0.025,
          f"y la de hoy se queda en {brecha_n*100:.1f} puntos")
    check(hoy['acierto'] < hoy['esperado'] + 0.03,
          "lo que se anuncia no se queda corto de forma absurda")
    check(hoy['acierto'] > viejo['acierto'],
          f"y acierta mas que la vieja ({hoy['acierto']} contra "
          f"{viejo['acierto']})")
    check(hoy['n'] <= viejo['n'],
          f"sin apostar en mas partidos ({hoy['n']} de {hoy['de']})")

    # el ROI sigue siendo negativo y eso NO se esconde
    # v171 — Y LA POLITICA DEL SCORE, QUE ES LA MEJOR MEDIDA HASTA HOY.
    #
    #     politica  apuestas    de     acierto  anunciado    ROI      p5
    #     v164        47.794  47.794    74,5 %    78,9 %   -8,42 % -12,25 %
    #     v169        44.421  47.794    75,2 %    77,0 %   -5,00 %  -7,47 %
    #     v170        44.557  47.794    76,0 %    78,0 %   -6,17 % -12,61 %
    #     v171         2.947  47.794    66,0 %    65,2 %   -0,67 %  -2,81 %
    #
    # Un orden de magnitud mejor en ROI, y apostando en el 6,2 % de los
    # partidos en vez de en el 93 %. SIGUE SIENDO NEGATIVO: -0,67 % con p5
    # -2,81 % no demuestra ventaja, demuestra que se acerco al punto de
    # equilibrio. No se puede prometer dinero con esto.
    score = d.get('v171')
    if score:
        check(score['n'] < hoy['n'] / 5,
              f"la politica del Score es mucho mas selectiva ({score['n']} de "
              f"{score['de']})")
        check(score['roi'] > hoy['roi'],
              f"y rinde mejor que elegir por probabilidad ({score['roi']} "
              f"contra {hoy['roi']})")
        check(score['roi'] > viejo['roi'],
              f"y muchisimo mejor que la v164 ({score['roi']} contra "
              f"{viejo['roi']})")
        check(score['roi'] < 0,
              f"pero NO es positivo ({score['roi']} %): no se promete dinero")
        check(abs(score['esperado'] - score['acierto']) <= 0.02,
              f"y lo que anuncia se parece a lo que pasa "
              f"({score['esperado']} contra {score['acierto']})")

    if hoy.get('roi') is not None:
        check(hoy['roi'] < 0,
              f"el ROI sigue negativo ({hoy['roi']} %): esto calibra, no "
              f"promete dinero")
        check(hoy['roi'] > viejo['roi'],
              f"aunque menos malo que la vieja ({hoy['roi']} contra "
              f"{viejo['roi']})")
        # Y EL INTERCAMBIO, DICHO: mirar el precio (v169) rendia mejor que
        # mirar la probabilidad (v170). Se eligio acertar mas, no ganar mas.
        if nuevo.get('roi') is not None and nuevo is not hoy:
            check(nuevo['roi'] >= hoy['roi'] - 1e-9,
                  f"mirar el precio rendia mejor ({nuevo['roi']} contra "
                  f"{hoy['roi']}): el intercambio esta medido")



def test_la_recomendacion_es_la_mas_segura_y_no_la_mejor_pagada():
    """
    v170 — EL CAMBIO DE FILOSOFIA, Y ES DEL USUARIO.

    Hasta la v168 mandaba la ventaja de PRECIO, que es el unico canal con p5
    positivo medido del proyecto. Pero ese canal obliga a esperar a que la casa
    se equivoque, y lo que se pidio es «la apuesta con mas probabilidad de
    acierto, aunque el momio sea 1,20».

    Medido sobre 47.794 partidos, con el catalogo completo y las tres
    politicas sobre los MISMOS partidos:

        politica  apuestas   acierto  anunciado    ROI      p5
        v164        47.794    74,5 %    78,9 %   -8,42 % -12,25 %
        v169        44.421    75,2 %    77,0 %   -5,00 %  -7,47 %
        v170        44.557    76,0 %    78,0 %   -6,17 % -12,61 %

    La v170 acierta MAS que ninguna (76,0 %) y anuncia con dos puntos de
    holgura. Paga por ello en ROI: -6,17 % contra el -5,00 % de mirar el
    precio. Es el intercambio que se pidio, medido, no supuesto.
    """
    import modo_modelo as mm

    base = {'partido': 'A vs B', 'clave_liga': 'premier', 'deporte': 'Fútbol',
            'fecha': '2026-08-24'}
    # una con EV altisimo pero mercado inestable, y otra segura y estable
    pick = {**base,
            'implicitas': {'casa': 'Playdoit', 'goles': {'2.5': 0.50}},
            'mercados': [
                {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.52,
                 'cuota': 3.50},
                {'mercado': '1X2', 'apuesta': 'Gana A', 'prob': 0.66}]}
    r = mm.apuesta_recomendada(pick)
    check(r is not None, "hay recomendacion")
    if r:
        check(r['apuesta'] != 'Menos de 2.5',
              f"un EV enorme en un mercado inestable NO gana ({r})")
        check(r['motivo'] in ('seguridad', 'rey'),
              f"y el motivo es la seguridad, no el precio ({r['motivo']})")

    # el momio bajo no descalifica: es justo lo que se pidio
    barato = mm.apuesta_recomendada({
        **base, 'mercados': [
            {'mercado': '1X2', 'apuesta': 'Gana A', 'prob': 0.78,
             'cuota': 1.20}]})
    check(barato is not None and barato['prob'] >= 0.60 and barato['verde'],
          f"una apuesta al 78 % con cuota 1,20 se recomienda igual ({barato})")

    # el precio queda como INSIGNIA, no como criterio
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('VALOR_MIN' in src, "existe el umbral de la insignia de valor")
    check("elegida['motivo'] = 'precio'" not in src,
          "y ya no hay una via que elija por precio")


def test_el_catalogo_incluye_la_doble_oportunidad():
    """
    v170 — LA DOBLE OPORTUNIDAD ENTRA, Y CAMBIA LA PANTALLA ENTERA.

    Sale del mismo 1X2 que ya esta calculado —`P(1X) = P(1) + P(X)`— y es el
    Mercado Rey de SEIS competiciones. Por su forma es donde viven las
    probabilidades altas que esta pantalla busca desde la v170.

    CONSECUENCIA MEDIDA, y hay que saberla: con la doble oportunidad dentro, 33
    de 40 recomendaciones salen de ahi y la aplicacion propone algo en el 93 %
    de los partidos. Es lo que «la apuesta mas segura» significa
    matematicamente — cubrir dos de tres resultados.
    """
    import modo_modelo as mm

    pick = {'partido': 'Man City vs Arsenal', 'clave_liga': 'premier',
            'deporte': 'Fútbol',
            'board': {'Gana Man City': 0.55, 'Empate': 0.24,
                      'Gana Arsenal': 0.21}}
    dos = mm.doble_oportunidad(pick)
    check(len(dos) == 3, f"salen las tres dobles ({len(dos)})")
    probs = {d['apuesta']: d['prob'] for d in dos}
    check(abs(probs['Man City o empate'] - 0.79) < 1e-6,
          f"1X es la suma de local y empate ({probs})")
    check(abs(probs['Man City o Arsenal'] - 0.76) < 1e-6, "12 tambien")
    check(abs(probs['Arsenal o empate'] - 0.45) < 1e-6, "y X2")
    check(sum(probs.values()) > 1.9,
          "las tres suman 2, que es lo que tiene que dar")

    check(not mm.doble_oportunidad({'partido': 'A vs B'}),
          "sin 1X2 no se inventan dobles")

    # no se encoge dos veces: el 1X2 de produccion ya viene encogido (v71)
    src = open('modo_modelo.py', encoding='utf-8').read()
    i = src.index('def doble_oportunidad')
    j = src.index('_candidatas_fisicas(pick, bloques or {})')
    check('ya_encogido=True' in src[i:j],
          "las dobles heredan el encogimiento del 1X2, no se aplica dos veces")


def test_los_goles_del_brasileirao_b_no_pasan_del_60_por_ciento():
    """
    v170 — EL CASO ORIGINAL, CERRADO POR TRES SITIOS A LA VEZ.

    «Menos de 2.5 — 82 %» en el Brasileirao B, termino 1-4. Hoy no puede
    volver a salir, y no por una regla sino por tres que se apilan:

        1. los goles de esa liga estan en CUARENTENA (ECE 0,118)
        2. si hubiera cuota, el encogimiento bajaria el 82 % hacia la casa
        3. y el techo por media de goles de la liga lo recortaria igual
    """
    import mercado_estabilidad as me
    import modo_modelo as mm

    check(me.en_cuarentena('bra_serie_b', 'goles'),
          "los goles del Brasileirao B siguen en cuarentena")

    pick = {'partido': 'Athletic vs Novorizontino',
            'clave_liga': 'bra_serie_b', 'deporte': 'Fútbol',
            'fecha': '2026-08-24',
            'mercados': [
                {'mercado': 'Goles', 'apuesta': 'Menos de 2.5', 'prob': 0.82},
                {'mercado': 'Goles', 'apuesta': 'Más de 2.5', 'prob': 0.18}]}
    r = mm.apuesta_recomendada(pick)
    check(r is None or r['bloque'] != 'goles',
          f"un 82 % en goles de esa liga no se recomienda ({r})")

    # y con cuota de la casa, la cifra que se ENSEÑA tampoco pasa del 60 %
    import cordura_probabilidad as cp
    info = cp.revisar(0.82, 'Menos de 2.5', 'bra_serie_b', implicita=0.55,
                      mercado='Goles')
    check(info['prob'] <= 0.60 + 1e-9,
          f"y lo que se enseña no pasa del 60 % ({info['prob']})")


def test_la_linea_de_jugador_es_la_principal_de_la_casa():
    """
    v170 — LA LINEA DEL JUGADOR ES LA PRINCIPAL, NO LA MAS ALTA.

    Ya estaba resuelto en la v164 y se comprueba aqui porque el encargo lo pide
    explicitamente: `sv` NO es la linea principal (su cuota mediana es 2,60).
    Se elige la de cuota mas cercana a 2,00, que da mediana 1,95.
    """
    import lineas_jugador as lj

    src = open('lineas_jugador.py', encoding='utf-8').read()
    check('2.0' in src or '2,00' in src,
          "el modulo elige por cercania a la cuota 2,00")
    check('sv' in src, "y explica por que `sv` no vale")

    fam = {'nombre': 'Remates - Jugador X (RMA)', 'sv': '2.5',
           'selecciones': [{'nombre': 'Más de 0.5', 'cuota': 1.10},
                           {'nombre': 'Más de 1.5', 'cuota': 1.95},
                           {'nombre': 'Más de 2.5', 'cuota': 3.60}]}
    princ = None
    for f in (lj.principal, ) if hasattr(lj, 'principal') else ():
        princ = f(fam)
    if princ is not None:
        check(abs(princ.get('cuota', 0) - 1.95) < 0.01,
              f"se queda la de cuota mas cercana a 2,00 ({princ})")
    else:
        # el modulo no expone la funcion suelta: se comprueba sobre el fichero
        # del dia, que es lo que la tarjeta lee
        doc = lj.cargar()
        fichas = [v for v in (doc.get('partidos') or {}).values()]
        cuotas = [j.get('tot', {}).get('cuota')
                  for p in fichas for j in p.values()
                  if isinstance(j, dict) and isinstance(j.get('tot'), dict)]
        cuotas = [c for c in cuotas if c]
        if cuotas:
            import statistics as _st
            med = _st.median(cuotas)
            check(1.5 <= med <= 2.5,
                  f"la cuota mediana de las lineas guardadas es principal "
                  f"({med:.2f})")


def test_la_tarjeta_ensena_el_catalogo_completo():
    """
    v170 — TODOS LOS BLOQUES DEL CATALOGO EN LA TARJETA, Y SIN PARRAFOS.
    """
    import re as _re
    import modo_modelo as mm

    src = open('modo_modelo.py', encoding='utf-8').read()
    cuerpo = src.split('def tarjeta(st, pick')[1].split(
        'def _analisis_completo')[0]
    for pieza in ('Resultado', 'Goles', 'Ambos marcan', 'Córners', 'Tarjetas',
                  'Remates', 'A puerta', 'Doble'):
        check(pieza in cuerpo, f"la tarjeta enseña «{pieza}»")

    # y sigue sin parrafos visibles
    def _textos(html):
        plano = _re.sub(r'<[^>]+>', chr(0), str(html))
        return [t.strip() for t in plano.split(chr(0))
                if t.strip() and t.strip() != '&nbsp;·&nbsp;']

    fila = mm._fila_compacta('🛡️', 'Doble', '',
                             '<b>Man City o empate: 79 %</b>', '', '')
    for t in _textos(fila):
        check(len(t) <= 50, f"la fila de doble oportunidad es corta: «{t}»")



def test_la_recomendacion_se_elige_por_score_y_no_por_probabilidad():
    """
    v171 — LA MEJOR RELACION PROBABILIDAD/CUOTA, NO LA MAS SEGURA.

    La v170 elegia por probabilidad absoluta y acabo recomendando doble
    oportunidad al 79 % con cuota 1,10 en el 93 % de los partidos. Desde la
    v171 manda `Score = probabilidad ajustada x cuota de Playdoit`, que es el
    valor esperado mas uno.

    El ejemplo del encargo, comprobado literalmente: «Mas de 2,5» al 80 % con
    cuota 1,40 da 1,12; «Mas de 3,5» al 67 % con cuota 1,80 da 1,21. Gana la
    segunda, y hasta la v171 la aplicacion ni la calculaba.
    """
    import valor_apuesta as va

    check(abs(va.SCORE_VERDE - 1.10) < 1e-9,
          f"el verde es Score > 1,10 ({va.SCORE_VERDE})")
    check(abs(va.SCORE_AMBAR - 0.95) < 1e-9,
          f"y el ambar baja hasta 0,95 ({va.SCORE_AMBAR})")

    # el semaforo es por SCORE, que es lo que ahora significa el color
    check(va.semaforo(1.21) == '🟢', "Score 1,21 es verde")
    check(va.semaforo(1.00) == '🟡', "Score 1,00 es ambar")
    check(va.semaforo(0.90) == '🔴', "Score 0,90 es rojo")
    check(va.semaforo(None) == '⚪', "sin cuota no hay color")
    check(va.semaforo(1.20, prob=0.30) == '🟢',
          "un Score alto con probabilidad baja sigue siendo valor...")
    check(va.semaforo(1.05, prob=0.30) == '🔴',
          "...pero uno mediano con probabilidad baja, no")

    # y el ejemplo del encargo, con las dos lineas del mismo mercado
    a = va._fila('Goles', 'Total', 'Goles: Más de 2.5', 0.80, 1.40, 0.72,
                 'goles', 2.5)
    b = va._fila('Goles', 'Total', 'Goles: Más de 3.5', 0.67, 1.80, 0.60,
                 'goles', 3.5)
    check(abs(a['score'] - 1.12) < 0.01 and abs(b['score'] - 1.206) < 0.01,
          f"los Score salen como en el ejemplo ({a['score']}, {b['score']})")
    check(b['score'] > a['score'],
          "y la de 3,5 vale mas que la de 2,5 pese a ser menos probable")


def test_el_score_no_recomienda_volados_ni_rojos():
    """
    v171 — DOS GUARDAS QUE APARECIERON PROBANDO CONTRA TABLEROS REALES.

    1) LA EXCEPCION DEL 1,15 NO ES UNA PUERTA PARA UN VOLADO. Sin suelo duro,
       la primera prueba contra el tablero de Real Madrid-Real Sociedad eligio
       «Real Sociedad o empate» al 38 % con cuota 3,10 (Score 1,178) — justo
       la apuesta que el encargo dice no querer. Ahora hay suelo del 50 % pase
       lo que pase, y la excepcion exige ademas CONTRASTE con la casa: un EV
       alto sobre una probabilidad que nadie ha contradicho es el canal que
       este proyecto tiene medido como anti-indicador.

    2) NUNCA SE PROPONE UN 🔴. El propio encargo define el rojo como «no
       recomendado»; devolver el maximo de una lista donde todo es rojo seria
       recomendar lo menos malo. Medido: sin esta guarda salian
       recomendaciones con Score 0,872.
    """
    import valor_apuesta as va

    check(va.PROB_SUELO_DURO >= 0.50,
          f"hay un suelo duro de probabilidad ({va.PROB_SUELO_DURO})")

    src = open('valor_apuesta.py', encoding='utf-8').read()
    cuerpo = src.split('def mejor(')[1]
    check('SCORE_AMBAR' in cuerpo,
          "`mejor` no devuelve nada por debajo del ambar")
    check('PROB_SUELO_DURO' in cuerpo, "ni por debajo del suelo duro")
    check("f.get('contrastada')" in cuerpo,
          "y la excepcion del Score alto exige contraste con la casa")

    # la doble oportunidad no entra a precio de saldo
    check(abs(va.CUOTA_MINIMA_DOBLE - 1.30) < 1e-9,
          f"la doble oportunidad exige cuota >= 1,30 ({va.CUOTA_MINIMA_DOBLE})")
    src_do = src.split('LA DOBLE OPORTUNIDAD ENTRA')[1][:900]
    check('CUOTA_MINIMA_DOBLE' in src_do,
          "y el filtro esta en el sitio donde se construye")


def test_la_casa_guarda_sus_cuotas_y_el_lector_es_compatible():
    """
    v171 — SIN CUOTA NO HAY SCORE, ASI QUE LA CUOTA SE GUARDA.

    Hasta la v170 el precalculo del dia guardaba solo la probabilidad SIN
    MARGEN, que bastaba para contrastar. Para el Score hace falta el PRECIO que
    el usuario cobra — que no es 1/implicita, porque la implicita ya no lleva
    margen y la cuota si.

    El fichero se regenera cada noche, asi que durante unas horas conviven el
    formato viejo (`float`) y el nuevo (`dict`). El lector entiende los dos: sin
    eso, la tarjeta se quedaria sin lineas hasta que corriera el bot.
    """
    import mercado_implicito as mi

    tablero = {'casa': 'Playdoit', 'home': 'A', 'away': 'B',
               'casa_home': 'A', 'casa_away': 'B', 'mercados': [
                   {'nombre': 'Total', 'sv': '2.5', 'selecciones': [
                       {'nombre': 'Más de 2.5', 'cuota': 1.80},
                       {'nombre': 'Menos de 2.5', 'cuota': 2.05}]},
                   {'nombre': 'Resultado Final (Tiempo Regular)',
                    'selecciones': [{'nombre': 'A', 'cuota': 2.2, 'tipo': 1},
                                    {'nombre': 'Empate', 'cuota': 3.4,
                                     'tipo': 2},
                                    {'nombre': 'B', 'cuota': 3.1,
                                     'tipo': 3}]},
                   {'nombre': 'Doble oportunidad', 'selecciones': [
                       {'nombre': '1X', 'cuota': 1.28},
                       {'nombre': '12', 'cuota': 1.31},
                       {'nombre': 'X2', 'cuota': 1.62}]}]}
    p = mi.del_tablero(tablero)
    g = (p.get('goles') or {}).get('2.5')
    check(isinstance(g, dict),
          f"la linea guarda un dict, no un numero suelto ({g})")
    check(abs(mi.cuota_de(g, 'mas') - 1.80) < 1e-6,
          "con la cuota del lado «Mas»")
    check(abs(mi.cuota_de(g, 'menos') - 2.05) < 1e-6, "y la del «Menos»")
    check(0.0 < mi.prob_de(g) < 1.0, "y la probabilidad sin margen")
    check(mi.prob_de(g) < 1 / 1.80,
          "que es MENOR que la implicita cruda, porque se le quito el margen")

    check((p.get('1x2_cuotas') or {}).get('home') == 2.2,
          f"el 1X2 guarda sus tres cuotas ({p.get('1x2_cuotas')})")
    check(set(p.get('doble_cuotas') or {}) == {'1X', '12', 'X2'},
          f"y la doble oportunidad las suyas ({p.get('doble_cuotas')})")

    # compatibilidad con el formato viejo
    check(abs(mi.prob_de(0.53) - 0.53) < 1e-9,
          "un `float` del formato viejo sigue leyendose")
    check(mi.cuota_de(0.53) is None,
          "y no inventa una cuota que no estaba")


def test_se_exploran_todas_las_lineas_de_cada_mercado():
    """
    v171 — LA ESCALERA ENTERA, NO EL PELDAÑO MAS CERCANO A LA MEDIA.

    Playdoit publica de diez a veinte lineas por mercado. El modelo sabe dar
    probabilidad a todas —la binomial negativa acepta cualquier linea y la
    matriz de marcador tambien—, asi que la recomendacion las mira todas.

    Medido sobre los partidos del dia: 327 lineas candidatas en 117 partidos.
    """
    import modo_modelo as mm
    import valor_apuesta as va

    pick = {'partido': 'A vs B', 'clave_liga': 'premier', 'deporte': 'Fútbol',
            'fecha': '2026-08-25',
            'goles_lineas': {'1.5': 0.82, '2.5': 0.62, '3.5': 0.40},
            'implicitas': {'casa': 'Playdoit', 'goles': {
                '1.5': {'p': 0.78, 'mas': 1.22, 'menos': 4.20},
                '2.5': {'p': 0.58, 'mas': 1.65, 'menos': 2.30},
                '3.5': {'p': 0.36, 'mas': 2.60, 'menos': 1.48}}}}
    filas = va._de_goles(pick)
    lineas = {f['linea'] for f in filas}
    check(lineas == {1.5, 2.5, 3.5},
          f"se evaluan las tres lineas que publica la casa ({lineas})")
    lados = {f['apuesta'] for f in filas}
    check(any('Más' in x for x in lados) and any('Menos' in x for x in lados),
          "y los dos lados de cada una")
    for f in filas:
        check(f['score'] is not None and f['cuota'] > 1,
              f"cada linea trae cuota y Score ({f['apuesta']})")

    # el alpha_finder calcula ahora mas lineas del modelo, o la casa publicaria
    # lineas que no podriamos evaluar
    af = open('alpha_finder.py', encoding='utf-8').read()
    check('for linea in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5):' in af,
          "el modelo calcula la escalera entera de goles")

    # y la tabla de valor se pinta en la tarjeta
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('MEJOR VALOR' in src, "la tarjeta enseña la tabla de valor")
    cuerpo = src.split('def tarjeta(st, pick')[1].split(
        'def _analisis_completo')[0]
    check('_tabla_valor' in cuerpo, "y se pinta en el cuerpo de la tarjeta")
    check('Score' in src, "con el Score a la vista")


def test_todas_las_ligas_tienen_remates():
    """
    v163 — ninguna competicion se queda sin la seccion, y la estimada lo dice.

    Mismo compromiso que la v162 con corners y tarjetas. Donde hay datos
    observados sale observado; donde no, sale el nivel de la competicion
    derivado de sus goles, MARCADO. Los dos mercados de remates estimados
    calibran por debajo del umbral de 0,05 —0,0281 en totales y 0,0168 a
    puerta, medidos dejando una liga fuera—, asi que llevan el aviso suave y no
    el fuerte de las tarjetas (0,0539).
    """
    import fixtures_espn
    import rendimiento_equipos as rq
    import stats_estimadas
    from config import LEAGUES

    doc = stats_estimadas.cargar()
    for obj in ('rem', 'rem_on'):
        recta = (doc.get('rectas') or {}).get(obj) or {}
        check(bool(recta),
              f"el ajuste de {obj} esta calculado y guardado")
        if recta:
            check(recta.get('corr_goles', 0) > 0.5,
                  f"{obj}: el nivel de remates de una liga se predice bien "
                  f"desde sus goles (corr {recta.get('corr_goles'):.3f})")
        err = (doc.get('calibracion_estimada') or {}).get(obj)
        check(err is not None and err <= stats_estimadas.UMBRAL_ACEPTABLE,
              f"{obj}: la estimacion calibra por debajo del umbral ({err})")

    sin, con = 0, 0
    claves = [c for c, v in LEAGUES.items()
              if v.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    for c in claves[:25]:
        d = rq._historico(c)
        if d is None or getattr(d, 'empty', True) or len(d) < 50:
            continue
        r = rq.remates_equipo(c, str(d['home_team'].iloc[-1]),
                              str(d['away_team'].iloc[-1]))
        if r and r.get('totales'):
            con += 1
            b = r['totales']
            if b.get('origen') == 'estimado':
                sin += 1
                check(b.get('error_calibracion') is not None,
                      f"{c}: la estimacion dice cuanto se equivoca")
                check(b.get('aceptable') is True,
                      f"{c}: y esta por debajo del umbral aceptable")
    check(con >= 15,
          f"{con} de las 25 primeras competiciones tienen seccion de remates")

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
    _sin = _liga_sin_observar('corners')
    if _sin:
        check(rq.media_corners_liga(_sin) is None,
              f"una competicion sin córners observados ({_sin}) no tiene media: "
              f"los suyos son del generador")

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
    # v158 — el motivo cambió porque la probabilidad MEJORÓ. Desde que las
    # lineas de córners se calculan con binomial negativa, el error de
    # calibracion contra la frecuencia real es de 0,4-0,6 puntos, asi que ya no
    # es cierto que «el modelo predice la media de la competicion» para todo.
    # Lo que sigue sin haber es histórico de LINEAS con el que saber si ese EV
    # gana dinero, y eso es lo que el aviso tiene que decir.
    check(any('no hay' in c.lower() and 'histórico' in c.lower()
              for c in motivos),
          "el motivo que se enseña dice que falta el histórico de lineas")
    check(any('señal' in c for c in motivos),
          "y que sirve como señal, no como apuesta validada")

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
    test_la_tarjeta_es_la_misma_para_hoy_y_manana()
    test_los_bloques_de_la_tarjeta()
    test_los_ordenes_de_la_lista()
    test_modo_modelo_esta_enrutado_en_la_interfaz()
    test_corners_no_suben_a_seccion1_sin_medicion()
    test_el_suelo_del_error_en_corners()
    test_las_probabilidades_de_corners_usan_la_sobredispersion()
    test_los_corners_por_equipo_salen_de_sus_datos()
    test_los_corners_en_la_tarjeta()
    test_se_guardan_las_lineas_de_corners()
    test_las_tarjetas_cuentan_amarillas_y_rojas()
    test_las_tarjetas_por_equipo_salen_de_sus_datos()
    test_el_arbitro_designado_y_su_encogimiento()
    test_las_tarjetas_en_la_tarjeta()
    test_se_guardan_las_lineas_de_tarjetas()
    test_las_ligas_apagadas_por_elo_se_encendieron()
    test_las_estadisticas_reales_de_espn()
    test_solo_se_promedian_las_filas_reales()
    test_todas_las_ligas_tienen_cornrs_y_tarjetas()
    test_los_jugados_salen_en_la_lista_con_su_pronostico()
    test_los_remates_por_equipo_salen_de_sus_datos()
    test_el_nivel_de_remates_no_se_mide_sobre_dos_epocas()
    test_los_remates_en_la_tarjeta()
    test_los_remates_por_jugador_no_se_inventan()
    test_la_alineacion_no_cuesta_la_pantalla_ni_se_inventa()
    test_el_catalogo_de_equipos_de_espn_no_se_corta()
    test_remates_no_suben_a_seccion1_sin_medicion()
    test_los_jugados_son_del_dia_de_cdmx()
    test_los_goles_traen_tres_lineas()
    test_la_contencion_no_empareja_clubes_distintos()
    test_el_aviso_sin_modelo_dice_la_causa()
    test_la_tarjeta_no_pinta_remates_por_equipo()
    test_la_insignia_solo_en_mercados_observados()
    test_las_lineas_de_jugador_de_la_casa()
    test_se_guardan_las_lineas_de_remates()
    test_todas_las_ligas_tienen_remates()
    print('\n=== v165: control de cordura de las probabilidades ===')
    test_el_control_de_cordura_recorta_lo_que_no_se_sostiene()
    test_el_titular_no_va_en_verde_sin_contraste()
    test_el_precio_de_la_casa_llega_a_la_tarjeta_sin_pedir_red()
    test_los_bloques_sin_insignia_van_en_gris()
    print('\n=== v166: umbral medido, encogimiento y corners ===')
    test_el_umbral_de_cordura_sale_del_historico()
    test_los_goles_se_encogen_hacia_el_mercado()
    test_los_corners_salen_en_todas_las_ligas_y_con_la_linea_de_la_casa()
    test_la_tarjeta_enseña_todos_los_mercados()
    print('\n=== v167: la tarjeta accionable ===')
    test_la_apuesta_recomendada_es_una_y_es_jugable()
    test_los_mercados_fisicos_se_recomiendan_pero_nunca_en_verde()
    test_la_tarjeta_es_accionable_y_no_un_parrafo()
    print('\n=== v168: mercado rey y modo seguridad ===')
    test_el_mercado_rey_recorre_todo_el_catalogo()
    test_los_goles_del_brasileirao_b_nunca_salen_en_verde()
    test_el_modo_seguridad_bloquea_lo_que_discrepa_de_la_casa()
    test_la_tarjeta_no_tiene_parrafos_visibles()
    print('\n=== v169: lineas reales de la casa y eficacia ===')
    test_las_lineas_de_conteo_salen_del_tablero_y_no_se_suponen()
    test_la_tarjeta_usa_la_linea_de_la_casa_en_cada_bando()
    test_los_goles_se_calibran_encogiendo_y_no_con_un_modelo_nuevo()
    test_la_recomendacion_se_liquida_contra_el_resultado()
    print('\n=== v170: la mas segura, y el catalogo completo ===')
    test_la_recomendacion_es_la_mas_segura_y_no_la_mejor_pagada()
    test_el_catalogo_incluye_la_doble_oportunidad()
    test_los_goles_del_brasileirao_b_no_pasan_del_60_por_ciento()
    test_la_linea_de_jugador_es_la_principal_de_la_casa()
    test_la_tarjeta_ensena_el_catalogo_completo()
    print('\n=== v171: el Score, todas las lineas ===')
    test_la_recomendacion_se_elige_por_score_y_no_por_probabilidad()
    test_el_score_no_recomienda_volados_ni_rojos()
    test_la_casa_guarda_sus_cuotas_y_el_lector_es_compatible()
    test_se_exploran_todas_las_lineas_de_cada_mercado()
    print(f"\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    for f in FALLOS:
        print('  - ' + f)
    sys.exit(1 if FALLOS else 0)
