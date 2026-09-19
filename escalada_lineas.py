#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v212 — Escalada de líneas: subir de «Más de 2,5» a «Más de 3,5» con evidencia.

LA IDEA, Y POR QUÉ NO ES LO MISMO QUE MAXIMIZAR EV
--------------------------------------------------
Escalar una línea es cambiar probabilidad por cuota. Hecho por EV del modelo,
es el patrón que este proyecto tiene medido como trampa: `ventaja_ponches`
(v132) lo dejó por escrito midiendo una escalera real de ponches —el margen de
la casa CRECE con el escalón—

    escalón   1/cuota   precio justo   margen
    2+         84,6 %      87,1 %      pequeño
    6+         20,0 %      15,2 %      grande
    7+         11,1 %       7,1 %      enorme

...así que maximizar EV empuja justo adonde la casa se queda más, y el optimismo
residual del modelo vive en esa misma cola.

Por eso aquí la escalada NO la decide el EV: la deciden CUATRO FUENTES
INDEPENDIENTES y hacen falta tres. Una sola fuente puede equivocarse en la cola;
tres que coinciden es otra cosa. Que eso funcione o no lo dice el backtest,
no este módulo: `ACTIVO` lo fija `backtest_v212.py` y arranca apagado.

GENÉRICO POR MÉTRICA Y POR DEPORTE, A PROPÓSITO
-----------------------------------------------
No sabe qué es un gol. Recibe `metrica`, `linea_base`, `linea_superior`,
`deporte` y un contexto con lo que cada fuente aporte, y aplica la misma
aritmética a goles, córners, tarjetas, remates, yardas, touchdowns, sets o
aces. Lo específico de cada deporte vive en `scraper_contexto`, no aquí.
"""

import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('escalada_lineas')

# ---------------------------------------------------------------------------
# Los umbrales del encargo
# ---------------------------------------------------------------------------
FUERZA_FUERTE, FUERZA_MEDIA, FUERZA_DEBIL, FUERZA_NULA = 'fuerte', 'media', 'debil', 'nula'

FUENTES_REQUERIDAS = 3          # de 4
MAX_ESCALADAS = 2               # cadena máxima por pick

# Fuente 2 — mercado
CUOTA_MERCADO_FUERTE = 1.65     # <= esto, el mercado respalda
CUOTA_MERCADO_MEDIA = 1.90      # <= esto, media; por encima, débil

# Excepción: 3 fuertes con mercado débil
CUOTA_SUPERIOR_MINIMA_SIN_MERCADO = 1.50

# Fuente 3 — forma
MARGEN_FORMA = 0.5              # media_5 >= linea + esto
# Contra qué línea se compara la forma. `superior` es la regla tal y como está
# escrita en el encargo; `base` es la que hace cuadrar su ejemplo. Ver
# `fuente_forma`. El backtest mide las dos y el veredicto queda en
# `activacion_v212.json`.
REFERENCIA_FORMA = 'superior'

# Anti-patrones
FACTOR_RIESGO_MAXIMO = 1.5
CUOTA_BASE_MINIMA = 1.30
CUOTA_SUPERIOR_MINIMA = 1.50

FICHERO_ACTIVACION = 'activacion_v212.json'
_ACTIVACION: Optional[Dict] = None


def _cargar_activacion(recargar: bool = False) -> Dict:
    global _ACTIVACION
    if _ACTIVACION is not None and not recargar:
        return _ACTIVACION
    _ACTIVACION = {}
    try:
        if os.path.exists(FICHERO_ACTIVACION):
            with open(FICHERO_ACTIVACION, encoding='utf-8') as f:
                _ACTIVACION = json.load(f) or {}
    except Exception as e:
        logger.warning('[escalada] no se pudo leer la activación: %s', e)
    return _ACTIVACION


def activo(regla: str = 'escalada_lineas') -> bool:
    """Apagado mientras el backtest no la valide. Ver `backtest_v212.py`."""
    e = (_cargar_activacion().get('reglas') or {}).get(regla) or {}
    return bool(e.get('activa'))


def motivo_estado(regla: str = 'escalada_lineas') -> str:
    doc = _cargar_activacion()
    if not doc:
        return 'sin backtest todavía: arranca apagada'
    return str(((doc.get('reglas') or {}).get(regla) or {}).get('motivo') or '')


# ---------------------------------------------------------------------------
def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Las cuatro fuentes. Cada una devuelve su fuerza y por qué.
# ---------------------------------------------------------------------------
def fuente_modelo(prob_superior: Optional[float],
                  prob_base: Optional[float] = None) -> Dict:
    """Fuente 1 — el modelo. Se omite (nula) si no hay probabilidad.

    El corte es 0,60 para «fuerte» porque es el mismo suelo que usa el Modo
    Seguridad: por debajo de ahí la línea superior deja de ser una apuesta de
    alta probabilidad y pasa a ser un volado mejor pagado, que es justo lo que
    la escalada NO debe producir.
    """
    p = _f(prob_superior)
    if p is None:
        return {'fuerza': FUERZA_NULA, 'nota': 'el modelo no cotiza esa línea'}
    if p >= 0.60:
        return {'fuerza': FUERZA_FUERTE,
                'nota': f'el modelo da {p*100:.0f} % a la línea superior'}
    if p >= 0.50:
        return {'fuerza': FUERZA_MEDIA,
                'nota': f'el modelo da {p*100:.0f} %, justo por encima del 50 %'}
    return {'fuerza': FUERZA_DEBIL,
            'nota': f'el modelo sólo da {p*100:.0f} % a la línea superior'}


def fuente_mercado(cuota_superior: Optional[float]) -> Dict:
    """Fuente 2 — el mercado, por la cuota de la línea superior."""
    c = _f(cuota_superior)
    if c is None:
        return {'fuerza': FUERZA_NULA, 'nota': 'nadie cotiza la línea superior'}
    if c <= CUOTA_MERCADO_FUERTE:
        return {'fuerza': FUERZA_FUERTE,
                'nota': f'el mercado la paga a {c:.2f}: la considera probable'}
    if c <= CUOTA_MERCADO_MEDIA:
        return {'fuerza': FUERZA_MEDIA, 'nota': f'el mercado la paga a {c:.2f}'}
    return {'fuerza': FUERZA_DEBIL,
            'nota': f'el mercado la paga a {c:.2f}: no se lo cree'}


def fuente_forma(media_5: Optional[float], linea_superior: Optional[float],
                 esperado_5: Optional[float] = None,
                 linea_base: Optional[float] = None,
                 referencia: str = REFERENCIA_FORMA) -> Dict:
    """Fuente 3 — forma reciente y su equivalente esperado (xG, xBA, EPA…).

    `esperado_5` es la versión «de calidad» de la misma métrica. Si la fuente
    no la publica, la media sola puede llegar como mucho a MEDIA: una racha de
    goles sin respaldo de ocasiones es exactamente el dato que engaña.

    EL ENCARGO SE CONTRADICE AQUÍ, Y POR ESO ES UN PARÁMETRO
    --------------------------------------------------------
    La regla dice: «si media_5 >= linea_superior + 0,5 y xG_5 >= linea_superior
    -> fuerte». Su propio ejemplo (Barcelona-Getafe) escala a Más de 3,5 con
    media 3,4 y xG 3,1 y lo llama fuerte — pero con `linea_superior = 3,5` la
    regla pide media >= 4,0 y xG >= 3,5, y 3,4/3,1 no cumplen ninguna de las
    dos. Con la LÍNEA BASE como referencia (3,4 >= 3,0 y 3,1 >= 2,5) el ejemplo
    sí cuadra.

    Son dos lecturas distintas y no se puede elegir a ojo: `superior` es
    conservadora (exige evidencia de superar la línea a la que se sube) y
    `base` es laxa (escala mucho más). Se dejan las dos y las compara el
    backtest, que es quien tiene que arbitrar esto.
    """
    m = _f(media_5)
    L = _f(linea_superior)
    if str(referencia) == 'base':
        ref = _f(linea_base)
        if ref is None:
            ref = L
    else:
        ref = L
    L = ref
    if m is None or L is None:
        return {'fuerza': FUERZA_NULA, 'nota': 'sin forma reciente'}
    x = _f(esperado_5)
    supera = m >= L + MARGEN_FORMA
    if supera and x is not None and x >= L:
        return {'fuerza': FUERZA_FUERTE,
                'nota': f'media de {m:.1f} en los últimos 5 y esperado {x:.1f}, '
                        f'los dos por encima de {L}'}
    if supera:
        return {'fuerza': FUERZA_MEDIA,
                'nota': f'media de {m:.1f} en los últimos 5, pero sin dato '
                        f'esperado que lo respalde'}
    if m >= L:
        return {'fuerza': FUERZA_MEDIA, 'nota': f'media de {m:.1f}, justa'}
    return {'fuerza': FUERZA_DEBIL,
            'nota': f'media de {m:.1f}, por debajo de {L}'}


def fuente_contexto(senales: Optional[List[Dict]]) -> Dict:
    """Fuente 4 — el contexto. `>= 2` señales es fuerte, 1 media, 0 débil."""
    s = [x for x in (senales or []) if isinstance(x, dict)]
    peso = sum(int(x.get('peso') or 1) for x in s)
    if peso >= 2:
        tipos = ', '.join(sorted({str(x.get('tipo') or '?') for x in s})[:3])
        return {'fuerza': FUERZA_FUERTE,
                'nota': f'{peso} señales de contexto ({tipos})'}
    if peso == 1:
        return {'fuerza': FUERZA_MEDIA,
                'nota': f"una señal: {s[0].get('tipo', '?')}"}
    return {'fuerza': FUERZA_DEBIL, 'nota': 'sin señales de contexto'}


# ---------------------------------------------------------------------------
# La decisión
# ---------------------------------------------------------------------------
def decidir(fuentes: Dict[str, Dict], cuota_superior: Optional[float] = None,
            cuota_base: Optional[float] = None,
            factor_riesgo: float = 1.3,
            alta_incertidumbre: bool = False,
            fuentes_requeridas: int = FUENTES_REQUERIDAS) -> Dict:
    """La regla de escalada del encargo. Función PURA: la mide el backtest.

    `fuentes` es {'modelo': {...}, 'mercado': {...}, 'forma': {...},
    'contexto': {...}}, cada uno con su `fuerza`.
    """
    f = {k: (v or {}).get('fuerza', FUERZA_NULA) for k, v in (fuentes or {}).items()}
    fuertes = [k for k, v in f.items() if v == FUERZA_FUERTE]
    n_fuertes = len(fuertes)

    # --- anti-patrones: van primero, descalifican ---------------------------
    cs, cb = _f(cuota_superior), _f(cuota_base)
    if alta_incertidumbre:
        return {'escalar': False, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
                'motivo': '🔴 Alta incertidumbre: no se escala nada'}
    if float(factor_riesgo) > FACTOR_RIESGO_MAXIMO:
        return {'escalar': False, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
                'motivo': f'competición de riesgo {factor_riesgo}: no se escala'}
    if cb is not None and cb < CUOTA_BASE_MINIMA:
        return {'escalar': False, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
                'motivo': f'la cuota base {cb:.2f} ya es demasiado corta'}
    if cs is not None and cs < CUOTA_SUPERIOR_MINIMA:
        return {'escalar': False, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
                'motivo': f'la línea superior paga {cs:.2f}: escalar no '
                          f'compensa la probabilidad que se pierde'}

    # --- la regla -----------------------------------------------------------
    # `fuentes_requeridas` es 3 en producción. Es parámetro porque el backtest
    # necesita medir una variante DEGRADADA: en el histórico sólo existen dos
    # de las cuatro fuentes (el xG de este repo lo escribe el generador
    # sintético —ver ARQUITECTURA §5.3— y las señales de contexto de un partido
    # de 2024 no las archivó nadie), así que la regla de 3 de 4 no puede
    # dispararse ni una vez sobre datos pasados. Ver `backtest_v212`.
    if n_fuertes >= int(fuentes_requeridas):
        if f.get('mercado') == FUERZA_DEBIL:
            if cs is not None and cs >= CUOTA_SUPERIOR_MINIMA_SIN_MERCADO:
                return {'escalar': True, 'n_fuertes': n_fuertes,
                        'fuertes': fuertes,
                        'motivo': f'{n_fuertes} fuentes fuertes; el mercado no '
                                  f'acompaña pero la cuota {cs:.2f} lo paga'}
            return {'escalar': False, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
                    'motivo': 'tres fuentes fuertes pero el mercado va en '
                              'contra y la cuota no compensa'}
        return {'escalar': True, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
                'motivo': f'{n_fuertes} de 4 fuentes fuertes'}
    if n_fuertes == 2:
        return {'escalar': False, 'n_fuertes': 2, 'fuertes': fuertes,
                'contexto_positivo': True,
                'motivo': 'dos fuentes fuertes: contexto positivo, pero no '
                          'basta para escalar'}
    return {'escalar': False, 'n_fuertes': n_fuertes, 'fuertes': fuertes,
            'motivo': f'sólo {n_fuertes} fuente(s) fuerte(s)'}


def evaluar(metrica: str, linea_base: float, linea_superior: float,
            deporte: str = 'futbol',
            prob_superior: Optional[float] = None,
            cuota_superior: Optional[float] = None,
            cuota_base: Optional[float] = None,
            media_5: Optional[float] = None,
            esperado_5: Optional[float] = None,
            senales: Optional[List[Dict]] = None,
            factor_riesgo: float = 1.3,
            alta_incertidumbre: bool = False,
            referencia_forma: str = REFERENCIA_FORMA,
            fuentes_requeridas: int = FUENTES_REQUERIDAS) -> Dict:
    """Evalúa UNA escalada. Devuelve la decisión con las cuatro fuentes."""
    fuentes = {
        'modelo': fuente_modelo(prob_superior),
        'mercado': fuente_mercado(cuota_superior),
        'forma': fuente_forma(media_5, linea_superior, esperado_5,
                              linea_base, referencia_forma),
        'contexto': fuente_contexto(senales),
    }
    d = decidir(fuentes, cuota_superior, cuota_base, factor_riesgo,
                alta_incertidumbre, fuentes_requeridas)
    return {**d, 'metrica': metrica, 'deporte': deporte,
            'linea_base': linea_base, 'linea_superior': linea_superior,
            'cuota_base': cuota_base, 'cuota_superior': cuota_superior,
            'prob_superior': prob_superior,
            'fuentes': fuentes,
            'razones': [v['nota'] for v in fuentes.values() if v.get('nota')]}


def cadena(escalones: List[Dict], max_escaladas: int = MAX_ESCALADAS) -> Dict:
    """Aplica escaladas sucesivas mientras la regla lo permita.

    `escalones` es la lista ordenada de candidatos, cada uno con los mismos
    argumentos que `evaluar`. Para en el primer «no» — una escalada que no se
    justifica no puede saltarse para probar la siguiente.
    """
    hechas, ultimo = [], None
    for i, e in enumerate(escalones or []):
        if len(hechas) >= max(0, int(max_escaladas)):
            break
        r = evaluar(**e)
        if not r.get('escalar'):
            return {'escaladas': hechas, 'n': len(hechas), 'final': ultimo,
                    'parada': r}
        hechas.append(r)
        ultimo = r
    return {'escaladas': hechas, 'n': len(hechas), 'final': ultimo,
            'parada': None}


def explicar(r: Dict) -> str:
    """El texto que va a pantalla."""
    if not r:
        return ''
    if r.get('escalar'):
        return (f"⬆️ Escalada de {r['metrica']} {r['linea_base']} a "
                f"{r['linea_superior']}: {r['motivo']}")
    if r.get('contexto_positivo'):
        return f"➕ Contexto positivo en {r['metrica']}: {r['motivo']}"
    return f"⏸ Sin escalar: {r.get('motivo', '')}"


if __name__ == '__main__':
    # El ejemplo del encargo: Barcelona vs Getafe.
    r = evaluar('goles', 2.5, 3.5, 'futbol',
                prob_superior=0.62, cuota_superior=1.72, cuota_base=1.45,
                media_5=3.4, esperado_5=3.1,
                senales=[{'tipo': 'baja_defensiva', 'peso': 1},
                         {'tipo': 'h2h', 'peso': 1}])
    print(explicar(r))
    for nota in r['razones']:
        print('   -', nota)
