#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — H2 · El aprendiz walk-forward para las patas de la soñadora a 1,30 / 1,45 /
1,60 / 1,70 / 1,80: ¿un modelo supervisado elige mejor que «la casa elige»?

El usuario (12-oct): «quiero boletos de N patas (hasta 25 o más) y poder escoger
la cuota: 1,5, 1,6, 1,7 — hay promociones donde cada selección tiene que ser
mínimo 1,60 —, pero siempre con buenas probabilidades de acuerdo con el
contexto, el histórico, los partidos y las estadísticas recientes de ambos
equipos, el rendimiento y el desgaste; de acuerdo con la casa, pero un paso
adelante de la casa. Machine learning, árboles de decisión, logísticas…».

LO YA MEDIDO (base): «Método Casa 70/130» 78,3 % a 1,31; la casa elige gana a
elegir por el modelo (72,1 vs 69,8 %); el aprendiz de v368/v371 (logística y
LightGBM sobre método + casa) calibraba algo mejor pero no decidía mejor.
Lo NUEVO aquí: los rasgos de CONTEXTO de los dos equipos (forma l5/ew de
goles, tiros, córners y tarjetas, descanso = desgaste, tabla, presión, zona,
puntos por partido, fuerza por precio), varias formas de quitarle el margen a
la casa (proporcional, aditiva, potencia, Shin) y el lado real de cada línea
de equipo resuelto con el tablero de Playdoit (también los «igual»).

DATOS
  · Escaleras de Playdoit con resultado (`_v362b_lineas.pkl`, 28-ago → 9-oct),
    los dos lados («más» y «menos» reconstruido), universo de
    `_v371_sencillas.playdoit()`.
  · Contexto por equipo-partido (`e_v361.pkl`, sólo rasgos con lo ANTERIOR al
    partido: `tiros_equipo.rasgos` desplaza todo una fecha). Los `mid` no
    coinciden: se empareja por liga + fecha (±1 día) + los valores reales de
    cada estadística, como `_v366c_lado.py`.
  · El lado (local / visita) de cada línea de equipo: la línea y la cuota del
    «más» en `corners_home` / `corners_away`… de la última foto del tablero
    antes del día (`_v344_precio.emparejar` sobre `_v362b_tableros.pkl`). Si el
    tablero no distingue y los dos equipos sacaron lo mismo, el lado se SORTEA
    (dejarlo vacío delataría el resultado).

MODELOS (walk-forward por SEMANA: cada semana se predice con modelos entrenados
SÓLO con las semanas anteriores; se juzga desde la 3.ª semana)
  logistica    — regresión logística L2 con rasgos orientados al lado apostado;
  arbol        — árbol de decisión de profundidad 4 (hojas ≥ 250 líneas);
  lgbm         — LightGBM con todo (casa, método, línea, mercado, lado, liga,
                 contexto);
  lgbm_sin_ctx — el mismo sin el contexto de los equipos (¿aporta el contexto?);
  apilado      — logística sobre los logits de casa + los tres modelos,
                 entrenada con sus predicciones FUERA DE MUESTRA de las semanas
                 anteriores, y calibración isotónica encima.

LA PRUEBA (por piso de cuota P: pata con cuota en [P, P+0,5])
  Una pata por partido: la de mayor probabilidad del modelo (desempate: la
  casa). LÍNEA BASE: «la casa elige» (la de mayor probabilidad de la casa
  proporcional) en el mismo piso y los mismos partidos. Dos mitades por fecha
  (A/B) y bootstrap PAREADO por partido de la diferencia de acierto (p5).
  Una regla pasa sólo si mejora a la base en LAS DOS mitades con p5 > 0.
  La regla JUZGADA se declara antes de correr: el APILADO (la hipótesis
  completa). Los otros modelos se reportan como diagnóstico, no para escoger
  al que mejor salga.
  Boletos del día (una pata por partido, las N de mayor probabilidad):
  N = 4, 6, 10, 15, 25 — días enteros / días, rojas medias y ganancia por
  $100 sin booster y con booster ×1,2 / ×1,3 / ×1,8 sobre el momio.
  Además: importancia de rasgos (ganancia de LightGBM por familia) y un árbol
  de RESIDUO (lo que pasó − lo que prometía la casa) ajustado en la mitad A y
  juzgado en la B, para ver si hay reglas legibles «si … entonces …» que
  justifiquen una pata ante el usuario; y esa regla puesta a ELEGIR con ajuste
  cruzado (árbol ajustado en una mitad, elige en la otra sólo entre las patas
  de sus hojas buenas, la más probable según la casa) contra la misma base.
