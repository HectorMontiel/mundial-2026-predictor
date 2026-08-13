#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v125 — El clasificador: semáforo, tres secciones y material para parlays.

Qué es
------
La pieza que decide, para cada mercado, si es jugable en solitario, si sólo
sirve como pata, o si no debe enseñarse. Es el mismo motor para los dos niveles
de la aplicación (el día entero y un partido concreto), porque un pick que sale
como «Máximo Valor» en la vista diaria tiene que salir igual al abrir su
partido: si no, uno de los dos está mintiendo.

El criterio, y por qué es ÉSTE
------------------------------
El filtro NO es el EV del modelo. Está medido en −4,66 % a −6,52 % sobre 37.158
apuestas, y el EV declarado es anti-indicador del cierre (correlación −0,054).
Cuando una casa paga por encima de lo que el modelo cree justo, lo más probable
es que se equivoque el modelo.

El filtro es la VENTAJA DE PRECIO contra el consenso del mercado sin margen.
Eso no depende de que el modelo acierte: son dos precios del mismo suceso.

    p_consenso = devig(cuotas de las casas de referencia)
    c_justa    = 1 / p_consenso
    VENTAJA    = c_playdoit / c_justa − 1

EL UMBRAL NO ES CERO, Y ESO ES NUEVO
------------------------------------
`VENTAJA > 0` parecía el filtro obvio. Medido sobre `odds_snapshots.csv`
(1.414 selecciones con dos o más casas y resultado conocido), no lo es:

    ventaja  0 % – 5 %   n=623   ROI −11,48 %   p5 −20,18 %
    ventaja  5 % – 100 % n=791   ROI  +8,22 %   p5  −3,12 %

Comprobado con cuatro definiciones distintas del consenso (media y mediana, con
2 y con 3 casas mínimas): la dirección no cambia en ninguna. **Una ventaja
pequeña no es una ventaja: es ruido de redondeo, y apostarla pierde más que no
hacer nada.** De ahí `UMBRAL_VENTAJA = 0,05`.

LO QUE ESTO NO GARANTIZA
------------------------
Ni siquiera el tramo bueno tiene el percentil 5 del bootstrap por encima de
cero (−3,12 %). Con la regla de oro de este proyecto —nada se despliega sin p5
positivo en el tramo de juicio— eso significa que la Sección 1 es **la mejor
apuesta disponible, no una apuesta ganadora garantizada**. La interfaz lo dice
con esas palabras. Prometer un ROI positivo garantizado sería exactamente el
tipo de afirmación que este proyecto lleva veinte versiones desmontando.

El backtest de la liga
----------------------
Se pidió usarlo como puerta: `backtest > 53,5 %` AND ventaja. Medido:

    liga con backtest > 53,5 %   n=213   ROI +10,71 %   p5 −13,06 %
    liga con backtest ≤ 53,5 %   n=1107  ROI  −1,76 %   p5  −9,69 %

La estimación puntual favorece claramente al filtro, pero con 213 apuestas su
p5 es PEOR que el del grupo que supera. O sea: puede ser una buena regla y puede
ser una racha, y con estos datos no se distingue.

Por eso el backtest entra como **indicador de confianza visible** (`X/5`) y como
criterio de ORDEN, no como puerta que tira picks en silencio. Cuando haya
muestra para decidirlo, se decide; mientras tanto, el usuario ve la cifra y
elige. `exigir_backtest=True` activa la puerta para quien la quiera.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Ventaja mínima contra el consenso para considerar que hay algo. Ver el
# encabezado: por debajo de esto, el ROI medido es negativo y grande.
UMBRAL_VENTAJA = 0.05

# Por debajo de esto, la casa paga claramente peor que el mercado y el pick se
# retira de las vistas principales. No es cero: entre −2 % y 0 % la diferencia
# es ruido entre casas, y pintarlo de rojo empujaría a abrir cuentas por nada.
UMBRAL_ROJO = -0.02

# Backtest de liga a partir del cual se considera «liga fiable». Sale de la
# propuesta del usuario y de la medición de arriba; se usa para ORDENAR y para
# el indicador de confianza, no para descartar.
BACKTEST_FIABLE = 0.535

