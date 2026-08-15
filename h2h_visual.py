#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v135 — La forma de un equipo, en imagen y no en un churro de letras.

Qué sustituye
-------------
La ficha decía cosas como:

    🏠 Club Tijuana — últimos 8: PPEGGEGE · 1.5 pts/partido

Para saber si el equipo llega bien había que leer ocho letras de izquierda a
derecha y acordarse de cuál era la más reciente. Nadie hace eso: se mira, se
encoge de hombros y se pasa.

Qué se dibuja, y con qué
------------------------
SVG en línea, sin ninguna librería. No entra Plotly (~3 MB de JS por página
para pintar cinco cuadros) ni Altair (su tema no casa con el propio y en móvil
deja demasiado aire). Los colores salen de las variables que ya define
`estilo_ui` —`--ok`, `--mira`, `--no`— así que esto respeta el tema oscuro sin
repetir un solo valor hexadecimal, y si mañana cambia la paleta cambia sola.

Todo sale de `panel_equipos.forma_global`, que ya se llamaba en la ficha:
`racha`, `gf_media`, `gc_media`, el desglose G/E/P y, por partido, `stats` con
Córners, Amarillas, Tiros a puerta, Posesión y xG.

EL COLOR NUNCA VA SOLO
----------------------
Cada cuadro lleva su letra (G/E/P) dentro. Un daltónico no distingue el verde
del ámbar, y en un móvil a pleno sol no lo distingue nadie. Es la misma regla
que el semáforo de la tabla del día.
"""
import html
from typing import Dict, List, Optional

# Los tres estados y su variable de color. Se usan las mismas que el resto de
# la aplicación: verde «va bien», ámbar «ni una cosa ni otra», rojo «va mal».
_TONO = {'G': ('var(--ok)', 'Ganó'), 'E': ('var(--mira)', 'Empató'),
         'P': ('var(--no)', 'Perdió')}


def _esc(t) -> str:
    return html.escape(str(t if t is not None else ''), quote=True)


def _desglose(partidos: List[Dict], n: int = 5):
    """Ganados/empatados/perdidos EN LOS `n` QUE SE DIBUJAN."""
    g = e = p = 0
    for x in (partidos or [])[:n]:
        r = str(x.get('resultado') or '').upper()[:1]
        if r == 'G':
            g += 1
        elif r == 'E':
            e += 1
        elif r == 'P':
            p += 1
    return g, e, p


def _media_goles(partidos: List[Dict], n: int = 5):
    """Goles a favor y en contra por partido EN LOS `n` QUE SE DIBUJAN."""
    gf = gc = 0.0
    vistos = 0
    for x in (partidos or [])[:n]:
        try:
            gf += float(x.get('goles'))
            gc += float(x.get('encajados'))
            vistos += 1
        except (TypeError, ValueError):
            continue
    if not vistos:
        return None, None
    return round(gf / vistos, 2), round(gc / vistos, 2)


def racha(partidos: List[Dict], n: int = 5) -> str:
    """
    Los últimos `n` resultados como cuadros de color, el más reciente a la
    DERECHA.

    `forma_global` los entrega del más nuevo al más viejo, así que se invierten:
    una línea de tiempo que avanza hacia la izquierda no la lee nadie.

    Cada cuadro lleva el marcador y el rival en el `title`, que es lo que sale
    al pasar por encima — la información no se pierde, se esconde hasta que se
    pide.
    """
    if not partidos:
        return ''
    ult = list(partidos[:n])[::-1]
    ancho, alto, hueco = 30, 30, 6
    total = len(ult) * (ancho + hueco) - hueco
    piezas = []
    for i, p in enumerate(ult):
        letra = str(p.get('resultado') or '·')[:1].upper()
        color, verbo = _TONO.get(letra, ('var(--tenue)', ''))
        x = i * (ancho + hueco)
        rival = _esc(p.get('rival'))
        marcador = f"{p.get('goles', '?')}-{p.get('encajados', '?')}"
        donde = 'en casa' if p.get('casa') else 'fuera'
        titulo = _esc(f"{verbo} {marcador} {donde} contra {rival} "
                      f"({p.get('fecha', '')})")
        piezas.append(
            f'<g><title>{titulo}</title>'
            f'<rect x="{x}" y="0" width="{ancho}" height="{alto}" rx="7" '
            f'fill="{color}" fill-opacity=".22" stroke="{color}" '
            f'stroke-width="1.5"/>'
            f'<text x="{x + ancho / 2}" y="{alto / 2 + 5}" text-anchor="middle" '
            f'font-size="14" font-weight="700" fill="{color}">{letra}</text>'
            f'</g>')
    return (f'<svg viewBox="0 0 {total} {alto}" width="100%" '
            f'style="max-width:{total}px;height:auto;display:block" '
            f'role="img" aria-label="Últimos resultados, el más reciente a la '
            f'derecha">{"".join(piezas)}</svg>')


def _barra(valor: float, maximo: float, color: str, etiqueta: str) -> str:
    """Una barra horizontal con su cifra dentro. Sin ejes: no hacen falta."""
    ancho = 200
    largo = max(2.0, min(float(valor) / max(float(maximo), 0.01), 1.0) * ancho)
    return (
        f'<div style="display:flex;align-items:center;gap:.5rem;margin:.18rem 0">'
        f'<span style="font-size:.72rem;color:var(--tenue);min-width:8.5ch">'
        f'{_esc(etiqueta)}</span>'
        f'<svg viewBox="0 0 {ancho} 14" width="{ancho}" height="14" '
        f'preserveAspectRatio="none" style="max-width:100%;flex:1">'
        f'<rect x="0" y="3" width="{ancho}" height="8" rx="4" '
        f'fill="var(--panel2)"/>'
        f'<rect x="0" y="3" width="{largo:.1f}" height="8" rx="4" '
        f'fill="{color}"/></svg>'
        f'<b style="font-size:.8rem;min-width:3.2ch;text-align:right">'
        f'{valor:.1f}</b></div>')


def _media_stat(partidos: List[Dict], clave: str, n: int = 5) -> Optional[float]:
    """Media propia de una estadística en los últimos `n` partidos, si la hay."""
    vals = []
    for p in (partidos or [])[:n]:
        v = ((p.get('stats') or {}).get(clave) or {}).get('propio')
        try:
            if v is not None:
                vals.append(float(v))
        except (TypeError, ValueError):
            continue
    return round(sum(vals) / len(vals), 2) if vals else None


# Las barras que se dibujan bajo la racha, por deporte. Iban incrustadas en
# `tarjeta_equipo` con los nombres del fútbol («Córners», «Amarillas», «Tiros a
# puerta»), lo que servía mientras todos los deportes de la ficha fueran fútbol.
#
# v131 — con la NFL dentro ya no lo son, y una tarjeta de fútbol americano
# titulada «Goles a favor» no es un detalle cosmético: es una etiqueta que
# miente sobre lo que hay debajo. Se declara por deporte; el fútbol conserva
# exactamente las suyas, así que su ficha no cambia ni un píxel.
PERFILES = {
    'futbol': {
        'favor': 'Goles a favor', 'contra': 'Goles en contra',
        'stats': (('Córners', 'Córners', 'var(--info)'),
                  ('Amarillas', 'Tarjetas', 'var(--mira)'),
                  ('Tiros a puerta', 'Tiros a puerta', 'var(--tenue)')),
    },
    'nfl': {
        'favor': 'Puntos a favor', 'contra': 'Puntos en contra',
        # Yardas y yardas por jugada son las dos magnitudes que mejor separan
        # a un ataque de otro, y las pérdidas de balón lo que más pesa en el
        # resultado — las tres salen del boxscore de ESPN sin fuente nueva.
        'stats': (('Yardas', 'Yardas', 'var(--info)'),
                  ('Yardas por jugada', 'Yardas/jugada', 'var(--tenue)'),
                  ('Pérdidas', 'Pérdidas', 'var(--mira)')),
    },
}


def tarjeta_equipo(nombre: str, forma: Dict, icono: str = '',
                   n: int = 5, deporte: str = 'futbol') -> str:
    """
    La ficha de un equipo: racha, desglose y las medias que de verdad hay.

    Las estadísticas que no existen NO se pintan a cero: se omiten. Una barra a
    cero dice «este equipo no hace córners», y lo que pasa es que no tenemos el
    dato — que es una cosa muy distinta y es justo el tipo de mentira visual
    que este proyecto evita en el resto de la interfaz.
    """
    perfil = PERFILES.get(deporte, PERFILES['futbol'])
    if not forma or not forma.get('n'):
        return (f'<div class="h2hcard"><b>{_esc(icono)} {_esc(nombre)}</b>'
                f'<div style="color:var(--tenue);font-size:.8rem;'
                f'margin-top:.3rem">Sin partidos recientes registrados.</div>'
                f'</div>')
    partidos = forma.get('partidos') or []
    # EL DESGLOSE SE CUENTA SOBRE LO QUE SE DIBUJA, NO SOBRE TODO.
    #
    # `forma_global` agrega los 8 últimos y la tira enseña 5. Tomar `ganados`
    # tal cual producía «últimos 5: 5V-0E-3D» —ocho resultados con etiqueta de
    # cinco—, que es una cifra que no cuadra con los cuadros de al lado. Lo
    # cazó la primera prueba del módulo.
    g, e, p_ = _desglose(partidos, n)
    # Las medias de gol, por lo mismo: `gf_media` agrega los 8 y aquí se
    # dibujan 5. Se recalculan sobre la misma ventana; si los partidos no
    # traen goles, se cae a la media global antes que quedarse sin barra.
    gf, gc = _media_goles(partidos, n)
    if gf is None or gc is None:
        gf, gc = forma.get('gf_media'), forma.get('gc_media')
    filas = []
    if gf is not None and gc is not None:
        tope = max(float(gf), float(gc), 1.0)
        filas.append(_barra(float(gf), tope, 'var(--ok)', perfil['favor']))
        filas.append(_barra(float(gc), tope, 'var(--no)', perfil['contra']))
    for clave, etq, color in perfil['stats']:
        v = _media_stat(partidos, clave, n)
        if v is not None:
            # EL TOPE DE LA BARRA SALE DEL PROPIO VALOR, NO DE UNA CONSTANTE.
            #
            # El 6.0 fijo venía de los córners y sirve mientras las magnitudes
            # sean de un dígito. Con yardas de NFL (350-450 por partido) la
            # barra saldría siempre llena y no distinguiría nada. Se redondea
            # hacia arriba al orden de magnitud del valor.
            import math as _m
            escala = 10 ** max(0, int(_m.floor(_m.log10(max(abs(v), 1e-9)))))
            filas.append(_barra(v, max(v, min(6.0, escala) if escala <= 10
                                       else escala * 1.5), color, etq))
    return (
        f'<div class="h2hcard">'
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:baseline;gap:.5rem">'
        f'<b>{_esc(icono)} {_esc(nombre)}</b>'
        f'<span style="font-size:.75rem;color:var(--tenue)">'
        f'{g}V · {e}E · {p_}D</span></div>'
        f'<div style="margin:.45rem 0 .55rem">{racha(partidos, n)}</div>'
        f'{"".join(filas)}'
        f'<div style="font-size:.72rem;color:var(--tenue);margin-top:.4rem">'
        f'Últimos {min(len(partidos), n)} partidos'
        + (f' · {forma.get("pts_por_partido")} pts por partido'
           if forma.get('pts_por_partido') is not None else '')
        + '</div></div>')


CSS = """
<style>
.h2hwrap { display: grid; grid-template-columns: 1fr 1fr; gap: .7rem;
           margin: .3rem 0 .6rem; }
