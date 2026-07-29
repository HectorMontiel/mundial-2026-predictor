#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — Con el peso ya resuelto para TODAS las ligas, ¿por qué sigue sin
calibrarse ni un pick de fútbol?

Arreglada la caída al w global, `peso_modelo` devuelve 0,25 para argentina,
liga_mx, china... y aun así la cobertura del encogimiento sigue en 0/40. O sea
que la puerta que queda cerrada es otra. Se instrumenta el interior de la rama
de calibración de `_mercados_del_partido` para ver exactamente cuál.

Candidatas:
  · no llega cuota de Pinnacle en el fixture (`pin_home`/`pin_away`)
  · llega pero SIN el empate, y `corregir` exige el vector 1X2 completo
  · `devig` no devuelve las tres patas
"""
import logging
from collections import Counter

logging.basicConfig(level=logging.WARNING)

C = Counter()
EJ = []


def main():
    import alpha_finder
    import calibracion_mercado as cal
    import cuotas_multi as cm

    orig = alpha_finder._mercados_del_partido

    def espia(pred, o, home, away, clave_liga=None):
        ph, pa, pd_ = o.get('pin_home'), o.get('pin_away'), o.get('pin_draw')
        if not clave_liga:
            C['sin clave_liga'] += 1
        elif not (ph and pa):
            C['sin cuota de Pinnacle en el fixture'] += 1
        else:
            w = cal.peso_modelo(clave_liga)
            if w >= 1.0:
                C[f'w=1 para {clave_liga}'] += 1
            elif not pd_:
                C['CON Pinnacle 1 y 2, pero SIN EMPATE'] += 1
                if len(EJ) < 6:
                    EJ.append(f'{home} vs {away} ({clave_liga}): '
                              f'pin {ph}/-/{pa}')
            else:
                justa = cm.devig({'home': ph, 'draw': pd_, 'away': pa},
                                 metodo='potencia')
                if len(justa) < 3:
                    C[f'devig devuelve {len(justa)} patas'] += 1
                else:
                    C['TODO OK -> se calibra'] += 1
                    if len(EJ) < 6:
                        EJ.append(f'{home} vs {away} ({clave_liga}): '
                                  f'w={w} justa={ {k: round(v,3) for k,v in justa.items()} }')
        return orig(pred, o, home, away, clave_liga)

    alpha_finder._mercados_del_partido = espia
    alpha_finder.apuestas_del_dia(max_partidos=40)

    tot = sum(C.values())
    print(f'\n{tot} evaluaciones de mercados\n')
    for k, v in C.most_common():
        print(f'  {v:5d}  ({v/max(tot,1):5.1%})  {k}')
    if EJ:
        print('\nEjemplos:')
        for e in EJ:
            print(f'   · {e}')


if __name__ == '__main__':
    main()
