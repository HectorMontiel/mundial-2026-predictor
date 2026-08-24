#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v166 — EL UMBRAL DE CORDURA, MEDIDO SOBRE EL HISTÓRICO QUE YA TENEMOS.

Qué corrige
-----------
La v165 recorta la probabilidad que se enseña cuando el modelo se separa más de
**15 puntos** de la implícita de la casa. Ese 15 fue una intuición y estaba
escrito como tal. No hace falta esperar a acumular nada: el proyecto ya tiene
dos ledgers WALK-FORWARD con la probabilidad que el modelo dio de verdad, el
resultado real y la cuota de CIERRE.

    pick_ledger_totales.csv   47.794 partidos · 17.532 con cuota O/U 2,5
    pick_ledger.csv           47.948 partidos · 36.006 con cierre 1X2
                                               26.666 con Pinnacle

Las dos cosas que importan, y no son la misma
---------------------------------------------
El control de cordura no promete ganar dinero: promete que **el número que se
enseña se parezca a lo que pasa**. Así que se miden las dos y se enseñan las
dos:

  · **ROI** de respaldar el lado que el modelo prefiere, a la cuota de cierre,
    con su percentil 5 de bootstrap. Es la regla de oro del proyecto: nada se
    decide sobre una media.
  · **BRECHA DE CALIBRACIÓN** = |media(p del modelo) − frecuencia real| en ese
    tramo. Es lo que el usuario ve: si el modelo dice 80 % y pasa el 62 % de
    las veces, el 80 % es mentira aunque la apuesta fuera rentable.

Se mira el lado que el modelo PREFIERE, no los dos, porque es el único que la
tarjeta enseña — medir los dos mezclaría la apuesta que se propone con la que
nunca se propuso.

    python _v166_umbral_cordura.py
