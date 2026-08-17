#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v146 · Sección de CÓRNERS de la ficha de partido.

Qué enseña, y por qué en este orden
-----------------------------------
1. **El total esperado del modelo** y, al lado, **la línea que cotiza la
   casa**. Juntos, porque la información que decide no es ninguno de los dos
   por separado: es la diferencia entre ambos.
2. **Los precios reales de Playdoit**, total del partido y por equipo, con la
   probabilidad del modelo al lado.
3. **El H2H de córners** de los últimos enfrentamientos directos.

Qué NO enseña, y esto es deliberado
-----------------------------------
**No hay columna de EV ni recomendación de línea.** Medido el 2026-08-16, el
total de córners que predice el modelo va **~1 córner por encima** de la línea
que cotiza la casa (n=4 partidos con línea publicada, correlación modelo-línea
+0,81). Con ese desfase, cruzar la probabilidad contra la cuota produce EV de
+50 % a +136 % en cada «Más de N» — la firma exacta de `EV_SOSPECHOSO`, que en
este proyecto se lee como «el modelo se equivoca», no como «la casa regala».

La correlación de +0,81 dice que el modelo **ordena** bien los partidos; lo que
no está validado es su **nivel**. Por eso se enseña lo que sí se sabe —el
precio real y el pronóstico, uno al lado del otro— y se dice en pantalla qué
falta para poder recomendar. Enseñar un EV que sé desplazado sería inventarle
valor a un mercado, que es justo lo que la bitácora §0 prohíbe.

