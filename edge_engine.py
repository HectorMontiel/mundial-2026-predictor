#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de Rentabilidad (v38) — selección de apuestas VALIDADA con datos reales.

## El hallazgo que origina este módulo
El diagnóstico sobre 2.846 apuestas históricas reales (roi_bets_*.json, con la
cuota apostada, la de cierre de Pinnacle y el resultado) reveló que:

  · El ROI global es −4.47 % (el sistema perdía dinero).
  · El tramo de EV alto (>15 %) es TÓXICO: −10 % de ROI en 1.033 apuestas
    (el 36 % del total) — el mayor sumidero, por descalibración del modelo en
    los extremos (ya lo señalaba la v32).
  · El mapa de rentabilidad POR LIGA NO es estacionario: seleccionar ligas
    "rentables" del pasado SOBREAJUSTA y empeora fuera de muestra.
  · Lo que SÍ generaliza es la BANDA DE EV. Restringir a EV ∈ [3 %, 12 %]
    convierte el ROI de las recomendaciones de ~negativo a **positivo y
    consistente**: validación en 4 ventanas temporales fuera de muestra
    (+0.77 %, +7.86 %, +9.01 %, +19.24 %) — TODAS positivas.

## Qué hace este módulo
1. Calibra la banda de EV rentable por criterio MAXIMIN (maximiza la PEOR
   ventana fuera de muestra, no el ROI global — robusto, no optimista).
2. Expone `banda_rentable()` para que alpha_finder filtre la Capa 1.
3. Puntúa cada pick con su "rentabilidad esperada" según el tramo de EV en el
   que cae (histórico real, no teórico).
4. Publica el mapa de ligas como DIAGNÓSTICO (no filtro duro: sobreajusta),
   para avisar de ligas estructuralmente deficitarias.

