#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLV Tracker (v38) — Closing Line Value como métrica REY de rentabilidad.

## Por qué el CLV es la brújula
Batir de forma consistente la línea de cierre (la cuota justo antes del
partido, cuando el mercado ya incorporó toda la información) es el ÚNICO
predictor empíricamente robusto del beneficio a largo plazo en apuestas: si
apuestas a mejor precio que el cierre, tienes EV+ esperado aunque una racha de
resultados diga lo contrario. Es un indicador ADELANTADO — informa mucho antes
de que los resultados se acumulen.

## El diagnóstico que lo motiva
Sobre 1.174 apuestas históricas con cuota de cierre de Pinnacle registrada:
  · CLV medio = −2.53 %  → apostamos SISTEMÁTICAMENTE a peor precio que el
    cierre. Ésa es la raíz del ROI negativo, no la mala suerte.
  · Solo batimos el cierre el 15 % de las veces.
  · Cuando SÍ lo batimos: ROI −0.66 % (casi break-even).
  · Cuando NO: ROI −6.9 %.
El CLV discrimina el ROI de forma brutal. Objetivo de la plataforma: subir el
CLV medio hacia 0 y por encima.

## Qué mide este módulo
1. CLV histórico desde roi_bets (cuota apostada vs cuota_pin de cierre).
2. CLV reciente desde odds_historico.db (si hay snapshots): compara la primera
   cuota capturada de un partido con la última (proxy de línea de cierre).
"""

import glob
import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DB_ODDS = 'odds_historico.db'


def _cargar_apuestas() -> List[Dict]:
    filas = []
    for f in glob.glob('roi_bets_*.json'):
        liga = f.split('roi_bets_')[1].rsplit('.', 1)[0]
        try:
            for b in json.load(open(f, encoding='utf-8')):
                if b.get('cuota') and b.get('cuota_pin'):
                    b['liga'] = liga
                    filas.append(b)
        except Exception:
            continue
    return filas


def clv_historico() -> Dict:
    """CLV agregado desde roi_bets. El CLV de una apuesta = cuota/cuota_cierre−1
    (positivo = apostamos a mejor precio que el cierre)."""
    bs = _cargar_apuestas()
    if not bs:
        return {'n': 0, 'aviso': 'Sin apuestas con cuota de cierre registrada.'}
    clv = np.array([b['cuota'] / b['cuota_pin'] - 1 for b in bs])
    batidas = clv > 0

    def _roi(sub):
        if not sub:
            return None
        g = sum((b['cuota'] - 1) if b['gano'] else -1 for b in sub
                if b.get('gano') is not None)
        liq = [b for b in sub if b.get('gano') is not None]
        return round(100 * g / len(liq), 2) if liq else None

    return {
        'n': len(bs),
        'clv_medio_pct': round(float(clv.mean()) * 100, 2),
        'clv_mediano_pct': round(float(np.median(clv)) * 100, 2),
        'pct_batimos_cierre': round(float(batidas.mean()) * 100, 1),
        'roi_cuando_batimos': _roi([b for b, ok in zip(bs, batidas) if ok]),
        'roi_cuando_no': _roi([b for b, ok in zip(bs, batidas) if not ok]),
        'interpretacion': (
            'CLV medio positivo: vamos por delante del cierre (buena señal '
            'adelantada de rentabilidad).' if clv.mean() > 0 else
            'CLV medio NEGATIVO: apostamos a peor precio que el cierre — la '
            'causa estructural del ROI negativo. Prioridad: capturar cuotas '
            'antes y filtrar por la banda de EV validada (edge_engine).'),
    }


def clv_reciente(dias: int = 30) -> Dict:
    """CLV aproximado desde odds_historico.db: por partido, primera cuota
    capturada (nuestra "entrada") vs última (proxy del cierre). El DB es
    gitignored/efímero en cloud; si no existe, se informa sin romper."""
    if not os.path.exists(DB_ODDS):
        return {'n': 0, 'aviso': 'Sin odds_historico.db (snapshots CLV).'}
    try:
        con = sqlite3.connect(DB_ODDS)
        # esquema flexible: se intenta la forma conocida (match_id, mercado,
        # seleccion, cuota, capturado_utc)
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tablas = [r[0] for r in cur.fetchall()]
        if 'snapshots' not in tablas:
            con.close()
            return {'n': 0, 'aviso': f'odds_historico.db sin tabla snapshots '
                                     f'(tablas: {tablas}).'}
        import pandas as pd
        df = pd.read_sql_query("SELECT * FROM snapshots", con)
        con.close()
    except Exception as e:
        return {'n': 0, 'aviso': f'odds_historico.db ilegible: {e}'}
    if df.empty or 'match_id' not in df.columns:
        return {'n': 0, 'aviso': 'Snapshots insuficientes para CLV.'}
    col_t = next((c for c in ('capturado_utc', 'timestamp', 'ts', 'fecha')
                  if c in df.columns), None)
    col_c = next((c for c in ('cuota', 'odd', 'price') if c in df.columns), None)
    col_s = next((c for c in ('seleccion', 'sel', 'outcome') if c in df.columns), None)
    if not (col_t and col_c and col_s):
        return {'n': 0, 'aviso': 'Snapshots sin columnas de cuota/tiempo/selección.'}
    df = df.sort_values(col_t)
    clvs = []
    for (mid, sel), g in df.groupby(['match_id', col_s]):
        if len(g) < 2:
            continue
        entrada = float(g.iloc[0][col_c])
        cierre = float(g.iloc[-1][col_c])
        if entrada > 1 and cierre > 1:
            clvs.append(entrada / cierre - 1)
    if not clvs:
        return {'n': 0, 'aviso': 'Sin partidos con ≥2 snapshots para CLV.'}
    arr = np.array(clvs)
    return {'n': len(clvs), 'clv_medio_pct': round(float(arr.mean()) * 100, 2),
            'pct_positivo': round(float((arr > 0).mean()) * 100, 1)}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(json.dumps({'historico': clv_historico(), 'reciente': clv_reciente()},
                     indent=2, ensure_ascii=False))
