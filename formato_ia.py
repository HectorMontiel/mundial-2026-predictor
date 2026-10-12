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
LO PRIMERO: «✅ QUÉ METER» es la DECISIÓN de la app, ya tomada y medida.
- Sólo se mete lo que está en esa lista. Todo lo demás del documento es
  CONTEXTO para entenderla, no otras apuestas: no las propongas como «meter».
- ⭐ ELIGE: las «se mete» que más se cumplen. Medido en lo archivado al pitido
  (5-11 oct): 241 ✅ 29 ❌ (89 %) contra 76 % del resto. Si hay que elegir
  pocas, las ⭐ primero.
- «acierta de verdad»: lo que acertaron de verdad las apuestas como ésa (no lo
  que promete el modelo). 🏆 = Capa 1 (~85 %).
- 🔒 FIJADA HH:MM: la apuesta oficial, fijada al abrirse la hora de apostar
  (4 h antes del partido); ya no cambia. ⏳ PROVISIONAL: aún puede cambiar o
  desaparecer; se fija a la hora indicada (medido: la fijada acierta 82 %
  contra 79 % de la del pitido). Lo mejor es apostar desde esa hora.
- Horas en CDMX. Cuotas decimales. «casa sin margen» = lo que cree la casa.
- «🏆 LO MEJOR DEL MODELO» es la Capa 1; «🔷 MÁS RIESGO, MÁS CUOTA» es otra
  probabilidad (71-72 %, cuota ~1,43), para dobles: no cuenta como «meter».
- «📊 ASÍ LE FUE A LA APP»: lo que dijo «meter» los últimos días, liquidado.
- «↗ subir a …»: el siguiente escalón de una «meter», con sus números. NO es
  una recomendación de la app.
- Sólo van partidos con MODELO (el motor de ligas o el de cada deporte).
- El λ total de córners es la suma de lo esperado de los dos equipos.
- «MODELO», «TABLA», «Forma», «Bajas», «MERCADOS»: datos de cada partido.
  EV = prob × cuota − 1. Córners/tarjetas/remates sólo con datos reales; si
  dice «🚫 SIN HISTÓRICO REAL», no se apuesta ese mercado. Remates por jugador:
  sólo información.
