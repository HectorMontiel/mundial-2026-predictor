#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v71 — Reentrena las ligas que el bug de julio dejaba con datos viejos.

Por qué hace falta un paso aparte
---------------------------------
Arreglar `uefa_scraper` corrige la DESCARGA, pero los ficheros que la app lee
—`historico_<liga>.csv` y sobre todo `team_stats_<liga>.json`— solo se
reescriben al entrenar. Y es `team_stats_*.json` quien guarda
`ultima_fecha_historico`, que es de donde `alpha_finder` saca el aviso
«🔴 sin datos nuevos desde hace N d» y la cuarentena de pretemporada que baja
los picks a Capa 2.

Es decir: sin este paso el código está bien pero la app sigue enseñando el
aviso falso y penalizando picks que no lo merecen.

Medido antes de correr esto (`_v71_recuperacion_julio.json`): 21 ligas con
partidos recuperados, **2.925 partidos** en total, y **15 ligas** cuya fecha
más reciente estaba mal.

Salida: `_v71_reentrenamiento_julio.json`
"""
import json
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v71_reentrenamiento_julio.json'
ENTRADA = '_v71_recuperacion_julio.json'


def ligas_afectadas():
    """Las que ganaron partidos al arreglar el salto de julio."""
    if not os.path.exists(ENTRADA):
        raise FileNotFoundError(f'falta {ENTRADA}')
    with open(ENTRADA, encoding='utf-8') as f:
        datos = json.load(f)
    out = []
    for r in datos:
        if not (r.get('antes') and r.get('ahora')):
            continue
        if r['ahora'][0] > r['antes'][0]:
            out.append({'clave': r['clave'], 'antes': r['antes'],
                        'esperado': r['ahora']})
    # primero las que tenían la fecha reciente mal: son las del aviso falso
    out.sort(key=lambda x: (x['antes'][1] == x['esperado'][1],
                            -(x['esperado'][0] - x['antes'][0])))
    return out


def main():
    import league_engine as le
    afectadas = ligas_afectadas()
    logger.info(f"Reentrenando {len(afectadas)} ligas afectadas por el salto "
                f"de julio")
    resultados = []
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding='utf-8') as f:
            hechas = {r['clave'] for r in json.load(f) if r.get('estado') == 'ok'}
        with open(SALIDA, encoding='utf-8') as f:
            resultados = json.load(f)
    else:
        hechas = set()

    for i, item in enumerate(afectadas, 1):
        clave = item['clave']
        if clave in hechas:
            logger.info(f"[{i}/{len(afectadas)}] {clave}: ya hecha, se salta")
            continue
        logger.info(f"[{i}/{len(afectadas)}] {clave} "
                    f"({item['antes'][1]} → {item['esperado'][1]})")
        t0 = time.time()
        try:
            md = le.entrenar_liga(clave)
            fila = {'clave': clave, 'estado': 'ok',
                    'fecha_antes': item['antes'][1],
                    'fecha_ahora': item['esperado'][1],
                    'partidos_antes': item['antes'][0],
                    'partidos_ahora': item['esperado'][0],
                    'precision': md.get('precision_validacion'),
                    'elo': md.get('precision_linea_base_elo'),
                    'familia': md.get('familia_modelo'),
                    'segundos': round(time.time() - t0, 1)}
            logger.info(f"    acc={fila['precision']} (elo {fila['elo']}) "
                        f"[{fila['familia']}]")
        except Exception as e:
            fila = {'clave': clave, 'estado': 'error',
                    'detalle': f'{type(e).__name__}: {e}',
                    'segundos': round(time.time() - t0, 1)}
            logger.error(f"    falló: {fila['detalle']}")
        resultados = [r for r in resultados if r['clave'] != clave] + [fila]
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)

    ok = [r for r in resultados if r['estado'] == 'ok']
    logger.info(f"== {len(ok)}/{len(resultados)} reentrenadas")
    # comprobación final: ¿queda alguna con el aviso de datos viejos?
    import pandas as pd
    hoy = pd.Timestamp.today()
    viejas = []
    for r in ok:
        ruta = f"team_stats_{r['clave']}.json"
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding='utf-8') as f:
            u = json.load(f).get('ultima_fecha_historico')
        if u:
            d = (hoy - pd.Timestamp(u)).days
            if d > 30:
                viejas.append((r['clave'], u, d))
    if viejas:
        logger.info("Ligas que SIGUEN con estado antiguo (parón real, no bug):")
        for c, u, d in sorted(viejas, key=lambda x: -x[2]):
            logger.info(f"   {c:24s} último {u} ({d} d)")
    else:
        logger.info("Ninguna liga reentrenada queda con estado antiguo.")


if __name__ == '__main__':
    main()
