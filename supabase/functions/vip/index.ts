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
    const { tipo = 'mensual', correo, renovar = true } = await req.json().catch(() => ({}));
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const { data: aj } = await admin.from('ajustes').select('clave,valor');
    const A: Record<string, string> = Object.fromEntries((aj ?? []).map((x) => [x.clave, x.valor]));
    const semestral = tipo === 'semestral';
    let fundador = false;
    if (!semestral) {
      const { data: reservado, error: errorReserva } = await admin.rpc('reservar_lugar_fundador', {
        p_id: 'reserva:' + crypto.randomUUID(),
        p_usuario: user.id,
        p_precio: Number(A.precio_fundador ?? 99),
      });
      if (errorReserva) throw new Error('No se pudo reservar una plaza fundador');
      fundador = reservado === true;
    }
    const precio = Number(semestral ? A.precio_semestral ?? 749 : fundador ? A.precio_fundador ?? 99 : A.precio_mensual ?? 149);
    if (!renovar) {
      // v395 — el usuario eligió NO renovar: un solo pago por ese periodo (Checkout Pro)
      const meses = semestral ? 6 : 1;
      const r1 = await fetch('https://api.mercadopago.com/checkout/preferences', {
        method: 'POST', headers: { Authorization: 'Bearer ' + MP, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: [{ id: 'vip-' + meses, title: 'SharPicks VIP ' + (semestral ? '6 meses' : '1 mes') + ' (sin renovación automática)',
                    quantity: 1, unit_price: precio, currency_id: 'MXN' }],
          external_reference: 'vip|' + user.id + '|' + meses + '|' + (fundador ? '1' : '0'),
          back_urls: { success: SITIO + '/?vip=ok', pending: SITIO + '/?vip=pendiente', failure: SITIO + '/?vip=no' },
          auto_return: 'approved', notification_url: URL_ + '/functions/v1/mp-webhook', statement_descriptor: 'SHARPICKS',
        }),
      });
      const d1 = await r1.json();
      if (!r1.ok || !d1.init_point) return json({ error: 'Mercado Pago: ' + (d1.message || 'no se pudo crear el cobro') }, 502);
      return json({ url: d1.init_point, precio, fundador });
    }
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
      id: d.id, usuario: user.id, tipo: semestral ? 'semestral' : 'mensual', precio, fundador, estado: d.status ?? 'pending', renueva: true,
      actualizado: new Date().toISOString() });
    return json({ url: d.init_point, precio, fundador });
  } catch (_e) {
    return json({ error: 'No se pudo iniciar el pago. Intenta de nuevo.' }, 500);
  }
});
