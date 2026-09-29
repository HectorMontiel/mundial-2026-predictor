# -*- coding: utf-8 -*-
"""
v314 — LIGAS CHICAS (SIN MODELO PROPIO): GOLES, AMBOS MARCAN, GOLES POR
EQUIPO, LOCAL Y DOBLE OPORTUNIDAD, CON LOS PATRONES DE CADA LIGA.

El usuario: «para los otros modelos también puedes armar Over/Under de goles,
tanto global como por equipo, y córners y tarjetas. Analiza los patrones de
cada una de las ligas chicas: en una habrá equipos muy fuertes arriba en la
tabla, en otra el local pesa mucho, en otra hay muchos goles o pocos, muchas
tarjetas, buena probabilidad del local o de la doble oportunidad. Encuentra
esos patrones y después haz la simulación con los partidos finalizados de las
últimas fechas, para verificar que tus números cuadran y son muy buenos».

LOS DATOS
  · Precios: cada foto del tablero de casas mexicanas (`cuotas_mx.json`, en
    git con la hora del commit), la ÚLTIMA anterior a cada inicio: 1X2, doble
    oportunidad, más/menos goles (todas las líneas) y ambos marcan, de las
    casas del usuario. La probabilidad del mercado es la media de las casas,
    cada una sin su margen (devigado «potencia» del proyecto).
  · Resultados y patrones: los partidos terminados de FotMob, día a día,
    desde el 25 de julio. De ahí sale, para cada liga y cada equipo, lo que
    pasó ANTES de cada partido (nunca después): cuánto gana el local, cuántos
    goles hay, cuánto marcan los dos, y la forma de cada equipo.
  · Sólo partidos que el modelo NO cubre (los mismos de la v313).

QUÉ SE PRUEBA
  1. Si los patrones de la liga y de los equipos MEJORAN la probabilidad del
     mercado (Brier), por familia de mercado, mezclándolos con peso w. Elegido
     en los días de elección, juzgado en los de prueba con bootstrap.
  2. Qué regla de «meter» en goles / ambos marcan acierta al menos lo que ya
     acierta lo que se dice «meter» (sin bajar el total).
  3. Goles por equipo (no hay cuota en las casas del usuario): si la
     probabilidad está bien calibrada, para enseñarla como dato.
  4. Córners y tarjetas: si hay con qué medirlos en estas ligas.

Uso: python _v314_ligas_chicas.py [--rehacer]   (escribe _v314_ligas_chicas.json)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import subprocess
import sys

import numpy as np
import pandas as pd

DESDE_PRECIOS = '2026-09-19'
DESDE_FOTMOB = dt.date(2026, 7, 25)
HASTA_FOTMOB = dt.date(2026, 9, 29)
CACHE_FM = '_v314_fotmob.csv'
CACHE_PR = '_v314_precios.json'
SALIDA = '_v314_ligas_chicas.json'
CORTE = '2026-09-27'            # mismos tramos que v312/v313
CASAS = ('Calientemx', '1xBet', 'Winpot', 'Novibet', 'Sportium.mx')
VENTANA_LIGA = 60               # días de historia de la liga
K_LIGA = 20                     # encogimiento hacia lo global
LINEAS = (1.5, 2.5, 3.5)


# ---------------------------------------------------------------- datos
def fotmob() -> pd.DataFrame:
    if os.path.exists(CACHE_FM):
        return pd.read_csv(CACHE_FM, parse_dates=['ini'])
    import fuente_bajas as fb
    import horario as hz
    filas = []
    d = DESDE_FOTMOB
    while d <= HASTA_FOTMOB:
        doc = fb._get(fb.FOTMOB_DIA.format(fecha=d.strftime('%Y%m%d'))) or {}
        for L in doc.get('leagues') or []:
            for m in L.get('matches') or []:
                est = m.get('status') or {}
                h, a = m.get('home') or {}, m.get('away') or {}
                if not est.get('finished') or h.get('score') is None:
                    continue
                ini = hz._a_utc(est.get('utcTime'))
                if ini is None:
                    continue
                filas.append({'ini': ini, 'liga_id': L.get('primaryId') or L.get('id'),
                              'liga': L.get('name'), 'pais': L.get('ccode'),
                              'home': h.get('name'), 'away': a.get('name'),
                              'gh': int(h['score']), 'ga': int(a['score'])})
        print('fotmob', d, len(filas), flush=True)
        d += dt.timedelta(days=1)
    f = pd.DataFrame(filas).drop_duplicates(['ini', 'home', 'away'])
    f.to_csv(CACHE_FM, index=False)
    return pd.read_csv(CACHE_FM, parse_dates=['ini'])


def _commits(ruta):
    return [(h, float(ts)) for h, ts in (l.split() for l in subprocess.check_output(
        ['git', 'log', '--reverse', '--format=%h %ct', '--since=' + DESDE_PRECIOS,
         '--', ruta], text=True).splitlines() if l.strip())]


def precios() -> dict:
    """(home|away|inicio) -> las casas del usuario en la última foto previa."""
    if os.path.exists(CACHE_PR):
        return json.load(open(CACHE_PR, encoding='utf-8'))
    ult = {}
    for h, ts in _commits('cuotas_mx.json'):
        try:
            d = json.loads(subprocess.check_output(['git', 'show', h + ':cuotas_mx.json']))
        except Exception:
            continue
        for v in (d.get('partidos') or {}).values():
            if v.get('deporte') != 'futbol':
                continue
            try:
                ini = float(v.get('inicio'))
            except (TypeError, ValueError):
                continue
            if ini <= ts:
                continue
            casas = {c: m for c, m in (v.get('casas') or {}).items() if c in CASAS}
            if casas:
                ult['%s|%s|%d' % (v['home'], v['away'], int(ini))] = {
                    'home': v['home'], 'away': v['away'], 'inicio': int(ini),
                    'liga': v.get('liga'), 'casas': casas}
    json.dump(ult, open(CACHE_PR, 'w', encoding='utf-8'), ensure_ascii=False)
    return ult


# ------------------------------------------------------------ mercado
def _devig(cuotas: dict) -> dict:
    import cuotas_multi as cm
    try:
        return dict(cm.devig({k: float(v) for k, v in cuotas.items()}, metodo='potencia'))
    except Exception:
        return {}


def mercado(v: dict) -> dict:
    """Probabilidad (media de casas sin margen) y mejor cuota por selección."""
    probs, mejor = {}, {}

    def _add(sel, p, q):
        probs.setdefault(sel, []).append(p)
        if q and q > mejor.get(sel, 0):
            mejor[sel] = q
    for casa, m in v['casas'].items():
        x = m.get('HOME_DRAW_AWAY') or {}
        if all(x.get(k) for k in ('home', 'draw', 'away')):
            f = _devig({k: x[k] for k in ('home', 'draw', 'away')})
            if f:
                _add('home', f['home'], x['home'])
                _add('draw', f['draw'], x['draw'])
                _add('away', f['away'], x['away'])
                dc = m.get('DOUBLE_CHANCE') or {}
                _add('1X', f['home'] + f['draw'], dc.get('homeOrDraw'))
                _add('X2', f['away'] + f['draw'], dc.get('awayOrDraw'))
        bt = m.get('BOTH_TEAMS_TO_SCORE') or {}
        if bt.get('yes') and bt.get('no'):
            f = _devig({'s': bt['yes'], 'n': bt['no']})
            if f:
                _add('btts_si', f['s'], bt['yes'])
                _add('btts_no', f['n'], bt['no'])
        for ln in ((m.get('OVER_UNDER') or {}).get('lineas') or []):
            L = ln.get('linea')
            if L not in LINEAS or not (ln.get('over') and ln.get('under')):
                continue
            f = _devig({'o': ln['over'], 'u': ln['under']})
            if f:
                _add('mas_%s' % L, f['o'], ln['over'])
                _add('menos_%s' % L, f['u'], ln['under'])
    return {k: float(np.mean(v)) for k, v in probs.items()}, mejor


_REJ = None


def _rejilla():
    """P(gana local), P(gana visita) y P(más de 2,5) para cada par de λ."""
    global _REJ
    if _REJ is None:
        lh = np.arange(0.2, 4.01, 0.05)
        la = np.arange(0.2, 3.51, 0.05)
        k = np.arange(11)
        fac = np.array([math.factorial(i) for i in k], dtype=float)
        ph = np.exp(-lh)[:, None] * lh[:, None] ** k / fac          # (H, 11)
        pa = np.exp(-la)[:, None] * la[:, None] ** k / fac          # (A, 11)
        M = ph[:, None, :, None] * pa[None, :, None, :]            # (H, A, 11, 11)
        tri_i, tri_j = np.meshgrid(k, k, indexing='ij')
        PH = (M * (tri_i > tri_j)).sum(axis=(2, 3))
        PA = (M * (tri_i < tri_j)).sum(axis=(2, 3))
        PO = (M * ((tri_i + tri_j) >= 3)).sum(axis=(2, 3))
        _REJ = (lh, la, PH, PA, PO)
    return _REJ


def lambdas(p: dict):
    """λ local y visitante de Poisson que reproducen el 1X2 y el más de 2,5
    del mercado (lo que permite hablar de goles por equipo sin cuota)."""
    if not all(k in p for k in ('home', 'away')):
        return None
    lh, la, PH, PA, PO = _rejilla()
    e = (PH - p['home']) ** 2 + (PA - p['away']) ** 2
    if p.get('mas_2.5') is not None:
        e = e + (PO - p['mas_2.5']) ** 2
    i, j = np.unravel_index(np.argmin(e), e.shape)
    return float(lh[i]), float(la[j])


# ------------------------------------------------------------ patrones
def patrones(fm: pd.DataFrame, liga_id, fecha: pd.Timestamp, h: str, a: str) -> dict:
    """Lo que pasó ANTES de `fecha` en la liga (60 días) y a cada equipo."""
    prev = fm[fm.ini < fecha]
    lg = prev[(prev.liga_id == liga_id) & (prev.ini >= fecha - pd.Timedelta(days=VENTANA_LIGA))]
    glob = prev[prev.ini >= fecha - pd.Timedelta(days=VENTANA_LIGA)]

    def tasas(x):
        t = x.gh + x.ga
        return {'home': (x.gh > x.ga).mean(), 'draw': (x.gh == x.ga).mean(),
                'away': (x.gh < x.ga).mean(), 'btts_si': ((x.gh > 0) & (x.ga > 0)).mean(),
                **{'mas_%s' % L: (t > L).mean() for L in LINEAS},
                'goles': t.mean()}
    tg = tasas(glob)
    out = {'n_liga': int(len(lg))}
    tl = tasas(lg) if len(lg) else tg
    for k, v in tg.items():
        out['liga_' + k] = (len(lg) * tl[k] + K_LIGA * v) / (len(lg) + K_LIGA)
        out['glob_' + k] = v
    out['liga_1X'] = out['liga_home'] + out['liga_draw']
    out['liga_X2'] = out['liga_away'] + out['liga_draw']
    out['glob_1X'] = out['glob_home'] + out['glob_draw']
    out['glob_X2'] = out['glob_away'] + out['glob_draw']
    for k in ('btts', ) + tuple('mas_%s' % L for L in LINEAS):
        pass
    out['liga_btts_no'] = 1 - out['liga_btts_si']
    out['glob_btts_no'] = 1 - out['glob_btts_si']
    for L in LINEAS:
        out['liga_menos_%s' % L] = 1 - out['liga_mas_%s' % L]
        out['glob_menos_%s' % L] = 1 - out['glob_mas_%s' % L]
    # forma de cada equipo (últimos 8, cualquier competición)
    for lado, eq in (('h', h), ('a', a)):
        x = prev[(prev.home == eq) | (prev.away == eq)].tail(8)
        gf = np.where(x.home == eq, x.gh, x.ga)
        gc = np.where(x.home == eq, x.ga, x.gh)
        out['n_' + lado] = int(len(x))
        out['gf_' + lado] = float(gf.mean()) if len(x) else None
        out['gc_' + lado] = float(gc.mean()) if len(x) else None
    return out


# ------------------------------------------------------------ construir
def construir() -> pd.DataFrame:
    import cuotas_multi as cm
    import mercado_sin_modelo as msm
    import _v313_sin_modelo as v313
    fm = fotmob()
    pr = precios()
    cub = {}
    for dia, par in v313.cubiertos():
        cub.setdefault(dia, []).append(par)
    import horario as hz
    filas = []
    fm_ini = fm.set_index('ini', drop=False)
    for k, v in pr.items():
        ini = pd.Timestamp(v['inicio'], unit='s', tz='UTC')
        dia = hz.fecha(str(v['inicio']))
        par = '%s vs %s' % (v['home'], v['away'])
        if any(msm.mismo_partido(par, x) for x in cub.get(dia, [])):
            continue
        # el partido en FotMob: misma hora (±20 min) y nombres parecidos
        cand = fm[(fm.ini >= ini - pd.Timedelta(minutes=20)) & (fm.ini <= ini + pd.Timedelta(minutes=20))]
        m, s_ = None, 0
        for r in cand.itertuples(index=False):
            s = min(cm._sim_club(v['home'], r.home), cm._sim_club(v['away'], r.away))
            if max(cm._sim_club(v['home'], r.home), cm._sim_club(v['away'], r.away)) >= .85:
                s = max(s, .6)
            if s > s_:
                m, s_ = r, s
        if m is None or s_ < .55:
            continue
        p, q = mercado(v)
        if not p:
            continue
        pt = patrones(fm, m.liga_id, ini, m.home, m.away)
        lam = lambdas(p)
        fila = {'dia': dia, 'partido': par, 'liga': v.get('liga'), 'liga_fm': m.liga,
                'liga_id': m.liga_id, 'gh': m.gh, 'ga': m.ga,
                'lam_h': lam[0] if lam else None, 'lam_a': lam[1] if lam else None}
        for sel, pv in p.items():
            fila['p_' + sel] = pv
            fila['q_' + sel] = q.get(sel)
        fila.update(pt)
        filas.append(fila)
    d = pd.DataFrame(filas)
    d.to_csv('_v314_partidos.csv', index=False)
    return d


# ------------------------------------------------------------ medir
SELS = ['home', 'away', '1X', 'X2', 'btts_si', 'btts_no'] + \
    ['%s_%s' % (x, L) for L in LINEAS for x in ('mas', 'menos')]


def resultado(sel, gh, ga):
    t = gh + ga
    return {'home': gh > ga, 'away': ga > gh, '1X': gh >= ga, 'X2': ga >= gh,
            'btts_si': gh > 0 and ga > 0, 'btts_no': not (gh > 0 and ga > 0),
            **{'mas_%s' % L: t > L for L in LINEAS},
            **{'menos_%s' % L: t < L for L in LINEAS}}[sel]


def familia(sel):
    if sel in ('home', 'away', '1X', 'X2'):
        return 'resultado'
    return 'ambos' if sel.startswith('btts') else 'goles'


def largo(d: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for r in d.to_dict('records'):
        for sel in SELS:
            p = r.get('p_' + sel)
            if p is None or (isinstance(p, float) and math.isnan(p)):
                continue
            filas.append({'dia': r['dia'], 'partido': r['partido'],
                          'liga_fm': r['liga_fm'], 'sel': sel, 'fam': familia(sel),
                          'p': p, 'q': r.get('q_' + sel),
                          'liga': r.get('liga_' + sel), 'glob': r.get('glob_' + sel),
                          'n_liga': r['n_liga'],
                          'y': int(resultado(sel, r['gh'], r['ga']))})
    return pd.DataFrame(filas)


def mezcla(x, w):
    """Mercado + w × (lo que la liga se aparta de lo global), en logit."""
    lg = lambda z: np.log(np.clip(z, 1e-4, 1 - 1e-4) / (1 - np.clip(z, 1e-4, 1 - 1e-4)))
    z = lg(x['p']) + w * (lg(x['liga']) - lg(x['glob']))
    return 1 / (1 + np.exp(-z))


def resumen(x, rng):
    if not len(x):
        return {'n': 0}
    bs = [rng.choice(x['y'].values, len(x)).mean() for _ in range(2000)]
    out = {'n': int(len(x)), 'acierto': round(float(x['y'].mean()), 4),
           'p5': round(float(np.percentile(bs, 5)), 4)}
    if 'q' in x and x['q'].notna().all():
        out['roi'] = round(float((x['y'] * x['q'] - 1).mean()), 4)
        out['cuota_media'] = round(float(x['q'].mean()), 3)
    return out


def main():
    if '--rehacer' in sys.argv and os.path.exists('_v314_partidos.csv'):
        os.remove('_v314_partidos.csv')
    d = pd.read_csv('_v314_partidos.csv') if os.path.exists('_v314_partidos.csv') \
        else construir()
    rng = np.random.default_rng(0)
    L = largo(d)
    E, P = L[L.dia < CORTE], L[L.dia >= CORTE]
    out = {'partidos': int(len(d)), 'eleccion_dias': '< ' + CORTE,
           'prueba_dias': '>= ' + CORTE, 'ligas': int(d.liga_id.nunique())}

    # 1) ¿los patrones de la liga mejoran al mercado?
    out['patrones_liga'] = {}
    for fam in ('resultado', 'goles', 'ambos'):
        e, p_ = E[E.fam == fam], P[P.fam == fam]
        grid = {w: float(((mezcla(e, w) - e.y) ** 2).mean()) for w in (0, .25, .5, .75, 1)}
        w = min(grid, key=grid.get)
        res = {'grid_eleccion': grid, 'w': w}
        for nombre, x in (('eleccion', e), ('prueba', p_)):
            b0 = (x['p'] - x.y) ** 2
            b1 = (mezcla(x, w) - x.y) ** 2
            g = (b0 - b1).groupby(x.partido).sum()
            n = x.groupby('partido').size()
            ms = g.index.values
            dif = [g[s].sum() / n[s].sum() for s in (rng.choice(ms, len(ms)) for _ in range(2000))]
            res[nombre] = {'mejora_brier': round(float(np.mean(dif)), 5),
                           'p5': round(float(np.percentile(dif, 5)), 5)}
        res['pasa'] = w > 0 and res['eleccion']['p5'] > 0 and res['prueba']['p5'] > 0
        out['patrones_liga'][fam] = res

    # calibración del mercado de estas ligas, por banda
    out['calibracion_mercado'] = {}
    for fam in ('resultado', 'goles', 'ambos'):
        x = L[L.fam == fam]
        b = pd.cut(x.p, [.5, .6, .7, .75, .8, .85, .9, 1])
        out['calibracion_mercado'][fam] = {
            str(k): {'n': int(len(v)), 'p': round(float(v.p.mean()), 3),
                     'real': round(float(v.y.mean()), 3)}
            for k, v in x.groupby(b, observed=True)}

    # 2) reglas de «meter» en goles y ambos marcan (con cuota de las casas)
    def elegir(x, sels, lo, hi, qmin=1.10, qmax=1.35):
        y = x[x.sel.isin(sels) & (x.p >= lo) & (x.p <= hi) & (x.q >= qmin) & (x.q < qmax)]
        return y.sort_values('p', ascending=False).drop_duplicates('partido')
    GOLES = [s for s in SELS if familia(s) == 'goles']
    reglas = {}
    for nombre, sels in (('goles (todas las líneas)', GOLES),
                         ('más de 1,5', ['mas_1.5']), ('menos de 3,5', ['menos_3.5']),
                         ('más de 1,5 y menos de 3,5', ['mas_1.5', 'menos_3.5']),
                         ('ambos marcan', ['btts_si', 'btts_no'])):
        for lo, hi in ((.70, .80), (.75, .85), (.80, .90)):
            reglas['%s · %.0f-%.0f %%' % (nombre, lo * 100, hi * 100)] = {
                'eleccion': resumen(elegir(E, sels, lo, hi), rng),
                'prueba': resumen(elegir(P, sels, lo, hi), rng),
                '_sels': sels, '_lo': lo, '_hi': hi}
    out['reglas_goles'] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith('_')}
                           for k, v in reglas.items()}
    # la elegida: la de mejor acierto en ELECCIÓN con al menos 20 apuestas
    cand = [(k, v) for k, v in reglas.items() if v['eleccion'].get('n', 0) >= 20]
    k_el, v_el = max(cand, key=lambda kv: kv[1]['eleccion']['acierto'])
    out['regla_goles_elegida'] = k_el
    sel_el = elegir(L, v_el['_sels'], v_el['_lo'], v_el['_hi'])
    out['regla_goles_por_dia'] = {k: resumen(v, rng) for k, v in sel_el.groupby('dia')}

    # sumado a lo que ya se dice «meter» (v312 modelo + v313 sin modelo)
    try:
        v312 = json.load(open('_v312_patrones.json', encoding='utf-8'))
        v313 = json.load(open('_v313_sin_modelo.json', encoding='utf-8'))
        suma = {}
        for tramo, x in (('eleccion', sel_el[sel_el.dia < CORTE]),
                         ('prueba', sel_el[sel_el.dia >= CORTE]),
                         ('hoy', sel_el[sel_el.dia == v312['hoy']['dia']])):
            a = v312[tramo]['ahora']
            s13 = v313['sumado_a_v312'][tramo]['juntos']
            vv, nn = [int(t) for t in s13.split('=')[0].strip().split('/')]
            n2, v2 = nn + len(x), vv + int(x['y'].sum())
            suma[tramo] = {'hasta_v313': s13,
                           'goles_ligas_chicas': '%d/%d' % (int(x['y'].sum()), len(x)),
                           'juntos': '%d/%d = %.1f %%' % (v2, n2, 100 * v2 / n2)}
        out['sumado'] = suma
    except Exception as e:
        out['sumado'] = {'error': str(e)}

    # 3) goles por equipo (sin cuota): calibración de la λ del mercado
    ge = []
    for r in d.dropna(subset=['lam_h', 'lam_a']).to_dict('records'):
        for lado, lam, g in (('local', r['lam_h'], r['gh']), ('visita', r['lam_a'], r['ga'])):
            for Lq in (0.5, 1.5):
                pm = 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i)
                             for i in range(int(Lq) + 1))
                ge.append({'dia': r['dia'], 'lado': lado, 'linea': Lq, 'p': pm,
                           'y': int(g > Lq)})
    ge = pd.DataFrame(ge)
    out['goles_equipo'] = {}
    for Lq, x in ge.groupby('linea'):
        b = pd.cut(x.p, [0, .5, .6, .7, .8, .9, 1])
        out['goles_equipo']['más de %s' % Lq] = {
            str(k): {'n': int(len(v)), 'p': round(float(v.p.mean()), 3),
                     'real': round(float(v.y.mean()), 3)}
            for k, v in x.groupby(b, observed=True)}

    # patrones por liga, para enseñarlos (las ligas con más partidos)
    tabla = []
    for lid, x in d.groupby('liga_id'):
        tabla.append({'liga': x.liga_fm.iloc[0], 'partidos_medidos': int(len(x)),
                      'historia_60d': int(x.n_liga.max()),
                      'local_gana': round(float(x.liga_home.mean()), 3),
                      'mas_2.5': round(float(x['liga_mas_2.5'].mean()), 3),
                      'ambos_marcan': round(float(x.liga_btts_si.mean()), 3),
                      'goles_partido': round(float(x.liga_goles.mean()), 2)})
    out['ligas_patron'] = sorted(tabla, key=lambda t: -t['partidos_medidos'])[:25]
    json.dump(out, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    print(json.dumps({k: v for k, v in out.items() if k != 'ligas_patron'},
                     ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
