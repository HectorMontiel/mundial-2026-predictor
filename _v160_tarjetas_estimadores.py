# -*- coding: utf-8 -*-
"""
v160 - TARJETAS: que estimador acierta, y si el arbitro aporta.

Se replica la metodologia con la que se cerraron los corners:
  - lambda por equipo = (lo que COMETE el equipo en su bando + lo que INDUCE el
    rival en el bando contrario) / 2, ventana 10
  - binomial negativa con la razon varianza/media medida
  - se juzga por ERROR DE CALIBRACION contra la frecuencia real en las lineas
    que cotiza la casa, no por MAE (leccion de la v157: el MAE esconde senal)

Todo causal: cada partido se predice con medias moviles DESPLAZADAS un partido.
El tramo de juicio es el ultimo 30 % por fecha, y el arbitro solo se compara en
las 7 competiciones que publican quien pito cada partido.
"""
import json
import numpy as np
import pandas as pd
from scipy import stats as st

VENTANA = 10
MINP = 3
CON_ARBITRO = ['premier', 'eng_championship', 'eng_league_one', 'eng_league_two',
               'eng_national', 'sco_premiership', 'sco_championship']
SIN_ARBITRO = ['laliga', 'serie_a', 'ligue_1', 'bundesliga', 'esp_hypermotion',
               'ita_serie_b', 'fra_ligue2', 'turquia', 'primeira',
               'ger_bundesliga2', 'eredivisie', 'gre_super_league',
               'bel_pro_league']
LINEAS_EQ = [0.5, 1.5, 2.5, 3.5]
LINEAS_TOT = [2.5, 3.5, 4.5, 5.5]


def carga(clave):
    d = pd.read_csv('historico_%s.csv' % clave, low_memory=False)
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    for c in ('home_yellow', 'away_yellow'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['home_yellow', 'away_yellow']).reset_index(drop=True)
    return d


def movil(serie_grupo, serie_valor, n=VENTANA):
    """Media de los n anteriores del grupo, DESPLAZADA: nunca se ve a si mismo."""
    return (serie_valor.groupby(serie_grupo)
            .transform(lambda s: s.shift().rolling(n, min_periods=MINP).mean()))


def prob_mas(media, linea, disp):
    m = np.asarray(media, float)
    k = int(np.floor(linea))
    d = float(disp)
    if d <= 1.0001:
        return 1.0 - st.poisson.cdf(k, m)
    r = m / (d - 1.0)
    p = r / (r + m)
    return 1.0 - st.nbinom.cdf(k, r, p)


def calibracion(pred, real, lineas, disp):
    """Error medio |P calculada - frecuencia real| en las lineas dadas."""
    errs = []
    pred = np.asarray(pred, float)
    real = np.asarray(real, float)
    ok = np.isfinite(pred) & np.isfinite(real)
    if ok.sum() < 200:
        return None, 0
    p, x = pred[ok], real[ok]
    for L in lineas:
        errs.append(abs(float(np.mean(prob_mas(p, L, disp))) - float(np.mean(x > L))))
    return float(np.mean(errs)), int(ok.sum())


def corr(pred, real):
    pred = np.asarray(pred, float)
    real = np.asarray(real, float)
    m = np.isfinite(pred) & np.isfinite(real)
    if m.sum() < 200 or np.std(pred[m]) == 0:
        return float('nan')
    return float(np.corrcoef(pred[m], real[m])[0, 1])


filas, filas_ref, resumen_disp = [], [], []

