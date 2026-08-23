# -*- coding: utf-8 -*-
"""
v162 - ¿SE PUEDEN IMPUTAR CORNERS Y TARJETAS DONDE NO HAY DATOS?

La pregunta exacta: para una competicion de la que NO se tiene ni un corner
observado, ¿se puede estimar la lambda de cada equipo mejor que con la media de
su liga, usando solo lo que SI hay en todas partes (goles, ELO)?

Se responde con VALIDACION DEJANDO UNA LIGA FUERA. Se entrena con las ligas
que si tienen datos y se predice la que se ha apartado, como si fuera una de
las que no tienen nada. Eso es exactamente la situacion de produccion, y es la
unica forma de que el numero signifique algo: medirlo dentro de la misma liga
seria trampa, porque en produccion esa liga no tendria historia de corners.

Estimadores comparados, todos causales dentro de la liga apartada:
  A) media global de las OTRAS ligas (el suelo tonto)
  B) media de la propia liga         (el suelo real: en produccion no se
     conoce, pero se aproxima con B' = predicha desde los goles)
  B') media de liga PREDICHA desde sus goles/ELO, ajustada con las otras ligas
  C) B' modulada por el ataque del equipo (goles a favor/en contra moviles)
  D) el estimador completo con corners reales (el TECHO: lo que se consigue
     cuando si hay datos, para saber cuanto se pierde imputando)
"""
import json
import warnings

import numpy as np
import pandas as pd
from scipy import stats as st

warnings.filterwarnings('ignore')

LIGAS = ['premier', 'eng_championship', 'eng_league_one', 'eng_league_two',
         'eng_national', 'sco_premiership', 'sco_championship', 'laliga',
         'serie_a', 'ligue_1', 'bundesliga', 'esp_hypermotion', 'ita_serie_b',
         'fra_ligue2', 'turquia', 'primeira', 'ger_bundesliga2', 'eredivisie',
         'gre_super_league', 'bel_pro_league']
VENT = 10
MINP = 3
LINEAS_CK = [3.5, 4.5, 5.5, 6.5]
LINEAS_TJ = [0.5, 1.5, 2.5, 3.5]


def carga(clave):
    d = pd.read_csv('historico_%s.csv' % clave, low_memory=False)
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    for c in ('home_goals', 'away_goals', 'home_corners', 'away_corners',
              'home_yellow', 'away_yellow', 'home_red', 'away_red'):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
        else:
            d[c] = np.nan
    d['home_tj'] = d['home_yellow'] + d['home_red']
    d['away_tj'] = d['away_yellow'] + d['away_red']
    return d


def movil(g, v, n=VENT):
    return v.groupby(g).transform(
        lambda s: s.shift().rolling(n, min_periods=MINP).mean())


def prob_mas(media, linea, disp):
    m = np.asarray(media, float)
    k = int(np.floor(linea))
    if disp <= 1.0001:
        return 1.0 - st.poisson.cdf(k, m)
    r = m / (disp - 1.0)
    return 1.0 - st.nbinom.cdf(k, r, r / (r + m))


def calib(pred, real, lineas, disp):
    pred = np.asarray(pred, float)
    real = np.asarray(real, float)
    ok = np.isfinite(pred) & np.isfinite(real) & (pred > 0)
    if ok.sum() < 300:
        return None, None, 0
    p, x = pred[ok], real[ok]
    err = [abs(float(prob_mas(p, L, disp).mean()) - float((x > L).mean()))
           for L in lineas]
    corr = float(np.corrcoef(p, x)[0, 1]) if np.std(p) > 0 else np.nan
    return float(np.mean(err)), corr, int(ok.sum())


# --- se precarga todo -------------------------------------------------------
datos = {}
for c in LIGAS:
    try:
        datos[c] = carga(c)
    except Exception as e:
        print('  %s: %s' % (c, e))

# perfil de cada liga: medias globales que en produccion SI se conocen
perfil = {}
for c, d in datos.items():
    gol = float((d['home_goals'] + d['away_goals']).mean())
    perfil[c] = {
        'goles': gol,
        'gol_local': float(d['home_goals'].mean()),
        'ck': float((d['home_corners'] + d['away_corners']).mean()),
        'tj': float((d['home_tj'] + d['away_tj']).mean()),
        'disp_ck_eq': max(float(pd.concat([d['home_corners'], d['away_corners']])
                                .var()
                                / pd.concat([d['home_corners'], d['away_corners']])
                                .mean()), 1.0),
        'disp_tj_eq': max(float(pd.concat([d['home_tj'], d['away_tj']]).var()
                                / pd.concat([d['home_tj'], d['away_tj']]).mean()),
                          1.0),
    }

print('=' * 78)
print('PERFIL POR LIGA (lo que se conoce sin tener corners)')
pf = pd.DataFrame(perfil).T
print(pf.round(3).to_string())

# ¿los goles predicen la media de corners/tarjetas de una liga?
print()
print('=' * 78)
print('¿LOS GOLES DE UNA LIGA PREDICEN SU MEDIA DE CORNERS / TARJETAS?')
for objetivo in ('ck', 'tj'):
    x = pf['goles'].to_numpy(float)
    y = pf[objetivo].to_numpy(float)
    r = float(np.corrcoef(x, y)[0, 1])
    print('  %s ~ goles: correlacion entre ligas = %+.3f  (n=%d ligas)'
          % (objetivo, r, len(x)))
    print('     rango de %s entre ligas: %.2f a %.2f (sd %.2f)'
          % (objetivo, y.min(), y.max(), y.std()))

