#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v162 — LOS PARTIDOS YA JUGADOS, CON EL PRONÓSTICO QUE SE HIZO ANTES.

Qué resuelve
------------
La lista de «Apuestas de hoy» sólo enseña partidos que aún no han empezado,
porque un partido acabado no se puede apostar. Es correcto y no se toca. Pero
un sábado por la tarde deja la lista casi vacía: medido el 2026-08-22, ESPN
tenía 224 partidos de fútbol y la aplicación enseñaba 55.

La v161 los puso detrás de un botón, en una lista escueta con el marcador. Lo
que se pidió ahora es verlos **en la misma lista, con su tarjeta completa** y
una etiqueta `✅ Finalizado`, para poder analizar qué decía el modelo antes de
que se jugaran.

DE DÓNDE SALE EL PRONÓSTICO «PREVIO», Y POR QUÉ NO SE RECALCULA
---------------------------------------------------------------
No se predice el partido ahora. Se recupera lo que el bot calculó por la
mañana, cuando todavía no se había jugado: `predicciones_dia.json` guarda la
matriz de marcador completa de cada partido del día, indexada por el nombre
CRUDO del fixture. De esa matriz salen el 1X2, los goles y el «ambos marcan»,
que son exactamente las mismas cifras que vio quien miró la tarjeta antes del
pitido inicial.

Recalcularlo tendría dos problemas y ninguna ventaja: costaría cargar los
motores de todas las ligas del día —el grueso del arranque en frío, ~50 s— y,
peor, el ELO y las medias móviles ya se habrán movido con el resultado, así que
el número no sería «lo que el modelo dijo», sino una reconstrucción posterior
con información del futuro. Enseñar eso etiquetado como pronóstico previo sería
mentir con precisión decimal.

LO QUE ESTE MÓDULO **NO** HACE
------------------------------
No entra en `alpha_finder`. Los partidos que devuelve NO pasan por la Sección 1
ni por la Sección 2, no tienen EV, no se comparan con la cuota y no pueden
llegar a Telegram. La única forma de que un partido acabado se convirtiera en
un pick sería que alguien lo metiera en el barrido, y esto vive fuera a
propósito.

