#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — ¿Cuánto costaba predecir 2026 con el estado congelado en 2025-09-28?

El experimento de features salió negativo: las estadísticas de equipo están en
su techo. Pero ese experimento mide el histórico 2018-2021, donde la
obsolescencia no existía. El fallo que veía el usuario era otro y hay que
cuantificarlo aparte.

Se predicen los partidos ya jugados de 2026 de dos maneras, con el MISMO
modelo entrenado:

  A) ESTADO CONGELADO — ELO, forma y rachas tal como quedaron el 2025-09-28,
     que es literalmente lo que hacía producción (304 días de antigüedad).
  B) ESTADO AL DÍA     — el estado recalculado partido a partido, causal.

La diferencia es el precio de no refrescar.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('frescura')

MA = 10


def main():
    from engines.mlb_engine import MLBEngine

    eng = MLBEngine().cargar_modelo()
    if not eng.listo:
        print('modelo no disponible')
        return

    df = pd.read_csv('historico_mlb.csv', low_memory=False)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    corte = pd.Timestamp('2025-09-29')       # justo tras el fin de la 2025
    hist = df[df.date < corte]
    _X, _y, _t, _f, estado_viejo = MLBEngine._dataset(hist)
    log.info(f'estado congelado reconstruido con {len(hist)} juegos '
             f'(hasta {hist.date.max().date()})')

    # --- recorrido causal por 2026 manteniendo el estado al día ---------
    elo, rs, ra, streak, ult, pit_ra = {}, {}, {}, {}, {}, {}
    for r in hist.itertuples(index=False):
        h, a = r.home_team, r.away_team
        gh, ga = float(r.home_runs), float(r.away_runs)
        rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
        rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
        for pid, c in ((r.home_pitcher, ga), (r.away_pitcher, gh)):
            if isinstance(pid, str) and pid:
                pit_ra.setdefault(pid, []).append(c)
        for eq, gano in ((h, gh > ga), (a, ga > gh)):
            streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else \
                min(streak.get(eq, 0), 0) - 1
        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
        e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
        s_h = 1.0 if gh > ga else 0.0
        elo[h] = eh + 20 * (s_h - e_h)
        elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
        ult[h] = ult[a] = r.date

    eq_viejo = estado_viejo['equipos']
    pit_viejo = estado_viejo['pitchers']

    def _feat(fuente_eq, fuente_pit, h, a, hp, ap, fecha, usar_dict):
        if usar_dict:
            if h not in fuente_eq or a not in fuente_eq:
                return None
            H, A = fuente_eq[h], fuente_eq[a]
            elo_h, elo_a = H['elo'], A['elo']
            rs_h = np.mean(H['rs']) if H['rs'] else 4.5
            rs_a = np.mean(A['rs']) if A['rs'] else 4.5
            ra_h = np.mean(H['ra']) if H['ra'] else 4.5
            ra_a = np.mean(A['ra']) if A['ra'] else 4.5
            st_h, st_a = H['streak'], A['streak']
            uh = H.get('ult_fecha'); ua = A.get('ult_fecha')
            rest_h = min((fecha - pd.Timestamp(uh)).days, 7) if uh else 3
            rest_a = min((fecha - pd.Timestamp(ua)).days, 7) if ua else 3
            pf = fuente_pit
        else:
            if h not in rs or a not in rs:
                return None
            elo_h, elo_a = elo.get(h, 1500.0), elo.get(a, 1500.0)
            rs_h, rs_a = np.mean(rs[h][-MA:]), np.mean(rs[a][-MA:])
            ra_h, ra_a = np.mean(ra[h][-MA:]), np.mean(ra[a][-MA:])
            st_h, st_a = streak.get(h, 0), streak.get(a, 0)
            rest_h = min((fecha - ult[h]).days, 7) if h in ult else 3
            rest_a = min((fecha - ult[a]).days, 7) if a in ult else 3
            pf = pit_ra
        pr_h = np.mean(pf.get(hp, [])[-5:]) if (hp and pf.get(hp)) else 4.5
        pr_a = np.mean(pf.get(ap, [])[-5:]) if (ap and pf.get(ap)) else 4.5
        return [(elo_h - elo_a) / 100.0, (rs_h - rs_a) / 3.0,
                (ra_h - ra_a) / 3.0, (st_h - st_a) / 5.0,
                (max(min(rest_h, 7), 0) - max(min(rest_a, 7), 0)) / 5.0,
                (pr_h - pr_a) / 3.0, (rs_h + rs_a) / 9.0,
                (ra_h + ra_a) / 9.0, (pr_h + pr_a) / 9.0]

    Xa, Xb, Y = [], [], []
    nuevos = df[df.date >= corte]
    for r in nuevos.itertuples(index=False):
        h, a, fecha = r.home_team, r.away_team, r.date
        hp = r.home_pitcher if isinstance(r.home_pitcher, str) else ''
        ap = r.away_pitcher if isinstance(r.away_pitcher, str) else ''
        fa = _feat(eq_viejo, pit_viejo, h, a, hp, ap, fecha, True)
        fb = _feat(None, None, h, a, hp, ap, fecha, False)
        if fa is not None and fb is not None:
            Xa.append(fa); Xb.append(fb)
            Y.append(int(r.home_runs > r.away_runs))
        # actualizar el estado «al día» tras emitir
        gh, ga = float(r.home_runs), float(r.away_runs)
        rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
        rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
        for pid, c in ((hp, ga), (ap, gh)):
            if pid:
                pit_ra.setdefault(pid, []).append(c)
        for e_, gano in ((h, gh > ga), (a, ga > gh)):
            streak[e_] = max(streak.get(e_, 0), 0) + 1 if gano else \
                min(streak.get(e_, 0), 0) - 1
        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
        e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
        s_h = 1.0 if gh > ga else 0.0
        elo[h] = eh + 20 * (s_h - e_h)
        elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
        ult[h] = ult[a] = fecha

    Xa, Xb, Y = np.array(Xa), np.array(Xb), np.array(Y)
    i1 = list(eng.modelo_ml.classes_).index(1)
    pa = eng.modelo_ml.predict_proba(eng.scaler.transform(Xa))[:, i1]
    pb = eng.modelo_ml.predict_proba(eng.scaler.transform(Xb))[:, i1]

    def met(p, etiq):
        pc = p.clip(1e-6, 1 - 1e-6)
        ll = float(-(Y * np.log(pc) + (1 - Y) * np.log(1 - pc)).mean())
        ac = float(((p >= .5).astype(int) == Y).mean())
        print(f"  {etiq:26s} log-loss {ll:.4f}   precisión {ac:.4f}   "
              f"std {p.std():.4f}   máx {p.max():.4f}   "
              f"|45-55%| {((p>.45)&(p<.55)).mean():.1%}")
        return {'log_loss': round(ll, 4), 'precision': round(ac, 4),
                'std': round(float(p.std()), 4),
                'frac_50_50': round(float(((p > .45) & (p < .55)).mean()), 4)}

    print(f"\n{len(Y)} partidos jugados desde {corte.date()} "
          f"(temporada 2026)\n")
    a = met(pa, 'A) estado CONGELADO')
    b = met(pb, 'B) estado AL DÍA')
    print(f"\n  Precio de la obsolescencia: "
          f"{a['log_loss'] - b['log_loss']:+.4f} de log-loss, "
          f"{(b['precision'] - a['precision'])*100:+.2f} pp de precisión")
    json.dump({'n': int(len(Y)), 'congelado': a, 'al_dia': b},
              open('_v79_mlb_frescura.json', 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
