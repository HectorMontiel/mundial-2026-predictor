#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — ¿PUBLICA FOTMOB LA ALINEACIÓN PROBABLE ANTES DEL PARTIDO?

ESPN ya está descartado y medido: 50 de 50 partidos TERMINADOS traen once
inicial y **0 de 54 por jugar**, incluido uno a 4,4 horas del saque
(`_v163_sondeo_alineacion.json`). Es exactamente la misma firma que tenía el
árbitro en la v160, y allí la respuesta fue FotMob.

Así que se pregunta lo mismo aquí. FotMob distingue dos cosas en
`content.lineup`:

    · el once CONFIRMADO, que llega poco antes del saque;
    · un once PROBABLE (`lineup.usingOptimalLineup` / `optimalLineup`),
      derivado de las últimas alineaciones, que sí existiría con antelación.

Si el probable está disponible con horas de margen, el bloque por jugador se
puede construir sobre él diciendo que es probable. Si no está, la sección no
puede prometer «alineación» y hay que decidir otra cosa.

    python _v163_sondeo_fotmob_lineup.py
"""
import json
import logging
import sys
import time
import warnings

import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_sondeo_fotmob_lineup.json'
LIGAS = ('Premier League', 'LaLiga', 'Serie A', 'Bundesliga', 'Ligue 1',
         'Liga MX', 'Major League Soccer', 'Serie A Betano',
         'Liga Profesional de Fútbol', 'Primeira Liga', 'Eredivisie',
         'Süper Lig', 'Trendyol Süper Lig')
MAX = 45


def _once(d):
    """
    Cuántos titulares trae el partido y de qué tipo.

    LA ESTRUCTURA, COMPROBADA Y NO SUPUESTA. La primera versión de esta función
    buscaba `content.lineup.lineup` como lista de equipos y devolvía cero
    SIEMPRE — también en partidos terminados, donde la alineación está. Lo cazó
    `_v163_verificar_lector_lineup.py`, que es justo para lo que existe: un
    sondeo que no encuentra nada y un lector roto se parecen demasiado.

    Lo que FotMob devuelve de verdad es:

        content.lineup = {matchId, lineupType, source, homeTeam, awayTeam, ...}
        content.lineup.homeTeam = {id, name, formation, starters:[...], ...}

    y `lineupType` es la etiqueta que distingue un once confirmado
    («standard») de uno probable, que es la pregunta del sondeo.
    """
    c = (d or {}).get('content') or {}
    lu = c.get('lineup') or {}
    if not isinstance(lu, dict):
        return 0, None, []
    n = 0
    for lado in ('homeTeam', 'awayTeam'):
        eq = lu.get(lado) or {}
        if isinstance(eq, dict) and isinstance(eq.get('starters'), list):
            n += len(eq['starters'])
    return n, lu.get('lineupType'), sorted(lu.keys())


def main():
    import arbitro_partido as ap

    hoy = pd.Timestamp.now(tz='UTC')
    filas = []
    for salto in (0, 1):
        fecha = (hoy + pd.Timedelta(days=salto)).strftime('%Y-%m-%d')
        idx = ap.indice_dia(fecha)
        cand = [m for m in idx if m.get('liga') in LIGAS]
        print('%s: %d partidos en el índice, %d en ligas de interés'
              % (fecha, len(idx), len(cand)), flush=True)
        for m in cand[:MAX]:
            d = ap._get('%s/matchDetails?matchId=%s' % (ap.BASE, m['match_id']))
            if not d:
                continue
            cuando = pd.to_datetime(m.get('utc'), errors='coerce', utc=True)
            horas = (float((cuando - pd.Timestamp.now(tz='UTC'))
                           .total_seconds()) / 3600.0
                     if cuando is not pd.NaT else None)
            n, optimal, claves = _once(d)
            started = bool((((d.get('general') or {}).get('started'))
                            or ((d.get('header') or {}).get('status') or {})
                            .get('started')))
            filas.append({'match_id': m['match_id'], 'liga': m['liga'],
                          'partido': '%s-%s' % (m['home'], m['away']),
                          'horas': round(horas, 2) if horas is not None else None,
                          'empezado': started, 'jugadores_en_once': n,
                          'lineup_type': optimal, 'claves_lineup': claves})
            print('   %-34s h=%7s  empezado=%-5s  once=%3d  tipo=%s'
                  % (('%s-%s' % (m['home'], m['away']))[:34],
                     ('%.1f' % horas) if horas is not None else '?',
                     started, n, optimal), flush=True)
            time.sleep(0.4)

    d = pd.DataFrame(filas)
    print()
    if len(d):
        fut = d[(~d['empezado']) & (d['horas'].fillna(-1) > 0.5)]
        print('POR JUGAR (>0,5 h de margen): %d' % len(fut))
        if len(fut):
            print('  con once publicado: %d (%.0f %%)'
                  % (int((fut['jugadores_en_once'] >= 22).sum()),
                     100.0 * (fut['jugadores_en_once'] >= 22).mean()))
            print('  tipos de alineación vistos: %s'
                  % dict(fut['lineup_type'].value_counts(dropna=False)))
            for lo, hi in ((0.5, 2), (2, 6), (6, 24), (24, 1e9)):
                sub = fut[(fut['horas'] >= lo) & (fut['horas'] < hi)]
                if len(sub):
                    print('   %5.1f-%5.0f h antes: %2d partidos, %2d con once'
                          % (lo, min(hi, 999), len(sub),
                             int((sub['jugadores_en_once'] >= 22).sum())))
    json.dump(filas, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
