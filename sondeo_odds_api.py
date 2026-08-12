#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v127 — ¿Cubre The Odds API las 24 ligas que no tienen histórico de cuotas?

Por qué este script existe
--------------------------
El proyecto tiene 24 competiciones de fútbol cuyo histórico trae las columnas
de cuota con CERO filas rellenas. Sin cuota de cierre no hay ROI simulado, sin
ROI simulado no hay p5, y sin p5 esas ligas no se pueden juzgar. La única vía
identificada para rellenarlas es un proveedor de pago.

Antes de pagar hay que saber si cubre justo esas ligas, que son pequeñas
(Primera Nacional argentina, Bolivia, Chile, Copa de Brasil…) y son
precisamente las que un agregador suele no tener.

CÓMO SE GASTAN LOS CRÉDITOS, Y POR QUÉ ESTE SONDEO CASI NO GASTA
----------------------------------------------------------------
Según la documentación de la API:

    GET /v4/sports        →  0 créditos   ← NO cuenta contra la cuota
    GET /v4/events        →  0 créditos   ← NO cuenta contra la cuota
    GET /v4/.../odds      →  1 × mercados × regiones
    GET /v4/.../odds-history → 10 × mercados × regiones   ← diez veces más caro

El catálogo de deportes es GRATIS y contiene la lista de competiciones
soportadas. Eso responde «¿está esta liga?» sin gastar nada. Sólo si una de
nuestras 24 aparece tiene sentido gastar créditos comprobando que su histórico
devuelve datos de verdad, y aun así con UN mercado y UNA región, que es el
mínimo posible: 10 créditos por comprobación.

Es decir: el peor caso de este sondeo son unas decenas de créditos de los 500,
no los 500.

La clave NO se guarda en el repositorio
---------------------------------------
Se lee de la variable de entorno `ODDS_API_KEY`. Nunca se escribe en disco ni
se imprime. El fichero de salida sólo lleva los nombres de las ligas.

Uso:
    ODDS_API_KEY=... python sondeo_odds_api.py            # sólo lo gratis
    ODDS_API_KEY=... python sondeo_odds_api.py --historico # + 10 créditos/liga
