#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v137 — La lista del día: barras en vez de doce columnas de porcentajes.

Qué sustituye
-------------
Una tabla con `Qué hacer · Hora · Fecha · Deporte · Liga · Techo · Partido ·
1 · X · 2 · +2.5 · −2.5 · BTTS · Mejor pronóstico`. Catorce columnas y setenta
filas: para saber quién es favorito había que comparar mentalmente tres cifras
por fila. El propio proyecto ya había resuelto ese problema en «los seis más
próximos» con una barra proporcional; esto lo lleva a la lista entera.

POR QUÉ UN SOLO BLOQUE DE HTML Y NO UNA FILA DE WIDGETS
-------------------------------------------------------
La forma evidente sería `for partido in partidos: st.columns(...)` con un
`st.button` por fila. Con 71 partidos eso son 71 botones —la vista entera
tiene hoy 69— y cada uno es un widget con estado que Streamlit mantiene, que
el smoke pulsa y que engorda cada rerun.

Aquí las 71 filas se pintan en UNA sola llamada a `st.markdown`. El coste de
render es plano: da igual que haya 20 partidos o 200. La navegación se queda
en el selector que ya existía debajo de la tabla, que hace el mismo trabajo
con un widget en vez de setenta.

EL ORDEN ES EL TIEMPO
---------------------
Estrictamente por hora de inicio, lo más próximo arriba. Es lo que pidió el
usuario y es lo correcto: lo que empieza en veinte minutos no puede estar
debajo de lo que empieza mañana.

