#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Todos los mercados de todos los partidos de un día, en una sola estructura.

PARA QUÉ EXISTE
---------------
El envío diario a Telegram manda los PICKS: lo que pasa los filtros. El usuario
pidió además poder mandar el día entero —todos los deportes, todos los partidos
y todas las métricas, no sólo el ganador— y para eso hace falta juntar en un
sitio lo que hoy vive repartido entre once listas del barrido y las secciones
de la ficha de cada partido.

QUÉ ENTRA Y POR QUÉ, CON EL COSTE MEDIDO
----------------------------------------
La bitácora §4 cuenta tres regresiones de rendimiento seguidas, todas por meter
una petición nueva en el camino caliente, y todas cazadas midiendo. Así que
aquí se midió antes de escribir, sobre los 102 partidos de fútbol de un día
real (2026-09-15):

    lo que YA trae el barrido (1X2, goles, BTTS, hándicap,
      ganador, primer set, total de sets, moneyline) ........  0 s
    rendimiento_equipos.corners_equipo  × 102 partidos ......  1,20 s
    rendimiento_equipos.tarjetas_equipo × 102 partidos ......  0,68 s
    rendimiento_equipos.remates_equipo  × 102 partidos ......  1,55 s
                                                              -------
                                                               3,43 s

y, para comparar, lo que NO se hace:

    ClubEngine.plantilla_club × 102 partidos ................  ~14 min
      (8,35 s por partido, medido sobre 8)
    cuotas_multi.mercados_playdoit × 102 partidos ...........  1 petición
      de 250-320 KB por partido, sin caché la primera vez

Es decir: córners, tarjetas y remates entran porque salen de ficheros locales
por 34 ms de partido. La ficha entera y el tablero de la casa no entran, y no
por pereza: cuestan entre cien y mil veces más y ya costaron tres regresiones.

DE DÓNDE SALEN LOS NÚMEROS — Y NO SON NUEVOS
--------------------------------------------
`corners_equipo`, `tarjetas_equipo` y `remates_equipo` de `rendimiento_equipos`
son los MISMOS estimadores que usa la ficha del partido. No se re-implementa
ninguna fórmula aquí: si la ficha dice 9,4 córners, este módulo dice 9,4. Ésa
es la razón de llamar a la función pública en vez de copiar el bloque del motor
— dos verdades para el mismo partido sería peor que no enseñar ninguna.

LO QUE ESTE MÓDULO NO HACE
--------------------------
No calcula EV de córners, tarjetas ni remates, y no es un olvido: el proyecto
tiene medido (`corners_ui`, bitácora §10.7) que el modelo de córners **ordena**
bien los partidos pero su **nivel** va alto, y cruzar eso contra la cuota
produce EV de +50 % a +136 %, que es la firma de que el modelo se equivoca. Se
publica la probabilidad y se dice que es informativa.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Las líneas que se publican de cada mercado. Son las de `distributions.LINEAS`,
# que a su vez son las que cotizan las casas; se copian aquí como tupla para no
# arrastrar numpy ni scipy sólo por leer una constante.
LINEAS_CORNERS_TOTAL = (6.5, 7.5, 8.5, 9.5, 10.5)
LINEAS_CORNERS_EQUIPO = (3.5, 4.5, 5.5)
LINEAS_TARJETAS_TOTAL = (2.5, 3.5, 4.5, 5.5)
LINEAS_TARJETAS_EQUIPO = (1.5, 2.5)
LINEAS_REMATES_TOTAL = (18.5, 20.5, 22.5, 24.5)
LINEAS_REMATES_PUERTA = (4.5, 5.5, 6.5, 7.5)

# Deportes cuyo texto de partido va «visitante @ local» en vez de «A vs B».
_ARROBA = ('MLB', 'KBO')


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _lados(p: Dict) -> Optional[tuple]:
    """(local, visitante) del texto del partido, o None si no se puede leer."""
    txt = str(p.get('partido') or '')
    if ' @ ' in txt:
        visitante, local = [x.strip() for x in txt.split(' @ ', 1)]
        return (local, visitante) if local and visitante else None
    if ' vs ' in txt:
        local, visitante = [x.strip() for x in txt.split(' vs ', 1)]
        return (local, visitante) if local and visitante else None
    return None


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _justa(prob) -> Optional[float]:
    p = _f(prob)
    return round(1.0 / p, 2) if p and p > 0 else None


