#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v371 — Sencillas a cuota 1,30 o más con pocas rojas: ¿qué forma de elegir gana?

El usuario (11-oct), con un boleto de 4 patas que salió 1 ✅ 3 ❌: «tener 3/4
malas es inaceptable; mejora el algoritmo para dar apuestas con cuota mínima de
1,30 sencillas; evalúa todos los mercados; analiza cómo está la casa y sus
índices para saber a qué lado inclinarte, en los equipos o en la global;
también quién gana, incluso empates».

MÉTODO (DMAIC)
  Definir: defecto = pata roja. Meta: el menor % de rojas a cuota ≥ 1,30.
  Medir:   la forma de hoy (el armador viejo elige por el MODELO).
  Analizar: por mercado, lado (más/menos, local/visita), banda de la casa y
           distancia modelo↔casa (5 porqués en el commit).
  Mejorar: la regla que gane en las DOS mitades con p5 > 0 (bootstrap por
           partido) y sin bajar la cuota más de lo que sube el acierto.
  Controlar: el seguimiento de los boletos (la pantalla) y una carta p de
           las rojas por día.

DATOS
  A. PLAYDOIT, escaleras completas (`_v362b_lineas.pkl`, 28-ago → 9-oct):
     goles, goles por equipo, córners, tarjetas, tiros y a puerta; el «más» Y
     el «menos» de cada línea, con el Método Contexto entrenado sólo con lo
     anterior (`p_mod`), la casa sin margen (`p_casa`), la cuota y lo que pasó.
  B. NOVIBET real (`_v332_novibet_patas.pkl`, 10-sep → 7-oct): 1X2 (también
     el empate), doble oportunidad y ambos marcan, con resultado. La casa sin
     margen se saca de su propio mercado.
  Una casa por boleto: un parlay se juega en una sola casa.

FORMAS DE ELEGIR (una pata por partido, cuota 1,30-1,70)
  modelo   — la más probable según el modelo (lo que hacía el armador viejo).
  casa     — la más probable según la casa sin margen («inclinarse a la casa»).
  consenso — la mejor en el PEOR de los dos (que estén de acuerdo).
  aprendiz — logística entrenada semana a semana con lo anterior (método +
             casa + estadística + lado), como en `_v368_aprendiz.py`.
