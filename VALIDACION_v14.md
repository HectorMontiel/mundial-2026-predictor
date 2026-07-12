# VALIDACIÓN v14 — "Solo gratis, solo real" (2026-07-12)

Filosofía: todas las fuentes incorporadas son **gratuitas y legales**. Cada
mejora se validó con backtesting; lo que no superó el listón se documenta y
descarta. El 1X2 del Mundial permanece intacto (los cambios de datos vienen
solo de partidos REALES nuevos).

---

## M7 — Resultados en vivo del Mundial con fuente 100 % gratuita ✅ ADOPTADO

- **Fuente elegida: ESPN** (`site.api.espn.com`, JSON público, sin clave).
  Flashscore se evaluó primero (la especificación lo proponía) pero su HTML
  se renderiza por JavaScript y el contenido estático solo sirve "partidos de
  hoy" — frágil de parsear. ESPN devuelve JSON estructurado y estable:
  estrictamente mejor con el mismo coste (cero).
- Cadena final en `live_worldcup.py`: API-Football (con clave) → **ESPN** →
  FBref → base Kaggle.
- **Endurecimiento del dedupe**: las fuentes en vivo reportan fecha UTC y la
  base Kaggle fecha local (el mismo partido puede diferir ±1 día), y los
  nombres difieren ("Türkiye"/"Turkey", "Czechia"/"Czech Republic"). Se
  añadió mapeo ESPN→Kaggle y dedupe por par de equipos con ventana ±1 día.
- **Resultado**: 19 partidos reales nuevos añadidos (octavos y cuartos que
  Kaggle aún no traía; histórico pasó del 2026-07-02 al 2026-07-12), 0
  duplicados verificados por par de equipos.

## M8 — xG real de Understat ❌ DESCARTADO COMO FEATURE (scraper disponible)

- `understat_scraper.py` funciona: endpoint JSON `getLeagueData/{liga}/{año}`,
  caché por temporada, pausas de 4 s, 98 % de partidos emparejados en LaLiga.
- Cobertura: Premier, LaLiga, Serie A, Bundesliga, Ligue 1 (no Liga MX,
  Eredivisie ni Primeira — Understat no las publica).
- **A/B controlado (mismo código, mismos datos, con/sin xG real):**

  | Liga    | Sin xG real (acc / log-loss) | Con xG real | Veredicto |
  |---------|------------------------------|-------------|-----------|
  | LaLiga  | 50.7 % / 1.014               | 50.7 % / 1.108 | log-loss peor |
  | Premier | 45.0 % / 1.077               | 44.6 % / 1.092 | ambas peor |

- **Por qué empeora**: el relleno sintético calibrado está condicionado a los
  goles reales del partido (encapsula el resultado de forma suavizada); el xG
  real solo mide calidad de ocasiones. Como feature de forma reciente, la
  señal sintética es más informativa.
- La inyección queda **desactivada** en `league_engine.descargar_liga` (véase
  el comentario en el código); el módulo queda en el repo, mismo precedente
  que `player_ratings.py` en v13.

## M9 — Valores de plantilla Transfermarkt ⚠️ MECANISMO LISTO, NO ADOPTADO

- `transfermarkt_scraper.py`: 1 petición por LIGA (página resumen con el
  valor de plantilla de todos los clubes), caché 24 h, pausas de 8 s.
  Accesible desde esta red con requests simple (20 clubes LaLiga OK).
- Feature experimental `VAL_LOG_RATIO` con `league_engine.py --build <liga>
  --ratings` (evalúa SIN guardar artefactos).
- **A/B**: LaLiga 50.7 % → 50.7 % (=, bajo umbral); Premier 45.0 % → 46.8 %
  (**+1.8 pp**, pasa el umbral numérico de 0.5 pp).
- **Decisión: NO adoptar pese al número.** Los valores son los ACTUALES
  aplicados a partidos de hasta 3 temporadas atrás → sesgo de anticipación
  (un club que mejoró "sabe" en el pasado lo que vale hoy) y los descendidos
  reciben la mediana. El backtest es estructuralmente optimista y no es
  comparable 1:1. Para adoptar honestamente harían falta valores históricos
  fechados (scraping por jugador, horas por temporada) — pendiente v15.

## M10 — Cuotas reales gratuitas para el parlay ✅ ADOPTADO

- **Clubes: `fixtures.csv` de football-data.co.uk** (mismo proveedor del
  histórico): B365 1X2 + over/under 2.5 + hándicap asiático de los próximos
  partidos, sin clave ni scraping. Integrado en `fetch_odds.py` →
  `odds_actuales.json` → `parlay_builder`. Al ser el MISMO proveedor de las
  cuotas de cierre del backtest, no requiere validación cruzada.
  *Nota: en el receso de verano (hoy) trae 0 filas de nuestras ligas; en
  agosto fluye solo.*
