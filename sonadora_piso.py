#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v373 — LA SOÑADORA POR CUOTA MÍNIMA: N PATAS, LA CUOTA QUE TÚ ELIJAS.

El usuario (12-oct): «quiero poder escoger la cuota mínima por pata (1,5, 1,6,
1,7…) porque hay promociones de mínimo 1,60; N patas, hasta 25 o más; patas
sólidas y justificadas, de acuerdo con la casa pero un paso adelante».

LO QUE SE MIDIÓ ANTES DE HACERLO (`_v373_*.py`, cada uno con un revisor que
intentó tumbarlo; escaleras de Playdoit 28-ago → 9-oct, 125.721 partidos del
histórico 2010-2026, Novibet real, Playdoit y Pinnacle en el mismo barrido):
  · Ni corregir el margen de la casa (potencia, Shin, logit, recalibrar), ni
    el aprendizaje automático (logística, árbol, LightGBM, apilado), ni el
    contexto de los equipos (forma, desgaste, tabla), ni el Método Contexto
    por equipo, ni otras formas de armar el boleto, ni el cruce con Pinnacle
    con precios simultáneos le ganan de forma sostenida a «LA CASA ELIGE» a
    cuota 1,45 o más. La señal de Pinnacle que parecía grande era una fuga
    (comparaba contra el cierre). Por eso aquí manda la casa.
  · Lo que acierta cada piso eligiendo así, una pata por partido
    (`_v373_pisos.py`): 1,30 → 72,9 % a 1,34 · 1,45 → 61,5 % a 1,51 ·
    1,60 → 56,2 % a 1,67 · 1,70 → 51,3 % a 1,75 · 1,80 → 49,7 % a 1,87.
  · La pata acierta lo que dice la casa sin margen (calibrada ±1,5 pts), salvo
    las que la casa ve al 70 %+, que aciertan 79 % (la Casa 70/130).
  · Boletos del día: de 4 patas salieron enteros 14 / 11 / 6 / 2 / 4 de 27
    días según el piso; de 10 o más, NINGUNO en 18 días a ningún piso.
  · Boosters: con los márgenes de hoy, el +20 % de Draftea (4 patas ≥ 1,60)
    no alcanza; un ×1,8 sí deja valor esperado positivo con 4 patas.

Mercados: goles (total y por equipo), córners del partido, tiros y tiros a
puerta (total y por equipo), ambos marcan y ganador (también el empate, si su
cuota cae en el piso). Fuera: tarjetas y córners de equipo (medidos
perdedores). Cada pata lleva lo que necesita para liquidarse sola en «Mis
boletos» y su justificación: lo que ve la casa, lo que ve el Método Contexto
y lo medido.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
ANCHO = 0.5                  # la cuota de la pata, entre el piso y piso + 0,5
CASA_ALTA = 0.70
ACIERTO_CASA_ALTA = 0.78     # la Casa 70/130 (medido 78-79 %)
ORIGEN = 'piso'
# por piso: acierto por pata, cuota media, y boletos {N: (enteros, días)}
MEDIDO = {1.30: (0.729, 1.34, {4: (14, 27), 6: (5, 23), 10: (0, 18)}),
          1.45: (0.615, 1.51, {4: (11, 27), 6: (3, 23), 10: (0, 18)}),
          1.60: (0.562, 1.67, {4: (6, 27), 6: (2, 23), 10: (0, 18)}),
          1.70: (0.513, 1.75, {4: (2, 27), 6: (0, 23), 10: (0, 18)}),
          1.80: (0.497, 1.87, {4: (4, 27), 6: (1, 23), 10: (0, 18)})}
VETO_METODO = 0.06           # el método la ve 6+ pts por debajo: se avisa


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _lados(partido: str):
    par = str(partido or '')
    return [x.strip() for x in par.split(' vs ', 1)] if ' vs ' in par else [None, None]


def prob_medida(p_casa: float) -> float:
    """Lo que acierta de verdad una pata que la casa ve a `p_casa`."""
    return ACIERTO_CASA_ALTA if p_casa >= CASA_ALTA else p_casa


