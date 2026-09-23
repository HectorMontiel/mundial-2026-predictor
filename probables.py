# -*- coding: utf-8 -*-
"""
v302 — LAS PROBABLES CON BUENA CUOTA: el visitante favorito.

LO QUE PIDIÓ EL USUARIO
    «En apuestas del día veo muy buenas apuestas y de acuerdo al histórico
     cuando finalizan veo que muchas se aciertan. Quiero que esas lleguen
     también a Capa 1 para que puedan entrar a la escalera y tenga apuestas
     más seguras y con buena cuota. Encontrar las probables con buena cuota,
     esa es la idea. No es de encontrar fallos.»

LO QUE SE MIDIÓ (`_v302_probables.py`, 78.020 partidos de `pick_ledger.csv`
con probabilidad FUERA DE MUESTRA del modelo, cierre del mercado y de
Pinnacle; 70 % antiguo = elección, 30 % reciente = juicio, corte 2025-05-04)

Se probaron 293 reglas: favorito del modelo, del mercado, de los dos; doble
oportunidad; y el «constructor» de doble oportunidad + menos de 2,5. NINGUNA
pasa la puerta completa (p5 positivo en los dos tramos). Lo que sale con
claridad es DÓNDE está lo probable que además paga:

    regla (visitante)            n   cuota  acierta  ELECCIÓN       JUICIO
    modelo y Pinnacle >= 55 %,  325   1,61   68,0 %  +8,19 % p5+0,15  +12,55 % p5-0,53
      cuota >= 1,50
    Pinnacle >= 55 %,           859   1,64   63,2 %  +2,25 % p5-3,11   +7,54 % p5-2,01
      cuota >= 1,50

Y lo mismo con el LOCAL favorito no funciona: «modelo >= 60 % y cuota >= 1,50»
da -1,49 % y -1,74 %. El mercado sobrevalora al que juega en casa, así que el
favorito que va de visita sale barato. Es el mismo efecto que destapó el
canal del visitante en la Capa 1 (v297), visto desde la probabilidad en vez
de desde el error de cuota.

Tampoco el «constructor» (doble oportunidad + menos de 2,5) paga cobrado
multiplicando: X2 + menos de 2,5 entra un 12 % más de lo que el producto
supone (31,96 % contra 28,44 %), pero el margen de las dos patas se lo come
(-2,9 % y -6,7 %). Medido y cerrado.

LO QUE ESTO ES Y LO QUE NO
No es Capa 1: no pasa la puerta del p5, y se dice en la etiqueta. Es lo que
la Escalera necesita —acertar a menudo con una cuota que merezca la pena— y
por eso entra en la Escalera con su número (68 % o 63 %) y en la pantalla de
la Capa 1 en un grupo aparte con su nombre, nunca mezclada con las medidas.

Sólo FÚTBOL: el ledger es de fútbol y en los demás deportes no hay empate que
haga de «colchón» en la cuota.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROB_MINIMA = 0.55
CUOTA_MINIMA = 1.50
# Una cuota muy larga con probabilidad >= 55 % es un precio roto, no una
# oportunidad: el justo de 55 % es 1,82, y 2,60 sería +43 % de EV.
CUOTA_MAXIMA = 2.60

# Lo medido, que viaja con cada pick y es lo que enseña la pantalla.
MEDIDO = {
    'ambos': {'acierta': 0.680, 'n': 325, 'eleccion': 0.0819,
              'juicio': 0.1255, 'p5_peor': -0.0053,
              'etiqueta': 'Probable: modelo y mercado de acuerdo',
              'nota': 'Visitante favorito para el modelo y para Pinnacle. '
                      'Medido en 325 partidos: acierta el 68 % y rindió '
                      '+8,2 % y +12,6 % en los dos tramos. No es ventaja '
                      'medida del todo: su p5 roza el cero.'},
    'mercado': {'acierta': 0.632, 'n': 859, 'eleccion': 0.0225,
                'juicio': 0.0754, 'p5_peor': -0.0311,
                'etiqueta': 'Probable: favorito del mercado',
                'nota': 'Visitante favorito según Pinnacle (el modelo no '
                        'cubre esta liga). Medido en 859 partidos: acierta el '
                        '63 % y rindió +2,3 % y +7,5 %. Más flojo que cuando '
                        'el modelo también lo ve.'},
}


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _prob_modelo(pronosticos: Optional[List[Dict]]) -> Dict[str, float]:
    """{'home|away' normalizado: p_visitante del modelo}."""
    fuera: Dict[str, float] = {}
    try:
        import cuotas_multi as cm
        norm = cm.normalizar
    except Exception:
        def norm(x):
            return str(x or '').strip().lower()
    for p in (pronosticos or []):
        if not isinstance(p, dict):
            continue
        if str(p.get('deporte') or '') not in ('Fútbol', 'futbol', ''):
            continue
        par = str(p.get('partido') or '')
        if ' vs ' not in par:
            continue
        h, a = par.split(' vs ', 1)
        pv = _num((p.get('board') or {}).get('Gana %s' % a))
        if pv is not None:
            fuera['%s|%s' % (norm(h), norm(a))] = pv
    return fuera


def barrer(pronosticos: Optional[List[Dict]] = None,
           ruta: Optional[str] = None) -> List[Dict]:
    """Las probables del tablero, de más a menos probable. NUNCA lanza.

    `pronosticos` es la lista del precálculo del día: de ahí sale la
    probabilidad del modelo cuando la liga la cubre. Sin ella la regla cae a
    la versión de sólo mercado, que está medida aparte y se etiqueta así.
    """
    try:
        import barrido_capa1 as bc
        import cuotas_multi as cm
    except Exception as e:
        logger.warning('[probables] sin dependencias: %s', e)
        return []
    modelo = _prob_modelo(pronosticos)
    fuera: List[Dict] = []
    vistos = set()
    try:
        tablero = bc._tablero(ruta or bc.TABLERO)
    except Exception as e:
        logger.warning('[probables] tablero ilegible: %s', e)
        return []
    for v in tablero:
        try:
            if str(v.get('deporte') or '').lower() != 'futbol':
                continue
            h, a = str(v.get('home') or ''), str(v.get('away') or '')
            if not (h and a):
                continue
            clave = (cm.normalizar(h), cm.normalizar(a))
            if clave in vistos:
                continue
            vistos.add(clave)
            # La regla se midió sobre ligas ABSOLUTAS (el ledger no tiene ni
            # un sub-19 ni un femenino). Visto en la primera prueba en vivo:
            # «Peru U19 vs Argentina U19» se colaba como probable. Fuera lo
            # que la medición no cubre.
            try:
                if cm.categoria_partido(h, a, str(v.get('liga') or '')):
                    continue
            except Exception:
                pass
            res = cm.cuotas_partido('futbol', h, a)
            pin = (res or {}).get('pinnacle') or {}
            if not all(pin.get(k) for k in ('home', 'draw', 'away')):
                continue
            just = cm.devig({k: pin[k] for k in ('home', 'draw', 'away')},
                            metodo='potencia') or {}
            pj = _num(just.get('away'))
            if pj is None or pj < PROB_MINIMA:
                continue
            precio = cm.precio_accionable(res, 'away') or {}
            cuota = _num(precio.get('cuota'))
            if (not cuota or cuota < CUOTA_MINIMA or cuota > CUOTA_MAXIMA
                    or precio.get('casa') == 'Pinnacle'):
                continue
            pm = modelo.get('%s|%s' % clave)
            if pm is not None and pm < PROB_MINIMA:
                # el modelo lo ve y NO está de acuerdo: la regla medida pide
                # a los dos, y la de sólo mercado es para cuando el modelo no
                # opina, no para cuando opina en contra.
                continue
            tipo = 'ambos' if pm is not None else 'mercado'
            med = MEDIDO[tipo]
            fuera.append({
                'deporte': 'Fútbol',
                'liga': v.get('liga') or '',
                'clave_liga': str(v.get('liga') or '').lower(),
                'partido': '%s vs %s' % (h, a),
                'inicio': v.get('inicio'),
                'fecha': bc._fecha_de(v.get('inicio')),
                'mercado': 'Ganador',
                'apuesta': 'Gana %s' % a,
                'lado': 'away',
                'prob': round(pj, 3),
                'prob_modelo': round(pm, 3) if pm is not None else None,
                'cuota': cuota,
                'cuota_justa': round(1.0 / pj, 3),
                'ev': round(cuota * pj - 1.0, 4),
                'casa': precio.get('casa'),
                'probable': tipo,
                'acierta_medido': med['acierta'],
                'etiqueta_probable': med['etiqueta'],
                'nota_canal': med['nota'],
                'validado': False,
                'origen': 'probable (visitante favorito)',
            })
        except Exception as e:
            logger.debug('[probables] %s: %s', v.get('home'), e)
    # los dos de acuerdo primero; dentro, la más probable
    fuera.sort(key=lambda x: (x['probable'] != 'ambos', -x['prob']))
    return fuera