"""
import json
import logging
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v166_umbral_cordura.json'
TRAMOS = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
          (0.20, 1.01)]
# Los tramos finos existen porque los gruesos dejaron la respuesta a medias: en
# goles la brecha pasa de 0,039 (5-10 pp) a 0,103 (10-15 pp), y el umbral del
# proyecto para «aceptable» es 0,05. El corte está DENTRO de ese salto, y con
# tramos de cinco puntos no se puede ver dónde.
TRAMOS_FINOS = [(0.00, 0.03), (0.03, 0.05), (0.05, 0.07), (0.07, 0.09),
                (0.09, 0.11), (0.11, 0.13), (0.13, 0.15), (0.15, 0.20),
                (0.20, 1.01)]
N_BOOT = 2000
SEMILLA = 20260824


def devig_dos(c1, c2):
    """Probabilidad justa del primer lado en un mercado de dos vías."""
    i1, i2 = 1.0 / c1, 1.0 / c2
    s = i1 + i2
    return i1 / s


def devig_tres(ch, cd, ca):
    """Probabilidades justas de un 1X2, método `potencia` (v80)."""
    imp = np.stack([1.0 / ch, 1.0 / cd, 1.0 / ca], axis=1)
    salida = np.zeros_like(imp)
    for i in range(imp.shape[0]):
        p = imp[i]
        lo, hi = 0.5, 1.5
        for _ in range(40):
            k = (lo + hi) / 2
            if (p ** k).sum() > 1.0:
                lo = k
            else:
                hi = k
        q = p ** ((lo + hi) / 2)
        salida[i] = q / q.sum()
    return salida


def _boot_p5(ganancias: np.ndarray, rng) -> float:
    """Percentil 5 del ROI por bootstrap. Nada se decide sobre una media."""
    if len(ganancias) < 30:
        return float('nan')
    idx = rng.integers(0, len(ganancias), size=(N_BOOT, len(ganancias)))
    return float(np.percentile(ganancias[idx].mean(axis=1), 5) * 100)


def _tabla(nombre, desvio, p_mod, gano, cuota, rng, tramos=None,
           signo=None):
    """
    Una fila por tramo de desvío: n, ROI, p5, calibración.

    `signo` restringe al lado del desvío: `+1` el modelo por ENCIMA de la casa,
    `-1` por debajo. Hace falta porque la regla de la v165 usa el valor
    absoluto, y eso sólo está justificado si las dos direcciones mienten igual.
    """
    print('\n' + '=' * 78)
    print(nombre)
    print('=' * 78)
    print('%-14s %7s %9s %9s %9s %9s %9s'
          % ('desvío', 'n', 'ROI %', 'p5 %', 'media p', 'real', 'brecha'))
    print('-' * 78)
    filas = []
    ad = np.abs(desvio)
    if signo is not None:
        fuera = (desvio * signo) <= 0
        ad = np.where(fuera, -1.0, ad)
    for lo, hi in (tramos or TRAMOS):
        m = (ad >= lo) & (ad < hi)
        n = int(m.sum())
        if n == 0:
            continue
        g = np.where(gano[m] == 1, cuota[m] - 1.0, -1.0)
        roi = float(g.mean() * 100)
        p5 = _boot_p5(g, rng)
        media_p = float(p_mod[m].mean())
        real = float(gano[m].mean())
        brecha = abs(media_p - real)
        etq = ('%.0f-%.0f pp' % (lo * 100, hi * 100)) if hi <= 1.0 \
            else '> %.0f pp' % (lo * 100)
        print('%-14s %7d %9.2f %9.2f %9.3f %9.3f %9.3f'
              % (etq, n, roi, p5, media_p, real, brecha))
        filas.append({'tramo': etq, 'n': n, 'roi': round(roi, 3),
                      'p5': None if np.isnan(p5) else round(p5, 3),
                      'media_p': round(media_p, 4),
                      'real': round(real, 4), 'brecha': round(brecha, 4)})
    return filas


def _acumulado(nombre, desvio, p_mod, gano, cuota, rng):
    """
    Lo mismo pero ACUMULADO por encima de cada corte candidato.

    Es la vista que decide: el umbral no separa un tramo, separa «lo que se
    deja pasar» de «lo que se recorta». Un tramo intermedio malo con dos
    vecinos buenos no justifica un corte ahí.
    """
    print('\n' + '-' * 78)
    print('%s — ACUMULADO POR ENCIMA DEL CORTE' % nombre)
    print('%-10s %8s %9s %9s %9s %9s %9s'
          % ('corte', 'n', 'ROI %', 'p5 %', 'media p', 'real', 'brecha'))
    print('-' * 78)
    filas = []
    ad = np.abs(desvio)
    for corte in (0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25):
        m = ad > corte
        n = int(m.sum())
        if n < 30:
            continue
        g = np.where(gano[m] == 1, cuota[m] - 1.0, -1.0)
        media_p = float(p_mod[m].mean())
        real = float(gano[m].mean())
        print('%-10s %8d %9.2f %9.2f %9.3f %9.3f %9.3f'
              % ('> %.0f pp' % (corte * 100), n, g.mean() * 100,
                 _boot_p5(g, rng), media_p, real, abs(media_p - real)))
        filas.append({'corte': round(corte, 2), 'n': n,
                      'roi': round(float(g.mean() * 100), 3),
                      'p5': round(_boot_p5(g, rng), 3),
                      'media_p': round(media_p, 4), 'real': round(real, 4),
                      'brecha': round(abs(media_p - real), 4)})
    return filas


def goles(rng):
    """O/U 2,5: el mercado donde falló la tarjeta del 2026-08-23."""
    d = pd.read_csv('pick_ledger_totales.csv')
    d = d[d['cuota_over25'].notna() & d['cuota_under25'].notna()].copy()
    d = d[(d['cuota_over25'] > 1) & (d['cuota_under25'] > 1)]
    p_over = d['p_over_2.5'].astype(float).values
    c_o = d['cuota_over25'].astype(float).values
    c_u = d['cuota_under25'].astype(float).values
    mkt_over = devig_dos(c_o, c_u)
    real_over = d['over_2.5_real'].astype(int).values

    # el lado que la tarjeta enseñaría: el que el modelo prefiere
    lado_over = p_over >= 0.5
    p_mod = np.where(lado_over, p_over, 1.0 - p_over)
    p_mkt = np.where(lado_over, mkt_over, 1.0 - mkt_over)
    cuota = np.where(lado_over, c_o, c_u)
    gano = np.where(lado_over, real_over, 1 - real_over)
    print('\nGOLES O/U 2,5 — %d partidos con las dos cuotas de cierre '
          '(%s a %s, %d competiciones)'
          % (len(d), d['fecha'].min(), d['fecha'].max(), d['liga'].nunique()))
    desv = p_mod - p_mkt
    print('  desvío |modelo − casa|: mediana %.3f · p90 %.3f · máx %.3f'
          % (np.median(np.abs(desv)), np.percentile(np.abs(desv), 90),
             np.abs(desv).max()))
    t = _tabla('GOLES O/U 2,5 — POR TRAMO DE DESVÍO', desv, p_mod, gano,
               cuota, rng)
    tf = _tabla('GOLES O/U 2,5 — TRAMOS FINOS (dónde cruza el 0,05)', desv,
                p_mod, gano, cuota, rng, tramos=TRAMOS_FINOS)
    ta = _tabla('GOLES — SÓLO CUANDO EL MODELO VA POR ENCIMA DE LA CASA', desv,
                p_mod, gano, cuota, rng, tramos=TRAMOS_FINOS, signo=+1)
    tb = _tabla('GOLES — SÓLO CUANDO EL MODELO VA POR DEBAJO', desv, p_mod,
                gano, cuota, rng, tramos=TRAMOS_FINOS, signo=-1)
    a = _acumulado('GOLES O/U 2,5', desv, p_mod, gano, cuota, rng)
    return {'n': len(d), 'tramos': t, 'finos': tf, 'por_encima': ta,
            'por_debajo': tb, 'acumulado': a}


def x2(rng):
    """1X2, con el ancla que valida el sistema: Pinnacle y, si no, el cierre."""
    d = pd.read_csv('pick_ledger.csv')
    cols_c = ['cuota_home', 'cuota_draw', 'cuota_away']
    cols_p = ['pin_home', 'pin_draw', 'pin_away']
    tiene_pin = d[cols_p].notna().all(axis=1) & (d[cols_p] > 1).all(axis=1)
    tiene_cie = d[cols_c].notna().all(axis=1) & (d[cols_c] > 1).all(axis=1)
    d = d[tiene_pin | tiene_cie].copy()
    usa_pin = (d[cols_p].notna().all(axis=1)
               & (d[cols_p] > 1).all(axis=1)).values
    ancla = np.where(usa_pin[:, None], d[cols_p].values,
                     d[cols_c].values).astype(float)
    # se apuesta SIEMPRE al cierre disponible, no al ancla: el ancla sólo sirve
    # para saber qué cree el mercado.
    precio = np.where(d[cols_c].notna().all(axis=1).values[:, None],
                      d[cols_c].values, d[cols_p].values).astype(float)
    p_mkt = devig_tres(ancla[:, 0], ancla[:, 1], ancla[:, 2])
    p_mod = d[['p_home', 'p_draw', 'p_away']].values.astype(float)
    lado = p_mod.argmax(axis=1)
    fila = np.arange(len(d))
    res = d['resultado'].astype(int).values
    print('\n\n1X2 — %d partidos con cierre (%d con Pinnacle de ancla, '
          '%d competiciones)'
          % (len(d), int(usa_pin.sum()), d['liga'].nunique()))
    desv = p_mod[fila, lado] - p_mkt[fila, lado]
    print('  desvío |modelo − casa|: mediana %.3f · p90 %.3f · máx %.3f'
          % (np.median(np.abs(desv)), np.percentile(np.abs(desv), 90),
             np.abs(desv).max()))
    gano = (res == lado).astype(int)
    t = _tabla('1X2 (el lado que el modelo prefiere) — POR TRAMO', desv,
               p_mod[fila, lado], gano, precio[fila, lado], rng)
    tf = _tabla('1X2 — TRAMOS FINOS', desv, p_mod[fila, lado], gano,
                precio[fila, lado], rng, tramos=TRAMOS_FINOS)
    ta = _tabla('1X2 — SÓLO CUANDO EL MODELO VA POR ENCIMA DE LA CASA', desv,
                p_mod[fila, lado], gano, precio[fila, lado], rng,
                tramos=TRAMOS_FINOS, signo=+1)
    a = _acumulado('1X2', desv, p_mod[fila, lado], gano, precio[fila, lado],
                   rng)
    return {'n': len(d), 'tramos': t, 'finos': tf, 'por_encima': ta,
            'acumulado': a}


def _brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def _ece(p, y, n_bins: int = 10):
    """
    Error de calibración por deciles.

    Es la métrica con la que la v163 decide, y no el error marginal
    |media(p) − frecuencia|: ése se deja engañar por dos sesgos que se cancelan
    (§2b del traspaso). Aquí se enseñan las tres.
    """
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    bordes = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    bordes[0], bordes[-1] = -1e-9, 1 + 1e-9
    total, n = 0.0, len(p)
    for i in range(n_bins):
        m = (p >= bordes[i]) & (p < bordes[i + 1])
        if m.sum() == 0:
            continue
        total += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(total / max(n, 1))


def mezcla(rng):
    """
    ¿Y SI EL PROBLEMA NO ES EL UMBRAL, SINO QUE A GOLES NADIE LE APLICÓ LO QUE
    SÍ SE LE APLICA AL 1X2?

    El 1X2 se encoge hacia el mercado desde la v71 (`calibracion_mercado`,
    w=0,25) y en la tabla de arriba calibra perfecto en TODOS los tramos de
    desvío: brecha ≤ 0,008 hasta los 20 puntos. Los goles NUNCA recibieron ese
    tratamiento, y su brecha llega a 0,281.

    Mismo modelo, mismos partidos, mismo día: la única diferencia es el
    encogimiento. Así que antes de elegir un umbral hay que ver cuánto queda
    del problema si se aplica lo que ya está validado.

    Se elige `w` por ECE, que es la métrica con la que decide este proyecto
    desde la v163.
    """
    d = pd.read_csv('pick_ledger_totales.csv')
    d = d[d['cuota_over25'].notna() & d['cuota_under25'].notna()].copy()
    d = d[(d['cuota_over25'] > 1) & (d['cuota_under25'] > 1)]
    p_mod = d['p_over_2.5'].astype(float).values
    p_mkt = devig_dos(d['cuota_over25'].astype(float).values,
                      d['cuota_under25'].astype(float).values)
    y = d['over_2.5_real'].astype(int).values

    print('\n\n' + '=' * 78)
    print('GOLES — ¿CUÁNTO SE ARREGLA ENCOGIENDO HACIA EL MERCADO?')
    print('=' * 78)
    print('%-8s %10s %10s %10s %12s' % ('w', 'log-loss', 'Brier', 'ECE',
                                        'brecha >15pp'))
    print('-' * 78)
    filas, mejor = [], None
    desv0 = p_mod - p_mkt
    for w in [round(x * 0.05, 2) for x in range(0, 21)]:
        p = w * p_mod + (1 - w) * p_mkt
        ll = float(-np.mean(y * np.log(np.clip(p, 1e-9, 1))
                            + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1))))
        e = _ece(p, y)
        m = np.abs(desv0) > 0.15
        # la brecha en el tramo que hoy se recorta, con la p ya mezclada y
        # mirando el lado que la tarjeta enseñaría
        lado = p >= 0.5
        p_lado = np.where(lado, p, 1 - p)
        y_lado = np.where(lado, y, 1 - y)
        brecha15 = abs(float(p_lado[m].mean() - y_lado[m].mean()))
        filas.append({'w': w, 'logloss': round(ll, 5), 'brier': round(_brier(p, y), 5),
                      'ece': round(e, 5), 'brecha_15': round(brecha15, 4)})
        if mejor is None or e < mejor['ece']:
            mejor = filas[-1]
        if int(w * 100) % 10 == 0 or w in (0.25, 0.15, 0.35):
            print('%-8.2f %10.5f %10.5f %10.5f %12.4f'
                  % (w, ll, _brier(p, y), e, brecha15))
    print('\n  MEJOR POR ECE: w = %.2f  (ECE %.5f · Brier %.5f · '
          'brecha en el tramo de >15 pp: %.4f)'
          % (mejor['w'], mejor['ece'], mejor['brier'], mejor['brecha_15']))
    print('  w=1,00 es el modelo solo (lo de hoy): ECE %.5f · brecha %.4f'
          % (filas[-1]['ece'], filas[-1]['brecha_15']))

    # Y AHORA EN EL PESO QUE USA PRODUCCIÓN, QUE ES EL QUE IMPORTA.
    #
    # `calibracion_mercado` tiene un suelo de W_MIN=0,25 fijado y medido en la
    # v75. El óptimo por ECE de arriba cae por debajo, pero bajar ese suelo
    # sería re-litigar una decisión ya medida para OTRO mercado. Con 0,25 la
    # mejora ya es de un orden de magnitud, así que se usa la maquinaria que
    # existe en vez de una constante nueva.
    salida_prod = {}
    for w_prod in (0.25,):
        p = w_prod * p_mod + (1 - w_prod) * p_mkt
        lado = p >= 0.5
        p_lado = np.where(lado, p, 1 - p)
        mkt_lado = np.where(lado, p_mkt, 1 - p_mkt)
        y_lado = np.where(lado, y, 1 - y)
        cu = np.where(lado, d['cuota_over25'].astype(float).values,
                      d['cuota_under25'].astype(float).values)
        salida_prod[str(w_prod)] = _tabla(
            'GOLES CON EL PESO DE PRODUCCIÓN (w=%.2f) — MODELO POR ENCIMA'
            % w_prod, p_lado - mkt_lado, p_lado, y_lado, cu, rng,
            tramos=TRAMOS_FINOS, signo=+1)

    # y cómo queda la tabla de desvíos DESPUÉS de encoger
    w = mejor['w']
    p = w * p_mod + (1 - w) * p_mkt
    lado = p >= 0.5
    p_lado = np.where(lado, p, 1 - p)
    mkt_lado = np.where(lado, p_mkt, 1 - p_mkt)
    y_lado = np.where(lado, y, 1 - y)
    cuota = np.where(lado, d['cuota_over25'].astype(float).values,
                     d['cuota_under25'].astype(float).values)
    t = _tabla('GOLES YA ENCOGIDOS (w=%.2f) — POR TRAMO DE DESVÍO' % w,
               p_lado - mkt_lado, p_lado, y_lado, cuota, rng,
               tramos=TRAMOS_FINOS, signo=+1)
    return {'curva': filas, 'mejor_w': mejor, 'tras_encoger': t, 'produccion': salida_prod}


def escribir_umbrales(doc):
    """
    Convierte la medición en el fichero que lee producción.

    Se escribe A PARTIR de la tabla y no a mano: si alguien vuelve a correr
    esto con más partidos y el corte se mueve, el fichero se mueve con él. Un
    umbral copiado a mano en el código es el que hubo que arreglar hoy.

    La regla de elección: el primer tramo cuya BRECHA DE CALIBRACIÓN supera
    0,05 — el mismo umbral con el que este proyecto declara «aceptable» una
    estimación desde la v162 (`confianza_mercado.UMBRAL_ACEPTABLE`). Por debajo
    de él lo que se enseña se parece a lo que pasa; por encima, no.
    """
    def _corte(tabla, por_defecto):
        for f in tabla:
            if f['brecha'] > 0.05 and f['n'] >= 200:
                # el corte es el BORDE INFERIOR del primer tramo que miente
                txt = f['tramo'].split()[0]
                lo = txt.split('-')[0].replace('>', '')
                try:
                    return round(float(lo) / 100.0, 3)
                except ValueError:
                    return por_defecto
        return por_defecto

    prod = (doc['mezcla'].get('produccion') or {}).get('0.25') or []
    corte_goles = _corte(prod, 0.05)
    corte_x2 = _corte(doc['1x2'].get('por_encima') or [], 0.05)
    salida = {
        'generado_por': '_v166_umbral_cordura.py',
        'n_goles': doc['goles']['n'], 'n_1x2': doc['1x2']['n'],
        'w_encogimiento': 0.25,
        'w_optimo_por_ece': doc['mezcla']['mejor_w']['w'],
        'umbrales': {'Goles': corte_goles, 'BTTS': corte_goles,
                     '1X2': corte_x2},
        'nota': ('Umbral = borde inferior del primer tramo de desvío cuya '
                 'brecha de calibración pasa de 0,05, medido sobre los ledgers '
                 'walk-forward. BTTS hereda el de Goles: sale de la misma '
                 'matriz de marcador y no hay cuota histórica de BTTS con la '
                 'que medirlo por separado.')}
    json.dump(salida, open('cordura_umbrales.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n' + '=' * 78)
    print('UMBRALES ESCRITOS -> cordura_umbrales.json')
    print('=' * 78)
    for k, v in salida['umbrales'].items():
        print('  %-8s %.0f pp' % (k, v * 100))
    print('  encogimiento hacia el mercado: w = %.2f (suelo de '
          'calibracion_mercado; el óptimo por ECE es %.2f)'
          % (salida['w_encogimiento'], salida['w_optimo_por_ece']))


def main():
    rng = np.random.default_rng(SEMILLA)
    doc = {'goles': goles(rng), '1x2': x2(rng)}
    doc['mezcla'] = mezcla(rng)
    escribir_umbrales(doc)
    json.dump(doc, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
