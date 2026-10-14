#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — H3 · Contexto de equipo (desgaste, forma, tabla, copas) contra la casa.

El usuario (12-oct) quiere soñadoras de N patas (4 a 25+) eligiendo la cuota
mínima por pata (1,30 · 1,45 · 1,60 · 1,70 · 1,80, como el booster de Draftea
«cada selección ≥ 1,60, mínimo 4»), con patas sólidas y justificadas: «de
acuerdo con la casa, pero un paso adelante de la casa».

HIPÓTESIS (H3)
  Hay contextos del equipo en los que gana (o el partido tiene más / menos de
  2,5) MÁS de lo que dice la casa a cuota 1,45-1,80: ventaja de descanso o
  desgaste (días de descanso, partidos en 14 días, copa entre semana), presión
  de tabla al final de la temporada (descenso / título contra un rival sin nada
  en juego), forma reciente contra el precio (puntos de las últimas 5 menos los
  que la casa esperaba), rachas, equipos que vienen de perder, dominio de tiros
  a puerta, local / visita.

DATOS (todo local)
  A. `historico_*.csv`: las 36 ligas con cuotas (2010-2026, 125.721 partidos con
     cuota de la casa; Pinnacle en ~85 %; más/menos 2,5 en 20 ligas). Los
     rasgos se arman SÓLO con partidos anteriores, con TODOS los partidos de la
     liga (también los que no tienen cuota): forma (últimas 5 de la misma
     temporada), rachas, tabla antes de la jornada (temporada detectada por el
     parón largo del calendario, no por el año), descanso y partidos en 14
     días. Las copas (`champions`, `europa_league`, `conference_league`, FA
     Cup, Carabao, Copa del Rey, Copa do Brasil, Libertadores, Sudamericana,
     AFC) NO traen cuotas: sólo aportan fechas para el desgaste (2021→), con el
     nombre del equipo emparejado a su liga por texto (cobertura en el json).
     Patas: gana local / empate / gana visita, doble oportunidad DERIVADA
     (1X, X2, 12; cuota 1/(1/c1+1/c2), el mismo margen que el 1X2) y más /
     menos 2,5.
  B. `e_v361.pkl` (26 ligas, 2021-2026): el contexto que ya usa el Método
     Contexto (descanso, presión, zona alta / baja, ppg, forma de tiros
     exponencial `ew_*`), con la cuota 1X2 de la casa. Segunda comprobación,
     independiente de cómo se arman los rasgos en A.

PROTOCOLO
  Pisos 1,30 / 1,45 / 1,60 / 1,70 / 1,80 (cuota ≥ piso y ≤ piso + 0,5), por
  familia (ganador, doble, goles 2,5; «todo» junta las tres). LÍNEA BASE: «la
  casa elige» (la pata más probable para la casa sin margen, una por partido)
  en el mismo piso y familia. Regla de contexto: la casa elige, pero sólo
  entre las patas que cumplen el contexto (lista fija, escrita antes de mirar
  resultados). Dos mitades por fecha (la mediana de las patas de CADA regla;
  la base se mide en las mismas fechas), aparte 2023-07→, bootstrap POR
  PARTIDO (Poisson, emparejado regla↔base) para el p5 de:
    · la diferencia de ACIERTO contra la base (lo que pide el protocolo);
    · la diferencia de «exceso sobre la casa CALIBRADA» (acierto − la prob.
      de un árbol walk-forward entrenado SÓLO con la casa y el tipo de pata,
      que aprende el sesgo favorito-sorpresa): si sólo sube el acierto, la
      regla está escogiendo cuotas más bajas dentro de la ventana o
      favoritos que la casa proporcional infravalora, cosa que no necesita
      contexto. (También se guarda el exceso sobre la proporcional.)
  PASA = p5 > 0 en las dos mitades en LAS DOS diferencias. «Acierto por
  precio» = sólo la primera (pasa el protocolo, pero no le gana a la casa
  calibrada). Además un aprendiz walk-forward (logística y árbol HGB
  entrenados sólo con temporadas anteriores) con los rasgos + la casa: elige
  él, o la casa elige con su respaldo (aprendiz ≥ casa + u), y el CONTROL
  (la casa calibrada ≥ casa + u, sin contexto) para ver cuánto es sólo precio.
  Pinnacle (`REF …`) se mide como referencia: no es contexto de equipo.
  Boletos del día (una pata por partido, las N de mayor puntaje): N = 4, 6,
  10, 15, 25, enteros / días, rojas medias y ganancia por $100 sin booster y
  con ×1,2 / ×1,3 / ×1,8 sobre el momio.
