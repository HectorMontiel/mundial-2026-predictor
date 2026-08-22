#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v152 — EL SESGO DE LA FÓRMULA DE CÓRNERS, MEDIDO COMO HABÍA QUE MEDIRLO.

Qué corrige de la v146
----------------------
La v146 midió el sesgo alimentando `ck = 4.0 + 0.25·(lam_h+lam_a)·spx·tpo` con
el xG **OBSERVADO** del histórico. Producción la alimenta con `lam_h`/`lam_a`,
que son el xG **PREDICHO** por el regresor de goles del motor. No son la misma
magnitud y el sesgo de una no se traslada a la otra, así que la corrección se
revirtió sin poder afirmar cuál era el número bueno.

Aquí la fórmula se alimenta con los lambdas que produce el propio motor, que es
la única entrada que existe en producción.

Lo que esta medición SÍ puede decidir
-------------------------------------
El NIVEL: si la constante 4,0 deja el total medio por encima o por debajo de los
córners reales de la liga. Es una calibración de media, y la media de `lam` no
depende de la fuga temporal (el regresor de goles está entrenado para acertar el
nivel, y el script comprueba ese supuesto imprimiendo lam_tot vs goles reales).

Lo que NO puede decidir
-----------------------
La DISCRIMINACIÓN partido a partido. `predecir` usa el estado ACTUAL de cada
equipo, no el que tenían el día del partido histórico, así que la correlación
que salga aquí es optimista y NO se usa para decidir nada. Se imprime sólo para
saber si hay señal que perseguir.

Los córners son REALES
----------------------
football-data publica HC/AC. El script comprueba la cobertura contra el CSV
crudo antes de medir: si una liga trae córners rellenados por el generador
sintético, se excluye — medir el sesgo de una fórmula contra su propio relleno
no diría nada.
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

LIGAS = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'eredivisie',
         'primeira', 'turquia', 'gre_super_league', 'eng_league_one',
         'eng_league_two', 'sco_premiership', 'esp_hypermotion', 'ita_serie_b',
         'fra_ligue2']

CAL = statsbomb_calibration.calibrar()
SPX = float(CAL.get('shots_on_por_xg', 3.1))
TPO = float(CAL.get('shots_total_por_on', 2.6))
BASE_ACTUAL = 4.0


def ck_formula(lam_h, lam_a, base=BASE_ACTUAL):
    """La fórmula de producción, tal cual está en league_engine (sección 11)."""
    return base + 0.25 * (np.asarray(lam_h) + np.asarray(lam_a)) * SPX * TPO


def corners_reales_del_crudo(clave):
    """
    Fracción de filas con HC/AC en el CSV CRUDO de football-data.

    Sin esto no se sabe si `home_corners` viene de la fuente o lo puso el
    generador sintético: `generate_advanced_metrics` hace `fillna`, así que las
    dos cosas llegan al dataframe indistinguibles.
    """
    cfg = LEAGUES[clave]
    if cfg.get('formato') != 'main':
        return None
    filas, con_ck = 0, 0
    # La configuración lleva las URLs completas (`temporadas_fd` las deriva de
    # la fecha desde la v148); las tres últimas son las tres temporadas que
    # `descargar_liga(temporadas=3)` acaba usando para entrenar.
    for url in list(cfg.get('urls') or [])[-3:]:
        try:
            hoja = le._csv_temporada(url, clave)
        except Exception:
            hoja = None
        if hoja is None or hoja.empty:
            continue
        filas += len(hoja)
        if 'HC' in hoja.columns and 'AC' in hoja.columns:
            con_ck += int((pd.to_numeric(hoja['HC'], errors='coerce').notna() &
                           pd.to_numeric(hoja['AC'], errors='coerce').notna()).sum())
    return (con_ck / filas) if filas else None


