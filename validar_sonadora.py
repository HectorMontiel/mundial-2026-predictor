#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validación histórica de la Soñadora: ¿qué rinde de verdad un parlay de patas
seguras?

DE DÓNDE SALE LA PREGUNTA
-------------------------
El usuario ganó un parlay de 13 patas con cuotas de 1,35 a 1,79 —ocho de ellas
de total de goles— que pagó 490x. La pregunta no es si eso pasó (pasó), sino si
se puede sistematizar. Esto lo mide.

LA CUENTA QUE MANDA, Y POR QUÉ LA SIMULACIÓN SÓLO LA CONFIRMA
-------------------------------------------------------------
Un parlay de patas independientes MULTIPLICA el rendimiento de cada pata: si
cada una rinde (1 + e), el parlay de N rinde (1 + e)^N − 1. O sea que combinar
no crea ventaja: la amplifica si la hay y la amplifica también si es negativa.

    e = −5 %  ->   4 patas −18,5 %   ·   13 patas −48,7 %
    e =  0 %  ->   cualquier N, 0 %
    e = +2 %  ->   4 patas  +8,2 %   ·   13 patas +29,4 %

Así que el número que decide una sección entera es **el ROI de UNA pata**, y
todo lo demás es consecuencia. La simulación se hace igual porque aporta dos
cosas que la cuenta no: la tasa de acierto real de cada configuración (que es
lo que el usuario ve) y el efecto de que las patas de un mismo día NO son
independientes.

QUÉ SE PUEDE MEDIR Y QUÉ NO
---------------------------
Sólo entran mercados con **cuota de cierre real guardada** y resultado real:

    1X2 (gana local / gana visitante) ....  `pick_ledger.csv`
    Más / Menos de 2,5 goles .............  `pick_ledger_totales.csv`

**Más de 1,5 — que era la columna vertebral del parlay ganador (4 de 13
patas)— NO tiene cuota en el histórico.** Su probabilidad sí está
(`p_over_1.5`) y su resultado también, así que se mide su ACIERTO, pero su ROI
no se puede calcular sin inventar un precio, y eso no se hace. Lo mismo con
Más/Menos 3,5, Ambos Marcan, Doble Oportunidad y córners: el modelo los
publica, la casa los cotiza en vivo, pero el histórico no guardó su precio.

Tampoco se modela el **Pago Anticipado** de Playdoit (cobrar si tu equipo se
pone por delante), que sube el valor real de las patas de «Gana X» y no está en
ningún dato. Lo que se mide es el caso sin PA, que es el peor caso.

Uso:
    python validar_sonadora.py                 # ventana de 6 meses
    python validar_sonadora.py --meses 24      # otra ventana
    python validar_sonadora.py --informe       # no escribe el JSON