Escribe `_v373_contexto.json`.
"""
import difflib
import glob
import json
import os
import re
import sys
import time
import unicodedata

import numpy as np
import pandas as pd

T0 = time.time()
rng = np.random.default_rng(373)
PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
ANCHO = 0.5
NB = 300
D2023 = np.datetime64('2023-07-01')
NS = (4, 6, 10, 15, 25)
BOOST = (1.0, 1.2, 1.3, 1.8)
RUTA_E = os.environ.get('V373_E', r'C:\Users\HMREY\AppData\Local\Temp\claude\D--Claude'
                        r'\ac0b7101-79c7-47ef-8aff-6775a8d6ea8b\scratchpad\e_v361.pkl')

CAL = {'mls', 'brasil', 'china', 'jpn_j1', 'suecia', 'noruega', 'finlandia', 'irlanda', 'argentina'}
SPLIT = {'liga_mx'}
SIN_TABLA = {'mls', 'liga_mx', 'argentina'}
EUR = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'eredivisie', 'primeira',
       'sco_premiership', 'bel_pro_league', 'turquia', 'gre_super_league', 'aut_bundesliga',
       'dinamarca', 'suiza', 'noruega', 'suecia', 'polonia', 'rumania', 'rus_premier', 'finlandia',
       'irlanda', 'eng_championship', 'ger_bundesliga2', 'esp_hypermotion', 'ita_serie_b',
       'fra_ligue2', 'sco_championship']
ING = ['premier', 'eng_championship', 'eng_league_one', 'eng_league_two', 'eng_national']
COPAS = {'champions': EUR, 'europa_league': EUR, 'conference_league': EUR, 'eng_fa_cup': ING,
         'eng_carabao': ING, 'esp_copa_rey': ['laliga', 'esp_hypermotion'], 'bra_copa': ['brasil'],
         'libertadores': ['brasil', 'argentina'], 'sudamericana': ['brasil', 'argentina'],
         'afc_champions': ['jpn_j1', 'china']}
COLS = ['date', 'home_team', 'away_team', 'home_goals', 'away_goals', 'odd_home', 'odd_draw',
        'odd_away', 'odd_home_pin', 'odd_draw_pin', 'odd_away_pin', 'odd_over25', 'odd_under25',
        'home_shots_on', 'away_shots_on']


def log(*a):
    print('[%5.0fs]' % (time.time() - T0), *a, flush=True)


# ===================================================================== carga
def leer(f, cols):
    cab = pd.read_csv(f, nrows=0).columns
    d = pd.read_csv(f, usecols=[c for c in cols if c in cab], low_memory=False)
    for c in cols:
        if c not in d:
            d[c] = np.nan
    d['fecha'] = pd.to_datetime(d['date'], errors='coerce', format='mixed').dt.normalize()
    return d


def cargar_ligas():
    filas = []
    for f in sorted(glob.glob('historico_*.csv')):
        liga = f[len('historico_'):-4]
        if liga in COPAS:
            continue
        cab = set(pd.read_csv(f, nrows=0).columns)
        if not {'date', 'home_team', 'away_team', 'home_goals', 'away_goals', 'odd_home'} <= cab:
            continue
        d = leer(f, COLS)
        for c in COLS[3:]:
            d[c] = pd.to_numeric(d[c], errors='coerce')
        if ((d.odd_home > 1) & (d.odd_draw > 1) & (d.odd_away > 1)).sum() < 300:
            continue
        d['liga'] = liga
        filas.append(d)
    d = pd.concat(filas, ignore_index=True)
    d = d.dropna(subset=['fecha', 'home_team', 'away_team', 'home_goals', 'away_goals'])
    d = d.drop_duplicates(subset=['liga', 'fecha', 'home_team', 'away_team']).reset_index(drop=True)
    d['mid'] = d.liga + '|' + d.index.astype(str)
    return d


def temporadas(d):
    """Temporada = tramo entre los parones largos de cada liga (no el año)."""
    # Ventana donde cae el parón entre temporadas. En las europeas se toma el
    # ÚLTIMO hueco ≥ 30 días (el de la pandemia, marzo-junio 2020, va antes del
    # verano); en las de año natural el PRIMERO (la pandemia va después).
    vent = {'cal': [((10, 1), (3, 31))], 'split': [((3, 1), (7, 31)), ((10, 15), (1, 20))],
            'eur': [((3, 1), (9, 30))]}
    out = pd.Series(0, index=d.index, dtype=np.int64)
    for liga, g in d.groupby('liga'):
        fechas = np.array(sorted(g.fecha.unique()), dtype='datetime64[D]')
        gaps = np.diff(fechas).astype(int)
        tipo = 'cal' if liga in CAL else 'split' if liga in SPLIT else 'eur'
        cortes = []
        for y in range(fechas[0].astype(object).year - 1, fechas[-1].astype(object).year + 1):
            for (m1, d1), (m2, d2) in vent[tipo]:
                ini = np.datetime64('%04d-%02d-%02d' % (y, m1, d1))
                fin = np.datetime64('%04d-%02d-%02d' % (y + (1 if (m2, d2) < (m1, d1) else 0), m2, d2))
                ix = np.where((fechas[:-1] >= ini) & (fechas[:-1] <= fin))[0]
                if len(ix) == 0:
                    continue
                largos = ix[gaps[ix] >= 30]
                if tipo == 'eur' and len(largos):
                    k = largos[-1]
                elif tipo == 'cal' and len(largos):
                    k = largos[0]
                else:
                    k = ix[np.argmax(gaps[ix])]
                if gaps[k] >= 14:
                    cortes.append(fechas[k + 1])
        cortes = np.array(sorted(set(cortes)), dtype='datetime64[D]')
        out[g.index] = np.searchsorted(cortes, g.fecha.values.astype('datetime64[D]'), side='right')
    return out


# ============================================================ copas → ligas
STOP = {'fc', 'afc', 'cf', 'sc', 'ac', 'fk', 'sk', 'as', 'ss', 'us', 'cd', 'ud', 'sd', 'rc', 'rcd',
        'club', 'de', 'sv', 'vfb', 'vfl', 'tsg', 'bsc', 'calcio', 'cp', 'fbc', 'if', 'bk', 'ik', 'ff',
        'ca', 'ec', 'the', 'and', 'da', 'do', 'del', 'la', 'el', 'esporte', 'futebol', 'clube',
        'football', 'sad', 'ssc', 'osc', 'kv', 'krc', 'rsc', 'sporting'}
ALIAS_TXT = {'ath madrid': 'atletico madrid', 'ath bilbao': 'athletic club bilbao',
             'man city': 'manchester city', 'man united': 'manchester united',
             "nott'm forest": 'nottingham forest', 'paris sg': 'paris saint germain',
             "m'gladbach": 'borussia monchengladbach', 'ein frankfurt': 'eintracht frankfurt',
             'wolves': 'wolverhampton wanderers', 'sp lisbon': 'sporting lisbon cp',
             'sp braga': 'braga', 'inter': 'internazionale', 'spurs': 'tottenham'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower().strip()
    s = ALIAS_TXT.get(s, s).replace("'", '')
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return [w for w in s.split() if w not in STOP]


def mapear_copas(d):
    """Cada equipo de copa → (liga, equipo) de una liga candidata activa esos años."""
    activos = {}
    for liga, g in d.groupby('liga'):
        for col in ('home_team', 'away_team'):
            for eq, y in zip(g[col], g.fecha.dt.year):
                activos.setdefault(liga, {}).setdefault(eq, set()).add(y)
    citas, info = [], {}
    for copa, ligas in COPAS.items():
        f = 'historico_%s.csv' % copa
        if not os.path.exists(f):
            continue
        c = leer(f, ['date', 'home_team', 'away_team']).dropna(subset=['fecha'])
        apar = pd.concat([c[['fecha', 'home_team']].rename(columns={'home_team': 'eqc'}),
                          c[['fecha', 'away_team']].rename(columns={'away_team': 'eqc'})])
        cand = [(lg, eq, ys, norm(eq)) for lg in ligas if lg in activos for eq, ys in activos[lg].items()]
        indice = {}
        for i, (_, _, _, tk) in enumerate(cand):
            for w in tk:
                if len(w) >= 3:
                    indice.setdefault(w[:4], set()).add(i)
        mapa = {}
        for eq, g in apar.groupby('eqc'):
            ys = set(g.fecha.dt.year)
            tk = norm(eq)
            pos = set()
            for w in tk:
                if len(w) >= 3:
                    pos |= indice.get(w[:4], set())
            sc = []
            for i in pos:
                lg, eqL, ysL, tkL = cand[i]
                if not (ys & ysL):
                    continue
                r = difflib.SequenceMatcher(None, ' '.join(tk), ' '.join(tkL)).ratio()
                a, b = set(tk), set(tkL)
                if a and b and (a <= b or b <= a):
                    r = max(r, 0.9)
                sc.append((r, lg, eqL))
            sc.sort(reverse=True)
            if sc and sc[0][0] >= 0.82 and (len(sc) == 1 or sc[1][0] < sc[0][0] - 0.04
                                             or (sc[1][1], sc[1][2]) == (sc[0][1], sc[0][2])):
                mapa[eq] = (sc[0][1], sc[0][2])
        # un equipo de liga sólo puede venir de UN nombre de la copa: si varios
        # caen en el mismo (AEK Athens / AEK Larnaca → AEK), se queda sólo el
        # que coincide exacto; si ninguno coincide exacto, se descartan todos
        inv = {}
        for eq, dest in mapa.items():
            inv.setdefault(dest, []).append(eq)
        for dest, nombres in inv.items():
            if len(nombres) > 1:
                exactos = [e for e in nombres if norm(e) == norm(dest[1])]
                for e in nombres:
                    if not (len(exactos) == 1 and e == exactos[0]):
                        mapa.pop(e, None)
        ok = apar.eqc.map(lambda e: e in mapa)
        info[copa] = {'apariciones': int(len(apar)), 'emparejadas': round(float(ok.mean()), 3),
                      'ejemplos': {k: '%s|%s' % v for k, v in list(mapa.items())[:12]}}
        for fe, eq in zip(apar.fecha[ok.values], apar.eqc[ok.values]):
            lg, eqL = mapa[eq]
            citas.append((lg, eqL, fe))
    return pd.DataFrame(citas, columns=['liga', 'equipo', 'fecha']), info


# ============================================================ rasgos por equipo
def previos(t, col, k, minp):
    """Media de las k anteriores del mismo equipo y temporada (t ordenado por gid, fecha)."""
    g = t.gid.values
    v = t[col].astype(float)
    okv = v.notna().astype(float)
    cs = v.fillna(0).groupby(g).cumsum()
    cn = okv.groupby(g).cumsum()
    s1, sk = cs.groupby(g).shift(1).fillna(0), cs.groupby(g).shift(k + 1).fillna(0)
    n1, nk = cn.groupby(g).shift(1).fillna(0), cn.groupby(g).shift(k + 1).fillna(0)
    n = n1 - nk
    return ((s1 - sk) / n.replace(0, np.nan)).where(n >= minp)


def racha(t, cond):
    g = t.gid
    nuevo = (cond != cond.groupby(g).shift(1)) | (g != g.shift(1))
    largo = cond.astype(int).groupby(nuevo.cumsum()).cumsum()
    return largo.groupby(g).shift(1).fillna(0)


def tabla(d):
    """Tabla ANTES de cada jornada: posición, puntos al líder y sobre la salvación."""
    cols = ['n_eq', 'h_pos', 'a_pos', 'h_pj', 'a_pj', 'h_lider', 'a_lider', 'h_salv', 'a_salv']
    res = np.full((len(d), len(cols)), np.nan)
    pos_de = {m: i for i, m in enumerate(d.index)}
    maxpj = {}
    for (liga, temp), g in d.groupby(['liga', 'temporada'], sort=False):
        if liga in SIN_TABLA:
            continue
        eqs = pd.unique(np.concatenate([g.home_team.values, g.away_team.values]))
        n = len(eqs)
        if n < 10:
            continue
        baja = 3 if n >= 18 else 2 if n >= 14 else 1          # descensos aproximados
        pts, gd, pj = dict.fromkeys(eqs, 0), dict.fromkeys(eqs, 0), dict.fromkeys(eqs, 0)
        for fe, gg in g.groupby('fecha', sort=True):
            orden = sorted(eqs, key=lambda e: (-pts[e], -gd[e]))
            pos = {e: i + 1 for i, e in enumerate(orden)}
            lider, salv = pts[orden[0]], pts[orden[n - baja - 1]]
            filas = list(zip(gg.index, gg.home_team, gg.away_team, gg.home_goals, gg.away_goals))
            for i, h, a, x, y in filas:
                res[pos_de[i]] = [n, pos[h], pos[a], pj[h], pj[a], lider - pts[h], lider - pts[a],
                                  pts[h] - salv, pts[a] - salv]
            for i, h, a, x, y in filas:
                pts[h] += 3 if x > y else 1 if x == y else 0
                pts[a] += 3 if y > x else 1 if x == y else 0
                gd[h] += x - y
                gd[a] += y - x
                pj[h] += 1
                pj[a] += 1
        maxpj.setdefault(liga, []).append(max(pj.values()))
    out = pd.DataFrame(res, index=d.index, columns=cols)
    # jornadas por equipo del FORMATO de la liga (mediana de las temporadas
    # completas): las ligas a 3-4 vueltas (Escocia, Suiza, Austria…) no son 2(n−1)
    jor = {lg: float(np.median([x for x in v if x >= 0.7 * np.median(v)])) for lg, v in maxpj.items()}
    out['jornadas'] = d.liga.map(jor).values
    return out


def rasgos(d, citas):
    im = 1 / d[['odd_home', 'odd_draw', 'odd_away']].where(d[['odd_home', 'odd_draw', 'odd_away']] > 1)
    s = im.sum(axis=1)
    d['ph'], d['pdr'], d['pa'] = im.odd_home / s, im.odd_draw / s, im.odd_away / s
    base = dict(mid=d.mid, fecha=d.fecha, liga=d.liga, temporada=d.temporada)
    h = pd.DataFrame(dict(base, equipo=d.home_team, local=1, gf=d.home_goals, gc=d.away_goals,
                          sf=d.home_shots_on, sc=d.away_shots_on, pw=d.ph, pe=d.pdr))
    a = pd.DataFrame(dict(base, equipo=d.away_team, local=0, gf=d.away_goals, gc=d.home_goals,
                          sf=d.away_shots_on, sc=d.home_shots_on, pw=d.pa, pe=d.pdr))
    t = pd.concat([h, a], ignore_index=True).sort_values(['liga', 'temporada', 'equipo', 'fecha', 'mid'])
    t = t.reset_index(drop=True)
    t['gid'] = t.groupby(['liga', 'temporada', 'equipo'], sort=False).ngroup()
    t['pts'] = np.where(t.gf > t.gc, 3, np.where(t.gf == t.gc, 1, 0))
    t['xres'] = t.pts - (3 * t.pw + t.pe)
    t['gd'] = t.gf - t.gc
    t['gt'] = t.gf + t.gc
    t['sotd'] = t.sf - t.sc
    t['sott'] = t.sf + t.sc
    for col in ('pts', 'xres', 'gd', 'gt', 'sotd', 'sott'):
        t['l5_' + col] = previos(t, col, 5, 3)
    t['rv'] = racha(t, t.gf > t.gc)
    t['rd'] = racha(t, t.gf < t.gc)
    t['perdio'] = (t.gf < t.gc).astype(float).groupby(t.gid).shift(1)
    # ---- calendario: liga + copas (las copas sólo 2021→). Una cita de copa a
    # ±1 día de un partido de liga del mismo equipo es un emparejamiento malo.
    lig = set(zip(t.liga, t.equipo, t.fecha.values.astype('datetime64[D]').astype(np.int64)))
    cd = citas.fecha.values.astype('datetime64[D]').astype(np.int64)
    choque = np.array([any((lg_, eq_, x + s) in lig for s in (-1, 0, 1))
                       for lg_, eq_, x in zip(citas.liga, citas.equipo, cd)], dtype=bool)
    citas = citas[~choque]
    cal = pd.concat([t[['liga', 'equipo', 'fecha']].assign(copa=0), citas.assign(copa=1)], ignore_index=True)
    cal = cal.sort_values(['liga', 'equipo', 'fecha', 'copa']).drop_duplicates(['liga', 'equipo', 'fecha'])
    cal = cal.reset_index(drop=True)
    cl = cal.groupby(['liga', 'equipo'], sort=False).ngroup().values.astype(np.int64)
    dias = cal.fecha.values.astype('datetime64[D]').astype(np.int64)
    k = cl * 1_000_000 + (dias - dias.min())
    cal['n14'] = np.arange(len(k)) - np.searchsorted(k, k - 14, side='left')
    same_prev = np.r_[False, cl[1:] == cl[:-1]]
    same_next = np.r_[cl[1:] == cl[:-1], False]
    prev = np.r_[0, dias[:-1]]
    nxt = np.r_[dias[1:], 0]
    cal['desc'] = np.where(same_prev, dias - prev, np.nan)
    cal['prox'] = np.where(same_next, nxt - dias, np.nan)
    cal['copa_a'] = np.where(same_prev, np.r_[0, cal.copa.values[:-1]], 0)
    cal['copa_d'] = np.where(same_next, np.r_[cal.copa.values[1:], 0], 0)
    cal.loc[cal.desc > 30, 'desc'] = np.nan
    cal.loc[cal.prox > 30, 'prox'] = np.nan
    cal['copa_a'] = ((cal.copa_a == 1) & (cal.desc <= 5)).astype(float)
    cal['copa_d'] = ((cal.copa_d == 1) & (cal.prox <= 5)).astype(float)
    t = t.merge(cal[cal.copa == 0][['liga', 'equipo', 'fecha', 'n14', 'desc', 'prox', 'copa_a', 'copa_d']],
                on=['liga', 'equipo', 'fecha'], how='left')
    F = ['l5_pts', 'l5_xres', 'l5_gd', 'l5_gt', 'l5_sotd', 'l5_sott', 'rv', 'rd', 'perdio',
         'n14', 'desc', 'prox', 'copa_a', 'copa_d']
    th = t[t.local == 1].set_index('mid')[F].add_prefix('h_')
    ta = t[t.local == 0].set_index('mid')[F].add_prefix('a_')
    tb = tabla(d.sort_values('fecha'))
    m = d.set_index('mid').join(th).join(ta)
    m = m.join(tb.set_index(d.loc[tb.index, 'mid']))
    m['h_avance'] = m.h_pj / m.jornadas
    m['a_avance'] = m.a_pj / m.jornadas
    m['h_pos_rel'] = (m.h_pos - 1) / (m.n_eq - 1)
    m['a_pos_rel'] = (m.a_pos - 1) / (m.n_eq - 1)
    return m.reset_index()


FEAT = ['l5_pts', 'l5_xres', 'l5_gd', 'l5_gt', 'l5_sotd', 'l5_sott', 'rv', 'rd', 'perdio', 'n14', 'desc',
        'prox', 'copa_a', 'copa_d', 'pos', 'pos_rel', 'pj', 'lider', 'salv', 'avance']


# ===================================================================== patas
def patas(m):
    ok3 = (m.odd_home > 1) & (m.odd_draw > 1) & (m.odd_away > 1)
    q = m[ok3]
    gh, ga = q.home_goals.values, q.away_goals.values
    oh, od, oa = q.odd_home.values, q.odd_draw.values, q.odd_away.values
    ph, pdr, pa = q.ph.values, q.pdr.values, q.pa.values
    sp = 1 / q.odd_home_pin + 1 / q.odd_draw_pin + 1 / q.odd_away_pin
    pih = ((1 / q.odd_home_pin) / sp).values
    pid = ((1 / q.odd_draw_pin) / sp).values
    pia = ((1 / q.odd_away_pin) / sp).values
    defs = [('gana local', 'ganador', 'local', oh, ph, gh > ga, pih),
            ('empate', 'ganador', 'ninguno', od, pdr, gh == ga, pid),
            ('gana visita', 'ganador', 'visita', oa, pa, gh < ga, pia),
            ('1X', 'doble', 'local', 1 / (1 / oh + 1 / od), ph + pdr, gh >= ga, pih + pid),
            ('X2', 'doble', 'visita', 1 / (1 / oa + 1 / od), pa + pdr, gh <= ga, pia + pid),
            ('12', 'doble', 'ninguno', 1 / (1 / oh + 1 / oa), ph + pa, gh != ga, pih + pia)]
    out = []
    for tipo, fam, lado, c, p, ok, pp in defs:
        out.append(pd.DataFrame({'mid': q.mid.values, 'tipo': tipo, 'familia': fam, 'lado': lado,
                                 'cuota': c, 'p_c': p, 'ok': ok.astype(float), 'p_pin': pp}))
    o = m[(m.odd_over25 > 1) & (m.odd_under25 > 1)]
    so = 1 / o.odd_over25 + 1 / o.odd_under25
    tot = (o.home_goals + o.away_goals).values
    for tipo, col, ok in (('más 2,5', 'odd_over25', tot > 2.5), ('menos 2,5', 'odd_under25', tot < 2.5)):
        out.append(pd.DataFrame({'mid': o.mid.values, 'tipo': tipo, 'familia': 'goles', 'lado': 'ninguno',
                                 'cuota': o[col].values, 'p_c': ((1 / o[col]) / so).values,
                                 'ok': ok.astype(float), 'p_pin': np.nan}))
    P = pd.concat(out, ignore_index=True)
    P = P[(P.cuota >= 1.20) & (P.cuota <= 2.50)].copy()
    cols = ['mid', 'fecha', 'liga'] + ['h_' + f for f in FEAT] + ['a_' + f for f in FEAT]
    P = P.merge(m[cols], on='mid', how='left')
    vis = (P.lado == 'visita').values
    for f in FEAT:
        hv, av = P['h_' + f].values.astype(np.float32), P['a_' + f].values.astype(np.float32)
        P['T_' + f] = np.where(vis, av, hv)
        P['R_' + f] = np.where(vis, hv, av)
    P = P.drop(columns=['h_' + f for f in FEAT] + ['a_' + f for f in FEAT])
    P['gan'] = np.where(P.ok == 1, P.cuota - 1, -1.0)
    P['exc'] = P.ok - P.p_c
    return P.reset_index(drop=True)


# ================================================================ contextos
def contextos_lado(P):
    """Filtros sobre la pata de un equipo (T) contra su rival (R): ganador y doble."""
    T = lambda f: P['T_' + f]
    R = lambda f: P['R_' + f]
    final_T, final_R = T('avance') >= 0.70, R('avance') >= 0.70
    desc_T = final_T & (T('salv') <= 3) & (T('pos_rel') >= 0.5)
    tit_T = final_T & (T('lider') <= 3)
    nada_R = (R('avance') >= 0.75) & (R('salv') >= 8) & (R('lider') >= 10) & (R('pos_rel') >= 0.25)
    nada_T = (T('avance') >= 0.75) & (T('salv') >= 8) & (T('lider') >= 10) & (T('pos_rel') >= 0.25)
    return {
        # desgaste
        'descanso +2 días sobre el rival': T('desc') - R('desc') >= 2,
        'descanso −2 días bajo el rival': T('desc') - R('desc') <= -2,
        'rival con ≤3 días, equipo ≥5': (R('desc') <= 3) & (T('desc') >= 5),
        'equipo con ≤3 días': T('desc') <= 3,
        'rival 3+ partidos en 14 días, equipo ≤2': (R('n14') >= 3) & (T('n14') <= 2),
        'rival viene de copa (≤5 días), equipo no': (R('copa_a') == 1) & (T('copa_a') == 0),
        'equipo viene de copa (≤5 días)': T('copa_a') == 1,
        'equipo tiene copa en ≤5 días': T('copa_d') == 1,
        'rival tiene copa en ≤5 días, equipo no': (R('copa_d') == 1) & (T('copa_d') == 0),
        'equipo vuelve a jugar en ≤3 días': T('prox') <= 3,
        'tras parón (equipo >14 días sin jugar)': T('desc') > 14,
        # forma
        'forma buena (l5 ≥ 2,2 pts)': T('l5_pts') >= 2.2,
        'forma mala (l5 ≤ 0,8 pts)': T('l5_pts') <= 0.8,
        'rival en forma mala (l5 ≤ 0,8)': R('l5_pts') <= 0.8,
        'rival en forma buena (l5 ≥ 2,2)': R('l5_pts') >= 2.2,
        'viene de perder': T('perdio') == 1,
        'rival viene de perder': R('perdio') == 1,
        '3+ derrotas seguidas': T('rd') >= 3,
        '3+ victorias seguidas': T('rv') >= 3,
        'rival 3+ derrotas seguidas': R('rd') >= 3,
        'rival 3+ victorias seguidas': R('rv') >= 3,
        'sobre-rinde al precio (l5 +0,5 pts)': T('l5_xres') >= 0.5,
        'infra-rinde al precio (l5 −0,5 pts)': T('l5_xres') <= -0.5,
        'rival sobre-rinde al precio': R('l5_xres') >= 0.5,
        'rival infra-rinde al precio': R('l5_xres') <= -0.5,
        'domina a puerta (l5 +3 sobre el rival)': T('l5_sotd') - R('l5_sotd') >= 3,
        'mala suerte (l5 dif<0 pero +1 a puerta)': (T('l5_gd') < 0) & (T('l5_sotd') >= 1),
        'rival con suerte (l5 dif>0,5 sin dominar a puerta)': (R('l5_gd') > 0.5) & (R('l5_sotd') <= 0),
        # tabla
        'pelea el descenso al final': desc_T,
        'pelea el título al final': tit_T,
        'rival sin nada en juego al final': nada_R & final_R,
        'equipo sin nada en juego al final': nada_T,
        'presión (descenso/título) contra rival sin nada': (desc_T | tit_T) & nada_R,
        'inicio de temporada (≤5 jornadas)': T('pj') <= 5,
        'mejor en la tabla (pos_rel −0,3, 8+ jornadas)': (T('pos_rel') - R('pos_rel') <= -0.3) & (T('pj') >= 8),
        'peor en la tabla pero favorito de la casa': (T('pos_rel') - R('pos_rel') >= 0.2) & (T('pj') >= 8),
        # lado
        'local': P.lado == 'local',
        'visitante': P.lado == 'visita',
        # referencia (no es contexto de equipo): el precio de Pinnacle
        'REF Pinnacle ve +2 pts sobre la casa': P.p_pin - P.p_c >= 0.02,
    }


def contextos_goles(P):
    H = lambda f: P['T_' + f]          # en goles T = local, R = visita
    A = lambda f: P['R_' + f]
    nada = lambda X: (X('avance') >= 0.75) & (X('salv') >= 8) & (X('lider') >= 10)
    c = {
        'ambos goleadores (l5 goles totales ≥ 3,2)': ((H('l5_gt') >= 3.2) & (A('l5_gt') >= 3.2), 'más 2,5'),
        'ambos cerrados (l5 goles totales ≤ 2,0)': ((H('l5_gt') <= 2.0) & (A('l5_gt') <= 2.0), 'menos 2,5'),
        'muchos tiros a puerta (l5 suma ≥ 20)': (H('l5_sott') + A('l5_sott') >= 20, 'más 2,5'),
        'pocos tiros a puerta (l5 suma ≤ 14)': (H('l5_sott') + A('l5_sott') <= 14, 'menos 2,5'),
        'ambos sin nada en juego al final (más)': (nada(H) & nada(A), 'más 2,5'),
        'los dos pelean el descenso al final (menos)': ((H('avance') >= 0.7) & (H('salv') <= 3) &
                                                        (A('avance') >= 0.7) & (A('salv') <= 3), 'menos 2,5'),
        'ambos cansados ≤3 días (más)': ((H('desc') <= 3) & (A('desc') <= 3), 'más 2,5'),
        'ambos cansados ≤3 días (menos)': ((H('desc') <= 3) & (A('desc') <= 3), 'menos 2,5'),
        'inicio de temporada (más)': ((H('pj') <= 5) & (A('pj') <= 5), 'más 2,5'),
        'inicio de temporada (menos)': ((H('pj') <= 5) & (A('pj') <= 5), 'menos 2,5'),
        'sólo «más» (sin contexto)': (P.tipo == 'más 2,5', 'más 2,5'),
        'sólo «menos» (sin contexto)': (P.tipo == 'menos 2,5', 'menos 2,5'),
    }
    return {k: (v & (P.tipo == t)) for k, (v, t) in c.items()}


# ============================================================ medición
class Banco:
    """Una familia en un piso: la base («la casa elige») y los pesos del bootstrap."""

    def __init__(self, z):
        self.z = z
        b = z.sort_values('p_c', ascending=False, kind='mergesort').drop_duplicates('mid').sort_values('mid')
        self.base = b
        self.idx = pd.Index(b.mid.values)
        self.fecha = b.fecha.values.astype('datetime64[D]')
        self.dia = self.fecha.astype(np.int64)
        self.bok, self.bgan, self.bexc, self.bexk = (b[c].values.astype(np.float32)
                                                     for c in ('ok', 'gan', 'exc', 'exc_cal'))
        self.bcuota = b.cuota.values
        self.W = rng.poisson(1.0, size=(NB, len(b))).astype(np.float32)

    def picks(self, mask=None, score='p_c'):
        q = self.z if mask is None else self.z[np.asarray(mask, dtype=bool)]
        q = q[q[score].notna()]
        return q.sort_values(score, ascending=False, kind='mergesort').drop_duplicates('mid')

    def evaluar(self, mask=None, score='p_c'):
        q = self.picks(mask, score)
        if len(q) < 60:
            return {'n': int(len(q))}, q
        n = len(self.idx)
        pos = self.idx.get_indexer(q.mid.values)
        has = np.zeros(n, np.float32)
        ok, gan, exc, exk, cu, pc = (np.zeros(n, np.float32) for _ in range(6))
        has[pos] = 1
        ok[pos], gan[pos], exc[pos], exk[pos] = q.ok.values, q.gan.values, q.exc.values, q.exc_cal.values
        cu[pos], pc[pos] = q.cuota.values, q.p_c.values
        f = np.sort(q.fecha.values.astype('datetime64[D]'))
        fmin, corte = f[0], f[len(f) // 2]
        masks = {'A': (self.fecha >= fmin) & (self.fecha < corte), 'B': self.fecha >= corte,
                 '2023': self.fecha >= D2023, 'todo': self.fecha >= fmin}
        cols = []
        for mm in masks.values():
            mf = mm.astype(np.float32)
            cols += [has * mf, ok * mf, gan * mf, exc * mf, mf, self.bok * mf, self.bgan * mf, self.bexc * mf,
                     exk * mf, self.bexk * mf]
        V = np.column_stack(cols)
        S = V.sum(0)
        Rb = self.W @ V
        out = {'corte': str(corte)}
        for j, (k, mm) in enumerate(masks.items()):
            s, r = S[10 * j:10 * j + 10], Rb[:, 10 * j:10 * j + 10]
            if s[0] < 30:
                out[k] = {'n': int(s[0])}
                continue
            with np.errstate(invalid='ignore', divide='ignore'):
                acc, bacc = r[:, 1] / r[:, 0], r[:, 5] / r[:, 4]
                ex, bex = r[:, 3] / r[:, 0], r[:, 7] / r[:, 4]
                ek, bek = r[:, 8] / r[:, 0], r[:, 9] / r[:, 4]
                ga = r[:, 2] / r[:, 0]
            dias = len(np.unique(self.dia[mm]))
            sel = has.astype(bool) & mm
            out[k] = {'n': int(s[0]), 'patas_dia': round(float(s[0] / max(dias, 1)), 2),
                      'acierto': round(float(s[1] / s[0]), 4), 'base': round(float(s[5] / s[4]), 4),
                      'dif': round(float(s[1] / s[0] - s[5] / s[4]), 4),
                      'dif_p5': round(float(np.nanpercentile(acc - bacc, 5)), 4),
                      'casa_promete': round(float(pc[sel].mean()), 4),
                      'exceso': round(float(s[3] / s[0]), 4), 'exceso_base': round(float(s[7] / s[4]), 4),
                      'dif_exceso_p5': round(float(np.nanpercentile(ex - bex, 5)), 4),
                      'exceso_cal': round(float(s[8] / s[0]), 4), 'exceso_cal_base': round(float(s[9] / s[4]), 4),
                      'dif_exceso_cal': round(float(s[8] / s[0] - s[9] / s[4]), 4),
                      'dif_exceso_cal_p5': round(float(np.nanpercentile(ek - bek, 5)), 4),
                      'cuota': round(float(cu[sel].mean()), 3),
                      'cuota_base': round(float(self.bcuota[mm].mean()), 3),
                      'gan_100': round(100 * float(s[2] / s[0]), 2),
                      'gan_p5': round(100 * float(np.nanpercentile(ga, 5)), 2),
                      'gan_base_100': round(100 * float(s[6] / s[4]), 2)}
        A, B = out.get('A', {}), out.get('B', {})
        if 'dif_p5' in A and 'dif_p5' in B:
            acc_ok = A['dif_p5'] > 0 and B['dif_p5'] > 0
            # «paso adelante»: además le gana a la casa CALIBRADA (el sesgo
            # favorito-sorpresa ya corregido con lo anterior), no sólo a la proporcional
            exc_ok = A['dif_exceso_cal_p5'] > 0 and B['dif_exceso_cal_p5'] > 0
            out['pasa_protocolo'] = bool(acc_ok)
            out['le_gana_a_la_casa_proporcional'] = bool(A['dif_exceso_p5'] > 0 and B['dif_exceso_p5'] > 0)
            C3 = out.get('2023', {})
            out['sostiene_2023'] = bool(C3.get('dif', -1) > 0 and C3.get('dif_exceso_cal', -1) > 0)
            if acc_ok and exc_ok:
                v = 'pasa'
            elif acc_ok:
                v = 'acierto por precio'
            elif A['dif'] > 0 and B['dif'] > 0 and (A['dif_p5'] > 0 or B['dif_p5'] > 0):
                v = 'parcial'
            elif A['dif'] > 0 and B['dif'] > 0:
                v = 'a favor sin p5'
            else:
                v = 'no'
            out['veredicto'] = v
        return out, q


def boletos(q, score, desde=None):
    """Boletos del día con las N patas de mayor puntaje (una por partido)."""
    q = q[['fecha', 'ok', 'cuota', score]].copy()
    if desde is not None:
        q = q[q.fecha.values.astype('datetime64[D]') >= desde]
    q['lc'] = np.log(q.cuota)
    q = q.sort_values(['fecha', score], ascending=[True, False])
    out = {}
    for N in NS:
        top = q.groupby('fecha', sort=False).head(N)
        g = top.groupby('fecha').agg(n=('ok', 'size'), bien=('ok', 'sum'), lc=('lc', 'sum'))
        g = g[g.n == N]
        if len(g) < 5:
            out[N] = {'dias': int(len(g))}
            continue
        ent = (g.bien == N).values
        mom = np.exp(g.lc.values)
        r = {'dias': int(len(g)), 'enteros': int(ent.sum()), 'pct_entero': round(float(ent.mean()), 4),
             'rojas_media': round(float((N - g.bien).mean()), 2), 'momio_mediano': round(float(np.median(mom)), 1)}
        for b in BOOST:
            r['gan_x%.1f' % b] = round(100 * float(np.where(ent, mom * b - 1, -1).mean()), 1)
        out[N] = r
    return out


# ================================================================== aprendiz
def aprendiz(P):
    """Logística y árbol (HGB) walk-forward por temporada (julio→junio), y el
    CONTROL: el mismo árbol sólo con la casa (prob. proporcional y tipo de pata),
    que aprende el sesgo favorito-sorpresa y nada más («casa calibrada»)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    tipos = sorted(P.tipo.unique())
    lg = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))
    num = ['T_' + f for f in FEAT] + ['R_' + f for f in FEAT]
    Xa = np.column_stack([lg(P.p_c.values), P.tipo.map({t: i for i, t in enumerate(tipos)}).values]
                         + [P[c].values for c in num]).astype(np.float32)
    lado = np.where(P.familia == 'goles', 0.0, 1.0)
    signo = np.where(P.tipo == 'menos 2,5', -1.0, 1.0)
    D = np.column_stack([(P.tipo == t).values.astype(float) for t in tipos])
    Xn = np.nan_to_num(Xa[:, 2:].astype(float))
    gsum = np.column_stack([(P.T_l5_gt + P.R_l5_gt).fillna(5.4).values, (P.T_l5_sott + P.R_l5_sott).fillna(17).values,
                            ((P.T_desc <= 3) & (P.R_desc <= 3)).values.astype(float),
                            ((P.T_pj <= 5) & (P.R_pj <= 5)).values.astype(float)])
    falta = np.column_stack([P[c].isna().values for c in ('T_desc', 'R_desc', 'T_l5_pts', 'R_l5_pts',
                                                          'T_l5_sotd', 'T_pos', 'R_pos')]).astype(float)
    Xl = np.column_stack([lg(P.p_c.values), D, Xn * lado[:, None], gsum * signo[:, None] * (1 - lado)[:, None],
                          falta])
    f = P.fecha.values.astype('datetime64[D]')
    y = P.ok.values.astype(int)
    p_arb = np.full(len(P), np.nan)
    p_log = np.full(len(P), np.nan)
    p_cal = np.full(len(P), np.nan)
    for Y in range(2012, 2027):
        ini, fin = np.datetime64('%d-07-01' % Y), np.datetime64('%d-07-01' % (Y + 1))
        tr, te = f < ini, (f >= ini) & (f < fin)
        if te.sum() == 0 or tr.sum() < 20000:
            continue
        arb = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15,
                                             min_samples_leaf=400, l2_regularization=1.0, max_bins=64,
                                             categorical_features=[1], early_stopping=False, random_state=0)
        arb.fit(Xa[tr], y[tr])
        p_arb[te] = arb.predict_proba(Xa[te])[:, 1]
        mu, sd = Xl[tr].mean(0), Xl[tr].std(0) + 1e-6
        lr = LogisticRegression(C=0.5, max_iter=400)
        lr.fit((Xl[tr] - mu) / sd, y[tr])
        p_log[te] = lr.predict_proba((Xl[te] - mu) / sd)[:, 1]
        ctl = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=8,
                                             min_samples_leaf=1000, max_bins=64, categorical_features=[1],
                                             monotonic_cst=[1, 0], early_stopping=False, random_state=0)
        ctl.fit(Xa[tr][:, :2], y[tr])
        p_cal[te] = ctl.predict_proba(Xa[te][:, :2])[:, 1]
        log('  aprendiz temporada %d: %d entren., %d pred.' % (Y, tr.sum(), te.sum()))
    return p_arb, p_log, p_cal


