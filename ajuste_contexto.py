#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v213 — Las barritas que suman y restan: contexto y noticias sobre la probabilidad.

EL ENCARGO, CON SUS PALABRAS
----------------------------
«Si de repente sale una noticia de que hay jugadores lesionados, bueno pues eso
le va a restar al equipo; si sale que regresó un jugador muy bueno, eso le va a
sumar; si son locales y no han perdido en bastante tiempo, eso le va a sumar.
Todas las barritas, porque se suman o restan.»

Eso es exactamente lo que hace este módulo: cada señal de contexto aporta un
DELTA CON SIGNO sobre la probabilidad del equipo, y el resultado se enseña
descompuesto — no un número nuevo, sino el número de siempre con sus sumas y
sus restas a la vista.

LA REGLA DE ORO DE ESTE MÓDULO
------------------------------
**Nunca se pisa la probabilidad del modelo: se publica una SEGUNDA.**

    prob_modelo      la de siempre, intacta, la que el motor entrenó
    prob_ajustada    la anterior más los deltas de contexto
    desglose         cada delta con su nombre, su signo y su fuente

Las dos viajan juntas y la pantalla puede enseñar las dos. Esto no es prudencia
decorativa: ninguno de estos deltas está medido contra ROI, y el proyecto ya
tiene la cicatriz de aplicar coeficientes a ojo (ver `riesgo_liga`, donde la
tabla de volatilidad escrita a mano salió invertida al medirla). Con las dos
probabilidades separadas, el día que haya ledger se puede medir CUÁL de las dos
acierta más. Si se pisara la original, esa pregunta ya no se podría hacer.

DE DÓNDE SALEN LOS TAMAÑOS
--------------------------
De ningún sitio: son la escala que pidió el encargo, puesta a mano. Están todos
en `PESOS`, en un solo bloque, para que se puedan cambiar de golpe cuando haya
medición — y para que nadie los confunda con un resultado. La única señal con
efecto MEDIDO fuera de muestra es la aclimatación, y ésa no pasa por aquí: la
aplica `contexto_ampliado` sobre el 1X2 antes, porque está medida.

