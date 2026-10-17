// v395 — CANCELAR O REACTIVAR LA RENOVACIÓN DEL VIP (Mercado Pago o Stripe).
// El usuario: «tiene que haber una sección de cancelar suscripción». Al cancelar,
// el VIP SIGUE hasta el final de lo ya pagado (`perfiles.plan_hasta`) y no se
// vuelve a cobrar.
//   {accion: 'cancelar'}  → Stripe: cancel_at_period_end; Mercado Pago: preapproval cancelado
//   {accion: 'reactivar'} → Stripe: vuelve a renovar (si aún no venció). Mercado Pago no
//                           permite reactivar un cancelado: se contrata de nuevo.
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
    const URL_ = Deno.env.get('SUPABASE_URL')!;
    const yo = createClient(URL_, Deno.env.get('SUPABASE_ANON_KEY')!, {
      global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } }, auth: { persistSession: false } });
    const { data: { user } } = await yo.auth.getUser();
    if (!user) return json({ error: 'Inicia sesión.' }, 401);
    const { accion = 'cancelar' } = await req.json().catch(() => ({}));
    const admin = createClient(URL_, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const { data: subs } = await admin.from('suscripciones').select('*').eq('usuario', user.id)
      .in('estado', accion === 'reactivar' ? ['cancela_al_final'] : ['authorized', 'pending'])
      .order('actualizado', { ascending: false });
    if (!subs || !subs.length) return json({ error: accion === 'reactivar' ? 'No hay nada que reactivar.' : 'No tienes una renovación activa.' }, 404);
    let hechas = 0;
    for (const s of subs) {
      if (String(s.id).startsWith('stripe:')) {
        const SK = Deno.env.get('STRIPE_SECRET_KEY');
        if (!SK) continue;
        const r = await fetch('https://api.stripe.com/v1/subscriptions/' + s.id.slice(7), {
          method: 'POST', headers: { Authorization: 'Bearer ' + SK, 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ cancel_at_period_end: accion === 'cancelar' ? 'true' : 'false' }) });
        if (!r.ok) continue;
      } else {
        if (accion === 'reactivar') continue;
        const MP = Deno.env.get('MP_ACCESS_TOKEN');
        if (!MP) continue;
        const r = await fetch('https://api.mercadopago.com/preapproval/' + s.id, {
          method: 'PUT', headers: { Authorization: 'Bearer ' + MP, 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'cancelled' }) });
        if (!r.ok) continue;
      }
      await admin.from('suscripciones').update({ estado: accion === 'cancelar' ? (String(s.id).startsWith('stripe:') ? 'cancela_al_final' : 'cancelled') : 'authorized',
                                                 renueva: accion !== 'cancelar', actualizado: new Date().toISOString() }).eq('id', s.id);
      hechas++;
    }
    if (!hechas) return json({ error: 'No se pudo cambiar. Intenta de nuevo en un momento.' }, 502);
    const { data: pf } = await admin.from('perfiles').select('plan_hasta').eq('id', user.id).maybeSingle();
    return json({ ok: true, hasta: pf?.plan_hasta ?? null });
  } catch (_e) {
    return json({ error: 'No se pudo cambiar. Intenta de nuevo.' }, 500);
  }
});
