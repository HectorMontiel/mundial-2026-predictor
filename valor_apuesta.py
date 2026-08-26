#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v171 — LA MEJOR RELACIÓN PROBABILIDAD/CUOTA, LÍNEA A LÍNEA.

El cambio, con las palabras del usuario
---------------------------------------
«No quiero la apuesta más segura, quiero la de mejor relación entre
probabilidad y cuota.» La v170 elegía por probabilidad absoluta y acabó
recomendando doble oportunidad al 79 % con cuota 1,10 en el 93 % de los
partidos. Desde la v171 se elige por

    Score = probabilidad ajustada × cuota de Playdoit

que es el valor esperado más uno. Un Score de 1,20 significa que, si la
probabilidad es correcta, cada peso apostado devuelve 1,20.

Y SE EXPLORAN TODAS LAS LÍNEAS, QUE ES LA MITAD DEL ASUNTO
-----------------------------------------------------------
El ejemplo que se dio es exacto: «Más de 2,5» al 80 % con cuota 1,40 da Score
1,12; «Más de 3,5» al 67 % con cuota 1,80 da 1,21. La segunda es mejor apuesta
y hasta ahora la aplicación ni la miraba, porque sólo calculaba la línea más
cercana a la media. Playdoit publica de diez a veinte líneas por mercado y el
modelo sabe dar probabilidad a todas: la binomial negativa de córners,
tarjetas y remates acepta cualquier línea, y la matriz de marcador también.

LO QUE ESTE MÓDULO NO PROMETE
-----------------------------
Que gane dinero. Elegir por EV sobre la probabilidad del modelo es un canal
que este proyecto tiene MEDIDO como anti-indicador cuando la probabilidad va
cruda (−4,66 % a −6,52 % sobre 37.158 apuestas). Aquí no va cruda: va encogida
hacia el precio de la casa (v166) y recortada (v166), y con ESA probabilidad la
política de precio fue la que mejor ROI dio de las tres medidas en la v169
(−5,00 % contra −6,17 % de la v170 y −8,42 % de la v164). Sigue siendo
negativo. Lo que este módulo hace es elegir mejor dentro de lo que hay, no
convertir en positivo lo que no lo es.
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger('valor_apuesta')

