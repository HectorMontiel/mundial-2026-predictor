#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v190 — LO QUE YA VENÍA EN EL `summary` DE ESPN Y NADIE MIRABA: CUOTAS Y PLANTILLAS.

DOS AVERÍAS, UNA SOLA CAUSA
---------------------------
1. **Las cuotas de cierre se acabaron.** `football-data.co.uk` lleva caído —503
   en todo el sitio, comprobado— y de ahí salían las columnas `odd_*` de los
   históricos, que son las que `odds_store` importa como fase «cierre». Sin
   ellas, los partidos nuevos entran en el ledger sin precio: se puede medir si
   el modelo acierta, pero no si gana dinero.

2. **El bot de plantillas no ha commiteado nunca.** `precalcular_rosters.yml`
   corre a diario y se come **1.130 errores 403**: ESPN bloquea `/teams` y
   `/roster` desde IPs de centro de datos, y ese workflow existía justamente
   para rodear ese bloqueo desde Streamlit Cloud. Ahora bloquea también las de
   GitHub Actions. Como la caché no cambia, el paso de commit dice «no cambió»
   y el workflow termina en verde. Todos los días.

Lo que las une: **`/summary` NO está bloqueado**. Se sabe porque `stats_espn`
lo usa cada día en el runner y trae córners y tarjetas sin un solo fallo. Y ese
mismo `summary` ya traía dentro, sin que nadie lo abriera, `pickcenter` (la
línea de una casa) y `rosters` (las dos alineaciones con sus jugadores).

POR QUÉ LAS CUOTAS DE ESPN SÍ Y LA FOTO DE PLAYDOIT NO
-------------------------------------------------------
La v189 midió usar el último snapshot de Playdoit como cierre y lo **descartó**:
su error contra el cierre real era del tamaño de la señal que se quiere medir.
Medido lo mismo aquí, sobre 60 partidos de LaLiga con cierre conocido:

                        football-data   ESPN/DraftKings   foto Playdoit
    sobreredondeo          1,0555           1,0482           1,1377
    error normalizado         —             0,0162           0,0234
    p90                       —             0,0343           0,0602
    mismo favorito            —             97 %                —
    cobertura                 —             60 de 60            —

ESPN no sólo es mejor que la foto: trae **menos margen que la propia
football-data**, o sea que es una línea más ajustada que la que se venía
usando como referencia. Y aparece en el 100 % de la muestra.

Queda dicho lo que es: la línea de UNA casa (DraftKings) para un partido ya
jugado, no un cierre de consenso. Por eso viaja con su `bookmaker` puesto y no
se disfraza de otra cosa.

