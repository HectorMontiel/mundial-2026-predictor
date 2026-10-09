#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v344 — los patrones de liga del usuario, CONTRA EL PRECIO.

Lo que dice la transcripción:
  MLS      «mínimo más de 1,5 en todos; ambos anotan; muchos empates (va
           ganando uno y el otro empata); los córners se farmean»
  Liga MX  «tarjetas amarillas; goles de los favoritos (América, Cruz Azul,
           Monterrey…)»

Que un patrón sea frecuente no lo hace apostable: la casa ya lo cobra. Se
mide de dos formas:

  A. HISTÓRICO LARGO (2021-2026, Pinnacle 1X2 y estadística de ESPN): la
     frecuencia en esa liga contra el resto, y para el empate y el favorito,
     contra la probabilidad de Pinnacle sin margen.
  B. CONTRA PLAYDOIT (las fotos de `mercado_dia.json` desde el 24-ago):
     apostar el patrón en TODOS los partidos de la liga, a la cuota de la
     casa, y ver el acierto contra lo que la casa promete y el rendimiento,
     con bootstrap por partido.
"""
import ast
import json
import subprocess

import numpy as np
import pandas as pd

import _v344_precio as P

rng = np.random.default_rng(3442)
GRANDES_MX = ('america', 'cruzazul', 'monterrey', 'tigres', 'toluca', 'pumas',
              'chivas', 'guadalajara', 'pachuca', 'leon')
CACHE = '_v344_tableros_todo.pkl'


def tableros_todo():
    try:
        return pd.read_pickle(CACHE)
    except Exception:
        pass
    hs = subprocess.run(['git', 'log', '--format=%H %cI', 'origin/main', '--',
                         'mercado_dia.json'], capture_output=True, text=True).stdout
    filas = []
    for linea in [x for x in hs.split('\n') if x.strip()]:
        h, cuando = linea.split()
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':mercado_dia.json'],
                                          capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        ts = pd.Timestamp(cuando).tz_convert('UTC').tz_localize(None)
        for v in (d.get('partidos') or {}).values():
            if isinstance(v, dict) and v.get('clave_liga') in ('mls', 'liga_mx', 'brasil'):
                filas.append((ts, v.get('clave_liga'), v.get('home'), v.get('away'), v))
    t = pd.DataFrame(filas, columns=['ts', 'liga', 'home', 'away', 'board'])
    t['h'] = t.home.map(P._norm)
    t['a'] = t.away.map(P._norm)
    t.to_pickle(CACHE)
    return t


def _d(x):
    if isinstance(x, str):
        try:
            return ast.literal_eval(x)
        except Exception:
            return {}
    return x or {}


def _ok(v):
    """Una línea con sus dos cuotas, o None (hay fotos viejas sin precio)."""
    return v if isinstance(v, dict) and v.get('mas') and v.get('menos') else None


def historico(liga):
    d = pd.read_csv('historico_%s.csv' % liga, low_memory=False)
    d['fecha'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['home_goals', 'away_goals'])
    d = d[d.fecha >= '2021-01-01']
    return d


def frecuencias():
    """A: cuánto pasa cada cosa en cada liga (y el empate contra Pinnacle)."""
    out = {}
    for lg in ('mls', 'liga_mx', 'brasil', 'premier', 'laliga', 'bundesliga',
               'serie_a', 'usl_championship'):
        d = historico(lg)
        g = d.home_goals + d.away_goals
        r = {'partidos': len(d), 'mas_1.5': round(float((g > 1.5).mean()), 3),
             'ambos': round(float(((d.home_goals > 0) & (d.away_goals > 0)).mean()), 3),
             'empate': round(float((d.home_goals == d.away_goals).mean()), 3)}
        e = d[d.stats_origen == 'espn'] if 'stats_origen' in d else d.iloc[:0]
        if len(e):
            r['corners'] = round(float((e.home_corners + e.away_corners).mean()), 2)
            r['amarillas'] = round(float((e.home_yellow + e.away_yellow).mean()), 2)
        pin = ['odd_draw_pin', 'odd_home_pin', 'odd_away_pin']
        o = d.dropna(subset=pin) if set(pin) <= set(d.columns) else d.iloc[:0]
        if len(o) > 200:
            inv = 1 / o[['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']]
            pe = inv.odd_draw_pin / inv.sum(axis=1)
            emp = (o.home_goals == o.away_goals).astype(int)
            gan = emp * o.odd_draw_pin - 1
            r['empate_pinnacle'] = {'n': len(o), 'promete': round(float(pe.mean()), 3),
                                    'real': round(float(emp.mean()), 3),
                                    'roi_a_pinnacle': round(float(gan.mean()), 4)}
        out[lg] = r
    # favoritos grandes de la Liga MX contra Pinnacle (ganar)
    d = historico('liga_mx').dropna(subset=['odd_home_pin', 'odd_away_pin', 'odd_draw_pin'])
    filas = []
    for lado, otro in (('home', 'away'), ('away', 'home')):
        x = d[[P._norm(t) in GRANDES_MX or any(gm in P._norm(t) for gm in GRANDES_MX)
               for t in d['%s_team' % lado]]]
        inv = 1 / x[['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']]
        p = (1 / x['odd_%s_pin' % lado]) / inv.sum(axis=1)
        x = x[p >= 0.5]
        p = p[p >= 0.5]
        gana = (x['%s_goals' % lado] > x['%s_goals' % otro]).astype(int)
        filas.append(pd.DataFrame({'p': p, 'gana': gana,
                                   'cuota': x['odd_%s_pin' % lado],
                                   'goles': x['%s_goals' % lado]}))
    f = pd.concat(filas)
    out['liga_mx_grandes_favoritos'] = {
        'n': len(f), 'pinnacle_promete_gana': round(float(f.p.mean()), 3),
        'gana_real': round(float(f.gana.mean()), 3),
        'roi_gana_a_pinnacle': round(float((f.gana * f.cuota - 1).mean()), 4),
        'mete_1+': round(float((f.goles >= 1).mean()), 3),
        'mete_2+': round(float((f.goles >= 2).mean()), 3)}
    return out


def _boot(gan, mids):
    um, inv = np.unique(mids, return_inverse=True)
    s, n = np.bincount(inv, weights=gan), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in
          (rng.integers(0, len(um), len(um)) for _ in range(3000))]
    return round(float(np.percentile(bs, 5)), 4)


def contra_playdoit():
    """B: apostar el patrón en todos los partidos, a la cuota de Playdoit."""
    tab = tableros_todo()
    res = {}
    for lg in ('mls', 'liga_mx', 'brasil'):
        d = historico(lg)
        d = d[d.fecha >= P.DESDE].copy()
        d['mid'] = np.arange(len(d))
        prox = pd.DataFrame({'mid': d.mid, 'liga': lg, 'fecha': d.fecha,
                             'equipo': d.home_team, 'rival': d.away_team})
        casa = P.emparejar(prox, tab[tab.liga == lg])
        apuestas = {}

        def apunta(nombre, mid, y, cuota, p_casa):
            apuestas.setdefault(nombre, []).append((mid, y, cuota, p_casa))
        for r in d.itertuples():
            b = casa.get(r.mid)
            if b is None:
                continue
            gh, ga = r.home_goals, r.away_goals
            # más de 1,5
            g15 = _ok(_d(b.get('goles')).get('1.5'))
            if g15:
                pc = (1 / g15['mas']) / (1 / g15['mas'] + 1 / g15['menos'])
                apunta('más de 1,5', r.mid, int(gh + ga > 1.5), g15['mas'], pc)
            bt = _d(b.get('btts_cuotas'))
            if bt.get('si') and bt.get('no'):
                pc = (1 / bt['si']) / (1 / bt['si'] + 1 / bt['no'])
                apunta('ambos anotan', r.mid, int(gh > 0 and ga > 0), bt['si'], pc)
            x = _d(b.get('1x2_cuotas'))
            if x.get('draw'):
                s = sum(1 / x[k] for k in ('home', 'draw', 'away') if x.get(k))
                apunta('empate', r.mid, int(gh == ga), x['draw'], (1 / x['draw']) / s)
            # córners y tarjetas: la línea más pareja, «más»
            if getattr(r, 'stats_origen', '') == 'espn':
                for mk, real in (('corners', r.home_corners + r.away_corners),
                                 ('tarjetas', r.home_yellow + r.away_yellow
                                  + 2 * (r.home_red + r.away_red))):
                    ls = {k: v for k, v in _d(b.get(mk)).items() if _ok(v)}
                    if not ls or pd.isna(real):
                        continue
                    L, v = min(ls.items(), key=lambda kv: abs(kv[1].get('p', 0.5) - 0.5))
                    pc = (1 / v['mas']) / (1 / v['mas'] + 1 / v['menos'])
                    apunta('%s: más (línea pareja)' % mk, r.mid, int(real > float(L)),
                           v['mas'], pc)
            # goles del favorito grande (Liga MX)
            if lg == 'liga_mx' and x.get('home') and x.get('away'):
                for lado, eq, gol in (('home', r.home_team, gh), ('away', r.away_team, ga)):
                    n = P._norm(eq)
                    if not any(gm in n for gm in GRANDES_MX):
                        continue
                    if x[lado] > min(x['home'], x['away']):
                        continue                      # sólo si es el favorito
                    ge = _ok(_d(b.get('goles_%s' % lado)).get('0.5'))
                    if ge:
                        pc = (1 / ge['mas']) / (1 / ge['mas'] + 1 / ge['menos'])
                        apunta('favorito grande mete gol', r.mid, int(gol > 0.5), ge['mas'], pc)
                    ge = _ok(_d(b.get('goles_%s' % lado)).get('1.5'))
                    if ge:
                        pc = (1 / ge['mas']) / (1 / ge['mas'] + 1 / ge['menos'])
                        apunta('favorito grande mete 2+', r.mid, int(gol > 1.5), ge['mas'], pc)
        res[lg] = {'partidos_con_tablero': len(casa)}
        for nombre, lst in apuestas.items():
            a = np.array(lst, dtype=float)
            gan = a[:, 1] * a[:, 2] - 1
            res[lg][nombre] = {'n': len(a), 'casa_promete': round(float(a[:, 3].mean()), 3),
                               'real': round(float(a[:, 1].mean()), 3),
                               'cuota_media': round(float(a[:, 2].mean()), 3),
                               'roi': round(float(gan.mean()), 4),
                               'p5': _boot(gan, a[:, 0])}
    return res


if __name__ == '__main__':
    out = {'historico': frecuencias(), 'contra_playdoit': contra_playdoit()}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open('_v344_patrones.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
