#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v309 — UN SOLO NOMBRE POR COMPETICIÓN, DIGA LA FUENTE LO QUE DIGA.

LO QUE PIDIÓ EL USUARIO
    «Hay unas que me las das en inglés, otras en español, y son lo mismo pero
     traen diferentes partidos. No quiero eso: quiero todos en una misma sin
     importar inglés o español.»

QUÉ PASABA, MEDIDO
Cada partido llega con el nombre de competición de la fuente que lo trajo, y
el selector de «Liga» agrupa por ese texto tal cual. Contados en 64 versiones
de `pronostico_dia.json` (2026-08-20 → 2026-09-25), la misma competición salía
con hasta CINCO nombres, cada uno con sus propios partidos:

    Amistosos de selecciones   «International - Friendlies» (49 partidos),
                               «Partidos Amistosos Internacionales» (28, el
                               de Playdoit), «WORLD: Friendly International»
                               (32, el del tablero de Flashscore)
    Nations League UEFA        «UEFA - Nations League A/B/C/D» (260),
                               «International — UEFA Nations League» (7),
                               «EUROPE: UEFA Nations League - League A…» (24)
    Nations League CONCACAF    «CONCACAF - Nations League A/B/C» (50),
                               «CONCACAF — Nations League», «International —
                               CONCACAF Nations League», «NORTH & CENTRAL
                               AMERICA: CONCACAF Nations League - League B/C»
    Eliminatoria Copa Africana «CAF - Africa Cup of Nations Qualifiers» (111)
                               y «AFRICA: Africa Cup of Nations -
                               Qualification» (62)
    LaLiga Hypermotion         «LaLiga Hypermotion» y «SPAIN: LaLiga2»
    Colombia                   «Categoría Primera A» y «COLOMBIA: Primera A -
                               Clausura»

Y al revés, TRES ligas distintas se llamaban igual: «Primera División» era a
la vez Argentina, Uruguay y El Salvador, y elegirla en el filtro mezclaba las
tres.

LA REGLA
`canonica(liga, clave_liga, deporte)` devuelve el nombre único, en español:

  1. Si la competición tiene clave del proyecto (`config.LEAGUES`, las
     femeniles de `historico_fotmob`), manda el nombre de esa clave. Si ese
     nombre lo comparten dos claves, se le añade el país: «Primera División
     (Uruguay)».
  2. Las competiciones de SELECCIONES se reconocen por patrón, no por lista:
     da igual que diga «Friendlies», «Friendly International» o «Amistosos»,
     y que venga con la división (A/B/C/D) o sin ella — ESPN no la da y las
     casas sí, así que separarlas por división volvería a partir la lista.
  3. El formato «PAÍS: Liga - Fase» del tablero de Flashscore se cruza con
     las ligas del proyecto («SPAIN: LaLiga2» es LaLiga Hypermotion); si no
     es ninguna, queda «País: Liga» con el país en español y sin la fase
     (Apertura y Clausura son el mismo torneo para quien filtra).
  4. En tenis, el mismo torneo llegaba escrito de tres maneras («ATP
     Challenger Genoa - Qualifiers», «Challenger — Genoa», «CHALLENGER MEN -
     SINGLES: Genova 2 (Italy) - Qualification, clay»): queda «Challenger —
     Genoa». La previa y la final son el mismo torneo.

Es IDEMPOTENTE —el nombre canónico de un nombre canónico es él mismo—, y eso
es lo que permite aplicarlo en la aplicación sobre datos que ya pasaron por
aquí sin que cambien de nombre dos veces.

