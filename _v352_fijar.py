#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v352 — ¿Fijar la apuesta a la hora de apostar?

El usuario, con Kashiwa–Vissel delante (cinco apuestas 📌 distintas a lo
largo del día, ninguna al pitido, dos en rojo): «las apuestas cambian
mucho, siento que es ruido; quiero que sea fácil saber cuál es la segura».
Y: «un filtro por el reloj: los partidos que hay que apostar a las seis,
porque a esa hora ya está definido lo que se mete».

La propuesta: la apuesta OFICIAL de cada partido es la que la tarjeta da en
la primera foto del precálculo dentro de la ventana de apostar (desde
`hora_apuesta.VENTANA_H` antes del partido). Desde ahí se queda FIJA. Antes,
lo que se enseña es provisional y no cuenta.

Se compara, partido a partido, con las fotos del git (3-9 oct):
  A  al pitido      la última foto antes del partido (lo que cuenta hoy)
  B  fijada         la primera foto dentro de la ventana, sin cambios después
  C  primera        la primera vez que salió (v346: peor)
  D  todo lo 📌     todo lo que se anunció alguna vez (lo que ve el usuario)
Acierto, cuántas apuestas por partido, y bootstrap por partido B − A.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import _v343_estabilidad as E
import _v346_fijada as F
import hora_apuesta as ha

rng = np.random.default_rng(352)


def construir():
    E.pg.de_partido = lambda *a, **k: None
    ft = F.fotos()
    filas = []
    for p in E.jugados():
        if p.get('goles_home') is None:
            continue
        par, ini = str(p.get('partido')), p.get('inicio')
        if par not in ft or not ini:
            continue
        try:
            t0 = E._ts(ini)
        except Exception:
            continue
        dep = str(p.get('deporte') or 'Fútbol')
        ven = ha.VENTANA_H.get(dep, 4.0)
        f = sorted(x for x in ft[par] if E._ts(x[0]) < t0)
        if not f:
            continue
        dentro = [x for x in f if (t0 - E._ts(x[0])).total_seconds() / 3600 <= ven]
        sets = {
            'A_pitido': F._metidas(f[-1][1]),
            'B_fijada': F._metidas(dentro[0][1]) if dentro else None,
            'C_primera': next((F._metidas(r) for _, r in f if F._metidas(r)), []),
        }
        # B2: lo que la tarjeta enseña en el momento de abrir la ventana (la
        # última foto ANTES de esa hora); si no la hay, la primera de dentro.
        # Es la que se puede dar por definitiva justo a la hora de apostar.
        fuera_v = [x for x in f if (t0 - E._ts(x[0])).total_seconds() / 3600 > ven]
        if dentro or fuera_v:
            sets['B2_al_abrir'] = F._metidas((fuera_v[-1] if fuera_v else dentro[0])[1])
        todas, vistas = [], set()
        for _, recos in f:
            for r in F._metidas(recos):
                if r['apuesta'] not in vistas:
                    vistas.add(r['apuesta'])
                    todas.append(r)
        sets['D_todo'] = todas
        antes_ven = set()
        for ts, recos in f:
            if (t0 - E._ts(ts)).total_seconds() / 3600 > ven:
                antes_ven |= {r['apuesta'] for r in F._metidas(recos)}
        dentro_set = set()
        for ts, recos in dentro:
            dentro_set |= {r['apuesta'] for r in F._metidas(recos)}
        for nom, s in sets.items():
            if s is None:
                continue
            for ap, ok, c in E.liquidar(p, s):
                filas.append({'partido': par, 'deporte': dep, 'dia': str(t0.date()),
                              'version': nom, 'apuesta': ap, 'verde': ok, 'cuota': c,
                              'hay_fijada': int(bool(dentro)),
                              'n_antes': len(antes_ven), 'n_dentro': len(dentro_set),
                              'fotos_dentro': len(dentro)})
    return pd.DataFrame(filas)


def boot_dif(d, a, b, n=3000):
    """Acierto de la versión a menos la b, remuestreando partidos."""
    pa = d[d.version == a].groupby('partido').verde.agg(['sum', 'size'])
    pb = d[d.version == b].groupby('partido').verde.agg(['sum', 'size'])
    ps = sorted(set(pa.index) & set(pb.index))
    pa, pb = pa.loc[ps].values, pb.loc[ps].values
    out = []
    for _ in range(n):
        i = rng.integers(0, len(ps), len(ps))
        out.append(pa[i, 0].sum() / pa[i, 1].sum() - pb[i, 0].sum() / pb[i, 1].sum())
    return round(float(np.mean(out)), 4), round(float(np.percentile(out, 5)), 4), len(ps)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if os.path.exists('_v352_filas.pkl'):
        d = pd.read_pickle('_v352_filas.pkl')
    else:
        d = construir()
        d.to_pickle('_v352_filas.pkl')
    out = {'partidos': int(d.partido.nunique()), 'dias': [d.dia.min(), d.dia.max()]}
    for dep, g in [('todos', d)] + list(d.groupby('deporte')):
        if g.partido.nunique() < 15:
            continue
        # sólo partidos con foto dentro de la ventana, para comparar lo mismo
        g = g[g.hay_fijada == 1]
        r = g.groupby('version').agg(apuestas=('verde', 'size'), partidos=('partido', 'nunique'),
                                     acierto=('verde', 'mean'), cuota=('cuota', 'mean'))
        r['rojas'] = g.groupby('version').verde.apply(lambda s: int((s == 0).sum()))
        r['por_partido'] = (r.apuestas / r.partidos).round(2)
        print('\n=====', dep)
        print(r.round(4).to_string())
        out[dep] = {'tabla': r.round(4).reset_index().to_dict('records'),
                    'B_menos_A': boot_dif(g, 'B_fijada', 'A_pitido'),
                    'B_menos_C': boot_dif(g, 'B_fijada', 'C_primera'),
                    'B_menos_D': boot_dif(g, 'B_fijada', 'D_todo'),
                    'apuestas_distintas_antes_de_la_ventana': round(float(
                        g.drop_duplicates('partido').n_antes.mean()), 2),
                    'apuestas_distintas_dentro': round(float(
                        g.drop_duplicates('partido').n_dentro.mean()), 2)}
        out[dep]['B2_menos_A'] = boot_dif(g, 'B2_al_abrir', 'A_pitido')
        out[dep]['B2_menos_D'] = boot_dif(g, 'B2_al_abrir', 'D_todo')
        print('B2−A', out[dep]['B2_menos_A'], ' B2−D', out[dep]['B2_menos_D'])
        print('B−A', out[dep]['B_menos_A'], ' B−C', out[dep]['B_menos_C'],
              ' B−D', out[dep]['B_menos_D'])
        print('apuestas distintas por partido: antes de la ventana %.2f · dentro %.2f'
              % (out[dep]['apuestas_distintas_antes_de_la_ventana'],
                 out[dep]['apuestas_distintas_dentro']))
    print('\npartidos sin foto dentro de la ventana:',
          int(d[d.hay_fijada == 0].partido.nunique()), 'de', out['partidos'])
    out['sin_foto_en_ventana'] = int(d[d.hay_fijada == 0].partido.nunique())
    json.dump(out, open('_v352_fijar.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