Coste
-----
`fixtures_espn.jugados_del_dia` son 61 peticiones a ESPN, medidas en 5,2 s, y
quedan en la caché de 5 minutos del módulo. La vista entera va además detrás de
`guardia_barrido`, con 3 h de caducidad.
"""
import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _board_de_matriz(matriz, home: str, away: str,
                     probs: Optional[Dict] = None) -> Dict[str, float]:
    """
    Todas las probabilidades de la tarjeta, sacadas de la matriz de marcador.

    Es la misma cuenta que hace el barrido: 1X2 por triángulos, más/menos 2,5
    sumando la antidiagonal y «ambos marcan» quitando fila y columna cero. Se
    repite aquí en vez de importarla de `alpha_finder` porque allí vive dentro
    de `_mercados_del_partido`, que necesita cuotas —y un partido jugado ya no
    las tiene.
    """
    salida: Dict[str, float] = {}
    try:
        M = np.asarray(matriz, dtype=float)
        if M.ndim != 2 or M.size == 0:
            return salida
        idx = np.arange(M.shape[0])
        total = idx[:, None] + idx[None, :]
        if probs and all(k in probs for k in ('home', 'draw', 'away')):
            pl, px, pv = (float(probs['home']), float(probs['draw']),
                          float(probs['away']))
        else:
            pl = float(np.tril(M, -1).sum())
            px = float(np.trace(M))
            pv = float(np.triu(M, 1).sum())
        salida['Gana %s' % home] = pl
        salida['Empate'] = px
        salida['Gana %s' % away] = pv
        over = float(M[total > 2].sum())
        salida['Más de 2.5'] = over
        salida['Menos de 2.5'] = 1.0 - over
        btts = float(M[1:, 1:].sum())
        salida['Ambos marcan: Sí'] = btts
        salida['Ambos marcan: No'] = 1.0 - btts
    except Exception as e:
        logger.debug('[jugados] board de la matriz: %s', e)
    return {k: round(v, 4) for k, v in salida.items()
            if v is not None and 0.0 <= v <= 1.0}


def _hora_txt(inicio: str) -> str:
    """La hora de inicio en el huso de la pantalla, como en el resto de la app."""
    if not inicio:
        return ''
    try:
        import pandas as pd
        import horario
        t = pd.Timestamp(inicio)
        if t.tzinfo is None:
            t = t.tz_localize('UTC')
        return horario.hora(t) or ''
    except Exception as e:
        logger.debug('[jugados] hora de %s: %s', inicio, e)
        return ''


FICHERO_JUGADOS = 'jugados_dia.json'
# Un día acabado ya no cambia, pero el día EN CURSO sí: a las 18:00 faltan los
# partidos de la noche. Por eso el precálculo del día de hoy caduca y el de
# ayer no. Tres horas es la cadencia del cron que lo escribe.
CADUCIDAD_HOY_S = 3 * 3600


def _ruta_jugados() -> str:
    """Se resuelve en cada llamada, no al importar.

    Un `def leer(ruta=FICHERO)` ata el valor en el momento de definir la
    función, y este proyecto ya perdió una tarde con eso en la v220.
    """
    import os
    return os.environ.get('JUGADOS_DIA_FICHERO') or FICHERO_JUGADOS


def _leer_precalculo(dia: str, permitir_viejo: bool = False):
    """La lista precocinada de `dia`, o `None` si no sirve.

    v309 — con `permitir_viejo=True` devuelve también la del día en curso
    aunque haya caducado: `de_dia` la UNE con la red en vez de tirarla,
    porque ahí dentro están los partidos archivados del pronóstico (con su
    apuesta previa) que ESPN no conoce.

    `None` y `[]` NO son lo mismo: `[]` es «ese día no se jugó nada», que es
    una respuesta legítima y ahorra la red; `None` es «no hay precálculo», y
    obliga a salir a buscarlo.
    """
    import json
    import os
    import time
    ruta = _ruta_jugados()
    try:
        if not os.path.exists(ruta):
            return None
        with open(ruta, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        logger.debug('[jugados] precálculo ilegible: %s: %s',
                     type(e).__name__, e)
        return None
    if str(doc.get('dia') or '') != str(dia):
        return None
    partidos = doc.get('partidos')
    if not isinstance(partidos, list):
        return None
    # ¿es el día de hoy? entonces caduca
    try:
        import datetime as _dt
        import dia_picks as _dp
        hoy = _dp.hoy_local().strftime('%Y-%m-%d')      # v305: CDMX, no el servidor
    except Exception:
        hoy = None
    if str(dia) == hoy and not permitir_viejo:
        edad = time.time() - float(doc.get('ts') or 0)
        if edad > CADUCIDAD_HOY_S:
            logger.info('[jugados] el precálculo del día en curso tiene %.1f h '
                        'y faltarían los partidos de después; se va a la red',
                        edad / 3600.0)
            return None
    return partidos


# ---------------------------------------------------------------------------
# v305 — NINGÚN FINALIZADO DEL DÍA SE PIERDE
# ---------------------------------------------------------------------------
# El usuario, con «Partidos de hoy (2)» delante a las 17:44 de CDMX: «me
# borras los anteriores del día de hoy, cuando debería mostrarme todos los
# finalizados del día hasta la hora de actualización». Eran tres fallos:
#
#   1. EL DÍA ERA EL DEL SERVIDOR. `precalculo_dia` llamaba con
#      `datetime.now()`, que en el runner es UTC: de 18:00 a 24:00 de CDMX
#      cocinaba el día SIGUIENTE, y la aplicación, que pide el de CDMX, no lo
#      encontraba.
#   2. NO IBA A LA RED. El barrido del mismo proceso deja los días marcados
#      como «ya barridos» y `jugados_del_dia` se fiaba: sólo salían los que
#      estaban terminados en el instante del barrido.
#   3. SÓLO MIRABA LAS LIGAS DE CLUBES DE ESPN. Los partidos de otras ramas
#      —selecciones, Champions femenina, Liga MX Femenil— estaban por la
#      mañana en «Hoy» con su pronóstico, desaparecían de la lista en cuanto
#      empezaban (el barrido sólo guarda lo que está por jugarse) y nunca
#      volvían como finalizados.
#
# Ahora cada pasada del precálculo: va a la red de verdad, ARCHIVA los
# partidos del pronóstico anterior que ya empezaron (con su pronóstico previo
# y el marcador de su histórico si ya está), y UNE con lo que ya había en el
# fichero del mismo día. Una lista del día sólo puede crecer.

HORAS_PARTIDO = 2.5          # un partido que empezó hace más, ya terminó


# ---------------------------------------------------------------------------
# v309 — SE ARCHIVA EN CUANTO EMPIEZA, CON LA APUESTA QUE SE RECOMENDÓ
# ---------------------------------------------------------------------------
# El usuario: «en los partidos finalizados no me despliegas todos los que
# finalizaron ya y con su apuesta que tú recomendaste; quiero que estén
# todas».
#
# MEDIDO el 2026-09-25 (viernes de fecha FIFA) sobre las ocho pasadas del
# precálculo: 47 partidos de fútbol del día pasaron por el pronóstico y
# `jugados_dia.json` tenía SIETE. Faltaban los 25 de selecciones (Italia-
# Bélgica, Turquía-Francia, Mozambique-Senegal…), justo los que el usuario
# había mirado.
#
# LA CAUSA era aritmética. El archivo exigía que el partido hubiera empezado
# hace más de 2,5 h, y leía el pronóstico ANTERIOR, el que la pasada va a
# sobrescribir. Las pasadas van cada ~1,6 h: un partido que empieza entre
# dos pasadas tiene, en la siguiente, entre 0 y 1,6 h de juego — nunca 2,5 —
# y esa pasada escribe un pronóstico nuevo en el que ya no está. En la
# siguiente ya no había de dónde archivarlo. Se salvaban sólo los que ESPN
# trae por su cuenta (ligas de clubes), y las selecciones no están ahí.
#
# Ahora se archiva en cuanto EMPIEZA, con tres cosas:
#   · la apuesta que la tarjeta recomendaba antes del pitido
#     (`recomendadas_previas`), calculada sobre el pick del pronóstico
#     anterior, que es estado de antes del partido. Si ya estaba archivado,
#     no se toca: gana siempre el primero (el más cercano al inicio por
#     delante), igual que el registro de `pronosticos_guardados`;
#   · el marcador, del histórico de su competición o de FotMob (una
#     petición por día UTC, trae TODOS los partidos: selecciones, femenil,
#     ligas chicas);
#   · mientras no tiene marcador y no han pasado 2,5 h, la tarjeta dice «en
#     juego» en vez de «Finalizado»: no se inventa un final.


def _recomendadas_previas(pick: Dict) -> List[Dict]:
    """Lo que la tarjeta recomendaba de este partido ANTES de empezar.

    Es la misma cuenta que pinta la tarjeta (`modo_modelo.recomendadas` con
    los bloques de córners, tarjetas y remates), sobre el pick del
    pronóstico anterior. Si la casa no cotizaba nada jugable, la lectura del
    modelo sin precio (`pronosticos_guardados._del_board`), que la tarjeta
    rotula como tal. Nunca lanza.
    """
    try:
        import modo_modelo as mm
        import pronosticos_guardados as pg
    except Exception as e:
        logger.debug('[jugados] sin modo_modelo: %s', e)
        return []
    q = {k: v for k, v in pick.items()
         if k not in ('jugado', 'archivado_del_pronostico')}
    recos = []
    try:
        _rm = mm.remates_tarjeta(q) or {}
        bloques = {'Córners': mm.corners_tarjeta(q),
                   'Tarjetas': mm.tarjetas_tarjeta(q),
                   'Remates': _rm.get('totales'),
                   'Remates a puerta': _rm.get('a_puerta')}
        recos = mm.recomendadas(q, bloques, n=mm.MAX_RECOMENDADAS) or []
    except Exception as e:
        logger.debug('[jugados] recomendadas de %s: %s', pick.get('partido'), e)
    # v310 — LO QUE LA TARJETA ENSEÑÓ, NI UNA MÁS: la principal (aunque sea
    # «no meter», es la única forma de decir «esto es lo mejor y no llega») y
    # las alternativas que sí eran «meter» (`modo_modelo`, regla de la v308).
    # Guardar también las «no meter» mezclaba en la liquidación apuestas que
    # la tarjeta nunca propuso.
    recos = recos[:1] + [o for o in recos[1:]
                         if o.get('veredicto_vp') != 'no_meter']
    if recos:
        return [dict(pg._fila(r), origen='archivo') for r in recos]
    try:
        return pg._del_board(q)
    except Exception:
        return []


def _sin_femenino(t: str) -> str:
    import re
    return re.sub(r'\s*(\((W|F)\)|\bW\b|\bWomen\b|\bFemenil\b)\s*$', '',
                  str(t or ''), flags=re.I).strip()


def marcadores_fotmob(dia: str) -> List[Dict]:
    """Los partidos TERMINADOS de FotMob que caen en el día `dia` de CDMX.

    Un día de CDMX son dos días UTC, así que se piden los dos. Devuelve
    `[{'ini', 'home', 'away', 'gh', 'ga', 'liga'}]` con `ini` en UTC.
    Nunca lanza; sin red, lista vacía.
    """
    import datetime as _dt
    try:
        import fuente_bajas as fb
        import horario as hz
    except Exception:
        return []
    try:
        d0 = _dt.date.fromisoformat(str(dia)[:10])
    except Exception:
        return []
    fuera = []
    for d in (d0, d0 + _dt.timedelta(days=1)):
        doc = fb._get(fb.FOTMOB_DIA.format(fecha=d.strftime('%Y%m%d'))) or {}
        for L in doc.get('leagues') or []:
            for m in L.get('matches') or []:
                est = m.get('status') or {}
                if not est.get('finished') or est.get('cancelled'):
                    continue
                ini = hz._a_utc(est.get('utcTime'))
                h, a = m.get('home') or {}, m.get('away') or {}
                if ini is None or h.get('score') is None or a.get('score') is None:
                    continue
                fuera.append({'ini': ini, 'home': h.get('name'),
                              'away': a.get('name'), 'id': m.get('id'),
                              'gh': float(h['score']), 'ga': float(a['score']),
                              'liga': L.get('name')})
    logger.info('[jugados] FotMob: %d partidos terminados alrededor del %s',
                len(fuera), dia)
    return fuera


def _casar_fotmob(p: Dict, lista: List[Dict]) -> Optional[Dict]:
    """El partido de FotMob que es `p`: misma hora de inicio (±20 min) y los
    dos nombres parecidos. La hora hace casi todo el trabajo — a la misma
    hora hay pocos partidos —, así que el listón de nombre puede ser el del
    emparejador de clubes sin cruzar equipos."""
    try:
        import cuotas_multi as cm
        import horario as hz
    except Exception:
        return None
    ini = hz._a_utc(p.get('inicio'))
    par = str(p.get('partido') or '')
    if ini is None or ' vs ' not in par:
        return None
    hh, aa = (_sin_femenino(x.strip()) for x in par.split(' vs ', 1))
    mejor, mejor_s = None, 0.0
    for f in lista or []:
        if abs((f['ini'] - ini).total_seconds()) > 20 * 60:
            continue
        sh = cm._sim_club(hh, _sin_femenino(f.get('home')))
        sa = cm._sim_club(aa, _sin_femenino(f.get('away')))
        s = min(sh, sa)
        if max(sh, sa) >= 0.85:
            s = max(s, 0.6)          # uno clavado y a la misma hora
        if s > mejor_s:
            mejor, mejor_s = f, s
    return mejor if mejor_s >= 0.55 else None


# Los mercados que no salen del marcador y necesitan la estadística del
# partido. Sin ella la tarjeta los deja ⏳; con ella, verde o rojo.
_BLOQUES_STATS = ('corners', 'tarjetas', 'remates', 'remates_on')


def _stats_de_fotmob(mid) -> Optional[Dict]:
    """Córners, amarillas, remates y a puerta de un partido TERMINADO, de su
    ficha de FotMob (`matchDetails`, con la caché de disco de
    `fuente_bajas`). Mismas claves que `pronosticos_guardados`
    (`corners_home`…). Las amarillas, como en la caché de ESPN: sólo
    amarillas. None si la ficha no trae estadísticas (amistosos menores)."""
    try:
        import fuente_bajas as fb
        import remates_fotmob as rf
        det = fb.detalle(mid)
        s = rf._stats_equipo(((det or {}).get('content')) or {})
    except Exception as e:
        logger.debug('[jugados] stats FotMob %s: %s', mid, e)
        return None
    if not s:
        return None

    def par(k):
        v = s.get(k) or (None, None)
        return v[0], v[1]
    ch, ca = par('corners')
    th, ta = par('yellow_cards')
    rh, ra = par('total_shots')
    oh, oa = par('ShotsOnTarget')
    out = {'fuente': 'fotmob', 'corners_home': ch, 'corners_away': ca,
           'tarjetas_home': th, 'tarjetas_away': ta,
           'remates_home': rh, 'remates_away': ra,
           'remates_on_home': oh, 'remates_on_away': oa}
    if all(v is None for k, v in out.items() if k != 'fuente'):
        return None
    return out


def poner_estadisticas(partidos: List[Dict], dia: str,
                       fotmob: List[Dict] = None) -> int:
    """v309 — la estadística de los partidos terminados cuya apuesta
    recomendada la necesita (córners, tarjetas, remates). Una ficha de
    FotMob por partido, y sólo de ésos. Devuelve cuántos rellenó."""
    faltan = [p for p in (partidos or [])
              if p.get('goles_home') is not None and not p.get('stats_partido')
              and any(str((r or {}).get('bloque')) in _BLOQUES_STATS
                      for r in (p.get('recomendadas_previas') or []))]
    if not faltan:
        return 0
    lista = fotmob if fotmob is not None else marcadores_fotmob(dia)
    n = 0
    for p in faltan:
        mid = p.get('fotmob_id')
        if not mid:
            f = _casar_fotmob(p, lista)
            mid = f.get('id') if f else None
        if not mid:
            continue
        p['fotmob_id'] = mid
        st = _stats_de_fotmob(mid)
        if st:
            p['stats_partido'] = st
            n += 1
    return n


def poner_marcadores(partidos: List[Dict], dia: str,
                     ahora: float = None, fotmob: List[Dict] = None) -> int:
    """Rellena el marcador de los que ya deberían haber terminado y no lo
    tienen: primero el histórico de su competición, luego FotMob. Devuelve
    cuántos rellenó."""
    import time
    ahora = float(ahora if ahora is not None else time.time())
    try:
        import horario as hz
    except Exception:
        return 0
    faltan = []
    for p in partidos or []:
        if p.get('goles_home') is not None:
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is None or ini.timestamp() + 1.75 * 3600 > ahora:
            continue                 # aún no puede haber terminado
        m = _marcador(p)
        if m:
            p['goles_home'], p['goles_away'] = m
            p['marcador_fuente'] = 'historico'
        else:
            faltan.append(p)
    n = sum(1 for p in partidos or [] if p.get('marcador_fuente') == 'historico')
    lista = fotmob
    if faltan:
        lista = lista if lista is not None else marcadores_fotmob(dia)
        for p in faltan:
            f = _casar_fotmob(p, lista)
            if f:
                p['goles_home'], p['goles_away'] = f['gh'], f['ga']
                p['marcador_fuente'] = 'fotmob'
                p['fotmob_id'] = f.get('id')
                n += 1
    try:
        _s = poner_estadisticas(partidos, dia, fotmob=lista)
        logger.info('[jugados] estadísticas de FotMob: %d partidos', _s)
    except Exception as e:
        logger.debug('[jugados] estadísticas: %s', e)
    return n


def _norm(t) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t or '').lower())
    return ''.join(c for c in t.encode('ascii', 'ignore').decode('ascii')
                   if c.isalnum())


def _nombres(p: Dict):
    """(local, visitante) normalizados; en selecciones, por el nombre
    CANÓNICO en inglés, que el mismo partido puede llegar como «Azerbaiyán»
    desde el tablón y como «Azerbaijan» desde ESPN."""
    par = str(p.get('partido') or '')
    if ' vs ' not in par:
        return _norm(par), ''
    hh, aa = (x.strip() for x in par.split(' vs ', 1))
    h, a = _norm(hh), _norm(aa)
    if str(p.get('clave_liga') or '') == 'selecciones':
        try:
            from config import TEAM_NAMES_EN as _EN
            import name_mapper as _nm
            import selecciones_dia as _sd
            m = _sd._motor()
            if m is not None:
                cat = _sd.catalogo(m)
                ch = _nm.mapear(hh, list(cat), contexto='selecciones')
                ca = _nm.mapear(aa, list(cat), contexto='selecciones')
                if ch and ca:
                    h = _norm(_EN.get(cat[ch], ch))
                    a = _norm(_EN.get(cat[ca], ca))
        except Exception as e:
            logger.debug('[jugados] nombre canónico de %s: %s', par, e)
    return h, a


def _llave(p: Dict) -> str:
    h, a = _nombres(p)
    return h + '|' + a


def _marcador(p: Dict):
    """(goles local, goles visitante) desde el histórico de su competición,
    o None. Para las ramas que no son las ligas de ESPN."""
    import os
    clave = str(p.get('clave_liga') or '')
    ruta = 'historico_%s.csv' % clave
    if not clave or not os.path.exists(ruta):
        return None
    par = str(p.get('partido') or '')
    if ' vs ' not in par:
        return None
    h, a = _nombres(p)
    try:
        import pandas as pd
        import dia_picks as dp
        d = pd.read_csv(ruta, usecols=lambda c: c in (
            'date', 'home_team', 'away_team', 'home_goals', 'away_goals'))
        fecha_utc = str(p.get('fecha') or '')[:10]
        dias = {fecha_utc, dp.dia_de(p)}
        d = d[d['date'].astype(str).str[:10].isin(dias)]
        for r in d.itertuples(index=False):
            if _norm(r.home_team) == h and _norm(r.away_team) == a:
                return float(r.home_goals), float(r.away_goals)
    except Exception as e:
        logger.debug('[jugados] marcador de %s: %s', par, e)
    return None


def archivar_del_pronostico(dia: str, ruta_pronostico: str,
                            ahora: float = None,
                            ya: Optional[set] = None) -> List[Dict]:
    """Los partidos de fútbol de `dia` (CDMX) que estaban en el pronóstico y
    ya EMPEZARON (v309), como tarjetas de finalizado con su pronóstico previo
    y la apuesta que se recomendaba. `ya` son las llaves que el fichero ya
    tiene archivadas con su apuesta: ésas no se recalculan."""
    import json
    import os
    import time
    ahora = float(ahora if ahora is not None else time.time())
    if not os.path.exists(ruta_pronostico):
        return []
    try:
        with open(ruta_pronostico, encoding='utf-8') as f:
            doc = json.load(f)
        pr = ((doc.get('datos') or doc).get('pronosticos')) or []
        generado_ts = float(doc.get('generado_ts') or 0) or None
    except Exception as e:
        logger.debug('[jugados] pronóstico previo ilegible: %s', e)
        return []
    try:
        import dia_picks as dp
        import horario as hz
    except Exception:
        return []
    fuera = []
    for p in pr:
        if not isinstance(p, dict) or str(p.get('deporte') or '') != 'Fútbol':
            continue
        if dp.dia_de(p) != dia:
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is None or ini.timestamp() > ahora:
            continue                     # v309: basta con que haya EMPEZADO
        q = dict(p)
        q['jugado'] = True
        q['archivado_del_pronostico'] = True
        q['archivado_ts'] = ahora
        if generado_ts:
            # si el pronóstico se escribió ya empezado el partido, se sabe
            q['pronostico_ts'] = generado_ts
        if not (ya and _llave(q) in ya):
            q['recomendadas_previas'] = _recomendadas_previas(p)
        m = _marcador(q)
        if m:
            q['goles_home'], q['goles_away'] = m
            q['marcador_fuente'] = 'historico'
        fuera.append(q)
    return fuera


_CAMPOS_MARCADOR = ('goles_home', 'goles_away', 'marcador_fuente')
_CAMPOS_SUMA = ('_home_crudo', '_away_crudo', 'board', 'goles_lineas', 'prob')


def _misma_cita(a: Dict, b: Dict) -> bool:
    """El mismo partido escrito distinto: misma competición, misma hora de
    inicio y al menos un equipo que casa. Pasa cuando ESPN dice «Inverness
    C» y el pronóstico «Inverness Caledonian Thistle»."""
    if str(a.get('clave_liga') or '') != str(b.get('clave_liga') or ''):
        return False
    try:
        import cuotas_multi as cm
        import horario as hz
        ia, ib = hz._a_utc(a.get('inicio')), hz._a_utc(b.get('inicio'))
        if ia is None or ib is None or abs((ia - ib).total_seconds()) > 15 * 60:
            return False
        pa, pb = str(a.get('partido') or ''), str(b.get('partido') or '')
        if ' vs ' not in pa or ' vs ' not in pb:
            return False
        ha, aa = pa.split(' vs ', 1)
        hb, ab = pb.split(' vs ', 1)
        return max(cm._sim_club(ha, hb), cm._sim_club(aa, ab)) >= 0.8
    except Exception:
        return False


def _fusion(viejo: Dict, nuevo: Dict) -> Dict:
    """v309 — dos copias del mismo partido. Manda la que trae la apuesta
    previa (y de ellas la PRIMERA archivada, que es la de antes del
    inicio); de la otra se toma lo que le falte: el marcador y los nombres
    crudos de ESPN, que son la llave del precálculo del día."""
    if 'recomendadas_previas' in nuevo and 'recomendadas_previas' not in viejo:
        base, otro = nuevo, viejo
    else:
        base, otro = viejo, nuevo
    out = dict(base)
    if out.get('goles_home') is None and otro.get('goles_home') is not None:
        for c in _CAMPOS_MARCADOR:
            if otro.get(c) is not None:
                out[c] = otro[c]
    for c in _CAMPOS_SUMA:
        if out.get(c) in (None, {}, []) and otro.get(c) not in (None, {}, []):
            out[c] = otro[c]
    if out.get('sin_modelo') and out.get('board'):
        out.pop('sin_modelo', None)
    return out


def unir(*listas: List[Dict]) -> List[Dict]:
    """Une sin repetir. v309: ante el mismo partido no se elige uno y se
    tira el otro — se FUSIONAN (`_fusion`), para que el marcador de ESPN y
    la apuesta archivada acaben en la misma tarjeta."""
    por: Dict[str, Dict] = {}
    for lista in listas:
        for p in (lista or []):
            if not isinstance(p, dict):
                continue
            k = _llave(p)
            if not k:
                continue
            if k not in por:
                gemelo = next((k2 for k2, v in por.items()
                               if _misma_cita(v, p)), None)
                if gemelo is not None:
                    k = gemelo
            viejo = por.get(k)
            por[k] = p if viejo is None else _fusion(viejo, p)
    return list(por.values())


def escribir_dia(dia: str, ruta: str = '',
                 ruta_pronostico: str = 'pronostico_dia.json') -> int:
    """Cocina los partidos jugados de `dia` y los deja en disco. Para el cron.

    `dia` es un día de CDMX. v305: va siempre a la red, archiva lo que ya se
    jugó del pronóstico anterior y UNE con lo que el fichero ya tuviera de
    ese mismo día, así que la lista del día sólo crece (ver arriba).

    Devuelve cuántos escribió. No lanza: si falla, la aplicación sigue con el
    respaldo por red, que es más lento pero correcto.
    """
    import json
    import time
    try:
        import os
        os.environ.pop('_JUGADOS_DESDE_PRECALCULO', None)
        de_red = _de_dia_por_red(dia, usar_cache=False)
        previos = []
        try:
            with open(ruta or _ruta_jugados(), encoding='utf-8') as f:
                _doc = json.load(f) or {}
            if str(_doc.get('dia') or '') == str(dia):
                previos = _doc.get('partidos') or []
        except Exception:
            previos = []
        ya = {_llave(p) for p in previos
              if isinstance(p, dict) and 'recomendadas_previas' in p}
        archivados = archivar_del_pronostico(dia, ruta_pronostico, ya=ya)
        # v309 — el orden importa: lo ya archivado va ANTES que lo recién
        # archivado, para que gane la apuesta más antigua (la de antes del
        # inicio) y no la de un pronóstico escrito con el partido en juego.
        partidos = unir(previos, archivados, de_red)
        # los que ya deberían haber terminado y no tienen marcador: su
        # histórico y, si no, FotMob (selecciones, femenil, ligas chicas)
        _n = poner_marcadores(partidos, dia)
        logger.info('[jugados] marcadores rellenados: %d', _n)
        partidos.sort(key=lambda p: str(p.get('inicio') or ''))
        doc = {'dia': str(dia), 'ts': time.time(),
               'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'partidos': partidos}
        with open(ruta or _ruta_jugados(), 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
        logger.info('[jugados] %d partidos del %s escritos en %s',
                    len(partidos), dia, ruta or _ruta_jugados())
        return len(partidos)
    except Exception as e:
        logger.warning('[jugados] no se pudo escribir el precálculo: %s: %s',
                       type(e).__name__, e)
        return 0


def de_dia(dia: str, maximo: int = 200) -> List[Dict]:
    """
    Los partidos jugados de `dia`, con la forma que espera `modo_modelo.tarjeta`.

    Cada uno lleva `jugado=True` y su marcador. Los que no tengan pronóstico
    guardado salen igual, con `sin_modelo`: que el bot no llegara a
    precalcularlos no es motivo para esconder el partido — el usuario pidió
    verlos todos.
    """
    if not dia:
        return []
    # v229 — PRIMERO EL PRECÁLCULO, Y LA RED SÓLO SI NO LO HAY.
    #
    # Esto costaba cero mientras ESPN rechazaba los rangos de fechas: las 62
    # competiciones fallaban y la lista salía vacía al instante. Al arreglarlo
    # (v228) la función pasó a hacer su trabajo de verdad —190 partidos, 186
    # peticiones, 13 segundos medidos— y ese trabajo ocurre AL PINTAR.
    #
    # Es exactamente el coste que la v220 sacó del render por el mismo motivo,
    # y aquí duele igual: se paga en cada pasada de Streamlit, con el usuario
    # esperando delante, y para eso está el cron.
    #
    # El respaldo por red NO se quita. Un día sin precálculo tiene que seguir
    # enseñando los partidos acabados, aunque tarde: preferir lento a vacío es
    # la misma regla que gobierna el resto del precálculo.
    precocinado = _leer_precalculo(dia)
    if precocinado is not None:
        logger.info('[jugados] %d partidos del %s desde el precálculo '
                    '(sin tocar la red)', len(precocinado), dia)
        return _para_la_vista(precocinado[:maximo])
    # v309 — un precálculo CADUCADO del día en curso no se tira: lleva los
    # partidos archivados con su apuesta, que la red de ESPN no sabe
    # reconstruir (las selecciones no están ahí). Se une con lo de la red.
    viejo = _leer_precalculo(dia, permitir_viejo=True) or []
    return _para_la_vista(unir(viejo, _de_dia_por_red(dia, maximo))[:maximo])


def _para_la_vista(partidos: List[Dict], ahora: float = None) -> List[Dict]:
    """v309 — lo que la vista necesita y el fichero no guarda: el nombre
    ÚNICO de la competición (`nombres_ligas`), para que el filtro de liga
    case con el de los que aún no se juegan, y la marca `en_juego` de los
    que empezaron hace menos de 2,5 h y todavía no tienen marcador."""
    import time
    ahora = float(ahora if ahora is not None else time.time())
    try:
        import nombres_ligas as nl
    except Exception:
        nl = None
    try:
        import horario as hz
    except Exception:
        hz = None
    fuera = []
    for p in partidos or []:
        if not isinstance(p, dict):
            continue
        q = dict(p)
        if nl is not None:
            nl.aplicar(q)
        q.pop('en_juego', None)
        if q.get('goles_home') is None and hz is not None:
            ini = hz._a_utc(q.get('inicio'))
            if ini is not None and ini.timestamp() + HORAS_PARTIDO * 3600 > ahora:
                q['en_juego'] = True
        fuera.append(q)
    return fuera


def _de_dia_por_red(dia: str, maximo: int = 200,
                    usar_cache: bool = True) -> List[Dict]:
    """El camino largo: 62 competiciones contra ESPN. Lo usa el cron, y la
    aplicación sólo cuando no hay precálculo del día."""
    if not dia:
        return []
    try:
        import fixtures_espn
    except Exception as e:
        logger.debug('[jugados] sin fixtures_espn: %s', e)
        return []
    try:
        crudos = fixtures_espn.jugados_del_dia(
            fixtures_espn.claves_de_futbol(), dia, usar_cache=usar_cache)
    except Exception as e:
        logger.warning('[jugados] no se pudieron pedir los resultados: %s', e)
        return []

    try:
        import predicciones_dia as _pd
    except Exception:
        _pd = None

    salida: List[Dict] = []
    for r in crudos[:maximo]:
        clave = r.get('clave_liga')
        home, away = r.get('home'), r.get('away')
        if not (clave and home and away):
            continue
        pick: Dict = {
            'partido': '%s vs %s' % (home, away),
            'liga': r.get('liga') or clave,
            'clave_liga': clave,
            'deporte': 'Fútbol',
            'fecha': str(r.get('fecha') or '')[:10],
            'inicio': r.get('inicio'),
            'hora_txt': _hora_txt(r.get('inicio')),
            'jugado': True,
            'goles_home': r.get('goles_home'),
            'goles_away': r.get('goles_away'),
            # v177 — EL NOMBRE CRUDO DE ESPN VIAJA CON EL PARTIDO.
            #
            # `predicciones_dia.json` y `mercado_dia.json` se indexan
            # los dos por el nombre TAL COMO LLEGA DEL FIXTURE, no por
            # el del catálogo del modelo. Abajo, `pick['partido']` pasa
            # a los nombres MAPEADOS —hacen falta para que córners y
            # tarjetas encuentren su histórico— y con eso se perdía la
            # única llave que abre esos dos ficheros.
            #
            # Sin ella, un partido acabado no puede recuperar lo que la
            # aplicación recomendó por la mañana, y la tarjeta acababa
            # diciendo «sin pronóstico previo» de un partido que sí se
            # había evaluado. Es el defecto que el usuario reportó en
            # Dalian Yingbo - Beijing Guoan.
            '_home_crudo': home,
            '_away_crudo': away,
        }
        pred = None
        if _pd is not None:
            try:
                pred = _pd.prediccion(clave, home, away)
            except Exception as e:
                logger.debug('[jugados] predicción de %s: %s', clave, e)
        if pred:
            # el nombre MAPEADO viaja dentro de la predicción; se usa ése para
            # que el rótulo del partido y el catálogo del histórico coincidan,
            # que es lo que hace que córners y tarjetas encuentren sus datos.
            hm = pred.get('home') or home
            am = pred.get('away') or away
            pick['partido'] = '%s vs %s' % (hm, am)
            pick['board'] = _board_de_matriz(pred.get('score_matrix'), hm, am,
                                             pred.get('probabilities'))
            # v163.1 — las tres líneas de goles, igual que en los que aún no se
            # han jugado. Van aparte del `board` a propósito: aquí `prob` sale
            # de `max(board.values())` y «Más de 1,5» lo ganaría siempre.
            try:
                import alpha_finder as _af
                pick['goles_lineas'] = _af.lineas_de_goles(pred)
            except Exception as e:
                logger.debug('[jugados] líneas de goles: %s', e)
            if pick['board']:
                pick['prob'] = max(pick['board'].values())
        if not pick.get('board'):
            pick['sin_modelo'] = True
        salida.append(pick)
    logger.info('[jugados] %d partidos jugados el %s · %d con pronóstico previo',
                len(salida), dia,
                sum(1 for p in salida if not p.get('sin_modelo')))
    return salida
