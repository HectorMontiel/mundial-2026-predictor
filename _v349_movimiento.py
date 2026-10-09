#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v349 — la metodología del video: «mira cómo mueve la casa la cuota».

El tipster (transcripción que pasó el usuario): el 60 % de su análisis es
cómo se mueven los momios en la semana; si se mueven mucho, «pasó algo»; y
si la casa hace MÁS atractivo un lado en vez de equilibrar, «suele ganar el
otro lado». Sin datos de cuánto dinero hay en cada lado (eso no lo tenemos),
lo que SÍ se puede medir con `odds_snapshots.csv` (Pinnacle, Playdoit y
Bovada, varias fotos por partido desde días antes, 28-jul en adelante):

  H1 SEGUIR EL MOVIMIENTO: el lado cuya probabilidad sube ≥ 3 pts de la
     apertura al cierre, ¿gana más de lo que promete el CIERRE?
  H2 DESCONFIAR DEL QUE LA CASA ABARATA: el lado cuya probabilidad baja
     ≥ 3 pts, ¿gana menos de lo que promete el cierre?
  H3 «ALGO RARO»: Playdoit mueve al revés que Pinnacle (≥ 3 pts de
     diferencia en el movimiento): apostar en Playdoit el lado hacia el que
     fue Pinnacle, a la cuota de cierre de Playdoit.
  H4 NUESTRAS «SE METE»: las que la tarjeta tenía al pitido, por cómo se
     movió su cuota desde que se anunciaron (`_v348_cambios.pkl`).

