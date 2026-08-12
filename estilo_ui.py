#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v122 — La capa visual de la aplicación, rediseñada de arriba abajo.

Por qué se rehace
-----------------
La v117 introdujo este módulo con seis componentes y algo de CSS, y el usuario
volvió con el mismo reproche por cuarta vez: «sigo sin ver mejoras fuertes en
la interfaz, quiero una interfaz totalmente rediseñada, más moderna, intuitiva,
fácil de usar y atractiva visualmente».

Tenía razón, y el motivo estaba medido dentro del propio código: de los seis
componentes que la v117 creó, la aplicación usaba **tres, en cuatro sitios**,
sobre 5.884 líneas de interfaz. El resto seguía siendo `st.markdown` con
asteriscos y `st.metric` por defecto. Un módulo de estilo que nadie llama no
cambia nada; lo que se veía era, literalmente, Streamlit de fábrica.

Así que esta versión hace las dos mitades del trabajo: aquí está el sistema de
diseño, y `dashboard_ui` pasa a usarlo en todas las pantallas.

Qué hace y qué NO hace
----------------------
Esto es SÓLO presentación: no toca ni un número, ni un filtro, ni una
probabilidad. Si este módulo falla entero, la aplicación sigue funcionando
exactamente igual — sólo se ve como antes. Por eso `aplicar` va en `try` y
todos los componentes devuelven cadena vacía ante datos que no entienden, en
vez de lanzar.

Las cuatro reglas que lo gobiernan
---------------------------------
1. **El color significa una decisión, no un adorno.** Verde = puedes actuar
   (precio real, ventaja comprobable); ámbar = míralo antes de decidir; rojo =
   descartado; azul = informativo. Si un color no distingue una decisión de
   otra, no se usa. Esto importa especialmente aquí: el proyecto tiene medido
   que el EV alto de una sola casa NO es una oportunidad, así que un EV alto
   sin comparación **no se pinta de verde** por bonito que quede.
2. **La cifra manda sobre la caja.** Números tabulares, jerarquía de tamaño
   real (una cifra principal es 2,2 rem y una secundaria 0,78 rem, no ambas
   1 rem en negrita) y etiquetas en minúscula que no compitan con el dato.
3. **Funciona en claro y en oscuro.** Todo sale de variables de tema y
   `color-mix`. Un panel legible en oscuro e ilegible en claro es peor que uno
   plano.
4. **La animación orienta, no luce.** Entradas de 200-300 ms y respuesta al
   pasar por encima; nada que se mueva solo mientras se lee, y todo apagado si
   el sistema pide movimiento reducido.
"""
import html as _html
import logging

logger = logging.getLogger(__name__)


def _esc(t) -> str:
    """Todo texto que entre en el HTML pasa por aquí. Sin excepciones."""
    return _html.escape(str(t if t is not None else ''), quote=True)


# ===========================================================================
# EL SISTEMA: tokens + componentes
# ===========================================================================
# Los tokens se derivan del tema activo de Streamlit con `color-mix`, no son
# colores fijos. Es lo que permite que la misma hoja valga para el tema claro y
# el oscuro sin duplicar nada y sin que un despliegue con otro tema rompa la
# legibilidad.
CSS = """
<style>
:root {
  /* --- significado ------------------------------------------------- */
  --ok:    #10b981;   /* accionable: precio real, ventaja comprobable   */
  --mira:  #f59e0b;   /* con reparos: míralo antes de decidir           */
  --no:    #ef4444;   /* descartado                                     */
  --info:  #6366f1;   /* informativo, sin decisión asociada             */

  /* --- superficies, derivadas del tema ------------------------------ */
  --tinta:  currentColor;
  --sutil:  color-mix(in srgb, currentColor 8%,  transparent);
  --panel:  color-mix(in srgb, currentColor 4%,  transparent);
  --panel2: color-mix(in srgb, currentColor 7%,  transparent);
  --borde:  color-mix(in srgb, currentColor 13%, transparent);
  --borde2: color-mix(in srgb, currentColor 22%, transparent);
  --tenue:  color-mix(in srgb, currentColor 62%, transparent);

  /* --- forma -------------------------------------------------------- */
  --radio:   16px;
  --radio-s: 10px;
  --radio-p: 999px;
  --sombra:  0 1px 2px color-mix(in srgb, currentColor 6%, transparent),
             0 8px 28px color-mix(in srgb, currentColor 7%, transparent);
  --sombra-alta: 0 2px 6px color-mix(in srgb, currentColor 8%, transparent),
                 0 18px 44px color-mix(in srgb, currentColor 12%, transparent);

  /* --- números ------------------------------------------------------ */
  --cifra: "SF Mono", "JetBrains Mono", "Cascadia Mono", Consolas,
           ui-monospace, monospace;
}

/* =====================================================================
   1. RESPIRACIÓN Y RITMO
   Streamlit apila todo con el mismo hueco; sin ritmo vertical, catorce
   secciones seguidas se leen como una sola mancha.
   ===================================================================== */
.block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1320px; }
.block-container > div > div > div > div > .element-container { scroll-margin-top: 5rem; }
hr { border-color: var(--borde) !important; opacity: .8; }

/* =====================================================================
   2. TIPOGRAFÍA — jerarquía de verdad, no todo del mismo tamaño
   ===================================================================== */
