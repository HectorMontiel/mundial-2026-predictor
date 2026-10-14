#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — Lo que la Soñadora necesita para cada CUOTA MÍNIMA por pata.

Tras las seis hipótesis de `_v373_*.py` (ninguna le gana a «la casa elige» a
1,45+ de forma sostenida: ni corregir el margen, ni el aprendiz, ni el contexto,
ni el método por equipo, ni el cruce de casas con precios simultáneos), la
Soñadora elige como la casa: en cada partido, la pata con la cuota en
[piso, piso + 0,5] que la casa ve más probable. Aquí se mide, en las escaleras
de Playdoit (28-ago → 9-oct, ambos lados, sin tarjetas ni córners de equipo):
  · por piso: acierto en dos mitades, cuota media, patas por día, ganancia;
  · la CALIBRACIÓN de esas patas (lo que acierta cada banda de la casa), para
    dar a cada pata su probabilidad medida;
  · boletos del día de N patas: enteros / días.
Escribe `_v373_pisos.json`."""
import importlib.util as iu
import json
import sys
import numpy as np
import pandas as pd
s = iu.spec_from_file_location('v371', '_v371_sencillas.py'); V = iu.module_from_spec(s); s.loader.exec_module(V)
PERD = ('tarjetas equipo', 'tarjetas total', 'corners equipo')


def elegir(x, piso):
    z = x[(x.cuota >= piso) & (x.cuota <= piso + 0.5) & ~x.mercado.isin(PERD)]
    z = z.sort_values('p_c', ascending=False).drop_duplicates('partido')
    return z.assign(gan=np.where(z.ok == 1, z.cuota - 1, -1.0))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    x = V.playdoit()
    corte = x.fecha.quantile(0.5)
    R = {'pisos': {}, 'calibracion': {}}
    todas = []
    for piso in (1.30, 1.45, 1.60, 1.70, 1.80):
        z = elegir(x, piso)
        todas.append(z)
        f = {'n': int(len(z)), 'acierto': round(float(z.ok.mean()), 4), 'promete': round(float(z.p_c.mean()), 4),
             'cuota': round(float(z.cuota.mean()), 3), 'gan_100': round(100 * float(z.gan.mean()), 1),
             'por_dia': round(float(z.groupby(z.fecha.dt.date).size().mean()), 1)}
        for t, m in (('A', z.fecha < corte), ('B', z.fecha >= corte)):
            q = z[m]
            f[t] = round(float(q.ok.mean()), 4)
        bol = {}
        zz = z.assign(dia=z.fecha.dt.strftime('%Y-%m-%d'))
        for n in (4, 6, 10, 15, 25):
            ent = dias = 0
            for _, g in zz.groupby('dia'):
                g = g.sort_values('p_c', ascending=False).head(n)
                if len(g) < n:
                    continue
                dias += 1
                ent += int(g.ok.all())
            bol[n] = [ent, dias]
        f['boletos'] = bol
        R['pisos']['%.2f' % piso] = f
    t = pd.concat(todas).drop_duplicates(['partido', 'mercado', 'lado_ap', 'linea'])
    for b, g in t.groupby(pd.cut(t.p_c, [0, .45, .50, .55, .60, .65, .70, .75, 1]), observed=True):
        R['calibracion'][str(b)] = {'n': int(len(g)), 'acierto': round(float(g.ok.mean()), 4),
                                    'promete': round(float(g.p_c.mean()), 4)}
    json.dump(R, open('_v373_pisos.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for k, v in R['pisos'].items():
        print(k, {a: v[a] for a in ('n', 'acierto', 'A', 'B', 'promete', 'cuota', 'gan_100', 'por_dia')}, v['boletos'])
    for k, v in R['calibracion'].items():
        print('  cal', k, v)


if __name__ == '__main__':
    main()
