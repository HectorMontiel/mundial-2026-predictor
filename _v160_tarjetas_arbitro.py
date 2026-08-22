# -*- coding: utf-8 -*-
"""
v160 - EL ARBITRO EN TARJETAS: cuanto aporta, y con cuanto encogimiento.

La primera pasada dejo dos cosas peleadas: con encogimiento flojo la
CORRELACION sube y la CALIBRACION empeora; con encogimiento fuerte pasa al
reves. Eso huele a que el problema no es la senal del arbitro sino el NIVEL:
una razon cruda con media distinta de 1 mueve todas las probabilidades a la vez.

Aqui se separan las dos cosas:
  - discriminacion: correlacion y BRIER en cada linea (regla propia, premia
    acertar partido a partido, no solo acertar la media)
  - nivel: la media de la razon aplicada, que deberia quedarse en 1

y se prueba la razon normalizada CAUSALMENTE (dividida por su propia media
acumulada hasta ese partido), que corrige el nivel sin mirar al futuro.

Todo causal. Tramo de juicio: ultimo 30 % por fecha.
"""
import json
import numpy as np
import pandas as pd
from scipy import stats as st

VENTANA = 10
MINP = 3
LIGAS = ['premier', 'eng_championship', 'eng_league_one', 'eng_league_two',
         'eng_national', 'sco_premiership', 'sco_championship']
LINEAS_TOT = [2.5, 3.5, 4.5, 5.5]


def movil(g, v, n=VENTANA):
    return v.groupby(g).transform(lambda s: s.shift().rolling(n, min_periods=MINP).mean())


def prob_mas(media, linea, disp):
    m = np.asarray(media, float)
    k = int(np.floor(linea))
    if disp <= 1.0001:
        return 1.0 - st.poisson.cdf(k, m)
    r = m / (disp - 1.0)
    return 1.0 - st.nbinom.cdf(k, r, r / (r + m))


def metricas(pred, real, disp):
    pred = np.asarray(pred, float)
    real = np.asarray(real, float)
    ok = np.isfinite(pred) & np.isfinite(real) & (pred > 0)
    if ok.sum() < 500:
        return None
    p, x = pred[ok], real[ok]
    cal, brier = [], []
    for L in LINEAS_TOT:
        pr = prob_mas(p, L, disp)
        y = (x > L).astype(float)
        cal.append(abs(float(pr.mean()) - float(y.mean())))
        brier.append(float(np.mean((pr - y) ** 2)))
    return {'calib': float(np.mean(cal)), 'brier': float(np.mean(brier)),
            'corr': float(np.corrcoef(p, x)[0, 1]), 'n': int(ok.sum())}


filas = []
for clave in LIGAS:
    d = pd.read_csv('historico_%s.csv' % clave, low_memory=False)
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    for c in ('home_yellow', 'away_yellow'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['home_yellow', 'away_yellow']).reset_index(drop=True)
    tot = d['home_yellow'] + d['away_yellow']
    disp = max(float(tot.var() / tot.mean()), 1.0)

    lam = ((movil(d['home_team'], d['home_yellow']) + movil(d['away_team'], d['home_yellow'])) / 2.0
           + (movil(d['away_team'], d['away_yellow']) + movil(d['home_team'], d['away_yellow'])) / 2.0)
    media_causal = tot.expanding().mean().shift()

    ref = d['referee'].astype('object').map(lambda x: str(x).strip() if pd.notna(x) else '')
    vale = (ref != '') & (ref.str.lower() != 'nan')
    r_media = tot.groupby(ref).transform(lambda s: s.shift().expanding().mean())
    r_n = tot.groupby(ref).transform(lambda s: s.shift().expanding().count())
    # el arbitro tambien envejece: ventana de 40 partidos frente al historico entero
    r_media40 = tot.groupby(ref).transform(
        lambda s: s.shift().rolling(40, min_periods=5).mean())
    r_n40 = tot.groupby(ref).transform(
        lambda s: s.shift().rolling(40, min_periods=5).count())

    corte = d['date'].quantile(0.70)
    J = ((d['date'] > corte) & vale).to_numpy()
    base = lam.to_numpy(float)
    real = tot.to_numpy(float)

    m = metricas(base[J], real[J], disp)
    if m:
        filas.append(dict(clave=clave, variante='sin_arbitro', K=None,
                          razon_media=1.0, **m))

    for etiqueta, rm, rn in (('hist', r_media, r_n), ('v40', r_media40, r_n40)):
        bruto = (rm / media_causal).to_numpy(float)
        nn = rn.to_numpy(float)
        for K in (10, 20, 40, 60, 80, 120, 200):
            razon = (nn * bruto + K) / (nn + K)
            razon = np.where(np.isfinite(razon), razon, 1.0)
            m = metricas(base[J] * razon[J], real[J], disp)
            if m:
                filas.append(dict(clave=clave, variante=etiqueta, K=K,
                                  razon_media=float(np.mean(razon[J])), **m))
            # misma razon, renormalizada por su propia media acumulada
            s = pd.Series(razon)
            norm = (s / s.expanding().mean().shift()).to_numpy(float)
            norm = np.where(np.isfinite(norm), norm, 1.0)
            m = metricas(base[J] * norm[J], real[J], disp)
            if m:
                filas.append(dict(clave=clave, variante=etiqueta + '_norm', K=K,
                                  razon_media=float(np.mean(norm[J])), **m))

t = pd.DataFrame(filas)
base_row = t[t['variante'] == 'sin_arbitro']
print('=' * 88)
print('REFERENCIA sin arbitro: calib %.5f  brier %.5f  corr %.4f  (n=%d)' % (
    base_row['calib'].mean(), base_row['brier'].mean(),
    base_row['corr'].mean(), base_row['n'].sum()))
print()
g = (t[t['variante'] != 'sin_arbitro']
     .groupby(['variante', 'K'])
     .agg(calib=('calib', 'mean'), brier=('brier', 'mean'), corr=('corr', 'mean'),
          razon_media=('razon_media', 'mean'), ligas=('clave', 'nunique'))
     .sort_values('brier'))
print('CON ARBITRO (ordenado por Brier, que es la regla propia)')
print(g.round(5).to_string())
print()
print('mejora de Brier del mejor sobre la referencia: %.6f' % (
    base_row['brier'].mean() - g['brier'].min()))

# por liga, para ver si el aporte es general o de una sola competicion
mejor = g['brier'].idxmin()
print()
print('DESGLOSE POR COMPETICION de la variante ganadora %s' % (mejor,))
sub = t[(t['variante'] == mejor[0]) & (t['K'] == mejor[1])][
    ['clave', 'calib', 'brier', 'corr', 'n']]
ref0 = base_row.set_index('clave')
sub = sub.assign(brier_sin=sub['clave'].map(ref0['brier']),
                 corr_sin=sub['clave'].map(ref0['corr']))
sub['gana_brier'] = sub['brier_sin'] - sub['brier']
print(sub.round(5).to_string(index=False))

json.dump(filas, open('_v160_tarjetas_arbitro.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=float)
