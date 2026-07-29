#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v81 — ¿Qué fracción de Kelly conviene, y conviene que sea dinámica?

Situación
---------
El stake sale de ⅛ de Kelly con tope del 5 % por pick (`aplicar_kelly`) y un
cap global del 20 % por jornada (v27). El ⅛ es una decisión de prudencia que
nunca se optimizó, y la propuesta es un Kelly **dinámico** que suba o baje con
la racha y la volatilidad recientes.

Antes de implementar nada hay que responder dos preguntas por separado, porque
son distintas:

  1. ¿Cuál es la fracción FIJA óptima? (línea base honesta)
  2. ¿Aporta algo hacerla DINÁMICA sobre esa base?

El criterio no puede ser solo el capital final: una fracción alta gana más en
la mediana y arruina en la cola. Se miden las tres cosas que importan juntas:
crecimiento (mediana del capital final), riesgo (máxima caída) y ruina.

Método
------
Se toma la secuencia REAL de picks del ledger —los que producción habría
emitido, en orden cronológico— y se remuestrea en bloques (bootstrap por
bloques de 20 apuestas, que conserva las rachas; un bootstrap i.i.d. las
destruiría y es justo lo que se quiere estudiar). Cada camino se juega con cada
política de stake.

**Importante sobre la fuga**: la política dinámica solo puede mirar hacia
atrás. La racha y la volatilidad se calculan con las apuestas YA resueltas.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('kelly')

LEDGER = 'pick_ledger_total.csv'
N_CAMINOS = 4000
BLOQUE = 20
CAP_PICK = 0.05          # tope por pick, como en produccion
RUINA = 0.30             # se considera ruina caer por debajo del 30 % del inicial


def secuencia_picks():
    """Los picks que produccion habria emitido, en orden cronologico."""
    import recalibrate_from_history as rec
    import calibracion_mercado as cm
    import alpha_finder as af

    d = rec.cargar(LEDGER).dropna(subset=['cuota_home'])
    d = d[d['deporte'] == 'Fútbol']
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['fecha']).sort_values('fecha').reset_index(drop=True)

    pm = d[['p_home', 'p_draw', 'p_away']].values.astype(float)
    mk = d[['m_home', 'm_draw', 'm_away']].values.astype(float)
    cu = np.fmax(
        d[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(0).values.astype(float),
        np.nan_to_num(d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float),
                      nan=0.0))
    w = d['liga'].map(cm.peso_modelo).values[:, None]
    p = w * pm + (1 - w) * mk
    p = p / p.sum(axis=1, keepdims=True)
    y = d['resultado'].values.astype(int)
    f = np.arange(len(d))
    k = p.argmax(axis=1)
    prob, cuota = p[f, k], cu[f, k]
    ev = cuota * prob - 1.0
    sel = (prob > 0.55) & (ev > af.MIN_EV) & (cuota > af.MIN_CUOTA)
    log.info(f'{int(sel.sum())} picks emitidos de {len(d)} partidos')
    return prob[sel], cuota[sel], (k[sel] == y[sel])


def kelly(prob, cuota):
    b = np.maximum(cuota - 1.0, 1e-6)
    return np.clip((b * prob - (1 - prob)) / b, 0.0, None)


def simular(prob, cuota, gano, politica, caminos, rng):
    """Devuelve capital final, maxima caida y ruina de cada camino."""
    n = len(prob)
    finales = np.empty(len(caminos))
    caidas = np.empty(len(caminos))
    ruinas = np.zeros(len(caminos), dtype=bool)
    kf = kelly(prob, cuota)
    for c, idx in enumerate(caminos):
        cap, pico, peor = 1.0, 1.0, 0.0
        hist = []
        for i in idx:
            frac = politica(kf[i], hist)
            stake = min(frac, CAP_PICK) * cap
            g = stake * (cuota[i] - 1.0) if gano[i] else -stake
            cap += g
            hist.append(1.0 if gano[i] else 0.0)
            pico = max(pico, cap)
            peor = max(peor, 1.0 - cap / pico)
            if cap <= RUINA:
                ruinas[c] = True
                break
        finales[c] = cap
        caidas[c] = peor
    return finales, caidas, ruinas


