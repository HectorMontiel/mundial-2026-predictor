// v389 — COMPRAR MONEDAS: un pago único con Mercado Pago (Checkout Pro). Se
// crea la «preferencia» del paquete y se devuelve su página de cobro; el aviso
// del pago llega a `mp-webhook`, que lo comprueba con Mercado Pago y acredita
// las monedas UNA sola vez (`acreditar_compra`). Nunca vemos la tarjeta.
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
    if (!user) return json({ error: 'Inicia sesión para comprar monedas.' }, 401);
    const { paquete } = await req.json().catch(() => ({}));
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const { data: k } = await admin.from('paquetes').select('*').eq('id', String(paquete || '')).maybeSingle();
    if (!k) return json({ error: 'Ese paquete no existe.' }, 400);
    const r = await fetch('https://api.mercadopago.com/checkout/preferences', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + MP, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: [{ id: k.id, title: 'SharPicks · ' + k.monedas + ' monedas (' + k.nombre + ')', quantity: 1,
                  unit_price: Number(k.precio), currency_id: 'MXN' }],
        external_reference: 'monedas|' + user.id + '|' + k.id,
        payer: user.email ? { email: user.email } : undefined,
        back_urls: { success: SITIO + '/?monedas=ok', pending: SITIO + '/?monedas=pendiente', failure: SITIO + '/?monedas=no' },
        auto_return: 'approved',
        notification_url: URL_ + '/functions/v1/mp-webhook',
        statement_descriptor: 'SHARPICKS',
      }),
    });
    const d = await r.json();
    if (!r.ok || !d.init_point) return json({ error: 'Mercado Pago: ' + (d.message || 'no se pudo crear el cobro') }, 502);
    return json({ url: d.init_point });
  } catch (_e) {
    return json({ error: 'No se pudo iniciar el pago. Intenta de nuevo.' }, 500);
  }
});