QUÉ HACE ESTE MÓDULO
--------------------
Un solo paseo por los `scoreboard` de los días pedidos y un `summary` por
partido —los mismos que `stats_espn` ya pide— y de cada respuesta saca las dos
cosas. No se toca `stats_espn` por dentro: su modo de fallo es corromper el
fondo de estadísticas en silencio, y eso ya pasó una vez.
"""
import io
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('espn_extras')

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{code}'
CABEZ = {'User-Agent': 'Mozilla/5.0'}
CACHE_ROSTERS = 'goleadores_cache.json'
TIMEOUT = 25
PAUSA = 0.05

# Cuántas plantillas distintas puede haber por liga antes de sospechar. Una
# liga tiene 18-24 equipos; 80 significa que se están mezclando competiciones.
MAX_EQUIPOS_POR_LIGA = 80


# ---------------------------------------------------------------------------
# cuotas
# ---------------------------------------------------------------------------
def a_decimal(americana) -> Optional[float]:
    """
    Americana → decimal. `None` si no se puede.

    ESPN publica en formato americano: −1100 es «apuesta 1100 para ganar 100»
    y +2200 es «apuesta 100 para ganar 2200». En decimal son 1,091 y 23,0.
    """
    try:
        m = float(americana)
    except (TypeError, ValueError):
        return None
    if m == 0:
        return None
    d = 1.0 + (100.0 / abs(m) if m < 0 else m / 100.0)
    # una cuota fuera de este rango es un error de lectura, no un precio
    return round(d, 4) if 1.001 <= d <= 1000.0 else None


def _cuotas_de(sumario: Dict) -> Optional[Dict]:
    """Las tres cuotas 1X2 de la primera casa que las publique, o None."""
    for p in (sumario.get('pickcenter') or sumario.get('odds') or []):
        h = a_decimal((p.get('homeTeamOdds') or {}).get('moneyLine'))
        x = a_decimal((p.get('drawOdds') or {}).get('moneyLine'))
        a = a_decimal((p.get('awayTeamOdds') or {}).get('moneyLine'))
        if h and x and a:
            # UN SOBREREDONDEO IMPOSIBLE ES UNA LECTURA MAL HECHA.
            # La suma de las tres probabilidades implícitas vale 1 + margen.
            # Por debajo de 1 sería dinero regalado y por encima de 1,5 no es
            # una línea de nadie: en los dos casos se prefiere no traer nada.
            s = 1 / h + 1 / x + 1 / a
            if not (1.0 <= s <= 1.5):
                logger.debug('[extras] sobreredondeo %.3f descartado', s)
                continue
            return {'odd_home': h, 'odd_draw': x, 'odd_away': a,
                    'casa': ((p.get('provider') or {}).get('name') or 'ESPN')}
    return None


# ---------------------------------------------------------------------------
# plantillas
# ---------------------------------------------------------------------------
_STAT = {'appearances': 'apariciones', 'totalGoals': 'goles',
         'goals': 'goles', 'goalAssists': 'asistencias',
         'assists': 'asistencias', 'totalShots': 'remates',
         'shotsOnTarget': 'al_arco', 'subIns': 'suplencias'}


def _plantillas_de(sumario: Dict) -> List[Tuple[str, str, List[Dict]]]:
    """`[(team_id, nombre_equipo, [jugadores…]), …]` de un partido."""
    salida = []
    for eq in (sumario.get('rosters') or []):
        equipo = eq.get('team') or {}
        tid = str(equipo.get('id') or '').strip()
        if not tid:
            continue
        jugadores = []
        for p in (eq.get('roster') or []):
            a = p.get('athlete') or {}
            pid = str(a.get('id') or '').strip()
            nombre = (a.get('displayName') or a.get('fullName') or '').strip()
            if not pid or not nombre:
                continue
            j = {'id': pid, 'nombre': nombre,
                 'posicion': str((p.get('position') or {}).get('abbreviation')
                                 or '')[:3],
                 'goles': 0.0, 'apariciones': 0.0, 'asistencias': 0.0,
                 'remates': 0.0, 'al_arco': 0.0, 'suplencias': 0.0}
            for st in (p.get('stats') or []):
                col = _STAT.get(st.get('name'))
                if not col:
                    continue
                try:
                    j[col] += float(str(st.get('displayValue') or 0)
                                    .replace(',', ''))
                except (TypeError, ValueError):
                    pass
            if not j['apariciones'] and p.get('active'):
                j['apariciones'] = 1.0
            jugadores.append(j)
        if jugadores:
            salida.append((tid, (equipo.get('displayName') or '').strip(),
                           jugadores))
    return salida


# ---------------------------------------------------------------------------
# el paseo
# ---------------------------------------------------------------------------
def recolectar(clave: str, dias: int = 10,
               sesion=None) -> Dict:
    """
    Un paseo por los últimos `dias` de una competición.

    Devuelve `{'cuotas': [...], 'equipos': {...}, 'plantillas': {...}}`. No
    escribe nada: quien decide qué hacer con esto es `aplicar_*`.
    """
    import datetime as dt
    import requests

    try:
        import fixtures_espn as fe
        code = (fe.ESPN_CODIGOS or {}).get(clave)
    except Exception:
        code = None
    if not code:
        logger.info('[extras] %s no tiene código ESPN: se salta', clave)
        return {'cuotas': [], 'equipos': {}, 'plantillas': {}}

    ses = sesion or requests.Session()
    ses.headers.update(CABEZ)
    hoy = dt.date.today()
    cuotas, equipos, plantillas = [], {}, {}

    for n in range(dias):
        d = (hoy - dt.timedelta(days=n)).strftime('%Y%m%d')
        try:
            r = ses.get(BASE.format(code=code) + '/scoreboard?dates=%s' % d,
                        timeout=TIMEOUT)
            eventos = (r.json() or {}).get('events') or []
        except Exception as e:
            logger.debug('[extras] %s %s: %s', clave, d, e)
            continue
        for ev in eventos:
            try:
                s = ses.get(BASE.format(code=code) + '/summary?event=%s'
                            % ev['id'], timeout=TIMEOUT).json()
            except Exception as e:
                logger.debug('[extras] %s evento %s: %s', clave, ev.get('id'), e)
                continue

            c = _cuotas_de(s)
            if c:
                comp = ((ev.get('competitions') or [{}])[0])
                lados = {}
                for x in (comp.get('competitors') or []):
                    lados[str(x.get('homeAway') or '')] = x
                h, a = lados.get('home') or {}, lados.get('away') or {}
                fila = dict(c)
                fila.update({
                    'event_id': str(ev.get('id')),
                    'fecha': str(ev.get('date') or '')[:10],
                    'home': ((h.get('team') or {}).get('displayName') or ''),
                    'away': ((a.get('team') or {}).get('displayName') or ''),
                })
                try:
                    fila['home_goals'] = int(h.get('score'))
                    fila['away_goals'] = int(a.get('score'))
                except (TypeError, ValueError):
                    fila['home_goals'] = fila['away_goals'] = None
                if fila['home'] and fila['away']:
                    cuotas.append(fila)

            for tid, nombre, jug in _plantillas_de(s):
                if nombre:
                    equipos[tid] = nombre
                plantillas.setdefault(tid, {})
                for j in jug:
                    v = plantillas[tid].setdefault(j['id'], dict(j))
                    if v is not j:
                        for k in ('goles', 'apariciones', 'asistencias',
                                  'remates', 'al_arco', 'suplencias'):
                            v[k] = float(v.get(k) or 0) + float(j.get(k) or 0)
                        if j.get('posicion') and not v.get('posicion'):
                            v['posicion'] = j['posicion']
            time.sleep(PAUSA)

    logger.info('[extras] %s: %d partidos con cuota · %d equipos · %d '
                'plantillas', clave, len(cuotas), len(equipos), len(plantillas))
    return {'cuotas': cuotas, 'equipos': equipos, 'plantillas': plantillas}


# ---------------------------------------------------------------------------
# aplicar: las cuotas al histórico
# ---------------------------------------------------------------------------
def aplicar_cuotas(clave: str, cuotas: List[Dict]) -> Dict:
    """
    Rellena `odd_home/odd_draw/odd_away` de `historico_<clave>.csv` DONDE ESTÉN
    VACÍAS.

    Nunca pisa una cuota que ya estaba: si football-data vuelve, su cierre
    manda, y así esto es reversible sin perder nada. El emparejamiento va por
    fecha y marcador, que es lo único común sin depender del nombre —los
    históricos de football-data escriben «Ath Bilbao» y ESPN «Athletic Club»—.

    SE EDITA POR LÍNEAS, NO CON `to_csv`. Volcar el DataFrame entero reescribe
    las miles de filas que no han cambiado, y pandas no devuelve los flotantes
    tal cual: `45.574062886167894` vuelve como `45.57406288616789`. Medido: 872
    cuotas producían **325.130 líneas de diff**. Con un `.git` de 16 GB eso no
    es un detalle de estilo. Así el diff mide lo que cambió y nada más.
    """
    import csv
    import os

    ruta = 'historico_%s.csv' % clave
    if not os.path.exists(ruta) or not cuotas:
        return {'escritas': 0, 'motivo': 'sin histórico o sin cuotas'}

    with io.open(ruta, encoding='utf-8', newline='') as f:
        crudo = f.read()
    lineas = crudo.split('\n')
    if not lineas:
        return {'escritas': 0, 'motivo': 'histórico vacío'}

    cab = next(csv.reader([lineas[0]]))
    try:
        i_fecha = cab.index('date')
        i_gh, i_ga = cab.index('home_goals'), cab.index('away_goals')
        i_h, i_x, i_a = (cab.index('odd_home'), cab.index('odd_draw'),
                         cab.index('odd_away'))
    except ValueError as e:
        return {'escritas': 0, 'motivo': 'faltan columnas: %s' % e}

    # índice por (fecha, goles) -> números de línea. Se guardan TODOS los que
    # coinciden para poder descartar los ambiguos: dos partidos el mismo día
    # con el mismo marcador no se adivinan.
    indice, filas = {}, {}
    antes = 0
    for n in range(1, len(lineas)):
        if not lineas[n].strip():
            continue
        try:
            fila = next(csv.reader([lineas[n]]))
        except Exception:
            continue
        if len(fila) <= max(i_fecha, i_gh, i_ga, i_h, i_x, i_a):
            continue
        if (fila[i_h] or '').strip():
            antes += 1
        try:
            gh = int(float(fila[i_gh]))
            ga = int(float(fila[i_ga]))
        except (TypeError, ValueError):
            continue
        clav = (str(fila[i_fecha])[:10], gh, ga)
        indice.setdefault(clav, []).append(n)
        filas[n] = fila

    escritas, ambiguas, ya_tenian = 0, 0, 0
    for c in cuotas:
        if c.get('home_goals') is None:
            continue
        donde = indice.get((c['fecha'], c['home_goals'], c['away_goals']))
        if not donde:
            continue
        if len(donde) != 1:
            ambiguas += 1
            continue
        n = donde[0]
        fila = filas[n]
        if (fila[i_h] or '').strip():
            ya_tenian += 1
            continue                      # ya tenía cierre: no se toca
        fila[i_h] = str(c['odd_home'])
        fila[i_x] = str(c['odd_draw'])
        fila[i_a] = str(c['odd_away'])
        salida = io.StringIO()
        csv.writer(salida, lineterminator='').writerow(fila)
        lineas[n] = salida.getvalue()
        escritas += 1

    if escritas:
        nuevo = '\n'.join(lineas)
        # el número de líneas NO puede cambiar: aquí sólo se rellenan huecos.
        if nuevo.count('\n') != crudo.count('\n'):
            raise RuntimeError('%s cambió de número de líneas al rellenar'
                               % clave)
        with io.open(ruta, 'w', encoding='utf-8', newline='') as f:
            f.write(nuevo)
    return {'escritas': escritas, 'ambiguas': ambiguas,
            'ya_tenian': ya_tenian, 'con_cuota_antes': antes,
            'con_cuota_ahora': antes + escritas}


# ---------------------------------------------------------------------------
# aplicar: las plantillas a la caché
# ---------------------------------------------------------------------------
def aplicar_plantillas(clave: str, equipos: Dict, plantillas: Dict) -> Dict:
    """
    Mete lo visto en `goleadores_cache.json`, en su formato de siempre.

    **SE FUSIONA, NO SE SUSTITUYE.** La caché lleva la temporada entera y esto
    es una ventana de diez días: reemplazarla dejaría el panel de máximos
    goleadores contando desde el lunes. Un equipo que no jugó esta semana
    conserva lo que tenía.
    """
    if not equipos and not plantillas:
        return {'equipos': 0, 'plantillas': 0, 'motivo': 'nada que escribir'}
    if len(equipos) > MAX_EQUIPOS_POR_LIGA:
        raise RuntimeError('%s trajo %d equipos: eso no es una liga'
                           % (clave, len(equipos)))

    cache = {}
    if os.path.exists(CACHE_ROSTERS):
        try:
            with io.open(CACHE_ROSTERS, encoding='utf-8') as f:
                cache = json.load(f)
        except Exception as e:
            logger.warning('[extras] no se pudo leer la caché: %s', e)
            return {'equipos': 0, 'plantillas': 0, 'motivo': 'caché ilegible'}

    ahora = time.time()
    n_eq = n_pl = 0

    if equipos:
        ck = 'teams:%s' % clave
        previos = {str(t.get('id')): t.get('nombre')
                   for t in ((cache.get(ck) or {}).get('data') or [])
                   if isinstance(t, dict)}
        previos.update({str(k): v for k, v in equipos.items()})
        cache[ck] = {'ts': ahora,
                     'data': [{'id': k, 'nombre': v}
                              for k, v in sorted(previos.items(),
                                                 key=lambda x: x[1] or '')]}
        n_eq = len(previos)

    for tid, jug in plantillas.items():
        ck = 'roster:%s:%s' % (clave, tid)
        previos = {str(j.get('id')): j
                   for j in ((cache.get(ck) or {}).get('data') or [])
                   if isinstance(j, dict) and j.get('id')}
        for pid, j in jug.items():
            if pid in previos:
                # el que ya estaba conserva sus totales; sólo se refresca el
                # nombre y la posición, que es lo que cambia de verdad
                previos[pid]['nombre'] = j['nombre'] or previos[pid].get('nombre')
                if j.get('posicion'):
                    previos[pid]['posicion'] = j['posicion']
            else:
                previos[pid] = j
        cache[ck] = {'ts': ahora, 'data': list(previos.values())}
        n_pl += 1

    tmp = CACHE_ROSTERS + '.nuevo'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        # COMPACTO, no indentado. Con `indent=1` este fichero son 312.310
        # lineas y 6 MB, y ahora que el bot SI lo commitea a diario eso
        # son ~2 GB al año sobre un `.git` que ya pesa 16. Nadie lee
        # 312.000 lineas de JSON a mano: lo que se mira es su contenido,
        # y para eso esta `frescura_datos`.
        json.dump(cache, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, CACHE_ROSTERS)
    return {'equipos': n_eq, 'plantillas': n_pl}


# ---------------------------------------------------------------------------
def main() -> int:
    import argparse
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('claves', nargs='*', help='competiciones (por defecto, las '
                                              'disponibles con código ESPN)')
    ap.add_argument('--dias', type=int, default=10)
    ap.add_argument('--solo-cuotas', action='store_true')
    ap.add_argument('--solo-plantillas', action='store_true')
    a = ap.parse_args()

    claves = a.claves
    if not claves:
        import config
        import fixtures_espn as fe
        codigos = fe.ESPN_CODIGOS or {}
        claves = sorted(c for c, cfg in config.LEAGUES.items()
                        if cfg.get('disponible') and c in codigos)

    print('%d competiciones · ventana de %d días' % (len(claves), a.dias))
    tot_c = tot_p = 0
    fallos = []
    for c in claves:
        try:
            r = recolectar(c, dias=a.dias)
            if not a.solo_plantillas:
                res = aplicar_cuotas(c, r['cuotas'])
                tot_c += res.get('escritas', 0)
                if res.get('escritas'):
                    print('  %-24s +%d cuotas (%d -> %d)'
                          % (c, res['escritas'], res['con_cuota_antes'],
                             res['con_cuota_ahora']))
            if not a.solo_cuotas:
                res = aplicar_plantillas(c, r['equipos'], r['plantillas'])
                tot_p += res.get('plantillas', 0)
        except Exception as e:
            fallos.append('%s: %s: %s' % (c, type(e).__name__, e))
            logger.warning('[extras] %s: %s', c, e)

    print()
    print('cuotas escritas en los históricos: %d' % tot_c)
    print('plantillas actualizadas:           %d' % tot_p)
    if fallos:
        print('con fallo (%d):' % len(fallos))
        for f in fallos[:10]:
            print('   ', f)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
