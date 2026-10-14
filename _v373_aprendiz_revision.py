#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — REVISIÓN escéptica de H2 (`_v373_aprendiz.py`): ¿se sostiene el
«no pasa» del aprendiz walk-forward contra «la casa elige»?

Lo que se revisa (sin tocar `_v373_aprendiz.py` ni su JSON: se importa el
módulo y se vuelve a correr su universo y su walk-forward):
  1. REPRODUCCIÓN — las cifras clave del apilado y de la base en cada piso
     (acierto total, A, B, cuota, diferencia y p5) contra `_v373_aprendiz.json`.
  2. FUGAS —
     · la forma l5/ew y la tabla de `e_v361.pkl` se recalculan desde cero con
       sólo los partidos ANTERIORES y se comparan con las columnas que usa;
     · duplicados: dos partidos de Playdoit emparejados al mismo partido de
       `e_v361`, un partido repartido en dos semanas, mitades que se solapan;
     · el walk-forward: que cada semana sólo vea semanas anteriores (se
       comprueba con las fechas máximas de entrenamiento);
     · «avance» usa el máximo de partidos de la temporada (dato del futuro,
       aunque no del resultado): se mide si pesa.
  3. EL EMPATE DEL ISOTÓNICO — el apilado con calibración isotónica deja
     muchas probabilidades iguales y entonces desempata la casa: se cuenta en
     cuántos partidos elige lo mismo que la casa y se prueba el apilado SIN
     isotónico (sólo la logística de arriba) como diagnóstico.
  4. OTROS CORTES TEMPORALES con las mismas predicciones fuera de muestra:
     por mes (septiembre / octubre), 70/30 por fecha de partido y tercios.
  5. OTRO ENTRENAMIENTO: un solo ajuste 70/30 (todo lo anterior al corte del
     70 % entrena; el 30 % final se juzga, y se parte en dos mitades).
