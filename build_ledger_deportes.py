#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v78 — Ledger de predicciones fuera de muestra para TENIS, MLB y NBA.

Por qué
-------
La v75 corrigió la sobreconfianza del modelo encogiendo su probabilidad hacia
el precio sharp, y eso convirtió el ROI del fútbol de −3,8 % a +5,8 %. Pero
`calibracion_mercado.json` está indexado por clave de liga de FÚTBOL, así que
los otros tres deportes siguen sin corregir. Se nota: los picks de MLB salen
con EV de +11 % justo donde el fútbol ya está calibrado.

Para calibrarlos hace falta lo mismo que hizo falta en fútbol: un registro de
qué habría dicho el modelo ANTES de cada partido y a qué cuota cerró. Este
módulo lo construye con la misma receta —walk-forward de origen móvil, sin
filtrar, con el vector completo— y escribe `pick_ledger_deportes.csv`, del que
come `recalibrate_from_history`.

Estado de los datos por deporte (medido 2026-07-28)
--------------------------------------------------
  · **Tenis** — listo. `tenis_fuentes.historico_unificado` ya trae las cuotas
    de tennis-data.co.uk: ATP 72.907 partidos con 91,6 % de cuota, WTA 58.145
    con 77,6 %. No hace falta ninguna fuente nueva.
  · **MLB** — `historico_mlb.csv` (11.928 partidos) NO tiene cuotas. Las aporta
    `backfill_mlb_odds.py` desde los archivos de sportsbookreviewsonline.
  · **NBA** — `historico_nba.csv` (6.140 partidos) tampoco tiene cuotas, y no
    se ha encontrado fuente gratuita completa: sportsbookreviewsonline publica
    las páginas de temporada pero sin fichero descargable, y BetExplorer solo
    sirve los playoffs. Queda documentado en VALIDACION_v78.md.

Uso:
    python build_ledger_deportes.py --deporte tenis
    python build_ledger_deportes.py
"""

import argparse
import datetime as dt
import json
import logging
import os
import sys
import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

SALIDA_CSV = 'pick_ledger_deportes.csv'
SALIDA_META = '_v78_ledger_deportes.json'
INICIO_TRAIN = 0.50
N_FOLDS = 5
MIN_TEST = 200


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


# ---------------------------------------------------------------------------
# TENIS
# ---------------------------------------------------------------------------
def ledger_tenis(circuito: str, n_folds: int = N_FOLDS,
                 inicio: float = INICIO_TRAIN) -> pd.DataFrame:
    """
    Walk-forward de origen móvil sobre el histórico unificado de ese circuito.

    Se reutiliza `TennisEngine._dataset`, que es exactamente el constructor de
    features del modelo desplegado y ya es causal (ELO, forma y H2H se van
    acumulando en orden cronológico). Entrenar con el mismo estimador y el
    mismo escalado que `entrenar()` es lo que hace que el ledger mida el modelo
    real y no un primo suyo.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.preprocessing import StandardScaler
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    from engines.tennis_engine import TennisEngine

    eng = TennisEngine(circuito)
    df = eng.cargar_datos_historicos()
    X, y, fechas, odds, estado = eng._dataset(df, eng.features)
    X = np.asarray(X, dtype=float)
    y = np.asarray(y).astype(int)
    fechas = pd.Series(pd.to_datetime(fechas)).reset_index(drop=True)
    odds = np.asarray(odds, dtype=float)

    n = len(X)
    if n < 2000:
        logger.info(f"[tenis/{circuito}] solo {n} partidos: se omite")
        return pd.DataFrame()
    bordes = np.linspace(int(n * inicio), n, n_folds + 1).astype(int)

    # identidad del partido, para poder cruzar y depurar
    jug1 = df['Player_1'].astype(str).values if 'Player_1' in df.columns else None
    jug2 = df['Player_2'].astype(str).values if 'Player_2' in df.columns else None
    # `_dataset` descarta filas, así que se alinea por longitud desde el final
    if jug1 is not None and len(jug1) != n:
        jug1, jug2 = jug1[-n:], jug2[-n:]

    filas = []
    for k in range(n_folds):
        ini, fin = bordes[k], bordes[k + 1]
        if fin - ini < MIN_TEST:
            continue
        f_corte = fechas.iloc[ini:fin].min()
        idx_tr = np.arange(ini)[fechas.iloc[:ini].values < f_corte]
        idx_te = np.arange(ini, fin)
        if len(idx_tr) < 1000:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            sc = StandardScaler().fit(X[idx_tr])
            vc = VotingClassifier([
                ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                      learning_rate=0.05, verbosity=0)),
                ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                        learning_rate=0.05, verbose=-1)),
                ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                              random_state=42))], voting='soft')
            modelo = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(
                sc.transform(X[idx_tr]), y[idx_tr])
            i1 = list(modelo.classes_).index(1)
            proba = modelo.predict_proba(sc.transform(X[idx_te]))[:, i1]

        for j, i in enumerate(idx_te):
            p1 = float(proba[j])
            filas.append({
                'deporte': 'Tenis', 'liga': circuito.upper(),
                'match_id': (f"{fechas.iloc[i].strftime('%Y%m%d')}_"
                             f"{(jug1[i] if jug1 is not None else '?')}_"
                             f"{(jug2[i] if jug2 is not None else '?')}").replace(' ', '-'),
                'fecha': fechas.iloc[i].strftime('%Y-%m-%d'),
                'pliegue': k,
                'p_home': round(p1, 5), 'p_draw': 0.0,
                'p_away': round(1 - p1, 5),
                'resultado': 0 if y[i] == 1 else 2,     # 0=gana el 1, 2=gana el 2
                'cuota_home': (float(odds[i, 0]) if np.isfinite(odds[i, 0]) else None),
                'cuota_draw': None,
                'cuota_away': (float(odds[i, 1]) if np.isfinite(odds[i, 1]) else None),
                'pin_home': None, 'pin_draw': None, 'pin_away': None,
            })
    out = pd.DataFrame(filas)
    if not out.empty:
        logger.info(f"[tenis/{circuito}] {len(out)} predicciones fuera de muestra "
                    f"({out['fecha'].min()} → {out['fecha'].max()}), "
                    f"{int(out['cuota_home'].notna().sum())} con cuota")
    return out


