#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v223 — La Soñadora armada con los picks del día: una por partido, verde primero.

LO QUE SE PIDIÓ
---------------
«Al abrir la Soñadora que sólo me extraiga las apuestas, una de cada partido y
que sea la que esté en verde y que dé una buena cuota. Si de un partido hay
tres opciones y dos están en rojo y una en verde, la Soñadora debe coger la
verde. Y si ya no hay verdes para completar las patas, hay que meter la roja
que sea más probable.»

POR QUÉ NO SERVÍA LO QUE YA HABÍA
---------------------------------
`sonadora_motor.patas_del_dia` arma sus patas desde los TABLEROS de la casa:
recorre todos los mercados cotizados de cada partido y elige por cuota y
probabilidad cruda. Es otra fuente y otro criterio.

Esto arma desde lo que el usuario VE en «Apuestas del Día»: las mismas
recomendaciones, con el mismo veredicto y la misma probabilidad corregida por
`fiabilidad_picks`. La diferencia importa — un 55 % en «Goles» acierta el 47 %
y uno en «Doble oportunidad» el 63 %, así que elegir por probabilidad cruda
mete justo las peores.

LAS TRES REGLAS, EN ORDEN
-------------------------
1. **Una por partido.** Dos patas del mismo partido están correlacionadas y el
   boleto no multiplica lo que parece; `auditoria_pick` ya lo bloquea a nivel
   de combinada y aquí ni se llega a proponer.
2. **Verde antes que roja**, siempre, aunque la roja pague más. La cuota no
   ordena: ordena el veredicto.
3. **Si no hay verdes suficientes, se completa con las rojas MÁS PROBABLES** —
   no con las mejor pagadas. Es lo que se pidió y además es lo correcto: en un
   boleto de varias patas la probabilidad se multiplica, así que una pata
   floja hunde el conjunto mucho más de lo que su cuota lo levanta.

EL FILTRO DE CUOTA MÍNIMA
-------------------------
Dentro de un partido se descartan las patas por debajo del mínimo y de las que
quedan se coge **la más probable**, no la mejor pagada. Con cuota mínima 1,30,
entre una de 1,35 al 70 % y una de 1,90 al 55 %, entra la primera.

LO QUE ESTE MÓDULO NO PROMETE
-----------------------------
Que el boleto gane. Un parlay multiplica probabilidades y margen de casa a la
vez: cuatro patas al 70 % son un 24 % de acierto, y el EV combinado es
Π(1+EVᵢ)−1, que con EV negativos empeora con cada pata. Esto elige mejor
dentro de lo que hay; no convierte en positivo lo que no lo es.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger('patas_veredicto')

MIN_PATAS, MAX_PATAS = 1, 20
CUOTA_MINIMA_POR_DEFECTO = 1.30

# Cuántas recomendaciones se miran por partido. `modo_modelo.recomendadas`
# devuelve las mejores ordenadas; con tres hay margen para que el filtro de
# cuota descarte alguna y siga quedando candidata.
RECOS_POR_PARTIDO = 3


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _es_principal(pick: Dict) -> bool:
    """¿Es de una competición grande?

    `modo_modelo.es_secundaria` devuelve None cuando el eje no aplica —todo lo
    que no es fútbol—. Eso NO es «principal»: es «no se sabe», y colarlo en el
    filtro de principales metería la KBO entre las ligas grandes. Se compara
    con `is False` a propósito.
    """
    try:
        import modo_modelo as mm
        return mm.es_secundaria(pick) is False
    except Exception as e:
        logger.debug('[patas] es_secundaria: %s', e)
        return False


def candidatas_de(pick: Dict, cuota_minima: float) -> List[Dict]:
    """Las recomendaciones de UN partido, evaluadas y ordenadas.

    Orden: primero las verdes, y dentro de cada grupo por probabilidad
    ajustada. La cuota NO ordena — sólo filtra por el mínimo.
    """
    try:
        import modo_modelo as mm
        import veredicto_pick as vp
    except Exception as e:
        logger.debug('[patas] sin módulos: %s', e)
        return []

    recos = pick.get('_recomendadas')
    if not recos:
        try:
            recos = mm.recomendadas(pick, None, n=RECOS_POR_PARTIDO)
        except Exception as e:
            logger.debug('[patas] recomendadas de %s: %s',
                         pick.get('partido'), e)
            return []
    if not recos:
        return []

    fuera = []
    for v in vp.evaluar_lista(recos):
        cuota = _f((v.get('pick') or {}).get('cuota'))
        if cuota is None or cuota < cuota_minima:
            continue
        fuera.append({
            'partido': pick.get('partido'),
            'liga': pick.get('liga'),
            'clave_liga': pick.get('clave_liga'),
            'deporte': pick.get('deporte'),
            'fecha': pick.get('fecha'),
            'inicio': pick.get('inicio'),
            'apuesta': (v.get('pick') or {}).get('apuesta'),
            'mercado': (v.get('pick') or {}).get('mercado'),
            'cuota': cuota,
            'prob_modelo': v.get('prob_modelo'),
            'prob': v.get('prob_ajustada'),
            'verde': v.get('veredicto') == 'meter',
            # v257 — si la probabilidad de esta pata la corrigió algo MEDIDO o
            # es el modelo a pelo. `sonadora_motor.armar` lo exige para contar
            # las patas sin calibrar, y decirlo es media honestidad del
            # boleto: «8 patas» y «8 patas de las que 5 nadie ha medido» no
            # son la misma apuesta.
            'medido': bool(v.get('medido')),
            'n_muestra': v.get('n_muestra') or 0,
            'razones': v.get('razones') or [],
            'principal': _es_principal(pick),
        })
    # verde primero; dentro de cada grupo, la más probable
    fuera.sort(key=lambda q: (not q['verde'], -(q['prob'] or 0)))
    return fuera


