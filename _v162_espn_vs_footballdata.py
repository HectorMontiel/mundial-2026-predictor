# -*- coding: utf-8 -*-
"""
v162 - ¿SON CIERTOS LOS NUMEROS DEL BOXSCORE DE ESPN?

El boxscore trae wonCorners, yellowCards, redCards, foulsCommitted... para
ligas que hoy no tienen esas columnas. Antes de construir NADA encima hay que
comprobar que no es otro relleno: se cruzan los MISMOS partidos contra
football-data, que es la fuente observada del proyecto.

Si coinciden, ESPN es fuente valida y las 42 ligas sin datos dejan de
necesitar imputacion. Si no coinciden, hay que saberlo ahora y no dentro de
tres semanas.

Se cruza por (fecha, equipos) con el emparejador del proyecto.
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

UA = {'User-Agent': 'Mozilla/5.0'}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def stats_de(code, event_id):
    """{'home': {...}, 'away': {...}} con las estadisticas del boxscore."""
    try:
        su = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                 'summary?event=%s' % (code, event_id))
    except Exception:
        return None
    box = su.get('boxscore') or {}
    equipos = box.get('teams') or []
    if len(equipos) < 2:
        return None
    salida = {}
    for t in equipos:
        lado = (t.get('homeAway') or '').lower()
        if lado not in ('home', 'away'):
            continue
        d = {}
        for st in (t.get('statistics') or []):
            n = st.get('name')
            v = st.get('displayValue')
            if n is None:
                continue
            try:
                d[n] = float(str(v).replace('%', ''))
            except (TypeError, ValueError):
                pass
        d['_equipo'] = ((t.get('team') or {}).get('displayName') or '')
        salida[lado] = d
    return salida if len(salida) == 2 else None


LIGAS = [('premier', 'eng.1'), ('laliga', 'esp.1'), ('serie_a', 'ita.1'),
         ('bundesliga', 'ger.1'), ('ligue_1', 'fra.1'), ('eredivisie', 'ned.1')]
VENTANA = '20260501-20260822'

import name_mapper

filas = []
for clave, code in LIGAS:
    try:
        d = pd.read_csv('historico_%s.csv' % clave, low_memory=False)
    except Exception as e:
        print('  %s: %s' % (clave, e))
        continue
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    try:
        sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                 'scoreboard?dates=%s&limit=500' % (code, VENTANA))
    except Exception as e:
        print('  %s scoreboard: %s' % (clave, e))
        continue
    evs = [e for e in (sb.get('events') or [])
           if (((e.get('status') or {}).get('type') or {}).get('state') == 'post')]
    print('%s: %d partidos jugados en ESPN' % (clave, len(evs)))

    catalogo = sorted(set(d['home_team'].dropna().astype(str)))

    def _uno(ev):
        try:
            comp = ev['competitions'][0]
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            fecha = pd.to_datetime(ev['date'])
            if fecha.tzinfo:
                fecha = fecha.tz_convert(None)
            h = name_mapper.mapear(loc['team']['displayName'], catalogo)
            a = name_mapper.mapear(vis['team']['displayName'], catalogo)
            if not h or not a:
                return None
            dia = fecha.normalize()
            fila = d[(d['home_team'] == h) & (d['away_team'] == a)
                     & (d['date'].dt.normalize().between(
                         dia - pd.Timedelta(days=1), dia + pd.Timedelta(days=1)))]
            if fila.empty:
                return None
            fila = fila.iloc[0]
            st = stats_de(code, ev.get('id'))
            if not st:
                return None
            return {
                'clave': clave, 'partido': '%s-%s' % (h, a),
                'ck_h_espn': st['home'].get('wonCorners'),
                'ck_h_fd': pd.to_numeric(fila.get('home_corners'), errors='coerce'),
                'ck_a_espn': st['away'].get('wonCorners'),
                'ck_a_fd': pd.to_numeric(fila.get('away_corners'), errors='coerce'),
                'am_h_espn': st['home'].get('yellowCards'),
                'am_h_fd': pd.to_numeric(fila.get('home_yellow'), errors='coerce'),
                'am_a_espn': st['away'].get('yellowCards'),
                'am_a_fd': pd.to_numeric(fila.get('away_yellow'), errors='coerce'),
                'ro_h_espn': st['home'].get('redCards'),
                'ro_h_fd': pd.to_numeric(fila.get('home_red'), errors='coerce'),
                'ti_h_espn': st['home'].get('totalShots'),
                'ti_h_fd': (pd.to_numeric(fila.get('home_shots_on'), errors='coerce')
                            + pd.to_numeric(fila.get('home_shots_off'), errors='coerce')),
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(_uno, evs):
            if r:
                filas.append(r)

t = pd.DataFrame(filas)
if t.empty:
    print('sin cruces')
    raise SystemExit

print()
print('=' * 74)
print('CRUCES: %d partidos de %d competiciones' % (len(t), t['clave'].nunique()))
print()
print('%-14s %6s %8s %8s %8s %8s' % ('variable', 'n', 'iguales', 'media ESPN',
                                     'media FD', 'corr'))
PARES = [('corners local', 'ck_h_espn', 'ck_h_fd'),
         ('corners visit', 'ck_a_espn', 'ck_a_fd'),
         ('amarill local', 'am_h_espn', 'am_h_fd'),
         ('amarill visit', 'am_a_espn', 'am_a_fd'),
         ('rojas local  ', 'ro_h_espn', 'ro_h_fd'),
         ('remates local', 'ti_h_espn', 'ti_h_fd')]
for nombre, a, b in PARES:
    m = t[a].notna() & t[b].notna()
    if m.sum() < 5:
        print('%-14s %6d  (muestra insuficiente)' % (nombre, m.sum()))
        continue
    x, y = t.loc[m, a].astype(float), t.loc[m, b].astype(float)
    iguales = float((x == y).mean())
    corr = float(x.corr(y)) if x.std() and y.std() else float('nan')
    print('%-14s %6d %7.1f%% %9.2f %8.2f %8.3f'
          % (nombre, m.sum(), iguales * 100, x.mean(), y.mean(), corr))

print()
print('DESACUERDOS de corners (los 10 primeros):')
m = t['ck_h_espn'].notna() & t['ck_h_fd'].notna()
mal = t[m & (t['ck_h_espn'] != t['ck_h_fd'])]
print('  %d de %d' % (len(mal), int(m.sum())))
for _, r in mal.head(10).iterrows():
    print('   %-28s ESPN %s-%s  FD %s-%s'
          % (r['partido'][:28], r['ck_h_espn'], r['ck_a_espn'],
             r['ck_h_fd'], r['ck_a_fd']))

t.to_json('_v162_espn_vs_footballdata.json', orient='records', indent=1)
