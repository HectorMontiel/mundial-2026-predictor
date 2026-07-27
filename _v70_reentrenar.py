#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 — Reentrena las ligas que cambian de familia de modelo y actualiza su
`disponible` en `config_ligas_espn.py` según la regla del proyecto (batir al
ELO con margen de 0.005).

Reutiliza la maquinaria de `entrenar_ligas_v68.py` para no duplicar la lógica de
adopción; lo único nuevo es de qué conjunto de ligas parte.

Salida: `_v70_reentrenamiento.json`
"""
import json
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logging.getLogger('py.warnings').setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

SALIDA = '_v70_reentrenamiento.json'


def main():
    import entrenar_ligas_v68 as e68
    import config

    with open('modelos_familia.json', encoding='utf-8') as f:
        familias = json.load(f)['ligas']
    claves = [c for c in familias if c in config.LEAGUES]
    logger.info(f"Reentrenando {len(claves)} competiciones con familia nueva: "
                f"{', '.join(claves)}")

    resultados = []
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding='utf-8') as f:
            resultados = [r for r in json.load(f) if r['clave'] not in claves]

    for i, clave in enumerate(claves, 1):
        cfg = config.LEAGUES[clave]
        logger.info(f"[{i}/{len(claves)}] {clave} → familia {familias[clave]}")
        t0 = time.time()
        r = e68.entrenar_una(clave)
        r['familia_v70'] = familias[clave]
        r['nombre'] = cfg['nombre']
        r['formato'] = cfg['formato']
        r['segundos'] = round(time.time() - t0, 1)
        resultados.append(r)
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)
        if r['estado'] == 'ok':
            logger.info(f"    acc={r['precision']} elo={r['elo']} → "
                        f"{'ADOPTADA' if r['adoptada'] else 'no supera al ELO'}")

    # ------------------------------------------------------------------
    # Decisión de despliegue: manda el WALK-FORWARD, no el split único.
    #
    # `entrenar_una` marca `adoptada` con el 80/20 de `entrenar_liga`, que es
    # justamente el estimador que v70 demostró poco fiable: en la FA Cup deja 79
    # partidos de validación (±5,5 pp de error típico) y varias de estas ligas
    # empatan con el ELO al decimal por puro azar de muestreo. La evidencia
    # buena es el walk-forward de 5 pliegues con selección secuencial, que es
    # con la que se eligió la familia. Se usa esa.
    # ------------------------------------------------------------------
    with open('_v70_wf_modelos.json', encoding='utf-8') as f:
        wf = {r['clave']: r for r in json.load(f) if r.get('estado') == 'ok'}
    for r in resultados:
        w = wf.get(r['clave'])
        if not w:
            continue
        s = w['seleccion_secuencial']
        r['wf_acc'] = s['acc']
        r['wf_ll'] = s['ll']
        r['wf_elo'] = w['elo_acc']
        r['wf_n_oos'] = w['n_oos']
        r['wf_bate_elo'] = bool(s['acc'] >= w['elo_acc'] + e68.MARGEN_ELO)
        r['adoptada'] = r['wf_bate_elo'] and r['estado'] == 'ok'

    # persistir las métricas de walk-forward en cada metadata.json: son las que
    # deben leerse para juzgar la liga, y con muchos más partidos de validación
    for r in resultados:
        if 'wf_acc' not in r:
            continue
        ruta = os.path.join('modelos', r['clave'], 'metadata.json')
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding='utf-8') as f:
            md = json.load(f)
        md['walk_forward_v70'] = {
            'precision': r['wf_acc'], 'log_loss': r['wf_ll'],
            'linea_base_elo': r['wf_elo'], 'n_validacion': r['wf_n_oos'],
            'pliegues': 5, 'bate_elo': r['wf_bate_elo'],
            'nota': 'walk-forward expandente de 5 pliegues con selección '
                    'secuencial de familia; mucho más fiable que el split '
                    'único 80/20 de precision_validacion'}
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(md, f, ensure_ascii=False, indent=2)

    ok = [r for r in resultados if r['estado'] == 'ok']
    adoptadas = [r for r in ok if r['adoptada']]
    cambios = e68.actualizar_disponibles(resultados)
    logger.info(f"== {len(ok)}/{len(resultados)} entrenadas · "
                f"{len(adoptadas)} baten al ELO · "
                f"{cambios} marcadas disponibles en config_ligas_espn.py")
    for r in sorted(adoptadas, key=lambda x: -(x.get('wf_acc', 0) - x.get('wf_elo', 0))):
        logger.info(f"   +{r['wf_acc'] - r['wf_elo']:.4f}  {r['clave']:22s} "
                    f"wf_acc={r['wf_acc']:.4f} (elo {r['wf_elo']:.4f}, "
                    f"n={r['wf_n_oos']}) [{r['familia_v70']}]")


if __name__ == '__main__':
    main()
