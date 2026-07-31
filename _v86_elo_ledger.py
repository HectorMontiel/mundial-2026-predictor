#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Añadir el ELO de cada partido al ledger de fútbol.

Es el paso que v85 dejó pendiente. Sin el ELO por partido no se puede medir un
prior de ELO, y sin eso la conclusión de v85 se apoyaba en el prior equivocado
(la tasa base) sobre la población equivocada (todo el ledger).

No hace falta reentrenar nada: `fe.construir_dataset_supervisado` devuelve
DIFF_ELO ya calculado partido a partido y SIN FUGA (el ELO previo al pitazo),
junto con el MATCH_ID en `ds['meta']`. Basta recorrer las ligas, quedarse con
ese par y cruzarlo con el ledger existente.

DIFF_ELO = (ELO_local - ELO_visitante) / 400   (feature_engineering.py:249)

Salida: `elo_por_partido.csv` con liga, match_id, diff_elo.
"""
import logging
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
log = logging.getLogger('elo-ledger')

SALIDA = 'elo_por_partido.csv'


def elo_de_liga(clave: str) -> pd.DataFrame:
    import os
    import feature_engineering as fe

    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        return pd.DataFrame()
    df = pd.read_csv(ruta, low_memory=False)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = (df.dropna(subset=['date'])
            .sort_values(['date', 'MATCH_ID'], kind='mergesort')
            .reset_index(drop=True))
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df']
    if 'DIFF_ELO' not in X_df.columns or not len(X_df):
        return pd.DataFrame()
    ids = [m[3] for m in ds['meta']]
    return pd.DataFrame({'liga': clave, 'match_id': ids,
                         'diff_elo': X_df['DIFF_ELO'].values.astype(float)})


def main():
    import config

    claves = [c for c, cfg in config.LEAGUES.items() if cfg.get('disponible', True)]
    print(f'recorriendo {len(claves)} ligas...')
    trozos = []
    for i, c in enumerate(claves, 1):
        try:
            t = elo_de_liga(c)
        except Exception as ex:
            print(f'  {i:2d}/{len(claves)} {c:24s} ERROR {type(ex).__name__}: '
                  f'{str(ex)[:60]}')
            continue
        if len(t):
            trozos.append(t)
            print(f'  {i:2d}/{len(claves)} {c:24s} {len(t):6d} partidos  '
                  f'DIFF_ELO [{t["diff_elo"].min():+.2f}, '
                  f'{t["diff_elo"].max():+.2f}]')
        else:
            print(f'  {i:2d}/{len(claves)} {c:24s} sin datos')

    if not trozos:
        print('nada que guardar')
        return
    out = pd.concat(trozos, ignore_index=True)
    out = out.drop_duplicates(subset=['liga', 'match_id'])
    out.to_csv(SALIDA, index=False)
    print(f'\n{len(out)} partidos con ELO -> {SALIDA}')

    # ¿cuánto del ledger queda cubierto?
    led = pd.read_csv('pick_ledger_total.csv')
    fut = led[led['deporte'] == 'Fútbol'].copy()
    m = fut.merge(out, on=['liga', 'match_id'], how='left')
    cob = m['diff_elo'].notna().mean()
    print(f'cobertura del ledger de fútbol: {m["diff_elo"].notna().sum()} de '
          f'{len(fut)} ({cob:.1%})')

    sin_mercado = m[m['cuota_home'].isna()]
    con_mercado = m[m['cuota_home'].notna()]
    print(f'  filas SIN mercado: {len(sin_mercado)} '
          f'(con ELO: {sin_mercado["diff_elo"].notna().sum()})')
    print(f'  filas CON mercado: {len(con_mercado)} '
          f'(con ELO: {con_mercado["diff_elo"].notna().sum()})')

    # comprobación de cordura: ¿el ELO correlaciona con el resultado real?
    from scipy.stats import spearmanr
    v = m.dropna(subset=['diff_elo'])
    gana_local = (v['resultado'] == 0).astype(int)
    rho, p = spearmanr(v['diff_elo'], gana_local)
    print(f'\ncordura — Spearman(DIFF_ELO, gana el local) = {rho:+.4f} '
          f'(p={p:.1e})')
    print('  debe ser claramente POSITIVO: si no, el ELO estaría mal calculado')

    rho2, _ = spearmanr(v['diff_elo'], v['p_home'])
    print(f'Spearman(DIFF_ELO, P(local) del modelo) = {rho2:+.4f}')
    print('  ésta es la que la auditoría de monotonía encontró baja o negativa '
          'en 32 ligas')


if __name__ == '__main__':
    main()
