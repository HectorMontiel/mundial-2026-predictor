#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
¿Sirven ya los snapshots de corners, tarjetas y remates? Se liquidan y se mira.

POR QUE EXISTEN. La v159 los empezo porque **no existe historico de lineas de
corners**: football-data no las publica y el de The Odds API es de pago. Sin
lineas pasadas no hay apuestas que liquidar, asi que la regla de oro del
proyecto —percentil 5 positivo en el tramo de juicio— no se podia ni aplicar a
esos mercados, y su EV sale marcado. El plan escrito era: «en unos meses habra
con que medir».

EL EMPAREJAMIENTO, QUE ES LO QUE FALTABA. Las fotos vienen de PLAYDOIT
(«Eyupspor», «Gaziantep FK») y los resultados de football-data («Ath Bilbao»,
«Ath Madrid»). Comparando los nombres tal cual casaban **0 de 167.700**. Pero
cada foto trae su `clave_liga`, asi que se puede emparejar DENTRO de esa liga
con `name_mapper`, que es justo para lo que esta hecho y donde acierta.

QUE CONTESTA: si apostar el EV que este proyecto calcula para corners gana o
pierde dinero. Es la pregunta que esos ficheros llevan meses esperando poder
responder.
"""
import io
import sys
import unicodedata
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

# SOLO LAS FAMILIAS QUE SE SABEN INTERPRETAR, y esto no es un detalle.
#
# La primera pasada metia en el mismo saco «Total de tarjetas», «1a mitad -
# tarjetas exacto», «15 minutos - total tarjetas», «Impar/Par» y «Ambos equipos
# 2+», y las comparaba TODAS contra el total del partido. Resultado: un ROI del
# +76,93 % en tarjetas, que no es un hallazgo sino un artefacto de comparar una
# linea de media parte contra el marcador final.
#
# Se liquidan solo las familias de TOTAL DEL PARTIDO con mercado Mas/Menos. El
# resto —exactas, rangos, 1x2, impar/par, ventanas de 15 minutos, por equipo—
# necesitan cada una su propia regla, y una regla inventada da un numero con
# aspecto de ROI.
FICHEROS = {
    'corners': ('corners_snapshots.csv', 'corners',
                ('total tiros de esquina',)),
    'tarjetas': ('tarjetas_snapshots.csv', 'yellow',
                 ('total de tarjetas',)),
    'remates': ('remates_snapshots.csv', 'shots_on',
                ('remates a puerta totales',)),
}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().replace('.', '').replace('-', ' ').split())


def historico(clave, stat):
    import rendimiento_equipos as rq
    try:
        return rq._solo_reales(rq._historico(clave), stat)
    except Exception:
        return None


def traduce(nombres, catalogo):
    """{nombre de la casa: nombre del historico} con ambito de UNA liga."""
    try:
        import name_mapper
    except Exception:
        return {}
    cat = list(catalogo)
    out = {}
    for n in nombres:
        m = name_mapper.mapear(str(n), cat, contexto='snapshots')
        if m:
            out[n] = m
    return out


def liquida(ruta, stat, familias):
    s = pd.read_csv(ruta, low_memory=False)
    fam = s['familia'].astype(str).str.strip().str.lower()
    antes = len(s)
    s = s[fam.isin(familias)]
    print('  familias del total del partido: %d de %d fotos' % (len(s), antes))
    print('  %d fotos · %s -> %s' % (
        len(s), str(s['capturado_en'].min())[:10],
        str(s['capturado_en'].max())[:10]))
    total_casadas = 0
    filas = []
    for clave, sub in s.groupby('clave_liga'):
        d = historico(clave, stat)
        if d is None or getattr(d, 'empty', True):
            continue
        cat = sorted(set(d['home_team'].dropna()) | set(d['away_team'].dropna()))
        nombres = sorted(set(sub['home'].dropna()) | set(sub['away'].dropna()))
        tr = traduce(nombres, cat)
        if not tr:
            continue
        # indice de resultados de esa liga
        idx = {}
        for f in d.itertuples(index=False):
            idx[(str(f.date)[:10], str(f.home_team), str(f.away_team))] = f
        for r in sub.itertuples(index=False):
            h = tr.get(getattr(r, 'home', None))
            a = tr.get(getattr(r, 'away', None))
            if not h or not a:
                continue
            real = idx.get((str(getattr(r, 'fecha_partido', ''))[:10], h, a))
            if real is None:
                continue
            total_casadas += 1
            filas.append((r, real))
    print('  fotos con resultado real: %d de %d (%.1f %%)'
          % (total_casadas, len(s), 100.0 * total_casadas / max(len(s), 1)))
    return filas


def valor_real(real, familia, stat):
    """
    El valor que hay que comparar contra la linea.

    En tarjetas se cuentan AMARILLAS MAS ROJAS, que es lo que cuenta la casa y
    lo que el proyecto ya tiene medido (§ de `lambda_tarjetas_equipo`: contar
    solo amarillas producia un sesgo sistematico de -0,056 a -0,083 contra las
    lineas reales).
    """
    ch = getattr(real, 'home_%s' % stat, None)
    ca = getattr(real, 'away_%s' % stat, None)
    if stat == 'yellow':
        try:
            ch = float(ch) + float(getattr(real, 'home_red', 0) or 0)
            ca = float(ca) + float(getattr(real, 'away_red', 0) or 0)
        except (TypeError, ValueError):
            pass
    if ch is None or ca is None:
        return None
    try:
        ch, ca = float(ch), float(ca)
    except (TypeError, ValueError):
        return None
    f = str(familia or '').lower()
    if 'local' in f or 'home' in f:
        return ch
    if 'visit' in f or 'away' in f:
        return ca
    return ch + ca


def main():
    for etiqueta, (ruta, stat, familias) in FICHEROS.items():
        print()
        print('=' * 70)
        print('  %s' % etiqueta.upper())
        print('=' * 70)
        try:
            filas = liquida(ruta, stat, familias)
        except Exception as e:
            print('  error: %s: %s' % (type(e).__name__, e))
            continue
        if not filas:
            print('  -> nada que liquidar')
            continue
        # UNA apuesta por (partido, mercado, linea): la foto MAS CERCANA al
        # partido, que es el precio al que de verdad se habria jugado.
        mejor = {}
        for r, real in filas:
            k = (getattr(r, 'snapshot_key', None), getattr(r, 'mercado', None),
                 getattr(r, 'linea', None))
            d = getattr(r, 'dias_al_partido', 99)
            if k not in mejor or d < mejor[k][2]:
                mejor[k] = (r, real, d)
        print('  apuestas unicas (partido x mercado x linea): %d' % len(mejor))
        res = []
        for r, real, _ in mejor.values():
            v = valor_real(real, getattr(r, 'familia', ''), stat)
            if v is None:
                continue
            try:
                linea = float(getattr(r, 'linea'))
                cuota = float(getattr(r, 'cuota'))
            except (TypeError, ValueError):
                continue
            if cuota <= 1.0 or v == linea:
                continue
            m = str(getattr(r, 'mercado', '')).lower()
            if 'mas' in m or 'más' in m or 'over' in m:
                gana = v > linea
            elif 'menos' in m or 'under' in m:
                gana = v < linea
            else:
                continue
            res.append((cuota - 1.0) if gana else -1.0)
        if not res:
            print('  -> ninguna apuesta liquidable (mercados no reconocidos)')
            continue
        res = np.array(res, dtype=float)
        roi = 100.0 * res.mean()
        # percentil 5 por bootstrap, la regla de oro del proyecto
        rng = np.random.default_rng(7)
        p5 = np.percentile([rng.choice(res, len(res), replace=True).mean()
                            for _ in range(2000)], 5) * 100
        print()
        print('  APUESTAS LIQUIDADAS: %d' % len(res))
        print('  aciertos:            %.1f %%' % (100.0 * (res > 0).mean()))
        print('  ROI:                 %+.2f %%' % roi)
        print('  percentil 5 (boot):  %+.2f %%' % p5)
        print('  -> %s' % ('SUPERA la regla de oro (p5 > 0)' if p5 > 0
                           else 'NO supera la regla de oro'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