def mercado(categoria: str, etiqueta: str, prob=None, cuota=None, casa=None,
            ev=None, cuota_justa=None, informativo: bool = False,
            nota: str = '') -> Dict:
    """Una línea de mercado, con la misma forma venga del deporte que venga."""
    return {'categoria': categoria, 'etiqueta': etiqueta,
            'prob': _f(prob), 'cuota': _f(cuota), 'casa': casa or None,
            'ev': _f(ev),
            'cuota_justa': _f(cuota_justa) if cuota_justa is not None
            else _justa(prob),
            'informativo': bool(informativo), 'nota': nota or ''}


# ---------------------------------------------------------------------------
# Córners, tarjetas y remates — los tres bloques que sólo tiene el fútbol
# ---------------------------------------------------------------------------
def _lineas_de(media, dispersion, lineas, plantilla: str,
               categoria: str) -> List[Dict]:
    """Las líneas de un conteo, con la sobredispersión de su competición.

    Se usa `rendimiento_equipos.prob_mas_de`, que con dispersión 1 es Poisson
    exacta y por encima la binomial negativa. No es un detalle: medido sobre 24
    líneas de 6 competiciones, la binomial negativa comete la MITAD de error
    que Poisson en las líneas que cotiza la casa.
    """
    m = _f(media)
    if not m or m <= 0:
        return []
    import rendimiento_equipos as rq
    fuera = []
    for L in lineas:
        p = rq.prob_mas_de(m, L, dispersion)
        if p is None:
            continue
        fuera.append(mercado(categoria, plantilla.format(linea=L), prob=p,
                             informativo=True))
    return fuera


def extras_futbol(clave_liga: str, home: str, away: str) -> List[Dict]:
    """Córners, tarjetas y remates del partido — todo de ficheros locales.

    Devuelve lista vacía sin romper nada si la competición no publica esos
    datos: un hueco se ve, un relleno no (bitácora v150).
    """
    fuera: List[Dict] = []
    if not (clave_liga and home and away):
        return fuera
    try:
        import rendimiento_equipos as rq
    except Exception as e:                       # nunca puede tumbar el envío
        logger.warning('[mercados-dia] rendimiento_equipos no disponible: %s', e)
        return fuera

    # --- córners ---------------------------------------------------------
    try:
        ck = rq.corners_equipo(clave_liga, home, away)
    except Exception as e:
        ck = None
        logger.debug('[mercados-dia] córners %s: %s', clave_liga, e)
    if ck:
        _org = ' (estimado)' if ck.get('origen') != 'observado' else ''
        fuera.append(mercado(
            'Córners', f"Media del partido{_org}",
            informativo=True, nota=f"{_f(ck.get('lambda_total')):.1f} córners"
            if _f(ck.get('lambda_total')) else ''))
        fuera += _lineas_de(ck.get('lambda_total'), ck.get('dispersion_total'),
                            LINEAS_CORNERS_TOTAL, 'Más de {linea} córners',
                            'Córners')
        for lado, eq in (('lambda_home', home), ('lambda_away', away)):
            fuera += _lineas_de(ck.get(lado), ck.get('dispersion'),
                                LINEAS_CORNERS_EQUIPO,
                                f'{eq}: más de {{linea}} córners', 'Córners')

    # --- tarjetas --------------------------------------------------------
    try:
        tj = rq.tarjetas_equipo(clave_liga, home, away)
    except Exception as e:
        tj = None
        logger.debug('[mercados-dia] tarjetas %s: %s', clave_liga, e)
    if tj:
        _org = ' (estimado)' if tj.get('origen') != 'observado' else ''
        fuera.append(mercado(
            'Tarjetas', f"Media del partido{_org}", informativo=True,
            nota=f"{_f(tj.get('lambda_total')):.1f} tarjetas"
            if _f(tj.get('lambda_total')) else ''))
        fuera += _lineas_de(tj.get('lambda_total'), tj.get('dispersion_total'),
                            LINEAS_TARJETAS_TOTAL, 'Más de {linea} tarjetas',
                            'Tarjetas')
        for lado, eq in (('lambda_home', home), ('lambda_away', away)):
            fuera += _lineas_de(tj.get(lado), tj.get('dispersion'),
                                LINEAS_TARJETAS_EQUIPO,
                                f'{eq}: más de {{linea}} tarjetas', 'Tarjetas')

    # --- remates ---------------------------------------------------------
    try:
        rm = rq.remates_equipo(clave_liga, home, away)
    except Exception as e:
        rm = None
        logger.debug('[mercados-dia] remates %s: %s', clave_liga, e)
    if rm:
        for clave, titulo, lineas in (
                ('totales', 'Remates', LINEAS_REMATES_TOTAL),
                ('a_puerta', 'Remates a puerta', LINEAS_REMATES_PUERTA)):
            blo = rm.get(clave) or {}
            if not blo:
                continue
            _org = ' (estimado)' if blo.get('origen') != 'observado' else ''
            _m = _f(blo.get('lambda_total'))
            fuera.append(mercado(titulo, f'Media del partido{_org}',
                                 informativo=True,
                                 nota=f'{_m:.1f}' if _m else ''))
            fuera += _lineas_de(blo.get('lambda_total'),
                                blo.get('dispersion_total'), lineas,
                                'Más de {linea} ' + titulo.lower(), titulo)
    return fuera


