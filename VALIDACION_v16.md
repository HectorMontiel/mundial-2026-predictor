# VALIDACIÓN v16 — Parlay dinámico + ciclo de experimentos de precisión (2026-07-12)

Regla de oro extendida: toda fuente nueva debe ser legal, gratuita y
reproducible en Streamlit Cloud. Criterio de adopción de experimentos:
precisión **+0.3 pp o más** sin empeorar el log-loss más de 0.01 (o mejora en
ambas + mejor calibración en picks de confianza >70 %), confirmado después
sobre la base acumulada.

---

## Parte A — Parlay por partido DINÁMICO (2-8 picks)

Problema reportado: los tres perfiles devolvían el mismo parlay y el slider
empezaba en 4.

Cambios en `match_parlay.py` / `dashboard_ui.py`:

- **Perfiles con filosofías distintas** (no solo umbrales):
  - 🛡️ Conservador: umbral **70 %**, ordena por probabilidad; **nunca relaja
    el umbral** — si no alcanzan los mercados devuelve MENOS picks y lo avisa.
  - ⚖️ Medio: umbral 55 % (suelo 50 % si falta), greedy por
    `prob × cuota^0.3` — equivale a maximizar
    `prob_conjunta × cuota_combinada^0.3`.
  - 🚀 Agresivo: umbral **30 %**, ordena por cuota (o por EV con cuotas
    reales): marcadores exactos, hándicaps largos, over 3.5…
- **Slider 2-8** (antes 4-8); un parlay de 2 picks es válido.
- **Una sola línea por mercado**: los grupos de over/under colapsan por stat —
  nunca "más de 6.5 córners" + "más de 7.5 córners" en el mismo parlay
  (aplica igual a goles, tarjetas y totales por equipo).

Verificación (`test_match_parlay.py`, MEX-ECU y Arsenal-Aston Villa):
los perfiles generan parlays DISTINTOS; el agresivo paga más
(120-350× vs ~2× del conservador) y el conservador es más probable
(0.39-0.46 vs 0.002-0.007); cero parejas incompatibles; una selección por
grupo; prob conjunta = producto × haircut^parejas. AppTest en Mundial y
Serie A: 0 excepciones. Parlay multi-partido del fixture intacto.

---

## Parte B — Ciclo de experimentos de precisión del Mundial

Benchmark: split temporal train < 2024-01-01, validación 2024-2026 (2,592
partidos reales). Línea base v15: **59.30 % / 0.9005** (conf>70 %: 80.2 %).
Motor de experimentos: `run_experiments.py` (reproducible, un solo comando).

### Fase 1 — screening sobre la base 2010 (12 ideas, 10 ejecutadas)

| Experimento | Acc | Δacc (pp) | Log-loss | Δll | Conf>70 % | Veredicto |
|---|---|---|---|---|---|---|
| baseline v15 | 59.30 % | — | 0.9005 | — | 0.802 | referencia |
| **histórico 1990** (idea 9) | **60.42 %** | **+1.12** | **0.8704** | **−0.030** | 0.811 | ✅ pasa |
| stacking logístico (idea 7) | 59.94 % | +0.64 | 0.8878 | −0.013 | 0.789 | ✅ pasa |
| H2H rico (idea 2) | 59.83 % | +0.53 | 0.9103 | +0.010 | 0.800 | ⚠️ borderline |
| importancia torneo (idea 5) | 59.79 % | +0.49 | 0.8989 | −0.002 | 0.796 | ✅ pasa |
| extras combinadas (2+4+5+10) | 59.71 % | +0.41 | 0.8955 | −0.005 | 0.802 | ✅ pasa |
| blend Poisson 30 % (idea 12b) | 59.64 % | +0.34 | 0.8869 | −0.014 | 0.798 | ✅ pasa |
| Poisson→1X2 puro (idea 12) | 59.56 % | +0.26 | 0.8908 | −0.010 | 0.786 | ✗ bajo umbral |
| calibración sigmoid (idea 8) | 59.52 % | +0.22 | 0.8938 | −0.007 | **0.814** | ✗ bajo umbral |
| forma exponencial (idea 1) | 59.52 % | +0.22 | 0.8880 | −0.013 | 0.801 | ✗ bajo umbral |
| descanso (idea 4) | 59.30 % | +0.00 | 0.8997 | −0.001 | 0.806 | ✗ sin efecto |
| rachas (idea 10) | 59.26 % | −0.04 | 0.9014 | +0.001 | 0.805 | ✗ descartada |