Escribe `_v373_aprendiz.json`.
"""
import importlib.util as iu
import json
import os
import sys
import time

import numpy as np
import pandas as pd

T0 = time.time()
rng = np.random.default_rng(373)
E_CTX = os.environ.get('V373_E', r'C:\Users\HMREY\AppData\Local\Temp\claude\D--Claude'
                       r'\ac0b7101-79c7-47ef-8aff-6775a8d6ea8b\scratchpad\e_v361.pkl')
PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
ANCHO = 0.50
NS = (4, 6, 10, 15, 25)
BOOST = (1.0, 1.2, 1.3, 1.8)
NBOOT = 2000
COL = {'corners': 'corners', 'tiros': 'tiros', 'a_puerta': 'a_puerta', 'tarjetas': 'amarillas', 'goles': 'gf'}
CLAVE = {'corners': 'corners', 'tiros': 'remates', 'a_puerta': 'remates_on', 'tarjetas': 'tarjetas',
         'goles': 'goles'}
# la estadística propia y lo que concede el rival, para la «forma contra la línea»
FORMA = {'goles': ('l5_gf', 'l5_gc'), 'corners': ('l5_corners', 'l5_corners_c'),
         'tiros': ('l5_tiros', 'l5_tiros_c'), 'a_puerta': ('l5_a_puerta', 'l5_a_puerta_c'),
         'tarjetas': ('l5_amarillas', None)}
CTX = ['l5_gf', 'l5_gc', 'ew_tiros', 'ew_a_puerta', 'ew_tiros_c', 'l5_corners', 'l5_corners_c',
       'l5_amarillas', 'ppg', 'pos_rel', 'zona_alta', 'zona_baja', 'presion', 'avance', 'descanso',
       'n_prev', 'p_gana', 'p_empate', 'p_pierde',
       'r_l5_gf', 'r_l5_gc', 'r_ew_tiros', 'r_ew_a_puerta', 'r_ew_tiros_c', 'r_l5_corners',
       'r_l5_corners_c', 'r_l5_amarillas', 'r_ppg', 'r_pos_rel', 'r_zona_alta', 'r_zona_baja',
       'r_presion', 'r_descanso', 'r_n_prev']
DERIV = ['forma_stat', 'forma_or', 'desc_min', 'desc_dif', 'ppg_dif', 'fuerza', 'desequilibrio']


def _cargar(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V = _cargar('v371', '_v371_sencillas.py')


def lg(p):
    p = np.clip(np.asarray(p, float), 0.01, 0.99)
    return np.log(p / (1 - p))


# ------------------------------------------------------------------ contexto
def emparejar_contexto(d):
    """mid de las líneas → (mid de e_v361, fila local, fila visita, tablero)."""
    import _v344_precio as P
    e = pd.read_pickle(E_CTX)
    e = e[e.fecha >= d.fecha.min() - pd.Timedelta(days=1)]
    loc = e[e.local == 1].drop_duplicates('mid').set_index('mid')
    vis = e[e.local == 0].drop_duplicates('mid').set_index('mid')
    part = {}
    for m in loc.index.intersection(vis.index):
        a, b = loc.loc[m], vis.loc[m]
        part.setdefault((a.liga, pd.Timestamp(a.fecha).normalize()), []).append(
            (m, {o: (a[c], b[c]) for o, c in COL.items()}))
    emp = {}
    for mid, g in d.groupby('mid'):
        liga, fecha = g.liga.iloc[0], pd.Timestamp(g.fecha.iloc[0]).normalize()
        cands = []
        for dd in (0, -1, 1):
            cands += part.get((liga, fecha + pd.Timedelta(days=dd)), [])
        ok = []
        for me, c in cands:
            bien = True
            for r in g[g.tipo == 'total'].drop_duplicates('obj').itertuples():
                h, a = c[r.obj]
                if not (h == h and a == a and abs(h + a - r.real) < 1e-6):
                    bien = False
                    break
            for r in g[g.tipo == 'equipo'].drop_duplicates(['obj', 'real']).itertuples():
                if bien and r.real not in c[r.obj]:
                    bien = False
            if bien:
                ok.append(me)
        if len(ok) == 1:
            emp[mid] = ok[0]
    tab = pd.read_pickle('_v362b_tableros.pkl')
    tablero = P.emparejar(loc.loc[list(emp.values())].reset_index(), tab)
    return emp, loc, vis, tablero, P


def lado_por_tablero(d, emp, tablero, P):
    """El lado de cada línea de equipo: la línea y la cuota del «más» en el
    tablero local o visita. Si las dos coinciden (o no hay tablero), el del
    equipo cuyo valor real es el de la fila (es identificar la fila, no el
    resultado). Si los dos equipos sacaron lo MISMO («igual») el lado se sortea:
    dejarlo «sin» haría que la falta de contexto delatara un empate de la
    estadística (fuga del resultado)."""
    lado = pd.Series(np.where(d.tipo == 'total', 'total', 'sin'), index=d.index, dtype=object)
    diag = {'tablero': 0, 'real': 0, 'sorteo': 0, 'sin': 0, 'tablero_vs_real_coincide': 0,
            'tablero_vs_real_difiere': 0}
    sorteo = np.random.default_rng(3730)
    for idx, r in d[d.tipo == 'equipo'].iterrows():
        b = tablero.get(emp.get(r.mid))
        cand = []
        if b is not None:
            for lad, nom in (('home', 'local'), ('away', 'visita')):
                for k, v in P._lineas(b.get('%s_%s' % (CLAVE[r.obj], lad))).items():
                    try:
                        if abs(float(k) - r.linea) < 1e-6 and abs(float(v['mas']) - r.c_mas) < 1e-6:
                            cand.append(nom)
                    except Exception:
                        pass
        if len(cand) == 1:
            lado[idx] = cand[0]
            diag['tablero'] += 1
            if r.lado_real in ('local', 'visita'):
                diag['tablero_vs_real_coincide' if r.lado_real == cand[0] else 'tablero_vs_real_difiere'] += 1
        elif r.lado_real in ('local', 'visita'):
            lado[idx] = r.lado_real
            diag['real'] += 1
        elif r.lado_real == 'igual':
            lado[idx] = 'local' if sorteo.random() < 0.5 else 'visita'
            diag['sorteo'] += 1
        else:
            diag['sin'] += 1
    return lado, diag


def sin_margen(cm, cn):
    """Probabilidad del «más» sin margen: proporcional, aditiva, potencia, Shin."""
    im, inn = 1 / cm, 1 / cn
    s = im + inn
    prop = im / s
    add = np.clip(im - (s - 1) / 2, 0.01, 0.99)
    lo, hi = np.ones_like(im), np.full_like(im, 3.0)
    for _ in range(60):                                       # im^k + in^k = 1
        k = (lo + hi) / 2
        f = im ** k + inn ** k - 1
        lo, hi = np.where(f > 0, k, lo), np.where(f > 0, hi, k)
    pot = im ** ((lo + hi) / 2)
    zl, zh = np.zeros_like(im), np.full_like(im, 0.4)
    for _ in range(60):                                       # Shin, dos resultados
        z = (zl + zh) / 2
        pm = (np.sqrt(z ** 2 + 4 * (1 - z) * im ** 2 / s) - z) / (2 * (1 - z))
        pn = (np.sqrt(z ** 2 + 4 * (1 - z) * inn ** 2 / s) - z) / (2 * (1 - z))
        f = pm + pn - 1
        zl, zh = np.where(f > 0, z, zl), np.where(f > 0, zh, z)
    z = (zl + zh) / 2
    shin = (np.sqrt(z ** 2 + 4 * (1 - z) * im ** 2 / s) - z) / (2 * (1 - z))
    return prop, add, pot, shin, s - 1


def universo():
    d = pd.read_pickle('_v362b_lineas.pkl').join(pd.read_pickle('_v366_lado.pkl'))
    emp, loc, vis, tablero, P = emparejar_contexto(d)
    d['lado'], diag_lado = lado_por_tablero(d, emp, tablero, P)
    keep = (d.p_mod - d.p_casa).abs() <= 0.20                 # el filtro de playdoit()
    dk = d[keep]
    x = V.playdoit()
    assert len(x) == 2 * len(dk), (len(x), len(dk))
    x['orig'] = np.concatenate([dk.index.values, dk.index.values])
    x['lado'] = d.loc[x.orig, 'lado'].values
    x['mu'] = d.loc[x.orig, 'mu'].values                      # la λ del Método Contexto
    # contexto: el equipo de la línea (o el local en los totales) y su rival
    filas = []
    for o in x.orig.unique():
        r = d.loc[o]
        me = emp.get(r.mid)
        if me is None:
            continue
        fila = (vis if r.lado == 'visita' else loc).loc[me]
        if r.lado == 'sin':
            continue
        filas.append((o, fila))
    ctx = pd.DataFrame([f[CTX + ['local']].astype(float).values for _, f in filas],
                       index=[o for o, _ in filas], columns=CTX + ['local_eq'])
    # la forma de la estadística apostada contra la línea
    fs = {}
    for o, f in filas:
        r = d.loc[o]
        prop, conc = FORMA[r.obj]
        if r.tipo == 'equipo':
            v = f[prop] if conc is None else (f[prop] + f['r_' + conc]) / 2
        elif conc is None:
            v = f[prop] + f['r_' + prop]
        else:
            v = (f[prop] + f['r_' + conc]) / 2 + (f['r_' + prop] + f[conc]) / 2
        fs[o] = v
    ctx['forma_stat'] = pd.Series(fs)
    x = x.join(ctx, on='orig')
    x['con_ctx'] = x.forma_stat.notna().astype(int)
    x['sgn'] = np.where(x.lado_ap == 'más', 1.0, -1.0)
    x['forma_or'] = x.sgn * (x.forma_stat - x.linea) / np.sqrt(x.linea.clip(lower=0.5))
    x['dist_or'] = -x.sgn * x.dist_sd                         # > 0: la línea juega a favor del lado
    x['desc_min'] = np.minimum(x.descanso, x.r_descanso)
    x['desc_dif'] = x.descanso - x.r_descanso
    x['ppg_dif'] = x.ppg - x.r_ppg
    x['fuerza'] = x.p_gana - x.p_pierde
    x['desequilibrio'] = x.fuerza.abs()
    # la casa sin margen de varias formas (del lado apostado)
    cm = d.loc[x.orig, 'c_mas'].values
    cn = 1.0 / ((1.0 / cm) * (1 - d.loc[x.orig, 'p_casa'].values) / d.loc[x.orig, 'p_casa'].values)
    prop, add, pot, shin, marg = sin_margen(cm, cn)
    mas = (x.lado_ap == 'más').values
    x['p_prop'] = np.where(mas, prop, 1 - prop)
    x['p_add'] = np.where(mas, add, 1 - add)
    x['p_pot'] = np.where(mas, pot, 1 - pot)
    x['p_shin'] = np.where(mas, shin, 1 - shin)
    x['margen'] = marg
    x['gap'] = x.p_m - x.p_c
    x['semana'] = x.fecha.dt.to_period('W').astype(str)
    x['dia'] = x.fecha.dt.strftime('%Y-%m-%d')
    x['es_mas'] = mas.astype(float)
    x['es_total'] = (x.tipo == 'total').astype(float)
    x['es_local'] = (x.lado == 'local').astype(float)
    x['es_visita'] = (x.lado == 'visita').astype(float)
    x['liga_c'] = x.liga.astype('category')
    x['mercado_c'] = x.mercado.astype('category')
    x['lado_c'] = x.lado.astype('category')
    info = {'partidos': int(d.mid.nunique()), 'con_contexto': len(emp),
            'lado_equipo': d[d.tipo == 'equipo'].lado.value_counts().to_dict(), 'lado_como': diag_lado,
            'lineas_ambos_lados': int(len(x)), 'con_ctx_pct': round(float(x.con_ctx.mean()), 3)}
    return x.reset_index(drop=True), info


# ------------------------------------------------------------------- rasgos
OBJS = ['goles', 'corners', 'tiros', 'a_puerta', 'tarjetas']
NUM_LGB = ['p_m', 'p_c', 'p_add', 'p_pot', 'p_shin', 'margen', 'gap', 'cuota', 'linea', 'mu', 'dist_sd',
           'dist_or', 'es_mas', 'es_total', 'es_local', 'es_visita'] + CTX + DERIV
NUM_SIN = ['p_m', 'p_c', 'p_add', 'p_pot', 'p_shin', 'margen', 'gap', 'cuota', 'linea', 'mu', 'dist_sd',
           'dist_or', 'es_mas', 'es_total', 'es_local', 'es_visita']
CAT = ['liga_c', 'mercado_c', 'lado_c']
# el árbol legible: pocos rasgos con nombre claro
ARBOL = {'prob_casa': 'p_c', 'prob_metodo': 'p_m', 'metodo_menos_casa': 'gap', 'cuota': 'cuota',
         'linea_a_favor_sd': 'dist_or', 'forma_l5_a_favor': 'forma_or', 'descanso_min': 'desc_min',
         'descanso_dif': 'desc_dif', 'ppg_dif': 'ppg_dif', 'fuerza_precio': 'fuerza', 'es_mas': 'es_mas',
         'es_total': 'es_total', 'es_local': 'es_local'}


def mat_log(q, ligas, med, sd):
    """Rasgos de la logística, orientados al lado apostado (sgn)."""
    cols = [lg(q.p_m), lg(q.p_c), lg(q.p_pot), lg(q.p_shin), q.gap.values, q.dist_or.values,
            q.margen.values, np.log(q.cuota.values)]
    c = q[CTX + DERIV].copy()
    c = ((c - med) / sd).fillna(0.0).clip(-4, 4)
    for k in CTX + ['desc_min', 'desc_dif', 'ppg_dif', 'fuerza', 'desequilibrio', 'forma_stat']:
        cols.append(c[k].values * q.sgn.values)
    cols.append(c['forma_or'].values)
    cols.append(q.con_ctx.values)
    for m in sorted(V.OBJS):
        for t in ('total', 'equipo'):
            f = ((q.obj == m) & (q.tipo == t)).values.astype(float)
            cols += [f, f * q.sgn.values]
    for l_ in ('local', 'visita'):
        f = (q.lado == l_).values.astype(float)
        cols += [f, f * q.sgn.values]
    for l_ in ligas:
        f = (q.liga == l_).values.astype(float)
        cols += [f * q.sgn.values]
    return np.column_stack(cols)


def mat_arbol(q):
    return q[list(ARBOL.values())].fillna(0.0).values


def walk_forward(x):
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    sem = sorted(x.semana.unique())
    for c in ('p_log', 'p_arb', 'p_lgb', 'p_lgb0', 'p_api'):
        x[c] = np.nan
    imp, imp0 = [], []
    par = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80, subsample=0.8,
               subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=373)
    for i, s in enumerate(sem):
        if i < 1:
            continue
        tr, te = x[x.semana < s], x[x.semana == s]
        ligas = sorted(tr.liga.unique())
        med, sd = tr[CTX + DERIV].median(), tr[CTX + DERIV].std().replace(0, 1).fillna(1)
        lr = LogisticRegression(C=0.3, max_iter=4000).fit(mat_log(tr, ligas, med, sd), tr.ok)
        x.loc[te.index, 'p_log'] = lr.predict_proba(mat_log(te, ligas, med, sd))[:, 1]
        ar = DecisionTreeClassifier(max_depth=4, min_samples_leaf=250, random_state=373)
        ar.fit(mat_arbol(tr), tr.ok)
        x.loc[te.index, 'p_arb'] = ar.predict_proba(mat_arbol(te))[:, 1]
        for col, num, L in (('p_lgb', NUM_LGB, imp), ('p_lgb0', NUM_SIN, imp0)):
            m = lgb.LGBMClassifier(**par)
            m.fit(tr[num + CAT], tr.ok, categorical_feature=CAT)
            x.loc[te.index, col] = m.predict_proba(te[num + CAT])[:, 1]
            g = pd.Series(m.booster_.feature_importance('gain'), index=num + CAT)
            L.append(g / g.sum())
        # el apilado: con las predicciones FUERA DE MUESTRA de las semanas anteriores
        oof = x[(x.semana < s) & x.p_lgb.notna()]
        if i >= 2 and len(oof) > 500:
            def M(q):
                return np.column_stack([lg(q.p_c), lg(q.p_log), lg(q.p_lgb), lg(q.p_arb)])
            meta = LogisticRegression(C=1.0, max_iter=2000).fit(M(oof), oof.ok)
            iso = IsotonicRegression(out_of_bounds='clip', y_min=0.01, y_max=0.99)
            iso.fit(meta.predict_proba(M(oof))[:, 1], oof.ok)
            x.loc[te.index, 'p_api'] = iso.predict(meta.predict_proba(M(x.loc[te.index]))[:, 1])
        print('  semana %s: entrena %d líneas, predice %d  (%.0f s)' % (s, len(tr), len(te), time.time() - T0))
    return x, pd.concat(imp, axis=1).mean(axis=1), pd.concat(imp0, axis=1).mean(axis=1)


# ---------------------------------------------------------------- la prueba
# la regla que se JUZGA (declarada antes de correr): el apilado, que es la
# hipótesis completa; los demás se reportan como diagnóstico.
PRINCIPAL = 'apilado'
MODELOS = {'casa (base)': 'p_c', 'logistica': 'p_log', 'arbol': 'p_arb', 'lgbm': 'p_lgb',
           'lgbm_sin_ctx': 'p_lgb0', 'apilado': 'p_api', 'metodo': 'p_m'}


def elegir(z, col):
    z = z.assign(score=z[col]).sort_values(['score', 'p_c'], ascending=False).drop_duplicates('partido')
    return z.assign(gan=np.where(z.ok == 1, z.cuota - 1, -1.0))


def _boot_par(a, b, n=NBOOT):
    """Bootstrap PAREADO por partido de la diferencia de acierto (a − b)."""
    m = a[['partido', 'ok']].merge(b[['partido', 'ok']], on='partido', suffixes=('_a', '_b'))
    v = (m.ok_a - m.ok_b).values
    if len(v) < 20:
        return None, None
    idx = rng.integers(0, len(v), (n, len(v)))
    return float(v.mean()), float(np.percentile(v[idx].mean(1), 5))


def _boot(z, col, n=NBOOT):
    v = z[col].values
    idx = rng.integers(0, len(v), (n, len(v)))
    return float(np.percentile(v[idx].mean(1), 5))


def boletos(z, n):
    out = []
    for dia, g in z.groupby('dia'):
        g = g.sort_values(['score', 'p_c'], ascending=False).head(n)
        if len(g) < n:
            continue
        out.append((int(g.ok.sum()), float(np.prod(g.cuota)), float(np.prod(g.score.clip(0.01, 0.99)))))
    if not out:
        return {'dias': 0}
    bien = np.array([o[0] for o in out])
    mom = np.array([o[1] for o in out])
    r = {'dias': len(out), 'enteros': int((bien == n).sum()), 'rojas_media': round(float((n - bien).mean()), 2),
         'momio_medio': round(float(np.median(mom)), 1),
         'prob_prometida': round(float(np.mean([o[2] for o in out])), 4)}
    for b in BOOST:
        r['gan_100_x%.1f' % b] = round(100 * float(np.mean(np.where(bien == n, mom * b - 1, -1.0))), 1)
    return r


def prueba(x, corte):
    R = {}
    for piso in PISOS:
        z0 = x[(x.cuota >= piso) & (x.cuota <= piso + ANCHO)]
        base = elegir(z0, 'p_c')
        R[piso] = {}
        for nom, col in MODELOS.items():
            z = z0[z0[col].notna()]
            if not len(z):
                continue
            ch = elegir(z, col)
            b = base[base.partido.isin(ch.partido)]
            f = {'n': int(len(ch)), 'patas_dia': round(float(ch.groupby('dia').size().mean()), 1),
                 'acierto': round(float(ch.ok.mean()), 4), 'promete': round(float(ch.score.mean()), 4),
                 'promete_casa': round(float(ch.p_c.mean()), 4), 'cuota': round(float(ch.cuota.mean()), 3),
                 'gan_100': round(100 * float(ch.gan.mean()), 1), 'gan_p5': round(100 * _boot(ch, 'gan'), 1),
                 'base_acierto': round(float(b.ok.mean()), 4), 'base_cuota': round(float(b.cuota.mean()), 3)}
            dif, p5 = _boot_par(ch, b)
            if nom != 'casa (base)' and dif is not None:
                f['dif'], f['dif_p5'] = round(dif, 4), round(p5, 4)
            for t, m in (('A', ch.fecha < corte), ('B', ch.fecha >= corte)):
                q = ch[m]
                bq = b[b.partido.isin(q.partido)]
                f[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4),
                        'base': round(float(bq.ok.mean()), 4), 'cuota': round(float(q.cuota.mean()), 3),
                        'gan_100': round(100 * float(q.gan.mean()), 1)}
                if nom != 'casa (base)':
                    dq, pq = _boot_par(q, bq)
                    if dq is not None:
                        f[t]['dif'], f[t]['dif_p5'] = round(dq, 4), round(pq, 4)
            if nom != 'casa (base)' and 'dif' in f.get('A', {}) and 'dif' in f.get('B', {}):
                ambas = f['A']['dif'] > 0 and f['B']['dif'] > 0
                f['veredicto'] = ('pasa' if ambas and f['A']['dif_p5'] > 0 and f['B']['dif_p5'] > 0 else
                                  'parcial' if ambas else 'no_pasa')
            f['boletos'] = {n: boletos(ch, n) for n in NS}
            f['por_mercado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3), round(float(g.cuota.mean()), 2)]
                                for m, g in ch.groupby('mercado') if len(g) >= 15}
            f['por_lado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3)] for m, g in ch.groupby('lado_ap')}
            R[piso][nom] = f
    return R


def calibracion(x):
    z = x[(x.cuota >= 1.30) & (x.cuota <= 2.30)]
    out = {}
    for nom, col in MODELOS.items():
        q = z[z[col].notna() & z.p_api.notna()]
        p = np.clip(q[col].values, 1e-3, 1 - 1e-3)
        out[nom] = {'n': int(len(q)), 'logloss': round(float(-np.mean(q.ok * np.log(p) + (1 - q.ok) * np.log(1 - p))), 4),
                    'brier': round(float(np.mean((q.ok - p) ** 2)), 4)}
    return out


def familias(imp):
    fam = {'casa (precio)': ['p_c', 'p_add', 'p_pot', 'p_shin', 'margen', 'cuota'],
           'metodo contexto': ['p_m', 'gap', 'mu'], 'linea': ['linea', 'dist_sd', 'dist_or'],
           'mercado / lado': ['es_mas', 'es_total', 'es_local', 'es_visita', 'mercado_c', 'lado_c'],
           'liga': ['liga_c'], 'contexto equipos': CTX + DERIV}
    out = {k: round(float(imp.reindex(v).fillna(0).sum()), 4) for k, v in fam.items()}
    top = imp.sort_values(ascending=False).head(15)
    return out, {k: round(float(v), 4) for k, v in top.items()}


def reglas_legibles(x, corte):
    """Árbol de RESIDUO (ok − casa) en la mitad A, juzgado hoja por hoja en la B."""
    from sklearn.tree import DecisionTreeRegressor, export_text
    z = x[(x.cuota >= 1.30) & (x.cuota <= 2.30)]
    A, B = z[z.fecha < corte], z[z.fecha >= corte]
    t = DecisionTreeRegressor(max_depth=3, min_samples_leaf=300, random_state=373)
    t.fit(mat_arbol(A), A.ok - A.p_c)
    texto = export_text(t, feature_names=list(ARBOL), decimals=2)
    hA, hB = t.apply(mat_arbol(A)), t.apply(mat_arbol(B))
    # el camino de cada hoja en palabras
    tr_ = t.tree_
    nombres = list(ARBOL)
    camino = {}

    def rec(nodo, cond):
        if tr_.children_left[nodo] == -1:
            camino[nodo] = ' y '.join(cond) or 'todo'
            return
        f, u = nombres[tr_.feature[nodo]], tr_.threshold[nodo]
        rec(tr_.children_left[nodo], cond + ['%s ≤ %.2f' % (f, u)])
        rec(tr_.children_right[nodo], cond + ['%s > %.2f' % (f, u)])
    rec(0, [])
    hojas = []
    for h in sorted(set(hA)):
        a, b = A[hA == h], B[hB == h]
        p5B = None
        if len(b) >= 30:                                       # p5 del residuo en B, por partido
            g = b.assign(res=b.ok - b.p_c).groupby('partido').res.agg(['sum', 'count']).values
            idx = rng.integers(0, len(g), (NBOOT, len(g)))
            p5B = round(float(np.percentile(g[idx, 0].sum(1) / g[idx, 1].sum(1), 5)), 3)
        hojas.append({'si': camino[h], 'A_n': int(len(a)), 'A_acierto': round(float(a.ok.mean()), 3),
                      'A_casa': round(float(a.p_c.mean()), 3),
                      'B_n': int(len(b)), 'B_acierto': round(float(b.ok.mean()), 3) if len(b) else None,
                      'B_casa': round(float(b.p_c.mean()), 3) if len(b) else None,
                      'B_partidos': int(b.partido.nunique()), 'B_residuo_p5': p5B})
    for hj in hojas:
        hj['sobre_casa_A'] = round(hj['A_acierto'] - hj['A_casa'], 3)
        hj['sobre_casa_B'] = None if hj['B_acierto'] is None else round(hj['B_acierto'] - hj['B_casa'], 3)
        hj['sostiene'] = bool(hj['sobre_casa_B'] is not None and hj['B_n'] >= 100 and
                              hj['sobre_casa_A'] > 0.02 and hj['sobre_casa_B'] > 0.02 and
                              (hj['B_residuo_p5'] or 0) > 0)
    return texto, hojas


def _caminos(t):
    """El camino de cada hoja del árbol en palabras."""
    tr_, nombres, camino = t.tree_, list(ARBOL), {}

    def rec(nodo, cond):
        if tr_.children_left[nodo] == -1:
            camino[nodo] = ' y '.join(cond) or 'todo'
            return
        f, u = nombres[tr_.feature[nodo]], tr_.threshold[nodo]
        rec(tr_.children_left[nodo], cond + ['%s ≤ %.2f' % (f, u)])
        rec(tr_.children_right[nodo], cond + ['%s > %.2f' % (f, u)])
    rec(0, [])
    return camino


def regla_arbol_cruzada(x):
    """La regla legible como REGLA DE ELECCIÓN, con ajuste cruzado: el árbol de
    residuo se ajusta en una mitad, sus hojas con residuo > +2 pts (y 100+
    líneas) son las «buenas», y en la OTRA mitad se elige, por partido, la pata
    más probable según la casa SÓLO entre las de hojas buenas. Se compara con
    «la casa elige» en los mismos partidos y el mismo piso (bootstrap pareado
    por partido). Pasa si mejora en las dos mitades con p5 > 0."""
    from sklearn.tree import DecisionTreeRegressor, export_text
    corte = x.drop_duplicates('partido').fecha.quantile(0.5)
    mitad = {'A': x[x.fecha < corte], 'B': x[x.fecha >= corte]}
    out = {'corte': str(corte)[:10]}
    elegidas = {piso: [] for piso in PISOS}
    for juz, aj in (('B', 'A'), ('A', 'B')):
        F = mitad[aj]
        F = F[(F.cuota >= 1.30) & (F.cuota <= 2.30)]
        t = DecisionTreeRegressor(max_depth=3, min_samples_leaf=300, random_state=373)
        t.fit(mat_arbol(F), F.ok - F.p_c)
        res = (F.ok - F.p_c).groupby(t.apply(mat_arbol(F))).agg(['mean', 'size'])
        buenas = [h for h, r in res.iterrows() if r['mean'] > 0.02 and r['size'] >= 100]
        cam = _caminos(t)
        J = mitad[juz].assign(hoja=t.apply(mat_arbol(mitad[juz])))
        o = {'ajustado_en': aj, 'arbol': export_text(t, feature_names=list(ARBOL), decimals=2),
             'hojas_buenas': [{'si': cam[h], 'residuo_ajuste': round(float(res.loc[h, 'mean']), 3),
                               'n_ajuste': int(res.loc[h, 'size'])} for h in buenas], 'pisos': {}}
        for piso in PISOS:
            z0 = J[(J.cuota >= piso) & (J.cuota <= piso + ANCHO)]
            base = elegir(z0, 'p_c')
            ch = elegir(z0[z0.hoja.isin(buenas)], 'p_c')
            if not len(ch):
                o['pisos'][piso] = {'n': 0}
                continue
            b = base[base.partido.isin(ch.partido)]
            dif, p5 = _boot_par(ch, b)
            o['pisos'][piso] = {'n': int(len(ch)), 'patas_dia': round(float(ch.groupby('dia').size().mean()), 1),
                                'acierto': round(float(ch.ok.mean()), 4), 'base': round(float(b.ok.mean()), 4),
                                'cuota': round(float(ch.cuota.mean()), 3), 'base_cuota': round(float(b.cuota.mean()), 3),
                                'gan_100': round(100 * float(ch.gan.mean()), 1),
                                'base_gan_100': round(100 * float(b.gan.mean()), 1),
                                'dif': None if dif is None else round(dif, 4),
                                'dif_p5': None if p5 is None else round(p5, 4),
                                'por_lado': {m: [int(len(g)), round(float(g.ok.mean()), 3)]
                                             for m, g in ch.groupby('lado_ap')}}
            elegidas[piso].append(ch)
        out[juz] = o
    out['pisos'] = {}
    for piso in PISOS:
        A_, B_ = out['A']['pisos'].get(piso, {}), out['B']['pisos'].get(piso, {})
        ok = all((h.get('dif') or 0) > 0 for h in (A_, B_))
        ok5 = ok and all((h.get('dif_p5') or -1) > 0 for h in (A_, B_))
        f = {'veredicto': 'pasa' if ok5 else 'parcial' if ok else 'no_pasa'}
        if elegidas[piso]:
            ch = pd.concat(elegidas[piso])
            f.update({'n': int(len(ch)), 'acierto': round(float(ch.ok.mean()), 4),
                      'cuota': round(float(ch.cuota.mean()), 3), 'gan_100': round(100 * float(ch.gan.mean()), 1),
                      'gan_p5': round(100 * _boot(ch, 'gan'), 1),
                      'boletos': {n: boletos(ch, n) for n in NS}})
        out['pisos'][piso] = f
    return out


def coef_logistica(x):
    """Coeficientes de la logística entrenada con todo (descriptivo, rasgos estandarizados)."""
    from sklearn.linear_model import LogisticRegression
    ligas = sorted(x.liga.unique())
    med, sd = x[CTX + DERIV].median(), x[CTX + DERIV].std().replace(0, 1).fillna(1)
    X = mat_log(x, ligas, med, sd)
    mu_, sx = X.mean(0), X.std(0)
    sx[sx == 0] = 1
    lr = LogisticRegression(C=0.3, max_iter=4000).fit((X - mu_) / sx, x.ok)
    nom = ['lg_metodo', 'lg_casa', 'lg_casa_pot', 'lg_casa_shin', 'gap', 'linea_a_favor', 'margen', 'log_cuota']
    nom += [k + '×lado' for k in CTX + ['desc_min', 'desc_dif', 'ppg_dif', 'fuerza', 'desequilibrio', 'forma_stat']]
    nom += ['forma_a_favor', 'con_ctx']
    for m in sorted(V.OBJS):
        for t in ('total', 'equipo'):
            nom += ['%s %s' % (m, t), '%s %s×lado' % (m, t)]
    nom += ['local', 'local×lado', 'visita', 'visita×lado'] + [l_ + '×lado' for l_ in ligas]
    c = pd.Series(lr.coef_[0], index=nom)
    return {k: round(float(v), 3) for k, v in c.reindex(c.abs().sort_values(ascending=False).index).head(20).items()}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    x, info = universo()
    print('universo', info, '(%.0f s)' % (time.time() - T0))
    x, imp, imp0 = walk_forward(x)
    ev = x[x.p_log.notna() & (x.semana >= sorted(x.semana.unique())[2])].copy()
    corte = ev.drop_duplicates('partido').fecha.quantile(0.5)
    print('juzgado desde', str(ev.fecha.min())[:10], 'partidos', ev.partido.nunique(), 'corte A/B', str(corte)[:10])
    R = {'info': info, 'juzgado_desde': str(ev.fecha.min())[:10], 'hasta': str(ev.fecha.max())[:10],
         'partidos_juzgados': int(ev.partido.nunique()), 'corte_AB': str(corte)[:10], 'principal': PRINCIPAL}
    R['calibracion_1.30_2.30'] = calibracion(ev)
    R['pisos'] = prueba(ev, corte)
    fam, top = familias(imp)
    R['importancia_lgbm'] = {'familias': fam, 'top': top}
    fam0, _ = familias(imp0)
    R['importancia_lgbm_sin_ctx'] = fam0
    R['coef_logistica'] = coef_logistica(x)
    texto, hojas = reglas_legibles(x, x.drop_duplicates('partido').fecha.quantile(0.5))
    R['arbol_residuo'] = {'texto': texto, 'hojas': hojas}
    R['regla_arbol_cruzada'] = regla_arbol_cruzada(x)
    R['segundos'] = round(time.time() - T0, 1)
    json.dump(R, open('_v373_aprendiz.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print('calibración', R['calibracion_1.30_2.30'])
    for piso, M in R['pisos'].items():
        print('== piso %.2f' % piso)
        for nom, f in M.items():
            print('  %-13s n %4d %4.1f/día  ac %.3f (base %.3f) cuota %.2f  gan %+5.1f p5 %+5.1f | A %s %s | B %s %s | %s' % (
                nom, f['n'], f['patas_dia'], f['acierto'], f['base_acierto'], f['cuota'], f['gan_100'], f['gan_p5'],
                f['A']['acierto'], (f['A'].get('dif'), f['A'].get('dif_p5')),
                f['B']['acierto'], (f['B'].get('dif'), f['B'].get('dif_p5')), f.get('veredicto', '')))
            print('     boletos', {n: (b.get('enteros'), b.get('dias'), b.get('rojas_media'), b.get('gan_100_x1.0'),
                                    b.get('gan_100_x1.3')) for n, b in f['boletos'].items()})
    print('importancia', fam, top)
    print('sin ctx', fam0)
    print('coef', R['coef_logistica'])
    print(texto)
    for h in hojas:
        print('  ', h)
    rc = R['regla_arbol_cruzada']
    for juz in ('A', 'B'):
        print('regla del árbol juzgada en', juz, 'hojas buenas', rc[juz]['hojas_buenas'])
        for piso, f in rc[juz]['pisos'].items():
            print('   %.2f %s' % (piso, f))
    for piso, f in rc['pisos'].items():
        print('  cruzada %.2f %s' % (piso, {k: v for k, v in f.items() if k != 'boletos'}))
        print('     boletos', {n: (b.get('enteros'), b.get('dias'), b.get('rojas_media'), b.get('gan_100_x1.0'),
                                b.get('gan_100_x1.3')) for n, b in f.get('boletos', {}).items()})
    print('%.0f s' % R['segundos'])


if __name__ == '__main__':
    main()
