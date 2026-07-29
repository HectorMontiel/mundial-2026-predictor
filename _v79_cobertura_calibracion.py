#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — ¿A cuántos picks de fútbol les llega de verdad el encogimiento?

Por qué importa
---------------
El fútbol es el ÚNICO deporte con edge validado, y ese edge se midió
concretamente en **w = 0,25**: ROI +6,72 % con bootstrap p5 +0,92 %. Con w=1,00
(sin encoger) el mismo ledger da ROI +0,47 % y p5 −2,62 %, o sea sin edge.

La corrección solo puede aplicarse si hay cuota de PINNACLE para ese partido
(`o['pin_home']` y `o['pin_away']`). Si producción emite picks de ligas que
Pinnacle no cubre, esos picks salen sin encoger — y entonces no son los que se
validaron.

Este script mide esa cobertura sobre el barrido real del día.
"""
import json
import logging
from collections import Counter

logging.basicConfig(level=logging.WARNING)


def main():
    import alpha_finder
    r = alpha_finder.apuestas_del_dia_universal(max_partidos=40)

    por_liga = Counter()
    con_cal = Counter()
    aplicado = Counter()
    total = 0
    for capa in ('capa1', 'capa2', 'candidatos', 'confianza'):
        for p in (r.get(capa) or []):
            if p.get('deporte', 'Fútbol') != 'Fútbol':
                continue
            total += 1
            liga = p.get('liga', '?')
            por_liga[liga] += 1
            cal = p.get('calibracion')
            if cal is not None:
                con_cal[liga] += 1
                if cal.get('aplicado'):
                    aplicado[liga] += 1

    print(f'\n{total} picks de fútbol en el barrido de hoy\n')
    print(f"{'liga':28s} {'picks':>6} {'con info':>9} {'ENCOGIDOS':>10}")
    print('-' * 58)
    for liga, n in por_liga.most_common():
        print(f'{liga:28s} {n:6d} {con_cal[liga]:9d} {aplicado[liga]:10d}')
    print('-' * 58)
    ta, tc = sum(aplicado.values()), sum(con_cal.values())
    print(f"{'TOTAL':28s} {total:6d} {tc:9d} {ta:10d}")
    if total:
        print(f'\nCobertura del encogimiento: {ta}/{total} = {ta/total:.1%}')
    print('\nRecordatorio: el edge del fútbol (+6,72 % ROI, p5 +0,92 %) se midió '
          'con w=0,25.\nSin encoger, el mismo ledger da +0,47 % con p5 −2,62 % '
          '— es decir, sin edge.')
    json.dump({'total': total, 'con_info': tc, 'aplicado': ta,
               'por_liga': dict(por_liga), 'encogidos': dict(aplicado)},
              open('_v79_cobertura_calibracion.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
