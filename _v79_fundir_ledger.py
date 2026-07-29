#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Recompone `pick_ledger_deportes.csv` (tenis + MLB).

Al reconstruir SOLO el ledger de MLB con el modelo nuevo, el fichero se
sobrescribió entero y las 64.587 filas de tenis se perdieron. El modelo de
tenis no ha cambiado en esta versión, así que su ledger sigue siendo válido y
no hace falta recalcular 5 pliegues sobre 46.000 partidos: basta con recuperar
esas filas de la copia y fundirlas con las de MLB recién construidas.
"""
import os
import sys

import pandas as pd

BACKUP = (r'C:\Users\HMREY\AppData\Local\Temp\claude\C--Users-HMREY'
          r'\5e74aae6-9f0c-4be2-88cc-b813755c754b\scratchpad'
          r'\pick_ledger_deportes.csv')
ACTUAL = 'pick_ledger_deportes.csv'


def main():
    if not os.path.exists(BACKUP):
        sys.exit(f'no existe la copia: {BACKUP}')
    b = pd.read_csv(BACKUP, low_memory=False)
    n = pd.read_csv(ACTUAL, low_memory=False)
    print(f'copia : {len(b)} {b.deporte.value_counts().to_dict()}')
    print(f'actual: {len(n)} {n.deporte.value_counts().to_dict()}')

    tenis = b[b.deporte == 'Tenis']
    mlb = n[n.deporte == 'MLB']
    if tenis.empty or mlb.empty:
        sys.exit('falta alguno de los dos deportes; no se funde')

    out = pd.concat([tenis, mlb], ignore_index=True)
    out = out.drop_duplicates(subset=['deporte', 'match_id'], keep='last')
    out.to_csv(ACTUAL, index=False)
    print(f'fundido: {len(out)} {out.deporte.value_counts().to_dict()}')


if __name__ == '__main__':
    main()
