#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v100 — Leagues Cup: matar la localía ficticia.

Diagnóstico (v98/v99): el modelo predice 52,1 % de victoria local y se observa
40,9 %; con «local» de la Liga MX predice 53,0 % y gana el 27,5 %. El torneo se
juega casi entero en Estados Unidos, así que esa localía no existe.

Un matiz importante sobre CÓMO se quita
---------------------------------------
El modelo NO tiene una feature `is_home` que se pueda poner a cero: la ventaja
de campo está IMPLÍCITA en el conjunto de entrenamiento (11.000 partidos de
liga doméstica donde el local gana más). Ponerla a cero no es tocar una
variable, es darle a los partidos de Leagues Cup su PROPIO intercepto. Eso se
hace con indicadores que el clasificador pueda usar:

    neutral   · 1 si el partido es de Leagues Cup (cancha de hecho neutral)
    cruce     · 1 si los dos equipos son de ligas distintas
    host_mls  · +1 si el «local» es de la MLS, −1 si es de la Liga MX

Variantes que se miden, todas con el MISMO conjunto y el mismo protocolo:

    base      · lo desplegado
    neutral   · + indicador de cancha neutral
    completo  · + neutral + cruce + host_mls
    sin_local · se PREDICE el partido como si no hubiera local: se promedia la
                predicción con la del partido espejo. Es la forma más pura de
                «quitar la localía» y no necesita estimar nada.

Protocolo: se ajusta con lo anterior a cada edición y se juzga la edición
entera. La elección mira 2023-2024; el veredicto es 2025, que no se toca.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import leagues_cup as lc

BOOT = 4000
SEMILLA = 100
EDICIONES = (2023, 2024, 2025)
JUICIO = 2025


def preparar():
    df = lc.historico(con_ligas=True).reset_index(drop=True)
    elo, d = {}, np.zeros(len(df))
    ppg, fh, fa = {}, [], []
    for i, f in enumerate(df.itertuples(index=False)):
        h, a = f.home_team, f.away_team
        rh, ra = elo.get(h, 1500.0), elo.get(a, 1500.0)
        d[i] = rh - ra
        fh.append(np.mean(ppg.get(h, [])[-5:]) if ppg.get(h) else 1.3)
        fa.append(np.mean(ppg.get(a, [])[-5:]) if ppg.get(a) else 1.3)
        e = 1 / (1 + 10 ** ((ra - rh) / 400))
        s = 1.0 if f.home_goals > f.away_goals else (0.5 if f.home_goals == f.away_goals else 0.0)
        elo[h] = rh + 24 * (s - e)
        elo[a] = ra + 24 * ((1 - s) - (1 - e))
        r = 3 if f.home_goals > f.away_goals else (1 if f.home_goals == f.away_goals else 0)
        ppg.setdefault(h, []).append(r)
        ppg.setdefault(a, []).append(3 - r if r != 1 else 1)
    df['DIFF_ELO'], df['PPG_H'], df['PPG_A'] = d, fh, fa
    origen = {}
    for cl in ('mls', 'liga_mx'):
        sub = df[df.competicion == cl]
        for e in set(sub.home_team) | set(sub.away_team):
            origen.setdefault(e, cl)
    df['liga_h'] = df.home_team.map(origen)
    df['liga_a'] = df.away_team.map(origen)
    df['anio'] = df.date.dt.year
    df['y'] = np.where(df.home_goals > df.away_goals, 0,
                       np.where(df.home_goals == df.away_goals, 1, 2))
    df['neutral'] = (df.competicion == 'leagues_cup').astype(float)
    df['cruce'] = ((df.liga_h != df.liga_a) & df.liga_h.notna()
                   & df.liga_a.notna() & (df.competicion == 'leagues_cup')).astype(float)
    df['host_mls'] = np.where(df.competicion != 'leagues_cup', 0.0,
                              np.where(df.liga_h == 'mls', 1.0, -1.0))
    return df


COLS = {
    'base': ['DIFF_ELO', 'DIF_PPG', 'SUM_PPG'],
    'neutral': ['DIFF_ELO', 'DIF_PPG', 'SUM_PPG', 'neutral'],
    'completo': ['DIFF_ELO', 'DIF_PPG', 'SUM_PPG', 'neutral', 'cruce', 'host_mls'],
}


