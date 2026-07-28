#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v74 · Auditoría de frescura — ¿cuánto se retrasa cada liga y por qué?

El aviso «datos de hace N días» sale de `ultima_fecha_historico` en
`team_stats_<liga>.json`. Esto mide, para TODAS las competiciones desplegadas:

  · qué fecha tiene el estado del modelo
  · qué fecha tiene el histórico en disco
  · qué fecha tiene ESPN (la fuente diaria)
  · el retraso atribuible a la FUENTE (no al reentrenamiento)

Separa así dos cosas que se confunden: una liga «vieja» porque nadie la ha
reentrenado, y una liga vieja porque su fuente publica por lotes semanales.

Salida: `_v74_frescura.json`
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

UA = {'User-Agent': 'Mozilla/5.0'}
SB = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard'


def ultima_espn(liga_espn: str, dias: int = 40):
    """Fecha del último partido TERMINADO que publica ESPN."""
    hoy = pd.Timestamp.today().normalize()
    ini = (hoy - pd.Timedelta(days=dias)).strftime('%Y%m%d')
    try:
        j = requests.get(SB.format(liga=liga_espn),
                         params={'dates': f"{ini}-{hoy:%Y%m%d}", 'limit': 400},
                         headers=UA, timeout=30).json()
    except Exception:
        return None, 0
    fechas = [e['date'][:10] for e in j.get('events', [])
              if e.get('status', {}).get('type', {}).get('completed')]
    return (max(fechas) if fechas else None), len(fechas)


def main():
    import config
    import league_engine as le

    hoy = pd.Timestamp.today().normalize()
    claves = [c for c, cfg in config.LEAGUES.items() if cfg.get('disponible')]
    logger.info(f"Auditando {len(claves)} competiciones desplegadas")

    def _espn_de(clave):
        cfg = config.LEAGUES[clave]
        return (cfg.get('espn_liga') or le._ESPN_POR_LIGA.get(clave))

    def _uno(clave):
        cfg = config.LEAGUES[clave]
        r = {'clave': clave, 'formato': cfg.get('formato'),
             'espn_liga': _espn_de(clave)}
        ruta = f'team_stats_{clave}.json'
        if os.path.exists(ruta):
            try:
                with open(ruta, encoding='utf-8') as f:
                    r['estado_modelo'] = json.load(f).get('ultima_fecha_historico')
            except Exception:
                pass
        csv = f'historico_{clave}.csv'
        if os.path.exists(csv):
            try:
                d = pd.read_csv(csv, usecols=['date'], parse_dates=['date'])
                r['historico'] = str(d['date'].max().date())
                r['n_partidos'] = len(d)
            except Exception:
                pass
        if r['espn_liga']:
            u, n = ultima_espn(r['espn_liga'])
            r['espn'] = u
            r['espn_terminados_40d'] = n
        for k in ('estado_modelo', 'historico', 'espn'):
            if r.get(k):
                r[f'dias_{k}'] = int((hoy - pd.Timestamp(r[k])).days)
        # retraso que NO se explica por el calendario: lo que ESPN ya tiene y
        # el histórico no
        if r.get('historico') and r.get('espn'):
            r['retraso_fuente'] = int((pd.Timestamp(r['espn'])
                                       - pd.Timestamp(r['historico'])).days)
        return r

    with ThreadPoolExecutor(max_workers=6) as ex:
        salida = list(ex.map(_uno, claves))

    with open('_v74_frescura.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    con_retraso = [r for r in salida if (r.get('retraso_fuente') or 0) > 0]
    con_retraso.sort(key=lambda r: -r['retraso_fuente'])
    logger.info(f"== {len(con_retraso)}/{len(salida)} ligas con partidos que "
                f"ESPN ya publica y el histórico no tiene:")
    for r in con_retraso:
        logger.info(f"   {r['clave']:22s} [{r['formato']:6s}] "
                    f"histórico {r.get('historico')} · ESPN {r.get('espn')} "
                    f"→ {r['retraso_fuente']:3d} d de retraso")
    sin_espn = [r['clave'] for r in salida if not r.get('espn_liga')]
    if sin_espn:
        logger.info(f"Sin mapeo a ESPN ({len(sin_espn)}): {sin_espn}")


if __name__ == '__main__':
    main()