# ============================================================ parte B: e_v361
def parte_e():
    e = pd.read_pickle(RUTA_E)
    e = e[(e.odd_w > 1) & (e.odd_d > 1) & (e.odd_l > 1)].copy()
    s = 1 / e.odd_w + 1 / e.odd_d + 1 / e.odd_l
    e['mid'] = e.liga + '|' + e.mid.astype(str)
    pw, pe = (1 / e.odd_w) / s, (1 / e.odd_d) / s
    filas = []
    for tipo, fam, c, p, ok in (('gana', 'ganador', e.odd_w, pw, e.gf > e.gc),
                                ('no pierde', 'doble', 1 / (1 / e.odd_w + 1 / e.odd_d), pw + pe, e.gf >= e.gc)):
        filas.append(e.assign(tipo=tipo, familia=fam, cuota=c.values, p_c=p.values, ok=ok.astype(float).values))
    P = pd.concat(filas, ignore_index=True)
    P = P[(P.cuota >= 1.20) & (P.cuota <= 2.50)].reset_index(drop=True)
    P['lado'] = np.where(P.local == 1, 'local', 'visita')
    P['gan'] = np.where(P.ok == 1, P.cuota - 1, -1.0)
    P['exc'] = P.ok - P.p_c
    P['exc_cal'] = P.exc        # se rehace abajo con la casa calibrada
    dom_p = (P.ew_a_puerta - P.ew_a_puerta_c) - (P.r_ew_a_puerta - P.r_ew_a_puerta_c)
    dom_t = (P.ew_tiros - P.ew_tiros_c) - (P.r_ew_tiros - P.r_ew_tiros_c)
    final = P.avance >= 0.7
    C = {
        'descanso +2 días sobre el rival': P.descanso - P.r_descanso >= 2,
        'descanso −2 días bajo el rival': P.descanso - P.r_descanso <= -2,
        'rival con ≤3 días, equipo ≥5': (P.r_descanso <= 3) & (P.descanso >= 5),
        'equipo con ≤3 días': P.descanso <= 3,
        'presión al final contra rival sin presión': final & (P.presion >= 0.5) & (P.r_presion <= 0.1),
        'rival con presión al final, equipo sin': final & (P.r_presion >= 0.5) & (P.presion <= 0.1),
        'equipo en zona baja': P.zona_baja == 1,
        'rival en zona baja': P.r_zona_baja == 1,
        'zona alta al final': final & (P.zona_alta == 1),
        'ppg 0,7 mejor que el rival': P.ppg - P.r_ppg >= 0.7,
        'domina a puerta (ew +3)': dom_p >= 3,
        'domina en tiros (ew +8)': dom_t >= 8,
        'mala suerte (l5 dif<0, ew a puerta +1)': (P.l5_gf - P.l5_gc < 0) & (P.ew_a_puerta - P.ew_a_puerta_c >= 1),
        'goleador l5 ≥2 contra rival que encaja l5 ≥1,6': (P.l5_gf >= 2) & (P.r_l5_gc >= 1.6),
        'inicio de temporada (≤5 previos)': P.n_prev <= 5,
        'local': P.lado == 'local',
        'visitante': P.lado == 'visita',
    }
    # aprendiz walk-forward por trimestre con los rasgos del Método Contexto + la casa
    from sklearn.ensemble import HistGradientBoostingClassifier
    num = [c for c in P.columns if (c.startswith(('l5_', 'ew_', 't_', 'r_', 'v_')) or
                                    c in ('descanso', 'ppg', 'posicion', 'pos_rel', 'zona_baja', 'zona_alta',
                                          'avance', 'presion', 'n_prev', 'local'))
           and P[c].dtype.kind in 'fiub']
    lg = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))
    X = np.column_stack([lg(P.p_c.values), (P.familia == 'doble').values.astype(float)]
                        + [P[c].values.astype(float) for c in num]).astype(np.float32)
    f = P.fecha.values.astype('datetime64[D]')
    y = P.ok.values.astype(int)
    p_arb = np.full(len(P), np.nan)
    p_cal = np.full(len(P), np.nan)
    q0 = pd.Timestamp('2022-01-01')
    while q0 <= pd.Timestamp('2026-10-31'):
        q1 = q0 + pd.DateOffset(months=3)
        tr = f < np.datetime64(q0.date())
        te = (f >= np.datetime64(q0.date())) & (f < np.datetime64(q1.date()))
        if te.sum() and tr.sum() > 5000:
            arb = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15,
                                                 min_samples_leaf=300, l2_regularization=1.0, max_bins=64,
                                                 early_stopping=False, random_state=0)
            arb.fit(X[tr], y[tr])
            p_arb[te] = arb.predict_proba(X[te])[:, 1]
            ctl = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=8,
                                                 min_samples_leaf=500, max_bins=64, monotonic_cst=[1, 0],
                                                 early_stopping=False, random_state=0)
            ctl.fit(X[tr][:, :2], y[tr])
            p_cal[te] = ctl.predict_proba(X[te][:, :2])[:, 1]
        q0 = q1
    P['p_arb'] = p_arb
    P['p_cal'] = np.where(np.isnan(p_cal), P.p_c.values, p_cal)
    P['exc_cal'] = P.ok - P.p_cal
    R = {'filas': int(len(P)), 'partidos': int(P.mid.nunique()), 'desde': str(P.fecha.min().date()),
         'hasta': str(P.fecha.max().date()), 'rasgos_aprendiz': len(num), 'reglas': {}}
    for fam in ('ganador', 'doble'):
        for piso in PISOS:
            z = P[(P.familia == fam) & (P.cuota >= piso) & (P.cuota <= piso + ANCHO)]
            if z.mid.nunique() < 300:
                continue
            bk = Banco(z)
            base, _ = bk.evaluar()
            R['reglas'].setdefault(fam, {}).setdefault('%.2f' % piso, {})['casa elige (base)'] = base
            for nom, msk in C.items():
                r, _ = bk.evaluar(msk.loc[z.index].values)
                R['reglas'][fam]['%.2f' % piso][nom] = r
            r, _ = bk.evaluar(z.p_arb.notna().values, score='p_arb')
            R['reglas'][fam]['%.2f' % piso]['árbol elige (walk-forward)'] = r
            for u in (0.0, 0.02, 0.04):
                r, _ = bk.evaluar((z.p_arb - z.p_c >= u).values)
                R['reglas'][fam]['%.2f' % piso]['casa elige, árbol ≥ casa+%d' % round(100 * u)] = r
                r, _ = bk.evaluar((z.p_cal - z.p_c >= u).values)
                R['reglas'][fam]['%.2f' % piso]['CONTROL casa calibrada ≥ casa+%d' % round(100 * u)] = r
            r, _ = bk.evaluar((z.p_arb - z.p_cal >= 0).values)
            R['reglas'][fam]['%.2f' % piso]['casa elige, árbol ≥ casa calibrada'] = r
            del bk
    return R


