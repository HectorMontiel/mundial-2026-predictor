#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test de BOTONES (v58.1).

Lección de producción: el UnboundLocalError de «Proponer parlays con cuotas»
llegó al usuario porque los smoke tests solo CARGABAN la página; el fallo vivía
dentro del bloque `if st.button(...)`, que nunca se ejecutaba. Este test pulsa
los botones de cada vista y verifica que ninguno lanza excepción.

Uso:  python smoke_botones.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from streamlit.testing.v1 import AppTest

# vista -> subcadenas de los botones a pulsar (los costosos/críticos)
VISTAS = {
    '⚾ MLB (béisbol)': ['Proponer parlays'],
    '🇲🇽 Liga MX': ['Proponer parlays'],
    '🎾 Tenis (ATP/WTA)': [],
    '💎 Apuestas del Día': ['Generar combinadas'],
}

fallos = []
for vista, textos in VISTAS.items():
    at = AppTest.from_file('dashboard_ui.py', default_timeout=420).run()
    try:
        at.selectbox(key='competencia').select(vista).run()
    except Exception as e:
        fallos.append(f'{vista}: no se pudo seleccionar ({e})')
        continue
    if at.exception:
        fallos.append(f'{vista} [carga]: {at.exception[0].message}')
        print(f'FALLO {vista} [carga]: {at.exception[0].message}')
        continue
    print(f'OK   {vista} [carga]')
    for texto in textos:
        objetivo = [b for b in at.button if texto.lower() in (b.label or '').lower()]
        if not objetivo:
            print(f'  ·  botón «{texto}» no encontrado (¿condicional?)')
            continue
        try:
            objetivo[0].click().run()
        except Exception as e:
            fallos.append(f'{vista} [{texto}]: {type(e).__name__}: {e}')
            print(f'  FALLO botón «{texto}»: {type(e).__name__}: {e}')
            continue
        if at.exception:
            fallos.append(f'{vista} [{texto}]: {at.exception[0].message}')
            print(f'  FALLO botón «{texto}»: {at.exception[0].message}')
        else:
            print(f'  OK   botón «{texto}»')

print('\n' + '=' * 40)
print('TODO OK' if not fallos else f'{len(fallos)} FALLOS')
for f in fallos:
    print(' -', f)
sys.exit(1 if fallos else 0)
