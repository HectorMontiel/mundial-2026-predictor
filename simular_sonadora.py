#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
¿Acierta la Soñadora? Se arman sus boletos sobre días ya jugados y se miran.

QUÉ HACE, Y EN QUÉ SE DIFERENCIA DE `validar_sonadora`
------------------------------------------------------
`validar_sonadora` muestrea patas al azar dentro de una banda de cuota: mide
qué rinde LA BANDA. Esto es otra cosa — reconstruye lo que la sección **habría
ofrecido de verdad** cada día, con sus reglas (una pata por partido, tope por
competición, el patrón de mercados del boleto ganador) y con la MISMA receta
de selección que usa la pantalla, y comprueba si ese boleto concreto habría
entrado.

O sea: no mide el mercado, mide **la herramienta**.

POR QUÉ SE PUEDE MEDIR SIN CUOTAS
---------------------------------
El acierto no las necesita. Hacen falta la probabilidad del modelo y el
resultado real, y las dos están en `pick_ledger_totales.csv` (47.794 partidos,
55 competiciones, walk-forward y sin fuga) y en `pick_ledger.csv`. El
rendimiento sí necesita precio y por eso se publica aparte y sólo donde lo hay
—«Más de 2,5» y el 1X2—: el resto lleva el acierto y no lleva ROI, dicho.

LA PREGUNTA QUE DECIDE SI LA HERRAMIENTA SIRVE
----------------------------------------------
No es «¿acierta mucho?» — un boleto de trece patas acierta poco por
construcción. Es **¿acierta lo que dice que va a acertar?**

    acierto REAL  contra  acierto TEÓRICO (el producto de las probabilidades)

Si el real queda por debajo del teórico, o el modelo va sobrado de confianza o
las patas están correlacionadas, y en los dos casos el boleto promete más de
lo que da. Ésa es la cifra que hay que mirar, y la que hay que mejorar.

Uso:
    python simular_sonadora.py                 # últimos 120 días
    python simular_sonadora.py --dias 365
    python simular_sonadora.py --informe       # no escribe el JSON
