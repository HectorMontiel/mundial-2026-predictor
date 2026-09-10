#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v188/v189 — VIGILA QUE LOS DATOS QUE APRENDEN NO SE QUEDEN PARADOS.

POR QUÉ EXISTE, y son tres fallos del mismo día
------------------------------------------------
Todos silenciosos, todos con el workflow en verde, y ninguno lo cazó nada:

    historico_champions.csv    parado desde el 2026-07-14   (2 meses)
    pick_ledger_total.csv      parado desde el 2026-07-29   (6 semanas)
    umbrales_capa1.json        parado desde el 2026-07-28   (6 semanas)
    stats_espn/                parado desde el 2026-08-22   (3 semanas)

El de la Champions salió porque el usuario dijo «sólo veo un partido». Los otros
tres, porque preguntó «¿qué has hecho con los resultados de los partidos que ya
acabaron?». Sin esas dos preguntas seguirían parados.

Lo que tienen en común no es la causa —una fuente de pago caducada, un `git add`
con un path ignorado, un `\\n` literal— sino que **nada miraba la fecha**. Un
fichero que deja de actualizarse no da error: simplemente se queda quieto, y
todo lo que se calcula encima sigue funcionando y devolviendo lo de antes.

QUÉ COMPRUEBA
-------------
Para cada pieza que debería refrescarse sola, cuántos días lleva sin cambiar y
cuántos se le toleran. El plazo sale de cada cuánto corre quien la escribe:

  · lo que toca el bot nocturno, 3 días de margen (por si falla una noche);
  · lo que toca la recalibración semanal, 10 días;
  · los históricos de las ligas activas, 10 días (hay parones y receso).

NO FALLA POR UN DÍA MALO. El umbral es generoso a propósito: esto no está para
avisar de que anoche hubo un 503, sino de que algo lleva SEMANAS sin moverse.

CÓMO SE MIDE LA EDAD — v189: PREGUNTÁNDOLE AL CONTENIDO
-------------------------------------------------------
La v188 usaba la fecha del último COMMIT que tocó cada fichero, porque el
`mtime` no vale —un `git clone` los pone todos a la hora del clon—.

**Y ahí este check se volvió un check que no podía fallar.** En el runner,
`actions/checkout@v4` clona con `fetch-depth: 1`: un solo commit. Con un commit
en el historial, `git log -1 -- <lo que sea>` devuelve ESE commit para todo, o
sea «0 días» para todo. El vigilante informó **«PARADOS: 0, al día: 73»** en el
único sitio donde tenía que avisar, la misma semana en que cuatro ficheros
llevaban seis semanas congelados.

Subir el `fetch-depth` no era la salida: este `.git` pesa **16 GB** —años de
CSV grandes commiteados a diario—, así que un clon completo no cabe en el
runner.

La salida es no depender de git: **cada fichero lleva dentro la fecha de su
dato más reciente**, y esa fecha es además la que de verdad importa. Un ledger
recommiteado con las mismas filas de julio no está fresco por mucho que su
commit sea de hoy —es exactamente lo que pasaba—, y un histórico dice hasta qué
día llega mirando su columna `date`.

