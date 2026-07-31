#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Arregla el prior de ELO el caso que reportó el usuario?

Dos comprobaciones:

  1. El partido concreto: Puebla vs Chivas en Liga MX. Con el ELO 1349 vs 1597
     y todo lo demás en contra de Puebla, la ficha daba Puebla favorito al 54 %.

  2. La propiedad general: la dependencia parcial respecto al ELO, repetida
     sobre las ligas que salían PLANAS o INVERTIDAS. Si el encogimiento sirve,
     esas curvas deben pasar a subir.
"""
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

DELTAS = np.array([-300.0, -200.0, -100.0, 0.0, 100.0, 200.0, 300.0])

# las peores de _v86_dependencia_elo.json
PLANAS = ['sco_championship', 'argentina', 'jpn_j1', 'ita_serie_b',
          'ger_bundesliga2', 'suecia', 'finlandia', 'ligue_1',
          'sco_premiership', 'polonia', 'eng_national', 'premier', 'mls',
          'irlanda', 'rumania', 'serie_a', 'liga_mx']


def caso_puebla():
    import league_engine as le
    print('=' * 80)
    print('1) EL PARTIDO QUE REPORTÓ EL USUARIO')
    print('=' * 80)
    e = le.ClubEngine('liga_mx')
    if not e.listo:
        print('  motor no listo')
        return

    cand_p = [t for t in e.stats if 'puebla' in t.lower()]
    cand_c = [t for t in e.stats if 'chiva' in t.lower() or
              'guadalajara' in t.lower()]
    if not cand_p or not cand_c:
        print(f'  no se encuentran los equipos '
              f'(puebla={cand_p}, chivas={cand_c})')
        return
    p, c = cand_p[0], cand_c[0]
    print(f'  {p} (ELO {e.stats[p]["ELO"]:.0f}) vs '
          f'{c} (ELO {e.stats[c]["ELO"]:.0f})')
    print(f'  forma MA5: {e.stats[p].get("FORMA_MA5", 0):.2f} vs '
          f'{e.stats[c].get("FORMA_MA5", 0):.2f}')

    antes = e.predecir(p, c, prior_elo=False)
    despues = e.predecir(p, c, prior_elo=True)
    for nombre, r in (('SIN prior de ELO (como estaba)', antes),
                      ('CON prior de ELO (v86)', despues)):
        pr = r['prediction']['probabilities']
        print(f'\n  {nombre}:')
        print(f'    {p}: {pr["home"]:.1%} · Empate: {pr["draw"]:.1%} · '
              f'{c}: {pr["away"]:.1%}')
        print(f'    ganador mostrado: {r["prediction"]["winner"]} '
              f'({r["prediction"]["confidence"]:.1%})')

    a, d = antes['prediction'], despues['prediction']
    print(f'\n  ¿cambia el favorito mostrado? '
          f'{a["winner"]} -> {d["winner"]} '
          f'{"SÍ" if a["winner"] != d["winner"] else "no"}')

    # y el espejo: Chivas en su casa
    print('\n  espejo (el fuerte en SU campo):')
    for nombre, kw in (('sin prior', {'prior_elo': False}),
                       ('con prior', {'prior_elo': True})):
        r1 = e.predecir(p, c, **kw)['prediction']['probabilities']['home']
        r2 = e.predecir(c, p, **kw)['prediction']['probabilities']['home']
        coherente = r2 > r1
        print(f'    {nombre}: {p} en casa {r1:.1%} · {c} en casa {r2:.1%} '
              f'-> {"COHERENTE" if coherente else "INCOHERENTE"}')


def monotonia():
    import league_engine as le
    print('\n' + '=' * 80)
    print('2) DEPENDENCIA PARCIAL EN LAS LIGAS QUE SALÍAN PLANAS')
    print('=' * 80)
    print(f'{"liga":22s} {"salto ANTES":>12} {"salto DESPUÉS":>14} {"cambio":>9}')
    print('-' * 80)

    antes_l, despues_l = [], []
    for clave in PLANAS:
        try:
            e = le.ClubEngine(clave)
            if not e.listo:
                continue
            equipos = [t for t in e.stats
                       if isinstance(e.stats[t], dict) and e.stats[t].get('ELO')]
            if len(equipos) < 6:
                continue
            rng = np.random.default_rng(86)
            pares = [(a, b) for a in equipos for b in equipos if a != b]
            if len(pares) > 15:
                pares = [pares[i] for i in
                         rng.choice(len(pares), 15, replace=False)]

            saltos = {}
            for usar in (False, True):
                curvas = []
                for home, away in pares:
                    orig = e.stats[home]['ELO']
                    fila = []
                    try:
                        for dd in DELTAS:
                            e.stats[home] = dict(e.stats[home], ELO=orig + dd)
                            r = e.predecir(home, away, prior_elo=usar)
                            if 'error' in r:
                                fila = None
                                break
                            fila.append(
                                float(r['prediction']['probabilities']['home']))
                    finally:
                        e.stats[home] = dict(e.stats[home], ELO=orig)
                    if fila:
                        curvas.append(fila)
                if curvas:
                    C = np.array(curvas)
                    saltos[usar] = float(C.mean(axis=0)[-1] - C.mean(axis=0)[0])
            if False in saltos and True in saltos:
                a, d = saltos[False], saltos[True]
                antes_l.append(a)
                despues_l.append(d)
                print(f'{clave:22s} {a:+12.4f} {d:+14.4f} {d - a:+9.4f}')
        except Exception as ex:
            print(f'{clave:22s} ERROR {type(ex).__name__}: {str(ex)[:40]}')

    if antes_l:
        print('-' * 80)
        print(f'{"MEDIANA":22s} {np.median(antes_l):+12.4f} '
              f'{np.median(despues_l):+14.4f} '
              f'{np.median(despues_l) - np.median(antes_l):+9.4f}')
        peor_a = sum(1 for x in antes_l if x <= 0.02)
        peor_d = sum(1 for x in despues_l if x <= 0.02)
        print(f'\nligas todavía planas (salto <= 0,02): '
              f'{peor_a} antes -> {peor_d} después (de {len(antes_l)})')
        neg_a = sum(1 for x in antes_l if x < 0)
        neg_d = sum(1 for x in despues_l if x < 0)
        print(f'ligas con salto NEGATIVO: {neg_a} antes -> {neg_d} después')


if __name__ == '__main__':
    caso_puebla()
    monotonia()
