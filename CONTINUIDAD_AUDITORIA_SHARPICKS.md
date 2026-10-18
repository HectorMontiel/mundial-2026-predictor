# Continuidad compartida — auditoría de SharPicks

**Última actualización:** 2026-10-18 (CDMX)  
**Propietario:** HMREY / Héctor Montiel  
**Repositorio canónico:** https://github.com/HectorMontiel/mundial-2026-predictor  
**Producción web:** https://sharpicks.pages.dev/  
**Registro maestro:** [AUDITORIA_BUGHUNTER_SHARPICKS_2026-10-18.md](./AUDITORIA_BUGHUNTER_SHARPICKS_2026-10-18.md)  
**Rama de auditoría/trabajo:** `audit/sharpicks-bughunter-2026-10-18`  
**Política:** NO hacer cambios directos a `main` mientras falte alguna validación crítica. Abrir PR, ejecutar las pruebas, revisar el diff y verificar dependencias externas antes de fusionar.

## Instrucciones para Claude y ChatGPT

Este archivo y el informe maestro son la memoria compartida del trabajo. Antes de trabajar:
1. Lee este archivo y el informe maestro completo.
2. Revisa el estado más reciente de la rama, `main`, los commits del bot y los checks de GitHub Actions; los bots escriben a `main` de forma recurrente.
3. No des por vigente un número de línea si el archivo cambió: vuelve a consultar la fuente y actualiza el enlace al commit/archivo.
4. Usa los mismos IDs `SHP-###`. No dupliques hallazgos; añade evidencia nueva al existente.
5. No marques nada como resuelto hasta que la prueba de aceptación correspondiente se haya ejecutado y su resultado conste en el informe.
6. Distingue explícitamente: `CONFIRMADO EN CÓDIGO`, `REPRODUCIDO EN PRUEBA`, `VALIDADO EN STAGING`, `VALIDADO EN PRODUCCIÓN`. No son equivalentes.
7. No publicar secretos, claves, tokens de pago, correos de clientes ni payloads de webhook completos. Las claves del cliente Supabase con prefijo `sb_publishable_` son de naturaleza pública, pero no deben confundirse con `service_role` ni con secretos.
8. No modificar ni restaurar artefactos de datos del bot como efecto lateral. Si hace falta una prueba local, usa datos sintéticos y restaura los artefactos antes del commit.
9. Antes de tocar `main`: revisar commits recientes; ejecutar `git pull --rebase origin main` si se trabaja con el clon local y resolver artefactos de bot combinando, nunca pisando los datos automáticos.
10. Si una corrección necesita desplegar SQL o una Edge Function de Supabase, no digas que está en producción hasta tener evidencia de la migración y de la función desplegada.

## Contexto del proyecto

- SharPicks es un frontend estático en `web/`; la publicación se coordina con `.github/workflows/sitio_web.yml`.
- La lógica deportiva y precálculo viven en Python y GitHub Actions; la web consume Supabase y/o `web/datos/hoy.json`, y consulta ESPN para el marcador/estadísticas en directo.
- Supabase implementa Auth, RLS, monedas, accesos premium, combinadas, suscripciones y comentarios.
- Los pagos se gestionan por Mercado Pago y Stripe, con funciones en `supabase/functions/`.
- El antiguo `app.py` / `dashboard_ui.py` de Streamlit sigue en el repositorio; no eliminarlo sin un plan de retirada y una verificación de producción por parte del propietario.

## Estado inicial de los hallazgos (no equivale a que se hayan reparado)

| ID | Prioridad | Tema | Estado |
|---|---|---|---|
| SHP-001 | P1 | Webhooks pueden contestar éxito pese a fallos de escritura | Abierto |
| SHP-002 | P1 | Activación de VIP único no atómica con la idempotencia | Abierto |
| SHP-003 | P1/P2 | Migraciones de pago no totalmente reproducibles desde SQL versionado | Abierto |
| SHP-004 | P1 condicionado | INSERT directo a perfiles / columnas sensibles | Abierto; comprobar grants efectivos |
| SHP-005 | P1 comercial | La bandera `premium_con_cuenta` también abre el enlace VIP | Abierto |
| SHP-006 | P1/P2 | Script SQL histórico puede degradar funciones recientes | Abierto |
| SHP-007 | P2 | Reserva de precio fundador no atómica | Abierto |
| SHP-008 | P2 | Parser de fecha no reconoce offset UTC negativo | Abierto |
| SHP-009 | P2 | Sólo se consulta el primer bloque de 40 partidos en vivo | Abierto |
| SHP-010 | P2 | Fallo de lectura se presenta como lista vacía | Abierto |
| SHP-011 | P2 | El porcentaje puede mostrar NaN % | Abierto |
| SHP-012 | P2 | Workflow puede verse verde con fallos opcionales y sin tests frontend | Abierto |
| SHP-013 | P2 | Aviso de privacidad incompleto respecto a métodos/proveedores | Abierto; requiere datos legales del responsable |
| SHP-014 | P2 | Comentarios públicos sin límite de frecuencia servidor | Abierto |

## Orden de corrección recomendado

