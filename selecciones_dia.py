# -*- coding: utf-8 -*-
"""
v302 — LAS SELECCIONES ENTRAN EN APUESTAS DEL DÍA.

LO QUE PIDIÓ EL USUARIO
    «Veo que ya pronto se juega la UEFA Nations League y varios partidos de
     equipos internacionales, pero no lo veo reflejado en las apuestas del día
     de acuerdo al filtro que corresponda.»

POR QUÉ NO ESTABAN
El barrido del día (`alpha_finder.apuestas_del_dia_universal`) tenía seis
ramas —fútbol de clubes, MLB, tenis, NBA, KBO y NFL— y NINGUNA de
selecciones. El motor de selecciones existe desde el principio del proyecto
(`prediction_api.PredictionEngine`, 200 selecciones, walk-forward de cinco
semestres con 59,7 % de acierto y log-loss 0,868) pero sólo lo usaba la vista
«Partidos Internacionales», a la que hay que ir a mano y elegir el cruce.

Medido el 2026-09-22 sobre el precálculo publicado: 407 pronósticos, cero de
selecciones, y en el calendario de ESPN a cuatro días había 140 partidos de
selecciones, entre ellos Netherlands-Germany y Norway-Denmark de la Nations
League, y Japan-Uruguay y South Korea-Ecuador.

LO QUE SE HACE AQUÍ
Una rama más del barrido. Toma el calendario de `fixtures_espn`
(ESPN + el tablón de cuotas, que es lo que sobrevive al 403 de ESPN en la
nube), enlaza cada nombre con el catálogo del motor igual que la vista de
selecciones, predice, y devuelve pronósticos CON LA MISMA FORMA que los del
fútbol de clubes. Así la tarjeta, el filtro de día y la Escalera los tratan
igual sin tocar nada más.

DOS REGLAS QUE NO SE NEGOCIAN
1. SÓLO ABSOLUTAS MASCULINAS. El motor se entrenó con ellas. Un sub-20 o un
   femenino comparten bandera y no comparten plantilla (v119): se dejan fuera
   y se cuentan como no enlazados, para que se vea que existen.
2. LA LOCALÍA SE RESPETA. El motor nació para el Mundial y, sin decirle nada,
   trata el partido como sede neutral (promedia las dos ópticas). En la
   Nations League y en los amistosos el local juega en casa, que es
   exactamente con lo que el modelo aprendió la ventaja de campo: se le pide la
   óptica directa (`en_casa=True`) salvo que la fuente marque sede neutral.

   Medido sobre los 700 últimos partidos NO neutrales de `historico_partidos`
   (2024-2026): log-loss 0,7744 tratándolos como neutrales contra 0,7529 con
   la localía, mejora +0,0215 con p5 +0,0100. El acierto del favorito casi no
   cambia (66,1 % contra 65,4 %): lo que mejora es la probabilidad, que es lo
   que la pantalla enseña. Ojo: el estado de los equipos es del 2026-07-15, así
   que la medición no es fuera de muestra estricta; lo es la COMPARACIÓN,
   porque las dos variantes comparten ese mismo estado.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DIAS = 3
CLAVE_LIGA = 'selecciones'

_MOTOR: List = []


def _motor():
    """El motor de selecciones, cargado una vez por proceso. None si falla."""
    if _MOTOR:
        return _MOTOR[0]
    try:
        from prediction_api import PredictionEngine
        m = PredictionEngine()
        if not m.listo:
            logger.warning('[selecciones] motor no listo: %s', m.error)
            return None
        _MOTOR.append(m)
        return m
    except Exception as e:
        logger.warning('[selecciones] motor no disponible: %s: %s',
                       type(e).__name__, e)
        return None


def catalogo(motor) -> Dict[str, str]:
    """{nombre visible (inglés, alias, español): código del motor}.

    El MISMO catálogo que la vista de selecciones (v66): los alias dan
    coincidencia exacta y evitan que el emparejado difuso confunda Congo con
    RD Congo o Irlanda con Irlanda del Norte.
    """
    from config import TEAM_NAMES_EN, TEAM_ALIAS
    from prediction_api import NOMBRES_PAIS
    cat: Dict[str, str] = {}
    for c in motor.equipos:
        cat[TEAM_NAMES_EN.get(c, c)] = c
        for al in TEAM_ALIAS.get(c, []):
            cat.setdefault(al, c)
        cat.setdefault(NOMBRES_PAIS.get(c, c), c)
    return cat


def _es_absoluta(f: Dict) -> bool:
    """¿Absoluta masculina? Por el torneo y por la marca de categoría."""
    torneo = str(f.get('torneo') or '')
    t = torneo.lower()
    if any(x in t for x in ('femen', 'women', '(w)', ' w ', 'fem.')):
        return False
    try:
        import cuotas_multi as cm
        if cm.categoria_partido(f.get('home') or '', f.get('away') or '',
                                torneo):
            return False
    except Exception:
        pass
    return True


def _inicio_utc(valor) -> str:
    """'YYYY-MM-DD HH:MM:SS' en UTC, que es como el resto guarda `inicio`."""
    try:
        import horario as _h
        d = _h._a_utc(valor)
        return d.strftime('%Y-%m-%d %H:%M:%S') if d else ''
    except Exception:
        return ''


def _mercados_de_matriz(matriz) -> Dict:
    """Goles y ambos marcan desde la matriz de marcadores del motor."""
    try:
        n = len(matriz)
        tot = sum(sum(f) for f in matriz) or 1.0
        p = [[float(matriz[i][j]) / tot for j in range(n)] for i in range(n)]
        lineas = {}
        for ln in (0.5, 1.5, 2.5, 3.5, 4.5):
            lineas[str(ln)] = round(sum(p[i][j] for i in range(n)
                                        for j in range(n) if i + j > ln), 4)
        btts = sum(p[i][j] for i in range(1, n) for j in range(1, n))
        loc = {str(ln): round(sum(p[i][j] for i in range(n) for j in range(n)
                                  if i > ln), 4) for ln in (0.5, 1.5, 2.5)}
        vis = {str(ln): round(sum(p[i][j] for i in range(n) for j in range(n)
                                  if j > ln), 4) for ln in (0.5, 1.5, 2.5)}
        return {'goles_lineas': lineas, 'btts': round(btts, 4),
                'goles_equipo': {'local': loc, 'visitante': vis}}
    except Exception as e:
        logger.debug('[selecciones] matriz: %s', e)
        return {}


def _precio(home: str, away: str, lado: str) -> Dict:
    """La cuota accionable de ese lado, si alguna casa lo cotiza."""
    try:
        import cuotas_multi as cm
        res = cm.cuotas_partido('futbol', home, away)
        pr = cm.precio_accionable(res, lado) or {}
        if pr.get('cuota') and pr.get('casa') != 'Pinnacle':
            return {'cuota': float(pr['cuota']), 'casa': pr.get('casa'),
                    'pinnacle': (res.get('pinnacle') or {})}
        return {'pinnacle': (res.get('pinnacle') or {})}
    except Exception as e:
        logger.debug('[selecciones] precio %s vs %s: %s', home, away, e)
        return {}


def pronostico(motor, f: Dict, h: str, a: str) -> Optional[Dict]:
    """Un pronóstico con la forma de los del fútbol de clubes."""
    r = motor.predecir(h, a, en_casa=not bool(f.get('neutral')))
    if not isinstance(r, dict) or r.get('error'):
        return None
    pr = (r.get('prediction') or {})
    pb = pr.get('probabilities') or {}
    ph, pd_, pa = (float(pb.get('home') or 0), float(pb.get('draw') or 0),
                   float(pb.get('away') or 0))
    if ph + pd_ + pa <= 0:
        return None
    # v304.1 — el nombre CANÓNICO en inglés, que es el de ESPN y el de
    # `historico_selecciones`. Un partido que entraba por el tablón en
    # español («Azerbaiyán vs Tajikistán») no encontraba su histórico y la
    # tarjeta se quedaba sin forma, sin córners y sin el porqué.
    try:
        from config import TEAM_NAMES_EN as _EN
    except Exception:
        _EN = {}
    home = str(_EN.get(h) or f.get('home'))
    away = str(_EN.get(a) or f.get('away'))
    mk = _mercados_de_matriz(r.get('score_matrix') or [])
    board = {'Gana %s' % home: round(ph, 3), 'Empate': round(pd_, 3),
             'Gana %s' % away: round(pa, 3)}
    gl = mk.get('goles_lineas') or {}
    if '2.5' in gl:
        board['Más de 2.5'] = round(gl['2.5'], 3)
        board['Menos de 2.5'] = round(1 - gl['2.5'], 3)
    if 'btts' in mk:
        board['Ambos marcan: Sí'] = round(mk['btts'], 3)
        board['Ambos marcan: No'] = round(1 - mk['btts'], 3)
    lado, prob = max((('home', ph), ('draw', pd_), ('away', pa)),
                     key=lambda x: x[1])
    apuesta = ('Empate' if lado == 'draw' else
               'Gana %s' % (home if lado == 'home' else away))
    precio = _precio(home, away, lado)
    cuota = precio.get('cuota')
    mercados = [{'mercado': '1X2' if k.startswith(('Gana', 'Empate')) else
                 ('Goles' if k.startswith(('Más', 'Menos')) else 'BTTS'),
                 'apuesta': k, 'prob': v, 'cuota': None, 'ev': None,
                 'cuota_justa': round(1 / v, 2) if v > 0 else None,
                 'valor': '🎯'} for k, v in board.items()]
    inicio = _inicio_utc(f.get('inicio')) or ('%s 00:00:00' % f.get('fecha'))
    p = {
        'deporte': 'Fútbol',
        'liga': str(f.get('torneo') or 'Selecciones'),
        'clave_liga': CLAVE_LIGA,
        'partido': '%s vs %s' % (home, away),
        'fecha': inicio[:10],
        'inicio': inicio,
        'mercado': '1X2',
        'apuesta': apuesta,
        'prob': round(prob, 3),
        'cuota': cuota,
        'casa': precio.get('casa'),
        'ev': round(cuota * prob - 1, 4) if cuota else None,
        'cuota_justa': round(1 / prob, 2),
        'valor': '🎯',
        'mercados': mercados,
        'board': board,
        'goles_lineas': gl,
        'goles_lambda': float(pr.get('total_goals_expected') or 0) or None,
        'goles_equipo': mk.get('goles_equipo'),
        'sin_cuota': cuota is None,
        'seleccion_nacional': True,
        'localia': (r.get('localia') or {}).get('metodo'),
        'motivo_modelo': str(r.get('decisive_factor') or '')[:240],
    }
    # v303 — LOS PRECIOS DE TODOS LOS MERCADOS, NO SÓLO DEL 1X2.
    #
    # El usuario, con Japan-Uruguay delante: «me agrada que me des ganador,
    # pero no me estás dando más métricas... habrá juegos donde es mejor la
    # doble oportunidad y meter over u under por lo parejos que serán». La
    # tarjeta sólo propone apuestas que la casa COTIZA (v174: sin precio no
    # hay apuesta), y aquí sólo se adjuntaba el 1X2 de Pinnacle. Se usa la
    # misma función que el fútbol de clubes, con los nombres CRUDOS del
    # calendario, que son los que indexan el tablero de la casa.
    pin = precio.get('pinnacle') or {}
    try:
        import alpha_finder as _af
        o_espn = {'pin_home': pin.get('home'), 'pin_draw': pin.get('draw'),
                  'pin_away': pin.get('away')}
        imp = {}
        # Playdoit publica las selecciones EN ESPAÑOL («Japón|Uruguay») y
        # ESPN en inglés: se prueban los dos. Visto el 2026-09-23: con el
        # nombre inglés Japan-Uruguay no encontraba su tablero y la tarjeta
        # sólo podía proponer el ganador.
        # v308 — `NOMBRES_PAIS` va por CÓDIGO FIFA («WAL»: «Gales») y aquí se
        # le pasaba el nombre inglés («Wales»): nunca encontraba el español y
        # la selección se quedaba sin sus mercados. Se traduce inglés →
        # código → español con la misma función que las líneas de jugador.
        try:
            import lineas_jugador as _lj
            _pares = _lj.nombres_de_casa('selecciones', home, away)
        except Exception:
            _pares = [(home, away)]
        for _hh, _aa in _pares:
            if not (_hh and _aa):
                continue
            imp = _af.implicitas_de_la_casa(
                {'home': _hh, 'away': _aa}, o_espn) or {}
            if len(imp) > 2:          # más que el 1X2 de respaldo
                break
        if imp:
            p['implicitas'] = imp
    except Exception as e:
        logger.debug('[selecciones] precios de la casa %s: %s', home, e)
    if not p.get('implicitas') and all(pin.get(k) for k in
                                       ('home', 'draw', 'away')):
        p['implicitas'] = {'1x2_cuotas': {k: pin[k] for k in
                                          ('home', 'draw', 'away')}}
    try:
        import horario as _h
        _h.anotar(p)
    except Exception:
        pass
    return p


def barrer(dias: int = DIAS) -> Dict:
    """La rama de selecciones del barrido del día. NUNCA lanza.

    Devuelve lo mismo que las demás ramas: `pronosticos`, `no_enlazados`,
    `evaluados` y `cobertura`, para que `apuestas_del_dia_universal` la sume
    sin casos especiales.
    """
    t0 = time.time()
    salida = {'pronosticos': [], 'no_enlazados': [], 'evaluados': 0,
              'cobertura': {}, 'capa1': [], 'capa2': [], 'incidencias': []}
    motor = _motor()
    if motor is None:
        salida['incidencias'].append(
            '⚠️ El motor de selecciones no cargó: los partidos de selecciones '
            'de hoy no tienen pronóstico.')
        return salida
    try:
        import fixtures_espn as fe
        import name_mapper as nm
        fx = fe.fixtures_selecciones(dias=max(int(dias), 1)) or []
    except Exception as e:
        salida['incidencias'].append(
            '⚠️ No se pudo leer el calendario de selecciones (%s).'
            % type(e).__name__)
        return salida
    cat = catalogo(motor)
    claves = list(cat.keys())
    vistos = set()
    for f in fx:
        try:
            if not _es_absoluta(f):
                continue
            ch = nm.mapear(str(f.get('home') or ''), claves,
                           contexto='selecciones')
            ca = nm.mapear(str(f.get('away') or ''), claves,
                           contexto='selecciones')
            if not (ch and ca) or cat[ch] == cat[ca]:
                salida['no_enlazados'].append('%s vs %s' % (f.get('home'),
                                                            f.get('away')))
                continue
            h, a = cat[ch], cat[ca]
            k = (h, a, str(f.get('fecha') or '')[:10])
            if k in vistos:
                continue          # ESPN y el tablón traen el mismo partido
            vistos.add(k)
            p = pronostico(motor, f, h, a)
            if p:
                salida['pronosticos'].append(p)
        except Exception as e:
            logger.debug('[selecciones] %s: %s', f.get('home'), e)
    salida['evaluados'] = len(salida['pronosticos'])
    if salida['pronosticos']:
        salida['cobertura'] = {CLAVE_LIGA: len(salida['pronosticos'])}
    logger.info('[selecciones] %d pronósticos, %d sin enlazar, %.1f s',
                len(salida['pronosticos']), len(salida['no_enlazados']),
                time.time() - t0)
    return salida
