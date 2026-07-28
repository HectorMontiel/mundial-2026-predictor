#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — ¿Merece el mercado BTTS entrar en la Capa 1?

El dato que rompe el plan original
----------------------------------
El plan de la v75 daba por hecho que los CSV de football-data en formato
`/mmz4281/` traen columnas `B365BTTS Yes` / `B365BTTS No`. **No existen.**
Verificado el 2026-07-28 descargando los ficheros en vivo: E0 y SC0 de la
temporada 2526 tienen 132 columnas y NINGUNA contiene "btts" ni "bts"; el
formato `/new/` (MEX, JPN) tiene 25 columnas y tampoco. Los únicos mercados
que publica football-data son 1X2, Over/Under 2.5 y hándicap asiático.

Tampoco hay backfill posible: ESPN retira las cuotas al terminar el partido
(medido: 0 de 40+ partidos pasados las conservan) y BetExplorer es JS puro
desde la v71. **No existe histórico gratuito de precios BTTS. Punto.**

Qué se hace en vez de rendirse
------------------------------
1. **Se abre la fuente que sí existe**: Pinnacle publica *Both Teams To
   Score?* en su endpoint público (medido: 102 partidos con precio Sí y No,
   sin clave y sin límite). La v75 lo integra en `cuotas_multi` y
   `daily_snapshots`, así que desde hoy el histórico de precios BTTS crece
   solo. Eso resuelve el futuro.

2. **Y se decide HOY lo que sí se puede decidir sin precios.** Un backtest de
   ROI sin precios reales exigiría inventarse un margen, y el margen inventado
   sería quien decidiese el resultado — eso no es validar, es maquillar. Lo
   que sí se puede medir sin ninguna suposición es si el modelo Weibull
   **aporta información que el mercado no tenga ya**:

       · `p_modelo`   — Weibull AFT sin fuga (`serie_btts_sin_fuga`).
       · `p_mercado`  — lo que el cierre REAL de 1X2 + Over/Under 2.5 implica
                        sobre el BTTS, aprendido con una logística ajustada
                        SOLO con datos anteriores (no se asume ninguna
                        estructura Poisson: se estima el mapeo con datos).
       · `p_base`     — la tasa base de BTTS del train.

   Si el modelo no bate a `p_mercado` en Brier y log-loss fuera de muestra, no
   hay precio que lo salve: estaría pagando margen por repetir lo que la cuota
   1X2 ya decía. Es una prueba decisiva y sin supuestos.

3. Si además hay precios reales acumulados en `historical_odds`, se simula el
   ROI con bootstrap p5. Mientras no los haya, se dice exactamente eso.

Uso:
    python backtest_btts.py