# --- la validacion dejando una liga fuera ----------------------------------
filas = []
for fuera in LIGAS:
    if fuera not in datos:
        continue
    otras = [c for c in datos if c != fuera]
    # regresion simple entre ligas: media_objetivo ~ a + b * media_goles
    X = np.array([[1.0, perfil[c]['goles']] for c in otras])
    for objetivo, cols, lineas in (('ck', ('home_corners', 'away_corners'), LINEAS_CK),
                                   ('tj', ('home_tj', 'away_tj'), LINEAS_TJ)):
        y = np.array([perfil[c][objetivo] for c in otras])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        media_pred = float(coef[0] + coef[1] * perfil[fuera]['goles'])
        media_global = float(y.mean())
        # dispersion: la mediana de las otras ligas (tampoco se conoce la suya)
        disp_pred = float(np.median([perfil[c]['disp_%s_eq' % objetivo]
                                     for c in otras]))

        d = datos[fuera]
        ch, ca = cols
        # tramo de juicio: el ultimo 30 %
        corte = d['date'].quantile(0.70)
        J = (d['date'] > corte).to_numpy()
        real = np.concatenate([d[ch].to_numpy()[J], d[ca].to_numpy()[J]])

        # A) media global de las otras ligas, repartida por bando segun la
        #    proporcion local/visitante media de las otras
        prop_h = float(np.mean([
            datos[c][cols[0]].mean() / (datos[c][cols[0]].mean()
                                        + datos[c][cols[1]].mean())
            for c in otras]))
        n = int(J.sum())
        A = np.concatenate([np.full(n, media_global * prop_h),
                            np.full(n, media_global * (1 - prop_h))])
        # B') media de liga PREDICHA desde sus goles
        B = np.concatenate([np.full(n, media_pred * prop_h),
                            np.full(n, media_pred * (1 - prop_h))])
        # C) B' modulada por el ataque del equipo (goles moviles, causales)
        gf_h = movil(d['home_team'], d['home_goals'])
        gf_a = movil(d['away_team'], d['away_goals'])
        gc_h = movil(d['home_team'], d['away_goals'])
        gc_a = movil(d['away_team'], d['home_goals'])
        base_h = d['home_goals'].expanding().mean().shift()
        base_a = d['away_goals'].expanding().mean().shift()
        # empuje: cuanto ataca el equipo frente a la media de su bando, y
        # cuanto concede el rival. Acotado para que no dispare.
        mod_h = np.clip(0.5 * (gf_h / base_h) + 0.5 * (gc_a / base_a), 0.6, 1.6)
        mod_a = np.clip(0.5 * (gf_a / base_a) + 0.5 * (gc_h / base_h), 0.6, 1.6)
        C = np.concatenate([media_pred * prop_h * mod_h.to_numpy()[J],
                            media_pred * (1 - prop_h) * mod_a.to_numpy()[J]])
        # C2) la MISMA modulacion, pero preservando la media. El recorte a
        # [0,6 - 1,6] y la propia forma del cociente dejan la media del
        # modulador lejos de 1, y eso mueve el NIVEL de todas las
        # probabilidades a la vez: por eso C tenia mejor correlacion y peor
        # calibracion que la media a secas. Se divide por la media acumulada
        # del propio modulador, que es causal.
        def _norm(serie):
            s = pd.Series(serie)
            return (s / s.expanding().mean().shift()).clip(0.6, 1.6)
        nh, na = _norm(mod_h), _norm(mod_a)
        C2 = np.concatenate([media_pred * prop_h * nh.to_numpy()[J],
                             media_pred * (1 - prop_h) * na.to_numpy()[J]])
        # C3) modulacion INVERTIDA, para tarjetas: si atacar mas significa
        # menos tarjetas (correlacion negativa medida), el mismo modulador con
        # el signo cambiado deberia ayudar en vez de estorbar.
        C3 = np.concatenate([media_pred * prop_h / nh.to_numpy()[J],
                             media_pred * (1 - prop_h) / na.to_numpy()[J]])
        # D) el techo: el estimador real con datos de la propia liga
        lh = (movil(d['home_team'], d[ch]) + movil(d['away_team'], d[ch])) / 2
        la = (movil(d['away_team'], d[ca]) + movil(d['home_team'], d[ca])) / 2
        D = np.concatenate([lh.to_numpy()[J], la.to_numpy()[J]])
        disp_real = perfil[fuera]['disp_%s_eq' % objetivo]

        for nombre, pred, dsp in (('A_media_global', A, disp_pred),
                                  ('B_media_predicha', B, disp_pred),
                                  ('C_modulada', C, disp_pred),
                                  ('C2_modulada_normalizada', C2, disp_pred),
                                  ('C3_modulada_invertida', C3, disp_pred),
                                  ('D_TECHO_con_datos', D, disp_real)):
            e, r, nn = calib(pred, real, lineas, dsp)
            if e is None:
                continue
            filas.append({'liga': fuera, 'objetivo': objetivo,
                          'estimador': nombre, 'error_calib': e,
                          'corr': r, 'n': nn})

t = pd.DataFrame(filas)
print()
print('=' * 78)
print('VALIDACION DEJANDO UNA LIGA FUERA (media sobre las 20)')
for objetivo, etq in (('ck', 'CORNERS'), ('tj', 'TARJETAS')):
    print()
    print('--- %s por equipo ---' % etq)
    g = (t[t['objetivo'] == objetivo].groupby('estimador')
         .agg(error_calib=('error_calib', 'mean'), corr=('corr', 'mean'),
              ligas=('liga', 'nunique'), n=('n', 'sum'))
         .sort_values('error_calib'))
    print(g.round(4).to_string())

json.dump(filas, open('_v162_imputacion.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=float)
