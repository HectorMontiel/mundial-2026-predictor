#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v346 — ¿se pueden METER los tiros, como el resto de la tarjeta?

El usuario: «valida la metodología con todo el historial, no sólo lo
reciente, para que los tiros también se puedan meter». No hay cuotas de tiros
anteriores al 24-ago en ninguna fuente (`remates_snapshots.csv` y las fotos
del tablero empiezan ese día), así que se mide en dos partes, que es también
como se mide el resto del «se mete» de la app (más verdes, no ganarle al
cierre):

  A. HISTORIAL COMPLETO (sin cuotas, 2021-2026): el modelo entrenado con el
     70 % más viejo; en el 30 % reciente, cuando dice 70, 75, 80, 85, 90 %
     en una línea de tiros, ¿se cumple? Si cumple lo que promete en todo el
     historial, el porcentaje es de fiar.
  B. CONTRA PLAYDOIT (24-ago a 8-oct): una regla de «meter» como la del
     fútbol (v335: la casa y el modelo altos, cuota 1,15-1,35), elegida con
     la primera mitad, juzgada con la segunda. La puerta: que su acierto no
     baje el de lo que la app ya mete (≈ 79 %) — bootstrap p5 del acierto
     por encima de lo que promete y de ese listón.
"""
import json

import numpy as np
import pandas as pd

import _v344_tiros as T4
import _v345_tiros as V

rng = np.random.default_rng(346)


def parte_a():
    e = V._base(V.preparar())
    e = e[e.fecha < V.DESDE]
    corte = e.fecha.quantile(0.70)
    el, ju = e[e.fecha < corte], e[e.fecha >= corte]
    out = {'corte': str(corte.date()), 'n_juzga': int(len(ju))}
    for obj, lineas in (('tiros', [7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5, 14.5,
                                   15.5, 16.5, 17.5, 18.5]),
                        ('a_puerta', [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5])):
        m, k = V._modelo(obj, el, V.columnas('v345'))
        lam = np.clip(m.predict(ju[V.columnas('v345')]), 0.3, None)
        y = ju[obj].values
        filas = []
        for L in lineas:
            p = T4.nb_sf(lam, L, k)
            for lado, pl, yl in (('más', p, (y > L)), ('menos', 1 - p, (y <= L))):
                filas.append(pd.DataFrame({'p': pl, 'y': yl.astype(int), 'linea': L,
                                           'lado': lado, 'mid': ju.mid.values}))
        f = pd.concat(filas)
        f = f[f.p >= 0.70]
        f['banda'] = pd.cut(f.p, [0.70, 0.75, 0.80, 0.85, 0.90, 1.0], right=False)
        tb = f.groupby('banda', observed=True).agg(n=('y', 'size'), promete=('p', 'mean'),
                                                   acierta=('y', 'mean')).round(4)
        out[obj] = tb.reset_index().astype(str).to_dict('records')
        print(obj, '\n', tb)
    return out


def _acierto_boot(a, listón):
    """p5 de (acierto − listón) con bootstrap por partido."""
    um, inv = np.unique(a.mid.values, return_inverse=True)
    s, n = np.bincount(inv, weights=a.gana.values), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in
          (rng.integers(0, len(um), len(um)) for _ in range(3000))]
    return round(float(np.percentile(bs, 5) - listón), 4)


def candidatas(g, pmod, pcasa, cmin=1.15, cmax=1.35):
    """Las dos caras de cada línea que pasan la regla (una por fila)."""
    mas = (g.p_mod >= pmod) & (g.p_casa >= pcasa) & g.c_mas.between(cmin, cmax)
    men = ((1 - g.p_mod) >= pmod) & ((1 - g.p_casa) >= pcasa) & g.c_menos.between(cmin, cmax)
    a = pd.DataFrame({'mid': np.r_[g.mid[mas], g.mid[men]],
                      'equipo': np.r_[g.equipo[mas], g.equipo[men]],
                      'obj': np.r_[g.obj[mas], g.obj[men]],
                      'p': np.r_[g.p_mod[mas], 1 - g.p_mod[men]],
                      'pc': np.r_[g.p_casa[mas], 1 - g.p_casa[men]],
                      'cuota': np.r_[g.c_mas[mas], g.c_menos[men]],
                      'gana': np.r_[g.y[mas], 1 - g.y[men]]})
    # como la tarjeta: una apuesta por equipo y mercado, la más probable
    return a.sort_values('p', ascending=False).drop_duplicates(['mid', 'equipo', 'obj'])


def resumen(a, listón):
    if len(a) == 0:
        return {'n': 0}
    return {'n': int(len(a)), 'partidos': int(a.mid.nunique()),
            'acierto': round(float(a.gana.mean()), 4),
            'promete': round(float(a.p.mean()), 4),
            'casa': round(float(a.pc.mean()), 4),
            'cuota': round(float(a.cuota.mean()), 3),
            'roi': round(float((a.gana * a.cuota - 1).mean()), 4),
            'p5_sobre_liston': _acierto_boot(a, listón)}


def parte_b(liston=0.79):
    d = pd.read_pickle('_v345_lineas.pkl')
    corte = d.fecha.quantile(0.5)
    el, ju = d[d.fecha < corte], d[d.fecha >= corte]
    rej = []
    for pm in (0.70, 0.75, 0.80, 0.85):
        for pc in (0.0, 0.70, 0.74, 0.78):
            r = resumen(candidatas(el, pm, pc), liston)
            if r['n'] >= 40:
                rej.append(((pm, pc), r))
    # el criterio, fijado antes de mirar el juicio: el mayor p5 sobre el
    # listón con al menos 40 apuestas
    (pm, pc), r_el = max(rej, key=lambda x: x[1]['p5_sobre_liston'])
    return {'liston': liston, 'corte': str(corte.date()),
            'regla': {'modelo_min': pm, 'casa_min': pc, 'cuota': [1.15, 1.35]},
            'elige': r_el, 'juzga': resumen(candidatas(ju, pm, pc), liston),
            'todo': resumen(candidatas(d, pm, pc), liston),
            'rejilla': [(k, v['n'], v['acierto'], v['p5_sobre_liston']) for k, v in rej]}


if __name__ == '__main__':
    out = {'A_historial': parte_a(), 'B_playdoit': parte_b()}
    print(json.dumps(out['B_playdoit'], ensure_ascii=False, indent=1, default=str))
    json.dump(out, open('_v346_tiros_meter.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)
