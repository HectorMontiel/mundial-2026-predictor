#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — ¿Qué dice el MERCADO sobre Puebla vs Chivas?

Por qué esto cierra el caso
---------------------------
Se ha medido que cuando el modelo y el ELO eligen favoritos distintos —el 19,2 %
de los partidos— es un EMPATE ESTADÍSTICO: el modelo acierta el 36,34 % y el
ELO el 34,89 % (z = +1,84, n = 7.361). O sea que «hacer caso al ELO» en esos
partidos no habría acertado más.

Entonces la pregunta «¿el favorito correcto es Chivas?» no la puede contestar
ni el ELO ni el modelo. El único árbitro con mejor información que los dos es
el mercado, que es lo que este proyecto usa como referencia en todo lo demás.

Si el mercado tiene el partido parejo, el 50-25-25 de la ficha es razonable y
no hay nada que arreglar. Si el mercado da a Chivas claramente favorito, hay un
hueco real y se puede cuantificar.
"""
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

DB = 'odds_historico.db'


def main():
    print('=' * 78)
    print('v87 · PUEBLA vs CHIVAS — LA OPINIÓN DEL MERCADO')
    print('=' * 78)

    # 1) lo que dice el modelo hoy
    import league_engine as le
    e = le.ClubEngine('liga_mx')
    if e.listo:
        p = [t for t in e.stats if 'puebla' in t.lower()]
        c = [t for t in e.stats if 'chiva' in t.lower() or 'guadalajara' in t.lower()]
        if p and c:
            r = e.predecir(p[0], c[0])['prediction']['probabilities']
            print(f'\n  modelo (con prior de ELO): {p[0]} {r["home"]:.1%} · '
                  f'empate {r["draw"]:.1%} · {c[0]} {r["away"]:.1%}')
            print(f'  ELO: {e.stats[p[0]]["ELO"]:.0f} vs {e.stats[c[0]]["ELO"]:.0f}')
    else:
        print('\n  (motor de liga_mx no disponible en esta plataforma)')

    # 2) cuotas en vivo
    print('\n--- cuotas EN VIVO ---')
    try:
        import cuotas_multi as cm
        res = cm.cuotas_partido('futbol', 'Puebla', 'Guadalajara Chivas')
        casas = res.get('casas') or {}
        print(f'  casas encontradas: {len(casas)}')
        for casa, cu in list(casas.items())[:8]:
            print(f'    {casa:20s} {cu}')
        pin = res.get('pinnacle') or {}
        if pin:
            just = cm.devig({k: v for k, v in pin.items() if v},
                            metodo='potencia')
            print(f'\n  Pinnacle: {pin}')
            print(f'  probabilidad JUSTA de Pinnacle: '
                  + ' · '.join(f'{k} {v:.1%}' for k, v in just.items()))
        elif casas:
            prom = {}
            for cu in casas.values():
                for k, v in (cu or {}).items():
                    if v and v > 1:
                        prom.setdefault(k, []).append(v)
            if prom:
                med = {k: sum(v) / len(v) for k, v in prom.items()}
                just = cm.devig(med, metodo='potencia')
                print(f'\n  media del mercado: '
                      + ' · '.join(f'{k} {v:.2f}' for k, v in med.items()))
                print(f'  probabilidad JUSTA: '
                      + ' · '.join(f'{k} {v:.1%}' for k, v in just.items()))
        else:
            print('  sin cuotas en vivo para ese partido')
    except Exception as ex:
        print(f'  no se pudieron leer cuotas en vivo: {type(ex).__name__}: {ex}')

    # 3) qué ha hecho el mercado históricamente con este cruce
    print('\n--- histórico de este cruce en odds_historico.db ---')
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tablas = [t[0] for t in cur.fetchall()]
        hallado = False
        for t in tablas:
            cur.execute(f'PRAGMA table_info({t})')
            cols = [c[1] for c in cur.fetchall()]
            texto = [c for c in cols
                     if any(k in c.lower() for k in ('home', 'away', 'local',
                                                     'visit', 'equipo', 'match'))]
            if not texto:
                continue
            for c in texto:
                try:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE LOWER({c}) LIKE '%puebla%'")
                    n = cur.fetchone()[0]
                except Exception:
                    continue
                if n:
                    print(f'  tabla {t}, columna {c}: {n} filas con Puebla')
                    hallado = True
                    break
        if not hallado:
            print('  no se encuentran filas de Puebla en la base de cuotas')
        con.close()
    except Exception as ex:
        print(f'  {type(ex).__name__}: {ex}')

    print('\n' + '=' * 78)
    print('LECTURA')
    print('=' * 78)
    print('  Si el mercado también tiene el partido parejo, el 50-25-25 de la')
    print('  ficha no es un fallo: es que el ELO no es la última palabra.')
    print('  Medido sobre 7.361 partidos donde modelo y ELO discrepan, seguir')
    print('  al ELO habría acertado MENOS (34,89 % frente a 36,34 %).')


if __name__ == '__main__':
    main()
