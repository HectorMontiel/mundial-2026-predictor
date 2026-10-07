# -*- coding: utf-8 -*-
"""
v332 — EL HISTÓRICO DEL MODELO CON EL MARCADOR AL DESCANSO DE FLASHSCORE.

Para medir el «pago anticipado por 2 goles» (Novibet paga «Gana X» si X se
pone dos goles arriba en cualquier momento) hace falta saber cómo iba el
partido, no sólo cómo acabó. `pick_ledger*.csv` trae la λ del modelo, sus
probabilidades fuera de muestra y las cuotas, pero no el descanso;
`resultados_flashscore.csv.gz` (226 mil partidos) trae el descanso pero no
el modelo. Se cruzan por fecha (±1 día, por los husos) y por el parecido de
los dos nombres, exigiendo que el marcador final coincida — así un cruce
equivocado no puede colarse.

Salida: _v332_ledger_descanso.pkl (no se sube; se rehace en segundos)
"""
from __future__ import annotations

import io
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

RUIDO = {'fc', 'cf', 'sc', 'ac', 'cd', 'club', 'de', 'the', 'afc', 'cfc', 'fk',
         'sk', 'if', 'bk', 'ud', 'sd', 'ca', 'rc', 'ss', 'as', 'us', 'cs', 'sv',
         'vfb', 'vfl', 'tsg', 'sport', 'clube', 'deportivo', 'atletico'}


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-z0-9 ]', ' ', s.lower().replace('-', ' '))
    t = [w for w in s.split() if w not in RUIDO and len(w) > 1]
    return ' '.join(t) or s.strip()


def parecido(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    return max(jac, SequenceMatcher(None, a, b).ratio())


def main():
    t = pd.read_csv('pick_ledger_totales.csv')
    r = pd.read_csv('pick_ledger.csv').drop(columns=['goles_local', 'goles_visit',
                                                      'fecha', 'pliegue'])
    d = t.merge(r, on=['liga', 'match_id'], how='inner')
    for k in ('cuota_over25', 'cuota_under25'):
        d[k] = d[k + '_y'].fillna(d[k + '_x'])
    p = d.match_id.str.split('_', n=2, expand=True)
    d['h_n'], d['a_n'] = p[1].map(norm), p[2].map(norm)
    d['fecha'] = pd.to_datetime(d.fecha)
    f = pd.read_csv('resultados_flashscore.csv.gz')
    f = f[f.hh.notna()].copy()
    f['fecha'] = pd.to_datetime(f.ini).dt.normalize()
    f['h_n'], f['a_n'] = f.home.map(norm), f.away.map(norm)
    idx = defaultdict(list)
    for i, (fe, gh, ga) in enumerate(zip(f.fecha, f.gh, f.ga)):
        idx[(fe, int(gh), int(ga))].append(i)
    F = f.reset_index(drop=True)
    hh, ha, ok = [], [], []
    for fe, gh, ga, hn, an in zip(d.fecha, d.goles_local, d.goles_visit,
                                  d.h_n, d.a_n):
        mejor, s_mejor = None, 0.0
        if pd.notna(gh):
            for dd in (0, -1, 1):
                for i in idx.get((fe + pd.Timedelta(days=dd), int(gh), int(ga)), []):
                    s = min(parecido(hn, F.h_n[i]), parecido(an, F.a_n[i]))
                    if s > s_mejor:
                        mejor, s_mejor = i, s
        if mejor is not None and s_mejor >= 0.5:
            hh.append(F.hh[mejor]); ha.append(F.ha[mejor]); ok.append(s_mejor)
        else:
            hh.append(None); ha.append(None); ok.append(None)
    d['hh'], d['ha'], d['cruce'] = hh, ha, ok
    n = d.hh.notna().sum()
    print('partidos del histórico: %d · con descanso: %d (%.0f %%)'
          % (len(d), n, 100 * n / len(d)))
    print(d[d.hh.notna()].groupby('liga').size().sort_values().tail(8).to_string())
    d.drop(columns=['h_n', 'a_n']).to_pickle('_v332_ledger_descanso.pkl')


if __name__ == '__main__':
    main()
