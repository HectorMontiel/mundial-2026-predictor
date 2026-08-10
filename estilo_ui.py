#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v117 — La capa visual de la aplicación.

Por qué existe
--------------
La app tiene cinco años de funciones amontonadas y ninguna gramática visual:
todo con el tema por defecto de Streamlit, todo del mismo tamaño y del mismo
color, y la jerarquía la marcaba el orden en que estaban escritas las cosas. El
usuario lo dijo tres veces: «modernizar, que no sea tan plano, más diseño,
efectos, deslizantes, intuitiva».

Qué hace y qué NO hace
----------------------
Esto es SÓLO presentación: inyecta CSS y ofrece unos cuantos componentes. No
toca ni un número, ni un filtro, ni una probabilidad. Si este módulo falla
entero, la aplicación sigue funcionando exactamente igual — sólo se ve como
antes. Por eso todo lo que hay aquí está envuelto en `try`.

Las tres decisiones que lo gobiernan
------------------------------------
1. **El color significa una acción, no un adorno.** Verde = puedes actuar
   (precio real, EV positivo comprobable); ámbar = mira antes de decidir;
   gris = informativo. Si el color no distingue nada, no se usa.
2. **Funciona en claro y en oscuro.** Se usan las variables de tema de
   Streamlit y `color-mix`, no colores fijos: un panel que se ve bien en claro
   y es ilegible en oscuro es peor que uno plano.
3. **La animación sirve para orientar, no para lucirse.** Transiciones de 150
   ms al pasar por encima y entradas suaves; nada que se mueva solo mientras se
   lee, y todo desactivado si el sistema pide movimiento reducido.
"""
import logging

logger = logging.getLogger(__name__)

# Paleta. Los tonos se derivan del color de acento del tema con `color-mix`,
# así que respetan el claro/oscuro del usuario en vez de imponer los nuestros.
CSS = """
<style>
:root {
  --ok:    #16a34a;   /* accionable  */
  --mira:  #d97706;   /* con reparos */
  --no:    #dc2626;   /* descartado  */
  --sutil: color-mix(in srgb, currentColor 12%, transparent);
  --panel: color-mix(in srgb, currentColor 4%, transparent);
  --borde: color-mix(in srgb, currentColor 14%, transparent);
  --radio: 14px;
}

/* ---- respiración general ------------------------------------------- */
.block-container { padding-top: 2.2rem; max-width: 1250px; }

/* ---- tarjetas (st.container(border=True)) --------------------------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: var(--radio) !important;
  border-color: var(--borde) !important;
  transition: transform .15s ease, box-shadow .15s ease,
              border-color .15s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px color-mix(in srgb, currentColor 10%, transparent);
  border-color: color-mix(in srgb, var(--ok) 35%, var(--borde)) !important;
}

/* ---- métricas: la cifra manda --------------------------------------- */
div[data-testid="stMetric"] {
  background: var(--panel);
  border: 1px solid var(--borde);
  border-radius: var(--radio);
  padding: .7rem .9rem;
  transition: border-color .15s ease, background .15s ease;
}
div[data-testid="stMetric"]:hover {
  border-color: color-mix(in srgb, var(--ok) 40%, var(--borde));
}
div[data-testid="stMetricValue"] {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  letter-spacing: -.02em;
}
div[data-testid="stMetricLabel"] { opacity: .75; font-size: .82rem; }

/* ---- pestañas: que se vea cuál está activa -------------------------- */
button[data-baseweb="tab"] {
  font-weight: 600;
  border-radius: 10px 10px 0 0;
  transition: background .15s ease, color .15s ease;
}
button[data-baseweb="tab"]:hover { background: var(--sutil); }

/* ---- botones: jerarquía real ---------------------------------------- */
.stButton > button {
  border-radius: 10px;
  font-weight: 600;
  transition: transform .12s ease, box-shadow .15s ease, filter .15s ease;
}
.stButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px color-mix(in srgb, currentColor 14%, transparent);
}
.stButton > button:active { transform: translateY(0); }

/* ---- desplegables: que parezcan pulsables --------------------------- */
details summary, div[data-testid="stExpander"] summary {
  border-radius: 10px;
  transition: background .15s ease;
}
details summary:hover { background: var(--sutil); }

/* ---- selectores y campos -------------------------------------------- */
div[data-baseweb="select"] > div,
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
  border-radius: 10px !important;
  transition: border-color .15s ease, box-shadow .15s ease;
}
div[data-baseweb="select"] > div:hover {
  border-color: color-mix(in srgb, var(--ok) 45%, var(--borde)) !important;
}

