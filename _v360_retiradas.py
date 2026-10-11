#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v360 — Las «se mete» que se retiraron antes del pitido: ¿cuáles siguen valiendo?

El usuario, con el marcador delante (🎯 al pitido 78 %, 📌 primera anunciada
82 %): «de todas esas recomendadas que ya no tenemos, ¿cuáles todavía pueden
funcionar y cuáles no? Prueba algoritmos, plantéate hipótesis, compruébalas
con simulaciones y validaciones, y dame una metodología».

Datos: las fotos del precálculo (`pronostico_dia.json`, una cada ~2 h, en el
historial de git) y los partidos de fútbol acabados con marcador
(`jugados_dia.json` / `jugados_ayer.json`). Para cada partido:

  · las que se dijeron «se mete» en alguna foto antes del pitido;
  · las que quedaron al pitido (la última foto antes del inicio);
  · cada RETIRADA, con su estado en la última foto: sigue como «meter» pero
    desplazada por otra, sigue sin «meter», o ya ni aparece; y cómo se
    movieron su probabilidad y su cuota desde que se anunció.

Hipótesis (se miden en dos mitades de días, con bootstrap de la diferencia):
  H1 las retiradas aciertan igual que las que se quedan;
  H2 las retiradas por DESPLAZAMIENTO (siguen «meter» al final) aciertan más;
  H3 si la cuota BAJÓ (el mercado se movió a su favor) aciertan más;
  H4 si la probabilidad de la casa / app SUBIÓ o se mantuvo, aciertan más;
  H5 las que estuvieron anunciadas más fotos (más estables) aciertan más;
  H6 por mercado;
  H7 un modelo (regresión logística) con todo lo anterior, elegido con la
     primera mitad y juzgado con la segunda.
Escribe `_v360_retiradas.pkl` y `_v360_retiradas.json`.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

import _v343_estabilidad as E

rng = np.random.default_rng(360)
DESDE = '2026-10-01T00:00'
CACHE = '_v360_fotos.json'


def fotos():
    """{partido: [(ts, recos, por_mercado)]} con lo necesario de cada foto."""
    viejo = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {'hechos': [], 'out': {}}
    hechos, out = set(viejo['hechos']), viejo['out']
    hs = subprocess.run(['git', 'log', '--reverse', '--format=%H %cI', '--since=' + DESDE,
                         'origin/main', '--', 'pronostico_dia.json'],
                        capture_output=True, text=True).stdout.split('\n')
    campos = ('apuesta', 'mercado', 'bloque', 'etiqueta', 'linea', 'cuota', 'prob',
              'prob_meter', 'p_mercado', 'veredicto_vp', 'elite', 'tercera', 'motivo')
    for linea in [x for x in hs if x.strip()]:
        h, cuando = linea.split()
        if h in hechos:
            continue
        try:
            d = E._git_json(h, 'pronostico_dia.json')
        except Exception:
            hechos.add(h)
            continue
        for x in ((d.get('decisiones') or {}).get('listas') or {}).get('pronosticos') or []:
            recos = x.get('recomendadas_tarjeta') or x.get('recomendadas') or []
            otras = x.get('otras_tarjeta') or []
            pm = x.get('por_mercado') or {}
            par = str((x.get('llave') or [''])[0])
            out.setdefault(par, []).append([
                cuando,
                [{k: r.get(k) for k in campos} for r in recos],
                [{k: r.get(k) for k in campos} for r in otras],
                {m: {k: (r or {}).get(k) for k in campos} for m, r in pm.items()
                 if isinstance(r, dict)}])
        hechos.add(h)
    json.dump({'hechos': sorted(hechos), 'out': out}, open(CACHE, 'w', encoding='utf-8'),
              ensure_ascii=False)
    return out


