#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v312 — EL DOCUMENTO DE LOS DÍAS, ESCRITO PARA QUE LO LEA UNA IA.

El usuario: «en los botones de enviar todo lo de hoy y mañana deberá haber
uno de pasado mañana y uno de enviar todo (hoy, mañana y pasado), y en eso
que se envía deberán ir todas las estadísticas de las apuestas que me arroja.
La idea es que ese formato lo pase a un LLM y fácilmente me ayude a hacer los
análisis de cuál sí meter y cuál no, como una segunda validación».

QUÉ LLEVA CADA PARTIDO, EN ESTE ORDEN
  1. cabecera: día, hora de CDMX, deporte, competición y los dos equipos;
  2. 🎯 METER (app): las apuestas que la tarjeta dice meter —la misma función
     de la tarjeta, `modo_modelo.recomendadas` + `metidas`—, con la
     probabilidad con la que se decidió, la cuota, la casa y lo que la casa
     cree sin su margen. O «🚫 nada que meter»;
  3. MODELO: 1X2, goles esperados, más/menos 1,5/2,5/3,5, ambos marcan,
     goles de cada equipo, y los conteos (córners, tarjetas, remates) con su
     media total y por equipo;
  4. CONTEXTO: bajas, árbitro y alineación si el precálculo los tiene;
  5. MERCADOS: todo lo cotizado, con probabilidad del modelo, cuota, casa y
     EV (lo mismo que el documento de siempre).

Y una GUÍA al principio que dice qué es cada número, para que la IA no
confunda la probabilidad del modelo con la de la casa.

Coste medido: 0,14 s por partido de fútbol (los bloques de conteo y el
veredicto), ~1,5 min para tres días enteros. Se usa el barrido YA calculado:
un segundo barrido dentro de Streamlit mata el contenedor (bitácora v86).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

GUIA = """GUÍA DE LECTURA (para la IA que analice este documento)
- Horas en hora de Ciudad de México (CDMX). Cuotas en formato decimal.
- «🎯 METER (app)»: apuestas que la aplicación recomienda meter. «prob» es la
  probabilidad CALIBRADA con la que decidió (modelo corregido por su historial
  y mezclado 50/50 con la casa). «casa sin margen» es lo que cree la casa.
  Si prob ≫ casa, el modelo discrepa del mercado: históricamente ahí falla más.
- Regla de la app para «meter» en fútbol: prob entre 70 % y 80 %, cuota
  menor de 1,35 y nunca «doble y goles», remates ni hándicap (medido: ahí
  salían los rojos). Con esa regla lo marcado «meter» se cumplió ~76-81 %
  (20-28 sep). A cuotas de Playdoit la casa conserva margen: la única ventaja
  de precio medida es cuando la casa paga por encima del justo (EV > 0).
- «MODELO»: probabilidades del modelo sin mezclar. λ = media esperada.
  Córners y tarjetas: total del partido y de cada equipo. En CÓRNERS el
  total es a propósito la MEDIA DE LA COMPETICIÓN (por eso se repite, p. ej.
  9,1 en toda la Liga de Naciones): medido, sumar lo de los dos equipos no
  predice mejor el total. Lo que cambia por partido es lo de cada equipo,
  que ya usa la TABLA (diferencia de goles, posición): el fuerte saca más
  córners. Medido en partidos no vistos: lo ofrecido al 70-80 % acierta
  77,2 % contra 74,3 % sin la tabla.
- «[estimado]»: la competición no publica esa estadística; es su nivel
  general, no algo de estos dos equipos. No lo uses para decidir.
- Sólo van partidos con MODELO (el motor de ligas o el de cada deporte). Los
  de competiciones fuera del motor (sub-21, copas, ligas chicas) ya no se
  envían: sin el modelo completo son ruido (decisión del usuario, v317).
- «🏆 LO MEJOR DEL MODELO»: la Capa 1 de la app, la parte de las «meter»
  que más acierta según la simulación con partidos terminados.
- «🔷 MÁS RIESGO, MÁS CUOTA»: OTRA PROBABILIDAD, más baja que la de la
  Capa 1 (71-72 % medido, cuota ~1,43). Para multiplicar en dobles; no se
  cuenta como «meter».
- «🎯 APUESTAS A METER POR CATEGORÍA»: todas las «meter» del día agrupadas
  por mercado; debajo, el detalle de cada partido.
- «MERCADOS»: todo lo cotizado. «justa» = 1/probabilidad del modelo.
  EV = prob × cuota − 1 (positivo = la casa paga de más según el modelo).
- «TABLA» (v316): posición, puntos a la zona de arriba (el 25 % de la
  tabla) y al descenso (el 15 % de abajo), goles a favor y en contra por
  partido (el local en casa, el visitante fuera) y % de sus partidos con 4+
  goles; «⚠️ decisivo para los dos» si ambos están a ≤ 3 puntos de una zona
  pasada la mitad de la temporada. Medido en 80.829 partidos: la zona y el
  4+ ya van DENTRO del modelo en «más de 3,5» (lo mejoran); en decisivos los
  «menos de 3,5» NO fallan más (75,7 % contra 73,8 %), los «menos de 2,5»
  algo sí (55 % contra 58 %).
- «Forma»: puntos por partido y goles A FAVOR / EN CONTRA por partido de los
  últimos cinco (no son goles del partido: no se suman).
- «🚑 Bajas», «Árbitro», «Alineación»: contexto; puede faltar.
- Remates por jugador: SOLO información (medido: apostarlos pierde).
"""