Donde un fichero no lleva fecha dentro se cae a la de commit, y si el clon es
superficial se declara **«sin evaluar»**. No saber nunca se informa como «al
día»: ése fue el fallo.
"""
import io
import json
import logging
import os
import subprocess
import sys
from typing import Callable, Dict, List, Optional

logger = logging.getLogger('frescura_datos')


# ---------------------------------------------------------------------------
# LECTORES: cómo saber, mirando dentro, hasta qué día llega cada fichero.
# Devuelven 'AAAA-MM-DD' o None si el fichero no lleva esa fecha dentro.
# ---------------------------------------------------------------------------
def _fecha_json(campo: str = 'generado') -> Callable[[str], Optional[str]]:
    def leer(ruta: str) -> Optional[str]:
        try:
            with io.open(ruta, encoding='utf-8') as f:
                d = json.load(f)
            v = d.get(campo) if isinstance(d, dict) else None
            return str(v)[:10] if v else None
        except Exception as e:
            logger.debug('[frescura] json %s: %s', ruta, e)
            return None
    return leer


def _fecha_csv(*columnas: str) -> Callable[[str], Optional[str]]:
    """
    Se pasan varios nombres porque no todos los CSV del proyecto llaman igual a
    su columna de fecha: los históricos usan `date` y el fondo ESPN usa `fecha`.
    Con un solo nombre, el fondo caía a la fecha de commit sin decir nada —y el
    fondo es justo uno de los tres que se habían quedado congelados—.
    """
    def leer(ruta: str) -> Optional[str]:
        import pandas as pd
        for columna in columnas:
            try:
                d = pd.read_csv(ruta, usecols=[columna], low_memory=False)
                m = pd.to_datetime(d[columna], errors='coerce').max()
                if not pd.isna(m):
                    return str(m)[:10]
            except Exception as e:
                logger.debug('[frescura] csv %s (%s): %s', ruta, columna, e)
        return None
    return leer


def _fecha_pronosticos(ruta: str) -> Optional[str]:
    """`pronosticos_emitidos.json` no tiene cabecera: la fecha va por entrada."""
    try:
        with io.open(ruta, encoding='utf-8') as f:
            d = json.load(f)
        fechas = [str(v.get('fecha'))[:10] for v in d.values()
                  if isinstance(v, dict) and v.get('fecha')]
        return max(fechas) if fechas else None
    except Exception as e:
        logger.debug('[frescura] pronosticos: %s', e)
        return None


def _fecha_rosters(ruta: str):
    """
    `goleadores_cache.json` no lleva fecha de cabecera: cada entrada trae su
    propio `ts`. La mas reciente contesta lo unico que se pregunta aqui, que es
    si algo lo ha refrescado ultimamente.

    Se vigila porque su bot —`precalcular_rosters.yml`, diario— **no ha
    commiteado nunca**, ni una sola vez, y nada lo decia. Sin esta cache la app
    pide los rosters a ESPN en cada carga y ESPN devuelve 403 desde las IPs de
    Streamlit Cloud.
    """
    try:
        import datetime as dt
        with io.open(ruta, encoding='utf-8') as f:
            d = json.load(f)
        ts = [v.get('ts') for v in d.values()
              if isinstance(v, dict) and v.get('ts')]
        if not ts:
            return None
        return dt.date.fromtimestamp(max(ts)).isoformat()
    except Exception as e:
        logger.debug('[frescura] rosters: %s', e)
        return None


# fichero -> (días tolerados, quién debería tocarlo, cómo leer su fecha)
VIGILADOS = {
    # ---- lo que escribe el bot nocturno -------------------------------
    'pronosticos_emitidos.json': (3, 'bot nocturno', _fecha_pronosticos),
    'predicciones_dia.json': (3, 'bot nocturno', _fecha_json()),
    'mercado_dia.json': (3, 'bot nocturno', _fecha_json()),
    # El bot de rosters corre a diario y NO ha commiteado nunca.
    'goleadores_cache.json': (5, 'precalcular_rosters.yml (diario)',
                              _fecha_rosters),
    # ---- lo que escribe la recalibración semanal ----------------------
    # El ledger se mira por la fecha del ÚLTIMO PARTIDO que contiene, que es
    # justo lo que se le pide: haber aprendido de lo que ya se jugó.
    'pick_ledger_total.csv': (10, 'recalibrar.yml (semanal)',
                              _fecha_csv('fecha')),
    'umbrales_capa1.json': (10, 'recalibrar.yml (semanal)', _fecha_json()),
    # Las metas de los dos ledgers de origen. Pesan nada y llevan dentro su
    # `generado`, que es lo que senala CUAL de los dos se quedo atras: el
    # total puede parecer reciente y estar hecho de un futbol de julio.
    '_v75_pick_ledger.json': (10, 'recalibrar.yml (ledger de futbol)',
                              _fecha_json()),
    '_v78_ledger_deportes.json': (10, 'recalibrar.yml (ledger de deportes)',
                                  _fecha_json()),
    # Éste no lleva fecha dentro; se cae a la de commit.
    'calibracion_confianza.json': (10, 'recalibrar.yml (semanal)', None),
    'edge_map.json': (10, 'recalibrar.yml (semanal)', _fecha_json()),
    'calibracion_mercado.json': (10, 'recalibrar.yml (semanal)', _fecha_json()),
    # ---- la NFL, que se quedo parada 4 semanas sin que nada lo dijera ---
    # Su historico solo lo construia una funcion llamada a mano y se congelo
    # en pretemporada. Se mide por la fecha del ultimo partido que contiene.
    'historico_nfl.csv': (10, 'retrain_leagues.yml (diario)',
                          _fecha_csv('fecha', 'date')),
    # ---- el fondo de estadísticas -------------------------------------
    'stats_espn/laliga.csv.gz': (10, 'recalibrar.yml (fondo ESPN)',
                                 _fecha_csv('date', 'fecha')),
    'stats_espn/premier.csv.gz': (10, 'recalibrar.yml (fondo ESPN)',
                                  _fecha_csv('date', 'fecha')),
}

# Y los históricos de las competiciones encendidas, que los toca el
# reentrenamiento diario. Se comprueban aparte porque son muchos y la lista
# sale de `config`, no escrita a mano — una lista a mano se queda corta sola.
DIAS_HISTORICO = 10


def _es_clon_superficial() -> bool:
    """
    Un `actions/checkout@v4` sin `fetch-depth` deja UN solo commit, y entonces
    `git log -1 -- <fichero>` devuelve ese commit para todos: cero días para
    todo. Saberlo es lo que separa «al día» de «no puedo saberlo».
    """
    try:
        r = subprocess.run(['git', 'rev-parse', '--is-shallow-repository'],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or '').strip().lower() == 'true'
    except Exception as e:
        logger.debug('[frescura] rev-parse: %s', e)
        return False


def _dias_desde_el_ultimo_commit(ruta: str) -> Optional[int]:
    """Días desde el último commit que tocó el fichero. `None` si no se sabe."""
    if not os.path.exists(ruta):
        return None
    try:
        salida = subprocess.run(
            ['git', 'log', '-1', '--format=%ct', '--', ruta],
            capture_output=True, text=True, timeout=30)
        marca = (salida.stdout or '').strip()
        if not marca:
            return None
        import time
        return int((time.time() - float(marca)) / 86400)
    except Exception as e:
        logger.debug('[frescura] git log de %s: %s', ruta, e)
        return None


def _dias_desde(fecha: str) -> Optional[int]:
    try:
        import datetime as dt
        d = dt.date.fromisoformat(str(fecha)[:10])
        return (dt.date.today() - d).days
    except Exception:
        return None


def _historicos_de_ligas_activas() -> List[str]:
    try:
        import config
    except Exception:
        return []
    salida = []
    for clave, cfg in config.LEAGUES.items():
        if not cfg.get('disponible'):
            continue
        ruta = 'historico_%s.csv' % clave
        if os.path.exists(ruta):
            salida.append(ruta)
    return sorted(salida)


def revisar() -> Dict:
    """`{'ok': [...], 'viejos': [...], 'sin_datos': [...]}`."""
    ok, viejos, sin_datos = [], [], []
    superficial = _es_clon_superficial()

    def mira(ruta, dias_max, quien, lector=None):
        if not os.path.exists(ruta):
            sin_datos.append({'fichero': ruta, 'motivo': 'no existe'})
            return
        d, via, hasta = None, None, None
        if lector is not None:
            hasta = lector(ruta)
            if hasta:
                d, via = _dias_desde(hasta), 'contenido'
        if d is None:
            # Sin fecha dentro: sólo queda git, y en un clon superficial git
            # miente. Antes que decir «al día» sin saberlo, no se dice nada.
            if superficial:
                sin_datos.append({
                    'fichero': ruta,
                    'motivo': 'sin fecha dentro y el clon es superficial: '
                              'no se puede evaluar'})
                return
            d, via = _dias_desde_el_ultimo_commit(ruta), 'commit'
        if d is None:
            sin_datos.append({'fichero': ruta, 'motivo': 'sin fecha ni commits'})
            return
        fila = {'fichero': ruta, 'dias': d, 'tolerado': dias_max,
                'quien': quien, 'via': via}
        if hasta:
            fila['hasta'] = hasta
        (viejos if d > dias_max else ok).append(fila)

    for ruta, cfg in VIGILADOS.items():
        dias, quien = cfg[0], cfg[1]
        lector = cfg[2] if len(cfg) > 2 else None
        mira(ruta, dias, quien, lector)
    for ruta in _historicos_de_ligas_activas():
        mira(ruta, DIAS_HISTORICO, 'retrain_leagues.yml (diario)',
             _fecha_csv('date', 'fecha'))

    # UNA COMPETICION EN RECESO NO ESTA ROTA, Y CONFUNDIRLAS ARRUINA EL CHECK.
    #
    # La primera version marcó como paradas la Europa League, la Conference, la
    # FA Cup, la A-League australiana y la ISL india. Ninguna lo estaba: las
    # cinco terminaron su temporada en mayo y la siguiente no ha empezado. ESPN
    # devuelve para la Europa League exactamente hasta el 2026-05-20, que es su
    # final —Freiburg 0-3 Aston Villa—, o sea que el histórico está completo.
    #
    # Un check con cinco falsos positivos se ignora a la tercera semana, y
    # entonces no avisa del que sí importa. Así que a las sospechosas se les
    # pregunta si les FALTA algún partido ya jugado.
    #
    # Sólo se consulta a las que ya salieron marcadas —cinco peticiones, no
    # sesenta— y si la consulta falla se deja como estaba: no saber no es
    # motivo para callar una alarma.
    en_receso = []
    if viejos:
        restantes = []
        for f in viejos:
            clave = _clave_de_historico(f['fichero'])
            if clave and _en_receso(clave):
                f['motivo'] = 'en receso: sin partidos próximos'
                en_receso.append(f)
            else:
                restantes.append(f)
        viejos = restantes

    viejos.sort(key=lambda x: -x['dias'])
    return {'ok': ok, 'viejos': viejos, 'sin_datos': sin_datos,
            'en_receso': en_receso, 'clon_superficial': superficial}


def _clave_de_historico(ruta: str) -> Optional[str]:
    base = os.path.basename(str(ruta))
    if base.startswith('historico_') and base.endswith('.csv'):
        return base[len('historico_'):-4]
    return None


def _en_receso(clave: str) -> bool:
    """
    Si a esta competición no le FALTA ningún partido ya jugado.

    LA PREGUNTA CORRECTA NO ES «¿tiene partidos próximos?», y la primera versión
    la hizo mal. La Europa League tiene partidos próximos —su fase liga empieza
    el 24 de septiembre— y aun así su histórico se para en mayo, porque de la
    temporada nueva **todavía no se ha jugado ninguno**. No le falta nada.

    Lo que de verdad delata un histórico parado es que existan resultados más
    recientes que su última fecha y no estén dentro. Eso es lo que se mira.

    Ante la duda —la fuente no responde, el fichero no se puede leer— devuelve
    False: no saber no es motivo para callar una alarma.
    """
    try:
        import pandas as pd
        import fixtures_espn as fe
        ruta = 'historico_%s.csv' % clave
        d = pd.read_csv(ruta, usecols=['date'], low_memory=False)
        ultima = pd.to_datetime(d['date'], errors='coerce').max()
        if pd.isna(ultima):
            return False
        # Partidos de los últimos 30 días, jugados o no.
        for f in (fe.fixtures_liga(clave, dias=30) or []):
            try:
                cuando = pd.to_datetime(f.get('fecha') or f.get('inicio'),
                                        errors='coerce', utc=True)
            except Exception:
                continue
            if pd.isna(cuando):
                continue
            jugado = (f.get('home_goals') is not None
                      or str(f.get('estado', '')).lower() in
                      ('post', 'final', 'finalizado'))
            if jugado and cuando.tz_localize(None) > ultima:
                return False          # le falta un partido jugado: SÍ está roto
        return True
    except Exception as e:
        logger.debug('[frescura] no se pudo mirar %s: %s', clave, e)
        return False


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    r = revisar()
    print('frescura de los datos que aprenden')
    if r.get('clon_superficial'):
        print('  (clon superficial: lo que no lleva fecha dentro no se evalúa)')
    print('  al día:      %d' % len(r['ok']))
    print('  PARADOS:     %d' % len(r['viejos']))
    print('  en receso:   %d  (sin partidos próximos: no es un fallo)'
          % len(r.get('en_receso') or []))
    print('  sin evaluar: %d' % len(r['sin_datos']))
    for f in (r.get('en_receso') or []):
        print('     · %-38s %3d días · %s'
              % (f['fichero'], f['dias'], f.get('motivo', '')))
    for f in r['sin_datos']:
        print('     · %-38s %s' % (f['fichero'], f.get('motivo', '')))
    if r['viejos']:
        print()
        print('  %-38s %6s %9s %-9s %s'
              % ('fichero', 'días', 'tolerado', 'medido por', 'quién'))
        for f in r['viejos']:
            print('  %-38s %6d %9d %-9s %s'
                  % (f['fichero'], f['dias'], f['tolerado'],
                     f.get('via', '?'), f['quien']))
    with io.open('frescura_datos.json', 'w', encoding='utf-8',
                 newline='\n') as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1)
    print()
    print('escrito frescura_datos.json')
    # 1 si hay algo parado, para que un workflow lo pueda mirar
    return 1 if r['viejos'] else 0


if __name__ == '__main__':
    sys.exit(main())
