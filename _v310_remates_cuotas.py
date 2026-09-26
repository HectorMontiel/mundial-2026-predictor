# -*- coding: utf-8 -*-
"""
v310 — ¿GANA DINERO APOSTAR REMATES POR JUGADOR? MEDIDO CON LAS CUOTAS REALES.

El usuario: «¿no quedamos que podías medir con el histórico? Puedes rescatar
los remates históricos y compararlos con el resultado final. Tenemos muchos
datos, no sé por qué no los ocupas».

Tenía razón. La v308 dejó esto «pendiente hasta tener 6-8 semanas de
cuotas», pero las cuotas YA existían: el bot commitea `lineas_jugador_dia.json`
(la línea principal de Playdoit y su cuota del «Más», por jugador) desde el
2026-08-23. Son 61 fotos en el historial de git, ~140.000 líneas.

CÓMO SE MIDE, SIN MIRAR EL FUTURO
  · el modelo de producción (`remates_ml`: LightGBM Poisson + cola binomial
    negativa, el M2 de la v308) se entrena SÓLO con partidos anteriores al
    CORTE (2026-08-22) y predice los posteriores con sus rasgos, que ya son
    de partidos previos (`_v308_remates_jugador.rasgos`);
  · la cuota es la de la PRIMERA foto en la que aparece el partido (la más
    lejana al inicio: nunca es un precio en vivo);
  · el resultado es el remate real del jugador (fondo FotMob `_v308_fondo`);
  · el partido se casa por los DOS equipos y la fecha, y el jugador DENTRO
    de ese partido (la primera versión casaba por apellido y pegaba a
    «Mathias Llontop Díaz», cuota 9,5, con otro Díaz de LaLiga: inflaba
    todo);
  · la cuota se toma por la mañana, SIN saber la alineación: se apuesta a
    los TITULARES PROBABLES (titular en ≥60 % de sus últimas apariciones,
    con al menos 3), y se liquida con lo que de verdad jugó — si entró de
    suplente cuenta con sus minutos; si no jugó, la apuesta es nula (se
    devuelve) y no entra en la cuenta. Condicionar a «fue titular» sería
    usar información que la cuota de la mañana no tenía.
Se apuesta el «Más» de la línea cuando p·cuota − 1 supera un umbral. ROI por
tramos de fecha (70 % elección / 30 % juicio) y bootstrap por PARTIDO.

Uso: python _v310_remates_cuotas.py      (escribe _v310_remates_cuotas.json)
"""
from __future__ import annotations

import json
import subprocess
import sys
import unicodedata

import numpy as np
import pandas as pd

import _v308_remates_jugador as v8

CORTE = pd.Timestamp('2026-08-22')
SALIDA = '_v310_remates_cuotas.json'
B = 2000


def _n(t) -> str:
    t = unicodedata.normalize('NFKD', str(t or ''))
    return ' '.join(t.encode('ascii', 'ignore').decode('ascii').lower()
                    .replace('-', ' ').replace('.', ' ').split())


def fotos() -> pd.DataFrame:
    """Todas las líneas de jugador de todas las fotos del historial."""
    hs = subprocess.check_output(
        ['git', 'log', '--reverse', '--format=%h %cI', '--',
         'lineas_jugador_dia.json'], text=True).split('\n')
    filas = []
    for l in hs:
        if not l.strip():
            continue
        h, t = l.split()
        try:
            d = json.loads(subprocess.check_output(
                ['git', 'show', h + ':lineas_jugador_dia.json']))
        except Exception:
            continue
        ts = pd.Timestamp(t).tz_convert('UTC').tz_localize(None)
        for k, p in (d.get('partidos') or {}).items():
            for jug, x in p.items():
                if not isinstance(x, dict):
                    continue
                for obj in ('tot', 'on'):
                    o = x.get(obj)
                    if not isinstance(o, dict):
                        continue
                    lineas = {}
                    if o.get('principal') is not None and o.get('cuota'):
                        lineas[float(o['principal'])] = float(o['cuota'])
                    for ln, c in (o.get('lineas') or {}).items():
                        try:
                            cc = c.get('mas') if isinstance(c, dict) else c
                            if cc:
                                lineas[float(ln)] = float(cc)
                        except (TypeError, ValueError):
                            continue
                    for ln, c in lineas.items():
                        filas.append({'foto': ts, 'partido': k,
                                      'liga': p.get('clave_liga'),
                                      'jugador': jug, 'jn': _n(jug),
                                      'obj': obj, 'linea': ln, 'cuota': c})
    f = pd.DataFrame(filas)
    # la PRIMERA foto de cada (partido, jugador, objetivo, línea)
    f = (f.sort_values('foto')
         .drop_duplicates(['partido', 'jn', 'obj', 'linea'], keep='first'))
    return f


