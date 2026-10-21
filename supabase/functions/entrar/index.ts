// v383 — ENTRAR CON NOMBRE DE USUARIO Y CONTRASEÑA.
// Supabase sólo sabe entrar con correo; aquí se busca el correo del usuario
// (con la clave de servicio, en el servidor: el correo nunca llega a la
// página) y se inicia la sesión. La respuesta es igual si el usuario no existe
// o la contraseña está mal, para no revelar quién tiene cuenta.
// v413 — y con LÍMITE DE INTENTOS propio (por usuario y por la IP real de quien
// intenta): para Supabase todos los intentos salen de esta función, así que su
// límite por IP no protegía cada cuenta (`v413_intentos_entrar.sql`).
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (d: unknown, s = 200) => new Response(JSON.stringify(d), { status: s, headers: { ...CORS, 'Content-Type': 'application/json' } });

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  try {
    const { usuario, contrasena, captcha, accion } = await req.json();
    const URL_ = Deno.env.get('SUPABASE_URL')!;
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const nombre = String(usuario || '').trim().slice(0, 64);
    const ip = (req.headers.get('x-forwarded-for') || req.headers.get('cf-connecting-ip') || '').split(',')[0].trim().slice(0, 64);
    // v425 — EL ENLACE POR CORREO CON EL USUARIO: se busca su correo aquí (nunca
    // llega a la página) y Supabase se lo manda. La respuesta es la misma exista
    // o no el usuario, y cuenta como intento (frena que se use para mandar spam).
    // v426 — y es el de RESTABLECER CONTRASEÑA (antes era uno para entrar).
    if (accion === 'recuperar' || accion === 'enlace') {
      if (!nombre) return json({ error: 'Escribe tu usuario o tu correo.' }, 400);
      const { data: puedeE, error: errE } = await admin.rpc('puede_entrar', { p_usuario: nombre, p_ip: ip });
      if (!errE && puedeE === false) return json({ error: 'Demasiados intentos. Espera 15 minutos e intenta de nuevo.' }, 429);
      await admin.rpc('anotar_entrar', { p_usuario: nombre, p_ip: ip, p_ok: false });
      const { data: idE } = await admin.rpc('id_de_usuario', { u: nombre });
      if (idE) {
        const { data: uE } = await admin.auth.admin.getUserById(idE);
        const correoE = uE?.user?.email;
        if (correoE) {
          const anonE = createClient(URL_, Deno.env.get('SUPABASE_ANON_KEY')!, { auth: { persistSession: false } });
          const { error: eOtp } = await anonE.auth.resetPasswordForEmail(correoE, {
            redirectTo: 'https://sharpicks.pages.dev/', captchaToken: captcha ? String(captcha) : undefined });
          if (eOtp && /captcha/i.test(eOtp.message)) return json({ error: 'Completa la verificación de abajo y vuelve a intentar.' }, 400);
          if (eOtp) return json({ error: 'No se pudo enviar el correo. Intenta en unos minutos.' }, 502);
        }
      }
      return json({ ok: true, mensaje: 'Si ese usuario existe, le mandamos a su correo el enlace para elegir una contraseña nueva (revisa también «spam»).' });
    }
    if (!usuario || !contrasena) return json({ error: 'Escribe tu usuario y tu contraseña.' }, 400);
    const { data: puede, error: errLimite } = await admin.rpc('puede_entrar', { p_usuario: nombre, p_ip: ip });
    if (!errLimite && puede === false) return json({ error: 'Demasiados intentos. Espera 15 minutos e intenta de nuevo.' }, 429);
    // un fallo se anota y se responde igual (y con la misma demora) exista o no el usuario
    const malo = async () => {
      await admin.rpc('anotar_entrar', { p_usuario: nombre, p_ip: ip, p_ok: false });
      await new Promise((r) => setTimeout(r, 400));
      return json({ error: 'Usuario o contraseña incorrectos.' }, 401);
    };
    const { data: id } = await admin.rpc('id_de_usuario', { u: nombre });
    if (!id) return await malo();
    const { data: u } = await admin.auth.admin.getUserById(id);
    const correo = u?.user?.email;
    if (!correo) return await malo();
    const anon = createClient(URL_, Deno.env.get('SUPABASE_ANON_KEY')!, { auth: { persistSession: false } });
    const { data, error } = await anon.auth.signInWithPassword({ email: correo, password: String(contrasena), options: { captchaToken: captcha ? String(captcha) : undefined } });
    if (error && /captcha/i.test(error.message)) return json({ error: 'Completa la verificación de abajo y vuelve a intentar.' }, 400);
    if (error || !data.session) return await malo();
    await admin.rpc('anotar_entrar', { p_usuario: nombre, p_ip: ip, p_ok: true });
    return json({ access_token: data.session.access_token, refresh_token: data.session.refresh_token });
  } catch (_e) {
    return json({ error: 'No se pudo entrar. Intenta de nuevo.' }, 500);
  }
});
