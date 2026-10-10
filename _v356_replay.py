# -*- coding: utf-8 -*-
"""v356 — la réplica de la tarjeta (`_v324_nada.py`) del 24-ago hasta hoy,
para medir el «modelo de anticipación» de rojas. Escribe
`_v356_candidatas.csv.gz` (cada candidata de cada partido, su motivo, si se
metía y si acertó)."""
import os
os.environ['V324_CACHE'] = '_v356_candidatas.csv.gz'
import _v310_replay_semana as rp
rp.DESDE = '2026-08-24'
import _v324_nada as N
N.CACHE = '_v356_candidatas.csv.gz'
d = N.construir()
print('filas', len(d), 'partidos', d.partido.nunique(), d.dia.min(), d.dia.max())
