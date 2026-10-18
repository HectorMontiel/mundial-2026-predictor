// v402 — comentarios públicos con validación del lado servidor y límite de frecuencia.
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';

const ORIGENES = new Set([
  'https://sharpicks.pages.dev',
  'https://hectormontiel.github.io',
]);
const json = (body: unknown, status = 200, origin = '') => {
  const permitido = ORIGENES.has(origin) ? origin : 'https://sharpicks.pages.dev';
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Access-Control-Allow-Origin': permitido,
      'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Vary': 'Origin',
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
};

async function sha256(s: string): Promise<string> {
  const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
}

Deno.serve(async (req) => {
  const origin = req.headers.get('origin') || '';
  if (req.method === 'OPTIONS') return json({ ok: true }, 200, origin);
  if (req.method !== 'POST') return json({ error: 'Método no permitido.' }, 405, origin);
  if (origin && !ORIGENES.has(origin)) return json({ error: 'Origen no permitido.' }, 403, origin);

  try {
    const URL_ = Deno.env.get('SUPABASE_URL');
    const ANON = Deno.env.get('SUPABASE_ANON_KEY');
    const SERVICE = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
    if (!URL_ || !ANON || !SERVICE) return json({ error: 'El servicio de comentarios no está configurado.' }, 503, origin);

    const body = await req.json().catch(() => null);
    if (!body || typeof body !== 'object') return json({ error: 'Solicitud inválida.' }, 400, origin);
    const tipo = String(body.tipo || '');
    const texto = typeof body.texto === 'string' ? body.texto.trim() : '';
    const correo = typeof body.correo === 'string' && body.correo.trim() ? body.correo.trim() : null;
    const pagina = typeof body.pagina === 'string' ? body.pagina.slice(0, 300) : null;
    if (!['idea', 'falla', 'otro'].includes(tipo) || texto.length < 3 || texto.length > 2000
      || (correo !== null && correo.length > 200)) {
      return json({ error: 'Revisa el tipo, el texto y el correo.' }, 400, origin);
    }

    // La IP nunca se guarda en claro. Si el proxy no la entrega, fallamos
    // de forma explícita en vez de desactivar silenciosamente el límite.
    const forwarded = req.headers.get('cf-connecting-ip')
      || req.headers.get('x-real-ip')
      || req.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
      || '';
    if (!forwarded) return json({ error: 'No pudimos validar el origen. Intenta de nuevo.' }, 503, origin);
    const huella = await sha256((Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || SERVICE) + ':' + forwarded);

    // Los comentarios pueden ser anónimos; si viene una sesión real la
    // verificamos con Supabase y no confiamos en un user_id enviado por la web.
    let usuario: string | null = null;
    const authorization = req.headers.get('authorization') || '';
    const token = authorization.replace(/^Bearer\s+/i, '');
    // La web usa una clave sb_publishable_...; no es un access token de usuario.
    const esClavePublica = token === ANON || token.startsWith('sb_publishable_');
    if (token && !esClavePublica) {
      const authClient = createClient(URL_, ANON, {
        global: { headers: { Authorization: authorization } },
        auth: { persistSession: false, autoRefreshToken: false },
      });
      const { data, error } = await authClient.auth.getUser();
      if (error || !data.user) return json({ error: 'La sesión ya no es válida. Entra de nuevo.' }, 401, origin);
      usuario = data.user.id;
    }

    const admin = createClient(URL_, SERVICE, { auth: { persistSession: false, autoRefreshToken: false } });
    const { data, error } = await admin.rpc('registrar_comentario', {
      p_fingerprint: huella, p_tipo: tipo, p_texto: texto,
      p_correo: correo, p_pagina: pagina, p_usuario: usuario,
    });
    if (error) {
      console.error('[sharpicks] falló el registro de comentario', error.code || 'sin código');
      return json({ error: 'No se pudo guardar el comentario. Intenta de nuevo.' }, 500, origin);
    }
    if (data?.reason === 'rate_limit') return json({ error: 'Has enviado varios comentarios recientemente. Espera un rato y vuelve a intentarlo.' }, 429, origin);
    if (!data?.ok) return json({ error: 'El comentario no pasó la validación.' }, 400, origin);
    return json({ ok: true }, 201, origin);
  } catch (_e) {
    return json({ error: 'No se pudo guardar el comentario. Intenta de nuevo.' }, 500, origin);
  }
});
