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
    'futbol': {'lados': ('home',), 'ev_min': 0.005, 'prob_min': 0.30,
               'validado': True,
               'nota': 'lado local, validado n=353 · +11,49 % · p5 +1,73 %'},
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
