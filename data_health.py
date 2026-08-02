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

DB_ODDS = 'odds_historico.db'
# umbrales
MIN_CUOTAS_SANO = 10          # menos que esto en temporada activa = sospechoso
HORAS_FRESCURA = 18           # snapshots más viejos que esto = obsoleto


def _ultima_captura() -> Dict:
    """Última foto registrada en odds_historico.db (fuente + antigüedad).
    v89: se lee `historical_odds` fase='snapshot' (daily_snapshots) — la
    tabla `snapshots` de la v43 murió con The Odds API en la v88."""
    if not os.path.exists(DB_ODDS):
        return {'existe': False}
    try:
        con = sqlite3.connect(DB_ODDS)
        row = con.execute("SELECT MAX(ingested_at), COUNT(*) "
                          "FROM historical_odds WHERE fase='snapshot'").fetchone()
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
    """Diagnóstico completo de la llegada de datos. Nunca lanza.

    v89 — el diagnóstico giraba alrededor de ODDS_API_KEY y de
    `odds_actuales.json`, que son de The Odds API, RETIRADA en la v88. Contar
    un fichero que ya nada escribe podía inflar el número con cuotas rancias,
    y «sin clave» señalaba como causa una clave que ya no se usa. Las fuentes
    reales de la app son Pinnacle, Bovada, Playdoit y ESPN (cuotas_multi),
    todas sin clave ni límite: el diagnóstico mide eso.
    """
    det: List[str] = []
    nivel = 'ok'
    captura = _ultima_captura()

    n_cuotas = 0
    detalle_multi = {}
    try:
        import cuotas_multi as _cm
        detalle_multi = _cm.diagnostico()
        n_cuotas = sum(detalle_multi.values())
    except Exception:
        pass

    if n_cuotas == 0:
        horas = captura.get('horas_desde')
        if horas is not None and horas > HORAS_FRESCURA:
            nivel = 'critico'
            det.append(f"❌ 0 cuotas vigentes y la última captura fue hace "
                       f"{horas:.0f} h: las fuentes pueden estar caídas.")
        else:
            nivel = 'degradado'
            det.append("⚠️ 0 cuotas vigentes ahora mismo con captura reciente "
                       "→ probable parón de calendario, no un fallo de datos.")
    elif n_cuotas < MIN_CUOTAS_SANO:
        nivel = 'degradado'
        det.append(f"⚠️ Solo {n_cuotas} cuotas vigentes (poca cobertura hoy).")
    else:
        det.append(f"✅ {n_cuotas} partidos con cuota de fuentes sin límite "
                   f"(Pinnacle + Bovada + Playdoit): "
                   + ' · '.join(f'{k} {v}' for k, v in detalle_multi.items()
                                if v))

    if captura.get('existe') and captura.get('horas_desde') is not None:
        h = captura['horas_desde']
        det.append(f"{'✅' if h <= HORAS_FRESCURA else '⚠️'} Última foto de la "
                   f"línea hace {h:.0f} h "
                   f"({captura.get('total_snapshots')} fotos acumuladas).")
    elif not captura.get('existe'):
        det.append("ℹ️ Sin odds_historico.db (disco efímero del cloud entre "
                   "despliegues) — normal salvo que persista tras el pipeline.")

    alarma = None
    if nivel == 'critico':
        alarma = ("🚨 ALERTA DE DATOS: no están llegando cuotas de ninguna "
                  "fuente (Pinnacle/Bovada/Playdoit/ESPN caídas o bloqueadas). "
                  "Los picks de hoy pueden estar incompletos.")
    return {'nivel': nivel, 'ok': nivel == 'ok',
            'cuotas_vigentes': n_cuotas, 'captura': captura,
            'detalles': det, 'alarma': alarma}


def linea_alarma_telegram() -> str:
    """Línea de alarma para anteponer al resumen de Telegram (vacía si ok)."""
    e = estado_datos()
    return (e['alarma'] + "\n\n") if e.get('alarma') else ""


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(estado_datos(), indent=2, ensure_ascii=False))
