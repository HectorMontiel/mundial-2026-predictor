# -*- coding: utf-8 -*-
"""
v393 — LAS FECHAS QUE ESPN SÍ ACEPTA, EN UN SOLO SITIO.

ESPN dejó de aceptar los rangos con guion (`dates=20261001-20261017`) en el
scoreboard de fútbol, NFL, NBA y MLB: responde HTTP 400 o, en algunas
rutas, 200 con CERO eventos, sin más aviso (medido el 17-oct; sólo el tenis
los sigue aceptando). Ya había salido en `fixtures_espn` (v252) y en
`stats_espn`, y cada vez se arregló SÓLO ese módulo; quedaban siete más
(`uefa_scraper`, `nfl_datos`, `leagues_cup`, `lineup_impact`,
`remates_jugadores`, `live_worldcup`, `generar_ligas_v68`) pidiendo rangos
que ya no existen. El de `uefa_scraper` dejaba a TODAS las ligas sin los
partidos recientes (la Liga MX llegaba al 12-oct el día 17).

Lo que ESPN sí acepta: un día (`AAAAMMDD`), un mes (`AAAAMM`) o un año
(`AAAA`). `consultas` parte cualquier rango en esas piezas y `eventos`
devuelve sólo los del rango pedido, sin repetir.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pandas as pd

UA = {'User-Agent': 'Mozilla/5.0'}


def consultas(ini, fin) -> List[str]:
    """Los valores de `dates` que cubren [ini, fin]: días sueltos si son
    pocos (≤ 7), meses enteros si no."""
    a = pd.Timestamp(str(ini)).normalize()
    b = pd.Timestamp(str(fin)).normalize()
    if b < a:
        a, b = b, a
    if (b - a).days < 7:
        return [d.strftime('%Y%m%d') for d in pd.date_range(a, b, freq='D')]
    meses = pd.period_range(a.to_period('M'), b.to_period('M'), freq='M')
    return [m.strftime('%Y%m') for m in meses]


def dentro(ev: Dict, ini, fin) -> bool:
    """¿El evento cae en [ini, fin] (por día, en UTC)? Sin fecha: sí."""
    f = pd.to_datetime((ev or {}).get('date'), errors='coerce', utc=True)
    if pd.isna(f):
        return True
    d = f.tz_convert(None).normalize()
    return pd.Timestamp(str(ini)).normalize() <= d <= pd.Timestamp(str(fin)).normalize()


def _requests(url: str, params: Dict, timeout: float = 30) -> Optional[Dict]:
    import requests
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def eventos(url: str, ini, fin, params: Optional[Dict] = None,
            obtener: Optional[Callable] = None, timeout: float = 30) -> List[Dict]:
    """Los eventos del scoreboard `url` entre `ini` y `fin`, ambos incluidos.
    `obtener(url, params)` devuelve el JSON (por defecto, `requests`). Un
    trozo que falla no tumba los demás."""
    fuera, vistos = [], set()
    for q in consultas(ini, fin):
        p = dict(params or {}, dates=q)
        try:
            j = obtener(url, p) if obtener else _requests(url, p, timeout)
        except Exception:
            j = None
        for ev in (j or {}).get('events') or []:
            k = ev.get('id')
            if k in vistos or not dentro(ev, ini, fin):
                continue
            vistos.add(k)
            fuera.append(ev)
    return fuera
