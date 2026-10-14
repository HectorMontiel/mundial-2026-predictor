#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — Revisión escéptica de H1 («Corregir la probabilidad de la casa»,
`_v373_calibracion.py`).

Lo que se intenta tumbar:
  1. La única señal de H1 en Playdoit: a piso 1,45, «potencia ≥ 0,65» (una
     pata por partido, cuota 1,45-1,95) gana a «la casa elige» y a la
     proporcional «a igual volumen» (+5,5 pts en B, p5 +1,4).
  2. La «referencia por piso» del histórico con la proporcional
     (1,30 → p ≥ 0,63; 1,45 → 0,59; 1,60 → 0,55; 1,70 → 0,52; 1,80 → 0,50),
     que «pasa» contra la casa elige en las dos mitades.

PRUEBAS
  (a) ¿Es la potencia o es el umbral? Con dos cuotas, a cuota propia fija la
      proporcional y la potencia ordenan las patas IGUAL (las dos sólo
      dependen de la cuota del otro lado). Se busca el umbral proporcional
      que da EXACTAMENTE la misma selección (Jaccard = 1). Si existe, la
      «ventaja sobre la proporcional» es la rejilla de umbrales (0,63 / 0,64),
      no la forma de quitar el margen.
  (b) ¿Es la probabilidad o es la cuota? Comparador sin probabilidad: la pata
      más barata del partido dentro de la banda, si su cuota ≤ tope (Playdoit:
      1,47; histórico: el tope que en la parte de elegir da el mismo volumen).
  (c) OTRO CORTE TEMPORAL. Playdoit: por semana, por mes y 70/30 por días
      (umbral y método se vuelven a elegir en el 70 % con el mismo criterio
      del original —mayor p5 de la diferencia contra la casa elige, ≥ 60 patas
      y ≥ 3 por día— y se juzgan en el 30 %). Histórico: por año y 70/30.
  Bootstrap por partido (pesos de Poisson pareados, 2.000).