# POR ENCIMA DE ESTO, LA VENTAJA NO ES UNA VENTAJA: ES UN ERROR DE DATOS.
#
# Dos casas de verdad no pueden diferir un 40 % en el precio del mismo suceso.
# El propio proyecto tiene medida la dispersión real entre casas y su peor caso
# ronda el 24 %. Cuando aparece más, lo que hay es un mercado que no es el
# mismo — casi siempre porque el emparejador cogió otro partido.
#
# Caso real que obligó a poner esta red (2026-08-11): pidiendo «Athletico-PR vs
# Bragantino», Playdoit devolvía el tablero de «Atlético-MG vs Bragantino» —
# otro club y otra competición— con similitud 1,0, porque el normalizador se
# come el sufijo de estado. La Sección 1 anunciaba «Empate @ 16,00 · +392 %
# sobre el mercado». La causa está corregida en `cuotas_multi.marca_estado`,
# pero esta red es independiente y atrapa el fallo venga de donde venga.
VENTAJA_IMPOSIBLE = 0.30

# ---------------------------------------------------------------------------
# LA EXCEPCIÓN DEL TENIS (v126)
#
# Es la ÚNICA regla de todo el proyecto que entra en la Sección 1 sin
# necesitar ventaja de precio, y entra porque está medida sobre el ledger real
# (`_v126_roi_tenis_mlb.py`, 46.151 partidos de tenis con probabilidad,
# resultado y cuota):
#
#     banda            n        acierto   ROI       p5
#     prob >= 90 %     1.793    91,69 %   +5,76 %   +0,18 %   <- pasa el listón
#     prob 80-90 %     4.906    84,51 %   −1,96 %   −3,01 %
#     tenis global    46.151    65,88 %   −4,92 %   −5,53 %
#
# TRES COSAS QUE NO SE PUEDEN OMITIR AL ENSEÑARLA:
#
# 1. El p5 es +0,18 %. Es el aprobado más raspado posible: la regla se sostiene
#    por los pelos y una racha mala la pondría en negativo. Se despliega porque
#    la regla del proyecto dice «p5 positivo», no porque sea una mina.
# 2. La cuota media de esa banda es ~1,15 (de 91,69 % de acierto y +5,76 % de
#    ROI). Son apuestas de cuota baja: hace falta volumen, y un solo precio
#    malo se come varias apuestas buenas.
# 3. El tenis GLOBAL pierde −4,92 %, casi lo mismo que el fútbol. Lo que
#    funciona es esta banda, no el deporte.
REGLA_TENIS_PROB = 0.90
REGLA_TENIS_MEDICION = {
    'n': 1793, 'acierto': 0.9169, 'roi': 0.0576, 'p5': 0.0018,
    'cuota_media': 1.15,
}

# Tamaño mínimo de banda de calibración para que su acierto sea publicable.
N_BANDA_MINIMO = 500


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def consenso_sin_margen(cuotas: Dict[str, float]) -> Optional[Dict[str, float]]:
    """
    Precio JUSTO de cada lado, quitado el margen de la casa.

    `cuotas` es `{lado: cuota}` de un mismo libro (o el mejor de varios). Se
    normaliza para que las probabilidades implícitas sumen 1, que es el devig
    proporcional. Es el método más simple y el que menos supone; el proyecto usa
    el mismo criterio en el resto del código.

    Devuelve `{lado: cuota_justa}` o None si el libro está incompleto — que es
    un resultado correcto: con un lado sin precio no hay libro que normalizar.
    """
    vals = {k: _f(v) for k, v in (cuotas or {}).items()}
    vals = {k: v for k, v in vals.items() if v}
    if len(vals) < 2:
        return None
    suma = sum(1.0 / v for v in vals.values())
    if suma <= 0:
        return None
    # p_i = 1/c_i · p_i' = p_i / Σp · cuota justa = 1/p_i' = c_i · Σp
    return {k: round(v * suma, 6) for k, v in vals.items()}


def ventaja_de_precio(cuota_casa, cuota_justa) -> Optional[float]:
    """
    Cuánto paga tu casa por encima del precio justo del mercado.

    0,05 = tu casa paga un 5 % más de lo que vale. Es la única cifra del
    clasificador que no depende de que el modelo acierte.
    """
    c, j = _f(cuota_casa), _f(cuota_justa)
    if not c or not j:
        return None
    return round(c / j - 1.0, 4)