Mercados: 1X2 (los tres lados), más de 2,5 y ambos marcan. Elige la mitad
vieja de fechas, juzga la nueva; bootstrap por partido.
"""
import json

import numpy as np
import pandas as pd

import _v344_precio as P

rng = np.random.default_rng(349)
MOV = 0.03


def _novig(cs):
    cs = [c for c in cs]
    if any((c is None) or (not np.isfinite(c)) or c <= 1 for c in cs):
        return [np.nan] * len(cs)
    inv = [1 / c for c in cs]
    s = sum(inv)
    return [x / s for x in inv]


def lados(df):
    """Una fila por (partido, casa, foto) con las probabilidades sin margen."""
    out = []
    for r in df.itertuples():
        h, x, a = _novig([r.odds_home, r.odds_draw, r.odds_away])
        o, u = _novig([r.odds_over25, r.odds_under25])
        si, no = _novig([r.odds_btts_yes, r.odds_btts_no])
        for lado, p, c in (('1', h, r.odds_home), ('X', x, r.odds_draw), ('2', a, r.odds_away),
                           ('mas25', o, r.odds_over25), ('menos25', u, r.odds_under25),
                           ('btts_si', si, r.odds_btts_yes), ('btts_no', no, r.odds_btts_no)):
            if np.isfinite(p):
                out.append((r.match_id, r.league_key, r.match_date, r.home_team, r.away_team,
                            r.bookmaker, r.dias_al_partido, lado, p, c))
    return pd.DataFrame(out, columns=['mid', 'liga', 'fecha', 'home', 'away', 'casa',
                                      'dias', 'lado', 'p', 'cuota'])


def resultados():
    """{(liga, fecha, home_norm, away_norm): (gh, ga)} de los históricos."""
    import glob
    res = {}
    for ruta in glob.glob('historico_*.csv'):
        liga = ruta[len('historico_'):-4]
        try:
            d = pd.read_csv(ruta, usecols=['date', 'home_team', 'away_team',
                                           'home_goals', 'away_goals'], low_memory=False)
        except Exception:
            continue
        d = d.dropna(subset=['home_goals', 'away_goals'])
        d = d[d.date >= '2026-07-01']
        for r in d.itertuples():
            res[(liga, str(r.date)[:10], P._norm(r.home_team), P._norm(r.away_team))] = (
                r.home_goals, r.away_goals)
    return res


def gano(lado, gh, ga):
    return {'1': gh > ga, 'X': gh == ga, '2': ga > gh, 'mas25': gh + ga > 2.5,
            'menos25': gh + ga < 2.5, 'btts_si': gh > 0 and ga > 0,
            'btts_no': not (gh > 0 and ga > 0)}[lado]


def boot(v, mids):
    um, inv = np.unique(mids, return_inverse=True)
    s, n = np.bincount(inv, weights=v), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in
          (rng.integers(0, len(um), len(um)) for _ in range(3000))]
    return round(float(np.mean(bs)), 4), round(float(np.percentile(bs, 5)), 4)


def resumen(g):
    """Acierto contra lo que promete el cierre (exceso) y rendimiento a la
    cuota de cierre de la propia casa."""
    if len(g) == 0:
        return {'n': 0}
    exc = (g.y - g.p_cierre).values
    roi = (g.y * g.c_cierre - 1).values
    return {'n': int(len(g)), 'partidos': int(g.mid.nunique()),
            'acierto': round(float(g.y.mean()), 4),
            'promete_cierre': round(float(g.p_cierre.mean()), 4),
            'exceso': boot(exc, g.mid.values),
            'roi': boot(roi, g.mid.values)}


def construir():
    d = pd.read_csv('odds_snapshots.csv', low_memory=False)
    d = d[(d.fase == 'snapshot') & d.bookmaker.isin(['Pinnacle', 'Playdoit'])]
    d = d[d.dias_al_partido >= 0]
    L = lados(d)
    res = resultados()
    filas = []
    for (mid, casa, lado), g in L.groupby(['mid', 'casa', 'lado']):
        if g.dias.nunique() < 2:
            continue
        a = g.loc[g.dias.idxmax()]
        c = g.loc[g.dias.idxmin()]
        k = (a.liga, str(a.fecha)[:10], P._norm(a.home), P._norm(a.away))
        if k not in res:
            continue
        gh, ga = res[k]
        filas.append({'mid': mid, 'fecha': str(a.fecha)[:10], 'liga': a.liga,
                      'casa': casa, 'lado': lado, 'p_ap': a.p, 'p_cierre': c.p,
                      'c_cierre': c.cuota, 'dias_ap': a.dias,
                      'y': int(gano(lado, gh, ga))})
    f = pd.DataFrame(filas)
    f['mov'] = f.p_cierre - f.p_ap
    return f


def main():
    f = construir()
    f.to_pickle('_v349_movimiento.pkl')
    print('filas', len(f), 'partidos', f.mid.nunique(), f.fecha.min(), f.fecha.max())
    corte = sorted(f.fecha.unique())[len(f.fecha.unique()) // 2]
    out = {'partidos': int(f.mid.nunique()), 'corte': corte}
    for casa in ('Pinnacle', 'Playdoit'):
        g = f[f.casa == casa]
        for nom, msk in (('H1_sube', g.mov >= MOV), ('H2_baja', g.mov <= -MOV),
                         ('estable', g.mov.abs() < MOV)):
            x = g[msk]
            out['%s_%s' % (casa, nom)] = {
                'todo': resumen(x), 'elige': resumen(x[x.fecha < corte]),
                'juzga': resumen(x[x.fecha >= corte])}
    # H3: Playdoit al revés que Pinnacle
    pv = f.pivot_table(index=['mid', 'lado', 'fecha'], columns='casa',
                       values=['mov', 'p_cierre', 'c_cierre', 'y'], aggfunc='first').dropna()
    pv.columns = ['%s_%s' % c for c in pv.columns]
    pv = pv.reset_index()
    h3 = pv[(pv.mov_Pinnacle >= MOV) & (pv.mov_Pinnacle - pv.mov_Playdoit >= MOV)]
    h3 = pd.DataFrame({'mid': h3.mid, 'fecha': h3.fecha, 'y': h3.y_Playdoit,
                       'p_cierre': h3.p_cierre_Playdoit, 'c_cierre': h3.c_cierre_Playdoit})
    out['H3_playdoit_al_reves'] = {'todo': resumen(h3), 'elige': resumen(h3[h3.fecha < corte]),
                                   'juzga': resumen(h3[h3.fecha >= corte])}
    # H4: nuestras «se mete» al pitido, por el movimiento de su cuota
    try:
        c = pd.read_pickle('_v348_cambios.pkl')
        c = c[c.sobrevive == 1]
        prim = c.sort_values('horas', ascending=False).drop_duplicates(['partido', 'apuesta'])
        ult = c.sort_values('horas').drop_duplicates(['partido', 'apuesta'])
        m = prim[['partido', 'apuesta', 'cuota', 'verde', 'dia']].merge(
            ult[['partido', 'apuesta', 'cuota']], on=['partido', 'apuesta'], suffixes=('_ap', '_ult'))
        m['dc'] = m.cuota_ult - m.cuota_ap
        h4 = {}
        for nom, msk in (('cuota_sube_(la casa la abarata)', m.dc >= 0.03),
                         ('cuota_baja_(la casa la respalda)', m.dc <= -0.03),
                         ('cuota_igual', m.dc.abs() < 0.03)):
            x = m[msk]
            h4[nom] = {'n': int(len(x)), 'acierto': round(float(x.verde.mean()), 4) if len(x) else None}
        out['H4_nuestras'] = h4
    except Exception as e:
        out['H4_nuestras'] = str(e)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    json.dump(out, open('_v349_movimiento.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