# ---------------------------------------------------------------------------
# Los mercados que cada fila del barrido ya trae consigo
# ---------------------------------------------------------------------------
def mercados_de_fila(p: Dict) -> List[Dict]:
    """Todo lo que esta fila del barrido publica, sin calcular nada nuevo."""
    fuera: List[Dict] = []
    dep = str(p.get('deporte') or 'Fútbol')

    # la apuesta principal, con su precio real si lo hay
    if p.get('apuesta'):
        fuera.append(mercado(str(p.get('mercado') or 'Principal'),
                             str(p['apuesta']), prob=p.get('prob'),
                             cuota=p.get('cuota'), casa=p.get('casa'),
                             ev=p.get('ev'), cuota_justa=p.get('cuota_justa')))

    # `mercados`: el desglose que el fútbol ya publica (1X2 + goles + BTTS)
    for m in (p.get('mercados') or []):
        if not isinstance(m, dict) or not m.get('apuesta'):
            continue
        fuera.append(mercado(str(m.get('mercado') or 'Mercado'),
                             str(m['apuesta']), prob=m.get('prob'),
                             cuota=m.get('cuota'), ev=m.get('ev'),
                             cuota_justa=m.get('cuota_justa')))

    # `board`: cuando no hay `mercados`, es donde vive el 1X2 y el over/under.
    # Se salta lo que ya salió como apuesta principal: ahí la etiqueta es la
    # misma y la principal es la que trae precio, así que repetirla sería
    # enseñar el mismo mercado dos veces con distinta información.
    if not (p.get('mercados') or []):
        _ya = {m['etiqueta'] for m in fuera}
        for etq, pr in (p.get('board') or {}).items():
            if str(etq) in _ya:
                continue
            fuera.append(mercado('Pronóstico', str(etq), prob=pr))

    # la escalera de goles, que va en su propia clave a propósito
    for linea, pr in sorted((p.get('goles_lineas') or {}).items(),
                            key=lambda kv: _f(kv[0]) or 0):
        fuera.append(mercado('Goles', f'Más de {linea}', prob=pr))

    # tenis: primer set y total de sets
    ms = p.get('mercados_sets') or {}
    for bloque in ('primer_set', 'sets'):
        for etq, pr in (ms.get(bloque) or {}).items():
            fuera.append(mercado(
                'Sets' if bloque == 'sets' else 'Primer set', str(etq),
                prob=pr, informativo=(bloque == 'sets'),
                nota=('ninguna casa que se lee publica esta línea'
                      if bloque == 'sets' else '')))
    if ms.get('muestra_corta'):
        fuera.append(mercado('Sets', 'Aviso', informativo=True,
                             nota='muestra corta: la probabilidad de sets sale '
                                  'de pocos partidos'))

    # tenis: los mercados derivados que alimentan los parlays
    for m in (p.get('mercados_tenis') or []):
        if not isinstance(m, dict) or not m.get('etiqueta'):
            continue
        v = _f(m.get('valor'))
        fuera.append(mercado('Tenis · derivados', str(m['etiqueta']),
                             prob=(v / 100.0) if v is not None else None,
                             informativo=True))

    # NFL: el marcador que predice el modelo
    if dep == 'NFL':
        for campo, etq in (('marcador_esperado', 'Marcador esperado'),
                           ('margen_esperado', 'Margen esperado'),
                           ('total_esperado', 'Total esperado')):
            if p.get(campo) is not None:
                fuera.append(mercado('NFL · modelo', etq, informativo=True,
                                     nota=str(p[campo])))

    # el precio de referencia del mercado, que NO es una oferta de nadie
    imp = p.get('implicitas') or {}
    cu = imp.get('1x2_cuotas') or {}
    if cu:
        _l = _lados(p)
        _n = {'home': (_l[0] if _l else 'local'), 'draw': 'Empate',
              'away': (_l[1] if _l else 'visitante')}
        partes = [f"{_n.get(k, k)} {v}" for k, v in cu.items() if _f(v)]
        if partes:
            fuera.append(mercado(
                'Referencia de mercado', ' · '.join(partes), informativo=True,
                nota='precio del mercado para medir el valor; no es una casa '
                     'donde puedas apostar'))
    return fuera


