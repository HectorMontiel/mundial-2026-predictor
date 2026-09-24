# -*- coding: utf-8 -*-
"""
v307 — EL ID DE FOTMOB DE CADA LIGA DEL PROYECTO, VERIFICADO POR SUS EQUIPOS.

El usuario: «¿por qué por ahora sólo las ligas identificadas y no las 60?
Deberían ser todas». Tenía razón: `fotmob_scraper.FOTMOB_LEAGUE_IDS` traía
diez ligas escritas a mano y todo lo que dependía de FotMob (bajas, remates por
jugador, alineaciones) se quedaba en ellas.

CÓMO SE RESUELVE, SIN ADIVINAR
Cada competición tiene un id CONOCIDO (`CONOCIDOS`, sacado de las páginas de
FotMob: 66 de 67 comprobados a mano el 2026-09-23) y ese id se VERIFICA con los
equipos de nuestro histórico antes de aceptarlo. Si una liga no tiene id
conocido o el conocido no casa (FotMob renumera a veces), se buscan candidatas
en la página de búsqueda de FotMob (la que responde: la API está blindada) y se
ELIGE la candidata cuyos equipos coinciden con los de nuestro histórico. La
búsqueda sola no bastaba: tardaba 2-3 minutos por liga y no encontraba Noruega,
Suecia ni Dinamarca («Eliteserien» no devuelve nada en el buscador). El nombre solo no basta:
«Primera División» es Argentina, Uruguay y El Salvador, y «Super League» es
Suiza, Grecia, China e India. Los equipos no mienten: una candidata sólo se
acepta si al menos el 40 % de sus equipos casan con los de la competición.

Salida: `fotmob_ligas.json` = {clave: {'id', 'slug', 'nombre', 'solape'}}.
Las que no se puedan verificar se listan aparte, con el motivo, en vez de
colgarles un id dudoso.

Uso:
    python fotmob_ligas.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FICHERO = 'fotmob_ligas.json'
SOLAPE_MINIMO = 0.40
SOLAPE_COPA = 0.15
PAUSA = 1.0

# id de FotMob de cada competición del proyecto (verificados contra la página
# de la liga el 2026-09-23; el nombre que da FotMob, al lado).
CONOCIDOS = {
    'liga_mx': 230, 'mls': 130, 'brasil': 268, 'argentina': 112,
    'noruega': 59,             # Eliteserien
    'suecia': 67,              # Allsvenskan
    'finlandia': 51, 'rumania': 189,
    'irlanda': 126,            # Premier Division IRL
    'turquia': 71,             # Super Lig
    'dinamarca': 46,           # Superligaen
    'china': 120, 'polonia': 196, 'aut_bundesliga': 38,
    'rus_premier': 63, 'gre_super_league': 135, 'suiza': 69,
    'premier': 47, 'laliga': 87, 'serie_a': 55, 'bundesliga': 54,
    'ligue_1': 53, 'eredivisie': 57, 'primeira': 61, 'champions': 42,
    'europa_league': 73, 'conference_league': 10216, 'leagues_cup': 10043,
    'eng_championship': 48, 'eng_league_one': 108, 'eng_league_two': 109,
    'eng_national': 117, 'sco_premiership': 64, 'sco_championship': 123,
    'esp_hypermotion': 140, 'ita_serie_b': 86, 'fra_ligue2': 110,
    'ger_bundesliga2': 146, 'bel_pro_league': 40, 'jpn_j1': 223,
    'arg_primera_nacional': 8965, 'col_primera_a': 274,
    'usl_championship': 8972, 'ned_eerste': 111, 'bra_serie_b': 8814,
    'per_liga1': 131, 'uru_primera': 161, 'ecu_liga_pro': 246,
    'slv_primera': 335, 'bol_division': 144, 'par_division': 199,
    'crc_fpd': 121, 'mex_expansion': 8976, 'chi_primera': 273,
    'rsa_premier': 537, 'ven_primera': 339, 'aus_aleague': 113,
    'libertadores': 45, 'sudamericana': 299, 'eng_fa_cup': 132,
    'ind_isl': 9478, 'esp_copa_rey': 138, 'afc_champions': 525,
    'bra_copa': 9067, 'eng_carabao': 133, 'ksa_pro': 536, 'isr_premier': 127,
}

# Palabras para buscar cuando el nombre del proyecto no es el de FotMob.
TERMINOS_EXTRA = {
    'china': ['super league china'], 'rsa_premier': ['premiership'],
    'ven_primera': ['liga futve'], 'crc_fpd': ['primera division costa'],
    'slv_primera': ['primera division'], 'uru_primera': ['primera division'],
    'argentina': ['liga profesional'], 'par_division': ['primera division'],
    'bol_division': ['division profesional'], 'rus_premier': ['premier league'],
    'suiza': ['super league'], 'gre_super_league': ['super league'],
    'ind_isl': ['super league'], 'eng_carabao': ['efl cup'],
    'esp_copa_rey': ['copa del rey'], 'bra_copa': ['copa do brasil'],
    'afc_champions': ['afc champions league'], 'leagues_cup': ['leagues cup'],
    'eng_national': ['national league'], 'ned_eerste': ['eerste divisie'],
    'mex_expansion': ['liga de expansion'], 'ecu_liga_pro': ['liga pro'],
    'col_primera_a': ['primera a'], 'chi_primera': ['primera division chile'],
    'per_liga1': ['liga 1'], 'jpn_j1': ['j. league', 'j1 league'],
    'aus_aleague': ['a-league'], 'isr_premier': ['ligat', 'premier league'],
    'ksa_pro': ['saudi pro league'], 'irlanda': ['premier division'],
}


def _norm(t) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t or '').lower())
    return re.sub(r'[^a-z0-9 ]', '', t.encode('ascii', 'ignore').decode())


def candidatas(termino: str) -> Dict[str, str]:
    import fotmob_scraper as fm
    from urllib.parse import quote
    d = fm._next_data('https://www.fotmob.com/search?term=%s' % quote(termino))
    s = json.dumps(d or {}, ensure_ascii=False)
    fuera = {}
    for m in re.finditer(r'\{"\d+": "[^"]+"(?:, "\d+": "[^"]+")+\}', s):
        try:
            fuera.update(json.loads(m.group(0)))
        except Exception:
            continue
    t = set(_norm(termino).split())
    return {i: n for i, n in fuera.items() if t & set(_norm(n).split())}


def equipos_fotmob(lid: str) -> List[str]:
    import fotmob_scraper as fm
    d = fm._next_data('https://www.fotmob.com/leagues/%s/overview/x' % lid)
    pp = (d or {}).get('props', {}).get('pageProps', {})
    ms = ((pp.get('fixtures') or {}).get('allMatches')
          or (pp.get('overview') or {}).get('leagueOverviewMatches') or [])
    eq = set()
    for m in ms:
        for lado in ('home', 'away'):
            n = (m.get(lado) or {}).get('name')
            if n:
                eq.add(n)
    return sorted(eq)


def nombre_fotmob(lid) -> str:
    import fotmob_scraper as fm
    d = fm._next_data('https://www.fotmob.com/leagues/%s/overview/x' % lid)
    pp = (d or {}).get('props', {}).get('pageProps', {})
    return str((pp.get('details') or {}).get('name') or '')


def equipos_propios(clave: str) -> List[str]:
    import pandas as pd
    r = 'historico_%s.csv' % clave
    if not os.path.exists(r):
        return []
    d = pd.read_csv(r, usecols=['date', 'home_team', 'away_team'],
                    low_memory=False)
    d = d[d['date'].astype(str) >= '2024-01-01']
    return sorted(set(d['home_team']) | set(d['away_team']))


def solape(fm_eq: List[str], nuestros: List[str]) -> float:
    if not fm_eq or not nuestros:
        return 0.0
    import name_mapper as nm
    ok = 0
    for e in fm_eq:
        if nm.mapear(e, nuestros, contexto='fotmob_ligas'):
            ok += 1
    return ok / len(fm_eq)


def resolver(clave: str, nombre: str) -> Dict:
    nuestros = equipos_propios(clave)
    if not nuestros:
        return {'error': 'sin histórico reciente'}
    vistos, mejor = set(), None
    # 1) el id conocido, verificado por sus equipos
    lid = CONOCIDOS.get(clave)
    if lid:
        vistos.add(str(lid))
        try:
            fm_eq = equipos_fotmob(lid)
            s = solape(fm_eq, nuestros)
            mejor = {'id': int(lid), 'nombre': nombre_fotmob(lid) or nombre,
                     'solape': round(s, 3), 'equipos': len(fm_eq),
                     'origen': 'conocido'}
            # Las copas continentales cambian de participantes cada temporada:
            # la Conference 2026/27 (id 10216, el bueno) sólo comparte el 22 %
            # de sus equipos con nuestro histórico, que acaba en mayo de 2026,
            # y el buscador proponía en su lugar la «Champions League
            # Qualification» (40 %). Con el id conocido basta que el NOMBRE de
            # FotMob esté contenido en el nuestro y un solape mínimo del 15 %.
            nombre_ok = set(_norm(mejor['nombre']).split()) <= set(
                _norm(nombre).split())
            if s >= SOLAPE_MINIMO or (nombre_ok and s >= SOLAPE_COPA):
                mejor['slug'] = _slug(mejor['nombre'])
                return mejor
        except Exception as e:
            logger.debug('[fotmob_ligas] %s: %s', clave, e)
    # 2) si no casa, el buscador de FotMob
    for termino in [nombre] + TERMINOS_EXTRA.get(clave, []):
        try:
            cand = candidatas(termino)
        except Exception as e:
            logger.debug('[fotmob_ligas] %s: %s', termino, e)
            continue
        time.sleep(PAUSA)
        for lid, n in cand.items():
            if lid in vistos:
                continue
            vistos.add(lid)
            try:
                fm_eq = equipos_fotmob(lid)
            except Exception:
                continue
            time.sleep(PAUSA)
            s = solape(fm_eq, nuestros)
            if mejor is None or s > mejor['solape']:
                mejor = {'id': int(lid), 'nombre': n, 'solape': round(s, 3),
                         'equipos': len(fm_eq), 'origen': 'buscador'}
            if s >= 0.8:
                break
        if mejor and mejor['solape'] >= 0.8:
            break
    if not mejor or mejor['solape'] < SOLAPE_MINIMO:
        return {'error': 'ninguna candidata casa sus equipos',
                'mejor': mejor}
    mejor['slug'] = _slug(mejor['nombre'])
    return mejor


def _slug(nombre) -> str:
    return re.sub(r'[^a-z0-9]+', '-', _norm(nombre)).strip('-') or 'x'


def cargar() -> Dict:
    try:
        with open(FICHERO, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def ids() -> Dict[str, tuple]:
    """{clave: (id, slug)} de todo lo verificado, más las fijas de siempre."""
    fuera = {}
    try:
        import fotmob_scraper as fm
        fuera.update(fm.FOTMOB_LEAGUE_IDS)
    except Exception:
        pass
    for k, v in (cargar().get('ligas') or {}).items():
        if isinstance(v, dict) and v.get('id'):
            fuera[k] = (int(v['id']), v.get('slug') or 'x')
    return fuera


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from config import LEAGUES
    previo = cargar()
    doc = {'ligas': dict(previo.get('ligas') or {}), 'sin_resolver': {}}
    excluir = {'mlb', 'nba', 'nfl', 'kbo', 'itf_vivo', 'tenis_espn'}
    claves = [c for c in sys.argv[1:] if c in LEAGUES] or [
        k for k in LEAGUES if k not in excluir
        and os.path.exists('historico_%s.csv' % k)]
    pendientes = [k for k in claves
                  if k not in doc['ligas'] or '--forzar' in sys.argv]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        hechos = list(ex.map(
            lambda k: (k, resolver(k, LEAGUES[k].get('nombre') or k)),
            pendientes))
    for k, r in hechos:
        doc['sin_resolver'].pop(k, None)
        if r.get('error'):
            doc['sin_resolver'][k] = r
            print('%-22s SIN RESOLVER: %s %s' % (k, r['error'],
                                                  r.get('mejor') or ''))
        else:
            doc['ligas'][k] = r
            print('%-22s %6d %-32s solape %.0f%%' % (k, r['id'], r['nombre'],
                                                     100 * r['solape']))
        with open(FICHERO, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    print('resueltas %d · sin resolver %d' % (len(doc['ligas']),
                                              len(doc['sin_resolver'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
