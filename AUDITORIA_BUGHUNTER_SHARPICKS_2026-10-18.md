# Auditoría Bug Hunter — SharPicks

**Fecha:** 18 de octubre de 2026 (CDMX)  
**Repositorio auditado:** [HectorMontiel/mundial-2026-predictor](https://github.com/HectorMontiel/mundial-2026-predictor)  
**Rama base:** `main` en `a86a9d5c7e05fa5dfdefe6d225e9a64704dbe5c4` al iniciar esta auditoría.  
**Sitio:** https://sharpicks.pages.dev/  
**Estado global:** **NO APROBADO todavía para declarar la auditoría completa ni para dar por validados los cobros.** Se detectaron riesgos en pagos/seguridad y defectos funcionales reproducibles desde el código.  
**Alcance real:** revisión estática de los archivos fuente y metadatos de GitHub Actions. No se pudo cargar el sitio publicado en el navegador de esta sesión (el host devolvió “Failed to fetch / Cache miss”); tampoco se dispone de acceso a la base Supabase de producción, a sus secretos ni a sesiones de usuario reales. Por tanto, los problemas de código señalados tienen evidencia estática, pero los efectos en producción que dependen de configuración/datos deben validarse en entorno controlado. No se ejecutaron aquí los tests locales de Python/Node ni un flujo real de pago.

## Resumen ejecutivo

El frontend estático se publica desde `web/` mediante `.github/workflows/sitio_web.yml`. La última ejecución del workflow de sitio que se inspeccionó terminó en verde y registró exitoso el paso Cloudflare Pages: [run 39102584649](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39102584649). Eso valida ese despliegue concreto, **no** todas las funciones, la seguridad de Supabase ni la integridad de pagos.

### Prioridad de arreglos

1. **Antes de cobrar o vender picks premium:** SHP-001, SHP-002, SHP-003, SHP-004 y SHP-005.
2. **Antes de dar la web por estable:** SHP-006, SHP-007, SHP-008 y SHP-009.
3. **Calidad, operación y confianza:** SHP-010, SHP-011 y SHP-012.

Los hallazgos mantienen IDs estables para que Claude y ChatGPT puedan anotar evidencia, correcciones y pruebas sin duplicar investigaciones. Todos siguen **ABIERTO** hasta que se corrija el código pertinente y la prueba de aceptación se ejecute con resultado verificable.

## Hallazgos

### SHP-001 — Los webhooks de pago pueden responder “éxito” sin confirmar que Supabase guardó el pago
**Severidad:** P1 — integridad de pagos. **Confianza:** alta en el problema de manejo de errores.

**Evidencia**
- [Mercado Pago webhook, líneas 14, 32, 38–42 y 55–70](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/functions/mp-webhook/index.ts#L14): si falta `MP_ACCESS_TOKEN`, responde 200; se ignoran errores devueltos por `admin.rpc('acreditar_compra', ...)`, por el `upsert` de suscripción y por la actualización de perfil; el `catch` también responde 200.
- [Stripe webhook, líneas 26, 43, 50–55 y 74–90](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/functions/stripe-webhook/index.ts#L26): si faltan secretos responde 200; se ignoran errores de RPC y de escrituras. Stripe puede recibir un 200 aunque no se hayan aplicado las monedas o el VIP.

**Impacto posible:** el proveedor considera procesada una notificación de pago, pero la cuenta no recibe monedas o acceso VIP. El usuario paga y no obtiene el producto; el sistema no genera una alerta fiable.

**Cómo verificarlo, sin dinero real:** en un entorno de pruebas, simular fallo de la RPC/escritura de Supabase y enviar una notificación de pago de prueba. Comprobar código HTTP, logs, reintento e idempotencia. Nunca provocar estos fallos con clientes reales.

**Corrección propuesta:** comprobar todos los objetos `{ error }` de Supabase; diferenciar errores permanentes de errores reintentables; devolver código no-2xx cuando el evento no quede aplicado y el proveedor deba reintentarlo; registrar un ID de evento/pago y un log saneado, sin datos sensibles. La acreditación de pago debe ejecutarse en una operación transaccional idempotente.

**Aceptación:** un fallo de escritura no devuelve éxito; el reintento completa el pago una sola vez; los logs permiten rastrear el evento sin filtrar tokens ni datos personales.

---

### SHP-002 — La activación de VIP de pago único no es atómica con el registro que evita duplicados
**Severidad:** P1 — integridad de pagos. **Confianza:** alta en el patrón de código.

**Evidencia**
- [Mercado Pago webhook, líneas 35–42](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/functions/mp-webhook/index.ts#L35): primero inserta `suscripciones` con ID `mp-unico:<pago>`; solo si la inserción no devuelve error ejecuta `sumar_vip`.
- [Stripe webhook, líneas 47–55](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/functions/stripe-webhook/index.ts#L47): mismo patrón con `stripe-unico:<sesión>`.

**Impacto posible:** si la inserción se guarda pero la llamada `sumar_vip` falla, el reintento encuentra la fila duplicada y no vuelve a sumar el periodo. El pago está registrado, pero el VIP podría no activarse nunca mediante esos reintentos.

**Prueba de aceptación:** provocar, en staging, fallo de `sumar_vip` después de insertar el registro; reintentar el mismo webhook. Debe terminar activando el VIP una sola vez, sin duplicar meses.

**Corrección propuesta:** mover “registrar pago + conceder periodo” a una sola función SQL/RPC transaccional con clave única por ID del pago. La idempotencia debe abarcar toda la operación, no solo el INSERT. Aplicar el mismo contrato a ambos proveedores.

---

### SHP-003 — La migración versionada no contiene la definición verificable de varias piezas críticas de pago
**Severidad:** P1 antes de activar cobros; P2 para reproducibilidad mientras el lanzamiento sea gratuito. **Confianza:** alta en la brecha documental del repositorio.

**Evidencia**
- [supabase/v389_monedas.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v389_monedas.sql#L8-L18) modifica columnas de `picks`, pero el resto describe en comentarios tablas/funciones como `paquetes`, `precios_cuota` y `acreditar_compra`, remitiendo al “historial de la sesión v386-v389” en vez de contener la DDL y el cuerpo de la función.
- Los webhooks llaman `acreditar_compra`; las funciones de pago leen tablas necesarias para el proceso. Desde el repositorio, no se puede reconstruir de forma autónoma y verificable toda esa parte crítica ni revisar los permisos de la función.

**Impacto posible:** una nueva instancia de Supabase, una restauración o una auditoría de seguridad no puede reproducir completamente las garantías de pago a partir del repositorio.

**Corrección propuesta:** guardar todas las migraciones de tablas, índices, RLS, funciones y permisos en SQL versionado y ordenado. No incluir secretos. Incluir una comprobación de instalación desde una base vacía o de comparación contra un esquema esperado.

**Aceptación:** una instancia de staging creada a partir de las migraciones versionadas reproduce las tablas, funciones y permisos que usa la app; las pruebas de cobro y devolución pasan allí.

---

### SHP-004 — La base concede INSERT directo a perfiles de usuario y no lo revoca en la migración posterior
**Severidad:** P1 de seguridad, **condicionado a que falte la fila del perfil** o a que la configuración de producción difiera del estado esperado. **Confianza:** alta en los permisos declarados; la explotabilidad de producción no se pudo probar.

**Evidencia**
- [web/supabase.sql, línea 64](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/supabase.sql#L64): concede `select, insert, update` sobre `public.perfiles` a `authenticated`.
- [web/negocio.sql, líneas 31–32](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/negocio.sql#L31): revoca UPDATE general y concede columnas concretas, pero no revoca INSERT.
- [supabase/v383_usuarios_vip.sql, línea 11](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v383_usuarios_vip.sql#L11): concede UPDATE de columnas concretas, pero tampoco revoca INSERT. La política de perfil de [web/supabase.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/supabase.sql#L38) admite operaciones del propietario con `auth.uid() = id`.

**Impacto posible:** si un usuario autenticado no tiene su fila precreada por el trigger, puede intentar insertar una propia con campos como `admin`, `plan`, `monedas` o `plan_hasta`. El trigger normalmente crea la fila, así que esto **no demuestra por sí solo una escalación actualmente explotable**; es un permiso innecesario que debe cerrarse y comprobarse contra la base real.

**Corrección propuesta:** revocar INSERT de `anon` y `authenticated` en `public.perfiles`; mantener la creación únicamente mediante el trigger de confianza/servidor. Confirmar que los usuarios siguen pudiendo cambiar solo nombre, usuario y deportes.

**Aceptación:** las pruebas directas con la clave pública y una sesión autenticada reciben 401/403 al intentar INSERT o cambiar columnas protegidas; el registro normal y Google siguen creando el perfil correcto.

---

### SHP-005 — La bandera que hace públicos los picks premium también abre el enlace del grupo VIP
**Severidad:** P1 antes de cobrar picks premium o tratar el grupo de Telegram como privado. **Confianza:** alta en el acoplamiento; si es un bug hoy depende de la intención explícita de lanzamiento.

**Evidencia**
- [web/negocio.sql, líneas 183–191](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/negocio.sql#L183): inserta `premium_con_cuenta = '1'` y usa esa bandera para permitir que cualquier usuario con sesión lea los picks premium.
- [supabase/v383_usuarios_vip.sql, líneas 118–124](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v383_usuarios_vip.sql#L118): `enlace_vip()` usa la misma bandera como alternativa a ser VIP/admin.
- [NEGOCIO.md](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/NEGOCIO.md) diferencia el canal gratis del grupo VIP.

**Impacto posible:** activar la venta de picks cambiando solo `PREMIUM_NIVELES` puede dejar los picks premium legibles para cualquier cuenta si no se cambia también la política/ajuste de Supabase. Además, la bandera puede entregar el enlace del grupo VIP a cuentas gratuitas. Los comentarios lo describen como una excepción de lanzamiento; hay que separar explícitamente ese estado de la configuración comercial.

**Corrección propuesta:** separar las flags, por ejemplo `premium_con_cuenta` y `telegram_vip_abierto`; añadir una comprobación de despliegue que impida activar el modo de cobro mientras la política de lectura premium siga abierta para cualquier cuenta.

**Aceptación:** con modo de cobro activo, una sesión gratuita no puede leer `picks_premium` ni obtener el enlace VIP; un usuario VIP o quien desbloqueó sí accede; la página y la base coinciden.

---

### SHP-006 — Volver a ejecutar web/negocio.sql después de v383 puede reemplazar funciones más nuevas
**Severidad:** P1/P2 de mantenimiento y seguridad, según el orden de migraciones. **Confianza:** alta.

**Evidencia**
- [web/negocio.sql, líneas 34 en adelante y 97 en adelante](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/negocio.sql#L34) redefine `nuevo_usuario()`, `es_pro()` y `desbloquear()`.
- [supabase/v383_usuarios_vip.sql, líneas 14, 46 y 51](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v383_usuarios_vip.sql#L14) trae versiones posteriores que guardan el usuario elegido y contemplan `admin` en VIP/desbloqueos.
- `web/negocio.sql` se presenta como un script que puede volver a ejecutarse, pero sus definiciones más antiguas no son equivalentes a las de v383.

**Impacto posible:** si alguien sigue la guía antigua y vuelve a ejecutar `web/negocio.sql`, puede perder el comportamiento de nombre de usuario o el tratamiento de administrador.

**Corrección propuesta:** dejar una única secuencia canónica de instalación/migración. Marcar `web/negocio.sql` como histórica/no volver a ejecutar o sincronizarla con las definiciones actuales. Añadir una prueba que detecte downgrade de estas funciones.

**Aceptación:** ejecutar el proceso documentado de instalación/migración en staging y verificar que las definiciones finales coinciden con las funciones vigentes, sin perder username/admin.

---

### SHP-007 — La reserva de los 50 precios de fundador no es atómica
**Severidad:** P2 comercial. **Confianza:** alta en el patrón; requiere prueba concurrente para medir el efecto.

**Evidencia**
- [supabase/v383_usuarios_vip.sql, líneas 107–111](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v383_usuarios_vip.sql#L107) calcula lugares disponibles contando suscripciones cuyo estado sea `authorized`.
- [supabase/functions/vip/index.ts, líneas 29–31](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/functions/vip/index.ts#L29) y [supabase/functions/stripe/index.ts, líneas 75–77](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/functions/stripe/index.ts#L75) consultan esa cantidad y luego crean un checkout por separado.

**Impacto posible:** dos compras simultáneas cerca del límite podrían recibir el precio de fundador, aunque solo quede un lugar. Además, un estado de cancelación deja de contar antes de que venza el periodo pagado. El contrato “primeros 50, para siempre” debe definir si un espacio se consume permanentemente o se libera.

**Corrección propuesta:** decidir la regla comercial y reservar plazas en una transacción/función SQL con bloqueo o restricción única; no calcular el cupo con una lectura separada del checkout.

**Aceptación:** prueba concurrente con más de 50 solicitudes: exactamente el número permitido recibe el precio de fundador; la cancelación sigue la regla documentada.

---

### SHP-008 — El parser de fecha invalida timestamps con desplazamiento UTC negativo
**Severidad:** P2 funcional. **Confianza:** alta en el defecto del parser; falta medir si ese formato llega en los datos actuales.

**Evidencia**
- [web/app.js, líneas 13–20](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/app.js#L13): `aFecha()` detecta zona horaria con `/[zZ+]/`, pero no contempla el signo menos.

**Reproducción unitaria:** pasar una fecha ISO válida con offset negativo, por ejemplo `2026-10-17T19:30:00-06:00`. El código termina concatenando `Z` al valor con offset, lo que genera una fecha inválida y devuelve `null`.

**Impacto posible:** fecha de partido, hora restante y clasificación de vivo/final pueden quedar incorrectas cuando el dato llega con un offset negativo.

**Corrección propuesta:** reconocer cualquier sufijo de zona horaria ISO (`Z`, `+HH:MM`, `-HH:MM`) y añadir `Z` solo a fechas sin zona. Añadir pruebas para los cuatro formatos habituales.

**Aceptación:** los casos `Z`, `+02:00`, `-06:00`, fecha/tiempo sin zona y fecha sin hora producen la fecha esperada en CDMX.

---

### SHP-009 — Los partidos en vivo después del primer bloque de 40 pueden quedar sin actualización
**Severidad:** P2 funcional. **Confianza:** alta en el límite estático.

**Evidencia**
- [web/app.js, línea 157](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/app.js#L157): `Object.entries(ids).slice(0, 40)` recorta la lista de partidos elegibles para consultar a ESPN.

**Impacto posible:** si hay más de 40 partidos dentro de la ventana de seguimiento, los restantes no se consultan mientras sigan ocupando las primeras posiciones de la lista. La función se repite cada 30 segundos, pero el corte no rota ni garantiza equidad.

**Corrección propuesta:** usar cola rotatoria o priorizar en vivo con reparto justo del presupuesto de peticiones. Mantener límite de concurrencia y un timeout por partido.

**Aceptación:** test con 50 partidos mock y varios ciclos; todos reciben consultas dentro de un máximo de ciclos definido y no se consultan más de 40 por pasada.

---

### SHP-010 — Fallos de lectura pueden mostrarse como “no hay combinadas” o “aún se llena el historial”
**Severidad:** P2 de confianza/operación. **Confianza:** alta.

**Evidencia**
- [web/app.js, líneas 71–80](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/app.js#L71): si la consulta de combinadas falla o responde no-2xx, asigna `estado.combinadas = []`; después, la UI muestra el mismo estado vacío que si no existieran combinadas.
- [web/cuenta.js, líneas 488–492](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/cuenta.js#L488): errores de consulta de historial dejan `data` vacío y el usuario ve “El historial se va llenando día con día”, aunque haya fallado Supabase.
- [comentarios_correo.py](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/comentarios_correo.py): si la consulta de comentarios devuelve un error HTTP, usa una lista vacía y puede imprimir “0 nuevos”.

**Impacto posible:** una falla de red/permisos se interpreta como falta de datos, contradiciendo la regla del proyecto de no mostrar “no hay” si en realidad falló la consulta.

**Corrección propuesta:** mantener estados separados de carga, vacío real y error. Mostrar “No se pudo consultar; reintenta” ante error, registrar detalles saneados para diagnóstico y no reportar cero filas cuando no se logró consultar.

**Aceptación:** simular 401, 429, 500 y timeout; la interfaz muestra error recuperable, no un estado vacío. Una respuesta 200 con lista vacía sí muestra el estado vacío.

---

### SHP-011 — El porcentaje de acierto del historial puede mostrar NaN %
**Severidad:** P2 visual/datos. **Confianza:** alta.

**Evidencia**
- [web/cuenta.js, línea 498](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/cuenta.js#L498) calcula `tv / (tv + tr)` sin proteger un denominador cero.
- La tabla por día, cerca de la línea 518, hace lo mismo con `d.verdes / (d.verdes + d.rojas)`.
- La lista de días puede incluir resultados de “Cuota alta” aunque no haya resultados verdes/rojos normales, por lo que el denominador puede ser cero.

**Corrección propuesta:** mostrar “—” cuando no hay picks normales liquidados en lugar de calcular porcentaje.

**Aceptación:** historial con solo errores de cuota (o solo resultados aún no liquidados) no enseña `NaN`, `Infinity` ni un 0 % engañoso.

---

### SHP-012 — El workflow de la web puede terminar verde aunque fallen tareas opcionales; no ejecuta las pruebas frontend
**Severidad:** P2 operacional. **Confianza:** alta.

**Evidencia**
- [sitio_web.yml, líneas 63, 74, 83, 93 y 103](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/.github/workflows/sitio_web.yml#L63): Telegram, Gemini, avisos, correo de comentarios y publicación Cloudflare usan `continue-on-error: true`.
- El workflow instala dependencias, ejecuta `exportar_web.py` y publica; no se encontró ejecución de `test_v400.py`, `node --check` ni smoke test de navegador en el pipeline.
- El run 39102584649 fue exitoso y su paso Cloudflare también terminó exitoso; se cita como comprobación de ese run, no como prueba de que todos los futuros runs reportarán bien los fallos.

**Impacto posible:** una regresión en JS o un fallo de correo/Telegram puede desplegarse sin bloquear el workflow ni crear una señal operativa obvia. Un fallo de Cloudflare puede quedar oculto por el deploy de GitHub Pages que corre después.

**Corrección propuesta:** un job obligatorio de pruebas previas a publicar (`python test_v400.py`, `node --check web/app.js`, `node --check web/cuenta.js`, revisión de scripts Python y pruebas del exporter). Separar las tareas realmente opcionales, pero publicar su resultado en un resumen y alertar sobre fallos del sitio canónico.

**Aceptación:** una prueba fallida bloquea el despliegue; un fallo opcional no queda invisible y especifica qué capacidad está degradada.

---

### SHP-013 — El aviso de privacidad no coincide con los métodos de cuenta ni con todos los proveedores/datos usados
**Severidad:** P2 de confianza y cumplimiento; requiere revisión legal. **Confianza:** alta en las diferencias de texto, no es un dictamen legal.

**Evidencia**
- [web/privacidad.html, líneas 15–30](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/privacidad.html#L15) menciona acceso por enlace de correo y dice que no se guardan contraseñas; el producto también implementa inicio con usuario/contraseña y Google.
- La implementación y el workflow usan pagos de Mercado Pago y Stripe, correo de Brevo y comentarios voluntarios con texto/correo/página. El aviso actual solo menciona Supabase y Telegram de forma destacada.
- La página remite solicitudes ARCO al canal de Telegram; confirmar que ese canal permite recibir mensajes privados y que exista un proceso para responderlos/borrar cuenta.

**Impacto posible:** los usuarios no reciben información clara sobre métodos de acceso, proveedores y datos tratados. Los términos prometen opciones de cancelación/acceso y el aviso debe reflejar el comportamiento real.

**Corrección propuesta:** inventariar flujo por flujo qué dato recoge cada función, proveedor, finalidad, plazo de conservación, procedimiento de baja/ARCO y contacto efectivo. Coordinar el texto final con revisión legal para México.

**Aceptación:** la política se valida contra una matriz de datos real (registro, OAuth, comentarios, cobro/renovación, Telegram y correos); los enlaces de contacto funcionan desde una cuenta de prueba.

---

### SHP-014 — El formulario público de comentarios no tiene limitación de frecuencia en el lado servidor
**Severidad:** P2 de abuso/operación. **Confianza:** alta en la política publicada; abuso real no probado.

**Evidencia**
- [supabase/v401_comentarios.sql, líneas 15–20](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v401_comentarios.sql#L15) permite INSERT a `anon` y `authenticated`; hay límites de longitud, pero no se observa limitación por frecuencia.
- [web/cuenta.js, líneas 462–476](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/cuenta.js#L462) solo deshabilita el botón del navegador mientras se envía.
- [comentarios_correo.py](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/comentarios_correo.py) manda los comentarios pendientes por email en las pasadas del workflow.

**Impacto posible:** llamadas automatizadas pueden insertar muchos comentarios, saturar el correo de administración y afectar reputación de envío.

**Corrección propuesta:** colocar la escritura detrás de una función de servidor con límite de frecuencia/rate limit, honeypot o Turnstile y deduplicación básica; conservar la política para que la web no pueda leer los comentarios.

**Aceptación:** un flujo de prueba de alta frecuencia es limitado en el servidor; mensajes legítimos siguen llegando y no se exponen comentarios en la API pública.

---

## Comprobaciones aún bloqueadas (no deben marcarse “verdes” sin hacerlas)

- Abrir la web en navegador real y ejecutar smoke de escritorio y móvil, registro, login, Google, seguir un pick, desbloquear, devolución, combinadas, historial, planes, comentarios y cierre de sesión.
- Verificar en Supabase de producción el estado de las migraciones, RLS/grants efectivos, triggers, funciones/RPC, ajustes `premium_con_cuenta`, `privados.telegram_vip` y configuración real de webhooks/secrets.
- Ejecutar las pruebas del repo con el Python 3.12 del venv descrito en CONTEXTO_TRASPASO, sin tocar artefactos de datos del bot.
- Ejecutar pruebas de proveedor en modo sandbox (Mercado Pago/Stripe), incluidos pago aprobado, repetición del mismo webhook, retraso, estado pendiente, cancelación, renovación, fallo de base e idempotencia.
- Verificar el resultado de cada paso en GitHub Actions: “workflow verde” no sustituye la validación del contenido ni de las llamadas laterales.
- Auditar seguridad de frontend de forma automatizada (XSS/CSP/dependencias), y no inferir una vulnerabilidad solo porque `innerHTML` exista: comprobar cada entrada dinámica y sus escapes.

## Orden de trabajo recomendado

1. **SHP-001 y SHP-002:** fiabilidad e idempotencia de cobros/webhooks.
2. **SHP-003, SHP-004 y SHP-005:** esquema reproducible, acceso a perfiles y controles premium/VIP; no activar cobros hasta validar.
3. **SHP-006:** evitar degradar la base al volver a ejecutar scripts SQL históricos.
4. **SHP-008 a SHP-011:** pruebas unitarias de fechas, feed en vivo, estados de error y porcentajes.
5. **SHP-012 a SHP-014:** CI, privacidad y protección contra abuso.
6. Después de cada arreglo: actualizar el ID, poner commit/PR, registrar la prueba ejecutada y el resultado real; no marcar como resuelto únicamente porque el despliegue quedó verde.

## Historial de esta auditoría

- Revisión de fuente sobre la rama base indicada arriba; las funciones de datos de GitHub Actions estaban generando commits durante la auditoría.
- El sitio publicado no respondió al método de navegación disponible; no se certifican interacciones de producción.
- No se cambió código de la app ni se tocaron datos/secretos de Supabase.
- Este documento es el registro maestro de hallazgos. El archivo CONTINUIDAD_AUDITORIA_SHARPICKS.md define cómo Claude y ChatGPT deben mantenerlo sincronizado.
