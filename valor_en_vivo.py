#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Valor en Vivo (v34 §6, reescrito en v89) — evolución del EV SIN consumir API.

RESTRICCIÓN ESTRICTA del spec: esta vista **nunca** hace peticiones HTTP.
Se alimenta solo de:
  * las fotos diarias de `historical_odds` (fase='snapshot', las que captura
    `daily_snapshots.py` y persisten en `odds_snapshots.csv`),
  * las probabilidades del modelo (cálculo local).

v89 — por qué se reescribió: hasta la v88 leía la tabla `snapshots` de la
v43, cuyo ÚNICO escritor era el acelerador RLM de The Odds API, eliminado en
la v88. En Streamlit Cloud la base se creaba sin esa tabla y la vista tiraba
la app entera (`OperationalError: no such table: snapshots`). La fuente viva
es `historical_odds` fase='snapshot', que además trae `league_key` y los
nombres del catálogo del modelo — desaparecen el parseo de `match_id` y el
mapeo fuzzy de equipos que necesitaba la versión anterior.

En Cloud la base es efímera: si no hay fotos se rehidrata desde
`odds_snapshots.csv` (commiteado en el repositorio, sin tocar la red).

Para cada partido futuro con fotos, se toma la mejor cuota vigente por
selección y la TENDENCIA en esa casa (si la cuota sube, el mercado se aleja
de nuestro pick; si baja, se acerca — el clásico "line movement").
"""

import logging
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)


def _snapshots() -> pd.DataFrame:
    """Fotos 1X2 de partidos aún no jugados; rehidrata la base si hace falta."""
    import odds_store
    try:
        con = odds_store.conectar()
        n = con.execute("SELECT COUNT(*) FROM historical_odds "
                        "WHERE fase='snapshot'").fetchone()[0]
        if not n:
            odds_store.importar_snapshots(con)
        df = pd.read_sql_query(
            "SELECT match_id, league_key, match_date, home_team, away_team, "
            "bookmaker, ingested_at, odds_home, odds_draw, odds_away "
            "FROM historical_odds WHERE fase='snapshot' "
            "AND odds_home IS NOT NULL AND odds_draw IS NOT NULL "
            "AND odds_away IS NOT NULL "
            "ORDER BY ingested_at", con)
        con.close()
    except Exception as e:
        logger.warning(f"fotos de cuotas ilegibles ({e}); la vista sale vacía.")
        return pd.DataFrame()
    if df.empty:
        return df
    hoy = pd.Timestamp.utcnow().strftime('%Y-%m-%d')
    return df[df['match_date'] >= hoy]


def _ancla_mercado(g: pd.DataFrame) -> Dict[str, float]:
    """Probabilidad justa del mercado desde las fotos de ESTE partido.

    Se prefiere la última foto de Pinnacle (precio sharp); si no hay, la
    última de cualquier casa. Devig proporcional. Devuelve {} si no hay terna.
    """
    pin = g[g['bookmaker'].str.lower() == 'pinnacle']
    fila = (pin if not pin.empty else g).iloc[-1]
    try:
        inv = [1.0 / float(fila[c]) for c in ('odds_home', 'odds_draw',
                                              'odds_away')]
    except (TypeError, ValueError, ZeroDivisionError):
        return {}
    s = sum(inv)
    if s <= 0:
        return {}
    return {'home': inv[0] / s, 'draw': inv[1] / s, 'away': inv[2] / s}


def valor_en_vivo(max_partidos: int = 25) -> Dict:
    """Tabla de EV actual y tendencia por partido (sin tocar la red)."""
    df = _snapshots()
    if df.empty:
        return {'filas': [], 'aviso': 'Sin fotos de cuotas para partidos '
                                      'futuros: la vista se llena conforme '
                                      'daily_snapshots captura la línea '
                                      '(sin gastar API extra).'}
    from league_engine import ClubEngine
    motores: Dict[str, object] = {}
    filas = []
    n_partidos = 0
    for mid, g in df.groupby('match_id', sort=False):
        if n_partidos >= max_partidos:
            break
        liga = g['league_key'].iloc[0]
        home, away = g['home_team'].iloc[0], g['away_team'].iloc[0]
        if liga not in motores:
            try:
                motores[liga] = ClubEngine(liga)
            except Exception:
                motores[liga] = None
        eng = motores[liga]
        if eng is None or not getattr(eng, 'listo', False) \
                or home not in eng.stats or away not in eng.stats:
            continue
        # anclar=False: con True `predecir` sale a buscar mercado por red
        # (contra el spec de esta vista) — y el mercado YA está en la foto.
        pred = eng.predecir(home, away, anclar=False)
        if 'error' in pred:
            continue
        probs = pred['prediction']['probabilities']
        # v89 — encogimiento hacia el mercado de la PROPIA foto, con el w por
        # liga validado (v87 midió que el modelo crudo acierta 33,6 % cuando
        # discrepa fuerte del mercado; encogido, 55,5 %). Sin esto la vista
        # mostraba EV de +90 % que eran desacuerdo modelo-mercado, no valor.
        ancla = _ancla_mercado(g)
        if ancla:
            import calibracion_mercado as _cmer
            probs, _ = _cmer.corregir(probs, ancla, liga)
        n_partidos += 1
        for sel, col in (('home', 'odds_home'), ('draw', 'odds_draw'),
                         ('away', 'odds_away')):
            sub = g.dropna(subset=[col])
            if sub.empty:
                continue
            # última foto de cada casa → el precio VIGENTE por casa; de esas,
            # la mejor cuota es la apostable ahora mismo
            vigentes = sub.groupby('bookmaker', sort=False).tail(1)
            mejor = vigentes.loc[vigentes[col].idxmax()]
            cuota = float(mejor[col])
            ev = cuota * probs[sel] - 1
            if ev <= 0:
                continue
            # tendencia dentro de la casa del mejor precio (mezclar casas
            # convertiría diferencias de margen en falsas "subidas")
            serie = sub[sub['bookmaker'] == mejor['bookmaker']]
            cuota0 = float(serie.iloc[0][col])
            delta = cuota - cuota0
            tendencia = ('📈 la cuota sube (más valor)' if delta > 0.01 else
                         '📉 la cuota baja (el mercado se ajusta)'
                         if delta < -0.01 else '➖ estable')
            filas.append({
                'partido': f'{home} vs {away}', 'liga': liga,
                'mercado': {'home': f'Gana {home}', 'draw': 'Empate',
                            'away': f'Gana {away}'}[sel],
                'cuota_actual': round(cuota, 2),
                'cuota_inicial': round(cuota0, 2),
                'ev_pct': round(ev * 100, 1),
                'tendencia': tendencia,
                'casa': str(mejor['bookmaker']),
                'snapshots': int(len(serie)),
                'ultima_captura': str(mejor['ingested_at'])})
    filas.sort(key=lambda f: -f['ev_pct'])
    return {'filas': filas, 'n_partidos': int(df['match_id'].nunique()),
            'aviso': None if filas else
            'Sin oportunidades con EV positivo en las fotos guardadas.'}


if __name__ == '__main__':
    import json
    import sys
    import warnings
    warnings.filterwarnings('ignore')
    # La consola de Windows es cp1252: sin esto, imprimir la flecha de
    # tendencia aborta el script después de haber hecho todo el trabajo.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO)
    r = valor_en_vivo()
    print(f"partidos con snapshots: {r.get('n_partidos')} · filas: {len(r['filas'])}")
    for f in r['filas'][:8]:
        print(f"  {f['liga']:<10} {f['partido'][:34]:<34} {f['mercado'][:22]:<22} "
              f"@ {f['cuota_actual']} ({f['casa']}) EV {f['ev_pct']:+.1f}% {f['tendencia']}")
