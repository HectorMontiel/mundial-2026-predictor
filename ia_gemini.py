#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v387 — LA IA DE SHARPICKS (Gemini): ANALIZA, PREDICE Y SE LE MIDE.

El usuario: «que pueda analizar el partido con todo lo que tenemos —el
modelo, el reciente, el H2H, toda la información de la aplicación— y dé una
predicción, y vamos a cuantificar sus aciertos y sus errores».

1. ANALIZAR. Para los partidos de fútbol con picks que empiezan en las
   próximas 30 h, se le dan a Gemini SÓLO nuestros datos (las probabilidades
   del mercado sin margen, nuestros picks con lo que se cumplen, el error de
   cuota si hay, la forma, el H2H y las bajas) y devuelve, en JSON: un
   análisis de 3-4 líneas en español sencillo, SUS probabilidades de local /
   empate / visita, si habrá más o menos de 2,5 goles, su confianza (1-5),
   el pick que más le gusta y si coincide con el nuestro.
2. MEDIR. Al terminar el partido se le pone su ✅/❌ (resultado y goles) y
   el del FAVORITO DEL MERCADO, que es la vara mínima: si la IA no le gana a
   «elegir al favorito», no aporta. La vista `ia_aciertos` lo resume.

Una vez por partido (lo ya analizado no se repite) y con tope por pasada,
para quedar dentro del nivel gratis de Gemini. Sin `GEMINI_API_KEY` o sin la
base, no hace nada. Nunca falla.

