#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — Leagues Cup: barrido de variantes contra la línea base ELO.

El primer intento (`_v97_wf_leagues_cup.py`) se quedó corto: el modelo
agrupado saca 43,52 % frente al 44,44 % del ELO. Antes de dar la competición
por no modelable hay una hipótesis concreta que probar.

LA HIPÓTESIS
------------
El ELO «agrupado» no está realmente agrupado. La MLS y la Liga MX sólo se
cruzan en la Leagues Cup, y antes de 2023 eso eran 14 partidos en total: los
dos grupos de equipos arrancan en 1500 y evolucionan **en burbujas separadas**,
así que un ELO de 1560 mexicano y uno de 1560 estadounidense no significan lo
mismo. La diferencia de ELO entre un equipo de la MLS y uno de la Liga MX es,
literalmente, una resta entre dos escalas distintas.

Se prueban por tanto:
  base        · ELO agrupado + forma (lo que ya se midió)
  offset      · igual, pero con un DESPLAZAMIENTO por liga estimado con los
                partidos cruzados anteriores al corte (sin mirar el futuro)
  cruce       · igual que offset + indicador de si el local es de la MLS
  elo_solo    · sólo DIFF_ELO con el offset, logística binaria+empate
  gbm         · árbol regularizado sobre el conjunto de offset

Protocolo: ELEGIR mirando 2023-2024, JUZGAR en 2025 (regla de oro 3).
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import leagues_cup as lc

BOOT = 4000
SEMILLA = 97
ELECCION = (2023, 2024)
JUICIO = (2025,)


def elo_por_fila(df, k=24.0):
    elo, diffs, eh_l, ea_l = {}, np.zeros(len(df)), [], []
    for i, f in enumerate(df.itertuples(index=False)):
        h, a = f.home_team, f.away_team
        rh, ra = elo.get(h, 1500.0), elo.get(a, 1500.0)
        diffs[i] = rh - ra
        eh_l.append(rh); ea_l.append(ra)
        e = 1 / (1 + 10 ** ((ra - rh) / 400))
        s = 1.0 if f.home_goals > f.away_goals else (0.5 if f.home_goals == f.away_goals else 0.0)
        elo[h] = rh + k * (s - e)
        elo[a] = ra + k * ((1 - s) - (1 - e))
    return diffs, np.array(eh_l), np.array(ea_l)


def preparar():
    df = lc.historico(con_ligas=True).reset_index(drop=True)
    d, eh, ea = elo_por_fila(df)
    df['ELO_H'], df['ELO_A'], df['DIFF_ELO'] = eh, ea, d
    # liga de origen de cada club (la que más veces lo lista)
    origen = {}
    for cl in ('mls', 'liga_mx'):
        sub = df[df.competicion == cl]
        for e in set(sub.home_team) | set(sub.away_team):
            origen.setdefault(e, cl)
    df['liga_h'] = df.home_team.map(origen)
    df['liga_a'] = df.away_team.map(origen)
    # forma: ppg de los ultimos 5
    ppg, fh, fa = {}, [], []
    for f in df.itertuples(index=False):
        h, a = f.home_team, f.away_team
        fh.append(np.mean(ppg.get(h, [])[-5:]) if ppg.get(h) else 1.3)
        fa.append(np.mean(ppg.get(a, [])[-5:]) if ppg.get(a) else 1.3)
        r = 3 if f.home_goals > f.away_goals else (1 if f.home_goals == f.away_goals else 0)
        ppg.setdefault(h, []).append(r)
        ppg.setdefault(a, []).append(3 - r if r != 1 else 1)
    df['PPG_H'], df['PPG_A'] = fh, fa
    df['y'] = np.where(df.home_goals > df.away_goals, 0,
                       np.where(df.home_goals == df.away_goals, 1, 2))
    df['anio'] = df.date.dt.year
    return df