Se quita el aviso y aparece la recomendación en cuanto el nivel esté validado
contra los lambdas de producción sobre muestra grande.
"""
from __future__ import annotations

import html
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AVISO_NIVEL = (
    "El modelo **ordena** bien los partidos de córners (correlación +0,81 con "
    "la línea de la casa) pero su **nivel** va ~1 córner alto, así que aquí no "
    "se publica EV ni recomendación: saldría inflado en todas las líneas. "
    "Los precios sí son reales y sirven para comparar."
)


def _esc(t) -> str:
    return html.escape(str(t if t is not None else ''), quote=True)


def _campo(pl: Dict, cid: str):
    """El valor de un campo de la plantilla por id, o None."""
    for s in (pl or {}).get('secciones', []):
        for c in s.get('campos', []):
            if c.get('id') == cid:
                return c.get('valor')
    return None


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def h2h_corners(clave: str, home: str, away: str, n: int = 5) -> List[Dict]:
    """
    Los últimos enfrentamientos directos con sus córners.

    Sale del mismo `historico_{clave}.csv` que alimenta al modelo, así que no
    añade ninguna fuente ni ninguna petición de red.
    """
    import os

    import pandas as pd
    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        return []
    try:
        d = pd.read_csv(ruta, usecols=['date', 'home_team', 'away_team',
                                       'home_corners', 'away_corners'],
                        parse_dates=['date'])
    except Exception as e:
        logger.debug(f'[corners] {ruta}: {e}')
        return []
    d = d.dropna(subset=['home_corners', 'away_corners'])
    m = d[((d['home_team'] == home) & (d['away_team'] == away))
          | ((d['home_team'] == away) & (d['away_team'] == home))]
    m = m.sort_values('date', ascending=False).head(n)
    out = []
    for r in m.itertuples(index=False):
        out.append({'fecha': str(r.date)[:10], 'home': r.home_team,
                    'away': r.away_team,
                    'ck_home': int(r.home_corners), 'ck_away': int(r.away_corners),
                    'total': int(r.home_corners) + int(r.away_corners)})
    return out


def barra_corners(ck_home: float, ck_away: float, home: str, away: str) -> str:
    """
    El reparto esperado de córners entre los dos equipos, en una barra.

    Mismos colores que el resto de la aplicación (verde local, azul visitante)
    para que no haya que aprender una paleta nueva por sección.
    """
    h, a = _f(ck_home) or 0.0, _f(ck_away) or 0.0
    tot = h + a
    if tot <= 0:
        return ''
    ph = h / tot * 100.0
    return (
        '<div style="display:flex;height:26px;border-radius:8px;overflow:hidden;'
        'border:1px solid var(--borde);margin:.35rem 0">'
        f'<span style="width:{ph:.1f}%;background:var(--ok);display:flex;'
        f'align-items:center;justify-content:center;font-size:.78rem;'
        f'font-weight:700" title="{_esc(home)} {h:.1f} córners">{h:.1f}</span>'
        f'<span style="width:{100-ph:.1f}%;background:var(--info);display:flex;'
        f'align-items:center;justify-content:center;font-size:.78rem;'
        f'font-weight:700" title="{_esc(away)} {a:.1f} córners">{a:.1f}</span>'
        '</div>')


def _lineas_de_la_casa(det: Dict, home: str, away: str) -> List[Dict]:
    """
    Las filas de córners del tablero de Playdoit, ya traducidas.

    Reutiliza `cuotas_tablon.filas_playdoit`, que es donde vive la traducción
    y su veto por seña. Duplicar aquí ese trabajo garantizaría que las dos
    copias digan cosas distintas en cuanto una cambie.
    """
    if not det:
        return []
    try:
        import cuotas_tablon as ct
        return [f for f in ct.filas_playdoit(det, home, away)
                if str(f.get('familia', '')).startswith('Córners')]
    except Exception as e:
        logger.debug(f'[corners] tablero: {e}')
        return []


def render(st, pl: Dict, clave: str, home: str, away: str,
           det: Optional[Dict] = None) -> None:
    """Pinta la sección entera. Nunca lanza: una sección no tumba la ficha."""
    try:
        _render(st, pl, clave, home, away, det)
    except Exception as e:                                  # pragma: no cover
        logger.warning(f'[corners-ui] {type(e).__name__}: {e}')
        st.caption(f'Sección de córners no disponible ahora '
                   f'({type(e).__name__}).')


def _render(st, pl, clave, home, away, det):
    import pandas as pd

    ck_tot = _f(_campo(pl, 'corners_media'))
    ck_h = _f(_campo(pl, 'ck_home_media'))
    ck_a = _f(_campo(pl, 'ck_away_media'))
    if ck_tot is None:
        return

    st.markdown('#### 🚩 Córners')

    filas = _lineas_de_la_casa(det, home, away)
    # la línea «pivote» de la casa: aquella cuya cuota está más cerca de 2,00,
    # que es donde la casa cree que está el 50 %. Es la forma más directa de
    # enseñar qué piensa el mercado sin devigar nada.
    pivote = None
    tot_casa = [f for f in filas if f['familia'] == 'Córners'
                and 'córners' in f['etiqueta'] and f['etiqueta'].startswith('Más de')]
    if tot_casa:
        pivote = min(tot_casa, key=lambda f: abs(f['cuota'] - 2.0))

    c1, c2, c3 = st.columns(3)
    c1.metric('Total esperado (modelo)', f'{ck_tot:.1f}')
    if pivote:
        _linea = pivote['etiqueta'].replace('Más de ', '').replace(' córners', '')
        c2.metric('Línea de la casa', _linea,
                  help='La línea cuya cuota está más cerca de 2,00: es donde '
                       'la casa sitúa el 50 %.')
        c3.metric('Diferencia', f"{ck_tot - float(_linea):+.1f}",
                  help='Cuánto se separa el modelo del mercado. Positivo = el '
                       'modelo espera más córners que la casa.')
    else:
        c2.metric('Línea de la casa', '—',
                  help='Playdoit no cotiza córners en este partido ahora mismo.')

    if ck_h is not None and ck_a is not None:
        st.markdown(f'<div style="font-size:.8rem;color:var(--tenue)">'
                    f'Reparto esperado · {_esc(home)} vs {_esc(away)}</div>',
                    unsafe_allow_html=True)
        st.markdown(barra_corners(ck_h, ck_a, home, away), unsafe_allow_html=True)

    st.info('ℹ️ ' + AVISO_NIVEL)

    # --- precios reales de la casa -----------------------------------------
    if filas:
        st.markdown(f'**Lo que paga {det.get("casa", "tu casa")}** '
                    f'· {len(filas)} mercados de córner')
        tabla = []
        for f in sorted(filas, key=lambda x: (x['familia'], x['etiqueta'])):
            prob = None
            for s in pl.get('secciones', []):
                for c in s.get('campos', []):
                    if str(c.get('etiqueta', '')).strip().lower() == \
                            f['etiqueta'].strip().lower() and c.get('tipo', 'pct') == 'pct':
                        prob = c.get('valor')
            tabla.append({
                'Mercado': f['familia'], 'Apuesta': f['etiqueta'],
                'Cuota': f['cuota'],
                'Prob. modelo': f'{prob:.1f} %' if isinstance(prob, (int, float)) else '—',
                'Cuota justa': (round(100.0 / prob, 2)
                                if isinstance(prob, (int, float)) and prob > 0 else '—'),
            })
        st.dataframe(pd.DataFrame(tabla), width='stretch', hide_index=True)
        st.caption(
            'La **cuota justa** es 1/probabilidad del modelo, sin margen. '
            'Se enseña para comparar a ojo con la cuota de la casa; **no** es '
            'una recomendación, por el desfase de nivel explicado arriba.')
    else:
        st.caption('Playdoit no publica mercados de córner de este partido '
                   'ahora mismo. Suelen abrir el mismo día.')

    # --- H2H de córners ------------------------------------------------------
    h2h = h2h_corners(clave, home, away, n=5)
    st.markdown('**Córners en los últimos enfrentamientos directos**')
    if not h2h:
        st.caption('Sin cruces directos con córners en el histórico de esta '
                   'competición. Es lo normal en ligas con muchos equipos.')
        return
    st.dataframe(pd.DataFrame([{
        'Fecha': x['fecha'],
        'Partido': f"{x['home']} vs {x['away']}",
        'Córners': f"{x['ck_home']}-{x['ck_away']}",
        'Total': x['total'],
    } for x in h2h]), width='stretch', hide_index=True)
    medias = sum(x['total'] for x in h2h) / len(h2h)
    st.caption(
        f'Media de **{medias:.1f} córners** en estos {len(h2h)} cruces, contra '
        f'los {ck_tot:.1f} que espera el modelo. Con tan pocos partidos esta '
        f'media es orientativa: sirve para ver si el cruce suele ser abierto o '
        f'trabado, no para fijar una línea.')
