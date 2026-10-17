# SharPicks — modelo de negocio

Sitio: https://sharpicks.pages.dev · Base: Supabase (gratis) · Picks: nuestro modelo (GitHub Actions)

## Lo que tenemos que nos distingue

- **Acierto medido, no prometido**: 💎 Diamante acierta 89-92 %, todas las «se mete» 82-85 % (partidos ya jugados).
- **En vivo**: marcador, minuto, estadísticas tipo SofaScore y cómo va cada apuesta.
- **Historial público con dinero**: casi nadie enseña cuánto habría dado apostar sus picks. Nosotros sí. Eso da confianza.

## La verdad que hay que cuidar

A cuota 1,12-1,20, acertar 85-90 % deja **muy poco dinero** por apuesta (medido: entre −5 y +1 por cada $100). Por eso:

- **No vender «ganancias»**. Lo que se vende es la selección medida, el en vivo, los avisos a tiempo y el ahorro de horas de análisis.
- Anunciar «90 % de acierto» sin decir el dinero puede ser publicidad engañosa (PROFECO). El sitio ya enseña las dos cosas.
- Cobrar de verdad conviene cuando las 💎 den dinero en las dos mitades (p5 > 0). Mientras tanto, crecer.

## El modelo: gratis + «No Win, No Pay» + VIP (+ afiliados)

| Nivel | Qué recibe | Cómo se cobra |
|---|---|---|
| **Gratis** | 🥇 Oro y 🥈 Plata, en vivo, historial, canal gratis de Telegram | Nada: es el gancho |
| **No Win, No Pay** | Desbloquea cada 💎/🔷 | Monedas 🪙; **si sale roja, se devuelven solas** (lo hace la base) |
| **VIP mensual** | Todos los 💎/🔷, grupo VIP de Telegram, Soñadora | Suscripción (sugerido $99-149 MXN/mes) |
| **Afiliados** | Enlaces a casas con permiso (Caliente, Playdoit, Codere…) | La casa paga por cada registro (CPA). Mejor CPA que «revenue share», para no ganar cuando el usuario pierde |

Precios sugeridos de monedas (a decidir): paquete de 100 🪙 = $49 MXN; 💎 = 10 🪙; 🔷 = 5 🪙. Con 89 % de acierto, cobrarías ~89 % de lo desbloqueado.

## Fases

1. **Lanzamiento (ahora, 4-6 semanas)**: todo gratis («0 monedas», como BetFlipAi). Registro con 50 🪙 de regalo. Canal gratis + VIP abiertos. Meta: 500-1.000 personas y un historial que hable solo.
2. **Encender el cobro**: `PREMIUM_NIVELES = Diamante` (variable del repositorio) y precios en la tabla `ajustes`. Los 💎 se ocultan sólo hasta que empieza el partido.
3. **Pagos**: Telegram Stars para el VIP (Telegram cobra, sin pasarela) y Mercado Pago (enlace de pago) para monedas. Stripe no acepta pronósticos deportivos.
4. **Afiliados**: registrarse en los programas de las casas mexicanas con permiso de Gobernación.

## Lo que falta de tu lado

- **Telegram**: crear el **canal gratis** y el **grupo VIP**, agregar el bot como administrador, y pasar sus IDs a los secretos `TELEGRAM_CHAT_GRATIS` y `TELEGRAM_CHAT_VIP`. Los enlaces de invitación van en `web/config.js`.
- **Correo de acceso**: Supabase gratis sólo manda unos pocos correos por hora. Para muchos usuarios: una cuenta gratis en Resend (3.000 correos al mes) conectada en Supabase → Authentication → SMTP.
- **SAT**: alta como persona física (RESICO) antes de cobrar.
- **Mercado Pago**: confirmar que acepta el giro antes de conectarlo.
