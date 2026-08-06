#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Autopsia de los picks: dónde falla el sistema de forma SISTEMÁTICA.

Qué cierra
----------
Desde la v92 el circuito de producción registra los picks y los liquida contra
el resultado. Eso contesta «¿acerté?». No contesta la siguiente, que es la que
pidió el usuario: «¿qué tenían en común los que fallé?».

Este módulo la contesta partiendo cada conjunto de predicciones en SEGMENTOS
(liga, mercado, banda de probabilidad, franja de cuota, y las circunstancias del
partido anterior que extrae `contexto_previo`) y midiendo en cada uno la
BRECHA DE CALIBRACIÓN:

    brecha = acierto real − probabilidad media prometida

Una brecha negativa grande significa que el modelo promete más de lo que
entrega en ese segmento. Eso es una lección utilizable. Una brecha negativa
pequeña sobre veinte casos no es nada.

El listón, que es el punto del módulo
-------------------------------------
Un segmento sólo se declara LECCIÓN si:

  1. tiene al menos `MIN_N` casos, y
  2. el intervalo bootstrap de la brecha **no toca el cero**.

Sin ese listón esto sería una máquina de fabricar supersticiones: con 30
segmentos y ruido puro, uno o dos «destacan» siempre. Por eso el módulo reporta
también cuántos segmentos miró — un hallazgo entre 3 pesa distinto que uno
entre 300— y aplica corrección por comparaciones múltiples.

Dos fuentes, dos propósitos
---------------------------
  · `--historico` — sobre `pick_ledger*.csv` (más de 47.000 predicciones fuera
    de muestra). Aquí SÍ hay muestra para concluir. Es de donde puede salir un
    ajuste real.
  · `--produccion` — sobre `picks_historico.csv`, lo que se publicó de verdad.
    Hoy son ~144 picks liquidados: no alcanza para concluir casi nada, y el
    módulo lo dice en vez de inventarlo. Sirve para vigilar deriva y para que el
    histórico crezca.

Uso:
    python autopsia.py --historico
    python autopsia.py --produccion
