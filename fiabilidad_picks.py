#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v217 — Cuándo fiarse de un verde: qué acierta DE VERDAD cada probabilidad.

LA PREGUNTA QUE CONTESTA, CON LAS PALABRAS DEL USUARIO
------------------------------------------------------
«Entiendo que sale rojo porque no se atinó la predicción, pero quiero entender
POR QUÉ no se atinó y cómo saber cuál partido meterle y cuál no. Que me digas:
éstas son verdes y es muy probable que se cumplan, o éstas son mis predicciones
pero no es tan probable.»

LA RESPUESTA CORTA, ANTES DE LOS NÚMEROS
----------------------------------------
Un pick al 60 % **tiene que fallar cuatro de cada diez veces**. Que uno salga
rojo no es un fallo del modelo: es lo que significa 60 %. El problema empieza
cuando el 60 % del modelo no es un 60 % de verdad — y eso sí está medido, y es
lo que este módulo mide sobre los picks REALES que la aplicación publicó.

    Si la app dice 60 % y acierta 60 %, el verde es de fiar.
    Si la app dice 60 % y acierta 47 %, el verde miente y hay que saberlo.

Sobre 107.280 picks del ledger, `patrones_acierto` ya midió que el modelo se
desordena cuanto más larga es la cuota: en la banda 1,80-2,20 promete 53,8 % y
acierta 47,9 %. Esto es lo mismo, pero sobre **lo que el usuario vio en
pantalla**: los puntos verdes y rojos de «Apuestas del Día».

QUÉ HACE, EXACTAMENTE
---------------------
1. Lee `pronosticos_emitidos.json` — lo que la app recomendó, con su
   probabilidad, ANTES de que se jugara el partido. Es un registro de
   sólo-inserción, así que no puede haberse retocado a posteriori.
2. Busca el marcador real en el histórico de esa competición.
3. Juzga cada recomendación con la MISMA función que pinta el punto
   (`pronosticos_guardados._acierto`), para que el análisis y la pantalla no
   puedan decir cosas distintas.
4. Agrega por banda de probabilidad, por mercado y por competición.

POR QUÉ NO BASTA CON «LLEVA MUCHOS VERDES»
------------------------------------------
Con pocas muestras, cualquier banda parece buena o mala por azar. Cada cifra
sale con su INTERVALO DE WILSON al 90 %, que es el que aguanta muestras
pequeñas y proporciones cerca de 0 o 1. Una banda cuyo intervalo cruza su
propia promesa es una banda de la que todavía no se puede decir nada.

Uso:
    python fiabilidad_picks.py              # informe completo
    python fiabilidad_picks.py --md         # y escribe FIABILIDAD_PICKS.md
