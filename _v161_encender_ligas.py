# -*- coding: utf-8 -*-
"""
v161 - encender las competiciones que estaban apagadas por no batir a su ELO.

QUE SE CAMBIA Y POR QUE, escrito aqui porque el cambio es un `disponible` por
liga y la razon no cabe al lado.

Estas competiciones se apagaron entre la v39 y la v106 con una nota del tipo
«no bate ELO (0,4422 vs 0,4496)». La regla de entonces era: si el modelo 1X2 de
una liga no supera a su propia linea base de ELO, la liga no sale.

Esa regla ya no decide nada, y esta medido:
  - el modelo bate al mercado en 1 de 34 ligas, o sea que su acierto NO es de
    donde sale el valor (v90);
  - apostar la probabilidad del modelo PIERDE entre -4,66 % y -6,52 % sobre
    37.158 apuestas, y su EV correlaciona -0,054 con el CLV;
  - lo que gana es comprar al mejor precio: +11,49 % en juicio, p5 +1,73 %.

O sea que filtrar competiciones por el acierto de su 1X2 quitaba partidos sin
proteger de nada: el semaforo de la Seccion 1 va por VENTAJA DE PRECIO, y esa
no depende de lo bueno que sea el modelo de la liga.

Lo que se gana: 28 partidos mas en un sabado normal (medido el 2026-08-22), y
dos de ellas -eng_championship y bel_pro_league- son de formato 'main' de
football-data, o sea que traen CORNERS Y TARJETAS OBSERVADAS y arbitro en el
historico. La Championship sola son 11 partidos.

Lo que NO se toca: la nota de cada liga. Se conserva y se le añade que la liga
esta encendida a pesar de eso, para que nadie la lea dentro de un año y crea
que alguien no vio la medicion.
"""
import io
import re

# Las que tienen historico Y team_stats Y codigo ESPN. Las tres que faltan se
# quedan fuera a proposito:
#   esp_copa_rey, eng_carabao -> sin team_stats_*.json
#   ksa_pro                   -> sin historico y sin team_stats
ENCENDER = [
    'aut_bundesliga', 'eng_championship', 'bel_pro_league', 'ned_eerste',
    'slv_primera', 'par_division', 'crc_fpd', 'ven_primera', 'aus_aleague',
    'eng_fa_cup', 'ind_isl', 'bra_copa',
]
FICHEROS = ['config.py', 'config_ligas_espn.py']
COLETILLA = (' v161: ENCENDIDA de todas formas — el acierto del 1X2 dejo de '
             'decidir que ligas salen (el modelo bate al mercado en 1 de 34 y '
             'el valor esta en el precio), asi que esto describe su modelo, '
             'no su derecho a aparecer.')


def bloque_de(src, clave):
    m = re.search(r"(['\"]%s['\"]\s*:\s*\{)" % re.escape(clave), src)
    if not m:
        return None, None
    ini = m.end()
    prof, fin = 1, ini
    while fin < len(src) and prof > 0:
        if src[fin] == '{':
            prof += 1
        elif src[fin] == '}':
            prof -= 1
        fin += 1
    return ini, fin - 1


hechas = []
for ruta in FICHEROS:
    src = io.open(ruta, encoding='utf-8').read()
    tocado = False
    for clave in ENCENDER:
        if clave in hechas:
            continue
        ini, fin = bloque_de(src, clave)
        if ini is None:
            continue
        bloque = src[ini:fin]
        if "'disponible': False" not in bloque:
            print('  %-18s ya estaba encendida en %s' % (clave, ruta))
            hechas.append(clave)
            continue
        nuevo = bloque.replace("'disponible': False", "'disponible': True", 1)
        # la nota se conserva y se amplia; si no tenia, se le pone una
        mnota = re.search(r"'nota':\s*'((?:[^'\\]|\\.)*)'", nuevo)
        if mnota:
            nuevo = (nuevo[:mnota.end(1)] + COLETILLA + nuevo[mnota.end(1):])
        else:
            nuevo = nuevo.rstrip().rstrip(',') + ",\n        'nota': '%s',\n    " % (
                COLETILLA.strip())
        src = src[:ini] + nuevo + src[fin:]
        tocado = True
        hechas.append(clave)
        print('  encendida: %-18s (%s)' % (clave, ruta))
    if tocado:
        io.open(ruta, 'w', encoding='utf-8').write(src)

faltan = [c for c in ENCENDER if c not in hechas]
print()
print('encendidas: %d · no encontradas: %s' % (len(hechas), faltan))

import config
import fixtures_espn
disp = [c for c, v in config.LEAGUES.items() if v.get('disponible')]
print('competiciones disponibles: %d' % len(disp))
sin_codigo = [c for c in disp if c not in fixtures_espn.ESPN_CODIGOS]
print('disponibles SIN codigo ESPN: %s' % sin_codigo)
sigue_apagada = [c for c, v in config.LEAGUES.items() if not v.get('disponible')]
print('siguen apagadas (%d): %s' % (len(sigue_apagada), sigue_apagada))
