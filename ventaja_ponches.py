#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v132 — La escalera de ponches: ventaja de precio, y la foto diaria que falta.

QUÉ DECIDE, Y QUÉ NO
--------------------
Playdoit no publica una línea de ponches: publica una ESCALERA («al menos 2+,
3+, 4+…») con precio en cada escalón. Elegir escalón por el EV del modelo es
una trampa, y está medido: ajustando una Poisson a los precios de una escalera
real, el margen de la casa CRECE con el escalón.

    escalón   1/cuota   precio justo   margen
    2+         84,6 %      87,1 %      pequeño
    4+         46,5 %      47,8 %      pequeño
    6+         20,0 %      15,2 %      grande
    7+         11,1 %       7,1 %      enorme

Maximizar el EV del modelo empuja justo a los escalones donde la casa se queda
más, y como el modelo tiene su optimismo residual en la cola, el EV que sale es
fantasía — es el patrón que el proyecto bautizó `EV_SOSPECHOSO`.

Así que se decide igual que en la Sección 1 de fútbol, que es el único criterio
con p5 positivo del proyecto: **por ventaja de precio contra el mercado.**

    λ_mercado = de la línea de Pinnacle, devigada
    justo_n   = 1 / P_mercado(K >= n)
    VENTAJA   = cuota_playdoit(n) / justo_n − 1      ← esto decide
    EV_modelo = P_modelo(K >= n) × cuota − 1         ← se enseña, no decide

EL MODELO ORDENA Y DESCARTA, NO DECIDE
--------------------------------------
Medido sobre 7.017 aperturas de 2025 y 2026 con λ del módulo B y el descuento
de calibración, la brecha entre lo que promete P(K>=n) y lo que se cumple:

    escalón   2025     2026
    2+ … 7+   ≤ 0      ≤ +0,4 pp     fiables
    8+        −0,4     **+0,9 pp**   promete de más

Por eso `ESCALON_MAXIMO = 7`: por encima el modelo no puede ni descartar.

LO QUE ESTE MÓDULO TODAVÍA NO PUEDE HACER
-----------------------------------------
**No hay histórico de precios de props.** Ni `odds_snapshots.csv` ni
`historical_odds` (155.364 filas) guardan una sola línea de ponches, y
`daily_snapshots` nunca las miró. Sin ese histórico no se puede medir el ROI ni
el p5 de decidir por ventaja de precio, y sin esa medición **esto no se publica
como recomendación**: es la regla del proyecto y no se salta ni con prisa.

