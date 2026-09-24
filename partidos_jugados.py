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


def _leer_precalculo(dia: str):
    """La lista precocinada de `dia`, o `None` si no sirve.

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
    if str(dia) == hoy:
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


def _norm(t) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t or '').lower())
    return ''.join(c for c in t.encode('ascii', 'ignore').decode('ascii')
                   if c.isalnum())


def _llave(p: Dict) -> str:
    par = str(p.get('partido') or '')
    return _norm(par)


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
    h, a = (_norm(x) for x in par.split(' vs ', 1))
    if clave == 'selecciones':
        # el pronóstico pudo salir con el nombre del tablón en español
        # («Azerbaiyán»); el histórico va en inglés. Se pasa por el código.
        try:
            from config import TEAM_NAMES_EN as _EN
            import name_mapper as _nm
            import selecciones_dia as _sd
            cat = _sd.catalogo(_sd._motor())
            hh, aa = (x.strip() for x in par.split(' vs ', 1))
            ch = _nm.mapear(hh, list(cat), contexto='selecciones')
            ca = _nm.mapear(aa, list(cat), contexto='selecciones')
            if ch and ca:
                h = _norm(_EN.get(cat[ch], ch))
                a = _norm(_EN.get(cat[ca], ca))
        except Exception as e:
            logger.debug('[jugados] nombre canónico de %s: %s', par, e)
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
                            ahora: float = None) -> List[Dict]:
    """Los partidos de fútbol de `dia` (CDMX) que estaban en el pronóstico y
    ya se jugaron, como tarjetas de finalizado con su pronóstico previo."""
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
        if ini is None or ini.timestamp() + HORAS_PARTIDO * 3600 > ahora:
            continue                     # no ha empezado o puede seguir en juego
        q = dict(p)
        q['jugado'] = True
        q['archivado_del_pronostico'] = True
        m = _marcador(q)
        if m:
            q['goles_home'], q['goles_away'] = m
        fuera.append(q)
    return fuera


def unir(*listas: List[Dict]) -> List[Dict]:
    """Une sin repetir; ante el mismo partido gana el que trae marcador."""
    por: Dict[str, Dict] = {}
    for lista in listas:
        for p in (lista or []):
            if not isinstance(p, dict):
                continue
            k = _llave(p)
            if not k:
                continue
            viejo = por.get(k)
            if viejo is None or (viejo.get('goles_home') is None
                                 and p.get('goles_home') is not None):
                por[k] = p
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
        archivados = archivar_del_pronostico(dia, ruta_pronostico)
        partidos = unir(de_red, previos, archivados)
        # los archivados que aún no tenían marcador, se buscan otra vez
        for _p in partidos:
            if _p.get('archivado_del_pronostico') and _p.get('goles_home') is None:
                _m = _marcador(_p)
                if _m:
                    _p['goles_home'], _p['goles_away'] = _m
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
        return precocinado[:maximo]
    return _de_dia_por_red(dia, maximo)


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
