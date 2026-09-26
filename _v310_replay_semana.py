# -*- coding: utf-8 -*-
"""
v310 — LAS APUESTAS QUE DIO LA TARJETA, REPRODUCIDAS Y LIQUIDADAS, CON LA
REGLA VIEJA Y CON LA NUEVA, A LAS CUOTAS REALES DE PLAYDOIT.

El usuario: «puedes hacer simulaciones de apuestas que tú das y si encajan
perfectamente con el resultado es que tenemos éxito con el modelo».

QUÉ SE REPRODUCE
Cada pronóstico del día que el bot commitea (`pronostico_dia.json`, en git
desde el 2026-09-19) es una foto con la probabilidad del modelo y los precios
de Playdoit de ESE momento. Para cada partido de fútbol se toma la ÚLTIMA foto
anterior a su inicio y se pasa por `modo_modelo.recomendadas`, exactamente la
función de la tarjeta, y se queda lo que la tarjeta enseña (la principal y las
alternativas «meter»).

SIN MIRAR EL FUTURO
Los históricos que alimentan córners, tarjetas y remates se RECORTAN a lo
anterior a la fecha de cada partido (`panel_equipos._CACHE` y
`remates_fotmob._leer`), y se vacían sus cachés en cada fecha. Si no, el
propio partido estaría dentro de la media de sus últimos diez.

LAS DOS REGLAS
    vieja   la de la v309: tarjetas y remates sin mezclar con la media, los
            conteos corregidos por banda de cuota, «meter» con ≥ 65 %
    nueva   la de la v310: tarjetas/remates a medio camino de la media de su
            competición y los conteos SIN corrección por banda
    (con V310_CUOTA_METER=1.40 se reproduce la variante de cuota mínima, que
    se midió y se rechazó: ver `veredicto_pick.CUOTA_METER_FUTBOL`)

LIQUIDACIÓN: marcador y estadística del partido (histórico, ESPN o la ficha
de FotMob), con `pronosticos_guardados._valor_real` / `_acierto`.

Uso: python _v310_replay_semana.py    (escribe _v310_replay_semana.json)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

DESDE = '2026-09-19'
SALIDA = os.environ.get('V310_SALIDA', '_v310_replay_semana.json')


def fotos():
    hs = [l.split() for l in subprocess.check_output(
        ['git', 'log', '--reverse', '--format=%h %ct', '--since=' + DESDE,
         '--', 'pronostico_dia.json'], text=True).splitlines() if l.strip()]
    import horario as hz
    ult = {}
    for h, ts in hs:
        ts = float(ts)
        try:
            d = json.loads(subprocess.check_output(
                ['git', 'show', h + ':pronostico_dia.json']))
        except Exception:
            continue
        for p in (d.get('datos') or d).get('pronosticos') or []:
            if str(p.get('deporte') or '') != 'Fútbol' or p.get('sin_modelo'):
                continue
            ini = hz._a_utc(p.get('inicio'))
            if ini is None or ini.timestamp() <= ts:
                continue                       # ya empezado: no es previo
            if not (p.get('implicitas') or {}):
                continue                       # sin precio no hay apuesta
            k = (p.get('clave_liga'), p.get('partido'), str(p.get('inicio')))
            ult[k] = (ts, p)                   # la última foto previa
    return [p for _ts, p in ult.values()]


class Recorte:
    """Los históricos recortados a lo anterior a una fecha."""

    def __init__(self):
        import panel_equipos as pe
        import remates_fotmob as rf
        self.pe, self.rf = pe, rf
        self.completo = {}
        self.corte = None
        self._leer_orig = rf._leer
        rec = self

        def _leer(ruta, cols):
            d = rec._leer_orig(ruta, cols)
            if rec.corte is not None and 'fecha' in d.columns:
                d = d[pd.to_datetime(d['fecha'], errors='coerce') < rec.corte]
            return d
        rf._leer = _leer

    def fijar(self, fecha: pd.Timestamp, claves):
        import rendimiento_equipos as rq
        import contexto_partido as cx
        self.corte = fecha
        for c in claves:
            if c not in self.completo:
                self.pe._CACHE.pop(c, None)
                self.completo[c] = self.pe._historico(c).copy()
            full = self.completo[c]
            if full is not None and not full.empty and 'date' in full.columns:
                self.pe._CACHE[c] = full[full['date'] < fecha].reset_index(drop=True)
        for mod in (rq, cx, self.rf):
            for nombre, v in vars(mod).items():
                if isinstance(v, dict) and (nombre.startswith('_CACHE')
                                            or nombre.startswith('_MEMO')) \
                        and nombre != '_CACHE_TENIS':
                    v.clear()


def recos_de(pick: dict, regla: str) -> list:
    import modo_modelo as mm
    import rendimiento_equipos as rq
    import veredicto_pick as vp
    mezcla, cuota = dict(rq.MEZCLA_MEDIA), vp.CUOTA_METER_FUTBOL
    sin_corr = vp.MERCADOS_SIN_CORRECCION
    if regla == 'vieja':
        # la v309: sin mezcla, conteos corregidos por banda, sin cuota mínima
        rq.MEZCLA_MEDIA.clear()
        vp.CUOTA_METER_FUTBOL = None
        vp.MERCADOS_SIN_CORRECCION = ()
    elif os.environ.get('V310_CUOTA_METER'):
        # la variante rechazada, para reproducir su medición
        vp.CUOTA_METER_FUTBOL = float(os.environ['V310_CUOTA_METER'])
    try:
        for nombre, v in vars(rq).items():
            if isinstance(v, dict) and nombre.startswith('_CACHE_MEDIA'):
                v.clear()
        q = dict(pick)
        _rm = mm.remates_tarjeta(q) or {}
        bloques = {'Córners': mm.corners_tarjeta(q),
                   'Tarjetas': mm.tarjetas_tarjeta(q),
                   'Remates': _rm.get('totales'),
                   'Remates a puerta': _rm.get('a_puerta')}
        recos = mm.recomendadas(q, bloques, n=mm.MAX_RECOMENDADAS) or []
    finally:
        rq.MEZCLA_MEDIA.clear()
        rq.MEZCLA_MEDIA.update(mezcla)
        vp.CUOTA_METER_FUTBOL = cuota
        vp.MERCADOS_SIN_CORRECCION = sin_corr
    return recos[:1] + [o for o in recos[1:]
                        if o.get('veredicto_vp') != 'no_meter']


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import dia_picks as dp
    import horario as hz
    import partidos_jugados as pj
    import pronosticos_guardados as pg
    t0 = time.time()
    picks = fotos()
    print('partidos de fútbol con precio y foto previa:', len(picks), flush=True)
    rec = Recorte()
    por_fecha = {}
    for p in picks:
        f = pd.Timestamp(hz._a_utc(p['inicio']).date())
        por_fecha.setdefault(f, []).append(p)
    filas_partido = []
    for fecha in sorted(por_fecha):
        grupo = por_fecha[fecha]
        rec.fijar(fecha, {p.get('clave_liga') for p in grupo})
        for p in grupo:
            q = dict(p, jugado=True)
            for regla in ('vieja', 'nueva'):
                try:
                    q['recos_' + regla] = [pg._fila(r) for r in recos_de(p, regla)]
                except Exception as e:
                    print('  fallo', p.get('partido'), regla, e)
                    q['recos_' + regla] = []
            q['recomendadas_previas'] = q['recos_vieja'] + q['recos_nueva']
            filas_partido.append(q)
        print(fecha.date(), len(grupo), 'partidos · %.0f s' % (time.time() - t0),
              flush=True)
    rec.corte = None
    # marcador y estadística, por día de CDMX
    por_dia = {}
    for q in filas_partido:
        por_dia.setdefault(dp.dia_de(q), []).append(q)
    for dia, lista in sorted(por_dia.items()):
        fm = pj.marcadores_fotmob(dia)
        pj.poner_marcadores(lista, dia, fotmob=fm)
    # liquidación
    filas = []
    for q in filas_partido:
        gh, ga = q.get('goles_home'), q.get('goles_away')
        if gh is None:
            continue
        import modo_modelo as mm
        h, a = mm._equipos(q)
        stats = q.get('stats_partido')
        for regla in ('vieja', 'nueva'):
            for i, f in enumerate(q['recos_' + regla]):
                real = pg._valor_real(f, gh, ga, stats)
                ok, _d = pg._acierto(f, real, h, a)
                filas.append({'regla': regla, 'principal': i == 0,
                              'liga': q.get('clave_liga'),
                              'torneo': q.get('liga'),
                              'partido': q.get('partido'),
                              'dia': dp.dia_de(q),
                              'mercado': f.get('mercado'),
                              'apuesta': f.get('apuesta'),
                              'veredicto': f.get('veredicto'),
                              'prob': f.get('prob'),
                              'prob_meter': f.get('prob_meter'),
                              'cuota': f.get('cuota'),
                              'acierto': None if ok is None else int(bool(ok))})
    d = pd.DataFrame(filas)
    d.to_csv(SALIDA.replace('.json', '.csv'), index=False)
    doc = {'partidos': len(filas_partido),
           'con_resultado': int(sum(1 for q in filas_partido
                                    if q.get('goles_home') is not None)),
           'reglas': {}}
    liq = d[d['acierto'].notna() & d['cuota'].notna()]
    for regla in ('vieja', 'nueva'):
        x = liq[(liq['regla'] == regla) & (liq['veredicto'] == 'meter')]
        r = {'n': int(len(x))}
        if len(x):
            gan = x['acierto'] * x['cuota'] - 1
            rng = np.random.default_rng(310)
            bs = [gan.values[rng.integers(0, len(gan), len(gan))].mean()
                  for _ in range(2000)]
            r.update(prometido=round(float(x['prob_meter'].mean()), 4),
                     real=round(float(x['acierto'].mean()), 4),
                     cuota=round(float(x['cuota'].mean()), 3),
                     roi=round(float(gan.mean()), 4),
                     p5=round(float(np.percentile(bs, 5)), 4),
                     por_mercado={m: {'n': int(len(g)),
                                      'prometido': round(float(g['prob_meter'].mean()), 3),
                                      'real': round(float(g['acierto'].mean()), 3),
                                      'roi': round(float((g['acierto'] * g['cuota'] - 1).mean()), 3)}
                                  for m, g in x.groupby('mercado')})
        doc['reglas'][regla] = r
        print(regla, json.dumps(r, ensure_ascii=False))
    json.dump(doc, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1)


if __name__ == '__main__':
    main()
