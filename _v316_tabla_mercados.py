# -*- coding: utf-8 -*-
"""
v316 — ¿LA TABLA AYUDA TAMBIÉN EN LOS GOLES DE CADA EQUIPO Y EN LOS CÓRNERS?

El usuario: «¿por qué sobre esto no se mide también la probabilidad de gol de
equipo individual? ¿Córners? ¿Mitades? Para eso también ayuda la tabla, la
clasificación, ver la diferencia de goles, cuánto anotó, y analizar el patrón,
no sólo en esa liga sino en todas».

QUÉ SE AÑADE A LO QUE YA MIRABA `patrones_liga`
La tabla de la TEMPORADA de cada equipo antes del partido:
    · diferencia de goles por partido,
    · goles a favor y en contra por partido,
    · posición (0 = último, 1 = líder),
    · puntos a la zona de arriba y al descenso, avance, decisivo/nada en juego,
    · % de partidos con 4+ goles.

DOS PRUEBAS, EN TODAS LAS LIGAS
1. GOLES POR EQUIPO (el ledger de 80.829 partidos, 61 ligas, fuera de
   muestra): que marque el local, que marque el visitante, que el local meta
   2+, que el visitante meta 2+. «Siempre» = el corrector de `patrones_liga`
   con sus rasgos (forma de 10 y 5 partidos, casa/fuera, puntos por
   partido); «+ tabla» = eso más la tabla de la temporada.
2. CÓRNERS (67 ligas con córners reales en su histórico): total más de 8,5 /
   9,5 / 10,5; local más de 4,5; visitante más de 3,5. «Siempre» = los
   córners a favor y en contra de cada equipo (media de los 8 últimos, casa y
   fuera, y media exponencial) y la media de la liga; «+ tabla» = eso más la
   tabla de goles de la temporada.

Igual que `patrones_liga.entrenar`: LightGBM en el 70 % antiguo, juicio en
el 30 % reciente, bootstrap 2.000 del log-loss. Se adopta sólo si «+ tabla»
le gana a «siempre» con p5 > 0. Además, el ACIERTO de lo que se ofrecería
(el lado con 70 % o más) en el tramo de juicio, con y sin la tabla.

Uso: python _v316_tabla_mercados.py   (escribe _v316_tabla_mercados.json)
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict, deque

import numpy as np
import pandas as pd

TABLA = ['gdpj_h', 'gdpj_a', 'gfpj_h', 'gcpj_h', 'gfpj_a', 'gcpj_a',
         'pos_h', 'pos_a', 'p4_h', 'p4_a', 'gap_top_h', 'gap_bot_h',
         'gap_top_a', 'gap_bot_a', 'prog', 'decisivo_ambos', 'nada_en_juego']
CORNERS = ['ck_f_h', 'ck_c_h', 'ck_f_a', 'ck_c_a', 'ck_casa_f_h',
           'ck_casa_c_h', 'ck_fuera_f_a', 'ck_fuera_c_a', 'ck_ew_f_h',
           'ck_ew_c_h', 'ck_ew_f_a', 'ck_ew_c_a', 'liga_ck_h', 'liga_ck_a']
OBJ_EQUIPO = {'marca_local': ('marca_h', 'p_marca_h'),
              'marca_visitante': ('marca_v', 'p_marca_v'),
              'local_mas15': ('local_2', 'p_local_2'),
              'visit_mas15': ('visit_2', 'p_visit_2')}
OBJ_CORNERS = {'total_mas_8.5': ('t', 8.5), 'total_mas_9.5': ('t', 9.5),
               'total_mas_10.5': ('t', 10.5), 'local_mas_4.5': ('h', 4.5),
               'visit_mas_3.5': ('a', 3.5)}
FUERA = {'partidos', 'leagues_cup'}          # agregados, no una liga


def _tabla_ext():
    """La tabla de `patrones_liga`, que desde esta medición ya lleva la
    diferencia de goles, a favor/en contra por partido y la posición de la
    temporada (RASGOS_TABLA). Al medir era una subclase con eso mismo."""
    import patrones_liga as pl
    return pl.Tabla


# ------------------------------------------------------------------ córners
def _corners_liga(ruta, TablaExt, copa):
    d = pd.read_csv(ruta, low_memory=False, usecols=lambda c: c in (
        'date', 'home_team', 'away_team', 'home_goals', 'away_goals',
        'home_corners', 'away_corners'))
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date', 'home_team', 'away_team', 'home_goals',
                         'away_goals']).sort_values('date')
    t = TablaExt(copa=copa)
    f8 = defaultdict(lambda: deque(maxlen=8))
    c8 = defaultdict(lambda: deque(maxlen=8))
    cf, cc = defaultdict(lambda: deque(maxlen=5)), defaultdict(lambda: deque(maxlen=5))
    ff, fc = defaultdict(lambda: deque(maxlen=5)), defaultdict(lambda: deque(maxlen=5))
    ewf, ewc = {}, {}
    lh, la = deque(maxlen=300), deque(maxlen=300)
    m = lambda q: float(np.mean(q)) if len(q) >= 3 else np.nan
    filas = []
    for r in d.itertuples(index=False):
        h, a = r.home_team, r.away_team
        ch, ca = r.home_corners, r.away_corners
        tiene = ch == ch and ca == ca
        if tiene and len(lh) >= 50 and len(f8[h]) >= 3 and len(f8[a]) >= 3:
            f = t.rasgos(h, a, r.date)
            f.update({'fecha': r.date, 'ch': ch, 'ca': ca,
                      'ck_f_h': m(f8[h]), 'ck_c_h': m(c8[h]),
                      'ck_f_a': m(f8[a]), 'ck_c_a': m(c8[a]),
                      'ck_casa_f_h': m(cf[h]), 'ck_casa_c_h': m(cc[h]),
                      'ck_fuera_f_a': m(ff[a]), 'ck_fuera_c_a': m(fc[a]),
                      'ck_ew_f_h': ewf.get(h, np.nan), 'ck_ew_c_h': ewc.get(h, np.nan),
                      'ck_ew_f_a': ewf.get(a, np.nan), 'ck_ew_c_a': ewc.get(a, np.nan),
                      'liga_ck_h': float(np.mean(lh)), 'liga_ck_a': float(np.mean(la))})
            filas.append(f)
        t.sumar(h, a, r.date, float(r.home_goals), float(r.away_goals))
        if tiene:
            for eq, x, y, fq, cq in ((h, ch, ca, cf, cc), (a, ca, ch, ff, fc)):
                f8[eq].append(x); c8[eq].append(y)
                fq[eq].append(x); cq[eq].append(y)
                ewf[eq] = x if eq not in ewf else .25 * x + .75 * ewf[eq]
                ewc[eq] = y if eq not in ewc else .25 * y + .75 * ewc[eq]
            lh.append(ch); la.append(ca)
    return pd.DataFrame(filas)


def conjunto_corners():
    import patrones_liga as pl
    TablaExt = _tabla_ext()
    partes = []
    for ruta in sorted(glob.glob('historico_*.csv')):
        liga = ruta[len('historico_'):-4]
        if liga in FUERA:
            continue
        try:
            cols = pd.read_csv(ruta, nrows=1).columns
            if 'home_corners' not in cols:
                continue
            x = _corners_liga(ruta, TablaExt, liga in pl.COPAS)
        except Exception as e:
            print('  fallo', liga, e)
            continue
        if len(x) >= 250:
            x['liga'] = liga
            partes.append(x)
    df = pd.concat(partes, ignore_index=True).sort_values('fecha').reset_index(drop=True)
    # λ base: lo que suele sacar cada uno y lo que suele conceder el rival
    df['lam_ch'] = (df['ck_casa_f_h'].fillna(df['ck_f_h']) + df['ck_fuera_c_a'].fillna(df['ck_c_a'])) / 2
    df['lam_ca'] = (df['ck_fuera_f_a'].fillna(df['ck_f_a']) + df['ck_casa_c_h'].fillna(df['ck_c_h'])) / 2
    return df


def _p_poisson_mas(lam, L):
    from scipy.stats import poisson
    return 1 - poisson.cdf(np.floor(L), lam)


# ------------------------------------------------------------------ prueba
def _prueba(e, j, y_col, base_col, r_siempre, r_tabla, codigos, rng):
    import lightgbm as lgb
    import patrones_liga as pl

    def X(d, rasgos):
        x = d[[c for c in rasgos if c not in ('liga_cod', 'logit_modelo')]].astype(float).copy()
        x['liga_cod'] = d['liga'].map(codigos).fillna(-1).astype(int)
        x['logit_modelo'] = pl._logit(d[base_col])
        return x[rasgos]
    y = j[y_col].astype(int).to_numpy()
    preds = {}
    for etq, rasgos in (('siempre', r_siempre), ('+ tabla', r_tabla)):
        bst = lgb.train(pl.PARAMS, lgb.Dataset(X(e, rasgos), label=e[y_col].astype(int),
                                               categorical_feature=['liga_cod']),
                        num_boost_round=pl.RONDAS)
        preds[etq] = bst.predict(X(j, rasgos))
    p_cal = pl._base_calibrada(e, j, y_col, base_col)
    idx = rng.integers(0, len(y), size=(2000, len(y)))
    out = {'n_juicio': int(len(y)), 'tasa_real': round(float(y.mean()), 4),
           'log-loss base calibrada': round(float(pl._ll(y, p_cal).mean()), 5)}
    for etq, p in preds.items():
        ll = pl._ll(y, p)
        d0 = pl._ll(y, p_cal) - ll
        # lo que se ofrecería: el lado con 70 % o más
        lado = np.maximum(p, 1 - p) >= .70
        acierto = np.where(p >= .5, y, 1 - y)[lado]
        r = {'log-loss': round(float(ll.mean()), 5),
             'mejora_vs_base': round(float(d0.mean()), 5),
             'p5_vs_base': round(float(np.percentile(d0[idx].mean(axis=1), 5)), 5),
             'ofrecidas_70': int(lado.sum()),
             'acierto_70': round(float(acierto.mean()), 4) if lado.any() else None}
        if etq != 'siempre':
            d1 = pl._ll(y, preds['siempre']) - ll
            r['mejora_vs_siempre'] = round(float(d1.mean()), 5)
            r['p5_vs_siempre'] = round(float(np.percentile(d1[idx].mean(axis=1), 5)), 5)
            r['adopta'] = bool(d1.mean() > 0 and r['p5_vs_siempre'] > 0)
        out[etq] = r
    return out


def main():
    import patrones_liga as pl
    rng = np.random.default_rng(316)
    out = {}

    # 1. goles por equipo
    Tabla0 = pl.Tabla
    pl.Tabla = _tabla_ext()
    try:
        df = pl.conjunto()
    finally:
        pl.Tabla = Tabla0
    ligas = sorted(df['liga'].unique())
    codigos = {l: i for i, l in enumerate(ligas)}
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    ele, jui = df[df['fecha'] < corte], df[df['fecha'] >= corte]
    out['goles_equipo'] = {'n': int(len(df)), 'ligas': len(ligas), 'corte': str(corte.date())}
    for nombre, (y_col, p_col) in OBJ_EQUIPO.items():
        e, j = ele.dropna(subset=[y_col, p_col]), jui.dropna(subset=[y_col, p_col])
        r_s = list(pl.RASGOS_V1)
        r_t = r_s[:-2] + TABLA + ['liga_cod', 'logit_modelo']
        out['goles_equipo'][nombre] = _prueba(e, j, y_col, p_col, r_s, r_t, codigos, rng)
        print(nombre, json.dumps(out['goles_equipo'][nombre], ensure_ascii=False), flush=True)

    # 2. córners
    ck = conjunto_corners()
    ligas = sorted(ck['liga'].unique())
    codigos = {l: i for i, l in enumerate(ligas)}
    corte = ck['fecha'].iloc[int(len(ck) * 0.70)]
    out['corners'] = {'n': int(len(ck)), 'ligas': len(ligas), 'corte': str(corte.date()),
                      'por_liga': {k: int(v) for k, v in ck['liga'].value_counts().items()}}
    ck['t'] = ck['ch'] + ck['ca']
    ck['h'], ck['a'] = ck['ch'], ck['ca']
    ele, jui = ck[ck['fecha'] < corte], ck[ck['fecha'] >= corte]
    goles_tabla = ['ppg_h', 'ppg_a', 'gf_h', 'gc_h', 'gf_a', 'gc_a', 'pct_h', 'pct_a']
    for nombre, (col, L) in OBJ_CORNERS.items():
        lam = {'t': ck['lam_ch'] + ck['lam_ca'], 'h': ck['lam_ch'], 'a': ck['lam_ca']}[col]
        ck['y_'] = (ck[col] > L).astype(int)
        ck['p_'] = _p_poisson_mas(lam, L)
        e, j = ck.loc[ele.index].dropna(subset=['p_']), ck.loc[jui.index].dropna(subset=['p_'])
        r_s = CORNERS + ['liga_cod', 'logit_modelo']
        r_t = CORNERS + goles_tabla + TABLA + ['liga_cod', 'logit_modelo']
        out['corners'][nombre] = _prueba(e, j, 'y_', 'p_', r_s, r_t, codigos, rng)
        print(nombre, json.dumps(out['corners'][nombre], ensure_ascii=False), flush=True)
    json.dump(out, open('_v316_tabla_mercados.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
