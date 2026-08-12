#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v127 — The Odds API dentro del presupuesto gratuito: 23 casas por 0 €.

Qué aporta
----------
El consenso es la palanca medida del proyecto, y hoy tiene cinco casas. Medido
con una llamada de 2 créditos sobre Liga MX: este proveedor devuelve **23 casas
distintas** en el mismo partido, con una dispersión real de hasta el 14,6 % en
el mismo resultado (Atlante FC a 5,75 en sport888 y a 6,59 en onexbet).

Esa dispersión es exactamente lo que el proyecto mide como su única señal
positiva, y con cinco casas no se ve.

EL PRESUPUESTO MANDA SOBRE TODO LO DEMÁS
----------------------------------------
El plan gratuito da **500 créditos al mes**, que se renuevan. El coste es:

    /v4/sports            0 créditos   (catálogo: gratis)
    /v4/events            0 créditos
    /v4/{liga}/odds       1 × mercados × regiones      ← por LIGA, no por partido
    /v4/.../historical   10 × mercados × regiones      ← PROHIBIDO aquí

Con 500 al mes son 16,7 al día. Las cuentas, hechas antes de escribir una línea:

    5 ligas × 2 mercados × 1 región × 4 veces/día = 1.200/mes  ✗ imposible
    5 ligas × 2 mercados × 1 región × 3 veces/día =   900/mes  ✗ imposible
    5 ligas × 1 mercado  × 1 región × 3 veces/día =   450/mes  ✓ justo
    bajo demanda, 10 partidos/día, 1 mercado      =   300/mes  ✓ holgado

POR QUÉ BAJO DEMANDA Y NO SONDEO PROGRAMADO
-------------------------------------------
Un sondeo a horas fijas gasta lo mismo mire alguien o no, y además llega viejo:
si el usuario abre una ficha a las 19:40 y el último sondeo fue a las 18:00, se
le enseña una foto de hora y media antes. Bajo demanda se gasta sólo en lo que
se mira y el dato es de hace minutos.

Y como la llamada trae **toda la liga**, la caché por liga hace que mirar diez
partidos de la misma jornada cueste UN crédito, no diez.

El sondeo programado sigue disponible (`refrescar_ligas`) para quien lo
prefiera, con el mismo contador delante.

EL CORTE ES DURO Y ESTÁ EN EL CÓDIGO
------------------------------------
Por encima de `LIMITE_DURO` créditos en el mes, este módulo **deja de llamar** y
devuelve `None`. El sistema vuelve solo al consenso de cinco casas y la interfaz
lo dice. No hay forma de que una racha de consultas se coma el presupuesto y
deje la app sin cuotas el día 20.

