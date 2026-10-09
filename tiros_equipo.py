#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v345 — LOS TIROS POR EQUIPO, CON LA METODOLOGÍA DEL USUARIO.

El usuario pasó la metodología de un amigo que acertaba tiros en la liga
brasileña: «no basta con los últimos cinco partidos o el promedio —en un
partido hizo 4 tiros y en otro 31—. Hay que ver en qué posición están en la
tabla, cuántos goles reciben y anotan, cuánto retienen el balón, los córners,
las tarjetas, si el rival hace muchas faltas, y la plantilla».

CÓMO SE CONVIRTIÓ EN UN MODELO (medido en `_v344_tiros.py` y `_v345_tiros.py`)
--------------------------------------------------------------------------
Cada idea es una variable que se conoce ANTES del partido (sólo partidos
anteriores): tiros a favor y concedidos (temporada, últimos 5, forma
ponderada, en la misma condición), goles a favor y en contra, posesión de los
dos, faltas que comete el rival, córners, amarillas, posición y puntos por
partido, zona de la tabla × avance de la temporada, descanso, calidad de los
rivales ya enfrentados y la fuerza según la cuota (la «plantilla»). Un
LightGBM Poisson por mercado, con 59.000 partidos-equipo de 43 ligas con
estadística REAL de ESPN (2021-2026), y una binomial negativa para las líneas.

    log-loss (elige 70 % / juzga 30 %)      tiros     a puerta
    últimos 5 en la misma condición          0,632      0,657
    ataque × defensa                         0,603      0,616
    metodología (v344)                       0,550      0,575
    metodología + extras (v345)              0,549      0,574   p5 > 0

Contra la línea REAL de Playdoit (24-ago a 8-oct, 410 partidos, 2.886
líneas): el modelo predice mejor que la casa — tiros 0,681 contra 0,691, a
puerta 0,654 contra 0,665 —. La mezcla con la casa que mejor cumple lo que
promete, elegida con la primera mitad: el modelo solo en tiros, 65 % modelo
y 35 % casa en a puerta (`PESO_MODELO`).

LO QUE NO SE HACE TODAVÍA: «meter». La regla elegida con la primera mitad
(tiros, 10 puntos de ventaja sobre la casa) rindió +20 % (p5 +7 %) al elegir
y +3 % (p5 −10 %) al juzgar. Queda en seguimiento automático
(`tiros_seguimiento`), que la activa sola cuando el registro posterior a la
elección tenga p5 > 0.

Uso:
    python tiros_equipo.py --entrenar       # el workflow, una vez al día
    python tiros_equipo.py --precalcular    # el precálculo de cada pasada
