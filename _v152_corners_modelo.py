#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v152 — ¿HAY UN MODELO DE CÓRNERS, O SÓLO UNA CONSTANTE?

Por qué este experimento
------------------------
La medición del sesgo (`_v152_corners_sesgo.py`) devolvió sobre la Premier algo
que no se esperaba y que decide el rumbo:

    sesgo con lambdas de producción ...  +0,32   (no −1,3)
    correlación predicho/real .........  +0,0039

El sesgo de nivel es pequeño: la base 4,0 estaba bien y la «corrección» a 5,3
habría empeorado. Pero la correlación es CERO, y además es una correlación
OPTIMISTA (el motor predice con el estado actual de los equipos, o sea con
información del futuro respecto al partido medido). Un límite superior de 0,004
no deja margen: **la fórmula de córners de producción no distingue un partido de
otro. Es una constante con ruido.**

Eso invalida cualquier EV de córners calculado con ella, en la dirección
peligrosa: un modelo que siempre dice ~10,1 producirá EV enormes en cuanto la
casa mueva su línea a 8,5 u 11,5, y ese EV será íntegramente error del modelo.
Es la firma que la bitácora §2 manda leer como «el modelo se equivoca».

La pregunta que este script contesta
------------------------------------
¿Se puede construir un modelo de córners que SÍ discrimine, con lo que hay?
football-data publica córners (HC/AC) y remates (HS/AS/HST/AST) REALES en las
20 ligas de formato 'main'. La fórmula actual no los usa: deriva los córners del
xG, que en este proyecto es sintético.

Cómo se valida, y por qué así
-----------------------------
Split TEMPORAL: las temporadas antiguas entrenan, la última juzga. Las features
se calculan en un pase cronológico con medias móviles que sólo miran hacia
atrás, igual que `features_extra_liga`. No hay `predecir` de por medio, así que
no hay estado actual filtrándose.

Se compara contra dos líneas base, y las dos importan:

  · CONSTANTE: la media de córners del tramo de entrenamiento. Es el rival de
    verdad. Un modelo de córners que no bate a «di siempre 10,1» no es un
    modelo.
  · FÓRMULA ACTUAL: `4,0 + 0,25·(lam_h+lam_a)·spx·tpo`, alimentada con el xG
    sintético del histórico, que es lo más cerca que se puede estar de la
    entrada de producción sin fuga.

Métrica: MAE y correlación fuera de muestra, con bootstrap sobre la DIFERENCIA
de MAE contra la constante. Si el percentil 5 de la mejora no cruza cero, no hay
modelo: hay ruido que a veces gana.