De ahí `fotografiar()`: empieza a guardar hoy lo que hará posible la medición
en unas semanas. No cuesta créditos — Pinnacle y Altenar son endpoints libres.
"""
import csv
import logging
import math
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Por encima de este escalón el modelo promete de más (ver el encabezado), así
# que no puede usarse ni para descartar. No se ofrecen.
ESCALON_MAXIMO = 7

# Ventaja mínima para considerar que hay algo. Es el mismo umbral que la
# Sección 1 de fútbol, y por el mismo motivo: por debajo, lo medido es ruido de
# redondeo entre casas. Ver `clasificador.UMBRAL_VENTAJA`.
UMBRAL_VENTAJA = 0.05

# Por encima de esto no es una ventaja, es un desemparejamiento. Misma red que
# `clasificador.VENTAJA_IMPOSIBLE`.
VENTAJA_IMPOSIBLE = 0.30

ARCHIVO_FOTOS = 'ponches_snapshots.csv'
_CAMPOS = ('fecha_foto', 'fecha_partido', 'home', 'away', 'lanzador',
           'escalon', 'cuota_playdoit', 'linea_pinnacle', 'odd_over_pin',
           'odd_under_pin', 'lam_mercado', 'lam_modelo', 'bf_apertura',
           'n_aperturas')

_RE_ESCALERA = re.compile(r'strikeouts del jugador al menos \(([^()]+)\s*\(',
                          re.I)
_RE_ESCALON = re.compile(r'^(\d+)\+$')


def p_al_menos(lam: float, n: int) -> float:
    """P(K >= n) con la misma Poisson que usa el resto del proyecto."""
    if not lam or lam <= 0:
        return 0.0
    return max(0.0, 1.0 - sum(math.exp(-lam) * lam ** i / math.factorial(i)
                              for i in range(int(n))))


def lam_desde_linea(linea: float, odd_over, odd_under) -> Optional[float]:
    """
    La λ que el MERCADO implica, a partir de la línea de ponches de Pinnacle.

    Se devigan las dos cuotas —normalizando para que sumen 1, igual que hace
    `clasificador.consenso_sin_margen`— y se busca la λ de Poisson cuya
    P(K > línea) coincide con la probabilidad justa del over. Es una búsqueda
    binaria porque P es monótona en λ, así que converge siempre.

    Devuelve None si falta un lado: con una sola cuota no hay libro que
    normalizar, y suponer el otro sería inventarse el ancla.
    """
    try:
        o, u = float(odd_over), float(odd_under)
        L = float(linea)
    except (TypeError, ValueError):
        return None
    if o <= 1 or u <= 1:
        return None
    inv_o, inv_u = 1.0 / o, 1.0 / u
    suma = inv_o + inv_u
    if suma <= 0:
        return None
    p_over = inv_o / suma            # devig proporcional
    objetivo = int(math.floor(L)) + 1        # «más de 5.5» == «al menos 6»
    lo, hi = 0.05, 20.0
    for _ in range(60):
        med = (lo + hi) / 2
        if p_al_menos(med, objetivo) < p_over:
            lo = med
        else:
            hi = med
    return round((lo + hi) / 2, 4)


def escalera_de(detalle: Dict, lanzador: str) -> Dict[int, float]:
    """
    `{escalón: cuota}` de ese lanzador en el tablero de Playdoit.

    El nombre viaja dentro del nombre del mercado —«Strikeouts del jugador al
    menos (Keider Montero (DET))»— porque el `sv` trae el id interno de
    Altenar, que no es el de StatsAPI y no sirve para cruzar con nada nuestro.
    Se empareja por apellido, que es lo que ya hace `prop_de_pitcher`.
    """
    if not detalle or not lanzador:
        return {}
    apellido = str(lanzador).split()[-1].lower()
    out: Dict[int, float] = {}
    for m in (detalle.get('mercados') or []):
        nombre = str(m.get('nombre') or '')
        g = _RE_ESCALERA.search(nombre)
        if not g or apellido not in g.group(1).lower():
            continue
        for s in (m.get('selecciones') or []):
            e = _RE_ESCALON.match(str(s.get('nombre') or '').strip())
            try:
                cuota = float(s.get('cuota'))
            except (TypeError, ValueError):
                continue
            if e and cuota > 1.0:
                n = int(e.group(1))
                # si el mismo escalón sale dos veces, manda el mejor precio
                if n not in out or cuota > out[n]:
                    out[n] = round(cuota, 4)
    return out


def evaluar(escalera: Dict[int, float], lam_mercado: Optional[float],
            lam_modelo: Optional[float] = None,
            margen_modelo: float = 0.0) -> Dict:
    """
    Cada escalón con su ventaja de precio, y cuál se propondría.

    `lam_mercado` es el ancla. Sin ella no se decide nada: se devuelve la
    escalera con el EV del modelo marcado como NO validado y un aviso, que es
    lo que pide la regla de degradación silenciosa.
    """
    filas: List[Dict] = []
    for n in sorted(escalera):
        if n > ESCALON_MAXIMO:
            continue                      # el modelo promete de más ahí arriba
        cuota = escalera[n]
        fila = {'escalon': n, 'cuota': cuota}
        if lam_mercado:
            p_mkt = p_al_menos(lam_mercado, n)
            fila['prob_mercado'] = round(p_mkt, 4)
            fila['cuota_justa'] = round(1.0 / p_mkt, 4) if p_mkt > 0 else None
            if fila['cuota_justa']:
                fila['ventaja'] = round(cuota / fila['cuota_justa'] - 1.0, 4)
        if lam_modelo:
            p_mod = max(0.0, p_al_menos(lam_modelo, n) - float(margen_modelo))
            fila['prob_modelo'] = round(p_mod, 4)
            fila['ev_modelo'] = round(cuota * p_mod - 1.0, 4)
        filas.append(fila)

    if not lam_mercado:
        return {'escalones': filas, 'elegido': None, 'sin_ancla': True,
                'motivo': 'Sin consenso de precio (la línea de Pinnacle no '
                          'está disponible), así que no se puede medir la '
                          'ventaja. Lo que se ve es la estimación del modelo, '
                          'que por sí sola no decide.'}

    # EL MODELO DESCARTA, EL PRECIO DECIDE.
    #
    # Primero se caen los escalones que el modelo considera improbables —no
    # tiene sentido comprar barato algo que no va a pasar— y de los que
    # sobreviven se elige el de MAYOR VENTAJA, no el de mayor EV.
    con_ventaja = [f for f in filas if f.get('ventaja') is not None]

    # PRIMERO EL GUARDIA DE DATOS, Y CON MENSAJE PROPIO.
    #
    # Si TODOS los escalones dan una ventaja imposible, lo que falla no es el
    # partido: es el ancla. Pasa cuando la línea de Pinnacle es de otro
    # lanzador o la escalera se emparejó mal — y entonces decir «este partido
    # no tiene valor» sería mentir con cara de veredicto. Se dice lo que de
    # verdad ocurre. Lo cazó la primera prueba del módulo: la tabla enseñaba
    # ventajas del +33 % al +65 % y el veredicto decía que no había ninguna.
    imposibles = [f for f in con_ventaja if f['ventaja'] >= VENTAJA_IMPOSIBLE]
    if con_ventaja and len(imposibles) == len(con_ventaja):
        return {'escalones': filas, 'elegido': None, 'ancla_sospechosa': True,
                'motivo': f'Los {len(imposibles)} escalones dan una ventaja de '
                          f'entre {min(f["ventaja"] for f in imposibles)*100:+.0f} % y '
                          f'{max(f["ventaja"] for f in imposibles)*100:+.0f} %, que '
                          f'entre dos casas reales es imposible. Casi seguro '
                          f'que la línea de referencia es de otro lanzador: no '
                          f'se propone nada hasta que cuadre.'}

    aptos = [f for f in con_ventaja if f['ventaja'] < VENTAJA_IMPOSIBLE]
    if lam_modelo:
        # el modelo DESCARTA lo improbable, no elige lo valioso
        aptos = [f for f in aptos if (f.get('prob_modelo') or 0) >= 0.20]
    con_valor = [f for f in aptos if f['ventaja'] >= UMBRAL_VENTAJA]
    if not con_valor:
        return {'escalones': filas, 'elegido': None,
                'motivo': 'Ningún escalón paga por encima del precio justo del '
                          'mercado. Este partido no tiene valor en ponches: no '
                          'juegues la línea.'}
    mejor = max(con_valor, key=lambda f: f['ventaja'])
    return {'escalones': filas, 'elegido': mejor,
            'motivo': f"más de {mejor['escalon'] - 0.5:.1f} ponches a "
                      f"{mejor['cuota']:.2f}: paga un "
                      f"{mejor['ventaja']*100:+.1f} % por encima del precio "
                      f"justo del mercado"}


# ---------------------------------------------------------------------------
# LA FOTO DIARIA — sin esto no habrá backtest nunca
# ---------------------------------------------------------------------------
def fotografiar(filas: List[Dict], ruta: str = ARCHIVO_FOTOS) -> int:
    """
    Añade al CSV de fotos. Una fila por escalón y día.

    Es la pieza que hoy falta para poder medir si decidir por ventaja de precio
    gana dinero. El proyecto tiene 155.364 filas de histórico de 1X2 y CERO de
    props, y por eso la Tarea 3 no se puede validar todavía. Esto lo arregla
    hacia adelante: en unas semanas habrá muestra.
    """
    if not filas:
        return 0
    nuevo = not os.path.exists(ruta)
    try:
        with open(ruta, 'a', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(_CAMPOS),
                               extrasaction='ignore')
            if nuevo:
                w.writeheader()
            for fila in filas:
                w.writerow(fila)
        return len(filas)
    except Exception as e:
        logger.warning(f'[ponches] no se pudo escribir la foto: '
                       f'{type(e).__name__}: {e}')
        return 0
