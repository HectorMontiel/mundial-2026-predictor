# -*- coding: utf-8 -*-
"""
v310 — SIMULACIÓN DE LAS APUESTAS QUE DA LA APLICACIÓN: ¿SE CUMPLE LO QUE
PROMETE Y CON QUÉ CUOTA?

El usuario: «puedes hacer simulaciones de apuestas que tú das y si encajan
con el resultado es que tenemos éxito con el modelo. Tiene que haber una
probabilidad alta, pero no abras tanto los rangos; la cosa es tener buenas
cuotas».

LO QUE YA SE SABÍA (registro de 1.238 apuestas liquidadas de la app)
Cuando el modelo dice MÁS que la casa, falla más de lo que promete (dijo 68 %
con la casa en 65 %: pasó el 61 %, ROI −11 %); cuando dice menos, acierta
más. Elegir por «probabilidad × cuota» premia justo los errores del modelo.

AQUÍ, A ESCALA: los ledgers fuera de muestra con cuota de cierre
    pick_ledger.csv          1X2       (cuotas de cierre; Pinnacle aparte)
    pick_ledger_totales.csv  más/menos 2,5
Para cada partido: p del modelo, p de la casa (sin margen) y
    p_cal = logística(logit p_modelo, logit p_casa), ajustada SÓLO con el
            tramo anterior (50 % → evalúa 50-70 %; 70 % → evalúa 30 % final).
REGLAS (una apuesta por partido y mercado como máximo):
    R0  la de hoy: p_modelo ≥ 50 %, cuota ≥ 1,20, la de mayor p_modelo·cuota
    R1  p_cal ≥ 60 % y cuota ≥ 1,40, la más probable
    R2  p_cal ≥ 55 %, cuota ≥ 1,50 y p_cal·cuota ≥ 1
    R3  p_cal ≥ 65 % y cuota ≥ 1,30
    R4  p_cal ≥ 60 %, cuota ≥ 1,40 y p_cal·cuota ≥ 1
Se mide: lo prometido (p_cal) contra lo real, ROI a la cuota y p5 por
bootstrap, en los DOS tramos.

Uso: python _v310_simulacion.py     (escribe _v310_simulacion.json)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

B = 1000


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def candidatos() -> pd.DataFrame:
    """Una fila por (partido, lado): p del modelo, de la casa, cuota, y."""
    filas = []
    l = pd.read_csv('pick_ledger.csv', low_memory=False)
    l = l.dropna(subset=['cuota_home', 'cuota_draw', 'cuota_away'])
    inv = 1 / l[['cuota_home', 'cuota_draw', 'cuota_away']]
    s = inv.sum(axis=1)
    for lado, pc, cc, res in (('1', 'p_home', 'cuota_home', 0),
                              ('X', 'p_draw', 'cuota_draw', 1),
                              ('2', 'p_away', 'cuota_away', 2)):
        filas.append(pd.DataFrame({
            'mercado': '1X2', 'liga': l['liga'], 'mid': l['match_id'],
            'fecha': l['fecha'], 'lado': lado, 'p_mod': l[pc],
            'p_casa': (1 / l[cc]) / s, 'cuota': l[cc],
            'y': (l['resultado'] == res).astype(int)}))
    t = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    # las cuotas de más/menos 2,5 viven en `pick_ledger.csv` (17.447 partidos);
    # las columnas homónimas de `pick_ledger_totales` están vacías
    t = t.drop(columns=['cuota_over25', 'cuota_under25']).merge(
        l[['match_id', 'cuota_over25', 'cuota_under25']].drop_duplicates(
            'match_id'), on='match_id', how='inner')
    t = t.dropna(subset=['cuota_over25', 'cuota_under25', 'p_over_2.5'])
    s = 1 / t['cuota_over25'] + 1 / t['cuota_under25']
    for lado, sg, cc in (('más', 1, 'cuota_over25'), ('menos', 0, 'cuota_under25')):
        pm = t['p_over_2.5'] if sg else 1 - t['p_over_2.5']
        y = t['over_2.5_real'] if sg else 1 - t['over_2.5_real']
        filas.append(pd.DataFrame({
            'mercado': 'Goles 2.5', 'liga': t['liga'], 'mid': t['match_id'],
            'fecha': t['fecha'], 'lado': lado, 'p_mod': pm,
            'p_casa': (1 / t[cc]) / s, 'cuota': t[cc], 'y': y}))
    d = pd.concat(filas, ignore_index=True).dropna()
    d = d[(d['cuota'] > 1.01) & (d['cuota'] < 30)]
    d['fecha'] = pd.to_datetime(d['fecha'])
    return d.sort_values('fecha').reset_index(drop=True)


def calibrar(ent: pd.DataFrame, pru: pd.DataFrame) -> np.ndarray:
    X = np.c_[_logit(ent['p_mod']), _logit(ent['p_casa'])]
    m = LogisticRegression(C=10.0, max_iter=500).fit(X, ent['y'])
    Xp = np.c_[_logit(pru['p_mod']), _logit(pru['p_casa'])]
    return m.predict_proba(Xp)[:, 1], m.coef_[0].tolist()


REGLAS = {
    'R0 hoy (p≥50, c≥1.20, max p·c)': ('p_mod', lambda g: g[(g['p_mod'] >= .5)
                                                           & (g['cuota'] >= 1.2)],
                                       lambda g: g['p_mod'] * g['cuota']),
    'R1 p≥60, c≥1.40': ('p_cal', lambda g: g[(g['p_cal'] >= .6)
                                               & (g['cuota'] >= 1.4)],
                        lambda g: g['p_cal']),
    'R2 p≥55, c≥1.50, EV≥0': ('p_cal', lambda g: g[(g['p_cal'] >= .55)
                                                     & (g['cuota'] >= 1.5)
                                                     & (g['p_cal'] * g['cuota'] >= 1)],
                              lambda g: g['p_cal']),
    'R3 p≥65, c≥1.30': ('p_cal', lambda g: g[(g['p_cal'] >= .65)
                                               & (g['cuota'] >= 1.3)],
                        lambda g: g['p_cal']),
    'R4 p≥60, c≥1.40, EV≥0': ('p_cal', lambda g: g[(g['p_cal'] >= .6)
                                                     & (g['cuota'] >= 1.4)
                                                     & (g['p_cal'] * g['cuota'] >= 1)],
                              lambda g: g['p_cal']),
}


def aplicar(regla, x: pd.DataFrame) -> pd.DataFrame:
    col, filtro, orden = REGLAS[regla]
    g = filtro(x)
    if g.empty:
        return g
    g = g.assign(_o=orden(g)).sort_values('_o', ascending=False)
    g = g.drop_duplicates(['mid', 'mercado'])
    return g.assign(prometido=g[col])


def resumen(g: pd.DataFrame, rng) -> dict:
    if len(g) < 20:
        return {'n': int(len(g))}
    gan = (g['y'] * g['cuota'] - 1).values
    bs = [gan[rng.integers(0, len(gan), len(gan))].mean() for _ in range(B)]
    return {'n': int(len(g)), 'prometido': round(float(g['prometido'].mean()), 4),
            'real': round(float(g['y'].mean()), 4),
            'cuota': round(float(g['cuota'].mean()), 3),
            'roi': round(float(gan.mean()), 4),
            'p5': round(float(np.percentile(bs, 5)), 4)}


GRUPOS = {'liga_mx': 'Liga MX', 'champions': 'UEFA clubes',
          'europa_league': 'UEFA clubes', 'conference_league': 'UEFA clubes',
          'leagues_cup': 'Leagues Cup'}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = candidatos()
    rng = np.random.default_rng(310)
    q50, q70 = d['fecha'].quantile(.5), d['fecha'].quantile(.7)
    tramos = {}
    for nom, ent, pru in (('eleccion', d[d['fecha'] < q50],
                           d[(d['fecha'] >= q50) & (d['fecha'] < q70)]),
                          ('juicio', d[d['fecha'] < q70], d[d['fecha'] >= q70])):
        pru = pru.copy()
        pru['p_cal'] = np.nan
        coefs = {}
        for m in pru['mercado'].unique():
            p, c = calibrar(ent[ent['mercado'] == m], pru[pru['mercado'] == m])
            pru.loc[pru['mercado'] == m, 'p_cal'] = p
            coefs[m] = [round(v, 3) for v in c]
        tramos[nom] = (pru, coefs)
    doc = {'corte_50': str(q50.date()), 'corte_70': str(q70.date()),
           'coeficientes': {k: v[1] for k, v in tramos.items()}, 'reglas': {}}
    for regla in REGLAS:
        for mercado in ('1X2', 'Goles 2.5'):
            fila = {}
            for nom, (pru, _c) in tramos.items():
                g = aplicar(regla, pru[pru['mercado'] == mercado])
                fila[nom] = resumen(g, rng)
                fila[nom + '_por_grupo'] = {
                    gr: resumen(x, rng) for gr, x in
                    g.assign(gr=g['liga'].map(GRUPOS).fillna('Resto'))
                    .groupby('gr')}
            doc['reglas'].setdefault(regla, {})[mercado] = fila
            e, j = fila['eleccion'], fila['juicio']
            print('%-34s %-9s | elec n=%5s prom=%s real=%s c=%s roi=%s p5=%s | '
                  'juicio n=%5s prom=%s real=%s roi=%s p5=%s'
                  % (regla, mercado, e.get('n'), e.get('prometido'), e.get('real'),
                     e.get('cuota'), e.get('roi'), e.get('p5'), j.get('n'),
                     j.get('prometido'), j.get('real'), j.get('roi'), j.get('p5')))
    # los coeficientes que usa producción: ajustados con TODO lo disponible
    final = {}
    for m in d['mercado'].unique():
        x = d[d['mercado'] == m]
        X = np.c_[_logit(x['p_mod']), _logit(x['p_casa'])]
        lr = LogisticRegression(C=10.0, max_iter=500).fit(X, x['y'])
        final[m] = {'a': round(float(lr.intercept_[0]), 4),
                    'b_modelo': round(float(lr.coef_[0][0]), 4),
                    'c_casa': round(float(lr.coef_[0][1]), 4),
                    'n': int(len(x))}
    # Sólo informativo: producción NO usa estos coeficientes. Con cuotas
    # PREVIAS al partido (`_v310_peso_casa.py`) la mezcla 50/50 que ya usa
    # `concordancia` sale la mejor, así que no se cambia.
    doc['coef_final'] = final
    json.dump(doc, open('_v310_simulacion.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(doc['coeficientes'])


if __name__ == '__main__':
    main()
