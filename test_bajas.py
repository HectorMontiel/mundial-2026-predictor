#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de las bajas de FotMob (v306).

La fuente de bajas del proyecto llevaba semanas vacía (2.357 partidos
anotados, cero señales): leía la API blindada de FotMob. Lo que se vigila:

  · SE LEEN DE LA FICHA DEL PARTIDO (`lineup.<equipo>.unavailable`), la
    página que sí responde, y NO de la API.
  · SE ACUMULAN en un histórico para poder medirlas antes de usarlas.
  · NO MUEVEN NINGUNA PROBABILIDAD todavía: se enseñan en la tarjeta.
  · EL TEXTO ES CORTO y nunca lanza.

Ejecutar:  python test_bajas.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def main():
    import bajas_fotmob as bf
    src = open('bajas_fotmob.py', encoding='utf-8').read()
    check("'unavailable'" in src and '/match/%s' in src,
          'lee las bajas de la ficha del partido')
    check('api/data' not in src, 'y no de la API blindada')
    check('HISTORICO' in src and 'bajas_historico.csv' in src,
          'las acumula en un histórico para medirlas')
    # el texto, sobre un bloque con la forma que escribe `capturar`
    bloque = {'clave_liga': 'premier', 'inicio': '2026-09-27 14:00:00',
              'home': {'equipo': 'Arsenal', 'bajas': [
                  {'jugador': 'William Saliba', 'tipo': 'injury'},
                  {'jugador': 'Ben White', 'tipo': 'injury'},
                  {'jugador': 'Jurriën Timber', 'tipo': 'injury'}]},
              'away': {'equipo': 'Leeds United', 'bajas': [
                  {'jugador': 'Joe Rodon', 'tipo': 'injury'}]}}
    orig = bf.de_partido
    bf.de_partido = lambda pick: bloque
    try:
        t = bf.texto({'partido': 'Arsenal vs Leeds United',
                      'clave_liga': 'premier'})
    finally:
        bf.de_partido = orig
        bf._CACHE.clear()
    check(t.startswith('🚑 Bajas:') and 'Arsenal 3' in t and 'Leeds United 1' in t,
          'el texto dice cuántas bajas tiene cada uno («%s»)' % t)
    check(len(t) < 120, 'y es corto (%d caracteres)' % len(t))
    try:
        check(bf.texto({'partido': None}) == '', 'con un pick roto no lanza')
    except Exception as e:
        check(False, 'lanzó: %s' % e)
    mm = open('modo_modelo.py', encoding='utf-8').read()
    check('bajas_fotmob' in mm, 'la tarjeta enseña las bajas')
    for f in ('patrones_liga.py', 'valor_apuesta.py', 'alpha_finder.py'):
        check('bajas_fotmob' not in open(f, encoding='utf-8').read(),
              '%s no las usa para calcular: todavía no están medidas' % f)
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('bajas_fotmob.py' in wf and 'bajas_historico.csv' in wf,
          'el precálculo las refresca y guarda el histórico')


if __name__ == '__main__':
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
