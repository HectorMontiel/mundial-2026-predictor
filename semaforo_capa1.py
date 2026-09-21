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
                    'orden': 5}

        if ev >= EV_ROJO:
            return {
                'nivel': ROJO, 'titulo': 'No la metas',
                'porque': (
                    'Paga demasiado bien: un %.0f %% por encima de lo que vale. '
                    'Cuando una casa se pasa tanto casi nunca es una ganga, es '
                    'un precio viejo o un error que van a corregir. De éstas '
                    'ha habido 52 en cuatro años y medio, y no se puede '
                    'demostrar que ganen.' % (100 * ev)),
                'orden': 9}

        if (not validado):
            return {
                'nivel': AMBAR, 'titulo': 'Puedes meterla',
                'porque': (
                    'La ventaja está ahí, pero este deporte todavía no tiene '
                    'suficientes apuestas resueltas como para prometerte nada. '
                    'Se está midiendo.'),
                'orden': 6}

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
                'orden': 7}

        return {
            'nivel': AMBAR, 'titulo': 'Puedes meterla',
            'porque': (
                'Hay ventaja medida, aunque menos clara que en las verdes.'),
            'orden': 4}
    except Exception as e:
        logger.debug('[semaforo] %s', e)
        return {'nivel': AMBAR, 'titulo': 'Puedes meterla',
                'porque': 'No se ha podido juzgar con detalle.', 'orden': 5}


def ordenar(picks: List[Dict]) -> List[Dict]:
    """Los mismos picks, con el semáforo puesto y en el orden de meterlas.

    Verde primero, ámbar después, rojo al final. Dentro de cada grupo manda la
    calidad medida, NO la probabilidad de acertar: ver el encabezado.
    """
    if not picks:
        return []
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
