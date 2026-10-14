#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — H6 · Cruce de casas: ir con el mercado, pero al MEJOR PRECIO.

El usuario quiere soñadoras de N patas con cuota mínima por pata (1,30 · 1,45 ·
1,60 · 1,70 · 1,80, como el booster de Draftea) «de acuerdo con la casa, pero
un paso adelante de la casa». La hipótesis H6 dice que ese paso es el PRECIO:
usar el mercado más eficiente (Pinnacle) o el consenso de varias casas para
saber qué lado es el bueno, y apostarlo donde paguen más.

QUÉ SE MIDE (cuatro bolsas, cada una con su precio y su referencia)
  H. HISTÓRICO 2012-2026 (`historico_*.csv`): 1X2 de la «casa» contra el
     cierre de Pinnacle. Ojo, dos formatos:
       · 'new' (16 ligas, 2018→): casa = media de mercado de CIERRE (AvgC) y
         Pinnacle de CIERRE → simultáneos: ésta es la prueba válida;
       · 'main' (20 ligas grandes, 2012→): casa = Bet365 de ANTES del cierre
         (viernes/martes) y Pinnacle de CIERRE → Pinnacle sabe lo que pasó
         después (fuga; es CLV, no una regla que se pueda usar). Se reporta
         aparte sólo para mostrar el tamaño de la fuga.
     El más/menos 2,5 del histórico NO tiene Pinnacle: no se puede cruzar.
  P. PLAYDOIT CONTRA PINNACLE en el MISMO barrido (`odds_snapshots.csv`,
     clave hora|casa, 30-jul → 9-oct): 1X2, la última foto común del día
     anterior o antes; resultado del `historico_<liga>.csv`. Y el más/menos
     2,5: el tablero de Playdoit (`_v362b_tableros.pkl`, última foto del día
     anterior o antes) contra el barrido de Pinnacle más cercano (NO
     simultáneos: se reporta el desfase y el bloque con desfase ≤ 6 h).
  M. CASAS MEXICANAS en la MISMA foto (historial de git de `cuotas_mx.json`:
     1xBet, Winpot, Novibet, Caliente y Sportium, 10-sep → 12-oct): 1X2,
     doble oportunidad, más/menos 1,5/2,5/3,5 y ambos marcan; la última foto
     antes del inicio; resultado de `resultados_flashscore*.csv.gz` por id.
     Se apuesta en NOVIBET (la casa de los boletos del usuario) o en la que
     más paga; se repite con 1xBet como casa base (cotiza el más/menos, que
     Novibet casi nunca trae en el feed).
  X. CRUCE NOVIBET ↔ PLAYDOIT ↔ PINNACLE: cada partido de M emparejado con el
     de P (nombres, ±1 día) y la foto de M más cercana al barrido de P antes
     del inicio; se guarda el desfase en horas (no simultáneo; se reporta con
     desfase ≤ 3 h aparte). Incluye el 1X2 y el más/menos 2,5 de Pinnacle
     contra la MEJOR cuota mexicana. El emparejamiento se comprueba con el
     marcador (Flashscore contra el histórico).

REGLAS (una pata por partido, piso de cuota ≤ cuota ≤ piso + 0,5)
  base         — LÍNEA BASE: la casa donde se apuesta elige (su propia
                 probabilidad sin margen, reparto proporcional).
  ref_elige    — elige la referencia (Pinnacle / consenso), se apuesta a la
                 cuota de la casa.
  valor        — sólo patas con cuota de la casa > cuota justa de la
                 referencia (cuota × p_ref > 1); elige la referencia.
  direccion    — sólo patas que la referencia ve MÁS probables que la casa
                 (p_ref > p_casa); elige la referencia.
  consenso / discrepan — la casa elige, partido a partido según si casa y
                 referencia tienen el mismo favorito en el 1X2.
  mejor_precio — (M y X) elige el consenso y se apuesta en la casa que más
                 paga (un parlay va en UNA casa: sus boletos son orientativos).
  boleto_una_casa — (M) la versión jugable del boleto: cada día, para cada
                 casa mexicana, las N patas de más probabilidad del consenso
                 con la cuota de ESA casa en el piso; se juega entero en la
                 casa con mayor Π(p_consenso × cuota).
Umbrales fijos de antemano (0 de valor, 0 de dirección): nada se ajusta
mirando el resultado.

PROTOCOLO: dos mitades por fecha (A/B, corte en la mediana de cada bolsa);
bootstrap POR PARTIDO (pesos de Poisson, emparejado regla↔base) para el p5 de
la diferencia contra la línea base en el MISMO piso; ganancia por $100 con su
p5; boletos del día de N ∈ {4, 6, 10, 15, 25} patas (las N de más
probabilidad según la regla) sin booster y con ×1,2 / ×1,3 / ×1,8 sobre el
momio. Una regla PASA si mejora a la base en las dos mitades con p5 > 0; si
mejora en las dos sin p5 > 0 es «parcial». Calibración (log-loss) de cada
casa en los mismos partidos, y la tabla «¿la diferencia entre casas señala el
lado bueno?» por tramos de p_ref − p_casa.