def offset_ligas(tr):
    """
    Cuánto ELO vale de más una liga que la otra, medido SÓLO con los partidos
    cruzados del tramo de entrenamiento.

    Se ajusta el desplazamiento `c` que hace que el ELO explique los cruces:
    con los partidos MLS-vs-LigaMX anteriores al corte se compara el resultado
    real con el que predeciría el ELO crudo, y la diferencia media (en puntos
    de ELO) es el desfase entre escalas.
    """
    cruz = tr[(tr.competicion == 'leagues_cup') &
              (tr.liga_h.notna()) & (tr.liga_a.notna()) &
              (tr.liga_h != tr.liga_a)]
    if len(cruz) < 10:
        return 0.0
    # puntuación real del local en esos cruces
    s = np.where(cruz.home_goals > cruz.away_goals, 1.0,
                 np.where(cruz.home_goals == cruz.away_goals, 0.5, 0.0))
    # signo: +1 si el local es de la MLS
    signo = np.where(cruz.liga_h == 'mls', 1.0, -1.0)
    d = cruz.DIFF_ELO.to_numpy()
    # busca c que minimiza el error cuadratico de la esperanza ELO
    mejor, mejor_err = 0.0, np.inf
    for c in np.arange(-150, 151, 5.0):
        e = 1 / (1 + 10 ** (-(d + signo * c) / 400))
        err = float(np.mean((s - e) ** 2))
        if err < mejor_err:
            mejor, mejor_err = float(c), err
    return mejor


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler
    from lightgbm import LGBMClassifier

    df = preparar()
    lcs = df[df.competicion == 'leagues_cup']
    print(f'agrupado {len(df)} · leagues_cup {len(lcs)} · '
          f'cruces MLS-MX {int(((lcs.liga_h != lcs.liga_a) & lcs.liga_h.notna() & lcs.liga_a.notna()).sum())}')

    variantes = {}
    for ed in (2023, 2024, 2025):
        te = df[(df.competicion == 'leagues_cup') & (df.anio == ed)]
        tr = df[df.date < te.date.min()]
        if te.empty or tr.empty:
            continue
        c = offset_ligas(tr)
        print(f'  {ed}: offset MLS-vs-LigaMX estimado = {c:+.0f} puntos de ELO '
              f'(con {len(tr[(tr.competicion=="leagues_cup")])} cruces previos)')

        def X(d):
            sg_h = np.where(d.liga_h == 'mls', 1.0, -1.0)
            sg_a = np.where(d.liga_a == 'mls', 1.0, -1.0)
            de_off = d.DIFF_ELO.to_numpy() + c * (sg_h - sg_a) / 2.0
            cruce = (d.liga_h != d.liga_a).astype(float).to_numpy()
            return {
                'base': np.column_stack([d.DIFF_ELO / 100, d.PPG_H - d.PPG_A,
                                         d.PPG_H + d.PPG_A]),
                'offset': np.column_stack([de_off / 100, d.PPG_H - d.PPG_A,
                                           d.PPG_H + d.PPG_A]),
                'cruce': np.column_stack([de_off / 100, d.PPG_H - d.PPG_A,
                                          d.PPG_H + d.PPG_A, cruce, sg_h]),
                'elo_solo': np.column_stack([de_off / 100]),
            }

        Xtr_all, Xte_all = X(tr), X(te)
        ytr, yte = tr.y.to_numpy(), te.y.to_numpy()
        # ELO base con offset aplicado (linea base «lista»)
        sg_h = np.where(te.liga_h == 'mls', 1.0, -1.0)
        sg_a = np.where(te.liga_a == 'mls', 1.0, -1.0)
        de_te = te.DIFF_ELO.to_numpy() + c * (sg_h - sg_a) / 2.0
        base_crudo = (np.where(te.DIFF_ELO > 0, 0, 2) == yte)
        base_off = (np.where(de_te > 0, 0, 2) == yte)

        for nombre in ('base', 'offset', 'cruce', 'elo_solo'):
            sc = StandardScaler().fit(Xtr_all[nombre])
            m = LogisticRegression(max_iter=3000).fit(sc.transform(Xtr_all[nombre]), ytr)
            p = m.predict_proba(sc.transform(Xte_all[nombre]))
            ok = m.predict(sc.transform(Xte_all[nombre])) == yte
            variantes.setdefault(nombre, {}).setdefault(ed, {})
            variantes[nombre][ed] = {'ok': ok,
                                     'll': float(log_loss(yte, p, labels=[0, 1, 2]))}
        g = LGBMClassifier(n_estimators=150, num_leaves=5, max_depth=3,
                           learning_rate=0.05, min_child_samples=60,
                           reg_lambda=20.0, random_state=42, verbose=-1)
        g.fit(Xtr_all['cruce'], ytr)
        pg = g.predict_proba(Xte_all['cruce'])
        variantes.setdefault('gbm', {})[ed] = {
            'ok': g.predict(Xte_all['cruce']) == yte,
            'll': float(log_loss(yte, pg, labels=[0, 1, 2]))}
        variantes.setdefault('ELO_crudo', {})[ed] = {'ok': base_crudo, 'll': None}
        variantes.setdefault('ELO_offset', {})[ed] = {'ok': base_off, 'll': None}

    print()
    print(f"{'variante':<14} " + ' '.join(f'{e:>16}' for e in (2023, 2024, 2025)))
    for nombre, por_ed in variantes.items():
        cel = []
        for e in (2023, 2024, 2025):
            v = por_ed.get(e)
            cel.append(f"{v['ok'].mean():.4f}"
                       + (f"/{v['ll']:.3f}" if v and v['ll'] else '      ') if v else ' ' * 16)
        print(f'{nombre:<14} ' + ' '.join(f'{c:>16}' for c in cel))

    print()
    print('=== ELECCION (2023-2024) ===')
    rank = []
    for nombre, por_ed in variantes.items():
        if nombre.startswith('ELO'):
            continue
        oks = np.concatenate([por_ed[e]['ok'] for e in ELECCION if e in por_ed])
        lls = [por_ed[e]['ll'] for e in ELECCION if e in por_ed and por_ed[e]['ll']]
        rank.append((nombre, float(np.mean(lls)) if lls else np.inf, float(oks.mean())))
    rank.sort(key=lambda t: t[1])
    for n, l, a in rank:
        print(f'   {n:<14} ll={l:.4f}  acc={a:.4f}')
    elegida = rank[0][0]
    print(f'   -> elegida: {elegida}')

    print()
    print('=== JUICIO (2025, no mirado para elegir) ===')
    rng = np.random.default_rng(SEMILLA)
    ok_e = np.concatenate([variantes[elegida][e]['ok'] for e in JUICIO])
    for base in ('ELO_crudo', 'ELO_offset'):
        ok_b = np.concatenate([variantes[base][e]['ok'] for e in JUICIO])
        d = ok_e.astype(float) - ok_b.astype(float)
        bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
        p5, p50, p95 = np.percentile(bt, [5, 50, 95])
        print(f'   {elegida} {ok_e.mean():.4f}  vs  {base} {ok_b.mean():.4f}  '
              f'ventaja {d.mean():+.4f} (p5 {p5:+.4f} · p95 {p95:+.4f}) '
              f'P(>0)={(bt > 0).mean():.1%}  n={len(d)}')

    salida = {'elegida': elegida,
              'por_variante': {n: {str(e): {'acc': float(v['ok'].mean()), 'll': v['ll']}
                                   for e, v in pe.items()}
                               for n, pe in variantes.items()}}
    json.dump(salida, open('_v97_familias_leagues_cup.json', 'w'), indent=1)
    print('\n-> _v97_familias_leagues_cup.json')


if __name__ == '__main__':
    main()
