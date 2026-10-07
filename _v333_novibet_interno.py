# -*- coding: utf-8 -*-
"""
v333 — VALIDACIÓN 2: ¿NOVIBET PAGA DE MÁS SUS MERCADOS SECUNDARIOS?

Con la última foto de Novibet antes de cada partido (las 263 versiones de
`cuotas_mx.json` en git, 10-sep a 7-oct), se despejan sus λ de SU 1X2 y SU
más/menos 2,5 sin margen (`motor_mercado`), y con ellas el precio justo de
lo que deriva: las otras líneas de goles, ambos marcan, doble oportunidad y
hándicap asiático. Valor = probabilidad justa × cuota de Novibet. Como todo
sale de la MISMA foto, no hay referencia desfasada (lo que tumbó el «error de
precio» contra Pinnacle en la v332).

Se mide con el resultado real: acierto y rendimiento por tramo de valor, por
mercado, sólo patas «sólidas» (justa ≥ 60 %), las dos mitades del periodo y
bootstrap por día. Después, combinadas de 2-4 patas de valor.
"""
from __future__ import annotations

import io
import json
import os
import sys
from itertools import combinations

import numpy as np
import pandas as pd

import motor_mercado as mm

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3331)


def fotos_novibet():
    if os.path.exists('_v333_fotos_novibet.pkl'):
        return pd.read_pickle('_v333_fotos_novibet.pkl')
    import _v332_novibet_real as nr
    ult = nr.fotos()
    pd.to_pickle(ult, '_v333_fotos_novibet.pkl')
    return ult


def patas(ult) -> pd.DataFrame:
    res = pd.concat([pd.read_csv('resultados_flashscore_reciente.csv.gz'),
                     pd.read_csv('resultados_flashscore.csv.gz')]).drop_duplicates('match_id')
    res = res.set_index('match_id')
    T = mm.tabla()
    filas = []
    for eid, u in ult.items():
        if eid not in res.index:
            continue
        nv = u['nv']
        h = nv.get('HOME_DRAW_AWAY') or {}
        p3 = mm.sin_margen(h.get('home'), h.get('draw'), h.get('away'))
        if not p3:
            continue
        ou = {float(l['linea']): l for l in ((nv.get('OVER_UNDER') or {}).get('lineas') or [])
              if l.get('linea') is not None}
        po = None
        if 2.5 in ou:
            q = mm.sin_margen(ou[2.5].get('over'), ou[2.5].get('under'))
            po = q[0] if q else None
        i = mm.lote([p3[0]], [p3[2]], [po if po is not None else np.nan])[0]
        lh, la = T['lh'][i], T['la'][i]
        P = {k: T['P'][k][i] for k in T['P']}
        r = res.loc[eid]
        gh, ga = int(r.gh), int(r.ga)
        tot = gh + ga
        base = {'fecha': pd.to_datetime(u['ini'], unit='s').normalize(), 'eid': eid,
                'partido': '%s vs %s' % (u['home'], u['away']), 'liga': u['liga'],
                'con_ou': po is not None, 'lh': lh, 'la': la}

        def add(mer, ap, cuota, justa, ganancia):
            try:
                c = float(cuota)
            except Exception:
                return
            if c > 1.01 and np.isfinite(justa):
                filas.append(dict(base, mercado=mer, apuesta=ap, cuota=c, justa=float(justa),
                                  dev=ganancia(c)))
        for L, l in ou.items():
            if L == 2.5:
                continue
            for k, nom, gana in (('over', 'Más de %s' % L, tot > L), ('under', 'Menos de %s' % L, tot < L)):
                if 'Más de %s' % L in P or nom in P:
                    pj = P.get(nom)
                    if pj is None:
                        continue
                    push = (tot == L)
                    add('Goles', nom, l.get(k), pj,
                        lambda c, g=gana, pu=push: c if g else (1.0 if pu else 0.0))
        bt = nv.get('BOTH_TEAMS_TO_SCORE') or {}
        both = gh > 0 and ga > 0
        add('Ambos marcan', 'Ambos marcan sí', bt.get('yes'), P['Ambos marcan sí'],
            lambda c: c if both else 0.0)
        add('Ambos marcan', 'Ambos marcan no', bt.get('no'), P['Ambos marcan no'],
            lambda c: 0.0 if both else c)
        dc = nv.get('DOUBLE_CHANCE') or {}
        for k, nom, g in (('homeOrDraw', 'Local o empate', gh >= ga),
                          ('awayOrDraw', 'Visita o empate', ga >= gh),
                          ('noDraw', 'Local o visita', gh != ga)):
            add('Doble oportunidad', nom, dc.get(k), P[nom], lambda c, g=g: c if g else 0.0)
        for l in ((nv.get('ASIAN_HANDICAP') or {}).get('lineas') or []):
            L = l.get('linea')
            ch, ca = l.get('home'), l.get('away')
            if L is None or not ch or not ca:
                continue
            L = float(L)
            evh, eva = mm.handicap_ev(lh, la, L, float(ch), float(ca))
            cuarto = abs((L * 4) % 2 - 1) < 1e-9
            partes = [L - 0.25, L + 0.25] if cuarto else [L]

            def dev_h(c, s=1):
                v = 0.0
                for Lp in partes:
                    d = s * (gh - ga) + (Lp if s == 1 else -Lp)
                    v += (c if d > 0 else (1.0 if d == 0 else 0.0)) / len(partes)
                return v
            # «justa» de un hándicap = la cuota que daría valor 0; se guarda
            # el valor esperado directamente vía justa = (ev+1)/cuota
            add('Hándicap', 'Local %+.2f' % L, ch, (evh + 1) / float(ch), lambda c: dev_h(c, 1))
            add('Hándicap', 'Visita %+.2f' % (-L), ca, (eva + 1) / float(ca), lambda c: dev_h(c, -1))
    x = pd.DataFrame(filas)
    x['valor'] = x.justa * x.cuota
    x['verde'] = (x.dev > 1).astype(int)
    return x


