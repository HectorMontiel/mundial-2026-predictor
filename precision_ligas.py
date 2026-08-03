#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — El TECHO REAL de acierto de cada competición.

Por qué existe
--------------
La app presenta los ~274 pronósticos del día con el mismo aire de autoridad,
y no lo tienen. Medido sobre las 26.666 filas del ledger que llevan cierre de
Pinnacle, el acierto del MERCADO —que es el mejor predictor disponible, y por
tanto el techo práctico— va del 42,4 % en la Serie B italiana al 59,1 % en la
Superliga turca. Diecisiete puntos de diferencia entre competiciones.

Eso cambia la decisión del usuario: un pronóstico al 55 % en Turquía y otro al
55 % en la Serie B no valen lo mismo, porque en una el techo da margen y en la
otra ya se está pidiendo más de lo que nadie consigue. Enseñar el techo no es
un adorno de transparencia — es lo que permite no apostar donde la predicción
no funciona.

Se mide también el acierto del MODELO en la misma población, y el resultado
hay que decirlo tal cual: **el modelo bate al mercado en 1 de 34 ligas**
(sco_premiership, +1,30 pp). No es un fallo de este proyecto, es lo normal
contra un cierre eficiente, y es la razón por la que la Capa 1 se apoya en el
line shopping y no en ganarle al mercado.

Cómo se valida (y por qué no es el error de la v38)
---------------------------------------------------
La v38 midió que el ROI por liga NO es estacionario y por eso se rechazó
elegir ligas por su rentabilidad pasada. El acierto es otra cosa: refleja el
equilibrio competitivo de la liga (si hay favoritos claros o todos se parecen),
que es una propiedad estructural y cambia despacio. Pero eso hay que
comprobarlo, no suponerlo: `generar()` mide la correlación entre el acierto de
los pliegues tempranos y el de los tardíos, y **sólo publica el fichero si esa
correlación es alta**. Si no lo fuera, el techo sería ruido y no se publicaría.

Esto NO filtra picks ni toca ninguna probabilidad. Sólo informa.
"""
import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

ARCHIVO = 'precision_ligas.json'
LEDGER = 'pick_ledger_total.csv'
MIN_PARTIDOS = 300          # por debajo, el acierto medido es ruido
MIN_CORRELACION = 0.50      # si el techo no se sostiene entre mitades, no se publica
_CACHE: Dict[str, dict] = {}


def _devig_potencia(cuotas):
    import numpy as np
    inv = 1.0 / cuotas
    out = np.empty_like(inv)
    for i in range(len(inv)):
        p = inv[i]
        lo, hi = 0.5, 1.5
        for _ in range(40):
            mid = (lo + hi) / 2
            if (p ** mid).sum() > 1:
                lo = mid
            else:
                hi = mid
        q = p ** ((lo + hi) / 2)
        out[i] = q / q.sum()
    return out


def generar(ruta: str = ARCHIVO) -> dict:
    """Mide el techo por liga y lo publica SÓLO si es estable entre mitades."""
    import numpy as np
    import pandas as pd

    df = pd.read_csv(LEDGER)
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away', 'resultado',
                           'p_home', 'p_draw', 'p_away'])
    for c in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[c] > 1.0]

    mk = _devig_potencia(df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float))
    pm = df[['p_home', 'p_draw', 'p_away']].to_numpy(float)
    pm = pm / pm.sum(axis=1, keepdims=True)
    y = df['resultado'].to_numpy(int)
    df = df.assign(_mk=(mk.argmax(axis=1) == y), _pm=(pm.argmax(axis=1) == y))

    # --- comprobación de estabilidad: ¿el techo de la primera mitad predice
    #     el de la segunda? Si no, esto es ruido y no se publica.
    temp = df[df['pliegue'] <= 2].groupby('liga')['_mk'].agg(['mean', 'size'])
    tard = df[df['pliegue'] >= 3].groupby('liga')['_mk'].agg(['mean', 'size'])
    par = temp.join(tard, lsuffix='_t', rsuffix='_j')
    par = par[(par['size_t'] >= 150) & (par['size_j'] >= 60)]
    corr = float(par['mean_t'].corr(par['mean_j'])) if len(par) >= 8 else 0.0

    g = df.groupby('liga').agg(n=('resultado', 'size'), mercado=('_mk', 'mean'),
                               modelo=('_pm', 'mean'))
    g = g[g['n'] >= MIN_PARTIDOS]

    salida = {
        'generado': pd.Timestamp.today().strftime('%Y-%m-%d'),
        'n_total': int(len(df)),
        'correlacion_mitades': round(corr, 4),
        'estable': bool(corr >= MIN_CORRELACION),
        'nota': ('Acierto real del 1X2 sobre el ledger con cierre de Pinnacle. '
                 '«mercado» es el acierto de la cuota de cierre devigada: el '
                 'mejor predictor disponible y por tanto el techo práctico de '
                 'la competición. «modelo» es el acierto del modelo propio en '
                 'la misma población.'),
        'ligas': {liga: {'n': int(r['n']),
                         'mercado': round(float(r['mercado']), 4),
                         'modelo': round(float(r['modelo']), 4)}
                  for liga, r in g.iterrows()},
    }
    if not salida['estable']:
        logger.warning(f'[precision_ligas] techo por liga INESTABLE '
                       f'(correlación entre mitades {corr:.3f} < '
                       f'{MIN_CORRELACION}); no se publica.')
        return salida
    from io_atomico import escribir_json
    escribir_json(ruta, salida)
    logger.info(f'[precision_ligas] {len(salida["ligas"])} ligas · '
                f'correlación entre mitades {corr:.3f}')
    return salida


def _tabla() -> dict:
    if 'datos' not in _CACHE:
        datos = {}
        try:
            if os.path.exists(ARCHIVO):
                with open(ARCHIVO, encoding='utf-8') as f:
                    datos = json.load(f) or {}
        except Exception as e:
            logger.warning(f'[precision_ligas] no se pudo leer {ARCHIVO}: {e}')
        _CACHE['datos'] = datos
    return _CACHE['datos']


def techo(clave_liga: Optional[str]) -> Optional[dict]:
    """{'n','mercado','modelo'} de esa liga, o None si no está medida."""
    if not clave_liga:
        return None
    return (_tabla().get('ligas') or {}).get(str(clave_liga).strip().lower())


def etiqueta(clave_liga: Optional[str]) -> str:
    """Frase corta para la UI. Cadena vacía si la liga no está medida."""
    t = techo(clave_liga)
    if not t:
        return ''
    m = t['mercado'] * 100
    icono = '🟢' if m >= 54 else ('🟡' if m >= 48 else '🔴')
    return (f'{icono} Techo de la liga: ni el mercado acierta más del '
            f'{m:.0f} % aquí ({t["n"]} partidos medidos)')


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    r = generar()
    print(f"correlación entre mitades: {r['correlacion_mitades']} · "
          f"estable: {r['estable']}")
    ligas = sorted(r['ligas'].items(), key=lambda kv: -kv[1]['mercado'])
    print(f"\n{'liga':24s} {'n':>6s} {'techo (mercado)':>16s} {'modelo':>9s} {'dif':>8s}")
    print('-' * 68)
    for k, v in ligas:
        d = (v['modelo'] - v['mercado']) * 100
        print(f"{k:24s} {v['n']:6d} {v['mercado']*100:15.2f} % "
              f"{v['modelo']*100:8.2f} % {d:+7.2f} pp")
    bate = [k for k, v in ligas if v['modelo'] > v['mercado']]
    print(f"\nel modelo bate al mercado en {len(bate)} de {len(ligas)} ligas: {bate}")
