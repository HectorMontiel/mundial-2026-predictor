#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shadow Booster — predicción del RESIDUO del mercado (v26, spec §1.1).

## Idea
El mercado no publica probabilidades: publica precios que equilibran su
riesgo. Un XGBRegressor aprende el error sistemático del cierre:

    residuo = 1{gana el local} − p_home_mercado      (de-vig proporcional)

con cierre de PINNACLE si existe (odd_*_pin, v26) y si no B365/Avg.

## Sin fuga (spec §3.2)
Las probabilidades del modelo base que alimentan al Shadow son OUT-OF-FOLD:
en cada ventana walk-forward, el base se entrena SOLO con partidos
anteriores y predice la ventana; esas predicciones se acumulan en
predicciones_oof.csv y el Shadow de la ventana k se entrena únicamente con
ventanas < k. El árbitro entra como severidad ROLLING (media de tarjetas de
sus partidos ANTERIORES, spec §1.5) y solo en el Shadow, no en el base.

## Señal y validación
    señal = +1 (apostar local) si residuo_pred > umbral (0.05)
            −1 (apostar visitante) si residuo_pred < −umbral
ROI simulado con el cierre real de la señal vs ROI de apostar a ciegas el
pick del base en los MISMOS partidos. Adopción solo si ROI_shadow supera al
base en > +1 pp (spec §1.1.5) de forma consistente.

