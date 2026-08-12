#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v123 — Cuando el partido está parejo, el 1X2 no es la única forma de jugarlo.

El usuario lo pidió así: «en partidos que sean parejos deberías también evaluar
en el modelo no irte tanto por un ganador, si no ver si es mejor irte por doble
oportunidad».

Es una petición sensata y encaja con lo que este proyecto tiene medido. En un
partido igualado, la probabilidad del ganador ronda el 35-40 % y la del empate
el 28-30 %: el 1X2 es prácticamente una moneda de tres caras, y ahí la
diferencia entre acertar y no acertar la marca el azar más que el modelo. La
doble oportunidad cubre dos de los tres resultados.

QUÉ SE MIDE AQUÍ Y QUÉ NO
-------------------------
NO se dice que la doble oportunidad tenga valor. No hay ninguna medición en
este proyecto que lo respalde, y la regla de la casa es no publicar una ventaja
que no se haya medido. Lo que este módulo calcula es lo que SÍ se puede
comprobar con los precios que hay delante, sin depender de que el modelo
acierte:

  1. **Cuánta probabilidad más cubres** al pasar de «Gana X» a «X o Empate».
  2. **Cuánta cuota pagas por esa cobertura**, en porcentaje.
  3. **Qué margen cobra la casa en cada uno de los dos mercados.** Ésta es la
     cifra clave y casi nadie la mira: si la doble oportunidad cobra tres
     puntos más de margen que el 1X2, cubrir el empate sale caro aunque la
     probabilidad suba, y eso se sabe SIN modelo — sale de sumar inversos de
     cuotas.

El margen de la doble oportunidad no se calcula como el del 1X2. Cada una de
sus tres opciones cubre DOS de los tres resultados, así que la suma de las
probabilidades implícitas de un libro sin margen vale 2, no 1. El margen es
`suma / 2 - 1`. Compararlo con el del 1X2 sin esa corrección haría parecer que
la doble oportunidad cobra el doble, que es falso.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Por debajo de esta probabilidad, el favorito no es un favorito: es el menos
# improbable de tres. 0,45 no es un número redondo elegido a ojo — es donde el
# 1X2 deja de tener un resultado que gane más de la mitad de las veces, y por
# tanto donde «apostar al ganador» pasa a ser minoritario por construcción.
PROB_FAVORITO_PAREJO = 0.45

# Y si además los dos equipos están a menos de esto, el partido no sólo no
# tiene favorito claro: no tiene favorito.
DIF_MAXIMA_PAREJA = 0.12


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def margen_1x2(cuotas: Dict) -> Optional[float]:
    """
    Margen del libro de 1X2: cuánto se queda la casa. 0,07 = 7 %.

    Es la suma de las probabilidades implícitas menos 1. Sin modelo y sin
    supuestos: sale de las tres cuotas y de nada más.
    """
    vs = [_f(cuotas.get(k)) for k in ('home', 'draw', 'away')]
    if not all(vs):
        return None
    return round(sum(1.0 / v for v in vs) - 1.0, 4)


def margen_doble(cuotas: Dict) -> Optional[float]:
    """
    Margen del libro de doble oportunidad, comparable con el del 1X2.

    Sus tres opciones cubren dos resultados cada una, así que en un libro justo
    las probabilidades implícitas suman 2. De ahí el `/2` — sin él parecería
    que la casa cobra el doble de lo que cobra.
    """
    vs = [_f(cuotas.get(k)) for k in ('1x', '12', 'x2')]
    if not all(vs):
        return None
    return round(sum(1.0 / v for v in vs) / 2.0 - 1.0, 4)


def es_parejo(p_home: float, p_draw: float, p_away: float) -> Dict:
    """
    ¿Está el partido igualado? Con el porqué, no sólo con un sí o un no.
    """
    try:
        ph, px, pa = float(p_home), float(p_draw), float(p_away)
    except (TypeError, ValueError):
        return {'parejo': False, 'motivo': 'sin probabilidades'}
    s = ph + px + pa
    if s <= 0:
        return {'parejo': False, 'motivo': 'sin probabilidades'}
    ph, px, pa = ph / s, px / s, pa / s
    favorito = max(ph, pa)
    dif = abs(ph - pa)
    parejo = favorito < PROB_FAVORITO_PAREJO or dif < DIF_MAXIMA_PAREJA
    if parejo:
        motivo = (f"el favorito sólo gana el {favorito*100:.0f} % de las veces"
                  if favorito < PROB_FAVORITO_PAREJO else
                  f"los dos equipos están a {dif*100:.0f} puntos")
    else:
        motivo = (f"hay un favorito claro ({favorito*100:.0f} %) y "
                  f"{dif*100:.0f} puntos de diferencia")
    return {'parejo': bool(parejo), 'motivo': motivo,
            'p_home': round(ph, 4), 'p_draw': round(px, 4),
            'p_away': round(pa, 4),
            'p_favorito': round(favorito, 4), 'diferencia': round(dif, 4),
            'p_1x': round(ph + px, 4), 'p_x2': round(px + pa, 4),
            'p_12': round(ph + pa, 4)}