"""

import argparse
import datetime as _dt
import json
import logging
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = 'sonadora_historico.json'
LEDGER_1X2 = 'pick_ledger.csv'
LEDGER_TOT = 'pick_ledger_totales.csv'
LEDGER_DEP = 'pick_ledger_deportes.csv'     # MLB y tenis, con su cuota

# Las combinaciones de deportes que la pantalla puede pedir. Se miden por
# separado porque no rinden igual: el modelo de tenis no bate al mercado
# (medido sobre 108.657 partidos, §8 del traspaso) y el de MLB tampoco.
COMBOS_DEPORTE = (('Fútbol',), ('MLB',), ('Tenis',),
                  ('Fútbol', 'MLB'), ('Fútbol', 'MLB', 'Tenis'))

# Las configuraciones del encargo.
N_PATAS = (4, 6, 8, 10, 13)
BANDAS = ((1.10, 1.30), (1.30, 1.50), (1.50, 1.80), (1.10, 1.80))
N_SIMULACIONES = 10000
PROB_MINIMA = 0.55
SEMILLA = 20260915

# El listón de despliegue que fija el encargo.
ROI_MINIMO = -0.05
P5_MINIMO = -0.15

# Mínimo de partidos por competición para publicar su error de calibración.
N_MINIMO_ECE = 100

# MESES SOBRE LOS QUE SE MIDE EL ERROR DE CALIBRACIÓN POR COMPETICIÓN.
#
# Va aparte de la ventana de simulación a propósito. El ECE de una liga es una
# propiedad del modelo en esa liga, no del semestre: medido a 6 meses cada
# competición aporta 120-280 filas y el número baila tanto que sólo 3 de 31
# ligas quedaban por debajo de 0,05 — no porque el modelo sea malo en las
# otras 28, sino porque con esa muestra el ECE no distingue.
MESES_ECE = 24

# DÍAS DISTINTOS mínimos para que una configuración se pueda interpretar.
#
# No es un adorno: la unidad independiente de esta simulación es el DÍA, no el
# parlay. Diez mil parlays armados sobre cuatro jornadas son cuatro jornadas
# repetidas dos mil quinientas veces. Medido en la primera pasada: la banda
# 1,10-1,30 con 8 patas tiene **4 días** que reúnan ocho partidos, y salía con
# «+49,9 % de ROI y hit del 26 % contra un 7 % teórico» — o sea cuatro tardes
# de fútbol con suerte, presentadas como una estrategia. Con 10 patas queda
# **un solo día**, y con 13 ninguno.
DIAS_MINIMOS = 30


# ---------------------------------------------------------------------------
# El conjunto de patas
# ---------------------------------------------------------------------------
def _patas_1x2(d: pd.DataFrame) -> pd.DataFrame:
    """Una fila por (partido, lado) con probabilidad del modelo y cuota real.

    `resultado` es el ÍNDICE de [p_home, p_draw, p_away] —0 local, 1 empate,
    2 visitante— y no el 1X2 clásico. Verificado contra los goles: las filas
    con `resultado=0` promedian 2,37 goles locales y 0,56 visitantes. Leerlo
    como 1=local daba «el favorito a 1,50 acierta el 27 %», que es imposible y
    es la firma de desalineación que `build_ledger_deportes.verificar_
    alineacion` existe para cazar.
    """
    fuera = []
    for lado, pcol, ccol, res in (('Gana local', 'p_home', 'cuota_home', 0),
                                  ('Gana visitante', 'p_away', 'cuota_away', 2)):
        g = d[d[ccol].notna() & d[pcol].notna() & d['resultado'].notna()]
        fuera.append(pd.DataFrame({
            'fecha': g['fecha'].astype(str), 'liga': g['liga'].astype(str),
            'match_id': g['match_id'].astype(str),
            'mercado': '1X2', 'seleccion': lado,
            'prob': g[pcol].astype(float), 'cuota': g[ccol].astype(float),
            'gana': (g['resultado'].astype(int) == res).astype(int)}))
    return pd.concat(fuera, ignore_index=True)


def _patas_goles(t: pd.DataFrame) -> pd.DataFrame:
    fuera = []
    for sel, pcol, ccol, invertir in (
            ('Más de 2.5', 'p_over_2.5', 'cuota_over25', False),
            ('Menos de 2.5', 'p_over_2.5', 'cuota_under25', True)):
        g = t[t[ccol].notna() & t[pcol].notna() & t['over_2.5_real'].notna()]
        real = g['over_2.5_real'].astype(float).round().astype(int)
        fuera.append(pd.DataFrame({
            'fecha': g['fecha'].astype(str), 'liga': g['liga'].astype(str),
            'match_id': g['match_id'].astype(str),
            'mercado': 'Goles 2.5', 'seleccion': sel,
            'prob': (1.0 - g[pcol].astype(float)) if invertir
            else g[pcol].astype(float),
            'cuota': g[ccol].astype(float),
            'gana': (1 - real) if invertir else real}))
    return pd.concat(fuera, ignore_index=True)


def _patas_deportes(d: pd.DataFrame) -> pd.DataFrame:
    """Ganador de MLB y tenis, con su cuota de cierre real.

    Mismo criterio que el 1X2 del futbol: `resultado` es el INDICE de
    [p_home, p_draw, p_away], asi que 0 es local y 2 visitante.
    """
    fuera = []
    for lado, pcol, ccol, res in (('Gana local', 'p_home', 'cuota_home', 0),
                                  ('Gana visitante', 'p_away', 'cuota_away', 2)):
        g = d[d[ccol].notna() & d[pcol].notna() & d['resultado'].notna()]
        fuera.append(pd.DataFrame({
            'fecha': g['fecha'].astype(str), 'liga': g['liga'].astype(str),
            'match_id': g['match_id'].astype(str),
            'deporte': g['deporte'].astype(str),
            'mercado': 'Ganador', 'seleccion': lado,
            'prob': g[pcol].astype(float), 'cuota': g[ccol].astype(float),
            'gana': (g['resultado'].astype(int) == res).astype(int)}))
    return pd.concat(fuera, ignore_index=True)


def conjunto_patas(desde: Optional[str] = None) -> pd.DataFrame:
    d = pd.read_csv(LEDGER_1X2)
    t = pd.read_csv(LEDGER_TOT)
    trozos = [_patas_1x2(d), _patas_goles(t)]
    for tr in trozos:
        tr['deporte'] = 'Fútbol'
    try:
        dep = pd.read_csv(LEDGER_DEP)
        trozos.append(_patas_deportes(dep))
    except Exception as e:
        logger.warning('[sonadora] sin ledger multideporte: %s', e)
    P = pd.concat(trozos, ignore_index=True)
    if desde:
        P = P[P['fecha'] >= desde]
    return P.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def ece(p: np.ndarray, y: np.ndarray, n_cajas: int = 10) -> Optional[float]:
    """Error de calibración esperado, por cajas de anchura fija."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return None
    bordes = np.linspace(0.0, 1.0, n_cajas + 1)
    total = 0.0
    for i in range(n_cajas):
        lo, hi = bordes[i], bordes[i + 1]
        dentro = (p > lo) & (p <= hi) if i else (p >= lo) & (p <= hi)
        if not dentro.any():
            continue
        total += dentro.mean() * abs(p[dentro].mean() - y[dentro].mean())
    return float(total)


