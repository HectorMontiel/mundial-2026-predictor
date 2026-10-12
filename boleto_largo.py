#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v370 — EL BOLETO LARGO CON LAS «SE METE» (tipo Draftea).

El usuario (11-oct), con un boleto de Draftea de 21 patas (×618, $191 →
$117.995): «quiero lograr hacer este tipo de apuestas con las soñadoras».

Las patas son SÓLO lo que la app dice «se mete» (`modo_modelo.lista_por_acierto`:
lo precalculado, con la apuesta fijada), una por partido, las ⭐ ELIGE primero
y luego de la que más se cumple a la que menos. De cualquier deporte, o de los
que se elijan.

Lo medido (`_v370_boleto_largo.py`, lo archivado al pitido del 5 al 11-oct, 7
días): una ⭐ acierta 89 % a cuota ~1,13 y el resto 77 % a ~1,24. Con esas
cuotas 20 patas pagan ×8-11, no ×618: el boleto de Draftea va a ~1,36 por pata.
Enteros: 10 patas 3 de 7 días, 15 patas 1 de 7, 20 patas 1 de 7; las mismas 20
partidas en 4 boletos de 5 salieron 17 de 28. Pocos días: se sigue midiendo.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

# (patas: (días con boleto entero, días medidos)) — `_v370_boleto_largo.json`
MEDIDO = {3: (5, 7), 5: (4, 7), 8: (4, 7), 10: (3, 7), 15: (1, 7), 20: (1, 7)}
MEDIDO_PARTIR = (17, 28)        # 20 patas en boletos de 5: enteros / boletos
TAM_TROZO = 5


def _filas(pronosticos: List[Dict], ahora: Optional[float] = None) -> List[Dict]:
    """Las filas de `lista_por_acierto` (sólo lee lo precalculado) y, para los
    partidos sin precálculo —justo después de cada actualización de la app,
    hasta el siguiente cálculo del día—, la misma cuenta de la tarjeta
    (`recos_tarjeta`, recordada). Sin esto el boleto salía vacío."""
    import time
    import decisiones_dia as dd
    import horario as hz
    import modo_modelo as mm
    con = [p for p in pronosticos if isinstance(p, dict) and dd.tarjeta_de_pick(p) is not None]
    filas = list(mm.lista_por_acierto(con, ahora)) if con else []
    t = float(ahora if ahora is not None else time.time())
    for p in pronosticos:
        if (not isinstance(p, dict) or dd.tarjeta_de_pick(p) is not None or p.get('jugado')
                or p.get('solo_mercado') or p.get('sin_modelo') or p.get('prob') is None):
            continue
        ini = hz._a_utc(p.get('inicio'))
        if ini is not None and ini.timestamp() <= t:
            continue
        dep = str(p.get('deporte') or 'Fútbol')
        try:
            recos = mm.recos_tarjeta(p)
        except Exception:
            continue
        for r in mm.metidas(recos):
            real = 0.85 if r.get('elite') else mm.acierta_de_verdad(r, dep)
            if real is None or not r.get('cuota'):
                continue
            ele = mm.elige(r, dep) and not r.get('elite')
            filas.append({'partido': p.get('partido'), 'inicio': p.get('inicio'),
                          'fecha': p.get('fecha'), 'deporte': dep, 'casa': '',
                          'apuesta': ('⭐ ' if ele else ('🏆 ' if r.get('elite') else ''))
                          + str(r.get('apuesta')),
                          'cuota': r.get('cuota'), 'prob': real, 'elige': ele,
                          'porque': 'acierta de verdad %.0f %% (medido)' % (100 * real)})
    return filas


def patas(pronosticos: List[Dict], deportes=None, ahora: Optional[float] = None) -> List[Dict]:
    """Las «se mete» que faltan, una por partido, en el orden del boleto."""
    import modo_modelo as mm
    nombres = None
    if deportes:
        import formato_ia as fi
        nombres = {n for d in deportes for n in fi.DEPORTES_ENVIO.get(d, (d,))}
    filas = _filas(pronosticos or [], ahora)
    out, vistos = [], set()
    # la lista ya viene con las ⭐ primero; dentro de ellas, la más probable
    orden = sorted(filas, key=lambda x: (not x.get('elige'), -float(x.get('prob') or 0),
                                          str(x.get('inicio') or '')))
    for x in orden:
        if x.get('sigue'):
            continue                        # ♻️: no es una «se mete» oficial
        if nombres and str(x.get('deporte') or 'Fútbol') not in nombres:
            continue
        if x.get('partido') in vistos or not x.get('cuota'):
            continue
        vistos.add(x.get('partido'))
        out.append(dict(x))
    return out


def boleto(lista: List[Dict], n: int) -> Optional[Dict]:
    """Las `n` primeras (o todas si hay menos, con al menos 2)."""
    b = list(lista or [])[:max(int(n), 0)]
    if len(b) < 2:
        return None
    return {'patas': sorted(b, key=lambda x: str(x.get('inicio') or '')),
            'momio': math.prod(float(x['cuota']) for x in b),
            'prob': math.prod(float(x['prob']) for x in b),
            'n_elige': sum(1 for x in b if x.get('elige')),
            'completo': len(b) >= int(n)}


def partir(b: Optional[Dict], tam: int = TAM_TROZO) -> List[Dict]:
    """El mismo boleto partido en boletos chicos (en el orden de la hora)."""
    if not b:
        return []
    ps = b['patas']
    return [boleto(ps[i:i + tam], tam) or {'patas': ps[i:i + tam],
                                           'momio': math.prod(float(x['cuota']) for x in ps[i:i + tam]),
                                           'prob': math.prod(float(x['prob']) for x in ps[i:i + tam]),
                                           'n_elige': 0, 'completo': True}
            for i in range(0, len(ps), tam)]


def medido(n: int) -> str:
    """Lo que salió con boletos de ese largo (el más cercano medido)."""
    k = min(MEDIDO, key=lambda m: (abs(m - int(n)), m))
    e, d = MEDIDO[k]
    return 'Medido (5-11 oct): con %d patas el boleto salió entero %d de %d días.' % (k, e, d)