No ejecutadas: idea 3 (alineaciones — sin histórico leak-free, imposible de
backtestear), idea 6 (árbitro en 1X2 — el histórico Kaggle no trae árbitro),
idea 8 beta-cal (requiere dependencia nueva `betacal`; se probó sigmoid como
proxy), idea 11 (el aumento sintético ya existe y fue optimizado en v10).

### Fase 2 — ganadores re-testeados SOBRE la base 1990 (efectos no aditivos)

Dataset ampliado: **32,384 partidos** (1990-2026) vs 15,920 (2010-2026).

| Candidato | Acc | Log-loss | Conf>70 % |
|---|---|---|---|
| **1990 solo** | **60.42 %** | **0.8704** | **0.811** |
| 1990 + stacking | 60.39 % | 0.8745 | 0.793 |
| 1990 + stacking + importancia | 60.39 % | 0.8733 | 0.795 |
| 1990 + blend Poisson | 60.24 % | 0.8710 | 0.807 |
| 1990 + importancia | 60.08 % | 0.8817 | 0.802 |
| 1990 + extras combinadas | 60.01 % | 0.8699 | 0.808 |
| 1990 + Poisson puro | 59.93 % | 0.8778 | 0.796 |

**Conclusión honesta**: los datos adicionales absorben TODO lo que las demás
ideas aportaban sobre la base corta. Ninguna combinación supera a "1990 solo".

### Decisión adoptada

**Solo se adopta el histórico ampliado a 1990** (`data_fetcher.py`:
`FECHA_INICIO_HISTORICO = '1990-01-01'`):

- La mayor mejora de todo el ciclo: **59.30 → 60.42 % (+1.12 pp)** y log-loss
  **0.9005 → 0.8704 (−0.030)**, cruzando por primera vez la barrera del 60 %.
- Cero features nuevas, cero cambios en inferencia, cero dependencias nuevas:
  el mismo pipeline con más pasado real de Kaggle.
- Stacking, importancia, blend Poisson y compañía quedan DOCUMENTADOS y
  descartados: sobre la base 1990 no aportan (o empeoran la calibración de
  alta confianza, como el stacking: 0.811 → 0.793).

### Walk-forward de confirmación (base 1990, ventanas de 6 meses 2024-2026)

| Ventana | n | Precisión | Log-loss |
|---|---|---|---|
| 2024-01 → 2024-07 | 588 | 59.0 % | 0.895 |
| 2024-07 → 2025-01 | 643 | 58.2 % | 0.926 |
| 2025-01 → 2025-07 | 407 | 60.7 % | 0.839 |
| 2025-07 → 2026-01 | 592 | 62.8 % | 0.810 |
| 2026-01 → 2026-07 | 389 | 59.4 % | 0.879 |
| **Media** | 2,619 | **60.0 %** | **0.870** |

vs v13/v15 (walk-forward 59.5 % / 0.908): **+0.5 pp de precisión y −0.038 de
log-loss** confirmados fuera de muestra. Split estándar final del modelo
desplegado: **60.4 % / 0.871** (línea base "siempre el favorito ELO": 59.8 %).

Nota de auditoría: el primer rebuild con ESPN duplicó 4 partidos de DR Congo
(displayName real de ESPN es "Congo DR" con espacio y el alias usaba guion);
se corrigió el alias en `live_worldcup.py`, se limpiaron las filas y el
modelo final se entrenó con el dataset verificado (32,386 partidos, 0
duplicados por par de equipos).

---

## Objetivo estricto (62 % / 0.85)

Sigue sin alcanzarse y se reporta con transparencia: 60.4 % / 0.870 queda a
~1.6 pp del objetivo. El techo empírico del 1X2 internacional ronda el
60-65 %; las vías restantes más prometedoras (alineaciones confirmadas en
vivo, cuotas de mercado como feature) no son backtesteables con fuentes
gratuitas hoy y quedan como candidatas para v17.
