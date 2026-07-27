#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v68 — Entrena las competiciones nuevas y decide cuáles se despliegan.

Regla de adopción (la del proyecto desde v39, §2.2): una liga entra en la Capa 1
—y por tanto en Apuestas del Día— **sólo si su modelo bate a la línea base ELO**.
Si no, se queda entrenada (sirve para el explorador y la ficha de partido) pero
con `disponible: False`, para no meter picks deficitarios en el barrido.

Salida:
  · `modelos/<liga>/` con los artefactos de cada competición entrenada.
  · `_v68_entrenamiento.json` con el detalle de todas.
  · `config_ligas_espn.py` reescrito con el `disponible` que toca.

Uso:
    .venv\\Scripts\\python.exe entrenar_ligas_v68.py            # todas las nuevas
    .venv\\Scripts\\python.exe entrenar_ligas_v68.py --solo eng_championship
"""

import argparse
import json
import logging
import os
import re
import time
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

RESULTADOS = '_v68_entrenamiento.json'
CONFIG_LIGAS = 'config_ligas_espn.py'

# Margen exigido sobre el ELO. Cero sería "empatar con el ELO", que no aporta
# nada: se pide batirlo de verdad, aunque sea por poco.
MARGEN_ELO = 0.005


def entrenar_una(clave: str) -> Dict:
    from league_engine import entrenar_liga
    t0 = time.time()
    try:
        entrenar_liga(clave)
    except Exception as e:
        logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
        return {'clave': clave, 'estado': 'error',
                'detalle': f'{type(e).__name__}: {e}', 'segundos': round(time.time() - t0, 1)}
    ruta = os.path.join('modelos', clave, 'metadata.json')
    if not os.path.exists(ruta):
        return {'clave': clave, 'estado': 'sin_metadata',
                'segundos': round(time.time() - t0, 1)}
    with open(ruta, encoding='utf-8') as f:
        md = json.load(f)
    acc = md.get('precision_validacion')
    elo = md.get('precision_linea_base_elo')
    mkt = md.get('precision_mercado_cuotas')
    bate_elo = bool(acc is not None and elo is not None and acc >= elo + MARGEN_ELO)
    bate_mkt = bool(acc is not None and mkt is not None and acc > mkt)
    return {
        'clave': clave, 'estado': 'ok',
        'liga': md.get('liga'), 'n_train': md.get('n_train'),
        'n_validacion': md.get('n_validacion'),
        'precision': acc, 'elo': elo, 'mercado': mkt,
        'log_loss': md.get('log_loss_validacion'),
        'margen_elo': round(acc - elo, 4) if (acc is not None and elo is not None) else None,
        'bate_elo': bate_elo, 'bate_mercado': bate_mkt,
        'adoptada': bate_elo,
        'segundos': round(time.time() - t0, 1),
    }


def actualizar_disponibles(resultados: List[Dict], ruta: str = CONFIG_LIGAS) -> int:
    """Pone `disponible: True` sólo en las ligas que baten al ELO."""
    adoptadas = {r['clave'] for r in resultados if r.get('adoptada')}
    with open(ruta, encoding='utf-8') as f:
        texto = f.read()
    cambios = 0
    for clave in adoptadas:
        # Sustituye el `'disponible': False` del bloque de ESA liga
        patron = re.compile(
            r"(\{}\s*:\s*\{{.*?)'disponible':\s*False".format(re.escape(repr(clave))),
            re.S)
        texto, n = patron.subn(r"\1'disponible': True", texto, count=1)
        cambios += n
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(texto)
    return cambios


def main(solo: str = None) -> None:
    import config
    claves = list(config.LIGAS_V68_ANADIDAS)
    if solo:
        claves = [c for c in claves if c == solo]
    logger.info(f"Entrenando {len(claves)} competiciones nuevas...")
    resultados = []
    for i, clave in enumerate(claves, 1):
        cfg = config.LEAGUES[clave]
        logger.info(f"[{i}/{len(claves)}] {clave} ({cfg['formato']}) — {cfg['nombre']}")
        r = entrenar_una(clave)
        r['formato'] = cfg['formato']
        r['nombre'] = cfg['nombre']
        r['pais'] = cfg.get('pais')
        resultados.append(r)
        if r['estado'] == 'ok':
            logger.info(f"    acc={r['precision']} elo={r['elo']} mercado={r['mercado']} "
                        f"→ {'ADOPTADA' if r['adoptada'] else 'no supera al ELO'}")
        with open(RESULTADOS, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)

    ok = [r for r in resultados if r['estado'] == 'ok']
    adoptadas = [r for r in ok if r['adoptada']]
    cambios = actualizar_disponibles(resultados)
    logger.info(f"== RESUMEN: {len(ok)}/{len(resultados)} entrenadas · "
                f"{len(adoptadas)} adoptadas (baten al ELO) · "
                f"{sum(1 for r in ok if r['bate_mercado'])} baten también al mercado · "
                f"{cambios} marcadas disponibles en {CONFIG_LIGAS}")
    for r in sorted(adoptadas, key=lambda x: -(x['margen_elo'] or 0)):
        logger.info(f"   +{r['margen_elo']:.3f}  {r['clave']:24s} "
                    f"acc={r['precision']:.4f} (elo {r['elo']:.4f}) {r['nombre']}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo', type=str, default=None)
    a = ap.parse_args()
    main(a.solo)
