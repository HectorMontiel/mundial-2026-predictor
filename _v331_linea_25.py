# -*- coding: utf-8 -*-
"""
v331 — H15: LA LÍNEA 2,5 DE GOLES PROMETE DE MÁS EN LA FRANJA «METER».

Apareció al mirar la calibración por tipo de apuesta en el histórico (70-80 %):
    Más de 2,5    prometía 72 % → 66 % (mirar y juzgar, los dos tramos)
    Menos de 2,5  prometía 73 % → 70 / 68 %
    Más de 1,5 y Menos de 3,5 cumplen (75 / 74 %).
y en las reales de la app: Más de 2,5 13 apuestas 73,7 → 61,5 %; Menos de 2,5
5 apuestas 70,8 → 60,0 %.

LA PRUEBA, en los tres sitios, con la regla de hoy ya aplicada:
  A. histórico de goles (modelo 70-80 %, cuota < 1,35 si la hay), contra el
     control «quitar el mismo número de menor probabilidad»;
  B. las reales de la app;
  C. la simulación de la tarjeta (_v324_candidatas, lo que se «metía»).
Y, aparte, el meta-modelo de goles SIN «ambos marcan» (su probabilidad en el
histórico está rota: 70-80 % prometido, 52 % real; la app la calcula distinto
desde la v326) para ver lo que aportan de verdad los equipos.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3315)
NO_METER = ('Doble y goles', 'Remates', 'Remates a puerta', 'Handicap')


def boot(s, qa, qb, n_iter=2000):
    g = pd.DataFrame({'f': s.fecha.values, 'v': s.verde.values,
                      'a': (~qa).values, 'b': (~qb).values})
    g['va'], g['vb'] = g.v * g.a, g.v * g.b
    A = g.groupby('f')[['va', 'a', 'vb', 'b']].sum().values
    d = []
    for _ in range(n_iter):
        x = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        if x[1] and x[3]:
            d.append(x[0] / x[1] - x[2] / x[3])
    return 100 * np.percentile(d, 5), 100 * np.mean(d)


def ctrl(s, n):
    m = pd.Series(False, index=s.index)
    m[s.prob.sort_values(kind='mergesort').index[:n]] = True
    return m


def informe(nombre, s, quita, corte, contra_control=True):
    print('\n=== %s — %d apuestas, %.1f %%; la regla quita %d (%.0f %%)'
          % (nombre, len(s), 100 * s.verde.mean(), quita.sum(),
             100 * quita.mean()))
    q = s[quita]
    print('   las que quita: prometían %.1f %% · acertaron %.1f %%'
          % (100 * q.prob.mean(), 100 * q.verde.mean()))
    out = {}
    for t, m in (('mirar', s.fecha < corte), ('juzgar', s.fecha >= corte)):
        a = s[m]
        qa = quita[m]
        r = 100 * a[~qa].verde.mean()
        c = 100 * a[~ctrl(a, int(qa.sum()))].verde.mean()
        print('   %-6s sin regla %.1f %% (%d) · con regla %.1f %% (%d) · control '
              '%.1f %% · rojos %d → %d' % (t, 100 * a.verde.mean(), len(a), r,
                                          int((~qa).sum()), c,
                                          int((1 - a.verde).sum()),
                                          int((1 - a[~qa].verde).sum())))
        out[t] = {'sin': 100 * a.verde.mean(), 'con': r, 'control': c,
                  'n': int(len(a)), 'n_con': int((~qa).sum())}
    J = s[s.fecha >= corte]
    qj = quita[s.fecha >= corte]
    p5s, ms = boot(J, qj, pd.Series(False, index=J.index))
    p5c, mc = boot(J, qj, ctrl(J, int(qj.sum())))
    print('   juzgar: frente a no hacer nada %+.2f (p5 %+.2f) · frente al control '
          '%+.2f (p5 %+.2f)' % (ms, p5s, mc, p5c))
    out.update({'p5_sin': p5s, 'media_sin': ms, 'p5_ctrl': p5c, 'media_ctrl': mc})
    return out


def main():
    res = {}
    # A. histórico
    c = pd.read_pickle('_v331_candidatas_hist.pkl')
    g = c[(c.grupo == 'goles') & ~c.apuesta.str.startswith('Ambos')].copy()
    dias = np.sort(g.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    quita = g.apuesta.str.contains('2.5', regex=False)
    res['historico'] = informe('A. HISTÓRICO goles (sin ambos marcan)', g, quita, corte)
    anios = {}
    for a, s in g.groupby(g.fecha.dt.year):
        q = s.apuesta.str.contains('2.5', regex=False)
        if q.sum() >= 30:
            anios[a] = (100 * s[q].prob.mean(), 100 * s[q].verde.mean(), int(q.sum()))
    print('   la línea 2,5 por año (prometido → real, n): ' + ' · '.join(
        '%d %.0f→%.0f (%d)' % (a, x[0], x[1], x[2]) for a, x in anios.items()))
    res['historico']['anios'] = anios
    # B. reales
    r = pd.read_csv('_v331_meter_app.csv')
    r = r[(r.deporte == 'Fútbol') & ~r.mercado.isin(NO_METER)
          & r.prob.between(0.70, 0.80) & (r.cuota < 1.35)].copy()
    r['fecha'] = pd.to_datetime(r.dia)
    q = r.apuesta.str.match(r'Goles: (Más|Menos) de 2\.5$')
    res['reales'] = informe('B. REALES de la app (todas las «meter» de fútbol)',
                            r, q, pd.Timestamp('2026-10-03'))
    # C. simulación de la tarjeta
    v = pd.read_csv('_v324_candidatas.csv.gz')
    v = v[v.metida & v.acierto.notna()].copy()
    v['fecha'] = pd.to_datetime(v.dia)
    v['verde'] = v.acierto
    v['prob'] = v.ajustada
    d2 = np.sort(v.fecha.unique())
    q = v.apuesta.str.match(r'Goles: (Más|Menos) de 2\.5$')
    res['simulacion'] = informe('C. SIMULACIÓN de la tarjeta (v324, lo «metido»)',
                                v, q, d2[int(len(d2) * 0.7)])
    print('   en la simulación, «metidas» por línea de goles:')
    for ap, x in v[v.apuesta.str.startswith('Goles: ')].groupby('apuesta'):
        if len(x) >= 5:
            print('      %-22s n %3d · prometía %.1f %% · real %.1f %%'
                  % (ap, len(x), 100 * x.prob.mean(), 100 * x.verde.mean()))
    json.dump(res, open('_v331_linea_25.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