def confianza_liga(backtest, techo_mercado=None) -> Dict:
    """
    La confianza en una liga, en estrellas de 1 a 5, con su porqué.

    Se compara con el TECHO del mercado en esa liga cuando se conoce, que es lo
    honesto: acertar el 45 % en una liga donde la mejor casa del mundo acierta
    el 45,9 % no es un mal modelo, es una liga impredecible. Sin ese contexto,
    un 45 % parece un desastre y un 54 % parece bueno, y ninguna de las dos
    lecturas es correcta.
    """
    b = None
    try:
        b = float(backtest) if backtest is not None else None
    except (TypeError, ValueError):
        b = None
    if b is None:
        return {'estrellas': 0, 'backtest': None,
                'texto': 'sin backtest publicado para esta liga'}
    t = None
    try:
        t = float(techo_mercado) if techo_mercado else None
    except (TypeError, ValueError):
        t = None
    if t and t > 0:
        # cuánto del techo alcanzable se consigue
        rel = b / t
        estrellas = (5 if rel >= 1.02 else 4 if rel >= 0.99 else
                     3 if rel >= 0.96 else 2 if rel >= 0.92 else 1)
        texto = (f"acierta {b*100:.1f} % y el techo del mercado en esta liga "
                 f"es {t*100:.1f} %")
    else:
        estrellas = (5 if b >= 0.545 else 4 if b >= BACKTEST_FIABLE else
                     3 if b >= 0.51 else 2 if b >= 0.48 else 1)
        texto = f"acierta {b*100:.1f} % en validación"
    return {'estrellas': int(estrellas), 'backtest': round(b, 4),
            'techo': round(t, 4) if t else None, 'texto': texto,
            'fiable': bool(b >= BACKTEST_FIABLE)}


