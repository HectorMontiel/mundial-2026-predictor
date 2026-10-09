#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v350 — las escaleras de totales de Playdoit (2026) contra el marcador real.

Toma la última foto antes del partido (`_v350_escaleras.csv.gz`) y el
resultado (MLB: `historico_mlb.csv`; NFL: `historico_nfl_largo.csv`), y mira
por distancia a la línea principal lo que la casa dijo y lo que pasó. Es la
comprobación con partidos recientes de que los totales no llegan al ~80 %.
"""
import sys
import unicodedata

import numpy as np
import pandas as pd


def _n(t):
    t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().lower()
    return ''.join(c for c in t if c.isalnum())


def marcadores(ult):
    """El total real de cada partido con los mismos lectores que el marcador
    de la app (`partidos_jugados`): nflverse para la NFL y la API de la MLB."""
    import liquidador as lq
    import nfl_nflverse as nv
    import partidos_jugados as pj
    largo = nv.cargar()
    mlb = ult[ult.deporte == 'MLB']
    res_mlb = lq._resultados_mlb(mlb.fecha.min(), mlb.fecha.max()) if len(mlb) else {}
    out = {}
    for r in ult.drop_duplicates(['deporte', 'partido', 'fecha']).itertuples():
        p = {'deporte': r.deporte, 'partido': r.partido, 'fecha': r.fecha, 'inicio': r.inicio}
        m = (pj._marcador_nfl(p, largo) if r.deporte == 'NFL' else
             pj._marcador_mlb(p, res_mlb) if r.deporte == 'MLB' else None)
        if m:
            out[(r.deporte, r.partido, r.fecha)] = m[0] + m[1]
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    e = pd.read_csv('_v350_escaleras.csv.gz')
    e['ts'] = pd.to_datetime(e.ts, utc=True)
    e['ini'] = pd.to_datetime(e.inicio, errors='coerce', utc=True)
    e = e[e.ts <= e.ini + pd.Timedelta(hours=6)]          # foto antes (el inicio va en hora local)
    ult = e.sort_values('ts').groupby(['deporte', 'partido', 'fecha', 'linea']).tail(1)
    res = marcadores(ult)
    tot = []
    for r in ult.itertuples():
        t = res.get((r.deporte, r.partido, r.fecha))
        if t is None:
            continue
        tot.append({'deporte': r.deporte, 'partido': r.partido, 'offset': r.offset,
                    'p_mas': r.p_mas, 'mas': int(t > r.linea), 'menos': int(t < r.linea)})
    t = pd.DataFrame(tot)
    print('partidos con resultado:', t.groupby('deporte').partido.nunique().to_dict())
    for dep, g in t.groupby('deporte'):
        print('\n==', dep)
        # el lado probable de cada línea: «más» si la línea está por debajo de la principal
        g = g.assign(prob=np.where(g.offset < 0, g.p_mas, 1 - g.p_mas),
                     acierta=np.where(g.offset < 0, g.mas, g.menos),
                     dist=g.offset.abs())
        print(g[g.dist > 0].groupby('dist').agg(n=('acierta', 'size'), casa_dice=('prob', 'mean'),
                                                 acierto=('acierta', 'mean')).round(3).to_string())


if __name__ == '__main__':
    main()
