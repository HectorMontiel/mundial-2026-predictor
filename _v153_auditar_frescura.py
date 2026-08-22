#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v153 — ¿QUÉ COMPETICIONES TIENEN EL HISTÓRICO ATRASADO, Y CUÁNTO?

Por qué hace falta medirlo así
------------------------------
La queja era «la J1 no muestra los partidos de la semana pasada». Medido, la J1
**no jugó** del 16 al 20 de agosto: sólo hubo 2 partidos el día 21. O sea que la
mayor parte del hueco que se veía no era un hueco.

De ahí la única definición útil de «atrasado»:

    desfase = CUÁNTOS PARTIDOS da ESPN por jugados que el CSV no tiene

Y NO en días, que es lo que engaña. La primera versión de este script medía
días y sacó que la Premier llevaba **89 días de retraso**. Suena a avería y no
lo es: su CSV termina el 24 de mayo porque ahí acabó la temporada 2025-26, y el
21 de agosto se jugó la primera jornada de la 2026-27. Entre medias hay un
verano. El desfase real de la Premier era **un partido**.

O sea que la métrica en días cometía exactamente el mismo error que la queja que
vino a investigar. Se deja escrito porque es fácil de repetir.

Qué mira, y por qué esas dos fuentes
------------------------------------
  · El CSV del repositorio (`historico_<clave>.csv`) es lo que la INTERFAZ lee
    para la forma reciente, el cara a cara y el Modo Modelo. Lo escribe el bot.
  · ESPN es la fuente que `_completar_desde_espn` usa para adelantar la cola
    cuando football-data aún no ha publicado el lote.

Si ESPN tiene partidos jugados que el CSV no tiene, ese es el desfase real que
ve el usuario en pantalla.

Uso:
    python _v153_auditar_frescura.py            # todas las disponibles
    python _v153_auditar_frescura.py jpn_j1 china
"""
import json
import logging
import os
import sys
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import pandas as pd
import requests

from config import LEAGUES
import fixtures_espn as fe

UA = {'User-Agent': 'Mozilla/5.0'}
BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/%s/scoreboard'
DIAS_ATRAS = 14          # ventana suficiente: más atrás ya sería otro problema


def ultima_fecha_csv(clave):
    ruta = 'historico_%s.csv' % clave
    if not os.path.exists(ruta):
        return None, 0
    try:
        d = pd.read_csv(ruta, usecols=lambda c: c in ('date', 'home_goals'))
        f = pd.to_datetime(d['date'], errors='coerce', format='mixed')
        f = f[d['home_goals'].notna()] if 'home_goals' in d.columns else f
        f = f.dropna()
        return (f.max().normalize() if len(f) else None), len(d)
    except Exception:
        return None, 0


def _jugado(evento):
    n = str((evento.get('status') or {}).get('type', {}).get('name', '')).upper()
    return 'FINAL' in n or 'FULL_TIME' in n


def jugados_espn(codigo, desde, dias=DIAS_ATRAS):
    """
    Partidos que ESPN da por TERMINADOS en la ventana, y cuántos son
    posteriores a `desde` (la última fecha del CSV).

    Se recorre la ventana ENTERA y no se corta en el primer día con partidos:
    lo que hace falta es contarlos todos, no encontrar el más reciente.
    """
    hoy = pd.Timestamp.utcnow().tz_localize(None).normalize()
    ultimo, faltan, total = None, 0, 0
    for i in range(dias + 1):
        dia = hoy - pd.Timedelta(days=i)
        try:
            r = requests.get(BASE % codigo, params={'dates': dia.strftime('%Y%m%d')},
                             timeout=20, headers=UA)
            if r.status_code != 200:
                continue
            eventos = r.json().get('events') or []
        except Exception:
            continue
        n = sum(1 for e in eventos if _jugado(e))
        if not n:
            continue
        total += n
        if ultimo is None:
            ultimo = dia
        if desde is None or dia > desde:
            faltan += n
    return ultimo, faltan, total


def main():
    claves = sys.argv[1:] or [
        c for c, cfg in LEAGUES.items()
        if cfg.get('disponible') and c in fe.ESPN_CODIGOS]
    filas = []
    for clave in claves:
        codigo = fe.ESPN_CODIGOS.get(clave)
        if not codigo:
            continue
        csv_f, n = ultima_fecha_csv(clave)
        espn_f, faltan, jugados = jugados_espn(codigo, csv_f)
        fila = {
            'liga': clave,
            'nombre': (LEAGUES.get(clave) or {}).get('nombre', clave),
            'formato': (LEAGUES.get(clave) or {}).get('formato', '?'),
            'n_csv': n,
            'csv_hasta': str(csv_f.date()) if csv_f is not None else None,
            'espn_jugado_hasta': str(espn_f.date()) if espn_f is not None else None,
            'jugados_en_ventana': jugados,
            'partidos_que_faltan': faltan,
        }
        filas.append(fila)
        print(json.dumps(fila, ensure_ascii=False), flush=True)

    con_desfase = [f for f in filas if f['partidos_que_faltan'] > 0]
    print('\n=== RESUMEN ===')
    print('competiciones auditadas: %d' % len(filas))
    print('con partidos que faltan en el CSV: %d' % len(con_desfase))
    for f in sorted(con_desfase, key=lambda x: -x['partidos_que_faltan']):
        print('  %-22s %-26s faltan %3d de %3d jugados  (csv %s, espn %s)'
              % (f['liga'], f['nombre'][:26], f['partidos_que_faltan'],
                 f['jugados_en_ventana'], f['csv_hasta'],
                 f['espn_jugado_hasta']))
    sin_espn = [f for f in filas if f['jugados_en_ventana'] == 0]
    if sin_espn:
        print('\nsin partidos jugados en ESPN en los ultimos %d dias '
              '(parón o fuera de temporada, su CSV no puede estar atrasado): %d'
              % (DIAS_ATRAS, len(sin_espn)))
        print('  ' + ', '.join(f['liga'] for f in sin_espn))
    json.dump(filas, open('_v153_frescura.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