def comparar(plantilla: Dict, mercados: List[Dict], home: str,
             away: str, cuotas_1x2: Optional[Dict] = None,
             cuotas_dc: Optional[Dict] = None) -> Optional[Dict]:
    """
    «Gana X» frente a «X o Empate», con el precio real de cada uno.

    `mercados` son las filas ya cruzadas con el modelo (las devuelve
    `cuotas_tablon.mercados_con_ev` o `mercados_playdoit_con_ev`), así que esto
    vale igual para el tablón multi-casa que para la casa del usuario — y por
    eso no importa de dónde vengan los precios: lo que compara son dos mercados
    del MISMO libro.

    Devuelve None si el modelo no da el 1X2, que es cuando no hay nada que
    comparar.
    """
    por_id = {m.get('id'): m for m in (mercados or []) if m.get('id')}
    campos = {}
    for sec in (plantilla or {}).get('secciones', []):
        for c in sec.get('campos', []):
            if c.get('id'):
                campos[c['id']] = c
    try:
        ph = float(campos['home_win_prob']['valor']) / 100.0
        px = float(campos['draw_prob']['valor']) / 100.0
        pa = float(campos['away_win_prob']['valor']) / 100.0
    except (KeyError, TypeError, ValueError):
        return None

    estado = es_parejo(ph, px, pa)
    salida = {**estado, 'home': home, 'away': away, 'lados': []}

    # Los dos libros salen de los MISMOS mercados ya cruzados, por su `id` del
    # modelo. Así esto funciona igual con el tablero de una sola casa y con el
    # tablón multi-casa, sin que el llamador tenga que volver a leer nada.
    #
    # Con el tablón multi-casa el margen resultante es el del MEJOR precio de
    # cada resultado —que es más bajo que el de cualquier casa suelta y no
    # corresponde a ningún libro real—, así que se marca de dónde viene para
    # que la pantalla no lo presente como «lo que cobra tu casa».
    def _cuota(cid):
        return _f((por_id.get(cid) or {}).get('cuota_casa'))

    if cuotas_1x2 is None:
        cuotas_1x2 = {'home': _cuota('home_win_prob'),
                      'draw': _cuota('draw_prob'),
                      'away': _cuota('away_win_prob')}
    if cuotas_dc is None:
        cuotas_dc = {'1x': _cuota('dc_1x'), '12': _cuota('dc_12'),
                     'x2': _cuota('dc_x2')}
    casas = {(por_id.get(c) or {}).get('casa')
             for c in ('home_win_prob', 'draw_prob', 'away_win_prob',
                       'dc_1x', 'dc_12', 'dc_x2')
             if (por_id.get(c) or {}).get('casa')}
    salida['casas'] = sorted(casas)
    salida['casa_unica'] = len(casas) == 1

    for lado, id_gana, id_doble, etq_gana, etq_doble, p_g, p_d in (
            ('home', 'home_win_prob', 'dc_1x', f'Gana {home}',
             f'{home} o Empate', ph, ph + px),
            ('away', 'away_win_prob', 'dc_x2', f'Gana {away}',
             f'Empate o {away}', pa, pa + px)):
        m_g, m_d = por_id.get(id_gana), por_id.get(id_doble)
        c_g = _f((m_g or {}).get('cuota_casa'))
        c_d = _f((m_d or {}).get('cuota_casa'))
        fila = {'lado': lado, 'etiqueta_gana': etq_gana,
                'etiqueta_doble': etq_doble,
                'prob_gana': round(p_g, 4), 'prob_doble': round(p_d, 4),
                'cuota_gana': c_g, 'cuota_doble': c_d,
                'casa_gana': (m_g or {}).get('casa'),
                'casa_doble': (m_d or {}).get('casa')}
        if c_g and c_d:
            # cuánta probabilidad ganas y cuánta cuota das a cambio
            fila['prob_extra'] = round(p_d - p_g, 4)
            fila['cuota_menos'] = round(c_d / c_g - 1, 4)      # negativo
            # el precio de la tranquilidad: cuánta cuota se cede por cada punto
            # porcentual de probabilidad que se cubre de más
            if p_d > p_g:
                fila['precio_por_punto'] = round(
                    (1 - c_d / c_g) / ((p_d - p_g) * 100), 4)
        salida['lados'].append(fila)

    # los dos márgenes, que es lo único de aquí que no depende del modelo
    if cuotas_1x2:
        salida['margen_1x2'] = margen_1x2(cuotas_1x2)
    if cuotas_dc:
        salida['margen_doble'] = margen_doble(cuotas_dc)
    if salida.get('margen_1x2') is not None \
            and salida.get('margen_doble') is not None:
        salida['margen_extra'] = round(salida['margen_doble']
                                       - salida['margen_1x2'], 4)
    return salida


