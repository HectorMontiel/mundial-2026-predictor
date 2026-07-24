# VALIDACIÓN v54 — Córners por equipo + mercados de córners/tarjetas + auditoría scores24

**Fecha:** 2026-07-24

## 1. Córners individuales por equipo (todas las ligas) ✅

**Problema:** la plantilla solo tenía córners TOTALES (media + O/U 8.5/9.5/10.5).
Faltaban los córners por equipo y los mercados derivados.

**Limitación de datos (auditada):** football-data.co.uk trae córners reales
(HC/AC) SOLO en el formato 'main' (Premier, LaLiga, Serie A, Bundesliga, Ligue 1,
Eredivisie, Primeira, Turquía, Grecia). El formato 'new' (**Liga MX, MLS, Brasil,
Argentina, China, nórdicas**) NO trae córners. Como el ejemplo del usuario es
Liga MX, la solución debe funcionar sin datos de córner.

**Solución (universal):** el córner total del modelo (heurística sobre el xG) se
reparte por equipo según su cuota de ataque (xG), con base de 2 córners cada uno.
Funciona en TODAS las ligas porque usa el xG (disponible en todas). Es una
estimación del modelo (declarada), coherente con que la suma = total.

Mercados añadidos a la sección «11. Córners y tarjetas» (33 mercados):
- Córners por equipo: media + O/U 3.5/4.5/5.5 (local y visitante)
- Córners 1X2 (quién saca más) — suma 100 % verificado
- Hándicap de córners (−1.5, −2.5 y sus espejos)
- Córners par/impar
- Tarjetas 1X2 (quién recibe más) + tarjetas por equipo O/U 1.5/2.5 (rojas ×2)

Todos con IDs nuevos (no se renombró nada) y clasificados en el motor de parlay
(`match_parlay._PREFIJOS`), así que se pueden **combinar** en «🎰 Arma TU
combinada». Verificado: *Atlante córners >3.5 (65 %) + Atlante +1.5 (93 %)* →
60 % conjunta, cuota justa 1.67.

No requiere reentrenar (deriva del xG en inferencia).

## 2. Auditoría de scores24.live 🔍

**Objetivo:** evaluar extraer datos de https://scores24.live/es/soccer para
alimentar la IA.

**Hallazgo:** el sitio está protegido por **Cloudflare** (la 2ª petición devolvió
la página de error de Cloudflare, `cf.errors.css`, 4.5 KB) y es una **SPA React
renderizada por JavaScript** (sin datos en el HTML inicial). Extraer datos exigiría
eludir Cloudflare con navegador headless — frágil, contra la regla del proyecto
(«sin scraping agresivo») y contra los ToS del sitio.

**Conclusión y decisión:** NO se scrapea scores24. El VALOR que aporta (córners,
remates, tarjetas, faltas por equipo) ya está en fuentes que usamos legalmente:
- **football-data.co.uk** ('main'): HC/AC (córners), HS/AS + HST/AST (remates y a
  puerta), HF/AF (faltas), tarjetas. Ya se DESCARGAN pero no se explotaban por
  equipo → esta es la palanca real.
- **ESPN** (JSON, sin clave): stats por partido + cuotas (ya integrado en v52).

**Auditoría de qué darían MÁS valor estos datos (roadmap):**
1. **Enriquecer team_stats con córners/remates/faltas por equipo** (MA5) para las
   ligas 'main' → córners y remates por equipo DIRIGIDOS POR DATOS (mejor que la
   heurística xG). Requiere reentrenar (recalcula stats). Alto valor para
   Premier/LaLiga/etc.; nulo para Liga MX (sin datos).
2. **Remates y remates a puerta** (mercados de la plantilla §4) — derivables ya en
   'main' (tenemos HST/AST). Añadir O/U por partido y por equipo.
3. **Modelo de medias partes** (§7-8: 1ª/2ª mitad 1X2, totales, BTTS) — requiere un
   modelo de goles por mitad; tenemos la señal `g2h` (reparto 2ª mitad) como punto
   de partida. Esfuerzo medio.
4. **Goleadores** (§3) — requiere modelo a nivel jugador (hay `player_db` /
   `jugadores_clave`). Esfuerzo alto.

## 3. No incluido (honestidad)

De la plantilla completa del usuario, NO se añadió lo que exige datos/modelos que
no tenemos: goleadores, fueras de juego, asistencias, mercados de 1ª/2ª mitad,
marcador exacto ampliado y hándicaps de cuartos (0.25/0.75). Se documentan en el
roadmap; se irán añadiendo por valor.

## No regresión
- `test_simetria.py` → TODO OK · `test_match_parlay.py` → TODO OK
- Smoke `dashboard_ui.py` (Liga MX 'new', LaLiga 'main') → OK