# ---------------------------------------------------------------------------
# El día entero
# ---------------------------------------------------------------------------
def _dia_de(p: Dict) -> str:
    """La fecha en CDMX, que es la que el usuario llama «hoy»."""
    try:
        import horario
        d = horario.fecha(p.get('inicio'))
        if d:
            return d
    except Exception:
        pass
    return str(p.get('fecha_cdmx') or p.get('fecha') or '')[:10]


def dia_cdmx(desplazamiento: int = 0) -> str:
    """'2026-09-15' — hoy en CDMX, o el día que se pida de desplazamiento."""
    import datetime as _dt
    try:
        import horario
        ahora = _dt.datetime.now(_dt.timezone.utc).astimezone(horario._zona())
    except Exception:
        ahora = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-6)))
    return (ahora + _dt.timedelta(days=desplazamiento)).strftime('%Y-%m-%d')


# Las listas del barrido que llevan filas de partido. Se recorren TODAS a
# propósito: un partido puede llegar por `pronosticos` y su mejor mercado por
# `candidatos`, y quedarse con una sola lista era justo el fallo que la v195.4
# encontró en el guardia de casas (miraba tres listas y había catorce).
LISTAS = ('pronosticos', 'capa1', 'capa2', 'capa1_prob', 'candidatos',
          'seleccion_dia', 'sin_modelo', 'btts_destacado', 'mejores_patas',
          'seccion1', 'seccion2', 'elite')


def partidos_del_dia(r: Dict, dia: Optional[str] = None,
                     con_extras: bool = True) -> List[Dict]:
    """
    Un registro por partido de ese día, con TODOS sus mercados y sin repetir.

    `dia` es una fecha de CDMX ('2026-09-15'); `None` significa hoy. Si no se
    le pasa `r` ya calculado no se lanza ningún barrido: eso lo decide quien
    llama, porque un segundo barrido dentro del proceso de Streamlit sube el
    pico de memoria de 1.297 MB a 2.172 MB y mata el contenedor (bitácora v86).
    """
    dia = dia or dia_cdmx()
    por_partido: Dict[tuple, Dict] = {}

    for nombre in LISTAS:
        for p in (r.get(nombre) or []):
            if not isinstance(p, dict) or not p.get('partido'):
                continue
            if _dia_de(p) != dia:
                continue
            clave = (str(p.get('deporte') or 'Fútbol'), str(p['partido']))
            reg = por_partido.get(clave)
            if reg is None:
                reg = {
                    'deporte': clave[0], 'partido': clave[1],
                    'liga': p.get('liga') or p.get('clave_liga') or '',
                    'clave_liga': p.get('clave_liga') or '',
                    'hora': p.get('hora_cdmx') or '',
                    'inicio': p.get('inicio'),
                    'superficie': p.get('superficie') or '',
                    'fiabilidad': p.get('fiabilidad') or '',
                    'mercados': [], 'notas': [], '_vistos': set(),
                }
                por_partido[clave] = reg
            if not reg['hora'] and p.get('hora_cdmx'):
                reg['hora'] = p['hora_cdmx']
            if not reg['fiabilidad'] and p.get('fiabilidad'):
                reg['fiabilidad'] = p['fiabilidad']
            if p.get('nota') and p['nota'] not in reg['notas']:
                reg['notas'].append(str(p['nota']))
            for m in mercados_de_fila(p):
                # una misma apuesta puede venir de dos listas; se queda la que
                # trae precio, que es la accionable
                k = (m['categoria'], m['etiqueta'])
                if k in reg['_vistos']:
                    if m['cuota'] is not None:
                        for i, viejo in enumerate(reg['mercados']):
                            if (viejo['categoria'], viejo['etiqueta']) == k \
                                    and viejo['cuota'] is None:
                                reg['mercados'][i] = m
                                break
                    continue
                reg['_vistos'].add(k)
                reg['mercados'].append(m)

    if con_extras:
        for reg in por_partido.values():
            if reg['deporte'] != 'Fútbol' or not reg['clave_liga']:
                continue
            lados = _lados({'partido': reg['partido']})
            if not lados:
                continue
            for m in extras_futbol(reg['clave_liga'], lados[0], lados[1]):
                k = (m['categoria'], m['etiqueta'])
                if k in reg['_vistos']:
                    continue
                reg['_vistos'].add(k)
                reg['mercados'].append(m)

    for reg in por_partido.values():
        reg.pop('_vistos', None)

    return sorted(por_partido.values(),
                  key=lambda x: (x['deporte'], str(x['inicio'] or 'zz'),
                                 x['partido']))
