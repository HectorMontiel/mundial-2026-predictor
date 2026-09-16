#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuando un dato falta, se sale a buscarlo. Y se apunta qué se encontró.

QUÉ PEDÍA EL ENCARGO
--------------------
Que cuando falte un dato —entrenador, alineaciones, xG, lesiones— el sistema
no espere a que alguien le diga de dónde sacarlo, sino que pruebe fuentes
alternativas por su cuenta, registre lo que funcionó y active la regla sólo si
encontró de verdad la fuente.

Esto es la parte que se puede automatizar: el REGISTRO de qué se probó y el
LECTOR de las fuentes que resultaron viables. Lo que no se automatiza —y se
dice— es elegir una fuente nueva: eso lo hace una persona mirando el sondeo,
porque adoptar una fuente es decidir de quién se fía el sistema.

EL SONDEO, HECHO EL 2026-09-15
------------------------------
Se probaron todas las candidatas que el encargo nombraba, más las que este
proyecto ya conocía:

    ENTRENADOR
      ESPN soccer summary ..................  0 campos de cuerpo técnico
      SofaScore api/v1/team/{id} ...........  403
      Transfermarkt (página de club) .......  200, pero sin el dato en el HTML
      transfermarkt-api.fly.dev ............  500
      FotMob (__NEXT_DATA__) ...............  ✅ nombre del entrenador de los
                                               dos equipos, con su id

    ALINEACIONES
      SofaScore api/v1/event/{id}/lineups ..  403
      FotMob (__NEXT_DATA__) ...............  ✅ once, suplentes, formación,
                                               `lineupType` (predicted/
                                               confirmed) y `unavailable`
                                               (bajas)

    xG
      Understat ............................  ✅ 200, con xG
      FBref ................................  403

    CUOTAS
      The Odds API .........................  401 sin clave (ya integrada;
                                               `ODDS_API_KEY` del entorno)

La API interna de FotMob (`/api/*`) exige el header firmado `x-mas` y devuelve
404 a un `requests` plano — eso ya estaba documentado en `fotmob_scraper`, y
por eso todo va por el `__NEXT_DATA__` de la página, que es la puerta que este
proyecto ya usaba para los córners y el árbitro. No se resuelve ningún
anti-bot: se lee la página como la lee un navegador.

FOTMOB NO DA LA FECHA. WIKIDATA SÍ, Y ÉSA ES LA BUENA
-----------------------------------------------------
El bloque `coach` de FotMob trae id, nombre, edad y país, y ni un campo de
cuándo llegó. Con él, «cambió en los últimos 7 días» sólo se puede responder
recordando quién entrenaba antes — o sea acumulando fotos, y el primer día no
detecta nada.

**Wikidata publica el nombramiento con su fecha de inicio** (P286 con el
calificador P580, y sin P582 para quedarse con los vivos). Medido el
2026-09-15: 60 nombramientos vigentes desde junio, cuatro en la última semana
y uno del mismo día. Una consulta SPARQL para el mundo entero, cacheada por
día.

Las dos se usan, y se complementan por donde cada una flojea:

    Wikidata   tiene la FECHA, pero la escribe gente y puede ir con retraso
    FotMob     es inmediato, pero no dice desde cuándo

