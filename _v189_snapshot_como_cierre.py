#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v189 - ¿SIRVE LA ULTIMA FOTO COMO LINEA DE CIERRE?

football-data.co.uk lleva caido (503 en todo el sitio, comprobado hoy), y de
ahi salen las cuotas de cierre. Sin cierre, las filas nuevas del ledger entran
sin cuota y no se pueden liquidar.

Hay 683 partidos con foto y sin cierre. La tentacion es marcar la ultima foto
como cierre. Antes de eso hay que medir cuanto se parece una foto a <N horas
del pitido a la linea de cierre de verdad, y eso se puede medir en los
partidos donde estan LAS DOS.

Si el error es grande, promover fotos meteria ruido en la metrica rey (el CLV)
y en todo lo que se liquida. Si es pequeño, es mejor que no tener nada.
"""
import io
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')


def main():
    import statistics
    con = sqlite3.connect('odds_historico.db')

    # Para cada partido con cierre, la foto mas cercana al pitido.
    q = """
    SELECT s.match_id, s.dias_al_partido,
           s.odds_home, s.odds_draw, s.odds_away,
           c.odds_home, c.odds_draw, c.odds_away
    FROM historical_odds s
    JOIN (SELECT match_id, MIN(odds_home) AS odds_home,
                 MIN(odds_draw) AS odds_draw, MIN(odds_away) AS odds_away
          FROM historical_odds WHERE fase='cierre' AND odds_home IS NOT NULL
          GROUP BY match_id) c ON c.match_id = s.match_id
    WHERE s.fase='snapshot' AND s.odds_home IS NOT NULL
    """
    mejor = {}
    for mid, dias, sh, sd, sa, ch, cd, ca in con.execute(q):
        if dias is None:
            continue
        if mid not in mejor or dias < mejor[mid][0]:
            mejor[mid] = (dias, sh, sd, sa, ch, cd, ca)
    con.close()

    print('partidos con foto Y cierre de verdad: %d' % len(mejor))
    if not mejor:
        print('sin solape: no se puede medir. NO se promueve nada.')
        return 1
    print()

    for tope in (0.5, 1.0, 2.0, 7.0):
        filas = [v for v in mejor.values() if v[0] <= tope]
        if len(filas) < 20:
            print('  <= %-4s dias: solo %d partidos, muestra corta' % (tope, len(filas)))
            continue
        errs, sesgos = [], []
        for dias, sh, sd, sa, ch, cd, ca in filas:
            for s, c in ((sh, ch), (sd, cd), (sa, ca)):
                if not s or not c or c <= 1.0:
                    continue
                # en probabilidad implicita, que es como se usa
                ps, pc = 1.0 / s, 1.0 / c
                errs.append(abs(ps - pc))
                sesgos.append(ps - pc)
        if not errs:
            continue
        errs.sort()
        print('  <= %-4s dias  n=%4d partidos (%5d cuotas)' % (tope, len(filas),
                                                               len(errs)))
        print('       error medio en prob. implicita: %.4f' % statistics.mean(errs))
        print('       mediana                        : %.4f' % statistics.median(errs))
        print('       p90                            : %.4f'
              % errs[int(0.90 * len(errs))])
        print('       sesgo medio (foto - cierre)    : %+.4f'
              % statistics.mean(sesgos))
        print()

    print('REFERENCIA: el margen tipico de una casa en 1X2 ronda 0,02-0,04 de')
    print('probabilidad por resultado. Un error por encima de eso significa que')
    print('la foto NO es un sustituto del cierre.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
