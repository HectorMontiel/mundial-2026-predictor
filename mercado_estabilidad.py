#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v168 — EL MERCADO REY DE CADA COMPETICIÓN.

Qué pregunta contesta
---------------------
No todas las competiciones se predicen igual, y no todos los mercados de una
competición valen lo mismo. En una liga puede que lo único fiable sea el 1X2 y
en otra las tarjetas. Hasta ahora la aplicación recomendaba SIEMPRE del mismo
sitio —el máximo de la matriz de marcador— sin mirar si ese mercado era el más
estable de esa liga o el peor.

Este módulo mide **todos los mercados medibles de las 62 competiciones** y los
ordena por fiabilidad. El primero de cada liga es su **Mercado Rey**.

CON QUÉ SE MIDE, Y POR QUÉ CON ESO
----------------------------------
Con el **ECE** —error de calibración por deciles— sobre el resultado REAL. Es
la métrica con la que este proyecto decide desde la v163, y por un motivo que
ya costó caro: el error marginal |media(p) − frecuencia| se deja engañar por
dos sesgos que se cancelan (§2b del traspaso), y en remates habría elegido el
PEOR estimador. Además el ECE es comparable entre un mercado binario (1X2) y
uno de conteo (córners), que es imprescindible para ordenarlos juntos — una
razón varianza/media no se puede comparar con la de un mercado de dos vías.

La razón varianza/media SÍ se usa, pero para lo que sirve: la **cuarentena** de
los mercados de conteo, donde sí es interpretable.

DE DÓNDE SALEN LOS NÚMEROS — TODO YA ESTABA EN EL REPO
-------------------------------------------------------
    1X2, doble oportunidad ....  pick_ledger.csv          47.948 · 56 ligas
    goles 1,5/2,5/3,5 y BTTS ..  pick_ledger_totales.csv  47.794 · 55 ligas
    hándicap asiático .........  pick_ledger_handicap.csv 47.794 · 55 ligas
    córners/tarjetas/remates ..  _v162_calibracion_por_liga.json    61 ligas

Los tres ledgers son WALK-FORWARD (columna `pliegue`): la probabilidad es la
que el modelo dio sin haber visto ese partido. Sin eso, todo lo de aquí sería
una medición de memoria.

LO QUE NO SE PUEDE MEDIR NO SE INVENTA
---------------------------------------
Del catálogo pedido, tres familias no tienen con qué medirse hoy y salen con
`origen: 'sin medir'`, fuera del ranking:

  · **goles por equipo** — ningún ledger guarda la probabilidad del modelo por
    bando, sólo el total y el BTTS;
  · **resultado exacto** — el propio encargo lo marca de baja prioridad por su
    varianza, y no hay columna que lo recoja;
  · **remates de jugador** — `calibracion_remates_jugador.json` mide ECE 0,029
    y 0,024, pero AGREGADO sobre todas las competiciones, no por liga. Un
    número global no puede coronar a una liga concreta.

Decir «no medido» de esas tres es más útil que colarlas con un número prestado:
el Mercado Rey existe justo para no recomendar a ciegas.

    python mercado_estabilidad.py           # construye el fichero
    python mercado_estabilidad.py --ver premier