def _pct(x) -> str:
    try:
        return '%.0f%%' % (100 * float(x))
    except (TypeError, ValueError):
        return '—'


def _num(x, dec=2) -> str:
    try:
        return ('%.' + str(dec) + 'f') % float(x)
    except (TypeError, ValueError):
        return '—'


def _bloques(pick: Dict) -> Dict:
    import modo_modelo as mm
    try:
        _rm = mm.remates_tarjeta(pick) or {}
        return {'Córners': mm.corners_tarjeta(pick),
                'Tarjetas': mm.tarjetas_tarjeta(pick),
                'Remates': _rm.get('totales'),
                'Remates a puerta': _rm.get('a_puerta')}
    except Exception as e:
        logger.debug('[ia] bloques de %s: %s', pick.get('partido'), e)
        return {}


def _conteo_crudo(pick: Dict, que: str) -> Optional[Dict]:
    """λ total y por equipo de un conteo, directo de `rendimiento_equipos`."""
    try:
        import modo_modelo as mm
        import rendimiento_equipos as rq
        h, a = mm._equipos(pick)
        clave = str(pick.get('clave_liga') or '')
        torneo = str(pick.get('liga_origen') or pick.get('liga') or '')
        if not (h and a and clave):
            return None
        if que == 'corners':
            return rq.corners_equipo(clave, h, a)
        if que == 'tarjetas':
            return rq.tarjetas_equipo(clave, h, a, torneo=torneo)
        rm = rq.remates_equipo(clave, h, a, torneo=torneo) or {}
        return rm.get('totales' if que == 'remates' else 'a_puerta')
    except Exception:
        return None


def _meter(pick: Dict) -> List[Dict]:
    import modo_modelo as mm
    try:
        b = _bloques(pick) if str(pick.get('deporte') or 'Fútbol') == 'Fútbol' \
            else None
        return mm.metidas(mm.recomendadas(pick, b, n=mm.MAX_RECOMENDADAS))
    except Exception as e:
        logger.debug('[ia] meter de %s: %s', pick.get('partido'), e)
        return []