Ejecutar:  python ia_gemini.py [--seco]
"""
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional

logger = logging.getLogger('ia_gemini')
DATOS = os.environ.get('WEB_DATOS', os.path.join('web', 'datos', 'hoy.json'))
PRIVADO = os.environ.get('WEB_PRIVADO', os.path.join('datos_privados', 'premium.json'))
# v469 — sin los 2.5: Google los retiró y cada pasada gastaba consultas en un 404 (ia_uso: ok=0 siempre)
MODELOS = [m for m in (os.environ.get('GEMINI_MODELO'), 'gemini-flash-latest', 'gemini-flash-lite-latest') if m]
# v394 — VARIOS PARTIDOS POR CONSULTA. El nivel gratis cuenta CONSULTAS por día y
# por modelo, no partidos: con una por partido se agotaba a media mañana y la
# mayoría de los partidos se quedaban sin análisis (el usuario lo vio el 17-oct).
LOTE = int(os.environ.get('IA_LOTE', '5'))
MAX_POR_PASADA = int(os.environ.get('IA_MAX', '80'))
# v407 — 72 h: hoy, mañana y pasado (el usuario: «veo partidos de mañana y pasado
# mañana que no tienen el análisis de la IA, eso no debe pasar»)
HORAS = 72
# la unidad del «total» y del hándicap en cada deporte (la de nuestros picks)
_V407 = ('total_esperado', 'linea_total', 'pred_total', 'prob_total', 'ok_total',
         'linea_handicap', 'pred_handicap', 'prob_handicap', 'ok_handicap')
UNIDAD = {'Béisbol': 'Carreras',   # v423 — el béisbol de invierno
          'Fútbol': 'Goles', 'NHL': 'Goles', 'NBA': 'Puntos', 'NFL': 'Puntos',
          'MLB': 'Carreras', 'KBO': 'Carreras', 'Tenis': 'Sets'}
PAUSA_S = 4.5            # ~13 por minuto: debajo del límite del nivel gratis

ESQUEMA = {
    'type': 'OBJECT',
    'properties': {
        'analisis': {'type': 'STRING'},
        'p_local': {'type': 'NUMBER'}, 'p_empate': {'type': 'NUMBER'}, 'p_visita': {'type': 'NUMBER'},
        'pred_goles': {'type': 'STRING', 'enum': ['mas', 'menos']},
        'confianza': {'type': 'INTEGER'},
        'pick_ia': {'type': 'STRING'},
        'coincide': {'type': 'BOOLEAN'},
        # v392 — más precisa: marcador, goles esperados, ambos anotan, córners y tarjetas
        'marcador_probable': {'type': 'STRING'}, 'goles_esperados': {'type': 'NUMBER'},
        'ambos_anotan': {'type': 'STRING', 'enum': ['si', 'no']},
        'corners_esperados': {'type': 'NUMBER'}, 'linea_corners': {'type': 'NUMBER'},
        'pred_corners': {'type': 'STRING', 'enum': ['mas', 'menos']},
        'tarjetas_esperadas': {'type': 'NUMBER'}, 'linea_tarjetas': {'type': 'NUMBER'},
        'pred_tarjetas': {'type': 'STRING', 'enum': ['mas', 'menos']},
        # v394 — para saber qué meter: los goles de cada equipo y SU mejor apuesta
        'goles_local_esperados': {'type': 'NUMBER'}, 'goles_visita_esperados': {'type': 'NUMBER'},
        'mejor_apuesta': {'type': 'STRING'}, 'prob_mejor_apuesta': {'type': 'NUMBER'},
        # v396 — la probabilidad (0 a 1) de cada predicción, para saber qué tan fuerte es
        'prob_goles': {'type': 'NUMBER'}, 'prob_ambos_anotan': {'type': 'NUMBER'},
        'prob_corners': {'type': 'NUMBER'}, 'prob_tarjetas': {'type': 'NUMBER'}, 'prob_marcador': {'type': 'NUMBER'},
        # v407 — el TEMPLATE común a todos los deportes: total y hándicap con su probabilidad
        'total_esperado': {'type': 'NUMBER'}, 'linea_total': {'type': 'NUMBER'},
        'pred_total': {'type': 'STRING', 'enum': ['mas', 'menos']}, 'prob_total': {'type': 'NUMBER'},
        'linea_handicap': {'type': 'NUMBER'}, 'pred_handicap': {'type': 'STRING', 'enum': ['local', 'visita']},
        'prob_handicap': {'type': 'NUMBER'},
        # v391 — el usuario: «si ve que la apuesta que metemos no se va a cumplir, que lo diga»
        'veredictos': {'type': 'ARRAY', 'items': {'type': 'OBJECT', 'properties': {
            'apuesta': {'type': 'STRING'}, 'opinion': {'type': 'STRING', 'enum': ['a_favor', 'en_contra']},
            'motivo': {'type': 'STRING'}}, 'required': ['apuesta', 'opinion', 'motivo']}},
    },
    'required': ['analisis', 'p_local', 'p_empate', 'p_visita', 'pred_goles', 'confianza', 'pick_ia', 'coincide', 'veredictos',
                 'marcador_probable', 'goles_esperados', 'ambos_anotan', 'corners_esperados', 'linea_corners', 'pred_corners',
                 'tarjetas_esperadas', 'linea_tarjetas', 'pred_tarjetas', 'goles_local_esperados',
                 'goles_visita_esperados', 'mejor_apuesta', 'prob_mejor_apuesta', 'prob_goles', 'prob_ambos_anotan',
                 'prob_corners', 'prob_tarjetas', 'prob_marcador', 'total_esperado', 'linea_total', 'pred_total',
                 'prob_total', 'linea_handicap', 'pred_handicap', 'prob_handicap'],
}
# v447 — quién anota PRIMERO (o «nadie» si queda 0-0), con su probabilidad
ESQUEMA['properties']['primero_anota'] = {'type': 'STRING', 'enum': ['local', 'visita', 'nadie']}
ESQUEMA['properties']['prob_primero'] = {'type': 'NUMBER'}
ESQUEMA['required'] += ['primero_anota', 'prob_primero']
# v407 — los demás deportes: el mismo template sin lo que es sólo del fútbol
_COMUNES = ['analisis', 'p_local', 'p_empate', 'p_visita', 'confianza', 'pick_ia', 'coincide', 'veredictos',
            'marcador_probable', 'goles_local_esperados', 'goles_visita_esperados', 'mejor_apuesta',
            'prob_mejor_apuesta', 'prob_marcador', 'total_esperado', 'linea_total', 'pred_total', 'prob_total',
            'linea_handicap', 'pred_handicap', 'prob_handicap']
ESQUEMA_GEN = {'type': 'OBJECT',
               'properties': {k: ESQUEMA['properties'][k] for k in _COMUNES + ['ambos_anotan', 'prob_ambos_anotan', 'primero_anota', 'prob_primero']},
               'required': list(_COMUNES)}
ESQUEMA['properties']['partido'] = {'type': 'STRING'}
ESQUEMA['required'] = ['partido'] + ESQUEMA['required']
ESQUEMA_GEN['properties']['partido'] = {'type': 'STRING'}
ESQUEMA_GEN['required'] = ['partido'] + ESQUEMA_GEN['required']
ESQUEMA_LOTE = {'type': 'OBJECT', 'properties': {'partidos': {'type': 'ARRAY', 'items': ESQUEMA}},
                'required': ['partidos']}
ESQUEMA_LOTE_GEN = {'type': 'OBJECT', 'properties': {'partidos': {'type': 'ARRAY', 'items': ESQUEMA_GEN}},
                    'required': ['partidos']}
INSTRUCCION = (
    'Eres el analista de fútbol de SharPicks, una app mexicana de pronósticos. Recibes los datos de UN partido '
    'en JSON. Reglas: 1) Usa SÓLO esos datos; no inventes jugadores, lesiones, rachas ni noticias que no estén. '
    'Si vienen "noticias_recientes_web" (bajas, lesiones, sanciones, alineación probable, de medios), son datos: '
    'tómalas en cuenta y menciona en el análisis la baja más importante si la hay. '
    '2) Estima TUS probabilidades de que gane el local, empaten o gane el visitante (suman 1) y si habrá más o '
    'menos de 2.5 goles. Las probabilidades del mercado son una base muy buena: muévete de ellas sólo si la '
    'forma, el H2H o las bajas lo justifican claramente. 3) Escribe un análisis de 3 o 4 frases en español '
    'sencillo, para alguien que no sabe de estadística: qué dicen los datos y por qué. Nada de garantías ni de '
    '"apuesta segura". 4) Di cuál de NUESTROS picks te gusta más (copia su texto) o "ninguno", y si coincide '
    'con tu lectura del partido. 5) Confianza de 1 (muy dudoso) a 5 (muy claro). 6) Para CADA uno de nuestros '
    'picks (copia su texto exacto en "apuesta") di si estás "a_favor" o "en_contra" de que se cumpla, con un motivo '
    'de una frase. Sé honesto: si los datos dicen que un pick no se ve, dilo ("en_contra"), aunque tenga '
    'probabilidad alta; no lo digas por decir. 7) Sé PRECISO: da el marcador más probable ("1-2"), los goles '
    'totales esperados (con un decimal) y si ambos anotan. 8) Córners y tarjetas TOTALES del partido (de los dos '
    'equipos): estima cuántos habrá con los promedios de cada equipo y la media de la liga que te damos, elige la '
    'línea .5 más cercana a tu estimación (por ejemplo 9.5 córners, 4.5 tarjetas) y di si habrá más o menos. Si '
    'faltan los promedios, apóyate en la media de la liga y baja la confianza. Menciona en el análisis lo más '
    'llamativo de córners o tarjetas si lo hay. 9) Da los goles esperados de CADA equipo (un decimal) y tu mejor '
    'apuesta del partido en cualquier mercado (resultado, doble oportunidad, goles, goles de un equipo, ambos '
    'anotan, córners o tarjetas), con la probabilidad que le das (0 a 1): la que más se va a cumplir, no la que '
    'más paga. Escríbela EXACTAMENTE en uno de estos formatos (con el nombre del equipo tal como te llega): '
    '"Gana <equipo>", "Empate", "<equipo> o empate", "Goles: Más de 2.5", "Goles: Menos de 3.5", '
    '"Goles <equipo>: Más de 0.5", "Ambos anotan: Sí", "Ambos anotan: No", "Córners: Más de 8.5", '
    '"Tarjetas: Menos de 4.5". 11) Da la PROBABILIDAD (0 a 1) de cada predicción: la de tu lado de goles (más o menos de 2.5), la de que '
    'AMBOS anoten (sí), la de tu lado de córners, la de tu lado de tarjetas y la del marcador exacto (suele ser baja, '
    '0.08-0.15). Que sean coherentes con lo demás. 13) Y SIEMPRE el TOTAL de goles del partido con TU línea .5 '
    '(total_esperado, linea_total, más o menos, prob_total) y el HÁNDICAP del local (linea_handicap: por ejemplo -1.5 '
    'si el local es favorito, +1.5 si no; pred_handicap "local" si el local lo cubre, "visita" si no; prob_handicap). '
    '14) Di qué equipo anota PRIMERO (primero_anota: "local", "visita" o "nadie" si crees que queda 0-0) y su '
    'probabilidad (prob_primero, 0 a 1), con todo lo que sabes: goles esperados de cada uno, forma, bajas y noticias. '
    '12) Recibes una LISTA de partidos: responde uno por cada uno, en "partidos", copiando el campo '
    '"partido" tal cual.'
)


def instruccion(deporte: str) -> str:
    """v407 — la misma plantilla para cada deporte, con su unidad."""
    if deporte == 'Fútbol':
        return INSTRUCCION
    u = UNIDAD.get(deporte, 'Puntos')
    return (
        'Eres el analista de %s de SharPicks, una app mexicana de pronósticos. Recibes una LISTA de partidos en '
        'JSON: responde uno por cada uno, en "partidos", copiando el campo "partido" tal cual. Reglas: 1) Usa SÓLO '
        'esos datos; no inventes jugadores, lesiones ni noticias. Si vienen "noticias_recientes_web" (bajas, '
        'lesiones, sanciones, alineación probable, de medios), son datos: tómalas en cuenta y menciona la más '
        'importante. 2) Estima TUS probabilidades de que gane el local, '
        'el empate y el visitante (suman 1). En este deporte cuenta el GANADOR FINAL (con prórroga o penales si los '
        'hay), así que p_empate = 0. Las probabilidades de la casa y de nuestro modelo son una base muy buena: '
        'muévete de ellas sólo con motivo. 3) Análisis de 3 o 4 frases en español sencillo; nada de garantías ni de '
        '"apuesta segura". 4) Tu pick favorito de NUESTROS picks (copia su texto) o "ninguno", y si coincide con tu '
        'lectura. 5) Confianza de 1 a 5. 6) Para CADA uno de nuestros picks (texto exacto en "apuesta"): "a_favor" o '
        '"en_contra", con un motivo de una frase. Sé honesto. 7) Marcador más probable ("%s"), y %s esperados de '
        'cada uno (goles_local_esperados y goles_visita_esperados, con un decimal). 8) El TOTAL de %s del partido: '
        'total_esperado, tu línea .5 más cercana (linea_total), más o menos (pred_total) y su probabilidad '
        '(prob_total). 9) El HÁNDICAP del local en %s: linea_handicap (por ejemplo -%s si el local es favorito, +%s '
        'si no), pred_handicap "local" si el local lo cubre o "visita" si no, y prob_handicap. 10) Tu mejor apuesta '
        'del partido, la que MÁS se va a cumplir (no la que más paga), con su probabilidad (0 a 1), EXACTAMENTE en '
        'uno de estos formatos: "Gana <equipo>", "%s: Más de N.5", "%s: Menos de N.5", "Handicap: <equipo> +N.5"%s. '
        '11) La probabilidad del marcador exacto (baja).%s'
        % ('la ' + deporte if deporte in ('NHL', 'NBA', 'NFL', 'MLB', 'KBO') else 'tenis', '2-1' if deporte == 'Tenis' else '3-2',
           u.lower(), u.lower(), u.lower(), '1.5' if u in ('Goles', 'Carreras', 'Sets') else '5.5',
           '1.5' if u in ('Goles', 'Carreras', 'Sets') else '5.5', u, u,
           ', "Ambos anotan: Sí", "Ambos anotan: No"' if deporte == 'NHL' else '',
           ' 12) Di si AMBOS equipos anotan (ambos_anotan, prob_ambos_anotan). 13) Di qué equipo anota PRIMERO '
           '(primero_anota: "local" o "visita") y su probabilidad (prob_primero).' if deporte == 'NHL' else ''))


def _id(fecha, partido) -> str:
    return hashlib.sha1(('%s|%s' % (fecha, partido)).encode('utf-8')).hexdigest()[:20]


def _utc(s) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(s).replace(' ', 'T')[:19]).replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _mercado() -> Dict:
    """partido → {'1x2': {...}, 'mas25': p} del cálculo del día (sin margen)."""
    out = {}
    try:
        import precalculo_dia as pc
        for p in ((pc.leer() or {}).get('datos') or {}).get('pronosticos') or []:
            im = p.get('implicitas') or {}
            x = im.get('1x2') or {}
            fila = {'clave': p.get('clave_liga'),
                    # v407 — lo de nuestro modelo y las cuotas de la casa, en todos los deportes
                    'modelo': {k: round(float(v), 3) for k, v in list((p.get('board') or {}).items())[:12]
                               if isinstance(v, (int, float))},
                    'cuotas_casa': im.get('1x2_cuotas'), 'totales_casa': im.get('totales_cuotas')}
            if x.get('home') is not None:
                fila['1x2'] = {k: round(float(v), 3) for k, v in x.items()}
                fila['mas25'] = ((im.get('goles') or {}).get('2.5') or {}).get('p')
            out[p.get('partido')] = fila
    except Exception as e:
        logger.debug('[ia] mercado: %s', e)
    return out


def partidos(picks: List[Dict], ahora: dt.datetime) -> List[Dict]:
    """v407 — TODOS los partidos con picks (de todos los deportes) que empiezan en
    las próximas 72 h: los más cercanos y los mejores primero."""
    g = {}
    for p in picks:
        ini = _utc(p.get('inicio'))
        if (p.get('estado') != 'pendiente' or ini is None or p.get('tipo') == 'combinada'
                or not (ahora < ini <= ahora + dt.timedelta(hours=HORAS))):
            continue
        g.setdefault((p.get('fecha'), p.get('partido')), []).append(p)
    out = []
    for (fecha, partido), ps in g.items():
        peso = max((-1 if x.get('solo_analisis') else 3 if x.get('elige') else 2 if x.get('tipo') == 'error' else 1 if (x.get('prob') or 0) >= 0.85 else 0) for x in ps)
        out.append({'id': _id(fecha, partido), 'fecha': fecha, 'partido': partido, 'picks': ps, 'peso': peso,
                    'deporte': str(ps[0].get('deporte') or 'Fútbol'),
                    'inicio': ps[0].get('inicio'), 'liga': ps[0].get('liga'), 'ctx': next((x.get('ctx') for x in ps if x.get('ctx')), None)})
    # lo de las próximas 24 h primero (por peso), después mañana y pasado
    return sorted(out, key=lambda x: (str(x['inicio'])[:10] > (ahora + dt.timedelta(hours=24)).strftime('%Y-%m-%d'),
                                      -x['peso'], str(x['inicio'])))


def datos_del_partido(m: Dict, mercado: Dict) -> Dict:
    # v418 — la sugerencia del modelo de una tarjeta «sólo análisis» NO es un pick nuestro
    m = dict(m, picks=[x for x in m.get('picks') or [] if not x.get('solo_analisis')])
    mk = mercado.get(m['partido']) or {}
    ctx = m.get('ctx') or {}
    home, _, away = str(m['partido']).partition(' vs ')
    if m.get('deporte', 'Fútbol') != 'Fútbol':
        return {
            'partido': m['partido'], 'local': home, 'visitante': away, 'liga': m.get('liga'), 'deporte': m.get('deporte'),
            'unidad_del_total': UNIDAD.get(m.get('deporte'), 'Puntos'),
            'probabilidades_de_nuestro_modelo': mk.get('modelo'),
            'cuotas_de_la_casa': mk.get('cuotas_casa'), 'totales_de_la_casa': mk.get('totales_casa'),
            'nuestros_picks': [{'apuesta': x.get('apuesta'), 'cuota': x.get('cuota'),
                                'probabilidad_estimada': x.get('prob')} for x in m['picks']],
        }
    return {
        'partido': m['partido'], 'local': home, 'visitante': away, 'liga': m.get('liga'),
        'probabilidades_del_mercado_sin_margen': mk.get('1x2'),
        'probabilidad_mercado_mas_de_2_5_goles': mk.get('mas25'),
        'nuestros_picks': [{'apuesta': x.get('apuesta'), 'cuota': x.get('cuota'),
                            'se_cumplen_las_apuestas_asi': x.get('prob'),
                            'error_de_cuota': x.get('tipo') == 'error',
                            'paga_de_mas': x.get('ventaja')} for x in m['picks']],
        'forma_local_ultimos_5': ctx.get('fl'), 'forma_visitante_ultimos_5': ctx.get('fv'),
        'nota_forma': 'G=ganó, E=empató, P=perdió; el más reciente a la derecha',
        'h2h_ultimos': [{'fecha': h[0], 'local': h[1], 'marcador': h[2], 'visitante': h[3]} for h in ctx.get('h2h') or []],
        'bajas_local': ctx.get('bl'), 'bajas_visitante': ctx.get('bv'),
        # v392 — promedios de sus últimos 10 (gf/gc goles a favor/en contra, o25 y btts en proporción,
        # cor córners, tap tiros a puerta, tar amarillas, pos posesión %) y la media de la liga
        'promedios_local_ultimos_10': ctx.get('sl'), 'promedios_visitante_ultimos_10': ctx.get('sv'),
        'nota_promedios': 'gf=goles a favor, gc=en contra, o25=partidos con +2.5 goles, btts=ambos anotan, '
                          'cor=córners propios por partido, tap=tiros a puerta, tar=amarillas propias, pos=posesión %',
        'media_corners_liga_por_partido': _media_liga(mk.get('clave'), 'corners'),
        'media_tarjetas_liga_por_partido': _media_liga(mk.get('clave'), 'tarjetas'),
        # v469 — quién puede anotar y tirar a puerta (nuestro modelo, medido y calibrado)
        'jugadores_probables': [{'jugador': j.get('n'), 'equipo': home if lado == 'h' else away,
                                 'prob_anota': j.get('gol'), 'prob_1_o_mas_tiros_a_puerta': j.get('p1'),
                                 'prob_2_o_mas_tiros_a_puerta': j.get('p2')}
                                for lado in ('h', 'a') for j in ((m.get('jug') or {}).get(lado) or [])] or None,
        'nota_jugadores': 'probabilidades medidas de nuestro modelo (ya cuentan que puede no jugar); si las '
                          'noticias dicen que uno está lesionado o suspendido, dilo en el análisis',
    }


def _media_liga(clave, que):
    """Media OBSERVADA de la liga (córners o tarjetas totales por partido); None si no hay."""
    if not clave:
        return None
    try:
        import rendimiento_equipos as rq
        if que == 'corners':
            return rq.media_corners_liga(clave)
        _d, ts = rq._serie_tarjetas(clave)    # (histórico, (tarjetas local, tarjetas visita)) observadas
        if not ts:
            return None
        tot = (ts[0] + ts[1]).dropna()
        return round(float(tot.tail(1000).mean()), 2) if len(tot) >= 100 else None
    except Exception:
        return None


_AGOTADOS: set = set()
_AGOTADOS_WEB: set = set()
# v450 — EL CUPO DE GEMINI ES EL CUELLO DE BOTELLA (el usuario: «no quiero gastarme
# todo; midamos cuánto nos sobra»). Se cuenta cada consulta por modelo y para qué
# (análisis, búsqueda, ventana) y se guarda en `ia_uso`. Y se reparte por prioridad:
# los partidos CON PICK van con el mejor modelo y con búsqueda; los de «sólo
# análisis», con el modelo lite y sin búsqueda; la medición, sólo con lo que sobra.
USO: Dict = {}
LITE = [m for m in MODELOS if 'lite' in m] + [m for m in MODELOS if 'lite' not in m]


# v451 — EL USUARIO: «priorizar las ligas principales (con y sin pick), después los
# picks y después los de sólo análisis». Las principales del fútbol son las de
# `modo_modelo.PRINCIPALES` (la lista corta del proyecto); en los demás deportes,
# su liga grande (NBA, NFL, NHL, MLB).
PRINCIPAL_OTROS = {'NBA', 'NFL', 'NHL', 'MLB'}
_PRINC: Optional[set] = None


def _principales() -> set:
    global _PRINC
    if _PRINC is None:
        try:
            import modo_modelo
            import nombres_ligas
            _PRINC = set(modo_modelo.PRINCIPALES) | {nombres_ligas.canonica('', k, 'Fútbol') for k in modo_modelo.PRINCIPALES}
        except Exception:
            _PRINC = set()
    return _PRINC


def _de_selecciones(liga: str) -> bool:
    """v451 — el usuario: «los partidos internacionales también cuentan como principal:
    amistosos, Mundial o cualquier partido de selecciones». Lo que `nombres_ligas` ya
    reconoce como de selecciones absolutas, y el Mundial (no el de clubes ni juveniles)."""
    import re
    try:
        import nombres_ligas as nl
        t = nl._n(liga)
        r = nl._de_selecciones(t)
        if r and r != 'Amistosos de clubes':
            return True
        return bool(re.search(r'world cup|mundial|copa del mundo', t)) and not re.search(r'club|u-?\d{2}|sub-?\d{2}|youth|juvenil', t)
    except Exception:
        return False


def nivel(m: Dict, mercado: Dict) -> int:
    """0 = liga principal o selecciones (con o sin pick) · 1 = con pick · 2 = sólo análisis."""
    dep = m.get('deporte') or 'Fútbol'
    if dep != 'Fútbol':
        principal = dep in PRINCIPAL_OTROS
    else:
        clave = (mercado.get(m.get('partido')) or {}).get('clave')
        liga = str(m.get('liga') or '')
        try:
            import nombres_ligas
            liga_c = nombres_ligas.canonica(liga, '', 'Fútbol')     # «Champions League» → «UEFA Champions League»
        except Exception:
            liga_c = liga
        principal = clave in _principales() or liga in _principales() or liga_c in _principales() or _de_selecciones(liga)
    return 0 if principal else 1 if m.get('peso', 0) >= 0 else 2


def _contar(modelo: str, tipo: str, ok: bool, agotado: bool = False):
    u = USO.setdefault((modelo, tipo), {'llamadas': 0, 'ok': 0, 'agotado': False})
    u['llamadas'] += 1
    u['ok'] += int(ok)
    u['agotado'] = u['agotado'] or agotado
# v446 — EL USUARIO: «la IA tiene acceso a internet: que complemente con las
# alineaciones, las bajas y las noticias recientes, en todos los partidos». Hasta
# aquí sólo veía nuestros datos. Ahora, ANTES del análisis, una consulta con la
# búsqueda de Google trae lo CONFIRMADO de cada partido del lote (con su fuente);
# el análisis sigue igual y lo recibe como un dato más. Si la búsqueda falla o se
# acaba su cupo, se analiza como antes (sin noticias) y queda marcado, para medir.
_V446 = ('con_noticias', 'noticias')
BUSCAR = os.environ.get('IA_BUSCAR', '1') != '0'
INSTRUCCION_WEB = (
    'Busca en la web noticias de los últimos 3 días de cada partido de la lista (deporte y liga incluidos). '
    'Para CADA uno da sólo hechos confirmados por medios o cuentas oficiales: jugadores lesionados o '
    'suspendidos, dudas importantes, la alineación probable o confirmada si existe, y cualquier noticia que '
    'cambie el partido (rotaciones, cambio de entrenador, clima extremo). Nada de opiniones ni pronósticos. '
    'Si no hay nada confirmado, di "sin novedades". Responde SÓLO con JSON, sin texto antes ni después: '
    '{"partidos": [{"partido": "<copia el texto tal cual>", "noticias": ["<hecho breve>", ...], '
    '"fuentes": ["<medio>", ...]}]}'
)


# v469 — LAS NOTICIAS DE VERDAD. La búsqueda de Gemini NUNCA funcionó: en ia_uso, todos los días,
# «busqueda» con ok=0 (su cupo gratis se acaba al empezar el día) y los análisis con
# con_noticias=false. Ahora los titulares salen de Google News (RSS): gratis, sin clave, de los
# últimos 3 días y SÓLO los publicados antes del inicio. La búsqueda de Gemini queda de respaldo.
RSS = os.environ.get('IA_RSS', '1') != '0'
RSS_URL = 'https://news.google.com/rss/search'
_SIN_INFO = __import__('re').compile(r'd[oó]nde ver|hora y (canal|d[oó]nde)|canal y hora|en (vivo|directo)|comentarios en directo|'
                                     r'resultados? en vivo|minuto a minuto|live stream', __import__('re').I)


def _nombre_busqueda(equipo: str) -> str:
    """El nombre más largo que conocen los alias («Ath Madrid» → «Atlético Madrid»)."""
    try:
        import name_mapper as nm
        al = nm._cargar_alias().get(nm.normalizar(equipo)) or []
        return max([equipo] + [a for a in al if isinstance(a, str)], key=len)
    except Exception:
        return equipo


def noticias_rss(lista: List[Dict]) -> Dict:
    """{partido: {'noticias': [titulares], 'fuentes': [medios]}} de Google News; {} si falla."""
    import email.utils
    import xml.etree.ElementTree as ET
    import requests
    if not RSS:
        return {}
    out = {}
    for m in lista:
        lados = str(m.get('partido') or '')
        sep = ' vs ' if ' vs ' in lados else (' @ ' if ' @ ' in lados else None)
        if not sep:
            continue
        a, b = [_nombre_busqueda(x.strip()) for x in lados.split(sep, 1)]
        try:
            ini = dt.datetime.fromisoformat(str(m.get('inicio')).replace(' ', 'T').replace('Z', '+00:00'))
            ini = ini if ini.tzinfo else ini.replace(tzinfo=dt.timezone.utc)
        except Exception:
            ini = None
        items = []
        for q in ('"%s" "%s" when:3d' % (a, b), '%s %s when:3d' % (a, b)):
            try:
                r = requests.get(RSS_URL, params={'q': q, 'hl': 'es-419', 'gl': 'MX', 'ceid': 'MX:es-419'},
                                 timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
                items = ET.fromstring(r.text).findall('.//item') if r.ok else []
            except Exception as e:
                logger.debug('[ia] noticias %s: %s', lados, e)
                items = []
            if items:
                break
        ns, fs = [], []
        for it in items:
            try:
                pub = email.utils.parsedate_to_datetime(it.findtext('pubDate') or '')
            except Exception:
                pub = None
            if ini and pub and pub >= ini:              # lo publicado después del inicio no cuenta
                continue
            t, _, fuente = (it.findtext('title') or '').rpartition(' - ')
            t = (t or it.findtext('title') or '').strip()
            if _SIN_INFO.search(t):                     # «dónde ver», «hora y canal», «en directo»: no dicen nada
                continue
            if t and t not in ns:
                ns.append(t[:200])
                if fuente and fuente not in fs:
                    fs.append(fuente[:60])
            if len(ns) >= 6:
                break
        if ns:
            out[lados] = {'noticias': ns, 'fuentes': fs[:4]}
        time.sleep(0.3)
    return out


def noticias_web(lista: List[Dict], tipo: str = 'busqueda') -> Dict:
    """{partido: {'noticias': [...], 'fuentes': [...]}} con la búsqueda de Google;
    {} si no hay clave, se acabó el cupo o algo falla (el análisis sigue sin ellas)."""
    import requests
    k = os.environ.get('GEMINI_API_KEY')
    if not k or not BUSCAR:
        return {}
    pide = [{'partido': m.get('partido'), 'deporte': m.get('deporte') or 'Fútbol', 'liga': m.get('liga'),
             'inicio': str(m.get('inicio') or '')} for m in lista]
    cuerpo = {'systemInstruction': {'parts': [{'text': INSTRUCCION_WEB}]},
              'contents': [{'role': 'user', 'parts': [{'text': json.dumps(pide, ensure_ascii=False)}]}],
              'tools': [{'google_search': {}}], 'generationConfig': {'temperature': 0.2}}
    for modelo in MODELOS:
        if modelo in _AGOTADOS_WEB:
            continue
        try:
            r = requests.post('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % modelo,
                              params={'key': k}, json=cuerpo, timeout=90)
            _contar(modelo, tipo, r.ok, r.status_code == 429)
            if r.status_code in (404, 429):   # v449 — 404: ese modelo ya no existe; 429: sin cupo hoy
                logger.warning('[ia] búsqueda %s: %s', modelo, 'sin cupo hoy' if r.status_code == 429 else 'el modelo ya no existe')
                _AGOTADOS_WEB.add(modelo)
                continue
            if not r.ok:
                logger.warning('[ia] búsqueda %s respondió %s: %s', modelo, r.status_code, r.text[:160].replace('\n', ' '))
                continue
            cand = r.json()['candidates'][0]
            txt = ''.join(x.get('text', '') for x in cand.get('content', {}).get('parts', []))
            ini, fin = txt.find('{'), txt.rfind('}')
            datos = json.loads(txt[ini:fin + 1]) if ini >= 0 and fin > ini else {}
            if not datos.get('partidos'):     # v449 — no vino lo pedido: se dice y se prueba el siguiente modelo
                logger.warning('[ia] búsqueda %s: respuesta sin la lista de partidos: %s', modelo, txt[:160].replace('\n', ' '))
                continue
            webs = [c.get('web', {}).get('title') for c in (cand.get('groundingMetadata') or {}).get('groundingChunks') or []]
            out = {}
            for d in datos.get('partidos') or []:
                ns = [str(x)[:200] for x in (d.get('noticias') or []) if str(x).strip() and 'sin novedades' not in str(x).lower()][:6]
                fs = [str(x)[:60] for x in (d.get('fuentes') or []) if str(x).strip()][:4] or [w for w in webs if w][:4]
                out[str(d.get('partido') or '')] = {'noticias': ns, 'fuentes': fs}
            return out
        except Exception as e:
            logger.warning('[ia] búsqueda %s: %s', modelo, type(e).__name__)
    return {}


def preguntar(lista: List[Dict], deporte: str = 'Fútbol', tipo: str = 'analisis', modelos: Optional[List[str]] = None) -> Optional[Dict]:
    """{partido: análisis} de un lote; {'_limite': True} si TODOS los modelos
    agotaron su cupo del día. Cada modelo tiene su propio cupo: si uno dice 429
    se pasa al siguiente (antes se paraba la pasada entera en el primero)."""
    import requests
    k = os.environ.get('GEMINI_API_KEY')
    if not k:
        return None
    cuerpo = {'systemInstruction': {'parts': [{'text': instruccion(deporte)}]},
              'contents': [{'role': 'user', 'parts': [{'text': json.dumps(lista, ensure_ascii=False)}]}],
              'generationConfig': {'temperature': 0.3, 'responseMimeType': 'application/json',
                                   'responseSchema': ESQUEMA_LOTE if deporte == 'Fútbol' else ESQUEMA_LOTE_GEN}}
    for modelo in (modelos or MODELOS):
        if modelo in _AGOTADOS:
            continue
        try:
            for intento in range(3):          # 503 = Gemini saturado: se espera y se reintenta
                r = requests.post('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % modelo,
                                  params={'key': k}, json=cuerpo, timeout=60)
                if r.status_code != 503:
                    break
                time.sleep(6 * (intento + 1))
            _contar(modelo, tipo, r.ok, r.status_code == 429)
            if r.status_code in (404, 429):   # v449 — 404: el modelo ya no existe (Google retiró los 2.5)
                logger.warning('[ia] %s: %s; se prueba el siguiente modelo', modelo,
                               'límite del nivel gratis' if r.status_code == 429 else 'ya no existe')
                _AGOTADOS.add(modelo)
                continue
            if not r.ok:
                logger.warning('[ia] %s respondió %s', modelo, r.status_code)
                continue
            txt = r.json()['candidates'][0]['content']['parts'][0]['text']
            fuera = {}
            for d in json.loads(txt).get('partidos') or []:
                d['_modelo'] = modelo
                fuera[str(d.get('partido') or '')] = d
            return fuera
        except Exception as e:
            logger.warning('[ia] %s: %s', modelo, type(e).__name__)
    if all(m in _AGOTADOS for m in MODELOS):
        return {'_limite': True}
    return None


def fila(m: Dict, d: Dict, mercado: Dict) -> Dict:
    pl, pe, pv = (max(0.0, float(d.get(k) or 0)) for k in ('p_local', 'p_empate', 'p_visita'))
    s = (pl + pe + pv) or 1.0
    pl, pe, pv = pl / s, pe / s, pv / s
    mk = (mercado.get(m['partido']) or {}).get('1x2') or {}
    return {'id': m['id'], 'fecha': m['fecha'], 'inicio': str(m['inicio']), 'deporte': m.get('deporte', 'Fútbol'),
            'liga': m.get('liga'),
            # v407 — el template común: total y hándicap con su probabilidad
            'total_esperado': _num(d.get('total_esperado')), 'linea_total': _linea(d.get('linea_total')),
            'pred_total': d.get('pred_total') if d.get('pred_total') in ('mas', 'menos') else None,
            'prob_total': _prob(d.get('prob_total')), 'linea_handicap': _linea_h(d.get('linea_handicap')),
            'pred_handicap': d.get('pred_handicap') if d.get('pred_handicap') in ('local', 'visita') else None,
            'prob_handicap': _prob(d.get('prob_handicap')),
            'partido': m['partido'], 'analisis': str(d.get('analisis') or '')[:900],
            'pred_resultado': ['local', 'empate', 'visita'][max(range(3), key=lambda i: (pl, pe, pv)[i])],
            'p_local': round(pl, 3), 'p_empate': round(pe, 3), 'p_visita': round(pv, 3),
            'pred_goles': d.get('pred_goles') if d.get('pred_goles') in ('mas', 'menos') else None,
            'confianza': max(1, min(5, int(d.get('confianza') or 3))), 'pick_ia': str(d.get('pick_ia') or '')[:160],
            'coincide': bool(d.get('coincide')), 'modelo': d.get('_modelo'),
            'veredictos': [{'apuesta': str(v.get('apuesta') or '')[:160], 'opinion': v.get('opinion'),
                            'motivo': str(v.get('motivo') or '')[:240]}
                           for v in (d.get('veredictos') or []) if v.get('opinion') in ('a_favor', 'en_contra')][:8],
            'p_mercado_local': mk.get('home'), 'p_mercado_empate': mk.get('draw'), 'p_mercado_visita': mk.get('away'),
            'clave_liga': (mercado.get(m['partido']) or {}).get('clave'),
            'marcador_ia': str(d.get('marcador_probable') or '').replace(' ', '')[:7] or None,
            'goles_esperados': _num(d.get('goles_esperados')), 'btts': d.get('ambos_anotan') if d.get('ambos_anotan') in ('si', 'no') else None,
            'corners_esperados': _num(d.get('corners_esperados')), 'linea_corners': _linea(d.get('linea_corners')),
            'pred_corners': d.get('pred_corners') if d.get('pred_corners') in ('mas', 'menos') else None,
            'tarjetas_esperadas': _num(d.get('tarjetas_esperadas')), 'linea_tarjetas': _linea(d.get('linea_tarjetas')),
            'pred_tarjetas': d.get('pred_tarjetas') if d.get('pred_tarjetas') in ('mas', 'menos') else None,
            'goles_local_esperados': _num(d.get('goles_local_esperados')),
            'goles_visita_esperados': _num(d.get('goles_visita_esperados')),
            'mejor_apuesta': str(d.get('mejor_apuesta') or '')[:160] or None,
            'prob_mejor_apuesta': _prob(d.get('prob_mejor_apuesta')),
            'prob_goles': _prob(d.get('prob_goles')), 'prob_ambos': _prob(d.get('prob_ambos_anotan')),
            'prob_corners': _prob(d.get('prob_corners')), 'prob_tarjetas': _prob(d.get('prob_tarjetas')),
            'prob_marcador': _prob(d.get('prob_marcador')),
            # v447 — quién anota primero
            'primero_anota': d.get('primero_anota') if d.get('primero_anota') in ('local', 'visita', 'nadie') else None,
            'prob_primero': _prob(d.get('prob_primero'))}


def _linea_h(x):
    """La línea de hándicap siempre en .5 (con su signo): -1.2 → -1.5, 0 → +0.5."""
    v = _num(x)
    if v is None:
        return None
    v = round(v * 2) / 2
    if v == int(v):
        v = v + 0.5 if v >= 0 else v - 0.5
    return v


def _prob(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    v = v / 100 if v > 1 else v
    return round(min(max(v, 0.0), 1.0), 3)


def _num(x):
    try:
        return round(float(x), 1)
    except (TypeError, ValueError):
        return None


def _linea(x):
    """Siempre una línea .5 (para que no haya empate con el real)."""
    v = _num(x)
    return None if v is None else float(int(v)) + 0.5


# ---------- la base ----------
def _sb():
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return None
    return url.rstrip('/') + '/rest/v1/ia_analisis', {'apikey': key, 'Authorization': 'Bearer ' + key,
                                                      'Content-Type': 'application/json'}


def ya_hechos(sb) -> Optional[set]:
    import requests
    desde = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    r = requests.get(sb[0], headers=sb[1], params={'select': 'id,veredictos,mejor_apuesta,prob_total', 'fecha': 'gte.' + desde,
                                                   'limit': 5000}, timeout=30)
    # v394-v407 — lo analizado con un esquema viejo (sin «qué meter», sin probabilidades o sin el
    # template común de total y hándicap) se vuelve a pedir
    if not r.ok:
        # sin la migración v407 la columna no existe: se usa el criterio anterior
        # (si no, se volvería a pedir TODO en cada pasada y se gastaría el cupo)
        r = requests.get(sb[0], headers=sb[1], params={'select': 'id,veredictos,mejor_apuesta', 'fecha': 'gte.' + desde,
                                                       'limit': 5000}, timeout=30)
        return {x['id'] for x in r.json() if x.get('veredictos') is not None and x.get('mejor_apuesta')} if r.ok else None
    return {x['id'] for x in r.json() if x.get('veredictos') is not None and x.get('mejor_apuesta')
            and x.get('prob_total') is not None}


def _final(partido: str, fecha: str, picks: List[Dict]):
    """(goles local, goles visita) del partido terminado: de nuestros picks ya
    liquidados o del histórico de Flashscore."""
    for p in picks:
        if p.get('partido') == partido and p.get('estado') in ('verde', 'roja') and p.get('marcador'):
            try:
                a, b = str(p['marcador']).split('-')
                return int(a), int(b)
            except Exception:
                pass
    try:
        import errores_web
        df, idx = errores_web._flashscore()
        home, _, away = partido.partition(' vs ')
        comun = sorted(set(idx.get(home.strip(), [])) & set(idx.get(away.strip(), [])))
        if comun:
            m = df.iloc[comun]
            m = m[m['date'].dt.strftime('%Y-%m-%d') >= str(fecha)]
            if len(m):
                r = m.iloc[0]
                return (int(r.gh), int(r.ga)) if r.home == home.strip() else (int(r.ga), int(r.gh))
    except Exception:
        pass
    return None


def _corners_tarjetas(x: Dict):
    """Córners y tarjetas TOTALES reales del partido, del histórico de su liga
    (llega con la actualización de datos del día). (None, None) si aún no."""
    try:
        import pandas as pd
        import panel_equipos as pe
        h = pe._historico(x.get('clave_liga')) if x.get('clave_liga') else None
        if h is None or getattr(h, 'empty', True):
            return None, None
        home, _, away = str(x['partido']).partition(' vs ')
        f = pd.Timestamp(str(x.get('fecha')))
        h = h[(h['home_team'] == home.strip()) & (h['away_team'] == away.strip())]
        h = h[(pd.to_datetime(h['date']) - f).abs() <= pd.Timedelta(days=1)]
        if not len(h):
            return None, None
        r = h.iloc[-1]
        k = (r.get('home_corners'), r.get('away_corners'))
        t = (r.get('home_yellow'), r.get('away_yellow'), r.get('home_red', 0), r.get('away_red', 0))
        kk = int(k[0] + k[1]) if all(pd.notna(v) for v in k) else None
        tt = int(sum(v for v in t if pd.notna(v))) if pd.notna(t[0]) and pd.notna(t[1]) else None
        return kk, tt
    except Exception:
        return None, None


def _lado(nombre: str, home: str, away: str) -> Optional[str]:
    """'h' o 'a' según a qué equipo del partido se refiere `nombre`."""
    import name_mapper as nm
    n = nm.normalizar(nombre)
    for k, eq in (('h', home), ('a', away)):
        e = nm.normalizar(eq)
        if n and e and (n == e or n in e or e in n):
            return k
    m = nm.mapear(nombre, [home, away], contexto='ia_mejor')
    return 'h' if m == home else 'a' if m == away else None


def liquidar(apuesta: str, home: str, away: str, g, corners=None, tarjetas=None) -> Optional[bool]:
    """v399 — ✅/❌ de «lo que metería la IA», con el marcador final y, si hace
    falta, los córners o tarjetas reales. None si no se puede calificar (aún no
    hay córners, o la IA no usó el formato): NO se cuenta, ni como verde ni roja."""
    import re
    a = str(apuesta or '').strip().rstrip('.').replace('Mas de', 'Más de')
    if not a or not g:
        return None
    gh, ga = g
    m = re.match(r'^Handicap: (.+) ([+-][\d.]+)$', a, re.I)
    if m:
        k = _lado(m.group(1), home, away)
        if not k:
            return None
        h = float(m.group(2))
        return (gh + h > ga) if k == 'h' else (ga + h > gh)
    m = re.match(r'^(Goles|Puntos|Carreras|Sets|Total|Córners|Corners|Tarjetas): (Más|Menos) de ([\d.]+)$', a, re.I)
    if m:
        total = {'goles': gh + ga, 'puntos': gh + ga, 'carreras': gh + ga, 'sets': gh + ga, 'total': gh + ga,
                 'córners': corners, 'corners': corners, 'tarjetas': tarjetas}[m.group(1).lower()]
        if total is None:
            return None
        return (total > float(m.group(3))) == (m.group(2).lower() == 'más')
    m = re.match(r'^Goles (.+): (Más|Menos) de ([\d.]+)$', a, re.I)
    if m:
        k = _lado(m.group(1), home, away)
        if not k:
            return None
        return ((gh if k == 'h' else ga) > float(m.group(3))) == (m.group(2).lower() == 'más')
    m = re.match(r'^Ambos anotan: (Sí|Si|No)$', a, re.I)
    if m:
        return (gh > 0 and ga > 0) == (m.group(1).lower() != 'no')
    if a.lower() == 'empate':
        return gh == ga
    m = re.match(r'^(.+) o empate$', a, re.I)
    if m:
        k = _lado(m.group(1), home, away)
        return None if not k else (gh >= ga if k == 'h' else ga >= gh)
    m = re.match(r'^Gana (.+)$', a, re.I)
    if m:
        k = _lado(m.group(1), home, away)
        return None if not k else (gh > ga if k == 'h' else ga > gh)
    return None


def _primer_gol(x: Dict, picks: List[Dict]) -> Optional[str]:
    """v447 — 'local' o 'visita': quién anotó el primer gol, de las jugadas clave de
    ESPN. None si no se sabe (sin ESPN, sin jugadas o fue autogol): NO se califica."""
    import requests
    esp = next((p.get('espn') for p in picks if p.get('partido') == x['partido'] and p.get('espn')), None)
    if not esp or ':' not in str(esp):
        return None
    ruta, eid = str(esp).split(':', 1)
    try:
        d = requests.get('https://site.api.espn.com/apis/site/v2/sports/%s/summary' % ruta, params={'event': eid}, timeout=20).json()
    except Exception:
        return None
    evs = [e for e in (d.get('keyEvents') or d.get('scoringPlays') or []) if e.get('scoringPlay', True)
           and (e.get('team') or {}).get('displayName')]
    if not evs or 'own' in str((evs[0].get('type') or {}).get('text') or '').lower():
        return None
    home, _, away = str(x['partido']).partition(' vs ')
    return {'h': 'local', 'a': 'visita'}.get(_lado(evs[0]['team']['displayName'], home, away))


def evaluar(sb, picks: List[Dict]) -> int:
    """✅/❌ a lo que la IA predijo de los partidos ya terminados."""
    import requests
    hace = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2.5)).isoformat()
    tres = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
    r = requests.get(sb[0], headers=sb[1], timeout=30,
                     params={'select': '*', 'inicio': 'lt.' + hace, 'limit': 500,
                             'or': '(evaluado.is.null,and(corners_real.is.null,linea_corners.not.is.null,inicio.gt.%s),'
                                   'and(ok_mejor.is.null,mejor_apuesta.not.is.null,inicio.gt.%s))' % (tres, tres)})
    n = 0
    for x in (r.json() if r.ok else []):
        g = _final(x['partido'], x['fecha'], picks)
        if not g:
            continue
        real = 'local' if g[0] > g[1] else ('visita' if g[0] < g[1] else 'empate')
        mk = [x.get('p_mercado_local'), x.get('p_mercado_empate'), x.get('p_mercado_visita')]
        fav = ['local', 'empate', 'visita'][max(range(3), key=lambda i: mk[i] or 0)] if all(v is not None for v in mk) else None
        est = {p.get('apuesta'): p.get('estado') for p in picks if p.get('partido') == x['partido']}
        vs = [dict(v, estado=est.get(v.get('apuesta'))) for v in (x.get('veredictos') or [])]
        futbol = (x.get('deporte') or 'Fútbol') == 'Fútbol'
        k_real, t_real = _corners_tarjetas(x) if futbol else (None, None)
        extra = {'ok_marcador': (str(x.get('marcador_ia') or '') == '%d-%d' % g) if x.get('marcador_ia') else None,
                 'ok_btts': ((x['btts'] == 'si') == (g[0] > 0 and g[1] > 0)) if x.get('btts') else None}
        if k_real is not None and x.get('linea_corners') is not None and x.get('pred_corners'):
            extra.update(corners_real=k_real, ok_corners=(k_real > float(x['linea_corners'])) == (x['pred_corners'] == 'mas'))
        if t_real is not None and x.get('linea_tarjetas') is not None and x.get('pred_tarjetas'):
            extra.update(tarjetas_real=t_real, ok_tarjetas=(t_real > float(x['linea_tarjetas'])) == (x['pred_tarjetas'] == 'mas'))
        # v399 — lo que metería la IA, también verde o roja
        home, _, away = str(x['partido']).partition(' vs ')
        okm = liquidar(x.get('mejor_apuesta'), home, away, g, k_real, t_real) if x.get('mejor_apuesta') else None
        if okm is not None:
            extra['ok_mejor'] = okm
        # v407 — el total y el hándicap del template (todos los deportes)
        if x.get('linea_total') is not None and x.get('pred_total'):
            extra['ok_total'] = (sum(g) > float(x['linea_total'])) == (x['pred_total'] == 'mas')
        if x.get('linea_handicap') is not None and x.get('pred_handicap'):
            extra['ok_handicap'] = (g[0] + float(x['linea_handicap']) > g[1]) == (x['pred_handicap'] == 'local')
        if x.get('primero_anota') and x.get('ok_primero') is None:     # v447 — quién anotó primero
            real1 = 'nadie' if sum(g) == 0 else _primer_gol(x, picks)
            if real1:
                extra['ok_primero'] = x['primero_anota'] == real1
        if x.get('evaluado'):                 # ya evaluado: sólo faltaban córners/tarjetas o lo que metería
            falta = {k: v for k, v in extra.items()
                     if k.startswith(('corners', 'ok_corners', 'tarjetas', 'ok_tarjetas'))
                     or (k in ('ok_mejor', 'ok_total', 'ok_handicap', 'ok_primero') and x.get(k) is None)}
            if falta:
                u = requests.patch(sb[0], headers=sb[1], params={'id': 'eq.' + x['id']}, json=falta, timeout=30)
                n += bool(u.ok)
            continue
        cambio = dict(extra, **{'marcador': '%d-%d' % g, 'ok_resultado': x['pred_resultado'] == real, 'veredictos': vs})
        cambio.update({
                  'ok_goles': (x['pred_goles'] == ('mas' if sum(g) > 2.5 else 'menos')) if x.get('pred_goles') else None,
                  'ok_mercado': (fav == real) if fav else None, 'evaluado': dt.datetime.now(dt.timezone.utc).isoformat()})
        u = requests.patch(sb[0], headers=sb[1], params={'id': 'eq.' + x['id']}, json=cambio, timeout=30)
        n += bool(u.ok)
    return n


_V447 = ('primero_anota', 'prob_primero')


def guardar(sb, filas: List[Dict]):
    """Sube las filas. Si la base aún no tiene columnas nuevas (migración
    pendiente), se guarda sin ellas, quitando primero las más nuevas."""
    import requests
    h = dict(sb[1], Prefer='resolution=merge-duplicates,return=minimal')
    r = requests.post(sb[0], headers=h, json=filas, timeout=30)
    for grupo in (_V447, _V446, _V407):
        if r.ok or 'column' not in r.text.lower():
            break
        logger.warning('[ia] la base no tiene columnas nuevas: se guarda sin %s', grupo[0])
        filas = [{k: v for k, v in f.items() if k not in grupo} for f in filas]
        r = requests.post(sb[0], headers=h, json=filas, timeout=30)
    return r


def analizar(sb, lista: List[Dict], mercado: Dict, ventana: Optional[str] = None):
    """En lotes por deporte: primero las noticias de la web, luego el análisis, y se
    guarda. Devuelve (cuántos, si se acabó el cupo de todos los modelos)."""
    hechos = 0
    lotes = []
    for nv in (0, 1, 2):                      # v451 — principales, luego con pick, luego sólo análisis
        for dep in dict.fromkeys(m.get('deporte', 'Fútbol') for m in lista):
            del_dep = [m for m in lista if m.get('deporte', 'Fútbol') == dep and nivel(m, mercado) == nv]
            lotes += [(dep, nv < 2, del_dep[i:i + LOTE]) for i in range(0, len(del_dep), LOTE)]
    for dep, con_pick, lote in lotes:
        tipo = 'ventana' if ventana else 'analisis' if con_pick else 'solo_analisis'
        # v469 — Google News para TODOS (es gratis); la búsqueda de Gemini sólo de respaldo con pick
        web = noticias_rss(lote) if dep == 'Fútbol' else {}
        if not web and con_pick:
            web = noticias_web(lote, 'busqueda_ventana' if ventana else 'busqueda')
        entrada = []
        for m in lote:
            d = datos_del_partido(m, mercado)
            w = web.get(m['partido'])
            if w and w['noticias']:
                d['noticias_recientes_web'] = w['noticias']
                d['fuentes_de_las_noticias'] = w['fuentes']
            entrada.append(d)
        res = preguntar(entrada, dep, tipo, None if con_pick and not ventana else LITE)
        if res and res.get('_limite'):
            print('ia: todos los modelos agotaron su cupo de hoy')
            return hechos, True
        filas = [fila(m, res[m['partido']], mercado) for m in lote if res and m['partido'] in res]
        for f in filas:                     # v446 — para medir si con noticias acierta más
            w = web.get(f['partido'])
            f['con_noticias'] = bool(w and w['noticias'])
            f['noticias'] = ' | '.join(w['noticias'])[:900] if f['con_noticias'] else None
            if ventana:                     # v447 — la misma fila, guardada aparte con su hora
                f['base'], f['id'], f['ventana'] = f['id'], f['id'] + '|' + ventana, ventana
        if filas:
            r = guardar(sb, filas)
            if r.ok:
                hechos += len(filas)
            else:
                logger.warning('[ia] la base rechazó el lote: %s %s', r.status_code, r.text[:200])
        time.sleep(PAUSA_S)
    return hechos, False


# v447 — EL USUARIO: «midamos a qué hora acierta más y, si sale bien, agarremos el
# mejor grupo horario para cada segmento». El análisis de siempre sigue igual (es
# el que se enseña); además, cada partido CON PICK se vuelve a analizar —con las
# noticias de la web— en tres horas antes del inicio. Se guarda en `ia_ventanas`
# (no lo ve el usuario), se califica igual y se compara por deporte y predicción.
# v450 — más chica para cuidar el cupo: sólo fútbol, ~6 h y ~2 h, 15 por pasada y
# 60 por día, con el modelo lite (el que hace casi todos los análisis): así se
# comparan horas con el mismo modelo, no modelos distintos.
VENTANAS = [('v6', 4.0, 8.0), ('v2', 1.0, 3.5)]
MAX_VENTANA = int(os.environ.get('IA_MAX_VENTANA', '15'))
MAX_VENTANA_DIA = int(os.environ.get('IA_MAX_VENTANA_DIA', '60'))


def ventanas(sb, picks: List[Dict], ahora: dt.datetime, mercado: Dict) -> int:
    import requests
    sbv = (sb[0].replace('/ia_analisis', '/ia_ventanas'), sb[1])
    desde = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    try:
        r = requests.get(sbv[0], headers=sbv[1], params={'select': 'id,creado', 'fecha': 'gte.' + desde, 'limit': 10000}, timeout=30)
    except Exception:
        return 0
    if not r.ok:
        return 0                            # sin la migración v447 no se mide (no pasa nada más)
    filas_v = r.json()
    hechos = {x['id'] for x in filas_v}
    hoy = sum(1 for x in filas_v if str(x.get('creado') or '')[:10] == ahora.strftime('%Y-%m-%d'))
    evaluar(sbv, picks)
    n = 0
    for nombre, h0, h1 in VENTANAS:
        queda = min(MAX_VENTANA - n, MAX_VENTANA_DIA - hoy - n)
        if queda <= 0:
            break
        lista = [m for m in partidos(picks, ahora) if m['peso'] >= 0 and m.get('deporte', 'Fútbol') == 'Fútbol' and _utc(m['inicio'])
                 and h0 <= (_utc(m['inicio']) - ahora).total_seconds() / 3600 < h1
                 and m['id'] + '|' + nombre not in hechos][:queda]
        if not lista:
            continue
        k, sin_cupo = analizar(sbv, lista, mercado, nombre)
        n += k
        if sin_cupo:
            break
    return n


def guardar_uso(sb, ahora: dt.datetime):
    """v450 — suma lo de esta pasada a `ia_uso` (por día de Google, que reinicia el
    cupo a medianoche del Pacífico). Sin la migración v450, no hace nada."""
    import requests
    if not USO or not sb:
        return
    url = sb[0].replace('/ia_analisis', '/ia_uso')
    dia = (ahora - dt.timedelta(hours=8)).strftime('%Y-%m-%d')
    try:
        r = requests.get(url, headers=sb[1], params={'select': '*', 'fecha': 'eq.' + dia}, timeout=20)
        if not r.ok:
            return
        antes = {x['id']: x for x in r.json()}
        filas = []
        for (modelo, tipo), u in USO.items():
            k = '%s|%s|%s' % (dia, modelo, tipo)
            a = antes.get(k) or {}
            filas.append({'id': k, 'fecha': dia, 'modelo': modelo, 'tipo': tipo,
                          'llamadas': int(a.get('llamadas') or 0) + u['llamadas'], 'ok': int(a.get('ok') or 0) + u['ok'],
                          'cupo_agotado': bool(a.get('cupo_agotado')) or u['agotado'],
                          'agotado_a': a.get('agotado_a') or (ahora.isoformat() if u['agotado'] else None),
                          'actualizado': ahora.isoformat()})
        requests.post(url, headers=dict(sb[1], Prefer='resolution=merge-duplicates,return=minimal'), json=filas, timeout=20)
    except Exception as e:
        logger.warning('[ia] no se guardó la cuenta del cupo: %s', type(e).__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    seco = '--seco' in sys.argv
    sb = _sb()
    if not seco and (sb is None or not os.environ.get('GEMINI_API_KEY')):
        print('ia: sin GEMINI_API_KEY o sin la base: no se hace nada')
        return 0
    try:
        picks = json.load(open(DATOS, encoding='utf-8')).get('picks') or []
    except Exception as e:
        print('ia: sin datos del sitio (%s)' % e)
        return 0
    # v418 — también los partidos SIN pick (tarjetas de «sólo análisis»): la IA
    # analiza todos; detrás de los que tienen pick, que pesan más
    try:
        picks += json.load(open(os.path.join(os.path.dirname(DATOS), 'analisis.json'), encoding='utf-8')).get('analisis') or []
    except Exception:
        pass
    try:                                  # el texto real de lo premium (el público va tapado)
        reales = json.load(open(PRIVADO, encoding='utf-8'))
        for p in picks:
            if p.get('id') in reales:
                p['apuesta'] = reales[p['id']]
    except Exception:
        pass
    ahora = dt.datetime.now(dt.timezone.utc)
    evaluados = 0 if seco else evaluar(sb, picks)
    hechos = set() if seco else (ya_hechos(sb) or set())
    mercado = _mercado()
    todos = [m for m in partidos(picks, ahora) if m['id'] not in hechos]
    nuevos = sorted(todos, key=lambda m: nivel(m, mercado))[:MAX_POR_PASADA]   # v451 — el orden estable deja lo demás igual
    if seco:
        for m in nuevos[:2]:
            print(json.dumps(datos_del_partido(m, mercado), ensure_ascii=False, indent=1))
        print('ia (seco): %d partidos por analizar' % len(nuevos))
        return 0
    hechos_ahora, sin_cupo = analizar(sb, nuevos, mercado)
    # v447 — el mismo partido otra vez ~12 h, ~6 h y ~2 h antes, SÓLO para medir
    medidos = 0 if sin_cupo else ventanas(sb, picks, ahora, mercado)
    guardar_uso(sb, ahora)
    print('ia: %d analizados, %d evaluados, %d en ventanas · consultas: %s' % (hechos_ahora, evaluados, medidos,
          ', '.join('%s %s=%d%s' % (t, m.replace('gemini-', ''), u['llamadas'], ' (sin cupo)' if u['agotado'] else '') for (m, t), u in sorted(USO.items()))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
