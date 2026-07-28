#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v74 — Reentrena las ligas cuyo estado va por detrás de su fuente.

El workflow diario (v74) mantiene esto al día por sí solo a partir de ahora;
este script existe para no esperar al próximo cron y para poder forzar el
refresco cuando haga falta.

Selecciona por comparación real: descarga la liga (que ya incluye la cola de
ESPN de `_completar_desde_espn`) y la reentrena solo si trae partidos más
recientes que los que tiene el estado guardado. Así no se malgasta cómputo en
las ligas en receso, que es lo correcto y lo honesto.

Salida: `_v74_refresco.json`
"""
import json
import logging
import os
import time

import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v74_refresco.json'


def estado_actual(clave: str):
    ruta = f'team_stats_{clave}.json'
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding='utf-8') as f:
            return json.load(f).get('ultima_fecha_historico')
    except Exception:
        return None


def main(solo=None, minimo_dias=1):
    import config
    import league_engine as le

    claves = [solo] if solo else [c for c, cfg in config.LEAGUES.items()
                                  if cfg.get('disponible')
                                  and cfg.get('formato') in ('main', 'new', 'espn')]
    hoy = pd.Timestamp.today().normalize()
    resultados = []
    logger.info(f"Revisando {len(claves)} competiciones")

    for i, clave in enumerate(claves, 1):
        est = estado_actual(clave)
        try:
            df = le.descargar_liga(clave)
        except Exception as e:
            logger.warning(f"[{i}/{len(claves)}] {clave}: descarga falló "
                           f"({type(e).__name__}: {e})")
            resultados.append({'clave': clave, 'estado': 'error_descarga',
                               'detalle': str(e)[:120]})
            continue
        if df.empty:
            continue
        fuente = pd.Timestamp(df['date'].max()).normalize()
        desfase = (fuente - pd.Timestamp(est)).days if est else 999
        if desfase < minimo_dias:
            resultados.append({'clave': clave, 'estado': 'al_dia',
                               'estado_previo': est,
                               'fuente': str(fuente.date())})
            continue
        logger.info(f"[{i}/{len(claves)}] {clave}: estado {est} → fuente "
                    f"{fuente.date()} ({desfase} d) — reentrenando")
        t0 = time.time()
        try:
            md = le.entrenar_liga(clave)
            fila = {'clave': clave, 'estado': 'reentrenada',
                    'estado_previo': est, 'estado_nuevo': str(fuente.date()),
                    'dias_recuperados': desfase,
                    'precision': md.get('precision_validacion'),
                    'elo': md.get('precision_linea_base_elo'),
                    'familia': md.get('familia_modelo'),
                    'segundos': round(time.time() - t0, 1)}
            logger.info(f"     acc={fila['precision']} (elo {fila['elo']}) "
                        f"[{fila['familia']}] en {fila['segundos']}s")
        except Exception as e:
            fila = {'clave': clave, 'estado': 'error_entrenamiento',
                    'detalle': f'{type(e).__name__}: {e}'[:140]}
            logger.warning(f"     falló: {fila['detalle']}")
        resultados.append(fila)
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)

    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1)
    ok = [r for r in resultados if r['estado'] == 'reentrenada']
    dia = [r for r in resultados if r['estado'] == 'al_dia']
    logger.info(f"== {len(ok)} reentrenadas · {len(dia)} ya al día · "
                f"{len(resultados) - len(ok) - len(dia)} con error")
    for r in sorted(ok, key=lambda x: -(x.get('dias_recuperados') or 0)):
        logger.info(f"   {r['clave']:22s} {r['estado_previo']} → "
                    f"{r['estado_nuevo']}  (+{r['dias_recuperados']} d)")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo', default=None)
    a = ap.parse_args()
    main(solo=a.solo)