# ---------------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------------
def ledger_mlb(n_folds: int = N_FOLDS, inicio: float = INICIO_TRAIN) -> pd.DataFrame:
    """
    Walk-forward de origen móvil REAL sobre MLB: se reentrena en cada pliegue.

    v78 — la primera versión de esta función usaba el modelo YA ENTRENADO para
    predecir 2021, y eso es fuga pura: el artefacto desplegado se entrenó con
    2021-2025, así que sus predicciones sobre 2021 son dentro de muestra. El
    modelo habría parecido mejor de lo que es, el sesgo habría salido
    subestimado y `w` demasiado alto — es decir, la calibración habría
    corregido MENOS de lo necesario, que es exactamente el error que esta
    versión venía a arreglar. Un ledger con fuga es peor que no tener ledger.

    Se resolvió ampliando el histórico de Retrosheet a 2015-2025 (24.778
    juegos, antes 11.928) para que haya pasado suficiente ANTES de las
    temporadas con cuota, y reentrenando el estimador en cada pliegue con solo
    lo anterior. Se usa `MLBEngine._dataset`, que es el constructor de features
    de producción y ya es causal.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.preprocessing import StandardScaler
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    from engines.mlb_engine import MLBEngine, codigo_mlb
    import odds_store

    ruta = 'historico_mlb.csv'
    if not os.path.exists(ruta):
        return pd.DataFrame()
    df = pd.read_csv(ruta, low_memory=False)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    con = odds_store.conectar()
    cur = con.execute("SELECT match_id, odds_home, odds_away FROM historical_odds "
                      "WHERE league_key='mlb' AND fase='cierre'")
    cuotas = {m: (h, a) for m, h, a in cur.fetchall()}
    con.close()
    if not cuotas:
        logger.warning('[mlb] sin cuotas históricas: ejecuta backfill_mlb_odds.py')
        return pd.DataFrame()

    X, y, tot, fechas, _estado = MLBEngine._dataset(df)
    X = np.asarray(X, dtype=float)
    y = np.asarray(y).astype(int)
    fechas = pd.Series(pd.to_datetime(fechas)).reset_index(drop=True)

    # v78: la identidad de cada fila la da EL PROPIO `_dataset`.
    #
    # La primera versión la reconstruía replicando aquí su bucle de emisión, y
    # eso salió mal de la peor manera posible: `_dataset` ordena con
    # `sort_values('date')`, cuyo desempate no está garantizado, y con ~15
    # juegos por día bastaba una permutación dentro del mismo día para pegarle
    # a cada predicción la cuota de OTRO partido. No daba ningún error — al
    # contrario, fabricaba un edge espectacular (+37,68 % de ROI, p5 +31,7 %),
    # porque el filtro de EV se quedaba justo con las filas donde la cuota
    # ajena había salido alta por azar.
    #
    # Se detectó con una comprobación que ahora es obligatoria: el log-loss del
    # MERCADO salía 0,7142, peor que una moneda al aire (0,693). Unas cuotas de
    # cierre reales nunca pueden ser peores que el azar; si lo son, están
    # desalineadas. Ver `_verificar_alineacion` más abajo.
    usable = [(f, codigo_mlb(h), codigo_mlb(a))
              for f, h, a in (_estado.get('filas') or [])]
    if len(usable) != len(X):
        logger.warning(f"[mlb] `_dataset` no devolvió identidades alineadas "
                       f"({len(usable)} vs {len(X)}): se omite")
        return pd.DataFrame()

    # Los pliegues se reparten sobre el PERIODO CON CUOTA, no sobre todo el
    # histórico. Con el reparto ingenuo, MLB solo llegaba a los pliegues 0 y 1:
    # el walk-forward recorría 2015-2025 pero las cuotas solo cubren hasta 2021,
    # así que los pliegues 2-4 salían vacíos y la calibración descartaba el
    # deporte entero por «no tiene datos en el pliegue de validación». El
    # entrenamiento sigue usando TODO lo anterior a cada pliegue — solo cambia
    # dónde se colocan los cortes.
    ids = [f"{f.strftime('%Y%m%d')}_{h}_{a}" for f, h, a in usable]
    con_odds = np.array([i for i, m in enumerate(ids)
                         if cuotas.get(m) and cuotas[m][0] and cuotas[m][1]])
    if len(con_odds) < n_folds * MIN_TEST:
        logger.warning(f"[mlb] solo {len(con_odds)} juegos con cuota: se omite")
        return pd.DataFrame()
    logger.info(f"[mlb] {len(con_odds)} juegos con cuota de "
                f"{len(X)} del histórico; pliegues sobre ese periodo")
    bordes_o = np.linspace(int(len(con_odds) * inicio), len(con_odds),
                           n_folds + 1).astype(int)
    filas = []
    for k in range(n_folds):
        sel = con_odds[bordes_o[k]:bordes_o[k + 1]]
        if len(sel) < MIN_TEST:
            continue
        ini, fin = int(sel[0]), int(sel[-1]) + 1
        f_corte = fechas.iloc[ini:fin].min()
        idx_tr = np.arange(ini)[fechas.iloc[:ini].values < f_corte]
        if len(idx_tr) < 2000:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            sc = StandardScaler().fit(X[idx_tr])
            vc = VotingClassifier([
                ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                      learning_rate=0.05, verbosity=0)),
                ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                        learning_rate=0.05, verbose=-1)),
                ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                              random_state=42))], voting='soft')
            modelo = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(
                sc.transform(X[idx_tr]), y[idx_tr])
            i1 = list(modelo.classes_).index(1)
            proba = modelo.predict_proba(sc.transform(X[ini:fin]))[:, i1]

        for j, i in enumerate(range(ini, fin)):
            fecha, ch, ca = usable[i]
            mid = f"{fecha.strftime('%Y%m%d')}_{ch}_{ca}"
            c = cuotas.get(mid)
            if not c or not (c[0] and c[1]):
                continue
            ph = float(proba[j])
            filas.append({
                'deporte': 'MLB', 'liga': 'mlb', 'match_id': mid,
                'fecha': fecha.strftime('%Y-%m-%d'), 'pliegue': k,
                'p_home': round(ph, 5), 'p_draw': 0.0, 'p_away': round(1 - ph, 5),
                'resultado': 0 if y[i] == 1 else 2,
                'cuota_home': c[0], 'cuota_draw': None, 'cuota_away': c[1],
                'pin_home': None, 'pin_draw': None, 'pin_away': None,
            })
    out = pd.DataFrame(filas)
    if not out.empty:
        logger.info(f"[mlb] {len(out)} predicciones fuera de muestra con cuota "
                    f"({out['fecha'].min()} → {out['fecha'].max()})")
    return out


def verificar_alineacion(d: pd.DataFrame, etiqueta: str) -> dict:
    """
    Guardia contra el desalineado entre predicción y cuota.

    Es la comprobación que destapó el fallo de la v78: si las cuotas están
    pegadas al partido equivocado, **el log-loss del MERCADO sale peor que una
    moneda al aire**. Y eso es imposible: unas cuotas de cierre reales, por
    malas que sean, siempre baten al azar. Si el mercado no supera ln(2)=0,693
    en un mercado de dos vías (o ln(3)=1,099 en uno de tres), los datos están
    mal cruzados y NO se debe calibrar con ellos.

    El fallo no daba error ni parecía un fallo: fabricaba un ROI de +37,68 %
    con bootstrap p5 de +31,7 %, es decir, exactamente lo que uno querría ver.
    Por eso la comprobación es automática y bloqueante, no un chequeo manual.
    """
    import numpy as np
    # Hacen falta AMBAS cuotas: con una sola, el devig da NaN y el log-loss
    # sale NaN, que la comparación trata como "peor que el azar" y tumbaría un
    # ledger perfectamente válido (le pasó a WTA, que tenía 15.885 filas con
    # `cuota_home` pero no todas con `cuota_away`).
    sub = d.dropna(subset=['cuota_home', 'cuota_away']).copy()
    if len(sub) < 200:
        return {'ok': True, 'motivo': 'muestra corta, no se juzga'}
    dos_vias = sub['cuota_draw'].isna()
    imp = np.zeros((len(sub), 3))
    ch = sub['cuota_home'].values.astype(float)
    ca = sub['cuota_away'].values.astype(float)
    cd = sub['cuota_draw'].fillna(0).values.astype(float)
    inv = np.column_stack([1 / np.clip(ch, 1.0001, None),
                           np.where(dos_vias, 0.0, 1 / np.clip(cd, 1.0001, None)),
                           1 / np.clip(ca, 1.0001, None)])
    imp = inv / inv.sum(axis=1, keepdims=True)
    y = sub['resultado'].values.astype(int)
    ll_mkt = float(-np.log(np.clip(imp[np.arange(len(sub)), y], 1e-9, None)).mean())
    techo = float(np.log(2)) if bool(dos_vias.all()) else float(np.log(3))
    if not np.isfinite(ll_mkt):
        return {'ok': False, 'n': int(len(sub)), 'logloss_mercado': None,
                'techo_azar': round(techo, 4),
                'motivo': 'log-loss no finito: hay cuotas nulas o corruptas'}
    ok = ll_mkt < techo
    info = {'ok': ok, 'n': int(len(sub)), 'logloss_mercado': round(ll_mkt, 4),
            'techo_azar': round(techo, 4),
            'motivo': ('ok' if ok else
                       'el log-loss del mercado supera al azar: las cuotas NO '
                       'corresponden a estas predicciones')}
    if not ok:
        logger.error(f"[{etiqueta}] ALINEACIÓN ROTA: log-loss del mercado "
                     f"{ll_mkt:.4f} > azar {techo:.4f}. No se usa este ledger.")
    else:
        logger.info(f"[{etiqueta}] alineación OK (log-loss del mercado "
                    f"{ll_mkt:.4f} < azar {techo:.4f})")
    return info


def construir(deporte: Optional[str] = None) -> pd.DataFrame:
    partes = []
    if deporte in (None, 'tenis'):
        for c in ('atp', 'wta'):
            try:
                d = ledger_tenis(c)
                if not d.empty:
                    partes.append(d)
            except Exception as e:
                logger.warning(f"[tenis/{c}] {type(e).__name__}: {e}")
    if deporte in (None, 'mlb'):
        try:
            d = ledger_mlb()
            if not d.empty:
                partes.append(d)
        except Exception as e:
            logger.warning(f"[mlb] {type(e).__name__}: {e}")
    if not partes:
        raise RuntimeError('ningún deporte produjo ledger')
    # guardia obligatoria: un ledger desalineado es peor que ninguno
    verificaciones = {}
    validas = []
    for d in partes:
        et = f"{d['deporte'].iat[0]}/{d['liga'].iat[0]}"
        v = verificar_alineacion(d, et)
        verificaciones[et] = v
        if v['ok']:
            validas.append(d)
    if not validas:
        raise RuntimeError('ningún ledger pasó la verificación de alineación')
    out = pd.concat(validas, ignore_index=True)
    out.to_csv(SALIDA_CSV, index=False)
    meta = {'generado': _ahora(), 'filas': int(len(out)),
            'por_deporte': {k: int(v) for k, v in out['deporte'].value_counts().items()},
            'por_liga': {k: int(v) for k, v in out['liga'].value_counts().items()},
            'con_cuota': int(out['cuota_home'].notna().sum()),
            'rango': [out['fecha'].min(), out['fecha'].max()],
            'verificacion_alineacion': verificaciones}
    with open(SALIDA_META, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    logger.info(f"✅ {len(out)} predicciones fuera de muestra "
                f"({meta['con_cuota']} con cuota) en {SALIDA_CSV}")
    return out


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--deporte', choices=['tenis', 'mlb'])
    a = ap.parse_args()
    d = construir(a.deporte)
    print(f"\n{len(d)} filas · {d['deporte'].value_counts().to_dict()}")
    print(f"con cuota: {int(d['cuota_home'].notna().sum())}")
