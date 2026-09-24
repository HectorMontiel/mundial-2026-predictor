# -*- coding: utf-8 -*-
"""
v306 — LAS BAJAS DE CADA EQUIPO (LESIONES Y SANCIONES), DESDE FOTMOB.

POR QUÉ
El usuario pidió que el modelo «extraiga automáticamente la información más
relevante de cada equipo —noticias, rendimiento de los jugadores— para que se
agregue como variable». El proyecto tenía la pieza (`fuente_bajas`, v209) y
llevaba semanas vacía: medido el 2026-09-23, `archivo_contexto.json` tenía
2.357 partidos anotados y CERO señales. Leía la API interna de FotMob, que
exige una cabecera firmada y devuelve 404/403 a todo.

La página de cada partido (`/match/<id>`, el mismo `__NEXT_DATA__` que ya usa
`fotmob_scraper`) sí responde, y trae en `lineup.<equipo>.unavailable` los
lesionados y sancionados con su regreso previsto. Comprobado con Arsenal-
Leeds: Saliba, Timber, White y Mosquera en el Arsenal; Rodon y Joseph en el
Leeds.

QUÉ HACE, Y QUÉ TODAVÍA NO
    · Captura las bajas de los partidos próximos de las ligas con id de
      FotMob y las deja en `bajas_dia.json` para la tarjeta.
    · Las ACUMULA en `bajas_historico.csv`, una fila por partido y equipo.
    · NO entra todavía en ninguna probabilidad. Una variable nueva sólo se
      usa cuando se ha medido que mejora el pronóstico en el tramo que no vio,
      y para eso hace falta histórico. Enchufarla sin medir sería repetir lo
      que el proyecto lleva años evitando.

Uso:
    python bajas_fotmob.py            # próximos 3 días
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

FICHERO = 'bajas_dia.json'
HISTORICO = 'bajas_historico.csv'
DIAS = 3
PAUSA = 1.2

# clave del proyecto -> (id de FotMob, slug). Las ligas de clubes que
# `fotmob_scraper` ya conocía, más las femeninas de `historico_fotmob`.
def ligas() -> Dict[str, tuple]:
    fuera = {}
    try:
        import fotmob_scraper as fm
        fuera.update(fm.FOTMOB_LEAGUE_IDS)
    except Exception:
        pass
    try:
        import historico_fotmob as hf
        for clave, (paginas, _) in hf.LIGAS.items():
            fuera[clave] = paginas[0]
    except Exception:
        pass
    return fuera


def _bajas_de_partido(mid: str) -> Dict:
    import fotmob_scraper as fm
    raw = fm._next_data('https://www.fotmob.com/match/%s' % mid)
    if not raw:
        return {}
    lu = (((raw.get('props') or {}).get('pageProps') or {})
          .get('content') or {}).get('lineup') or {}
    fuera = {}
    for lado in ('homeTeam', 'awayTeam'):
        t = lu.get(lado) or {}
        lista = []
        for u in t.get('unavailable') or []:
            un = u.get('unavailability') or {}
            lista.append({'jugador': u.get('name'),
                          'tipo': un.get('type'),           # injury / suspension
                          'regreso': un.get('expectedReturn')})
        fuera['home' if lado == 'homeTeam' else 'away'] = {
            'equipo': t.get('name'), 'bajas': lista}
    return fuera


def capturar(dias: int = DIAS) -> Dict:
    import historico_fotmob as hf
    ahora = pd.Timestamp.now('UTC').tz_localize(None)
    limite = ahora + pd.Timedelta(days=dias)
    doc = {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'partidos': {}}
    filas = []
    for clave, (lid, slug) in ligas().items():
        try:
            partidos = hf._temporada(lid, slug)
        except Exception as e:
            logger.debug('[bajas] %s: %s', clave, e)
            continue
        for m in partidos:
            st = m.get('status') or {}
            if st.get('finished') or st.get('started') or st.get('cancelled'):
                continue
            f = pd.to_datetime(st.get('utcTime'), errors='coerce', utc=True)
            if pd.isna(f):
                continue
            f = f.tz_convert(None)
            if not (ahora <= f <= limite):
                continue
            try:
                b = _bajas_de_partido(str(m.get('id')))
            except Exception as e:
                logger.debug('[bajas] partido %s: %s', m.get('id'), e)
                b = {}
            time.sleep(PAUSA)
            if not b:
                continue
            h = hf._limpia((m.get('home') or {}).get('name'))
            a = hf._limpia((m.get('away') or {}).get('name'))
            k = '%s|%s|%s' % (clave, h, a)
            doc['partidos'][k] = {'clave_liga': clave, 'home': h, 'away': a,
                                  'inicio': f.strftime('%Y-%m-%d %H:%M:%S'),
                                  'fotmob_id': str(m.get('id')), **b}
            for lado, eq in (('home', h), ('away', a)):
                bl = (b.get(lado) or {}).get('bajas') or []
                filas.append({
                    'capturado': doc['generado'], 'clave_liga': clave,
                    'fecha': f.strftime('%Y-%m-%d'), 'partido': '%s vs %s' % (h, a),
                    'lado': lado, 'equipo': eq, 'n_bajas': len(bl),
                    'n_lesion': sum(1 for x in bl if x.get('tipo') == 'injury'),
                    'n_sancion': sum(1 for x in bl
                                     if x.get('tipo') == 'suspension'),
                    'jugadores': '; '.join(str(x.get('jugador')) for x in bl)})
    tmp = FICHERO + '.nuevo'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    if filas:
        nuevo = not os.path.exists(HISTORICO)
        with open(HISTORICO, 'a', encoding='utf-8', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
            if nuevo:
                w.writeheader()
            w.writerows(filas)
    logger.info('[bajas] %d partidos con su parte de bajas',
                len(doc['partidos']))
    return doc


_CACHE: Dict = {}


def de_partido(pick: Dict) -> Dict:
    """Las bajas de un pronóstico, buscando por liga y nombres. {} si no."""
    try:
        if 'doc' not in _CACHE:
            with open(FICHERO, encoding='utf-8') as fh:
                _CACHE['doc'] = json.load(fh) or {}
        par = str(pick.get('partido') or '')
        if ' vs ' not in par:
            return {}
        import name_mapper as nm
        h, a = (x.strip() for x in par.split(' vs ', 1))
        cand = [v for v in (_CACHE['doc'].get('partidos') or {}).values()
                if v.get('clave_liga') == pick.get('clave_liga')]
        if not cand:
            return {}
        ch = nm.mapear(h, [v['home'] for v in cand], contexto='bajas')
        if not ch:
            return {}
        for v in cand:
            if v['home'] == ch and nm.mapear(a, [v['away']], contexto='bajas'):
                return v
    except Exception as e:
        logger.debug('[bajas] %s: %s', pick.get('partido'), e)
    return {}


def texto(pick: Dict) -> str:
    """«🚑 Arsenal 4 (Saliba, Timber…) · Leeds 2» — o cadena vacía."""
    v = de_partido(pick)
    if not v:
        return ''
    trozos = []
    for lado in ('home', 'away'):
        b = (v.get(lado) or {}).get('bajas') or []
        if not b:
            continue
        nombres = ', '.join(str(x.get('jugador') or '').split(' ')[-1]
                            for x in b[:2])
        trozos.append('%s %d (%s%s)' % ((v.get(lado) or {}).get('equipo')
                                        or lado, len(b), nombres,
                                        '…' if len(b) > 2 else ''))
    return ('🚑 Bajas: ' + ' · '.join(trozos)) if trozos else ''


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    d = capturar()
    print('bajas capturadas de %d partidos' % len(d['partidos']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
