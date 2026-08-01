#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v88 — El fuzzy de `codigo_mlb` confunde equipos de otras ligas con equipos MLB.

Encontrado al revisar el tablón: `codigo_mlb('Kia Tigers')` devuelve **'DET'**.
Kia Tigers es de la KBO coreana; Detroit Tigers es de la MLB. Comparten la
palabra «Tigers» y el umbral de 0,6 del `SequenceMatcher` los da por el mismo.

Eso no es sólo ruido en las cuotas: `codigo_mlb` es la puerta por la que entran
los nombres de las casas al MOTOR de MLB, así que un partido de la KBO puede
predecirse con las estadísticas de Detroit.

Esto mide cuántos equipos de otras ligas de béisbol se hacen pasar por equipos
de la MLB.
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Equipos reales de otras ligas de béisbol que aparecen en los tablones.
OTRAS_LIGAS = {
    'LMB (México)': [
        'Olmecas de Tabasco', 'Bravos de Leon', 'El Aguila de Veracruz',
        'Tigres de Quintana Roo', 'Toros de Tijuana', 'Acereros de Monclova',
        'Sultanes de Monterrey', 'Dorados de Chihuahua',
        'Tecolotes de Los Dos Laredos', 'Saraperos de Saltillo',
        'Pericos de Puebla', 'Diablos Rojos del Mexico', 'Leones de Yucatan',
        'Guerreros de Oaxaca', 'Charros de Jalisco', 'Piratas de Campeche',
    ],
    'NPB (Japón)': [
        'Tohoku Rakuten Golden Eagles', 'Fukuoka Softbank Hawks',
        'Hanshin Tigers', 'Yomiuri Giants', 'Chunichi Dragons',
        'Hiroshima Toyo Carp', 'Orix Buffaloes', 'Chiba Lotte Marines',
        'Saitama Seibu Lions', 'Hokkaido Nippon-Ham Fighters',
        'Tokyo Yakult Swallows', 'Yokohama DeNA BayStars',
    ],
    'KBO (Corea)': [
        'NC Dinos', 'Kia Tigers', 'SSG Landers', 'Lotte Giants',
        'Doosan Bears', 'LG Twins', 'Samsung Lions', 'Hanwha Eagles',
        'Kiwoom Heroes', 'KT Wiz',
    ],
    'CPBL (Taiwán)': [
        'Rakuten Monkeys', 'Uni-President 7-Eleven Lions',
        'Uni-President Lions', 'Wei Chuan Dragons', 'CTBC Brothers',
        'Fubon Guardians', 'TSG Hawks',
    ],
    'Triple-A': [
        'Sacramento River Cats', 'Tacoma Rainiers', 'Durham Bulls',
        'Las Vegas Aviators', 'Round Rock Express',
    ],
}


def main():
    from engines.mlb_engine import NOMBRES_MLB, codigo_mlb

    validos = set(NOMBRES_MLB.values())
    print('=' * 78)
    print('v88 · ¿CUÁNTOS EQUIPOS DE OTRAS LIGAS SE HACEN PASAR POR MLB?')
    print('=' * 78)

    total, falsos = 0, []
    for liga, equipos in OTRAS_LIGAS.items():
        print(f'\n  {liga}')
        for e in equipos:
            total += 1
            c = codigo_mlb(e)
            if c in validos:
                falsos.append((liga, e, c))
                print(f'    ✗ {e:34s} -> {c}  '
                      f'({[k for k, v in NOMBRES_MLB.items() if v == c][0]})')
    if not falsos:
        print('    (ninguno)')

    print('\n' + '-' * 78)
    print(f'  equipos de otras ligas probados : {total}')
    print(f'  que el fuzzy da por MLB         : {len(falsos)} '
          f'({len(falsos) / total:.1%})')

    print('\n  Consecuencia: `codigo_mlb` es la puerta al MOTOR de MLB, así que')
    print('  esos partidos se predicen con las estadísticas del equipo MLB')
    print('  equivocado, y entran a la Capa 1 con etiqueta «MLB».')

    # ¿y el filtro estricto los deja fuera?
    print('\n' + '-' * 78)
    print('CON EL FILTRO ESTRICTO PROPUESTO (nombre exacto o alias declarado)')
    print('-' * 78)
    try:
        from engines.mlb_engine import es_equipo_mlb
    except ImportError:
        print('  (todavía no existe `es_equipo_mlb`; se implementa a continuación)')
        return 1

    quedan = [(l, e) for l, e, _ in falsos if es_equipo_mlb(e)]
    print(f'  falsos positivos que sobreviven: {len(quedan)}')
    for l, e in quedan:
        print(f'    ✗ {l}: {e}')
    # y los MLB de verdad deben seguir pasando
    fallan = [n for n in NOMBRES_MLB if not es_equipo_mlb(n)]
    print(f'  equipos MLB reales que se caerían: {len(fallan)} {fallan}')
    ok = not quedan and not fallan
    print(f'\nVEREDICTO: {"FILTRO CORRECTO" if ok else "revisar"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
