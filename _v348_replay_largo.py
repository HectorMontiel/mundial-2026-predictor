# -*- coding: utf-8 -*-
"""v348 — la réplica de la tarjeta (`_v324_nada.py`) desde el 24-ago, cuando
empiezan las fotos del tablero con precios, para medir las «también se meten»
con más historia. Escribe `_v348_candidatas.csv.gz`."""
import os
import sys
os.environ['V324_CACHE'] = '_v348_candidatas.csv.gz'
import _v310_replay_semana as rp
rp.DESDE = '2026-08-24'
import _v324_nada as N
N.CACHE = '_v348_candidatas.csv.gz'
d = N.construir()
print('filas', len(d), 'partidos', d.partido.nunique(), d.dia.min(), d.dia.max())
