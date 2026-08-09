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

    # --- v114: TODAS las líneas de goles del ancla sharp -------------------
    #
    # `totales_por_casa` sólo trae la línea de 2.5. Pinnacle publica el abanico
    # entero (0.5, 1.5, 2.5, 3.5, 4.5…) y hasta la v114 se descartaba. Sin
    # esto, un partido tenía cinco mercados con precio real y no había con qué
    # armar más de una combinada.
    #
    # Sólo se emiten las líneas que la plantilla del modelo TIENE: las de .5
    # hasta 5.5. Las asiáticas de cuarto (2.25, 2.75) no existen ahí, y
    # dejarlas pasar sería peor que perderlas — el cruce es por similitud de
    # texto y «Más de 2.25 goles» se parece demasiado a «Más de 2.5 goles»,
    # así que acabaría poniéndole a un mercado el precio de otro.
    for linea, precios in (res.get('lineas_totales') or {}).items():
        try:
            L = float(linea)
        except (TypeError, ValueError):
            continue
        if abs(L * 2 - round(L * 2)) > 1e-9 or L % 1 == 0 or not (0 < L <= 5.5):
            continue                      # sólo X.5, y dentro de la plantilla
        _add(f'Más de {_linea_txt(L)} goles', (precios or {}).get('over'),
             'Pinnacle', 'Total de goles')
        _add(f'Menos de {_linea_txt(L)} goles', (precios or {}).get('under'),
             'Pinnacle', 'Total de goles')

    # --- v114: TODAS las líneas de hándicap del ancla sharp ----------------
    # Misma criba: la plantilla nombra «Monterrey -1.5» y «Juarez +1.5», así
    # que sólo entran las líneas de .5. La del visitante va con el signo
    # cambiado, que es como la escribe la plantilla.
    for linea, precios in (res.get('lineas_handicap') or {}).items():
        try:
            L = float(linea)
        except (TypeError, ValueError):
            continue
        if abs(L * 2 - round(L * 2)) > 1e-9 or L % 1 == 0 or abs(L) > 4:
            continue
        v = _linea_txt(abs(L))
        signo_h = '-' if L < 0 else '+'
        signo_a = '+' if L < 0 else '-'
        _add(f'{home} {signo_h}{v}', (precios or {}).get('home'),
             'Pinnacle', 'Hándicap asiático')
        _add(f'{away} {signo_a}{v}', (precios or {}).get('away'),
             'Pinnacle', 'Hándicap asiático')

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


# Por encima de este EV, la explicación más probable NO es que haya valor.
#
# El proyecto lo tiene medido: el modelo no bate al mercado (4 de 37 ligas) y
# el EV que declara es ANTI-indicador del cierre (correlación −0,054 con el
# CLV). Un mercado líquido como el de Pinnacle no se equivoca un 40 %; el que
# se equivoca es el modelo. Ordenar por EV, sin más, pone arriba justo sus
# peores errores — que es lo contrario de lo que hace falta.
#
# Ejemplo real del 2026-08-09, Bodo/Glimt vs Union Saint-Gilloise:
#     «Menos de 1.5 goles» @ 5,40 · el modelo dice justa 2,47 → EV +118,7 %
# Pinnacle da un 18,5 % implícito y el modelo un 40 %. La diferencia no es una
# oportunidad de +118 %: es el modelo equivocándose en un mercado sharp.
EV_SOSPECHOSO = 0.30


def marcar_ev_sospechoso(filas: List[Dict]) -> List[Dict]:
    """Marca las filas cuyo EV es demasiado bueno para ser cierto."""
    for r in filas:
        r['ev_sospechoso'] = bool(
            (r.get('ev') or 0) > EV_SOSPECHOSO and (r.get('n_casas') or 1) <= 1)
    return filas


