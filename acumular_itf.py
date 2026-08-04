#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — La fuente VIVA del circuito ITF, que es lo que le faltaba a la v96.

Qué problema resuelve
---------------------
La v96 ingirió 566.860 partidos de ITF desde el espejo
`Aneeshers/tennis-sackmann-archive` y con eso el circuito pasó a tener modelo.
Pero ese espejo es un **archivo**, no un servicio: su último partido es del
**2026-06-01**. Para ENTRENAR da igual (35 años de historia no cambian porque
falten dos meses), pero el estado de FORMA de un jugador de M15 sí cambia: en
ocho semanas un chico de 19 años juega 15 torneos y cambia de nivel.

Lo que se probó antes de llegar aquí (todo medido el 2026-08-04, ver
VALIDACION_v97.md):

  · **itftennis.com** — sigue devolviendo la página anti-bot. Peor que en la
    v96: ahora son **212 bytes** en la web y en las cuatro rutas de API que se
    probaron (`GetCalendar`, `GetLiveScores`, `GetResults`,
    `GetCompletedTournaments`). No hay endpoint JSON accesible.
  · **TennisAbstract** — SÍ tiene el array `matchmx`… pero su `robots.txt`
    dice literalmente `Disallow: /jsmatches/`, `/jsplayers/`, `/jsfrags/`,
    que son exactamente las rutas donde vive. Queda **descartado por
    robots.txt**, no por falta de dato.
  · **Sofascore** — 403.
  · **ESPN** — reconfirmado: 0 partidos de ITF (sí cubre challengers, que es
    lo que `acumular_tenis.py` ya recoge).
  · **TennisExplorer** — robots permisivo y cubre las 11 mujeres de ITF que
    hoy cotiza Pinnacle… pero **cero torneos ITF masculinos**. Media fuente.

  · **BetExplorer** — es ésta. `robots.txt` sólo prohíbe cadenas de consulta
    (`/*?year=`, `/*?month=`, `/*?page=`…); las rutas planas que aquí se usan
    están permitidas. Sirve `itf-men-singles` e `itf-women-singles` con
    **fecha explícita** (`data-dt="4,8,2026,9,30"`), ganador, sets y juegos.

Por qué el ganador NO se lee de la posición
-------------------------------------------
En la v96 la fuga de posición casi se despliega: al traducir el esquema de
Sackmann el ganador quedaba SIEMPRE en la primera columna y el modelo aprendió
«gana el primero» (93,54 % de precisión imposible). Aquí el riesgo es el mismo
y el mecanismo también: BetExplorer marca al ganador con `<strong>`, y quien
gana está a veces arriba y a veces abajo — pero eso hay que **medirlo**, no
suponerlo. `acumular()` calcula el reparto antes de escribir y **lanza
ValueError si se sale de [40 %, 60 %]**. Un fallo así no puede depender de que
alguien mire la métrica.

Uso:
    python acumular_itf.py              # ventana viva de BetExplorer
    python acumular_itf.py --dry-run    # mide y no escribe
