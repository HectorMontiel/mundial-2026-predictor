# -*- coding: utf-8 -*-
"""
v330 — pruebas: la NBA con 19 temporadas, medida, y en «Apuestas del Día».

  1. El histórico largo: partidos, temporadas, el hándicap CON signo y sin
     líneas imposibles; los clubes de fuera no se confunden con la NBA.
  2. Sin fuga: las variables de un partido no cambian si cambia su resultado.
  3. Lo medido en el artefacto se cumple: la mezcla no es peor que la casa y
     lo que se mete promete lo que acierta; el peso es el de `concordancia`.
  4. El modelo predice y la mezcla con la casa es 10 % / 90 %.
  5. La pretemporada nunca se mete; la temporada regular sí, con su razón.
  6. El barrido (red simulada) publica TODOS los partidos en `pronosticos`
     con tablero, cuotas y más/menos puntos.
  7. «Finalizados»: el marcador de la NBA sale del de ESPN.

Uso: python test_v330.py
"""
from __future__ import annotations

import json
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _fila(m, h, a, ch, ca, tipo='regular', tot=None):
    import modelo_nba as mn
    pred = m.predecir_partido(h, a, '2026-10-22', tipo)
    ph, pa = pred['prob_home_sin_empate'], pred['prob_away_sin_empate']
    f = {'deporte': 'NBA', 'liga': 'NBA', 'clave_liga': 'nba',
         'partido': '%s vs %s' % (h, a), 'fecha': '2026-10-22',
         'inicio': '2026-10-22 23:30:00', 'mercado': 'Moneyline',
         'apuesta': 'Gana %s' % (h if ph >= .5 else a),
         'prob': round(max(ph, pa), 3),
         'board': {'Gana %s' % h: ph, 'Gana %s' % a: pa},
         'cuota': ch if ph >= .5 else ca,
         'total_esperado': pred['total_esperado'],
         'implicitas': {'1x2_cuotas': {'home': ch, 'away': ca}}}
    if tot:
        f['implicitas']['totales_cuotas'] = tot
    f['totales'] = m.totales(pred, list((tot or {}).keys()))
    if tipo == 'pretemporada':
        f.update({'pretemporada': True, 'nota': mn.NOTA_PRETEMPORADA})
    return f


