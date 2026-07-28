#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v77 — Combinadas MULTI-DEPORTE.

Qué hace
--------
Toma los picks ya filtrados de las dos primeras pestañas (Máximo Valor y
Máxima Confianza) y arma combinadas de 2 a 6 patas que crucen **al menos dos
deportes distintos**, devolviendo tres perfiles: conservadora, media y
agresiva.

Por qué cruzar deportes no es un capricho
-----------------------------------------
El riesgo real de una combinada no es la cuota, es la CORRELACIÓN entre patas.
Dos picks del mismo partido, o de la misma liga en la misma jornada, fallan
juntos mucho más de lo que sugiere multiplicar sus probabilidades: comparten
árbitro, clima, estado del campo y, sobre todo, comparten el sesgo del modelo
que los generó. Si el modelo va mal calibrado esa tarde en la Liga MX, las
tres patas de Liga MX caen a la vez.

Cruzar deportes es la forma más barata de romper esa correlación: el resultado
de un partido de béisbol no comparte nada con el de un partido de tenis, ni
siquiera el modelo que lo predice. Por eso se exige y no solo se sugiere.

Qué NO hace, a propósito
------------------------
No promete que la probabilidad conjunta sea el producto de las patas. Lo
calcula así porque con deportes distintos la independencia es defendible, pero
lo declara en la salida (`supuesto`) en vez de venderlo como un número exacto.
Y **no entra sola en el Plan de Ataque**: se muestra con un stake sugerido de
⅛ de Kelly y el usuario decide, porque una combinada concentra varianza y esa
es una decisión suya, no del sistema.
"""

import itertools
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_PATAS, MAX_PATAS = 2, 6
MIN_PROB_CONJUNTA = 0.10       # por debajo de esto es una lotería, no una apuesta
MAX_CUOTA_TOTAL = 60.0
MIN_PROB_PATA = 0.55           # una pata floja arrastra a toda la combinada
FRACCION_KELLY = 0.125         # ⅛ — una combinada es varianza concentrada

PERFILES = (
    # (nombre, nº de patas, descripción)
    ('conservadora', 2, 'Dos patas, las más probables. Menos premio, menos varianza.'),
    ('media', 3, 'Tres patas equilibradas entre probabilidad y cuota.'),
    ('agresiva', 4, 'Cuatro patas: el premio sube rápido y la probabilidad baja igual.'),
)


def _clave_partido(p: Dict) -> str:
    return f"{p.get('deporte', '')}|{p.get('liga', '')}|{p.get('partido', '')}"


def _elegibles(picks: List[Dict]) -> List[Dict]:
    """Patas utilizables: con cuota y probabilidad reales, una por partido."""
    vistos, out = set(), []
    for p in sorted(picks, key=lambda x: -(x.get('prob') or 0)):
        prob, cuota = p.get('prob'), p.get('cuota')
        if not prob or not cuota or cuota <= 1:
            continue
        if prob < MIN_PROB_PATA:
            continue
        k = _clave_partido(p)
        if k in vistos:
            continue          # nunca dos patas del MISMO partido: correlación 1
        vistos.add(k)
        out.append(p)
    return out


def _evaluar(combo: List[Dict]) -> Optional[Dict]:
    prob = 1.0
    cuota = 1.0
    for p in combo:
        prob *= float(p['prob'])
        cuota *= float(p['cuota'])
    if prob < MIN_PROB_CONJUNTA or cuota > MAX_CUOTA_TOTAL:
        return None
    deportes = {p.get('deporte') for p in combo}
    if len(deportes) < 2:
        return None
    ev = cuota * prob - 1.0
    # Kelly fraccionado sobre la combinada completa
    b = cuota - 1.0
    kelly = max(0.0, (prob * (b + 1) - 1) / b) if b > 0 else 0.0
    return {
        'patas': [{'deporte': p.get('deporte'), 'liga': p.get('liga'),
                   'partido': p.get('partido'), 'apuesta': p.get('apuesta'),
                   'prob': round(float(p['prob']), 3),
                   'cuota': round(float(p['cuota']), 2),
                   'casa': p.get('casa')} for p in combo],
        'n_patas': len(combo),
        'deportes': sorted(d for d in deportes if d),
        'prob_conjunta': round(prob, 4),
        'cuota_total': round(cuota, 2),
        'ev': round(ev, 4),
        'stake_sugerido_pct': round(100 * kelly * FRACCION_KELLY, 2),
        'supuesto': 'Probabilidad conjunta = producto de las patas. Es '
                    'defendible porque las patas son de deportes distintos y '
                    'no comparten ni contexto ni modelo, pero es un supuesto, '
                    'no una medición.',
    }


def generar(picks_ev: List[Dict], picks_prob: List[Dict],
            max_candidatos: int = 12) -> List[Dict]:
    """
    Tres combinadas (conservadora, media, agresiva) a partir de los picks de
    las dos pestañas. Lista vacía si no hay material para cruzar deportes.
    """
    universo = _elegibles(list(picks_ev or []) + list(picks_prob or []))
    deportes = {p.get('deporte') for p in universo}
    if len(deportes) < 2 or len(universo) < 2:
        logger.info(f"[parlay-cruzado] material insuficiente: {len(universo)} "
                    f"patas de {len(deportes)} deportes")
        return []

    # se limita el universo a los mejores por probabilidad para que el número
    # de combinaciones no explote (C(12,4) = 495, asumible; C(40,4) = 91.390)
    universo = universo[:max_candidatos]

    salida = []
    for nombre, n, desc in PERFILES:
        if len(universo) < n:
            continue
        mejor = None
        for combo in itertools.combinations(universo, n):
            r = _evaluar(list(combo))
            if not r:
                continue
            # criterio: dentro de las válidas, la de mayor EV; a igualdad de
            # EV, la más probable (menos varianza para el mismo retorno)
            llave = (round(r['ev'], 4), r['prob_conjunta'])
            if mejor is None or llave > mejor[0]:
                mejor = (llave, r)
        if mejor:
            salida.append({**mejor[1], 'perfil': nombre, 'descripcion': desc})
    return salida


def resumen(combinadas: List[Dict]) -> Dict:
    return {'n': len(combinadas),
            'deportes': sorted({d for c in combinadas for d in c['deportes']}),
            'fraccion_kelly': FRACCION_KELLY}
