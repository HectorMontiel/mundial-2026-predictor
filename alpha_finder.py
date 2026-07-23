#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha Finder — panel «Apuestas del Día» (v26, spec §4.2).

Recorre los partidos con cuotas vigentes en odds_actuales.json (próximas
48 h), pide la predicción al motor de su liga y evalúa los mercados
disponibles (1X2, O/U 2.5, BTTS, AH ±0.5) con la cuota REAL.

Filtros de élite (spec):
  * probabilidad del modelo para el mercado > 0.70
  * EV > +3 % con la cuota real
  * cuota real > 1.50 (nada de micro-cuotas)

Si el Shadow Booster está adoptado y hay señal para el partido, el pick se
marca con ⚡ y se prioriza. Degradación honesta: si ningún candidato pasa
los filtros, se devuelven los mejores por EV marcados como no-élite; si un
partido no tiene cuota para un mercado, ese mercado no se evalúa (lista
blanca implícita de mercados disponibles).
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# v30: último barrido almacenado a nivel de módulo (respaldo para la
# exportación sin argumentos; evita el AttributeError de producción v29).
_ULTIMO_RESULTADO: Dict = {}

MIN_PROB = 0.70
MIN_EV = 0.03
MIN_CUOTA = 1.50
HORIZONTE_HORAS = 48


def _mapa_equipo_liga() -> Dict[str, str]:
    from config import LEAGUES
    mapa = {}
    for clave in LEAGUES:
        try:
            with open(f'team_stats_{clave}.json', encoding='utf-8') as f:
                for eq in json.load(f).get('equipos', {}):
                    mapa[eq] = clave
        except Exception:
            continue
    return mapa


def _liga_fuzzy(home: str, away: str, mapa: Dict[str, str]):
    """v29 (§1.2): respaldo fuzzy nombre→liga (Betexplorer/API usan grafías
    que no siempre coinciden exacto con team_stats — la causa del bug "solo
    salía MLS": los partidos de Liga MX se descartaban en silencio)."""
    from difflib import SequenceMatcher
    for equipo in (home, away):
        mejor, ratio = None, 0.0
        for nombre, liga in mapa.items():
            s = SequenceMatcher(None, equipo.lower(), nombre.lower()).ratio()
            if s > ratio:
                mejor, ratio = liga, s
        if ratio >= 0.82:
            return mejor
    return None


def _mercados_del_partido(pred: Dict, o: Dict, home: str, away: str) -> List[Dict]:
    """Evalúa cada mercado con cuota disponible contra el modelo."""
    M = np.array(pred['score_matrix'])
    idx = np.arange(M.shape[0])
    diff = idx[:, None] - idx[None, :]
    total = idx[:, None] + idx[None, :]
    pr = pred['prediction']['probabilities']
    btts = float(M[(idx[:, None] >= 1) & (idx[None, :] >= 1)].sum())
    over25 = float(M[total > 2.5].sum())

    candidatos = []

    def _add(mercado, etiqueta, prob, cuota):
        if not cuota or pd.isna(cuota) or cuota <= 1:
            return
        candidatos.append({'mercado': mercado, 'apuesta': etiqueta,
                           'prob': round(float(prob), 3),
                           'cuota': round(float(cuota), 2),
                           'cuota_justa': round(1 / max(float(prob), 1e-6), 2),
                           'ev': round(float(cuota) * float(prob) - 1, 3)})

    _add('1X2', f'Gana {home}', pr['home'], o.get('odd_home'))
    _add('1X2', 'Empate', pr['draw'], o.get('odd_draw'))
    _add('1X2', f'Gana {away}', pr['away'], o.get('odd_away'))
    _add('Goles', 'Más de 2.5', over25, o.get('odd_over25'))
    _add('Goles', 'Menos de 2.5', 1 - over25, o.get('odd_under25'))
    _add('BTTS', 'Ambos marcan: Sí', btts, o.get('odd_btts_yes'))
    _add('BTTS', 'Ambos marcan: No', 1 - btts, o.get('odd_btts_no'))
    linea = o.get('ah_linea')
    try:
        linea = float(linea)
    except (TypeError, ValueError):
        linea = None
    if linea == -0.5:
        _add('Hándicap', f'{home} −0.5', float(M[diff > 0].sum()), o.get('odd_ah_home'))
        _add('Hándicap', f'{away} +0.5', float(M[diff <= 0].sum()), o.get('odd_ah_away'))
    elif linea == 0.5:
        _add('Hándicap', f'{home} +0.5', float(M[diff >= 0].sum()), o.get('odd_ah_home'))
        _add('Hándicap', f'{away} −0.5', float(M[diff < 0].sum()), o.get('odd_ah_away'))
    return candidatos