LO QUE ESTE SCRIPT NO PUEDE MEDIR
---------------------------------
El ROI. No existe histórico de LÍNEAS de córners: football-data no las publica y
el histórico de The Odds API es de pago (prohibido en el §7 del proyecto). Sin
líneas no hay apuesta que liquidar, así que la regla de oro —p5 positivo en el
tramo de juicio— NO se puede aplicar a córners hoy. Un modelo que baje el MAE es
condición necesaria y no suficiente para activar EV.
"""
import json
import logging
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import league_engine as le
import statsbomb_calibration
from config import LEAGUES

# LAS 20 COMPETICIONES CON CÓRNERS OBSERVADOS, y ni una más.
#
# Medido por `_v152_cobertura_stats.py`: de las 75 competiciones del proyecto,
# sólo estas 20 —las de football-data formato 'main'— tienen córners que
# publicó la fuente. En las otras 55 la columna existe pero la escribió el
# generador sintético, y entrenar un modelo de córners contra el relleno del
# propio generador daría un backtest excelente por construcción.
#
# La marca `secundaria` sirve para la otra pregunta del plan: si el margen de
# error de la casa es mayor en las ligas de menos volumen, aquí es donde se
# puede empezar a mirar. Once de las veinte lo son, con 48.000 partidos.
PRINCIPALES = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1',
               'eredivisie', 'primeira', 'turquia', 'sco_premiership',
               'bel_pro_league']
SECUNDARIAS = ['eng_championship', 'eng_league_one', 'eng_league_two',
               'eng_national', 'esp_hypermotion', 'ita_serie_b', 'fra_ligue2',
               'ger_bundesliga2', 'sco_championship', 'gre_super_league']
LIGAS = PRINCIPALES + SECUNDARIAS

CAL = statsbomb_calibration.calibrar()
SPX = float(CAL.get('shots_on_por_xg', 3.1))
TPO = float(CAL.get('shots_total_por_on', 2.6))

VENTANA = 5          # «últimos 5 partidos», que es lo que pidió el usuario
MIN_HIST = 3         # con menos de 3 partidos previos la media móvil no dice nada


def _ma(historial, n=VENTANA):
    """Media de los últimos `n`, o None si no hay suficientes."""
    if len(historial) < MIN_HIST:
        return None
    return float(np.mean(historial[-n:]))


def construir_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Un pase cronológico. Cada fila ve SÓLO lo anterior a su fecha.

    Se separan córners a favor y en contra, y dentro de cada equipo se guarda
    además la serie de local y la de visitante por separado: un equipo que saca
    7 córners en casa y 3 fuera no es lo mismo que uno que saca 5 y 5, y el
    partido que se predice tiene bandos asignados.
    """
    df = df.sort_values('date').reset_index(drop=True)
    # historial[eq] = {'ck_f': [...], 'ck_c': [...], 'ck_f_casa': [...], ...}
    hist = {}

    def h(eq):
        return hist.setdefault(eq, {'ck_f': [], 'ck_c': [], 'ck_f_casa': [],
                                    'ck_f_fuera': [], 'rem': [], 'rem_c': [],
                                    'tiros': []})

    filas = []
    for f in df.itertuples(index=False):
        hh, ha = h(f.home_team), h(f.away_team)
        fila = {
            'idx': f.Index if hasattr(f, 'Index') else None,
            'date': f.date,
            'ck_total': float(f.home_corners) + float(f.away_corners),
            'elo_diff': float(getattr(f, 'elo_diff', 0) or 0),
            # a favor / en contra, todos los partidos
            'ck_h_f': _ma(hh['ck_f']), 'ck_h_c': _ma(hh['ck_c']),
            'ck_a_f': _ma(ha['ck_f']), 'ck_a_c': _ma(ha['ck_c']),
            # la serie del bando que le toca jugar
            'ck_h_casa': _ma(hh['ck_f_casa']), 'ck_a_fuera': _ma(ha['ck_f_fuera']),
            # RITMO: remates totales, que son reales en formato 'main' y son la
            # variable física de la que salen los córners (un remate bloqueado o
            # desviado ES un córner en buena parte de los casos)
            'rem_h': _ma(hh['rem']), 'rem_a': _ma(ha['rem']),
            'rem_h_c': _ma(hh['rem_c']), 'rem_a_c': _ma(ha['rem_c']),
            # xG sintético del histórico, para reproducir la fórmula actual
            'xg_h': float(getattr(f, 'home_xg', np.nan) or np.nan),
            'xg_a': float(getattr(f, 'away_xg', np.nan) or np.nan),
        }
        filas.append(fila)

        ckh, cka = float(f.home_corners), float(f.away_corners)
        rh = float(getattr(f, 'home_shots_on', 0) or 0) + \
            float(getattr(f, 'home_shots_off', 0) or 0)
        ra = float(getattr(f, 'away_shots_on', 0) or 0) + \
            float(getattr(f, 'away_shots_off', 0) or 0)
        hh['ck_f'].append(ckh); hh['ck_c'].append(cka); hh['ck_f_casa'].append(ckh)
        hh['rem'].append(rh); hh['rem_c'].append(ra)
        ha['ck_f'].append(cka); ha['ck_c'].append(ckh); ha['ck_f_fuera'].append(cka)
        ha['rem'].append(ra); ha['rem_c'].append(rh)
    return pd.DataFrame(filas)


COLS = ['ck_h_f', 'ck_h_c', 'ck_a_f', 'ck_a_c', 'ck_h_casa', 'ck_a_fuera',
        'rem_h', 'rem_a', 'rem_h_c', 'rem_a_c', 'elo_diff']


def bootstrap_p5(dif, n_iter=2000, semilla=7):
    """
    Percentil 5 de la mejora media de MAE, por bootstrap.

    `dif` es (error_base − error_modelo) partido a partido: positivo = el modelo
    acierta más. Si el p5 no cruza cero, la mejora no se distingue de la suerte.
    """
    rng = np.random.default_rng(semilla)
    d = np.asarray(dif, float)
    m = rng.choice(d, size=(n_iter, len(d)), replace=True).mean(axis=1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95))


