#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — ¿ESTÁ NUESTRA LAMBDA POR DEBAJO DE LA QUE IMPLICA LA CASA?

Por qué se mira
---------------
Al enseñar la probabilidad sobre la línea de la casa apareció un patrón: varios
delanteros salían con 14-16 % sobre su línea. Si la casa pone la línea donde
parte su opinión por la mitad, nuestro modelo estaría diciendo mucho menos que
ella de forma sistemática — y eso sería un sesgo, no una discrepancia.

La medición del modelo por jugador (§13.7) dio ECE 0,029 contra el RESULTADO
REAL, así que no debería estar sesgado. Pero se midió sobre titulares de
Premier, LaLiga y Liga MX con datos de los últimos partidos de ESPN; en la
tarjeta se usa el ROSTER DE TEMPORADA, que es otra fuente y otra ventana. Este
script comprueba si esa diferencia se nota.

Cómo
----
Para cada jugador con línea, se compara nuestra lambda con la que implica la
casa: si la línea equilibrada es L y la probabilidad de la casa (quitado el
margen de forma aproximada, 1/cuota) es p, la lambda implícita es la que hace
P(X > L) = p con Poisson. Se resuelve por bisección.

No se busca acertar la lambda de la casa —eso sería copiarla— sino ver si hay
un SESGO sistemático en una dirección.


LO QUE SALIÓ, Y POR QUÉ NO SE PERSIGUIÓ HASTA EL FINAL
------------------------------------------------------
Nuestra lambda va por debajo: mediana de la razón 0,619 la primera vez.
Buscando el motivo se encontró UN DEFECTO REAL y se arregló:

    el modelo se validó sobre remates POR TITULARIDAD (§13.7) y producción
    dividía entre APARICIONES, que incluyen entrar diez minutos desde el
    banquillo. Medido sobre 24.059 apariciones: de titular se remata 0,9888 y
    de suplente 0,4741, y el 29 % de las apariciones son suplencias.

Con `subIns` del roster se despejan las titularidades y la razón sube a 0,668.

El resto del hueco NO se persiguió, y la razón es que este patrón de medida no
puede zanjarlo:

  · **el margen de la casa no se puede medir aquí.** Playdoit publica SÓLO el
    lado «Más de» de estos mercados —comprobado: 0 pares Más/Menos con los dos
    lados en cinco partidos— así que el `1/cuota` no se puede desvigorizar y la
    lambda implícita sale inflada por un margen desconocido. Los mercados de
    jugador a un solo lado cargan márgenes altos.
  · **la población no está emparejada.** La casa cotiza a los ~20 jugadores por
    equipo que espera que jueguen; nuestra lista es la plantilla cacheada
    entera, con suplentes de rotación que rematan poco de verdad.

Y en cambio hay dos comprobaciones contra la REALIDAD que dicen que el nivel
está bien:

  · el modelo por jugador se midió contra el resultado real y dio ECE 0,029
    sobre 6.688 titulares-partido (§13.7);
  · la cuota posicional está exactamente escalada: un once 4-4-2 suma 0,857 de
    los remates del equipo, y la fracción REAL que se llevan los titulares es
    0,857 de mediana sobre 1.515 equipos-partido.

Así que la referencia de la casa queda anotada como lo que es —una señal
blanda— y la forma de zanjarlo es liquidar `remates_snapshots.csv` cuando haya
volumen, que es lo único que mide dinero en vez de opiniones.

    python _v164_lambda_contra_casa.py
