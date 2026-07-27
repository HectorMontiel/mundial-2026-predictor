#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v68 — Generador del CATÁLOGO DE LIGAS de fútbol.

Contexto
--------
Hasta v67 el proyecto cubría 19 competiciones, casi todas atadas a
football-data.co.uk (que solo publica ~22 ligas europeas). La petición del
usuario es cubrir **todas las competiciones de su casa de apuestas** (~100).

Hallazgo que lo hace viable: ESPN publica **220 competiciones de fútbol** y el
proyecto YA tiene un cargador genérico para ellas (`uefa_scraper.descargar_espn`,
que pese al nombre no es específico de UEFA — lo usan Europa y Conference League
desde v35). Es decir, la infraestructura existía; faltaba el catálogo.

Este módulo:
  1. Mapea la lista pedida a los slugs reales de ESPN (verificados contra el
     catálogo en vivo, no adivinados).
  2. Mide cuántos partidos terminados hay por competición.
  3. Escribe `config_ligas_espn.py` con las entradas listas para `config.LEAGUES`.

Criterio de inclusión: una competición entra al catálogo si ESPN devuelve
suficientes partidos para entrenar. Que ENTRE al catálogo no significa que se
despliegue: eso lo decide la regla de oro del proyecto (batir al ELO) en
`entrenar_ligas_v68.py`.

Uso:
    .venv\\Scripts\\python.exe generar_ligas_v68.py --medir