def _p5(pnl: np.ndarray, n: int = 2000) -> Optional[float]:
    """Percentil 5 del rendimiento medio, remuestreando observaciones."""
    if len(pnl) < 30:
        return None
    rng = np.random.default_rng(SEMILLA)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    return float(np.percentile(pnl[idx].mean(axis=1), 5))


def _p5_por_dia(pnl: np.ndarray, dia: np.ndarray,
                n: int = 2000) -> Optional[float]:
    """
    Percentil 5 remuestreando DÍAS, no parlays.

    POR QUE ESTO Y NO EL BOOTSTRAP DE SIEMPRE, y es la correccion que salva
    esta validacion entera. Los 10.000 parlays de una configuracion se arman
    sobre unas decenas de jornadas: NO son 10.000 observaciones independientes,
    son unas decenas repetidas. Remuestrear parlays trata cada repeticion como
    informacion nueva y estrecha el intervalo hasta mentir.

    Medido en la primera pasada, con 24 meses y la banda 1,30-1,50: los parlays
    de 13 patas salian con **ROI +60,4 % y p5 +41,6 %** sobre 75 jornadas,
    cuando la proyeccion desde la pata suelta —que si tiene observaciones
    independientes— daba −37,4 %. La diferencia entera era esto: unas pocas
    jornadas en las que gano todo, con premios de x90, muestreadas miles de
    veces.

    Remuestreando jornadas, cada jornada entra o no entra en bloque, que es
    como se comporta de verdad.
    """
    if len(pnl) < 30:
        return None
    dias = np.unique(dia)
    if len(dias) < 5:
        return None
    por_dia = [pnl[dia == d] for d in dias]
    rng = np.random.default_rng(SEMILLA)
    medias = np.empty(n, float)
    for k in range(n):
        elegidos = rng.integers(0, len(por_dia), size=len(por_dia))
        medias[k] = float(np.mean(np.concatenate([por_dia[i]
                                                  for i in elegidos])))
    return float(np.percentile(medias, 5))


def roi_pata(sub: pd.DataFrame) -> Dict:
    """Lo que rinde UNA pata. Es el número del que cuelga todo lo demás."""
    if not len(sub):
        return {'n': 0}
    pnl = np.where(sub['gana'].values == 1, sub['cuota'].values - 1.0, -1.0)
    return {'n': int(len(sub)),
            'acierto': round(float(sub['gana'].mean()), 4),
            'prob_media': round(float(sub['prob'].mean()), 4),
            'cuota_media': round(float(sub['cuota'].mean()), 4),
            'roi': round(float(pnl.mean()), 4),
            'p5': (round(_p5(pnl), 4) if _p5(pnl) is not None else None),
            'ece': (round(ece(sub['prob'].values, sub['gana'].values), 4)
                    if len(sub) >= 30 else None)}