"""


# v369 — «quiero poder decirle de qué deporte quiero mandar: sólo fútbol, o
# sólo básquetbol, o combinados». Cada opción junta los nombres con los que el
# barrido escribe ese deporte.
DEPORTES_ENVIO = {'⚽ Fútbol': ('Fútbol',), '🏀 Básquetbol': ('NBA', 'Baloncesto'),
                  '🎾 Tenis': ('Tenis',), '🏈 NFL': ('NFL',), '🏒 NHL': ('NHL',),
                  '⚾ Béisbol': ('MLB', 'KBO', 'Béisbol')}
# lo que se puede escribir a mano (workflow, consola): sin acentos ni mayúsculas
_ALIAS = {'futbol': '⚽ Fútbol', 'soccer': '⚽ Fútbol', 'basquet': '🏀 Básquetbol',
          'basquetbol': '🏀 Básquetbol', 'basket': '🏀 Básquetbol',
          'basketball': '🏀 Básquetbol', 'baloncesto': '🏀 Básquetbol', 'nba': '🏀 Básquetbol',
          'tenis': '🎾 Tenis', 'tennis': '🎾 Tenis', 'nfl': '🏈 NFL', 'americano': '🏈 NFL',
          'nhl': '🏒 NHL', 'hockey': '🏒 NHL', 'beisbol': '⚾ Béisbol', 'mlb': '⚾ Béisbol',
          'kbo': '⚾ Béisbol', 'baseball': '⚾ Béisbol'}


def deportes_de_texto(txt) -> List[str]:
    """«futbol,nba» → ['⚽ Fútbol', '🏀 Básquetbol']. Vacío o «todos»: []."""
    import unicodedata
    out: List[str] = []
    for t in str(txt or '').replace(';', ',').replace('+', ',').split(','):
        t = ''.join(c for c in unicodedata.normalize('NFD', t.strip().lower())
                    if unicodedata.category(c) != 'Mn')
        t = ''.join(c for c in t if c.isalnum())
        o = _ALIAS.get(t)
        if o and o not in out:
            out.append(o)
    return out


def _nombres(deportes) -> Optional[set]:
    if not deportes:
        return None
    return {n for d in deportes for n in DEPORTES_ENVIO.get(d, (d,))}


def filtrar_deportes(r: Dict, deportes) -> Dict:
    """El barrido con SÓLO esos deportes (copia; `r` no se toca). Sin
    deportes, el barrido tal cual."""
    nombres = _nombres(deportes)
    if not nombres or not isinstance(r, dict):
        return r
    out = dict(r)
    for k, v in r.items():
        if isinstance(v, list) and any(isinstance(x, dict) and 'partido' in x for x in v):
            out[k] = [x for x in v if not isinstance(x, dict)
                      or str(x.get('deporte') or 'Fútbol') in nombres]
    out['deportes_cubiertos'] = [d for d in (r.get('deportes_cubiertos') or [])
                                 if any(n.lower() in str(d).lower() for n in nombres)] \
        or list(deportes)
    return out


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


# v319 — las líneas que se enseñan de cada conteo
_LINEAS_CONTEO = {'corners': ((8.5, 'mas'), (9.5, 'mas'), (10.5, 'menos')),
                  'tarjetas': ((3.5, 'mas'), (4.5, 'mas'), (5.5, 'menos')),
                  'remates': ((20.5, 'mas'), (24.5, 'mas'), (28.5, 'menos')),
                  'a_puerta': ((6.5, 'mas'), (8.5, 'mas'), (10.5, 'menos'))}


def _bloque_conteo(pick: Dict, que: str, nombre: str) -> List[str]:
    """v319 — EL FORMATO QUE PIDIÓ EL USUARIO, Y NADA ESTIMADO.

    Con histórico real (5+ partidos de cada equipo esta temporada):
        MODELO Córners (datos reales · N partidos local en casa · N visitante fuera):
          λ total esperado: X.X
          Local (promedio histórico en casa): X.X por partido · modelo X.X
          Visitante (promedio histórico fuera): X.X por partido · modelo X.X
          Más de 8.5: XX % · justa X.XX | Más de 9.5 … | Menos de 10.5 …
    Sin él: «MODELO Córners: 🚫 SIN HISTÓRICO REAL — no apostar este
    mercado (motivo)»."""
    c = _conteo_crudo(pick, que)
    if not c or not c.get('lambda_total'):
        stat = {'corners': 'corners', 'tarjetas': 'tarjetas'}.get(que, 'remates')
        motivo = ''
        try:
            import historico_real as hr
            import modo_modelo as mm
            h, a = mm._equipos(pick)
            motivo = hr.evaluar(str(pick.get('clave_liga') or ''), h, a, stat).get('motivo') or ''
        except Exception:
            pass
        return ['MODELO %s: 🚫 SIN HISTÓRICO REAL — no apostar este mercado%s'
                % (nombre, (' (%s)' % motivo) if motivo else '')]
    try:
        import rendimiento_equipos as rq
    except Exception:
        return []
    if c.get('historico_real'):
        cab = ('MODELO %s (datos reales · %s partidos del local en casa · %s del '
               'visitante fuera; %s y %s en la temporada):'
               % (nombre, c.get('n_local_casa'), c.get('n_visita_fuera'),
                  c.get('n_local'), c.get('n_visita')))
    else:
        cab = 'MODELO %s (datos reales de FotMob, últimos partidos de cada equipo):' % nombre
    L = [cab, '   λ total esperado: %s%s' % (_num(c['lambda_total'], 1),
                                            ' (suma de los dos equipos)'
                                            if que in ('corners', 'tarjetas') else '')]
    for lado, prom, lam in (('Local (promedio histórico en casa)', c.get('prom_local_casa'),
                             c.get('lambda_home')),
                            ('Visitante (promedio histórico fuera)', c.get('prom_visita_fuera'),
                             c.get('lambda_away'))):
        L.append('   %s: %s por partido · modelo %s'
                 % (lado, _num(prom, 1) if prom is not None else '—', _num(lam, 1)))
    trozos = []
    for linea, lado in _LINEAS_CONTEO.get(que, ()):
        p = rq.prob_mas_de(c['lambda_total'], linea, c.get('dispersion_total'))
        if p is None:
            continue
        p = p if lado == 'mas' else 1 - p
        trozos.append('%s de %s: %s · justa %s' % ('Más' if lado == 'mas' else 'Menos',
                                                  linea, _pct(p), _num(1 / max(p, 1e-6))))
    if trozos:
        L.append('   ' + ' | '.join(trozos))
    return L


def _meter(pick: Dict) -> List[Dict]:
    import modo_modelo as mm
    try:
        # v369 — LA MISMA TARJETA QUE LA APP: lo precalculado, con la apuesta
        # fijada a la hora de apostar y la tercera (`recos_tarjeta`). Antes
        # se recalculaba sin fijada: el documento podía decir otra cosa.
        if not pick.get('solo_mercado') and str(pick.get('deporte') or 'Fútbol') == 'Fútbol':
            return mm.metidas(mm.recos_tarjeta(pick))
        b = None
        return mm.metidas(mm.con_fijada(pick, mm.recomendadas(pick, b, n=mm.MAX_RECOMENDADAS)))
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
                _esc = _texto_escalon(escalon(pick, m))
                if _esc:
                    L.append('     ↗ %s' % _esc)
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
                L += _bloque_conteo(pick, que, nombre)
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


def escalon(pick: Optional[Dict], m: Dict) -> Optional[Dict]:
    """v318 — EL SIGUIENTE ESCALÓN DE UNA «METER», CON SUS NÚMEROS.

    El usuario: «si la app me da más de 1,5 goles, que el agente me diga
    "súbele a 2,5, veo un ataque muy bueno"; si me dice doble oportunidad,
    que me diga "dale al ganador"». La app no lo recomienda (no está medido
    como apuesta); da el dato para que el agente lo decida con lo que
    encuentre en internet: la apuesta de un escalón más, la probabilidad del
    modelo, lo que cree la casa sin margen y su cuota. Nunca lanza."""
    import re
    try:
        if not pick:
            return None
        ap, mer = str(m.get('apuesta') or ''), str(m.get('mercado') or '')
        im = pick.get('implicitas') or {}

        def _l(x):
            return ('%.1f' % x).rstrip('0').rstrip('.') if x != int(x) else '%d' % x
        mo = re.search(r'(M[aá]s|Menos) de ([0-9]+(?:\.[0-9]+)?)', ap)
        if mer == 'Goles' and mo:
            mas, L = 'menos' not in mo.group(1).lower(), float(mo.group(2))
            L2 = L + 1 if mas else L - 1
            # «menos de 0,5» es apostar al 0-0: no es un escalón útil
            if L2 < (0.5 if mas else 1.5):
                return None
            k = '%.1f' % L2
            gl = pick.get('goles_lineas') or {}
            if gl.get(k) is None:
                return None
            pm = gl[k] if mas else 1 - gl[k]
            c = (im.get('goles') or {}).get(k) or {}
            q = c.get('p')
            return {'apuesta': 'Goles: %s de %s' % ('Más' if mas else 'Menos', k),
                    'prob': pm, 'cuota': c.get('mas' if mas else 'menos'),
                    'casa': (q if mas else (1 - q)) if q is not None else None}
        if mer == 'Goles equipo' and mo and ':' in ap:
            eq = ap.split(':', 1)[0].replace('Goles', '', 1).strip()
            h, a = (str(pick.get('partido') or '').split(' vs ', 1) + [''])[:2]
            lado, clave = (('local', 'goles_home') if eq == h else
                           ('visitante', 'goles_away') if eq == a else (None, None))
            mas = 'menos' not in mo.group(1).lower()
            if not lado or not mas:
                return None
            k = '%.1f' % (float(mo.group(2)) + 1)
            ge = (pick.get('goles_equipo') or {}).get(lado) or {}
            if ge.get(k) is None:
                return None
            c = (im.get(clave) or {}).get(k) or {}
            return {'apuesta': 'Goles %s: Más de %s' % (eq, k), 'prob': ge[k],
                    'cuota': c.get('mas'), 'casa': c.get('p')}
        if mer == 'Doble oportunidad' and ap.endswith(' o empate'):
            eq = ap[:-len(' o empate')]
            h, a = (str(pick.get('partido') or '').split(' vs ', 1) + [''])[:2]
            lado = 'home' if eq == h else 'away' if eq == a else None
            b = pick.get('board') or {}
            if not lado or b.get('Gana ' + eq) is None:
                return None
            return {'apuesta': 'Gana %s' % eq, 'prob': b['Gana ' + eq],
                    'cuota': (im.get('1x2_cuotas') or {}).get(lado),
                    'casa': (im.get('1x2') or {}).get(lado)}
    except Exception as e:
        logger.debug('[ia] escalón: %s', e)
    return None


def _texto_escalon(e: Optional[Dict]) -> str:
    if not e:
        return ''
    t = 'subir a %s: modelo %s' % (e['apuesta'], _pct(e['prob']))
    if e.get('casa') is not None:
        t += ' · casa sin margen %s' % _pct(e['casa'])
    if e.get('cuota'):
        t += ' · cuota %s' % _num(e['cuota'])
    return t


def _linea_meter(reg: Dict, m: Dict, pick: Optional[Dict] = None) -> str:
    p = m.get('prob_meter', m.get('prob'))
    trozos = ['prob %s' % _pct(p)]
    if m.get('cuota'):
        trozos.append('cuota %s' % _num(m['cuota']))
    if m.get('casa'):
        trozos.append(str(m['casa']))
    linea = '   • %s  %s — %s · %s' % (reg.get('hora') or '--:--', reg['partido'],
                                      m.get('apuesta'), ' · '.join(trozos))
    esc = _texto_escalon(escalon(pick, m))
    return linea + ('\n       ↗ %s' % esc if esc else '')


def balance_app(dias: List[str]) -> List[str]:
    """v318 — ASÍ LE FUE A LA APP: lo que dijo «meter», ya liquidado.

    El usuario: «en la aplicación sí están los finalizados y hay muchos
    verdes, y el agente no lo tomó en cuenta». El documento no lo llevaba.
    Se liquida con lo mismo que la pestaña de finalizados
    (`partidos_jugados.de_dia` + `pronosticos_guardados.validar`), sólo las
    apuestas que la app marcó «meter» y sólo de partidos con modelo. Nunca
    lanza."""
    import datetime as _dt
    try:
        import partidos_jugados as pj
        import pronosticos_guardados as pg
    except Exception:
        return []
    L = ['', '📊 ASÍ LE FUE A LA APP — lo que dijo «meter», ya liquidado '
         '(verdes/total por categoría)']
    try:
        d0 = _dt.date.fromisoformat(min(dias))
    except Exception:
        return []
    fechas = [(d0 - _dt.timedelta(days=i)).isoformat() for i in (3, 2, 1, 0)]
    rojos_ayer = []
    hubo = False
    for f in fechas:
        try:
            J = pj.de_dia(f)
        except Exception:
            continue
        cats: Dict[str, List[int]] = {}
        for p in J:
            if p.get('solo_mercado') or p.get('sin_modelo'):
                continue
            dep = str(p.get('deporte') or 'Fútbol')
            try:
                filas = pg.validar(p)
            except Exception:
                continue
            for fl in filas:
                if fl.get('veredicto') != 'meter' or fl.get('estado') not in (
                        pg.CUMPLIDO, pg.FALLADO):
                    continue
                ok = fl['estado'] == pg.CUMPLIDO
                c = cats.setdefault(categoria(fl, dep), [0, 0])
                c[0] += int(ok)
                c[1] += 1
                if not ok and f == fechas[-2]:
                    rojos_ayer.append('%s — %s (%s-%s)' % (
                        p.get('partido'), fl.get('apuesta'),
                        p.get('goles_home', '?'), p.get('goles_away', '?')))
        v = sum(x[0] for x in cats.values())
        n = sum(x[1] for x in cats.values())
        if not n:
            continue
        hubo = True
        orden = [c for c, _ in CATEGORIAS]
        det = ' · '.join('%s %d/%d' % (c, cats[c][0], cats[c][1]) for c in
                         sorted(cats, key=lambda c: (orden.index(c) if c in orden
                                                     else len(orden), c)))
        L.append('   %s: %d verdes de %d (%s) — %s'
                 % (f, v, n, _pct(v / n), det))
    if not hubo:
        return []
    if rojos_ayer:
        L.append('   Rojos del %s: %s' % (fechas[-2], ' | '.join(rojos_ayer[:15])))
    return L


def _estado_fijada(m: Dict) -> str:
    if m.get('fijada'):
        return '🔒 FIJADA %s' % (m.get('fijada_hora') or '')
    if m.get('provisional_hasta'):
        return '⏳ PROVISIONAL, se fija a las %s' % m['provisional_hasta']
    return ''


def que_meter(r: Dict, dias: List[str], deportes=None) -> List[str]:
    """v369 — «✅ QUÉ METER»: la decisión de la app en una línea por apuesta,
    las ⭐ ELIGE primero y por hora, luego el resto por hora. Es lo que un
    agente de IA tiene que leer para decir qué meter. Nunca lanza."""
    import mercados_dia as md
    import modo_modelo as mm
    L = ['', '=' * 70, '✅ QUÉ METER (la decisión de la app) — %s%s'
         % (', '.join(dias), (' · ' + ', '.join(deportes)) if deportes else ''), '=' * 70]
    filas = []
    for dia in dias:
        for reg in md.partidos_del_dia(r, dia, con_extras=True):
            pick = _pick_de(r, reg)
            if not _con_modelo(pick):
                continue
            dep = reg['deporte']
            for m in _meter(pick):
                ele = mm.elige(m, dep) and not m.get('elite')
                real = 0.85 if m.get('elite') else mm.acierta_de_verdad(m, dep)
                filas.append((0 if ele else 1, dia, reg.get('hora') or '--:--', ele, reg, m, real))
    if not filas:
        L.append('Nada que meter en estos días.')
        return L
    filas.sort(key=lambda x: (x[0], x[1], x[2]))
    n_e = sum(1 for f in filas if f[3])
    L.append('%d apuestas · ⭐ %d ELIGE (las que más se cumplen, primero)' % (len(filas), n_e))
    for orden, dia, hora, ele, reg, m, real in filas:
        trozos = ['cuota %s' % _num(m.get('cuota'))] if m.get('cuota') else []
        if m.get('casa'):
            trozos.append(str(m['casa']))
        if real is not None:
            trozos.append('acierta de verdad %s' % _pct(real))
        est = _estado_fijada(m)
        if est:
            trozos.append(est)
        L.append('%s %s %s · %s · %s — %s · %s'
                 % ('⭐' if ele else ('🏆' if m.get('elite') else '•'), dia[5:], hora,
                    reg['deporte'], reg['partido'], m.get('apuesta'), ' · '.join(trozos)))
    L.append('❌ Todo lo que no está en esta lista: NO se mete.')
    return L


def texto(r: Dict, dias: List[str], deportes=None) -> str:
    """El documento de uno o varios días, listo para pegar en una IA.
    v369 — `deportes` (p. ej. ['⚽ Fútbol', '🏀 Básquetbol']): sólo esos."""
    import datetime as _dt
    import mercados_dia as md
    r = filtrar_deportes(r, deportes)
    L = ['PREDICTOR DEPORTIVO — DATOS PARA ANÁLISIS',
         'Días: %s · generado %s UTC%s' % (', '.join(dias),
                                           _dt.datetime.utcnow().strftime(
                                               '%Y-%m-%d %H:%M'),
                                           (' · deportes: ' + ', '.join(deportes))
                                           if deportes else ' · todos los deportes')]
    L += que_meter(r, dias, deportes)
    L += ['', GUIA]
    L += balance_app(dias)
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
                    _linea_meter(reg, m, pick))
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


def resumen(r: Dict, dias: List[str], etiqueta: str, deportes=None) -> str:
    """El pie corto del adjunto de Telegram.
    v369 — con los deportes elegidos y las primeras «qué meter»."""
    import mercados_dia as md
    r = filtrar_deportes(r, deportes)
    n = sum(len(md.partidos_del_dia(r, d, con_extras=False)) for d in dias)
    try:
        qm = [x for x in que_meter(r, dias, deportes)
              if x[:1] in ('⭐', '🏆', '•')]
    except Exception:
        qm = []
    cab = ('📋 *%s* (%s) · %s\n%d partidos · %d para meter (⭐ %d)'
           % (etiqueta, ', '.join(dias), ', '.join(deportes) if deportes else 'todos los deportes',
              n, len(qm), sum(1 for x in qm if x.startswith('⭐'))))
    pie = '\n_El adjunto empieza por «✅ QUÉ METER»: es la decisión de la app._'
    # el pie de un adjunto de Telegram admite 1.024 caracteres: líneas enteras
    lineas, largo = [], len(cab) + len(pie) + 40
    for x in qm:
        x = x.replace('*', '').replace('_', ' ')
        if largo + len(x) + 1 > 1000:
            break
        lineas.append(x)
        largo += len(x) + 1
    resto = len(qm) - len(lineas)
    return (cab + ''.join('\n' + x for x in lineas)
            + ('\n…y %d más en el adjunto' % resto if resto else '') + pie)[:1024]