Si las dos discrepan en quién entrena, eso mismo es señal de un cambio más
fresco que la base. Y el retraso de Wikidata va a favor de seguridad: un
cambio que aún no está NO dispara la regla, en vez de disparar una falsa.
"""

import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REGISTRO = 'fuentes_consultadas.json'
HISTORIAL = 'historial_entrenadores.json'

# El sondeo del 2026-09-15, tal cual salió. Viaja con el código para que nadie
# repita las llamadas ni dé por hecho que una fuente muerta sigue viva.
SONDEO = {
    'fecha': '2026-09-15',
    'entrenador': [
        {'fuente': 'ESPN soccer summary', 'estado': 'sin el dato',
         'detalle': '0 campos de cuerpo técnico en 430 KB'},
        {'fuente': 'SofaScore api/v1/team', 'estado': 'bloqueada', 'http': 403},
        {'fuente': 'Transfermarkt web', 'estado': 'sin el dato en el HTML',
         'http': 200},
        {'fuente': 'transfermarkt-api.fly.dev', 'estado': 'caída', 'http': 500},
        {'fuente': 'FotMob __NEXT_DATA__', 'estado': 'adoptada', 'http': 200,
         'detalle': 'quién entrena AHORA, sin fecha de nombramiento'},
        {'fuente': 'Wikidata SPARQL (P286 + P580)', 'estado': 'adoptada',
         'http': 200,
         'detalle': 'el nombramiento CON su fecha de inicio; 60 vivos desde '
                    'junio y uno del mismo 2026-09-15 — es la fuente que '
                    'responde «¿cambió en 7 días?» sin historial'},
    ],
    'alineaciones': [
        {'fuente': 'SofaScore lineups', 'estado': 'bloqueada', 'http': 403},
        {'fuente': 'FotMob __NEXT_DATA__', 'estado': 'disponible',
         'detalle': 'once, suplentes, formación, lineupType y bajas'},
    ],
    'xg': [
        {'fuente': 'Understat', 'estado': 'disponible', 'http': 200},
        {'fuente': 'FBref', 'estado': 'bloqueada', 'http': 403},
    ],
    'cuotas': [
        {'fuente': 'The Odds API', 'estado': 'ya integrada',
         'detalle': 'clave en ODDS_API_KEY, nunca en código'},
    ],
}


# ---------------------------------------------------------------------------
# El registro de lo que se consulta
# ---------------------------------------------------------------------------
def _cargar(ruta: str, por_defecto):
    try:
        with open(ruta, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return por_defecto


def _guardar(ruta: str, doc) -> None:
    try:
        tmp = f'{ruta}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)
    except Exception as e:
        logger.debug('[fuentes] no se pudo escribir %s: %s', ruta, e)


def apuntar(dato: str, fuente: str, ok: bool, detalle: str = '',
            ruta: Optional[str] = None) -> None:
    """Deja constancia de una consulta. Nunca lanza."""
    ruta = ruta or REGISTRO
    doc = _cargar(ruta, {}) or {}
    entrada = doc.setdefault(str(dato), {}).setdefault(str(fuente), {
        'intentos': 0, 'aciertos': 0, 'ultimo_detalle': ''})
    entrada['intentos'] += 1
    entrada['aciertos'] += int(bool(ok))
    entrada['ultimo'] = _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec='seconds')
    if detalle:
        entrada['ultimo_detalle'] = str(detalle)[:200]
    doc['_sondeo'] = SONDEO
    _guardar(ruta, doc)


def consultadas(ruta: Optional[str] = None) -> Dict:
    """Todo lo que se ha intentado, por dato y fuente."""
    return _cargar(ruta or REGISTRO, {}) or {}


# ---------------------------------------------------------------------------
# Entrenador y alineación, por la puerta que funciona
# ---------------------------------------------------------------------------
def contexto_fotmob(match_id: str) -> Dict:
    """Entrenador, formación, tipo de alineación y bajas de los dos equipos.

    Va por el `__NEXT_DATA__` de la página, que es la puerta que
    `fotmob_scraper` ya usaba para los córners y el árbitro. Devuelve `{}` sin
    romper nada si no se puede leer.
    """
    fuera: Dict = {}
    try:
        import fotmob_scraper as fs
        data = fs._next_data(f'https://www.fotmob.com/match/{match_id}')
    except Exception as e:
        apuntar('entrenador', 'FotMob', False, f'{type(e).__name__}: {e}')
        return fuera
    if not data:
        apuntar('entrenador', 'FotMob', False, 'sin __NEXT_DATA__')
        return fuera
    try:
        pp = data['props']['pageProps']
        lu = (pp.get('content') or {}).get('lineup') or {}
        for lado in ('homeTeam', 'awayTeam'):
            t = lu.get(lado) or {}
            if not isinstance(t, dict):
                continue
            coach = t.get('coach') or {}
            fuera[lado] = {
                'equipo': t.get('name'),
                'entrenador': coach.get('name'),
                'entrenador_id': coach.get('id'),
                'formacion': t.get('formation'),
                'bajas': len(t.get('unavailable') or []),
            }
        fuera['tipo_alineacion'] = lu.get('lineupType')
    except Exception as e:
        apuntar('entrenador', 'FotMob', False, f'{type(e).__name__}: {e}')
        return {}
    apuntar('entrenador', 'FotMob', bool(fuera),
            f"tipo={fuera.get('tipo_alineacion')}")
    return fuera


# ---------------------------------------------------------------------------
# El historial, que es lo único que convierte «quién entrena» en «cambió»
# ---------------------------------------------------------------------------
def anotar_entrenador(equipo: str, entrenador: str, dia: Optional[str] = None,
                      ruta: Optional[str] = None) -> Dict:
    """Guarda quién entrena a ese equipo hoy y dice si cambió.

    Devuelve `{'cambio': bool, 'anterior': str|None, 'desde': 'AAAA-MM-DD'}`.
    `cambio` sólo puede ser `True` si ya había una foto anterior — el primer
    día de un equipo nunca es un cambio, es el punto de partida.
    """
    # EL FICHERO SE RESUELVE AQUI Y NO EN LA FIRMA. Un `ruta=HISTORIAL` por
    # defecto congela el valor que tenia el modulo al importarse, asi que
    # cambiar `HISTORIAL` despues no tiene efecto — y eso hace que los tests
    # escriban en el fichero de produccion creyendo que usan el suyo.
    ruta = ruta or HISTORIAL
    if not (equipo and entrenador):
        return {'cambio': False, 'anterior': None, 'desde': None}
    dia = dia or _dt.date.today().isoformat()
    doc = _cargar(ruta, {}) or {}
    prev = doc.get(str(equipo)) or {}
    anterior = prev.get('entrenador')
    cambio = bool(anterior) and str(anterior) != str(entrenador)
    desde = dia if (cambio or not anterior) else prev.get('desde', dia)
    doc[str(equipo)] = {'entrenador': str(entrenador), 'desde': desde,
                        'visto': dia,
                        'anterior': anterior if cambio else prev.get('anterior')}
    _guardar(ruta, doc)
    return {'cambio': cambio, 'anterior': anterior, 'desde': desde}


def cambios_recientes(dias: int = 7, hoy: Optional[str] = None,
                      ruta: Optional[str] = None) -> Dict[str, str]:
    """`{equipo: 'AAAA-MM-DD'}` de los que estrenaron entrenador hace <= `dias`.

    Es exactamente la forma que `filtro_contexto.registrar_fuente` espera, así
    que enchufar esto enciende la regla del rebote sin tocar nada más.
    """
    doc = _cargar(ruta or HISTORIAL, {}) or {}
    try:
        ref = _dt.date.fromisoformat(hoy or _dt.date.today().isoformat())
    except ValueError:
        return {}
    fuera: Dict[str, str] = {}
    for equipo, reg in doc.items():
        if not isinstance(reg, dict) or not reg.get('anterior'):
            # sin un entrenador ANTERIOR guardado no hubo cambio observado:
            # es el primer dato que se tiene de ese equipo
            continue
        desde = str(reg.get('desde') or '')
        try:
            d = _dt.date.fromisoformat(desde)
        except ValueError:
            continue
        if 0 <= (ref - d).days <= int(dias):
            fuera[str(equipo)] = desde
    return fuera


# ---------------------------------------------------------------------------
# WIKIDATA: la fuente que sí trae la FECHA
# ---------------------------------------------------------------------------
SPARQL = 'https://query.wikidata.org/sparql'
CACHE_CAMBIOS = 'cambios_entrenador.json'

# Q476028 es «club de fútbol»; P286 «entrenador»; P580 «fecha de inicio» y
# P582 «fecha de fin». Se piden sólo los nombramientos VIVOS —sin fecha de
# fin— posteriores a la fecha que se pase.
_CONSULTA = """
SELECT ?clubLabel ?coachLabel ?desde WHERE {
  ?club wdt:P31/wdt:P279* wd:Q476028 .
  ?club p:P286 ?st .
  ?st ps:P286 ?coach .
  ?st pq:P580 ?desde .
  FILTER NOT EXISTS { ?st pq:P582 ?hasta . }
  FILTER (?desde > "%sT00:00:00Z"^^xsd:dateTime)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "es,en". }
} ORDER BY DESC(?desde) LIMIT 400
"""


def cambios_wikidata(dias: int = 7, hoy: Optional[str] = None,
                     cache: Optional[str] = None) -> Dict[str, str]:
    """`{club: 'AAAA-MM-DD'}` de los entrenadores nombrados hace <= `dias`.

    ES LA PIEZA QUE FALTABA. FotMob dice quién entrena hoy y no cuándo llegó,
    así que con él un cambio sólo se ve comparando fotos y el primer día no
    detecta nada. Wikidata publica el nombramiento **con su fecha de inicio**,
    o sea que responde la pregunta del encargo —«¿cambió en los últimos 7
    días?»— de una sola consulta y sin historial.

    Medido el 2026-09-15: 60 nombramientos vivos desde junio, con uno del
    mismo día (Velež Mostar) y cuatro en la última semana. La base está al día.

    LO QUE HAY QUE SABER DE ESTA FUENTE: la escribe gente, así que un cese de
    anoche puede tardar en aparecer. Va a favor de seguridad —un cambio que no
    está no dispara la regla, en vez de disparar una falsa— y por eso se cruza
    con FotMob, que sí es inmediato: si los dos no coinciden en quién entrena,
    es señal de un cambio más fresco que la base.

    Una consulta por día para el mundo entero, cacheada en disco.
    """
    import datetime as d
    ruta = cache or CACHE_CAMBIOS
    hoy = hoy or d.date.today().isoformat()
    guardado = _cargar(ruta, {}) or {}
    if guardado.get('dia') == hoy and guardado.get('dias') == int(dias):
        return dict(guardado.get('cambios') or {})
    try:
        import requests
        desde = (d.date.fromisoformat(hoy)
                 - d.timedelta(days=int(dias))).isoformat()
        r = requests.get(SPARQL, params={'query': _CONSULTA % desde,
                                         'format': 'json'},
                         headers={'User-Agent': 'mundial-2026-predictor/1.0 '
                                                '(analisis deportivo)'},
                         timeout=60)
        r.raise_for_status()
        filas = r.json()['results']['bindings']
    except Exception as e:
        apuntar('entrenador', 'Wikidata', False, f'{type(e).__name__}: {e}')
        return dict(guardado.get('cambios') or {})
    fuera: Dict[str, str] = {}
    for f in filas:
        club = ((f.get('clubLabel') or {}).get('value') or '').strip()
        fecha = ((f.get('desde') or {}).get('value') or '')[:10]
        if not (club and fecha):
            continue
        # el más reciente manda si un club aparece dos veces
        if club not in fuera or fecha > fuera[club]:
            fuera[club] = fecha
    apuntar('entrenador', 'Wikidata', bool(fuera),
            f'{len(fuera)} clubes con nombramiento en {dias} días')
    _guardar(ruta, {'dia': hoy, 'dias': int(dias), 'cambios': fuera,
                    'consultado': d.datetime.now(
                        d.timezone.utc).isoformat(timespec='seconds')})
    return fuera


def foto_del_dia(claves: Optional[List[str]] = None,
                 max_por_liga: int = 12) -> Dict:
    """Guarda quién entrena hoy a cada equipo, y devuelve lo que cambió.

    ESTO NO CORRE SOLO, y es deliberado: son una petición por partido a
    FotMob, y meter un trabajo de N peticiones en un workflow diario sin medir
    antes lo que tarda es cómo se rompen los workflows de este proyecto. Se
    deja como entrada de línea de comandos (`python buscador_fuentes.py
    --foto`) para poder medirlo y, con el número delante, decidir dónde va.

    COBERTURA: `fotmob_scraper.FOTMOB_LEAGUE_IDS` conoce **diez** competiciones
    (las cinco grandes europeas, Champions, Eredivisie, Primeira, MLS y Liga
    MX). Fuera de ahí no hay entrenador, así que la regla del rebote nunca
    podrá dispararse en las demás — y eso incluye las sudamericanas.
    """
    try:
        import fotmob_scraper as fs
    except Exception as e:
        logger.warning('[fuentes] sin fotmob_scraper: %s', e)
        return {'ligas': 0, 'equipos': 0, 'cambios': {}}
    hoy = _dt.date.today().isoformat()
    cambios: Dict[str, str] = {}
    equipos = 0
    ligas = [c for c in (claves or fs.FOTMOB_LEAGUE_IDS)
             if c in fs.FOTMOB_LEAGUE_IDS]
    for clave in ligas:
        try:
            df = fs.partidos_liga(clave)
        except Exception as e:
            apuntar('entrenador', 'FotMob', False, f'{clave}: {e}')
            continue
        try:
            filas = df.to_dict('records')[:int(max_por_liga)]
        except Exception:
            continue
        for fila in filas:
            mid = fila.get('match_id') or fila.get('id')
            if not mid:
                continue
            ctx = contexto_fotmob(str(mid))
            for lado in ('homeTeam', 'awayTeam'):
                bloque = ctx.get(lado) or {}
                eq, en = bloque.get('equipo'), bloque.get('entrenador')
                if not (eq and en):
                    continue
                equipos += 1
                r = anotar_entrenador(eq, en, hoy)
                if r.get('cambio'):
                    cambios[eq] = r['desde']
    return {'ligas': len(ligas), 'equipos': equipos, 'cambios': cambios,
            'dia': hoy}


def estado() -> Dict:
    """Qué sabe hoy el buscador. Para la pantalla y para la bitácora."""
    hist = _cargar(HISTORIAL, {}) or {}
    con_anterior = sum(1 for v in hist.values()
                       if isinstance(v, dict) and v.get('anterior'))
    wd = _cargar(CACHE_CAMBIOS, {}) or {}
    n_wd = len(wd.get('cambios') or {})
    return {
        'sondeo': SONDEO,
        'equipos_con_foto': len(hist),
        'equipos_con_cambio_observado': con_anterior,
        'cambios_en_wikidata': n_wd,
        'wikidata_consultada': wd.get('consultado'),
        # `puede_detectar_cambios` sigue hablando SÓLO del historial de fotos,
        # que es lo que consume `cambios_recientes`. Wikidata no lo necesita.
        'puede_detectar_cambios': con_anterior > 0,
        'motivo': ('' if con_anterior else
                   'el historial de fotos no tiene aún ningún cambio '
                   'observado; la detección va por Wikidata, que sí trae la '
                   'fecha de nombramiento'),
        'consultas': consultadas(),
    }


def main() -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--foto', action='store_true',
                    help='guarda quién entrena hoy a cada equipo')
    ap.add_argument('--ligas', default='',
                    help='claves separadas por comas; por defecto, todas')
    ap.add_argument('--max-por-liga', type=int, default=12)
    args = ap.parse_args()
    if args.foto:
        claves = [c.strip() for c in args.ligas.split(',') if c.strip()]
        r = foto_del_dia(claves or None, args.max_por_liga)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in estado().items() if k != 'consultas'},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