Los partidos sin hora conocida NO se cuelan arriba con un cero: van al final,
que es donde corresponde algo cuya fecha no se sabe.
"""
import html
from typing import Dict, List, Optional

# Convención del proyecto, ya usada en `estilo_ui.barra_1x2`: verde el local,
# gris el empate, azul el visitante. No se cambia aquí porque cambiarla en un
# sitio y no en otro es peor que cualquier paleta.
_COL_LOCAL = 'var(--ok)'
_COL_EMPATE = 'var(--tenue)'
_COL_VISITA = 'var(--info)'

# El semáforo prescriptivo, con su tono. Es el mismo vocabulario que la
# columna «Qué hacer» de la tabla anterior: si dijeran cosas distintas, el
# usuario tendría dos verdades para el mismo partido.
_TONO_MARCA = {
    '✅': ('var(--ok)', 'Para jugar'),
    '🟡': ('var(--mira)', 'Sólo pata'),
    '❌': ('var(--no)', 'Sin precio'),
    '·': ('var(--tenue)', 'Informativo'),
}


def _esc(t) -> str:
    return html.escape(str(t if t is not None else ''), quote=True)


def _pct(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 1.0 else None


def barra_1x2(pl, px, pv, home: str, away: str) -> str:
    """
    La barra proporcional de un partido, o un hueco honesto si no hay modelo.

    Cuando faltan probabilidades NO se dibuja una barra a cero ni se reparte a
    tercios: se dice que no hay pronóstico. Una barra inventada es una mentira
    visual, y en esta aplicación el hueco vacío es información.
    """
    vals = [_pct(pl), _pct(px), _pct(pv)]
    if any(v is None for v in vals) or sum(v for v in vals) <= 0:
        return ('<div class="tp-barra tp-sinmodelo">'
                '<span>sin pronóstico del modelo</span></div>')
    total = sum(vals)
    anchos = [v / total * 100.0 for v in vals]
    etiquetas = (f'{home} {vals[0]*100:.0f} %', f'Empate {vals[1]*100:.0f} %',
                 f'{away} {vals[2]*100:.0f} %')
    colores = (_COL_LOCAL, _COL_EMPATE, _COL_VISITA)
    trozos = []
    for ancho, color, etq, v in zip(anchos, colores, etiquetas, vals):
        # El número sólo se escribe dentro si cabe; por debajo del 12 % el
        # texto se sale del trozo y se lee peor que sin él. El título lo
        # conserva siempre.
        dentro = f'{v*100:.0f}' if ancho >= 12 else ''
        trozos.append(
            f'<span class="tp-seg" style="width:{ancho:.2f}%;background:{color}"'
            f' title="{_esc(etq)}">{dentro}</span>')
    return f'<div class="tp-barra">{"".join(trozos)}</div>'


def _hora_de(p: Dict, horario=None) -> str:
    if horario is not None:
        try:
            partes = horario.partes(p.get('inicio'))
            if partes:
                return str(partes[1])
        except Exception:
            pass
    return str(p.get('hora_txt') or '—')


def clave_orden(p: Dict) -> tuple:
    """
    Orden estrictamente temporal. Sin hora, al final.

    Devuelve `(0, inicio)` para lo que tiene hora y `(1, '')` para lo que no,
    de modo que ningún partido sin fecha se cuele arriba por comparar contra
    una cadena vacía.
    """
    ini = str(p.get('inicio') or '')
    if not ini:
        return (1, str(p.get('fecha') or ''), '')
    return (0, ini, str(p.get('partido') or ''))


def _prob_lados(p: Dict):
    """
    `(p_local, p_visitante)` de un partido, mire donde mire el dato.

    Hay tres formas de guardarlo en el proyecto y las tres tienen que servir,
    porque conviven en la misma lista:

      · `board` con las tres salidas del 1X2 (fútbol);
      · `board` de dos vías (NFL, MLB);
      · sólo `prob` + `apuesta`, sin board (tenis, KBO), donde hay que mirar
        de qué lado habla la apuesta para saber a quién pertenece esa cifra.

    Devuelve `(None, None)` cuando no hay pronóstico. Ese caso NO se inventa:
    va a su propio bloque al final, porque colocarlo entre los locales o entre
    los visitantes sería afirmar algo que no se sabe.
    """
    home, away = lados(p.get('partido'))
    board = p.get('board') or {}
    pl = _pct(board.get(f'Gana {home}'))
    pv = _pct(board.get(f'Gana {away}'))
    if pl is not None and pv is not None:
        return pl, pv
    # sin board: la probabilidad viaja suelta y la apuesta dice de quién es
    pr = _pct(p.get('prob'))
    if pr is None:
        return None, None
    apuesta = str(p.get('apuesta') or '')
    if home and home in apuesta:
        return pr, 1.0 - pr
    if away and away in apuesta:
        return 1.0 - pr, pr
    return None, None


def clave_orden_por_favorito(p: Dict) -> tuple:
    """
    El orden que pidió el usuario: **primero los locales, de más a menos
    probable; debajo los visitantes, también de más a menos probable.**

    Textualmente: «ordena la visualización de mayor probabilidad local a la
    menor y abajo los de mayor visitante a menor».

    Ojo con lo que NO es: no es un único orden descendente por probabilidad
    local. Eso dejaría al visitante más claro del día en mitad de la lista,
    entre partidos parejos. Son DOS bloques, cada uno descendente por SU lado:

        bloque 1  local favorito     p_local 78 %, 71 %, 63 %, 55 %…
        bloque 2  visitante favorito p_visita 74 %, 66 %, 58 %…
        bloque 3  sin pronóstico del modelo

    Así los dos extremos de convicción quedan en los dos extremos de la lista,
    que es donde se buscan, y lo parejo —que es lo que menos decide— queda en
    el centro. El empate no abre bloque propio: en el 1X2 casi nunca es el
    resultado más probable, y cuando lo fuera seguiría clasificándose por cuál
    de los dos equipos va por delante.
    """
    pl, pv = _prob_lados(p)
    if pl is None or pv is None:
        return (2, 0.0, str(p.get('inicio') or ''))
    if pl >= pv:
        return (0, -pl, str(p.get('inicio') or ''))
    return (1, -pv, str(p.get('inicio') or ''))


def lados(partido: str):
    """
    `(local, visitante)` del nombre del partido, sea cual sea el separador.

    v139 — ESTO ESTABA MAL Y SE VEÍA EN PANTALLA.
    ---------------------------------------------
    El fútbol escribe «Local vs Visitante» y la MLB y la KBO escriben
    «Visitante @ Local»: no sólo cambia el separador, cambia el ORDEN. Partir
    siempre por « vs » dejaba `home` con la cadena entera, así que se buscaba
    `Gana Chicago White Sox @ Detroit Tigers` en un board que tenía
    `Gana Detroit Tigers`. Resultado: los 11 partidos de MLB salían con «sin
    pronóstico del modelo» teniendo el pronóstico delante.
    """
    t = str(partido or '')
    if ' @ ' in t:
        visita, local = t.split(' @ ', 1)
        return local.strip(), visita.strip()
    partes = t.split(' vs ')
    return partes[0].strip(), (partes[-1].strip() if len(partes) > 1 else '')


def barra_dos_vias(prob, etiqueta: str) -> str:
    """
    Barra de dos tramos para los deportes SIN empate y sin board.

    El tenis y la KBO no publican `board`, pero sí traen la probabilidad del
    lado elegido. Con dos resultados posibles, eso basta para pintar la
    proporción — y es mejor que un hueco, porque el hueco aquí no significa
    «no se sabe» sino «no lo guardamos con ese formato».
    """
    v = _pct(prob)
    if v is None:
        return ('<div class="tp-barra tp-sinmodelo">'
                '<span>sin pronóstico del modelo</span></div>')
    resto = 1.0 - v
    # El número sólo se escribe si el tramo da de sí; por debajo del 12 % se
    # sale y se lee peor que sin él. El título lo conserva siempre.
    txt_v = f'{v*100:.0f}' if v >= 0.12 else ''
    txt_r = f'{resto*100:.0f}' if resto >= 0.12 else ''
    return (
        f'<div class="tp-barra">'
        f'<span class="tp-seg" style="width:{v*100:.2f}%;background:{_COL_LOCAL}"'
        f' title="{_esc(etiqueta)} {v*100:.0f} %">{txt_v}</span>'
        f'<span class="tp-seg" style="width:{resto*100:.2f}%;'
        f'background:{_COL_VISITA}" title="el otro lado {resto*100:.0f} %">'
        f'{txt_r}</span></div>')


def fila(p: Dict, marca: str, horario=None) -> str:
    """Una fila: hora, liga, partido, barra y semáforo."""
    home, away = lados(p.get('partido'))
    board = p.get('board') or {}
    icono = str(marca or '·').strip().split()[0] if marca else '·'
    color_marca, _ = _TONO_MARCA.get(icono, ('var(--tenue)', ''))
    return (
        f'<div class="tp-fila">'
        f'<div class="tp-hora">{_esc(_hora_de(p, horario))}</div>'
        f'<div class="tp-meta">'
        f'<div class="tp-eq">{_esc(home)} <i>vs</i> {_esc(away)}</div>'
        f'<div class="tp-liga">{_esc(p.get("deporte", ""))} · '
        f'{_esc(p.get("liga", ""))}</div></div>'
        f'<div class="tp-graf">'
        + (barra_1x2(board.get(f'Gana {home}'), board.get('Empate'),
                     board.get(f'Gana {away}'), home, away)
           if board.get('Empate') is not None
           # sin empate en el board —MLB con dos vías, o tenis y KBO sin board
           # ninguno— se pinta con la probabilidad del lado elegido, que sí
           # viene siempre. Ver `barra_dos_vias`.
           else barra_dos_vias(
               board.get(f'Gana {home}') if board.get(f'Gana {home}') is not None
               else p.get('prob'),
               p.get('apuesta') or home))
        + f'</div>'
        f'<div class="tp-marca" style="color:{color_marca};'
        f'border-color:{color_marca}">{_esc(marca or "·")}</div>'
        f'</div>')


CSS = """
<style>
.tp-lista { display: flex; flex-direction: column; gap: .3rem; margin: .4rem 0; }
.tp-fila { display: grid; grid-template-columns: 3.6rem minmax(9rem,1.4fr) 2fr 7.5rem;
           gap: .6rem; align-items: center; padding: .45rem .6rem;
           border: 1px solid var(--borde); border-radius: 10px;
           background: var(--panel); }
