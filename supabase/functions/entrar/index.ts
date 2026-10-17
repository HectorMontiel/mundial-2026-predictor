// v383 — ENTRAR CON NOMBRE DE USUARIO Y CONTRASEÑA.
// Supabase sólo sabe entrar con correo; aquí se busca el correo del usuario
// (con la clave de servicio, en el servidor: el correo nunca llega a la
// página) y se inicia la sesión. La respuesta es igual si el usuario no existe
// o la contraseña está mal, para no revelar quién tiene cuenta.
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
    const { usuario, contrasena } = await req.json();
    if (!usuario || !contrasena) return json({ error: 'Escribe tu usuario y tu contraseña.' }, 400);
    const URL_ = Deno.env.get('SUPABASE_URL')!;
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const malo = json({ error: 'Usuario o contraseña incorrectos.' }, 401);
    const { data: id } = await admin.rpc('id_de_usuario', { u: String(usuario).trim() });
    if (!id) return malo;
    const { data: u } = await admin.auth.admin.getUserById(id);
    const correo = u?.user?.email;
    if (!correo) return malo;
    const anon = createClient(URL_, Deno.env.get('SUPABASE_ANON_KEY')!, { auth: { persistSession: false } });
    const { data, error } = await anon.auth.signInWithPassword({ email: correo, password: String(contrasena) });
    if (error || !data.session) return malo;
    return json({ access_token: data.session.access_token, refresh_token: data.session.refresh_token });
  } catch (_e) {
    return json({ error: 'No se pudo entrar. Intenta de nuevo.' }, 500);
  }
});
