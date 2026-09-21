#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la forma reciente (v295).

Este módulo NO decide nada: sólo enseña un dato en pantalla. Por eso lo que
se vigila aquí es distinto de lo habitual:

  · QUE NO LANCE NUNCA, pase lo que pase, porque va dentro de un render.
  · QUE NO MIENTA: si de un equipo no hay bastantes partidos, devuelve cadena
    vacía. Un «ganó 1 de sus últimos 2» es peor que no decir nada.
  · QUE SEPA A QUÉ EQUIPO APUNTA EL PICK, que es de donde salen los errores
    tontos («Gana Nueva Chicago» -> Nueva Chicago, no «Gana Nueva Chicago»).
  · Y que NO se haya colado como filtro en la escalera: se midió y no
    sobrevive al tramo de juicio. Si algún día alguien lo cuela, este test lo
    tiene que cazar.

Ejecutar:  python test_forma.py
"""

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_no_lanza():
    import forma_equipos as fe

    for malo in (None, '', 7, {}, [], 'Equipo Que No Existe 12345'):
        try:
            fe.de(malo)
            fe.resumen(malo)
        except Exception as e:
            check(False, 'lanzó con %r: %r' % (malo, e))
    for malo in (None, 7, {}, [], {'apuesta': None}, {'partido': 3}):
        try:
            fe.del_pick(malo)
            fe.resumen_pick(malo)
        except Exception as e:
            check(False, 'del_pick lanzó con %r: %r' % (malo, e))
    check(True, 'de/resumen/del_pick aguantan basura')


def probar_no_miente():
    import forma_equipos as fe

    check(fe.resumen('Equipo Que No Existe 12345') == '',
          'de un equipo desconocido devuelve cadena vacía, no un texto vago')
    check(fe.MIN_PARTIDOS >= 5,
          'no se enseña forma con menos de 5 partidos (%d)' % fe.MIN_PARTIDOS)
    check(fe.VENTANA == 10, 'la ventana es de 10 partidos, como lo medido')

    m = fe.cargar()
    check(len(m) > 500, 'hay forma de bastantes equipos (%d)' % len(m))
    for eq, f in list(m.items())[:200]:
        if f['gana'] + f['empata'] + f['pierde'] != f['de']:
            check(False, 'las cuentas de %s no cuadran: %r' % (eq, f))
            break
        if f['de'] < fe.MIN_PARTIDOS or f['de'] > fe.VENTANA:
            check(False, '%s tiene %d partidos, fuera de rango' % (eq, f['de']))
            break
    else:
        check(True, 'ganados + empatados + perdidos = jugados, en toda la muestra')


def probar_a_que_equipo_apunta():
    import forma_equipos as fe

    check(fe.del_pick({'apuesta': 'Gana Nueva Chicago',
                       'partido': 'Nueva Chicago vs Colegiales'})
          == 'Nueva Chicago', '«Gana X» devuelve X, sin el «Gana»')
    check(fe.del_pick({'apuesta': 'Más de 2.5 goles',
                       'partido': 'Santos vs Bahia'}) == 'Santos',
          'si la apuesta no es un «Gana», cae al local del partido')
    check(fe.del_pick({'apuesta': 'algo', 'partido': 'sin separador'}) == '',
          'sin « vs » no se inventa un equipo')

    # acentos y mayúsculas no pueden partir la búsqueda
    if fe.de('Santos'):
        check(fe.de('SANTOS') is not None and fe.de('  santos  ') is not None,
              'la búsqueda ignora mayúsculas y espacios')


def probar_que_no_es_un_filtro():
    """Lo importante: que nadie lo convierta en puerta sin volver a medirlo."""
    import escalera as esc
    import inspect

    fuente = inspect.getsource(esc)
    check('forma_equipos' not in fuente,
          'la escalera NO importa la forma: se midió y no pasa el tramo de '
          'juicio (p5 -8,70 %), así que se enseña pero no filtra')

    # y la prueba de verdad: un equipo en mala forma tiene que poder salir
    p = {'apuesta': 'Gana Nueva Chicago', 'partido': 'Nueva Chicago vs X',
         'cuota': 2.20, 'ev': 0.04, 'margen_pin': 0.04, 'validado': True}
    check(esc.elegir([p]) is not None,
          'un equipo que ganó 2 de 10 sigue pudiendo salir: la banda de mala '
          'forma es la que MÁS rindió (+23,25 %)')


def probar_cache():
    import forma_equipos as fe

    a = fe.cargar()
    b = fe.cargar()
    check(a is b, 'la segunda llamada usa la caché, no relee 77 ficheros')
    fe.olvidar()
    check(fe.cargar() is not b, 'olvidar() fuerza la recarga')


if __name__ == '__main__':
    print('=== 1. nunca lanza ===')
    probar_no_lanza()
    print('\n=== 2. no miente ===')
    probar_no_miente()
    print('\n=== 3. a qué equipo apunta ===')
    probar_a_que_equipo_apunta()
    print('\n=== 4. NO es un filtro ===')
    probar_que_no_es_un_filtro()
    print('\n=== 5. la caché ===')
    probar_cache()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
