# -*- coding: utf-8 -*-
"""
v362 — «🎲 APUESTAS ARRIESGADAS»: CÓRNERS Y TIROS EN COMBINADA.

El usuario, con un boleto de Draftea ganado (córners de equipo +4,5/+5,5 y
total +9,5 en la Liga MX, ×78): «una sección nueva de apuestas arriesgadas,
con mercados como córners y tiros, que sí tengan una probabilidad
significativa de que se hagan». Y la metodología de córners de su amigo:
los equipos de córners altos (a favor y en contra), el que domina en córners
contra un rival que concede muchos, y el tipo de partido (tabla, local).

v362b — Y CON LA ESCALERA DE PLAYDOIT, A CUOTA DE RIESGO. El usuario: «las
cuotas del boleto no son bajas, por algo son arriesgadas (hasta 1,7); tiene
que ser de acuerdo a la casa que atacamos: si abre desde 4,5 córners a un
equipo, desde ahí se avanza; y tiros más de 2,5, 3,5 o N; para todos los
mercados». Medido con las escaleras de Playdoit desde el 24-ago
(`_v362b_escaleras.py`: 12.820 líneas de 643 partidos, el método entrenado
sólo con lo anterior; quitadas las líneas que la casa y el método ven a más
de 20 pts, que son otro mercado con la misma clave). A cuota 1,45-3 el
método ACIERTA LO QUE PROMETE y le saca 3-5 pts a la casa:

    el método ve   la casa ve   acierta de verdad
      50-55 %        52 %            56 %
      55-60 %        54 %            58 %
      60-65 %        57 %            61 %
      65-70 %        58 %            65 %

pero la ganancia no está demostrada (la mejor regla +5/+10 %, p5 < 0). La
combinada del día con las mejores patas: de 2 sale 35-43 % (momio ~3,5), de 3
14-25 % (~6,6), de 4 7-15 % (~12), de 5 0-10 % (~22-26). Eso es «arriesgada»:
un boleto de ×78 sale ~1 de cada 20. Por eso cada pata y cada boleto llevan su
probabilidad DE VERDAD.

LO DE ANTES (`_v362_corners.py`, 17.742 equipo-partido de juicio en dos mitades):

    córners de equipo «más de 3.5»                 mitad A   mitad B
      todos                                          65 %      66 %
      regla del amigo (genera mucho y el rival
        concede mucho)                               74 %      78 %
      … y de local                                   78 %      82 %
      Método Contexto ≥ 80 %                         83 %      84 %
    córners de equipo «más de 4.5», método ≥ 75 %    77 %      79 %
    córners totales «más de 7.5», método ≥ 75 %      77 %      79 %

La regla del amigo funciona (+10 pts) y el Método Contexto —que ya lleva los
córners a favor y en contra, la tabla y la presión— la supera; por eso las
patas salen del método. La COMBINADA del día con las patas más probables (una
por partido, ≥ 75 %): de 3, sale entera 59 % (momio justo ~1,75); de 6, 37-39 %
(~3,1). Las patas sueltas aciertan 83-84 %.

Las patas usan las cuotas de Playdoit (`mercado_implicito`, la escalera de
córners y tiros por equipo y total) y la probabilidad del método
(`tiros_equipo`). Nunca lanza.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional

logger = logging.getLogger('arriesgadas')

META_PATA = 0.55          # v362b — probabilidad mínima del método
CUOTA_MIN_PATA = 1.45     # la cuota de riesgo, como el boleto de Draftea
CUOTA_MAX_PATA = 3.00
BOLETOS = (2, 3, 4, 6)
PATAS_SEGURA = 3
PATAS_ARRIESGADA = 6
DIF_CASA_MAX = 0.20      # más lejos que esto del método: es otro mercado
# (objetivo del método, línea de equipo local, visita, total, rótulo)
MERCADOS = (('corners', None, None, 'corners', 'Córners'),
            ('tiros', 'remates_home', 'remates_away', 'remates', 'Tiros'),
            ('a_puerta', 'remates_on_home', 'remates_on_away', 'remates_on', 'Tiros a puerta'),
            ('goles', 'goles_home', 'goles_away', 'goles', 'Goles'))
# v363 — FUERA LAS TARJETAS Y LOS CÓRNERS DE EQUIPO. Contra los cierres de
# Playdoit (`_v363_simulaciones.py`, 642 partidos desde el 24-ago), en la zona
# de riesgo prometían más de lo que aciertan: tarjetas 61 % → 43-47 %
# (−26/−30 por cada 100), córners de equipo 60 % → 53 % (−12). Lo demás
# acierta lo prometido (60-62 %). La combinada del día con lo que queda sale
# entera: de 2 ~40 %, de 3 ~26 %, de 4 ~22 %, de 6 ~9 % (pocos días: 13-17).
MEDIDO = {2: 0.40, 3: 0.26, 4: 0.22, 6: 0.09}
FICHERO = 'arriesgadas_seguimiento.csv'


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _lados(partido: str):
    par = str(partido or '')
    return [x.strip() for x in par.split(' vs ', 1)] if ' vs ' in par else [None, None]


def _mejor_linea(lineas: Dict, mu: float, k: float) -> Optional[tuple]:
    """(línea, prob, cuota) de la escalera de la casa —desde donde la abra—:
    de las líneas «más de» a cuota de riesgo (1,45-3) que el método ve al 55 %
    o más, la que más rinde (prob × cuota; el método está calibrado ahí)."""
    import mercado_implicito as mi
    import tiros_equipo as te
    mejor = None
    for clave, ent in (lineas or {}).items():
        L = _f(clave)
        c = mi.cuota_de(ent, 'mas')
        if (L is None or c is None or L % 1 != 0.5
                or not CUOTA_MIN_PATA <= c <= CUOTA_MAX_PATA):
            continue
        p = te.prob_mas(mu, L, k)
        # la línea tiene que ser la del mercado que creemos: medido el 11-oct,
        # la clave «corners» traía «más de 1,5» a 2,33 (otro mercado de la
        # casa) con el método al 99,8 %
        hp = mi.prob_de(ent)
        if hp is None or abs(p - hp) > DIF_CASA_MAX:
            continue
        if p >= META_PATA and (mejor is None or p * c > mejor[1] * mejor[2]):
            mejor = (L, p, c)
    return mejor


def patas_del_partido(pick: Dict) -> List[Dict]:
    """Las patas de córners y tiros de un partido de fútbol."""
    out: List[Dict] = []
    try:
        import mercado_implicito as mi
        import tiros_equipo as te
        h, a = _lados(pick.get('partido'))
        if not h:
            return out
        dp = te.del_partido(pick) or {}
        lados, kk = dp.get('lados') or {}, dp.get('k') or {}
        tab = mi.del_partido(h, a) or {}
        if not lados or not tab:
            return out
        for obj, kh, ka, kt, rot in MERCADOS:
            lh = (lados.get('local') or {}).get(obj)
            la = (lados.get('visitante') or {}).get(obj)
            if lh is None or la is None:
                continue
            k = float(kk.get(obj) or (12.0 if obj == 'corners' else 500.0))
            for mu, clave, eq in ((lh, kh, h), (la, ka, a)):
                if not clave:
                    continue
                m = _mejor_linea(tab.get(clave), float(mu), k)
                if m:
                    out.append({'obj': obj, 'tipo': 'equipo', 'linea': m[0], 'prob': m[1],
                                'cuota': m[2], 'apuesta': '%s %s: Más de %g' % (rot, eq, m[0])})
            tot = float(lh) + float(la)
            k_t = ((tot ** 2) / max((float(lh) ** 2 + float(la) ** 2) / k, 1e-9)
                   if k < 400 else 1e6)
            m = _mejor_linea(tab.get(kt), tot, k_t)
            if m:
                out.append({'obj': obj, 'tipo': 'total', 'linea': m[0], 'prob': m[1],
                            'cuota': m[2], 'apuesta': '%s: Más de %g' % (rot, m[0])})
        for x in out:
            x.update({'icono': '🎲', 'partido': pick.get('partido'), 'inicio': pick.get('inicio'),
                      'fecha': pick.get('fecha'), 'clave_liga': pick.get('clave_liga'),
                      'liga': pick.get('liga'), 'deporte': 'Fútbol', 'casa': 'Playdoit',
                      'porque': 'Método Contexto: %.0f %% · cuota de Playdoit' % (100 * x['prob'])})
    except Exception as e:
        logger.debug('[arriesgadas] %s: %s', pick.get('partido'), e)
    return out


_MEMO: Dict = {}


def del_dia(pronosticos: List[Dict], ahora: Optional[float] = None) -> List[Dict]:
    """Todas las patas de los partidos de fútbol que aún no empiezan, por hora.
    v363 — recordadas 5 minutos (cada pasada de la pantalla las pedía: ~1,7 s)."""
    import os
    import time
    try:
        import horario as hz
    except Exception:
        return []
    if ahora is None:
        mt = tuple(os.path.getmtime(f) if os.path.exists(f) else 0
                   for f in ('tiros_dia.json', 'mercado_dia.json'))
        k = (id(pronosticos), len(pronosticos or []), mt, int(time.time() // 300))
        if _MEMO.get('k') == k:
            return [dict(x) for x in _MEMO['v']]
        v = del_dia(pronosticos, time.time())
        _MEMO.update(k=k, v=v)
        return [dict(x) for x in v]
    ahora = float(ahora)
    out = []
    for p in pronosticos or []:
        if str(p.get('deporte') or 'Fútbol') != 'Fútbol' or p.get('jugado'):
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is None or ini.timestamp() <= ahora:
            continue
        out += patas_del_partido(p)
    out.sort(key=lambda x: (str(x.get('inicio') or ''), -x['prob']))
    return out


def boleto(patas: List[Dict], n: int) -> Optional[Dict]:
    """Las `n` patas más probables, una por partido. None si no hay `n`."""
    vistas, elegidas = set(), []
    for x in sorted(patas or [], key=lambda x: -x['prob']):
        if x['partido'] in vistas:
            continue
        vistas.add(x['partido'])
        elegidas.append(x)
        if len(elegidas) == n:
            break
    if len(elegidas) < n:
        return None
    return {'patas': sorted(elegidas, key=lambda x: str(x.get('inicio') or '')),
            'prob': math.prod(x['prob'] for x in elegidas),
            'momio': math.prod(x['cuota'] for x in elegidas),
            'medido': MEDIDO.get(n)}


# ---------------------------------------------------------------------------
# seguimiento: lo que se dijo y lo que pasó (córners/tiros de FotMob)
# ---------------------------------------------------------------------------
CAMPOS = ['dia', 'partido', 'inicio', 'apuesta', 'obj', 'tipo', 'lado', 'linea', 'prob',
          'cuota', 'real', 'cumple']
_STAT = {'corners': ('corners_home', 'corners_away'),
         'tiros': ('remates_home', 'remates_away'),
         'a_puerta': ('remates_on_home', 'remates_on_away'),
         'tarjetas': ('tarjetas_home', 'tarjetas_away')}


def registrar(pronosticos: List[Dict], ruta: str = FICHERO) -> int:
    try:
        import pandas as pd
        import analisis_seguimiento as an
        filas = []
        for x in del_dia(pronosticos):
            h, a = _lados(x['partido'])
            lado = ('total' if x['tipo'] == 'total' else
                    'local' if (' %s:' % h) in x['apuesta'] else 'visita')
            filas.append({'dia': an._dia(x), 'partido': x['partido'], 'inicio': x['inicio'],
                          'apuesta': x['apuesta'], 'obj': x['obj'], 'tipo': x['tipo'],
                          'lado': lado, 'linea': x['linea'], 'prob': round(x['prob'], 4),
                          'cuota': x['cuota'], 'real': None, 'cumple': None})
        if not filas:
            return 0
        try:
            d = pd.read_csv(ruta)
        except Exception:
            d = pd.DataFrame(columns=CAMPOS)
        n = pd.DataFrame(filas)
        clave = lambda z: z.dia.astype(str) + '|' + z.partido.astype(str) + '|' + z.obj.astype(str) \
            + '|' + z.lado.astype(str)
        if len(d):
            d = d[~(clave(d).isin(set(clave(n))) & d.real.isna())]
        pd.concat([d, n], ignore_index=True)[CAMPOS].to_csv(ruta, index=False)
        return len(n)
    except Exception as e:
        logger.warning('[arriesgadas] no se pudo registrar: %s', e)
        return 0


def liquidar(ruta: str = FICHERO, maximo: int = 80) -> int:
    try:
        import pandas as pd
        import analisis_seguimiento as an
        import partidos_jugados as pj
        d = pd.read_csv(ruta)
        pend = d[d.real.isna()]
        if pend.empty:
            return 0
        jug = an._jugados()
        fichas, listas, pedidas, n = {}, {}, 0, 0
        for i, r in pend.iterrows():
            p = jug.get((str(r.dia), str(r.partido)))
            if not p or p.get('goles_home') is None:
                continue
            if str(r.obj) == 'goles':
                gh, ga = float(p['goles_home']), float(p['goles_away'])
                real = gh + ga if r.lado == 'total' else gh if r.lado == 'local' else ga
                d.loc[i, 'real'] = real
                d.loc[i, 'cumple'] = int(real > float(r.linea))
                n += 1
                continue
            k = str(r.partido) + '|' + str(r.dia)
            if k not in fichas:
                st = p.get('stats_partido')
                if not st and pedidas < maximo:
                    pedidas += 1
                    mid = p.get('fotmob_id')
                    if not mid:
                        if str(r.dia) not in listas:
                            listas[str(r.dia)] = pj.marcadores_fotmob(str(r.dia))
                        f = pj._casar_fotmob(p, listas[str(r.dia)])
                        mid = f.get('id') if f else None
                    st = pj._stats_de_fotmob(mid) if mid else None
                fichas[k] = st
            st = fichas.get(k)
            ch, ca = _STAT.get(str(r.obj), (None, None))
            if not st or st.get(ch) is None or st.get(ca) is None:
                continue
            real = (float(st[ch]) + float(st[ca]) if r.lado == 'total' else
                    float(st[ch]) if r.lado == 'local' else float(st[ca]))
            d.loc[i, 'real'] = real
            d.loc[i, 'cumple'] = int(real > float(r.linea))
            n += 1
        d[CAMPOS].to_csv(ruta, index=False)
        return n
    except Exception as e:
        logger.warning('[arriesgadas] no se pudo liquidar: %s', e)
        return 0


def resumen(ruta: str = FICHERO, dias: int = 14) -> Optional[Dict]:
    """Cuántas patas se cumplieron en los últimos días (lo apuntado)."""
    try:
        import datetime as _dt
        import pandas as pd
        d = pd.read_csv(ruta)
        d = d[d.cumple.notna()]
        desde = (_dt.date.today() - _dt.timedelta(days=dias)).isoformat()
        d = d[d.dia.astype(str) >= desde]
        if d.empty:
            return None
        return {'n': int(len(d)), 'verdes': int(d.cumple.astype(float).sum()),
                'acierto': round(float(d.cumple.astype(float).mean()), 4)}
    except Exception:
        return None
