# -*- coding: utf-8 -*-
"""
v160 - NUESTRA PROBABILIDAD DE TARJETAS CONTRA LA DE LA CASA.

No es un backtest —para eso hace falta el histórico que `snapshots_tarjetas`
acaba de empezar a acumular—, es una comprobación de MAGNITUD. Si la casa
contase las rojas dentro de «Total de tarjetas» y nosotros contamos sólo
amarillas, nuestras probabilidades saldrían sistematicamente por debajo de las
suyas en las lineas altas, y eso se ve ya con una foto.

Se compara, en las lineas que la casa cotiza:
  - P(mas de L) del modelo, con la dispersion medida de la competicion
  - P(mas de L) implicita en la cuota, quitado el margen con las dos caras
"""
import pandas as pd
import numpy as np

import rendimiento_equipos as rq
import arbitro_partido as ap

d = pd.read_csv('tarjetas_snapshots.csv')
tot = d[d['familia'] == 'Total de tarjetas'].copy()
print('partidos con linea de total:', tot[['home', 'away']].drop_duplicates().shape[0])

filas = []
for (clave, h, a, fecha), g in tot.groupby(['clave_liga', 'home', 'away',
                                            'fecha_partido']):
    tj = rq.tarjetas_equipo(clave, h, a,
                            factor_arbitro=ap.factor_de(fecha, h, a))
    if tj is None:
        # los nombres del fixture son los de ESPN; el historico usa los suyos
        continue
    for linea, gg in g.groupby('linea'):
        mas = gg[gg['mercado'].str.startswith('Más')]['cuota']
        men = gg[gg['mercado'].str.startswith('Menos')]['cuota']
        if mas.empty or men.empty:
            continue
        cm_, cM = float(mas.iloc[0]), float(men.iloc[0])
        imp_mas, imp_men = 1.0 / cm_, 1.0 / cM
        s = imp_mas + imp_men
        p_mercado = imp_mas / s               # devig proporcional
        p_modelo = rq.prob_mas_de(tj['lambda_total'], float(linea),
                                  tj['dispersion_total'])
        if p_modelo is None:
            continue
        filas.append({'clave': clave, 'partido': '%s-%s' % (h, a),
                      'linea': float(linea), 'lambda': tj['lambda_total'],
                      'p_modelo': p_modelo, 'p_mercado': p_mercado,
                      'dif': p_modelo - p_mercado, 'margen': s - 1.0})

t = pd.DataFrame(filas)
if t.empty:
    print('sin cruces: los nombres del fixture no casan con el historico')
    raise SystemExit
print('cruces: %d en %d partidos, %d competiciones'
      % (len(t), t['partido'].nunique(), t['clave'].nunique()))
print()
print('POR LINEA (dif = modelo - mercado; positivo = el modelo ve MAS tarjetas)')
g = t.groupby('linea').agg(n=('dif', 'size'), p_modelo=('p_modelo', 'mean'),
                           p_mercado=('p_mercado', 'mean'), dif=('dif', 'mean'))
print(g.round(4).to_string())
print()
print('sesgo medio global: %+.4f' % t['dif'].mean())
print('lambda media del modelo: %.2f' % t['lambda'].mean())

# La linea "central" de la casa: aquella donde su probabilidad esta mas cerca
# de 0,5. Es su mejor estimacion del total, y se puede comparar con la nuestra.
centro = []
for p, gg in t.groupby('partido'):
    i = (gg['p_mercado'] - 0.5).abs().idxmin()
    centro.append({'partido': p, 'linea_casa': gg.loc[i, 'linea'],
                   'p_casa': gg.loc[i, 'p_mercado'],
                   'lambda_modelo': gg.loc[i, 'lambda']})
c = pd.DataFrame(centro)
print()
print('DONDE PONE CADA UNO EL CENTRO')
print('  linea central de la casa (media) ... %.2f' % c['linea_casa'].mean())
print('  lambda del modelo (media) ......... %.2f' % c['lambda_modelo'].mean())
print('  diferencia ........................ %+.2f tarjetas'
      % (c['lambda_modelo'].mean() - c['linea_casa'].mean()))
print()
print(c.round(3).to_string(index=False))
