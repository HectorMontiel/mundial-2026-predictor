#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — El tablón multi-casa, cruzado con el modelo: mercados con EV REAL.

El problema que resuelve
------------------------
La vista de liga tenía DOS caminos para enseñar cuotas y no eran comparables:

  A) `cuotas_auto` — encuentra el `event_id` de ESPN y saca 1X2, over/under,
     hándicap y props de jugador, todo cruzado con la plantilla y con su EV.
     Es la tabla rica que se ve en Liga MX.
  B) `_mostrar_cuotas_multi` — el respaldo cuando (A) no encuentra el evento.
     Enseñaba SÓLO el 1X2 de cada casa y la línea «Mejor precio disponible».

Y (A) falla justo donde más partidos hay: `buscar_event_id` mapea el nombre de
ESPN contra el nombre del modelo, y en las competiciones europeas el catálogo
del motor no contiene a los equipos de fase previa. En los registros de
producción se ve tal cual:

    [name_mapper] sin mapear: 'Kairat Almaty' (evid) — mejor candidato
                              'AC Milan' con 0.29

Sin `event_id` no hay (A), y la Champions, la Conference y la Eredivisie se
quedaban con la tabla pobre de (B) mientras Liga MX enseñaba treinta mercados.
El usuario lo dijo así: «¿y las demás cuotas? Quiero que todas las ligas
muestren bien todas las cuotas, todo al mismo nivel».

La solución
-----------
Dejar de depender del `event_id`. `cuotas_multi.cuotas_partido` YA devuelve, de
las cinco casas y sin ninguna clave, mucho más de lo que (B) pintaba:

    casas               1X2 de cada casa
    totales             Más/Menos de 2.5 y ambos marcan
    totales_por_casa    lo mismo, sin fusionar, con la casa de cada precio
    handicap_por_casa   hándicap asiático con la línea referida al local

Aquí eso se traduce al MISMO vocabulario que usa la plantilla del modelo y se
cruza con `cuotas_manual.cruzar_con_plantilla`, que es el cruce difuso que (A)
ya usaba. Resultado: la tabla rica en TODAS las competiciones que tengan
precio, venga o no de ESPN.

Y con una ventaja que (A) no tenía: (A) lee una sola casa (la que ESPN
publique), mientras que esto compara las cinco y se queda con la MEJOR de cada
mercado. Eso importa más que el modelo — la v112 midió que comprar al mejor
precio da +1,37 % de ROI sin modelo ninguno, mientras que apostar por la
probabilidad del modelo pierde entre −4,66 % y −6,52 %.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Mercados que se saben leer del tablón, en el orden en que se enseñan.
FAMILIAS = ('1X2', 'Total de goles', 'Ambos marcan', 'Hándicap asiático')


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _linea_txt(v: float) -> str:
    """0.5 → «0.5»; 1.0 → «1»  (la plantilla escribe «Monterrey -1», no «-1.0»)."""
    return f'{v:g}'


def filas_del_tablon(res: Dict, home: str, away: str) -> List[Dict]:
    """
    Todo lo que el tablón publica, como filas `{etiqueta, cuota, casa, familia}`
    en el vocabulario de la plantilla del modelo.

    Las etiquetas están copiadas de `plantilla_club` a propósito —«Gana
    Monterrey», «Más de 2.5 goles», «Ambos equipos marcan: Sí», «Juarez
    +1.5»—, porque el cruce posterior es por similitud de cadena y acertar el
    vocabulario es lo que decide si un mercado aparece o se pierde.
    """
    filas: List[Dict] = []

    def _add(etiqueta, cuota, casa, familia):
        c = _f(cuota)
        if c is not None:
            filas.append({'etiqueta': etiqueta, 'cuota': round(c, 4),
                          'casa': casa, 'familia': familia})

    # --- 1X2, de cada casa ------------------------------------------------
    for casa, c in (res.get('casas') or {}).items():
        if casa.startswith('_'):          # '_totales' es un cajón interno
            continue
        _add(f'Gana {home}', (c or {}).get('home'), casa, '1X2')
        _add('Empate', (c or {}).get('draw'), casa, '1X2')
        _add(f'Gana {away}', (c or {}).get('away'), casa, '1X2')

    # --- totales y ambos marcan -------------------------------------------
    # Se prefiere la versión POR CASA (permite line shopping); el dict
    # fusionado es el respaldo, y entonces no se sabe de quién es el precio.
    por_casa = res.get('totales_por_casa') or {}
    if not por_casa and (res.get('totales') or {}):
        por_casa = {'—': res['totales']}
    for casa, t in por_casa.items():
        _add('Más de 2.5 goles', (t or {}).get('over25'), casa, 'Total de goles')
        _add('Menos de 2.5 goles', (t or {}).get('under25'), casa, 'Total de goles')
        _add('Ambos equipos marcan: Sí', (t or {}).get('btts_yes'), casa,
             'Ambos marcan')
        _add('Ambos equipos marcan: No', (t or {}).get('btts_no'), casa,
             'Ambos marcan')

    # --- hándicap asiático -------------------------------------------------
    # `handicap_por_casa` trae la línea REFERIDA AL LOCAL (negativa = local
    # favorito), que es el convenio del proyecto. La plantilla nombra cada
    # lado con su propia línea, así que la del visitante va cambiada de signo.
    for casa, ah in (res.get('handicap_por_casa') or {}).items():
        linea = (ah or {}).get('linea')
        if linea is None:
            continue
        try:
            L = float(linea)
        except (TypeError, ValueError):
            continue
        signo_h = '-' if L < 0 else '+'
        signo_a = '+' if L < 0 else '-'
        v = _linea_txt(abs(L))
        _add(f'{home} {signo_h}{v}', ah.get('home'), casa, 'Hándicap asiático')
        _add(f'{away} {signo_a}{v}', ah.get('away'), casa, 'Hándicap asiático')

    return filas


