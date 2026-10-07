# -*- coding: utf-8 -*-
"""
v331 — ¿UN ROJO DE UN EQUIPO AVISA DE SU SIGUIENTE ROJO?

La teoría del usuario: «analiza los patrones de las rojas para que en los
siguientes partidos de esos equipos no nos vuelva a pasar». Se prueba en
grande, con los dos históricos FUERA DE MUESTRA:

  · pick_ledger_totales.csv — goles (más/menos de 1,5 / 2,5 / 3,5 y BTTS)
  · pick_ledger.csv         — resultado (ganador y doble oportunidad)

En cada partido se simula la «meter» de la app: la candidata con el modelo
entre 70 y 80 % (la franja de la regla; NO se abre), una por partido y por
histórico. Se liquida con el marcador real. Luego, para cada equipo, se mira
qué le pasó a SU apuesta anterior y se mide si eso cambia la siguiente.

Reglas que se prueban (todas QUITAN apuestas, ninguna añade):
  R1  saltar si el último partido de alguno de los dos equipos fue rojo
  R2  saltar si los dos últimos de un equipo fueron rojos
  R3  saltar si el último rojo fue del MISMO mercado (p. ej. «menos» y otra «menos»)
  R4  saltar si el equipo lleva ≥ 2 rojos en sus últimos 4
  R5  saltar si el último rojo fue «por sorpresa» (el modelo daba ≥ 75 %)

LA PRUEBA, la de siempre: los días se ordenan; el 70 % primero sirve para
mirar y el 30 % último para juzgar. En el tramo de juzgar se hace bootstrap
por día de la diferencia de acierto (con regla − sin regla): se adopta sólo si
p5 > 0 y si además mejora en el tramo de mirar. Se informa también lo que se
pierde en número de apuestas.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
LO, HI = 0.70, 0.80
rng = np.random.default_rng(323)


def equipos(mid: str):
    t = str(mid).split('_')
    if len(t) < 3:
        return None, None
    return t[1], '_'.join(t[2:])


def candidatas_goles() -> pd.DataFrame:
    d = pd.read_csv('pick_ledger_totales.csv')
    filas = []
    for ln in ('1.5', '2.5', '3.5'):
        p = d['p_over_%s' % ln]
        real = d['over_%s_real' % ln]
        filas.append(pd.DataFrame({'idx': d.index, 'mercado': 'goles',
                                   'dir': 'mas', 'apuesta': 'Más de ' + ln,
                                   'prob': p, 'verde': real}))
        filas.append(pd.DataFrame({'idx': d.index, 'mercado': 'goles',
                                   'dir': 'menos', 'apuesta': 'Menos de ' + ln,
                                   'prob': 1 - p, 'verde': 1 - real}))
    filas.append(pd.DataFrame({'idx': d.index, 'mercado': 'btts', 'dir': 'si',
                               'apuesta': 'Ambos marcan sí',
                               'prob': d.p_btts, 'verde': d.btts_real}))
    filas.append(pd.DataFrame({'idx': d.index, 'mercado': 'btts', 'dir': 'no',
                               'apuesta': 'Ambos marcan no',
                               'prob': 1 - d.p_btts, 'verde': 1 - d.btts_real}))
    c = pd.concat(filas)
    c = c[(c.prob >= LO) & (c.prob <= HI) & c.verde.notna()]
    c = c.sort_values('prob', ascending=False).drop_duplicates('idx')
    c = c.join(d[['liga', 'match_id', 'fecha']], on='idx')
    c['fuente'] = 'goles'
    return c


def candidatas_resultado() -> pd.DataFrame:
    d = pd.read_csv('pick_ledger.csv')
    res = d.resultado          # 1 local, 0 empate?, 2 visita? — se deduce abajo
    gh, ga = d.goles_local, d.goles_visit
    loc, emp, vis = (gh > ga).astype(int), (gh == ga).astype(int), (gh < ga).astype(int)
    filas = [
        ('Gana local', 'local', d.p_home, loc),
        ('Gana visita', 'visita', d.p_away, vis),
        ('Local o empate', 'local', d.p_home + d.p_draw, loc | emp),
        ('Visita o empate', 'visita', d.p_away + d.p_draw, vis | emp),
        ('Local o visita', 'sin_empate', d.p_home + d.p_away, loc | vis),
    ]
    c = pd.concat([pd.DataFrame({'idx': d.index, 'mercado': 'resultado',
                                 'dir': dr, 'apuesta': ap, 'prob': p,
                                 'verde': v}) for ap, dr, p, v in filas])
    c = c[(c.prob >= LO) & (c.prob <= HI) & gh.reindex(c.idx).notna().values]
    c = c.sort_values('prob', ascending=False).drop_duplicates('idx')
    c = c.join(d[['liga', 'match_id', 'fecha']], on='idx')
    c['fuente'] = 'resultado'
    return c


def con_memoria(c: pd.DataFrame) -> pd.DataFrame:
    """Añade, por equipo, lo que le pasó a sus apuestas ANTERIORES."""
    c = c.copy()
    c['fecha'] = pd.to_datetime(c.fecha)
    c['home'], c['away'] = zip(*c.match_id.map(equipos))
    c = c.sort_values(['fecha', 'match_id']).reset_index(drop=True)
    hist = {}                     # (liga, equipo) -> [(fecha, rojo, dir, prob)]
    cols = {k: [] for k in ('r1', 'r2', 'r3', 'r4', 'r5', 'con_hist')}
    for fecha, g in c.groupby('fecha', sort=True):
        for _, r in g.iterrows():
            f = {k: False for k in cols}
            for eq in (r.home, r.away):
                h = hist.get((r.liga, eq), [])
                if not h:
                    continue
                f['con_hist'] = True
                u = h[-1]
                f['r1'] |= u[1] == 1
                f['r2'] |= len(h) >= 2 and h[-1][1] == 1 and h[-2][1] == 1
                f['r3'] |= u[1] == 1 and u[2] == r.dir
                f['r4'] |= sum(x[1] for x in h[-4:]) >= 2
                f['r5'] |= u[1] == 1 and u[3] >= 0.75
            for k in cols:
                cols[k].append(f[k])
        for _, r in g.iterrows():       # se apunta DESPUÉS de todo el día
            for eq in (r.home, r.away):
                hist.setdefault((r.liga, eq), []).append(
                    (fecha, 1 - int(r.verde), r.dir, float(r.prob)))
    for k, v in cols.items():
        c[k] = v
    return c


def evalua(c: pd.DataFrame, nombre: str) -> dict:
    dias = np.sort(c.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    out = {}
    print('\n=== %s — %d apuestas, %d días, base %.1f %% (corte %s)'
          % (nombre, len(c), len(dias), 100 * c.verde.mean(),
             str(corte)[:10]))
    print('  tras rojo vs tras verde (sólo equipos con historial):')
    h = c[c.con_hist]
    for k in ('r1',):
        a, b = h[h[k]], h[~h[k]]
        print('    último rojo  : %.1f %% (n %d) · exceso sobre el modelo %+.1f pts'
              % (100 * a.verde.mean(), len(a), 100 * (a.verde - a.prob).mean()))
        print('    último verde : %.1f %% (n %d) · exceso sobre el modelo %+.1f pts'
              % (100 * b.verde.mean(), len(b), 100 * (b.verde - b.prob).mean()))
    for k in ('r1', 'r2', 'r3', 'r4', 'r5'):
        res = {}
        for tramo, s in (('mirar', c[c.fecha < corte]),
                         ('juzgar', c[c.fecha >= corte])):
            q = s[~s[k]]
            res[tramo] = (100 * s.verde.mean(), 100 * q.verde.mean(),
                          len(s), len(q))
        s = c[c.fecha >= corte]
        por_dia = s.groupby('fecha')
        tot = por_dia.verde.agg(['sum', 'size'])
        kep = s[~s[k]].groupby('fecha').verde.agg(['sum', 'size']).reindex(
            tot.index, fill_value=0)
        idx = np.arange(len(tot))
        difs = []
        for _ in range(2000):
            b = rng.choice(idx, len(idx))
            A = tot.iloc[b].sum()
            K = kep.iloc[b].sum()
            if K['size'] == 0:
                continue
            difs.append(K['sum'] / K['size'] - A['sum'] / A['size'])
        p5 = 100 * np.percentile(difs, 5)
        m, j = res['mirar'], res['juzgar']
        pasa = (m[1] > m[0]) and p5 > 0
        print('  %s  mirar %.1f→%.1f (%d→%d) · juzgar %.1f→%.1f (%d→%d) · '
              'p5 %+.2f pts → %s' % (k.upper(), m[0], m[1], m[2], m[3], j[0],
                                     j[1], j[2], j[3], p5,
                                     'PASA' if pasa else 'no pasa'))
        out[k] = {'mirar': m, 'juzgar': j, 'p5': p5, 'pasa': bool(pasa)}
    return out


def main():
    res = {}
    cg = con_memoria(candidatas_goles())
    cr = con_memoria(candidatas_resultado())
    res['goles'] = evalua(cg, 'GOLES (más/menos y BTTS)')
    res['resultado'] = evalua(cr, 'RESULTADO (ganador y doble oportunidad)')
    json.dump(res, open('_v331_memoria_equipos.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
