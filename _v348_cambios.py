#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v348 — ¿Se puede predecir qué apuesta anunciada va a cambiar?

El usuario, con los finalizados delante (🎯 lo del pitido, 📌 lo anunciado
antes): «tenemos que ver cuáles son las que se van a meter; si podemos
predecir los cambios de las cuotas, ajustarlo». Cada vez que una apuesta
aparece como «meter» en una foto (salvo la última antes del pitido), se mira
si sigue al pitido. Con lo que se sabe en ESE momento:

    cuota y su distancia a los cortes (1,15 · 1,35), probabilidad y su
    distancia a la franja (70 · 80 %), mercado, horas al partido, cuántas
    fotos lleva, si es la 1.ª o la 2.ª

una regresión logística entrenada con la primera mitad de fechas y juzgada
con la segunda (AUC), y lo que importa al apostar: ¿las que el modelo ve
«firmes» aciertan más que las demás?
"""
import json

import numpy as np
import pandas as pd

import _v343_estabilidad as E
import _v346_fijada as F

rng = np.random.default_rng(348)


def construir():
    E.pg.de_partido = lambda *a, **k: None
    ft = F.fotos()
    filas = []
    for p in E.jugados():
        if p.get('goles_home') is None or str(p.get('deporte') or 'Fútbol') != 'Fútbol':
            continue
        par, ini = str(p.get('partido')), p.get('inicio')
        if par not in ft or not ini:
            continue
        t0 = E._ts(ini)
        f = sorted(x for x in ft[par] if E._ts(x[0]) < t0)
        if len(f) < 2 or not F._metidas(f[-1][1]):
            continue
        final = {r['apuesta'] for r in F._metidas(f[-1][1])}
        visto: dict = {}
        resultado: dict = {}
        for ts, recos in f[:-1]:
            for k, r in enumerate(F._metidas(recos)):
                ap = r['apuesta']
                visto[ap] = visto.get(ap, 0) + 1
                if ap not in resultado:
                    liq = E.liquidar(p, [r])
                    resultado[ap] = liq[0][1] if liq else None
                if resultado[ap] is None:
                    continue
                c = float(r.get('cuota') or 0)
                pr = float(r.get('prob_meter') or r.get('prob') or 0)
                filas.append({
                    'partido': par, 'dia': str(t0.date()), 'apuesta': ap,
                    'mercado': str(r.get('mercado')), 'cuota': c,
                    'd_c115': c - 1.15, 'd_c135': 1.35 - c,
                    'prob': pr, 'd_p70': pr - 0.70, 'd_p80': 0.80 - pr,
                    'horas': (t0 - E._ts(ts)).total_seconds() / 3600,
                    'fotos': visto[ap], 'puesto': k + 1,
                    'sobrevive': int(ap in final), 'verde': resultado[ap]})
    return pd.DataFrame(filas)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    d = construir()
    d.to_pickle('_v348_cambios.pkl')
    print('observaciones', len(d), 'apuestas', d.groupby(['partido', 'apuesta']).ngroups,
          'sobreviven %.3f' % d.sobrevive.mean())
    X = pd.get_dummies(d[['cuota', 'd_c115', 'd_c135', 'prob', 'd_p70', 'd_p80',
                          'horas', 'fotos', 'puesto', 'mercado']],
                       columns=['mercado'], dtype=float)
    X['cerca_corte'] = ((d.d_c115.abs() < 0.03) | (d.d_c135.abs() < 0.03)
                        | (d.d_p70.abs() < 0.02) | (d.d_p80.abs() < 0.02)).astype(float)
    X['log_horas'] = np.log1p(d.horas)
    corte = sorted(d.dia.unique())[len(d.dia.unique()) // 2]
    el, ju = d.dia < corte, d.dia >= corte
    m = LogisticRegression(max_iter=2000, C=0.5).fit(X[el], d.sobrevive[el])
    d['p_firme'] = m.predict_proba(X)[:, 1]
    res = {'corte': corte, 'n_elige': int(el.sum()), 'n_juzga': int(ju.sum()),
           'auc_elige': round(float(roc_auc_score(d.sobrevive[el], d.p_firme[el])), 3),
           'auc_juzga': round(float(roc_auc_score(d.sobrevive[ju], d.p_firme[ju])), 3),
           'sobrevive_base': round(float(d.sobrevive.mean()), 3)}
    # ¿las «firmes» aciertan más? una fila por apuesta: su PRIMERA aparición
    pri = d.sort_values('horas', ascending=False).drop_duplicates(['partido', 'apuesta'])
    umbral = float(pri[pri.dia < corte].p_firme.median())
    for tr, g in (('elige', pri[pri.dia < corte]), ('juzga', pri[pri.dia >= corte]), ('todo', pri)):
        a, b = g[g.p_firme >= umbral], g[g.p_firme < umbral]
        res[tr] = {'firmes': {'n': len(a), 'sobreviven': round(a.sobrevive.mean(), 3),
                              'acierto': round(a.verde.mean(), 3)},
                   'resto': {'n': len(b), 'sobreviven': round(b.sobrevive.mean(), 3),
                             'acierto': round(b.verde.mean(), 3)}}
    # la señal más simple, sin modelo: pegada a un corte
    pri2 = pri.assign(cerca=X.loc[pri.index, 'cerca_corte'].values)
    res['cerca_de_un_corte'] = {
        'si': {'n': int(pri2.cerca.sum()), 'sobreviven': round(pri2[pri2.cerca == 1].sobrevive.mean(), 3),
               'acierto': round(pri2[pri2.cerca == 1].verde.mean(), 3)},
        'no': {'n': int((pri2.cerca == 0).sum()), 'sobreviven': round(pri2[pri2.cerca == 0].sobrevive.mean(), 3),
               'acierto': round(pri2[pri2.cerca == 0].verde.mean(), 3)}}
    # las que se retiran contra las que se quedan (¿se equivoca la app al retirar?)
    res['retiradas'] = {'n': int((pri.sobrevive == 0).sum()),
                        'acierto': round(float(pri[pri.sobrevive == 0].verde.mean()), 3)}
    res['se_quedan'] = {'n': int((pri.sobrevive == 1).sum()),
                        'acierto': round(float(pri[pri.sobrevive == 1].verde.mean()), 3)}
    res['coeficientes'] = dict(sorted(zip(X.columns, np.round(m.coef_[0], 3)),
                                      key=lambda kv: -abs(kv[1]))[:10])
    print(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    json.dump(res, open('_v348_cambios.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
