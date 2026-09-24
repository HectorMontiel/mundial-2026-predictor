# -*- coding: utf-8 -*-
"""v308 — una vez: rehace `remates_fotmob_jugadores.csv` con las columnas
nuevas (puesto del partido, puesto habitual, valor de mercado) pidiendo otra
vez la ficha de cada partido de FotMob ya guardado en el fichero de equipos.
Después poda a los 10 últimos partidos de cada equipo."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import remates_fotmob as rf


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    e = pd.read_csv(rf.EQUIPOS, low_memory=False)
    e = e[~e['match_id'].astype(str).str.startswith('fs:')]
    e = e[e['por_jugador'] == 1]
    # sólo lo que puede entrar en los 10 últimos de algún equipo
    e = e.sort_values('fecha')
    vivos = set(e.groupby('equipo').tail(rf.CONSERVAR)['match_id'].astype(str))
    pares = (e[e['match_id'].astype(str).isin(vivos)]
             [['match_id', 'liga']].drop_duplicates('match_id'))
    filas, cerrojo = [], threading.Lock()
    cuenta = {'ok': 0, 'fallo': 0}

    def uno(par):
        mid, liga = str(par[0]), par[1]
        r = rf.extraer(mid, liga)
        with cerrojo:
            if r and r[0]:
                filas.extend(r[0])
                cuenta['ok'] += 1
            else:
                cuenta['fallo'] += 1

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(uno, list(pares.itertuples(index=False, name=None))))
    d = pd.DataFrame(filas)[rf.COL_J]
    tmp = rf.JUGADORES + '.nuevo'
    d.to_csv(tmp, index=False)
    import os
    os.replace(tmp, rf.JUGADORES)
    print('partidos', len(pares), cuenta, 'filas', len(d),
          'podadas', rf.podar())


if __name__ == '__main__':
    main()