# Los tres números de la regla, tal y como se pidieron.
PROB_MINIMA = 0.60          # por debajo de esto no se recomienda...
SCORE_EXCEPCION = 1.15      # ...salvo que el valor sea muy alto
# ...pero NUNCA por debajo de aqui, pase lo que pase con el Score.
#
# La excepcion del 1,15 se escribio como valvula para una apuesta muy bien
# pagada, no como puerta para un volado. Sin este suelo, la primera prueba
# contra un tablero real eligio «Real Sociedad o empate» al 38 % con cuota
# 3,10 (Score 1,178): exactamente la apuesta que el encargo dice no querer.
#
# Y la excepcion exige ademas CONTRASTE con la casa. Un EV alto calculado
# sobre una probabilidad del modelo que nadie ha contradicho es el canal que
# este proyecto tiene medido como anti-indicador (-4,66 % a -6,52 % sobre
# 37.158 apuestas). Con contraste, es otra cosa: es discrepancia de precio.
PROB_SUELO_DURO = 0.50
# v175 — EL VERDE EXIGE LAS DOS COSAS: PROBABILIDAD **Y** PRECIO.
#
# El encargo lo fija literal: «Verde para la principal (Score > 0,97 y
# Prob > 60 %), Ambar para secundarias buenas». Es la QUINTA acepcion del
# verde en siete versiones —v168 ventaja de precio, v170 estable y
# >=60 %, v171 Score > 1,10, v173/v174 probabilidad >= 60 %— y conviene
# que sea la ultima. Pero es la unica que no promete una sola cosa: un
# 70 % a cuota 1,05 (Score 0,735) ya no puede ir en verde, y era justo el
# tipo de apuesta que llenaba la pantalla.
#
# POR QUE 0,97 Y NO 1,00. Un Score de 1,00 es el equilibrio TEORICO, y
# Playdoit cobra margen: en un mercado de dos vias con 5 % de vig, la
# apuesta perfectamente valorada da Score 0,95. Exigir 1,00 seria exigir
# que la casa se equivoque — un canal que este proyecto tiene medido
# (+11,49 % comprando al mejor precio) pero que aparece en un partido de
# cada muchos. 0,97 marca «bien pagada dentro de lo que hay», que es lo
# que el verde tiene que decir.
SCORE_VERDE = 0.97          # 🟢 valor
SCORE_AMBAR = 0.90          # 🟡 aceptable
CUOTA_MINIMA_DOBLE = 1.30   # la doble oportunidad no entra por debajo de esto
# v173 — «LA DE MAYOR PROBABILIDAD QUE TENGA UNA CUOTA DECENTE».
#
# Elegir por probabilidad a secas, con la escalera entera de goles delante,
# saca «Menos de 6,5 al 100 %» con cuota 1,01. Es lo mas probable del partido y
# no es una apuesta: nadie juega un 1,01. El propio encargo pone el limite —
# «la de mayor probabilidad QUE TENGA UNA CUOTA DECENTE»— y estos son los dos
# cortes que lo hacen operativo. Medido sobre los 113 partidos del dia, sin
# ellos 53 recomendaciones eran lineas de goles absurdas.
CUOTA_DECENTE = 1.20        # por debajo de esto no es una apuesta, es un tramite
PROB_MAXIMA_RECO = 0.90     # y por encima de esto tampoco, aunque no haya cuota
# v172/v173 — LA REGLA ANTI-TRAMPA SE RETIRA, Y SE DEJA EL RASTRO.
#
# La v172 prohibia recomendar una probabilidad < 20 % con cuota > 2,50
# («la trampa de la cuota inflada»). La v173 la quita a peticion del
# usuario: quiere poder ver esas apuestas de loteria si el H2H o la
# racha las respaldan.
#
# Hoy no hace falta para lo mismo que antes: desde la v173 la
# recomendacion se elige por PROBABILIDAD, y una apuesta del 15 % no
# puede ganar esa comparacion. La regla protegia contra la seleccion
# por Score, que ya no es la que manda.
PROB_TRAMPA = 0.20
CUOTA_TRAMPA = 2.50

_RE_MAS = re.compile(r'^m[aá]s de ', re.I)


def semaforo(score=None, prob=None) -> str:
    """
    v175 — EL COLOR PIDE PROBABILIDAD **Y** PRECIO, Y YA NO BLOQUEA NADA.

    Verde: >= 60 % de probabilidad Y Score >= 0,97 — o sea, probable y
    bien pagada. Ambar: >= 50 %, o buen Score sin llegar al 60 %. Gris:
    lo demas.

    LO QUE CAMBIA DE VERDAD NO ES EL UMBRAL, ES LO QUE SIGNIFICA EL GRIS.
    Hasta la v174 un mercado mal calibrado en esa liga salia con «🔒 No
    recomendado» y sin propuesta. Desde la v175 el gris quiere decir alta
    incertidumbre, no prohibido: el mercado enseña igual su mejor lado, y
    el color solo dice si es candidato a apuesta principal o a secundaria.

    Sin `score` —una fila sin cuota— manda la probabilidad sola, que es lo
    que hacia la v173. No es un caso de la tarjeta: desde la v174 toda
    candidata tiene precio.
    """
    if prob is None:
        return '\u26aa'
    if score is None:
        return ('\U0001f7e2' if prob >= PROB_MINIMA
                else '\U0001f7e1' if prob >= PROB_SUELO_DURO
                else '\u26aa')
    if prob >= PROB_MINIMA and score >= SCORE_VERDE:
        return '\U0001f7e2'
    # el ambar NO lo levanta el Score solo: un 30 % a cuota 4,00 da
    # Score 1,20 y sigue siendo un volado. Es la leccion de la v172
    # y el unico sitio del semaforo donde el precio no vota.
    if prob >= PROB_SUELO_DURO:
        return '\U0001f7e1'
    return '\u26aa'


