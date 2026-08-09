#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — Profundización en las tres candidatas que SÍ respondieron.

El sondeo (`_v114_sondeo_casas.py`) dejó tres vivas y descartó el resto con
motivo medido. Aquí se comprueba lo único que importa después de «responde»:
**¿cubren los partidos que apostamos, y con qué precio?**

  · Matchbook — EXCHANGE. Es la sorpresa: la v76 lo descartó por un 403 de
    Cloudflare y hoy devuelve 200 desde México. Si trae fútbol con libro de
    órdenes, es el sustituto conceptual de Betfair que la v113 pedía.
  · Polymarket — mercado de predicción con CLOB. El sondeo lo marcó «sin
    cuotas» porque publica PROBABILIDAD (0,52), no cuota decimal, y el
    detector buscaba cuotas. Hay que mirarlo de cerca.
  · Kalshi — mercado regulado en EE. UU., lectura sin clave.

Lo que se mide, por fuente:
  · cuántos eventos de fútbol trae y de qué competiciones,
  · si el precio es back/lay (exchange) o único,
  · el MARGEN implícito (suma de probabilidades): es la cifra que decide.
    Referencias medidas del proyecto: 1,0550 la media de las casas, 1,0311
    Pinnacle, 1,0034 el mejor de 18 casas, 1,0574 nuestras cinco.

    python _v114_profundizar.py