def _met(recos):
    m = [r for r in recos if r.get('veredicto_vp') == 'meter']
    return [r for r in m if not r.get('tercera')][:2] + [r for r in m if r.get('tercera')][:1]


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def construir():
    E.DESDE = DESDE
    E.pg.de_partido = lambda *a, **k: None
    ft = fotos()
    filas = []
    for p in E.jugados():
        if p.get('goles_home') is None or str(p.get('deporte') or 'Fútbol') != 'Fútbol':
            continue
        par, ini = str(p.get('partido')), p.get('inicio')
        if par not in ft or not ini:
            continue
        t0 = E._ts(ini)
        f = sorted((x for x in ft[par] if E._ts(x[0]) < t0), key=lambda x: x[0])
        if len(f) < 2:
            continue
        ts_fin, recos_fin, otras_fin, pm_fin = f[-1]
        final = {r['apuesta'] for r in _met(recos_fin)}
        if not final:
            continue
        info = {}
        for ts, recos, _o, _pm in f:
            for k, r in enumerate(_met(recos)):
                ap = r['apuesta']
                if ap not in info:
                    info[ap] = {'primera': r, 'ts_primera': ts, 'fotos': 0, 'puesto': k + 1}
                info[ap]['fotos'] += 1
                info[ap]['ultima'] = r
                info[ap]['ts_ultima'] = ts
        for ap, inf in info.items():
            r0, r1 = inf['primera'], inf['ultima']
            # el estado al final
            fin = next((r for r in recos_fin + otras_fin if r.get('apuesta') == ap), None)
            if fin is None:
                q = pm_fin.get(str(r0.get('mercado')))
                fin = q if q and q.get('apuesta') == ap else None
            if ap in final:
                estado = 'se_queda'
            elif fin is not None and fin.get('veredicto_vp') == 'meter':
                estado = 'desplazada'
            elif fin is not None:
                estado = 'no_meter_al_final'
            else:
                estado = 'desaparecida'
            liq = E.liquidar(p, [dict(r0)])
            if not liq:
                continue
            p0 = _f(r0.get('prob_meter')) or _f(r0.get('prob'))
            c0 = _f(r0.get('cuota'))
            pf = (_f(fin.get('prob_meter')) or _f(fin.get('prob'))) if fin else None
            cf = _f(fin.get('cuota')) if fin else None
            filas.append({
                'partido': par, 'dia': str(t0.date()), 'apuesta': ap,
                'mercado': str(r0.get('mercado')), 'estado': estado,
                'retirada': int(ap not in final), 'verde': liq[0][1],
                'p0': p0, 'c0': c0, 'pm0': _f(r0.get('p_mercado')),
                'pf': pf, 'cf': cf, 'pmf': _f(fin.get('p_mercado')) if fin else None,
                'fotos': inf['fotos'], 'puesto': inf['puesto'],
                'elite': bool(r0.get('elite')),
                'horas_retiro': (t0 - E._ts(inf['ts_ultima'])).total_seconds() / 3600,
                'horas_anuncio': (t0 - E._ts(inf['ts_primera'])).total_seconds() / 3600,
                'motivo_fin': str((fin or {}).get('motivo') or '')})
    return pd.DataFrame(filas)


def dif(a, b, n=2000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 10 or len(b) < 10:
        return None
    ds = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean()
          for _ in range(n)]
    return [round(float(np.mean(ds)), 4), round(float(np.percentile(ds, 5)), 4),
            round(float(np.percentile(ds, 95)), 4)]


