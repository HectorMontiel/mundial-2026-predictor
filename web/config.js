// Datos de conexión del sitio. La clave «publishable» de Supabase es PÚBLICA
// por diseño (sólo puede leer lo que las reglas de la base permiten; escribir
// con ella da 401, comprobado), así que puede ir aquí. NUNCA poner aquí la
// clave secreta (sb_secret_…): ésa vive sólo en los secretos de GitHub.
// Vacías: el sitio lee datos/hoy.json (lo que deja exportar_web.py).
window.CONFIG = {
  NOMBRE: 'SharPicks',
  SUPABASE_URL: 'https://lyfmyehvfywnjasinbne.supabase.co',
  SUPABASE_ANON_KEY: 'sb_publishable_SmDi-ah0LYBl2-F4wO70Sw_39B0SIpo',
  // v379 — enlaces de invitación de los canales (t.me/...); vacíos = «muy pronto»
  TELEGRAM_GRATIS: 'https://t.me/sharpicks_mx',
  // v380 — true cuando Google esté activo en Supabase (Authentication → Providers)
  LOGIN_GOOGLE: true,
};
