#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Verificación de los arreglos de concurrencia.

1) Escritura atómica del log de deriva: N hebras escribiendo y leyendo el mismo
   archivo a la vez. Antes (open 'w' directo) el archivo se puede leer truncado;
   ahora (tmp + os.replace) un lector ve siempre un JSON completo.

2) Techo de memoria del caché de ligas: se simula la política LRU de
   `st.cache_resource(max_entries=N)` recorriendo más ligas que el tope y se
   comprueba que el RSS se estabiliza en lugar de crecer sin freno.
"""
import gc
import json
import os
import sys
import threading
import time
from collections import OrderedDict

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import psutil

RUTA = '_v86_prueba_atomica.json'
N_HILOS = 6
N_VUELTAS = 60

lecturas_rotas_antiguo = 0
lecturas_rotas_nuevo = 0
lock = threading.Lock()


def escribir_antiguo(ruta, datos):
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False)


def escribir_nuevo(ruta, datos):
    tmp = f'{ruta}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False)
    os.replace(tmp, ruta)


def faena(escritor, contador_nombre, hilo_id):
    global lecturas_rotas_antiguo, lecturas_rotas_nuevo
    datos = {f'cruce_{i}': {'features': {f'f{j}': j * 0.1 for j in range(40)},
                            'probs': [0.4, 0.3, 0.3]}
             for i in range(30)}
    for v in range(N_VUELTAS):
        datos[f'cruce_{hilo_id}']['probs'] = [v / 100, 0.3, 0.3]
        escritor(RUTA, datos)
        try:
            with open(RUTA, encoding='utf-8') as f:
                json.load(f)
        except Exception:
            with lock:
                if contador_nombre == 'antiguo':
                    lecturas_rotas_antiguo += 1
                else:
                    lecturas_rotas_nuevo += 1


def prueba_atomicidad():
    global lecturas_rotas_antiguo, lecturas_rotas_nuevo
    print('=' * 78)
    print('1) ESCRITURA DEL LOG DE DERIVA BAJO CONCURRENCIA')
    print('=' * 78)

    for nombre, escritor in (('antiguo', escribir_antiguo),
                             ('nuevo', escribir_nuevo)):
        if os.path.exists(RUTA):
            os.remove(RUTA)
        escritor(RUTA, {'inicial': True})
        hilos = [threading.Thread(target=faena, args=(escritor, nombre, i))
                 for i in range(N_HILOS)]
        t0 = time.time()
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        dt = time.time() - t0
        rotas = (lecturas_rotas_antiguo if nombre == 'antiguo'
                 else lecturas_rotas_nuevo)
        total = N_HILOS * N_VUELTAS
        print(f'  método {nombre:8s}: {rotas:4d} lecturas corruptas de {total} '
              f'({rotas / total * 100:5.1f} %)  [{dt:.1f}s]')

    for f in os.listdir('.'):
        if f.startswith('_v86_prueba_atomica'):
            try:
                os.remove(f)
            except Exception:
                pass

    ok = lecturas_rotas_nuevo == 0 and lecturas_rotas_antiguo > 0
    print(f'\n  -> {"ARREGLADO" if ok else "sin diferencia medible"}'
          f' (antiguo {lecturas_rotas_antiguo} vs nuevo {lecturas_rotas_nuevo})')
    return ok


def rss_mb():
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def prueba_techo_memoria(max_entries=6):
    print('\n' + '=' * 78)
    print(f'2) TECHO DE MEMORIA CON max_entries={max_entries}')
    print('=' * 78)

    import config
    import league_engine

    claves = [c for c, cfg in config.LEAGUES.items()
              if cfg.get('disponible', True)][:16]

    cache = OrderedDict()

    def cargar(clave):
        """Réplica de la política LRU de st.cache_resource(max_entries=N)."""
        if clave in cache:
            cache.move_to_end(clave)
            return cache[clave]
        motor = league_engine.ClubEngine(clave)
        cache[clave] = motor
        while len(cache) > max_entries:
            cache.popitem(last=False)
            gc.collect()
        return motor

    gc.collect()
    base = rss_mb()
    print(f'\nRSS de partida: {base:.1f} MB')
    print(f'recorriendo {len(claves)} ligas distintas '
          f'(como dos usuarios navegando en paralelo):\n')

    picos = []
    for i, c in enumerate(claves, 1):
        try:
            cargar(c)
        except Exception as ex:
            print(f'  {i:2d}. {c:20s} ERROR {type(ex).__name__}')
            continue
        gc.collect()
        r = rss_mb()
        picos.append(r)
        print(f'  {i:2d}. {c:20s} RSS {r:7.1f} MB   '
              f'(en caché: {len(cache)})')

    print(f'\nRSS máximo alcanzado: {max(picos):.1f} MB')
    print(f'RSS final           : {picos[-1]:.1f} MB')

    segunda_mitad = picos[len(picos) // 2:]
    deriva = segunda_mitad[-1] - segunda_mitad[0]
    print(f'deriva en la segunda mitad del recorrido: {deriva:+.1f} MB')
    print('(sin el tope, _v86_memoria.py medía +59,0 MB por cada liga nueva '
          'y proyectaba 3445 MB a las 56 ligas)')

    estable = max(picos) < 1024 and deriva < 150
    print(f'\n  -> {"ESTABLE, cabe en el contenedor" if estable else "sigue creciendo"}')
    return estable


def main():
    ok1 = prueba_atomicidad()
    ok2 = prueba_techo_memoria()
    print('\n' + '=' * 78)
    print(f'RESUMEN: escritura atómica {"OK" if ok1 else "REVISAR"} · '
          f'techo de memoria {"OK" if ok2 else "REVISAR"}')
    print('=' * 78)


if __name__ == '__main__':
    main()
