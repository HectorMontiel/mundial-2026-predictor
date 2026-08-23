#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163.1 — LA REGLA DE CONTENCIÓN EMPAREJA EQUIPOS DISTINTOS.

Lo que se encontró
------------------
Mirando por qué la Champions salía sin modelo, apareció algo peor que un hueco:

    name_mapper.mapear('Viking FK', catalogo_champions)  ->  'Vikingur Reykjavik'

El Viking FK es de Stavanger (Noruega) y el Víkingur Reykjavík es de Islandia.
Son dos clubes distintos, y el emparejado no falla: acierta con confianza. Con
él, el modelo predice el partido con la fuerza del equipo equivocado y publica
una probabilidad que parece normal. **Un hueco se ve; esto no.**

Por qué pasa
------------
`normalizar` quita los sufijos societarios, así que «Viking FK» queda en
«viking». Después la regla de CONTENCIÓN acepta cualquier candidato que
contenga al objetivo como subcadena, y «viking» está dentro de «vikingur
reykjavik». La similitud real es 0,48 —muy por debajo del umbral de 0,78— pero
la contención se aplica ANTES y no mira el parecido.

La regla es necesaria: es la que casa «Roma» con «AS Roma» y «Betis» con «Real
Betis». La diferencia entre esos y el Viking es que ahí el objetivo aparece como
PALABRA COMPLETA («as **roma**»), y en el Viking parte una palabra por la mitad
(«**viking**ur»).

Qué mide este script
--------------------
Cuánto cambia exigir que la contención respete los límites de palabra, sobre
TODOS los emparejados que hace el proyecto de verdad: cada equipo del histórico
de cada competición activa contra el catálogo de su motor, y contra el catálogo
de ESPN. Se listan uno a uno los que cambian, para poder mirarlos.

    python _v163_contencion_enganosa.py
