#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibración del ajuste por contexto de arranque de temporada en la NFL.

QUÉ PREGUNTA RESPONDE
---------------------
La hipótesis es que las semanas 1-3 de la NFL tienen ruido estructural
(coordinadores nuevos, líneas reorganizadas) y que por eso los favoritos con
spread grande fallan más de lo que dice su probabilidad. Si eso es cierto y se
puede medir, la confianza de esos partidos hay que recortarla con un peso γ₁
medido, no inventado.

Este script NO decide por corazonada: construye la muestra, la mide contra el
resultado real y escribe el veredicto en `modelos/contexto_nfl.json`. Si la
muestra no da para sostener un peso, lo dice y el veredicto es que NO se
despliega. Ésa es la regla del proyecto: medir antes de desplegar, y un «a
priori no hay motivo» no es una medición (bitácora §6 del traspaso).

CÓMO SE CONSTRUYE LA MUESTRA
----------------------------
Walk-forward, igual que `modelo_nfl.backtest`: para cada temporada de juicio se
entrena con las anteriores y se predice la siguiente, así que ninguna
probabilidad ha visto su propio partido. De ahí salen:

  * `p_fav`   — probabilidad que el modelo le da al favorito del mercado
  * `gana_fav`— si ganó
  * `semana`  — la semana de temporada regular
  * `spread`  — la línea de cierre, en puntos

EL SPREAD ESTÁ SUCIO Y AQUÍ SE LIMPIA
-------------------------------------
`nfl_datos._pointspread` cae al campo `american` cuando falta `value`, y para
unos cuantos partidos ESPN mete ahí el PRECIO (-115) en vez de la línea (-6.5).
Eso deja valores imposibles en `hcp_home` (el récord de spread en la NFL ronda
los 27 puntos). Aquí se descartan los |spread| > 30 y se cuentan aparte, para
que el recuento de la muestra no mienta.

Uso:
    python calibrar_contexto_nfl.py            # mide y escribe el veredicto
    python calibrar_contexto_nfl.py --informe  # mide y sólo imprime
