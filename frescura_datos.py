#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v188 — VIGILA QUE LOS DATOS QUE APRENDEN NO SE QUEDEN PARADOS.

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

CÓMO SE MIDE LA EDAD, Y POR QUÉ NO POR `mtime`
-----------------------------------------------
La fecha del fichero en disco no vale: un `git clone` los pone todos a la hora
del clon. Se usa la fecha del último COMMIT que tocó cada uno, que es lo que de
verdad dice cuándo cambió su contenido.
"""
import io
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional

logger = logging.getLogger('frescura_datos')

# fichero -> (días tolerados, quién debería tocarlo)
VIGILADOS = {
    # ---- lo que escribe el bot nocturno -------------------------------
    'pronosticos_emitidos.json': (3, 'bot nocturno'),
    'predicciones_dia.json': (3, 'bot nocturno'),
    'mercado_dia.json': (3, 'bot nocturno'),
    # ---- lo que escribe la recalibración semanal ----------------------
    'pick_ledger_total.csv': (10, 'recalibrar.yml (semanal)'),
    'umbrales_capa1.json': (10, 'recalibrar.yml (semanal)'),
    'calibracion_confianza.json': (10, 'recalibrar.yml (semanal)'),
    'edge_map.json': (10, 'recalibrar.yml (semanal)'),
    'calibracion_mercado.json': (10, 'recalibrar.yml (semanal)'),
    # ---- el fondo de estadísticas -------------------------------------
    'stats_espn/laliga.csv.gz': (10, 'recalibrar.yml (fondo ESPN)'),
    'stats_espn/premier.csv.gz': (10, 'recalibrar.yml (fondo ESPN)'),
}

# Y los históricos de las competiciones encendidas, que los toca el
# reentrenamiento diario. Se comprueban aparte porque son muchos y la lista
# sale de `config`, no escrita a mano — una lista a mano se queda corta sola.
DIAS_HISTORICO = 10


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

    def mira(ruta, dias_max, quien):
        d = _dias_desde_el_ultimo_commit(ruta)
        if d is None:
            sin_datos.append({'fichero': ruta, 'motivo': 'no existe o sin commits'})
            return
        fila = {'fichero': ruta, 'dias': d, 'tolerado': dias_max, 'quien': quien}
        (viejos if d > dias_max else ok).append(fila)

    for ruta, (dias, quien) in VIGILADOS.items():
        mira(ruta, dias, quien)
    for ruta in _historicos_de_ligas_activas():
        mira(ruta, DIAS_HISTORICO, 'retrain_leagues.yml (diario)')

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
    # pregunta si tienen partidos próximos: si no los tienen, están en receso.
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
            'en_receso': en_receso}


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
    print('  al día:      %d' % len(r['ok']))
    print('  PARADOS:     %d' % len(r['viejos']))
    print('  en receso:   %d  (sin partidos próximos: no es un fallo)'
          % len(r.get('en_receso') or []))
    print('  sin evaluar: %d' % len(r['sin_datos']))
    for f in (r.get('en_receso') or []):
        print('     · %-38s %3d días · %s'
              % (f['fichero'], f['dias'], f.get('motivo', '')))
    if r['viejos']:
        print()
        print('  %-40s %6s %10s  %s' % ('fichero', 'días', 'tolerado', 'quién'))
        for f in r['viejos']:
            print('  %-40s %6d %10d  %s'
                  % (f['fichero'], f['dias'], f['tolerado'], f['quien']))
    with io.open('frescura_datos.json', 'w', encoding='utf-8',
                 newline='\n') as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1)
    print()
    print('escrito frescura_datos.json')
    # 1 si hay algo parado, para que un workflow lo pueda mirar
    return 1 if r['viejos'] else 0


if __name__ == '__main__':
    sys.exit(main())
