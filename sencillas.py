#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v371 — «🎯 SENCILLAS A 1,30+»: EL MÉTODO CASA 70/130.

El usuario (11-oct), con un boleto de 4 patas que salió 1 ✅ 3 ❌: «tener 3/4
malas es inaceptable; da mejores apuestas con cuota mínima de 1,30 sencillas;
evalúa todos los mercados; analiza cómo está la casa y sus índices para saber a
qué lado inclinarte; también quién gana».

LA REGLA (una línea): la pata entra si LA CASA LA VE AL 70 % O MÁS sin margen
Y AUN ASÍ PAGA 1,30 O MÁS. Es una línea donde la casa cobra poco margen —su
propia probabilidad y su precio no cuadran a su favor—, y ahí se queda corta.

LO MEDIDO (los finalizados, dos mitades por fecha, una pata por partido):
  · Escaleras de Playdoit (`_v371e_umbral.py`, 28-ago → 9-oct): 78,3 % de
    acierto (80,0 / 77,0) a cuota 1,31, +2,5 por cada $100 (+4,7 / +0,7);
    ~8 patas por día. Sin la condición del 70 % (la casa elige sin más):
    72,1 %. El armador viejo (elegía por el modelo): 69,8 % a 1,38.
  · Ganador (`_v371b_ganador.py`, 125.721 partidos 2010-2026): el favorito
    local con la casa ≥ 70 % y cuota ≥ 1,30 ganó 75,1 % (1.723), el visitante
    74,6 % (507); sin la condición, 63,9 %.
  · Boletos del día (una por partido, las más altas de la casa): de 2 patas
    18 de 26 enteros, de 3 12 de 21, de 4 10 de 19 (1 día con 3 rojas), de 5
    7 de 17.
  · NO sumaron (ninguna pasó las dos mitades): el veto del modelo, «sólo más
    de», el consenso modelo+casa, el aprendiz (logística semana a semana) y
    los mismos mercados en Novibet (a 70-75 % acierta 71 %: lo que dice).
  · Fuera, por medidos perdedores: tarjetas, córners de equipo, doble
    oportunidad con goles y hándicap (eran justo las rojas del boleto).

CADA PATA lleva `bloque`/`etiqueta`/`linea` para liquidarse sola en «Mis
boletos» (`pronosticos_guardados.validar`).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

CUOTA_MIN = 1.30
CUOTA_MAX = 1.70
CASA_MIN = 0.70
MEDIDO_PATA = 0.78
# patas: (días con el boleto entero, días medidos) — `_v371e_umbral.json`
MEDIDO_BOLETO = {2: (18, 26), 3: (12, 21), 4: (10, 19), 5: (7, 17)}
NOMBRE = 'Método Casa 70/130'
ORIGEN = 'casa70'
# v372 — «también debe haber ganador, que es lo que más cuota da, pero sólo
# cuando la casa también esté a favor»: el 🔷 de la Capa 1 (`lo_mejor.
# del_pick_riesgo`): ganador con la casa sin margen al 55-70 % y el modelo al
# 70 %+ (60 % si la casa ya da 65 %), cuota 1,35+. Medido fuera de muestra
# (`_v317_capa1.json`, 2.354 partidos): 71-72 % a cuota media 1,43. En vivo
# (capa1_historial.json, 3-11 oct): 13 ✅ de 19 a 1,49.
MEDIDO_GANADOR = 0.72
ORIGEN_GANADOR = 'riesgo'
# 🏠 el favorito de la casa, sólo con la casa (ver `ganador_del_partido`)
FAV_CASA_MIN, FAV_CASA_MAX = 0.62, 0.70
FAV_CUOTA_MIN, FAV_CUOTA_MAX = 1.35, 1.60
MEDIDO_FAVORITO = 0.68


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _lados(partido: str):
    par = str(partido or '')
    return [x.strip() for x in par.split(' vs ', 1)] if ' vs ' in par else [None, None]


