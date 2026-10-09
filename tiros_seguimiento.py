#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v345 — EL «SE METE» DE LOS TIROS SE GANA SOLO, CON DATOS.

`tiros_equipo` predice los tiros de cada equipo mejor que la línea de
Playdoit (log-loss 0,681 contra 0,691 en tiros, 0,654 contra 0,665 a puerta,
410 partidos del 24-ago al 8-oct). Pero la regla de apuesta, elegida con la
primera mitad de ese periodo, no aguantó la segunda:

    regla: tiros totales, el lado que el modelo ve ≥ 10 puntos por encima de
           la casa (y al menos al 50 %)
    elige (24-ago a 10-sep)   168 apuestas  +20,5 %  p5 +7,2 %
    juzga (10-sep a 8-oct)    208 apuestas   +3,2 %  p5 −10,5 %

El usuario pidió que entre en la tarjeta «cuando tenga buena probabilidad,
como lo hemos hecho» y preguntó qué hace falta para que el p5 pase a positivo:
MUESTRA. Con un rendimiento real del 10 % hacen falta unas 220 apuestas
nuevas; con uno del 3 %, más de dos mil (y entonces no conviene).

Así que la regla queda FIJADA desde el 10-sep (lo que vino después no se usó
para elegirla) y este módulo, en cada precálculo:

  1. `registrar`   apunta cada línea de tiros de Playdoit de los partidos sin
                   jugar con la probabilidad del modelo y si la regla apuesta;
  2. `liquidar`    les pone el número real de tiros (`stats_espn`);
  3. `medir`       calcula el registro desde el 10-sep y escribe
                   `tiros_seguimiento.json` con `activo`: p5 > 0 con al menos
                   150 apuestas. Sólo entonces `veredicto_pick` deja «meter»
                   tiros, y sólo los que pasan la regla.