def main():
    import numpy as np
    import pandas as pd
    import nba_estado as ne
    import nba_historico as nh

    # 1 ---------------------------------------------------------------
    d = nh.cargar()
    check(d is not None and len(d) >= 24000,
          'histórico largo con %d partidos' % (0 if d is None else len(d)))
    check(d.temporada.min() <= 2007 and d.temporada.max() >= 2025,
          'temporadas %d → %d' % (d.temporada.min(), d.temporada.max()))
    c = d[d.spread.notna()]
    m_ = c.home_pts - c.away_pts
    check(np.corrcoef(c.spread, m_)[0, 1] > 0.4 and (m_ - c.spread).abs().mean() < 10.5,
          'el hándicap de la casa lleva signo (corr %.2f, error medio %.2f)'
          % (np.corrcoef(c.spread, m_)[0, 1], (m_ - c.spread).abs().mean()))
    check(d.total_linea.dropna().between(150, 280).all() and (d.spread.dropna().abs() <= 25).all(),
          'sin líneas imposibles (totales 150-280, hándicap ≤ 25)')
    check(nh.codigo('Sydney Kings') is None and nh.codigo('Perth Wildcats') is None
          and nh.codigo('LA Clippers') == 'LAC' and nh.codigo('LA Lakers') == 'LAL'
          and nh.codigo('Golden State Warriors') == 'GSW',
          'los clubes de fuera (Sydney Kings) no se confunden con la NBA')

    # 2 ---------------------------------------------------------------
    sub = d[d.temporada.between(2022, 2023)].reset_index(drop=True)
    x1, _ = ne.dataset(sub)
    i = len(sub) // 2
    sub2 = sub.copy()
    sub2.loc[i, 'home_pts'] = sub2.loc[i, 'home_pts'] + 40
    x2, _ = ne.dataset(sub2)
    cols = ne.COLS_MARGEN + ne.COLS_TOTAL
    check(np.allclose(x1.loc[:i, cols].values, x2.loc[:i, cols].values),
          'sin fuga: las variables de un partido no ven su resultado')
    check(not np.allclose(x1.loc[i + 1:, cols].values, x2.loc[i + 1:, cols].values),
          'y los partidos siguientes sí lo aprenden')

    # 3 ---------------------------------------------------------------
    import concordancia as conc
    art = json.load(open('modelos/nba_v330.json', encoding='utf-8'))
    me = art['medicion']
    j = me['juzga']
    check(j['mezcla']['log_loss'] <= j['casa']['log_loss'] + 0.0005 and j['mezcla']['n'] >= 10000,
          'juzga 2017-26: mezcla %.5f · casa %.5f · modelo %.5f (n %d)'
          % (j['mezcla']['log_loss'], j['casa']['log_loss'],
             j['modelo']['log_loss'], j['mezcla']['n']))
    mt = me['meter_juzga']
    check(mt['n'] >= 5000 and abs(mt['promete'] - mt['real']) < 0.02,
          '«meter» (≥65 %%) en 2017-26: promete %.1f %%, acierta %.1f %% (%d)'
          % (mt['promete'] * 100, mt['real'] * 100, mt['n']))
    check(me['peso_modelo'] == conc.PESO_MODELO_NBA == 0.10,
          'el peso medido (%.2f) es el que usa la app' % me['peso_modelo'])

    # 4 ---------------------------------------------------------------
    import modelo_nba as mn
    m = mn.NBAModelo.cargar()
    check(m is not None, 'el modelo carga con el estado al día')
    p = m.predecir_partido('Boston Celtics', 'New York Knicks', '2026-10-22')
    check(abs(p['prob_home_sin_empate'] + p['prob_away_sin_empate'] - 1) < 1e-3
          and 190 < p['total_esperado'] < 260 and abs(p['margen_esperado']) < 25,
          'predicción sensata: %s' % {k: p[k] for k in ('margen_esperado', 'total_esperado',
                                                        'prob_home_sin_empate')})
    check('error' in m.predecir_partido('Sydney Kings', 'Boston Celtics'),
          'un rival de fuera de la NBA no se predice')
    t = m.totales(p, ['210.5', '220.5', '230.5'])
    ls = t.get('lineas') or {}
    check(len(ls) == 3 and ls['210.5'] > ls['220.5'] > ls['230.5'],
          'más/menos puntos en las líneas de la casa: %s' % ls)
    f = _fila(m, 'Boston Celtics', 'New York Knicks', 1.65, 2.3)
    r = conc.evaluar(f, 'Gana Boston Celtics', 'Moneyline', prob_modelo=0.60)
    pm = (1 / 1.65) / (1 / 1.65 + 1 / 2.3)
    check(r.get('hay') and abs(r['p_mezcla'] - (0.1 * 0.60 + 0.9 * pm)) < 2e-4,
          'la NBA se mezcla 10 %% modelo / 90 %% casa (%.4f)' % (r.get('p_mezcla') or -1))

    # 5 ---------------------------------------------------------------
    import modo_modelo as mmod
    import veredicto_pick as vp
    tot = {'%.1f' % L: {'mas': o, 'menos': u}
           for L, o, u in ((215.5, 1.22, 4.2), (233.5, 1.91, 1.91), (250.5, 4.5, 1.2))}
    reg = _fila(m, 'Oklahoma City Thunder', 'Washington Wizards', 1.12, 7.0, tot=tot)
    pre = _fila(m, 'Oklahoma City Thunder', 'Washington Wizards', 1.12, 7.0,
                'pretemporada', tot)
    met_r = mmod.metidas(mmod.recomendadas(reg))
    met_p = mmod.metidas(mmod.recomendadas(pre))
    check(len(met_r) >= 1 and not met_p,
          'temporada regular: se mete %s; pretemporada: nada'
          % [x.get('apuesta') for x in met_r])
    v = vp.evaluar({'deporte': 'NBA', 'prob': 0.80, 'apuesta': 'Gana X',
                    'mercado': 'Moneyline', 'cuota': 1.3, 'pretemporada': True})
    check(v['veredicto'] == vp.NO_METER and 'pretemporada' in ' '.join(v['razones']),
          'la pretemporada se dice: %s' % v['razones'])
    v = vp.evaluar({'deporte': 'NBA', 'prob': 0.80, 'apuesta': 'Gana X',
                    'mercado': 'Moneyline', 'cuota': 1.3})
    check(v['veredicto'] == vp.NO_METER and 'precio de la casa' in ' '.join(v['razones']),
          'sin precio de la casa no se mete (el modelo solo no basta): %s' % v['razones'])
    v = vp.evaluar({'deporte': 'NBA', 'prob': 0.80, 'apuesta': 'Gana Boston Celtics',
                    'mercado': 'Moneyline', 'cuota': 1.3,
                    'partido': 'Boston Celtics vs New York Knicks',
                    # v350 — la casa en 78 %+ (1,22 / 4,6 → 79 %): la regla medida
                    'implicitas': {'1x2_cuotas': {'home': 1.22, 'away': 4.6}}})
    check(v['veredicto'] == vp.METER and v['correccion'] == 0.0
          and any('NBA' in r_ for r_ in v['razones']),
          'con precio, la NBA mezcla sin la corrección del fútbol y lo dice: %s (%.3f)'
          % (v['razones'], v['prob_ajustada']))

    # 6 ---------------------------------------------------------------
    import alpha_finder as af
    import cuotas_multi as cm
    fx = [{'fecha': '2026-10-22', 'inicio': '2026-10-22 23:30:00',
           'home': 'Boston Celtics', 'away': 'New York Knicks',
           'abrev_home': 'BOS', 'abrev_away': 'NYK', 'tipo': 'regular'},
          {'fecha': '2026-10-06', 'inicio': '2026-10-06 23:00:00',
           'home': 'LA Clippers', 'away': 'Los Angeles Lakers',
           'abrev_home': 'LAC', 'abrev_away': 'LAL', 'tipo': 'pretemporada'}]
    orig = (mn.fixtures_nba, cm.cuotas_partido, af._cuotas_de_totales, af.hoy_utc,
            cm.precio_accionable)
    try:
        mn.fixtures_nba = lambda dias=2: [dict(x) for x in fx]
        cm.cuotas_partido = lambda *a, **k: {'mejor': {'home': {'cuota': 1.65, 'casa': 'X'},
                                                       'away': {'cuota': 2.3, 'casa': 'Y'}}}
        cm.precio_accionable = lambda c, lado: {'cuota': 1.6, 'casa': 'Playdoit'}

        def _tot(ps, dep):
            for q in ps:
                q.setdefault('implicitas', {})['totales_cuotas'] = tot
            return len(ps)
        af._cuotas_de_totales = _tot
        af.hoy_utc = lambda: pd.Timestamp('2026-10-22')
        s = af._picks_nba()
    finally:
        (mn.fixtures_nba, cm.cuotas_partido, af._cuotas_de_totales, af.hoy_utc,
         cm.precio_accionable) = orig
    pr = s.get('pronosticos') or []
    check(len(pr) == 2 and all(q.get('board') and q.get('implicitas', {}).get('1x2_cuotas')
                               and q.get('totales') for q in pr),
          'el barrido publica los 2 partidos con tablero, cuotas y más/menos (%d)' % len(pr))
    check([bool(q.get('pretemporada')) for q in pr] == [False, True]
          and 'Pretemporada' in str(pr[1].get('nota')),
          'la pretemporada va marcada y con su nota')
    check(all(q['deporte'] == 'NBA' and q['clave_liga'] == 'nba' for q in pr)
          and any('NBA:' in i_ for i_ in s.get('incidencias') or []),
          'deporte NBA y la incidencia del barrido: %s' % (s.get('incidencias') or [''])[-1])

    # 6b — sin ESPN (pasa en GitHub Actions): el calendario de Playdoit, que
    # sí cotiza la pretemporada, con sus nombres abreviados
    pdt = {'a': {'home': 'PHI 76ers', 'away': 'NY Knicks', 'liga': 'NBA, Pretemporada',
                 'fecha': '2026-10-22T23:00:00Z', 'cuotas': {'home': 2.05, 'away': 1.78}},
           'b': {'home': 'Sydney Kings', 'away': 'Perth Wildcats', 'liga': 'NBL',
                 'fecha': '2026-10-22T09:00:00Z', 'cuotas': {'home': 1.5, 'away': 2.6}},
           'c': {'home': 'Real Madrid', 'away': 'Panathinaikos', 'liga': 'Euroliga',
                 'fecha': '2026-10-22T19:00:00Z', 'cuotas': {'home': 1.5, 'away': 2.6}}}
    orig = (mn.fixtures_nba, cm.cuotas_partido, af._cuotas_de_totales, af.hoy_utc,
            cm._indice_pdt, cm._indice, cm._indice_bov)
    try:
        mn.fixtures_nba = lambda dias=2: []
        cm.cuotas_partido = lambda *a, **k: {}
        af._cuotas_de_totales = lambda ps, dep: 0
        af.hoy_utc = lambda: pd.Timestamp('2026-10-22')
        cm._indice_pdt = lambda dep: pdt if dep == 'nba' else {}
        cm._indice = cm._indice_bov = lambda dep: {}
        s2 = af._picks_nba()
    finally:
        (mn.fixtures_nba, cm.cuotas_partido, af._cuotas_de_totales, af.hoy_utc,
         cm._indice_pdt, cm._indice, cm._indice_bov) = orig
    pr2 = s2.get('pronosticos') or []
    check(len(pr2) == 1 and pr2[0]['partido'] == 'Philadelphia 76ers vs New York Knicks'
          and pr2[0].get('pretemporada')
          and pr2[0].get('implicitas', {}).get('1x2_cuotas') == {'home': 2.05, 'away': 1.78},
          'sin ESPN: la pretemporada de Playdoit entra (nombres largos, su precio) '
          'y las ligas que no son NBA no: %s' % [q.get('partido') for q in pr2])

    # 7 ---------------------------------------------------------------
    import partidos_jugados as pj
    q = {'partido': 'LA Clippers vs Los Angeles Lakers', 'deporte': 'NBA'}
    check(pj._marcador_nba(q, {('LAC', 'LAL'): (110.0, 104.0)}) == (110.0, 104.0)
          and pj._marcador_nba(q, {}) is None,
          'el marcador de la NBA se casa por código; sin dato, pendiente')
    check(pj.duracion_h({'deporte': 'NBA'}) == 2.75, 'un partido de la NBA dura 2,75 h')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
