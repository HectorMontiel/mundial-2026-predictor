#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v358 — variantes de la regla de la NFL (hándicap y puntos alternativos):
meta 75 / 78 / 80 % y el modelo de la NFL como filtro (que vea el partido del
lado de la apuesta). Elegir con 2010-2014, juzgar con 2015-2025 y mirar 2026.
Y las cuotas reales de Playdoit a esas probabilidades (tableros del 10-oct).
Escribe `_v358_nfl_variantes.json`."""
import json
import sys

import numpy as np
import pandas as pd

import _v358_nfl_lineas as L


def modelo():
    import _v325_nfl as V
    import nfl_estado as ne
    import nfl_nflverse as nv
    ds, _ = ne.dataset(nv.cargar())
    x = V.variables(ds)
    return V.walk_forward(x, range(2010, 2027))[['game_id', 'm_pred', 't_pred']]


def acuerdo(g):
    mod_fav = np.where(g.spread_line >= 0, g.m_pred, -g.m_pred)
    dif = mod_fav - g.s
    dt = g.t_pred - g.t0
    return np.select([g.lado == 'favorito', g.lado == 'no_favorito', g.lado == 'mas'],
                     [dif >= 0, dif <= 0, dt >= 0], dt <= 0)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = L.cargar()
    r = modelo()
    filas = []
    for s in range(2010, 2027):
        fo = L.Forma(d[d.season < s], 'k')
        filas.append(L.filas_pred(fo, d[d.season == s]))
    f = pd.concat(filas).merge(d[['game_id', 'spread_line']], on='game_id').merge(r, on='game_id', how='left')
    f['acuerdo'] = acuerdo(f)
    out = {}
    tramos = (('elige_2010_14', f.season <= 2014), ('juzga_2015_25', (f.season >= 2015) & (f.season <= 2025)),
              ('t2026', f.season == 2026))
    for nombre, cond in (('meta75', None), ('meta78', None), ('meta80', None),
                         ('meta75_modelo', 'acuerdo'), ('meta75_modelo_fav_mas', 'parcial')):
        meta = {'meta75': .75, 'meta78': .78, 'meta80': .80}.get(nombre, .75)
        x = f
        if cond == 'acuerdo':
            x = f[f.acuerdo == 1]
        elif cond == 'parcial':
            x = f[(f.acuerdo == 1) | f.lado.isin(['no_favorito', 'menos'])]
        el = L.regla(x, meta)
        out[nombre] = {}
        for t, c in tramos:
            m = el.season.isin(f[c].season.unique())
            g = el[m]
            n_part = f[c].game_id.nunique()
            out[nombre][t] = {'n': int(len(g)), 'por_partido': round(len(g) / max(n_part, 1), 2),
                              'acierta': round(float(g.gana.mean()), 4) if len(g) else None,
                              'p5': L.boot(g.gana) if len(g) else None,
                              'por_lado': {k: round(float(v.gana.mean()), 3) for k, v in g.groupby('lado')}}
        print(nombre, json.dumps(out[nombre], ensure_ascii=False))
    # las cuotas de Playdoit hoy
    try:
        tab = json.load(open(sys.argv[1], encoding='utf-8'))
    except Exception:
        tab = {}
    import nba_lineas as nl
    fo = L.Forma(d[d.season <= 2025], 'k')
    filas = []
    for par, det in tab.items():
        h, a = par.split(' vs ', 1)
        nl_apodo = nl._apodo
        nl._apodo = lambda n: str(n).split()[-1].lower()
        t = nl.del_tablero(det, h, a)
        nl._apodo = nl_apodo
        if not t:
            continue
        hc = t.get('handicap') or {}
        h0 = float(hc.get('principal_local', 0))
        s = abs(h0)
        for lado_eq, h0e in (('local', h0), ('visita', -h0)):
            for lin, c in (hc.get(lado_eq) or {}).items():
                k = float(lin) - h0e
                if k <= 0:
                    continue
                tipo = 'favorito' if h0e < 0 else 'no_favorito'
                umbral = (s - k) if tipo == 'favorito' else (s + k)
                filas.append({'partido': par, 'tipo': tipo, 'k': k, 'cuota': c,
                              'p': fo.p(tipo, umbral, s, 44)})
        tt = t.get('totales') or {}
        if tt:
            t0 = float(tt['principal'])
            for lado in ('mas', 'menos'):
                for lin, c in (tt.get(lado) or {}).items():
                    k = (t0 - float(lin)) if lado == 'mas' else (float(lin) - t0)
                    if k > 0:
                        filas.append({'partido': par, 'tipo': lado, 'k': k, 'cuota': c,
                                      'p': fo.p(lado, float(lin), s, t0)})
    q = pd.DataFrame(filas)
    if len(q):
        q['p_casa'] = 1 / q.cuota
        for meta in (.75, .78, .80):
            e = q[(q.p >= meta) & (q.cuota >= 1.15)].sort_values('p').groupby(['partido', 'tipo']).head(1)
            out['playdoit_meta%d' % int(meta * 100)] = {
                'n': int(len(e)), 'partidos': int(e.partido.nunique()),
                'cuota_media': round(float(e.cuota.mean()), 3) if len(e) else None,
                'p_media': round(float(e.p.mean()), 3) if len(e) else None,
                'por_tipo': e.groupby('tipo').size().to_dict()}
            print('playdoit meta', meta, out['playdoit_meta%d' % int(meta * 100)])
        out['playdoit_max_p'] = q.groupby('tipo').p.max().round(3).to_dict()
        print('max p por tipo', out['playdoit_max_p'])
    json.dump(out, open('_v358_nfl_variantes.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