def semaforo(ventaja, n_casas: int = 1, backtest=None,
             ev_sospechoso: bool = False, ev_no_fiable: bool = False,
             n_banda: Optional[int] = None,
             exigir_backtest: bool = False,
             deporte: str = '', prob=None, hay_precio: bool = True) -> Dict:
    """
    Verde, amarillo o rojo, con el motivo en texto llano.

    El orden de las comprobaciones importa: primero lo que descalifica (rojo),
    después lo que obliga a mirar (amarillo), y sólo lo que sobrevive a las dos
    es verde. Al revés, un pick con un aviso grave podría salir verde por
    cumplir el criterio de precio.
    """
    v = None
    try:
        v = float(ventaja) if ventaja is not None else None
    except (TypeError, ValueError):
        v = None

    # --- ERROR DE DATOS: antes que cualquier otra cosa ---------------------
    # Va la primera porque una ventaja imposible NO es una ventaja grande: es
    # otro partido. Si se comprobara después, un mercado desemparejado saldría
    # verde por cumplir de sobra el criterio de precio.
    if v is not None and v > VENTAJA_IMPOSIBLE:
        return {'luz': 'rojo', 'seccion': 0, 'error_datos': True,
                'motivo': f'ventaja de {v*100:+.0f} %, que entre dos casas '
                          f'reales es imposible: casi seguro que los precios '
                          f'son de partidos distintos'}

    # --- LA EXCEPCIÓN DEL TENIS (ver REGLA_TENIS_MEDICION) -----------------
    #
    # Va después del guardia de datos y antes que todo lo demás: es la única
    # regla con p5 positivo medido, así que no depende del consenso. Pero SÍ
    # exige precio: sin cuota publicada no hay nada que apostar, y la medición
    # se hizo sobre cuotas reales.
    if str(deporte or '').lower().startswith('tenis') and prob is not None:
        try:
            p = float(prob)
        except (TypeError, ValueError):
            p = None
        if p is not None and p >= REGLA_TENIS_PROB:
            if not hay_precio:
                return {'luz': 'amarillo', 'seccion': 2,
                        'motivo': 'supera el 90 % de probabilidad, pero '
                                  'ninguna casa lo cotiza todavía'}
            m = REGLA_TENIS_MEDICION
            return {'luz': 'verde', 'seccion': 1, 'regla': 'tenis_90',
                    'motivo': f"tenis con {p*100:.0f} % de probabilidad: la "
                              f"banda ≥ 90 % da un ROI de "
                              f"{m['roi']*100:+.2f} % con p5 "
                              f"{m['p5']*100:+.2f} % sobre {m['n']:,} partidos"
                              .replace(',', '.')}

    # --- ROJO: la casa paga claramente peor que el mercado -----------------
    if v is not None and v < UMBRAL_ROJO:
        return {'luz': 'rojo', 'seccion': 0,
                'motivo': f'tu casa paga un {v*100:.1f} % menos que el precio '
                          f'justo del mercado'}

    # --- AMARILLO: hay ventaja pero algo obliga a mirar --------------------
    if ev_sospechoso:
        return {'luz': 'amarillo', 'seccion': 2,
                'motivo': 'EV demasiado alto con una sola casa: casi siempre es '
                          'el modelo equivocándose, no valor'}
    if ev_no_fiable:
        return {'luz': 'amarillo', 'seccion': 2,
                'motivo': 'el EV de este mercado no es fiable (el modelo da la '
                          'misma probabilidad a las dos mitades)'}
    if v is None:
        return {'luz': 'amarillo', 'seccion': 2,
                'motivo': 'sin precio de otra casa con el que comparar: no se '
                          'puede saber si tu casa paga bien'}
    if n_casas < 2:
        return {'luz': 'amarillo', 'seccion': 2,
                'motivo': 'una sola casa cotiza este mercado, así que no hay '
                          'consenso con el que medir la ventaja'}
    if n_banda is not None and n_banda < N_BANDA_MINIMO:
        return {'luz': 'amarillo', 'seccion': 2,
                'motivo': f'la banda de probabilidad tiene {n_banda} casos '
                          f'medidos: por debajo de {N_BANDA_MINIMO} no dice nada'}
    if v < UMBRAL_VENTAJA:
        return {'luz': 'amarillo', 'seccion': 2,
                'motivo': f'la ventaja es de {v*100:+.1f} % y por debajo del '
                          f'{UMBRAL_VENTAJA*100:.0f} % está medida en negativo '
                          f'(ROI −11,5 % entre 0 % y 5 %)'}
    if exigir_backtest:
        c = confianza_liga(backtest)
        if not c.get('fiable'):
            return {'luz': 'amarillo', 'seccion': 2,
                    'motivo': f"la liga no llega al {BACKTEST_FIABLE*100:.1f} % "
                              f"de backtest ({c['texto']})"}

    # --- VERDE -------------------------------------------------------------
    return {'luz': 'verde', 'seccion': 1,
            'motivo': f'tu casa paga un {v*100:+.1f} % por encima del precio '
                      f'justo del mercado, comparando {n_casas} casas'}


