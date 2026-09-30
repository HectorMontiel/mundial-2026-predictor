# -*- coding: utf-8 -*-
"""
v316 — EL MODELO PROPIO SOBRE LA BASE DE FLASHSCORE: ¿CUÁNTOS PARTIDOS CUBRE
Y CÓMO ACIERTA?

Misma simulación que `_v315_modelo_competiciones.py` (partidos del tablero
fuera del motor de ligas, 19-28 sep, predicción hecha sólo con lo anterior,
mercado = media de casas sin margen), pero con la base de Flashscore
(`resultados_flashscore.py`), que usa los nombres exactos del tablero.

Lo que se quiere saber:
  1. COBERTURA: con FotMob, de cada 100 partidos fuera del motor sólo una
     parte tenía modelo (los demás: liga que FotMob no publica, reservas,
     sub-20, femenil). ¿Con Flashscore?
  2. ACIERTO: el modelo solo, contra el mercado, y las reglas de «meter»
     (resultado local / local o empate y más de 1,5, 80-90 %, cuota
     1,10-1,35) en los partidos que ahora sí tienen modelo.

RESULTADO (2026-09-29, base con la temporada entera)
Cobertura 84,7 % (1.914 de 2.259). El modelo solo pierde contra el
mercado (Brier de resultado 0,2074 contra 0,1913) y la MEZCLA no pasa la
prueba en ningún mercado ni tramo (goles w=0,25: p5 −0,00011 y −0,00133),
así que la probabilidad sigue saliendo del mercado y el modelo propio va de
referencia. La regla de meter en estos partidos: 85,7 % en elección (843) y
87,1 % en prueba (255).

Uso: python _v316_modelo_flashscore.py   (escribe el .json)
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

CORTE = '2026-09-27'


def main():
    import horario as hz
    import mercado_sin_modelo as msm
    import modelo_competiciones as mc
    import resultados_flashscore as rf
    import _v313_sin_modelo as v313
    import _v314_ligas_chicas as v314
    import _v315_modelo_competiciones as v315
    b = rf.cargar()
    x = pd.DataFrame({
        'match_id': b['match_id'], 'ini': b['ini'], 'liga_id': b['ruta'],
        'home_id': [rf.clave_equipo(r, h) for r, h in zip(b['ruta'], b['home'])],
        'away_id': [rf.clave_equipo(r, a) for r, a in zip(b['ruta'], b['away'])],
        'home': b['home'], 'away': b['away'], 'gh': b['gh'], 'ga': b['ga']})
    m, pred = mc.entrenar(x, registrar_desde=pd.Timestamp('2026-09-15'))
    P = pd.DataFrame(pred, columns=['match_id', 'lh', 'la', 'nh', 'na'])
    P = P.merge(x[['match_id', 'ini', 'home', 'away', 'gh', 'ga', 'liga_id']],
                on='match_id')
    pr = v314.precios()
    cub = {}
    for dia, par in v313.cubiertos():
        cub.setdefault(dia, []).append(par)
    filas, n_fuera, n_con = [], 0, 0
    for k, v in pr.items():
        ini = pd.Timestamp(v['inicio'], unit='s')
        dia = hz.fecha(str(v['inicio']))
        par = '%s vs %s' % (v['home'], v['away'])
        if dia < '2026-09-19' or any(msm.mismo_partido(par, z) for z in cub.get(dia, [])):
            continue
        n_fuera += 1
        c = P[(P['home'] == v['home']) & (P['away'] == v['away'])
              & ((P['ini'] - ini).abs() <= pd.Timedelta(hours=3))]
        if c.empty:
            continue
        r = c.iloc[0]
        if min(r['nh'], r['na']) < mc.MIN_PARTIDOS:
            continue
        n_con += 1
        pm, q = v314.mercado(v)
        pmod = mc.probabilidades(r['lh'], r['la'])
        pmod['1X'], pmod['X2'] = pmod['homeOrDraw'], pmod['awayOrDraw']
        for sel in list(v314.SELS):
            if sel not in pmod:
                continue
            filas.append({'dia': dia, 'partido': par, 'liga': v.get('liga'),
                          'sel': sel, 'fam': v315._fam(sel),
                          'y': int(v315._res(sel, r['gh'], r['ga'])),
                          'p_mod': pmod[sel], 'p_mer': pm.get(sel), 'q': q.get(sel)})
    L = pd.DataFrame(filas)
    out = {'base_partidos': int(len(b)), 'base_competiciones': int(b['ruta'].nunique()),
           'partidos_fuera_del_motor': n_fuera, 'con_modelo_flashscore': n_con,
           'cobertura': round(n_con / max(n_fuera, 1), 3)}
    rng = np.random.default_rng(0)
    out['brier'] = {}
    for fam, z in L.dropna(subset=['p_mer']).groupby('fam'):
        out['brier'][fam] = {'n': int(len(z)),
                             'mercado': round(float(((z.p_mer - z.y) ** 2).mean()), 5),
                             'modelo': round(float(((z.p_mod - z.y) ** 2).mean()), 5),
                             'mezcla_50': round(float(((.5 * z.p_mer + .5 * z.p_mod - z.y) ** 2).mean()), 5)}

    # la prueba formal de la mezcla: por tramo, bootstrap por partido
    out['mezcla'] = {}
    for fam, z in L.dropna(subset=['p_mer']).groupby('fam'):
        r_ = {}
        for tramo, y in (('eleccion', z[z.dia < CORTE]), ('prueba', z[z.dia >= CORTE])):
            fila = {'n': int(len(y))}
            for w in (0.25, 0.5):
                d = (y.p_mer - y.y) ** 2 - (w * y.p_mod + (1 - w) * y.p_mer - y.y) ** 2
                g = d.groupby(y.partido).sum()
                nn = y.groupby('partido').size()
                ms = g.index.values
                bs = [g[s].sum() / nn[s].sum() for s in (rng.choice(ms, len(ms)) for _ in range(1500))]
                fila['w=%s' % w] = {'mejora': round(float(d.mean()), 5),
                                    'p5': round(float(np.percentile(bs, 5)), 5)}
            r_[tramo] = fila
        out['mezcla'][fam] = r_
    L['p_mix'] = 0.5 * L.p_mod + 0.5 * L.p_mer

    def regla_g(y, col):
        z = y[(y.sel == 'mas_1.5') & (y[col] >= .8) & (y[col] <= .9)
              & (y.q >= 1.10) & (y.q < 1.35)]
        return z.drop_duplicates('partido')
    for col in ('p_mer', 'p_mix'):
        for tramo, y in (('eleccion', L[L.dia < CORTE]), ('prueba', L[L.dia >= CORTE])):
            z = regla_g(y, col)
            out['mas15_%s_%s' % (col, tramo)] = {
                'n': int(len(z)), 'acierto': round(float(z.y.mean()), 4) if len(z) else None}

    def regla(y):
        z = y[y.sel.isin(['home', '1X', 'mas_1.5']) & (y.p_mer >= .8) & (y.p_mer <= .9)
              & (y.q >= 1.10) & (y.q < 1.35)]
        z = z.assign(f2=np.where(z.sel == 'mas_1.5', 'g', 'r'))
        return z.sort_values('p_mer', ascending=False).drop_duplicates(['partido', 'f2'])
    for tramo, y in (('eleccion', L[L.dia < CORTE]), ('prueba', L[L.dia >= CORTE])):
        z = regla(y)
        bs = [rng.choice(z.y.values, len(z)).mean() for _ in range(1500)] if len(z) else [0]
        out['meter_' + tramo] = {'n': int(len(z)), 'acierto': round(float(z.y.mean()), 4) if len(z) else None,
                                 'p5': round(float(np.percentile(bs, 5)), 4)}
    json.dump(out, open('_v316_modelo_flashscore.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