def patas_del_partido(pick: Dict) -> List[Dict]:
    """Todas las patas del partido que cumplen la regla, de la que la casa ve
    más probable a la que menos."""
    out: List[Dict] = []
    try:
        import mercado_implicito as mi
        h, a = _lados(pick.get('partido'))
        if not h:
            return out
        tab = mi.del_partido(h, a) or {}
        if not tab:
            return out

        def _add(apuesta, p, c, bloque, etiqueta, linea, mercado):
            if p is None or c is None:
                return
            if p >= CASA_MIN and CUOTA_MIN <= c <= CUOTA_MAX:
                out.append({'apuesta': apuesta, 'p_casa': p, 'cuota': c, 'bloque': bloque,
                            'etiqueta': etiqueta, 'linea': linea, 'mercado': mercado})

        # escaleras: el «más» y el «menos» de cada línea .5
        for clave, bloque, etq, rot in (('goles', 'goles', 'Total', 'Goles'),
                                        ('goles_home', 'goles_equipo', 'Local', 'Goles %s' % h),
                                        ('goles_away', 'goles_equipo', 'Visitante', 'Goles %s' % a),
                                        ('corners', 'corners', 'Total', 'Córners'),
                                        ('remates_on_home', 'remates_on', 'Local', 'Tiros a puerta %s' % h),
                                        ('remates_on_away', 'remates_on', 'Visita', 'Tiros a puerta %s' % a)):
            for k, ent in (tab.get(clave) or {}).items():
                L, p = _f(k), mi.prob_de(ent)
                if L is None or p is None or L % 1 != 0.5:
                    continue
                for lado, q in (('mas', p), ('menos', 1 - p)):
                    _add('%s: %s de %g' % (rot, 'Más' if lado == 'mas' else 'Menos', L),
                         q, mi.cuota_de(ent, lado), bloque, etq, L,
                         'Goles' if bloque == 'goles' else rot.split(' ')[0])
        # el ganador: lo que la casa ve (sin margen) y lo que paga
        p1, c1 = tab.get('1x2') or {}, tab.get('1x2_cuotas') or {}
        for lado, eq in (('home', h), ('away', a)):
            _add('Gana %s' % eq, _f(p1.get(lado)), _f(c1.get(lado)), 'resultado', 'Ganador',
                 None, '1X2')
        out.sort(key=lambda x: -x['p_casa'])
        for x in out:
            x.update({'partido': pick.get('partido'), 'inicio': pick.get('inicio'),
                      'fecha': pick.get('fecha'), 'clave_liga': pick.get('clave_liga'),
                      'liga': pick.get('liga'), 'deporte': 'Fútbol', 'casa': 'Playdoit',
                      'prob': MEDIDO_PATA, 'origen': ORIGEN, 'icono': '🎯',
                      'porque': 'la casa lo ve al %.0f %% y paga %.2f · %s'
                                % (100 * x['p_casa'], x['cuota'], NOMBRE)})
    except Exception:
        return []
    return out


_MEMO: Dict = {}


def ganador_del_partido(pick: Dict) -> Optional[Dict]:
    """v372 — el ganador con la casa a favor, o None:
    1. 🔷 con el modelo de acuerdo (`lo_mejor.del_pick_riesgo`, 72 %);
    2. si no, 🏠 el FAVORITO DE LA CASA: sin margen al 62-70 % y cuota
       1,35-1,60 en Playdoit. Medido sólo con la casa en 125.721 partidos
       (`_v372_ganador_casa.py`, 2010-2026): 68,1 % a cuota 1,44 (67,4 / 68,9
       en las dos mitades; 68,6 % desde 2023); al 65-70 %, 70,1 % a 1,40, pero
       Playdoit casi no tiene favoritos ahí (los pone al 62-65 % a ~1,50). El
       modelo casi nunca lo ve al 70 % (más bajo que la casa): el 🔷 sale poco."""
    base = {'partido': pick.get('partido'), 'inicio': pick.get('inicio'),
            'fecha': pick.get('fecha'), 'clave_liga': pick.get('clave_liga'),
            'liga': pick.get('liga'), 'deporte': 'Fútbol', 'origen': ORIGEN_GANADOR,
            'etiqueta': 'Resultado', 'bloque': 'resultado', 'mercado': '1X2', 'linea': None}
    try:
        import lo_mejor as lm
        e = lm.del_pick_riesgo(pick)
    except Exception:
        e = None
    if e:
        return dict(e, **base, casa=e.get('casa') or 'Playdoit', p_casa=e.get('p_mercado'),
                    prob=MEDIDO_GANADOR, icono='🔷',
                    porque='🔷 la casa lo ve al %.0f %% y el modelo al %.0f %% · paga %.2f'
                            % (100 * float(e.get('p_mercado') or 0),
                               100 * float(e.get('prob') or 0), float(e.get('cuota') or 0)))
    try:
        import mercado_implicito as mi
        h, a = _lados(pick.get('partido'))
        tab = mi.del_partido(h, a) or {} if h else {}
        p1, c1 = tab.get('1x2') or {}, tab.get('1x2_cuotas') or {}
        mejor = None
        for lado, eq in (('home', h), ('away', a)):
            pc, cu = _f(p1.get(lado)), _f(c1.get(lado))
            if pc is None or cu is None:
                continue
            if FAV_CASA_MIN <= pc < FAV_CASA_MAX and FAV_CUOTA_MIN <= cu <= FAV_CUOTA_MAX:
                if mejor is None or pc > mejor[1]:
                    mejor = (eq, pc, cu)
        if mejor:
            eq, pc, cu = mejor
            return dict(base, apuesta='Gana %s' % eq, cuota=cu, p_casa=pc, casa='Playdoit',
                        prob=MEDIDO_FAVORITO, icono='🏠',
                        porque='🏠 favorito de la casa: lo ve al %.0f %% y paga %.2f' % (100 * pc, cu))
    except Exception:
        return None
    return None


