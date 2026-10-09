#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v344 — ¿La metodología del usuario predice mejor los TIROS por equipo?

El usuario (transcripción de un amigo que acertó en la liga brasileña): «no
basta con los últimos cinco partidos o el promedio: en un partido hizo 4 tiros
y en otro 31. Hay que ver en qué posición están en la tabla (a quién le sirve
ganar), cuántos goles reciben y anotan, cuánto retienen el balón (si lo
retienen mucho no te tiran), los córners, las tarjetas, si el rival hace
muchas faltas (eso da tiros libres, córners y tiros), y la plantilla».

Cada idea se convierte en una variable medible ANTES del partido (sólo con
partidos anteriores: sin fuga), y se compara contra dos referencias:

    B1  últimos 5 del equipo en la misma condición (lo que critica)
    B2  ataque del equipo × defensa del rival en la temporada (encogido)
    N   LightGBM Poisson con TODO lo de la metodología
    N-  el mismo sin la tabla ni la posesión ni las faltas (para saber qué
        aporta cada parte)

Objetivos: tiros totales del equipo (a puerta + fuera) y tiros a puerta.
Datos: `historico_*.csv` con estadísticas REALES de ESPN (43 ligas,
2021-2026). Elige con el 70 % de fechas más viejo, juzga con el 30 %.
Métrica: log-loss de «más de» en las líneas típicas, con una binomial
negativa ajustada en el tramo de elegir; bootstrap por partido.
"""
import glob
import json
import sys

import numpy as np
import pandas as pd
from scipy import stats

rng = np.random.default_rng(344)
CACHE = '_v344_filas.pkl'
LINEAS = {'tiros': [8.5, 10.5, 12.5, 14.5], 'a_puerta': [2.5, 3.5, 4.5, 5.5]}
COPAS = ('afc_champions', 'champions', 'conference_league', 'europa_league',
         'libertadores', 'sudamericana', 'selecciones')
# ligas de torneos cortos: la tabla es por semestre
SEMESTRE = ('liga_mx', 'col_primera_a', 'chi_primera', 'per_liga1')
CALENDARIO = ('brasil', 'bra_serie_b', 'mls', 'usl_championship', 'china',
              'jpn_j1', 'suecia', 'noruega', 'ksa_pro', 'ind_isl')


def temporada(liga, f):
    if liga in SEMESTRE:
        return '%d-%d' % (f.year, 1 if f.month <= 6 else 2)
    if liga in CALENDARIO:
        return str(f.year)
    return str(f.year if f.month >= 7 else f.year - 1)


def cargar():
    filas = []
    for ruta in sorted(glob.glob('historico_*.csv')):
        liga = ruta[len('historico_'):-4]
        try:
            d = pd.read_csv(ruta, low_memory=False)
        except Exception:
            continue
        need = {'stats_origen', 'home_shots_on', 'home_shots_off',
                'home_possession', 'home_fouls'}
        if not need <= set(d.columns):
            continue
        d = d[(d.stats_origen == 'espn') & d.home_shots_on.notna()
              & d.away_shots_on.notna() & d.home_possession.notna()].copy()
        if len(d) < 300:
            continue
        d['fecha'] = pd.to_datetime(d['date'], errors='coerce')
        d = d.dropna(subset=['fecha', 'home_goals', 'away_goals'])
        d['liga'] = liga
        filas.append(d)
    d = pd.concat(filas, ignore_index=True).sort_values('fecha')
    d['mid'] = np.arange(len(d))
    return d


def a_equipos(d):
    """Una fila por equipo y partido (el equipo y su rival)."""
    out = []
    for lado, otro in (('home', 'away'), ('away', 'home')):
        x = pd.DataFrame({
            'mid': d.mid, 'fecha': d.fecha, 'liga': d.liga,
            'equipo': d['%s_team' % lado], 'rival': d['%s_team' % otro],
            'local': int(lado == 'home'),
            'tiros': d['%s_shots_on' % lado] + d['%s_shots_off' % lado],
            'a_puerta': d['%s_shots_on' % lado],
            'tiros_c': d['%s_shots_on' % otro] + d['%s_shots_off' % otro],
            'a_puerta_c': d['%s_shots_on' % otro],
            'gf': d['%s_goals' % lado], 'gc': d['%s_goals' % otro],
            'pos': d['%s_possession' % lado],
            'faltas': d['%s_fouls' % lado], 'faltas_r': d['%s_fouls' % otro],
            'corners': d['%s_corners' % lado], 'corners_c': d['%s_corners' % otro],
            'amarillas': d['%s_yellow' % lado],
            'odd_w': d['odd_%s_pin' % lado].fillna(d['odd_%s' % lado]),
            'odd_d': d['odd_draw_pin'].fillna(d['odd_draw']),
            'odd_l': d['odd_%s_pin' % otro].fillna(d['odd_%s' % otro]),
        })
        out.append(x)
    e = pd.concat(out, ignore_index=True).sort_values(['fecha', 'mid'])
    e['temporada'] = [temporada(l, f) for l, f in zip(e.liga, e.fecha)]
    e['pts'] = np.where(e.gf > e.gc, 3, np.where(e.gf == e.gc, 1, 0))
    return e


def rasgos(e):
    """Lo que se sabía de cada equipo ANTES del partido (shift(1))."""
    e = e.sort_values(['fecha', 'mid']).copy()
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    stats_ = ['tiros', 'a_puerta', 'tiros_c', 'a_puerta_c', 'gf', 'gc', 'pos',
              'faltas', 'faltas_r', 'corners', 'corners_c', 'amarillas']
    e['n_prev'] = g.cumcount()
    for c in stats_:
        s = g[c].transform(lambda x: x.shift(1).expanding().mean())
        e['t_' + c] = s
        e['l5_' + c] = g[c].transform(lambda x: x.shift(1).rolling(5, 1).mean())
    # la referencia que critica el usuario: últimos 5 en la misma condición
    gv = e.groupby(['liga', 'temporada', 'equipo', 'local'], sort=False)
    e['b1_tiros'] = gv['tiros'].transform(lambda x: x.shift(1).rolling(5, 1).mean())
    e['b1_a_puerta'] = gv['a_puerta'].transform(lambda x: x.shift(1).rolling(5, 1).mean())
    # la tabla antes del partido
    e['pts_prev'] = g['pts'].transform(lambda x: x.shift(1).cumsum()).fillna(0)
    e['ppg'] = e.pts_prev / e.n_prev.replace(0, np.nan)
    e['dg_prev'] = g.apply(lambda x: (x.gf - x.gc).shift(1).cumsum()).reset_index(
        level=[0, 1, 2], drop=True).reindex(e.index).fillna(0)
    # posición: rango por puntos (y dif. de goles) entre los equipos de esa
    # liga-temporada con su último registro anterior a esta fecha
    e = e.sort_values(['fecha', 'mid'])
    posiciones = np.full(len(e), np.nan)
    tamano = np.full(len(e), np.nan)
    for (_, _), idx in e.groupby(['liga', 'temporada']).groups.items():
        sub = e.loc[idx].sort_values(['fecha', 'mid'])
        tabla = {}
        for fecha, bloque in sub.groupby('fecha', sort=True):
            orden = sorted(tabla.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
            rango = {k: i + 1 for i, (k, _) in enumerate(orden)}
            n = max(len(tabla), 1)
            for i, r in bloque.iterrows():
                posiciones[e.index.get_loc(i)] = rango.get(r.equipo, np.nan)
                tamano[e.index.get_loc(i)] = n
            for i, r in bloque.iterrows():
                p, dg = tabla.get(r.equipo, (0, 0))
                tabla[r.equipo] = (p + r.pts, dg + r.gf - r.gc)
    e['posicion'] = posiciones
    e['pos_rel'] = e.posicion / pd.Series(tamano, index=e.index)
    e['zona_baja'] = (e.pos_rel >= 0.80).astype(float)
    e['zona_alta'] = (e.pos_rel <= 0.30).astype(float)
    # el precio: la fuerza (la «plantilla») según Pinnacle, sin margen
    inv = 1 / e[['odd_w', 'odd_d', 'odd_l']]
    s = inv.sum(axis=1)
    e['p_gana'] = inv.odd_w / s
    e['p_pierde'] = inv.odd_l / s
    return e


def con_rival(e):
    """Pega a cada fila lo que se sabía del RIVAL antes del partido."""
    cols = [c for c in e.columns if c.startswith(('t_', 'l5_'))] + [
        'ppg', 'pos_rel', 'zona_baja', 'zona_alta', 'n_prev', 'posicion']
    r = e[['mid', 'equipo'] + cols].rename(
        columns={c: 'r_' + c for c in cols}).rename(columns={'equipo': 'rival'})
    return e.merge(r, on=['mid', 'rival'], how='left')


def preparar():
    try:
        return pd.read_pickle(CACHE)
    except Exception:
        pass
    d = cargar()
    print('partidos', len(d), 'ligas', d.liga.nunique())
    e = con_rival(rasgos(a_equipos(d)))
    e.to_pickle(CACHE)
    return e


def media_liga(e, c):
    return e.groupby(['liga', 'temporada', 'local'])[c].transform(
        lambda x: x.shift(1).expanding().mean())


F_TODO = None


def columnas(e, sin_metodologia=False):
    base = ['local', 't_tiros', 't_a_puerta', 'r_t_tiros_c', 'r_t_a_puerta_c',
            'l5_tiros', 'l5_a_puerta', 'r_l5_tiros_c', 'r_l5_a_puerta_c',
            't_gf', 't_gc', 'r_t_gf', 'r_t_gc', 'n_prev', 'r_n_prev',
            'liga_tiros', 'liga_a_puerta']
    met = ['t_pos', 'r_t_pos', 'l5_pos', 'r_l5_pos', 'r_t_faltas', 't_faltas_r',
           't_corners', 'r_t_corners_c', 'r_t_amarillas', 't_amarillas',
           'ppg', 'r_ppg', 'pos_rel', 'r_pos_rel', 'zona_baja', 'zona_alta',
           'r_zona_baja', 'r_zona_alta', 'p_gana', 'p_pierde']
    return base if sin_metodologia else base + met


def nb_sf(lam, linea, k):
    """P(X > linea) con binomial negativa de media lam y tamaño k."""
    p = k / (k + lam)
    return stats.nbinom.sf(np.floor(linea), k, p)


def ajustar_k(y, lam):
    """Tamaño de la binomial negativa por momentos (var = mu + mu²/k)."""
    v = np.mean((y - lam) ** 2 - lam)
    m2 = np.mean(lam ** 2)
    return float(np.clip(m2 / max(v, 1e-6), 2, 500))


def evaluar(objetivo):
    import lightgbm as lgb
    e = preparar()
    e = e[~e.liga.isin(COPAS)].copy()
    e['liga_tiros'] = media_liga(e, 'tiros')
    e['liga_a_puerta'] = media_liga(e, 'a_puerta')
    e = e[(e.n_prev >= 3) & (e.r_n_prev >= 3)].dropna(
        subset=['b1_' + objetivo, 't_' + objetivo, 'liga_' + objetivo,
                'p_gana']).copy()
    corte = e.fecha.quantile(0.70)
    el, ju = e[e.fecha < corte], e[e.fecha >= corte]
    y_el, y_ju = el[objetivo].values, ju[objetivo].values
    # B2: ataque × defensa, encogidos hacia la liga con n=5 partidos
    def b2(x):
        a = (x['t_' + objetivo] * x.n_prev + x['liga_' + objetivo] * 5) / (x.n_prev + 5)
        dfn = (x['r_t_%s_c' % objetivo] * x.r_n_prev + x['liga_' + objetivo] * 5) / (x.r_n_prev + 5)
        return (a * dfn / x['liga_' + objetivo]).values
    preds = {'B1 últimos 5 (misma condición)': (el['b1_' + objetivo].values,
                                                 ju['b1_' + objetivo].values),
             'B2 ataque × defensa': (b2(el), b2(ju))}
    imp = {}
    for nombre, sin in (('N- sin tabla/posesión/faltas', True),
                        ('N metodología completa', False)):
        cols = columnas(e, sin)
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=600,
                              learning_rate=0.03, num_leaves=31,
                              min_child_samples=80, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8,
                              verbose=-1, random_state=344)
        # para no sobreajustar el tramo de elegir: se entrena en su 80 % viejo
        # y la dispersión se ajusta en su 20 % reciente
        c2 = el.fecha.quantile(0.80)
        a, b = el[el.fecha < c2], el[el.fecha >= c2]
        m.fit(a[cols], a[objetivo])
        lam_b = m.predict(b[cols])
        m.fit(el[cols], y_el)
        preds[nombre] = (np.r_[m.predict(a[cols]) * 0 + np.nan, lam_b] if False
                         else m.predict(el[cols]), m.predict(ju[cols]))
        if not sin:
            imp = dict(sorted(zip(cols, m.booster_.feature_importance('gain')),
                              key=lambda kv: -kv[1])[:15])
    res = {'n_elige': int(len(el)), 'n_juzga': int(len(ju)),
           'corte': str(corte.date()), 'modelos': {}}
    ll_por = {}
    for nombre, (lam_el, lam_ju) in preds.items():
        lam_el = np.clip(np.nan_to_num(lam_el, nan=np.nanmean(y_el)), 0.3, None)
        lam_ju = np.clip(np.nan_to_num(lam_ju, nan=np.nanmean(y_el)), 0.3, None)
        k = ajustar_k(y_el, lam_el)
        fila = {'k': round(k, 1), 'mae_juzga': round(float(np.mean(np.abs(y_ju - lam_ju))), 3)}
        ll_tot = np.zeros(len(ju))
        for L in LINEAS[objetivo]:
            p = np.clip(nb_sf(lam_ju, L, k), 1e-4, 1 - 1e-4)
            yb = (y_ju > L).astype(float)
            ll = -(yb * np.log(p) + (1 - yb) * np.log(1 - p))
            ll_tot += ll
            fila['ll_%.1f' % L] = round(float(ll.mean()), 4)
            # «meter»: 70 % o más hacia un lado
            sel = (p >= 0.70) | (p <= 0.30)
            ac = np.where(p >= 0.5, yb, 1 - yb)[sel]
            fila['meter_%.1f' % L] = [int(sel.sum()), round(float(ac.mean()), 4) if sel.any() else None]
        ll_por[nombre] = ll_tot / len(LINEAS[objetivo])
        fila['ll_media'] = round(float(ll_por[nombre].mean()), 4)
        res['modelos'][nombre] = fila
    # bootstrap por partido: N contra B1 y contra B2 (y contra N-)
    mids = ju.mid.values
    um, inv = np.unique(mids, return_inverse=True)

    def boot(a_nom, b_nom):
        dif = ll_por[a_nom] - ll_por[b_nom]          # >0: b mejor
        s = np.bincount(inv, weights=dif)
        n = np.bincount(inv)
        out = []
        for _ in range(2000):
            i = rng.integers(0, len(um), len(um))
            out.append(s[i].sum() / n[i].sum())
        return {'mejora_media': round(float(np.mean(out)), 5),
                'p5': round(float(np.percentile(out, 5)), 5)}
    N = 'N metodología completa'
    res['bootstrap'] = {'N vs B1': boot('B1 últimos 5 (misma condición)', N),
                        'N vs B2': boot('B2 ataque × defensa', N),
                        'N vs N-': boot('N- sin tabla/posesión/faltas', N)}
    res['importancia_N'] = {k: int(v) for k, v in imp.items()}
    # por liga (las del usuario)
    res['por_liga'] = {}
    for lg in ('brasil', 'mls', 'liga_mx'):
        msk = (ju.liga == lg).values
        if msk.sum() < 100:
            continue
        res['por_liga'][lg] = {nom: round(float(v[msk].mean()), 4)
                               for nom, v in ll_por.items()}
        res['por_liga'][lg]['n'] = int(msk.sum())
    return res


if __name__ == '__main__':
    out = {}
    for obj in ('tiros', 'a_puerta'):
        out[obj] = evaluar(obj)
        print(json.dumps({obj: out[obj]}, ensure_ascii=False, indent=1))
    json.dump(out, open('_v344_tiros.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
