#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v358 — NFL: hándicap y puntos (más/menos) alternativos, contra la línea de la casa.

El usuario: «quiero meter en la NFL hándicap, puntos más/menos y ganador, con
la misma metodología, para pretemporada y temporada oficial».

Lo que publica Playdoit (tableros del 10-oct, `cuotas_multi.mercados_playdoit`):
«Hándicap (incl. prórroga)» con escalera de ±11 puntos alrededor de la
principal (cuota mínima ~1,14-1,22) y «Totales (incl. prórroga)» con ±11
(cuota mínima ~1,15). Todas las líneas en ,5: nunca hay empate (push).

Aquí, con `historico_nfl_largo.csv` (nflverse 1999-2026, cierre de la casa):
  1. DOS FORMAS de convertir la distancia a la línea principal en
     probabilidad, elegidas con 1999-2014 y juzgadas con 2015-2025:
       A. por distancia k (la de la NBA): acierto medio a k puntos;
       B. por vecinos (la de la NFL): con los partidos de hándicap parecido
          (±1 punto), la proporción que pasa EXACTAMENTE esa línea. Respeta
          los números clave (3, 7, 10), que en la NFL pesan mucho.
  2. LA REGLA: por lado, la línea más lejana a la meta (mejor cuota) con
     probabilidad ≥ 75 %; su acierto real por temporada; y la de Capa 1 (≥ 84 %).
  3. EL MODELO (`_v325_nfl.walk_forward`): ¿acierta más la alternativa cuando
     el modelo ve el partido del lado de la apuesta?
  4. 2026 (5 semanas jugadas): lo mismo, fuera de muestra.
  5. LA PRETEMPORADA (ESPN, `_v358_nfl_pretemporada.csv`).
Guarda lo que usa la app en `nfl_lineas.json`.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(358)
KMAX = 11.0
LADO = ('favorito', 'no_favorito', 'mas', 'menos')


def cargar():
    d = pd.read_csv('historico_nfl_largo.csv', low_memory=False)
    d = d[d.spread_line.notna() & d.total_line.notna() & d.home_score.notna()].copy()
    d['margen'] = d.home_score - d.away_score
    d['total'] = d.home_score + d.away_score
    d['s'] = d.spread_line.abs()                       # hándicap del favorito (puntos)
    d['mfav'] = np.where(d.spread_line >= 0, d.margen, -d.margen)
    return d


# ------------------------------------------------------------ las dos formas
def lineas(s, t0):
    """La escalera de Playdoit: líneas en ,5 hasta ±KMAX de la principal.
    Devuelve [(lado, umbral, k)] — para el favorito el umbral es lo que debe
    ganar por MÁS; para el no favorito, por lo que el favorito debe ganar por
    MENOS; para los totales, la línea."""
    out = []
    base_h = np.floor(s) + 0.5 if s % 1 == 0 else s       # primera línea en ,5
    for j in range(-12, 13):
        x = base_h + j                                   # margen del favorito a superar
        k_fav = s - x                                    # cuánto se le regala al favorito
        if 0 < k_fav <= KMAX:
            out.append(('favorito', x, k_fav))
        k_dog = x - s
        if 0 < k_dog <= KMAX:
            out.append(('no_favorito', x, k_dog))
    base_t = np.floor(t0) + 0.5 if t0 % 1 == 0 else t0
    for j in range(-12, 13):
        L = base_t + j
        if 0 < t0 - L <= KMAX:
            out.append(('mas', L, t0 - L))
        if 0 < L - t0 <= KMAX:
            out.append(('menos', L, L - t0))
    return out


def gana(lado, umbral, fila):
    if lado == 'favorito':
        return fila.mfav > umbral
    if lado == 'no_favorito':
        return fila.mfav < umbral
    if lado == 'mas':
        return fila.total > umbral
    return fila.total < umbral


class Forma:
    def __init__(self, ent, metodo):
        self.metodo = metodo
        self.s = ent.s.values
        self.mfav = ent.mfav.values
        self.t0 = ent.total_line.values
        self.tot = ent.total.values
        self.ds = self.mfav - self.s
        self.dt = self.tot - self.t0

    def p(self, lado, umbral, s, t0):
        if self.metodo == 'k':
            if lado in ('favorito', 'no_favorito'):
                k = (s - umbral) if lado == 'favorito' else (umbral - s)
                return float((self.ds > -k).mean()) if lado == 'favorito' else float((self.ds < k).mean())
            k = (t0 - umbral) if lado == 'mas' else (umbral - t0)
            return float((self.dt > -k).mean()) if lado == 'mas' else float((self.dt < k).mean())
        if lado in ('favorito', 'no_favorito'):
            m = np.abs(self.s - s) <= 1.0
            v = self.mfav[m]
            return float((v > umbral).mean()) if lado == 'favorito' else float((v < umbral).mean())
        m = np.abs(self.t0 - t0) <= 1.5
        v = self.tot[m]
        return float((v > umbral).mean()) if lado == 'mas' else float((v < umbral).mean())


