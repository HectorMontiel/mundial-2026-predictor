# Migración de hosting — diagnóstico, alternativas gratuitas y plan

Investigado el 2026-09-19 con datos verificados, no de memoria. Los límites de
los tiers gratuitos cambiaron mucho en 2026 y varias fuentes antiguas ya no
valen.

---

## 0. La conclusión primero

**El framework no es el problema. La arquitectura sí.**

La aplicación **recalcula todo dentro del render**, una vez por sesión y por
interacción. Mover eso de Streamlit a otro sitio sin arreglarlo traslada el
problema, no lo resuelve — y encima cuesta semanas.

Medido en esta máquina, sólo importando los módulos, sin cargar un modelo ni un
dataframe:

| qué se importa | RSS acumulado |
|---|---|
| Python pelado | 18 MB |
| + pandas / numpy | 80 MB |
| + xgboost / scikit-learn | 144 MB |
| + streamlit | 179 MB |
| + módulos del repo | **183 MB** |

183 MB **antes de empezar a trabajar**. Con el barrido cargado, los modelos de
la competición que se mire y los dataframes de histórico, la huella real sube a
varios cientos de MB más.

Y el techo actual de Streamlit Community Cloud es **1 GB de RAM y 1 núcleo**,
con un límite práctico de **~3 usuarios concurrentes**. Ahí está el crash: no
es un bug, es el techo.

---

## 1. Qué hay que arreglar, y se puede hacer sin migrar nada

La buena noticia es que **la mitad del trabajo ya está hecha y en producción**:
el proyecto ya precalcula cosas en GitHub Actions y las deja en el repositorio.

    predicciones_dia.json     la matriz de marcador del día
    mercado_dia.json          el tablero de la casa
    .cache_barrido.pkl        el barrido completo, cacheado
    modelos-latest            los pesos, en un GitHub Release

El paso que falta es llevarlo al final: que el **cálculo** viva entero en el
cron y que la **interfaz** sólo lea un JSON ya cocinado.

```
    HOY                              PROPUESTO
    ───                              ─────────
    usuario abre la app              cron nocturno (ya existe)
      └─ importa xgboost               └─ barrido + modelos + cuotas
      └─ carga modelos                 └─ escribe pronostico_dia.json
      └─ corre el barrido                      │
      └─ pinta                                 ▼
                                     usuario abre la app
    ~183 MB + modelos                  └─ lee el JSON
    por sesión                         └─ pinta
                                     ~80 MB, sin xgboost
```

**Qué se gana, medido con los números de arriba:** no importar
xgboost/scikit-learn quita 64 MB de golpe, y no cargar modelos ni recalcular el
barrido quita la mayor parte del resto. La huella por sesión baja a ~80-100 MB.
Con 1 GB eso son **diez sesiones**, no tres.

**Y esto arregla los crashes de HOY**, con una persona, sin cambiar de
proveedor y sin tocar el modelo. Es lo más barato que se puede hacer.

Las vistas que necesiten cálculo en vivo (la ficha completa de un partido, el
constructor de combinadas) se quedan detrás de un botón, que es donde ya están.

---

## 2. Las alternativas gratuitas, con los números de 2026

Verificado en septiembre de 2026. **Varias cambiaron este mismo año**, y la
mayoría a peor.

| plataforma | RAM | CPU | estado real en 2026 | ¿sirve? |
|---|---|---|---|---|
| **Streamlit Community Cloud** (actual) | 1 GB | 1 núcleo | ~3 usuarios concurrentes, duerme a los 15 min | es el techo que estorba |
| **Hugging Face Spaces** (CPU Basic) | **16 GB** | 2 vCPU | gratis, pero el SDK de Streamlit está **deprecado**: hay que ir por Docker. Hay debate abierto sobre restringir el SDK de Docker a cuentas de pago | **la mejor opción hoy, con riesgo de política** |
| **Oracle Cloud Always Free** | **12 GB** | 2 OCPU ARM | **recortado de 24 GB / 4 OCPU a 12 GB / 2 OCPU el 15-jun-2026, sin anuncio**. Instancias por encima del nuevo límite se terminaron el 18-ago | potente, pero hay que administrar una VM y la capacidad ARM falla en varias regiones |
| **Google Cloud Run** | configurable | configurable | 2 M peticiones, 180.000 vCPU-s y 360.000 GiB-s al mes | **sí, y con holgura** (ver cuenta abajo) |
| **Render** free | 512 MB | compartido | la mitad que Streamlit | no |
| **Koyeb** | 512 MB | 1 vCPU | **tier gratuito cerrado a nuevos usuarios** tras la compra por Mistral | no |
| **Fly.io** | — | — | **ya no hay tier gratuito** para cuentas nuevas: prueba de 2 VM-hora o 7 días | no |
| **GitHub Pages / Cloudflare Pages** | — | — | estático puro, gratis y sin límite práctico para 3 personas | **sí, si la UI es estática** |

### La cuenta de Cloud Run, que es la que sorprende

