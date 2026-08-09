#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — ¿La guardia del emparejador mata los falsos SIN matar los buenos?

Un filtro que rechaza de más es tan malo como uno que acepta de más: dejaría
partidos legítimos «sin cuota» y el tablón perdería cobertura, que es
exactamente lo contrario de lo que busca el proyecto. Así que se mide en las
dos direcciones sobre el tablón real:

  1. el caso que motivó el arreglo (Independiente/Belgrano femenino contra
     Belgrano/Independiente Rivadavia masculino) ya no casa,
  2. la contención legítima («Gremio» ≡ «Gremio FBPA») sigue casando,
  3. y la COBERTURA GLOBAL apenas cambia: se cuentan los partidos de Pinnacle
     que encuentran precio en Bovada y en Playdoit, y se enumera uno a uno lo
     que se ha dejado de emparejar, para poder mirarlo.

    python _v114_validar_emparejado.py
"""
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import cuotas_multi as cm

FALLOS = []


def check(nombre, condicion, detalle=''):
    print(f"  {'✅' if condicion else '❌'} {nombre}" +
          (f" — {detalle}" if detalle else ''))
    if not condicion:
        FALLOS.append(nombre)


def main() -> int:
    print('=' * 78)
    print('1. SIMILITUD: contención ya no empata con igualdad')
    print('=' * 78)
    s_igual = cm._sim_club('Belgrano', 'Belgrano')
    s_contiene = cm._sim_club('Independiente', 'Independiente Rivadavia')
    s_gremio = cm._sim_club('Gremio', 'Gremio FBPA')
    check('igualdad exacta puntúa 1.0', s_igual == 1.0, f'{s_igual}')
    check('contención puntúa por debajo', s_contiene < s_igual,
          f'Independiente/Independiente Rivadavia = {s_contiene}')
    check('contención SIGUE por encima del umbral 0.80', s_gremio >= 0.80,
          f'Gremio/Gremio FBPA = {s_gremio}')

    print('\n' + '=' * 78)
    print('2. CATEGORÍA: femenino y masculino no son el mismo partido')
    print('=' * 78)
    cat_f = cm.categoria_partido('CA Independiente (W)', 'Belgrano (W)', '')
    cat_m = cm.categoria_partido('Independiente', 'Belgrano', '')
    cat_liga = cm.categoria_partido('Independiente', 'Belgrano',
                                    'Argentina - Primera Division Women')
    check('marca (W) detectada', 'fem' in cat_f, str(set(cat_f)))
    check('partido masculino sin marca', not cat_m, str(set(cat_m)))
    check('la marca también se lee de la LIGA', 'fem' in cat_liga,
          str(set(cat_liga)))
    check('sub-20 detectado',
          'filial' in cm.categoria_partido('Brasil U20', 'Chile U20', ''))
    check('un club llamado «Boca Juniors» NO es filial',
          not cm.categoria_partido('Boca Juniors', 'River Plate', ''))
    # la marca débil «II»/«B» sólo cuenta en la categoría EFECTIVA, y nunca
    # desde el nombre de la competición (ver `categoria_efectiva`)
    check('«Benfica II» ≡ «Benfica Sub-21» (mismo filial, otra notación)',
          cm.categoria_efectiva('Benfica II', 'Leixoes', 'Liga 2')
          == cm.categoria_efectiva('Benfica Sub-21', 'Leixoes', 'Segunda Liga'))
    check('«Benfica II» ≠ «Benfica» (filial contra primer equipo)',
          cm.categoria_efectiva('Benfica II', 'Leixoes', '')
          != cm.categoria_efectiva('Benfica', 'Leixoes', ''))
    check('«Primera B» en el nombre de la LIGA no marca filial',
          not cm.categoria_efectiva('Laferrere', 'Arsenal de Sarandi',
                                    'Argentina - Primera B Metropolitana'))

    print('\n' + '=' * 78)
    print('3. FECHA: cinco días de diferencia no son el mismo partido')
    print('=' * 78)
    idx = {'belgrano|independiente rivadavia': {
        'home': 'Belgrano', 'away': 'Independiente Rivadavia',
        'fecha': '2026-08-15T22:00:00', 'cuotas': {'home': 1.95, 'away': 4.3}}}
    sin_fecha = cm._buscar(idx, 'Independiente', 'Belgrano', 'futbol')
    con_fecha = cm._buscar(idx, 'Independiente', 'Belgrano', 'futbol',
                           fecha='2026-08-10T18:00:00')
    check('con la fecha del partido real, NO casa', con_fecha is None,
          'era el falso arbitraje del 0,7737')
    check('el mismo día sí casa',
          cm._buscar(idx, 'Belgrano', 'Independiente Rivadavia', 'futbol',
                     fecha='2026-08-15T20:00:00') is not None)
    print(f"    (sin fecha seguía casando: {bool(sin_fecha)} — por eso el "
          f"barrido ahora la pasa)")

    print('\n' + '=' * 78)
    print('4. AMBIGÜEDAD: dos candidatos empatados se descartan')
    print('=' * 78)
    idx2 = {
        'independiente|belgrano': {
            'home': 'Independiente', 'away': 'Belgrano',
            'cuotas': {'home': 2.0, 'away': 3.0}},
        'independiente rivadavia|belgrano': {
            'home': 'Independiente Rivadavia', 'away': 'Belgrano',
            'cuotas': {'home': 2.5, 'away': 2.6}}}
    r = cm._buscar(idx2, 'Independiente', 'Belgrano', 'futbol')
    check('gana el EXACTO, no el que lo contiene',
          r is not None and r['home'] == 'Independiente',
          f"eligió {r['home'] if r else None}")

    print('\n' + '=' * 78)
    print('5. COBERTURA REAL — ¿se ha perdido emparejamiento útil?')
    print('=' * 78)
    cm.precargar('futbol')
    pin = cm._indice('futbol')
    bov = cm._indice_bov('futbol')
    pdt = cm._indice_pdt('futbol')
    print(f'  tablón: Pinnacle {len(pin)} · Bovada {len(bov)} · '
          f'Playdoit {len(pdt)}')

    for nombre, idxc in (('Bovada', bov), ('Playdoit', pdt)):
        casados = ambiguos = 0
        rechazados_fecha = []
        for v in pin.values():
            hit = cm._buscar(idxc, v['home'], v['away'], 'futbol',
                             fecha=v.get('fecha'), liga=v.get('liga'))
            if hit:
                casados += 1
                continue
            # ¿habría casado sin las guardias? entonces la guardia actuó
            laxo = cm._buscar(idxc, v['home'], v['away'], 'futbol')
            if laxo:
                d = cm._dias_entre(v.get('fecha'), laxo.get('fecha'))
                rechazados_fecha.append(
                    (v['home'], v['away'], laxo['home'], laxo['away'],
                     d, v.get('liga'), laxo.get('liga')))
        print(f'\n  {nombre}: {casados}/{len(pin)} partidos de Pinnacle con '
              f'precio ({casados/max(len(pin),1)*100:.1f} %)')
        print(f'  emparejamientos que las guardias han BLOQUEADO: '
              f'{len(rechazados_fecha)}')
        for h, a, h2, a2, d, l1, l2 in rechazados_fecha[:15]:
            _d = f'{d:.1f} d' if d is not None else 'sin fecha'
            print(f'    · «{h} vs {a}» ({l1})')
            print(f'      ≠ «{h2} vs {a2}» ({l2}) — Δ {_d}')

    print('\n' + '=' * 78)
    if FALLOS:
        print(f'❌ {len(FALLOS)} comprobaciones fallidas: {FALLOS}')
        return 1
    print('✅ TODO OK — las guardias hacen lo que dicen')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