"""

import argparse
import collections
import datetime as _dt
import json
import logging
import math
import os
import sys
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('fiabilidad')

SALIDA_JSON = 'fiabilidad_picks.json'
SALIDA_MD = 'FIABILIDAD_PICKS.md'

# Bandas de la probabilidad que la app ENSEÑA. Son las que el usuario lee.
BANDAS = ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01))

N_MINIMO = 30          # por debajo de esto no se publica veredicto
Z_90 = 1.6449          # intervalo de Wilson al 90 %

# Cuánto puede quedarse corta una banda antes de llamarla optimista. No es
# una constante medida: es el listón de honestidad que se quiere en pantalla.
MARGEN_TOLERADO = 0.05


# ---------------------------------------------------------------------------
def wilson(exitos: int, n: int, z: float = Z_90) -> Tuple[float, float]:
    """Intervalo de Wilson: el que no miente con muestras pequeñas.

    El intervalo normal (p ± z·√(p(1−p)/n)) se sale de [0,1] y da anchuras
    absurdas con n chico o p cerca de los extremos, que es exactamente el caso
    de «esta liga lleva 12 picks y todos verdes».
    """
    if n <= 0:
        return (0.0, 1.0)
    p = exitos / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    radio = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centro - radio), min(1.0, centro + radio))


def nombre_banda(p: Optional[float]) -> Optional[str]:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if v > 1.0:
        v = v / 100.0
    for lo, hi in BANDAS:
        if lo <= v < hi:
            return f'{lo:.0%}-{min(hi, 1.0):.0%}'
    return None


# ---------------------------------------------------------------------------
def _marcadores() -> Dict[Tuple[str, str, str], Tuple[float, float]]:
    """Índice (liga, local, visitante) -> (goles_local, goles_visitante).

    Sale de los `historico_*.csv`, que es donde el bot deja los resultados. Se
    normalizan los nombres con `name_mapper` porque el registro guarda el
    nombre que enseñó la aplicación y el histórico usa el suyo.
    """
    import glob
    import pandas as pd
    fuera = {}
    for ruta in glob.glob('historico_*.csv'):
        clave = os.path.basename(ruta)[len('historico_'):-4]
        try:
            d = pd.read_csv(ruta, usecols=lambda c: c in (
                'date', 'home_team', 'away_team', 'home_goals', 'away_goals'))
        except Exception as e:
            logger.debug('[fiabilidad] %s: %s', ruta, e)
            continue
        if not {'home_team', 'away_team', 'home_goals'} <= set(d.columns):
            continue
        d = d[d.home_goals.notna() & d.away_goals.notna()]
        for h, a, gh, ga in zip(d.home_team, d.away_team,
                                d.home_goals, d.away_goals):
            fuera[(clave, _norm(h), _norm(a))] = (float(gh), float(ga))
    return fuera


def _norm(s) -> str:
    try:
        import name_mapper as nm
        return nm.normalizar(str(s))
    except Exception:
        return str(s).strip().lower()


def juzgar() -> List[Dict]:
    """Cada recomendación publicada, con su veredicto real.

    Sólo entran las que se pueden juzgar CON EL MARCADOR: resultado, goles y
    ambos-marcan. Córners, tarjetas y remates necesitan estadísticas que no
    están en todos los históricos, y meterlas a medias sesgaría el recuento
    hacia las competiciones que sí las publican.
    """
    import pronosticos_guardados as pg

    doc = pg._leer()
    marcadores = _marcadores()
    logger.info('registros publicados: %d · marcadores en histórico: %d',
                len(doc), len(marcadores))

    filas = []
    sin_resultado = 0
    for k, reg in doc.items():
        liga = str(reg.get('clave_liga') or '')
        h, a = reg.get('home'), reg.get('away')
        if not (liga and h and a):
            continue
        res = marcadores.get((liga, _norm(h), _norm(a)))
        if res is None:
            sin_resultado += 1
            continue
        gh, ga = res
        for rec in (reg.get('recomendadas') or []):
            prob = rec.get('prob')
            banda = nombre_banda(prob)
            if banda is None:
                continue
            try:
                real = pg._valor_real(rec, gh, ga, None)
                acierto, dist = pg._acierto(rec, real, h, a)
            except Exception as e:
                logger.debug('[fiabilidad] %s: %s', rec.get('apuesta'), e)
                continue
            if acierto is None:
                continue          # mercado que no se puede juzgar sin stats
            p = float(prob)
            filas.append({
                'liga': reg.get('liga') or liga, 'clave_liga': liga,
                'partido': reg.get('partido'), 'fecha': reg.get('fecha'),
                'apuesta': rec.get('apuesta'),
                'mercado': str(rec.get('mercado') or '?'),
                'prob': p if p <= 1.0 else p / 100.0,
                'cuota': rec.get('cuota'),
                'banda': banda,
                'acierto': int(bool(acierto)),
                'distancia': dist,
            })
    logger.info('juzgadas: %d · sin resultado en histórico: %d',
                len(filas), sin_resultado)
    return filas


# ---------------------------------------------------------------------------
def agregar(filas: List[Dict], por: str) -> List[Dict]:
    """Acierto real por grupo, con su intervalo y su veredicto."""
    grupos = collections.defaultdict(list)
    for f in filas:
        grupos[f[por]].append(f)

    fuera = []
    for llave, g in grupos.items():
        n = len(g)
        exitos = sum(x['acierto'] for x in g)
        prometido = sum(x['prob'] for x in g) / n
        real = exitos / n
        lo, hi = wilson(exitos, n)
        fuera.append({
            'grupo': str(llave), 'n': n, 'aciertos': exitos,
            'prometido': prometido, 'real': real,
            'brecha': real - prometido,
            'ic90': [lo, hi],
            'veredicto': _veredicto(n, prometido, real, lo, hi),
        })
    return sorted(fuera, key=lambda x: -x['n'])


def _veredicto(n: int, prometido: float, real: float,
               lo: float, hi: float) -> str:
    """`de_fiar` · `optimista` · `conservador` · `sin_medir`.

    La clave es el INTERVALO, no el punto: si el intervalo contiene lo
    prometido, la diferencia observada cabe dentro del azar y no se puede
    afirmar nada. Con 12 picks y 8 aciertos, el intervalo va de 0,42 a 0,86:
    eso no distingue un modelo bueno de uno malo.
    """
    if n < N_MINIMO:
        return 'sin_medir'
    if lo <= prometido <= hi:
        return 'de_fiar'
    if real < prometido - MARGEN_TOLERADO:
        return 'optimista'
    if real > prometido + MARGEN_TOLERADO:
        return 'conservador'
    return 'de_fiar'


# ---------------------------------------------------------------------------
_TABLA: Optional[Dict] = None


def cargar(recargar: bool = False) -> Dict:
    global _TABLA
    if _TABLA is not None and not recargar:
        return _TABLA
    _TABLA = {}
    try:
        if os.path.exists(SALIDA_JSON):
            with open(SALIDA_JSON, encoding='utf-8') as f:
                _TABLA = json.load(f) or {}
    except Exception as e:
        logger.debug('[fiabilidad] no se pudo leer: %s', e)
    return _TABLA


def fiabilidad(prob: Optional[float], mercado: str = '') -> Dict:
    """Lo que ese porcentaje ha valido DE VERDAD hasta ahora.

    Es lo que la tarjeta puede enseñar al lado del verde para que el usuario
    sepa si fiarse. Sin medición devuelve `sin_medir` — que también es una
    respuesta, y mejor que un número inventado.
    """
    vacio = {'veredicto': 'sin_medir', 'n': 0, 'real': None,
             'prometido': prob, 'texto': 'sin histórico suficiente todavía'}
    b = nombre_banda(prob)
    if not b:
        return vacio
    doc = cargar()
    entrada = None
    for fila in (doc.get('por_mercado_banda') or []):
        if fila['grupo'] == f'{mercado}|{b}':
            entrada = fila
            break
    if entrada is None:
        for fila in (doc.get('por_banda') or []):
            if fila['grupo'] == b:
                entrada = fila
                break
    if entrada is None or entrada.get('veredicto') == 'sin_medir':
        return vacio
    return {
        'veredicto': entrada['veredicto'],
        'n': entrada['n'],
        'real': entrada['real'],
        'prometido': entrada['prometido'],
        'texto': _texto(entrada),
    }


def _texto(e: Dict) -> str:
    v = e['veredicto']
    if v == 'de_fiar':
        return (f"histórico: dijo {e['prometido']:.0%} y acertó "
                f"{e['real']:.0%} en {e['n']} picks — el número se sostiene")
    if v == 'optimista':
        return (f"⚠️ histórico: dijo {e['prometido']:.0%} y sólo acertó "
                f"{e['real']:.0%} en {e['n']} picks — este porcentaje va "
                f"sobrado")
    if v == 'conservador':
        return (f"histórico: dijo {e['prometido']:.0%} y acertó "
                f"{e['real']:.0%} en {e['n']} picks — se queda corto")
    return 'sin histórico suficiente todavía'


# ---------------------------------------------------------------------------
def construir() -> Dict:
    filas = juzgar()
    if not filas:
        return {'generado': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                'n': 0, 'por_banda': [], 'por_mercado': [],
                'por_liga': [], 'por_mercado_banda': []}

    for f in filas:
        f['mercado_banda'] = f"{f['mercado']}|{f['banda']}"

    doc = {
        'generado': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'n': len(filas),
        'aciertos': sum(f['acierto'] for f in filas),
        'desde': min(str(f.get('fecha') or '') for f in filas),
        'hasta': max(str(f.get('fecha') or '') for f in filas),
        'por_banda': agregar(filas, 'banda'),
        'por_mercado': agregar(filas, 'mercado'),
        'por_liga': agregar(filas, 'liga'),
        'por_mercado_banda': agregar(filas, 'mercado_banda'),
    }
    with open(SALIDA_JSON, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    global _TABLA
    _TABLA = doc
    return doc


def _tabla(filas: List[Dict], titulo: str) -> List[str]:
    L = [f'## {titulo}\n',
         '| grupo | n | dijo | acertó | brecha | IC 90 % | veredicto |',
         '|---|---|---|---|---|---|---|']
    for e in filas:
        if e['n'] < 10:
            continue
        L.append(f"| {e['grupo']} | {e['n']} | {e['prometido']:.1%} | "
                 f"{e['real']:.1%} | {e['brecha']:+.1%} | "
                 f"{e['ic90'][0]:.0%}-{e['ic90'][1]:.0%} | {e['veredicto']} |")
    L.append('')
    return L


def escribir_md(doc: Dict, ruta: str = SALIDA_MD) -> None:
    L = ['# Fiabilidad de los picks publicados\n',
         f"Generado por `fiabilidad_picks.py` el {doc['generado']}.\n",
         f"**{doc['n']} recomendaciones publicadas y resueltas** entre "
         f"{doc.get('desde')} y {doc.get('hasta')}, con "
         f"{doc.get('aciertos')} aciertos "
         f"({doc.get('aciertos', 0) / max(doc['n'], 1):.1%}).\n",
         '## Cómo leer esto\n',
         'Un pick al 60 % **tiene que fallar cuatro de cada diez veces**. Que '
         'uno salga rojo no dice nada por sí solo. Lo que importa es si la '
         'banda entera cumple lo que promete:\n',
         '- **de_fiar** — lo prometido cae dentro del intervalo: el número se '
         'sostiene.\n'
         '- **optimista** — acierta bastante menos de lo que dice. Ese verde '
         'vale menos de lo que parece.\n'
         '- **conservador** — acierta más de lo que dice.\n'
         '- **sin_medir** — menos de '
         f'{N_MINIMO} picks. No se puede afirmar nada, y decirlo es la '
         'respuesta honesta.\n',
         'El intervalo es de **Wilson al 90 %**, que es el que aguanta '
         'muestras pequeñas: con 12 picks y 8 aciertos va de 0,42 a 0,86, y '
         'eso no distingue un modelo bueno de uno malo.\n']
    L += _tabla(doc['por_banda'], 'Por banda de probabilidad — la tabla clave')
    L += _tabla(doc['por_mercado'], 'Por mercado')
    L += _tabla(doc['por_liga'][:25], 'Por competición')
    L += _tabla([e for e in doc['por_mercado_banda'] if e['n'] >= N_MINIMO][:30],
                'Por mercado y banda')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--md', action='store_true')
    a = ap.parse_args()

    doc = construir()
    if not doc['n']:
        print('no hay picks publicados que se puedan resolver todavía')
        return 0

    print(f"\n{doc['n']} recomendaciones resueltas · "
          f"{doc['aciertos']} aciertos "
          f"({doc['aciertos'] / doc['n']:.1%})")
    print('\n=== POR BANDA DE PROBABILIDAD (la tabla que contesta la pregunta) ===')
    print('%-10s %6s %8s %8s %9s   %s' % ('banda', 'n', 'dijo', 'acerto',
                                          'brecha', 'veredicto'))
    for e in sorted(doc['por_banda'], key=lambda x: x['grupo']):
        print('%-10s %6d %7.1f%% %7.1f%% %+8.1f%%   %s' % (
            e['grupo'], e['n'], e['prometido'] * 100, e['real'] * 100,
            e['brecha'] * 100, e['veredicto']))

    print('\n=== POR MERCADO ===')
    for e in doc['por_mercado'][:10]:
        if e['n'] < 10:
            continue
        print('%-26s n=%-5d dijo %5.1f%% acerto %5.1f%%  %s' % (
            e['grupo'][:26], e['n'], e['prometido'] * 100, e['real'] * 100,
            e['veredicto']))

    if a.md:
        escribir_md(doc)
        print(f'\n-> {SALIDA_MD}')
    print(f'-> {SALIDA_JSON}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