"""
import glob
import json
import os
import sys
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import requests

BASE = 'https://api.the-odds-api.com/v4'
ARCHIVO = 'sondeo_odds_api.json'
TIMEOUT = 25

# Las 24 competiciones cuyo histórico no tiene ni una fila con cuota, con el
# nombre que un agregador internacional usaría. La clave es la del proyecto.
HUERFANAS = {
    'afc_champions': 'AFC Champions League',
    'arg_primera_nacional': 'Argentina Primera Nacional',
    'bol_division': 'Bolivia Division Profesional',
    'bra_copa': 'Copa do Brasil',
    'bra_serie_b': 'Brazil Serie B',
    'champions': 'UEFA Champions League',
    'chi_primera': 'Chile Primera Division',
    'col_primera_a': 'Colombia Primera A',
    'conference_league': 'UEFA Conference League',
    'ecu_liga_pro': 'Ecuador Liga Pro',
    'europa_league': 'UEFA Europa League',
    'leagues_cup': 'Leagues Cup',
    'libertadores': 'Copa Libertadores',
    'mex_expansion': 'Mexico Liga de Expansion',
    'per_liga1': 'Peru Liga 1',
    'rsa_premier': 'South Africa Premier',
    'sudamericana': 'Copa Sudamericana',
    'uru_primera': 'Uruguay Primera',
    'usl_championship': 'USL Championship',
    'bol_division_2': 'Bolivia (otra)',
    'chi_primera_2': 'Chile (otra)',
    'bra_copa_2': 'Brasil copa (otra)',
    'kbo': 'KBO (béisbol)',
    'nba': 'NBA (baloncesto)',
}

# Palabras que identifican a cada liga en el catálogo del proveedor. Se casa
# por tokens y no por nombre exacto porque cada proveedor la escribe a su
# manera («soccer_argentina_primera_division» vs «Argentina Primera Nacional»).
PISTAS = {
    'afc_champions': ('afc', 'champions'),
    'arg_primera_nacional': ('argentina', 'nacional'),
    'bol_division': ('bolivia',),
    'bra_copa': ('brazil', 'copa'),
    'bra_serie_b': ('brazil', 'serie_b'),
    'champions': ('uefa', 'champs'),
    'chi_primera': ('chile',),
    'col_primera_a': ('colombia',),
    'conference_league': ('uefa', 'conference'),
    'ecu_liga_pro': ('ecuador',),
    'europa_league': ('uefa', 'europa'),
    'leagues_cup': ('leagues', 'cup'),
    'libertadores': ('libertadores',),
    'mex_expansion': ('mexico',),
    'per_liga1': ('peru',),
    'rsa_premier': ('africa',),
    'sudamericana': ('sudamericana',),
    'uru_primera': ('uruguay',),
    'usl_championship': ('usl',),
    'kbo': ('kbo',),
    'nba': ('basketball_nba',),
}


def _clave() -> str:
    k = os.environ.get('ODDS_API_KEY', '').strip()
    if not k:
        print('Falta la variable de entorno ODDS_API_KEY.')
        print('La clave NO se guarda en el repositorio: se pasa por entorno.')
        sys.exit(2)
    return k


def _creditos(resp) -> Dict:
    """Lo que la propia API dice que llevas gastado."""
    return {'usados': resp.headers.get('x-requests-used'),
            'restantes': resp.headers.get('x-requests-remaining'),
            'ultimo': resp.headers.get('x-requests-last')}


def catalogo(clave: str) -> List[Dict]:
    """Todas las competiciones soportadas. CUESTA 0 CRÉDITOS."""
    r = requests.get(f'{BASE}/sports', params={'apiKey': clave, 'all': 'true'},
                     timeout=TIMEOUT)
    if r.status_code != 200:
        print(f'/v4/sports devolvió HTTP {r.status_code}: {r.text[:200]}')
        sys.exit(1)
    c = _creditos(r)
    print(f'catálogo descargado · créditos usados hasta ahora: '
          f'{c["usados"]} · restantes: {c["restantes"]} '
          f'(esta llamada: {c["ultimo"]})')
    return r.json()


def main() -> int:
    clave = _clave()
    deportes = catalogo(clave)
    print(f'{len(deportes)} competiciones en el catálogo del proveedor\n')

    futbol = [d for d in deportes
              if str(d.get('key', '')).startswith('soccer')]
    print(f'de ellas, {len(futbol)} son de fútbol\n')

    encontradas, ausentes = {}, []
    for liga, nombre in HUERFANAS.items():
        pistas = PISTAS.get(liga)
        if not pistas:
            ausentes.append((liga, nombre, 'sin pista definida'))
            continue
        cands = [d for d in deportes
                 if all(p in str(d.get('key', '')).lower() for p in pistas)]
        if not cands:
            # segundo intento: por el título, que a veces difiere de la clave
            cands = [d for d in deportes
                     if all(p in str(d.get('title', '')).lower()
                            for p in pistas)]
        if cands:
            encontradas[liga] = [{'key': c['key'], 'title': c.get('title'),
                                  'activo': c.get('active')} for c in cands]
        else:
            ausentes.append((liga, nombre, 'no está en el catálogo'))

    print('=' * 78)
    print(f'CUBIERTAS: {len(encontradas)} de {len(HUERFANAS)}')
    for liga, cs in encontradas.items():
        for c in cs:
            print(f"   ✅ {liga:22} → {c['key']:38} "
                  f"{'activa' if c['activo'] else 'INACTIVA'}")
    print()
    print(f'NO CUBIERTAS: {len(ausentes)}')
    for liga, nombre, motivo in ausentes:
        print(f'   ❌ {liga:22} ({nombre}) — {motivo}')

    salida = {'catalogo': len(deportes), 'futbol': len(futbol),
              'cubiertas': encontradas,
              'ausentes': [{'liga': a, 'nombre': b, 'motivo': c}
                           for a, b, c in ausentes]}

    # --- lo caro, sólo si se pide expresamente ---------------------------
    if '--historico' in sys.argv and encontradas:
        print()
        print('Comprobando el HISTÓRICO (10 créditos por liga, 1 mercado, '
              '1 región)…')
        salida['historico'] = {}
        for liga, cs in list(encontradas.items())[:3]:      # tres, no más
            k = cs[0]['key']
            r = requests.get(f'{BASE}/historical/sports/{k}/odds',
                             params={'apiKey': clave, 'regions': 'eu',
                                     'markets': 'h2h', 'oddsFormat': 'decimal',
                                     'date': '2024-05-01T12:00:00Z'},
                             timeout=TIMEOUT)
            c = _creditos(r)
            ok = r.status_code == 200
            n = 0
            if ok:
                try:
                    j = r.json()
                    n = len(j.get('data') or [])
                except Exception:
                    n = 0
            print(f'   {liga:22} HTTP {r.status_code} · {n} partidos · '
                  f'restantes {c["restantes"]}')
            salida['historico'][liga] = {'http': r.status_code, 'n': n}

    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print(f'\n{ARCHIVO} escrito (sin la clave dentro).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
