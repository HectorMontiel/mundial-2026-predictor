#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de salud de datos (v41) — "que NO vuelva a pasar que no llegan datos
y no nos demos cuenta".

El fallo del 2026-07-24 (runner sin ODDS_API_KEY → 0 cuotas → capa1=0 →
mensaje vacío) no se detectó porque el sistema trataba "no llegaron datos"
igual que "llegaron datos pero hoy no hay picks". Son cosas MUY distintas:
  · Sin datos  = PROBLEMA (clave ausente, fuente caída, rate-limit) → ALARMA.
  · Con datos y sin picks = NORMAL (disciplina: no forzar apuestas flojas).

Este módulo audita la llegada de datos y devuelve un diagnóstico con nivel
(ok / degradado / critico) y una alarma legible. bot_telegram lo antepone al
resumen y el dashboard lo muestra como banner. NUNCA lanza excepción.
"""

import json
import logging
import os
import sqlite3
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

ODDS_ACTUALES = 'odds_actuales.json'
DB_ODDS = 'odds_historico.db'
# umbrales
MIN_CUOTAS_SANO = 10          # menos que esto en temporada activa = sospechoso
HORAS_FRESCURA = 18           # snapshots más viejos que esto = obsoleto


def _clave_odds_presente() -> bool:
    if os.getenv('ODDS_API_KEY'):
        return True
    try:
        import tomllib
        with open('.streamlit/secrets.toml', 'rb') as f:
            return bool(tomllib.load(f).get('ODDS_API_KEY'))
    except Exception:
        return False


def _cuotas_actuales() -> int:
    try:
        with open(ODDS_ACTUALES, encoding='utf-8') as f:
            return len(json.load(f).get('cuotas', {}))
    except Exception:
        return 0


def _ultima_captura() -> Dict:
    """Última captura registrada en odds_historico.db (fuente + antigüedad)."""
    if not os.path.exists(DB_ODDS):
        return {'existe': False}
    try:
        con = sqlite3.connect(DB_ODDS)
        row = con.execute("SELECT MAX(capturado_utc), COUNT(*) FROM snapshots").fetchone()
        con.close()
    except Exception as e:
        return {'existe': False, 'error': str(e)}
    if not row or not row[0]:
        return {'existe': True, 'vacio': True}
    ult = pd.to_datetime(row[0], errors='coerce', utc=True)
    horas = (pd.Timestamp.now('UTC') - ult).total_seconds() / 3600 if ult is not None else None
    return {'existe': True, 'ultima_utc': str(row[0]), 'total_snapshots': int(row[1]),
            'horas_desde': round(horas, 1) if horas is not None else None}


def estado_datos() -> Dict:
    """Diagnóstico completo de la llegada de datos. Nunca lanza."""
    det: List[str] = []
    nivel = 'ok'
    clave = _clave_odds_presente()
    n_cuotas = _cuotas_actuales()
    captura = _ultima_captura()

    if not clave:
        nivel = 'critico'
        det.append("❌ ODDS_API_KEY AUSENTE — sin ella no se capturan cuotas en "
                    "vivo (revisa los Secrets del repo / la variable de entorno).")
    if n_cuotas == 0:
        # sin cuotas: crítico si además no hay clave o la captura es vieja
        horas = captura.get('horas_desde')
        if not clave:
            nivel = 'critico'
            det.append("❌ 0 cuotas vigentes y sin clave: NO están llegando datos.")
        elif horas is not None and horas > HORAS_FRESCURA:
            nivel = 'critico' if nivel != 'critico' else nivel
            det.append(f"❌ 0 cuotas vigentes y la última captura fue hace "
                       f"{horas:.0f} h: la fuente puede estar caída o rate-limited.")
        else:
            # clave ok y captura reciente pero 0 vigentes → probable parón de
            # temporada (no es un fallo del sistema)
            if nivel == 'ok':
                nivel = 'degradado'
            det.append("⚠️ 0 cuotas vigentes ahora mismo, pero la clave está y la "
                       "captura es reciente → probable parón de calendario, no un "
                       "fallo de datos.")
    elif n_cuotas < MIN_CUOTAS_SANO:
        if nivel == 'ok':
            nivel = 'degradado'
        det.append(f"⚠️ Solo {n_cuotas} cuotas vigentes (poca cobertura hoy).")
    else:
        det.append(f"✅ {n_cuotas} cuotas vigentes.")

    if captura.get('existe') and captura.get('horas_desde') is not None:
        h = captura['horas_desde']
        det.append(f"{'✅' if h <= HORAS_FRESCURA else '⚠️'} Última captura hace "
                   f"{h:.0f} h ({captura.get('total_snapshots')} snapshots totales).")
    elif not captura.get('existe'):
        det.append("ℹ️ Sin odds_historico.db (disco efímero del cloud entre "
                   "despliegues) — normal salvo que persista tras el pipeline.")

    alarma = None
    if nivel == 'critico':
        alarma = ("🚨 ALERTA DE DATOS: no están llegando cuotas. Causa probable: "
                  + ("falta ODDS_API_KEY. " if not clave else "fuente caída / "
                     "rate-limit. ") + "Los picks de hoy pueden estar incompletos.")
    return {'nivel': nivel, 'ok': nivel == 'ok', 'clave_odds': clave,
            'cuotas_vigentes': n_cuotas, 'captura': captura,
            'detalles': det, 'alarma': alarma}


def linea_alarma_telegram() -> str:
    """Línea de alarma para anteponer al resumen de Telegram (vacía si ok)."""
    e = estado_datos()
    return (e['alarma'] + "\n\n") if e.get('alarma') else ""


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(estado_datos(), indent=2, ensure_ascii=False))