"""
import argparse
import json
import logging
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Por debajo de esto no se concluye nada. 100 no es un número mágico: es el
# punto en el que el error estándar de una proporción cerca de 0,5 baja del
# 5 %, que es el orden de la brecha que se quiere detectar.
MIN_N = 100
BOOT = 3000
SEMILLA = 101
SALIDA_JSON = 'autopsia.json'
SALIDA_CSV = 'autopsias.csv'
# Corrección por comparaciones múltiples: con muchos segmentos, el percentil
# exigido se endurece (Šidák). Sin esto, mirar 40 segmentos garantiza dos
# «hallazgos» falsos al 5 %.
ALFA = 0.05


def _bootstrap_brecha(acierto: np.ndarray, prob: np.ndarray,
                      alfa: float) -> tuple:
    """Intervalo de la brecha (acierto − prometido) por remuestreo."""
    rng = np.random.default_rng(SEMILLA)
    n = len(acierto)
    d = acierto - prob
    bt = np.array([d[rng.integers(0, n, n)].mean() for _ in range(BOOT)])
    return (float(np.percentile(bt, 100 * alfa / 2)),
            float(np.percentile(bt, 100 * (1 - alfa / 2))))


def analizar(df: pd.DataFrame, col_acierto: str, col_prob: str,
             segmentaciones: Dict[str, pd.Series],
             min_n: int = MIN_N) -> Dict:
    """
    Brecha de calibración por segmento, con listón de significancia.

    `segmentaciones` es {nombre_del_corte: serie de etiquetas}. Se miran todos
    los cortes a la vez para poder corregir por el número TOTAL de segmentos
    examinados, que es lo que hace honesta la corrección.
    """
    acierto = pd.to_numeric(df[col_acierto], errors='coerce').to_numpy(dtype=float)
    prob = pd.to_numeric(df[col_prob], errors='coerce').to_numpy(dtype=float)
    ok = ~np.isnan(acierto) & ~np.isnan(prob)

    # se cuentan primero todos los segmentos elegibles, para el ajuste
    candidatos = []
    for corte, etiquetas in segmentaciones.items():
        e = etiquetas.to_numpy()
        for val in pd.unique(e[ok]):
            m = ok & (e == val)
            if m.sum() >= min_n:
                candidatos.append((corte, val, m))
    k = max(len(candidatos), 1)
    # Šidák: alfa por comparación para mantener el error global en ALFA
    alfa_c = 1 - (1 - ALFA) ** (1 / k)

    filas = []
    for corte, val, m in candidatos:
        a, p = acierto[m], prob[m]
        lo, hi = _bootstrap_brecha(a, p, alfa_c)
        brecha = float(a.mean() - p.mean())
        leccion = (lo > 0) or (hi < 0)          # el intervalo no toca el cero
        filas.append({
            'corte': corte, 'segmento': str(val), 'n': int(m.sum()),
            'acierto_real': round(float(a.mean()), 4),
            'prob_prometida': round(float(p.mean()), 4),
            'brecha': round(brecha, 4),
            'ic_bajo': round(lo, 4), 'ic_alto': round(hi, 4),
            'leccion': bool(leccion),
            'sentido': ('promete de más' if brecha < 0 else 'promete de menos')
                       if leccion else '—',
        })
    filas.sort(key=lambda r: (not r['leccion'], r['brecha']))
    return {'segmentos_examinados': k, 'alfa_por_segmento': round(alfa_c, 5),
            'min_n': min_n, 'lecciones': sum(f['leccion'] for f in filas),
            'filas': filas}


def _bandas(p: pd.Series) -> pd.Series:
    return pd.cut(pd.to_numeric(p, errors='coerce'),
                  [0, .5, .55, .6, .65, .7, .8, 1.0],
                  labels=['<50%', '50-55%', '55-60%', '60-65%',
                          '65-70%', '70-80%', '>80%'])


def _tercios(s: pd.Series, etiquetas) -> pd.Series:
    """Corte en tercios por cuantil; si no hay variación, todo a 'medio'."""
    x = pd.to_numeric(s, errors='coerce')
    try:
        return pd.qcut(x, 3, labels=etiquetas, duplicates='drop')
    except (ValueError, IndexError):
        return pd.Series([etiquetas[1]] * len(x), index=x.index)


# ---------------------------------------------------------------------------
# Fuente 1 — el ledger histórico (donde sí hay muestra)
# ---------------------------------------------------------------------------
def autopsia_historico() -> Dict:
    """Brechas de calibración sobre las predicciones fuera de muestra."""
    import contexto_previo as cp
    from _v101_ab_contexto_futbol import cargar_contexto

    ctx = cargar_contexto()
    salida = {}

    tot = pd.read_csv('pick_ledger_totales.csv').join(ctx, on='match_id',
                                                      how='left')
    for mercado, col_p, col_y in (('over_1.5', 'p_over_1.5', 'over_1.5_real'),
                                  ('over_2.5', 'p_over_2.5', 'over_2.5_real'),
                                  ('btts', 'p_btts', 'btts_real')):
        d = tot.dropna(subset=[col_p, col_y]).copy()
        print(f'\n=== {mercado}: {len(d)} predicciones fuera de muestra')
        segs = {
            'liga': d['liga'].astype(str),
            'banda de probabilidad': _bandas(d[col_p]).astype(str),
            'año': pd.to_datetime(d['fecha']).dt.year.astype(str),
            'escalón de rival': _tercios(
                d.get('DIFF_ESCALON', pd.Series(np.nan, index=d.index)),
                ['baja de nivel', 'similar', 'sube de nivel']),
            'descanso': _tercios(
                d.get('DIFF_DESCANSO', pd.Series(np.nan, index=d.index)),
                ['menos descanso', 'igual', 'más descanso']),
            'partido previo': _tercios(
                d.get('DIFF_MARGEN_PREV', pd.Series(np.nan, index=d.index)),
                ['venía de perder', 'igualado', 'venía de golear']),
        }
        salida[mercado] = analizar(d, col_y, col_p, segs)
        _imprimir(salida[mercado])

    led = pd.read_csv('pick_ledger.csv').join(ctx, on='match_id', how='left')
    # codificación verificada contra el marcador: 0 local, 1 empate, 2 visitante
    for etiqueta, col_p, valor in (('1x2 · gana local', 'p_home', 0),
                                   ('1x2 · empate', 'p_draw', 1),
                                   ('1x2 · gana visita', 'p_away', 2)):
        d = led.dropna(subset=[col_p, 'resultado']).copy()
        d['_y'] = (d['resultado'] == valor).astype(float)
        print(f'\n=== {etiqueta}: {len(d)} predicciones fuera de muestra')
        segs = {
            'liga': d['liga'].astype(str),
            'banda de probabilidad': _bandas(d[col_p]).astype(str),
            'año': pd.to_datetime(d['fecha']).dt.year.astype(str),
            'escalón de rival': _tercios(
                d.get('DIFF_ESCALON', pd.Series(np.nan, index=d.index)),
                ['baja de nivel', 'similar', 'sube de nivel']),
            'descanso': _tercios(
                d.get('DIFF_DESCANSO', pd.Series(np.nan, index=d.index)),
                ['menos descanso', 'igual', 'más descanso']),
        }
        salida[etiqueta] = analizar(d, '_y', col_p, segs)
        _imprimir(salida[etiqueta])
    return salida


# ---------------------------------------------------------------------------
# Fuente 2 — lo que se publicó de verdad
# ---------------------------------------------------------------------------
def autopsia_produccion(ruta: str = 'picks_historico.csv') -> Dict:
    """
    Brechas sobre los picks REALES ya liquidados.

    Con la muestra actual casi todo saldrá «sin muestra», y eso es el resultado
    correcto, no un fallo del módulo: 144 picks repartidos en cinco mercados no
    autorizan ninguna conclusión. Se reporta igual para que la deriva se vea
    llegar y para que quede constancia de cuánto falta.
    """
    if not os.path.exists(ruta):
        return {'aviso': f'No existe {ruta}.'}
    d = pd.read_csv(ruta)
    d = d[d['resultado'].notna()].copy()
    if d.empty:
        return {'aviso': 'Sin picks liquidados todavía.'}
    print(f'\n=== producción: {len(d)} picks liquidados '
          f'({d["fecha"].min()} … {d["fecha"].max()})')
    segs = {
        'deporte': d['deporte'].astype(str),
        'mercado': d['mercado'].astype(str),
        'capa': d['capa'].astype(str),
        'canal': d['canal'].fillna('sin clasificar').astype(str),
        'banda de probabilidad': _bandas(d['prob']).astype(str),
    }
    # con esta muestra el mínimo se baja a 30 —lo mismo que exige
    # `monitor_canales` para enseñar un ROI— y se dice explícitamente que
    # cualquier cosa que salga es indicativa, no concluyente.
    res = analizar(d, 'resultado', 'prob', segs, min_n=30)
    res['aviso'] = ('Muestra pequeña: con menos de unos cientos de picks '
                    'liquidados esto vigila deriva, no autoriza a cambiar el '
                    'modelo.')
    _imprimir(res)
    # resumen general, que sí se puede dar siempre
    res['global'] = {
        'n': int(len(d)),
        'acierto_real': round(float(d['resultado'].mean()), 4),
        'prob_prometida': round(float(pd.to_numeric(d['prob'],
                                                    errors='coerce').mean()), 4),
    }
    res['global']['brecha'] = round(
        res['global']['acierto_real'] - res['global']['prob_prometida'], 4)
    print(f"  GLOBAL · {res['global']['n']} picks · acierto "
          f"{res['global']['acierto_real']:.1%} vs prometido "
          f"{res['global']['prob_prometida']:.1%} · brecha "
          f"{res['global']['brecha']:+.1%}")
    return res


def _imprimir(res: Dict, tope: int = 6) -> None:
    if not res.get('filas'):
        print('  sin segmentos con muestra suficiente '
              f'(mínimo {res.get("min_n", MIN_N)} casos)')
        return
    print(f'  {res["segmentos_examinados"]} segmentos con muestra · '
          f'{res["lecciones"]} lección(es) tras corregir por comparaciones '
          f'múltiples (alfa {res["alfa_por_segmento"]})')
    for f in res['filas'][:tope]:
        marca = '★' if f['leccion'] else ' '
        print(f'   {marca} {f["corte"]:<22} {f["segmento"]:<22} '
              f'n={f["n"]:>6} · real {f["acierto_real"]:.3f} vs prometido '
              f'{f["prob_prometida"]:.3f} · brecha {f["brecha"]:+.3f} '
              f'[{f["ic_bajo"]:+.3f}, {f["ic_alto"]:+.3f}] {f["sentido"]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--historico', action='store_true')
    ap.add_argument('--produccion', action='store_true')
    a = ap.parse_args()
    if not (a.historico or a.produccion):
        a.historico = a.produccion = True

    salida = {}
    if a.historico:
        salida['historico'] = autopsia_historico()
    if a.produccion:
        salida['produccion'] = autopsia_produccion()

    json.dump(salida, open(SALIDA_JSON, 'w'), indent=1, ensure_ascii=False)
    # volcado plano, para poder mirarlo en la app y diffearlo en git
    filas = []
    for fuente, bloques in salida.items():
        if 'filas' in bloques:
            bloques = {'—': bloques}
        for mercado, res in bloques.items():
            for f in res.get('filas', []) if isinstance(res, dict) else []:
                filas.append({'fuente': fuente, 'mercado': mercado, **f})
    if filas:
        from io_atomico import escribir_texto
        escribir_texto(SALIDA_CSV, pd.DataFrame(filas).to_csv(index=False))
    print(f'\n-> {SALIDA_JSON} · {SALIDA_CSV} ({len(filas)} segmentos)')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