def _metodo(pick: Dict):
    """{obj: (λ local, λ visita, k)} del Método Contexto, o {}."""
    try:
        import tiros_equipo as te
        dp = te.del_partido(pick) or {}
        lados, kk = dp.get('lados') or {}, dp.get('k') or {}
        out = {}
        for obj in ('goles', 'corners', 'tiros', 'a_puerta'):
            lh = (lados.get('local') or {}).get(obj)
            la = (lados.get('visitante') or {}).get(obj)
            if lh is not None and la is not None:
                out[obj] = (float(lh), float(la), float(kk.get(obj) or 0) or None)
        return out
    except Exception:
        return {}


def _p_metodo(met: Dict, obj: str, lado: str, linea: float, mas: bool) -> Optional[float]:
    try:
        import tiros_equipo as te
        if obj not in met:
            return None
        lh, la, k = met[obj]
        k = k or {'goles': 500.0, 'corners': 12.0, 'tiros': 20.0, 'a_puerta': 40.0}[obj]
        if lado == 'total':
            mu = lh + la
            k = (mu ** 2) / max((lh ** 2 + la ** 2) / k, 1e-9) if k < 400 else 1e6
        else:
            mu = lh if lado == 'local' else la
            k = k if k < 400 else 1e6
        p = te.prob_mas(mu, linea, k)
        return p if mas else 1 - p
    except Exception:
        return None


# (clave del tablero, bloque, etiqueta, objetivo del método, lado, rótulo)
_ESCALERAS = (('goles', 'goles', 'Total', 'goles', 'total', 'Goles'),
              ('goles_home', 'goles_equipo', 'Local', 'goles', 'local', 'Goles {h}'),
              ('goles_away', 'goles_equipo', 'Visitante', 'goles', 'visita', 'Goles {a}'),
              ('corners', 'corners', 'Total', 'corners', 'total', 'Córners'),
              ('remates', 'remates', 'Total', 'tiros', 'total', 'Tiros'),
              ('remates_home', 'remates', 'Local', 'tiros', 'local', 'Tiros {h}'),
              ('remates_away', 'remates', 'Visita', 'tiros', 'visita', 'Tiros {a}'),
              ('remates_on', 'remates_on', 'Total', 'a_puerta', 'total', 'Tiros a puerta'),
              ('remates_on_home', 'remates_on', 'Local', 'a_puerta', 'local', 'Tiros a puerta {h}'),
              ('remates_on_away', 'remates_on', 'Visita', 'a_puerta', 'visita', 'Tiros a puerta {a}'))


def candidatas(pick: Dict, piso: float, con_ganador: bool = True) -> List[Dict]:
    """Todas las patas del partido con la cuota en [piso, piso + 0,5], de la
    más probable (medido) a la menos. Nunca lanza."""
    out: List[Dict] = []
    try:
        import mercado_implicito as mi
        h, a = _lados(pick.get('partido'))
        if not h:
            return out
        tab = mi.del_partido(h, a) or {}
        if not tab:
            return out
        met = _metodo(pick)
        lo, hi = float(piso), float(piso) + ANCHO

        def _add(apuesta, p, c, bloque, etiqueta, linea, mercado, pm=None):
            if p is None or c is None or not lo <= c <= hi:
                return
            out.append({'apuesta': apuesta, 'p_casa': p, 'prob': prob_medida(p), 'cuota': c,
                        'bloque': bloque, 'etiqueta': etiqueta, 'linea': linea,
                        'mercado': mercado, 'p_metodo': pm})

        for clave, bloque, etq, obj, lado, rot in _ESCALERAS:
            rot = rot.format(h=h, a=a)
            for k, ent in (tab.get(clave) or {}).items():
                L, p = _f(k), mi.prob_de(ent)
                if L is None or p is None or L % 1 != 0.5:
                    continue
                for mas, q, ld in ((True, p, 'mas'), (False, 1 - p, 'menos')):
                    _add('%s: %s de %g' % (rot, 'Más' if mas else 'Menos', L), q,
                         mi.cuota_de(ent, ld), bloque, etq, L, rot.split(' ')[0],
                         _p_metodo(met, obj, lado, L, mas))
        pb, cb = _f(tab.get('btts')), tab.get('btts_cuotas') or {}
        if pb is not None:
            _add('Ambos marcan: Sí', pb, _f(cb.get('si')), 'btts', 'Ambos marcan', None, 'Ambos marcan')
            _add('Ambos marcan: No', 1 - pb, _f(cb.get('no')), 'btts', 'Ambos marcan', None, 'Ambos marcan')
        if con_ganador:
            p1, c1 = tab.get('1x2') or {}, tab.get('1x2_cuotas') or {}
            for lado, ap in (('home', 'Gana %s' % h), ('away', 'Gana %s' % a), ('draw', 'Empate')):
                _add(ap, _f(p1.get(lado)), _f(c1.get(lado)), 'resultado', 'Ganador', None, '1X2')
        out.sort(key=lambda x: (-x['prob'], -x['p_casa']))
        for x in out:
            pm = x.get('p_metodo')
            just = 'casa %.0f %%' % (100 * x['p_casa'])
            if pm is not None:
                just += ' · Método Contexto %.0f %%' % (100 * pm)
                if pm < x['p_casa'] - VETO_METODO:
                    just += ' ⚠️'
            if x['p_casa'] >= CASA_ALTA:
                just += ' · Casa 70/130'
            x.update({'partido': pick.get('partido'), 'inicio': pick.get('inicio'),
                      'fecha': pick.get('fecha'), 'clave_liga': pick.get('clave_liga'),
                      'liga': pick.get('liga'), 'deporte': 'Fútbol', 'origen': ORIGEN,
                      'casa': 'Playdoit · ' + just, 'icono': '🎯' if x['p_casa'] >= CASA_ALTA else '',
                      'porque': just})
    except Exception:
        return []
    return out


