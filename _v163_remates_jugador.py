#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — ¿CALIBRA UN MODELO DE REMATES POR JUGADOR?

Por qué hay que medirlo aparte
------------------------------
El modelo por equipo está cerrado y calibra (0,0131 en remates totales). Eso no
dice nada del de jugador: un delantero remata 2-3 veces por partido, así que la
muestra por jugador es diez veces más pequeña y encima está contaminada por dos
cosas que en el equipo no existen —si juega o no, y cuántos minutos—. Un modelo
que calibra sumando once jugadores puede estar mal en cada uno de ellos.

Cómo se mide
------------
Se bajan los `summary` de ESPN de los últimos partidos de varias competiciones
—los mismos que ya lee `stats_espn` para el boxscore, pero mirando el bloque
`rosters`, que trae SHOT y SOG por jugador y la marca de titular— y se hace un
pase cronológico. Por cada jugador que aparece en un partido se predice, SÓLO
con lo anterior:

    P(≥1 remate)          y          P(≥1 remate a puerta)

y se compara con lo que pasó. Tres variantes:

    plano       λ = sus remates por aparición en las últimas 10
    equipo      λ = plano · (remates esperados del equipo / su media)
                    o sea el factor de la Parte 1 aplicado al jugador
    posicion    λ = la media de su posición en la competición (referencia tonta)

y dos distribuciones, Poisson y binomial negativa.

SE EVALÚA SÓLO A QUIEN JUGÓ. Separa la pregunta «¿cuánto remata?» de la
pregunta «¿juega?», que es un problema distinto y se mide abajo aparte
(`aciertos_titular`). Mezclarlas daría un número que no dice cuál de las dos
falla.

    python _v163_remates_jugador.py [code_espn ...]
