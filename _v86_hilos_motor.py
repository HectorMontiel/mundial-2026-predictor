#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Es seguro que dos sesiones compartan el MISMO motor cacheado?

@st.cache_resource devuelve el mismo objeto a todas las sesiones, y Streamlit
corre una hebra por sesión. Si ClubEngine guarda estado mutable entre llamadas
(un buffer reutilizado, un DataFrame que se ordena in situ, un contador), dos
usuarios prediciendo a la vez se pisan: no hace falta que reviente, basta con
que devuelva un número distinto al de un usuario solo. Eso sería peor que una
caída, porque nadie lo notaría.

Prueba: se fija un partido, se calcula su probabilidad en solitario, y luego se
lanzan 4 hebras sobre el MISMO motor mezclando partidos distintos. Si el
resultado del partido de control cambia, hay estado compartido.
"""
import sys
import threading
import traceback

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

LIGA = 'liga_mx'
N_HILOS = 4
N_VUELTAS = 25

errores = []
control = []
lock = threading.Lock()


def trabajo(motor, pares, par_control):
    for i in range(N_VUELTAS):
        try:
            a, b = pares[i % len(pares)]
            motor.predecir(a, b)
            r = motor.predecir(*par_control)
            if 'error' not in r:
                with lock:
                    control.append(r['prediction']['probabilities']['home'])
        except Exception as ex:
            with lock:
                errores.append((type(ex).__name__, str(ex)[:200],
                                traceback.format_exc()[-600:]))


def main():
    print('=' * 78)
    print('v86 · ¿HAY ESTADO COMPARTIDO EN EL MOTOR ENTRE SESIONES?')
    print('=' * 78)

    import league_engine
    motor = league_engine.ClubEngine(LIGA)
    equipos = [t for t in motor.stats
               if isinstance(motor.stats[t], dict) and motor.stats[t].get('ELO')]
    equipos = sorted(equipos, key=lambda t: -motor.stats[t]['ELO'])[:10]

    par_control = (equipos[0], equipos[-1])
    pares = [(equipos[i], equipos[j])
             for i in range(len(equipos)) for j in range(len(equipos)) if i != j]

    ref = motor.predecir(*par_control)['prediction']['probabilities']['home']
    print(f'\npartido de control: {par_control[0]} vs {par_control[1]}')
    print(f'P(local) en SOLITARIO (verdad de referencia) = {ref:.6f}')

    print(f'\nlanzando {N_HILOS} hebras x {N_VUELTAS} vueltas sobre el mismo motor...')
    hilos = [threading.Thread(target=trabajo, args=(motor, pares, par_control))
             for _ in range(N_HILOS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    print(f'\nlecturas del partido de control: {len(control)}')
    print(f'excepciones                    : {len(errores)}')

    if control:
        distintos = sorted(set(round(c, 6) for c in control))
        print(f'valores distintos observados   : {len(distintos)}')
        desvia = [c for c in control if abs(c - ref) > 1e-9]
        print(f'lecturas que NO coinciden con la referencia: {len(desvia)}')
        if distintos[:6] != [round(ref, 6)]:
            print(f'  valores: {distintos[:6]}')
            print(f'  rango  : {min(control):.6f} .. {max(control):.6f}')

    if errores:
        print('\nExcepciones (únicas):')
        vistos = set()
        for t, m, tb in errores:
            if (t, m[:100]) in vistos:
                continue
            vistos.add((t, m[:100]))
            print(f'  · {t}: {m}')
            print(f'    {tb[-300:]}')

    limpio = not errores and control and all(abs(c - ref) < 1e-9 for c in control)
    print('\nVEREDICTO: ' + ('el motor es SEGURO de compartir entre sesiones'
                            if limpio else
                            'HAY estado compartido o excepciones — revisar'))


if __name__ == '__main__':
    main()
