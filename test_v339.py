#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v339.

El usuario: «auditoría completa del diseño… más intuitiva, más fácil de leer,
más visual, menos texto, más moderna, más Liquid Glass… fácil entender qué
meter y qué no».

Lo que se vigila:

  1. LA CAPA DE CRISTAL: existe, se aplica DESPUÉS de la hoja de la v122 y
     apunta a las tarjetas reales de esta versión de Streamlit (no al
     contenedor que ya no existe).
  2. LA PANTALLA PRINCIPAL: la marca en una línea; nada técnico a la vista
     (Ollama, ODDS_API_KEY); los envíos a Telegram, plegados y con sus claves
     de siempre; descargar y copiar, plegados.
  3. LA TARJETA: cabecera con el partido entero; estado como insignia; el
     contexto DESPUÉS de la apuesta y plegado; la lista «se mete» envuelta
     para no repetirse junto al bloque grande.

Ejecutar:  python test_v339.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_la_capa():
    import estilo_ui as eu
    check(hasattr(eu, 'CSS_VIDRIO') and 'backdrop-filter' in eu.CSS_VIDRIO,
          'existe la capa de cristal (con desenfoque)')
    src = open('estilo_ui.py', encoding='utf-8').read()
    check('st.markdown(CSS + CSS_VIDRIO' in src, 'y se aplica DESPUÉS de la de la v122')
    check('stVerticalBlockBorderWrapper' not in eu.CSS_VIDRIO,
          'no apunta al contenedor que esta versión de Streamlit ya no tiene')
    check(':has(> div[data-testid="stElementContainer"] :is(.mm-cab, .match))' in eu.CSS_VIDRIO,
          'las tarjetas se reconocen por su cabecera')
    check('.vp-lista' in eu.CSS_VIDRIO and ':has(.mm-rec-si)' in eu.CSS_VIDRIO,
          'la lista repetida se pliega cuando está el bloque grande')
    check("family=Inter" in eu.CSS_VIDRIO, 'la letra es Inter')
    m = eu.marca('Predictor deportivo', ('⚽', '🎾'))
    check('class="marca"' in m and 'Predictor deportivo' in m and '🎾' in m,
          'la marca en una línea')


def probar_la_pantalla():
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check("_estilo.marca(" in src, 'arriba va la marca, no la pancarta')
    i = src.find("Reescribir comentarios con SLM local")
    check(i > 0 and "os.environ.get('OLLAMA_MODEL')" in src[i - 400:i],
          'la casilla de Ollama sólo aparece con Ollama configurado')
    check("'6 casas · sin ODDS_API_KEY'" not in src,
          'el chip ya no enseña el nombre de una variable de entorno')
    j = src.find("st.expander('📤 Enviar a Telegram y exportar'")
    k = src.find("key='tg_send_top'")
    check(j > 0 and j < k < j + 2500, 'los envíos a Telegram, plegados')
    for clave in ('tg_send_top', 'tg_send_hoy', 'tg_send_manana', 'tg_send_pasado',
                  'tg_send_todo'):
        check("key='%s'" % clave in src, 'sigue viva la clave %s' % clave)
    check('📥 Descargar o copiar las apuestas' in src, 'descargar y copiar, plegados')


def probar_la_tarjeta():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('class="mm-cab"' in src and 'quote=False' in src,
          'la cabecera de la tarjeta lleva el partido entero')
    check('class="mm-estado vivo">⏱️ En juego' in src, 'el estado es una insignia')
    i, j = src.find('_ctx_html = _bloque_contexto(pick)'), src.find("st.expander('📊 Contexto del partido')")
    k = src.find("'🎯 Se mete')", i)
    check(0 < i < k < j, 'el contexto se pinta DESPUÉS de lo que se mete, plegado')
    vp = open('veredicto_pick.py', encoding='utf-8').read()
    check('<div class="vp-lista">' in vp, 'la lista «se mete» va envuelta')


if __name__ == '__main__':
    print('=== 1. la capa de cristal ===')
    probar_la_capa()
    print('\n=== 2. la pantalla principal ===')
    probar_la_pantalla()
    print('\n=== 3. la tarjeta ===')
    probar_la_tarjeta()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