def frases(an: Dict) -> List[str]:
    """
    La lectura en castellano llano, con los números delante.

    Se escribe aquí y no en la interfaz porque es donde están los datos y
    porque así el mismo texto vale para la pantalla y para Telegram.
    """
    if not an:
        return []
    out: List[str] = []
    if an.get('parejo'):
        out.append(
            f"**Este partido está parejo**: {an['motivo']}. Con el 1X2 estás "
            f"pagando por acertar cuál de tres cosas pasa, y dos de ellas "
            f"—empate y victoria visitante— suman "
            f"{(an['p_draw'] + an['p_away'])*100:.0f} %.")
    else:
        out.append(f"Este partido **no está parejo**: {an['motivo']}. La doble "
                   f"oportunidad aquí cubre poco más que el ganador y paga "
                   f"bastante menos.")

    for f in an.get('lados', []):
        if not (f.get('cuota_gana') and f.get('cuota_doble')):
            continue
        out.append(
            f"**{f['etiqueta_gana']}** paga {f['cuota_gana']:.2f} y acierta el "
            f"{f['prob_gana']*100:.0f} %. **{f['etiqueta_doble']}** paga "
            f"{f['cuota_doble']:.2f} y acierta el {f['prob_doble']*100:.0f} %: "
            f"cubres **{f['prob_extra']*100:+.0f} puntos** más de probabilidad "
            f"a cambio de **{f['cuota_menos']*100:.0f} %** de cuota.")

    me, m1, md = (an.get('margen_extra'), an.get('margen_1x2'),
                  an.get('margen_doble'))
    if m1 is not None and md is not None:
        if not an.get('casa_unica') and an.get('casas'):
            out.append(
                f"Aviso sobre los dos márgenes de abajo: estos precios vienen "
                f"de **{len(an['casas'])} casas distintas** "
                f"({', '.join(an['casas'])}), así que el margen que sale es el "
                f"del mejor precio de cada resultado y no el que cobra ninguna "
                f"casa en concreto. Para saber lo que te cobran a ti, mira "
                f"esta misma comparación en la sección de tu casa.")
        if me is not None and me > 0.015:
            out.append(
                f"⚠️ **Pero la casa cobra más por la doble oportunidad**: "
                f"{md*100:.1f} % de margen frente al {m1*100:.1f} % del 1X2, "
                f"o sea **{me*100:+.1f} puntos**. Cubrir el empate aquí no es "
                f"gratis: parte de esa tranquilidad ya la has pagado en el "
                f"precio. Esto NO depende de que el modelo acierte — sale de "
                f"sumar los inversos de las cuotas.")
        elif me is not None and me < -0.005:
            out.append(
                f"Y la doble oportunidad está **mejor de precio** que el 1X2 "
                f"en esta casa: {md*100:.1f} % de margen frente a "
                f"{m1*100:.1f} %. Es raro y merece mirarse.")
        else:
            out.append(
                f"Los dos mercados cobran prácticamente el mismo margen "
                f"({md*100:.1f} % la doble oportunidad, {m1*100:.1f} % el "
                f"1X2), así que cubrir el empate no te cuesta margen extra en "
                f"esta casa. La decisión es sólo de cuánto riesgo quieres.")
    out.append(
        "Esto es gestión de riesgo, **no una ventaja**: el proyecto no tiene "
        "medido que la doble oportunidad gane dinero, igual que no lo tiene "
        "medido para el 1X2. Lo único con ROI positivo y robusto sigue siendo "
        "comprar al mejor precio.")
    return out
