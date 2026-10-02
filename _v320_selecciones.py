# -*- coding: utf-8 -*-
"""
v320 — EL FILTRO DEL FAVORITO EN SELECCIONES, CON SUS CUOTAS DE VERDAD.

El usuario: «¿cómo no va a haber cuotas? En selecciones sí me las has dado;
chécalo bien en todas tus fuentes». Tenía razón: el HISTÓRICO de selecciones
no trae cuotas, pero el proyecto sí las guardó en otros sitios:
  · el historial de git de `cuotas_mx.json` (el tablero de casas, desde el
    10-sep-2026): el 1X2 de cada casa, partido a partido, antes del inicio;
  · `anclas_capturas.csv` (desde el 21-sep): la casa y Pinnacle.
Para los partidos anteriores a esas fechas, la probabilidad del favorito sale
de un Elo de selecciones calculado SÓLO con los partidos previos (es lo que
hace la regla en vivo cuando no hay casa: usa el modelo).

Se repite el backtest de córners de la v319 sólo para selecciones (el modelo
entrenado con lo anterior al 2025-07-01, partidos con histórico real),
franja 70-80 %, separado por la probabilidad del favorito.

Uso: python _v320_selecciones.py   (escribe _v320_selecciones.json)
"""
from __future__ import annotations

import json
import subprocess

import numpy as np
import pandas as pd

CORTE = pd.Timestamp('2025-07-01')


def cuotas_git() -> pd.DataFrame:
    """El 1X2 sin margen (media de las casas) de cada partido de fútbol, en la
    última versión del tablero ANTERIOR a su inicio."""
    hs = [l.split() for l in subprocess.check_output(
        ['git', 'log', '--reverse', '--format=%h %ct', '--', 'cuotas_mx.json'],
        text=True).splitlines() if l.strip()]
    ult = {}
    for h, ts in hs:
        try:
            d = json.loads(subprocess.check_output(['git', 'show', h + ':cuotas_mx.json']))
        except Exception:
            continue
        for v in (d.get('partidos') or {}).values():
            if v.get('deporte') != 'futbol':
                continue
            try:
                ini = int(v.get('inicio'))
            except Exception:
                continue
            if ini <= float(ts):
                continue
            qs = []
            for casa in (v.get('casas') or {}).values():
                m = (casa or {}).get('HOME_DRAW_AWAY') or {}
                try:
                    inv = np.array([1 / float(m['home']), 1 / float(m['draw']), 1 / float(m['away'])])
                    qs.append(inv / inv.sum())
                except Exception:
                    pass
            if qs:
                q = np.mean(qs, axis=0)
                ult[(v['home'], v['away'], ini)] = (float(ts), q[0], q[2], v.get('liga'))
    filas = [{'home': k[0], 'away': k[1], 'ini': pd.Timestamp(k[2], unit='s'),
              'q_home': x[1], 'q_away': x[2], 'liga_casa': x[3]} for k, x in ult.items()]
    return pd.DataFrame(filas)


def cuotas_anclas() -> pd.DataFrame:
    a = pd.read_csv('anclas_capturas.csv', low_memory=False)
    a = a[a['deporte'] == 'futbol'].copy()
    a['ini'] = pd.to_datetime(pd.to_numeric(a['inicio'], errors='coerce'), unit='s')
    a = a.sort_values('capturado').drop_duplicates(['home', 'away', 'ini'], keep='last')
    filas = []
    for r in a.itertuples(index=False):
        for t in (('pin_home', 'pin_draw', 'pin_away'), ('c_home', 'c_draw', 'c_away')):
            try:
                inv = np.array([1 / float(getattr(r, c)) for c in t])
                if np.isfinite(inv).all():
                    q = inv / inv.sum()
                    filas.append({'home': r.home, 'away': r.away, 'ini': r.ini,
                                  'q_home': q[0], 'q_away': q[2], 'liga_casa': r.liga})
                    break
            except Exception:
                pass
    return pd.DataFrame(filas)