def main():
    prob, cuota, gano = secuencia_picks()
    n = len(prob)
    if n < 200:
        print('muestra insuficiente')
        return

    rng = np.random.default_rng(2026)
    # bootstrap POR BLOQUES: conserva las rachas, que es lo que la politica
    # dinamica dice aprovechar. Con un bootstrap i.i.d. no habria rachas que
    # detectar y el experimento estaria amañado a favor del Kelly fijo.
    n_bloques = max(1, n // BLOQUE)
    caminos = []
    for _ in range(N_CAMINOS):
        inicios = rng.integers(0, max(1, n - BLOQUE), size=n_bloques)
        caminos.append(np.concatenate([np.arange(s, s + BLOQUE) for s in inicios]))

    politicas = {}
    for frac in (0.0625, 0.125, 0.25, 0.5, 1.0):
        politicas[f'fija {frac:.4g} Kelly'] = (
            lambda kf, hist, fr=frac: kf * fr)

    # DINAMICA: parte de 1/8 y se mueve entre 1/16 y 1/4 segun el acierto de
    # las ultimas 30 apuestas RESUELTAS (solo mira atras).
    def dinamica(kf, hist, base=0.125, lo=0.0625, hi=0.25, ventana=30):
        if len(hist) < ventana:
            return kf * base
        reciente = float(np.mean(hist[-ventana:]))
        # se escala linealmente entre lo y hi con el acierto reciente
        # (0,40 -> lo ; 0,60 -> hi), acotado
        t = (reciente - 0.40) / 0.20
        fr = lo + (hi - lo) * float(np.clip(t, 0.0, 1.0))
        return kf * fr
    politicas['DINAMICA (racha, 1/16-1/4)'] = dinamica

    # DINAMICA inversa: sube tras rachas MALAS (apuesta de reversion)
    def inversa(kf, hist, base=0.125, lo=0.0625, hi=0.25, ventana=30):
        if len(hist) < ventana:
            return kf * base
        reciente = float(np.mean(hist[-ventana:]))
        t = (0.60 - reciente) / 0.20
        fr = lo + (hi - lo) * float(np.clip(t, 0.0, 1.0))
        return kf * fr
    politicas['DINAMICA inversa'] = inversa

    print('\n' + '=' * 92)
    print(f"{'politica':28s} {'cap. mediano':>13} {'p5':>9} {'p95':>10} "
          f"{'caida med':>10} {'ruina':>8}")
    print('=' * 92)
    salida = {}
    for nombre, fn in politicas.items():
        fin, cai, rui = simular(prob, cuota, gano, fn, caminos, rng)
        r = {'mediana': float(np.median(fin)),
             'p5': float(np.percentile(fin, 5)),
             'p95': float(np.percentile(fin, 95)),
             'caida_mediana': float(np.median(cai)),
             'ruina': float(rui.mean())}
        salida[nombre] = r
        print(f"{nombre:28s} {r['mediana']:13.3f} {r['p5']:9.3f} "
              f"{r['p95']:10.3f} {r['caida_mediana']:10.1%} {r['ruina']:8.2%}")
    print('=' * 92)

    base = salida.get('fija 0.125 Kelly')
    din = salida.get('DINAMICA (racha, 1/16-1/4)')
    if base and din:
        print(f"\nDINAMICA frente a la ⅛ fija que hay hoy:")
        print(f"  capital mediano {din['mediana']/base['mediana']-1:+.2%}   "
              f"p5 {din['p5']/base['p5']-1:+.2%}   "
              f"ruina {din['ruina']-base['ruina']:+.2%}")
        mejor = (din['mediana'] > base['mediana'] and
                 din['p5'] >= base['p5'] and
                 din['ruina'] <= base['ruina'] + 1e-9)
        print(f"\nVEREDICTO: {'ADOPTAR la dinamica' if mejor else 'NO adoptar la dinamica'}")

    # ¿y cual es la mejor fija?
    fijas = {k: v for k, v in salida.items() if k.startswith('fija')}
    mejor_fija = max(fijas, key=lambda k: fijas[k]['mediana'])
    seguras = {k: v for k, v in fijas.items() if v['ruina'] <= 0.01}
    if seguras:
        mejor_segura = max(seguras, key=lambda k: seguras[k]['mediana'])
        print(f"\nMejor fija por capital mediano: {mejor_fija}")
        print(f"Mejor fija con ruina <= 1 %   : {mejor_segura}")

    json.dump(salida, open('_v81_kelly.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
