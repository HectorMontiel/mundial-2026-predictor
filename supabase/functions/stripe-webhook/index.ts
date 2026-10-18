// v395 — EL AVISO DE STRIPE (webhook). Dos candados, igual que con Mercado Pago:
//   1. la FIRMA (`Stripe-Signature`, HMAC con STRIPE_WEBHOOK_SECRET): un aviso
//      que no viene de Stripe se descarta;
//   2. no se confía en lo que trae: con el id se le PREGUNTA a Stripe cómo está.
// Eventos (los 4 dados de alta en el panel):
//   checkout.session.completed → monedas pagadas (una sola vez: `acreditar_compra`)
//                                o VIP nuevo;
//   invoice.paid / customer.subscription.updated|deleted → el VIP se renueva o vence.
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';

const ok = (s = 200) => new Response('ok', { status: s });
const hex = (b: ArrayBuffer) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');

async function firmaValida(cuerpo: string, cabecera: string, secreto: string): Promise<boolean> {
  const partes = Object.fromEntries(cabecera.split(',').map((p) => p.split('=') as [string, string]).filter((x) => x.length === 2));
  const t = Number(partes.t);
  if (!t || Math.abs(Date.now() / 1000 - t) > 600) return false;           // aviso viejo o reenviado: no
  const k = await crypto.subtle.importKey('raw', new TextEncoder().encode(secreto), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const esperado = hex(await crypto.subtle.sign('HMAC', k, new TextEncoder().encode(t + '.' + cuerpo)));
  const v1 = cabecera.split(',').filter((p) => p.startsWith('v1=')).map((p) => p.slice(3));
  return v1.some((v) => {
    if (v.length !== esperado.length) return false;
    let diferencia = 0;
    for (let i = 0; i < esperado.length; i++) diferencia |= v.charCodeAt(i) ^ esperado.charCodeAt(i);
    return diferencia === 0;
  });
}

Deno.serve(async (req) => {
  const SK = Deno.env.get('STRIPE_SECRET_KEY'), WS = Deno.env.get('STRIPE_WEBHOOK_SECRET');
  if (!SK || !WS) return new Response('Webhook no configurado', { status: 503 });
  const cuerpo = await req.text();
  if (!(await firmaValida(cuerpo, req.headers.get('stripe-signature') || '', WS))) return ok(400);
  try {
    const ev = JSON.parse(cuerpo);
    const stripe = async (ruta: string) => {
      const r = await fetch('https://api.stripe.com/v1' + ruta, { headers: { Authorization: 'Bearer ' + SK } });
      return r.ok ? await r.json() : null;
    };
    const admin = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const obj = ev?.data?.object || {};
    let subId: string | null = null;

    if (ev.type === 'checkout.session.completed') {
      const s = await stripe('/checkout/sessions/' + obj.id);
      if (!s) return ok(500);                                                // Stripe reintenta
      if (s.mode === 'payment' && s.payment_status === 'paid' && s.metadata?.tipo === 'monedas') {
        const { error } = await admin.rpc('acreditar_compra', {
          p_id: 'stripe:' + s.id, p_usuario: s.metadata.usuario,
          p_paquete: s.metadata.paquete, p_precio: Number(s.amount_total ?? 0) / 100,
        });
        if (error) throw new Error('No se pudo acreditar la compra de monedas');
        return ok();
      }
      if (s.mode === 'payment' && s.payment_status === 'paid' && s.metadata?.tipo === 'vip_unico') {
        // VIP de un solo pago: se suma el periodo UNA vez (el id de la fila es el candado)
        const meses = Number(s.metadata.meses || 1);
        const { error } = await admin.rpc('procesar_vip_unico', {
          p_id: 'stripe-unico:' + s.id, p_usuario: s.metadata.usuario, p_meses: meses,
          p_precio: Number(s.amount_total ?? 0) / 100, p_fundador: s.metadata.fundador === '1',
        });
        if (error) throw new Error('No se pudo activar el VIP de pago único');
        return ok();
      }
      if (s.mode === 'subscription') subId = typeof s.subscription === 'string' ? s.subscription : s.subscription?.id;
    } else if (ev.type === 'invoice.paid') {
      // en las versiones nuevas de la API la suscripción va en `parent.subscription_details`
      subId = obj.parent?.subscription_details?.subscription || obj.subscription || null;
    } else if (ev.type === 'customer.subscription.updated' || ev.type === 'customer.subscription.deleted') {
      subId = obj.id;
    }
    if (!subId) return ok();

    const sub = await stripe('/subscriptions/' + subId);
    if (!sub) return ok(500);
    const m = sub.metadata || {};
    if (m.tipo !== 'vip' || !m.usuario) return ok();
    const item = sub.items?.data?.[0] || {};
    const fin = Number(item.current_period_end || sub.current_period_end || 0);
    const activa = sub.status === 'active' || sub.status === 'trialing';
    const sigue = activa && !sub.cancel_at_period_end;      // activa, pero ¿se volverá a cobrar?
    const { error: errorSub } = await admin.from('suscripciones').upsert({
      id: 'stripe:' + sub.id, usuario: m.usuario, tipo: m.plan === 'semestral' ? 'semestral' : 'mensual',
      precio: Number(item.price?.unit_amount ?? 0) / 100, fundador: m.fundador === '1',
      estado: sigue ? 'authorized' : activa ? 'cancela_al_final' : sub.status, renueva: sigue,
      proximo_cobro: fin ? new Date(fin * 1000).toISOString() : null,
      actualizado: new Date().toISOString() });
    if (errorSub) throw new Error('No se pudo actualizar la suscripción de Stripe');
    if (activa && fin) {
      const hasta = new Date(fin * 1000 + 3 * 864e5);                         // 3 días de gracia, como con Mercado Pago
      const { data: pf } = await admin.from('perfiles').select('plan_hasta').eq('id', m.usuario).maybeSingle();
      const actual = pf?.plan_hasta ? new Date(pf.plan_hasta) : null;
      const { error: errorPerfil } = await admin.from('perfiles')
        .update({ plan: 'pro', plan_hasta: (actual && actual > hasta ? actual : hasta).toISOString() })
        .eq('id', m.usuario);
      if (errorPerfil) throw new Error('No se pudo actualizar el periodo VIP del perfil');
    }
    return ok();
  } catch (e) {
    console.error('[sharpicks] fallo al procesar webhook de Stripe', e instanceof Error ? e.message : 'error desconocido');
    return ok(500);
  }
});