- **Mundial: `betexplorer_scraper.py`** — robots.txt revisado (permite las
  páginas de competición; solo bloquea query-strings y rutas internas).
  1 petición por corrida. El HTML estático de Betexplorer solo lista los
  partidos DEL DÍA, así que el scraper filtra por selecciones mundialistas:
  en días de partido captura exactamente las cuotas que el parlay necesita
  (semifinales 14-15 julio). Hoy (día sin partidos): 0 filas, comportamiento
  correcto.
- Cadena en `fetch_odds.actualizar_odds`: The Odds API (clave) → Betexplorer
  (Mundial) + fixtures.csv (clubes, siempre).
- Oddsportal se descartó: JS pesado, mismo grupo que Flashscore.

## M11 — UI para apostadores ✅ (sin impacto en backtesting)

- **Modo Principiante/Pro** (radio en la barra lateral): Principiante oculta
  el monitor técnico de features y la jerga de "bajo el capó"; añade
  advertencia de juego responsable en cristiano. Pro conserva todo.
- **Asistente de Parlay en 3 pasos**: perfil de riesgo (🛡️ Conservador
  4 selecciones/prob≥65 % · ⚖️ Medio 6/55 % · 🚀 Agresivo 8/50 %) →
  propuesta con frase clara ("Este parlay tiene un X % de probabilidad de
  ganar, cuota total Y, EV Z unidades") → bloque copiable + descarga.
- Tooltips en métricas (EV, cuota combinada, prob. conjunta, riesgo) y
  glosario de EV/cuota justa en la barra lateral.
- Sidebar arranca expandido (`initial_sidebar_state='expanded'`).
- Smoke tests AppTest: 0 excepciones en Pro, Principiante y vista Serie A.

## M12 — Cinco ligas europeas nuevas ✅ ADOPTADO

Fuente: football-data.co.uk (formato main con stats + cuotas B365 de cierre).
Ventana de temporadas elegida por margen sobre ELO (regla ≥0.5 pp, mismo
criterio que v13/M5):

| Liga        | Temporadas | Modelo | ELO base | Mercado | Margen vs ELO |
|-------------|-----------|--------|----------|---------|----------------|
| Serie A     | 3         | 54.3 % | 53.4 %   | 57.1 %  | +0.9 pp (con 5: +0.0) |
| Bundesliga  | 5         | 54.3 % | 53.3 %   | 55.0 %  | +1.0 pp (con 3: −1.2) |
| Ligue 1     | 5         | 51.1 % | 48.9 %   | 53.5 %  | +2.2 pp |
| Eredivisie  | 5         | 51.3 % | 49.7 %   | 53.4 %  | +1.6 pp (con 3: −1.7) |
| Primeira    | 3         | 52.5 % | 49.7 %   | 55.4 %  | +2.8 pp (con 5: +2.4) |

Todas superan su línea base ELO; ninguna supera al favorito del mercado
(consistente con Premier/LaLiga — se reporta con transparencia en cada
plantilla). Selector de competición ampliado a 10 opciones en la UI.

## M13 — Orquestador `pipeline_total.py` ✅

Un comando actualiza todo con aislamiento de errores por paso (un fallo no
detiene el resto): Mundial (Kaggle + en vivo) → clubes (8 ligas) → cuotas →
Polymarket → Transfermarkt (solo `--ratings`). Flags `--solo-mundial` /
`--solo-clubes`. Probado: 8/8 ligas OK + cadena de cuotas OK.

---

## Cambio de infraestructura: giotto-tda → ripser

Streamlit Community Cloud hacía **segmentation fault** al cargar giotto-tda
(extensión C++ incompatible con su Linux). Se migró el cálculo de entropías
de persistencia a `ripser` (mismo algoritmo Vietoris-Rips H0/H1, wrapper
estable multiplataforma) en `train_tda_model.py` y `prediction_api.py`, y se
reentrenó el Mundial: **59.4 % / 0.902** (v13 con giotto: 59.4 % / 0.902 —
sin cambio material). Los modelos de ligas se reconstruyeron con ripser.

## Reglas de no-regresión verificadas

- Mundial 1X2: el modelo desplegado solo cambió por el reentrenamiento
  ripser (equivalente) y por partidos REALES nuevos (ESPN) — ninguna feature
  nueva entró al clasificador.
- Ligas v13 (Liga MX, Premier, LaLiga): reconstruidas sin features nuevas;
  las diferencias vs los números de v13 provienen de datos más recientes y
  del cambio ripser, no de cambios de diseño.
- Champions sigue en beta (sin fuente CSV gratuita), marcada en la UI.