def _senales_shadow() -> Dict[str, Dict]:
    """Residuos del Shadow Booster por partido (solo ligas ADOPTADAS)."""
    try:
        with open('shadow_senales.json', encoding='utf-8') as f:
            return json.load(f).get('detalle', {})
    except Exception:
        return {}


def _filtro_evc(tarjeta: Dict, resid: Optional[float]) -> str:
    """EVC 2.0 (v27 §7): doble validación sin tocar los modelos.
    Devuelve 'evc' | 'elite' | 'descartada' para un pick que ya cumple los
    filtros de élite. El residuo del Shadow es local-céntrico: se invierte
    para apuestas al visitante y se ignora en mercados no direccionales."""
    if resid is None:                       # liga sin Shadow adoptado → cond 4-5 se omiten
        return 'evc'
    apuesta = tarjeta['apuesta'].lower()
    if apuesta.startswith('gana ') and tarjeta['mercado'] == '1X2':
        es_home = tarjeta['partido'].lower().startswith(
            apuesta.replace('gana ', ''))
        r_dir = resid if es_home else -resid
    else:
        return 'evc'                        # mercado no direccional
    if tarjeta['prob'] > 0.75 and r_dir < -0.05:
        return 'descartada'                 # divergencia crítica (cond 5)
    return 'evc' if r_dir > -0.03 else 'elite'   # cond 4