La clave se lee de `ODDS_API_KEY` (variable de entorno o Secrets de Streamlit).
Nunca se escribe en disco ni se registra.
"""
import json
import logging
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE = 'https://api.the-odds-api.com/v4'
CUOTA_MENSUAL = 500
# El corte se pone por debajo del máximo a propósito: deja margen para que una
# llamada en curso o un descuadre con el contador del proveedor no rebasen.
LIMITE_DURO = int(os.environ.get('ODDS_API_LIMITE', '450'))
ARCHIVO_USO = 'consenso_api_uso.json'
CACHE_DIR = 'cuotas_cache'
TTL = 1800                       # 30 min, el mismo que el resto del tablón
TIMEOUT = 25

# ---------------------------------------------------------------------------
# LISTA BLANCA
#
# Sólo se gastan créditos en competiciones que (a) el proyecto modela y (b) el
# usuario mira. Las 24 huérfanas NO entran: de sus 19 de fútbol este proveedor
# sólo cubre 8, y su histórico —que es lo que necesitarían— está fuera del plan
# gratuito. Quedan congeladas, como se acordó.
#
# El orden importa: si algún día hubiera que recortar, se recorta por el final.
# ---------------------------------------------------------------------------
LIGAS_BLANCAS: Dict[str, str] = {
    'liga_mx':        'soccer_mexico_ligamx',
    'laliga':         'soccer_spain_la_liga',
    'premier':        'soccer_epl',
    'mls':            'soccer_usa_mls',
    'serie_a':        'soccer_italy_serie_a',
    'bundesliga':     'soccer_germany_bundesliga',
    'ligue_1':        'soccer_france_ligue_one',
    'primeira':       'soccer_portugal_primeira_liga',
    'eredivisie':     'soccer_netherlands_eredivisie',
    'brasil':         'soccer_brazil_campeonato',
    'argentina':      'soccer_argentina_primera_division',
    'champions':      'soccer_uefa_champs_league',
    'europa_league':  'soccer_uefa_europa_league',
    'leagues_cup':    'soccer_concacaf_leagues_cup',
    'libertadores':   'soccer_conmebol_copa_libertadores',
}

# Un solo mercado por defecto. Añadir 'totals' DUPLICA el gasto, así que es una
# decisión explícita del llamador y no un valor por defecto silencioso.
MERCADOS_POR_DEFECTO = ('h2h',)
# Una sola región. 'eu' trae el ancla sharp (Pinnacle) y la mayoría de las casas
# europeas; añadir 'us' duplicaría el coste por unas pocas casas más.
REGION_POR_DEFECTO = 'eu'


def _clave() -> str:
    k = (os.environ.get('ODDS_API_KEY') or '').strip()
    if not k:
        try:
            import streamlit as st
            k = (st.secrets.get('ODDS_API_KEY') or '').strip()
        except Exception:
            k = ''
    return k


def disponible() -> bool:
    """¿Hay clave configurada? Sin ella el módulo entero se queda callado."""
    return bool(_clave())


# ---------------------------------------------------------------------------
# EL CONTADOR
# ---------------------------------------------------------------------------
def _mes_actual() -> str:
    return time.strftime('%Y-%m')


def uso() -> Dict:
    """
    Créditos gastados este mes, según el proveedor y según nosotros.

    El número que manda es el del PROVEEDOR (`x-requests-used`), que llega en la
    cabecera de cada respuesta: es el único que no se descuadra si el módulo se
    ejecuta desde dos sitios a la vez. El nuestro sirve para decidir ANTES de
    llamar, que es cuando hace falta.
    """
    d = {'mes': _mes_actual(), 'usados': 0, 'llamadas': 0,
         'usados_proveedor': None, 'restantes_proveedor': None}
    try:
        if os.path.exists(ARCHIVO_USO):
            with open(ARCHIVO_USO, encoding='utf-8') as f:
                g = json.load(f)
            if g.get('mes') == d['mes']:      # el mes cambia → contador a cero
                d.update(g)
    except Exception as e:
        logger.debug(f'[consenso] contador ilegible: {type(e).__name__}: {e}')
    return d


def _anotar(coste: int, cab) -> None:
    d = uso()
    d['usados'] = int(d.get('usados', 0)) + max(int(coste or 0), 0)
    d['llamadas'] = int(d.get('llamadas', 0)) + 1
    for clave, cab_nombre in (('usados_proveedor', 'x-requests-used'),
                              ('restantes_proveedor', 'x-requests-remaining')):
        v = (cab or {}).get(cab_nombre)
        if v is not None:
            try:
                d[clave] = int(v)
            except (TypeError, ValueError):
                pass
    try:
        with open(ARCHIVO_USO, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def presupuesto() -> Dict:
    """
    El estado del presupuesto, para enseñarlo y para decidir.

    `queda` usa el contador del proveedor cuando lo tenemos, porque es el real.
    """
    d = uso()
    usados = d.get('usados_proveedor')
    if usados is None:
        usados = d.get('usados', 0)
    return {'mes': d['mes'], 'usados': int(usados),
            'limite': LIMITE_DURO, 'cuota': CUOTA_MENSUAL,
            'queda': max(LIMITE_DURO - int(usados), 0),
            'llamadas': d.get('llamadas', 0),
            'agotado': int(usados) >= LIMITE_DURO}


def hay_presupuesto(coste: int = 1) -> bool:
    """¿Cabe una llamada de este coste sin pasar del límite duro?"""
    p = presupuesto()
    return (p['usados'] + max(int(coste), 1)) <= LIMITE_DURO


# ---------------------------------------------------------------------------
# LA LLAMADA
# ---------------------------------------------------------------------------
def _ruta_cache(liga_prov: str, mercados, region: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    m = '-'.join(sorted(mercados))
    return os.path.join(CACHE_DIR, f'oddsapi_{liga_prov}_{m}_{region}.json')


def cuotas_liga(clave_liga: str, mercados=MERCADOS_POR_DEFECTO,
                region: str = REGION_POR_DEFECTO,
                ttl: int = TTL) -> Optional[List[Dict]]:
    """
    Todos los partidos de una liga con las cuotas de las casas del proveedor.

    Devuelve `None` —y no una lista vacía— cuando NO se pudo consultar, que es
    distinto de «no hay partidos»: sin clave, fuera de la lista blanca, sin
    presupuesto o con error de red. Quien llama tiene que poder distinguir «no
    hay nada hoy» de «no lo hemos podido mirar», porque en el segundo caso la
    interfaz debe decirlo.

    UNA llamada trae TODA la liga y se cachea 30 minutos, así que mirar diez
    partidos de la misma jornada cuesta un crédito, no diez.
    """
    liga_prov = LIGAS_BLANCAS.get(clave_liga)
    if not liga_prov:
        return None                     # fuera de la lista blanca: no se gasta
    ruta = _ruta_cache(liga_prov, mercados, region)
    if os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < ttl:
        try:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    k = _clave()
    if not k:
        return None
    coste = max(len(mercados), 1) * max(len(region.split(',')), 1)
    if not hay_presupuesto(coste):
        p = presupuesto()
        logger.warning(
            f"[consenso] presupuesto agotado ({p['usados']}/{LIMITE_DURO} "
            f"créditos en {p['mes']}): se sigue con el consenso de cinco casas "
            f"hasta que el mes se renueve")
        return None

    try:
        import requests
        r = requests.get(f'{BASE}/sports/{liga_prov}/odds',
                         params={'apiKey': k, 'regions': region,
                                 'markets': ','.join(mercados),
                                 'oddsFormat': 'decimal'},
                         timeout=TIMEOUT)
    except Exception as e:
        logger.info(f'[consenso] {liga_prov}: {type(e).__name__}: {e}')
        return None
    _anotar(r.headers.get('x-requests-last') or coste, r.headers)
    if r.status_code != 200:
        logger.warning(f'[consenso] {liga_prov}: HTTP {r.status_code}')
        return None
    try:
        datos = r.json()
    except Exception:
        return None
    try:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False)
    except Exception:
        pass
    return datos


def casas_del_partido(clave_liga: str, home: str, away: str,
                      mercados=MERCADOS_POR_DEFECTO,
                      region: str = REGION_POR_DEFECTO) -> Dict[str, Dict]:
    """
    Las cuotas 1X2 de cada casa para UN partido, en el formato del proyecto.

    `{casa: {'home': 1.55, 'draw': 4.25, 'away': 5.33}}`, que es exactamente lo
    que `cuotas_multi.cuotas_partido` mete en `casas`. Así el consenso pasa de
    cinco a veintitantas sin tocar el resto del tablón.

    El emparejamiento va por `name_mapper`, el mismo que usa todo el proyecto,
    y exige que casen LOS DOS equipos. Un partido mal emparejado aquí sería el
    fallo de la v114 otra vez, pero con veintitrés casas detrás.
    """
    datos = cuotas_liga(clave_liga, mercados, region)
    if not datos:
        return {}
    try:
        import name_mapper as nm
        equipos = []
        for e in datos:
            equipos += [e.get('home_team'), e.get('away_team')]
        equipos = [x for x in equipos if x]
        h = nm.mapear(home, equipos, contexto='oddsapi') or home
        a = nm.mapear(away, equipos, contexto='oddsapi') or away
    except Exception:
        h, a = home, away

    ev = None
    for e in datos:
        eh, ea = str(e.get('home_team') or ''), str(e.get('away_team') or '')
        if eh == h and ea == a:
            ev = e
            break
    if ev is None:
        return {}

    fuera: Dict[str, Dict] = {}
    for b in (ev.get('bookmakers') or []):
        casa = str(b.get('title') or b.get('key') or '').strip()
        if not casa:
            continue
        for m in (b.get('markets') or []):
            if m.get('key') != 'h2h':
                continue
            c = {}
            for o in (m.get('outcomes') or []):
                nombre, precio = o.get('name'), o.get('price')
                try:
                    precio = float(precio)
                except (TypeError, ValueError):
                    continue
                if precio <= 1:
                    continue
                if nombre == ev.get('home_team'):
                    c['home'] = precio
                elif nombre == ev.get('away_team'):
                    c['away'] = precio
                elif str(nombre).lower() in ('draw', 'empate', 'tie'):
                    c['draw'] = precio
            if c.get('home') and c.get('away'):
                fuera[casa] = c
    return fuera


def refrescar_ligas(claves: Optional[List[str]] = None,
                    mercados=MERCADOS_POR_DEFECTO,
                    region: str = REGION_POR_DEFECTO) -> Dict:
    """
    Sondeo programado de varias ligas, para quien prefiera la tarea a horas
    fijas en vez de bajo demanda. Respeta el mismo límite duro.

    Devuelve cuánto se ha gastado y qué ligas se han quedado fuera, para que la
    tarea pueda avisar en vez de fallar en silencio.
    """
    claves = claves or list(LIGAS_BLANCAS)
    hechas, saltadas = [], []
    for c in claves:
        antes = presupuesto()['usados']
        d = cuotas_liga(c, mercados, region, ttl=0)     # forzar refresco
        if d is None:
            saltadas.append(c)
        else:
            hechas.append((c, len(d), presupuesto()['usados'] - antes))
    p = presupuesto()
    logger.info(f"[consenso] refresco: {len(hechas)} ligas · "
                f"{len(saltadas)} saltadas · {p['usados']}/{LIMITE_DURO} "
                f"créditos usados en {p['mes']}")
    return {'hechas': hechas, 'saltadas': saltadas, 'presupuesto': p}
