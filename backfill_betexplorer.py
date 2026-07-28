#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v76 — Histórico de cuotas INMEDIATO para las ligas que ESPN dejaba a ciegas.

El problema
-----------
La v75 dejó 22 competiciones ACTIVAS (~31.700 partidos) sin una sola cuota
histórica, y con un diagnóstico que sonaba a callejón sin salida: ESPN retira
el bloque `odds` al acabar el partido y football-data no publica esos países.
La conclusión de entonces —"solo cabe acumular fotos diarias"— era correcta
para el MOVIMIENTO de línea, pero **falsa para la cuota de cierre**, que sí
está publicada y accesible.

Dos afirmaciones de la v71 que este módulo desmiente con datos:

  1. "BetExplorer es HTML puramente JS, cero filas de cuotas en 738 KB".
     **Falso.** Las páginas de resultados sirven las cuotas en el propio HTML,
     en atributos `data-odd`. Medido: Chile Primera División 2024 devuelve
     240 de 240 partidos con 1X2, marcador y fecha. Lo que falla es intentar
     leerlas con expresiones regulares —los nombres van envueltos en `<strong>`
     cuando el equipo ganó, y los `</tr>` no siempre cierran—, no la fuente.
     Con un parser de HTML de verdad salen enteras.

  2. Que no había forma de tener histórico "ya". Sí la hay, y son años: el
     sitemap oficial publica entre 8 y 20 temporadas por competición.

Cómo se hace de forma respetuosa
--------------------------------
  · **Solo URLs permitidas por `robots.txt`.** BetExplorer prohíbe `/ad/`,
    `/redirect/`, `/bookmaker/` y TODAS las variantes con query-string
    (`?stage=`, `?year=`, `?page=`…). Este módulo no toca ninguna: usa
    exclusivamente las páginas `/results/` que el propio sitemap anuncia.
    La consecuencia honesta es que en las ligas de Apertura/Clausura solo se
    obtiene la fase que la página sirve por defecto — se recupera cobertura
    recorriendo más temporadas, no saltándose la norma.
  · **Descubrimiento por sitemap**, no adivinando slugs. Adivinar dio 11 de 22
    ligas y varios falsos negativos (Paraguay no es `division-profesional`
    sino `primera-division`; Sudáfrica es `premier-league`; la Champions está
    en `europe/champions-league`). El sitemap las da todas y exactas.
  · **Un segundo entre peticiones** y caché en disco: una liga entera se baja
    una sola vez.

Qué cuota es
------------
La que BetExplorer muestra en su tabla de resultados es la **media de las casas
al cierre**, que es exactamente la misma naturaleza que el `odd_home` que el
proyecto ya usa para football-data (`AvgC*`). Por eso entra como
`bookmaker='mercado'` y es directamente comparable en el mismo backtest.

Uso:
    python backfill_betexplorer.py --descubrir     # mapea sitemap -> ligas
    python backfill_betexplorer.py --liga chi_primera
    python backfill_betexplorer.py                 # todas