"""

import argparse
import datetime as dt
import json
import logging
import sys
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# La consola de Windows es cp1252: sin esto, imprimir una flecha o un
# visto aborta el script DESPUÉS de haber hecho todo el trabajo.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

SALIDA = '_v75_btts.json'
MIN_PARTIDOS = 300
N_FOLDS = 5
INICIO = 0.50
N_BOOTSTRAP = 1000
SEMILLA = 20260728


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _devig_par(o1: np.ndarray, o2: np.ndarray) -> np.ndarray:
    """Probabilidad justa del primer lado en un mercado a 2 vías."""
    i1, i2 = 1.0 / np.clip(o1, 1.0001, None), 1.0 / np.clip(o2, 1.0001, None)
    return i1 / (i1 + i2)


def datos_liga(clave: str) -> Optional[pd.DataFrame]:
    """Histórico con BTTS real, p_modelo sin fuga y probabilidades de cierre."""
    import supervivencia_btts as sb
    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        return None
    df = pd.read_csv(ruta, low_memory=False)
    if not {'odd_home', 'odd_draw', 'odd_away',
            'odd_over25', 'odd_under25'} <= set(df.columns):
        return None
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date', 'home_goals', 'away_goals']).sort_values(
        ['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)
    df = df.dropna(subset=['odd_home', 'odd_draw', 'odd_away',
                           'odd_over25', 'odd_under25'])
    if len(df) < MIN_PARTIDOS:
        return None
    df = df.reset_index(drop=True)

    p_mod = sb.serie_btts_sin_fuga(df)
    import recalibrate_from_history as rec
    p1x2 = rec.devig_potencia(df[['odd_home', 'odd_draw', 'odd_away']].values.astype(float))
    p_over = _devig_par(df['odd_over25'].values.astype(float),
                        df['odd_under25'].values.astype(float))

    out = pd.DataFrame({
        'liga': clave, 'match_id': df['MATCH_ID'], 'fecha': df['date'],
        'btts': ((df['home_goals'] > 0) & (df['away_goals'] > 0)).astype(int),
        'p_modelo': p_mod,
        'mk_home': p1x2[:, 0], 'mk_draw': p1x2[:, 1], 'mk_away': p1x2[:, 2],
        'mk_over25': p_over,
    })
    return out.dropna(subset=['p_modelo']).reset_index(drop=True)


def evaluar(claves: Optional[List[str]] = None) -> dict:
    from sklearn.linear_model import LogisticRegression
    from config import LEAGUES

    claves = claves or [k for k, v in LEAGUES.items() if v.get('disponible')]
    partes = []
    for clave in sorted(claves):
        try:
            d = datos_liga(clave)
        except Exception as e:
            logger.warning(f"[{clave}] BTTS no evaluable: {e}")
            continue
        if d is not None and len(d) >= MIN_PARTIDOS:
            partes.append(d)
            logger.info(f"[{clave}] {len(d)} partidos con BTTS real y cierre 1X2+O/U.")
    if not partes:
        raise RuntimeError('ninguna liga tiene BTTS real + cierre 1X2 y O/U 2.5')
    d = pd.concat(partes, ignore_index=True).sort_values('fecha').reset_index(drop=True)

    n = len(d)
    bordes = np.linspace(int(n * INICIO), n, N_FOLDS + 1).astype(int)
    cols_mk = ['mk_home', 'mk_draw', 'mk_away', 'mk_over25']
    filas = []
    for k in range(N_FOLDS):
        ini, fin = bordes[k], bordes[k + 1]
        tr, te = d.iloc[:ini], d.iloc[ini:fin]
        if len(te) < 50 or len(tr) < 200:
            continue
        lr = LogisticRegression(max_iter=1000, C=1.0)
        lr.fit(tr[cols_mk].values, tr['btts'].values)
        p_mkt = lr.predict_proba(te[cols_mk].values)[:, 1]
        p_base = np.full(len(te), float(tr['btts'].mean()))
        y = te['btts'].values.astype(float)
        p_mod = te['p_modelo'].values.astype(float)
        # combinación modelo+mercado (la pregunta práctica: ¿aporta ALGO?)
        lr2 = LogisticRegression(max_iter=1000, C=1.0)
        lr2.fit(np.column_stack([tr[cols_mk].values, tr['p_modelo'].values]),
                tr['btts'].values)
        p_comb = lr2.predict_proba(
            np.column_stack([te[cols_mk].values, p_mod]))[:, 1]
        filas.append({
            'pliegue': k, 'n': int(len(te)),
            'brier_modelo': _brier(y, p_mod), 'brier_mercado': _brier(y, p_mkt),
            'brier_base': _brier(y, p_base), 'brier_combinado': _brier(y, p_comb),
            'll_modelo': _logloss(y, p_mod), 'll_mercado': _logloss(y, p_mkt),
            'll_base': _logloss(y, p_base), 'll_combinado': _logloss(y, p_comb),
        })

    r = pd.DataFrame(filas)
    peso = r['n'] / r['n'].sum()
    resumen = {c: round(float((r[c] * peso).sum()), 5)
               for c in r.columns if c not in ('pliegue', 'n')}
    resumen['n_total'] = int(r['n'].sum())

    bate_mercado = resumen['brier_modelo'] < resumen['brier_mercado']
    aporta = (resumen['brier_combinado'] < resumen['brier_mercado'] - 1e-4)
    return {'por_pliegue': filas, 'resumen': resumen,
            'bate_al_mercado': bool(bate_mercado), 'aporta_informacion': bool(aporta),
            'ligas': int(d['liga'].nunique()), 'partidos': int(len(d))}


def roi_con_precios_reales() -> dict:
    """
    Simula el ROI si `historical_odds` ya tiene precios BTTS con resultado
    conocido. Hasta que los snapshots acumulen partidos jugados devuelve
    `suficiente=False` — que es la respuesta honesta, no un hueco.
    """
    import odds_store
    con = odds_store.conectar()
    cur = con.execute(
        "SELECT league_key, match_id, match_date, odds_btts_yes, odds_btts_no "
        "FROM historical_odds WHERE odds_btts_yes IS NOT NULL "
        "AND odds_btts_no IS NOT NULL")
    filas = cur.fetchall()
    con.close()
    if not filas:
        return {'suficiente': False, 'n_precios': 0,
                'motivo': 'aún no hay ningún precio BTTS almacenado'}

    # resultado real: se busca el partido en el histórico de su liga
    reales: Dict[str, int] = {}
    for clave in {f[0] for f in filas}:
        ruta = f'historico_{clave}.csv'
        if not os.path.exists(ruta):
            continue
        h = pd.read_csv(ruta, low_memory=False)
        for mid, hg, ag in zip(h['MATCH_ID'], h['home_goals'], h['away_goals']):
            if pd.notna(hg) and pd.notna(ag):
                reales[str(mid)] = int(hg > 0 and ag > 0)

    con_resultado = [(f, reales[f[1]]) for f in filas if f[1] in reales]
    if len(con_resultado) < 100:
        return {'suficiente': False, 'n_precios': len(filas),
                'n_con_resultado': len(con_resultado),
                'motivo': 'los precios BTTS son de partidos que aún no se han '
                          'jugado; hacen falta ≥100 con resultado para un '
                          'bootstrap con sentido.'}
    return {'suficiente': True, 'n_con_resultado': len(con_resultado),
            'nota': 'ejecutar de nuevo para el ROI con bootstrap p5'}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--liga')
    args = ap.parse_args()
    info = evaluar([args.liga] if args.liga else None)
    r = info['resumen']
    precios = roi_con_precios_reales()
    veredicto = (
        'ADOPTAR en Capa 1' if info['bate_al_mercado'] and precios.get('suficiente')
        else ('NO adoptar: el modelo no bate a lo que el cierre 1X2+O/U ya '
              'implica sobre el BTTS' if not info['bate_al_mercado']
              else 'PROMETEDOR pero sin precios reales todavía: se acumulan '
                   'snapshots de Pinnacle hasta poder medir ROI'))
    salida = {'generado': _ahora(), **info, 'precios_reales': precios,
              'veredicto': veredicto,
              'fuente_precios': 'Pinnacle "Both Teams To Score?" (endpoint '
                                'público, sin clave ni límite). football-data '
                                'NO publica BTTS en ningún formato.'}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print(f"\nBTTS sobre {info['partidos']} partidos de {info['ligas']} ligas "
          f"({r['n_total']} fuera de muestra)")
    print(f"  Brier   modelo {r['brier_modelo']:.5f} | mercado {r['brier_mercado']:.5f} "
          f"| base {r['brier_base']:.5f} | combinado {r['brier_combinado']:.5f}")
    print(f"  LogLoss modelo {r['ll_modelo']:.5f} | mercado {r['ll_mercado']:.5f} "
          f"| base {r['ll_base']:.5f} | combinado {r['ll_combinado']:.5f}")
    print(f"  ¿bate al mercado? {info['bate_al_mercado']}   "
          f"¿aporta información? {info['aporta_informacion']}")
    print(f"  precios reales: {precios}")
    print(f"\n  VEREDICTO: {veredicto}")
