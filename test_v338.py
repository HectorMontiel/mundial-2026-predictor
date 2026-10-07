#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v338.

El usuario: «sí, quiero que dejes funcionando eso» (medir, solo y en cada
precálculo, si las bajas avisan antes que la cuota).

Lo que se vigila:

  1. EL REGISTRO (`senal_bajas.registrar`): apunta los partidos con bajas, con
     la cuota de ese momento; no repite filas iguales; fuera de GitHub
     Actions no escribe (la app no ensucia el repositorio).
  2. LA MEDICIÓN (`senal_bajas.medir`): deja el informe y no se declara lista
     sin las 300 señales liquidadas y p5 > 0.
  3. EL CABLEADO: `alpha_finder` registra justo después de aplicar las bajas;
     el workflow mide y publica los dos ficheros.

Ejecutar:  python test_v338.py
"""
import json
import os
import shutil
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def pick(f_l=0.9, f_v=1.0, mas=2.1, menos=1.75, partido='A vs B', fecha='2026-10-07'):
    return {'deporte': 'Fútbol', 'clave_liga': 'x', 'partido': partido, 'fecha': fecha,
            'inicio': fecha + ' 20:00:00',
            'goles_xg': {'local': 1.2, 'visitante': 1.0},
            'ajuste_bajas': {'local': {'factor': f_l}, 'visitante': {'factor': f_v}},
            'implicitas': {'goles': {'2.5': {'mas': mas, 'menos': menos}}}}


def probar_registro_y_medicion():
    import senal_bajas as sb
    cwd = os.getcwd()
    tmp = tempfile.mkdtemp(prefix='v338_')
    os.chdir(tmp)
    try:
        viejo = os.environ.pop('GITHUB_ACTIONS', None)
        check(sb.registrar([pick()]) == 0 and not os.path.exists(sb.FICHERO),
              'fuera de GitHub Actions no escribe')
        os.environ['GITHUB_ACTIONS'] = 'true'
        check(sb.registrar([pick()]) == 1, 'en Actions apunta el partido con bajas')
        check(sb.registrar([pick()]) == 0, 'no repite una fila igual')
        check(sb.registrar([pick(mas=2.0, menos=1.8)]) == 1, 'sí apunta si cambia la cuota')
        check(sb.registrar([dict(pick(), ajuste_bajas=None)]) == 0, 'sin bajas no apunta nada')
        r = sb.fila(pick(), 't')
        check(r['lam1'] < r['lam0'] and r['p25_1'] < r['p25_0'],
              'un ataque sin titulares baja la λ y el más de 2,5')
        doc = sb.medir()
        check(os.path.exists(sb.INFORME) and doc['listo_para_decidir'] is False,
              'el informe existe y sin muestra no se declara listo')
        if viejo is None:
            os.environ.pop('GITHUB_ACTIONS', None)
        else:
            os.environ['GITHUB_ACTIONS'] = viejo
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)


def probar_cableado():
    a = open('alpha_finder.py', encoding='utf-8').read()
    i, j = a.find('_bm.ajustar_lista('), a.find('_sb.registrar(')
    check(i > 0 and j > i, 'alpha_finder registra la señal justo después de las bajas')
    w = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('python senal_bajas.py --medir' in w, 'el precálculo mide la señal')
    check('senal_bajas.csv senal_bajas.json' in w, 'y publica el registro y el informe')


if __name__ == '__main__':
    print('=== 1. registro y medición ===')
    probar_registro_y_medicion()
    print('\n=== 2. cableado ===')
    probar_cableado()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
