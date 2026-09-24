# -*- coding: utf-8 -*-
"""
v307 — REMATES POR EQUIPO DE LAS LIGAS QUE FOTMOB NO CUBRE, DESDE FLASHSCORE.

POR QUÉ HACE FALTA
(Lo mismo pasa en otras siete ligas, listadas en `TORNEOS`.)
`remates_fotmob` saca los remates de la ficha de cada partido en FotMob, pero
en la Liga MX Femenil FotMob sólo publica el marcador: la ficha no trae
`stats`, ni `playerStats`, ni mapa de disparos, ni alineación (comprobado el
2026-09-23 con Toluca–Tigres, 2-7). Se buscaron otras fuentes:
    · ESPN (`mex.w.1`): la liga existe pero el marcador sale sin partidos;
    · SofaScore: 403 a cualquier petición que no sea de su app;
    · la web oficial (ligafemenil.mx): goles, minutos y tarjetas por
      jugadora, pero ningún disparo;
    · Flashscore: SÍ. Su feed de estadísticas del partido (`df_st_1_<id>`)
      trae remates totales, a puerta, xG y córners de cada equipo
      (Santos–Cruz Azul: 14 a 30, 4 a 8 a puerta).
Lo que Flashscore NO trae en esta liga son los remates POR JUGADORA: su
pestaña de estadísticas de jugador sólo existe en las ligas con datos de
Opta, y aquí el feed (`df_ps_1_<id>`) llega vacío. Por eso de esta liga se
guarda el equipo y ninguna jugadora; «quién remata» sigue sin salir en la
Liga MX Femenil, y la tarjeta no inventa nada.

QUÉ ESCRIBE
Filas en `remates_fotmob_equipos.csv` (el mismo fichero y la misma forma que
FotMob, con `match_id` = «fs:<id>» y `por_jugador` = 0), así que
`remates_fotmob.lambdas_partido` y `rendimiento_equipos` las leen sin más.
Los nombres se traducen a los de nuestro histórico («Club Leon W» →
«Club León»).

Uso:
    python remates_flashscore.py
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# clave del proyecto -> ruta de la competición en Flashscore. Son las que
# FotMob deja sin estadísticas: se probó un partido reciente de cada una de
# las 31 ligas cuyo nivel de remates salía ESTIMADO, y FotMob trajo equipo y
# jugadores en 23; en estas 8 la ficha llega vacía (2026-09-23). En todas
# Flashscore da remates y a puerta por equipo; por jugador, en ninguna.
TORNEOS = {
    'mex_femenil': 'football/mexico/liga-mx-women',
    'eng_national': 'football/england/national-league',
    'sco_championship': 'football/scotland/championship',
    'arg_primera_nacional': 'football/argentina/primera-nacional',
    'uru_primera': 'football/uruguay/liga-auf-uruguaya',
    'slv_primera': 'football/el-salvador/primera-division',
    'crc_fpd': 'football/costa-rica/primera-division',
    'mex_expansion': 'football/mexico/liga-de-expansion-mx',
}
# Los nombres de Flashscore que el emparejador no casa solo (65 partidos
# sin guardar en la primera pasada, 2026-09-23), a mano contra el histórico.
ALIAS = {
    'CA Estudiantes': 'Estudiantes (Buenos Aires)',
    'CA Mitre': 'Mitre (Santiago del Estero)',
    'Gimnasia Jujuy': 'Gimnasia y Esgrima (Jujuy)',
    'FAS': 'CD FAS', 'Platense Municipal': 'C.D. Platense',
    'Atl. Morelia': 'Club Atlético Morelia',
    'Zacatecas Mineros': 'Mineros de Zacatecas',
}
WEB = 'https://www.flashscore.com/%s/results/'
FEED = 'https://global.flashscore.ninja/2/x/feed/df_st_1_%s'
# La cabecera que manda la propia web a su feed. Es pública: va escrita en
# el JavaScript de la página, igual para todos los visitantes.
CABECERAS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
             'x-fsign': 'SW9D1eZo',
             'Referer': 'https://www.flashscore.com/'}
PAUSA = 1.0
DIAS = 150


def _pares(texto: str) -> List[Dict[str, str]]:
    """El formato de Flashscore: registros separados por «~» y campos
    «CLAVE÷valor» separados por «¬»."""
    fuera = []
    for reg in texto.split('~'):
        d = {}
        for campo in reg.split('¬'):
            if '÷' in campo:
                k, v = campo.split('÷', 1)
                d.setdefault(k, v)
        if d:
            fuera.append(d)
    return fuera


def partidos(ruta: str) -> List[Dict]:
    """Los partidos TERMINADOS de la página de resultados de la temporada."""
    r = requests.get(WEB % ruta, headers=CABECERAS, timeout=30)
    r.raise_for_status()
    fuera = []
    for trozo in r.text.split('~AA÷')[1:]:
        mid = trozo[:8]
        d = dict(c.split('÷', 1) for c in trozo.split('¬') if '÷' in c)
        if d.get('AB') != '3':                      # 3 = terminado
            continue
        try:
            fecha = dt.datetime.fromtimestamp(int(d['AD']), dt.timezone.utc)
        except Exception:
            continue
        fuera.append({'id': mid, 'fecha': fecha.strftime('%Y-%m-%d'),
                      'home': d.get('AE'), 'away': d.get('AF'),
                      'goles_home': d.get('AG'), 'goles_away': d.get('AH')})
    return fuera


def _num(v) -> Optional[float]:
    try:
        return float(str(v).split(' ')[0].rstrip('%'))
    except Exception:
        return None


def estadisticas(mid: str) -> Dict[str, tuple]:
    """{nombre: (local, visitante)} del partido entero (no de cada parte)."""
    r = requests.get(FEED % mid, headers=CABECERAS, timeout=30)
    # un error de red LANZA: quien llama lo deja para otra pasada en vez de
    # apuntarlo como partido sin datos para siempre
    r.raise_for_status()
    fuera, dentro = {}, False
    for d in _pares(r.text):
        if 'SE' in d:
            # «Match» es el partido entero; lo que sigue son las partes
            dentro = d['SE'] == 'Match'
            continue
        if dentro and 'SG' in d and d['SG'] not in fuera:
            fuera[d['SG']] = (_num(d.get('SH')), _num(d.get('SI')))
    return fuera


def _catalogo(clave: str) -> List[str]:
    import pandas as pd
    try:
        d = pd.read_csv('historico_%s.csv' % clave,
                        usecols=['date', 'home_team', 'away_team'])
    except Exception:
        return []
    d = d[d['date'].astype(str) >= '2025-01-01']
    return sorted(set(d['home_team']) | set(d['away_team']))


def _nombre(fs: str, catalogo: List[str]) -> Optional[str]:
    limpio = str(fs or '').strip()
    if limpio.endswith(' W'):
        limpio = limpio[:-2].strip()
    limpio = ALIAS.get(limpio, limpio)
    if limpio in catalogo:
        return limpio
    try:
        import name_mapper as nm
        return nm.mapear(limpio, catalogo, contexto='remates_flashscore')
    except Exception:
        return None


def capturar(dias: int = DIAS) -> Dict:
    import remates_fotmob as rf
    ya = rf._ya_guardados()
    desde = (dt.datetime.now(dt.timezone.utc)
             - dt.timedelta(days=dias)).strftime('%Y-%m-%d')
    cuenta = {'guardados': 0, 'sin_datos': 0, 'sin_nombre': 0}
    for clave, ruta in TORNEOS.items():
        catalogo = _catalogo(clave)
        try:
            lista = partidos(ruta)
        except Exception as e:
            logger.warning('[remates_flashscore] %s: %s', clave, e)
            continue
        for p in lista:
            llave = 'fs:' + p['id']
            if llave in ya or p['fecha'] < desde:
                continue
            h, a = _nombre(p['home'], catalogo), _nombre(p['away'], catalogo)
            if not h or not a:
                cuenta['sin_nombre'] += 1
                continue
            try:
                st = estadisticas(p['id'])
            except Exception as e:
                logger.debug('[remates_flashscore] %s: %s', p['id'], e)
                continue                    # sin respuesta: otra pasada
            time.sleep(PAUSA)
            tot = st.get('Total shots')
            if not tot or tot[0] is None:
                cuenta['sin_datos'] += 1
                with open(rf.VACIOS, 'a', encoding='utf-8') as f:
                    f.write(llave + '\n')
                continue
            filas = []
            for i, (eq, riv) in enumerate(((h, a), (a, h))):
                def de(k):
                    v = (st.get(k) or (None, None))[i]
                    return v
                g = p['goles_home'] if i == 0 else p['goles_away']
                filas.append({'match_id': llave, 'fecha': p['fecha'],
                              'liga': clave, 'equipo': eq, 'rival': riv,
                              'local': int(i == 0), 'tiros': int(tot[i]),
                              'a_puerta': (None if de('Shots on target')
                                           is None
                                           else int(de('Shots on target'))),
                              'xg': de('Expected goals (xG)'),
                              'goles': int(g) if str(g).isdigit() else None,
                              'corners': (None if de('Corner kicks') is None
                                          else int(de('Corner kicks'))),
                              'por_jugador': 0})
            rf._anexar(rf.EQUIPOS, filas, rf.COL_E)
            cuenta['guardados'] += 1
    rf.olvidar()
    logger.info('[remates_flashscore] %s', cuenta)
    return cuenta


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print(capturar())
    return 0


if __name__ == '__main__':
    sys.exit(main())
