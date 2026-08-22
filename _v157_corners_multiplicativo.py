#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v157 — CÓRNERS CON FUERZA DE ATAQUE Y DEFENSA, Y CON LA MÉTRICA CORRECTA.

Qué cambia respecto a la v156
-----------------------------
Dos cosas, y las dos importan.

1. LA MÉTRICA. La v156 midió MAE y concluyó que la línea estaba cerrada. El
   suelo del MAE (2,48) es correcto, pero con un ruido de Poisson de desviación
   3,2 encima, capturar señal de desviación 1,29 mueve el MAE unas centésimas:
   queda sepultado. Medido en la v157:

       sd(λ) = 1,288      corr máxima alcanzable = 0,378
       corr lograda       = 0,061   → el 16 % del margen

   O sea que SÍ hay señal y el MAE no la veía. La métrica de aquí es la
   CORRELACIÓN, que es además lo que importa para apostar: no acertar el número
   exacto, sino distinguir los partidos que van por encima de la línea.

2. EL MODELO. La v156 hacía regresión sobre medias móviles. Aquí se prueba la
   estructura que se usa para goles desde Dixon-Coles y que nunca se aplicó a
   los córners de este proyecto:

       λ_local    = media_liga_local × ataque(local) × defensa(visitante)
       λ_visitante= media_liga_visit × ataque(visit) × defensa(local)

   La diferencia no es cosmética: una regresión trata «córners que saca A» y
   «córners que concede B» como dos números sueltos, y el multiplicativo los
   combina como lo que son — una tasa de ataque contra una de defensa, cada una
   relativa a su liga y a su bando.

   Las fuerzas se estiman con DECAIMIENTO EXPONENCIAL sobre todo el historial
   previo, no con una media de los últimos 5: cinco partidos de un equipo son
   una muestra de 5, y el ruido de Poisson de esa muestra es mayor que la señal
   que se busca.