_MEMO: Dict = {}


def del_dia(pronosticos: List[Dict], piso: float, con_ganador: bool = True,
            ahora: Optional[float] = None) -> List[Dict]:
    """La mejor pata de cada partido de fútbol por empezar, de la más
    probable (medido) a la menos. Recordado 5 minutos."""
    import os
    import time
    try:
        import horario as hz
    except Exception:
        return []
    if ahora is None:
        mt = os.path.getmtime('mercado_dia.json') if os.path.exists('mercado_dia.json') else 0
        k = (id(pronosticos), len(pronosticos or []), float(piso), bool(con_ganador), mt,
             int(time.time() // 300))
        if _MEMO.get('k') == k:
            return [dict(x) for x in _MEMO['v']]
        v = del_dia(pronosticos, piso, con_ganador, time.time())
        _MEMO.update(k=k, v=v)
        return [dict(x) for x in v]
    out = []
    for p in pronosticos or []:
        if str(p.get('deporte') or 'Fútbol') != 'Fútbol' or p.get('jugado'):
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is None or ini.timestamp() <= float(ahora):
            continue
        c = candidatas(p, piso, con_ganador)
        if c:
            out.append(c[0])
    out.sort(key=lambda x: (-x['prob'], -x['p_casa']))
    return out


def boleto(lista: List[Dict], n: int) -> Optional[Dict]:
    """Las `n` más probables (todas si hay menos)."""
    b = list(lista or [])[:max(int(n), 0)]
    if not b:
        return None
    return {'patas': sorted(b, key=lambda x: str(x.get('inicio') or '')),
            'momio': math.prod(float(x['cuota']) for x in b),
            'prob': math.prod(float(x['prob']) for x in b),
            'completo': len(b) >= int(n)}


def partir(b: Optional[Dict], tam: int = 4) -> List[Dict]:
    if not b:
        return []
    ps = b['patas']
    return [{'patas': ps[i:i + tam], 'momio': math.prod(float(x['cuota']) for x in ps[i:i + tam]),
             'prob': math.prod(float(x['prob']) for x in ps[i:i + tam])}
            for i in range(0, len(ps), tam)]


def valor_esperado(b: Optional[Dict], booster: float = 0.0) -> Optional[float]:
    """Por cada $100: (1 + booster) × momio × probabilidad − 1."""
    if not b:
        return None
    return 100.0 * ((1.0 + float(booster)) * b['momio'] * b['prob'] - 1.0)


def medido(piso: float, n: int) -> str:
    pk = min(MEDIDO, key=lambda k: abs(k - float(piso)))
    ac, cu, bol = MEDIDO[pk]
    t = ('Medido a cuota %.2f (28-ago → 9-oct): cada pata acertó %.0f %% a %.2f.'
         % (pk, 100 * ac, cu))
    nk = min(bol, key=lambda k: (abs(k - int(n)), k))
    e, d = bol[nk]
    t += ' Boletos de %d patas: %d enteros de %d días.' % (nk, e, d)
    if n >= 10:
        t += ' Con 10 o más patas no salió NINGUNO entero en 18 días: mejor partirlo.'
    return t
