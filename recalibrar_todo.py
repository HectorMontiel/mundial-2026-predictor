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

    1. build_pick_ledger     ← re-predice el fútbol con los modelos de HOY
       build_ledger_deportes ← y el tenis y el MLB
       build_ledger_total    ← junta los dos (esto es lo único que corría)
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


# Un ledger que sale con menos de esta fracción de las filas que tenía es
# una descarga a medias, no una temporada que encogió. Misma guarda y mismo
# motivo que `league_engine._guardar_historico`.
ENCOGIMIENTO_MAXIMO = 0.30


def _filas(ruta: str):
    import os
    if not os.path.exists(ruta):
        return None
    try:
        import pandas as pd
        return len(pd.read_csv(ruta, usecols=[0], low_memory=False))
    except Exception:
        return None


def _rehacer(etiqueta: str, modulo, temporal: str) -> str:
    """
    Reconstruye un ledger EN UN FICHERO APARTE y sólo sustituye al bueno si
    sale sano.

    Sin esto, un `construir()` que se queda a medias —una liga cuyo histórico
    no se descargó, una fuente caída— escribe igualmente su resultado corto
    encima del ledger anterior, y toda la cadena que cuelga de él se recalibra
    con menos partidos sin que nada lo diga. Es exactamente lo que ya pasó con
    `historico_champions.csv`: 53.264 filas encima de 895, sin un aviso.
    """
    import os

    csv_bueno, meta_buena = modulo.SALIDA_CSV, modulo.SALIDA_META
    antes = _filas(csv_bueno)
    modulo.SALIDA_CSV = temporal
    modulo.SALIDA_META = temporal.replace('.csv', '.json')
    try:
        df = modulo.construir()
    finally:
        modulo.SALIDA_CSV, modulo.SALIDA_META = csv_bueno, meta_buena

    ahora = len(df)
    if antes and ahora < antes * (1.0 - ENCOGIMIENTO_MAXIMO):
        for f in (temporal, temporal.replace('.csv', '.json')):
            if os.path.exists(f):
                os.remove(f)
        raise RuntimeError(
            '%s salio con %d filas y tenia %d (-%.0f%%): se conserva el '
            'anterior' % (etiqueta, ahora, antes,
                          100.0 * (1 - ahora / float(antes))))

    os.replace(temporal, csv_bueno)
    tmp_meta = temporal.replace('.csv', '.json')
    if os.path.exists(tmp_meta):
        os.replace(tmp_meta, meta_buena)
    return '%s: %d filas (%+d)' % (etiqueta, ahora,
                                   ahora - (antes or 0))


def _ledger() -> str:
    """
    v189 — ESTE PASO DECIA RE-PREDECIR Y SOLO CONCATENABA.

    El encabezado de este modulo describe el paso 1 como «re-predice el
    historico con los modelos de HOY» y calcula que cuesta unos 40 minutos;
    por ese coste la recalibracion se dejo semanal en vez de diaria.

    **Ese coste no se pagaba nunca.** `build_ledger_total.construir()` no
    re-predice nada: junta `pick_ledger.csv` y `pick_ledger_deportes.csv`, que
    los escriben otros dos modulos, y a los que no llamaba nadie. La pasada
    semanal terminaba en 7 min y volvia a producir, byte a byte, el mismo
    fichero.

    Consecuencia, medida el 2026-09-09: `pick_ledger.csv` seguia generado el
    2026-07-28 —lo dice su propio `_v75_pick_ledger.json`—, o sea que durante
    seis semanas la cadena entera se recalibro sobre partidos de julio. Y como
    salia identico, no habia diff, no habia commit, y el workflow terminaba en
    verde cada lunes. Los cuatro ficheros que no se actualizaban no eran cuatro
    fallos: eran este.

    Ahora el paso reconstruye los dos ledgers de origen y DESPUES concatena.
    Cada uno por separado: si el de futbol falla, el de deportes se rehace
    igual y el total se arma con el futbol anterior, que es viejo pero existe.
    """
    import build_ledger_deportes
    import build_ledger_total
    import build_pick_ledger

    notas, fallos = [], []
    for etiqueta, modulo, temporal in (
            ('futbol', build_pick_ledger, '_pick_ledger.nuevo.csv'),
            ('deportes', build_ledger_deportes,
             '_pick_ledger_deportes.nuevo.csv')):
        try:
            notas.append(_rehacer(etiqueta, modulo, temporal))
        except Exception as e:
            fallos.append('%s: %s' % (etiqueta, e))
            logger.warning('[ledger/%s] no se rehizo: %s', etiqueta, e)

    df = build_ledger_total.construir()
    notas.append('total: %d filas' % len(df))
    if fallos:
        notas.append('SIN REHACER -> ' + '; '.join(fallos))
    return ' | '.join(notas)


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


def _autopsia() -> str:
    """v101 — dónde falla el sistema de forma sistemática."""
    import autopsia
    r = autopsia.autopsia_produccion()
    g = r.get('global') or {}
    if not g:
        return r.get('aviso', 'sin picks liquidados')
    return (f"{g['n']} picks liquidados · acierto {g['acierto_real']:.1%} vs "
            f"prometido {g['prob_prometida']:.1%} · brecha {g['brecha']:+.1%} · "
            f"{r.get('lecciones', 0)} segmento(s) con brecha significativa")


def _aprender() -> str:
    """v101 — reaprende el mapa de calibración adaptativa."""
    import aprendizaje_continuo as ac
    s = ac.reaprender()
    return (f"{len(s['mapa'])} nodos · fuentes {s['fuentes']} · "
            f"n global {s['n_total']}")


PASOS = [
    ('1. ledger (re-predice el histórico con los modelos de hoy)', _ledger),
    ('2. calibración de confianza (acierto real por banda)', _confianza),
    ('3. techo de acierto por liga', _precision_ligas),
    ('4. banda de EV rentable', _edge),
    ('5. qué deportes tienen edge validado', _deportes),
    ('6. peso del encogimiento al mercado', _peso_mercado),
    # --- v101: el lazo que aprende de sus propios resultados ---------------
    # Va AL FINAL a propósito. Los pasos 1-6 miden el modelo contra el
    # histórico; éstos dos lo miden contra lo que de verdad se publicó y ya se
    # liquidó, que es la única fuente que incluye los filtros, la Capa 2 y el
    # line shopping. La autopsia diagnostica y el aprendizaje corrige, en ese
    # orden: sin el diagnóstico, la corrección no sabría dónde hace falta.
    ('7. autopsia de los picks publicados', _autopsia),
    ('8. calibración adaptativa (aprende de lo liquidado)', _aprender),
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