def _fila(mercado: str, etiqueta: str, apuesta: str, prob: float,
          cuota: Optional[float], implicita: Optional[float],
          bloque: str, linea=None, extra: Optional[Dict] = None) -> Dict:
    """Una línea jugable, con su Score ya calculado."""
    score = None
    if cuota and cuota > 1:
        score = float(cuota) * float(prob)
    fila = {'mercado': mercado, 'etiqueta': etiqueta, 'apuesta': apuesta,
            'prob': round(float(prob), 4),
            'cuota': round(float(cuota), 3) if cuota else None,
            'score': None if score is None else round(score, 4),
            'implicita': implicita, 'bloque': bloque, 'linea': linea,
            'semaforo': semaforo(score, prob)}
    if extra:
        fila.update(extra)
    return fila


def contexto_de(pick: Dict) -> Dict:
    """El contexto del partido, cacheado en el propio pick."""
    if '_contexto' in pick:
        return pick['_contexto'] or {}
    ctx = {}
    try:
        import contexto_partido as cx
        import modo_modelo as mm
        h, a = mm._equipos(pick)
        if h and a and pick.get('clave_liga'):
            ctx = cx.de_partido(pick['clave_liga'], h, a)
    except Exception as e:
        logger.debug('[valor] contexto: %s', e)
    pick['_contexto'] = ctx
    return ctx


def _factor_sin_precio(pick: Dict, apuesta: str,
                       implicita: Optional[float]) -> float:
    """
    El multiplicador del H2H, y SOLO donde no hay precio con el que contrastar.

    Donde la casa pone precio, ella ya sabe el H2H —a AmaZulu le da un 6,43 %
    precisamente porque pierde siempre— y multiplicar encima seria contar la
    misma informacion dos veces y romper la calibracion que esta aplicacion
    lleva seis versiones arreglando.

    Donde NO hay precio, el modelo va solo y el historial si aporta.
    """
    if implicita is not None:
        return 1.0
    ctx = contexto_de(pick)
    if not ctx:
        return 1.0
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
    except Exception:
        return 1.0
    etq = str(apuesta or '')
    if h and h in etq and (not a or a not in etq):
        return float(ctx.get('factor_home') or 1.0)
    if a and a in etq and (not h or h not in etq):
        return float(ctx.get('factor_away') or 1.0)
    return 1.0


def _ajusta(pick: Dict, apuesta: str, prob: float, mercado: str,
            implicita: Optional[float], ya_encogido: bool = False) -> Dict:
    """La probabilidad que se puede enseñar de esa línea (v166 + v172)."""
    f = _factor_sin_precio(pick, apuesta, implicita)
    if f != 1.0:
        prob = max(0.0, min(1.0, float(prob) * f))
    try:
        import cordura_probabilidad as cp
        info = cp.revisar(prob, apuesta, pick.get('clave_liga'),
                          implicita=implicita, mercado=mercado,
                          ya_encogido=ya_encogido)
        info['factor_contexto'] = f
        return info
    except Exception as e:
        logger.debug('[valor] cordura de %s: %s', apuesta, e)
        return {'prob': prob, 'original': prob, 'fiable': True,
                'contrastada': implicita is not None, 'puede_verde': False}


# ---------------------------------------------------------------------------
# los mercados de CONTEO: córners, tarjetas, remates
# ---------------------------------------------------------------------------
_BLOQUES_CONTEO = (
    ('Córners', 'corners', 'corners'),
    ('Tarjetas', 'tarjetas', 'tarjetas'),
    ('Remates', 'remates', 'remates'),
    ('Remates a puerta', 'remates_on', 'remates_on'),
)


def _factor_lambda_de(pick: Dict, etiqueta: str, mercado: str) -> float:
    """El factor de forma reciente del bando que toca, o 1,0."""
    if etiqueta == 'Total':
        # el total es de los dos: se promedian sus factores
        fs = [_factor_lambda_de(pick, e, mercado)
              for e in ('Local', 'Visita')]
        return round(sum(fs) / 2.0, 3)
    try:
        import contexto_partido as cx
        import modo_modelo as mm
        h, a = mm._equipos(pick)
        equipo = h if etiqueta == 'Local' else a
        rival = a if etiqueta == 'Local' else h
        if not (equipo and pick.get('clave_liga')):
            return 1.0
        # el rival viaja para que el H2H pueda pesar en la lambda (v174)
        return cx.factor_lambda(pick['clave_liga'], equipo, mercado,
                                rival=rival or '')
    except Exception as e:
        logger.debug('[valor] factor lambda: %s', e)
        return 1.0


