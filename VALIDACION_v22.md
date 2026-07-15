# VALIDACIÓN v22 — FBref, Champions descongelada y asistente IA (2026-07-14)

Regla de oro de siempre. El Mundial (60.49 % / 0.8688) no se tocó.

## Realidad vs plan: dos supuestos del master prompt NO se cumplen

1. **`cloudscraper` NO supera el 403 de FBref** desde esta red (verificado;
   Cloudflare moderno no cae con esa técnica). `fbref_scraper_v3.py` lo
   intenta igualmente con pausas de 4-8 s por si otra red lo permite, y
   degrada a la caché en disco.
2. **FBref ya NO publica xG en los calendarios** — verificado en Liga MX
   2023-24 y Champions 2024-25/actual: las columnas home_xg/away_xg no
   existen. La promesa de "posesión + xG masivo para Liga MX, Eredivisie,
   Primeira" **no existe hoy en FBref**, así que los reentrenamientos con
   esas features quedan SIN efecto posible y se documenta como fracaso del
   supuesto (las stats reales siguen llegando gota a gota por el backfill
   de API-Football de v21, a ~40 partidos/día).

Lo que FBref SÍ da: **resultados completos de la Champions 2017-presente,
incluida la temporada en curso** que el plan Free de API-Football bloquea.
La caché `fbref_cache/*.psv` se sembró con una sesión de navegador real
(956 partidos, 8 con prórroga excluidos del 1X2 por no traer el marcador de
los 90').

## M1 — Champions: histórico ampliado y forma DESCONGELADA ✅

Fusión en `league_engine._fusionar_fbref_champions`:
- API-Football manda en 2022-24 (marcadores de 90' exactos); FBref aporta lo
  demás, incluida la 2025-26 completa y las fases previas 2026-27 (partidos
  de HOY mismo).
- Nombres FBref → canónicos API con mapeo aprendido del solape 2022-23
  (unión fecha+marcador) + 25 alias verificados a mano + fuzzy 0.85.
  Falsos amigos protegidos: Rīga FC ≠ Rīgas FS, Kauno Žalgiris ≠ Zalgiris
  Vilnius, Tre Fiori ≠ Tre Penne, FK Partizan ≠ Partizani.

**Walk-forward de 3 profundidades de historia** (`run_wf_champions_v22.py`;
baseline v21 = 53.5 % / 1.007 en la ventana 2024-25):

| Variante | 2024-25 (n≈215) | 2025-26 (n≈176) | media acc | media ll |
|---|---|---|---|---|
| B solo 2022+ | 53.1 % / 1.018 | **54.9 %** / 0.990 | **54.0 %** | 1.004 |
| C todo 2017+ | **54.7 %** / 0.983 | 52.3 % / 0.976 | 53.5 % | 0.979 |
| **D desde 2020 (ADOPTADA)** | 53.7 % / **0.959** | 53.4 % / 0.997 | 53.5 % | **0.978** |

Las diferencias de precisión están dentro del ruido (±3 pp de error estándar
por ventana); decide la calibración, el criterio histórico del proyecto:
**D mejora AMBAS métricas vs el baseline en la ventana comparable**
(53.7≥53.5 y 0.959<1.007 ✓ regla de oro) y tiene el mejor log-loss medio.
Config: `LEAGUES['champions']['desde'] = '2020-06-01'`.

Modelo desplegado: 1,174 partidos (2020-08 → 2026-07-14), split 53.8 % /
0.977. **La forma de los equipos ya NO está congelada en 2024-25** — el
aviso de la UI se sustituyó por la nota de fuentes.

## M2 — Reentrenamiento Liga MX / Eredivisie / Primeira con xG de FBref ❌

Imposible: FBref no publica xG para esas ligas (ver arriba). No hay
experimento que correr sin la feature; queda para cuando el backfill de
API-Football acumule cobertura (posesión/remates; xG tampoco existe allí
para Liga MX). Sin cambios en esas ligas = sin regresión.

## M3 — Asistente de apuestas con IA generativa local ✅ (con honestidad)

`asistente_comentarios.py` — comentario del analista **inline** en la vista
del partido (Mundial y clubes), compuesto por plantillas deterministas a
partir de las cifras reales del modelo (1X2, goles esperados, EV con cuotas
reales, riesgo de mercado; variedad por hash del partido, sin RNG global —
lección EGY-AUS). Con **Ollama local** corriendo (Phi-3/Llama 3.2, checkbox
"🤖 Reescribir con SLM local" en la barra lateral) el SLM reescribe el
comentario y el texto queda marcado como tal.

Por qué NO se embarca el SLM: Phi-3 mini cuantizado (~2.3 GB) supera la RAM
del tier gratuito de Streamlit Cloud y el límite de 100 MB por archivo de
GitHub. Las plantillas corren en cualquier parte; el SLM es mejora local
opcional y gratuita. (Se desarrollaron dos implementaciones en paralelo y
se consolidó en una sola — sin duplicados en la UI.)

## M4 — Panel de rendimiento ampliado ✅

- Barras agrupadas **Modelo vs ELO vs Mercado** por liga (la "comparativa
  visual" de la spec).
- **Evolución walk-forward por ventanas de 6 meses** (`run_wf_panel_v22.py`
  → `wf_panel_v22.json`, ahora conectado a la UI): línea de precisión del
  modelo vs favorito del mercado por ventana. Transparencia total: se ven
  las ventanas malas (p. ej. Bundesliga 35 % en 2025-02→08) tal cual son —
  la variación entre ventanas ES la incertidumbre real del modelo.

## No-regresión

- Mundial y las 8 ligas football-data: intactos.
- Tests en verde: `test_match_parlay.py`, `test_simetria.py`, AppTest en
  vista Mundial y vista Champions (0 excepciones).
- API-Football: 0 requests nuevos en toda la v22 (todo de caché/FBref).