Con el free tier de 360.000 GiB-s y 180.000 vCPU-s al mes, y suponiendo un
contenedor de 1 GiB:

    3 usuarios × 20 interacciones/día × 33 s = 1.980 s/día = ~59.000 s/mes

Eso son ~59.000 vCPU-s y ~59.000 GiB-s: **cabe con margen de tres veces**,
incluso con la aplicación pesada de hoy y sin partirla. Y escala a cero, así
que las horas muertas no cuentan.

---

## 3. Recomendación

**Por orden, y el orden importa: lo primero no es migrar.**

### Paso 1 — partir cálculo y servicio (1-2 tandas, sin cambiar de host)

Extender el cron que ya existe para que escriba el día entero cocinado, y hacer
que la vista principal lo lea. Arregla los crashes de hoy, quita 64 MB de
dependencias de la ruta caliente y **hace que cualquier host de la tabla valga**.

Es también la única parte que hay que hacer sí o sí: sin ella, cualquier
migración hereda el mismo problema con otro logo.

### Paso 2 — mover a Hugging Face Spaces (Docker)

16 GB contra 1 GB es dejar de pensar en memoria. El repositorio ya tiene
`.devcontainer`, así que el Dockerfile es trabajo menor. Streamlit sigue
funcionando ahí — lo que cambia es que se declara por Docker y no por el SDK
deprecado, así que **el código de la aplicación no se toca**.

El riesgo está declarado y hay que decirlo: hay debate abierto sobre restringir
el SDK de Docker a cuentas de pago. Por eso el paso 1 va antes — si HF cierra
la puerta, con la app partida cualquier alternativa de la tabla sirve.

### Paso 3 — sólo si hace falta: Cloud Run

Si HF cambia las reglas o si la aplicación crece, Cloud Run es el plan B con
números ya comprobados arriba. Pide tarjeta y un Dockerfile, que es lo mismo
que el paso 2, así que el trabajo se reaprovecha entero.

### Lo que NO recomiendo, y por qué

- **Reescribir la interfaz** (FastAPI + React, Gradio, Dash). Son 9.175 líneas
  sólo en `dashboard_ui.py` y 362 módulos detrás. El problema medido es la
  RAM por sesión, no el framework: reescribir cuesta meses y no arregla lo
  que duele.
- **Oracle Cloud como primera opción.** 12 GB gratis es mucho, pero es una VM
  que hay que administrar, parchear y vigilar — y acaban de recortar el tier a
  la mitad sin avisar a nadie. Para tres personas, el coste de operación no
  compensa.
- **Render y Koyeb.** 512 MB es la mitad de lo que ya se queda corto.

---

## 4. Qué del proyecto encaja y qué hay que tocar

De la auditoría (`AUDITORIA_v212.md`): 362 módulos, 135.267 líneas, Python
3.12, pandas + xgboost + scikit-learn, modelos fuera del repositorio en un
GitHub Release.

| pieza | ¿sobrevive a la migración? |
|---|---|
| Los 362 módulos de lógica | **sí, intactos**: son Python puro |
| `modelos_remotos` (pesos desde el Release) | **sí**, y encaja mejor: el contenedor no los lleva dentro |
| GitHub Actions (cron, reentreno, cuotas) | **sí, sin tocar**: son independientes del host |
| Los scrapers (FotMob, ESPN, Pinnacle, Wikidata) | **sí**, salvo que el host bloquee salida — ninguno de los candidatos lo hace |
| `dashboard_ui.py` y las vistas | **sí en HF/Cloud Run/Oracle**; habría que reescribir sólo si se fuera a estático puro |
| `.cache_barrido.pkl` y los JSON del día | **sí**, y pasan a ser la pieza central en vez de una caché |
| Ficheros que se escriben en caliente (`pronosticos_emitidos.json`, `feedback_humano.json`, `archivo_contexto.json`) | **atención**: en contenedores efímeros el disco se pierde al reiniciar. Hay que commitearlos desde el cron —como ya se hace con las calibraciones— o darles almacenamiento externo |

**El único punto que exige diseño nuevo es el último**, y ya hay precedente en
el repositorio: el workflow de recalibración commitea sus artefactos. El mismo
patrón sirve.

---

## Fuentes

- [Streamlit Community Cloud — límites del plan gratuito](https://discuss.streamlit.io/t/free-tier-limits/)
- [Hugging Face — Spaces Overview](https://huggingface.co/docs/hub/en/spaces-overview)
- [Hugging Face Forums — debate sobre CPU Basic y los SDK](https://discuss.huggingface.co/t/official-community-complaint-revert-free-cpu-basic-spaces-and-remove-anti-developer-sdk-restrictions/177703)
- [InfoQ — Oracle recorta el free tier de Ampere A1 sin anunciarlo](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
- [Oracle — Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Google Cloud Run — pricing y free tier](https://cloud.google.com/run/pricing)
- [Render — plataformas con tier gratuito real en 2026](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026)
- [Comparativa de plataformas gratuitas de despliegue 2026](https://snapdeploy.dev/blog/free-cloud-deployment-platforms-2026-comparison)