def _de_conteo(pick: Dict, bloques: Dict) -> List[Dict]:
    """
    Todas las líneas que la casa publica de cada conteo, contra el modelo.

    El modelo da probabilidad a CUALQUIER línea —es una binomial negativa con
    su media y su dispersión—, así que aquí no hay que elegir una: se recorre
    la escalera entera de la casa y cada peldaño sale con su cuota y su Score.
    """
    try:
        import rendimiento_equipos as rq
    except Exception as e:
        logger.debug('[valor] sin rendimiento_equipos: %s', e)
        return []
    imp = pick.get('implicitas') or {}
    salida: List[Dict] = []
    for titulo, clave_bloque, fam in _BLOQUES_CONTEO:
        bloque = bloques.get(titulo)
        if not bloque:
            continue
        # v175 — UN MERCADO SIN INSIGNIA YA NO SE CALLA: SE MARCA.
        #
        # Hasta la v174 un bloque estimado o mal calibrado no entraba en
        # la lista y su mercado se quedaba sin ninguna propuesta. El
        # encargo lo rechaza: «que TODOS los mercados que Playdoit ofrece
        # tengan siempre una recomendacion». Asi que entra, con
        # `incierto=True` colgado de cada fila, y la tarjeta lo pinta en
        # gris con el aviso de alta incertidumbre en vez de un candado.
        #
        # Lo que NO se ha quitado: la correccion. Estas filas siguen
        # pasando por `cordura_probabilidad` —encogidas hacia el precio
        # de Playdoit y recortadas— exactamente igual que las demas. Lo
        # que se levanta es el BLOQUEO, no el control.
        incierto = not (bloque.get('confianza') or {}).get('insignia')
        disp_tot = bloque.get('dispersion_total')
        disp_eq = bloque.get('dispersion')
        for etq, media, disp, sufijo in (
                ('Total', bloque.get('lambda_total'), disp_tot, ''),
                ('Local', bloque.get('lambda_home'), disp_eq, '_home'),
                ('Visita', bloque.get('lambda_away'), disp_eq, '_away')):
            if not media:
                continue
            # v173 — LA LAMBDA SE AJUSTA A LOS ULTIMOS CINCO PARTIDOS.
            #
            # Se pidio que un equipo que no anota vea bajar su «Mas de
            # 2,5» y que uno en racha lo vea subir. El factor compara su
            # media reciente con la suya larga —no con la de la liga— y
            # va recortado a [0,80 · 1,20]: cinco partidos son pocos.
            media = float(media) * _factor_lambda_de(pick, etq,
                                                     clave_bloque)
            lineas = imp.get(fam + sufijo) or {}
            for clave, dato in lineas.items():
                try:
                    linea = float(clave)
                except (TypeError, ValueError):
                    continue
                try:
                    p_mas = rq.prob_mas_de(float(media), linea, disp)
                except Exception:
                    p_mas = None
                if p_mas is None:
                    continue
                salida.extend(_dos_lados(
                    pick, titulo, etq, linea, float(p_mas), dato,
                    clave_bloque, media, incierto=incierto))
    return salida


