# -*- coding: utf-8 -*-
"""
v320 — pruebas: córners de UN EQUIPO sólo con favorito de 65 %+ (medido); al
total no se le aplica (no mejora).

Uso: python test_v320.py
"""
from __future__ import annotations

import json
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medido():
    m = json.load(open('_v320_corners_favorito.json', encoding='utf-8'))
    c = m['grupos']['clubes | equipo | 65 %+']
    check(m['adopta_equipo'] and c['acierto'] > 0.78 and c['primera_mitad'] > 0.77
          and c['segunda_mitad'] > 0.77,
          'córners de equipo con favorito 65 %%+ en clubes: %.1f %% (%.1f / %.1f en las dos mitades)'
          % (100 * c['acierto'], 100 * c['primera_mitad'], 100 * c['segunda_mitad']))
    check(not m['adopta_total'],
          'en el total no ayuda (%.1f %% contra %.1f %%): no se aplica'
          % (100 * m['total_65'], 100 * m['total_resto']))
    s = json.load(open('_v320_selecciones.json', encoding='utf-8'))['grupos']
    check(s['equipo | 65 %+']['acierto'] >= 0.78
          and s['equipo | 65 %+']['acierto'] > s['equipo | 50-65 %']['acierto'],
          'selecciones, con sus cuotas (git del tablero, capturas y Elo): equipo 65 %%+ %.1f %% '
          'contra %.1f %% con 50-65 %%'
          % (100 * s['equipo | 65 %+']['acierto'], 100 * s['equipo | 50-65 %']['acierto']))


def probar_regla():
    import modo_modelo as mm
    eq = {'veredicto': 'meter', 'mercado': 'Córners',
          'pick': {'mercado': 'Córners', 'etiqueta': 'Local', 'apuesta': 'Córners Local: Más de 4.5'}}
    tot = {'veredicto': 'meter', 'mercado': 'Córners',
           'pick': {'mercado': 'Córners', 'etiqueta': 'Total', 'apuesta': 'Córners: Menos de 10.5'}}
    check(mm.corners_equipo_sin_favorito(eq, 0.58) is not None, 'favorito al 58 %: no se mete')
    check(mm.corners_equipo_sin_favorito(eq, None) is not None, 'sin dato del favorito: no se mete')
    check(mm.corners_equipo_sin_favorito(eq, 0.70) is None, 'favorito al 70 %: sí')
    check(mm.corners_equipo_sin_favorito(tot, 0.50) is None, 'al total no se le aplica')
    p = {'partido': 'A vs B', 'implicitas': {'1x2': {'home': 0.30, 'draw': 0.25, 'away': 0.45}},
         'board': {'Gana A': 0.8, 'Gana B': 0.1}}
    check(abs(mm.prob_favorito(p) - 0.45) < 1e-9, 'el favorito sale de la casa sin margen (lo medido)')
    check(abs(mm.prob_favorito({'partido': 'A vs B', 'board': {'Gana A': 0.7, 'Gana B': 0.1}}) - 0.7) < 1e-9,
          'y si no hay casa, del modelo')
    src = open('modo_modelo.py', encoding='utf-8').read()
    # v324 — las reglas de «meter» se juntaron en `_motivo_fuera`, que usan la
    # línea elegida y la que la sustituye
    check('corners_equipo_sin_favorito(v, fav)' in src
          and '_motivo_fuera(v, _fav, _lam_ck)' in src,
          'la regla está en la decisión de «meter»')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medido()
    print('\n=== 2. la regla ===')
    probar_regla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