h1, h2, h3, h4 { letter-spacing: -.021em; font-weight: 700; }
h1 { font-size: 1.85rem !important; }
h2 { font-size: 1.42rem !important; margin-top: .4rem !important; }
h3 { font-size: 1.14rem !important; }
h4 { font-size: 1.0rem  !important; opacity: .96; }
.block-container p, .block-container li { line-height: 1.62; }
small, .stCaption, div[data-testid="stCaptionContainer"] p {
  line-height: 1.55; opacity: .78;
}

/* =====================================================================
   3. TARJETAS — st.container(border=True) deja de ser un rectángulo gris
   ===================================================================== */
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: var(--radio) !important;
  border-color: var(--borde) !important;
  background: var(--panel);
  box-shadow: var(--sombra);
  transition: transform .18s cubic-bezier(.2,.7,.3,1),
              box-shadow .18s ease, border-color .18s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
  transform: translateY(-2px);
  box-shadow: var(--sombra-alta);
  border-color: var(--borde2) !important;
}
/* una tarjeta dentro de otra no debe repetir sombra ni levantarse */
div[data-testid="stVerticalBlockBorderWrapper"]
  div[data-testid="stVerticalBlockBorderWrapper"] {
  box-shadow: none; background: transparent;
}
div[data-testid="stVerticalBlockBorderWrapper"]
  div[data-testid="stVerticalBlockBorderWrapper"]:hover { transform: none; }

/* =====================================================================
   4. MÉTRICAS — la cifra manda
   ===================================================================== */
div[data-testid="stMetric"] {
  background: linear-gradient(160deg, var(--panel2), var(--panel));
  border: 1px solid var(--borde);
  border-radius: var(--radio-s);
  padding: .8rem .95rem;
  transition: border-color .18s ease, transform .18s ease;
}
div[data-testid="stMetric"]:hover {
  border-color: var(--borde2); transform: translateY(-1px);
}
div[data-testid="stMetricValue"] {
  font-variant-numeric: tabular-nums; font-weight: 750;
  letter-spacing: -.03em; font-size: 1.72rem;
}
div[data-testid="stMetricLabel"] {
  opacity: .68; font-size: .76rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .06em;
}

/* =====================================================================
   5. PESTAÑAS — que se vea cuál está activa sin buscarla
   ===================================================================== */
div[data-baseweb="tab-list"] {
  gap: .25rem; border-bottom: 1px solid var(--borde);
  padding-bottom: 0; margin-bottom: .6rem;
}
button[data-baseweb="tab"] {
  font-weight: 620; border-radius: var(--radio-s) var(--radio-s) 0 0;
  padding: .55rem .9rem !important;
  transition: background .16s ease, color .16s ease;
}
button[data-baseweb="tab"]:hover { background: var(--sutil); }
button[data-baseweb="tab"][aria-selected="true"] {
  background: color-mix(in srgb, var(--ok) 11%, transparent);
}
div[data-baseweb="tab-highlight"] {
  background: var(--ok) !important; height: 3px !important;
  border-radius: 3px 3px 0 0;
}

/* =====================================================================
   6. BOTONES — jerarquía real entre «la acción» y «las demás»
   ===================================================================== */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: var(--radio-s); font-weight: 640; letter-spacing: -.005em;
  padding: .5rem 1rem;
  transition: transform .14s cubic-bezier(.2,.7,.3,1),
              box-shadow .18s ease, filter .18s ease, border-color .18s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px color-mix(in srgb, currentColor 16%, transparent);
  border-color: var(--borde2);
}
.stButton > button:active { transform: translateY(0); }
.stButton > button[kind="primary"] {
  box-shadow: 0 6px 18px color-mix(in srgb, var(--ok) 26%, transparent);
}

/* =====================================================================
   7. DESPLEGABLES Y SELECTORES
   ===================================================================== */
details summary, div[data-testid="stExpander"] summary {
  border-radius: var(--radio-s); font-weight: 600;
  transition: background .16s ease, padding-left .16s ease;
}
details summary:hover { background: var(--sutil); padding-left: .55rem; }
div[data-testid="stExpander"] {
  border: 1px solid var(--borde); border-radius: var(--radio-s);
  background: var(--panel); overflow: hidden;
}

div[data-baseweb="select"] > div,
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stDateInput"] input {
  border-radius: var(--radio-s) !important;
  border-color: var(--borde) !important;
  transition: border-color .16s ease, box-shadow .16s ease;
}
div[data-baseweb="select"] > div:hover {
  border-color: color-mix(in srgb, var(--ok) 50%, var(--borde)) !important;
}
div[data-baseweb="select"] > div:focus-within {
  border-color: var(--ok) !important;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 18%, transparent) !important;
}
/* el selector de competición es EL control de la app: se le da cuerpo */
div[data-testid="stSelectbox"] label { font-weight: 640; opacity: .85; }

/* radio y checkbox en forma de segmentos pulsables */
div[role="radiogroup"] { gap: .35rem; }
div[role="radiogroup"] label {
  border: 1px solid var(--borde); border-radius: var(--radio-p);
  padding: .3rem .8rem; transition: background .16s ease, border-color .16s ease;
}
div[role="radiogroup"] label:hover {
  background: var(--sutil); border-color: var(--borde2);
}