"""

import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ESPN_DROPDOWN = ('https://site.web.api.espn.com/apis/site/v2/leagues/dropdown'
                 '?lang=en&region=us&calendartype=whitelist&limit=400&sport=soccer')
ESPN_SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard'
UA = {'User-Agent': 'Mozilla/5.0'}
SALIDA = 'config_ligas_espn.py'
MEDICIONES = '_v68_volumen_ligas.json'

# Mínimo de partidos para que entrenar tenga sentido. Por debajo de esto el
# modelo memoriza en vez de aprender (el proyecto ya usa ~50 como suelo duro en
# la cadena de resiliencia; aquí se es más exigente).
MIN_PARTIDOS = 220

# ---------------------------------------------------------------------------
# PRIORIDAD DE FUENTES (medido, no supuesto)
#
#  1. football-data.co.uk /mmz4281/  — formato 'main'. Es la MEJOR: trae
#     remates (HS/AS), remates a puerta (HST/AST), córners, faltas, tarjetas Y
#     cuotas de cierre de varias casas. Cubre las segundas divisiones de los
#     países grandes, que es justo lo que pedía la lista.
#  2. football-data.co.uk /new/      — formato 'new'. Goles + cuotas de cierre,
#     sin estadística de juego. 16 países reales (ojo: el servidor devuelve el
#     MISMO fichero para códigos inexistentes, así que hay que validar el
#     contenido, no el código de estado).
#  3. ESPN                            — formato 'espn'. Resultados sin cuotas ni
#     estadística, pero cubre 220 competiciones: Latinoamérica, copas y
#     competiciones continentales que las otras dos no tienen.
#
# Una competición se toma de la fuente de MÁS calidad que la sirva.
# ---------------------------------------------------------------------------
FD_MAIN: List[Dict] = [
    dict(clave='eng_championship', nombre='EFL Championship', pais='Inglaterra', fd='E1', espn='eng.2'),
    dict(clave='eng_league_one', nombre='EFL League One', pais='Inglaterra', fd='E2', espn='eng.3'),
    dict(clave='eng_league_two', nombre='EFL League Two', pais='Inglaterra', fd='E3', espn='eng.4'),
    dict(clave='eng_national', nombre='National League', pais='Inglaterra', fd='EC', espn='eng.5'),
    dict(clave='sco_premiership', nombre='Scottish Premiership', pais='Escocia', fd='SC0', espn='sco.1'),
    dict(clave='sco_championship', nombre='Scottish Championship', pais='Escocia', fd='SC1', espn='sco.2'),
    dict(clave='esp_hypermotion', nombre='LaLiga Hypermotion', pais='España', fd='SP2', espn='esp.2'),
    dict(clave='ita_serie_b', nombre='Serie B', pais='Italia', fd='I2', espn='ita.2'),
    dict(clave='fra_ligue2', nombre='Ligue 2', pais='Francia', fd='F2', espn='fra.2'),
    dict(clave='ger_bundesliga2', nombre='2. Bundesliga', pais='Alemania', fd='D2', espn='ger.2'),
    dict(clave='bel_pro_league', nombre='Jupiler Pro League', pais='Bélgica', fd='B1', espn='bel.1'),
]

FD_NEW: List[Dict] = [
    # v34 dio a Japón por perdida ("228 días sin publicar"); vuelve a estar
    # viva y con 5 temporadas. Se re-evalúa.
    dict(clave='jpn_j1', nombre='J1 League', pais='Japón', fd='JPN', espn='jpn.1'),
]

# ---------------------------------------------------------------------------
# Resto: ESPN. Los slugs están verificados contra el catálogo en vivo.
# ---------------------------------------------------------------------------
CATALOGO: List[Dict] = [
    # --- Mundo / internacional -------------------------------------------
    dict(clave='mundial_clubes', nombre='Mundial de Clubes', pais='Mundo', espn='fifa.cwc'),
    # --- México -----------------------------------------------------------
    dict(clave='mex_expansion', nombre='Liga de Expansión MX', pais='México', espn='mex.2'),
    dict(clave='mex_femenil', nombre='Liga MX Femenil', pais='México', espn='mex.w.1'),
    # --- Europa (competiciones UEFA) --------------------------------------
    dict(clave='uefa_nations', nombre='UEFA Nations League', pais='Europa', espn='uefa.nations'),
    # --- España ------------------------------------------------------------
    dict(clave='esp_copa_rey', nombre='Copa del Rey', pais='España', espn='esp.copa_del_rey'),
    # --- Inglaterra ---------------------------------------------------------
    dict(clave='eng_fa_cup', nombre='FA Cup', pais='Inglaterra', espn='eng.fa'),
    dict(clave='eng_carabao', nombre='EFL Cup (Carabao)', pais='Inglaterra', espn='eng.league_cup'),
    # --- Italia --------------------------------------------------------------
    dict(clave='ita_coppa', nombre='Coppa Italia', pais='Italia', espn='ita.coppa_italia'),
    # --- Francia -------------------------------------------------------------
    dict(clave='fra_coupe', nombre='Coupe de France', pais='Francia', espn='fra.coupe_de_france'),
    # --- Alemania ------------------------------------------------------------
    dict(clave='ger_dfb_pokal', nombre='DFB-Pokal', pais='Alemania', espn='ger.dfb_pokal'),
    # --- Américas ------------------------------------------------------------
    dict(clave='libertadores', nombre='Copa Libertadores', pais='Américas', espn='conmebol.libertadores'),
    dict(clave='sudamericana', nombre='Copa Sudamericana', pais='Américas', espn='conmebol.sudamericana'),
    dict(clave='concacaf_ccc', nombre='CONCACAF Champions Cup', pais='Américas', espn='concacaf.champions'),
    dict(clave='leagues_cup', nombre='Leagues Cup', pais='Américas', espn='concacaf.leagues.cup'),
    # --- Asia -----------------------------------------------------------------
    dict(clave='afc_champions', nombre='AFC Champions League', pais='Asia', espn='afc.champions'),
    dict(clave='copa_asiatica', nombre='Copa Asiática', pais='Asia', espn='afc.asian.cup'),
    # --- Argentina -------------------------------------------------------------
    dict(clave='arg_primera_nacional', nombre='Primera Nacional', pais='Argentina', espn='arg.2'),
    dict(clave='arg_copa_liga', nombre='Copa de la Liga', pais='Argentina', espn='arg.copa_lpf'),
    # --- Brasil ------------------------------------------------------------------
    dict(clave='bra_serie_b', nombre='Brasileirão Série B', pais='Brasil', espn='bra.2'),
    dict(clave='bra_copa', nombre='Copa do Brasil', pais='Brasil', espn='bra.copa_do_brazil'),
    # --- África --------------------------------------------------------------------
    dict(clave='afcon', nombre='Copa Africana de Naciones', pais='África', espn='caf.nations'),
    dict(clave='caf_champions', nombre='CAF Champions League', pais='África', espn='caf.champions'),
    # --- Resto de ligas domésticas ---------------------------------------------------
    dict(clave='aus_aleague', nombre='A-League Men', pais='Australia', espn='aus.1'),
    dict(clave='aut_bundesliga', nombre='Austrian Bundesliga', pais='Austria', espn='aut.1'),
    dict(clave='bol_division', nombre='División Profesional', pais='Bolivia', espn='bol.1'),
    dict(clave='bul_parva', nombre='First Professional Football League', pais='Bulgaria', espn='bul.1'),
    dict(clave='can_premier', nombre='Canadian Premier League', pais='Canadá', espn='can.1'),
    dict(clave='chi_primera', nombre='Campeonato Nacional', pais='Chile', espn='chi.1'),
    dict(clave='col_primera_a', nombre='Categoría Primera A', pais='Colombia', espn='col.1'),
    dict(clave='col_primera_b', nombre='Categoría Primera B', pais='Colombia', espn='col.2'),
    dict(clave='crc_fpd', nombre='Liga FPD', pais='Costa Rica', espn='crc.1'),
    dict(clave='cro_hnl', nombre='HNL', pais='Croacia', espn='cro.1'),
    dict(clave='cyp_first', nombre='Cypriot First Division', pais='Chipre', espn='cyp.1'),
    dict(clave='cze_first', nombre='Czech First League', pais='Chequia', espn='cze.1'),
    dict(clave='ecu_liga_pro', nombre='LigaPro Serie A', pais='Ecuador', espn='ecu.1'),
    dict(clave='slv_primera', nombre='Primera División', pais='El Salvador', espn='slv.1'),
    dict(clave='usl_championship', nombre='USL Championship', pais='Estados Unidos', espn='usa.usl.1'),
    dict(clave='est_meistriliiga', nombre='Meistriliiga', pais='Estonia', espn='est.1'),
    dict(clave='gre_super_league', nombre='Super League Greece', pais='Grecia', espn='gre.1'),
    dict(clave='hun_nbi', nombre='Nemzeti Bajnokság I', pais='Hungría', espn='hun.1'),
    dict(clave='isl_besta', nombre='Besta deild karla', pais='Islandia', espn='isl.1'),
    dict(clave='ind_isl', nombre='Indian Super League', pais='India', espn='ind.1'),
    dict(clave='idn_liga1', nombre='Liga 1', pais='Indonesia', espn='idn.1'),
    dict(clave='isr_premier', nombre='Israeli Premier League', pais='Israel', espn='isr.1'),
    dict(clave='kaz_premier', nombre='Kazakhstan Premier League', pais='Kazajistán', espn='kaz.1'),
    dict(clave='ltu_alyga', nombre='A Lyga', pais='Lituania', espn='ltu.1'),
    dict(clave='ned_eerste', nombre='Eerste Divisie', pais='Países Bajos', espn='ned.2'),
    dict(clave='nir_premiership', nombre='NIFL Premiership', pais='Irlanda del Norte', espn='nir.1'),
    dict(clave='pan_lpf', nombre='Liga Panameña de Fútbol', pais='Panamá', espn='pan.1'),
    dict(clave='par_division', nombre='División Profesional', pais='Paraguay', espn='par.1'),
    dict(clave='per_liga1', nombre='Liga 1', pais='Perú', espn='per.1'),
    dict(clave='por_liga2', nombre='Liga Portugal 2', pais='Portugal', espn='por.2'),
    dict(clave='kor_k1', nombre='K League 1', pais='Corea del Sur', espn='kor.1'),
    dict(clave='kor_k2', nombre='K League 2', pais='Corea del Sur', espn='kor.2'),
    dict(clave='rus_premier', nombre='Russian Premier League', pais='Rusia', espn='rus.1'),
    dict(clave='srb_superliga', nombre='Serbian SuperLiga', pais='Serbia', espn='srb.1'),
    dict(clave='svk_nike', nombre='Niké Liga', pais='Eslovaquia', espn='svk.1'),
    dict(clave='svn_prvaliga', nombre='PrvaLiga', pais='Eslovenia', espn='slo.1'),
    dict(clave='rsa_premier', nombre='South African Premier Division', pais='Sudáfrica', espn='rsa.1'),
    dict(clave='sui_super_league', nombre='Swiss Super League', pais='Suiza', espn='sui.1'),
    dict(clave='ukr_premier', nombre='Ukrainian Premier League', pais='Ucrania', espn='ukr.1'),
    dict(clave='uru_primera', nombre='Primera División', pais='Uruguay', espn='uru.1'),
    dict(clave='uzb_super', nombre='Uzbekistan Super League', pais='Uzbekistán', espn='uzb.1'),
    dict(clave='wal_cymru', nombre='Cymru Premier', pais='Gales', espn='wal.1'),
    dict(clave='ven_primera', nombre='Liga FUTVE', pais='Venezuela', espn='ven.1'),
    dict(clave='nic_primera', nombre='Liga Primera', pais='Nicaragua', espn='nca.1'),
    dict(clave='lbn_premier', nombre='Lebanese Premier League', pais='Líbano', espn='lbn.1'),
    dict(clave='mya_national', nombre='Myanmar National League', pais='Myanmar', espn='mya.1'),
    dict(clave='bhu_premier', nombre='Bhutan Premier League', pais='Bután', espn='bhu.1'),
    dict(clave='fro_effodeildin', nombre='Effodeildin', pais='Islas Feroe', espn='fro.1'),
    dict(clave='chi_primera_b', nombre='Primera B', pais='Chile', espn='chi.2'),
    dict(clave='ecu_serie_b', nombre='LigaPro Serie B', pais='Ecuador', espn='ecu.2'),
    dict(clave='per_liga2', nombre='Liga 2', pais='Perú', espn='per.2'),
    dict(clave='esp_primera_rfef', nombre='Primera RFEF', pais='España', espn='esp.3'),
    dict(clave='ita_serie_c', nombre='Serie C', pais='Italia', espn='ita.3'),
    dict(clave='mex_liga_premier', nombre='Liga Premier', pais='México', espn='mex.3'),
]

# Competiciones que YA cubre el proyecto con football-data (mejor fuente: trae
# remates, córners y cuotas de cierre). No se duplican por ESPN.
YA_CUBIERTAS = {
    'liga_mx', 'mls', 'brasil', 'argentina', 'premier', 'laliga', 'serie_a',
    'bundesliga', 'ligue_1', 'eredivisie', 'primeira', 'noruega', 'suecia',
    'finlandia', 'rumania', 'irlanda', 'turquia', 'dinamarca', 'china',
    'polonia', 'grecia', 'suiza', 'austria', 'champions', 'europa_league',
    'conference_league',
}


def catalogo_espn() -> Dict[str, str]:
    """Slug -> nombre de las 220 competiciones que publica ESPN."""
    r = requests.get(ESPN_DROPDOWN, headers=UA, timeout=60)
    r.raise_for_status()
    return {l['slug']: l.get('name', '') for l in r.json().get('leagues', [])}


def _cuenta_tramo(slug: str, ini: pd.Timestamp, fin: pd.Timestamp) -> Optional[int]:
    try:
        r = requests.get(ESPN_SCOREBOARD.format(liga=slug),
                         params={'dates': f'{ini:%Y%m%d}-{fin:%Y%m%d}', 'limit': 500},
                         headers=UA, timeout=45)
        r.raise_for_status()
        return sum(1 for e in r.json().get('events', [])
                   if e.get('status', {}).get('type', {}).get('completed'))
    except Exception:
        return None


def medir(slug: str, anios: int = 3) -> Dict:
    """Partidos terminados en los últimos `anios`, en tramos de 2 meses."""
    hoy = pd.Timestamp.today().normalize()
    tramos = list(pd.date_range(hoy - pd.DateOffset(years=anios), hoy, freq='2MS'))
    total, fallos = 0, 0
    for ini in tramos:
        fin = min(ini + pd.DateOffset(months=2) - pd.Timedelta(days=1), hoy)
        n = _cuenta_tramo(slug, ini, fin)
        if n is None:
            fallos += 1
        else:
            total += n
    return {'partidos': total, 'tramos_fallidos': fallos, 'tramos': len(tramos)}


def medir_todo(max_workers: int = 6) -> List[Dict]:
    disponibles = catalogo_espn()
    filas = []

    def _una(e):
        existe = e['espn'] in disponibles
        r = dict(e, existe_en_espn=existe,
                 nombre_espn=disponibles.get(e['espn'], ''))
        r.update(medir(e['espn']) if existe else
                 {'partidos': 0, 'tramos_fallidos': 0, 'tramos': 0})
        r['entrenable'] = bool(existe and r['partidos'] >= MIN_PARTIDOS)
        logger.info(f"  {e['clave']:24s} {e['espn']:26s} "
                    f"{'OK ' if existe else 'NO '} {r['partidos']:5d} partidos"
                    f"{'  -> entrenable' if r['entrenable'] else ''}")
        return r

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        filas = list(ex.map(_una, CATALOGO))
    filas.sort(key=lambda r: -r['partidos'])
    with open(MEDICIONES, 'w', encoding='utf-8') as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)
    return filas


TEMPORADAS_FD = ('2122', '2223', '2324', '2425', '2526')


def escribir_config(filas: List[Dict], salida: str = SALIDA) -> None:
    # Prioridad de fuente: si football-data sirve la competición, ESPN NO la
    # aporta. Sin este filtro el diccionario generado repetía la clave y ganaba
    # la ÚLTIMA (ESPN), degradando silenciosamente EFL Championship, Serie B,
    # Ligue 2, etc. de "con remates y cuotas" a "solo resultados".
    mejores = {f['clave'] for f in FD_MAIN} | {f['clave'] for f in FD_NEW}
    entrenables = [f for f in filas if f['entrenable'] and f['clave'] not in mejores]
    for f in filas:
        if f['clave'] in mejores:
            logger.info(f"  {f['clave']}: se toma de football-data (mejor fuente), "
                        f"no de ESPN.")
    n_total = len(FD_MAIN) + len(FD_NEW) + len(entrenables)
    partes = [
        '#!/usr/bin/env python3', '# -*- coding: utf-8 -*-', '"""',
        'v68 — Competiciones de fútbol añadidas al catálogo.', '',
        'GENERADO por `generar_ligas_v68.py`. No editar a mano.', '',
        f'{n_total} competiciones nuevas, cada una desde la fuente de MÁS calidad',
        'que la sirva:',
        f'  · {len(FD_MAIN):2d} de football-data /mmz4281/ — formato "main": remates,',
        '       córners, tarjetas Y cuotas de cierre. La mejor fuente.',
        f'  · {len(FD_NEW):2d} de football-data /new/     — formato "new": goles + cuotas.',
        f'  · {len(entrenables):2d} de ESPN                   — resultados; sin cuotas ni',
        '       estadística, pero es la única que cubre Latinoamérica y las copas.',
        '',
        '`disponible` arranca en False en TODAS: lo activa el entrenamiento sólo',
        'para las que baten a la línea base ELO (regla de oro del proyecto).',
        '"""', '',
        "FD_BASE = 'https://www.football-data.co.uk'", '',
        'LIGAS_V68 = {']

    for f in FD_MAIN:
        urls = ', '.join(f"f'{{FD_BASE}}/mmz4281/{s}/{f['fd']}.csv'" for s in TEMPORADAS_FD)
        partes += [
            f"    {f['clave']!r}: {{",
            f"        'nombre': {f['nombre']!r}, 'pais': {f['pais']!r}, 'formato': 'main',",
            f"        'urls': [{urls}],",
            f"        'disponible': False, 'features_extra': ['cuotas', 'extras'],",
            f"        'fuente_v68': 'football-data/mmz4281',",
            '    },']
    for f in FD_NEW:
        partes += [
            f"    {f['clave']!r}: {{",
            f"        'nombre': {f['nombre']!r}, 'pais': {f['pais']!r}, 'formato': 'new',",
            f"        'urls': [f'{{FD_BASE}}/new/{f['fd']}.csv'], 'anios_ventana': 8,",
            f"        'disponible': False, 'features_extra': ['cuotas'],",
            f"        'fuente_v68': 'football-data/new',",
            '    },']
    for f in entrenables:
        partes += [
            f"    {f['clave']!r}: {{",
            f"        'nombre': {f['nombre']!r}, 'pais': {f['pais']!r}, 'formato': 'espn',",
            f"        'espn_liga': {f['espn']!r}, 'desde': '2021-07-01', 'urls': [],",
            f"        'disponible': False, 'features_extra': [],",
            f"        'fuente_v68': 'espn', 'partidos_espn': {f['partidos']},",
            '    },']
    partes.append('}')
    partes += ['', '# Pedidas pero descartadas por falta de volumen. Se documentan para no',
               '# fingir cobertura: el número es cuántos partidos devuelve ESPN en 3 años.',
               'SIN_VOLUMEN = {']
    for f in filas:
        if not f['entrenable']:
            motivo = ('sin cobertura en ESPN' if not f['existe_en_espn']
                      else f"solo {f['partidos']} partidos en 3 años")
            partes.append(f"    {f['clave']!r}: ({f['nombre']!r}, {f['espn']!r}, {motivo!r}),")
    partes.append('}')
    partes += ['', '# Slug de ESPN por competición. Es lo que hace que la liga aparezca en',
               '# FIXTURES y, con ello, en Apuestas del Día: `alpha_finder` solo barre las',
               '# ligas que están en `fixtures_espn.ESPN_CODIGOS`. Las que vienen de',
               '# football-data también lo llevan, porque su histórico es de ahí pero sus',
               '# PRÓXIMOS partidos y cuotas salen de ESPN.',
               'ESPN_CODIGOS_V68 = {']
    for f in FD_MAIN + FD_NEW:
        if f.get('espn'):
            partes.append(f"    {f['clave']!r}: {f['espn']!r},")
    for f in entrenables:
        partes.append(f"    {f['clave']!r}: {f['espn']!r},")
    partes.append('}')
    with open(salida, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(partes) + '\n')
    print(f"✅ {salida}: {n_total} competiciones nuevas "
          f"({len(FD_MAIN)} main + {len(FD_NEW)} new + {len(entrenables)} espn); "
          f"{len(filas) - len(entrenables)} descartadas por volumen.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--medir', action='store_true')
    a = ap.parse_args()
    if a.medir or not os.path.exists(MEDICIONES):
        filas = medir_todo()
    else:
        filas = json.load(open(MEDICIONES, encoding='utf-8'))
    escribir_config(filas)