def clasificar(mercados: List[Dict], backtest=None, techo_mercado=None,
               exigir_backtest: bool = False, deporte: str = '') -> Dict:
    """
    Reparte los mercados de un partido en las tres secciones.

    `mercados` son las filas que devuelve `cuotas_tablon` (con `cuota_casa`,
    `casa`, `n_casas`, `ev`, y opcionalmente `cuota_mercado`/`dif_vs_mercado`
    de `comparar_con_el_mercado`).

    Devuelve:
        seccion1  jugables en solitario (verde), ordenados por ventaja
        seccion2  sólo como pata, con su motivo (amarillo)
        descartados  rojo, para el desplegable de «por qué no está»
        confianza    el indicador de liga, común a todo el partido
    """
    conf = confianza_liga(backtest, techo_mercado)
    s1, s2, rojo = [], [], []
    for m in (mercados or []):
        # LA VENTAJA SE MIDE CONTRA EL CONSENSO, NO CONTRA EL MEJOR PRECIO.
        #
        # Es la referencia con la que se calibró el umbral del 5 %: la medición
        # comparó el mejor precio contra la MEDIA del resto de casas. Usar aquí
        # `dif_vs_mercado` —que compara contra el MEJOR del resto— sería
        # aplicar un umbral calibrado sobre una magnitud a otra distinta y
        # mucho más exigente, y la Sección 1 quedaría vacía por construcción.
        #
        # `dif_vs_mercado` se conserva en la fila porque es lo que hay que
        # ENSEÑAR («cuánto te dejas frente a la mejor casa»), pero no es lo que
        # decide.
        v = m.get('dif_vs_consenso')
        if v is None:
            v = m.get('dif_vs_mercado')
        if v is None and m.get('ventaja_line_shopping') is not None \
                and (m.get('n_casas') or 1) >= 2:
            v = m['ventaja_line_shopping']
        # CUÁNTAS CASAS RESPALDAN LA COMPARACIÓN, que no es lo mismo que
        # cuántas cotizan la fila.
        #
        # En el tablero de Playdoit `n_casas` vale SIEMPRE 1 —es una sola
        # casa, por definición— así que usarlo aquí mandaba todo a la Sección 2
        # con «una sola casa cotiza este mercado» y dejaba la Sección 1 vacía
        # por construcción. Lo que respalda la comparación es el número de
        # casas del CONSENSO contra el que se mide.
        n_ref = int(m.get('n_casas_mercado') or m.get('n_casas') or 1)
        luz = semaforo(v, n_ref, backtest,
                       bool(m.get('ev_sospechoso')),
                       bool(m.get('ev_no_fiable')),
                       m.get('n_banda'), exigir_backtest,
                       deporte=deporte, prob=m.get('prob'),
                       hay_precio=bool(m.get('cuota_casa')))
        fila = {**m, 'ventaja': v, **luz, 'confianza': conf}
        (s1 if luz['seccion'] == 1 else
         s2 if luz['seccion'] == 2 else rojo).append(fila)
    s1.sort(key=lambda r: -(r.get('ventaja') or 0))
    # la Sección 2 se ordena por PROBABILIDAD, que es para lo que sirve
    s2.sort(key=lambda r: -(r.get('prob') or 0))
    return {'seccion1': s1, 'seccion2': s2, 'descartados': rojo,
            'confianza': conf}


# ===========================================================================
# v128 — LAS TRES SECCIONES, APLICADAS AL DÍA ENTERO
#
# Hasta aquí el clasificador sólo vivía en el Nivel 2 (un partido concreto),
# porque es allí donde hay tablero de Playdoit y por tanto `dif_vs_consenso`
# fila a fila. El Nivel 1 —«Apuestas del Día»— seguía repartiendo sus picks por
# el EV del modelo, que es exactamente el criterio que el §0 de la bitácora mide
# en −4,66 % a −6,52 %. O sea que las dos pantallas decían cosas distintas del
# mismo partido, que es justo lo que el diseño de dos niveles prohíbe.
#
# El barrido del día no puede pagar un tablero por partido (mira cientos), así
# que no tiene `dif_vs_consenso`. Lo que SÍ tiene son canales enteros ya
# medidos, y sólo dos de ellos cruzan el listón del proyecto —p5 del bootstrap
# positivo en el tramo que no se usó para elegir—:
#
#   1. `valor_vs_sharp` AL LADO LOCAL, en fútbol. Comprar al mejor precio del
#      tablón cuando el devig de Pinnacle da ≥ 30 % y el EV contra ese precio
#      justo pasa del 1 %.
#   2. Tenis con probabilidad ≥ 90 % y precio publicado.
#
# El resto de lo que hoy sale en «Máximo Valor» —los picks por EV del modelo,
# la MLB, la NBA, el tenis por debajo del 90 %— no está descartado ni oculto:
# baja a la Sección 2 con el motivo medido escrito al lado. La diferencia entre
# «no te lo enseño» y «te lo enseño diciendo lo que rinde» es toda la tesis de
# este proyecto.
# ===========================================================================