def predicciones():
    """λ y α de sot y tiros para los titulares posteriores al CORTE."""
    d, e = v8.cargar()
    d = v8.rasgos(d, e)
    ok = d['lam_eq_sh'].notna() & d['lam_eq_sot'].notna() & (d['rol'] != 'POR')
    tit = d[(d['t'] == 1) & ok].copy()
    ent = tit[tit['fecha'] < CORTE]
    # a la prueba entran TODOS los que jugaron (titulares y suplentes); la
    # apuesta se decide con lo que se sabía antes: ¿es titular probable?
    pru = d[ok & (d['fecha'] >= CORTE)].copy()
    pru['probable'] = ((pru['apar'] >= 3)
                       & (pru['tits'] >= 0.6 * pru['apar']))
    for col in ('sot', 'sh'):
        lams, alphas, _m = v8.predecir(ent, pru, col)
        pru['lam_' + col] = lams['M1']
        pru['alpha_' + col] = alphas['M2']
    pru['jn'] = pru['n'].map(_n)
    return pru


def partidos_fondo() -> pd.DataFrame:
    """mid -> fecha, local y visitante con nombre (el fondo los trae)."""
    import glob
    import gzip
    filas = []
    for ruta in glob.glob('_v308_fondo/*.jsonl.gz'):
        with gzip.open(ruta, 'rt', encoding='utf-8') as fh:
            for linea in fh:
                try:
                    r = json.loads(linea)
                except Exception:
                    continue
                if r.get('fecha', '') < str(CORTE.date()):
                    continue
                filas.append({'mid': r['mid'], 'fecha': pd.Timestamp(r['fecha']),
                              'h': (r.get('h') or {}).get('eq'),
                              'a': (r.get('a') or {}).get('eq')})
    return pd.DataFrame(filas)


def _jug_casa(jn: str, nombres: list):
    """El jugador de FotMob (nombre corto) dentro del nombre completo de
    Playdoit: todas las palabras de uno dentro del otro, y único."""
    tj = set(jn.split())
    hits = [n for n in nombres if n and (set(n.split()) <= tj
                                         or tj <= set(n.split()))]
    return hits[0] if len(hits) == 1 else None


def casar(f: pd.DataFrame, pru: pd.DataFrame) -> pd.DataFrame:
    """Cada línea con su partido real: los DOS equipos (emparejador de
    clubes, listón 0,8) y la fecha entre la foto y 4 días después; el
    jugador, dentro de ese partido."""
    import cuotas_multi as cm
    pf = partidos_fondo()
    por_mid = {k: g for k, g in pru.groupby('mid')}
    mid_de = {}
    for clave in f['partido'].unique():
        fotos_k = f[f['partido'] == clave]
        dia = fotos_k['foto'].min().normalize()
        if '|' not in clave:
            continue
        hh, aa = clave.split('|', 1)
        c = pf[(pf['fecha'] >= dia) & (pf['fecha'] <= dia + pd.Timedelta(days=4))]
        mejor, ms = None, 0.0
        for r in c.itertuples(index=False):
            s_ = min(cm._sim_club(hh, _n(r.h)), cm._sim_club(aa, _n(r.a)))
            if s_ > ms:
                mejor, ms = r.mid, s_
        if mejor is not None and ms >= 0.8:
            mid_de[clave] = mejor
    print('partidos casados:', len(mid_de), 'de', f['partido'].nunique())
    fuera = []
    for r in f.itertuples(index=False):
        mid = mid_de.get(r.partido)
        g = por_mid.get(mid)
        if g is None:
            continue
        quien = _jug_casa(r.jn, list(g['jn'].unique()))
        if quien is None:
            continue                 # no jugó (nula) o nombre ambiguo
        m = g[g['jn'] == quien].iloc[0]
        if not m['probable']:
            continue                 # la tarjeta sólo ofrece titulares probables
        col = 'sot' if r.obj == 'on' else 'sh'
        k = int(np.floor(r.linea)) + 1
        p = float(v8.p_ge_nb(np.array([m['lam_' + col]]), k,
                             m['alpha_' + col])[0])
        fuera.append({'fecha': m['fecha'], 'mid': m['mid'], 'liga': m['liga'],
                      'jugador': r.jugador, 'obj': r.obj, 'linea': r.linea,
                      'k': k, 'cuota': r.cuota, 'p': p,
                      'real': int(m[col] >= k), 'rol': m['rol'],
                      'titular': int(m['t']), 'minutos': m['min']})
    return pd.DataFrame(fuera)


