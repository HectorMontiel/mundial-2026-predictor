#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 — Decisión final de despliegue de las competiciones evaluadas.

Separado del reentrenamiento a propósito: entrenar es caro y la decisión de
`disponible` hay que poder rehacerla sin volver a entrenar.

La decisión se toma con el **walk-forward de 5 pliegues con selección
secuencial**, no con el split único 80/20 de `entrenar_liga`. Motivo, medido en
esta misma versión: el split único deja 79 partidos de validación en la FA Cup
(±5,5 pp de error típico) y varias ligas empatan con el ELO al cuarto decimal
por puro azar de muestreo. El walk-forward valida sobre 384–2.680 partidos.

Escribe, para cada liga evaluada:
  · `disponible` en `config_ligas_espn.py` (sólo si bate al ELO con margen)
  · el bloque `walk_forward_v70` en su `modelos/<liga>/metadata.json`

Salida: `_v70_despliegue.json`
"""
import json
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_despliegue.json'
MARGEN_ELO = 0.005


def main():
    import entrenar_ligas_v68 as e68

    with open('_v70_wf_modelos.json', encoding='utf-8') as f:
        wf = [r for r in json.load(f) if r.get('estado') == 'ok']
    familias = {}
    if os.path.exists('modelos_familia.json'):
        with open('modelos_familia.json', encoding='utf-8') as f:
            familias = json.load(f).get('ligas') or {}

    resultados = []
    for r in wf:
        clave = r['clave']
        s = r['seleccion_secuencial']
        bate = bool(s['acc'] >= r['elo_acc'] + MARGEN_ELO)
        fila = {'clave': clave, 'estado': 'ok',
                'familia': familias.get(clave, 'ensemble'),
                'wf_acc': s['acc'], 'wf_ll': s['ll'], 'wf_elo': r['elo_acc'],
                'wf_n_oos': r['n_oos'], 'margen': round(s['acc'] - r['elo_acc'], 4),
                'bate_elo': bate, 'adoptada': bate}

        ruta = os.path.join('modelos', clave, 'metadata.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                md = json.load(f)
            md['walk_forward_v70'] = {
                'precision': s['acc'], 'log_loss': s['ll'],
                'linea_base_elo': r['elo_acc'], 'n_validacion': r['n_oos'],
                'pliegues': 5, 'bate_elo': bate,
                'familias_por_pliegue': s['familias'],
                'nota': 'walk-forward expandente de 5 pliegues con selección '
                        'secuencial de familia (la familia de cada pliegue se '
                        'elige con los pliegues anteriores, nunca con el test). '
                        'Mucho más fiable que el split único 80/20 de '
                        'precision_validacion.'}
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(md, f, ensure_ascii=False, indent=2)
            fila['metadata_actualizada'] = True
            fila['familia_entrenada'] = md.get('familia_modelo')
        else:
            fila['metadata_actualizada'] = False
            logger.warning(f"[{clave}] sin metadata.json — ¿modelo no entrenado?")
        resultados.append(fila)

    cambios = e68.actualizar_disponibles(resultados)
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1)

    adoptadas = [r for r in resultados if r['adoptada']]
    logger.info(f"== {len(adoptadas)}/{len(resultados)} baten al ELO en "
                f"walk-forward · {cambios} marcadas disponibles")
    for r in sorted(adoptadas, key=lambda x: -x['margen']):
        logger.info(f"   +{r['margen']:.4f}  {r['clave']:22s} "
                    f"acc={r['wf_acc']:.4f} (elo {r['wf_elo']:.4f}, "
                    f"n={r['wf_n_oos']}) [{r['familia']}]")


if __name__ == '__main__':
    main()