.tp-hora { font-weight: 700; font-size: .82rem; }
.tp-eq   { font-size: .86rem; line-height: 1.2; }
.tp-eq i { color: var(--tenue); font-style: normal; font-size: .76rem; }
.tp-liga { font-size: .7rem; color: var(--tenue); margin-top: .1rem; }
.tp-barra { display: flex; height: 16px; border-radius: 8px; overflow: hidden;
            background: var(--panel2); }
.tp-seg  { display: flex; align-items: center; justify-content: center;
           font-size: .64rem; font-weight: 700; color: #0d1117; }
.tp-sinmodelo { align-items: center; justify-content: center;
                font-size: .7rem; color: var(--tenue); }
.tp-marca { font-size: .74rem; font-weight: 600; text-align: center;
            border: 1px solid; border-radius: 999px; padding: .12rem .3rem;
            white-space: nowrap; }
@media (max-width: 768px) {
  /* En móvil la fila se parte en dos alturas: arriba hora, equipos y marca;
     abajo la barra a todo el ancho, que es donde de verdad se lee. */
  .tp-fila { grid-template-columns: 3.2rem 1fr auto; row-gap: .35rem; }
  .tp-graf { grid-column: 1 / -1; }
  .tp-marca { font-size: .68rem; }
}
</style>
"""


def pintar_con_boton(st, partidos: List[Dict], marca_de, horario=None,
                     navegar=None, clave: str = 'lista',
                     maximo: int = 250, orden=None) -> None:
    """
    La lista con un botón «Ver» por tarjeta.

    v142 — SE MIDIÓ ANTES DE DECIDIR, Y LA MEDIDA CORRIGIÓ LA SUPOSICIÓN.
    --------------------------------------------------------------------
    La versión anterior pintaba las filas en un solo bloque de HTML para
    evitar «setenta widgets», dando por hecho que serían caros. Medido en
    AppTest, con calentamiento y mejor de tres:

        201 filas en un bloque HTML .... 0,404 s
        201 tarjetas con st.button ..... 0,616 s   (1,53x)

    Doscientos botones cuestan **dos décimas de segundo**. Eso no justifica
    negar la navegación directa que se pedía, ni la complejidad de paginar.
    La suposición era mía y el dato la desmintió.

    `navegar(pick)` se llama al pulsar; si no se pasa, el botón no se dibuja y
    la lista se comporta como antes.
    """
    if not partidos:
        return
    st.markdown(CSS, unsafe_allow_html=True)
    # v144 — por defecto se ordena por FAVORITO, no por hora. Ver
    # `clave_orden_por_favorito`: el usuario pidió los locales de mayor a menor
    # probabilidad y debajo los visitantes igual. Pasar `orden=clave_orden`
    # recupera el orden temporal para quien lo prefiera.
    for i, p in enumerate(
            sorted(partidos, key=orden or clave_orden_por_favorito)[:maximo]):
        try:
            m = marca_de(p)
        except Exception:
            m = '·'
        if navegar is None:
            st.markdown(fila(p, m, horario), unsafe_allow_html=True)
            continue
        c1, c2 = st.columns([11, 1.6])
        c1.markdown(fila(p, m, horario), unsafe_allow_html=True)
        # La clave lleva el índice y el partido: dos encuentros del mismo
        # cruce en días distintos comparten nombre, y Streamlit exige claves
        # únicas o lanza «multiple elements with the same key».
        if c2.button('Ver', key=f'{clave}_ver_{i}',
                     help='Abre la ficha completa de este partido'):
            navegar(p)


def lista(partidos: List[Dict], marca_de, horario=None,
          maximo: int = 250, orden=None) -> str:
    """
    Las filas de todos los partidos, ordenadas por hora, en un solo bloque.

    `marca_de` es la función que devuelve el semáforo de un partido — se
    inyecta en vez de recalcularla aquí para que la lista y la ficha digan
    exactamente lo mismo, que es de donde salen las contradicciones.
    """
    if not partidos:
        return ''
    ordenados = sorted(partidos, key=orden or clave_orden_por_favorito)[:maximo]
    filas = []
    for p in ordenados:
        try:
            m = marca_de(p)
        except Exception:
            m = '·'
        filas.append(fila(p, m, horario))
    return CSS + '<div class="tp-lista">' + ''.join(filas) + '</div>'
