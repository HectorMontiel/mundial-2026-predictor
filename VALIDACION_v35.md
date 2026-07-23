# VALIDACIÓN v35 — Precisión, cobertura y automatización

**Fecha:** 2026-07-23 · **Protocolo:** walk-forward con ventanas móviles,
entrenando solo con el pasado. **Regla de oro:** ≥ +0.3 pp de precisión sin
empeorar el log-loss más de 0.01 (o mejorar ambos).

---

## 0. Resumen ejecutivo

| Frente | Resultado |
|---|---|
| §1 Tenis WTA | **Circuito femenino OPERATIVO**: 43,821 partidos, 64.86 % (walk-forward 65.57 %) vs ranking 62.75 % — **objetivo ≥65 % cumplido en walk-forward**. Mercado 67.9 % (no batido). |
| §1 Tenis ATP | Reentrenado con ELO de pista cubierta: **64.9 → 65.22 %** (mercado 68.26 %). Las features de fatiga **NO se adoptan en ATP** (+0.25 pp, bajo umbral). |
| §1 Challengers | **NO incorporados** — fuente inexistente/congelada (evidencia abajo). |
| §2 Europa League | **INCORPORADA** con 1,356 partidos (2019-2026). WF 51.71 % vs ELO 50.61 % ✅ |
| §2 Conference League | **INCORPORADA** con 729 partidos (2021-2026). WF 46.29 % vs ELO 43.21 % ✅ |
| §3 CDI en fútbol | **ADOPTADO en Europa League y MLS**; descartado en Champions, Conference y Liga MX. |
| §4 Telegram | Workflow verificado y mensaje generado de extremo a extremo; **bug de codificación corregido**. Falta el disparo manual del usuario en GitHub (requiere sus credenciales). |

---

## 1. Correcciones de supuestos del spec (verificadas empíricamente)

Antes de construir nada se comprobó cada fuente que el spec daba por hecha.
**Dos de ellas no existen tal como se describían:**

| Supuesto del spec v35 | Verificación (2026-07-23) | Consecuencia |
|---|---|---|
| «football-data.co.uk publica Europa League desde 2019 y Conference desde 2021» | **FALSO.** `data.php` solo lista ligas domésticas; `/new/EUR.csv` → **404**. Ninguna URL del sitio cubre competiciones UEFA. | Se sustituye por el **JSON público de ESPN** (`uefa.europa`, `uefa.europa.conf`), que además trae la SEDE de cada partido. |
| «mirror de Kaggle del dataset WTA de Jeff Sackmann» | El repo de Sackmann sigue en **404** (igual que en v30), pero **sí existe** un mirror equivalente: `dissfya/wta-tennis-2007-2023-daily-update`. | WTA operativa, **con cuotas de cierre** (100 % de cobertura) → línea base de mercado real. |
| «dataset de Challengers en el mismo repositorio de Kaggle» | `dissfya/atp-challenger-tennis-daily-pull` → **403** (privado). El único mirror gratuito con categorías inferiores (`ehallmar/a-large-tennis-dataset-for-atp-and-itf-betting`) **termina en 2018-08**. | **NO se incorporan.** Añadirían volumen de hace 8 años, no capacidad de predecir hoy. |
| «The Odds API no tiene tenis en la capa gratuita» (nota de la v30) | **FALSO, corregido en v35.** Sí lo tiene: **41 claves POR TORNEO** (`tennis_atp_*`, `tennis_wta_*`). No aparecían porque solo existen mientras el torneo se juega. | `odds_api.capturar_tenis()` las descubre con `/sports` (endpoint **gratuito**) y solo gasta crédito si hay torneo en curso. |
| «volumen combinado > 400,000 partidos» | ATP 68.3k + WTA 45.1k = **113.4k**. Los 400k del spec solo se alcanzarían con ITF/Challengers, que no hay. | Documentado; el volumen real es el que hay. |

---

## 2. §1 — Modelo de tenis (ATP + WTA)

### 2.1 Fuentes y volumen

| Circuito | Dataset | Partidos | Rango | Cuotas |
|---|---|---|---|---|
| ATP | `dissfya/atp-tennis-2000-2023daily-pull` | 68,300 (66,570 utilizables) | 2000 → 2026-07-19 | Odd_1/Odd_2 |
| WTA | `dissfya/wta-tennis-2007-2023-daily-update` | 45,064 (43,821 utilizables) | 2006 → 2026-07-19 | Odd_1/Odd_2 (100 %) |

### 2.2 Features nuevas

- **ELO por superficie con pista CUBIERTA propia**: `hard_indoor` ≠ `hard`
  (5 superficies efectivas). Cadena de respaldo explícita:
  superficie exacta → misma superficie al aire libre → ELO global.