def apuestas_del_dia(max_partidos: int = 40) -> Dict:
    """Tarjetas del panel. Devuelve élite + candidatos (degradación honesta)."""
    try:
        with open('odds_actuales.json', encoding='utf-8') as f:
            datos = json.load(f)
    except Exception:
        return {'actualizado': None, 'elite': [], 'candidatos': [],
                'aviso': 'Sin odds_actuales.json — corre el pipeline de cuotas.'}
    cuotas = datos.get('cuotas', {})
    mapa = _mapa_equipo_liga()
    senales = _senales_shadow()

    hoy = pd.Timestamp.today().normalize()
    limite = hoy + pd.Timedelta(hours=HORIZONTE_HORAS)
    motores: Dict[str, object] = {}
    elite, candidatos = [], []
    evaluados = 0
    # v29 (§1.2): diagnóstico de cobertura por liga — el bug "solo MLS" venía
    # de partidos descartados en silencio cuando el nombre no mapeaba a liga.
    cobertura: Dict[str, int] = {}
    sin_liga = 0
    for mid, o in sorted(cuotas.items()):
        partes = mid.split('_')
        if len(partes) != 3:
            continue
        try:
            fecha = pd.Timestamp(partes[0])
        except ValueError:
            continue
        if not (hoy <= fecha <= limite):
            continue
        home = partes[1].replace('-', ' ')
        away = partes[2].replace('-', ' ')
        liga = mapa.get(home) or mapa.get(away) or _liga_fuzzy(home, away, mapa)
        if not liga:
            sin_liga += 1
            logger.info(f"[alpha] sin liga para {home} vs {away} (revisar mapeo)")
            continue
        cobertura[liga] = cobertura.get(liga, 0) + 1
        if liga not in motores:
            from league_engine import ClubEngine
            motores[liga] = ClubEngine(liga)
        eng = motores[liga]
        if not getattr(eng, 'listo', False) or home not in eng.stats \
                or away not in eng.stats:
            continue
        if evaluados >= max_partidos:
            break
        evaluados += 1
        pred = eng.predecir(home, away)
        if 'error' in pred:
            continue
        det = senales.get(mid)
        resid = det.get('residuo') if det else None
        for c in _mercados_del_partido(pred, o, home, away):
            tarjeta = {
                'partido': f'{home} vs {away}', 'liga': pred.get('liga', liga),
                'fecha': str(fecha.date()), **c,
                'shadow': bool(det),
                'valor': ('🟢' if c['ev'] > 0.05 else
                          '🟡' if c['ev'] > 0 else '🔴'),
            }
            if (c['prob'] > MIN_PROB and c['ev'] > MIN_EV
                    and c['cuota'] > MIN_CUOTA):
                estado = _filtro_evc(tarjeta, resid)
                if estado == 'descartada':      # divergencia crítica (v27)
                    tarjeta['nota'] = ('⚠️ descartada por EVC: confianza alta '
                                       'con Shadow desfavorable')
                    candidatos.append(tarjeta)
                else:
                    tarjeta['evc'] = estado == 'evc'
                    elite.append(tarjeta)
            elif c['ev'] > 0:
                candidatos.append(tarjeta)

    # v28 (§2.5) EVC PLATINO — triple validación: EVC (conf>75 %) ∧ el mismo
    # partido tiene arbitraje cruzado con ν>1 (arbitraje_cache.json, del
    # último barrido) ∧ sin divergencia crítica (ya filtrada arriba).
    try:
        with open('arbitraje_cache.json', encoding='utf-8') as f:
            partidos_arb = {op['partido']
                            for op in json.load(f).get('oportunidades', [])}
    except Exception:
        partidos_arb = set()
    for t in elite:
        t['platino'] = bool(t.get('evc') and t['prob'] > 0.75
                            and t['partido'] in partidos_arb)

    orden = lambda t: (-int(t.get('platino', False)), -int(t['shadow']), -t['ev'])
    logger.info(f"[alpha] cobertura por liga: {cobertura} · sin liga: {sin_liga}")
    global _ULTIMO_RESULTADO
    _ULTIMO_RESULTADO = {'actualizado': datos.get('actualizado'),
            'partidos_evaluados': evaluados,
            'cobertura_ligas': cobertura, 'partidos_sin_liga': sin_liga,
            'elite': sorted(elite, key=orden),
            'candidatos': sorted(candidatos, key=orden)[:15],
            'aviso': None if elite else
            ('Ningún mercado cumple hoy los filtros de élite (prob >70 %, '
             'EV >+3 %, cuota >1.50) — se muestran los mejores candidatos '
             'con EV positivo.')}
    return _ULTIMO_RESULTADO


# ---------------------------------------------------------------------------
# v31 (§1/§5): bucle dinámico universal + doble capa
#   Capa 1 «EVC Platino»: hay CUOTA REAL y pasa los filtros de élite.
#   Capa 2 «Alta Confianza»: SIN cuota real y confianza > 75 % → se sugiere
#   la cuota mínima (1/prob). Sin stake (no hay EV real).
# ---------------------------------------------------------------------------
# v33 (§2): umbrales adaptativos por deporte, centralizados en config.py
try:
    from config import UMBRALES_DEPORTE
except ImportError:
    UMBRALES_DEPORTE = {}
CONF_CAPA2 = UMBRALES_DEPORTE.get('Fútbol', {}).get('capa2', 0.75)
UMBRAL_CONF = {d: u['capa1'] for d, u in UMBRALES_DEPORTE.items()} or \
    {'MLB': 0.58, 'Tenis': 0.65, 'NBA': 0.70}


def umbral(deporte: str, capa: str = 'capa1') -> float:
    """Umbral de confianza del deporte (§2)."""
    por_defecto = {'capa1': 0.70, 'capa2': 0.75}[capa]
    return UMBRALES_DEPORTE.get(deporte, {}).get(capa, por_defecto)