"""
import json
import logging
import re
import sys
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_contencion_enganosa.json'


MIN_PREFIJO = 3


def contenido_por_palabras(objetivo: str, candidato: str) -> bool:
    """
    ¿La contención entre estos dos nombres es de fiar?

    LA PRIMERA VERSIÓN EXIGÍA PALABRA COMPLETA Y ERA DEMASIADO ESTRICTA. Medido
    sobre 1.779 emparejados del proyecto, tumbaba tres y dos eran correctos:

        Manchester City      -> Man City             (se perdía)
        West Bromwich Albion -> West Brom            (se perdía)
        Viking FK            -> Vikingur Reykjavik   (se perdía, y ése sobraba)

    O sea que truncar una palabra —«man» por «manchester», «brom» por
    «bromwich»— es legítimo y hay que conservarlo. Lo que distingue esos dos
    del Viking no es la truncación: es que allí OTRA palabra casa entera y aquí
    no casa ninguna.

        {man, city}  contra {manchester, city}   -> «city» casa entera
        {west, brom} contra {west, bromwich, albion} -> «west» casa entera
        {viking}     contra {vikingur, reykjavik}    -> NINGUNA casa entera

    Y no vale con exigir parecido: «Ajax» contra «Ajax Amsterdam» tiene 0,44 de
    similitud —MENOS que el 0,50 del Viking— y es correcto. Lo que lo salva es
    que «ajax» está entero.

    Y OJO, QUE «CITY» ES RUIDO. `normalizar` borra los sufijos societarios y
    « city» está en la lista, así que «Man City» queda en «man» y «Manchester
    City» en «manchester»: la palabra que sostenía ese emparejado desaparece
    antes de llegar aquí. Con «al menos una entera» se perdía.

    El discriminante que aguanta los seis casos es otro: **cuántas palabras le
    SOBRAN al nombre largo**.

        man        contra manchester            -> no sobra ninguna  -> es el
                                                   mismo nombre truncado
        viking     contra vikingur reykjavik    -> sobra «reykjavik» y ninguna
                                                   casa entera       -> OTRO club
        ajax       contra ajax amsterdam        -> sobra «amsterdam» pero
                                                   «ajax» casa entera -> vale

    Regla final: cada palabra del corto tiene que casar con una del largo
    —entera, o como prefijo de tres letras o más— y, si al largo le sobran
    palabras, al menos una tiene que casar ENTERA. Una palabra entera es una
    prueba; un prefijo suelto con otra palabra sin explicar, no.
    """
    corto, largo = sorted((objetivo, candidato), key=len)
    if corto not in largo:
        return False
    t_corto, t_largo = corto.split(), list(largo.split())
    if not t_corto or not t_largo:
        return False
    exactas, restantes = 0, list(t_largo)
    for p in t_corto:
        if p in restantes:
            restantes.remove(p)
            exactas += 1
            continue
        cand = [q for q in restantes
                if len(p) >= MIN_PREFIJO and q.startswith(p)]
        if not cand:
            return False
        restantes.remove(cand[0])
    return exactas >= 1 or not restantes


def main():
    import name_mapper as nm

    # el caso que lo destapó, primero y a la vista
    print('=' * 78)
    print('EL CASO QUE LO DESTAPÓ')
    print('=' * 78)
    for objetivo, cand in (('Viking FK', 'Vikingur Reykjavik'),
                           ('Roma', 'AS Roma'),
                           ('Betis', 'Real Betis'),
                           ('Ajax', 'Ajax Amsterdam'),
                           ('Man City', 'Manchester City'),
                           ('West Brom', 'West Bromwich Albion')):
        o, c = nm.normalizar(objetivo), nm.normalizar(cand)
        from difflib import SequenceMatcher
        print('%-14s vs %-22s  subcadena=%-5s  por palabras=%-5s  '
              'similitud=%.2f'
              % (objetivo, cand, (o in c or c in o),
                 contenido_por_palabras(o, c),
                 SequenceMatcher(None, o, c).ratio()))

    print()
    print('=' * 78)
    print('CUÁNTOS EMPAREJADOS CAMBIAN EN TODO EL PROYECTO')
    print('=' * 78)
    import fixtures_espn
    import rendimiento_equipos as rq
    from config import LEAGUES

    cambios, total = [], 0
    claves = [c for c, v in LEAGUES.items()
              if v.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    for clave in claves:
        try:
            from league_engine import ClubEngine
            eng = ClubEngine(clave)
            catalogo = list(eng.stats.keys())
        except Exception:
            continue
        if not catalogo:
            continue
        d = rq._historico(clave)
        if d is None or getattr(d, 'empty', True):
            continue
        import pandas as pd
        corte = d['date'].max() - pd.Timedelta(days=400)
        rec = d[d['date'] >= corte]
        nombres = sorted(set(rec['home_team'].astype(str))
                         | set(rec['away_team'].astype(str)))
        # y los nombres que llegan de ESPN, que son los que de verdad se mapean
        try:
            nombres += [f.get('home') for f in
                        fixtures_espn.fixtures_liga(clave, dias=3)]
            nombres += [f.get('away') for f in
                        fixtures_espn.fixtures_liga(clave, dias=3)]
        except Exception:
            pass
        nombres = sorted({str(n) for n in nombres if n})
        for n in nombres:
            total += 1
            antes = nm.mapear(n, catalogo, contexto='medicion')
            despues = _mapear_estricto(n, catalogo, nm)
            if antes != despues:
                cambios.append({'clave': clave, 'nombre': n,
                                'antes': antes, 'despues': despues})
        print('%-22s %3d nombres · %d cambios acumulados'
              % (clave, len(nombres), len(cambios)), flush=True)

    print()
    print('%d emparejados revisados · %d cambian (%.2f %%)'
          % (total, len(cambios), 100.0 * len(cambios) / max(total, 1)))
    print()
    for c in cambios:
        print('   %-18s %-28s %-24s -> %s'
              % (c['clave'], c['nombre'][:28], str(c['antes'])[:24],
                 c['despues']))
    json.dump({'total': total, 'cambios': cambios},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


def _mapear_estricto(nombre, catalogo, nm):
    """`mapear` con la contención exigiendo límites de palabra."""
    from difflib import SequenceMatcher
    catalogo = list(catalogo)
    if not catalogo:
        return None
    if nombre in catalogo:
        return nombre
    objetivo = nm.normalizar(nombre)
    alias = nm._cargar_alias()
    for destino in alias.get(objetivo, ()):
        if destino in catalogo:
            return destino
    normalizados = {c: nm.normalizar(c) for c in catalogo}
    for c, n in normalizados.items():
        if n == objetivo:
            return c
    obj_exp = nm._expandir(objetivo)
    for c, n in normalizados.items():
        if nm._expandir(n) == obj_exp:
            return c
    fuera = ('de', 'del', 'la', 'el')
    sin_conector = ' '.join(w for w in obj_exp.split() if w not in fuera)
    for c, n in normalizados.items():
        if ' '.join(w for w in nm._expandir(n).split()
                    if w not in fuera) == sin_conector:
            return c
    contenidos = [c for c, n in normalizados.items()
                  if len(objetivo) >= 5 and contenido_por_palabras(objetivo, n)]
    if contenidos:
        return max(contenidos,
                   key=lambda c: (SequenceMatcher(None, objetivo,
                                                  normalizados[c]).ratio(),
                                  -abs(len(normalizados[c]) - len(objetivo))))
    mejor, ratio = None, 0.0
    for c, n in normalizados.items():
        s = SequenceMatcher(None, objetivo, n).ratio()
        if s > ratio:
            mejor, ratio = c, s
    return mejor if ratio >= nm.UMBRAL else None


if __name__ == '__main__':
    sys.exit(main())
