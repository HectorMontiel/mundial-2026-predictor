# -*- coding: utf-8 -*-
"""v357 — antes y después de la metodología nueva (sin «córners: más de» y la
tercera «se mete» filtrada), sobre la réplica de la tarjeta (889 partidos,
19-sep → 9-oct): por mitades, por día y en los dos últimos días.
Escribe `_v357_antes_despues.json`."""
import json
import re
import sys

import pandas as pd

import _v356_anticipar as A


def tarjeta(d):
    eq = re.compile(r'^Goles [^:]+: Menos de ')
    out = []
    for par, g in d.groupby('partido', sort=False):
        met = g[g.metida]
        if met.empty:
            continue
        q = met
        malas = met[met.corner_mas]
        if len(malas):
            q = met.drop(malas.index)
            c = g[(g.motivo.fillna('') == '') & ~g.metida & ~g.corner_mas
                  & ~g.apuesta.isin(set(q.apuesta)) & ~g.mercado.isin(set(q.mercado))]
            q = pd.concat([q, c.sort_values('p', ascending=False).head(len(malas))])
        if len(q):
            c = g[(g.motivo.fillna('') == '') & ~g.apuesta.isin(set(q.apuesta)) & ~g.corner_mas
                  & ~g.mercado.isin(set(q.mercado))].sort_values('p', ascending=False)
            if len(c) and c.p.iloc[0] >= 0.78 and not eq.match(c.apuesta.iloc[0]):
                q = pd.concat([q, c.head(1).assign(tercera=True)])
        out.append(q)
    return pd.concat(out)


def r(t):
    return {'verdes': int(t.acierto.sum()), 'rojas': int((1 - t.acierto).sum()),
            'acierto': round(100 * float(t.acierto.mean()), 1) if len(t) else None}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    d = A.cargar()
    d['corner_mas'] = d.apuesta.str.match(r'^Córners: Más de ')
    antes, despues = d[d.metida], tarjeta(d)
    out = {'tramos': {}, 'dias': {}}
    for nombre, f in (('19-sep a 29-sep (elegir)', 'elige'), ('30-sep a 9-oct (juzgar)', 'juzga')):
        out['tramos'][nombre] = {'antes': r(antes[antes.tramo == f]),
                                 'despues': r(despues[despues.tramo == f])}
    out['tramos']['todo'] = {'antes': r(antes), 'despues': r(despues),
                             'boot': A.boot_dif(antes, despues)}
    for dia in sorted(d.dia.unique()):
        out['dias'][dia] = {'antes': r(antes[antes.dia == dia]), 'despues': r(despues[despues.dia == dia])}
    out['terceras'] = r(despues[despues.get('tercera', False) == True])
    print(json.dumps(out['tramos'], ensure_ascii=False, indent=1))
    for dia, v in out['dias'].items():
        print(dia, v['antes'], '->', v['despues'])
    print('terceras', out['terceras'])
    json.dump(out, open('_v357_antes_despues.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
