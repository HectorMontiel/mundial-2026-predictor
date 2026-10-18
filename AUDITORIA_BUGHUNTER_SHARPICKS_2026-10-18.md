# Auditoría Bug Hunter — SharPicks

**Fecha:** 18 de octubre de 2026 (CDMX)  
**Repositorio auditado:** [HectorMontiel/mundial-2026-predictor](https://github.com/HectorMontiel/mundial-2026-predictor)  
**Rama base:** `main` en `a86a9d5c7e05fa5dfdefe6d225e9a64704dbe5c4` al iniciar esta auditoría.  
**Sitio:** https://sharpicks.pages.dev/  
**Estado global:** **NO APROBADO todavía para declarar la auditoría completa ni para dar por validados los cobros.** Se detectaron riesgos en pagos/seguridad y defectos funcionales reproducibles desde el código.  
**Alcance inicial:** revisión estática de los archivos fuente y metadatos de GitHub Actions. En la fase inicial no se pudo cargar el sitio publicado en el navegador disponible. **Actualización posterior:** ya se consultó el esquema activo de Supabase y se desplegó v403; el estado verificable actual y las limitaciones restantes se describen al final del documento. No se ha completado un flujo de pago real ni un smoke test interactivo del sitio.

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


---

## Addendum de revisión cruzada de tests y permisos (18-oct-2026, CDMX)

La revisión de pruebas existentes añadió hallazgos que no estaban en la lista inicial. Este complemento forma parte del mismo registro maestro.

### SHP-015 — La política de RLS puede revelar el texto premium desde el inicio del partido, aunque la nota de v389 dice que debe abrirse al terminar
**Severidad:** P1 si el requisito vigente sigue siendo “al terminar el partido”; **estado:** CONFIRMADO EN CÓDIGO, REQUISITO/DESPLIEGUE POR VALIDAR.  
**Confianza:** alta en la discrepancia; el contenido real de la base de producción no se consultó.

**Evidencia**
- [web/negocio.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/negocio.sql) crea la política **premium a quien le toca** con una condición que permite lectura cuando existe un pick con p.inicio <= now(). Conceder SELECT a anon junto con esa política permite que cualquier cliente anónimo que conozca el ID consulte picks_premium tras el inicio, independientemente de si pagó/desbloqueó.
- [supabase/v383_usuarios_vip.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v383_usuarios_vip.sql) contiene la misma condición en la política.
- [supabase/v389_monedas.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/v389_monedas.sql) resume que picks_premium “se abre al TERMINAR el partido (verde/roja/nula), no al empezar”.
- [test_v379.py](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/test_v379.py) comprueba la condición antigua p.inicio <= now() y la describe como “ya empezado”. Esto indica que la intención cambió o quedó contradictoria; no se debe corregir sin confirmar qué regla comercial manda hoy.

**Impacto posible:** usuarios sin pagar podrían recuperar el texto real de los picks premium por API desde que empieza el partido, antes de que termine, aun cuando la UI no lo muestre directamente.

**Prueba necesaria:** en staging, con PREMIUM_NIVELES activo y premium_con_cuenta='0', consultar picks_premium como cliente anónimo antes del partido, durante el partido y después de la liquidación. Confirmar resultados esperados y repetir como VIP y como usuario que desbloqueó. Consultar además la política real desplegada en producción antes de afirmar que es explotable allí.

**Corrección propuesta, si el requisito de v389 es el correcto:** retirar el acceso público por p.inicio <= now() y reemplazarlo por una condición ligada al estado final liquidado, comprobando si p.estado es uno de verde, roja o nula; conservar el acceso de VIP y desbloqueos previos. Añadir test de acceso directo vía API para los tres estados.

**Aceptación:** anon no lee la apuesta mientras esté pendiente/viva; una vez liquidada, el comportamiento coincide con la regla documentada; VIP y usuarios que desbloquearon antes conservan el acceso correcto.

---

### SHP-016 — El precio que muestra la interfaz no coincide necesariamente con el precio que cobra la base al desbloquear un pick
**Severidad:** P1 comercial/integridad de monedas antes de activar precios reales.  
**Estado:** CONFIRMADO EN CÓDIGO CANÓNICO; FUNCIÓN EFECTIVA DE PRODUCCIÓN POR VALIDAR.

**Evidencia**
- [web/cuenta.js](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/cuenta.js) calcula el precio mostrado mediante precios_cuota, usando la cuota del pick.
- [web/negocio.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/web/negocio.sql) define public.precio_pick(p public.picks) usando ajustes por categoría de probabilidad (precio_diamante, precio_platino, precio_oro, precio_plata), no la tabla precios_cuota.
- La función public.desbloquear(pick_id) cobra el valor devuelto por public.precio_pick(p). La implementación de este SQL no incluye un caso específico para tipo='error'/“Cuota alta”, aunque la interfaz sí lo clasifica como nivel cobrable y muestra precio según cuota.
- supabase/v389_monedas.sql solo documenta el nuevo esquema de precios en comentarios; en el archivo no queda versionada una definición actualizada de precio_pick que haga coincidir ambos cálculos.

**Impacto posible:** la pantalla puede decir “Desbloquear por N monedas” y descontar otra cantidad. En particular, los errores de cuota pueden caer en el precio de Plata si la función de base no tiene una implementación distinta desplegada; podrían quedar mal cobrados o incluso costar cero si el ajuste correspondiente vale cero.

**Prueba necesaria:** leer la definición efectiva de public.precio_pick en staging/producción; comparar con la función versionada y probar cuotas a ambos lados de cada límite, además de un pick tipo error. Verificar saldo y movimientos antes/después.

**Corrección propuesta:** definir una sola función SQL de precio por cuota/mercado, usada tanto por desbloquear como por combinadas y reflejada por la interfaz. La UI muestra una estimación, pero la base debe ser la autoridad. Añadir pruebas por bandas y garantizar que la etiqueta “Cuota alta” tiene una banda coherente.

**Aceptación:** para todo caso de prueba, el precio mostrado, el descuento en saldo y el registro de movimientos coinciden; los errores de cuota no se cobran según el precio de Plata por accidente.

---

### SHP-017 — El exportador registra fallos al subir picks premium o combinadas, pero aun así termina con código cero
**Severidad:** P1 funcional cuando se cobra contenido premium; P2 mientras la función de pago siga desactivada.  
**Estado:** CONFIRMADO EN CÓDIGO; NO REPRODUCIDO EN EJECUCIÓN.

**Evidencia**
- [exportar_web.py](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/exportar_web.py) registra un warning si falla el POST a picks_premium, pero subir_supabase devuelve el contador público y no informa el fallo de la tabla premium mediante el código de salida.
- main() ignora el resultado de la subida y termina con return 0; las excepciones al subir combinadas también solo generan warning.
- [sitio_web.yml](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/.github/workflows/sitio_web.yml) continúa con despliegue estático después de ejecutar el exportador.

**Impacto posible:** el pick público puede quedar como “🔒 Pick Diamante” mientras su texto real no se insertó en picks_premium; el workflow/CI puede verse verde y publicar de todos modos. Las combinadas también pueden quedar viejas o ausentes sin que el exportador falle.

**Prueba necesaria:** en staging, simular rechazo/timeout al insertar picks_premium y al subir combinadas; verificar exit code del exportador y resultado de Actions. No usar secretos/productos reales para la prueba.

**Corrección propuesta:** propagar errores críticos de sincronización a un resumen estructurado y a un exit code no-cero cuando falle una escritura necesaria para la experiencia publicada. Distinguir explícitamente tareas opcionales de operaciones necesarias para que las tarjetas premium funcionen. Si el modo premium está desactivado, mantener el comportamiento sencillo.

**Aceptación:** una subida crítica fallida bloquea la publicación o deja un estado degradado explícito y alerta; un retry completa la subida de forma idempotente. El workflow no presenta como operación completa una publicación cuyos datos de pago están incompletos.

---

## Nota de alcance actualizada

El árbol consultado de main contiene 1.733 paths y 97 archivos de prueba con nombres test*.py; 62 paths son directamente relevantes a web, hosting y APIs. Se inspeccionaron pruebas de forma dirigida, incluyendo test_v379.py, test_v383.py, test_v389.py, test_v390.py, test_v394.py, test_v395.py, test_v396.py y test_v400.py. No se han leído todos los 1.733 paths ni ejecutado todos los 97 tests. No se debe afirmar que el código de producción es seguro o que el proyecto completo está validado.

El main seguía avanzando automáticamente después de crear la rama. En una consulta posterior, el último commit observado fue 1e077067cf18afb2ad548c9fa859908200a7bd48 (precálculo de 18-oct-2026 06:55:32 UTC). Antes de corregir, volver a consultar main y revisar el diff/rebase.


## Estado de la rama compartida y PR #2 — 18-oct-2026

La rama y la PR evolucionaron durante la revisión. La PR [#2](https://github.com/HectorMontiel/mundial-2026-predictor/pull/2) sigue en **borrador, sin merge**. No representa una aprobación de producción. En la misma rama aparecieron commits candidatos v402 para fechas/feed en vivo, estados de error, historial, permisos de perfiles, enlace VIP, webhooks de pagos, comentarios con rate limit y validaciones de build. Estos commits aparecen con autor GitHub HMREY; no se debe inferir qué agente los escribió.

### Hallazgos con una corrección candidata presente en la rama, pendiente de validar
- SHP-001/002: los webhooks propagan algunos errores y los pagos VIP únicos usan la RPC transaccional procesar_vip_unico.
- SHP-004: se revoca INSERT directo a perfiles y se limitan actualizaciones a columnas permitidas.
- SHP-005: enlace de Telegram VIP usa telegram_vip_abierto, separada de premium_con_cuenta.
- SHP-008: parser ISO pasa a web/fechas.js y test_web_v402.cjs cubre offsets con Z, + y -.
- SHP-009: el bucle en vivo usa vivoCursor para rotar el grupo de hasta 40 partidos por pasada.
- SHP-010/011: se separan algunos estados de error de los estados vacíos; se protegen porcentajes contra denominador cero.
- SHP-012: sitio_web.yml incluye validaciones previas y un resumen de integraciones/despliegue.
- SHP-014: los comentarios pasan por Edge Function y RPC con límite por huella.

**Todo lo anterior es “CORRECCIÓN CANDIDATA EN RAMA”, no “validado”.** Faltan pruebas ejecutadas y, para SQL/Edge Functions, aplicar la migración y desplegar la función en staging antes de darlo por corregido.

### Hallazgos que siguen abiertos en la rama consultada
- SHP-003: la historia de migraciones de pagos sigue sin reproducir todo el esquema/funciones.
- SHP-006: web/negocio.sql sigue conteniendo definiciones históricas que pueden degradar funciones; el comentario preventivo no reemplaza una migración canónica segura.
- SHP-007: cupo fundador sigue calculado por lectura separada del checkout; pagos únicos con estado pagado tampoco entran en el conteo de estado authorized.
- SHP-015: la política premium sigue permitiendo lectura desde p.inicio <= now() en los scripts inspeccionados, mientras v389 documenta que debe abrirse al terminar. Requiere decidir y aplicar la regla actual.
- SHP-016: el precio mostrado en cuenta.js sigue calculado por precios_cuota, mientras precio_pick en negocio.sql usa ajustes por nivel y no contempla tipo error de forma explícita.
- SHP-017: exportar_web.py aún puede devolver 0 después de fallos al subir contenido premium/combinadas.

### Validación bloqueada
Intenté clonar la rama de forma superficial para ejecutar Node/Python tests; la terminal no pudo resolver github.com. Por tanto no se ha ejecutado test_web_v402.cjs, test_v400.py ni el resto de la suite desde este entorno. La PR no debe fusionarse hasta ejecutar esos tests en el clon local/CI y revisar logs reales.


---

## Estado verificable actualizado — 18 de octubre de 2026, 10:16 CDMX

Esta sección sustituye cualquier frase anterior que dijera que no se tenía acceso a Supabase. La auditoría pasó de revisar fuentes a comprobar parte del esquema activo. **No equivale todavía a una prueba E2E de navegador ni a una validación completa de pagos.**

### Qué sí se ejecutó y se comprobó

1. **Corrección de privacidad financiera v403 desplegada.** Se aplicó la migración `v403_finanzas_rpc_auth` al proyecto Supabase que usa SharPicks. La migración aparece en el historial como versión `20261018150201`. Después de aplicarla, una consulta de permisos confirmó: `anon_execute=false`, `authenticated_execute=true`, `security_definer=true` y la guarda `auth.uid() = p_user_id` presente en `public.monthly_category_summary(uuid,integer,integer)`. No se consultó ni se exportó ninguna transacción de usuario.
2. **Migración v402 y v404 validadas contra el esquema real sin persistir cambios.** Se ejecutó el contenido completo de ambas migraciones dentro de una transacción de comprobación seguida de `ROLLBACK`. El SQL compiló; las comprobaciones de firmas de funciones, permisos de RPC, política premium, comentarios y cálculo de precios finalizaron. Eso acredita compatibilidad sintáctica/estructural con el esquema actual; no significa que v402/v404 estén desplegadas.
3. **Precio real de producción cotejado.** `public.precio_pick` ya consulta `public.precios_cuota` en producción. Las 5 bandas son 1.00–1.30 = 5 monedas; 1.30–1.60 = 8; 1.60–2.00 = 12; 2.00–3.00 = 18; 3.00–99.00 = 25. En la prueba dentro de la transacción: cuota 1.04, premium = 5; error de cuota 3.50 = 25; pick no premium con cuota 1.50 = 0. Por eso SHP-016 no era un fallo de cobro activo: era una discrepancia del SQL de instalación/versionado, corregida en esta rama.
4. **Política premium de producción cotejada.** La política desplegada sólo habilita lectura pública cuando `p.estado` es `verde`, `roja` o `nula`; VIP/desbloqueos se contemplan por separado. SHP-015 tampoco era un fallo activo de la política en producción: la discrepancia estaba en los SQL históricos/versionados, que ahora usan la misma condición.
5. **Pruebas de la rama aprobadas en el SHA `3f8ed123e9fdb6ecb17a5ca9ee56c2943b0621cb`.** [Validación sin despliegue](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39144109592) y [tests seguros](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39144109604) terminaron en verde. Incluyen pruebas de fechas, guardas de interfaz, 5 pruebas de fallos de sincronización premium/combinadas y las pruebas existentes `test_v383.py`, `test_v389.py`, `test_v390.py`, `test_v394.py`, `test_v395.py`, `test_v396.py`, `test_v400.py`. La validación añadida de Deno comprobó sintaxis/tipos de las cinco Edge Functions candidatas (`comentario`, `vip`, `stripe`, `mp-webhook`, `stripe-webhook`).

### Qué sigue sin estar desplegado en producción

- La migración `supabase/v402_bughunter_hardening.sql` (perfiles, enlace VIP, reserva de fundador, rate limit de comentarios y RPC de pago único).
- La migración `supabase/v404_precios_cuota_canonico.sql` (hace reproducible el cálculo de precio que ya coincide con producción).
- Las versiones candidatas de las Edge Functions y la interfaz nueva de comentarios.
- Las correcciones de interfaz/exportador están probadas en CI, pero aún dependen de fusionar la PR y de que el workflow de sitio termine correctamente para considerarse desplegadas.

### Historial de fallos y cómo quedó

Los fallos que se ven en las capturas correspondían a revisiones previas de la rama. Se detectó una versión de `v402_bughunter_hardening.sql` con contenido duplicado/truncado; fue reconstruida, y la migración completa se volvió a ejecutar en una transacción de comprobación. Después, una aserción nueva de la suite dio un falso positivo por usar un regex demasiado amplio; se corrigió y la suite volvió a ejecutarse en verde. Los logs de los fallos anteriores no se ocultan: demuestran por qué no se debe equiparar un run antiguo en verde con el estado actual.

### SHP-018 — RPC financiera SECURITY DEFINER permitía consultar el ID de otro usuario

**Estado:** RESUELTO EN PRODUCCIÓN (v403, 18-oct-2026).  
**Hallazgo:** `public.monthly_category_summary(p_user_id, p_year, p_month)` tenía ejecución permitida a `anon` y no verificaba la propiedad de `p_user_id`.  
**Corrección:** la función ahora filtra por `auth.uid() = p_user_id` o `auth.role() = 'service_role'`; se revocó EXECUTE a `public/anon` y se concedió a `authenticated/service_role`.  
**Verificación posterior:** `anon_execute=false`, `authenticated_execute=true`, guarda de propiedad presente. No se usaron datos financieros reales en la prueba.  
**Registro versionado:** [supabase/v403_finanzas_rpc_auth.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/audit/sharpicks-bughunter-2026-10-18/supabase/v403_finanzas_rpc_auth.sql).

### Criterio de publicación vigente

La PR sigue siendo el vehículo de los cambios de SharPicks. No se fusionará hasta que el CI más reciente siga en verde, se actualice el informe con el orden de despliegue, y las migraciones v402/v404 y las Edge Functions se desplieguen en una secuencia que no deje a la página apuntando a endpoints inexistentes. El sitio no se declara validado hasta comprobar el resultado de la ejecución posterior a la fusión y hacer smoke tests del frontend publicado.


## Actualización de despliegue — 18 de octubre de 2026, 10:35 CDMX

### Cambios ya aplicados a producción (Supabase)
- Migración `20261018150201 / v403_finanzas_rpc_auth`: se restringió `monthly_category_summary` para impedir consultas de otros usuarios. Verificación posterior: `anon_execute=false`, `authenticated_execute=true`, guarda de propiedad presente.
- Migración `20261018163026 / v402_bughunter_hardening`: aplicada correctamente. Verificación posterior: existen `comentarios_rate_limit`, `registrar_comentario`, `procesar_vip_unico` y `reservar_lugar_fundador`; `anon` no puede ejecutar `enlace_vip` ni `desbloquear`; `anon`/autenticados no pueden insertar perfiles. `telegram_vip_abierto=0`.
- Migración `20261018163111 / v404_precios_cuota_canonico`: aplicada correctamente. Las bandas activas quedan iguales a las que ya usaba la base: 5 / 8 / 12 / 18 / 25 monedas. Prueba de función: cuota 1.04 premium → 5; error de cuota 3.50 → 25; pick 1.50 no premium → 0.
- Edge Functions desplegadas, todas `ACTIVE`: `comentario` v1; `vip` v5; `stripe` v2; `mp-webhook` v6; `stripe-webhook` v2. Las cinco versiones de esta rama pasaron `deno check` en CI.

### Secuencia segura de comentarios
La migración v402 crea la RPC/table de rate limit pero deja temporalmente el INSERT directo de comentarios para evitar cortar la web antigua. La nueva Edge Function ya está desplegada. Tras fusionar esta PR y confirmar el despliegue de la web nueva, se debe probar el formulario de comentarios; después ejecutar `supabase/v405_comentarios_solo_edge.sql` para revocar el INSERT directo. **v405 aún no se ha ejecutado en producción.**

### CI actual de la rama
En el SHA `1f5984e2cf444b0d044b88e6facb712800ba2f6b`:
- [Validar SharPicks sin desplegar](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39145101203): success.
- [Tests seguros SharPicks v402](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39145101110): success.
La rama pasó validación de JS, fechas, controles estáticos, Deno check y las pruebas Python de exportador/combinadas y regresión. Los fallos anteriores eran de commits más antiguos y quedaron superados; sus referencias siguen en el historial, no se borraron.

### Aún no se ha desplegado la web estática nueva
El frontend modificado todavía necesita que esta PR se fusione y que el workflow canónico de Cloudflare Pages termine exitosamente. Después se debe verificar el sitio servido y probar el formulario de comentarios desde la página. Sólo tras esa comprobación se aplicará v405 y se comprobará que INSERT directo en comentarios ya no está permitido.


---

## Estado final de despliegue — 18-oct-2026

**Correcciones principales desplegadas.** La PR #2 está fusionada en `main`; commit de publicación `68d8f139834fce15a6867a5bad6ff1912bf05b02`. El workflow de sitio [39146143725](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39146143725) terminó en verde, con validación pre-publicación y Cloudflare Pages exitoso. La prueba HTTP desde GitHub Actions [39147099500](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39147099500) confirmó homepage/cuenta HTTP 200 y validación esperada 400 del endpoint de comentarios sin insertar datos.

**Migraciones aplicadas a Supabase:** v403_finanzas_rpc_auth, v402_bughunter_hardening, v404_precios_cuota_canonico y v405_comentarios_solo_edge. Los permisos posteriores muestran: `anon/authenticated INSERT comentarios=false`, `service_role INSERT comentarios=true`, tabla de rate limit y RPC de comentarios presentes, y RPC financiera no ejecutable por anon. Las funciones `comentario`, `vip`, `stripe`, `mp-webhook` y `stripe-webhook` coinciden exactamente con los archivos de `main`.

Detalles, porqués, pruebas, limitaciones y enlaces: [DESPLIEGUE_SHARPICKS_2026-10-18.md](./DESPLIEGUE_SHARPICKS_2026-10-18.md).

**Aún abierto:** SHP-003/SHP-006 (instalación desde cero/migraciones históricas), pagos E2E con sandbox y un comentario válido con correo en staging. No declarar auditoría total certificada ni haber validado pagos reales.


## Pruebas transaccionales adicionales — finalización del 18-oct-2026

Además de los workflows, se ejecutaron tres comprobaciones directas en Supabase dentro de transacciones que terminaron en `ROLLBACK`; no se dejaron suscripciones, modificaciones de perfil, reservas ni comentarios sintéticos persistidos:

- **Pago VIP único/idempotencia:** la primera llamada a `procesar_vip_unico` insertó una sola suscripción de prueba; la segunda con el mismo ID devolvió el resultado de duplicado; `plan_hasta` no volvió a extenderse y el conteo de filas quedó en uno durante la prueba. PASS.
- **Reserva fundador:** dos llamadas para la misma cuenta sintética/reversible produjeron una sola reserva pendiente activa; no se duplicó la plaza. PASS.
- **Límite de comentarios:** cinco llamadas sintéticas se aceptaron y la sexta devolvió `rate_limit`; la transacción se revirtió. PASS.

Estas pruebas validan la lógica PostgreSQL desplegada, no sustituyen una compra real/sandbox ni validan la entrega del webhook por Stripe/Mercado Pago. El smoke HTTP de producción sigue siendo no destructivo: comprueba el endpoint con un body inválido y no crea comentarios.