def ece_por_liga(P: pd.DataFrame) -> Dict:
    """
    Error de calibración de cada competición en los mercados de goles.

    `confianza_mercado.py` NO sirve aquí: sólo mide córners, tarjetas y
    remates. Los mercados de los que vive esta sección —1X2 y goles— no están
    en su informe, así que su error se calcula aquí, del mismo ledger fuera de
    muestra con el que se mide todo lo demás.
    """
    fuera: Dict = {}
    for (liga, mercado), g in P.groupby(['liga', 'mercado']):
        if len(g) < N_MINIMO_ECE:
            continue
        fuera.setdefault(str(liga), {})[str(mercado)] = {
            'n': int(len(g)),
            'ece': round(ece(g['prob'].values, g['gana'].values), 4),
            'acierto': round(float(g['gana'].mean()), 4),
            'prob_media': round(float(g['prob'].mean()), 4)}
    return fuera


# ---------------------------------------------------------------------------
# Simulación
# ---------------------------------------------------------------------------
def _por_dia(F: pd.DataFrame, n_patas: int) -> Dict:
    """Cada dia, en arrays de numpy: por partido, sus patas.

    Se precalcula porque el bucle de simulacion se ejecuta 10.000 veces por
    configuracion y 20 configuraciones: filtrar el DataFrame dentro del bucle
    costaba minutos por configuracion. Es el mismo patron que la bitacora §4
    documenta tres veces — la diferencia entre medir y no medir.
    """
    fuera = {}
    for dia, g in F.groupby('fecha'):
        codigos, _ = pd.factorize(g['match_id'].values)
        n_partidos = int(codigos.max()) + 1 if len(codigos) else 0
        if n_partidos < n_patas:
            continue
        cuota = g['cuota'].to_numpy(float)
        gana = g['gana'].to_numpy(int)
        prob = g['prob'].to_numpy(float)
        # indices de las patas de cada partido
        patas_de = [np.where(codigos == i)[0] for i in range(n_partidos)]
        fuera[dia] = {'n_partidos': n_partidos, 'patas_de': patas_de,
                      'cuota': cuota, 'gana': gana, 'prob': prob}
    return fuera


