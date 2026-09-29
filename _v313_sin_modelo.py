# -*- coding: utf-8 -*-
"""
v313 — ¿SE PUEDE DECIR «METER» EN LOS PARTIDOS QUE EL MODELO NO CUBRE?

El usuario, con la Capa 1 delante (Belgium U21, USA U19, J.League Cup,
Cymru Premier…): «esos juegos no aparecen en las apuestas del día ni en lo
que me mandas a Telegram. Quiero que esté absolutamente todo, pero haz las
simulaciones: el porcentaje de acierto tiene que ser igual de alto o mayor
que el que ya tenemos. Eso no tiene que bajar».

En esos partidos no hay modelo propio (sub-21, sub-19, copas de Japón,
ligas galesas…), pero sí hay DOS precios: el de Pinnacle —la casa que menos
margen cobra y la referencia de todo el proyecto— y el de las casas
mexicanas del usuario. La pregunta es si la probabilidad justa de Pinnacle,
con la MISMA regla de «meter» que ya funciona en fútbol (70-80 %, cuota
< 1,35), acierta al menos lo mismo.

DOS MEDICIONES, LAS DOS SIN MIRAR EL RESULTADO AL ELEGIR
1. Réplica real (20-28 sep): cada captura Pinnacle del radar
   (`radar_capturas.csv`, en git con la hora de cada commit) y cada foto del
   tablero de casas mexicanas (`cuotas_mx.json`, en git), la ÚLTIMA anterior
   al inicio. 1X2 (local/visitante) y doble oportunidad. Liquidado con
   FotMob. Se separan los partidos que el modelo ya cubre (ahí manda el
   modelo; no se toca) de los que no.
2. Muestra grande: `pick_ledger_total.csv`, 1X2 de fútbol con cuota de
   cierre de Pinnacle y de una casa europea (2018-2026).

Uso: python _v313_sin_modelo.py   (escribe _v313_sin_modelo.json)

RESULTADO (29-sep-2026)
Primer intento: la misma franja del modelo (70-80 %). Con probabilidad
proporcional pareció valer 75-80 % local (85,7 % / 86,7 %), pero con el
devigado del proyecto («potencia», el de la Capa 1) se caía a 69,2 % en
elección: era ruido de muestra chica. Pinnacle está calibrada —al 75 %
acierta ~75 %—, así que para no bajar el 76-81 % del modelo hay que pedir
más. Lo que se sostiene en todo:

    80-90 %, cuota 1,10-1,35, local o local/empate
        réplica: elección 94,0 % (50) · prueba 88,2 % (17) · hoy 5/5
        muestra grande (gana el local): 82,8 % (795) · 84,7 % (347)
        sumado al «meter» del modelo: 74,8 → 76,5 % · 80,8 → 81,7 %
"""
from __future__ import annotations

import json
import os
import subprocess
from io import StringIO

import numpy as np
import pandas as pd

DESDE = '2026-09-19'
SALIDA = '_v313_sin_modelo.json'
CACHE = os.environ.get('V313_CACHE', '_v313_sin_modelo.csv')
# Lo elegido: se eligió en los días de ELECCIÓN y se juzgó en los de PRUEBA,
# que no se usaron para elegir. Probabilidad con el devigado del proyecto
# («potencia», el mismo de la Capa 1).
P_MIN, P_MAX, CUOTA_MIN, CUOTA_MAX = 0.80, 0.90, 1.10, 1.35
LADOS = ('home', 'homeOrDraw')
# los mismos tramos de la v312: elección hasta el 26, prueba 27-28
CORTE = '2026-09-27'
VARIANTES = {
    'misma regla que el modelo (70-80 %, los cuatro)': (0.70, 0.80, None),
    '70-80 %, local / local o empate': (0.70, 0.80, ('home', 'homeOrDraw')),
    '75-85 %, local / local o empate': (0.75, 0.85, ('home', 'homeOrDraw')),
    '78-90 %, los cuatro': (0.78, 0.90, None),
    '80-90 %, los cuatro': (0.80, 0.90, None),
    '80-90 %, sólo 1X2': (0.80, 0.90, ('home', 'away')),
    '80-90 %, local / local o empate (ELEGIDA)': (0.80, 0.90, ('home', 'homeOrDraw')),
}


def _commits(ruta):
    return [(h, float(ts)) for h, ts in (l.split() for l in subprocess.check_output(
        ['git', 'log', '--reverse', '--format=%h %ct', '--since=' + DESDE,
         '--', ruta], text=True).splitlines() if l.strip())]


def _show(h, ruta):
    return subprocess.check_output(['git', 'show', '%s:%s' % (h, ruta)])


def capturas_pinnacle() -> dict:
    """(home, away, inicio) -> última captura de Pinnacle anterior al inicio."""
    ult = {}
    for h, ts in _commits('radar_capturas.csv'):
        try:
            d = pd.read_csv(StringIO(_show(h, 'radar_capturas.csv').decode('utf-8')))
        except Exception:
            continue
        d = d[(d['deporte'] == 'futbol')]
        for r in d.itertuples(index=False):
            try:
                ini = float(r.inicio)
            except (TypeError, ValueError):
                continue
            if ini <= ts:
                continue
            ult[(r.home, r.away, str(int(ini)))] = (r.liga, r.pin_home,
                                                   r.pin_draw, r.pin_away)
    return ult


