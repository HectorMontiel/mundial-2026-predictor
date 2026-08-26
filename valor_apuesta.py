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
SCORE_VERDE = 1.10          # 🟢 valor
SCORE_AMBAR = 0.95          # 🟡 aceptable
CUOTA_MINIMA_DOBLE = 1.30   # la doble oportunidad no entra por debajo de esto
# v172 — la trampa de la cuota inflada, tal y como se describio:
# probabilidad baja + cuota alta = cebo, no oportunidad.
PROB_TRAMPA = 0.20
CUOTA_TRAMPA = 2.50

_RE_MAS = re.compile(r'^m[aá]s de ', re.I)


def semaforo(score: Optional[float], prob: Optional[float] = None) -> str:
    """🟢 / 🟡 / 🔴 por SCORE, que es lo que ahora significa el color."""
    if score is None:
        return '⚪'
    if prob is not None and prob < PROB_MINIMA and score < SCORE_EXCEPCION:
        return '🔴'
    if score > SCORE_VERDE:
        return '🟢'
    if score >= SCORE_AMBAR:
        return '🟡'
    return '🔴'


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
        # un mercado que no se ha ganado la insignia no propone (v164/v168)
        if not (bloque.get('confianza') or {}).get('insignia'):
            continue
        disp_tot = bloque.get('dispersion_total')
        disp_eq = bloque.get('dispersion')
        for etq, media, disp, sufijo in (
                ('Total', bloque.get('lambda_total'), disp_tot, ''),
                ('Local', bloque.get('lambda_home'), disp_eq, '_home'),
                ('Visita', bloque.get('lambda_away'), disp_eq, '_away')):
            if not media:
                continue
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
                    clave_bloque, media))
    return salida


def _dos_lados(pick, titulo, etq, linea, p_mas, dato, bloque, media):
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
    for clave, dato in imp.items():
        p_mas = lineas_modelo.get(clave)
        if p_mas is None:
            # la casa cotiza esa línea pero el modelo no la calculó: no se
            # inventa. `alpha_finder.lineas_de_goles` decide cuáles hay.
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
            if not cuota:
                continue
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
    # la cuarentena de la v168 sigue mandando: un mercado inestable en esta
    # liga no se propone por mucho Score que tenga.
    try:
        import mercado_estabilidad as me
        filas = [f for f in filas
                 if not me.en_cuarentena(pick.get('clave_liga'), f['bloque'])]
    except Exception as e:
        logger.debug('[valor] estabilidad: %s', e)
    return [f for f in filas if f.get('score') is not None]


def mejor(pick: Dict, bloques: Optional[Dict] = None) -> Optional[Dict]:
    """
    La apuesta de mejor valor del partido, o `None`.

    La regla que se pidió, en orden: máximo Score; nunca por debajo del 60 % de
    probabilidad salvo que el Score pase de 1,15; y a igualdad de Score, la más
    probable.
    """
    filas = candidatos(pick, bloques)
    if not filas:
        return None
    # Y NUNCA SE PROPONE UN 🔴. El propio encargo define el rojo como «no
    # recomendado» (Score < 0,95): devolver el maximo de una lista donde todo
    # es rojo seria recomendar lo menos malo, que no es lo mismo. Medido sobre
    # los picks del dia, sin esta guarda salian recomendaciones con Score 0,872.
    # v172 — LAS DOS REGLAS ANTI-TRAMPA, Y EL VETO DEL HISTORIAL.
    #
    #   · CUOTA INFLADA: probabilidad ajustada < 20 % con cuota > 2,50 no se
    #     recomienda nunca. Es el cebo clasico de la casa para el equipo debil.
    #   · VETO POR H2H: una apuesta que nombra al bando que pierde 8 de 10
    #     cruces no se propone, tenga el Score que tenga. Es un FILTRO: no
    #     cambia ninguna probabilidad, asi que no puede romper la calibracion.
    ctx = contexto_de(pick)
    try:
        import contexto_partido as cx
        import modo_modelo as mm
        h_, a_ = mm._equipos(pick)
    except Exception:
        cx, h_, a_ = None, None, None
    vivos = []
    for f in filas:
        if f['prob'] < PROB_TRAMPA and (f['cuota'] or 0) > CUOTA_TRAMPA:
            continue
        if cx is not None and h_ and a_ and cx.veta(ctx, f['apuesta'], h_, a_):
            continue
        if f['score'] < SCORE_AMBAR or f['prob'] < PROB_SUELO_DURO:
            continue
        if f['prob'] < PROB_MINIMA and not (f['score'] > SCORE_EXCEPCION
                                            and f.get('contrastada')):
            continue
        vivos.append(f)
    if not vivos:
        return None
    elegida = max(vivos, key=lambda f: (f['score'], f['prob']))
    return dict(elegida, mejor_del_partido=True)
