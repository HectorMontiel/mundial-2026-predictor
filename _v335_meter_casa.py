# -*- coding: utf-8 -*-
"""
v335 — «METER» ELEGIDO POR EL PRECIO DE LA CASA, NO POR EL MODELO.

El usuario eligió las dos opciones de la v334. Ésta es la A: la v334 midió
que, a IGUAL número de apuestas, el precio de la casa sin margen elige
mejores partidos que el modelo (+1,5 a +2,4 pts de verdes, p5 > 0) y que el
apilado le da peso ≈ 1 al precio y ≈ 0 al modelo.

LA REGLA NUEVA, sobre la simulación de la tarjeta (`_v331_sim_candidatas`,
765 partidos, 20-sep a 6-oct, precios de Playdoit):
  · donde la casa cotiza la apuesta (goles, goles por equipo, ganador, doble
    oportunidad, ambos marcan): se mete si su probabilidad SIN MARGEN
    (`p_mercado`) llega al umbral T, con la cuota < 1,35 y las exclusiones de
    siempre (doble y goles, remates, hándicap, línea 2,5 del total);
  · donde no cotiza (córners, tarjetas): lo que ya se metía, igual;
  · máximo 2 por partido y una sola de resultado, las más probables primero.
T se elige con los días de mirar (70 %) para dar el MISMO número de apuestas
que la regla de hoy, y se juzga con los últimos días.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(335)
FUERA = ('Doble y goles', 'Remates', 'Remates a puerta', 'Handicap')
RESULTADO = ('1X2', 'Doble oportunidad')
CON_PRECIO = ('Goles', 'Goles equipo', '1X2', 'Doble oportunidad', 'BTTS')


def cargar(ruta='_v331_sim_candidatas.csv.gz'):
    v = pd.read_csv(ruta)
    v = v[v.acierto.notna()].copy()
    v['fecha'] = pd.to_datetime(v.dia)
    return v


def elegibles(v, T, techo=1.35, piso=1.01, modelo_min=0.0):
    linea25 = (v.mercado == 'Goles') & v.apuesta.str.contains(r'(?:Más|Menos) de 2\.5$', regex=True)
    precio = (v.mercado.isin(CON_PRECIO) & ~v.mercado.isin(FUERA) & ~linea25
              & v.p_mercado.notna() & (v.p_mercado >= T) & v.cuota.notna() & (v.cuota < techo)
              & (v.cuota >= piso) & (v.ajustada.fillna(0) >= modelo_min))
    sin_precio = ~v.mercado.isin(CON_PRECIO) & v.metida
    e = v[precio | sin_precio].copy()
    e['orden'] = np.where(e.mercado.isin(CON_PRECIO), e.p_mercado, e.ajustada)
    return e


def tarjeta(e):
    """Máximo 2 por partido y una sola de resultado, las más probables."""
    e = e.sort_values('orden', ascending=False)
    filas = []
    for (dia, partido), g in e.groupby(['dia', 'partido'], sort=False):
        res, n = False, 0
        for _, r in g.iterrows():
            if r.mercado in RESULTADO:
                if res:
                    continue
                res = True
            filas.append(r)
            n += 1
            if n == 2:
                break
    return pd.DataFrame(filas)


def resumen(s):
    return {'n': int(len(s)), 'verdes': float(s.acierto.mean()), 'rojos': int((1 - s.acierto).sum()),
            'cuota': float(s.cuota.mean()), 'rinde': float((s.acierto * s.cuota).mean() - 1),
            'partidos': int(s.partido.nunique())}


def boot(a, b, n=3000):
    A = a.groupby('fecha').acierto.agg(['sum', 'size'])
    B = b.groupby('fecha').acierto.agg(['sum', 'size'])
    dd = sorted(set(A.index) | set(B.index))
    A, B = A.reindex(dd, fill_value=0).values, B.reindex(dd, fill_value=0).values
    d = []
    for _ in range(n):
        q = rng.integers(0, len(dd), len(dd))
        x, y = A[q].sum(axis=0), B[q].sum(axis=0)
        d.append(x[0] / x[1] - y[0] / y[1])
    return 100 * np.mean(d), 100 * np.percentile(d, 5)


def elige(M, n0):
    """En MIRAR: la combinación (cuota mínima, modelo mínimo, umbral de la
    casa) con más verdes que mantenga el volumen de hoy (±5 %) y la cuota
    media ≥ 1,20 (lo acordado con el usuario: no bajar a cuotas de 1,07)."""
    filas = []
    for piso in (1.10, 1.12, 1.15, 1.18, 1.20):
        for mmin in (0.0, 0.65, 0.70):
            for T in np.round(np.arange(0.66, 0.86, 0.01), 2):
                t = tarjeta(elegibles(M, T, piso=piso, modelo_min=mmin))
                if len(t):
                    filas.append((piso, mmin, T, len(t), t.acierto.mean(), t.cuota.mean()))
    r = pd.DataFrame(filas, columns=['piso', 'modelo_min', 'T', 'n', 'verdes', 'cuota'])
    ok = r[r.n.between(0.95 * n0, 1.05 * n0) & (r.cuota >= 1.20)]
    return ok.sort_values(['verdes', 'n'], ascending=False).iloc[0]


def main():
    v = cargar()
    dias = np.sort(v.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    hoy = v[v.metida]
    n0 = int((hoy.fecha < corte).sum())
    print('simulación: %d partidos (%s a %s) · mirar hasta %s · juzgar desde %s'
          % (v.partido.nunique(), str(dias[0])[:10], str(dias[-1])[:10],
             str(dias[dias < corte][-1])[:10], str(corte)[:10]))
    r = elige(v[v.fecha < corte], n0)
    piso, mmin, T = float(r['piso']), float(r['modelo_min']), float(r['T'])
    print('regla elegida AL MIRAR: casa sin margen ≥ %.0f %%, modelo ≥ %.0f %%, cuota %.2f-1,35'
          % (100 * T, 100 * mmin, piso))
    nueva = tarjeta(elegibles(v, T, piso=piso, modelo_min=mmin))
    out = {'T': T, 'modelo_min': mmin, 'piso': piso, 'corte': str(corte)[:10]}
    print()
    print('            ANTES (regla de hoy)                        DESPUÉS (casa + modelo)')
    for tramo, m_h, m_n in (('mirar', hoy.fecha < corte, nueva.fecha < corte),
                            ('juzgar', hoy.fecha >= corte, nueva.fecha >= corte),
                            ('todo', hoy.fecha.notna(), nueva.fecha.notna())):
        a, b = resumen(hoy[m_h]), resumen(nueva[m_n])
        print('  %-6s  %5.1f %% · %4d (%3d rojos) · cuota %.3f · %+.1f %%   '
              '%5.1f %% · %4d (%3d rojos) · cuota %.3f · %+.1f %%'
              % (tramo, 100 * a['verdes'], a['n'], a['rojos'], a['cuota'], 100 * a['rinde'],
                 100 * b['verdes'], b['n'], b['rojos'], b['cuota'], 100 * b['rinde']))
        out[tramo] = {'antes': a, 'despues': b}
    med, p5 = boot(nueva[nueva.fecha >= corte], hoy[hoy.fecha >= corte])
    print('  juzgar: después − antes %+.2f pts de verdes (bootstrap por día, p5 %+.2f)' % (med, p5))
    out['boot_juzgar'] = [med, p5]
    print()
    print('  DÍA POR DÍA (los más recientes):  antes  →  después')
    out['dias'] = {}
    for d in dias[-10:]:
        a, b = hoy[hoy.fecha == d], nueva[nueva.fecha == d]
        if len(a) + len(b) == 0:
            continue
        print('   %s  %3d/%3d verdes (%5.1f %%)  →  %3d/%3d (%5.1f %%)%s'
              % (str(d)[:10], a.acierto.sum(), len(a), 100 * a.acierto.mean() if len(a) else 0,
                 b.acierto.sum(), len(b), 100 * b.acierto.mean() if len(b) else 0,
                 '   ← juzgar' if d >= corte else ''))
        out['dias'][str(d)[:10]] = [int(a.acierto.sum()), len(a), int(b.acierto.sum()), len(b)]
    print()
    print('  por mercado (todo el periodo): verdes antes → después (n)')
    for mer in sorted(set(hoy.mercado) | set(nueva.mercado)):
        a, b = hoy[hoy.mercado == mer], nueva[nueva.mercado == mer]
        print('     %-18s %5.1f %% (%3d) → %5.1f %% (%3d)'
              % (mer, 100 * a.acierto.mean() if len(a) else float('nan'), len(a),
                 100 * b.acierto.mean() if len(b) else float('nan'), len(b)))
    json.dump(out, open('_v335_meter_casa.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