def _repartir(candidatas: List[Dict], cuantas: int,
              max_mercado: int, max_liga: int,
              ya: Optional[List[Dict]] = None):
    """Coge las mejores respetando los topes por mercado y por competición.

    POR QUÉ HAY TOPES, Y NO ES BUROCRACIA. Sin ellos el boleto salía con ocho
    patas de «Goles» a cuota 1,30: ocho apuestas distintas que dependen del
    MISMO modelo de goles y de su sesgo de hoy. No están correlacionadas por el
    marcador —son partidos distintos— pero sí por el error del estimador, que
    es la correlación que de verdad hunde un parlay.

    Son los mismos topes que `sonadora_motor` ya aplica (`MAX_POR_MERCADO`,
    `MAX_POR_LIGA`): dos de cada. Se cuentan sobre lo YA elegido para que el
    relleno rojo no se salte lo que las verdes ocuparon.

    SE LEVANTAN ANTES QUE DEVOLVER UN BOLETO CORTO. Si con los topes no se
    llega al número pedido, se hace una segunda pasada sin ellos: el usuario
    pidió N patas, y darle N−3 por una regla interna que él no ve es peor que
    darle N con dos del mismo mercado.
    """
    elegidas = []
    n_merc, n_liga = {}, {}
    for q in (ya or []):
        n_merc[q.get('mercado')] = n_merc.get(q.get('mercado'), 0) + 1
        n_liga[q.get('liga')] = n_liga.get(q.get('liga'), 0) + 1

    for q in candidatas:
        if len(elegidas) >= cuantas:
            break
        m, l = q.get('mercado'), q.get('liga')
        if n_merc.get(m, 0) >= max_mercado or n_liga.get(l, 0) >= max_liga:
            continue
        elegidas.append(q)
        n_merc[m] = n_merc.get(m, 0) + 1
        n_liga[l] = n_liga.get(l, 0) + 1

    topados = False
    if len(elegidas) < cuantas:
        topados = True
        puestas = {id(x) for x in elegidas} | {id(x) for x in (ya or [])}
        for q in candidatas:
            if len(elegidas) >= cuantas:
                break
            if id(q) not in puestas:
                elegidas.append(q)
    return elegidas, topados


