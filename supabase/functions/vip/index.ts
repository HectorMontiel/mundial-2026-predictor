// v383 — HACERSE VIP: crea la suscripción en Mercado Pago y devuelve su
// página de cobro (Mercado Pago pide la tarjeta: nosotros nunca la vemos).
// Precio (tabla `ajustes`): fundador $99 al mes para los primeros 50, después
// $149; semestral $749 cada 6 meses. IVA incluido.
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (d: unknown, s = 200) => new Response(JSON.stringify(d), { status: s, headers: { ...CORS, 'Content-Type': 'application/json' } });
const SITIO = 'https://sharpicks.pages.dev';

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  try {
    const URL_ = Deno.env.get('SUPABASE_URL')!;
    const MP = Deno.env.get('MP_ACCESS_TOKEN');
    if (!MP) return json({ error: 'Los pagos todavía no están activos.' }, 503);
    const yo = createClient(URL_, Deno.env.get('SUPABASE_ANON_KEY')!, {
      global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } }, auth: { persistSession: false } });
    const { data: { user } } = await yo.auth.getUser();
    if (!user) return json({ error: 'Inicia sesión para hacerte VIP.' }, 401);
    const { tipo = 'mensual', correo } = await req.json().catch(() => ({}));
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const { data: aj } = await admin.from('ajustes').select('clave,valor');
    const A: Record<string, string> = Object.fromEntries((aj ?? []).map((x) => [x.clave, x.valor]));
    const { data: lugares } = await admin.rpc('lugares_fundador');
    const semestral = tipo === 'semestral';
    const fundador = !semestral && Number(lugares ?? 0) > 0;
    const precio = Number(semestral ? A.precio_semestral ?? 749 : fundador ? A.precio_fundador ?? 99 : A.precio_mensual ?? 149);
    const pagador = String(correo || user.email || '').trim();
    if (!pagador) return json({ error: 'Falta el correo de tu cuenta de Mercado Pago.' }, 400);
    const r = await fetch('https://api.mercadopago.com/preapproval', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + MP, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reason: 'SharPicks VIP ' + (semestral ? 'semestral' : 'mensual') + (fundador ? ' (fundador)' : ''),
        external_reference: user.id,
        payer_email: pagador,
        auto_recurring: { frequency: semestral ? 6 : 1, frequency_type: 'months', transaction_amount: precio, currency_id: 'MXN' },
        back_url: SITIO + '/?vip=ok',
        status: 'pending',
      }),
    });
    const d = await r.json();
    if (!r.ok || !d.init_point) return json({ error: 'Mercado Pago: ' + (d.message || 'no se pudo crear la suscripción') }, 502);
    await admin.from('suscripciones').upsert({
      id: d.id, usuario: user.id, tipo: semestral ? 'semestral' : 'mensual', precio, fundador, estado: d.status ?? 'pending',
      actualizado: new Date().toISOString() });
    return json({ url: d.init_point, precio, fundador });
  } catch (_e) {
    return json({ error: 'No se pudo iniciar el pago. Intenta de nuevo.' }, 500);
  }
});