EL TOPE, QUE ES LA PARTE IMPORTANTE
-----------------------------------
El ajuste total está limitado a ±`TOPE_TOTAL` (12 puntos). Sin tope, cuatro
señales de 5 puntos mueven una probabilidad 20 puntos y el «contexto» acaba
pesando más que el modelo entrenado con miles de partidos. El tope es lo que
mantiene esto en su sitio: un matiz, no una segunda opinión.
"""

import logging
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger('ajuste_contexto')

# ---------------------------------------------------------------------------
# LOS PESOS. Todos a mano, todos juntos, ninguno medido.
# ---------------------------------------------------------------------------
PESOS = {
    # --- restan ---
    'lesion_clave': -0.06,        # baja un jugador del top 3 en xG/xA
    'lesion_multiple': -0.09,     # dos o más bajas importantes
    'baja_defensiva': -0.04,
    'entrenador_nuevo_rival': -0.05,   # el rebote lo sufre el favorito
    'racha_negativa': -0.04,      # 5+ sin ganar
    'fatiga': -0.03,              # partido con poco descanso
    # --- suman ---
    'regreso_clave': +0.05,       # vuelve un jugador importante
    'racha_positiva': +0.04,      # 3 de los últimos 4
    'invicto_local': +0.05,       # local sin perder en mucho tiempo
    'h2h_favorable': +0.03,
    'descanso_extra': +0.02,
}

# Cuánto puede mover el contexto en total, sumando todo.
TOPE_TOTAL = 0.12

# Suelo y techo de la probabilidad ajustada. Una probabilidad no puede salir
# de aquí por mucho contexto que haya: 0 y 1 son certezas y el contexto no las
# produce nunca.
SUELO, TECHO = 0.02, 0.98

# Cuánto pesa una señal según lo fiable que sea su fuente. Un dato del
# histórico propio vale más que un titular.
FIABILIDAD_MINIMA = 0.5


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def delta_de(senal: Dict) -> Dict:
    """El aporte con signo de UNA señal. Cero si no se reconoce el tipo.

    Se escala por `confianza_fuente`: una señal de Wikidata (0,85) mueve menos
    que una del histórico propio (0,95). Por debajo de `FIABILIDAD_MINIMA` no
    mueve nada — y se dice, en vez de descartarla en silencio.
    """
    s = senal or {}
    tipo = str(s.get('tipo') or '')
    base = PESOS.get(tipo)
    if base is None:
        return {'tipo': tipo, 'delta': 0.0, 'aplicado': False,
                'motivo': f'tipo `{tipo}` sin peso definido'}
    conf = _f(s.get('confianza_fuente'))
    conf = 1.0 if conf is None else conf
    if conf < FIABILIDAD_MINIMA:
        return {'tipo': tipo, 'delta': 0.0, 'aplicado': False,
                'motivo': f'fuente poco fiable ({conf:.2f})'}
    peso = _f(s.get('peso'))
    peso = 1.0 if peso is None else max(0.0, peso)
    delta = base * conf * min(peso, 2.0)
    return {'tipo': tipo, 'delta': round(delta, 4), 'aplicado': True,
            'fuente': s.get('fuente'), 'confianza': conf,
            'detalle': s.get('detalle') or '',
            'motivo': ''}


def ajustar(prob_modelo: Optional[float],
            senales: Optional[Sequence[Dict]] = None,
            tope: float = TOPE_TOTAL) -> Dict:
    """La probabilidad con el contexto sumado y restado, y su desglose.

    Devuelve SIEMPRE las dos probabilidades. Nunca lanza.
    """
    p = _f(prob_modelo)
    vacio = {'prob_modelo': p, 'prob_ajustada': p, 'delta_total': 0.0,
             'desglose': [], 'topado': False}
    if p is None or not (0.0 < p < 1.0):
        return vacio

    desglose = [delta_de(s) for s in (senales or []) if isinstance(s, dict)]
    bruto = sum(d['delta'] for d in desglose if d['aplicado'])

    topado = abs(bruto) > tope
    neto = max(-tope, min(tope, bruto))
    ajustada = max(SUELO, min(TECHO, p + neto))

    return {'prob_modelo': round(p, 4),
            'prob_ajustada': round(ajustada, 4),
            'delta_total': round(ajustada - p, 4),
            'delta_bruto': round(bruto, 4),
            'topado': topado,
            'tope': tope,
            'desglose': desglose,
            'medido': False}


def ajustar_1x2(p_home: Optional[float], p_draw: Optional[float],
                p_away: Optional[float],
                senales_home: Optional[Sequence[Dict]] = None,
                senales_away: Optional[Sequence[Dict]] = None) -> Dict:
    """Las tres probabilidades del 1X2, ajustadas y RENORMALIZADAS.

    La renormalización no es cosmética. Si el local sube 5 puntos y nadie más
    se mueve, las tres dejan de sumar 1 y la doble oportunidad —que se calcula
    sumando dos de ellas— empieza a dar probabilidades imposibles. Es el mismo
    cuidado que `contexto_ampliado.ajustar_1x2` ya tiene, y por el mismo
    motivo.

    El empate no recibe señales propias: absorbe el resto, que es lo que hace
    en la práctica cuando uno de los dos equipos mejora o empeora.
    """
    ph, px, pa = _f(p_home), _f(p_draw), _f(p_away)
    if None in (ph, px, pa):
        return {'aplicado': False, 'p_home': ph, 'p_draw': px, 'p_away': pa}

    ah = ajustar(ph, senales_home)
    aa = ajustar(pa, senales_away)
    nh, na = ah['prob_ajustada'], aa['prob_ajustada']
    nx = max(SUELO, px)

    s = nh + nx + na
    if s <= 0:
        return {'aplicado': False, 'p_home': ph, 'p_draw': px, 'p_away': pa}
    nh, nx, na = nh / s, nx / s, na / s

    # REDONDEAR LAS TRES POR SEPARADO ROMPE LA SUMA. Con 4 decimales salían
    # 1,0001, y quien consume esto suma DOS de ellas para la doble oportunidad:
    # el error no se queda donde nace. El empate absorbe el residuo, que es lo
    # que ya hace en el resto del módulo.
    rh, ra = round(nh, 4), round(na, 4)
    rx = round(1.0 - rh - ra, 4)

    return {'aplicado': bool(ah['desglose'] or aa['desglose']),
            'p_home': rh, 'p_draw': rx, 'p_away': ra,
            'p_home_modelo': ph, 'p_draw_modelo': px, 'p_away_modelo': pa,
            'local': ah, 'visitante': aa,
            'medido': False}


# ---------------------------------------------------------------------------
def de_partido(clave_liga: Optional[str], home: str, away: str,
               p_home: Optional[float], p_draw: Optional[float],
               p_away: Optional[float], deporte: str = 'futbol',
               fecha: Optional[str] = None) -> Dict:
    """Recoge las señales reales del partido y devuelve el 1X2 ajustado.

    Se apoya en `scraper_contexto`, que es quien sabe qué fuentes existen y
    cuáles no. Aquí no se consulta ninguna fuente directamente.
    """
    sh: List[Dict] = []
    sa: List[Dict] = []
    try:
        import scraper_contexto as sc
        todas = sc.senales({'clave_liga': clave_liga, 'home': home,
                            'away': away, 'partido': f'{home} vs {away}',
                            'deporte': deporte, 'fecha': fecha})
    except Exception as e:
        logger.debug('[ajuste] señales: %s', e)
        todas = []

    # A quién afecta cada señal se decide por el nombre del equipo que la
    # señal menciona en su detalle. Si no menciona a ninguno, no se reparte:
    # aplicar una señal al equipo equivocado es peor que no aplicarla.
    for s in todas:
        detalle = str(s.get('detalle') or '')
        if home and home in detalle:
            sh.append(s)
        elif away and away in detalle:
            sa.append(s)
    return ajustar_1x2(p_home, p_draw, p_away, sh, sa)


def explicar(a: Dict) -> List[str]:
    """Las barritas en texto: qué suma, qué resta y cuánto."""
    fuera = []
    for lado, etiqueta in (('local', 'Local'), ('visitante', 'Visitante')):
        d = (a or {}).get(lado) or {}
        for x in d.get('desglose', []):
            if not x.get('aplicado'):
                continue
            signo = '▲' if x['delta'] > 0 else '▼'
            fuera.append(f"{signo} {etiqueta} {x['delta']*100:+.1f} pp · "
                         f"{x['tipo'].replace('_', ' ')}"
                         + (f" ({x['detalle']})" if x.get('detalle') else ''))
        if d.get('topado'):
            fuera.append(f"· {etiqueta}: ajuste recortado al tope de "
                         f"±{d['tope']*100:.0f} pp")
    return fuera


if __name__ == '__main__':
    a = ajustar_1x2(
        0.45, 0.27, 0.28,
        senales_home=[{'tipo': 'invicto_local', 'peso': 1,
                       'confianza_fuente': 0.95, 'detalle': '12 sin perder'},
                      {'tipo': 'regreso_clave', 'peso': 1,
                       'confianza_fuente': 0.85, 'detalle': 'vuelve el 9'}],
        senales_away=[{'tipo': 'lesion_multiple', 'peso': 1,
                       'confianza_fuente': 0.85, 'detalle': 'dos centrales'}])
    print('modelo   :', a['p_home_modelo'], a['p_draw_modelo'], a['p_away_modelo'])
    print('ajustado :', a['p_home'], a['p_draw'], a['p_away'])
    print('suma 1   :', round(a['p_home'] + a['p_draw'] + a['p_away'], 6))
    for linea in explicar(a):
        print('  ', linea)