Base en todo: «la casa elige» en el mismo piso y los mismos partidos;
bootstrap PAREADO por partido (2.000 réplicas) del p5 de la diferencia.
Escribe `_v373_aprendiz_revision.json`.
"""
import importlib.util as iu
import json
import sys
import time

import numpy as np
import pandas as pd

T0 = time.time()
rng = np.random.default_rng(3731)
NBOOT = 2000


def _cargar(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


A = _cargar('v373a', '_v373_aprendiz.py')
PISOS = A.PISOS
ANCHO = A.ANCHO


def boot_par(a, b):
    m = a[['partido', 'ok']].merge(b[['partido', 'ok']], on='partido', suffixes=('_a', '_b'))
    v = (m.ok_a - m.ok_b).values
    if len(v) < 20:
        return (float(v.mean()) if len(v) else None), None, len(v)
    idx = rng.integers(0, len(v), (NBOOT, len(v)))
    return float(v.mean()), float(np.percentile(v[idx].mean(1), 5)), len(v)


def comparar(ev, col, segmentos):
    """Por piso: acierto del modelo y de la base en cada segmento, dif y p5."""
    out = {}
    for piso in PISOS:
        z0 = ev[(ev.cuota >= piso) & (ev.cuota <= piso + ANCHO)]
        base = A.elegir(z0, 'p_c')
        z = z0[z0[col].notna()]
        ch = A.elegir(z, col)
        b = base[base.partido.isin(ch.partido)]
        mm = ch[['partido', 'orig', 'lado_ap']].merge(b[['partido', 'orig', 'lado_ap']], on='partido')
        igual = float(((mm.orig_x == mm.orig_y) & (mm.lado_ap_x == mm.lado_ap_y)).mean())
        f = {'n': int(len(ch)), 'acierto': round(float(ch.ok.mean()), 4), 'base': round(float(b.ok.mean()), 4),
             'cuota': round(float(ch.cuota.mean()), 3), 'gan_100': round(100 * float(ch.gan.mean()), 1),
             'igual_que_casa': round(igual, 3)}
        segs = {}
        for nom, mask_fn in segmentos.items():
            q = ch[mask_fn(ch)]
            bq = b[b.partido.isin(q.partido)]
            dif, p5, n = boot_par(q, bq)
            segs[nom] = {'n': n, 'acierto': round(float(q.ok.mean()), 4) if len(q) else None,
                         'base': round(float(bq.ok.mean()), 4) if len(bq) else None,
                         'dif': None if dif is None else round(dif, 4),
                         'p5': None if p5 is None else round(p5, 4)}
        f['segmentos'] = segs
        mejoras = [s['dif'] is not None and s['dif'] > 0 for s in segs.values()]
        p5s = [s['p5'] is not None and s['p5'] > 0 for s in segs.values()]
        f['veredicto'] = 'pasa' if all(mejoras) and all(p5s) else 'parcial' if all(mejoras) else 'no_pasa'
        out[piso] = f
    return out


# ------------------------------------------------------------------- fugas
def revisar_contexto():
    """Recalcula l5_gf, l5_corners, ew_tiros, ppg y posición con sólo lo anterior."""
    e = pd.read_pickle(A.E_CTX).sort_values(['fecha', 'mid']).reset_index(drop=True)
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    chk = {}
    for c in ('gf', 'corners', 'amarillas'):
        r = g[c].transform(lambda s: s.shift(1).rolling(5, 1).mean())
        m = e['l5_' + c].notna() & r.notna()
        chk['l5_' + c] = round(float((e.loc[m, 'l5_' + c] - r[m]).abs().max()), 6)
        # ¿se parece más a la versión que INCLUYE el propio partido?
        r_in = g[c].transform(lambda s: s.rolling(5, 1).mean())
        chk['l5_%s_corr_con_propio' % c] = round(float(np.corrcoef(e.loc[m, 'l5_' + c], r_in[m])[0, 1]), 4)
        chk['l5_%s_corr_sin_propio' % c] = round(float(np.corrcoef(e.loc[m, 'l5_' + c], r[m])[0, 1]), 4)
    r = g['tiros'].transform(lambda s: s.shift(1).ewm(span=8, min_periods=1).mean())
    m = e.ew_tiros.notna() & r.notna()
    chk['ew_tiros'] = round(float((e.loc[m, 'ew_tiros'] - r[m]).abs().max()), 6)
    pp = g['pts'].transform(lambda s: s.shift(1).fillna(0).cumsum()) / g.cumcount().replace(0, np.nan)
    m = e.ppg.notna() & pp.notna()
    chk['ppg'] = round(float((e.loc[m, 'ppg'] - pp[m]).abs().max()), 6)
    # correlación del rasgo con el resultado del PROPIO partido (una fuga daría |r| alto)
    rec = e[e.fecha >= '2026-08-20']
    chk['corr_gf_l5gf_2026'] = round(float(rec[['gf', 'l5_gf']].corr().iloc[0, 1]), 3)
    chk['corr_pts_ppg_2026'] = round(float(rec[['pts', 'ppg']].corr().iloc[0, 1]), 3)
    chk['corr_pts_posrel_2026'] = round(float(rec[['pts', 'pos_rel']].corr().iloc[0, 1]), 3)
    chk['dup_equipo_fecha'] = int((e.groupby(['equipo', e.fecha.dt.normalize()]).size() > 1).sum())
    return chk


def revisar_duplicados(x):
    emp, *_ = A.emparejar_contexto(pd.read_pickle('_v362b_lineas.pkl').join(pd.read_pickle('_v366_lado.pkl')))
    v = pd.Series(emp)
    return {'playdoit_emparejados': int(len(v)), 'mid_e_repetidos': int(v.duplicated().sum()),
            'partido_en_2_semanas': int((x.groupby('partido').semana.nunique() > 1).sum()),
            'partido_en_2_fechas': int((x.groupby('partido').fecha.nunique() > 1).sum())}


def apilado_sin_iso(x):
    """La logística de arriba del apilado SIN el isotónico (diagnóstico de empates)."""
    from sklearn.linear_model import LogisticRegression
    x['p_meta'] = np.nan
    sem = sorted(x.semana.unique())
    diag = []
    for i, s in enumerate(sem):
        if i < 2:
            continue
        oof = x[(x.semana < s) & x.p_lgb.notna()]
        te = x[x.semana == s]
        if len(oof) <= 500:
            continue

        def M(q):
            return np.column_stack([A.lg(q.p_c), A.lg(q.p_log), A.lg(q.p_lgb), A.lg(q.p_arb)])
        meta = LogisticRegression(C=1.0, max_iter=2000).fit(M(oof), oof.ok)
        x.loc[te.index, 'p_meta'] = meta.predict_proba(M(te))[:, 1]
        diag.append({'semana': s, 'oof_hasta': str(oof.fecha.max())[:10], 'juzga_desde': str(te.fecha.min())[:10],
                     'coef': [round(float(c), 3) for c in meta.coef_[0]]})
    return x, diag


def fechas_walk_forward(x):
    """Comprueba que cada semana se predice sólo con fechas anteriores."""
    sem = sorted(x.semana.unique())
    out = []
    for i, s in enumerate(sem[1:], 1):
        tr, te = x[x.semana < s], x[x.semana == s]
        out.append({'semana': s, 'max_fecha_entrena': str(tr.fecha.max())[:10],
                    'min_fecha_predice': str(te.fecha.min())[:10], 'ok': bool(tr.fecha.max() < te.fecha.min())})
    return out


# ----------------------------------------------------------- 70/30 un ajuste
def ajuste_7030(x, corte):
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    tr, te = x[x.fecha < corte].copy(), x[x.fecha >= corte].copy()
    ligas = sorted(tr.liga.unique())
    med, sd = tr[A.CTX + A.DERIV].median(), tr[A.CTX + A.DERIV].std().replace(0, 1).fillna(1)
    lr = LogisticRegression(C=0.3, max_iter=4000).fit(A.mat_log(tr, ligas, med, sd), tr.ok)
    te['q_log'] = lr.predict_proba(A.mat_log(te, ligas, med, sd))[:, 1]
    ar = DecisionTreeClassifier(max_depth=4, min_samples_leaf=250, random_state=373).fit(A.mat_arbol(tr), tr.ok)
    te['q_arb'] = ar.predict_proba(A.mat_arbol(te))[:, 1]
    par = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80, subsample=0.8,
               subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=373)
    for col, num in (('q_lgb', A.NUM_LGB), ('q_lgb0', A.NUM_SIN)):
        m = lgb.LGBMClassifier(**par).fit(tr[num + A.CAT], tr.ok, categorical_feature=A.CAT)
        te[col] = m.predict_proba(te[num + A.CAT])[:, 1]
    # el apilado: logística de arriba con las predicciones WF fuera de muestra ANTERIORES al corte
    oof = x[(x.fecha < corte) & x.p_lgb.notna()]

    def M(q, a, b, c):
        return np.column_stack([A.lg(q.p_c), A.lg(q[a]), A.lg(q[b]), A.lg(q[c])])
    meta = LogisticRegression(C=1.0, max_iter=2000).fit(M(oof, 'p_log', 'p_lgb', 'p_arb'), oof.ok)
    iso = IsotonicRegression(out_of_bounds='clip', y_min=0.01, y_max=0.99)
    iso.fit(meta.predict_proba(M(oof, 'p_log', 'p_lgb', 'p_arb'))[:, 1], oof.ok)
    te['q_meta'] = meta.predict_proba(M(te, 'q_log', 'q_lgb', 'q_arb'))[:, 1]
    te['q_api'] = iso.predict(te.q_meta)
    return te


def calib(ev, cols):
    z = ev[(ev.cuota >= 1.30) & (ev.cuota <= 2.30)]
    out = {}
    for nom, col in cols.items():
        q = z[z[col].notna()]
        p = np.clip(q[col].values, 1e-3, 1 - 1e-3)
        out[nom] = {'n': int(len(q)), 'logloss': round(float(-np.mean(q.ok * np.log(p) + (1 - q.ok) * np.log(1 - p))), 4)}
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    R = {}
    x, info = A.universo()
    print('universo', info, '(%.0f s)' % (time.time() - T0))
    x, imp, imp0 = A.walk_forward(x)
    R['fechas_walk_forward'] = fechas_walk_forward(x)
    ev = x[x.p_log.notna() & (x.semana >= sorted(x.semana.unique())[2])].copy()
    corte = ev.drop_duplicates('partido').fecha.quantile(0.5)
    # 1. reproducción exacta (mismo orden de llamadas al rng del módulo que main())
    orig = json.load(open('_v373_aprendiz.json', encoding='utf-8'))
    Rp = A.prueba(ev, corte)
    rep = {}
    for piso in PISOS:
        for nom in ('casa (base)', 'apilado', 'lgbm', 'lgbm_sin_ctx', 'metodo'):
            f, o = Rp[piso][nom], orig['pisos'][str(piso)][nom]
            claves = ['n', 'acierto', 'base_acierto', 'cuota', 'gan_100', 'dif', 'dif_p5']
            nuevo = [f.get(k) for k in claves] + [f['A']['acierto'], f['B']['acierto'], f.get('veredicto')]
            viejo = [o.get(k) for k in claves] + [o['A']['acierto'], o['B']['acierto'], o.get('veredicto')]
            rep['%.2f %s' % (piso, nom)] = {'igual': nuevo == viejo, 'nuevo': nuevo, 'json': viejo,
                                            'boletos_N4': (f['boletos'][4].get('enteros'), f['boletos'][4].get('dias'),
                                                           o['boletos']['4'].get('enteros'))}
    R['reproduccion'] = rep
    print('reproducción: iguales %d de %d' % (sum(v['igual'] for v in rep.values()), len(rep)))
    for k, v in rep.items():
        if not v['igual']:
            print('  DIFIERE', k, v)
    # 2. fugas
    R['contexto'] = revisar_contexto()
    R['duplicados'] = revisar_duplicados(x)
    R['solape_AB'] = {'A_max': str(ev[ev.fecha < corte].fecha.max())[:10],
                      'B_min': str(ev[ev.fecha >= corte].fecha.min())[:10],
                      'partidos_en_ambas': int(len(set(ev[ev.fecha < corte].partido) & set(ev[ev.fecha >= corte].partido)))}
    print('contexto', R['contexto'])
    print('duplicados', R['duplicados'], 'solape', R['solape_AB'])
    # 3. empates del isotónico y apilado sin isotónico
    x, diag_meta = apilado_sin_iso(x)
    ev = x[x.p_log.notna() & (x.semana >= sorted(x.semana.unique())[2])].copy()
    R['meta_coef'] = diag_meta
    vals = ev.groupby('semana').p_api.nunique()
    R['isotonico_valores_distintos_por_semana'] = {k: int(v) for k, v in vals.items()}
    R['calibracion'] = calib(ev, {'casa': 'p_c', 'apilado': 'p_api', 'apilado_sin_iso': 'p_meta',
                                  'lgbm': 'p_lgb', 'lgbm_sin_ctx': 'p_lgb0', 'metodo': 'p_m'})
    # 4. otros cortes temporales sobre las MISMAS predicciones fuera de muestra
    fechas = ev.drop_duplicates('partido').fecha
    c70 = fechas.quantile(0.7)
    t1, t2 = fechas.quantile(1 / 3), fechas.quantile(2 / 3)
    CORTES = {
        'original_mitades': {'A': lambda q: q.fecha < corte, 'B': lambda q: q.fecha >= corte},
        'por_mes': {'sep': lambda q: q.fecha < '2026-10-01', 'oct': lambda q: q.fecha >= '2026-10-01'},
        '70_30': {'70': lambda q: q.fecha < c70, '30': lambda q: q.fecha >= c70},
        'tercios': {'T1': lambda q: q.fecha < t1, 'T2': lambda q: (q.fecha >= t1) & (q.fecha < t2),
                    'T3': lambda q: q.fecha >= t2},
    }
    R['cortes_fechas'] = {'mitad': str(corte)[:10], '70': str(c70)[:10], 'tercios': [str(t1)[:10], str(t2)[:10]],
                          'partidos_oct': int((fechas >= '2026-10-01').sum()), 'partidos': int(len(fechas))}
    MODS = {'apilado': 'p_api', 'apilado_sin_iso': 'p_meta', 'lgbm': 'p_lgb', 'lgbm_sin_ctx': 'p_lgb0',
            'logistica': 'p_log', 'arbol': 'p_arb', 'metodo': 'p_m'}
    R['cortes'] = {}
    for cn, segs in CORTES.items():
        R['cortes'][cn] = {}
        for nom, col in MODS.items():
            R['cortes'][cn][nom] = comparar(ev, col, segs)
    for cn in CORTES:
        print('== corte', cn)
        for nom in MODS:
            print('  %-15s' % nom, ' | '.join(
                '%.2f %s %.3f/%.3f %s' % (p, f['veredicto'][:4], f['acierto'], f['base'],
                                          ' '.join('%s%+.3f(%s)' % (k, s['dif'] if s['dif'] is not None else 0,
                                                                    s['p5']) for k, s in f['segmentos'].items()))
                for p, f in R['cortes'][cn][nom].items()))
    print('igual que la casa (apilado):', {p: f['igual_que_casa'] for p, f in R['cortes']['original_mitades']['apilado'].items()})
    print('igual que la casa (sin iso):', {p: f['igual_que_casa'] for p, f in R['cortes']['original_mitades']['apilado_sin_iso'].items()})
    # 5. un solo ajuste 70/30 (desde el principio de los datos)
    todas = x.drop_duplicates('partido').fecha
    c70x = todas.quantile(0.7)
    te = ajuste_7030(x, c70x)
    cm = te.drop_duplicates('partido').fecha.quantile(0.5)
    segs = {'30a': lambda q: q.fecha < cm, '30b': lambda q: q.fecha >= cm}
    R['ajuste_7030'] = {'corte': str(c70x)[:10], 'partidos_juzgados': int(te.partido.nunique()),
                        'calibracion': calib(te, {'casa': 'p_c', 'apilado': 'q_api', 'apilado_sin_iso': 'q_meta',
                                                  'lgbm': 'q_lgb', 'lgbm_sin_ctx': 'q_lgb0', 'logistica': 'q_log',
                                                  'arbol': 'q_arb', 'metodo': 'p_m'})}
    for nom, col in {'apilado': 'q_api', 'apilado_sin_iso': 'q_meta', 'lgbm': 'q_lgb', 'lgbm_sin_ctx': 'q_lgb0',
                     'logistica': 'q_log', 'arbol': 'q_arb'}.items():
        R['ajuste_7030'][nom] = comparar(te, col, segs)
    print('== ajuste único 70/30, corte', R['ajuste_7030']['corte'], 'partidos', R['ajuste_7030']['partidos_juzgados'])
    print('  calib', R['ajuste_7030']['calibracion'])
    for nom in ('apilado', 'apilado_sin_iso', 'lgbm', 'lgbm_sin_ctx', 'logistica', 'arbol'):
        print('  %-15s' % nom, ' | '.join(
            '%.2f %s %.3f/%.3f %s' % (p, f['veredicto'][:4], f['acierto'], f['base'],
                                      ' '.join('%s%+.3f(%s)' % (k, s['dif'] if s['dif'] is not None else 0, s['p5'])
                                               for k, s in f['segmentos'].items()))
            for p, f in R['ajuste_7030'][nom].items()))
    # resumen de veredictos
    resumen = {}
    for cn in CORTES:
        for nom in MODS:
            for p, f in R['cortes'][cn][nom].items():
                resumen.setdefault(nom, {}).setdefault('%.2f' % p, {})[cn] = f['veredicto']
    for nom in ('apilado', 'apilado_sin_iso', 'lgbm', 'lgbm_sin_ctx', 'logistica', 'arbol'):
        for p, f in R['ajuste_7030'][nom].items():
            resumen.setdefault(nom, {}).setdefault('%.2f' % p, {})['ajuste_7030'] = f['veredicto']
    R['resumen_veredictos'] = resumen
    print('calibración', R['calibracion'])
    R['segundos'] = round(time.time() - T0, 1)
    json.dump(R, open('_v373_aprendiz_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    print('%.0f s' % R['segundos'])


if __name__ == '__main__':
    main()