"""
import argparse
import datetime as _dt
import glob
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('tiros_equipo')

# como los demás pesos: asset del Release `modelos-latest` (`modelos_remotos`)
DIR_MODELO = os.path.join('modelos', 'tiros_equipo')
FICHERO_DIA = 'tiros_dia.json'
VERSION = 'v345'
OBJETIVOS = ('tiros', 'a_puerta')
# peso del modelo frente a la casa en la probabilidad que se enseña (medido)
PESO_MODELO = {'tiros': 1.0, 'a_puerta': 0.65}
MIN_PARTIDOS = 3
COPAS = ('afc_champions', 'champions', 'conference_league', 'europa_league',
         'libertadores', 'sudamericana', 'selecciones', 'leagues_cup',
         'bra_copa', 'eng_fa_cup')
SEMESTRE = ('liga_mx', 'col_primera_a', 'chi_primera', 'per_liga1')
CALENDARIO = ('brasil', 'bra_serie_b', 'mls', 'usl_championship', 'china',
              'jpn_j1', 'suecia', 'noruega', 'ksa_pro', 'ind_isl')
_CACHE: Dict = {}


# ---------------------------------------------------------------------------
# los datos
# ---------------------------------------------------------------------------
def temporada(liga: str, f) -> str:
    if liga in SEMESTRE:
        return '%d-%d' % (f.year, 1 if f.month <= 6 else 2)
    if liga in CALENDARIO:
        return str(f.year)
    return str(f.year if f.month >= 7 else f.year - 1)


def _marcadores(code: str, meses) -> Dict[str, tuple]:
    """{event_id: (goles local, goles visita)} del scoreboard de ESPN."""
    import requests
    out = {}
    for m in meses:
        try:
            j = requests.get('https://site.api.espn.com/apis/site/v2/sports/'
                             'soccer/%s/scoreboard' % code,
                             params={'dates': m, 'limit': 500}, timeout=30).json()
        except Exception as e:
            logger.debug('[tiros] marcadores %s %s: %s', code, m, e)
            continue
        for ev in j.get('events') or []:
            try:
                if not ((ev.get('status') or {}).get('type') or {}).get('completed'):
                    continue
                comp = ev['competitions'][0]
                h = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                a = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
                out[str(ev['id'])] = (float(h['score']), float(a['score']))
            except Exception:
                continue
    return out


def cargar_partidos(ligas: Optional[List[str]] = None,
                    desde: Optional[str] = None) -> pd.DataFrame:
    """El histórico con estadística REAL de ESPN y, detrás, lo que
    `stats_espn/` ya tiene y el histórico todavía no (con su marcador)."""
    filas = []
    for ruta in sorted(glob.glob('historico_*.csv')):
        liga = ruta[len('historico_'):-4]
        if liga in COPAS or (ligas and liga not in ligas):
            continue
        try:
            d = pd.read_csv(ruta, low_memory=False)
        except Exception:
            continue
        need = {'stats_origen', 'home_shots_on', 'home_shots_off',
                'home_possession', 'home_fouls'}
        if not need <= set(d.columns):
            continue
        d['fecha'] = pd.to_datetime(d['date'], errors='coerce')
        if desde:
            d = d[d.fecha >= pd.Timestamp(desde)]
        d = d[(d.stats_origen == 'espn') & d.home_shots_on.notna()
              & d.away_shots_on.notna() & d.home_possession.notna()]
        d = d.dropna(subset=['fecha', 'home_goals', 'away_goals']).copy()
        if len(d) < (300 if not desde else 1):
            continue
        d['liga'] = liga
        filas.append(d)
        cola = _cola_stats_espn(liga, d)
        if cola is not None and len(cola):
            filas.append(cola)
    if not filas:
        return pd.DataFrame()
    d = pd.concat(filas, ignore_index=True).sort_values('fecha')
    for c in ('odd_home_pin', 'odd_draw_pin', 'odd_away_pin', 'odd_home',
              'odd_draw', 'odd_away'):
        if c not in d:
            d[c] = np.nan
    d['mid'] = np.arange(len(d))
    return d


def _cola_stats_espn(liga: str, hist: pd.DataFrame) -> Optional[pd.DataFrame]:
    try:
        import fixtures_espn
        import stats_espn as se
        code = fixtures_espn.ESPN_CODIGOS.get(liga)
        if not code:
            return None
        s = se.leer(liga)
        if not len(s):
            return None
        s = s[pd.to_datetime(s.fecha) > hist.fecha.max()].copy()
        if s.empty:
            return None
        meses = sorted({pd.Timestamp(f).strftime('%Y%m') for f in s.fecha})
        mk = _marcadores(code, meses)
        s['ev'] = s.event_id.astype(str)
        s = s[s.ev.isin(mk)]
        if s.empty:
            return None
        tr = se._traductor(set(s.home) | set(s.away),
                           set(hist.home_team) | set(hist.away_team))
        s['home_team'] = s.home.map(lambda n: tr.get(n, n))
        s['away_team'] = s.away.map(lambda n: tr.get(n, n))
        s['home_goals'] = s.ev.map(lambda e: mk[e][0])
        s['away_goals'] = s.ev.map(lambda e: mk[e][1])
        s['date'] = s.fecha
        s['fecha'] = pd.to_datetime(s.fecha)
        s['liga'] = liga
        s['stats_origen'] = 'espn'
        return s
    except Exception as e:
        logger.debug('[tiros] cola de stats_espn %s: %s', liga, e)
        return None


# ---------------------------------------------------------------------------
# los rasgos: sólo con lo anterior a cada partido
# ---------------------------------------------------------------------------
def a_equipos(d: pd.DataFrame) -> pd.DataFrame:
    out = []
    for lado, otro in (('home', 'away'), ('away', 'home')):
        x = pd.DataFrame({
            'mid': d.mid, 'fecha': d.fecha, 'liga': d.liga,
            'equipo': d['%s_team' % lado], 'rival': d['%s_team' % otro],
            'local': int(lado == 'home'),
            'tiros': d['%s_shots_on' % lado] + d['%s_shots_off' % lado],
            'a_puerta': d['%s_shots_on' % lado],
            'tiros_c': d['%s_shots_on' % otro] + d['%s_shots_off' % otro],
            'a_puerta_c': d['%s_shots_on' % otro],
            'gf': d['%s_goals' % lado], 'gc': d['%s_goals' % otro],
            'pos': d['%s_possession' % lado],
            'faltas': d['%s_fouls' % lado], 'faltas_r': d['%s_fouls' % otro],
            'corners': d['%s_corners' % lado], 'corners_c': d['%s_corners' % otro],
            'amarillas': d['%s_yellow' % lado],
            'odd_w': d['odd_%s_pin' % lado].fillna(d['odd_%s' % lado]),
            'odd_d': d['odd_draw_pin'].fillna(d['odd_draw']),
            'odd_l': d['odd_%s_pin' % otro].fillna(d['odd_%s' % otro]),
        })
        out.append(x)
    e = pd.concat(out, ignore_index=True).sort_values(['fecha', 'mid'])
    e['temporada'] = [temporada(l, f) for l, f in zip(e.liga, e.fecha)]
    e['pts'] = np.where(e.gf > e.gc, 3, np.where(e.gf == e.gc, 1, 0)).astype(float)
    e.loc[e.gf.isna() | e.gc.isna(), 'pts'] = np.nan
    return e.reset_index(drop=True)


_STATS = ['tiros', 'a_puerta', 'tiros_c', 'a_puerta_c', 'gf', 'gc', 'pos',
          'faltas', 'faltas_r', 'corners', 'corners_c', 'amarillas']


def rasgos(e: pd.DataFrame) -> pd.DataFrame:
    e = e.sort_values(['fecha', 'mid']).reset_index(drop=True)
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    e['n_prev'] = g.cumcount()
    for c in _STATS:
        e['t_' + c] = g[c].transform(lambda x: x.shift(1).expanding().mean())
        e['l5_' + c] = g[c].transform(lambda x: x.shift(1).rolling(5, 1).mean())
    for c in ('tiros', 'a_puerta', 'tiros_c', 'a_puerta_c', 'pos', 'faltas_r'):
        e['ew_' + c] = g[c].transform(
            lambda x: x.shift(1).ewm(span=8, min_periods=1).mean())
    gv = e.groupby(['liga', 'temporada', 'equipo', 'local'], sort=False)
    for c in ('tiros', 'a_puerta', 'tiros_c'):
        e['v_' + c] = gv[c].transform(lambda x: x.shift(1).expanding().mean())
    e['descanso'] = g.fecha.transform(lambda x: x.diff().dt.days).clip(0, 30)
    e['pts_prev'] = g['pts'].transform(lambda x: x.shift(1).fillna(0).cumsum())
    e['ppg'] = e.pts_prev / e.n_prev.replace(0, np.nan)
    # la tabla antes de cada fecha
    pos = np.full(len(e), np.nan)
    tam = np.full(len(e), np.nan)
    for _, idx in e.groupby(['liga', 'temporada']).groups.items():
        sub = e.loc[idx].sort_values(['fecha', 'mid'])
        tabla: Dict[str, tuple] = {}
        for _, bloque in sub.groupby('fecha', sort=True):
            orden = sorted(tabla.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
            rango = {k: i + 1 for i, (k, _) in enumerate(orden)}
            n = max(len(tabla), 1)
            for i, eq in zip(bloque.index, bloque.equipo):
                pos[i] = rango.get(eq, np.nan)
                tam[i] = n
            for eq, p_, gf, gc in zip(bloque.equipo, bloque.pts, bloque.gf, bloque.gc):
                if pd.isna(p_):
                    continue
                a, b = tabla.get(eq, (0.0, 0.0))
                tabla[eq] = (a + p_, b + gf - gc)
    e['posicion'] = pos
    e['pos_rel'] = e.posicion / pd.Series(tam)
    e['zona_baja'] = (e.pos_rel >= 0.80).astype(float)
    e['zona_alta'] = (e.pos_rel <= 0.30).astype(float)
    largo = e.groupby(['liga', 'temporada']).n_prev.transform('max').clip(lower=10)
    e['avance'] = e.n_prev / largo
    e['presion'] = e.avance * (e.zona_baja + e.zona_alta)
    inv = 1 / e[['odd_w', 'odd_d', 'odd_l']]
    s = inv.sum(axis=1)
    e['p_gana'] = inv.odd_w / s
    e['p_pierde'] = inv.odd_l / s
    e['p_empate'] = inv.odd_d / s
    # calidad de los rivales: tiros del equipo entre lo que concede el rival
    conc = e[['mid', 'equipo', 't_tiros_c']].rename(
        columns={'equipo': 'rival', 't_tiros_c': '_rc'})
    e = e.merge(conc, on=['mid', 'rival'], how='left')
    e['_ratio'] = e.tiros / e._rc
    e = e.sort_values(['fecha', 'mid']).reset_index(drop=True)
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    e['t_ratio'] = g['_ratio'].transform(lambda x: x.shift(1).expanding().mean())
    e = e.drop(columns=['_rc', '_ratio'])
    # lo del rival, del mismo partido
    cols = [c for c in e.columns if c.startswith(('t_', 'l5_', 'ew_', 'v_'))] + [
        'ppg', 'pos_rel', 'zona_baja', 'zona_alta', 'n_prev', 'posicion',
        'descanso', 'avance', 'presion']
    r = e[['mid', 'equipo'] + cols].rename(
        columns={c: 'r_' + c for c in cols}).rename(columns={'equipo': 'rival'})
    e = e.merge(r, on=['mid', 'rival'], how='left')
    for c in ('tiros', 'a_puerta'):
        e['liga_' + c] = e.groupby(['liga', 'temporada', 'local'])[c].transform(
            lambda x: x.shift(1).expanding().mean())
    return e


COLUMNAS = [
    'local', 't_tiros', 't_a_puerta', 'r_t_tiros_c', 'r_t_a_puerta_c',
    'l5_tiros', 'l5_a_puerta', 'r_l5_tiros_c', 'r_l5_a_puerta_c',
    't_gf', 't_gc', 'r_t_gf', 'r_t_gc', 'n_prev', 'r_n_prev',
    'liga_tiros', 'liga_a_puerta',
    't_pos', 'r_t_pos', 'l5_pos', 'r_l5_pos', 'r_t_faltas', 't_faltas_r',
    't_corners', 'r_t_corners_c', 'r_t_amarillas', 't_amarillas',
    'ppg', 'r_ppg', 'pos_rel', 'r_pos_rel', 'zona_baja', 'zona_alta',
    'r_zona_baja', 'r_zona_alta', 'p_gana', 'p_pierde',
    'ew_tiros', 'ew_a_puerta', 'r_ew_tiros_c', 'r_ew_a_puerta_c', 'ew_pos',
    'r_ew_pos', 'r_ew_faltas_r', 'v_tiros', 'v_a_puerta', 'r_v_tiros_c',
    'descanso', 'r_descanso', 'avance', 'presion', 'r_presion',
    'p_empate', 't_ratio', 'r_t_ratio']


def ajustar_k(y, lam) -> float:
    """Tamaño de la binomial negativa por momentos (var = mu + mu²/k)."""
    v = float(np.mean((np.asarray(y) - lam) ** 2 - lam))
    return float(np.clip(np.mean(np.asarray(lam) ** 2) / max(v, 1e-6), 2, 500))


def prob_mas(lam: float, linea: float, k: float) -> float:
    """P(tiros > línea) con binomial negativa de media `lam` y tamaño `k`."""
    from scipy import stats
    p = k / (k + lam)
    return float(stats.nbinom.sf(np.floor(linea), k, p))


# ---------------------------------------------------------------------------
# entrenar (el workflow, una vez al día)
# ---------------------------------------------------------------------------
def entrenar(directorio: str = DIR_MODELO) -> Dict:
    import lightgbm as lgb
    d = cargar_partidos()
    e = rasgos(a_equipos(d))
    e = e[(e.n_prev >= MIN_PARTIDOS) & (e.r_n_prev >= MIN_PARTIDOS)].dropna(
        subset=['p_gana', 'tiros', 'a_puerta'])
    os.makedirs(directorio, exist_ok=True)
    meta = {'version': VERSION, 'entrenado': _dt.datetime.utcnow().strftime(
        '%Y-%m-%dT%H:%M:%SZ'), 'filas': int(len(e)), 'columnas': COLUMNAS,
        'ligas': sorted(e.liga.unique().tolist()), 'k': {},
        'peso_modelo': PESO_MODELO}
    for obj in OBJETIVOS:
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=700,
                              learning_rate=0.03, num_leaves=31,
                              min_child_samples=80, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8,
                              reg_lambda=1.0, verbose=-1, random_state=345)
        c2 = e.fecha.quantile(0.85)
        a, b = e[e.fecha < c2], e[e.fecha >= c2]
        m.fit(a[COLUMNAS], a[obj])
        meta['k'][obj] = ajustar_k(b[obj].values,
                                   np.clip(m.predict(b[COLUMNAS]), 0.3, None))
        m.fit(e[COLUMNAS], e[obj])
        m.booster_.save_model(os.path.join(directorio, '%s.txt' % obj))
    with open(os.path.join(directorio, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    logger.info('[tiros] modelo entrenado con %d filas de %d ligas',
                meta['filas'], len(meta['ligas']))
    return meta


def _modelos(directorio: str = DIR_MODELO):
    if _CACHE.get('dir') == directorio and 'boosters' in _CACHE:
        return _CACHE['meta'], _CACHE['boosters']
    if directorio == DIR_MODELO and not os.path.exists(
            os.path.join(directorio, 'meta.json')):
        import modelos_remotos as mr
        mr.asegurar('tiros_equipo')
    import lightgbm as lgb
    with open(os.path.join(directorio, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    boosters = {o: lgb.Booster(model_file=os.path.join(directorio, '%s.txt' % o))
                for o in OBJETIVOS}
    _CACHE.update(dir=directorio, meta=meta, boosters=boosters)
    return meta, boosters


# ---------------------------------------------------------------------------
# precalcular (cada pasada del precálculo)
# ---------------------------------------------------------------------------
def _lados(partido: str):
    par = str(partido or '')
    return [x.strip() for x in par.split(' vs ', 1)] if ' vs ' in par else [None, None]


def _nombre_del_catalogo(nombre: str, catalogo) -> Optional[str]:
    if nombre in catalogo:
        return nombre
    try:
        import name_mapper
        return name_mapper.mapear(str(nombre), list(catalogo), contexto='tiros')
    except Exception:
        return None


def precalcular(pronosticos: List[Dict], ruta: str = FICHERO_DIA,
                directorio: str = DIR_MODELO) -> int:
    """Las medias de tiros de cada equipo en los partidos sin jugar, con el
    MISMO cálculo de rasgos que se entrenó (los partidos por jugar se añaden
    a la temporada en curso y se les calculan sus rasgos). Nunca lanza."""
    try:
        meta, boosters = _modelos(directorio)
    except Exception as e:
        logger.warning('[tiros] sin modelo entrenado: %s', e)
        return 0
    ligas = set(meta.get('ligas') or [])
    picks = [p for p in (pronosticos or []) if isinstance(p, dict)
             and str(p.get('deporte') or 'Fútbol') == 'Fútbol'
             and p.get('clave_liga') in ligas and not p.get('jugado')]
    if not picks:
        return 0
    desde = (pd.Timestamp.utcnow().tz_localize(None)
             - pd.Timedelta(days=400)).strftime('%Y-%m-%d')
    d = cargar_partidos(sorted({p['clave_liga'] for p in picks}), desde=desde)
    if d.empty:
        return 0
    nuevas, llaves = [], {}
    for p in picks:
        h, a = _lados(p.get('partido'))
        liga = p['clave_liga']
        dl = d[d.liga == liga]
        cat = set(dl.home_team) | set(dl.away_team)
        hc, ac = _nombre_del_catalogo(h, cat), _nombre_del_catalogo(a, cat)
        if not (hc and ac):
            continue
        try:
            f = pd.Timestamp(str(p.get('inicio') or p.get('fecha'))[:19])
        except Exception:
            continue
        c = ((p.get('implicitas') or {}).get('1x2_cuotas') or {})
        mid = int(d.mid.max()) + 1 + len(nuevas)
        nuevas.append({'mid': mid, 'fecha': f.normalize(), 'liga': liga,
                       'home_team': hc, 'away_team': ac,
                       'odd_home': c.get('home'), 'odd_draw': c.get('draw'),
                       'odd_away': c.get('away')})
        llaves[mid] = '%s|%s' % (p.get('partido'), liga)
    if not nuevas:
        return 0
    n = pd.DataFrame(nuevas)
    for c in d.columns:
        if c not in n:
            n[c] = np.nan
    todo = pd.concat([d, n[d.columns]], ignore_index=True)
    e = rasgos(a_equipos(todo))
    e = e[e.mid.isin(llaves)]
    out = {}
    cols = meta['columnas']
    for obj in OBJETIVOS:
        e['lam_' + obj] = np.clip(boosters[obj].predict(e[cols]), 0.3, None)
    for mid, g in e.groupby('mid'):
        lados = {}
        for r in g.itertuples():
            if (r.n_prev < MIN_PARTIDOS or pd.isna(r.r_n_prev)
                    or r.r_n_prev < MIN_PARTIDOS):
                continue
            lados['local' if r.local == 1 else 'visitante'] = {
                'tiros': round(float(r.lam_tiros), 3),
                'a_puerta': round(float(r.lam_a_puerta), 3),
                'partidos': int(r.n_prev)}
        if len(lados) == 2:
            out[llaves[mid]] = lados
    doc = {'version': VERSION, 'k': meta['k'], 'peso_modelo': meta.get('peso_modelo'),
           'generado': _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
           'partidos': out}
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    logger.info('[tiros] %d partidos con tiros precalculados', len(out))
    return len(out)


# ---------------------------------------------------------------------------
# la app
# ---------------------------------------------------------------------------
def _dia(ruta: str = FICHERO_DIA) -> Dict:
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        return {}
    if _CACHE.get('dia_mt') != (ruta, mt):
        try:
            with open(ruta, encoding='utf-8') as f:
                _CACHE['dia'] = json.load(f) or {}
        except Exception:
            _CACHE['dia'] = {}
        _CACHE['dia_mt'] = (ruta, mt)
    return _CACHE['dia']


def del_partido(pick: Dict, ruta: str = FICHERO_DIA) -> Optional[Dict]:
    doc = _dia(ruta)
    p = (doc.get('partidos') or {}).get(
        '%s|%s' % ((pick or {}).get('partido'), (pick or {}).get('clave_liga')))
    if not p:
        return None
    return {'lados': p, 'k': doc.get('k') or {},
            'peso_modelo': doc.get('peso_modelo') or PESO_MODELO}


def bloques_tarjeta(pick: Dict, ruta: str = FICHERO_DIA) -> Optional[Dict]:
    """{'totales': bloque, 'a_puerta': bloque} con la forma que pinta la
    tarjeta (`modo_modelo._filas_de`) y que lee `valor_apuesta`, o None."""
    dp = del_partido(pick, ruta)
    if not dp:
        return None
    salida = {}
    for nombre, obj in (('totales', 'tiros'), ('a_puerta', 'a_puerta')):
        mh = dp['lados']['local'][obj]
        ma = dp['lados']['visitante'][obj]
        k = float(dp['k'].get(obj) or 50.0)
        # la razón varianza/media de la binomial negativa es 1 + mu/k
        salida[nombre] = {
            'lambda_home': mh, 'lambda_away': ma,
            'lambda_total': round(mh + ma, 3),
            'dispersion': round(1 + (mh + ma) / 2 / k, 4),
            'dispersion_total': round(1 + (mh ** 2 + ma ** 2) / (k * (mh + ma)), 4),
            'k': k, 'modelo_tiros': VERSION,
            'peso_modelo': float(dp['peso_modelo'].get(obj, 1.0)),
            'origen': 'observado', 'clave_liga': pick.get('clave_liga'),
            'base': 'modelo de tiros (tabla, posesión, faltas, plantilla)',
            'confianza': {'nivel': 2, 'insignia': True}}
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--entrenar', action='store_true')
    ap.add_argument('--precalcular', action='store_true')
    ap.add_argument('--pronostico', default='pronostico_dia.json')
    a = ap.parse_args()
    if a.entrenar:
        print(json.dumps(entrenar(), ensure_ascii=False, indent=1)[:2000])
    if a.precalcular:
        with open(a.pronostico, encoding='utf-8') as f:
            doc = json.load(f)
        print(precalcular((doc.get('datos') or doc).get('pronosticos') or []))