def filas_pred(forma, jui):
    out = []
    for r in jui.itertuples():
        for lado, umbral, k in lineas(r.s, r.total_line):
            out.append({'game_id': r.game_id, 'season': r.season, 'lado': lado, 'k': k,
                        'umbral': umbral, 's': r.s, 't0': r.total_line,
                        'p': forma.p(lado, umbral, r.s, r.total_line),
                        'gana': bool(gana(lado, umbral, r))})
    return pd.DataFrame(out)


def calibracion(f):
    b = pd.cut(f.p, [0.70, 0.75, 0.80, 0.84, 0.88, 0.92, 1.0])
    return [{'banda': str(k), 'n': int(len(g)), 'promete': round(float(g.p.mean()), 3),
             'acierta': round(float(g.gana.mean()), 3)} for k, g in f.groupby(b, observed=True)]


def regla(f, meta):
    """Por partido y lado, la línea de MENOR probabilidad que llega a la meta
    (la de mejor cuota)."""
    x = f[f.p >= meta].sort_values('p').groupby(['game_id', 'lado']).head(1)
    return x


def boot(a, n=2000):
    a = np.asarray(a, float)
    m = [a[rng.integers(0, len(a), len(a))].mean() for _ in range(n)]
    return round(float(np.percentile(m, 5)), 4)


def resumen(x):
    out = {}
    for lado, g in x.groupby('lado'):
        out[lado] = {'n': int(len(g)), 'acierta': round(float(g.gana.mean()), 4),
                     'promete': round(float(g.p.mean()), 4), 'p5': boot(g.gana),
                     'k_medio': round(float(g.k.mean()), 1)}
    out['todo'] = {'n': int(len(x)), 'acierta': round(float(x.gana.mean()), 4), 'p5': boot(x.gana)}
    return out


def modelo_acuerdo(d, f):
    """El no favorito / favorito / más / menos con el modelo del lado de la apuesta."""
    try:
        import _v325_nfl as V
        import nfl_estado as ne
        import nfl_nflverse as nv
        ds, _ = ne.dataset(nv.cargar())
        x = V.variables(ds)
        r = V.walk_forward(x, range(2010, 2026))
    except Exception as e:
        return {'error': str(e)}
    r = r[['game_id', 'm_pred', 't_pred']]
    g = f.merge(d[['game_id', 'spread_line']], on='game_id').merge(r, on='game_id')
    mod_fav = np.where(g.spread_line >= 0, g.m_pred, -g.m_pred)
    dif = mod_fav - g.s
    dt = g.t_pred - g.t0
    con = np.select([g.lado == 'favorito', g.lado == 'no_favorito', g.lado == 'mas'],
                    [dif >= 2, dif <= -2, dt >= 2], dt <= -2)
    out = {}
    for tramo, ft in (('elige_2010_14', g.season <= 2014), ('juzga_2015_25', g.season >= 2015)):
        for lado in LADO:
            m = ft & (g.lado == lado)
            out['%s_%s' % (tramo, lado)] = {
                'con_el_modelo': round(float(g.gana[m & con].mean()), 4), 'n_con': int((m & con).sum()),
                'resto': round(float(g.gana[m & ~con].mean()), 4)}
    return out


def pretemporada(forma):
    if not os.path.exists('_v358_nfl_pretemporada.csv'):
        return None
    p = pd.read_csv('_v358_nfl_pretemporada.csv')
    out = {'partidos': int(len(p))}
    p = p[p.spread.notna() & p.total.notna()].copy()
    if p.empty:
        return out
    p['margen'] = p.pts_home - p.pts_away
    p['total_pts'] = p.pts_home + p.pts_away
    fav_home = p.fav_home.astype(str).str.lower().eq('true')
    sin_fav = ~fav_home & ~p.fav_home.astype(str).str.lower().eq('false')
    ph = None
    if p.ml_home.notna().any():
        ph = (1 / p.ml_home) / (1 / p.ml_home + 1 / p.ml_away)
        fav_home = np.where(sin_fav, ph >= 0.5, fav_home)
    p['s'] = p.spread.abs()
    p['mfav'] = np.where(fav_home, p.margen, -p.margen)
    p['total_line'] = p.total
    p['total'] = p.total_pts
    p['game_id'] = p.event_id
    p['season'] = p.temporada
    out['con_linea'] = int(len(p))
    out['sd_margen_vs_linea'] = round(float((p.mfav - p.s).std()), 2)
    out['sd_total_vs_linea'] = round(float((p.total - p.total_line).std()), 2)
    f = filas_pred(forma, p)
    out['calibracion'] = {lado: calibracion(f[f.lado == lado]) for lado in LADO}
    out['regla_75'] = resumen(regla(f, 0.75))
    out['regla_78'] = resumen(regla(f, 0.78))
    out['regla_84'] = resumen(regla(f, 0.84))
    # en dos mitades (2021-23 / 2024-26): ¿el mismo lado aguanta en las dos?
    out['regla_78_mitades'] = {nombre: resumen(regla(f[c], 0.78))
                               for nombre, c in (('2021_2023', f.season <= 2023),
                                                 ('2024_2026', f.season >= 2024))}
    if ph is not None:
        q = p[p.ml_home.notna()].copy()
        q['pf'] = np.maximum(ph[q.index], 1 - ph[q.index])
        q['gana_fav'] = q.mfav > 0
        b = pd.cut(q.pf, [0.5, 0.6, 0.7, 0.74, 0.8, 1.0])
        out['ganador_por_banda'] = [{'banda': str(k), 'n': int(len(g)),
                                     'promete': round(float(g.pf.mean()), 3),
                                     'acierta': round(float(g.gana_fav.mean()), 3)}
                                    for k, g in q.groupby(b, observed=True)]
        g = q[q.pf >= 0.74]
        out['ganador_casa74'] = {'n': int(len(g)), 'acierta': round(float(g.gana_fav.mean()), 3) if len(g) else None}
    return out


