# -*- coding: utf-8 -*-
"""
v266 — La Capa 1 sobre TODO el tablero, no sólo sobre lo que el modelo conoce.

EL HALLAZGO QUE LO TRAE
La Capa 1 —`valor_vs_sharp`, el único canal con ventaja medida del proyecto
(+9,09 % con p5 +4,13 %)— se calculaba DENTRO de los bucles de cada deporte,
así que sólo veía los partidos para los que hay modelo y calendario.

Pero `valor_vs_sharp` **no usa el modelo para nada**. Sólo necesita el precio
justo de Pinnacle y una casa donde el usuario pueda apostar. Buscar errores de
cuota únicamente donde hay modelo es como buscar las llaves sólo bajo la
farola.

Medido sobre el tablero del 2026-09-20: de las seis oportunidades que pasan
todos los filtros validados, **cinco estaban en partidos que la aplicación ni
evaluaba**:

    Dobrudzha vs CSKA Sofia II ............ no la evalúa
    Gibson T. vs Ferro F. ................. no la evalúa
    Okamura K. vs Fernandez L. ............ sí
    Kato/Perez vs Sakkari/Vekic ........... no la evalúa
    Ferro/Fruhvirtova vs Tang/Xu .......... no la evalúa
    Santos vs Lobos Plateados ............. no la evalúa

Por eso el usuario veía uno o dos picks al día donde había siete.

LOS FILTROS SON LOS VALIDADOS, NI UNO MÁS NI UNO MENOS
No se relaja nada para sacar más picks. Cada deporte entra con el criterio que
pasó su propia medición, y los que no la pasaron siguen fuera:

    fútbol .... sólo el lado LOCAL. El visitante y el empate lucían bien en el
                tramo de elección y se hundían en el de juicio (visitante
                +7,92 % pero p5 −5,10 %). No es un olvido: está medido.
    tenis ..... sólo WTA. En ATP ninguna configuración sobrevive a los dos
                periodos, y su `Odd_Max` tiene valores atípicos que hay que
                limpiar antes de bajar el listón.
    MLB ....... precio temprano contra cierre, prob ≥ 0,30.
    NFL ....... «no medible»: ESPN sólo conserva multi-casa de una temporada,
                y sin dos precios no hay line shopping que medir.
    NBA ....... sin medición propia todavía. Entra marcado como NO VALIDADO
                para que se acumule histórico y se pueda juzgar, pero se
                distingue en pantalla de lo que sí está medido.

Y el precio tiene que ser ACCIONABLE: de las casas del usuario y de ninguna
otra. Una oportunidad en una casa donde no puede apostar no es una
oportunidad, y usar su cuota inflaría el EV de toda la Capa 1.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TABLERO = 'cuotas_mx.json'

# Lo que cada deporte tiene medido. `lados` a None es «el que sea».
# v269 — la ventaja minima baja de 1 % a 0,5 %. Medido en dos tramos:
#
#     umbral                      eleccion p5    JUICIO p5
#     EV>0,010 prob>=0,30 (antes)   +1,67 %       +0,20 %
#     EV>0,005 prob>=0,30           +1,74 %       +1,31 %   <- gana
#     EV>0,010 prob>=0,15           +0,38 %       -3,31 %
#     EV>0,005 prob>=0,15           +1,14 %       -0,25 %
#
# Da un 12 % mas de picks (1.820 contra 1.629) y un p5 seis veces mejor
# en el tramo de juicio. La PROBABILIDAD no se toca: bajarla se hunde.
REGLAS = {
    # v297.4 — EL VISITANTE SE ABRE, Y LO DESTAPO UN BOLETO DEL USUARIO.
    #
    # Esto decia `('home',)`, asi que el barrido TIRABA todos los picks del
    # visitante antes de enseñarlos. No era una omision de medicion: era una
    # puerta cerrada en produccion. Por eso cada pick del tablero empezaba por
    # «Gana» y el nombre del local, siempre.
    #
    # El 2026-09-21 el usuario enseño un parlay ganador de Novibet con el Dila
    # Gori @2,25 y el CSKA Sofia II @2,08, los dos VISITANTES, en los dos
    # partidos donde la Capa 1 apuntaba al local: Spaeri perdio 1-4 en casa y
    # Dobrudzha perdio 1-3 en casa.
    #
    # Medido despues sobre el ledger, con la misma regla y el mismo bootstrap:
    #
    #     canal        eleccion (70 %)        juicio (30 %)
    #     local      +6,81 % (p5 +1,58)   +10,67 % (p5 +2,79)
    #     visitante  +7,55 % (p5 +1,03)   +13,14 % (p5 +2,50)   n=1.326
    #
    # El visitante rinde IGUAL O MAS. Y su mejor banda es justo la del boleto:
    # cuota 1,50-1,80, n=89, acierta el 75,3 %, ROI +24,09 %, p5 +11,65 %.
    #
    # Tiene sentido que sea asi: un visitante al que Pinnacle hace favorito en
    # una liga pequeña es donde mas se equivoca la casa blanda, porque el
    # sesgo de local es justo lo que esas casas cobran de mas.
    'futbol': {'lados': None, 'ev_min': 0.005, 'prob_min': 0.30,
               'validado': True,
               'nota': 'los dos lados, medidos por separado: local n=1.803 '
                       '+6,81 %/+10,67 % · visitante n=1.326 +7,55 %/+13,14 %, '
                       'p5 positivo en los cuatro tramos'},
    'tenis': {'lados': None, 'ev_min': 0.005, 'prob_min': 0.30,
              'validado': True, 'circuitos': ('wta',),
              'nota': 'sólo WTA, validado n=2.436 · +4,22 % · p5 +0,61 %'},
    'mlb': {'lados': None, 'ev_min': 0.02, 'prob_min': 0.30,
            'validado': True,
            'nota': 'precio temprano vs cierre, n=2.658 · +5,01 % · p5 +1,67 %'},
    'nba': {'lados': None, 'ev_min': 0.03, 'prob_min': 0.30,
            'validado': False,
            'nota': 'SIN medición propia: se acumula para poder juzgarlo'},
    'nfl': {'lados': None, 'ev_min': 0.03, 'prob_min': 0.30,
            'validado': False,
            'nota': 'no medible: ESPN sólo guarda multi-casa de una temporada'},
}

# Por debajo de esto no es una apuesta. El mismo suelo que el resto del
# proyecto usa para no proponer trámites de 1,05.
MIN_CUOTA = 1.15


def _tablero(ruta: str = TABLERO) -> List[Dict]:
    """Los partidos del tablero, con su deporte. Nunca lanza."""
    import json
    import os
    if not os.path.exists(ruta):
        return []
    try:
        with open(ruta, encoding='utf-8') as f:
            doc = json.load(f) or {}
    except Exception as e:
        logger.warning('[capa1] no se pudo leer %s: %s', ruta, e)
        return []
    # v275 — LOS QUE YA EMPEZARON, FUERA.
    #
    # `cuotas_mx.json` se commitea al repositorio y el contenedor lo recibe con
    # la edad que tenga. Si el cron se salta pasadas —y se las salta: medido
    # el 2026-09-21, once horas sin correr con un cron de dos— el fichero
    # puede traer partidos que ya se jugaron. Ofrecer un pick de un partido
    # terminado no es un fallo de presentacion: es mandar a apostar algo que
    # ya no existe.
    import time as _t
    ahora = _t.time()
    fuera, pasados = [], 0
    for v in (doc.get('partidos') or {}).values():
        if not (isinstance(v, dict) and v.get('home') and v.get('away')):
            continue
        try:
            if float(v.get('inicio') or 0) <= ahora:
                pasados += 1
                continue
        except (TypeError, ValueError):
            pass
        fuera.append(v)
    if pasados:
        logger.info('[capa1] %d partidos del tablero ya habian empezado',
                    pasados)
    return fuera


def _pasa(dep: str, v: Dict, val: Dict, regla: Dict) -> bool:
    """Los filtros validados de ese deporte, sin relajar ninguno."""
    if (val.get('ev') or 0) < regla['ev_min']:
        return False
    if (val.get('prob_justa') or 0) < regla['prob_min']:
        return False
    if (val.get('cuota') or 0) < MIN_CUOTA:
        return False
    lados = regla.get('lados')
    if lados and val.get('lado') not in lados:
        return False
    circ = regla.get('circuitos')
    if circ:
        liga = str(v.get('liga') or '').lower()
        if not any(c in liga for c in circ):
            return False
    return True


def barrer(ruta: str = TABLERO, incluir_no_validados: bool = True) -> List[Dict]:
    """Todos los errores de cuota del tablero. NUNCA lanza.

    Devuelve picks con la misma forma que los de la Capa 1 de `alpha_finder`,
    más `validado` para que la pantalla pueda separar lo medido de lo que
    todavía se está midiendo.
    """
    try:
        import cuotas_multi as cm
    except Exception as e:
        logger.warning('[capa1] sin cuotas_multi: %s', e)
        return []
    fuera: List[Dict] = []
    vistos = set()
    for v in _tablero(ruta):
        dep = str(v.get('deporte') or '').lower()
        regla = REGLAS.get(dep)
        if not regla:
            continue
        if not regla['validado'] and not incluir_no_validados:
            continue
        try:
            r = cm.valor_vs_sharp(dep, v['home'], v['away'])
        except Exception as e:
            logger.debug('[capa1] %s vs %s: %s', v['home'], v['away'], e)
            continue
        # v271 — SE GUARDA LO QUE SE ACABA DE VER.
        #
        # Aquí Pinnacle y la casa blanda están emparejados, que es justo el
        # dato que el radar necesita para aprender. Existía sólo un instante
        # en memoria y se tiraba. No cuesta ninguna petición: la consulta ya
        # está pagada. Ver `radar_capturas`.
        try:
            import radar_capturas as _cap
            _cap.anotar(v, (r or {}).get('pinnacle') or {},
                        (r or {}).get('valor'))
        except Exception as _e:
            logger.debug('[capa1] no se pudo anotar la captura: %s', _e)
        if not (r or {}).get('prob_justa'):
            continue
        # v276 — EL MARGEN DE PINNACLE VIAJA CON EL PICK.
        #
        # No es un adorno: es la puerta que decide si este pick esta dentro de
        # lo que se valido. Toda la medicion de la Capa 1 (1.820 apuestas,
        # +7,77 % de ROI) se hizo con partidos donde Pinnacle cobra MENOS del
        # 7 % de margen; por encima de eso hay SIETE apuestas en cuatro años y
        # medio. Ver `semaforo_capa1`.
        _mp = None
        try:
            _pin = (r.get('pinnacle') or {})
            _vs = [float(_pin[_k]) for _k in ('home', 'draw', 'away')
                   if _pin.get(_k)]
            if len(_vs) >= 2:
                _mp = round(sum(1.0 / _v for _v in _vs) - 1.0, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            _mp = None
        for val in (r.get('valor') or []):
            if not isinstance(val, dict):
                continue
            if not _pasa(dep, v, val, regla):
                continue
            lado = val.get('lado')
            nombre = v['home'] if lado == 'home' else v['away']
            clave = (dep, str(v['home']), str(v['away']), lado)
            if clave in vistos:
                continue
            vistos.add(clave)
            fuera.append({
                'deporte': _bonito(dep, v.get('liga')),
                'liga': v.get('liga') or '',
                'clave_liga': str(v.get('liga') or '').lower(),
                'partido': '%s vs %s' % (v['home'], v['away']),
                'inicio': v.get('inicio'),
                # v279 — `inicio` es una marca de tiempo Unix y la pantalla
                # espera una fecha. Sin esto la tarjeta decia «fecha no
                # disponible» en todos los picks del barrido.
                'fecha': _fecha_de(v.get('inicio')),
                'mercado': 'Ganador',
                'apuesta': 'Gana %s' % nombre,
                'prob': round(float(val['prob_justa']), 3),
                'cuota': val['cuota'],
                'cuota_justa': val.get('cuota_justa'),
                'ev': val['ev'],
                'casa': val.get('casa'),
                'lado': lado,
                'valor': '🟢', 'evc': True, 'valor_mercado': True,
                'validado': bool(regla['validado']),
                'nota_canal': regla['nota'],
                'origen': 'line shopping vs Pinnacle (barrido completo)',
                'margen_pin': _mp,
                # v297 — LA SEGUNDA PATA, PARA LA COMBINADA DEL MISMO PARTIDO.
                #
                # El «más de 2,5» de ESTE partido y de LA MISMA CASA. Tiene
                # que ser la misma casa o el usuario no puede meter las dos
                # patas en un boleto, y una combinada repartida entre dos
                # casas no es una combinada: son dos apuestas sueltas.
                #
                # Va aquí y no en un barrido aparte porque el precio ya está
                # en la mano: `v['casas'][casa]` es justo lo que se acaba de
                # leer para el 1X2.
                'over25': _over25_de(v, val.get('casa')),
                'combi': _pata_combinada(v, r, lado),
            })
            break          # una por partido: la de mejor EV, que va primera
    # v283 — y las discrepancias del mercado de goles, que es el que el
    # usuario juega de verdad. Van marcadas como no validadas: ver
    # `barrer_goles`.
    try:
        fuera.extend(barrer_goles(ruta))
    except Exception as e:
        logger.warning('[capa1] el barrido de goles fallo: %s: %s',
                       type(e).__name__, e)
    fuera.sort(key=lambda x: (-int(x['validado']), -(x.get('ev') or 0)))
    return fuera


def _fecha_de(inicio) -> str:
    """La fecha del partido en formato AAAA-MM-DD, o cadena vacia."""
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(float(inicio)).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError, OverflowError):
        return ''



# ---------------------------------------------------------------------------
# v283 — EL MERCADO DE GOLES, POR DISCREPANCIA DE PRECIO
# ---------------------------------------------------------------------------
# POR QUE ESTE CANAL EXISTE
#
# El usuario juega «mas de 1.5», «mas de 2.5» y «ambos anotan»: son sus
# mercados. Y una busqueda a fondo del 2026-09-21 dejo claro que NO se pueden
# elegir con el modelo: 23 reglas distintas sobre 17.447 partidos con cuota y
# resultado —umbrales de EV del 2 al 15 %, brechas contra el mercado de 5, 10
# y 15 puntos, confianza del modelo, combinaciones, y las 20 ligas por
# separado— y NINGUNA sobrevive a los dos tramos. Todas negativas en juicio,
# la mayoria entre -4 % y -12 %.
#
# Pero eso descarta una FORMA de elegirlos, no el mercado. El mecanismo que si
# esta validado en este proyecto es otro: comparar lo que paga la casa contra
# el precio justo de Pinnacle. Eso no usa el modelo para nada.
#
# Y aqui si hay ancla, que es lo que fallo al intentarlo con «ambos anotan»:
#
#     Pinnacle publica «ambos anotan» en    50 de 521 partidos  -> imposible
#     Pinnacle publica TOTALES en          405 de 405 partidos  -> viable
#
# LO QUE ESTE CANAL NO TIENE, Y HAY QUE DECIRLO
# No esta validado sobre historico. El mecanismo es el mismo que el del 1X2
# —que si lo esta, +7,77 % sobre 1.820 apuestas— pero el mercado es otro y no
# hay forma de comprobarlo hacia atras: los ledgers guardan la cuota de UNA
# casa, no el par casa-blanda/Pinnacle que haria falta.
#
# Por eso entra marcado como NO VALIDADO. Acumula su propio historico y se
# juzgara cuando lo tenga, igual que se hizo con todo lo demas.
def _over25_de(v: Dict, casa) -> Optional[Dict]:
    """El «más de 2,5» de ese partido en esa casa. None si no está.

    v297 — La segunda pata de la combinada. La probabilidad sale de quitarle
    el vig a la pareja over/under de LA PROPIA CASA, no de Pinnacle: aquí no
    se busca un error de precio en esta pata, sólo saber lo que vale para
    calcular la conjunta. El error de precio lo pone la pata del 1X2, y la
    ventaja de la combinada la pone la correlación (ver `combinada.py`).

    NUNCA lanza.
    """
    try:
        mk = ((v.get('casas') or {}).get(casa) or {})
        ou = (mk.get('OVER_UNDER') or {})
        for L in (ou.get('lineas') or []):
            try:
                if abs(float(L.get('linea')) - 2.5) > 1e-6:
                    continue
                cu_ov, cu_un = float(L.get('over')), float(L.get('under'))
            except (TypeError, ValueError):
                continue
            if not (cu_ov > 1 and cu_un > 1):
                continue
            s = 1.0 / cu_ov + 1.0 / cu_un
            return {'cuota': cu_ov,
                    'prob': round((1.0 / cu_ov) / s, 4),
                    'margen': round(s - 1.0, 4),
                    'casa': casa}
    except Exception as e:
        logger.debug('[capa1/over25] %s', e)
    return None


def _num_seguro(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _pata_combinada(v: Dict, r: Dict, lado: str = 'home') -> Optional[Dict]:
    """Las DOS patas de la combinada, en una casa que tenga las dos cosas.

    v297.1 — LA PRIMERA VERSION NO SACABA NINGUNA, Y POR UN MOTIVO REAL.
    Se pedia el «más de 2,5» en la casa que gana el line shopping, y en las
    ligas pequeñas —que es donde la Capa 1 encuentra sus errores— esa casa
    publica el 1X2 y NO publica totales. Medido el 2026-09-21: de diez picks
    vivos, diez sin línea de 2,5 en su casa (Novibet y Playdoit, `lineas=[]`).

    Asi que se busca la mejor casa que ofrezca LAS DOS. El precio del 1X2 sale
    peor que el del line shopping puro, y da igual mientras siga teniendo EV
    contra Pinnacle: la medicion de `combinada.py` filtra exactamente por eso
    —EV > 0,5 % con el precio que se use— asi que el resultado sigue valiendo.

    Lo que NO se hace es repartir las patas entre dos casas. Eso no es una
    combinada, son dos apuestas sueltas, y el usuario enseñó un boleto único.

    NUNCA lanza.
    """
    try:
        # v297.2 — HAY QUE MIRAR TODAS LAS CASAS, NO SOLO LAS QUE GANAN.
        #
        # `r['valor']` solo lista las casas que baten a Pinnacle, y en estas
        # ligas es UNA sola (Novibet), justo la que no publica totales. Pero
        # la linea de 2,5 SI existe en otras: de diez picks vivos, seis la
        # tenian en Calientemx o 1xBet.
        #
        # Asi que se recorre el tablero entero y se le calcula el EV a cada
        # casa con el mismo justo de Pinnacle. Sigue siendo la misma regla
        # —que la casa pague por encima del justo— solo que aplicada a todas.
        #
        # v297.3 — Y EL LADO SALE DEL PICK, NO SIEMPRE «home».
        #
        # La primera version lo tenia fijo en el local, que es el mismo punto
        # ciego que el usuario destapo con su boleto: gano con el Dila Gori y
        # el CSKA Sofia II, los dos VISITANTES, en los dos partidos donde la
        # Capa 1 apuntaba al local. Medido despues sobre 1.326 picks, el
        # canal del visitante rinde igual o mas que el del local
        # (+7,55 %/+13,14 % contra +6,81 %/+10,67 %, p5 positivo en los dos
        # tramos), asi que dejarlo fuera de la combinada seria repetir el
        # fallo a proposito.
        lado = 'away' if str(lado) == 'away' else 'home'
        pr = _num_seguro((r or {}).get('prob_justa', {}).get(lado))
        if pr is None or not (0 < pr <= 1):
            return None
        mejor = None
        for casa, mk in ((v or {}).get('casas') or {}).items():
            try:
                cu = float(((mk or {}).get('HOME_DRAW_AWAY') or {})
                           .get(lado))
            except (TypeError, ValueError):
                continue
            if not cu > 1:
                continue
            ev = pr * cu - 1.0
            if ev <= 0.005:
                continue
            ou = _over25_de(v, casa)
            if not ou:
                continue
            val = {'casa': casa}
            # la que deje la combinada mas alta, que es la que mas paga por
            # el mismo riesgo
            total = cu * float(ou['cuota'])
            if mejor is None or total > mejor['cuota_total']:
                mejor = {'casa': val.get('casa'), 'cuota_1x2': cu,
                         'prob_1x2': round(pr, 4), 'ev_1x2': round(ev, 4),
                         'over25': ou, 'cuota_total': round(total, 2)}
        return mejor
    except Exception as e:
        logger.debug('[capa1/combi] %s', e)
        return None


def barrer_goles(ruta: str = TABLERO) -> List[Dict]:
    """Discrepancias en el mercado de goles. NUNCA lanza.

    Misma regla que el 1X2: la casa paga por encima del justo de Pinnacle.
    """
    try:
        import cuotas_multi as cm
    except Exception as e:
        logger.warning('[capa1/goles] sin cuotas_multi: %s', e)
        return []
    try:
        totales = cm.totales_del_deporte('futbol') or {}
    except Exception as e:
        logger.warning('[capa1/goles] sin totales de Pinnacle: %s', e)
        return []
    if not totales:
        return []

    fuera: List[Dict] = []
    vistos = set()
    for v in _tablero(ruta):
        if str(v.get('deporte') or '').lower() != 'futbol':
            continue
        try:
            clave = '%s|%s' % (cm.normalizar(v.get('home') or ''),
                               cm.normalizar(v.get('away') or ''))
            pin = totales.get(clave) or {}
            if not pin:
                continue
            for casa, mk in (v.get('casas') or {}).items():
                ou = (mk or {}).get('OVER_UNDER') or {}
                for L in (ou.get('lineas') or []):
                    try:
                        linea = float(L.get('linea'))
                    except (TypeError, ValueError):
                        continue
                    p = (pin.get(str(linea))
                         or pin.get('%.1f' % linea) or {})
                    try:
                        pm, pn = float(p.get('mas')), float(p.get('menos'))
                    except (TypeError, ValueError):
                        continue
                    if not (pm > 1 and pn > 1):
                        continue
                    sm = 1.0 / pm + 1.0 / pn
                    margen = sm - 1.0
                    for lado, campo, pin_cu in (('over', 'over', pm),
                                                ('under', 'under', pn)):
                        try:
                            cu = float(L.get(campo))
                        except (TypeError, ValueError):
                            continue
                        q = (1.0 / pin_cu) / sm
                        ev = q * cu - 1.0
                        if ev < 0.005 or q < 0.30 or cu < MIN_CUOTA:
                            continue
                        k = (str(v.get('home')), str(v.get('away')), linea,
                             lado)
                        if k in vistos:
                            continue
                        vistos.add(k)
                        etq = ('Más de %.1f goles' % linea if lado == 'over'
                               else 'Menos de %.1f goles' % linea)
                        fuera.append({
                            'deporte': 'Fútbol',
                            'liga': v.get('liga') or '',
                            'clave_liga': str(v.get('liga') or '').lower(),
                            'partido': '%s vs %s' % (v['home'], v['away']),
                            'inicio': v.get('inicio'),
                            'fecha': _fecha_de(v.get('inicio')),
                            'mercado': 'Goles',
                            'apuesta': etq,
                            'prob': round(q, 3),
                            'cuota': cu,
                            'cuota_justa': round(1.0 / q, 3) if q else None,
                            'ev': round(ev, 4),
                            'casa': casa,
                            'lado': '%s_%.1f' % (lado, linea),
                            'valor': '🟢', 'evc': True, 'valor_mercado': True,
                            'validado': False,
                            'margen_pin': round(margen, 4),
                            'nota_canal': (
                                'Mercado de goles por discrepancia de precio. '
                                'El mecanismo es el mismo que ya está validado '
                                'en el ganador, pero este mercado todavía no '
                                'tiene medición propia: está acumulando.'),
                            'origen': 'line shopping vs Pinnacle (goles)',
                        })
        except Exception as e:
            logger.debug('[capa1/goles] %s: %s', v.get('home'), e)
    # v283.1 — UNA LINEA POR PARTIDO, Y NO CINCO.
    #
    # La primera pasada real saco esto:
    #
    #     Mas de 3.0 goles  Montana vs Hebar  @2.49  EV +12,9 %
    #     Mas de 3.2 goles  Montana vs Hebar  @2.81  EV +12,7 %
    #     Mas de 3.5 goles  Montana vs Hebar  @3.08  EV +11,1 %
    #     Mas de 2.8 goles  Montana vs Hebar  @2.08  EV  +7,9 %
    #     Mas de 2.2 goles  Montana vs Hebar  @1.66  EV  +5,6 %
    #
    # Cinco tarjetas que son LA MISMA apuesta a distintas lineas. Quien las
    # meta todas cree que diversifica y esta cargando un solo partido — el
    # mismo fallo que la v278 arreglo para los picks repetidos, con otra cara.
    #
    # Se queda la de mejor EV de cada partido, igual que hace el barrido del
    # ganador. Las alternativas siguen existiendo en el tablero; lo que no
    # existe es la ilusion de que son cinco oportunidades.
    mejor_por_partido = {}
    for p in fuera:
        k = p.get('partido')
        if k not in mejor_por_partido or (
                (p.get('ev') or 0) > (mejor_por_partido[k].get('ev') or 0)):
            mejor_por_partido[k] = p
    n_antes = len(fuera)
    fuera = list(mejor_por_partido.values())
    fuera.sort(key=lambda x: -(x.get('ev') or 0))
    logger.info('[capa1/goles] %d discrepancias en %d partidos '
                '(%d lineas alternativas fuera)',
                len(fuera), len(fuera), n_antes - len(fuera))
    return fuera

def _bonito(dep: str, liga: str = '') -> str:
    """El nombre del deporte para la pantalla.

    v277 — «NBA» ERA MENTIRA LA MITAD DE LAS VECES.

    Flashscore mete TODO el baloncesto bajo el mismo identificador (sportId 3)
    y el proyecto lo llama `nba` desde siempre. El barrido completo del tablero
    saco a la luz lo que eso significaba: el 2026-09-21 aparecieron «Soles vs
    Panteras» y «Santos vs Lobos Plateados» etiquetados como NBA, y son de la
    LNBP mexicana; tambien «Djurgarden vs AIK Basket», que es sueco.

    La clave interna (`nba`) NO se toca: la usan `cuotas_multi.DEPORTES`, las
    REGLAS de aqui y media docena de sitios mas, y renombrarla seria un cambio
    grande para arreglar una etiqueta. Lo que cambia es lo que LEE el usuario,
    que es donde estaba el engaño.
    """
    if dep == 'nba':
        # solo se llama NBA si de verdad lo es; si no, «Baloncesto»
        return 'NBA' if 'nba' in str(liga or '').lower() else 'Baloncesto'
    return {'futbol': 'Fútbol', 'tenis': 'Tenis', 'mlb': 'MLB',
            'nfl': 'NFL'}.get(dep, dep)


def kelly(prob: float, cuota: float, fraccion: float = 0.25,
          tope: float = 0.05) -> Optional[float]:
    """Qué fracción del banco arriesgar, con Kelly fraccionado.

    POR QUÉ FRACCIONADO Y POR QUÉ UN CUARTO. Simulado sobre las 1.629
    apuestas históricas de este canal (2021-2026), con el banco resuelto por
    día:

        plano 1 % fijo ....  2,26x   caída máxima  9,6 %
        Kelly 1/8 .........  2,42x                12,1 %
        Kelly 1/4 .........  4,68x                23,0 %
        Kelly 1/2 .........  7,38x                41,8 %
        Kelly completo ....  9,36x                67,0 %

    Kelly completo dobla el resultado de 1/4 pero con caídas del 67 %, que no
    se aguantan en la práctica: el que va por la mitad de su banco deja de
    apostar. Un cuarto duplica el resultado del plano con una caída que sí se
    tolera. El tope del 5 % existe para que un EV enorme —casi siempre un
    precio mal leído— no se lleve el banco por delante.
    """
    try:
        p, c = float(prob), float(cuota)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0) or c <= 1.0:
        return None
    k = (p * c - 1.0) / (c - 1.0)
    if k <= 0:
        return 0.0
    return round(min(k * float(fraccion), float(tope)), 4)


def main() -> int:
    """Barre el tablón y deja anotado lo que vio.

    EXISTE PARA EL WORKFLOW, NO PARA LA PANTALLA.

    El barrido corre también dentro de la aplicación, pero allí el disco es de
    usar y tirar: Streamlit Cloud rehace el contenedor en cada despliegue y se
    lleva por delante `radar_capturas.csv`. Lo que se anota en la aplicación
    se pierde.

    Aquí no: el workflow de las cuotas corre cada dos horas, anota, y commitea
    el fichero al repositorio. Por eso las capturas crecen de verdad — que es
    lo que el radar necesita para dejar de depender del histórico congelado de
    football-data y aprender sobre las casas que se juegan.
    """
    import logging as _lg
    _lg.basicConfig(level=_lg.INFO, format='%(message)s')
    picks = barrer()
    print('capa 1: %d picks' % len(picks))
    for p in picks[:10]:
        print('   %-7s %-40s %-22s cuota %.2f  EV %+.1f %%  %s'
              % (p.get('deporte'), p.get('partido', '')[:40],
                 p.get('apuesta', '')[:22], p.get('cuota') or 0,
                 100 * (p.get('ev') or 0), p.get('casa') or ''))
    try:
        import radar_capturas as cap
        r = cap.resumen()
        print('capturas del radar: %s filas · %s con error · %s días'
              % (format(r['filas'], ',d'), format(r['con_error'], ',d'),
                 r['dias']))
    except Exception as e:
        print('no se pudo resumir las capturas: %s' % e)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