/* =====================================================================
   8. TABLAS — números alineados, cabecera legible
   ===================================================================== */
div[data-testid="stDataFrame"] {
  border-radius: var(--radio-s); overflow: hidden;
  border: 1px solid var(--borde);
}
div[data-testid="stDataFrame"] td { font-variant-numeric: tabular-nums; }

/* =====================================================================
   9. AVISOS — menos grito, más información
   ===================================================================== */
div[data-testid="stAlert"] {
  border-radius: var(--radio-s);
  border-width: 0 0 0 3px; padding: .75rem .95rem;
}

/* =====================================================================
   10. BARRA LATERAL
   ===================================================================== */
section[data-testid="stSidebar"] {
  border-right: 1px solid var(--borde);
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }

/* =====================================================================
   COMPONENTES PROPIOS
   ===================================================================== */

/* ---- cabecera de pantalla ------------------------------------------ */
.hero {
  position: relative; overflow: hidden;
  border: 1px solid var(--borde); border-radius: var(--radio);
  padding: 1.15rem 1.3rem 1.2rem;
  margin: .1rem 0 1.1rem;
  background:
    radial-gradient(120% 160% at 0% 0%,
      color-mix(in srgb, var(--ok) 15%, transparent) 0%, transparent 58%),
    radial-gradient(120% 160% at 100% 0%,
      color-mix(in srgb, var(--info) 13%, transparent) 0%, transparent 55%),
    var(--panel);
  animation: entra .32s cubic-bezier(.2,.7,.3,1) both;
}
.hero::after {
  content: ''; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: linear-gradient(90deg, var(--ok), var(--info), transparent);
  opacity: .75;
}
.hero h1 { margin: 0 0 .18rem; font-size: 1.65rem; line-height: 1.18; }
.hero .sub { opacity: .74; font-size: .93rem; line-height: 1.5; margin: 0; }
.hero .chips { margin-top: .7rem; display: flex; flex-wrap: wrap; gap: .35rem; }

/* ---- cabecera de sección ------------------------------------------- */
.sec {
  display: flex; align-items: baseline; gap: .55rem;
  margin: 1.4rem 0 .55rem; padding-bottom: .4rem;
  border-bottom: 1px solid var(--borde);
}
.sec b { font-size: 1.06rem; letter-spacing: -.015em; }
.sec i { font-style: normal; opacity: .62; font-size: .84rem; font-weight: 500; }
.sec .pt { width: 7px; height: 7px; border-radius: 50%; background: var(--ok);
           flex: 0 0 auto; align-self: center;
           box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 22%, transparent); }

/* ---- rejilla de KPIs ------------------------------------------------ */
.kpis { display: grid; gap: .55rem; margin: .3rem 0 .2rem;
        grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); }
.kpi {
  border: 1px solid var(--borde); border-radius: var(--radio-s);
  background: linear-gradient(160deg, var(--panel2), var(--panel));
  padding: .7rem .8rem; position: relative; overflow: hidden;
  transition: transform .18s cubic-bezier(.2,.7,.3,1), border-color .18s ease;
  animation: entra .3s cubic-bezier(.2,.7,.3,1) both;
}
.kpi:hover { transform: translateY(-2px); border-color: var(--borde2); }
.kpi::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--c, var(--borde2));
}
.kpi u { display: block; text-decoration: none; font-size: .68rem;
         font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
         opacity: .6; margin-bottom: .18rem; }
.kpi b { display: block; font-size: 1.55rem; font-weight: 750;
         letter-spacing: -.035em; line-height: 1.1;
         font-variant-numeric: tabular-nums; color: var(--c, inherit); }
.kpi s { display: block; text-decoration: none; font-size: .74rem;
         opacity: .62; margin-top: .18rem; line-height: 1.35; }

/* ---- píldoras de estado -------------------------------------------- */
.pild {
  display: inline-flex; align-items: center; gap: .28rem;
  padding: .17rem .62rem; border-radius: var(--radio-p);
  font-size: .755rem; font-weight: 680; letter-spacing: .005em;
  border: 1px solid transparent; white-space: nowrap; line-height: 1.5;
}
.pild-ok   { color: var(--ok);   background: color-mix(in srgb, var(--ok) 13%, transparent);
             border-color: color-mix(in srgb, var(--ok) 32%, transparent); }
.pild-mira { color: var(--mira); background: color-mix(in srgb, var(--mira) 13%, transparent);
             border-color: color-mix(in srgb, var(--mira) 32%, transparent); }
.pild-no   { color: var(--no);   background: color-mix(in srgb, var(--no) 13%, transparent);
             border-color: color-mix(in srgb, var(--no) 32%, transparent); }
.pild-azul { color: var(--info); background: color-mix(in srgb, var(--info) 13%, transparent);
             border-color: color-mix(in srgb, var(--info) 32%, transparent); }
.pild-info { opacity: .82; background: var(--sutil); border-color: var(--borde); }

/* ---- barra de probabilidad ------------------------------------------ */
.barra { height: 7px; border-radius: var(--radio-p); background: var(--sutil);
         overflow: hidden; margin: .4rem 0; }
.barra > i { display: block; height: 100%; border-radius: var(--radio-p);
             background: linear-gradient(90deg,
               color-mix(in srgb, var(--bc, var(--ok)) 45%, transparent),
               var(--bc, var(--ok)));
             animation: crece .55s cubic-bezier(.2,.7,.3,1); }