Escribe `_v373_casas.json`. Si existe la variable V373_CACHE (una carpeta),
guarda ahí el historial de `cuotas_mx.json` leído de git para no releerlo.
"""
import importlib.util as iu
import json
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

rng = np.random.default_rng(3736)
PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
ANCHO = 0.50
NS = (4, 6, 10, 15, 25)
BOOST = (1.0, 1.2, 1.3, 1.8)
NB = 1000
CASAS_MX = ('1xBet', 'Winpot', 'Novibet', 'Calientemx', 'Sportium.mx')
OTRAS_SNAP = ('Pinnacle', 'Bovada', 'DraftKings', 'Matchbook', 'Unibet')
T0 = time.time()


def log(*a):
    print('[%5.0f s]' % (time.time() - T0), *a, flush=True)


def _carga(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _r(v, k=4):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), k)


# ======================================================== motor de medición
def elegir(x, piso, score, filtro=None, cuota='cuota'):
    z = x[(x[cuota] >= piso) & (x[cuota] <= piso + ANCHO)]
    if filtro is not None:
        z = z[filtro(z)]
    z = z.assign(score=z[score], cuota_ap=z[cuota])
    z = z.assign(_pid=z.partido.astype(str))
    z = z.sort_values(['score', 'cuota_ap', '_pid'], ascending=[False, False, True]).drop_duplicates('partido')
    z = z.drop(columns='_pid')
    return z.assign(gan=np.where(z.ok == 1, z.cuota_ap - 1, -1.0))


def _pesos(n, m):
    for i in range(0, n, 100):
        yield rng.poisson(1.0, (min(100, n - i), m)).astype(np.float32)


def boot_uno(z):
    """p5 del acierto y de la ganancia (bootstrap por partido)."""
    g = z.groupby('partido').agg(ok=('ok', 'sum'), n=('ok', 'size'), g=('gan', 'sum')).values.astype(np.float32)
    if len(g) < 20:
        return None, None
    S = np.vstack([W @ g for W in _pesos(NB, len(g))])
    return float(np.percentile(S[:, 0] / S[:, 1], 5)), float(np.percentile(S[:, 2] / S[:, 1], 5))


def boot_par(zr, zb):
    """p5 de (regla − base) en acierto y en ganancia, emparejado por partido."""
    a = zr.groupby('partido').agg(okr=('ok', 'sum'), nr=('ok', 'size'), gr=('gan', 'sum'))
    b = zb.groupby('partido').agg(okb=('ok', 'sum'), nb=('ok', 'size'), gb=('gan', 'sum'))
    M = a.join(b, how='outer').fillna(0).values.astype(np.float32)
    if len(zr) < 20 or len(zb) < 20:
        return None, None
    S = np.vstack([W @ M for W in _pesos(NB, len(M))])
    with np.errstate(invalid='ignore', divide='ignore'):
        da = S[:, 0] / S[:, 1] - S[:, 3] / S[:, 4]
        dg = S[:, 2] / S[:, 1] - S[:, 5] / S[:, 4]
    return float(np.nanpercentile(da, 5)), float(np.nanpercentile(dg, 5))


def resumen(z, dias):
    if len(z) < 20:
        return {'n': int(len(z))}
    a5, g5 = boot_uno(z)
    return {'n': int(len(z)), 'patas_por_dia': _r(len(z) / max(dias, 1), 2),
            'acierto': _r(z.ok.mean()), 'acierto_p5': _r(a5), 'promete_casa': _r(z.p_base.mean()),
            'promete_ref': _r(z.p_ref.mean()) if 'p_ref' in z and z.p_ref.notna().any() else None,
            'cuota': _r(z.cuota_ap.mean(), 3), 'gan_100': _r(100 * z.gan.mean(), 2),
            'gan_p5': _r(100 * g5, 2) if g5 is not None else None}


def boletos(z, n):
    z = z.assign(dia=z.fecha.dt.strftime('%Y-%m-%d'), lc=np.log(z.cuota_ap))
    z = z.assign(_pid=z.partido.astype(str))
    z = z.sort_values(['dia', 'score', 'cuota_ap', '_pid'], ascending=[True, False, False, True]).groupby('dia').head(n)
    g = z.groupby('dia').agg(k=('ok', 'size'), bien=('ok', 'sum'), lc=('lc', 'sum'))
    g = g[g.k == n]
    if g.empty:
        return {'dias_con_boleto': 0}
    entero = (g.bien == n).values
    momio = np.exp(g.lc.values)
    return {'dias_con_boleto': int(len(g)), 'enteros': int(entero.sum()),
            'pct_entero': _r(entero.mean(), 3), 'rojas_medias': _r((n - g.bien).mean(), 2),
            'momio_mediano': _r(np.median(momio), 2),
            'gan_100': {('x%.1f' % f): _r(100 * np.mean(np.where(entero, momio * f - 1, -1.0)), 1)
                        for f in BOOST}}


def medir(x, reglas, dias, corte, con_boletos=True, base_spec=('p_base', None, 'cuota')):
    """reglas: {nombre: (score, filtro, columna de cuota)}. Devuelve {piso: {...}}."""
    out = {}
    for piso in PISOS:
        base = elegir(x, piso, base_spec[0], base_spec[1], base_spec[2])
        fila = {}
        for nombre, (score, filtro, cc) in [('base', base_spec)] + list(reglas.items()):
            z = base if nombre == 'base' else elegir(x, piso, score, filtro, cc)
            f = {'todo': resumen(z, dias)}
            for t, m, mb in (('A', z.fecha < corte, base.fecha < corte),
                             ('B', z.fecha >= corte, base.fecha >= corte)):
                q, b = z[m], base[mb]
                f[t] = {'n': int(len(q)), 'acierto': _r(q.ok.mean()) if len(q) else None,
                        'cuota': _r(q.cuota_ap.mean(), 3) if len(q) else None,
                        'gan_100': _r(100 * q.gan.mean(), 2) if len(q) else None}
                if nombre != 'base' and len(q) >= 20 and len(b) >= 20:
                    a5, g5 = boot_par(q, b)
                    f[t].update({'dif_acierto': _r(q.ok.mean() - b.ok.mean()), 'dif_acierto_p5': _r(a5),
                                 'dif_gan_100': _r(100 * (q.gan.mean() - b.gan.mean()), 2),
                                 'dif_gan_p5': _r(100 * g5, 2) if g5 is not None else None})
            if nombre != 'base' and len(z) >= 20:
                a5, g5 = boot_par(z, base)
                f['todo'].update({'dif_acierto': _r(z.ok.mean() - base.ok.mean()), 'dif_acierto_p5': _r(a5),
                                  'dif_gan_100': _r(100 * (z.gan.mean() - base.gan.mean()), 2),
                                  'dif_gan_p5': _r(100 * g5, 2) if g5 is not None else None})
                f['veredicto'] = veredicto(f)
            if cc != 'cuota' and len(z) >= 20:
                # ¿de dónde sale lo que gana? la misma pata a la cuota de la casa base
                f['misma_pata_en_casa_base'] = {
                    'gan_100': _r(100 * np.where(z.ok == 1, z.cuota - 1, -1.0).mean(), 2),
                    'cuota': _r(z.cuota.mean(), 3),
                    'pct_bajo_piso_en_casa_base': _r((z.cuota < piso).mean())}
            if con_boletos and len(z) >= 20:
                f['boletos'] = {n: boletos(z, n) for n in NS}
            if len(z) >= 20 and 'mercado' in z:
                f['por_mercado'] = {m: [int(len(g)), _r(g.ok.mean(), 3), _r(g.cuota_ap.mean(), 3)]
                                    for m, g in z.groupby('mercado') if len(g) >= 15}
            fila[nombre] = f
        out['%.2f' % piso] = fila
    return out


def veredicto(f):
    """pasa / parcial / no_pasa, por acierto y por ganancia (las dos mitades)."""
    res = {}
    for met in ('acierto', 'gan'):
        k, k5 = ('dif_acierto', 'dif_acierto_p5') if met == 'acierto' else ('dif_gan_100', 'dif_gan_p5')
        A, B = f.get('A', {}), f.get('B', {})
        if A.get(k) is None or B.get(k) is None:
            res[met] = 'sin_muestra'
        elif A[k] > 0 and B[k] > 0 and (A.get(k5) or -1) > 0 and (B.get(k5) or -1) > 0:
            res[met] = 'pasa'
        elif A[k] > 0 and B[k] > 0:
            res[met] = 'parcial'
        else:
            res[met] = 'no_pasa'
    return res


def senal(x, col_base='p_base', col_ref='p_ref'):
    """¿La diferencia entre casas señala el lado bueno? Todas las patas con
    referencia, por tramo de p_ref − p_casa: acierto contra lo que promete
    cada una."""
    z = x[x[col_ref].notna()].copy()
    z['d'] = z[col_ref] - z[col_base]
    z['tramo'] = pd.cut(z.d, [-1, -.05, -.02, -.005, .005, .02, .05, 1],
                        labels=['ref −5+', 'ref −2..−5', 'ref −0,5..−2', '±0,5', 'ref +0,5..+2',
                                'ref +2..+5', 'ref +5+'])
    out = {}
    for t, g in z.groupby('tramo', observed=True):
        if len(g) < 30:
            continue
        out[str(t)] = {'n': int(len(g)), 'acierto': _r(g.ok.mean()), 'casa': _r(g[col_base].mean()),
                       'ref': _r(g[col_ref].mean()), 'cuota': _r(g.cuota.mean(), 3),
                       'gan_100': _r(100 * (np.where(g.ok == 1, g.cuota - 1, -1.0)).mean(), 2)}
    return out


def logloss_1x2(x, cols):
    """log-loss del 1X2 (por partido) de cada fuente, en los mismos partidos."""
    z = x[x.mercado == '1X2'].dropna(subset=list(cols))
    n = z.groupby('partido').ok.transform('size')
    z = z[n == 3]
    z = z[z.ok == 1]
    if len(z) < 30:
        return {'n': int(len(z))}
    out = {'n_partidos': int(len(z))}
    for c in cols:
        out[c] = _r(-np.log(z[c].clip(1e-4, 1)).mean(), 5)
    return out


def consenso_1x2(x, fav_base, fav_ref):
    """Partido a partido: favorito de la casa y de la referencia coinciden o
    no; si discrepan, ¿quién acierta más? (las dos apostadas a la cuota de la
    casa)."""
    z = x[x.mercado == '1X2']
    fb = z[z[fav_base] == 1].drop_duplicates('partido')
    fr = z[z[fav_ref] == 1].drop_duplicates('partido')
    k = fb[['partido', 'fecha', 'lado', 'ok', 'cuota', 'p_base']].merge(
        fr[['partido', 'lado', 'ok', 'cuota', 'p_ref']], on='partido', suffixes=('_c', '_r'))
    co, di = k[k.lado_c == k.lado_r], k[k.lado_c != k.lado_r]
    g = lambda s, o, c: _r(100 * np.where(s[o] == 1, s[c] - 1, -1.0).mean(), 2) if len(s) else None
    extra = {}
    if len(di) >= 40:
        corte = x.fecha.quantile(0.5)
        gr = np.where(di.ok_r == 1, di.cuota_r - 1, -1.0)
        gc = np.where(di.ok_c == 1, di.cuota_c - 1, -1.0)
        d = gr - gc
        bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(NB)]
        extra = {'ref_menos_casa_gan_100': _r(100 * d.mean(), 2),
                 'ref_menos_casa_gan_p5': _r(100 * np.percentile(bs, 5), 2),
                 'ref_gan_p5': _r(100 * np.percentile([gr[rng.integers(0, len(gr), len(gr))].mean()
                                                       for _ in range(NB)], 5), 2),
                 'A': {'n': int((di.fecha < corte).sum()), 'acierto_ref': _r(di[di.fecha < corte].ok_r.mean()),
                       'acierto_casa': _r(di[di.fecha < corte].ok_c.mean()),
                       'gan_ref': _r(100 * gr[(di.fecha < corte).values].mean(), 2)},
                 'B': {'n': int((di.fecha >= corte).sum()), 'acierto_ref': _r(di[di.fecha >= corte].ok_r.mean()),
                       'acierto_casa': _r(di[di.fecha >= corte].ok_c.mean()),
                       'gan_ref': _r(100 * gr[(di.fecha >= corte).values].mean(), 2)}}
    return {'partidos': int(len(k)), 'coinciden': int(len(co)), 'discrepan': int(len(di)), **extra,
            'pct_discrepan': _r(len(di) / max(len(k), 1)),
            'fav_si_coinciden': {'acierto': _r(co.ok_c.mean()), 'promete': _r(co.p_base.mean()),
                                 'cuota': _r(co.cuota_c.mean(), 3), 'gan_100': g(co, 'ok_c', 'cuota_c')},
            'si_discrepan_fav_casa': {'acierto': _r(di.ok_c.mean()) if len(di) else None,
                                      'cuota': _r(di.cuota_c.mean(), 3) if len(di) else None,
                                      'gan_100': g(di, 'ok_c', 'cuota_c')},
            'si_discrepan_fav_ref': {'acierto': _r(di.ok_r.mean()) if len(di) else None,
                                     'cuota': _r(di.cuota_r.mean(), 3) if len(di) else None,
                                     'gan_100': g(di, 'ok_r', 'cuota_r')}}


def _fav(x, col):
    """1 si la pata es la de mayor probabilidad (según col) de su 1X2."""
    z = x[x.mercado == '1X2']
    mx = z.groupby('partido')[col].transform('max')
    out = pd.Series(0, index=x.index)
    out.loc[z.index] = (z[col] >= mx - 1e-12).astype(int)
    return out


REGLAS_STD = {
    'ref_elige': ('p_ref', lambda z: z.p_ref.notna(), 'cuota'),
    'valor': ('p_ref', lambda z: z.cuota * z.p_ref > 1.0, 'cuota'),
    'direccion': ('p_ref', lambda z: z.p_ref > z.p_base, 'cuota'),
    'consenso': ('p_base', lambda z: z.coinciden == 1, 'cuota'),
    'discrepan': ('p_base', lambda z: z.coinciden == 0, 'cuota'),
}


# ================================================== H · histórico 2012-2026
def historico():
    G = _carga('g371b', '_v371b_ganador.py')
    d = G.cargar()
    try:
        import config
        fmt = d.liga.map(lambda k: (config.LEAGUES.get(k) or {}).get('formato', '?'))
    except Exception:
        fmt = pd.Series('?', index=d.index)
    d['formato'] = fmt
    P = ['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']
    C = ['odd_home', 'odd_draw', 'odd_away']
    ok = d[P].notna().all(axis=1) & (d[P] > 1).all(axis=1)
    igual = (d[C].values == d[P].values).all(axis=1)
    d = d[ok & ~igual].copy()
    gh, ga = d.home_goals.astype(float), d.away_goals.astype(float)
    sc = (1 / d[C]).sum(axis=1)
    sp = (1 / d[P]).sum(axis=1)
    filas = []
    for lado, c, p, res in (('local', 'odd_home', 'odd_home_pin', gh > ga), ('empate', 'odd_draw', 'odd_draw_pin', gh == ga),
                            ('visita', 'odd_away', 'odd_away_pin', gh < ga)):
        filas.append(pd.DataFrame({'partido': d.liga + '|' + d.MATCH_ID.astype(str), 'fecha': d.fecha.dt.normalize(),
                                   'liga': d.liga, 'formato': d.formato, 'mercado': '1X2', 'lado': lado,
                                   'cuota': d[c], 'p_base': (1 / d[c]) / sc, 'p_ref': (1 / d[p]) / sp,
                                   'cuota_ref': d[p], 'ok': res.astype(int)}))
    x = pd.concat(filas, ignore_index=True)
    x['fav_c'] = _fav(x, 'p_base')
    x['fav_r'] = _fav(x, 'p_ref')
    co = x[x.fav_c == 1][['partido', 'lado']].merge(x[x.fav_r == 1][['partido', 'lado']], on='partido')
    co = co.drop_duplicates('partido')
    x['coinciden'] = x.partido.map(dict(zip(co.partido, (co.lado_x == co.lado_y).astype(int))))
    return x


def bloque(x, nombre, reglas, extra=None, con_boletos=True):
    dias = x.fecha.dt.normalize().nunique()
    corte = x.fecha.quantile(0.5)
    log('%s: %d patas, %d partidos, %d días, corte %s' % (nombre, len(x), x.partido.nunique(), dias,
                                                        corte.date()))
    R = {'universo': {'patas': int(len(x)), 'partidos': int(x.partido.nunique()), 'dias': int(dias),
                      'desde': str(x.fecha.min().date()), 'hasta': str(x.fecha.max().date()),
                      'corte_AB': str(corte.date())},
         'pisos': medir(x, reglas, dias, corte, con_boletos)}
    if 'p_ref' in x:
        R['senal'] = senal(x)
        R['valor_todas'] = {}
        z = x[x.p_ref.notna()]
        for piso in PISOS:
            q = z[(z.cuota >= piso) & (z.cuota <= piso + ANCHO)]
            v = q[q.cuota * q.p_ref > 1]
            R['valor_todas']['%.2f' % piso] = {
                'patas': int(len(q)), 'con_valor': int(len(v)), 'pct_valor': _r(len(v) / max(len(q), 1)),
                'acierto_valor': _r(v.ok.mean()) if len(v) else None,
                'promete_ref': _r(v.p_ref.mean()) if len(v) else None,
                'gan_valor_100': _r(100 * np.where(v.ok == 1, v.cuota - 1, -1.0).mean(), 2) if len(v) else None,
                'acierto_sin_valor': _r(q[q.cuota * q.p_ref <= 1].ok.mean()) if len(q) > len(v) else None}
    if extra:
        R.update(extra)
    return R


# =========================================== P · Playdoit y Pinnacle (barrido)
def snapshots():
    d = pd.read_csv('odds_snapshots.csv', low_memory=False)
    d = d[(d.fase == 'snapshot') & d.snapshot_key.astype(str).str.contains('|', regex=False)]
    d['hora'] = d.snapshot_key.str.split('|').str[0]
    d = d[d.hora.str.len() == 13].copy()
    d['ts'] = pd.to_datetime(d.hora + ':00', format='%Y-%m-%dT%H:%M', errors='coerce')
    d['match_date'] = pd.to_datetime(d.match_date, errors='coerce')
    return d.dropna(subset=['ts', 'match_date'])


def resultados_hist(claves):
    out = []
    for lk in claves:
        f = 'historico_%s.csv' % lk
        if not os.path.exists(f):
            continue
        h = pd.read_csv(f, usecols=lambda c: c in {'MATCH_ID', 'home_goals', 'away_goals'}, low_memory=False)
        if not {'MATCH_ID', 'home_goals', 'away_goals'} <= set(h.columns):
            continue
        out.append(h.dropna(subset=['home_goals', 'away_goals']).drop_duplicates('MATCH_ID'))
    r = pd.concat(out, ignore_index=True).drop_duplicates('MATCH_ID')
    return r.set_index('MATCH_ID')


def _devig3(q):
    q = np.asarray(q, float)
    if q.shape[-1] != 3 or not np.all(q > 1):
        return None
    im = 1 / q
    return im / im.sum()


def playdoit_pinnacle(S):
    s = S[S.bookmaker.isin(('Playdoit',) + OTRAS_SNAP)]
    s = s[(s.odds_home > 1) & (s.odds_draw > 1) & (s.odds_away > 1)]
    s = s[s.ts.dt.normalize() < s.match_date]               # el día anterior o antes
    res = resultados_hist(s.league_key.unique())
    s = s[s.match_id.isin(res.index)]
    play = s[s.bookmaker == 'Playdoit'].set_index(['match_id', 'hora'])
    pin = s[s.bookmaker == 'Pinnacle'].set_index(['match_id', 'hora'])
    comun = play.index.intersection(pin.index)
    k = pd.DataFrame(index=comun).reset_index()
    k = k.sort_values(['match_id', 'hora']).drop_duplicates('match_id', keep='last')
    otros = {b: g.set_index(['match_id', 'hora']) for b, g in s.groupby('bookmaker') if b in OTRAS_SNAP}
    filas = []
    for mid, hora in k.itertuples(index=False):
        pr = play.loc[(mid, hora)]
        pr = pr.iloc[0] if isinstance(pr, pd.DataFrame) else pr
        q = pin.loc[(mid, hora)]
        q = q.iloc[0] if isinstance(q, pd.DataFrame) else q
        pp = _devig3([pr.odds_home, pr.odds_draw, pr.odds_away])
        pq = _devig3([q.odds_home, q.odds_draw, q.odds_away])
        if pp is None or pq is None:
            continue
        mk = [pq]
        for b, g in otros.items():
            if b == 'Pinnacle' or (mid, hora) not in g.index:
                continue
            o = g.loc[(mid, hora)]
            o = o.iloc[0] if isinstance(o, pd.DataFrame) else o
            po = _devig3([o.odds_home, o.odds_draw, o.odds_away])
            if po is not None:
                mk.append(po)
        pm = np.mean(mk, axis=0) if len(mk) >= 2 else np.full(3, np.nan)
        r = res.loc[mid]
        gh, ga = float(r.home_goals), float(r.away_goals)
        for i, (lado, cq, okk) in enumerate((('local', pr.odds_home, gh > ga), ('empate', pr.odds_draw, gh == ga),
                                             ('visita', pr.odds_away, gh < ga))):
            filas.append({'partido': mid, 'fecha': pr.match_date, 'liga': pr.league_key, 'mercado': '1X2',
                          'lado': lado, 'cuota': float(cq), 'p_base': pp[i], 'p_ref': pq[i], 'p_mkt': pm[i],
                          'n_mkt': len(mk), 'ok': int(okk), 'hora': hora})
    x = pd.DataFrame(filas)
    x['fav_c'] = _fav(x, 'p_base')
    x['fav_r'] = _fav(x, 'p_ref')
    co = x[x.fav_c == 1][['partido', 'lado']].merge(x[x.fav_r == 1][['partido', 'lado']], on='partido')
    co = co.drop_duplicates('partido')
    x['coinciden'] = x.partido.map(dict(zip(co.partido, (co.lado_x == co.lado_y).astype(int))))
    return x


def _tablero_lineas(v):
    if not v:
        return {}
    if isinstance(v, str):
        import ast
        try:
            v = ast.literal_eval(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def playdoit_mm25(S):
    """Más/menos 2,5: Playdoit (tablero `mercado_dia.json`, última foto del día
    anterior o antes) contra Pinnacle (barrido de `odds_snapshots`, el del día
    anterior o antes más cercano a la foto). NO simultáneos: se guarda el
    desfase en horas."""
    t = pd.read_pickle('_v362b_tableros.pkl')
    pin = S[(S.bookmaker == 'Pinnacle') & (S.odds_over25 > 1) & (S.odds_under25 > 1)]
    pin = pin[pin.ts.dt.normalize() < pin.match_date]
    res = resultados_hist(pin.league_key.unique())
    pin = pin[pin.match_id.isin(res.index)]
    try:
        import cuotas_multi as cm
        sim = cm._sim_club
    except Exception:
        sim = lambda a_, b_: 1.0 if _norm(a_) == _norm(b_) else 0.0
    t = t.sort_values('ts')
    filas = []
    for mid, g in pin.groupby('match_id'):
        r0 = g.iloc[0]
        dia = r0.match_date
        w = t[(t.ts < dia) & (t.ts >= dia - pd.Timedelta(days=3))]
        cand = w[(w.h == _norm(r0.home_team)) & (w.a == _norm(r0.away_team))]
        if cand.empty:
            pares = [(h_, a_) for h_, a_ in w[['home', 'away']].drop_duplicates().itertuples(index=False)
                     if sim(r0.home_team, h_) >= 0.8 and sim(r0.away_team, a_) >= 0.8]
            if not pares:
                continue
            cand = w[(w.home == pares[0][0]) & (w.away == pares[0][1])]
        if cand.empty:
            continue
        foto = cand.iloc[-1]
        ln = _tablero_lineas(foto.board.get('goles')).get('2.5')
        if not isinstance(ln, dict):
            continue
        cm_, cn_ = _f(ln.get('mas')), _f(ln.get('menos'))
        if not (cm_ and cn_):
            continue
        j = int(np.argmin(np.abs((g.ts - foto.ts).dt.total_seconds().values)))
        q = g.iloc[j]
        pq = _probs([q.odds_over25, q.odds_under25], 1)
        pp = _probs([cm_, cn_], 1)
        rr = res.loc[mid]
        tot = float(rr.home_goals) + float(rr.away_goals)
        for i, (lado, cq, okk) in enumerate((('más de 2.5', cm_, tot > 2.5), ('menos de 2.5', cn_, tot < 2.5))):
            filas.append({'partido': mid, 'fecha': dia, 'liga': r0.league_key, 'mercado': 'Goles 2.5', 'lado': lado,
                          'cuota': cq, 'p_base': pp[i], 'p_ref': pq[i], 'cuota_ref': float([q.odds_over25,
                                                                                            q.odds_under25][i]),
                          'desfase_h': abs((q.ts - foto.ts).total_seconds()) / 3600, 'ok': int(okk)})
    x = pd.DataFrame(filas)
    x['coinciden'] = -1
    return x


# ============================================ M · casas mexicanas (cuotas_mx)
def _f(v):
    try:
        v = float(v)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def _compacta(casas):
    out = {}
    for c, m in casas.items():
        if c not in CASAS_MX or not isinstance(m, dict):
            continue
        e = {}
        h = m.get('HOME_DRAW_AWAY') or {}
        t = (_f(h.get('home')), _f(h.get('draw')), _f(h.get('away')))
        if all(t):
            e['1x2'] = t
        dc = m.get('DOUBLE_CHANCE') or {}
        t = (_f(dc.get('homeOrDraw')), _f(dc.get('awayOrDraw')), _f(dc.get('noDraw')))
        if all(t):
            e['dc'] = t
        ou = {}
        for ln in ((m.get('OVER_UNDER') or {}).get('lineas') or []):
            try:
                L = float(ln.get('linea'))
            except (TypeError, ValueError):
                continue
            if L in (1.5, 2.5, 3.5):
                t = (_f(ln.get('over')), _f(ln.get('under')))
                if all(t):
                    ou[L] = t
        if ou:
            e['ou'] = ou
        bt = m.get('BOTH_TEAMS_TO_SCORE') or {}
        t = (_f(bt.get('yes')), _f(bt.get('no')))
        if all(t):
            e['btts'] = t
        if e:
            out[c] = e
    return out


def mx_historial():
    cache = os.environ.get('V373_CACHE')
    fc = os.path.join(cache, '_v373_casas_mx.pkl') if cache else None
    if fc and os.path.exists(fc):
        return pd.read_pickle(fc)
    lg = subprocess.run(['git', 'log', '--format=%H %ct', '--reverse', '--', 'cuotas_mx.json'],
                        capture_output=True, check=True).stdout.decode().split()
    ver, meta = {}, {}
    for i, (h, ts) in enumerate(zip(lg[0::2], lg[1::2])):
        ts = int(ts)
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':cuotas_mx.json'], capture_output=True,
                                          check=True).stdout)
        except Exception:
            continue
        for eid, p in (d.get('partidos') or {}).items():
            if p.get('deporte') != 'futbol':
                continue
            try:
                ini = int(float(p.get('inicio')))
            except (TypeError, ValueError):
                continue
            if ts >= ini:
                continue
            datos = _compacta(p.get('casas') or {})
            if not datos:
                continue
            firma = repr(sorted((k, sorted(v.items(), key=str)) for k, v in datos.items()))
            L = ver.setdefault(eid, [])
            if L and L[-1][1] == firma:
                continue
            L.append((ts, firma, datos))
            meta[eid] = (ini, p.get('home'), p.get('away'), p.get('liga'))
        if i % 50 == 0:
            log('cuotas_mx: commit %d/%d, %d partidos' % (i, len(lg) // 2, len(ver)))
    filas = [{'eid': e, 'ts': ts, 'datos': datos, 'inicio': meta[e][0], 'home': meta[e][1],
              'away': meta[e][2], 'liga': meta[e][3]} for e, L in ver.items() for ts, _, datos in L]
    v = pd.DataFrame(filas)
    if fc:
        os.makedirs(cache, exist_ok=True)
        v.to_pickle(fc)
    return v


def resultados_fs():
    r = pd.concat([pd.read_csv('resultados_flashscore_reciente.csv.gz'),
                   pd.read_csv('resultados_flashscore.csv.gz')]).drop_duplicates('match_id')
    return r.set_index('match_id')[['gh', 'ga']]


MERCADOS_MX = (
    ('1X2', '1x2', (('local', lambda h, a: h > a), ('empate', lambda h, a: h == a), ('visita', lambda h, a: h < a)), 1),
    ('Doble oportunidad', 'dc', (('1X', lambda h, a: h >= a), ('X2', lambda h, a: h <= a), ('12', lambda h, a: h != a)), 2),
    ('Ambos marcan', 'btts', (('sí', lambda h, a: h > 0 and a > 0), ('no', lambda h, a: not (h > 0 and a > 0))), 1),
)


def _probs(t, suma):
    im = np.array([1 / v for v in t])
    return suma * im / im.sum()


def legs_mx(datos, gh, ga):
    """[(mercado, lado, {casa: (cuota, p)}, ok)] de una foto."""
    out = []
    for merc, k, lados, suma in MERCADOS_MX:
        pc = {c: (e[k], _probs(e[k], suma)) for c, e in datos.items() if k in e}
        if not pc:
            continue
        for i, (lado, f) in enumerate(lados):
            out.append((merc, lado, {c: (t[i], p[i]) for c, (t, p) in pc.items()}, int(f(gh, ga))))
    for L in (1.5, 2.5, 3.5):
        pc = {c: (e['ou'][L], _probs(e['ou'][L], 1)) for c, e in datos.items() if 'ou' in e and L in e['ou']}
        if not pc or gh + ga == L:
            continue
        for i, (lado, okk) in enumerate((('más de %.1f' % L, gh + ga > L), ('menos de %.1f' % L, gh + ga < L))):
            out.append(('Goles %.1f' % L, lado, {c: (t[i], p[i]) for c, (t, p) in pc.items()}, int(okk)))
    return out


def mexicanas(V, res, casa='Novibet'):
    ult = V.sort_values('ts').drop_duplicates('eid', keep='last')
    ult = ult[ult.eid.isin(res.index)]
    filas = []
    for r in ult.itertuples(index=False):
        rr = res.loc[r.eid]
        gh, ga = int(rr.gh), int(rr.ga)
        for merc, lado, pc, okk in legs_mx(r.datos, gh, ga):
            if casa not in pc or len(pc) < 3:
                continue
            ps = np.array([p for _, p in pc.values()])
            otras = [p for c, (_, p) in pc.items() if c != casa]
            cmax = max(pc.items(), key=lambda kv: kv[1][0])
            fila = {'partido': r.eid, 'fecha': pd.to_datetime(r.inicio, unit='s').normalize(),
                    'liga': r.liga, 'mercado': merc, 'lado': lado, 'cuota': pc[casa][0],
                    'p_base': pc[casa][1], 'p_ref': float(np.mean(otras)), 'p_cons': float(ps.mean()),
                    'cuota_max': cmax[1][0], 'casa_max': cmax[0], 'n_casas': len(pc), 'ok': okk,
                    'ts_foto': r.ts, 'inicio': r.inicio}
            for c in CASAS_MX:
                fila['c_' + c] = pc[c][0] if c in pc else np.nan
            filas.append(fila)
    x = pd.DataFrame(filas)
    x['fav_c'] = _fav(x, 'p_base')
    x['fav_r'] = _fav(x, 'p_ref')
    co = x[x.fav_c == 1][['partido', 'lado']].merge(x[x.fav_r == 1][['partido', 'lado']], on='partido')
    co = co.drop_duplicates('partido')
    x['coinciden'] = x.partido.map(dict(zip(co.partido, (co.lado_x == co.lado_y).astype(int))))
    x['coinciden'] = x.coinciden.fillna(-1).astype(int)
    return x


def boleto_una_casa(x, casa_base='Novibet'):
    """El boleto va en UNA casa. Cada día y para cada casa mexicana H: las N
    patas de más probabilidad del consenso (una por partido) con la cuota de
    H en el piso; se juega en la casa con mayor Π(p_consenso × cuota_H)
    (regla fija, sin mirar el resultado). Contra la base: la casa base elige y
    se juega en ella."""
    out = {}
    x = x.assign(dia=x.fecha.dt.strftime('%Y-%m-%d'))
    for piso in PISOS:
        fila = {}
        for n in NS:
            res_d, res_b, casas_el = [], [], {}
            for dia, g in x.groupby('dia'):
                mejor = None
                for c in CASAS_MX:
                    q = g[(g['c_' + c] >= piso) & (g['c_' + c] <= piso + ANCHO)]
                    q = q.assign(_pid=q.partido.astype(str)).sort_values(
                        ['p_cons', 'c_' + c, '_pid'], ascending=[False, False, True]).drop_duplicates('partido').head(n)
                    if len(q) < n:
                        continue
                    ev = float(np.sum(np.log(q.p_cons * q['c_' + c])))
                    if mejor is None or ev > mejor[0]:
                        mejor = (ev, c, int(q.ok.sum()), float(np.prod(q['c_' + c])))
                if mejor is not None:
                    res_d.append(mejor[2:])
                    casas_el[mejor[1]] = casas_el.get(mejor[1], 0) + 1
                b = g[(g.cuota >= piso) & (g.cuota <= piso + ANCHO)]
                b = b.assign(_pid=b.partido.astype(str)).sort_values(
                    ['p_base', 'cuota', '_pid'], ascending=[False, False, True]).drop_duplicates('partido').head(n)
                if len(b) == n:
                    res_b.append((int(b.ok.sum()), float(np.prod(b.cuota))))

            def _res(L):
                if not L:
                    return {'dias_con_boleto': 0}
                bien = np.array([a for a, _ in L])
                mom = np.array([m for _, m in L])
                ent = bien == n
                return {'dias_con_boleto': len(L), 'enteros': int(ent.sum()), 'pct_entero': _r(ent.mean(), 3),
                        'rojas_medias': _r((n - bien).mean(), 2), 'momio_mediano': _r(np.median(mom), 2),
                        'gan_100': {('x%.1f' % f): _r(100 * np.mean(np.where(ent, mom * f - 1, -1.0)), 1)
                                    for f in BOOST}}
            fila[n] = {'una_casa_mejor': _res(res_d), 'casas_elegidas': casas_el,
                       'base_' + casa_base: _res(res_b)}
        out['%.2f' % piso] = fila
    return out


# ============================== X · cruce Novibet ↔ Playdoit ↔ Pinnacle (barrido)
def _norm(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return ''.join(ch for ch in s.lower() if ch.isalnum())


def emparejar(V, S):
    """eid de cuotas_mx → match_id del barrido (nombres parecidos, ±1 día)."""
    try:
        import cuotas_multi as cm
        sim = cm._sim_club
    except Exception:
        sim = lambda a, b: 1.0 if _norm(a) == _norm(b) else 0.0
    mx = V.drop_duplicates('eid')[['eid', 'home', 'away', 'inicio']].copy()
    mx['dia'] = pd.to_datetime(mx.inicio, unit='s').dt.normalize()
    sn = S.drop_duplicates('match_id')[['match_id', 'home_team', 'away_team', 'match_date']]
    por_dia = {d: g for d, g in sn.groupby('match_date')}
    out = {}
    for r in mx.itertuples(index=False):
        cand = pd.concat([por_dia[d] for d in (r.dia - pd.Timedelta(days=1), r.dia, r.dia + pd.Timedelta(days=1))
                          if d in por_dia]) if any(d in por_dia for d in (r.dia - pd.Timedelta(days=1), r.dia,
                                                                             r.dia + pd.Timedelta(days=1))) else None
        if cand is None:
            continue
        nh, na = _norm(r.home), _norm(r.away)
        ex = cand[(cand.home_team.map(_norm) == nh) & (cand.away_team.map(_norm) == na)]
        if len(ex):
            out[r.eid] = ex.match_id.iloc[0]
            continue
        mejor, mid = 0.0, None
        for c in cand.itertuples(index=False):
            s1 = sim(r.home, c.home_team)
            if s1 < 0.8:
                continue
            s2 = sim(r.away, c.away_team)
            if s2 >= 0.8 and s1 + s2 > mejor:
                mejor, mid = s1 + s2, c.match_id
        if mid is not None:
            out[r.eid] = mid
    return out


def cruce(V, S, res, par):
    """Patas 1X2 y más/menos 2,5 con Novibet/mexicanas (foto más cercana) y
    Playdoit + Pinnacle del último barrido antes del inicio."""
    s = S[S.match_id.isin(set(par.values()))]
    s = s[s.bookmaker.isin(['Playdoit', 'Pinnacle'])]
    Vg = {e: g.sort_values('ts') for e, g in V[V.eid.isin(par)].groupby('eid')}
    sg = {m: g for m, g in s.groupby('match_id')}
    filas = []
    for eid, mid in par.items():
        if eid not in res.index or mid not in sg or eid not in Vg:
            continue
        vv = Vg[eid]
        ini = pd.to_datetime(int(vv.inicio.iloc[0]), unit='s')
        g = sg[mid]
        g = g[g.ts + pd.Timedelta(hours=1) <= ini]
        if g.empty:
            continue
        rr = res.loc[eid]
        gh, ga = int(rr.gh), int(rr.ga)
        for ref_casa in ('Playdoit', 'Pinnacle'):
            h = g[g.bookmaker == ref_casa].sort_values('ts')
            if h.empty:
                continue
            fila = h.iloc[-1]
            t_s = fila.ts
            # Pinnacle del MISMO barrido que Playdoit (para el cruce de tres)
            pin_mismo = g[(g.bookmaker == 'Pinnacle') & (g.ts == t_s)]
            vt = pd.to_datetime(vv.ts, unit='s')
            j = int(np.argmin(np.abs((vt - t_s).dt.total_seconds().values)))
            v = vv.iloc[j]
            desfase = abs((pd.to_datetime(v.ts, unit='s') - t_s).total_seconds()) / 3600
            for merc, lado, pc, okk in legs_mx(v.datos, gh, ga):
                if merc not in ('1X2', 'Goles 2.5'):
                    continue
                if merc == '1X2':
                    q = [fila.odds_home, fila.odds_draw, fila.odds_away]
                    i = ('local', 'empate', 'visita').index(lado)
                    pr = _devig3(q)
                    qp = None
                    if len(pin_mismo) and ref_casa == 'Playdoit':
                        o = pin_mismo.iloc[0]
                        qp = _devig3([o.odds_home, o.odds_draw, o.odds_away])
                else:
                    q = [fila.odds_over25, fila.odds_under25]
                    if not (pd.notna(q[0]) and pd.notna(q[1]) and q[0] > 1 and q[1] > 1):
                        continue
                    i = 0 if lado.startswith('más') else 1
                    pr = _probs(q, 1)
                    qp = None
                if pr is None:
                    continue
                cmax = max(pc.items(), key=lambda kv: kv[1][0])
                filas.append({'partido': eid, 'fecha': ini.normalize(), 'mercado': merc, 'lado': lado,
                              'ref_casa': ref_casa, 'cuota_ref': float(q[i]), 'p_ref_casa': float(pr[i]),
                              'p_pin_mismo': float(qp[i]) if qp is not None else np.nan,
                              'cuota_nov': pc['Novibet'][0] if 'Novibet' in pc else np.nan,
                              'p_nov': pc['Novibet'][1] if 'Novibet' in pc else np.nan,
                              'p_mx': float(np.mean([p for _, p in pc.values()])), 'n_mx': len(pc),
                              'cuota_mx_max': cmax[1][0], 'casa_mx_max': cmax[0],
                              'desfase_h': desfase, 'ok': okk})
    return pd.DataFrame(filas)


def _fav_cons(x):
    x = x.copy()
    x['fav_c'] = _fav(x, 'p_base')
    x['fav_r'] = _fav(x, 'p_ref')
    co = x[x.fav_c == 1][['partido', 'lado']].merge(x[x.fav_r == 1][['partido', 'lado']], on='partido')
    co = co.drop_duplicates('partido')
    x['coinciden'] = x.partido.map(dict(zip(co.partido, (co.lado_x == co.lado_y).astype(int))))
    x['coinciden'] = x.coinciden.fillna(-1).astype(int)
    return x


# ===================================================================== main
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    R = {'version': 'v373', 'hipotesis': 'H6 · cruce de casas: ir con el mercado, pero al mejor precio',
         'pisos': list(PISOS), 'ancho': ANCHO, 'bootstrap': NB}

    # ---------------------------------------------------------------- H
    H = historico()
    for fmt, nombre, nota in (('new', 'historico_cierre', 'casa = media de mercado de cierre (AvgC) contra '
                                                          'Pinnacle de cierre: simultáneos, prueba válida'),
                              ('main', 'historico_fuga', 'casa = Bet365 de antes del cierre contra Pinnacle de '
                                                         'cierre: Pinnacle sabe lo que pasó después (CLV); NO es '
                                                         'una regla utilizable, sólo el tamaño de la fuga')):
        x = H[H.formato == fmt].copy()
        R[nombre] = bloque(x, nombre, REGLAS_STD, {'nota': nota, 'ligas': sorted(x.liga.unique()),
                                                   'consenso': consenso_1x2(x, 'fav_c', 'fav_r'),
                                                   'logloss': logloss_1x2(x, ['p_base', 'p_ref'])},
                           con_boletos=(fmt == 'new'))
    R['historico_mas_menos_25'] = 'sin Pinnacle de más/menos en historico_*.csv: no se puede cruzar'
    del H

    # ---------------------------------------------------------------- P
    S = snapshots()
    x = playdoit_pinnacle(S)
    reg = dict(REGLAS_STD)
    reg['mercado_elige'] = ('p_mkt', lambda z: z.p_mkt.notna(), 'cuota')
    reg['valor_mercado'] = ('p_mkt', lambda z: z.cuota * z.p_mkt > 1.0, 'cuota')
    R['playdoit_pinnacle'] = bloque(x, 'playdoit_pinnacle', reg, {
        'nota': 'Playdoit y Pinnacle del MISMO barrido (odds_snapshots), día anterior o antes; mercado = media '
                'sin margen de Pinnacle, Bovada, DraftKings, Matchbook y Unibet presentes en ese barrido',
        'consenso': consenso_1x2(x, 'fav_c', 'fav_r'),
        'logloss': logloss_1x2(x.dropna(subset=['p_mkt']), ['p_base', 'p_ref', 'p_mkt']),
        'margen_playdoit': _r((1 / x.cuota).groupby(x.partido).sum().mean() - 1),
    })
    y = playdoit_mm25(S)
    regy = {k: REGLAS_STD[k] for k in ('ref_elige', 'valor', 'direccion')}
    for etq, q in (('todo', y), ('desfase_6h', y[y.desfase_h <= 6])):
        if q.partido.nunique() >= 60:
            R['playdoit_pinnacle_mm25_' + etq] = bloque(q, 'playdoit_pinnacle_mm25_' + etq, regy, {
                'nota': 'más/menos 2,5: tablero de Playdoit (última foto del día anterior o antes) contra el '
                        'barrido de Pinnacle más cercano; NO simultáneos',
                'desfase_mediano_h': _r(q.desfase_h.median(), 1),
                'margen_playdoit': _r((1 / q.cuota).groupby(q.partido).sum().mean() - 1),
                'margen_pinnacle': _r((1 / q.cuota_ref).groupby(q.partido).sum().mean() - 1)})

    # ---------------------------------------------------------------- M
    V = mx_historial()
    log('cuotas_mx: %d fotos distintas de %d partidos' % (len(V), V.eid.nunique()))
    res = resultados_fs()
    m = mexicanas(V, res)
    regm = {
        'ref_elige': ('p_ref', None, 'cuota'),
        'valor': ('p_ref', lambda z: z.cuota * z.p_ref > 1.0, 'cuota'),
        'direccion': ('p_ref', lambda z: z.p_ref > z.p_base, 'cuota'),
        'consenso': ('p_base', lambda z: z.coinciden == 1, 'cuota'),
        'discrepan': ('p_base', lambda z: z.coinciden == 0, 'cuota'),
        'mejor_precio': ('p_cons', None, 'cuota_max'),
        'mejor_precio_valor': ('p_cons', lambda z: z.cuota_max * z.p_cons > 1.0, 'cuota_max'),
    }
    mm = m.copy()
    R['mexicanas_novibet'] = bloque(mm, 'mexicanas_novibet', regm, {
        'nota': 'cinco casas mexicanas en la MISMA foto (cuotas_mx.json en git); se apuesta en Novibet; ref = media '
                'sin margen de las otras casas (≥ 2); mejor_precio = la casa que más paga (un parlay va en una '
                'casa: sus boletos son sólo orientativos)',
        'consenso': consenso_1x2(mm, 'fav_c', 'fav_r'),
        'logloss': logloss_1x2(mm, ['p_base', 'p_ref']),
        'casa_que_mas_paga': {c: int(n) for c, n in mm.casa_max.value_counts().items()},
        'por_mercado_universo': {k: int(v) for k, v in mm.mercado.value_counts().items()},
        'boleto_una_casa': boleto_una_casa(mm, 'Novibet'),
    })
    # la misma prueba apostando en 1xBet (la que más mercados cotiza: entra el más/menos)
    m1 = mexicanas(V, res, casa='1xBet')
    R['mexicanas_1xbet'] = bloque(m1, 'mexicanas_1xbet', regm, {
        'nota': 'igual que mexicanas_novibet, pero la casa base es 1xBet (cotiza más/menos 1,5/2,5/3,5)',
        'consenso': consenso_1x2(m1, 'fav_c', 'fav_r'),
        'logloss': logloss_1x2(m1, ['p_base', 'p_ref']),
        'por_mercado_universo': {k: int(v) for k, v in m1.mercado.value_counts().items()},
    })
    del m1

    # ---------------------------------------------------------------- X
    par = emparejar(V, S)
    log('cruce: %d partidos de cuotas_mx emparejados con el barrido' % len(par))
    c = cruce(V, S, res, par)
    out = {'emparejados': len(par), 'patas': int(len(c))}
    if len(c):
        # X1 · Playdoit (ref) contra Novibet: ¿la otra casa señala el lado?
        a = c[(c.ref_casa == 'Playdoit') & (c.mercado == '1X2') & c.p_nov.notna()].copy()
        a = a.rename(columns={'cuota_ref': 'cuota', 'p_ref_casa': 'p_base'})
        a['p_ref'] = a.p_nov
        a['p_dos'] = (a.p_base + a.p_nov) / 2
        a['cuota_dos'] = np.maximum(a.cuota, a.cuota_nov)
        a = _fav_cons(a)
        regx = {
            'novibet_elige': ('p_ref', None, 'cuota'),
            'valor_vs_novibet': ('p_ref', lambda z: z.cuota * z.p_ref > 1.0, 'cuota'),
            'novibet_ve_mas': ('p_ref', lambda z: z.p_ref > z.p_base, 'cuota'),
            'consenso': ('p_base', lambda z: z.coinciden == 1, 'cuota'),
            'discrepan': ('p_base', lambda z: z.coinciden == 0, 'cuota'),
            'dos_casas_mejor_precio': ('p_dos', None, 'cuota_dos'),
            'pinnacle_mismo_barrido_valor': ('p_pin_mismo', lambda z: z.cuota * z.p_pin_mismo > 1.0, 'cuota'),
        }
        for etq, q in (('todo', a), ('desfase_3h', a[a.desfase_h <= 3])):
            if q.partido.nunique() >= 60:
                out['playdoit_vs_novibet_' + etq] = bloque(q, 'playdoit_vs_novibet_' + etq, regx, {
                    'desfase_mediano_h': _r(q.desfase_h.median(), 1),
                    'consenso': consenso_1x2(q, 'fav_c', 'fav_r'),
                    'logloss': logloss_1x2(q.dropna(subset=['p_pin_mismo']), ['p_base', 'p_ref', 'p_pin_mismo'])})
        # X2 · Pinnacle (ref) contra Novibet: 1X2
        b = c[c.ref_casa == 'Pinnacle'].copy()
        b = b[b.cuota_nov.notna() & (b.mercado == '1X2')].rename(columns={'cuota_nov': 'cuota', 'p_nov': 'p_base'})
        b['p_ref'] = b.p_ref_casa
        b = _fav_cons(b)
        regp = {
            'pinnacle_elige': ('p_ref', None, 'cuota'),
            'valor_pinnacle': ('p_ref', lambda z: z.cuota * z.p_ref > 1.0, 'cuota'),
            'direccion': ('p_ref', lambda z: z.p_ref > z.p_base, 'cuota'),
            'pinnacle_elige_mejor_mx': ('p_ref', None, 'cuota_mx_max'),
            'valor_pinnacle_mejor_mx': ('p_ref', lambda z: z.cuota_mx_max * z.p_ref > 1.0, 'cuota_mx_max'),
        }
        for etq, q in (('todo', b), ('desfase_3h', b[b.desfase_h <= 3])):
            if q.partido.nunique() >= 60:
                k = 'pinnacle_vs_novibet_1x2_%s' % etq
                out[k] = bloque(q, k, regp, {'desfase_mediano_h': _r(q.desfase_h.median(), 1),
                                             'consenso': consenso_1x2(q, 'fav_c', 'fav_r'),
                                             'logloss': logloss_1x2(q, ['p_base', 'p_ref'])})
        # X3 · Pinnacle (ref) contra la MEJOR cuota mexicana: 1X2 y más/menos 2,5
        e = c[(c.ref_casa == 'Pinnacle') & (c.n_mx >= 2)].copy()
        e = e.rename(columns={'cuota_mx_max': 'cuota', 'p_mx': 'p_base'})
        e['p_ref'] = e.p_ref_casa
        e['coinciden'] = -1
        rege = {
            'pinnacle_elige': ('p_ref', None, 'cuota'),
            'valor_pinnacle': ('p_ref', lambda z: z.cuota * z.p_ref > 1.0, 'cuota'),
            'direccion': ('p_ref', lambda z: z.p_ref > z.p_base, 'cuota'),
        }
        for merc in ('1X2', 'Goles 2.5'):
            for etq, q in (('todo', e), ('desfase_3h', e[e.desfase_h <= 3])):
                qq = q[q.mercado == merc]
                if qq.partido.nunique() >= 60:
                    k = 'pinnacle_vs_mejor_mx_%s_%s' % ('1x2' if merc == '1X2' else 'mm25', etq)
                    out[k] = bloque(qq, k, rege, {'desfase_mediano_h': _r(qq.desfase_h.median(), 1),
                                                  'nota': 'se apuesta en la mexicana que más paga; la casa base '
                                                          'es el consenso mexicano sin margen'})
    # comprobación del emparejamiento: el marcador de Flashscore contra el del histórico
    rh = resultados_hist(S.league_key.unique())
    mm = [(int(res.loc[e_].gh), int(res.loc[e_].ga), float(rh.loc[m_].home_goals), float(rh.loc[m_].away_goals))
          for e_, m_ in par.items() if e_ in res.index and m_ in rh.index]
    if mm:
        a_ = np.array(mm)
        out['concordancia_marcador'] = {'n': int(len(a_)), 'igual': _r(((a_[:, 0] == a_[:, 2]) &
                                                                         (a_[:, 1] == a_[:, 3])).mean())}
    R['cruce'] = out

    json.dump(R, open('_v373_casas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    log('escrito _v373_casas.json')
    imprimir(R)


def imprimir(R):
    def bloque_txt(nombre, B):
        if not isinstance(B, dict) or 'pisos' not in B:
            return
        u = B['universo']
        print('\n== %s · %d partidos, %d días (%s → %s, corte %s)' % (nombre, u['partidos'], u['dias'], u['desde'],
                                                                      u['hasta'], u['corte_AB']))
        for k in ('consenso', 'logloss'):
            if B.get(k):
                print('   %s: %s' % (k, B[k]))
        if B.get('senal'):
            print('   señal (p_ref − p_casa → acierto/casa/ref/gan):')
            for t, v in B['senal'].items():
                print('     %-14s n %6d acierto %.3f casa %.3f ref %.3f cuota %.2f gan %+.1f'
                      % (t, v['n'], v['acierto'], v['casa'], v['ref'], v['cuota'], v['gan_100']))
        for piso, fila in B['pisos'].items():
            print('  piso %s' % piso)
            for regla, f in fila.items():
                t = f['todo']
                if t.get('n', 0) < 20:
                    print('    %-28s n %d' % (regla, t.get('n', 0)))
                    continue
                A, Bb = f['A'], f['B']
                print('    %-28s n %6d (%.2f/día) acierto %.3f [A %s B %s] cuota %.2f gan %+.1f (p5 %s) | '
                      'dif acierto A %s B %s (p5 %s/%s) · dif gan A %s B %s (p5 %s/%s) %s'
                      % (regla, t['n'], t['patas_por_dia'], t['acierto'], A.get('acierto'), Bb.get('acierto'),
                         t['cuota'], t['gan_100'], t['gan_p5'], A.get('dif_acierto'), Bb.get('dif_acierto'),
                         A.get('dif_acierto_p5'), Bb.get('dif_acierto_p5'), A.get('dif_gan_100'),
                         Bb.get('dif_gan_100'), A.get('dif_gan_p5'), Bb.get('dif_gan_p5'), f.get('veredicto', '')))
                if f.get('misma_pata_en_casa_base'):
                    print('        misma pata en la casa base:', f['misma_pata_en_casa_base'])
                bo = f.get('boletos') or {}
                if bo and regla in ('base', 'valor', 'ref_elige', 'mejor_precio', 'dos_casas_mejor_precio'):
                    print('        boletos', {n: (v.get('enteros'), v.get('dias_con_boleto'), v.get('rojas_medias'),
                                              (v.get('gan_100') or {}).get('x1.0'), (v.get('gan_100') or {}).get('x1.2'))
                                          for n, v in bo.items() if v.get('dias_con_boleto')})
    for k, v in R.items():
        if isinstance(v, dict) and 'pisos' in v:
            bloque_txt(k, v)
            if v.get('boleto_una_casa'):
                print('  boleto en una sola casa (la de mayor Π p×cuota) contra la base:')
                for piso, fila in v['boleto_una_casa'].items():
                    for n, w in fila.items():
                        u, b = w['una_casa_mejor'], w[[kk for kk in w if kk.startswith('base_')][0]]
                        print('    %s N=%s  una casa: %s/%s enteros, gan %s | base: %s/%s, gan %s | casas %s'
                              % (piso, n, u.get('enteros'), u.get('dias_con_boleto'), u.get('gan_100'),
                                 b.get('enteros'), b.get('dias_con_boleto'), b.get('gan_100'), w['casas_elegidas']))
    for k, v in (R.get('cruce') or {}).items():
        bloque_txt('cruce.' + k, v)
    print('\ncruce:', {k: v for k, v in (R.get('cruce') or {}).items() if not isinstance(v, dict) or 'pisos' not in v})


if __name__ == '__main__':
    main()
