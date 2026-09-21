#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v93 — Recalibra TODA la cadena con los partidos que ya se jugaron.

El agujero que tapa
-------------------
El workflow diario reentrena los modelos de fútbol y refresca `team_stats`,
así que las PREDICCIONES mejoran cada día. Pero las CALIBRACIONES que
corrigen esas predicciones estaban congeladas en el día en que alguien las
generó a mano. Auditado el 2026-08-03:

    artefacto                     edad   ¿lo regenera el workflow?
    modelos de fútbol               1 d   SÍ
    team_stats_*.json               1 d   SÍ
    calibracion_mercado.json        1 d   SÍ
    ─────────────────────────────────────────────────────────────
    pick_ledger_total.csv           5 d   ❌ NUNCA
    calibracion_confianza.json      3 d   ❌ NUNCA
    umbrales_capa1.json             6 d   ❌ NUNCA
    edge_map.json                  11 d   ❌ NUNCA
    precision_ligas.json            1 d   ❌ NUNCA
    deportes_capa1.json               —   ❌ NUNCA

Y hay una inconsistencia peor que la antigüedad: **la corrección que se aplica
describe el comportamiento de un modelo que ya no existe**. `calibracion_
confianza` mide cuánto acierta de verdad cada banda de probabilidad; si el
modelo se reentrena a diario y esa medición no, se está corrigiendo con la
huella de un modelo de hace días. Lo mismo con la banda de EV rentable
(`edge_map`) y con los umbrales de Capa 1.

El orden importa
----------------
Todo cuelga del ledger, así que la cadena es estrictamente secuencial:

    1. build_pick_ledger     ← re-predice el fútbol con los modelos de HOY
       build_ledger_deportes ← y el tenis y el MLB
       build_ledger_total    ← junta los dos (esto es lo único que corría)
    2. calibracion_confianza  ← acierto real por banda y mercado
    3. precision_ligas        ← techo de acierto de cada competición
    4. edge_engine            ← banda de EV rentable (maximin + bootstrap)
    5. validacion_deportes    ← qué deportes entran en la Capa 1
    6. recalibrate_from_history ← el peso w del encogimiento al mercado

Cada paso es independiente en su fallo: si uno revienta, se anota y los demás
siguen. Un artefacto viejo es peor que uno nuevo, pero MUCHO mejor que ninguno
— y el que no se regenere conserva el anterior, nunca se queda a medias.

Cuánto cuesta
-------------
El paso 1 re-predice decenas de miles de partidos y es el caro (~40 min). Por
eso esto NO va en el workflow diario sino en uno semanal: las calibraciones se
mueven despacio y reconstruirlas a diario sería gastar una hora de CI para
cambiar el cuarto decimal.

Uso:
    python recalibrar_todo.py              # cadena completa
    python recalibrar_todo.py --sin-ledger # sólo lo que cuelga del ledger ya hecho