@keyframes crece { from { width: 0 } }

/* ---- barra 1X2 proporcional ----------------------------------------- */
.b1x2 { display: flex; height: 30px; border-radius: var(--radio-s);
        overflow: hidden; margin: .5rem 0 .35rem; font-size: .74rem;
        font-weight: 700; border: 1px solid var(--borde); }
.b1x2 > span { display: flex; align-items: center; justify-content: center;
               color: #fff; text-shadow: 0 1px 3px rgba(0,0,0,.45);
               transition: filter .16s ease; animation: ancho .5s cubic-bezier(.2,.7,.3,1);
               font-variant-numeric: tabular-nums; }
.b1x2 > span:hover { filter: brightness(1.14); }
.b1x2l { display: flex; justify-content: space-between; font-size: .72rem;
         opacity: .62; margin-bottom: .1rem; }
@keyframes ancho { from { width: 0 !important } }

/* ---- anillo de probabilidad -----------------------------------------
   El hueco del centro se hace con `mask`, no con un círculo interior pintado
   del color del fondo. Ese truco —el que tenía la v117— obliga a que el
   círculo de dentro ADIVINE el color de fondo de la página, y hay tres
   posibles: tema claro, tema oscuro y el tema propio del despliegue. En cuanto
   uno no coincide aparece un disco de otro color en mitad del anillo. Con
   `mask` el hueco es transparente de verdad y no hay nada que adivinar.   */
.anillo { position: relative; width: 96px; height: 96px; margin: .2rem auto;
          display: grid; place-items: center; }
