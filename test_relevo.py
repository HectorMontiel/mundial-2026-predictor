#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test del relevo de las dos horas (v302).

El cron de GitHub no cumple: con 48 pasadas declaradas creó SEIS el
2026-09-22, con huecos de hasta 5h10. La cadena `cuotas_mx -> relevo ->
cuotas_mx` no depende del cron. Lo que se vigila, leyendo los workflows:

  · LA CADENA EXISTE Y NO SE PUEDE ROMPER por un fallo del barrido: el relevo
    se pasa con `if: always()`.
  · EL RELEVO DUERME HASTA UNA HORA ABSOLUTA (`generado` + ciclo) y con
    `cancel-in-progress`: así relevar dos veces no adelanta ni atrasa nada.
  · EL CICLO QUEDA POR DEBAJO DE LAS DOS HORAS con el barrido dentro, y hay
    un mínimo de espera para que un barrido roto no dispare en bucle.
  · EL PERMISO para disparar workflows está declarado.
  · LA PASADA LARGA SE DECIDE POR EDAD: con el relevo la hora deriva y
    «00 o 12 UTC» dejaría días enteros sin la semana.
  · EL CRON SIGUE DE RED.
  · EL PRECÁLCULO SE CUELGA DETRÁS de las cuotas nuevas.

Ejecutar:  python test_relevo.py
"""
import re

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def main():
    import yaml
    c = open('.github/workflows/cuotas_mx.yml', encoding='utf-8').read()
    r = open('.github/workflows/relevo.yml', encoding='utf-8').read()
    yc, yr = yaml.safe_load(c), yaml.safe_load(r)

    pasos = yc['jobs']['cuotas']['steps']
    rel = [s for s in pasos if 'relevo.yml' in str(s.get('run', ''))]
    check(len(rel) == 1, 'el barrido pasa el relevo al acabar')
    check(rel and rel[0].get('if') == 'always()',
          'y lo pasa SIEMPRE, aunque el barrido o el push fallen')
    check(pasos and rel and pasos[-1] is rel[0],
          'es el último paso: nada detrás puede impedirlo')
    check((yc.get('permissions') or {}).get('actions') == 'write',
          'cuotas_mx tiene permiso para disparar workflows')
    check((yr.get('permissions') or {}).get('actions') == 'write',
          'y el relevo también')
    pre = [s for s in pasos if 'precalculo_dia.yml' in str(s.get('run', ''))]
    check(len(pre) == 1 and 'saltar' in str(pre[0].get('if', '')),
          'el precálculo se dispara detrás de un barrido de verdad')

    on = yr.get(True) or yr.get('on') or {}
    check('workflow_dispatch' in on, 'el relevo se dispara a mano / por API')
    check('schedule' in on, 'y tiene su cron de red por si la cadena cae')
    conc = yr.get('concurrency') or {}
    check(conc.get('cancel-in-progress') is True,
          'un relevo nuevo cancela al que dormía: sólo hay uno vivo')
    m = re.search(r'CICLO_MIN=(\d+)', r)
    ciclo = int(m.group(1)) if m else 999
    check(80 <= ciclo <= 100,
          'el ciclo deja el barrido (~10 min) dentro de las dos horas (%d)'
          % ciclo)
    m = re.search(r'MINIMO_MIN=(\d+)', r)
    check(m is not None and int(m.group(1)) >= 15,
          'hay una espera mínima contra el bucle (%s)'
          % (m.group(1) if m else 'no'))
    check("get('generado')" in r and 'SEG + CICLO_MIN' in r,
          'la espera es hasta una hora ABSOLUTA sacada del tablero')
    check('forzar=false' in r,
          'y dispara el barrido pasando por la guarda de frescura')
    job = yr['jobs']['relevo']
    check(int(job.get('timeout-minutes', 0)) <= 355,
          'cabe en el techo de seis horas de un job')
    m = re.search(r'MAXIMO_MIN=(\d+)', r)
    check(m is not None and int(m.group(1)) + 5 < int(job.get('timeout-minutes', 0)),
          'y la espera máxima cabe dentro del timeout')

    # la guarda obedece a `forzar`
    check('inputs.forzar' in c, 'la guarda de frescura respeta `forzar`')
    fm = re.search(r'FRESCURA_MINUTOS=(\d+)', c)
    check(fm is not None and int(fm.group(1)) < ciclo,
          'y su umbral queda por debajo del ciclo, o el relevo se saltaría '
          'a sí mismo (%s < %d)' % (fm.group(1) if fm else '?', ciclo))
    # la pasada larga por edad
    check("get('ultimo_largo')" in c and '_EDAD_H' in c,
          'la pasada larga se decide por la edad de la última')
    check('_H" = "00"' not in c, 'y ya no por la hora UTC')
    src = open('cuotas_mx.py', encoding='utf-8').read()
    check("doc['ultimo_largo']" in src,
          'cuotas_mx.py escribe cuándo fue la última larga')
    check("_doc_previo.get('ultimo_largo')" in src,
          'y la conserva en las pasadas cortas')
    # el cron sigue de red
    check("cron:" in c, 'el cron de cuotas sigue puesto de red')


if __name__ == '__main__':
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
