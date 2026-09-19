#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v212 — La puerta de activación: backtesting fuera de muestra y el veredicto.

QUÉ HACE
--------
Mide las reglas nuevas contra los ledgers walk-forward del proyecto y escribe
DOS cosas:

    activacion_v212.json   el interruptor que leen `modo_seguridad` y
                           `escalada_lineas`. Sin él, las reglas están
                           apagadas.
    backtesting_v212.md    el informe con las tablas y la justificación.

LOS CUATRO CRITERIOS (§7.3 del encargo)
---------------------------------------
Una regla se activa SOLA si y sólo si, contra su línea base:

    Brier      <=  baseline      (no empeora la calibración)
    p5         >=  0             (no pierde en el peor 5 % de escenarios)
    hit rate   >=  baseline      (no acierta menos)
    ROI        >=  baseline      (no gana menos)

Si alguno falla, o si alguno NO SE PUEDE MEDIR, la regla se queda apagada. No
medible cuenta como no aprobado: es la única lectura que no permite colar una
regla por falta de datos.

POR QUÉ ESTE BACKTEST ES FUERA DE MUESTRA DE VERDAD (§7.4)
----------------------------------------------------------
No hace falta partir 2025/2026 a mano: los ledgers YA son walk-forward.
`build_ledger_totales.py` (línea 112) recorta los índices de entrenamiento a
fechas estrictamente anteriores al mínimo del pliegue de test, así que cada
probabilidad del ledger la produjo un modelo que no vio ese partido. Se
verifica y se reporta el reparto por pliegue.

LO QUE NO SE PUEDE MEDIR, Y SE DICE
-----------------------------------
El almacén histórico (`odds_historico.db`, 155.364 filas) sólo guarda precio de
la línea de goles 2,5: `odds_over25` / `odds_under25`. No hay cuota de Más de
3,5 en ninguna fuente del proyecto. Por lo tanto:

  · la escalada 1,5 -> 2,5 SÍ se puede medir con precio real (se apuesta la
    línea 2,5, que tiene cuota), y se mide.
  · la escalada 2,5 -> 3,5 NO tiene precio para la línea que se apostaría.
    Inventarle una cuota «justa más un margen típico» sería fabricar el número
    del que depende el ROI. Se marca `no_medible` y se queda APAGADA.

Uso:
    python backtest_v212.py                 # mide, escribe JSON e informe
    python backtest_v212.py --sin-escribir  # sólo imprime
