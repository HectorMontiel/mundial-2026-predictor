#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v171 — ¿QUÉ MERCADOS PUBLICA PLAYDOIT DE VERDAD, Y CUÁLES PODEMOS MODELAR?

«Todo debe venir de Playdoit para saber qué otros mercados podemos meter.» Esto
lo contesta: recorre los tableros del día, agrupa las familias por su forma y
dice cuáles tienen los DOS lados de una línea —que son las únicas que podemos
convertir en probabilidad sin margen— y cuáles de ésas sabemos modelar hoy.

Tres columnas, y las tres importan:

    publica      en cuántos partidos aparece la familia
    con línea    en cuántos trae Más/Menos de la misma línea (devigable)
    modelable    si el proyecto tiene un modelo para ese conteo

Una familia que Playdoit publica pero que no sabemos modelar NO es un fallo: es
la lista de la compra. Y una que sabemos modelar pero la casa no publica es un
número que no se puede jugar, que es peor que no tenerlo.

    python _v171_catalogo_playdoit.py --partidos 25
"""
import argparse
import json
import logging
import re
import sys
import warnings
from collections import Counter, defaultdict

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v171_catalogo_playdoit.json'

# Lo que el proyecto sabe modelar hoy, y con qué.
MODELABLE = {
    'goles': 'matriz de marcador',
    'corners': 'ataque/defensa + binomial negativa',
    'tarjetas': 'ataque/defensa + árbitro + binomial negativa',
    'remates': 'ataque/defensa + binomial negativa',
    'remates_on': 'ataque/defensa + binomial negativa',
    '1x2': 'matriz de marcador, encogida al mercado',
    'btts': 'matriz de marcador',
    'handicap': 'matriz de marcador con push',
    'jugador_remates': 'Poisson por jugador encogido a la cuota posicional',
}


def _clasifica(nom_norm: str) -> str:
    """La familia a la que pertenece un rótulo de Playdoit."""
    n = nom_norm
    if 'jugador' in n or re.search(r'\([A-Z]{3}\)', n, re.I):
        if 'puerta' in n or 'arco' in n:
            return 'jugador_remates_on'
        if 'remate' in n or 'tiro' in n:
            return 'jugador_remates'
        if 'tarjeta' in n:
            return 'jugador_tarjetas'
        if 'gol' in n:
            return 'jugador_goles'
        return 'jugador_otros'
    if 'esquina' in n or 'corner' in n:
        return 'corners'
    if 'tarjeta' in n or 'amarilla' in n:
        return 'tarjetas'
    if 'puerta' in n or 'arco' in n:
        return 'remates_on'
    if 'remate' in n or ('tiro' in n and 'esquina' not in n):
        return 'remates'
    if n.startswith('resultado final') or n == '1x2':
        return '1x2'
    if 'doble oportunidad' in n:
        return 'doble_oportunidad'
    if 'handicap' in n or 'hándicap' in n or 'asiatico' in n:
        return 'handicap'
    if 'ambos equipos' in n:
        return 'btts'
    if n.startswith('total') or 'total de goles' in n:
        return 'goles'
    if 'marcador exacto' in n or 'goles exactos' in n:
        return 'marcador'
    if 'falta' in n:
        return 'faltas'
    if 'fuera de juego' in n or 'offside' in n:
        return 'fuera_de_juego'
    if 'saque' in n or 'penal' in n:
        return 'otros_sucesos'
    return 'otros'


_LINEA = re.compile(r'^(m[aá]s|menos)\s+de\s+([0-9]+(?:[.,][0-9]+)?)$')


def _tiene_dos_lados(sels) -> bool:
    mas, menos = set(), set()
    for s in sels or []:
        if not isinstance(s, dict):
            continue
        m = _LINEA.match(str(s.get('nombre') or '').strip().lower())
        if not m:
            continue
        (menos if m.group(1) == 'menos' else mas).add(m.group(2))
    return bool(mas & menos)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--partidos', type=int, default=25)
    a = ap.parse_args()

    import cuotas_multi as cm
    import mercado_implicito as mi

    doc = mi.cargar(recargar=True)
    pares = [(v['home'], v['away'])
             for v in list((doc.get('partidos') or {}).values())][:a.partidos]
    print('%d partidos del precálculo del día\n' % len(pares))

    publica, con_linea, ejemplos = Counter(), Counter(), defaultdict(set)
    n_ok = 0
    for h, aw in pares:
        try:
            t = cm.mercados_playdoit('futbol', h, aw)
        except Exception:
            t = None
        if not t:
            continue
        n_ok += 1
        vistas, vistas_linea = set(), set()
        for m in (t.get('mercados') or []):
            nom = str(m.get('nombre') or '')
            fam = _clasifica(nom.strip().lower())
            vistas.add(fam)
            if len(ejemplos[fam]) < 3:
                ejemplos[fam].add(nom[:52])
            if _tiene_dos_lados(m.get('selecciones')):
                vistas_linea.add(fam)
        for f in vistas:
            publica[f] += 1
        for f in vistas_linea:
            con_linea[f] += 1

    print('%d tableros leídos\n' % n_ok)
    print('%-22s %9s %10s  %s' % ('familia', 'publica', 'con línea',
                                  'modelable con'))
    print('-' * 78)
    filas = []
    for fam, n in publica.most_common():
        modelo = MODELABLE.get(fam)
        print('%-22s %6d/%-2d %7d/%-2d  %s'
              % (fam, n, n_ok, con_linea[fam], n_ok,
                 modelo or '— (no lo sabemos modelar)'))
        filas.append({'familia': fam, 'publica': n, 'con_linea': con_linea[fam],
                      'de': n_ok, 'modelable': bool(modelo),
                      'modelo': modelo,
                      'ejemplos': sorted(ejemplos[fam])})

    print('\nLO QUE PODEMOS JUGAR HOY (publica con línea Y sabemos modelar):')
    for f in filas:
        if f['modelable'] and f['con_linea']:
            print('  ✓ %-20s en %d de %d partidos'
                  % (f['familia'], f['con_linea'], n_ok))
    print('\nLA LISTA DE LA COMPRA (la casa lo publica con línea, no lo '
          'modelamos):')
    for f in filas:
        if not f['modelable'] and f['con_linea'] >= max(2, n_ok // 5):
            print('  · %-20s en %d de %d · ej.: %s'
                  % (f['familia'], f['con_linea'], n_ok,
                     (f['ejemplos'] or ['-'])[0]))

    json.dump({'partidos': n_ok, 'familias': filas},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
