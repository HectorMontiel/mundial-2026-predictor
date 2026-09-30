# -*- coding: utf-8 -*-
"""
v316 — LAS MITADES: ¿SE PUEDEN PRONOSTICAR, Y LES AYUDA LA TABLA?

El usuario: «¿Mitades? Para eso también ayuda la tabla, la clasificación…
no sólo en esa liga sino en todas».

POR QUÉ NO SE HABÍA MEDIDO
Ningún histórico del motor de ligas trae el marcador al descanso (ni el de
football-data ni el de FotMob que se guarda). Flashscore da en su feed los
goles de la 2.ª mitad (campos BC/BD; la primera versión los tomó por el
descanso y la parte de goles de la 1.ª mitad salía 55 %, al revés de lo que
se sabe; comprobado con Liverpool 3-1 Southampton, 0-1 al descanso) y desde
la v316 `resultados_flashscore.py` guarda el descanso = final − 2.ª mitad.

PASO 1 — RELLENAR: a cada competición de la base de Flashscore se le vuelven
a pedir su temporada en curso y las anteriores, esta vez con el descanso.

PASO 2 — MEDIR, fuera de muestra (cada partido con lo previo; el modelo
propio de `modelo_competiciones` sobre la base de Flashscore):
    · más de 0,5 y de 1,5 goles en la 1.ª mitad;
    · más de 0,5 y de 1,5 goles en la 2.ª mitad;
    · marca el local / el visitante en la 1.ª mitad.
Base = Poisson con las λ del partido por la parte de goles de cada mitad
(aprendida en el tramo de elección). «Siempre» = LightGBM con λ y forma de
goles; «+ tabla» = eso más la tabla de la temporada (diferencia de goles,
a favor/en contra por partido, posición, zonas). 70 % / 30 % por fecha,
bootstrap 2.000, p5 > 0.

RESULTADO (2026-09-29, 226 mil partidos, 428 competiciones, juicio 54.185)
La 1.ª mitad lleva el 45,1 % de los goles. Repartir las λ del partido con
esa proporción ya calibra: más de 0,5 en la 1.ª mitad, 73,6 % previsto
contra 74,0 % real; en la 2.ª, 80,0 % contra 81,1 %. La forma de goles
añade un poco sobre eso (p5 > 0 en las seis) y la TABLA NO AÑADE NADA MÁS
en ninguna (p5 contra «siempre» entre −0,00004 y −0,00032). Las mitades no
se ofrecen en la aplicación; si se añaden, con el reparto 45/55 y la
corrección de forma, sin la tabla.

Uso: python _v316_mitades.py [--sin-rellenar]   (escribe _v316_mitades.json)
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

DESDE = pd.Timestamp('2024-07-01')      # desde aquí se registran predicciones


def rellenar(hilos: int = 6) -> int:
    import resultados_flashscore as rf
    b = rf.cargar(recargar=True)
    rutas = sorted(b['ruta'].dropna().unique())

    def una(ruta):
        paginas = [ruta] + rf._temporadas_previas(ruta)
        filas = []
        for p in paginas:
            t = rf._get(rf.WEB + p + 'results/')
            if t:
                filas += rf._partidos(t, '', ruta)
                # y el resto de la temporada (la página sólo trae ~100)
                for t2 in rf.paginas_siguientes(t):
                    filas += rf._partidos(t2, '', ruta)
        return filas
    nuevas = []
    with ThreadPoolExecutor(hilos) as ex:
        for i, f in enumerate(ex.map(una, rutas)):
            nuevas += f
            if i % 50 == 0:
                print('  %d/%d rutas' % (i, len(rutas)), flush=True)
    nd = pd.DataFrame(nuevas)
    nd['ini'] = pd.to_datetime(nd['ini'])
    # se conserva el nombre de liga que ya tenía cada partido
    viejo = b.set_index('match_id')['liga']
    nd['liga'] = nd['match_id'].map(viejo).fillna(nd['ruta'])
    todo = pd.concat([b, nd], ignore_index=True) \
        .drop_duplicates('match_id', keep='last').sort_values('ini').reset_index(drop=True)
    for c in rf.COLUMNAS:
        if c not in todo.columns:
            todo[c] = None
    todo[rf.COLUMNAS].to_csv(rf.FICHERO, index=False, compression='gzip',
                             date_format='%Y-%m-%d %H:%M:%S')
    rf._MEM.pop('df', None)
    return int(todo['hh'].notna().sum())


def conjunto() -> pd.DataFrame:
    import modelo_competiciones as mc
    import patrones_liga as pl
    import resultados_flashscore as rf
    import _v316_tabla_mercados as tm
    b = rf.cargar(recargar=True)
    x = pd.DataFrame({
        'match_id': b['match_id'], 'ini': b['ini'], 'liga_id': b['ruta'],
        'home_id': [rf.clave_equipo(r, h) for r, h in zip(b['ruta'], b['home'])],
        'away_id': [rf.clave_equipo(r, a) for r, a in zip(b['ruta'], b['away'])],
        'home': b['home'], 'away': b['away'], 'gh': b['gh'], 'ga': b['ga']})
    _, pred = mc.entrenar(x, registrar_desde=DESDE)
    P = pd.DataFrame(pred, columns=['match_id', 'lh', 'la', 'nh', 'na'])
    P = P[(P['nh'] >= mc.MIN_PARTIDOS) & (P['na'] >= mc.MIN_PARTIDOS)]
    # la tabla de cada competición, partido a partido
    TablaExt = tm._tabla_ext()
    filas = []
    for ruta, g in b.groupby('ruta'):
        t = TablaExt(copa=False)
        for r in g.sort_values('ini').itertuples(index=False):
            f = t.rasgos(r.home, r.away, r.ini)
            f['match_id'] = r.match_id
            filas.append(f)
            t.sumar(r.home, r.away, r.ini, float(r.gh), float(r.ga))
    R = pd.DataFrame(filas)
    df = P.merge(b[['match_id', 'ini', 'ruta', 'gh', 'ga', 'hh', 'ha']], on='match_id') \
        .merge(R, on='match_id')
    df = df.dropna(subset=['hh', 'ha']).rename(columns={'ruta': 'liga', 'ini': 'fecha'})
    df['h2'], df['a2'] = df['gh'] - df['hh'], df['ga'] - df['ha']
    df['t1'], df['t2'] = df['hh'] + df['ha'], df['h2'] + df['a2']
    return df.sort_values('fecha').reset_index(drop=True)


OBJ = {'1a_mas_0.5': ('t1', .5, 't'), '1a_mas_1.5': ('t1', 1.5, 't'),
       '2a_mas_0.5': ('t2', .5, 't'), '2a_mas_1.5': ('t2', 1.5, 't'),
       'local_marca_1a': ('hh', .5, 'h'), 'visit_marca_1a': ('ha', .5, 'a')}


def main():
    import patrones_liga as pl
    import _v316_tabla_mercados as tm
    from scipy.stats import poisson
    if '--sin-rellenar' not in sys.argv:
        print('con descanso:', rellenar(), flush=True)
    df = conjunto()
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    ele = df['fecha'] < corte
    # la parte de los goles que cae en la 1.ª mitad, aprendida en elección
    s1 = float(df.loc[ele, 't1'].sum() / (df.loc[ele, 't1'].sum() + df.loc[ele, 't2'].sum()))
    ligas = sorted(df['liga'].unique())
    codigos = {l: i for i, l in enumerate(ligas)}
    rng = np.random.default_rng(316)
    out = {'n': int(len(df)), 'competiciones': len(ligas), 'corte': str(corte.date()),
           'parte_goles_1a_mitad': round(s1, 4)}
    forma = ['ppg_h', 'ppg_a', 'gf_h', 'gc_h', 'gf_a', 'gc_a', 'gf5_h', 'gc5_h',
             'gf5_a', 'gc5_a', 'casa_gf_h', 'casa_gc_h', 'fuera_gf_a', 'fuera_gc_a']
    df['lam_h'], df['lam_a'] = df['lh'], df['la']
    for nombre, (col, L, quien) in OBJ.items():
        s = s1 if nombre.startswith('1a') or '1a' in nombre else 1 - s1
        lam = {'t': df['lh'] + df['la'], 'h': df['lh'], 'a': df['la']}[quien] * s
        df['y_'] = (df[col] > L).astype(int)
        df['p_'] = 1 - poisson.cdf(np.floor(L), lam)
        e, j = df[ele], df[~ele]
        r_s = ['lam_h', 'lam_a'] + forma + ['liga_cod', 'logit_modelo']
        r_t = ['lam_h', 'lam_a'] + forma + tm.TABLA + ['liga_cod', 'logit_modelo']
        r = tm._prueba(e, j, 'y_', 'p_', r_s, r_t, codigos, rng)
        yj, pj = j['y_'].to_numpy(), j['p_'].to_numpy()
        r['poisson_sin_corregir'] = {'p_media': round(float(pj.mean()), 4),
                                     'log-loss': round(float(pl._ll(yj, pj).mean()), 5)}
        out[nombre] = r
        print(nombre, json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(out, open('_v316_mitades.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