def _dos_lados(pick, titulo, etq, linea, p_mas, dato, bloque, media,
               incierto: bool = False):
    """Las dos apuestas de una línea —Más y Menos—, cada una con su cuota."""
    import mercado_implicito as mi
    imp_mas = mi.prob_de(dato)
    filas = []
    for es_mas, p, cuota, imp in (
            (True, p_mas, mi.cuota_de(dato, 'mas'), imp_mas),
            (False, 1.0 - p_mas, mi.cuota_de(dato, 'menos'),
             None if imp_mas is None else 1.0 - imp_mas)):
        if not cuota:
            continue
        texto = '%s de %s' % ('Más' if es_mas else 'Menos',
                              ('%.1f' % linea).rstrip('0').rstrip('.'))
        info = _ajusta(pick, texto, p, titulo, imp)
        if not info.get('fiable'):
            continue
        filas.append(_fila(
            titulo, etq, '%s%s: %s' % (titulo,
                                       '' if etq == 'Total' else ' ' + etq,
                                       texto),
            info.get('prob', p), cuota, imp, bloque, linea,
            {'media': round(float(media), 2),
             'incierto': bool(incierto),
             'contrastada': bool(info.get('contrastada'))}))
    return filas


# ---------------------------------------------------------------------------
# goles, 1X2, BTTS y doble oportunidad
# ---------------------------------------------------------------------------
def _de_goles(pick: Dict) -> List[Dict]:
    """Cada línea de goles que la casa publica Y el modelo sabe calcular."""
    import mercado_implicito as mi
    lineas_modelo = pick.get('goles_lineas') or {}
    imp = (pick.get('implicitas') or {}).get('goles') or {}
    salida = []
    # v174 — SOLO LAS LINEAS QUE LA CASA PUBLICA. EL TABLERO ES EL FILTRO.
    #
    # La v173 recorria las lineas DEL MODELO para que los partidos sin precio
    # tuvieran algo que proponer, y con eso invento lineas que no existen:
    # medido, **218 de 773 candidatas de goles (el 28 %)** eran fantasma. El
    # caso claro fue Rapid Vienna - Hearts, donde la casa solo cotiza 2,5 y la
    # aplicacion ofrecia 0,5, 1,5, 3,5, 4,5, 5,5 y 6,5.
    #
    # El historico es el MOTOR —dice cuantos goles esperar— y el tablero de
    # Playdoit es el FILTRO —dice que se puede jugar—. Una probabilidad sobre
    # una linea que no existe no es una apuesta: es un numero.
    for clave, dato in imp.items():
        p_mas = lineas_modelo.get(clave)
        if p_mas is None:
            # la casa cotiza esa linea y el modelo no la calcula: tampoco se
            # inventa. `alpha_finder.lineas_de_goles` decide cuales hay.
            continue
        try:
            p_mas = float(p_mas)
        except (TypeError, ValueError):
            continue
        imp_mas = mi.prob_de(dato)
        for es_mas, p, cuota, i in (
                (True, p_mas, mi.cuota_de(dato, 'mas'), imp_mas),
                (False, 1.0 - p_mas, mi.cuota_de(dato, 'menos'),
                 None if imp_mas is None else 1.0 - imp_mas)):
            texto = '%s de %s' % ('Más' if es_mas else 'Menos', clave)
            info = _ajusta(pick, texto, p, 'Goles', i)
            if not info.get('fiable'):
                continue
            salida.append(_fila('Goles', 'Total', 'Goles: %s' % texto,
                                info.get('prob', p), cuota, i, 'goles',
                                float(clave),
                                {'contrastada': bool(info.get('contrastada'))}))
    return salida


