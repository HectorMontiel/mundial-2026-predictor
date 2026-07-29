#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Diagnóstico del barrido diario: DÓNDE se va el tiempo y POR QUÉ las
probabilidades salen planas.

No cambia nada. Solo instrumenta `apuestas_del_dia_universal`, cronometra cada
fase y vuelca la distribución de las probabilidades emitidas por deporte,
separando la probabilidad ANTES y DESPUÉS del encogimiento hacia el mercado.
"""
import json
import logging
import time
import sys
from collections import defaultdict

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('diag')

FASES = []


def cronometrar(mod, nombre):
    """Envuelve una función de módulo para medir su tiempo acumulado."""
    orig = getattr(mod, nombre, None)
    if orig is None or not callable(orig):
        return
    estado = {'n': 0, 't': 0.0}

    def envuelto(*a, **kw):
        t0 = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            dt = time.perf_counter() - t0
            estado['n'] += 1
            estado['t'] += dt
    envuelto.__name__ = nombre
    setattr(mod, nombre, envuelto)
    FASES.append((f"{mod.__name__}.{nombre}", estado))


def main():
    t_import = time.perf_counter()
    import alpha_finder
    import cuotas_multi
    import calibracion_mercado
    t_import = time.perf_counter() - t_import
    log.info(f"import de módulos: {t_import:.2f}s")

    # Fases candidatas a ser el cuello de botella
    for mod, fn in ((alpha_finder, '_picks_mlb'),
                    (alpha_finder, '_picks_tenis'),
                    (alpha_finder, '_picks_nba'),
                    (alpha_finder, '_cuotas_tenis_multi'),
                    (alpha_finder, '_barrido_fixtures'),
                    (alpha_finder, 'apuestas_del_dia'),
                    (cuotas_multi, 'odds_partido'),
                    (cuotas_multi, 'todas_las_cuotas')):
        cronometrar(mod, fn)

    t0 = time.perf_counter()
    res = alpha_finder.apuestas_del_dia_universal(max_partidos=40)
    total = time.perf_counter() - t0

    print("\n" + "=" * 72)
    print(f"TIEMPO TOTAL DEL BARRIDO: {total:.1f}s  (imports aparte: {t_import:.1f}s)")
    print("=" * 72)
    for nombre, e in sorted(FASES, key=lambda x: -x[1]['t']):
        if e['n']:
            print(f"  {nombre:42s} {e['t']:7.2f}s  ({e['n']} llamadas, "
                  f"{e['t']/e['n']:.3f}s/llamada)")

    # ---- distribución de probabilidades -------------------------------
    print("\n" + "=" * 72)
    print("DISTRIBUCIÓN DE PROBABILIDADES EMITIDAS")
    print("=" * 72)
    cubos = defaultdict(lambda: defaultdict(int))
    desplaz = defaultdict(list)
    for capa in ('capa1', 'capa2', 'candidatos', 'confianza'):
        for p in (res.get(capa) or []):
            dep = p.get('deporte', '?')
            pr = p.get('prob')
            if pr is None:
                continue
            b = min(int(pr * 20) * 5, 95)
            cubos[dep][b] += 1
            cal = p.get('calibracion') or {}
            if cal.get('aplicado'):
                desplaz[dep].append(cal.get('desplazamiento', 0.0))

    for dep in sorted(cubos):
        tot = sum(cubos[dep].values())
        print(f"\n  {dep}  (n={tot})")
        for b in sorted(cubos[dep]):
            n = cubos[dep][b]
            barra = '#' * max(1, int(40 * n / max(tot, 1)))
            print(f"    {b:3d}-{b+5:3d}%  {n:4d}  {barra}")
        d = desplaz.get(dep) or []
        if d:
            med = sum(abs(x) for x in d) / len(d)
            print(f"    → encogimiento aplicado en {len(d)} picks, "
                  f"desplazamiento medio |Δ| = {med:.4f}")
        else:
            print("    → SIN encogimiento aplicado")

    resumen = {
        'total_s': round(total, 2),
        'import_s': round(t_import, 2),
        'fases': {n: {'s': round(e['t'], 2), 'n': e['n']}
                  for n, e in FASES if e['n']},
        'conteo': {c: len(res.get(c) or [])
                   for c in ('capa1', 'capa2', 'candidatos', 'confianza')},
        'avisos': res.get('avisos') or [],
    }
    with open('_v79_diag_barrido.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)
    print(f"\nConteo por capa: {resumen['conteo']}")
    print("Guardado en _v79_diag_barrido.json")


if __name__ == '__main__':
    sys.exit(main())
