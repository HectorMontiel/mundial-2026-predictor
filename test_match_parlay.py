#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests del asistente de parlay por partido (v16: perfiles dinámicos, 2-8).

Ejecutar:  .venv\\Scripts\\python test_match_parlay.py
"""

import math

from match_parlay import (construir_parlay_partido, obtener_selecciones,
                          _compatibles, _correlacionadas, _clasificar,
                          PERFILES, HAIRCUT_CORRELACION)

FALLOS = []


def check(cond, msg):
    print(('OK  ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _plantilla(motor, home, away):
    return motor.plantilla_club(home, away) if hasattr(motor, 'plantilla_club') \
        else motor.plantilla(home, away)


def probar_motor(nombre, motor, home, away):
    print(f"\n=== {nombre}: {home} vs {away} ===")

    resultados_por_perfil = {}
    for perfil, cfg in PERFILES.items():
        for n in (2, 4, 6, 8):
            r = construir_parlay_partido(motor, home, away, num_selecciones=n,
                                         perfil=perfil, excluir_alto_riesgo=False)
            if 'error' in r:
                # aceptable solo si el perfil restrictivo no tiene 2 mercados
                check(perfil == 'conservador',
                      f"{perfil}/n={n}: sin mercados suficientes ({r['error'][:60]})")
                continue
            check(2 <= r['n_selecciones'] <= n,
                  f"{perfil}/n={n}: devuelve {r['n_selecciones']} picks (<= pedidos, >= 2)")
            umbral_ok = all(s['prob'] >= r['umbral_usado'] - 1e-9 for s in r['selecciones'])
            check(umbral_ok, f"{perfil}/n={n}: probs >= umbral usado "
                             f"({r['umbral_usado']*100:.0f} %)")
            if r['n_selecciones'] < n:
                check(bool(r['avisos']), f"{perfil}/n={n}: avisa al devolver menos picks")

            # v20: PISO de probabilidad conjunta del perfil (o aviso honesto)
            lo, hi = cfg['zona']
            en_zona = lo - 1e-6 <= r['prob_conjunta'] < hi
            check(en_zona or bool(r['avisos']),
                  f"{perfil}/n={n}: prob conjunta {r['prob_conjunta']*100:.1f} % "
                  f"en zona [{lo*100:.0f}, {hi*100:.0f}) o avisa")

            # v20: diversidad de categorías min(3, N-1) (o aviso honesto)
            n_sel = r['n_selecciones']
            min_fam = max(1, min(3, n_sel - 1))
            n_fam = len({s['categoria'] for s in r['selecciones']})
            check(n_fam >= min_fam or bool(r['avisos']),
                  f"{perfil}/n={n}: {n_fam} categorías >= {min_fam} o avisa")

            # v20: nunca más de un mercado de córners ni de tarjetas
            cats = [s['categoria'] for s in r['selecciones']]
            check(cats.count('Córners') <= 1 and cats.count('Tarjetas/Disciplina') <= 1,
                  f"{perfil}/n={n}: máx. 1 córners y 1 tarjetas")

            if n == 6:
                resultados_por_perfil[perfil] = r

    # v20: los TRES perfiles deben producir parlays DISTINTOS (mismo partido, n=6)
    if len(resultados_por_perfil) >= 2:
        firmas = {p: tuple(sorted(s['apuesta'] for s in r['selecciones']))
                  for p, r in resultados_por_perfil.items()}
        check(len(set(firmas.values())) == len(firmas),
              f"los perfiles generan parlays DIFERENTES entre sí (n=6): "
              f"{len(set(firmas.values()))} firmas distintas de {len(firmas)}")
        if 'conservador' in resultados_por_perfil and 'agresivo' in resultados_por_perfil:
            c = resultados_por_perfil['conservador']
            a = resultados_por_perfil['agresivo']
            check(a['cuota_combinada'] >= c['cuota_combinada'],
                  f"agresivo paga más que conservador "
                  f"({a['cuota_combinada']:.2f} >= {c['cuota_combinada']:.2f})")
            check(c['prob_conjunta'] >= a['prob_conjunta'],
                  f"conservador es más probable que agresivo "
                  f"({c['prob_conjunta']:.3f} >= {a['prob_conjunta']:.3f})")
        if 'medio' in resultados_por_perfil and not resultados_por_perfil['medio']['avisos']:
            m = resultados_por_perfil['medio']
            check(0.15 - 1e-6 <= m['prob_conjunta'] < 0.60,
                  f"medio queda en su zona 15-60 % ({m['prob_conjunta']*100:.1f} %)")
        if 'agresivo' in resultados_por_perfil and not resultados_por_perfil['agresivo']['avisos']:
            check(resultados_por_perfil['agresivo']['prob_conjunta'] >= 0.05 - 1e-6,
                  "agresivo nunca baja del 5 % conjunto (adiós quimeras)")

    # sin conflictos + regla de UNA línea por stat (córners/goles/tarjetas)
    r = construir_parlay_partido(motor, home, away, num_selecciones=8,
                                 perfil='agresivo', excluir_alto_riesgo=False)
    check('error' not in r, "agresivo/8 genera parlay")
    if 'error' not in r:
        sels = {s.apuesta: s for s in obtener_selecciones(_plantilla(motor, home, away))}
        elegidas = [sels[x['apuesta']] for x in r['selecciones'] if x['apuesta'] in sels]
        sin_conflicto = all(_compatibles(a, b)
                            for i, a in enumerate(elegidas) for b in elegidas[:i])
        check(sin_conflicto, "ninguna pareja elegida es incompatible")
        grupos = [s.grupo for s in elegidas]
        check(len(grupos) == len(set(grupos)),
              "una sola seleccion por mercado (nunca dos lineas de corners/goles/tarjetas)")

        prod = 1.0
        for s in elegidas:
            prod *= s.prob
        n_corr = sum(1 for i, a in enumerate(elegidas) for b in elegidas[:i]
                     if _correlacionadas(a, b))
        esperada = prod * HAIRCUT_CORRELACION ** n_corr
        # prob_conjunta viene redondeada a 4 decimales: usar tolerancia absoluta
        check(math.isclose(r['prob_conjunta'], esperada, rel_tol=1e-3, abs_tol=1e-4),
              f"prob conjunta coherente ({r['prob_conjunta']:.4f} ~ {esperada:.4f})")
        if not r['cuotas_reales']:
            check(r['ev_parlay'] == 0.0, "EV = 0 con cuotas justas")

    # parlay mínimo de 2 picks aceptado
    r2 = construir_parlay_partido(motor, home, away, num_selecciones=2,
                                  perfil='medio', excluir_alto_riesgo=False)
    check('error' not in r2 and r2['n_selecciones'] == 2,
          "un parlay de 2 picks es válido")


def probar_clasificacion():
    print("\n=== Clasificación de campos (regla de líneas) ===")
    g1, _ = _clasificar('over65_corners')
    g2, _ = _clasificar('over75_corners')
    check(g1 == g2 == 'ou_ck', "over 6.5 y over 7.5 córners comparten grupo (excluyentes)")
    g3, _ = _clasificar('over15')
    g4, _ = _clasificar('over35_goles')
    check(g3 == g4 == 'ou_goles', "todas las líneas de goles comparten grupo")


if __name__ == '__main__':
    from prediction_api import PredictionEngine
    from league_engine import ClubEngine

    probar_clasificacion()
    probar_motor('Mundial', PredictionEngine(), 'MEX', 'ECU')

    club = ClubEngine('premier')
    if club.listo:
        e = [t for t in club.equipos if t in ('Arsenal', 'Aston Villa')]
        h, a = (e[0], e[1]) if len(e) == 2 else (club.equipos[0], club.equipos[1])
        probar_motor('Premier', club, h, a)

    print(f"\n{'='*40}\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    raise SystemExit(1 if FALLOS else 0)