def matriz(d, cols):
    d = d.copy()
    d['DIF_PPG'] = d.PPG_H - d.PPG_A
    d['SUM_PPG'] = d.PPG_H + d.PPG_A
    return d[cols].to_numpy(dtype=float)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    df = preparar()
    print(f'agrupado {len(df)} · leagues_cup '
          f'{int((df.competicion == "leagues_cup").sum())}')
    res = {}

    for ed in EDICIONES:
        te = df[(df.competicion == 'leagues_cup') & (df.anio == ed)]
        tr = df[df.date < te.date.min()]
        if te.empty or tr.empty:
            continue
        y_te = te.y.to_numpy()
        elo_pred = np.where(te.DIFF_ELO.to_numpy() > 0, 0, 2)
        res.setdefault('ELO', {})[ed] = (elo_pred == y_te)

        for nombre, cols in COLS.items():
            sc = StandardScaler().fit(matriz(tr, cols))
            m = LogisticRegression(max_iter=3000).fit(
                sc.transform(matriz(tr, cols)), tr.y)
            p = m.predict_proba(sc.transform(matriz(te, cols)))
            res.setdefault(nombre, {})[ed] = (p.argmax(1) == y_te)
            res.setdefault(nombre + '_ll', {})[ed] = float(
                log_loss(y_te, p, labels=[0, 1, 2]))
            if nombre == 'completo':
                # sin_local: se promedia con la predicción del partido espejo
                esp = te.copy()
                esp['DIFF_ELO'] = -esp['DIFF_ELO']
                esp[['PPG_H', 'PPG_A']] = esp[['PPG_A', 'PPG_H']].values
                esp['host_mls'] = -esp['host_mls']
                p_esp = m.predict_proba(sc.transform(matriz(esp, cols)))
                # el espejo predice el partido al revés: se reordena 1X2
                p_sim = np.column_stack([p_esp[:, 2], p_esp[:, 1], p_esp[:, 0]])
                p_neu = (p + p_sim) / 2.0
                res.setdefault('sin_local', {})[ed] = (p_neu.argmax(1) == y_te)
                res.setdefault('sin_local_ll', {})[ed] = float(
                    log_loss(y_te, p_neu, labels=[0, 1, 2]))

    print()
    print(f"{'variante':<12}" + ''.join(f'{e:>10}' for e in EDICIONES) + f"{'GLOBAL':>10}")
    resumen = {}
    for nombre in ('base', 'neutral', 'completo', 'sin_local', 'ELO'):
        if nombre not in res:
            continue
        fila = ''
        todos = []
        for e in EDICIONES:
            v = res[nombre].get(e)
            fila += f'{v.mean():>10.4f}' if v is not None else ' ' * 10
            if v is not None:
                todos.append(v)
        g = np.concatenate(todos)
        print(f'{nombre:<12}{fila}{g.mean():>10.4f}')
        resumen[nombre] = {'global': float(g.mean()),
                           'por_edicion': {str(e): float(res[nombre][e].mean())
                                           for e in EDICIONES if e in res[nombre]}}

    print()
    print(f'=== JUICIO: edición {JUICIO} (no mirada para elegir) ===')
    rng = np.random.default_rng(SEMILLA)
    base_j = res['ELO'][JUICIO]
    for nombre in ('base', 'neutral', 'completo', 'sin_local'):
        if nombre not in res or JUICIO not in res[nombre]:
            continue
        v = res[nombre][JUICIO]
        d = v.astype(float) - base_j.astype(float)
        bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
        p5, p95 = np.percentile(bt, [5, 95])
        ll = res.get(nombre + '_ll', {}).get(JUICIO)
        print(f'  {nombre:<12} acc={v.mean():.4f} (ELO {base_j.mean():.4f}) '
              f'ventaja {d.mean():+.4f} p5 {p5:+.4f} P(>0)={(bt > 0).mean():.1%}'
              + (f' · ll {ll:.4f}' if ll else ''))
        resumen.setdefault(nombre, {}).update(
            {'juicio_acc': float(v.mean()), 'juicio_ventaja': float(d.mean()),
             'juicio_p5': float(p5), 'juicio_prob_pos': float((bt > 0).mean())})

    json.dump(resumen, open('_v100_localia_leagues_cup.json', 'w'), indent=1)
    print('\n-> _v100_localia_leagues_cup.json')


if __name__ == '__main__':
    main()