CASAS = ('Calientemx', '1xBet', 'Winpot', 'Novibet', 'Sportium.mx')


def fotos_tablero() -> dict:
    """(home, away, inicio) -> mejor cuota de las casas del usuario, última
    foto anterior al inicio: 1X2 y doble oportunidad."""
    ult = {}
    for h, ts in _commits('cuotas_mx.json'):
        try:
            d = json.loads(_show(h, 'cuotas_mx.json'))
        except Exception:
            continue
        for v in (d.get('partidos') or {}).values():
            if v.get('deporte') != 'futbol':
                continue
            try:
                ini = float(v.get('inicio'))
            except (TypeError, ValueError):
                continue
            if ini <= ts:
                continue
            mejor = {}
            for casa, m in (v.get('casas') or {}).items():
                if casa not in CASAS:
                    continue
                for merc, lados in (('HOME_DRAW_AWAY', ('home', 'away')),
                                    ('DOUBLE_CHANCE', ('homeOrDraw', 'awayOrDraw'))):
                    x = m.get(merc) or {}
                    for lado in lados:
                        try:
                            q = float(x.get(lado))
                        except (TypeError, ValueError):
                            continue
                        if q > 1 and q > mejor.get(lado, (0,))[0]:
                            mejor[lado] = (q, casa)
            if mejor:
                ult[(v['home'], v['away'], str(int(ini)))] = mejor
    return ult


def _justas(h, d, a) -> dict:
    import mercado_sin_modelo as msm
    return msm.justas({'home': h, 'draw': d, 'away': a})


def construir() -> pd.DataFrame:
    import horario as hz
    import partidos_jugados as pj
    pin = capturas_pinnacle()
    tab = fotos_tablero()
    print('capturas Pinnacle:', len(pin), '· fotos del tablero:', len(tab), flush=True)
    filas = []
    for k, (liga, ph, pd_, pa) in pin.items():
        q = tab.get(k)
        if not q:
            continue
        try:
            inv = np.array([1 / float(ph), 1 / float(pd_), 1 / float(pa)])
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if not np.isfinite(inv).all():
            continue
        # el mismo devigado que la Capa 1 y la aplicación (`potencia`, el
        # medido mejor en `cuotas_multi.devig`)
        f = _justas(float(ph), float(pd_), float(pa))
        for lado, (cuota, casa) in q.items():
            if lado not in f:
                continue
            filas.append({'home': k[0], 'away': k[1], 'inicio': k[2],
                          'liga': liga, 'lado': lado, 'p': f[lado],
                          'cuota': cuota, 'casa': casa,
                          'pin_h': ph, 'pin_d': pd_, 'pin_a': pa})
    d = pd.DataFrame(filas)
    # marcador
    d['dia'] = [hz.fecha(x) for x in d['inicio']]
    res = {}
    for dia in sorted(d['dia'].dropna().unique()):
        lista = pj.marcadores_fotmob(dia)
        for k in d[d['dia'] == dia][['home', 'away', 'inicio']].drop_duplicates().itertuples(index=False):
            m = pj._casar_fotmob({'partido': '%s vs %s' % (k.home, k.away),
                                  'inicio': k.inicio}, lista)
            if m:
                res[(k.home, k.away, k.inicio)] = (m['gh'], m['ga'])
        print(dia, len(lista), flush=True)
    gh, ga = [], []
    for r in d.itertuples(index=False):
        x = res.get((r.home, r.away, r.inicio))
        gh.append(None if x is None else x[0])
        ga.append(None if x is None else x[1])
    d['gh'], d['ga'] = gh, ga
    d.to_csv(CACHE, index=False)
    return d


def _acierto(r) -> int:
    if r.lado == 'home':
        return int(r.gh > r.ga)
    if r.lado == 'away':
        return int(r.ga > r.gh)
    if r.lado == 'homeOrDraw':
        return int(r.gh >= r.ga)
    return int(r.ga >= r.gh)


def cubiertos() -> set:
    """Los partidos que el modelo ya cubría (réplica v312)."""
    try:
        c = pd.read_csv('_v312_candidatas.csv', usecols=['dia', 'partido'])
    except Exception:
        return set()
    return set(zip(c['dia'], c['partido']))