def tabla_app(ent):
    """Lo que usa la app (`nfl_lineas.tablas`): la forma elegida (por
    distancia k) con TODAS las temporadas 1999-2025, de k = 0,5 a 15."""
    fo = Forma(ent, 'k')
    out = {lado: {} for lado in LADO}
    for k in np.arange(0.5, 15.01, 0.5):
        out['favorito']['%.1f' % k] = round(fo.p('favorito', 10 - k, 10, 44), 4)
        out['no_favorito']['%.1f' % k] = round(fo.p('no_favorito', 10 + k, 10, 44), 4)
        out['mas']['%.1f' % k] = round(fo.p('mas', 44 - k, 10, 44), 4)
        out['menos']['%.1f' % k] = round(fo.p('menos', 44 + k, 10, 44), 4)
    return {'tablas': out}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar()
    print('partidos con línea', len(d), d.season.min(), '-', d.season.max())
    el, ju, nuevo = d[d.season <= 2014], d[(d.season >= 2015) & (d.season <= 2025)], d[d.season == 2026]
    res = {}
    for metodo in ('k', 'vecinos'):
        fo = Forma(el, metodo)
        f = filas_pred(fo, ju)
        f = f[(f.p >= 0.70)]
        bri = float(((f.p - f.gana) ** 2).mean())
        res[metodo] = {'brier_juzga': round(bri, 5),
                       'calibracion': {lado: calibracion(f[f.lado == lado]) for lado in LADO},
                       'regla_75': resumen(regla(f, 0.75)), 'regla_84': resumen(regla(f, 0.84))}
        print('\n== forma', metodo, 'brier', round(bri, 5))
        print(' regla 75', res[metodo]['regla_75'])
        print(' regla 84', res[metodo]['regla_84'])
    # se elige con el tramo de elegir (forma ajustada con 1999-2006, juzgada 2007-2014)
    e1, e2 = d[d.season <= 2006], d[(d.season >= 2007) & (d.season <= 2014)]
    bri_e = {}
    for metodo in ('k', 'vecinos'):
        f = filas_pred(Forma(e1, metodo), e2)
        f = f[f.p >= 0.70]
        bri_e[metodo] = round(float(((f.p - f.gana) ** 2).mean()), 5)
    elegido = min(bri_e, key=bri_e.get)
    print('\nbrier al elegir (1999-2006 → 2007-14):', bri_e, '→', elegido)
    # por temporada (la elegida, ajustada con todo lo anterior)
    por_temp = {}
    for s in range(2015, 2027):
        fo = Forma(d[d.season < s], elegido)
        f = filas_pred(fo, d[d.season == s])
        r75, r84 = regla(f, 0.75), regla(f, 0.84)
        por_temp[s] = {'r75': resumen(r75)['todo'] if len(r75) else None,
                       'r75_hcp': resumen(r75[r75.lado.isin(['favorito', 'no_favorito'])])['todo'] if len(r75) else None,
                       'r75_tot': resumen(r75[r75.lado.isin(['mas', 'menos'])])['todo'] if len(r75) else None,
                       'r84': resumen(r84)['todo'] if len(r84) else None}
        print(s, por_temp[s])
    fo26 = Forma(d[d.season < 2026], elegido)
    f26 = filas_pred(fo26, nuevo)
    r26 = {'r75': resumen(regla(f26, 0.75)), 'r84': resumen(regla(f26, 0.84)),
           'partidos': int(len(nuevo))}
    print('\n2026:', json.dumps(r26, ensure_ascii=False))
    mod = modelo_acuerdo(d, filas_pred(Forma(el, elegido), d[(d.season >= 2010) & (d.season <= 2025)]).query('p >= 0.75'))
    print('\nmodelo:', json.dumps(mod, ensure_ascii=False))
    pre = pretemporada(Forma(d[d.season <= 2025], elegido))
    print('\npretemporada:', json.dumps(pre, ensure_ascii=False, default=str))
    doc = {'generado': pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
           'fuente': 'nflverse 1999-2025 (cierre de la casa); forma %s' % elegido,
           'forma': elegido, 'brier_elegir': bri_e, 'formas': res,
           'por_temporada': por_temp, 'temporada_2026': r26, 'modelo': mod,
           'pretemporada': pre}
    doc.update(tabla_app(d[d.season <= 2025]))
    json.dump(doc, open('nfl_lineas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    print('guardado nfl_lineas.json')


if __name__ == '__main__':
    main()