Sólo lee; escribe `_v373_calibracion_revision.json`.
"""
import importlib.util as iu
import json
import sys
import time

import numpy as np
import pandas as pd


def _mod(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


C = _mod('v373cal', '_v373_calibracion.py')
rng = np.random.default_rng(37399)
T0 = time.time()
ESTATICOS = C.ESTATICOS
REF_HIST = {1.30: 0.63, 1.45: 0.59, 1.60: 0.55, 1.70: 0.52, 1.80: 0.50}


def log(*a):
    print('[%5.0f s]' % (time.time() - T0), *a, flush=True)


def r4(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 4)


# ------------------------------------------------------------------ utilidades
def por_partido(x, piso, col, asc=False):
    """La mejor pata de cada partido dentro de [piso, piso+0,5] según col."""
    z = C.en_piso(x, piso)
    if asc:
        z = z.sort_values([col, 'p_proporcional'], ascending=[True, False], kind='mergesort')
    else:
        z = z.sort_values(col, ascending=False, kind='mergesort')
    return z.drop_duplicates('mid').set_index('mid')


def tabla(x, piso, reglas):
    """Por partido (los de la casa elige): base y cada regla como (sel, ok, gan, cuota)."""
    base = por_partido(x, piso, 'p_proporcional')
    t = pd.DataFrame({'fecha': base.fecha, 'dia': base.dia, 'b_ok': base.ok.astype(float),
                      'b_gan': base.gan, 'b_cu': base.cuota})
    for nombre, (col, asc, cond) in reglas.items():
        e = por_partido(x, piso, col, asc).reindex(t.index)
        t[nombre + '_s'] = cond(e).fillna(False).astype(float).values
        t[nombre + '_ok'] = e.ok.fillna(0).astype(float).values
        t[nombre + '_gan'] = e.gan.fillna(0).values
        t[nombre + '_cu'] = e.cuota.fillna(0).values
        t[nombre + '_id'] = (e.mercado.astype(str) + '|' + e.lado_ap.astype(str) + '|' + e.linea.astype(str)
                             if 'lado_ap' in e else e.lado.astype(str))
    return t


def resumen(t, r):
    s = t[r + '_s'] > 0
    n = int(s.sum())
    if not n:
        return {'n': 0}
    return {'n': n, 'patas_dia': round(n / max(t.dia.nunique(), 1), 2), 'acierto': r4(t[r + '_ok'][s].mean()),
            'cuota': round(float(t[r + '_cu'][s].mean()), 3), 'gan_100': round(100 * float(t[r + '_gan'][s].mean()), 2),
            'base_acierto': r4(t.b_ok.mean()), 'base_cuota': round(float(t.b_cu.mean()), 3),
            'base_gan_100': round(100 * float(t.b_gan.mean()), 2),
            'dif_acierto': r4(t[r + '_ok'][s].mean() - t.b_ok.mean()),
            'dif_gan_100': round(100 * float(t[r + '_gan'][s].mean() - t.b_gan.mean()), 2)}


def boot(t, r, otra=None, B=2000, trozo=250):
    """p5 por partido de (regla − otra) en acierto y ganancia; otra=None → la casa elige."""
    s1 = t[r + '_s'].values.astype(np.float32)
    o1, g1 = t[r + '_ok'].values.astype(np.float32), t[r + '_gan'].values.astype(np.float32)
    if otra is None:
        s2 = np.ones(len(t), np.float32)
        o2, g2 = t.b_ok.values.astype(np.float32), t.b_gan.values.astype(np.float32)
    else:
        s2 = t[otra + '_s'].values.astype(np.float32)
        o2, g2 = t[otra + '_ok'].values.astype(np.float32), t[otra + '_gan'].values.astype(np.float32)
    if s1.sum() == 0 or s2.sum() == 0:
        return {}
    da, dg = [], []
    for i in range(0, B, trozo):
        W = rng.poisson(1.0, (min(trozo, B - i), len(t))).astype(np.float32)
        n1, n2 = W @ s1, W @ s2
        n1, n2 = np.where(n1 > 0, n1, np.nan), np.where(n2 > 0, n2, np.nan)
        da.append((W @ (s1 * o1)) / n1 - (W @ (s2 * o2)) / n2)
        dg.append((W @ (s1 * g1)) / n1 - (W @ (s2 * g2)) / n2)
    da, dg = np.concatenate(da), np.concatenate(dg)
    s1b, s2b = s1 > 0, s2 > 0
    return {'dif_acierto': r4(o1[s1b].mean() - o2[s2b].mean()), 'dif_acierto_p5': r4(np.nanpercentile(da, 5)),
            'dif_gan_100': round(100 * float(g1[s1b].mean() - g2[s2b].mean()), 2),
            'dif_gan_p5': round(100 * float(np.nanpercentile(dg, 5)), 2)}


def jaccard(t, r1, r2):
    m1, m2 = (t[r1 + '_s'] > 0).values, (t[r2 + '_s'] > 0).values
    a = set(zip(t.index.values[m1], t[r1 + '_id'].astype(str).values[m1]))
    b = set(zip(t.index.values[m2], t[r2 + '_id'].astype(str).values[m2]))
    return round(len(a & b) / max(len(a | b), 1), 4)


def reelegir(x, piso, corte, metodos):
    """70/30: método y umbral elegidos en la parte de elegir con el criterio del original."""
    fA, fB = (lambda z: z.fecha < corte), (lambda z: z.fecha >= corte)
    MA = C.Mitad(x, piso, fA, C.B_SEL, metodos)
    MB = C.Mitad(x, piso, fB, 0, metodos)
    elegido = {}
    for m in metodos:
        mejor, _ = C.elegir_umbral(MA, m)
        if mejor is not None:
            elegido[m] = mejor
    if not elegido:
        return {'metodo': None}
    m_ = max(elegido, key=lambda k: elegido[k][1])
    u_ = elegido[m_][0]
    out = {'metodo': m_, 'umbral': u_, 'criterio_elegir': elegido[m_][1],
           'todos': {m: list(v) for m, v in elegido.items()}}
    for t_, MM in (('elegir', MA), ('juzgar', MB)):
        pt = MM.punto(m_, u_)
        if pt['n']:
            bt = MM.boot_fin(m_, u_)
            pt.update({k: C._p5(v, 100 if 'gan' in k else 1) for k, v in bt.items()})
        out[t_] = pt
    out['pasa'] = bool((out['elegir'].get('dif_p5') or -1) > 0 and (out['juzgar'].get('dif_p5') or -1) > 0)
    return out


# ------------------------------------------------------------------ Playdoit
def playdoit():
    x = C.playdoit()
    xe = x[~x.mercado.isin(C.PERDEDORES)].copy()
    dias = np.sort(xe.fecha.unique())
    xs = xe[xe.fecha >= dias[0] + np.timedelta64(7, 'D')].copy()
    R = {}
    reglas = {
        'potencia_065': ('p_potencia', False, lambda e: e.p_potencia >= 0.65),
        'prop_063': ('p_proporcional', False, lambda e: e.p_proporcional >= 0.63),
        'prop_0635': ('p_proporcional', False, lambda e: e.p_proporcional >= 0.635),
        'cuota_147': ('cuota', True, lambda e: e.cuota <= 1.47),
    }
    for nombre_u, u in (('produccion_desde_dia8', xs), ('fijos_34d', xe)):
        t = tabla(u, 1.45, reglas)
        corte50 = u.fecha.quantile(0.5)
        Ru = {'patas': int(len(u)), 'partidos': int(u.mid.nunique()), 'dias': int(u.dia.nunique()),
              'todo': {r: resumen(t, r) for r in reglas},
              'jaccard_potencia_vs_prop_0635': jaccard(t, 'potencia_065', 'prop_0635'),
              'jaccard_potencia_vs_prop_063': jaccard(t, 'potencia_065', 'prop_063'),
              'cuotas_elegidas_potencia': t.loc[t.potencia_065_s > 0, 'potencia_065_cu'].round(3)
              .value_counts().head(5).to_dict()}
        # la misma comparación del original, mitades 50/50: potencia vs prop 0,63 (no es igual volumen)
        for t_, q in (('A', t[t.fecha < corte50]), ('B', t[t.fecha >= corte50])):
            Ru['mitad_' + t_] = {
                'potencia_vs_base': boot(q, 'potencia_065'),
                'potencia_vs_prop063': boot(q, 'potencia_065', 'prop_063'),
                'prop0635_vs_prop063': boot(q, 'prop_0635', 'prop_063'),
                'potencia_vs_cuota147': boot(q, 'potencia_065', 'cuota_147'),
                'cuota147_vs_base': boot(q, 'cuota_147'),
                'n': {r: int(q[r + '_s'].sum()) for r in reglas}}
        # por semana y por mes (la regla fija recomendada)
        sem = t.fecha.dt.to_period('W-SUN').astype(str)
        mes = t.fecha.dt.to_period('M').astype(str)
        for nombre_c, clave in (('por_semana', sem), ('por_mes', mes)):
            filas = {}
            for k, q in t.groupby(clave):
                filas[k] = {'potencia_065': resumen(q, 'potencia_065'), 'cuota_147': resumen(q, 'cuota_147')}
            Ru[nombre_c] = filas
            gana = [v['potencia_065'].get('dif_acierto') for v in filas.values()
                    if v['potencia_065'].get('n', 0) >= 10]
            Ru[nombre_c + '_cuantas_ganan_a_base'] = '%d de %d (con ≥ 10 patas)' % (
                sum(1 for g in gana if g is not None and g > 0), len(gana))
        # 70/30 por días: elegir de nuevo método y umbral, juzgar en el 30 %
        dd = np.sort(u.fecha.unique())
        corte70 = dd[int(np.ceil(0.7 * len(dd)))]
        Ru['corte_70_30'] = str(pd.Timestamp(corte70))[:10]
        Ru['reelegido_70_30'] = reelegir(u, 1.45, corte70, ESTATICOS)
        q30 = t[t.fecha >= corte70]
        Ru['fija_en_30'] = {r: resumen(q30, r) for r in reglas}
        Ru['fija_en_30_boot'] = {'potencia_vs_base': boot(q30, 'potencia_065'),
                                 'potencia_vs_prop063': boot(q30, 'potencia_065', 'prop_063'),
                                 'potencia_vs_cuota147': boot(q30, 'potencia_065', 'cuota_147')}
        # y los otros pisos con la elección 70/30 (todos los métodos fijos)
        Ru['otros_pisos_70_30'] = {'%.2f' % p: reelegir(u, p, corte70, ESTATICOS) for p in (1.30, 1.60, 1.70, 1.80)}
        R[nombre_u] = Ru
        log('playdoit', nombre_u, 'listo')
    return R


# ------------------------------------------------------------------ histórico
def historico():
    h, npart = C.historico()
    h = h[h.fecha >= '2011-01-01'].copy()
    # el más/menos entra cuando el original ya lo predecía (≥ 3000 patas antes del trimestre)
    ou = h[h.mercado == 'OU25']
    trims = pd.date_range('2011-01-01', h.fecha.max() + pd.Timedelta(days=1), freq='QS')
    ini_ou = None
    for q0 in trims:
        if int((ou.fecha < q0).sum()) >= 3000:
            ini_ou = q0
            break
    h = h[(h.mercado == '1X2') | (h.fecha >= ini_ou)].copy()
    h['ano'] = h.fecha.dt.year
    R = {'patas': int(len(h)), 'partidos': int(h.mid.nunique()), 'ligas_con_cuotas': int(h.liga.nunique()),
         'ou_desde': str(ini_ou)[:10], 'pisos': {}}
    dd = np.sort(h.fecha.unique())
    corte70 = dd[int(np.ceil(0.7 * len(dd)))]
    R['corte_70_30'] = str(pd.Timestamp(corte70))[:10]
    for piso, u in REF_HIST.items():
        reglas = {'prop_ref': ('p_proporcional', False, (lambda e, u=u: e.p_proporcional >= u)),
                  'cuota_min': ('cuota', True, (lambda e: e.cuota >= 0))}
        t = tabla(h, piso, reglas)
        el = t[t.fecha < corte70]
        # tope de cuota (sin probabilidad) que en la parte de elegir da el mismo volumen que la regla
        n_obj = int(el.prop_ref_s.sum())
        cus = np.sort(el.cuota_min_cu.values)
        tope = float(cus[min(n_obj, len(cus)) - 1]) if n_obj else piso
        t['cuota_tope_s'] = (t.cuota_min_cu <= tope).astype(float)
        for c in ('ok', 'gan', 'cu', 'id'):
            t['cuota_tope_' + c] = t['cuota_min_' + c]
        P = {'umbral_ref': u, 'tope_cuota_mismo_volumen': round(tope, 3)}
        P['todo'] = {r: resumen(t, r) for r in ('prop_ref', 'cuota_tope')}
        P['jaccard_prop_vs_tope'] = jaccard(t, 'prop_ref', 'cuota_tope')
        ju = t[t.fecha >= corte70]
        P['juzgar_30'] = {r: resumen(ju, r) for r in ('prop_ref', 'cuota_tope')}
        P['juzgar_30_boot'] = {'prop_vs_base': boot(ju, 'prop_ref', B=1000),
                               'prop_vs_cuota_tope': boot(ju, 'prop_ref', 'cuota_tope', B=1000)}
        anos = {}
        for a, q in t.groupby(t.fecha.dt.year):
            anos[int(a)] = {'prop_ref': resumen(q, 'prop_ref'), 'cuota_tope': resumen(q, 'cuota_tope')}
        P['por_ano'] = anos
        ok = [v['prop_ref'] for v in anos.values() if v['prop_ref'].get('n', 0) >= 100]
        P['anos_regla_gana_en_ganancia_a_base'] = '%d de %d' % (sum(1 for v in ok if v['dif_gan_100'] > 0), len(ok))
        P['anos_ganancia_positiva'] = '%d de %d' % (sum(1 for v in ok if v['gan_100'] > 0), len(ok))
        P['acierto_por_ano_min_max'] = [min(v['acierto'] for v in ok), max(v['acierto'] for v in ok)] if ok else None
        # 70/30: re-elegir (proporcional y potencia) con el criterio del original
        P['reelegido_70_30'] = reelegir(h, piso, corte70, ('proporcional', 'potencia'))
        R['pisos']['%.2f' % piso] = P
        log('histórico piso', piso, 'listo')
    # Casa 70/130 por año: lo que prometen proporcional y potencia contra lo que pasa
    z = h[(h.cuota >= 1.30) & (h.cuota <= 1.70) & (h.p_proporcional >= 0.70)]
    z = z.sort_values('p_proporcional', ascending=False).drop_duplicates('mid')
    R['casa_70_130_por_ano'] = {int(a): {'n': int(len(q)), 'acierto': r4(q.ok.mean()),
                                         'prop': r4(q.p_proporcional.mean()), 'potencia': r4(q.p_potencia.mean()),
                                         'gan_100': round(100 * float(q.gan.mean()), 2)}
                                for a, q in z.groupby(z.fecha.dt.year)}
    return R


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    R = {'playdoit': playdoit()}
    json.dump(R, open('_v373_calibracion_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    R['historico'] = historico()
    json.dump(R, open('_v373_calibracion_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    for k, v in R['playdoit'].items():
        print('==', k, {a: v[a] for a in ('patas', 'partidos', 'dias', 'jaccard_potencia_vs_prop_0635',
                                          'jaccard_potencia_vs_prop_063', 'cuotas_elegidas_potencia')})
        print('  todo', json.dumps(v['todo'], ensure_ascii=False))
        for t_ in ('A', 'B'):
            print('  mitad', t_, json.dumps(v['mitad_' + t_], ensure_ascii=False))
        print('  semanas', v['por_semana_cuantas_ganan_a_base'], '| meses', v['por_mes_cuantas_ganan_a_base'])
        for s, f in v['por_semana'].items():
            print('    ', s, {r: {a: f[r].get(a) for a in ('n', 'acierto', 'cuota', 'gan_100', 'base_acierto',
                                                          'base_gan_100')} for r in f})
        for s, f in v['por_mes'].items():
            print('    ', s, {r: {a: f[r].get(a) for a in ('n', 'acierto', 'cuota', 'gan_100', 'base_acierto',
                                                          'base_gan_100')} for r in f})
        print('  70/30 corte', v['corte_70_30'], 'reelegido', json.dumps(
            {a: v['reelegido_70_30'].get(a) for a in ('metodo', 'umbral', 'todos', 'elegir', 'juzgar', 'pasa')},
            ensure_ascii=False))
        print('  fija en 30', json.dumps(v['fija_en_30'], ensure_ascii=False))
        print('  fija en 30 boot', json.dumps(v['fija_en_30_boot'], ensure_ascii=False))
        for p, f in v['otros_pisos_70_30'].items():
            print('  piso', p, '70/30', f.get('metodo'), f.get('umbral'), 'elegir', f.get('elegir', {}).get('acierto'),
                  f.get('elegir', {}).get('dif_p5'), 'juzgar', {a: f.get('juzgar', {}).get(a) for a in (
                      'n', 'acierto', 'cuota', 'gan_100', 'dif_acierto', 'dif_p5', 'dif_gan_100', 'dif_gan_p5')},
                  'pasa', f.get('pasa'))
    H = R['historico']
    print('== histórico', {k: H[k] for k in ('patas', 'partidos', 'ligas_con_cuotas', 'ou_desde', 'corte_70_30')})
    for p, P in H['pisos'].items():
        print(' piso', p, 'u', P['umbral_ref'], 'tope', P['tope_cuota_mismo_volumen'], 'jaccard', P['jaccard_prop_vs_tope'])
        print('   todo', json.dumps(P['todo'], ensure_ascii=False))
        print('   juzgar 30', json.dumps(P['juzgar_30'], ensure_ascii=False))
        print('   boot 30', json.dumps(P['juzgar_30_boot'], ensure_ascii=False))
        print('   años: gana a base en ganancia', P['anos_regla_gana_en_ganancia_a_base'], '| ganancia > 0',
              P['anos_ganancia_positiva'], '| acierto min-max', P['acierto_por_ano_min_max'])
        r = P['reelegido_70_30']
        print('   reelegido 70/30', r.get('metodo'), r.get('umbral'), r.get('todos'), 'juzgar',
              {a: r.get('juzgar', {}).get(a) for a in ('n', 'acierto', 'cuota', 'gan_100', 'dif_acierto', 'dif_p5',
                                                        'dif_gan_100', 'dif_gan_p5')})
    print(' Casa 70/130 por año', json.dumps(H['casa_70_130_por_ano']))
    log('escrito _v373_calibracion_revision.json')


if __name__ == '__main__':
    main()
