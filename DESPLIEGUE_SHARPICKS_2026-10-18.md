# Informe de despliegue de SharPicks — 18 de octubre de 2026

## Resultado ejecutivo

**Estado:** mejoras principales desplegadas y comprobadas; auditoría total aún abierta por pruebas de negocio y reconstrucción de migraciones históricas.

- **Sitio publicado:** https://sharpicks.pages.dev/
- **Commit de la publicación:** `68d8f139834fce15a6867a5bad6ff1912bf05b02`
- **PR integrada:** [PR #2](https://github.com/HectorMontiel/mundial-2026-predictor/pull/2), fusionada el 18-oct-2026 a las 16:41:21 UTC.
- **Deploy web:** [GitHub Actions run 39146143725](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39146143725) — éxito, incluyó validación antes de publicar y paso de Cloudflare Pages en verde.
- **Smoke test de producción:** [run 39147099500](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39147099500) — éxito: página 200, `cuenta.js` servido desde producción y usando la Edge Function nueva, petición inválida respondió 400 como se esperaba, CORS correcto, sin crear comentario.
- **CI de regresión:** [tests seguros run 39145762192](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39145762192) y [validador sin despliegue run 39145762105](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39145762105) — ambos en verde.
- **Edge Functions:** `comentario`, `vip`, `stripe`, `mp-webhook` y `stripe-webhook` se compararon byte por byte contra sus archivos de `main`; las cinco fuentes coinciden.
- **Migraciones aplicadas a Supabase:** `v403_finanzas_rpc_auth`, `v402_bughunter_hardening`, `v404_precios_cuota_canonico` y `v405_comentarios_solo_edge`.

La mejora es funcional y de seguridad, no una medición de rendimiento en milisegundos. No se inventa un porcentaje de “mejora global”: los resultados comprobados se enumeran por control y prueba.

## Cambios desplegados y por qué

### 1. Privacidad del resumen financiero — SHP-018
Antes, `public.monthly_category_summary(p_user_id, p_year, p_month)` era `SECURITY DEFINER`, se podía ejecutar anónimamente y no vinculaba el ID consultado con la identidad autenticada.

**Cambio:** ahora exige `auth.uid() = p_user_id` o una llamada de `service_role`, y se revocó la ejecución a `public/anon`.

**Validación posterior:** `anon_execute=false`, `authenticated_execute=true`, guarda de propiedad presente. También se comprobó dentro de una transacción que una sesión con otra identidad no obtenga filas para el ID ajeno; la prueba se cerró con `ROLLBACK`. No se leyeron ni exportaron movimientos financieros.

### 2. Perfiles y RPC de cuenta
**Cambios:** escritura directa de perfiles revocada; el cliente ya no puede insertar perfiles y se restringe qué columnas puede actualizar. Las RPC de desbloqueo y enlace VIP no están disponibles a `anon`; quedan para usuario autenticado cuando corresponde. La creación de VIP de pago único usa una RPC idempotente/transaccional. La reserva de fundador usa un bloqueo transaccional para evitar que dos checkouts asignen simultáneamente la misma plaza.

**Validación posterior:** las RPC `procesar_vip_unico` y `reservar_lugar_fundador` existen; `anon` no puede ejecutar `enlace_vip` ni `desbloquear`; el acceso al enlace de Telegram VIP tiene una bandera separada `telegram_vip_abierto`.

**Límite de prueba:** no se hizo un cobro real ni se ejecutó una transacción con las pasarelas de producción. Las rutas de pago se validaron con CI y revisión de fuente; la confirmación monetaria E2E requiere transacción de prueba del proveedor o staging.

### 3. Comentarios públicos
**Cambios:** Edge Function `comentario` con validación del servidor, comprobación opcional de sesión, validación de campos, límite de cinco envíos por huella/hash en una hora y CORS limitado al origen de SharPicks. El frontend usa `fetch(FN + 'comentario')`, no un INSERT directo a PostgREST.

**Secuencia aplicada de forma segura:**
1. Desplegar la Edge Function.
2. Publicar la interfaz nueva y confirmar el despliegue de Cloudflare.
3. Ejecutar el smoke test desde GitHub Actions.
4. Aplicar `v405_comentarios_solo_edge.sql` para revocar la inserción directa antigua.

**Validación posterior a v405:** `anon INSERT=false`, `authenticated INSERT=false`, `service_role INSERT=true`; RPC `registrar_comentario` y tabla `comentarios_rate_limit` presentes.

**Límite de prueba:** el smoke test usa un body deliberadamente inválido para demostrar conectividad/configuración sin crear comentarios ni enviar correos. No se envió un comentario de usuario real para no generar efectos secundarios en la base ni en el correo.

### 4. Precio por cuota y política de picks premium
En producción ya existía la política premium que da lectura pública sólo para picks liquidados (`verde`, `roja`, `nula`) y la función de precio consultaba `precios_cuota`. La discrepancia estaba en archivos SQL históricos/versionados.

**Cambio:** `v404_precios_cuota_canonico.sql` vuelve reproducible la tabla y su función sin cambiar las bandas ya configuradas; el SQL de instalación también se alinea con la regla de picks liquidados. No se atribuye a producción un fallo que no se observó en la política/precio efectivos.

**Precios observados:** 1.00–1.30 = 5 monedas; 1.30–1.60 = 8; 1.60–2.00 = 12; 2.00–3.00 = 18; 3.00–99.00 = 25. En una prueba de transacción con rollback: cuota 1.04 premium = 5; error de cuota 3.50 = 25; pick normal no premium = 0.

### 5. Fechas, partidos en vivo y estados de error
- El parser de fechas cubre ISO con `Z`, offset `-06:00`, offset `+02:00`, offset `-0600`, fecha simple, formato histórico con espacio, cadena inválida y `null`.
- El feed en vivo rota los grupos, evitando que sólo se refresquen siempre los primeros 40 partidos.
- Los errores de consulta de picks/combinadas/historial tienen rutas de error separadas de un resultado vacío; el cálculo de porcentajes evita divisiones por cero.
- El exportador deja de presentar una publicación correcta si falla una escritura crítica de picks premium/combinadas; ahora propaga el error y bloquea el deploy cuando no hay sincronización consistente.

**Validación:** CI de JavaScript/Python y pruebas de regresión v402 en verde. El smoke test comprueba la página desplegada. No se midió el tiempo de carga antes/después bajo una carga representativa, así que no hay afirmación de una mejora de velocidad.

### 6. Calidad de despliegue
El workflow de sitio ahora corre pruebas antes de exportar/publicar, y publica resumen de integraciones auxiliares. Añadí un smoke test de producción independiente, que verifica la página pública y la Edge Function sin crear datos.

## Registro de pruebas

| Control | Resultado |
|---|---|
| JavaScript: sintaxis de `fechas.js`, `app.js`, `cuenta.js` | PASS |
| Parser ISO y guardas de frontend | PASS |
| Exportador: fallo de credenciales premium | PASS |
| Exportador: fallo al insertar texto premium | PASS |
| Exportador: retry individual fallido | PASS |
| Combinadas: lista vacía conserva los registros | PASS |
| Combinadas: error al leer IA bloquea sincronización | PASS |
| Pruebas existentes `test_v383.py`, `test_v389.py`, `test_v390.py`, `test_v394.py`, `test_v395.py`, `test_v396.py`, `test_v400.py` | PASS en la ejecución de CI |
| Fuente de cinco Edge Functions contra `main` | Coincidencia exacta |
| Smoke de producción: homepage y cuenta | HTTP 200 |
| Smoke de producción: comentario inválido | HTTP 400 esperado, CORS correcto, sin inserción |
| Supabase: política de comentarios tras v405 | PASS: sólo service_role puede insertar |
| Supabase: privacidad de resumen financiero | PASS: anon no ejecuta; guarda de propiedad activa |
| Transacción de comprobación SQL | PASS con `ROLLBACK`, sin persistir los cambios de la prueba |

## Pendientes que no deben confundirse con un despliegue fallido

1. **SHP-003 / SHP-006 — reconstrucción completa de instalación nueva.** El repositorio conserva SQL/bootstrap histórico. El encabezado advierte que no se debe volver a ejecutar sobre una base ya migrada. Aún falta construir y probar un camino completo y único para inicializar desde cero una base nueva, sin que scripts antiguos reemplacen funciones de versiones posteriores.
2. **Pagos E2E con proveedor sandbox.** No se hicieron transacciones reales de Stripe o Mercado Pago. Hace falta una comprobación sandbox de pago duplicado, reintento webhook, fallo temporal al escribir en DB y concesión/expiración de VIP.
3. **Comentario válido con correo.** La ruta fue comprobada por un smoke no destructivo (petición inválida). Hace falta probar un comentario sintético en staging y comprobar el correo sólo allí.
4. **Auditoría estática completa del repositorio.** Se revisaron archivos de web/API y pruebas relevantes, pero no se leyó ni ejecutó cada archivo del repositorio; no se declara “todo el repositorio certificado”.
5. **Medición de rendimiento de interfaz.** No hay benchmark representativo de carga anterior/posterior; las mejoras validadas aquí son de corrección, manejo de errores, seguridad y confiabilidad.

## Reglas para el siguiente agente (Claude/ChatGPT)

Antes de continuar, leer `AUDITORIA_BUGHUNTER_SHARPICKS_2026-10-18.md` y `CONTINUIDAD_AUDITORIA_SHARPICKS.md`. No reabrir ni volver a aplicar v402–v405 en producción a ciegas: ya están registradas como migraciones aplicadas. Verificar la versión actual de `main` y los logs más recientes antes de reintentar cualquier acción.


## Pruebas transaccionales adicionales — finalización del 18-oct-2026

Además de los workflows, se ejecutaron tres comprobaciones directas en Supabase dentro de transacciones que terminaron en `ROLLBACK`; no se dejaron suscripciones, modificaciones de perfil, reservas ni comentarios sintéticos persistidos:

- **Pago VIP único/idempotencia:** la primera llamada a `procesar_vip_unico` insertó una sola suscripción de prueba; la segunda con el mismo ID devolvió el resultado de duplicado; `plan_hasta` no volvió a extenderse y el conteo de filas quedó en uno durante la prueba. PASS.
- **Reserva fundador:** dos llamadas para la misma cuenta sintética/reversible produjeron una sola reserva pendiente activa; no se duplicó la plaza. PASS.
- **Límite de comentarios:** cinco llamadas sintéticas se aceptaron y la sexta devolvió `rate_limit`; la transacción se revirtió. PASS.

Estas pruebas validan la lógica PostgreSQL desplegada, no sustituyen una compra real/sandbox ni validan la entrega del webhook por Stripe/Mercado Pago. El smoke HTTP de producción sigue siendo no destructivo: comprueba el endpoint con un body inválido y no crea comentarios.
