#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — ¿Aportan Matchbook y Polymarket algo que las cinco casas no den?

Responder que «tienen mejor margen» no basta. La v112 midió que el edge del
proyecto es COMPRAR AL MEJOR PRECIO (+1,37 % de ROI sin modelo), y la v113
midió que con nuestras cinco casas el margen conjunto es 1,0574 y hay CERO
arbitrajes. La pregunta que decide es otra:

    sobre los partidos que REALMENTE evaluamos, ¿cuántas veces el exchange
    mejora el mejor precio del tablón actual, y cuánto?

Y una segunda, todavía más útil en la práctica: un exchange no cobra margen,
así que su precio medio de back/lay es la mejor estimación disponible de la
probabilidad real. Eso convierte al exchange en el ANCLA de devig —mejor que
Pinnacle, que es lo que el proyecto usa hoy— aunque el usuario nunca llegue a
apostar allí. Un ancla mejor mueve TODOS los EV del tablón.

Se mide, sobre los partidos de fútbol de hoy y los próximos días:
  1. cobertura: cuántos partidos del tablón aparecen en cada exchange,
  2. margen implícito medio de cada fuente,
  3. cuántas veces cada fuente da el MEJOR precio de una selección,
  4. arbitrajes: partidos donde 1/mejor_home + 1/mejor_draw + 1/mejor_away < 1,
  5. y el caso accionable: exchange como ancla, Playdoit como precio —
     ¿cuántas apuestas de EV positivo aparecen en la casa del usuario?

    python _v114_medir_exchanges.py
