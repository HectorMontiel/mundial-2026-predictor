#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v350 — «se mete» y Capa 1 del GANADOR en la NFL y la NBA.

El usuario: «quiero meter a la Capa 1 y a las apuestas que se meten el
ganador de la NFL y de la NBA (y la MLB), con la misma metodología del
fútbol: simulaciones con todo el histórico y los partidos recientes; que la
mayoría sigan siendo verdes».

Lo que había: la regla general (la mezcla modelo/casa ≥ 65 %), que en el
tramo de juzgar acierta 76,8 % (NFL) y 76 % (NBA): por debajo del ~80 % del
fútbol. Aquí se busca la regla del tipo de la del fútbol y el tenis
(v335 / v342): la casa sin margen ≥ C, la probabilidad de la app ≥ M y la
cuota ≥ Q.

  · Datos: la réplica sin fuga de cada deporte (`_v325_nfl`, `_v330_nba`):
    cada temporada 2010-2025 con un modelo que no la vio, el cierre de la
    casa (moneyline), y el resultado.
  · La probabilidad de la app es la misma mezcla de producción
    (`concordancia.PESO_MODELO_NFL` / `_NBA`).
  · Elige con las temporadas 2010-2020 (≈70 %), juzga con 2021-2025.
  · Bootstrap por partido: el acierto de la regla nueva MENOS el de la de
    hoy, sobre los mismos partidos remuestreados.
  · También la Capa 1 «lo mejor del modelo» del fútbol (casa 80-88 % y
    modelo ≥ 70 %) en cada deporte.