for clave in CON_ARBITRO + SIN_ARBITRO:
    try:
        d = carga(clave)
    except Exception as e:
        print('  %s: %s' % (clave, e))
        continue
    if len(d) < 800:
        continue

    tot = d['home_yellow'] + d['away_yellow']
    serie_eq = pd.concat([d['home_yellow'], d['away_yellow']])
    disp_tot = max(float(tot.var() / tot.mean()), 1.0)
    disp_eq = max(float(serie_eq.var() / serie_eq.mean()), 1.0)
    resumen_disp.append({'clave': clave, 'n': len(d),
                         'media_tot': round(float(tot.mean()), 3),
                         'disp_tot': round(disp_tot, 4),
                         'media_eq': round(float(serie_eq.mean()), 3),
                         'disp_eq': round(disp_eq, 4)})

    # --- estimadores causales, por equipo -----------------------------------
    h_comete = movil(d['home_team'], d['home_yellow'])   # el local, en casa
    a_comete = movil(d['away_team'], d['away_yellow'])   # el visitante, fuera
    h_induce = movil(d['home_team'], d['away_yellow'])   # lo que el local provoca
    a_induce = movil(d['away_team'], d['home_yellow'])   # lo que el visitante provoca

    lam_h = (h_comete + a_induce) / 2.0
    lam_a = (a_comete + h_induce) / 2.0

    m5_h = movil(d['home_team'], d['home_yellow'], 5)
    m5_a = movil(d['away_team'], d['away_yellow'], 5)
    prop_h = d['home_yellow'].expanding().mean().shift()
    prop_a = d['away_yellow'].expanding().mean().shift()

    corte = d['date'].quantile(0.70)
    J = (d['date'] > corte).to_numpy()

    real_eq = np.concatenate([d['home_yellow'].to_numpy()[J],
                              d['away_yellow'].to_numpy()[J]])
    pred_eq = {
        'A_media_liga_bando': np.concatenate([prop_h.to_numpy()[J], prop_a.to_numpy()[J]]),
        'B_media_equipo_movil5': np.concatenate([m5_h.to_numpy()[J], m5_a.to_numpy()[J]]),
        'C_solo_comete_v10': np.concatenate([h_comete.to_numpy()[J], a_comete.to_numpy()[J]]),
        'D_atk_def_v10': np.concatenate([lam_h.to_numpy()[J], lam_a.to_numpy()[J]]),
    }
    for nombre, p in pred_eq.items():
        for etiqueta, dsp in (('binneg', disp_eq), ('poisson', 1.0)):
            err, n = calibracion(p, real_eq, LINEAS_EQ, dsp)
            if err is None:
                continue
            filas.append({'clave': clave, 'ambito': 'equipo', 'estimador': nombre,
                          'dist': etiqueta, 'error_calib': err, 'n': n,
                          'corr': corr(p, real_eq)})

    # --- total del partido ---------------------------------------------------
    lam_tot = lam_h + lam_a
    media_tot_causal = tot.expanding().mean().shift()
    real_tot = tot.to_numpy()[J]
    for nombre, p in (('A_media_liga', media_tot_causal.to_numpy()[J]),
                      ('D_atk_def_v10', lam_tot.to_numpy()[J])):
        for etiqueta, dsp in (('binneg', disp_tot), ('poisson', 1.0)):
            err, n = calibracion(p, real_tot, LINEAS_TOT, dsp)
            if err is None:
                continue
            filas.append({'clave': clave, 'ambito': 'total', 'estimador': nombre,
                          'dist': etiqueta, 'error_calib': err, 'n': n,
                          'corr': corr(p, real_tot)})

    # --- el arbitro ----------------------------------------------------------
    if clave in CON_ARBITRO and 'referee' in d.columns:
        ref = d['referee'].astype('object').map(
            lambda x: str(x).strip() if pd.notna(x) else '')
        vale = (ref != '') & (ref.str.lower() != 'nan')
        r_media = tot.groupby(ref).transform(lambda s: s.shift().expanding().mean())
        r_n = tot.groupby(ref).transform(lambda s: s.shift().expanding().count())
        base = lam_tot.to_numpy(float)
        sel = J & vale.to_numpy()
        err0, n0 = calibracion(base[sel], tot.to_numpy()[sel], LINEAS_TOT, disp_tot)
        if err0 is not None:
            filas_ref.append({'clave': clave, 'K': None, 'estimador': 'D_sin_arbitro',
                              'error_calib': err0, 'n': n0,
                              'corr': corr(base[sel], tot.to_numpy()[sel])})
        for K in (0, 5, 10, 20, 40, 80):
            bruto = (r_media / media_tot_causal).to_numpy(float)
            nn = r_n.to_numpy(float)
            razon = (nn * bruto + K * 1.0) / (nn + K)
            razon = np.where(np.isfinite(razon), razon, 1.0)
            p_ref = base * razon
            err, n = calibracion(p_ref[sel], tot.to_numpy()[sel], LINEAS_TOT, disp_tot)
            if err is None:
                continue
            filas_ref.append({'clave': clave, 'K': K,
                              'estimador': 'E_con_arbitro_K%d' % K,
                              'error_calib': err, 'n': n,
                              'corr': corr(p_ref[sel], tot.to_numpy()[sel])})

t = pd.DataFrame(filas)
print('=' * 78)
print('DISPERSION MEDIDA')
print(pd.DataFrame(resumen_disp).to_string(index=False))
print()
print('=' * 78)
print('ESTIMADORES - media sobre competiciones (error de calibracion: menos es mejor)')
for ambito in ('equipo', 'total'):
    print()
    print('--- %s ---' % ambito.upper())
    g = (t[t['ambito'] == ambito]
         .groupby(['estimador', 'dist'])
         .agg(error_calib=('error_calib', 'mean'), corr=('corr', 'mean'),
              ligas=('clave', 'nunique'), n=('n', 'sum'))
         .sort_values('error_calib'))
    print(g.round(4).to_string())

r = pd.DataFrame(filas_ref)
print()
print('=' * 78)
print('EL ARBITRO - solo las 7 competiciones que publican quien pito')
g = (r.groupby('estimador')
     .agg(error_calib=('error_calib', 'mean'), corr=('corr', 'mean'),
          ligas=('clave', 'nunique'), n=('n', 'sum'))
     .sort_values('error_calib'))
print(g.round(5).to_string())

json.dump({'dispersion': resumen_disp, 'estimadores': filas, 'arbitro': filas_ref},
          open('_v160_tarjetas_estimadores.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=float)