def _de_resultado(pick: Dict) -> List[Dict]:
    """1X2, ambos marcan y doble oportunidad, con las cuotas de la casa."""
    import modo_modelo as mm
    imp = pick.get('implicitas') or {}
    salida = []
    h, a = mm._equipos(pick)
    # v172 — ¿VIENE EL 1X2 YA ENCOGIDO, O SOLO LO SUPONEMOS?
    #
    # `alpha_finder` encoge el 1X2 hacia el mercado desde la v71, pero SOLO
    # cuando hubo ancla (Pinnacle o el cierre de ESPN). Darlo por hecho
    # siempre dejaba pasar la probabilidad cruda del modelo justo en los
    # partidos sin ancla — el mismo fallo que acababa de costarnos la doble
    # oportunidad. Se lee la marca que el propio barrido deja en el pick.
    ya = any(bool((m.get('calibracion') or {}).get('aplicado'))
             for m in (pick.get('mercados') or [])
             if isinstance(m, dict) and str(m.get('mercado')) == '1X2')
    tri = mm.probabilidades_1x2(pick)
    cu = imp.get('1x2_cuotas') or {}
    x2 = imp.get('1x2') or {}
    if tri and h and a:
        pl, px, pv = tri
        for lado, p, etq in (('home', pl, 'Gana %s' % h),
                             ('draw', px, 'Empate'),
                             ('away', pv, 'Gana %s' % a)):
            # v174 — SIN CUOTA NO HAY APUESTA QUE PROPONER.
            #
            # La v173 emitia estas filas sin precio para que ningun partido se
            # quedara vacio. Pero una seleccion que la casa no cotiza no se
            # puede jugar, y ofrecerla es el mismo defecto que las lineas
            # fantasma. Los partidos sin tablero los cubre el camino heredado
            # de `modo_modelo`, que usa los mercados que el barrido ya publica.
            cuota = cu.get(lado)
            if not cuota:
                continue
            info = _ajusta(pick, etq, p, '1X2', x2.get(lado),
                           ya_encogido=ya)
            if not info.get('fiable'):
                continue
            salida.append(_fila('1X2', 'Resultado', etq,
                                info.get('prob', p), cuota, x2.get(lado),
                                'resultado'))
        # LA DOBLE OPORTUNIDAD ENTRA, PERO NO POR LA PUERTA GRANDE.
        #
        # Se pidió explícitamente: es un mercado más y sólo se recomienda si
        # tiene valor. Por debajo de 1,30 de cuota ni se evalúa — a ese precio
        # el Score no puede competir aunque la probabilidad sea del 80 %, y era
        # justo lo que llenaba la pantalla en la v170.
        dob = imp.get('doble_cuotas') or {}
        for clave, p, etq, lados in (
                ('1X', pl + px, '%s o empate' % h, ('home', 'draw')),
                ('12', pl + pv, '%s o %s' % (h, a), ('home', 'away')),
                ('X2', px + pv, '%s o empate' % a, ('draw', 'away'))):
            cuota = dob.get(clave)
            # v174 — sin precio no hay doble que jugar; y con precio, el suelo
            # de 1,30 sigue valiendo: por debajo de eso la doble es la trampa
            # que llenaba la pantalla en la v170.
            if not cuota or cuota < CUOTA_MINIMA_DOBLE:
                continue
            # v172 — LA IMPLICITA SALE DE SUMAR DOS LADOS DEL 1X2 DEVIGADO.
            #
            # Era el UNICO mercado que entraba sin contraste (`implicita=None`)
            # y por eso la aplicacion recomendo «AmaZulu o empate» con Score
            # 1,35 en un partido donde la casa le daba 21,15 %: sin implicita
            # no hay encogimiento ni control de cordura, y el Score se
            # calculaba sobre la probabilidad cruda del modelo.
            #
            # Y se suma el 1X2, no se deviga la familia de dobles: sus tres
            # selecciones suman 2 y no 1, asi que devigarlas a tres vias da un
            # numero que no es una probabilidad (se probo: 0,468/0,434/0,098).
            imp_do = None
            if x2 and all(k in x2 for k in lados):
                imp_do = float(x2[lados[0]]) + float(x2[lados[1]])
            info = _ajusta(pick, etq, p, 'Doble oportunidad', imp_do,
                           ya_encogido=ya)
            if not info.get('fiable'):
                continue
            salida.append(_fila('Doble oportunidad', 'Doble', etq,
                                info.get('prob', p), cuota, imp_do,
                                'resultado'))
    b = mm._board(pick)
    cb = imp.get('btts_cuotas') or {}
    p_si = b.get(mm._ETQ_BTTS_SI)
    if p_si is not None:
        imp_si = imp.get('btts')
        for clave, p, etq, i in (
                ('si', p_si, 'Ambos marcan: Sí', imp_si),
                ('no', 1.0 - float(p_si), 'Ambos marcan: No',
                 None if imp_si is None else 1.0 - float(imp_si))):
            cuota = cb.get(clave)
            if not cuota:
                continue
            info = _ajusta(pick, etq, float(p), 'BTTS', i)
            if not info.get('fiable'):
                continue
            salida.append(_fila('BTTS', 'Ambos marcan', etq,
                                info.get('prob', p), cuota, i, 'btts'))
    return salida


