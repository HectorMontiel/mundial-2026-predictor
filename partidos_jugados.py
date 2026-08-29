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
    try:
        import fixtures_espn
    except Exception as e:
        logger.debug('[jugados] sin fixtures_espn: %s', e)
        return []
    try:
        crudos = fixtures_espn.jugados_del_dia(
            fixtures_espn.claves_de_futbol(), dia)
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