def bloque_partido(reg: Dict, pick: Optional[Dict]) -> List[str]:
    """Las líneas de un partido."""
    import bot_telegram as bt
    cab = '%s  %s — %s  [%s]' % (reg.get('hora') or '--:--', reg['deporte'],
                                 reg['partido'], reg.get('liga') or '')
    L = ['', '-' * 70, cab]
    if pick:
        mets = _meter(pick)
        if mets:
            L.append('🎯 METER (app):')
            for m in mets:
                p = m.get('prob_meter', m.get('prob'))
                trozos = ['prob %s' % _pct(p)]
                if m.get('cuota'):
                    trozos.append('cuota %s' % _num(m['cuota']))
                if m.get('p_mercado') is not None:
                    trozos.append('casa sin margen %s' % _pct(m['p_mercado']))
                L.append('   • %s · %s' % (m.get('apuesta'), ' · '.join(trozos)))
                if m.get('razon'):
                    L.append('     por qué: %s' % m['razon'])
        else:
            L.append('🚫 Nada que meter según la app')
        if pick.get('solo_mercado'):
            # v313 — sin modelo: el 1X2 de Pinnacle, dicho como lo que es
            b = pick.get('board') or {}
            L.append('FUERA DEL MOTOR DE LIGAS — 1X2 de %s sin margen: '
                     % ('Pinnacle' if pick.get('pinnacle') else 'Playdoit')
                     + ' · '.join('%s %s' % (k, _pct(v)) for k, v in b.items()))
            # v315 — el modelo propio de la competición (ver
            # `modelo_competiciones`): segunda opinión
            mp = pick.get('modelo_propio') or {}
            if mp.get('p'):
                q_ = mp['p']
                L.append('MODELO PROPIO (λ %s y %s; %s y %s partidos en la base): '
                         'local %s · empate %s · visita %s · más de 1.5 %s · '
                         'más de 2.5 %s · ambos marcan %s'
                         % (_num((mp.get('lambdas') or [0, 0])[0]),
                            _num((mp.get('lambdas') or [0, 0])[1]),
                            (mp.get('n') or ['?', '?'])[0], (mp.get('n') or ['?', '?'])[1],
                            _pct(q_.get('home')), _pct(q_.get('draw')),
                            _pct(q_.get('away')), _pct(q_.get('mas_1.5')),
                            _pct(q_.get('mas_2.5')), _pct(q_.get('btts_si'))))
            # v316 — y su tabla (base de Flashscore)
            try:
                import tabla_liga as _tl
                _tt = _tl.texto(pick)
                if _tt:
                    L.append(_tt)
            except Exception:
                pass
            # v314 — goles por equipo, sin cuota (de las λ del mercado)
            try:
                import mercado_sin_modelo as _msm
                lam = pick.get('lambdas_mercado')
                ge = _msm.goles_equipo(lam)
                if ge:
                    h_, a_ = (reg['partido'].split(' vs ', 1) + [''])[:2]
                    L.append('GOLES POR EQUIPO (sin cuota; λ %s y %s): %s más '
                             'de 0.5 %s · más de 1.5 %s · %s más de 0.5 %s · '
                             'más de 1.5 %s'
                             % (_num(lam[0]), _num(lam[1]), h_,
                                _pct(ge['local_0.5']), _pct(ge['local_1.5']),
                                a_, _pct(ge['visita_0.5']),
                                _pct(ge['visita_1.5'])))
            except Exception:
                pass
            if reg.get('mercados'):
                L.append('MERCADOS:')
                import bot_telegram as _bt
                L += [_bt._linea_mercado(m) for m in reg['mercados']]
            for nota in (reg.get('notas') or []):
                L.append('   ! %s' % nota)
            return L
        # el modelo
        b = pick.get('board') or {}
        tri = [(k, v) for k, v in b.items()
               if k.startswith('Gana ') or k == 'Empate']
        if tri:
            L.append('MODELO 1X2: ' + ' · '.join('%s %s' % (k, _pct(v))
                                                  for k, v in tri))
        gl = pick.get('goles_lineas') or {}
        if pick.get('goles_lambda') or gl:
            partes = []
            if pick.get('goles_lambda'):
                partes.append('λ goles %s' % _num(pick['goles_lambda']))
            for k in ('1.5', '2.5', '3.5'):
                if gl.get(k) is not None:
                    partes.append('Más de %s %s' % (k, _pct(gl[k])))
            if b.get('Ambos marcan: Sí') is not None:
                partes.append('Ambos marcan %s' % _pct(b['Ambos marcan: Sí']))
            L.append('MODELO goles: ' + ' · '.join(partes))
        ge = pick.get('goles_equipo') or {}
        for lado, nombre in (('local', 'local'), ('visitante', 'visitante')):
            x = ge.get(lado) or {}
            if x:
                L.append('MODELO goles %s: %s' % (nombre, ' · '.join(
                    'Más de %s %s' % (k, _pct(v)) for k, v in
                    sorted(x.items(), key=lambda kv: float(kv[0]))[:3])))
        if str(pick.get('deporte') or 'Fútbol') == 'Fútbol':
            for que, nombre in (('corners', 'Córners'), ('tarjetas', 'Tarjetas'),
                                ('remates', 'Remates'),
                                ('a_puerta', 'Remates a puerta')):
                c = _conteo_crudo(pick, que)
                if c and c.get('lambda_total'):
                    # v313 — en córners el total ES la media de la
                    # competición (medido: sumar los equipos no predice
                    # mejor). Se dice, o parece un valor por defecto.
                    media = (que == 'corners' and c.get('origen') == 'observado')
                    L.append('MODELO %s: λ total %s%s (local %s · visita %s)%s'
                             % (nombre, _num(c['lambda_total'], 1),
                                ' = media de la competición' if media else '',
                                _num(c.get('lambda_home'), 1),
                                _num(c.get('lambda_away'), 1),
                                '' if c.get('origen') == 'observado'
                                else ' [estimado]'))
        # v316 — la tabla de la temporada (goles a favor/en contra, 4+ goles,
        # puntos a las zonas)
        try:
            import tabla_liga as tl
            tt = tl.texto(pick)
            if tt:
                L.append(tt)
        except Exception:
            pass
        # contexto
        try:
            import bajas_fotmob as bf
            tb = bf.texto(pick)
            if tb:
                L.append(tb)
        except Exception:
            pass
        try:
            import arbitro_partido as ap
            import modo_modelo as mm
            h, a = mm._equipos(pick)
            perf = ap.buscar(str(pick.get('fecha') or '')[:10], h, a) if h else None
            if perf:
                nom = perf.get('arbitro') or perf.get('nombre') or ''
                if nom:
                    L.append('Árbitro: %s' % nom)
        except Exception:
            pass
        if pick.get('motivo_modelo'):
            L.append('Nota del modelo: %s' % str(pick['motivo_modelo'])[:200])
    # los mercados cotizados, como en el documento de siempre
    if reg.get('mercados'):
        L.append('MERCADOS:')
        L += [bt._linea_mercado(m) for m in reg['mercados']]
    for nota in (reg.get('notas') or []):
        L.append('   ! %s' % nota)
    return L