def main():
    import cuotas_multi as cm
    d = pd.read_csv(CACHE, dtype={'inicio': str}) if os.path.exists(CACHE) \
        else construir()
    d = d.dropna(subset=['gh', 'ga'])
    d['y'] = [_acierto(r) for r in d.itertuples(index=False)]
    cub = cubiertos()
    por_dia = {}
    for dia, partido in cub:
        por_dia.setdefault(dia, []).append(partido)

    import mercado_sin_modelo as msm

    def _es_cubierto(r):
        # el mismo criterio que usa la aplicación para no duplicar
        par = '%s vs %s' % (r.home, r.away)
        return any(msm.mismo_partido(par, x) for x in por_dia.get(r.dia, []))
    d['cubierto'] = [_es_cubierto(r) for r in d.itertuples(index=False)]
    def elegir(lo, hi, lados):
        x = d[(d.p >= lo) & (d.p <= hi) & (d.cuota < CUOTA_MAX)
              & (d.cuota >= CUOTA_MIN)]
        if lados:
            x = x[x.lado.isin(lados)]
        # una por partido: la de mayor probabilidad (como la tarjeta)
        return x.sort_values('p', ascending=False).drop_duplicates(
            ['home', 'away', 'inicio']).copy()
    sel = elegir(P_MIN, P_MAX, LADOS)
    out = {'regla': 'prob Pinnacle %.2f-%.2f, cuota %.2f-%.2f, %s, una por partido'
           % (P_MIN, P_MAX, CUOTA_MIN, CUOTA_MAX, '/'.join(LADOS))}
    rng = np.random.default_rng(0)

    def resumen(x):
        if not len(x):
            return {'n': 0}
        bs = [rng.choice(x['y'].values, len(x)).mean() for _ in range(2000)]
        return {'n': int(len(x)), 'acierto': round(float(x['y'].mean()), 4),
                'p5': round(float(np.percentile(bs, 5)), 4),
                'roi': round(float((x['y'] * x['cuota'] - 1).mean()), 4)}
    corte = CORTE
    out['replica'] = {
        'todo': resumen(sel),
        'sin_modelo': resumen(sel[~sel.cubierto]),
        'con_modelo': resumen(sel[sel.cubierto]),
        'eleccion_sin_modelo': resumen(sel[(~sel.cubierto) & (sel.dia < corte)]),
        'prueba_sin_modelo': resumen(sel[(~sel.cubierto) & (sel.dia >= corte)]),
        'por_mercado_sin_modelo': {k: resumen(v) for k, v in
                                   sel[~sel.cubierto].groupby('lado')},
        'por_dia_sin_modelo': {k: resumen(v) for k, v in
                               sel[~sel.cubierto].groupby('dia')},
        'corte': corte}
    # LO QUE IMPORTA: sumadas a las «meter» del modelo (v312, mismos tramos),
    # ¿sube o baja el acierto de todo lo que se dice «meter»?
    try:
        v312 = json.load(open('_v312_patrones.json', encoding='utf-8'))
        out['sumado_a_v312'] = {}
        sm = sel[~sel.cubierto]
        for tramo, x in (('eleccion', sm[sm.dia < corte]),
                         ('prueba', sm[sm.dia >= corte]),
                         ('hoy', sm[sm.dia == v312['hoy']['dia']])):
            a = v312[tramo]['ahora']
            n_, v_ = a['apuestas'] + len(x), a['verdes'] + int(x['y'].sum())
            out['sumado_a_v312'][tramo] = {
                'solo_modelo': '%d/%d = %.1f %%' % (a['verdes'], a['apuestas'],
                                                    100 * a['acierto']),
                'sin_modelo': '%d/%d' % (int(x['y'].sum()), len(x)),
                'juntos': '%d/%d = %.1f %%' % (v_, n_, 100 * v_ / n_)}
    except Exception as e:
        out['sumado_a_v312'] = {'error': str(e)}
    out['variantes'] = {}
    for nombre, (lo, hi, lados) in VARIANTES.items():
        x = elegir(lo, hi, lados)
        x = x[~x.cubierto]
        out['variantes'][nombre] = {
            'eleccion': resumen(x[x.dia < corte]),
            'prueba': resumen(x[x.dia >= corte])}
    # muestra grande
    L = pd.read_csv('pick_ledger_total.csv', low_memory=False)
    L = L[L.deporte == 'Fútbol'].dropna(subset=['pin_home', 'pin_draw', 'pin_away',
                                                 'resultado'])
    fair = pd.DataFrame([_justas(h, d_, a) for h, d_, a in zip(
        L.pin_home, L.pin_draw, L.pin_away)], index=L.index)
    fair = fair.rename(columns={'home': 'pin_home', 'away': 'pin_away'})
    res = L['resultado'].astype(int)          # 0 local · 1 empate · 2 visita
    # el ledger sólo trae 1X2: se mide «gana el local», que es lo elegido
    R = pd.DataFrame({'fecha': L.fecha, 'p': fair['pin_home'],
                      'cuota': L.cuota_home, 'y': (res == 0).astype(int)}).dropna()
    R = R[(R.p >= P_MIN) & (R.p <= P_MAX) & (R.cuota < CUOTA_MAX)
          & (R.cuota >= CUOTA_MIN)].sort_values('fecha')
    c = R['fecha'].iloc[int(len(R) * 0.7)]
    out['ledger'] = {'eleccion': resumen(R[R.fecha < c]),
                     'prueba': resumen(R[R.fecha >= c]), 'corte': str(c)}
    json.dump(out, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