"""
import json
import logging
import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_remates_jugador.json'
CACHE = '_v163_cache_jugadores'
CODIGOS = ['eng.1', 'esp.1', 'ita.1', 'mex.1', 'ger.1', 'fra.1']
DIAS = 400
TRAMO = 55
VENTANA = 10          # apariciones previas del jugador
MIN_PREV = 4


# ---------------------------------------------------------------------------
# descarga
# ---------------------------------------------------------------------------
def _eventos(code, dias=DIAS):
    """Partidos terminados de la competición en el último año."""
    import remates_jugadores as rj
    hoy = pd.Timestamp.today().normalize()
    vistos, salida = set(), []
    for salto in range(0, dias, TRAMO):
        fin = hoy - pd.Timedelta(days=salto)
        ini = fin - pd.Timedelta(days=TRAMO)
        j = rj._get(rj.BASE.format(liga=code) + '/scoreboard',
                    {'dates': '%s-%s' % (ini.strftime('%Y%m%d'),
                                         fin.strftime('%Y%m%d')),
                     'limit': 400})
        for ev in (j or {}).get('events', []):
            if not ((ev.get('status') or {}).get('type') or {}).get('completed'):
                continue
            if ev['id'] in vistos:
                continue
            vistos.add(ev['id'])
            salida.append({'id': ev['id'], 'fecha': ev.get('date', '')})
    salida.sort(key=lambda x: x['fecha'])
    return salida


def _jugadores_de(code, ev_id):
    """Los dos equipos de un partido con sus jugadores y sus remates."""
    import remates_jugadores as rj
    j = rj._get(rj.BASE.format(liga=code) + '/summary', {'event': ev_id})
    if not j:
        return None
    filas = []
    for ro in j.get('rosters') or []:
        equipo = ((ro.get('team') or {}).get('displayName') or '').strip()
        rival = None
        for otro in j.get('rosters') or []:
            n = ((otro.get('team') or {}).get('displayName') or '').strip()
            if n and n != equipo:
                rival = n
        for a in ro.get('roster') or []:
            st = {x.get('abbreviation'): x.get('displayValue')
                  for x in (a.get('stats') or [])}
            if 'SHOT' not in st:
                continue

            def num(k):
                try:
                    return float(st.get(k) or 0)
                except (TypeError, ValueError):
                    return 0.0
            at = a.get('athlete') or {}
            filas.append({
                'evento': ev_id, 'equipo': equipo, 'rival': rival,
                'jugador_id': str(at.get('id') or ''),
                'jugador': at.get('displayName'),
                'posicion': (a.get('position') or {}).get('abbreviation') or '',
                'titular': bool(a.get('starter')),
                'jugo': bool(num('APP') > 0 or a.get('starter')),
                'remates': num('SHOT'), 'al_arco': num('SOG'),
            })
    return filas


def descargar(code, limite=260):
    """Baja y cachea en disco los jugadores de los últimos partidos."""
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, '%s.json' % code)
    if os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as f:
            return pd.DataFrame(json.load(f))
    evs = _eventos(code)[-limite:]
    print('   %s: %d partidos terminados, bajando...' % (code, len(evs)),
          flush=True)
    filas, fechas = [], {e['id']: e['fecha'] for e in evs}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(lambda e: _jugadores_de(code, e['id']),
                                       evs), 1):
            if res:
                filas.extend(res)
            if i % 50 == 0:
                print('      %d/%d' % (i, len(evs)), flush=True)
    for f in filas:
        f['fecha'] = fechas.get(f['evento'], '')
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(filas, f, ensure_ascii=False)
    time.sleep(0.5)
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# medición
# ---------------------------------------------------------------------------
def _p_al_menos_uno(lam, disp):
    """P(X >= 1) con Poisson o binomial negativa de media `lam`."""
    from scipy import stats as st
    lam = float(lam)
    if lam <= 0:
        return 0.0
    if disp is None or disp <= 1.0001:
        return float(1.0 - np.exp(-lam))
    r = lam / (disp - 1.0)
    p = r / (r + lam)
    return float(1.0 - st.nbinom.cdf(0, r, p))


def corpus(d, obj):
    """
    Pase cronológico por partido, evaluando SÓLO a los titulares.

    LA FUGA QUE TUVO LA PRIMERA VERSIÓN, Y QUE CAMBIABA EL RESULTADO.
    ESPN no pone la posición real a quien sale del banquillo: le pone
    literalmente `SUB` (4.580 de 10.390 filas en la Premier). Así que la
    «media de su posición», calculada con la posición de ESTE partido, estaba
    diciendo en realidad «este jugador fue suplente», que es justo lo que no se
    sabe antes del partido. Con esa información de contrabando la referencia
    posicional ganaba a todo lo demás, y era mentira.

    Se arregla con dos cambios:

      · la posición sale de su HISTORIAL —la moda de sus titularidades
        anteriores—, nunca de la fila que se está prediciendo;
      · se evalúa sólo a quien fue TITULAR, que es el escenario que va a
        enseñar la interfaz cuando FotMob publique el once probable.

    Si juega o no es una pregunta distinta y se mide aparte (`_seleccion`).
    Mezclarlas daba un número que no decía cuál de las dos fallaba.
    """
    col = 'remates' if obj == 'tot' else 'al_arco'
    d = d.sort_values(['fecha', 'evento']).copy()
    hist = {}          # jugador_id -> sus valores COMO TITULAR
    pos_de = {}        # jugador_id -> posiciones en las que ha sido titular
    eq_hist = {}       # equipo -> su total por partido
    pos_hist = {}      # posicion -> valores de titulares en esa posición
    filas = []
    for ev, g in d.groupby('evento', sort=False):
        # --- se predice con lo de ANTES ------------------------------------
        for r in g.itertuples(index=False):
            if not r.titular:
                continue
            h = hist.get(r.jugador_id) or []
            eq = eq_hist.get(r.equipo) or []
            pos = pos_de.get(r.jugador_id)
            ph = pos_hist.get(pos) or [] if pos else []
            if len(h) < MIN_PREV or len(eq) < 6 or len(ph) < 200:
                continue
            plano = float(np.mean(h[-VENTANA:]))
            ref = float(np.mean(ph))
            # el factor del equipo: lo que se espera que tire el equipo en este
            # partido dividido por lo que tira de media. Con el estimador de la
            # Parte 1 haría falta el rival; aquí basta su media móvil, que es
            # la parte del factor que depende del propio equipo.
            base_eq = float(np.mean(eq))
            movil_eq = float(np.mean(eq[-VENTANA:]))
            factor = movil_eq / base_eq if base_eq > 0 else 1.0
            filas.append({
                'real': float(getattr(r, col)),
                'plano': plano,
                'equipo': plano * factor,
                'posicion_ref': ref,
                'factor_equipo': factor,
                'n_previas': min(len(h), VENTANA),
                'pos': pos,
            })
        # --- y luego se apunta lo de este partido --------------------------
        tot_eq = {}
        for r in g.itertuples(index=False):
            tot_eq[r.equipo] = tot_eq.get(r.equipo, 0.0) + float(getattr(r, col))
            if r.titular:
                hist.setdefault(r.jugador_id, []).append(float(getattr(r, col)))
                if r.posicion and r.posicion != 'SUB':
                    # la posición del jugador es la moda de sus titularidades:
                    # un lateral que un día juega de central no cambia de sitio
                    # en la tabla por un partido
                    c = pos_de.setdefault('_c_' + r.jugador_id, {})
                    c[r.posicion] = c.get(r.posicion, 0) + 1
                    pos_de[r.jugador_id] = max(c, key=c.get)
                    pos_hist.setdefault(r.posicion, []).append(
                        float(getattr(r, col)))
        for e, v in tot_eq.items():
            eq_hist.setdefault(e, []).append(v)
    return pd.DataFrame(filas)


def _seleccion(d):
    """
    La OTRA pregunta: ¿acierta la frecuencia de titularidad quién va a jugar?

    Es lo que sustituye al once cuando FotMob no lo publica, así que hay que
    saber cuánto vale. Se mide como una probabilidad más: por cada jugador del
    plantel se predice P(titular) con su frecuencia previa y se compara con lo
    que pasó.
    """
    from _v163_remates_estimadores import metricas
    d = d.sort_values(['fecha', 'evento']).copy()
    veces, plantel_n, filas = {}, {}, []
    for ev, g in d.groupby('evento', sort=False):
        for r in g.itertuples(index=False):
            n = plantel_n.get(r.jugador_id, 0)
            if n >= 6:
                filas.append({'p': veces.get(r.jugador_id, 0) / n,
                              'real': float(bool(r.titular))})
        for r in g.itertuples(index=False):
            plantel_n[r.jugador_id] = plantel_n.get(r.jugador_id, 0) + 1
            if r.titular:
                veces[r.jugador_id] = veces.get(r.jugador_id, 0) + 1
    x = pd.DataFrame(filas)
    if len(x) < 500:
        return None
    m = metricas(x['p'], x['real'])
    if m:
        m['n'] = int(len(x))
        m['tasa_real'] = round(float(x['real'].mean()), 4)
    return m


def main():
    from _v163_remates_estimadores import metricas

    codigos = sys.argv[1:] or CODIGOS
    marcos = {}
    for code in codigos:
        try:
            d = descargar(code)
        except Exception as e:
            print('%-8s ERROR %s' % (code, type(e).__name__))
            continue
        if d is None or not len(d):
            print('%-8s sin datos' % code)
            continue
        print('%-8s %d filas jugador-partido, %d partidos, %d jugadores'
              % (code, len(d), d['evento'].nunique(), d['jugador_id'].nunique()),
              flush=True)
        marcos[code] = d

    salida = {}
    for obj in ('tot', 'on'):
        print()
        print('=' * 78)
        print('POR JUGADOR — P(≥1 remate%s)'
              % ('' if obj == 'tot' else ' a puerta'))
        print('=' * 78)
        acc, por_liga = {}, {}
        for code, d in marcos.items():
            c = corpus(d, obj)
            if len(c) < 1000:
                print('%-8s n=%d insuficiente' % (code, len(c)))
                continue
            serie = c['real']
            m, v = float(serie.mean()), float(serie.var())
            disp = max(v / m, 1.0) if m > 0 else 1.0
            print('%-8s n=%6d  media=%.3f  disp=%.3f  frecuencia real de ≥1: '
                  '%.3f' % (code, len(c), m, disp, float((serie >= 1).mean())),
                  flush=True)
            # ENCOGIMIENTO HACIA LA MEDIA DE SU POSICIÓN.
            #
            # La media de un jugador sale de 4-10 apariciones. Con λ≈0,78 eso
            # es una desviación típica de la media de ~0,28: un tercio de ruido
            # puro. La media de su posición se calcula con cientos de
            # observaciones, así que es estable pero no distingue a Haaland de
            # su compañero de ataque. La combinación pesada por muestra es lo
            # que hizo la v160 con el árbitro (K=60) y por el mismo motivo.
            for K in (2, 4, 6, 8, 12, 20):
                n = c['n_previas'].astype(float)
                c['enc%d' % K] = ((n * c['plano'] + K * c['posicion_ref'])
                                  / (n + K))
                c['enceq%d' % K] = c['enc%d' % K] * c['factor_equipo']
            fila = {}
            estimadores = (['plano', 'equipo', 'posicion_ref']
                           + ['enc%d' % K for K in (2, 4, 6, 8, 12, 20)]
                           + ['enceq%d' % K for K in (4, 8, 12)])
            for est in estimadores:
                for dist, dv in (('poisson', 1.0), ('binneg', disp)):
                    p = c[est].apply(lambda x: _p_al_menos_uno(x, dv))
                    real = (c['real'] >= 1).astype(float)
                    mt = metricas(p, real)
                    if mt is None:
                        continue
                    mt['corr'] = float(np.corrcoef(c[est], c['real'])[0, 1])
                    acc.setdefault((est, dist), []).append((len(c), mt))
                    fila['%s/%s' % (est, dist)] = {k: round(vv, 5)
                                                   for k, vv in mt.items()}
            por_liga[code] = {'n': int(len(c)), 'dispersion': round(disp, 4),
                              'media': round(m, 4), 'errores': fila}
        if not acc:
            continue
        filas = []
        for (est, dist), vals in acc.items():
            n = sum(v[0] for v in vals)
            filas.append({'estimador': est, 'dist': dist, 'n': n,
                          **{k: sum(v[0] * v[1][k] for v in vals) / n
                             for k in ('marginal', 'brier', 'ece', 'corr')}})
        print()
        print('%-14s %-9s %10s %10s %10s %8s'
              % ('estimador', 'distrib.', 'marginal', 'brier', 'ECE', 'corr'))
        print('-' * 66)
        for f in sorted(filas, key=lambda f: f['brier']):
            print('%-14s %-9s %10.5f %10.5f %10.5f %8.3f'
                  % (f['estimador'], f['dist'], f['marginal'], f['brier'],
                     f['ece'], f['corr']))
        mejor = min(filas, key=lambda f: f['ece'])
        print('\nMEJOR por ECE: %s con %s (ece %.5f)'
              % (mejor['estimador'], mejor['dist'], mejor['ece']))
        salida[obj] = {'filas': sorted(filas, key=lambda f: f['brier']),
                       'mejor': mejor, 'por_liga': por_liga}

    # ¿AGUANTA EL ENCOGIMIENTO CON MUY POCA MUESTRA?
    #
    # Todo lo de arriba exige `MIN_PREV` apariciones previas. En producción hay
    # que decidir si se enseña también al que lleva una o dos —a principio de
    # temporada son casi todos—, y eso no se decide por gusto: se mide por
    # tramos de muestra. Si el ECE aguanta, la fila sale marcada; si se
    # dispara, no sale.
    print()
    print('=' * 78)
    print('POR TRAMOS DE MUESTRA — ECE de P(≥1 remate) con el encogido')
    print('=' * 78)
    global MIN_PREV
    guardado = MIN_PREV
    MIN_PREV = 1
    tramos = {}
    for obj, K in (('tot', 6), ('on', 12)):
        print('remates %s:' % ('totales' if obj == 'tot' else 'a puerta'))
        for code, d in marcos.items():
            c = corpus(d, obj)
            if not len(c):
                continue
            n = c['n_previas'].astype(float)
            c['enc'] = (n * c['plano'] + K * c['posicion_ref']) / (n + K)
            for lo, hi in ((1, 2), (2, 4), (4, 7), (7, 99)):
                sub = c[(n >= lo) & (n < hi)]
                if len(sub) < 200:
                    continue
                p = sub['enc'].apply(lambda x: _p_al_menos_uno(x, 1.0))
                mt = metricas(p, (sub['real'] >= 1).astype(float))
                if not mt:
                    continue
                k = '%s|%d-%d' % (obj, lo, hi - 1)
                tramos.setdefault(k, []).append((len(sub), mt))
        for k in sorted(t for t in tramos if t.startswith(obj)):
            vals = tramos[k]
            nn = sum(v[0] for v in vals)
            agg = {m: sum(v[0] * v[1][m] for v in vals) / nn
                   for m in ('marginal', 'brier', 'ece')}
            print('   apariciones %-6s n=%6d  marginal %.5f  brier %.5f  '
                  'ECE %.5f' % (k.split('|')[1], nn, agg['marginal'],
                                agg['brier'], agg['ece']))
            salida.setdefault('tramos', {})[k] = {
                'n': nn, **{m: round(v, 5) for m, v in agg.items()}}
    MIN_PREV = guardado

    print()
    print('=' * 78)
    print('¿QUIÉN JUEGA? — la frecuencia de titularidad como probabilidad')
    print('=' * 78)
    sel = {}
    for code, d in marcos.items():
        m = _seleccion(d)
        if not m:
            continue
        sel[code] = {k: round(v, 5) for k, v in m.items()}
        print('%-8s n=%6d  tasa real %.3f  marginal %.5f  brier %.5f  '
              'ECE %.5f' % (code, m['n'], m['tasa_real'], m['marginal'],
                            m['brier'], m['ece']))
    salida['seleccion'] = sel
    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\nescrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