def _pick_de(r: Dict, reg: Dict) -> Optional[Dict]:
    # v313 — también los partidos sin modelo propio (`solo_mercado`)
    # v317 — apagados salvo que `mercado_sin_modelo.MOSTRAR` diga otra cosa
    try:
        import mercado_sin_modelo as _msm_v
        _sm_ok = bool(_msm_v.MOSTRAR)
    except Exception:
        _sm_ok = False
    lista = (r.get('pronosticos') or []) + ((r.get('solo_mercado') or []) if _sm_ok else [])
    for p in lista:
        if (isinstance(p, dict) and str(p.get('partido')) == reg['partido']
                and str(p.get('deporte') or 'Fútbol') == reg['deporte']):
            return p
    if reg['deporte'] == 'Fútbol':
        try:
            import mercado_sin_modelo as msm
            for p in lista:
                if (isinstance(p, dict)
                        and str(p.get('deporte') or 'Fútbol') == 'Fútbol'
                        and msm.mismo_partido(str(p.get('partido')),
                                              reg['partido'])):
                    return p
        except Exception:
            pass
    return None


# v317 — EL DOCUMENTO, CATALOGADO.
#
# El usuario: «que me esté mandando diferentes métricas de recomendaciones,
# no sólo de un solo mercado, sino de varias, y que esté bien catalogado en
# lo que estamos mandando a Telegram. Todo tiene que estar bien estructurado
# porque se lo vamos a dar a una IA generativa». Y: «quiero que únicamente
# esté lo que nosotros hemos analizado y puesto con el modelo».
#
# Cada día lleva ahora, en este orden:
#   1. 🏆 LO MEJOR DEL MODELO: lo que sale en la Capa 1 (`lo_mejor.py`);
#   2. 🎯 APUESTAS A METER POR CATEGORÍA: todas las «meter» del día agrupadas
#      por mercado (resultado, goles del partido, goles de cada equipo, ambos
#      marcan, córners, tarjetas; y en los otros deportes, por deporte), una
#      línea por apuesta con hora, partido, probabilidad, cuota y casa;
#   3. DETALLE POR PARTIDO: sólo los partidos con modelo (antes entraban
#      también los que sólo tenían precio de las casas: Capa 2, candidatos,
#      «sin modelo»).
CATEGORIAS = (('RESULTADO', ('1X2', 'Doble oportunidad', 'Ganador', 'Handicap')),
              ('GOLES DEL PARTIDO', ('Goles',)),
              ('GOLES DE CADA EQUIPO', ('Goles equipo',)),
              ('AMBOS MARCAN', ('BTTS',)),
              ('CÓRNERS', ('Córners',)),
              ('TARJETAS', ('Tarjetas',)))


