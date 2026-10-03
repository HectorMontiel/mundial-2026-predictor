# -*- coding: utf-8 -*-
"""
v324 — «NADA QUE METER»: ¿DE VERDAD NO HABÍA NADA?

El usuario: «no quiero que se vean las que no debo meter, pero tampoco
quiero perder la visibilidad de esos partidos… valida bien con el modelo,
simulaciones, los partidos recientes y el histórico si de verdad no hay
nada que meter, habiendo goles, ganador, doble oportunidad… y los que sí
deben tener algo, hay que mejorarlo».

LOS DATOS: los mismos que la réplica de la v312 (cada partido de fútbol
pronosticado desde el 2026-09-19 con la ÚLTIMA foto anterior a su inicio y
los precios de Playdoit de ese momento, históricos recortados a lo anterior
a su fecha: `_v310_replay_semana`), pero guardando TODAS las apuestas que
el modelo sabe tarifar —cada mercado y cada línea, no sólo las 12 que la
tarjeta preselecciona y una por familia de resultado—, cada una con:

  - la probabilidad ajustada del veredicto (`veredicto_pick.evaluar`),
  - el motivo por el que la regla la deja fuera (o vacío si se mete),
  - si la tarjeta de hoy la mete (`modo_modelo.recomendadas` + `metidas`),
  - y su acierto con el marcador y la ficha de FotMob.

Uso: python _v324_nada.py [--rehacer]   (caché: _v324_candidatas.csv.gz)
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

CACHE = os.environ.get('V324_CACHE', '_v324_candidatas.csv.gz')


def motivo(v, fav, lam) -> str:
    """Por qué la regla de la tarjeta deja fuera esta apuesta ('' si no)."""
    import modo_modelo as mm
    import veredicto_pick as vp
    if v.get('veredicto') != vp.METER:
        return 'menos de 65 %'
    return (vp.franja_futbol(v) or mm.corners_equipo_sin_favorito(v, fav)
            or mm.corners_margen_corto(v, lam) or '')


def marcadores_git() -> dict:
    """{(partido, día de inicio): (goles local, goles visita)} de todas las
    versiones de `jugados_dia.json` desde la primera foto."""
    import json
    import subprocess
    import _v310_replay_semana as rp
    out = {}
    hs = subprocess.check_output(
        ['git', 'log', '--format=%h', '--since=' + rp.DESDE, '--',
         'jugados_dia.json'], text=True).split()
    for h in hs:
        try:
            d = json.loads(subprocess.check_output(
                ['git', 'show', h + ':jugados_dia.json']))
        except Exception:
            continue
        for p in d.get('partidos') or []:
            gh, ga = p.get('goles_home'), p.get('goles_away')
            if gh is None or ga is None or p.get('aplazado'):
                continue
            out.setdefault((p.get('partido'), str(p.get('inicio'))[:10]),
                           (float(gh), float(ga)))
    print('marcadores en git:', len(out), flush=True)
    return out


def construir() -> pd.DataFrame:
    import dia_picks as dp
    import horario as hz
    import modo_modelo as mm
    import partidos_jugados as pj
    import pronosticos_guardados as pg
    import valor_apuesta as va
    import veredicto_pick as vp
    import _v310_replay_semana as rp
    t0 = time.time()
    picks = rp.fotos()
    print('partidos con foto previa y precio:', len(picks), flush=True)
    rec = rp.Recorte()
    por_fecha = {}
    for p in picks:
        por_fecha.setdefault(pd.Timestamp(hz._a_utc(p['inicio']).date()),
                             []).append(p)
    partidos = []
    for fecha in sorted(por_fecha):
        grupo = por_fecha[fecha]
        rec.fijar(fecha, {p.get('clave_liga') for p in grupo})
        for p in grupo:
            q = dict(p)
            todas, metidas, elite = [], [], None
            try:
                _rm = mm.remates_tarjeta(q) or {}
                bloques = {'Córners': mm.corners_tarjeta(q),
                           'Tarjetas': mm.tarjetas_tarjeta(q),
                           'Remates': _rm.get('totales'),
                           'Remates a puerta': _rm.get('a_puerta')}
                recos = mm.recomendadas(q, bloques, n=mm.MAX_RECOMENDADAS) or []
                metidas = [r.get('apuesta') for r in mm.metidas(recos)]
                fav = mm.prob_favorito(q)
                lam = mm.lambdas_corners(q, bloques)
                for i, f in enumerate(va.candidatos(q, bloques) or []):
                    c = mm._enriquece(q, f, i + 1)
                    v = vp.evaluar(c, con_contexto=False)
                    v['pick'] = c
                    c['_motivo'] = motivo(v, fav, lam)
                    c['_ajustada'] = v.get('prob_ajustada')
                    todas.append(c)
                # la Capa 1 (`lo_mejor`) entra en la tarjeta con su propia
                # fila, que puede no estar entre las candidatas de arriba
                for r in recos:
                    if r.get('elite'):
                        elite = r.get('apuesta')
                        if elite not in [c.get('apuesta') for c in todas]:
                            c = dict(r, _motivo='', _ajustada=r.get('prob_meter'))
                            todas.append(c)
            except Exception as e:
                print('  fallo', p.get('partido'), e)
            q.update(_todas=todas, _metidas=metidas, _elite=elite,
                     _fav=mm.prob_favorito(q), jugado=True)
            partidos.append(q)
        print(fecha.date(), len(grupo), '· %.0f s' % (time.time() - t0),
              flush=True)
    rec.corte = None
    por_dia = {}
    for q in partidos:
        por_dia.setdefault(dp.dia_de(q), []).append(q)
    for dia, lista in sorted(por_dia.items()):
        pj.poner_marcadores(lista, dia, fotmob=pj.marcadores_fotmob(dia))
    # FotMob no siempre es alcanzable (desde el contenedor de pruebas no lo
    # es): el marcador que falte se toma del archivo de finalizados que el
    # cron guarda en git (`jugados_dia.json`, todas sus versiones).
    marc = marcadores_git()
    for q in partidos:
        if q.get('goles_home') is None:
            m = marc.get((q.get('partido'), str(q.get('inicio'))[:10]))
            if m:
                q['goles_home'], q['goles_away'] = m
    filas = []
    for q in partidos:
        gh, ga = q.get('goles_home'), q.get('goles_away')
        if gh is None or q.get('aplazado'):
            continue
        h, a = mm._equipos(q)
        stats = q.get('stats_partido')
        if stats is None:
            stats = pg._stats_del_partido(q.get('clave_liga'), h, a, q.get('fecha'))
        for c in q['_todas']:
            f = pg._fila(c)
            real = pg._valor_real(f, gh, ga, stats)
            ok, _dist = pg._acierto(f, real, h, a)
            filas.append({
                'dia': dp.dia_de(q), 'liga': q.get('clave_liga'),
                'partido': q.get('partido'), 'inicio': q.get('inicio'),
                'mercado': c.get('mercado'), 'etiqueta': c.get('etiqueta'),
                'apuesta': c.get('apuesta'), 'linea': c.get('linea'),
                'prob': c.get('prob'), 'ajustada': c.get('_ajustada'),
                'cuota': c.get('cuota'), 'p_mercado': c.get('p_mercado'),
                'motivo': c.get('_motivo'),
                'metida': c.get('apuesta') in q['_metidas'],
                'n_metidas': len(q['_metidas']),
                'elite': c.get('apuesta') == q['_elite'],
                'fav': q.get('_fav'), 'goles_home': gh, 'goles_away': ga,
                'acierto': None if ok is None else int(bool(ok))})
    d = pd.DataFrame(filas)
    d.to_csv(CACHE, index=False)
    return d


FAMILIA = ('1X2', 'Doble oportunidad', 'Doble y goles', 'Handicap', 'Ganador')
CORTE = '2026-09-26'      # se elige con los días hasta aquí; se juzga después


def regla_de_antes(d: pd.DataFrame) -> pd.DataFrame:
    """Lo que metía la tarjeta ANTES de la v324, reproducido sobre la caché:
    una línea por mercado (la más probable), la regla de «meter» DESPUÉS,
    la Capa 1 primero, una de resultado, cuatro recomendadas y dos «meter».
    Con el código de antes coincidía apuesta por apuesta (756 de 756)."""
    d = d.assign(motivo=d.motivo.fillna(''), score=d.prob * d.cuota)
    filas = []
    for _k, g in d.groupby(['partido', 'inicio']):
        g = g[g.cuota.notna()]
        dig = g[(g.prob >= .5) & (g.prob <= .9) & (g.cuota >= 1.20)]
        if dig.empty:
            dig = g
        o = dig.sort_values(['prob', 'score'], ascending=False)
        o = o.drop_duplicates('mercado').head(12)
        o = o.assign(met=o.motivo == '').sort_values(['met', 'ajustada'],
                                                    ascending=[False, False])
        lista = [r for _, r in o.iterrows()]
        el = g[g.elite]
        if len(el):
            e = el.iloc[0].copy()
            e['met'] = True
            lista = [e] + [r for r in lista if r.apuesta != e.apuesta]
        vistas, fuera = set(), []
        for r in lista:
            f = 'resultado' if r.mercado in FAMILIA else r.mercado
            if f not in vistas:
                vistas.add(f)
                fuera.append(r)
        filas += [r for r in fuera[:4] if r.met][:2]
    return pd.DataFrame(filas)


def resumen(d: pd.DataFrame) -> None:
    partidos = d.groupby('partido').dia.first()
    antes = regla_de_antes(d)
    ahora = d[d.metida]
    for nom, x in (('antes', antes), ('ahora', ahora)):
        for t, f in (('elige', x.dia <= CORTE), ('juzga', x.dia > CORTE)):
            y = x[f & x.acierto.notna()]
            print('%-6s %-6s %.1f %% (%d, %d rojos)' % (
                nom, t, 100 * y.acierto.mean(), len(y),
                int((1 - y.acierto).sum())))
        print('       sin nada que meter: %d de %d partidos'
              % (len(partidos) - x.partido.nunique(), len(partidos)))
    ka = set(map(tuple, antes[['partido', 'apuesta']].values))
    kb = set(map(tuple, ahora[['partido', 'apuesta']].values))
    for nom, x, otro in (('entran', ahora, ka), ('salen', antes, kb)):
        x = x[[t not in otro for t in map(tuple, x[['partido', 'apuesta']].values)]]
        x = x[x.acierto.notna()]
        print(nom, len(x), ' '.join(
            '%s %d %.1f %%' % (t, len(x[f]), 100 * x[f].acierto.mean())
            for t, f in (('elige', x.dia <= CORTE), ('juzga', x.dia > CORTE))))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if '--rehacer' in sys.argv or not os.path.exists(CACHE):
        d = construir()
    else:
        d = pd.read_csv(CACHE)
    print('apuestas liquidadas:', int(d['acierto'].notna().sum()),
          'de', len(d), '· partidos', d['partido'].nunique(),
          '· días', sorted(d['dia'].unique()))
    resumen(d)


if __name__ == '__main__':
    main()
