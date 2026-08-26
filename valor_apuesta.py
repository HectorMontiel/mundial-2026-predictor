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


def _ajusta(pick: Dict, apuesta: str, prob: float, mercado: str,
            implicita: Optional[float], ya_encogido: bool = False) -> Dict:
    """La probabilidad que se puede enseñar de esa línea (v166)."""
    try:
        import cordura_probabilidad as cp
        return cp.revisar(prob, apuesta, pick.get('clave_liga'),
                          implicita=implicita, mercado=mercado,
                          ya_encogido=ya_encogido)
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
                           ya_encogido=True)
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
        for clave, p, etq in (('1X', pl + px, '%s o empate' % h),
                              ('12', pl + pv, '%s o %s' % (h, a)),
                              ('X2', px + pv, '%s o empate' % a)):
            cuota = dob.get(clave)
            if not cuota or cuota < CUOTA_MINIMA_DOBLE:
                continue
            info = _ajusta(pick, etq, p, 'Doble oportunidad', None,
                           ya_encogido=True)
            salida.append(_fila('Doble oportunidad', 'Doble', etq,
                                info.get('prob', p), cuota, None,
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
    vivos = [f for f in filas
             if f['score'] >= SCORE_AMBAR
             and f['prob'] >= PROB_SUELO_DURO
             and (f['prob'] >= PROB_MINIMA
                  or (f['score'] > SCORE_EXCEPCION and f.get('contrastada')))]
    if not vivos:
        return None
    elegida = max(vivos, key=lambda f: (f['score'], f['prob']))
    return dict(elegida, mejor_del_partido=True)