"""
import json
import sys

import requests

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0 Safari/537.36'),
      'Accept': 'application/json, text/plain, */*'}


def jget(url, params=None, headers=None, timeout=30):
    try:
        r = requests.get(url, params=params, headers={**UA, **(headers or {})},
                         timeout=timeout)
        if r.status_code != 200:
            return {'_error': f'HTTP {r.status_code}', '_texto': r.text[:200]}
        return r.json()
    except Exception as e:
        return {'_error': f'{type(e).__name__}: {str(e)[:150]}'}


# ---------------------------------------------------------------------------
def matchbook():
    print('=' * 78)
    print('MATCHBOOK — exchange (back/lay). La v76 lo descartó por 403.')
    print('=' * 78)
    lk = jget('https://www.matchbook.com/edge/rest/lookups/sports')
    if isinstance(lk, dict) and lk.get('_error'):
        print(f"  lookups: {lk['_error']}")
        deportes = []
    else:
        deportes = lk if isinstance(lk, list) else (lk.get('sports') or [])
        print(f"  deportes publicados: {len(deportes)}")
        for d in deportes[:30]:
            print(f"    id={d.get('id'):<6} {d.get('name')}")
    ids = {str(d.get('name', '')).lower(): d.get('id') for d in deportes}
    sid = ids.get('soccer') or ids.get('football') or 15
    print(f"\n  → probando eventos de fútbol (sport-id={sid}) CON precios")
    ev = jget('https://www.matchbook.com/edge/rest/events',
              {'sport-ids': sid, 'states': 'open', 'include-prices': 'true',
               'price-depth': 3, 'odds-type': 'DECIMAL',
               'exchange-type': 'back-lay', 'currency': 'EUR',
               'per-page': 50, 'offset': 0})
    if ev.get('_error'):
        print(f"  {ev['_error']} — {ev.get('_texto','')}")
        return None
    eventos = ev.get('events') or []
    print(f"  eventos: {len(eventos)} (total declarado {ev.get('total')})")
    con_precio, ligas = 0, {}
    muestra = None
    for e in eventos:
        ligas[e.get('meta-tags', [{}])[0].get('name') if e.get('meta-tags')
              else e.get('name')] = 1
        for m in (e.get('markets') or []):
            runners = m.get('runners') or []
            precios = [r for r in runners if r.get('prices')]
            if len(precios) >= 2:
                con_precio += 1
                if muestra is None:
                    muestra = (e, m)
                break
    print(f"  eventos con mercado y precios: {con_precio}")
    if muestra:
        e, m = muestra
        print(f"\n  EJEMPLO — {e.get('name')}  ({e.get('start')})")
        print(f"    mercado: {m.get('name')} · tipo {m.get('market-type')}")
        implicita = 0.0
        for r in (m.get('runners') or []):
            backs = [p for p in (r.get('prices') or [])
                     if p.get('side') == 'back']
            lays = [p for p in (r.get('prices') or [])
                    if p.get('side') == 'lay']
            b = max((p.get('odds') or 0) for p in backs) if backs else None
            l = min((p.get('odds') or 0) for p in lays) if lays else None
            if b:
                implicita += 1.0 / b
            print(f"      {r.get('name'):<28} back {b}  lay {l}  "
                  f"(vol {r.get('volume')})")
        if implicita:
            print(f"    → margen implícito del mejor BACK: {implicita:.4f}  "
                  f"(Pinnacle 1,0311 · nuestras 5 casas 1,0574)")
    return eventos


# ---------------------------------------------------------------------------
def polymarket():
    print('\n' + '=' * 78)
    print('POLYMARKET — mercado de predicción con libro de órdenes')
    print('=' * 78)
    # los mercados deportivos se etiquetan por serie/deporte; se busca por texto
    j = jget('https://gamma-api.polymarket.com/events',
             {'closed': 'false', 'limit': 200, 'order': 'volume24hr',
              'ascending': 'false'})
    if isinstance(j, dict) and j.get('_error'):
        print(f"  {j['_error']}")
        return None
    eventos = j if isinstance(j, list) else (j.get('data') or [])
    print(f"  eventos abiertos (top volumen): {len(eventos)}")
    claves = ('soccer', 'football', 'premier', 'laliga', 'la liga', 'nba',
              'mlb', 'liga mx', 'champions', 'serie a', 'bundesliga',
              'tennis', 'atp', 'wta', 'ufc', 'nfl')
    deportivos = [e for e in eventos
                  if any(k in json.dumps(e.get('tags') or [], default=str).lower()
                         or k in str(e.get('title', '')).lower() for k in claves)]
    print(f"  con pinta de deporte: {len(deportivos)}")
    for e in deportivos[:12]:
        mk = (e.get('markets') or [])
        print(f"    · {str(e.get('title'))[:62]:<62} mercados={len(mk)} "
              f"vol24h={e.get('volume24hr')}")
    if deportivos:
        e = deportivos[0]
        m = (e.get('markets') or [None])[0]
        if m:
            print(f"\n  EJEMPLO — {e.get('title')}")
            try:
                outs = json.loads(m.get('outcomes') or '[]')
                pr = [float(x) for x in json.loads(m.get('outcomePrices') or '[]')]
            except Exception:
                outs, pr = [], []
            suma = sum(pr)
            for o, p in zip(outs, pr):
                print(f"      {o:<20} prob {p:.4f}  → cuota "
                      f"{(1/p if p else 0):.3f}")
            if suma:
                print(f"    → suma de probabilidades: {suma:.4f} "
                      f"(1,0000 = sin margen)")
            print(f"      bestBid={m.get('bestBid')} bestAsk={m.get('bestAsk')} "
                  f"spread={m.get('spread')}")
    return deportivos


# ---------------------------------------------------------------------------
def kalshi():
    print('\n' + '=' * 78)
    print('KALSHI — mercado regulado (EE. UU.), lectura sin clave')
    print('=' * 78)
    j = jget('https://api.elections.kalshi.com/trade-api/v2/markets',
             {'limit': 200, 'status': 'open'})
    if j.get('_error'):
        print(f"  {j['_error']}")
        return None
    mk = j.get('markets') or []
    print(f"  mercados abiertos en la primera página: {len(mk)}")
    series = {}
    for m in mk:
        s = str(m.get('ticker', '')).split('-')[0]
        series[s] = series.get(s, 0) + 1
    dep = {s: n for s, n in series.items()
           if any(k in s.upper() for k in ('NBA', 'MLB', 'NFL', 'EPL', 'SOCCER',
                                           'UEFA', 'ATP', 'WTA', 'TENNIS',
                                           'LIGAMX', 'NHL', 'UFC'))}
    print(f"  series presentes: {len(series)} · con pinta de deporte: {len(dep)}")
    for s, n in sorted(dep.items(), key=lambda x: -x[1])[:15]:
        print(f"    · {s:<18} {n} mercados")
    ej = next((m for m in mk if any(k in str(m.get('ticker', '')).upper()
                                    for k in ('NBA', 'MLB', 'EPL', 'NFL'))), None)
    if ej is None and mk:
        ej = mk[0]
    if ej:
        print(f"\n  EJEMPLO — {ej.get('ticker')}: {str(ej.get('title'))[:60]}")
        ya, yb = ej.get('yes_ask'), ej.get('yes_bid')
        print(f"      yes_bid={yb}¢  yes_ask={ya}¢  volumen={ej.get('volume')}")
        if ya:
            print(f"      → cuota de comprar SÍ al ask: {100/ya:.3f}")
        if yb and ya:
            print(f"      → suma implícita bid/ask: "
                  f"{(ya + (100 - yb))/100:.4f} (1,0000 = sin margen)")
    return mk


if __name__ == '__main__':
    res = {'matchbook': bool(matchbook()), 'polymarket': bool(polymarket()),
           'kalshi': bool(kalshi())}
    print('\n' + '=' * 78)
    print('RESUMEN:', json.dumps(res))
