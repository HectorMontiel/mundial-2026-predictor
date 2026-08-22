# -*- coding: utf-8 -*-
"""v160 — cuanto arbitro y cuanta tarjeta OBSERVADA hay en cada competicion.

Nota: en pandas 3 el astype(str) de una columna con NaN NO devuelve 'nan',
devuelve NA. Contar 'no vacio' con esa via daba 100% en ligas cuya columna
referee esta entera vacia. Aqui se cuenta sobre notna() y cadena no vacia.
"""
import glob, os
import pandas as pd
import rendimiento_equipos as re_

filas = []
for ruta in sorted(glob.glob('historico_*.csv')):
    clave = os.path.basename(ruta)[len('historico_'):-len('.csv')]
    try:
        d = pd.read_csv(ruta, low_memory=False)
    except Exception:
        continue
    if 'home_team' not in d.columns or 'home_yellow' not in d.columns:
        continue
    n = len(d)
    if 'referee' in d.columns:
        s = d['referee']
        s = s[s.notna()].astype('object').map(lambda x: str(x).strip())
        s = s[(s != '') & (s.str.lower() != 'nan')]
        ref_ok, n_arb = len(s), s.nunique()
    else:
        ref_ok = n_arb = 0
    disp = re_.stats_disponibles(clave)
    filas.append({'clave': clave, 'n': n, 'con_arbitro': ref_ok,
                  'pct_arb': round(100.0 * ref_ok / n, 1) if n else 0.0,
                  'arbitros': int(n_arb),
                  'tarjetas_obs': bool(disp.get('tarjetas')),
                  'corners_obs': bool(disp.get('corners'))})

t = pd.DataFrame(filas).sort_values(['pct_arb', 'n'], ascending=False)
print(t[t['tarjetas_obs'] | (t['pct_arb'] > 0)].to_string(index=False))
print()
print('con tarjetas OBSERVADAS :', int(t['tarjetas_obs'].sum()))
print('con arbitro en >90%     :', int((t['pct_arb'] > 90).sum()))
print('ambas cosas             :', int((t['tarjetas_obs'] & (t['pct_arb'] > 90)).sum()))
t.to_json('_v160_cobertura_arbitros.json', orient='records', indent=1, force_ascii=False)
