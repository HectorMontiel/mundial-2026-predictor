#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test de la app (v35): recorre las competiciones nuevas y las
existentes con AppTest y comprueba que ninguna lanza excepción."""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from streamlit.testing.v1 import AppTest

VISTAS = ['🌍 Partidos Internacionales', '💎 Apuestas del Día', '🎾 Tenis (ATP/WTA)',
          '🇪🇺 Europa League', '🇪🇺 Conference League', '🇺🇸 MLS', '🇹🇷 Süper Lig', '🇩🇰 Superliga',
          '🇲🇽 Liga MX', '🇪🇸 LaLiga', '🇪🇺 Champions League']

fallos = []
for vista in VISTAS:
    at = AppTest.from_file('dashboard_ui.py', default_timeout=180).run()
    try:
        at.selectbox(key='competencia').select(vista).run()
    except Exception as e:
        fallos.append(f'{vista}: selección falló {type(e).__name__}: {e}')
        continue
    if at.exception:
        fallos.append(f'{vista}: {at.exception[0].message}')
        print(f'FALLO {vista}: {at.exception[0].message}')
    else:
        print(f'OK   {vista}')
print('\nTODO OK' if not fallos else f'\n{len(fallos)} FALLOS')
sys.exit(1 if fallos else 0)