def roi(g: pd.DataFrame, rng, b=B) -> dict:
    if g.empty:
        return {'n': 0}
    gan = g['real'] * g['cuota'] - 1
    mids = g['mid'].unique()
    por = gan.groupby(g['mid']).agg(['sum', 'size'])
    s, n = por['sum'].reindex(mids).values, por['size'].reindex(mids).values
    bs = []
    for _ in range(b):
        i = rng.integers(0, len(mids), len(mids))
        bs.append(s[i].sum() / max(n[i].sum(), 1))
    return {'n': int(len(g)), 'partidos': int(len(mids)),
            'acierto': round(float(g['real'].mean()), 4),
            'p_media': round(float(g['p'].mean()), 4),
            'cuota_media': round(float(g['cuota'].mean()), 3),
            'roi': round(float(gan.mean()), 4),
            'p5': round(float(np.percentile(bs, 5)), 4),
            'p95': round(float(np.percentile(bs, 95)), 4)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    f = fotos()
    print('líneas con precio (primera foto):', len(f))
    pru = predicciones()
    print('titulares posteriores al corte:', len(pru))
    x = casar(f, pru)
    print('líneas casadas con su partido real:', len(x))
    x = x.sort_values('fecha').reset_index(drop=True)
    q70 = x['fecha'].quantile(0.7)
    x['tramo'] = np.where(x['fecha'] <= q70, 'eleccion', 'juicio')
    x['ev'] = x['p'] * x['cuota'] - 1
    x['imp'] = 1 / x['cuota']
    rng = np.random.default_rng(310)
    doc = {'corte_modelo': str(CORTE.date()), 'corte_70': str(q70.date()),
           'lineas': int(len(x)), 'partidos': int(x['mid'].nunique())}

    # calibración del modelo y de la casa sobre TODAS las líneas con precio
    cal = {}
    for obj in ('on', 'tot'):
        g = x[x['obj'] == obj]
        bins = pd.cut(g['p'], [0, .2, .3, .4, .5, .6, .7, .8, .9, 1])
        cal[obj] = {
            'n': int(len(g)),
            'brier_modelo': round(float(((g['p'] - g['real']) ** 2).mean()), 4),
            'brier_casa': round(float(((g['imp'] - g['real']) ** 2).mean()), 4),
            'bandas': {str(k): {'n': int(len(v)),
                                'p': round(float(v['p'].mean()), 3),
                                'real': round(float(v['real'].mean()), 3)}
                       for k, v in g.groupby(bins, observed=True)}}
    doc['calibracion'] = cal

    reglas = {
        'todas_las_lineas': lambda g: g,
        'ev>0': lambda g: g[g['ev'] > 0],
        'ev>5%': lambda g: g[g['ev'] > .05],
        'ev>10%': lambda g: g[g['ev'] > .10],
        'app_v308 (5%<ev<40%)': lambda g: g[(g['ev'] > .05) & (g['ev'] < .40)],
        'p>=60% y ev>0': lambda g: g[(g['p'] >= .6) & (g['ev'] > 0)],
        'p>=60% y ev>5%': lambda g: g[(g['p'] >= .6) & (g['ev'] > .05)],
        'p>=50%, cuota>=1.5 y ev>5%': lambda g: g[(g['p'] >= .5)
                                                   & (g['cuota'] >= 1.5)
                                                   & (g['ev'] > .05)],
    }
    res = {}
    for obj in ('on', 'tot', 'ambos'):
        g0 = x if obj == 'ambos' else x[x['obj'] == obj]
        res[obj] = {}
        for nom, fn in reglas.items():
            g = fn(g0)
            res[obj][nom] = {t: roi(g[g['tramo'] == t], rng)
                             for t in ('eleccion', 'juicio')}
            res[obj][nom]['total'] = roi(g, rng)
    doc['reglas'] = res
    # por línea (a puerta 0.5 / 1.5, tiros 0.5 .. 2.5)
    doc['por_linea'] = {
        '%s %.1f' % (o, l): roi(g[g['ev'] > .05], rng, 500)
        for (o, l), g in x.groupby(['obj', 'linea']) if len(g) >= 200}
    doc['por_liga'] = {lg: roi(g[g['ev'] > .05], rng, 500)
                       for lg, g in x.groupby('liga') if len(g) >= 300}
    json.dump(doc, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1)
    print(json.dumps({k: doc[k] for k in ('lineas', 'partidos', 'corte_70')},
                     ensure_ascii=False))
    for obj in res:
        for nom, r in res[obj].items():
            e, j = r['eleccion'], r['juicio']
            print('%-6s %-28s n=%5s roi=%7s p5=%7s | juicio n=%5s roi=%7s p5=%7s'
                  % (obj, nom, e.get('n'), e.get('roi'), e.get('p5'),
                     j.get('n'), j.get('roi'), j.get('p5')))
    print(json.dumps(cal, ensure_ascii=False)[:3000])


if __name__ == '__main__':
    main()
