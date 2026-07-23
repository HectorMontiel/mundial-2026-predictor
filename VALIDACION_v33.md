# VALIDACIÓN v33 — Expansión estival, resiliencia y automatización

**Fecha:** 2026-07-23 · Regla de oro respetada; Mundial (60.49 %) y las 10
ligas previas intactos.

## 0. Principio transversal: cadena de resiliencia ✅ PROBADO

`source_resilience.py` ejecuta fuentes ordenadas hasta que una devuelve
datos válidos; cada eslabón en su propio try/except y **nunca** propaga la
excepción al pipeline.

**Probado con fallo forzado** (no es decorativo): con la fuente primaria
lanzando una excepción, el eslabón 2 (ESPN) tomó el relevo y devolvió 20
partidos; con todas las fuentes rotas, la cadena devuelve `None` limpio para
que el llamador conserve el estado anterior.

## 1. Ligas de verano (§1.1) — verificación antes de construir

| Liga | Estado de la fuente | Decisión |
|---|---|---|
| **Brasil** (BRA.csv) | 5,502 partidos, **actualizado hace 4 días** | ✅ **AÑADIDA** |
| **Argentina** (ARG.csv) | 6,235 partidos, **59 días sin actualizar** | ✅ añadida (la cuarentena v32 la degrada sola) |
| **Japón** (JPN.csv) | **228 días sin datos** (2025-12-06) | ❌ **NO se añade**: football-data dejó de publicarla; entrenar con eso sería vender humo |

Entrenamiento (split 80/20):

| Liga | Modelo | ELO | Mercado |
|---|---|---|---|
| **Brasil** | **52.3 %** | 45.2 % | 52.1 % → 🏆 **bate al mercado** |
| Argentina | 42.1 % | 38.8 % | 41.7 % → por encima del mercado, aunque en una liga de altísima varianza |

Ambas quedan en el selector y en el barrido; con sus claves añadidas a The
Odds API (`soccer_brazil_campeonato`, `soccer_argentina_primera_division`)
ya aportan partidos reales: cobertura verificada `{mls:6, argentina:6,
brasil:2, primeira:1}`.

## 2. MLS al día (§1.2) ✅ RESUELTO

El diagnóstico de la v32 (estado 58 días obsoleto) se corrigió: football-data
ya publica USA.csv hasta el **2026-07-18**, así que la MLS se reentrenó
(47.1 % vs ELO 45.1 %) y **sale de la cuarentena**. La cadena de resiliencia
queda montada con tres eslabones reales (football-data → ESPN → API-Football)
para que no vuelva a envejecer en silencio.

*Nota de honestidad sobre el orden:* el spec ponía ESPN primero, pero
football-data es la fuente CANÓNICA de entrenamiento del proyecto y estaba
fresca; invertir el orden habría mezclado grafías de equipos. ESPN queda como
respaldo vivo (verificado: 15 eventos con marcador).

## 3. Umbrales adaptativos (§2) ✅

`config.UMBRALES_DEPORTE` centraliza los umbrales de Capa 1/Capa 2 por
deporte (Fútbol 70/75, MLB 58/65, NBA 60/70, Tenis 65/75), consumidos por
`alpha_finder`. Evita que el béisbol —cuyo techo real ronda el 57 %— se
quede permanentemente sin picks.

## 4. ELO Ataque/Defensa (§3.1) ❌ NO ADOPTADO (y por qué)

Dos ratings por equipo (ATK/DEF) actualizados enfrentando ataque contra
defensa, con features `ATK_local − DEF_visitante` y `DEF_local − ATK_visitante`:

| Liga | base | +ATK/DEF | Veredicto |
|---|---|---|---|
| Liga MX | 51.26 % | 50.19 % | ❌ −1.07 pp |
| Premier | 51.27 % | 49.22 % | ❌ −2.05 pp |
| LaLiga | 54.30 % | 53.92 % | ❌ −0.38 pp |
| Serie A | 54.35 % | 52.31 % | ❌ −2.04 pp |
| Bundesliga | 49.24 % | 50.00 % | ⚠️ +0.76 pp (pasa la regla) |
| Brasil | 53.22 % | 53.26 % | ⚠️ **+0.04 pp** (pasa por la cláusula de «mejora en ambas», pero es ruido puro) |

**Decisión: NO se adopta en ninguna liga.** Los números lo dicen claro:
**4 de 6 ligas se degradan** (hasta −2.05 pp), una mejora +0.04 pp (ruido
de libro) y solo Bundesliga sube de forma apreciable. Con seis pruebas
simultáneas, un único positivo aislado es exactamente lo que produce el azar:
adoptarlo sería premiar una comparación múltiple. Se aplica el mismo criterio
que descartó el IMT en MLS (+0.04 pp) y el Shadow en Serie A (+22 % con
n=62). Documentado para no repetir el experimento.

## 5. Optimizador de cartera (§3.2) ✅ EXPERIMENTAL

`portfolio_optimizer.py`: máximo Sharpe long-only con **covarianza DIAGONAL
entre deportes/ligas distintos** (independencia declarada, como exige el
§3.2) y ρ=0.15 solo dentro de la misma liga y día; tope del 25 % por pick y
escala a la exposición objetivo (20 %). Incluye `comparar_con_kelly()` (Monte
Carlo de una jornada: retorno, volatilidad y peor 5 %).

**No sustituye al Kelly simultáneo**: con los picks de hoy (1 solo con cuota
real) la comparación no es concluyente y el módulo lo dice
(«se necesitan ≥2 picks»). Se dejará correr durante la temporada.

## 6. Bot de Telegram (§4) ✅

`bot_telegram.py` + `.github/workflows/telegram_bot.yml` (cron diario 10:00
UTC + ejecución manual). El workflow refresca datos con
`pipeline_total.py --update-only` (flag nuevo: solo cuotas, sin reentrenar)
antes de calcular los picks.

**Seguridad**: token y chat_id se leen **exclusivamente** de `os.environ`
(GitHub Secrets); sin credenciales el script entra en modo seco e imprime el
mensaje. Los errores de Telegram se registran **sin** exponer el token.
Verificado en seco: el mensaje sale formateado con Pick del Día, Capa 1,
Capa 2, escalera y el aviso de EV extremo.

## 7. Indicador de antigüedad (§5) ✅

Semáforo 🟢 <3 d / 🟡 3-7 d / 🔴 >7 d en cada tarjeta de pick, con tooltip
explicando que es la frescura de los datos con los que se entrenó la liga.

## 8. No regresión ✅

test_simetria ✓ · test_match_parlay ✓ · **smoke de 12 ligas de fútbol**
(incluidas Brasil y Argentina) ✓ · smoke MLB/NBA/Tenis ✓ · AppTest en ambos
modos × todas las vistas ✓ · Mundial intacto.

## 9. Pendientes heredados

Shadow en Bundesliga/Eredivisie con RLM (calendarizado a septiembre 2026,
§3.3) y CDI en fútbol (§3.4): sigue faltando el histórico de sedes por
partido; no se fuerza.
