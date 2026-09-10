#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v190 - ¿SIRVEN LAS CUOTAS DE ESPN COMO LINEA DE CIERRE?

football-data.co.uk lleva caido (503 en todo el sitio) y de ahi salian las
columnas `odd_*` de los historicos, que son las que `odds_store` importa como
fase «cierre». Sin ellas, los partidos nuevos entran en el ledger sin precio.

El `summary` de ESPN -que este proyecto YA descarga para cada partido, en
`stats_espn._fila_de_evento`- trae `pickcenter` con la linea de DraftKings.
Coste de red adicional: cero.

Antes de enchufarlo hay que saber cuanto se parece a los cierres que ya
tenemos. Se compara en probabilidad implicita, que es como se usa, y se mira
tambien el sobreredondeo: una linea con 5 % de margen y otra con 13 % no son
la misma cosa aunque acierten al favorito.
"""
import io
import statistics
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{code}'
CABEZ = {'User-Agent': 'Mozilla/5.0'}
MAX = 60


def decimal(ml):
    """Americana -> decimal. None si no se puede."""
    try:
        m = float(ml)
    except (TypeError, ValueError):
        return None
    if m == 0:
        return None
    return 1.0 + (100.0 / abs(m) if m < 0 else m / 100.0)


def main():
    import requests
    import pandas as pd
    import config_ligas_espn as cle

    liga = 'laliga'
    code = (cle.ESPN_CODIGOS.get(liga) if hasattr(cle, 'ESPN_CODIGOS')
            else None) or 'esp.1'
    d = pd.read_csv('historico_%s.csv' % liga, low_memory=False)
    d = d.dropna(subset=['odd_home', 'odd_draw', 'odd_away'])
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date']).sort_values('date').tail(400)
    print('partidos de %s con cierre de football-data: %d' % (liga, len(d)))
    print('  rango: %s -> %s' % (str(d['date'].min())[:10],
                                 str(d['date'].max())[:10]))
    print()

    ses = requests.Session()
    ses.headers.update(CABEZ)
    pares, sin_odds, sin_evento = [], 0, 0

    # se recorre por dia: un scoreboard trae todos los partidos de esa fecha
    for dia, grupo in list(d.groupby(d['date'].dt.strftime('%Y%m%d')))[-40:]:
        if len(pares) >= MAX:
            break
        try:
            r = ses.get(BASE.format(code=code) + '/scoreboard?dates=%s' % dia,
                        timeout=25)
            evs = (r.json() or {}).get('events') or []
        except Exception:
            continue
        for ev in evs:
            if len(pares) >= MAX:
                break
            try:
                s = ses.get(BASE.format(code=code) + '/summary?event=%s'
                            % ev['id'], timeout=25).json()
            except Exception:
                continue
            pc = (s.get('pickcenter') or s.get('odds') or [])
            if not pc:
                sin_odds += 1
                continue
            p = pc[0]
            h = decimal(((p.get('homeTeamOdds') or {}).get('moneyLine')))
            x = decimal(((p.get('drawOdds') or {}).get('moneyLine')))
            a = decimal(((p.get('awayTeamOdds') or {}).get('moneyLine')))
            if not (h and x and a):
                sin_odds += 1
                continue
            comp = ((ev.get('competitions') or [{}])[0])
            eqs = comp.get('competitors') or []
            nom = {}
            for c in eqs:
                nom[c.get('homeAway')] = ((c.get('team') or {})
                                          .get('displayName') or '')
            # se casa por fecha + goles, que es lo unico comun sin mapear
            try:
                gh = int((eqs[0] or {}).get('score'))
                ga = int((eqs[1] or {}).get('score'))
            except (TypeError, ValueError):
                continue
            fecha = str(ev.get('date') or '')[:10]
            cand = d[(d['date'].dt.strftime('%Y-%m-%d') == fecha)
                     & (d['home_goals'] == (gh if eqs[0].get('homeAway') == 'home' else ga))
                     & (d['away_goals'] == (ga if eqs[0].get('homeAway') == 'home' else gh))]
            if len(cand) != 1:
                sin_evento += 1
                continue
            f = cand.iloc[0]
            pares.append((float(f['odd_home']), float(f['odd_draw']),
                          float(f['odd_away']), h, x, a))
        time.sleep(0.1)

    print('partidos emparejados: %d  (sin cuotas en ESPN: %d, sin casar: %d)'
          % (len(pares), sin_odds, sin_evento))
    if len(pares) < 15:
        print('MUESTRA CORTA: no se decide nada con esto.')
        return 1

    crudo, norm, ov_e, ov_f, gana = [], [], [], [], 0
    for fh, fx, fa, eh, ex, ea in pares:
        pf = [1 / fh, 1 / fx, 1 / fa]
        pe = [1 / eh, 1 / ex, 1 / ea]
        sf, se_ = sum(pf), sum(pe)
        ov_f.append(sf)
        ov_e.append(se_)
        crudo += [abs(x - y) for x, y in zip(pe, pf)]
        norm += [abs(x / se_ - y / sf) for x, y in zip(pe, pf)]
        if pe.index(max(pe)) == pf.index(max(pf)):
            gana += 1

    print()
    print('SOBREREDONDEO (margen de la casa)')
    print('  football-data  %.4f' % statistics.mean(ov_f))
    print('  ESPN/DraftKings %.4f' % statistics.mean(ov_e))
    print()
    print('ERROR CONTRA EL CIERRE, en probabilidad implicita')
    print('  crudo        medio %.4f   p90 %.4f'
          % (statistics.mean(crudo), sorted(crudo)[int(0.9 * len(crudo))]))
    print('  normalizado  medio %.4f   p90 %.4f'
          % (statistics.mean(norm), sorted(norm)[int(0.9 * len(norm))]))
    print('  mismo favorito: %d de %d (%.0f%%)'
          % (gana, len(pares), 100.0 * gana / len(pares)))
    print()
    print('REFERENCIA: la foto de Playdoit daba 0,0234 normalizado (p90 0,0602)')
    print('y por eso se descarto: el CLV medio del proyecto es -2,78 %, o sea')
    print('que el error era del tamaño de la señal.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