"""
import json
import statistics
import sys
from typing import Dict, List, Optional

import requests

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import cuotas_multi as cm

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0 Safari/537.36'),
      'Accept': 'application/json'}

MB = 'https://www.matchbook.com/edge/rest/events'
PM = 'https://gamma-api.polymarket.com/events'


# ---------------------------------------------------------------------------
def indice_matchbook(deporte: str = 'futbol') -> Dict[str, dict]:
    """{clave: {...,'cuotas':{home,draw,away},'lay':{...}}} desde Matchbook."""
    SPORT = {'futbol': 15, 'tenis': 9, 'mlb': 3, 'nba': 4}
    sid = SPORT.get(deporte)
    if not sid:
        return {}
    indice: Dict[str, dict] = {}
    for offset in range(0, 400, 50):
        try:
            r = requests.get(MB, params={
                'sport-ids': sid, 'states': 'open', 'include-prices': 'true',
                'price-depth': 3, 'odds-type': 'DECIMAL',
                'exchange-type': 'back-lay', 'currency': 'EUR',
                'per-page': 50, 'offset': offset}, headers=UA, timeout=30)
            if r.status_code != 200:
                break
            evs = r.json().get('events') or []
        except Exception as e:
            print(f'  [matchbook] corte en offset {offset}: {type(e).__name__}')
            break
        if not evs:
            break
        for e in evs:
            nombre = str(e.get('name') or '')
            if ' vs ' not in nombre:
                continue
            home, away = [x.strip() for x in nombre.split(' vs ', 1)]
            for m in (e.get('markets') or []):
                if str(m.get('market-type')) not in ('one_x_two', 'two_way'):
                    continue
                back, lay = {}, {}
                for run in (m.get('runners') or []):
                    nom = str(run.get('name') or '').strip()
                    if nom.lower() in ('draw', 'the draw', 'empate'):
                        lado = 'draw'
                    elif cm.normalizar(nom) == cm.normalizar(home):
                        lado = 'home'
                    elif cm.normalizar(nom) == cm.normalizar(away):
                        lado = 'away'
                    else:
                        continue
                    bs = [p.get('odds') for p in (run.get('prices') or [])
                          if p.get('side') == 'back' and p.get('odds')]
                    ls = [p.get('odds') for p in (run.get('prices') or [])
                          if p.get('side') == 'lay' and p.get('odds')]
                    if bs:
                        back[lado] = round(max(bs), 4)
                    if ls:
                        lay[lado] = round(min(ls), 4)
                if back.get('home') and back.get('away'):
                    indice[f'{cm.normalizar(home)}|{cm.normalizar(away)}'] = {
                        'home': home, 'away': away, 'casa': 'Matchbook',
                        'fecha': cm.fecha_normalizada(e.get('start')),
                        'cuotas': back, 'lay': lay}
                    break
    return indice


def indice_polymarket() -> Dict[str, dict]:
    """Mercados «A vs. B» de Polymarket con su precio de mercado."""
    indice: Dict[str, dict] = {}
    for offset in (0, 100, 200, 300, 400, 500):
        try:
            r = requests.get(PM, params={
                'closed': 'false', 'limit': 100, 'offset': offset,
                'order': 'volume24hr', 'ascending': 'false'},
                headers=UA, timeout=30)
            if r.status_code != 200:
                break
            evs = r.json()
        except Exception as e:
            print(f'  [polymarket] corte en offset {offset}: {type(e).__name__}')
            break
        if not evs:
            break
        for e in evs:
            titulo = str(e.get('title') or '')
            sep = ' vs. ' if ' vs. ' in titulo else (' vs ' if ' vs ' in titulo
                                                     else None)
            if not sep or ' - ' in titulo:
                continue        # «- More Markets» son derivados, no el 1X2
            home, away = [x.strip() for x in titulo.split(sep, 1)]
            cuotas = {}
            for m in (e.get('markets') or []):
                try:
                    outs = json.loads(m.get('outcomes') or '[]')
                    pr = [float(x) for x in
                          json.loads(m.get('outcomePrices') or '[]')]
                except Exception:
                    continue
                if len(outs) != 2 or len(pr) != 2:
                    continue
                # el mercado del ganador es el que enfrenta a los dos equipos;
                # los derivados son «Yes/No» sobre otra cosa
                for nom, p in zip(outs, pr):
                    if p <= 0:
                        continue
                    n = cm.normalizar(str(nom))
                    if n == cm.normalizar(home):
                        cuotas['home'] = round(1 / p, 4)
                    elif n == cm.normalizar(away):
                        cuotas['away'] = round(1 / p, 4)
                    elif str(nom).strip().lower() in ('draw', 'tie'):
                        cuotas['draw'] = round(1 / p, 4)
            if cuotas.get('home') and cuotas.get('away'):
                indice[f'{cm.normalizar(home)}|{cm.normalizar(away)}'] = {
                    'home': home, 'away': away, 'casa': 'Polymarket',
                    'cuotas': cuotas}
    return indice


# ---------------------------------------------------------------------------
def margen(c: Dict[str, float]) -> Optional[float]:
    if not (c.get('home') and c.get('away')):
        return None
    s = 1 / c['home'] + 1 / c['away']
    if c.get('draw'):
        s += 1 / c['draw']
    return round(s, 4)


def main() -> int:
    print('=' * 78)
    print('v114 — EXCHANGES CONTRA EL TABLÓN ACTUAL')
    print('=' * 78)

    print('\nBajando el tablón de las cinco casas…')
    cm.precargar('futbol')
    pin = cm._indice('futbol')
    bov = cm._indice_bov('futbol')
    pdt = cm._indice_pdt('futbol')
    uni = cm._indice_uni('futbol')
    print(f'  Pinnacle {len(pin)} · Bovada {len(bov)} · Playdoit {len(pdt)} '
          f'· Unibet {len(uni)}')

    print('\nBajando los exchanges…')
    mb = indice_matchbook('futbol')
    pm = indice_polymarket()
    print(f'  Matchbook {len(mb)} · Polymarket {len(pm)}')

    # ---- 1. margen medio por fuente ---------------------------------------
    print('\n' + '-' * 78)
    print('1. MARGEN IMPLÍCITO MEDIO (1,0000 = sin margen)')
    print('-' * 78)
    for nombre, idx in (('Pinnacle', pin), ('Bovada', bov), ('Playdoit', pdt),
                        ('Unibet', uni), ('Matchbook', mb), ('Polymarket', pm)):
        ms = [m for m in (margen(v.get('cuotas') or {}) for v in idx.values())
              if m and 0.8 < m < 1.6]
        if ms:
            print(f'  {nombre:<12} {statistics.mean(ms):.4f}   '
                  f'(mediana {statistics.median(ms):.4f}, n={len(ms)})')
        else:
            print(f'  {nombre:<12} sin datos')

    # ---- 2. cobertura y mejora sobre el tablón ----------------------------
    print('\n' + '-' * 78)
    print('2. SOBRE LOS PARTIDOS DE PINNACLE, ¿QUIÉN DA EL MEJOR PRECIO?')
    print('-' * 78)
    fuentes = [('Pinnacle', pin), ('Bovada', bov), ('Playdoit', pdt),
               ('Unibet', uni), ('Matchbook', mb), ('Polymarket', pm)]
    gana = {n: 0 for n, _ in fuentes}
    cobertura = {n: 0 for n, _ in fuentes}
    mejoras_mb, mejoras_pm = [], []
    n_comunes = arbitrajes = 0
    margen_5, margen_7 = [], []

    for clave, v in pin.items():
        home, away = v['home'], v['away']
        dispon = {}
        for nombre, idx in fuentes:
            hit = idx.get(clave)
            if hit is None:
                hit = cm._buscar(idx, home, away)
            if hit and (hit.get('cuotas') or {}).get('home'):
                dispon[nombre] = hit['cuotas']
                cobertura[nombre] += 1
        if len(dispon) < 2:
            continue
        n_comunes += 1
        for lado in ('home', 'draw', 'away'):
            precios = {n: c[lado] for n, c in dispon.items() if c.get(lado)}
            if len(precios) < 2:
                continue
            mejor = max(precios.values())
            for n, p in precios.items():
                if p == mejor:
                    gana[n] += 1
            # ¿cuánto mejora el exchange al mejor de las CINCO?
            cinco = {n: p for n, p in precios.items()
                     if n in ('Pinnacle', 'Bovada', 'Playdoit', 'Unibet')}
            if cinco:
                mejor5 = max(cinco.values())
                if 'Matchbook' in precios:
                    mejoras_mb.append(precios['Matchbook'] / mejor5 - 1)
                if 'Polymarket' in precios:
                    mejoras_pm.append(precios['Polymarket'] / mejor5 - 1)
        # margen del mejor precio, con 5 casas y con 5+exchanges
        def _mejor_margen(nombres):
            c = {}
            for lado in ('home', 'draw', 'away'):
                ps = [dispon[n][lado] for n in nombres
                      if n in dispon and dispon[n].get(lado)]
                if ps:
                    c[lado] = max(ps)
            return margen(c)
        m5 = _mejor_margen(('Pinnacle', 'Bovada', 'Playdoit', 'Unibet'))
        m7 = _mejor_margen([n for n, _ in fuentes])
        if m5:
            margen_5.append(m5)
        if m7:
            margen_7.append(m7)
            if m7 < 1.0:
                arbitrajes += 1
                if arbitrajes <= 8:
                    print(f'  💰 ARBITRAJE {home} vs {away}: margen {m7:.4f} '
                          f'({", ".join(sorted(dispon))})')

    print(f'\n  partidos con ≥2 fuentes: {n_comunes}')
    print('  cobertura sobre el tablón de Pinnacle:')
    for n, _ in fuentes:
        print(f'    {n:<12} {cobertura[n]:>4}')
    print('  veces que da el MEJOR precio de una selección:')
    tot = sum(gana.values()) or 1
    for n, c in sorted(gana.items(), key=lambda x: -x[1]):
        print(f'    {n:<12} {c:>5}  ({c/tot*100:.1f} %)')

    if margen_5 and margen_7:
        print(f'\n  margen del MEJOR precio con 4 casas : '
              f'{statistics.mean(margen_5):.4f} (n={len(margen_5)})')
        print(f'  margen del MEJOR precio + exchanges : '
              f'{statistics.mean(margen_7):.4f} (n={len(margen_7)})')
        print(f'  arbitrajes (margen < 1): {arbitrajes}')
    if mejoras_mb:
        pos = sum(1 for x in mejoras_mb if x > 0)
        print(f'\n  Matchbook mejora al mejor de las casas en '
              f'{pos}/{len(mejoras_mb)} selecciones '
              f'({pos/len(mejoras_mb)*100:.1f} %), '
              f'media {statistics.mean(mejoras_mb)*100:+.2f} %')
    if mejoras_pm:
        pos = sum(1 for x in mejoras_pm if x > 0)
        print(f'  Polymarket mejora al mejor de las casas en '
              f'{pos}/{len(mejoras_pm)} selecciones '
              f'({pos/len(mejoras_pm)*100:.1f} %), '
              f'media {statistics.mean(mejoras_pm)*100:+.2f} %')

    # ---- 3. el caso accionable: exchange como ancla, Playdoit como precio --
    print('\n' + '-' * 78)
    print('3. ANCLA SIN MARGEN → VALOR EN LA CASA DEL USUARIO')
    print('-' * 78)
    print('  Precio justo = devig del exchange (que no cobra margen).')
    print('  Apuesta = la cuota de Playdoit, que es la que el usuario puede tomar.')
    hallazgos = []
    for clave, v in mb.items():
        pd_hit = pdt.get(clave) or cm._buscar(pdt, v['home'], v['away'])
        if not pd_hit:
            continue
        justas = cm.devig(v['cuotas'])
        for lado, prob in justas.items():
            precio = (pd_hit.get('cuotas') or {}).get(lado)
            if not precio or not prob:
                continue
            ev = precio * prob - 1
            if ev > 0.02:
                hallazgos.append((ev, v['home'], v['away'], lado, precio,
                                  round(1 / prob, 3)))
    hallazgos.sort(reverse=True)
    print(f'  partidos de Matchbook que también están en Playdoit: '
          f'{sum(1 for k in mb if k in pdt or cm._buscar(pdt, mb[k]["home"], mb[k]["away"]))}')
    print(f'  selecciones con EV > +2 % contra el ancla del exchange: '
          f'{len(hallazgos)}')
    for ev, h, a, lado, precio, justa in hallazgos[:12]:
        print(f'    {ev*100:+5.1f} %  {h} vs {a} · {lado:<5} '
              f'Playdoit {precio} vs justa {justa}')

    with open('_v114_exchanges_medicion.json', 'w', encoding='utf-8') as f:
        json.dump({'cobertura': cobertura, 'mejor_precio': gana,
                   'n_comunes': n_comunes, 'arbitrajes': arbitrajes,
                   'margen_4casas': (statistics.mean(margen_5)
                                     if margen_5 else None),
                   'margen_con_exchanges': (statistics.mean(margen_7)
                                            if margen_7 else None),
                   'ev_playdoit_vs_ancla': len(hallazgos)},
                  f, ensure_ascii=False, indent=2)
    print('\nDetalle en _v114_exchanges_medicion.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
