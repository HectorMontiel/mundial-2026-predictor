#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Debe el encogimiento ser más fuerte donde el modelo ignora más el ELO?

Por qué
-------
Con w=0,90 global la monotonía queda arreglada (13 ligas planas -> 0, 6
negativas -> 0), pero el caso concreto del usuario NO: Puebla sigue saliendo
favorito sobre Chivas (50,0 % frente a 24,9 %) pese a 248 puntos de ELO en
contra, y el espejo sigue incoherente.

La idea es la misma que ya usa `calibracion_mercado`: el peso no tiene por qué
ser igual en todas las ligas. Donde el modelo SÍ responde al ELO no hace falta
corregir; donde lo ignora, hace falta más.

Clasificación INDEPENDIENTE de los datos de validación
-------------------------------------------------------
Las ligas se clasifican con la dependencia parcial (_v86_dependencia_elo.json),
que se calcula moviendo el ELO sobre el modelo — no mira ni un resultado real.
Luego se valida sobre el ledger. Así la etiqueta no puede estar contaminada por
lo que se usa para juzgarla.

Protocolo, igual que antes: elegir en los pliegues 1-2, validar en los 3-4,
adoptar sólo si la mejora persiste.
"""
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CORTE_RESPONDE = 0.05      # salto de P(local) por 600 pts de ELO
REJILLA_PLANAS = [0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]
REJILLA_RESPONDEN = [1.00, 0.95, 0.90, 0.85]


def ece(p, y, bins=10):
    conf, pred = p.max(axis=1), p.argmax(axis=1)
    ac = (pred == y).astype(float)
    b = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (conf > b[i]) & (conf <= b[i + 1])
        if m.sum():
            e += m.mean() * abs(ac[m].mean() - conf[m].mean())
    return float(e)


def met(p, y):
    p = np.clip(p, 1e-9, 1)
    p = p / p.sum(axis=1, keepdims=True)
    return {'ll': float(-np.log(p[np.arange(len(y)), y]).mean()),
            'ece': ece(p, y),
            'acc': float((p.argmax(axis=1) == y).mean())}


def main():
    from sklearn.linear_model import LogisticRegression

    dep = json.load(open('_v86_dependencia_elo.json', encoding='utf-8'))
    salto = {r['liga']: r['salto'] for r in dep if not r.get('error')}
    planas = {l for l, s in salto.items() if s <= CORTE_RESPONDE}
    print('=' * 78)
    print('v86 · ¿w POR LIGA SEGÚN LA RESPUESTA AL ELO?')
    print('=' * 78)
    print(f'  ligas medidas          : {len(salto)}')
    print(f'  PLANAS (salto <= {CORTE_RESPONDE}) : {len(planas)}')
    print(f'  responden              : {len(salto) - len(planas)}')

    led = pd.read_csv('pick_ledger_total.csv')
    elo = pd.read_csv('elo_por_partido.csv')
    d = (led[led['deporte'] == 'Fútbol']
         .merge(elo, on=['liga', 'match_id'], how='inner')
         .sort_values(['pliegue', 'fecha']).reset_index(drop=True))

    filas = []
    for k in sorted(d['pliegue'].unique())[1:]:
        tr, te = d[d['pliegue'] < k], d[d['pliegue'] == k]
        if len(tr) < 500 or len(te) < 100:
            continue
        m = LogisticRegression(max_iter=1000)
        m.fit(tr['diff_elo'].values.reshape(-1, 1),
              tr['resultado'].values.astype(int))
        p = m.predict_proba(te['diff_elo'].values.reshape(-1, 1))
        pe = np.zeros((len(te), 3))
        for i, c in enumerate(m.classes_):
            pe[:, int(c)] = p[:, i]
        t = te.copy()
        t[['pe_home', 'pe_draw', 'pe_away']] = pe
        filas.append(t)
    ev = pd.concat(filas, ignore_index=True)
    ev = ev[ev['cuota_home'].isna()].reset_index(drop=True)
    ev['plana'] = ev['liga'].isin(planas)

    print(f'\n  fichas sin mercado evaluables: {len(ev)}')
    print(f'    en ligas planas   : {int(ev["plana"].sum())}')
    print(f'    en ligas que responden: {int((~ev["plana"]).sum())}')

    elec = ev[ev['pliegue'].isin([1, 2])]
    vali = ev[ev['pliegue'].isin([3, 4])]

    def evalua(sub, w_plana, w_resp):
        pm = sub[['p_home', 'p_draw', 'p_away']].values.astype(float)
        pe = sub[['pe_home', 'pe_draw', 'pe_away']].values.astype(float)
        y = sub['resultado'].values.astype(int)
        w = np.where(sub['plana'].values, w_plana, w_resp).reshape(-1, 1)
        return met(w * pm + (1 - w) * pe, y)

    base_e = evalua(elec, 1.0, 1.0)
    base_v = evalua(vali, 1.0, 1.0)
    glob_e = evalua(elec, 0.90, 0.90)
    glob_v = evalua(vali, 0.90, 0.90)

    print(f'\n  referencia:')
    print(f'    sin encoger      elección ECE {base_e["ece"]:.4f} · '
          f'VALIDACIÓN ECE {base_v["ece"]:.4f} ll {base_v["ll"]:.5f}')
    print(f'    w=0,90 global    elección ECE {glob_e["ece"]:.4f} · '
          f'VALIDACIÓN ECE {glob_v["ece"]:.4f} ll {glob_v["ll"]:.5f}')

    print(f"\n  {'w planas':>9} {'w responden':>12} | "
          f"{'elección ECE':>13} {'ll':>10} | {'VALID ECE':>10} {'ll':>10}")
    print('  ' + '-' * 70)
    res = []
    for wp in REJILLA_PLANAS:
        for wr in REJILLA_RESPONDEN:
            a = evalua(elec, wp, wr)
            b = evalua(vali, wp, wr)
            res.append({'w_plana': wp, 'w_resp': wr, 'eleccion': a,
                        'validacion': b})
            print(f"  {wp:9.2f} {wr:12.2f} | {a['ece']:13.4f} {a['ll']:10.5f} "
                  f"| {b['ece']:10.4f} {b['ll']:10.5f}")

    # elección: mejor ECE en pliegues 1-2, exigiendo que el log-loss no empeore
    cands = [r for r in res if r['eleccion']['ll'] <= base_e['ll']]
    if not cands:
        print('\nVEREDICTO: ninguna combinación mejora. NO adoptar.')
        return
    eleg = min(cands, key=lambda r: r['eleccion']['ece'])
    wp, wr = eleg['w_plana'], eleg['w_resp']

    print('\n' + '-' * 78)
    print(f'elegido en pliegues 1-2: w_planas={wp:.2f} · w_responden={wr:.2f}')
    print(f'  VALIDACIÓN (pliegues 3-4):')
    print(f'    ECE      {eleg["validacion"]["ece"]:.4f}  '
          f'(sin encoger {base_v["ece"]:.4f} · global 0,90 {glob_v["ece"]:.4f})')
    print(f'    log-loss {eleg["validacion"]["ll"]:.5f}  '
          f'(sin encoger {base_v["ll"]:.5f} · global 0,90 {glob_v["ll"]:.5f})')
    print(f'    precisión {eleg["validacion"]["acc"]:.4f}  '
          f'(sin encoger {base_v["acc"]:.4f})')

    mejor_que_base = (eleg['validacion']['ece'] < base_v['ece']
                      and eleg['validacion']['ll'] < base_v['ll'])
    mejor_que_global = eleg['validacion']['ece'] < glob_v['ece']
    print(f'\n  ¿mejor que no encoger?     {"SÍ" if mejor_que_base else "NO"}')
    print(f'  ¿mejor que w=0,90 global?  {"SÍ" if mejor_que_global else "NO"}')
    veredicto = ('ADOPTAR w por liga' if (mejor_que_base and mejor_que_global)
                 else ('ADOPTAR w=0,90 global (el por-liga no aporta)'
                       if mejor_que_base else 'NO adoptar'))
    print(f'\nVEREDICTO: {veredicto}')

    json.dump({'corte_responde': CORTE_RESPONDE,
               'planas': sorted(planas),
               'w_plana': wp, 'w_resp': wr,
               'validacion': eleg['validacion'],
               'base': base_v, 'global090': glob_v,
               'mejor_que_base': bool(mejor_que_base),
               'mejor_que_global': bool(mejor_que_global)},
              open('_v86_w_por_liga.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