def grupo(x):
    return {'n': int(len(x)), 'acierto': round(float(x.verde.mean()), 4) if len(x) else None}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = construir()
    d.to_pickle('_v360_retiradas.pkl')
    dias = sorted(d.dia.unique())
    corte = dias[len(dias) // 2]
    d['tramo'] = np.where(d.dia < corte, 'elige', 'juzga')
    print('días', dias[0], '→', dias[-1], 'corte', corte, '| apuestas', len(d),
          '| retiradas', int(d.retirada.sum()))
    out = {'dias': [dias[0], dias[-1]], 'corte': corte}
    ret, que = d[d.retirada == 1], d[d.retirada == 0]
    d['dp'] = d.pf - d.p0
    d['dc'] = d.cf - d.c0
    ret = d[d.retirada == 1]
    hip = {
        'H1 retiradas (todas)': (ret, que),
        'H2 desplazada (sigue «meter» al final)': (ret[ret.estado == 'desplazada'], que),
        'H2b no «meter» al final': (ret[ret.estado == 'no_meter_al_final'], que),
        'H2c desaparecida': (ret[ret.estado == 'desaparecida'], que),
        'H3 la cuota bajó (≥ 0,03)': (ret[ret.dc <= -0.03], que),
        'H3b la cuota subió (≥ 0,03)': (ret[ret.dc >= 0.03], que),
        'H4 la prob. final ≥ 0,74': (ret[ret.pf >= 0.74], que),
        'H4b la prob. final < 0,70': (ret[ret.pf < 0.70], que),
        'H5 anunciada 3+ fotos': (ret[ret.fotos >= 3], que),
        'H5b anunciada 1 foto': (ret[ret.fotos == 1], que),
        'H8 prob. al anunciar ≥ 0,80': (ret[ret.p0 >= 0.80], que),
        'H9 retirada a ≤ 4 h del pitido': (ret[ret.horas_retiro <= 4], que),
    }
    out['hipotesis'] = {}
    print('\n%-42s %-18s %-18s %s' % ('hipótesis (retiradas que…)', 'elige n/acierto',
                                      'juzga n/acierto', 'dif. contra las que se quedan (juzga: media, p5, p95)'))
    for nombre, (x, base) in hip.items():
        r = {}
        for tr in ('elige', 'juzga'):
            xa, xb = x[x.tramo == tr], base[base.tramo == tr]
            r[tr] = dict(grupo(xa), base=grupo(xb)['acierto'], dif=dif(xa.verde, xb.verde))
        out['hipotesis'][nombre] = r
        print('%-42s %-18s %-18s %s' % (nombre, (r['elige']['n'], r['elige']['acierto']),
                                        (r['juzga']['n'], r['juzga']['acierto']), r['juzga']['dif']))
    print('\nse quedan:', {tr: grupo(que[que.tramo == tr]) for tr in ('elige', 'juzga')})
    out['se_quedan'] = {tr: grupo(que[que.tramo == tr]) for tr in ('elige', 'juzga')}
    # H6 por mercado
    out['por_mercado'] = {}
    for m, g in ret.groupby('mercado'):
        out['por_mercado'][m] = {tr: grupo(g[g.tramo == tr]) for tr in ('elige', 'juzga')}
    print('por mercado (retiradas):', json.dumps(out['por_mercado'], ensure_ascii=False))
    # H7 modelo
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        X = pd.DataFrame({'p0': ret.p0.fillna(0.75), 'c0': ret.c0.fillna(1.25),
                          'pf': ret.pf.fillna(ret.p0).fillna(0.75), 'dp': ret.dp.fillna(0),
                          'dc': ret.dc.fillna(0), 'fotos': np.log1p(ret.fotos),
                          'desplazada': (ret.estado == 'desplazada').astype(float),
                          'desaparecida': (ret.estado == 'desaparecida').astype(float),
                          'horas': np.log1p(ret.horas_retiro.clip(lower=0))})
        el, ju = ret.tramo == 'elige', ret.tramo == 'juzga'
        m = LogisticRegression(max_iter=2000, C=0.5).fit(X[el], ret.verde[el])
        pr = m.predict_proba(X)[:, 1]
        u = float(np.median(pr[el]))
        out['modelo'] = {'auc_elige': round(float(roc_auc_score(ret.verde[el], pr[el])), 3),
                         'auc_juzga': round(float(roc_auc_score(ret.verde[ju], pr[ju])), 3),
                         'arriba_juzga': grupo(ret[ju & (pr >= u)]),
                         'abajo_juzga': grupo(ret[ju & (pr < u)]),
                         'coef': dict(zip(X.columns, np.round(m.coef_[0], 3)))}
        print('modelo:', json.dumps(out['modelo'], ensure_ascii=False))
    except Exception as e:
        out['modelo'] = {'error': str(e)}
    json.dump(out, open('_v360_retiradas.json', 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1, default=str)


if __name__ == '__main__':
    main()