/* ---- tablas: números alineados y cabecera fija ---------------------- */
div[data-testid="stDataFrame"] { border-radius: var(--radio); overflow: hidden; }
div[data-testid="stDataFrame"] td { font-variant-numeric: tabular-nums; }

/* ---- avisos: menos grito, más información --------------------------- */
div[data-testid="stAlert"] { border-radius: var(--radio); border-width: 0 0 0 4px; }

/* ---- píldoras de estado (las usa `pildora`) ------------------------- */
.pild {
  display: inline-block; padding: .16rem .6rem; border-radius: 999px;
  font-size: .78rem; font-weight: 700; letter-spacing: .01em;
  border: 1px solid transparent; white-space: nowrap;
}
.pild-ok   { color: var(--ok);   background: color-mix(in srgb, var(--ok) 12%, transparent);
             border-color: color-mix(in srgb, var(--ok) 30%, transparent); }
.pild-mira { color: var(--mira); background: color-mix(in srgb, var(--mira) 12%, transparent);
             border-color: color-mix(in srgb, var(--mira) 30%, transparent); }
.pild-no   { color: var(--no);   background: color-mix(in srgb, var(--no) 12%, transparent);
             border-color: color-mix(in srgb, var(--no) 30%, transparent); }
.pild-info { opacity: .8; background: var(--sutil); border-color: var(--borde); }

/* ---- barra de probabilidad ------------------------------------------ */
.barra { height: 8px; border-radius: 999px; background: var(--sutil);
         overflow: hidden; margin: .35rem 0; }
.barra > i { display: block; height: 100%; border-radius: 999px;
             background: linear-gradient(90deg,
               color-mix(in srgb, var(--ok) 55%, transparent), var(--ok));
             animation: crece .5s ease-out; }
@keyframes crece { from { width: 0 } }

/* ---- entrada suave de las secciones --------------------------------- */
.block-container > div { animation: aparece .28s ease-out both; }
@keyframes aparece { from { opacity: 0; transform: translateY(4px) } }

/* ---- móvil: las tablas anchas no rompen la página ------------------- */
@media (max-width: 768px) {
  .block-container { padding-left: .7rem; padding-right: .7rem; }
  div[data-testid="stDataFrame"] { overflow-x: auto; }
  div[data-testid="stMetricValue"] { font-size: 1.35rem; }
}

/* ---- quien pide menos movimiento, no lo recibe ---------------------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
"""


def aplicar(st) -> None:
    """Inyecta los estilos. Un fallo aquí no puede costar la aplicación."""
    try:
        st.markdown(CSS, unsafe_allow_html=True)
    except Exception as e:
        logger.debug(f'[estilo] no aplicado: {type(e).__name__}: {e}')


def pildora(texto: str, tono: str = 'info') -> str:
    """
    Etiqueta corta de estado, en HTML, para meter dentro de un `st.markdown`.

    `tono` es 'ok' (accionable), 'mira' (con reparos), 'no' (descartado) o
    'info'. El color va con el SIGNIFICADO, no con el gusto: si una píldora no
    distingue una decisión de otra, sobra.
    """
    t = tono if tono in ('ok', 'mira', 'no', 'info') else 'info'
    return f'<span class="pild pild-{t}">{texto}</span>'


def barra(prob: float) -> str:
    """Barra de probabilidad, para ver de un vistazo lo que un % no transmite."""
    try:
        p = max(0.0, min(1.0, float(prob)))
    except (TypeError, ValueError):
        return ''
    return f'<div class="barra"><i style="width:{p*100:.0f}%"></i></div>'


def tono_por_ev(ev, n_casas: int = 1, sospechoso: bool = False) -> str:
    """
    Qué color merece un mercado.

    Sigue el criterio medido del proyecto, no la intuición: un EV alto de UNA
    sola casa no es una oportunidad —es el modelo equivocándose contra un
    mercado líquido— así que no se pinta de verde. Lo que se premia es tener
    varias casas comparadas, que es la única ventaja con ROI positivo medido.
    """
    if sospechoso:
        return 'mira'
    try:
        v = float(ev)
    except (TypeError, ValueError):
        return 'info'
    if v > 0 and n_casas >= 2:
        return 'ok'
    if v > 0:
        return 'info'
    return 'no'
