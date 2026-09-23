# -*- coding: utf-8 -*-
"""
v303 — HISTÓRICO DE RESULTADOS DESDE FOTMOB, PARA LO QUE NADIE MÁS CUBRE.

DE DÓNDE SALE
El usuario puso de ejemplo la Liga MX Femenil —«los equipos top de tabla
normalmente golean y los de media y baja tabla no anotan muchos goles»— y el
proyecto no tenía ni un partido suyo: `config_ligas_espn.SIN_VOLUMEN` la
apuntaba como «sin cobertura en ESPN» y ahí se quedó. Y la regla del usuario
es clara: «en este proyecto no estará permitido no tener datos».

FotMob sí la tiene. Medido el 2026-09-23: es su liga 9906, con seis
temporadas (2021/2022 a 2026/2027) y ~335 partidos por temporada, y la página
de cada temporada sale con HTTP 200 a una petición normal (la API interna
está blindada, las páginas no; ver `fotmob_scraper`). Trae el marcador de
cada partido. Estadísticas de partido (córners, tarjetas) NO publica para esta
liga: se comprobó partido a partido y el bloque viene vacío. Así que de aquí
salen goles, que es justo lo que pedía el ejemplo, y nada inventado.

QUÉ ESCRIBE
`historico_<clave>.csv` con las columnas de los históricos de liga (`date`,
`home_team`, `away_team`, `home_goals`, `away_goals`, `MATCH_ID`...), para
que `patrones_liga`, `razon_apuesta` y `motor_goles` lo lean igual que los
demás. Los nombres son los de FotMob sin el «(W)».

Uso:
    python historico_fotmob.py mex_femenil
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

# clave del proyecto -> ([(id de FotMob, slug), ...], nombre visible)
#
# Una competición puede venir de VARIAS páginas: la Champions femenil tiene
# la fase principal (9375) y la previa (10612) por separado, y para medir la
# fuerza de un equipo hacen falta las dos.
LIGAS: Dict[str, tuple] = {
    'mex_femenil': ([(9906, 'liga-mx-femenil')], 'Liga MX Femenil'),
    # v303 — pedida por el usuario «de una vez que estás con femeniles».
    'champions_femenil': ([(9375, 'womens-champions-league'),
                           (10612, 'womens-champions-league-qualification')],
                          "Champions League femenina"),
    # Las cinco ligas grandes: tienen sus propios pronósticos si su motor
    # valida, y SIRVEN DE APOYO a la Champions (ver `APOYO`).
    'fem_inglaterra': ([(9227, 'wsl')], 'WSL (Inglaterra, femenil)'),
    'fem_espana': ([(9907, 'liga-f')], 'Liga F (España, femenil)'),
    'fem_alemania': ([(9676, 'frauen-bundesliga')], 'Frauen-Bundesliga'),
    'fem_francia': ([(9677, 'premiere-ligue-feminine')],
                    'Première Ligue (Francia, femenil)'),
    'fem_italia': ([(10178, 'serie-a-femminile')], 'Serie A Femminile'),
}

# v303 — LA FUERZA DE UN EQUIPO DE CHAMPIONS SALE TAMBIÉN DE SU LIGA.
#
# Con sólo los partidos de la Champions, cada equipo juega seis u ocho al año
# y sus fuerzas se quedan en la media: la primera prueba daba a Chelsea un 49 %
# contra el Austria de Viena y a Servette un 44 % contra Lyon. Midiendo con su
# liga doméstica —y con la Champions cosiendo las ligas entre sí— el motor
# sabe quién es quién.
APOYO: Dict[str, List[str]] = {
    'champions_femenil': ['fem_inglaterra', 'fem_espana', 'fem_alemania',
                          'fem_francia', 'fem_italia'],
}
PAUSA = 1.5


def _limpia(nombre: str) -> str:
    """Sin la marca femenina: FotMob escribe «Chelsea (W)» y a veces
    «Austria Wien W», y los dos son el mismo equipo en todas sus ligas."""
    n = re.sub(r'\s*\((W|F)\)\s*$', '', str(nombre or '')).strip()
    return re.sub(r'\s+W$', '', n).strip()


def _temporada(lid: int, slug: str, temporada: str = '') -> List[Dict]:
    import fotmob_scraper as fm
    url = 'https://www.fotmob.com/leagues/%d/overview/%s' % (lid, slug)
    if temporada:
        url += '?season=%s' % temporada
    d = fm._next_data(url)
    if not d:
        return []
    pp = d.get('props', {}).get('pageProps', {})
    return ((pp.get('fixtures') or {}).get('allMatches')
            or (pp.get('overview') or {}).get('leagueOverviewMatches') or [])


def temporadas(lid: int, slug: str) -> List[str]:
    import fotmob_scraper as fm
    d = fm._next_data('https://www.fotmob.com/leagues/%d/overview/%s'
                      % (lid, slug))
    pp = (d or {}).get('props', {}).get('pageProps', {})
    return list(pp.get('allAvailableSeasons') or [])


def _todas(clave: str, max_temporadas: int):
    paginas, nombre = LIGAS[clave]
    for lid, slug in paginas:
        for i, t in enumerate(temporadas(lid, slug)[:max_temporadas]):
            yield from _temporada(lid, slug, t if i else '')
            time.sleep(PAUSA)


def descargar(clave: str, max_temporadas: int = 6) -> pd.DataFrame:
    _, nombre = LIGAS[clave]
    filas = []
    for m in _todas(clave, max_temporadas):
        st = m.get('status') or {}
        if not st.get('finished') or st.get('cancelled'):
            continue
        h, a = m.get('home') or {}, m.get('away') or {}
        # el marcador viene en cada equipo en la portada, y en
        # `status.scoreStr` («0 - 5») en la lista de la temporada
        try:
            gh, ga = float(h.get('score')), float(a.get('score'))
        except (TypeError, ValueError):
            mm = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*$',
                          str(st.get('scoreStr') or ''))
            if not mm:
                continue
            gh, ga = float(mm.group(1)), float(mm.group(2))
        f = pd.to_datetime(st.get('utcTime'), errors='coerce', utc=True)
        if pd.isna(f):
            continue
        hn, an = _limpia(h.get('name')), _limpia(a.get('name'))
        filas.append({
            'date': f.tz_convert(None).strftime('%Y-%m-%d'),
            'home_team': hn, 'away_team': an,
            'home_goals': gh, 'away_goals': ga,
            'tournament': nombre, 'fotmob_id': str(m.get('id')),
            'MATCH_ID': '%s_%s_%s' % (f.strftime('%Y%m%d'),
                                      hn.replace(' ', '-'),
                                      an.replace(' ', '-'))})
    d = pd.DataFrame(filas)
    if d.empty:
        return d
    d = d.drop_duplicates(subset=['fotmob_id']).sort_values('date')
    return d.reset_index(drop=True)


def proximos(clave: str) -> List[Dict]:
    """Los partidos por jugar de la temporada vigente, con su hora UTC."""
    paginas, nombre = LIGAS[clave]
    fuera = []
    for m in [x for lid, slug in paginas for x in _temporada(lid, slug)]:
        st = m.get('status') or {}
        if st.get('finished') or st.get('started') or st.get('cancelled'):
            continue
        f = pd.to_datetime(st.get('utcTime'), errors='coerce', utc=True)
        if pd.isna(f):
            continue
        fuera.append({'home': _limpia((m.get('home') or {}).get('name')),
                      'away': _limpia((m.get('away') or {}).get('name')),
                      'inicio': f.tz_convert(None).strftime('%Y-%m-%d %H:%M:%S'),
                      'fecha': f.tz_convert(None).strftime('%Y-%m-%d'),
                      'torneo': nombre, 'fotmob_id': str(m.get('id'))})
    return fuera


def actualizar(clave: str) -> Dict:
    d = descargar(clave)
    if d.empty:
        return {'clave': clave, 'partidos': 0}
    ruta = 'historico_%s.csv' % clave
    tmp = ruta + '.nuevo'
    d.to_csv(tmp, index=False)
    os.replace(tmp, ruta)
    return {'clave': clave, 'partidos': int(len(d)),
            'desde': d['date'].min(), 'hasta': d['date'].max()}


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    claves = [c for c in sys.argv[1:] if c in LIGAS] or list(LIGAS)
    for c in claves:
        print(actualizar(c))
    return 0


if __name__ == '__main__':
    sys.exit(main())
