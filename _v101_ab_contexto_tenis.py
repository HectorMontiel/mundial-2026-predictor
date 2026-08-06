#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Contexto del partido anterior, sobre el VECTOR DESPLEGADO de tenis.

En fútbol el contexto previo no aportó nada en ninguno de los seis mercados una
vez controlada la fuerza de hoy. El tenis es el sitio donde más razones hay para
que sí aporte: es deporte individual, se juega día sí día no durante un torneo,
y un partido a cinco sets de tres horas deja huella física que un equipo de
fútbol con veinte suplentes no sufre.

Se mide contra lo que HAY DESPLEGADO, no contra una base de juguete: ATP usa 6
features + IDF, WTA usa 13 + IDF. Y ojo con lo que ya está dentro:

  · WTA ya lleva DIFF_DIAS_DESCANSO, DIFF_PARTIDOS_14D y DIFF_HORAS_7D (v35).
    Para ese circuito el descanso y la carga NO son nuevos, y añadirlos otra vez
    mediría redundancia, no aportación.
  · ATP no las lleva (su vector es FEATURES[:6] + IDF), así que ahí sí son
    candidatas de pleno derecho.

Lo genuinamente nuevo en los dos circuitos es el RIVAL ANTERIOR —limpio de la
diferencia de ELO de hoy, que es la resta que en fútbol destapó una atribución
falsa— y el MARGEN del partido anterior.

Protocolo idéntico al de la v99.2: 6 pliegues walk-forward, juicio en los
tardíos, bootstrap pareado de log-loss por partido, veredicto por p5.
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contexto_previo as cp
import engines.tennis_engine as te

N_PLIEGUES = 6
JUICIO_DESDE = 3
BOOT = 4000
SEMILLA = 101
SALIDA = '_v101_ab_contexto_tenis.json'


def contexto_alineado(df: pd.DataFrame):
    """
    Contexto por fila, con la MISMA máscara que usa `_dataset`.

    `_dataset` sólo emite la fila cuando los dos jugadores ya tienen historial
    (`p1 in elo_g and p2 in elo_g`). Se reproduce ese filtro recorriendo el df
    en el mismo orden, en vez de suponer que las longitudes cuadran: si un día
    cambia el criterio del motor, esto se desalinearía en silencio y el A/B
    mediría ruido pareado con las filas equivocadas.
    """
    d = df.copy()
    d['_res'] = (d['Winner'].astype(str) == d['Player_1'].astype(str)).astype(float)
    d['_margen'] = np.nan
    ctx = cp.contexto(d, 'Date', 'Player_1', 'Player_2', '_res', '_margen',
                      ventaja_a=0.0)
    vistos = set()
    mask = np.zeros(len(d), dtype=bool)
    for i, (p1, p2) in enumerate(zip(d['Player_1'].astype(str),
                                     d['Player_2'].astype(str))):
        mask[i] = (p1 in vistos) and (p2 in vistos)
        vistos.add(p1)
        vistos.add(p2)
    return ctx, mask


def _wf(X, y, bordes):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    p = np.full(len(y), np.nan)
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
        p[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
    return p


def evaluar(Xa, Xb, y, etiqueta):
    n = len(y)
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    pa, pb = _wf(Xa, y, bordes), _wf(Xb, y, bordes)
    msk = ~np.isnan(pa) & ~np.isnan(pb) & (np.arange(n) >= bordes[JUICIO_DESDE])
    yy = y[msk]

    def ll(p):
        p = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(p) + (1 - yy) * np.log(1 - p))

    ea, eb = ll(pa), ll(pb)
    d = ea - eb
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    prob = float((bt > 0).mean())
    acc_a = float(((pa[msk] >= 0.5) == yy).mean())
    acc_b = float(((pb[msk] >= 0.5) == yy).mean())
    ver = 'ADOPTAR' if p5 > 0 and acc_b >= acc_a - 0.002 else 'RECHAZAR'
    print(f'  {etiqueta:<34} n={len(d):>6} · A {ea.mean():.5f} → B {eb.mean():.5f} '
          f'· mejora {d.mean():+.5f} · p5 {p5:+.5f} · P(>0) {prob:.1%} · {ver}')
    return {'n': int(len(d)), 'll_a': float(ea.mean()), 'll_b': float(eb.mean()),
            'mejora': float(d.mean()), 'p5': p5, 'prob_positiva': prob,
            'acc_a': acc_a, 'acc_b': acc_b, 'veredicto': ver}


def main():
    salida = {}
    for circuito in ('atp', 'wta'):
        eng = te.TennisEngine(circuito)
        df = eng.cargar_datos_historicos()
        Xa, y, fechas, _odds, _est = te.TennisEngine._dataset(df, eng.features)
        ctx, mask = contexto_alineado(df)
        print(f'\n=== {circuito.upper()} · vector desplegado '
              f'{len(eng.features)} features · {len(Xa)} filas del motor · '
              f'{int(mask.sum())} de la máscara replicada')
        if len(Xa) != int(mask.sum()):
            print('  ! la máscara no reproduce el filtro del motor — se aborta '
                  'este circuito en vez de medir filas descuadradas')
            salida[circuito] = {'veredicto': 'NO MEDIDO',
                                'motivo': 'máscara desalineada'}
            continue
        c = ctx.loc[mask].reset_index(drop=True)
        # rival anterior LIMPIO: se le quita la diferencia de ELO de hoy, que es
        # lo que en fútbol se hacía pasar por «venía de uno más fuerte».
        elo_hoy = ((c['ELO_A'] - c['ELO_B']) / cp.ESCALA_ELO).to_numpy(dtype=float)
        rival_prev = c['DIFF_ESCALON'].to_numpy(dtype=float) - elo_hoy
        Xa = np.asarray(Xa, dtype=float)

        bloques = {
            'rival anterior': rival_prev.reshape(-1, 1),
            'margen previo': c[['DIFF_MARGEN_PREV']].to_numpy(dtype=float),
            'sorpresa previa': c[['DIFF_SORPRESA_PREV']].to_numpy(dtype=float),
            'descanso+carga': c[['DIFF_DESCANSO', 'DIFF_CARGA']].to_numpy(dtype=float),
        }
        res = {}
        for nombre, extra in bloques.items():
            res[nombre] = evaluar(Xa, np.column_stack([Xa, extra]), y, nombre)
        todo = np.column_stack([rival_prev.reshape(-1, 1),
                                c[cp.COLUMNAS].to_numpy(dtype=float)])
        res['todo el contexto'] = evaluar(Xa, np.column_stack([Xa, todo]), y,
                                          'todo el contexto')
        salida[circuito] = res

    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