LO QUE NO TOCA
`clave_liga` no se cambia nunca: es la llave de los modelos, la calibración y
los históricos. El nombre original se conserva en `liga_origen`.
"""
import re
import unicodedata
from functools import lru_cache
from typing import Dict, Optional


def _n(t) -> str:
    """Minúsculas, sin acentos y con los espacios colapsados."""
    t = unicodedata.normalize('NFKD', str(t or ''))
    t = t.encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'\s+', ' ', t).strip()


# ---------------------------------------------------------------------------
# países: inglés (como lo escribe el tablero) y español -> español
# ---------------------------------------------------------------------------
_PAISES_ES = {
    'england': 'Inglaterra', 'spain': 'España', 'italy': 'Italia',
    'germany': 'Alemania', 'france': 'Francia',
    'netherlands': 'Países Bajos', 'portugal': 'Portugal',
    'belgium': 'Bélgica', 'scotland': 'Escocia', 'wales': 'Gales',
    'northern ireland': 'Irlanda del Norte', 'ireland': 'Irlanda',
    'austria': 'Austria', 'switzerland': 'Suiza', 'turkey': 'Turquía',
    'turkiye': 'Turquía', 'greece': 'Grecia', 'denmark': 'Dinamarca',
    'norway': 'Noruega', 'sweden': 'Suecia', 'finland': 'Finlandia',
    'poland': 'Polonia', 'czech republic': 'República Checa',
    'czechia': 'República Checa', 'slovakia': 'Eslovaquia',
    'hungary': 'Hungría', 'romania': 'Rumanía', 'bulgaria': 'Bulgaria',
    'serbia': 'Serbia', 'croatia': 'Croacia', 'slovenia': 'Eslovenia',
    'bosnia and herzegovina': 'Bosnia', 'russia': 'Rusia',
    'ukraine': 'Ucrania', 'estonia': 'Estonia', 'latvia': 'Letonia',
    'lithuania': 'Lituania', 'iceland': 'Islandia', 'israel': 'Israel',
    'cyprus': 'Chipre', 'usa': 'Estados Unidos',
    'united states': 'Estados Unidos', 'canada': 'Canadá',
    'mexico': 'México', 'brazil': 'Brasil', 'argentina': 'Argentina',
    'chile': 'Chile', 'colombia': 'Colombia', 'peru': 'Perú',
    'ecuador': 'Ecuador', 'uruguay': 'Uruguay', 'paraguay': 'Paraguay',
    'bolivia': 'Bolivia', 'venezuela': 'Venezuela',
    'costa rica': 'Costa Rica', 'guatemala': 'Guatemala',
    'honduras': 'Honduras', 'el salvador': 'El Salvador',
    'panama': 'Panamá', 'nicaragua': 'Nicaragua', 'jamaica': 'Jamaica',
    'japan': 'Japón', 'south korea': 'Corea del Sur',
    'korea republic': 'Corea del Sur', 'china': 'China',
    'australia': 'Australia', 'saudi arabia': 'Arabia Saudita',
    'egypt': 'Egipto', 'nigeria': 'Nigeria', 'south africa': 'Sudáfrica',
    'morocco': 'Marruecos', 'algeria': 'Argelia', 'tunisia': 'Túnez',
    'oman': 'Omán', 'qatar': 'Catar', 'united arab emirates': 'Emiratos Árabes',
    'uae': 'Emiratos Árabes', 'india': 'India', 'singapore': 'Singapur',
    'indonesia': 'Indonesia', 'thailand': 'Tailandia', 'vietnam': 'Vietnam',
    'philippines': 'Filipinas', 'united kingdom': 'Reino Unido',
    'world': 'Mundial', 'europe': 'Europa', 'africa': 'África',
    'asia': 'Asia', 'south america': 'Sudamérica',
    'north & central america': 'Norte y Centroamérica',
    'oceania': 'Oceanía',
}
# el español también entra (idempotencia: «Japón: B.League One» -> igual)
for _v in list(_PAISES_ES.values()):
    _PAISES_ES.setdefault(_n(_v), _v)


# ---------------------------------------------------------------------------
# el tablero de Flashscore -> la clave del proyecto
# ---------------------------------------------------------------------------
# (país en inglés normalizado, patrón sobre el nombre de liga SIN la fase)
# Sacado de los nombres reales vistos en el tablero (2026-08-20 → 09-25) y de
# cómo llama Flashscore a cada liga del catálogo. El orden importa: la
# primera regla que casa gana, así que las más específicas van antes.
_TABLERO_A_CLAVE = [
    ('england', r'^premier league$', 'premier'),
    ('england', r'^championship$', 'eng_championship'),
    ('england', r'^league one$', 'eng_league_one'),
    ('england', r'^league two$', 'eng_league_two'),
    ('england', r'^national league$', 'eng_national'),
    ('england', r'^fa cup$', 'eng_fa_cup'),
    ('england', r'^(efl|carabao) cup$', 'eng_carabao'),
    ('england', r'^(wsl|super league women|women.?s super league)$',
     'fem_inglaterra'),
    ('spain', r'^laliga ?2$|^laliga hypermotion$|^segunda', 'esp_hypermotion'),
    ('spain', r'^laliga$|^la liga$', 'laliga'),
    ('spain', r'^copa del rey$', 'esp_copa_rey'),
    ('spain', r'^liga f', 'fem_espana'),
    ('italy', r'^serie a women$|^serie a femminile$', 'fem_italia'),
    ('italy', r'^serie a$', 'serie_a'),
    ('italy', r'^serie b$', 'ita_serie_b'),
    ('germany', r'^bundesliga women$|^frauen', 'fem_alemania'),
    ('germany', r'^bundesliga$', 'bundesliga'),
    ('germany', r'^2\. bundesliga$', 'ger_bundesliga2'),
    ('france', r'premiere ligue|d1 arkema|division 1 women', 'fem_francia'),
    ('france', r'^ligue 1$', 'ligue_1'),
    ('france', r'^ligue 2$', 'fra_ligue2'),
    ('netherlands', r'^eredivisie$', 'eredivisie'),
    ('netherlands', r'^eerste divisie$', 'ned_eerste'),
    ('portugal', r'^liga portugal$|^primeira liga$', 'primeira'),
    ('belgium', r'jupiler|^pro league$', 'bel_pro_league'),
    ('scotland', r'^premiership$', 'sco_premiership'),
    ('scotland', r'^championship$', 'sco_championship'),
    ('austria', r'^bundesliga$', 'aut_bundesliga'),
    ('switzerland', r'^super league$', 'suiza'),
    ('turkey', r'^super lig$', 'turquia'),
    ('greece', r'^super league', 'gre_super_league'),
    ('denmark', r'^superliga(en)?$', 'dinamarca'),
    ('norway', r'^eliteserien$', 'noruega'),
    ('sweden', r'^allsvenskan$', 'suecia'),
    ('finland', r'^veikkausliiga$', 'finlandia'),
    ('poland', r'^ekstraklasa$', 'polonia'),
    ('romania', r'^superliga$|^liga 1$|^liga i$', 'rumania'),
    ('russia', r'^premier league$', 'rus_premier'),
    ('ireland', r'^premier division$', 'irlanda'),
    ('israel', r'ligat|premier league', 'isr_premier'),
    ('usa', r'^mls$', 'mls'),
    ('usa', r'^usl championship$', 'usl_championship'),
    ('mexico', r'^liga mx women$|^liga mx femenil$', 'mex_femenil'),
    ('mexico', r'^liga mx$', 'liga_mx'),
    ('mexico', r'^liga de expansion', 'mex_expansion'),
    ('brazil', r'^serie a', 'brasil'),
    ('brazil', r'^serie b', 'bra_serie_b'),
    ('brazil', r'^copa (do )?brasil', 'bra_copa'),
    ('argentina', r'^liga profesional|^torneo betano|^primera division$',
     'argentina'),
    ('argentina', r'^primera nacional$', 'arg_primera_nacional'),
    ('colombia', r'^primera a$|^liga betplay', 'col_primera_a'),
    ('peru', r'^liga 1', 'per_liga1'),
    ('ecuador', r'^liga ?pro', 'ecu_liga_pro'),
    ('uruguay', r'^liga auf|^primera division$', 'uru_primera'),
    ('paraguay', r'^primera division$|^copa de primera|^division profesional$',
     'par_division'),
    ('bolivia', r'^division profesional$', 'bol_division'),
    ('chile', r'^liga de primera$|^primera division$|^campeonato nacional$',
     'chi_primera'),
    ('venezuela', r'^liga futve$|^primera division$', 'ven_primera'),
    ('costa rica', r'^primera division$|^liga fpd$', 'crc_fpd'),
    ('el salvador', r'^primera division$', 'slv_primera'),
    ('japan', r'^j1 league$', 'jpn_j1'),
    ('saudi arabia', r'^saudi professional league$|^pro league$', 'ksa_pro'),
    ('south africa', r'premiership$|^premier (soccer )?league$', 'rsa_premier'),
    ('australia', r'^a-league', 'aus_aleague'),
    ('china', r'^super league$', 'china'),
    ('india', r'^isl$|^indian super league$', 'ind_isl'),
]

# Fases que no separan un torneo de otro para quien filtra.
_FASE = re.compile(
    r'\s+-\s+(apertura|clausura|play ?offs?|winners.*|losers.*|'
    r'group [a-z0-9]+|relegation.*|promotion.*|qualification|'
    r'championship round|regular season|final.*)$', re.I)


def _nombres_de_clave() -> Dict[str, tuple]:
    """clave -> (nombre, país). Del catálogo del proyecto y de las femeniles."""
    fuera: Dict[str, tuple] = {}
    try:
        from config import LEAGUES
        for k, cfg in LEAGUES.items():
            if cfg.get('nombre'):
                fuera[k] = (str(cfg['nombre']), str(cfg.get('pais') or ''))
    except Exception:
        pass
    # las ramas que no están en LEAGUES (femeniles), con su nombre visible
    fem = {'mex_femenil': ('Liga MX Femenil', 'México'),
           'champions_femenil': ('Champions League femenina', 'Europa'),
           'fem_inglaterra': ('WSL (Inglaterra, femenil)', 'Inglaterra'),
           'fem_espana': ('Liga F (España, femenil)', 'España'),
           'fem_alemania': ('Frauen-Bundesliga (Alemania, femenil)',
                            'Alemania'),
           'fem_francia': ('Première Ligue (Francia, femenil)', 'Francia'),
           'fem_italia': ('Serie A (Italia, femenil)', 'Italia')}
    for k, v in fem.items():
        fuera.setdefault(k, v)
    return fuera


@lru_cache(maxsize=1)
def _catalogo():
    """(clave -> nombre canónico, nombre normalizado -> nombre canónico)."""
    base = _nombres_de_clave()
    cuenta: Dict[str, int] = {}
    for nombre, _p in base.values():
        cuenta[_n(nombre)] = cuenta.get(_n(nombre), 0) + 1
    por_clave: Dict[str, str] = {}
    for k, (nombre, pais) in base.items():
        if cuenta[_n(nombre)] > 1 and pais:
            por_clave[k] = '%s (%s)' % (nombre, pais)
        else:
            por_clave[k] = nombre
    # un nombre que sólo tiene una clave se reconoce aunque llegue sin ella;
    # los repetidos («Primera División») sin clave no se pueden resolver
    por_nombre = {_n(v): v for v in por_clave.values()}
    for k, (nombre, _p) in base.items():
        if cuenta[_n(nombre)] == 1:
            por_nombre[_n(nombre)] = por_clave[k]
    return por_clave, por_nombre


# ---------------------------------------------------------------------------
# selecciones: por patrón
# ---------------------------------------------------------------------------
_CONFEDERACIONES = (('conmebol', 'CONMEBOL'), ('concacaf', 'CONCACAF'),
                    ('uefa', 'UEFA'), ('europe', 'UEFA'), ('caf', 'CAF'),
                    ('africa', 'CAF'), ('afc', 'AFC'), ('asia', 'AFC'),
                    ('ofc', 'OFC'), ('oceania', 'OFC'),
                    ('south america', 'CONMEBOL'),
                    ('north & central', 'CONCACAF'))


def _confederacion(t: str) -> str:
    for clave, nombre in _CONFEDERACIONES:
        if re.search(r'\b%s\b' % re.escape(clave), t):
            return nombre
    return ''


def _de_selecciones(t: str) -> Optional[str]:
    """El nombre canónico si `t` (normalizado) es una competición de
    selecciones absolutas; None si no lo es o no se reconoce."""
    # las juveniles y las de clubes NO son esto
    if re.search(r'\bu-?\d{2}\b|\bsub-?\d{2}\b|youth|juvenil', t):
        return None
    femenino = bool(re.search(r'\bwomen\b|femenin|\(w\)|\bfem\b', t))
    if re.search(r'club friendl|amistosos? de clubes', t):
        return 'Amistosos de clubes'
    if re.search(r'friendl|amistos', t):
        return ('Amistosos internacionales femeninos' if femenino
                else 'Amistosos internacionales')
    if re.search(r'nations league|liga de naciones', t):
        conf = _confederacion(t)
        if not conf:
            return None
        return 'Liga de Naciones %s%s' % (conf,
                                          ' femenina' if femenino else '')
    if re.search(r'africa cup of nations|copa africa|afcon', t):
        if re.search(r'qualif|clasif|eliminatoria', t):
            return 'Eliminatorias Copa Africana'
        return 'Copa Africana de Naciones'
    if re.search(r'eliminatorias copa africana', t):
        return 'Eliminatorias Copa Africana'
    if (re.search(r'world cup|world championship|mundial|worldq', t)
            and re.search(r'qualif|clasif|eliminatoria', t)):
        conf = _confederacion(t)
        return 'Eliminatorias Mundial%s' % (' (%s)' % conf if conf else '')
    m = re.match(r'^clasif\.? (uefa|concacaf|conmebol|afc|caf|ofc)$', t)
    if m:
        return 'Eliminatorias Mundial (%s)' % m.group(1).upper()
    if re.search(r'\beuro(copa)?\b|european championship', t):
        if re.search(r'qualif|clasif|eliminatoria', t):
            return 'Eliminatorias Eurocopa'
        return 'Eurocopa' + (' femenina' if femenino else '')
    if re.search(r'gold cup|copa oro', t):
        return 'Copa Oro'
    if re.search(r'copa america', t):
        return 'Copa América'
    if re.search(r'asian cup|copa asia', t):
        return 'Copa Asiática'
    if re.search(r'asean', t):
        return 'Copa ASEAN'
    if re.search(r'arabian gulf cup|copa del golfo', t):
        return 'Copa del Golfo'
    return None


# ---------------------------------------------------------------------------
# tenis
# ---------------------------------------------------------------------------
_CIUDAD_ALIAS = {'genova': 'Genoa', 'saint tropez': 'Saint-Tropez',
                 'sao paulo': 'São Paulo', 'sao luis': 'São Luís',
                 'belem': 'Belém'}


def _ciudad(c: str) -> str:
    c = re.sub(r'\b[MW]\d{2,3}\b', ' ', c)                 # nivel ITF
    c = re.sub(r'(?i)\b(qualification|qualifiers|clasificaci[oó]n|'
               r'qual\.?|final|singles|doubles)\b', ' ', c)
    c = re.sub(r'\s+\d+\s*$', ' ', c)                    # «Genova 2»
    c = re.sub(r'\s+', ' ', c).strip(' -—,.')
    k = _n(c).replace('-', ' ')
    k = re.sub(r'^st\.? ', 'saint ', k)
    return _CIUDAD_ALIAS.get(k, c)


def _tenis(liga: str) -> str:
    t = _n(liga)
    if not t:
        return liga
    if 'davis' in t:
        return 'Copa Davis'
    if 'billie jean' in t:
        return 'Billie Jean King Cup'
    if 'laver' in t:
        return 'Laver Cup'
    if re.search(r'\butr\b', t):
        return 'UTR Pro Tennis Series'
    if t in ('atp', 'wta', 'itf'):
        return t.upper()
    if re.search(r'challenger women|wta ?125', t):
        nivel = 'WTA 125'
    elif 'challenger' in t:
        nivel = 'Challenger'
    elif re.search(r'\bitf\b', t):
        nivel = ('ITF femenino' if re.search(
            r'women|femenino|mujeres|\bw\d{2,3}\b', t) else 'ITF masculino')
    elif t.startswith('wta'):
        nivel = 'WTA'
    elif t.startswith('atp'):
        nivel = 'ATP'
    else:
        return liga
    s = str(liga)
    if ':' in s:
        s = s.split(':', 1)[1]
    elif '—' in s:
        s = s.split('—', 1)[1]
    else:
        s = re.sub(r'(?i)^\s*(atp challenger|wta ?125k?|itf (men|women)'
                   r'( qual\.?)?|itf|challenger (men|women)|challenger|'
                   r'wta|atp)\s*', '', s)
    s = re.split(r'\(|,|\s-\s', s)[0]
    ciudad = _ciudad(s)
    return '%s — %s' % (nivel, ciudad) if ciudad else nivel


# ---------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def canonica(liga: str, clave_liga: str = '', deporte: str = '') -> str:
    """El nombre único y en español de la competición. Nunca lanza."""
    try:
        return _canonica(str(liga or '').strip(), str(clave_liga or '').strip(),
                         str(deporte or '').strip())
    except Exception:
        return str(liga or '').strip()


def _canonica(liga: str, clave: str, deporte: str) -> str:
    if not liga and not clave:
        return liga
    if _n(deporte) == 'tenis':
        return _tenis(liga)
    por_clave, por_nombre = _catalogo()
    if clave and clave in por_clave:
        return por_clave[clave]
    t = _n(liga)
    sel = _de_selecciones(t)
    if sel:
        return sel
    if t in por_nombre:
        return por_nombre[t]
    # «PAÍS: Liga - Fase», el formato del tablero
    m = re.match(r'^([^:]{2,40}):\s*(.+)$', liga)
    if m:
        pais_raw, resto = m.group(1).strip(), m.group(2).strip()
        pais_n = _n(pais_raw)
        # la fase puede venir encadenada («Clausura - Winners»): se quita
        # hasta que no quede ninguna
        sin_fase, previo = resto, None
        while sin_fase != previo:
            previo, sin_fase = sin_fase, _FASE.sub('', sin_fase).strip()
        sn = _n(sin_fase)
        # el cruce con las ligas del proyecto es SÓLO de fútbol: «TURKEY:
        # Super Lig» de baloncesto no es la Süper Lig
        if _n(deporte) in ('', 'futbol'):
            for p, patron, k in _TABLERO_A_CLAVE:
                if p == pais_n and re.search(patron, sn) and k in por_clave:
                    return por_clave[k]
        pais = _PAISES_ES.get(pais_n)
        if pais:
            return '%s: %s' % (pais, sin_fase)
        return '%s: %s' % (pais_raw.title() if pais_raw.isupper() else pais_raw,
                           sin_fase)
    return liga


# ---------------------------------------------------------------------------
_PROFUNDIDAD = 7


def aplicar(obj, _prof: int = 0):
    """Pone el nombre canónico en todo dict con `liga` que sea un partido o
    un pick, recorriendo listas y dicts anidados (Capa 1, combinadas, patas…).

    Muta en su sitio y devuelve el mismo objeto. El original se guarda UNA
    vez en `liga_origen`. Nunca lanza.
    """
    if _prof > _PROFUNDIDAD:
        return obj
    try:
        if isinstance(obj, dict):
            lg = obj.get('liga')
            if isinstance(lg, str) and lg and (
                    'partido' in obj or 'deporte' in obj
                    or 'clave_liga' in obj or 'apuesta' in obj):
                nuevo = canonica(lg, str(obj.get('clave_liga') or ''),
                                 str(obj.get('deporte') or ''))
                if nuevo and nuevo != lg:
                    obj.setdefault('liga_origen', lg)
                    obj['liga'] = nuevo
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    aplicar(v, _prof + 1)
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, (dict, list)):
                    aplicar(v, _prof + 1)
    except Exception:
        pass
    return obj