def indicador_antiguedad(dias: Optional[int]) -> str:
    """§5: semáforo de frescura de los datos de la liga."""
    if dias is None:
        return ''
    if dias < 3:
        return f'🟢 datos de hace {dias} d'
    if dias <= 7:
        return f'🟡 datos de hace {dias} d'
    return f'🔴 sin datos nuevos desde hace {dias} d'


def _picks_mlb() -> Dict[str, List[Dict]]:
    """MLB: cuotas en vivo de The Odds API (capa 1) + alta confianza (capa 2)."""
    try:
        from engines.mlb_engine import MLBEngine
        eng = MLBEngine().cargar_modelo()
        if not eng.listo:
            return {'capa1': [], 'capa2': []}
        r = eng.apuestas_dia(min_prob=UMBRAL_CONF['MLB'])
        capa1 = [{**p, 'liga': 'MLB', 'mercado': 'Moneyline',
                  'valor': p.get('valor', '🟡')} for p in r.get('picks', [])]
        return {'capa1': capa1, 'capa2': []}
    except Exception as e:
        logger.warning(f"[alpha] MLB omitido: {type(e).__name__}: {e}")
        return {'capa1': [], 'capa2': []}


def _picks_tenis() -> Dict[str, List[Dict]]:
    """Tenis: cuotas de Betexplorer (ATP) + fuzzy de nombres (§4.2)."""
    salida = {'capa1': [], 'capa2': [], 'no_enlazados': []}
    try:
        import betexplorer_scraper as bx
        from engines.tennis_engine import TennisEngine
        eng = TennisEngine().cargar_modelo()
        if not eng.listo:
            return salida
        partidos = bx.cuotas_tenis_hoy()
        for m in partidos:
            j1 = bx.emparejar_jugador(m['home'], eng.jugadores)
            j2 = bx.emparejar_jugador(m['away'], eng.jugadores)
            if not (j1 and j2):
                salida['no_enlazados'].append(f"{m['home']} vs {m['away']}")
                continue
            pred = eng.predecir(j1, j2)
            if 'error' in pred:
                continue
            for lado, nombre, prob, cuota in (
                    ('home', m['home'], pred['prob_home'], m['odd_home']),
                    ('away', m['away'], pred['prob_away'], m['odd_away'])):
                ev = round(cuota * prob - 1, 4)
                base = {'deporte': 'Tenis', 'liga': 'ATP',
                        'partido': f"{m['home']} vs {m['away']}",
                        'fecha': str(pd.Timestamp.today().date()),
                        'mercado': 'Ganador', 'apuesta': f'Gana {nombre}',
                        'prob': round(prob, 3),
                        'cuota_justa': round(1 / max(prob, 1e-6), 2)}
                if prob > UMBRAL_CONF['Tenis'] and ev > MIN_EV and cuota > MIN_CUOTA:
                    salida['capa1'].append({**base, 'cuota': round(cuota, 2),
                                            'ev': ev,
                                            'valor': '🟢' if ev > 0.05 else '🟡'})
                elif prob > CONF_CAPA2:
                    salida['capa2'].append({**base, 'cuota': None, 'ev': None,
                                            'valor': '🎯'})
    except Exception as e:
        logger.warning(f"[alpha] tenis omitido: {type(e).__name__}: {e}")
    return salida


