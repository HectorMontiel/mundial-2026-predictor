# -*- coding: utf-8 -*-
"""
v274 — Cuál meter, cuál no, y en qué orden. Dicho para quien apuesta.

LO QUE PIDIÓ EL USUARIO
«Quiero que me diga cuál de todas son las que debo meter, y que las ordene de
menor a mayor riesgo.»

POR QUÉ EL ORDEN NO ES EL QUE PARECE
Ordenar por «probabilidad de acertar» pondría delante justo las que menos
rinden. Medido sobre las 1.820 apuestas históricas de este canal:

    prob 0,30-0,35   acierta 39,8 %   ROI +29,63 %   p5  +9,80 %
    prob 0,60 o más  acierta 68,6 %   ROI  +2,47 %   p5  -3,42 %

    cuota 2,80-4,00  acierta 38,8 %   ROI +21,82 %   p5  +8,07 %
    cuota 1,15-1,80  acierta 65,9 %   ROI  +0,31 %   p5  -5,57 %

Las cuotas bajas aciertan mucho y no ganan nada. Las casas blandas se
equivocan sobre todo con los NO favoritos, y ahí es donde está el dinero. Así
que se ordena por CALIDAD MEDIDA, no por sensación de seguridad.

Y EL EV GRANDE ES PELIGRO, NO GANGA
    EV 2-5 %     n=621   ROI +11,34 %   p5  +3,87 %
    EV 20-50 %   n= 51   ROI  +5,92 %   p5 -25,38 %

Cuando una casa paga un 20 % por encima del precio justo, casi nunca es una
oportunidad: es un precio viejo, un error de dedo o una línea que van a
corregir. Parece la mejor de la lista y es la peor.

EL SEMÁFORO, VALIDADO EN LOS DOS TRAMOS
Medido por separado en el 70 % antiguo (elección) y el 30 % reciente (juicio),
que es como se cazan los espejismos en este proyecto:

    regla                          ELECCION p5   JUICIO p5   al dia
    VERDE  EV 2-10 % y cuota 2,2-4   +2,61 %      +7,10 %     1,15
    AMBAR  el resto con EV < 20 %    +1,57 %      +2,25 %     3,89
    ROJO   EV >= 20 %                no medible (n=52 en 4,5 años)

LO QUE ESTO NO HACE, Y HAY QUE DECIRLO
No sube el porcentaje de aciertos. Las verdes aciertan MENOS que la media,
porque son cuotas altas. Este canal gana por lo que pagan, no por cuántas
entran. Quien busque acertar mucho tiene que irse a cuotas bajas, y eso está
medido en negativo: p5 -3,42 %.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Los cortes salen de la tabla del encabezado. No se tocan sin volver a medir
# en los dos tramos.
EV_MIN_VERDE = 0.02
EV_MAX_VERDE = 0.10
CUOTA_MIN_VERDE = 2.20
CUOTA_MAX_VERDE = 4.00
EV_ROJO = 0.20

# v276 — EL MARGEN DE PINNACLE, LA PUERTA QUE FALTABA.
#
# Lo encontro el usuario preguntando por un pick que no le cuadraba. Su
# argumento —«ese equipo nunca le ha ganado a ese otro»— no era el correcto:
# el historial YA esta dentro del precio de Pinnacle, por eso lo cotiza a 2,73
# y no a 1,80. Pero su sospecha si lo era, por otro motivo:
#
#     ROI de la Capa 1 segun el margen de Pinnacle en ese partido
#        margen  0-3 %   n=362    ROI +11,29 %   p5 +1,22 %
#        margen  3-5 %   n=1263   ROI  +6,89 %   p5 +1,68 %
#        margen  5-7 %   n=188    ROI  +5,09 %   p5 -6,45 %
#        margen  7-9 %   n=6      <- sin muestra
#        margen 9-12 %   n=1      <- sin muestra
#
# TODA la validacion de este canal se hizo con partidos donde Pinnacle cobra
# menos del 7 %. Por encima hay SIETE apuestas en cuatro años y medio.
#
# Y esto no es teorico: el barrido completo del tablero (v266) abrio la puerta
# a ligas georgianas, bolivianas y sub-23 donde Pinnacle pone el 9 o el 13 %.
# El 2026-09-21, SIETE de quince picks del dia caian ahi, y dos de ellos
# salian marcados en VERDE con el texto «es el tipo de apuesta que mejor ha
# rendido». Era falso: ese tipo de apuesta no se ha medido nunca.
#
# Un margen del 13 % es Pinnacle diciendo «esta liga no me la creo». Su precio
# deja de ser una referencia fiable, y quitarle el margen a partes
# proporcionales distorsiona mas cuanto mas gordo es.
MARGEN_PIN_MAXIMO = 0.07

VERDE, AMBAR, ROJO = 'verde', 'ambar', 'rojo'


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # NaN fuera


def clasificar(pick: Dict) -> Dict:
    """Qué hacer con esta apuesta, y por qué. NUNCA lanza.

    Devuelve `nivel`, un `titulo` corto para la pantalla, el `porque` en
    lenguaje de andar por casa, y un `orden` para colocarla en la lista.
    """
    try:
        ev = _num(pick.get('ev'))
        cuota = _num(pick.get('cuota'))
        justa = _num(pick.get('cuota_justa'))
        validado = bool(pick.get('validado', True))

        if ev is None or cuota is None:
            return {'nivel': AMBAR, 'titulo': 'Puedes meterla',
                    'porque': 'Le falta algún dato para poder juzgarla mejor.',
                    'etiqueta': 'sin datos suficientes', 'orden': 5}

        if ev >= EV_ROJO:
            return {
                'nivel': ROJO, 'titulo': 'No la metas',
                'porque': (
                    'Paga demasiado bien: un %.0f %% por encima de lo que vale. '
                    'Cuando una casa se pasa tanto casi nunca es una ganga, es '
                    'un precio viejo o un error que van a corregir. De éstas '
                    'ha habido 52 en cuatro años y medio, y no se puede '
                    'demostrar que ganen.' % (100 * ev)),
                'etiqueta': 'paga demasiado: mala señal', 'orden': 9}

        if (not validado):
            return {
                'nivel': AMBAR, 'titulo': 'Puedes meterla',
                'porque': (
                    'La ventaja está ahí, pero este deporte todavía no tiene '
                    'suficientes apuestas resueltas como para prometerte nada. '
                    'Se está midiendo.'),
                'etiqueta': 'deporte aún sin medir', 'orden': 6}

        # la puerta del margen va ANTES de decidir el verde: si Pinnacle no
        # se cree la liga, su precio no sirve de referencia y no hay nada
        # medido que prometer
        margen = _num(pick.get('margen_pin'))
        if margen is not None and margen > MARGEN_PIN_MAXIMO:
            return {
                'nivel': AMBAR, 'titulo': 'Puedes meterla',
                'porque': (
                    'Cuidado con ésta: Pinnacle le pone un %.0f %% de comisión '
                    'a este partido, el triple de lo normal. Cuando cobra '
                    'tanto es que la liga no le interesa y su precio deja de '
                    'ser buena referencia. De apuestas así sólo tenemos siete '
                    'en cuatro años y medio, o sea que no hay con qué '
                    'prometerte nada.' % (100 * margen)),
                'etiqueta': 'liga que Pinnacle no se cree', 'orden': 8}

        if (EV_MIN_VERDE <= ev < EV_MAX_VERDE
                and CUOTA_MIN_VERDE <= cuota < CUOTA_MAX_VERDE):
            extra = ''
            if justa:
                extra = ' Pagan %.2f cuando lo justo sería %.2f.' % (cuota,
                                                                     justa)
            return {
                'nivel': VERDE, 'titulo': 'Métela',
                'porque': (
                    'Es el tipo de apuesta que mejor ha rendido de este canal.'
                    + extra +
                    ' Ojo: de cada diez así entran unas cuatro. Se gana por lo '
                    'que pagan, no por cuántas entran.'),
                'etiqueta': 'la banda que mejor rinde',
                # dentro del verde, primero la de EV mas cercano al 5 %, que es
                # la banda de mejor p5 medido
                'orden': 1 + abs(ev - 0.05)}

        if cuota < CUOTA_MIN_VERDE:
            return {
                'nivel': AMBAR, 'titulo': 'Puedes meterla',
                'porque': (
                    'Es de las que más entran, pero también de las que menos '
                    'dejan: a cuotas bajas la ventaja casi desaparece. '
                    'Medido, este grupo apenas empata.'),
                'etiqueta': 'cuota baja: deja poco', 'orden': 7}

        return {
            'nivel': AMBAR, 'titulo': 'Puedes meterla',
            'porque': (
                'Hay ventaja medida, aunque menos clara que en las verdes.'),
            'etiqueta': 'ventaja menos clara', 'orden': 4}
    except Exception as e:
        logger.debug('[semaforo] %s', e)
        return {'nivel': AMBAR, 'titulo': 'Puedes meterla',
                'porque': 'No se ha podido juzgar con detalle.',
                'etiqueta': 'sin juzgar', 'orden': 5}


def _apellido(trozo: str) -> str:
    """El apellido de un participante, con las iniciales fuera.

    «Storm Hunter» y «Hunter S.» son la misma persona. Quedarse con el ultimo
    token de tres letras o mas las une, y no une a dos jugadores distintos
    salvo que compartan apellido —caso que la cuota desempata, ver `_clave`—.
    """
    import unicodedata
    t = unicodedata.normalize('NFKD', str(trozo or '').lower())
    t = t.encode('ascii', 'ignore').decode('ascii')
    trozos = [x for x in t.replace('.', ' ').split() if len(x) >= 3]
    return trozos[-1] if trozos else t.strip()


def _clave(pick) -> tuple:
    """Que dos picks sean EL MISMO, aunque esten escritos distinto."""
    partido = str((pick or {}).get('partido') or '')
    lados = [_apellido(x) for x in partido.replace(' vs ', '|').split('|')]
    cuota = _num((pick or {}).get('cuota'))
    return (frozenset(lados), _apellido((pick or {}).get('apuesta')),
            round(cuota, 2) if cuota is not None else None)


def quitar_repetidos(picks):
    """El mismo partido dos veces es doblar la apuesta sin saberlo.

    v278 — PASO DE VERDAD, Y EL USUARIO LO VIO ANTES QUE YO.

    En la lista del 2026-09-21 aparecian:

        6. Gana Joanna Garland · Storm Hunter vs Joanna Garland · @1.93
        7. Gana Garland J.     · Hunter S. vs Garland J.        · @1.93

    El mismo partido, la misma apuesta y la misma cuota, escritos de dos
    formas porque vienen de dos fuentes (el barrido del tablero y el pase de
    fixtures). El deduplicado de `alpha_finder` compara la cadena entera, asi
    que no los veia.

    Quien meta las dos cree que diversifica y en realidad esta doblando el
    riesgo en un solo partido — que es lo contrario de lo que este canal
    necesita, porque su ventaja vive en repartir muchas apuestas pequeñas.

    Se exige que coincidan participantes, seleccion Y cuota: dos jugadores
    distintos con el mismo apellido no se fusionan salvo que ademas coticen
    identico, y en ese caso dan lo mismo.
    """
    if not picks:
        return []
    vistos, fuera, repetidos = set(), [], 0
    for p in picks:
        if not isinstance(p, dict):
            continue
        try:
            k = _clave(p)
        except Exception:
            fuera.append(p)
            continue
        if k in vistos:
            repetidos += 1
            continue
        vistos.add(k)
        fuera.append(p)
    if repetidos:
        logger.info('[semaforo] %d picks repetidos fuera', repetidos)
    return fuera


def ordenar(picks: List[Dict]) -> List[Dict]:
    """Los mismos picks, con el semáforo puesto y en el orden de meterlas.

    Verde primero, ámbar después, rojo al final. Dentro de cada grupo manda la
    calidad medida, NO la probabilidad de acertar: ver el encabezado.
    """
    if not picks:
        return []
    picks = quitar_repetidos(picks)
    fuera = []
    for p in picks:
        # lo que no sea un diccionario se descarta: esto va dentro del render
        # y una fila rara no puede llevarse por delante la pantalla entera
        if not isinstance(p, dict):
            continue
        try:
            q = dict(p)
            q['semaforo'] = clasificar(p)
            fuera.append(q)
        except Exception:
            fuera.append(p)
    orden = {VERDE: 0, AMBAR: 1, ROJO: 2}

    def _clave(x):
        s = x.get('semaforo') or {}
        # `_num` porque un `ev` de texto hacia reventar el `sort` entero: lo
        # cazo `test_semaforo` con una lista con basura dentro
        ev = _num(x.get('ev'))
        ordn = _num(s.get('orden'))
        return (orden.get(s.get('nivel'), 1),
                ordn if ordn is not None else 5.0,
                -(ev if ev is not None else 0.0))

    try:
        fuera.sort(key=_clave)
    except Exception as e:
        logger.debug('[semaforo] ordenando: %s', e)
    return fuera


def resumen(picks: List[Dict]) -> str:
    """La frase de arriba: cuántas meter y cuántas dejar. En cristiano."""
    try:
        if not picks:
            return ''
        n = {VERDE: 0, AMBAR: 0, ROJO: 0}
        for p in picks:
            s = p.get('semaforo') or clasificar(p)
            n[s.get('nivel', AMBAR)] = n.get(s.get('nivel', AMBAR), 0) + 1
        total = sum(n.values())
        if n[VERDE] == 0:
            base = ('Hoy no hay ninguna de las buenas de verdad. '
                    'Salen 1,15 al día de media, así que es normal.')
        elif n[VERDE] == 1:
            base = 'De las %d de hoy, **mete 1**: la primera de la lista.' % total
        else:
            base = ('De las %d de hoy, **mete las %d primeras**.'
                    % (total, n[VERDE]))
        resto = []
        if n[AMBAR]:
            resto.append('%d puedes meterlas si quieres más volumen' % n[AMBAR])
        if n[ROJO]:
            resto.append('%d mejor déjalas' % n[ROJO])
        if resto:
            base += ' ' + ' y '.join(resto) + '.'
        return base
    except Exception as e:
        logger.debug('[semaforo] resumen: %s', e)
        return ''


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    ejemplos = [
        {'partido': 'A vs B', 'ev': 0.045, 'cuota': 2.85, 'cuota_justa': 2.61,
         'validado': True},
        {'partido': 'C vs D', 'ev': 0.39, 'cuota': 2.90, 'validado': False},
        {'partido': 'E vs F', 'ev': 0.012, 'cuota': 1.60, 'validado': True},
        {'partido': 'G vs H', 'ev': 0.033, 'cuota': 1.93, 'validado': False},
    ]
    picks = ordenar(ejemplos)
    print(resumen(picks))
    print()
    for i, p in enumerate(picks, 1):
        s = p['semaforo']
        icono = {'verde': '🟢', 'ambar': '🟡', 'rojo': '🔴'}[s['nivel']]
        print('%d. %s %s — %s (cuota %.2f)'
              % (i, icono, s['titulo'], p['partido'], p['cuota']))
        print('   %s' % s['porque'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
