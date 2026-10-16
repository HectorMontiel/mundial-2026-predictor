#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v376 — ¿El portero ayuda a acertar en la NHL? (la teoría del amigo del usuario:
«el portero es una verga, para un chingo de tiros»).

Datos: la API pública de la NHL (api-web.nhle.com): por cada partido de temporada
regular, el portero TITULAR de cada equipo y sus tiros recibidos y paradas. Con eso,
antes de cada partido, el % de paradas que llevaba ese titular en la temporada
(sólo partidos anteriores, mínimo 5 titularidades). Se empareja con los cierres de
`_v359_nhl_cierres.csv` (ganador y total de goles con su cuota).

Se mide, por temporada (dos mitades = temporadas distintas):
  · TOTAL: cuando los dos titulares llevan buen % de paradas, ¿el «menos» acierta más
    de lo que dice la casa? (y el «más» cuando los dos son malos);
  · GANADOR: el favorito con mejor portero que el rival contra el favorito con peor.
Escribe `_v376_porteros.json` (y guarda lo bajado en `_v376_porteros_partidos.csv`).
"""
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

BASE = 'https://api-web.nhle.com/v1'
CACHE = '_v376_porteros_partidos.csv'
TEMPORADAS = {2023: ('2023-10-10', '2024-04-18'), 2024: ('2024-10-04', '2025-04-17')}
S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0'


def _get(url):
    for _ in range(3):
        try:
            r = S.get(url, timeout=25)
            if r.ok:
                return r.json()
        except Exception:
            pass
    return None


def ids_del_dia(dia):
    d = _get('%s/score/%s' % (BASE, dia)) or {}
    return [(g['id'], dia) for g in d.get('games') or [] if g.get('gameType') == 2]


def caja(par):
    gid, dia = par
    b = _get('%s/gamecenter/%s/boxscore' % (BASE, gid)) or {}
    fila = {'gid': gid, 'dia': dia,
            'home': ((b.get('homeTeam') or {}).get('placeName') or {}).get('default'),
            'away': ((b.get('awayTeam') or {}).get('placeName') or {}).get('default'),
            'gh': (b.get('homeTeam') or {}).get('score'), 'ga': (b.get('awayTeam') or {}).get('score')}
    for lado, k in (('h', 'homeTeam'), ('a', 'awayTeam')):
        gs = ((b.get('playerByGameStats') or {}).get(k) or {}).get('goalies') or []
        t = next((g for g in gs if g.get('starter')), None)
        if t:
            sa = str(t.get('saveShotsAgainst') or '0/0').split('/')
            fila['g_%s' % lado] = t.get('playerId')
            fila['sv_%s' % lado] = int(sa[0]) if sa[0].isdigit() else None
            fila['sa_%s' % lado] = int(sa[1]) if len(sa) > 1 and sa[1].isdigit() else None
    return fila


def bajar():
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE)
    dias = []
    for a, (i, f) in TEMPORADAS.items():
        d = dt.date.fromisoformat(i)
        while d <= dt.date.fromisoformat(f):
            dias.append(d.isoformat())
            d += dt.timedelta(days=1)
    with ThreadPoolExecutor(6) as ex:
        pares = [p for lst in ex.map(ids_del_dia, dias) for p in lst]
        filas = list(ex.map(caja, pares))
    df = pd.DataFrame(filas)
    df.to_csv(CACHE, index=False)
    return df


def previo(df):
    """El % de paradas del titular ANTES de cada partido (sólo lo anterior)."""
    df = df.sort_values('dia').reset_index(drop=True)
    acc = {}
    for lado in ('h', 'a'):
        df['pre_%s' % lado] = np.nan
    for i, r in df.iterrows():
        for lado in ('h', 'a'):
            g = r.get('g_%s' % lado)
            if pd.isna(g):
                continue
            k = (int(g), str(r.dia)[:4] if str(r.dia)[5:7] >= '09' else str(int(str(r.dia)[:4]) - 1))
            sv, sa, n = acc.get(k, (0, 0, 0))
            if n >= 5 and sa:
                df.at[i, 'pre_%s' % lado] = sv / sa
        for lado in ('h', 'a'):
            g = r.get('g_%s' % lado)
            if pd.isna(g) or pd.isna(r.get('sa_%s' % lado)):
                continue
            k = (int(g), str(r.dia)[:4] if str(r.dia)[5:7] >= '09' else str(int(str(r.dia)[:4]) - 1))
            sv, sa, n = acc.get(k, (0, 0, 0))
            acc[k] = (sv + r['sv_%s' % lado], sa + r['sa_%s' % lado], n + 1)
    return df


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    df = previo(bajar())
    c = pd.read_csv('_v359_nhl_cierres.csv')
    c = c[c.tipo == 'regular']
    c['dia'] = c.fecha.astype(str)
    # los cierres (ESPN) dicen «Tampa Bay Lightning»; la API, «Tampa Bay»: se
    # empata por fecha (±1 día, por la zona horaria) y ciudad al principio del
    # nombre; si hay dos candidatos (las dos de Nueva York), se descarta
    filas = []
    por_dia = {d_: g for d_, g in c.groupby('dia')}
    for r in df.itertuples(index=False):
        if not isinstance(r.home, str) or not isinstance(r.away, str):
            continue
        cands = []
        for d_ in (r.dia, (dt.date.fromisoformat(r.dia) + dt.timedelta(days=1)).isoformat()):
            g = por_dia.get(d_)
            if g is None:
                continue
            ok = g[g.home.str.startswith(r.home) & g.away.str.startswith(r.away)]
            cands += ok.to_dict('records')
        if len(cands) == 1:
            x = cands[0]
            fila = r._asdict()
            fila.update({k: x[k] for k in ('total', 'over_c', 'under_c', 'ml_home', 'ml_away')})
            filas.append(fila)
    m = pd.DataFrame(filas)
    m = m.dropna(subset=['pre_h', 'pre_a', 'total', 'over_c', 'under_c', 'ml_home', 'ml_away'])
    m['temporada_c'] = np.where(m.dia.str[5:7] >= '09', m.dia.str[:4], (m.dia.str[:4].astype(int) - 1).astype(str))
    tot = m.gh + m.ga
    io, iu = 1 / m.over_c, 1 / m.under_c
    m['p_under'] = iu / (io + iu)
    m['ok_under'] = (tot < m.total).astype(float)
    m.loc[tot == m.total, 'ok_under'] = np.nan          # empate con la línea entera: nulo
    m['sv_suma'] = m.pre_h + m.pre_a
    R = {'partidos': int(len(m)), 'temporadas': sorted(m.temporada_c.unique().tolist())}
    q = m.sv_suma.quantile([1 / 3, 2 / 3]).values
    m['grupo'] = np.where(m.sv_suma >= q[1], 'porteros buenos', np.where(m.sv_suma <= q[0], 'porteros malos', 'medio'))
    R['total'] = {}
    for (t, gru), g in m.dropna(subset=['ok_under']).groupby(['temporada_c', 'grupo']):
        cu = g.under_c
        gan_u = np.where(g.ok_under == 1, cu - 1, -1).mean()
        gan_o = np.where(g.ok_under == 0, g.over_c - 1, -1).mean()
        R['total']['%s · %s' % (t, gru)] = {
            'n': int(len(g)), 'menos_acierta': round(float(g.ok_under.mean()), 4),
            'casa_dice_menos': round(float(g.p_under.mean()), 4),
            'gan_menos_100': round(100 * float(gan_u), 1), 'gan_mas_100': round(100 * float(gan_o), 1)}
    # ganador: favorito con mejor / peor portero
    imh, ima = 1 / m.ml_home, 1 / m.ml_away
    ph = imh / (imh + ima)
    fav_h = ph >= 0.5
    gana_fav = np.where(fav_h, m.gh > m.ga, m.ga > m.gh)
    sv_fav = np.where(fav_h, m.pre_h, m.pre_a)
    sv_riv = np.where(fav_h, m.pre_a, m.pre_h)
    cuota_fav = np.where(fav_h, m.ml_home, m.ml_away)
    pfav = np.maximum(ph, 1 - ph)
    m2 = pd.DataFrame({'t': m.temporada_c, 'gana': gana_fav.astype(float), 'cuota': cuota_fav, 'p': pfav,
                       'mejor': np.where(sv_fav - sv_riv >= 0.01, 'favorito con mejor portero (+1 pt)',
                                         np.where(sv_fav - sv_riv <= -0.01, 'favorito con peor portero (−1 pt)',
                                                  'porteros parecidos'))})
    R['ganador'] = {}
    for (t, gru), g in m2.groupby(['t', 'mejor']):
        R['ganador']['%s · %s' % (t, gru)] = {
            'n': int(len(g)), 'gana': round(float(g.gana.mean()), 4), 'casa_dice': round(float(g.p.mean()), 4),
            'gan_100': round(100 * float(np.where(g.gana == 1, g.cuota - 1, -1).mean()), 1)}
    json.dump(R, open('_v376_porteros.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(R, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