### Bloque A — integridad y seguridad (antes de activar o expandir cobros)
- SHP-001 y SHP-002: diseñar el procesamiento de webhook para que sea reintentable e idempotente de extremo a extremo; implementar acreditación/activación de pago en una RPC transaccional.
- SHP-003: comprobar que cada función, tabla e índice que usa la operación comercial se crea desde migraciones SQL versionadas; no reconstruir funciones a ciegas desde comentarios.
- SHP-004: revocar INSERT de `anon`/ `authenticated` en `perfiles`; mantener solo las operaciones de perfil explícitamente permitidas; verificar en staging y producción.
- SHP-005: separar configuración de acceso a picks premium de configuración de acceso a Telegram VIP.
- SHP-006: consolidar las definiciones de esquema, marcar scripts históricos como no volver a ejecutar y prevenir degradaciones.
- SHP-007: definir con el propietario si un puesto fundador se libera o queda reservado cuando cancela y hacer reserva atómica.

### Bloque B — fiabilidad visible
- SHP-008: parser ISO compatible con `Z`, offsets positivos/negativos y fechas sin zona.
- SHP-009: agenda rotatoria con un límite por pasada que garantice que todos los partidos elegibles se consultan.
- SHP-010: estados separados `cargando`, `vacío`, `error` para picks, combinadas, historial y comentarios.
- SHP-011: porcentajes protegidos contra denominador cero.
- SHP-012: tests obligatorios previos al despliegue; fallos opcionales visibles en summary/alerta, y fallo de publicación canónica de Cloudflare no silencioso.

### Bloque C — protección y cumplimiento
- SHP-013: actualizar privacidad con datos reales de responsable y proveedores; no inventar nombre legal, domicilio, correo o plazos. Requiere validación del propietario y revisión legal.
- SHP-014: endpoint server-side con límite de frecuencia y validación antiabuso para comentarios; la página no debe poder leer comentarios de otros usuarios.

## Evidencia y validaciones

- La ejecución de “Sitio web” que se comprobó, run [39102584649](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39102584649), finalizó correctamente y el paso de Cloudflare Pages fue exitoso en esa ejecución.
- Esta señal solo valida ese despliegue concreto; no certifica RLS, pagos, navegación ni contenido real de producción.
- El navegador/herramienta de lectura usada durante esta sesión no pudo recuperar `https://sharpicks.pages.dev/` (error de caché/conectividad de herramienta). No debe registrarse como fallo comprobado del sitio ni como validación del mismo.
- La auditoría es de código estático; los hallazgos dependientes de secretos, permisos reales, configuración de Supabase, proveedor de pagos o cuenta real no se pueden dar por reproducidos sin pruebas controladas.

## Registro de cambios de esta auditoría

| Fecha CDMX | Cambio | Evidencia |
|---|---|---|
| 2026-10-18 | Creación de la rama de auditoría y del informe maestro | Ver commits de `audit/sharpicks-bughunter-2026-10-18` |
| 2026-10-18 | Revisión estática de frontend, SQL, Edge Functions y workflow del sitio | Evidencia enlazada en el informe maestro |

## Formato obligatorio al resolver un hallazgo

Añade un registro en el informe maestro:
- ID y descripción.
- Commit/PR con el cambio.
- Archivos afectados.
- Prueba exacta ejecutada y resultado (comando o enlace a CI).
- Validación en staging (si aplica).
- Validación en producción (si aplica).
- Riesgos restantes.
- Estado: `ABIERTO`, `CORREGIDO EN CÓDIGO`, `PASÓ TESTS`, `VALIDADO EN STAGING`, `VALIDADO EN PRODUCCIÓN`, o `BLOQUEADO POR ACCESO`.

Nunca usar simplemente “listo” como evidencia.


## Inventario y revisión cruzada adicional — 18-oct-2026

- Un árbol recursivo de la rama principal arrojó 1.733 paths y 97 archivos de prueba con nombre tipo test*.py; 62 paths están directamente relacionados con la web, hosting, funciones Supabase y workflows.
- Leídos parcialmente para revisar cobertura: test_v379.py, test_v383.py, test_v389.py, test_v390.py, test_v394.py, test_v395.py, test_v396.py y test_v400.py. Son en gran parte pruebas de estructura/código fuente; no equivalen a validación de Postgres real, APIs de pago o navegador.
- Se agregaron tres hallazgos nuevos al informe maestro: SHP-015 (RLS de picks premium permite lectura desde el inicio del partido pese a que la nota de v389 dice al terminar), SHP-016 (precio de la interfaz calculado por precios_cuota, pero la función SQL canónica public.precio_pick usa ajustes por categoría y no contempla tipo error), SHP-017 (fallos al subir datos premium/combinadas pueden quedar como warning mientras exportar_web.py devuelve éxito).
- Estos hallazgos están confirmados como discrepancias en el código fuente; el estado efectivo de Supabase y la intención de negocio donde los documentos se contradicen aún necesitan validación antes de corregir.
- Último commit de main observado después de crear la rama: 1e077067cf18afb2ad548c9fa859908200a7bd48 (precálculo automático del 18-oct-2026 a las 06:55:32 UTC). Antes de realizar cambios funcionales, volver a consultar main y rebasar con cuidado.
- El sitio sharpicks.pages.dev no pudo recuperarse con el navegador disponible en esta sesión; no confundir esa limitación de herramienta con un fallo de producción.
- Aún no se han ejecutado aquí los 97 tests, no se ha leído cada archivo del repositorio y no hay verificación directa de la base desplegada. No anunciar la auditoría como completa.
