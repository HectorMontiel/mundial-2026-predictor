#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v169 — ¿SIRVE LO QUE RECOMIENDA LA APLICACIÓN? LIQUIDADO CONTRA EL RESULTADO.

Dos preguntas, las dos con el histórico que ya está en el repo y las dos
contestadas comparando la apuesta con LO QUE PASÓ DE VERDAD.

    1. GOLES. ¿Cuánto baja el error de calibración encogiendo hacia la casa, y
       con qué peso? El encargo propone 0,6·modelo + 0,4·casa; aquí se ajusta
       el peso sobre 17.532 partidos en vez de fijarlo.

    2. EFICACIA. Para cada partido del histórico se reconstruye QUÉ APUESTA
       habría propuesto la aplicación con las reglas de hoy (v166 encogimiento,
       v166 recorte, v168 cuarentena y Mercado Rey) y se liquida contra el
       marcador real: acierto y ROI a la cuota de cierre. Al lado, la política
       ANTERIOR —el máximo de probabilidad cruda, que es lo que hacía la v164—
       sobre exactamente los mismos partidos.

Sin esa segunda tabla, todo lo demás son opiniones sobre calibración. Esto dice
si la apuesta se cumple.

    python _v169_goles_y_eficacia.py
"""
import json
import logging
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v169_goles_y_eficacia.json'
N_BOOT = 2000
SEMILLA = 20260824
UMBRAL_ACEPTABLE = 0.05      # el del proyecto desde la v162


def ece(p, y, n_bins: int = 10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) < 200:
        return None
    b = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    b[0], b[-1] = -1e-9, 1 + 1e-9
    t = 0.0
    for i in range(n_bins):
        m = (p >= b[i]) & (p < b[i + 1])
        if m.sum():
            t += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(t / len(p))


def devig2(c1, c2):
    return (1.0 / c1) / ((1.0 / c1) + (1.0 / c2))


def boot_p5(g, rng):
    if len(g) < 30:
        return float('nan')
    idx = rng.integers(0, len(g), size=(N_BOOT, len(g)))
    return float(np.percentile(g[idx].mean(axis=1), 5) * 100)


# ---------------------------------------------------------------------------
# 1) GOLES: el peso, ajustado en vez de fijado
# ---------------------------------------------------------------------------
def goles(rng):
    d = pd.read_csv('pick_ledger_totales.csv')
    d = d[d['cuota_over25'].notna() & d['cuota_under25'].notna()].copy()
    d = d[(d['cuota_over25'] > 1) & (d['cuota_under25'] > 1)]
    p_mod = d['p_over_2.5'].astype(float).values
    p_mkt = devig2(d['cuota_over25'].astype(float).values,
                   d['cuota_under25'].astype(float).values)
    y = d['over_2.5_real'].astype(int).values

    print('=' * 78)
    print('1) GOLES O/U 2,5 — EL PESO DEL ENCOGIMIENTO, AJUSTADO')
    print('=' * 78)
    print('%d partidos con las dos cuotas de cierre · %d competiciones\n'
          % (len(d), d['liga'].nunique()))
    print('%-28s %9s %9s' % ('peso del modelo', 'ECE', 'ligas > 0,05'))
    print('-' * 50)
    filas = []
    for w, etq in ((1.00, '1,00 (sólo modelo)'), (0.60, '0,60 (lo pedido)'),
                   (0.40, '0,40'), (0.25, '0,25 (lo desplegado)'),
                   (0.15, '0,15'), (0.00, '0,00 (sólo casa)')):
        p = w * p_mod + (1 - w) * p_mkt
        e = ece(p, y)
        malas = 0
        for lg, g in d.groupby('liga'):
            m = d['liga'].values == lg
            el = ece(p[m], y[m])
            if el is not None and el > UMBRAL_ACEPTABLE:
                malas += 1
        print('%-28s %9.5f %9d' % (etq, e, malas))
        filas.append({'w': w, 'ece': round(e, 5), 'ligas_malas': malas})

    # el peso que MINIMIZA el ECE, buscado y no supuesto
    mejor = min(((w, ece(w * p_mod + (1 - w) * p_mkt, y))
                 for w in np.arange(0, 1.001, 0.01)), key=lambda t: t[1])
    print('\n  peso que minimiza el ECE: %.2f (ECE %.5f)' % mejor)
    print('  el 0,60 que pedía el encargo da %.5f — %.1f veces peor'
          % (filas[1]['ece'], filas[1]['ece'] / mejor[1]))

    # ¿cuántas ligas quedan por debajo de 0,05 con lo desplegado?
    por_liga = []
    for lg, g in d.groupby('liga'):
        m = (d['liga'].values == lg)
        if m.sum() < 200:
            continue
        por_liga.append({
            'liga': lg, 'n': int(m.sum()),
            'crudo': ece(p_mod[m], y[m]),
            'w025': ece(0.25 * p_mod[m] + 0.75 * p_mkt[m], y[m])})
    ok_crudo = sum(1 for r in por_liga if r['crudo'] is not None
                   and r['crudo'] <= UMBRAL_ACEPTABLE)
    ok_025 = sum(1 for r in por_liga if r['w025'] is not None
                 and r['w025'] <= UMBRAL_ACEPTABLE)
    print('\n  ligas con muestra suficiente: %d' % len(por_liga))
    print('  con ECE <= 0,05 sin encoger .....  %d' % ok_crudo)
    print('  con ECE <= 0,05 encogiendo ......  %d' % ok_025)
    peores = sorted([r for r in por_liga if r['w025'] is not None],
                    key=lambda r: -r['w025'])[:5]
    print('\n  las que siguen por encima de 0,05 tras encoger:')
    for r in peores:
        if r['w025'] > UMBRAL_ACEPTABLE:
            print('    %-22s crudo %.4f -> encogido %.4f  (n=%d)'
                  % (r['liga'], r['crudo'], r['w025'], r['n']))
    return {'curva': filas, 'mejor_w': round(float(mejor[0]), 2),
            'mejor_ece': round(float(mejor[1]), 5),
            'ligas': por_liga, 'ok_crudo': ok_crudo, 'ok_encogido': ok_025}


# ---------------------------------------------------------------------------
# 2) EFICACIA: la apuesta contra el marcador
# ---------------------------------------------------------------------------
def _candidatos_del_partido(fila, estab):
    """
    Los mercados que la aplicación podría proponer de ESE partido histórico.

    Cada uno con: probabilidad cruda, probabilidad de la casa (si hay cuota),
    si acertó, la cuota a la que se habría jugado y el puesto de estabilidad de
    su mercado en esa liga.
    """
    salida = []

    def _add(nombre, mercado_rank, p, gano, cuota, p_mkt=None):
        if p is None or not np.isfinite(p):
            return
        salida.append({'nombre': nombre, 'rank': mercado_rank,
                       'p': float(p), 'gano': int(gano),
                       'cuota': float(cuota) if cuota and cuota > 1 else None,
                       'p_mkt': None if p_mkt is None else float(p_mkt)})

    # goles 2,5 — los dos lados, y se queda el que el modelo prefiere
    p_over = fila['p_over_2.5']
    co, cu = fila.get('cuota_over25'), fila.get('cuota_under25')
    mkt = (devig2(co, cu) if (co and cu and co > 1 and cu > 1) else None)
    if p_over >= 0.5:
        _add('Goles: Más de 2.5', 'Goles 2.5', p_over,
             fila['over_2.5_real'], co, mkt)
    else:
        _add('Goles: Menos de 2.5', 'Goles 2.5', 1 - p_over,
             1 - fila['over_2.5_real'], cu,
             None if mkt is None else 1 - mkt)
    # BTTS
    pb = fila['p_btts']
    if pb >= 0.5:
        _add('Ambos marcan: Sí', 'BTTS', pb, fila['btts_real'], None)
    else:
        _add('Ambos marcan: No', 'BTTS', 1 - pb, 1 - fila['btts_real'], None)
    # 1X2, el lado que el modelo prefiere
    p3 = np.array([fila['p_home'], fila['p_draw'], fila['p_away']], float)
    c3 = [fila.get('cuota_home'), fila.get('cuota_draw'),
          fila.get('cuota_away')]
    lado = int(p3.argmax())
    mkt3 = None
    if all(c and c > 1 for c in c3):
        inv = np.array([1.0 / c for c in c3])
        mkt3 = float((inv / inv.sum())[lado])
    _add(['Gana local', 'Empate', 'Gana visitante'][lado], '1X2',
         p3[lado], int(fila['resultado']) == lado, c3[lado], mkt3)
    # v170 — la doble oportunidad, que sale del mismo 1X2 y es donde viven
    # las probabilidades altas que la nueva politica busca.
    res = int(fila['resultado'])
    for a_, b_, etq in ((0, 1, '1X'), (0, 2, '12'), (1, 2, 'X2')):
        _add('Doble oportunidad %s' % etq, 'Doble oportunidad',
             p3[a_] + p3[b_], int(res in (a_, b_)), None)
    for c in salida:
        c['puesto'] = (estab.get(c['rank']) or {}).get('puesto')
        c['estado'] = (estab.get(c['rank']) or {}).get('estado', 'sin medir')
    return salida


def _politica_v169(cands):
    """Lo que propondría la aplicación HOY. `None` si nada es jugable."""
    vivos = []
    for c in cands:
        p = c['p']
        # v166: encogimiento hacia la casa cuando hay precio
        if c['p_mkt'] is not None:
            p = 0.25 * p + 0.75 * c['p_mkt']
            # v166: recorte por desvío, y v168: bloqueo a 10 pp
            if p - c['p_mkt'] > 0.10:
                continue
            if p - c['p_mkt'] > 0.05:
                p = min(p, 0.60)
        # v168: cuarentena
        if c['estado'] in ('inestable', 'sin medir') or c['puesto'] is None:
            continue
        if p < 0.55:
            continue
        vivos.append({**c, 'p_ajustada': p})
    if not vivos:
        return None
    # v168: manda el ranking de estabilidad de esa liga
    return min(vivos, key=lambda c: (c['puesto'], -c['p_ajustada']))


def _politica_v170(cands):
    """
    v170 — LA MAS SEGURA ENTRE LAS ESTABLES. Sin mirar el precio.

    Es la politica que pidio el usuario: nada de esperar a que la casa se
    equivoque, sino la mayor probabilidad ajustada de un mercado que en esa
    liga este medido como fiable.
    """
    vivos = []
    for c in cands:
        p = c['p']
        if c['p_mkt'] is not None:
            p = 0.25 * p + 0.75 * c['p_mkt']
            if p - c['p_mkt'] > 0.10:
                continue
            if p - c['p_mkt'] > 0.05:
                p = min(p, 0.60)
        if c['estado'] not in ('estable', 'moderado'):
            continue
        if p < 0.50:
            continue
        vivos.append({**c, 'p_ajustada': p})
    if not vivos:
        return None
    return max(vivos, key=lambda c: c['p_ajustada'])


def _politica_v164(cands):
    """Lo que proponía antes: el máximo de probabilidad cruda, sin más."""
    vivos = [c for c in cands if c['p'] >= 0.50]
    if not vivos:
        return None
    return max(vivos, key=lambda c: c['p'])


def eficacia(rng):
    import mercado_estabilidad as me

    a = pd.read_csv('pick_ledger.csv')
    b = pd.read_csv('pick_ledger_totales.csv')
    d = a.merge(b, on=['liga', 'match_id'], suffixes=('', '_t'))
    print('\n\n' + '=' * 78)
    print('2) EFICACIA: LA APUESTA CONTRA EL MARCADOR REAL')
    print('=' * 78)
    print('%d partidos con 1X2 y goles del mismo encuentro\n' % len(d))

    estab_por_liga = {}
    for lg in d['liga'].unique():
        filas = (me.de_liga(lg).get('mercados') or [])
        estab_por_liga[lg] = {f['mercado']: f for f in filas}

    res = {'v169': [], 'v170': [], 'v164': []}
    for fila in d.to_dict('records'):
        cands = _candidatos_del_partido(fila, estab_por_liga.get(fila['liga'],
                                                                 {}))
        if not cands:
            continue
        for nombre, pol in (('v169', _politica_v169),
                            ('v170', _politica_v170),
                            ('v164', _politica_v164)):
            e = pol(cands)
            if e is None:
                continue
            res[nombre].append({
                'liga': fila['liga'], 'mercado': e['rank'],
                'p': e.get('p_ajustada', e['p']), 'gano': e['gano'],
                'cuota': e['cuota']})

    print('%-10s %8s %9s %9s %9s %9s %9s'
          % ('política', 'apuestas', 'de', 'acierto', 'esperado', 'ROI %',
             'p5 %'))
    print('-' * 78)
    salida = {}
    for nombre in ('v164', 'v169', 'v170'):
        r = res[nombre]
        if not r:
            continue
        gano = np.array([x['gano'] for x in r], float)
        p = np.array([x['p'] for x in r], float)
        con_cuota = [x for x in r if x['cuota']]
        roi = p5 = float('nan')
        if con_cuota:
            g = np.array([(x['cuota'] - 1) if x['gano'] else -1.0
                          for x in con_cuota])
            roi, p5 = float(g.mean() * 100), boot_p5(g, rng)
        print('%-10s %8d %9d %8.1f%% %8.1f%% %9.2f %9.2f'
              % (nombre, len(r), len(d), gano.mean() * 100, p.mean() * 100,
                 roi, p5))
        salida[nombre] = {'n': len(r), 'de': len(d),
                          'acierto': round(float(gano.mean()), 4),
                          'esperado': round(float(p.mean()), 4),
                          'n_con_cuota': len(con_cuota),
                          'roi': None if np.isnan(roi) else round(roi, 3),
                          'p5': None if np.isnan(p5) else round(p5, 3)}

    print('\n  «esperado» es lo que la aplicación anunciaba; «acierto» lo que')
    print('  pasó. La diferencia entre las dos columnas ES la honestidad de')
    print('  la cifra que se enseña.')

    # de qué mercados sale cada política
    from collections import Counter
    for nombre in ('v164', 'v169', 'v170'):
        c = Counter(x['mercado'] for x in res[nombre])
        print('\n  %s propone desde: %s' % (nombre, dict(c.most_common(6))))
        salida.setdefault(nombre, {})['mercados'] = dict(c)
    return salida


def main():
    rng = np.random.default_rng(SEMILLA)
    doc = {'goles': goles(rng), 'eficacia': eficacia(rng)}
    json.dump(doc, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