def con_ganador(pronosticos: List[Dict], prioridad: str = 'seguras',
                ahora: Optional[float] = None) -> List[Dict]:
    """v372 — las sencillas MÁS el 🔷 ganador, una por partido. `seguras`:
    primero las 🎯 (78 %), luego los 🔷 de los partidos que no tienen 🎯;
    `cuota`: primero los 🔷 (72 %, ~1,45) y luego las 🎯."""
    import time
    try:
        import horario as hz
    except Exception:
        return []
    t = float(ahora if ahora is not None else time.time())
    base = del_dia(pronosticos, ahora)
    gan = []
    for p in pronosticos or []:
        if str(p.get('deporte') or 'Fútbol') != 'Fútbol' or p.get('jugado'):
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is None or ini.timestamp() <= t:
            continue
        g = ganador_del_partido(p)
        if g:
            gan.append(g)
    gan.sort(key=lambda x: -float(x.get('p_casa') or 0))
    primero, despues = (base, gan) if prioridad != 'cuota' else (gan, base)
    out, vistos = [], set()
    for x in primero + despues:
        if x.get('partido') in vistos:
            continue
        vistos.add(x.get('partido'))
        out.append(x)
    return out


def del_dia(pronosticos: List[Dict], ahora: Optional[float] = None) -> List[Dict]:
    """La mejor pata de cada partido de fútbol por empezar, de la que la casa
    ve más probable a la que menos. Recordado 5 minutos."""
    import os
    import time
    try:
        import horario as hz
    except Exception:
        return []
    if ahora is None:
        mt = os.path.getmtime('mercado_dia.json') if os.path.exists('mercado_dia.json') else 0
        k = (id(pronosticos), len(pronosticos or []), mt, int(time.time() // 300))
        if _MEMO.get('k') == k:
            return [dict(x) for x in _MEMO['v']]
        v = del_dia(pronosticos, time.time())
        _MEMO.update(k=k, v=v)
        return [dict(x) for x in v]
    out = []
    for p in pronosticos or []:
        if str(p.get('deporte') or 'Fútbol') != 'Fútbol' or p.get('jugado'):
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is None or ini.timestamp() <= float(ahora):
            continue
        pats = patas_del_partido(p)
        if pats:
            out.append(pats[0])
    out.sort(key=lambda x: -x['p_casa'])
    return out


def boleto(lista: List[Dict], n: int) -> Optional[Dict]:
    """Las `n` de la casa más alta (todas si hay menos, con al menos 1)."""
    b = list(lista or [])[:max(int(n), 0)]
    if not b:
        return None
    return {'patas': sorted(b, key=lambda x: str(x.get('inicio') or '')),
            'momio': math.prod(float(x['cuota']) for x in b),
            # v372 — cada pata con lo suyo (🎯 78 %, 🔷 72 %)
            'prob': math.prod(float(x.get('prob') or MEDIDO_PATA) for x in b),
            'n_ganador': sum(1 for x in b if x.get('origen') == ORIGEN_GANADOR),
            'completo': len(b) >= int(n)}


def medido(n: int) -> str:
    if n <= 1:
        return 'Medido: cada pata sola acertó 78 % (80 y 77 % en las dos mitades).'
    k = min(MEDIDO_BOLETO, key=lambda m: (abs(m - int(n)), m))
    e, d = MEDIDO_BOLETO[k]
    return ('Medido (28-ago → 9-oct): con %d patas el boleto salió entero %d de %d días; '
            'cada pata sola, 78 %%.' % (k, e, d))
