#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v77 — ¿Por qué NO aparece este pick en la Capa 1?

Para qué sirve
--------------
La pregunta más frecuente del usuario no es "¿qué apuesto?" sino "¿por qué no
está X?". Hasta ahora había que leer código para responderla. Este script coge
cada candidato del último barrido y dice, filtro por filtro, cuál lo detuvo y
por cuánto.

Uso:
    python v77_auditar_capa1.py                  # todos
    python v77_auditar_capa1.py --liga "Liga MX"
    python v77_auditar_capa1.py --equipo Chivas
"""
import argparse
import json
import logging
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def motivos(p, u):
    """Lista de (filtro, valor, umbral, pasa) para un pick."""
    prob = p.get('prob') or 0
    ev = p.get('ev')
    cuota = p.get('cuota') or 0
    out = [('probabilidad', prob, u['prob_min'], prob > u['prob_min']),
           ('cuota', cuota, u['cuota_min'], cuota > u['cuota_min'])]
    if ev is None:
        out.append(('EV', None, u['ev_min'], False))
    else:
        out.append(('EV', ev, u['ev_min'], ev > u['ev_min']))
        out.append(('convicción prob×EV', round(prob * ev, 4), u['conviccion'],
                    prob * ev >= u['conviccion']))
        out.append(('techo de EV', ev, u['ev_max'], ev <= u['ev_max']))
    return out


def main(liga=None, equipo=None):
    logging.basicConfig(level=logging.WARNING)
    import alpha_finder as af
    r = af._ULTIMO_RESULTADO or af.apuestas_del_dia_universal()
    from config import LEAGUES as LG
    liga_a_clave = {c.get('nombre', k): k for k, c in LG.items()}

    en_capa1 = {(p.get('partido'), p.get('apuesta')) for p in (r.get('capa1') or [])}
    universo = ((r.get('capa1') or []) + (r.get('candidatos') or []) +
                (r.get('ev_extremo') or []) + (r.get('capa2') or []))
    if liga:
        universo = [p for p in universo if liga.lower() in str(p.get('liga', '')).lower()]
    if equipo:
        universo = [p for p in universo if equipo.lower() in str(p.get('partido', '')).lower()]

    print(f"{len(universo)} candidatos analizados "
          f"({len(r.get('capa1') or [])} en Capa 1)\n")
    resumen = {}
    for p in sorted(universo, key=lambda x: -(x.get('ev') or -9)):
        clave = liga_a_clave.get(p.get('liga', ''), str(p.get('liga', '')).lower())
        u = af.umbrales_liga(clave)
        ms = motivos(p, u)
        fallos = [m for m in ms if not m[3]]
        dentro = (p.get('partido'), p.get('apuesta')) in en_capa1
        estado = '✅ EN CAPA 1' if dentro else '❌ fuera'
        print(f"{estado}  {str(p.get('deporte'))[:6]:6s} {str(p.get('liga'))[:16]:16s} "
              f"{str(p.get('partido'))[:32]:32s} {str(p.get('apuesta'))[:22]:22s}")
        for nombre, val, umb, pasa in ms:
            marca = 'ok  ' if pasa else 'FALLA'
            v = 'sin cuota' if val is None else f"{val:.4f}"
            print(f"       {marca} {nombre:20s} {v:>10s}  (umbral {umb})")
        for f in fallos:
            resumen[f[0]] = resumen.get(f[0], 0) + 1
        print()
    print('--- por qué se cae la gente ---')
    for k, v in sorted(resumen.items(), key=lambda x: -x[1]):
        print(f"   {k:22s} descarta {v} candidatos")
    print(f"\nUmbral vigente (general): {af.umbrales_liga(None)}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--liga')
    ap.add_argument('--equipo')
    a = ap.parse_args()
    main(a.liga, a.equipo)
