#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99.1 — A/B del Índice de Dispersión de Forma en tenis.

Rama A: ELO global + ELO de superficie (la base).
Rama B: A + DIFF_IDF (forma relativa a lo que el ELO predeciría).

Se juzga sobre 108.657 partidos con CUOTA DE CIERRE real, así que además de
precisión y log-loss se puede responder lo único que decide la Capa 1: si la
feature acerca el modelo al mercado.

La ventana del IDF (5, 10 o 15) se ELIGE en los pliegues tempranos y se JUZGA
en los tardíos. Y se mira aparte el decil de IDF EXTREMO, que es donde la
hipótesis dice que tiene que notarse — el caso Rublev.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import indice_forma as idf_mod
from _v99_edge_tenis import preparar

N_PLIEGUES = 6
ELECCION = (0, 1, 2)
JUICIO = (3, 4, 5)
BOOT = 3000
SEMILLA = 991


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss

    salida = {}
    for circuito in ('atp', 'wta'):
        df = preparar(circuito)
        # El IDF necesita el ELO de cada lado; `preparar` da la DIFERENCIA, así
        # que se reconstruyen unos ELO absolutos equivalentes (el esperado sólo
        # depende de la diferencia, así que basta con centrarlos).
        df['ELO_A'] = 1500.0 + df.DIFF_ELO / 2.0
        df['ELO_B'] = 1500.0 - df.DIFF_ELO / 2.0
        n = len(df)
        bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
        print(f'=== {circuito.upper()}: {n} partidos con cuota')

        idfs = {}
        for v in idf_mod.VENTANAS:
            idfs[v] = idf_mod.idf_por_participante(
                df, 'Player_1', 'Player_2', 'ELO_A', 'ELO_B', 'y',
                ventana=v)['DIFF_IDF'].to_numpy()

        y = df.y.to_numpy()
        base = df[['DIFF_ELO', 'DIFF_ELO_SUP']].to_numpy() / 100.0
        imp = df.p_mkt.to_numpy()
        o1, o2 = df.Odd_1.to_numpy(), df.Odd_2.to_numpy()

        def evaluar(X, pliegues):
            p = np.full(n, np.nan)
            for i in range(N_PLIEGUES):
                ini, fin = bordes[i], bordes[i + 1]
                m = LogisticRegression(max_iter=2000).fit(X[:ini], y[:ini])
                p[ini:fin] = m.predict_proba(X[ini:fin])[:, 1]
            msk = np.zeros(n, dtype=bool)
            for i in pliegues:
                msk[bordes[i]:bordes[i + 1]] = True
            msk &= ~np.isnan(p)
            return p, msk

        res = {}
        for nombre, X in [('A (sin IDF)', base)] + [
                (f'B · ventana {v}', np.column_stack([base, idfs[v]]))
                for v in idf_mod.VENTANAS]:
            p, msk = evaluar(X, ELECCION)
            ll = float(log_loss(y[msk], np.column_stack([1 - p[msk], p[msk]]), labels=[0, 1]))
            acc = float(((p[msk] >= 0.5) == y[msk]).mean())
            res[nombre] = {'ll_elec': ll, 'acc_elec': acc, 'X': X}
            print(f'   ELECCIÓN {nombre:<16} log-loss {ll:.5f}  acc {acc:.4f}')

        cand = {k: v for k, v in res.items() if k.startswith('B')}
        mejor = min(cand, key=lambda k: cand[k]['ll_elec'])
        print(f'   -> elegida: {mejor}')

        print(f'   {"JUICIO":<10}{"log-loss":>11}{"acc":>9}{"Brier":>9}'
              f'{"ROI EV>2%":>11}{"p5":>9}')
        rng = np.random.default_rng(SEMILLA)
        juicio = {}
        for nombre in ('A (sin IDF)', mejor):
            p, msk = evaluar(res[nombre]['X'], JUICIO)
            yy, pp = y[msk], p[msk]
            ll = float(log_loss(yy, np.column_stack([1 - pp, pp]), labels=[0, 1]))
            acc = float(((pp >= 0.5) == yy).mean())
            br = float(np.mean((pp - yy) ** 2))
            pnl = []
            for lado in (1, 2):
                pr = pp if lado == 1 else 1 - pp
                cu = (o1 if lado == 1 else o2)[msk]
                ac = (yy == 1) if lado == 1 else (yy == 0)
                sel = (pr * cu - 1) > 0.02
                pnl.append(np.where(ac[sel], cu[sel] - 1, -1.0))
            pnl = np.concatenate(pnl)
            bt = np.array([pnl[rng.integers(0, len(pnl), len(pnl))].mean()
                           for _ in range(BOOT)]) if len(pnl) > 50 else np.array([np.nan])
            roi, p5 = float(np.nanmean(bt)), float(np.nanpercentile(bt, 5))
            print(f'   {nombre:<10}{ll:>11.5f}{acc:>9.4f}{br:>9.4f}{roi:>10.2%}{p5:>9.2%}')
            juicio[nombre] = {'ll': ll, 'acc': acc, 'brier': br,
                              'roi': roi, 'p5': p5, 'n': int(msk.sum())}

        # --- donde la hipótesis dice que tiene que notarse ---------------
        v_mejor = int(mejor.split()[-1])
        d = np.abs(idfs[v_mejor])
        _, msk = evaluar(res[mejor]['X'], JUICIO)
        corte = np.nanpercentile(d[msk], 90)
        ext = msk & (d >= corte)
        print(f'   decil de IDF EXTREMO (|IDF| >= {corte:.4f}): n={int(ext.sum())}')
        for nombre in ('A (sin IDF)', mejor):
            p, _ = evaluar(res[nombre]['X'], JUICIO)
            acc = float(((p[ext] >= 0.5) == y[ext]).mean())
            ll = float(log_loss(y[ext], np.column_stack([1 - p[ext], p[ext]]), labels=[0, 1]))
            print(f'      {nombre:<16} acc {acc:.4f}  log-loss {ll:.5f}')
            juicio.setdefault(nombre, {}).update({'acc_extremo': acc, 'll_extremo': ll})
        # y el mercado, como referencia en ese mismo decil
        acc_m = float(((imp[ext] >= 0.5) == y[ext]).mean())
        ll_m = float(log_loss(y[ext], np.column_stack([1 - imp[ext], imp[ext]]), labels=[0, 1]))
        print(f'      {"MERCADO":<16} acc {acc_m:.4f}  log-loss {ll_m:.5f}')

        base_ll = juicio['A (sin IDF)']['ll']
        mej_ll = juicio[mejor]['ll']
        veredicto = 'ADOPTAR' if mej_ll < base_ll else 'RECHAZAR'
        print(f'   VEREDICTO: {veredicto} (log-loss {base_ll:.5f} -> {mej_ll:.5f})')
        salida[circuito] = {'elegida': mejor, 'juicio': juicio,
                            'mercado_extremo': {'acc': acc_m, 'll': ll_m},
                            'veredicto': veredicto}
        print()

    json.dump(salida, open('_v991_ab_idf_tenis.json', 'w'), indent=1)
    print('-> _v991_ab_idf_tenis.json')


if __name__ == '__main__':
    main()