# ---------------------------------------------------------------------------
# la puerta de entrada
# ---------------------------------------------------------------------------
def candidatos(pick: Dict, bloques: Optional[Dict] = None) -> List[Dict]:
    """Todas las apuestas jugables del partido, con su cuota y su Score."""
    if pick.get('jugado') or pick.get('sin_modelo'):
        return []
    filas = []
    try:
        filas += _de_resultado(pick)
    except Exception as e:
        logger.debug('[valor] resultado: %s', e)
    try:
        filas += _de_goles(pick)
    except Exception as e:
        logger.debug('[valor] goles: %s', e)
    try:
        filas += _de_conteo(pick, bloques or {})
    except Exception as e:
        logger.debug('[valor] conteo: %s', e)
    # v175 — LA CUARENTENA DEJA DE APARTAR NADA: SOLO MARCA.
    #
    # La v168 la puso como muro (un bloque mal calibrado en esa liga no
    # se propone) y la v173 la rebajo a preferencia (aparta si queda
    # algo). El encargo la rebaja del todo: «Eliminar el estado 🔒 No
    # recomendado... solo deben faltar si el mercado no existe en
    # Playdoit». Un mercado en cuarentena sigue siendo un mercado que la
    # casa cotiza y el usuario puede jugar.
    #
    # LO QUE ESTO CUESTA, Y NO ES CERO. La cuarentena existe porque hay
    # mercados que en algunas ligas calibran mal de verdad: los goles del
    # Brasileirao B dan ECE 0,118 en crudo, mas del doble del 0,05 que
    # este proyecto llama aceptable. Ese 0,118 es de la probabilidad
    # CRUDA; lo que se publica va encogido hacia el precio de Playdoit y
    # medido asi da 0,0111 (v175). Aun asi, una recomendacion de un
    # bloque en cuarentena es peor que una de un bloque estable, y por
    # eso la fila viaja marcada y la tarjeta lo dice.
    try:
        import mercado_estabilidad as me
        for f in filas:
            if me.en_cuarentena(pick.get('clave_liga'), f['bloque']):
                f['incierto'] = True
                f['sin_medir'] = True
    except Exception as e:
        logger.debug('[valor] estabilidad: %s', e)
    # v174 — TODA CANDIDATA TIENE PRECIO, PORQUE TODA CANDIDATA SE PUEDE
    # JUGAR. Sin cuota no hay Score y, mas importante, no hay apuesta: es una
    # probabilidad sobre algo que la casa no ofrece.
    return [f for f in filas if f.get('cuota')]