def _picks_nba() -> Dict[str, List[Dict]]:
    """NBA: sin cuotas en julio (fuera de temporada) → capa 2 si hay partidos."""
    salida = {'capa1': [], 'capa2': []}
    try:
        import betexplorer_scraper as bx
        partidos = bx.cuotas_baloncesto_hoy()
        if not partidos:
            return salida
        from engines.nba_engine import NBAEngine
        eng = NBAEngine().cargar_modelo()
        if not eng.listo:
            return salida
        for m in partidos:
            pred = eng.predecir(m['home'], m['away'])
            if 'error' in pred:
                continue
            for nombre, prob, cuota in ((m['home'], pred['prob_home'], m['odd_home']),
                                        (m['away'], pred['prob_away'], m['odd_away'])):
                ev = round(cuota * prob - 1, 4)
                base = {'deporte': 'NBA', 'liga': 'NBA',
                        'partido': f"{m['home']} vs {m['away']}",
                        'fecha': str(pd.Timestamp.today().date()),
                        'mercado': 'Moneyline', 'apuesta': f'Gana {nombre}',
                        'prob': round(prob, 3),
                        'cuota_justa': round(1 / max(prob, 1e-6), 2)}
                if prob > UMBRAL_CONF['NBA'] and ev > MIN_EV and cuota > MIN_CUOTA:
                    salida['capa1'].append({**base, 'cuota': round(cuota, 2),
                                            'ev': ev, 'valor': '🟢'})
                elif prob > CONF_CAPA2:
                    salida['capa2'].append({**base, 'cuota': None, 'ev': None,
                                            'valor': '🎯'})
    except Exception as e:
        logger.warning(f"[alpha] NBA omitido: {type(e).__name__}: {e}")
    return salida


# ---------------------------------------------------------------------------
# v32: fiabilidad histórica (Brier real de los picks publicados por liga),
# cuarentena de pretemporada y segregación de EV extremo.
# ---------------------------------------------------------------------------
EV_EXTREMO = 0.15          # §3: por encima, el modelo está descalibrado
                           # (gap de calibración −0.154 vs −0.038; ROI −12.4 pp)
_FIABILIDAD: Dict[str, float] = {}


def fiabilidad_liga(liga: str) -> Optional[float]:
    """Brier score REAL de los picks que el sistema publicó en esa liga
    (roi_bets_{liga}.json: prob prometida vs resultado). None si no hay datos."""
    if not _FIABILIDAD:
        import glob
        for ruta in glob.glob('roi_bets_*.json'):
            clave = ruta[len('roi_bets_'):-len('.json')]
            try:
                with open(ruta, encoding='utf-8') as f:
                    bets = json.load(f)
                if len(bets) >= 30:
                    _FIABILIDAD[clave] = round(float(np.mean(
                        [(b['prob'] - b['gano']) ** 2 for b in bets])), 4)
            except Exception:
                continue
        _FIABILIDAD.setdefault('_vacio', 1.0)
    return _FIABILIDAD.get(liga)


def etiqueta_fiabilidad(brier: Optional[float]) -> str:
    """Traducción UX del Brier (§5.2)."""
    if brier is None:
        return '⚪ Sin histórico'
    if brier < 0.15:
        return '🟢 Fiabilidad élite'
    if brier < 0.22:
        return '🟡 Fiabilidad estándar'
    return '🔴 Alta incertidumbre'


DIAS_ESTADO_OBSOLETO = 45


def _dias_estado_obsoleto(liga: str, fecha: str) -> Optional[int]:
    """§4 (cuarentena): días transcurridos desde el último partido con el que
    se entrenó la liga. Un desfase grande significa PRETEMPORADA (ligas
    europeas en julio) o simplemente estado sin refrescar: en ambos casos la
    varianza sube y el pick baja a Capa 2. Regla dirigida por datos."""
    try:
        with open(f'team_stats_{liga}.json', encoding='utf-8') as f:
            ultima = json.load(f).get('ultima_fecha_historico')
        if not ultima:
            return None
        return int((pd.Timestamp(fecha) - pd.Timestamp(ultima)).days)
    except Exception:
        return None


def pick_del_dia(picks: List[Dict]) -> Optional[Dict]:
    """UN solo pick (§5.3): confianza >80 %, EV en [+2 %, +15 %], fiabilidad
    del mercado ≥ 🟡 y sin pretemporada. Desempate: Brier ↑, EV ↓, prob ↓."""
    aptos = []
    for p in picks:
        ev = p.get('ev')
        if ev is None or not (0.02 <= ev <= EV_EXTREMO):
            continue
        if (p.get('prob') or 0) <= 0.80 or p.get('pretemporada'):
            continue
        brier = p.get('brier')
        if brier is not None and brier >= 0.22:
            continue
        aptos.append(p)
    if not aptos:
        return None
    return sorted(aptos, key=lambda p: (p.get('brier') if p.get('brier')
                                        is not None else 0.21,
                                        -(p.get('ev') or 0),
                                        -(p.get('prob') or 0)))[0]