"""

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('backtest_v212')

SALIDA_JSON = 'activacion_v212.json'
SALIDA_MD = 'backtesting_v212.md'

LEDGER_1X2 = 'pick_ledger_total.csv'
LEDGER_TOTALES = 'pick_ledger_totales.csv'

N_MINIMO_DEPORTE = 1000     # §7.1
N_BOOTSTRAP = 2000
N_MONTECARLO = 10000
DIAS_RUINA = 30
RUINA_MAXIMA = 0.05         # §7.5
APUESTAS_POR_DIA = 3


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def brier(p: np.ndarray, y: np.ndarray) -> Optional[float]:
    if len(p) == 0:
        return None
    return float(np.mean((p - y) ** 2))


def ece(p: np.ndarray, y: np.ndarray, n_cajas: int = 10) -> Optional[float]:
    """Expected calibration error, mismo esquema que `riesgo_liga._ece`."""
    if len(p) == 0:
        return None
    bordes = np.linspace(0, 1, n_cajas + 1)
    total, n = 0.0, len(p)
    for i in range(n_cajas):
        m = (p >= bordes[i]) & (p < bordes[i + 1] if i < n_cajas - 1
                                else p <= bordes[i + 1])
        if not m.any():
            continue
        total += m.sum() / n * abs(y[m].mean() - p[m].mean())
    return float(total)


def roi_de(ganancias: np.ndarray) -> Optional[float]:
    """ROI a stake plano de 1 unidad. `ganancias` es el neto por apuesta."""
    if len(ganancias) == 0:
        return None
    return float(np.mean(ganancias))


def p5_bootstrap(ganancias: np.ndarray, n: int = N_BOOTSTRAP,
                 seed: int = 42) -> Optional[float]:
    """Percentil 5 del ROI remuestreado. El criterio rey del proyecto."""
    if len(ganancias) < 30:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ganancias), size=(n, len(ganancias)))
    return float(np.percentile(ganancias[idx].mean(axis=1), 5))


def montecarlo_ruina(ganancias: np.ndarray, dias: int = DIAS_RUINA,
                     n_sim: int = N_MONTECARLO, seed: int = 7) -> Dict:
    """Ruina, ROI esperado con IC90 y drawdown, remuestreando picks reales.

    No se asume ninguna distribución: se remuestrean las ganancias observadas,
    que es lo que hay. Stake plano del 2 % de la banca.
    """
    vacio = {'prob_ruina': None, 'roi_ic90': None, 'drawdown_max': None}
    if len(ganancias) < 30:
        return vacio
    rng = np.random.default_rng(seed)
    n_apuestas = max(1, dias * APUESTAS_POR_DIA)
    muestras = ganancias[rng.integers(0, len(ganancias),
                                      size=(n_sim, n_apuestas))]
    stake = 0.02
    banca = np.ones(n_sim)
    pico = np.ones(n_sim)
    caida = np.zeros(n_sim)
    quebrado = np.zeros(n_sim, dtype=bool)
    for t in range(n_apuestas):
        banca = banca + banca * stake * muestras[:, t]
        banca = np.maximum(banca, 0.0)
        quebrado |= banca <= 0.20          # ruina: perder el 80 % de la banca
        pico = np.maximum(pico, banca)
        caida = np.maximum(caida, (pico - banca) / np.maximum(pico, 1e-9))
    roi_final = banca - 1.0
    return {'prob_ruina': float(quebrado.mean()),
            'roi_ic90': [float(np.percentile(roi_final, 5)),
                         float(np.percentile(roi_final, 95))],
            'drawdown_max': float(np.percentile(caida, 95))}


def medir(p: np.ndarray, y: np.ndarray,
          ganancias: Optional[np.ndarray]) -> Dict:
    """El paquete de métricas de una versión."""
    d = {'n': int(len(p)),
         'brier': brier(p, y),
         'ece': ece(p, y),
         'hit_rate': float(np.mean(y)) if len(y) else None,
         'roi': None, 'p5': None, 'montecarlo': {}}
    if ganancias is not None and len(ganancias):
        d['roi'] = roi_de(ganancias)
        d['p5'] = p5_bootstrap(ganancias)
        d['montecarlo'] = montecarlo_ruina(ganancias)
    return d


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
def _devig(cuotas: List[Optional[float]]) -> List[Optional[float]]:
    """Probabilidades implícitas sin margen. None donde no haya cuota."""
    inv, ok = [], []
    for c in cuotas:
        if c is not None and c > 1.0:
            inv.append(1.0 / c)
            ok.append(True)
        else:
            inv.append(0.0)
            ok.append(False)
    s = sum(inv)
    if s <= 0:
        return [None] * len(cuotas)
    return [(v / s if k else None) for v, k in zip(inv, ok)]


def cargar_1x2() -> pd.DataFrame:
    """El ledger de ganador, con la mejor selección del modelo por partido."""
    d = pd.read_csv(LEDGER_1X2)
    d = d[d.cuota_home.notna() & d.cuota_away.notna()].copy()

    probs = d[['p_home', 'p_draw', 'p_away']].fillna(0.0).to_numpy()
    cuotas = d[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(dtype=float)

    elegido = probs.argmax(axis=1)
    fila = np.arange(len(d))
    d['prob_modelo'] = probs[fila, elegido]
    d['cuota_pick'] = cuotas[fila, elegido]
    # `resultado` es el ÍNDICE entero de la columna que acertó (0 local,
    # 1 empate, 2 visitante), no una cadena. Compararlo contra 'home'/'draw'/
    # 'away' daba cero aciertos siempre y un ROI de −100 % en las tres
    # versiones, que es justo el tipo de número que parece un resultado.
    d['indice_elegido'] = elegido
    d['lado'] = [['home', 'draw', 'away'][i] for i in elegido]

    # probabilidad de mercado devigada, del mismo lado elegido
    inv = np.where(np.isfinite(cuotas) & (cuotas > 1.0), 1.0 / cuotas, np.nan)
    suma = np.nansum(inv, axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        devig = inv / suma[:, None]
    d['prob_mercado'] = devig[fila, elegido]

    d['acierto'] = (d['resultado'].astype(int)
                    == d['indice_elegido']).astype(int)
    d = d[d.cuota_pick.notna() & (d.cuota_pick > 1.0)
          & d.prob_mercado.notna()].copy()
    return d


def cargar_totales() -> pd.DataFrame:
    """El ledger de goles. Sólo la línea 2,5 tiene precio histórico."""
    d = pd.read_csv(LEDGER_TOTALES)
    d = d[d.cuota_over25.notna() & (d.cuota_over25 > 1.0)].copy()
    d = d[d['p_over_2.5'].notna() & d['over_2.5_real'].notna()].copy()
    return d


# ---------------------------------------------------------------------------
# Las tres versiones
# ---------------------------------------------------------------------------
def _factor_riesgo(claves: pd.Series) -> np.ndarray:
    """Factor de riesgo por competición, del índice medido."""
    try:
        import auditoria_pick as ap
        import riesgo_liga as rl
        cache = {}
        fuera = []
        for k in claves:
            if k not in cache:
                cache[k] = ap.FACTOR_RIESGO.get(rl.nivel_liga(k), 1.3)
            fuera.append(cache[k])
        return np.asarray(fuera, dtype=float)
    except Exception as e:
        logger.warning('[backtest] sin índice de riesgo (%s): se usa 1,3', e)
        return np.full(len(claves), 1.3)


def aplicar_modo_seguridad(d: pd.DataFrame) -> np.ndarray:
    """Máscara booleana: qué filas entran en Modo Seguridad.

    Llama a `modo_seguridad.evaluar`, que es EXACTAMENTE la función que corre
    en producción. Si se reimplementaran aquí los umbrales, el backtest dejaría
    de decir nada sobre lo que el usuario ve.
    """
    import modo_seguridad as ms
    factores = _factor_riesgo(d['liga'])
    fuera = np.zeros(len(d), dtype=bool)
    p = d['prob_modelo'].to_numpy()
    pm = d['prob_mercado'].to_numpy()
    c = d['cuota_pick'].to_numpy()
    for i in range(len(d)):
        try:
            fuera[i] = bool(ms.evaluar(p[i], pm[i], c[i],
                                       factor_riesgo=float(factores[i]))['entra'])
        except Exception:
            fuera[i] = False
    return fuera


def aplicar_escalada(d: pd.DataFrame, referencia: str = 'superior',
                     fuentes_requeridas: int = 2) -> np.ndarray:
    """Máscara: dónde la regla de 4 fuentes escalaría de Más de 1,5 a Más de 2,5.

    Se elige este par y no 2,5 -> 3,5 porque es el único con PRECIO para la
    línea que se apostaría. La media reciente de goles se aproxima con la suma
    de lambdas del propio ledger (`lam_h + lam_a`), que es la cantidad que el
    motor usa para esa predicción; no hay xG observado en el ledger, así que
    `esperado_5` va a None y la fuente de forma no puede pasar de MEDIA salvo
    por la vía de la referencia.
    """
    import escalada_lineas as el
    fuera = np.zeros(len(d), dtype=bool)
    p_sup = d['p_over_2.5'].to_numpy()
    cuota = d['cuota_over25'].to_numpy()
    lam = (d['lam_h'].fillna(0) + d['lam_a'].fillna(0)).to_numpy()
    for i in range(len(d)):
        try:
            r = el.evaluar('goles', 1.5, 2.5, 'futbol',
                           prob_superior=float(p_sup[i]),
                           cuota_superior=float(cuota[i]),
                           cuota_base=1.35,
                           media_5=float(lam[i]),
                           esperado_5=None,
                           senales=None,
                           referencia_forma=referencia,
                           fuentes_requeridas=fuentes_requeridas)
            fuera[i] = bool(r.get('escalar'))
        except Exception:
            fuera[i] = False
    return fuera


# ---------------------------------------------------------------------------
# La puerta
# ---------------------------------------------------------------------------
def veredicto(base: Dict, nueva: Dict, n_minimo: int = N_MINIMO_DEPORTE) -> Dict:
    """Los cuatro criterios. NO MEDIBLE cuenta como NO APROBADO."""
    fallos, notas = [], []

    if nueva.get('n', 0) < 30:
        return {'activa': False, 'fallos': ['muestra vacía o mínima'],
                'muestra_insuficiente': True,
                'motivo': f"sólo {nueva.get('n', 0)} picks: no hay con qué medir"}

    def _cmp(clave, mejor_es_menor=False):
        a, b = base.get(clave), nueva.get(clave)
        if a is None or b is None:
            fallos.append(f'{clave} no medible')
            return
        ok = (b <= a) if mejor_es_menor else (b >= a)
        notas.append(f'{clave} {b:+.4f} vs {a:+.4f} '
                     f"{'OK' if ok else 'FALLA'}")
        if not ok:
            fallos.append(f'{clave} empeora ({b:.4f} contra {a:.4f})')

    _cmp('brier', mejor_es_menor=True)
    _cmp('hit_rate')
    _cmp('roi')

    p5 = nueva.get('p5')
    if p5 is None:
        fallos.append('p5 no medible')
    else:
        notas.append(f'p5 {p5:+.4f} ' + ('OK' if p5 >= 0 else 'FALLA'))
        if p5 < 0:
            fallos.append(f'p5 de bootstrap negativo ({p5:+.2%})')

    ruina = (nueva.get('montecarlo') or {}).get('prob_ruina')
    if ruina is None:
        fallos.append('probabilidad de ruina no medible')
    elif ruina > RUINA_MAXIMA:
        fallos.append(f'ruina a {DIAS_RUINA} días {ruina:.1%} > '
                      f'{RUINA_MAXIMA:.0%}')

    insuficiente = nueva.get('n', 0) < n_minimo
    if insuficiente:
        notas.append(f"muestra {nueva['n']} < {n_minimo}")

    activa = not fallos
    return {'activa': activa,
            'fallos': fallos,
            'notas': notas,
            'muestra_insuficiente': insuficiente,
            'motivo': ('pasa los cuatro criterios' if activa
                       else 'no se activa: ' + '; '.join(fallos))}


# ---------------------------------------------------------------------------
def correr() -> Dict:
    doc = {'generado': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'criterios': {'brier': '<= baseline', 'p5': '>= 0',
                         'hit_rate': '>= baseline', 'roi': '>= baseline',
                         'ruina_30d': f'<= {RUINA_MAXIMA:.0%}'},
           'deportes': {}, 'reglas': {}}

    # ---------------- Modo Seguridad, por deporte -------------------------
    d = cargar_1x2()
    logger.info('ledger 1X2 con cuota: %d filas, %d deportes',
                len(d), d.deporte.nunique())
    doc['pliegues'] = {str(k): int(v) for k, v in
                       d.pliegue.value_counts().sort_index().items()}

    resultados_ms = {}
    for deporte, g in d.groupby('deporte'):
        p = g['prob_modelo'].to_numpy()
        y = g['acierto'].to_numpy()
        gan = np.where(y == 1, g['cuota_pick'].to_numpy() - 1.0, -1.0)
        A = medir(p, y, gan)

        m = aplicar_modo_seguridad(g)
        B = medir(p[m], y[m], gan[m])
        v = veredicto(A, B)
        resultados_ms[deporte] = {'A': A, 'B': B, 'veredicto': v,
                                  'n_total': int(len(g)),
                                  'n_seguras': int(m.sum())}
        logger.info('  %-8s A n=%-6d roi=%+.4f | B n=%-5d roi=%s p5=%s -> %s',
                    deporte, A['n'], A['roi'] or 0, B['n'],
                    f"{B['roi']:+.4f}" if B['roi'] is not None else '?',
                    f"{B['p5']:+.4f}" if B['p5'] is not None else '?',
                    'ACTIVA' if v['activa'] else 'apagada')

    doc['deportes']['modo_seguridad'] = resultados_ms

    # Una regla se activa globalmente sólo si pasa en ALGÚN deporte con
    # muestra suficiente. Se guarda también el detalle por deporte.
    aprobados = [dep for dep, r in resultados_ms.items()
                 if r['veredicto']['activa']
                 and not r['veredicto'].get('muestra_insuficiente')]
    doc['reglas']['modo_seguridad'] = {
        'activa': bool(aprobados),
        'deportes_aprobados': aprobados,
        'motivo': ('activa en ' + ', '.join(aprobados) if aprobados
                   else 'no supera los criterios en ningún deporte con '
                        'muestra suficiente'),
        'detalle': {dep: r['veredicto'] for dep, r in resultados_ms.items()},
    }

    # ---------------- Escalada de líneas ----------------------------------
    t = cargar_totales()
    logger.info('ledger de totales con cuota 2,5: %d filas', len(t))
    p = t['p_over_2.5'].to_numpy()
    y = t['over_2.5_real'].to_numpy().astype(int)
    gan = np.where(y == 1, t['cuota_over25'].to_numpy() - 1.0, -1.0)
    A_esc = medir(p, y, gan)

    # LA REGLA COMPLETA (3 DE 4) NO ES MEDIBLE SOBRE DATOS PASADOS.
    # Dos de sus cuatro fuentes no existen en el histórico: el xG de este
    # repositorio lo escribe `correlated_synthetic_generator` (ARQUITECTURA
    # §5.3), así que la fuente de forma no puede alcanzar FUERTE; y nadie
    # archivó las señales de contexto de un partido de 2024. Con dos fuentes
    # tapadas, 3 de 4 no se dispara NI UNA VEZ: no es que falle, es que no
    # tiene con qué evaluarse.
    m_completa = aplicar_escalada(t, 'superior', fuentes_requeridas=3)
    esc = {'_regla_completa_3de4': {'n_escaladas': int(m_completa.sum())}}

    # Lo que SÍ se puede medir: la variante degradada de DOS fuentes, las que
    # existen en el histórico (modelo y mercado). No valida la regla del
    # encargo — valida su mitad medible, y se etiqueta como tal.
    for ref in ('superior', 'base'):
        m = aplicar_escalada(t, referencia=ref, fuentes_requeridas=2)
        C = medir(p[m], y[m], gan[m])
        v = veredicto(A_esc, C)
        esc[ref] = {'C': C, 'veredicto': v, 'n_escaladas': int(m.sum())}
        logger.info('  escalada 1,5->2,5 (2 fuentes) ref=%-9s n=%-6d roi=%s '
                    'p5=%s -> %s', ref, C['n'],
                    f"{C['roi']:+.4f}" if C['roi'] is not None else '?',
                    f"{C['p5']:+.4f}" if C['p5'] is not None else '?',
                    'pasa' if v['activa'] else 'no pasa')
    logger.info('  regla COMPLETA (3 de 4): %d disparos -> no medible',
                int(m_completa.sum()))

    doc['deportes']['escalada'] = {'A': A_esc, 'variantes': esc}

    aprob_degradada = [r for r in ('superior', 'base')
                       if esc[r]['veredicto']['activa']]
    doc['reglas']['escalada_lineas'] = {
        'activa': False,
        'no_medible': True,
        'disparos_regla_completa': int(m_completa.sum()),
        'motivo': 'la regla de 3 de 4 fuentes no se dispara ni una vez sobre '
                  'el histórico: dos de sus cuatro fuentes no existen ahí '
                  '(el xG del repositorio es sintético, y las señales de '
                  'contexto de partidos pasados no se archivaron). No es que '
                  'falle los criterios: es que no hay con qué evaluarla, y no '
                  'medible cuenta como no aprobado.',
        'que_haria_falta': 'xG observado (FotMob cubre hoy 28 partidos) y un '
                           'archivo de señales de contexto por partido, que '
                           'sólo se puede construir hacia delante',
        'variante_degradada_2_fuentes': {
            'que_es': 'modelo + mercado, las dos fuentes que sí existen en el '
                      'histórico. NO valida la regla del encargo.',
            'aprueba_en': aprob_degradada,
            'detalle': {r: esc[r]['veredicto'] for r in ('superior', 'base')},
        },
    }

    # La escalada 2,5 -> 3,5: declarada NO MEDIBLE, y por tanto apagada.
    doc['reglas']['escalada_2_5_a_3_5'] = {
        'activa': False,
        'no_medible': True,
        'motivo': 'no existe cuota histórica de Más de 3,5 en ninguna fuente '
                  'del proyecto (odds_historico.db sólo guarda la línea 2,5), '
                  'así que el ROI de la línea que se apostaría no se puede '
                  'medir. No medible cuenta como no aprobado.',
        'que_haria_falta': 'cuotas de cierre de Más de 3,5, por partido, en '
                           'al menos 1.000 partidos por competición',
    }

    # Deportes sin ledger fuera de muestra: NFL y KBO.
    doc['reglas']['modo_seguridad_nfl'] = {
        'activa': False, 'muestra_insuficiente': True,
        'motivo': 'no existe ledger walk-forward de NFL: `historico_nfl.csv` '
                  'tiene 1.095 partidos con resultado pero sin predicciones '
                  'fuera de muestra ni cuota de ganador',
        'que_haria_falta': 'construir un ledger walk-forward de NFL, como '
                           '`build_ledger_totales.py` hace con el fútbol'}
    doc['reglas']['modo_seguridad_kbo'] = {
        'activa': False, 'muestra_insuficiente': True,
        'motivo': 'no existe ledger walk-forward de KBO y `historico_kbo.csv` '
                  '(13.149 partidos) NO tiene ninguna columna de cuotas, así '
                  'que el ROI es inmedible por construcción',
        'que_haria_falta': 'una fuente de cuotas históricas de KBO'}
    return doc


# ---------------------------------------------------------------------------
def _fmt(v, pct=False, dec=4):
    if v is None:
        return '—'
    if pct:
        return f'{v*100:+.2f} %'
    return f'{v:.{dec}f}'


def escribir_md(doc: Dict, ruta: str = SALIDA_MD) -> None:
    L = [f'# Backtesting v212 — la puerta de activación\n',
         f"Generado por `backtest_v212.py` el {doc['generado']}.\n",
         '## Criterios de activación (§7.3)\n',
         'Una regla se activa **sola** si y sólo si cumple los cuatro. '
         '**No medible cuenta como no aprobado.**\n',
         '| criterio | umbral |', '|---|---|']
    for k, v in doc['criterios'].items():
        L.append(f'| {k} | {v} |')

    L += ['', '## Fuera de muestra (§7.4)\n',
          'Los ledgers son walk-forward por construcción: '
          '`build_ledger_totales.py` recorta el entrenamiento a fechas '
          'estrictamente anteriores al pliegue de test. Reparto por pliegue:\n',
          '| pliegue | picks |', '|---|---|']
    for k, v in (doc.get('pliegues') or {}).items():
        L.append(f'| {k} | {v:,} |'.replace(',', '.'))

    # Modo Seguridad
    L += ['', '## Modo Seguridad — A (baseline) vs B\n',
          '| deporte | versión | n | Brier | ECE | hit rate | ROI | p5 | ruina 30d |',
          '|---|---|---|---|---|---|---|---|---|']
    for dep, r in (doc['deportes'].get('modo_seguridad') or {}).items():
        for etq, m in (('A baseline', r['A']), ('B seguridad', r['B'])):
            mc = m.get('montecarlo') or {}
            L.append(f"| {dep} | {etq} | {m['n']:,} | {_fmt(m['brier'])} | "
                     f"{_fmt(m['ece'])} | {_fmt(m['hit_rate'])} | "
                     f"{_fmt(m['roi'], pct=True)} | {_fmt(m['p5'], pct=True)} | "
                     f"{_fmt(mc.get('prob_ruina'), pct=True)} |"
                     .replace(',', '.'))

    # Escalada
    esc = doc['deportes'].get('escalada') or {}
    if esc:
        L += ['', '## Escalada de líneas 1,5 → 2,5 (la única con precio real)\n',
              '| versión | n | Brier | ECE | hit rate | ROI | p5 |',
              '|---|---|---|---|---|---|---|']
        a = esc['A']
        L.append(f"| A baseline (todo Más de 2,5) | {a['n']:,} | "
                 f"{_fmt(a['brier'])} | {_fmt(a['ece'])} | "
                 f"{_fmt(a['hit_rate'])} | {_fmt(a['roi'], pct=True)} | "
                 f"{_fmt(a['p5'], pct=True)} |".replace(',', '.'))
        for ref, v in esc['variantes'].items():
            if 'C' not in v:      # la entrada de la regla completa no mide
                continue
            c = v['C']
            L.append(f"| C escalada (ref. {ref}) | {c['n']:,} | "
                     f"{_fmt(c['brier'])} | {_fmt(c['ece'])} | "
                     f"{_fmt(c['hit_rate'])} | {_fmt(c['roi'], pct=True)} | "
                     f"{_fmt(c['p5'], pct=True)} |".replace(',', '.'))

    # Veredicto
    L += ['', '## Decisión por regla (§7.6, §7.7)\n',
          '| regla | estado | por qué |', '|---|---|---|']
    for nombre, r in doc['reglas'].items():
        estado = '🟢 ACTIVADA' if r.get('activa') else '🔴 apagada'
        L.append(f"| `{nombre}` | {estado} | {r.get('motivo', '')} |")

    L += ['', '## Justificación escrita\n']
    for nombre, r in doc['reglas'].items():
        L.append(f"### `{nombre}` — "
                 f"{'activada' if r.get('activa') else 'apagada'}\n")
        L.append(r.get('motivo', '') + '\n')
        if r.get('que_haria_falta'):
            L.append(f"**Qué haría falta para poder decidirlo:** "
                     f"{r['que_haria_falta']}\n")
        det = r.get('detalle') or {}
        for k, v in det.items():
            if v.get('fallos'):
                L.append(f"- **{k}**: " + '; '.join(v['fallos']))
            elif v.get('activa'):
                L.append(f"- **{k}**: pasa los cuatro criterios")
        L.append('')

    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sin-escribir', action='store_true')
    a = ap.parse_args()

    doc = correr()

    print('\n=== VEREDICTO ===')
    for nombre, r in doc['reglas'].items():
        print(f"  {'ACTIVA  ' if r.get('activa') else 'apagada '} {nombre}")
        print(f"           {r.get('motivo', '')}")

    if not a.sin_escribir:
        with open(SALIDA_JSON, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, default=str)
        escribir_md(doc)
        print(f'\n-> {SALIDA_JSON}\n-> {SALIDA_MD}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