def categoria(m: Dict, deporte: str) -> str:
    if deporte != 'Fútbol':
        return deporte.upper()
    mer = str(m.get('mercado') or '')
    for nombre, mercados in CATEGORIAS:
        if mer in mercados:
            return nombre
    return 'OTROS (%s)' % mer if mer else 'OTROS'


def _con_modelo(pick: Optional[Dict]) -> bool:
    if not pick or pick.get('sin_modelo'):
        return False
    if pick.get('solo_mercado'):
        # los de fuera del motor, sólo si están encendidos
        try:
            import mercado_sin_modelo as _msm
            return bool(_msm.MOSTRAR)
        except Exception:
            return False
    return True


def _linea_meter(reg: Dict, m: Dict) -> str:
    p = m.get('prob_meter', m.get('prob'))
    trozos = ['prob %s' % _pct(p)]
    if m.get('cuota'):
        trozos.append('cuota %s' % _num(m['cuota']))
    if m.get('casa'):
        trozos.append(str(m['casa']))
    return '   • %s  %s — %s · %s' % (reg.get('hora') or '--:--', reg['partido'],
                                     m.get('apuesta'), ' · '.join(trozos))


def texto(r: Dict, dias: List[str]) -> str:
    """El documento de uno o varios días, listo para pegar en una IA."""
    import datetime as _dt
    import mercados_dia as md
    L = ['PREDICTOR DEPORTIVO — DATOS PARA ANÁLISIS',
         'Días: %s · generado %s UTC' % (', '.join(dias),
                                         _dt.datetime.utcnow().strftime(
                                             '%Y-%m-%d %H:%M')),
         '', GUIA]
    total_meter = 0
    for dia in dias:
        filas = []
        for reg in md.partidos_del_dia(r, dia, con_extras=True):
            pick = _pick_de(r, reg)
            if _con_modelo(pick):
                filas.append((reg, pick, _meter(pick)))
        L += ['', '=' * 70, 'DÍA %s — %d partidos con modelo' % (dia, len(filas)),
              '=' * 70]
        if not filas:
            L.append('Sin partidos con pronóstico para este día.')
            continue
        # 1. lo mejor del modelo (la Capa 1)
        try:
            import lo_mejor as _lm
            top = _lm.del_dia(r, dia)
        except Exception as e:
            logger.debug('[ia] lo mejor: %s', e)
            top = []
        L += ['', '🏆 LO MEJOR DEL MODELO (Capa 1) — %d' % len(top)]
        if top:
            L += ['   • %s  %s — %s · prob %s · cuota %s · %s'
                  % (t.get('hora') or '--:--', t.get('partido'), t.get('apuesta'),
                     _pct(t.get('prob')), _num(t.get('cuota')), t.get('casa') or '')
                  for t in top]
            try:
                L.append('   (%s)' % _lm.NOTA)
            except Exception:
                pass
        else:
            L.append('   Ninguna apuesta del día llega al nivel de la Capa 1.')
        # 1b. 🔷 más riesgo, más cuota: otra probabilidad, dicha aparte
        try:
            import lo_mejor as _lm
            rz = _lm.del_dia(r, dia, riesgo=True)
        except Exception as e:
            logger.debug('[ia] riesgo: %s', e)
            rz = []
        L += ['', '🔷 MÁS RIESGO, MÁS CUOTA (Capa 1, otra probabilidad) — %d' % len(rz)]
        if rz:
            L += ['   • %s  %s — %s · modelo %s · casa sin margen %s · cuota %s · %s'
                  % (t.get('hora') or '--:--', t.get('partido'), t.get('apuesta'),
                     _pct(t.get('prob')), _pct(t.get('p_mercado')),
                     _num(t.get('cuota')), t.get('casa') or '') for t in rz]
            L.append('   (%s)' % _lm.NOTA_RIESGO)
            # la doble sugerida: las dos de riesgo de partidos distintos, o
            # una de riesgo con la mejor del primer nivel
            pares = []
            if len(rz) >= 2:
                pares.append((rz[0], rz[1], 0.715 * 0.715))
            otra = next((t for t in top if t.get('partido') != rz[0].get('partido')), None)
            if otra:
                pares.append((rz[0], otra, 0.715 * 0.85))
            for x, y, pr in pares:
                L.append('   DOBLE SUGERIDA: %s (%s) + %s (%s) → cuota %s · se cumple '
                         '~%s según lo medido'
                         % (x.get('apuesta'), x.get('partido'), y.get('apuesta'),
                            y.get('partido'), _num((x.get('cuota') or 1) * (y.get('cuota') or 1)),
                            _pct(pr)))
        else:
            L.append('   Ninguna hoy.')
        # 2. todas las «meter», por categoría
        grupos: Dict[str, List[str]] = {}
        for reg, pick, mets in filas:
            for m in mets:
                grupos.setdefault(categoria(m, reg['deporte']), []).append(
                    _linea_meter(reg, m))
        n = sum(len(v) for v in grupos.values())
        total_meter += n
        L += ['', '🎯 APUESTAS A METER POR CATEGORÍA — %d' % n]
        orden = [c for c, _ in CATEGORIAS]
        for cat in sorted(grupos, key=lambda c: (orden.index(c) if c in orden
                                                 else len(orden), c)):
            L.append('%s (%d)' % (cat, len(grupos[cat])))
            L += grupos[cat]
        if not grupos:
            L.append('   Ninguna.')
        # 3. el detalle de cada partido
        L += ['', 'DETALLE POR PARTIDO']
        for reg, pick, _m in filas:
            L += bloque_partido(reg, pick)
    L += ['', '=' * 70, 'Total de apuestas «meter» de la app: %d' % total_meter]
    return '\n'.join(L)


def resumen(r: Dict, dias: List[str], etiqueta: str) -> str:
    """El pie corto del adjunto de Telegram."""
    import mercados_dia as md
    n = sum(len(md.partidos_del_dia(r, d, con_extras=False)) for d in dias)
    return ('📋 *%s* (%s)\n%d partidos con todos sus datos y las apuestas '
            '«🎯 meter» de la app.\n_Formato pensado para pegarlo en tu agente '
            'de IA: lleva al principio la guía de lectura._'
            % (etiqueta, ', '.join(dias), n))[:1000]
