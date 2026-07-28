#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v71 · ¿Qué cobertura de cuotas da ESPN + Pinnacle sobre los fixtures REALES?

El número que importa no es cuántos partidos tiene cada fuente, sino qué
porcentaje de los partidos que la app va a mostrar acaba con cuota. Esto lo
mide sobre los fixtures de la semana en curso, liga por liga, y lista los que
se quedan fuera para poder decir POR QUÉ (liga que ninguna casa cubre, o
partido demasiado lejano para que haya línea abierta).

Salida: `_v71_cobertura_combinada.json`
"""
import json
import logging

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

UA = {'User-Agent': 'Mozilla/5.0'}
SB = 'https://site.api.espn.com/apis/site/v2/sports/{dep}/{liga}/scoreboard'

LIGAS = [
    ('soccer', 'mex.1', 'liga_mx', 'futbol'), ('soccer', 'bra.1', 'brasil', 'futbol'),
    ('soccer', 'usa.1', 'mls', 'futbol'), ('soccer', 'arg.1', 'argentina', 'futbol'),
    ('soccer', 'arg.2', 'arg_primera_nacional', 'futbol'),
    ('soccer', 'col.1', 'col_primera_a', 'futbol'),
    ('soccer', 'usa.usl.1', 'usl_championship', 'futbol'),
    ('soccer', 'bra.2', 'bra_serie_b', 'futbol'),
    ('soccer', 'per.1', 'per_liga1', 'futbol'), ('soccer', 'uru.1', 'uru_primera', 'futbol'),
    ('soccer', 'ecu.1', 'ecu_liga_pro', 'futbol'), ('soccer', 'slv.1', 'slv_primera', 'futbol'),
    ('soccer', 'bol.1', 'bol_division', 'futbol'), ('soccer', 'par.1', 'par_division', 'futbol'),
    ('soccer', 'crc.1', 'crc_fpd', 'futbol'), ('soccer', 'mex.2', 'mex_expansion', 'futbol'),
    ('soccer', 'rus.1', 'rus_premier', 'futbol'), ('soccer', 'chi.1', 'chi_primera', 'futbol'),
    ('soccer', 'rsa.1', 'rsa_premier', 'futbol'), ('soccer', 'aut.1', 'aut_bundesliga', 'futbol'),
    ('soccer', 'conmebol.sudamericana', 'sudamericana', 'futbol'),
    ('tennis', 'atp', 'atp', 'tenis'), ('tennis', 'wta', 'wta', 'tenis'),
    ('baseball', 'mlb', 'mlb', 'mlb'),
]


def main(dias=7):
    import cuotas_multi as cm
    import fixtures_espn as fx
    for d in ('futbol', 'tenis', 'mlb', 'nba'):
        cm.precargar(d)

    hoy = pd.Timestamp.today().normalize()
    ini, fin = hoy.strftime('%Y%m%d'), (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    salida, sin_cuota = [], []
    tot_f = tot_c = 0

    for dep, liga, clave, dep_pin in LIGAS:
        try:
            j = requests.get(SB.format(dep=dep, liga=liga),
                             params={'dates': f'{ini}-{fin}', 'limit': 300},
                             headers=UA, timeout=30).json()
        except Exception as e:
            logger.warning(f'{clave}: {e}')
            continue
        evs = [e for e in j.get('events', [])
               if not e.get('status', {}).get('type', {}).get('completed')]
        n = con = espn_n = pin_n = 0
        for e in evs:
            c = (e.get('competitions') or [{}])[0]
            comps = c.get('competitors') or []
            if len(comps) < 2:
                continue
            loc = next((x for x in comps if x.get('homeAway') == 'home'), comps[0])
            vis = next((x for x in comps if x.get('homeAway') == 'away'), comps[-1])
            home = (loc.get('team') or loc.get('athlete') or {}).get('displayName')
            away = (vis.get('team') or vis.get('athlete') or {}).get('displayName')
            if not home or not away:
                continue
            n += 1
            o_espn = fx._odds_de_evento(c)
            res = cm.cuotas_partido(dep_pin, home, away, odds_espn=o_espn,
                                    espn_ref=(dep, liga, e['id'], c.get('id')))
            if res['n_casas']:
                con += 1
                if 'espn_scoreboard' in res['fuentes']:
                    espn_n += 1
                if 'pinnacle' in res['fuentes']:
                    pin_n += 1
            else:
                sin_cuota.append({'liga': clave, 'partido': f'{home} vs {away}',
                                  'fecha': (e.get('date') or '')[:10]})
        tot_f += n
        tot_c += con
        salida.append({'clave': clave, 'liga_espn': liga, 'fixtures': n,
                       'con_cuota': con, 'via_espn': espn_n, 'via_pinnacle': pin_n,
                       'pct': round(100 * con / n, 1) if n else None})
        if n:
            logger.info(f'{clave:22s} {con:3d}/{n:3d} ({100*con/n:5.1f} %) '
                        f'espn={espn_n:3d} pinnacle={pin_n:3d}')

    res = {'generado': str(pd.Timestamp.now()), 'dias': dias,
           'total_fixtures': tot_f, 'total_con_cuota': tot_c,
           'pct_global': round(100 * tot_c / max(tot_f, 1), 1),
           'por_liga': salida, 'sin_cuota': sin_cuota}
    with open('_v71_cobertura_combinada.json', 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    logger.info(f"== GLOBAL: {tot_c}/{tot_f} con cuota ({res['pct_global']} %)")
    from collections import Counter
    for lg, k in Counter(x['liga'] for x in sin_cuota).most_common(8):
        logger.info(f'   sin cuota: {lg} ({k})')


if __name__ == '__main__':
    main()