# Canal de line shopping al lado LOCAL (`_v90_line_shopping_por_lado.json`,
# reproducido el 2026-08-12 sobre `pick_ledger_total.csv`). Es la única
# configuración del canal que da p5 > 0 en LAS DOS mitades del ledger:
#
#     lado        pliegues 0-2 (elige)      pliegues 3-4 (juzga)
#     local       n=1817  +5,09 %  p5 +1,09 %   n=353  +11,49 %  p5 +1,73 %
#     empate      n= 546 +12,21 %  p5 +1,08 %   n= 56   −7,09 %  p5 −38,91 %
#     visitante   n=1168 +10,21 %  p5 +4,28 %   n=234   +7,92 %  p5  −5,10 %
#
# El empate y el visitante lucen bien en la mitad con la que se eligió y se
# hunden en la otra: es el retrato exacto de un hallazgo que no era real. Por
# eso van a la Sección 2 aunque salgan del mismo canal.
CANAL_LOCAL_MEDICION = {
    'n_elige': 1817, 'roi_elige': 0.0509, 'p5_elige': 0.0109,
    'n_juicio': 353, 'roi_juicio': 0.1149, 'p5_juicio': 0.0173,
}
CANAL_NO_LOCAL_MEDICION = {
    'empate': {'n_juicio': 56, 'roi_juicio': -0.0709, 'p5_juicio': -0.3891},
    'visitante': {'n_juicio': 234, 'roi_juicio': 0.0792, 'p5_juicio': -0.0510},
}


