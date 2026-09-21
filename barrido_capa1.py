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
    fuera = []
    for v in (doc.get('partidos') or {}).values():
        if isinstance(v, dict) and v.get('home') and v.get('away'):
            fuera.append(v)
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
                'deporte': _bonito(dep),
                'liga': v.get('liga') or '',
                'clave_liga': str(v.get('liga') or '').lower(),
                'partido': '%s vs %s' % (v['home'], v['away']),
                'inicio': v.get('inicio'),
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
            })
            break          # una por partido: la de mejor EV, que va primera
    fuera.sort(key=lambda x: (-int(x['validado']), -(x.get('ev') or 0)))
    return fuera


def _bonito(dep: str) -> str:
    return {'futbol': 'Fútbol', 'tenis': 'Tenis', 'mlb': 'MLB',
            'nba': 'NBA', 'nfl': 'NFL'}.get(dep, dep)


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
