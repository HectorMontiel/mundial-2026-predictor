#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — La tabla de pesos cubre las ligas que NO juegan.

Cadena de hechos medida hoy:

  1. Pinnacle cubre el 73 % de los partidos de fútbol de hoy.
  2. 21 de 129 evaluaciones llegan a la rama de calibración con cuota sharp.
  3. Aun así, 0 de 41 picks salen encogidos.

El motivo no es la cuota: es que `peso_modelo(liga)` devuelve 1,00 (sin
corrección) para las ligas que están jugando. `calibracion_mercado.json` se
construye desde el ledger, y el ledger de fútbol viene de fuentes que cubren
sobre todo **Europa** — que en julio está de vacaciones. Las que sí juegan
ahora (Argentina, Liga MX, Sudamericana, Paraguay, El Salvador...) no tienen
histórico de cuotas, así que nunca se les midió un peso.

Consecuencia que hay que decir con todas las letras: el edge del fútbol se
validó **en w = 0,25** (+6,72 % de ROI, p5 +0,92 %). Con w = 1,00 el mismo
ledger da +0,47 % y p5 −2,62 %, o sea sin edge. Los picks que salen hoy se
emiten con w = 1,00.
"""
import json
from collections import Counter


def main():
    import calibracion_mercado as cal
    import config
    import fixtures_espn

    tabla = set((json.load(open('calibracion_mercado.json', encoding='utf-8'))
                 .get('ligas') or {}).keys())
    print(f'{len(tabla)} claves con peso en calibracion_mercado.json\n')

    activas = [c for c in config.LEAGUES if c in fixtures_espn.ESPN_CODIGOS]
    fx = fixtures_espn.fixtures_multi(activas, dias=3)

    con_partidos = {c: len(ps) for c, ps in fx.items() if ps}
    print(f"{'liga':26s} {'partidos':>9} {'w':>6}   estado")
    print('-' * 60)
    n_con, n_sin, p_con, p_sin = 0, 0, 0, 0
    for c, n in sorted(con_partidos.items(), key=lambda kv: -kv[1]):
        w = cal.peso_modelo(c)
        tiene = c in tabla
        if tiene:
            n_con += 1; p_con += n
        else:
            n_sin += 1; p_sin += n
        print(f'{c:26s} {n:9d} {w:6.2f}   '
              f"{'medida' if tiene else 'SIN MEDIR -> sin encoger'}")
    print('-' * 60)
    print(f'\nLigas que juegan hoy: {n_con} con peso medido, '
          f'{n_sin} SIN medir')
    print(f'Partidos            : {p_con} con peso medido, {p_sin} SIN medir')
    tot = p_con + p_sin
    if tot:
        print(f'\nCobertura real de la calibración: {p_con}/{tot} = '
              f'{p_con/tot:.1%} de los partidos de hoy')

    dormidas = sorted(tabla - set(con_partidos) - {'atp', 'wta', 'mlb'})
    print(f'\n{len(dormidas)} ligas CON peso medido pero SIN partidos hoy '
          f'(parón):\n   {dormidas}')

    json.dump({'con_peso': n_con, 'sin_peso': n_sin,
               'partidos_con_peso': p_con, 'partidos_sin_peso': p_sin,
               'ligas_sin_peso': sorted(set(con_partidos) - tabla)},
              open('_v79_cobertura_w.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