"""
import json
import logging
import math
import sys
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v164_lambda_contra_casa.json'


def _p_mas(lam, L):
    k = int(math.floor(L))
    acum, t = 0.0, math.exp(-lam)
    for i in range(k + 1):
        if i:
            t *= lam / i
        acum += t
    return 1.0 - acum


def lambda_implicita(L, p, lo=0.01, hi=15.0):
    """La lambda de Poisson que hace P(X > L) = p."""
    if not (0.0 < p < 1.0):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _p_mas(mid, L) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def main():
    import lineas_jugador as lj
    import remates_jugador as rjg

    doc = lj.cargar()
    partidos = doc.get('partidos') or {}
    if not partidos:
        print('no hay precálculo del día; corre antes `lineas_jugador.py`')
        return 1

    filas = []
    for llave, datos in list(partidos.items())[:40]:
        clave, h, a = (datos.get('clave_liga'), datos.get('home'),
                       datos.get('away'))
        if not (clave and h and a):
            continue
        qr = rjg.partido(clave, h, a, en_vivo=False)
        if not qr:
            continue
        for lado in ('home', 'away'):
            for j in (qr.get(lado + '_jugadores') or []):
                L, lam = j.get('linea_tot'), j.get('lambda_tot')
                cuota = j.get('cuota_tot')
                if L is None or lam is None or not cuota:
                    continue
                try:
                    p_casa = 1.0 / float(cuota)
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
                # el margen de la casa infla `1/cuota`; con un mercado de dos
                # lados el margen típico reparte ~5 % entre los dos, así que se
                # quita a ojo. No hace falta más precisión: lo que se busca es
                # un sesgo grande, no el tercer decimal.
                p_casa = min(max(p_casa / 1.05, 0.01), 0.99)
                lam_casa = lambda_implicita(L, p_casa)
                if lam_casa is None:
                    continue
                filas.append({'jugador': j.get('jugador'),
                              'clave': clave, 'linea': L,
                              'nuestra': round(float(lam), 3),
                              'casa': round(float(lam_casa), 3),
                              'ratio': round(float(lam) / lam_casa, 3)})

    if not filas:
        print('sin jugadores comparables')
        return 1

    import statistics as st
    ratios = [f['ratio'] for f in filas]
    nuestras = [f['nuestra'] for f in filas]
    casas = [f['casa'] for f in filas]
    print('%d jugadores comparados\n' % len(filas))
    print('lambda NUESTRA  media %.3f · mediana %.3f'
          % (st.mean(nuestras), st.median(nuestras)))
    print('lambda DE LA CASA media %.3f · mediana %.3f'
          % (st.mean(casas), st.median(casas)))
    print()
    print('razón nuestra/casa: mediana %.3f · media %.3f'
          % (st.median(ratios), st.mean(ratios)))
    print('   por debajo de 0,80 ... %3d (%.0f %%)'
          % (sum(1 for r in ratios if r < 0.8),
             100.0 * sum(1 for r in ratios if r < 0.8) / len(ratios)))
    print('   entre 0,80 y 1,25 .... %3d (%.0f %%)'
          % (sum(1 for r in ratios if 0.8 <= r <= 1.25),
             100.0 * sum(1 for r in ratios if 0.8 <= r <= 1.25) / len(ratios)))
    print('   por encima de 1,25 ... %3d (%.0f %%)'
          % (sum(1 for r in ratios if r > 1.25),
             100.0 * sum(1 for r in ratios if r > 1.25) / len(ratios)))
    print()
    print('VEREDICTO: ', end='')
    m = st.median(ratios)
    if m < 0.85:
        print('nuestra lambda va SISTEMÁTICAMENTE POR DEBAJO de la casa.')
    elif m > 1.18:
        print('nuestra lambda va sistemáticamente POR ENCIMA de la casa.')
    else:
        print('no hay sesgo sistemático: la mediana está cerca de 1.')
    print()
    print('los diez más alejados por abajo:')
    for f in sorted(filas, key=lambda f: f['ratio'])[:10]:
        print('   %-26s %-14s +%.1f  nuestra %.2f · casa %.2f  (x%.2f)'
              % (f['jugador'][:26], f['clave'], f['linea'], f['nuestra'],
                 f['casa'], f['ratio']))
    json.dump({'n': len(filas), 'mediana_ratio': round(st.median(ratios), 4),
               'filas': filas}, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\nescrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
