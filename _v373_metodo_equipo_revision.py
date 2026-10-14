#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — Revisión escéptica de H4 (`_v373_metodo_equipo.py`): ¿se sostiene el «parcial»?

H4 dice: el Método Contexto en las líneas POR EQUIPO de Playdoit no da regla
implementable; a 1,30 / 1,45 / 1,60 «no pasa» y a 1,70 / 1,80 queda «parcial»
con «más · descanso parejo · método − casa > 6 pts» (elegida en A, +1,6 y
+5,8 pts sobre «la casa elige» en B, p5 < 0). Lo único que «se repite»: el
«más» de equipo con método − casa > 6 a cuota 1,70-2,30.

QUÉ SE REVISA (reutiliza las funciones de `_v373_metodo_equipo.py`)
  1. Fugas: mitades que se solapan (fechas), partidos duplicados (dos `mid` de
     las líneas que caen en el mismo partido del contexto), rasgos del
     contexto calculados con el propio partido (`l5_tiros` contra la media de
     los 5 anteriores con y sin el partido; `descanso` contra los días desde el
     partido anterior).
  2. Las reglas FIJAS (sin volver a elegir) con OTROS cortes de tiempo: por mes
     (agosto · septiembre · octubre), 70/30 (sólo el 30 % final), y por semana
     (cuántas semanas gana a la base). Con controles: el mismo segmento SIN el
     método (sólo «más · descanso parejo», la casa elige) y el complemento
     (método − casa ≤ 6): si el control rinde igual, el método no aporta.
  3. El PROCEDIMIENTO entero (elegir el segmento y el umbral con el mejor p5 en
     una parte y juzgarlo en la otra) con otros cortes: 70/30, «hasta
     septiembre → octubre» y el invertido (elegir en B, juzgar en A).
  4. Walk-forward semanal: cada semana (desde la 3.ª) se elige con TODO lo
     anterior y se aplica a esa semana; se juntan las patas y se comparan con
     «la casa elige» en esas mismas semanas.