.h2hcard { border: 1px solid var(--borde); border-radius: 12px;
           padding: .7rem .8rem; background: var(--panel); }
@media (max-width: 768px) { .h2hwrap { grid-template-columns: 1fr; } }
</style>
"""


def bloque(home: str, away: str, forma_home: Dict, forma_away: Dict,
           n: int = 5, deporte: str = 'futbol') -> str:
    """Las dos fichas enfrentadas. En móvil se apilan (ver el CSS)."""
    return (CSS + '<div class="h2hwrap">'
            + tarjeta_equipo(home, forma_home, '🏠', n, deporte)
            + tarjeta_equipo(away, forma_away, '✈️', n, deporte)
            + '</div>')


def resumen_texto(nombre: str, forma: Dict, n: int = 5) -> str:
    """
    La misma información en una línea, para quien prefiera leerla.

    El gráfico no sustituye al texto: lo acompaña. Un lector de pantalla no ve
    los cuadros de colores, y un resumen de una línea es lo que se copia y se
    pega en un mensaje.
    """
    if not forma or not forma.get('n'):
        return f'{nombre}: sin partidos recientes.'
    partidos = forma.get('partidos') or []
    g, e, p_ = _desglose(partidos, n)
    txt = f"**{nombre}** · últimos {min(len(partidos), n)}: {g}V-{e}E-{p_}D"
    _gf, _gc = _media_goles(partidos, n)
    if _gf is None:
        _gf, _gc = forma.get('gf_media'), forma.get('gc_media')
    if _gf is not None:
        txt += f" · {_gf} goles a favor"
    if _gc is not None:
        txt += f" y {_gc} en contra por partido"
    return txt
