#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v93 — Recalibra TODA la cadena con los partidos que ya se jugaron.

El agujero que tapa
-------------------
El workflow diario reentrena los modelos de fútbol y refresca `team_stats`,
así que las PREDICCIONES mejoran cada día. Pero las CALIBRACIONES que
corrigen esas predicciones estaban congeladas en el día en que alguien las
generó a mano. Auditado el 2026-08-03:

    artefacto                     edad   ¿lo regenera el workflow?
    modelos de fútbol               1 d   SÍ
    team_stats_*.json               1 d   SÍ
    calibracion_mercado.json        1 d   SÍ
    ─────────────────────────────────────────────────────────────
    pick_ledger_total.csv           5 d   ❌ NUNCA
    calibracion_confianza.json      3 d   ❌ NUNCA
    umbrales_capa1.json             6 d   ❌ NUNCA
    edge_map.json                  11 d   ❌ NUNCA
    precision_ligas.json            1 d   ❌ NUNCA
    deportes_capa1.json               —   ❌ NUNCA

Y hay una inconsistencia peor que la antigüedad: **la corrección que se aplica
describe el comportamiento de un modelo que ya no existe**. `calibracion_
confianza` mide cuánto acierta de verdad cada banda de probabilidad; si el
modelo se reentrena a diario y esa medición no, se está corrigiendo con la
huella de un modelo de hace días. Lo mismo con la banda de EV rentable
(`edge_map`) y con los umbrales de Capa 1.

El orden importa
----------------
Todo cuelga del ledger, así que la cadena es estrictamente secuencial:

    1. build_ledger_total     ← re-predice el histórico con los modelos de HOY
    2. calibracion_confianza  ← acierto real por banda y mercado
    3. precision_ligas        ← techo de acierto de cada competición
    4. edge_engine            ← banda de EV rentable (maximin + bootstrap)
    5. validacion_deportes    ← qué deportes entran en la Capa 1
    6. recalibrate_from_history ← el peso w del encogimiento al mercado

Cada paso es independiente en su fallo: si uno revienta, se anota y los demás
siguen. Un artefacto viejo es peor que uno nuevo, pero MUCHO mejor que ninguno
— y el que no se regenere conserva el anterior, nunca se queda a medias.

Cuánto cuesta
-------------
El paso 1 re-predice decenas de miles de partidos y es el caro (~40 min). Por
eso esto NO va en el workflow diario sino en uno semanal: las calibraciones se
mueven despacio y reconstruirlas a diario sería gastar una hora de CI para
cambiar el cuarto decimal.

Uso:
    python recalibrar_todo.py              # cadena completa
    python recalibrar_todo.py --sin-ledger # sólo lo que cuelga del ledger ya hecho
"""
import argparse
import json
import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

SALIDA = 'recalibracion_estado.json'


def _paso(nombre: str, fn) -> Dict:
    """Ejecuta un paso y devuelve su resultado sin dejar caer la cadena."""
    t0 = time.time()
    try:
        detalle = fn()
        dt = time.time() - t0
        logger.info(f'✅ {nombre} ({dt:.0f}s)')
        return {'paso': nombre, 'ok': True, 'segundos': round(dt, 1),
                'detalle': detalle}
    except Exception as e:
        dt = time.time() - t0
        logger.warning(f'❌ {nombre}: {type(e).__name__}: {e}')
        return {'paso': nombre, 'ok': False, 'segundos': round(dt, 1),
                'error': f'{type(e).__name__}: {e}'}


def _ledger() -> str:
    import build_ledger_total
    df = build_ledger_total.construir()
    return f'{len(df)} filas'


def _confianza() -> str:
    import calibracion_confianza as cc
    r = cc.calcular()
    return (f"{r['n_total']} predicciones medidas · umbral "
            f"{r['umbral_recomendado']:.2f}")


def _precision_ligas() -> str:
    import precision_ligas
    r = precision_ligas.generar()
    return (f"{len(r.get('ligas') or {})} ligas · correlación "
            f"{r.get('correlacion_mitades')} · "
            f"{'publicado' if r.get('estable') else 'NO publicado (inestable)'}")


def _edge() -> str:
    import edge_engine
    edge_engine.calibrar(guardar=True)
    import importlib
    importlib.reload(edge_engine)
    lo, hi = edge_engine.banda_rentable()
    return (f'banda EV [{lo:.3f}, {hi:.3f}] · piso de probabilidad '
            f'{edge_engine.piso_prob():.2f}')


def _deportes() -> str:
    import validacion_deportes as vd
    r = vd.calcular()
    dentro = [d for d, v in (r.get('deportes') or {}).items()
              if v.get('edge_validado')]
    return f'con edge validado: {dentro or "ninguno"}'


def _peso_mercado() -> str:
    import recalibrate_from_history as rh
    d = rh.analizar(rh.LEDGER)
    v = d.get('validacion') or {}
    return (f"w global {d.get('w_global')} · {d.get('ligas_adoptadas')} ligas "
            f"adoptadas · log-loss {v.get('delta_logloss')}")


PASOS = [
    ('1. ledger (re-predice el histórico con los modelos de hoy)', _ledger),
    ('2. calibración de confianza (acierto real por banda)', _confianza),
    ('3. techo de acierto por liga', _precision_ligas),
    ('4. banda de EV rentable', _edge),
    ('5. qué deportes tienen edge validado', _deportes),
    ('6. peso del encogimiento al mercado', _peso_mercado),
]


def recalibrar(sin_ledger: bool = False) -> Dict:
    """Ejecuta la cadena completa. Nunca lanza: informa de lo que falló."""
    import pandas as pd
    pasos = PASOS[1:] if sin_ledger else PASOS
    resultados: List[Dict] = [_paso(n, f) for n, f in pasos]
    doc = {
        'generado': pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'pasos': resultados,
        'ok': sum(1 for r in resultados if r['ok']),
        'fallos': [r['paso'] for r in resultados if not r['ok']],
        'segundos_total': round(sum(r['segundos'] for r in resultados), 1),
    }
    try:
        from io_atomico import escribir_json
        escribir_json(SALIDA, doc, indent=1)
    except Exception:
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--sin-ledger', action='store_true',
                    help='salta la reconstrucción del ledger (usa el que hay)')
    a = ap.parse_args()
    d = recalibrar(a.sin_ledger)
    print(f"\n{d['ok']}/{len(d['pasos'])} pasos OK en {d['segundos_total']:.0f}s")
    for p in d['pasos']:
        print(f"  {'✅' if p['ok'] else '❌'} {p['paso']}")
        print(f"      {p.get('detalle') or p.get('error')}")
    sys.exit(0 if not d['fallos'] else 1)