"""
import argparse
import logging
import os
import re
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ARCHIVO = 'historico_itf_vivo.csv'
CAMPOS = ('fecha', 'circuito', 'nivel', 'torneo', 'superficie',
          'jugador_1', 'jugador_2', 'ganador', 'sets_1', 'sets_2',
          'juegos_totales', 'cuota_1', 'cuota_2')

URL_RESULTADOS = 'https://www.betexplorer.com/results/tennis/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# Reparto ganador arriba/abajo admisible. Fuera de esta banda algo está mal en
# el parseo y escribir el fichero contaminaría el entrenamiento (lección v96).
REPARTO_MIN, REPARTO_MAX = 0.40, 0.60
# Por debajo de esto no se juzga el reparto: con 20 partidos un 65 % es ruido.
MUESTRA_MINIMA = 60

# Cabecera de torneo:
#   <a href="/tennis/itf-men-singles/m15-astana/" ...>...ITF Men - Singles: M15 Astana, hard</a>
RE_TORNEO = re.compile(
    r'<tr class="js-tournament">.*?<a href="(/tennis/([a-z\-]+)/([^/"]+)/)"[^>]*>(.*?)</a>',
    re.S)
# Fila de partido finalizado.
RE_PARTIDO = re.compile(
    r'<tr data-fro="\d+" data-dt="(\d+),(\d+),(\d+),(\d+),(\d+)".*?'
    r'<a href="(/tennis/[^"]+?/([^/"]+)/[A-Za-z0-9]+/)"[^>]*>'
    r'<span class="table-main__teamLine table-main__teamLine--home">(.*?)</span>'
    r'<span class="table-main__teamLine table-main__teamLine--away">(.*?)</span>'
    r'</a>\s*</td>(.*?)</tr>', re.S)
RE_MARCADOR = re.compile(r'<td class="table-main__result">.*?<strong>(\d+):(\d+)</strong>', re.S)
RE_PARCIALES = re.compile(r'<td class="table-main__partial"[^>]*>\(([^)]*)\)</td>')
RE_CUOTA = re.compile(r'data-odd="([\d.]+)"')
RE_ETIQUETA = re.compile(r'<[^>]+>')


def _texto(html: str) -> str:
    return RE_ETIQUETA.sub('', html).replace('&nbsp;', ' ').strip()


def _get(url: str, intentos: int = 3, timeout: int = 40):
    """GET educado: un hilo, espera creciente, User-Agent real."""
    import requests
    ultima = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers={'User-Agent': UA}, timeout=timeout)
            if r.status_code == 200:
                return r
            ultima = RuntimeError(f'HTTP {r.status_code}')
            time.sleep(2 * (i + 1))
        except Exception as e:
            ultima = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'betexplorer no respondió: {ultima}')


def _nivel(slug_torneo: str) -> Optional[str]:
    """M15/M25/W15/W35… del slug (`m25-fano` -> 'M25'). None si no es ITF."""
    m = re.match(r'([mw])(\d{2,3})\b', slug_torneo.lower())
    return f'{m.group(1).upper()}{m.group(2)}' if m else None


def _nombres_del_slug(slug: str, mostrado_1: str, mostrado_2: str):
    """
    Nombre COMPLETO de cada jugador a partir del slug del partido.

    La tabla muestra el nombre abreviado ("Bar Biryukov P.") y el slug trae el
    completo ("bar-biryukov-petr-shebekin-grigory"). El completo es el que
    sirve para cruzar contra el catálogo del modelo, así que se prefiere — pero
    partir el slug por el guion es ambiguo (los apellidos compuestos también
    llevan guion), así que se usa el apellido MOSTRADO como ancla y, si no
    encaja, se cae al nombre abreviado en vez de inventar un reparto.
    """
    def _ap(mostrado: str) -> str:
        # "Bar Biryukov P." -> "bar-biryukov"
        base = re.sub(r'\s+[A-Z]\.?$', '', mostrado).strip()
        return re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')

    def _cap(s: str) -> str:
        return ' '.join(p.capitalize() for p in s.split('-') if p)

    a1, a2 = _ap(mostrado_1), _ap(mostrado_2)
    if not (a1 and a2 and slug.startswith(a1 + '-')):
        return mostrado_1, mostrado_2

    resto = slug[len(a1) + 1:]
    # Dónde empieza el segundo jugador. Se exige i > 0 porque en i == 0 el
    # primer jugador se quedaría sin nombre de pila y eso significa que el
    # apellido mostrado no encajaba de verdad: mejor el nombre abreviado, que
    # es correcto aunque sea corto, que un reparto inventado.
    i = resto.find(a2 + '-')
    if i == -1 and resto.endswith(a2):
        i = len(resto) - len(a2)
    if i <= 0:
        return mostrado_1, mostrado_2
    return _cap(f'{a1}-{resto[:i - 1]}'), _cap(resto[i:])


def descargar() -> List[dict]:
    """
    Partidos ITF de singles TERMINADOS en la ventana viva de BetExplorer.

    Una sola petición. Devuelve la lista sin tocar disco (lo que permite
    medir el reparto de ganadores antes de decidir si se escribe).
    """
    html = _get(URL_RESULTADOS).text
    cortes = [(m.start(), m.group(2), m.group(3), _texto(m.group(4)))
              for m in RE_TORNEO.finditer(html)]
    filas: List[dict] = []
    for i, (pos, categoria, slug_torneo, etiqueta) in enumerate(cortes):
        if categoria not in ('itf-men-singles', 'itf-women-singles'):
            continue
        nivel = _nivel(slug_torneo)
        circuito = 'itf_masculino' if categoria == 'itf-men-singles' else 'itf_femenino'
        # "ITF Men - Singles: M15 Astana, hard" -> torneo y superficie
        cola = etiqueta.split(':', 1)[-1].strip()
        partes = [p.strip() for p in cola.rsplit(',', 1)]
        torneo = partes[0]
        superficie = partes[1] if len(partes) > 1 else ''
        fin = cortes[i + 1][0] if i + 1 < len(cortes) else len(html)
        for m in RE_PARTIDO.finditer(html[pos:fin]):
            d, mes, anio, hh, mm = (int(x) for x in m.groups()[:5])
            slug_partido, cr_1, cr_2, cola_html = m.group(7), m.group(8), m.group(9), m.group(10)
            marc = RE_MARCADOR.search(cola_html)
            if not marc:
                continue                       # aún no jugado o sin marcador
            s1, s2 = int(marc.group(1)), int(marc.group(2))
            if s1 == s2:
                continue                       # abandono/retirada sin ganador claro
            # El ganador es el que la tabla pone en <strong>, NO el primero.
            gana_1 = '<strong>' in cr_1
            gana_2 = '<strong>' in cr_2
            if gana_1 == gana_2:
                # sin marca fiable: se resuelve por sets, que es el mismo dato
                gana_1, gana_2 = s1 > s2, s2 > s1
            n1, n2 = _nombres_del_slug(slug_partido, _texto(cr_1), _texto(cr_2))
            par = RE_PARCIALES.search(cola_html)
            juegos = None
            if par:
                try:
                    juegos = sum(int(x) for x in re.findall(r'\d+', par.group(1)))
                except Exception:
                    juegos = None
            cuotas = RE_CUOTA.findall(cola_html)
            filas.append({
                'fecha': f'{anio:04d}-{mes:02d}-{d:02d}',
                'circuito': circuito, 'nivel': nivel or '', 'torneo': torneo,
                'superficie': superficie,
                'jugador_1': n1, 'jugador_2': n2,
                'ganador': n1 if gana_1 else n2,
                'sets_1': s1, 'sets_2': s2, 'juegos_totales': juegos,
                'cuota_1': cuotas[0] if len(cuotas) > 0 else None,
                'cuota_2': cuotas[1] if len(cuotas) > 1 else None,
            })
    logger.info(f'[itf/betexplorer] {len(filas)} partidos ITF terminados '
                f'en la ventana viva')
    return filas


def reparto_ganadores(filas: List[dict]) -> float:
    """Fracción de partidos donde gana el jugador de la PRIMERA columna."""
    if not filas:
        return 0.5
    return sum(1 for f in filas if f['ganador'] == f['jugador_1']) / len(filas)


def _clave(f: dict) -> tuple:
    return (f['fecha'], *sorted((f['jugador_1'], f['jugador_2'])))


def _leer(ruta: str) -> List[dict]:
    import csv
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def acumular(ruta: str = ARCHIVO, dry_run: bool = False) -> Dict:
    """
    Añade al CSV los partidos ITF nuevos. Idempotente: no pisa lo guardado.

    GUARDIA ANTI-FUGA (regla de oro 7, lección de la v96): si el ganador cae
    en la misma columna más del `REPARTO_MAX` de las veces, **no se escribe
    nada**. Un dataset así no da error — entrena un modelo que aprende la
    posición y devuelve una precisión preciosa e inservible.
    """
    nuevos_crudos = descargar()
    reparto = reparto_ganadores(nuevos_crudos)
    if len(nuevos_crudos) >= MUESTRA_MINIMA and not (REPARTO_MIN <= reparto <= REPARTO_MAX):
        raise ValueError(
            f'[itf/betexplorer] reparto de ganadores {reparto:.1%} fuera de '
            f'[{REPARTO_MIN:.0%}, {REPARTO_MAX:.0%}] sobre {len(nuevos_crudos)} '
            f'partidos: el ganador está quedando siempre en la misma columna. '
            f'No se escribe {ruta} (ver la fuga de posición de la v96).')

    previos = _leer(ruta)
    vistos = {_clave(f) for f in previos}
    nuevos = [f for f in nuevos_crudos if _clave(f) not in vistos]

    if nuevos and not dry_run:
        filas = previos + nuevos
        buf = [','.join(CAMPOS)]
        for f in filas:
            buf.append(','.join(
                '' if f.get(c) is None else
                str(f.get(c)).replace(',', ';').replace('\n', ' ')
                for c in CAMPOS))
        texto = '\n'.join(buf) + '\n'
        try:
            from io_atomico import escribir_texto
            escribir_texto(ruta, texto)
        except Exception:
            with open(ruta, 'w', encoding='utf-8', newline='') as fh:
                fh.write(texto)

    todos = previos + nuevos
    jugadores = ({f['jugador_1'] for f in todos} | {f['jugador_2'] for f in todos})
    fechas = sorted(f['fecha'] for f in todos if f.get('fecha'))
    salida = {
        'nuevos': len(nuevos), 'total': len(todos),
        'jugadores': len(jugadores),
        'torneos': len({f['torneo'] for f in todos}),
        'reparto_ganador_col1': round(reparto, 4),
        'desde': fechas[0] if fechas else None,
        'hasta': fechas[-1] if fechas else None,
        'dry_run': dry_run,
    }
    logger.info(f"[itf/betexplorer] +{len(nuevos)} partidos "
                f"(total {salida['total']}, {salida['jugadores']} jugadores, "
                f"reparto {reparto:.1%})")
    return salida


def jugadores_conocidos(ruta: str = ARCHIVO) -> set:
    filas = _leer(ruta)
    return ({f['jugador_1'] for f in filas if f.get('jugador_1')} |
            {f['jugador_2'] for f in filas if f.get('jugador_2')})


# ---------------------------------------------------------------------------
# Puente al histórico del modelo
# ---------------------------------------------------------------------------
_CATEGORIA = {'itf_masculino': 'itf_m', 'itf_femenino': 'itf_w'}
_CIRCUITO_DE = {'atp': 'itf_masculino', 'wta': 'itf_femenino'}


def cargar(circuito: str, ruta: str = ARCHIVO, semilla: int = 97):
    """
    Lo acumulado, en el esquema de `tenis_fuentes.COLUMNAS`.

    El ganador se reparte entre `Player_1` y `Player_2` de forma
    pseudoaleatoria pero DETERMINISTA (semilla fija → dos cargas del mismo CSV
    dan lo mismo). No es paranoia: BetExplorer coloca al ganador en la primera
    columna el **41,5 %** de las veces (n=118), y aunque eso esté dentro de lo
    que el azar explica, el histórico donde esto se vuelca ya tiene 566.860
    filas repartidas al 50 % por la misma razón. Dejar que una fuente nueva
    llegue con CUALQUIER sesgo de posición es justo el fallo de la v96, y
    cuesta una línea evitarlo.
    """
    import numpy as np
    import pandas as pd

    filas = [f for f in _leer(ruta)
             if f.get('circuito') == _CIRCUITO_DE.get(circuito)]
    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame(filas)
    rng = np.random.default_rng(semilla + len(df))
    primero_gana = rng.random(len(df)) < 0.5

    gan = df['ganador'].to_numpy()
    j1, j2 = df['jugador_1'].to_numpy(), df['jugador_2'].to_numpy()
    per = np.where(gan == j1, j2, j1)

    out = pd.DataFrame(index=df.index)
    out['Tournament'] = df['torneo']
    out['Date'] = pd.to_datetime(df['fecha'], errors='coerce')
    out['Series'] = df['nivel']
    out['Court'] = 'Outdoor'
    out['Surface'] = (df['superficie'].astype(str).str.strip().str.title()
                      .replace({'': 'Hard', 'Nan': 'Hard'}))
    out['Round'] = ''
    out['Best of'] = 3
    out['Player_1'] = np.where(primero_gana, gan, per)
    out['Player_2'] = np.where(primero_gana, per, gan)
    out['Winner'] = gan
    for c in ('Rank_1', 'Rank_2', 'Pts_1', 'Pts_2', 'Odd_1', 'Odd_2'):
        out[c] = np.nan
    # El marcador viaja CON la columna. `sets_1`/`sets_2` del CSV están en el
    # orden de BetExplorer; tras barajar hay que reexpresarlos desde el punto
    # de vista de `Player_1`, o el fichero diría «Player_1 gana» con un
    # marcador de 0-2 y cualquiera que lo lea sacará el ganador equivocado.
    sets1 = pd.to_numeric(df['sets_1'], errors='coerce').to_numpy()
    sets2 = pd.to_numeric(df['sets_2'], errors='coerce').to_numpy()
    sets_gan = np.maximum(sets1, sets2)
    sets_per = np.minimum(sets1, sets2)
    out['Score'] = np.where(primero_gana,
                            [f'{a}-{b}' for a, b in zip(sets_gan, sets_per)],
                            [f'{b}-{a}' for a, b in zip(sets_gan, sets_per)])
    out['Comment'] = 'Completed'
    out['Categoria'] = _CATEGORIA.get(_CIRCUITO_DE.get(circuito), 'itf_m')
    out['Fuente'] = 'itf_vivo'
    return out.dropna(subset=['Date', 'Player_1', 'Player_2'])


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    print(json.dumps(acumular(dry_run=a.dry_run), ensure_ascii=False, indent=1))