Escribe `_v371_sencillas.json`.
"""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(371)
CMIN, CMAX = 1.30, 1.70
OBJS = ['goles', 'corners', 'tiros', 'a_puerta', 'tarjetas']


# --------------------------------------------------------------------- datos
def playdoit():
    d = pd.read_pickle('_v362b_lineas.pkl')
    try:
        d = d.join(pd.read_pickle('_v366_lado.pkl'))
    except Exception:
        d['lado_real'] = np.where(d.tipo == 'total', 'total', 'sin')
    d = d[(d.p_mod - d.p_casa).abs() <= 0.20].copy()
    im_mas = 1.0 / d.c_mas
    d['c_menos'] = 1.0 / (im_mas * (1 - d.p_casa) / d.p_casa)
    mas = d.assign(lado_ap='más', p_m=d.p_mod, p_c=d.p_casa, cuota=d.c_mas, ok=d.y)
    men = d.assign(lado_ap='menos', p_m=1 - d.p_mod, p_c=1 - d.p_casa, cuota=d.c_menos, ok=1 - d.y)
    x = pd.concat([mas, men], ignore_index=True)
    x['mercado'] = x.obj + ' ' + x.tipo
    x['partido'] = x.mid.astype(str)
    x['dist_sd'] = (x.linea - x.mu) / np.sqrt(x.mu.clip(lower=0.2))
    return x[['partido', 'fecha', 'liga', 'mercado', 'obj', 'tipo', 'lado_ap', 'lado_real',
              'linea', 'dist_sd', 'p_m', 'p_c', 'cuota', 'ok']]


def novibet():
    d = pd.read_pickle('_v332_novibet_patas.pkl')
    d = d[d.mercado.isin(['1X2', 'Doble oportunidad', 'Ambos marcan'])].copy()
    d['im'] = 1.0 / d.cuota
    tot = d.groupby(['eid', 'mercado']).im.transform('sum')
    n = d.groupby(['eid', 'mercado']).im.transform('size')
    # 1X2 y ambos marcan: se reparte el margen; doble oportunidad suma 2
    d['p_c'] = np.where(d.mercado == 'Doble oportunidad', 2 * d.im / tot, d.im / tot)
    d = d[(n == np.where(d.mercado == 'Ambos marcan', 2, 3))]
    d['p_m'] = d.p_c                      # sin modelo propio cruzado: la casa
    d['ok'] = d.verde.astype(int)
    d['partido'] = d.eid
    d['obj'] = d.mercado
    d['tipo'] = d.apuesta
    d['lado_ap'] = d.apuesta
    return d[['partido', 'fecha', 'liga', 'mercado', 'obj', 'tipo', 'lado_ap', 'p_m', 'p_c',
              'cuota', 'ok']]


# --------------------------------------------------------------- el aprendiz
def aprendiz(x):
    """p_ap: logística entrenada SÓLO con semanas anteriores."""
    from sklearn.linear_model import LogisticRegression
    x = x.copy()
    x['semana'] = x.fecha.dt.to_period('W').astype(str)
    x['p_ap'] = np.nan
    lg = lambda p: np.log(p.clip(.01, .99) / (1 - p.clip(.01, .99)))
    mercs = sorted(x.mercado.unique())

    def F(q):
        cols = [lg(q.p_m), lg(q.p_c), (q.lado_ap == 'más').astype(float),
                q.get('dist_sd', pd.Series(0, index=q.index)).fillna(0)]
        cols += [(q.mercado == m).astype(float) for m in mercs]
        if 'lado_real' in q:
            cols += [(q.lado_real == 'local').astype(float), (q.lado_real == 'visita').astype(float)]
        return np.column_stack(cols)
    sem = sorted(x.semana.unique())
    for i, s in enumerate(sem):
        if i < 2:
            continue
        tr, te = x[x.semana < s], x[x.semana == s]
        lr = LogisticRegression(C=1.0, max_iter=3000).fit(F(tr), tr.ok)
        x.loc[te.index, 'p_ap'] = lr.predict_proba(F(te))[:, 1]
    return x


# --------------------------------------------------------------- las reglas
def elegir(x, regla, excluir=()):
    z = x[(x.cuota >= CMIN) & (x.cuota <= CMAX)]
    if excluir:
        z = z[~z.mercado.isin(excluir)]
    if regla == 'modelo':
        s = z.p_m
    elif regla == 'casa':
        s = z.p_c
    elif regla == 'consenso':
        s = np.minimum(z.p_m, z.p_c)
    else:
        z = z[z.p_ap.notna()]
        s = z.p_ap
    z = z.assign(score=s).sort_values('score', ascending=False).drop_duplicates('partido')
    z = z.assign(gan=np.where(z.ok == 1, z.cuota - 1, -1.0))
    return z


def _boot(z, col, n=2000):
    g = z.groupby('partido')[col].agg(['sum', 'count']).values
    out = []
    for _ in range(n):
        s = g[rng.integers(0, len(g), len(g))].sum(0)
        out.append(s[0] / s[1])
    return np.array(out)


def resumen(z):
    if not len(z):
        return {'n': 0}
    return {'n': int(len(z)), 'acierto': round(float(z.ok.mean()), 4),
            'acierto_p5': round(float(np.percentile(_boot(z, 'ok'), 5)), 4),
            'cuota': round(float(z.cuota.mean()), 3), 'gan_100': round(100 * float(z.gan.mean()), 1),
            'gan_p5': round(100 * float(np.percentile(_boot(z, 'gan'), 5)), 1)}


def boletos(z, n):
    z = z.assign(dia=z.fecha.dt.strftime('%Y-%m-%d'))
    out = []
    for dia, g in z.groupby('dia'):
        g = g.sort_values('score', ascending=False).head(n)
        if len(g) < n:
            continue
        out.append((int(g.ok.sum()), float(np.prod(g.cuota))))
    if not out:
        return {'dias': 0}
    bien = np.array([o[0] for o in out])
    return {'dias': len(out), 'enteros': int((bien == n).sum()),
            'pct_entero': round(float((bien == n).mean()), 3),
            'tres_o_mas_rojas': int((bien <= n - 3).sum()) if n >= 3 else None,
            'momio': round(float(np.mean([o[1] for o in out])), 2),
            'gan_100': round(100 * float(np.mean([(o[1] - 1) if b == n else -1
                                                  for b, o in zip(bien, out)])), 1)}


def comparar(x, nombre, excluir=()):
    corte = x.fecha.quantile(0.5)
    R = {}
    base = elegir(x, 'modelo', excluir)
    for regla in ('modelo', 'casa', 'consenso', 'aprendiz'):
        z = elegir(x, regla, excluir)
        fila = {'todo': resumen(z)}
        for t, f in (('A', z.fecha < corte), ('B', z.fecha >= corte)):
            q = z[f]
            b = base[(base.fecha < corte) if t == 'A' else (base.fecha >= corte)]
            fila[t] = resumen(q)
            if regla != 'modelo' and len(q) > 30 and len(b) > 30:
                da = _boot(q, 'ok') - _boot(b, 'ok')
                fila[t]['dif_vs_modelo'] = round(float(q.ok.mean() - b.ok.mean()), 4)
                fila[t]['dif_p5'] = round(float(np.percentile(da, 5)), 4)
        fila['boleto_3'] = boletos(z, 3)
        fila['boleto_4'] = boletos(z, 4)
        fila['por_mercado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3),
                                   round(float(g.cuota.mean()), 3)]
                               for m, g in z.groupby('mercado') if len(g) >= 15}
        R[regla] = fila
    return R


def analizar(x):
    """Dónde caen las rojas a cuota ≥ 1,30 (todas las líneas, sin elegir)."""
    z = x[(x.cuota >= CMIN) & (x.cuota <= CMAX)].copy()
    z['gap'] = pd.cut(z.p_m - z.p_c, [-1, -.05, 0, .05, 1],
                      labels=['casa ve +5', 'casa ve +0-5', 'modelo ve +0-5', 'modelo ve +5'])
    z['banda_casa'] = pd.cut(z.p_c, [0, .55, .60, .65, .70, .75, 1])
    out = {}
    for col in ('mercado', 'lado_ap', 'gap', 'banda_casa'):
        g = z.groupby(col, observed=True).agg(n=('ok', 'size'), acierto=('ok', 'mean'),
                                              casa=('p_c', 'mean'), modelo=('p_m', 'mean'),
                                              cuota=('cuota', 'mean'))
        out[col] = {str(k): {kk: round(float(v), 3) for kk, v in r.items()} for k, r in g.iterrows()}
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    R = {}
    A = aprendiz(playdoit())
    R['playdoit_analisis'] = analizar(A)
    R['playdoit'] = comparar(A, 'playdoit')
    R['playdoit_sin_perdedores'] = comparar(A, 'playdoit', excluir=('tarjetas equipo', 'tarjetas total',
                                                                    'corners equipo'))
    B = novibet()
    B['p_ap'] = B.p_c
    R['novibet_analisis'] = analizar(B)
    R['novibet'] = {k: v for k, v in comparar(B, 'novibet').items() if k in ('casa',)}
    json.dump(R, open('_v371_sencillas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    for k in ('playdoit', 'playdoit_sin_perdedores', 'novibet'):
        print('==', k)
        for regla, f in R[k].items():
            print('  %-9s todo %s | A %s | B %s | 3: %s | 4: %s' % (
                regla, f['todo'], {a: f['A'].get(a) for a in ('acierto', 'cuota', 'dif_vs_modelo', 'dif_p5')},
                {a: f['B'].get(a) for a in ('acierto', 'cuota', 'dif_vs_modelo', 'dif_p5')},
                f['boleto_3'], f['boleto_4']))
    for k in ('playdoit_analisis', 'novibet_analisis'):
        print('==', k)
        for col, v in R[k].items():
            print('  ', col, v)


if __name__ == '__main__':
    main()
