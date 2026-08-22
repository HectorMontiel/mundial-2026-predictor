#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v157 — ¿CAPTURAN MÁS SEÑAL LAS VARIABLES DE FOTMOB?

La pregunta, con el marco correcto
----------------------------------
El techo de correlación para el total de córners es 0,360 (v157: `sd(λ)/sd(X)`
sobre 49.986 partidos). Todo lo probado hasta ahora se queda en 0,06:

    ridge con 32 features del histórico ....  0,0609
    XGBoost / LightGBM / Poisson ...........  peores que la constante
    multiplicativo ataque/defensa ..........  0,0634  (16 de 20 ligas positivas)

O sea que el 83 % de la señal disponible sigue sin capturar, y NO es por el
modelo: cinco estructuras distintas dan lo mismo. Si el cuello está en los
datos, la forma de comprobarlo es traer datos que el histórico no tiene.

FotMob publica por partido lo que football-data no: **posesión real, xG real,
ocasiones claras, tiros bloqueados y estadísticas defensivas**. Y a diferencia
de FBref —que devuelve 403 a un `requests` normal— es accesible: sus páginas
incrustan el JSON completo.

Coste medido: 1,69 s por partido. Una liga-temporada son 380 partidos, 11
minutos. Por eso este experimento se hace ANTES de plantear un backfill de 18
horas: si con una temporada la correlación no se mueve, no hay nada que
esperar de cinco.

Qué se mide
-----------
Se toma una liga-temporada de FotMob, se cruzan sus partidos con los córners
reales del histórico, y se comparan dos modelos sobre el MISMO tramo:

    A) las features que ya se tenían (córners y remates previos)
    B) A + las de FotMob (posesión, xG real, ocasiones claras, tiros)

La diferencia entre A y B es la respuesta. Se usa validación cruzada temporal
porque una temporada da poco tramo de juicio.

Uso:
    python _v157_fotmob_corners.py premier 2024/2025
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

import fotmob_scraper as fm
import league_engine as le

LIGA_IDS = fm.FOTMOB_LEAGUE_IDS


def partidos_temporada(clave, temporada):
    """Los partidos de UNA temporada concreta, con su id de FotMob."""
    par = LIGA_IDS.get(clave)
    if not par:
        return []
    lid, slug = par
    url = ('https://www.fotmob.com/leagues/%d/overview/%s?season=%s'
           % (lid, slug, temporada.replace('/', '%2F')))
    datos = fm._next_data(url)
    if not datos:
        return []
    ov = (datos.get('props', {}).get('pageProps', {}).get('overview') or {})
    salida = []
    for m in (ov.get('leagueOverviewMatches') or []):
        est = m.get('status') or {}
        if not est.get('finished'):
            continue
        salida.append({
            'match_id': str(m.get('id')),
            'fecha': str(est.get('utcTime') or '')[:10],
            'home': (m.get('home') or {}).get('name'),
            'away': (m.get('away') or {}).get('name'),
        })
    return salida


def detalles(lista, pausa=1.4, maximo=None):
    """Baja el detalle de cada partido, reutilizando la caché del scraper."""
    filas, t0 = [], time.time()
    for i, p in enumerate(lista[:maximo] if maximo else lista, 1):
        try:
            d = fm.detalle_partido(p['match_id'])
        except Exception:
            d = None
        if d:
            filas.append({**p, **{k: d.get(k) for k in (
                'posesion_h', 'posesion_a', 'xg_h', 'xg_a', 'tiros_h',
                'tiros_a', 'tiros_puerta_h', 'tiros_puerta_a',
                'ocasiones_claras_h', 'ocasiones_claras_a',
                'corners_h', 'corners_a')}})
        if i % 50 == 0:
            print('   %d/%d (%.0f s)' % (i, len(lista), time.time() - t0),
                  flush=True)
    return pd.DataFrame(filas)


COLS_BASE = ['ck_f_h', 'ck_c_h', 'ck_f_a', 'ck_c_a', 'sh_h', 'sh_a']
COLS_FM = ['pos_h', 'xg_h_ma', 'xg_a_ma', 'oc_h', 'oc_a', 'tir_h', 'tir_a']