def mide_liga(clave, temporadas=6):
    t0 = time.time()
    df = le.descargar_liga(clave, temporadas=temporadas)
    df = df.dropna(subset=['home_corners', 'away_corners', 'home_goals',
                           'away_goals'])
    if len(df) < 500:
        return {'liga': clave, 'excluida': True, 'motivo': 'n=%d' % len(df)}
    d = construir_features(df).dropna(subset=COLS + ['ck_total'])
    if len(d) < 400:
        return {'liga': clave, 'excluida': True,
                'motivo': 'con features n=%d' % len(d)}

    # Split TEMPORAL: el último 25 % del calendario juzga.
    corte = d['date'].quantile(0.75)
    tr, te = d[d['date'] <= corte], d[d['date'] > corte]
    if len(te) < 120:
        return {'liga': clave, 'excluida': True, 'motivo': 'juicio n=%d' % len(te)}

    y_tr, y_te = tr['ck_total'].to_numpy(), te['ck_total'].to_numpy()

    # --- línea base 1: LA CONSTANTE ---------------------------------------
    const = float(y_tr.mean())
    e_const = np.abs(y_te - const)

    # --- línea base 2: LA FÓRMULA DE PRODUCCIÓN ---------------------------
    var_tr = 0.25 * (tr['xg_h'] + tr['xg_a']) * SPX * TPO
    var_te = 0.25 * (te['xg_h'] + te['xg_a']) * SPX * TPO
    ck_form = 4.0 + var_te
    e_form = np.abs(y_te - ck_form.to_numpy())

    # --- línea base 3: LA MISMA FÓRMULA CON EL NIVEL CORREGIDO ------------
    #
    # La medición del sesgo dejó claro que la constante 4,0 descuadra el nivel
    # (+0,435 de media, +1,53 en Grecia). Corregirlo es la reparación MÍNIMA:
    # se sustituye la constante global por la que calibra esta liga en el tramo
    # de entrenamiento, y se deja la parte variable intacta.
    #
    # Esta variante contesta la pregunta que decide qué se cambia en
    # producción: si con el nivel ya corregido la fórmula SIGUE por detrás de
    # decir siempre la media, entonces el problema no es la constante — es que
    # la parte variable es ruido, y añadir ruido a una media la empeora.
    base_liga = float(y_tr.mean() - var_tr.mean())
    ck_nivel = base_liga + var_te
    e_nivel = np.abs(y_te - ck_nivel.to_numpy())

    # --- el modelo --------------------------------------------------------
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import HistGradientBoostingRegressor
    esc = StandardScaler().fit(tr[COLS])
    rid = RidgeCV(alphas=np.logspace(-2, 3, 20)).fit(esc.transform(tr[COLS]), y_tr)
    p_rid = rid.predict(esc.transform(te[COLS]))
    e_rid = np.abs(y_te - p_rid)

    gbm = HistGradientBoostingRegressor(
        max_depth=3, max_iter=200, learning_rate=0.05,
        l2_regularization=1.0, random_state=7).fit(tr[COLS], y_tr)
    p_gbm = gbm.predict(te[COLS])
    e_gbm = np.abs(y_te - p_gbm)

    def bloque(nombre, err, pred):
        p5, p95 = bootstrap_p5(e_const - err)
        return {
            'mae': round(float(err.mean()), 4),
            'mejora_vs_constante': round(float((e_const - err).mean()), 4),
            'p5': round(p5, 4), 'p95': round(p95, 4),
            'corr': round(float(np.corrcoef(pred, y_te)[0, 1]), 4)
            if np.std(pred) > 1e-9 else 0.0,
        }

    return {
        'liga': clave, 'excluida': False,
        'tipo': 'secundaria' if clave in SECUNDARIAS else 'principal',
        'n_train': int(len(tr)), 'n_juicio': int(len(te)),
        'ck_media_juicio': round(float(y_te.mean()), 3),
        'ck_sd_juicio': round(float(y_te.std()), 3),
        'constante': round(const, 3),
        'mae_constante': round(float(e_const.mean()), 4),
        'formula_actual': bloque('formula', e_form, ck_form.to_numpy()),
        'formula_nivel_corregido': bloque('nivel', e_nivel, ck_nivel.to_numpy()),
        'base_liga_calibrada': round(base_liga, 3),
        'ridge': bloque('ridge', e_rid, p_rid),
        'gbm': bloque('gbm', e_gbm, p_gbm),
        'coef_ridge': {c: round(float(v), 4)
                       for c, v in zip(COLS, rid.coef_)},
        'segundos': round(time.time() - t0, 1),
    }


def main():
    ligas = sys.argv[1:] or LIGAS
    res = []
    for c in ligas:
        try:
            r = mide_liga(c)
        except Exception as e:
            r = {'liga': c, 'excluida': True,
                 'motivo': '%s: %s' % (type(e).__name__, e)}
        res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)

    ok = [r for r in res if not r.get('excluida')]
    if not ok:
        return

    def resume(grupo, etiqueta):
        n = sum(r['n_juicio'] for r in grupo)

        def pond(*camino):
            tot = 0.0
            for r in grupo:
                v = r
                for k in camino:
                    v = v[k]
                tot += v * r['n_juicio']
            return round(tot / n, 4)

        return {
            'grupo': etiqueta, 'ligas': len(grupo), 'n_juicio_total': n,
            'mae_constante': pond('mae_constante'),
            'mae_formula': pond('formula_actual', 'mae'),
            'mae_formula_nivel_corregido': pond('formula_nivel_corregido', 'mae'),
            'mae_ridge': pond('ridge', 'mae'),
            'mae_gbm': pond('gbm', 'mae'),
            'corr_formula': pond('formula_actual', 'corr'),
            'corr_ridge': pond('ridge', 'corr'),
            'corr_gbm': pond('gbm', 'corr'),
            'ligas_nivel_p5_positivo': sum(
                1 for r in grupo if r['formula_nivel_corregido']['p5'] > 0),
            'ligas_ridge_p5_positivo': sum(1 for r in grupo if r['ridge']['p5'] > 0),
            'ligas_gbm_p5_positivo': sum(1 for r in grupo if r['gbm']['p5'] > 0),
        }

    resumen = {'todas': resume(ok, 'todas')}
    for etq in ('principal', 'secundaria'):
        g = [r for r in ok if r.get('tipo') == etq]
        if g:
            resumen[etq] = resume(g, etq)
    for v in resumen.values():
        print('\nRESUMEN ' + json.dumps(v, ensure_ascii=False), flush=True)
    json.dump({'ligas': res, 'resumen': resumen},
              open('_v152_corners_modelo.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