def apuestas_del_dia_universal(max_partidos: int = 40) -> Dict:
    """Barrido de TODAS las competiciones activas (11 de fútbol + MLB, NBA,
    tenis) con clasificación en dos capas (§1.2, §5.1)."""
    r = apuestas_del_dia(max_partidos=max_partidos)
    capa1 = list(r.get('elite') or [])
    for p in capa1:
        p.setdefault('deporte', 'Fútbol')
    capa2, no_enlazados = [], []
    for fn in (_picks_mlb, _picks_tenis, _picks_nba):
        try:
            sub = fn()
        except Exception as e:
            logger.warning(f"[alpha] {fn.__name__}: {e}")
            continue
        capa1 += sub.get('capa1', [])
        capa2 += sub.get('capa2', [])
        no_enlazados += sub.get('no_enlazados', [])
    # --- v32: fiabilidad, pretemporada y segregación de EV extremo -------
    LIGA_A_CLAVE = {'Liga MX': 'liga_mx', 'MLS': 'mls', 'Premier League': 'premier',
                    'LaLiga': 'laliga', 'Serie A': 'serie_a',
                    'Bundesliga': 'bundesliga', 'Ligue 1': 'ligue_1',
                    'Eredivisie': 'eredivisie', 'Primeira Liga': 'primeira',
                    'UEFA Champions League': 'champions'}
    for p in capa1 + capa2:
        clave = LIGA_A_CLAVE.get(p.get('liga', ''), p.get('liga', '').lower())
        p['brier'] = fiabilidad_liga(clave)
        p['fiabilidad'] = etiqueta_fiabilidad(p['brier'])
        dias = (_dias_estado_obsoleto(clave, p.get('fecha'))
                if p.get('deporte', 'Fútbol') == 'Fútbol' else None)
        p['dias_estado'] = dias
        p['antiguedad'] = indicador_antiguedad(dias)      # §5 semáforo
        p['pretemporada'] = bool(dias and dias > DIAS_ESTADO_OBSOLETO)
        if p['pretemporada']:
            p['nota'] = (f'⚠️ El modelo de esta liga no ve partidos desde hace '
                         f'{dias} días (pretemporada o estado sin refrescar) — '
                         'alta varianza')
    # §4: los partidos de pretemporada salen de la Capa 1 (van a Capa 2)
    pretemporada = [p for p in capa1 if p.get('pretemporada')]
    capa1 = [p for p in capa1 if not p.get('pretemporada')]
    capa2 += pretemporada
    # §3: EV extremo se SEGREGA (no se descarta) — validado en
    # resultados_ev_extremo_v32.json
    ev_extremo = [p for p in capa1 if (p.get('ev') or 0) > EV_EXTREMO]
    capa1 = [p for p in capa1 if (p.get('ev') or 0) <= EV_EXTREMO]

    capa1.sort(key=lambda t: (-int(t.get('platino', False)), -(t.get('ev') or 0)))
    capa2.sort(key=lambda t: -(t.get('prob') or 0))
    ev_extremo.sort(key=lambda t: -(t.get('ev') or 0))
    deportes = sorted({p.get('deporte', 'Fútbol') for p in capa1 + capa2})
    r.update({'capa1': capa1, 'capa2': capa2, 'ev_extremo': ev_extremo,
              'no_enlazados': no_enlazados, 'deportes_cubiertos': deportes,
              'pick_del_dia': pick_del_dia(capa1),
              'elite': capa1,          # compatibilidad con UI/exportación
              })
    try:                      # v32 §6: registro para el rendimiento REAL
        import rendimiento_real
        rendimiento_real.registrar(capa1, 'capa1')
        rendimiento_real.registrar(capa2, 'capa2')
    except Exception as e:
        logger.warning(f"[alpha] rendimiento_real no registrado: {e}")
    global _ULTIMO_RESULTADO
    _ULTIMO_RESULTADO = r
    logger.info(f"[alpha] universal: capa1={len(capa1)} capa2={len(capa2)} "
                f"deportes={deportes} no_enlazados={len(no_enlazados)}")
    return r