"""

import json
import logging
import math
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

HISTORICO = 'historico_nfl.csv'
SALIDA = os.path.join('modelos', 'contexto_nfl.json')

SEMANAS_ARRANQUE = (1, 2, 3)
SPREAD_MINIMO = 9.5          # «favorito con spread ≤ -9.5»
SPREAD_IMPOSIBLE = 30.0      # por encima de esto es precio americano colado

# Mínimos para que un peso ajustado signifique algo. NO son redondos por gusto:
# se eligen de una cuenta de potencia que este mismo fichero imprime en el
# informe (`_potencia`). Con menos que esto, un γ ajustado es ruido con
# decimales, y desplegarlo sería exactamente lo que la bitácora prohíbe.
N_MINIMO_SUBCONJUNTO = 100   # partidos en semanas 1-3 con spread grande
N_MINIMO_CONTROL = 100       # partidos de semanas 4+ con spread grande
MEJORA_ECE_MINIMA = 0.05     # 5 % relativo, el listón del encargo


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def ece(p: np.ndarray, y: np.ndarray, n_cajas: int = 10) -> float:
    """Error de calibración esperado, por cajas de anchura fija.

    Es la media de |confianza − acierto| dentro de cada caja, pesada por
    cuántos casos caen en ella. Cero es calibración perfecta.
    """
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(p) == 0:
        return float('nan')
    bordes = np.linspace(0.0, 1.0, n_cajas + 1)
    total = 0.0
    for i in range(n_cajas):
        lo, hi = bordes[i], bordes[i + 1]
        dentro = (p > lo) & (p <= hi) if i else (p >= lo) & (p <= hi)
        if not dentro.any():
            continue
        total += dentro.mean() * abs(p[dentro].mean() - y[dentro].mean())
    return float(total)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2)) if len(p) else float('nan')


def _ic_diferencia(k1: int, n1: int, k2: int, n2: int) -> Dict[str, float]:
    """Intervalo de confianza al 95 % de la diferencia de dos proporciones.

    Es la comprobación que puede FALLAR: si el intervalo contiene el cero, la
    diferencia medida es compatible con no haber diferencia, y entonces no hay
    nada que calibrar.
    """
    if n1 <= 0 or n2 <= 0:
        return {'dif': float('nan'), 'lo': float('nan'), 'hi': float('nan')}
    p1, p2 = k1 / n1, k2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p1 - p2
    # Con una proporción pegada a 0 o a 1 la varianza binomial sale CERO y el
    # intervalo se estrecha hasta parecer concluyente. Es el caso de «6 de 6
    # favoritos ganaron»: la fórmula normal diría que el cero queda fuera y no
    # significaría nada. Se marca para que nadie lo cite como prueba.
    degenerado = (min(n1, n2) < 30 or p1 in (0.0, 1.0) or p2 in (0.0, 1.0))
    return {'dif': d, 'lo': d - 1.96 * se, 'hi': d + 1.96 * se,
            'se': se, 'p1': p1, 'p2': p2,
            'interpretable': not degenerado}


def _potencia(p_base: float, efecto: float, n: int) -> float:
    """Potencia aproximada para detectar `efecto` (en proporción) con n por
    grupo, a dos colas y α=0,05. Sirve para justificar el mínimo de muestra en
    vez de fijarlo a ojo."""
    if n <= 0:
        return 0.0
    p2 = max(1e-6, min(1 - 1e-6, p_base - efecto))
    se = math.sqrt(p_base * (1 - p_base) / n + p2 * (1 - p2) / n)
    if se <= 0:
        return 0.0
    z = abs(efecto) / se - 1.96
    return float(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))


# ---------------------------------------------------------------------------
# Muestra
# ---------------------------------------------------------------------------
def _devig(c1, c2):
    try:
        p1, p2 = 1.0 / float(c1), 1.0 / float(c2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    s = p1 + p2
    return (p1 / s) if s > 0 else None


def construir_muestra(ruta: str = HISTORICO,
                      temporadas_juicio: Optional[List[int]] = None
                      ) -> pd.DataFrame:
    """Juicio walk-forward con semana, spread limpio y probabilidad del modelo.

    Devuelve una fila por partido juzgado, siempre fuera de muestra.
    """
    import modelo_nfl as mn

    d = pd.read_csv(ruta, dtype={'event_id': str})
    ds = mn.construir_dataset(d)
    ds = ds[ds['tipo'].isin(mn.TIPOS_ENTRENAMIENTO)].reset_index(drop=True)

    # `construir_dataset` no arrastra la semana: se recupera por event_id.
    semanas = d.set_index(d['event_id'].astype(str))['semana'].to_dict()
    ds['semana'] = ds['event_id'].astype(str).map(semanas)

    if temporadas_juicio is None:
        temporadas = sorted(int(t) for t in ds['temporada'].dropna().unique())
        # se juzga toda temporada que tenga al menos 150 partidos anteriores
        temporadas_juicio = [
            T for T in temporadas if int((ds['temporada'] < T).sum()) >= 150]

    trozos = []
    for T in temporadas_juicio:
        ent = ds[ds['temporada'] < T]
        jui = ds[ds['temporada'] == T]
        if len(ent) < 150 or not len(jui):
            logger.info('[contexto-nfl] temporada %s omitida '
                        '(entrena=%d juicio=%d)', T, len(ent), len(jui))
            continue
        m = mn.NFLModelo().entrenar(ent, alpha=mn.ALPHA)
        pm = m.m_margen.predecir(jui[mn.COLS_MARGEN].values)
        g = jui.copy()
        g['pred_margen'] = pm
        # el mismo método que elige `modelo_nfl.backtest`: residuos empíricos
        g['p_home'] = [float(np.mean(x + m.res_margen > 0.5)) for x in pm]
        g['temporada_juicio'] = T
        trozos.append(g)
        logger.info('[contexto-nfl] temporada %s: entrena=%d juicio=%d',
                    T, len(ent), len(jui))

    if not trozos:
        return pd.DataFrame()
    J = pd.concat(trozos, ignore_index=True)

    # --- favorito del MERCADO, que es de quien habla la hipótesis ----------
    J['p_mercado_home'] = [_devig(a, b) for a, b in
                           zip(J['ml_home'], J['ml_away'])]
    J = J[J['p_mercado_home'].notna()].reset_index(drop=True)
    fav_home = J['p_mercado_home'].astype(float) > 0.5
    J['fav_es_home'] = fav_home
    J['p_fav_modelo'] = np.where(fav_home, J['p_home'], 1 - J['p_home'])
    J['p_fav_mercado'] = np.where(fav_home, J['p_mercado_home'],
                                  1 - J['p_mercado_home'].astype(float))
    J['gana_fav'] = np.where(fav_home, J['margen'] > 0, J['margen'] < 0)
    J = J[J['margen'] != 0].reset_index(drop=True)      # empates: no hay lado

    # --- spread limpio -----------------------------------------------------
    hcp = pd.to_numeric(J['hcp_home'], errors='coerce')
    sucio = hcp.notna() & (hcp.abs() > SPREAD_IMPOSIBLE)
    J['spread_sucio'] = sucio
    J['spread_fav'] = np.where(hcp.notna() & ~sucio, hcp.abs(), np.nan)
    J['arranque'] = J['semana'].isin(SEMANAS_ARRANQUE)
    return J


def spread_implicito(J: pd.DataFrame) -> pd.Series:
    """Spread estimado desde el moneyline, AJUSTADO sobre los partidos que
    traen las dos cosas. No es una constante de libro: es la recta que sale de
    esta misma muestra, y sólo se usa como sensibilidad, nunca como el dato.
    """
    base = J[J['spread_fav'].notna() & J['p_fav_mercado'].notna()]
    if len(base) < 50:
        return pd.Series(np.nan, index=J.index)
    x = np.log(base['p_fav_mercado'].astype(float).clip(0.5001, 0.9999)
               / (1 - base['p_fav_mercado'].astype(float).clip(0.5001, 0.9999)))
    y = base['spread_fav'].astype(float)
    a, b = np.polyfit(x, y, 1)
    xx = np.log(J['p_fav_mercado'].astype(float).clip(0.5001, 0.9999)
                / (1 - J['p_fav_mercado'].astype(float).clip(0.5001, 0.9999)))
    return pd.Series(a * xx + b, index=J.index)


# ---------------------------------------------------------------------------
# Medición
# ---------------------------------------------------------------------------
def _bloque(sub: pd.DataFrame, nombre: str) -> Dict:
    if not len(sub):
        return {'nombre': nombre, 'n': 0}
    p = sub['p_fav_modelo'].astype(float).values
    y = sub['gana_fav'].astype(float).values
    return {
        'nombre': nombre,
        'n': int(len(sub)),
        'confianza_media': round(float(p.mean()), 4),
        'acierto_real': round(float(y.mean()), 4),
        'sesgo_pp': round(float((p.mean() - y.mean()) * 100), 2),
        'ece': round(ece(p, y), 5),
        'brier': round(brier(p, y), 5),
    }


def medir(J: pd.DataFrame, columna_spread: str = 'spread_fav') -> Dict:
    """Compara los favoritos grandes de semanas 1-3 contra los de semanas 4+."""
    grande = J[columna_spread].astype(float) >= SPREAD_MINIMO
    sub = J[grande & J['arranque']]
    ctl = J[grande & ~J['arranque']]

    inf = {
        'criterio_spread': columna_spread,
        'n_juicio_total': int(len(J)),
        'n_con_spread': int(J[columna_spread].notna().sum()),
        'n_spread_sucio_descartado': int(J['spread_sucio'].sum()),
        'arranque': _bloque(sub, 'semanas 1-3, spread >= 9.5'),
        'control': _bloque(ctl, 'semanas 4+, spread >= 9.5'),
        'arranque_todos': _bloque(J[J['arranque']], 'semanas 1-3, cualquier spread'),
        'control_todos': _bloque(J[~J['arranque']], 'semanas 4+, cualquier spread'),
    }
    ic = _ic_diferencia(int(sub['gana_fav'].sum()), len(sub),
                        int(ctl['gana_fav'].sum()), len(ctl))
    inf['diferencia_acierto'] = {
        k: (v if isinstance(v, bool) else (round(v, 4) if v == v else None))
        for k, v in ic.items()}
    inf['potencia_10pp'] = round(_potencia(0.75, 0.10,
                                           min(len(sub), len(ctl))), 3)
    return inf


def ajustar_gamma(J: pd.DataFrame, columna_spread: str = 'spread_fav') -> Dict:
    """Regresión logística del resultado sobre el logit del modelo y la
    bandera de arranque. γ₁ es lo que hay que mover el logit en semanas 1-3.

    Se ajusta con descenso de gradiente sobre la verosimilitud, sin depender de
    scikit-learn (el proyecto no lo tiene en el camino de producción).
    """
    grande = J[columna_spread].astype(float) >= SPREAD_MINIMO
    sub = J[grande].copy()
    if len(sub) < 30:
        return {'ajustado': False, 'motivo': 'muestra insuficiente',
                'n': int(len(sub))}
    p = sub['p_fav_modelo'].astype(float).clip(1e-4, 1 - 1e-4).values
    z = np.log(p / (1 - p))
    a = sub['arranque'].astype(float).values
    y = sub['gana_fav'].astype(float).values
    X = np.column_stack([np.ones(len(z)), z, a])
    w = np.zeros(3)
    for _ in range(4000):
        q = 1.0 / (1.0 + np.exp(-X @ w))
        w += 0.05 * (X.T @ (y - q)) / len(y)
    return {'ajustado': True, 'n': int(len(sub)),
            'intercepto': round(float(w[0]), 4),
            'pendiente_logit': round(float(w[1]), 4),
            'gamma_1_logit': round(float(w[2]), 4)}


def comparar_ece(J: pd.DataFrame, gamma_1: float,
                 columna_spread: str = 'spread_fav') -> Dict:
    """ECE del subconjunto con y sin el ajuste. El número que decide."""
    grande = J[columna_spread].astype(float) >= SPREAD_MINIMO
    sub = J[grande & J['arranque']]
    if not len(sub):
        return {'n': 0}
    p = sub['p_fav_modelo'].astype(float).clip(1e-4, 1 - 1e-4).values
    y = sub['gana_fav'].astype(float).values
    z = np.log(p / (1 - p)) + gamma_1
    p_aj = 1.0 / (1.0 + np.exp(-z))
    e0, e1 = ece(p, y), ece(p_aj, y)
    return {'n': int(len(sub)),
            'ece_sin_modulo': round(e0, 5), 'ece_con_modulo': round(e1, 5),
            'mejora_relativa': (round((e0 - e1) / e0, 4) if e0 > 0 else None),
            'brier_sin_modulo': round(brier(p, y), 5),
            'brier_con_modulo': round(brier(p_aj, y), 5)}


# ---------------------------------------------------------------------------
# Veredicto
# ---------------------------------------------------------------------------
def calibrar(ruta: str = HISTORICO) -> Dict:
    J = construir_muestra(ruta)
    if not len(J):
        return {'medido': False, 'veredicto': 'sin_muestra',
                'motivo': 'el histórico no da para juzgar ninguna temporada '
                          'fuera de muestra'}

    inf = medir(J)
    J['spread_implicito'] = spread_implicito(J)
    inf['sensibilidad_spread_implicito'] = medir(J, 'spread_implicito')

    gamma = ajustar_gamma(J)
    inf['ajuste'] = gamma

    n_sub = inf['arranque']['n']
    n_ctl = inf['control']['n']
    ic = inf['diferencia_acierto']

    motivos = []
    if n_sub < N_MINIMO_SUBCONJUNTO:
        motivos.append(
            f"el subconjunto de semanas 1-3 con spread ≥ {SPREAD_MINIMO} tiene "
            f"{n_sub} partidos y el mínimo para ajustar un peso es "
            f"{N_MINIMO_SUBCONJUNTO}")
    if n_ctl < N_MINIMO_CONTROL:
        motivos.append(
            f"el grupo de control (semanas 4+) tiene {n_ctl} partidos y el "
            f"mínimo es {N_MINIMO_CONTROL}")
    if not ic.get('interpretable', True):
        motivos.append(
            "el intervalo de la diferencia de acierto no es interpretable: "
            "algún grupo baja de 30 partidos o su proporción está pegada a 0 "
            "o a 1, y ahí la varianza binomial sale cero y el intervalo miente")
    elif ic.get('lo') is not None and ic.get('hi') is not None:
        if ic['lo'] <= 0 <= ic['hi']:
            motivos.append(
                f"la diferencia de acierto medida ({ic['dif']:+.3f}) tiene un "
                f"intervalo de confianza [{ic['lo']:+.3f}, {ic['hi']:+.3f}] "
                f"que contiene el cero: es compatible con no haber diferencia")

    salida = {
        'gamma_1': None, 'gamma_2': None, 'gamma_3': None,
        'medido': False,
        'fecha': pd.Timestamp.now('UTC').strftime('%Y-%m-%d'),
        'n_partidos': n_sub,
        'ece_mejora': None,
        'veredicto': 'no_desplegado',
        'informe': inf,
    }

    # γ₂ (coordinador nuevo) y γ₃ (dinero sharp) no tienen fuente en el
    # pipeline. No se inventan: se dicen.
    salida['reglas_sin_fuente'] = {
        'gamma_2_coordinador_nuevo':
            'no hay dato de coordinadores en nfl_datos.py ni en ninguna otra '
            'fuente del proyecto; la regla no se puede activar',
        'gamma_3_dinero_sharp':
            'no hay feed de reparto de apuestas; la regla no se puede activar',
        'novatos_titulares':
            'no hay depth chart ni año de debut por jugador en el pipeline',
    }

    if motivos:
        salida['veredicto'] = 'sin_muestra'
        salida['motivo'] = ' · '.join(motivos)
        return salida

    g1 = float(gamma.get('gamma_1_logit') or 0.0)
    cmp_ece = comparar_ece(J, g1)
    salida['comparacion_ece'] = cmp_ece
    mejora = cmp_ece.get('mejora_relativa')
    salida['ece_mejora'] = mejora
    if mejora is not None and mejora >= MEJORA_ECE_MINIMA:
        salida['gamma_1'] = round(g1, 4)
        salida['medido'] = True
        salida['veredicto'] = 'desplegado'
    else:
        salida['veredicto'] = 'no_mejora'
        salida['motivo'] = (
            f"el ajuste no baja el ECE lo suficiente "
            f"({mejora if mejora is not None else 'n/d'} frente al mínimo de "
            f"{MEJORA_ECE_MINIMA})")
    return salida


def _imprimir(res: Dict) -> None:
    inf = res.get('informe') or {}
    print('=' * 72)
    print('CALIBRACIÓN — ajuste por contexto de arranque (NFL semanas 1-3)')
    print('=' * 72)
    print(f"Partidos juzgados fuera de muestra: {inf.get('n_juicio_total', 0)}")
    print(f"Con spread de cierre utilizable:    {inf.get('n_con_spread', 0)}")
    print(f"Descartados por spread imposible:   "
          f"{inf.get('n_spread_sucio_descartado', 0)}")
    print()
    for clave in ('arranque', 'control', 'arranque_todos', 'control_todos'):
        b = inf.get(clave) or {}
        if not b.get('n'):
            print(f"  {b.get('nombre', clave):38s}  n=0")
            continue
        print(f"  {b['nombre']:38s}  n={b['n']:4d}  "
              f"confianza {b['confianza_media']*100:5.1f}%  "
              f"real {b['acierto_real']*100:5.1f}%  "
              f"sesgo {b['sesgo_pp']:+5.1f} pp  ECE {b['ece']:.4f}")
    ic = inf.get('diferencia_acierto') or {}
    if ic.get('dif') is not None:
        _aviso = '' if ic.get('interpretable', True) else '  ← NO interpretable'
        print(f"\n  Diferencia de acierto (1-3 menos 4+): {ic['dif']:+.3f} "
              f"IC95% [{ic.get('lo')}, {ic.get('hi')}]{_aviso}")
    print(f"  Potencia para detectar 10 pp:        {inf.get('potencia_10pp')}")
    print()
    print(f"VEREDICTO: {res.get('veredicto')}")
    if res.get('motivo'):
        print(f"  {res['motivo']}")
    for k, v in (res.get('reglas_sin_fuente') or {}).items():
        print(f"  · {k}: {v}")


if __name__ == '__main__':
    res = calibrar()
    try:
        _imprimir(res)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(json.dumps(res, ensure_ascii=False,
                                           indent=1).encode('utf-8') + b'\n')
    if '--informe' not in sys.argv:
        os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"\nEscrito {SALIDA}")