def simular(P: pd.DataFrame, n_patas: int, lo: float, hi: float,
            n_sim: int = N_SIMULACIONES, semilla: int = SEMILLA) -> Dict:
    """
    `n_sim` parlays de `n_patas` patas, armados como se arman de verdad.

    DOS REGLAS QUE CAMBIAN EL RESULTADO Y NO SON COSMETICAS:

    1. **Las patas de un parlay salen del MISMO DIA.** Nadie combina el partido
       del martes con el del sabado; y mas importante, los partidos de una
       misma jornada comparten contexto, asi que muestrear del historico entero
       fabricaria una independencia que no existe y haria salir la tasa de
       acierto mejor de lo que es.

    2. **Una pata por PARTIDO.** Dos patas del mismo encuentro —«gana el local»
       y «mas de 2,5»— estan correlacionadas de forma brutal, y la casa ni
       siquiera las deja combinar sin tratarlas aparte.

    LO QUE ESTE p5 NO ES. Las 10.000 configuraciones comparten patas: salen de
    un conjunto de unos pocos miles, asi que NO son 10.000 pruebas
    independientes y su percentil 5 subestima la incertidumbre real. El
    intervalo honesto es el de la PATA SUELTA, que si tiene observaciones
    independientes, elevado a N. Los dos se publican.
    """
    F = P[(P['cuota'] >= lo) & (P['cuota'] <= hi)
          & (P['prob'] >= PROB_MINIMA)]
    base = {'n_patas': int(n_patas), 'rango_cuota': [lo, hi],
            'patas_disponibles': int(len(F))}
    if not len(F):
        return {**base, 'intentos': 0,
                'motivo': 'ninguna pata pasa el filtro'}
    dias = _por_dia(F, n_patas)
    if not dias:
        return {**base, 'intentos': 0,
                'motivo': f'ningun dia tiene {n_patas} partidos distintos '
                          f'que pasen el filtro'}

    rng = np.random.default_rng(semilla + n_patas * 13 + int(lo * 100))
    claves = list(dias)
    pnl = np.empty(n_sim, float)
    mult = np.empty(n_sim, float)
    p_teorica = np.empty(n_sim, float)
    gana_todo = np.zeros(n_sim, bool)
    dia_de = np.empty(n_sim, int)      # de que jornada salio cada parlay
    for k in range(n_sim):
        _i_dia = int(rng.integers(0, len(claves)))
        dia_de[k] = _i_dia
        d = dias[claves[_i_dia]]
        elegidos = rng.choice(d['n_partidos'], size=n_patas, replace=False)
        idx = np.array([p[int(rng.integers(0, len(p)))]
                        for p in (d['patas_de'][i] for i in elegidos)])
        c = float(np.prod(d['cuota'][idx]))
        ok = bool(np.all(d['gana'][idx] == 1))
        mult[k] = c
        p_teorica[k] = float(np.prod(d['prob'][idx]))
        gana_todo[k] = ok
        pnl[k] = (c - 1.0) if ok else -1.0

    ganadas = int(gana_todo.sum())
    p5 = _p5(pnl)
    p5_dia = _p5_por_dia(pnl, dia_de)
    # cuantas jornadas aportan TODAS las ganadoras: si son cuatro, el ROI es
    # el de cuatro tardes de futbol y no el de una estrategia
    _dias_ganadores = int(len(np.unique(dia_de[gana_todo]))) if ganadas else 0
    return {
        **base,
        'intentos': int(n_sim), 'ganadas': ganadas,
        'hit_rate': round(ganadas / n_sim, 5),
        'hit_rate_teorico': round(float(p_teorica.mean()), 5),
        'multiplicador_medio': round(float(mult.mean()), 2),
        'multiplicador_mediana': round(float(np.median(mult)), 2),
        'multiplicador_de_las_ganadoras': (
            round(float(mult[gana_todo].mean()), 2) if ganadas else None),
        'roi_simulado': round(float(pnl.mean()), 4),
        'p5': (round(p5, 4) if p5 is not None else None),
        'p5_por_dia': (round(p5_dia, 4) if p5_dia is not None else None),
        'dias_con_suficientes_partidos': int(len(dias)),
        'dias_que_aportan_ganadoras': _dias_ganadores,
    }


