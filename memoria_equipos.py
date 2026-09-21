# -*- coding: utf-8 -*-
"""
v265 — En qué se equivoca el modelo con CADA equipo, y que no se le olvide.

LO QUE SE PIDIÓ
«Que el modelo pueda aprender de sí mismo, de las cuotas finalizadas de sus
predicciones, en cada liga, en cada mercado, en cada deporte; en qué se está
equivocando... y así los refine para que la próxima vez que ese equipo juegue
se tome en cuenta.»

LA PREGUNTA, Y LA RESPUESTA
Si el modelo fuera perfecto, su error con un equipo sería ruido blanco: lo que
falló el mes pasado no diría nada de lo que va a fallar el próximo. Medido
sobre 154.636 observaciones de `pick_ledger_totales.csv` (error = goles reales
menos la λ predicha, ventana de 10 partidos, siempre ANTERIORES):

    lo que venía fallando ese equipo        error de hoy
    sobrando 0,5 goles o más   n=14.818        -0,069
    sobrando 0,2-0,5           n=34.040        -0,038
    ajustado                   n=59.360        +0,011
    corto 0,2-0,5              n=28.403        +0,048
    corto 0,5 o más            n=18.015        +0,127

Hay memoria: correlación +0,0493 y un gradiente limpio y monótono. No es
ruido.

CUÁNTO VALE, VALIDADO FUERA DE MUESTRA
Con el peso ajustado SÓLO en el 60 % más antiguo y medido en el 40 % reciente:

    peso 0,1415 · MSE 1,39182 -> 1,38838  (-0,247 %)
    mejora media +0,00344 · p5 +0,00244 · 100 % de los remuestreos a favor

Pasa la puerta, y es **pequeño**: un cuarto de punto porcentual. Conviene
decirlo antes de que alguien espere un milagro de aquí.

POR QUÉ NO CORRIGE LA λ DIRECTAMENTE
Sería la tercera corrección apilada sobre la misma cantidad —ya están el
encogimiento de la v251 y la curva de goles de la v225— y hoy mismo se vio a
dónde lleva eso: la curva de goles se estaba aplicando sobre una λ distinta de
aquella con la que se midió, y empeoraba las cosas.

Así que esto NO toca la λ. Publica el sesgo de cada equipo y se lo da al
selector como una variable más, para que él aprenda cuánto pesarla junto con
todo lo demás. Una sola puerta, un solo sitio donde medirlo.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

FICHERO = 'memoria_equipos.json'
LEDGER = 'pick_ledger_totales.csv'

# Los últimos N partidos de cada equipo. Diez es lo que se midió; con menos la
# media es ruido y con más se arrastra una plantilla que ya no existe.
VENTANA = 10
# Por debajo de esto no se publica sesgo: cinco partidos no son una tendencia.
MIN_PARTIDOS = 5

_CACHE: Optional[Dict] = None


def cargar(ruta: str = FICHERO) -> Dict:
    """El sesgo de cada equipo, o {} si no hay. Nunca lanza."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    doc = {}
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8') as f:
                doc = json.load(f) or {}
        except Exception as e:
            logger.warning('[memoria] no se pudo leer %s: %s', ruta, e)
            doc = {}
    _CACHE = doc
    return _CACHE


def olvidar() -> None:
    global _CACHE
    _CACHE = None


def _clave(nombre) -> str:
    """La misma normalización que usa el resto del proyecto."""
    try:
        import cuotas_multi as cm
        return cm.normalizar(str(nombre or ''))
    except Exception:
        return str(nombre or '').strip().lower()


def sesgo(equipo) -> Optional[float]:
    """Cuánto se ha quedado corto (+) o sobrado (-) el modelo con ese equipo.

    En goles por partido. None si no hay suficientes partidos suyos: no
    inventar un sesgo es mejor que inventarlo pequeño.
    """
    d = (cargar().get('equipos') or {})
    v = d.get(_clave(equipo))
    if not v:
        return None
    try:
        if int(v.get('n') or 0) < MIN_PARTIDOS:
            return None
        return float(v.get('sesgo'))
    except (TypeError, ValueError):
        return None


def del_partido(home, away) -> Dict:
    """Los dos sesgos de un partido, para colgarlos de un pick."""
    return {'sesgo_local': sesgo(home), 'sesgo_visita': sesgo(away)}


# ---------------------------------------------------------------------------
def construir(ruta_ledger: str = LEDGER, ruta: str = FICHERO) -> Dict:
    """Recorre el histórico y deja el sesgo vigente de cada equipo.

    Sin mirar el futuro por construcción: el sesgo que se publica es el de los
    ÚLTIMOS `VENTANA` partidos de cada equipo, que es exactamente lo que se
    sabrá antes del próximo.
    """
    import collections
    import numpy as np
    import pandas as pd

    if not os.path.exists(ruta_ledger):
        logger.warning('[memoria] sin %s', ruta_ledger)
        return {}
    d = pd.read_csv(ruta_ledger, low_memory=False)
    faltan = [c for c in ('lam_h', 'lam_a', 'goles_local', 'goles_visit',
                          'match_id', 'fecha') if c not in d.columns]
    if faltan:
        logger.warning('[memoria] al ledger le faltan columnas: %s', faltan)
        return {}
    d = d.dropna(subset=['lam_h', 'lam_a', 'goles_local', 'goles_visit',
                         'match_id', 'fecha'])
    d = d.sort_values('fecha').reset_index(drop=True)

    def equipos(mid):
        p = str(mid).split('_')
        return (p[1], p[2]) if len(p) >= 3 else (None, None)

    home, away = zip(*d['match_id'].map(equipos))
    err_h = (d['goles_local'] - d['lam_h']).to_numpy(dtype=float)
    err_a = (d['goles_visit'] - d['lam_a']).to_numpy(dtype=float)

    hist = collections.defaultdict(list)
    for i in range(len(d)):
        for eq, e in ((home[i], err_h[i]), (away[i], err_a[i])):
            if eq:
                hist[_clave(eq)].append(float(e))

    equipos_out = {}
    for k, xs in hist.items():
        ult = xs[-VENTANA:]
        if len(ult) < MIN_PARTIDOS:
            continue
        equipos_out[k] = {'sesgo': round(float(np.mean(ult)), 4),
                          'n': len(ult), 'total': len(xs)}

    doc = {
        'generado': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'ventana': VENTANA,
        'partidos': int(len(d)),
        'hasta': str(d['fecha'].max())[:10],
        'equipos': equipos_out,
    }
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    olvidar()
    return doc


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    doc = construir()
    if not doc:
        print('sin ledger')
        return 1
    eq = doc.get('equipos') or {}
    import numpy as np
    ses = [v['sesgo'] for v in eq.values()]
    print('equipos con memoria: %s (de %s partidos, hasta %s)'
          % (format(len(eq), ',d'), format(doc.get('partidos', 0), ',d'),
             doc.get('hasta')))
    if ses:
        print('sesgo: media %+.4f · desv %.4f · min %+.3f · max %+.3f'
              % (float(np.mean(ses)), float(np.std(ses)), min(ses), max(ses)))
        peor = sorted(eq.items(), key=lambda kv: -abs(kv[1]['sesgo']))[:5]
        print('los cinco con más sesgo:')
        for k, v in peor:
            print('   %-28s %+.3f goles/partido (n=%d)'
                  % (k[:28], v['sesgo'], v['n']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