"""
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('mercado_estabilidad')

FICHERO = 'mercado_estable_por_liga.json'
INFORME_FISICO = '_v162_calibracion_por_liga.json'

# Los dos umbrales del proyecto, importados en espíritu de `confianza_mercado`:
# el 0,02 separa lo bien calibrado de lo que sólo está calibrado, y el 0,05 es
# el que la v162 fijó como «aceptable». No se inventan nuevos.
ECE_ESTABLE = 0.02
ECE_MODERADO = 0.05
# Cuarentena pedida: un mercado de CONTEO cuya varianza dobla a su media es
# demasiado ruidoso para recomendarlo. Sólo aplica a conteos — en un mercado
# binario la razón varianza/media no significa lo mismo.
DISPERSION_MAX = 2.0
MIN_N = 200          # por debajo de esto un ECE es ruido, no una medición

ESTABLE, MODERADO, INESTABLE, SIN_MEDIR = 'estable', 'moderado', 'inestable', 'sin medir'
SEMAFORO = {ESTABLE: '🟢', MODERADO: '🟡', INESTABLE: '🔴', SIN_MEDIR: '⚪'}

# Nombre visible de cada familia -> el bloque de la tarjeta al que pertenece.
# La tarjeta pinta un semáforo por BLOQUE, no por línea, así que varias
# familias comparten destino.
BLOQUE = {
    '1X2': 'resultado', 'Doble oportunidad': 'resultado',
    'Hándicap': 'handicap',
    'Goles 1.5': 'goles', 'Goles 2.5': 'goles', 'Goles 3.5': 'goles',
    'BTTS': 'btts',
    'Córners': 'corners', 'Córners por equipo': 'corners',
    'Tarjetas': 'tarjetas', 'Tarjetas por equipo': 'tarjetas',
    'Remates': 'remates', 'Remates por equipo': 'remates',
    'Remates a puerta': 'remates_on',
    'Goles por equipo': 'goles', 'Resultado exacto': 'resultado',
    'Remates de jugador': 'jugador',
}

_CACHE: Optional[Dict] = None


# ---------------------------------------------------------------------------
# la métrica
# ---------------------------------------------------------------------------
def ece(p, y, n_bins: int = 10) -> Optional[float]:
    """
    Error de calibración por deciles. `None` si no hay muestra para medirlo.

    Se reparte por CUANTILES y no por cortes fijos: con cortes fijos, un
    mercado cuyas probabilidades viven todas entre 0,45 y 0,60 dejaría ocho
    cajones vacíos y el número saldría de dos.
    """
    import numpy as np
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if len(p) < MIN_N:
        return None
    bordes = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    bordes[0], bordes[-1] = -1e-9, 1 + 1e-9
    total = 0.0
    for i in range(n_bins):
        m = (p >= bordes[i]) & (p < bordes[i + 1])
        if m.sum() == 0:
            continue
        total += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(total / len(p))


def _clasifica(e: Optional[float], disp: Optional[float] = None) -> str:
    """El semáforo de un mercado: ECE manda, la dispersión pone cuarentena."""
    # La cuarentena por varianza va PRIMERO, y también sin ECE. Un mercado
    # cuya varianza dobla a su media es demasiado ruidoso para recomendarlo, y
    # eso se sabe aunque no haya muestra para calibrarlo: son dos preguntas
    # distintas. Etiquetarlo «sin medir» diría que no sabemos nada de él cuando
    # sí sabemos lo peor. Medido: le pasa a «Remates por equipo» en 6
    # competiciones con muestra corta.
    if disp is not None and disp > DISPERSION_MAX:
        return INESTABLE
    if e is None:
        return SIN_MEDIR
    if e < ECE_ESTABLE:
        return ESTABLE
    if e <= ECE_MODERADO:
        return MODERADO
    return INESTABLE


def _fila(nombre: str, e: Optional[float], n: int,
          disp: Optional[float] = None, media: Optional[float] = None,
          origen: str = 'medido', e_ajustada: Optional[float] = None,
          n_ajustada: int = 0) -> Dict:
    """
    Una fila del ranking. Con DOS calibraciones, y la diferencia importa.

    `ece` es la del modelo crudo. `ece_ajustada` es la de la probabilidad que
    la aplicación ENSEÑA de verdad: encogida hacia el precio de la casa, como
    hace `cordura_probabilidad` desde la v166.

    La distinción no es académica. Medido sobre los mismos partidos, los goles
    pasan de un ECE de 0,09-0,13 en crudo a menos de 0,02 encogidos. Clasificar
    por el crudo pondría en cuarentena el mercado que en pantalla calibra bien;
    clasificar sólo por el ajustado mentiría en los partidos que la casa no
    cotiza, donde no hay hacia dónde encoger y lo que se ve es el crudo.

    Así que se guardan las dos y manda la ajustada cuando existe — que es
    exactamente la regla de «qué está viendo el usuario».
    """
    efectiva = e_ajustada if e_ajustada is not None else e
    return {'mercado': nombre, 'bloque': BLOQUE.get(nombre, 'otros'),
            'ece': None if e is None else round(e, 5),
            'ece_ajustada': (None if e_ajustada is None
                             else round(e_ajustada, 5)),
            'ece_efectiva': None if efectiva is None else round(efectiva, 5),
            'n': int(n), 'n_ajustada': int(n_ajustada),
            'dispersion': None if disp is None else round(float(disp), 4),
            'media': None if media is None else round(float(media), 3),
            'estado': _clasifica(efectiva, disp), 'origen': origen}


def _encoge(p, p_mkt, w: float = 0.25):
    """La misma mezcla que aplica `cordura_probabilidad` en producción."""
    return w * p + (1.0 - w) * p_mkt


def _devig_dos(c1, c2):
    return (1.0 / c1) / ((1.0 / c1) + (1.0 / c2))


# ---------------------------------------------------------------------------
# las cuatro fuentes
# ---------------------------------------------------------------------------
def _de_1x2() -> Dict[str, List[Dict]]:
    """1X2 y doble oportunidad, del ledger walk-forward."""
    import numpy as np
    import pandas as pd
    salida: Dict[str, List[Dict]] = {}
    if not os.path.exists('pick_ledger.csv'):
        return salida
    d = pd.read_csv('pick_ledger.csv')
    for liga, g in d.groupby('liga'):
        p = g[['p_home', 'p_draw', 'p_away']].values.astype(float)
        res = g['resultado'].astype(int).values
        filas = []
        # 1X2: el lado que el modelo elige, que es el que la tarjeta enseñaría
        lado = p.argmax(axis=1)
        idx = np.arange(len(g))
        # Y su versión ENCOGIDA hacia el mercado, que es la que producción
        # publica desde la v71 — el ledger guarda la cruda, así que sin esto el
        # 1X2 saldría peor clasificado de lo que de verdad se enseña.
        e_aj, n_aj = None, 0
        cols = ['cuota_home', 'cuota_draw', 'cuota_away']
        if all(c in g for c in cols):
            con = g[cols].notna().all(axis=1) & (g[cols] > 1).all(axis=1)
            if int(con.sum()) >= MIN_N:
                cu = g.loc[con, cols].values.astype(float)
                inv = 1.0 / cu
                mkt = inv / inv.sum(axis=1, keepdims=True)
                pa = _encoge(p[con.values], mkt)
                la = pa.argmax(axis=1)
                ia = np.arange(len(pa))
                e_aj = ece(pa[ia, la],
                           (res[con.values] == la).astype(int))
                n_aj = int(con.sum())
        filas.append(_fila('1X2', ece(p[idx, lado], (res == lado).astype(int)),
                           len(g), e_ajustada=e_aj, n_ajustada=n_aj))
        # doble oportunidad: las tres combinaciones, y se queda la mejor —
        # es UN mercado con tres selecciones, igual que el 1X2
        mejor, n_mejor = None, 0
        for a, b, nom in ((0, 1, '1X'), (0, 2, '12'), (1, 2, 'X2')):
            pd_ = p[:, a] + p[:, b]
            yd = ((res == a) | (res == b)).astype(int)
            e = ece(pd_, yd)
            if e is not None and (mejor is None or e < mejor):
                mejor, n_mejor = e, len(g)
        filas.append(_fila('Doble oportunidad', mejor, n_mejor))
        salida[str(liga)] = filas
    return salida


def _de_totales() -> Dict[str, List[Dict]]:
    """Goles 1,5/2,5/3,5 y BTTS."""
    import pandas as pd
    salida: Dict[str, List[Dict]] = {}
    if not os.path.exists('pick_ledger_totales.csv'):
        return salida
    d = pd.read_csv('pick_ledger_totales.csv')
    for liga, g in d.groupby('liga'):
        filas = []
        for linea in ('1.5', '2.5', '3.5'):
            col, real = 'p_over_%s' % linea, 'over_%s_real' % linea
            if col not in g or real not in g:
                continue
            sub = g[[col, real]].dropna()
            e_aj, n_aj = None, 0
            # Sólo la línea de 2,5 trae cuota en el ledger; es también la única
            # que la tarjeta encoge hoy con seguridad, así que cuadra.
            if linea == '2.5' and 'cuota_over25' in g:
                con = g[[col, real, 'cuota_over25', 'cuota_under25']].dropna()
                con = con[(con['cuota_over25'] > 1) & (con['cuota_under25'] > 1)]
                if len(con) >= MIN_N:
                    mkt = _devig_dos(con['cuota_over25'].values,
                                     con['cuota_under25'].values)
                    e_aj = ece(_encoge(con[col].values, mkt),
                               con[real].values)
                    n_aj = len(con)
            filas.append(_fila('Goles %s' % linea,
                               ece(sub[col].values, sub[real].values),
                               len(sub), e_ajustada=e_aj, n_ajustada=n_aj))
        if 'p_btts' in g and 'btts_real' in g:
            sub = g[['p_btts', 'btts_real']].dropna()
            # BTTS no tiene cuota en ningún ledger: su ajustada no se puede
            # medir y no se hereda de goles. Se queda con la cruda, dicho.
            filas.append(_fila('BTTS', ece(sub['p_btts'].values,
                                           sub['btts_real'].values), len(sub)))
        # goles por equipo: pedido, pero ningún ledger guarda la probabilidad
        # del modelo por bando. No se inventa.
        filas.append(_fila('Goles por equipo', None, 0, origen='sin medir'))
        filas.append(_fila('Resultado exacto', None, 0, origen='sin medir'))
        salida[str(liga)] = filas
    return salida


def _de_handicap() -> Dict[str, List[Dict]]:
    """
    Hándicap asiático: se mide cada línea y se resume en la MEJOR.

    Se resume porque en la tarjeta el hándicap es un bloque, no diecinueve; y
    se toma la mejor y no la media porque lo que se pregunta es «¿hay aquí una
    línea fiable?», no «¿lo son todas?».
    """
    import pandas as pd
    salida: Dict[str, List[Dict]] = {}
    if not os.path.exists('pick_ledger_handicap.csv'):
        return salida
    d = pd.read_csv('pick_ledger_handicap.csv')
    lineas = [c for c in d.columns if c.startswith('p_ah_')]
    # las cuatro que pidió el encargo, si están
    preferidas = [c for c in lineas
                  if c.endswith(('-1p50', '-0p50', '+0p50', '+1p50'))]
    usar = preferidas or lineas
    for liga, g in d.groupby('liga'):
        mejor, n_mejor = None, 0
        for col in usar:
            real = col.replace('p_ah_', 'ah_') + '_real'
            if real not in g:
                continue
            sub = g[[col, real]].dropna()
            e = ece(sub[col].values, sub[real].values)
            if e is not None and (mejor is None or e < mejor):
                mejor, n_mejor = e, len(sub)
        salida[str(liga)] = [_fila('Hándicap', mejor, n_mejor)]
    return salida


def _de_fisicos() -> Dict[str, List[Dict]]:
    """
    Córners, tarjetas y remates — ya medidos por `informe_calibracion.py`.

    No se vuelven a medir aquí: se leen de donde ya están. Dos mediciones del
    mismo número acaban divergiendo, y entonces la insignia del bloque y el
    ranking del Mercado Rey dirían cosas distintas de lo mismo.
    """
    salida: Dict[str, List[Dict]] = {}
    if not os.path.exists(INFORME_FISICO):
        return salida
    try:
        with open(INFORME_FISICO, encoding='utf-8') as f:
            doc = json.load(f) or {}
    except Exception as e:
        logger.warning('[estabilidad] no se pudo leer %s: %s', INFORME_FISICO, e)
        return salida
    nombres = {'corners': ('Córners', 'Córners por equipo'),
               'tarjetas': ('Tarjetas', 'Tarjetas por equipo'),
               'remates': ('Remates', 'Remates por equipo'),
               'remates_on': ('Remates a puerta', None)}
    for lg in (doc.get('ligas') or []):
        clave = str(lg.get('clave') or '')
        if not clave:
            continue
        filas = []
        for campo, (n_tot, n_eq) in nombres.items():
            b = lg.get(campo) or {}
            if (b.get('origen') or '') != 'observado':
                # estimado o sin datos: se dice, y queda fuera del ranking
                filas.append(_fila(n_tot, None, 0, origen='estimado'))
                continue
            tot = b.get('total') or {}
            eq = b.get('por_equipo') or {}
            filas.append(_fila(n_tot, tot.get('error_calib'),
                               tot.get('n') or 0,
                               disp=b.get('dispersion_total'),
                               media=b.get('media_total')))
            if n_eq:
                filas.append(_fila(n_eq, eq.get('error_calib'),
                                   eq.get('n') or 0,
                                   disp=b.get('dispersion_equipo')))
        # remates de jugador: medido, pero AGREGADO sobre todas las ligas
        filas.append(_fila('Remates de jugador', None, 0, origen='sin medir'))
        salida[clave] = filas
    return salida


# ---------------------------------------------------------------------------
# construcción y consulta
# ---------------------------------------------------------------------------
def construir() -> Dict:
    """Junta las cuatro fuentes y ordena cada liga por fiabilidad."""
    fuentes = [_de_1x2(), _de_totales(), _de_handicap(), _de_fisicos()]
    ligas: Dict[str, List[Dict]] = {}
    for f in fuentes:
        for clave, filas in f.items():
            ligas.setdefault(clave, []).extend(filas)

    salida: Dict[str, Dict] = {}
    for clave, filas in ligas.items():
        # el orden: primero lo medido y por ECE ascendente; lo no medido, al
        # final y sin puesto. Un mercado sin medición no puede ser rey.
        medidos = [f for f in filas if f['ece_efectiva'] is not None
                   and f['estado'] != INESTABLE]
        medidos.sort(key=lambda f: f['ece_efectiva'])
        for i, f in enumerate(medidos):
            f['puesto'] = i + 1
        rey = medidos[0]['mercado'] if medidos else None
        salida[clave] = {
            'rey': rey,
            'mercados': sorted(
                filas, key=lambda f: (f['ece_efectiva'] is None,
                                      f['ece_efectiva'] or 9.9)),
            'bloques': _por_bloque(filas)}
    return {'generado_por': 'mercado_estabilidad.py',
            'umbrales': {'ece_estable': ECE_ESTABLE,
                         'ece_moderado': ECE_MODERADO,
                         'dispersion_max': DISPERSION_MAX, 'min_n': MIN_N},
            'ligas': salida}


def _por_bloque(filas: List[Dict]) -> Dict[str, str]:
    """
    El estado de cada BLOQUE de la tarjeta: el mejor de sus familias.

    El mejor y no el peor: la tarjeta enseña un semáforo por bloque y lo que el
    usuario necesita saber es si en ese bloque hay algo fiable, no si TODAS sus
    líneas lo son. La línea concreta ya lleva su propia cifra.
    """
    orden = {ESTABLE: 0, MODERADO: 1, INESTABLE: 2, SIN_MEDIR: 3}
    salida: Dict[str, str] = {}
    for f in filas:
        b = f['bloque']
        if b not in salida or orden[f['estado']] < orden[salida[b]]:
            salida[b] = f['estado']
    return salida


def guardar(doc: Dict, ruta: str = FICHERO) -> None:
    try:
        import io_atomico
        io_atomico.escribir_json(ruta, doc)
    except Exception:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))


def cargar(ruta: str = FICHERO, recargar: bool = False) -> Dict:
    global _CACHE
    if _CACHE is not None and not recargar:
        return _CACHE
    datos: Dict = {}
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.debug('[estabilidad] no se pudo leer %s: %s', ruta, e)
    _CACHE = datos
    return datos


def de_liga(clave_liga) -> Dict:
    """Todo lo medido de esa competición. `{}` si no está."""
    return ((cargar().get('ligas') or {}).get(str(clave_liga or '')) or {})


def rey(clave_liga) -> Optional[str]:
    """El mercado más fiable de esa competición, o `None`."""
    return de_liga(clave_liga).get('rey')


def estado_bloque(clave_liga, bloque: str) -> str:
    """`estable` / `moderado` / `inestable` / `sin medir` de un bloque."""
    return (de_liga(clave_liga).get('bloques') or {}).get(bloque, SIN_MEDIR)


def semaforo(clave_liga, bloque: str) -> str:
    """El icono de ese bloque: 🟢 🟡 🔴 ⚪."""
    return SEMAFORO.get(estado_bloque(clave_liga, bloque), '⚪')


def en_cuarentena(clave_liga, bloque: str) -> bool:
    """
    ¿Este bloque está bloqueado para recomendaciones?

    Lo está cuando su mejor familia sale `inestable`: o calibra por encima de
    0,05 o su varianza dobla a su media. Se puede MIRAR —el usuario ve sus
    probabilidades— pero la aplicación no lo propone.
    """
    return estado_bloque(clave_liga, bloque) in (INESTABLE, SIN_MEDIR)


def puesto(clave_liga, mercado: str) -> Optional[int]:
    """El puesto de ese mercado en el ranking de su liga, o `None`."""
    for f in (de_liga(clave_liga).get('mercados') or []):
        if f.get('mercado') == mercado:
            return f.get('puesto')
    return None


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ver', help='enseña el ranking de una competición')
    ap.add_argument('--salida', default=FICHERO)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    if a.ver:
        d = de_liga(a.ver)
        if not d:
            print('sin datos de %s' % a.ver)
            return 1
        print('MERCADO REY de %s: %s\n' % (a.ver, d.get('rey')))
        print('%-24s %-8s %8s %7s %10s %s'
              % ('mercado', 'estado', 'ECE', 'n', 'disp', 'puesto'))
        print('-' * 72)
        for f in d['mercados']:
            print('%-24s %-8s %8s %7d %10s %s'
                  % (f['mercado'], SEMAFORO[f['estado']] + f['estado'][:3],
                     '%.4f' % f['ece'] if f['ece'] is not None else '-',
                     f['n'],
                     '%.3f' % f['dispersion'] if f['dispersion'] else '-',
                     f.get('puesto') or '-'))
        return 0

    doc = construir()
    guardar(doc, a.salida)
    ligas = doc['ligas']
    from collections import Counter
    c = Counter(v['rey'] for v in ligas.values())
    print('%d competiciones -> %s\n' % (len(ligas), a.salida))
    print('MERCADO REY, reparto:')
    for k, v in c.most_common():
        print('  %-24s %3d' % (k or '(ninguno)', v))
    est = Counter()
    for v in ligas.values():
        for b, e in (v.get('bloques') or {}).items():
            est[e] += 1
    print('\nbloques por estado: %s' % dict(est))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
