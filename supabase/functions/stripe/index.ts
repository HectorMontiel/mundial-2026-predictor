// v395 — COBRAR CON STRIPE (además de Mercado Pago): tarjeta, Apple Pay y
// Google Pay en la página de cobro de Stripe. Nunca vemos la tarjeta.
//   {accion: 'monedas', paquete}         → pago único de un paquete de monedas
//   {accion: 'vip', tipo: 'mensual'|'semestral', renovar} → VIP; con renovar=false
//        se paga UNA vez ese periodo y no se vuelve a cobrar (el usuario lo elige)
//   {accion: 'portal'}                   → el portal de Stripe para cancelar o cambiar la tarjeta
// Lo que se paga lo acredita `stripe-webhook` (comprobando la firma y
// volviendo a preguntarle a Stripe), igual que `mp-webhook` con Mercado Pago.
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (d: unknown, s = 200) => new Response(JSON.stringify(d), { status: s, headers: { ...CORS, 'Content-Type': 'application/json' } });
const SITIO = 'https://sharpicks.pages.dev';

// la API de Stripe va en formulario (a[b][c]=valor)
function formulario(o: Record<string, unknown>, pre = '', out = new URLSearchParams()) {
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null) continue;
    const clave = pre ? pre + '[' + k + ']' : k;
    if (typeof v === 'object') formulario(v as Record<string, unknown>, clave, out);
    else out.append(clave, String(v));
  }
  return out;
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  try {
    const URL_ = Deno.env.get('SUPABASE_URL')!;
    const SK = Deno.env.get('STRIPE_SECRET_KEY');
    if (!SK) return json({ error: 'El pago con tarjeta y Apple Pay todavía no está activo.' }, 503);
    const stripe = async (ruta: string, cuerpo?: Record<string, unknown>) => {
      const r = await fetch('https://api.stripe.com/v1' + ruta, {
        method: cuerpo ? 'POST' : 'GET',
        headers: { Authorization: 'Bearer ' + SK, 'Content-Type': 'application/x-www-form-urlencoded' },
        body: cuerpo ? formulario(cuerpo) : undefined,
      });
      return { ok: r.ok, d: await r.json() };
    };
    const yo = createClient(URL_, Deno.env.get('SUPABASE_ANON_KEY')!, {
      global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } }, auth: { persistSession: false } });
    const { data: { user } } = await yo.auth.getUser();
    if (!user) return json({ error: 'Inicia sesión para pagar.' }, 401);
    const { accion = 'monedas', paquete, tipo = 'mensual', renovar = true } = await req.json().catch(() => ({}));
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const base = {
      client_reference_id: user.id,
      customer_email: user.email || undefined,
      // tarjeta: incluye Apple Pay y Google Pay (OXXO y SPEI van por Mercado Pago)
      payment_method_types: { 0: 'card' },
      locale: 'es-419',
    };

    if (accion === 'monedas') {
      const { data: k } = await admin.from('paquetes').select('*').eq('id', String(paquete || '')).maybeSingle();
      if (!k) return json({ error: 'Ese paquete no existe.' }, 400);
      const meta = { tipo: 'monedas', usuario: user.id, paquete: k.id };
      const { ok, d } = await stripe('/checkout/sessions', {
        ...base, mode: 'payment', metadata: meta, payment_intent_data: { metadata: meta, statement_descriptor_suffix: 'MONEDAS' },
        line_items: { 0: { quantity: 1, price_data: { currency: 'mxn', unit_amount: Math.round(Number(k.precio) * 100),
          product_data: { name: 'SharPicks · ' + k.monedas + ' monedas' } } } },
        success_url: SITIO + '/?monedas=ok', cancel_url: SITIO + '/?monedas=no',
      });
      if (!ok || !d.url) return json({ error: 'Stripe: ' + (d?.error?.message || 'no se pudo crear el cobro') }, 502);
      return json({ url: d.url });
    }

    if (accion === 'vip') {
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
      const meta = { tipo: 'vip', usuario: user.id, plan: semestral ? 'semestral' : 'mensual', fundador: fundador ? '1' : '0' };
      if (!renovar) {
        // pago único: el periodo y nada más (sin cobros automáticos)
        const unico = { ...meta, tipo: 'vip_unico', meses: semestral ? '6' : '1' };
        const { ok, d } = await stripe('/checkout/sessions', {
          ...base, mode: 'payment', metadata: unico, payment_intent_data: { metadata: unico },
          line_items: { 0: { quantity: 1, price_data: { currency: 'mxn', unit_amount: Math.round(precio * 100),
            product_data: { name: 'SharPicks VIP ' + (semestral ? '6 meses' : '1 mes') + ' (sin renovación automática)' } } } },
          success_url: SITIO + '/?vip=ok', cancel_url: SITIO + '/?vip=no',
        });
        if (!ok || !d.url) return json({ error: 'Stripe: ' + (d?.error?.message || 'no se pudo crear el cobro') }, 502);
        return json({ url: d.url, precio, fundador });
      }
      const { ok, d } = await stripe('/checkout/sessions', {
        ...base, mode: 'subscription', metadata: meta, subscription_data: { metadata: meta },
        line_items: { 0: { quantity: 1, price_data: { currency: 'mxn', unit_amount: Math.round(precio * 100),
          recurring: { interval: 'month', interval_count: semestral ? 6 : 1 },
          product_data: { name: 'SharPicks VIP ' + (semestral ? 'semestral' : 'mensual') + (fundador ? ' (fundador)' : '') } } } },
        success_url: SITIO + '/?vip=ok', cancel_url: SITIO + '/?vip=no',
      });
      if (!ok || !d.url) return json({ error: 'Stripe: ' + (d?.error?.message || 'no se pudo crear la suscripción') }, 502);
      return json({ url: d.url, precio, fundador });
    }

    if (accion === 'portal') {
      const { data: s } = await admin.from('suscripciones').select('id').eq('usuario', user.id).like('id', 'stripe:%')
        .order('actualizado', { ascending: false }).limit(1).maybeSingle();
      if (!s) return json({ error: 'No tienes una suscripción pagada con Stripe.' }, 404);
      const sub = await stripe('/subscriptions/' + s.id.slice('stripe:'.length));
      const cliente = sub.d?.customer;
      if (!cliente) return json({ error: 'No se encontró tu suscripción en Stripe.' }, 404);
      const { ok, d } = await stripe('/billing_portal/sessions', { customer: cliente, return_url: SITIO + '/' });
      if (!ok || !d.url) return json({ error: 'Stripe: ' + (d?.error?.message || 'no se pudo abrir el portal') }, 502);
      return json({ url: d.url });
    }
    return json({ error: 'Acción desconocida.' }, 400);
  } catch (_e) {
    return json({ error: 'No se pudo iniciar el pago. Intenta de nuevo.' }, 500);
  }
});
