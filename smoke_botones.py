#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test de BOTONES (v58.1).

Lección de producción: el UnboundLocalError de «Proponer parlays con cuotas»
llegó al usuario porque los smoke tests solo CARGABAN la página; el fallo vivía
dentro del bloque `if st.button(...)`, que nunca se ejecutaba. Este test pulsa
los botones de cada vista y verifica que ninguno lanza excepción.

CUÁNDO SE USA ESTE, Y CUÁNDO NO (v152)
--------------------------------------
Dejó de ser la puerta de cada push, por decisión de HMREY y con un motivo
medido: el 2026-08-22 no terminó en 55 minutos en dos intentos seguidos (EXIT
124 las dos veces), y sólo la vista de «Apuestas del Día» tarda 254 s. La cifra
real está en horas, no en los 110 minutos que decía la documentación. Una puerta
que cuesta media jornada deja de usarse, y una puerta que no se usa no protege
nada.

    cualquier cambio ...........  test_catalogo_y_cuotas.py, siempre
    cambio de INTERFAZ .........  valida_render.py <vistas tocadas>  (minutos)
    cambio de MOTOR ............  ESTE, completo
    una vez por semana .........  ESTE, completo

Lo que NO se relaja es que el render se valide: `py_compile` y el AST no ven un
`UnboundLocalError`, y ésa es la lección que hizo nacer este fichero.
`valida_render.py` usa el mismo AppTest sobre las vistas que el cambio toca.

Uso:  python smoke_botones.py
      python smoke_botones.py --rapido
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
    # v131 — la NFL. Entra en el smoke desde el primer día y no «cuando se
    # estabilice»: su vista pulsa «Cargar» (que reescribe `session_state` y
    # hace `st.rerun()`) y su pestaña de EV+ lanza el barrido del deporte.
    # Los dos son exactamente el tipo de camino que sólo se recorre pulsando,
    # que es la razón por la que este fichero existe.
    '🏈 NFL (fútbol americano)': ['Cargar'],
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


# ---------------------------------------------------------------------------
# v138 — MODO RÁPIDO, PORQUE 110 MINUTOS POR CADA REENTRENAMIENTO NO SALEN.
#
# Medido el 2026-08-14 sobre esta misma máquina:
#
#     barrido del día en frío ........   2,6 min
#     cargar una vista con AppTest ...   1,2 min
#     estimación de 8 vistas .........  11,3 min
#     SMOKE COMPLETO REAL ............ 110    min
#
# Los 100 minutos de diferencia NO están en cargar pantallas: están en pulsar
# tres botones que cargan motores de liga y corren Monte Carlo. Son justo los
# que hay que pulsar cuando cambia el código —el fallo que dio origen a este
# fichero vivía dentro de un `if st.button(...)`— pero no aportan nada cuando
# lo único que ha cambiado son los JSON de estadísticas que sube el bot diario.
#
# `--rapido` carga LAS 8 VISTAS igual (que es donde se detecta un dato que
# rompe el arranque) y pulsa todo MENOS esos tres. Baja a ~15 min.
#
# CUÁNDO SE USA CADA UNO, y esto no es opinable:
#   · --rapido  -> cambió el DATO y no el código (rebase del bot, iteración).
#   · completo  -> cambió el CÓDIGO. Obligatorio antes de cualquier push.
# ---------------------------------------------------------------------------
RAPIDO = '--rapido' in sys.argv

# Los que cargan motores y corren Monte Carlo. Se comparan en minúsculas
# contra la etiqueta del botón, igual que el resto del fichero.
BOTONES_CAROS = ('proponer parlays', 'enviar estos parlays',
                 'traer cuotas reales ahora')

if RAPIDO:
    print('MODO RÁPIDO: se cargan las 8 vistas y se pulsa todo menos los '
          'botones que cargan motores.')
    print('             NO sustituye al completo antes de un push.\n')

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
    if RAPIDO:
        _fuera = [t for t in textos
                  if any(c in t.lower() for c in BOTONES_CAROS)]
        textos = [t for t in textos if t not in _fuera]
        # Se dice EN VOZ ALTA lo que no se ha probado. Un smoke que calla lo
        # que se salta es el que hace creer que algo está validado cuando no
        # lo está — que es el fallo del que nació este fichero.
        for t in _fuera:
            print(f'  ⏭️  botón «{t}» OMITIDO por --rapido (no validado)')
    # v147 — recorrer las secciones de la ficha, si la vista las tiene.
    #
    # `partido_ui` ejecuta SÓLO la sección abierta, así que cargar la vista
    # valida una de cinco. Aquí se pulsan todas: es barato (ninguna vuelve a
    # tocar la red, medido) y es la única forma de que un fallo dentro de
    # «Mercados» o «Combinadas» salga aquí y no en la pantalla del usuario.
    _secs = [r for r in at.radio if r.key and r.key.startswith('_sec_')]
    if _secs:
        _opts = list(_secs[0].options)
        print(f'  ·  ficha con {len(_opts)} secciones: se recorren todas')
        for _o in _opts:
            _r = [x for x in at.radio if x.key and x.key.startswith('_sec_')]
            if not _r:
                break
            try:
                _r[0].set_value(_o).run()
            except Exception as e:
                fallos.append(f'{vista} [sección {_o}]: {type(e).__name__}: {e}')
                print(f'  FALLO sección «{_o}»: {type(e).__name__}: {e}')
                continue
            if at.exception:
                fallos.append(f'{vista} [sección {_o}]: {at.exception[0].message}')
                print(f'  FALLO sección «{_o}»: {at.exception[0].message}')
                continue
            print(f'  OK   sección «{_o}»')
            # v147 — Y SE PULSAN LOS BOTONES QUE VIVEN DENTRO DE LA SECCIÓN.
            #
            # Al partir la ficha en secciones, «Proponer parlays» dejó de estar
            # en el nivel superior: ahora vive dentro de «Combinadas», que no se
            # renderiza hasta que se abre. El smoke lo daba por «no encontrado
            # (¿condicional?)» y seguía en verde — o sea que había dejado de
            # probar EL BOTÓN QUE ORIGINÓ ESTE FICHERO, sin decirlo.
            #
            # Aquí se recogen los botones de la sección abierta y se pulsan los
            # que la vista pidiera. Es la misma cobertura de antes, buscada
            # donde ahora están.
            _en_sec = botones(at)
            for _t in list(textos):
                if RAPIDO and any(c in _t.lower() for c in BOTONES_CAROS):
                    continue
                _obj = [b for b in _en_sec
                        if _t.lower() in (b.label or '').lower()]
                if not _obj:
                    continue
                try:
                    _obj[0].click().run()
                except Exception as e:
                    fallos.append(f'{vista} [{_o}/{_t}]: {type(e).__name__}: {e}')
                    print(f'  FALLO botón «{_t}» en «{_o}»: {type(e).__name__}: {e}')
                    continue
                if at.exception:
                    fallos.append(f'{vista} [{_o}/{_t}]: {at.exception[0].message}')
                    print(f'  FALLO botón «{_t}» en «{_o}»: {at.exception[0].message}')
                else:
                    print(f'  OK   botón «{_t}» dentro de «{_o}»')
                    textos = [x for x in textos if x != _t]

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
if RAPIDO:
    # El veredicto tiene que decir de qué está hablando. «TODO OK» a secas,
    # saliendo del modo rápido, se leería como una validación completa.
    print('\n⚠️  MODO RÁPIDO: no se han pulsado los botones que cargan '
          'motores.')
    print('    Antes de subir código, ejecuta `python smoke_botones.py` sin '
          'el flag.')
sys.exit(1 if fallos else 0)