def seleccionar(r: Dict, n_patas: int = 4,
                cuota_minima: float = CUOTA_MINIMA_POR_DEFECTO,
                solo_principales: bool = False,
                max_partidos: int = 400,
                max_por_mercado: int = 2,
                max_por_liga: int = 2,
                deportes: Optional[List[str]] = None,
                ligas: Optional[List[str]] = None) -> Dict:
    """Arma el boleto: una pata por partido, verdes primero.

    Devuelve siempre el mismo esquema y NUNCA lanza. Si no llega a `n_patas`
    lo dice en vez de rellenar con lo que sea — un boleto de cuatro patas
    cuando se pidieron diez es una respuesta, y esconderlo sería peor.
    """
    n_patas = max(MIN_PATAS, min(MAX_PATAS, int(n_patas or 1)))
    cuota_minima = _f(cuota_minima) or CUOTA_MINIMA_POR_DEFECTO

    pron = [p for p in ((r or {}).get('pronosticos') or [])
            if isinstance(p, dict) and not p.get('jugado')]
    # v257 - POR DEPORTE, QUE ES LO QUE FALTABA PARA ELEGIR.
    #
    # `solo_principales` corta por TAMANO de competicion y no por deporte, asi
    # que no habia forma de pedir «solo MLB» ni «futbol y tenis». Una lista
    # vacia o None quiere decir TODOS, que es como se comporta el selector
    # cuando no se elige nada.
    if deportes:
        _q = {str(d).strip().lower() for d in deportes if d}
        if _q:
            pron = [p for p in pron
                    if str(p.get('deporte') or '').strip().lower() in _q]
    # v260 - Y POR LIGA, QUE ES EL OTRO EJE QUE FALTABA.
    #
    # «Quiero que a las sonadoras se les pueda poner un filtro de liga, ya sea
    # todas o la que yo escoja.»
    #
    # Va por el nombre visible (`liga`) y no por `clave_liga` porque es lo que
    # el usuario ve en la pantalla y lo que el selector le ofrece: filtrar por
    # una clave interna obligaria a mantener dos listas que se desincronizan.
    # Lista vacia o None quiere decir TODAS, igual que en `deportes`.
    if ligas:
        _l = {str(x).strip().lower() for x in ligas if x}
        if _l:
            pron = [p for p in pron
                    if str(p.get('liga') or '').strip().lower() in _l]
    if solo_principales:
        pron = [p for p in pron if _es_principal(p)]
    pron = pron[:max_partidos]

    # La MEJOR de cada partido, que es la regla «una de cada partido».
    mejores = []
    for p in pron:
        cands = candidatas_de(p, cuota_minima)
        if cands:
            mejores.append(cands[0])

    verdes = [q for q in mejores if q['verde']]
    rojas = [q for q in mejores if not q['verde']]
    verdes.sort(key=lambda q: -(q['prob'] or 0))
    rojas.sort(key=lambda q: -(q['prob'] or 0))

    # Verdes primero; se completa con las rojas MÁS PROBABLES, no con las
    # mejor pagadas: en un boleto la probabilidad se multiplica.
    patas, usados_verdes = _repartir(verdes, n_patas, max_por_mercado,
                                     max_por_liga)
    faltan = n_patas - len(patas)
    completadas = []
    if faltan > 0:
        completadas, _ = _repartir(rojas, faltan, max_por_mercado,
                                   max_por_liga, ya=patas)
        patas = patas + completadas

    prob = 1.0
    cuota = 1.0
    for q in patas:
        prob *= float(q['prob'] or 0.0)
        cuota *= float(q['cuota'] or 1.0)

    return {
        'patas': patas,
        'n_pedidas': n_patas,
        'n_verdes': sum(1 for q in patas if q['verde']),
        'n_rojas_de_relleno': len(completadas),
        'verdes_disponibles': len(verdes),
        'rojas_disponibles': len(rojas),
        'partidos_mirados': len(pron),
        'cuota_total': round(cuota, 2) if patas else None,
        'prob_total': round(prob, 4) if patas else None,
        'cuota_minima': cuota_minima,
        'solo_principales': bool(solo_principales),
        'ligas': list(ligas or []),
        'deportes': list(deportes or []),
        'completo': len(patas) == n_patas,
        'motivo': _motivo(len(patas), n_patas, len(verdes), len(rojas),
                          cuota_minima, solo_principales),
    }


def _motivo(n, pedidas, n_verdes, n_rojas, cuota_min, principales) -> str:
    if n == 0:
        extra = ' de competiciones principales' if principales else ''
        return (f'Ningún partido{extra} tiene hoy una apuesta con cuota '
                f'≥ {cuota_min:.2f}. Baja la cuota mínima'
                + (' o quita el filtro de principales.' if principales
                   else '.'))
    if n < pedidas:
        return (f'Sólo salen {n} patas de las {pedidas} pedidas: hay '
                f'{n_verdes} verdes y {n_rojas} rojas por encima de '
                f'{cuota_min:.2f}. Bajar la cuota mínima abre más.')
    if n_verdes >= pedidas:
        return f'Las {pedidas} patas son verdes.'
    return (f'{n_verdes} verdes y {pedidas - n_verdes} rojas de relleno, '
            f'las más probables que había.')


def alternativas(r: Dict, tamanos=(3, 4, 6, 8, 10),
                 cuota_minima: float = CUOTA_MINIMA_POR_DEFECTO,
                 solo_principales: bool = False) -> List[Dict]:
    """El mismo boleto en varios tamaños, para poder comparar.

    Es lo que pedía «puede ser que haya diferentes, entonces puede haber
    varias alternativas»: el mismo criterio con 3, 4, 6, 8 y 10 patas, para
    ver a partir de dónde hay que empezar a meter rojas.
    """
    fuera = []
    for n in tamanos:
        if not (MIN_PATAS <= n <= MAX_PATAS):
            continue
        try:
            fuera.append(seleccionar(r, n, cuota_minima, solo_principales))
        except Exception as e:
            logger.debug('[patas] alternativa de %d: %s', n, e)
    return fuera


if __name__ == '__main__':
    import precalculo_dia as pre
    d = (pre.leer() or {}).get('datos') or {}
    for n in (4, 8):
        s = seleccionar(d, n, 1.30)
        print('\n=== %d patas · cuota >= 1,30 ===' % n)
        print('  %s' % s['motivo'])
        print('  cuota total %.2f · prob %.1f%%'
              % (s['cuota_total'] or 0, (s['prob_total'] or 0) * 100))
        for q in s['patas']:
            print('   %s %-30s %-22s @%.2f  %.0f%%'
                  % ('🟢' if q['verde'] else '🔴', str(q['apuesta'])[:30],
                     str(q['liga'])[:22], q['cuota'], (q['prob'] or 0) * 100))
