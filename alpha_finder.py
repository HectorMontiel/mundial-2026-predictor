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


def exportar_txt(r: Optional[Dict] = None) -> str:
    """Apuestas del día como texto plano (v30 §1: arg opcional — si es None
    usa el último barrido; robusto ante cualquier forma de los picks)."""
    r = r if r is not None else _ULTIMO_RESULTADO
    lineas = [f"APUESTAS DEL DÍA — {r.get('actualizado', '?')}",
              f"(cobertura: {r.get('cobertura_ligas', {})})", ""]
    for grupo, titulo in (('elite', '⭐ ÉLITE / EVC'),
                          ('candidatos', 'CANDIDATOS')):
        picks = r.get(grupo) or []
        if not picks:
            continue
        lineas.append(f"== {titulo} ==")
        for t in picks:
            estrella = '⭐' if t.get('platino') else ('💎' if t.get('evc') else '')
            ev = t.get('ev', 0) or 0
            prob = t.get('prob', 0) or 0
            lineas.append(
                f"{estrella} {t.get('partido','?')} ({t.get('liga','?')}, "
                f"{t.get('fecha','')}) — {t.get('apuesta','?')} @ "
                f"{t.get('cuota','?')} (justa {t.get('cuota_justa','?')}) · "
                f"EV {ev*100:+.1f}% · prob {prob*100:.0f}%"
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
    w.writerow(['grupo', 'partido', 'liga', 'fecha', 'mercado', 'apuesta',
                'cuota', 'cuota_justa', 'ev_pct', 'prob_pct', 'stake',
                'evc', 'platino'])
    for grupo in ('elite', 'candidatos'):
        for t in r.get(grupo) or []:
            w.writerow([grupo, t.get('partido', ''), t.get('liga', ''),
                        t.get('fecha', ''), t.get('mercado', ''),
                        t.get('apuesta', ''), t.get('cuota', ''),
                        t.get('cuota_justa', ''), round((t.get('ev', 0) or 0)*100, 1),
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