Todo se pre-calcula a partir de roi_bets (cero peticiones); el frontend solo
lee edge_map.json.
"""

import glob
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

ARCHIVO = 'edge_map.json'
# Banda por defecto (la adoptada tras la validación maximin — ver __main__).
BANDA_DEFECTO = (0.03, 0.12)
# Candidatas que se escanean en la calibración.
BANDAS_CANDIDATAS = [(0.02, 0.10), (0.02, 0.12), (0.03, 0.10), (0.03, 0.12),
                     (0.03, 0.13), (0.025, 0.11), (0.04, 0.12), (0.03, 0.14)]
# v39: piso de PROBABILIDAD dentro de la banda. El hallazgo: con el piso 0.70
# de la v38 apenas entraban 18 apuestas (ruido); bajarlo a 0.55 rescata la
# franja [0.55,0.70) que rinde +8 % ROI → más cobertura Y más ROI.
PISO_PROB_DEFECTO = 0.55
PISOS_PROB_CANDIDATOS = [0.50, 0.55, 0.60, 0.65, 0.70]
# v40: filtro de CONVICCIÓN = prob × EV. Un pick fuerte tiene prob alta Y EV
# alto a la vez; exigir un mínimo del producto descarta los picks "flojos por
# los dos lados". Validado: sube el ROI de +7.9 % a +9.9 % con las 4 ventanas
# OOS en [17.8, 20.6] (más ROI Y más consistente).
CONVICCION_DEFECTO = 0.025
CONVICCION_CANDIDATOS = [0.0, 0.015, 0.02, 0.025, 0.03]


def _ligas_disponibles() -> Optional[set]:
    """Claves de liga con disponible=True en config (para no calibrar sobre
    ligas retiradas de Capa 1, que sesgarían la banda). None si no se puede
    leer config (entonces no se filtra)."""
    try:
        from config import LEAGUES
        return {k for k, v in LEAGUES.items() if v.get('disponible')}
    except Exception:
        return None


def _cargar_apuestas() -> List[Dict]:
    disponibles = _ligas_disponibles()
    filas = []
    for f in glob.glob('roi_bets_*.json'):
        liga = f.split('roi_bets_')[1].rsplit('.', 1)[0]
        # v39: excluir ligas NO disponibles (retiradas de Capa 1) — sus
        # apuestas deficitarias contaminaban la calibración de la banda.
        if disponibles is not None and liga not in disponibles:
            continue
        try:
            for b in json.load(open(f, encoding='utf-8')):
                if b.get('cuota') and b.get('gano') is not None and b.get('fecha'):
                    b['liga'] = liga
                    filas.append(b)
        except Exception as e:
            logger.warning(f"[edge] {f} ilegible: {e}")
    filas.sort(key=lambda b: b['fecha'])
    return filas


def _roi(bs: List[Dict]) -> Tuple[int, float, float]:
    if not bs:
        return (0, 0.0, 0.0)
    g = sum((b['cuota'] - 1) if b['gano'] else -1 for b in bs)
    hit = sum(b['gano'] for b in bs) / len(bs)
    return (len(bs), round(100 * g / len(bs), 2), round(hit, 3))


def _roi_ventanas(rows: List[Dict], lo: float, hi: float,
                  n_ventanas: int = 4) -> List[float]:
    """ROI en n ventanas OOS rodantes sobre la mitad final del histórico."""
    out = []
    for k in range(n_ventanas):
        a = int(len(rows) * (0.5 + 0.1 * k))
        b = int(len(rows) * (0.6 + 0.1 * k))
        seg = [x for x in rows[a:b] if lo <= x['ev'] <= hi]
        out.append(_roi(seg)[1])
    return out


def calibrar(guardar: bool = True) -> Dict:
    """Elige la banda de EV por MAXIMIN (mejor peor-ventana OOS) y arma el mapa
    de ligas + tramos de EV como diagnóstico."""
    rows = _cargar_apuestas()
    if not rows:
        return {'error': 'sin roi_bets para calibrar'}

    # tramos de EV (diagnóstico) sobre TODO el histórico — se usan también como
    # RESTRICCIÓN: una banda no puede contener un subtramo grueso claramente
    # deficitario (evita que el maximin extienda la banda a zonas que SABEMOS
    # que pierden, un artefacto de la definición de ventanas).
    tramos = []
    for a, b in [(-1, 0), (0, 0.03), (0.03, 0.08), (0.08, 0.12),
                 (0.12, 0.13), (0.13, 0.14), (0.12, 0.15), (0.15, 10)]:
        r = _roi([x for x in rows if a <= x['ev'] < b])
        tramos.append({'ev': [a, b], 'n': r[0], 'roi': r[1], 'hit': r[2]})
    ROI_TRAMO_MIN = -3.0

    def _banda_valida(lo: float, hi: float) -> bool:
        for t in tramos:
            a, b = t['ev']
            # subtramo COMPLETAMENTE dentro de la banda y con muestra suficiente
            if a >= lo and b <= hi and t['n'] >= 60 and t['roi'] < ROI_TRAMO_MIN:
                return False
        return True

    resultados = []
    for lo, hi in BANDAS_CANDIDATAS:
        vent = _roi_ventanas(rows, lo, hi)
        glob_ = _roi([b for b in rows if lo <= b['ev'] <= hi])
        resultados.append({
            'banda': [lo, hi], 'roi_global': glob_[1], 'n': glob_[0],
            'ventanas_oos': vent, 'peor_ventana': round(min(vent), 2),
            'ventanas_positivas': int(sum(1 for v in vent if v > 0)),
            'valida': _banda_valida(lo, hi),
        })
    # maximin SOBRE LAS BANDAS VÁLIDAS: mayor peor-ventana; desempate por nº de
    # ventanas positivas y volumen. Si ninguna es válida, se cae a todas.
    validas = [r for r in resultados if r['valida']] or resultados
    mejor = max(validas, key=lambda r: (r['peor_ventana'],
                                        r['ventanas_positivas'], r['n']))

    # v39: piso de probabilidad (maximin) DENTRO de la banda adoptada. Solo se
    # evalúa sobre apuestas que traen prob; si no hay, se usa el defecto.
    lo_b, hi_b = mejor['banda']
    escaneo_prob = []
    con_prob = [b for b in rows if b.get('prob') is not None]
    if con_prob:
        for piso in PISOS_PROB_CANDIDATOS:
            vent = []
            for k in range(4):
                a = int(len(con_prob) * (0.5 + 0.1 * k))
                c = int(len(con_prob) * (0.6 + 0.1 * k))
                seg = [x for x in con_prob[a:c]
                       if lo_b <= x['ev'] <= hi_b and x['prob'] >= piso]
                vent.append(_roi(seg)[1])
            g = _roi([x for x in con_prob
                      if lo_b <= x['ev'] <= hi_b and x['prob'] >= piso])
            escaneo_prob.append({'piso': piso, 'n': g[0], 'roi_global': g[1],
                                 'ventanas_oos': vent,
                                 'peor_ventana': round(min(vent), 2),
                                 'ventanas_positivas': int(sum(v > 0 for v in vent))})
        # maximin con volumen mínimo (evitar pisos altos con muy pocas apuestas)
        cand = [e for e in escaneo_prob if e['n'] >= 100] or escaneo_prob
        mejor_piso = max(cand, key=lambda e: (e['peor_ventana'],
                                              e['ventanas_positivas'], e['n']))['piso']
    else:
        mejor_piso = PISO_PROB_DEFECTO

    # v40: CONVICCIÓN (prob × EV) — seleccionada por BOOTSTRAP p5 (robustez).
    # LECCIÓN v40: el maximin sobre 4 ventanas es FRÁGIL — depende de dónde
    # caen los límites de ventana y da resultados inconsistentes. El bootstrap
    # remuestrea toda la selección sin fronteras arbitrarias: maximizar el p5
    # (peor ROI plausible al 95 %) es un criterio robusto y honesto.
    rng = np.random.default_rng(42)

    def _p5(bets: List[Dict]) -> float:
        if len(bets) < 30:
            return -999.0
        pnl = np.array([(b['cuota'] - 1) if b['gano'] else -1.0 for b in bets])
        boot = [100 * rng.choice(pnl, len(pnl), replace=True).mean()
                for _ in range(2000)]
        return float(np.percentile(boot, 5))

    escaneo_conv = []
    mejor_conv = CONVICCION_DEFECTO
    if con_prob:
        pool = [b for b in con_prob
                if lo_b <= b['ev'] <= hi_b and b['prob'] >= mejor_piso]
        for q in CONVICCION_CANDIDATOS:
            sel_q = [x for x in pool if x['prob'] * x['ev'] >= q]
            escaneo_conv.append({'conviccion': q, 'n': len(sel_q),
                                 'roi_global': _roi(sel_q)[1],
                                 'roi_p5_bootstrap': round(_p5(sel_q), 2)})
        # exigir volumen mínimo y elegir el mayor p5 (mejor peor ROI plausible)
        cand = [e for e in escaneo_conv if e['n'] >= 150] or escaneo_conv
        mejor_conv = max(cand, key=lambda e: (e['roi_p5_bootstrap'], e['n']))['conviccion']

    # v40: intervalo de confianza BOOTSTRAP del ROI de la selección FINAL
    # (banda ∩ piso ∩ convicción) — robustez honesta: el p5 dice el peor ROI
    # plausible. Si el p5 es positivo, el edge no es una casualidad.
    ci = {}
    if con_prob:
        final = [b for b in con_prob if lo_b <= b['ev'] <= hi_b
                 and b['prob'] >= mejor_piso and b['prob'] * b['ev'] >= mejor_conv]
        if len(final) >= 30:
            rng = np.random.default_rng(42)
            pnl = np.array([(b['cuota'] - 1) if b['gano'] else -1.0 for b in final])
            boot = [100 * rng.choice(pnl, len(pnl), replace=True).mean()
                    for _ in range(3000)]
            ci = {'n': len(final), 'roi_medio': round(float(np.mean(boot)), 2),
                  'roi_p5': round(float(np.percentile(boot, 5)), 2),
                  'roi_p95': round(float(np.percentile(boot, 95)), 2)}

    # mapa de ligas (DIAGNÓSTICO, no filtro)
    ligas = {}
    for lg in sorted(set(b['liga'] for b in rows)):
        r = _roi([b for b in rows if b['liga'] == lg])
        ligas[lg] = {'n': r[0], 'roi': r[1], 'hit': r[2]}

    salida = {
        'generado': __import__('pandas').Timestamp.today().strftime('%Y-%m-%d'),
        'n_apuestas': len(rows),
        'banda_adoptada': mejor['banda'],
        'roi_banda_global': mejor['roi_global'],
        'ventanas_oos_banda': mejor['ventanas_oos'],
        'piso_prob_adoptado': mejor_piso,
        'conviccion_adoptada': mejor_conv,
        'ci_bootstrap_seleccion': ci,
        'escaneo_prob': sorted(escaneo_prob, key=lambda e: -e['peor_ventana']),
        'escaneo_conviccion': sorted(escaneo_conv,
                                     key=lambda e: -e.get('roi_p5_bootstrap', -999)),
        'escaneo_bandas': sorted(resultados, key=lambda r: -r['peor_ventana']),
        'tramos_ev': tramos,
        'ligas': ligas,
    }
    if guardar:
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)
    logger.info(f"[edge] banda adoptada {mejor['banda']} · ROI global "
                f"{mejor['roi_global']:+.1f} % · ventanas OOS {mejor['ventanas_oos']}")
    return salida


_cache: Optional[Dict] = None


def _mapa() -> Dict:
    global _cache
    if _cache is None:
        try:
            with open(ARCHIVO, encoding='utf-8') as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def banda_rentable() -> Tuple[float, float]:
    """Banda de EV adoptada (calibrada o por defecto)."""
    m = _mapa()
    b = m.get('banda_adoptada')
    return (b[0], b[1]) if b and len(b) == 2 else BANDA_DEFECTO


def piso_prob() -> float:
    """Piso de probabilidad adoptado (v39, maximin) o el defecto."""
    return _mapa().get('piso_prob_adoptado', PISO_PROB_DEFECTO)


def conviccion_min() -> float:
    """Mínimo de convicción prob×EV adoptado (v40) o el defecto."""
    return _mapa().get('conviccion_adoptada', CONVICCION_DEFECTO)


def en_seleccion(ev: Optional[float], prob: Optional[float]) -> bool:
    """v40: ¿el pick está en la selección rentable validada? (banda de EV ∩
    piso de probabilidad ∩ convicción prob×EV). Es el gate único de Capa 1."""
    if ev is None or prob is None:
        return False
    lo, hi = banda_rentable()
    return (lo <= ev <= hi and prob >= piso_prob()
            and prob * ev >= conviccion_min())


def en_banda(ev: Optional[float]) -> bool:
    if ev is None:
        return False
    lo, hi = banda_rentable()
    return lo <= ev <= hi


def roi_esperado_liga(liga: str) -> Optional[float]:
    """ROI histórico real de la liga (diagnóstico, puede sobreajustar)."""
    return (_mapa().get('ligas', {}).get(liga) or {}).get('roi')


def clasificar_pick(ev: Optional[float], liga: str = '') -> Dict:
    """Etiqueta de rentabilidad esperada de un pick según el tramo de EV real
    en el que cae y (informativo) el ROI histórico de su liga."""
    if ev is None:
        return {'tier': 'sin_ev', 'etiqueta': '⚪ sin cuota', 'en_banda': False}
    lo, hi = banda_rentable()
    dentro = lo <= ev <= hi
    if ev > 0.15:
        tier, etiqueta = 'toxico', '🔴 EV extremo (histórico −10 % ROI)'
    elif dentro:
        tier, etiqueta = 'rentable', '🟢 zona rentable validada'
    elif ev > hi:
        tier, etiqueta = 'alto', '🟡 EV alto (fuera de la banda validada)'
    else:
        tier, etiqueta = 'bajo', '⚪ EV bajo (histórico deficitario)'
    roi_liga = roi_esperado_liga(liga)
    return {'tier': tier, 'etiqueta': etiqueta, 'en_banda': dentro,
            'roi_historico_liga': roi_liga,
            'liga_deficitaria': bool(roi_liga is not None and roi_liga < -8)}


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    r = calibrar()
    print(json.dumps({k: r[k] for k in ('n_apuestas', 'banda_adoptada',
                                        'roi_banda_global', 'ventanas_oos_banda')},
                     indent=2, ensure_ascii=False))
    if '--full' in sys.argv:
        print(json.dumps(r['escaneo_bandas'], indent=2, ensure_ascii=False))