def elo_selecciones() -> dict:
    """{(fecha, local, visitante): prob. de ganar del favorito} con un Elo que
    sólo mira hacia atrás (K 30, 60 puntos de local si no es neutral)."""
    import rendimiento_equipos as rq
    h = rq._historico('selecciones').copy()
    h['date'] = pd.to_datetime(h['date'], errors='coerce')
    h = h.dropna(subset=['date', 'home_goals', 'away_goals']).sort_values('date')
    elo, out = {}, {}
    for r in h.itertuples(index=False):
        eh, ea = elo.get(r.home_team, 1500.0), elo.get(r.away_team, 1500.0)
        ventaja = 0.0 if bool(getattr(r, 'neutral', False)) else 60.0
        e = 1 / (1 + 10 ** (-(eh + ventaja - ea) / 400))
        # de la esperanza (gana + medio empate) a la probabilidad de ganar
        empate = 0.28 * (1 - abs(2 * e - 1))
        out[(r.date.normalize(), r.home_team, r.away_team)] = max(e - empate / 2, 1 - e - empate / 2)
        res = 1.0 if r.home_goals > r.away_goals else 0.5 if r.home_goals == r.away_goals else 0.0
        elo[r.home_team] = eh + 30 * (res - e)
        elo[r.away_team] = ea - 30 * (res - e)
    return out


def main():
    import corners_tabla as ct
    import historico_real as hr
    import mercado_sin_modelo as msm
    import rendimiento_equipos as rq
    from _v319_conteos_reales import _filas_lineas
    df = ct.conjunto()
    cod = {l: i for i, l in enumerate(sorted(df['liga'].unique()))}
    mods = ct.ajustar_modelos(df[df['fecha'] < CORTE], cod, ct.rasgos_modelo())
    s = df[(df['liga'] == 'selecciones') & (df['fecha'] >= CORTE)].copy()
    X = ct._X(s, cod, ct.rasgos_modelo())
    s['lh'], s['la'] = mods['local'].predict(X), mods['visita'].predict(X)
    cu = pd.concat([cuotas_git(), cuotas_anclas()], ignore_index=True)
    elo = elo_selecciones()
    disp, disp_t = rq.dispersion_corners_equipo('selecciones'), rq.dispersion_corners_liga('selecciones')
    filas, origen = [], {'casa': 0, 'elo': 0, 'ninguna': 0}
    for i, r in enumerate(s.itertuples(index=False)):
        if not hr.evaluar('selecciones', r.home, r.away, 'corners', r.fecha)['ok']:
            continue
        cand = cu[(cu['ini'] - pd.Timestamp(r.fecha)).abs() <= pd.Timedelta(days=1)]
        fav, de = None, 'ninguna'
        for c in cand.itertuples(index=False):
            if msm.mismo_equipo(c.home, r.home) and msm.mismo_equipo(c.away, r.away):
                fav, de = float(max(c.q_home, c.q_away)), 'casa'
                break
        if fav is None:
            e = elo.get((pd.Timestamp(r.fecha).normalize(), r.home, r.away))
            if e is not None:
                fav, de = float(e), 'elo'
        origen[de] += 1
        extra = {'fav': fav, 'de': de, 'fecha': r.fecha}
        filas += _filas_lineas(i, r.lh + r.la, disp_t, r.ch + r.ca, (7.5, 8.5, 9.5, 10.5, 11.5, 12.5), 'total', extra, rq)
        filas += _filas_lineas(i, r.lh, disp, r.ch, (2.5, 3.5, 4.5, 5.5, 6.5), 'equipo', extra, rq)
        filas += _filas_lineas(i, r.la, disp, r.ca, (2.5, 3.5, 4.5, 5.5, 6.5), 'equipo', extra, rq)
    P = pd.DataFrame(filas)
    P = P[P.p.between(.70, .80) & P.fav.notna()]
    P['banda'] = np.where(P.fav >= .65, '65 %+', np.where(P.fav >= .50, '50-65 %', 'menor al 50 %'))
    out = {'partidos_con_historico_real': int(sum(origen.values())),
           'favorito_de': origen, 'grupos': {}}
    for (t, b), z in P.groupby(['tipo', 'banda']):
        out['grupos']['%s | %s' % (t, b)] = {'partidos': int(z['mid'].nunique()), 'apuestas': int(len(z)),
                                             'acierto': round(float(z.y.mean()), 4)}
    for t, z in P[P['de'] == 'casa'].groupby('tipo'):
        for b, zz in z.groupby('banda'):
            out['grupos']['%s | %s | sólo con cuota de casa' % (t, b)] = {
                'partidos': int(zz['mid'].nunique()), 'acierto': round(float(zz.y.mean()), 4)}
    json.dump(out, open('_v320_selecciones.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
