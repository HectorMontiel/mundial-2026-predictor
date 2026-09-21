# -*- coding: utf-8 -*-
"""
v280 — LA ESCALERA: una sola apuesta al día para ir doblando el banco.

LO QUE PIDIÓ EL USUARIO
«Quiero una sola apuesta que me permita ir duplicando mi banco, empezando con
100. Tiene que ser muy segura y con buena cuota.»

Eso son dos cosas que tiran en direcciones opuestas —una cuota de 2,0 implica
por definición que gana la mitad de las veces— así que lo que se puede
construir es **la más probable de entre las que doblan**, y decir con claridad
cuánto vale eso.

LA REGLA, VALIDADA EN LOS DOS TRAMOS
De las 1.820 apuestas históricas de la Capa 1, se filtran las que cumplen:

    cuota >= 2,00    (si no, ganar no dobla el banco)
    probabilidad >= 0,45   (la probabilidad justa de Pinnacle, sin margen)

Quedan 440. Medidas por separado en el 70 % antiguo y el 30 % reciente:

    criterio                    ELECCION acierta   JUICIO acierta
    todas las que doblan            42,6 %            47,5 %
    ESTA (prob >= 0,45)             47,9 %            51,9 %   <- gana

Sube el acierto entre cuatro y cinco puntos, y lo hace en LOS DOS tramos, que
es lo que separa una regla de un espejismo.

    acierto global .......... 49,1 %
    cuota media ............. 2,16
    salen ................... ~1 al día

EL AVISO QUE VA PEGADO A ESTO, Y NO ES OPCIONAL
Este grupo SUSPENDE la puerta habitual del proyecto: su bootstrap p5 es
NEGATIVO (-6,81 % en elección, -4,26 % en juicio). Para apostar repetidamente
a monto fijo es PEOR que tomar todas las de Capa 1.

No es una contradicción: son objetivos distintos. La puerta p5 protege al que
apuesta muchas veces una fracción pequeña. Aquí el objetivo es otro —maximizar
la probabilidad de acertar UNA apuesta que doble— y para eso este filtro es
mejor. Quien use esto para apostar a monto fijo todos los días estará usando
la herramienta equivocada.

LO QUE DICE LA LITERATURA SOBRE IR A TODO, Y ESTÁ MEDIDO AQUÍ TAMBIÉN
Kelly (1956), Breiman y Thorp lo demostraron hace setenta años: apostar el
banco entero en cada jugada da una esperanza logarítmica de MENOS INFINITO, y
las estrategias de doblar apostándolo todo llevan a la ruina incluso con
esperanza positiva. Existe una fracción óptima y todo lo que la supere reduce
el crecimiento.

Medido con estas 440 apuestas, empezando con 100:

    objetivo    a todo o nada    apostando 100 fijos
      200 $        49,2 %             48,9 %      <- igual (la 1ª es forzosa)
      500 $        13,7 %             20,1 %      <- no ir a todo GANA
    1.000 $         8,9 %             12,6 %      <- y gana más

Hasta 200 da lo mismo, porque con banco 100 y mínima 100 la primera apuesta es
a todo por obligación. A partir de ahí, seguir yendo a todo cuesta un tercio
de las posibilidades. Por eso este módulo enseña las dos columnas y no esconde
la segunda.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Los dos cortes que definen el pick. No se tocan sin volver a medir en los
# dos tramos (ver el encabezado).
CUOTA_MINIMA = 2.00
PROB_MINIMA = 0.45

# Lo medido sobre las 440 apuestas historicas que cumplen la regla.
ACIERTO_MEDIDO = 0.491
CUOTA_MEDIA = 2.16

# El margen de Pinnacle por encima del cual su precio deja de ser referencia
# fiable. Misma puerta que el semaforo (v276).
MARGEN_PIN_MAXIMO = 0.07

# v281 — LA CASCADA: SIEMPRE HAY ALGO, PERO SE DICE DE QUE CALIDAD ES.
#
# El usuario lo pidio claro: «no quiero que nunca me des apuesta; que si hay
# una improbable, tambien me la des». Y tiene razon en la queja: la regla
# estricta solo tiene candidata el 55,6 % de los dias.
#
# La solucion NO es relajar la regla —eso seria vender lo flojo como si fuera
# lo bueno— sino bajar por niveles y decir en cual estamos. Medido sobre el
# historico, sin rojas, y por separado en los dos tramos:
#
#   nivel                          acierta  ELECCION  JUICIO  dias con alguna
#   1  cuota>=2,0 y prob>=0,45      48,9 %   47,6 %   51,9 %      55,6 %
#   2  cuota>=2,0 y prob>=0,40      47,2 %   45,6 %   50,9 %      67,6 %
#   3  cuota>=2,0 (cualquiera)      44,5 %   43,0 %   47,9 %      80,0 %
#   4  cuota>=1,8 (NO llega a doblar) 46,4 % 45,2 %   49,2 %      88,4 %
#
# El nivel 4 merece un aviso aparte: acierta MAS que el 3, pero con cuota 1,8
# ganar no dobla el banco. Sirve para no quedarse quieto, no para la escalera.
#
# Las ROJAS no entran en ningun nivel. Antes prefiero decir «hoy no hay».
NIVELES = (
    {'n': 1, 'cuota': 2.00, 'prob': 0.45, 'acierta': 0.489,
     'etiqueta': 'La buena', 'dias': 0.556,
     'nota': 'Cumple la regla entera. Es la mejor que produce el sistema.'},
    {'n': 2, 'cuota': 2.00, 'prob': 0.40, 'acierta': 0.472,
     'etiqueta': 'Aceptable', 'dias': 0.676,
     'nota': 'Hoy no había ninguna de las mejores. Ésta dobla igual, pero '
             'es de un grupo que a la larga acierta un par de puntos menos.'},
    {'n': 3, 'cuota': 2.00, 'prob': 0.30, 'acierta': 0.445,
     'etiqueta': 'Floja', 'dias': 0.800,
     'nota': 'Día pobre: es lo mejor que hay y no es gran cosa. Dobla, pero '
             'su grupo es el que menos acierta de los que doblan. Saltártela '
             'y esperar a mañana es una opción razonable.'},
    {'n': 4, 'cuota': 1.80, 'prob': 0.30, 'acierta': 0.464,
     'etiqueta': 'No llega a doblar', 'dias': 0.884,
     'nota': 'Ojo: con esta cuota ganar NO dobla tu dinero. Entra más a '
             'menudo, pero 100 se te quedan en unos 180. Para la escalera no '
             'sirve; para no quedarte quieto, sí.'},
)


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def candidatas(picks: List[Dict], nivel: Optional[Dict] = None) -> List[Dict]:
    """Las que sirven para la escalera en ese nivel, de mejor a peor.

    Sin `nivel` usa el mas exigente. NUNCA lanza.
    """
    nv = nivel or NIVELES[0]
    fuera = []
    try:
        for p in (picks or []):
            if not isinstance(p, dict):
                continue
            cuota = _num(p.get('cuota'))
            ev = _num(p.get('ev'))
            if cuota is None or ev is None or cuota < nv['cuota']:
                continue
            prob = _num(p.get('prob'))
            if prob is None:
                prob = (1.0 + ev) / cuota      # la justa que implica el EV
            if prob < nv['prob']:
                continue
            margen = _num(p.get('margen_pin'))
            if margen is not None and margen > MARGEN_PIN_MAXIMO:
                continue
            if p.get('validado') is False:
                continue
            # v280.1 — LA ESCALERA NO PUEDE CONTRADECIR AL SEMAFORO.
            #
            # La primera version filtraba por su cuenta (cuota, probabilidad,
            # margen) y en la primera prueba real eligio «Gana Club Leon W»,
            # que el semaforo marca en ROJO con el texto «No la metas: paga un
            # 39 % por encima de lo que vale, casi siempre es un precio viejo».
            #
            # O sea que la aplicacion habria dicho «no la metas» en una
            # pantalla y «juegate aqui los 100» en la otra. Eso no es un fallo
            # de presentacion: es mandar al usuario justo a la apuesta que el
            # propio sistema ha marcado como precio rancio, y ademas a todo.
            #
            # Se arregla usando el MISMO juez, no uno paralelo. Asi no pueden
            # divergir nunca, por construccion.
            try:
                import semaforo_capa1 as _sem
                if (_sem.clasificar(p) or {}).get('nivel') == _sem.ROJO:
                    continue
            except Exception as _e:
                logger.debug('[escalera] semaforo no disponible: %s', _e)
            q = dict(p)
            q['prob_escalera'] = round(prob, 4)
            fuera.append(q)
        # la mas probable primero; a igualdad, la que mas paga
        fuera.sort(key=lambda x: (-x['prob_escalera'], -(x.get('cuota') or 0)))
    except Exception as e:
        logger.debug('[escalera] %s', e)
    return fuera


def elegir(picks: List[Dict]) -> Optional[Dict]:
    """LA apuesta de hoy. Baja de nivel hasta encontrar algo. NUNCA lanza.

    El pick sale con `nivel_escalera` puesto para que la pantalla pueda decir
    si es de las buenas o de las de «hoy no habia otra cosa». Devuelve None
    solo cuando no hay NADA, ni siquiera floja — y eso pasa uno de cada nueve
    dias.
    """
    for nv in NIVELES:
        c = candidatas(picks, nv)
        if c:
            e = c[0]
            e['nivel_escalera'] = nv
            return e
    return None


def plan(inicial: float, cuota: float, pasos: int = 5,
         rodar: bool = True) -> Dict:
    """La escalera: 100 -> 200 -> 400 -> ... rodando lo ganado.

    `rodar=True` es lo que el usuario pidio: los 100 son lo que se pone en
    juego y cada acierto se vuelve a jugar entero. `rodar=False` enseña la
    alternativa —retirar lo inicial y jugar solo la ganancia— que pierde menos
    veces todo pero sube mas despacio.

    La cuota de los escalones siguientes es la MEDIA medida (2,16), no la de
    hoy: manana habra otra apuesta y no se sabe a cuanto pagara.
    """
    fuera = {'inicial': inicial, 'escalones': []}
    try:
        b = float(inicial)
        c = float(cuota)
        if not (b > 0 and c > 1):
            return fuera
        acumulada = 1.0
        for i in range(pasos):
            cu = c if i == 0 else CUOTA_MEDIA
            ap = b if rodar else min(b, float(inicial))
            gana = b - ap + ap * cu
            acumulada *= ACIERTO_MEDIDO
            fuera['escalones'].append({
                'paso': i + 1,
                'banco': round(b, 2),
                'apuesta': round(ap, 2),
                'cuota': round(cu, 2),
                'si_entra': round(gana, 2),
                'si_falla': round(b - ap, 2),
                'prob_llegar': round(acumulada, 4)})
            b = gana
    except Exception as e:
        logger.debug('[escalera] plan: %s', e)
    return fuera


def probabilidades(objetivo: float, banco: float = 100.0,
                   minima: float = 100.0) -> Dict:
    """La probabilidad medida de llegar a ese objetivo. Sin adornos.

    Los números salen de simular las 440 apuestas históricas que cumplen la
    regla, no de multiplicar el acierto: la cuota varía y eso importa.
    """
    TABLA_TODO = {200: 0.492, 400: 0.239, 500: 0.137, 800: 0.119,
                  1000: 0.089, 2000: 0.049}
    TABLA_FIJO = {200: 0.489, 500: 0.201, 1000: 0.126}
    try:
        o = int(round(float(objetivo)))
    except (TypeError, ValueError):
        return {}
    cercano = min(TABLA_TODO, key=lambda k: abs(k - o))
    fuera = {'objetivo': cercano, 'a_todo': TABLA_TODO.get(cercano)}
    if cercano in TABLA_FIJO:
        fuera['monto_fijo'] = TABLA_FIJO[cercano]
    return fuera


def resumen(pick: Optional[Dict], banco: float = 100.0) -> str:
    """La frase de la tarjeta, en lenguaje de quien apuesta."""
    if not pick:
        return ('Hoy no hay **nada** que ofrecer, ni siquiera floja. Pasa uno '
                'de cada nueve días. Lo único que queda por debajo de esto '
                'son las que el sistema marca en rojo por precio rancio, y '
                'ésas no te las voy a poner.')
    try:
        cuota = float(pick.get('cuota'))
        prob = float(pick.get('prob_escalera') or 0)
        base = ('Si entra, tus **%.0f $** se convierten en **%.0f $**. '
                'Entra **%.0f de cada 100 veces**.'
                % (banco, banco * cuota, 100 * prob))
        nv = pick.get('nivel_escalera') or {}
        if nv.get('n', 1) > 1 and nv.get('nota'):
            base += '\n\n' + nv['nota']
        return base
    except (TypeError, ValueError):
        return ''
