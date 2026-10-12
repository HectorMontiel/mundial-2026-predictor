#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v370 — ¿Se puede hacer un boleto largo «tipo Draftea» con nuestras apuestas?

El usuario (11-oct), con un boleto de Draftea de 21 patas (×618, $191 →
$117.995): «quiero lograr hacer este tipo de apuestas con las soñadoras».

Ese boleto son favoritos a cuota corta (−150 a −800: 1,12-1,67) de varios
deportes. Aquí se reconstruye, con lo que la app dijo «meter» y quedó
ARCHIVADO AL PITIDO (jugados_ayer / jugados_dia en git, liquidado con
`pronosticos_guardados.validar`), qué habría pasado cada día con un boleto de
N patas, una por partido:
  · ⭐ sólo ELIGE;  · ⭐ y luego el resto, de la que más se cumple a la que
    menos;  · todas las «se mete» por probabilidad.
Para cada N: días con patas suficientes, boletos enteros, momio medio, cuántas
patas fallaron (0, 1, 2+) y la ganancia por $100. Y la alternativa de partir
las mismas patas en boletos chicos (4 de 5, 2 de 10).
Escribe `_v370_boleto_largo.json`.
"""
import json
import subprocess
import sys

import numpy as np

sys.path.insert(0, '.')


def archivos():
    commits = subprocess.run(['git', 'log', '--format=%h', '--since=2026-10-02', '--',
                              'jugados_ayer.json', 'jugados_dia.json'],
                             capture_output=True, text=True).stdout.split()
    por_dia = {}
    for c in commits:
        for f in ('jugados_ayer.json', 'jugados_dia.json'):
            r = subprocess.run(['git', 'show', '%s:%s' % (c, f)], capture_output=True)
            if r.returncode:
                continue
            try:
                d = json.loads(r.stdout.decode('utf-8'))
            except Exception:
                continue
            dia = d.get('dia')
            if dia and dia not in por_dia and d.get('partidos'):
                por_dia[dia] = d['partidos']
    return por_dia


def patas(por_dia):
    import modo_modelo as mm
    import pronosticos_guardados as pg
    out = {}
    for dia, ps in por_dia.items():
        L = []
        for p in ps:
            if p.get('solo_mercado') or p.get('sin_modelo') or p.get('aplazado'):
                continue
            dep = str(p.get('deporte') or 'Fútbol')
            for fl in pg.validar(p) or []:
                if fl.get('veredicto') != 'meter' or fl.get('estado') not in (pg.CUMPLIDO, pg.FALLADO):
                    continue
                try:
                    cu = float(fl.get('cuota'))
                except (TypeError, ValueError):
                    continue
                pr = fl.get('prob_meter') if fl.get('prob_meter') is not None else fl.get('prob')
                ele = mm.elige(dict(fl, veredicto_vp='meter'), dep)
                L.append({'partido': p.get('partido'), 'dep': dep, 'cuota': cu,
                          'prob': float(pr or 0), 'elige': ele,
                          'real': 0.86 if ele else 0.79,
                          'ok': fl['estado'] == pg.CUMPLIDO})
        out[dia] = L
    return out


def elegir(L, n, modo):
    if modo == 'solo_elige':
        L = [x for x in L if x['elige']]
        clave = lambda x: -x['prob']
    elif modo == 'elige_y_resto':
        clave = lambda x: (not x['elige'], -x['prob'])
    else:
        clave = lambda x: -x['prob']
    vistos, out = set(), []
    for x in sorted(L, key=clave):
        if x['partido'] in vistos:
            continue
        vistos.add(x['partido'])
        out.append(x)
        if len(out) == n:
            return out
    return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    por_dia = archivos()
    P = patas(por_dia)
    dias = sorted(d for d in P if d >= '2026-10-05')     # la regla de hoy (⭐ desde v360)
    R = {'dias': dias, 'patas_por_dia': {d: len(P[d]) for d in dias},
         'acierto_patas': {}}
    todas = [x for d in dias for x in P[d]]
    for k, f in (('⭐', lambda x: x['elige']), ('resto', lambda x: not x['elige'])):
        q = [x for x in todas if f(x)]
        R['acierto_patas'][k] = {'n': len(q), 'acierto': round(np.mean([x['ok'] for x in q]), 4),
                                 'cuota': round(np.mean([x['cuota'] for x in q]), 3)}
    R['boletos'] = {}
    for modo in ('solo_elige', 'elige_y_resto', 'todas_por_prob'):
        for n in (3, 5, 8, 10, 15, 20):
            res = []
            for d in dias:
                b = elegir(P[d], n, modo)
                if not b:
                    continue
                fallos = sum(1 for x in b if not x['ok'])
                momio = float(np.prod([x['cuota'] for x in b]))
                res.append({'dia': d, 'fallos': fallos, 'momio': momio,
                            'teorico': float(np.prod([x['real'] for x in b]))})
            if not res:
                continue
            enteros = [r for r in res if r['fallos'] == 0]
            R['boletos']['%s · %d patas' % (modo, n)] = {
                'dias': len(res), 'enteros': len(enteros),
                'momio_medio': round(np.mean([r['momio'] for r in res]), 2),
                'sale_teorico': round(np.mean([r['teorico'] for r in res]), 4),
                'fallos_1': sum(1 for r in res if r['fallos'] == 1),
                'fallos_2_mas': sum(1 for r in res if r['fallos'] >= 2),
                'gan_100': round(100 * np.mean([(r['momio'] - 1) if r['fallos'] == 0 else -1
                                                for r in res]), 1),
                'por_dia': [(r['dia'], r['fallos'], round(r['momio'], 1)) for r in res]}
    # partir 20 patas en boletos chicos (las mismas patas: ⭐ y resto)
    R['partir'] = {}
    for n_total, trozo in ((20, 5), (20, 10), (10, 5)):
        gan, n_b, enteros = 0.0, 0, 0
        for d in dias:
            b = elegir(P[d], n_total, 'elige_y_resto')
            if not b:
                continue
            for i in range(0, n_total, trozo):
                t = b[i:i + trozo]
                ok = all(x['ok'] for x in t)
                m = float(np.prod([x['cuota'] for x in t]))
                n_b += 1
                enteros += ok
                gan += (m - 1) if ok else -1
        if n_b:
            R['partir']['%d patas en boletos de %d' % (n_total, trozo)] = {
                'boletos': n_b, 'enteros': enteros, 'gan_100': round(100 * gan / n_b, 1)}
    json.dump(R, open('_v370_boleto_largo.json', 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1, default=str)
    print(json.dumps({k: R[k] for k in ('dias', 'patas_por_dia', 'acierto_patas')},
                     ensure_ascii=False))
    for k, v in R['boletos'].items():
        print(k, {x: v[x] for x in v if x != 'por_dia'})
    for k, v in R['partir'].items():
        print(k, v)


if __name__ == '__main__':
    main()
