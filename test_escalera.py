#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la escalera (v280).

Lo que se vigila aquí es lo que puede costarle dinero al usuario, y una cosa
por encima de todas:

  · LA ESCALERA NO PUEDE ELEGIR LO QUE EL SEMÁFORO PROHÍBE. En la primera
    prueba real eligió un pick marcado en ROJO —«no la metas, paga un 39 % por
    encima de lo que vale»— y lo habría puesto arriba del todo diciendo
    «juégate aquí los 100». Es el peor fallo posible de esta pantalla.
  · cada apuesta cae en el nivel que le toca, y el nivel es lo que le dice al
    usuario si la de hoy es de las buenas o es lo que había. Desde la v292 el
    nivel 1 acepta cuota 1,90 —acierta más y por eso va primero— pero su nota
    tiene que avisar de que a esa cuota NO se dobla.
  · no puede elegir en ligas donde Pinnacle cobra margen alto.
  · y no puede lanzar, porque va en el render.

Ejecutar:  .venv\\Scripts\\python test_escalera.py
"""

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _pick(**kw):
    base = {'apuesta': 'Gana X', 'partido': 'A vs B', 'cuota': 2.20,
            'ev': 0.04, 'margen_pin': 0.04, 'validado': True}
    base.update(kw)
    return base


def probar_filtros():
    import escalera as esc

    # v292 — CINCO NIVELES, Y EL MAS ALTO YA NO ES EL QUE DOBLA.
    #
    # Medido: `cuota>=1,9 y prob>=0,50` acierta el 51,8 % contra el 48,9 % de
    # `cuota>=2,0 y prob>=0,45`, y es consistente en los dos tramos. Asi que
    # el nivel 1 pasa a ser «la mas probable» y el que dobla limpio es el 2.
    # El precio esta dicho en su nota: a 1,90 no se dobla.
    e = esc.elegir([_pick()])          # cuota 2,20 · prob 47,3 %
    check(e is not None, 'una candidata normal se elige')
    check((e.get('nivel_escalera') or {}).get('n') == 2,
          'cuota 2,20 y prob 47 % es nivel 2, «La que dobla»')

    mas_prob = esc.elegir([_pick(cuota=1.95, ev=0.01)])   # prob 51,8 %
    check(mas_prob is not None
          and (mas_prob.get('nivel_escalera') or {}).get('n') == 1,
          'cuota 1,95 y prob 52 % sube al nivel 1, «La más probable»')
    check('no dobla' in (mas_prob['nivel_escalera'].get('nota') or ''),
          'y su nota avisa de que a esa cuota no se dobla')

    # v281 — LA CASCADA. El usuario pidio que nunca falte apuesta, asi que
    # estas ya NO devuelven None: bajan de nivel. Lo que hay que comprobar es
    # que el nivel que sale es el correcto, porque es lo que le dice al
    # usuario que la de hoy es peor.
    e2 = esc.elegir([_pick(cuota=1.85, ev=0.03)])     # prob 55,7 %
    check(e2 is not None
          and (e2.get('nivel_escalera') or {}).get('n') == 5,
          'cuota 1,85 baja al ultimo nivel («no llega a doblar»)')
    check('NO dobla' in (e2['nivel_escalera'].get('nota') or ''),
          'y la nota avisa de que ganar no dobla el dinero')

    # v297 — «Aceptable» paso del 3 al 4 al meterse la combinada en medio.
    e3 = esc.elegir([_pick(cuota=2.50, ev=0.02)])     # prob 40,8 %
    check(e3 is not None
          and (e3.get('nivel_escalera') or {}).get('etiqueta') == 'Aceptable',
          'probabilidad 0,41 baja al nivel «aceptable»')

    check(esc.elegir([_pick(cuota=1.30, ev=0.02)]) is None,
          'por debajo de TODOS los niveles si devuelve None')
    # v294/v295 — EL MARGEN ALTO YA NO DEVUELVE None, PERO TIENE TECHO.
    #
    # Antes un margen del 13 % tumbaba el pick y la seccion salia vacia, que es
    # lo que el usuario vio en produccion el 2026-09-21 con siete picks en
    # pantalla. Ahora cae al nivel 6 CON el aviso por delante. Lo que no puede
    # es no tener limite: por encima del 15 % el precio de Pinnacle ya no
    # informa de nada y ahi no se ofrece nada, ni con bandera.
    alto = esc.elegir([_pick(margen_pin=0.13)])
    check(alto is not None
          and (alto.get('nivel_escalera') or {}).get('n') == 6,
          'margen del 13 % baja al nivel 6, «fuera de lo medido»')
    check((alto.get('nivel_escalera') or {}).get('margen_libre') is True
          and 'sin red' in (alto['nivel_escalera'].get('nota') or ''),
          'y sale marcado como sin respaldo, no como una mas')
    check(esc.elegir([_pick(margen_pin=0.18)]) is None,
          'margen del 18 % NO sale: por encima del techo no hay señal')
    check(esc.MARGEN_PIN_TOPE > esc.MARGEN_PIN_MAXIMO,
          'el techo esta por encima de la puerta validada, no al reves')
    check(esc.elegir([_pick(validado=False)]) is None,
          'un deporte sin validar queda fuera')
    check(esc.elegir([]) is None, 'sin picks devuelve None')
    check(esc.elegir(None) is None, 'None devuelve None')


def probar_no_contradice_al_semaforo():
    """El fallo que de verdad importa."""
    import escalera as esc
    import semaforo_capa1 as sm

    roja = _pick(apuesta='Gana Club Leon W', cuota=2.30, ev=0.392,
                 margen_pin=0.056)
    check(sm.clasificar(roja)['nivel'] == sm.ROJO,
          'el caso de prueba ES una roja para el semaforo')
    check(esc.elegir([roja]) is None,
          'y la escalera NO la elige (si no, la app se contradice)')

    # con una roja y una buena, elige la buena
    buena = _pick()
    e = esc.elegir([roja, buena])
    check(e is not None and e.get('apuesta') == 'Gana X',
          'con una roja y una buena, elige la buena')

    # ninguna candidata puede ser roja, pase lo que pase
    for c in esc.candidatas([roja, buena, _pick(ev=0.35, cuota=2.6)]):
        check(sm.clasificar(c)['nivel'] != sm.ROJO,
              'ninguna candidata es roja (%s)' % c.get('apuesta'))


def probar_varias_opciones():
    """v291 — la seccion enseña varias y el usuario elige."""
    import escalera as esc
    import semaforo_capa1 as sm

    # v296 — cada una en SU partido. Desde que «una sola por partido» es la
    # regla, cinco picks del mismo encuentro colapsan en uno solo y este test
    # media otra cosa sin enterarse.
    picks = sm.ordenar([
        _pick(apuesta='mas probable', partido='A1 vs B1', cuota=1.95, ev=0.01),
        _pick(apuesta='dobla', partido='A2 vs B2', cuota=2.20, ev=0.04),
        _pick(apuesta='aceptable', partido='A3 vs B3', cuota=2.40, ev=0.02),
        _pick(apuesta='no dobla', partido='A4 vs B4', cuota=1.85, ev=0.03),
        _pick(apuesta='ROJA', partido='A5 vs B5', cuota=2.30, ev=0.39),
    ])
    t = esc.todas(picks)
    check(len(t) == 4, 'salen las cuatro que sirven, no una (salieron %d)'
          % len(t))
    check(t and t[0].get('apuesta') == 'mas probable',
          'y la primera es la MAS PROBABLE, no la que mas paga')
    # v295 — ESTO SE COMPROBABA EN VACIO. `todas` no ponia la clave `semaforo`,
    # asi que `(x.get('semaforo') or {}).get('nivel')` valia None para todas y
    # la comprobacion pasaba sin mirar nada. Y en la pantalla el circulo de
    # color caia siempre en el amarillo por defecto. Primero se exige que la
    # clave ESTE, y despues ya se mira lo que dice.
    check(all(isinstance(x.get('semaforo'), dict) for x in t),
          'cada opcion trae su veredicto del semaforo (la pantalla lo pinta)')
    check(all((x.get('semaforo') or {}).get('nivel') in
              (sm.VERDE, sm.AMBAR) for x in t),
          'y NINGUNA de ellas es roja, este en la posicion que este')
    check(all((x.get('semaforo') or {}).get('nivel')
              == sm.clasificar(x).get('nivel') for x in t),
          'el veredicto adjunto es el MISMO que da el semaforo por su cuenta')
    niveles = [(x.get('nivel_escalera') or {}).get('n') for x in t]
    check(niveles == sorted(niveles),
          'salen ordenadas de mejor a peor nivel (%s)' % niveles)
    check(all('nivel_escalera' in x for x in t),
          'cada una trae su nivel, para que la pantalla lo pinte')

    check(esc.todas([]) == [], 'sin picks no rompe')
    check(esc.todas(None) == [], 'None tampoco')
    check(len(esc.todas(picks, tope=2)) == 2, 'el tope se respeta')

    # la primera de la lista tiene que ser la MISMA que elegir()
    e = esc.elegir(picks)
    check(e is not None and t and e.get('apuesta') == t[0].get('apuesta'),
          'la primera de la lista es la que elegir() recomienda')


def probar_otros_mercados():
    """v296 — «que no sean sólo para el gane sino para cualquier estadística»."""
    import escalera as esc

    gol = _pick(apuesta='Más de 2.5 goles', partido='A vs B', mercado='Goles',
                cuota=2.10, ev=0.04, validado=False, margen_pin=0.06)

    # entra, pero SOLO por el nivel que lo dice, y ese va el ultimo
    e = esc.elegir([gol])
    check(e is not None, 'un pick de goles ya no se cae de la escalera')
    etq = (e.get('nivel_escalera') or {}).get('etiqueta') if e else None
    check(etq == 'Otro mercado',
          'entra por el nivel de «otro mercado» (salio %s)' % etq)
    # v297.1 — y NO por el de la combinada, que tiene medicion propia y no
    # es la suya. Un «Más de 2,5» suelto no puede heredar esos numeros.
    check(etq != 'Combinada del partido',
          'un pick de goles suelto NO se cuela en el nivel de la combinada')
    check((e.get('nivel_escalera') or {}).get('otros_mercados') is True,
          'y ese nivel esta marcado como de otros mercados')
    check('no tiene medición propia' in
          ((e.get('nivel_escalera') or {}).get('nota') or ''),
          'con el aviso de que el canal aun acumula')

    # lo que NO puede pasar: colarse en un nivel medido y salir con su sello
    for nv in esc.NIVELES:
        if nv.get('otros_mercados'):
            continue
        check(not esc.candidatas([gol], nv),
              'el pick de goles no entra en el nivel %s, que es del 1X2'
              % nv['n'])

    # y el 1X2 de siempre sigue yendo delante
    t = esc.todas([gol, _pick(apuesta='Gana X', partido='C vs D',
                              cuota=1.95, ev=0.01)])
    check(len(t) == 2 and t[0].get('apuesta') == 'Gana X',
          'el ganador medido va ANTES que el mercado sin medir')


def probar_una_sola_por_partido():
    """«Sólo apuesta de una»: el mismo partido no ocupa dos huecos."""
    import escalera as esc

    # v297.1 — la regla es «un partido, un MERCADO». El mismo encuentro puede
    # salir como ganador y como combinada —son dos productos y el usuario
    # elige— pero NUNCA con dos lineas de goles, que parecen dos
    # oportunidades y son la misma apuesta a distinto precio.
    dos_goles = [
        _pick(apuesta='Más de 2.5 goles', partido='A vs B', mercado='Goles',
              cuota=2.10, ev=0.04, validado=False),
        _pick(apuesta='Más de 3.5 goles', partido='A vs B', mercado='Goles',
              cuota=3.10, ev=0.06, validado=False),
        _pick(apuesta='Gana Otro', partido='C vs D', cuota=2.20, ev=0.04),
    ]
    t = esc.todas(dos_goles)
    claves = [(x.get('partido'), x.get('mercado')) for x in t]
    check(len(claves) == len(set(claves)),
          'ningun partido repite mercado (%s)' % claves)
    check(len(t) == 2,
          'las dos lineas de goles del mismo partido cuentan como una (%d)'
          % len(t))

    mixto = [
        _pick(apuesta='Gana Local', partido='A vs B', mercado='Ganador',
              cuota=1.95, ev=0.01),
        _pick(apuesta='Gana Local + Más de 2.5', partido='A vs B',
              mercado='Combinada', cuota=2.60, ev=0.08, prob=0.42,
              validado=False),
    ]
    t = esc.todas(mixto)
    check(len(t) == 2,
          'el mismo partido SI puede salir como ganador y como combinada')


def probar_no_baja_a_cuota_1_50_en_el_1x2():
    """La banda 1,50-1,80 se midio y es la PEOR. No se abre por gusto."""
    import escalera as esc

    # medido sobre 1.803 picks: 1,50-1,80 da ROI -0,61 % global y, en el tramo
    # de juicio, -11,98 % con p5 -26,76 %. Es la unica banda que pierde.
    for nv in esc.NIVELES:
        if nv.get('otros_mercados'):
            continue      # el nivel 7 es de otro mercado y otro canal
        check(nv['cuota'] >= 1.80,
              'ningun nivel del 1X2 baja de 1,80 (el %s pide %.2f)'
              % (nv['n'], nv['cuota']))
    check(esc.elegir([_pick(cuota=1.60, ev=0.02)]) is None,
          'un ganador a cuota 1,60 NO se ofrece: esa banda pierde')


def probar_orden():
    import escalera as esc

    picks = [_pick(apuesta='menos probable', cuota=2.60, ev=0.19),
             _pick(apuesta='mas probable', cuota=2.10, ev=0.03)]
    e = esc.elegir(picks)
    check(e is not None and e['apuesta'] == 'mas probable',
          'elige la MAS probable, que es lo que importa al ir a todo')


def probar_plan():
    import escalera as esc

    p = esc.plan(100.0, 2.20)
    es = p.get('escalones') or []
    check(len(es) == 5, 'el plan trae cinco escalones (salieron %d)' % len(es))
    check(abs(es[0]['si_entra'] - 220.0) < 0.01,
          '100 a cuota 2,20 dan 220 (salio %s)' % es[0]['si_entra'])
    check(es[0]['apuesta'] == 100.0 and es[1]['apuesta'] == es[0]['si_entra'],
          'rodando, el segundo escalon apuesta todo lo ganado')
    probs = [x['prob_llegar'] for x in es]
    check(all(probs[i] > probs[i + 1] for i in range(len(probs) - 1)),
          'la probabilidad de llegar BAJA en cada escalon')
    check(probs[0] < 0.55,
          'el primer escalon no promete mas de la mitad (%.3f)' % probs[0])
    check(probs[3] < 0.10,
          'el cuarto escalon esta por debajo del 10 %% (%.3f)' % probs[3])

    # sin rodar: se apuesta siempre lo inicial
    p2 = esc.plan(100.0, 2.20, rodar=False)
    e2 = p2['escalones']
    check(all(x['apuesta'] == 100.0 for x in e2),
          'sin rodar, siempre se apuestan los 100 iniciales')

    for malo in ((0, 2.0), (100, 1.0), (100, 0), (-5, 2.0)):
        try:
            esc.plan(*malo)
        except Exception as e:
            check(False, 'plan lanzo con %r: %r' % (malo, e))


def probar_numeros_medidos():
    """Los numeros de la tarjeta son los medidos. Si cambian, que se vea."""
    import escalera as esc
    check(esc.CUOTA_MINIMA == 2.00, 'la cuota minima es 2,00')
    check(esc.PROB_MINIMA == 0.45, 'la probabilidad minima es 0,45')
    check(abs(esc.ACIERTO_MEDIDO - 0.518) < 1e-6,
          'el acierto de referencia es el del nivel 1: 51,8 %')
    check(esc.NIVELES[0]['acierta'] > esc.NIVELES[1]['acierta'],
          'el nivel 1 acierta MAS que el 2, que es lo que lo hace nivel 1')
    check(esc.NIVELES[0]['cuota'] < esc.NIVELES[1]['cuota'],
          'y lo consigue bajando la cuota, no subiendo la probabilidad')
    pr = esc.probabilidades(1000)
    check(pr.get('a_todo') == 0.089 and pr.get('monto_fijo') == 0.126,
          'llegar a 1.000: 8,9 %% a todo, 12,6 %% a monto fijo (%s)' % pr)
    check(pr['monto_fijo'] > pr['a_todo'],
          'y la tabla dice que NO ir a todo es mejor, que es lo medido')


def probar_no_lanza():
    import escalera as esc

    for malo in ([{}], [None], [7], [{'cuota': 'x', 'ev': 'y'}],
                 [{'cuota': float('nan'), 'ev': 0.04}]):
        try:
            esc.candidatas(malo)
            esc.elegir(malo)
        except Exception as e:
            check(False, 'lanzo con %r: %r' % (malo, e))
    check(True, 'candidatas y elegir aguantan basura')
    check(esc.resumen(None) != '', 'sin pick hay mensaje de todos modos')
    check('100' in esc.resumen(_pick(), 100), 'el resumen menciona el importe')


if __name__ == '__main__':
    print('=== 1. los filtros ===')
    probar_filtros()
    print('\n=== 2. no contradice al semaforo ===')
    probar_no_contradice_al_semaforo()
    print('\n=== 2c. varias opciones ===')
    probar_varias_opciones()
    print('\n=== 2d. otros mercados (v296) ===')
    probar_otros_mercados()
    print('\n=== 2e. una sola por partido ===')
    probar_una_sola_por_partido()
    print('\n=== 2f. la banda 1,50 no se abre ===')
    probar_no_baja_a_cuota_1_50_en_el_1x2()
    print('\n=== 3. el orden ===')
    probar_orden()
    print('\n=== 4. el plan ===')
    probar_plan()
    print('\n=== 5. los numeros medidos ===')
    probar_numeros_medidos()
    print('\n=== 6. nunca lanza ===')
    probar_no_lanza()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