def construir(df):
    """Medias móviles previas, de las dos familias, en un pase cronológico."""
    df = df.sort_values('fecha').reset_index(drop=True)
    hist = {}

    def H(eq):
        return hist.setdefault(eq, {k: [] for k in (
            'ck_f', 'ck_c', 'sh', 'pos', 'xg_f', 'xg_c', 'oc', 'tir')})

    def ma(s, n=6):
        return float(np.mean(s[-n:])) if len(s) >= 3 else None

    filas = []
    for f in df.itertuples(index=False):
        hh, ha = H(f.home), H(f.away)
        filas.append({
            'fecha': f.fecha, 'ck_total': f.ck_total,
            'ck_f_h': ma(hh['ck_f']), 'ck_c_h': ma(hh['ck_c']),
            'ck_f_a': ma(ha['ck_f']), 'ck_c_a': ma(ha['ck_c']),
            'sh_h': ma(hh['sh']), 'sh_a': ma(ha['sh']),
            'pos_h': ma(hh['pos']), 'oc_h': ma(hh['oc']), 'oc_a': ma(ha['oc']),
            'xg_h_ma': ma(hh['xg_f']), 'xg_a_ma': ma(ha['xg_f']),
            'tir_h': ma(hh['tir']), 'tir_a': ma(ha['tir']),
        })
        for d, cf, cc, sh, pos, xg, oc, tir in (
                (hh, f.corners_h, f.corners_a, f.tiros_h, f.posesion_h,
                 f.xg_h, f.ocasiones_claras_h, f.tiros_puerta_h),
                (ha, f.corners_a, f.corners_h, f.tiros_a, f.posesion_a,
                 f.xg_a, f.ocasiones_claras_a, f.tiros_puerta_a)):
            for clave, val in (('ck_f', cf), ('ck_c', cc), ('sh', sh),
                               ('pos', pos), ('xg_f', xg), ('oc', oc),
                               ('tir', tir)):
                try:
                    v = float(val)
                    if v == v:
                        d[clave].append(v)
                except (TypeError, ValueError):
                    pass
    return pd.DataFrame(filas)


def evalua(d, cols, semilla=7):
    """Validación temporal en 3 cortes: se entrena con el pasado, se juzga el
    futuro inmediato, y se acumulan las predicciones fuera de muestra."""
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler
    d = d.dropna(subset=cols + ['ck_total']).reset_index(drop=True)
    if len(d) < 150:
        return None
    preds, reales = [], []
    for q in (0.55, 0.70, 0.85):
        corte = int(len(d) * q)
        tr, te = d.iloc[:corte], d.iloc[corte:int(len(d) * (q + 0.15))]
        if len(tr) < 80 or len(te) < 25:
            continue
        esc = StandardScaler().fit(tr[cols])
        m = RidgeCV(alphas=np.logspace(-2, 3, 20)).fit(
            esc.transform(tr[cols]), tr['ck_total'])
        preds += list(m.predict(esc.transform(te[cols])))
        reales += list(te['ck_total'])
    if len(preds) < 60:
        return None
    p, y = np.array(preds), np.array(reales)
    cte = float(np.mean(y))
    return {'n': len(y),
            'corr': round(float(np.corrcoef(p, y)[0, 1]), 4),
            'mae': round(float(np.mean(np.abs(y - p))), 4),
            'mae_cte': round(float(np.mean(np.abs(y - cte))), 4)}


def main():
    # VARIAS TEMPORADAS, y no una. Con 380 partidos el tramo de juicio queda en
    # ~159 y el error estándar de una correlación es 1/sqrt(159) = 0,079: una
    # ganancia de 0,03 no se distingue de cero. Medido así, el primer intento
    # dio +0,0032 y no significaba nada. La caché del scraper hace que repetir
    # una temporada ya bajada sea gratis, así que acumular es barato.
    clave = sys.argv[1] if len(sys.argv) > 1 else 'premier'
    temporadas = sys.argv[2:] or ['2024/2025']
    lista = []
    for t in temporadas:
        p = partidos_temporada(clave, t)
        print('%s · %s -> %d partidos' % (clave, t, len(p)), flush=True)
        lista += p
    print('total: %d' % len(lista), flush=True)
    if not lista:
        return
    df = detalles(lista)
    print('con detalle: %d' % len(df), flush=True)
    if df.empty:
        return
    df['ck_total'] = (pd.to_numeric(df['corners_h'], errors='coerce')
                      + pd.to_numeric(df['corners_a'], errors='coerce'))
    df = df.dropna(subset=['ck_total'])
    print('con córners: %d' % len(df), flush=True)

    d = construir(df)
    base = evalua(d, COLS_BASE)
    todo = evalua(d, COLS_BASE + COLS_FM)
    print()
    print('SOLO features del histórico :', json.dumps(base, ensure_ascii=False))
    print('CON variables de FotMob     :', json.dumps(todo, ensure_ascii=False))
    if base and todo:
        print()
        print('ganancia de correlación: %+.4f  (%.4f -> %.4f)'
              % (todo['corr'] - base['corr'], base['corr'], todo['corr']))
        json.dump({'liga': clave, 'temporadas': temporadas,
                   'base': base, 'con_fotmob': todo},
                  open('_v157_fotmob_corners.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