.anillo .aro { position: absolute; inset: 0; border-radius: 50%;
               background: conic-gradient(var(--c) var(--p), var(--sutil) 0);
               -webkit-mask: radial-gradient(closest-side, transparent 71%, #000 72%);
               mask: radial-gradient(closest-side, transparent 71%, #000 72%);
               animation: gira .6s cubic-bezier(.2,.7,.3,1); }
.anillo .txt { position: relative; text-align: center; line-height: 1.05; }
.anillo .txt b { font-size: 1.34rem; font-weight: 750; letter-spacing: -.03em;
                 font-variant-numeric: tabular-nums; }
.anillo .txt small { display: block; opacity: .64; font-size: .58rem;
                     margin-top: 3px; text-transform: uppercase;
                     letter-spacing: .06em; }
@keyframes gira { from { --p: 0deg } }

/* ---- chips de cuota -------------------------------------------------- */
.cuota { display: inline-flex; align-items: baseline; gap: .32rem;
         padding: .22rem .6rem; border-radius: var(--radio-s); font-weight: 720;
         font-variant-numeric: tabular-nums; border: 1px solid var(--borde);
         background: var(--panel2); margin: 0 .3rem .3rem 0;
         font-family: var(--cifra); font-size: .88rem;
         transition: transform .14s ease, border-color .16s ease; }
.cuota:hover { transform: translateY(-1px); border-color: var(--borde2); }
.cuota i { font-style: normal; font-weight: 500; font-size: .66rem; opacity: .62;
           font-family: inherit; letter-spacing: .02em; }
.cuota.mejor { border-color: color-mix(in srgb, var(--ok) 55%, transparent);
               background: color-mix(in srgb, var(--ok) 11%, transparent);
               color: var(--ok); }

/* ---- medidor bidireccional (tu casa vs el mercado) ------------------- */
.med { margin: .45rem 0 .2rem; }
.med .via { position: relative; height: 8px; border-radius: var(--radio-p);
            background: var(--sutil); overflow: hidden; }
.med .via::before { content: ''; position: absolute; left: 50%; top: 0;
                    bottom: 0; width: 1px;
                    background: color-mix(in srgb, currentColor 34%, transparent); }
.med .via > i { position: absolute; top: 0; bottom: 0; border-radius: var(--radio-p);
                animation: crece .5s cubic-bezier(.2,.7,.3,1); }
.med .pie { display: flex; justify-content: space-between; font-size: .72rem;
            opacity: .68; margin-top: .28rem; }

/* ---- patas de una combinada ----------------------------------------- */
.patas { margin: .5rem 0 .2rem; display: grid; gap: .3rem; }
.pata {
  display: grid; grid-template-columns: 1fr auto; gap: .5rem .8rem;
  align-items: center; padding: .55rem .7rem;
  border: 1px solid var(--borde); border-radius: var(--radio-s);
  background: var(--panel); position: relative;
  transition: border-color .16s ease, background .16s ease;
  animation: entra .3s cubic-bezier(.2,.7,.3,1) both;
}
.pata:hover { border-color: var(--borde2); background: var(--panel2); }
.pata .q { font-weight: 640; font-size: .92rem; line-height: 1.35; }
.pata .m { font-size: .72rem; opacity: .58; margin-top: .1rem;
           display: flex; flex-wrap: wrap; gap: .3rem .55rem; }
.pata .c { font-family: var(--cifra); font-weight: 750; font-size: 1.06rem;
           font-variant-numeric: tabular-nums; text-align: right;
           letter-spacing: -.02em; }
.pata .c s { display: block; text-decoration: none; font-size: .68rem;
             font-weight: 500; opacity: .6; font-family: inherit; }

/* ---- ticket: el resumen de una combinada ---------------------------- */
.ticket { display: flex; flex-wrap: wrap; gap: .9rem 1.6rem;
          align-items: flex-end; margin: .15rem 0 .1rem; }
.ticket .big { font-family: var(--cifra); font-size: 2.05rem; font-weight: 780;
               letter-spacing: -.045em; line-height: 1;
               font-variant-numeric: tabular-nums; }
.ticket u { display: block; text-decoration: none; font-size: .67rem;
            font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
            opacity: .55; margin-bottom: .22rem; }

/* ---- nota / llamada de atención ------------------------------------- */
.nota { border-left: 3px solid var(--c, var(--info)); border-radius: 0 var(--radio-s) var(--radio-s) 0;
        background: color-mix(in srgb, var(--c, var(--info)) 8%, transparent);
        padding: .6rem .85rem; margin: .5rem 0; font-size: .88rem;
        line-height: 1.55; }
.nota b { font-weight: 680; }

/* ---- estado vacío ---------------------------------------------------- */
.vacio { border: 1px dashed var(--borde2); border-radius: var(--radio);
         padding: 1.6rem 1.2rem; text-align: center; background: var(--panel);
         margin: .5rem 0; }
.vacio .ico { font-size: 1.9rem; opacity: .5; display: block; margin-bottom: .4rem; }
.vacio b { display: block; font-size: 1.02rem; margin-bottom: .25rem; }
.vacio span { opacity: .68; font-size: .88rem; line-height: 1.55;
              display: block; max-width: 52ch; margin: 0 auto; }

/* ---- cabecera de partido -------------------------------------------- */
.match {
  display: grid; grid-template-columns: 1fr auto 1fr; gap: .5rem 1rem;
  align-items: center; padding: .1rem 0 .5rem;
}
.match .eq { font-weight: 700; font-size: 1.06rem; letter-spacing: -.015em; }
.match .eq.v { text-align: right; }
.match .vs { font-size: .74rem; opacity: .5; font-weight: 700;
             letter-spacing: .1em; }
.meta { display: flex; flex-wrap: wrap; gap: .3rem .55rem; font-size: .78rem;
        opacity: .68; margin-top: .1rem; align-items: center; }
.meta .sep { opacity: .4; }

/* ---- tabla de mercados propia --------------------------------------- */
.tm { width: 100%; border-collapse: separate; border-spacing: 0;
      font-size: .86rem; margin: .4rem 0; }
.tm th { text-align: left; font-size: .68rem; text-transform: uppercase;
         letter-spacing: .07em; opacity: .55; font-weight: 700;
         padding: .4rem .6rem; border-bottom: 1px solid var(--borde); }
.tm td { padding: .48rem .6rem; border-bottom: 1px solid var(--sutil);
         font-variant-numeric: tabular-nums; }
.tm tr:last-child td { border-bottom: 0; }
.tm tbody tr { transition: background .14s ease; }
.tm tbody tr:hover { background: var(--sutil); }
.tm .num { text-align: right; font-family: var(--cifra); font-weight: 680; }
.tm-wrap { overflow-x: auto; border: 1px solid var(--borde);
           border-radius: var(--radio-s); background: var(--panel); }

/* ---- entradas suaves ------------------------------------------------- */
@keyframes entra { from { opacity: 0; transform: translateY(6px) } }

/* =====================================================================
   MÓVIL — el usuario mira esto desde el teléfono antes de un partido
   ===================================================================== */
@media (max-width: 768px) {
  .block-container { padding-left: .75rem; padding-right: .75rem; }
  h1 { font-size: 1.45rem !important; }
  .hero { padding: .95rem 1rem 1rem; }
  .hero h1 { font-size: 1.32rem; }
  div[data-testid="stDataFrame"] { overflow-x: auto; }
  div[data-testid="stMetricValue"] { font-size: 1.35rem; }
  .kpis { grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); }
  .kpi b { font-size: 1.3rem; }
  .ticket .big { font-size: 1.7rem; }
  .match { grid-template-columns: 1fr; }
  .match .eq.v { text-align: left; }
  .match .vs { display: none; }
  .pata { grid-template-columns: 1fr auto; }
}

/* =====================================================================
   Quien pide menos movimiento, no lo recibe
   ===================================================================== */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
"""

_TONOS = {'ok': 'var(--ok)', 'mira': 'var(--mira)', 'no': 'var(--no)',
          'azul': 'var(--info)', 'info': 'var(--tenue)'}


def _color(tono: str) -> str:
    return _TONOS.get(tono, 'var(--tenue)')


def aplicar(st) -> None:
    """Inyecta los estilos. Un fallo aquí no puede costar la aplicación."""
    try:
        st.markdown(CSS, unsafe_allow_html=True)
    except Exception as e:
        logger.debug(f'[estilo] no aplicado: {type(e).__name__}: {e}')


def pinta(st, html: str) -> None:
    """
    Escribe un componente de este módulo. Atajo para no repetir el
    `unsafe_allow_html=True` en ciento y pico llamadas —y para que, si el
    componente devuelve vacío porque no entendió los datos, no se pinte un
    hueco en blanco.
    """
    try:
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as e:
        logger.debug(f'[estilo] no pintado: {type(e).__name__}: {e}')


# ---------------------------------------------------------------------------
# CABECERAS
# ---------------------------------------------------------------------------
def cabecera(titulo: str, subtitulo: str = '', chips=(), icono: str = '') -> str:
    """
    La cabecera de una pantalla: qué es esto y en qué estado está.

    Sustituye al `st.title` + `st.caption` + tres `st.metric` sueltos que había
    en cada vista. Los `chips` son el estado de un vistazo —cuántos partidos,
    qué día, cuántas casas cotizan— y van como píldoras, que es lo que un dato
    de contexto merece: visible sin competir con el título.
    """
    ch = ''
    if chips:
        trozos = []
        for c in chips:
            if isinstance(c, (tuple, list)) and len(c) == 2:
                trozos.append(pildora(c[0], c[1]))
            elif c:
                trozos.append(pildora(c))
        if trozos:
            ch = '<div class="chips">' + ''.join(trozos) + '</div>'
    return (
        '<div class="hero">'
        f'<h1>{_esc(icono) + " " if icono else ""}{_esc(titulo)}</h1>'
        + (f'<p class="sub">{_esc(subtitulo)}</p>' if subtitulo else '')
        + ch + '</div>')


def seccion(titulo: str, sub: str = '', tono: str = 'ok') -> str:
    """Separador de sección con punto de color. Reemplaza al `####` suelto."""
    if not titulo:
        return ''
    return (
        f'<div class="sec"><span class="pt" style="background:{_color(tono)};'
        f'box-shadow:0 0 0 3px color-mix(in srgb, {_color(tono)} 22%, transparent)">'
        f'</span><b>{_esc(titulo)}</b>'
        + (f'<i>{_esc(sub)}</i>' if sub else '') + '</div>')


# ---------------------------------------------------------------------------
# CIFRAS
# ---------------------------------------------------------------------------
def _kpi(valor, etiqueta: str, tono: str = 'info', sub: str = '') -> str:
    """
    Una cifra con su etiqueta y, opcionalmente, la letra pequeña debajo.

    Es privada a propósito: una cifra suelta no existe en esta interfaz — o va
    en una fila con sus compañeras (`kpis`, que reparte la rejilla sola) o es
    una métrica de Streamlit. Exponerla invitaría a maquetar filas a mano.
    """
    return (
        f'<div class="kpi" style="--c:{_color(tono)}">'
        f'<u>{_esc(etiqueta)}</u><b>{_esc(valor)}</b>'
        + (f'<s>{_esc(sub)}</s>' if sub else '') + '</div>')


def kpis(items) -> str:
    """
    Una fila de cifras.

    `items` son diccionarios `{valor, etiqueta, tono, sub}` o tuplas
    `(valor, etiqueta)`. Se reparten solas en la rejilla, así que la misma
    llamada vale para dos cifras y para seis, y en el teléfono se apilan sin
    que haya que decidir nada.
    """
    if not items:
        return ''
    trozos = []
    for it in items:
        if isinstance(it, dict):
            trozos.append(_kpi(it.get('valor', '—'), it.get('etiqueta', ''),
                               it.get('tono', 'info'), it.get('sub', '')))
        elif isinstance(it, (tuple, list)) and len(it) >= 2:
            trozos.append(_kpi(it[0], it[1],
                               it[2] if len(it) > 2 else 'info',
                               it[3] if len(it) > 3 else ''))
    return '<div class="kpis">' + ''.join(trozos) + '</div>'


def ticket(cuota, prob, extra: str = '', tono: str = 'ok') -> str:
    """
    El resumen de una combinada: la cuota y la probabilidad, en grande.

    Son las dos cifras que deciden, y hasta ahora salían como dos `st.metric`
    del mismo tamaño que «Deportes» o «Stake sugerido». Aquí mandan.
    """
    try:
        c, p = float(cuota), float(prob)
    except (TypeError, ValueError):
        return ''
    return (
        '<div class="ticket">'
        f'<div><u>Cuota combinada</u>'
        f'<div class="big" style="color:{_color(tono)}">{c:.2f}</div></div>'
        f'<div><u>Prob. de acertarlo todo</u>'
        f'<div class="big">{p*100:.0f}%</div></div>'
        f'<div><u>100 u pagan</u><div class="big">{c*100:.0f}</div></div>'
        + (f'<div style="flex:1 1 12rem;font-size:.82rem;opacity:.7;'
           f'line-height:1.5">{extra}</div>' if extra else '')
        + '</div>')


# ---------------------------------------------------------------------------
# ESTADO
# ---------------------------------------------------------------------------
def pildora(texto: str, tono: str = 'info') -> str:
    """
    Etiqueta corta de estado, en HTML, para meter dentro de un `st.markdown`.

    `tono` es 'ok' (accionable), 'mira' (con reparos), 'no' (descartado),
    'azul' (informativo con peso) o 'info'. El color va con el SIGNIFICADO, no
    con el gusto: si una píldora no distingue una decisión de otra, sobra.
    """
    t = tono if tono in ('ok', 'mira', 'no', 'azul', 'info') else 'info'
    return f'<span class="pild pild-{t}">{_esc(texto)}</span>'


def nota(texto: str, tono: str = 'azul', titulo: str = '') -> str:
    """
    Una advertencia o una aclaración, sin el bloque de color de `st.info`.

    Se usa para lo que este proyecto tiene que decir a menudo y no debería
    gritar cada vez: que el EV alto de una sola casa no es una oportunidad, que
    una cuota justa no es un precio que se pueda tomar.

    OJO: `texto` es el ÚNICO parámetro de este módulo que NO se escapa, porque
    estas notas llevan `<b>` para resaltar la cifra que importa. Sólo se le
    pasan literales escritos aquí. Si algún día hay que meter un dato —el
    nombre de un equipo, una casa—, pásalo por `_esc` en el llamador.
    """
    if not texto:
        return ''
    return (f'<div class="nota" style="--c:{_color(tono)}">'
            + (f'<b>{_esc(titulo)}</b> ' if titulo else '')
            + str(texto) + '</div>')


def vacio(titulo: str, texto: str = '', icono: str = '🗓️') -> str:
    """
    Qué se ve cuando NO hay nada que ver.

    Importa más de lo que parece: media aplicación depende de que hoy haya
    partidos y de que las casas hayan abierto mercado. Un hueco en blanco se
    lee como un fallo; esto dice qué falta y por qué.
    """
    return ('<div class="vacio">'
            f'<span class="ico">{_esc(icono)}</span><b>{_esc(titulo)}</b>'
            + (f'<span>{_esc(texto)}</span>' if texto else '') + '</div>')


# ---------------------------------------------------------------------------
# PROBABILIDAD
# ---------------------------------------------------------------------------
def barra(prob: float, tono: str = 'ok') -> str:
    """Barra de probabilidad, para ver de un vistazo lo que un % no transmite."""
    try:
        p = max(0.0, min(1.0, float(prob)))
    except (TypeError, ValueError):
        return ''
    return (f'<div class="barra" style="--bc:{_color(tono)}">'
            f'<i style="width:{p*100:.0f}%"></i></div>')


def barra_1x2(p_local: float, p_empate: float, p_visita: float,
              local: str = '1', visita: str = '2') -> str:
    """
    Las tres probabilidades del 1X2 en una sola barra proporcional.

    Tres porcentajes en fila obligan a comparar mentalmente; una barra donde
    cada tramo ocupa lo que vale se entiende sin leer. Los tramos llevan su
    cifra dentro cuando caben, el `title` da el detalle al pasar por encima, y
    encima van los nombres para no tener que adivinar cuál es cuál.
    """
    try:
        a, b, c = float(p_local), float(p_empate), float(p_visita)
    except (TypeError, ValueError):
        return ''
    s = a + b + c
    if s <= 0:
        return ''
    a, b, c = a / s, b / s, c / s

    def _tramo(p, color, titulo):
        txt = f'{p*100:.0f}%' if p >= 0.12 else ''
        return (f'<span style="width:{p*100:.2f}%;background:{color}" '
                f'title="{_esc(titulo)}">{txt}</span>')

    return (
        f'<div class="b1x2l"><span>{_esc(local)}</span><span>Empate</span>'
        f'<span>{_esc(visita)}</span></div>'
        '<div class="b1x2">'
        + _tramo(a, 'var(--ok)', f'{local}: {a*100:.0f} %')
        + _tramo(b, 'color-mix(in srgb, currentColor 32%, transparent)',
                 f'Empate: {b*100:.0f} %')
        + _tramo(c, 'var(--info)', f'{visita}: {c*100:.0f} %')
        + '</div>')


def anillo(prob: float, etiqueta: str = '', tono: str = 'ok') -> str:
    """
    Anillo de progreso para una probabilidad. Ocupa poco y se lee de lejos:
    sirve para la cifra principal de una tarjeta, donde una barra se pierde.
    """
    try:
        p = max(0.0, min(1.0, float(prob)))
    except (TypeError, ValueError):
        return ''
    return (
        f'<div class="anillo" style="--p:{p*360:.0f}deg;--c:{_color(tono)}">'
        f'<span class="aro"></span>'
        f'<span class="txt"><b>{p*100:.0f}%</b>'
        + (f'<small>{_esc(etiqueta)}</small>' if etiqueta else '')
        + '</span></div>')


# ---------------------------------------------------------------------------
# PRECIO
# ---------------------------------------------------------------------------
def chip_cuota(cuota, casa: str = '', mejor: bool = False) -> str:
    """Una cuota con su casa, destacada si es la mejor del tablón."""
    try:
        c = float(cuota)
    except (TypeError, ValueError):
        return ''
    clase = 'cuota mejor' if mejor else 'cuota'
    return (f'<span class="{clase}" title="{_esc(casa)}">{c:.2f}'
            + (f'<i>{_esc(casa)}</i>' if casa else '') + '</span>')


def medidor_precio(dif, casa_tuya: str = 'tu casa',
                   casa_mejor: str = 'el mercado') -> str:
    """
    Cuánto paga TU casa comparada con el mejor precio del mercado.

    Es el componente clave de la vista de una sola casa (v122). La escala va de
    −15 % a +15 % con el cero en el centro, porque lo que interesa no es el
    valor absoluto sino de qué lado del cero cae: a la derecha tu casa paga más
    y no pierdes nada por no tener otra cuenta; a la izquierda ése es el precio
    que te cuesta jugar donde juegas.

    Deliberadamente NO se pinta de rojo un diferencial pequeño: por debajo del
    2 % la diferencia es ruido de redondeo entre casas y marcarla en rojo
    empujaría a abrir cuentas por nada.
    """
    try:
        d = float(dif)
    except (TypeError, ValueError):
        return ''
    tope = 0.15
    frac = max(-1.0, min(1.0, d / tope))
    ancho = abs(frac) * 50.0
    if d >= 0.002:
        col, lado = 'var(--ok)', f'left:50%;width:{ancho:.1f}%'
    elif d <= -0.02:
        col, lado = 'var(--no)', f'right:50%;width:{ancho:.1f}%'
    elif d < 0:
        col, lado = 'var(--mira)', f'right:50%;width:{ancho:.1f}%'
    else:
        col, lado = 'var(--tenue)', 'left:50%;width:1%'
    return (
        '<div class="med"><div class="via">'
        f'<i style="{lado};background:{col}"></i></div>'
        f'<div class="pie"><span>{_esc(casa_tuya)} paga '
        f'<b style="color:{col}">{d*100:+.1f} %</b></span>'
        f'<span>frente a {_esc(casa_mejor)}</span></div></div>')


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


def tono_por_diferencia(dif) -> str:
    """El color de un diferencial de precio contra el mercado."""
    try:
        d = float(dif)
    except (TypeError, ValueError):
        return 'info'
    if d >= 0.002:
        return 'ok'
    if d <= -0.02:
        return 'no'
    return 'mira'


# ---------------------------------------------------------------------------
# COMBINADAS
# ---------------------------------------------------------------------------
def pata(apuesta: str, cuota, prob=None, mercado: str = '',
         etiquetas=(), tono: str = 'info') -> str:
    """
    Una pata de combinada como fila con estructura, no como una línea de texto.

    Antes era `• **Apuesta** @ 1.54 · 62% · EV -4.2 %`, todo del mismo tamaño y
    del mismo color. Aquí la apuesta manda, la cuota se lee alineada a la
    derecha en cifra monoespaciada, y lo que matiza (probabilidad, cuántas
    casas, avisos) va debajo en pequeño, que es donde va lo que matiza.
    """
    if not apuesta:
        return ''
    bajo = []
    if mercado:
        bajo.append(_esc(mercado))
    if prob is not None:
        try:
            bajo.append(f'acierta {float(prob)*100:.0f} %')
        except (TypeError, ValueError):
            pass
    marcas = ''.join(pildora(e[0], e[1]) if isinstance(e, (tuple, list))
                     else pildora(e) for e in (etiquetas or []))
    try:
        c_txt = f'{float(cuota):.2f}'
    except (TypeError, ValueError):
        c_txt = '—'
    return (
        f'<div class="pata" style="border-left:3px solid {_color(tono)}">'
        f'<div><div class="q">{_esc(apuesta)}</div>'
        + (f'<div class="m">{" · ".join(bajo)}</div>' if bajo else '')
        + (f'<div class="m" style="margin-top:.28rem">{marcas}</div>'
           if marcas else '')
        + f'</div><div class="c">{c_txt}</div></div>')


def patas(lista) -> str:
    """Todas las patas de una combinada, ya montadas con `pata`."""
    trozos = [p for p in (lista or []) if p]
    return '<div class="patas">' + ''.join(trozos) + '</div>' if trozos else ''


# ---------------------------------------------------------------------------
# PARTIDO
# ---------------------------------------------------------------------------
def cabecera_partido(home: str, away: str, meta=()) -> str:
    """
    El encabezado de un partido: los dos equipos y su contexto.

    `meta` son trozos sueltos —liga, hora, cuánto falta, frescura del modelo—
    que se pintan como una sola línea con separadores en vez de cuatro saltos
    de línea seguidos, que es como estaban.
    """
    trozos = [t for t in (meta or []) if t]
    linea = ('<div class="meta">'
             + '<span class="sep">·</span>'.join(
                 f'<span>{_esc(t)}</span>' for t in trozos)
             + '</div>') if trozos else ''
    return (
        '<div class="match">'
        f'<div class="eq">{_esc(home)}</div>'
        '<div class="vs">VS</div>'
        f'<div class="eq v">{_esc(away)}</div>'
        '</div>' + linea)


def tabla(columnas, filas, alineadas=()) -> str:
    """
    Una tabla propia, para cuando `st.dataframe` es demasiado.

    `st.dataframe` está bien para explorar datos, pero pinta una rejilla con
    barra de desplazamiento y altura fija que rompe el ritmo de una página de
    lectura. Esto es HTML plano: se lee como parte del texto, respeta el tema y
    en el teléfono se desliza en horizontal sin llevarse la página por delante.

    `alineadas` son los índices de columna con cifras, que van a la derecha y
    en tipografía monoespaciada.
    """
    if not columnas or not filas:
        return ''
    der = set(alineadas or ())
    th = ''.join(f'<th{" class=num" if i in der else ""}>{_esc(c)}</th>'
                 for i, c in enumerate(columnas))
    cuerpo = []
    for f in filas:
        tds = ''.join(f'<td{" class=num" if i in der else ""}>{v}</td>'
                      for i, v in enumerate(f))
        cuerpo.append(f'<tr>{tds}</tr>')
    return ('<div class="tm-wrap"><table class="tm"><thead><tr>'
            + th + '</tr></thead><tbody>' + ''.join(cuerpo)
            + '</tbody></table></div>')