def mercados_con_ev(res: Dict, plantilla: Dict, home: str,
                    away: str) -> List[Dict]:
    """
    Mercados del tablón cruzados con el modelo, **al mejor precio de cada uno**.

    Por qué al mejor precio y no al de una casa fija: es el único criterio con
    ROI positivo y robusto que el proyecto ha medido (+11,49 % en el tramo de
    juicio, p5 +1,73 %). Cada fila lleva la casa que da ese precio y cuántas
    casas se compararon, para que se vea de dónde sale.

    Devuelve filas ordenadas por EV descendente con:
        mercado, apuesta, prob, cuota_casa, casa, cuota_justa, ev,
        n_casas, cuota_peor, familia
    """
    filas = filas_del_tablon(res, home, away)
    if not filas:
        return []

    # line shopping: una sola fila por etiqueta, con el precio más alto
    mejor_por_etq: Dict[str, Dict] = {}
    for f in filas:
        prev = mejor_por_etq.get(f['etiqueta'])
        if prev is None:
            mejor_por_etq[f['etiqueta']] = {**f, 'n_casas': 1,
                                            'cuota_peor': f['cuota']}
            continue
        prev['n_casas'] += 1
        prev['cuota_peor'] = min(prev['cuota_peor'], f['cuota'])
        if f['cuota'] > prev['cuota']:
            prev.update({'cuota': f['cuota'], 'casa': f['casa']})

    try:
        import cuotas_manual
        cruzadas = cuotas_manual.cruzar_con_plantilla(
            [{'etiqueta': v['etiqueta'], 'cuota': v['cuota']}
             for v in mejor_por_etq.values()], plantilla)
    except Exception as e:
        logger.warning(f'[tablon] no se pudo cruzar con la plantilla: {e}')
        return []

    # `cruzar_con_plantilla` devuelve la etiqueta de la PLANTILLA, no la que se
    # le pasó; el enlace de vuelta es `texto_pegado`, que conserva la nuestra.
    for r in cruzadas:
        origen = mejor_por_etq.get(r.get('texto_pegado')) or {}
        r['casa'] = origen.get('casa')
        r['n_casas'] = origen.get('n_casas', 1)
        r['cuota_peor'] = origen.get('cuota_peor')
        r['familia'] = origen.get('familia', '')
        # cuánto se gana por comprar bien en vez de mal, en el mismo mercado
        if r.get('cuota_peor') and r['cuota_peor'] > 0:
            r['ventaja_line_shopping'] = round(
                r['cuota_casa'] / r['cuota_peor'] - 1, 4)
        else:
            r['ventaja_line_shopping'] = 0.0

    # un mismo mercado del modelo puede recibir dos etiquetas nuestras; se
    # conserva la de mejor EV (mismo criterio que `cuotas_auto.evaluar`)
    mejor: Dict[str, Dict] = {}
    for r in cruzadas:
        prev = mejor.get(r['apuesta'])
        if prev is None or r['ev'] > prev['ev']:
            mejor[r['apuesta']] = r
    return sorted(mejor.values(), key=lambda r: -r['ev'])


