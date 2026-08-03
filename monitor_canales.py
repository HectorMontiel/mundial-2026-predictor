#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v92 — ¿Se está cobrando en producción el edge que dice el backtest?

Por qué existe
--------------
El proyecto lleva versiones validando canales de valor con bootstrap fuera de
muestra —fútbol p5 +1,07 %, WTA p5 +0,61 %, MLB p5 +1,67 %— y publicando picks
con esos números detrás. Pero nadie comprobaba lo obvio: que lo que se emite de
verdad, día a día, se parezca a lo que se midió. Un backtest es una promesa;
esto es la factura.

Y hasta la v92 ni siquiera se podía mirar, porque `rendimiento_real` guardaba
todos los picks juntos: el ROI agregado no distingue si lo que falla es el
canal validado o si simplemente ese día hubo pocos picks suyos. La columna
`canal` (v92) separa las vías.

Cómo se lee
-----------
Para cada canal se compara el ROI real de los picks LIQUIDADOS contra su
referencia de backtest, y se emite un veredicto con tres estados:

  ✅ en rango   — el ROI real está por encima del p5 del backtest.
  ⚠️ por debajo — está por debajo del p5. No es prueba de que el edge se haya
                  roto (el p5 es el peor 5 % plausible: tocarlo entra dentro
                  de lo esperado), pero sí de que hay que mirar.
  ⏳ sin muestra — menos de `MIN_LIQUIDADOS` picks resueltos. Se dice, en vez
                  de enseñar un ROI de tres apuestas como si significara algo.

Ese último estado es el importante y el que más se va a ver al principio: con
pocas apuestas, el ROI es ruido. Enseñar «+40 % de ROI» sobre 5 picks sería
exactamente el error que este proyecto lleva siete versiones documentando.
"""
import logging
import os
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB = 'rendimiento_real.db'
# por debajo de esto el ROI es ruido y se dice en vez de dibujarlo
MIN_LIQUIDADOS = 30

# Referencias de backtest, con su procedencia. Son las cifras validadas fuera
# de muestra que aparecen en los VALIDACION correspondientes.
REFERENCIAS: Dict[str, dict] = {
    'line_shopping': {
        'nombre': 'Line shopping vs Pinnacle',
        'roi': 8.57, 'p5': 1.07, 'n_backtest': 643,
        'fuente': 'v90 · 26.666 partidos de fútbol, pliegues 3-4',
    },
    'modelo': {
        'nombre': 'Modelo con encogimiento al mercado',
        'roi': 6.72, 'p5': 0.92, 'n_backtest': 584,
        'fuente': 'v78 · ledger de fútbol con w=0,25',
    },
}


def _con() -> Optional[sqlite3.Connection]:
    if not os.path.exists(DB):
        return None
    try:
        return sqlite3.connect(DB)
    except Exception as e:
        logger.warning(f'[monitor_canales] base ilegible: {e}')
        return None


def rendimiento(dias: int = 30) -> Dict:
    """ROI real por canal en la ventana, contra su referencia de backtest."""
    con = _con()
    if con is None:
        return {'canales': [], 'aviso': 'Sin rendimiento_real.db todavía: el '
                                        'registro se crea con el primer '
                                        'barrido que emita picks.'}
    try:
        import pandas as pd
        cols = {r[1] for r in con.execute('PRAGMA table_info(picks)')}
        if 'canal' not in cols:
            con.close()
            return {'canales': [], 'aviso': 'El registro es anterior a la v92 '
                                            'y no distingue canales; se '
                                            'separan solos con los picks '
                                            'nuevos.'}
        desde = (pd.Timestamp.utcnow() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
        df = pd.read_sql_query(
            "SELECT canal, deporte, prob, cuota, ev, resultado FROM picks "
            "WHERE fecha >= ? AND capa = 'capa1'", con, params=[desde])
        con.close()
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        return {'canales': [], 'aviso': f'Registro ilegible ({type(e).__name__}).'}

    if df.empty:
        return {'canales': [], 'aviso': f'Sin picks de Capa 1 en los últimos '
                                        f'{dias} días.'}

    salida: List[Dict] = []
    for canal, g in df.groupby(df['canal'].fillna('sin_clasificar')):
        ref = REFERENCIAS.get(canal, {})
        liq = g.dropna(subset=['resultado'])
        liq = liq[liq['cuota'].notna()]
        fila = {
            'canal': canal,
            'nombre': ref.get('nombre', canal.replace('_', ' ').capitalize()),
            'emitidos': int(len(g)),
            'liquidados': int(len(liq)),
            'ref_roi': ref.get('roi'), 'ref_p5': ref.get('p5'),
            'ref_fuente': ref.get('fuente'),
            'deportes': sorted({str(d) for d in g['deporte'].dropna()}),
        }
        if len(liq) >= MIN_LIQUIDADOS:
            ganancia = ((liq['cuota'] - 1.0) * liq['resultado']
                        - (1 - liq['resultado']))
            fila['roi'] = round(float(ganancia.mean()) * 100, 2)
            fila['acierto'] = round(float(liq['resultado'].mean()) * 100, 1)
            p5 = ref.get('p5')
            fila['estado'] = ('sin_referencia' if p5 is None else
                              'ok' if fila['roi'] >= p5 else 'bajo')
        else:
            fila['roi'] = None
            fila['acierto'] = None
            fila['estado'] = 'sin_muestra'
            fila['faltan'] = MIN_LIQUIDADOS - len(liq)
        salida.append(fila)

    salida.sort(key=lambda f: -f['emitidos'])
    return {'canales': salida, 'dias': dias, 'min_liquidados': MIN_LIQUIDADOS,
            'aviso': None}


def veredicto(fila: Dict) -> str:
    """Una frase por canal, sin adornos y sin prometer lo que no se sabe."""
    e = fila.get('estado')
    if e == 'sin_muestra':
        return (f"⏳ {fila['liquidados']} picks resueltos de "
                f"{fila['emitidos']} emitidos: faltan {fila.get('faltan', 0)} "
                f"para que el ROI signifique algo. Con menos, es ruido.")
    if e == 'sin_referencia':
        return (f"ℹ️ ROI real {fila['roi']:+.2f} % sobre {fila['liquidados']} "
                f"picks. Este canal no tiene referencia de backtest con la que "
                f"compararlo.")
    if e == 'ok':
        return (f"✅ ROI real {fila['roi']:+.2f} % sobre {fila['liquidados']} "
                f"picks, por encima del peor caso plausible del backtest "
                f"(p5 {fila['ref_p5']:+.2f} %). El canal se está comportando.")
    return (f"⚠️ ROI real {fila['roi']:+.2f} % sobre {fila['liquidados']} "
            f"picks, por DEBAJO del p5 del backtest ({fila['ref_p5']:+.2f} %). "
            f"No prueba que el edge se haya roto —el p5 es el peor 5 % "
            f"plausible y tocarlo entra en lo esperado— pero toca vigilarlo.")


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    for d in (7, 30):
        r = rendimiento(d)
        print(f"\n=== últimos {d} días ===")
        if r.get('aviso'):
            print(' ', r['aviso'])
            continue
        for f in r['canales']:
            print(f"  {f['nombre']:38s} emitidos {f['emitidos']:4d} · "
                  f"liquidados {f['liquidados']:4d}")
            print(f"    {veredicto(f)}")