"""

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = 'modelos/simulacion_sonadora.json'
MAPA = 'modelos/calibracion_patas.json'

# Los tamaños de boleto que la pantalla ofrece.
TAMANOS = (4, 6, 8, 10, 13)

# El suelo de probabilidad de la sección.
PROB_MINIMA = 0.55

# Tope de patas de la misma competición, como en el motor.
MAX_POR_LIGA = 2

# Días mínimos con boleto armable para que un número signifique algo. Misma
# razón que `validar_sonadora.DIAS_MINIMOS`: la unidad independiente es la
# JORNADA, no el boleto.
DIAS_MINIMOS = 30


# ---------------------------------------------------------------------------
# El conjunto de patas, con la forma que tiene en la pantalla
# ---------------------------------------------------------------------------
def patas_historicas(desde: Optional[str] = None) -> pd.DataFrame:
    """Una fila por (partido, mercado) con probabilidad del modelo y acierto.

    Los mercados son los que la Soñadora ofrece de verdad y para los que el
    ledger guarda probabilidad Y resultado: la escalera de goles, «ambos
    marcan» y el 1X2. Córners, tarjetas y remates NO están —el ledger no
    guarda su resultado— y eso se dice en el informe en vez de disimularlo.
    """
    T = pd.read_csv('pick_ledger_totales.csv')
    filas = []
    for etiqueta, pcol, rcol, patron in (
            ('Más de 1.5', 'p_over_1.5', 'over_1.5_real', True),
            ('Más de 2.5', 'p_over_2.5', 'over_2.5_real', True),
            ('Más de 3.5', 'p_over_3.5', 'over_3.5_real', True),
            ('Ambos marcan: Sí', 'p_btts', 'btts_real', False)):
        if pcol not in T.columns or rcol not in T.columns:
            continue
        g = T[T[pcol].notna() & T[rcol].notna()]
        filas.append(pd.DataFrame({
            'fecha': g['fecha'].astype(str), 'liga': g['liga'].astype(str),
            'match_id': g['match_id'].astype(str),
            'mercado': 'Goles' if etiqueta.startswith('Más') else 'BTTS',
            'etiqueta': etiqueta,
            'prob': g[pcol].astype(float),
            'gana': g[rcol].astype(float).round().astype(int),
            'patron': patron,
            'cuota': (g['cuota_over25'].astype(float)
                      if etiqueta == 'Más de 2.5'
                      and 'cuota_over25' in g.columns else np.nan),
        }))

    try:
        D = pd.read_csv('pick_ledger.csv')
        for etiqueta, pcol, ccol, res in (
                ('Gana local', 'p_home', 'cuota_home', 0),
                ('Gana visitante', 'p_away', 'cuota_away', 2)):
            g = D[D[pcol].notna() & D['resultado'].notna()]
            filas.append(pd.DataFrame({
                'fecha': g['fecha'].astype(str), 'liga': g['liga'].astype(str),
                'match_id': g['match_id'].astype(str),
                'mercado': '1X2', 'etiqueta': etiqueta,
                'prob': g[pcol].astype(float),
                'gana': (g['resultado'].astype(int) == res).astype(int),
                'patron': True,
                'cuota': (g[ccol].astype(float) if ccol in g.columns
                          else np.nan),
            }))
    except Exception as e:
        logger.warning('[simular] sin ledger 1X2: %s', e)

    P = pd.concat(filas, ignore_index=True)
    if desde:
        P = P[P['fecha'] >= desde]
    return P.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Las recetas, que son las mismas que propone la pantalla
# ---------------------------------------------------------------------------
def _elegir(dia: pd.DataFrame, n: int, clave: str,
            por_liga: bool = False,
            max_liga: Optional[int] = MAX_POR_LIGA) -> Optional[pd.DataFrame]:
    """`n` patas sin repetir partido, como `sonadora_motor._elegir`."""
    d = dia.sort_values(clave, ascending=False)
    vistos, ligas, filas = set(), {}, []
    for fila in d.itertuples():
        if fila.match_id in vistos:
            continue
        if por_liga and fila.liga in ligas:
            continue
        if max_liga is not None and ligas.get(fila.liga, 0) >= max_liga:
            continue
        vistos.add(fila.match_id)
        ligas[fila.liga] = ligas.get(fila.liga, 0) + 1
        filas.append(fila)
        if len(filas) >= n:
            break
    if len(filas) < n:
        return None
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# LA CALIBRACION, QUE ES LO QUE ARREGLA EL BOLETO
# ---------------------------------------------------------------------------
#
# La primera pasada dejo el diagnostico sin lugar a dudas:
#
#     4 patas   promete 59,76 %   da 37,23 %   ratio 0,62
#     8 patas   promete 32,20 %   da 13,70 %   ratio 0,43
#    13 patas   promete 14,49 %   da  4,74 %   ratio 0,33
#
# El ratio cae con cada pata, que es la firma de una probabilidad
# SOBRECONFIADA multiplicandose por si misma. Y no es una sorpresa: en la v207
# se midio que el modelo dice 89 % en «Mas de 1,5» y cae el 80 %.
#
# La correccion es mapear la probabilidad cruda a la que se observa de verdad,
# por mercado y por tramo. Se ajusta sobre el PASADO y se aplica al FUTURO —el
# corte es por fecha— porque ajustar y aplicar sobre lo mismo siempre mejora.
#
# Y esto NO es solo cosmetica sobre el numero que se ensena: cambia QUE PATAS
# SE ELIGEN, porque la receta ordena por probabilidad y la calibracion mueve
# el orden. Las patas donde el modelo iba mas sobrado dejan de encabezar.
CAJAS = [0.0, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]


def calibrar(P: pd.DataFrame, corte: str) -> pd.DataFrame:
    """Anade `prob_cal`: la probabilidad cruda mapeada a la observada.

    El mapa se aprende SOLO con las filas anteriores a `corte`, por mercado y
    etiqueta. Una celda con menos de 200 observaciones no se corrige: con esa
    muestra el numero observado es ruido y corregir con ruido es peor que no
    corregir.
    """
    P = P.copy()
    P['caja'] = pd.cut(P['prob'], bins=CAJAS, labels=False)
    pasado = P[P['fecha'] < corte]
    mapa = (pasado.groupby(['etiqueta', 'caja'])['gana']
            .agg(['mean', 'size']).reset_index())
    mapa = mapa[mapa['size'] >= 200]
    # se recorre con `iterrows` y no con `itertuples`: éste último renombra la
    # columna 'mean' porque choca con el método del namedtuple, y el nombre
    # que le pone depende de la versión de pandas
    d = {(row['etiqueta'], row['caja']): float(row['mean'])
         for _, row in mapa.iterrows()}
    P['prob_cal'] = [
        d.get((e, c), p) for e, c, p in
        zip(P['etiqueta'], P['caja'], P['prob'])]
    return P


RECETAS = ('A_mas_probable', 'P_solo_patron',
           'A_calibrada', 'P_calibrada', 'D_calibrada',
           # las que buscan ACERTAR MAS, no solo prometer bien
           'M15_calibrada',      # solo «Mas de 1,5», que cae el 73 % de base
           'F70_calibrada',      # suelo de probabilidad calibrada al 70 %
           'F75_calibrada')      # y al 75 %


def _boleto(dia: pd.DataFrame, n: int, receta: str) -> Optional[pd.DataFrame]:
    calibrada = receta.endswith('_calibrada')
    clave = 'prob_cal' if calibrada else 'prob'
    d = dia
    if receta.startswith('P_'):
        d = dia[dia['patron']]
    elif receta.startswith('M15'):
        # SOLO «MAS DE 1,5». Es la linea con mejor tasa base del catalogo —cae
        # el 73,3 % de 47.794 partidos— y era la mitad del boleto ganador.
        d = dia[dia['etiqueta'] == 'Más de 1.5']
    elif receta.startswith('F70'):
        d = dia[dia['prob_cal'] >= 0.70]
    elif receta.startswith('F75'):
        d = dia[dia['prob_cal'] >= 0.75]
    if not len(d):
        return None
    if receta.startswith('D_'):
        return _elegir(d, n, clave, por_liga=True, max_liga=1)
    return _elegir(d, n, clave)


def simular(P: pd.DataFrame, tamanos=TAMANOS) -> Dict:
    """Arma un boleto por (jornada, receta, tamaño) y mira si entró."""
    P = P[P['prob'] >= PROB_MINIMA]
    if 'prob_cal' not in P.columns:
        P = P.assign(prob_cal=P['prob'])
    fuera: Dict = {}
    for receta in RECETAS:
        for n in tamanos:
            ganados = intentos = 0
            teoricos: List[float] = []
            reales: List[int] = []
            for dia, g in P.groupby('fecha'):
                b = _boleto(g, n, receta)
                if b is None:
                    continue
                intentos += 1
                col = ('prob_cal' if receta.endswith('_calibrada')
                       and 'prob_cal' in b.columns else 'prob')
                p = float(np.prod(b[col].values))
                ok = int(b['gana'].sum() == n)
                teoricos.append(p)
                reales.append(ok)
                ganados += ok
            if intentos < DIAS_MINIMOS:
                fuera[f'{receta}|{n}'] = {
                    'jornadas': intentos, 'veredicto': 'sin_muestra'}
                continue
            real = ganados / intentos
            teo = float(np.mean(teoricos))
            # intervalo de Wilson al 95 %, que es el honesto con proporciones
            # pequeñas: el normal da límites negativos y aquí el acierto de un
            # boleto de trece ronda el 1 %
            z = 1.96
            den = 1 + z * z / intentos
            centro = (real + z * z / (2 * intentos)) / den
            margen = (z * np.sqrt(real * (1 - real) / intentos
                                  + z * z / (4 * intentos ** 2))) / den
            fuera[f'{receta}|{n}'] = {
                'receta': receta, 'n_patas': n,
                'jornadas': intentos, 'ganados': ganados,
                'acierto_real': round(real, 5),
                'acierto_teorico': round(teo, 5),
                'ratio': round(real / teo, 3) if teo else None,
                'ic95': [round(max(centro - margen, 0.0), 5),
                         round(min(centro + margen, 1.0), 5)],
                'prob_media_pata': round(
                    float(np.mean([t ** (1.0 / n) for t in teoricos])), 4),
                'cumple': bool(teo and (centro + margen) >= teo),
            }
    return fuera


def _imprimir(doc: Dict) -> None:
    print('=' * 92)
    print('SIMULACIÓN DE LA SOÑADORA SOBRE JORNADAS YA JUGADAS')
    print('=' * 92)
    print(f"periodo {doc.get('periodo')} · {doc.get('n_patas')} patas "
          f"candidatas · {doc.get('n_jornadas')} jornadas")
    print()
    print(f"{'receta':17s} {'n':>3s} {'jorn':>5s} {'gana':>5s} "
          f"{'real':>8s} {'teórico':>8s} {'real/teo':>9s} "
          f"{'IC 95 %':>18s}  ¿cumple?")
    for clave, v in (doc.get('resultados') or {}).items():
        if v.get('veredicto') == 'sin_muestra':
            continue
        ic = v['ic95']
        print(f"{v['receta']:17s} {v['n_patas']:>3d} {v['jornadas']:>5d} "
              f"{v['ganados']:>5d} {v['acierto_real']*100:>7.2f}% "
              f"{v['acierto_teorico']*100:>7.2f}% {v['ratio']:>9.2f} "
              f"[{ic[0]*100:>6.2f}%,{ic[1]*100:>6.2f}%]  "
              f"{'sí' if v['cumple'] else 'NO'}")
    print()
    print(f"VEREDICTO: {doc.get('veredicto')}")
    for linea in (doc.get('notas') or []):
        print(f'   · {linea}')


def validar(dias: int = 120) -> Dict:
    hoy = _dt.date.today()
    desde = (hoy - _dt.timedelta(days=int(dias))).isoformat()
    P = patas_historicas()
    # el ledger termina cuando termina; se toma su ventana final y no la del
    # calendario, que estaría vacía
    fin = P['fecha'].max()
    corte = (pd.Timestamp(fin) - pd.Timedelta(days=int(dias))).date().isoformat()
    P = P[P['fecha'] >= corte]
    if not len(P):
        return {'medido': False, 'veredicto': 'sin_datos'}

    # el mapa se aprende con el primer 60 % de la ventana y se aplica al
    # resto; simular sobre el tramo de aprendizaje seria hacer trampa
    fechas = sorted(P['fecha'].unique())
    corte_cal = fechas[int(len(fechas) * 0.60)] if len(fechas) > 10 else fechas[0]
    P = calibrar(P, corte_cal)
    P = P[P['fecha'] >= corte_cal]
    res = simular(P)
    buenos = [v for v in res.values() if v.get('cumple')]
    malos = [v for v in res.values()
             if v.get('ratio') is not None and not v.get('cumple')]
    doc = {
        'medido': True,
        'fecha': hoy.isoformat(),
        'periodo': f'{corte} a {fin}',
        'corte_calibracion': str(corte_cal),
        'dias_pedidos': dias,
        'n_patas': int(len(P)),
        'n_jornadas': int(P['fecha'].nunique()),
        'prob_minima': PROB_MINIMA,
        'max_por_liga': MAX_POR_LIGA,
        'resultados': res,
        'notas': [
            'el acierto TEÓRICO es el producto de las probabilidades del '
            'modelo y supone independencia; los partidos de una misma '
            'jornada no lo son',
            'córners, tarjetas y remates NO entran: el ledger no guarda su '
            'resultado, así que su acierto no se puede comprobar',
            'el intervalo es de Wilson al 95 %, que es el que no da límites '
            'negativos con aciertos del 1 %',
        ],
    }
    doc['boletos_ganadores'] = boletos_ganadores(P)
    doc['cumplen'] = len(buenos)
    doc['no_cumplen'] = len(malos)
    doc['veredicto'] = ('la_herramienta_cumple' if len(buenos) > len(malos)
                        else 'promete_mas_de_lo_que_da')
    return doc


def boletos_ganadores(P: pd.DataFrame, receta: str = 'M15_calibrada',
                      tamanos=range(4, 14)) -> Dict:
    """Los boletos que HABRÍAN GANADO, con sus partidos.

    Contar aciertos no convence a nadie: hay que poder mirar el boleto. Esto
    devuelve, por tamaño, cuántos entraron y un ejemplo completo — el menos
    probable de los que entraron, que es el que mejor enseña hasta dónde llega
    la herramienta.
    """
    fuera: Dict = {}
    for n in tamanos:
        ganados, jornadas = [], 0
        for dia, g in P.groupby('fecha'):
            b = _boleto(g, int(n), receta)
            if b is None:
                continue
            jornadas += 1
            if int(b['gana'].sum()) == int(n):
                ganados.append((dia, b))
        if not jornadas:
            continue
        entrada = {'jornadas': jornadas, 'ganados': len(ganados),
                   'acierto': round(len(ganados) / jornadas, 5)}
        if ganados:
            col = ('prob_cal' if receta.endswith('_calibrada')
                   and 'prob_cal' in ganados[0][1].columns else 'prob')
            dia, b = min(ganados,
                         key=lambda x: float(np.prod(x[1][col].values)))
            entrada['ejemplo'] = {
                'fecha': str(dia),
                'probabilidad': round(float(np.prod(b[col].values)), 5),
                'patas': [{'liga': r.liga, 'mercado': r.etiqueta,
                           'prob': round(float(getattr(r, col)), 3)}
                          for r in b.itertuples()],
            }
        fuera[str(n)] = entrada
    return fuera


def escribir_mapa(ruta: str = MAPA, dias: int = 540) -> Dict:
    """El mapa de calibración que la pantalla aplica en vivo.

    Se aprende con TODO el histórico disponible —aquí no hay que reservar
    tramo de prueba: la prueba ya se hizo en `validar`, con corte por fecha, y
    dio ratio 1,14 a ocho patas—. Lo que se guarda es el mapa final, con la
    muestra de cada celda al lado para que se pueda juzgar.
    """
    P = patas_historicas()
    P = P[P['prob'] >= PROB_MINIMA]
    P['caja'] = pd.cut(P['prob'], bins=CAJAS, labels=False)
    mapa = (P.groupby(['etiqueta', 'caja'])['gana']
            .agg(['mean', 'size']).reset_index())
    mapa = mapa[mapa['size'] >= 200]
    doc = {'fecha': _dt.date.today().isoformat(),
           'cajas': CAJAS, 'n_minimo_celda': 200,
           'periodo': f"{P['fecha'].min()} a {P['fecha'].max()}",
           'etiquetas': {}}
    for _, row in mapa.iterrows():
        doc['etiquetas'].setdefault(str(row['etiqueta']), {})[
            str(int(row['caja']))] = {
                'observado': round(float(row['mean']), 4),
                'n': int(row['size'])}
    os.makedirs(os.path.dirname(ruta) or '.', exist_ok=True)
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dias', type=int, default=120)
    ap.add_argument('--informe', action='store_true')
    ap.add_argument('--mapa', action='store_true',
                    help='escribe el mapa de calibración y sale')
    args = ap.parse_args()
    if args.mapa:
        m = escribir_mapa()
        print(f"Escrito {MAPA}: "
              f"{len(m['etiquetas'])} mercados, "
              f"{sum(len(v) for v in m['etiquetas'].values())} celdas")
        return 0
    doc = validar(args.dias)
    try:
        _imprimir(doc)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            json.dumps(doc, ensure_ascii=False, indent=1).encode('utf-8'))
    if not args.informe:
        os.makedirs('modelos', exist_ok=True)
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f'\nEscrito {SALIDA}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