Uso: python shadow_booster.py [liga ...]     # sin args: ligas con cuotas
"""

import json
import logging
import os
import sys
import warnings

warnings.filterwarnings('ignore')

from typing import Dict

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
import features_v26 as f26
import league_engine
import momentum_tactico as mt
from config import LEAGUES
from train_tda_model import construir_ensemble, calcular_features_topologicas

logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_shadow_v27.json'   # v26 en resultados_shadow_v26.json
OOF_CSV = 'predicciones_oof.csv'
UMBRAL_SENAL = 0.05
MIN_TRAIN_SHADOW = 300
# v27: el CASTIGO_NARRATIVO ayudó en LaLiga (+5.1→+7.3 %) y Ligue 1
# (−9.3→−0.2 %) pero EMPEORÓ la MLS (+2.6→−2.0 vs su variante v26 sin CN):
# la feature es configurable por liga y cada artefacto guarda su variante.
CN_LIGAS = {'laliga', 'ligue_1'}
LIGAS_DEF = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1',
             'eredivisie', 'primeira', 'liga_mx', 'mls']


def _severidad_arbitral(df: pd.DataFrame) -> pd.Series:
    """Severidad ROLLING del árbitro (amarillas + 2·rojas de SUS partidos
    anteriores; sin árbitro o sin historial → media global previa)."""
    if 'referee' not in df.columns:
        return pd.Series(0.0, index=df.index)
    tot = {}
    n = {}
    global_tot, global_n = 0.0, 0
    out = np.zeros(len(df))
    for i, r in enumerate(df.itertuples(index=False)):
        arb = getattr(r, 'referee', None)
        if arb and not pd.isna(arb) and n.get(arb, 0) >= 3:
            out[i] = tot[arb] / n[arb]
        elif global_n >= 50:
            out[i] = global_tot / global_n
        am = (getattr(r, 'home_yellow', np.nan), getattr(r, 'away_yellow', np.nan))
        rj = (getattr(r, 'home_red', np.nan), getattr(r, 'away_red', np.nan))
        if not any(pd.isna(x) for x in am + rj):
            sev = am[0] + am[1] + 2 * (rj[0] + rj[1])
            global_tot += sev
            global_n += 1
            if arb and not pd.isna(arb):
                tot[arb] = tot.get(arb, 0.0) + sev
                n[arb] = n.get(arb, 0) + 1
    # normalizar a ~[0, 1.5] (media típica ~4.5 tarjetas)
    return pd.Series(out / 6.0, index=df.index)


def _probs_mercado(df: pd.DataFrame) -> pd.DataFrame:
    """p implícitas de-vig (Pinnacle preferido; respaldo cuotas estándar)."""
    def _devig(oh, od, oa):
        with np.errstate(divide='ignore', invalid='ignore'):
            inv = np.column_stack([1.0 / oh, 1.0 / od, 1.0 / oa])
        s = inv.sum(axis=1)
        return inv / s[:, None]
    fuente = np.where(df.get('odd_home_pin', pd.Series(np.nan, index=df.index)).notna(),
                      'pinnacle', 'estandar')
    oh = df.get('odd_home_pin', pd.Series(np.nan, index=df.index)) \
        .fillna(df['odd_home']).values.astype(float)
    od = df.get('odd_draw_pin', pd.Series(np.nan, index=df.index)) \
        .fillna(df['odd_draw']).values.astype(float)
    oa = df.get('odd_away_pin', pd.Series(np.nan, index=df.index)) \
        .fillna(df['odd_away']).values.astype(float)
    p = _devig(oh, od, oa)
    return pd.DataFrame({'p_mkt_h': p[:, 0], 'p_mkt_d': p[:, 1],
                         'p_mkt_a': p[:, 2], 'fuente_mkt': fuente,
                         'odd_h': oh, 'odd_d': od, 'odd_a': oa},
                        index=df.index)


def _dataset(clave: str):
    """Descarga FRESCA (para traer referee + Pinnacle v26) + features."""
    df = league_engine.descargar_liga(clave)
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    ids = [m[3] for m in ds['meta']]
    grupos = LEAGUES[clave].get('features_extra', [])
    # las columnas v26 se añaden aparte (todas): quitarlas del bloque base
    cols_base = [c for c in league_engine.columnas_extra(clave)
                 if c not in f26.COLS_V26]
    if cols_base:
        extras_df, _ = league_engine.features_extra_liga(df)
        if 'mx' in grupos:
            extras_df = extras_df.join(league_engine.features_mx(df))
        if 'imt' in grupos or 'imt_c' in grupos:
            imt_df, _ = mt.features_imt(df)
            if 'imt_c' in grupos:
                coef = mt.optimizar_coeficientes(
                    df, imt_df, hasta_fecha=df['date'].quantile(0.60))['coef']
                imt_df = imt_df.join(mt.indice_compuesto(imt_df, coef))
            extras_df = extras_df.join(imt_df)
        ext = extras_df.reindex(ids).reset_index(drop=True)
        for c in cols_base:
            X_df[c] = ext[c].values
    v26_df, _ = f26.features_v26(df)
    ext26 = v26_df.reindex(ids).reset_index(drop=True)
    for c in f26.COLS_V26:
        X_df[c] = ext26[c].values

    df_idx = df.set_index('MATCH_ID').reindex(ids)
    mkt = _probs_mercado(df_idx).reset_index(drop=True)
    sev = _severidad_arbitral(df).rename('SEVERIDAD')
    sev = sev.to_frame().set_index(df['MATCH_ID']).reindex(ids).reset_index(drop=True)
    topo = calcular_features_topologicas(ds)
    return X_df, ds['y'], ds['fechas'], topo, mkt, sev['SEVERIDAD'], cols_base


def _modelo_base(clave):
    if LEAGUES[clave].get('calibracion') == 'beta':
        return league_engine.ModeloBetaCalibrado()
    return construir_ensemble()


def wf_liga(clave: str, oof_acum: list) -> dict:
    from xgboost import XGBRegressor
    X_df, y, fechas, topo, mkt, sev, cols_base = _dataset(clave)
    y = np.asarray(y)
    # el Shadow ve las features base + TODAS las ortogonales v26 (spec §1.1)
    cols = list(fe.FEATURES_MODELO) + cols_base + f26.COLS_V26
    con_mkt = np.isfinite(mkt[['p_mkt_h', 'p_mkt_d', 'p_mkt_a']].values).all(axis=1)

    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')

    # dataset acumulado del Shadow (solo ventanas ANTERIORES a la actual)
    S_X, S_y = [], []
    filas = []
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values & con_mkt
        if m_va.sum() < 60 or m_tr.sum() < 250:
            continue
        Xv = X_df[cols].copy()
        for c in cols:
            if c in league_engine.COLS_CUOTAS:
                Xv[c] = Xv[c].fillna(float(pd.to_numeric(
                    Xv.loc[m_tr, c], errors='coerce').mean()))
            else:
                Xv[c] = Xv[c].fillna(0.0)
        X_tr_n, X_va_n, _ = fe.normalizar_features(Xv[m_tr], Xv[m_va])
        base = _modelo_base(clave)
        base.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        pr = base.predict_proba(np.hstack([X_va_n, topo[m_va]]))
        p_oof = np.zeros((int(m_va.sum()), 3))
        for k_idx, k in enumerate(base.classes_):
            p_oof[:, int(k)] = pr[:, k_idx]
        p_oof /= p_oof.sum(axis=1, keepdims=True)

        idx_va = np.where(m_va)[0]
        y_va = y[idx_va]
        mkt_va = mkt.iloc[idx_va]
        # registro OOF global (spec §3.2)
        for j, i in enumerate(idx_va):
            oof_acum.append({'liga': clave, 'fecha': str(fechas.iloc[i].date()),
                             'p_home': round(float(p_oof[j, 0]), 4),
                             'p_draw': round(float(p_oof[j, 1]), 4),
                             'p_away': round(float(p_oof[j, 2]), 4),
                             'resultado': int(y_va[j])})

        # features del Shadow para ESTA ventana (con y sin severidad)
        # v27 (§3.2): CASTIGO_NARRATIVO — cruce de la velocidad del ELO con
        # la entropía de resultados (adaptado a diffs local−visitante:
        # CN = ELO_VEL_DIFF · (1 − (ENTROPIA_DIFF+1)/2)). El RLM exige
        # histórico de snapshots que apenas empieza a acumularse
        # (odds_historico.db, v25) → forward-only, documentado.
        cn = (Xv.iloc[idx_va]['ELO_VEL_DIFF'].values
              * (1 - (Xv.iloc[idx_va]['ENTROPIA_DIFF'].values + 1) / 2))
        extras_shadow = np.column_stack([
            p_oof,
            mkt_va[['p_mkt_h', 'p_mkt_d', 'p_mkt_a']].values,
            cn.reshape(-1, 1),
            sev.iloc[idx_va].values.reshape(-1, 1),
        ])
        Xs_va = np.hstack([Xv.iloc[idx_va].values, extras_shadow])
        resid_va = (y_va == 0).astype(float) - mkt_va['p_mkt_h'].values

        fila = {'ventana': str(inicio.date()), 'n': int(m_va.sum())}
        # ROI del BASE (apostar a ciegas el pick del base con el cierre)
        cuotas_va = mkt_va[['odd_h', 'odd_d', 'odd_a']].values
        pick_b = p_oof.argmax(axis=1)
        cb = cuotas_va[np.arange(len(pick_b)), pick_b]
        gan_b = np.where(pick_b == y_va, cb - 1.0, -1.0)
        fila['roi_base'] = round(100 * float(gan_b.mean()), 2)
        fila['n_bets_base'] = int(len(gan_b))

        if len(S_X) and sum(len(b) for b in S_X) >= MIN_TRAIN_SHADOW:
            Xs_tr = np.vstack(S_X)
            ys_tr = np.concatenate(S_y)
            for etiqueta, quitar_sev in (('shadow', False), ('shadow_sin_sev', True)):
                Xt, Xp = Xs_tr, Xs_va
                if quitar_sev:
                    Xt, Xp = Xs_tr[:, :-1], Xs_va[:, :-1]
                reg = XGBRegressor(n_estimators=250, max_depth=4,
                                   learning_rate=0.05, subsample=0.9,
                                   colsample_bytree=0.9, random_state=42,
                                   verbosity=0)
                reg.fit(Xt, ys_tr)
                pred = reg.predict(Xp)
                senal = np.where(pred > UMBRAL_SENAL, 0,
                                 np.where(pred < -UMBRAL_SENAL, 2, -1))
                juega = senal >= 0
                if juega.sum() >= 5:
                    c = cuotas_va[np.arange(len(senal)), np.clip(senal, 0, 2)]
                    gan = np.where(senal == y_va, c - 1.0, -1.0)[juega]
                    fila[f'roi_{etiqueta}'] = round(100 * float(gan.mean()), 2)
                    fila[f'n_bets_{etiqueta}'] = int(juega.sum())
                    fila[f'aciertos_{etiqueta}'] = int((senal == y_va)[juega].sum())
        filas.append(fila)
        logger.info(f"  [{clave}] {inicio.date()} n={fila['n']} "
                    f"roi_base {fila['roi_base']}% · "
                    f"shadow {fila.get('roi_shadow', 'aun sin datos')}% "
                    f"({fila.get('n_bets_shadow', 0)} bets)")
        # acumular ESTA ventana para entrenar el Shadow de las siguientes
        S_X.append(Xs_va)
        S_y.append(resid_va)

    con_sh = [f for f in filas if 'roi_shadow' in f]
    if not con_sh:
        return {'ventanas': filas, 'veredicto': 'sin datos suficientes'}

    def _roi_pond(clave_roi, clave_n):
        n = sum(f[clave_n] for f in con_sh)
        tot = sum(f[clave_roi] * f[clave_n] for f in con_sh)
        return round(tot / n, 2) if n else None, n

    roi_b, n_b = _roi_pond('roi_base', 'n_bets_base')
    roi_s, n_s = _roi_pond('roi_shadow', 'n_bets_shadow')
    roi_ss, n_ss = _roi_pond('roi_shadow_sin_sev', 'n_bets_shadow_sin_sev')
    adoptar = bool(roi_s is not None and roi_b is not None
                   and roi_s - roi_b > 1.0 and n_s >= 30)
    salida = {'ventanas': filas,
              'roi_base_pct': roi_b, 'n_bets_base': n_b,
              'roi_shadow_pct': roi_s, 'n_bets_shadow': n_s,
              'roi_shadow_sin_severidad_pct': roi_ss,
              'n_bets_shadow_sin_severidad': n_ss,
              'umbral': UMBRAL_SENAL, 'adoptar': adoptar}
    logger.info(f"[{clave}] ROI base {roi_b}% ({n_b} bets) vs shadow {roi_s}% "
                f"({n_s} bets; sin severidad {roi_ss}%) → "
                f"{'ADOPTAR' if adoptar else 'descartado'}")
    return salida


def entrenar_produccion(clave: str) -> bool:
    """Entrena el Shadow de PRODUCCIÓN con todo el histórico (dataset OOF
    construido por el mismo protocolo del walk-forward) y lo persiste en
    modelos/{clave}/shadow.joblib. Solo para ligas ADOPTADAS."""
    import joblib
    from xgboost import XGBRegressor
    X_df, y, fechas, topo, mkt, sev, cols_base = _dataset(clave)
    y = np.asarray(y)
    cols = list(fe.FEATURES_MODELO) + cols_base + f26.COLS_V26
    con_mkt = np.isfinite(mkt[['p_mkt_h', 'p_mkt_d', 'p_mkt_a']].values).all(axis=1)
    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')
    S_X, S_y = [], []
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values & con_mkt
        if m_va.sum() < 60 or m_tr.sum() < 250:
            continue
        Xv = X_df[cols].copy()
        for c in cols:
            if c in league_engine.COLS_CUOTAS:
                Xv[c] = Xv[c].fillna(float(pd.to_numeric(
                    Xv.loc[m_tr, c], errors='coerce').mean()))
            else:
                Xv[c] = Xv[c].fillna(0.0)
        X_tr_n, X_va_n, _ = fe.normalizar_features(Xv[m_tr], Xv[m_va])
        base = _modelo_base(clave)
        base.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        pr = base.predict_proba(np.hstack([X_va_n, topo[m_va]]))
        p_oof = np.zeros((int(m_va.sum()), 3))
        for k_idx, k in enumerate(base.classes_):
            p_oof[:, int(k)] = pr[:, k_idx]
        p_oof /= p_oof.sum(axis=1, keepdims=True)
        idx_va = np.where(m_va)[0]
        con_cn = clave in CN_LIGAS
        bloques = [p_oof,
                   mkt.iloc[idx_va][['p_mkt_h', 'p_mkt_d', 'p_mkt_a']].values]
        if con_cn:
            cn = (Xv.iloc[idx_va]['ELO_VEL_DIFF'].values
                  * (1 - (Xv.iloc[idx_va]['ENTROPIA_DIFF'].values + 1) / 2))
            bloques.append(cn.reshape(-1, 1))
        bloques.append(sev.iloc[idx_va].values.reshape(-1, 1))
        extras_shadow = np.column_stack(bloques)
        S_X.append(np.hstack([Xv.iloc[idx_va].values, extras_shadow]))
        S_y.append((y[idx_va] == 0).astype(float)
                   - mkt.iloc[idx_va]['p_mkt_h'].values)
    if not S_X or sum(len(b) for b in S_X) < MIN_TRAIN_SHADOW:
        logger.warning(f"[{clave}] shadow producción: datos insuficientes.")
        return False
    reg = XGBRegressor(n_estimators=250, max_depth=4, learning_rate=0.05,
                       subsample=0.9, colsample_bytree=0.9, random_state=42,
                       verbosity=0)
    reg.fit(np.vstack(S_X), np.concatenate(S_y))
    joblib.dump({'modelo': reg, 'cols': cols, 'umbral': UMBRAL_SENAL,
                 'con_cn': clave in CN_LIGAS,
                 'sev_media': round(float(sev.mean()), 4)},
                os.path.join('modelos', clave, 'shadow.joblib'), compress=3)
    logger.info(f"[{clave}] shadow de producción → modelos/{clave}/shadow.joblib "
                f"({sum(len(b) for b in S_X)} obs OOF)")
    return True


def generar_senales(claves=None) -> Dict:
    """Señales ⚡ para los partidos FUTUROS con cuotas vigentes →
    shadow_senales.json (lo consume alpha_finder). Aproximación documentada:
    la prob base en vivo es la del modelo de producción (en el arnés era
    OOF pura); el resto de features es idéntico."""
    import joblib
    from league_engine import ClubEngine
    claves = claves or [c for c in LIGAS_DEF
                        if os.path.exists(os.path.join('modelos', c, 'shadow.joblib'))]
    try:
        with open('odds_actuales.json', encoding='utf-8') as f:
            cuotas = json.load(f).get('cuotas', {})
    except Exception:
        cuotas = {}
    senales = {}
    for clave in claves:
        ruta = os.path.join('modelos', clave, 'shadow.joblib')
        if not os.path.exists(ruta):
            continue
        art = joblib.load(ruta)
        eng = ClubEngine(clave)
        if not eng.listo:
            continue
        hoy = pd.Timestamp.today().normalize()
        for mid, o in cuotas.items():
            partes = mid.split('_')
            if len(partes) != 3 or not o.get('odd_home'):
                continue
            try:
                fecha = pd.Timestamp(partes[0])
            except ValueError:
                continue
            home = partes[1].replace('-', ' ')
            away = partes[2].replace('-', ' ')
            if fecha < hoy or home not in eng.stats or away not in eng.stats:
                continue
            try:
                s_l, s_v = eng.stats[home], eng.stats[away]
                ctx = {'CHOQUE_ESTILOS': 0.0, 'ALTURA_NORM': 0.0,
                       'VENTAJA_LOCALIA': 0.55, 'CLIMA_TEMP_NORM': 25 / 40.0,
                       'H2H_BALANCE': eng._h2h(home, away)}
                vec = dict(zip(fe.FEATURES_MODELO,
                               fe.vector_features(s_l, s_v, ctx)))
                cols_cfg = eng.metadata.get('features_extra_cols', [])
                if cols_cfg:
                    vals_extra = eng._vector_extra(home, away)[0]
                    vec.update(dict(zip(cols_cfg, vals_extra)))
                vec.update(f26.vector_v26(eng.estado_v26, home, away))
                x_base = [vec.get(c, 0.0) for c in art['cols']]
                p = eng.predecir(home, away)['prediction']['probabilities']
                inv = np.array([1 / o['odd_home'], 1 / o['odd_draw'],
                                1 / o['odd_away']])
                pm = inv / inv.sum()
                extras = [p['home'], p['draw'], p['away'], pm[0], pm[1], pm[2]]
                if art.get('con_cn'):
                    extras.append(vec.get('ELO_VEL_DIFF', 0.0)
                                  * (1 - (vec.get('ENTROPIA_DIFF', 0.0) + 1) / 2))
                extras.append(art.get('sev_media', 0.75))
                x = np.array([x_base + extras])
                resid = float(art['modelo'].predict(x)[0])
                if abs(resid) > art['umbral']:
                    senales[mid] = {'residuo': round(resid, 4),
                                    'lado': 'local' if resid > 0 else 'visitante',
                                    'liga': clave}
            except Exception as e:
                logger.warning(f"[shadow señal] {mid}: {type(e).__name__}: {e}")
    with open('shadow_senales.json', 'w', encoding='utf-8') as f:
        json.dump({'generado': pd.Timestamp.today().strftime('%Y-%m-%d'),
                   'senales': {k: 1 for k in senales},
                   'detalle': senales}, f, ensure_ascii=False)
    logger.info(f"shadow_senales.json: {len(senales)} señales ⚡")
    return senales


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if '--produccion' in sys.argv:
        for clave in [a for a in sys.argv[1:] if not a.startswith('-')]:
            entrenar_produccion(clave)
        generar_senales()
        sys.exit(0)
    if '--senales' in sys.argv:
        generar_senales()
        sys.exit(0)
    objetivos = sys.argv[1:] or LIGAS_DEF
    salida = {}
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding='utf-8') as f:
            salida = json.load(f)
    oof_acum = []
    for clave in objetivos:
        logger.info(f"=== shadow booster {clave} ===")
        try:
            salida[clave] = wf_liga(clave, oof_acum)
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        if oof_acum:
            pd.DataFrame(oof_acum).to_csv(OOF_CSV, index=False)
    print(json.dumps({k: {kk: v.get(kk) for kk in
                          ('roi_base_pct', 'roi_shadow_pct',
                           'roi_shadow_sin_severidad_pct', 'n_bets_shadow',
                           'adoptar')}
                      for k, v in salida.items() if isinstance(v, dict)}, indent=2))