def mejor(pick: Dict, bloques: Optional[Dict] = None) -> Optional[Dict]:
    """
    v175 — LA APUESTA RECOMENDADA ES LA DE MAYOR SCORE. SIEMPRE HAY UNA.

    EL ENCARGO, con sus numeros: «La 🏆 Apuesta Recomendada sera la de
    mayor Score, siempre que Probabilidad >= 50 % y Cuota >= 1,20. Si la
    de mayor Score no cumple, se pasa a la siguiente que si cumpla. Si
    ninguna cumple, se muestra la de mayor Score con aviso de baja
    probabilidad.» Eso es exactamente lo que hace esta funcion.

    EL CASO QUE LO PROVOCA, del propio usuario: en Toluca - Austin la
    aplicacion recomendaba «Goles Mas de 1,5» al 79 % con Score 0,95
    mientras en «Mejor Valor», dos lineas mas abajo, habia un Score 0,98.
    Recomendar lo que uno mismo esta diciendo que vale menos no se puede
    defender, y la separacion entre las dos secciones era el sintoma.

    LO QUE CUESTA, MEDIDO SOBRE 47.794 PARTIDOS (v171.1)
    -----------------------------------------------------
        elegir por Score        2.947 apuestas · acierto 66,0 % ·
                                ROI −0,67 % · p5 −2,81 %
        elegir por probabilidad 44.557 apuestas · acierto 76,0 % ·
                                ROI −6,17 %

    Se acierta DIEZ PUNTOS MENOS y se pierde cinco y medio menos. De las
    cuatro politicas que este proyecto ha liquidado contra el marcador,
    la del Score es la unica que se acerca al equilibrio — y ninguna gana
    dinero. La tarjeta no puede prometer que se bate al mercado y no lo
    promete.

    LO QUE **NO** SE QUITA
    ----------------------
    Ni el ajuste de la probabilidad —una linea que se separa del precio
    de la casa sigue viniendo encogida y recortada por
    `cordura_probabilidad`— ni el techo del 90 %: una cifra por encima de
    ahi con cuota jugable es casi siempre un defecto del modelo, no una
    ganga. Lo que se levanta es el bloqueo por mercado, no el control de
    la cifra.
    """
    filas = candidatos(pick, bloques)
    if not filas:
        return None
    dignas = [f for f in filas
              if f.get('score') is not None
              and f['prob'] >= PROB_SUELO_DURO
              and f['prob'] <= PROB_MAXIMA_RECO
              and (f.get('cuota') or 0.0) >= CUOTA_DECENTE]
    baja = not dignas
    if baja:
        # regla 5 del encargo: si ninguna llega a los minimos se propone
        # igual la de mejor Score, avisando. La promesa de la v173 —que
        # siempre hay recomendacion— sigue en pie.
        dignas = filas
    elegida = max(dignas, key=lambda f: (f.get('score') or 0.0,
                                         round(f['prob'], 4)))
    return dict(elegida, mejor_del_partido=True, baja_probabilidad=baja)


def por_mercado(pick: Dict, bloques: Optional[Dict] = None) -> Dict:
    """
    v175 — LA MEJOR APUESTA DE **CADA** MERCADO QUE PLAYDOIT COTIZA.

    La tarjeta ya no enseña un mercado con sus dos lados y un candado:
    enseña, mercado por mercado, la linea concreta que la aplicacion
    jugaria y su Score. Un mercado sin entrada aqui es un mercado que
    Playdoit NO publica — la unica ausencia que el encargo admite.

    Devuelve `{nombre_del_mercado: fila}` con la de mejor Score de cada
    uno, sin filtro de probabilidad ni de cuota: aqui se INFORMA de lo
    mejor que hay en ese mercado. Los minimos son cosa de `mejor`, que es
    quien elige la apuesta principal.
    """
    grupos: Dict[str, List[Dict]] = {}
    for f in candidatos(pick, bloques):
        grupos.setdefault(str(f.get('mercado') or ''), []).append(f)
    salida: Dict[str, Dict] = {}
    for clave, filas in grupos.items():
        # LOS MISMOS MINIMOS QUE LA PRINCIPAL, Y NO ES UN ADORNO.
        #
        # Sin ellos, la primera prueba contra el tablero real de
        # Mamelodi - AmaZulu propuso «Gana AmaZulu» al 10 % como
        # recomendacion del 1X2, porque a cuota 11,00 su Score es 1,08 —
        # el mas alto del mercado. Es la trampa de la cuota inflada que
        # la v172 vino a cerrar, entrando por la puerta de al lado.
        #
        # Y cuando NINGUNA linea del mercado llega a los minimos no se
        # deja el mercado vacio —eso seria el candado otra vez— sino que
        # se propone la MAS PROBABLE. En un mercado donde no hay nada
        # bien pagado, lo honesto es enseñar lo mas probable, no lo mas
        # caro.
        dignas = [f for f in filas
                  if f.get('score') is not None
                  and f['prob'] >= PROB_SUELO_DURO
                  and f['prob'] <= PROB_MAXIMA_RECO
                  and (f.get('cuota') or 0.0) >= CUOTA_DECENTE]
        if dignas:
            salida[clave] = max(dignas,
                                key=lambda f: (f.get('score') or 0.0,
                                               round(f['prob'], 4)))
        else:
            salida[clave] = dict(
                max(filas, key=lambda f: (round(f['prob'], 4),
                                          f.get('cuota') or 0.0)),
                incierto=True)
    return salida