"""

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional

import requests

import odds_store

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

BASE = 'https://www.betexplorer.com'
UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0.0.0 Safari/537.36')}
CACHE = 'betexplorer_cache'
MAPA = '_v76_betexplorer_mapa.json'
SALIDA = '_v76_backfill.json'
PAUSA = 1.0          # segundos entre peticiones — cortesía, no hay prisa

# Competición del proyecto -> (país, slug) en BetExplorer.
# Verificado uno a uno contra el sitemap oficial el 2026-07-28.
LIGAS = {
    'chi_primera':          ('chile', 'primera-division'),
    'per_liga1':            ('peru', 'liga-1'),
    'uru_primera':          ('uruguay', 'primera-division'),
    'ecu_liga_pro':         ('ecuador', 'liga-pro'),
    'bol_division':         ('bolivia', 'division-profesional'),
    'par_division':         ('paraguay', 'primera-division'),
    'crc_fpd':              ('costa-rica', 'primera-division'),
    'slv_primera':          ('el-salvador', 'primera-division'),
    'col_primera_a':        ('colombia', 'primera-a'),
    'mex_expansion':        ('mexico', 'liga-de-expansion-mx'),
    'bra_serie_b':          ('brazil', 'serie-b'),
    'arg_primera_nacional': ('argentina', 'primera-nacional'),
    'usl_championship':     ('usa', 'usl-championship'),
    'rsa_premier':          ('south-africa', 'premier-league'),
    'ned_eerste':           ('netherlands', 'eerste-divisie'),
    'eng_fa_cup':           ('england', 'fa-cup'),
    'champions':            ('europe', 'champions-league'),
    'europa_league':        ('europe', 'europa-league'),
    'conference_league':    ('europe', 'europa-conference-league'),
    'libertadores':         ('south-america', 'copa-libertadores'),
    'sudamericana':         ('south-america', 'copa-sudamericana'),
    'afc_champions':        ('asia', 'afc-champions-league'),
}


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


# ---------------------------------------------------------------------------
# Descubrimiento por sitemap (la vía que el propio robots.txt anuncia)
# ---------------------------------------------------------------------------
def urls_de_resultados(refrescar: bool = False) -> List[str]:
    ruta = os.path.join(CACHE, 'sitemap_results.json')
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(ruta) and not refrescar:
        with open(ruta, encoding='utf-8') as f:
            return json.load(f)
    urls: List[str] = []
    for sm in ('results', 'results/other', 'results/other2', 'results/other3'):
        r = requests.get(f'{BASE}/sitemap/football/{sm}.xml', headers=UA, timeout=60)
        if r.status_code == 200:
            urls += re.findall(r'<loc>([^<]+)</loc>', r.text)
        time.sleep(PAUSA)
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(urls, f)
    logger.info(f"sitemap: {len(urls)} páginas de resultados descubiertas")
    return urls


def temporadas_de_liga(clave: str, urls: List[str]) -> List[str]:
    """URLs de todas las temporadas de esa competición, más reciente primero."""
    pais, slug = LIGAS[clave]
    pref = f'{BASE}/football/{pais}/{slug}'
    sel = [u for u in urls
           if u.startswith(pref) and re.fullmatch(
               rf'{re.escape(pref)}(-\d{{4}}(-\d{{4}})?)?/results/', u)]
    return sorted(set(sel), reverse=True)


# ---------------------------------------------------------------------------
# Descarga y parseo
# ---------------------------------------------------------------------------
def _descargar(url: str, refrescar: bool = False) -> Optional[str]:
    os.makedirs(CACHE, exist_ok=True)
    nombre = re.sub(r'[^a-z0-9]+', '_', url.replace(BASE, '').lower()).strip('_') + '.html'
    ruta = os.path.join(CACHE, nombre)
    if os.path.exists(ruta) and not refrescar:
        with open(ruta, encoding='utf-8') as f:
            return f.read()
    try:
        r = requests.get(url, headers=UA, timeout=45)
    except Exception as e:
        logger.warning(f"{url}: {e}")
        return None
    time.sleep(PAUSA)
    if r.status_code != 200:
        logger.warning(f"{url}: HTTP {r.status_code}")
        return None
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(r.text)
    return r.text


def parsear(html: str) -> List[dict]:
    """
    Partidos con 1X2, marcador y fecha de una página de resultados.

    Se usa BeautifulSoup y NO expresiones regulares a propósito: el equipo
    ganador viene envuelto en `<strong>` y las filas no siempre cierran
    `</tr>`, así que un regex se deja fuera el 78 % de los partidos (medido:
    52 de 240 en Chile 2024) y encima falla en silencio, que es lo peor que
    puede hacer un extractor de datos.
    """
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, 'lxml')
    salida = []
    for tr in s.select('tr'):
        a = tr.select_one('a.in-match')
        if not a:
            continue
        spans = a.select('span')
        if len(spans) < 2:
            continue
        home = spans[0].get_text(strip=True)
        away = spans[-1].get_text(strip=True)
        marcador = tr.select_one('td.h-text-center a')
        cuotas = []
        for td in tr.select('td.table-main__odds'):
            v = td.get('data-odd')
            if v is None:
                hijo = td.select_one('[data-odd]')
                v = hijo.get('data-odd') if hijo else None
            cuotas.append(v)
        celda_fecha = tr.select_one('td.h-text-right')
        fecha = celda_fecha.get_text(strip=True) if celda_fecha else None
        if not (home and away and marcador and len(cuotas) >= 3 and all(cuotas[:3])):
            continue
        m = re.match(r'(\d+):(\d+)', marcador.get_text(strip=True))
        f = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', fecha or '')
        if not (m and f):
            continue
        salida.append({
            'home': home, 'away': away,
            'goles_local': int(m.group(1)), 'goles_visit': int(m.group(2)),
            'fecha': f'{f.group(3)}-{f.group(2)}-{f.group(1)}',
            'odd_home': float(cuotas[0]), 'odd_draw': float(cuotas[1]),
            'odd_away': float(cuotas[2]),
        })
    return salida


# ---------------------------------------------------------------------------
# Enlace con la identidad de partido del proyecto
# ---------------------------------------------------------------------------
def _catalogo(clave: str) -> List[str]:
    """Equipos tal y como los conoce el modelo de esa liga."""
    try:
        with open(f'team_stats_{clave}.json', encoding='utf-8') as f:
            return list((json.load(f).get('equipos') or {}).keys())
    except Exception:
        return []


def enlazar(clave: str, partidos: List[dict]) -> List[dict]:
    """
    Empareja cada partido de BetExplorer con el del histórico del proyecto.

    El emparejamiento va por FECHA + MARCADOR primero y por nombre después, que
    es justo al revés de lo intuitivo, y la razón es empírica. Con el orden
    natural —traducir el nombre y luego buscar el partido— Chile perdía 453 de
    1.489 partidos porque BetExplorer abrevia ("U. Catolica", "U. De Chile",
    "A. Italiano") y la similitud contra "Universidad Católica" se queda en
    0,67, por debajo del umbral 0,78 de `name_mapper`. Bajar el umbral a lo
    bruto habría abierto la puerta a emparejamientos falsos, que en un backfill
    de cuotas son el peor error posible: contaminan el backtest sin dejar
    rastro visible.

    Yendo por fecha y marcador, el propio resultado hace de verificación. Entre
    los partidos de un mismo día con el mismo marcador exacto, el nombre solo
    tiene que desempatar, así que un umbral bajo (0,45) es seguro: un candidato
    con la fecha correcta, el marcador correcto y el nombre más parecido es el
    partido, y si hay empate se descarta en vez de adivinar.
    """
    import pandas as pd
    import name_mapper

    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        return []
    h = pd.read_csv(ruta, low_memory=False)
    h['date'] = pd.to_datetime(h['date'], errors='coerce')
    h = h.dropna(subset=['date'])

    # índice: (fecha, goles_local, goles_visit) -> [(match_id, home, away)]
    porclave: Dict[tuple, list] = {}
    for mid, f, hg, ag, ht, at in zip(h['MATCH_ID'], h['date'], h['home_goals'],
                                      h['away_goals'], h['home_team'], h['away_team']):
        if pd.isna(hg) or pd.isna(ag):
            continue
        porclave.setdefault((f.date(), int(hg), int(ag)), []).append(
            (str(mid), str(ht), str(at)))

    def _sim(a: str, b: str) -> float:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, name_mapper.normalizar(a),
                               name_mapper.normalizar(b)).ratio()

    salida, sin_partido, ambiguos = [], 0, 0
    usados = set()
    for p in partidos:
        f0 = dt.date.fromisoformat(p['fecha'])
        cands = []
        for d in (0, -1, 1):                    # husos horarios
            cands += porclave.get((f0 + dt.timedelta(days=d),
                                   p['goles_local'], p['goles_visit']), [])
        cands = [c for c in cands if c[0] not in usados]
        if not cands:
            sin_partido += 1
            continue
        puntuados = sorted(
            ((min(_sim(p['home'], c[1]), _sim(p['away'], c[2])), c) for c in cands),
            key=lambda x: -x[0])
        mejor, c = puntuados[0]
        if mejor < 0.45:
            sin_partido += 1
            continue
        # si dos candidatos empatan, no se adivina
        if len(puntuados) > 1 and abs(puntuados[1][0] - mejor) < 1e-9:
            ambiguos += 1
            continue
        usados.add(c[0])
        salida.append({**p, 'match_id': c[0], 'home_team': c[1], 'away_team': c[2]})
    logger.info(f"[{clave}] enlazados {len(salida)}/{len(partidos)} "
                f"(sin partido en el histórico {sin_partido}, ambiguos {ambiguos})")
    return salida


def backfill_liga(clave: str, urls: List[str], max_temporadas: int = 12,
                  refrescar: bool = False) -> dict:
    temporadas = temporadas_de_liga(clave, urls)[:max_temporadas]
    if not temporadas:
        logger.warning(f"[{clave}] sin temporadas en el sitemap")
        return {'clave': clave, 'temporadas': 0, 'partidos': 0, 'enlazados': 0}
    crudos = []
    for u in temporadas:
        html = _descargar(u, refrescar)
        if html:
            crudos += parsear(html)
    enlazados = enlazar(clave, crudos)
    filas = []
    ahora = _ahora()
    for p in enlazados:
        filas.append({
            'match_id': p['match_id'], 'league_key': clave,
            'match_date': p['fecha'], 'home_team': p['home_team'],
            'away_team': p['away_team'], 'bookmaker': 'mercado',
            'fase': 'cierre', 'snapshot_key': 'cierre', 'dias_al_partido': 0.0,
            'odds_home': p['odd_home'], 'odds_draw': p['odd_draw'],
            'odds_away': p['odd_away'],
            'source_file': 'betexplorer', 'ingested_at': ahora,
        })
    n = 0
    if filas:
        con = odds_store.conectar()
        n = odds_store.guardar(con, filas, reemplazar=True)
        con.close()
    return {'clave': clave, 'temporadas': len(temporadas),
            'partidos': len(crudos), 'enlazados': len(enlazados), 'insertados': n}


def main(solo: Optional[str] = None, max_temporadas: int = 12,
         refrescar: bool = False) -> dict:
    urls = urls_de_resultados(refrescar)
    claves = [solo] if solo else list(LIGAS)
    res = []
    for c in claves:
        if c not in LIGAS:
            logger.error(f"{c} no está en el mapa de BetExplorer")
            continue
        r = backfill_liga(c, urls, max_temporadas, refrescar)
        res.append(r)
        logger.info(f"[{c}] {r['insertados']} cuotas insertadas "
                    f"({r['temporadas']} temporadas, {r['partidos']} partidos leídos)")
    total = sum(r['insertados'] for r in res)
    salida = {'generado': _ahora(), 'total_insertados': total,
              'ligas': len([r for r in res if r['insertados']]), 'detalle': res,
              'fuente': 'betexplorer (páginas /results/ permitidas por robots.txt, '
                        'descubiertas vía sitemap oficial)'}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--liga')
    ap.add_argument('--temporadas', type=int, default=12)
    ap.add_argument('--refrescar', action='store_true')
    ap.add_argument('--descubrir', action='store_true')
    a = ap.parse_args()
    if a.descubrir:
        u = urls_de_resultados(True)
        for c in LIGAS:
            t = temporadas_de_liga(c, u)
            print(f"  {c:24s} {len(t):3d} temporadas  {t[0].replace(BASE,'') if t else '--'}")
    else:
        r = main(a.liga, a.temporadas, a.refrescar)
        print(f"\n{r['total_insertados']} cuotas de cierre insertadas en "
              f"{r['ligas']} competiciones.")
        for d in sorted(r['detalle'], key=lambda x: -x['insertados']):
            print(f"  {d['clave']:24s} {d['insertados']:6d} cuotas  "
                  f"({d['enlazados']}/{d['partidos']} enlazados, "
                  f"{d['temporadas']} temporadas)")
