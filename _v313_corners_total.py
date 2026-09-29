# -*- coding: utf-8 -*-
"""
v313 — ¿EL TOTAL DE CÓRNERS DEBE SER LA MEDIA DE LA COMPETICIÓN O LA SUMA DE
LOS DOS EQUIPOS?

El usuario, con el documento de Telegram delante: «λ de córners = 9,1
repetido en casi todos los partidos de Liga de Naciones. Parece un valor por
defecto, no un cálculo por partido. Arregla eso».

No es un valor por defecto: `rendimiento_equipos.corners_equipo` pone a
propósito como total la MEDIA DE LA COMPETICIÓN, porque en ligas de clubes
la parte variable (sumar lo de los dos equipos) tenía correlación −0,0012
con el total real. Pero aquello se midió con clubes, y lo que el usuario ve
son selecciones. Se vuelve a medir, con selecciones incluidas.

CÓMO: las predicciones fuera de muestra de `_v310_conteos.csv` (código de
producción con el histórico recortado a lo anterior a cada partido: Liga MX,
UEFA clubes y selecciones, 2.425 partidos con córners observados). Para cada
partido, el total con peso w de la suma de equipos y 1−w de la media:
λ = w·(λ_local + λ_visita) + (1−w)·media, y el Brier en las líneas 7,5 a
12,5, a los dos lados. Elección el 70 % más antiguo, prueba el 30 % más
reciente; bootstrap por partido de la mejora.

RESULTADO
    w elegido en elección: 0,4 (Brier 0,21401 → 0,21255)
    elección: mejora +0,00149, p5 +0,00036
    prueba:   mejora +0,00057, p5 −0,00137   ← NO pasa
    franja 70-80 % en prueba: 73,9 % → 73,6 % de acierto (baja)

No pasa la puerta (p5 > 0 en los dos tramos). El total se queda como media
de la competición. Lo que sí se arregla es cómo se ENSEÑA: el documento de
Telegram dice ahora «λ total 9,1 = media de la competición», y la guía para
la IA explica por qué se repite.

Uso: python _v313_corners_total.py   (escribe _v313_corners_total.json)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

LINEAS = (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)


def _filas(x, w, rq):
    lam = w * x['suma'] + (1 - w) * x['lam_t']
    out = []
    for i, l, dd, r in zip(x.index, lam, x['disp_t'], x['real_t']):
        for L in LINEAS:
            p = rq.prob_mas_de(l, L, dd)
            y = int(r > L)
            out += [(i, p, y), (i, 1 - p, 1 - y)]
    return pd.DataFrame(out, columns=['m', 'p', 'y'])


def main():
    import rendimiento_equipos as rq
    d = pd.read_csv('_v310_conteos.csv', parse_dates=['fecha'])
    d = d[(d.mercado == 'corners') & (d.origen == 'observado')].dropna(
        subset=['lam_h', 'lam_a', 'lam_t']).sort_values('fecha').reset_index(drop=True)
    d['real_t'] = d.real_h + d.real_a
    d['suma'] = d.lam_h + d.lam_a
    corte = d.fecha.quantile(.7)
    E, P = d[d.fecha < corte], d[d.fecha >= corte]
    grid = {w: float(((f := _filas(E, w, rq)).p - f.y).pow(2).mean())
            for w in (0, .1, .2, .25, .3, .35, .4, .5, .75, 1)}
    w = min(grid, key=grid.get)
    rng = np.random.default_rng(0)
    out = {'partidos': int(len(d)), 'grid_eleccion': grid, 'w_elegido': w}
    for nombre, x in (('eleccion', E), ('prueba', P)):
        a, b = _filas(x, 0, rq), _filas(x, w, rq)
        ga = ((a.p - a.y) ** 2).groupby(a.m).sum()
        gb = ((b.p - b.y) ** 2).groupby(b.m).sum()
        ms = ga.index.values
        dif = np.array([(ga[s].sum() - gb[s].sum()) / (len(s) * len(LINEAS) * 2)
                        for s in (rng.choice(ms, len(ms)) for _ in range(2000))])
        sa, sb = a[(a.p >= .7) & (a.p <= .8)], b[(b.p >= .7) & (b.p <= .8)]
        out[nombre] = {'mejora_brier': round(float(dif.mean()), 5),
                       'p5': round(float(np.percentile(dif, 5)), 5),
                       'franja_70_80_media': round(float(sa.y.mean()), 3),
                       'franja_70_80_mezcla': round(float(sb.y.mean()), 3)}
    out['pasa'] = bool(out['eleccion']['p5'] > 0 and out['prueba']['p5'] > 0)
    json.dump(out, open('_v313_corners_total.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
