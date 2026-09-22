#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la combinada del mismo partido (v297).

Aquí hay dinero real en juego y una cosa que vigilar por encima de todo:

  · LA CORRELACION ES LA VENTAJA. Si alguien pone `CORRELACION = 1.0` la
    combinada deja de tener sentido —pasa a ser dos apuestas con doble vig— y
    nadie se entera, porque los números de la pantalla siguen saliendo. Este
    test lo caza.
  · LAS DOS PATAS, EN LA MISMA CASA. Una combinada repartida entre dos casas
    no existe: son dos apuestas sueltas y el usuario no puede meterla en un
    boleto. El barrido busca la casa que tenga las dos cosas.
  · LA CONJUNTA NO PUEDE PASAR DE LA PATA MAS FLOJA, por mucha correlación.
  · Y que no lance, porque va en el render.

Ejecutar:  python test_combinada.py
"""

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _pick(**kw):
    base = {'apuesta': 'Gana Local', 'partido': 'A vs B', 'cuota': 1.80,
            'prob': 0.55, 'ev': 0.04, 'lado': 'home', 'casa': 'Casa1',
            'margen_pin': 0.04, 'validado': True,
            'combi': {'casa': 'Casa1', 'cuota_1x2': 1.80, 'prob_1x2': 0.55,
                      'ev_1x2': 0.04,
                      'over25': {'cuota': 1.75, 'prob': 0.52,
                                 'margen': 0.05, 'casa': 'Casa1'}}}
    base.update(kw)
    return base


def probar_solo_futbol():
    """v300 — la correlación medida es DE FÚTBOL. En otro deporte no vale.

    Sin este corte salían estas tarjetas, vistas en producción:

        Gana Kenin S. + Más de 2.5 goles    @4,16   <- TENIS
        Gana SSG Landers + Más de 2.5 goles @1,85   <- BÉISBOL (KBO)

    En tenis la línea de 2,5 son SETS y en béisbol CARRERAS. La tarjeta
    mentía en el nombre del mercado, y la ventaja que justifica toda la
    combinada —los +18,4 % de correlación— está medida sobre fútbol y nada
    más. Aplicarla fuera es inventarse el número.
    """
    import barrido_capa1 as bc

    v = {'home': 'A', 'away': 'B',
         'casas': {'C1': {'HOME_DRAW_AWAY': {'home': 2.0},
                          'OVER_UNDER': {'lineas': [
                              {'linea': 2.5, 'over': 1.9, 'under': 1.9}]}}}}
    r = {'prob_justa': {'home': 0.60, 'away': 0.25}}

    check(bc._pata_combinada(v, r, 'home', 'futbol') is not None,
          'en fútbol la combinada se arma')
    for dep in ('tenis', 'mlb', 'nba', 'nfl', '', None):
        check(bc._pata_combinada(v, r, 'home', dep) is None,
              'en %r NO se arma: la correlación no está medida ahí' % (dep,))

    # LA SEGUNDA PUERTA, Y HACE FALTA. Con sólo el corte de arriba las de
    # tenis SEGUÍAN saliendo en producción, porque hay un camino alternativo
    # —`over25`— que se rellena sin mirar el deporte. Un corte en el
    # productor se puede esquivar; uno en el consumidor, no.
    import combinada as cb

    for dep, debe in (('Fútbol', True), ('Futbol', True), ('Tenis', False),
                      ('MLB', False), ('NBA', False), ('NFL', False)):
        p = _pick(deporte=dep)
        sale = cb.de_pick(p) is not None
        check(sale is debe,
              'de_pick con deporte %r %s' % (dep, 'sale' if debe else 'NO sale'))


def probar_la_ventaja_es_la_correlacion():
    import combinada as cb

    check(cb.CORRELACION > 1.0,
          'la correlación del local es > 1: es de donde sale la ventaja')
    check(cb.CORRELACION_VISITANTE > 1.0,
          'la del visitante también (%.3f)' % cb.CORRELACION_VISITANTE)
    check(abs(cb.CORRELACION - 1.184) < 1e-6,
          'y vale lo medido sobre 17.420 partidos: 1,184')
    check(abs(cb.CORRELACION_VISITANTE - 1.162) < 1e-6,
          'y la del visitante lo medido sobre 13.012: 1,162')

    # la conjunta tiene que ser MAYOR que multiplicar, que es el error de la casa
    p1, p2 = 0.50, 0.50
    check(cb.conjunta(p1, p2) > p1 * p2,
          'la conjunta supera al producto (si no, no hay negocio)')
    check(cb.conjunta(p1, p2, 'away') > p1 * p2,
          'por el lado del visitante también')
    check(cb.conjunta(p1, p2, 'away') < cb.conjunta(p1, p2, 'home'),
          'y el visitante correlaciona algo menos, como se midió')


def probar_la_conjunta_tiene_techo():
    import combinada as cb

    # con probabilidades altas, p1*p2*1,184 se dispararia por encima de p1
    check(cb.conjunta(0.95, 0.95) <= 0.95,
          'la conjunta no puede pasar de la pata más floja')
    check(cb.conjunta(0.90, 0.60) <= 0.60,
          'ni con una pata muy probable y otra regular')
    for malo in ((0, 0.5), (0.5, 0), (-1, 0.5), (1.5, 0.5), (None, 0.5),
                 ('x', 0.5)):
        check(cb.conjunta(*malo) == 0.0,
              'basura devuelve 0, no una probabilidad inventada (%r)'
              % (malo,))


def probar_las_dos_patas_misma_casa():
    import combinada as cb

    c = cb.de_pick(_pick())
    check(c is not None, 'con las dos patas sale la combinada')
    check(c and c.get('casa') == 'Casa1',
          'y la combinada dice EN QUE CASA se mete')
    patas = (c or {}).get('patas') or []
    check(len(patas) == 2, 'trae sus dos patas para pintarlas (%d)' % len(patas))
    check(abs((c or {}).get('cuota', 0) - round(1.80 * 1.75, 2)) < 0.01,
          'la cuota es el producto de las dos (%.2f)' % (c or {}).get('cuota', 0))

    sin = _pick()
    sin.pop('combi')
    sin.pop('over25', None)
    check(cb.de_pick(sin) is None,
          'sin la segunda pata NO se inventa una combinada')


def probar_los_filtros():
    import combinada as cb

    # combinada demasiado baja: no multiplica el banco
    baja = _pick(combi={'casa': 'C', 'cuota_1x2': 1.10, 'prob_1x2': 0.88,
                        'over25': {'cuota': 1.20, 'prob': 0.80}})
    check(cb.de_pick(baja) is None,
          'por debajo de 1,50 no sale: no multiplica nada')

    # demasiado alta: eso es una soñadora, no una escalera
    alta = _pick(combi={'casa': 'C', 'cuota_1x2': 4.00, 'prob_1x2': 0.28,
                        'over25': {'cuota': 2.50, 'prob': 0.42}})
    check(cb.de_pick(alta) is None,
          'por encima de 6,00 tampoco: para eso está la Soñadora')

    # EV negativo: aunque la correlacion ayude, si no llega no se ofrece
    mala = _pick(combi={'casa': 'C', 'cuota_1x2': 1.50, 'prob_1x2': 0.55,
                        'over25': {'cuota': 1.30, 'prob': 0.60}})
    c = cb.de_pick(mala)
    check(c is None or c.get('ev', 0) > 0,
          'nunca sale una combinada con EV negativo')

    check(cb.CUOTA_MINIMA == 1.50,
          'la cuota mínima es la que pidió el usuario: 1,50')
    check(cb.PROB_MINIMA >= 0.20,
          'y hay un piso de probabilidad (%.2f)' % cb.PROB_MINIMA)


def probar_una_por_partido():
    import combinada as cb

    dos = [_pick(apuesta='Gana Local'), _pick(apuesta='Gana Local otra vez')]
    t = cb.todas(dos)
    check(len(t) == 1, 'el mismo partido da UNA combinada, no dos (%d)' % len(t))

    varias = [_pick(partido='A vs B'), _pick(partido='C vs D'),
              _pick(partido='E vs F')]
    t = cb.todas(varias)
    check(len(t) == 3, 'tres partidos dan tres combinadas')
    probs = [x.get('prob') for x in t]
    check(probs == sorted(probs, reverse=True),
          'salen de MAS a MENOS probable, que es lo que el usuario pidió')
    check(len(cb.todas(varias, tope=2)) == 2, 'el tope se respeta')


def probar_no_lanza():
    import combinada as cb

    for malo in (None, 7, {}, [], 'x', {'combi': 'no es un dict'},
                 {'combi': {'over25': None}},
                 {'combi': {'cuota_1x2': float('nan'),
                            'over25': {'cuota': 2, 'prob': 0.5}}}):
        try:
            cb.de_pick(malo)
            cb.todas([malo])
        except Exception as e:
            check(False, 'lanzó con %r: %r' % (malo, e))
    check(True, 'de_pick y todas aguantan basura')
    check(cb.todas(None) == [], 'None devuelve lista vacía')
    check(cb.resumen(None) != '', 'sin combinada hay mensaje igual')
    check('100' in cb.resumen(_pick_combinada()), 'el resumen dice el importe')


def _pick_combinada():
    import combinada as cb
    return cb.de_pick(_pick())


def probar_entra_en_la_escalera():
    """Que el nivel de la escalera la acepte de verdad."""
    import combinada as cb
    import escalera as esc

    c = cb.de_pick(_pick())
    check(c is not None, 'hay combinada de prueba')
    nivel = None
    for nv in esc.NIVELES:
        if nv.get('etiqueta') == 'Combinada del partido':
            nivel = nv
    check(nivel is not None, 'la escalera tiene un nivel para la combinada')
    if nivel and c:
        check(bool(esc.candidatas([c], nivel)),
              'y la combinada entra por ese nivel')
        # el nivel de la combinada NO puede ir antes que los medidos del 1X2
        orden = [n.get('etiqueta') for n in esc.NIVELES]
        check(orden.index('Combinada del partido') >= 2,
              'va después de los dos niveles del 1X2 que más aciertan')


def probar_el_visitante_no_esta_bloqueado():
    """v297.4 — el candado que tiró cuatro años de picks del visitante.

    `REGLAS['futbol']['lados']` valía `('home',)`, así que el barrido
    descartaba TODOS los picks del visitante antes de enseñarlos. No era que
    no estuvieran medidos: era una puerta cerrada. Lo destapó un boleto
    ganador del usuario con dos visitantes, en los dos partidos donde la
    Capa 1 apuntaba al local.

    Medido después: el visitante rinde igual o más que el local
    (+7,55 %/+13,14 % contra +6,81 %/+10,67 %, p5 positivo en los cuatro).
    Si alguien vuelve a cerrarlo, que sea con una medición y no sin querer.
    """
    import barrido_capa1 as bc

    lados = bc.REGLAS['futbol'].get('lados')
    check(lados is None,
          'el fútbol acepta los DOS lados, no sólo el local (vale %r)' % (lados,))
    nota = bc.REGLAS['futbol'].get('nota') or ''
    check('visitante' in nota,
          'y la nota dice lo que está medido de cada lado')

    # el filtro tiene que dejar pasar un pick del visitante
    val = {'ev': 0.05, 'prob_justa': 0.45, 'cuota': 2.20, 'lado': 'away'}
    check(bc._pasa('futbol', {'liga': 'x'}, val, bc.REGLAS['futbol']),
          'un pick del visitante con EV pasa el filtro')


if __name__ == '__main__':
    print('=== 0. el visitante no esta bloqueado ===')
    probar_el_visitante_no_esta_bloqueado()
    print('\n=== 0b. solo futbol (v300) ===')
    probar_solo_futbol()
    print('\n=== 1. la ventaja ES la correlacion ===')
    probar_la_ventaja_es_la_correlacion()
    print('\n=== 2. la conjunta tiene techo ===')
    probar_la_conjunta_tiene_techo()
    print('\n=== 3. las dos patas, misma casa ===')
    probar_las_dos_patas_misma_casa()
    print('\n=== 4. los filtros ===')
    probar_los_filtros()
    print('\n=== 5. una por partido ===')
    probar_una_por_partido()
    print('\n=== 6. entra en la escalera ===')
    probar_entra_en_la_escalera()
    print('\n=== 7. nunca lanza ===')
    probar_no_lanza()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