Bootstrap emparejado por partido (el de `Mitad`, 1.000 réplicas).
Escribe `_v373_metodo_equipo_revision.json`.
"""
import importlib.util as iu
import json
import sys
import time

import numpy as np
import pandas as pd


def _mod(nombre, ruta):
    s = iu.spec_from_file_location(nombre, ruta)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


M = _mod('m373', '_v373_metodo_equipo.py')
M.NB = 1000
M.rng = np.random.default_rng(3739)
r4 = M.r4

REGLAS = {
    'R1 más · descanso parejo · >6 (la elegida a 1,70 y 1,80)': ((('ap', 'más'), ('desc', 'descanso parejo')), 0.06),
    'R2 más de equipo · >6 («lo único que se repite»)': ((('ap', 'más'),), 0.06),
    'C1 control: más · descanso parejo SIN método': ((('ap', 'más'), ('desc', 'descanso parejo')), None),
    'C2 control: más de equipo SIN método': ((('ap', 'más'),), None),
}


def construir():
    d = pd.read_pickle('_v362b_lineas.pkl').join(pd.read_pickle('_v366_lado.pkl'))
    e = pd.read_pickle(M.E_PATH)
    ju, ks = M.lambdas(e)
    d = M.con_contexto(d, e, ju)
    return d, e, M.universo(d)


def fugas(d, e, x):
    out = {}
    corte = x.fecha.quantile(0.5)
    A, B = x[x.fecha < corte], x[x.fecha >= corte]
    out['mitades'] = {'A_hasta': str(A.fecha.max())[:10], 'B_desde': str(B.fecha.min())[:10],
                      'partidos_en_las_dos': int(len(set(A.partido) & set(B.partido)))}
    em = d.drop_duplicates('mid')[['mid', 'emid']].dropna()
    rep = em.groupby('emid').mid.nunique()
    out['mid_lineas_sin_partido_contexto'] = int(d.drop_duplicates('mid').emid.isna().sum())
    out['partidos_contexto_con_2_o_mas_mid'] = int((rep > 1).sum())
    # misma liga, fecha y TODOS los totales reales → duplicado
    tot = (d[d.tipo == 'total'].drop_duplicates(['mid', 'obj']).pivot_table(index=['mid'], columns='obj',
                                                                           values='real', aggfunc='first'))
    meta = d.drop_duplicates('mid').set_index('mid')[['liga', 'fecha']]
    tot = tot.join(meta)
    clave = tot.reset_index(drop=True).apply(lambda r: '|'.join(map(str, r.values)), axis=1)
    out['mid_con_mismos_totales_liga_fecha'] = int(clave.duplicated(keep=False).sum())
    # rasgos del contexto: ¿antes del partido?
    ee = e.sort_values(['equipo', 'fecha'])
    g = ee.groupby('equipo')
    prev = g.tiros.transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    incl = g.tiros.transform(lambda s: s.rolling(5, min_periods=1).mean())
    ok = ee.l5_tiros.notna() & prev.notna()
    dd = g.fecha.diff().dt.days
    ok2 = ee.descanso.notna() & dd.notna()
    out['contexto_antes_del_partido'] = {
        'l5_tiros_vs_5_anteriores_mae': r4((ee.l5_tiros[ok] - prev[ok]).abs().mean()),
        'l5_tiros_vs_5_con_el_partido_mae': r4((ee.l5_tiros[ok] - incl[ok]).abs().mean()),
        'descanso_igual_dias_desde_el_anterior': r4((ee.descanso[ok2] == dd[ok2]).mean())}
    q = d[(d.tipo == 'equipo') & d.lado_real.isin(['local', 'visita']) & d.equipo.notna()]
    out['equipo_por_lambda_vs_resultado'] = r4((q.lado_real == q.equipo).mean())
    return out


def _sel(x, piso):
    return x[(x.cuota >= piso) & (x.cuota <= piso + M.ANCHO)]


def evaluar(x, D, piso, seg, u, mask, dias):
    band = _sel(x, piso)[mask(_sel(x, piso))]
    if band.empty:
        return {'n': 0}
    mi = M.Mitad(M.una_por_partido(band), dias)
    T = band[band.tipo == 'equipo']
    f = M.mascara(T, seg, D)
    if u is not None:
        f &= T.edge.values > u
    z = M.una_por_partido(T[f])
    r = mi.juzgar(z)
    keep = ('n', 'patas_dia', 'acierto', 'cuota', 'casa', 'metodo', 'gan_100', 'gan_p5', 'base_acierto',
            'dif', 'dif_p5', 'dif_gan_100', 'dif_gan_p5')
    return {k: r.get(k) for k in keep}


def fijas(x, D):
    """Las reglas fijas en cada corte: mitades, meses, 70/30, semanas."""
    c50, c70 = x.fecha.quantile(0.5), x.fecha.quantile(0.7)
    nd = lambda f: max(int(x[f(x)].fecha.dt.date.nunique()), 1)
    cortes = {
        'A (mitad 1)': lambda z: z.fecha < c50,
        'B (mitad 2)': lambda z: z.fecha >= c50,
        'agosto': lambda z: z.fecha.dt.month == 8,
        'septiembre': lambda z: z.fecha.dt.month == 9,
        'octubre': lambda z: z.fecha.dt.month == 10,
        'primer 70 %': lambda z: z.fecha < c70,
        'último 30 %': lambda z: z.fecha >= c70,
    }
    out = {'corte_70': str(c70)[:10]}
    for piso in (1.70, 1.80):
        out['%.2f' % piso] = {}
        for nom, (seg, u) in REGLAS.items():
            fila = {}
            for cn, f in cortes.items():
                fila[cn] = evaluar(x, D, piso, seg, u, f, nd(f))
            # semanas
            sem = x.fecha.dt.to_period('W')
            ws = {}
            for w in sorted(sem.unique()):
                f = (lambda w_: (lambda z: z.fecha.dt.to_period('W') == w_))(w)
                r = evaluar(x, D, piso, seg, u, f, nd(f))
                if r.get('n', 0) >= 5:
                    ws[str(w)[:10]] = {k: r.get(k) for k in ('n', 'acierto', 'base_acierto', 'dif', 'gan_100')}
            fila['semanas'] = ws
            fila['semanas_dif_positiva'] = '%d de %d' % (sum(1 for v in ws.values() if (v['dif'] or 0) > 0), len(ws))
            out['%.2f' % piso][nom] = fila
    return out


def procedimiento(x, D, SEG, fs, fj, nom):
    """Elegir (segmento, umbral) con el mejor p5 en la parte S y juzgar en J, por piso."""
    ds = max(int(x[fs(x)].fecha.dt.date.nunique()), 1)
    dj = max(int(x[fj(x)].fecha.dt.date.nunique()), 1)
    out = {'dias_eleccion': ds, 'dias_juicio': dj}
    for piso in M.PISOS:
        band = _sel(x, piso)
        S, J = band[fs(band)], band[fj(band)]
        Ms, Mj = M.Mitad(M.una_por_partido(S), ds), M.Mitad(M.una_por_partido(J), dj)
        TS, TJ = S[S.tipo == 'equipo'], J[J.tipo == 'equipo']
        cand = []
        for seg in SEG:
            mS, mJ = M.mascara(TS, seg, D), M.mascara(TJ, seg, D)
            for u in M.UMBRALES:
                zS = M.una_por_partido(TS[mS & (TS.edge.values > u)])
                if len(zS) < M.NMIN:
                    continue
                cand.append((seg, u, Ms.juzgar(zS, completo=False), mJ))
        if not cand:
            out['%.2f' % piso] = 'sin candidatos'
            continue
        cand.sort(key=lambda c: (-c[2]['dif_p5'], -c[2]['n']))
        seg, u, rS, mJ = cand[0]
        rJ = Mj.juzgar(M.una_por_partido(TJ[mJ & (TJ.edge.values > u)]))
        pos = [c for c in cand if c[2]['dif_p5'] > 0]
        arr_dif, arr_p5 = 0, 0
        for c in pos:
            r = Mj.juzgar(M.una_por_partido(TJ[c[3] & (TJ.edge.values > c[1])]), completo=False)
            arr_dif += int((r.get('dif') or -1) > 0)
            arr_p5 += int((r.get('dif_p5') or -1) > 0)
        b = rJ
        ver = ('pasa' if rS['dif'] > 0 and (b.get('dif') or -1) > 0 and (b.get('dif_p5') or -1) > 0
               else 'parcial' if (b.get('dif') or -1) > 0 else 'no pasa')
        out['%.2f' % piso] = {
            'regla': M.nombre(seg, u),
            'eleccion': {k: rS.get(k) for k in ('n', 'acierto', 'cuota', 'base_acierto', 'dif', 'dif_p5')},
            'juicio': {k: rJ.get(k) for k in ('n', 'acierto', 'cuota', 'casa', 'base_acierto', 'dif', 'dif_p5',
                                              'gan_100', 'gan_p5')},
            'candidatos': len(cand), 'p5_eleccion_mayor_0': len(pos),
            'de_esos_dif_juicio_mayor_0': arr_dif, 'de_esos_p5_juicio_mayor_0': arr_p5,
            'veredicto': ver}
        print('  [%s] %.2f %s | S %s | J %s | %s' % (nom, piso, out['%.2f' % piso]['regla'],
                                                    out['%.2f' % piso]['eleccion'], out['%.2f' % piso]['juicio'], ver))
    return out


def walk_forward(x, D, SEG):
    """Cada semana (desde la 3.ª) se elige (segmento, umbral) con TODO lo anterior y se aplica a esa
    semana. Se juntan las patas elegidas y se comparan con «la casa elige» en las mismas semanas."""
    sem_x = x.fecha.dt.to_period('W')
    ws = sorted(sem_x.unique())
    out = {}
    for piso in M.PISOS:
        band = _sel(x, piso)
        bs = band.fecha.dt.to_period('W')
        filas, log = [], []
        for i, w in enumerate(ws):
            if i < 2:
                continue
            S, J = band[bs < w], band[bs == w]
            if J.empty:
                continue
            Ms = M.Mitad(M.una_por_partido(S), S.fecha.dt.date.nunique())
            TS, TJ = S[S.tipo == 'equipo'], J[J.tipo == 'equipo']
            best = None
            for seg in SEG:
                mS = M.mascara(TS, seg, D)
                for u in M.UMBRALES:
                    zS = M.una_por_partido(TS[mS & (TS.edge.values > u)])
                    if len(zS) < M.NMIN:
                        continue
                    r = Ms.juzgar(zS, completo=False)
                    k = (r['dif_p5'], r['n'])
                    if best is None or k > best[0]:
                        best = (k, seg, u)
            if best is None:
                continue
            _, seg, u = best
            zJ = M.una_por_partido(TJ[M.mascara(TJ, seg, D) & (TJ.edge.values > u)])
            filas.append(zJ)
            log.append({'semana': str(w)[:10], 'regla': M.nombre(seg, u), 'n': int(len(zJ)),
                        'acierto': r4(zJ.ok.mean()) if len(zJ) else None})
        Z = pd.concat(filas) if filas else band.iloc[:0]
        Jall = band[bs >= ws[2]]
        Mj = M.Mitad(M.una_por_partido(Jall), Jall.fecha.dt.date.nunique())
        r = Mj.juzgar(Z)
        b = {k: r.get(k) for k in ('n', 'patas_dia', 'acierto', 'cuota', 'casa', 'base_acierto', 'dif', 'dif_p5',
                                   'gan_100', 'gan_p5', 'dif_gan_100', 'dif_gan_p5')}
        out['%.2f' % piso] = {'resultado': b, 'semanas': log}
        print('  [walk-forward] %.2f %s' % (piso, b))
        for f in log:
            print('       ', f)
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    t0 = time.time()
    d, e, x = construir()
    print('universo', len(x), 'patas', x.partido.nunique(), 'partidos (%.0f s)' % (time.time() - t0))
    R = {'fugas': fugas(d, e, x)}
    print('fugas', json.dumps(R['fugas'], ensure_ascii=False))
    T = x[x.tipo == 'equipo']
    D = M.dimensiones(T)
    SEG = M.segmentos(D)
    R['reglas_fijas'] = fijas(x, D)
    for p in ('1.70', '1.80'):
        for nom, fila in R['reglas_fijas'][p].items():
            print('\n%s %s' % (p, nom))
            for cn, r in fila.items():
                if cn == 'semanas':
                    continue
                print('   %-14s %s' % (cn, r if isinstance(r, str) else {k: r.get(k) for k in (
                    'n', 'acierto', 'cuota', 'casa', 'base_acierto', 'dif', 'dif_p5', 'gan_100', 'gan_p5')}))
    print('\nprocedimiento con otros cortes (%.0f s)' % (time.time() - t0))
    c50, c70, oct1 = x.fecha.quantile(0.5), x.fecha.quantile(0.7), pd.Timestamp('2026-10-01')
    R['procedimiento'] = {
        '70/30': procedimiento(x, D, SEG, lambda z: z.fecha < c70, lambda z: z.fecha >= c70, '70/30'),
        'hasta sep → oct': procedimiento(x, D, SEG, lambda z: z.fecha < oct1, lambda z: z.fecha >= oct1, 'sep→oct'),
        'invertido B → A': procedimiento(x, D, SEG, lambda z: z.fecha >= c50, lambda z: z.fecha < c50, 'B→A'),
    }
    print('\nwalk-forward por semana (%.0f s)' % (time.time() - t0))
    R['walk_forward_semanal'] = walk_forward(x, D, SEG)
    R['segundos'] = round(time.time() - t0, 1)
    print('\n%.0f s' % (time.time() - t0))
    json.dump(R, open('_v373_metodo_equipo_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