def mide_liga(clave):
    t0 = time.time()
    cob = corners_reales_del_crudo(clave)
    if not cob or cob < 0.90:
        txt = 'n/d' if cob is None else ('%.0f %%' % (cob * 100))
        return {'liga': clave, 'excluida': True,
                'motivo': 'cornersreales en el crudo: ' + txt}
    df = le.descargar_liga(clave, temporadas=3)
    df = df.dropna(subset=['home_corners', 'away_corners'])
    if len(df) < 200:
        return {'liga': clave, 'excluida': True,
                'motivo': 'solo %d partidos con corners' % len(df)}
    eng = le.ClubEngine(clave)
    if not eng.listo:
        return {'liga': clave, 'excluida': True, 'motivo': 'motor: %s' % eng.error}

    # Un `predecir` por PAR único, no por partido: la predicción de producción
    # depende del par y del estado actual, no de la fecha del partido pasado.
    pares = df[['home_team', 'away_team']].drop_duplicates()
    lam = {}
    for h, a in pares.itertuples(index=False):
        try:
            p = eng.predecir(h, a, prior_elo=False)
            if 'error' in p:
                continue
            eg = p['prediction']['expected_goals']
            lam[(h, a)] = (float(eg['home']), float(eg['away']))
        except Exception:
            continue
    if len(lam) < 100:
        return {'liga': clave, 'excluida': True,
                'motivo': 'solo %d pares predichos' % len(lam)}

    filas = []
    for f in df.itertuples(index=False):
        v = lam.get((f.home_team, f.away_team))
        if not v:
            continue
        filas.append({
            'lam_h': v[0], 'lam_a': v[1], 'lam_tot': v[0] + v[1],
            'ck_real': float(f.home_corners) + float(f.away_corners),
            'g_real': float(f.home_goals) + float(f.away_goals),
        })
    d = pd.DataFrame(filas)
    if len(d) < 200:
        return {'liga': clave, 'excluida': True, 'motivo': 'n=%d' % len(d)}

    d['ck_pred'] = ck_formula(d['lam_h'], d['lam_a'])
    sesgo = float((d['ck_pred'] - d['ck_real']).mean())
    # La base que dejaría el nivel calibrado, dejando el resto de la fórmula
    # intacto: base* = media(real) − media(parte variable)
    variable = 0.25 * d['lam_tot'] * SPX * TPO
    base_cal = float(d['ck_real'].mean() - variable.mean())
    # ¿Y si además la pendiente está mal? Regresión real ~ a + b·lam_tot
    b, a = np.polyfit(d['lam_tot'], d['ck_real'], 1)
    return {
        'liga': clave, 'excluida': False, 'n': int(len(d)),
        'cobertura_ck_crudo': round(cob, 4),
        'ck_real_media': round(float(d['ck_real'].mean()), 3),
        'ck_real_sd': round(float(d['ck_real'].std()), 3),
        'ck_pred_media': round(float(d['ck_pred'].mean()), 3),
        'sesgo': round(sesgo, 3),
        'mae': round(float((d['ck_pred'] - d['ck_real']).abs().mean()), 3),
        'corr_optimista': round(float(np.corrcoef(d['ck_pred'], d['ck_real'])[0, 1]), 4),
        'base_calibrada': round(base_cal, 3),
        'reg_a': round(float(a), 3), 'reg_b': round(float(b), 3),
        'lam_tot_media': round(float(d['lam_tot'].mean()), 3),
        'g_real_media': round(float(d['g_real'].mean()), 3),
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
    if ok:
        n = sum(r['n'] for r in ok)
        # ponderado por n: una liga de 1.100 partidos no vale lo mismo que una
        # de 220
        sesgo = sum(r['sesgo'] * r['n'] for r in ok) / n
        base = sum(r['base_calibrada'] * r['n'] for r in ok) / n
        real = sum(r['ck_real_media'] * r['n'] for r in ok) / n
        pred = sum(r['ck_pred_media'] * r['n'] for r in ok) / n
        lamt = sum(r['lam_tot_media'] * r['n'] for r in ok) / n
        gol = sum(r['g_real_media'] * r['n'] for r in ok) / n
        resumen = {
            'ligas_ok': len(ok), 'n_total': n,
            'ck_real_media': round(real, 3), 'ck_pred_media': round(pred, 3),
            'sesgo_ponderado': round(sesgo, 3),
            'base_calibrada_ponderada': round(base, 3),
            'lam_tot_media': round(lamt, 3), 'goles_reales_media': round(gol, 3),
            'sesgo_del_regresor_de_goles': round(lamt - gol, 3),
        }
        print('\nRESUMEN ' + json.dumps(resumen, ensure_ascii=False), flush=True)
        json.dump({'ligas': res, 'resumen': resumen},
                  open('_v152_corners_sesgo.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
