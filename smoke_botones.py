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
    '⚾ MLB (béisbol)': ['Proponer parlays', 'Enviar estos parlays'],
    '🇲🇽 Liga MX': ['Proponer parlays', 'Enviar estos parlays', 'Traer cuotas reales ahora'],
    # v67: el tenis ya tiene combinadas y envío a Telegram, así que sus botones
    # entran al smoke igual que los del resto de deportes.
    '🎾 Tenis (ATP/WTA)': ['Proponer parlays', 'Enviar estos parlays'],
    # v89: «Generar combinadas» dejó de ser botón — las combinadas del día se
    # calculan solas (el usuario pidió cero pasos manuales). La vista se sigue
    # cargando entera en el smoke, que es lo que detecta los crashes.
    '💎 Apuestas del Día': [],
    '🌍 Partidos Internacionales': ['Proponer parlays'],
    # v97 — las dos competiciones nuevas. La de KBO tiene motor propio (vista
    # aparte, como la de MLB) y la Leagues Cup es una liga de fútbol más, pero
    # con un histórico construido a mano (MLS + Liga MX + ESPN): si ese armado
    # se rompe, es aquí donde tiene que verse y no en producción.
    '⚾ KBO (béisbol coreano)': [],
    '🏆 Leagues Cup': ['Proponer parlays'],
}

def botones(at):
    """
    v106 — TODOS los botones, incluidos los que viven en pestañas y
    desplegables.

    `at.button` sólo devuelve los del nivel superior. Medido: la vista de MLB
    daba **0 botones** aunque tiene el de «Proponer parlays» dentro de su
    primera pestaña — o sea que el smoke llevaba versiones dando por buenos
    unos botones que jamás pulsaba, y decía «no encontrado (¿condicional?)»
    como si fuera normal.

    Importa justo por lo que este fichero existe: el UnboundLocalError de la
    v58.1 llegó a producción porque el fallo vivía dentro de un
    `if st.button(...)` que nadie ejecutaba. Un botón escondido en una pestaña
    tiene exactamente el mismo problema.
    """
    fuera, vistos = [], set()

    def _recoger(nodo):
        try:
            for b in nodo.button:
                if id(b) not in vistos:
                    vistos.add(id(b))
                    fuera.append(b)
        except Exception:
            pass
        for atributo in ('tabs', 'expander'):
            try:
                for hijo in getattr(nodo, atributo):
                    _recoger(hijo)
            except Exception:
                pass

    _recoger(at)
    return fuera


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
    todos = botones(at)
    print(f'OK   {vista} [carga] · {len(todos)} botones '
          f'({len(list(at.button))} en el nivel superior)')
    # v106 — se añade UN botón de refresco por vista, no todos.
    #
    # Los «Actualizar» de los paneles de EV+ vacían la caché y relanzan el
    # barrido entero del deporte, así que pulsar los tres de una vista
    # multiplica por tres el coste del smoke (medido: pasa de minutos a más de
    # veinte). Con uno se cubre el camino que de verdad se rompe —el
    # `.clear()` de una función cacheada definida DESPUÉS del botón, que es un
    # NameError— sin volver el smoke inservible.
    _refrescos = [b.label for b in todos
                  if 'actualizar' in (b.label or '').lower()]
    textos = list(textos) + _refrescos[:1]
    for texto in textos:
        objetivo = [b for b in todos if texto.lower() in (b.label or '').lower()]
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
