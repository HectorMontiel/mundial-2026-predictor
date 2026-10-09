# -*- coding: utf-8 -*-
"""
v317 — LO MEJOR DEL MODELO: LO QUE VA A LA CAPA 1.

El usuario: «ahora Capa 1 no me muestra nada y eso está mal. Capa 1 debería
mostrarme partidos. Se supone que ahí debería ser lo mejor de lo mejor, y más
si ya tenemos nuestras probabilidades más altas, nuestras proyecciones más
eficientes».

POR QUÉ ESTABA VACÍA
La Capa 1 sólo tenía los ERRORES DE PRECIO contra Pinnacle (una casa paga
por encima del precio justo), y desde la v315 sólo en las casas del usuario.
Con las casas y Pinnacle de acuerdo, cero es la respuesta correcta de ese
canal: no dice nada del modelo.

QUÉ SE AÑADE, Y CÓMO SE ELIGIÓ
Se buscó qué parte de lo que el modelo dice acierta más, en tres fuentes:
  · la simulación de la tarjeta con partidos terminados (`_v312_patrones.py`
    rehecho hasta el 29-sep: 2.287 candidatas de 473 partidos). La regla de
    «meter» acierta 75,7 % (20-26 sep, 440) y 78,9 % (27-29, 175); ningún
    subgrupo por mercado, franja o cuota destaca de forma estable: 10 días
    no dan para más;
  · el histórico de resultado (`pick_ledger.csv`, 60.796 partidos con
    predicción fuera de muestra y cuota de la casa), partido en 70 % antiguo
    y 30 % reciente. Aquí sí aparece un criterio claro: cuando el MODELO
    dice 70 % o más y LA CASA, sin su margen, lo ve entre el 80 % y el 88 %,
    se cumple mucho más que el resto:

                              elegir (70 %)     juzgar (30 %)
      doble oportunidad       85,3 % (8.166)    84,8 % (3.680)
      ganador                 86,9 % (  594)    87,9 % (  132)
      resto (modelo 70-80 %,
      casa por debajo de 80)  73,2 %            72,7 %

    Bootstrap por partido de la diferencia: p5 +0,095 al juzgar. Unas cuatro
    por día (mediana). Por encima del 88 % la casa paga menos de 1,10 y no
    vale la pena; por eso el tope.
Se exige además cuota de 1,10 o más en la casa del usuario.

EL SEGUNDO NIVEL: 🔷 MÁS RIESGO, MÁS CUOTA
El usuario, al ver el primero: «¿puedes encontrar uno con cuotas más grandes?
La cosa es tener arriba de un 65 % de probabilidad… no importa que sólo
hagamos apuesta de un partido o de dos, pero nos ayudaría a multiplicar más.
Márcalo de alguna forma que sepamos que tiene otra probabilidad».
Buscado en el mismo histórico, sólo con cuota 1,40-2,10 (lo que la casa
pagaba de verdad). En doble oportunidad no hay nada: a esa cuota acierta
63-66 % y pierde 4-8 %. En GANADOR sí, cuando el modelo lo ve claro y la casa
lo tiene entre 55 % y 70 %:

    regla: ganador, casa sin margen 55-70 %, el modelo en 70 % o más
           (o en 60 % o más si la casa ya lo da en 65-70 %), cuota ≥ 1,35
                     apuestas  cuota  acierto (p5)      ganancia (p5)
    elegir (70 %)      1.706   1,43   71,4 % (69,5 %)   +1,6 % (−1,1 %)
    juzgar (30 %)        648   1,42   72,4 % (69,6 %)   +3,0 % (−1,0 %)
    por cuota: 1,35-1,45 → 72,4 / 71,3 %; 1,45-1,60 → 67,3 / 81,0 %;
               1,60-1,80 → 60,8 / 66,7 % (poca muestra)
    (`_v317_capa1.json`). El ACIERTO está asegurado por encima del 65 % en
    los dos tramos; la ganancia es positiva pero su p5 no, así que no se
    promete dinero, sólo el acierto.

Casi dos por día. Es menos seguro que el primero (71-72 % contra 85 %) y se
dice así en todas partes: 🔷 y «más riesgo». Una doble de dos de éstas paga
~2,10 y se cumple ~50 % de las veces; una de éstas con una del primer nivel,
~1,65 y ~62 %.

Uso: `del_dia(r, dia)` para la Capa 1 y Telegram; `del_pick(pick)` para la
tarjeta (`modo_modelo.recomendadas` la pone primera y «meter»);
`del_pick_riesgo` y `del_dia(r, dia, riesgo=True)` para el segundo nivel.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODELO_MIN = 0.70
CASA_MIN = 0.80
CASA_MAX = 0.88
CUOTA_MIN = 1.10
RIESGO_CASA_MIN = 0.55
RIESGO_CASA_MAX = 0.70
RIESGO_MODELO_MIN = 0.70
RIESGO_CASA_ALTA = 0.65          # con la casa ya en 65-70 % …
RIESGO_MODELO_MIN_ALTA = 0.60    # … basta el modelo en 60 %
RIESGO_CUOTA_MIN = 1.35
NOTA_RIESGO = ('ganador con la casa sin margen entre 55 % y 70 % y el modelo en '
               '70 % o más (60 % si la casa ya da 65 %): en 2.354 partidos fuera '
               'de muestra acertó 71-72 % a cuota media 1,43')
# lo medido de cada grupo (`_v317_capa1.json`, tramo de juzgar)
ACIERTO_CAPA1 = {'Doble oportunidad': 0.85, '1X2': 0.87}
ACIERTO_RIESGO = 0.72
NOTA = ('resultado con el modelo en 70 % o más y la casa sin margen entre 80 % '
        'y 88 %: en 60.796 partidos fuera de muestra acertó 85 % en doble '
        'oportunidad y 87 % en ganador')

# v350 — LA MISMA REGLA, EN EL GANADOR DE LA NFL Y LA NBA.
#
# El usuario pidió meter más deportes en la Capa 1, «con la misma metodología
# del fútbol». Se replicó tal cual (modelo ≥ 70 %, casa sin margen 80-88 %,
# cuota ≥ 1,10) sobre la réplica sin fuga de cada deporte (`_v350_ganador.py`:
# cada temporada con un modelo que no la vio, moneyline de cierre):
#
#                elige 2010-20      juzga 2021-25    por temporada
#     NFL        83,6 % (214)       84,4 % (109)     ~22
#     NBA        83,2 % (1.609)     83,6 % (657)     ~130
#
# Rinde −3/−4 % al cierre, como la del fútbol: es la apuesta más segura del
# deporte, no una ganancia prometida. Los precios de estos deportes ya salen
# de las casas del usuario (`alpha_finder`, v193). La pretemporada de la NBA
# no entra (no se mide). El 🔷 de más riesgo sigue siendo sólo del fútbol: en
# la NBA la casa sabe más que el modelo (`concordancia.PESO_MODELO_NBA`).
DEPORTES_DOS_VIAS = ('NFL', 'NBA')
ACIERTO_CAPA1_DEPORTE = {'NFL': 0.84, 'NBA': 0.84}


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def del_pick(pick: Dict) -> Optional[Dict]:
    """La mejor apuesta de resultado del partido que cumple el criterio, o
    None. Nunca lanza."""
    try:
        if str(pick.get('deporte') or '') in DEPORTES_DOS_VIAS:
            return _del_pick_dos_vias(pick)
        if str(pick.get('deporte') or 'Fútbol') != 'Fútbol' or pick.get('jugado') \
                or pick.get('solo_mercado') or pick.get('sin_modelo'):
            return None
        par = str(pick.get('partido') or '')
        if ' vs ' not in par:
            return None
        h, a = par.split(' vs ', 1)
        b = pick.get('board') or {}
        mh, md, ma = _f(b.get('Gana ' + h)), _f(b.get('Empate')), _f(b.get('Gana ' + a))
        im = pick.get('implicitas') or {}
        q = im.get('1x2') or {}
        qh, qd, qa = _f(q.get('home')), _f(q.get('draw')), _f(q.get('away'))
        if None in (mh, md, ma, qh, qd, qa):
            return None
        c1 = im.get('1x2_cuotas') or {}
        cd = im.get('doble_cuotas') or {}
        opciones = [
            ('1X2', 'Gana %s' % h, mh, qh, _f(c1.get('home'))),
            ('1X2', 'Gana %s' % a, ma, qa, _f(c1.get('away'))),
            ('Doble oportunidad', '%s o empate' % h, mh + md, qh + qd, _f(cd.get('1X'))),
            ('Doble oportunidad', '%s o empate' % a, ma + md, qa + qd, _f(cd.get('X2'))),
        ]
        # sólo en las casas del usuario (v315: Playdoit, Novibet, Draftea)
        casa = im.get('casa') or pick.get('casa')
        try:
            import mercado_sin_modelo as _msm
            if casa not in _msm.CASAS_USUARIO:
                return None
        except Exception:
            pass
        buenas = [o for o in opciones
                  if o[2] >= MODELO_MIN and CASA_MIN <= o[3] < CASA_MAX
                  and o[4] is not None and o[4] >= CUOTA_MIN]
        if not buenas:
            return None
        # la que más paga de las que cumplen (a igual criterio medido)
        mer, ap, pm, pc, cu = max(buenas, key=lambda o: o[4])
        return {'mercado': mer, 'bloque': 'resultado', 'etiqueta': 'Resultado',
                'apuesta': ap, 'prob': round(pm, 4), 'p_mercado': round(pc, 4),
                'cuota': round(cu, 3), 'casa': casa,
                'linea': None, 'elite': True,
                'razon': 'Capa 1: el modelo %.0f %% y la casa %.0f %% de acuerdo '
                         '(medido: ~85 %% de acierto)' % (100 * pm, 100 * pc)}
    except Exception as e:
        logger.debug('[lo_mejor] %s: %s', pick.get('partido'), e)
        return None


def _del_pick_dos_vias(pick: Dict) -> Optional[Dict]:
    """v350 — el 🏆 del ganador de la NFL y la NBA (ver `DEPORTES_DOS_VIAS`)."""
    dep = str(pick.get('deporte') or '')
    if pick.get('jugado') or pick.get('pretemporada') or pick.get('solo_mercado') \
            or pick.get('sin_modelo'):
        return None
    par = str(pick.get('partido') or '')
    if ' vs ' not in par:
        return None
    h, a = par.split(' vs ', 1)
    b = pick.get('board') or {}
    mh, ma = _f(b.get('Gana ' + h)), _f(b.get('Gana ' + a))
    c1 = (pick.get('implicitas') or {}).get('1x2_cuotas') or {}
    ch, ca = _f(c1.get('home')), _f(c1.get('away'))
    if None in (mh, ma, ch, ca) or ch <= 1 or ca <= 1:
        return None
    s = 1.0 / ch + 1.0 / ca
    qh, qa = (1.0 / ch) / s, (1.0 / ca) / s
    buenas = [o for o in (('Gana %s' % h, mh, qh, ch), ('Gana %s' % a, ma, qa, ca))
              if o[1] >= MODELO_MIN and CASA_MIN <= o[2] < CASA_MAX and o[3] >= CUOTA_MIN]
    if not buenas:
        return None
    ap, pm, pc, cu = buenas[0]
    return {'mercado': '1X2', 'bloque': 'resultado', 'etiqueta': 'Resultado',
            'apuesta': ap, 'prob': round(pm, 4), 'p_mercado': round(pc, 4),
            'cuota': round(cu, 3), 'casa': pick.get('casa'), 'deporte': dep,
            'linea': None, 'elite': True,
            'razon': 'Capa 1: el modelo %.0f %% y la casa %.0f %% de acuerdo '
                     '(medido en la %s: ~84 %% de acierto)' % (100 * pm, 100 * pc, dep)}


def del_pick_riesgo(pick: Dict) -> Optional[Dict]:
    """🔷 El segundo nivel: ganador a cuota ~1,40-1,75 que el modelo ve claro.
    Nunca lanza."""
    try:
        if str(pick.get('deporte') or 'Fútbol') != 'Fútbol' or pick.get('jugado') \
                or pick.get('solo_mercado') or pick.get('sin_modelo'):
            return None
        par = str(pick.get('partido') or '')
        if ' vs ' not in par:
            return None
        h, a = par.split(' vs ', 1)
        b = pick.get('board') or {}
        im = pick.get('implicitas') or {}
        casa = im.get('casa') or pick.get('casa')
        try:
            import mercado_sin_modelo as _msm
            if casa not in _msm.CASAS_USUARIO:
                return None
        except Exception:
            pass
        q = im.get('1x2') or {}
        c1 = im.get('1x2_cuotas') or {}
        mejores = []
        for lado, eq in (('home', h), ('away', a)):
            pm, pc, cu = _f(b.get('Gana ' + eq)), _f(q.get(lado)), _f(c1.get(lado))
            if None in (pm, pc, cu) or not (RIESGO_CASA_MIN <= pc < RIESGO_CASA_MAX):
                continue
            if cu < RIESGO_CUOTA_MIN:
                continue
            if pm >= RIESGO_MODELO_MIN or (pc >= RIESGO_CASA_ALTA
                                           and pm >= RIESGO_MODELO_MIN_ALTA):
                mejores.append((eq, pm, pc, cu))
        if not mejores:
            return None
        eq, pm, pc, cu = max(mejores, key=lambda o: o[1])
        return {'mercado': '1X2', 'bloque': 'resultado', 'etiqueta': 'Resultado',
                'apuesta': 'Gana %s' % eq, 'prob': round(pm, 4),
                'p_mercado': round(pc, 4), 'cuota': round(cu, 3), 'casa': casa,
                'linea': None, 'riesgo': True,
                'razon': '🔷 más riesgo: el modelo %.0f %% y la casa %.0f %% '
                         '(medido: 71-72 %% de acierto a cuota ~1,43)'
                         % (100 * pm, 100 * pc)}
    except Exception as e:
        logger.debug('[lo_mejor] riesgo %s: %s', pick.get('partido'), e)
        return None


def del_dia(r: Dict, dia: Optional[str] = None, riesgo: bool = False) -> List[Dict]:
    """Las de un día (fecha CDMX) o de todos, listas para la Capa 1 y
    Telegram, ordenadas por lo que cree la casa (las de riesgo, por lo que
    cree el modelo). Nunca lanza."""
    out = []
    for p in (r.get('pronosticos') or []):
        if not isinstance(p, dict):
            continue
        if dia and str(p.get('fecha_cdmx') or p.get('fecha') or '')[:10] != dia:
            continue
        e = del_pick_riesgo(p) if riesgo else del_pick(p)
        if not e:
            continue
        out.append(_entrada(p, e, riesgo))
    out.sort(key=lambda x: -(x['prob'] if riesgo else x['p_mercado']))
    return out


def _entrada(p: Dict, e: Dict, riesgo: bool) -> Dict:
    """La fila de la Capa 1 y de Telegram para la apuesta `e` del partido `p`."""
    dep = str(p.get('deporte') or 'Fútbol')
    return dict(e, partido=p.get('partido'), liga=p.get('liga'),
                clave_liga=p.get('clave_liga'), deporte=dep,
                inicio=p.get('inicio'), fecha=p.get('fecha'),
                fecha_cdmx=p.get('fecha_cdmx'),
                hora=p.get('hora_cdmx') or p.get('hora_txt'),
                # la columna «acierta» de la Capa 1 enseña lo MEDIDO del
                # grupo, no la probabilidad del modelo (que va en la ayuda)
                prob_escalera=(ACIERTO_RIESGO if riesgo else
                               ACIERTO_CAPA1_DEPORTE.get(dep) or
                               ACIERTO_CAPA1.get(e['mercado'], 0.85)),
                semaforo={'nivel': 'riesgo' if riesgo else 'verde',
                          'etiqueta': '%smodelo %.0f %% · casa %.0f %%'
                                      % ('🔷 más riesgo · ' if riesgo else '',
                                         100 * e['prob'], 100 * e['p_mercado'])})


def resultado(apuesta: str, partido: str, goles_home, goles_away) -> Optional[str]:
    """'verde', 'rojo' o None (sin marcador) para «Gana X» y «X o empate»."""
    gh, ga = _f(goles_home), _f(goles_away)
    par = str(partido or '')
    if gh is None or ga is None or ' vs ' not in par:
        return None
    h, a = par.split(' vs ', 1)
    ap = str(apuesta or '')
    if ap == 'Gana %s' % h:
        ok = gh > ga
    elif ap == 'Gana %s' % a:
        ok = ga > gh
    elif ap == '%s o empate' % h:
        ok = gh >= ga
    elif ap == '%s o empate' % a:
        ok = ga >= gh
    else:
        return None
    return 'verde' if ok else 'rojo'


def finalizados(jugados: List[Dict], riesgo: bool = False) -> List[Dict]:
    """v342 — LA CAPA 1 DE LOS PARTIDOS QUE YA EMPEZARON, CON SU RESULTADO.

    El usuario: «cuando termina el partido, la predicción de Capa 1
    desaparece; quiero que se ilumine de verde si se dio o de rojo si no».
    Desaparecía porque el barrido sólo guarda lo que está por jugarse. Aquí se
    rehace con el pick ARCHIVADO al empezar (`partidos_jugados`, con los
    precios de antes del pitido) —el mismo criterio, `del_pick`— y se le pega
    el marcador: `resultado_c1` es 'verde', 'rojo' o 'vivo' (empezado y aún
    sin marcador). Nunca lanza."""
    out = []
    for p in (jugados or []):
        if not isinstance(p, dict) or p.get('aplazado'):
            continue
        try:
            q = {k: v for k, v in p.items()
                 if k not in ('jugado', 'en_juego', 'archivado_del_pronostico')}
            e = del_pick_riesgo(q) if riesgo else del_pick(q)
            if not e:
                continue
            fila = _entrada(p, e, riesgo)
            res = resultado(e['apuesta'], p.get('partido'),
                            p.get('goles_home'), p.get('goles_away'))
            fila['resultado_c1'] = res or 'vivo'
            if res:
                fila['marcador'] = '%d-%d' % (int(_f(p.get('goles_home'))),
                                              int(_f(p.get('goles_away'))))
            out.append(fila)
        except Exception as ex:
            logger.debug('[lo_mejor] finalizado %s: %s', p.get('partido'), ex)
    out.extend(_capa1_anunciada(jugados, out, riesgo))
    out.sort(key=lambda x: str(x.get('inicio') or ''))
    return out


def _capa1_anunciada(jugados: List[Dict], ya: List[Dict], riesgo: bool) -> List[Dict]:
    """v346 — lo que la Capa 1 enseñó ANTES y ya no estaba al empezar el
    partido (`anunciadas`), con su resultado y marcado 📌: quien lo apostó
    también quiere verlo en verde o en rojo. Nunca lanza."""
    try:
        import anunciadas as an
    except Exception:
        return []
    nivel = '🔷' if riesgo else '🏆'
    vistos = {(str(f.get('partido')), f.get('apuesta')) for f in ya}
    out = []
    for p in (jugados or []):
        if not isinstance(p, dict) or p.get('aplazado'):
            continue
        for a in an.capa1_del_partido(p):
            if a.get('nivel') != nivel or (str(p.get('partido')), a['apuesta']) in vistos:
                continue
            e = dict(a, linea=None, elite=not riesgo, riesgo=riesgo,
                     razon='anunciada antes del partido')
            fila = _entrada(p, e, riesgo)
            res = resultado(a['apuesta'], p.get('partido'),
                            p.get('goles_home'), p.get('goles_away'))
            fila['resultado_c1'] = res or 'vivo'
            fila['anunciada'] = True
            if res:
                fila['marcador'] = '%d-%d' % (int(_f(p.get('goles_home'))),
                                              int(_f(p.get('goles_away'))))
            vistos.add((str(p.get('partido')), a['apuesta']))
            out.append(fila)
    return out
