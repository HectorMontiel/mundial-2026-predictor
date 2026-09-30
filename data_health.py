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


def _precios_publicados() -> Dict:
    """v315 — LO QUE LA APLICACIÓN USA DE VERDAD: los precios que trae el
    precálculo del cron (`pronostico_dia.json`) y el tablero de casas
    (`cuotas_mx.json`), con su edad. Nada de red.

    El 2026-09-29 la pantalla gritó «🚨 no están llegando cuotas de ninguna
    fuente» con precios de hace hora y media en la misma pantalla. La cuenta
    salía de `cuotas_multi.diagnostico()`, que pide Pinnacle EN VIVO desde el
    servidor de Streamlit Cloud: ese servidor ya no recibe respuesta de
    Pinnacle (desde un equipo normal devuelve 648 partidos), y además pedirla
    al pintar es justo lo que la v220 sacó del render. La aplicación no usa
    esa petición para nada: sus precios llegan en el precálculo."""
    out = {}
    for nombre, ruta in (('precalculo', 'pronostico_dia.json'),
                         ('tablero', 'cuotas_mx.json')):
        try:
            if not os.path.exists(ruta):
                continue
            with open(ruta, encoding='utf-8') as f:
                doc = json.load(f) or {}
            gen = doc.get('generado_ts') or doc.get('generado')
            ts = (pd.Timestamp(float(gen), unit='s', tz='UTC')
                  if isinstance(gen, (int, float)) else
                  pd.to_datetime(gen, errors='coerce', utc=True))
            if nombre == 'precalculo':
                dat = doc.get('datos') or doc
                n = sum(1 for p in (dat.get('pronosticos') or [])
                        if isinstance(p, dict) and p.get('cuota'))
                n += len(dat.get('solo_mercado') or [])
            else:
                n = len(doc.get('partidos') or {})
            horas = ((pd.Timestamp.now('UTC') - ts).total_seconds() / 3600
                     if ts is not None and not pd.isna(ts) else None)
            out[nombre] = {'n': int(n),
                           'horas': round(horas, 1) if horas is not None else None}
        except Exception as e:
            logger.debug('[salud] %s: %s', ruta, e)
    return out


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
    publicados = _precios_publicados()
    if publicados:
        # v315 — los precios que la aplicación enseña, no una petición en vivo
        frescos = {k: v for k, v in publicados.items()
                   if v.get('horas') is not None and v['horas'] <= HORAS_FRESCURA}
        n_cuotas = sum(v['n'] for v in frescos.values())
        detalle_multi = {k: v['n'] for k, v in frescos.items()}
        if n_cuotas == 0:
            edades = [v['horas'] for v in publicados.values()
                      if v.get('horas') is not None]
            captura = {'existe': True, 'horas_desde': min(edades) if edades else None,
                       'total_snapshots': sum(v['n'] for v in publicados.values())}
    else:
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
        det.append(f"✅ {n_cuotas} precios vigentes: "
                   + ' · '.join(f'{k} {v}' for k, v in detalle_multi.items()
                                if v))

    # v315 — la base de fotos de línea sólo la mantiene el pipeline; en el
    # servidor de la aplicación es una copia vieja y no dice nada de los
    # precios que se enseñan. Se nombra sólo cuando no hay precálculo.
    if publicados:
        pass
    elif captura.get('existe') and captura.get('horas_desde') is not None:
        h = captura['horas_desde']
        det.append(f"{'✅' if h <= HORAS_FRESCURA else '⚠️'} Última foto de la "
                   f"línea hace {h:.0f} h "
                   f"({captura.get('total_snapshots')} fotos acumuladas).")
    elif not captura.get('existe'):
        det.append("ℹ️ Sin odds_historico.db (disco efímero del cloud entre "
                   "despliegues) — normal salvo que persista tras el pipeline.")

    alarma = None
    if nivel == 'critico':
        alarma = ("🚨 ALERTA DE DATOS: el precálculo no trae precios de hace "
                  "menos de %d h (las casas o el cron pueden estar caídos). "
                  "Los picks de hoy pueden estar incompletos." % HORAS_FRESCURA)
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
