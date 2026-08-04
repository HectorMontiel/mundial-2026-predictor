#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha Finder — panel «Apuestas del Día» (v26, spec §4.2).

Recorre los partidos con cuotas vigentes en odds_actuales.json (próximas
48 h), pide la predicción al motor de su liga y evalúa los mercados
disponibles (1X2, O/U 2.5, BTTS, AH ±0.5) con la cuota REAL.

Filtros de élite (spec):
  * probabilidad del modelo para el mercado > 0.70
  * EV > +3 % con la cuota real
  * cuota real > 1.50 (nada de micro-cuotas)

Si el Shadow Booster está adoptado y hay señal para el partido, el pick se
marca con ⚡ y se prioriza. Degradación honesta: si ningún candidato pasa
los filtros, se devuelven los mejores por EV marcados como no-élite; si un
partido no tiene cuota para un mercado, ese mercado no se evalúa (lista
blanca implícita de mercados disponibles).
"""

import json
import logging
import os
import traceback
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# v30: último barrido almacenado a nivel de módulo (respaldo para la
# exportación sin argumentos; evita el AttributeError de producción v29).
_ULTIMO_RESULTADO: Dict = {}

# v39: el PISO DE PROBABILIDAD lo fija edge_engine (maximin walk-forward). El
# 0.70 de la v38 apenas dejaba pasar 18 apuestas dentro de la banda de EV
# (ruido, peor ventana −7.3 %); el piso validado 0.55 rescata la franja
# [0.55,0.70) → 337 apuestas, +7.9 % ROI, peor ventana +14 %. Más cobertura Y
# más rentabilidad, ambas validadas. Fallback 0.55.
try:
    import edge_engine as _ee
    MIN_PROB = _ee.piso_prob()
    MIN_EV = _ee.banda_rentable()[0]
    # v40: gate de CONVICCIÓN prob×EV (bootstrap p5) — sube el ROI de +7.9 % a
    # +9.9 % (p5 bootstrap +0.7 % → +2.6 %: el peor 5 % plausible ya es rentable).
    MIN_CONVICCION = _ee.conviccion_min()
except Exception:
    MIN_PROB = 0.55
    MIN_EV = 0.03
    MIN_CONVICCION = 0.025
MIN_CUOTA = 1.50
# v95 — por debajo de esto no hay apuesta que valorar: una cuota de 1.00
# devuelve el importe y nada más. El tablón las publica en favoritos extremos
# de ITF y llegaban a la interfaz como «prob 96 %, EV +0,0 %», que parece una
# oportunidad y no lo es.
CUOTA_MINIMA_REAL = 1.05

# v80 — filtros del «valor de mercado» (line shopping contra Pinnacle), que es
# lo que hoy llena la Capa 1. Elegidos en el 70 % más antiguo del ledger y
# validados en el 30 % más reciente, que no participó en la elección: p5
# +3,92 % y +3,91 % sobre 3.009 y 1.309 apuestas. Sin el piso de probabilidad
# el p5 del periodo reciente es NEGATIVO con cualquier margen. Ver el bloque
# comentado en `_barrido_fixtures`.
VS_PROB_MIN = 0.30
VS_EV_MIN = 0.01

# v82 — la misma estrategia, en TENIS.
#
# El modelo de tenis no bate al mercado (log-loss 0,6109 frente a 0,5831) y por
# eso está fuera de la Capa 1. Pero `valor_vs_sharp` NO USA EL MODELO: apuesta
# donde una casa se ha quedado descolgada respecto a Pinnacle. Si el edge vive
# en la discrepancia entre casas, no hace falta arreglar el modelo.
#
# Medido sobre los datos de tennis-data, que traen Pinnacle (`Odd_PS`) y la
# mejor cuota (`Odd_Max`) en el mismo fichero — 26.397 partidos ATP y 24.594
# WTA, sin ninguna fuente nueva. Parámetros elegidos en el 70 % más antiguo y
# validados en el 30 % más reciente:
#
#     WTA · margen 1 % + prob ≥ 30 %
#         elección    n=7.909  ROI +4,68 %  p5 +1,70 %
#         validación  n=2.436  ROI +4,22 %  p5 +0,61 %   <- EDGE VALIDADO
#
#     ATP · NINGUNA configuración con p5 positivo en los dos periodos.
#         Todas las que funcionan en el 70 % se hunden en el 30 %.
#
# Por eso se habilita **solo en WTA**. Y hay un motivo para sospechar del ATP
# más allá del resultado: la mejor cuota supera a Pinnacle un 26,45 % de MEDIA
# con mediana 1,72 %, o sea que su columna `Odd_Max` tiene valores atípicos
# extremos. Antes de habilitar el ATP hay que limpiar esa fuente, no bajar el
# listón.
VS_TENIS_CIRCUITOS = {'wta'}
VS_TENIS_PROB_MIN = 0.30
VS_TENIS_EV_MIN = 0.01

# v83 — la misma estrategia en MLB.
#
# El ledger no guarda ancla de Pinnacle para MLB, así que no se podía medir por
# ahí. Pero la fuente sí tenía con qué: `sportsbookreviewsonline` publica el
# moneyline de APERTURA y el de CIERRE, y solo se ingería el cierre. Con los dos
# se reconstruye la misma estructura — precio tomable temprano contra referencia
# eficiente — que es CLV puro, y es lo que la app hace de forma natural al tomar
# precios con días de antelación.
#
# Medido sobre 27.977 juegos (cierre alineado: log-loss 0,6738 < ln 2), con
# elección en el 70 % antiguo y validación en el 30 % reciente:
#
#     margen 2 % + prob ≥ 30 %
#         elección    n=5.474  ROI +7,27 %  p5 +5,05 %
#         validación  n=2.658  ROI +5,01 %  p5 +1,67 %
#
# Lo que da confianza no es ese punto sino la forma de la tabla: **16 de las 20
# configuraciones probadas son positivas en LOS DOS periodos** (en tenis solo lo
# fueron 2 de 15). Eso no es un máximo afortunado, es una superficie estable.
#
# Matiz honesto: la medición usa el CIERRE como referencia sharp y producción
# usa a Pinnacle AHORA. No son idénticos. Lo que queda validado es el mecanismo
# —el precio temprano bate al precio eficiente en MLB— y la implementación es la
# misma que ya está validada en fútbol con Pinnacle como ancla.
VS_MLB_PROB_MIN = 0.30
VS_MLB_EV_MIN = 0.02
# v77: pestaña «Máxima Confianza». Umbral de probabilidad alto y sin mínimo de
# EV; el stake se reduce a ¼ de Kelly porque acertar mucho no es lo mismo que
# ganar dinero (ver el bloque que la construye).
PROB_MAXIMA_CONFIANZA = 0.80
FRACCION_KELLY_CONFIANZA = 0.25
# v39/v40 no tenían techo de EV en el filtro, aunque `edge_engine` sí calibra
# una BANDA: el tramo de EV alto es tóxico (−10 % de ROI en 1.033 apuestas).
try:
    MAX_EV = _ee.banda_rentable()[1]
except Exception:
    MAX_EV = 0.12

# ---------------------------------------------------------------------------
# v75 — UMBRALES POR LIGA
#
# `edge_engine` calibra un único juego de umbrales para TODAS las competiciones,
# y con razón: en la v38 se comprobó que elegir ligas por su ROI pasado
# sobreajusta. Pero eso no implica que los umbrales tengan que ser idénticos en
# todas partes, solo que una liga no puede tener los suyos "porque le fue bien".
#
# `backtest_thresholds.py` (v75) los somete a walk-forward anidado: la
# combinación se elige con los pliegues anteriores y se juzga en el siguiente, y
# solo se publica si bate a la configuración vigente por ≥2 pp de ROI con ≥50
# apuestas y bootstrap p5 > 0. Lo que llega aquí ya pasó por ahí.
#
# Sin `umbrales_capa1.json`, o con una liga que no lo superó, rige exactamente
# lo de antes (los umbrales de `edge_engine`): degradación limpia.
# ---------------------------------------------------------------------------
UMBRALES_ARCHIVO = 'umbrales_capa1.json'
_UMBRALES_CACHE: Dict = {}


def _umbrales_por_defecto() -> Dict[str, float]:
    return {'prob_min': MIN_PROB, 'ev_min': MIN_EV, 'ev_max': MAX_EV,
            'cuota_min': MIN_CUOTA, 'conviccion': MIN_CONVICCION}


def _tabla_umbrales() -> Dict:
    if 'datos' not in _UMBRALES_CACHE:
        datos = {}
        try:
            if os.path.exists(UMBRALES_ARCHIVO):
                with open(UMBRALES_ARCHIVO, encoding='utf-8') as f:
                    datos = json.load(f) or {}
        except Exception as e:
            logger.warning(f"[alpha] no se pudo leer {UMBRALES_ARCHIVO}: {e}")
        _UMBRALES_CACHE['datos'] = datos
    return _UMBRALES_CACHE['datos']


def umbrales_liga(clave_liga: Optional[str]) -> Dict[str, float]:
    """Umbrales de Capa 1 vigentes para esa liga (validados o los generales)."""
    base = _umbrales_por_defecto()
    tabla = _tabla_umbrales()
    for fuente in (tabla.get('global'), (tabla.get('ligas') or {}).get(clave_liga)):
        if isinstance(fuente, dict):
            for k in base:
                if fuente.get(k) is not None:
                    base[k] = float(fuente[k])
    return base


def pasa_capa1(prob: float, ev: float, cuota: float,
               clave_liga: Optional[str] = None) -> bool:
    """
    Filtro de élite ÚNICO (antes estaba copiado en dos sitios del módulo).

    Deliberadamente NO aplica aquí el techo de EV: el proyecto ya lo aplica al
    final del barrido (`ev_extremo`), donde los picks de EV tóxico no se
    descartan sino que se APARTAN a su propia bandeja para que el usuario los
    vea marcados. Repetir el corte aquí los mandaría a "candidatos" y esa
    bandeja se quedaría vacía. El techo por liga se respeta en ese punto.
    """
    u = umbrales_liga(clave_liga)
    return bool(prob > u['prob_min'] and ev > u['ev_min']
                and cuota > u['cuota_min']
                and prob * ev >= u['conviccion'])


# v42: umbral de CONFIRMACIÓN SHARP — el modelo supera la prob devig del cierre
# de Pinnacle por ≥5 pp. Validado: esos picks rindieron +14.7 % de ROI (p5
# bootstrap +1.4) vs +12 % del resto. Es la señal que usan las apps de pago.
SHARP_GAP_MIN = 0.05
# v44: mercados con edge VALIDADO admitidos en la Capa 1 accionable. El
# backtest multi-mercado (roi_bets_ou) probó que Over/Under 2.5 NO es rentable
# de forma robusta (p5 bootstrap negativo) → fuera de Capa 1. Solo 1X2 por
# ahora; se ampliará a otros mercados a medida que superen el bootstrap p5.
MERCADOS_VALIDADOS_CAPA1 = {'1X2'}
# v91 — «APUESTAS DEL DÍA» ES EL DÍA CALENDARIO, y punto.
#
# La historia de esta ventana en tres actos, todos pedidos por el usuario y
# cada uno corrigiendo al anterior:
#   · v88: «las próximas 24 h desde la consulta» (rolling). Funcionaba, pero
#     a las 20:00 metía ya los partidos de mañana por la mañana.
#   · v89: la ventana pasó a etiqueta y el barrido evaluó la SEMANA entera.
#     Resultado: la pestaña mezclaba picks del sábado con los de hoy, y el
#     usuario lo rechazó expresamente.
#   · v91: «si es 1 de agosto, solo apuestas del 1 de agosto, sin importar la
#     hora en que se consulte». Día calendario sobre la fecha que muestra la
#     app. La SEMANA vive en las vistas por liga/deporte (próximos partidos),
#     que es donde el usuario dijo que la quiere.
#
# Consecuencia buena: el barrido vuelve a evaluar ~25-40 partidos en vez de
# ~300, así que el arranque en frío baja de minutos a decenas de segundos.


def hoy_utc() -> pd.Timestamp:
    """
    El «hoy» del sistema, en UTC y normalizado a medianoche.

    v91 — UN SOLO RELOJ. Antes convivían `pd.Timestamp.today()` (local) y
    `utcnow()` según el punto del código, y las fechas de los fixtures vienen
    de ESPN en UTC. En Streamlit Cloud el servidor va en UTC y coincidían, así
    que la mezcla no se notaba; en cualquier máquina de América el barrido
    filtraba con un día de desfase y se quedaba a cero partidos.
    """
    return pd.Timestamp.utcnow().tz_localize(None).normalize()


def _es_del_dia(fx: dict) -> bool:
    """¿Este fixture se juega HOY (día calendario UTC)?"""
    try:
        d = pd.Timestamp(fx.get('fecha')).normalize()
    except (ValueError, TypeError):
        return False
    return d == hoy_utc()


# v91 — `_mapa_equipo_liga` y `_liga_fuzzy` se retiraron con el camino de
# `odds_actuales.json` (ver el docstring de `apuestas_del_dia`): resolvían la
# liga desde el match_id de The Odds API, y los fixtures de ESPN ya llegan con
# su clave de liga puesta.


def _mercados_del_partido(pred: Dict, o: Dict, home: str, away: str,
                          clave_liga: str = None) -> List[Dict]:
    """Evalúa cada mercado con cuota disponible contra el modelo."""
    M = np.array(pred['score_matrix'])
    idx = np.arange(M.shape[0])
    diff = idx[:, None] - idx[None, :]
    total = idx[:, None] + idx[None, :]
    pr = pred['prediction']['probabilities']
    # v71 — corrección de la sobreconfianza del pick contra el mercado sharp.
    # Medido: el modelo infla la selección que elige entre +4 y +13 pp según la
    # liga (maldición del ganador), y con el EV calculado sobre esa cifra la
    # Capa 1 se llenaba de apuestas perdedoras. Si hay cuota de Pinnacle para
    # este partido, la probabilidad del 1X2 se encoge hacia la del mercado.
    #
    # v80 — EL ANCLA CAE AL MERCADO CUANDO NO HAY PINNACLE.
    #
    # Exigir Pinnacle era MÁS ESTRICTO QUE LO QUE SE VALIDÓ.
    # `recalibrate_from_history.cargar` construye la probabilidad de mercado
    # así: usa Pinnacle si está y, si no, el cierre genérico — y lo deja
    # anotado en la columna `ancla` ('pinnacle' | 'mercado'). O sea que el
    # +6,72 % de ROI con p5 +1,02 % que el sistema exhibe se midió anclando
    # también en cuotas no-Pinnacle.
    #
    # Producción, en cambio, no encogía nada sin Pinnacle. Y Pinnacle no cubre
    # Bolivia, Colombia ni la Scottish Championship, que son parte de lo que
    # juega en julio. Con el ancla de respaldo la cobertura del encogimiento
    # pasa de 35 % a cubrir también esas ligas.
    #
    # El orden importa: Pinnacle primero por ser la casa más eficiente, y el
    # consenso disponible como segunda opción. Cuál se usó viaja en la info,
    # para que se pueda auditar desde fuera.
    calib_info = None
    _ancla, _fuente_ancla = None, None
    if clave_liga:
        if o.get('pin_home') and o.get('pin_away'):
            _ancla = {'home': o.get('pin_home'), 'draw': o.get('pin_draw'),
                      'away': o.get('pin_away')}
            _fuente_ancla = 'pinnacle'
        elif o.get('odd_home') and o.get('odd_away'):
            _ancla = {'home': o.get('odd_home'), 'draw': o.get('odd_draw'),
                      'away': o.get('odd_away')}
            _fuente_ancla = 'mercado'
    if _ancla:
        try:
            import calibracion_mercado as _cal
            import cuotas_multi as _cm
            justa = _cm.devig(_ancla, metodo='potencia')
            if len(justa) >= 2:
                pr2, calib_info = _cal.corregir(
                    {'home': pr['home'], 'draw': pr['draw'], 'away': pr['away']},
                    justa, clave_liga)
                calib_info['ancla'] = _fuente_ancla
                if calib_info.get('aplicado'):
                    pr = pr2
        except Exception as e:
            logger.debug(f"[alpha] calibración de mercado omitida: {e}")
    btts = float(M[(idx[:, None] >= 1) & (idx[None, :] >= 1)].sum())
    over25 = float(M[total > 2.5].sum())

    candidatos = []

    def _add(mercado, etiqueta, prob, cuota, sharp_gap=None, casa=None):
        if not cuota or pd.isna(cuota) or cuota <= 1:
            return
        c = {'mercado': mercado, 'apuesta': etiqueta,
             'prob': round(float(prob), 3),
             'cuota': round(float(cuota), 2),
             'cuota_justa': round(1 / max(float(prob), 1e-6), 2),
             'ev': round(float(cuota) * float(prob) - 1, 3)}
        if sharp_gap is not None:
            c['sharp_gap'] = round(float(sharp_gap), 4)
            c['sharp_confirmado'] = bool(sharp_gap >= SHARP_GAP_MIN)   # v42
        if casa:
            c['casa'] = casa                                          # v43 line shopping
        # v79 — el pick de fútbol dice ahora SI se le encogió hacia el mercado.
        #
        # La v78 adjuntó `calibracion` a los picks de MLB y de tenis, pero el
        # fútbol se quedó sin ello: la corrección se aplicaba y luego el `info`
        # se tiraba. Se descubrió al instrumentar el barrido, porque el
        # diagnóstico daba «Fútbol: SIN encogimiento aplicado» cuando en
        # realidad sí se aplicaba — simplemente no había forma de saberlo desde
        # fuera.
        #
        # Importa más aquí que en los otros dos deportes: el fútbol es HOY el
        # único con edge validado, o sea el único cuyos picks son accionables,
        # y `w=0,25` significa que tres cuartas partes de la probabilidad que
        # ve el usuario vienen del mercado. Eso tiene que poder auditarse.
        if calib_info:
            c['calibracion'] = calib_info
        # v74 — DEDUPLICACIÓN CON LINE SHOPPING.
        #
        # El mismo mercado llegaba dos veces cuando dos fuentes lo cubrían: el
        # over/under 2.5 se emitía desde `odd_over25` (scoreboard) y otra vez
        # desde `odd_over` cuando la línea rica del core API también era 2.5.
        # Resultado: «Menos de 2.5» duplicado en 4 partidos de la lista de
        # candidatos.
        #
        # En vez de descartar el segundo sin más, se conserva **la mejor
        # cuota**: es la misma apuesta y el usuario quiere el precio más alto.
        # Así el duplicado deja de ser ruido y pasa a ser line shopping.
        for i, prev in enumerate(candidatos):
            if prev['mercado'] == mercado and prev['apuesta'] == etiqueta:
                if c['cuota'] > prev['cuota']:
                    candidatos[i] = c
                return
        candidatos.append(c)

    # v42: confirmación SHARP — la prob implícita (devig) del cierre de
    # Pinnacle por selección. Si el modelo la supera por ≥5 pp, el pick rinde
    # +14.7 % de ROI (validado). Se adjunta a cada tarjeta 1X2 vía _add.
    pin = {'home': o.get('odd_home_pin'), 'draw': o.get('odd_draw_pin'),
           'away': o.get('odd_away_pin')}
    _sharp_gap = {}
    if all(pin.get(s) for s in ('home', 'draw', 'away')):
        inv = {s: 1.0 / float(pin[s]) for s in pin}
        suma = sum(inv.values())
        if suma > 0:
            devig = {s: inv[s] / suma for s in inv}   # quita el margen
            _sharp_gap = {'home': pr['home'] - devig['home'],
                          'draw': pr['draw'] - devig['draw'],
                          'away': pr['away'] - devig['away']}

    _add('1X2', f'Gana {home}', pr['home'], o.get('odd_home'),
         _sharp_gap.get('home'), o.get('casa_home'))
    _add('1X2', 'Empate', pr['draw'], o.get('odd_draw'),
         _sharp_gap.get('draw'), o.get('casa_draw'))
    _add('1X2', f'Gana {away}', pr['away'], o.get('odd_away'),
         _sharp_gap.get('away'), o.get('casa_away'))
    _add('Goles', 'Más de 2.5', over25, o.get('odd_over25'))
    _add('Goles', 'Menos de 2.5', 1 - over25, o.get('odd_under25'))
    _add('BTTS', 'Ambos marcan: Sí', btts, o.get('odd_btts_yes'))
    _add('BTTS', 'Ambos marcan: No', 1 - btts, o.get('odd_btts_no'))
    # v65: O/U en la LÍNEA REAL de la casa (ESPN publica 2.5, 3.5...), no solo 2.5
    ou_linea = o.get('ou_linea')
    try:
        ou_linea = float(ou_linea)
    except (TypeError, ValueError):
        ou_linea = None
    if ou_linea is not None and not np.isfinite(ou_linea):
        ou_linea = None
    if ou_linea is not None and abs(ou_linea - 2.5) > 1e-6:
        p_over = float(M[total > ou_linea].sum())
        _add('Goles', f'Más de {ou_linea}', p_over, o.get('odd_over'))
        _add('Goles', f'Menos de {ou_linea}', 1 - p_over, o.get('odd_under'))
    elif ou_linea is not None:
        _add('Goles', 'Más de 2.5', over25, o.get('odd_over'))
        _add('Goles', 'Menos de 2.5', 1 - over25, o.get('odd_under'))

    # v65: HÁNDICAP con línea ARBITRARIA. Antes solo se evaluaba ±0.5 y las
    # casas publican −1.5, −2.5... La probabilidad sale de la misma matriz de
    # marcadores: el local cubre −L si su margen supera L (líneas .5 → sin push).
    linea = o.get('ah_linea')
    try:
        linea = float(linea)
    except (TypeError, ValueError):
        linea = None
    if linea is not None and not np.isfinite(linea):
        linea = None                       # NaN de capturas antiguas
    if linea is not None and abs(linea * 2 - round(linea * 2)) < 1e-6:
        # margen del local necesario para cubrir: diff > -linea
        p_home_cubre = float(M[diff > -linea].sum())
        etq_h = f'{home} {"−" if linea < 0 else "+"}{abs(linea)}'
        etq_a = f'{away} {"+" if linea < 0 else "−"}{abs(linea)}'
        _add('Hándicap', etq_h, p_home_cubre, o.get('odd_ah_home'))
        _add('Hándicap', etq_a, 1 - p_home_cubre, o.get('odd_ah_away'))
    return candidatos


def _mercados_modelo(pred: Dict, home: str, away: str) -> List[Dict]:
    """v49: mercados derivados SOLO del modelo (sin cuota real) — para los
    fixtures sin cuota en vivo. Devuelve 1X2, O/U 2.5 y BTTS con la CUOTA JUSTA
    (1/prob) y sin EV. Alimenta la Capa 2 y la lista de pronósticos del día,
    para que TODO partido con jornada tenga apuestas visibles."""
    M = np.array(pred['score_matrix'])
    idx = np.arange(M.shape[0])
    total = idx[:, None] + idx[None, :]
    pr = pred['prediction']['probabilities']
    btts = float(M[(idx[:, None] >= 1) & (idx[None, :] >= 1)].sum())
    over25 = float(M[total > 2.5].sum())
    crudos = [
        ('1X2', f'Gana {home}', pr['home']),
        ('1X2', 'Empate', pr['draw']),
        ('1X2', f'Gana {away}', pr['away']),
        ('Goles', 'Más de 2.5', over25),
        ('Goles', 'Menos de 2.5', 1 - over25),
        ('BTTS', 'Ambos marcan: Sí', btts),
        ('BTTS', 'Ambos marcan: No', 1 - btts),
    ]
    salida = []
    for mercado, etiqueta, prob in crudos:
        prob = float(prob)
        salida.append({'mercado': mercado, 'apuesta': etiqueta,
                       'prob': round(prob, 3),
                       'cuota': None, 'ev': None,
                       'cuota_justa': round(1 / max(prob, 1e-6), 2),
                       'valor': '🎯'})
    return salida


# v91 — `_senales_shadow` y `_filtro_evc` se retiraron con el camino de
# `odds_actuales.json`: sólo se llamaban desde el bucle de The Odds API, que
# en producción llevaba meses sin ejecutarse (el fichero no existe en cloud).
# El Shadow Booster como experimento sigue documentado en la v26/v27.


def apuestas_del_dia(max_partidos: int = 40) -> Dict:
    """Tarjetas del panel. Devuelve élite + candidatos (degradación honesta).

    v91 — SE RETIRA EL CAMINO DE `odds_actuales.json`, el volcado de la API de
    cuotas que se dio de baja en la v88. En producción ese fichero no existe,
    así que el bucle llevaba meses sin ejecutarse: todo lo que se ve en la app
    sale del pase de fixtures (`_barrido_fixtures`, ESPN + Pinnacle + Bovada +
    Playdoit vía cuotas_multi). Con él se van sus satélites sin otro llamador
    (`_mapa_equipo_liga`, `_liga_fuzzy`, `_senales_shadow`, `_filtro_evc`) y el
    aviso «sin captura de cuotas propia», que confundía al usuario citando una
    fuente que ya no forma parte del sistema.
    """
    hoy = hoy_utc()
    motores: Dict[str, object] = {}
    elite, candidatos = [], []
    # v29 (§1.2): diagnóstico de cobertura por liga — el bug "solo MLS" venía
    # de partidos descartados en silencio cuando el nombre no mapeaba a liga.
    cobertura: Dict[str, int] = {}
    evaluados_pares: set = set()

    # v72 — ORDEN POR CALIDAD, NO POR EV BRUTO.
    #
    # Ordenar por EV descendente ponía primero justo los peores picks: un EV
    # del +169 % no es una oportunidad, es una probabilidad rota. En la lista
    # de candidatos salían «Lillestrom a 8.00 con 34 %» y «Estudiantes Río
    # Cuarto a 9.50 con 28 %» por delante de picks sanos del +5 %.
    #
    # La puntuación premia el EV **dentro de la banda creíble** y penaliza lo
    # que se sale de ella, porque a partir de cierto punto más EV significa
    # peor calibración, no más valor. Se pondera además por la probabilidad
    # (convicción) para que un 80 % al +4 % gane a un 25 % al +12 %.
    def _calidad(t):
        ev = float(t.get('ev') or 0.0)
        prob = float(t.get('prob') or 0.0)
        if ev <= 0:
            return 0.0
        creible = min(ev, EV_EXTREMO)          # el tramo que nos creemos
        exceso = max(0.0, ev - EV_EXTREMO)     # lo que huele a descalibración
        return prob * creible - 0.25 * prob * min(exceso, 1.0)

    orden = lambda t: (-int(t.get('platino', False)),
                       -int(t.get('shadow', False)),
                       -_calidad(t), -(t.get('ev') or 0))
    # v34 (§1): auditoría de cobertura — log detallado y aviso si una liga
    # activa se queda a cero partidos evaluados.
    try:
        import name_mapper
        n_fallos = name_mapper.volcar_fallos()
        if n_fallos:
            logger.warning(f"[alpha] {n_fallos} nombres sin mapear volcados a "
                           "nombres_sin_mapear.json (añade alias para llegar a 0)")
    except Exception:
        pass
    # v49: PASE DE FIXTURES (ESPN) — evalúa TODO partido con jornada aunque no
    # haya cuota en vivo. Los partidos sin cuota generan Capa 2 (cuota justa)
    # y pronósticos. Desde la v91 es EL camino (ver el docstring).
    elite_fix, candidatos_fix, capa2_futbol, pronosticos, cob_fix, n_fix = \
        _barrido_fixtures(motores, evaluados_pares)
    # v52: los fixtures con cuota REAL de ESPN entran a la Capa 1 / candidatos
    elite.extend(elite_fix)
    candidatos.extend(candidatos_fix)
    for liga, n in cob_fix.items():
        cobertura[liga] = cobertura.get(liga, 0) + n
    evaluados = n_fix

    from config import LEAGUES as _LG
    activas = [c for c, cfg in _LG.items() if cfg.get('disponible')]
    vacias = [c for c in activas if cobertura.get(c, 0) == 0]
    logger.info(f"[alpha] cobertura por liga: {cobertura} "
                f"· fixtures ESPN: {n_fix}")
    if vacias:
        logger.info(f"[alpha] ligas sin partidos HOY "
                    f"({len(vacias)}/{len(activas)}) — normal: sólo se "
                    f"evalúa el día calendario (v91)")
    global _ULTIMO_RESULTADO
    _ULTIMO_RESULTADO = {
            'actualizado': hoy_utc().strftime('%Y-%m-%d'),
            'partidos_evaluados': evaluados,
            'cobertura_ligas': cobertura, 'partidos_sin_liga': 0,
            'elite': sorted(elite, key=orden),
            # v89: 15 → 40 para no tirar apuestas con EV positivo.
            'candidatos': sorted(candidatos, key=orden)[:40],
            'capa2_futbol': capa2_futbol,        # v49
            'pronosticos': pronosticos,          # v49: TODOS los partidos
            'aviso': None if elite else
            ('Hoy ningún mercado cumple los filtros de élite (prob, EV y '
             'cuota mínimos) con las cuotas de Pinnacle, Bovada, Playdoit y '
             'ESPN — se muestran la Selección del Día, la Capa 2 y los '
             'candidatos con EV positivo.')}
    return _ULTIMO_RESULTADO


def _barrido_fixtures(motores: Dict, evaluados_pares: set):
    """v49: recorre los FIXTURES (ESPN) de todas las ligas disponibles y
    predice cada partido con su motor. Devuelve:
      · capa2_futbol: mejor selección 1X2 por partido con prob ≥ CONF_CAPA2
        (sin cuota real → cuota justa),
      · pronosticos: TODO partido con su 1X2 del modelo (informativo),
      · cobertura por liga y número de partidos evaluados nuevos.
    """
    import fixtures_espn
    import name_mapper
    from config import LEAGUES as _LG
    from league_engine import ClubEngine

    hoy = hoy_utc()
    elite_fix, candidatos_fix, capa2_futbol, pronosticos = [], [], [], []
    cobertura: Dict[str, int] = {}
    n_eval = 0
    # v50.1: prefetch CONCURRENTE de los fixtures de todas las ligas (evita que
    # ~14 llamadas secuenciales a ESPN cuelguen el barrido en Streamlit Cloud).
    claves_disp = [c for c, cfg in _LG.items()
                   if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    # v91 — SÓLO EL DÍA. `dias=1` trae hoy y mañana (rango de ESPN) y el
    # filtro `_es_del_dia` se queda con hoy. La semana completa vive en las
    # vistas por liga (fixtures_liga con DIAS_SEMANA), que es donde el usuario
    # la pidió. Ver el comentario junto a `_es_del_dia`.
    # dias=2: el rango de ESPN es UTC y así cubre el día completo aunque la
    # consulta caiga justo en el cambio de fecha; `_es_del_dia` recorta.
    fixtures_por_liga = fixtures_espn.fixtures_multi(claves_disp, dias=2)
    for _cl in list(fixtures_por_liga):
        fixtures_por_liga[_cl] = [f for f in (fixtures_por_liga[_cl] or [])
                                  if _es_del_dia(f)]
    # v89 — los motores que cargue ESTE pase se liberan al terminar su liga
    # (patrón de memoria de la v86); los precargados por el llamador se
    # respetan.
    _precargados = set(motores)

    # v65: cuotas RICAS por evento (hándicap con su línea y O/U real). El
    # scoreboard solo trae 1X2 + O/U 2.5; este endpoint añade el hándicap, que
    # es donde suele estar el valor.
    # v89 — PREFETCH: las cuotas por evento de TODAS las ligas se piden a la
    # vez al principio; la descarga corre en paralelo con las predicciones y
    # queda escondida detrás de ellas (304 s → 102 s medido con la semana; con
    # el día solo, el barrido entero baja a decenas de segundos).
    from concurrent.futures import ThreadPoolExecutor
    _pool_odds = ThreadPoolExecutor(max_workers=4, thread_name_prefix='odds89')
    _fut_odds = {}
    for _cl in claves_disp:
        _ids = [f.get('event_id') for f in (fixtures_por_liga.get(_cl) or [])]
        _ids = [i for i in _ids if i]
        if _ids:
            _fut_odds[_cl] = _pool_odds.submit(
                fixtures_espn.odds_multi, _cl, _ids)

    for clave, cfg in _LG.items():
        if not cfg.get('disponible') or clave not in fixtures_espn.ESPN_CODIGOS:
            continue
        fixtures = fixtures_por_liga.get(clave) or []
        if not fixtures:
            continue
        try:
            odds_ricas = (_fut_odds[clave].result(timeout=90)
                          if clave in _fut_odds else {})
        except Exception as e:
            logger.warning(f"[alpha/fix] odds_multi {clave}: {e}")
            odds_ricas = {}
        eng = motores.get(clave)
        if eng is None:
            try:
                eng = ClubEngine(clave)
            except Exception as e:
                logger.warning(f"[alpha/fix] motor {clave}: {e}")
                continue
            motores[clave] = eng
        if not getattr(eng, 'listo', False):
            continue
        catalogo = list(eng.stats.keys())
        for fx in fixtures:
            try:
                fecha = pd.Timestamp(fx['fecha'])
            except (ValueError, TypeError):
                continue
            tiene_cuota = bool(fx.get('odd_home') and fx.get('odd_away'))
            # v91 — los fixtures ya vienen filtrados al DÍA calendario (ver
            # `_es_del_dia`); este segundo chequeo es cinturón y tirantes.
            if fecha.normalize() != hoy:
                continue
            es_hoy = True
            home = name_mapper.mapear(fx['home'], catalogo, contexto=f'fixture→{clave}')
            away = name_mapper.mapear(fx['away'], catalogo, contexto=f'fixture→{clave}')
            if not (home and away) or home == away:
                continue
            if (clave, home, away) in evaluados_pares:
                continue                        # ya evaluado con cuota real
            evaluados_pares.add((clave, home, away))
            # v86: igual que en el barrido de cuotas — el prior de ELO es de la
            # ficha, no del pick. Ver el comentario en `_barrido_cuotas`.
            pred = eng.predecir(home, away, prior_elo=False)
            if 'error' in pred:
                continue
            n_eval += 1
            cobertura[clave] = cobertura.get(clave, 0) + 1
            mercados = _mercados_modelo(pred, home, away)
            partido = f'{home} vs {away}'
            base = {'deporte': 'Fútbol', 'liga': cfg.get('nombre', clave),
                    # v82: la CLAVE de la liga viaja con el pick. El nombre
                    # visible no la identifica: tres competiciones se llaman
                    # «Primera División» y dos «División Profesional», así que
                    # deducir la clave del nombre resolvía Argentina como El
                    # Salvador y Bolivia como Paraguay.
                    'clave_liga': clave,
                    'partido': partido, 'fecha': str(fecha.date()),
                    'shadow': False,
                    # v89: hora de inicio y bandera de «hoy» (ventana de 24 h
                    # desde la consulta) para que la UI destaque el día actual
                    # y agrupe el resto de la semana por fecha.
                    'inicio': fx.get('inicio'),
                    'es_hoy': es_hoy,
                    # v71: antelación y nº de casas, para poder ordenar por
                    # cercanía y ver de cuántas casas sale el precio
                    'dias_hasta': int((fecha - hoy).days),
                    'n_casas': fx.get('n_casas'),
                    'casas': fx.get('casas')}
            # v50: board COMPLETO por partido (todas las apuestas posibles)
            board = {m['apuesta']: round(m['prob'], 3) for m in mercados}
            x2 = [m for m in mercados if m['mercado'] == '1X2']
            mejor = max(x2, key=lambda m: m['prob'])
            pron = {**base, **mejor, 'mercados': mercados, 'board': board,
                    'sin_cuota': True}
            pronosticos.append(pron)
            # v52: ¿ESPN trajo cuotas 1X2/O-U reales para este partido? Si sí,
            # se evalúan con la MISMA lógica de élite que las cuotas capturadas
            # (line shopping ESPN) → Capa 1 con EV. Si no, van a Capa 2 (modelo).
            o_espn = {}
            # v65: se combinan las cuotas del scoreboard con las RICAS del
            # endpoint por evento (que aportan hándicap y la línea real de O/U).
            _ricas = odds_ricas.get(fx.get('event_id')) or {}
            _oh = _ricas.get('odd_home') or fx.get('odd_home')
            _od = _ricas.get('odd_draw') or fx.get('odd_draw')
            _oa = _ricas.get('odd_away') or fx.get('odd_away')
            if _oh and _od and _oa:
                casa = _ricas.get('casa') or fx.get('casa', 'ESPN')
                o_espn = {'odd_home': _oh, 'odd_draw': _od, 'odd_away': _oa,
                          'odd_over25': fx.get('odd_over25'),
                          'odd_under25': fx.get('odd_under25'),
                          # línea real de O/U y HÁNDICAP (v65)
                          'ou_linea': _ricas.get('ou_linea'),
                          'odd_over': _ricas.get('odd_over'),
                          'odd_under': _ricas.get('odd_under'),
                          'ah_linea': _ricas.get('ah_linea'),
                          'odd_ah_home': _ricas.get('odd_ah_home'),
                          'odd_ah_away': _ricas.get('odd_ah_away'),
                          'casa_home': casa, 'casa_draw': casa, 'casa_away': casa,
                          # v71: ancla sharp para la calibración de mercado
                          'pin_home': fx.get('odd_home_pin'),
                          'pin_draw': fx.get('odd_draw_pin'),
                          'pin_away': fx.get('odd_away_pin')}
            # v71 — VALOR DE MERCADO: una casa blanda pagando por encima del
            # precio justo de Pinnacle. Es edge de baja varianza y no depende
            # de que el modelo acierte más que el mercado, solo de que dos
            # casas discrepen. Requiere 2+ casas: con solo Pinnacle+DraftKings
            # no salía ninguna; con Bovada aparecen.
            try:
                import cuotas_multi as _cmv
                _vm = _cmv.valor_vs_sharp('futbol', fx['home'], fx['away'],
                                          odds_espn=fx)
                for _v in (_vm.get('valor') or [])[:2]:
                    _etq = {'home': f'Gana {home}', 'draw': 'Empate',
                            'away': f'Gana {away}'}.get(_v['lado'])
                    if not _etq or _v['cuota'] <= MIN_CUOTA:
                        continue
                    _t = {
                        **base, 'mercado': '1X2', 'apuesta': _etq,
                        'prob': round(_v['prob_justa'], 3),
                        'cuota': _v['cuota'], 'cuota_justa': _v['cuota_justa'],
                        'ev': _v['ev'], 'casa': _v['casa'],
                        'valor': '🟢', 'evc': True, 'valor_mercado': True,
                        'pinnacle': _v.get('pinnacle'),
                        'origen': 'line shopping vs Pinnacle'}
                    # -------------------------------------------------------
                    # v80 — ESTOS PICKS SON HOY TODA LA CAPA 1, Y NADIE LOS
                    # HABÍA MEDIDO NUNCA.
                    #
                    # Se añadían directos a `elite_fix`: sin pasar por
                    # `_mercados_del_partido` (por eso jamás se calibraban) y
                    # **sin pasar por `pasa_capa1`** (por eso salían con
                    # probabilidad de 20-40 %). De ahí lo que se veía en la
                    # interfaz: «Empate · EV +9,5 % · prob 29 %» presentado
                    # como pick de élite.
                    #
                    # Medidos por fin sobre las 26.647 filas del ledger que
                    # tienen precio tomable Y cuota de Pinnacle, la estrategia
                    # SÍ tiene edge —y del bueno—, pero solo con el filtro
                    # correcto. Partiendo el histórico en 70 % para elegir y
                    # 30 % para validar:
                    #
                    #   config              70 % (elige)      30 % (valida)
                    #   margen 1 %, sin pmin  p5 +4,48 %        p5 −0,29 %
                    #   margen 3 %, sin pmin  p5 +3,88 %        p5 −5,67 %
                    #   margen 5 %, sin pmin  p5 +4,66 %        p5 −7,57 %
                    #   margen 1 % + p≥30 %   p5 +3,92 %        p5 **+3,91 %**
                    #
                    # Dos lecciones en esa tabla. La primera: subir el margen
                    # de EV parecía lo obvio —el máximo del barrido estaba en
                    # el 10 % con p5 +10,09 %— y fuera de muestra se hunde a
                    # −9,44 %. Es el máximo del barrido, nada más. La segunda:
                    # lo que da robustez es el **piso de probabilidad**, no el
                    # margen. Y encaja con lo que se veía: los picks al 20-29 %
                    # son los que arrastran el resultado.
                    #
                    # Con margen 1 % y probabilidad ≥ 30 % el p5 sale casi
                    # idéntico en los dos periodos (+3,92 % y +3,91 %) sobre
                    # 3.009 y 1.309 apuestas. Esa estabilidad es la señal.
                    #
                    # Lo que no pasa el filtro NO se tira: baja a candidatos
                    # con su motivo, igual que se hace con el resto.
                    # -------------------------------------------------------
                    if _v['prob_justa'] >= VS_PROB_MIN and _v['ev'] >= VS_EV_MIN:
                        elite_fix.append(_t)
                    else:
                        _t['valor'] = '🟡'
                        _t['evc'] = False
                        _t['motivo_fuera'] = (
                            f"valor sobre Pinnacle pero probabilidad "
                            f"{_v['prob_justa']:.0%} < {VS_PROB_MIN:.0%}"
                            if _v['prob_justa'] < VS_PROB_MIN else
                            f"valor sobre Pinnacle pero EV {_v['ev']:.1%} < "
                            f"{VS_EV_MIN:.1%}")
                        candidatos_fix.append(_t)
            except Exception as e:
                logger.debug(f"[alpha] valor de mercado omitido: {e}")

            if o_espn:
                for c in _mercados_del_partido(pred, o_espn, home, away, clave):
                    tarjeta = {**base, **c, 'deporte': 'Fútbol',
                               'valor': ('🟢' if c['ev'] > 0.05 else
                                         '🟡' if c['ev'] > 0 else '🔴')}
                    pasa = pasa_capa1(c['prob'], c['ev'], c['cuota'], clave)
                    if pasa and c['mercado'] in MERCADOS_VALIDADOS_CAPA1:
                        tarjeta['evc'] = True
                        elite_fix.append(tarjeta)
                    elif c['ev'] > 0:
                        candidatos_fix.append(tarjeta)
            else:
                # sin cuota real → Capa 2 con el modelo (cuota justa)
                if mejor['prob'] >= CONF_CAPA2:
                    capa2_futbol.append({**pron, 'valor': '🎯'})
                for m in mercados:
                    if m['mercado'] in ('BTTS', 'Goles') and m['prob'] >= 0.62:
                        capa2_futbol.append({**base, **m, 'sin_cuota': True,
                                             'valor': '🎯'})
        # v89: liberar el motor que cargó este pase — cada liga se procesa una
        # sola vez y retener ~32 motores era el patrón de memoria de la v86.
        if clave not in _precargados:
            motores.pop(clave, None)
    _pool_odds.shutdown(wait=False)
    logger.info(f"[alpha/fix] fixtures evaluados={n_eval} · elite={len(elite_fix)} "
                f"· candidatos={len(candidatos_fix)} · capa2={len(capa2_futbol)} "
                f"· pronósticos={len(pronosticos)}")
    return (elite_fix, candidatos_fix, capa2_futbol, pronosticos,
            cobertura, n_eval)


# ---------------------------------------------------------------------------
# v31 (§1/§5): bucle dinámico universal + doble capa
#   Capa 1 «EVC Platino»: hay CUOTA REAL y pasa los filtros de élite.
#   Capa 2 «Alta Confianza»: SIN cuota real y confianza > 75 % → se sugiere
#   la cuota mínima (1/prob). Sin stake (no hay EV real).
# ---------------------------------------------------------------------------
# v33 (§2): umbrales adaptativos por deporte, centralizados en config.py
try:
    from config import UMBRALES_DEPORTE
except ImportError:
    UMBRALES_DEPORTE = {}
CONF_CAPA2 = UMBRALES_DEPORTE.get('Fútbol', {}).get('capa2', 0.75)
UMBRAL_CONF = {d: u['capa1'] for d, u in UMBRALES_DEPORTE.items()} or \
    {'MLB': 0.58, 'Tenis': 0.65, 'NBA': 0.70}


def umbral(deporte: str, capa: str = 'capa1') -> float:
    """Umbral de confianza del deporte (§2)."""
    por_defecto = {'capa1': 0.70, 'capa2': 0.75}[capa]
    return UMBRALES_DEPORTE.get(deporte, {}).get(capa, por_defecto)


def indicador_antiguedad(dias: Optional[int]) -> str:
    """§5: semáforo de frescura de los datos de la liga."""
    if dias is None:
        return ''
    if dias < 3:
        return f'🟢 datos de hace {dias} d'
    if dias <= 7:
        return f'🟡 datos de hace {dias} d'
    return f'🔴 sin datos nuevos desde hace {dias} d'


def _picks_mlb() -> Dict[str, List[Dict]]:
    """
    MLB con la capa de cuotas sin límite (Pinnacle + Bovada + Playdoit).

    v77: hasta ahora dependía de The Odds API y, con la cuota mensual a 0, la
    MLB desaparecía del barrido **sin que nadie lo viera**: el motor cargaba
    bien, devolvía cero picks con un aviso interno y ese aviso no llegaba a
    ninguna parte. Ahora las incidencias suben hasta la interfaz.
    """
    try:
        from engines.mlb_engine import MLBEngine
        eng = MLBEngine().cargar_modelo()
        if not eng.listo:
            return {'capa1': [], 'capa2': [],
                    'incidencias': ['MLB: el modelo no está disponible.']}
        r = eng.apuestas_dia(min_prob=UMBRAL_CONF['MLB'])
        capa1 = [{**p, 'liga': 'MLB', 'mercado': 'Moneyline',
                  'valor': p.get('valor', '🟡')} for p in r.get('picks', [])]
        inc = list(r.get('incidencias') or [])

        # v83 — VALOR DE MERCADO EN MLB (no usa el modelo). Ver `VS_MLB_*`.
        #
        # El modelo de MLB no bate al mercado y por eso está fuera de la Capa 1,
        # pero esta estrategia no lo necesita: apuesta donde una casa se queda
        # descolgada. Medido sobre 27.977 juegos con apertura y cierre, con 16
        # de 20 configuraciones positivas en los dos periodos de validación.
        try:
            import cuotas_multi as _cmm
            from engines.mlb_engine import (codigo_mlb as _cmlb,
                                            es_partido_mlb as _es_mlb,
                                            CODIGO_A_NOMBRE)
            _vistos = set()
            _no_mlb = 0
            for _idx in (_cmm._indice('mlb'), _cmm._indice_bov('mlb'),
                         _cmm._indice_pdt('mlb')):
                for _v0 in (_idx or {}).values():
                    if not (_v0.get('home') and _v0.get('away')):
                        continue
                    # v88 — SÓLO MLB. El tablón trae LMB, NPB, KBO, CPBL y
                    # Triple-A. Sin este filtro llegaban a la Capa 1 partidos
                    # de la CPBL de Taiwán etiquetados «MLB», y por duplicado
                    # (los nombres desconocidos no colapsan en la clave). El
                    # edge de esta vía se midió sobre 27.977 juegos DE MLB;
                    # operar otras ligas con él es extrapolar.
                    if not _es_mlb(_v0['home'], _v0['away']):
                        _no_mlb += 1
                        continue
                    _cl = (_cmlb(_v0['home']), _cmlb(_v0['away']))
                    if _cl in _vistos:
                        continue
                    _vistos.add(_cl)
                    _vm = _cmm.valor_vs_sharp('mlb', _v0['home'], _v0['away'])
                    for _v in (_vm.get('valor') or [])[:1]:
                        if not (_v.get('prob_justa', 0) >= VS_MLB_PROB_MIN
                                and _v.get('ev', 0) >= VS_MLB_EV_MIN
                                and _v.get('cuota', 0) > MIN_CUOTA):
                            continue
                        _lado = _v.get('lado')
                        _cod = _cl[0] if _lado == 'home' else _cl[1]
                        _nom = CODIGO_A_NOMBRE.get(
                            _cod, _v0['home'] if _lado == 'home' else _v0['away'])
                        capa1.append({
                            'deporte': 'MLB', 'liga': 'MLB',
                            'clave_liga': 'mlb',
                            'partido': f"{CODIGO_A_NOMBRE.get(_cl[1], _v0['away'])}"
                                       f" @ {CODIGO_A_NOMBRE.get(_cl[0], _v0['home'])}",
                            'fecha': str(hoy_utc().date()),
                            'mercado': 'Moneyline', 'apuesta': f'Gana {_nom}',
                            'prob': round(_v['prob_justa'], 3),
                            'cuota': _v['cuota'],
                            'cuota_justa': _v.get('cuota_justa'),
                            'ev': _v['ev'], 'casa': _v.get('casa'),
                            'valor': '🟢', 'evc': True, 'valor_mercado': True,
                            'pinnacle': _v.get('pinnacle'),
                            'origen': 'line shopping vs Pinnacle'})
            # v91 — UNA sola línea de estado en vez de tres solapadas. Que el
            # tablón traiga LMB/NPB/KBO y se filtren es OPERACIÓN NORMAL, no
            # una incidencia: se degrada al log. El usuario ve un ✅ con los
            # números que importan.
            _n_vs = sum(1 for p in capa1 if p.get('valor_mercado'))
            if _no_mlb:
                logger.info(f'[alpha/mlb] {_no_mlb} entradas del tablón no-MLB '
                            f'filtradas (LMB/NPB/KBO/CPBL/AAA) — normal.')
            inc.append(
                f'✅ MLB operativa: {r.get("eventos", len(_vistos))} partidos '
                f'con cuota, {r.get("evaluados", 0)} evaluados por el modelo y '
                f'{len(_vistos)} comparados contra Pinnacle → {len(capa1)} '
                f'picks hoy'
                + (f' ({_n_vs} por valor de mercado).' if _n_vs else
                   '. Cero picks = las casas coinciden y el modelo no ve EV '
                   'suficiente — es el sistema no forzando apuestas, no un '
                   'fallo.'))
        except Exception as e:
            logger.debug(f'[alpha/mlb] valor de mercado omitido: {e}')
            inc.append(f'⚠️ MLB: valor de mercado no evaluado '
                       f'({type(e).__name__}).')
        # v91 — la MLB aporta CAPA 2. Los favoritos claros con cuota real que
        # no pasan los filtros de élite (casi siempre por cuota corta) son el
        # material de «Máxima Confianza»; antes se descartaban dentro del
        # motor y la MLB no aparecía nunca en esa pestaña.
        _conf = [{**p, 'deporte': 'MLB'} for p in (r.get('confianza') or [])]
        return {'capa1': capa1, 'capa2': _conf, 'incidencias': inc}
    except Exception as e:
        # v88 — se registra la TRAZA. «MLB omitido por error: OSError» sin más
        # obliga a adivinar dónde falló, y este proyecto ya ha perdido tiempo
        # con fallos silenciosos que sólo dejaban el nombre de la excepción.
        logger.warning(f"[alpha] MLB omitido: {type(e).__name__}: {e}\n"
                       + traceback.format_exc())
        return {'capa1': [], 'capa2': [],
                'incidencias': [f'MLB omitido por error: {type(e).__name__}: {e}']}


def _cuotas_tenis_multi() -> List[Dict]:
    """
    v72 — partidos de tenis con cuota desde Pinnacle y Bovada, en el mismo
    formato que esperaba la cadena de resiliencia
    (`home`, `away`, `odd_home`, `odd_away`, `circuito`).

    El circuito se deduce del nombre del torneo que publica la casa: los ITF y
    challengers femeninos y los WTA llevan marca explícita; el resto se trata
    como ATP, que es el motor por defecto (y si el emparejado falla,
    `_picks_tenis` ya reintenta con el otro motor).
    """
    try:
        import cuotas_multi as cm
    except Exception:
        return []
    salida, vistos = [], set()
    # v73 — dedup por APELLIDOS, no por nombre completo. Pinnacle escribe
    # «Martin Damm» y Bovada «Martin Damm Jr»; «Andres Andrade» y «Andrés
    # Andrade (PAN)». Como la clave era el nombre normalizado completo, el
    # mismo partido entraba dos veces y salía duplicado en la Capa 2.
    def _clave_par(h, a):
        ap = sorted((cm._clave_tenista(h)[0], cm._clave_tenista(a)[0]))
        return '|'.join(ap)

    for idx in (cm._indice('tenis'), cm._indice_bov('tenis')):
        for v in (idx or {}).values():
            c = v.get('cuotas') or {}
            oh, oa = c.get('home'), c.get('away')
            if not oh or not oa:
                continue
            # DOBLES fuera. Las casas los publican con los dos nombres
            # separados por «/» y el modelo del proyecto es de INDIVIDUALES.
            # Sin este filtro el emparejado difuso casaba una pareja con un
            # jugador suelto y salían picks absurdos: «Sara Errani / Nicole
            # Melichar → Gana Katie Boulter» con EV +210 %.
            if '/' in v['home'] or '/' in v['away']:
                continue
            # v95 — FUERA LAS CUOTAS QUE NO SON APUESTAS.
            #
            # El tablón trae precios de 1.00 y 1.01 en favoritos extremos de
            # ITF. Una cuota de 1.00 devuelve el importe y nada más: no es una
            # apuesta, es ruido que además salía en la interfaz como «prob
            # 96 %, EV +0,0 %», que parece una oportunidad y no lo es.
            if min(float(oh), float(oa)) <= CUOTA_MINIMA_REAL:
                continue
            # v95 — ITF FUERA DEL BARRIDO, y con motivo.
            #
            # Los 182 partidos que salían como «con cuota, sin modelo propio»
            # eran casi todos ITF. No es un descuido del catálogo: **no existe
            # fuente gratuita de resultados de ITF**. Comprobado sobre el
            # scoreboard de ESPN, que es el que alimenta el histórico de tenis:
            # 785 partidos en 15 días, 13 torneos, **0 de ITF** (sí cubre
            # challengers: Iasi, Praga, Memphis, VanOpen).
            #
            # Sin resultados no hay entrenamiento posible, y sin modelo lo
            # único que se podía enseñar era la probabilidad implícita del
            # precio — o sea, repetirle al usuario lo que ya dice la casa.
            # Mejor no ofrecer el circuito que ofrecerlo sin nada detrás.
            if 'ITF' in (v.get('liga') or '').upper():
                continue
            clave = _clave_par(v['home'], v['away'])
            if clave in vistos:
                continue
            vistos.add(clave)
            liga = (v.get('liga') or '')
            circuito = 'wta' if ('women' in liga.lower() or 'wta' in liga.lower()
                                 or '(w)' in liga.lower()) else 'atp'
            salida.append({'home': v['home'], 'away': v['away'],
                           'odd_home': oh, 'odd_away': oa,
                           'circuito': circuito, 'torneo': liga,
                           'casa': v.get('casa')})
    logger.info(f"[alpha/tenis] {len(salida)} partidos con cuota "
                f"(Pinnacle + Bovada)")
    return salida


def _picks_tenis() -> Dict[str, List[Dict]]:
    """Tenis ATP **y WTA** (v35 §1.4).

    Cadena de resiliencia de cuotas (principio transversal v33):
      1. The Odds API — claves por torneo tennis_atp_*/tennis_wta_*,
         descubiertas dinámicamente (0 créditos si no hay torneo en curso);
      2. Betexplorer — página /next/tennis/ (ATP y WTA).
    Cada circuito usa SU modelo (modelos/tennis y modelos/tennis_wta).
    """
    salida = {'capa1': [], 'capa2': [], 'no_enlazados': [], 'parlay_legs': []}
    try:
        import betexplorer_scraper as bx
        import source_resilience as sr
        from engines.tennis_engine import TennisEngine

        motores = {}
        for circuito in ('atp', 'wta'):
            try:
                eng = TennisEngine(circuito).cargar_modelo()
                if eng.listo:
                    motores[circuito] = eng
            except Exception as e:
                logger.warning(f"[alpha] tenis {circuito}: {type(e).__name__}: {e}")
        if not motores:
            return salida

        # v72 — el tenis entero caía a Capa 2 «sin cuota en vivo» aunque
        # hubiera cuotas de sobra. Motivo: los dos eslabones de esta cadena
        # están muertos — The Odds API con la cuota mensual agotada y
        # Betexplorer sirviendo HTML puramente JS. Se antepone `cuotas_multi`,
        # que trae ~252 partidos de tenis de Pinnacle y ~274 de Bovada sin
        # límite de peticiones.
        # v88: se retira el eslabón de The Odds API — la clave devuelve 401 en
        # todas las ligas y sólo servía para ensuciar los logs. Quedan las dos
        # fuentes que sí responden.
        cadena = sr.Cadena('cuotas de tenis', [
            ('Pinnacle/Bovada', _cuotas_tenis_multi),
            ('Betexplorer', lambda: bx.cuotas_tenis_hoy()),
        ])
        partidos = cadena.obtener(validador=lambda d: d) or []
        for m in partidos:
            circuito = m.get('circuito', 'atp')
            eng = motores.get(circuito) or motores.get('atp')
            j1 = bx.emparejar_jugador(m['home'], eng.jugadores)
            j2 = bx.emparejar_jugador(m['away'], eng.jugadores)
            if not (j1 and j2) and len(motores) > 1:
                # el circuito puede venir mal etiquetado por la fuente: se
                # intenta con el otro motor antes de darlo por no enlazado
                otro = motores['wta' if eng.circuito == 'atp' else 'atp']
                a1 = bx.emparejar_jugador(m['home'], otro.jugadores)
                a2 = bx.emparejar_jugador(m['away'], otro.jugadores)
                if a1 and a2:
                    eng, j1, j2 = otro, a1, a2
            if not (j1 and j2):
                # v91 — el partido sin modelo YA NO se pierde en una lista de
                # texto: sale como tarjeta con su cuota real y la probabilidad
                # implícita del precio (devigada). El usuario pidió que todo lo
                # que tenga precio tenga tarjeta; la etiqueta dice honestamente
                # que ahí no hay predicción propia (jugador fuera del catálogo,
                # típico en challengers/ITF).
                salida['no_enlazados'].append(f"{m['home']} vs {m['away']}")
                try:
                    oh, oa = float(m['odd_home']), float(m['odd_away'])
                    imp_h = (1 / oh) / (1 / oh + 1 / oa)
                except (TypeError, ValueError, ZeroDivisionError):
                    oh = oa = imp_h = None
                if oh and oa:
                    fav_home = imp_h >= 0.5
                    salida.setdefault('sin_modelo', []).append({
                        'deporte': 'Tenis',
                        'liga': (m.get('torneo') or
                                 m.get('circuito', 'tenis').upper()),
                        'partido': f"{m['home']} vs {m['away']}",
                        'fecha': str(hoy_utc().date()),
                        'mercado': 'Ganador',
                        'apuesta': ('Gana ' + (m['home'] if fav_home
                                               else m['away'])),
                        'prob': round(imp_h if fav_home else 1 - imp_h, 3),
                        'cuota': round(oh if fav_home else oa, 2),
                        'cuota_justa': round(1 / max(
                            imp_h if fav_home else 1 - imp_h, 1e-6), 2),
                        'ev': None, 'casa': m.get('casa'),
                        'sin_modelo': True, 'valor': '🏷️',
                        'nota': ('🏷️ Sin predicción propia: jugador fuera del '
                                 'catálogo del modelo. La probabilidad es la '
                                 'implícita del precio de la casa.')})
                continue
            pred = eng.predecir(j1, j2)
            if 'error' in pred:
                continue
            # v47: la plantilla ya calcula 19 mercados derivados (ganador,
            # totales de juegos, hándicaps, sets 2-0/2-1, "ambos ganan un
            # set"...). El usuario los pidió expresamente para armar parlays y
            # porque "en tenis no se muestra nada". Se calculan UNA vez por
            # partido y se adjuntan a las tarjetas; los mejores legs alimentan
            # el "Parlay del día de tenis".
            superficie = m.get('surface') or m.get('superficie') or 'Hard'
            try:
                pl = eng.plantilla(j1, j2, surface=superficie)
                mercados = [c for c in pl.get('campos', [])]
            except Exception as e:
                logger.warning(f"[alpha] plantilla tenis {m['home']}: {e}")
                mercados = []
            # legs candidatos a parlay: mercados con prob en [55%, 88%] (ni
            # trivial ni arriesgado), ordenados por confianza. Se etiquetan con
            # el partido y su cuota justa (1/prob) para combinar.
            for c in mercados:
                pr = c['valor'] / 100.0
                if 0.55 <= pr <= 0.90:
                    salida['parlay_legs'].append({
                        'partido': f"{m['home']} vs {m['away']}",
                        'circuito': eng.circuito.upper(),
                        'mercado': c['etiqueta'], 'prob': round(pr, 3),
                        'cuota_justa': round(1 / max(pr, 1e-6), 2)})
            # v78 — ENCOGIMIENTO HACIA EL MERCADO también en tenis. Hasta la
            # v77 solo se corregía el fútbol, así que los EV de tenis salían
            # sin corregir. Medido sobre 46.210 partidos fuera de muestra con
            # cuota real: encoger mejora la precisión de 65,9 % a 68,3 % y la
            # log-loss de 0,6105 a 0,5842. ATP y WTA adoptan w=0,25 con
            # muestras de 30.327 y 15.883 partidos.
            #
            # v79 — se pasa por `calibracion_segura`. El import directo de
            # `calibracion_mercado` tumbó el barrido entero de tenis en
            # producción con un AttributeError, porque Streamlit conservaba en
            # `sys.modules` el módulo de la v77 mientras este fichero ya era el
            # de la v78. Ver el docstring de `calibracion_segura`.
            import calibracion_segura as _cal
            _ph, _info_cal = _cal.encoger_dos_vias(
                pred['prob_home'], m.get('odd_home'), m.get('odd_away'),
                eng.circuito.lower())
            _probs = {'home': _ph, 'away': 1.0 - _ph}

            # -------------------------------------------------------------
            # v82 — VALOR DE MERCADO EN TENIS (no usa el modelo).
            #
            # Ver `VS_TENIS_*` arriba: medido sobre 24.594 partidos WTA con
            # Pinnacle y mejor precio, con elección y validación en periodos
            # distintos, la estrategia da p5 +1,70 % y +4,22 %/+0,61 %. El ATP
            # no pasa la validación y queda fuera a propósito.
            #
            # Estos picks NO dependen de que el modelo de tenis acierte, así
            # que el veto por «deporte sin edge» —que es un juicio sobre el
            # MODELO— no debe aplicárseles. Se marcan con `valor_mercado` para
            # que el filtro los deje pasar, igual que en fútbol.
            # -------------------------------------------------------------
            if eng.circuito.lower() in VS_TENIS_CIRCUITOS:
                try:
                    import cuotas_multi as _cmt
                    _vt = _cmt.valor_vs_sharp('tenis', m['home'], m['away'])
                    for _v in (_vt.get('valor') or [])[:1]:
                        _lado = _v.get('lado')
                        _nom = m['home'] if _lado == 'home' else m['away']
                        if (_v.get('prob_justa', 0) >= VS_TENIS_PROB_MIN
                                and _v.get('ev', 0) >= VS_TENIS_EV_MIN
                                and _v.get('cuota', 0) > MIN_CUOTA):
                            salida['capa1'].append({
                                'deporte': 'Tenis',
                                'liga': eng.circuito.upper(),
                                'clave_liga': eng.circuito.lower(),
                                'partido': f"{m['home']} vs {m['away']}",
                                'fecha': str(hoy_utc().date()),
                                'mercado': 'Ganador',
                                'apuesta': f'Gana {_nom}',
                                'prob': round(_v['prob_justa'], 3),
                                'cuota': _v['cuota'],
                                'cuota_justa': _v.get('cuota_justa'),
                                'ev': _v['ev'], 'casa': _v.get('casa'),
                                'valor': '🟢', 'evc': True,
                                'valor_mercado': True,
                                'pinnacle': _v.get('pinnacle'),
                                'superficie': superficie,
                                'origen': 'line shopping vs Pinnacle'})
                except Exception as e:
                    logger.debug(f'[alpha/tenis] valor de mercado omitido: {e}')

            for lado, nombre, prob, cuota in (
                    ('home', m['home'], _probs['home'], m['odd_home']),
                    ('away', m['away'], _probs['away'], m['odd_away'])):
                ev = round(cuota * prob - 1, 4)
                base = {'deporte': 'Tenis', 'liga': eng.circuito.upper(),
                        'partido': f"{m['home']} vs {m['away']}",
                        'fecha': str(hoy_utc().date()),
                        'mercado': 'Ganador', 'apuesta': f'Gana {nombre}',
                        'prob': round(prob, 3),
                        'superficie': superficie,
                        'mercados_tenis': mercados,   # v47: 19 mercados
                        'calibracion': _info_cal,     # v78: w aplicado
                        'cuota_justa': round(1 / max(prob, 1e-6), 2)}
                if prob > UMBRAL_CONF['Tenis'] and ev > MIN_EV and cuota > MIN_CUOTA:
                    salida['capa1'].append({**base, 'cuota': round(cuota, 2),
                                            'ev': ev, 'casa': m.get('casa'),
                                            'valor': '🟢' if ev > 0.05 else '🟡'})
                elif prob > CONF_CAPA2:
                    # v73 — la Capa 2 TIRABA LA CUOTA. Un partido con precio
                    # real que no pasaba los filtros de élite acababa aquí con
                    # `cuota: None`, y la UI lo rotulaba «sin cuota en vivo»,
                    # que es falso: la cuota existe, lo que no llega es el
                    # filtro. Caso típico: un favorito al 86 % pagado a 1.10,
                    # por debajo del mínimo de 1.50.
                    #
                    # Ahora la cuota real viaja a la Capa 2 y se dice POR QUÉ
                    # no es Capa 1, que es información accionable: si el
                    # motivo es «cuota baja», el usuario sabe que solo le
                    # interesa si su casa paga bastante más.
                    if cuota <= MIN_CUOTA:
                        motivo = (f'cuota {cuota:.2f} por debajo del mínimo '
                                  f'{MIN_CUOTA:.2f}')
                    elif ev <= MIN_EV:
                        motivo = f'EV {ev:+.1%} por debajo del mínimo'
                    else:
                        motivo = 'no alcanza el umbral de confianza de élite'
                    salida['capa2'].append({
                        **base, 'cuota': round(cuota, 2), 'ev': ev,
                        'casa': m.get('casa'), 'motivo_capa2': motivo,
                        'valor': '🎯'})
    except Exception as e:
        logger.warning(f"[alpha] tenis omitido: {type(e).__name__}: {e}")
    return salida


def _picks_nba() -> Dict[str, List[Dict]]:
    """NBA (v34 §4): cuotas reales EN CUANTO arranque la temporada. Fuera de
    temporada (julio) ninguna fuente devuelve partidos y no se consulta nada."""
    salida = {'capa1': [], 'capa2': []}
    try:
        import betexplorer_scraper as bx
        import source_resilience as sr

        # v88 — la ventana de temporada vivía en `odds_api`, que se retira. Se
        # declara aquí: la NBA va de octubre a junio.
        _m = hoy_utc().month
        if not (_m >= 10 or _m <= 6):
            logger.info("[alpha] NBA fuera de temporada: barrido omitido.")
            return salida

        # v88: el eslabón de The Odds API se retira (401 en todas las ligas).
        # Pinnacle y Bovada cubren la NBA vía `cuotas_multi` en cuanto arranca
        # la temporada — medido: 57 partidos de NBA en el tablón de Pinnacle.
        def _de_cuotas_multi():
            import cuotas_multi as _cm
            out = []
            for idx in (_cm._indice('nba'), _cm._indice_bov('nba')):
                for v in (idx or {}).values():
                    c = v.get('cuotas') or {}
                    if v.get('home') and v.get('away') and \
                            c.get('home') and c.get('away'):
                        out.append({'home': v['home'], 'away': v['away'],
                                    'odd_home': c['home'], 'odd_away': c['away']})
            return out

        cadena = sr.Cadena('cuotas NBA', [('Pinnacle/Bovada', _de_cuotas_multi),
                                          ('Betexplorer', bx.cuotas_baloncesto_hoy)])
        partidos = cadena.obtener(lambda d: d is not None and len(d) > 0) or []
        if not partidos:
            return salida
        from engines.nba_engine import NBAEngine
        eng = NBAEngine().cargar_modelo()
        if not eng.listo:
            return salida
        for m in partidos:
            pred = eng.predecir(m['home'], m['away'])
            if 'error' in pred:
                continue
            for nombre, prob, cuota in ((m['home'], pred['prob_home'], m['odd_home']),
                                        (m['away'], pred['prob_away'], m['odd_away'])):
                ev = round(cuota * prob - 1, 4)
                base = {'deporte': 'NBA', 'liga': 'NBA',
                        'partido': f"{m['home']} vs {m['away']}",
                        'fecha': str(hoy_utc().date()),
                        'mercado': 'Moneyline', 'apuesta': f'Gana {nombre}',
                        'prob': round(prob, 3),
                        'cuota_justa': round(1 / max(prob, 1e-6), 2)}
                if prob > UMBRAL_CONF['NBA'] and ev > MIN_EV and cuota > MIN_CUOTA:
                    salida['capa1'].append({**base, 'cuota': round(cuota, 2),
                                            'ev': ev, 'valor': '🟢'})
                elif prob > CONF_CAPA2:
                    salida['capa2'].append({**base, 'cuota': None, 'ev': None,
                                            'valor': '🎯'})
    except Exception as e:
        logger.warning(f"[alpha] NBA omitido: {type(e).__name__}: {e}")
    return salida


# ---------------------------------------------------------------------------
# v32: fiabilidad histórica (Brier real de los picks publicados por liga),
# cuarentena de pretemporada y segregación de EV extremo.
# ---------------------------------------------------------------------------
# v38: el umbral de EV extremo lo fija el MOTOR DE RENTABILIDAD (edge_engine),
# calibrado por maximin walk-forward sobre 2.846 apuestas reales. La banda
# rentable validada es EV ∈ [3 %, 14 %]; por encima del tope, el histórico da
# −10 % de ROI (descalibración del modelo en los extremos). Fallback 0.15.
try:
    import edge_engine
    _BANDA = edge_engine.banda_rentable()
    EV_EXTREMO = _BANDA[1]
except Exception:
    EV_EXTREMO = 0.15
_FIABILIDAD: Dict[str, float] = {}


def fiabilidad_liga(liga: str) -> Optional[float]:
    """Brier score REAL de los picks que el sistema publicó en esa liga
    (roi_bets_{liga}.json: prob prometida vs resultado). None si no hay datos."""
    if not _FIABILIDAD:
        import glob
        for ruta in glob.glob('roi_bets_*.json'):
            clave = ruta[len('roi_bets_'):-len('.json')]
            try:
                with open(ruta, encoding='utf-8') as f:
                    bets = json.load(f)
                if len(bets) >= 30:
                    _FIABILIDAD[clave] = round(float(np.mean(
                        [(b['prob'] - b['gano']) ** 2 for b in bets])), 4)
            except Exception:
                continue
        _FIABILIDAD.setdefault('_vacio', 1.0)
    return _FIABILIDAD.get(liga)


def etiqueta_fiabilidad(brier: Optional[float]) -> str:
    """Traducción UX del Brier (§5.2)."""
    if brier is None:
        return '⚪ Sin histórico'
    if brier < 0.15:
        return '🟢 Fiabilidad élite'
    if brier < 0.22:
        return '🟡 Fiabilidad estándar'
    return '🔴 Alta incertidumbre'


_PRECISION_MODELO: Dict[str, Optional[float]] = {}


def _precision_modelo(clave: str) -> Optional[float]:
    """v52: precisión de VALIDACIÓN (backtest walk-forward) del modelo de una
    liga/deporte, leída de modelos/{clave}/metadata.json. Es el respaldo del
    semáforo de fiabilidad cuando aún NO hay histórico de picks publicados
    (evita el '⚪ Sin histórico' vacío: siempre hay dato del backtest)."""
    if clave in _PRECISION_MODELO:
        return _PRECISION_MODELO[clave]
    import os
    val = None
    for sub in (clave, {'atp': 'tennis', 'wta': 'tennis_wta',
                        'tenis': 'tennis'}.get(clave, clave)):
        ruta = os.path.join('modelos', sub, 'metadata.json')
        if os.path.exists(ruta):
            try:
                with open(ruta, encoding='utf-8') as f:
                    val = json.load(f).get('precision_validacion')
                if val:
                    break
            except Exception:
                continue
    _PRECISION_MODELO[clave] = val
    return val


def fiabilidad_label(clave: str, brier: Optional[float]) -> str:
    """v52: etiqueta de fiabilidad con respaldo del backtest del modelo. Si hay
    histórico de picks (Brier) usa el semáforo; si no, muestra la precisión
    validada del modelo — nunca deja la celda vacía."""
    if brier is not None:
        return etiqueta_fiabilidad(brier)
    prec = _precision_modelo(clave)
    if prec:
        icono = '🟢' if prec >= 0.55 else ('🟡' if prec >= 0.50 else '🔵')
        return f'{icono} Modelo {prec*100:.0f}% (backtest)'
    return '⚪ Sin histórico'


DIAS_ESTADO_OBSOLETO = 45


def _dias_estado_obsoleto(liga: str, fecha: str) -> Optional[int]:
    """§4 (cuarentena): días transcurridos desde el último partido con el que
    se entrenó la liga. Un desfase grande significa PRETEMPORADA (ligas
    europeas en julio) o simplemente estado sin refrescar: en ambos casos la
    varianza sube y el pick baja a Capa 2. Regla dirigida por datos."""
    try:
        with open(f'team_stats_{liga}.json', encoding='utf-8') as f:
            ultima = json.load(f).get('ultima_fecha_historico')
        if not ultima:
            return None
        return int((pd.Timestamp(fecha) - pd.Timestamp(ultima)).days)
    except Exception:
        return None


def prob_calibrada(p: Dict) -> float:
    """
    Probabilidad de que ESTA apuesta se acierte, corregida por lo que su
    mercado y su banda aciertan DE VERDAD.

    v93 — el sistema mostraba la probabilidad del modelo y ordenaba por EV.
    Medido sobre los primeros 142 picks liquidados en producción (v92-v93), la
    diferencia entre lo que se promete y lo que pasa no es uniforme, es
    ENORME y depende del mercado:

        mercado    n    promete   acierta   brecha
        Ganador   58     77,2 %    70,7 %   −6,5 pp
        1X2       27     48,1 %    40,7 %   −7,4 pp
        Goles     29     69,7 %    51,7 %  −18,0 pp
        BTTS      22     69,7 %    50,0 %  −19,7 pp

    Coincide con lo que el backtest ya decía sobre 89.748 predicciones (v86:
    el BTTS promete 80 % y acierta 53 %), así que no es ruido de muestra
    pequeña: son dos mediciones independientes apuntando a lo mismo.

    La consecuencia práctica es que ordenar por probabilidad del modelo pone
    arriba justo los mercados que peor cumplen. Esta función devuelve la
    probabilidad que ya está medida (`calibracion_confianza`) y, donde no hay
    medición, la del modelo sin inflar.
    """
    prob = float(p.get('prob') or 0)
    try:
        import calibracion_confianza as _cc
        real = _cc.probabilidad_real(prob, p.get('mercado'))
        if real is not None:
            return float(real)
    except Exception:
        pass
    return prob


def pick_del_dia(picks: List[Dict]) -> Optional[Dict]:
    """
    UN solo pick: el que TIENE MÁS PROBABILIDAD DE ACERTARSE.

    v93 — cambia el criterio de selección, no los filtros. Antes se ordenaba
    por Brier de la liga y EV, con lo que un pick de BTTS al «80 %» que en
    realidad acierta el 50 % podía salir por delante de uno de 1X2 al 72 %
    que acierta el 70 %. El usuario pide lo contrario: la apuesta más probable
    de acertar. Ahora manda `prob_calibrada` (ver ahí los números) y el EV
    queda de desempate — sigue exigiéndose que sea positivo y esté dentro de
    la banda validada, así que no se recomienda nada con valor esperado malo.
    """
    aptos = []
    for p in picks:
        ev = p.get('ev')
        if ev is None or not (0.02 <= ev <= EV_EXTREMO):
            continue
        if (p.get('prob') or 0) <= 0.80 or p.get('pretemporada'):
            continue
        brier = p.get('brier')
        if brier is not None and brier >= 0.22:
            continue
        aptos.append(p)
    if not aptos:
        return None
    mejor = sorted(aptos, key=lambda p: (-prob_calibrada(p),
                                         -(p.get('ev') or 0),
                                         (p.get('brier') if p.get('brier')
                                          is not None else 0.21)))[0]
    q = dict(mejor)
    pc = prob_calibrada(mejor)
    q['prob_calibrada'] = round(pc, 3)
    q['prob_modelo'] = mejor.get('prob')
    if abs(pc - float(mejor.get('prob') or 0)) > 0.005:
        q['nota_calibracion'] = (
            f"El modelo dice {float(mejor.get('prob') or 0)*100:.0f} %; en el "
            f"histórico, los picks de {mejor.get('mercado','este mercado')} en "
            f"esa banda aciertan el {pc*100:.0f} %. Se muestra el segundo, que "
            f"es el que importa.")
    return q


def _seccion_btts(picks: List[Dict]) -> List[Dict]:
    """
    v37 (§6): sección destacada de Ambos Marcan. Picks de BTTS con confianza
    > 60 % y (si hay cuota real) EV > +1 %; sin cuota se muestran con la cuota
    mínima sugerida (1/prob).

    Se MANTIENE (la v43 la pidió expresamente: buen momio y base de parlays) y
    sigue fuera de la Capa 1 accionable, que solo admite 1X2.

    v75 — pero deja de venderse como ventaja del modelo. Medido sobre 15.950
    partidos fuera de muestra (`backtest_btts.py`), el Weibull de BTTS da un
    Brier de 0.24880 frente a 0.24891 de responder siempre la tasa base de la
    liga: no discrimina. La sección se marca con `sin_edge_modelo` para que la
    UI lo diga y el usuario decida sabiendo qué está mirando — lo único que
    puede sostener un pick de BTTS hoy es el PRECIO, no la probabilidad.
    """
    out = []
    for p in picks:
        if str(p.get('mercado', '')).upper() != 'BTTS':
            continue
        if (p.get('prob') or 0) <= 0.60:
            continue
        if p.get('cuota') and (p.get('ev') or 0) <= 0.01:
            continue
        q = dict(p)
        q['sin_edge_modelo'] = True
        out.append(q)
    return sorted(out, key=lambda p: (-(p.get('ev') or 0), -(p.get('prob') or 0)))


def _mejores_patas(picks: List[Dict]) -> List[Dict]:
    """
    v41 (§3.1): patas candidatas para construir PARLAYS seguros — umbrales más
    amplios que Capa 1 (prob ≥ 0.55 y EV > +2 %). No son apuestas simples
    recomendadas: son ladrillos de alta probabilidad para combinar.

    v75 — SE RETIRA EL TRATO DE FAVOR AL BTTS (antes entraba con prob > 60 % y
    EV > +1 %, un listón más bajo que el resto). El privilegio venía de una
    preferencia de producto de la v43, no de una medida. Medido ahora sobre
    **15.950 partidos fuera de muestra de 20 ligas** (`backtest_btts.py`):

        Brier   modelo 0.24880 · tasa base 0.24891 · mercado 0.24559
        LogLoss modelo 0.69077 · tasa base 0.69096 · mercado 0.68427

    El modelo Weibull de BTTS es indistinguible de contestar siempre "la tasa
    base de la liga" (0,0001 de Brier), y peor que lo que el cierre de 1X2 +
    O/U 2.5 ya implica. Combinarlo con el mercado tampoco aporta nada
    (0.24561 vs 0.24559). Es decir: no lleva información.

    Bajarle el listón por eso equivalía a promocionar patas cuya probabilidad
    es la media de la liga disfrazada de predicción, y las patas de un parlay
    multiplican sus errores. El BTTS sigue disponible — pero pasando por el
    mismo rasero que cualquier otro mercado, donde lo que lo sostenga sea el
    precio (line shopping) y no una probabilidad que no discrimina.
    """
    vistos = set()
    out = []
    for p in picks:
        prob = p.get('prob') or 0
        ev = p.get('ev')
        es_btts = str(p.get('mercado', '')).upper() == 'BTTS'
        ok = prob >= 0.55 and (ev is None or ev > 0.02)
        if not ok:
            continue
        clave = (p.get('partido'), p.get('apuesta'))
        if clave in vistos:
            continue
        vistos.add(clave)
        q = dict(p)
        q['btts'] = es_btts
        out.append(q)
    return sorted(out, key=lambda p: (-(p.get('prob') or 0), -(p.get('ev') or 0)))


def _oleadas(picks: List[Dict]) -> Dict[str, List[Dict]]:
    """v37 (§5): plan de ataque temporal — agrupa por fecha del partido.
      🔴 Oleada 1 (hoy): el/los mejores picks de hoy.
      🟡 Oleada 2 (mañana): los mejores del día siguiente.
      📋 Resto: lo demás, colapsable.
    """
    hoy = hoy_utc()
    manana = hoy + pd.Timedelta(days=1)
    o1, o2, resto = [], [], []
    for p in picks:
        try:
            f = pd.Timestamp(p.get('fecha')).normalize()
        except (ValueError, TypeError):
            resto.append(p); continue
        if f <= hoy:
            o1.append(p)
        elif f == manana:
            o2.append(p)
        else:
            resto.append(p)
    clave = lambda p: (-int(p.get('platino', False)), -(p.get('ev') or 0),
                       -(p.get('prob') or 0))
    return {'oleada1': sorted(o1, key=clave), 'oleada2': sorted(o2, key=clave),
            'resto': sorted(resto, key=clave)}


def _construir_parlay_tenis(legs: List[Dict], objetivo_cuota: float = 2.0,
                            max_patas: int = 4) -> Dict:
    """v47: parlay del día de tenis. Elige los mercados derivados más seguros
    (uno por partido para diversificar el riesgo) hasta alcanzar una cuota
    combinada ≈ objetivo. Cuotas justas (1/prob); el usuario compara con su
    casa. Devuelve {} si no hay material suficiente."""
    if not legs:
        return {}
    # el mejor leg por partido (mayor prob), evitando duplicar el mismo evento
    mejor_por_partido: Dict[str, Dict] = {}
    for l in sorted(legs, key=lambda x: -(x.get('prob') or 0)):
        mejor_por_partido.setdefault(l['partido'], l)
    ordenados = sorted(mejor_por_partido.values(), key=lambda x: -(x.get('prob') or 0))
    patas: List[Dict] = []
    cuota_comb = 1.0
    prob_comb = 1.0
    for l in ordenados:
        if len(patas) >= max_patas:
            break
        patas.append(l)
        cuota_comb *= l['cuota_justa']
        prob_comb *= l['prob']
        if cuota_comb >= objetivo_cuota and len(patas) >= 2:
            break
    if len(patas) < 2:
        return {}
    return {'patas': patas, 'n_patas': len(patas),
            'cuota_combinada': round(cuota_comb, 2),
            'prob_conjunta': round(prob_comb, 3),
            'nota': ('Combinación de tenis con los mercados más seguros del día '
                     '(uno por partido). Cuotas justas = 1/probabilidad; '
                     'apuesta solo si tu casa paga MÁS que la combinada.')}


def apuestas_del_dia_universal(max_partidos: int = 40) -> Dict:
    """Barrido de TODAS las competiciones activas (11 de fútbol + MLB, NBA,
    tenis) con clasificación en dos capas (§1.2, §5.1)."""
    # -----------------------------------------------------------------------
    # v79 — LAS CUATRO RAMAS EN PARALELO.
    #
    # Medido con `_v79_diag_barrido.py` sobre el barrido real:
    #
    #     TOTAL                     197,9 s
    #       apuestas_del_dia (fútbol) 117,4 s
    #         └ _barrido_fixtures     112,0 s
    #       _picks_tenis               77,7 s
    #       _picks_mlb                  2,6 s
    #       _picks_nba                  0,0 s
    #
    # Los tiempos SUMAN porque las cuatro ramas corrían una detrás de otra, y
    # sin embargo son independientes: ninguna lee lo que produce otra. Casi
    # todo el gasto es espera de red (ESPN, Pinnacle, Bovada, Playdoit), o sea
    # tiempo en el que el proceso está parado sin hacer nada.
    #
    # Se lanzan a la vez con hilos. No se quita ni una feature: se calcula
    # exactamente lo mismo, solo que a la vez. El techo pasa a ser la rama más
    # lenta en vez de la suma de todas.
    #
    # Hilos y no procesos a propósito: los modelos ya están cargados en este
    # intérprete y serializarlos a subprocesos costaría más de lo que ahorra.
    # Las esperas de red y las llamadas de numpy/sklearn sueltan el GIL, que es
    # donde está el tiempo.
    # -----------------------------------------------------------------------
    from concurrent.futures import ThreadPoolExecutor

    _ramas = {'futbol': lambda: apuestas_del_dia(max_partidos=max_partidos),
              'mlb': _picks_mlb, 'tenis': _picks_tenis, 'nba': _picks_nba}
    _res: Dict[str, Dict] = {}
    _fallos: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4,
                            thread_name_prefix='alpha') as _ex:
        _fut = {_ex.submit(fn): nombre for nombre, fn in _ramas.items()}
        for f, nombre in _fut.items():
            try:
                _res[nombre] = f.result() or {}
            except Exception as e:
                # Una rama caída no puede llevarse el barrido. Se anota y el
                # resto sigue — es la misma lección del tenis omitido por un
                # AttributeError de calibración.
                logger.warning(f"[alpha] rama '{nombre}' falló: "
                               f"{type(e).__name__}: {e}")
                _fallos[nombre] = f'{type(e).__name__}: {e}'
                _res[nombre] = {}

    r = _res.get('futbol') or {}
    capa1 = list(r.get('elite') or [])
    for p in capa1:
        p.setdefault('deporte', 'Fútbol')
    # v49: Capa 2 de fútbol desde el pase de fixtures (partidos sin cuota real)
    capa2, no_enlazados, parlay_legs = list(r.get('capa2_futbol') or []), [], []
    sin_modelo: List[Dict] = []          # v91: partidos con cuota y sin modelo
    # v77: registro de incidencias visible para el usuario. Nace de que la MLB
    # llevaba semanas fuera del barrido porque The Odds API se quedaba sin
    # cuota, y el aviso existía pero moría dentro del motor sin llegar a
    # ninguna pantalla. Un fallo que no se ve es un fallo que no se arregla.
    incidencias: List[str] = list(r.get('incidencias') or [])
    try:                                    # v78: cobertura de Playdoit
        import monitor_playdoit
        incidencias += monitor_playdoit.incidencias()
    except Exception as e:
        logger.debug(f"[alpha] monitor de Playdoit no disponible: {e}")
    for nombre, motivo in _fallos.items():
        incidencias.append(f'⚠️ La rama de {nombre} falló y se omitió: {motivo}')

    # -----------------------------------------------------------------------
    # v79 — AVISO: ¿a cuántos picks de fútbol les llega el encogimiento?
    #
    # El fútbol es el único deporte con edge validado, y ese edge se midió
    # concretamente EN w=0,25: +6,72 % de ROI con bootstrap p5 +0,92 %. Con
    # w=1,00 el mismo ledger da +0,47 % y p5 −2,62 %, o sea sin edge.
    #
    # Medido el 2026-07-29: **0 de 41 picks** de fútbol salieron encogidos. No
    # era falta de cuota sharp (Pinnacle cubría el 73 % de los partidos), sino
    # que `calibracion_mercado.json` no tiene peso para las ligas que juegan en
    # julio. La tabla se construye desde el ledger, y el ledger de fútbol viene
    # de fuentes que cubren sobre todo Europa — que ahora está de vacaciones:
    #
    #     18 ligas CON peso medido y SIN partidos hoy (parón)
    #     20 ligas jugando hoy SIN peso medido
    #     cobertura real: 49 de 160 partidos = 30,6 %
    #
    # O sea: el pick que ve el usuario en julio no es el que se validó. Es
    # información que tiene que estar delante, no enterrada en un JSON.
    # Arreglarlo de verdad exige histórico de cuotas sudamericano (BetExplorer
    # ya demostró servir para 22 ligas en la v76); mientras tanto, se avisa.
    try:
        import calibracion_mercado as _calm
        # v81 — el aviso EXCLUYE los picks de `valor_vs_sharp`.
        #
        # Decía «4 de 4 picks de fútbol salen SIN calibrar contra el mercado:
        # sus ligas no tienen peso medido», y las dos mitades eran falsas.
        # Desde la v80 todas las ligas tienen peso (caen al global), y sobre
        # todo: esos picks son de line shopping contra Pinnacle, así que su
        # probabilidad **ES** la del mercado. No es que no se calibren — es que
        # no hay nada que calibrar, ya son mercado puro. Avisar de lo contrario
        # mandaba a desconfiar precisamente de los picks mejor anclados.
        _f1 = [p for p in capa1
               if p.get('deporte', 'Fútbol') == 'Fútbol'
               and not p.get('valor_mercado')]
        if _f1:
            _sin = sorted({p.get('liga', '?') for p in _f1
                           if not (p.get('calibracion') or {}).get('aplicado')})
            _n_sin = sum(1 for p in _f1
                         if not (p.get('calibracion') or {}).get('aplicado'))
            if _n_sin:
                incidencias.append(
                    f'⚠️ {_n_sin} de {len(_f1)} picks de fútbol salen SIN calibrar '
                    f'contra el mercado: sus ligas no tienen peso medido '
                    f'({", ".join(_sin[:6])}'
                    f'{"…" if len(_sin) > 6 else ""}). El edge del fútbol se '
                    f'validó con encogimiento (w=0,25); sin él, el mismo '
                    f'histórico no muestra edge. Trátalos con más cautela.')
    except Exception as e:
        logger.debug(f'[alpha] aviso de cobertura de calibración: {e}')
    for nombre in ('mlb', 'tenis', 'nba'):
        sub = _res.get(nombre) or {}
        capa1 += sub.get('capa1', [])
        capa2 += sub.get('capa2', [])
        no_enlazados += sub.get('no_enlazados', [])
        sin_modelo += sub.get('sin_modelo', [])          # v91
        parlay_legs += sub.get('parlay_legs', [])
        incidencias += sub.get('incidencias', [])      # v77
    # --- v32: fiabilidad, pretemporada y segregación de EV extremo -------
    # v52: mapa nombre→clave DERIVADO de la config (cubre TODAS las ligas, no
    # solo un puñado) + circuitos de tenis. Antes faltaban Veikkausliiga,
    # Allsvenskan, etc. → su fiabilidad salía vacía.
    # -----------------------------------------------------------------------
    # v82 — EL NOMBRE DE LA LIGA NO IDENTIFICA A LA LIGA.
    #
    # Este mapa invierte «nombre visible → clave», y hay nombres REPETIDOS:
    #
    #     «Primera División»    -> argentina, uru_primera, slv_primera
    #     «División Profesional» -> bol_division, par_division
    #
    # Al invertir el diccionario gana el último, así que **todo pick argentino
    # o uruguayo se estaba resolviendo como `slv_primera` (El Salvador)** y
    # todo boliviano como `par_division`. Con la liga equivocada se leían la
    # fiabilidad (Brier), la antigüedad del estado y los umbrales de Capa 1 de
    # OTRA competición — de ahí que picks de River Plate salieran con «🔴 Alta
    # incertidumbre» que en realidad era el histórico salvadoreño.
    #
    # El mismo fallo tumbaba la «Combinada segura del día» con un
    # AttributeError: cargaba el motor de El Salvador y le pedía equipos
    # argentinos.
    #
    # La solución es no adivinar: cada pick lleva ahora su `clave_liga` desde
    # donde se genera, y el mapa por nombre queda solo como último recurso.
    # -----------------------------------------------------------------------
    from config import LEAGUES as _LGN
    LIGA_A_CLAVE = {cfg.get('nombre', c): c for c, cfg in _LGN.items()}
    LIGA_A_CLAVE.update({'ATP': 'atp', 'WTA': 'wta', 'MLB': 'mlb', 'NBA': 'nba',
                         'Brasileirão Serie A': 'brasil',
                         'Primera División': 'argentina'})
    for p in capa1 + capa2 + list(r.get('candidatos') or []):
        # v82: la clave REAL viaja en el pick; el nombre solo es respaldo.
        clave = (p.get('clave_liga')
                 or LIGA_A_CLAVE.get(p.get('liga', ''), p.get('liga', '').lower()))
        p['brier'] = fiabilidad_liga(clave)
        p['fiabilidad'] = fiabilidad_label(clave, p['brier'])   # v52
        dias = (_dias_estado_obsoleto(clave, p.get('fecha'))
                if p.get('deporte', 'Fútbol') == 'Fútbol' else None)
        p['dias_estado'] = dias
        p['antiguedad'] = indicador_antiguedad(dias)      # §5 semáforo
        p['pretemporada'] = bool(dias and dias > DIAS_ESTADO_OBSOLETO)
        if p['pretemporada']:
            p['nota'] = (f'⚠️ El modelo de esta liga no ve partidos desde hace '
                         f'{dias} días (pretemporada o estado sin refrescar) — '
                         'alta varianza')
    # §4: los partidos de pretemporada salen de la Capa 1 (van a Capa 2)
    pretemporada = [p for p in capa1 if p.get('pretemporada')]
    capa1 = [p for p in capa1 if not p.get('pretemporada')]
    capa2 += pretemporada
    # §3: EV extremo se SEGREGA (no se descarta) — validado en
    # resultados_ev_extremo_v32.json
    # v75: el techo se toma POR LIGA cuando el backtest de umbrales le adoptó
    # uno propio; si no, es el `EV_EXTREMO` global de `edge_engine`, igual que
    # hasta ahora.
    def _techo_ev(p) -> float:
        # v82: la clave REAL viaja en el pick; el nombre solo es respaldo.
        clave = (p.get('clave_liga')
                 or LIGA_A_CLAVE.get(p.get('liga', ''), p.get('liga', '').lower()))
        return umbrales_liga(clave).get('ev_max', EV_EXTREMO)

    ev_extremo = [p for p in capa1 if (p.get('ev') or 0) > _techo_ev(p)]
    capa1 = [p for p in capa1 if (p.get('ev') or 0) <= _techo_ev(p)]

    # -----------------------------------------------------------------------
    # v78 — SOLO DEPORTES CON EDGE VALIDADO EN LA CAPA 1.
    #
    # Al extender la calibración a tenis y MLB se pudo medir su rentabilidad
    # por primera vez, y el resultado es incómodo pero claro: barriendo el peso
    # de 1,00 a 0,25 con los umbrales de producción, ninguno de los dos alcanza
    # un ROI robusto. El tenis llevaba emitiendo picks que perdían un 5 %
    # sostenido sobre 3.666 apuestas.
    #
    #     Fútbol  +6,72 % (n=584, p5 +0,92 %)  → entra
    #     MLB     +3,46 % (n=394, p5 −3,98 %)  → fuera
    #     Tenis   −0,54 % (n=1.971, p5 −6,29 %) → fuera
    #
    # Es la misma regla que dejó el Over/Under 2.5 fuera de la Capa 1 en la
    # v44. Los picks se siguen calculando y mostrando como candidatos con su
    # motivo; no desaparecen, dejan de venderse como élite. En cuanto un
    # deporte pase la regla (`validacion_deportes.py` se recalcula con el
    # ledger), vuelve solo.
    # -----------------------------------------------------------------------
    try:
        import validacion_deportes as _vd
        # v82 — el veto por deporte es un juicio sobre el MODELO, y los picks
        # de `valor_vs_sharp` no lo usan: apuestan la discrepancia entre casas.
        # Aplicarles el veto los expulsaba por un defecto que no es suyo, y era
        # justo lo que dejaba la Capa 1 sin tenis pese a tener edge validado
        # (WTA: p5 +1,70 % en elección y +0,61 % en validación, n=2.436).
        def _exento(p):
            return bool(p.get('valor_mercado'))

        sin_edge = [p for p in capa1
                    if not _exento(p) and not _vd.tiene_edge(p.get('deporte'))]
        if sin_edge:
            capa1 = [p for p in capa1
                     if _exento(p) or _vd.tiene_edge(p.get('deporte'))]
            for p in sin_edge:
                p['sin_edge_deporte'] = True
                p['nota'] = ((p.get('nota') or '') + ' ' +
                             (_vd.motivo(p.get('deporte')) or '')).strip()
            candidatos_extra = sin_edge
            for dep in sorted({p.get('deporte') for p in sin_edge}):
                incidencias.append('ℹ️ ' + (_vd.motivo(dep) or f'{dep}: sin edge validado.'))
        else:
            candidatos_extra = []
    except Exception as e:
        logger.warning(f"[alpha] validacion_deportes no disponible: {e}")
        candidatos_extra = []

    # -----------------------------------------------------------------------
    # v77 — PESTAÑA «MÁXIMA CONFIANZA»
    #
    # Mismos modelos y mismas cuotas reales que la Capa 1; lo único que cambia
    # es el criterio de selección: prioriza ACERTAR por encima de cobrar caro.
    # Se exige prob ≥ 0,80 y cuota ≥ 1,50, sin mínimo de EV.
    #
    # Con un aviso que hay que decir claro y que la UI repite: un pick de
    # probabilidad muy alta y EV negativo es, por definición, una apuesta
    # perdedora a largo plazo — se acierta mucho y se pierde despacio. Por eso
    # va con stake reducido (¼ de Kelly) y por eso se marca `ev_negativo`
    # cuando toca, en vez de esconderlo detrás de un porcentaje de acierto
    # bonito. La pestaña existe porque el usuario la pidió para construir
    # combinadas, no porque sea la más rentable.
    # -----------------------------------------------------------------------
    # v91 — LA CAPA 2 ENTRA AL UNIVERSO de Máxima Confianza. El usuario
    # señaló que la pestaña sólo enseñaba fútbol, y el motivo era estructural:
    # los favoritos claros de tenis y MLB (82-88 % con cuota real de 1,08-1,15)
    # viven en la capa2 — no pasan los filtros de élite justamente por la
    # cuota corta — y la capa2 no entraba aquí. Son exactamente el material
    # que esta pestaña promete («acertar por encima de cobrar caro», v77).
    universo_prob = (capa1 + ev_extremo + list(r.get('candidatos') or [])
                     + capa2)
    vistos_prob, capa1_prob = set(), []
    try:
        import calibracion_confianza as _cc
        umbral_conf = float((_cc._tabla() or {}).get('umbral_recomendado')
                            or PROB_MAXIMA_CONFIANZA)
    except Exception:
        _cc, umbral_conf = None, PROB_MAXIMA_CONFIANZA
    for p in sorted(universo_prob, key=lambda x: -(x.get('prob') or 0)):
        prob, cuota = p.get('prob') or 0, p.get('cuota') or 0
        # v91 — el piso de cuota baja de 1,50 a 1,05 SÓLO en esta pestaña.
        # El 1,50 es un guardarraíl de APUESTA SIMPLE (v71: los favoritos
        # cortos concentraban la sobreconfianza); pero esta pestaña prioriza
        # acertar y alimenta combinadas (v77), y con 1,50 dejaba fuera a todo
        # el tenis y la MLB (favoritos a 1,08-1,15) — que es lo que el usuario
        # pidió ver aquí. La honestidad la ponen el acierto real por banda y
        # la bandera `ev_negativo`, que ya avisan de que un favorito corto con
        # EV negativo pierde dinero como apuesta simple.
        if prob < umbral_conf or cuota < 1.05:
            continue
        clave = (p.get('deporte'), p.get('partido'), p.get('apuesta'))
        if clave in vistos_prob:
            continue
        vistos_prob.add(clave)
        q = dict(p)
        q['perfil'] = 'confianza'
        q['fraccion_kelly'] = FRACCION_KELLY_CONFIANZA
        q['ev_negativo'] = bool((p.get('ev') or 0) <= 0)
        # el acierto que esa banda de probabilidad da DE VERDAD, junto al que
        # promete el modelo. Sin esto la pestaña vendería un 79 % que en el
        # histórico se convierte en 58 %.
        # v84 — SE MUESTRA UNA SOLA PROBABILIDAD: la de ganar la apuesta.
        #
        # Antes se enseñaba la del modelo (80 %) con una nota diciendo que esa
        # banda acierta el 58 %, y eso obliga a hacer la corrección de cabeza.
        # Si el histórico dice 58 %, la probabilidad de ganar es 58 %.
        #
        # Solo se corrige donde HAY medición para ese mercado. Donde no la hay
        # se dice, en vez de importar el número de otro mercado (ver
        # `calibracion_confianza`).
        #
        # v86 — GOLES y BTTS ya tienen medición propia, construida con
        # `build_ledger_totales.py` (47.794 partidos fuera de muestra con
        # walk-forward de los regresores de Poisson). Antes decían «no medido».
        # Lo que aparece ahora no es cosmético:
        #
        #     Goles, banda >=0,75 : el modelo dice 83,1 % y acierta 74,5 %
        #     BTTS,  banda >=0,75 : el modelo dice 80,6 % y acierta 53,2 %
        #
        # El BTTS está PLANO: 51-55 % de acierto real en todas las bandas, diga
        # lo que diga el modelo. Es la confirmación medida de lo que la v75
        # sospechaba, y ahora el usuario ve el 53 % en vez del 80 %.
        #
        # El hándicap asiático sigue sin medición y sigue diciéndolo.
        if _cc is not None:
            _merc = p.get('mercado')
            _real = _cc.probabilidad_real(prob, _merc)
            q['prob_modelo'] = prob              # se conserva para auditoría
            q['acierto_real'] = _real
            q['medido'] = _cc.hay_medicion(_merc)
            if _real is not None:
                q['prob'] = round(_real, 3)      # LA probabilidad que se muestra
                q['cuota_justa'] = round(1 / max(_real, 1e-6), 2)
                if q.get('cuota'):
                    q['ev'] = round(q['cuota'] * _real - 1, 4)
                    q['ev_negativo'] = bool(q['ev'] <= 0)
            q['aviso_calibracion'] = _cc.aviso_calibracion(prob, _merc)
        capa1_prob.append(q)
    if not capa1_prob:
        pct = None
        try:
            for u in ((_cc._tabla() or {}).get('umbrales') or []):
                if abs(float(u.get('umbral', 0)) - umbral_conf) < 1e-9:
                    pct = u.get('pct_partidos')
                    break
        except Exception:
            pass
        incidencias.append(
            f'ℹ️ Máxima Confianza: hoy ningún pick alcanza prob ≥ '
            f'{umbral_conf:.0%} con cuota real.'
            + (f' Históricamente solo lo consigue el {pct:.2%} de los partidos, '
               f'así que es normal que algunos días esté vacía.' if pct else ''))

    # v38: etiqueta de rentabilidad esperada (edge_engine) por pick de capa1 —
    # en qué tramo de EV real cae y si su liga es históricamente deficitaria.
    try:
        import edge_engine
        for p in capa1:
            # v82: la clave REAL viaja en el pick; el nombre solo es respaldo.
            clave = (p.get('clave_liga')
                     or LIGA_A_CLAVE.get(p.get('liga', ''),
                                         p.get('liga', '').lower()))
            p['rentabilidad'] = edge_engine.clasificar_pick(p.get('ev'), clave)
    except Exception as e:
        logger.warning(f"[alpha] edge_engine no disponible: {e}")

    # -----------------------------------------------------------------------
    # v81 — TODAS LAS CAPAS SE ORDENAN POR PROBABILIDAD DESCENDENTE.
    #
    # La Capa 1 se ordenaba por EV y la lista de candidatos por EV×probabilidad,
    # así que un pick al 34 % podía aparecer por encima de uno al 58 % solo por
    # llevar más EV. Para leer la lista de un vistazo —que es como se usa— la
    # probabilidad es el criterio natural: primero lo más probable.
    #
    # Se conservan como desempates las señales que sí están medidas y que antes
    # mandaban: la confirmación sharp (v42, +14,7 % de ROI frente a +9,9 % sin
    # ella) y el EV. No se pierde información de orden, se subordina.
    # -----------------------------------------------------------------------
    def _orden_prob(t):
        return (-(t.get('prob') or 0),
                -int(t.get('sharp_confirmado', False)),
                -int(t.get('platino', False)),
                -(t.get('ev') or 0))

    capa1.sort(key=_orden_prob)
    capa2.sort(key=_orden_prob)
    ev_extremo.sort(key=_orden_prob)
    deportes = sorted({p.get('deporte', 'Fútbol') for p in capa1 + capa2})
    # v37 (§6): sección BTTS destacada — de todo el universo de picks
    # (capa1 + capa2 + candidatos del barrido de fútbol)
    if candidatos_extra:
        r['candidatos'] = list(r.get('candidatos') or []) + candidatos_extra
    # v81 — los candidatos también, por el mismo motivo que las capas.
    r['candidatos'] = sorted(list(r.get('candidatos') or []), key=_orden_prob)
    todos_pool = capa1 + capa2 + list(r.get('candidatos') or [])
    btts = _seccion_btts(todos_pool)
    # v37 (§5): oleadas temporales sobre la capa 1 (la accionable con cuota)
    oleadas = _oleadas(capa1)
    # v41 (§3.1): mejores patas para construir parlays
    mejores_patas = _mejores_patas(todos_pool)
    # v77: combinadas MULTI-DEPORTE a partir de las dos primeras pestañas
    try:
        import cross_sport_parlay
        combinadas = cross_sport_parlay.generar(capa1, capa1_prob)
        if not combinadas:
            # v81 — el aviso decía «hacen falta picks de dos deportes con prob
            # ≥ 55 %», y eso apuntaba al sitio equivocado: hoy hay picks de
            # tenis al 88 %, 85 % y 83 %. Lo que falta no es probabilidad, es
            # que el tenis y la MLB **no tienen edge validado** (v78), así que
            # no entran en el material de las combinadas. Decir «faltan picks
            # buenos» invitaba a buscar donde no hay nada; decir el motivo real
            # explica también cuándo volverán: cuando el ledger valide un
            # segundo deporte.
            # v82 — el aviso dice el motivo EXACTO, comprobándolo en vez de
            # suponerlo. Ha ido cambiando dos veces porque la causa cambió: al
                        # principio faltaban deportes, luego faltaba edge, y
            # ahora que el tenis vuelve a la Capa 1 lo que falta puede ser
            # simplemente que sus picks no lleguen al mínimo por pata.
            _pool = capa1 + capa1_prob
            _min = cross_sport_parlay.MIN_PROB_PATA
            _aptos = {}
            for _p in _pool:
                if (_p.get('prob') or 0) >= _min:
                    _aptos.setdefault(_p.get('deporte'), 0)
                    _aptos[_p.get('deporte')] += 1
            deportes_disp = sorted({p.get('deporte') for p in _pool})
            _msg = (f'ℹ️ Combinadas: no se pudo cruzar deportes hoy. '
                    f'Deportes en Capa 1: {deportes_disp}.')
            if len(_aptos) >= 2:
                _msg += (f' Hay patas de {len(_aptos)} deportes '
                         f'({_aptos}) pero ninguna combinación superó los '
                         f'filtros de probabilidad conjunta o cuota máxima.')
            elif _aptos:
                _dep, _n = next(iter(_aptos.items()))
                _msg += (f' Solo {_dep} tiene picks con prob ≥ {_min:.0%} '
                         f'({_n}); los de los demás deportes se quedan por '
                         f'debajo de ese mínimo por pata, que existe porque '
                         f'una pata floja arrastra a toda la combinada.')
            else:
                _msg += (f' Ningún pick alcanza el mínimo por pata '
                         f'({_min:.0%}).')
            incidencias.append(_msg)
    except Exception as e:
        combinadas = []
        incidencias.append(f'⚠️ Combinadas no generadas: {type(e).__name__}: {e}')
    # v47: PARLAY DEL DÍA DE TENIS — combina los mercados derivados más seguros
    # (uno por partido para diversificar), objetivo cuota combinada contundente.
    tenis_parlay = _construir_parlay_tenis(parlay_legs)
    # v47: la CAPA 1 nunca debe quedar vacía (el usuario notó que "desapareció").
    # Si hoy no hay ningún 1X2 con cuota real que pase los filtros de élite, se
    # promueve una "Selección del día" con los mejores candidatos por convicción
    # (prob×EV), etiquetada con honestidad como NO confirmada por línea sharp.
    seleccion_dia = []
    if not capa1:
        pool = [p for p in (r.get('candidatos') or []) if (p.get('ev') or 0) > 0]
        pool.sort(key=lambda p: -((p.get('prob') or 0) * (p.get('ev') or 0)))
        # v89 — VARIAS APUESTAS POR PARTIDO. Antes se tomaban las 6 mejores
        # tarjetas del pool y en la práctica salía una apuesta por partido; el
        # usuario pidió que si un partido tiene varios mercados con buena
        # probabilidad/EV se muestren todos. Se eligen los mejores PARTIDOS
        # por convicción y de cada uno se llevan hasta 3 mercados con EV > 0.
        _por_partido: Dict[str, List[Dict]] = {}
        for p in pool:
            _por_partido.setdefault(p.get('partido', '?'), []).append(p)
        for _partido, _picks in list(_por_partido.items())[:8]:
            for p in _picks[:3]:
                q = dict(p)
                q['seleccion_dia'] = True
                q['nota_seleccion'] = ('Mejor oportunidad del día por valor '
                                       'esperado. Sin confirmación de la línea '
                                       'profesional: apuesta con stake prudente.')
                seleccion_dia.append(q)
    r.update({'capa1': capa1, 'capa2': capa2, 'ev_extremo': ev_extremo,
              'no_enlazados': no_enlazados, 'deportes_cubiertos': deportes,
              # v91: los partidos con cuota que el modelo no cubre salen como
              # tarjeta con precio real, no como lista de texto.
              'sin_modelo': sorted(sin_modelo,
                                   key=lambda p: -(p.get('prob') or 0)),
              'pick_del_dia': pick_del_dia(capa1),
              'btts_destacado': btts, 'oleadas': oleadas,
              'mejores_patas': mejores_patas,
              'tenis_parlay': tenis_parlay,
              'seleccion_dia': seleccion_dia,
              'pronosticos': r.get('pronosticos') or [],   # v49: todos los partidos
              'elite': capa1,          # compatibilidad con UI/exportación
              # --- v77: las tres pestañas ---
              'capa1_prob': capa1_prob,
              'combinadas': combinadas,
              'incidencias': incidencias,
              })
    try:                      # v32 §6: registro para el rendimiento REAL
        import rendimiento_real
        rendimiento_real.registrar(capa1, 'capa1')
        rendimiento_real.registrar(capa2, 'capa2')
    except Exception as e:
        logger.warning(f"[alpha] rendimiento_real no registrado: {e}")
    global _ULTIMO_RESULTADO
    _ULTIMO_RESULTADO = r
    logger.info(f"[alpha] universal: capa1={len(capa1)} capa2={len(capa2)} "
                f"deportes={deportes} no_enlazados={len(no_enlazados)}")
    return r


def exportar_txt(r: Optional[Dict] = None) -> str:
    """Apuestas del día como texto plano (v30 §1: arg opcional — si es None
    usa el último barrido; robusto ante cualquier forma de los picks)."""
    import traductor_quant as _tq
    r = r if r is not None else _ULTIMO_RESULTADO
    lineas = [f"APUESTAS DEL DÍA — {r.get('actualizado', '?')}",
              f"(cobertura: {r.get('cobertura_ligas', {})})", ""]
    grupos = [('elite', '💎 CAPA 1 — ÉLITE (cuota real, respaldo profesional)'),
              ('seleccion_dia', '⭐ SELECCIÓN DEL DÍA (mejor valor, sin confirmar)'),
              ('capa2', '🎯 CAPA 2 — ALTA CONFIANZA (sin cuota real)'),
              ('candidatos', 'CANDIDATOS')]
    for grupo, titulo in grupos:
        picks = r.get(grupo) or []
        if not picks:
            continue
        lineas.append(f"== {titulo} ==")
        for t in picks:
            estrella = '⭐' if t.get('platino') else ('💎' if t.get('evc') else '')
            ev = t.get('ev') or 0
            prob = t.get('prob', 0) or 0
            cuota = t.get('cuota')
            precio = (f"@ {cuota} (justa {t.get('cuota_justa','?')}) · "
                      f"EV {ev*100:+.1f}%" if cuota else
                      f"SIN cuota real · cuota mínima sugerida "
                      f"{t.get('cuota_justa','?')}")
            # v47: sharp en lenguaje llano en vez de "+6% sobre Pinnacle"
            cola = ''
            if t.get('sharp_confirmado'):
                cola += '\n     ' + _tq.sello_sharp(t.get('sharp_gap'))
            if t.get('casa'):
                cola += f"\n     🏠 mejor cuota en {t['casa']}"
            lineas.append(
                f"{estrella} [{t.get('deporte','Fútbol')}] {t.get('partido','?')} "
                f"({t.get('liga','?')}, {t.get('fecha','')}) — "
                f"{t.get('apuesta','?')} {precio} · prob {prob*100:.0f}%"
                + (f" · stake {t['stake_txt']}" if t.get('stake_txt') else '')
                + cola)
            # v47: tenis — desglose de los mercados derivados (parlays)
            mts = t.get('mercados_tenis') or []
            if mts:
                top = sorted(mts, key=lambda c: -c['valor'])[:6]
                lineas.append("     🎾 Mercados: " + " · ".join(
                    f"{c['etiqueta']} {c['valor']:.0f}%" for c in top))
        lineas.append("")
    # v47: parlay del día de tenis
    tp = r.get('tenis_parlay') or {}
    if tp.get('patas'):
        lineas.append(f"== 🎾 PARLAY DEL DÍA (TENIS) — cuota {tp['cuota_combinada']} · "
                      f"prob {tp['prob_conjunta']*100:.0f}% ==")
        for p in tp['patas']:
            lineas.append(f"  • [{p['circuito']}] {p['partido']}: {p['mercado']} "
                          f"({p['prob']*100:.0f}%, justa {p['cuota_justa']})")
        lineas.append("")
    lineas.append("Juego responsable. Cuotas justas = 1/probabilidad.")
    return '\n'.join(lineas)


def exportar_csv(r: Optional[Dict] = None) -> str:
    import csv
    import io
    r = r if r is not None else _ULTIMO_RESULTADO
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['capa', 'deporte', 'partido', 'liga', 'fecha', 'mercado',
                'apuesta', 'cuota', 'cuota_justa', 'ev_pct', 'prob_pct',
                'stake', 'evc', 'platino'])
    for grupo, capa in (('elite', 'capa1_evc'), ('capa2', 'capa2_confianza'),
                        ('candidatos', 'candidatos')):
        for t in r.get(grupo) or []:
            w.writerow([capa, t.get('deporte', 'Fútbol'), t.get('partido', ''),
                        t.get('liga', ''), t.get('fecha', ''), t.get('mercado', ''),
                        t.get('apuesta', ''), t.get('cuota', ''),
                        t.get('cuota_justa', ''), round((t.get('ev') or 0)*100, 1),
                        round((t.get('prob', 0) or 0)*100, 0), t.get('stake_txt', ''),
                        t.get('evc', False), t.get('platino', False)])
    return buf.getvalue()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    r = apuestas_del_dia()
    print(f"evaluados: {r['partidos_evaluados']} · élite: {len(r['elite'])} · "
          f"candidatos: {len(r['candidatos'])}")
    for t in (r['elite'] or r['candidatos'])[:8]:
        print(f"  {t['valor']} {t['fecha']} {t['liga']}: {t['partido']} — "
              f"{t['apuesta']} @ {t['cuota']} (justa {t['cuota_justa']}, "
              f"EV {t['ev']*100:+.1f} %)")