El registro arranca con las 208 apuestas del tramo de juzgar (`origen =
'backtest'`), que ya son posteriores a la elección.
"""
import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('tiros_seguimiento')

# v346 — LA SEGUNDA REGLA, LA QUE SÍ PASÓ: ALTA PROBABILIDAD.
#
# El usuario: «quiero que los tiros también se puedan meter, validado con
# todo el historial». No hay cuotas de tiros anteriores al 24-ago, pero el
# historial completo (2021-2026) dice que el número del modelo es de fiar:
# en el 30 % reciente, lo que promete 72,5 / 77,5 / 82,5 / 87,5 / 94,5 %
# acierta 72,6 / 77,1 / 82,4 / 87,2 / 94,3 % (`_v346_tiros_meter.py`, más de
# 100.000 líneas). Y contra Playdoit, una regla como el «se mete» del resto
# de la tarjeta —probabilidad alta, sin pedirle ventaja sobre la casa—,
# elegida con la primera mitad (24-ago a 10-sep) por el mejor p5 de
# rendimiento con 40+ apuestas, y juzgada con la segunda:
#
#                       apuestas  acierto (promete)  cuota  rinde    p5
#     elige                115     74,8 %             1,43   +4,9 %  −4,4 %
#     juzga (10-sep→)      127     78,0 % (76,6 %)    1,46  +12,1 %  +3,5 %
#
# Tiros totales y a puerta del equipo, el lado que el MODELO ve al 72 % o
# más, cuota hasta 2,0, una por equipo y mercado (la más probable). Sigue
# midiéndose sola: si el registro desde el 10-sep deja de tener p5 > 0, se
# apaga.
#
# v348 — SÓLO «MÁS DE». El usuario: en remates sólo se puede apostar «más de
# X». Medido otra vez con ese lado nada más (`_v348_tiros_mas.py`, elegida con
# la primera mitad: modelo ≥ 68 %, cuota ≤ 2):
#
#                       apuestas  acierto (promete)  rinde    p5
#     elige                 99     69,7 % (73,2 %)    −1,9 %  −13,9 %
#     juzga (10-sep→)      118     73,7 % (74,1 %)    +5,9 %   −4,3 %
#
# La ventaja estaba en el «menos»: con sólo «más» NO pasa, y acertaría ~72 %
# (bajaría el ~80 % de verdes). La regla queda en «más» y en seguimiento:
# `activo` sale falso hasta que su registro tenga p5 > 0.
REGLA_ALTA = {'mercados': ('tiros', 'a_puerta'), 'prob_min': 0.72,
              'cuota_max': 2.0}
MIN_APUESTAS_ALTA = 100

FICHERO = 'tiros_seguimiento.csv'
RESUMEN = 'tiros_seguimiento.json'
REGLA = {'mercado': 'tiros', 'ventaja': 0.10, 'prob_min': 0.50, 'cuota_max': 3.0}
FECHA_REGLA = '2026-09-10'
MIN_APUESTAS = 150
CAMPOS = ['fecha', 'partido', 'clave_liga', 'equipo', 'lado', 'mercado',
          'linea', 'c_mas', 'c_menos', 'p_casa', 'p_mod', 'apuesta',
          'origen', 'real', 'registrado']
_MERCADO_CASA = {'tiros': 'remates', 'a_puerta': 'remates_on'}


def apuesta_de(p_mod: float, p_casa: float, mercado: str,
               c_mas: float = 0.0, c_menos: float = 0.0) -> str:
    """'más', 'menos' o '' según la regla fijada."""
    if mercado != REGLA['mercado'] or p_mod is None or p_casa is None:
        return ''
    if (p_mod - p_casa >= REGLA['ventaja'] and p_mod >= REGLA['prob_min']
            and c_mas <= REGLA['cuota_max']):
        return 'más'
    return ''                # v348: sin «menos» (no se puede apostar)


def alta_de(p_mod: float, mercado: str, c_mas: float = 0.0,
            c_menos: float = 0.0) -> str:
    """'más', 'menos' o '' según la regla de alta probabilidad."""
    if mercado not in REGLA_ALTA['mercados'] or p_mod is None:
        return ''
    if p_mod >= REGLA_ALTA['prob_min'] and 0 < c_mas <= REGLA_ALTA['cuota_max']:
        return 'más'
    return ''                # v348: sin «menos» (no se puede apostar)


def _leer(ruta: str = FICHERO) -> pd.DataFrame:
    try:
        return pd.read_csv(ruta)
    except Exception:
        return pd.DataFrame(columns=CAMPOS)


def registrar(pronosticos: List[Dict], ruta: str = FICHERO,
              ahora: Optional[_dt.datetime] = None) -> int:
    """Apunta (o actualiza hasta el pitido) las líneas de los partidos sin
    jugar. Nunca lanza. Devuelve cuántas filas tocó."""
    try:
        import mercado_implicito as mi
        import tiros_equipo as te
        ahora = ahora or _dt.datetime.utcnow()
        filas = []
        for p in pronosticos or []:
            if not isinstance(p, dict) or p.get('jugado'):
                continue
            dp = te.del_partido(p)
            if not dp:
                continue
            try:
                ini = pd.Timestamp(str(p.get('inicio'))[:19])
            except Exception:
                continue
            if ini <= pd.Timestamp(ahora):
                continue
            imp = p.get('implicitas') or {}
            for lado, suf in (('local', '_home'), ('visitante', '_away')):
                h, a = te._lados(p.get('partido'))
                equipo = h if lado == 'local' else a
                for mercado, fam in _MERCADO_CASA.items():
                    lam = dp['lados'][lado][mercado]
                    k = float(dp['k'].get(mercado) or 50)
                    for lin, dato in (imp.get(fam + suf) or {}).items():
                        try:
                            L = float(lin)
                            cm_, cn = mi.cuota_de(dato, 'mas'), mi.cuota_de(dato, 'menos')
                        except Exception:
                            continue
                        if not (cm_ and cn):
                            continue
                        pc = (1 / cm_) / (1 / cm_ + 1 / cn)
                        pm = te.prob_mas(lam, L, k)
                        filas.append({
                            'fecha': ini.strftime('%Y-%m-%d'), 'partido': p.get('partido'),
                            'clave_liga': p.get('clave_liga'), 'equipo': equipo,
                            'lado': lado, 'mercado': mercado, 'linea': L,
                            'c_mas': cm_, 'c_menos': cn, 'p_casa': round(pc, 4),
                            'p_mod': round(pm, 4),
                            'apuesta': apuesta_de(pm, pc, mercado, cm_, cn),
                            'origen': 'vivo', 'real': np.nan,
                            'registrado': ahora.strftime('%Y-%m-%dT%H:%M:%SZ')})
        if not filas:
            return 0
        d = pd.concat([_leer(ruta), pd.DataFrame(filas)], ignore_index=True)
        # la última foto antes del pitido manda
        d = d.drop_duplicates(['partido', 'equipo', 'mercado', 'linea'], keep='last')
        d[CAMPOS].to_csv(ruta, index=False)
        return len(filas)
    except Exception as e:
        logger.warning('[tiros] no se pudo registrar: %s', e)
        return 0


def liquidar(ruta: str = FICHERO) -> int:
    """Pone el número real de tiros a lo ya jugado (`stats_espn`)."""
    try:
        import stats_espn as se
        d = _leer(ruta)
        if d.empty:
            return 0
        pend = d[d.real.isna() & (pd.to_datetime(d.fecha) < pd.Timestamp.utcnow().tz_localize(None))]
        n = 0
        for liga, g in pend.groupby('clave_liga'):
            try:
                s = se.leer(liga)
            except Exception:
                continue
            if not len(s):
                continue
            eqs = set(g.equipo)
            tr = se._traductor(set(s.home) | set(s.away), eqs)
            s = s.assign(h=s.home.map(lambda x: tr.get(x)), a=s.away.map(lambda x: tr.get(x)))
            for i, r in g.iterrows():
                f = pd.Timestamp(r.fecha)
                cand = s[(pd.to_datetime(s.fecha) - f).abs() <= pd.Timedelta(days=1)]
                lado_h = cand[cand.h == r.equipo]
                lado_a = cand[cand.a == r.equipo]
                if len(lado_h):
                    x, pre = lado_h.iloc[0], 'home'
                elif len(lado_a):
                    x, pre = lado_a.iloc[0], 'away'
                else:
                    continue
                on, off = x['%s_shots_on' % pre], x['%s_shots_off' % pre]
                if pd.isna(on) or pd.isna(off):
                    continue
                d.loc[i, 'real'] = (on + off) if r.mercado == 'tiros' else on
                n += 1
        d[CAMPOS].to_csv(ruta, index=False)
        return n
    except Exception as e:
        logger.warning('[tiros] no se pudo liquidar: %s', e)
        return 0


def medir(ruta: str = FICHERO, salida: str = RESUMEN, semilla: int = 345) -> Dict:
    """El registro de la regla desde que quedó fijada, y si ya se activa."""
    d = _leer(ruta)
    # v348 — el lado se recalcula con la regla VIGENTE (sólo «más»), no con
    # el que se apuntó al registrar
    if len(d):
        d['apuesta'] = [apuesta_de(a, b, c, m_, n_) for a, b, c, m_, n_ in
                        zip(d.p_mod, d.p_casa, d.mercado, d.c_mas, d.c_menos)]
    d = d[(d.apuesta.fillna('') != '') & d.real.notna()
          & (pd.to_datetime(d.fecha) >= pd.Timestamp(FECHA_REGLA))]
    res = {'regla': REGLA, 'desde': FECHA_REGLA, 'min_apuestas': MIN_APUESTAS,
           'n': int(len(d)), 'activo': False,
           'medido': _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}
    if len(d):
        mas = d.apuesta == 'más'
        gana = np.where(mas, d.real > d.linea, d.real <= d.linea).astype(int)
        cuota = np.where(mas, d.c_mas, d.c_menos)
        gan = gana * cuota - 1
        rng = np.random.default_rng(semilla)
        um, inv = np.unique(d.partido.astype(str).values, return_inverse=True)
        s, n = np.bincount(inv, weights=gan), np.bincount(inv)
        bs = [s[i].sum() / n[i].sum() for i in
              (rng.integers(0, len(um), len(um)) for _ in range(4000))]
        p5 = float(np.percentile(bs, 5))
        res.update({'partidos': int(len(um)), 'acierto': round(float(gana.mean()), 4),
                    'promete': round(float(np.where(mas, d.p_mod, 1 - d.p_mod).mean()), 4),
                    'cuota_media': round(float(cuota.mean()), 3),
                    'roi': round(float(gan.mean()), 4), 'p5': round(p5, 4),
                    'vivas': int((d.origen == 'vivo').sum()),
                    'activo': bool(len(d) >= MIN_APUESTAS and p5 > 0)})
    res['alta'] = _medir_alta(_leer(ruta), semilla)
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


def _medir_alta(d: pd.DataFrame, semilla: int = 346) -> Dict:
    """El registro de la regla de alta probabilidad desde el 10-sep: una
    apuesta por equipo y mercado (la más probable de sus líneas)."""
    out = {'regla': {k: list(v) if isinstance(v, tuple) else v
                     for k, v in REGLA_ALTA.items()},
           'desde': FECHA_REGLA, 'min_apuestas': MIN_APUESTAS_ALTA,
           'n': 0, 'activo': False}
    d = d[d.real.notna() & (pd.to_datetime(d.fecha) >= pd.Timestamp(FECHA_REGLA))].copy()
    if d.empty:
        return out
    d['lado_alta'] = [alta_de(p, m, a, b) for p, m, a, b in
                      zip(d.p_mod, d.mercado, d.c_mas, d.c_menos)]
    d = d[d.lado_alta != '']
    if d.empty:
        return out
    mas = d.lado_alta == 'más'
    d['p_lado'] = np.where(mas, d.p_mod, 1 - d.p_mod)
    d = d.sort_values('p_lado', ascending=False).drop_duplicates(
        ['partido', 'equipo', 'mercado'])
    mas = d.lado_alta == 'más'
    gana = np.where(mas, d.real > d.linea, d.real <= d.linea).astype(int)
    cuota = np.where(mas, d.c_mas, d.c_menos)
    gan = gana * cuota - 1
    rng = np.random.default_rng(semilla)
    um, inv = np.unique(d.partido.astype(str).values, return_inverse=True)
    s, n = np.bincount(inv, weights=gan), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in
          (rng.integers(0, len(um), len(um)) for _ in range(4000))]
    p5 = float(np.percentile(bs, 5))
    out.update({'n': int(len(d)), 'partidos': int(len(um)),
                'acierto': round(float(gana.mean()), 4),
                'promete': round(float(d.p_lado.mean()), 4),
                'cuota_media': round(float(cuota.mean()), 3),
                'roi': round(float(gan.mean()), 4), 'p5': round(p5, 4),
                'activo': bool(len(d) >= MIN_APUESTAS_ALTA and p5 > 0)})
    return out


def activo(salida: str = RESUMEN, regla: str = 'valor') -> bool:
    """¿Está ganada la regla? `regla`: 'valor' (ventaja sobre la casa) o
    'alta' (alta probabilidad)."""
    try:
        with open(salida, encoding='utf-8') as f:
            doc = json.load(f) or {}
        return bool((doc.get('alta') or {}).get('activo') if regla == 'alta'
                    else doc.get('activo'))
    except Exception:
        return False


def sembrar(lineas_pkl: str = '_v345_lineas.pkl', ruta: str = FICHERO) -> int:
    """Arranca el registro con las líneas de la prueba (`_v345_tiros.py`)."""
    x = pd.read_pickle(lineas_pkl)
    d = pd.DataFrame({
        'fecha': pd.to_datetime(x.fecha).dt.strftime('%Y-%m-%d'),
        'partido': 'mid-' + x.mid.astype(str), 'clave_liga': x.liga,
        'equipo': x.equipo, 'lado': '', 'mercado': x.obj, 'linea': x.linea,
        'c_mas': x.c_mas, 'c_menos': x.c_menos, 'p_casa': x.p_casa.round(4),
        'p_mod': x.p_mod.round(4),
        'apuesta': [apuesta_de(a, b, c, m_, n_) for a, b, c, m_, n_ in
                    zip(x.p_mod, x.p_casa, x.obj, x.c_mas, x.c_menos)],
        'origen': 'backtest', 'real': x.real, 'registrado': ''})
    d[CAMPOS].to_csv(ruta, index=False)
    return len(d)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import sys
    if '--sembrar' in sys.argv:
        print(sembrar())
    print(json.dumps(medir(), ensure_ascii=False, indent=1))
