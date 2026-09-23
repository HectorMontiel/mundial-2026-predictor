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
# El acierto del nivel 1, que es el que la pantalla proyecta por defecto.
ACIERTO_MEDIDO = 0.518
CUOTA_MEDIA = 2.16

# El margen de Pinnacle por encima del cual su precio deja de ser referencia
# fiable. Misma puerta que el semaforo (v276).
MARGEN_PIN_MAXIMO = 0.07

# v295 — Y UN TECHO DURO, QUE NI EL NIVEL 6 SALTA.
#
# El nivel 6 deja pasar margen alto para no dejar la seccion vacia, pero sin
# tope eso admitiria cualquier cosa: con un margen del 25 % la probabilidad
# «de Pinnacle» ya no es de Pinnacle, es de como se le haya quitado el vig, y
# el «error de cuota» pasa a ser un artefacto del metodo.
#
# ESTE NUMERO NO ESTA MEDIDO, Y NO PUEDE ESTARLO. En las 1.803 apuestas del
# historico solo hay SEIS por encima del 7 % y NINGUNA por encima del 12 %: el
# ledger se construye con las ligas de las que hay cuotas de cierre, y estas
# ligas pequeñas no estan. Con n=6 no se decide nada.
#
# Asi que es un criterio, y se declara como tal: 15 % es mas del doble de la
# puerta validada y deja fuera lo absurdo sin cerrar la seccion. Si algun dia
# hay muestra, se mide y se sustituye.
MARGEN_PIN_TOPE = 0.15

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
# v292 — EL NIVEL MAS PROBABLE, Y NO ESTABA DONDE PARECIA.
#
# El usuario lo pidio: «quiero que sea buena y probable». La respuesta obvia
# —subir el liston de probabilidad— casi no sirve:
#
#   regla                        n    acierta  ELECCION  JUICIO  dias con
#   cuota>=2,0 y prob>=0,45    425     49,2 %   48,1 %   51,5 %   56,0 %
#   cuota>=2,0 y prob>=0,48    258     47,7 %   46,6 %   50,0 %   39,3 %
#   cuota>=2,0 y prob>=0,50    154     50,6 %   51,0 %   50,0 %   26,1 %
#   cuota>=1,9 y prob>=0,50    278     51,8 %   52,2 %   51,1 %   40,4 %  <-
#
# De 0,45 a 0,50 se ganan 1,4 puntos de acierto y se pierde la MITAD de los
# dias. Lo que de verdad sube el acierto es bajar la cuota un pelo: 1,90 en
# vez de 2,00 da 51,8 %, consistente en los dos tramos, y esta disponible el
# 40 % de los dias.
#
# EL PRECIO, QUE HAY QUE DECIRLO: a 1,90 no se dobla. 100 se quedan en 190.
# Diez pesos menos por escalon a cambio de 2,6 puntos mas de acierto. Para
# quien quiera doblar exacto, el nivel 2 sigue ahi.
NIVELES = (
    # v302 — LA MÁS SEGURA: VISITANTE FAVORITO QUE EL MODELO TAMBIÉN VE.
    #
    # El usuario: «quiero que esas [las probables de Apuestas del Día] lleguen
    # a la escalera y tenga apuestas más seguras y con buena cuota». Medido en
    # `_v302_probables.py` sobre 78.020 partidos, 293 reglas: ninguna pasa la
    # puerta del p5, y la que más cerca se queda es ésta —
    #
    #     visitante favorito, modelo y Pinnacle >= 55 %, cuota >= 1,50
    #     n=325 · acierta 68,0 % · ELECCIÓN +8,19 % (p5 +0,15)
    #                             · JUICIO   +12,55 % (p5 -0,53)
    #
    # Va PRIMERA porque es lo que la Escalera necesita: de cada 100 acierta 68
    # a una cuota media de 1,61, o sea 110 por escalón de media contra 98 de
    # la «más probable» de abajo. Lo que NO hace es doblar: 100 se quedan en
    # unos 160. Y el aviso va con ella: no es ventaja medida del todo.
    #
    # `probable` hace de puerta en los dos sentidos: aquí sólo entran las
    # probables de ese tipo, y en los demás niveles NO entra ninguna — una
    # probable con cuota 2,05 no puede colarse en el nivel de la Capa 1 con
    # el sello de «acierta el 51,8 %», que es de otro canal.
    {'n': 0, 'cuota': 1.50, 'prob': 0.55, 'acierta': 0.680,
     'probable': 'ambos', 'margen_libre': True,
     'etiqueta': 'La más segura', 'dias': None,
     'nota': 'Visitante favorito para el modelo y para Pinnacle. Acierta 68 '
             'de cada 100 en 325 partidos medidos. No dobla: 100 se quedan '
             'en unos 160. Es probable, no es ventaja medida del todo.'},
    {'n': 1, 'cuota': 1.90, 'prob': 0.50, 'acierta': 0.518,
     'etiqueta': 'La más probable', 'dias': 0.404,
     'nota': 'La que más entra de todas las medidas: 52 de cada 100. Ojo, a '
             'esta cuota no dobla del todo — 100 se quedan en unos 190.'},
    {'n': 2, 'cuota': 2.00, 'prob': 0.45, 'acierta': 0.489,
     'etiqueta': 'La que dobla', 'dias': 0.556,
     'nota': 'Ésta sí dobla limpio. Entra algo menos que la más probable, '
             'pero cuando entra pagas el doble.'},
    # v297 — LA COMBINADA DEL MISMO PARTIDO, QUE EL USUARIO ENSEÑO.
    #
    # Su boleto: gana local 1,21 + más de 2,5 1,27 = 1,44. Dos patas del mismo
    # partido en un solo ticket. Va AQUI, tercera, y no antes: los niveles 1 y
    # 2 aciertan el 51,8 % y el 48,9 %, y ésta el 30,2 %. Paga mucho más y
    # entra bastante menos.
    #
    # Es el unico canal nuevo de toda la sesion que PASA LAS DOS PUERTAS:
    #
    #     elección (70 % antiguo)   +11,11 %   p5 +2,35 %
    #     juicio   (30 % reciente)  +22,74 %   p5 +8,61 %
    #
    # y le gana a jugar la pata sola (+14,60 % contra +7,46 %, mejora de
    # +7,14 pp con p5 +1,34, en el 97,8 % de los remuestreos). Ver la cabecera
    # de `combinada.py` para el porque: la casa la cobra multiplicando las dos
    # cuotas y las patas no son independientes.
    #
    # EL PISO ES EL DEL CANAL MEDIDO, NO UNO MAS ALTO «POR SEGURIDAD».
    #
    # La primera version pedia prob >= 0,45 pensando en el «lo mas probable»
    # que pidio el usuario. Pero lo medido —entra el 30,2 %— es el canal
    # ENTERO; recortarlo al 45 % seria ofrecer un subconjunto que no se ha
    # medido por separado y ademas tumbaria la mayoria de los dias. La lista
    # ya sale ordenada de mas a menos probable y el usuario elige, que es
    # exactamente lo que pidio en la v291.
    {'n': 3, 'cuota': 1.50, 'prob': 0.22, 'acierta': 0.302,
     'otros_mercados': True, 'margen_libre': True,
     # v297.1 — y SOLO combinadas. Sin esto un «Más de 2,5» suelto, que no
     # tiene medicion propia, entraba por aqui y salia con la etiqueta y los
     # numeros de un canal validado que no es el suyo.
     'solo_mercado': 'Combinada',
     'etiqueta': 'Combinada del partido', 'dias': None,
     'nota': 'Dos patas del mismo partido en un boleto, como la que me '
             'enseñaste. La casa las cobra multiplicando las cuotas, como si '
             'no tuvieran nada que ver, y sí lo tienen: si el local gana, '
             'suele haber goles. Medido en 17.420 partidos, entran juntas un '
             '18,4 % más de lo que ese precio supone. Ojo: paga más y entra '
             'menos que las de arriba.'},
    # v302 — LA PROBABLE DE SÓLO MERCADO, DETRÁS DE LAS QUE DOBLAN.
    #
    # El mismo visitante favorito, pero en ligas que el modelo no cubre: sólo
    # Pinnacle lo ve favorito. Medido aparte, más flojo:
    #
    #     n=859 · acierta 63,2 % · ELECCIÓN +2,25 % · JUICIO +7,54 %
    {'n': 3, 'cuota': 1.50, 'prob': 0.55, 'acierta': 0.632,
     'probable': 'mercado', 'margen_libre': True,
     'etiqueta': 'Segura, sólo mercado', 'dias': None,
     'nota': 'Visitante favorito según Pinnacle, en una liga que el modelo '
             'no cubre. Acierta 63 de cada 100 en 859 partidos medidos. No '
             'dobla, y es más floja que cuando el modelo también lo ve.'},
    {'n': 4, 'cuota': 2.00, 'prob': 0.40, 'acierta': 0.472,
     'etiqueta': 'Aceptable', 'dias': 0.676,
     'nota': 'Hoy no había ninguna de las dos mejores. Dobla igual, pero '
             'es de un grupo que a la larga acierta un par de puntos menos.'},
    {'n': 4, 'cuota': 2.00, 'prob': 0.30, 'acierta': 0.445,
     'etiqueta': 'Floja', 'dias': 0.800,
     'nota': 'Día pobre: es lo mejor que hay y no es gran cosa. Dobla, pero '
             'su grupo es el que menos acierta de los que doblan. Saltártela '
             'y esperar a mañana es una opción razonable.'},
    {'n': 5, 'cuota': 1.80, 'prob': 0.30, 'acierta': 0.464,
     'etiqueta': 'No llega a doblar', 'dias': 0.884,
     'nota': 'Ojo: con esta cuota ganar NO dobla tu dinero. Entra más a '
             'menudo, pero 100 se te quedan en unos 180. Para la escalera no '
             'sirve; para no quedarte quieto, sí.'},
    # v294 — EL FONDO DE ARMARIO, PARA NO DEJAR LA SECCION VACIA.
    #
    # El 2026-09-21 la seccion salio con «hoy no hay nada» mientras habia
    # siete picks de Capa 1 en pantalla: todos en ligas donde Pinnacle cobra
    # mas del 7 % de margen, asi que la puerta de la v276 los tumbo a todos.
    #
    # La puerta es correcta y no se toca: por encima del 7 % no hay medicion
    # que respalde nada (siete apuestas en cuatro años y medio). Lo que estaba
    # mal era la consecuencia: decir «nada» cuando hay algo que enseñar.
    #
    # Este nivel los deja pasar, ULTIMO y con el aviso por delante. El usuario
    # lo pidio dos veces: «no quiero que nunca me des apuesta». Que lo vea y
    # decida es distinto de que yo elija por el sin decirselo.
    {'n': 6, 'cuota': 1.80, 'prob': 0.30, 'acierta': None, 'dias': None,
     'margen_libre': True,
     'etiqueta': 'Fuera de lo medido',
     'nota': 'Esto es lo único que hay hoy, y va sin red: Pinnacle le cobra '
             'a esta liga un margen alto, así que su precio no sirve de '
             'referencia fiable. De apuestas así tenemos siete en cuatro años '
             'y medio — no puedo prometerte nada. Tú decides.'},
    # v296 — OTROS MERCADOS, NO SOLO EL GANADOR.
    #
    # El usuario: «que no sean sólo para el gane sino para cualquier otra
    # estadística». Tiene sentido y la via correcta NO es la que propuso.
    #
    # LO QUE SE MIDIO Y NO SIRVE: elegir por la tendencia estadistica. Sobre
    # 15.411 partidos CON CUOTA REAL de mas/menos 2,5, apostando cuando la
    # media de goles del par se aparta del precio:
    #
    #     se aparta > 5 pp    eleccion  -9,74 %   juicio  -9,46 %
    #     se aparta > 10 pp   eleccion -11,11 %   juicio  -9,85 %
    #     se aparta > 15 pp   eleccion -13,90 %   juicio -12,76 %
    #
    # Y con el modelo del repo en vez de la media, igual de mal (-8 a -10 %).
    # No es ruido: pierde lo MISMO en los dos tramos. El motivo esta a la
    # vista — la media SI predice (41 % de overs cuando el par promedia menos
    # de 2, 59 % cuando promedia mas de 3,2) pero el precio ya lo sabe, y el
    # margen medio de la pareja over/under es del 6,51 %. Informacion que el
    # mercado ya tiene no paga el peaje.
    #
    # LO QUE SI SIRVE es el mismo mecanismo del 1X2: que OTRA CASA pague por
    # encima del justo de Pinnacle. `barrido_capa1.barrer_goles` ya lo hace.
    # No tiene medicion propia todavia —esta acumulando— asi que entra ULTIMO
    # y marcado, igual que el nivel 6.
    #
    # `una_sola` esta puesto porque el usuario lo pidio explicito: «sólo
    # apuesta de una». Una linea por partido, nunca dos del mismo.
    {'n': 7, 'cuota': 1.50, 'prob': 0.30, 'acierta': None, 'dias': None,
     'margen_libre': True, 'otros_mercados': True, 'una_sola': True,
     'etiqueta': 'Otro mercado',
     'nota': 'No es al ganador: es goles. Sale por el mismo motivo que las '
             'demás —otra casa paga por encima del justo de Pinnacle— pero '
             'este mercado aún no tiene medición propia, está acumulando. '
             'Elegir por la media de goles se probó sobre 15.411 partidos y '
             'pierde un 10 %: el precio ya se sabe la media.'},
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
            # v302 — LAS PROBABLES VAN SÓLO POR SU NIVEL, Y SÓLO ELLAS.
            if nv.get('probable'):
                if p.get('probable') != nv['probable']:
                    continue
            elif p.get('probable'):
                continue
            margen = _num(p.get('margen_pin'))
            if margen is not None:
                if margen > MARGEN_PIN_TOPE:
                    continue          # ni con la bandera: ahi no hay señal
                if margen > MARGEN_PIN_MAXIMO and not nv.get('margen_libre'):
                    continue
            # v296 — QUE MERCADOS ENTRAN EN ESTE NIVEL.
            #
            # Todo lo medido de la Escalera es del 1X2, asi que los demas
            # mercados solo entran en los niveles que lo dicen (`otros
            # mercados`), y esos niveles van los ultimos. Al reves —que un
            # pick de goles se cuele en el nivel 1 y salga con el sello de
            # «acierta el 51,8 %»— seria prestarle a un canal sin medir el
            # aval de otro.
            #
            # `validado` es la bandera que el barrido pone a False en los
            # canales que aun acumulan, y por eso se lee junto con esto.
            #
            # Y AL REVES TAMBIEN, que costo un fallo en el test: el nivel 7
            # pide cuota 1,50, y sin esta segunda mitad un pick del GANADOR a
            # 1,60 se colaba por ahi. Esa banda se midio y es la unica que
            # pierde —ROI -0,61 % global, -11,98 % en el tramo de juicio con
            # p5 -26,76 %— asi que el 1,50 vale para goles y no para el 1X2.
            _mk = str(p.get('mercado') or '')
            _otro = _mk not in ('', '1X2', 'Ganador')
            if nv.get('otros_mercados'):
                if not _otro:
                    continue
                if nv.get('solo_mercado') and _mk != nv['solo_mercado']:
                    continue
            elif _otro:
                continue
            elif p.get('validado') is False and not nv.get('probable'):
                # las probables van marcadas `validado=False` A PROPÓSITO (no
                # pasan el p5) y tienen su nivel propio con su número
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
            #
            # v302 — salvo para las probables: el semáforo de la Capa 1 juzga
            # un ERROR DE CUOTA (cuánto paga por encima de Pinnacle) y una
            # probable no lo es — casi siempre paga por DEBAJO del justo y
            # aun así acierta lo medido. Pasarla por ese juez la tumbaría por
            # no ser lo que no pretende ser.
            if not p.get('probable'):
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


def todas(picks: List[Dict], tope: int = 8) -> List[Dict]:
    """TODAS las que sirven, de mejor a peor, cada una con su nivel.

    v291 — el usuario lo pidio: «que haya varias opciones, no sólo una, y yo
    escojo cuál». Antes solo salia la primera.

    Se recorren los niveles de mas exigente a menos y se van anadiendo sin
    repetir, asi que el orden de la lista ES el de calidad: las del nivel 1
    primero, luego las del 2, y asi. Las ROJAS no entran en ninguno.
    """
    fuera, vistos = [], set()
    try:
        for nv in NIVELES:
            for p in candidatas(picks, nv):
                # v296 — UN PARTIDO, UNA OPCION.
                #
                # El usuario lo pidio explicito: «sólo apuesta de una». Antes
                # la clave era (partido, apuesta), asi que el mismo partido
                # podia ocupar dos huecos —«Gana X» por un lado y «Más de 2,5»
                # por otro— y la lista parecia ofrecer mas donde habia menos.
                # Con el mercado de goles dentro eso pasaria a diario.
                # v297.1 — el partido, PERO POR MERCADO.
                #
                # Con la clave sólo del partido, la combinada de un encuentro
                # nunca aparecía: su pick del 1X2 ya había ocupado el hueco en
                # el nivel 1, que va antes. Y son dos productos distintos —el
                # ganador solo, o el ganador más los goles— entre los que el
                # usuario tiene que poder elegir.
                #
                # Lo que la clave sigue impidiendo es lo que motivó la regla:
                # el mismo partido con dos líneas de goles distintas, que
                # parecen dos oportunidades y son una.
                k = (str(p.get('partido')), str(p.get('mercado') or ''))
                if k in vistos:
                    continue
                vistos.add(k)
                q = dict(p)
                q['nivel_escalera'] = nv
                # v295 — EL VEREDICTO DEL SEMAFORO, ADJUNTO.
                #
                # La pantalla pinta un circulo de color por opcion leyendo
                # `semaforo.nivel`, y esta clave NUNCA se ponia: `_ICO.get(...)`
                # caia siempre en su valor por defecto y TODAS salian amarillas,
                # las buenas y las regulares igual. El selector prometia un
                # semaforo y enseñaba una fila de bombillas del mismo color.
                #
                # `candidatas` ya llama a `clasificar` para descartar las rojas,
                # asi que el veredicto existe; solo habia que guardarlo.
                if p.get('probable'):
                    # su propio color: ni verde de la Capa 1 ni rojo de ella
                    q['semaforo'] = {
                        'nivel': 'probable',
                        'etiqueta': nv.get('etiqueta') or 'Probable',
                        'porque': nv.get('nota') or ''}
                else:
                    try:
                        import semaforo_capa1 as _sem
                        q['semaforo'] = _sem.clasificar(p)
                    except Exception as _e:
                        logger.debug('[escalera] sin semaforo: %s', _e)
                fuera.append(q)
                if len(fuera) >= tope:
                    return fuera
    except Exception as e:
        logger.debug('[escalera] todas: %s', e)
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
        # v297.1 — `prob_escalera` la pone `candidatas`, asi que un pick que
        # llegue aqui por otro camino —una combinada recien armada, por
        # ejemplo— salia con «Entra 0 de cada 100 veces». Cero. Justo el
        # numero que hace que nadie la juegue, y falso.
        prob = float(pick.get('prob_escalera') or pick.get('prob') or 0)
        base = ('Si entra, tus **%.0f $** se convierten en **%.0f $**. '
                'Entra **%.0f de cada 100 veces**.'
                % (banco, banco * cuota, 100 * prob))
        nv = pick.get('nivel_escalera') or {}
        if nv.get('n', 1) > 1 and nv.get('nota'):
            base += '\n\n' + nv['nota']
        return base
    except (TypeError, ValueError):
        return ''
