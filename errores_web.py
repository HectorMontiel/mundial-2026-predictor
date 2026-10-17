#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v384 — LOS ERRORES DE CUOTA (💰) EN SHARPICKS, Y EL CONTEXTO DE CADA PARTIDO.

El usuario: «cualquier error de cuota que tenga buena probabilidad de acuerdo
a su histórico reciente y los datos de lesiones conviene meterlo… si de 50
errores se ve que 20 se van a cumplir, al gratuito uno o dos y los demás al
VIP».

ERRORES. Los 💰 de la Capa 1 (una casa paga más que el precio justo de
Pinnacle) que pasaron su validación. Cada uno lleva su PROBABILIDAD DE
CUMPLIRSE = la de Pinnacle sin margen (1 / cuota justa) y su VENTAJA (cuánto
paga de más).

v385 — MEDIDO EN 8 AÑOS (`_v385_errores_hist.py`: 13.217 errores de
`pick_ledger.csv`, 2018-2026, dos mitades): se cumplen EXACTAMENTE con la
probabilidad de Pinnacle y, todos juntos, ganan +5,6 / +5,7 por $100 (p5 > 0).
Pierden o no se sostienen: el EMPATE, cuota > 4 y ventaja de sólo 3-5 %. La
forma y el H2H NO mejoran la probabilidad de Pinnacle (AUC 0,667 contra
0,685): el mercado ya los descuenta. Filtro: ventaja ≥ 5 %, probabilidad
≥ 30 %, cuota ≤ 4, nunca empate. Al canal gratis, 1-2 de probabilidad ≥ 55 %
(salen ~7 de 10); al VIP, todos, con 🔥 los patrones más fuertes (local
favorito con ventaja ≥ 5 %: +7 / +16; ventaja ≥ 12 %: +24 / +19).

CONTEXTO. Para cada partido de fútbol: la forma (últimos 5 de cada equipo),
los últimos cruces (H2H) con fecha y marcador, del histórico de Flashscore
(los mismos nombres de equipo que los errores), y las bajas de FotMob cuando
las hay. Se enseña en la tarjeta y se guarda para volver a medirlo.
Nunca lanza.
"""
import datetime as dt
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('errores_web')
VENTAJA_MIN = 0.05
PROB_MIN = 0.30
CUOTA_MAX = 4.0
PROB_GRATIS = 0.55
N_GRATIS = 2
HORAS_GRATIS = 24


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _resultados_anunciados(ruta: str = 'anunciadas_dia.json') -> Dict:
    """(partido, apuesta) → (resultado, marcador) de los 💰 ya liquidados."""
    out = {}
    try:
        d = json.load(open(ruta, encoding='utf-8'))
        for e in (d.get('partidos') or {}).values():
            for c in e.get('capa1') or []:
                if c.get('nivel') == '💰' and c.get('resultado'):
                    out[(e.get('partido'), c.get('apuesta'))] = (c['resultado'], c.get('marcador'))
    except Exception as ex:
        logger.debug('[errores] anunciadas: %s', ex)
    return out


def errores(datos: Dict, ahora: Optional[dt.datetime] = None) -> List[Dict]:
    """Los 💰 del día como filas del sitio (`tipo` = 'error'), con su
    probabilidad, su ventaja, si pasan el filtro y cuáles van al gratis."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    res = _resultados_anunciados()
    out = []
    for c in (datos or {}).get('capa1') or []:
        try:
            if c.get('validado') is False or 'Pinnacle' not in str(c.get('origen') or ''):
                continue
            cuota, justa = _f(c.get('cuota')), _f(c.get('cuota_justa')) or _f(c.get('pinnacle'))
            if not cuota or not justa:
                continue
            prob, ventaja = 1.0 / justa, cuota / justa - 1.0
            ap = str(c.get('apuesta') or '')
            if ventaja < VENTAJA_MIN or prob < PROB_MIN or cuota > CUOTA_MAX or 'mpate' in ap:
                continue
            # 🔥 los patrones más fuertes medidos en 8 años
            local = c.get('lado') == 'home' and ' vs ' in str(c.get('partido') or '')
            fuerte = ventaja >= 0.12 or (local and prob >= 0.45)
            r = res.get((c.get('partido'), c.get('apuesta')))
            estado = {'verde': 'verde', 'rojo': 'roja'}.get((r or ('',))[0], 'pendiente')
            out.append({'partido': c.get('partido'), 'inicio': str(c.get('inicio') or '').replace('T', ' ')[:19],
                        'fecha': c.get('fecha'), 'deporte': c.get('deporte'), 'liga': c.get('liga'),
                        'clave_liga': c.get('clave_liga'),
                        'apuesta': c.get('apuesta'), 'cuota': round(cuota, 3), 'prob': round(prob, 3),
                        'elige': False, 'tipo': 'error', 'casa': c.get('casa'), 'ventaja': round(ventaja, 3),
                        'porque': ('🔥 ' if fuerte else '') + 'Paga %.0f %% más que el precio justo (Pinnacle) en %s' % (100 * ventaja, c.get('casa') or 'la casa'),
                        'estado': estado, 'resultado_c1': None, 'marcador': (r or (None, None))[1], 'gratis': False})
        except Exception as ex:
            logger.debug('[errores] %s: %s', c.get('partido'), ex)
    # al gratis: los más probables de las próximas horas (uno por partido)
    fin = ahora + dt.timedelta(hours=HORAS_GRATIS)
    vistos = set()
    for p in sorted(out, key=lambda x: -x['prob']):
        try:
            ini = dt.datetime.fromisoformat(p['inicio']).replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
        if p['estado'] == 'pendiente' and p['prob'] >= PROB_GRATIS and ahora < ini <= fin and p['partido'] not in vistos:
            p['gratis'] = True
            vistos.add(p['partido'])
            if len(vistos) >= N_GRATIS:
                break
    return out