def rinde(s):
    return 100 * (s.dev.mean() - 1) if len(s) else np.nan


def boot(s, n=3000):
    g = s.groupby('fecha').dev.agg(['sum', 'size']).values
    b = []
    for _ in range(n):
        q = g[rng.integers(0, len(g), len(g))].sum(axis=0)
        b.append(q[0] / q[1] - 1)
    return 100 * np.percentile(b, 5), 100 * np.mean(b)


def combinadas(e, k, maxc=300):
    from math import comb
    A = []
    for f, g in e.groupby('fecha'):
        if len(g) < k:
            continue
        c, v = g.cuota.values, g.dev.values / g.cuota.values   # v = fracción cobrada
        idx = (np.array(list(combinations(range(len(g)), k))) if comb(len(g), k) <= maxc
               else np.array([rng.choice(len(g), k, replace=False) for _ in range(maxc)]))
        pago = np.prod(c[idx] * v[idx], axis=1)
        A.append((len(idx), pago.sum(), (pago > 1).sum()))
    if len(A) < 5:
        return None
    A = np.array(A, float)
    b = []
    for _ in range(2000):
        q = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        b.append(q[1] / q[0] - 1)
    return {'dias': len(A), 'n': int(A[:, 0].sum()), 'acierto': A[:, 2].sum() / A[:, 0].sum(),
            'rinde': A[:, 1].sum() / A[:, 0].sum() - 1, 'p5': float(np.percentile(b, 5))}


def main():
    x = patas(fotos_novibet())
    mitad = x.fecha.sort_values().iloc[len(x) // 2]
    print('Novibet: %d partidos · %d patas secundarias · %s a %s (mitad %s)'
          % (x.eid.nunique(), len(x), x.fecha.min().date(), x.fecha.max().date(), mitad.date()))
    out = {}
    print('\n1. RENDIMIENTO POR VALOR (justa del motor × cuota de Novibet)')
    print('   valor        n      acierto  justa   rinde   1.ª mitad  2.ª mitad')
    for lo, hi in ((0, .90), (.90, .95), (.95, 1.0), (1.0, 1.03), (1.03, 1.06), (1.06, 1.10), (1.10, 9)):
        s = x[(x.valor >= lo) & (x.valor < hi)]
        if len(s) < 30:
            continue
        a, b = s[s.fecha < mitad], s[s.fecha >= mitad]
        print('   %.2f-%.2f  %6d   %5.1f %%  %5.1f %%  %+6.1f %%   %+6.1f %%   %+6.1f %%'
              % (lo, hi, len(s), 100 * s.verde.mean(), 100 * s.justa.mean(), rinde(s),
                 rinde(a), rinde(b)))
        out['valor %.2f-%.2f' % (lo, hi)] = [len(s), s.verde.mean(), rinde(s), rinde(a), rinde(b)]
    print('\n2. LAS DE VALOR (≥ 1,03) POR MERCADO Y SÓLO LAS SÓLIDAS (justa ≥ 60 %)')
    v = x[x.valor >= 1.03]
    for mer, s in v.groupby('mercado'):
        p5, med = boot(s) if s.fecha.nunique() >= 5 else (np.nan, np.nan)
        print('   %-18s n %5d · acierto %5.1f %% · rinde %+6.1f %% (p5 %+.1f)'
              % (mer, len(s), 100 * s.verde.mean(), rinde(s), p5))
    sol = v[v.justa >= 0.60]
    p5, med = boot(sol)
    a, b = sol[sol.fecha < mitad], sol[sol.fecha >= mitad]
    print('   SÓLIDAS ≥ 60 %%     n %5d · acierto %5.1f %% · rinde %+6.1f %% (p5 %+.1f) · mitades %+.1f / %+.1f'
          % (len(sol), 100 * sol.verde.mean(), rinde(sol), p5, rinde(a), rinde(b)))
    out['solidas'] = [len(sol), sol.verde.mean(), rinde(sol), p5, rinde(a), rinde(b)]
    for umbral in (1.02, 1.05, 1.08):
        s = x[(x.valor >= umbral) & (x.justa >= 0.60)]
        p5, _ = boot(s)
        print('   sólidas con valor ≥ %.2f: n %5d · acierto %5.1f %% · rinde %+6.1f %% (p5 %+.1f)'
              % (umbral, len(s), 100 * s.verde.mean(), rinde(s), p5))
        out['solidas_%.2f' % umbral] = [len(s), s.verde.mean(), rinde(s), p5]
    print('\n3. COMBINADAS de patas sólidas de valor (una por partido, la de más valor)')
    e = sol.sort_values('valor', ascending=False).drop_duplicates('eid')
    out['comb'] = {}
    for k in (2, 3, 4):
        r = combinadas(e, k)
        if r:
            print('   %d patas: %5d combinadas en %2d días · acierto %5.1f %% · rinde %+6.1f %% (p5 %+.1f)'
                  % (k, r['n'], r['dias'], 100 * r['acierto'], 100 * r['rinde'], 100 * r['p5']))
            out['comb'][k] = r
    x.to_pickle('_v333_novibet_interno.pkl')
    json.dump(out, open('_v333_novibet_interno.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