def exportar_txt(r: Optional[Dict] = None) -> str:
    """Apuestas del día como texto plano (v30 §1: arg opcional — si es None
    usa el último barrido; robusto ante cualquier forma de los picks)."""
    r = r if r is not None else _ULTIMO_RESULTADO
    lineas = [f"APUESTAS DEL DÍA — {r.get('actualizado', '?')}",
              f"(cobertura: {r.get('cobertura_ligas', {})})", ""]
    for grupo, titulo in (('elite', '💎 CAPA 1 — EVC PLATINO / ÉLITE (cuota real)'),
                          ('capa2', '🎯 CAPA 2 — ALTA CONFIANZA (sin cuota real)'),
                          ('candidatos', 'CANDIDATOS')):
        picks = r.get(grupo) or []
        if not picks:
            continue
        lineas.append(f"== {titulo} ==")
        for t in picks:
            estrella = '⭐' if t.get('platino') else ('💎' if t.get('evc') else '')
            ev = t.get('ev') or 0
            prob = t.get('prob', 0) or 0
            cuota = t.get('cuota')
            precio = (f"@ {cuota} (justa {t.get('cuota_justa','?')}) · "
                      f"EV {ev*100:+.1f}%" if cuota else
                      f"SIN cuota real · cuota mínima sugerida "
                      f"{t.get('cuota_justa','?')}")
            lineas.append(
                f"{estrella} [{t.get('deporte','Fútbol')}] {t.get('partido','?')} "
                f"({t.get('liga','?')}, {t.get('fecha','')}) — "
                f"{t.get('apuesta','?')} {precio} · prob {prob*100:.0f}%"
                + (f" · stake {t['stake_txt']}" if t.get('stake_txt') else ''))
        lineas.append("")
    lineas.append("Juego responsable. Cuotas justas = 1/probabilidad.")
    return '\n'.join(lineas)


def exportar_csv(r: Optional[Dict] = None) -> str:
    import csv
    import io
    r = r if r is not None else _ULTIMO_RESULTADO
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['capa', 'deporte', 'partido', 'liga', 'fecha', 'mercado',
                'apuesta', 'cuota', 'cuota_justa', 'ev_pct', 'prob_pct',
                'stake', 'evc', 'platino'])
    for grupo, capa in (('elite', 'capa1_evc'), ('capa2', 'capa2_confianza'),
                        ('candidatos', 'candidatos')):
        for t in r.get(grupo) or []:
            w.writerow([capa, t.get('deporte', 'Fútbol'), t.get('partido', ''),
                        t.get('liga', ''), t.get('fecha', ''), t.get('mercado', ''),
                        t.get('apuesta', ''), t.get('cuota', ''),
                        t.get('cuota_justa', ''), round((t.get('ev') or 0)*100, 1),
                        round((t.get('prob', 0) or 0)*100, 0), t.get('stake_txt', ''),
                        t.get('evc', False), t.get('platino', False)])
    return buf.getvalue()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    r = apuestas_del_dia()
    print(f"evaluados: {r['partidos_evaluados']} · élite: {len(r['elite'])} · "
          f"candidatos: {len(r['candidatos'])}")
    for t in (r['elite'] or r['candidatos'])[:8]:
        print(f"  {t['valor']} {t['fecha']} {t['liga']}: {t['partido']} — "
              f"{t['apuesta']} @ {t['cuota']} (justa {t['cuota_justa']}, "
              f"EV {t['ev']*100:+.1f} %)")