"""
import json
import sys

import numpy as np
import pandas as pd

import concordancia as cc

rng = np.random.default_rng(350)
CORTE = 2020          # elige hasta esta temporada incluida


def _nfl():
    import _v325_nfl as F
    d = F.nv.cargar()
    ds, _ = F.ne.dataset(d)
    x = F.variables(ds)
    x['p_mkt'] = F.mercado(x)
    r = F.walk_forward(x, range(2010, 2027))     # 2026: la temporada en curso
    r = r[r.p_mkt.notna() & r.margen.notna() & (r.margen != 0)]
    return pd.DataFrame({
        'temporada': r.season.values, 'mid': r.game_id.values if 'game_id' in r else np.arange(len(r)),
        'p_mod': r.p_home_emp.values, 'p_casa': r.p_mkt.values,
        'c_home': F.americano(r.home_moneyline), 'c_away': F.americano(r.away_moneyline),
        'gana_home': (r.margen > 0).astype(int).values}), cc.PESO_MODELO_NFL


def _nba():
    import _v330_nba as B
    d = B.nh.cargar()
    x, _ = B.ne.dataset(d)
    x['p_mkt'] = B.mercado(x)
    r = B.walk_forward(x, range(2010, 2026))
    r = r[r.p_mkt.notna() & r.margen.notna() & (r.margen != 0)]
    return pd.DataFrame({
        'temporada': r.temporada.values, 'mid': np.arange(len(r)),
        'p_mod': r.p_home.values, 'p_casa': r.p_mkt.values,
        'c_home': B.americano(r.ml_home), 'c_away': B.americano(r.ml_away),
        'gana_home': (r.margen > 0).astype(int).values}), cc.PESO_MODELO_NBA


def lados(t: pd.DataFrame, w: float) -> pd.DataFrame:
    """El favorito de la app en cada partido (el lado que la tarjeta pinta)."""
    t = t.copy()
    t['p_app_h'] = w * t.p_mod + (1 - w) * t.p_casa
    h = t.p_app_h >= 0.5
    return pd.DataFrame({
        'temporada': t.temporada, 'mid': t.mid,
        'p_app': np.where(h, t.p_app_h, 1 - t.p_app_h),
        'p_mod': np.where(h, t.p_mod, 1 - t.p_mod),
        'p_casa': np.where(h, t.p_casa, 1 - t.p_casa),
        'cuota': np.where(h, t.c_home, t.c_away),
        'gana': np.where(h, t.gana_home, 1 - t.gana_home)}).dropna()


def mascara(f, casa=None, app=0.65, cuota=1.0, casa_max=None, modelo=None):
    m = (f.p_app >= app) & (f.cuota >= cuota)
    if casa is not None:
        m &= f.p_casa >= casa
    if casa_max is not None:
        m &= f.p_casa < casa_max
    if modelo is not None:
        m &= f.p_mod >= modelo
    return m


def resumen(g):
    if len(g) == 0:
        return {'n': 0}
    return {'n': int(len(g)), 'acierto': round(float(g.gana.mean()), 4),
            'promete': round(float(g.p_app.mean()), 4),
            'casa': round(float(g.p_casa.mean()), 4),
            'cuota': round(float(g.cuota.mean()), 3),
            'roi': round(float((g.gana * g.cuota - 1).mean()), 4),
            'por_temporada': round(len(g) / max(1, g.temporada.nunique()), 1)}


def boot_dif(f, m_nueva, m_vieja, n=3000):
    """Acierto y rendimiento de la nueva menos la vieja, remuestreando partidos."""
    idx = np.arange(len(f))
    gana = f.gana.values
    pnl = (f.gana * f.cuota - 1).values
    a, b = m_nueva.values, m_vieja.values
    da, dr = [], []
    for _ in range(n):
        i = rng.choice(idx, len(idx))
        na, nb = a[i], b[i]
        if na.sum() == 0 or nb.sum() == 0:
            continue
        da.append(gana[i][na].mean() - gana[i][nb].mean())
        dr.append(pnl[i][na].mean() - pnl[i][nb].mean())
    return {'acierto_dif': round(float(np.mean(da)), 4),
            'acierto_dif_p5': round(float(np.percentile(da, 5)), 4),
            'roi_dif': round(float(np.mean(dr)), 4),
            'roi_dif_p5': round(float(np.percentile(dr, 5)), 4)}


def boot_roi(g, n=3000):
    if len(g) < 10:
        return None
    pnl = (g.gana * g.cuota - 1).values
    bs = [pnl[rng.integers(0, len(pnl), len(pnl))].mean() for _ in range(n)]
    return round(float(np.percentile(bs, 5)), 4)


def medir(nombre, f):
    el, ju = f[f.temporada <= CORTE], f[(f.temporada > CORTE) & (f.temporada <= 2025)]
    hoy = dict(app=0.65)
    out = {'partidos_lado': int(len(f)), 'hoy_elige': resumen(el[mascara(el, **hoy)]),
           'hoy_juzga': resumen(ju[mascara(ju, **hoy)])}
    n_hoy = out['hoy_elige']['n']
    rej = []
    for casa in (None, 0.65, 0.70, 0.72, 0.74, 0.76, 0.78, 0.80):
        for app in (0.65, 0.70, 0.72, 0.74, 0.76, 0.78, 0.80):
            for cuota in (1.0, 1.10, 1.15):
                k = dict(casa=casa, app=app, cuota=cuota)
                r = resumen(el[mascara(el, **k)])
                if r['n'] >= max(60, 0.30 * n_hoy):
                    rej.append((k, r))
    # la que más acierta con suficiente volumen; a igualdad, la de más rendimiento
    ok = [x for x in rej if x[1]['acierto'] >= 0.80] or rej
    k, r_el = max(ok, key=lambda x: (x[1]['n'] if x[1]['acierto'] >= 0.80 else 0,
                                      x[1]['acierto'], x[1]['roi']))
    out['rejilla_top'] = sorted([(json.dumps(a), b['n'], b['acierto'], b['roi'])
                                 for a, b in rej], key=lambda z: -z[2])[:15]
    out['regla'] = k
    out['elige'] = r_el
    out['juzga'] = resumen(ju[mascara(ju, **k)])
    out['juzga_vs_hoy'] = boot_dif(ju, mascara(ju, **k), mascara(ju, **hoy))
    out['juzga_roi_p5'] = boot_roi(ju[mascara(ju, **k)])
    out['ultima_temporada'] = resumen(f[(f.temporada == f.temporada.max()) & mascara(f, **k)])
    # LA ADOPTADA (v350): app ≥ 70 %, cuota 1,10-1,40 y la casa ≥ X cuya PEOR
    # temporada del tramo de elegir sea la más alta (criterio fijado antes de
    # mirar el juicio: lo que protege el semáforo año a año)
    cand = []
    for casa in (0.70, 0.72, 0.74, 0.76, 0.78, 0.80):
        k2 = dict(casa=casa, app=0.70, cuota=1.10)
        g = el[mascara(el, **k2) & (el.cuota <= 1.40)]
        peor = g.groupby('temporada').gana.mean().min()
        cand.append((casa, round(float(peor), 4), resumen(g)))
    casa_ok = max(cand, key=lambda z: z[1])[0]
    k2 = dict(casa=casa_ok, app=0.70, cuota=1.10)
    m_ju = mascara(ju, **k2) & (ju.cuota <= 1.40)
    out['adoptada'] = {'regla': {**k2, 'cuota_max': 1.40},
                       'candidatas_elige_peor_temporada': cand,
                       'elige': resumen(el[mascara(el, **k2) & (el.cuota <= 1.40)]),
                       'juzga': resumen(ju[m_ju]),
                       'juzga_vs_hoy': boot_dif(ju, m_ju, mascara(ju, **hoy)),
                       'juzga_por_temporada': {int(s2): resumen(g2) for s2, g2 in
                                               ju[m_ju].groupby('temporada')}}
    # y la temporada en curso (sólo la NFL juega ahora): los partidos recientes
    rec = f[(f.temporada > 2025) & mascara(f, **k2) & (f.cuota <= 1.40)]
    out['adoptada']['temporada_en_curso'] = resumen(rec)
    out['hoy_temporada_en_curso'] = resumen(f[(f.temporada > 2025) & mascara(f, **hoy)])
    # Capa 1 «lo mejor del modelo» del fútbol: casa 80-88 %, modelo ≥ 70 %
    c1 = dict(casa=0.80, casa_max=0.88, app=0.0, modelo=0.70, cuota=1.10)
    out['capa1_futbol_elige'] = resumen(el[mascara(el, **c1)])
    out['capa1_futbol_juzga'] = resumen(ju[mascara(ju, **c1)])
    # por banda de la casa en el juicio (para enseñarlo tal cual)
    b = ju.assign(banda=pd.cut(ju.p_casa, [0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0]))
    out['bandas_casa_juzga'] = [
        {'banda': str(k2), **resumen(g)} for k2, g in b.groupby('banda', observed=True)]
    print('\n=====', nombre, '=====')
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    out = {}
    for nombre, fn in (('NFL', _nfl), ('NBA', _nba)):
        t, w = fn()
        out[nombre] = medir(nombre, lados(t, w))
        out[nombre]['peso_modelo'] = w
    json.dump(out, open('_v350_ganador.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