"""
import json
import logging
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import league_engine as le

LIGAS = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'eredivisie',
         'primeira', 'turquia', 'sco_premiership', 'bel_pro_league',
         'eng_championship', 'eng_league_one', 'eng_league_two',
         'eng_national', 'esp_hypermotion', 'ita_serie_b', 'fra_ligue2',
         'ger_bundesliga2', 'sco_championship', 'gre_super_league']

# Vida media del decaimiento, en días. 180 = un partido de hace medio año pesa
# la mitad que uno de hoy. Se prueban varias y se elige por validación.
VIDAS = (90, 180, 365)
MIN_PREVIOS = 6


def construir(df: pd.DataFrame, vida_dias: int) -> pd.DataFrame:
    """
    Un pase cronológico que estima, para cada partido, las fuerzas PREVIAS.

    Todo lo que entra en la fila de un partido se calcula con los partidos
    ANTERIORES a su fecha. El decaimiento es exponencial por días, así que un
    equipo que cambió de estilo hace tres meses pesa menos que su forma actual
    sin necesidad de una ventana dura.
    """
    df = df.sort_values('date').reset_index(drop=True)
    # acumuladores ponderados por equipo y bando
    ac = {}

    def A(eq):
        return ac.setdefault(eq, {
            'cf_casa': 0.0, 'n_casa': 0.0, 'cc_casa': 0.0,
            'cf_fuera': 0.0, 'n_fuera': 0.0, 'cc_fuera': 0.0})

    # medias de liga, también ponderadas y sólo con lo anterior
    lig = {'cf_casa': 0.0, 'cf_fuera': 0.0, 'n': 0.0}
    tau = np.log(2) / float(vida_dias)
    filas = []
    ultimo_ts = None

    for f in df.itertuples(index=False):
        ts = pd.Timestamp(f.date)
        if ultimo_ts is not None:
            dt = max((ts - ultimo_ts).days, 0)
            if dt:
                w = float(np.exp(-tau * dt))
                for d in ac.values():
                    for k in d:
                        d[k] *= w
                for k in lig:
                    lig[k] *= w
        ultimo_ts = ts

        hh, ha = A(f.home_team), A(f.away_team)
        fila = {'date': ts,
                'ck_total': float(f.home_corners) + float(f.away_corners)}
        if (hh['n_casa'] >= MIN_PREVIOS and ha['n_fuera'] >= MIN_PREVIOS
                and lig['n'] >= 40):
            m_casa = lig['cf_casa'] / lig['n']
            m_fuera = lig['cf_fuera'] / lig['n']
            # fuerzas relativas a la media de la liga EN ESE BANDO
            at_h = (hh['cf_casa'] / hh['n_casa']) / m_casa if m_casa else 1.0
            df_a = (ha['cc_fuera'] / ha['n_fuera']) / m_casa if m_casa else 1.0
            at_a = (ha['cf_fuera'] / ha['n_fuera']) / m_fuera if m_fuera else 1.0
            df_h = (hh['cc_casa'] / hh['n_casa']) / m_fuera if m_fuera else 1.0
            lam_h = m_casa * at_h * df_a
            lam_a = m_fuera * at_a * df_h
            fila.update({'lam_h': lam_h, 'lam_a': lam_a,
                         'lam_tot': lam_h + lam_a,
                         'at_h': at_h, 'df_a': df_a, 'at_a': at_a, 'df_h': df_h,
                         'media_liga': m_casa + m_fuera})
        filas.append(fila)

        ckh, cka = float(f.home_corners), float(f.away_corners)
        hh['cf_casa'] += ckh; hh['cc_casa'] += cka; hh['n_casa'] += 1.0
        ha['cf_fuera'] += cka; ha['cc_fuera'] += ckh; ha['n_fuera'] += 1.0
        lig['cf_casa'] += ckh; lig['cf_fuera'] += cka; lig['n'] += 1.0
    return pd.DataFrame(filas)


def boot_p5(dif, n_iter=2000, semilla=7):
    rng = np.random.default_rng(semilla)
    d = np.asarray(dif, float)
    m = rng.choice(d, size=(n_iter, len(d)), replace=True).mean(axis=1)
    return round(float(np.percentile(m, 5)), 4)


def mide(clave, temporadas=8):
    t0 = time.time()
    df = le.descargar_liga(clave, temporadas=temporadas)
    df = df.dropna(subset=['home_corners', 'away_corners'])
    if len(df) < 800:
        return {'liga': clave, 'excluida': True, 'motivo': 'n=%d' % len(df)}

    mejor = None
    for vida in VIDAS:
        d = construir(df, vida).dropna(subset=['lam_tot'])
        if len(d) < 500:
            continue
        corte_val = d['date'].quantile(0.60)
        corte_te = d['date'].quantile(0.75)
        val = d[(d['date'] > corte_val) & (d['date'] <= corte_te)]
        if len(val) < 100:
            continue
        # se ELIGE la vida media en validación, nunca en el tramo de juicio
        c = float(np.corrcoef(val['lam_tot'], val['ck_total'])[0, 1])
        if mejor is None or c > mejor[1]:
            mejor = (vida, c, d, corte_te)
    if mejor is None:
        return {'liga': clave, 'excluida': True, 'motivo': 'sin ventana valida'}
    vida, _c_val, d, corte_te = mejor

    tr = d[d['date'] <= corte_te]
    te = d[d['date'] > corte_te]
    if len(te) < 120:
        return {'liga': clave, 'excluida': True, 'motivo': 'juicio n=%d' % len(te)}
    y = te['ck_total'].to_numpy(float)
    const = float(tr['ck_total'].mean())
    e_const = np.abs(y - const)

    # A) el multiplicativo tal cual
    p_mult = te['lam_tot'].to_numpy(float)
    # B) el multiplicativo RECALIBRADO: una recta ajustada en el train corrige
    #    el nivel y encoge la parte variable a lo que de verdad vale.
    b, a = np.polyfit(tr['lam_tot'], tr['ck_total'], 1)
    p_cal = a + b * p_mult

    var = float(np.var(y))
    media = float(np.mean(y))
    sd_lambda = float(np.sqrt(max(var - media, 0.0)))
    techo = sd_lambda / np.sqrt(var) if var else 0.0

    salida = {'liga': clave, 'excluida': False, 'vida_dias': vida,
              'n_train': int(len(tr)), 'n_juicio': int(len(te)),
              'mae_constante': round(float(e_const.mean()), 4),
              'corr_techo': round(float(techo), 4)}
    for nombre, p in (('multiplicativo', p_mult), ('recalibrado', p_cal)):
        err = np.abs(y - p)
        salida[nombre] = {
            'mae': round(float(err.mean()), 4),
            'mejora_mae': round(float((e_const - err).mean()), 4),
            'p5_mae': boot_p5(e_const - err),
            'corr': round(float(np.corrcoef(p, y)[0, 1]), 4)
            if np.std(p) > 1e-9 else 0.0,
            'sd_pred': round(float(np.std(p)), 3),
        }
    salida['segundos'] = round(time.time() - t0, 1)
    return salida


def main():
    claves = sys.argv[1:] or LIGAS
    res = []
    for c in claves:
        try:
            r = mide(c)
        except Exception as e:
            r = {'liga': c, 'excluida': True,
                 'motivo': '%s: %s' % (type(e).__name__, e)}
        res.append(r)
        if r.get('excluida'):
            print('%-20s EXCL %s' % (r['liga'], r.get('motivo')), flush=True)
        else:
            print('%-20s vida %3d | corr mult %+.3f | corr recal %+.3f | '
                  'techo %.3f | MAE %.3f (cte %.3f)'
                  % (r['liga'], r['vida_dias'], r['multiplicativo']['corr'],
                     r['recalibrado']['corr'], r['corr_techo'],
                     r['recalibrado']['mae'], r['mae_constante']), flush=True)

    ok = [r for r in res if not r.get('excluida')]
    if not ok:
        return
    n = sum(r['n_juicio'] for r in ok)

    def pond(*ruta):
        tot = 0.0
        for r in ok:
            v = r
            for k in ruta:
                v = v[k]
            tot += v * r['n_juicio']
        return round(tot / n, 4)

    resumen = {
        'ligas': len(ok), 'n_juicio': n,
        'mae_constante': pond('mae_constante'),
        'mae_recalibrado': pond('recalibrado', 'mae'),
        'corr_multiplicativo': pond('multiplicativo', 'corr'),
        'corr_recalibrado': pond('recalibrado', 'corr'),
        'corr_techo': pond('corr_techo'),
        'corr_v156_ridge': 0.0609,
        'ligas_p5_mae_positivo': sum(
            1 for r in ok if r['recalibrado']['p5_mae'] > 0),
        'ligas_corr_positiva': sum(
            1 for r in ok if r['recalibrado']['corr'] > 0),
    }
    resumen['fraccion_del_techo'] = round(
        resumen['corr_recalibrado'] / resumen['corr_techo'], 4) \
        if resumen['corr_techo'] else 0.0
    print('\nRESUMEN ' + json.dumps(resumen, ensure_ascii=False, indent=1))
    json.dump({'ligas': res, 'resumen': resumen},
              open('_v157_corners_multiplicativo.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