def adjuntar_a_plantilla(plantilla: Dict, res: Dict, home: str,
                         away: str) -> int:
    """
    Cuelga de la plantilla las cuotas REALES del tablón, por id de campo.

    Es el enganche que hace que el constructor de combinadas deje de razonar
    con cuotas justas. `match_parlay` armaba los parlays con `cuota = 1/prob`
    salvo para los pocos mercados que hubiera en `odds_actuales.json`, un
    fichero que escribe el pipeline una vez al día; con esto usa el precio que
    las casas publican AHORA, que es el que el usuario va a pagar.

    Importa para el resultado, no sólo para la presentación: con cuotas justas
    el EV de toda pata es 0 por construcción, así que el motor sólo podía
    ordenar por probabilidad. Con precio real puede ver qué pata paga de más —
    que es lo que el usuario pidió: «propón un parlay en base a las cuotas
    reales automáticas».

    Devuelve cuántos campos se han podido rellenar y escribe en la plantilla:
        pl['cuotas_tablon']      {id_campo: cuota}
        pl['casas_tablon']       {id_campo: casa que da ese precio}
    """
    if not isinstance(plantilla, dict):
        return 0
    try:
        filas = mercados_con_ev(res, plantilla, home, away)
    except Exception as e:
        logger.warning(f'[tablon] no se pudieron adjuntar cuotas: {e}')
        return 0
    cuotas, casas = {}, {}
    for r in filas:
        cid = r.get('id')
        if not cid or not r.get('cuota_casa'):
            continue
        # si el mismo id llega dos veces, manda el precio más alto: es el que
        # el usuario puede tomar de verdad (line shopping)
        if cid not in cuotas or r['cuota_casa'] > cuotas[cid]:
            cuotas[cid] = float(r['cuota_casa'])
            casas[cid] = r.get('casa')
    if cuotas:
        plantilla['cuotas_tablon'] = cuotas
        plantilla['casas_tablon'] = casas
    return len(cuotas)


class MotorConTablon:
    """
    El motor de la competición, pero con las cuotas del tablón enganchadas.

    `match_parlay` tiene tres constructores (`construir_parlay_partido`,
    `construir_parlay_con_resultado` y el `proponer_parlays` que los orquesta)
    y los tres piden la plantilla al motor por su cuenta. Envolver el motor
    resuelve los tres de una vez y sin añadir un parámetro que habría que ir
    pasando de función en función — y sin variables de módulo, que en una app
    con varias sesiones a la vez serían una fuente de datos cruzados.

    Todo lo que no sea pedir la plantilla se delega intacto.
    """

    def __init__(self, motor, cuotas: Dict, casas: Optional[Dict] = None):
        self._motor = motor
        self._cuotas = cuotas or {}
        self._casas = casas or {}

    def __getattr__(self, nombre):
        return getattr(self._motor, nombre)

    def _con_cuotas(self, pl):
        if isinstance(pl, dict) and self._cuotas:
            pl['cuotas_tablon'] = dict(self._cuotas)
            pl['casas_tablon'] = dict(self._casas)
        return pl

    def plantilla_club(self, *a, **kw):
        return self._con_cuotas(self._motor.plantilla_club(*a, **kw))

    def plantilla(self, *a, **kw):
        return self._con_cuotas(self._motor.plantilla(*a, **kw))


def motor_con_tablon(motor, home: str, away: str, deporte: str = 'futbol',
                     fecha=None, liga: Optional[str] = None):
    """
    Motor envuelto con el mejor precio real de cada mercado, o el motor tal
    cual si el tablón no da nada.

    Nunca lanza: sin red, sin partido en el tablón o sin cruce posible, se
    devuelve el motor original y las combinadas salen con cuota justa, que es
    exactamente lo que hacían antes.
    """
    try:
        import cuotas_multi as cm
        pl = (motor.plantilla_club(home, away)
              if hasattr(motor, 'plantilla_club') else motor.plantilla(home, away))
        if not isinstance(pl, dict) or 'error' in pl:
            return motor, 0
        res = cm.cuotas_partido(deporte, home, away, fecha=fecha, liga=liga)
        n = adjuntar_a_plantilla(pl, res, home, away)
        if not n:
            return motor, 0
        return MotorConTablon(motor, pl.get('cuotas_tablon'),
                              pl.get('casas_tablon')), n
    except Exception as e:
        logger.info(f'[tablon] sin cuotas en vivo para el parlay: '
                    f'{type(e).__name__}: {e}')
        return motor, 0


def resumen_line_shopping(res: Dict) -> Optional[str]:
    """
    Frase corta con lo que cuesta comprar en la casa equivocada.

    Sale del propio tablón, sin modelo: es la única cifra de esta pantalla que
    no depende de que el modelo acierte.
    """
    casas = {k: v for k, v in (res.get('casas') or {}).items()
             if not k.startswith('_')}
    if len(casas) < 2:
        return None
    peor_mejor = []
    for lado in ('home', 'draw', 'away'):
        precios = [c[lado] for c in casas.values()
                   if (c or {}).get(lado) and c[lado] > 1]
        if len(precios) >= 2 and min(precios) > 0:
            peor_mejor.append(max(precios) / min(precios) - 1)
    if not peor_mejor:
        return None
    return (f"Entre las {len(casas)} casas del tablón hay hasta un "
            f"**{max(peor_mejor)*100:.1f} %** de diferencia de precio en el "
            f"mismo resultado.")