def _prob(x) -> Optional[float]:
    """Probabilidad utilizable. `_f` no sirve: exige > 1 y una prob nunca lo es."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if 0.0 < v <= 1.0 else None


def canal_del_pick(p: Dict) -> Dict:
    """
    A qué sección va un pick del barrido del día, y por qué.

    Devuelve `{'seccion': 1|2, 'canal': str, 'motivo': str, 'medicion': dict}`.
    El `motivo` está escrito para salir tal cual en pantalla: es la respuesta a
    «¿por qué esto sí y aquello no?», y sin ella la separación en dos listas
    sería una opinión más.
    """
    dep = str(p.get('deporte') or 'Fútbol')
    prob = _prob(p.get('prob'))
    cuota = _f(p.get('cuota'))

    # --- 1. LA EXCEPCIÓN DEL TENIS ----------------------------------------
    #
    # Va la primera por el mismo motivo que en `semaforo`: es la única regla
    # con p5 positivo que no necesita consenso. Y aquí importa una cosa más
    # que en el Nivel 2: la cuota media de esta banda es ~1,15, o sea que el
    # mínimo de 1,50 del barrido la tira entera a la Capa 2. Ésta es la
    # puerta por la que la única regla rentable del proyecto vuelve a
    # aparecer en la pantalla del día.
    if dep.lower().startswith('tenis') and prob is not None \
            and prob >= REGLA_TENIS_PROB:
        m = REGLA_TENIS_MEDICION
        if not cuota:
            return {'seccion': 2, 'canal': 'tenis_90_sin_precio',
                    'motivo': 'supera el 90 % de probabilidad, pero ninguna '
                              'casa lo cotiza todavía: sin precio no hay '
                              'apuesta que medir'}
        return {'seccion': 1, 'canal': 'tenis_90', 'medicion': m,
                'motivo': f"tenis con {prob*100:.0f} % de probabilidad: la "
                          f"banda ≥ 90 % rinde {m['roi']*100:+.2f} % con p5 "
                          f"{m['p5']*100:+.2f} % sobre {m['n']:,} partidos"
                          .replace(',', '.')
                          + f". Cuota media de la banda ~{m['cuota_media']:.2f}: "
                            f"se gana por volumen, no por golpe."}

    # --- 2. EL CANAL DE PRECIO --------------------------------------------
    if p.get('valor_mercado'):
        lado = str(p.get('lado') or '')
        if dep == 'Fútbol' and lado == 'home':
            c = CANAL_LOCAL_MEDICION
            return {'seccion': 1, 'canal': 'precio_local', 'medicion': c,
                    'motivo': f"una casa blanda paga por encima del precio "
                              f"justo de Pinnacle, y es el LADO LOCAL: el "
                              f"único del canal con p5 positivo en las dos "
                              f"mitades del ledger "
                              f"({c['roi_juicio']*100:+.2f} % con p5 "
                              f"{c['p5_juicio']*100:+.2f} % sobre "
                              f"{c['n_juicio']} apuestas de juicio)"}
        if dep == 'Fútbol':
            nom = 'empate' if lado == 'draw' else 'visitante'
            d = CANAL_NO_LOCAL_MEDICION.get(nom) or {}
            return {'seccion': 2, 'canal': 'precio_no_local',
                    'motivo': f"mismo canal de precio, pero al {nom}: en el "
                              f"tramo de juicio da p5 "
                              f"{(d.get('p5_juicio') or 0)*100:+.1f} % con "
                              f"{d.get('n_juicio', 0)} apuestas. Luce bien en "
                              f"la mitad con la que se eligió y se hunde en la "
                              f"otra, que es el retrato de un hallazgo que no "
                              f"era real"}
        return {'seccion': 2, 'canal': 'precio_sin_medir',
                'motivo': f"canal de precio en {dep}, que es el mismo método "
                          f"pero SIN medir: el desglose por lado se hizo sólo "
                          f"sobre fútbol. Sin su propio p5 no puede subir"}

    # --- 3. TODO LO DEMÁS: EL EV DEL MODELO --------------------------------
    return {'seccion': 2, 'canal': 'ev_del_modelo',
            'motivo': 'seleccionado por el valor esperado del modelo, que está '
                      'medido en −4,66 % a −6,52 % de ROI sobre 37.158 '
                      'apuestas y es anti-indicador del cierre. Como pata o '
                      'como lectura, no como apuesta suelta'}


def secciones_del_dia(capa1: List[Dict], capa2: Optional[List[Dict]] = None,
                      max_seccion2: int = 40) -> Dict:
    """
    Reparte los picks del barrido del día en Sección 1 y Sección 2.

    `capa2` entra porque ahí es donde acaban los picks de tenis de la banda
    ≥ 90 %: su cuota media (~1,15) está por debajo del mínimo de 1,50 del
    barrido, así que el filtro de élite los aparta antes de que nadie los mire.

    El orden de la Sección 1 no es por EV ni por probabilidad: es por la
    FUERZA DE LA MEDICIÓN que respalda cada canal. El precio al lado local
    tiene p5 +1,73 % en juicio; el tenis, +0,18 %. Poner primero lo mejor
    medido es la única prioridad que este proyecto puede defender.
    """
    orden_canal = {'precio_local': 0, 'tenis_90': 1}
    s1, s2, vistos = [], [], set()
    for p in list(capa1 or []) + list(capa2 or []):
        if not isinstance(p, dict):
            continue
        clave = (p.get('deporte'), p.get('partido'), p.get('mercado'),
                 p.get('apuesta'))
        if clave in vistos:
            continue
        vistos.add(clave)
        c = canal_del_pick(p)
        fila = {**p, **c}
        (s1 if c['seccion'] == 1 else s2).append(fila)
    s1.sort(key=lambda r: (orden_canal.get(r.get('canal'), 9),
                           -(r.get('prob') or 0), -(r.get('ev') or 0)))
    s2.sort(key=lambda r: -(r.get('prob') or 0))
    return {'seccion1': s1, 'seccion2': s2[:max(0, int(max_seccion2))],
            'n_seccion2': len(s2)}


def ids_para_parlay(clasificacion: Dict, prob_minima_relleno: float = 0.85,
                    max_relleno: int = 1) -> List[str]:
    """
    Qué mercados pueden entrar en una combinada, y en qué orden.

    LA REGLA: se parte SIEMPRE de la Sección 1. La aritmética no deja otra
    opción — `EV_parlay = Π(1 + EV_i) − 1`, así que juntar patas de EV negativo
    multiplica la pérdida:

        3 patas de −4,76 %  →  −13,62 %
        3 patas de +4,50 %  →  +14,12 %

    Se admite como mucho `max_relleno` patas de la Sección 2, y sólo si superan
    `prob_minima_relleno`, que es el caso que el usuario planteó: inflar la
    cuota sin hundir la probabilidad conjunta. Cada una de ellas empeora el EV
    del boleto, así que van contadas y avisadas, no mezcladas sin más.
    """
    ids = [m['id'] for m in clasificacion.get('seccion1', []) if m.get('id')]
    relleno = [m['id'] for m in clasificacion.get('seccion2', [])
               if m.get('id') and (m.get('prob') or 0) >= prob_minima_relleno]
    return ids + relleno[:max(0, int(max_relleno))]
