#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la escalera (v280).

Lo que se vigila aquí es lo que puede costarle dinero al usuario, y una cosa
por encima de todas:

  · LA ESCALERA NO PUEDE ELEGIR LO QUE EL SEMÁFORO PROHÍBE. En la primera
    prueba real eligió un pick marcado en ROJO —«no la metas, paga un 39 % por
    encima de lo que vale»— y lo habría puesto arriba del todo diciendo
    «juégate aquí los 100». Es el peor fallo posible de esta pantalla.
  · no puede elegir cuotas por debajo de 2,00, porque entonces ganar NO dobla.
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

    e = esc.elegir([_pick()])
    check(e is not None, 'una candidata normal se elige')
    check((e.get('nivel_escalera') or {}).get('n') == 1,
          'y sale marcada como nivel 1, «La buena»')

    # v281 — LA CASCADA. El usuario pidio que nunca falte apuesta, asi que
    # estas ya NO devuelven None: bajan de nivel. Lo que hay que comprobar es
    # que el nivel que sale es el correcto, porque es lo que le dice al
    # usuario que la de hoy es peor.
    e2 = esc.elegir([_pick(cuota=1.90, ev=0.03)])
    check(e2 is not None
          and (e2.get('nivel_escalera') or {}).get('n') == 4,
          'cuota 1,90 baja al nivel 4 («no llega a doblar»)')
    check('NO dobla' in (e2['nivel_escalera'].get('nota') or ''),
          'y la nota avisa de que ganar no dobla el dinero')

    e3 = esc.elegir([_pick(cuota=2.50, ev=0.02)])
    check(e3 is not None
          and (e3.get('nivel_escalera') or {}).get('n') == 2,
          'probabilidad 0,41 baja al nivel 2 («aceptable»)')

    check(esc.elegir([_pick(cuota=1.30, ev=0.02)]) is None,
          'por debajo de TODOS los niveles si devuelve None')
    check(esc.elegir([_pick(margen_pin=0.13)]) is None,
          'liga con margen de Pinnacle del 13 % queda fuera')
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
    check(abs(esc.ACIERTO_MEDIDO - 0.491) < 1e-6,
          'el acierto medido es 49,1 %')
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