def recomendar_combinada(opciones: List[Dict],
                         mercados: Optional[List[Dict]] = None) -> Optional[Dict]:
    """
    Cuál de las combinadas propuestas merece la pena, y POR QUÉ.

    El criterio NO es el EV. Lo que este proyecto ha medido positivo es
    comprar al mejor precio (+1,37 % de ROI sin modelo ninguno), y lo que ha
    medido negativo es apostar por la probabilidad del modelo (−4,66 % a
    −6,52 % en 37.158 apuestas). Así que se puntúa, por este orden:

      1. que las patas tengan precio comparado entre VARIAS casas — es la
         única ventaja medida, y sin dos precios no hay comparación;
      2. la probabilidad conjunta real (PFP), que es lo que decide si la
         combinada entra;
      3. la cuota, pero con peso bajo: subirla es fácil y siempre a costa de
         la probabilidad.

    Se penaliza el EV sospechoso (ver `EV_SOSPECHOSO`) en vez de premiarlo.

    Devuelve la opción elegida con un campo `motivo_recomendacion` en texto
    llano, o None si ninguna reúne lo mínimo.
    """
    if not opciones:
        return None
    por_id = {m.get('id'): m for m in (mercados or []) if m.get('id')}
    mejor, mejor_score = None, -1e9
    for op in opciones:
        sels = op.get('selecciones') or []
        if not sels:
            continue
        pfp = float(op.get('prob_conjunta') or 0)
        cuota = float(op.get('cuota_combinada') or 1)
        n_reales = sum(1 for s in sels if s.get('cuota_fuente') == 'real')
        # cuántas patas tienen su precio comparado entre dos o más casas
        comparadas, ventaja = 0, 0.0
        sospechosas = 0
        for s in sels:
            m = por_id.get(s.get('id'))
            if not m:
                continue
            if (m.get('n_casas') or 1) >= 2:
                comparadas += 1
                ventaja += float(m.get('ventaja_line_shopping') or 0)
            if (m.get('ev') or 0) > EV_SOSPECHOSO and (m.get('n_casas') or 1) <= 1:
                sospechosas += 1
        frac_reales = n_reales / len(sels)
        frac_comp = comparadas / len(sels)
        score = (2.0 * frac_comp + 1.5 * frac_reales + 1.2 * pfp
                 + 0.25 * min(cuota, 6.0) / 6.0 - 0.8 * (sospechosas / len(sels)))
        if score > mejor_score:
            mejor, mejor_score = op, score
            mejor_meta = {'n_reales': n_reales, 'n_patas': len(sels),
                          'comparadas': comparadas, 'ventaja': ventaja,
                          'sospechosas': sospechosas, 'pfp': pfp,
                          'cuota': cuota}
    if mejor is None:
        return None
    m = mejor_meta
    partes = []
    if m['n_reales'] == m['n_patas']:
        partes.append(
            f"Las **{m['n_patas']} patas** tienen precio publicado por una "
            f"casa, así que la cuota combinada es la que vas a cobrar.")
    else:
        partes.append(
            f"**{m['n_reales']} de {m['n_patas']} patas** con precio "
            f"publicado; el resto va con cuota justa, que no es un precio que "
            f"puedas tomar.")
    if m['comparadas']:
        partes.append(
            f"**{m['comparadas']} de {m['n_patas']}** están comparadas entre "
            f"dos o más casas — la única ventaja que este proyecto tiene "
            f"medida con ROI positivo.")
    else:
        partes.append(
            "Ninguna pata tiene un segundo precio con el que compararse: las "
            "líneas alternativas hoy sólo las publica Pinnacle. Sin dos "
            "precios no hay line shopping, que es lo único que este proyecto "
            "mide en positivo — tómala como la más sólida de las disponibles, "
            "no como una ventaja demostrada.")
    partes.append(
        f"Probabilidad real de acertar todo: **{m['pfp']*100:.0f} %** a cuota "
        f"**{m['cuota']:.2f}**.")
    if m['ventaja'] > 0:
        partes.append(
            f"Comprando al mejor precio en vez de al peor se gana un "
            f"**{m['ventaja']*100:.1f} %** acumulado sobre estas patas.")
    # El aviso que más importa: si el EV conjunto sale disparado, lo que hay
    # es un modelo optimista, no una oportunidad. Se dice aquí y con el
    # número delante, no en letra pequeña.
    _ev_conj = m['pfp'] * m['cuota'] - 1
    if _ev_conj > 0.25:
        partes.append(
            f"⚠️ Ojo: {m['pfp']*100:.0f} % a cuota {m['cuota']:.2f} implica un "
            f"EV conjunto de **{_ev_conj*100:+.0f} %**. Ninguna combinada real "
            f"paga eso. Significa que el modelo da probabilidades bastante más "
            f"altas que las del mercado en estas patas, y el histórico del "
            f"proyecto dice que en esa discrepancia suele equivocarse él.")
    if m['sospechosas']:
        partes.append(
            f"⚠️ {m['sospechosas']} pata(s) con un EV superior al "
            f"{EV_SOSPECHOSO*100:.0f} % y una sola casa: eso casi siempre es "
            f"el modelo equivocándose, no valor. No es el motivo por el que "
            f"esta combinada se recomienda.")
    mejor = dict(mejor)
    mejor['motivo_recomendacion'] = partes
    return mejor


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