# ---------------------------------------------------------------------------
# El informe entero
# ---------------------------------------------------------------------------
def validar(meses: int = 6, n_sim: int = N_SIMULACIONES) -> Dict:
    hoy = _dt.date.today()
    desde = (hoy - _dt.timedelta(days=int(meses * 30.44))).isoformat()
    P = conjunto_patas(desde)
    logger.info('[sonadora] %d patas entre %s y %s', len(P), desde, hoy)
    if not len(P):
        return {'medido': False, 'veredicto': 'sin_datos',
                'motivo': 'no hay patas con cuota y resultado en esa ventana'}

    F = P[(P['cuota'] >= 1.10) & (P['cuota'] <= 1.80)
          & (P['prob'] >= PROB_MINIMA)]
    doc: Dict = {
        'fecha_validacion': hoy.isoformat(),
        'periodo': f'{desde} a {hoy.isoformat()}',
        'meses': meses,
        'n_patas_con_cuota': int(len(P)),
        'n_partidos': int(P['match_id'].nunique()),
        'n_patas_tras_filtro': int(len(F)),
        'mercados_medidos': sorted(P['mercado'].unique().tolist()),
        'pata_suelta': roi_pata(F),
        'pata_por_mercado': {m: roi_pata(F[F['mercado'] == m])
                             for m in sorted(F['mercado'].unique())},
        'pata_por_banda': {f'{lo}-{hi}': roi_pata(
            P[(P['cuota'] >= lo) & (P['cuota'] <= hi)
              & (P['prob'] >= PROB_MINIMA)])
            for lo, hi in BANDAS},
        # el ECE por liga se mide sobre su propia ventana, más larga
        'ece_por_liga': ece_por_liga(conjunto_patas(
            (hoy - _dt.timedelta(days=int(MESES_ECE * 30.44))).isoformat())),
        'meses_ece': MESES_ECE,
        'configuraciones': [],
    }

    for n in N_PATAS:
        for lo, hi in BANDAS:
            cfg = simular(P, n, lo, hi, n_sim)
            # LA PROYECCION DESDE LA PATA SUELTA, que es la estimacion fiable.
            # El ROI simulado sale de dias repetidos; el de la pata sale de
            # observaciones independientes. Un parlay de patas independientes
            # rinde (1+e)^N - 1, asi que esta columna es lo que cabe esperar y
            # la simulada es lo que salio en esas jornadas concretas.
            _e = (doc['pata_por_banda'].get(f'{lo}-{hi}') or {}).get('roi')
            cfg['roi_proyectado_desde_la_pata'] = (
                round((1.0 + _e) ** n - 1.0, 4) if _e is not None else None)
            cfg['veredicto'] = _veredicto_config(cfg)
            doc['configuraciones'].append(cfg)
            logger.info('[sonadora] %2d patas %.2f-%.2f -> hit %.3f%% roi %s',
                        n, lo, hi, (cfg.get('hit_rate') or 0) * 100,
                        cfg.get('roi_simulado'))

    # POR COMBINACION DE DEPORTES, que es lo que el selector permite pedir.
    # Se mide la pata suelta de cada combo —el numero del que cuelga todo— y
    # una configuracion representativa de 4 patas.
    doc['por_deporte'] = {}
    for combo in COMBOS_DEPORTE:
        sub = P[P['deporte'].isin(combo)]
        F2 = sub[(sub['cuota'] >= 1.10) & (sub['cuota'] <= 1.80)
                 & (sub['prob'] >= PROB_MINIMA)]
        entrada = {'deportes': list(combo), 'pata_suelta': roi_pata(F2)}
        cfg4 = simular(sub, 4, 1.10, 1.80, max(n_sim // 4, 1000))
        cfg4['veredicto'] = _veredicto_config(cfg4)
        entrada['cuatro_patas'] = cfg4
        doc['por_deporte']['+'.join(combo)] = entrada
        logger.info('[sonadora] %s: pata suelta n=%s roi=%s · 4 patas hit=%s',
                    '+'.join(combo), entrada['pata_suelta'].get('n'),
                    entrada['pata_suelta'].get('roi'), cfg4.get('hit_rate'))

    viables = [c for c in doc['configuraciones']
               if c.get('veredicto') == 'viable']
    doc['configuraciones_viables'] = [
        {'n_patas': c['n_patas'], 'rango_cuota': c['rango_cuota'],
         'roi_simulado': c['roi_simulado'], 'p5': c['p5'],
         'hit_rate': c['hit_rate']} for c in viables]
    doc['medido'] = True
    doc['veredicto'] = 'con_configuracion_viable' if viables else 'todas_negativas'
    return doc


def _veredicto_config(cfg: Dict) -> str:
    """El veredicto, con la puerta de muestra DELANTE del listón de ROI.

    Un ROI medido sobre cuatro jornadas no es un ROI, por bueno que salga: es
    la razón de que `DIAS_MINIMOS` se compruebe antes que nada.
    """
    roi = cfg.get('roi_simulado')
    if roi is None or not cfg.get('intentos'):
        return 'sin_muestra'
    if (cfg.get('dias_con_suficientes_partidos') or 0) < DIAS_MINIMOS:
        return 'sin_muestra'
    # el p5 que manda es el agrupado por jornada: el otro cuenta la misma
    # tarde de futbol dos mil veces
    _p5 = cfg.get('p5_por_dia')
    if _p5 is None:
        return 'sin_muestra'
    if roi > ROI_MINIMO and _p5 > P5_MINIMO:
        return 'viable'
    if roi > -0.20:
        return 'alto_riesgo'
    return 'loteria'


def _imprimir(doc: Dict) -> None:
    print('=' * 86)
    print('VALIDACIÓN DE LA SOÑADORA')
    print('=' * 86)
    print(f"Periodo: {doc.get('periodo')}   ·   "
          f"{doc.get('n_partidos')} partidos   ·   "
          f"{doc.get('n_patas_con_cuota')} patas con cuota real")
    print(f"Mercados con cuota en el histórico: "
          f"{', '.join(doc.get('mercados_medidos') or [])}")
    print()
    ps = doc.get('pata_suelta') or {}
    print('UNA PATA SUELTA (cuota 1,10-1,80 · prob ≥ 55 %)')
    if ps.get('n'):
        print(f"   n={ps['n']}   modelo dice {ps['prob_media']*100:.1f} %   "
              f"acierta {ps['acierto']*100:.1f} %   "
              f"ROI {ps['roi']*100:+.2f} %   p5 {(ps.get('p5') or 0)*100:+.2f} %")
    for m, v in (doc.get('pata_por_mercado') or {}).items():
        if v.get('n'):
            print(f"   {m:12s} n={v['n']:5d}  acierta {v['acierto']*100:5.1f} %"
                  f"  ROI {v['roi']*100:+6.2f} %  p5 "
                  f"{(v.get('p5') or 0)*100:+6.2f} %  ECE {v.get('ece')}")
    print()
    print(f"{'config':>16s} {'días':>5s} {'ganadas':>8s} {'hit':>8s} "
          f"{'teórico':>8s} {'multipl.':>9s} {'ROI sim':>8s} "
          f"{'p5/día':>8s} {'proyect.':>9s} {'dg':>4s}  veredicto")
    for c in doc.get('configuraciones') or []:
        if not c.get('intentos'):
            print(f"{c['n_patas']:>3d} patas {c['rango_cuota'][0]:.2f}-"
                  f"{c['rango_cuota'][1]:.2f}  {c.get('motivo', 'sin muestra')}")
            continue
        _pr = c.get('roi_proyectado_desde_la_pata')
        print(f"{c['n_patas']:>3d}p {c['rango_cuota'][0]:.2f}-"
              f"{c['rango_cuota'][1]:.2f} "
              f"{c.get('dias_con_suficientes_partidos', 0):>5d} "
              f"{c['ganadas']:>8d} {c['hit_rate']*100:>7.2f}% "
              f"{c['hit_rate_teorico']*100:>7.2f}% "
              f"{c['multiplicador_medio']:>9.2f} "
              f"{(c.get('roi_simulado') or 0)*100:>7.1f}% "
              f"{(c.get('p5_por_dia') or 0)*100:>7.1f}% "
              f"{(_pr*100 if _pr is not None else 0):>8.1f}% "
              f"{c.get('dias_que_aportan_ganadoras', 0):>4d}  {c['veredicto']}")
    print()
    print('POR COMBINACION DE DEPORTES (pata suelta y 4 patas 1,10-1,80)')
    for nombre, e in (doc.get('por_deporte') or {}).items():
        ps2 = e.get('pata_suelta') or {}
        c4 = e.get('cuatro_patas') or {}
        if not ps2.get('n'):
            print(f"   {nombre:24s} sin patas con cuota en la ventana")
            continue
        print(f"   {nombre:24s} n={ps2['n']:6d} acierta "
              f"{ps2['acierto']*100:5.1f} % ROI {ps2['roi']*100:+6.2f} % "
              f"| 4 patas: hit {(c4.get('hit_rate') or 0)*100:5.2f} % "
              f"mult {c4.get('multiplicador_medio', 0):6.2f}x "
              f"ROI {(c4.get('roi_simulado') or 0)*100:+6.1f} % "
              f"({c4.get('dias_con_suficientes_partidos', 0)} jornadas)")
    print()
    print(f"VEREDICTO: {doc.get('veredicto')}")
    for c in doc.get('configuraciones_viables') or []:
        print(f"   viable: {c['n_patas']} patas {c['rango_cuota']} "
              f"ROI {c['roi_simulado']*100:+.1f} % p5 {c['p5']*100:+.1f} %")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--meses', type=int, default=6)
    ap.add_argument('--simulaciones', type=int, default=N_SIMULACIONES)
    ap.add_argument('--informe', action='store_true',
                    help='no escribe el JSON')
    args = ap.parse_args()

    doc = validar(args.meses, args.simulaciones)
    try:
        _imprimir(doc)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            json.dumps(doc, ensure_ascii=False, indent=1).encode('utf-8'))
    if not args.informe:
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f'\nEscrito {SALIDA}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