# ---------- contexto: forma, H2H y bajas ----------
_FS = {}


def _flashscore():
    if 'df' not in _FS:
        try:
            import pandas as pd
            fs = [pd.read_csv(f) for f in ('resultados_flashscore.csv.gz', 'resultados_flashscore_reciente.csv.gz')
                  if os.path.exists(f)]
            df = pd.concat(fs).drop_duplicates('match_id') if fs else None
            if df is not None:
                df['date'] = pd.to_datetime(df['ini'], errors='coerce')
                df = df.dropna(subset=['date', 'gh', 'ga']).sort_values('date')
                idx = {}
                for i, (h, a) in enumerate(zip(df['home'], df['away'])):
                    idx.setdefault(h, []).append(i)
                    idx.setdefault(a, []).append(i)
                _FS.update(df=df, idx=idx)
            else:
                _FS.update(df=None, idx={})
        except Exception as ex:
            logger.debug('[errores] flashscore: %s', ex)
            _FS.update(df=None, idx={})
    return _FS['df'], _FS['idx']


def _bajas() -> Dict:
    if 'bajas' not in _FS:
        m = {}
        try:
            d = json.load(open('bajas_dia.json', encoding='utf-8'))
            for e in (d.get('partidos') or {}).values():
                for lado in ('home', 'away'):
                    x = e.get(lado) or {}
                    if x.get('equipo'):
                        m[x['equipo']] = [b.get('jugador') for b in x.get('bajas') or [] if b.get('jugador')]
        except Exception:
            pass
        _FS['bajas'] = m
    return _FS['bajas']


def _forma(df, idx, eq, antes) -> str:
    filas = [i for i in idx.get(eq, [])]
    if not filas:
        return ''
    m = df.iloc[filas]
    m = m[m['date'] < antes].tail(5)
    out = ''
    for h, gh, ga in zip(m['home'], m['gh'], m['ga']):
        gf, gc = (gh, ga) if h == eq else (ga, gh)
        out += 'G' if gf > gc else ('E' if gf == gc else 'P')
    return out


def contexto(p: Dict) -> Optional[Dict]:
    """{'fl': 'GGEPG', 'fv': ..., 'h2h': [[fecha, local, marcador, visita], …], 'bl': [...], 'bv': [...]}"""
    try:
        if str(p.get('deporte') or '') != 'Fútbol' or ' vs ' not in str(p.get('partido') or ''):
            return None
        home, away = [s.strip() for s in str(p['partido']).split(' vs ', 1)]
        df, idx = _flashscore()
        import pandas as pd
        antes = pd.Timestamp(str(p.get('inicio') or '')[:10] or dt.date.today().isoformat())
        ctx = {}
        if df is not None:
            ctx['fl'], ctx['fv'] = _forma(df, idx, home, antes), _forma(df, idx, away, antes)
            comun = sorted(set(idx.get(home, [])) & set(idx.get(away, [])))
            if comun:
                m = df.iloc[comun]
                m = m[m['date'] < antes].tail(5)
                ctx['h2h'] = [[d.strftime('%d/%m/%y'), h, '%d-%d' % (gh, ga), a]
                              for d, h, gh, ga, a in zip(m['date'], m['home'], m['gh'], m['ga'], m['away'])][::-1]
        b = _bajas()
        if b.get(home):
            ctx['bl'] = b[home][:6]
        if b.get(away):
            ctx['bv'] = b[away][:6]
        return {k: v for k, v in ctx.items() if v} or None
    except Exception as ex:
        logger.debug('[errores] contexto %s: %s', p.get('partido'), ex)
        return None