# ===================================================================== main
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar_ligas()
    d['temporada'] = temporadas(d)
    log('ligas', d.liga.nunique(), 'partidos', len(d), 'temporadas liga', int(d.groupby('liga').temporada.nunique().sum()))
    citas, info_copas = mapear_copas(d)
    log('copas emparejadas', len(citas))
    m = rasgos(d, citas)
    log('rasgos listos')
    P = patas(m)
    log('patas', len(P), 'partidos con cuota', P.mid.nunique())
    p_arb, p_log, p_cal = aprendiz(P)
    P['p_arb'], P['p_log'] = p_arb, p_log
    # casa calibrada (control); antes de 2012-07 no hay con qué calibrar: la proporcional
    P['p_cal'] = np.where(np.isnan(p_cal), P.p_c.values, p_cal)
    P['exc_cal'] = P.ok - P.p_cal
    log('aprendiz listo')
    CL = {k: np.asarray(v.fillna(False) if hasattr(v, 'fillna') else v, dtype=bool)
          for k, v in contextos_lado(P).items()}
    CG = {k: np.asarray(v.fillna(False) if hasattr(v, 'fillna') else v, dtype=bool)
          for k, v in contextos_goles(P).items()}
    lado_ok = (P.lado != 'ninguno').values
    R = {'meta': {'partidos_liga': int(len(d)), 'ligas': int(d.liga.nunique()),
                  'partidos_con_cuota': int(P.mid.nunique()), 'patas_1.20_2.50': int(len(P)),
                  'desde': str(d.fecha.min().date()), 'hasta': str(d.fecha.max().date()),
                  'copas': info_copas,
                  'cobertura_rasgos': {c: round(float(P[c].notna().mean()), 3) for c in
                                       ('T_desc', 'T_l5_pts', 'T_l5_sotd', 'T_pos', 'T_avance', 'p_pin', 'p_arb')},
                  'cuantas_con_contexto': {k: int(v.sum()) for k, v in list(CL.items()) + list(CG.items())}},
         'reglas': {}, 'boletos': {}}
    mejores = {}
    for fam in ('ganador', 'doble', 'goles', 'todo'):
        Pf = P if fam == 'todo' else P[P.familia == fam]
        for piso in PISOS:
            sel = (Pf.cuota >= piso) & (Pf.cuota <= piso + ANCHO)
            z = Pf[sel]
            if z.mid.nunique() < 300:
                continue
            ix = z.index.values
            bk = Banco(z)
            kp = '%.2f' % piso
            RR = R['reglas'].setdefault(fam, {}).setdefault(kp, {})
            base, qb = bk.evaluar()
            RR['casa elige (base)'] = base
            cand = {}
            if fam in ('ganador', 'doble'):
                for nom, msk in CL.items():
                    cand[nom] = (msk[ix] & lado_ok[ix], 'p_c')
            elif fam == 'goles':
                for nom, msk in CG.items():
                    cand[nom] = (msk[ix], 'p_c')
            cand['árbol elige (walk-forward)'] = (z.p_arb.notna().values, 'p_arb')
            cand['logística elige (walk-forward)'] = (z.p_log.notna().values, 'p_log')
            for u in (0.0, 0.02, 0.04):
                cand['casa elige, árbol ≥ casa+%d' % round(100 * u)] = ((z.p_arb - z.p_c >= u).values, 'p_c')
                cand['casa elige, logística ≥ casa+%d' % round(100 * u)] = ((z.p_log - z.p_c >= u).values, 'p_c')
                # CONTROL: lo mismo con la casa calibrada (sin contexto): cuánto es puro sesgo de precio
                cand['CONTROL casa calibrada ≥ casa+%d' % round(100 * u)] = ((z.p_cal - z.p_c >= u).values, 'p_c')
            for u in (0.0, 0.02):
                cand['casa elige, árbol ≥ casa calibrada+%d' % round(100 * u)] = ((z.p_arb - z.p_cal >= u).values, 'p_c')
                cand['casa elige, logística ≥ casa calibrada+%d' % round(100 * u)] = (
                    (z.p_log - z.p_cal >= u).values, 'p_c')
            for nom, (msk, sc) in cand.items():
                r, q = bk.evaluar(msk, sc)
                RR[nom] = r
                if r.get('veredicto') and fam != 'todo' and not nom.startswith(('REF', 'CONTROL')):
                    A, B = r['A'], r['B']
                    clave = (r['veredicto'] == 'pasa', r['sostiene_2023'], min(A['dif_p5'], B['dif_p5']))
                    if kp not in mejores or clave > mejores[kp][0]:
                        mejores[kp] = (clave, fam, nom, msk, sc, r)
            if fam == 'todo':
                R['boletos'].setdefault(kp, {})['casa elige (todo)'] = {
                    'todo': boletos(qb, 'p_c'), '2023': boletos(qb, 'p_c', D2023)}
            del bk
            log('  %s %s: %d reglas' % (fam, kp, len(cand)))
    # boletos con la mejor regla de cada piso (aunque no pase: se dice)
    for kp, (clave, fam, nom, msk, sc, r) in mejores.items():
        piso = float(kp)
        Pf = P[P.familia == fam]
        z = Pf[(Pf.cuota >= piso) & (Pf.cuota <= piso + ANCHO)]
        bk = Banco(z)
        _, q = bk.evaluar(msk, sc)
        _, qb = bk.evaluar()
        R['boletos'][kp]['mejor regla: %s · %s (%s)' % (fam, nom, r['veredicto'])] = {
            'todo': boletos(q, sc), '2023': boletos(q, sc, D2023)}
        R['boletos'][kp]['casa elige (%s)' % fam] = {'todo': boletos(qb, 'p_c'), '2023': boletos(qb, 'p_c', D2023)}
        del bk
    log('boletos listos')
    R['parte_e'] = parte_e()
    log('parte e lista')
    # resumen: qué pasa
    pasan, precio, parcial = [], [], []
    for parte, reglas in (('historico', R['reglas']), ('e_v361', R['parte_e']['reglas'])):
        for fam, porpiso in reglas.items():
            for kp, rr in porpiso.items():
                for nom, r in rr.items():
                    v = r.get('veredicto')
                    fila = '%s · %s · %s · %s' % (parte, fam, kp, nom)
                    if v == 'pasa':
                        pasan.append(fila + ' (acierto A %+.3f B %+.3f 2023 %s; sobre casa calibrada A %+.3f B %+.3f 2023 %s)' % (
                            r['A']['dif'], r['B']['dif'], r.get('2023', {}).get('dif'), r['A']['dif_exceso_cal'],
                            r['B']['dif_exceso_cal'], r.get('2023', {}).get('dif_exceso_cal')))
                    elif v == 'acierto por precio':
                        precio.append(fila)
                    elif v == 'parcial':
                        parcial.append(fila)
    # consistencia: en cuántas celdas (familia × piso) la regla le gana a la
    # casa calibrada en las DOS mitades (sin exigir p5): un contexto real
    # debería repetirse en pisos vecinos, no salir en uno solo
    consist = {}
    for parte, reglas in (('historico', R['reglas']), ('e_v361', R['parte_e']['reglas'])):
        for fam, porpiso in reglas.items():
            for kp, rr in porpiso.items():
                for nom, r in rr.items():
                    A, B = r.get('A', {}), r.get('B', {})
                    if 'dif_exceso_cal' not in A or 'dif_exceso_cal' not in B or nom == 'casa elige (base)':
                        continue
                    c = consist.setdefault('%s · %s · %s' % (parte, fam, nom), [0, 0, 0])
                    c[0] += 1
                    c[1] += int(A['dif_exceso_cal'] > 0 and B['dif_exceso_cal'] > 0)
                    c[2] += int(r.get('veredicto') == 'pasa')
    n_eval = sum(v[0] for v in consist.values())
    R['resumen_consistencia'] = {
        'nota': 'celdas evaluadas / celdas con exceso sobre la casa calibrada > 0 en A y en B / celdas que pasan',
        'reglas_evaluadas': n_eval,
        'pasan_por_azar_aprox': round(n_eval * 0.05 * 0.05, 1),
        'reglas': {k: v for k, v in sorted(consist.items(), key=lambda kv: (-kv[1][1] / max(kv[1][0], 1), -kv[1][2]))}}
    R['resumen'] = {'pasan': pasan, 'acierto_por_precio': precio, 'parcial': parcial,
                    'n_reglas': sum(len(rr) for porpiso in R['reglas'].values() for rr in porpiso.values())
                    + sum(len(rr) for porpiso in R['parte_e']['reglas'].values() for rr in porpiso.values()),
                    'mejor_por_piso': {kp: '%s · %s · %s' % (v[1], v[2], v[5]['veredicto']) for kp, v in mejores.items()},
                    'segundos': round(time.time() - T0)}
    json.dump(R, open('_v373_contexto.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    # ---- pantalla
    for fam, porpiso in R['reglas'].items():
        for kp, rr in porpiso.items():
            b = rr['casa elige (base)']
            print('== %s %s base: n %s acierto %s cuota %s gan %s | A %s B %s' % (
                fam, kp, b['todo'].get('n'), b['todo'].get('acierto'), b['todo'].get('cuota'),
                b['todo'].get('gan_100'), b['A'].get('acierto'), b['B'].get('acierto')))
            for nom, r in rr.items():
                if nom == 'casa elige (base)' or 'A' not in r or 'dif' not in r['A'] or 'dif' not in r.get('B', {}):
                    continue
                A, B, C = r['A'], r['B'], r.get('2023', {})
                print('   %-52s %-18s n %6d %4.1f/d acierto %.3f/%.3f (base %.3f/%.3f) dif %+.3f(p5 %+.3f) %+.3f(p5 %+.3f) '
                      'cal %+.3f(%+.3f)/%+.3f(%+.3f) 2023 %s/%s cuota %.2f gan %+.1f' % (
                          nom[:52], r['veredicto'], r['todo']['n'], r['todo']['patas_dia'], A['acierto'], B['acierto'],
                          A['base'], B['base'], A['dif'], A['dif_p5'], B['dif'], B['dif_p5'],
                          A['dif_exceso_cal'], A['dif_exceso_cal_p5'], B['dif_exceso_cal'], B['dif_exceso_cal_p5'],
                          C.get('dif'), C.get('dif_exceso_cal'), r['todo']['cuota'], r['todo']['gan_100']))
    print('== PARTE e_v361')
    for fam, porpiso in R['parte_e']['reglas'].items():
        for kp, rr in porpiso.items():
            b = rr['casa elige (base)']
            print('  %s %s base n %s acierto %s cuota %s' % (fam, kp, b['todo'].get('n'), b['todo'].get('acierto'),
                                                            b['todo'].get('cuota')))
            for nom, r in rr.items():
                if 'veredicto' in r:
                    print('     %-48s %-18s n %5d dif A %+.3f(%+.3f) B %+.3f(%+.3f) cal %+.3f(%+.3f)/%+.3f(%+.3f) 2023 %s/%s' % (
                        nom[:48], r['veredicto'], r['todo']['n'], r['A']['dif'], r['A']['dif_p5'], r['B']['dif'],
                        r['B']['dif_p5'], r['A']['dif_exceso_cal'], r['A']['dif_exceso_cal_p5'],
                        r['B']['dif_exceso_cal'], r['B']['dif_exceso_cal_p5'], r.get('2023', {}).get('dif'),
                        r.get('2023', {}).get('dif_exceso_cal')))
    print('== BOLETOS')
    for kp, bb in R['boletos'].items():
        for nom, v in bb.items():
            print('  %s %s' % (kp, nom))
            for N, x in v['todo'].items():
                print('     N=%-2s %s' % (N, x))
    print('== RESUMEN', json.dumps(R['resumen'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