- **Fatiga** (pase cronológico, sin fuga): `DIFF_DIAS_DESCANSO`,
  `DIFF_PARTIDOS_14D`, `DIFF_HORAS_7D` (horas en pista estimadas del
  marcador: juegos disputados × 3.75 min).
- **Puntos de ranking** (`DIFF_PTS_LOG`), más informativos que la posición.
- **ELO de saque/resto: IMPOSIBLE.** El dataset no publica aces, dobles
  faltas ni puntos ganados al saque → fallback al ELO global, exactamente
  el camino que el propio spec §1.3 contempla.

### 2.3 Walk-forward (5 ventanas anuales, `run_wf_tenis_v35.py`)

| Circuito | v30 (6 features) | v35 (10 features) | Ranking | Mercado | Veredicto |
|---|---|---|---|---|---|
| **ATP** | 64.98 % / 0.6204 | 65.23 % / 0.6209 | 63.91 % | 68.10 % | **NO adoptado** (+0.25 pp < 0.3 y log-loss plano) |
| **WTA** | 65.34 % / 0.6164 | **65.57 % / 0.6137** | 63.26 % | 68.05 % | **ADOPTADO** (mejora precisión Y log-loss) |

Modelos en producción (split 80/20 sobre todo el histórico):

| Circuito | Precisión | Log-loss | Ranking | Mercado |
|---|---|---|---|---|
| ATP | **65.22 %** (v30: 64.9) | 0.6175 | 62.60 % | 68.26 % |
| WTA | **64.86 %** | 0.6156 | 62.75 % | 67.91 % |

**Honestidad sobre el objetivo:** el spec pedía «acercar la precisión al
mercado (68 % ATP)». Se acorta la distancia (64.9 → 65.2) pero **el mercado
de tenis sigue por delante en ambos circuitos**; el tenis se mantiene en
modo analítico salvo cuando hay cuota real con EV positivo. El objetivo
«superar el 65 % en WTA» **sí se cumple en walk-forward (65.57 %)**.

### 2.4 Cobertura de cuotas (§1.4)

Cadena de resiliencia nueva en `alpha_finder._picks_tenis`:
1. **The Odds API** — torneos ATP/WTA activos, descubiertos dinámicamente
   (0 créditos si no hay ninguno; hoy 23-jul no había torneo en curso y la
   cadena degradó sola);
2. **Betexplorer** — `/next/tennis/`, ATP y WTA.

Verificado en ejecución real: eslabón 1 vacío → eslabón 2 devolvió 10
partidos → 2 picks de capa 1 y 1 de capa 2 publicados.

---

## 3. §2 — Europa League y Conference League

### 3.1 Datos (ESPN, con cadena de resiliencia ESPN → API-Football → CSV local)

| Competición | Partidos | Rango | Sede conocida |
|---|---|---|---|
| Europa League | 1,356 | 2019-08-01 → 2026-05-20 | **100 %** |
| Conference League | 729 | 2021-09-14 → 2026-05-27 | **100 %** |

### 3.2 Walk-forward (`run_wf_v35.py`, ventanas de 6 meses)

| Competición | Base | +urg | +cdi | +urg+cdi | ELO | Adoptado |
|---|---|---|---|---|---|---|
| **Europa League** | 50.31 / 1.1123 | 52.13 / 1.0019 | 51.79 / 0.9989 | **51.71 / 0.9959** | 50.61 | `extras+urg+cdi` (mejor log-loss entre las que pasan, criterio v26) |
| **Conference League** | **46.29 / 1.0646** | 46.29 / 1.0635 | 46.91 / 1.0670 | 46.91 / 1.0682 | 43.21 | `extras` (ver nota) |

**Nota Conference:** el CDI pasa la letra de la regla (+0.62 pp) pero con el
log-loss **plano** y solo ~330 partidos de validación repartidos en 4
ventanas, habiendo probado 4 variantes. Es el mismo patrón de comparaciones
múltiples que tumbó el ELO ataque/defensa en v33 → **no se adopta**; se
revisará con una temporada más. El modelo base ya bate al ELO por +3.1 pp.

**Umbral conservador (§2.3):** `conference_league` lleva
`umbral_confianza: 0.75` en config, por encima del 0.70 del resto de fútbol.

### 3.3 Integración

- `descargar_liga` soporta el formato `espn`; ambas competiciones entran en
  el bucle universal de `alpha_finder` sin código específico.
- **Verificado en el barrido real de hoy:** cobertura
  `{... 'europa_league': 1, 'conference_league': 3, ...}` — 0 nombres sin mapear.
- Claves de The Odds API añadidas (`soccer_uefa_europa_league`,
  `soccer_uefa_europa_conference_league`, existencia confirmada contra
  `/v4/sports?all=true`) con ventana de temporada jul-may (junio no gasta crédito).
