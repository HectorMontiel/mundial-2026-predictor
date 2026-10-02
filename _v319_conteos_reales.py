# -*- coding: utf-8 -*-
"""
v319 — CÓRNERS, TARJETAS Y GOLES POR EQUIPO CON HISTÓRICO REAL: BACKTEST.

Lo que pidió el usuario antes de activar nada:
  · backtest sobre al menos 200 partidos con datos reales verificados;
  · acierto real separado por liga con datos completos frente a parciales;
  · comparación entre «datos reales» y los actuales «estimados»;
  · si en la franja 70-80 % de probabilidad el acierto no supera el 72 %, ese
    mercado no se recomienda;
  · ¿fallan más los partidos parejos (favorito por debajo del 65 %) y los de
    visitante favorito? Si es así, confianza BAJA.

CÓRNERS — todas las ligas con córners reales (`corners_tabla.conjunto`):
  el modelo de producción (córners de cada equipo con la tabla) entrenado SÓLO
  con partidos anteriores al 2025-07-01 y aplicado a todo lo posterior. Cada
  partido se juzga con la regla del histórico real (`historico_real`, ≥ 5
  partidos de cada equipo en la temporada) A ESA FECHA. Líneas habituales
  (total 7,5-12,5; equipo 2,5-6,5), los dos lados. El total se prueba de dos
  formas: la media de la competición (lo de hoy) y la suma de lo esperado de
  los dos equipos (lo que pidió el usuario).
  «Estimado» = `stats_estimadas.estimar` (el nivel de la liga sacado de sus
  goles) sobre los mismos partidos.

TARJETAS — las predicciones de PRODUCCIÓN fuera de muestra de
  `_v310_conteos.csv` (Liga MX, selecciones, Champions, Europa, Conference),
  con su origen (observado/estimado) y la regla del histórico real.

GOLES POR EQUIPO — `pick_ledger_totales.csv` (80 mil partidos fuera de
  muestra): marca / mete 2+ de cada equipo. No hay «estimado»: sale siempre
  del modelo de goles.

Uso: python _v319_conteos_reales.py   (escribe _v319_conteos_reales.json)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

CORTE = pd.Timestamp('2025-07-01')
L_TOT = (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)
L_EQ = (2.5, 3.5, 4.5, 5.5, 6.5)
BANDA = (0.70, 0.80)


def _banda(df, col='p'):
    z = df[(df[col] >= BANDA[0]) & (df[col] <= BANDA[1])]
    return {'n': int(len(z)), 'partidos': int(z['mid'].nunique()) if 'mid' in z else None,
            'acierto': round(float(z['y'].mean()), 4) if len(z) else None,
            'p_media': round(float(z[col].mean()), 4) if len(z) else None}


def _filas_lineas(mid, lam, disp, real, lineas, tipo, extra, rq):
    out = []
    for L in lineas:
        p = rq.prob_mas_de(lam, L, disp)
        if p is None:
            continue
        y = int(real > L)
        out.append(dict(extra, mid=mid, tipo=tipo, linea=L, lado='mas', p=p, y=y))
        out.append(dict(extra, mid=mid, tipo=tipo, linea=L, lado='menos', p=1 - p, y=1 - y))
    return out


def corners(out, rng):
    import corners_tabla as ct
    import historico_real as hr
    import patrones_liga as pl
    import rendimiento_equipos as rq
    import stats_estimadas as se
    df = ct.conjunto()
    lg = sorted(df['liga'].unique())
    cod = {l: i for i, l in enumerate(lg)}
    ent = df[df['fecha'] < CORTE]
    mods = ct.ajustar_modelos(ent, cod, ct.rasgos_modelo())
    jz = df[df['fecha'] >= CORTE].copy()
    X = ct._X(jz, cod, ct.rasgos_modelo())
    jz['lh'], jz['la'] = mods['local'].predict(X), mods['visita'].predict(X)
    jz['mid'] = np.arange(len(jz))
    filas, n_ok = [], 0
    for liga, g in jz.groupby('liga'):
        disp = rq.dispersion_corners_equipo(liga)
        disp_t = rq.dispersion_corners_liga(liga)
        if not disp or not disp_t:
            continue
        h = rq._historico(liga)
        # «completa»: la liga trae el histórico entero de football-data (con
        # sus cuotas de goles desde 2010-2017); «parcial»: sólo lo que ESPN
        # publica de los últimos años
        parcial = not bool('odd_over25' in h.columns
                           and h['odd_over25'].notna().mean() > 0.5)
        # favorito y visitante favorito, con las cuotas del histórico
        cu = None
        if {'odd_home', 'odd_draw', 'odd_away'} <= set(h.columns):
            cu = h[['date', 'home_team', 'away_team', 'odd_home', 'odd_draw', 'odd_away']].copy()
            cu['date'] = pd.to_datetime(cu['date'], errors='coerce').dt.normalize()
            cu = cu.drop_duplicates(['date', 'home_team', 'away_team']).set_index(
                ['date', 'home_team', 'away_team'])
        est = se.estimar(liga, 'ck')
        for r in g.itertuples(index=False):
            ev = hr.evaluar(liga, r.home, r.away, 'corners', r.fecha)
            n_ok += int(ev['ok'])
            fav, vis_fav = None, None
            if cu is not None:
                try:
                    o = cu.loc[(pd.Timestamp(r.fecha).normalize(), r.home, r.away)]
                    inv = 1 / np.array([o.odd_home, o.odd_draw, o.odd_away], dtype=float)
                    q = inv / inv.sum()
                    fav, vis_fav = float(max(q[0], q[2])), bool(q[2] > q[0])
                except Exception:
                    pass
            extra = {'liga': liga, 'parcial': parcial, 'real': ev['ok'],
                     'fav': fav, 'vis_fav': vis_fav, 'fecha': r.fecha}
            media = r.liga_ck_h + r.liga_ck_a
            filas += _filas_lineas(r.mid, r.lh + r.la, disp_t, r.ch + r.ca, L_TOT, 'total_suma', extra, rq)
            filas += _filas_lineas(r.mid, media, disp_t, r.ch + r.ca, L_TOT, 'total_media', extra, rq)
            filas += _filas_lineas(r.mid, r.lh, disp, r.ch, L_EQ, 'local', extra, rq)
            filas += _filas_lineas(r.mid, r.la, disp, r.ca, L_EQ, 'visita', extra, rq)
            if est and est.get('lambda_home'):
                filas += _filas_lineas(r.mid, est['lambda_home'], est.get('dispersion') or disp,
                                       r.ch, L_EQ, 'est_local', extra, rq)
                filas += _filas_lineas(r.mid, est['lambda_away'], est.get('dispersion') or disp,
                                       r.ca, L_EQ, 'est_visita', extra, rq)
                if est.get('lambda_total'):
                    filas += _filas_lineas(r.mid, est['lambda_total'],
                                           est.get('dispersion_total') or disp_t,
                                           r.ch + r.ca, L_TOT, 'est_total', extra, rq)
    P = pd.DataFrame(filas)
    P.to_pickle('_v319_corners_filas.pkl')
    o = {'partidos_juzgados': int(jz['mid'].nunique()), 'con_historico_real': n_ok,
         'ligas': len(lg), 'corte': str(CORTE.date())}
    # el total: media de la competición contra suma de los dos equipos
    ll = {}
    for t in ('total_media', 'total_suma'):
        z = P[(P.tipo == t) & P.real]
        ll[t] = pl._ll(z['y'].to_numpy(), z['p'].to_numpy())
    d = ll['total_media'] - ll['total_suma']
    idx = rng.integers(0, len(d), size=(2000, len(d)))
    o['total'] = {'log_loss_media_competicion': round(float(ll['total_media'].mean()), 5),
                  'log_loss_suma_equipos': round(float(ll['total_suma'].mean()), 5),
                  'mejora_suma': round(float(d.mean()), 5),
                  'p5': round(float(np.percentile(d[idx].mean(axis=1), 5)), 5)}
    o['total']['adopta_suma'] = bool(o['total']['mejora_suma'] > 0 and o['total']['p5'] > 0)
    tot_ok = 'total_suma' if o['total']['adopta_suma'] else 'total_media'
    R = P[P.tipo.isin([tot_ok, 'local', 'visita'])]
    o['franja_70_80'] = {
        'datos_reales': _banda(R[R.real]),
        'sin_historico_real': _banda(R[~R.real]),
        'reales_liga_completa': _banda(R[R.real & ~R.parcial]),
        'reales_liga_parcial': _banda(R[R.real & R.parcial]),
        'reales_total': _banda(R[R.real & (R.tipo == tot_ok)]),
        'reales_por_equipo': _banda(R[R.real & R.tipo.isin(['local', 'visita'])]),
        'estimado_mismos_partidos': _banda(P[P.tipo.isin(['est_local', 'est_visita', 'est_total'])
                                             & P.real]),
        'reales_partido_parejo_fav_menor_65': _banda(R[R.real & (R.fav < .65)]),
        'reales_favorito_65_o_mas': _banda(R[R.real & (R.fav >= .65)]),
        'reales_visitante_favorito': _banda(R[R.real & (R.vis_fav == True)]),  # noqa: E712
        'reales_local_favorito': _banda(R[R.real & (R.vis_fav == False)]),  # noqa: E712
    }
    o['franja_70_80']['total_con_media_competicion'] = _banda(P[P.real & (P.tipo == 'total_media')])
    o['franja_70_80']['total_con_suma_equipos'] = _banda(P[P.real & (P.tipo == 'total_suma')])
    o['recomendable'] = bool((o['franja_70_80']['datos_reales']['acierto'] or 0) >= 0.72)
    # v319 — y liga por liga: el usuario quiere saber «qué córners están
    # mejor calibrados en cada liga»
    o['por_liga'] = {l: _banda(z) for l, z in R[R.real].groupby('liga')}
    out['corners'] = o


def tarjetas(out):
    import historico_real as hr
    import rendimiento_equipos as rq
    v = pd.read_csv('_v310_conteos.csv', parse_dates=['fecha'])
    filas = []
    for m, lt, le in (('tarjetas', (2.5, 3.5, 4.5, 5.5), (0.5, 1.5, 2.5)),
                      ('corners', L_TOT, L_EQ)):
        z = v[v['mercado'] == m]
        for i, r in enumerate(z.itertuples(index=False)):
            ev = hr.evaluar(r.clave, r.home, r.away, m, r.fecha)
            extra = {'mercado': m, 'origen': r.origen, 'real': ev['ok']}
            mid = '%s|%s|%s' % (r.fecha, r.home, r.away)
            if r.lam_t == r.lam_t:
                filas += _filas_lineas(mid, r.lam_t, r.disp_t, r.real_h + r.real_a, lt, 'total', extra, rq)
            filas += _filas_lineas(mid, r.lam_h, r.disp, r.real_h, le, 'local', extra, rq)
            filas += _filas_lineas(mid, r.lam_a, r.disp, r.real_a, le, 'visita', extra, rq)
    P = pd.DataFrame(filas)
    for m in ('tarjetas', 'corners'):
        z = P[P.mercado == m]
        o = {'partidos': int(z['mid'].nunique()),
             'franja_70_80': {'observado_con_historico_real': _banda(z[(z.origen == 'observado') & z.real]),
                              'observado_sin_historico_real': _banda(z[(z.origen == 'observado') & ~z.real]),
                              'estimado': _banda(z[z.origen == 'estimado'])}}
        o['recomendable'] = bool((o['franja_70_80']['observado_con_historico_real']['acierto'] or 0) >= 0.72)
        out['produccion_' + m] = o


def goles_equipo(out):
    t = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    t = t[t['liga'] != 'liga']
    for c in ('lam_h', 'lam_a', 'goles_local', 'goles_visit'):
        t[c] = pd.to_numeric(t[c], errors='coerce')
    t = t.dropna(subset=['lam_h', 'lam_a', 'goles_local', 'goles_visit'])
    t['fecha'] = pd.to_datetime(t['fecha'], errors='coerce')
    corte = t['fecha'].sort_values().iloc[int(len(t) * .7)]
    filas = []
    for lado, lam, g in (('local', t.lam_h, t.goles_local), ('visita', t.lam_a, t.goles_visit)):
        p1 = 1 - np.exp(-lam)
        p2 = 1 - np.exp(-lam) * (1 + lam)
        for L, p in ((0.5, p1), (1.5, p2)):
            y = (g > L).astype(int)
            for lado2, pp, yy in (('mas', p, y), ('menos', 1 - p, 1 - y)):
                filas.append(pd.DataFrame({'p': pp, 'y': yy, 'tramo': np.where(t.fecha < corte, 'elegir', 'juzgar'),
                                           'linea': L, 'lado': lado2, 'equipo': lado, 'mid': t.match_id}))
    P = pd.concat(filas)
    o = {'partidos': int(t['match_id'].nunique()), 'franja_70_80': {}}
    for tr, z in P.groupby('tramo'):
        o['franja_70_80'][tr] = _banda(z)
    for (L, lado), z in P.groupby(['linea', 'lado']):
        o['franja_70_80']['%s_de_%s' % (lado, L)] = _banda(z)
    o['recomendable'] = bool(all((v['acierto'] or 0) >= 0.72 for k, v in o['franja_70_80'].items()
                                 if k in ('elegir', 'juzgar')))
    out['goles_equipo'] = o


def main():
    rng = np.random.default_rng(319)
    out = {}
    goles_equipo(out)
    print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)
    tarjetas(out)
    print(json.dumps({k: out[k] for k in out if k.startswith('produccion')}, ensure_ascii=False, indent=1), flush=True)
    corners(out, rng)
    json.dump(out, open('_v319_conteos_reales.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out['corners'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