"""
import argparse
import json
import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

SALIDA = 'recalibracion_estado.json'


def _paso(nombre: str, fn) -> Dict:
    """Ejecuta un paso y devuelve su resultado sin dejar caer la cadena."""
    t0 = time.time()
    try:
        detalle = fn()
        dt = time.time() - t0
        logger.info(f'✅ {nombre} ({dt:.0f}s)')
        return {'paso': nombre, 'ok': True, 'segundos': round(dt, 1),
                'detalle': detalle}
    except Exception as e:
        dt = time.time() - t0
        logger.warning(f'❌ {nombre}: {type(e).__name__}: {e}')
        return {'paso': nombre, 'ok': False, 'segundos': round(dt, 1),
                'error': f'{type(e).__name__}: {e}'}


# Un ledger que sale con menos de esta fracción de las filas que tenía es
# una descarga a medias, no una temporada que encogió. Misma guarda y mismo
# motivo que `league_engine._guardar_historico`.
ENCOGIMIENTO_MAXIMO = 0.30


def _filas(ruta: str):
    import os
    if not os.path.exists(ruta):
        return None
    try:
        import pandas as pd
        return len(pd.read_csv(ruta, usecols=[0], low_memory=False))
    except Exception:
        return None


def _rehacer(etiqueta: str, modulo, temporal: str) -> str:
    """
    Reconstruye un ledger EN UN FICHERO APARTE y sólo sustituye al bueno si
    sale sano.

    Sin esto, un `construir()` que se queda a medias —una liga cuyo histórico
    no se descargó, una fuente caída— escribe igualmente su resultado corto
    encima del ledger anterior, y toda la cadena que cuelga de él se recalibra
    con menos partidos sin que nada lo diga. Es exactamente lo que ya pasó con
    `historico_champions.csv`: 53.264 filas encima de 895, sin un aviso.
    """
    import os

    csv_bueno, meta_buena = modulo.SALIDA_CSV, modulo.SALIDA_META
    antes = _filas(csv_bueno)
    modulo.SALIDA_CSV = temporal
    modulo.SALIDA_META = temporal.replace('.csv', '.json')
    try:
        df = modulo.construir()
    finally:
        modulo.SALIDA_CSV, modulo.SALIDA_META = csv_bueno, meta_buena

    ahora = len(df)
    if antes and ahora < antes * (1.0 - ENCOGIMIENTO_MAXIMO):
        for f in (temporal, temporal.replace('.csv', '.json')):
            if os.path.exists(f):
                os.remove(f)
        raise RuntimeError(
            '%s salio con %d filas y tenia %d (-%.0f%%): se conserva el '
            'anterior' % (etiqueta, ahora, antes,
                          100.0 * (1 - ahora / float(antes))))

    os.replace(temporal, csv_bueno)
    tmp_meta = temporal.replace('.csv', '.json')
    if os.path.exists(tmp_meta):
        os.replace(tmp_meta, meta_buena)
    return '%s: %d filas (%+d)' % (etiqueta, ahora,
                                   ahora - (antes or 0))


def _ledger() -> str:
    """
    v189 — ESTE PASO DECIA RE-PREDECIR Y SOLO CONCATENABA.

    El encabezado de este modulo describe el paso 1 como «re-predice el
    historico con los modelos de HOY» y calcula que cuesta unos 40 minutos;
    por ese coste la recalibracion se dejo semanal en vez de diaria.

    **Ese coste no se pagaba nunca.** `build_ledger_total.construir()` no
    re-predice nada: junta `pick_ledger.csv` y `pick_ledger_deportes.csv`, que
    los escriben otros dos modulos, y a los que no llamaba nadie. La pasada
    semanal terminaba en 7 min y volvia a producir, byte a byte, el mismo
    fichero.

    Consecuencia, medida el 2026-09-09: `pick_ledger.csv` seguia generado el
    2026-07-28 —lo dice su propio `_v75_pick_ledger.json`—, o sea que durante
    seis semanas la cadena entera se recalibro sobre partidos de julio. Y como
    salia identico, no habia diff, no habia commit, y el workflow terminaba en
    verde cada lunes. Los cuatro ficheros que no se actualizaban no eran cuatro
    fallos: eran este.

    Ahora el paso reconstruye los dos ledgers de origen y DESPUES concatena.
    Cada uno por separado: si el de futbol falla, el de deportes se rehace
    igual y el total se arma con el futbol anterior, que es viejo pero existe.
    """
    import build_ledger_deportes
    import build_ledger_total
    import build_pick_ledger

    notas, fallos = [], []
    for etiqueta, modulo, temporal in (
            ('futbol', build_pick_ledger, '_pick_ledger.nuevo.csv'),
            ('deportes', build_ledger_deportes,
             '_pick_ledger_deportes.nuevo.csv')):
        try:
            notas.append(_rehacer(etiqueta, modulo, temporal))
        except Exception as e:
            fallos.append('%s: %s' % (etiqueta, e))
            logger.warning('[ledger/%s] no se rehizo: %s', etiqueta, e)

    # v256 - EL LEDGER DE TOTALES TAMBIEN, QUE SE REHACIA A MANO.
    #
    # `pick_ledger_totales.csv` alimenta la calibracion por banda de cuota,
    # que corrige TODAS las probabilidades publicadas. No estaba en esta
    # cadena, asi que envejecia solo: se encontro con 42 dias mientras el
    # workflow semanal corria en verde cada lunes. Un fichero que decide y que
    # nadie regenera es una bomba de relojeria silenciosa.
    try:
        import build_ledger_totales
        _dt = build_ledger_totales.construir()
        notas.append('totales: %d filas' % len(_dt))
    except Exception as e:
        fallos.append('totales: %s' % e)
        logger.warning('[ledger/totales] no se rehizo: %s', e)

    df = build_ledger_total.construir()
    notas.append('total: %d filas' % len(df))
    if fallos:
        notas.append('SIN REHACER -> ' + '; '.join(fallos))
    return ' | '.join(notas)


def _confianza() -> str:
    import calibracion_confianza as cc
    r = cc.calcular()
    return (f"{r['n_total']} predicciones medidas · umbral "
            f"{r['umbral_recomendado']:.2f}")


def _precision_ligas() -> str:
    import precision_ligas
    r = precision_ligas.generar()
    return (f"{len(r.get('ligas') or {})} ligas · correlación "
            f"{r.get('correlacion_mitades')} · "
            f"{'publicado' if r.get('estable') else 'NO publicado (inestable)'}")


def _edge() -> str:
    import edge_engine
    edge_engine.calibrar(guardar=True)
    import importlib
    importlib.reload(edge_engine)
    lo, hi = edge_engine.banda_rentable()
    return (f'banda EV [{lo:.3f}, {hi:.3f}] · piso de probabilidad '
            f'{edge_engine.piso_prob():.2f}')


def _deportes() -> str:
    import validacion_deportes as vd
    r = vd.calcular()
    dentro = [d for d, v in (r.get('deportes') or {}).items()
              if v.get('edge_validado')]
    return f'con edge validado: {dentro or "ninguno"}'


def _peso_mercado() -> str:
    import recalibrate_from_history as rh
    d = rh.analizar(rh.LEDGER)
    v = d.get('validacion') or {}
    return (f"w global {d.get('w_global')} · {d.get('ligas_adoptadas')} ligas "
            f"adoptadas · log-loss {v.get('delta_logloss')}")


def _autopsia() -> str:
    """v101 — dónde falla el sistema de forma sistemática."""
    import autopsia
    r = autopsia.autopsia_produccion()
    g = r.get('global') or {}
    if not g:
        return r.get('aviso', 'sin picks liquidados')
    return (f"{g['n']} picks liquidados · acierto {g['acierto_real']:.1%} vs "
            f"prometido {g['prob_prometida']:.1%} · brecha {g['brecha']:+.1%} · "
            f"{r.get('lecciones', 0)} segmento(s) con brecha significativa")


def _aprender() -> str:
    """v101 — reaprende el mapa de calibración adaptativa."""
    import aprendizaje_continuo as ac
    s = ac.reaprender()
    return (f"{len(s['mapa'])} nodos · fuentes {s['fuentes']} · "
            f"n global {s['n_total']}")


def _bandas() -> str:
    """v256 - La calibracion por banda de cuota, regenerada aqui y no a mano.

    `calibracion_bandas.json` es lo que corrige la probabilidad de CADA pick
    que se publica (`veredicto_pick.correccion`), y se entrenaba ejecutando
    `calibrador_bandas.py` a mano. Va DESPUES del ledger porque come de el:
    regenerarla antes seria calibrar con la foto de la semana pasada.
    """
    import calibrador_bandas as cb
    doc = cb.entrenar()
    return 'n=%s · bandas=%d' % (doc.get('n_total'),
                                 len(doc.get('bandas') or {}))


def _liquidar() -> str:
    """v256 - Y los pronosticos ya jugados se resuelven.

    La v249 lo metio en el workflow nocturno, pero ahi solo corre si ese
    workflow entero llega hasta el final. Aqui va tambien, porque es de donde
    sale el historico de corners, tarjetas y remates — los tres mercados que
    no tenian NI UNA fila resuelta.
    """
    import pronosticos_guardados as pg
    r = pg.resolver_pendientes()
    return ('%d partidos, %d picks liquidados'
            % (r.get('resueltos', 0), r.get('picks', 0)))


def _goles_por_linea():
    """Reajusta la curva de goles y decide, midiendo, si debe estar encendida.

    POR QUE ESTE PASO EXISTE
    `calibrador_goles` es de la v225 y corrige la escalera de goles en origen,
    dentro de `alpha_finder`. Lo que no tenia era quien lo reentrenara:
    `calibracion_goles.json` se genero a mano y ninguna cadena lo volvia a
    tocar. Misma bomba silenciosa que la v256 encontro con el ledger de
    totales, y mismo sintoma: todo verde mientras el artefacto envejece.

    POR QUE MIDE CONTRA NO-CURVA Y NO CONTRA LA CURVA ANTERIOR
    La v251 anadio despues el encogimiento de lambda, que ataca la MISMA
    sobredispersion antes y mejor. Medido en el pliegue de juicio (n=16.170)
    con la lambda de produccion, apagar la curva mejora la log-loss +0,00252
    con p5 +0,00164 y el 100 % de los remuestreos a favor, y deja el sesgo al
    Under en -0,5 pp en vez de -16,1. O sea que la pregunta util ya no es
    «esta curva es mejor que la anterior» sino «hace falta alguna curva».

    Asi que el paso compara las tres probabilidades sobre el pliegue
    reservado, escribe el veredicto en `activa_medida` y deja que el modulo lo
    lea. Si algun dia la curva vuelve a ganar, se enciende sola; si no, se
    queda apagada sin que nadie tenga que acordarse.
    """
    import json
    import numpy as np
    import calibrador_goles as cg

    doc = cg.entrenar(hasta_pliegue=cg.PLIEGUE_JUICIO)
    if not doc.get('lineas'):
        return 'sin datos suficientes para ajustar'

    t = cg._datos()
    ju = t[t.pliegue == cg.PLIEGUE_JUICIO]
    if not len(ju):
        return 'el pliegue de juicio esta vacio'
    lam = ju['lam'].to_numpy()
    crudas = {L: cg._p_over(lam, L) for L in cg.LINEAS}
    cal = {}
    for L in cg.LINEAS:
        c = (doc.get('lineas') or {}).get(cg.clave_linea(L))
        cal[L] = (np.clip(np.interp(crudas[L], c['x'], c['y']), 1e-6, 1 - 1e-6)
                  if c else crudas[L])
    ll_sin, br_sin = cg._metricas(ju, crudas)
    ll_con, br_con = cg._metricas(ju, cal)

    # remuestreo de la diferencia, pareado: positivo = la curva GANA
    difs = []
    for L in cg.LINEAS:
        col = 'over_%s_real' % str(L)
        if col not in ju.columns:
            continue
        m = ju[col].notna().to_numpy()
        y = ju.loc[ju[col].notna(), col].to_numpy(dtype=float)
        a = np.clip(crudas[L][m], 1e-6, 1 - 1e-6)
        b = np.clip(cal[L][m], 1e-6, 1 - 1e-6)
        difs.append((-(y * np.log(a) + (1 - y) * np.log(1 - a)))
                    - (-(y * np.log(b) + (1 - y) * np.log(1 - b))))
    g = np.concatenate(difs) if difs else np.array([0.0])
    rng = np.random.default_rng(31)
    xs = np.array([g[rng.integers(0, len(g), len(g))].mean()
                   for _ in range(1000)])
    p5 = float(np.percentile(xs, 5))

    # LOS DOS CRITERIOS, NO UNO.
    #
    # La log-loss sola dice que la curva gana (+0,00040, p5 +0,00014). Pero
    # este modulo existe para arreglar el sesgo al Under, y con la lambda ya
    # encogida ese sesgo esta practicamente en cero SIN curva (-0,5 pp) y la
    # curva lo empeora (+2,2 pp). Aceptarla por una ganancia de 0,0004 a
    # cambio de reintroducir lo que vino a quitar seria cumplir la letra del
    # criterio y romper su motivo. Es el mismo par de condiciones que exige
    # `calibrador_goles.veredicto`, aplicado aqui contra NO-curva.
    col = 'over_2.5_real'
    sesgo_sin = sesgo_con = 0.0
    if col in ju.columns and ju[col].notna().any():
        mm = ju[col].notna().to_numpy()
        real_u = 1.0 - float(ju.loc[ju[col].notna(), col].mean())
        sesgo_sin = float((crudas[2.5][mm] < 0.5).mean()) - real_u
        sesgo_con = float((cal[2.5][mm] < 0.5).mean()) - real_u
    gana = (p5 > 0) and (abs(sesgo_con) <= abs(sesgo_sin))

    final = cg.entrenar()
    final['juicio_contra_sin_curva'] = {
        'n': int(len(ju)),
        'log_loss_sin': round(ll_sin, 5), 'log_loss_con': round(ll_con, 5),
        'brier_sin': round(br_sin, 5), 'brier_con': round(br_con, 5),
        'mejora_de_la_curva': round(float(g.mean()), 5),
        'p5': round(p5, 5),
        'a_favor': round(float((xs > 0).mean()), 3),
        'sesgo_under_sin': round(sesgo_sin, 4),
        'sesgo_under_con': round(sesgo_con, 4),
    }
    final['activa_medida'] = bool(gana)
    with open(cg.ARTEFACTO, 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False)
    cg.cargar(recargar=True)
    return ('%s · log-loss sin %.5f / con %.5f · p5 %+.5f · sesgo Under '
            '%+.1f -> %+.1f pp'
            % ('ENCENDIDA' if gana else 'APAGADA', ll_sin, ll_con, p5,
               100 * sesgo_sin, 100 * sesgo_con))


def _ledger_handicap():
    """Rehace el ledger del handicap asiatico (v261).

    POR QUE ESTE PASO FALTABA, Y ES DEUDA PROPIA
    `pick_ledger_handicap.csv` estaba en el 8 de agosto —seis semanas— y nadie
    lo regeneraba. Lo LEEN `calibracion_confianza` y `mercado_estabilidad`, o
    sea que decide, y desde la v254 el handicap ademas se publica como
    apuesta: se encendio un mercado cuya validacion llevaba mes y medio
    congelada.

    Es exactamente el fallo que la v256 arreglo con el ledger de totales (42
    dias, workflow en verde cada lunes) y que la auditoria del propio repo
    marcaba en rojo como «handicap: grande_activo_sin_medicion».

    No re-predice nada: deriva de `pick_ledger_totales.csv` y
    `pick_ledger_total.csv`, asi que tiene que ir DETRAS del paso 1, que es
    quien los reconstruye.
    """
    import build_ledger_handicap as blh
    d = blh.construir()
    if d is None or not len(d):
        return 'sin partidos con lambda y 1X2 a la vez'
    # cordura: lo que se prometio contra lo que se cubrio, en la linea mas
    # usada. Un ledger que sale sesgado es peor que no tenerlo.
    import numpy as np
    partes = []
    for L in ('-0p50', '+0p00', '+0p50'):
        cp, cr = 'p_ah_%s' % L, 'ah_%s_real' % L
        if cp not in d.columns or cr not in d.columns:
            continue
        m = d[cp].notna() & d[cr].notna()
        if int(m.sum()) < 500:
            continue
        partes.append('%s dijo %.3f pasa %.3f'
                      % (L.replace('p', ','), float(d.loc[m, cp].mean()),
                         float(np.asarray(d.loc[m, cr], dtype=float).mean())))
    return '%d partidos · %s' % (len(d), ' · '.join(partes) or 'sin cordura')


def _selector():
    """Reentrena el selector de apuestas (v264).

    Es lo que hace que la aplicacion APRENDA de sus propios resultados: cada
    semana rehace el universo de 1,9 millones de apuestas con resultado y
    vuelve a ajustar el modelo que decide cual tomar y cual no.

    Va el ULTIMO porque come de todos los ledgers que los pasos anteriores
    acaban de reconstruir. Y tiene su propia puerta: si no le gana a la
    probabilidad del modelo en el remuestreo, no se publica y todo sigue como
    estaba.
    """
    import selector_apuestas as sel
    doc = sel.entrenar()
    if not doc:
        return 'sin universo suficiente'
    m = doc.get('medicion') or {}
    if not doc.get('activo'):
        return ('NO se publica: no bate a la probabilidad del modelo '
                '(p5 %+.5f)' % m.get('p5', 0))
    extra = ''
    if 'roi_selector' in m:
        extra = (' · ROI %+.2f %% (n=%s)'
                 % (100 * m['roi_selector'], format(m.get('n_roi', 0), ',d')))
    return ('%s apuestas · log-loss %.5f -> %.5f · p5 %+.5f%s'
            % (format(doc.get('n_entrenamiento', 0), ',d'),
               m.get('log_loss_modelo', 0), m.get('log_loss_selector', 0),
               m.get('p5', 0), extra))


def _radar():
    """Reentrena el radar de errores de cuota (v270-v271).

    Aprende en QUÉ partidos es probable que una casa se haya descolgado, y con
    eso el barrido decide a cuáles gastarles las peticiones. Come de dos
    sitios: el histórico de `pick_ledger.csv` —26.647 partidos desde 2021— y
    las capturas que cada barrido va dejando en `radar_capturas.csv`, que son
    las casas que el usuario juega de verdad y crecen solas.

    Tiene su propia puerta: si no ordena mejor que el azar (AUC < 0,55) no se
    publica y el barrido sigue cortando como antes.
    """
    import radar_capturas as cap
    import radar_errores as radar
    doc = radar.entrenar()
    if not doc:
        return 'sin universo suficiente'
    m = doc.get('medicion') or {}
    if not doc.get('activo'):
        return 'NO se publica: AUC %.4f por debajo del mínimo' % m.get('auc', 0)
    g = (m.get('ganancia') or {}).get('top_20') or {}
    c = cap.resumen()
    return ('%s partidos · AUC %.4f · barriendo el 20 %% mejor, %sx errores '
            '· capturas propias: %s filas en %s días'
            % (format(doc.get('n_total', 0), ',d'), m.get('auc', 0),
               g.get('veces', '?'), format(c.get('filas', 0), ',d'),
               c.get('dias', 0)))


def _memoria_equipos():
    """Reajusta en que se viene equivocando el modelo con cada equipo (v265).

    Va ANTES del selector, que la usa como variable. Medido: correlacion
    +0,0493 entre el error pasado de un equipo y el de hoy, con gradiente
    monotono; validado fuera de muestra, MSE -0,247 % con p5 +0,00244 y el
    100 % de los remuestreos a favor.

    Es pequeno y conviene que este escrito: un cuarto de punto. No corrige la
    lambda —sobre ella ya hay dos correcciones apiladas— sino que se la da al
    selector para que la pese junto con lo demas.
    """
    import memoria_equipos as me
    doc = me.construir()
    if not doc:
        return 'sin ledger de totales'
    eq = doc.get('equipos') or {}
    if not eq:
        return 'ningun equipo con partidos suficientes'
    import numpy as np
    ses = [v['sesgo'] for v in eq.values()]
    return ('%s equipos · sesgo medio %+.4f · desv %.4f · hasta %s'
            % (format(len(eq), ',d'), float(np.mean(ses)),
               float(np.std(ses)), doc.get('hasta')))


PASOS = [
    ('1. ledger (re-predice el histórico con los modelos de hoy)', _ledger),
    ('2. calibración de confianza (acierto real por banda)', _confianza),
    ('3. techo de acierto por liga', _precision_ligas),
    ('4. banda de EV rentable', _edge),
    ('5. qué deportes tienen edge validado', _deportes),
    ('6. peso del encogimiento al mercado', _peso_mercado),
    # --- v101: el lazo que aprende de sus propios resultados ---------------
    # Va AL FINAL a propósito. Los pasos 1-6 miden el modelo contra el
    # histórico; éstos dos lo miden contra lo que de verdad se publicó y ya se
    # liquidó, que es la única fuente que incluye los filtros, la Capa 2 y el
    # line shopping. La autopsia diagnostica y el aprendizaje corrige, en ese
    # orden: sin el diagnóstico, la corrección no sabría dónde hace falta.
    ('7. autopsia de los picks publicados', _autopsia),
    ('8. calibración adaptativa (aprende de lo liquidado)', _aprender),
    ('9. calibración por banda de cuota (isotónica walk-forward)', _bandas),
    ('10. liquidar los pronósticos ya jugados', _liquidar),
    # v258 — LA CURVA POR LÍNEA DE GOLES.
    #
    # Va DESPUÉS del paso 1, que es quien rehace `pick_ledger_totales.csv`, y
    # por la misma razón que la v256 puso ahí la calibración por banda: una
    # curva ajustada sobre el ledger de la semana pasada corrige el sesgo de
    # la semana pasada. Y tiene su propia puerta dentro —si separar por línea
    # no aguanta el remuestreo, `entrenar` publica el fichero vacío y todo
    # sigue como estaba—, así que este paso no puede empeorar nada por sí
    # solo.
    ('11. curva por línea del mercado de goles', _goles_por_linea),
    ('12. ledger del hándicap asiático', _ledger_handicap),
    ('13. memoria de errores por equipo', _memoria_equipos),
    ('14. selector de apuestas (aprende cuál tomar)', _selector),
    # El radar va DESPUÉS del selector porque no depende de él: son dos
    # preguntas distintas. El selector decide si una apuesta concreta se
    # toma; el radar decide dónde ir a buscarlas. Si uno falla, el otro
    # sigue.
    ('15. radar de errores de cuota (dónde mirar)', _radar),
]


def recalibrar(sin_ledger: bool = False) -> Dict:
    """Ejecuta la cadena completa. Nunca lanza: informa de lo que falló."""
    import pandas as pd
    pasos = PASOS[1:] if sin_ledger else PASOS
    resultados: List[Dict] = [_paso(n, f) for n, f in pasos]
    doc = {
        'generado': pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'pasos': resultados,
        'ok': sum(1 for r in resultados if r['ok']),
        'fallos': [r['paso'] for r in resultados if not r['ok']],
        'segundos_total': round(sum(r['segundos'] for r in resultados), 1),
    }
    try:
        from io_atomico import escribir_json
        escribir_json(SALIDA, doc, indent=1)
    except Exception:
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--sin-ledger', action='store_true',
                    help='salta la reconstrucción del ledger (usa el que hay)')
    a = ap.parse_args()
    d = recalibrar(a.sin_ledger)
    print(f"\n{d['ok']}/{len(d['pasos'])} pasos OK en {d['segundos_total']:.0f}s")
    for p in d['pasos']:
        print(f"  {'✅' if p['ok'] else '❌'} {p['paso']}")
        print(f"      {p.get('detalle') or p.get('error')}")
    sys.exit(0 if not d['fallos'] else 1)