- Vistas nuevas en el dashboard: 🇪🇺 Europa League y 🇪🇺 Conference League.

---

## 4. §3 — CDI en fútbol

`sedes_futbol.csv` (2,974 partidos con estadio, ciudad y país) se rellena
**sin una sola petición extra**: el mismo JSON de ESPN que trae los
resultados de Europa League, Conference y Champions trae la sede.
`timezones_futbol.json` guarda el mapa club → huso aprendido de esas sedes
(más `GEO_MLS` para la MLS y la longitud para Liga MX).

Dos formulaciones evaluadas juntas: `CDI_SEDE` (definición literal del spec:
huso de la sede − huso del visitante) y `CDI_VIAJE` (huso de la sede − huso
donde el visitante jugó su partido anterior si fue hace ≤10 días, la
formulación que se adoptó en la NBA en v30).

| Competición | Cobertura CDI | Base | +CDI | Veredicto |
|---|---|---|---|---|
| **Europa League** | 58.6 % | 50.31 / 1.1123 | 51.79 / 0.9989 | **ADOPTADO** (dentro de `extras+urg+cdi`) |
| **MLS** | 51.3 % | 47.61 / 1.0395 | 46.59 / 1.0390 | **ADOPTADO solo junto a urgencia**: `urg+cdi` = **48.61 / 1.0347** (mejora precisión Y log-loss); el CDI aislado NO pasa |
| Champions | 44.8 % | 59.67 / 0.9341 | 57.96 / 0.9364 | **descartado** (−1.7 pp) |
| Conference | 50.3 % | 46.29 / 1.0646 | 46.91 / 1.0670 | **descartado** (ver §3.2) |
| Liga MX | 11.9 % | 51.26 / 1.0235 | 51.12 / 1.0237 | **descartado** — casi toda la liga comparte huso (solo Tijuana difiere), no hay señal que extraer |

**Lectura:** la señal circadiana aparece donde hay viajes largos *reales*
(Europa League: de Lisboa a Almaty son 6 husos) y donde se combina con el
contexto clasificatorio (MLS). Donde el huso es casi constante (Liga MX) o
los equipos son de élite con logística óptima (Champions), no aporta.

---

## 5. §4 — Telegram

1. `.github/workflows/telegram_bot.yml` está en `main`, con `workflow_dispatch`
   y cron diario 10:00 UTC; usa `secrets.TELEGRAM_BOT_TOKEN` /
   `TELEGRAM_CHAT_ID` y nunca los imprime.
2. **Ejecución real de `bot_telegram.py` verificada de extremo a extremo**:
   construye el resumen del día (Pick del Día, capa 1, capa 2, escalera,
   aviso de EV extremo) con los datos reales de hoy y, sin token en el
   entorno, entra en modo seco sin enviar nada.
3. **Bug corregido:** el `print` del mensaje reventaba con
   `UnicodeEncodeError` en consolas cp1252 (Windows) **antes** de llegar al
   envío. Ahora degrada a escritura UTF-8 en bruto.
4. **Pendiente del usuario (no automatizable desde aquí):** pulsar «Run
   workflow» en la pestaña Actions y confirmar la recepción en el chat. Los
   Secrets viven en su cuenta de GitHub; desde esta sesión no se pueden leer
   ni configurar.

---

## 6. No regresión

- `test_simetria.py` (Mundial) → **TODO OK**, modelo del Mundial intacto (60.49 %).
- `test_match_parlay.py` → **TODO OK**.
- `smoke_v35.py` (AppTest sobre 9 vistas, incluidas las 3 nuevas) → **0 excepciones**.
- Ligas existentes: solo se reentrenó **MLS** (con mejora validada). El resto
  de artefactos no se tocan.
- Sin dependencias nuevas en `requirements.txt` (ESPN y The Odds API se
  consultan con `requests`, ya presente).

---

## 7. Entregables

`uefa_scraper.py` · `cdi_futbol.py` · `run_wf_v35.py` ·
`run_wf_tenis_v35.py` · `smoke_v35.py` · `engines/tennis_engine.py`
(ATP+WTA) · `league_engine.py` (formato `espn` + grupo `cdi`) ·
`config.py` · `odds_api.py` (tenis + claves UEFA) · `alpha_finder.py` ·
`dashboard_ui.py` · `pipeline_total.py` (paso de sedes) · `bot_telegram.py` ·
`historico_europa_league.csv` · `historico_conference_league.csv` ·
`sedes_futbol.csv` · `timezones_futbol.json` · `modelos/{europa_league,
conference_league,tennis_wta}/` · `resultados_v35.json` ·
`resultados_tenis_v35.json`.
